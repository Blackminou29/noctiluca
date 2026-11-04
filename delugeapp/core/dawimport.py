# -*- coding: utf-8 -*-
"""Du DAW vers le Deluge : lire un projet, en faire un **nouveau** morceau.

Quatre portes d'entrée, toutes vers le modèle commun de :mod:`.daw` :

* un **fichier MIDI** (types 0 et 1) — tous les DAW en exportent ;
* un **DAWproject** (Bitwig, Studio One, Cubase) : pistes de notes,
  arrangement, scènes, repères ;
* un **set Ableton** (``.als``, XML compressé) : pistes MIDI, clips de
  l'arrangement et du lanceur, scènes, repères ;
* un **projet Reaper** (``.rpp``) : objets MIDI, boucles, repères.

Puis :func:`build_song` en fait un :class:`~delugeapp.core.songwriter.SongSpec`
— un synthé, un kit ou une piste MIDI par piste, au choix piste par piste —
coupé en **sections** du Deluge : les scènes du projet s'il en a, sinon ses
repères, sinon des tranches de quelques mesures ; une section qui se répète
tient dans un clip court qui boucle (:func:`~delugeapp.core.songwriter.fold`).
L'écriture passe par :func:`~delugeapp.core.songwriter.write_song` : un
fichier neuf, jamais un morceau existant.
"""

from __future__ import annotations

import gzip
import logging
import math
import re
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from ..i18n import tr, untranslated
from . import midifile
from .daw import DawClip, DawNote, DawScene, DawSong, DawTrack, Placement

log = logging.getLogger(__name__)

__all__ = ["EXTENSIONS", "read_project", "from_midi", "from_dawproject",
           "from_als", "from_rpp", "ImportChoice", "guess_role",
           "default_choices", "sections_of", "uses_scenes", "build_song",
           "SECTION_SOURCES", "IMPORT_KINDS"]

#: Ce que l'import sait ouvrir.
EXTENSIONS = (".mid", ".midi", ".dawproject", ".als", ".rpp")

#: Le nombre de sections que connaît le firmware des morceaux écrits.
MAX_SECTIONS = 12


# --------------------------------------------------------------------------- #
# Fichier MIDI
# --------------------------------------------------------------------------- #

def from_midi(path: Path) -> DawSong:
    """Un fichier MIDI : une piste par piste du fichier — par canal, s'il en
    mêle plusieurs (type 0) ; le canal 10 fait une batterie."""
    data = midifile.read_midi(Path(path))
    ppq = float(data.ppq)
    song = DawSong(name=Path(path).stem, bpm=round(data.tempo, 3),
                   numerator=data.numerator, denominator=data.denominator)
    song.markers = [(t / ppq, texte) for t, texte in data.markers]
    numero = 0
    for nom, notes in data.tracks:
        canaux = sorted({n[4] for n in notes})
        for canal in canaux:
            numero += 1
            mes_notes = [DawNote(n[1], n[0] / ppq, n[3] / ppq, n[2])
                         for n in notes if n[4] == canal]
            if not mes_notes:
                continue
            titre = nom or tr("Piste %d") % numero
            if len(canaux) > 1:
                titre = tr("%s (canal %d)") % (titre, canal + 1)
            song.tracks.append(_single_clip_track(
                titre, mes_notes, canal, song.numerator))
    return song


def _single_clip_track(name: str, notes: list[DawNote], channel: int,
                       numerator: int) -> DawTrack:
    """Une piste d'un seul clip posé au début, arrondi à la mesure."""
    fin = max((n.start + n.length for n in notes), default=0.0)
    longueur = max(float(numerator),
                   math.ceil(fin / numerator - 1e-9) * numerator)
    track = DawTrack(name=name, kind="kit" if channel == 9 else "synth",
                     channel=channel)
    track.clips.append(DawClip(name=name, length=longueur,
                               notes=sorted(notes, key=lambda n: n.start)))
    track.placements.append(Placement(0, 0.0, longueur))
    return track


# --------------------------------------------------------------------------- #
# DAWproject
# --------------------------------------------------------------------------- #

def _f(text, default: float = 0.0) -> float:
    try:
        return float(text)
    except (TypeError, ValueError):
        return default


