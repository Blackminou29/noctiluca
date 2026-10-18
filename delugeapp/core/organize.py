# -*- coding: utf-8 -*-
"""Réorganisation de la carte : plans d'opérations, simulés puis appliqués.

C'est le module le plus dangereux de l'application. Déplacer un échantillon
que des presets utilisent casse ces presets sans aucun message : le Deluge se
contente de ne plus rien jouer. Trois règles le gouvernent donc :

1. **Rien ne s'exécute à la construction d'un plan.** Un :class:`Plan` est une
   liste d'intentions ; seul :meth:`Plan.apply` touche à la carte (SPEC §0.2).
2. **Tout déplacement est suivi d'une réécriture des références.**
   :meth:`Plan.apply` déplace d'abord, puis réécrit les ``fileName`` de tous
   les XML concernés en un seul passage par fichier.
3. **Jamais d'écrasement.** Une destination déjà occupée fait échouer
   l'opération, qui est rapportée comme erreur, plutôt que de détruire un
   fichier existant.
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import deps
from .analysis import DRUM_CATEGORIES
from .db import Library
from .sdcard import (
    IGNORED_FILES,
    IGNORED_FILES_PREFIX,
    SDCard,
    _is_ignored_dir,
    check_name,
    norm_rel,
    safe_deluge_name,
)

log = logging.getLogger(__name__)

#: Natures d'opérations d'un plan.
OP_KINDS = ("move", "rename", "delete", "mkdir", "relink")

#: Dossier d'accueil des échantillons inutilisés.
DEFAULT_UNUSED_DIR = "_UNUSED"

#: Critères de conservation pour la déduplication.
KEEP_STRATEGIES = ("shortest_path", "longest_path", "most_used", "oldest",
                   "newest")


@dataclass
class Op:
    """Une opération élémentaire sur la carte.

    :param kind: ``'move'``, ``'rename'``, ``'delete'``, ``'mkdir'`` ou
        ``'relink'``.
    :param src: fichier ou dossier concerné.
    :param dst: destination. Pour un ``'delete'`` issu d'une déduplication,
        ``dst`` porte **le fichier conservé** : les références au fichier
        supprimé seront redirigées vers lui, ce qui évite de casser les
        presets qui l'utilisaient.
    :param note: explication affichée à l'utilisateur, en français.
    """

    kind: str
    src: Path
    dst: Path | None = None
    note: str = ""


@dataclass
class Plan:
    """Un ensemble d'opérations à simuler puis appliquer."""

    ops: list[Op] = field(default_factory=list)
    title: str = ""
    #: Octets concernés, quand le plan les a comptés en se construisant
    #: (fichiers parasites) : inutile de les redemander au disque.
    size: int = 0

    def __len__(self) -> int:
        return len(self.ops)

    def __bool__(self) -> bool:
        return bool(self.ops)

    def counts(self) -> dict[str, int]:
        """Nombre d'opérations par nature."""
        out: dict[str, int] = {}
        for op in self.ops:
            out[op.kind] = out.get(op.kind, 0) + 1
        return out

    def summary(self) -> str:
        """Résumé en français, affichable tel quel."""
        if not self.ops:
            return "Aucune modification à faire."
        labels = {"move": "déplacement", "rename": "renommage",
                  "delete": "suppression", "mkdir": "création de dossier",
                  "relink": "références à réécrire"}
        counts = self.counts()
        parts = []
        for kind, count in sorted(counts.items(), key=lambda kv: -kv[1]):
            label = labels.get(kind, kind)
            if count > 1 and not label.endswith("s"):
                label += "s"
            parts.append(f"{count} {label}")
        head = f"{self.title} : " if self.title else ""
        return head + ", ".join(parts) + "."

    def to_text(self) -> str:
        """Détail ligne par ligne, pour relecture avant application."""
        lines = [self.summary(), ""]
        for op in self.ops:
            if op.dst is not None:
                lines.append(f"[{op.kind}] {op.src}  ->  {op.dst}"
                             + (f"   ({op.note})" if op.note else ""))
            else:
                lines.append(f"[{op.kind}] {op.src}"
                             + (f"   ({op.note})" if op.note else ""))
        return "\n".join(lines)

    # -- application -------------------------------------------------------- #

    def apply(self, sd: SDCard, lib: Library,
              progress: Callable[[str], None] | None = None,
              ) -> tuple[int, list[str]]:
        """Exécute le plan. Retourne ``(opérations réussies, erreurs)``.

        L'ordre est imposé par la sécurité des données :

        1. créer les dossiers ;
        2. déplacer et renommer, en retenant chaque ``ancien -> nouveau`` ;
        3. **réécrire les références** des XML en un seul passage ;
        4. supprimer en dernier, une fois les références redirigées.

        Une opération en échec n'interrompt pas le plan : son message est
        ajouté à la liste d'erreurs et le reste continue.
        """
        done = 0
        errors: list[str] = []
        mapping: dict[str, str] = {}

        def _report(text: str) -> None:
            if progress is not None:
                try:
                    progress(text)
                except Exception:  # noqa: BLE001 - l'affichage ne bloque rien
                    pass

        # 1. Dossiers
        for op in self.ops:
            if op.kind != "mkdir":
                continue
            try:
                op.src.mkdir(parents=True, exist_ok=True)
                done += 1
            except OSError as exc:
                errors.append(f"Création de {op.src} impossible : {exc}")

        # 2. Déplacements et renommages
        for op in self.ops:
            if op.kind not in ("move", "rename") or op.dst is None:
                continue
            _report(op.src.name)
            try:
                if not op.src.exists():
                    errors.append(f"{sd.rel(op.src)} : fichier introuvable")
                    continue
                if op.dst.exists() and not _same_file(op.src, op.dst):
                    errors.append(
                        f"{sd.rel(op.dst)} existe déjà : {sd.rel(op.src)} "
                        f"n'a pas été déplacé")
                    continue
                op.dst.parent.mkdir(parents=True, exist_ok=True)
                old_rel = sd.rel(op.src)
                new_rel = sd.rel(op.dst)
                shutil.move(str(op.src), str(op.dst))
                if norm_rel(old_rel) != norm_rel(new_rel):
                    mapping[old_rel] = new_rel
                lib.move(_kind_of(old_rel), old_rel, new_rel)
                done += 1
            except (OSError, shutil.Error) as exc:
                errors.append(f"Déplacement de {sd.rel(op.src)} impossible : {exc}")

        # 3. Références à rediriger, de deux provenances :
        #    - une suppression de doublon pointe vers l'exemplaire conservé ;
        #    - une opération 'relink' ne fait que changer un chemin dans les
        #      XML, sans déplacer aucun fichier (cas d'un échantillon déjà
        #      présent ailleurs, que les presets cherchaient au mauvais
        #      endroit).
        # Un doublon n'est retiré que s'il est **encore** identique, octet
        # pour octet, à l'exemplaire gardé : l'index a pu vieillir, ou
        # décrire une autre carte aux mêmes chemins. Vérifié avant de
        # rediriger quoi que ce soit.
        refuses: set[int] = set()
        for index, op in enumerate(self.ops):
            if op.kind != "delete" or op.dst is None or not op.src.is_file():
                continue
            garde = sd.abs(mapping.get(sd.rel(op.dst), sd.rel(op.dst)))
            if not _identical(op.src, garde):
                refuses.add(index)
                errors.append(f"{sd.rel(op.src)} conservé : il ne correspond "
                              f"plus à {sd.rel(garde)} octet pour octet")

        redirections: dict[str, str] = {}
        for index, op in enumerate(self.ops):
            if index in refuses:
                continue
            if op.kind in ("delete", "relink") and op.dst is not None:
                target = sd.rel(op.dst)
                # Si la cible a elle-même été déplacée à l'étape 2, suivre le
                # déplacement : sans cela, on redirigerait les références vers
                # un chemin qui vient d'être vidé.
                target = mapping.get(target, target)
                mapping[sd.rel(op.src)] = target
                redirections[sd.rel(op.src)] = target

        relink_ok = True
        if mapping:
            sd.invalidate_cache()
            _report("Réécriture des références…")
            failures: list[str] = []
            try:
                changed = deps.relink_many(sd, mapping, apply=True,
                                           progress=lambda n: _report(n),
                                           failures=failures)
                done += len(changed)
                log.info("%d fichier(s) XML mis à jour", len(changed))
            except Exception as exc:  # noqa: BLE001
                log.exception("réécriture des références en échec")
                failures.append(f"Réécriture des références : {exc}")
            if failures:
                relink_ok = False
                errors.extend(failures)
            elif relink_ok:
                for old_rel, new_rel in redirections.items():
                    lib.retarget_links(old_rel, new_rel)

        # 4. Suppressions. Un doublon dont les références n'ont pas toutes
        #    été redirigées est gardé : le supprimer casserait les presets
        #    qui le citent encore.
        for index, op in enumerate(self.ops):
            if op.kind != "delete" or index in refuses:
                continue
            if op.dst is not None and not relink_ok:
                errors.append(f"{sd.rel(op.src)} conservé : ses références "
                              f"n'ont pas pu être toutes redirigées")
                continue
            _report(op.src.name)
            try:
                if op.src.is_dir():
                    op.src.rmdir()
                elif op.src.exists():
                    op.src.unlink()
                else:
                    continue
                lib.forget(_kind_of(sd.rel(op.src)), sd.rel(op.src))
                done += 1
            except OSError as exc:
                errors.append(f"Suppression de {sd.rel(op.src)} impossible : {exc}")

        sd.invalidate_cache()
        # L'index suit les fichiers : le diagnostic relancé juste après doit
        # voir la carte telle qu'elle est devenue.
        lib.recompute_usage()
        log.info("plan appliqué : %d opération(s), %d erreur(s)", done, len(errors))
        return done, errors


