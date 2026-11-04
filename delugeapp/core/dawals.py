# -*- coding: utf-8 -*-
"""Ableton Live : un set ``.als`` tiré d'un morceau du Deluge.

Un ``.als`` est un XML compressé (gzip) que Live écrit avec des centaines
d'éléments obligatoires, sans documentation publique ; un set inventé de
toutes pièces risque d'être refusé. Ce module n'invente donc rien : il part
de fichiers **écrits par le Live installé sur le PC**, tous au même format
(:func:`find_live`) —

* le set de base et sa piste MIDI : ``Default MIDI Track.als`` de la Core
  Library (un set complet d'une piste, sans instrument) ;
* la piste audio : ``Default Audio Track.als`` ;
* le clip MIDI : un clip ``.alc`` de la Core Library ;
* le clip audio : un clip d'un set de démonstration.

Mesuré sur Live 12.4.16 Lite (``D:\\Ableton``, 4 novembre 2026) : les fichiers
de ``Resources`` sont au format ``12.0_12402`` (375 sur 376 ; le set vide des
préférences, ``DefaultLiveSet.als``, est au format précédent, ``12.0_12117``,
et son clip MIDI n'a pas ``AutomationEnvelopesListWrapper``). Chaque élément
dont la balise finit par « Target », ainsi que ``Pointee`` et
``ControllerTargets.N``, porte un numéro unique dans tout le set, inférieur à
``NextPointeeId`` (578 numéros dans le set vide, 8 980 dans la démo, aucun en
double) ; les enveloppes les désignent par ``PointeeId``. Les autres ``Id`` ne
numérotent que les éléments d'une liste. Une piste clonée est donc
renumérotée à partir de ``NextPointeeId``. Le tempo vit deux fois : dans
``Tempo/Manual`` et dans l'enveloppe d'automation qui le désigne — sans elle,
l'automation l'emporte.

Le set s'adapte à l'**édition** de Live installée (:data:`EDITIONS`), lue
dans le nom de son exécutable : au-delà de ses pistes, les pistes de notes
passent d'abord et l'audio prend les places libres ; au-delà de ses scènes,
les premières sont gardées, l'arrangement restant complet. Mesuré sur Live
12.4.16 Lite : un set de 9 pistes ouvre « Ce Set contient des
fonctionnalités qui sont limitées ou indisponibles dans Ableton Live 12
Lite. 9 pistes ; (limité à 8) » ; douze scènes passent sans avertissement.
"""

from __future__ import annotations

import copy
import gzip
import logging
import os
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from ..i18n import tr, untranslated

log = logging.getLogger(__name__)

__all__ = ["TemplateMissing", "EDITIONS", "LiveInstall", "find_live",
           "write_als", "template_problem"]

#: Pistes audio et MIDI, scènes : les limites de chaque édition de Live 12,
#: d'après le tableau d'Ableton (https://www.ableton.com/en/upgrade-live/,
#: relu le 4 novembre 2026) ; ``None`` : illimité. Une édition inconnue
#: (version d'essai, bêta) n'est pas limitée : Live avertira s'il le faut.
EDITIONS: dict[str, tuple[int | None, int | None]] = untranslated({
    "Lite": (8, 16),
    "Intro": (16, 16),
    "Standard": (None, None),
    "Suite": (None, None),
})

#: Les fichiers de Live où l'on prend les modèles (chemins, pas des textes).
_MIDI_TRACK, _AUDIO_TRACK, _CLIPS, _DEMOS = untranslated((
    "Core Library/Defaults/Creating Tracks/MIDI Track/Default MIDI Track.als",
    "Core Library/Defaults/Creating Tracks/Audio Track/"
    "Default Audio Track.als",
    "Core Library/MIDI Clips",
    "Core Library/Lessons"))
#: Ce qu'on cherche sur le disque.
_LIVE_DIRS, _PROGRAM_FILES, _RESOURCES_GLOB, _EXE_GLOB, _VERSION = \
    untranslated(("Live *", "C:/Program Files/Ableton", "Live */Resources",
                  "Ableton Live*.exe", r"Live (\d+)(?: (\w+))?"))

