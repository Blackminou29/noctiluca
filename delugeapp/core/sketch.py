# -*- coding: utf-8 -*-
"""Esquisse d'un morceau : une progression déroulée sur un modèle d'arrangement.

La Boîte à outils savait proposer des accords, une basse, une mélodie, un
rythme, et montrer la structure d'un morceau type — mais chacun de son côté.
Ce module les assemble : la progression tourne sur toute la durée du modèle
(:data:`ARRANGEMENTS`), et chaque section ne garde que les parties que son
rôle appelle (:data:`SECTION_PARTS`) — l'intro sans basse, la cassure sans
grosse caisse, le refrain avec tout et une batterie variée.

Le résultat s'écoute section par section (:func:`excerpt`) et s'exporte en
un seul fichier MIDI, une piste par partie, avec le nom des sections en
repères : un squelette de morceau prêt à habiller dans un logiciel de MAO,
ou à rejouer partie par partie sur le Deluge.

Module arithmétique, sans dépendance : ni carte, ni audio, ni Qt.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from . import accomp, rhythm, theory
from .accomp import STEPS_PER_BAR, NoteEvent

log = logging.getLogger(__name__)

#: Modèles de structure : ``(section, mesures)``.
_CLUB = (("Intro", 16), ("Montée", 16), ("Thème", 32), ("Cassure", 16),
         ("Thème 2", 32), ("Final", 16))
_HOUSE = (("Intro", 16), ("Couplet", 16), ("Montée", 8), ("Refrain", 32),
          ("Cassure", 16), ("Refrain 2", 32), ("Final", 16))
_TRANCE = (("Intro", 16), ("Montée", 32), ("Cassure", 16),
           ("Explosion", 32), ("Thème", 32), ("Final", 16))
_BASS = (("Intro", 16), ("Montée", 16), ("Chute", 32), ("Cassure", 16),
         ("Chute 2", 32), ("Final", 8))
_AMBIENT = (("Apparition", 32), ("Développement", 64),
            ("Point culminant", 32), ("Dissipation", 48))
_BOUCLE = (("Intro", 8), ("Boucle A", 16), ("Boucle B", 16),
           ("Pont", 8), ("Boucle A", 16), ("Sortie", 8))
_CHANSON = (("Intro", 8), ("Couplet", 16), ("Refrain", 16), ("Couplet 2", 16),
            ("Refrain 2", 16), ("Pont", 8), ("Refrain final", 16),
            ("Sortie", 8))
_SEQUENCE = (("Apparition", 16), ("Séquence", 32), ("Variation", 32),
             ("Solo", 16), ("Séquence", 32), ("Dissipation", 16))

#: Modèle de structure de chaque genre.
ARRANGEMENTS: dict[str, tuple[tuple[str, int], ...]] = {
    "techno": _CLUB, "acid": _CLUB, "minimal": _CLUB, "detroit": _CLUB,
    "industrial": _CLUB, "hardcore": _CLUB, "electro": _CLUB,
    "house": _HOUSE, "deep_house": _HOUSE, "funk": _HOUSE,
    "trance": _TRANCE, "psytrance": _TRANCE,
    "dnb": _BASS, "jungle": _BASS, "dubstep": _BASS,
    "ambient": _AMBIENT, "boards_of_canada": _AMBIENT,
    "lofi": _BOUCLE, "downtempo": _BOUCLE, "idm": _BOUCLE,
    "synthwave": _CHANSON, "berlin_school": _SEQUENCE,
}

#: Rôle d'une section, deviné d'après son nom.
SECTION_KINDS: dict[str, str] = {
    "intro": "on installe : batterie légère et accords",
    "montée": "la tension monte : basse et arpège entrent",
    "pic": "tout joue, mélodie comprise, batterie variée",
    "cassure": "la grosse caisse et la basse se taisent",
    "fin": "on referme, comme on a ouvert",
}

_KIND_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cassure", ("cassure", "pont")),
    ("intro", ("intro", "apparition")),
    # Le sommet avant la fin : « Refrain final » est un refrain.
    ("pic", ("thème", "refrain", "chute", "explosion", "culminant", "solo",
             "boucle b")),
    ("fin", ("final", "sortie", "dissipation")),
    ("montée", ("montée", "couplet", "développement", "séquence",
                "variation", "boucle a")),
)

#: Parties jouées selon le rôle de la section.
SECTION_PARTS: dict[str, tuple[str, ...]] = {
    "intro": ("Batterie légère", "Accords"),
    "montée": ("Batterie", "Basse", "Accords", "Arpège"),
    "pic": ("Batterie", "Basse", "Accords", "Arpège", "Mélodie"),
    "cassure": ("Accords", "Arpège", "Mélodie"),
    "fin": ("Batterie légère", "Accords"),
}

#: Pistes d'une batterie « légère » : ni caisse claire, ni clap, ni crash.
LIGHT_DRUMS = ("Kick", "HatC", "HatO", "Shaker", "Ride", "Rim")

#: Ambiance de progression qui convient à chaque genre, quand aucune
#: progression n'a été proposée.
GENRE_AMBIANCE: dict[str, str] = {
    "house": "house", "deep_house": "deep", "funk": "house",
    "techno": "techno", "minimal": "techno", "acid": "techno",
    "detroit": "deep", "industrial": "tendu", "hardcore": "tendu",
    "electro": "tendu", "trance": "trance", "psytrance": "trance",
    "dnb": "mélancolique", "jungle": "mélancolique", "dubstep": "tendu",
    "ambient": "ambient", "boards_of_canada": "mélancolique",
    "lofi": "jazz", "downtempo": "deep", "idm": "mélancolique",
    "synthwave": "épique", "berlin_school": "mélancolique",
}


def section_kind(name: str) -> str:
    """Rôle d'une section d'après son nom ; « montée » à défaut."""
    text = str(name or "").strip().lower()
    for kind, words in _KIND_WORDS:
        if any(word in text for word in words):
            return kind
    return "montée"


@dataclass
class Section:
    """Une section de l'esquisse."""

    name: str
    kind: str
    start: int          # première mesure (0 = début du morceau)
    bars: int
    parts: tuple[str, ...] = ()


