# -*- coding: utf-8 -*-
"""Rythmes : motifs euclidiens, grooves, swing, tables de délai.

Module arithmétique, sans dépendance. Les motifs se traduisent en notes de
clip Deluge par :meth:`Pattern.to_notes`, ce qui permet de fabriquer une
boucle depuis l'application et de l'écrire dans un morceau.

Unité de temps : le **tick** du Deluge, 24 par noire, donc 96 par mesure 4/4
(cf. SPEC §1.6). Un pas de double-croche vaut 6 ticks.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

#: Résolution du Deluge.
TICKS_PER_QUARTER = 24
TICKS_PER_BAR = 96

#: Pas par mesure par défaut : 16 doubles-croches.
STEPS_PER_BAR = 16


@dataclass
class Step:
    """Un déclenchement dans un motif. ``pos`` est un numéro de pas."""

    pos: int
    velocity: int = 100
    length: int = 1
    probability: int = 100


@dataclass
class Pattern:
    """Un motif rythmique : plusieurs pistes nommées sur une grille de pas."""

    name: str = ""
    steps: int = STEPS_PER_BAR
    ppq: int = TICKS_PER_QUARTER
    tracks: dict[str, list[Step]] = field(default_factory=dict)

    @property
    def ticks_per_step(self) -> int:
        """Durée d'un pas en ticks.

        Déduite du nombre de pas par mesure : 16 pas donnent 6 ticks, 32 pas
        en donnent 3.
        """
        per_bar = max(1, self.steps / self.bars) if self.bars else self.steps
        return max(1, int(round(TICKS_PER_BAR / per_bar)))

    @property
    def bars(self) -> float:
        """Longueur du motif en mesures."""
        return max(1.0, self.steps / float(STEPS_PER_BAR))

    @property
    def length_ticks(self) -> int:
        """Longueur totale en ticks."""
        return self.steps * self.ticks_per_step

    def add(self, track: str, step: Step) -> None:
        """Ajoute un déclenchement à une piste."""
        self.tracks.setdefault(track, []).append(step)

    def track_names(self) -> list[str]:
        """Pistes du motif, dans l'ordre d'insertion."""
        return list(self.tracks)

    def to_notes(self, row_map: dict[str, int]) -> dict[int, list[Note]]:
        """Traduit le motif en notes de clip Deluge.

        :param row_map: ``{nom de piste: numéro de rangée}`` — pour un clip
            de kit, la rangée est l'index du pad ; pour un clip mélodique,
            c'est la note MIDI.
        :returns: ``{rangée: [Note]}``, prêt à être posé dans un
            :class:`~delugeapp.core.model.NoteRow`.
        """
        from .model import Note

        out: dict[int, list[Note]] = {}
        per_step = self.ticks_per_step
        for track, steps in self.tracks.items():
            row = row_map.get(track)
            if row is None:
                log.debug("piste sans rangée associée : %r", track)
                continue
            notes: list[Note] = []
            for step in sorted(steps, key=lambda s: s.pos):
                # ``pos`` peut être fractionnaire : le swing et les grooves
                # décalent les pas d'une fraction de pas. Tronquer ici
                # effacerait précisément l'effet qu'ils viennent d'appliquer,
                # d'où l'arrondi sur le produit et non sur le pas.
                pos = int(round(float(step.pos) * per_step))
                pos = max(0, min(pos, self.length_ticks - 1))
                length = max(1, int(round(float(step.length) * per_step)))
                velocity = max(1, min(127, int(step.velocity * 127 // 100)))
                # Le Deluge code la probabilité de 0 à 20 par pas de 5 %.
                condition = (20 if step.probability >= 100
                             else max(0, min(20, int(step.probability / 5))))
                notes.append(Note(pos=pos, length=length, velocity=velocity,
                                  condition=condition, lift=64))
            out[int(row)] = notes
        return out

    def ascii(self) -> str:
        """Représentation texte du motif, une ligne par piste.

        ``x`` = coup fort, ``o`` = coup faible, ``?`` = probabiliste,
        ``.`` = silence. C'est la façon la plus rapide de vérifier un rythme
        en lisant un journal ou un test.
        """
        if not self.tracks:
            return "(motif vide)"
        width = max((len(name) for name in self.tracks), default=0)
        lines: list[str] = []
        for track, steps in self.tracks.items():
            cells = ["."] * self.steps
            for step in steps:
                # ``pos`` peut être fractionnaire après un groove ou un
                # swing : il faut l'arrondir à la case la plus proche, comme
                # le fait ``to_notes``. Sans cela, indexer la liste lève.
                index = int(round(float(step.pos)))
                if not 0 <= index < self.steps:
                    continue
                if step.probability < 100:
                    cells[index] = "?"
                elif step.velocity >= 90:
                    cells[index] = "x"
                else:
                    cells[index] = "o"
            # Un séparateur tous les quatre pas : la lecture devient immédiate.
            grouped = "".join(
                "".join(cells[i:i + 4]) + ("|" if i + 4 < self.steps else "")
                for i in range(0, self.steps, 4))
            lines.append(f"{track:>{width}} |{grouped}")
        return "\n".join(lines)


def bars_to_ticks(bars: float) -> int:
    """Convertit des mesures 4/4 en ticks Deluge."""
    try:
        return int(round(float(bars) * TICKS_PER_BAR))
    except (TypeError, ValueError):
        return TICKS_PER_BAR


# --------------------------------------------------------------------------- #
# Motifs euclidiens
# --------------------------------------------------------------------------- #

def euclid(pulses: int, steps: int, rotate: int = 0) -> list[bool]:
    """Motif euclidien : ``pulses`` coups répartis le plus régulièrement
    possible sur ``steps`` pas.

    Implémente l'algorithme de Bjorklund, celui qui produit les rythmes
    traditionnels : ``E(3,8)`` donne ``x..x..x.``, le tresillo cubain, et
    ``E(5,8)`` le cinquillo.

    :param rotate: décale le motif vers la gauche, ce qui change le point de
        départ sans changer la figure.
    """
    try:
        k, n = int(pulses), int(steps)
    except (TypeError, ValueError):
        return []
    if n <= 0:
        return []
    k = max(0, min(k, n))
    if k == 0:
        return [False] * n
    if k == n:
        return [True] * n

    # Bjorklund : on répartit k groupes « coup » parmi n-k groupes « silence »
    # par divisions euclidiennes successives.
    groups_a: list[list[bool]] = [[True] for _ in range(k)]
    groups_b: list[list[bool]] = [[False] for _ in range(n - k)]

    while len(groups_b) > 1:
        pairs = min(len(groups_a), len(groups_b))
        merged = [groups_a[i] + groups_b[i] for i in range(pairs)]
        if len(groups_a) > pairs:
            rest = groups_a[pairs:]
        else:
            rest = groups_b[pairs:]
        groups_a, groups_b = merged, rest
        if not groups_b:
            break

    pattern = [cell for group in groups_a + groups_b for cell in group]
    if rotate:
        shift = int(rotate) % n
        pattern = pattern[shift:] + pattern[:shift]
    return pattern


def euclid_pattern(spec: dict[str, tuple[int, int, int]]) -> Pattern:
    """Motif à plusieurs pistes, chacune décrite par ``(coups, pas, rotation)``.

    Exemple : ``{'Kick': (4, 16, 0), 'HatC': (7, 16, 2)}``.
    """
    # Les spécifications sont validées d'abord : sans cela, une entrée
    # mal formée faisait échouer le calcul du nombre de pas et donc tout le
    # motif, au lieu d'être simplement ignorée.
    clean: dict[str, tuple[int, int, int]] = {}
    for track, value in (spec or {}).items():
        try:
            clean[track] = (int(value[0]), int(value[1]), int(value[2]))
        except (TypeError, ValueError, IndexError, KeyError):
            log.debug("spécification euclidienne invalide pour %r : %r",
                      track, value)

    steps = max((count for _p, count, _r in clean.values()), default=16)
    steps = max(1, steps)
    pattern = Pattern(name="Euclidien", steps=steps)
    for track, (pulses, count, rotation) in clean.items():
        cells = euclid(pulses, count, rotation)
        # Une piste plus courte que le motif est répétée pour le remplir.
        for index in range(steps):
            if cells and cells[index % len(cells)]:
                pattern.add(track, Step(pos=index, velocity=100))
    return pattern


def polyrhythm(a: int, b: int, steps: int) -> list[bool]:
    """Superposition de deux pulsations : vrai là où l'une des deux tombe.

    ``polyrhythm(3, 4, 12)`` marque les pas des deux cycles, ce qui donne la
    figure caractéristique du 3 contre 4.
    """
    try:
        first, second, count = int(a), int(b), int(steps)
    except (TypeError, ValueError):
        return []
    if count <= 0 or first <= 0 or second <= 0:
        return [False] * max(0, count)
    out = [False] * count
    for index in range(count):
        if index % max(1, count // first) == 0 or \
           index % max(1, count // second) == 0:
            out[index] = True
    return out


# --------------------------------------------------------------------------- #
# Motifs idiomatiques par genre
# --------------------------------------------------------------------------- #

#: Motifs écrits à la main, sur 16 pas. ``x`` coup fort, ``o`` coup faible,
#: ``.`` silence. Ce sont les figures que l'on reconnaît à l'oreille : les
#: produire par tirage au sort donnerait des rythmes corrects mais sans
#: identité.
_BEATS: dict[str, dict[str, str]] = {
    "four_on_floor": {
        "Kick": "x...x...x...x...",
        "Clap": "....x.......x...",
        "HatC": "..o...o...o...o.",
        "HatO": "....o.......o...",
    },
    "techno": {
        "Kick": "x...x...x...x...",
        "Clap": "....x.......x...",
        "HatC": "..o.o.o.o.o.o.o.",
        "Rim": ".......o.......o",
    },
    "house": {
        "Kick": "x...x...x...x...",
        "Clap": "....x.......x...",
        "HatO": "..o...o...o...o.",
        "Shaker": ".o.o.o.o.o.o.o.o",
    },
    "breakbeat": {
        "Kick": "x.....x...x.....",
        "Snare": "....x.......x...",
        "HatC": "..o...o...o...o.",
    },
    "amen": {
        "Kick": "x.....x.........",
        "Snare": "....x..o..x.o...",
        "Ride": "o.o.o.o.o.o.o.o.",
    },
    "half_time": {
        "Kick": "x.......x.......",
        "Snare": "........x.......",
        "HatC": "..o...o...o...o.",
    },
    "gabber": {
        "Kick": "x.x.x.x.x.x.x.x.",
        "Clap": "....x.......x...",
        "Crash": "x...............",
    },
    "electro": {
        "Kick": "x..x..x...x.....",
        "Snare": "....x.......x...",
        "HatC": "..o...o...o...o.",
        "Cowbell": "..o..o..o..o..o.",
    },
    "dub": {
        "Kick": "x.......x.......",
        "Snare": "............x...",
        "HatO": "....o.......o...",
    },
    "trap": {
        "Kick": "x.....x...x.....",
        "Snare": "........x.......",
        "HatC": "oooooooooooooooo",
    },
    "funk": {
        "Kick": "x..x....x..x....",
        "Snare": "....x..o....x..o",
        "HatC": "o.o.o.o.o.o.o.o.",
    },
}

#: Motif conseillé par genre.
GENRE_BEATS: dict[str, str] = {
    "acid": "four_on_floor", "techno": "techno", "detroit": "four_on_floor",
    "minimal": "techno", "house": "house", "deep_house": "house",
    "trance": "four_on_floor", "psytrance": "four_on_floor",
    "dnb": "amen", "jungle": "amen", "dubstep": "half_time",
    "ambient": "dub", "berlin_school": "four_on_floor",
    "synthwave": "four_on_floor", "lofi": "breakbeat", "idm": "breakbeat",
    "industrial": "techno", "electro": "electro", "hardcore": "gabber",
    "downtempo": "dub", "funk": "funk", "boards_of_canada": "breakbeat",
}

#: Remplissages ajoutés en fin de motif quand ``fills=True``.
_FILL_POSITIONS = (14, 15, 13, 11)


def beat_names() -> list[str]:
    """Motifs rythmiques disponibles."""
    return list(_BEATS)


def genre_beat(genre: str, bars: int = 1, seed: int | None = None,
               fills: bool = True) -> Pattern:
    """Rythme idiomatique d'un genre, étendu sur ``bars`` mesures.

    :param fills: ajoute une variation discrète à la dernière mesure, ce qui
        évite la boucle parfaitement identique.
    """
    rng = random.Random(seed if seed is not None
                        else random.randrange(1 << 30))
    key = GENRE_BEATS.get(str(genre or "").strip().lower(), "four_on_floor")
    grid = _BEATS.get(key, _BEATS["four_on_floor"])

    count = max(1, int(bars))
    steps = STEPS_PER_BAR * count
    pattern = Pattern(name=f"{key} ({count} mesure{'s' if count > 1 else ''})",
                      steps=steps)

    for track, row in grid.items():
        for bar in range(count):
            for index, cell in enumerate(row[:STEPS_PER_BAR]):
                if cell == ".":
                    continue
                pos = bar * STEPS_PER_BAR + index
                velocity = 105 if cell == "x" else 78
                # Légère variation de vélocité : un rythme aux vélocités
                # strictement égales sonne mécanique.
                velocity = max(1, min(127, velocity + rng.randint(-6, 6)))
                pattern.add(track, Step(pos=pos, velocity=velocity))

    if fills and count >= 1:
        _add_fill(pattern, grid, rng, count)
    return pattern


def _add_fill(pattern: Pattern, grid: dict[str, str], rng: random.Random,
              bars: int) -> None:
    """Ajoute quelques coups en fin de motif, de façon mesurée."""
    candidates = [t for t in grid if t in ("Snare", "Clap", "Rim", "TomL",
                                           "TomM", "TomH", "HatO")]
    if not candidates:
        candidates = list(grid)
    track = rng.choice(candidates)
    last_bar = (bars - 1) * STEPS_PER_BAR
    existing = {s.pos for s in pattern.tracks.get(track, ())}
    for offset in _FILL_POSITIONS[:rng.randint(1, 2)]:
        pos = last_bar + offset
        if pos < pattern.steps and pos not in existing:
            pattern.add(track, Step(pos=pos, velocity=rng.randint(70, 95),
                                    probability=rng.choice([100, 100, 75])))


# --------------------------------------------------------------------------- #
# Expression
# --------------------------------------------------------------------------- #

#: Grooves de référence, en ticks de décalage par pas de double-croche.
#: Reprise des grilles des échantillonneurs MPC, qui sont la référence du
#: domaine : un décalage positif retarde le pas.
GROOVES: dict[str, list[int]] = {
    "droit": [0] * 16,
    "MPC 16A": [0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1],
    "MPC 16B": [0, 2, 0, 2, 0, 2, 0, 2, 0, 2, 0, 2, 0, 2, 0, 2],
    "MPC 16C": [0, 3, 0, 3, 0, 3, 0, 3, 0, 3, 0, 3, 0, 3, 0, 3],
    "MPC 54": [0, -1, 1, 0, 0, -1, 1, 0, 0, -1, 1, 0, 0, -1, 1, 0],
    "MPC 62": [0, 2, -1, 1, 0, 2, -1, 1, 0, 2, -1, 1, 0, 2, -1, 1],
    "MPC 66": [0, 3, -1, 2, 0, 3, -1, 2, 0, 3, -1, 2, 0, 3, -1, 2],
    "laid-back": [0, 1, 1, 2, 0, 1, 1, 2, 0, 1, 1, 2, 0, 1, 1, 2],
    "en avant": [0, -1, -1, -2, 0, -1, -1, -2, 0, -1, -1, -2, 0, -1, -1, -2],
}


def groove_names() -> list[str]:
    """Grooves disponibles."""
    return list(GROOVES)


def _copy(pattern: Pattern, name_suffix: str = "") -> Pattern:
    """Copie profonde d'un motif."""
    clone = Pattern(name=pattern.name + name_suffix, steps=pattern.steps,
                    ppq=pattern.ppq)
    for track, steps in pattern.tracks.items():
        clone.tracks[track] = [Step(s.pos, s.velocity, s.length, s.probability)
                               for s in steps]
    return clone


