# -*- coding: utf-8 -*-
"""Écriture de fichiers MIDI standard, sans aucune dépendance.

Sert à faire sortir de l'application ce qu'on y a fabriqué — un motif
rythmique, une progression d'accords, un clip lu dans un morceau — vers
n'importe quel autre logiciel de musique.

Le format produit est un **SMF de type 1** : une piste de tempo suivie d'une
piste par instrument, ce que tous les séquenceurs savent lire. Les durées sont
exprimées en impulsions par noire (``ppq``), 96 par défaut, soit un multiple
exact des 24 ticks du Deluge : la conversion est donc sans perte.
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass, field
from pathlib import Path

from ..i18n import tr

log = logging.getLogger(__name__)

#: Résolution par défaut, multiple des 24 ticks par noire du Deluge.
DEFAULT_PPQ = 96

#: Résolution du Deluge, pour la conversion des clips et des motifs.
DELUGE_PPQ = 24

#: Canal réservé aux percussions par la norme General MIDI (canal 10,
#: numéroté 9 à partir de zéro).
DRUM_CHANNEL = 9

#: Correspondance rôle de percussion -> note General MIDI, pour que l'export
#: d'un motif tombe sur les bons sons dans un autre logiciel.
GM_DRUMS: dict[str, int] = {
    "Kick": 36, "Snare": 38, "Clap": 39, "Rim": 37,
    "HatC": 42, "HatO": 46, "Crash": 49, "Ride": 51, "China": 52,
    "TomL": 45, "TomM": 47, "TomH": 50,
    "ConL": 64, "ConM": 63, "ConH": 62,
    "Cowbell": 56, "Block": 76, "Claves": 75, "Shaker": 70,
    "Tambourine": 54, "Guiro": 73, "Timpany": 47, "Other": 41,
}


@dataclass
class MidiTrack:
    """Une piste : des notes sur un canal.

    Chaque événement est un quadruplet ``(tick, note, vélocité, durée)``, où
    ``tick`` et ``durée`` sont exprimés dans la résolution passée à
    :func:`write_midi`.
    """

    name: str = ""
    channel: int = 0
    events: list[tuple[int, int, int, int]] = field(default_factory=list)

    def add(self, tick: int, note: int, velocity: int = 100,
            duration: int = 24) -> None:
        """Ajoute une note."""
        self.events.append((int(tick), int(note), int(velocity),
                            int(duration)))


# --------------------------------------------------------------------------- #
# Encodage bas niveau
# --------------------------------------------------------------------------- #

def _varlen(value: int) -> bytes:
    """Entier en longueur variable, comme l'exige le format MIDI.

    Sept bits par octet, bit de poids fort à 1 pour indiquer qu'un octet
    suit. C'est la façon dont les délais sont codés dans un SMF.
    """
    number = max(0, int(value))
    out = bytearray([number & 0x7F])
    number >>= 7
    while number:
        out.insert(0, (number & 0x7F) | 0x80)
        number >>= 7
    return bytes(out)


def _meta(kind: int, payload: bytes) -> bytes:
    """Événement méta : ``FF <type> <longueur> <données>``."""
    return b"\xFF" + bytes([kind]) + _varlen(len(payload)) + payload


def _text_meta(kind: int, text: str) -> bytes:
    """Événement méta textuel, réduit à l'ASCII.

    Les noms de pistes non ASCII sont mal rendus par beaucoup de
    séquenceurs : mieux vaut translittérer que livrer des octets douteux.
    """
    import unicodedata

    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    payload = stripped.encode("ascii", "replace")[:120]
    return _meta(kind, payload)


def _chunk(tag: bytes, body: bytes) -> bytes:
    """Bloc MIDI : étiquette, longueur sur 4 octets, contenu."""
    return tag + struct.pack(">I", len(body)) + body


def _track_bytes(track: MidiTrack) -> bytes:
    """Encode une piste en bloc ``MTrk``.

    Les notes sont converties en paires activation/extinction, puis triées
    par instant : un SMF code des **délais** entre événements, donc l'ordre
    chronologique est obligatoire.
    """
    channel = max(0, min(15, int(track.channel)))
    timeline: list[tuple[int, int, int, int]] = []
    for tick, note, velocity, duration in track.events:
        pitch = max(0, min(127, int(note)))
        level = max(1, min(127, int(velocity)))
        start = max(0, int(tick))
        end = start + max(1, int(duration))
        # Le second champ ordonne les simultanéités : une extinction (0) passe
        # avant une activation (1) au même instant, pour qu'une note répétée
        # sur le même pas ne soit pas coupée par sa propre extinction.
        timeline.append((start, 1, pitch, level))
        timeline.append((end, 0, pitch, 0))
    timeline.sort(key=lambda e: (e[0], e[1]))

    body = bytearray()
    if track.name:
        body += b"\x00" + _text_meta(0x03, track.name)

    previous = 0
    for tick, kind, pitch, level in timeline:
        body += _varlen(tick - previous)
        previous = tick
        if kind:
            body += bytes([0x90 | channel, pitch, level])
        else:
            body += bytes([0x80 | channel, pitch, 0])

    body += b"\x00" + _meta(0x2F, b"")      # fin de piste
    return _chunk(b"MTrk", bytes(body))


def _tempo_track(bpm: float, ppq: int, name: str = "",
                 markers: list[tuple[int, str]] | None = None) -> bytes:
    """Piste de tête : tempo, métrique, et repères de section éventuels.

    Les repères (méta-événement 0x06, « marker ») s'affichent dans la ligne
    de temps de la plupart des logiciels de MAO : Intro, Montée, Cassure…
    """
    try:
        tempo = float(bpm)
    except (TypeError, ValueError):
        tempo = 120.0
    if tempo <= 0:
        tempo = 120.0
    micros = int(round(60_000_000.0 / tempo))

    body = bytearray()
    if name:
        body += b"\x00" + _text_meta(0x03, name)
    body += b"\x00" + _meta(0x51, struct.pack(">I", micros)[1:])
    # Métrique 4/4, noire = unité, 24 impulsions MIDI par noire.
    body += b"\x00" + _meta(0x58, bytes([4, 2, 24, 8]))
    previous = 0
    for tick, text in sorted(markers or [], key=lambda m: m[0]):
        tick = max(previous, int(tick))
        body += _varlen(tick - previous) + _text_meta(0x06, text)
        previous = tick
    body += b"\x00" + _meta(0x2F, b"")
    return _chunk(b"MTrk", bytes(body))


# --------------------------------------------------------------------------- #
# Écriture
# --------------------------------------------------------------------------- #

def write_midi(path: Path, tracks: list[MidiTrack], bpm: float = 120.0,
               ppq: int = DEFAULT_PPQ,
               markers: list[tuple[int, str]] | None = None) -> None:
    """Écrit un fichier MIDI de type 1.

    La première piste du fichier porte le tempo ; les pistes fournies
    suivent. Les pistes vides sont écrites quand même, pour que la
    correspondance avec les rangées d'origine reste lisible.

    Lève ``OSError`` si le fichier n'est pas accessible en écriture.
    """
    target = Path(path)
    resolution = max(1, int(ppq))
    blocks = [_tempo_track(bpm, resolution, target.stem, markers)]
    blocks += [_track_bytes(t) for t in (tracks or [])]

    header = struct.pack(">HHH", 1, len(blocks), resolution)
    data = _chunk(b"MThd", header) + b"".join(blocks)

    target.parent.mkdir(parents=True, exist_ok=True)
    # Écriture par un fichier temporaire puis remplacement : un export
    # interrompu ne laisse pas un MIDI tronqué derrière lui.
    tmp = target.with_suffix(target.suffix + ".part")
    try:
        tmp.write_bytes(data)
        tmp.replace(target)
    except OSError:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise
    log.info("MIDI écrit : %s (%d piste(s), %.1f BPM)", target,
             len(blocks) - 1, bpm)


def pattern_to_midi(path: Path, pattern, row_map: dict[str, int] | None,
                    bpm: float) -> None:
    """Exporte un motif rythmique.

    :param row_map: ``{nom de piste: note MIDI}``. Omis ou incomplet, les
        notes sont prises dans :data:`GM_DRUMS` afin que le fichier sonne
        juste dans n'importe quel séquenceur General MIDI.

    Toutes les pistes sont réunies sur le canal 10, celui des percussions.
    """
    mapping = dict(row_map or {})
    drum = MidiTrack(name=tr(pattern.name) if pattern.name else tr("Rythme"),
                     channel=DRUM_CHANNEL)

    ratio = DEFAULT_PPQ / float(max(1, pattern.ppq))
    per_step = pattern.ticks_per_step
    for track, steps in pattern.tracks.items():
        note = mapping.get(track)
        if note is None:
            note = GM_DRUMS.get(track)
        if note is None:
            log.debug("piste sans note MIDI : %r", track)
            continue
        for step in steps:
            tick = int(round(float(step.pos) * per_step * ratio))
            length = max(1, int(round(float(step.length) * per_step * ratio)))
            velocity = max(1, min(127, int(step.velocity * 127 // 100)))
            drum.add(tick, int(note), velocity, length)

    write_midi(path, [drum], bpm=bpm, ppq=DEFAULT_PPQ)


def progression_to_midi(path: Path, chords: list[dict], bpm: float,
                        ppq: int = DEFAULT_PPQ) -> None:
    """Exporte une progression d'accords, un accord par mesure.

    ``chords`` est la sortie de
    :func:`delugeapp.core.theory.progression` : chaque entrée porte ses
    ``notes`` et sa durée en ``bars``.
    """
    resolution = max(1, int(ppq))
    track = MidiTrack(name=tr("Accords"), channel=0)
    position = 0
    for chord in (chords or []):
        notes = chord.get("notes") or []
        bars = float(chord.get("bars", 1) or 1)
        duration = max(1, int(round(bars * 4 * resolution)))
        for note in notes:
            # Les notes sont légèrement raccourcies : sans cela, l'accord
            # suivant démarre exactement quand le précédent s'arrête, ce que
            # certains instruments interprètent comme une seule note tenue.
            track.add(position, int(note), 90, max(1, int(duration * 0.97)))
        position += duration
    write_midi(path, [track], bpm=bpm, ppq=resolution)


#: Canal MIDI de chaque partie d'accompagnement (numérotés à partir de 0).
PART_CHANNELS = {"Accords": 0, "Basse": 1, "Arpège": 2, "Mélodie": 3,
                 "Batterie": DRUM_CHANNEL}


def parts_to_midi(path: Path, parts: dict, bpm: float,
                  ppq: int = DEFAULT_PPQ,
                  markers: list[tuple[float, str]] | None = None) -> int:
    """Exporte des parties d'accompagnement : une piste par partie.

    ``parts`` est la sortie de :func:`delugeapp.core.accomp.accompany` :
    ``{nom: [NoteEvent]}``, positions en pas de double-croche. Chaque partie
    a son canal (:data:`PART_CHANNELS`), pour qu'un séquenceur — ou le
    Deluge, une piste par instrument — les joue sur des sons différents.

    :param markers: ``[(position en pas, nom)]`` — les sections d'une
        esquisse, écrites comme repères.

    Retourne le nombre de pistes écrites.
    """
    resolution = max(1, int(ppq))
    per_step = resolution / 4.0
    tracks: list[MidiTrack] = []
    for index, (name, events) in enumerate((parts or {}).items()):
        if not events:
            continue
        # Le nom de la partie (« Accords ») reste la clé de son canal ; la
        # piste se nomme dans la langue de l'interface.
        track = MidiTrack(name=tr(name),
                          channel=PART_CHANNELS.get(name, 3 + index))
        for event in events:
            velocity = max(1, min(127, int(event.velocity * 127 // 100)))
            track.add(int(round(event.start * per_step)), int(event.note),
                      velocity, max(1, int(round(event.length * per_step))))
        tracks.append(track)
    if tracks:
        write_midi(path, tracks, bpm=bpm, ppq=resolution,
                   markers=[(int(round(step * per_step)), tr(text))
                            for step, text in (markers or [])])
    return len(tracks)


def _ratio(clip) -> float:
    """Facteur entre les ticks d'un clip du Deluge et ceux du fichier MIDI.

    **Correction mesurée (14 octobre 2026).** Le facteur valait toujours 4,
    comme si une noire du Deluge faisait 24 ticks. Elle en fait
    ``24 << inputTickMagnitude`` : 48 dans les morceaux 3.x, 96 dans les
    morceaux c1.2.1. Les exports de morceaux sortaient donc deux à quatre
    fois trop lents. Un objet qui ne dit pas sa résolution garde l'ancienne
    hypothèse (24 par noire).
    """
    par_noire = getattr(clip, "ticks_per_quarter", None)
    try:
        par_noire = float(par_noire) if par_noire else float(DELUGE_PPQ)
    except (TypeError, ValueError):
        par_noire = float(DELUGE_PPQ)
    return DEFAULT_PPQ / max(1.0, par_noire)


def song_to_midi(path: Path, song, max_clips: int = 64) -> int:
    """Exporte un morceau entier : **une piste MIDI par clip**.

    Retourne le nombre de pistes écrites.

    Les clips du Deluge vivent dans une grille de session : ce sont des
    boucles qu'on déclenche, et le fichier ne porte **aucune position
    absolue** pour elles — vérifié sur les 46 morceaux de la carte de
    référence, dont aucun n'utilise la vue arrangement. Toutes les pistes
    démarrent donc au même point, chacune avec sa longueur propre. C'est ce
    que les données permettent d'affirmer ; inventer un placement dans le
    temps serait une fiction.

    Une piste de kit part sur le canal des percussions, pour qu'un
    séquenceur General MIDI la joue avec des percussions.
    """
    tracks: list[MidiTrack] = []

    clips = list(getattr(song, "clips", []) or [])
    clips += list(getattr(song, "arrangement_clips", []) or [])

    for index, clip in enumerate(clips, 1):
        if len(tracks) >= max(1, int(max_clips)):
            log.info("morceau tronqué à %d pistes", len(tracks))
            break
        rows = [r for r in (getattr(clip, "note_rows", []) or []) if r.notes]
        if not rows:
            continue

        est_kit = bool(getattr(clip, "is_kit", False))
        ratio = _ratio(clip)
        nom = (getattr(clip, "name", "") or getattr(clip, "preset_name", "")
               or "Clip %d" % index)
        track = MidiTrack(name=nom[:40],
                          channel=DRUM_CHANNEL if est_kit else 0)
        for row in rows:
            for note in row.notes:
                track.add(int(round(note.pos * ratio)), int(row.y),
                          max(1, min(127, note.velocity)),
                          max(1, int(round(note.length * ratio))))
        tracks.append(track)

    if not tracks:
        return 0
    write_midi(path, tracks, bpm=float(getattr(song, "tempo_bpm", 120.0)),
               ppq=DEFAULT_PPQ)
    return len(tracks)


def clip_to_midi(path: Path, clip, bpm: float) -> None:
    """Exporte un clip lu dans un morceau du Deluge.

    Une piste MIDI par rangée de notes, ce qui permet de retrouver la
    structure du clip dans le séquenceur d'arrivée. Les positions du Deluge
    sont converties à la résolution du fichier MIDI d'après celle du
    morceau (voir :func:`_ratio`).
    """
    ratio = _ratio(clip)
    tracks: list[MidiTrack] = []
    for row in getattr(clip, "note_rows", []) or []:
        if not row.notes:
            continue
        name = f"y{row.y}"
        channel = DRUM_CHANNEL if getattr(clip, "is_kit", False) else 0
        track = MidiTrack(name=name, channel=channel)
        for note in row.notes:
            track.add(int(round(note.pos * ratio)), int(row.y),
                      max(1, min(127, note.velocity)),
                      max(1, int(round(note.length * ratio))))
        tracks.append(track)

    if not tracks:
        tracks = [MidiTrack(name=getattr(clip, "name", "") or "Clip")]
    write_midi(path, tracks, bpm=bpm, ppq=DEFAULT_PPQ)
