# -*- coding: utf-8 -*-
"""Une copie de travail tenue à l'image de la carte du Deluge.

La carte reste dans la machine. L'application travaille sur une **copie de
travail** locale — lire cinq mille fichiers par USB à 120 Ko/s n'est pas
envisageable, parcourir leur liste l'est (3,6 s mesurées) — et la tient à
l'image de la carte par une synchronisation **à trois voies** : l'état de la
carte, celui de la copie, et ce qu'ils étaient à la dernière synchronisation
(le *manifeste*).

* ce que le Deluge a changé **descend** ; ce que l'application a créé ou
  modifié **monte** ;
* un fichier changé des deux côtés est un **conflit** : les deux versions
  sont gardées, rien n'est écrasé ;
* une suppression n'est **jamais** propagée sans accord : la carte contient
  des mois de travail ;
* ce qui est retiré de la copie de travail part dans son historique
  (``.deluge-companion/historique``), jamais à la poubelle.

Reconnaître un fichier réécrit par le Deluge
--------------------------------------------

**La machine n'a pas d'horloge** : tout ce qu'elle enregistre porte la date
nulle (mesuré). Après chaque synchronisation, l'application date donc sur la
carte les fichiers à date nulle ; si le Deluge réécrit l'un d'eux, sa date
retombe à zéro, et le changement se voit sans relire le contenu.

La première fois
----------------

La copie de travail se bâtit depuis la **sauvegarde** de l'utilisateur (une
copie de la carte) : un fichier de même chemin et de même taille, dont la
date ne diffère que d'un décalage de fuseau constant, est copié localement
au lieu de traverser le câble. Mesuré : 4 295 fichiers sur 4 318, tous à
exactement deux heures d'écart — la copie faite sur un Mac. La sauvegarde,
elle, n'est que lue.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from .delugefiles import (NOT_CONNECTED, STOPPED, CardEntry, FileError,
                          fat_stamp, from_fat)

log = logging.getLogger(__name__)

__all__ = ["Action", "Exchange", "FolderCard", "LocalFile", "Record",
           "SyncPlan", "SyncResult", "UsbCard", "apply_plan", "backup_state",
           "exchange_of", "is_junk", "load_exchanges", "load_manifest",
           "pending_changes", "plan_sync", "recent_arrivals",
           "record_exchange", "save_manifest", "scan_local", "update_backup"]

#: Dossier de l'application dans la copie de travail.
META_DIR = ".deluge-companion"
MANIFEST = META_DIR + "/synchro.json"
HISTORY = META_DIR + "/historique"
#: Ce qui a été reçu du Deluge et envoyé vers lui, synchronisation par
#: synchronisation : sans lui, la seule trace d'un échange était un message
#: de dix secondes dans la barre d'état — le journal de l'utilisateur ne
#: disait même pas que ses dix presets réparés étaient partis sur la carte.
EXCHANGES = META_DIR + "/echanges.json"
#: Échanges gardés, et fichiers nommés par échange : au-delà, les nombres
#: seuls (la création de la copie de travail en compte 2 757).
MAX_EXCHANGES = 200
MAX_NAMED = 300
#: Ce que la copie de travail sait de la sauvegarde : les fichiers déjà
#: vérifiés identiques, pour ne pas relire 1,4 Go à chaque mise à jour.
BACKUP_STATE = META_DIR + "/sauvegarde.json"

#: Ce que macOS, Windows et le firmware laissent sur une carte, et qui n'est
#: pas de la musique. Mesuré sur la sauvegarde : 11 061 fichiers et 4,2 Go
#: de corbeilles et d'index Spotlight.
_JUNK_DIRS = {"system volume information", ".trashes", ".spotlight-v100",
              ".fseventsd", ".temporaryitems", META_DIR,
              # Les originaux que ``samplefix`` met de côté : des copies de
              # sûreté, mieux à l'abri sur le PC que sur la carte.
              "_backup"}
_JUNK_FILES = {".ds_store", "thumbs.db", "desktop.ini"}
#: Les fichiers temporaires des écritures de l'application, qu'un arrêt
#: brutal peut laisser derrière lui : ``.dc-tmp`` (ici), ``.tmp~``
#: (``wav.write``) et ``<nom>.<8 signes>.tmp`` (``dxml.save``). Ils ne
#: doivent jamais partir sur la carte.
_TEMPORARY = re.compile(r"(\.dc-tmp|\.tmp~|\.[a-z0-9_]{8}\.tmp)$")

#: Les dossiers qui portent la musique.
MUSIC_DIRS = ("SONGS", "SYNTHS", "KITS", "SAMPLES")

#: Décalages de date tenus pour « même fichier » sans autre preuve : aucun,
#: et l'heure d'été.
_SAFE_OFFSETS = (0, 3600, -3600)


def is_junk(rel: str) -> bool:
    """Vrai pour ce qui n'a pas à voyager : corbeilles, index, fichiers
    parasites de macOS (``._*``), temporaires de l'application."""
    parts = [p for p in str(rel).replace("\\", "/").split("/") if p]
    if not parts:
        return True
    for p in parts[:-1]:
        low = p.casefold()
        if low in _JUNK_DIRS or low.startswith(".trash"):
            return True
    nom = parts[-1]
    low = nom.casefold()
    if low in _JUNK_DIRS or low.startswith(".trash") or low in _JUNK_FILES:
        return True
    if nom.startswith("._"):
        return True
    # Les ``.bak`` que chaque écriture XML laisse à côté du fichier : envoyés
    # au Deluge, ils encombreraient sa carte — et le câble, à 45 Ko/s.
    if low.endswith(".bak"):
        return True
    if nom.upper().startswith("~DC") and nom.upper().endswith((".TMP", ".OLD")):
        return True
    if _TEMPORARY.search(low):
        return True
    return False


