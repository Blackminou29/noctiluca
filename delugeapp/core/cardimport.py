# -*- coding: utf-8 -*-
"""Envoyer au Deluge : des fichiers du PC vers sa carte.

Depuis que la carte reste dans la machine (firmware 1.3, SPEC §4.33),
l'Explorateur ne l'atteint plus : c'est l'application qui pose sur la carte
les sons, les presets et les packs venus du PC. Ce module en fait un
**plan**, puis le copie — dans la copie de travail, d'où la synchronisation
l'envoie par le câble, ou directement sur une carte glissée dans un lecteur.

Mesuré chez l'utilisateur avant de l'écrire (18 octobre 2026) :

* ses 1 294 WAV du PC sont dans deux packs téléchargés. L'un reprend
  l'arborescence de la carte (``SAMPLES/MULTISAMPLES/…`` et
  ``SYNTHS/Artists/…``) et ses 766 références se résolvent toutes dans le
  pack ; l'autre non (``TJ SAMPLES/…``, ``TJ SYNTHS/SYNTHS/…``) ;
* 169 de ces fichiers sont des parasites de macOS (``._*``), à côté de
  dossiers ``__MACOSX`` venus des archives ;
* tous les vrais WAV, comme les 1 745 échantillons de la carte, respectent
  les règles de lecture du firmware (:func:`wav.deluge_problem`) ;
* 271 Mo par le câble, c'est près d'une heure trois quarts à 45 Ko/s : le
  plan le dit avant de copier.

Les règles
----------

* **rien d'existant n'est remplacé.** Un fichier identique déjà sur la carte
  est laissé ; un homonyme différent fait numéroter le nouveau
  (« Kick 2.wav ») — sauf dans un pack, dont les presets citent les chemins :
  le fichier de la carte est gardé, et c'est dit ;
* **les noms deviennent transmissibles** : ASCII (le câble perd le bit 7),
  sans caractère interdit par FAT32. Dans un pack, les presets suivent ;
* **un fichier que la machine refuserait n'est pas copié tel quel** :
  converti quand c'est sans perte audible (en-tête étendu, A-law…), refusé
  sinon, avec sa raison ;
* tout ce qui n'est pas du Deluge (MP3, documentation, fichiers de logiciels
  de MAO) reste sur le PC, et la liste dit pourquoi.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import dxml, wav
from ..i18n import N_, tr, untranslated
from .delugefiles import MAX_PATH, cable_time
from .sdcard import FORBIDDEN_CHARS, RESERVED_NAMES, SDCard, norm_rel

log = logging.getLogger(__name__)

__all__ = ["ImportItem", "ImportPlan", "ImportResult", "ImportScan",
           "apply_import", "card_files", "card_name", "card_path",
           "plan_import", "sample_folders", "scan_sources"]

#: Les quatre dossiers de la carte, et ce que chacun contient.
CARD_DIRS = ("SAMPLES", "SYNTHS", "KITS", "SONGS")
KIND_DIRS = {"sample": "SAMPLES", "synth": "SYNTHS", "kit": "KITS",
             "song": "SONGS"}
#: Racine d'un XML du Deluge -> nature.
XML_ROOTS = {"sound": "synth", "kit": "kit", "song": "song"}

#: Dossiers de passage des archives et des systèmes : jamais parcourus.
_JUNK_DIRS = untranslated({"__macosx", ".trashes", ".spotlight-v100",
                           ".fseventsd", "system volume information",
                           "$recycle.bin", ".git"})
#: Fichiers que les systèmes et les logiciels de MAO laissent à côté des
#: sons (``.reapeaks`` de Reaper : quatre sur la carte de l'utilisateur).
_JUNK_FILES = {".ds_store", "thumbs.db", "desktop.ini"}
_JUNK_EXT = (".reapeaks", ".reapindex", ".asd", ".pkf")
#: Ce qui n'est pas pour le Deluge, et pourquoi.
_OTHER_AUDIO = (".mp3", ".flac", ".ogg", ".m4a", ".aac", ".wma", ".opus")
_DOCS = (".txt", ".pdf", ".md", ".rtf", ".html", ".htm", ".png", ".jpg",
         ".jpeg", ".gif", ".url", ".nfo", ".doc", ".docx")

#: Ce que devient chaque fichier, en clair.
ACTIONS = {"copy": N_("à copier"), "convert": N_("à convertir puis copier"),
           "same": N_("déjà sur la carte"), "kept": N_("laissé tel quel sur la "
                                                       "carte"),
           "refused": N_("refusé")}

#: Lettres sans décomposition ASCII.
_TRANSLIT = {"ß": "ss", "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE",
             "ø": "o", "Ø": "O", "đ": "d", "Đ": "D", "ł": "l", "Ł": "L",
             "þ": "th", "Þ": "TH", "µ": "u", "×": "x", "–": "-", "—": "-",
             "’": "'", "‘": "'", "“": "'", "”": "'", "«": "'", "»": "'",
             "€": "EUR", "°": "o"}


def card_name(name: str) -> str:
    """Un nom de fichier ou de dossier qui passe par le câble et sur FAT32.

    Translittéré en ASCII (« Épée » -> « Epee » ; le câble perd le bit 7 des
    noms, mesuré), caractères interdits par FAT32 remplacés par « _ », sans
    point ni espace à la fin, jamais un nom réservé de Windows. Rien n'est
    tronqué, contrairement à :func:`sdcard.safe_deluge_name` : un pack cite
    ses fichiers par leur nom exact.
    """
    sortie = []
    for c in unicodedata.normalize("NFKD", str(name)):
        if unicodedata.combining(c):
            continue
        o = ord(c)
        if o < 32 or o == 127 or c in FORBIDDEN_CHARS:
            sortie.append("_")
        elif o > 126:
            sortie.append(_TRANSLIT.get(c, "_"))
        else:
            sortie.append(c)
    texte = "".join(sortie).strip().rstrip(" .")
    if not texte:
        return "_"
    if texte.split(".")[0].upper() in RESERVED_NAMES:
        texte = "_" + texte
    return texte


def card_path(rel: str) -> str:
    return "/".join(card_name(p) for p in str(rel).split("/") if p)


# --------------------------------------------------------------------------- #
# Ce qui a été déposé
# --------------------------------------------------------------------------- #

@dataclass
class Found:
    """Un fichier du Deluge trouvé dans ce qui a été déposé."""

    path: Path
    size: int
    kind: str
    #: Son chemin sur la carte, s'il vient d'un pack qui en a la forme.
    pack_rel: str = ""
    #: Sinon, son chemin sous le dossier de destination.
    loose_rel: str = ""
    #: Pourquoi le Deluge le refuserait, et si cela se répare.
    problem: str = ""
    fixable: bool = False
    #: Les échantillons qu'il cite (preset, kit, morceau).
    refs: list[str] = field(default_factory=list)


@dataclass
class ImportScan:
    """Ce qui a été déposé, lu une fois — en-têtes audio et XML compris."""

    found: list[Found] = field(default_factory=list)
    #: ``(chemin affiché, raison)`` : restent sur le PC.
    ignored: list[tuple[str, str]] = field(default_factory=list)
    #: Parasites écartés sans un mot (``._*``, ``.DS_Store``, ``__MACOSX``).
    junk: int = 0
    #: Arrêté avant la fin.
    stopped: bool = False

    @property
    def has_loose_samples(self) -> bool:
        return any(f.kind == "sample" and not f.pack_rel for f in self.found)


def _junk_name(nom: str) -> bool:
    bas = nom.casefold()
    return (nom.startswith("._") or bas in _JUNK_FILES
            or bas.endswith(_JUNK_EXT))


def _card_roots(dossier: Path) -> list[Path]:
    """Les dossiers qui ont la forme d'une carte : un enfant SAMPLES,
    SYNTHS, KITS ou SONGS. Cherchés jusqu'à deux niveaux sous ``dossier``
    — « TJ SYNTHS/SYNTHS » dans un pack réel —, les plus profonds d'abord."""
    racines: list[Path] = []
    a_voir = [(dossier, 0)]
    while a_voir:
        courant, profondeur = a_voir.pop()
        try:
            enfants = [e for e in os.scandir(courant) if e.is_dir()]
        except OSError:
            continue
        if any(e.name.upper() in CARD_DIRS for e in enfants):
            racines.append(courant)
        if profondeur < 2:
            a_voir.extend((Path(e.path), profondeur + 1) for e in enfants
                          if e.name.casefold() not in _JUNK_DIRS
                          and e.name.upper() not in CARD_DIRS)
    return sorted(racines, key=lambda p: len(p.parts), reverse=True)


