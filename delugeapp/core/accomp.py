# -*- coding: utf-8 -*-
"""Accompagnement : basse, arpège et rythme d'accords tirés d'une progression.

Une progression d'accords n'est qu'une suite de couleurs ; ce qui la rend
jouable, c'est la façon de la poser dans le temps. Ce module transforme la
sortie de :func:`delugeapp.core.theory.progression` en **parties** — accords,
basse, arpège — prêtes à écouter (:func:`delugeapp.core.render.render_parts`)
ou à exporter en MIDI (:func:`delugeapp.core.midifile.parts_to_midi`).

Les styles sont ceux qu'un producteur reconnaît : la basse « contretemps » de
la house et de la trance, la basse « roulante » de la psytrance, les octaves
de la disco et de la synthwave, la marche du jazz et du lo-fi ; les accords
tenus d'une nappe, les « stabs » syncopés de la house, le « charleston » du
pianiste. Chaque genre a ses habitudes (:data:`GENRE_STYLES`).

Module arithmétique, sans dépendance : ni carte, ni audio, ni Qt.

Unité de temps : le **pas de double-croche**, 16 par mesure. Une position
peut être fractionnaire.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass

log = logging.getLogger(__name__)

#: Pas de double-croche par mesure 4/4.
STEPS_PER_BAR = 16


@dataclass
class NoteEvent:
    """Une note d'une partie.

    ``start`` et ``length`` sont en pas de double-croche ; ``velocity`` est
    un pourcentage (1 à 100), comme dans :class:`~delugeapp.core.rhythm.Step`.
    """

    start: float
    length: float
    note: int
    velocity: int = 90


#: Rythmes d'accords : ``(début, durée)`` en pas, pour une mesure.
CHORD_STYLES: dict[str, tuple[tuple[float, float], ...]] = {
    "tenu": ((0.0, 15.5),),
    "blanches": ((0.0, 7.5), (8.0, 7.5)),
    "contretemps": ((2.0, 1.5), (6.0, 1.5), (10.0, 1.5), (14.0, 1.5)),
    # Les stabs de house : syncopés, courts, le dernier un peu tenu.
    "stabs": ((0.0, 1.0), (3.0, 1.0), (6.0, 1.0), (10.0, 1.0), (12.0, 2.0)),
    # Le « charleston » du piano de jazz : sur le 1 et le 2&.
    "charleston": ((0.0, 2.0), (6.0, 2.0)),
}

#: Styles de basse disponibles, avec leur libellé.
BASS_STYLES: dict[str, str] = {
    "fondamentale": "la fondamentale, tenue toute la mesure",
    "pulsée": "la fondamentale en croches",
    "contretemps": "sur les contretemps, entre les grosses caisses",
    "roulante": "trois doubles-croches entre chaque temps (psytrance)",
    "octaves": "fondamentale et octave en alternance (disco, synthwave)",
    "syncopée": "fondamentale, quinte et octave syncopées (funk)",
    "marche": "une note par temps, qui marche vers l'accord suivant",
    "acide": "doubles-croches de 303 : silences, accents, octaves et "
             "glissés (acid)",
}

#: Les deux mesures d'une ligne de 303, en alternance : ``(pas, note,
#: accent, glissé)``. ``R`` fondamentale, ``O`` octave, ``Q`` quinte,
#: ``T`` tierce de l'accord. Un glissé tient la note jusque dans la
#: suivante : sur un son en legato avec portamento, la hauteur glisse.
_ACID_BARS: tuple[tuple[tuple[int, str, bool, bool], ...], ...] = (
    ((0, "R", True, False), (2, "O", False, False), (3, "R", False, False),
     (5, "R", True, False), (6, "Q", False, True), (7, "O", False, False),
     (8, "R", False, False), (10, "R", True, False), (12, "O", False, True),
     (13, "R", False, False), (14, "Q", False, False), (15, "R", True, False)),
    ((0, "R", True, False), (1, "R", False, True), (2, "O", False, False),
     (4, "O", True, False), (6, "R", False, False), (7, "T", True, True),
     (8, "Q", False, False), (9, "R", False, False), (10, "O", False, True),
     (11, "T", False, False), (12, "R", True, False), (14, "O", False, True),
     (15, "Q", False, False)),
)

def _gm_drums() -> dict[str, int]:
    """Note General MIDI de chaque piste de batterie (celle des motifs)."""
    from .midifile import GM_DRUMS

    return GM_DRUMS


def drum_part(pattern, bars: int | None = None) -> list[NoteEvent]:
    """Le motif rythmique en notes General MIDI, bouclé sur ``bars`` mesures.

    Pour l'export : la partie « Batterie » part sur le canal 10, où tout
    séquenceur General MIDI joue des percussions.
    """
    from .rhythm import loop

    if pattern is None:
        return []
    looped = loop(pattern, bars) if bars else pattern
    notes = _gm_drums()
    out: list[NoteEvent] = []
    for track, steps in looped.tracks.items():
        note = notes.get(track, notes.get("Rim", 37))
        for step in steps:
            out.append(NoteEvent(float(step.pos), 1.0, int(note),
                                 max(1, min(100, int(step.velocity)))))
    out.sort(key=lambda e: (e.start, e.note))
    return out


#: Ordres de l'arpège.
ARP_ORDERS = ("montant", "descendant", "aller-retour", "aléatoire")

#: Habitudes de chaque genre : ``(accords, basse, arpège ?)``.
GENRE_STYLES: dict[str, tuple[str, str, bool]] = {
    "acid": ("contretemps", "acide", False),
    "techno": ("stabs", "pulsée", False),
    "detroit": ("tenu", "pulsée", True),
    "minimal": ("contretemps", "pulsée", False),
    "house": ("stabs", "contretemps", False),
    "deep_house": ("blanches", "octaves", False),
    "trance": ("tenu", "contretemps", True),
    "psytrance": ("tenu", "roulante", True),
    "dnb": ("tenu", "fondamentale", False),
    "jungle": ("tenu", "fondamentale", False),
    "dubstep": ("tenu", "fondamentale", False),
    "ambient": ("tenu", "fondamentale", False),
    "berlin_school": ("tenu", "pulsée", True),
    "synthwave": ("tenu", "octaves", True),
    "lofi": ("charleston", "marche", False),
    "idm": ("contretemps", "syncopée", True),
    "industrial": ("stabs", "pulsée", False),
    "electro": ("stabs", "syncopée", False),
    "hardcore": ("stabs", "pulsée", False),
    "downtempo": ("blanches", "marche", False),
    "funk": ("stabs", "syncopée", False),
    "boards_of_canada": ("tenu", "fondamentale", True),
}


def genre_styles(genre: str) -> tuple[str, str, bool]:
    """Styles conseillés pour un genre ; ``tenu``/``fondamentale`` à défaut."""
    return GENRE_STYLES.get(str(genre or "").strip().lower(),
                            ("tenu", "fondamentale", False))


# --------------------------------------------------------------------------- #
# Accords
# --------------------------------------------------------------------------- #

def chord_part(progression: list[dict], style: str = "tenu",
               velocity: int = 80) -> list[NoteEvent]:
    """Les accords de la progression, posés selon ``style``.

    Les voix sont celles de la progression : déjà conduites, elles bougent
    le moins possible d'un accord à l'autre.
    """
    rhythm = CHORD_STYLES.get(style, CHORD_STYLES["tenu"])
    out: list[NoteEvent] = []
    for bar, chord in enumerate(progression or []):
        base = bar * STEPS_PER_BAR
        for index, (start, length) in enumerate(rhythm):
            # Le premier coup de la mesure est un peu plus appuyé.
            vel = min(100, velocity + (8 if index == 0 else 0))
            for note in chord.get("notes") or []:
                out.append(NoteEvent(base + start, length, int(note), vel))
    return out


# --------------------------------------------------------------------------- #
# Basse
# --------------------------------------------------------------------------- #

def _bass_root(chord: dict) -> int:
    """Fondamentale de la basse : celle que fournit la progression."""
    if "bass" in chord:
        return int(chord["bass"])
    notes = chord.get("notes") or [48]
    return 36 + (int(chord.get("root", notes[0])) % 12)


def _fifth(chord: dict, root: int) -> int:
    """Quinte de l'accord au-dessus de la basse (ou ce qui en tient lieu)."""
    for note in sorted(chord.get("notes") or []):
        interval = (note - root) % 12
        if interval in (6, 7, 8):
            return root + interval
    return root + 7


