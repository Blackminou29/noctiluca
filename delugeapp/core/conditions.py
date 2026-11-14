# -*- coding: utf-8 -*-
"""Les conditions d'une note : probabilité, itération, remplissage.

Ce que la machine sait faire d'une note au-delà de sa hauteur et de sa force,
et que l'atelier écrit, pour qu'un morceau vive sur le Deluge : une charley
qui ne joue qu'une fois sur deux, un coup fantôme à 50 %, un roulement qui
attend le bouton FILL.

Mesuré sur la carte (13 novembre 2026, 56 morceaux) : **13 morceaux portent
des probabilités, 8 des itérations**, aucun de remplissage. L'utilisateur
s'en sert sur la machine ; l'atelier ne savait ni les écrire ni les entendre.

Les règles sont celles du firmware 1.3 (``model/clip/instrument_clip.cpp``,
``model/iterance/iterance.h``, ``model/note/note_row.cpp``) :

* **probabilité** : 1 à 20 (× 5 %), 20 voulant dire « toujours ». Deux notes
  de même probabilité, au même instant d'un clip, partagent leur tirage ; si
  toutes les notes d'un instant sont incertaines et que leurs probabilités
  font 100 %, **une seule** joue ;
* **itération** : ``diviseur << 8 | masque`` — la note joue à la répétition
  *r* du clip si le bit ``r % diviseur`` du masque est allumé. Diviseur 0 :
  masque 1, la première fois seulement ; 2, la dernière ;
* **remplissage** : 0 aucun, 1 « sauf remplissage » (la note se tait quand
  FILL est tenu), 2 « remplissage » (elle ne joue que FILL tenu).

La probabilité passe d'abord, puis l'itération, puis le remplissage.

Un morceau **c1.2** (``noteDataWithLift``), ce qu'écrit l'atelier, n'a qu'un
octet par note : 1–19 une probabilité, 20 toujours, 0 remplissage, 128 sauf
remplissage, 21 à 55 une itération de l'ancien menu (1 sur 2, 2 sur 2, 1 sur
3 … 8 sur 8), et le bit 7 sur une probabilité « suit la précédente ». Le
firmware 1.3 le relit ainsi (``note_row.cpp``, ``iterance_migration.cpp``) :
une note n'y porte donc **qu'une condition à la fois**, et l'atelier n'en
propose pas davantage.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import gcd

from ..i18n import tr

__all__ = ["ALWAYS", "FILL", "NOT_FILL", "Condition", "CHOICES",
           "iterance", "iterance_of", "legacy_byte", "from_legacy",
           "probability_byte", "percent", "label", "of", "cycle",
           "playing", "has_condition"]

#: ``kNumProbabilityValues`` : 20 crans de 5 %, le dernier voulant dire
#: « toujours ».
ALWAYS = 20

#: ``FillMode`` du firmware.
NOT_FILL = 1
FILL = 2

#: Les itérations de l'ancien menu, dans l'ordre de l'octet de condition
#: d'un morceau c1.2 (21 = 1 sur 2, 22 = 2 sur 2, 23 = 1 sur 3…, 55 = 8 sur
#: 8) : ``iterancePresets`` du firmware 1.3 sans « première » ni
#: « dernière », qu'il a placées devant.
LEGACY_ITERANCES: tuple[tuple[int, int], ...] = tuple(
    (divisor, step) for divisor in range(2, 9)
    for step in range(1, divisor + 1))

#: Octets d'un morceau c1.2 qui ne sont pas des probabilités.
_OLD_FILL = 0
_OLD_NOT_FILL = 128
#: Bit d'une probabilité qui « suit la précédente » (``& 128``).
_LATCHED = 128


#: Le réglage communautaire qui fait du bouton SYNC-SCALING le bouton FILL
#: (``RuntimeFeatureStateSyncScalingAction`` : 0 « Sync Scaling », 1 « Fill
#: mode »), et où le firmware range son fichier : ``SETTINGS/`` depuis la
#: 1.3, la racine avant.
_FILL_SETTING = "syncScalingAction"
_FEATURE_PLACES = ("SETTINGS/CommunityFeatures.XML", "CommunityFeatures.XML")


def fill_button_ready(card) -> bool | None:
    """Le Deluge de cette carte joue-t-il les notes de remplissage ?

    Seulement si *SETTINGS ▸ COMMUNITY FEATURES ▸ Sync Scaling Action* est
    sur *Fill mode* : sinon SYNC-SCALING garde son rôle (``view.cpp``), et
    une note de remplissage ne joue que par la commande MIDI globale
    « FILL ». Mesuré le 13 novembre 2026 : sur la carte de l'utilisateur, le
    réglage est sur « Sync Scaling ». ``None`` sans carte ni fichier
    lisible."""
    from pathlib import Path

    from . import dxml

    root = getattr(card, "root", None)
    if root is None:
        return None
    for place in _FEATURE_PLACES:
        path = Path(root) / place
        try:
            if not path.is_file():
                continue
            doc = dxml.load(path)
        except Exception:               # noqa: BLE001 - fichier utilisateur
            return None
        for el in doc.root.iter("setting"):
            if el.get("name") == _FILL_SETTING:
                return str(el.get("value", "0")).strip() == "1"
        return False
    return None


def iterance(divisor: int, step: int) -> int:
    """« ``step`` sur ``divisor`` » en valeur du firmware 1.3."""
    divisor, step = int(divisor), int(step)
    if not 1 <= divisor <= 8 or not 1 <= step <= divisor:
        raise ValueError(tr("itération impossible : %d sur %d")
                         % (step, divisor))
    return (divisor << 8) | (1 << (step - 1))


def iterance_of(value: int) -> tuple[int, int]:
    """``(diviseur, masque)`` d'une itération ; ``(0, 0)`` pour aucune, et
    pour une valeur que le firmware écarterait (``Iterance::fromInt``)."""
    value = int(value or 0)
    divisor, mask = (value >> 8) & 0xFF, value & 0xFF
    if (divisor == 0 and mask not in (1, 2)) or divisor > 8:
        return 0, 0
    return divisor, mask


def probability_byte(value: int) -> int:
    """Une probabilité en pour cent -> le cran du firmware, 1 à 20. Jamais
    0 : dans un morceau c1.2, l'octet 0 veut dire « remplissage »."""
    try:
        value = int(value)
    except (TypeError, ValueError):
        return ALWAYS
    return max(1, min(ALWAYS, int(round(value / 5.0))))