def _pack_rel(chemin: Path, racines: list[Path]) -> str:
    """Le chemin sur la carte d'un fichier de pack, ou ``""``."""
    for racine in racines:
        try:
            parties = chemin.relative_to(racine).parts
        except ValueError:
            continue
        if len(parties) >= 2 and parties[0].upper() in CARD_DIRS:
            return "/".join((parties[0].upper(),) + parties[1:])
    return ""


def _read_xml(chemin: Path) -> tuple[str, list[str], str]:
    """``(nature, références, erreur)`` d'un XML."""
    try:
        doc = dxml.load(chemin)
    except dxml.DelugeXMLError as exc:
        return "", [], tr("XML illisible : %s") % exc
    nature = XML_ROOTS.get(str(doc.root.tag))
    if nature is None:
        return "", [], ""
    refs = sorted({v for v in (dxml.get(n, "fileName") for n in doc.root.iter())
                   if v})
    return nature, refs, ""


def scan_sources(sources, progress: Callable[[str], None] | None = None,
                 should_stop: Callable[[], bool] | None = None) -> ImportScan:
    """Lit ce qui a été déposé : fichiers, dossiers, packs.

    Le coûteux est ici — un en-tête par son, chaque XML analysé —, et il ne
    dépend pas de la destination : le plan, lui, se recalcule à volonté.
    """
    scan = ImportScan()
    compte = 0

    def ajouter(chemin: Path, pack_rel: str, loose_rel: str) -> None:
        nonlocal compte
        compte += 1
        if progress is not None and compte % 50 == 0:
            progress(tr("Lecture de ce qui est déposé : %d fichiers…") % compte)
        ext = chemin.suffix.lower()
        try:
            taille = chemin.stat().st_size
        except OSError as exc:
            scan.ignored.append((str(chemin), tr("illisible : %s") % exc))
            return
        if ext in wav.DELUGE_EXT + (".aifc",):
            probleme, reparable = wav.deluge_problem(chemin)
            scan.found.append(Found(chemin, taille, "sample", pack_rel,
                                    loose_rel, probleme, reparable))
        elif ext == ".xml":
            nature, refs, erreur = _read_xml(chemin)
            if erreur:
                scan.ignored.append((str(chemin), erreur))
            elif not nature:
                scan.ignored.append((str(chemin), tr("XML qui n'est ni un "
                                        "preset, ni un kit, ni un morceau : "
                                        "réglage de la machine, non envoyé")))
            else:
                scan.found.append(Found(chemin, taille, nature, pack_rel,
                                        loose_rel, refs=refs))
        elif ext in _OTHER_AUDIO:
            scan.ignored.append((str(chemin), tr("le Deluge ne lit que le WAV et "
                                    "l'AIFF : exportez-le en WAV depuis votre "
                                    "logiciel")))
        elif ext in (".mid", ".midi"):
            scan.ignored.append((str(chemin), tr("le Deluge ne lit pas les "
                                    "fichiers MIDI")))
        elif ext == ".bin" and chemin.name.lower().startswith("deluge"):
            scan.ignored.append((str(chemin), tr("firmware : il s'installe à la "
                                    "main, jamais par l'application")))
        elif ext in _DOCS:
            scan.ignored.append((str(chemin), tr("documentation : reste sur le "
                                    "PC")))
        else:
            scan.ignored.append((str(chemin), tr("pas un fichier du Deluge")))

    for source in sources:
        if should_stop is not None and should_stop():
            scan.stopped = True
            break
        source = Path(source)
        if _junk_name(source.name) or source.name.casefold() in _JUNK_DIRS:
            scan.junk += 1
            continue
        if source.is_file():
            ajouter(source, "", source.name)
            continue
        if not source.is_dir():
            scan.ignored.append((str(source), "introuvable"))
            continue
        # Un dossier SAMPLES, SYNTHS… déposé seul va dans le dossier du même
        # nom de la carte.
        racines = ([source.parent] if source.name.upper() in CARD_DIRS
                   else _card_roots(source))
        for dossier, sous, fichiers in os.walk(source):
            if should_stop is not None and should_stop():
                scan.stopped = True
                break
            gardes = [s for s in sous if s.casefold() not in _JUNK_DIRS
                      and not s.startswith(".")]
            scan.junk += len(sous) - len(gardes)
            sous[:] = sorted(gardes)
            for nom in sorted(fichiers):
                if _junk_name(nom):
                    scan.junk += 1
                    continue
                chemin = Path(dossier) / nom
                pack = _pack_rel(chemin, racines)
                vrac = "" if pack else "/".join(
                    (source.name,) + chemin.relative_to(source).parts)
                ajouter(chemin, pack, vrac)
    return scan