def _third(chord: dict, root: int) -> int:
    for note in sorted(chord.get("notes") or []):
        interval = (note - root) % 12
        if interval in (3, 4):
            return root + interval
    return root + 4


def bass_part(progression: list[dict], style: str = "fondamentale",
              velocity: int = 92) -> list[NoteEvent]:
    """La ligne de basse de la progression, dans le style demandé."""
    chords = list(progression or [])
    out: list[NoteEvent] = []
    for bar, chord in enumerate(chords):
        base = bar * STEPS_PER_BAR
        root = _bass_root(chord)
        nxt = _bass_root(chords[bar + 1]) if bar + 1 < len(chords) else root

        def add(step: float, length: float, note: int, vel: int = velocity):
            out.append(NoteEvent(base + step, length, int(note),
                                 max(1, min(100, vel))))

        if style == "pulsée":
            for step in range(0, STEPS_PER_BAR, 2):
                add(step, 1.6, root, velocity if step % 4 == 0
                    else velocity - 14)
        elif style == "contretemps":
            for step in (2, 6, 10, 14):
                add(step, 1.6, root)
        elif style == "roulante":
            for step in range(STEPS_PER_BAR):
                if step % 4:
                    add(step, 0.9, root, velocity - (0 if step % 4 == 1
                                                     else 10))
        elif style == "octaves":
            for step in range(0, STEPS_PER_BAR, 2):
                add(step, 1.6, root + (12 if step % 4 == 2 else 0),
                    velocity if step % 4 == 0 else velocity - 10)
        elif style == "syncopée":
            fifth = _fifth(chord, root)
            for step, length, note in ((0, 2.5, root), (3, 1.0, root),
                                       (6, 1.5, fifth), (8, 1.0, root),
                                       (10, 1.5, root + 12), (14, 1.0, fifth)):
                add(step, length, note, velocity if step == 0
                    else velocity - 12)
        elif style == "acide":
            third = _third(chord, root)
            fifth = _fifth(chord, root)
            pitches = {"R": root, "O": root + 12, "Q": fifth, "T": third}
            steps = _ACID_BARS[bar % len(_ACID_BARS)]
            for index, (step, kind, accent, slide) in enumerate(steps):
                note = pitches[kind]
                following = steps[index + 1] if index + 1 < len(steps) else None
                # Un glissé ne vaut que vers une autre hauteur au pas suivant :
                # deux notes identiques qui se chevauchent se coupent en MIDI.
                glides = (slide and following is not None
                          and following[0] == step + 1
                          and pitches[following[1]] != note)
                add(step, 1.3 if glides else 0.6, note,
                    velocity if accent else velocity - 22)
        elif style == "marche":
            # Une note par temps : fondamentale, tierce, quinte, puis une
            # note d'approche à un demi-ton de l'accord suivant.
            approach = nxt - 1 if nxt > root else nxt + 1
            for beat, note in enumerate((root, _third(chord, root),
                                         _fifth(chord, root), approach)):
                add(beat * 4, 3.6, note,
                    velocity if beat == 0 else velocity - 12)
        else:                                   # fondamentale
            add(0, 15.5, root)
    return out


