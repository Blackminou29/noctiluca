# -*- coding: utf-8 -*-
"""L'automation d'un clip : un réglage du son qui bouge au cours du clip.

Une coupure qui s'ouvre sur une montée, un volume qui monte sur une intro,
un panoramique qui balance : sur le Deluge, chaque clip garde ses propres
réglages (``soundParams``), et chacun peut porter une courbe. Mesuré le
14 novembre 2026 sur la carte, courbe par courbe : **4 morceaux sur 56 en
portent** (Calm Down, Cool1 4, SONG050, SONG1 : 18 courbes — volume 9,
coupure 5, résonance 2, panoramique 2).

Le format est celui du firmware 1.3 (``AutoParam::writeToFile``,
``modulation/automation/auto_param.cpp``) : dans l'attribut du réglage,
``0x`` puis la valeur courante sur 8 chiffres hexadécimaux, puis, pour
chaque nœud, sa valeur (8 chiffres) et sa position en ticks du clip
(8 chiffres, le bit 31 allumé quand le nœud est **interpolé** : la valeur
y glisse depuis le nœud précédent). Un nœud non interpolé tient sa valeur
jusqu'au suivant ; la courbe boucle avec le clip, si bien qu'avant le
premier nœud vaut la valeur du dernier. La carte porte les deux formes :
des marches (17 courbes), et une coupure de SONG1 dont 56 nœuds sur 59 sont
interpolés. L'atelier écrit des marches, un nœud par double-croche où la
valeur change ; il relit les deux.

Dans l'atelier, une courbe est une liste ``[(pas, valeur affichée)]`` —
la valeur au cran de la machine, 0 à 50 (−25 à +25 pour le panoramique).
"""

from __future__ import annotations

import math

from ..i18n import N_, tr
from .fixedpoint import from_display, to_display

__all__ = ["AUTOMATABLE", "SHAPES", "BIPOLAR", "shape_nodes", "raw",
           "display", "encode", "decode", "value_at", "tile", "is_curve",
           "describe"]

#: Les réglages qu'un clip de synthé peut automatiser dans l'atelier, sous
#: leur nom de preset, et leur nom à l'écran.
AUTOMATABLE: dict[str, str] = {
    "lpfFrequency": N_("Coupure"),
    "lpfResonance": N_("Résonance"),
    "volume": N_("Volume"),
    "pan": N_("Panoramique"),
}

#: Les réglages bipolaires (−25 à +25 à l'écran).
BIPOLAR = frozenset({"pan"})

#: La montée qui recommence à chaque mesure.
PER_BAR = N_("par mesure")

#: Les formes de courbe, de la valeur de départ à celle d'arrivée.
SHAPES: dict[str, str] = {
    N_("montée"): N_("de la première valeur à la seconde, sur tout le clip"),
    N_("descente"): N_("de la seconde valeur à la première"),
    N_("vague"): N_("monte jusqu'au milieu du clip, puis redescend"),
    PER_BAR: N_("la montée recommence à chaque mesure"),
    N_("balancement"): N_("passe d'une valeur à l'autre à chaque temps"),
}

#: Bit d'un nœud interpolé, dans sa position.
_INTERPOLATED = 1 << 31


def bounds(key: str) -> tuple[int, int]:
    """Les valeurs d'écran d'un réglage."""
    return (-25, 25) if key in BIPOLAR else (0, 50)


def raw(key: str, value: int) -> int:
    """Une valeur d'écran -> l'entier 32 bits du fichier."""
    return from_display(int(value), bipolar=key in BIPOLAR)


def display(key: str, value: int) -> int:
    """L'entier du fichier -> la valeur d'écran."""
    return to_display(int(value), bipolar=key in BIPOLAR)