def apply_groove(pattern: Pattern, groove: str,
                 strength: float = 1.0) -> Pattern:
    """Applique un groove en décalant les pas.

    Le décalage est stocké dans ``Step.pos`` sous forme fractionnaire : il
    sera converti en ticks par :meth:`Pattern.to_notes`. ``strength`` permet
    de doser l'effet entre 0 (droit) et 1 (grille complète).
    """
    offsets = GROOVES.get(groove)
    if offsets is None:
        log.debug("groove inconnu : %r", groove)
        return _copy(pattern)
    factor = max(0.0, min(1.0, float(strength)))
    clone = _copy(pattern, "")
    per_step = pattern.ticks_per_step
    for steps in clone.tracks.values():
        for step in steps:
            shift = offsets[step.pos % len(offsets)] * factor
            # On reste en pas : le décalage est une fraction de pas.
            step.pos = step.pos + shift / per_step
    return clone


def swing(pattern: Pattern, amount: float) -> Pattern:
    """Retarde les pas impairs : le swing, mesuré de 0 à 1.

    À 0 le motif est droit ; à 1 les doubles-croches impaires tombent au
    tiers suivant, ce qui donne le ternaire.
    """
    factor = max(0.0, min(1.0, float(amount)))
    clone = _copy(pattern)
    if factor <= 0:
        return clone
    for steps in clone.tracks.values():
        for step in steps:
            if int(step.pos) % 2 == 1:
                step.pos = step.pos + factor / 3.0
    return clone


