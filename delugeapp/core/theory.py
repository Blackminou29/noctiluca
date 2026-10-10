# -*- coding: utf-8 -*-
"""Théorie musicale : gammes, accords, progressions, mixage harmonique.

Module purement arithmétique — ni carte SD, ni audio, ni Qt. Les notes sont
des numéros MIDI, où 60 est le do central (``Do3`` dans la convention de ce
projet, cf. SPEC §4.10).

Sert à trois choses dans l'application :

* proposer des notes justes dans la page Outils (gammes, accords,
  progressions) ;
* remplir le ``<modeNotes>`` d'un morceau du Deluge, qui n'accepte que les
  intervalles d'une gamme ;
* trouver quels morceaux se mixent harmonieusement, par le système Camelot.
"""

from __future__ import annotations

import logging
import random

log = logging.getLogger(__name__)

#: Noms français. Les altérations suivent l'usage : on écrit « Mib » plutôt
#: que « Ré# », parce que c'est ainsi qu'un musicien francophone les lit.
NOTE_NAMES_FR = ("Do", "Do#", "Ré", "Mib", "Mi", "Fa", "Fa#", "Sol", "Sol#",
                 "La", "Sib", "Si")
NOTE_NAMES_EN = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#",
                 "B")

#: Décalage d'octave : MIDI 60 est nommé « 3 » (convention Yamaha, celle du
#: Deluge), et non « 4 » comme en notation scientifique.
OCTAVE_OFFSET = 2

#: Gammes, par intervalles en demi-tons depuis la tonique.
SCALES: dict[str, tuple[int, ...]] = {
    "majeur": (0, 2, 4, 5, 7, 9, 11),
    "mineur": (0, 2, 3, 5, 7, 8, 10),
    "mineur harmonique": (0, 2, 3, 5, 7, 8, 11),
    "mineur mélodique": (0, 2, 3, 5, 7, 9, 11),
    "dorien": (0, 2, 3, 5, 7, 9, 10),
    "phrygien": (0, 1, 3, 5, 7, 8, 10),
    "lydien": (0, 2, 4, 6, 7, 9, 11),
    "mixolydien": (0, 2, 4, 5, 7, 9, 10),
    "locrien": (0, 1, 3, 5, 6, 8, 10),
    "phrygien dominant": (0, 1, 4, 5, 7, 8, 10),
    "lydien b7": (0, 2, 4, 6, 7, 9, 10),
    "pentatonique majeure": (0, 2, 4, 7, 9),
    "pentatonique mineure": (0, 3, 5, 7, 10),
    "blues": (0, 3, 5, 6, 7, 10),
    "par tons": (0, 2, 4, 6, 8, 10),
    "diminuée": (0, 2, 3, 5, 6, 8, 9, 11),
    "diminuée demi-ton": (0, 1, 3, 4, 6, 7, 9, 10),
    "hongroise mineure": (0, 2, 3, 6, 7, 8, 11),
    "hijaz": (0, 1, 4, 5, 7, 8, 10),
    "in sen": (0, 1, 5, 7, 10),
    "hirajoshi": (0, 2, 3, 7, 8),
    "kumoi": (0, 2, 3, 7, 9),
    "égyptienne": (0, 2, 5, 7, 10),
    "prométhée": (0, 2, 4, 6, 9),
    "chromatique": tuple(range(12)),
}

