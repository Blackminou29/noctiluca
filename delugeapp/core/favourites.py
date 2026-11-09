# -*- coding: utf-8 -*-
"""Les favoris du Deluge : seize pads par banque, seize banques.

Le firmware 1.3 range les favoris de ses navigateurs dans
``SETTINGS/FAVOURITES/<CATÉGORIE>_Bank<N>.xml`` — ``SAMPLES``, ``SYNTHS``,
``KITS``, ``SONG``… (``model/favourite/favourite_manager.cpp``, 1.3.0). Sur
la carte de l'utilisateur, le 7 novembre 2026, ces fichiers existaient et
étaient vides : le format vient donc du code, pas d'un exemple.

::

    <?xml version="1.0" encoding="UTF-8"?>
    <favourites>
        <favourite
            position="0"
            colour="4"
            instrumentPresetFolder="SAMPLES/DRUMS/Kick/808 Kick.wav" />
    </favourites>

``position`` est le pad (0 à 15), ``colour`` sa couleur (4 par défaut,
``favouriteDefaultColor``), et ``instrumentPresetFolder`` — malgré son nom —
le **chemin complet du fichier**. Une banque absente est créée vide par la
machine au premier passage dans le navigateur.

Ce que l'application en fait :

* les favoris d'échantillons de la machine deviennent des favoris de
  l'application (:func:`import_samples`), sans jamais en retirer un ;
* un son peut rejoindre un pad libre (:func:`plan_add`, :func:`write`) — ou
  le quitter (:func:`plan_remove`). La banque est réécrite entière, comme la
  machine le fait ; l'ancienne version est gardée dans ``_BACKUP``.

**La machine garde la banque ouverte en mémoire** tant que son navigateur
l'affiche, et la réécrit à chaque pad qu'on y change : une banque modifiée
ici pendant que le navigateur est ouvert serait écrasée au geste suivant sur
la machine. L'interface le dit.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from ..i18n import tr, untranslated
from . import dxml
from .sdcard import SDCard, norm_rel

log = logging.getLogger(__name__)

__all__ = ["Favourite", "BANKS", "PADS", "DEFAULT_COLOUR", "bank_rel",
           "read", "favourite_of", "plan_add", "plan_remove", "write",
           "import_samples"]

#: Banques et pads par catégorie (``kNumFavourites``, ``selectFavouritesBank``).
BANKS = 16
PADS = 16

#: Couleur d'un favori posé sur la machine (``favouriteDefaultColor``).
DEFAULT_COLOUR = 4

_BANK_RE = re.compile(r"^(?P<cat>[A-Z]+)_Bank(?P<n>\d+)\.xml$", re.I)


@dataclass(frozen=True)
class Favourite:
    """Un pad de favori : sa banque, sa place, sa couleur, son fichier."""

    bank: int
    position: int
    colour: int
    path: str


def bank_rel(category: str, bank: int) -> str:
    """Le fichier d'une banque, comme le nomme le firmware."""
    return "SETTINGS/FAVOURITES/%s_Bank%d.xml" % (category, int(bank))


def read(sd: SDCard, category: str) -> list[Favourite]:
    """Tous les favoris d'une catégorie, banque par banque."""
    out: list[Favourite] = []
    dossier = sd.abs("SETTINGS/FAVOURITES")
    try:
        fichiers = sorted(dossier.iterdir())
    except OSError:
        return out
    for fichier in fichiers:
        m = _BANK_RE.match(fichier.name)
        if m is None or m.group("cat").upper() != category.upper():
            continue
        bank = int(m.group("n"))
        if not 0 <= bank < BANKS:
            continue
        try:
            doc = dxml.load(fichier)
        except (OSError, dxml.DelugeXMLError) as exc:
            log.debug("banque de favoris illisible %s : %s", fichier, exc)
            continue
        for el in doc.root.iter("favourite"):
            try:
                position = int(dxml.get(el, "position", "-1"))
                colour = int(dxml.get(el, "colour", str(DEFAULT_COLOUR)))
            except (TypeError, ValueError):
                continue
            path = (dxml.get(el, "instrumentPresetFolder", "") or "").strip()
            if 0 <= position < PADS and path:
                out.append(Favourite(bank, position, colour, path))
    return out