# --------------------------------------------------------------------------- #
# États
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class LocalFile:
    """Un fichier de la copie de travail."""

    size: int
    mtime_ns: int


@dataclass
class Record:
    """Ce qu'étaient un fichier et sa copie à la dernière synchronisation."""

    rel: str
    card_size: int
    card_date: int
    card_time: int
    local_size: int
    local_mtime_ns: int

    def to_list(self) -> list:
        return [self.card_size, self.card_date, self.card_time,
                self.local_size, self.local_mtime_ns]

    @classmethod
    def from_list(cls, rel: str, valeurs: list) -> "Record":
        c, d, t, ls, lm = (int(v) for v in valeurs[:5])
        return cls(rel, c, d, t, ls, lm)


def _key(rel: str) -> str:
    """Clé insensible à la casse : FAT et Windows ne font pas la différence."""
    return rel.replace("\\", "/").strip("/").casefold()


def scan_local(work: Path) -> dict[str, LocalFile]:
    """Les fichiers de la copie de travail, sauf ceux de l'application."""
    work = Path(work)
    trouve: dict[str, LocalFile] = {}
    for dossier, sous, fichiers in os.walk(work):
        rel_dossier = Path(dossier).relative_to(work).as_posix()
        if rel_dossier == ".":
            rel_dossier = ""
        sous[:] = [s for s in sous
                   if not is_junk((rel_dossier + "/" + s).strip("/"))]
        for nom in fichiers:
            rel = (rel_dossier + "/" + nom).strip("/")
            if is_junk(rel):
                continue
            try:
                st = os.stat(os.path.join(dossier, nom))
            except OSError:
                continue
            trouve[rel] = LocalFile(int(st.st_size), int(st.st_mtime_ns))
    return trouve


def load_manifest(work: Path) -> dict[str, Record]:
    chemin = Path(work) / MANIFEST
    try:
        brut = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    fichiers = brut.get("files", {}) if isinstance(brut, dict) else {}
    sortie: dict[str, Record] = {}
    for rel, valeurs in fichiers.items():
        try:
            sortie[rel] = Record.from_list(rel, valeurs)
        except (TypeError, ValueError):
            continue
    return sortie


def save_manifest(work: Path, records: dict[str, Record]) -> None:
    """Écrit le manifeste d'un seul coup : un manifeste à moitié écrit ferait
    croire que tout a changé."""
    chemin = Path(work) / MANIFEST
    chemin.parent.mkdir(parents=True, exist_ok=True)
    temporaire = chemin.with_suffix(".tmp")
    temporaire.write_text(json.dumps(
        {"version": 1, "saved": time.time(),
         "files": {r.rel: r.to_list() for r in records.values()}},
        ensure_ascii=False), encoding="utf-8")
    os.replace(temporaire, chemin)


# --------------------------------------------------------------------------- #
# La carte, vue par un transport
# --------------------------------------------------------------------------- #

class CardTransport(Protocol):
    """Ce que la synchronisation demande à une carte."""

    def walk(self) -> dict[str, CardEntry]: ...
    def read(self, rel: str, progress=None) -> bytes: ...
    def write_new(self, rel: str, data: bytes, mtime: float,
                  progress=None) -> None: ...
    def replace(self, rel: str, data: bytes, mtime: float,
                progress=None) -> None: ...
    def delete(self, rel: str) -> None: ...
    def touch(self, rel: str, mtime: float) -> None: ...


class UsbCard:
    """La carte restée dans le Deluge, par :class:`delugefiles.DelugeFiles`.

    :param should_stop: consulté entre deux blocs de chaque transfert — la
        machine qui se met à jouer, la fenêtre qu'on ferme : le fichier en
        cours s'arrête là, son temporaire est retiré de la carte.
    """

    def __init__(self, files, should_stop: Callable[[], bool] | None = None
                 ) -> None:
        self.files = files
        self._should_stop = should_stop

    def _run(self, fn, *args):
        precedent = self.files.stop_check
        self.files.stop_check = self._should_stop
        try:
            return fn(*args)
        finally:
            self.files.stop_check = precedent

    def walk(self) -> dict[str, CardEntry]:
        self.files.unreachable = []
        return self._run(self.files.walk, "/", is_junk)

    @property
    def unreachable(self) -> list[str]:
        return [r for r in self.files.unreachable if not is_junk(r)]

    def read(self, rel, progress=None):
        return self._run(self.files.read, "/" + rel, progress)

    def write_new(self, rel, data, mtime, progress=None):
        self._run(self.files.write_new, "/" + rel, data, mtime, progress)

    def replace(self, rel, data, mtime, progress=None):
        self._run(self.files.replace, "/" + rel, data, mtime, progress)

    def delete(self, rel):
        self.files.delete("/" + rel)

    def touch(self, rel, mtime):
        self.files.touch("/" + rel, mtime)