#: Accords, par intervalles depuis la fondamentale.
CHORDS: dict[str, tuple[int, ...]] = {
    "maj": (0, 4, 7),
    "min": (0, 3, 7),
    "dim": (0, 3, 6),
    "aug": (0, 4, 8),
    "sus2": (0, 2, 7),
    "sus4": (0, 5, 7),
    "5": (0, 7),
    "6": (0, 4, 7, 9),
    "m6": (0, 3, 7, 9),
    "7": (0, 4, 7, 10),
    "maj7": (0, 4, 7, 11),
    "m7": (0, 3, 7, 10),
    "mMaj7": (0, 3, 7, 11),
    "m7b5": (0, 3, 6, 10),
    "dim7": (0, 3, 6, 9),
    "7sus4": (0, 5, 7, 10),
    "add9": (0, 4, 7, 14),
    "madd9": (0, 3, 7, 14),
    "9": (0, 4, 7, 10, 14),
    "maj9": (0, 4, 7, 11, 14),
    "m9": (0, 3, 7, 10, 14),
    "7b9": (0, 4, 7, 10, 13),
    "7#9": (0, 4, 7, 10, 15),
    "7#11": (0, 4, 7, 10, 18),
    "11": (0, 4, 7, 10, 14, 17),
    "m11": (0, 3, 7, 10, 14, 17),
    "13": (0, 4, 7, 10, 14, 21),
    "m13": (0, 3, 7, 10, 14, 21),
}

#: Degrés d'une gamme, en chiffres romains. Majuscule = accord majeur.
_ROMAN = ("I", "II", "III", "IV", "V", "VI", "VII")

#: Progressions d'accords usuelles, par ambiance ou par genre.
#: Les degrés sont notés en chiffres romains ; la casse est recalculée à
#: partir de la gamme, donc ``i`` et ``I`` désignent le même degré.
PROGRESSIONS: dict[str, list[list[str]]] = {
    "pop": [["I", "V", "VI", "IV"], ["I", "IV", "V", "I"],
            ["VI", "IV", "I", "V"]],
    "mélancolique": [["I", "VI", "III", "VII"], ["I", "VII", "VI", "VII"],
                     ["I", "III", "VI", "IV"]],
    "house": [["I", "IV", "VI", "V"], ["II", "V", "I", "VI"],
              ["I", "VI", "II", "V"]],
    "deep": [["I", "III", "IV", "VI"], ["I", "VII", "III", "VI"]],
    "techno": [["I", "I", "VI", "VI"], ["I", "VII", "I", "VII"],
               ["I", "VI", "VII", "VI"]],
    "trance": [["VI", "IV", "I", "V"], ["I", "V", "VI", "IV"],
               ["VI", "VII", "I", "V"]],
    "ambient": [["I", "IV", "I", "V"], ["I", "III", "IV", "I"],
                ["I", "VI", "IV", "I"]],
    "jazz": [["II", "V", "I", "I"], ["I", "VI", "II", "V"],
             ["III", "VI", "II", "V"]],
    "blues": [["I", "I", "IV", "I"], ["I", "IV", "I", "V"]],
    "épique": [["VI", "VII", "I", "I"], ["I", "VII", "VI", "VII"],
               ["IV", "V", "VI", "VI"]],
    "tendu": [["I", "VII", "VI", "V"], ["I", "II", "III", "IV"]],
    "lumineux": [["I", "IV", "V", "IV"], ["I", "V", "IV", "I"]],
}

#: Roue de Camelot : (classe de hauteur, mineur ?) -> code.
#: Sert au mixage harmonique : deux morceaux dont les codes sont voisins
#: s'enchaînent sans fausse note.
_CAMELOT: dict[tuple[int, bool], str] = {}


def _build_camelot() -> None:
    """Remplit la table Camelot.

    La roue avance de quinte en quinte : 8B = Do majeur, 8A = La mineur,
    puis 9B = Sol majeur, 9A = Mi mineur, etc.
    """
    major_root = 0          # Do
    minor_root = 9          # La
    for index in range(12):
        number = (7 + index) % 12 + 1
        _CAMELOT[(major_root % 12, False)] = f"{number}B"
        _CAMELOT[(minor_root % 12, True)] = f"{number}A"
        major_root = (major_root + 7) % 12
        minor_root = (minor_root + 7) % 12


_build_camelot()


# --------------------------------------------------------------------------- #
# Noms de notes
# --------------------------------------------------------------------------- #