#: Les couleurs des pistes, dans la palette de Live (0 à 69) : rouge,
#: orange, ambre, jaune, vert, menthe, cyan, bleu, indigo, violet, magenta,
#: rose — les teintes des pads du Deluge, dans leur ordre.
_COLOURS = (14, 1, 2, 4, 6, 10, 11, 12, 13, 24, 22, 15)


class TemplateMissing(Exception):
    """Live n'est pas trouvé, ou ses fichiers de départ manquent."""


@dataclass
class LiveInstall:
    """Un Live installé : son dossier ``Resources``, sa version, son
    édition (``Lite``, ``Intro``, ``Standard``, ``Suite``)."""

    resources: Path
    version: str = ""
    edition: str = ""

    @property
    def max_tracks(self) -> int | None:
        return EDITIONS.get(self.edition, (None, None))[0]

    @property
    def max_scenes(self) -> int | None:
        return EDITIONS.get(self.edition, (None, None))[1]

    @property
    def limited(self) -> bool:
        return self.max_tracks is not None or self.max_scenes is not None


def _live_logs() -> list[Path]:
    """Les journaux des Live de l'utilisateur, le plus récent d'abord."""
    racines = []
    if sys.platform == "win32":
        racines.append(Path(os.environ.get("APPDATA", "")) / "Ableton")
    else:
        racines.append(Path.home() / "Library" / "Preferences" / "Ableton")
    journaux = []
    for racine in racines:
        try:
            journaux += [d / "Preferences" / "Log.txt"
                         for d in racine.glob(_LIVE_DIRS) if d.is_dir()]
        except OSError:
            continue
    journaux = [j for j in journaux if j.exists()]
    return sorted(journaux, key=lambda j: j.stat().st_mtime, reverse=True)


_RESOURCES = re.compile(r"([A-Za-z]:[\\/][^\r\n\"']*?[\\/]Resources)[\\/]")


def find_live(resources: Path | None = None) -> LiveInstall | None:
    """Le Live installé. ``resources`` l'impose ; sinon, son journal le dit
    (Live y écrit les chemins de ses ``Resources``), sinon les emplacements
    habituels."""
    candidats: list[Path] = []
    if resources:
        candidats.append(Path(resources))
    for journal in _live_logs():
        try:
            texte = journal.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        candidats += [Path(m) for m in _RESOURCES.findall(texte)][:3]
    # Les emplacements de l'installateur, si le journal ne dit rien.
    for base in (Path("C:/ProgramData/Ableton"), Path(_PROGRAM_FILES)):
        try:
            candidats += sorted(base.glob(_RESOURCES_GLOB), reverse=True)
        except OSError:
            continue
    for dossier in candidats:
        if (dossier / _MIDI_TRACK).exists():
            programme = dossier.parent / "Program"
            exe = [p.name for p in programme.glob(_EXE_GLOB)] \
                if programme.exists() else []
            nom = exe[0] if exe else ""
            # « Ableton Live 12 Lite.exe » : la version, puis l'édition.
            lu = re.search(_VERSION, nom)
            return LiveInstall(dossier, lu.group(1) if lu else "",
                               (lu.group(2) or "") if lu else "")
    return None


def template_problem(template: Path | None = None) -> str:
    """Ce qui empêche d'écrire un set ; ``""`` s'il le peut."""
    live = find_live(template)
    if live is None:
        return tr("Ableton Live : Live n'est pas trouvé sur ce PC ; le "
                  "dossier contient le MIDI et les pistes audio, que Live "
                  "importe par glisser-déposer.")
    try:
        _Templates.load(live.resources)
    except TemplateMissing as exc:
        return str(exc)
    return ""


# --------------------------------------------------------------------------- #
# Les modèles, pris dans Live
# --------------------------------------------------------------------------- #

def _read(path: Path) -> ET.Element:
    with gzip.open(path, "rb") as f:
        return ET.fromstring(f.read())


def _is_pointee(tag: str) -> bool:
    return tag.endswith("Target") or tag == "Pointee" \
        or tag.startswith("ControllerTargets.")


