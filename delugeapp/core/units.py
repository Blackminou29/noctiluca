# -*- coding: utf-8 -*-
"""Grandeurs mises en forme pour l'affichage : octets, durées, tailles.

**Une seule implémentation, partagée par le noyau et l'interface.** Il y en a
eu trois : une dans ``ui/widgets/common.py`` et deux recopiées dans
``core/samplefix.py`` et ``core/songpack.py``. Les copies du noyau écrivaient
le séparateur décimal à l'anglaise — « 9.9 Mio » — là où l'interface écrivait
« 9,9 Mio ». Les messages de correction d'échantillons et de rassemblement de
morceau sortaient donc avec un point, au milieu d'une application en
français.

Ce module ne dépend de rien d'autre que de la bibliothèque standard : le
noyau peut l'utiliser sans toucher à Qt, et l'interface le réexporte pour que
les appels existants restent valables.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

__all__ = ["human_size", "human_duration", "human_datetime", "file_size",
           "BYTE_UNITS"]

#: Unités binaires, de l'octet au gibioctet.
BYTE_UNITS = ("o", "Kio", "Mio", "Gio")


def human_size(size: int | float | None) -> str:
    """Taille lisible : ``1,4 Mio``.

    ``None`` — ou une valeur illisible — rend un tiret cadratin plutôt que
    « 0 o » : une taille inconnue n'est pas une taille nulle.
    """
    if size is None:
        return "—"
    try:
        value = float(size)
    except (TypeError, ValueError):
        return "—"
    for unit in BYTE_UNITS:
        if value < 1024 or unit == BYTE_UNITS[-1]:
            if unit == "o":
                return "%d %s" % (int(value), unit)
            return ("%.1f %s" % (value, unit)).replace(".", ",")
        value /= 1024.0
    return "—"


def human_duration(seconds: int | float | None) -> str:
    """Durée lisible : ``1,25 s`` ou ``3 min 07 s``."""
    try:
        value = float(seconds or 0)
    except (TypeError, ValueError):
        return "—"
    if value <= 0:
        return "—"
    if value < 60:
        return ("%.2f s" % value).replace(".", ",")
    # L'arrondi porte sur le total avant la division : arrondir le reste
    # séparément produirait des « 2 min 60 s ».
    minutes, reste = divmod(int(round(value)), 60)
    return "%d min %02d s" % (minutes, reste)


def human_datetime(value: str | None, absent: str = "—") -> str:
    """Date lisible : ``10/10/2026 à 23h57``.

    La base garde les dates en ISO (``2026-10-10T23:57:06``), ce qui se trie
    bien et se lit mal. Une valeur vide, ou illisible, rend ``absent`` — ou
    la chaîne telle quelle si elle dit quelque chose : mieux vaut un
    horodatage brut qu'un tiret, quand on cherche justement à savoir quand.
    """
    texte = str(value or "").strip()
    if not texte:
        return absent
    try:
        quand = datetime.fromisoformat(texte)
    except ValueError:
        return texte
    return quand.strftime("%d/%m/%Y à %Hh%M")


def file_size(path: Path | str) -> int:
    """Taille d'un fichier, ou 0 s'il est illisible.

    Les appelants chiffrent des plans portant sur des milliers de fichiers :
    un fichier disparu entre l'inventaire et l'affichage ne doit pas
    interrompre le calcul.
    """
    try:
        return Path(path).stat().st_size
    except (OSError, ValueError):
        return 0