def note_to_name(midi: int, french: bool = True,
                 with_octave: bool = True) -> str:
    """Nom d'une note MIDI : ``60`` -> ``Do3`` (ou ``C3``)."""
    try:
        value = int(midi)
    except (TypeError, ValueError):
        return ""
    names = NOTE_NAMES_FR if french else NOTE_NAMES_EN
    name = names[value % 12]
    if not with_octave:
        return name
    return f"{name}{value // 12 - OCTAVE_OFFSET}"


def name_to_note(name: str) -> int:
    """Numéro MIDI d'un nom de note. ``-1`` si le nom est incompréhensible.

    Accepte les deux langues et les deux altérations : ``Do3``, ``C3``,
    ``Mib2``, ``Eb2``, ``D#4``, ``Sol``, ``F#``.
    """
    text = str(name or "").strip().replace(" ", "")
    if not text:
        return -1

    # Octave : chiffres de fin, éventuellement négatifs.
    octave = 3
    body = text
    i = len(text)
    while i > 0 and (text[i - 1].isdigit()
                     or (text[i - 1] == "-" and i < len(text)
                         and text[i:].isdigit())):
        i -= 1
    if i < len(text):
        try:
            octave = int(text[i:])
            body = text[:i]
        except ValueError:
            body = text

    low = body.lower()
    # Français d'abord : « do », « ré »/« re », « mib »…
    french_map = {
        "do": 0, "do#": 1, "dod": 1, "reb": 1, "réb": 1,
        "re": 2, "ré": 2, "re#": 3, "ré#": 3, "mib": 3,
        "mi": 4, "fa": 5, "fa#": 6, "solb": 6,
        "sol": 7, "sol#": 8, "lab": 8,
        "la": 9, "la#": 10, "sib": 10, "si": 11, "dob": 11,
    }
    if low in french_map:
        return french_map[low] + (octave + OCTAVE_OFFSET) * 12

    # Anglais : lettre + altération.
    letters = {"c": 0, "d": 2, "e": 4, "f": 5, "g": 7, "a": 9, "b": 11}
    if low and low[0] in letters:
        pitch = letters[low[0]]
        for char in low[1:]:
            if char == "#":
                pitch += 1
            elif char == "b":
                pitch -= 1
            else:
                log.debug("nom de note incompris : %r", name)
                return -1
        return pitch % 12 + (octave + OCTAVE_OFFSET) * 12

    log.debug("nom de note incompris : %r", name)
    return -1


def frequency(midi: int, a4: float = 440.0) -> float:
    """Fréquence en hertz d'une note MIDI."""
    try:
        return float(a4) * 2.0 ** ((int(midi) - 69) / 12.0)
    except (TypeError, ValueError):
        return 0.0


# --------------------------------------------------------------------------- #
# Gammes
# --------------------------------------------------------------------------- #

def scale_names() -> list[str]:
    """Noms des gammes disponibles."""
    return list(SCALES)


def scale_notes(root: int, scale: str, octaves: int = 1) -> list[int]:
    """Notes d'une gamme, de la tonique à l'octave supérieure incluse.

    ``octaves=2`` donne deux octaves. Les notes dépassant 127 sont écartées.
    """
    intervals = SCALES.get(scale)
    if intervals is None:
        log.debug("gamme inconnue : %r, repli sur le majeur", scale)
        intervals = SCALES["majeur"]
    try:
        base = int(root)
    except (TypeError, ValueError):
        return []
    count = max(1, int(octaves))

    out: list[int] = []
    for octave in range(count):
        for step in intervals:
            note = base + step + 12 * octave
            if 0 <= note <= 127:
                out.append(note)
    final = base + 12 * count
    if 0 <= final <= 127:
        out.append(final)
    return out