def percent(byte: int) -> int:
    """Le cran du firmware (1 à 20) -> pour cent."""
    return max(5, min(100, int(byte) * 5))


def legacy_byte(probability: int = 100, iterance_value: int = 0,
                fill: int = 0) -> int:
    """L'octet de condition d'une note de morceau c1.2.

    Le remplissage l'emporte, puis l'itération, puis la probabilité : un
    octet n'en porte qu'une. Une itération que l'ancien menu ne connaît pas
    (« la première fois », trois pas sur quatre…) laisse la note jouer
    toujours, plutôt qu'au hasard.
    """
    if int(fill or 0) == FILL:
        return _OLD_FILL
    if int(fill or 0) == NOT_FILL:
        return _OLD_NOT_FILL
    divisor, mask = iterance_of(iterance_value)
    if divisor:
        steps = [s + 1 for s in range(divisor) if mask >> s & 1]
        if len(steps) == 1 and (divisor, steps[0]) in LEGACY_ITERANCES:
            return ALWAYS + 1 + LEGACY_ITERANCES.index((divisor, steps[0]))
        return ALWAYS
    if divisor == 0 and mask:
        return ALWAYS
    return probability_byte(probability)


def from_legacy(byte: int) -> tuple[int, int, int]:
    """L'octet de condition d'un morceau c1.2 -> ``(pour cent, itération,
    remplissage)``, comme le relit le firmware 1.3. Une probabilité qui
    « suit la précédente » est prise pour elle-même."""
    byte = int(byte)
    if byte == _OLD_FILL:
        return 100, 0, FILL
    if byte == _OLD_NOT_FILL:
        return 100, 0, NOT_FILL
    if ALWAYS < byte <= ALWAYS + len(LEGACY_ITERANCES):
        divisor, step = LEGACY_ITERANCES[byte - ALWAYS - 1]
        return 100, iterance(divisor, step), 0
    value = byte & 0x7F
    if 1 <= value < ALWAYS:
        return percent(value), 0, 0
    return 100, 0, 0