def _identical(a: Path, b: Path) -> bool:
    """Vrai si les deux fichiers ont exactement le même contenu."""
    import filecmp

    try:
        return b.is_file() and filecmp.cmp(a, b, shallow=False)
    except OSError:
        return False


def _same_file(a: Path, b: Path) -> bool:
    """Vrai si les deux chemins désignent le même fichier (casse comprise)."""
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return str(a).lower() == str(b).lower()


def _kind_of(rel: str) -> str:
    """Nature d'un fichier d'après son emplacement sur la carte."""
    top = norm_rel(rel).split("/", 1)[0]
    return {"samples": "sample", "synths": "synth", "kits": "kit",
            "songs": "song"}.get(top, "sample")


# --------------------------------------------------------------------------- #
# Suggestion de rangement
# --------------------------------------------------------------------------- #

def suggest_folder(name: str, category: str) -> str:
    """Dossier conseillé pour un échantillon, selon sa catégorie.

    Les catégories de percussions du Deluge vont dans ``SAMPLES/DRUMS/<cat>``,
    qui est l'arborescence que la machine attend ; le reste est rangé par
    famille.
    """
    cat = str(category or "").strip()
    if cat in DRUM_CATEGORIES:
        return f"SAMPLES/DRUMS/{cat}"
    lowered = f"{name} {cat}".lower()
    if any(w in lowered for w in ("loop", "boucle", "break")):
        return "SAMPLES/CLIPS"
    if any(w in lowered for w in ("vocal", "voix", "voice", "choir")):
        return "SAMPLES/MULTISAMPLES/Voix"
    if any(w in lowered for w in ("bass", "basse", "sub")):
        return "SAMPLES/MULTISAMPLES/Basses"
    if any(w in lowered for w in ("pad", "nappe", "string", "atmo")):
        return "SAMPLES/MULTISAMPLES/Nappes"
    if cat:
        return f"SAMPLES/MULTISAMPLES/{safe_deluge_name(cat)}"
    return "SAMPLES/MULTISAMPLES/Divers"