# --------------------------------------------------------------------------- #
# Le plan
# --------------------------------------------------------------------------- #

@dataclass
class ImportItem:
    """Un fichier déposé, et ce qu'il deviendra."""

    source: Path
    rel: str
    kind: str
    size: int
    action: str
    reason: str = ""
    #: Le chemin qu'il aurait eu sans nettoyage ni numérotation.
    original: str = ""

    @property
    def label(self) -> str:
        return ACTIONS.get(self.action, self.action)


@dataclass
class ImportPlan:
    """Ce que l'envoi ferait. Rien n'a encore été copié."""

    items: list[ImportItem] = field(default_factory=list)
    ignored: list[tuple[str, str]] = field(default_factory=list)
    junk: int = 0
    #: Dossier des échantillons « en vrac ».
    dest: str = "SAMPLES"
    #: Presets, kits ou morceaux dont des échantillons resteraient
    #: introuvables : ``{chemin : [échantillons]}``.
    missing: dict[str, list[str]] = field(default_factory=dict)
    #: Références réécrites dans un XML du pack, son fichier ayant changé
    #: de nom : ``{chemin du XML : {ancienne : nouvelle}}``.
    retarget: dict[str, dict[str, str]] = field(default_factory=dict)

    def of(self, *actions: str) -> list[ImportItem]:
        return [i for i in self.items if i.action in actions]

    @property
    def to_copy(self) -> list[ImportItem]:
        return self.of("copy", "convert")

    @property
    def skipped(self) -> list[ImportItem]:
        return self.of("same", "kept", "refused")

    @property
    def empty(self) -> bool:
        return not self.to_copy

    def bytes_to_copy(self) -> int:
        return sum(i.size for i in self.to_copy)

    def cable_time(self) -> str:
        return cable_time(write_bytes=self.bytes_to_copy())

    def counts(self) -> Counter:
        return Counter(i.action for i in self.items)

    def summary(self) -> str:
        from .units import human_size

        c = self.counts()
        a_copier = c.get("copy", 0) + c.get("convert", 0)
        morceaux = [tr("%d fichier(s) à envoyer (%s)")
                    % (a_copier, human_size(self.bytes_to_copy()))]
        if c.get("convert"):
            morceaux.append(tr("dont %d à convertir") % c["convert"])
        if c.get("same"):
            morceaux.append(tr("%d déjà sur la carte") % c["same"])
        if c.get("kept"):
            morceaux.append(tr("%d laissé(s) tel quel") % c["kept"])
        if c.get("refused"):
            morceaux.append(tr("%d refusé(s)") % c["refused"])
        if self.ignored:
            morceaux.append(tr("%d resté(s) sur le PC") % len(self.ignored))
        return ", ".join(morceaux)

    def to_text(self) -> str:
        """Le détail, fichier par fichier, groupé par sort."""
        from .units import human_size

        lignes: list[str] = []
        for action in ("copy", "convert", "same", "kept", "refused"):
            groupe = self.of(action)
            if not groupe:
                continue
            lignes.append("— %s (%d) —" % (tr(ACTIONS[action]).capitalize(),
                                          len(groupe)))
            for item in groupe:
                ligne = "  %s   %s" % (item.rel, human_size(item.size))
                if item.original and item.original != item.rel:
                    ligne += "   ← %s" % item.original
                lignes.append(ligne)
                if item.reason:
                    lignes.append("      %s" % item.reason)
            lignes.append("")
        if self.missing:
            lignes.append(tr("— Échantillons introuvables, cités par —"))
            for rel, refs in sorted(self.missing.items()):
                lignes.append("  %s" % rel)
                lignes.extend("      %s" % r for r in refs[:8])
                if len(refs) > 8:
                    lignes.append(tr("      … et %d autres") % (len(refs) - 8))
            lignes.append("")
        if self.ignored:
            lignes.append(tr("— Resté sur le PC (%d) —") % len(self.ignored))
            for chemin, raison in self.ignored:
                lignes.append("  %s" % chemin)
                lignes.append("      %s" % raison)
        return "\n".join(lignes).rstrip() + "\n"