def _dp_notes(clip: ET.Element, offset: float = 0.0) -> list[DawNote]:
    """Les notes d'un clip DAWproject, ses clips imbriqués compris."""
    out: list[DawNote] = []
    for notes in clip.findall("Notes"):
        for n in notes.findall("Note"):
            out.append(DawNote(int(_f(n.get("key"), 60)),
                               offset + _f(n.get("time")),
                               max(1e-3, _f(n.get("duration"), 0.25)),
                               max(1, min(127, int(round(
                                   _f(n.get("vel"), 0.8) * 127))))))
    for inner in clip.findall("Clips"):
        for c in inner.findall("Clip"):
            out += _dp_notes(c, offset + _f(c.get("time")))
    return out


def _dp_clip(el: ET.Element, name: str) -> tuple[DawClip, float, float]:
    """``(clip, début, durée)`` : la boucle du clip, et sa place."""
    debut = _f(el.get("time"))
    duree = _f(el.get("duration"), 4.0)
    loop_start = _f(el.get("loopStart"), 0.0)
    loop_end = el.get("loopEnd")
    notes = _dp_notes(el)
    if loop_end is not None and _f(loop_end) > loop_start:
        longueur = _f(loop_end) - loop_start
        notes = [DawNote(n.pitch, n.start - loop_start, n.length, n.velocity)
                 for n in notes if loop_start <= n.start < _f(loop_end)]
    else:
        longueur = duree
    return DawClip(el.get("name") or name, max(1e-3, longueur), notes), \
        debut, duree


def _count_channels(canaux: dict, ident: str | None,
                    clip: ET.Element) -> None:
    compte = canaux.setdefault(ident or "", Counter())
    for n in clip.iter("Note"):
        compte[int(_f(n.get("channel"), 0)) & 15] += 1


def from_dawproject(path: Path) -> DawSong:
    """Un ``.dawproject`` : pistes de notes, arrangement, scènes, repères."""
    with zipfile.ZipFile(Path(path)) as z:
        root = ET.fromstring(z.read("project.xml"))
    song = DawSong(name=Path(path).stem)
    tempo = root.find("Transport/Tempo")
    if tempo is not None:
        song.bpm = _f(tempo.get("value"), 120.0)
    signature = root.find("Transport/TimeSignature")
    if signature is not None:
        song.numerator = int(_f(signature.get("numerator"), 4))
        song.denominator = int(_f(signature.get("denominator"), 4))
    pistes: dict[str, DawTrack] = {}
    for el in root.iter("Track"):
        types = (el.get("contentType") or "").split()
        if "notes" not in types:
            continue
        canal = el.find("Channel")
        if canal is not None and canal.get("role") == "master":
            continue
        track = DawTrack(name=el.get("name") or tr("Piste %d")
                         % (len(pistes) + 1))
        pistes[el.get("id") or str(len(pistes))] = track
        song.tracks.append(track)
    canaux: dict[str, Counter] = {}
    secondes = False
    arrangement = root.find("Arrangement")
    if arrangement is not None:
        lanes = arrangement.find("Lanes")
        if lanes is not None:
            secondes = lanes.get("timeUnit") == "seconds"
            for lane in lanes.iter("Lanes"):
                track = pistes.get(lane.get("track") or "")
                if track is None:
                    continue
                for clips in lane.findall("Clips"):
                    for c in clips.findall("Clip"):
                        clip, debut, duree = _dp_clip(c, track.name)
                        if not clip.notes:
                            continue
                        _count_channels(canaux, lane.get("track"), c)
                        track.clips.append(clip)
                        track.placements.append(Placement(
                            len(track.clips) - 1, debut, duree))
        for m in arrangement.findall("Markers/Marker"):
            song.markers.append((_f(m.get("time")), m.get("name") or ""))
    for s, scene in enumerate(root.findall("Scenes/Scene")):
        longest = 0.0
        for slot in scene.iter("ClipSlot"):
            track = pistes.get(slot.get("track") or "")
            c = slot.find("Clip")
            if track is None or c is None:
                continue
            clip, _debut, _duree = _dp_clip(c, track.name)
            if not clip.notes:
                continue
            _count_channels(canaux, slot.get("track"), c)
            track.clips.append(clip)
            track.scenes[s] = len(track.clips) - 1
            longest = max(longest, clip.length)
        song.scenes.append(DawScene(scene.get("name") or tr("Scène %d")
                                    % (s + 1), longest))
    # Le canal le plus joué de chaque piste : le 10 fait une batterie.
    for ident, compte in canaux.items():
        track = pistes[ident]
        track.channel = compte.most_common(1)[0][0]
        if track.channel == 9:
            track.kind = "kit"
    if secondes:
        _seconds_to_beats(song)
    song.markers.sort()
    song.arranged = any(t.placements for t in song.tracks)
    return song