@dataclass
class _Templates:
    root: ET.Element
    midi_track: ET.Element
    audio_track: ET.Element | None
    midi_clip: ET.Element
    audio_clip: ET.Element | None
    version: str

    @classmethod
    def load(cls, resources: Path) -> "_Templates":
        try:
            racine = _read(resources / _MIDI_TRACK)
        except (OSError, ET.ParseError, EOFError) as exc:
            raise TemplateMissing(tr("Ableton Live : le set de départ est "
                                     "illisible (%s).") % exc) from exc
        version = racine.get("MinorVersion", "")
        piste = racine.find("LiveSet/Tracks/MidiTrack")
        audio = None
        try:
            audio = _read(resources / _AUDIO_TRACK).find(
                "LiveSet/Tracks/AudioTrack")
        except (OSError, ET.ParseError, EOFError):
            log.info("piste audio de Live introuvable")
        clip = None
        for fichier in sorted((resources / _CLIPS).rglob("*.alc")):
            try:
                doc = _read(fichier)
            except (OSError, ET.ParseError, EOFError):
                continue
            if doc.get("MinorVersion", "") == version:
                clip = next(doc.iter("MidiClip"), None)
                if clip is not None:
                    break
        clip_audio = None
        for fichier in sorted((resources / _DEMOS).rglob("*.als")):
            try:
                doc = _read(fichier)
            except (OSError, ET.ParseError, EOFError):
                continue
            if doc.get("MinorVersion", "") == version:
                clip_audio = next(doc.iter("AudioClip"), None)
                if clip_audio is not None:
                    break
        if piste is None or clip is None:
            raise TemplateMissing(tr("Ableton Live : ses fichiers de départ "
                                     "manquent (Core Library)."))
        return cls(racine, piste, audio, clip, clip_audio, version)


def _renumber(el: ET.Element, prochain: int) -> int:
    """Donne aux numéros globaux d'une piste clonée des valeurs neuves, et
    met à jour les ``PointeeId`` qui les citent. Rend le prochain libre."""
    table: dict[str, str] = {}
    for e in el.iter():
        if e.get("Id") is not None and _is_pointee(e.tag):
            table[e.get("Id")] = str(prochain)
            e.set("Id", str(prochain))
            prochain += 1
    for e in el.iter("PointeeId"):
        if e.get("Value") in table:
            e.set("Value", table[e.get("Value")])
    return prochain


def _set(el: ET.Element, path: str, value) -> None:
    cible = el.find(path)
    if cible is not None:
        cible.set("Value", str(value))


def _fmt(x: float) -> str:
    return ("%.6f" % float(x)).rstrip("0").rstrip(".") or "0"


def _clear(el: ET.Element | None) -> None:
    if el is not None:
        for enfant in list(el):
            el.remove(enfant)