class FolderCard:
    """Un dossier tenu pour une carte : la carte dans un lecteur du PC, ou
    une carte simulée dans les tests. Mêmes règles que la machine : rien
    d'existant n'est écrasé par :meth:`write_new`."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.unreachable: list[str] = []

    def walk(self) -> dict[str, CardEntry]:
        trouve: dict[str, CardEntry] = {}
        for dossier, sous, fichiers in os.walk(self.root):
            rel_dossier = Path(dossier).relative_to(self.root).as_posix()
            rel_dossier = "" if rel_dossier == "." else rel_dossier
            garde = []
            for s in sous:
                rel = (rel_dossier + "/" + s).strip("/")
                if is_junk(rel):
                    continue
                garde.append(s)
                trouve[rel] = CardEntry(s, 0, 0, 0, 0x10)
            sous[:] = garde
            for nom in fichiers:
                rel = (rel_dossier + "/" + nom).strip("/")
                if is_junk(rel):
                    continue
                st = os.stat(os.path.join(dossier, nom))
                date, heure = self._stamp(st.st_mtime)
                trouve[rel] = CardEntry(nom, int(st.st_size), date, heure, 0x20)
        return trouve

    @staticmethod
    def _stamp(mtime: float) -> tuple[int, int]:
        # Une date « nulle » d'un fichier simulé reste nulle (1980-01-01).
        if mtime <= from_fat(0x21, 0) + 1:
            return 0, 0
        return fat_stamp(mtime)

    def read(self, rel, progress=None):
        return (self.root / rel).read_bytes()

    def write_new(self, rel, data, mtime, progress=None):
        cible = self.root / rel
        if cible.exists():
            raise FileError("existe déjà sur la carte : /" + rel, code=8)
        cible.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic(cible, data, mtime)

    def replace(self, rel, data, mtime, progress=None):
        cible = self.root / rel
        cible.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic(cible, data, mtime)

    def delete(self, rel):
        (self.root / rel).unlink()

    def touch(self, rel, mtime):
        os.utime(self.root / rel, (mtime, mtime))


def _write_atomic(cible: Path, data: bytes, mtime: float | None) -> None:
    temporaire = cible.with_name(cible.name + ".dc-tmp")
    temporaire.write_bytes(data)
    if mtime is not None:
        os.utime(temporaire, (mtime, mtime))
    os.replace(temporaire, cible)


# --------------------------------------------------------------------------- #
# Le plan
# --------------------------------------------------------------------------- #

#: Ce qu'une action fait, en clair.
KINDS = {
    "adopt": "déjà identique",
    "copy_backup": "repris de la sauvegarde",
    "pull": "reçu du Deluge",
    "push": "envoyé au Deluge",
    "conflict": "changé des deux côtés",
    "delete_local": "supprimé sur le Deluge",
    "delete_card": "supprimé sur le PC",
}


@dataclass
class Action:
    kind: str
    rel: str
    size: int = 0
    reason: str = ""
    #: Fichier source pour ``copy_backup``.
    source: Path | None = None
    #: Date FAT du fichier sur la carte au moment du parcours.
    date: int = 0
    time: int = 0
    #: Le fichier existe sur la carte (un envoi le remplace, sinon le crée).
    on_card: bool = False

    @property
    def label(self) -> str:
        return KINDS.get(self.kind, self.kind)


@dataclass
class SyncPlan:
    """Ce que la synchronisation ferait. Rien n'a encore bougé."""

    actions: list[Action] = field(default_factory=list)
    #: Noms de la carte impossibles à transmettre (non ASCII).
    unreachable: list[str] = field(default_factory=list)
    #: Entrées du manifeste dont le fichier a disparu des deux côtés.
    forget: list[str] = field(default_factory=list)
    #: Fichiers de la sauvegarde que la carte n'a pas : ``(chemin, taille)``.
    #: Jamais repris d'office — un fichier supprimé sur le Deluge
    #: reviendrait —, mais proposés : chez l'utilisateur, un kit créé par
    #: l'application dans la sauvegarde n'était jamais arrivé sur la carte.
    backup_only: list[tuple[str, int]] = field(default_factory=list)

    def backup_music(self) -> list[tuple[str, int]]:
        """Ceux de :attr:`backup_only` qui sont de la musique (morceaux,
        presets, kits, échantillons) ; le reste — un ancien firmware, des
        réglages que la 1.3 range ailleurs — n'a pas à revenir."""
        return [(r, n) for r, n in self.backup_only
                if r.split("/", 1)[0].upper() in MUSIC_DIRS and "/" in r]

    def of(self, *kinds: str) -> list[Action]:
        return [a for a in self.actions if a.kind in kinds]

    @property
    def transfers(self) -> list[Action]:
        """Ce qui fait voyager des octets ou change un fichier."""
        return self.of("copy_backup", "pull", "push", "conflict",
                       "delete_local")

    @property
    def needs_consent(self) -> list[Action]:
        """Ce qui ne se fait jamais sans accord explicite."""
        return self.of("delete_card")

    def bytes_over_cable(self) -> int:
        return sum(a.size for a in self.of("pull", "push", "conflict"))

    def counts(self) -> Counter:
        return Counter(a.kind for a in self.actions)

    def summary(self) -> str:
        c = self.counts()
        morceaux = []
        for kind, phrase in (("pull", "%d à recevoir"), ("push", "%d à envoyer"),
                             ("copy_backup", "%d repris de la sauvegarde"),
                             ("conflict", "%d changés des deux côtés"),
                             ("delete_local", "%d supprimés sur le Deluge"),
                             ("delete_card", "%d supprimés sur le PC")):
            if c.get(kind):
                morceaux.append(phrase % c[kind])
        return ", ".join(morceaux) if morceaux else "à jour"

    @property
    def empty(self) -> bool:
        return not self.transfers and not self.needs_consent


