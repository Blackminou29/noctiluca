# -*- coding: utf-8 -*-
"""Le pont entre le Deluge et un logiciel de musique (DAW).

Le compositeur esquisse sur la machine et finit souvent dans un DAW — ou
l'inverse. Ce module tient un **modèle commun** du morceau, indépendant de
l'un et de l'autre (:class:`DawSong`), et les traductions dans les deux sens :

* **du Deluge** : un morceau de la carte, lu tel que la machine le joue
  (:func:`from_deluge`) — son arrangement s'il en a un (``clipInstances`` :
  position, longueur et numéro de chaque clip posé), sinon l'enchaînement de
  ses sections, chacune durant ``numRepeats`` fois son plus long clip
  (``Session::armNextSection``) ; les sections deviennent aussi des
  **scènes** pour les DAW qui ont un lanceur de clips ;
* **vers les DAW** : un dossier universel (MIDI de type 1, pistes audio,
  lisez-moi) que tout logiciel ouvre, plus des projets prêts à l'emploi —
  DAWproject (Bitwig, Studio One, Cubase : format ouvert, schéma 1.0 de
  Bitwig) et Reaper (``.rpp``, texte) ; Ableton Live par :mod:`.dawals`.

Les temps sont en **noires** (``beats``), comme dans les DAW ; une mesure
4/4 en compte quatre. Le Deluge compte ``24 << inputTickMagnitude`` ticks
par noire (:func:`delugeapp.core.model.ticks_per_bar`).

Ce module ne touche jamais la carte : il lit un morceau et écrit dans le
dossier qu'on lui donne.
"""

from __future__ import annotations

import copy
import logging
import math
import re
import shutil
import time
import unicodedata
import uuid
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from ..i18n import N_, tr, untranslated
from . import dxml, midifile
from .analysis import classify_drum
from .model import Clip, Kit, Sound, ticks_per_bar

log = logging.getLogger(__name__)

__all__ = ["DawNote", "DawClip", "Placement", "DawTrack", "DawScene",
           "DawSong", "FORMATS", "from_deluge", "write_midi",
           "write_dawproject", "write_rpp", "write_readme", "write_folder",
           "safe_file_name", "drum_pitch"]


# --------------------------------------------------------------------------- #
# Le modèle commun
# --------------------------------------------------------------------------- #

@dataclass
class DawNote:
    """Une note : hauteur MIDI, début et durée en noires, vélocité 1–127."""

    pitch: int
    start: float
    length: float
    velocity: int = 100


@dataclass
class DawClip:
    """Une boucle de notes. ``length`` est sa longueur de boucle, en noires.

    ``source`` garde, pour un clip venu du Deluge, de quoi en recalculer le
    son : ``(élément de l'instrument, élément du clip)``.
    """

    name: str
    length: float
    notes: list[DawNote] = field(default_factory=list)
    source: object = None


@dataclass
class Placement:
    """Un clip posé sur la ligne de temps : il boucle s'il dure plus que lui."""

    clip: int
    start: float
    length: float


#: Natures de piste : celles du Deluge, plus ``audio``.
TRACK_KINDS = ("synth", "kit", "midi", "cv", "audio")


@dataclass
class DawTrack:
    """Une piste du morceau.

    :param channel: canal MIDI (0–15) ; 9 pour une batterie.
    :param drums: pour un kit, la hauteur MIDI de chaque son →
        ``(indice de la rangée, nom)``.
    :param scenes: scène → indice du clip qui y joue.
    :param audio: la piste audio rendue, si elle existe.
    :param listens: le canal (0–15) que l'instrument écoute sur la machine,
        s'il en écoute un (:func:`listened_channel`) ; ``channel`` le reprend.
    """

    name: str
    kind: str = "synth"
    channel: int = 0
    listens: int | None = None
    clips: list[DawClip] = field(default_factory=list)
    placements: list[Placement] = field(default_factory=list)
    scenes: dict[int, int] = field(default_factory=dict)
    drums: dict[int, tuple[int, str]] = field(default_factory=dict)
    audio: Path | None = None
    instrument: object = None

    @property
    def has_notes(self) -> bool:
        return any(c.notes for c in self.clips)

    @property
    def end(self) -> float:
        return max((p.start + p.length for p in self.placements), default=0.0)


@dataclass
class DawScene:
    """Une scène (une section du Deluge) : son nom et sa durée en noires."""

    name: str
    length: float


@dataclass
class DawSong:
    """Le morceau, tel que tout DAW peut le recevoir.

    :param arranged: vrai si l'arrangement vient du morceau lui-même
        (``clipInstances``) ; faux s'il est déduit des sections.
    """

    name: str
    bpm: float = 120.0
    numerator: int = 4
    denominator: int = 4
    root: int = 0
    mode_notes: tuple[int, ...] = (0, 2, 4, 5, 7, 9, 11)
    tracks: list[DawTrack] = field(default_factory=list)
    scenes: list[DawScene] = field(default_factory=list)
    markers: list[tuple[float, str]] = field(default_factory=list)
    arranged: bool = False
    #: Les clips lus, dans l'ordre de ``Song.clips + Song.arrangement_clips``
    #: — celui de la page Morceaux : ``(piste, clip)``, ou ``None`` pour un
    #: clip sans piste reconnue.
    clip_order: list = field(default_factory=list)

    @property
    def length(self) -> float:
        """Fin de l'arrangement, en noires."""
        return max((t.end for t in self.tracks), default=0.0)

    @property
    def seconds_per_beat(self) -> float:
        return 60.0 / max(1.0, float(self.bpm))

    def seconds(self, beats: float) -> float:
        return float(beats) * self.seconds_per_beat


# --------------------------------------------------------------------------- #
# Lecture d'un morceau du Deluge
# --------------------------------------------------------------------------- #

_INSTRUMENT_TAGS = {"sound": "synth", "kit": "kit", "midi": "midi",
                    "midiChannel": "midi", "mpeZone": "midi",
                    "cvChannel": "cv", "audioOutput": "audio"}
_CLIP_TAGS = ("instrumentClip", "audioClip")
#: Premier code d'un clip posé qui vise les clips de l'arrangement seul
#: (``arrangementOnlyClips``) plutôt que ceux de la session.
_ARRANGEMENT_ONLY = 0x80000000


def _first(root: ET.Element, names) -> ET.Element | None:
    for name in names:
        found = dxml.get_child(root, name)
        if found is not None:
            return found
    return None


def _int(text, default: int = 0) -> int:
    try:
        return int(str(text).strip(), 0)
    except (TypeError, ValueError):
        return default


