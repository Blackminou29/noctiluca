# -*- coding: utf-8 -*-
"""Rythmes : motifs euclidiens, grooves, swing, tables de délai.

Module arithmétique, sans dépendance. Les motifs se traduisent en notes de
clip Deluge par :meth:`Pattern.to_notes`, ce qui permet de fabriquer une
boucle depuis l'application et de l'écrire dans un morceau.

Unité de temps : une grille **interne** de 24 ticks par noire, 96 par mesure
4/4 ; un pas de double-croche vaut 6 ticks. Un morceau du Deluge compte, lui,
``96 << inputTickMagnitude`` ticks par mesure — 384 en c1.2.1 (SPEC §1.6,
corrigé le 14 octobre 2026) : :mod:`delugeapp.core.songwriter` convertit.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:                  # import circulaire à l'exécution
    from .model import Note

log = logging.getLogger(__name__)

#: Résolution du Deluge.
TICKS_PER_QUARTER = 24
TICKS_PER_BAR = 96

#: Pas par mesure par défaut : 16 doubles-croches.
STEPS_PER_BAR = 16


@dataclass
class Step:
    """Un déclenchement dans un motif.

    ``pos`` est un numéro de pas, éventuellement fractionnaire (swing,
    groove) ; ``velocity`` et ``probability`` sont des **pourcentages**,
    1 à 100. ``to_notes`` et l'export MIDI les ramènent à 1–127.
    """

    pos: int
    velocity: int = 100
    length: int = 1
    probability: int = 100
    #: Case de la grille avant tout décalage (swing, groove, humanisation).
    #: Un pas décalé de plus d'un demi-pas ne se ramène plus à sa case par
    #: un arrondi ; c'est ce champ qui permet de réappliquer un groove depuis
    #: le motif droit, et à la grille d'afficher le pas à sa place.
    grid: int | None = None


def cell(step: Step) -> int:
    """Case de grille d'un pas, décalage éventuel ignoré."""
    if step.grid is not None:
        return int(step.grid)
    return int(round(float(step.pos)))