def from_note(note) -> tuple[int, int, int]:
    """La condition d'une note lue dans un morceau (``model.Note``) :
    ``(pour cent, itération, remplissage)``, quel que soit son format — un
    octet c1.2, ou les trois champs d'un morceau 1.3."""
    byte = int(getattr(note, "condition", ALWAYS))
    iterance_value = int(getattr(note, "iterance", 0) or 0)
    fill = int(getattr(note, "fill", 0) or 0)
    if iterance_value or fill:
        pct = percent(byte) if 1 <= byte < ALWAYS else 100
        if iterance_of(iterance_value) == (0, 0):
            iterance_value = 0
        return pct, iterance_value, fill if fill in (NOT_FILL, FILL) else 0
    return from_legacy(byte)


@dataclass(frozen=True)
class Condition:
    """La condition d'une note, telle que l'atelier la pose : une seule à
    la fois (un morceau c1.2 n'en porte pas davantage)."""

    probability: int = 100
    iterance: int = 0
    fill: int = 0

    @property
    def always(self) -> bool:
        return (self.probability >= 100 and not self.iterance
                and not self.fill)

    def label(self) -> str:
        return label(self.probability, self.iterance, self.fill)


def _choices() -> tuple[Condition, ...]:
    out = [Condition(), Condition(probability=75), Condition(probability=50),
           Condition(probability=25)]
    for divisor, step in ((2, 1), (2, 2), (3, 1), (4, 1), (4, 2), (4, 3),
                          (4, 4), (8, 1), (8, 8)):
        out.append(Condition(iterance=iterance(divisor, step)))
    out += [Condition(fill=FILL), Condition(fill=NOT_FILL)]
    return tuple(out)


#: Ce que l'atelier propose, dans cet ordre.
CHOICES: tuple[Condition, ...] = _choices()


def label(probability: int = 100, iterance_value: int = 0,
          fill: int = 0) -> str:
    """« 50 % », « 1 sur 4 », « Remplissage »… dans la langue de
    l'interface."""
    if int(fill or 0) == FILL:
        return tr("Remplissage")
    if int(fill or 0) == NOT_FILL:
        return tr("Sauf remplissage")
    divisor, mask = iterance_of(iterance_value)
    if divisor:
        steps = [str(s + 1) for s in range(divisor) if mask >> s & 1]
        return tr("%s sur %d") % ("+".join(steps), divisor)
    if mask == 1:
        return tr("La première fois")
    if mask == 2:
        return tr("La dernière fois")
    if int(probability) < 100:
        return "%d %%" % int(probability)
    return tr("Toujours")


def short_label(probability: int = 100, iterance_value: int = 0,
                fill: int = 0) -> str:
    """La condition en deux ou trois signes, pour une case de la grille :
    « 50 », « 1/2 », « F », « ¬F »."""
    if int(fill or 0) == FILL:
        return "F"
    if int(fill or 0) == NOT_FILL:
        return "¬F"
    divisor, mask = iterance_of(iterance_value)
    if divisor:
        steps = [str(s + 1) for s in range(divisor) if mask >> s & 1]
        return "%s/%d" % ("+".join(steps), divisor)
    if mask:
        return "1er" if mask == 1 else "fin"
    if int(probability) < 100:
        return str(int(probability))
    return ""