@dataclass
class Sketch:
    """Le morceau esquissé : parties, sections, et batterie à écouter."""

    parts: dict[str, list[NoteEvent]] = field(default_factory=dict)
    sections: list[Section] = field(default_factory=list)
    drums: rhythm.Pattern | None = None
    bars: int = 0

    def markers(self) -> list[tuple[float, str]]:
        """Repères des sections, en pas : pour l'export MIDI."""
        return [(float(s.start * STEPS_PER_BAR), s.name)
                for s in self.sections]


def plan(genre: str, arp: bool | None = None,
         melody: bool = True) -> list[Section]:
    """Les sections du modèle du genre, avec les parties qu'elles jouent."""
    key = str(genre or "").strip().lower()
    template = ARRANGEMENTS.get(key, ARRANGEMENTS["techno"])
    with_arp = accomp.genre_styles(key)[2] if arp is None else bool(arp)
    out: list[Section] = []
    start = 0
    for name, bars in template:
        kind = section_kind(name)
        parts = tuple(p for p in SECTION_PARTS[kind]
                      if (p != "Arpège" or with_arp)
                      and (p != "Mélodie" or melody))
        out.append(Section(name, kind, start, int(bars), parts))
        start += int(bars)
    return out


def default_progression(genre: str, seed: int | None = None,
                        root: int = 57, scale: str = "mineur") -> list[dict]:
    """Une progression de quatre mesures dans l'ambiance du genre."""
    key = str(genre or "").strip().lower()
    return theory.progression(root, scale, GENRE_AMBIANCE.get(key, "pop"),
                              seed=seed, bars=4)


def _offset(pattern: rhythm.Pattern, bars: int, start_bar: int,
            keep: tuple[str, ...] | None, into: rhythm.Pattern) -> None:
    """Pose ``pattern`` bouclé sur ``bars`` mesures à partir de ``start_bar``."""
    looped = rhythm.loop(pattern, bars)
    base = start_bar * STEPS_PER_BAR
    for track, steps in looped.tracks.items():
        if keep is not None and track not in keep:
            continue
        for step in steps:
            into.add(track, rhythm.Step(pos=float(step.pos) + base,
                                        velocity=step.velocity,
                                        length=step.length,
                                        probability=step.probability))