def _remember_cell(step: Step) -> None:
    if step.grid is None:
        step.grid = int(round(float(step.pos)))


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
                index = cell(step)
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
    # Chaque cycle place exactement ``a`` (ou ``b``) coups, répartis au plus
    # juste : l'ancien calcul par division entière en mettait quatre au lieu
    # de trois pour « 3 contre 4 » sur 16 pas.
    out = [False] * count
    for pulses in (first, second):
        for i in range(pulses):
            out[int(round(i * count / float(pulses))) % count] = True
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
    # Les deux premières mesures du break des Winstons (« Amen, Brother »),
    # celles que la jungle a bouclées : grosse caisse sur 1, 1& et 3&-3a,
    # caisse claire sur 2 et 4 avec ses notes fantômes.
    "amen": {
        "Kick": "x.x.......xx....",
        "Snare": "....x..o.o..x..o",
        "Ride": "o.o.o.o.o.o.o.o.",
    },
    # Le « two-step » de la drum and bass : grosse caisse sur 1 et 3&,
    # caisse claire sur 2 et 4.
    "dnb": {
        "Kick": "x.........x.....",
        "Snare": "....x.......x...",
        "HatC": "o.o.o.o.o.o.o.o.",
        "Ride": "..o...o...o...o.",
    },
    "trance": {
        "Kick": "x...x...x...x...",
        "Clap": "....x.......x...",
        "HatC": "oo.ooo.ooo.ooo.o",
        "HatO": "..x...x...x...x.",
    },
    "psytrance": {
        "Kick": "x...x...x...x...",
        "HatC": "o.ooo.ooo.ooo.oo",
        "HatO": "..o...o...o...o.",
        "Clap": "....o.......o...",
    },
    # Le rythme motorik du krautrock (Neu!, et après lui l'école de Berlin).
    "motorik": {
        "Kick": "x.......x.x.....",
        "Snare": "....x.......x...",
        "HatC": "o.o.o.o.o.o.o.o.",
    },
    # La synthwave reprend la boîte à rythmes des années 80 : grosse caisse
    # sur 1 et 3, caisse claire massive sur 2 et 4.
    "synthwave": {
        "Kick": "x.......x.......",
        "Snare": "....x.......x...",
        "HatC": "o.o.o.o.o.o.o.o.",
        "Tambourine": "....o.......o...",
    },
    # Boom bap : le hip-hop d'échantillonneur dont vient le lo-fi.
    "boom_bap": {
        "Kick": "x......x..x.....",
        "Snare": "....x.......x...",
        "HatC": "o.o.o.o.o.o.o.oo",
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
    "trance": "trance", "psytrance": "psytrance",
    "dnb": "dnb", "jungle": "amen", "dubstep": "half_time",
    "ambient": "dub", "berlin_school": "motorik",
    "synthwave": "synthwave", "lofi": "boom_bap", "idm": "breakbeat",
    "industrial": "techno", "electro": "electro", "hardcore": "gabber",
    "downtempo": "dub", "funk": "funk", "boards_of_canada": "boom_bap",
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
                # Vélocités en pour-cent : 92 à 100 pour un coup fort, 64 à
                # 80 pour un coup faible. L'ancien 105 ± 6 dépassait 100 et
                # finissait écrêté à 127 : tous les accents se valaient.
                if cell == "x":
                    velocity = rng.randint(92, 100)
                else:
                    velocity = rng.randint(64, 80)
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

# --------------------------------------------------------------------------- #
# Variations
# --------------------------------------------------------------------------- #

#: Pistes qui font l'ossature d'un rythme : une variation ne leur retire
#: jamais un coup. Ce sont elles qui disent le genre.
BACKBONE = ("Kick", "Snare", "Clap")

#: Percussion d'appoint qu'une variation peut ajouter, par genre.
_EXTRA_PERC: dict[str, tuple[str, ...]] = {
    "house": ("Shaker", "Tambourine", "Cowbell"),
    "deep_house": ("Shaker", "ConH", "Rim"),
    "techno": ("Rim", "Cowbell", "Shaker"),
    "minimal": ("Rim", "Block", "Claves"),
    "funk": ("Tambourine", "Cowbell", "ConH"),
    "lofi": ("Shaker", "Rim", "Tambourine"),
    "electro": ("Cowbell", "Rim", "Claves"),
}

#: Genres au rythme clairsemé : des charleys en doubles-croches y
#: trahiraient le style (mesuré : la densité d'un motif dub y était
#: multipliée par 4,6).
_SPARSE_GENRES = ("ambient", "downtempo", "dubstep", "boards_of_canada")

#: Variations proposées, avec leur libellé.
VARIATIONS: dict[str, str] = {
    "fantômes": "notes fantômes de caisse claire autour des temps",
    "charleys": "charleys plus serrés, accentués à contretemps",
    "percussion": "une percussion euclidienne en plus",
    "grosse caisse": "une grosse caisse syncopée en fin de mesure",
    "ouverture": "un charleston ouvert qui respire en fin de phrase",
}


def loop(pattern: Pattern, bars: int) -> Pattern:
    """Le motif répété (ou tronqué) pour couvrir ``bars`` mesures."""
    total = max(1, int(bars)) * STEPS_PER_BAR
    out = Pattern(name=pattern.name, steps=total, ppq=pattern.ppq)
    length = max(1, int(pattern.steps))
    for track, steps in pattern.tracks.items():
        out.tracks[track] = []
        for offset in range(0, total, length):
            for step in steps:
                position = float(step.pos) + offset
                if position < total:
                    copy = Step(pos=position, velocity=step.velocity,
                                length=step.length,
                                probability=step.probability)
                    out.tracks[track].append(copy)
    return out


def variation(pattern: Pattern, genre: str = "", seed: int | None = None,
              amount: float = 0.5) -> Pattern:
    """Une variation du motif qui garde son ossature.

    Les coups de grosse caisse, de caisse claire et de clap restent tous en
    place (:data:`BACKBONE`) : c'est ce qui fait reconnaître le genre. La
    variation joue sur l'ornement — notes fantômes, charleys, une
    percussion euclidienne, une grosse caisse syncopée, un charleston
    ouvert —, d'autant plus que ``amount`` est grand (0 à 1).
    """
    rng = random.Random(seed if seed is not None
                        else random.randrange(1 << 30))
    out = _copy(straighten(pattern), " (variation)")
    total = int(out.steps)
    bars = max(1, total // STEPS_PER_BAR)
    count = 1 + int(round(max(0.0, min(1.0, float(amount))) * 2))
    possible = [v for v in VARIATIONS
                if not (v == "charleys"
                        and str(genre or "").strip().lower() in _SPARSE_GENRES)]
    choices = rng.sample(possible, k=min(count, len(possible)))
    occupied = {track: {cell(s) for s in steps}
                for track, steps in out.tracks.items()}

    def free(track: str, position: int) -> bool:
        return position not in occupied.setdefault(track, set())

    def add(track: str, position: int, velocity: int) -> None:
        if 0 <= position < total and free(track, position):
            out.add(track, Step(pos=position, velocity=velocity))
            occupied[track].add(position)

    snare = "Snare" if "Snare" in out.tracks else (
        "Clap" if "Clap" in out.tracks else "Snare")
    for choice in choices:
        if choice == "fantômes":
            for bar in range(bars):
                for offset in rng.sample([3, 6, 9, 11, 14, 15], k=2):
                    add(snare, bar * STEPS_PER_BAR + offset,
                        rng.randint(30, 48))
        elif choice == "charleys":
            hats = out.tracks.setdefault("HatC", [])
            for position in range(total):
                strong = position % 4 == 2
                if free("HatC", position) and (strong or position % 2 == 1
                                               or rng.random() < 0.5):
                    add("HatC", position,
                        rng.randint(84, 96) if strong
                        else rng.randint(46, 64))
            hats.sort(key=lambda s: float(s.pos))
        elif choice == "percussion":
            extra = [t for t in _EXTRA_PERC.get(
                str(genre or "").strip().lower(),
                ("Rim", "Shaker", "Cowbell")) if t not in out.tracks]
            track = extra[0] if extra else "Block"
            hits = euclid(rng.choice((3, 5, 7)), STEPS_PER_BAR,
                          rng.randrange(STEPS_PER_BAR))
            for bar in range(bars):
                for index, on in enumerate(hits):
                    if on:
                        add(track, bar * STEPS_PER_BAR + index,
                            rng.randint(58, 80))
        elif choice == "grosse caisse":
            for bar in range(bars):
                if bar % 2 == 1 or bars == 1:
                    add("Kick", bar * STEPS_PER_BAR + rng.choice((14, 15, 11)),
                        rng.randint(70, 86))
        elif choice == "ouverture":
            last = (bars - 1) * STEPS_PER_BAR
            add("HatO", last + rng.choice((10, 14)), rng.randint(76, 92))
    for steps in out.tracks.values():
        steps.sort(key=lambda s: float(s.pos))
    out.name = pattern.name.split(" (")[0] + " — " + ", ".join(choices)
    return out


def swing_offsets(percent: float) -> list[float]:
    """Décalages d'un swing « à la MPC », en ticks, pour 16 doubles-croches.

    Le swing d'une MPC se règle en pourcentage : la seconde double-croche de
    chaque croche tombe à ``percent`` % de la croche (50 % = droit, 66,7 % =
    ternaire exact). Une croche vaut 12 ticks à 24 par noire, d'où un retard
    de ``(2 × percent / 100 − 1) × 6`` ticks sur les pas impairs.
    """
    try:
        value = max(50.0, min(75.0, float(percent)))
    except (TypeError, ValueError):
        value = 50.0
    late = (2.0 * value / 100.0 - 1.0) * 6.0
    return [0.0 if i % 2 == 0 else round(late, 3) for i in range(16)]


#: Grooves de référence, en ticks de décalage par pas de double-croche ; un
#: décalage positif retarde le pas. Les « MPC » sont les réglages de swing
#: des échantillonneurs Akai, en pourcentage — les anciens noms (« MPC 16B »,
#: « MPC 54 »…) ne correspondaient à aucun réglage réel, et « MPC 54 »
#: avançait même certains pas.
GROOVES: dict[str, list[float]] = {
    "droit": [0.0] * 16,
    "MPC 54 %": swing_offsets(54),
    "MPC 58 %": swing_offsets(58),
    "MPC 62 %": swing_offsets(62),
    "MPC 66 %": swing_offsets(66),
    "MPC 71 %": swing_offsets(71),
    # Jeu « derrière le temps » : les contretemps traînent, de plus en plus
    # dans la croche.
    "laid-back": [0, 1, 1, 2, 0, 1, 1, 2, 0, 1, 1, 2, 0, 1, 1, 2],
    # Jeu « devant le temps » : les contretemps anticipent.
    "en avant": [0, -1, -1, -2, 0, -1, -1, -2, 0, -1, -1, -2, 0, -1, -1, -2],
}


def deluge_swing(groove: str) -> int | None:
    """Réglage de swing du Deluge équivalent à un groove MPC, ou ``None``.

    Le Deluge affiche son swing de 1 à 99, 50 étant droit : c'est le
    pourcentage lui-même.
    """
    name = str(groove or "")
    if name == "droit":
        return 50
    if name.startswith("MPC "):
        try:
            return int(round(float(name[4:].replace("%", "").strip())))
        except ValueError:
            return None
    return None


def straighten(pattern: Pattern) -> Pattern:
    """Copie du motif remise sur la grille : chaque pas à sa case entière.

    Sert à appliquer un groove **depuis le motif droit** : appliquer deux
    fois un groove l'aurait sinon cumulé.
    """
    clone = _copy(pattern)
    for steps in clone.tracks.values():
        for step in steps:
            step.pos = cell(step)
            step.grid = None
    return clone


def groove_names() -> list[str]:
    """Grooves disponibles."""
    return list(GROOVES)


def _copy(pattern: Pattern, name_suffix: str = "") -> Pattern:
    """Copie profonde d'un motif."""
    clone = Pattern(name=pattern.name + name_suffix, steps=pattern.steps,
                    ppq=pattern.ppq)
    for track, steps in pattern.tracks.items():
        clone.tracks[track] = [Step(s.pos, s.velocity, s.length, s.probability,
                                    s.grid)
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
            # La case de grille du pas, même s'il a déjà été décalé : indexer
            # avec une position fractionnaire levait une TypeError, et le
            # bouton « Appliquer » de la boîte à outils plantait au second
            # clic.
            _remember_cell(step)
            shift = offsets[cell(step) % len(offsets)] * factor
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
            _remember_cell(step)
            if cell(step) % 2 == 1:
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
            _remember_cell(step)
            if timing:
                step.pos = max(0.0, step.pos
                               + rng.gauss(0.0, float(timing)))
            if velocity:
                shift = rng.gauss(0.0, 25.0 * float(velocity))
                step.velocity = max(1, min(100,
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
