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

from ..i18n import N_, is_english, untranslated

log = logging.getLogger(__name__)

#: Noms français. Les altérations suivent l'usage : on écrit « Mib » plutôt
#: que « Ré# », parce que c'est ainsi qu'un musicien francophone les lit.
#: Les fonctions de nommage prennent les noms anglais quand l'interface
#: parle anglais (``french=None``).
NOTE_NAMES_FR = untranslated(("Do", "Do#", "Ré", "Mib", "Mi", "Fa", "Fa#",
                              "Sol", "Sol#", "La", "Sib", "Si"))
NOTE_NAMES_EN = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#",
                 "B")

#: Décalage d'octave : MIDI 60 est nommé « 3 » (convention Yamaha, celle du
#: Deluge), et non « 4 » comme en notation scientifique.
OCTAVE_OFFSET = 2

#: Gammes, par intervalles en demi-tons depuis la tonique.
#: Les noms servent de clés (morceaux, réglages) : ils restent en français
#: et se traduisent à l'affichage.
SCALES: dict[str, tuple[int, ...]] = {
    N_("majeur"): (0, 2, 4, 5, 7, 9, 11),
    N_("mineur"): (0, 2, 3, 5, 7, 8, 10),
    N_("mineur harmonique"): (0, 2, 3, 5, 7, 8, 11),
    N_("mineur mélodique"): (0, 2, 3, 5, 7, 9, 11),
    N_("dorien"): (0, 2, 3, 5, 7, 9, 10),
    N_("phrygien"): (0, 1, 3, 5, 7, 8, 10),
    N_("lydien"): (0, 2, 4, 6, 7, 9, 11),
    N_("mixolydien"): (0, 2, 4, 5, 7, 9, 10),
    N_("locrien"): (0, 1, 3, 5, 6, 8, 10),
    N_("phrygien dominant"): (0, 1, 4, 5, 7, 8, 10),
    N_("lydien b7"): (0, 2, 4, 6, 7, 9, 10),
    N_("pentatonique majeure"): (0, 2, 4, 7, 9),
    N_("pentatonique mineure"): (0, 3, 5, 7, 10),
    N_("blues"): (0, 3, 5, 6, 7, 10),
    N_("par tons"): (0, 2, 4, 6, 8, 10),
    N_("diminuée"): (0, 2, 3, 5, 6, 8, 9, 11),
    N_("diminuée demi-ton"): (0, 1, 3, 4, 6, 7, 9, 10),
    N_("hongroise mineure"): (0, 2, 3, 6, 7, 8, 11),
    N_("hijaz"): (0, 1, 4, 5, 7, 8, 10),
    N_("in sen"): (0, 1, 5, 7, 10),
    N_("hirajoshi"): (0, 2, 3, 7, 8),
    N_("kumoi"): (0, 2, 3, 7, 9),
    N_("égyptienne"): (0, 2, 5, 7, 10),
    N_("prométhée"): (0, 2, 4, 6, 9),
    # Deux gammes que propose le firmware c1.x sous ces noms.
    N_("marva"): (0, 1, 4, 6, 7, 9, 11),
    N_("arabe"): (0, 2, 4, 5, 6, 8, 10),
    N_("chromatique"): tuple(range(12)),
}