def card_files(racine: Path) -> dict[str, tuple[str, int]]:
    """Les fichiers de la carte : ``{clé : (chemin, taille)}``."""
    from .cardsync import is_junk

    trouve: dict[str, tuple[str, int]] = {}
    racine = Path(racine)
    for dossier, sous, fichiers in os.walk(racine):
        rel_dossier = Path(dossier).relative_to(racine).as_posix()
        rel_dossier = "" if rel_dossier == "." else rel_dossier
        sous[:] = [s for s in sous
                   if not is_junk((rel_dossier + "/" + s).strip("/"))]
        for nom in fichiers:
            rel = (rel_dossier + "/" + nom).strip("/")
            if is_junk(rel):
                continue
            try:
                taille = os.stat(os.path.join(dossier, nom)).st_size
            except OSError:
                continue
            trouve[norm_rel(rel)] = (rel, int(taille))
    return trouve


def sample_folders(racine: Path, depth: int = 2) -> list[str]:
    """Les dossiers d'échantillons de la carte, pour choisir où envoyer :
    ``SAMPLES``, ``SAMPLES/DRUMS``, ``SAMPLES/DRUMS/Kick``…"""
    racine = Path(racine)
    base = next((p for p in (racine.iterdir() if racine.is_dir() else ())
                 if p.is_dir() and p.name.upper() == "SAMPLES"), None)
    if base is None:
        return ["SAMPLES"]
    sortie = ["SAMPLES"]
    a_voir = [(base, "SAMPLES", 1)]
    while a_voir:
        dossier, rel, profondeur = a_voir.pop(0)
        try:
            enfants = sorted((e for e in os.scandir(dossier) if e.is_dir()),
                             key=lambda e: e.name.casefold())
        except OSError:
            continue
        for e in enfants:
            if e.name.startswith((".", "_")):
                continue
            chemin = rel + "/" + e.name
            sortie.append(chemin)
            if profondeur < depth:
                a_voir.append((Path(e.path), chemin, profondeur + 1))
    return sortie


