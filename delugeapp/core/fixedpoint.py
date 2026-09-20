# -*- coding: utf-8 -*-
"""Conversions entre les entiers 32 bits signés du Deluge et les valeurs usuelles.

Le Deluge stocke la plupart de ses paramètres continus sous forme d'entiers 32 bits
signés écrits en hexadécimal dans les fichiers XML (``0x7FFFFFFF``) :

* ``0x80000000`` = -2147483648 = minimum ;
* ``0x00000000`` = 0 = milieu ;
* ``0x7FFFFFFF`` = +2147483647 = maximum.

Deux familles de paramètres existent :

* **unipolaire** (volume, résonance, attaque, reverbAmount…) : l'écran affiche 0 à 50 ;
* **bipolaire** (pan, amount des patch cables, égaliseur…) : l'écran affiche -25 à +25
  (``scale=50``) ou -50 à +50 (``scale=100``, cas des patch cables).

Module volontairement sans dépendance : ni Qt, ni numpy.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

__all__ = [
    "INT32_MIN",
    "INT32_MAX",
    "INT32_SPAN",
    "parse_fixed",
    "format_fixed",
    "to_unit",
    "from_unit",
    "to_bipolar",
    "from_bipolar",
    "to_display",
    "from_display",
    "parse_int",
    "clamp_int32",
    "wrap_int32",
]

INT32_MIN = -2147483648
INT32_MAX = 2147483647
#: Amplitude totale de la plage 32 bits signée (4294967295).
INT32_SPAN = INT32_MAX - INT32_MIN

_UINT32 = 1 << 32
_INT32_OFFSET = 1 << 31


def clamp_int32(value: int) -> int:
    """Sature ``value`` dans la plage 32 bits signée (pas de repliement)."""
    if value < INT32_MIN:
        return INT32_MIN
    if value > INT32_MAX:
        return INT32_MAX
    return int(value)


def wrap_int32(value: int) -> int:
    """Replie ``value`` en complément à deux sur 32 bits (``0xFFFFFFFF`` -> -1)."""
    return ((int(value) + _INT32_OFFSET) % _UINT32) - _INT32_OFFSET


def _coerce_number(text: "str | int | float | None") -> "int | None":
    """Convertit une valeur brute de fichier Deluge en entier Python, ou ``None``.

    Accepte les entiers, les flottants, ``'0x1F'``, ``'-0x1F'``, ``'  42 '``,
    ``'1.0'``, ``'+3'``. Retourne ``None`` si rien d'exploitable.
    """
    if text is None:
        return None
    if isinstance(text, bool):  # bool est un int en Python : on le traite à part
        return 1 if text else 0
    if isinstance(text, int):
        return int(text)
    if isinstance(text, float):
        try:
            return int(text)
        except (ValueError, OverflowError):
            return None
    try:
        s = str(text).strip()
    except Exception:  # pragma: no cover - str() ne devrait jamais échouer
        return None
    if not s:
        return None
    neg = False
    if s[0] in "+-":
        neg = s[0] == "-"
        s = s[1:].strip()
    if not s:
        return None
    low = s.lower()
    try:
        if low.startswith("0x"):
            value = int(low[2:], 16)
            if len(low) - 2 > 8:  # hexadécimal trop long : on garde les 32 bits bas
                value &= 0xFFFFFFFF
            # Un hexadécimal de 8 chiffres est déjà en complément à deux.
            if not neg and len(low) - 2 >= 8 and value > INT32_MAX:
                value -= _UINT32
        elif low.startswith("0b"):
            value = int(low[2:], 2)
        elif low.startswith("0o"):
            value = int(low[2:], 8)
        else:
            try:
                value = int(s, 10)
            except ValueError:
                value = int(float(s.replace(",", ".")))
    except (ValueError, OverflowError):
        return None
    return -value if neg else value


def parse_fixed(text: "str | int | None", default: int = 0) -> int:
    """``'0x7FFFFFFF'`` | ``'-601295438'`` | ``None`` -> entier signé 32 bits.

    Toute valeur illisible retourne ``default`` (lui-même ramené dans la plage).
    Les valeurs hors plage sont repliées en complément à deux, comme le firmware.
    """
    value = _coerce_number(text)
    if value is None:
        return wrap_int32(default)
    return wrap_int32(value)


def format_fixed(value: int) -> str:
    """Entier signé 32 bits -> ``'0x7FFFFFFF'`` (8 chiffres hexadécimaux majuscules)."""
    return "0x%08X" % (wrap_int32(value) & 0xFFFFFFFF)


def to_unit(value: int) -> float:
    """Entier 32 bits -> flottant 0.0..1.0 (``0x80000000`` -> 0.0, ``0x7FFFFFFF`` -> 1.0)."""
    v = clamp_int32(_coerce_number(value) or 0) if not isinstance(value, int) else clamp_int32(value)
    return (v - INT32_MIN) / INT32_SPAN


def from_unit(u: float) -> int:
    """Flottant 0.0..1.0 -> entier 32 bits saturé."""
    try:
        f = float(u)
    except (TypeError, ValueError):
        f = 0.0
    if f != f:  # NaN
        f = 0.0
    f = min(1.0, max(0.0, f))
    return clamp_int32(int(round(f * INT32_SPAN)) + INT32_MIN)


def to_bipolar(value: int) -> float:
    """Entier 32 bits -> flottant -1.0..1.0 (0 reste 0.0)."""
    v = clamp_int32(value if isinstance(value, int) else (_coerce_number(value) or 0))
    return min(1.0, max(-1.0, v / INT32_MAX))


def from_bipolar(b: float) -> int:
    """Flottant -1.0..1.0 -> entier 32 bits saturé."""
    try:
        f = float(b)
    except (TypeError, ValueError):
        f = 0.0
    if f != f:  # NaN
        f = 0.0
    f = min(1.0, max(-1.0, f))
    return clamp_int32(int(round(f * INT32_MAX)))


def to_display(value: int, bipolar: bool = False, scale: int = 50) -> int:
    """Valeur affichée par le Deluge : 0..50 (unipolaire) ou -25..+25 (bipolaire, ``scale=50``).

    Pour les patch cables, le firmware affiche -50..+50 : utiliser ``scale=100``.
    """
    scale = int(scale) if scale else 50
    v = value if isinstance(value, int) else parse_fixed(value)
    disp = int(round(to_unit(clamp_int32(v)) * scale))
    if bipolar:
        disp -= scale // 2
        half = scale // 2
        return min(half, max(-half, disp))
    return min(scale, max(0, disp))


def from_display(disp: int, bipolar: bool = False, scale: int = 50) -> int:
    """Inverse de :func:`to_display` : valeur d'écran -> entier 32 bits."""
    scale = int(scale) if scale else 50
    d = _coerce_number(disp)
    if d is None:
        d = 0
    if bipolar:
        half = scale // 2
        d = min(half, max(-half, d)) + half
    else:
        d = min(scale, max(0, d))
    return from_unit(d / scale)


def parse_int(text, default: int = 0) -> int:
    """Entier brut tolérant : ``''``, ``None``, ``'0x1235'``, ``'-12'``, ``'2.0'``.

    Sert aux champs non hexadécimaux du Deluge (``transpose``, ``cents``, ``num``,
    ``syncLevel``, ``startSamplePos``…). Pas de repliement 32 bits : la valeur est
    rendue telle quelle, sauf si elle provient d'un hexadécimal de 8 chiffres.
    """
    value = _coerce_number(text)
    if value is None:
        value = _coerce_number(default)
    if value is None:
        return 0
    return int(value)