# --------------------------------------------------------------------------- #
# Arpège
# --------------------------------------------------------------------------- #

def arp_part(progression: list[dict], order: str = "montant",
             rate: int = 2, octaves: int = 1, velocity: int = 76,
             seed: int | None = None) -> list[NoteEvent]:
    """Arpège des accords de la progression.

    :param rate: durée d'une note en pas — 1 pour des doubles-croches,
        2 pour des croches.
    :param octaves: étendue de l'arpège en octaves.
    """
    rng = random.Random(seed if seed is not None else 0)
    step_len = max(0.5, float(rate))
    span = max(1, min(3, int(octaves)))
    out: list[NoteEvent] = []
    for bar, chord in enumerate(progression or []):
        base = bar * STEPS_PER_BAR
        tones = sorted(set(chord.get("notes") or []))
        if not tones:
            continue
        # L'arpège monte au-dessus des accords, pour ne pas les recouvrir.
        lift = 12
        pool = [n + lift + 12 * o for o in range(span) for n in tones]
        if order == "descendant":
            cycle = pool[::-1]
        elif order == "aller-retour":
            cycle = pool + pool[-2:0:-1]
        else:
            cycle = pool
        count = int(STEPS_PER_BAR // step_len)
        for index in range(count):
            note = (rng.choice(pool) if order == "aléatoire"
                    else cycle[index % len(cycle)])
            accent = index % int(max(1, 4 // step_len)) == 0
            out.append(NoteEvent(base + index * step_len, step_len * 0.85,
                                 int(note), velocity + (12 if accent else 0)))
    return out


# --------------------------------------------------------------------------- #
# Mélodie
# --------------------------------------------------------------------------- #

#: Allures de mélodie, avec leur libellé.
MELODY_STYLES: dict[str, str] = {
    "posée": "peu de notes, longues (ambient, downtempo, nappes)",
    "chantante": "noires et croches, une phrase qui respire "
                 "(trance, synthwave, lo-fi)",
    "syncopée": "un riff en croches et doubles-croches décalées "
                "(house, funk, techno)",
}

#: Rythmes d'une mesure pour chaque allure : ``(début, durée)`` en pas.
_MELODY_RHYTHMS: dict[str, list[tuple[tuple[float, float], ...]]] = {
    "posée": [
        ((0, 8), (8, 8)),
        ((0, 12), (12, 4)),
        ((0, 6), (6, 10)),
        ((0, 4), (4, 12)),
    ],
    "chantante": [
        ((0, 4), (4, 2), (6, 2), (8, 6), (14, 2)),
        ((0, 3), (3, 3), (6, 2), (8, 4), (12, 4)),
        ((0, 2), (2, 2), (4, 4), (8, 2), (10, 2), (12, 4)),
        ((0, 6), (6, 2), (8, 4), (12, 4)),
        ((0, 2), (2, 4), (8, 2), (10, 6)),
    ],
    "syncopée": [
        ((0, 2), (3, 1), (6, 2), (10, 1), (12, 2)),
        ((0, 1), (2, 2), (6, 1), (8, 2), (11, 2), (14, 2)),
        ((0, 3), (3, 3), (6, 2), (10, 2), (14, 2)),
        ((0, 2), (5, 2), (8, 1), (10, 2), (13, 3)),
    ],
}

#: Fin de phrase : moins de notes, la dernière tenue.
_MELODY_CADENCES: dict[str, tuple[tuple[float, float], ...]] = {
    "posée": ((0, 16),),
    "chantante": ((0, 4), (4, 4), (8, 8)),
    "syncopée": ((0, 2), (3, 3), (6, 2), (8, 8)),
}

#: Allure habituelle de chaque genre.
GENRE_MELODY: dict[str, str] = {
    "ambient": "posée", "downtempo": "posée", "boards_of_canada": "posée",
    "dubstep": "posée", "berlin_school": "chantante", "dnb": "chantante",
    "jungle": "chantante", "trance": "chantante", "synthwave": "chantante",
    "lofi": "chantante", "detroit": "chantante", "psytrance": "syncopée",
    "idm": "syncopée", "house": "syncopée", "deep_house": "syncopée",
    "funk": "syncopée", "techno": "syncopée", "minimal": "syncopée",
    "acid": "syncopée", "electro": "syncopée", "industrial": "syncopée",
    "hardcore": "syncopée",
}


def _scale_classes(progression: list[dict], root: int, scale: str) -> set[int]:
    """Classes de hauteur de la gamme ; à défaut, celles des accords."""
    from .theory import SCALES

    intervals = SCALES.get(scale)
    if intervals:
        return {(root + i) % 12 for i in intervals}
    out: set[int] = set()
    for chord in progression:
        out.update(int(n) % 12 for n in chord.get("notes") or [])
    return out or {(root + i) % 12 for i in SCALES["majeur"]}


def _chord_classes(chord: dict) -> set[int]:
    """Notes de l'accord, fondamentale comprise même si on ne la joue pas."""
    out = {int(n) % 12 for n in chord.get("notes") or []}
    if "root" in chord:
        out.add(int(chord["root"]) % 12)
    return out


def melody_part(progression: list[dict], root: int | None = None,
                scale: str = "", style: str = "", genre: str = "",
                seed: int | None = None,
                velocity: int = 92) -> list[NoteEvent]:
    """Une mélodie sur la progression, phrasée par quatre mesures.

    Ce qu'un mélodiste fait d'instinct, rendu explicite pour être vérifié :

    * **un motif qu'on répète** : la phrase de quatre mesures suit le plan
      A A B — fin de phrase, et la deuxième mesure reprend la première en
      marche, transposée sur le nouvel accord ;
    * **les notes de l'accord sur les temps forts** (le 1 et le 3, et la
      première note de chaque mesure), celles de la gamme entre eux ;
    * **un mouvement surtout conjoint** : des degrés voisins, parfois une
      tierce ou une quarte, et le saut est rattrapé en sens inverse ; la
      phrase monte puis redescend ;
    * **une fin qui conclut** : la dernière note tombe sur la fondamentale du
      dernier accord, tenue.

    :param root: tonique ; à défaut, la fondamentale du premier accord.
    :param scale: gamme (:data:`delugeapp.core.theory.SCALES`) ; à défaut,
        les notes des accords.
    :param style: allure (:data:`MELODY_STYLES`) ; vide = celle du genre.
    """
    chords = list(progression or [])
    if not chords:
        return []
    rng = random.Random(seed if seed is not None else 0)
    key = str(genre or "").strip().lower()
    allure = style if style in MELODY_STYLES else GENRE_MELODY.get(
        key, "chantante")
    tonic = int(root if root is not None else chords[0].get("root", 60))
    classes = _scale_classes(chords, tonic, scale)

    # Registre : la tonique vers le do 5 (MIDI 67 à 78), une octave et
    # demie de jeu — au-dessus des accords, sous l'arpège.
    centre = 72 + tonic % 12
    if centre > 78:
        centre -= 12
    pool = [n for n in range(centre - 7, centre + 13) if n % 12 in classes]
    if len(pool) < 3:
        return []

    def nearest(note: float) -> int:
        return min(range(len(pool)), key=lambda i: (abs(pool[i] - note), i))

    def on_chord(index: int, chord: dict) -> int:
        tones = _chord_classes(chord)
        candidates = [i for i in range(len(pool)) if pool[i] % 12 in tones]
        if not candidates:
            return index
        best = min(abs(i - index) for i in candidates)
        ties = [i for i in candidates if abs(i - index) == best]
        return rng.choice(ties)

    def clamp(index: int) -> int:
        if index < 0:
            return min(len(pool) - 1, -index)
        if index >= len(pool):
            return max(0, 2 * (len(pool) - 1) - index)
        return index

    rhythms = _MELODY_RHYTHMS[allure]
    motif_a = rng.choice(rhythms)
    others = [r for r in rhythms if r != motif_a] or rhythms
    motif_b = rng.choice(others)
    cadence = _MELODY_CADENCES[allure]

    out: list[NoteEvent] = []
    previous = on_chord(nearest(centre), chords[0])
    last_leap = 0
    first_a: list[int] = []

    def fresh(rhythm, chord, rising: bool) -> list[int]:
        nonlocal previous, last_leap
        indices: list[int] = []
        for position, (start, _length) in enumerate(rhythm):
            strong = position == 0 or start % 8 == 0
            if indices or out:
                draw = rng.random()
                if last_leap:
                    # Un saut se rattrape par un degré dans l'autre sens.
                    move, last_leap = -last_leap // abs(last_leap), 0
                else:
                    step = (3 if draw < 0.12 else 1 if draw < 0.55
                            else 2 if draw < 0.85 else 0)
                    direction = 1 if rising else -1
                    if rng.random() < 0.2:
                        direction = -direction
                    move = step * direction
                    if step == 3:
                        last_leap = move
                index = clamp(previous + move)
            else:
                index = previous
            if strong:
                index = on_chord(index, chord)
            indices.append(index)
            previous = index
        return indices

    phrases = [chords[i:i + 4] for i in range(0, len(chords), 4)]
    bar = 0
    for phrase in phrases:
        size = len(phrase)
        plan = {4: ["A", "A2", "B", "fin"], 3: ["A", "B", "fin"],
                2: ["A", "fin"], 1: ["fin"]}[size]
        for slot, chord in zip(plan, phrase):
            rising = plan.index(slot) < size / 2
            if slot == "A" and first_a:
                rhythm = motif_a
                # Reprise d'une phrase précédente : le même motif, recalé.
                start = on_chord(first_a[0], chord)
                indices = [clamp(start + (i - first_a[0])) for i in first_a]
                for k, (begin, _l) in enumerate(rhythm):
                    if k == 0 or begin % 8 == 0:
                        indices[k] = on_chord(indices[k], chord)
                previous = indices[-1]
            elif slot == "A":
                rhythm = motif_a
                indices = fresh(rhythm, chord, rising)
                first_a = list(indices)
            elif slot == "A2":
                # La marche : le motif de la mesure précédente, transposé
                # pour que sa première note tombe dans le nouvel accord.
                rhythm = motif_a
                base = on_chord(first_a[0] + 1, chord)
                indices = [clamp(base + (i - first_a[0])) for i in first_a]
                for k, (start, _l) in enumerate(rhythm):
                    if k == 0 or start % 8 == 0:
                        indices[k] = on_chord(indices[k], chord)
                previous = indices[-1]
            elif slot == "B":
                rhythm = motif_b
                indices = fresh(rhythm, chord, rising)
            else:
                rhythm = cadence
                tones = {int(chord.get("root", tonic)) % 12}
                targets = [i for i in range(len(pool)) if pool[i] % 12 in tones]
                target = (min(targets, key=lambda i: (abs(i - previous), i))
                          if targets else previous)
                indices = []
                count = len(rhythm)
                for k in range(count):
                    if k == count - 1:
                        index = target
                    else:
                        # On s'approche de la note finale par degrés.
                        remaining = count - 1 - k
                        index = clamp(target + remaining * (
                            1 if previous > target else -1))
                        if k == 0:
                            index = on_chord(index, chord)
                    indices.append(index)
                    previous = index
            base_step = bar * STEPS_PER_BAR
            for k, ((start, length), index) in enumerate(zip(rhythm, indices)):
                strong = k == 0 or start % 8 == 0
                vel = velocity + (6 if strong else -8 - rng.randrange(6))
                held = length * (0.8 if allure == "syncopée" else 0.95)
                if slot == "fin" and k == len(rhythm) - 1:
                    held = length * 0.98
                out.append(NoteEvent(base_step + start, held, pool[index],
                                     max(1, min(100, vel))))
            bar += 1
    return out


# --------------------------------------------------------------------------- #
# L'ensemble
# --------------------------------------------------------------------------- #

def accompany(progression: list[dict], genre: str = "",
              chords: str = "", bass: str = "",
              arp: bool | None = None, arp_order: str = "montant",
              arp_rate: int = 1, seed: int | None = None,
              melody: bool = False, melody_style: str = "",
              root: int | None = None, scale: str = "",
              drums=None) -> dict[str, list[NoteEvent]]:
    """Les parties d'accompagnement d'une progression.

    Les styles vides prennent ceux du genre (:data:`GENRE_STYLES`,
    :data:`GENRE_MELODY`). Retourne ``{'Accords': […], 'Basse': […],
    'Arpège': […], 'Mélodie': […], 'Batterie': […]}`` ; l'arpège, la
    mélodie et la batterie (``drums`` : un motif de
    :mod:`delugeapp.core.rhythm`, bouclé sur la progression) n'y figurent que
    s'ils sont demandés.
    """
    g_chords, g_bass, g_arp = genre_styles(genre)
    parts = {
        "Accords": chord_part(progression, chords or g_chords),
        "Basse": bass_part(progression, bass or g_bass),
    }
    if g_arp if arp is None else arp:
        parts["Arpège"] = arp_part(progression, arp_order, arp_rate,
                                   octaves=2, seed=seed)
    if melody:
        parts["Mélodie"] = melody_part(progression, root=root, scale=scale,
                                       style=melody_style, genre=genre,
                                       seed=seed)
    if drums is not None:
        parts["Batterie"] = drum_part(drums, max(1, len(progression or [])))
    return parts


def total_steps(parts: dict[str, list[NoteEvent]]) -> float:
    """Longueur de l'ensemble, en pas, arrondie à la mesure entière."""
    end = 0.0
    for events in (parts or {}).values():
        for event in events:
            end = max(end, event.start + event.length)
    bars = max(1, int(-(-end // STEPS_PER_BAR)))
    return float(bars * STEPS_PER_BAR)
