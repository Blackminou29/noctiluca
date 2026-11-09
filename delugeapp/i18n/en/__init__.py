# -*- coding: utf-8 -*-
"""Le catalogue anglais : un fichier par module du code.

Chaque fichier définit ``TEXTS``, du français vers l'anglais, pour les
textes de **son** module — ``ui_mainwindow.py`` pour
``delugeapp/ui/mainwindow.py``. Un test vérifie qu'il n'en manque aucun,
qu'aucun n'est orphelin, et qu'un même texte présent dans deux fichiers y
reçoit la même traduction.

La liste ci-dessous est explicite plutôt que découverte en parcourant le
dossier : une application empaquetée ne sait pas toujours lister ses
propres modules.
"""

from __future__ import annotations

import importlib

#: Les fichiers du catalogue, sans leur ``.py``.
MODULES: tuple[str, ...] = (
    "config",
    "core_accomp",
    "core_atelier",
    "core_audio_out",
    "core_backup",
    "core_cardimport",
    "core_cardsync",
    "core_daw",
    "core_dawals",
    "core_dawimport",
    "core_dawlive",
    "core_delugefiles",
    "core_delugelink",
    "core_deps",
    "core_dxml",
    "core_favourites",
    "core_firmware",
    "core_genres",
    "core_health",
    "core_kitgen",
    "core_midifile",
    "core_midifollow",
    "core_midiport",
    "core_multisample",
    "core_model",
    "core_organize",
    "core_rhythm",
    "core_samplefix",
    "core_scan",
    "core_sdcard",
    "core_similarity",
    "core_sketch",
    "core_slicer",
    "core_songpack",
    "core_songinsert",
    "core_songwriter",
    "core_soundedit",
    "core_synthgen",
    "core_theory",
    "core_units",
    "core_updates",
    "core_variation",
    "core_wavetable",
    "core_wav",
    "main",
    "ui_aide",
    "ui_cardwork",
    "ui_firmwaredialog",
    "ui_livewindow",
    "ui_mainwindow",
    "ui_manuel",
    "ui_pages_atelier",
    "ui_pages_base",
    "ui_pages_dashboard",
    "ui_pages_daw",
    "ui_pages_generator",
    "ui_pages_health",
    "ui_pages_kits",
    "ui_pages_samples",
    "ui_pages_settings",
    "ui_pages_songs",
    "ui_pages_synths",
    "ui_pages_toolbox",
    "ui_report",
    "ui_sendfiles",
    "ui_songexport",
    "ui_tasks",
    "ui_theme",
    "ui_widgets_atelierviews",
    "ui_widgets_chrome",
    "ui_widgets_common",
    "ui_widgets_delugescreen",
    "ui_widgets_filtercurve",
    "ui_widgets_soundeditor",
    "ui_widgets_waveform",
)


def load() -> dict[str, str]:
    """Réunit les fichiers du catalogue en un seul dictionnaire."""
    textes: dict[str, str] = {}
    for nom in MODULES:
        module = importlib.import_module(f"{__name__}.{nom}")
        textes.update(getattr(module, "TEXTS", {}))
    return textes