def _snap(beats: float) -> float:
    """Une position tirée des secondes, recalée sur la grille de 960 par
    noire quand elle en est à un cheveu : sans cela, 144 noires relues comme
    144,0000002 ajoutent un tour de boucle de durée nulle."""
    grille = round(beats * 960.0) / 960.0
    return grille if abs(grille - beats) < 1e-4 else beats


def _seconds_to_beats(song: DawSong) -> None:
    k = song.bpm / 60.0
    for track in song.tracks:
        for p in track.placements:
            p.start = _snap(p.start * k)
            p.length = _snap(p.length * k)
    song.markers = [(_snap(t * k), nom) for t, nom in song.markers]


# --------------------------------------------------------------------------- #
# Ableton Live
# --------------------------------------------------------------------------- #

def _v(el: ET.Element | None, path: str, default: str = "") -> str:
    if el is None:
        return default
    found = el.find(path)
    if found is None:
        return default
    return found.get("Value", default)


def _als_notes(clip: ET.Element) -> list[DawNote]:
    """Les notes d'un ``MidiClip`` : une piste de touche par hauteur."""
    out: list[DawNote] = []
    for key_track in clip.iter("KeyTrack"):
        pitch = int(_f(_v(key_track, "MidiKey"), -1))
        if not 0 <= pitch <= 127:
            continue
        for n in key_track.iter("MidiNoteEvent"):
            if n.get("IsEnabled", "true") == "false":
                continue
            out.append(DawNote(pitch, _f(n.get("Time")),
                               max(1e-3, _f(n.get("Duration"), 0.25)),
                               max(1, min(127, int(round(
                                   _f(n.get("Velocity"), 100)))))))
    return out


def _als_clip(clip: ET.Element, name: str) -> tuple[DawClip, float, float]:
    """``(clip, début, durée)`` d'un clip de Live : sa boucle s'il boucle,
    sinon la portion jouée."""
    debut = _f(_v(clip, "CurrentStart"), _f(clip.get("Time")))
    fin = _f(_v(clip, "CurrentEnd"), debut + 4.0)
    loop_start = _f(_v(clip, "Loop/LoopStart"), 0.0)
    loop_end = _f(_v(clip, "Loop/LoopEnd"), loop_start + (fin - debut))
    relatif = _f(_v(clip, "Loop/StartRelative"), 0.0)
    boucle = _v(clip, "Loop/LoopOn", "true") == "true"
    notes = _als_notes(clip)
    if boucle and loop_end > loop_start:
        origine = loop_start
        longueur = loop_end - loop_start
    else:
        origine = loop_start + relatif
        longueur = max(1e-3, fin - debut)
    notes = [DawNote(n.pitch, n.start - origine, n.length, n.velocity)
             for n in notes if origine <= n.start < origine + longueur]
    nom = _v(clip, "Name") or name
    return DawClip(nom, longueur, notes), debut, fin - debut


