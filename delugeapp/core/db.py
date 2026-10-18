# -*- coding: utf-8 -*-
"""Index SQLite de la carte SD.

Parcourir la carte prend des dizaines de secondes ; l'interface, elle, doit
répondre à chaque frappe dans un champ de recherche. Tout ce qui a été lu sur
la carte est donc conservé ici, et les pages n'interrogent plus que cette base.

La base est un simple fichier dans le dossier de configuration : on peut la
supprimer sans rien perdre d'autre que le temps d'une nouvelle analyse.

Conventions :

* les chemins sont stockés **en relatif, séparateur ``/``**, tels que le Deluge
  les écrit, et doublés d'une colonne normalisée (minuscules) pour les
  comparaisons insensibles à la casse (cf. SPEC §0.4 et §0.5) ;
* ``kind`` vaut ``'sample'``, ``'synth'``, ``'kit'`` ou ``'song'``.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any, Sequence

from .sdcard import norm_rel

log = logging.getLogger(__name__)

#: Version du schéma ; une valeur différente dans ``meta`` déclenche une remise à neuf.
SCHEMA_VERSION = "4"

#: Natures d'éléments indexés.
KINDS = ("sample", "synth", "kit", "song")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS samples (
    id       INTEGER PRIMARY KEY,
    rel      TEXT UNIQUE,
    rel_norm TEXT,
    name     TEXT,
    folder   TEXT,
    ext      TEXT,
    size     INTEGER,
    mtime    REAL,
    sr       INTEGER,
    channels INTEGER,
    bit_depth INTEGER,
    frames   INTEGER,
    duration REAL,
    hash      TEXT,
    hash_full TEXT DEFAULT '',
    peak     REAL,
    rms      REAL,
    dc_offset REAL,
    clipped  REAL,
    bpm      REAL,
    key      TEXT,
    category TEXT,
    -- Descripteurs acoustiques, pour la recherche par ressemblance
    -- (cf. core/similarity.py). Nuls tant que l'analyse n'a pas tourné.
    centroid  REAL,
    rolloff   REAL,
    flatness  REAL,
    bandwidth REAL,
    low_ratio  REAL,
    high_ratio REAL,
    crest    REAL,
    attack   REAL,
    used_count INTEGER DEFAULT 0,
    ok       INTEGER DEFAULT 1,
    error    TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS presets (
    id       INTEGER PRIMARY KEY,
    rel      TEXT UNIQUE,
    rel_norm TEXT,
    kind     TEXT,
    name     TEXT,
    folder   TEXT,
    size     INTEGER,
    mtime    REAL,
    firmware TEXT,
    mode     TEXT,
    category TEXT,
    osc1     TEXT,
    osc2     TEXT,
    filter   TEXT,
    fx       TEXT,
    uses_samples INTEGER DEFAULT 0,
    summary  TEXT,
    repaired TEXT DEFAULT '',
    ok       INTEGER DEFAULT 1,
    error    TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS songs (
    id       INTEGER PRIMARY KEY,
    rel      TEXT UNIQUE,
    rel_norm TEXT,
    name     TEXT,
    size     INTEGER,
    mtime    REAL,
    firmware TEXT,
    tempo    REAL,
    scale    TEXT,
    clips    INTEGER,
    notes    INTEGER,
    bars     REAL,
    instruments INTEGER,
    preview  TEXT,
    repaired TEXT DEFAULT '',
    ok       INTEGER DEFAULT 1,
    error    TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS links (
    src_kind TEXT,
    src_rel  TEXT,
    dst_rel  TEXT,
    dst_norm TEXT,
    missing  INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS tags (
    id    INTEGER PRIMARY KEY,
    name  TEXT UNIQUE,
    color TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS item_tags (
    kind   TEXT,
    rel    TEXT,
    tag_id INTEGER,
    UNIQUE(kind, rel, tag_id)
);
CREATE TABLE IF NOT EXISTS ratings (
    kind     TEXT,
    rel      TEXT,
    stars    INTEGER DEFAULT 0,
    favorite INTEGER DEFAULT 0,
    notes    TEXT DEFAULT '',
    PRIMARY KEY (kind, rel)
);
"""