def _instances(blob: str | None) -> list[tuple[int, int, int]]:
    """``clipInstances`` : ``0x`` puis des triplets de 8 chiffres
    hexadécimaux — position et longueur en ticks, code du clip."""
    texte = str(blob or "").strip()
    if texte[:2].lower() == "0x":
        texte = texte[2:]
    out = []
    for i in range(0, len(texte) - 23, 24):
        try:
            out.append((int(texte[i:i + 8], 16), int(texte[i + 8:i + 16], 16),
                        int(texte[i + 16:i + 24], 16)))
        except ValueError:
            break
    return out


def drum_pitch(name: str, rel: str, used: set[int]) -> int:
    """La note General MIDI d'un son de batterie, d'après son nom (ou celui
    de son fichier) ; une note déjà prise passe à la suivante libre."""
    role = classify_drum(name or "", {}, {})
    if role == "Other" and rel:
        role = classify_drum(Path(rel).name, {}, {})
    pitch = midifile.GM_DRUMS.get(role, midifile.GM_DRUMS["Other"])
    if pitch not in used:
        return pitch
    for candidate in list(range(35, 82)) + list(range(82, 128)):
        if candidate not in used:
            return candidate
    return pitch


def _instrument_key(el: ET.Element) -> tuple:
    kind = _INSTRUMENT_TAGS.get(el.tag, "")
    if kind in ("synth", "kit", "audio"):
        nom = (dxml.get(el, "presetName") or dxml.get(el, "name") or "")
        return (kind, nom.upper(), (dxml.get(el, "presetFolder") or "").upper())
    if kind == "midi":
        return (kind, _int(dxml.get(el, "channel")),
                _int(dxml.get(el, "suffix"), -1))
    return (kind, _int(dxml.get(el, "channel")))


def _clip_key(clip: Clip, el: ET.Element) -> tuple:
    kind = {"sound": "synth"}.get(clip.kind, clip.kind)
    if kind in ("synth", "kit", "audio"):
        nom = clip.preset_name or dxml.get(el, "trackName") or ""
        return (kind, nom.upper(), (clip.preset_folder or "").upper())
    if kind == "midi":
        return (kind, clip.channel, clip.suffix)
    return (kind, clip.channel)


def _track_name(el: ET.Element, kind: str) -> str:
    if kind == "midi":
        return tr("MIDI %d") % (_int(dxml.get(el, "channel")) + 1)
    if kind == "cv":
        return tr("CV %d") % (_int(dxml.get(el, "channel")) + 1)
    return (dxml.get(el, "presetName") or dxml.get(el, "name")
            or tr("Piste"))


def _drum_inputs(el: ET.Element) -> tuple[int | None, dict[int, int]]:
    """Ce qu'écoutent les sons d'un kit sur la machine : le canal qui leur est
    commun et la note apprise de chaque rangée sur ce canal (``<midiInput
    channel note />``).

    ``(None, {})`` si les sons n'écoutent rien, s'ils écoutent plusieurs
    canaux, ou si le kit entier écoute un canal (``MIDIInput``) : il passe
    alors avant ses sons (``Kit::offerReceivedNote``), rangée par rangée
    depuis sa note de base, et les notes General MIDI ne le jouent plus.
    """
    if dxml.get_child(el, "MIDIInput") is not None:
        return None, {}
    sources = dxml.get_child(el, "soundSources")
    sons = [s for s in (list(sources) if sources is not None else [])
            if s.tag == "sound"]
    appris: dict[int, tuple[int, int]] = {}
    for index, son in enumerate(sons):
        entree = dxml.get_child(son, "midiInput")
        if entree is not None:
            appris[index] = (_int(dxml.get(entree, "channel"), -1),
                             _int(dxml.get(entree, "note"), -1))
    canaux = {c for c, _n in appris.values() if 0 <= c <= 15}
    if len(canaux) != 1:
        return None, {}
    canal = canaux.pop()
    notes: dict[int, int] = {}
    for index, (c, n) in appris.items():
        if c == canal and 0 <= n <= 127 and n not in notes.values():
            notes[index] = n
    return canal, notes


def listened_channel(el: ET.Element, kind: str) -> int | None:
    """Le canal (0–15) qu'un instrument du morceau écoute sur la machine :
    ``inputMidiChannel`` pour un synthé, le canal commun de ses sons pour un
    kit (:func:`_drum_inputs`) ; ``None`` sinon — une zone MPE, une piste
    MIDI, CV ou audio n'écoutent pas de canal (:mod:`.dawlive`)."""
    if kind == "synth":
        canal = _int(dxml.get(el, "inputMidiChannel"), -1)
        return canal if 0 <= canal <= 15 else None
    if kind == "kit":
        return _drum_inputs(el)[0]
    return None


def _drum_map(el: ET.Element) -> dict[int, tuple[int, int, str]]:
    """Rangée du kit → ``(hauteur, indice, nom)``.

    Une note apprise sur la machine (:func:`_drum_inputs`) l'emporte sur la
    note General MIDI : le DAW joue alors chaque son là où le Deluge
    l'écoute, et les autres sons évitent ces notes.
    """
    sources = dxml.get_child(el, "soundSources")
    out: dict[int, tuple[int, int, str]] = {}
    if sources is None:
        return out
    appris = _drum_inputs(el)[1]
    used: set[int] = set(appris.values())
    for index, sound in enumerate(s for s in sources if s.tag == "sound"):
        nom = dxml.get(sound, "name") or ""
        rel = ""
        osc = dxml.get_child(sound, "osc1")
        if osc is not None:
            rel = dxml.get(osc, "fileName") or ""
        if index in appris:
            pitch = appris[index]
        else:
            pitch = drum_pitch(nom, rel, used)
            used.add(pitch)
        out[index] = (pitch, index, nom or Path(rel).stem or
                      tr("Rangée %d") % (index + 1))
    return out


def _clip_notes(clip: Clip, per_beat: float,
                drums: dict[int, tuple[int, int, str]] | None
                ) -> list[DawNote]:
    notes: list[DawNote] = []
    for row in clip.note_rows:
        if drums is not None:
            if row.drum_index is None or row.drum_index not in drums:
                continue
            pitch = drums[row.drum_index][0]
        else:
            pitch = int(row.y)
        if not 0 <= pitch <= 127:
            continue
        for n in row.notes:
            notes.append(DawNote(pitch, n.pos / per_beat,
                                 max(1, n.length) / per_beat,
                                 max(1, min(127, int(n.velocity)))))
    notes.sort(key=lambda x: (x.start, x.pitch))
    return notes