def _midi_clip(modele: ET.Element, clip, debut: float, duree: float,
               ident: int, couleur: int, session: bool) -> ET.Element:
    """Un clip MIDI de Live : la boucle du clip du Deluge, posée à ``debut``
    pour ``duree`` noires (ou rangée dans une case de scène)."""
    c = copy.deepcopy(modele)
    c.set("Id", str(ident))
    c.set("Time", _fmt(0 if session else debut))
    longueur = max(1e-3, clip.length)
    _set(c, "CurrentStart", _fmt(0 if session else debut))
    _set(c, "CurrentEnd", _fmt(longueur if session else debut + duree))
    _set(c, "Loop/LoopStart", "0")
    _set(c, "Loop/LoopEnd", _fmt(longueur))
    _set(c, "Loop/StartRelative", "0")
    _set(c, "Loop/LoopOn", "true")
    _set(c, "Loop/OutMarker", _fmt(longueur))
    _set(c, "Loop/HiddenLoopStart", "0")
    _set(c, "Loop/HiddenLoopEnd", _fmt(longueur))
    _set(c, "Name", (clip.name or "")[:60])
    _set(c, "Color", couleur)
    _clear(c.find("Envelopes/Envelopes"))
    _set(c, "ScrollerTimePreserver/LeftTime", "0")
    _set(c, "ScrollerTimePreserver/RightTime", _fmt(longueur))
    _set(c, "TimeSelection/AnchorTime", "0")
    _set(c, "TimeSelection/OtherTime", "0")
    pistes = c.find("Notes/KeyTracks")
    _clear(pistes)
    par_hauteur: dict[int, list] = {}
    for n in clip.notes:
        if 0 <= n.start < longueur:
            par_hauteur.setdefault(int(n.pitch), []).append(n)
    numero = 1
    for rang, hauteur in enumerate(sorted(par_hauteur)):
        kt = ET.SubElement(pistes, "KeyTrack", {"Id": str(rang)})
        notes = ET.SubElement(kt, "Notes")
        for n in sorted(par_hauteur[hauteur], key=lambda x: x.start):
            ET.SubElement(notes, "MidiNoteEvent", {
                "Time": _fmt(n.start), "Duration": _fmt(max(1e-3, n.length)),
                "Velocity": str(max(1, min(127, int(n.velocity)))),
                "OffVelocity": "64", "NoteId": str(numero)})
            numero += 1
        ET.SubElement(kt, "MidiKey", {"Value": str(hauteur)})
    _clear(c.find("Notes/PerNoteEventStore/EventLists"))
    _set(c, "Notes/NoteIdGenerator/NextId", numero)
    return c


def _audio_clip(modele: ET.Element, chemin: Path, set_dir: Path,
                bpm: float, ident: int, couleur: int) -> ET.Element | None:
    """Un clip audio de Live, calé au début : la piste rendue, à son
    tempo."""
    from . import wav as wavmod

    info = wavmod.probe(chemin)
    if not info.ok or not info.sample_rate:
        log.info("piste audio illisible : %s", chemin)
        return None
    trames, taux = int(info.frames), int(info.sample_rate)
    secondes = trames / float(max(1, taux))
    noires = secondes * bpm / 60.0
    c = copy.deepcopy(modele)
    c.set("Id", str(ident))
    c.set("Time", "0")
    _set(c, "CurrentStart", "0")
    _set(c, "CurrentEnd", _fmt(noires))
    _set(c, "Loop/LoopStart", "0")
    _set(c, "Loop/LoopEnd", _fmt(noires))
    _set(c, "Loop/StartRelative", "0")
    _set(c, "Loop/LoopOn", "false")
    _set(c, "Loop/OutMarker", _fmt(noires))
    _set(c, "Loop/HiddenLoopStart", "0")
    _set(c, "Loop/HiddenLoopEnd", _fmt(noires))
    _set(c, "Name", chemin.stem[:60])
    _set(c, "Color", couleur)
    _clear(c.find("Envelopes/Envelopes"))
    _set(c, "ScrollerTimePreserver/LeftTime", "0")
    _set(c, "ScrollerTimePreserver/RightTime", _fmt(noires))
    ref = c.find("SampleRef/FileRef")
    if ref is not None:
        try:
            relatif = os.path.relpath(chemin, set_dir).replace("\\", "/")
        except ValueError:
            relatif = chemin.name
        _set(ref, "RelativePathType", 1)
        _set(ref, "RelativePath", relatif)
        _set(ref, "Path", str(Path(chemin).resolve()).replace("\\", "/"))
        _set(ref, "Type", 2)
        _set(ref, "LivePackName", "")
        _set(ref, "LivePackId", "")
        _set(ref, "OriginalFileSize", chemin.stat().st_size)
        _set(ref, "OriginalCrc", 0)
        _set(ref, "SourceHint", "")
    _set(c, "SampleRef/LastModDate", int(chemin.stat().st_mtime))
    _set(c, "SampleRef/DefaultDuration", trames)
    _set(c, "SampleRef/DefaultSampleRate", taux)
    _set(c, "WarpMode", 0)
    _set(c, "IsWarped", "true")
    reperes = c.find("WarpMarkers")
    _clear(reperes)
    if reperes is not None:
        ET.SubElement(reperes, "WarpMarker", {"Id": "0", "SecTime": "0",
                                              "BeatTime": "0"})
        ET.SubElement(reperes, "WarpMarker", {
            "Id": "1", "SecTime": _fmt(secondes), "BeatTime": _fmt(noires)})
    _clear(c.find("SavedWarpMarkersForStretched"))
    return c