def _same_bytes(a: Path, b: Path) -> bool:
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


def _free_name(rel: str, pris) -> str:
    """« dossier/Kick.wav » -> « dossier/Kick 2.wav », jamais un nom pris."""
    dossier, _, nom = rel.rpartition("/")
    base, point, ext = nom.rpartition(".")
    if not point:
        base, ext = nom, ""
    for i in range(2, 10000):
        candidat = "%s %d%s" % (base, i, ("." + ext) if ext else "")
        complet = (dossier + "/" + candidat).strip("/")
        if norm_rel(complet) not in pris:
            return complet
    raise ValueError(tr("aucun nom libre pour %s") % rel)


def _fit(rel: str) -> str:
    """Raccourcit le nom pour tenir dans un chemin de la machine (256
    signes, et la place d'un nom temporaire à côté)."""
    limite = MAX_PATH - 16
    if len("/" + rel) <= limite:
        return rel
    dossier, _, nom = rel.rpartition("/")
    base, point, ext = nom.rpartition(".")
    if not point:
        base, ext = nom, ""
    garde = max(8, len(base) - (len("/" + rel) - limite))
    return (dossier + "/" + base[:garde].rstrip(" .")
            + (("." + ext) if ext else "")).strip("/")


def plan_import(scan: ImportScan, card_root: Path, dest: str = "SAMPLES",
                existing: dict[str, tuple[str, int]] | None = None
                ) -> ImportPlan:
    """Ce que deviendrait chaque fichier déposé, pour la carte ``card_root``.

    :param dest: dossier de la carte qui reçoit les échantillons « en
        vrac » — ce qui ne vient pas d'un pack à la forme de la carte.
        Toujours sous SAMPLES.
    :param existing: les fichiers de la carte (:func:`card_files`), si on
        les a déjà ; le dialogue recalcule le plan quand on change de
        destination.
    """
    card_root = Path(card_root)
    existants = existing if existing is not None else card_files(card_root)
    destination = card_path(dest) or "SAMPLES"
    if destination.split("/")[0].upper() != "SAMPLES":
        destination = "SAMPLES"
    destination = "SAMPLES" + destination[len("SAMPLES"):]
    plan = ImportPlan(ignored=list(scan.ignored), junk=scan.junk,
                      dest=destination)
    prevus: dict[str, str] = {}
    renommes: dict[str, str] = {}
    origines: dict[int, Found] = {}

    for trouve in scan.found:
        if trouve.pack_rel:
            original = trouve.pack_rel
        else:
            haut = destination if trouve.kind == "sample" \
                else KIND_DIRS[trouve.kind]
            original = haut + "/" + trouve.loose_rel
        rel = _fit(card_path(original))
        action, raison = "copy", ""
        if trouve.problem:
            action = "convert" if trouve.fixable else "refused"
            raison = ((tr("le Deluge le refuserait : %s — converti sans perte "
                          "audible") if trouve.fixable
                       else tr("le Deluge le refuserait : %s")) % trouve.problem)
            if trouve.fixable and rel.lower().endswith(".aifc"):
                rel = rel[:-5] + ".aif"
        if action != "refused":
            cle = norm_rel(rel)
            deja = existants.get(cle)
            if deja is not None:
                if action == "copy" and _same_bytes(trouve.path,
                                                    card_root / deja[0]):
                    action, rel = "same", deja[0]
                    raison = tr("identique, octet pour octet")
                elif trouve.pack_rel:
                    action, rel = "kept", deja[0]
                    raison = (tr("un fichier différent porte déjà ce nom sur la "
                                 "carte : c'est lui que les presets du pack "
                                 "joueront"))
                else:
                    rel = _free_name(rel, set(existants) | set(prevus))
                    raison = tr("nom déjà pris sur la carte : numéroté")
            elif cle in prevus:
                if trouve.pack_rel:
                    action = "kept"
                    raison = tr("en double dans ce qui est déposé")
                else:
                    rel = _free_name(rel, set(existants) | set(prevus))
                    raison = tr("nom déjà pris par un autre fichier déposé")
        if action in ("copy", "convert"):
            prevus[norm_rel(rel)] = rel
        if trouve.pack_rel and norm_rel(rel) != norm_rel(original):
            renommes[norm_rel(original)] = rel
        item = ImportItem(trouve.path, rel, trouve.kind, trouve.size, action,
                          raison, original)
        plan.items.append(item)
        origines[id(item)] = trouve

    connus = set(existants) | set(prevus)
    for item in plan.items:
        if item.kind == "sample" or item.action != "copy":
            continue
        reecrites: dict[str, str] = {}
        absents: list[str] = []
        for ref in origines[id(item)].refs:
            cle = norm_rel(ref)
            if cle in renommes:
                reecrites[ref] = renommes[cle]
                cle = norm_rel(renommes[cle])
            if cle not in connus:
                absents.append(ref)
        if reecrites:
            plan.retarget[item.rel] = reecrites
        if absents:
            plan.missing[item.rel] = absents
    return plan