def from_deluge(path: Path, name: str = "") -> DawSong:
    """Lit un morceau du Deluge (``SONGS/*.XML``) dans le modèle commun.

    Lève :class:`ValueError` si le fichier n'est pas un morceau.
    """
    doc = dxml.load(Path(path))
    root = doc.root
    if root is None or root.tag != "song":
        raise ValueError(tr("ce fichier n'est pas un morceau du Deluge"))
    magnitude = _int(dxml.get(root, "inputTickMagnitude"), 1)
    per_beat = ticks_per_bar(magnitude) / 4.0
    from .model import Song
    song = Song.from_xml(root, doc.dialect)
    daw = DawSong(name=name or Path(path).stem,
                  bpm=float(song.tempo_bpm or 120.0),
                  root=int(song.root_note or 0) % 12,
                  mode_notes=tuple(sorted({int(m) % 12
                                           for m in song.mode_notes}))
                  or (0, 2, 4, 5, 7, 9, 11))

    # Les pistes, dans l'ordre des instruments du morceau.
    holder = _first(root, ("instruments", "tracks"))
    by_key: dict[tuple, DawTrack] = {}
    instances: dict[int, list[tuple[int, int, int]]] = {}
    for el in list(holder) if holder is not None else []:
        kind = _INSTRUMENT_TAGS.get(el.tag)
        if kind is None:
            continue
        track = DawTrack(name=_track_name(el, kind), kind=kind,
                         channel=9 if kind == "kit" else 0, instrument=el)
        if kind == "midi":
            track.channel = max(0, min(15, _int(dxml.get(el, "channel"))))
        if kind == "kit":
            track.drums = {p: (i, n) for p, i, n in _drum_map(el).values()}
        # Un instrument qui écoute un canal sur la machine (une copie
        # « DAW », :mod:`.dawlive`) sort sur ce canal : le DAW le joue.
        track.listens = listened_channel(el, kind)
        if track.listens is not None:
            track.channel = track.listens
        key = _instrument_key(el)
        if key in by_key:
            continue
        by_key[key] = track
        daw.tracks.append(track)
        instances[id(track)] = _instances(dxml.get(el, "clipInstances"))

    # Les clips : session, puis arrangement seul.
    codes: dict[int, tuple[DawTrack, int]] = {}
    sections: dict[int, int] = {}
    for holder_names, base in ((("sessionClips", "tracks"), 0),
                               (("arrangementOnlyClips",
                                 "arrangementOnlyTracks"), _ARRANGEMENT_ONLY)):
        holder = _first(root, holder_names)
        rang = 0
        for el in list(holder) if holder is not None else []:
            if el.tag not in _CLIP_TAGS:
                continue
            code = base | rang
            rang += 1
            try:
                clip = Clip.from_xml(el, doc.dialect)
            except (ValueError, TypeError, AttributeError):
                continue
            track = by_key.get(_clip_key(clip, el))
            if track is None:
                daw.clip_order.append(None)
                continue
            drums = None
            if track.kind == "kit":
                drums = {i: (p, i, n) for p, (i, n) in track.drums.items()}
            daw_clip = DawClip(
                name=clip.name or track.name,
                length=max(1, int(clip.length)) / per_beat,
                notes=_clip_notes(clip, per_beat, drums),
                source=(track.instrument, el))
            track.clips.append(daw_clip)
            index = len(track.clips) - 1
            codes[code] = (track, index)
            daw.clip_order.append((daw.tracks.index(track), index))
            if base == 0:
                sections.setdefault(clip.section, 0)
                sections[clip.section] = max(sections[clip.section],
                                             int(clip.length))
                track.scenes.setdefault(clip.section, index)

    # Les scènes : une par section employée, dans l'ordre des sections.
    ordre = sorted(sections)
    scene_of = {s: i for i, s in enumerate(ordre)}
    for track in daw.tracks:
        track.scenes = {scene_of[s]: c for s, c in track.scenes.items()}
    repeats = _section_repeats(root)
    daw.scenes = [DawScene(tr("Section %d") % (s + 1), sections[s] / per_beat)
                  for s in ordre]

    # L'arrangement : celui du morceau, ou l'enchaînement des sections.
    for track in daw.tracks:
        for pos, longueur, code in instances.get(id(track), []):
            cible = codes.get(code)
            if cible is None or cible[0] is not track or longueur <= 0:
                continue
            track.placements.append(Placement(cible[1], pos / per_beat,
                                              longueur / per_beat))
    daw.arranged = any(t.placements for t in daw.tracks)
    if not daw.arranged:
        debut = 0.0
        for i, s in enumerate(ordre):
            duree = sections[s] / per_beat * max(1, repeats.get(s, 0))
            daw.markers.append((debut, daw.scenes[i].name))
            for track in daw.tracks:
                if i in track.scenes:
                    track.placements.append(
                        Placement(track.scenes[i], debut, duree))
            debut += duree
    for track in daw.tracks:
        track.placements.sort(key=lambda p: p.start)
    return daw


def _section_repeats(root: ET.Element) -> dict[int, int]:
    holder = dxml.get_child(root, "sections")
    out: dict[int, int] = {}
    if holder is None:
        return out
    for el in dxml.iter_children(holder, "section"):
        out[_int(dxml.get(el, "id"))] = max(0, _int(dxml.get(el,
                                                             "numRepeats")))
    return out


def clip_sound(track: DawTrack, clip: DawClip):
    """Le son d'un clip venu du Deluge, comme la machine le joue :
    l'instrument du morceau et les paramètres du clip réunis — un
    :class:`~delugeapp.core.model.Sound` pour un synthé, un
    :class:`~delugeapp.core.model.Kit` pour un kit, ``None`` sinon."""
    if not isinstance(clip.source, tuple):
        return None
    instrument, clip_el = clip.source
    if track.kind == "kit":
        kit_el = copy.deepcopy(instrument)
        params = dxml.get_child(clip_el, "kitParams")
        if params is not None:
            p = copy.deepcopy(params)
            p.tag = "defaultParams"
            kit_el.append(p)
        sources = dxml.get_child(kit_el, "soundSources")
        sons = [s for s in sources if s.tag == "sound"] \
            if sources is not None else []
        rows = dxml.get_child(clip_el, "noteRows")
        for row in list(rows) if rows is not None else []:
            indice = _int(dxml.get(row, "drumIndex"), -1)
            p = dxml.get_child(row, "soundParams")
            if 0 <= indice < len(sons) and p is not None:
                p = copy.deepcopy(p)
                p.tag = "defaultParams"
                sons[indice].append(p)
        return Kit.from_xml(kit_el)
    if track.kind == "synth":
        son_el = copy.deepcopy(instrument)
        p = dxml.get_child(clip_el, "soundParams")
        if p is not None:
            p = copy.deepcopy(p)
            p.tag = "defaultParams"
            son_el.append(p)
        son = Sound.from_xml(son_el)
        son.name = track.name
        return son
    return None