def _slots(piste: ET.Element, nombre: int) -> list[ET.Element]:
    """Les cases de scène d'une piste, au nombre des scènes, dans les deux
    listes que Live tient (lecture et gel)."""
    cases = []
    for chemin in ("DeviceChain/MainSequencer/ClipSlotList",
                   "DeviceChain/FreezeSequencer/ClipSlotList"):
        liste = piste.find(chemin)
        if liste is None or not len(liste):
            continue
        modele = copy.deepcopy(liste[0])
        _clear(modele.find("ClipSlot/Value"))
        _clear(liste)
        for i in range(nombre):
            case = copy.deepcopy(modele)
            case.set("Id", str(i))
            liste.append(case)
        if chemin.startswith("DeviceChain/Main"):
            cases = list(liste)
    return cases


def write_als(song, path: Path, audio: dict[int, str] | None = None,
              template: Path | None = None,
              notes: list[str] | None = None) -> Path:
    """Écrit le set ``.als`` de ``song`` : une piste MIDI par piste du
    morceau (une scène par section, l'arrangement entier, les repères), une
    piste audio par piste rendue, au tempo du morceau.

    ``template`` impose le dossier ``Resources`` de Live ; sans lui, Live est
    cherché (:func:`find_live`). Lève :class:`TemplateMissing` s'il manque.
    Rend le chemin écrit ; ce qui a été laissé — pistes et scènes au-delà des
    limites de Live Lite — s'ajoute à ``notes``.
    """
    live = find_live(template)
    if live is None:
        raise TemplateMissing(template_problem(template))
    modeles = _Templates.load(live.resources)
    racine = copy.deepcopy(modeles.root)
    ls = racine.find("LiveSet")
    prochain = int(ls.find("NextPointeeId").get("Value"))
    cible = Path(path)
    laisses: list[str] = []

    # Tempo : la valeur et l'enveloppe qui la porte.
    tempo = ls.find("MainTrack/DeviceChain/Mixer/Tempo")
    if tempo is not None:
        _set(tempo, "Manual", _fmt(song.bpm))
        cle = tempo.find("AutomationTarget").get("Id")
        for env in ls.find("MainTrack").iter("AutomationEnvelope"):
            if env.find("EnvelopeTarget/PointeeId").get("Value") == cle:
                for ev in env.find("Automation/Events"):
                    ev.set("Value", _fmt(song.bpm))

    # Les scènes : une par section du morceau, autant que l'édition en
    # accepte.
    scenes = list(song.scenes)
    if live.max_scenes is not None and len(scenes) > live.max_scenes:
        laisses.append(tr("Live %s : %d scènes au plus — %d scène(s) "
                          "laissée(s), l'arrangement reste complet")
                       % (live.edition, live.max_scenes,
                          len(scenes) - live.max_scenes))
        scenes = scenes[:live.max_scenes]
    conteneur = ls.find("Scenes")
    modele_scene = copy.deepcopy(conteneur[0])
    _clear(conteneur)
    for i, scene in enumerate(scenes or [None]):
        s = copy.deepcopy(modele_scene)
        s.set("Id", str(i))
        _set(s, "Name", scene.name if scene is not None else "")
        _set(s, "Tempo", _fmt(song.bpm))
        conteneur.append(s)
    nb_scenes = max(1, len(scenes))

    # Les pistes.
    pistes = ls.find("Tracks")
    _clear(pistes)
    ident = 0
    entrees = [(i, t) for i, t in enumerate(song.tracks)
               if t.has_notes and t.kind != "audio"]
    sons = sorted((audio or {}).items()) if modeles.audio_track is not None \
        and modeles.audio_clip is not None else []
    if (audio and not sons):
        laisses.append(tr("Ableton Live : pas de modèle de piste audio, les "
                          "pistes audio restent dans le dossier"))
    total = len(entrees) + len(sons)
    plafond = live.max_tracks
    if plafond is not None and total > plafond:
        # Les pistes de notes d'abord, puis l'audio dans les places libres ;
        # les autres pistes audio restent dans le dossier.
        laisses.append(tr("Live %s : %d pistes au plus — %d piste(s) "
                          "laissée(s) hors du set (les pistes audio restent "
                          "dans le dossier)")
                       % (live.edition, plafond, total - plafond))
        entrees = entrees[:plafond]
        sons = sons[:plafond - len(entrees)]
    for rang, (index, track) in enumerate(entrees):
        piste = copy.deepcopy(modeles.midi_track)
        prochain = _renumber(piste, prochain)
        piste.set("Id", str(ident))
        ident += 1
        couleur = _COLOURS[rang % len(_COLOURS)]
        _set(piste, "Name/EffectiveName", track.name[:60])
        _set(piste, "Name/UserName", track.name[:60])
        _set(piste, "Color", couleur)
        cases = _slots(piste, nb_scenes)
        for s, ci in track.scenes.items():
            if s < len(cases) and 0 <= ci < len(track.clips):
                valeur = cases[s].find("ClipSlot/Value")
                valeur.append(_midi_clip(modeles.midi_clip, track.clips[ci],
                                         0.0, 0.0, 0, couleur, True))
        evenements = piste.find(
            "DeviceChain/MainSequencer/ClipTimeable/ArrangerAutomation/Events")
        _clear(evenements)
        for k, p in enumerate(sorted(track.placements,
                                     key=lambda x: x.start)):
            clip = track.clips[p.clip]
            if clip.notes:
                evenements.append(_midi_clip(modeles.midi_clip, clip,
                                             p.start, p.length, k, couleur,
                                             False))
        pistes.append(piste)
    for rang, (index, rel) in enumerate(sons):
        piste = copy.deepcopy(modeles.audio_track)
        prochain = _renumber(piste, prochain)
        piste.set("Id", str(ident))
        ident += 1
        nom = tr("%s (audio)") % song.tracks[index].name
        couleur = _COLOURS[(len(entrees) + rang) % len(_COLOURS)]
        _set(piste, "Name/EffectiveName", nom[:60])
        _set(piste, "Name/UserName", nom[:60])
        _set(piste, "Color", couleur)
        _slots(piste, nb_scenes)
        evenements = piste.find(
            "DeviceChain/MainSequencer/Sample/ArrangerAutomation/Events")
        _clear(evenements)
        clip = _audio_clip(modeles.audio_clip, cible.parent / rel, cible.parent,
                           song.bpm, 0, couleur)
        if clip is not None and evenements is not None:
            evenements.append(clip)
        pistes.append(piste)

    # Les repères, aux sections.
    reperes = ls.find("Locators/Locators")
    if reperes is not None:
        _clear(reperes)
        for i, (t, nom) in enumerate(song.markers):
            loc = ET.SubElement(reperes, "Locator", {"Id": str(i)})
            ET.SubElement(loc, "LomId", {"Value": "0"})
            ET.SubElement(loc, "Time", {"Value": _fmt(t)})
            ET.SubElement(loc, "Name", {"Value": str(nom)[:60]})
            ET.SubElement(loc, "Annotation", {"Value": ""})
            ET.SubElement(loc, "IsSongStart", {"Value": "false"})

    ls.find("NextPointeeId").set("Value", str(prochain))
    donnees = (b'<?xml version="1.0" encoding="UTF-8"?>\n'
               + ET.tostring(racine, encoding="utf-8"))
    cible.parent.mkdir(parents=True, exist_ok=True)
    tmp = cible.with_suffix(cible.suffix + ".part")
    with gzip.open(tmp, "wb") as f:
        f.write(donnees)
    tmp.replace(cible)
    if notes is not None:
        notes.extend(laisses)
    log.info("set Live écrit : %s (%d pistes, %d scènes, Live %s %s)", cible,
             len(entrees) + len(sons), nb_scenes, live.version, live.edition)
    return cible