def of(item) -> Condition:
    """La condition d'une note de l'atelier (``NoteEvent``) ou d'un coup
    (``rhythm.Step``)."""
    return Condition(int(getattr(item, "probability", 100) or 100),
                     int(getattr(item, "iterance", 0) or 0),
                     int(getattr(item, "fill", 0) or 0))


def has_condition(item) -> bool:
    return not of(item).always


def cycle(items, limit: int = 8) -> int:
    """Combien de répétitions d'un clip il faut écouter pour entendre ses
    conditions : le plus petit commun multiple des diviseurs d'itération, au
    moins deux s'il y a du hasard, ``limit`` au plus. 1 sans condition."""
    period, chance = 1, False
    for item in items:
        divisor, _mask = iterance_of(getattr(item, "iterance", 0))
        if divisor:
            period = period * divisor // gcd(period, divisor)
        elif int(getattr(item, "probability", 100) or 100) < 100:
            chance = True
    if chance:
        period = max(period, 2)
    return max(1, min(int(limit), period))


def playing(items, repeat: int, rng=None, *, position=None, get=None,
            fill_held: bool = False, ending: bool = False) -> list:
    """Les notes d'un clip qui jouent à sa répétition ``repeat`` (0 pour la
    première), selon les règles du firmware 1.3.

    ``items`` : les notes de **tout le clip** — rangées d'un kit comprises :
    le firmware tire au sort par clip, pas par rangée. ``get(item)`` rend
    l'objet qui porte la condition (l'élément lui-même par défaut),
    ``position(item)`` l'instant de la note (``start``, à défaut ``pos``).
    ``rng`` : un ``random.Random`` ; sans lui, toute note incertaine joue
    (un export MIDI). ``ending`` : c'est la dernière répétition du clip, ce
    qu'une itération « la dernière fois » attend.
    """
    if get is None:
        def get(item):
            return item
    if position is None:
        def position(item):
            note = get(item)
            return getattr(note, "start", getattr(note, "pos", 0))
    by_time: dict[float, list] = {}
    for item in items:
        by_time.setdefault(round(float(position(item)), 4), []).append(item)
    out = []
    for moment in sorted(by_time):
        group = by_time[moment]
        crans = [probability_byte(getattr(get(i), "probability", 100) or 100)
                 for i in group]
        passed = [True] * len(group)
        if rng is not None and any(c < ALWAYS for c in crans):
            if all(c < ALWAYS for c in crans) and sum(crans) == ALWAYS:
                # « Somme à 100 % » : une seule note de l'instant joue.
                draw, upto = rng.randrange(ALWAYS), 0
                winner = None
                for index, cran in enumerate(crans):
                    upto += cran
                    if winner is None and upto > draw:
                        winner = index
                passed = [index == winner for index in range(len(group))]
            else:
                # Les notes de même probabilité partagent leur tirage.
                outcome: dict[int, bool] = {}
                for index, cran in enumerate(crans):
                    if cran >= ALWAYS:
                        continue
                    if cran not in outcome:
                        outcome[cran] = rng.randrange(ALWAYS) < cran
                    passed[index] = outcome[cran]
        for item, ok in zip(group, passed):
            if not ok:
                continue
            note = get(item)
            divisor, mask = iterance_of(getattr(note, "iterance", 0))
            if divisor and not mask >> (int(repeat) % divisor) & 1:
                continue
            if not divisor and mask == 1 and int(repeat) != 0:
                continue
            if not divisor and mask == 2 and not ending:
                continue
            fill = int(getattr(note, "fill", 0) or 0)
            if fill == FILL and not fill_held:
                continue
            if fill == NOT_FILL and fill_held:
                continue
            out.append(item)
    return out