# --------------------------------------------------------------------------- #
# Pistes audio : chaque piste rendue comme la machine la joue
# --------------------------------------------------------------------------- #

def _sounding_tracks(song: DawSong) -> list[DawTrack]:
    """Les pistes que la machine fait sonner : synthés et kits joués."""
    return [t for t in song.tracks if t.kind in ("synth", "kit")
            and t.has_notes and t.placements]


def sidechain_hits(song: DawSong) -> list[tuple[float, int]]:
    """Les coups de sidechain du morceau entier, ``(secondes, force)`` :
    chaque note d'un son qui en envoie — un synthé, ou la rangée d'un kit,
    souvent la grosse caisse. Une piste rendue seule en a besoin : ce qui la
    fait pomper joue sur une autre."""
    out: list[tuple[float, int]] = []
    for track in _sounding_tracks(song):
        for ci, clip in enumerate(track.clips):
            son = clip_sound(track, clip)
            if son is None:
                continue
            for _debut, n in _expanded(track, ci):
                if track.kind == "kit":
                    rang = track.drums.get(n.pitch)
                    if rang is None or rang[0] >= len(son.rows):
                        continue
                    force = son.rows[rang[0]].sound.side_chain_send
                else:
                    force = son.side_chain_send
                if force:
                    out.append((song.seconds(n.start), int(force)))
    out.sort()
    return out


def _clip_audio(song: DawSong, track: DawTrack, clip: DawClip,
                notes: list[tuple[float, DawNote]], sd, should_stop=None,
                hits=None):
    """Le rendu de ``notes`` (début absolu, note) jouées par le son de
    ``clip``, posé au début du morceau ; ``None`` si rien ne sonne.
    ``hits`` : les coups de sidechain du morceau (:func:`sidechain_hits`) ;
    sans eux, ceux du clip seul."""
    import numpy as np

    from . import render
    from .accomp import NoteEvent

    son = clip_sound(track, clip)
    if not notes or son is None:
        return None
    if track.kind == "kit":
        parts: dict[str, list] = {}
        sons: dict[str, object] = {}
        for _debut, n in notes:
            rang = track.drums.get(n.pitch)
            if rang is None or rang[0] >= len(son.rows):
                continue
            cle = "%02d" % rang[0]
            sons[cle] = son.rows[rang[0]].sound
            parts.setdefault(cle, []).append(NoteEvent(
                n.start * 4.0, n.length * 4.0, 60,
                max(1, round(n.velocity / 127.0 * 100))))
        gain = render.kit_gain(son)
    else:
        parts = {"son": [NoteEvent(n.start * 4.0, n.length * 4.0, n.pitch,
                                   max(1, round(n.velocity / 127.0 * 100)))
                         for _d, n in notes]}
        sons = {"son": son}
        gain = 1.0
    if not parts:
        return None
    audio = render.render_parts(parts, sons, bpm=song.bpm, sr=44100, sd=sd,
                                normalize=False, should_stop=should_stop,
                                sidechain_hits=hits)
    if audio is None:
        return None
    return np.asarray(audio, dtype=np.float64) * gain


def _mix_into(total, audio):
    """``total + audio``, le plus court complété de silence."""
    import numpy as np

    if audio is None:
        return total
    if total is None:
        return audio
    if audio.shape[0] > total.shape[0]:
        total = np.vstack([total, np.zeros(
            (audio.shape[0] - total.shape[0], total.shape[1]))])
    total[:audio.shape[0]] += audio
    return total


def _track_audio(song: DawSong, track: DawTrack, sd, should_stop=None,
                 hits=None):
    """Toute une piste sur l'arrangement, chaque clip avec ses réglages."""
    total = None
    for ci, clip in enumerate(track.clips):
        if should_stop is not None and should_stop():
            break
        total = _mix_into(total, _clip_audio(song, track, clip,
                                             _expanded(track, ci), sd,
                                             should_stop, hits))
    return total


def _contained(audio):
    """Sous 0 dBFS : la machine écrêterait, le rendu garde sa forme."""
    import numpy as np

    crete = float(np.max(np.abs(audio))) if audio.size else 0.0
    return audio * (0.999 / crete) if crete > 0.999 else audio


def render_clip(song: DawSong, track_index: int, clip_index: int, sd,
                should_stop=None):
    """Un clip joué une fois, sur toute sa longueur de boucle, comme la
    machine le joue (stéréo, 44,1 kHz) ; ``None`` s'il ne sonne pas — clip
    vide, piste MIDI, CV ou audio."""
    import numpy as np

    track = song.tracks[track_index]
    if track.kind not in ("synth", "kit"):
        return None
    clip = track.clips[clip_index]
    notes = [(n.start, n) for n in clip.notes if n.start < clip.length]
    audio = _clip_audio(song, track, clip, notes, sd, should_stop)
    if audio is None:
        return None
    # La boucle entière : le silence de fin compte autant que les notes.
    trames = int(round(song.seconds(clip.length) * 44100))
    if audio.shape[0] < trames:
        audio = np.vstack([audio, np.zeros((trames - audio.shape[0],
                                            audio.shape[1]))])
    return _contained(audio).astype(np.float32)


def render_mix(song: DawSong, sd, progress=None, should_stop=None):
    """Le morceau entier, toutes pistes mêlées, sur son arrangement : la
    somme des pistes de :func:`render_stems`, sans fichier écrit.

    :param progress: ``progress(fait, total, nom)``.
    """
    import numpy as np

    cibles = _sounding_tracks(song)
    coups = sidechain_hits(song)
    total = None
    for numero, track in enumerate(cibles):
        if should_stop is not None and should_stop():
            return None
        if progress is not None:
            progress(numero, len(cibles), track.name)
        total = _mix_into(total, _track_audio(song, track, sd, should_stop,
                                              coups))
    if total is None or (should_stop is not None and should_stop()):
        return None
    return _contained(total).astype(np.float32)