def from_als(path: Path) -> DawSong:
    """Un set Ableton Live (``.als``) : ses pistes MIDI, les clips de
    l'arrangement et du lanceur, ses scènes et ses repères."""
    with gzip.open(Path(path), "rb") as f:
        root = ET.fromstring(f.read())
    live = root.find("LiveSet")
    if live is None:
        raise ValueError(tr("ce fichier n'est pas un set Ableton Live"))
    song = DawSong(name=Path(path).stem)
    maitre = live.find("MainTrack")
    if maitre is None:
        maitre = live.find("MasterTrack")
    tempo = _f(_v(maitre, "DeviceChain/Mixer/Tempo/Manual"), 120.0)
    song.bpm = tempo if tempo > 0 else 120.0
    # Live 10 et après : ``Scenes/Scene/Name`` ; Live 8 et 9 :
    # ``SceneNames/Scene Value="…"``.
    noms_scenes = [_v(s, "Name").strip()
                   for s in live.findall("Scenes/Scene")] \
        or [s.get("Value", "").strip()
            for s in live.findall("SceneNames/Scene")]
    longueurs = [0.0] * len(noms_scenes)
    tracks = live.find("Tracks")
    for el in list(tracks) if tracks is not None else []:
        if el.tag != "MidiTrack":
            continue
        nom = (_v(el, "Name/UserName") or _v(el, "Name/EffectiveName")
               or tr("Piste %d") % (len(song.tracks) + 1))
        track = DawTrack(name=nom)
        sequenceur = el.find("DeviceChain/MainSequencer")
        if sequenceur is None:
            continue
        for clip in sequenceur.findall(
                "ClipTimeable/ArrangerAutomation/Events/MidiClip"):
            c, debut, duree = _als_clip(clip, nom)
            if c.notes:
                track.clips.append(c)
                track.placements.append(Placement(len(track.clips) - 1,
                                                  debut, duree))
        for s, slot in enumerate(sequenceur.findall(
                "ClipSlotList/ClipSlot")):
            clip = slot.find("ClipSlot/Value/MidiClip")
            if clip is None:
                continue
            c, _debut, _duree = _als_clip(clip, nom)
            if not c.notes:
                continue
            track.clips.append(c)
            track.scenes[s] = len(track.clips) - 1
            if s < len(longueurs):
                longueurs[s] = max(longueurs[s], c.length)
        if track.clips:
            song.tracks.append(track)
    song.scenes = [DawScene(n or tr("Scène %d") % (i + 1), longueurs[i])
                   for i, n in enumerate(noms_scenes) if longueurs[i] > 0]
    # Les scènes vides retirées : les numéros des pistes suivent.
    gardees = [i for i in range(len(noms_scenes)) if longueurs[i] > 0]
    renumero = {old: new for new, old in enumerate(gardees)}
    for track in song.tracks:
        track.scenes = {renumero[s]: c for s, c in track.scenes.items()
                        if s in renumero}
    for loc in live.findall("Locators/Locators/Locator"):
        song.markers.append((_f(_v(loc, "Time")), _v(loc, "Name")))
    song.markers.sort()
    song.arranged = any(t.placements for t in song.tracks)
    return song


# --------------------------------------------------------------------------- #
# Reaper
# --------------------------------------------------------------------------- #

_TOKEN = re.compile(r'"[^"]*"|\S+')


def _tokens(line: str) -> list[str]:
    return [t[1:-1] if t.startswith('"') else t
            for t in _TOKEN.findall(line)]