#: Index, créés APRÈS la migration : un index sur une colonne encore
#: absente d'une base ancienne ferait échouer tout le script.
_SCHEMA_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_links_dst     ON links(dst_norm);
CREATE INDEX IF NOT EXISTS idx_links_src     ON links(src_kind, src_rel);
CREATE INDEX IF NOT EXISTS idx_samples_hash  ON samples(hash);
CREATE INDEX IF NOT EXISTS idx_samples_hashf ON samples(hash_full);
CREATE INDEX IF NOT EXISTS idx_samples_folder ON samples(folder);
CREATE INDEX IF NOT EXISTS idx_samples_norm  ON samples(rel_norm);
CREATE INDEX IF NOT EXISTS idx_samples_cat   ON samples(category);
CREATE INDEX IF NOT EXISTS idx_presets_kind  ON presets(kind, folder);
CREATE INDEX IF NOT EXISTS idx_presets_norm  ON presets(rel_norm);
CREATE INDEX IF NOT EXISTS idx_item_tags     ON item_tags(kind, rel);
"""

#: Colonnes acceptées par chaque table, pour filtrer les dictionnaires reçus.
_COLUMNS: dict[str, tuple[str, ...]] = {
    "samples": (
        "rel", "rel_norm", "name", "folder", "ext", "size", "mtime", "sr",
        "channels", "bit_depth", "frames", "duration", "hash", "hash_full",
        "peak", "rms", "dc_offset", "clipped", "bpm", "key", "category",
        "centroid", "rolloff", "flatness", "bandwidth", "low_ratio",
        "high_ratio", "crest", "attack",
        "used_count", "ok", "error",
    ),
    "presets": (
        "rel", "rel_norm", "kind", "name", "folder", "size", "mtime",
        "firmware", "mode", "category", "osc1", "osc2", "filter", "fx",
        "uses_samples", "summary", "repaired", "ok", "error",
    ),
    "songs": (
        "rel", "rel_norm", "name", "size", "mtime", "firmware", "tempo",
        "scale", "clips", "notes", "bars", "instruments", "preview",
        "repaired", "ok", "error",
    ),
}


def _escape_like(text: str) -> str:
    """Neutralise les jokers SQL d'un texte de recherche saisi par l'utilisateur."""
    return (text.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_"))


class _Resultat:
    """Résultat d'une requête, déjà lu, donc lisible hors du verrou."""

    __slots__ = ("_rows", "lastrowid", "rowcount")

    def __init__(self, rows, lastrowid=None, rowcount=-1) -> None:
        self._rows = rows
        self.lastrowid = lastrowid
        self.rowcount = rowcount

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchmany(self, size: int = 1):
        return list(self._rows[:max(0, int(size))])

    def __iter__(self):
        return iter(self._rows)

    def __len__(self) -> int:
        return len(self._rows)


class _ConnexionVerrouillee:
    """Connexion SQLite protégée par un verrou.

    **``check_same_thread=False`` ne rend pas une connexion sûre** : il
    désactive seulement la vérification de Python. Deux fils qui lisent la
    même connexion en même temps obtiennent « bad parameter or other API
    misuse » et des lignes tronquées — mesuré sur trois fils et le
    diagnostic de santé, qui rendait alors un rapport incomplet en silence.

    Le verrou couvre l'exécution **et** la lecture du curseur : le relâcher
    entre les deux laisserait la même fenêtre de course. Le résultat est donc
    matérialisé, ce que le code appelant fait de toute façon.
    """

    def __init__(self, con: sqlite3.Connection,
                 lock: threading.RLock) -> None:
        self._con = con
        self._lock = lock

    # -- requêtes ---------------------------------------------------------- #

    def execute(self, sql: str, parameters=()) -> _Resultat:
        with self._lock:
            cur = self._con.execute(sql, parameters)
            try:
                rows = cur.fetchall()
            except sqlite3.Error:
                rows = []              # ordre sans résultat : INSERT, PRAGMA…
            return _Resultat(rows, cur.lastrowid, cur.rowcount)

    def executemany(self, sql: str, seq) -> _Resultat:
        with self._lock:
            cur = self._con.executemany(sql, seq)
            return _Resultat([], cur.lastrowid, cur.rowcount)

    def executescript(self, script: str) -> _Resultat:
        with self._lock:
            cur = self._con.executescript(script)
            return _Resultat([], cur.lastrowid, cur.rowcount)

    # -- transaction et cycle de vie --------------------------------------- #

    def commit(self) -> None:
        with self._lock:
            self._con.commit()

    def rollback(self) -> None:
        with self._lock:
            self._con.rollback()

    def close(self) -> None:
        with self._lock:
            self._con.close()

    @property
    def in_transaction(self) -> bool:
        with self._lock:
            return self._con.in_transaction

    @property
    def row_factory(self):
        return self._con.row_factory

    @row_factory.setter
    def row_factory(self, value) -> None:
        with self._lock:
            self._con.row_factory = value

    @property
    def raw(self) -> sqlite3.Connection:
        """La vraie connexion, pour un besoin que le proxy ne couvre pas.

        À n'utiliser que sous ``library.lock``, sans quoi la protection
        tombe.
        """
        return self._con