def render_stems(song: DawSong, sd, folder: Path, progress=None,
                 should_stop=None) -> list[Path]:
    """Rend, dans ``folder``, une piste audio par piste de synthé ou de kit
    (WAV 24 bits, 44,1 kHz, stéréo), **toutes calées au début du morceau** :
    posées à zéro dans le DAW, elles tombent juste. Le calcul est celui de
    l'écoute (:mod:`.render`), vérifié contre la machine ; chaque clip y
    garde ses propres réglages. Les pistes MIDI et CV, qui ne sonnent pas
    dans le Deluge, n'en ont pas.

    :param progress: ``progress(fait, total, nom)``.
    :param should_stop: consulté entre deux pistes et deux clips ; vrai, le
        rendu s'arrête et rend ce qui est déjà écrit.
    Renseigne ``track.audio`` pour chaque piste rendue.
    """
    import numpy as np

    from . import wav

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    cibles = _sounding_tracks(song)
    coups = sidechain_hits(song)
    faits: list[Path] = []
    for numero, track in enumerate(cibles):
        if should_stop is not None and should_stop():
            break
        if progress is not None:
            progress(numero, len(cibles), track.name)
        total = _track_audio(song, track, sd, should_stop, coups)
        if total is None:
            continue
        cible = folder / ("%02d %s.wav" % (song.tracks.index(track) + 1,
                                            safe_file_name(track.name)))
        wav.write(cible, _contained(total).astype(np.float32), 44100,
                  bit_depth=24)
        track.audio = cible
        faits.append(cible)
    if progress is not None:
        progress(len(cibles), len(cibles), "")
    return faits


_EXPORT_FOLDER = re.compile(r"^TRACKS(?:-(\d{2,}))?$", re.I)


def machine_stems(sd, song_name: str) -> list[Path]:
    """Les WAV du dernier export de pistes **fait par la machine** pour ce
    morceau, s'il y en a un.

    Le firmware 1.3 les range dans ``SAMPLES/EXPORTS/<morceau>/TRACKS``,
    puis ``TRACKS-00``, ``TRACKS-01``… à chaque nouvel export
    (``StemExport::getUnusedStemRecordingFolderPath`` ; le troisième export
    de l'utilisateur est arrivé dans ``CLIPS-00``), en jouant l'arrangement
    depuis le début : posés à zéro dans le DAW, ils tombent juste. C'est le
    rendu le plus fidèle qui soit — celui du Deluge.
    """
    if sd is None or not song_name:
        return []
    base = Path(sd.abs("SAMPLES/EXPORTS")) / song_name
    try:
        dossiers = [d for d in base.iterdir()
                    if d.is_dir() and _EXPORT_FOLDER.match(d.name)]
    except OSError:
        return []
    if not dossiers:
        return []

    def rang(d: Path) -> int:
        n = _EXPORT_FOLDER.match(d.name).group(1)
        return int(n) if n else -1

    dernier = max(dossiers, key=rang)
    return sorted(p for p in dernier.iterdir()
                  if p.is_file() and p.suffix.lower() == ".wav")


# --------------------------------------------------------------------------- #
# Écritures communes
# --------------------------------------------------------------------------- #

def safe_file_name(name: str, fallback: str = "piste") -> str:
    """Un nom de fichier sûr sous Windows comme ailleurs."""
    decomposed = unicodedata.normalize("NFKD", str(name or ""))
    texte = "".join(c for c in decomposed if not unicodedata.combining(c))
    texte = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", texte)
    texte = re.sub(r"\s+", " ", texte).strip(" .")
    return texte[:60] or fallback


def _expanded(track: DawTrack, clip_index: int | None = None
              ) -> list[tuple[float, DawNote]]:
    """Les notes de l'arrangement, boucles déroulées : ``(début absolu,
    note)``. Une note coupée par la fin de son emplacement est raccourcie."""
    out = []
    for p in track.placements:
        if clip_index is not None and p.clip != clip_index:
            continue
        clip = track.clips[p.clip]
        if clip.length <= 0 or not clip.notes:
            continue
        tours = int(math.ceil(p.length / clip.length - 1e-9))
        fin = p.start + p.length
        for k in range(tours):
            base = p.start + k * clip.length
            for note in clip.notes:
                if note.start >= clip.length:
                    continue
                debut = base + note.start
                if debut >= fin - 1e-9:
                    continue
                longueur = min(note.length, fin - debut)
                out.append((debut, DawNote(note.pitch, debut, longueur,
                                           note.velocity)))
    out.sort(key=lambda x: (x[0], x[1].pitch))
    return out


def write_midi(song: DawSong, path: Path, ppq: int = 960) -> int:
    """Le morceau en MIDI de type 1 : tempo, métrique, repères de section, une
    piste par piste du morceau (une batterie sur le canal 10). Rend le nombre
    de pistes écrites."""
    pistes = []
    for track in song.tracks:
        if not track.has_notes or track.kind == "audio":
            continue
        mt = midifile.MidiTrack(name=track.name[:40],
                                channel=max(0, min(15, track.channel)))
        for debut, note in _expanded(track):
            mt.add(int(round(debut * ppq)), note.pitch, note.velocity,
                   max(1, int(round(note.length * ppq))))
        pistes.append(mt)
    if not pistes:
        return 0
    reperes = [(int(round(t * ppq)), nom) for t, nom in song.markers]
    midifile.write_midi(Path(path), pistes, bpm=song.bpm, ppq=ppq,
                        markers=reperes)
    return len(pistes)


#: Couleurs des pistes dans les projets (les teintes des pads du Deluge).
_COLOURS = ("#ff5a00", "#00a0ff", "#b400ff", "#00dc78", "#ff0078",
            "#ffc800", "#00ffff", "#78ff00", "#ff7800", "#7800ff")


def _colour(index: int) -> str:
    return _COLOURS[index % len(_COLOURS)]


def _fmt(x: float) -> str:
    return "%.6f" % float(x)


# --------------------------------------------------------------------------- #
# DAWproject : Bitwig, Studio One, Cubase
# --------------------------------------------------------------------------- #

class _Ids:
    def __init__(self) -> None:
        self.n = 0

    def __call__(self) -> str:
        self.n += 1
        return "id%d" % (self.n - 1)


def _channel(parent: ET.Element, ids: _Ids, role: str, destination: str | None
             ) -> ET.Element:
    ch = ET.SubElement(parent, "Channel")
    ch.set("audioChannels", "2")
    if destination:
        ch.set("destination", destination)
    ch.set("role", role)
    ch.set("solo", "false")
    ch.set("id", ids())
    # L'ordre est celui du schéma : Devices, Mute, Pan, Sends, Volume.
    ET.SubElement(ch, "Mute", {"value": "false", "id": ids(), "name": "Mute"})
    ET.SubElement(ch, "Pan", {"max": "1.000000", "min": "0.000000",
                              "unit": "normalized", "value": "0.500000",
                              "id": ids(), "name": "Pan"})
    ET.SubElement(ch, "Volume", {"max": "2.000000", "min": "0.000000",
                                 "unit": "linear", "value": "1.000000",
                                 "id": ids(), "name": "Volume"})
    return ch