def deluge_mode_notes(scale: str) -> list[int]:
    """Intervalles à écrire dans le ``<modeNotes>`` d'un morceau.

    Le Deluge attend exactement sept valeurs : c'est la contrainte de son
    écran, qui réserve sept rangées de pads par octave. Une gamme plus courte
    est complétée, une gamme plus longue est réduite en gardant les degrés les
    plus structurants.
    """
    intervals = list(SCALES.get(scale, SCALES["majeur"]))
    if len(intervals) == 7:
        return intervals

    if len(intervals) < 7:
        # Compléter avec les degrés du majeur qui manquent, pour rester dans
        # une couleur proche.
        for candidate in SCALES["majeur"]:
            if len(intervals) >= 7:
                break
            if candidate not in intervals:
                intervals.append(candidate)
        return sorted(intervals)[:7]

    # Gamme de plus de sept notes : garder tonique, seconde, tierce, quarte,
    # quinte, sixte et septième les plus proches du majeur.
    out: list[int] = []
    for target in SCALES["majeur"]:
        best = min(intervals, key=lambda v: (abs(v - target), v))
        if best not in out:
            out.append(best)
    while len(out) < 7:
        for value in intervals:
            if value not in out:
                out.append(value)
                break
    return sorted(out)[:7]


def transpose(notes: list[int], semis: int) -> list[int]:
    """Transpose une liste de notes, en écartant ce qui sort de 0..127."""
    try:
        shift = int(semis)
    except (TypeError, ValueError):
        return list(notes)
    return [n + shift for n in notes if 0 <= n + shift <= 127]


def in_scale(note: int, root: int, scale: str) -> bool:
    """Vrai si la note appartient à la gamme, quelle que soit son octave."""
    intervals = SCALES.get(scale, SCALES["majeur"])
    return (int(note) - int(root)) % 12 in intervals


def snap_to_scale(note: int, root: int, scale: str) -> int:
    """Ramène une note à la plus proche de la gamme."""
    if in_scale(note, root, scale):
        return int(note)
    intervals = SCALES.get(scale, SCALES["majeur"])
    best = int(note)
    distance = 99
    for offset in range(-6, 7):
        candidate = int(note) + offset
        if (candidate - int(root)) % 12 in intervals and abs(offset) < distance:
            best, distance = candidate, abs(offset)
    return max(0, min(127, best))


# --------------------------------------------------------------------------- #
# Accords
# --------------------------------------------------------------------------- #

def chord_names() -> list[str]:
    """Noms des accords disponibles."""
    return list(CHORDS)


def chord_notes(root: int, chord: str, inversion: int = 0,
                voicing: str = "close") -> list[int]:
    """Notes d'un accord.

    :param inversion: nombre de renversements — la basse monte à l'octave.
    :param voicing: ``close`` (serré), ``open`` (la quinte montée d'une
        octave), ``spread`` (une note sur deux montée), ``drop2`` (la
        deuxième note du haut descendue d'une octave).
    """
    intervals = CHORDS.get(chord)
    if intervals is None:
        log.debug("accord inconnu : %r, repli sur majeur", chord)
        intervals = CHORDS["maj"]
    try:
        base = int(root)
    except (TypeError, ValueError):
        return []

    notes = [base + step for step in intervals]

    for _ in range(max(0, int(inversion))):
        if len(notes) < 2:
            break
        notes = notes[1:] + [notes[0] + 12]

    if voicing == "open" and len(notes) >= 3:
        notes = [notes[0]] + notes[2:] + [notes[1] + 12]
    elif voicing == "spread":
        notes = [n + (12 if i % 2 else 0) for i, n in enumerate(notes)]
    elif voicing == "drop2" and len(notes) >= 2:
        notes = sorted(notes)
        notes[-2] -= 12

    return sorted(n for n in notes if 0 <= n <= 127)