def favourite_of(sd: SDCard, category: str, rel: str) -> Favourite | None:
    """Le pad qui porte ce fichier, s'il y en a un."""
    cle = norm_rel(rel)
    return next((f for f in read(sd, category) if norm_rel(f.path) == cle),
                None)


def plan_add(sd: SDCard, category: str, rel: str) -> Favourite | None:
    """Le premier pad libre pour ce fichier, banque par banque ; ``None`` si
    les 256 sont pris. Un fichier déjà favori garde son pad."""
    existant = favourite_of(sd, category, rel)
    if existant is not None:
        return existant
    pris = {(f.bank, f.position) for f in read(sd, category)}
    for bank in range(BANKS):
        for position in range(PADS):
            if (bank, position) not in pris:
                return Favourite(bank, position, DEFAULT_COLOUR, rel)
    return None


def plan_remove(sd: SDCard, category: str, rel: str) -> Favourite | None:
    """Le pad à libérer pour ce fichier, s'il est favori."""
    return favourite_of(sd, category, rel)


def _xml(favoris: list[Favourite]) -> str:
    """Une banque, écrite comme l'écrit ``XMLSerializer``."""
    lignes = [untranslated('<?xml version="1.0" encoding="UTF-8"?>'),
              "<favourites>"]
    for fav in sorted(favoris, key=lambda f: f.position):
        lignes += ["\t<favourite",
                   '\t\tposition="%d"' % fav.position,
                   '\t\tcolour="%d"' % fav.colour,
                   untranslated('\t\tinstrumentPresetFolder="%s" />')
                   % dxml._escape_attr(fav.path)]
    lignes.append("</favourites>")
    return "\n".join(lignes) + "\n"


def write(sd: SDCard, category: str, add: Favourite | None = None,
          remove: Favourite | None = None, apply: bool = False) -> str:
    """Réécrit la banque touchée : le chemin de la banque, ou lève
    ``ValueError``. Sans ``apply``, rien n'est écrit."""
    cible = add or remove
    if cible is None:
        raise ValueError(tr("aucun favori à changer"))
    rel = bank_rel(category, cible.bank)
    favoris = [f for f in read(sd, category) if f.bank == cible.bank]
    if add is not None:
        if any(f.position == add.position and norm_rel(f.path)
               != norm_rel(add.path) for f in favoris):
            raise ValueError(tr("le pad %d de la banque %d est déjà pris")
                             % (add.position + 1, add.bank + 1))
        favoris = [f for f in favoris if f.position != add.position] + [add]
    if remove is not None:
        favoris = [f for f in favoris if f.position != remove.position]
    if not apply:
        return rel
    sd.require_writable()
    chemin = sd.abs(rel)
    if chemin.is_file():
        from .samplefix import BACKUP_ROOT

        garde = sd.abs("%s/favoris-%s" % (BACKUP_ROOT,
                                          time.strftime("%Y-%m-%d_%H%M%S")))
        garde = garde / Path(rel)
        garde.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(chemin, garde)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    provisoire = chemin.with_name(chemin.name + ".tmp")
    provisoire.write_text(_xml(favoris), encoding="utf-8", newline="\n")
    os.replace(provisoire, chemin)
    sd.invalidate_cache()
    log.info("favoris du Deluge : %s réécrit (%d pad(s))", rel, len(favoris))
    return rel


def import_samples(sd: SDCard, lib) -> int:
    """Les échantillons favoris de la machine deviennent favoris de
    l'application. Ne retire jamais un favori ; rend combien sont neufs."""
    neufs = 0
    for fav in read(sd, "SAMPLES"):
        rel = fav.path
        try:
            if lib.get("sample", rel) is None:
                continue
            if lib.get_rating("sample", rel).get("favorite"):
                continue
            lib.set_rating("sample", rel, favorite=True)
            neufs += 1
        except Exception:  # noqa: BLE001 - un favori n'arrête rien
            log.debug("favori %s non repris", rel, exc_info=True)
    if neufs:
        log.info("%d favori(s) du Deluge repris dans l'application", neufs)
    return neufs
