# -*- coding: utf-8 -*-
"""Variations d'un clip : la même idée, autrement.

Un morceau ne se fait pas d'une boucle répétée. Mesuré sur les 136 morceaux
de l'utilisateur : 400 pistes sur 472 n'ont qu'un clip, et la moitié des
morceaux n'ont qu'une section. Ce qui manque pour passer de la boucle au
morceau, ce sont les **variations** : la même basse qui anticipe, la même
mélodie qui répond, la batterie qui se tait pour la cassure ou roule avant
le refrain.

Ce module transforme une partie (:class:`~delugeapp.core.accomp.NoteEvent`,
en pas de double-croche) ou un motif de batterie
(:class:`~delugeapp.core.rhythm.Pattern`) en une variation reconnaissable :

* **dans la gamme** — une note ajoutée ou déplacée en est toujours ;
* **sur l'harmonie** — quand la progression est connue, les temps forts
  restent sur une note de l'accord ;
* **apparentée** — une variation garde une part de l'original
  (:func:`similarity`) : sinon ce serait un autre clip ;
* **reproductible** — même graine, même variation ;
* **jouable** — sans note qui en chevauche une autre de même hauteur, ce
  que le firmware ignorerait (``NoteRow::readFromFile``).

Module arithmétique, sans dépendance : ni carte, ni audio, ni Qt.
"""

from __future__ import annotations

import logging
import random

from ..i18n import N_, untranslated
from . import rhythm, theory
from .accomp import STEPS_PER_BAR, NoteEvent

log = logging.getLogger(__name__)

__all__ = [
    "MELODIC", "DRUMS", "PARTS", "vary_part", "vary_drums", "similarity",
    "kinship", "drum_similarity", "clean_part", "monophonic", "chord_at",
]

#: Parties mélodiques connues (les clés d'``accomp``).
PARTS = ("Basse", "Accords", "Arpège", "Mélodie")

#: Variations d'une partie mélodique, avec ce qu'elles font.
MELODIC: dict[str, str] = {
    N_("rythme"): N_("le même dessin, décalé : anticipations et notes "
                     "répétées"),
    N_("notes"): N_("le même rythme, d'autres notes : voisines, quinte, "
                    "renversements"),
    N_("plus"): N_("plus de notes : notes de passage, levées, relances"),
    N_("moins"): N_("moins de notes : les temps forts, tenus"),
    N_("réponse"): N_("la première moitié gardée, la seconde lui répond"),
    N_("octave"): N_("des sauts d'octave, ou le registre déplacé"),
    N_("fin"): N_("la dernière mesure prépare le retour au début"),
}

#: Variations d'une batterie.
DRUMS: dict[str, str] = {
    N_("ornements"): N_("notes fantômes, charleys, percussion ; l'ossature "
                        "intacte"),
    N_("remplissage"): N_("un roulement sur la fin de la dernière mesure"),
    N_("légère"): N_("ni caisse claire ni clap : pour une intro ou une fin"),
    N_("cassure"): N_("sans grosse caisse : la tension retombe"),
    N_("doublée"): N_("charleys deux fois plus serrés"),
    N_("demi-temps"): N_("caisse claire sur le troisième temps : le tempo "
                         "semble ralentir"),
    N_("montée"): N_("un roulement qui s'accélère jusqu'à la fin"),
}

#: Pistes gardées par une batterie légère (celles de l'esquisse).
_LIGHT = ("Kick", "HatC", "HatO", "Shaker", "Ride", "Rim")
#: Registre où une partie peut aller, en notes MIDI.
_RANGE = {"Basse": (24, 64), "Accords": (40, 88), "Arpège": (40, 100),
          "Mélodie": (48, 96)}


# --------------------------------------------------------------------------- #
# Outils
# --------------------------------------------------------------------------- #

def _rng(seed, how: str, part: str) -> random.Random:
    # La variation et la partie entrent dans la graine : la graine 3 ne fait
    # pas les mêmes choix pour une basse et pour une mélodie.
    return random.Random(f"{seed if seed is not None else 0}|{how}|{part}")