def diatonic_chords(root: int, scale: str,
                    sevenths: bool = False) -> list[tuple[str, list[int]]]:
    """Accords construits sur chaque degré d'une gamme.

    Retourne ``[(symbole, notes)]`` — le symbole est écrit en chiffres
    romains, majuscule pour un accord majeur, minuscule pour un mineur, avec
    ``°`` pour un diminué : la notation qu'utilisent les manuels d'harmonie.
    """
    intervals = list(SCALES.get(scale, SCALES["majeur"]))
    if len(intervals) < 7:
        intervals = deluge_mode_notes(scale)
    try:
        base = int(root)
    except (TypeError, ValueError):
        return []

    out: list[tuple[str, list[int]]] = []
    size = len(intervals)
    for degree in range(min(7, size)):
        positions = [0, 2, 4, 6] if sevenths else [0, 2, 4]
        notes: list[int] = []
        for offset in positions:
            index = (degree + offset) % size
            octave = (degree + offset) // size
            notes.append(base + intervals[index] + 12 * octave)

        # Qualité déduite des intervalles réels, et non supposée.
        steps = [n - notes[0] for n in notes]
        third = steps[1] if len(steps) > 1 else 4
        fifth = steps[2] if len(steps) > 2 else 7
        roman = _ROMAN[degree] if degree < len(_ROMAN) else str(degree + 1)
        if third <= 3:
            symbol = roman.lower()
            if fifth <= 6:
                symbol += "°"
        else:
            symbol = roman
            if fifth >= 8:
                symbol += "+"
        if sevenths and len(steps) > 3:
            seventh = steps[3]
            if third > 3 and seventh == 11:
                symbol += "maj7"
            elif seventh == 10:
                symbol += "7"
            elif seventh == 9:
                symbol += "7"
        out.append((symbol, [n for n in notes if 0 <= n <= 127]))
    return out


def chord_symbol(root: int, chord: str, french: bool = True) -> str:
    """Nom lisible d'un accord : ``Do min7``, ``A maj``."""
    suffix = {"maj": "", "min": "m"}.get(chord, chord)
    return f"{note_to_name(root, french, with_octave=False)}{suffix}"


def voice_leading(a: list[int], b: list[int]) -> list[int]:
    """Réagence ``b`` pour qu'il bouge le moins possible depuis ``a``.

    Chaque note de ``b`` est déplacée à l'octave la plus proche d'une note de
    ``a``. C'est ce qui distingue un enchaînement d'accords qui coule d'une
    suite de blocs plaqués.
    """
    if not a or not b:
        return list(b)
    out: list[int] = []
    for note in b:
        best = note
        distance = 999
        for octave in range(-3, 4):
            candidate = note + 12 * octave
            if not 0 <= candidate <= 127:
                continue
            gap = min(abs(candidate - ref) for ref in a)
            if gap < distance:
                best, distance = candidate, gap
        out.append(best)
    return sorted(out)


# --------------------------------------------------------------------------- #
# Progressions
# --------------------------------------------------------------------------- #

def progression_names() -> list[str]:
    """Ambiances de progression disponibles."""
    return list(PROGRESSIONS)


def progression(root: int, scale: str, name: str = "",
                seed: int | None = None, bars: int = 4) -> list[dict]:
    """Suite d'accords sur une gamme.

    :param name: ambiance (``pop``, ``mélancolique``, ``techno``…). Vide = au
        hasard parmi toutes.
    :param bars: nombre de mesures à remplir ; la progression est répétée ou
        tronquée pour y tenir.
    :returns: ``[{'degree', 'symbol', 'notes', 'bars'}]``.

    L'enchaînement passe par :func:`voice_leading`, pour que les accords se
    suivent au lieu de sauter d'un bout à l'autre du clavier.
    """
    rng = random.Random(seed if seed is not None
                        else random.randrange(1 << 30))
    key = name if name in PROGRESSIONS else rng.choice(list(PROGRESSIONS))
    pattern = list(rng.choice(PROGRESSIONS[key]))

    chords = diatonic_chords(root, scale, sevenths=False)
    if not chords:
        return []

    wanted = max(1, int(bars))
    sequence: list[str] = []
    while len(sequence) < wanted:
        sequence.extend(pattern)
    sequence = sequence[:wanted]

    out: list[dict] = []
    previous: list[int] = []
    for degree in sequence:
        index = _degree_index(degree)
        if index is None or index >= len(chords):
            continue
        symbol, notes = chords[index]
        if previous:
            notes = voice_leading(previous, notes)
        previous = notes
        out.append({
            "degree": degree,
            "symbol": symbol,
            "notes": notes,
            "bars": 1,
            "name": chord_symbol(notes[0] if notes else root, "maj"),
        })
    return out