# --------------------------------------------------------------------------- #
# Plans
# --------------------------------------------------------------------------- #

def plan_auto_classify_drums(sd: SDCard, lib: Library) -> Plan:
    """Range les percussions éparses dans ``SAMPLES/DRUMS/<catégorie>``.

    Ne touche qu'aux fichiers déjà sous ``SAMPLES`` et **déjà bien reconnus** :
    les échantillons classés ``Other`` sont laissés où ils sont, parce qu'un
    rangement douteux est plus gênant qu'un fichier non rangé.
    """
    plan = Plan(title="Classement automatique des percussions")
    try:
        from . import analysis
        from . import wav
    except ImportError as exc:  # pragma: no cover - numpy est obligatoire
        log.error("analyse indisponible : %s", exc)
        return plan

    for row in lib.search_samples(limit=100000):
        rel = row["rel"]
        parts = norm_rel(rel).split("/")
        if not parts or parts[0] != "samples":
            continue
        # Déjà rangé dans la bonne catégorie ?
        if len(parts) >= 3 and parts[1] == "drums":
            continue
        path = sd.resolve_sample(rel)
        if path is None:
            continue
        # Un son long n'est pas une percussion.
        duration = row["duration"] or 0.0
        if duration <= 0 or duration > 3.0:
            continue
        try:
            data, sr = wav.read(path, mono=True, max_frames=(row["sr"] or 44100) * 3)
            spec = analysis.spectral(data, sr)
        except Exception as exc:  # noqa: BLE001
            log.debug("analyse de %s impossible : %s", rel, exc)
            continue
        category = analysis.classify_drum(path.name, {"duration": duration}, spec)
        if category in ("", "Other"):
            continue
        dst_dir = f"SAMPLES/DRUMS/{category}"
        if norm_rel(str(Path(rel).parent)) == norm_rel(dst_dir):
            continue
        plan.ops.append(Op("move", path, sd.abs(f"{dst_dir}/{path.name}"),
                           f"reconnu comme « {category} »"))
    return plan