def shape_nodes(shape: str, steps: int, low: int, high: int,
                key: str = "lpfFrequency") -> list[tuple[int, int]]:
    """Une courbe de ``steps`` pas : un nœud par double-croche où la valeur
    change, le premier au pas 0. ``low`` et ``high`` sont des valeurs
    d'écran, bornées à celles du réglage."""
    if shape not in SHAPES:
        raise ValueError(tr("forme inconnue : %s") % shape)
    lo, hi = bounds(key)
    low = max(lo, min(hi, int(low)))
    high = max(lo, min(hi, int(high)))
    steps = max(1, int(steps))
    values = []
    for step in range(steps):
        if shape == "montée":
            t = step / max(1, steps - 1)
        elif shape == "descente":
            t = 1.0 - step / max(1, steps - 1)
        elif shape == "vague":
            t = 1.0 - abs(2.0 * step / max(1, steps - 1) - 1.0)
        elif shape == PER_BAR:
            t = (step % 16) / 15.0
        else:                                    # balancement
            t = float((step // 4) % 2)
        values.append(int(round(low + (high - low) * t)))
    out: list[tuple[int, int]] = []
    for step, value in enumerate(values):
        if not out or out[-1][1] != value:
            out.append((step, value))
    return out


def is_curve(text) -> bool:
    """Ce texte d'attribut porte-t-il des nœuds (et pas une seule
    valeur) ?"""
    t = str(text or "").strip()
    return t[:2].lower() == "0x" and len(t) > 10


def encode(key: str, nodes, ticks_per_step: int, length: int) -> str:
    """La courbe ``[(pas, valeur d'écran)]`` au format du firmware, pour un
    clip de ``length`` ticks : ``0x`` + valeur courante + nœuds. Les nœuds
    au-delà du clip sont écartés."""
    kept = [(int(step) * int(ticks_per_step), raw(key, value))
            for step, value in sorted(nodes)
            if 0 <= int(step) * int(ticks_per_step) < int(length)]
    if not kept:
        raise ValueError(tr("courbe vide"))
    parts = ["0x%08X" % (kept[0][1] & 0xFFFFFFFF)]
    for pos, value in kept:
        parts.append("%08X%08X" % (value & 0xFFFFFFFF, pos & 0x7FFFFFFF))
    return "".join(parts)


def _s32(value: int) -> int:
    value &= 0xFFFFFFFF
    return value - (1 << 32) if value & 0x80000000 else value


def decode(text) -> tuple[int, list[tuple[int, int, bool]]] | None:
    """``(valeur courante, [(position, valeur, interpolé)])`` d'un attribut
    du fichier, ou ``None`` s'il ne porte pas de nœuds."""
    t = str(text or "").strip()
    if not is_curve(t):
        return None
    hexa = t[2:]
    try:
        current = _s32(int(hexa[:8], 16))
        nodes = []
        for i in range(8, len(hexa) - 15, 16):
            value = _s32(int(hexa[i:i + 8], 16))
            pos = int(hexa[i + 8:i + 16], 16)
            nodes.append((pos & 0x7FFFFFFF, value, bool(pos & _INTERPOLATED)))
    except ValueError:
        return None
    return current, nodes


def value_at(nodes, step: float, length: float | None = None):
    """La valeur d'une courbe ``[(pas, valeur)]`` au pas ``step`` : celle du
    dernier nœud passé — avant le premier, celle du dernier nœud, la courbe
    bouclant avec le clip. ``None`` pour une courbe vide."""
    if not nodes:
        return None
    ordered = sorted(nodes)
    if length:
        step = float(step) % float(length)
    current = ordered[-1][1]
    for node_step, value in ordered:
        if node_step <= step:
            current = value
        else:
            break
    return current


def tile(nodes, clip_steps: int, total_steps: int, offset: int = 0
         ) -> list[tuple[float, int]]:
    """La courbe d'un clip répétée à chaque tour sur ``total_steps`` pas,
    décalée de ``offset`` : de quoi suivre le clip qui boucle dans une
    section."""
    if not nodes:
        return []
    clip_steps = max(1, int(clip_steps))
    ordered = sorted(nodes)
    out: list[tuple[float, int]] = []
    for start in range(0, int(total_steps), clip_steps):
        for step, value in ordered:
            if step < clip_steps and start + step < total_steps:
                out.append((float(offset + start + step), int(value)))
    return out


def describe(key: str, nodes) -> str:
    """« Coupure 12 → 40 » : le nom du réglage et ses bornes."""
    if not nodes:
        return ""
    values = [v for _s, v in nodes]
    first, last = values[0], values[-1]
    if max(values) not in (first, last):
        return "%s %d ↗ %d ↘ %d" % (tr(AUTOMATABLE.get(key, key)), first,
                                    max(values), last)
    return "%s %d → %d" % (tr(AUTOMATABLE.get(key, key)), first, last)


def sampled(decoded, ticks_per_step: float, length_ticks: int,
            key: str) -> list[tuple[int, int]]:
    """Une courbe lue sur la carte (:func:`decode`) ramenée aux pas de
    l'atelier : la valeur de chaque double-croche — un nœud interpolé fait
    glisser la valeur depuis le précédent —, un nœud où elle change."""
    if decoded is None:
        return []
    _current, nodes = decoded
    if not nodes:
        return []
    length = max(1, int(length_ticks))
    ordered = sorted(nodes)
    steps = max(1, int(math.ceil(length / float(ticks_per_step))))
    out: list[tuple[int, int]] = []
    for step in range(steps):
        tick = step * float(ticks_per_step)
        previous = ordered[-1]
        following = None
        for node in ordered:
            if node[0] <= tick:
                previous = node
            else:
                following = node
                break
        value = previous[1]
        if following is not None and following[2]:
            span = following[0] - previous[0] if previous[0] <= tick \
                else following[0] + length - previous[0]
            done = tick - previous[0] if previous[0] <= tick \
                else tick + length - previous[0]
            if span > 0:
                value = previous[1] + (following[1] - previous[1]) \
                    * done / float(span)
        shown = display(key, int(round(value)))
        if not out or out[-1][1] != shown:
            out.append((step, shown))
    return out