def _degree_index(degree: str) -> int | None:
    """Indice 0..6 d'un degré noté en chiffres romains."""
    text = str(degree or "").strip().upper()
    text = text.replace("°", "").replace("+", "")
    for suffix in ("MAJ7", "M7", "7", "9", "11", "13"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    try:
        return _ROMAN.index(text)
    except ValueError:
        log.debug("degré incompris : %r", degree)
        return None


# --------------------------------------------------------------------------- #
# Mixage harmonique
# --------------------------------------------------------------------------- #

def circle_of_fifths() -> list[tuple[str, str]]:
    """Cycle des quintes : ``[(majeure, relative mineure)]``, 12 entrées."""
    out: list[tuple[str, str]] = []
    major, minor = 0, 9
    for _ in range(12):
        out.append((note_to_name(major, french=False, with_octave=False),
                    note_to_name(minor, french=False, with_octave=False) + "m"))
        major = (major + 7) % 12
        minor = (minor + 7) % 12
    return out


def _parse_key(key_name: str) -> tuple[int, bool] | None:
    """``'C#m'`` -> ``(1, True)`` ; ``'F'`` -> ``(5, False)``."""
    text = str(key_name or "").strip()
    if not text:
        return None
    minor = False
    for suffix in ("min", "m", "Am"[1:]):
        if text.lower().endswith(suffix) and len(text) > len(suffix):
            minor = True
            text = text[: -len(suffix)]
            break
    note = name_to_note(text + "3")
    if note < 0:
        return None
    return note % 12, minor


def camelot(key_name: str) -> str:
    """Code Camelot d'une tonalité : ``'Am'`` -> ``'8A'``, ``'C'`` -> ``'8B'``.

    Retourne une chaîne vide si la tonalité n'est pas comprise.
    """
    parsed = _parse_key(key_name)
    if parsed is None:
        return ""
    return _CAMELOT.get(parsed, "")


def from_camelot(code: str) -> str:
    """Tonalité correspondant à un code Camelot. ``'8A'`` -> ``'Am'``."""
    wanted = str(code or "").strip().upper()
    for (pitch, minor), value in _CAMELOT.items():
        if value == wanted:
            name = note_to_name(pitch, french=False, with_octave=False)
            return name + ("m" if minor else "")
    return ""


def compatible_keys(key_name: str) -> list[str]:
    """Tonalités qui s'enchaînent bien avec celle-ci.

    Règle du mixage harmonique : on reste sur place, on avance ou recule d'un
    cran sur la roue, ou on bascule entre majeur et mineur relatif.
    """
    parsed = _parse_key(key_name)
    if parsed is None:
        return []
    code = _CAMELOT.get(parsed, "")
    if not code:
        return []

    number = int(code[:-1])
    letter = code[-1]
    wanted = [
        f"{number}{letter}",
        f"{number % 12 + 1}{letter}",
        f"{(number - 2) % 12 + 1}{letter}",
        f"{number}{'A' if letter == 'B' else 'B'}",
    ]
    out: list[str] = []
    for item in wanted:
        name = from_camelot(item)
        if name and name not in out:
            out.append(name)
    return out