def _offset_ok(card: CardEntry, local_mtime: float,
               offsets: tuple[int, ...]) -> bool:
    if card.date == 0:
        return False
    ecart = local_mtime - from_fat(card.date, card.time)
    return any(abs(ecart - o) <= 2 for o in offsets)


def _dominant_offset(card: dict[str, CardEntry], backup: Path) -> int | None:
    """Le décalage de fuseau constant entre la carte et sa sauvegarde, s'il y
    en a un (mesuré : −7 200 s sur tous les fichiers communs)."""
    ecarts: Counter = Counter()
    for rel, e in card.items():
        if e.is_dir or e.date == 0:
            continue
        p = backup / rel
        try:
            st = p.stat()
        except OSError:
            continue
        if st.st_size == e.size:
            ecarts[round((st.st_mtime - from_fat(e.date, e.time)) / 60) * 60] += 1
        if sum(ecarts.values()) >= 400:
            break
    if not ecarts:
        return None
    valeur, nombre = ecarts.most_common(1)[0]
    return valeur if nombre >= 0.9 * sum(ecarts.values()) else None


def plan_sync(card: dict[str, CardEntry], local: dict[str, LocalFile],
              manifest: dict[str, Record], backup: Path | None = None
              ) -> SyncPlan:
    """Compare les trois états et dit ce qu'il faudrait faire.

    :param backup: la sauvegarde de la carte, lue seulement, d'où reprendre
        localement les fichiers qui manquent à la copie de travail.
    """
    plan = SyncPlan()
    cartes = {_key(r): (r, e) for r, e in card.items() if not e.is_dir}
    locaux = {_key(r): (r, f) for r, f in local.items()}
    connus = {_key(r): rec for r, rec in manifest.items()}
    decalages = _SAFE_OFFSETS
    if backup is not None:
        dominant = _dominant_offset(card, Path(backup))
        if dominant is not None and dominant not in decalages:
            decalages = decalages + (dominant,)

    for cle in sorted(set(cartes) | set(locaux) | set(connus)):
        c = cartes.get(cle)
        l_ = locaux.get(cle)
        m = connus.get(cle)
        if c is not None:
            rel, ec = c
        else:
            rel = l_[0] if l_ is not None else m.rel
            ec = None
        lf = l_[1] if l_ is not None else None
        if is_junk(rel):
            continue
        if ec is None and lf is None:
            plan.forget.append(m.rel)
            continue
        sur_carte = ({"date": ec.date, "time": ec.time, "on_card": True}
                     if ec is not None else {})

        carte_change = ec is not None and (
            m is None or ec.size != m.card_size
            or (ec.date, ec.time) != (m.card_date, m.card_time))
        local_change = lf is not None and (
            m is None or lf.size != m.local_size
            or lf.mtime_ns != m.local_mtime_ns)

        if ec is not None and lf is not None:
            if m is None:
                # Jamais synchronisés ensemble : même fichier si même taille et
                # dates compatibles ; sinon la carte fait foi, et la version
                # locale part dans l'historique.
                if ec.size == lf.size and _offset_ok(ec, lf.mtime_ns / 1e9,
                                                     decalages):
                    plan.actions.append(Action("adopt", rel, ec.size,
                                               **sur_carte))
                else:
                    plan.actions.append(Action(
                        "pull", rel, ec.size,
                        "la copie de travail diffère de la carte", **sur_carte))
            elif carte_change and local_change:
                plan.actions.append(Action("conflict", rel, ec.size + lf.size,
                                           **sur_carte))
            elif carte_change:
                plan.actions.append(Action("pull", rel, ec.size, **sur_carte))
            elif local_change:
                plan.actions.append(Action("push", rel, lf.size, **sur_carte))
        elif ec is not None:
            if m is not None and not carte_change:
                plan.actions.append(Action("delete_card", rel, ec.size,
                                           "supprimé de la copie de travail",
                                           **sur_carte))
            else:
                source = None
                if backup is not None:
                    candidat = Path(backup) / rel
                    try:
                        st = candidat.stat()
                        if st.st_size == ec.size and _offset_ok(
                                ec, st.st_mtime, decalages):
                            source = candidat
                    except OSError:
                        pass
                if source is not None:
                    plan.actions.append(Action("copy_backup", rel, ec.size,
                                               source=source, **sur_carte))
                else:
                    plan.actions.append(Action("pull", rel, ec.size,
                                               **sur_carte))
        elif lf is not None:
            if m is not None and not local_change:
                plan.actions.append(Action("delete_local", rel, lf.size,
                                           "le Deluge ne l'a plus"))
            else:
                plan.actions.append(Action("push", rel, lf.size))
    if backup is not None:
        plan.backup_only = backup_only(cartes, locaux, Path(backup))
    return plan


def backup_only(cartes: dict, locaux: dict, backup: Path
                ) -> list[tuple[str, int]]:
    """Les fichiers de la sauvegarde que ni la carte ni la copie n'ont."""
    seuls = []
    for rel, f in scan_local(backup).items():
        cle = _key(rel)
        if cle not in cartes and cle not in locaux:
            seuls.append((rel, f.size))
    return sorted(seuls)