def _copy(events) -> list[NoteEvent]:
    return [NoteEvent(float(e.start), float(e.length), int(e.note),
                      int(e.velocity)) for e in events or ()]


def _classes(events, root: int | None, scale: str) -> set[int]:
    """Classes de hauteur permises : la gamme, ou celles de la partie."""
    intervals = theory.SCALES.get(scale or "")
    if intervals and root is not None:
        return {(int(root) + i) % 12 for i in intervals}
    found = {int(e.note) % 12 for e in events or ()}
    return found or set(range(12))


def chord_at(chords, bar: int) -> dict | None:
    """Accord de la mesure ``bar`` — la progression tourne en boucle."""
    if not chords:
        return None
    return chords[int(bar) % len(chords)]


def _chord_classes(chord: dict | None) -> set[int]:
    if not chord:
        return set()
    out = {int(n) % 12 for n in chord.get("notes") or []}
    if "root" in chord:
        out.add(int(chord["root"]) % 12)
    return out


def _bar(event) -> int:
    return int(float(event.start) // STEPS_PER_BAR)


def _strong(start: float) -> bool:
    """Le premier et le troisième temps."""
    return float(start) % 8 == 0


def _move(note: int, degrees: int, classes: set[int]) -> int:
    """``note`` déplacée de ``degrees`` degrés de la gamme."""
    step = 1 if degrees > 0 else -1
    out = int(note)
    for _ in range(abs(int(degrees))):
        out += step
        guard = 0
        while out % 12 not in classes and guard < 12:
            out += step
            guard += 1
    return out


def _nearest(note: float, classes: set[int], targets: set[int] | None = None
             ) -> int:
    """Note de la gamme (ou de ``targets``) la plus proche de ``note``."""
    wanted = targets or classes
    best, distance = int(round(note)), 99
    for candidate in range(int(note) - 12, int(note) + 13):
        if candidate % 12 in wanted and abs(candidate - note) < distance:
            best, distance = candidate, abs(candidate - note)
    return best


def _fit(note: int, part: str) -> int:
    """Ramène une note dans le registre de la partie, par octaves."""
    low, high = _RANGE.get(part, (24, 108))
    while note < low:
        note += 12
    while note > high:
        note -= 12
    return note


def _groups(events) -> list[list[NoteEvent]]:
    """Les notes regroupées par attaque (un accord = un groupe)."""
    by_start: dict[float, list[NoteEvent]] = {}
    for event in events:
        by_start.setdefault(round(float(event.start), 4), []).append(event)
    return [by_start[k] for k in sorted(by_start)]


def clean_part(events, total_steps: float, mono: bool = False
               ) -> list[NoteEvent]:
    """Notes triées, dans le clip, sans chevauchement de même hauteur.

    ``mono`` rend la partie **monophonique** (une piste CV ne joue qu'une
    note à la fois) : voir :func:`monophonic`.
    """
    total = float(total_steps)
    kept: list[NoteEvent] = []
    for event in sorted(_copy(events), key=lambda e: (e.start, e.note)):
        if not 0 <= event.start < total:
            continue
        event.length = max(0.25, min(float(event.length),
                                     total - event.start))
        event.velocity = max(1, min(100, int(event.velocity)))
        kept.append(event)
    # Même hauteur qui se chevauche : la première s'arrête où la seconde
    # commence — la machine ignorerait sinon la seconde.
    last: dict[int, NoteEvent] = {}
    out: list[NoteEvent] = []
    for event in kept:
        previous = last.get(event.note)
        if previous is not None:
            if abs(previous.start - event.start) < 1e-6:
                continue
            if previous.start + previous.length > event.start:
                previous.length = max(0.25, event.start - previous.start)
        last[event.note] = event
        out.append(event)
    return monophonic(out) if mono else out


def monophonic(events) -> list[NoteEvent]:
    """Une note à la fois : la plus haute d'un accord, chacune coupée à
    l'attaque de la suivante.

    C'est ce qu'une piste CV peut jouer : une tension de hauteur, une porte.
    """
    out: list[NoteEvent] = []
    for group in _groups(_copy(events)):
        top = max(group, key=lambda e: e.note)
        if out and out[-1].start + out[-1].length > top.start:
            out[-1].length = max(0.25, top.start - out[-1].start)
        out.append(top)
    return out


def _jaccard(set_a: set, set_b: set) -> float:
    if not set_a and not set_b:
        return 1.0
    return len(set_a & set_b) / float(len(set_a | set_b))


def similarity(a, b) -> float:
    """Part commune de deux parties : notes de même hauteur au même instant,
    rapportées à toutes les notes (indice de Jaccard, 0 à 1). 1 veut dire
    « la même partie »."""
    def key(event):
        return (round(float(event.start) * 4) / 4, int(event.note))

    return _jaccard({key(e) for e in a or ()}, {key(e) for e in b or ()})


def kinship(a, b) -> float:
    """Parenté musicale de deux parties, de 0 à 1.

    Moitié rythme (les mêmes attaques), moitié notes (les mêmes notes aux
    mêmes instants, **à l'octave près**) : une mélodie montée d'une octave
    n'a plus une note en commun avec l'original pour :func:`similarity`,
    et pourtant c'est la même ligne. Mesuré : 0,00 de similitude pour toute
    variation « octave », 1,00 de parenté.
    """
    def onsets(events):
        return {round(float(e.start) * 4) / 4 for e in events or ()}

    def classes(events):
        return {(round(float(e.start) * 4) / 4, int(e.note) % 12)
                for e in events or ()}

    return 0.5 * _jaccard(onsets(a), onsets(b)) \
        + 0.5 * _jaccard(classes(a), classes(b))


def drum_similarity(a: rhythm.Pattern, b: rhythm.Pattern) -> float:
    """Part commune de deux motifs : coups de même piste sur la même case."""
    def keys(pattern):
        return {(track, rhythm.cell(step))
                for track, steps in (pattern.tracks or {}).items()
                for step in steps}

    set_a, set_b = keys(a), keys(b)
    if not set_a and not set_b:
        return 1.0
    return len(set_a & set_b) / float(len(set_a | set_b))


# --------------------------------------------------------------------------- #
# Parties mélodiques
# --------------------------------------------------------------------------- #

def vary_part(events, how: str, *, part: str = "Mélodie", bars: int = 0,
              chords=None, root: int | None = None, scale: str = "",
              seed: int | None = None, genre: str = "",
              mono: bool = False) -> list[NoteEvent]:
    """Une variation de la partie ``events`` (:data:`MELODIC`).

    :param part: « Basse », « Accords », « Arpège » ou « Mélodie » : chaque
        variation s'adapte à ce que la partie joue.
    :param bars: longueur du clip en mesures ; à défaut, celle des notes.
    :param chords: la progression (sortie de
        :func:`~delugeapp.core.theory.progression`), une entrée par mesure,
        en boucle : elle garde les temps forts sur l'accord.
    :param mono: le résultat ne joue qu'une note à la fois (piste CV).
    """
    source = clean_part(events, 1 << 20)
    if not source:
        return []
    if how not in MELODIC:
        raise ValueError(untranslated("variation inconnue : %r") % how)
    part = part if part in PARTS else "Mélodie"
    if not bars:
        end = max(e.start + e.length for e in source)
        bars = max(1, int(-(-end // STEPS_PER_BAR)))
    total = float(bars * STEPS_PER_BAR)
    classes = _classes(source, root, scale)
    rng = _rng(seed, how, part)
    context = _Context(part, int(bars), chords, classes, rng, root, scale,
                       genre, seed)
    worker = {
        "rythme": _vary_rhythm, "notes": _vary_notes, "plus": _vary_more,
        "moins": _vary_less, "réponse": _vary_answer,
        "octave": _vary_octave, "fin": _vary_ending,
    }[how]
    out = clean_part(worker(_copy(source), context), total, mono=mono)
    if out and _same(out, source):
        # Rien n'a bougé (une mélodie d'une note, des tirages contraires) :
        # une variation qui rend l'original ne sert à rien.
        out = clean_part(_vary_rhythm(_copy(source), context, force=True),
                         total, mono=mono)
    return out


class _Context:
    """Ce qu'une variation sait de la partie et de son morceau."""

    def __init__(self, part, bars, chords, classes, rng, root, scale, genre,
                 seed) -> None:
        self.part = part
        self.bars = bars
        self.chords = list(chords or [])
        self.classes = classes
        self.rng = rng
        self.root = root
        self.scale = scale
        self.genre = genre
        self.seed = seed

    def chord_classes(self, start: float) -> set[int]:
        return _chord_classes(chord_at(self.chords, int(start
                                                         // STEPS_PER_BAR)))


def _same(a, b) -> bool:
    return similarity(a, b) >= 0.999 and len(a) == len(b)


def _vary_rhythm(events, ctx: _Context, force: bool = False
                 ) -> list[NoteEvent]:
    """Anticipations et notes répétées ; les hauteurs ne changent pas."""
    groups = _groups(events)
    starts = [g[0].start for g in groups]
    changed = False
    out: list[NoteEvent] = []
    # Au plus deux attaques sur cinq bougent : au-delà, une basse en
    # contretemps décalée presque entière n'avait plus que 0,19 de parenté
    # avec l'original — un autre clip, pas sa variation.
    budget = max(1, int(round(len(groups) * 0.4)))
    for index, group in enumerate(groups):
        start = group[0].start
        previous = starts[index - 1] if index else -1.0
        following = starts[index + 1] if index + 1 < len(starts) \
            else float(ctx.bars * STEPS_PER_BAR)
        draw = ctx.rng.random()
        shift = 0.0
        # Le début d'une mesure reste en place : c'est lui qu'on entend.
        if budget <= 0:
            pass
        elif start % STEPS_PER_BAR and draw < 0.35 and start - 1 > previous:
            shift = -1.0                      # anticipation
        elif start % STEPS_PER_BAR and draw > 0.85 and start + 1 < following:
            shift = 1.0                       # retard
        if shift:
            budget -= 1
        length = max(e.length for e in group)
        split = (length >= 4 and ctx.rng.random() < 0.3)
        for event in group:
            event.start += shift
            if split:
                half = max(1.0, round(event.length / 2.0))
                out.append(NoteEvent(event.start, half - 0.25, event.note,
                                     event.velocity))
                out.append(NoteEvent(event.start + half,
                                     max(0.5, event.length - half),
                                     event.note,
                                     max(1, event.velocity - 8)))
            else:
                out.append(event)
        changed = changed or bool(shift) or split
    if not changed or force:
        candidates = [i for i, g in enumerate(groups)
                      if g[0].start % STEPS_PER_BAR
                      and g[0].start - 1 > (starts[i - 1] if i else -1.0)]
        if candidates:
            pick = groups[ctx.rng.choice(candidates)]
            target = round(pick[0].start, 4)
            for event in out:
                if round(event.start, 4) == target:
                    event.start -= 1.0
        elif out:
            # Une seule note par mesure : on la répète à la croche suivante.
            first = out[0]
            if first.length >= 2:
                half = first.length / 2.0
                first.length = half
                out.append(NoteEvent(first.start + half, half, first.note,
                                     max(1, first.velocity - 10)))
    return out


def _vary_notes(events, ctx: _Context) -> list[NoteEvent]:
    """Le même rythme, d'autres hauteurs, selon la partie."""
    part = ctx.part
    if part == "Arpège":
        return _reorder_arp(events, ctx)
    if part == "Accords":
        return _reinvert(events, ctx)
    changed = False
    for event in events:
        if _strong(event.start) or event.start % STEPS_PER_BAR == 0:
            continue
        if ctx.rng.random() >= (0.4 if part == "Basse" else 0.45):
            continue
        if part == "Basse":
            chord = ctx.chord_classes(event.start)
            choice = ctx.rng.random()
            if choice < 0.45:
                # La quinte juste de l'accord ; à défaut (accord diminué),
                # la quinte de la gamme, quatre degrés plus haut : la quinte
                # juste d'un si, en la mineur, serait un fa dièse.
                targets = {c for c in chord if (c - event.note) % 12 == 7
                           and c in ctx.classes}
                if targets:
                    event.note = _nearest(event.note + 7, ctx.classes,
                                          targets)
                else:
                    event.note = _move(event.note, 4, ctx.classes)
                event.note = _fit(event.note, part)
            elif choice < 0.8:
                event.note = _fit(event.note + 12, part)
            else:
                event.note = _move(event.note, ctx.rng.choice((-1, 1)),
                                   ctx.classes)
        else:
            event.note = _fit(_move(event.note, ctx.rng.choice((-1, 1)),
                                    ctx.classes), part)
        changed = True
    if not changed:
        weak = [e for e in events if not _strong(e.start)]
        if weak:
            event = ctx.rng.choice(weak)
            event.note = _fit(_move(event.note, 1, ctx.classes), part)
    return events


def _reorder_arp(events, ctx: _Context) -> list[NoteEvent]:
    """Les notes de chaque mesure dans un autre ordre (même rythme)."""
    orders = untranslated(("descendant", "rotation", "alterné", "mélangé"))
    choice = ctx.rng.choice(orders)
    by_bar: dict[int, list[NoteEvent]] = {}
    for event in sorted(events, key=lambda e: e.start):
        by_bar.setdefault(_bar(event), []).append(event)
    for bar_events in by_bar.values():
        pitches = [e.note for e in bar_events]
        if len(set(pitches)) < 2:
            continue
        if choice == "descendant":
            new = list(reversed(pitches))
        elif choice == "rotation":
            new = pitches[1:] + pitches[:1]
        elif choice == untranslated("alterné"):
            ordered = sorted(pitches)
            new, low, high = [], 0, len(ordered) - 1
            while low <= high:
                new.append(ordered[low])
                if low != high:
                    new.append(ordered[high])
                low += 1
                high -= 1
        else:
            new = list(pitches)
            for _ in range(4):
                ctx.rng.shuffle(new)
                if new != pitches:
                    break
        if new == pitches:
            new = list(reversed(pitches))
        for event, note in zip(bar_events, new):
            event.note = note
    return events


def _reinvert(events, ctx: _Context) -> list[NoteEvent]:
    """Chaque accord renversé : sa note grave monte, ou l'aiguë descend.

    Les notes restent celles de l'accord ; seul le voicing change, en
    restant dans le registre des accords.
    """
    low_limit, high_limit = _RANGE["Accords"]
    up = ctx.rng.random() < 0.5
    for group in _groups(events):
        notes = sorted(group, key=lambda e: e.note)
        if len(notes) < 2:
            continue
        if up and notes[0].note + 12 <= high_limit:
            notes[0].note += 12
        elif notes[-1].note - 12 >= low_limit:
            notes[-1].note -= 12
        elif notes[0].note + 12 <= high_limit:
            notes[0].note += 12
    return events


def _vary_more(events, ctx: _Context) -> list[NoteEvent]:
    """Plus de notes, selon la partie."""
    part = ctx.part
    out = list(events)
    taken = {round(e.start, 4) for e in out}
    if part == "Mélodie":
        ordered = sorted(out, key=lambda e: e.start)
        budget = max(1, int(len(ordered) * 0.4))
        for current, following in zip(ordered, ordered[1:]):
            if budget <= 0:
                break
            gap = following.start - current.start
            if gap < 3 or ctx.rng.random() > 0.65:
                continue
            if current.note == following.note:
                continue
            direction = 1 if current.note > following.note else -1
            passing = _move(following.note, direction, ctx.classes)
            at = following.start - 1
            if round(at, 4) in taken:
                continue
            current.length = min(current.length, at - current.start)
            out.append(NoteEvent(at, 1.0, passing,
                                 max(1, current.velocity - 12)))
            taken.add(round(at, 4))
            budget -= 1
    elif part == "Basse":
        for bar in range(ctx.bars):
            base = bar * STEPS_PER_BAR
            in_bar = [e for e in out if base <= e.start < base + STEPS_PER_BAR]
            if not in_bar:
                continue
            root = min(in_bar, key=lambda e: e.start).note
            for step, note in ((14, _fit(root + 12, part)),
                               (7, root)):
                at = float(base + step)
                if round(at, 4) in taken or ctx.rng.random() > 0.7:
                    continue
                for event in out:
                    if event.start < at < event.start + event.length:
                        event.length = at - event.start
                out.append(NoteEvent(at, 1.0, note, 82))
                taken.add(round(at, 4))
    elif part == "Arpège":
        extra: list[NoteEvent] = []
        for event in out:
            if _bar(event) % 2 == 1 and event.length >= 1.0:
                half = event.length / 2.0
                event.length = half
                extra.append(NoteEvent(event.start + half, half,
                                       _move(event.note, 1, ctx.classes),
                                       max(1, event.velocity - 10)))
        out.extend(extra)
    else:                                      # Accords : une relance
        for bar in range(ctx.bars):
            base = bar * STEPS_PER_BAR
            groups = [g for g in _groups(out)
                      if base <= g[0].start < base + STEPS_PER_BAR]
            if not groups or any(g[0].start >= base + 12 for g in groups):
                continue
            last = groups[-1]
            at = float(base + 14)
            for event in last:
                if event.start + event.length > at:
                    event.length = at - event.start - 0.25
            for event in last:
                out.append(NoteEvent(at, 1.5, event.note,
                                     max(1, event.velocity - 6)))
    return out


def _vary_less(events, ctx: _Context) -> list[NoteEvent]:
    """Moins de notes : on garde l'essentiel, on le tient plus longtemps."""
    part = ctx.part
    ordered = sorted(events, key=lambda e: (e.start, e.note))
    if part == "Accords":
        out: list[NoteEvent] = []
        for bar in range(ctx.bars):
            base = bar * STEPS_PER_BAR
            groups = [g for g in _groups(ordered)
                      if base <= g[0].start < base + STEPS_PER_BAR]
            if not groups:
                continue
            first = groups[0]
            held = base + STEPS_PER_BAR - first[0].start - 0.5
            for event in first:
                out.append(NoteEvent(first[0].start, held, event.note,
                                     event.velocity))
        return out
    if part == "Arpège":
        kept = [e for i, e in enumerate(ordered) if i % 2 == 0]
        for event in kept:
            event.length = event.length * 2.0
        return kept
    keep_every = 8 if part == "Basse" else 4
    kept = [e for e in ordered
            if e.start % keep_every == 0 or e.start % STEPS_PER_BAR == 0]
    if ordered and ordered[-1] not in kept:
        kept.append(ordered[-1])
    if len(kept) < 2:
        kept = ordered[::2] or ordered
    kept.sort(key=lambda e: e.start)
    for current, following in zip(kept, kept[1:]):
        current.length = max(current.length,
                             min(8.0, following.start - current.start - 0.25))
    return kept


def _vary_answer(events, ctx: _Context) -> list[NoteEvent]:
    """La première moitié gardée, la seconde lui répond."""
    half = (ctx.bars // 2) * STEPS_PER_BAR if ctx.bars >= 2 \
        else STEPS_PER_BAR / 2.0
    first = [e for e in events if e.start < half]
    second = [e for e in events if e.start >= half]
    if ctx.part == "Mélodie" and ctx.chords and ctx.bars >= 2:
        from .accomp import melody_part

        progression = [chord_at(ctx.chords, b) for b in range(ctx.bars)]
        new_seed = ctx.rng.randrange(1 << 30)
        reply = melody_part(progression, root=ctx.root, scale=ctx.scale,
                            genre=ctx.genre, seed=new_seed)
        answer = [e for e in reply if half <= e.start < ctx.bars
                  * STEPS_PER_BAR]
        if answer and similarity(answer, second) < 0.9:
            return first + answer
    if ctx.part == "Arpège":
        return first + _reorder_arp(second, ctx)
    sub = _Context(ctx.part, ctx.bars, ctx.chords, ctx.classes, ctx.rng,
                   ctx.root, ctx.scale, ctx.genre, ctx.seed)
    varied = _vary_notes(second, sub) if second else []
    return first + varied


def _vary_octave(events, ctx: _Context) -> list[NoteEvent]:
    """Des sauts d'octave (basse, arpège) ou le registre déplacé."""
    part = ctx.part
    low, high = _RANGE[part]
    ordered = sorted(events, key=lambda e: (e.start, e.note))
    if part in ("Basse", "Arpège"):
        for index, event in enumerate(ordered):
            if index % 2 == 1:
                if event.note + 12 <= high:
                    event.note += 12
                elif event.note - 12 >= low:
                    event.note -= 12
        return ordered
    mean = sum(e.note for e in ordered) / float(len(ordered))
    shift = -12 if mean > (low + high) / 2.0 else 12
    if any(not low <= e.note + shift <= high for e in ordered):
        shift = -shift
    if any(not low <= e.note + shift <= high for e in ordered):
        # Plus de place : seules les notes de la seconde moitié montent.
        half = ctx.bars * STEPS_PER_BAR / 2.0
        for event in ordered:
            if event.start >= half and event.note + 12 <= high:
                event.note += 12
        return ordered
    for event in ordered:
        event.note += shift
    return ordered


def _vary_ending(events, ctx: _Context) -> list[NoteEvent]:
    """La dernière mesure prépare le retour au début du clip."""
    part = ctx.part
    last_bar = (ctx.bars - 1) * STEPS_PER_BAR
    ordered = sorted(events, key=lambda e: (e.start, e.note))
    target = ordered[0].note
    if part == "Accords":
        first_group = _groups(ordered)[0]
        at = float(last_bar + 14)
        kept = [e for e in ordered if e.start < at]
        for event in kept:
            if event.start + event.length > at:
                event.length = max(0.5, at - event.start - 0.25)
        for event in first_group:
            kept.append(NoteEvent(at, 2.0, event.note, event.velocity))
        return kept
    run_start = last_bar + 12
    kept = [e for e in ordered if e.start < run_start]
    for event in kept:
        if event.start + event.length > run_start:
            event.length = max(0.5, run_start - event.start)
    if part == "Arpège":
        pool = sorted({e.note for e in ordered if e.start >= last_bar}
                      or {e.note for e in ordered})
        steps = [run_start + 0.5 * i for i in range(8)]
        for index, at in enumerate(steps):
            note = pool[index % len(pool)] + 12 * (index // len(pool))
            kept.append(NoteEvent(at, 0.45, _fit(note, part), 70 + 3 * index))
        return kept
    # Basse et mélodie : quatre doubles-croches qui marchent par degrés vers
    # la première note du clip ; elle résout à la boucle suivante.
    direction = -1 if ctx.rng.random() < 0.6 else 1   # par en dessous
    for index in range(4):
        pitch = _move(target, direction * (4 - index), ctx.classes)
        kept.append(NoteEvent(run_start + index, 0.9, _fit(pitch, part),
                              min(100, 78 + 5 * index)))
    return kept


# --------------------------------------------------------------------------- #
# Batterie
# --------------------------------------------------------------------------- #

def _copy_pattern(pattern: rhythm.Pattern, name: str) -> rhythm.Pattern:
    out = rhythm.Pattern(name=name, steps=int(pattern.steps),
                         ppq=int(pattern.ppq))
    for track, steps in (pattern.tracks or {}).items():
        out.tracks[track] = [rhythm.Step(pos=float(rhythm.cell(s)),
                                         velocity=int(s.velocity),
                                         length=s.length,
                                         probability=int(s.probability))
                             for s in steps]
    return out


def _snare(pattern: rhythm.Pattern) -> str:
    for name in ("Snare", "Clap", "Rim"):
        if name in pattern.tracks:
            return name
    return "Snare"


def vary_drums(pattern: rhythm.Pattern, how: str, *, genre: str = "",
               seed: int | None = None) -> rhythm.Pattern:
    """Une variation du motif ``pattern`` (:data:`DRUMS`)."""
    if how not in DRUMS:
        raise ValueError(untranslated("variation inconnue : %r") % how)
    rng = _rng(seed, how, "Batterie")
    base_name = str(pattern.name or "").split(" (")[0]
    if how == "ornements":
        return rhythm.variation(pattern, genre, seed=rng.randrange(1 << 30),
                                amount=0.5)
    out = _copy_pattern(pattern, base_name)
    total = int(out.steps)
    bars = max(1, total // STEPS_PER_BAR)
    last = (bars - 1) * STEPS_PER_BAR
    snare = _snare(out)

    if how == "remplissage":
        toms = [t for t in ("TomH", "TomM", "TomL") if t in out.tracks]
        zone = range(last + 12, last + 16)
        for track in (snare, *toms):
            out.tracks[track] = [s for s in out.tracks.get(track, [])
                                 if rhythm.cell(s) not in zone]
        if len(toms) >= 2:
            plan = [toms[0], toms[0], toms[min(1, len(toms) - 1)], toms[-1]]
        else:
            plan = [snare] * 4
        for index, position in enumerate(zone):
            out.add(plan[index], rhythm.Step(pos=float(position),
                                             velocity=62 + 11 * index))
        if rng.random() < 0.5:
            out.add(snare, rhythm.Step(pos=float(last + 11), velocity=58))
    elif how == "légère":
        out.tracks = {t: s for t, s in out.tracks.items() if t in _LIGHT}
        if not out.tracks:
            out.tracks = {"HatC": [rhythm.Step(pos=float(p), velocity=70)
                                   for p in range(2, total, 4)]}
    elif how == "cassure":
        out.tracks.pop("Kick", None)
        for steps in out.tracks.values():
            for step in steps:
                step.velocity = max(1, int(step.velocity * 0.85))
        if not any(out.tracks.values()):
            out.tracks["HatC"] = [rhythm.Step(pos=float(p), velocity=60)
                                  for p in range(2, total, 4)]
    elif how == "doublée":
        hats = out.tracks.setdefault("HatC", [])
        taken = {rhythm.cell(s) for s in hats}
        for position in range(total):
            if position not in taken and (position % 2 == 1 or not hats):
                hats.append(rhythm.Step(pos=float(position),
                                        velocity=rng.randint(44, 60)))
    elif how == "demi-temps":
        for track in ("Snare", "Clap"):
            if track in out.tracks:
                out.tracks[track] = [s for s in out.tracks[track]
                                     if rhythm.cell(s) % STEPS_PER_BAR == 8]
        if not out.tracks.get(snare):
            out.tracks[snare] = []
        for bar in range(bars):
            position = bar * STEPS_PER_BAR + 8
            if all(rhythm.cell(s) != position for s in out.tracks[snare]):
                out.add(snare, rhythm.Step(pos=float(position), velocity=96))
        if "Kick" in out.tracks:
            out.tracks["Kick"] = [s for s in out.tracks["Kick"]
                                  if rhythm.cell(s) % STEPS_PER_BAR
                                  in (0, 3, 10, 11, 14)]
    elif how == "montée":
        out.tracks[snare] = []
        for position in range(total):
            progress = position / float(max(1, total - 1))
            division = 4 if progress < 0.5 else (2 if progress < 0.75 else 1)
            if position % division == 0:
                out.add(snare, rhythm.Step(
                    pos=float(position),
                    velocity=int(40 + 60 * progress)))
    for steps in out.tracks.values():
        steps.sort(key=lambda s: float(s.pos))
    out.tracks = {t: s for t, s in out.tracks.items() if s}
    if drum_similarity(pattern, out) >= 0.999:
        # Rien n'a changé — des charleys déjà en doubles-croches : une
        # variation qui rend l'original ne sert à rien, on orne.
        return rhythm.variation(pattern, genre, seed=rng.randrange(1 << 30),
                                amount=0.5)
    return out