def _notes_element(parent: ET.Element, ids: _Ids, notes: list[DawNote],
                   channel: int) -> None:
    el = ET.SubElement(parent, "Notes", {"id": ids()})
    for n in notes:
        ET.SubElement(el, "Note", {
            "time": _fmt(n.start), "duration": _fmt(n.length),
            "channel": str(channel), "key": str(n.pitch),
            "vel": _fmt(n.velocity / 127.0), "rel": "0.500000"})


def _audio_clip(parent: ET.Element, ids: _Ids, song: DawSong, rel: str,
                seconds: float, sample_rate: int, beats: float) -> None:
    """Un clip audio comme Bitwig l'écrit : un clip d'arrangement qui
    contient un événement audio, calé sur le tempo par deux points."""
    clips = ET.SubElement(parent, "Clips", {"id": ids()})
    clip = ET.SubElement(clips, "Clip", {
        "time": "0.0", "duration": _fmt(beats), "playStart": "0.0",
        "loopStart": "0.0", "loopEnd": _fmt(beats), "fadeTimeUnit": "beats",
        "fadeInTime": "0.0", "fadeOutTime": "0.0"})
    inner = ET.SubElement(clip, "Clips", {"id": ids()})
    event = ET.SubElement(inner, "Clip", {
        "time": "0.0", "duration": _fmt(beats), "contentTimeUnit": "beats",
        "playStart": "0.0", "fadeTimeUnit": "beats", "fadeInTime": "0.0",
        "fadeOutTime": "0.0"})
    warps = ET.SubElement(event, "Warps", {"contentTimeUnit": "seconds",
                                           "timeUnit": "beats", "id": ids()})
    audio = ET.SubElement(warps, "Audio", {
        "algorithm": "stretch", "channels": "2", "duration": _fmt(seconds),
        "sampleRate": str(int(sample_rate)), "id": ids()})
    ET.SubElement(audio, "File", {"path": rel})
    ET.SubElement(warps, "Warp", {"time": "0.0", "contentTime": "0.0"})
    ET.SubElement(warps, "Warp", {"time": _fmt(beats),
                                  "contentTime": _fmt(seconds)})


def _audio_info(path: Path) -> tuple[float, int]:
    from . import wav
    info = wav.probe(Path(path))
    return float(info.duration or 0.0), int(info.sample_rate or 44100)


def dawproject_xml(song: DawSong, audio: dict[int, str] | None = None
                   ) -> tuple[bytes, bytes]:
    """``(project.xml, metadata.xml)`` d'un DAWproject 1.0.

    :param audio: indice de piste → chemin de sa piste audio **dans
        l'archive** (``audio/…``) ; la durée se lit dans le fichier, posé à
        côté sous ce nom relatif (voir :func:`write_dawproject`).
    """
    from .. import __version__
    ids = _Ids()
    project = ET.Element("Project", {"version": "1.0"})
    ET.SubElement(project, "Application", {"name": "Noctiluca",
                                           "version": str(__version__)})
    transport = ET.SubElement(project, "Transport")
    ET.SubElement(transport, "Tempo", {
        "max": "999.000000", "min": "20.000000", "unit": "bpm",
        "value": _fmt(song.bpm), "id": ids(), "name": "Tempo"})
    ET.SubElement(transport, "TimeSignature", {
        "denominator": str(song.denominator),
        "numerator": str(song.numerator), "id": ids()})
    structure = ET.SubElement(project, "Structure")
    master_track = ET.Element("Track", {"contentType": untranslated(
                                            "audio notes"),
                                        "loaded": "true", "id": "", "name":
                                        "Master"})
    # Les pistes d'abord ; le maître est référencé par toutes.
    master_id_track = ids()
    master_channel_id = ids()
    track_ids: list[tuple[DawTrack, str, str | None]] = []
    for index, track in enumerate(song.tracks):
        tid_notes = None
        if track.has_notes and track.kind != "audio":
            tid_notes = ids()
            el = ET.SubElement(structure, "Track", {
                "contentType": "notes", "loaded": "true", "id": tid_notes,
                "name": track.name, "color": _colour(index)})
            _channel(el, ids, "regular", master_channel_id)
        tid_audio = None
        if audio and index in audio:
            tid_audio = ids()
            el = ET.SubElement(structure, "Track", {
                "contentType": "audio", "loaded": "true", "id": tid_audio,
                "name": tr("%s (audio)") % track.name,
                "color": _colour(index)})
            _channel(el, ids, "regular", master_channel_id)
        track_ids.append((track, tid_notes, tid_audio))
    master_track.set("id", master_id_track)
    structure.append(master_track)
    master = ET.SubElement(master_track, "Channel", {
        "audioChannels": "2", "role": "master", "solo": "false",
        "id": master_channel_id})
    ET.SubElement(master, "Mute", {"value": "false", "id": ids(),
                                   "name": "Mute"})
    ET.SubElement(master, "Pan", {"max": "1.000000", "min": "0.000000",
                                  "unit": "normalized", "value": "0.500000",
                                  "id": ids(), "name": "Pan"})
    ET.SubElement(master, "Volume", {"max": "2.000000", "min": "0.000000",
                                     "unit": "linear", "value": "1.000000",
                                     "id": ids(), "name": "Volume"})

    arrangement = ET.SubElement(project, "Arrangement", {"id": ids()})
    lanes = ET.SubElement(arrangement, "Lanes", {"timeUnit": "beats",
                                                "id": ids()})
    for index, (track, tid_notes, tid_audio) in enumerate(track_ids):
        if tid_notes:
            lane = ET.SubElement(lanes, "Lanes", {"track": tid_notes,
                                                  "id": ids()})
            clips = ET.SubElement(lane, "Clips", {"id": ids()})
            for p in track.placements:
                clip = track.clips[p.clip]
                el = ET.SubElement(clips, "Clip", {
                    "time": _fmt(p.start), "duration": _fmt(p.length),
                    "playStart": "0.0", "loopStart": "0.0",
                    "loopEnd": _fmt(clip.length), "name": clip.name})
                _notes_element(el, ids, [n for n in clip.notes
                                         if n.start < clip.length],
                               track.channel)
        if tid_audio:
            lane = ET.SubElement(lanes, "Lanes", {"track": tid_audio,
                                                  "id": ids()})
            rel = audio[index]
            fichier = track.audio
            secondes, taux = _audio_info(fichier) if fichier else (0.0, 44100)
            _audio_clip(lane, ids, song, rel, secondes, taux,
                        secondes / song.seconds_per_beat)
    if song.markers:
        reperes = ET.SubElement(arrangement, "Markers", {"id": ids()})
        for t, nom in song.markers:
            ET.SubElement(reperes, "Marker", {"time": _fmt(t), "name": nom})

    scenes = ET.SubElement(project, "Scenes")
    for s, scene in enumerate(song.scenes):
        el = ET.SubElement(scenes, "Scene", {"id": ids(), "name": scene.name})
        contenu = ET.SubElement(el, "Lanes", {"timeUnit": "beats",
                                              "id": ids()})
        for track, tid_notes, _tid_audio in track_ids:
            if not tid_notes or s not in track.scenes:
                continue
            clip = track.clips[track.scenes[s]]
            slot = ET.SubElement(contenu, "ClipSlot", {
                "track": tid_notes, "hasStop": "true", "id": ids()})
            c = ET.SubElement(slot, "Clip", {
                "time": "0.0", "duration": _fmt(clip.length),
                "playStart": "0.0", "loopStart": "0.0",
                "loopEnd": _fmt(clip.length), "name": clip.name})
            _notes_element(c, ids, [n for n in clip.notes
                                    if n.start < clip.length], track.channel)

    meta = ET.Element("MetaData")
    ET.SubElement(meta, "Title").text = song.name
    ET.SubElement(meta, "Comment").text = tr(
        "Exporté du Deluge par Noctiluca")
    return _xml_bytes(project), _xml_bytes(meta)