def take_from_backup(backup: Path, work: Path, rels: list[str]) -> int:
    """Recopie dans la copie de travail des fichiers de la sauvegarde ; la
    prochaine synchronisation les enverra au Deluge. Rend le nombre copié.
    Rien d'existant n'est remplacé."""
    copies = 0
    for rel in rels:
        source, cible = Path(backup) / rel, Path(work) / rel
        if cible.exists() or not source.is_file():
            continue
        cible.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, cible)
        copies += 1
    return copies


# --------------------------------------------------------------------------- #
# L'exécution
# --------------------------------------------------------------------------- #

@dataclass
class SyncResult:
    done: Counter = field(default_factory=Counter)
    errors: list[str] = field(default_factory=list)
    #: Copies faites lors d'un conflit : ``(chemin d'origine, nouveau nom)``.
    renamed: list[tuple[str, str]] = field(default_factory=list)
    stopped: bool = False
    #: Ce qui a été fait, fichier par fichier : ``(nature, chemin)``.
    items: list[tuple[str, str]] = field(default_factory=list)
    #: Arrêtée faute de machine (débranchée, ou muette) — pas à la demande.
    lost: bool = False

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        morceaux = ["%d %s" % (n, KINDS.get(k, k)) for k, n in
                    sorted(self.done.items()) if k != "adopt" and n]
        if self.errors:
            morceaux.append("%d erreur(s)" % len(self.errors))
        return ", ".join(morceaux) if morceaux else "rien à faire"


def _conflict_name(rel: str, existants: set[str]) -> str:
    """« Calm Down.XML » -> « Calm Down (PC).XML », jamais un nom pris."""
    dossier, _, nom = rel.rpartition("/")
    base, point, ext = nom.rpartition(".")
    if not point:
        base, ext = nom, ""
    for i in range(1, 100):
        suffixe = " (PC)" if i == 1 else " (PC %d)" % i
        candidat = base + suffixe + (("." + ext) if ext else "")
        complet = (dossier + "/" + candidat).strip("/")
        if _key(complet) not in existants:
            return complet
    raise FileError("aucun nom libre pour la version du PC de " + rel)


def _to_history(work: Path, rel: str) -> None:
    """Met de côté une version locale au lieu de l'écraser ou de l'effacer."""
    source = work / rel
    if not source.exists():
        return
    horodatage = time.strftime("%Y-%m-%d_%Hh%M%S")
    cible = work / HISTORY / horodatage / rel
    cible.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(cible))


def apply_plan(plan: SyncPlan, transport, work: Path,
               manifest: dict[str, Record], *, allow_card_deletes: bool = False,
               progress: Callable[[int, int, str], None] | None = None,
               should_stop: Callable[[], bool] | None = None) -> SyncResult:
    """Exécute le plan, fichier par fichier, et tient le manifeste à jour.

    Un fichier en erreur n'arrête pas les autres ; le manifeste est écrit à
    la fin, et aussi en cas d'arrêt — ce qui est fait reste acquis.
    Les fichiers à date nulle de la carte (écrits par le Deluge) y sont
    datés : une réécriture par la machine se verra à la prochaine fois.
    """
    work = Path(work)
    resultat = SyncResult()
    actions = [a for a in plan.actions
               if a.kind != "delete_card" or allow_card_deletes]
    total = len(actions)
    existants_carte = set()
    muettes = 0
    for i, action in enumerate(actions):
        if should_stop is not None and should_stop():
            resultat.stopped = True
            break
        if progress is not None:
            progress(i, total, action.rel)
        try:
            renomme = _apply_one(action, transport, work, manifest,
                                 existants_carte)
            if renomme:
                resultat.renamed.append(renomme)
            resultat.done[action.kind] += 1
            if action.kind != "adopt":
                resultat.items.append((action.kind, action.rel))
            muettes = 0
        except FileError as exc:
            # Arrêt demandé : le fichier en cours est abandonné proprement,
            # ce qui est fait reste acquis. Câble débranché, machine muette :
            # inutile d'essayer les fichiers suivants un par un — chacun
            # attendrait cinq secondes pour rien.
            if exc.code == STOPPED:
                resultat.stopped = True
                break
            if exc.code == NOT_CONNECTED:
                resultat.errors.append("le Deluge a été débranché")
                resultat.stopped = resultat.lost = True
                break
            log.warning("synchronisation de %s : %s", action.rel, exc)
            resultat.errors.append("%s : %s" % (action.rel, exc))
            muettes = muettes + 1 if exc.code == 15 else 0
            if muettes >= 2:
                resultat.errors.append("le Deluge ne répond plus")
                resultat.stopped = resultat.lost = True
                break
        except OSError as exc:
            log.warning("synchronisation de %s : %s", action.rel, exc)
            resultat.errors.append("%s : %s" % (action.rel, exc))
    if not resultat.stopped:
        for rel in plan.forget:
            manifest.pop(rel, None)
    if progress is not None:
        progress(total, total, "")
    save_manifest(work, manifest)
    return resultat


def _record(manifest: dict[str, Record], rel: str, card_size: int,
            date: int, heure: int, local: Path) -> None:
    st = local.stat()
    for cle in [k for k in manifest if _key(k) == _key(rel) and k != rel]:
        del manifest[cle]
    manifest[rel] = Record(rel, int(card_size), int(date), int(heure),
                           int(st.st_size), int(st.st_mtime_ns))