#: Nom qu'affiche le Deluge (firmware c1.2.1, ``model/scale/preset_scales.h``)
#: pour les gammes qu'il propose d'office. Les autres s'y entrent comme
#: gamme utilisateur (``USER``) : le firmware accepte n'importe quel jeu de
#: notes dans ``<modeNotes>``.
DELUGE_SCALE_NAMES: dict[str, str] = {
    "majeur": "MAJOR", "mineur": "MINOR", "dorien": "DORIAN",
    "phrygien": "PHRYGIAN", "lydien": "LYDIAN", "mixolydien": "MIXOLYDIAN",
    "locrien": "LOCRIAN", "mineur mélodique": "MELODIC MINOR",
    "mineur harmonique": "HARMONIC MINOR",
    "hongroise mineure": "HUNGARIAN MINOR", "marva": "MARVA",
    "arabe": "ARABIAN", "par tons": "WHOLE TONE", "blues": "BLUES",
    "pentatonique mineure": "PENTATONIC MINOR", "hirajoshi": "HIRAJOSHI",
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
    N_("pop"): [["I", "V", "VI", "IV"], ["I", "IV", "V", "I"],
            ["VI", "IV", "I", "V"]],
    N_("mélancolique"): [["I", "VI", "III", "VII"], ["I", "VII", "VI", "VII"],
                     ["I", "III", "VI", "IV"]],
    N_("house"): [["I", "IV", "VI", "V"], ["II", "V", "I", "VI"],
              ["I", "VI", "II", "V"]],
    N_("deep"): [["I", "III", "IV", "VI"], ["I", "VII", "III", "VI"]],
    N_("techno"): [["I", "I", "VI", "VI"], ["I", "VII", "I", "VII"],
               ["I", "VI", "VII", "VI"]],
    N_("trance"): [["VI", "IV", "I", "V"], ["I", "V", "VI", "IV"],
               ["VI", "VII", "I", "V"]],
    N_("ambient"): [["I", "IV", "I", "V"], ["I", "III", "IV", "I"],
                ["I", "VI", "IV", "I"]],
    N_("jazz"): [["II", "V", "I", "I"], ["I", "VI", "II", "V"],
             ["III", "VI", "II", "V"]],
    N_("blues"): [["I", "I", "IV", "I"], ["I", "IV", "I", "V"]],
    N_("épique"): [["VI", "VII", "I", "I"], ["I", "VII", "VI", "VII"],
               ["IV", "V", "VI", "VI"]],
    N_("tendu"): [["I", "VII", "VI", "V"], ["I", "II", "III", "IV"]],
    N_("lumineux"): [["I", "IV", "V", "IV"], ["I", "V", "IV", "I"]],
}

#: Couleurs d'accords : ce qu'on empile sur chaque degré de la gamme.
CHORD_COLORS: dict[str, str] = {
    N_("triades"): N_("trois sons : fondamentale, tierce, quinte"),
    N_("septièmes"): N_("la septième de la gamme en plus (jazz, house, "
                        "lo-fi)"),
    N_("neuvièmes"): N_("septième et neuvième ; jouées sans la "
                        "fondamentale, que tient la basse (deep house, "
                        "nappes)"),
    N_("suspendus"): N_("la tierce remplacée par la quarte ou la seconde "
                        "(trance, techno mélodique)"),
}