def humanize(pattern: Pattern, timing: float = 0.0, velocity: float = 0.0,
             seed: int | None = None) -> Pattern:
    """Introduit de l'imprécision, pour que le motif ne sonne pas mécanique.

    :param timing: ampleur du flottement, en fraction de pas (0,1 = un
        dixième de pas).
    :param velocity: ampleur de la variation de vélocité, de 0 à 1.
    """
    rng = random.Random(seed if seed is not None
                        else random.randrange(1 << 30))
    clone = _copy(pattern)
    for steps in clone.tracks.values():
        for step in steps:
            if timing:
                step.pos = max(0.0, step.pos
                               + rng.gauss(0.0, float(timing)))
            if velocity:
                shift = rng.gauss(0.0, 25.0 * float(velocity))
                step.velocity = max(1, min(127,
                                           int(round(step.velocity + shift))))
    return clone


# --------------------------------------------------------------------------- #
# Tables de temps
# --------------------------------------------------------------------------- #

#: Divisions rythmiques usuelles, en fraction de ronde.
_DIVISIONS = (
    ("1/1", 4.0), ("1/2", 2.0), ("1/4", 1.0), ("1/8", 0.5),
    ("1/16", 0.25), ("1/32", 0.125),
)


def delay_times(bpm: float) -> list[dict]:
    """Table des temps de délai et de LFO pour un tempo donné.

    Pour chaque division : la durée en millisecondes, la fréquence
    correspondante en hertz, et les variantes pointée et triolet. C'est la
    table qu'un producteur recopie à la main sur une calculatrice.
    """
    try:
        tempo = float(bpm)
    except (TypeError, ValueError):
        tempo = 120.0
    if tempo <= 0:
        tempo = 120.0
    quarter_ms = 60000.0 / tempo

    out: list[dict] = []
    for label, quarters in _DIVISIONS:
        ms = quarter_ms * quarters
        out.append({
            "div": label,
            "ms": round(ms, 2),
            "hz": round(1000.0 / ms, 4) if ms > 0 else 0.0,
            "dotted_ms": round(ms * 1.5, 2),
            "triplet_ms": round(ms * 2.0 / 3.0, 2),
        })
    return out