def _mark(transport, rel: str, local: Path) -> tuple[int, int]:
    """Date le fichier sur la carte à l'heure de sa copie locale ; rend la
    date FAT posée."""
    mtime = local.stat().st_mtime
    transport.touch(rel, mtime)
    return fat_stamp(mtime)


def _apply_one(action: Action, transport, work: Path,
               manifest: dict[str, Record], existants_carte: set) -> tuple | None:
    rel = action.rel
    local = work / rel
    if action.kind == "adopt":
        _record(manifest, rel, action.size, action.date, action.time, local)
        return None

    if action.kind == "copy_backup":
        local.parent.mkdir(parents=True, exist_ok=True)
        temporaire = local.with_name(local.name + ".dc-tmp")
        shutil.copy2(action.source, temporaire)
        os.replace(temporaire, local)
        _record(manifest, rel, action.size, action.date, action.time, local)
        return None

    if action.kind == "pull":
        donnees = transport.read(rel)
        if local.exists():
            _to_history(work, rel)
        local.parent.mkdir(parents=True, exist_ok=True)
        date, heure = action.date, action.time
        mtime = from_fat(date, heure) if date else None
        _write_atomic(local, donnees, mtime)
        if not date:
            date, heure = _mark(transport, rel, local)
        _record(manifest, rel, len(donnees), date, heure, local)
        return None

    if action.kind == "push":
        donnees = local.read_bytes()
        mtime = local.stat().st_mtime
        if action.on_card:
            transport.replace(rel, donnees, mtime)
        else:
            transport.write_new(rel, donnees, mtime)
        date, heure = fat_stamp(mtime)
        _record(manifest, rel, len(donnees), date, heure, local)
        return None

    if action.kind == "conflict":
        # La version du PC part sous un nouveau nom, des deux côtés ; celle
        # du Deluge garde le nom d'origine. La carte d'abord, la copie
        # ensuite : un arrêt entre les deux ne laisse rien de local à moitié
        # fait — la prochaine fois, la copie « (PC) » de la carte descend.
        tous = {_key(r) for r in manifest} | existants_carte
        nouveau = _conflict_name(rel, tous)
        existants_carte.add(_key(nouveau))
        version_pc = local.read_bytes()
        mtime_pc = local.stat().st_mtime
        transport.write_new(nouveau, version_pc, mtime_pc)
        donnees = transport.read(rel)
        cible_pc = work / nouveau
        cible_pc.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic(cible_pc, version_pc, mtime_pc)
        _record(manifest, nouveau, len(version_pc), *fat_stamp(mtime_pc),
                cible_pc)
        date, heure = action.date, action.time
        _write_atomic(local, donnees, from_fat(date, heure) if date else None)
        if not date:
            date, heure = _mark(transport, rel, local)
        _record(manifest, rel, len(donnees), date, heure, local)
        return rel, nouveau

    if action.kind == "delete_local":
        _to_history(work, rel)
        for cle in [k for k in manifest if _key(k) == _key(rel)]:
            del manifest[cle]
        return None

    if action.kind == "delete_card":
        transport.delete(rel)
        for cle in [k for k in manifest if _key(k) == _key(rel)]:
            del manifest[cle]
        return None
    raise ValueError("action inconnue : %s" % action.kind)


# --------------------------------------------------------------------------- #
# Ce qui attend, ce qui a voyagé
# --------------------------------------------------------------------------- #

def pending_changes(work: Path) -> list[tuple[str, int]]:
    """Ce que la prochaine synchronisation enverrait au Deluge : les fichiers
    de la copie de travail créés ou modifiés depuis la dernière.

    Ne touche pas au câble : la copie et son manifeste suffisent (0,11 s
    mesurées sur les 2 758 fichiers de l'utilisateur). Sans copie de
    travail, rien n'attend.
    """
    work = Path(work)
    if not (work / MANIFEST).is_file():
        return []
    connus = {_key(r): rec for r, rec in load_manifest(work).items()}
    sortie = []
    for rel, f in scan_local(work).items():
        rec = connus.get(_key(rel))
        if (rec is None or rec.local_size != f.size
                or rec.local_mtime_ns != f.mtime_ns):
            sortie.append((rel, f.size))
    return sorted(sortie)


