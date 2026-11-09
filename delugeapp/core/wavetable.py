# -*- coding: utf-8 -*-
"""Des tables d'onde pour l'oscillateur *wavetable* du Deluge.

Le générateur écartait ce moteur faute de fichier : la carte de
l'utilisateur n'avait aucune table d'onde (7 novembre 2026). Ce module en
tire une d'un son tenu — une nappe, une voix, une note de synthé qui évolue
— en prélevant une période à intervalles réguliers, du début à la fin.

Ce que le firmware attend (1.3.0, ``storage/audio/audio_file.cpp`` et
``storage/wave_table/wave_table.cpp``) :

* un WAV ordinaire, découpé en cycles de **2 048 échantillons** par défaut ;
* ou la taille d'un cycle dans un bloc ``clm `` à la manière de Serum, dont
  il lit les sept premiers octets : ``<!>2048`` ;
* plusieurs cycles demandent une taille en **puissance de deux**, de 8 à
  65 536.

Les tables partent dans ``SAMPLES/WAVETABLES`` ; rien n'est remplacé.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from ..i18n import tr
from . import analysis, wav
from .sdcard import SDCard, norm_rel, safe_deluge_name

log = logging.getLogger(__name__)

__all__ = ["CYCLE_SIZE", "DEFAULT_CYCLES", "FOLDER", "from_sound",
           "clm_payload", "cycle_size_of", "write_wavetable"]

#: Taille d'un cycle : celle que le firmware prend par défaut.
CYCLE_SIZE = 2048

#: Cycles prélevés dans le son : de quoi parcourir son évolution.
DEFAULT_CYCLES = 64

#: Dossier des tables écrites.
FOLDER = "SAMPLES/WAVETABLES"


def clm_payload(cycle: int = CYCLE_SIZE) -> bytes:
    """Le bloc ``clm `` : le firmware en lit ``<!>`` et les quatre chiffres
    qui suivent."""
    return b"<!>%04d 00000000 wavetable (Noctiluca)" % int(cycle)


def cycle_size_of(path: Path) -> int:
    """La taille de cycle d'un fichier : celle de son bloc ``clm ``, sinon
    2 048, comme le firmware."""
    try:
        with open(path, "rb") as stream:
            tete = stream.read(1 << 16)
    except OSError:
        return CYCLE_SIZE
    i = tete.find(b"clm ")
    if i >= 0 and tete[i + 8:i + 11] == b"<!>":
        chiffres = tete[i + 11:i + 15]
        if chiffres.isdigit() and int(chiffres) >= 1:
            return int(chiffres)
    return CYCLE_SIZE


def from_sound(data: np.ndarray, sr: int, cycles: int = DEFAULT_CYCLES,
               cycle: int = CYCLE_SIZE) -> np.ndarray | None:
    """Une table d'onde tirée d'un son tenu, ou ``None`` sans hauteur nette.

    La hauteur est mesurée (:func:`analysis.estimate_root_note`) ; à
    ``cycles`` instants répartis sur la partie sonore, une période commence
    au passage par zéro montant le plus proche, et se rééchantillonne sur
    ``cycle`` points. Chaque cycle est recentré ; la table entière est
    ramenée à −1 dBFS.
    """
    mono = np.asarray(data, dtype=np.float64)
    if mono.ndim == 2:
        mono = mono.mean(axis=1)
    note = analysis.estimate_root_note(mono, sr)
    if note is None:
        return None
    periode = sr / (440.0 * 2 ** ((note - 69) / 12.0))
    start, end = analysis.silence_bounds(mono, -40.0)
    if end - start < 4 * periode:
        return None
    morceaux = []
    for k in range(int(cycles)):
        centre = start + (end - start - 2 * periode) * k / max(1, cycles - 1)
        a = int(centre)
        fenetre = mono[a:a + int(2 * periode) + 2]
        montees = np.nonzero((fenetre[:-1] <= 0) & (fenetre[1:] > 0))[0]
        if montees.size:
            a += int(montees[0])
        x = a + np.arange(cycle) * (periode / cycle)
        tranche = np.interp(x, np.arange(mono.size), mono)
        morceaux.append(tranche - tranche.mean())
    table = np.concatenate(morceaux)
    crete = float(np.max(np.abs(table)))
    if crete <= 1e-6:
        return None
    return (table * (10 ** (-1 / 20.0) / crete)).astype(np.float32)


def write_wavetable(sd: SDCard, source_rel: str, name: str = "",
                    apply: bool = False) -> tuple[str, str]:
    """Écrit la table d'onde de ``source_rel`` dans :data:`FOLDER`.

    Rend ``(chemin, erreur)`` ; sans ``apply``, le chemin seulement. Un nom
    pris est numéroté.
    """
    path = sd.resolve_sample(source_rel)
    if path is None:
        return "", tr("son introuvable : %s") % source_rel
    stem = safe_deluge_name(name or Path(source_rel).stem) or "TABLE"
    rel, n = "%s/%s.wav" % (FOLDER, stem), 2
    while sd.abs(rel).exists():
        rel = "%s/%s %d.wav" % (FOLDER, stem, n)
        n += 1
    if not apply:
        return rel, ""
    try:
        data, sr = wav.read(path, max_frames=sr_max(), mono=True)
    except Exception as exc:  # noqa: BLE001 - un fichier abîmé ne bloque rien
        return "", tr("son illisible : %s") % exc
    table = from_sound(data, sr)
    if table is None:
        return "", tr("aucune hauteur nette dans ce son : une table d'onde "
                      "se tire d'un son tenu, une note qui dure")
    sd.require_writable()
    cible = sd.abs(rel)
    cible.parent.mkdir(parents=True, exist_ok=True)
    wav.write(cible, table, 44100, 16,
              extra_chunks=[(b"clm ", clm_payload())])
    sd.invalidate_cache()
    log.info("table d'onde écrite : %s (%d cycles)", rel,
             table.size // CYCLE_SIZE)
    return rel, ""


def sr_max() -> int:
    """Trames lues au plus dans le son source : 20 s à 48 kHz."""
    return 20 * 48000


def is_wavetable_rel(rel: str) -> bool:
    """Vrai pour un fichier du dossier des tables d'onde."""
    return norm_rel(rel).startswith(norm_rel(FOLDER) + "/")