def plan_dedupe(sd: SDCard, lib: Library,
                keep: str = "shortest_path") -> Plan:
    """Supprime les doublons **confirmés**, en redirigeant les références.

    N'opère que sur les groupes validés octet pour octet par
    ``scan.confirm_duplicates`` : l'empreinte rapide produit des faux positifs
    et ferait perdre de vrais échantillons (cf. SPEC §4.9).

    :param keep: lequel garder — ``shortest_path`` (défaut), ``longest_path``,
        ``most_used``, ``oldest`` ou ``newest``.
    """
    plan = Plan(title="Suppression des doublons")
    if keep not in KEEP_STRATEGIES:
        log.warning("critère de conservation inconnu : %r", keep)
        keep = "shortest_path"

    for group in lib.duplicates():
        if len(group) < 2:
            continue
        rows = list(group)
        if keep == "shortest_path":
            rows.sort(key=lambda r: (len(r["rel"]), r["rel"]))
        elif keep == "longest_path":
            rows.sort(key=lambda r: (-len(r["rel"]), r["rel"]))
        elif keep == "most_used":
            rows.sort(key=lambda r: (-(r["used_count"] or 0), len(r["rel"])))
        elif keep == "oldest":
            rows.sort(key=lambda r: (r["mtime"] or 0.0))
        else:
            rows.sort(key=lambda r: -(r["mtime"] or 0.0))

        kept = rows[0]
        kept_path = sd.resolve_sample(kept["rel"])
        if kept_path is None:
            continue
        for row in rows[1:]:
            path = sd.resolve_sample(row["rel"])
            if path is None:
                continue
            used = row["used_count"] or 0
            note = (f"identique à {kept['rel']}"
                    + (f" ; {used} référence(s) redirigée(s)" if used else ""))
            # dst porte le fichier conservé : apply() redirigera les références.
            plan.ops.append(Op("delete", path, kept_path, note))
    return plan