@dataclass
class Exchange:
    """Une synchronisation, telle qu'on la raconte à l'utilisateur."""

    when: float
    reason: str = ""
    seconds: float = 0.0
    #: Descendus du Deluge : ce qu'il a enregistré.
    received: list[str] = field(default_factory=list)
    #: Montés vers lui : ce que l'application a créé ou réparé.
    sent: list[str] = field(default_factory=list)
    #: Changés des deux côtés : ``[chemin, nom de la version du PC]``.
    conflicts: list[list[str]] = field(default_factory=list)
    #: Le Deluge ne les a plus : retirés de la copie, gardés dans
    #: l'historique.
    removed: list[str] = field(default_factory=list)
    #: Supprimés de la carte, avec l'accord de l'utilisateur.
    deleted: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    #: Nombre d'actions par nature — exact même quand les listes sont
    #: tronquées à :data:`MAX_NAMED`.
    counts: dict[str, int] = field(default_factory=dict)
    stopped: bool = False

    @property
    def empty(self) -> bool:
        return not any(self.counts.values()) and not self.errors

    def summary(self) -> str:
        c = self.counts
        morceaux = []
        for cle, phrase in (("pull", "%d reçu(s)"), ("push", "%d envoyé(s)"),
                            ("conflict", "%d changé(s) des deux côtés"),
                            ("delete_local", "%d retiré(s), le Deluge ne les "
                                             "a plus"),
                            ("delete_card", "%d supprimé(s) de la carte"),
                            ("copy_backup", "%d repris de la sauvegarde")):
            if c.get(cle):
                morceaux.append(phrase % c[cle])
        if self.errors:
            morceaux.append("%d erreur(s)" % len(self.errors))
        if self.stopped:
            morceaux.append("interrompue")
        return ", ".join(morceaux) if morceaux else "rien à faire"

    def to_dict(self) -> dict:
        return {"when": self.when, "reason": self.reason,
                "seconds": round(self.seconds, 2),
                "received": self.received, "sent": self.sent,
                "conflicts": self.conflicts, "removed": self.removed,
                "deleted": self.deleted, "errors": self.errors,
                "counts": self.counts, "stopped": self.stopped}

    @classmethod
    def from_dict(cls, d: dict) -> "Exchange":
        def liste(cle):
            valeur = d.get(cle) or []
            return [v for v in valeur if isinstance(v, (str, list))]
        return cls(when=float(d.get("when", 0) or 0),
                   reason=str(d.get("reason", "")),
                   seconds=float(d.get("seconds", 0) or 0),
                   received=liste("received"), sent=liste("sent"),
                   conflicts=liste("conflicts"), removed=liste("removed"),
                   deleted=liste("deleted"), errors=liste("errors"),
                   counts={str(k): int(v) for k, v in
                           (d.get("counts") or {}).items()},
                   stopped=bool(d.get("stopped", False)))


def exchange_of(result: SyncResult, reason: str = "",
                seconds: float = 0.0) -> Exchange:
    """Ce qu'une synchronisation a fait, prêt à garder."""
    echange = Exchange(when=time.time(), reason=reason,
                       seconds=float(seconds), errors=list(result.errors),
                       counts={k: int(n) for k, n in result.done.items()
                               if k != "adopt" and n},
                       stopped=bool(result.stopped))
    cibles = {"pull": echange.received, "push": echange.sent,
              "delete_local": echange.removed,
              "delete_card": echange.deleted}
    for kind, rel in result.items:
        liste = cibles.get(kind)
        if liste is not None and len(liste) < MAX_NAMED:
            liste.append(rel)
    echange.conflicts = [list(paire) for paire in result.renamed[:MAX_NAMED]]
    return echange