#: Couleur habituelle de chaque ambiance ; les autres restent en triades.
#: Le jazz, la house et la deep house vivent de septièmes et de neuvièmes :
#: en triades, une progression « jazz » sonnait comme une comptine.
AMBIANCE_COLORS: dict[str, str] = {
    "jazz": "septièmes", "house": "septièmes", "deep": "neuvièmes",
    "ambient": "neuvièmes",
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

def _french(french: bool | None) -> bool:
    """``None`` : les noms de la langue de l'interface."""
    return (not is_english()) if french is None else bool(french)


def note_to_name(midi: int, french: bool | None = None,
                 with_octave: bool = True) -> str:
    """Nom d'une note MIDI : ``60`` -> ``Do3`` (ou ``C3``)."""
    try:
        value = int(midi)
    except (TypeError, ValueError):
        return ""
    names = NOTE_NAMES_FR if _french(french) else NOTE_NAMES_EN
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


# --------------------------------------------------------------------------- #
# Orthographe selon la tonalité
# --------------------------------------------------------------------------- #

_LETTERS_FR = untranslated(("Do", "Ré", "Mi", "Fa", "Sol", "La", "Si"))
_LETTERS_EN = ("C", "D", "E", "F", "G", "A", "B")
_LETTER_PC = (0, 2, 4, 5, 7, 9, 11)
_ACCIDENTALS = {0: "", 1: "#", 2: "##", -1: "b", -2: "bb"}


def _seven_note_parent(intervals: tuple[int, ...]) -> tuple[int, ...] | None:
    """La gamme de sept notes à épeler pour ``intervals`` (elle-même ou un
    mode parent qui la contient), ou ``None``."""
    if len(set(intervals)) == 7:
        return tuple(sorted(set(intervals)))
    wanted = set(intervals)
    for parent in _PARENT_MODES:
        if wanted <= set(SCALES[parent]):
            return SCALES[parent]
    return None


def scale_spelling(root: int, scale: str,
                   french: bool | None = None) -> dict[int, str]:
    """Nom de chaque note de la gamme, épelé selon la tonalité.

    Dans une gamme de sept notes, chaque nom de note sert **une fois** :
    do mineur s'écrit Do Ré Mib Fa Sol Lab Sib, et non « Sol# » comme le
    donnait la table fixe des noms. Parmi les deux orthographes possibles de
    la tonique (Do#/Réb…), on garde celle qui demande le moins d'altérations.
    Une gamme plus courte est épelée comme son mode parent (la pentatonique
    mineure comme le mineur naturel).

    :returns: ``{classe de hauteur: nom}`` ; vide si la gamme ne s'épelle
        pas ainsi (par tons, chromatique…).
    """
    intervals = SCALES.get(scale)
    if intervals is None:
        return {}
    seven = _seven_note_parent(tuple(intervals))
    if seven is None:
        return {}
    try:
        tonic = int(root) % 12
    except (TypeError, ValueError):
        return {}
    french = _french(french)
    letters = _LETTERS_FR if french else _LETTERS_EN

    best: tuple[int, dict[int, str]] | None = None
    for start in range(7):
        names: dict[int, str] = {}
        cost = 0
        for degree, step in enumerate(sorted(seven)):
            index = (start + degree) % 7
            pc = (tonic + step) % 12
            diff = (pc - _LETTER_PC[index] + 6) % 12 - 6
            if diff not in _ACCIDENTALS:
                break
            names[pc] = letters[index] + _ACCIDENTALS[diff]
            cost += abs(diff) + (5 if abs(diff) == 2 else 0)
        else:
            # À égalité (mib mineur / ré# mineur : six altérations chacun),
            # on garde la tonique telle que l'application l'écrit partout
            # ailleurs, pour que le titre et les notes concordent.
            if names.get(tonic) != note_to_name(tonic, french,
                                                with_octave=False):
                cost += 0.5
            if best is None or cost < best[0]:
                best = (cost, names)
    if best is None:
        return {}
    wanted = {(tonic + i) % 12 for i in intervals}
    return {pc: name for pc, name in best[1].items() if pc in wanted}


def spell(midi: int, spelling: dict[int, str] | None,
          with_octave: bool = True, french: bool | None = None) -> str:
    """Nom d'une note selon une orthographe de tonalité.

    Hors de la gamme (ou sans orthographe), retombe sur
    :func:`note_to_name`. L'octave suit la lettre : Dob3 est le si juste
    sous Do3.
    """
    try:
        value = int(midi)
    except (TypeError, ValueError):
        return ""
    name = (spelling or {}).get(value % 12)
    if not name:
        return note_to_name(value, french, with_octave)
    if not with_octave:
        return name
    shift = name.count("#") - name.count("b")
    # « Sib » commence par « Si » sans être un si bémol de « S » : seules
    # les altérations finales comptent, d'où le compte sur la fin du nom.
    letters = _LETTERS_FR if _french(french) else _LETTERS_EN
    base = next((l for l in sorted(letters, key=len, reverse=True)
                 if name.startswith(l)), name)
    tail = name[len(base):]
    shift = tail.count("#") - tail.count("b")
    natural = value - shift
    return f"{name}{natural // 12 - OCTAVE_OFFSET}"


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


def deluge_scale_name(scale: str) -> str:
    """Nom de la gamme sur l'écran du Deluge, ou ``USER`` à saisir à la main."""
    return DELUGE_SCALE_NAMES.get(scale, "USER")


#: Gammes de sept notes, dans l'ordre où l'on cherche un « mode parent ».
_PARENT_MODES = untranslated((
    "majeur", "mineur", "dorien", "mixolydien", "phrygien", "lydien",
    "mineur harmonique", "mineur mélodique", "locrien"))


def deluge_mode_notes(scale: str, official: bool = False) -> list[int]:
    """Intervalles à écrire dans le ``<modeNotes>`` d'un morceau.

    **Firmware communautaire (c1.x, celui de la machine)** : la gamme telle
    quelle. Le firmware lit ``<modeNotes>`` comme une liste de longueur
    quelconque, propose lui-même des gammes de cinq et six notes, et un
    morceau de la carte (« Truc 1 ») est enregistré en pentatonique mineure à
    cinq notes. La règle des « sept notes exactement » valait pour le
    firmware officiel.

    ``official=True`` : sept valeurs, pour le firmware officiel. Une gamme
    plus courte est complétée par son **mode parent** — la gamme de sept
    notes qui la contient (mineur naturel pour la pentatonique mineure,
    phrygien pour l'in sen). L'ancienne version complétait par le majeur, et
    donnait à la pentatonique mineure à la fois la tierce mineure et la
    tierce majeure.
    """
    intervals = list(SCALES.get(scale, SCALES["majeur"]))
    if not official:
        return sorted(set(intervals))
    if len(intervals) == 7:
        return intervals

    if len(intervals) < 7:
        wanted = set(intervals)
        for parent in _PARENT_MODES:
            if wanted <= set(SCALES[parent]):
                return list(SCALES[parent])
        # Aucune gamme de sept notes ne la contient (par tons, blues) :
        # compléter par les degrés du majeur, faute de mieux.
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
            elif symbol.endswith("°") and seventh == 10:
                # Demi-diminué : la notation usuelle est « ø7 », pas « °7 »
                # qui désigne le diminué (septième diminuée).
                symbol = symbol[:-1] + "ø7"
            elif seventh in (9, 10):
                symbol += "7"
        out.append((symbol, [n for n in notes if 0 <= n <= 127]))
    return out


#: Suffixe d'un accord dans son nom usuel : ``Lam``, ``Sol7``, ``Si°``.
_CHORD_SUFFIX = {"maj": "", "min": "m", "dim": "°", "aug": "+",
                 "m7b5": "ø7", "dim7": "°7", "mMaj7": "m(maj7)"}


def chord_symbol(root: int, chord: str, french: bool | None = None,
                 spelling: dict[int, str] | None = None) -> str:
    """Nom lisible d'un accord : ``Lam``, ``Sol7``, ``Siø7``, ``Lab``.

    :param spelling: orthographe de la tonalité (:func:`scale_spelling`),
        pour que le VI de do mineur s'appelle Lab et non Sol#.
    """
    suffix = _CHORD_SUFFIX.get(chord, chord)
    return f"{spell(root, spelling, with_octave=False, french=french)}{suffix}"


def chord_quality(notes: list[int]) -> str:
    """Nom d'accord (clé de :data:`CHORDS`) d'après les intervalles réels.

    Les notes sont prises **depuis la fondamentale** : ``[57, 60, 64]``
    donne ``min``. Un empilement inconnu rend ``maj`` ou ``min`` selon la
    tierce.
    """
    if not notes:
        return "maj"
    root = notes[0]
    shape = tuple(sorted({(n - root) % 12 for n in notes}))
    for name, intervals in CHORDS.items():
        if tuple(sorted({i % 12 for i in intervals})) == shape:
            return name
    return "min" if 3 in shape and 4 not in shape else "maj"


def name_chord(notes) -> str:
    """Nom de l'accord formé par des notes tenues, quel que soit son
    renversement : ``[64, 67, 72]`` donne ``Do``. Chaîne vide s'il y a moins
    de trois classes de notes ou si l'empilement n'est pas un accord connu.

    La basse est essayée en premier comme fondamentale : ``Do/Mi`` se lit
    ``Do`` et non ``Mim♭6``.
    """
    try:
        valeurs = sorted({int(n) for n in notes})
    except (TypeError, ValueError):
        return ""
    classes = []
    for note in valeurs:
        if note % 12 not in classes:
            classes.append(note % 12)
    if len(classes) < 3:
        return ""
    formes = {name: tuple(sorted({i % 12 for i in intervals}))
              for name, intervals in CHORDS.items()}
    for fondamentale in classes:
        forme = tuple(sorted({(c - fondamentale) % 12 for c in classes}))
        for name, intervals in formes.items():
            if intervals == forme:
                return chord_symbol(60 + fondamentale, name)
    return ""


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


def colored_chord(root: int, scale: str, degree: int,
                  color: str = "triades") -> tuple[list[int], list[int], str]:
    """Accord diatonique d'un degré (0 à 6), dans la couleur demandée.

    :returns: ``(empilement complet, notes à jouer, suffixe du degré)``.
        L'empilement complet sert à nommer l'accord et à trouver sa basse :
        une neuvième se joue **sans sa fondamentale** — tierce, quinte,
        septième, neuvième, le voicing des pianistes, la basse tenant la
        fondamentale —, mais c'est avec elle qu'on la reconnaît (``m9``).

    Une couleur qui ne tient pas dans la gamme retombe sur la triade : pas
    de neuvième mineure (le ii de la mineur porterait un si-do grinçant),
    pas de quarte augmentée déguisée en « sus4 ». Les gammes de moins de
    sept notes restent en triades.
    """
    intervals = list(SCALES.get(scale, SCALES["majeur"]))
    if len(intervals) < 7:
        intervals = deluge_mode_notes(scale)
    size = len(intervals)
    base = int(root)

    def note(offset: int) -> int:
        position = degree + offset
        return base + intervals[position % size] + 12 * (position // size)

    triad = [note(0), note(2), note(4)]
    if size < 7 or color not in CHORD_COLORS or color == "triades":
        return triad, triad, ""
    low = triad[0]
    if color == "septièmes":
        full = triad + [note(6)]
        return full, full, "7"
    if color == "neuvièmes":
        seventh, ninth = note(6), note(8)
        if ninth - low == 14:
            return (triad + [seventh, ninth],
                    [triad[1], triad[2], seventh, ninth], "9")
        full = triad + [seventh]
        return full, full, "7"
    # Suspendus : quarte juste ou seconde majeure, sur une quinte juste.
    if triad[2] - low != 7:
        return triad, triad, ""
    sus4 = note(3) - low == 5
    sus2 = note(1) - low == 2
    if sus4 and (degree in (0, 4) or not sus2):
        chord = [low, note(3), triad[2]]
        return chord, chord, "sus4"
    if sus2:
        chord = [low, note(1), triad[2]]
        return chord, chord, "sus2"
    return triad, triad, ""


def progression(root: int, scale: str, name: str = "",
                seed: int | None = None, bars: int = 4,
                color: str = "") -> list[dict]:
    """Suite d'accords sur une gamme.

    :param name: ambiance (``pop``, ``mélancolique``, ``techno``…). Vide = au
        hasard parmi toutes.
    :param bars: nombre de mesures à remplir ; la progression est répétée ou
        tronquée pour y tenir.
    :param color: couleur des accords (:data:`CHORD_COLORS`) ; vide = celle
        de l'ambiance (:data:`AMBIANCE_COLORS`), triades à défaut.
    :returns: ``[{'degree', 'symbol', 'notes', 'bars', 'root', 'quality',
        'name', 'bass', 'color'}]``.

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
    colour = color if color in CHORD_COLORS else AMBIANCE_COLORS.get(
        key, "triades")
    sevenths = diatonic_chords(root, scale, sevenths=True)

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
        entry = _chord_entry(root, scale, index, colour, previous,
                             chords, sevenths, degree)
        previous = entry["notes"]
        out.append(entry)
    return out


#: Fonction harmonique de chaque degré (0 = I) : tonique, sous-dominante,
#: dominante. Deux accords de même fonction se remplacent sans casser le
#: sens de la phrase — le vi pour le I, le ii pour le IV, le vii° pour le V.
FUNCTIONS: dict[int, str] = {0: N_("tonique"), 2: N_("tonique"),
                             5: N_("tonique"), 1: N_("sous-dominante"),
                             3: N_("sous-dominante"), 4: N_("dominante"),
                             6: N_("dominante")}


def _chord_entry(root: int, scale: str, index: int, colour: str,
                 previous: list[int], chords=None, sevenths=None,
                 degree: str = "") -> dict:
    """Un accord de progression, tout décrit (voir :func:`progression`)."""
    chords = chords or diatonic_chords(root, scale, sevenths=False)
    sevenths = sevenths or diatonic_chords(root, scale, sevenths=True)
    symbol, position = chords[index]
    full, played, suffix = colored_chord(root, scale, index, colour)
    if suffix in ("7", "9") and index < len(sevenths):
        # Le degré noté comme dans les manuels : ii7, Imaj7, iiø7 ; la
        # neuvième remplace le 7 quand elle a pu être ajoutée.
        symbol = sevenths[index][0]
        if suffix == "9" and symbol.endswith("7"):
            symbol = symbol[:-1] + "9"
    elif suffix:
        symbol = symbol.upper() + suffix
    if played:
        position = played
    # Fondamentale et qualité se lisent sur l'accord en position serrée,
    # **avant** la conduite des voix : l'ancien nom venait de la note la
    # plus grave une fois les voix déplacées, et le VI de la mineur
    # (fa-la-do) s'appelait « La ».
    chord_root = (full or position or [int(root)])[0]
    quality = chord_quality(full or position)
    notes = voice_leading(previous, position) if previous else position
    return {
        "degree": degree or _ROMAN[index],
        "symbol": symbol,
        "notes": notes,
        "bars": 1,
        "root": chord_root,
        "quality": quality,
        "name": chord_symbol(chord_root, quality,
                             spelling=scale_spelling(root, scale)),
        # Basse : la fondamentale dans l'octave 1 (MIDI 36 à 47).
        "bass": 36 + (chord_root % 12),
        "color": colour,
        "function": FUNCTIONS.get(index, ""),
    }


def substitute(progression: list[dict], position: int, root: int,
               scale: str, seed: int | None = None) -> list[dict]:
    """La progression où l'accord ``position`` est remplacé par un autre.

    Le remplaçant a la **même fonction harmonique** (:data:`FUNCTIONS`) —
    le vi à la place du I, le ii à la place du IV —, garde la couleur de la
    progression, et n'est égal ni à l'accord remplacé ni à ses voisins
    immédiats. Ses voix suivent l'accord précédent, et celles de l'accord
    suivant sont reconduites depuis lui. Une gamme de moins de sept notes,
    sans fonctions établies, prend n'importe quel autre degré.

    Rend une **nouvelle** liste ; l'originale n'est pas touchée.
    """
    out = [dict(chord) for chord in progression or []]
    if not 0 <= int(position) < len(out):
        return out
    chords = diatonic_chords(root, scale, sevenths=False)
    if not chords:
        return out
    sevenths = diatonic_chords(root, scale, sevenths=True)
    rng = random.Random(seed if seed is not None
                        else random.randrange(1 << 30))
    current = _degree_index(out[position].get("degree", ""))
    neighbours = {_degree_index(out[i].get("degree", ""))
                  for i in (position - 1, position + 1) if 0 <= i < len(out)}
    size = len(chords)
    function = FUNCTIONS.get(current) if size >= 7 else None
    candidates = [i for i in range(size)
                  if i != current and i not in neighbours
                  and (function is None or FUNCTIONS.get(i) == function)]
    if not candidates:
        candidates = [i for i in range(size)
                      if i != current
                      and (function is None or FUNCTIONS.get(i) == function)]
    if not candidates:
        return out
    index = rng.choice(candidates)
    colour = out[position].get("color", "triades")
    previous = out[position - 1]["notes"] if position > 0 else []
    out[position] = _chord_entry(root, scale, index, colour, previous,
                                 chords, sevenths)
    if position + 1 < len(out):
        following = _degree_index(out[position + 1].get("degree", ""))
        if following is not None and following < size:
            out[position + 1] = _chord_entry(
                root, scale, following, out[position + 1].get("color", colour),
                out[position]["notes"], chords, sevenths,
                out[position + 1].get("degree", ""))
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