def _xml_bytes(el: ET.Element) -> bytes:
    ET.indent(el, space="  ")
    return (b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            + ET.tostring(el, encoding="utf-8"))


def write_dawproject(song: DawSong, path: Path) -> Path:
    """Un ``.dawproject`` (ZIP : ``project.xml``, ``metadata.xml``, et les
    pistes audio rendues dans ``audio/``)."""
    audio: dict[int, str] = {}
    for index, track in enumerate(song.tracks):
        if track.audio and Path(track.audio).exists():
            audio[index] = "audio/%02d %s.wav" % (index + 1,
                                                  safe_file_name(track.name))
    projet, meta = dawproject_xml(song, audio)
    cible = Path(path)
    cible.parent.mkdir(parents=True, exist_ok=True)
    tmp = cible.with_suffix(cible.suffix + ".part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("project.xml", projet)
        z.writestr("metadata.xml", meta)
        for index, rel in audio.items():
            z.write(song.tracks[index].audio, rel,
                    compress_type=zipfile.ZIP_STORED)
    tmp.replace(cible)
    return cible


# --------------------------------------------------------------------------- #
# Reaper
# --------------------------------------------------------------------------- #

_RPP_PPQ = 960


def _rpp_text(text: str) -> str:
    return '"%s"' % str(text).replace('"', "'")


def _rpp_guid() -> str:
    return "{%s}" % str(uuid.uuid4()).upper()


def _rpp_midi(clip: DawClip, channel: int) -> list[str]:
    """La source MIDI d'un clip : une boucle de sa longueur, en événements
    relatifs à 960 impulsions par noire ; le dernier marque la fin."""
    evenements = []
    for n in clip.notes:
        if n.start >= clip.length:
            continue
        debut = int(round(n.start * _RPP_PPQ))
        fin = min(int(round((n.start + n.length) * _RPP_PPQ)),
                  int(round(clip.length * _RPP_PPQ)))
        evenements.append((debut, 1, 0x90 | channel, n.pitch, n.velocity))
        evenements.append((max(debut + 1, fin), 0, 0x80 | channel, n.pitch, 0))
    evenements.sort(key=lambda e: (e[0], e[1]))
    lignes = ["HASDATA 1 %d QN" % _RPP_PPQ]
    avant = 0
    for t, _k, status, d1, d2 in evenements:
        lignes.append("E %d %02x %02x %02x" % (t - avant, status, d1, d2))
        avant = t
    fin = int(round(clip.length * _RPP_PPQ))
    lignes.append("E %d %02x 7b 00" % (max(0, fin - avant), 0xB0 | channel))
    return lignes


def rpp_text(song: DawSong, audio: dict[int, str] | None = None) -> str:
    """Le projet Reaper : une piste par piste du morceau, ses clips en objets
    MIDI qui bouclent, les pistes audio rendues, les repères de section."""
    spb = song.seconds_per_beat
    lignes = ['<REAPER_PROJECT 0.1 "7.0" %d' % int(time.time()),
              "  TEMPO %s %d %d" % (_fmt(song.bpm), song.numerator,
                                    song.denominator),
              "  SAMPLERATE 44100 0 0"]
    for i, (t, nom) in enumerate(song.markers, 1):
        lignes.append("  MARKER %d %s %s 0" % (i, _fmt(t * spb),
                                                _rpp_text(nom)))
    for index, track in enumerate(song.tracks):
        if track.has_notes and track.kind != "audio":
            lignes += ["  <TRACK %s" % _rpp_guid(),
                       "    NAME %s" % _rpp_text(track.name)]
            for p in track.placements:
                clip = track.clips[p.clip]
                lignes += ["    <ITEM",
                           "      POSITION %s" % _fmt(p.start * spb),
                           "      LENGTH %s" % _fmt(p.length * spb),
                           "      LOOP 1",
                           "      NAME %s" % _rpp_text(clip.name),
                           "      <SOURCE MIDI"]
                lignes += ["        " + x for x in _rpp_midi(clip,
                                                             track.channel)]
                lignes += ["      >", "    >"]
            lignes.append("  >")
        if audio and index in audio:
            secondes, _taux = _audio_info(track.audio)
            lignes += ["  <TRACK %s" % _rpp_guid(),
                       "    NAME %s" % _rpp_text(tr("%s (audio)")
                                                 % track.name),
                       "    <ITEM",
                       "      POSITION 0",
                       "      LENGTH %s" % _fmt(secondes),
                       "      NAME %s" % _rpp_text(track.name),
                       "      <SOURCE WAVE",
                       "        FILE %s" % _rpp_text(audio[index]),
                       "      >",
                       "    >",
                       "  >"]
    lignes.append(">")
    return "\n".join(lignes) + "\n"


def write_rpp(song: DawSong, path: Path,
              audio: dict[int, str] | None = None) -> Path:
    """Un ``.rpp``. ``audio`` donne, par piste, le chemin de sa piste audio
    relatif au projet."""
    cible = Path(path)
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.write_text(rpp_text(song, audio), encoding="utf-8")
    return cible


# --------------------------------------------------------------------------- #
# Le dossier pour le DAW
# --------------------------------------------------------------------------- #

#: Les formats proposés, dans l'ordre de l'interface : clé, libellé, DAW.
FORMATS: tuple[tuple[str, str, str], ...] = (
    ("midi", N_("MIDI et pistes audio"),
     N_("tous les DAW : FL Studio, Ableton Live, Logic, Pro Tools…")),
    ("als", N_("Ableton Live"), N_("un set .als prêt à ouvrir")),
    ("dawproject", N_("DAWproject"),
     N_("Bitwig Studio, Studio One, Cubase")),
    ("rpp", N_("Reaper"), N_("un projet .rpp prêt à ouvrir")),
)

#: Comment importer le dossier universel, DAW par DAW (lisez-moi).
_HOW_TO = (
    (N_("Ableton Live"),
     N_("ouvrez le set .als s'il est là ; sinon glissez le fichier MIDI dans "
        "l'arrangement (une piste par piste du morceau), puis les pistes "
        "audio. Réglez le tempo indiqué ci-dessus.")),
    (N_("FL Studio"),
     N_("Fichier ▸ Importer ▸ Fichier MIDI, puis glissez les pistes audio "
        "dans la playlist.")),
    (N_("Bitwig Studio, Studio One, Cubase"),
     N_("ouvrez le fichier .dawproject (Fichier ▸ Importer ▸ DAWproject "
        "dans Studio One et Cubase).")),
    (N_("Reaper"), N_("ouvrez le projet .rpp.")),
    (N_("Logic Pro, Pro Tools et les autres"),
     N_("importez le fichier MIDI, puis les pistes audio, toutes posées au "
        "début du morceau.")),
)


def write_readme(song: DawSong, path: Path, files: list[str]) -> Path:
    """Le lisez-moi du dossier : tempo, tonalité, pistes, mode d'emploi."""
    from .theory import note_to_name
    lignes = [song.name, "=" * len(song.name), "",
              tr("Tempo : %s BPM — mesure %d/%d — tonique %s")
              % (("%.2f" % song.bpm).rstrip("0").rstrip("."),
                 song.numerator, song.denominator,
                 note_to_name(song.root, with_octave=False)),
              tr("Durée : %d mesures") % int(math.ceil(
                  song.length / max(1, song.numerator))),
              ""]
    lignes.append(tr("Arrangement du morceau") if song.arranged
                  else tr("Arrangement déduit des sections, dans l'ordre"))
    lignes.append("")
    lignes.append(tr("Pistes :"))
    for i, track in enumerate(song.tracks, 1):
        detail = tr("canal %d") % (track.channel + 1)
        if track.kind == "kit" and track.drums:
            detail += " — " + ", ".join(
                "%s %d" % (nom, p) for p, (_i, nom) in sorted(
                    track.drums.items()))
        lignes.append("  %d. %s (%s)" % (i, track.name, detail))
    lignes += ["", tr("Fichiers :")] + ["  " + f for f in files]
    if any(f.startswith(tr("Pistes du Deluge") + "/") for f in files):
        lignes += ["", tr("Les pistes du Deluge sont celles que la machine a "
                          "exportées elle-même : posez-les toutes au début "
                          "du morceau.")]
    if any(f.endswith(".als") for f in files) \
            and any(t.listens is not None for t in song.tracks):
        lignes += ["", tr("Dans le set Live, les pistes dont le son écoute "
                          "un canal sur le Deluge sortent déjà vers lui, sur "
                          "ce canal (« MIDI To ») : chargez le morceau sur la "
                          "machine, Live le joue.")]
    lignes += ["", tr("Pour l'ouvrir :")]
    for daw, comment in _HOW_TO:
        lignes.append("  — %s : %s" % (tr(daw), tr(comment)))
    cible = Path(path)
    cible.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    return cible


def write_folder(song: DawSong, dest: Path, formats: tuple[str, ...] = (
        "midi", "dawproject", "rpp"), samples: list[Path] | None = None,
        als_template: Path | None = None,
        machine_audio: list[Path] | None = None) -> dict:
    """Écrit le dossier du morceau pour le DAW, dans un dossier **neuf**
    sous ``dest`` (numéroté s'il existe : rien n'est jamais remplacé).

    Les pistes audio déjà rendues (``track.audio``) y sont recopiées dans
    ``Pistes audio/`` ; celles qu'a exportées la machine
    (:func:`machine_stems`), dans ``Pistes du Deluge/`` ; les échantillons
    donnés, dans ``Échantillons/``.
    Rend ``{"folder": dossier, "files": [relatifs], "skipped": [raisons]}``.
    """
    base = Path(dest) / safe_file_name(tr("%s — pour le DAW") % song.name,
                                       "morceau")
    dossier = base
    n = 2
    while dossier.exists():
        dossier = base.with_name("%s %d" % (base.name, n))
        n += 1
    dossier.mkdir(parents=True)
    fichiers: list[str] = []
    ignores: list[str] = []
    nom = safe_file_name(song.name, "morceau")

    # Les pistes audio, à côté des projets qui les citent.
    audio: dict[int, str] = {}
    pistes = tr("Pistes audio")
    for index, track in enumerate(song.tracks):
        if track.audio and Path(track.audio).exists():
            rel = "%s/%02d %s.wav" % (pistes, index + 1,
                                      safe_file_name(track.name))
            (dossier / pistes).mkdir(exist_ok=True)
            shutil.copy2(track.audio, dossier / rel)
            audio[index] = rel
            fichiers.append(rel)
    if "midi" in formats:
        if write_midi(song, dossier / (nom + ".mid")):
            fichiers.append(nom + ".mid")
        else:
            ignores.append(tr("MIDI : aucune note dans le morceau"))
    if "dawproject" in formats:
        write_dawproject(song, dossier / (nom + ".dawproject"))
        fichiers.append(nom + ".dawproject")
    if "rpp" in formats:
        write_rpp(song, dossier / (nom + ".rpp"), audio)
        fichiers.append(nom + ".rpp")
    if "als" in formats:
        from . import dawals
        try:
            dawals.write_als(song, dossier / (nom + ".als"), audio,
                             template=als_template, notes=ignores)
            fichiers.append(nom + ".als")
        except dawals.TemplateMissing as exc:
            ignores.append(str(exc))
    if machine_audio:
        cible = dossier / tr("Pistes du Deluge")
        for src in machine_audio:
            src = Path(src)
            if src.exists():
                cible.mkdir(exist_ok=True)
                shutil.copy2(src, cible / src.name)
                fichiers.append("%s/%s" % (cible.name, src.name))
    if samples:
        cible = dossier / tr("Échantillons")
        for src in samples:
            src = Path(src)
            if src.exists():
                cible.mkdir(exist_ok=True)
                dst = cible / src.name
                if not dst.exists():
                    shutil.copy2(src, dst)
                    fichiers.append("%s/%s" % (cible.name, src.name))
    write_readme(song, dossier / tr("LISEZMOI.txt"), fichiers)
    fichiers.append(tr("LISEZMOI.txt"))
    log.info("dossier pour le DAW : %s (%d fichiers)", dossier, len(fichiers))
    return {"folder": dossier, "files": fichiers, "skipped": ignores}