def from_rpp(path: Path) -> DawSong:
    """Un projet Reaper : ses pistes et leurs objets MIDI (sources
    embarquées), qui bouclent s'ils durent plus que leur source."""
    lignes = Path(path).read_text(encoding="utf-8",
                                  errors="replace").splitlines()
    song = DawSong(name=Path(path).stem)
    pile: list[str] = []
    track: DawTrack | None = None
    item: dict = {}
    source: dict | None = None
    canaux: dict[int, tuple[DawTrack, Counter]] = {}
    for brute in lignes:
        ligne = brute.strip()
        if not ligne:
            continue
        if ligne.startswith("<"):
            mots = _tokens(ligne[1:])
            balise = mots[0] if mots else ""
            pile.append(balise)
            if balise == "TRACK":
                track = DawTrack(name=tr("Piste %d") % (len(song.tracks) + 1))
                song.tracks.append(track)
            elif balise == "ITEM":
                item = {"position": 0.0, "length": 0.0, "loop": True,
                        "name": ""}
            elif balise == "SOURCE" and len(mots) > 1 and mots[1] == "MIDI":
                source = {"ppq": 960, "tick": 0, "notes": [], "open": {},
                          "end": 0}
            continue
        if ligne == ">":
            balise = pile.pop() if pile else ""
            if balise == "ITEM" and track is not None and item.get("clip"):
                clip = item["clip"]
                k = song.bpm / 60.0
                track.clips.append(clip)
                duree = _snap(item["length"] * k)
                if not item["loop"]:
                    clip.length = max(clip.length, duree)
                track.placements.append(Placement(
                    len(track.clips) - 1, _snap(item["position"] * k), duree))
            if balise == "SOURCE" and source is not None:
                ppq = float(source["ppq"])
                notes = [DawNote(p, t / ppq, max(1, d) / ppq, v)
                         for t, p, v, d in source["notes"]]
                longueur = max(1, source["end"]) / ppq
                item["clip"] = DawClip(item.get("name") or (
                    track.name if track else ""), longueur, notes)
                source = None
            continue
        mots = _tokens(ligne)
        if not mots:
            continue
        cle = mots[0]
        if not pile:
            continue
        if pile[-1] == "REAPER_PROJECT" and cle == "TEMPO" and len(mots) > 1:
            song.bpm = _f(mots[1], 120.0)
            if len(mots) > 3:
                song.numerator = int(_f(mots[2], 4))
                song.denominator = int(_f(mots[3], 4))
        elif pile[-1] == "REAPER_PROJECT" and cle == "MARKER" \
                and len(mots) > 3:
            song.markers.append((_f(mots[2]), mots[3]))
        elif pile[-1] == "TRACK" and cle == "NAME" and track is not None \
                and len(mots) > 1:
            track.name = mots[1] or track.name
        elif pile[-1] == "ITEM":
            if cle == "POSITION" and len(mots) > 1:
                item["position"] = _f(mots[1])
            elif cle == "LENGTH" and len(mots) > 1:
                item["length"] = _f(mots[1])
            elif cle == "LOOP" and len(mots) > 1:
                item["loop"] = mots[1] != "0"
            elif cle == "NAME" and len(mots) > 1:
                item["name"] = mots[1]
        elif source is not None and pile[-1] == "SOURCE":
            if cle == "HASDATA" and len(mots) > 2:
                source["ppq"] = int(_f(mots[2], 960)) or 960
            elif cle in ("E", "e") and len(mots) >= 5:
                try:
                    delta = int(mots[1])
                    status = int(mots[2], 16)
                    d1 = int(mots[3], 16)
                    d2 = int(mots[4], 16)
                except ValueError:
                    continue
                source["tick"] += delta
                t = source["tick"]
                source["end"] = t
                kind = status & 0xF0
                cle_note = (status & 0x0F, d1)
                if kind == 0x90 and d2 > 0:
                    source["open"].setdefault(cle_note, []).append((t, d2))
                    if track is not None:
                        canaux.setdefault(id(track), (track, Counter()))[1][
                            status & 0x0F] += 1
                elif kind == 0x80 or (kind == 0x90 and d2 == 0):
                    ouvertes = source["open"].get(cle_note)
                    if ouvertes:
                        debut, vel = ouvertes.pop(0)
                        source["notes"].append((debut, d1, vel, t - debut))
    # Les repères de Reaper sont en secondes.
    k = song.bpm / 60.0
    song.markers = sorted((_snap(t * k), nom) for t, nom in song.markers)
    for track, compte in canaux.values():
        track.channel = compte.most_common(1)[0][0]
        if track.channel == 9:
            track.kind = "kit"
    song.tracks = [t for t in song.tracks if t.has_notes]
    song.arranged = any(t.placements for t in song.tracks)
    return song


_READERS = {".mid": from_midi, ".midi": from_midi,
            ".dawproject": from_dawproject, ".als": from_als,
            ".rpp": from_rpp}


def read_project(path: Path) -> DawSong:
    """Ouvre un projet d'après son extension (:data:`EXTENSIONS`).

    Lève :class:`ValueError`, avec un message lisible, pour un format
    inconnu comme pour un fichier abîmé ou tronqué."""
    path = Path(path)
    lecteur = _READERS.get(path.suffix.lower())
    if lecteur is None:
        raise ValueError(tr("format non pris en charge : %s")
                         % (path.suffix or path.name))
    try:
        return lecteur(path)
    except ValueError:
        raise
    except (OSError, EOFError, KeyError, ET.ParseError,
            zipfile.BadZipFile) as exc:
        log.info("projet illisible %s : %s", path, exc)
        raise ValueError(tr("%s est illisible : %s") % (path.name, exc)) \
            from exc


# --------------------------------------------------------------------------- #
# Vers un morceau du Deluge
# --------------------------------------------------------------------------- #

#: Natures proposées pour une piste importée.
IMPORT_KINDS = ("synth", "kit", "midi", "skip")

#: Des fragments de noms de piste, en anglais et en français : on les
#: cherche dans les noms, on ne les affiche pas.
_ROLE_HINTS = untranslated((
    ("bass", ("bass", "basse", "sub", "808")),
    ("pad", ("pad", "nappe", "string", "cordes", "choir", "atmo")),
    ("keys", ("key", "piano", "rhodes", "organ", "orgue", "chord", "accord",
              "ep ")),
    ("pluck", ("pluck", "pinc", "harp")),
    ("arp", ("arp",)),
    ("lead", ("lead", "melod", "mélod", "solo", "hook")),
))
_DRUM_HINTS = ("drum", "batterie", "beat", "kick", "perc", "kit")