class Library:
    """Accès à l'index SQLite de la carte.

    **L'objet est sûr entre fils d'exécution.** La connexion unique est
    protégée par un verrou réentrant : l'interface peut interroger l'index
    pendant qu'un fil de travail l'écrit. Ce n'était pas le cas, et cela se
    voyait — le diagnostic de santé lancé dans un fil pendant que le tableau
    de bord lisait la même base rendait un rapport amputé, sans erreur
    visible.
    """

    def __init__(self, db_path: Path) -> None:
        self.path = Path(db_path)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            log.warning("dossier de base de données inaccessible (%s) : %s",
                        self.path.parent, exc)
        #: Verrou de la connexion. Public : un appelant qui a besoin de
        #: plusieurs requêtes **indivisibles** le prend lui-même.
        self.lock = threading.RLock()
        brute = sqlite3.connect(str(self.path), check_same_thread=False)
        brute.row_factory = sqlite3.Row
        self.con = _ConnexionVerrouillee(brute, self.lock)
        # WAL : l'interface peut lire pendant que l'analyse écrit.
        for pragma in ("journal_mode=WAL", "synchronous=NORMAL",
                       "temp_store=MEMORY", "cache_size=-16000"):
            try:
                self.con.execute(f"PRAGMA {pragma}")
            except sqlite3.Error as exc:
                log.debug("PRAGMA %s refusé : %s", pragma, exc)
        self.init_db()

    # -- cycle de vie ------------------------------------------------------ #

    def init_db(self) -> None:
        """Crée les tables manquantes et met le schéma à niveau.

        ``CREATE TABLE IF NOT EXISTS`` ne touche pas à une table déjà
        présente : une base créée par une version antérieure garderait donc
        ses anciennes colonnes, et toute insertion citant une colonne neuve
        échouerait. La mise à niveau passe par :meth:`_migrate`, qui ajoute
        les colonnes manquantes **sans perdre les données**.
        """
        try:
            self.con.executescript(_SCHEMA)
            self.con.commit()
        except sqlite3.Error as exc:
            log.error("création du schéma impossible : %s", exc)
            raise

        self._migrate()

        try:
            self.con.executescript(_SCHEMA_INDEXES)
            self.con.commit()
        except sqlite3.Error as exc:
            log.error("création des index impossible : %s", exc)
            raise

        current = self.get_meta("schema_version")
        if current is None:
            self.set_meta("schema_version", SCHEMA_VERSION)
        elif current != SCHEMA_VERSION:
            log.info("index mis à niveau du schéma %s vers %s",
                     current, SCHEMA_VERSION)
            # Les colonnes neuves sont vides : il faut réanalyser la carte
            # pour les remplir, mais rien n'est perdu entre-temps.
            self.set_meta("schema_version", SCHEMA_VERSION)
            self.set_meta("needs_rescan", "1")

    #: Colonnes ajoutées après coup, avec leur déclaration SQL.
    _ADDED_COLUMNS: dict[str, dict[str, str]] = {
        "samples": {
            "rel_norm": "TEXT",
            "hash_full": "TEXT DEFAULT ''",
            "dc_offset": "REAL",
            "clipped": "REAL",
            # Schéma 4 : descripteurs acoustiques. Ajoutés par ALTER TABLE,
            # donc une base existante garde ses tags, notes et favoris ; les
            # colonnes restent nulles jusqu'à la prochaine analyse.
            "centroid": "REAL",
            "rolloff": "REAL",
            "flatness": "REAL",
            "bandwidth": "REAL",
            "low_ratio": "REAL",
            "high_ratio": "REAL",
            "crest": "REAL",
            "attack": "REAL",
        },
        "presets": {"rel_norm": "TEXT", "repaired": "TEXT DEFAULT ''"},
        "songs": {"rel_norm": "TEXT", "repaired": "TEXT DEFAULT ''"},
    }

    def _migrate(self) -> None:
        """Ajoute les colonnes absentes d'une base plus ancienne."""
        for table, columns in self._ADDED_COLUMNS.items():
            try:
                present = {row["name"] for row in
                           self.con.execute(f"PRAGMA table_info({table})")}
            except sqlite3.Error as exc:
                log.debug("inspection de %s impossible : %s", table, exc)
                continue
            if not present:
                continue
            for name, declaration in columns.items():
                if name in present:
                    continue
                try:
                    self.con.execute(
                        f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")
                    log.info("colonne %s.%s ajoutée", table, name)
                except sqlite3.Error as exc:
                    log.error("ajout de %s.%s impossible : %s",
                              table, name, exc)
        try:
            self.con.commit()
        except sqlite3.Error:
            pass

    @property
    def needs_rescan(self) -> bool:
        """Vrai si une mise à niveau du schéma réclame une nouvelle analyse."""
        return self.get_meta("needs_rescan") == "1"

    def clear_rescan_flag(self) -> None:
        """Oublie la demande de réanalyse, une fois celle-ci faite."""
        self.set_meta("needs_rescan", "0")

    def close(self) -> None:
        """Ferme la connexion (sans lever si elle l'est déjà)."""
        try:
            self.con.commit()
        except sqlite3.Error:
            pass
        try:
            self.con.close()
        except sqlite3.Error:
            pass

    def clear(self) -> None:
        """Vide l'index, en conservant tags, notes et favoris de l'utilisateur.

        Ces données-là sont saisies à la main : une nouvelle analyse de la carte
        ne doit jamais les effacer.
        """
        try:
            for table in ("samples", "presets", "songs", "links"):
                self.con.execute(f"DELETE FROM {table}")
            self.con.commit()
        except sqlite3.Error as exc:
            log.error("remise à zéro de l'index impossible : %s", exc)

    def clear_all(self) -> None:
        """Vide tout, y compris les tags, notes et favoris."""
        try:
            for table in ("samples", "presets", "songs", "links",
                          "item_tags", "tags", "ratings"):
                self.con.execute(f"DELETE FROM {table}")
            self.con.commit()
        except sqlite3.Error as exc:
            log.error("remise à zéro complète impossible : %s", exc)

    def vacuum(self) -> None:
        """Compacte le fichier de base après un gros nettoyage."""
        try:
            self.con.execute("VACUUM")
        except sqlite3.Error as exc:
            log.debug("VACUUM refusé : %s", exc)

    # -- transactions ------------------------------------------------------ #

    def begin(self) -> None:
        """Ouvre une transaction : indispensable pour insérer en masse."""
        try:
            if not self.con.in_transaction:
                self.con.execute("BEGIN")
        except sqlite3.Error as exc:
            log.debug("BEGIN refusé : %s", exc)

    def commit(self) -> None:
        """Valide la transaction courante."""
        try:
            self.con.commit()
        except sqlite3.Error as exc:
            log.error("validation impossible : %s", exc)

    # -- métadonnées ------------------------------------------------------- #

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        """Valeur de la clé ``key`` dans la table ``meta``."""
        try:
            row = self.con.execute(
                "SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        except sqlite3.Error as exc:
            log.debug("lecture meta %r impossible : %s", key, exc)
            return default
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        """Écrit une valeur dans la table ``meta``."""
        try:
            self.con.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)))
            self.con.commit()
        except sqlite3.Error as exc:
            log.debug("écriture meta %r impossible : %s", key, exc)

    # -- insertion / mise à jour ------------------------------------------- #

    def _upsert(self, table: str, row: dict) -> None:
        """Insère ou met à jour une ligne, en ne gardant que les colonnes connues."""
        rel = str(row.get("rel") or "").replace("\\", "/").strip("/")
        if not rel:
            log.debug("ligne sans chemin ignorée pour %s", table)
            return
        data = {k: v for k, v in row.items() if k in _COLUMNS[table]}
        data["rel"] = rel
        data["rel_norm"] = norm_rel(rel)

        cols = list(data)
        placeholders = ", ".join("?" for _ in cols)
        updates = ", ".join(f"{c} = excluded.{c}" for c in cols if c != "rel")
        sql = (f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) "
               f"ON CONFLICT(rel) DO UPDATE SET {updates}")
        try:
            self.con.execute(sql, [data[c] for c in cols])
        except sqlite3.Error as exc:
            log.debug("insertion impossible dans %s pour %r : %s", table, rel, exc)

    def upsert_sample(self, row: dict) -> None:
        """Enregistre un échantillon."""
        self._upsert("samples", row)

    def upsert_preset(self, row: dict) -> None:
        """Enregistre un preset de synthé ou un kit."""
        self._upsert("presets", row)

    def upsert_song(self, row: dict) -> None:
        """Enregistre un morceau."""
        self._upsert("songs", row)

    def replace_links(self, src_kind: str, src_rel: str,
                      dsts: list[tuple[str, bool]]) -> None:
        """Remplace les dépendances déclarées par un fichier source.

        ``dsts`` est une liste de ``(chemin_echantillon, manquant)``.
        """
        src_rel = str(src_rel or "").replace("\\", "/").strip("/")
        try:
            self.con.execute(
                "DELETE FROM links WHERE src_kind = ? AND src_rel = ?",
                (src_kind, src_rel))
            if dsts:
                self.con.executemany(
                    "INSERT INTO links(src_kind, src_rel, dst_rel, dst_norm, "
                    "missing) VALUES (?, ?, ?, ?, ?)",
                    [(src_kind, src_rel, dst, norm_rel(dst), 1 if missing else 0)
                     for dst, missing in dsts])
        except sqlite3.Error as exc:
            log.debug("écriture des dépendances de %r impossible : %s",
                      src_rel, exc)

    def forget(self, kind: str, rel: str) -> None:
        """Retire un élément de l'index (fichier disparu de la carte)."""
        table = {"sample": "samples", "song": "songs"}.get(kind, "presets")
        try:
            self.con.execute(f"DELETE FROM {table} WHERE rel = ?", (rel,))
            self.con.execute(
                "DELETE FROM links WHERE src_rel = ? OR dst_rel = ?", (rel, rel))
        except sqlite3.Error as exc:
            log.debug("suppression de %r impossible : %s", rel, exc)

    def purge_absent(self, kind: str, present: list[str]) -> int:
        """Retire de l'index les fichiers ``kind`` absents de ``present``.

        Les références d'autres fichiers vers un échantillon retiré sont
        **gardées** et marquées cassées : ce sont précisément celles que le
        diagnostic doit signaler. Retourne le nombre de lignes retirées.
        """
        keep = {str(r).replace("\\", "/").strip("/") for r in present}
        gone = [rel for rel in self.known_files(kind) if rel not in keep]
        table = {"sample": "samples", "song": "songs"}.get(kind, "presets")
        try:
            for rel in gone:
                self.con.execute(f"DELETE FROM {table} WHERE rel = ?", (rel,))
                if kind == "sample":
                    self.con.execute(
                        "UPDATE links SET missing = 1 WHERE dst_norm = ?",
                        (norm_rel(rel),))
                else:
                    self.con.execute(
                        "DELETE FROM links WHERE src_kind = ? AND src_rel = ?",
                        (kind, rel))
                # Favoris et étiquettes restent : ils sont le travail de
                # l'utilisateur, et le fichier peut revenir (autre carte
                # analysée avec le même index, dossier recopié).
            self.con.commit()
        except sqlite3.Error as exc:
            log.debug("purge de l'index (%s) impossible : %s", kind, exc)
        return len(gone)

    def refresh_missing_links(self) -> None:
        """Une référence vers un échantillon revenu n'est plus cassée.

        Un preset inchangé n'est pas relu par l'analyse incrémentale : sans
        ce rattrapage, il restait « cassé » après qu'on eut recopié
        l'échantillon manquant.
        """
        try:
            self.con.execute(
                "UPDATE links SET missing = 0 WHERE missing = 1 AND dst_norm "
                "IN (SELECT rel_norm FROM samples)")
            self.con.commit()
        except sqlite3.Error as exc:
            log.debug("mise à jour des références impossible : %s", exc)

    def move(self, kind: str, old_rel: str, new_rel: str) -> None:
        """Suit un fichier déplacé ou renommé sur la carte.

        Sans cela, l'index gardait l'ancien chemin jusqu'à la prochaine
        analyse : le diagnostic relancé juste après un rangement montrait
        encore les anomalies qu'on venait de corriger, et un favori ou une
        étiquette restaient attachés à un chemin vide.
        """
        old = str(old_rel or "").replace("\\", "/").strip("/")
        new = str(new_rel or "").replace("\\", "/").strip("/")
        if not old or not new or old == new:
            return
        table = {"sample": "samples", "song": "songs"}.get(kind, "presets")
        name = Path(new).stem
        try:
            if table == "songs":
                self.con.execute(
                    "UPDATE songs SET rel = ?, rel_norm = ?, name = ? "
                    "WHERE rel = ?", (new, norm_rel(new), name, old))
            else:
                self.con.execute(
                    f"UPDATE {table} SET rel = ?, rel_norm = ?, name = ?, "
                    f"folder = ? WHERE rel = ?",
                    (new, norm_rel(new), name, str(Path(new).parent).replace(
                        "\\", "/"), old))
            self.con.execute("UPDATE links SET src_rel = ? WHERE src_rel = ?",
                             (new, old))
            self.con.execute(
                "UPDATE links SET dst_rel = ?, dst_norm = ? WHERE dst_norm = ?",
                (new, norm_rel(new), norm_rel(old)))
            for appreciation in ("ratings", "item_tags"):
                self.con.execute(
                    f"UPDATE OR IGNORE {appreciation} SET rel = ? WHERE rel = ?",
                    (new, old))
        except sqlite3.Error as exc:
            log.debug("déplacement de %r dans l'index impossible : %s", old, exc)

    def retarget_links(self, old_rel: str, new_rel: str) -> None:
        """Les références à ``old_rel`` pointent désormais vers ``new_rel``."""
        try:
            self.con.execute(
                "UPDATE links SET dst_rel = ?, dst_norm = ?, missing = 0 "
                "WHERE dst_norm = ?",
                (str(new_rel), norm_rel(new_rel), norm_rel(old_rel)))
        except sqlite3.Error as exc:
            log.debug("réaffectation de %r dans l'index impossible : %s",
                      old_rel, exc)

    def known_files(self, kind: str) -> dict[str, tuple[int, float]]:
        """``{chemin: (taille, mtime)}`` déjà indexés, pour l'analyse incrémentale."""
        if kind == "sample":
            sql = "SELECT rel, size, mtime FROM samples"
            args: tuple = ()
        elif kind == "song":
            sql = "SELECT rel, size, mtime FROM songs"
            args = ()
        else:
            sql = "SELECT rel, size, mtime FROM presets WHERE kind = ?"
            args = (kind,)
        try:
            rows = self.con.execute(sql, args).fetchall()
        except sqlite3.Error as exc:
            log.debug("lecture de l'index (%s) impossible : %s", kind, exc)
            return {}
        return {r["rel"]: (r["size"] or 0, r["mtime"] or 0.0) for r in rows}

    # -- recherche ---------------------------------------------------------- #

    def _query(self, sql: str, args: Sequence[Any]) -> list[sqlite3.Row]:
        """Exécute une requête de lecture sans jamais lever."""
        try:
            return self.con.execute(sql, list(args)).fetchall()
        except sqlite3.Error as exc:
            log.error("requête en échec : %s", exc)
            return []

    def search_samples(self, text: str = "", folder: str = "",
                       category: str = "", tag: str = "",
                       min_dur: float = 0, max_dur: float = 0,
                       only_unused: bool = False, only_missing: bool = False,
                       favorite: bool = False,
                       limit: int = 5000) -> list[sqlite3.Row]:
        """Échantillons correspondant aux critères, les plus récents d'abord.

        ``only_missing`` cherche les échantillons *référencés mais absents* :
        ils ne sont pas dans ``samples`` mais dans ``links``, c'est pourquoi la
        requête change complètement dans ce cas.
        """
        if only_missing:
            return self._query(
                "SELECT DISTINCT dst_rel AS rel, dst_rel AS name, "
                "       src_kind, src_rel "
                "FROM links WHERE missing = 1 "
                "ORDER BY dst_rel LIMIT ?", (int(limit),))

        where = ["1=1"]
        args: list[Any] = []
        if text:
            where.append("(s.name LIKE ? ESCAPE '\\' OR s.rel LIKE ? ESCAPE '\\')")
            like = f"%{_escape_like(text)}%"
            args += [like, like]
        if folder:
            where.append("(s.folder = ? OR s.folder LIKE ? ESCAPE '\\')")
            args += [folder, f"{_escape_like(folder)}/%"]
        if category:
            where.append("s.category = ?")
            args.append(category)
        if min_dur:
            where.append("s.duration >= ?")
            args.append(float(min_dur))
        if max_dur:
            where.append("s.duration <= ?")
            args.append(float(max_dur))
        if only_unused:
            where.append("s.used_count = 0")

        joins = ""
        if tag:
            joins += (" JOIN item_tags it ON it.kind = 'sample' AND it.rel = s.rel"
                      " JOIN tags t ON t.id = it.tag_id AND t.name = ?")
            args.insert(0, tag)
        if favorite:
            joins += (" JOIN ratings r ON r.kind = 'sample' AND r.rel = s.rel"
                      " AND r.favorite = 1")

        sql = (f"SELECT s.* FROM samples s{joins} WHERE {' AND '.join(where)} "
               f"ORDER BY s.folder, s.name LIMIT ?")
        args.append(int(limit))
        return self._query(sql, args)

    def search_presets(self, kind: str = "synth", text: str = "",
                       folder: str = "", category: str = "", tag: str = "",
                       limit: int = 5000) -> list[sqlite3.Row]:
        """Presets de synthé (``kind='synth'``) ou kits (``kind='kit'``)."""
        where = ["p.kind = ?"]
        args: list[Any] = [kind]
        if text:
            where.append("(p.name LIKE ? ESCAPE '\\' OR p.rel LIKE ? ESCAPE '\\' "
                         "OR p.summary LIKE ? ESCAPE '\\')")
            like = f"%{_escape_like(text)}%"
            args += [like, like, like]
        if folder:
            where.append("(p.folder = ? OR p.folder LIKE ? ESCAPE '\\')")
            args += [folder, f"{_escape_like(folder)}/%"]
        if category:
            where.append("p.category = ?")
            args.append(category)

        joins = ""
        if tag:
            joins = (" JOIN item_tags it ON it.kind = p.kind AND it.rel = p.rel"
                     " JOIN tags t ON t.id = it.tag_id AND t.name = ?")
            args.insert(0, tag)

        sql = (f"SELECT p.* FROM presets p{joins} WHERE {' AND '.join(where)} "
               f"ORDER BY p.folder, p.name LIMIT ?")
        args.append(int(limit))
        return self._query(sql, args)

    def search_songs(self, text: str = "") -> list[sqlite3.Row]:
        """Morceaux, filtrés sur le nom."""
        if not text:
            return self._query("SELECT * FROM songs ORDER BY name", ())
        like = f"%{_escape_like(text)}%"
        return self._query(
            "SELECT * FROM songs WHERE name LIKE ? ESCAPE '\\' "
            "OR scale LIKE ? ESCAPE '\\' ORDER BY name", (like, like))

    def get(self, kind: str, rel: str) -> sqlite3.Row | None:
        """Une ligne précise, par nature et chemin."""
        table = {"sample": "samples", "song": "songs"}.get(kind, "presets")
        rows = self._query(f"SELECT * FROM {table} WHERE rel = ?", (rel,))
        return rows[0] if rows else None

    def folders(self, kind: str) -> list[tuple[str, int]]:
        """``[(dossier, nombre d'éléments)]`` pour l'arborescence latérale."""
        if kind == "sample":
            rows = self._query(
                "SELECT folder, COUNT(*) AS n FROM samples "
                "GROUP BY folder ORDER BY folder", ())
        elif kind == "song":
            rows = self._query(
                "SELECT 'SONGS' AS folder, COUNT(*) AS n FROM songs", ())
        else:
            rows = self._query(
                "SELECT folder, COUNT(*) AS n FROM presets WHERE kind = ? "
                "GROUP BY folder ORDER BY folder", (kind,))
        return [(r["folder"] or "", r["n"]) for r in rows]

    def categories(self, kind: str = "sample") -> list[tuple[str, int]]:
        """``[(catégorie, nombre)]``, catégories vides exclues."""
        table = "samples" if kind == "sample" else "presets"
        extra = "" if kind == "sample" else " AND kind = ?"
        args: tuple = () if kind == "sample" else (kind,)
        rows = self._query(
            f"SELECT category, COUNT(*) AS n FROM {table} "
            f"WHERE category IS NOT NULL AND category <> ''{extra} "
            f"GROUP BY category ORDER BY n DESC", args)
        return [(r["category"], r["n"]) for r in rows]

    # -- statistiques et anomalies ------------------------------------------ #

    def stats(self) -> dict:
        """Chiffres de la page d'accueil."""
        def one(sql: str, args: Sequence[Any] = ()) -> Any:
            rows = self._query(sql, args)
            return rows[0][0] if rows and rows[0][0] is not None else 0

        return {
            "samples": one("SELECT COUNT(*) FROM samples"),
            "synths": one("SELECT COUNT(*) FROM presets WHERE kind = 'synth'"),
            "kits": one("SELECT COUNT(*) FROM presets WHERE kind = 'kit'"),
            "songs": one("SELECT COUNT(*) FROM songs"),
            "sample_bytes": one("SELECT SUM(size) FROM samples"),
            "sample_seconds": one("SELECT SUM(duration) FROM samples"),
            "unused": one("SELECT COUNT(*) FROM samples WHERE used_count = 0"),
            "missing": one("SELECT COUNT(DISTINCT dst_norm) FROM links "
                           "WHERE missing = 1"),
            "unreadable": one("SELECT COUNT(*) FROM presets WHERE ok = 0")
                          + one("SELECT COUNT(*) FROM songs WHERE ok = 0"),
            # Doublons confirmés octet pour octet ; les candidats de
            # l'empreinte rapide sont comptés à part, car ils comportent des
            # faux positifs (cf. Library.duplicates).
            "duplicates": one(
                "SELECT COUNT(*) FROM (SELECT hash_full FROM samples "
                "WHERE hash_full IS NOT NULL AND hash_full <> '' "
                "GROUP BY hash_full HAVING COUNT(*) > 1)"),
            "duplicate_candidates": one(
                "SELECT COUNT(*) FROM (SELECT hash FROM samples "
                "WHERE hash IS NOT NULL AND hash <> '' "
                "GROUP BY hash HAVING COUNT(*) > 1)"),
            "favorites": one("SELECT COUNT(*) FROM ratings WHERE favorite = 1"),
            "tags": one("SELECT COUNT(*) FROM tags"),
            "last_scan": self.get_meta("last_scan", "") or "",
        }

    def _groups_by(self, column: str) -> list[list[sqlite3.Row]]:
        """Groupes d'échantillons partageant la même valeur non vide de ``column``."""
        rows = self._query(
            f"SELECT * FROM samples WHERE {column} IS NOT NULL AND {column} <> '' "
            f"AND {column} IN (SELECT {column} FROM samples "
            f"WHERE {column} IS NOT NULL AND {column} <> '' "
            f"GROUP BY {column} HAVING COUNT(*) > 1) "
            f"ORDER BY {column}, LENGTH(rel), rel", ())
        groups: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            groups.setdefault(row[column], []).append(row)
        return [g for g in groups.values() if len(g) > 1]

    def duplicate_candidates(self) -> list[list[sqlite3.Row]]:
        """Groupes **soupçonnés** identiques, d'après l'empreinte rapide.

        À ne jamais présenter comme des doublons : l'empreinte rapide ne lit
        que les extrémités du fichier et produit de vrais faux positifs
        (cf. :meth:`duplicates`). Il faut d'abord passer par
        ``core.scan.confirm_duplicates``.
        """
        return self._groups_by("hash")

    def duplicates(self) -> list[list[sqlite3.Row]]:
        """Groupes d'échantillons **confirmés** octet pour octet identiques.

        Seules les empreintes complètes sont prises en compte, parce que
        l'empreinte rapide se trompe sur des données réelles : les trois
        fichiers ``SAMPLES/Artists/Danny Taurus/MoDrama/Upper{01,14,20}.wav``
        de la carte ont la même taille et les mêmes 64 Kio de tête et de
        queue — du silence — mais diffèrent sur 1 407 blocs de 1 Kio. Les
        proposer à la suppression ferait perdre des échantillons bien réels.

        Les empreintes complètes sont calculées par
        ``core.scan.confirm_duplicates``, qui ne travaille que sur les groupes
        candidats : tant qu'il n'a pas tourné, cette méthode ne renvoie rien.
        """
        return self._groups_by("hash_full")

    def set_full_hash(self, rel: str, digest: str) -> None:
        """Enregistre l'empreinte complète d'un échantillon."""
        try:
            self.con.execute(
                "UPDATE samples SET hash_full = ? WHERE rel = ?",
                (digest, rel))
        except sqlite3.Error as exc:
            log.debug("écriture de l'empreinte complète de %r impossible : %s",
                      rel, exc)

    def unused_samples(self) -> list[sqlite3.Row]:
        """Échantillons qu'aucun preset, kit ou morceau n'utilise."""
        return self._query(
            "SELECT * FROM samples WHERE used_count = 0 ORDER BY size DESC", ())

    def missing_links(self) -> list[sqlite3.Row]:
        """Références d'échantillons introuvables sur la carte."""
        return self._query(
            "SELECT src_kind, src_rel, dst_rel, dst_norm FROM links "
            "WHERE missing = 1 ORDER BY dst_rel, src_rel", ())

    def recompute_usage(self) -> None:
        """Recalcule ``samples.used_count`` depuis la table des dépendances.

        Le rapprochement se fait sur la colonne normalisée, puisque la casse
        des ``fileName`` n'est pas fiable (cf. SPEC §1.7).
        """
        try:
            self.con.execute("UPDATE samples SET used_count = 0")
            self.con.execute(
                "UPDATE samples SET used_count = ("
                "  SELECT COUNT(*) FROM links l WHERE l.dst_norm = samples.rel_norm"
                ")")
            self.con.commit()
        except sqlite3.Error as exc:
            log.error("recalcul de l'utilisation impossible : %s", exc)

    # -- appréciations de l'utilisateur ------------------------------------- #

    def set_rating(self, kind: str, rel: str, stars: int | None = None,
                   favorite: bool | None = None,
                   notes: str | None = None) -> None:
        """Met à jour note, favori ou commentaire ; les ``None`` sont ignorés."""
        current = self.get_rating(kind, rel)
        merged = {
            "stars": current["stars"] if stars is None else int(stars),
            "favorite": current["favorite"] if favorite is None else int(bool(favorite)),
            "notes": current["notes"] if notes is None else str(notes),
        }
        try:
            self.con.execute(
                "INSERT INTO ratings(kind, rel, stars, favorite, notes) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(kind, rel) DO UPDATE SET stars = excluded.stars, "
                "favorite = excluded.favorite, notes = excluded.notes",
                (kind, rel, merged["stars"], merged["favorite"], merged["notes"]))
            self.con.commit()
        except sqlite3.Error as exc:
            log.error("enregistrement de l'appréciation impossible : %s", exc)

    def get_rating(self, kind: str, rel: str) -> dict:
        """``{'stars', 'favorite', 'notes'}`` ; valeurs neutres si rien n'est noté."""
        rows = self._query(
            "SELECT stars, favorite, notes FROM ratings "
            "WHERE kind = ? AND rel = ?", (kind, rel))
        if not rows:
            return {"stars": 0, "favorite": 0, "notes": ""}
        r = rows[0]
        return {"stars": r["stars"] or 0,
                "favorite": r["favorite"] or 0,
                "notes": r["notes"] or ""}

    def favorites(self, kind: str = "") -> list[sqlite3.Row]:
        """Éléments marqués comme favoris."""
        if kind:
            return self._query(
                "SELECT * FROM ratings WHERE favorite = 1 AND kind = ? "
                "ORDER BY rel", (kind,))
        return self._query(
            "SELECT * FROM ratings WHERE favorite = 1 ORDER BY kind, rel", ())

    # -- tags ---------------------------------------------------------------- #

    def _tag_id(self, tag: str, color: str = "", create: bool = True) -> int | None:
        """Identifiant d'un tag, créé au besoin."""
        tag = str(tag).strip()
        if not tag:
            return None
        rows = self._query("SELECT id FROM tags WHERE name = ?", (tag,))
        if rows:
            return rows[0]["id"]
        if not create:
            return None
        try:
            cur = self.con.execute(
                "INSERT INTO tags(name, color) VALUES (?, ?)", (tag, color))
            self.con.commit()
            return int(cur.lastrowid or 0)
        except sqlite3.Error as exc:
            log.error("création du tag %r impossible : %s", tag, exc)
            return None

    def add_tag(self, kind: str, rel: str, tag: str, color: str = "") -> None:
        """Associe un tag à un élément."""
        tag_id = self._tag_id(tag, color)
        if tag_id is None:
            return
        try:
            self.con.execute(
                "INSERT OR IGNORE INTO item_tags(kind, rel, tag_id) "
                "VALUES (?, ?, ?)", (kind, rel, tag_id))
            self.con.commit()
        except sqlite3.Error as exc:
            log.error("ajout du tag %r impossible : %s", tag, exc)

    def remove_tag(self, kind: str, rel: str, tag: str) -> None:
        """Retire un tag d'un élément."""
        tag_id = self._tag_id(tag, create=False)
        if tag_id is None:
            return
        try:
            self.con.execute(
                "DELETE FROM item_tags WHERE kind = ? AND rel = ? AND tag_id = ?",
                (kind, rel, tag_id))
            self.con.commit()
        except sqlite3.Error as exc:
            log.error("retrait du tag %r impossible : %s", tag, exc)

    def tags_of(self, kind: str, rel: str) -> list[str]:
        """Tags portés par un élément."""
        rows = self._query(
            "SELECT t.name FROM tags t JOIN item_tags it ON it.tag_id = t.id "
            "WHERE it.kind = ? AND it.rel = ? ORDER BY t.name", (kind, rel))
        return [r["name"] for r in rows]

    def all_tags(self) -> list[tuple[str, str, int]]:
        """``[(nom, couleur, nombre d'usages)]`` pour tous les tags."""
        rows = self._query(
            "SELECT t.name, t.color, COUNT(it.rel) AS n FROM tags t "
            "LEFT JOIN item_tags it ON it.tag_id = t.id "
            "GROUP BY t.id ORDER BY t.name", ())
        return [(r["name"], r["color"] or "", r["n"]) for r in rows]

    # -- confort ------------------------------------------------------------ #

    def __enter__(self) -> "Library":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