class _FallbackRow:
    """Ligne d'échantillon minimale, quand l'index n'a rien sur ce fichier.

    Donne le même accès par clé qu'un ``sqlite3.Row``, en rendant ``None``
    pour les colonnes inconnues.
    """

    def __init__(self, rel: str) -> None:
        self._values = {"rel": rel, "category": "", "bpm": None, "key": "",
                        "sr": None, "duration": None}

    def __getitem__(self, key: str):
        return self._values.get(key)


def _format_pattern(pattern: str, row, index: int, sd: SDCard) -> str:
    """Applique un motif de renommage à une ligne d'échantillon.

    Jetons reconnus : ``{name} {n} {n:03} {folder} {cat} {bpm} {key} {sr}
    {dur}``. Un jeton inconnu est laissé tel quel plutôt que de faire échouer
    le renommage de toute une sélection.
    """
    rel = row["rel"]
    values = {
        "name": Path(rel).stem,
        "n": index,
        "folder": Path(rel).parent.name,
        "cat": row["category"] or "",
        "bpm": f"{row['bpm']:.0f}" if row["bpm"] else "",
        "key": row["key"] or "",
        "sr": row["sr"] or "",
        "dur": f"{row['duration']:.2f}" if row["duration"] else "",
    }
    try:
        return pattern.format(**values)
    except (KeyError, IndexError, ValueError) as exc:
        log.debug("motif de renommage inapplicable (%r) : %s", pattern, exc)
        return Path(rel).stem


def plan_rename(sd: SDCard, items: list[str], pattern: str,
                apply_case: str = "", lib: Library | None = None) -> Plan:
    """Renomme une sélection d'échantillons selon un motif.

    :param items: chemins relatifs à renommer.
    :param pattern: motif, cf. :func:`_format_pattern`.
    :param apply_case: ``'upper'``, ``'lower'``, ``'title'`` ou ``''``.
    """
    plan = Plan(title="Renommage")
    rows_by_rel: dict[str, object] = {}
    if lib is not None:
        try:
            rows_by_rel = {r["rel"]: r for r in lib.search_samples(limit=100000)}
        except Exception as exc:  # noqa: BLE001
            log.debug("index indisponible pour le renommage : %s", exc)

    taken: set[str] = set()
    for index, rel in enumerate(items, 1):
        path = sd.resolve_sample(rel)
        if path is None:
            continue
        row = rows_by_rel.get(rel) or _FallbackRow(rel)
        stem = _format_pattern(pattern, row, index, sd)
        if apply_case == "upper":
            stem = stem.upper()
        elif apply_case == "lower":
            stem = stem.lower()
        elif apply_case == "title":
            stem = stem.title()
        stem = safe_deluge_name(stem)
        new_name = f"{stem}{path.suffix}"
        dst = path.parent / new_name
        key = norm_rel(sd.rel(dst))
        if key in taken:
            # Deux fichiers ne peuvent pas prendre le même nom.
            stem = f"{stem} {index}"
            dst = path.parent / f"{stem}{path.suffix}"
            key = norm_rel(sd.rel(dst))
        if norm_rel(sd.rel(path)) == key:
            continue
        taken.add(key)
        plan.ops.append(Op("rename", path, dst, f"motif « {pattern} »"))
    return plan


def plan_flatten(sd: SDCard, folder: str) -> Plan:
    """Remonte tous les fichiers des sous-dossiers de ``folder`` dans ``folder``.

    Les collisions de noms sont évitées en préfixant le nom du sous-dossier
    d'origine, ce qui garde l'information plutôt que de numéroter.
    """
    plan = Plan(title=f"Mise à plat de {folder}")
    base = sd.resolve_sample(folder)
    if base is None or not base.is_dir():
        return plan

    seen: set[str] = set()
    try:
        for entry in os.scandir(base):
            if entry.is_file():
                seen.add(entry.name.lower())
    except OSError as exc:
        log.debug("dossier illisible %s : %s", base, exc)
        return plan

    for path in sorted(base.rglob("*")):
        if not path.is_file() or path.parent == base:
            continue
        if path.name.startswith(IGNORED_FILES_PREFIX):
            continue
        name = path.name
        if name.lower() in seen:
            prefix = safe_deluge_name(path.parent.name)
            name = f"{prefix} - {path.name}"
        seen.add(name.lower())
        plan.ops.append(Op("move", path, base / name,
                           f"remonté de {path.parent.name}"))
    return plan