@dataclass
class ImportChoice:
    """Ce que devient une piste du projet dans le Deluge.

    :param kind: ``synth``, ``kit``, ``midi`` (piste MIDI de la machine, vers
        un appareil extérieur) ou ``skip``.
    :param role: le rôle du son généré (``bass``, ``lead``…) si ``preset``
        est vide.
    :param preset: le son choisi : un :class:`~delugeapp.core.model.SynthPreset`
        pour un synthé, un :class:`~delugeapp.core.model.Kit` pour une
        batterie (complété par la bibliothèque) ; ``None`` pour un son
        généré.
    :param channel: le canal de sortie d'une piste MIDI (1–16).
    """

    kind: str = "synth"
    role: str = "lead"
    preset: object = None
    channel: int = 1


def guess_role(track: DawTrack) -> str:
    """Le rôle probable d'une piste : son nom d'abord, sa tessiture et sa
    polyphonie ensuite."""
    nom = " %s " % track.name.lower()
    for role, mots in _ROLE_HINTS:
        if any(m in nom for m in mots):
            return role
    notes = [n for c in track.clips for n in c.notes]
    if not notes:
        return "lead"
    hauteurs = sorted(n.pitch for n in notes)
    mediane = hauteurs[len(hauteurs) // 2]
    if mediane < 48:
        return "bass"
    debuts: dict[float, int] = {}
    for n in notes:
        debuts[round(n.start, 3)] = debuts.get(round(n.start, 3), 0) + 1
    if max(debuts.values()) >= 3:
        return "pad" if sum(n.length for n in notes) / len(notes) >= 2 \
            else "keys"
    return "lead"


_KICKS_SNARES = {35, 36, 38, 40}
_HATS = {42, 44, 46}


def looks_like_drums(track: DawTrack) -> bool:
    """Vrai pour une piste qui joue comme une batterie General MIDI : grosse
    caisse ou caisse claire **et** charleston, trois hauteurs au moins,
    sept notes sur dix entre 35 et 59 (le cœur de la batterie), des notes
    courtes. Un projet ne dit pas toujours qu'une piste est une batterie ;
    son contenu, souvent. Une ligne de synthé qui passe par ces hauteurs
    monte plus haut.

    Mesuré sur les 128 pistes des morceaux de la carte, exportées puis
    relues : avec le canal et le nom, 126 justes (les deux autres, des
    synthés nommés « KICK ») ; le contenu seul en reconnaît 106 — il manque
    les kits qui ne jouent qu'une ou deux rangées."""
    notes = [n for c in track.clips for n in c.notes]
    hauteurs = {n.pitch for n in notes}
    if len(hauteurs) < 3 or not (hauteurs & _KICKS_SNARES) \
            or not (hauteurs & _HATS):
        return False
    coeur = sum(1 for n in notes if 35 <= n.pitch <= 59)
    if coeur < 0.7 * len(notes):
        return False
    durees = sorted(n.length for n in notes)
    return durees[len(durees) // 2] <= 0.5


def default_choices(song: DawSong) -> list[ImportChoice]:
    """Le choix proposé pour chaque piste : batterie sur le canal 10, au
    nom de batterie ou au jeu de batterie, synthé du rôle deviné sinon."""
    out = []
    for track in song.tracks:
        nom = track.name.lower()
        if track.kind == "kit" or track.channel == 9 \
                or any(m in nom for m in _DRUM_HINTS) \
                or looks_like_drums(track):
            out.append(ImportChoice(kind="kit", role="drums"))
        elif not track.has_notes:
            out.append(ImportChoice(kind="skip"))
        else:
            out.append(ImportChoice(kind="synth", role=guess_role(track)))
    return out


#: D'où viennent les sections du morceau importé.
SECTION_SOURCES = ("auto", "arrangement", "scenes")


def sections_of(song: DawSong, bars: int = 8) -> list[tuple[float, float,
                                                              str]]:
    """Les sections du futur morceau, tirées de l'arrangement : ``(début,
    fin, nom)`` en noires.

    Les repères du projet coupent d'abord (douze au plus : au-delà, la plus
    courte section fusionne avec la suivante). Une section plus longue que
    ``bars`` mesures est ensuite découpée en tranches de ``bars`` mesures —
    sans repère, tout le morceau l'est —, tranches doublées tant qu'elles
    dépasseraient douze sections. Le déroulé ne change pas : le morceau
    écrit enchaîne ses sections dans son arrangement ; les clips, eux,
    restent à la taille de la machine."""
    mesure = float(max(1, song.numerator))
    fin = max(song.length, mesure)
    fin = math.ceil(fin / mesure - 1e-9) * mesure
    noms = {round(t, 6): n for t, n in song.markers}
    bornes = sorted({round(t, 6) for t, _n in song.markers if 0 < t < fin})
    bornes = [0.0] + bornes + [fin]
    while len(bornes) - 1 > MAX_SECTIONS:
        _e, i = min((bornes[i + 1] - bornes[i], i)
                    for i in range(1, len(bornes) - 1))
        del bornes[i]
    grandes = [(bornes[i], bornes[i + 1],
                noms.get(bornes[i], "") or (tr("Début") if i == 0
                                            and len(bornes) > 2
                                            else tr("Section %d") % (i + 1)))
               for i in range(len(bornes) - 1)]
    taille = max(1, int(bars)) * mesure

    def decoupe(taille: float) -> list[tuple[float, float, str]]:
        out = []
        for a, b, nom in grandes:
            n = max(1, math.ceil((b - a) / taille - 1e-9))
            for k in range(n):
                out.append((a + k * taille, min(b, a + (k + 1) * taille),
                            nom if n == 1 or k == 0
                            else "%s %d" % (nom, k + 1)))
        return out

    while True:
        out = decoupe(taille)
        if len(out) <= MAX_SECTIONS or taille >= fin:
            break
        taille *= 2
    if len(out) > MAX_SECTIONS:
        out = grandes
    if len(grandes) == 1 and len(out) > 1:
        out = [(a, b, tr("Section %d") % (i + 1))
               for i, (a, b, _n) in enumerate(out)]
    return out


def _notes_between(track: DawTrack, a: float, b: float) -> list[DawNote]:
    from .daw import _expanded
    return [DawNote(n.pitch, n.start - a, n.length, n.velocity)
            for debut, n in _expanded(track) if a - 1e-9 <= debut < b - 1e-9]


def uses_scenes(song: DawSong, source: str = "auto") -> bool:
    """Vrai si les sections viendront des scènes : demandé, ou bien
    ``auto`` et le projet a des scènes sans arrangement."""
    if source == "scenes":
        return bool(song.scenes)
    if source == "arrangement":
        return bool(song.scenes) and not any(t.placements
                                             for t in song.tracks)
    return bool(song.scenes) and not song.arranged


def build_song(song: DawSong, choices: list[ImportChoice], *, name: str,
               sd=None, lib=None, genre: str = "", bars: int = 8,
               source: str = "auto", seed: int = 7):
    """Le :class:`~delugeapp.core.songwriter.SongSpec` du morceau importé.

    Les sections viennent des scènes ou de l'arrangement
    (:func:`uses_scenes`, :func:`sections_of`). Chaque piste retenue reçoit
    un clip par section où elle joue, replié sur sa plus courte boucle ; une
    piste qui ne joue nulle part n'est pas créée. Chaque piste de batterie
    reçoit son kit, monté dans la bibliothèque d'après les rôles General
    MIDI de ses notes.

    Lève :class:`ValueError` si rien n'est à écrire.
    """
    from . import songwriter as sw
    from . import synthgen
    from .model import Note

    par_noire = sw.BAR // 4
    scenes = uses_scenes(song, source)
    if scenes:
        sections = [(0.0, max(1.0, s.length), s.name)
                    for s in song.scenes[:MAX_SECTIONS]]
    else:
        sections = sections_of(song, bars)
    tracks: list = []
    clips: list = []
    summary: list[str] = []
    for track, choice in zip(song.tracks, choices):
        if choice.kind not in ("synth", "kit", "midi") \
                or not track.has_notes:
            continue
        rows_of: dict[int, int] = {}
        if choice.kind == "kit":
            hauteurs = sorted({n.pitch for c in track.clips for n in c.notes})
            kit_obj, rows_of = _kit_for(sd, lib, genre, hauteurs,
                                        choice.preset, seed)
            if kit_obj is None:
                summary.append(tr("%s : la bibliothèque n'a pas de kit à "
                                  "proposer, piste laissée") % track.name)
                continue
        mes_clips = []
        for s, (a, b, _nom) in enumerate(sections):
            if scenes:
                if s not in track.scenes:
                    continue
                clip = track.clips[track.scenes[s]]
                notes = [n for n in clip.notes if 0 <= n.start < clip.length]
                longueur = clip.length
            else:
                notes = _notes_between(track, a, b)
                longueur = b - a
            ticks = max(par_noire, int(round(longueur * par_noire)))
            rows: dict[int, list] = {}
            for n in notes:
                row = rows_of.get(n.pitch) if choice.kind == "kit" \
                    else n.pitch
                if row is None:
                    continue
                rows.setdefault(row, []).append(Note(
                    pos=int(round(n.start * par_noire)),
                    length=max(1, int(round(n.length * par_noire))),
                    velocity=max(1, min(127, int(n.velocity)))))
            rows = {y: sw._clean_notes(v, ticks) for y, v in rows.items()}
            rows = {y: v for y, v in rows.items() if v}
            if rows:
                rows, ticks = sw.fold(rows, ticks)
                mes_clips.append((s, ticks, rows))
        if not mes_clips:
            summary.append(tr("%s : aucune note dans les sections, piste "
                              "laissée") % track.name)
            continue
        label = sw._label(track.name[:20], "")
        if choice.kind == "kit":
            built = sw.kit_track(kit_obj, name=label or "KIT")
        elif choice.kind == "midi":
            built = sw.midi_track(choice.channel, name=label)
        else:
            preset = choice.preset
            if preset is None:
                preset = synthgen.generate(synthgen.GenOptions(
                    genre=genre or "techno", role=choice.role, seed=seed))
            # Les notes viennent déjà arpégées du DAW.
            built = sw.synth_track(preset, name=label or "SYNTH", arp=False)
        tracks.append(built)
        for s, ticks, rows in mes_clips:
            clips.append(sw.ClipSpec(track=len(tracks) - 1, length=ticks,
                                     rows=rows, section=s,
                                     name=sw.ascii_label(track.name)))
        summary.append(tr("%s : %s, %d clip(s)") % (
            track.name, built.name, len(mes_clips)))
        if choice.kind == "kit":
            sans = sorted(set(hauteurs) - set(rows_of))
            if sans:
                summary.append(tr("%s : %d hauteur(s) sans son dans le kit, "
                                  "leurs notes sont laissées (%s)") % (
                    track.name, len(sans), ", ".join(map(str, sans[:12]))))
    if not clips:
        raise ValueError(tr("aucune note à écrire dans le morceau"))
    sections_spec = [sw.SectionSpec(name=nom, length=max(par_noire, int(
        round((b - a) * par_noire)))) for a, b, nom in sections]
    return sw.SongSpec(name=name, bpm=float(song.bpm), root=song.root,
                       mode_notes=song.mode_notes, tracks=tracks,
                       clips=clips, sections=sections_spec, summary=summary)


#: Les autres notes de la batterie General MIDI, rapportées aux rôles des kits
#: (:data:`~delugeapp.core.midifile.GM_DRUMS` n'en garde qu'une par rôle).
_GM_EXTRA = {35: "Kick", 40: "Snare", 44: "HatC", 41: "TomL", 43: "TomL",
             48: "TomM", 53: "Ride", 59: "Ride", 55: "Crash", 57: "Crash",
             58: "Other", 60: "ConH", 61: "ConL", 69: "Shaker", 82: "Shaker",
             77: "Block", 74: "Guiro"}


def _kit_for(sd, lib, genre: str, pitches: list[int], kit, seed: int):
    """``(kit, {hauteur: rangée})`` : chaque hauteur prend le rôle que lui
    donne la batterie General MIDI ; ``kit`` (un kit de la carte), s'il est
    donné, joue les rôles qu'il a et la bibliothèque complète les autres —
    une copie : le kit de la carte ne change pas."""
    from . import songwriter as sw
    inverse: dict[int, str] = {}
    for role, pitch in midifile.GM_DRUMS.items():
        inverse.setdefault(pitch, role)
    for pitch, role in _GM_EXTRA.items():
        inverse.setdefault(pitch, role)
    noms: dict[int, str] = {}
    pris: set[str] = set()
    for p in pitches:
        role = inverse.get(p, "")
        nom = role if role and role not in pris else "N%d" % p
        pris.add(nom)
        noms[p] = nom
    if sd is None or lib is None:
        if kit is None:
            return None, {}
        mapping = sw.drum_rows(list(noms.values()), kit)
    else:
        kit, mapping, _lost = sw.drum_kit_for(sd, lib, genre or "techno",
                                              list(noms.values()), base=kit,
                                              seed=seed)
    rows = {p: mapping[n] for p, n in noms.items() if n in mapping}
    return (kit, rows) if kit is not None and rows else (None, {})