def sketch(progression: list[dict], genre: str = "techno",
           pattern: rhythm.Pattern | None = None, root: int | None = None,
           scale: str = "", arp: bool | None = None, melody: bool = True,
           seed: int | None = None) -> Sketch:
    """L'esquisse du morceau : la progression déroulée sur tout le modèle.

    :param pattern: le rythme ; à défaut, celui du genre. Les sections au
        sommet jouent une **variation** qui garde son ossature
        (:func:`delugeapp.core.rhythm.variation`), une crash marque leur
        entrée.
    :param root, scale: tonalité de la mélodie (voir
        :func:`delugeapp.core.accomp.melody_part`).
    """
    sections = plan(genre, arp=arp, melody=melody)
    total = sum(s.bars for s in sections)
    chords = [c for c in (progression or []) if c.get("notes")]
    if not chords or total <= 0:
        return Sketch(sections=sections, bars=total)
    song = [dict(chords[bar % len(chords)]) for bar in range(total)]
    with_arp = any("Arpège" in s.parts for s in sections)
    full = accomp.accompany(song, genre=genre, arp=with_arp, melody=melody,
                            root=root, scale=scale, seed=seed)

    beat = pattern if pattern is not None else rhythm.genre_beat(
        genre, bars=1, seed=seed if seed is not None else 1)
    lifted = rhythm.variation(beat, genre, seed=seed, amount=0.5)
    drums = rhythm.Pattern(name="Esquisse", steps=total * STEPS_PER_BAR)

    parts: dict[str, list[NoteEvent]] = {name: [] for name in full}
    for section in sections:
        first = section.start * STEPS_PER_BAR
        last = (section.start + section.bars) * STEPS_PER_BAR
        for name, events in full.items():
            if name not in section.parts:
                continue
            parts[name].extend(e for e in events if first <= e.start < last)
        if "Batterie" in section.parts:
            source = lifted if section.kind == "pic" else beat
            _offset(source, section.bars, section.start, None, drums)
            if section.kind == "pic":
                drums.add("Crash", rhythm.Step(pos=float(first), velocity=96))
        elif "Batterie légère" in section.parts:
            _offset(beat, section.bars, section.start, LIGHT_DRUMS, drums)

    for steps in drums.tracks.values():
        steps.sort(key=lambda s: float(s.pos))
    parts = {name: events for name, events in parts.items() if events}
    if drums.tracks:
        parts["Batterie"] = accomp.drum_part(drums)
    log.info("esquisse %s : %d mesures, %d sections, parties %s", genre,
             total, len(sections), ", ".join(parts))
    return Sketch(parts=parts, sections=sections, drums=drums, bars=total)


def excerpt(result: Sketch, index: int, max_bars: int = 8
            ) -> tuple[dict[str, list[NoteEvent]], rhythm.Pattern | None, int]:
    """Le début d'une section, ramené au temps zéro : pour l'écouter.

    :returns: ``(parties, batterie, mesures)``.
    """
    if not 0 <= int(index) < len(result.sections):
        return {}, None, 0
    section = result.sections[index]
    bars = max(1, min(int(max_bars), section.bars))
    first = section.start * STEPS_PER_BAR
    last = first + bars * STEPS_PER_BAR
    parts = {name: [NoteEvent(e.start - first, e.length, e.note, e.velocity)
                    for e in events if first <= e.start < last]
             for name, events in result.parts.items() if name != "Batterie"}
    parts = {name: events for name, events in parts.items() if events}
    drums = None
    if result.drums is not None:
        drums = rhythm.Pattern(name=section.name, steps=bars * STEPS_PER_BAR)
        for track, steps in result.drums.tracks.items():
            for step in steps:
                if first <= float(step.pos) < last:
                    drums.add(track, rhythm.Step(
                        pos=float(step.pos) - first, velocity=step.velocity,
                        length=step.length, probability=step.probability))
        if not drums.tracks:
            drums = None
    return parts, drums, bars