# --------------------------------------------------------------------------- #
# La copie
# --------------------------------------------------------------------------- #

@dataclass
class ImportResult:
    written: list[str] = field(default_factory=list)
    converted: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    stopped: bool = False

    def summary(self) -> str:
        morceaux = [tr("%d fichier(s) posé(s) sur la carte") % len(self.written)]
        if self.converted:
            morceaux.append(tr("dont %d converti(s)") % len(self.converted))
        if self.errors:
            morceaux.append("%d erreur(s)" % len(self.errors))
        if self.stopped:
            morceaux.append("interrompu")
        return ", ".join(morceaux)


def _exists_ci(racine: Path, rel: str) -> bool:
    """Le fichier existe-t-il, à la casse près — comme sur FAT32 ?"""
    courant = Path(racine)
    for partie in [p for p in rel.split("/") if p]:
        try:
            noms = {e.name.casefold(): e.name for e in os.scandir(courant)}
        except OSError:
            return False
        vrai = noms.get(partie.casefold())
        if vrai is None:
            return False
        courant = courant / vrai
    return True


def _copy_new(source: Path, cible: Path) -> None:
    """Copie vers un fichier **neuf** : l'ouverture exclusive refuse un nom
    pris, même apparu entre le plan et la copie."""
    try:
        with open(source, "rb") as entree, open(cible, "xb") as sortie:
            shutil.copyfileobj(entree, sortie, 1 << 20)
    except FileExistsError:
        raise
    except BaseException:
        try:
            cible.unlink()
        except OSError:
            pass
        raise
    shutil.copystat(source, cible)