def plan_group_by(sd: SDCard, lib: Library, key: str) -> Plan:
    """Regroupe les échantillons dans des sous-dossiers selon un critère.

    :param key: ``'category'``, ``'bpm'``, ``'key'``, ``'duration'`` ou
        ``'artist'``.
    """
    plan = Plan(title=f"Regroupement par {key}")
    for row in lib.search_samples(limit=100000):
        rel = row["rel"]
        path = sd.resolve_sample(rel)
        if path is None:
            continue
        bucket = _bucket_for(row, key)
        if not bucket:
            continue
        parent = Path(rel).parent.as_posix()
        folder = safe_deluge_name(bucket)
        dst_dir = f"{parent}/{folder}"
        # Déjà dans le bon sous-dossier ? On compare le dernier segment entier :
        # un simple suffixe prenait « BigKick » pour le dossier « Kick ».
        if norm_rel(parent).rsplit("/", 1)[-1] == norm_rel(folder):
            continue
        plan.ops.append(Op("move", path, sd.abs(f"{dst_dir}/{path.name}"),
                           f"{key} = {bucket}"))
    return plan


def _bucket_for(row, key: str) -> str:
    """Nom de sous-dossier correspondant au critère de regroupement."""
    if key == "category":
        return str(row["category"] or "")
    if key == "bpm":
        bpm = row["bpm"]
        if not bpm:
            return ""
        low = int(bpm // 10 * 10)
        return f"{low}-{low + 9} BPM"
    if key == "key":
        return str(row["key"] or "")
    if key == "duration":
        dur = row["duration"] or 0.0
        if dur <= 0:
            return ""
        if dur < 1:
            return "Moins de 1 s"
        if dur < 5:
            return "1 a 5 s"
        if dur < 30:
            return "5 a 30 s"
        return "Plus de 30 s"
    if key == "artist":
        parts = Path(row["rel"]).parts
        return parts[2] if len(parts) > 3 and parts[1].upper() == "ARTISTS" else ""
    return ""


def plan_purge_junk(sd: SDCard) -> Plan:
    """Supprime les parasites : ``._*``, ``.DS_Store``, ``Thumbs.db``.

    Ne touche **jamais** aux corbeilles ni aux dossiers système : elles sont
    écartées du parcours, et leur suppression n'est pas du ressort de cette
    application.
    """
    plan = Plan(title="Nettoyage des fichiers parasites")
    # Parcours par ``os.scandir`` plutôt que ``rglob`` : les dossiers ignorés
    # sont élagués au lieu d'être parcourus puis écartés, seuls des noms —
    # des chaînes — sont comparés, et sous Windows la taille vient avec
    # l'entrée de répertoire, sans interroger le disque. Le parcours
    # précédent créait un chemin relatif et un ``stat`` par fichier : 0,82 s
    # sur la carte de l'utilisateur (16 936 fichiers), 90 % du diagnostic de
    # santé, que le tableau de bord relançait à chaque affichage.
    junk: list[tuple[str, int]] = []
    pile = [str(sd.root)]
    while pile:
        dossier = pile.pop()
        try:
            with os.scandir(dossier) as entrees:
                for entree in entrees:
                    try:
                        if entree.is_dir(follow_symlinks=False):
                            # Ne pas descendre dans les dossiers ignorés — la
                            # même liste que tous les parcours.
                            if not _is_ignored_dir(entree.name):
                                pile.append(entree.path)
                            continue
                        if not (entree.name.startswith(IGNORED_FILES_PREFIX)
                                or entree.name.lower() in IGNORED_FILES):
                            continue
                        if not entree.is_file():
                            continue
                    except OSError:
                        continue
                    try:
                        size = entree.stat().st_size
                    except OSError:
                        size = 0
                    junk.append((entree.path, size))
        except OSError as exc:
            log.debug("dossier illisible pendant le nettoyage : %s", exc)
    for chemin, size in sorted(junk, key=lambda item: Path(item[0])):
        plan.ops.append(Op("delete", Path(chemin), None,
                           f"fichier parasite ({size} octets)"))
        plan.size += size
    return plan


def plan_archive_unused(sd: SDCard, lib: Library,
                        dest: str = DEFAULT_UNUSED_DIR) -> Plan:
    """Déplace les échantillons inutilisés dans un dossier d'archive.

    Déplacer plutôt que supprimer : « inutilisé » veut seulement dire
    « aucun XML de cette carte ne le cite », ce qui n'empêche pas
    l'utilisateur d'y tenir.
    """
    plan = Plan(title="Archivage des échantillons inutilisés")
    base = str(dest or DEFAULT_UNUSED_DIR).strip("/") or DEFAULT_UNUSED_DIR
    for row in lib.unused_samples():
        rel = row["rel"]
        path = sd.resolve_sample(rel)
        if path is None:
            continue
        if (norm_rel(rel) + "/").startswith(norm_rel(base) + "/"):
            continue
        # On conserve l'arborescence sous le dossier d'archive.
        inner = Path(rel)
        try:
            inner = inner.relative_to("SAMPLES")
        except ValueError:
            pass
        size_mb = (row["size"] or 0) / (1024 * 1024)
        plan.ops.append(Op("move", path, sd.abs(f"{base}/{inner.as_posix()}"),
                           f"inutilisé ({size_mb:.1f} Mio)"))
    return plan


def plan_fix_names(sd: SDCard, lib: Library) -> Plan:
    """Corrige les noms incompatibles avec FAT32 ou l'écran du Deluge."""
    plan = Plan(title="Correction des noms de fichiers")
    seen: set[str] = set()

    def _consider(rel: str, path: Path | None) -> None:
        if path is None:
            return
        problems = check_name(path.stem)
        if not problems:
            return
        stem = safe_deluge_name(path.stem)
        if not stem or stem == path.stem:
            return
        dst = path.parent / f"{stem}{path.suffix}"
        key = norm_rel(sd.rel(dst))
        if key in seen:
            return
        seen.add(key)
        plan.ops.append(Op("rename", path, dst, " ; ".join(problems)))

    for row in lib.search_samples(limit=100000):
        _consider(row["rel"], sd.resolve_sample(row["rel"]))
    # Un morceau désigne ses presets **par leur nom** : en renommer un que
    # cite un morceau couperait ce lien, et aucune réécriture ne le rétablit
    # (les morceaux ne sont jamais réécrits pour cela). Ceux-là restent.
    cites = _preset_names_in_songs(sd)
    for kind in ("synth", "kit"):
        for row in lib.search_presets(kind=kind, limit=100000):
            if norm_rel(Path(row["rel"]).stem) in cites:
                continue
            _consider(row["rel"], sd.abs(row["rel"]))
    return plan


def _preset_names_in_songs(sd: SDCard) -> set[str]:
    """Noms (normalisés) des presets et kits que citent les morceaux."""
    from .model import Song

    noms: set[str] = set()
    for path in sd.songs():
        try:
            for _kind, name, _folder in Song.load(path).preset_refs():
                if name:
                    noms.add(norm_rel(name))
        except Exception as exc:  # noqa: BLE001 - un morceau illisible
            log.debug("morceau illisible %s : %s", path.name, exc)
    return noms


def plan_create_drum_folders(sd: SDCard) -> Plan:
    """Crée l'arborescence ``SAMPLES/DRUMS/<catégorie>`` attendue par le Deluge."""
    plan = Plan(title="Création de l'arborescence des percussions")
    for category in DRUM_CATEGORIES:
        if category == "Other":
            continue
        target = sd.abs(f"SAMPLES/DRUMS/{category}")
        if not target.is_dir():
            plan.ops.append(Op("mkdir", target, None,
                               "dossier de percussion standard"))
    return plan