def load_exchanges(work: Path, limit: int | None = None) -> list[Exchange]:
    """Les échanges gardés, le plus récent d'abord."""
    try:
        brut = json.loads((Path(work) / EXCHANGES).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    entrees = brut.get("exchanges", []) if isinstance(brut, dict) else []
    sortie = []
    for d in entrees:
        if isinstance(d, dict):
            try:
                sortie.append(Exchange.from_dict(d))
            except (TypeError, ValueError):
                continue
    sortie.sort(key=lambda e: e.when, reverse=True)
    return sortie[:limit] if limit else sortie


def record_exchange(work: Path, echange: Exchange) -> bool:
    """Garde un échange — sauf s'il n'a rien fait : une synchronisation au
    retour dans la fenêtre, toutes les trente secondes, n'a rien à raconter.
    Rend ``True`` s'il a été gardé."""
    if echange.empty:
        return False
    tous = [echange] + load_exchanges(work)
    chemin = Path(work) / EXCHANGES
    chemin.parent.mkdir(parents=True, exist_ok=True)
    temporaire = chemin.with_name(chemin.name + ".dc-tmp")
    temporaire.write_text(json.dumps(
        {"version": 1,
         "exchanges": [e.to_dict() for e in tous[:MAX_EXCHANGES]]},
        ensure_ascii=False), encoding="utf-8")
    os.replace(temporaire, chemin)
    return True


def recent_arrivals(work: Path, limit: int = 12,
                    since: float = 0.0) -> list[tuple[float, str]]:
    """La musique reçue du Deluge, la plus récente d'abord : morceaux,
    presets, kits et échantillons encore présents dans la copie de travail.
    ``(instant, chemin)``, un chemin une seule fois."""
    work = Path(work)
    vus: set[str] = set()
    sortie: list[tuple[float, str]] = []
    for echange in load_exchanges(work):
        if echange.when < since:
            break
        for rel in echange.received:
            cle = _key(rel)
            if cle in vus or rel.split("/", 1)[0].upper() not in MUSIC_DIRS:
                continue
            vus.add(cle)
            if (work / rel).is_file():
                sortie.append((echange.when, rel))
                if len(sortie) >= limit:
                    return sortie
    return sortie


# --------------------------------------------------------------------------- #
# La sauvegarde de la carte
# --------------------------------------------------------------------------- #

@dataclass
class BackupUpdate:
    """Ce qu'une mise à jour de la sauvegarde ferait, ou a fait."""

    added: list[str] = field(default_factory=list)
    replaced: list[str] = field(default_factory=list)
    #: Présents dans la sauvegarde, plus sur la carte : **gardés**.
    kept: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    bytes: int = 0

    def summary(self) -> str:
        morceaux = []
        if self.added:
            morceaux.append("%d ajoutés" % len(self.added))
        if self.replaced:
            morceaux.append("%d remplacés (anciennes versions gardées)"
                            % len(self.replaced))
        if self.kept:
            morceaux.append("%d absents de la carte, gardés" % len(self.kept))
        if self.errors:
            morceaux.append("%d erreur(s)" % len(self.errors))
        return ", ".join(morceaux) if morceaux else "déjà à jour"


def _same_content(a: Path, b: Path) -> bool:
    try:
        if a.stat().st_size != b.stat().st_size:
            return False
        with open(a, "rb") as fa, open(b, "rb") as fb:
            while True:
                x, y = fa.read(1 << 20), fb.read(1 << 20)
                if x != y:
                    return False
                if not x:
                    return True
    except OSError:
        return False


def _same_folder(a, b) -> bool:
    try:
        return (os.path.normcase(os.path.abspath(str(a))).rstrip("\\/")
                == os.path.normcase(os.path.abspath(str(b))).rstrip("\\/"))
    except (TypeError, ValueError):
        return False


def backup_state(work: Path, backup: Path | None = None) -> dict:
    """Ce que la copie de travail sait de la sauvegarde : ``updated`` (date
    de la dernière mise à jour faite par l'application, 0 sinon) et
    ``same`` (fichiers vérifiés identiques). Vide si elle parle d'une autre
    sauvegarde que ``backup``."""
    try:
        brut = json.loads((Path(work) / BACKUP_STATE).read_text(
            encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(brut, dict):
        return {}
    if backup is not None and not _same_folder(brut.get("backup", ""), backup):
        return {}
    return brut


def _save_backup_state(work: Path, backup: Path, same: dict,
                       updated: float) -> None:
    chemin = Path(work) / BACKUP_STATE
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        temporaire = chemin.with_name(chemin.name + ".dc-tmp")
        temporaire.write_text(json.dumps(
            {"version": 1, "backup": str(backup), "updated": updated,
             "same": same}, ensure_ascii=False), encoding="utf-8")
        os.replace(temporaire, chemin)
    except OSError as exc:
        log.debug("état de la sauvegarde non gardé : %s", exc)


def update_backup(work: Path, backup: Path, apply: bool = False,
                  progress: Callable[[str], None] | None = None,
                  should_stop: Callable[[], bool] | None = None
                  ) -> BackupUpdate:
    """Met la sauvegarde à l'image de la copie de travail — donc de la carte.

    Ajoute ce qui manque, remplace ce qui a changé, **ne supprime rien** :
    ce que la carte n'a plus reste dans la sauvegarde. Une version remplacée
    part dans ``<sauvegarde>/.deluge-companion/remplaces/<date>/`` au lieu
    d'être perdue. Sans ``apply``, rien n'est écrit : le plan seulement.

    Un fichier déjà vérifié identique, dont ni la copie ni la sauvegarde
    n'ont bougé depuis (taille et date des deux côtés), n'est pas relu.
    Mesuré chez l'utilisateur sans cette mémoire : 11,3 s à froid, 3,4 s
    ensuite — le contenu de 1,4 Go comparé à chaque fois, et la fenêtre
    figée pendant ce temps.
    """
    work, backup = Path(work), Path(backup)
    rapport = BackupUpdate()
    etat = backup_state(work, backup)
    memoire = etat.get("same") if isinstance(etat.get("same"), dict) else {}
    identiques: dict[str, list[int]] = {}
    locaux = scan_local(work)
    cles_locales = {_key(r) for r in locaux}
    horodatage = time.strftime("%Y-%m-%d_%Hh%M")
    for i, rel in enumerate(sorted(locaux)):
        if should_stop is not None and should_stop():
            break
        if progress is not None and i % 50 == 0:
            progress("Sauvegarde : %d / %d" % (i, len(locaux)))
        source, cible = work / rel, backup / rel
        local = locaux[rel]
        try:
            st = cible.stat()
        except OSError:
            st = None
        if st is not None:
            signature = [local.size, local.mtime_ns, int(st.st_size),
                         int(st.st_mtime_ns)]
            if memoire.get(rel) == signature or _same_content(source, cible):
                identiques[rel] = signature
                continue
            rapport.replaced.append(rel)
        else:
            rapport.added.append(rel)
        rapport.bytes += local.size
        if not apply:
            continue
        try:
            cible.parent.mkdir(parents=True, exist_ok=True)
            if st is not None:
                ancienne = backup / META_DIR / "remplaces" / horodatage / rel
                ancienne.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(cible, ancienne)
            temporaire = cible.with_name(cible.name + ".dc-tmp")
            shutil.copy2(source, temporaire)
            os.replace(temporaire, cible)
            copie = cible.stat()
            identiques[rel] = [local.size, local.mtime_ns,
                               int(copie.st_size), int(copie.st_mtime_ns)]
        except OSError as exc:
            rapport.errors.append("%s : %s" % (rel, exc))
    derniere = float(etat.get("updated", 0) or 0)
    if apply and not rapport.errors:
        derniere = time.time()
    _save_backup_state(work, backup, identiques, derniere)
    for dossier, sous, fichiers in os.walk(backup):
        rel_dossier = Path(dossier).relative_to(backup).as_posix()
        rel_dossier = "" if rel_dossier == "." else rel_dossier
        sous[:] = [s for s in sous
                   if not is_junk((rel_dossier + "/" + s).strip("/"))]
        for nom in fichiers:
            rel = (rel_dossier + "/" + nom).strip("/")
            if not is_junk(rel) and _key(rel) not in cles_locales:
                rapport.kept.append(rel)
    return rapport
