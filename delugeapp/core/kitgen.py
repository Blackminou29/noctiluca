# -*- coding: utf-8 -*-
"""Générateur de kits de batterie.

Assemble un kit en piochant un échantillon par rôle dans la bibliothèque
indexée. Deux façons de faire :

* :func:`build_kit` choisit lui-même les échantillons, par rôle et par genre,
  en s'appuyant sur la catégorie déduite lors de l'analyse ;
* :func:`kit_from_folder` prend tout un dossier tel quel, ce qui correspond à
  la façon dont les banques d'échantillons sont livrées.

Chaque rangée reçoit une enveloppe et un volume adaptés à son rôle : une
grosse caisse n'a pas la même extinction qu'une cymbale, et laisser les
réglages par défaut donne un kit où tout sonne pareil.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from pathlib import Path

from .db import Library
from .fixedpoint import from_display
from .genres import genre as get_genre
from .model import Kit, KitRow
from .sdcard import SDCard, norm_rel, safe_deluge_name

log = logging.getLogger(__name__)

#: Rangées d'un kit par défaut, dans l'ordre des pads du Deluge.
DEFAULT_SLOTS: tuple[str, ...] = (
    "Kick", "Snare", "HatC", "HatO", "Clap", "Rim",
    "TomL", "TomM", "TomH", "Crash", "Ride", "Shaker",
)

#: Rangées conseillées par genre, quand le genre a des habitudes marquées.
GENRE_SLOTS: dict[str, tuple[str, ...]] = {
    "acid": ("Kick", "Snare", "HatC", "HatO", "Clap", "Cowbell",
             "TomL", "TomM", "Rim", "Crash"),
    "techno": ("Kick", "Clap", "HatC", "HatO", "Snare", "Rim",
               "TomL", "Crash", "Shaker", "Ride"),
    "minimal": ("Kick", "HatC", "Clap", "Rim", "Shaker", "Block",
                "Claves", "HatO"),
    "house": ("Kick", "Clap", "HatC", "HatO", "Snare", "Shaker",
              "Cowbell", "TomM", "Rim", "Ride"),
    "deep_house": ("Kick", "Clap", "HatC", "HatO", "Shaker", "Rim",
                   "ConH", "ConL", "Snare", "Ride"),
    "dnb": ("Kick", "Snare", "HatC", "HatO", "Rim", "Clap",
            "TomL", "TomM", "Crash", "Ride"),
    "jungle": ("Kick", "Snare", "HatC", "HatO", "Rim", "ConH",
               "ConL", "Shaker", "Crash", "Timpany"),
    "dubstep": ("Kick", "Snare", "HatC", "HatO", "Clap", "Rim",
                "TomL", "Crash", "China", "Ride"),
    "electro": ("Kick", "Snare", "HatC", "HatO", "Clap", "Cowbell",
                "TomL", "TomM", "TomH", "Crash"),
    "industrial": ("Kick", "Snare", "HatC", "Rim", "Crash", "China",
                   "Block", "TomL", "TomM", "Clap"),
    "hardcore": ("Kick", "Snare", "HatC", "HatO", "Clap", "Crash",
                 "China", "TomL", "Rim", "Ride"),
    "lofi": ("Kick", "Snare", "HatC", "HatO", "Rim", "Shaker",
             "Tambourine", "Block", "ConM", "Clap"),
    "boards_of_canada": ("Kick", "Snare", "HatC", "Shaker", "Tambourine",
                         "Block", "ConM", "Rim", "HatO", "Ride"),
}

#: Réglages par rôle : ``(volume affiché, decay affiché, sustain affiché)``.
#:
#: Une percussion se règle en decay, sustain à zéro : la note s'éteint d'elle
#: même. Seules les cymbales gardent une longue extinction.
ROLE_SETTINGS: dict[str, tuple[int, int, int]] = {
    "Kick": (44, 22, 0),
    "Snare": (40, 18, 0),
    "Clap": (38, 16, 0),
    "Rim": (36, 10, 0),
    "HatC": (34, 8, 0),
    "HatO": (34, 22, 0),
    "Crash": (32, 40, 0),
    "Ride": (32, 34, 0),
    "China": (32, 38, 0),
    "TomL": (38, 20, 0),
    "TomM": (38, 18, 0),
    "TomH": (38, 16, 0),
    "ConL": (36, 16, 0),
    "ConM": (36, 14, 0),
    "ConH": (36, 12, 0),
    "Cowbell": (34, 14, 0),
    "Block": (34, 8, 0),
    "Claves": (34, 8, 0),
    "Shaker": (30, 12, 0),
    "Tambourine": (32, 14, 0),
    "Guiro": (32, 16, 0),
    "Timpany": (38, 26, 0),
    "Other": (36, 18, 0),
}

#: Durée maximale d'un échantillon retenu comme percussion, en secondes.
MAX_SLOT_SECONDS = 4.0


@dataclass
class KitSlot:
    """Un emplacement de kit et l'échantillon qui l'occupe."""

    role: str
    rel: str = ""
    name: str = ""

    @property
    def filled(self) -> bool:
        """Vrai si un échantillon a été trouvé pour ce rôle."""
        return bool(self.rel)


def suggest_slots(genre: str) -> list[str]:
    """Rangées conseillées pour un genre."""
    key = str(genre or "").strip().lower()
    return list(GENRE_SLOTS.get(key, DEFAULT_SLOTS))


def _candidates(lib: Library, role: str, prefer_folder: str = "") -> list:
    """Échantillons plausibles pour un rôle, les mieux placés d'abord.

    Deux sources, par ordre de confiance : la catégorie déduite à l'analyse
    (qui vient elle-même du rangement et du nom du fichier), puis une
    recherche sur le nom pour les bibliothèques non rangées.
    """
    rows: list = []
    seen: set[str] = set()

    def _collect(found) -> None:
        for row in found:
            rel = row["rel"]
            if rel in seen:
                continue
            duration = row["duration"] or 0.0
            if duration <= 0 or duration > MAX_SLOT_SECONDS:
                continue
            seen.add(rel)
            rows.append(row)

    try:
        _collect(lib.search_samples(category=role, limit=4000))
        _collect(lib.search_samples(text=role, limit=2000))
    except Exception as exc:  # noqa: BLE001 - index indisponible
        log.debug("recherche d'échantillons pour %s impossible : %s", role, exc)
        return []

    if prefer_folder:
        wanted = norm_rel(prefer_folder)
        rows.sort(key=lambda r: 0 if norm_rel(r["rel"]).startswith(wanted) else 1)
    return rows


def build_kit(sd: SDCard, lib: Library, name: str, genre: str = "techno",
              seed: int | None = None, slots: list[str] | None = None,
              prefer_folder: str = "") -> Kit:
    """Assemble un kit en choisissant un échantillon par rôle.

    :param slots: rôles à remplir ; par défaut ceux conseillés pour le genre.
    :param prefer_folder: dossier à privilégier, pour bâtir un kit cohérent à
        partir d'une seule banque.
    :param seed: rend le choix reproductible.

    Les rôles sans candidat sont **omis** plutôt que laissés vides : un kit
    avec des rangées muettes est plus déroutant qu'un kit plus court.
    """
    # Le genre entre dans la graine : sans cela, une même graine donnait la
    # même grosse caisse à tous les genres, puisque le premier tirage portait
    # sur le même ensemble de candidats.
    base = seed if seed is not None else random.randrange(1 << 30)
    rng = random.Random(f"{base}|{genre}")
    wanted = list(slots) if slots else suggest_slots(genre)
    profile = get_genre(genre)

    kit = Kit.new(safe_deluge_name(name or f"KIT {profile.label}"))
    kit.rows = []
    chosen: list[KitSlot] = []

    for role in wanted:
        rows = _candidates(lib, role, prefer_folder)
        if not rows:
            chosen.append(KitSlot(role=role))
            log.debug("aucun échantillon pour le rôle %s", role)
            continue
        # On tire dans les meilleurs candidats plutôt que de prendre le
        # premier : deux kits du même genre ne doivent pas être identiques.
        pool = rows[:max(1, min(len(rows), 12))]
        row = rng.choice(pool)
        slot = KitSlot(role=role, rel=row["rel"], name=Path(row["rel"]).stem)
        chosen.append(slot)

        kit_row = kit.add_row(safe_deluge_name(role.upper()), slot.rel)
        _tune_row(kit_row, role)

    kit_rel = [s for s in chosen if s.filled]
    log.info("kit « %s » : %d rangée(s) sur %d rôle(s) demandés",
             kit.name, len(kit_rel), len(wanted))
    return kit


def _tune_row(row: KitRow, role: str) -> None:
    """Règle volume et enveloppe d'une rangée selon son rôle."""
    volume, decay, sustain = ROLE_SETTINGS.get(role, ROLE_SETTINGS["Other"])
    sound = row.sound
    sound.set_param("volume", from_display(volume, scale=50))
    sound.env1.attack = from_display(0, scale=50)
    sound.env1.decay = from_display(decay, scale=50)
    sound.env1.sustain = from_display(sustain, scale=50)
    sound.env1.release = from_display(max(2, decay // 2), scale=50)
    # Une percussion est monophonique : deux déclenchements successifs se
    # coupent l'un l'autre plutôt que de s'empiler.
    sound.polyphonic = "choke" if role in ("HatC", "HatO") else "mono"


def kit_from_folder(sd: SDCard, folder: str, name: str = "") -> Kit:
    """Crée un kit depuis tous les échantillons d'un dossier.

    Les fichiers sont pris dans l'ordre alphabétique, ce qui respecte la
    numérotation des banques (``01 Kick``, ``02 Snare``…). Le rôle de chaque
    rangée est déduit du nom du fichier.
    """
    from .analysis import classify_drum

    base = sd.resolve_sample(folder)
    kit = Kit.new(safe_deluge_name(name or (base.name if base else "KIT")))
    kit.rows = []
    if base is None or not base.is_dir():
        log.warning("dossier introuvable pour le kit : %r", folder)
        return kit

    from .sdcard import AUDIO_EXT, _is_ignored_file

    files = sorted(
        (p for p in base.iterdir()
         if p.is_file() and not _is_ignored_file(p.name)
         and p.suffix.lower() in AUDIO_EXT),
        key=lambda p: p.name.lower())

    for path in files[:64]:        # le Deluge n'affiche pas plus de pads
        rel = sd.rel(path)
        role = classify_drum(path.name, {"duration": 0.5}, {})
        row = kit.add_row(safe_deluge_name(path.stem.upper())[:32], rel)
        _tune_row(row, role)

    log.info("kit « %s » : %d rangée(s) depuis %s", kit.name, len(kit.rows),
             folder)
    return kit