def _conversion(info: wav.AudioInfo, aiff: bool) -> dict:
    """Paramètres de :func:`wav.convert` qui rendent le fichier lisible."""
    params: dict = {}
    if info.sample_rate > wav.DELUGE_MAX_RATE:
        params["sample_rate"] = 48000
    elif info.sample_rate < wav.DELUGE_MIN_RATE:
        params["sample_rate"] = 44100
    if info.fmt == "float":
        # L'AIFF flottant s'écrit en AIFC, que le Deluge refuse.
        params["bit_depth"] = 24 if aiff else "float32"
    elif info.bit_depth in (16, 24, 32):
        params["bit_depth"] = info.bit_depth
    else:
        # A-law et µ-law (8 bits codés), 20 bits… : vers 16 ou 24 bits.
        params["bit_depth"] = 24 if info.bit_depth > 16 else 16
    return params


def _convert_new(source: Path, cible: Path) -> None:
    """Convertit vers un fichier neuf, en passant par un dossier temporaire
    hors de la carte : rien d'inachevé n'y traîne jamais."""
    info = wav.probe(source)
    if not info.ok:
        raise ValueError(tr("illisible : %s") % info.error)
    aiff = cible.suffix.lower() in (".aif", ".aiff")
    with tempfile.TemporaryDirectory(prefix="deluge-envoi-") as dossier:
        temporaire = Path(dossier) / ("conversion" + cible.suffix.lower())
        resultat = wav.convert(source, temporaire, **_conversion(info, aiff))
        if not resultat.ok:
            raise ValueError(tr("conversion impossible : %s") % resultat.error)
        probleme, _ = wav.deluge_problem(temporaire)
        if probleme:
            raise ValueError(tr("toujours refusé après conversion : %s")
                             % probleme)
        _copy_new(temporaire, cible)


def _retarget_new(source: Path, cible: Path, refs: dict[str, str]) -> None:
    """Copie un XML du pack en faisant suivre ses références renommées."""
    doc = dxml.load(source)
    cles = {norm_rel(a): b for a, b in refs.items()}
    for noeud in doc.root.iter():
        valeur = dxml.get(noeud, "fileName")
        if valeur and norm_rel(valeur) in cles:
            dialecte = ("elem" if dxml.get_child(noeud, "fileName") is not None
                        else "attr")
            dxml.set_(noeud, "fileName", cles[norm_rel(valeur)], dialecte)
    donnees = dxml.dump(doc).encode("utf-8")
    with open(cible, "xb") as sortie:
        sortie.write(donnees)


def apply_import(plan: ImportPlan, sd: SDCard,
                 progress: Callable[[object], None] | None = None,
                 should_stop: Callable[[], bool] | None = None
                 ) -> ImportResult:
    """Copie sur la carte ce que le plan prévoit. Rien d'existant n'est
    remplacé ; un fichier en erreur n'arrête pas les autres."""
    sd.require_writable()
    racine = Path(sd.root)
    resultat = ImportResult()
    a_faire = plan.to_copy
    for i, item in enumerate(a_faire, 1):
        if should_stop is not None and should_stop():
            resultat.stopped = True
            break
        if progress is not None:
            progress(tr("Copie sur la carte : %d / %d — %s")
                     % (i, len(a_faire), item.rel))
        cible = racine / item.rel
        try:
            if _exists_ci(racine, item.rel):
                raise FileExistsError(tr("apparu sur la carte depuis le plan"))
            cible.parent.mkdir(parents=True, exist_ok=True)
            if item.action == "convert":
                _convert_new(item.source, cible)
                resultat.converted.append(item.rel)
            elif item.rel in plan.retarget:
                _retarget_new(item.source, cible, plan.retarget[item.rel])
            else:
                _copy_new(item.source, cible)
            resultat.written.append(item.rel)
        except (OSError, ValueError, dxml.DelugeXMLError) as exc:
            log.warning("envoi de %s : %s", item.rel, exc)
            resultat.errors.append(tr("%s : %s") % (item.rel, exc))
    log.info("envoi vers la carte : %s", resultat.summary())
    return resultat
