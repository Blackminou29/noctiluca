# -*- coding: utf-8 -*-
"""Les sons compressés — MP3, FLAC, Ogg Vorbis —, que le Deluge ne lit pas :
décodés en WAV à l'envoi (:mod:`.cardimport`).

Le décodage passe par ``miniaudio`` (licence MIT : le paquet d'Irmen de
Jong, la bibliothèque de David Reid, stb_vorbis de Sean Barrett). Il est
facultatif : sans lui, ces fichiers restent sur le PC, comme avant, avec le
conseil de les exporter en WAV.

Mesuré le 14 novembre 2026 (miniaudio 1.71) sur des fichiers faits par
ffmpeg à partir de WAV connus :

* un FLAC revient **à l'échantillon près**, en 16 comme en 24 bits ; l'en-tête
  donne la profondeur d'origine (``SIGNED16``, ``SIGNED24``), que le WAV
  garde ;
* un MP3 ou un Ogg revient calé sur l'original, même nombre de trames (le
  décodeur retire le délai de l'encodeur) ; l'écart est celui de la
  compression. L'en-tête annonce 16 bits : le WAV aussi ;
* sans qu'on le lui demande, ``decode_file`` rend tout en stéréo à
  44,1 kHz — un MP3 mono à 22 kHz devenait stéréo, un FLAC à 96 kHz perdait
  sa fréquence. On lui donne donc celles de l'en-tête, et la conversion de
  l'envoi décide seule de ce que la machine accepte.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..i18n import tr, untranslated
from . import wav

log = logging.getLogger(__name__)

__all__ = ["EXTENSIONS", "CompressedInfo", "available", "format_name",
           "probe", "to_wav"]

#: Ce que le décodeur lit. Le M4A, l'AAC, le WMA et l'Opus restent dehors.
EXTENSIONS = (".mp3", ".flac", ".ogg")
_NAMES = untranslated({".mp3": "MP3", ".flac": "FLAC", ".ogg": "Ogg Vorbis"})

try:
    import miniaudio as _ma
except Exception:  # noqa: BLE001 - absent, ou sa bibliothèque refuse
    _ma = None


def available() -> bool:
    """Le décodeur est-il là ?"""
    return _ma is not None


def format_name(path: Path | str) -> str:
    """« MP3 », « FLAC »… d'après l'extension."""
    return _NAMES.get(Path(path).suffix.lower(), Path(path).suffix.upper())


@dataclass
class CompressedInfo:
    """L'en-tête d'un son compressé, lu sans le décoder."""

    ok: bool
    error: str = ""
    channels: int = 0
    sample_rate: int = 0
    frames: int = 0
    #: La profondeur que garde le WAV : 24 pour un FLAC 24 bits, 16 sinon.
    bit_depth: int = 16

    @property
    def wav_size(self) -> int:
        """La taille du WAV qu'il deviendra — c'est elle qui passe par le
        câble."""
        return 44 + self.frames * self.channels * self.bit_depth // 8


def probe(path: Path) -> CompressedInfo:
    """Canaux, fréquence, longueur et profondeur d'un son compressé."""
    if _ma is None:
        return CompressedInfo(False, untranslated("miniaudio absent"))
    try:
        info = _ma.get_file_info(str(path))
    except Exception as exc:  # noqa: BLE001 - fichier abîmé, Opus dans un Ogg…
        return CompressedInfo(False, str(exc).strip() or exc.__class__.__name__)
    if info.nchannels <= 0 or info.sample_rate <= 0 or info.num_frames <= 0:
        return CompressedInfo(False, tr("vide"))
    fmt = getattr(info.sample_format, "name", "")
    profondeur = 24 if fmt in ("SIGNED24", "SIGNED32", "FLOAT32") else 16
    return CompressedInfo(True, "", int(info.nchannels),
                          int(info.sample_rate), int(info.num_frames),
                          profondeur)


def to_wav(src: Path, dst: Path) -> CompressedInfo:
    """Décode ``src`` en WAV dans ``dst``, à ses canaux, sa fréquence et sa
    profondeur d'origine. Lève ``ValueError`` s'il ne se décode pas."""
    info = probe(src)
    if not info.ok:
        raise ValueError(info.error)
    try:
        son = _ma.decode_file(str(src),
                              output_format=_ma.SampleFormat.FLOAT32,
                              nchannels=info.channels,
                              sample_rate=info.sample_rate)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(str(exc).strip() or exc.__class__.__name__) from exc
    trames = np.frombuffer(son.samples, dtype=np.float32).reshape(
        -1, son.nchannels)
    if trames.shape[0] == 0:
        raise ValueError(tr("vide"))
    wav.write(dst, trames, son.sample_rate, info.bit_depth)
    log.info("%s décodé : %d trames, %d Hz, %d canal(aux), %d bits",
             Path(src).name, trames.shape[0], son.sample_rate, son.nchannels,
             info.bit_depth)
    return info
