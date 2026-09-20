# -*- coding: utf-8 -*-
"""Lecture et écriture de fichiers audio WAV / AIFF sans dépendance externe.

Seuls ``struct`` et ``numpy`` sont utilisés. Aucune fonction retournant un
:class:`AudioInfo` ne lève d'exception : en cas de problème l'objet retourné
porte ``ok=False`` et un message dans ``error``.

Formats lus :
  * RIFF/WAVE (ainsi que RIFX big-endian, RF64/BW64) : PCM 8 bits non signé,
    PCM 16/24/32 bits signés little-endian, IEEE float 32/64, A-law, µ-law,
    WAVE_FORMAT_EXTENSIBLE (fmt de 40 octets, sous-format GUID).
  * AIFF / AIFC big-endian : PCM 8/16/24/32, ``sowt``/``twos``/``raw ``,
    ``fl32``/``fl64``, ``in24``/``in32``, ``ulaw``/``alaw``.

Les chunks ``LIST``/``bext``/``cue ``/``JUNK`` sont ignorés ; ``smpl`` (WAV) et
``INST`` + ``MARK`` (AIFF) fournissent la boucle et la note fondamentale.
Les tailles de chunk impaires (octet de bourrage) et les fichiers tronqués
sont gérés.
"""

from __future__ import annotations

import logging
import math
import os
import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

__all__ = ["AudioInfo", "probe", "read", "write", "peaks", "convert"]

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

WAVE_FORMAT_PCM = 0x0001
WAVE_FORMAT_FLOAT = 0x0003
WAVE_FORMAT_ALAW = 0x0006
WAVE_FORMAT_ULAW = 0x0007
WAVE_FORMAT_EXTENSIBLE = 0xFFFE

#: Nombre maximal de chunks parcourus (garde-fou contre les fichiers corrompus).
_MAX_CHUNKS = 512
#: Taille de la lecture anticipée de l'en-tête (un seul appel système typique).
_PREFETCH = 8192
#: Taille de bloc pour les lectures/écritures en flux.
_BLOCK_BYTES = 1 << 20

_EXT_AIFF = (".aif", ".aiff", ".aifc")


# ---------------------------------------------------------------------------
# Structure publique
# ---------------------------------------------------------------------------

@dataclass
class AudioInfo:
    """Description d'un fichier audio (obtenue à partir des seuls en-têtes)."""

    path: Path
    sample_rate: int = 0
    channels: int = 0
    bit_depth: int = 0
    frames: int = 0
    duration: float = 0.0
    fmt: str = ""                       # 'pcm' | 'float' | 'aiff'
    loop_start: int | None = None
    loop_end: int | None = None
    root_note: int | None = None
    ok: bool = False
    error: str = ""


class _AudioError(Exception):
    """Erreur interne de décodage (jamais propagée hors du module)."""


# ---------------------------------------------------------------------------
# En-tête interne
# ---------------------------------------------------------------------------

@dataclass
class _Header:
    """En-tête décodé : tout ce qu'il faut pour lire les octets audio."""

    container: str = "wav"              # 'wav' | 'aiff'
    sample_rate: int = 0
    channels: int = 0
    bits: int = 0                       # bits par échantillon (conteneur)
    sample_bytes: int = 0               # octets par échantillon
    encoding: str = "pcm-s"             # pcm-s | pcm-u | float | ulaw | alaw
    big_endian: bool = False
    frames: int = 0
    data_offset: int = 0
    data_size: int = 0
    fmt: str = "pcm"                    # valeur exposée par AudioInfo.fmt
    loop_start: int | None = None
    loop_end: int | None = None
    root_note: int | None = None

    @property
    def frame_bytes(self) -> int:
        """Octets par trame (tous canaux confondus)."""
        return max(1, self.channels * self.sample_bytes)


class _Reader:
    """Lecteur d'en-tête à tampon : évite les allers-retours disque inutiles."""

    __slots__ = ("f", "size", "buf", "buf_end")

    def __init__(self, f, size: int) -> None:
        self.f = f
        self.size = size
        self.buf = f.read(_PREFETCH)
        self.buf_end = len(self.buf)

    def at(self, off: int, n: int) -> bytes:
        """Lit ``n`` octets à la position absolue ``off``."""
        if n <= 0 or off < 0:
            return b""
        if off + n <= self.buf_end:
            return self.buf[off:off + n]
        self.f.seek(off)
        return self.f.read(n)


# ---------------------------------------------------------------------------
# Tables A-law / µ-law (G.711)
# ---------------------------------------------------------------------------

def _build_ulaw() -> np.ndarray:
    """Table de décodage µ-law -> float32."""
    u = (~np.arange(256, dtype=np.int32)) & 0xFF
    t = ((u & 0x0F) << 3) + 0x84
    t = t << ((u & 0x70) >> 4)
    v = np.where(u & 0x80, 0x84 - t, t - 0x84)
    return (v.astype(np.float32) / 32768.0)


def _build_alaw() -> np.ndarray:
    """Table de décodage A-law -> float32."""
    a = np.arange(256, dtype=np.int32) ^ 0x55
    man = (a & 0x0F) << 4
    seg = (a & 0x70) >> 4
    small = man + 8
    big = (man + 0x108) << np.maximum(seg - 1, 0)
    t = np.where(seg == 0, small, big)
    v = np.where(a & 0x80, t, -t)
    return (v.astype(np.float32) / 32768.0)


_ULAW_TABLE: np.ndarray | None = None
_ALAW_TABLE: np.ndarray | None = None


def _ulaw_table() -> np.ndarray:
    global _ULAW_TABLE
    if _ULAW_TABLE is None:
        _ULAW_TABLE = _build_ulaw()
    return _ULAW_TABLE


def _alaw_table() -> np.ndarray:
    global _ALAW_TABLE
    if _ALAW_TABLE is None:
        _ALAW_TABLE = _build_alaw()
    return _ALAW_TABLE


# ---------------------------------------------------------------------------
# Flottant étendu 80 bits (taux d'échantillonnage AIFF)
# ---------------------------------------------------------------------------

def _ext80_to_float(b: bytes) -> float:
    """Décode un flottant étendu IEEE 80 bits."""
    if len(b) < 10:
        return 0.0
    expon = struct.unpack(">H", b[0:2])[0]
    himant, lomant = struct.unpack(">II", b[2:10])
    sign = -1.0 if (expon & 0x8000) else 1.0
    expon &= 0x7FFF
    if expon == 0 and himant == 0 and lomant == 0:
        return 0.0
    if expon == 0x7FFF:
        return 0.0
    expon -= 16383
    try:
        value = himant * (2.0 ** (expon - 31)) + lomant * (2.0 ** (expon - 63))
    except OverflowError:
        return 0.0
    return sign * value


def _float_to_ext80(v: float) -> bytes:
    """Encode un flottant en étendu IEEE 80 bits."""
    sign = 0
    if v < 0:
        sign = 0x8000
        v = -v
    if v == 0 or not math.isfinite(v):
        return b"\x00" * 10
    mant, exp = math.frexp(v)           # v = mant * 2**exp, 0.5 <= mant < 1
    expon = exp - 1 + 16383
    if expon <= 0:
        return b"\x00" * 10
    if expon > 0x7FFE:
        expon = 0x7FFE
    m = int(mant * (2.0 ** 64))
    m = min(m, (1 << 64) - 1)
    return struct.pack(">HII", sign | expon, (m >> 32) & 0xFFFFFFFF, m & 0xFFFFFFFF)


# ---------------------------------------------------------------------------
# Analyse des en-têtes
# ---------------------------------------------------------------------------

def _printable_id(cid: bytes) -> bool:
    """Vrai si l'identifiant de chunk est plausible (ASCII imprimable)."""
    return len(cid) == 4 and all(0x20 <= c <= 0x7E for c in cid)


def _parse_riff(rd: _Reader) -> _Header:
    """Analyse un conteneur RIFF/RIFX/RF64 de forme WAVE."""
    head = rd.at(0, 12)
    if len(head) < 12:
        raise _AudioError("fichier trop court")
    magic, form = head[0:4], head[8:12]
    if form != b"WAVE":
        raise _AudioError("conteneur RIFF sans forme WAVE")
    big = magic == b"RIFX"
    u32 = ">I" if big else "<I"
    u16 = ">H" if big else "<H"
    end = ">" if big else "<"
    h = _Header(container="wav", big_endian=big)

    pos = 12
    size = rd.size
    got_fmt = False
    data_off = -1
    data_size = -1
    ds64_data: int | None = None
    ds64_frames: int | None = None
    count = 0

    while pos + 8 <= size and count < _MAX_CHUNKS:
        count += 1
        hdr = rd.at(pos, 8)
        if len(hdr) < 8:
            break
        cid = hdr[0:4]
        if not _printable_id(cid):
            break
        csz = struct.unpack(u32, hdr[4:8])[0]
        body = pos + 8
        avail = max(0, size - body)
        truncated = csz > avail
        take = avail if truncated else csz

        if cid == b"fmt ":
            d = rd.at(body, min(take, 64))
            if len(d) < 16:
                raise _AudioError("chunk fmt incomplet")
            af, nch, sr, _brate, balign, bps = struct.unpack(
                end + "HHIIHH", d[:16])
            if af == WAVE_FORMAT_EXTENSIBLE:
                if len(d) >= 40:
                    af = struct.unpack(u16, d[24:26])[0]
                else:
                    af = WAVE_FORMAT_PCM            # repli raisonnable
            bits = int(bps)
            if af == WAVE_FORMAT_PCM:
                h.encoding = "pcm-u" if bits == 8 else "pcm-s"
                h.fmt = "pcm"
                if bits <= 0:
                    raise _AudioError("nombre de bits invalide")
            elif af == WAVE_FORMAT_FLOAT:
                h.encoding = "float"
                h.fmt = "float"
                if bits not in (32, 64):
                    bits = 32
            elif af == WAVE_FORMAT_ULAW:
                h.encoding = "ulaw"
                h.fmt = "pcm"
                bits = 8
            elif af == WAVE_FORMAT_ALAW:
                h.encoding = "alaw"
                h.fmt = "pcm"
                bits = 8
            else:
                raise _AudioError("format WAV non géré (code 0x%04X)" % af)
            h.bits = bits
            h.sample_bytes = max(1, (bits + 7) // 8)
            h.channels = int(nch)
            h.sample_rate = int(sr)
            if h.channels <= 0:
                # en-tête cassé : déduire le nombre de canaux du bloc
                if balign and balign % h.sample_bytes == 0:
                    h.channels = max(1, int(balign) // h.sample_bytes)
                else:
                    h.channels = 1
            got_fmt = True

        elif cid == b"data":
            data_off = body
            data_size = avail if (truncated or csz == 0xFFFFFFFF) else csz

        elif cid == b"ds64":
            d = rd.at(body, min(take, 28))
            if len(d) >= 24:
                _riff_sz, dsz, nsamp = struct.unpack("<QQQ", d[:24])
                ds64_data = int(dsz)
                ds64_frames = int(nsamp)

        elif cid == b"smpl":
            d = rd.at(body, min(take, 36 + 24))
            if len(d) >= 36:
                vals = struct.unpack(end + "9I", d[:36])
                unity = vals[3]
                nloops = vals[7]
                if 0 <= unity <= 127:
                    h.root_note = int(unity)
                if nloops and len(d) >= 36 + 24:
                    lp = struct.unpack(end + "6I", d[36:60])
                    h.loop_start = int(lp[2])
                    h.loop_end = int(lp[3])

        elif cid == b"inst":
            d = rd.at(body, min(take, 7))
            if len(d) >= 1 and h.root_note is None and 0 <= d[0] <= 127:
                h.root_note = int(d[0])

        if truncated:
            break
        pos = body + csz + (csz & 1)

    if not got_fmt:
        raise _AudioError("chunk fmt absent")
    if data_off < 0:
        raise _AudioError("chunk data absent")
    if h.sample_rate <= 0:
        raise _AudioError("taux d'échantillonnage invalide")

    if ds64_data is not None and 0 < ds64_data <= size - data_off:
        data_size = ds64_data
    if data_size <= 0:
        data_size = max(0, size - data_off)
    data_size = min(data_size, max(0, size - data_off))

    h.data_offset = data_off
    h.data_size = data_size - (data_size % h.frame_bytes)
    h.frames = h.data_size // h.frame_bytes
    if ds64_frames and 0 < ds64_frames <= h.frames:
        h.frames = ds64_frames
        h.data_size = h.frames * h.frame_bytes
    return h


#: Type de compression AIFC -> (encodage interne, big-endian)
_AIFC_ENCODINGS = {
    b"NONE": ("pcm-s", True),
    b"none": ("pcm-s", True),
    b"twos": ("pcm-s", True),
    b"TWOS": ("pcm-s", True),
    b"sowt": ("pcm-s", False),
    b"SOWT": ("pcm-s", False),
    b"in24": ("pcm-s", True),
    b"IN24": ("pcm-s", True),
    b"in32": ("pcm-s", True),
    b"IN32": ("pcm-s", True),
    b"23ni": ("pcm-s", False),
    b"42ni": ("pcm-s", False),
    b"raw ": ("pcm-u", True),
    b"RAW ": ("pcm-u", True),
    b"fl32": ("float", True),
    b"FL32": ("float", True),
    b"fl64": ("float", True),
    b"FL64": ("float", True),
    b"ulaw": ("ulaw", True),
    b"ULAW": ("ulaw", True),
    b"alaw": ("alaw", True),
    b"ALAW": ("alaw", True),
}


def _parse_aiff(rd: _Reader) -> _Header:
    """Analyse un conteneur FORM/AIFF ou FORM/AIFC."""
    head = rd.at(0, 12)
    if len(head) < 12:
        raise _AudioError("fichier trop court")
    kind = head[8:12]
    if kind not in (b"AIFF", b"AIFC"):
        raise _AudioError("conteneur FORM inconnu")
    h = _Header(container="aiff", big_endian=True, fmt="aiff")

    pos = 12
    size = rd.size
    got_comm = False
    ssnd_off = -1
    ssnd_size = 0
    comm_frames = 0
    markers: dict[int, int] = {}
    loop_ids: tuple[int, int] | None = None
    count = 0

    while pos + 8 <= size and count < _MAX_CHUNKS:
        count += 1
        hdr = rd.at(pos, 8)
        if len(hdr) < 8:
            break
        cid = hdr[0:4]
        if not _printable_id(cid):
            break
        csz = struct.unpack(">I", hdr[4:8])[0]
        body = pos + 8
        avail = max(0, size - body)
        truncated = csz > avail
        take = avail if truncated else csz

        if cid == b"COMM":
            d = rd.at(body, min(take, 40))
            if len(d) < 18:
                raise _AudioError("chunk COMM incomplet")
            nch, nfr, ssize = struct.unpack(">hIh", d[:8])
            rate = _ext80_to_float(d[8:18])
            h.channels = int(nch) if nch > 0 else 1
            comm_frames = int(nfr)
            bits = int(ssize) if ssize > 0 else 16
            h.sample_rate = int(round(rate))
            enc, be = "pcm-s", True
            if kind == b"AIFC" and len(d) >= 22:
                comp = d[18:22]
                if comp not in _AIFC_ENCODINGS:
                    raise _AudioError("compression AIFC non gérée (%s)"
                                      % comp.decode("latin-1", "replace"))
                enc, be = _AIFC_ENCODINGS[comp]
                if comp in (b"fl32", b"FL32"):
                    bits = 32
                elif comp in (b"fl64", b"FL64"):
                    bits = 64
                elif comp in (b"ulaw", b"ULAW", b"alaw", b"ALAW"):
                    bits = 8
            h.bits = bits
            h.encoding = enc
            h.big_endian = be
            h.sample_bytes = 1 if enc in ("ulaw", "alaw") else max(1, (bits + 7) // 8)
            got_comm = True

        elif cid == b"SSND":
            d = rd.at(body, min(avail, 8))
            off = 0
            if len(d) >= 8:
                off, _blk = struct.unpack(">II", d[:8])
            off = int(off)
            if off > take:
                off = 0
            ssnd_off = body + 8 + off
            ssnd_size = max(0, take - 8 - off)
            ssnd_size = max(0, min(ssnd_size, size - ssnd_off))

        elif cid == b"MARK":
            d = rd.at(body, min(take, 4096))
            if len(d) >= 2:
                n = struct.unpack(">H", d[:2])[0]
                q = 2
                for _ in range(min(n, 64)):
                    if q + 7 > len(d):
                        break
                    mid, mpos = struct.unpack(">HI", d[q:q + 6])
                    q += 6
                    slen = d[q]
                    q += 1 + slen
                    if (slen + 1) & 1:
                        q += 1
                    markers[int(mid)] = int(mpos)

        elif cid == b"INST":
            d = rd.at(body, min(take, 20))
            if len(d) >= 1 and 0 <= d[0] <= 127:
                h.root_note = int(d[0])
            if len(d) >= 14:
                mode, beg, fin = struct.unpack(">hhh", d[8:14])
                if mode != 0:
                    loop_ids = (int(beg), int(fin))

        if truncated:
            break
        pos = body + csz + (csz & 1)

    if not got_comm:
        raise _AudioError("chunk COMM absent")
    if ssnd_off < 0:
        raise _AudioError("chunk SSND absent")
    if h.sample_rate <= 0:
        raise _AudioError("taux d'échantillonnage invalide")

    if loop_ids and markers:
        a = markers.get(loop_ids[0])
        b = markers.get(loop_ids[1])
        if a is not None and b is not None and b > a:
            h.loop_start, h.loop_end = a, b

    h.data_offset = ssnd_off
    usable = max(0, min(ssnd_size, size - ssnd_off))
    usable -= usable % h.frame_bytes
    h.data_size = usable
    h.frames = usable // h.frame_bytes
    if 0 < comm_frames < h.frames:
        h.frames = comm_frames
        h.data_size = comm_frames * h.frame_bytes
    return h


def _read_header(f, size: int) -> _Header:
    """Analyse l'en-tête d'un fichier déjà ouvert en binaire."""
    if size < 12:
        raise _AudioError("fichier vide ou trop court")
    rd = _Reader(f, size)
    magic = rd.at(0, 4)
    if magic in (b"RIFF", b"RIFX", b"RF64", b"BW64"):
        h = _parse_riff(rd)
    elif magic == b"FORM":
        h = _parse_aiff(rd)
    else:
        if _printable_id(magic):
            shown = magic.decode("ascii")
        else:
            shown = magic.hex(" ").upper()
        raise _AudioError("format de fichier inconnu (%s)" % shown)
    if h.channels <= 0 or h.sample_bytes <= 0:
        raise _AudioError("en-tête incohérent")
    if h.channels > 64:
        raise _AudioError("nombre de canaux aberrant (%d)" % h.channels)
    if h.loop_start is not None and h.loop_end is not None:
        if not (0 <= h.loop_start < h.loop_end <= max(1, h.frames)):
            h.loop_start = None
            h.loop_end = None
    return h


# ---------------------------------------------------------------------------
# Décodage des échantillons
# ---------------------------------------------------------------------------

def _decode(raw: bytes, h: _Header) -> np.ndarray:
    """Décode un bloc d'octets en float32 entrelacé (tableau 1-D)."""
    unit = h.frame_bytes
    n = len(raw) - (len(raw) % unit)
    if n <= 0:
        return np.zeros(0, dtype=np.float32)
    raw = raw[:n]
    enc = h.encoding
    sb = h.sample_bytes
    be = h.big_endian

    if enc == "float":
        if sb == 8:
            code = ">f8" if be else "<f8"
        else:
            code = ">f4" if be else "<f4"
        a = np.frombuffer(raw, dtype=np.dtype(code)).astype(np.float32)
        return np.nan_to_num(a, nan=0.0, posinf=1.0, neginf=-1.0)
    if enc == "ulaw":
        return _ulaw_table()[np.frombuffer(raw, dtype=np.uint8)]
    if enc == "alaw":
        return _alaw_table()[np.frombuffer(raw, dtype=np.uint8)]
    if sb == 1:
        if enc == "pcm-u":
            a = np.frombuffer(raw, dtype=np.uint8).astype(np.float32)
            return (a - 128.0) * np.float32(1.0 / 128.0)
        return np.frombuffer(raw, dtype=np.int8).astype(np.float32) * np.float32(1.0 / 128.0)
    if sb == 2:
        code = ">i2" if be else "<i2"
        return (np.frombuffer(raw, dtype=np.dtype(code)).astype(np.float32)
                * np.float32(1.0 / 32768.0))
    if sb == 3:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        if be:
            v = (b[:, 0] << 16) | (b[:, 1] << 8) | b[:, 2]
        else:
            v = (b[:, 2] << 16) | (b[:, 1] << 8) | b[:, 0]
        v = np.where(v & 0x800000, v - 0x1000000, v)
        return v.astype(np.float32) * np.float32(1.0 / 8388608.0)
    if sb == 4:
        code = ">i4" if be else "<i4"
        return (np.frombuffer(raw, dtype=np.dtype(code)).astype(np.float32)
                * np.float32(1.0 / 2147483648.0))
    if sb == 8:
        code = ">i8" if be else "<i8"
        a = np.frombuffer(raw, dtype=np.dtype(code)).astype(np.float64)
        return (a / 9223372036854775808.0).astype(np.float32)
    raise _AudioError("largeur d'échantillon non gérée (%d octets)" % sb)


def _info_from_header(p: Path, h: _Header) -> AudioInfo:
    """Construit l'AudioInfo public à partir d'un en-tête interne."""
    dur = (h.frames / h.sample_rate) if h.sample_rate > 0 else 0.0
    return AudioInfo(
        path=p,
        sample_rate=int(h.sample_rate),
        channels=int(h.channels),
        bit_depth=int(h.bits),
        frames=int(h.frames),
        duration=float(dur),
        fmt=h.fmt,
        loop_start=h.loop_start,
        loop_end=h.loop_end,
        root_note=h.root_note,
        ok=True,
        error="",
    )


# ---------------------------------------------------------------------------
# API publique — lecture
# ---------------------------------------------------------------------------

def probe(path: Path) -> AudioInfo:
    """Lit uniquement les en-têtes du fichier (rapide, aucun décodage audio)."""
    p = Path(path)
    try:
        size = os.path.getsize(p)
        with open(p, "rb") as f:
            h = _read_header(f, size)
        return _info_from_header(p, h)
    except _AudioError as exc:
        return AudioInfo(path=p, ok=False, error=str(exc))
    except (OSError, ValueError, struct.error, MemoryError) as exc:
        return AudioInfo(path=p, ok=False, error="%s: %s" % (type(exc).__name__, exc))
    except Exception as exc:                            # garde-fou absolu
        log.debug("probe(%s) : erreur inattendue", p, exc_info=True)
        return AudioInfo(path=p, ok=False, error="erreur inattendue: %s" % exc)


def _read_raw(path: Path, max_frames: int | None, mono: bool,
              clip: bool) -> tuple[np.ndarray, int]:
    """Lecture interne, sans filet : peut lever."""
    p = Path(path)
    size = os.path.getsize(p)
    with open(p, "rb") as f:
        h = _read_header(f, size)
        n = h.frames if max_frames is None else max(0, min(h.frames, int(max_frames)))
        f.seek(h.data_offset)
        raw = f.read(n * h.frame_bytes) if n > 0 else b""
        a = _decode(raw, h)
    ch = h.channels
    usable = a.size // ch
    a = a[:usable * ch].reshape(usable, ch)
    if clip and a.size:
        np.clip(a, -1.0, 1.0, out=a)
    if mono:
        a = a.mean(axis=1, dtype=np.float32) if ch > 1 else a[:, 0]
    return np.ascontiguousarray(a, dtype=np.float32), int(h.sample_rate)


def read(path: Path, max_frames: int | None = None,
         mono: bool = False) -> tuple[np.ndarray, int]:
    """Lit le fichier : ``(données float32 dans [-1, 1], taux d'échantillonnage)``.

    La forme est ``(frames, channels)``, ou ``(frames,)`` si ``mono=True``.
    En cas d'échec, retourne un tableau vide et un taux de 0 (jamais d'exception).
    """
    try:
        return _read_raw(path, max_frames, mono, clip=True)
    except (_AudioError, OSError, ValueError, struct.error, MemoryError) as exc:
        log.debug("read(%s) : %s", path, exc)
    except Exception:
        log.debug("read(%s) : erreur inattendue", path, exc_info=True)
    empty = np.zeros(0, dtype=np.float32) if mono else np.zeros((0, 1), dtype=np.float32)
    return empty, 0


def peaks(path: Path, buckets: int = 1200) -> np.ndarray:
    """Enveloppe min/max pour l'affichage : tableau ``(buckets, 2)`` float32.

    La lecture se fait par blocs : le fichier n'est jamais chargé en entier.
    """
    buckets = int(buckets)
    if buckets <= 0:
        return np.zeros((0, 2), dtype=np.float32)
    out = np.zeros((buckets, 2), dtype=np.float32)
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            h = _read_header(f, size)
            frames = h.frames
            ch = h.channels
            fb = h.frame_bytes
            if frames <= 0:
                return out

            if frames <= buckets * 2:
                # petit fichier : une seule lecture suffit
                f.seek(h.data_offset)
                a = _decode(f.read(frames * fb), h)
                nfr = a.size // ch
                if nfr == 0:
                    return out
                a = a[:nfr * ch].reshape(nfr, ch)
                edges = np.linspace(0, nfr, buckets + 1).astype(np.int64)
                for i in range(buckets):
                    s = int(edges[i])
                    e = int(max(edges[i + 1], s + 1))
                    seg = a[s:min(e, nfr)]
                    if seg.size:
                        out[i, 0] = float(seg.min())
                        out[i, 1] = float(seg.max())
                np.clip(out, -1.0, 1.0, out=out)
                return out

            fpb = frames // buckets
            per = max(1, min(buckets, _BLOCK_BYTES // max(1, fpb * fb)))
            f.seek(h.data_offset)
            b0 = 0
            while b0 < buckets:
                nb = min(per, buckets - b0)
                raw = f.read(nb * fpb * fb)
                nfr = len(raw) // fb
                if nfr <= 0:
                    break
                a = _decode(raw, h)
                full = nfr // fpb
                if full:
                    m = a[:full * fpb * ch].reshape(full, fpb * ch)
                    out[b0:b0 + full, 0] = m.min(axis=1)
                    out[b0:b0 + full, 1] = m.max(axis=1)
                rest = a[full * fpb * ch:]
                if rest.size and (b0 + full) < buckets:
                    out[b0 + full, 0] = float(rest.min())
                    out[b0 + full, 1] = float(rest.max())
                b0 += nb
                if nfr < nb * fpb:
                    break

            tail = frames - buckets * fpb
            if tail > 0:
                raw = f.read(tail * fb)
                if raw:
                    a = _decode(raw, h)
                    if a.size:
                        out[buckets - 1, 0] = min(float(out[buckets - 1, 0]),
                                                  float(a.min()))
                        out[buckets - 1, 1] = max(float(out[buckets - 1, 1]),
                                                  float(a.max()))
            np.clip(out, -1.0, 1.0, out=out)
            return out
    except (_AudioError, OSError, ValueError, struct.error, MemoryError) as exc:
        log.debug("peaks(%s) : %s", path, exc)
    except Exception:
        log.debug("peaks(%s) : erreur inattendue", path, exc_info=True)
    return out


# ---------------------------------------------------------------------------
# API publique — écriture
# ---------------------------------------------------------------------------

def _resolve_out_format(bit_depth) -> tuple[str, int]:
    """Retourne ``('pcm'|'float', bits)`` à partir d'un ``bit_depth`` tolérant.

    Accepte 8, 16, 24, 32 (PCM entier) ; 64, -32, -64, 'float32', 'float64'
    pour l'IEEE flottant.
    """
    if bit_depth is None:
        return ("pcm", 16)
    if isinstance(bit_depth, str):
        s = bit_depth.strip().lower()
        if s in ("float", "float32", "f32", "ieee", "ieee32"):
            return ("float", 32)
        if s in ("float64", "f64", "double"):
            return ("float", 64)
        try:
            bit_depth = int(s)
        except ValueError:
            raise ValueError("profondeur de bits inconnue : %r" % bit_depth)
    b = int(bit_depth)
    if b == -32:
        return ("float", 32)
    if b in (-64, 64):
        return ("float", 64)
    if b in (8, 16, 24, 32):
        return ("pcm", b)
    raise ValueError("profondeur de bits non gérée : %r" % bit_depth)


def _as_2d(data: np.ndarray) -> np.ndarray:
    """Normalise les données d'entrée en float32 de forme (frames, channels)."""
    a = np.asarray(data)
    if a.dtype.kind in "iu":
        info = np.iinfo(a.dtype)
        if a.dtype.kind == "u":
            mid = (float(info.max) + 1.0) / 2.0
            a = (a.astype(np.float32) - np.float32(mid)) / np.float32(mid)
        else:
            a = a.astype(np.float32) / np.float32(float(info.max) + 1.0)
    else:
        a = a.astype(np.float32, copy=False)
    if a.ndim == 1:
        a = a.reshape(-1, 1)
    elif a.ndim != 2:
        raise ValueError("forme de tableau non gérée : %r" % (a.shape,))
    return np.nan_to_num(a, nan=0.0, posinf=1.0, neginf=-1.0)


def _encode(block: np.ndarray, kind: str, bits: int, big: bool,
            unsigned8: bool = True) -> bytes:
    """Encode un bloc float32 (n, ch) vers les octets du format cible."""
    flat = np.ascontiguousarray(block).reshape(-1)
    if kind == "float":
        if bits == 32:
            code = ">f4" if big else "<f4"
        else:
            code = ">f8" if big else "<f8"
        return flat.astype(np.dtype(code)).tobytes()
    x = flat.astype(np.float64)
    if bits == 8:
        v = np.clip(np.round(x * 128.0), -128.0, 127.0)
        if unsigned8:
            return (v + 128.0).astype(np.uint8).tobytes()
        return v.astype(np.int8).tobytes()
    if bits == 16:
        v = np.clip(np.round(x * 32768.0), -32768.0, 32767.0)
        return v.astype(np.dtype(">i2" if big else "<i2")).tobytes()
    if bits == 24:
        v = np.clip(np.round(x * 8388608.0), -8388608.0, 8388607.0)
        u = v.astype(np.int32).astype(np.uint32) & np.uint32(0xFFFFFF)
        b = np.empty((u.size, 3), dtype=np.uint8)
        if big:
            b[:, 0] = (u >> 16) & 0xFF
            b[:, 1] = (u >> 8) & 0xFF
            b[:, 2] = u & 0xFF
        else:
            b[:, 0] = u & 0xFF
            b[:, 1] = (u >> 8) & 0xFF
            b[:, 2] = (u >> 16) & 0xFF
        return b.tobytes()
    if bits == 32:
        v = np.clip(np.round(x * 2147483648.0), -2147483648.0, 2147483647.0)
        return v.astype(np.dtype(">i4" if big else "<i4")).tobytes()
    raise ValueError("profondeur de bits non gérée : %d" % bits)


def _write_wav(fp, data: np.ndarray, sample_rate: int, kind: str, bits: int) -> None:
    """Écrit un flux RIFF/WAVE little-endian."""
    frames, ch = data.shape
    sb = (bits + 7) // 8
    block_align = ch * sb
    data_bytes = frames * block_align
    tag = WAVE_FORMAT_FLOAT if kind == "float" else WAVE_FORMAT_PCM
    fmt_size = 18 if kind == "float" else 16
    fmt = struct.pack("<HHIIHH", tag, ch, sample_rate,
                      sample_rate * block_align, block_align, bits)
    if fmt_size == 18:
        fmt += struct.pack("<H", 0)
    extra = (8 + 4) if kind == "float" else 0          # chunk 'fact'
    riff_size = 4 + (8 + fmt_size) + extra + (8 + data_bytes) + (data_bytes & 1)

    fp.write(b"RIFF" + struct.pack("<I", riff_size) + b"WAVE")
    fp.write(b"fmt " + struct.pack("<I", fmt_size) + fmt)
    if kind == "float":
        fp.write(b"fact" + struct.pack("<II", 4, frames))
    fp.write(b"data" + struct.pack("<I", data_bytes))
    step = max(1, _BLOCK_BYTES // max(1, block_align))
    for i in range(0, frames, step):
        fp.write(_encode(data[i:i + step], kind, bits, big=False, unsigned8=True))
    if data_bytes & 1:
        fp.write(b"\x00")


def _write_aiff(fp, data: np.ndarray, sample_rate: int, kind: str, bits: int) -> None:
    """Écrit un flux FORM/AIFF (PCM big-endian) ou FORM/AIFC (flottant)."""
    frames, ch = data.shape
    sb = (bits + 7) // 8
    block_align = ch * sb
    data_bytes = frames * block_align
    aifc = (kind == "float")
    comm = struct.pack(">hIh", ch, frames, bits) + _float_to_ext80(float(sample_rate))
    if aifc:
        if bits == 32:
            comm += b"fl32" + b"\x0cFloat 32-bit"
        else:
            comm += b"fl64" + b"\x0cFloat 64-bit"
    comm_size = len(comm)
    ssnd_size = 8 + data_bytes
    total = 4
    if aifc:
        total += 8 + 4                                  # chunk FVER
    total += 8 + comm_size + (comm_size & 1)
    total += 8 + ssnd_size + (ssnd_size & 1)

    fp.write(b"FORM" + struct.pack(">I", total) + (b"AIFC" if aifc else b"AIFF"))
    if aifc:
        fp.write(b"FVER" + struct.pack(">II", 4, 0xA2805140))
    fp.write(b"COMM" + struct.pack(">I", comm_size) + comm)
    if comm_size & 1:
        fp.write(b"\x00")
    fp.write(b"SSND" + struct.pack(">I", ssnd_size) + struct.pack(">II", 0, 0))
    step = max(1, _BLOCK_BYTES // max(1, block_align))
    for i in range(0, frames, step):
        fp.write(_encode(data[i:i + step], kind, bits, big=True, unsigned8=False))
    if ssnd_size & 1:
        fp.write(b"\x00")


def write(path: Path, data: np.ndarray, sample_rate: int, bit_depth: int = 16) -> None:
    """Écrit un fichier WAV (ou AIFF/AIFC si l'extension le demande).

    ``data`` : tableau ``(frames,)`` ou ``(frames, channels)``, flottant dans
    [-1, 1] ou entier. ``bit_depth`` : 8/16/24/32 pour le PCM entier,
    ``'float32'``/``'float64'`` (ou -32/-64/64) pour l'IEEE flottant.
    Écriture atomique : fichier temporaire puis ``os.replace``.
    """
    p = Path(path)
    kind, bits = _resolve_out_format(bit_depth)
    arr = _as_2d(data)
    sr = int(sample_rate)
    if sr <= 0:
        raise ValueError("taux d'échantillonnage invalide : %r" % sample_rate)
    if arr.shape[1] <= 0:
        raise ValueError("aucun canal à écrire")
    if p.parent and not p.parent.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
    aiff = p.suffix.lower() in _EXT_AIFF
    tmp = p.with_name(p.name + ".tmp~")
    try:
        with open(tmp, "wb") as fp:
            if aiff:
                _write_aiff(fp, arr, sr, kind, bits)
            else:
                _write_wav(fp, arr, sr, kind, bits)
            fp.flush()
        os.replace(tmp, p)
    except BaseException:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Traitements utilisés par convert()
# ---------------------------------------------------------------------------

def _db_to_amp(db: float) -> float:
    """Décibels pleine échelle -> amplitude linéaire."""
    return float(10.0 ** (float(db) / 20.0))


def _trim_silence(a: np.ndarray, threshold_db: float) -> np.ndarray:
    """Retire le silence de tête et de queue sous le seuil donné."""
    if a.shape[0] == 0:
        return a
    thr = _db_to_amp(threshold_db)
    env = np.abs(a).max(axis=1)
    idx = np.flatnonzero(env > thr)
    if idx.size == 0:
        return a                                       # tout est silencieux
    return a[int(idx[0]):int(idx[-1]) + 1]


def _to_channels(a: np.ndarray, mono: bool) -> np.ndarray:
    """Force le mono (mixage) ou la stéréo (duplication / 2 premiers canaux)."""
    ch = a.shape[1]
    if mono:
        if ch == 1:
            return a
        return a.mean(axis=1, dtype=np.float32).reshape(-1, 1)
    if ch == 1:
        return np.repeat(a, 2, axis=1)
    if ch > 2:
        return np.ascontiguousarray(a[:, :2])
    return a


def _lowpass_fir(a: np.ndarray, fc: float, taps: int = 63) -> np.ndarray:
    """Filtre anti-repliement simple : sinus cardinal fenêtré (Blackman)."""
    fc = float(min(max(fc, 1e-4), 0.499))
    n = np.arange(taps, dtype=np.float64) - (taps - 1) / 2.0
    h = 2.0 * fc * np.sinc(2.0 * fc * n) * np.blackman(taps)
    s = h.sum()
    if s:
        h = h / s
    out = np.empty_like(a)
    for c in range(a.shape[1]):
        out[:, c] = np.convolve(a[:, c].astype(np.float64), h,
                                mode="same").astype(np.float32)
    return out


def _resample(a: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    """Rééchantillonne par interpolation linéaire (anti-repliement si descente)."""
    n = a.shape[0]
    if sr_in == sr_out or n == 0 or sr_in <= 0 or sr_out <= 0:
        return a
    ratio = float(sr_out) / float(sr_in)
    if ratio < 1.0 and n > 8:
        a = _lowpass_fir(a, 0.45 * ratio)
    n_out = int(round(n * ratio))
    if n_out <= 0:
        return np.zeros((0, a.shape[1]), dtype=np.float32)
    t = np.arange(n_out, dtype=np.float64) / ratio
    i0 = np.floor(t).astype(np.int64)
    frac = (t - i0).astype(np.float32).reshape(-1, 1)
    i0 = np.clip(i0, 0, n - 1)
    i1 = np.clip(i0 + 1, 0, n - 1)
    return (a[i0] * (np.float32(1.0) - frac) + a[i1] * frac).astype(np.float32)


def _normalize(a: np.ndarray, target_db: float) -> np.ndarray:
    """Normalise la crête au niveau demandé (dBFS)."""
    if a.size == 0:
        return a
    peak = float(np.abs(a).max())
    if peak <= 1e-9:
        return a
    gain = _db_to_amp(target_db) / peak
    return np.clip(a * np.float32(gain), -1.0, 1.0).astype(np.float32)


def _fade(a: np.ndarray, sr: int, fade_ms: float) -> np.ndarray:
    """Applique un fondu d'entrée et de sortie linéaire."""
    n = a.shape[0]
    k = int(round(float(fade_ms) * sr / 1000.0))
    if k <= 0 or n == 0:
        return a
    k = min(k, max(1, n // 2))
    ramp = np.linspace(0.0, 1.0, k, dtype=np.float32).reshape(-1, 1)
    a = a.copy()
    a[:k] *= ramp
    a[n - k:] *= ramp[::-1]
    return a


def convert(src: Path, dst: Path, sample_rate: int | None = None,
            bit_depth: int | None = None, mono: bool | None = None,
            normalize_db: float | None = None,
            trim_silence_db: float | None = None,
            fade_ms: float = 0.0) -> AudioInfo:
    """Convertit un fichier audio ; retourne l'``AudioInfo`` du résultat.

    Ordre des traitements : coupe du silence, mono/stéréo, rééchantillonnage,
    normalisation, fondus. Ne lève jamais : en cas d'échec ``ok=False``.
    """
    src_p, dst_p = Path(src), Path(dst)
    try:
        info = probe(src_p)
        if not info.ok:
            return AudioInfo(path=dst_p, ok=False,
                             error="source illisible : %s" % info.error)
        a, sr = _read_raw(src_p, None, mono=False, clip=False)
        if sr <= 0:
            return AudioInfo(path=dst_p, ok=False, error="source illisible")

        if trim_silence_db is not None:
            a = _trim_silence(a, float(trim_silence_db))
        if mono is not None:
            a = _to_channels(a, bool(mono))
        target_sr = int(sample_rate) if sample_rate else sr
        if target_sr != sr:
            a = _resample(a, sr, target_sr)
        if normalize_db is not None:
            a = _normalize(a, float(normalize_db))
        else:
            a = np.clip(a, -1.0, 1.0).astype(np.float32)
        if fade_ms and float(fade_ms) > 0.0:
            a = _fade(a, target_sr, float(fade_ms))

        depth = bit_depth if bit_depth is not None else info.bit_depth
        if bit_depth is None and info.fmt == "float":
            depth = "float64" if info.bit_depth == 64 else "float32"
        try:
            _resolve_out_format(depth)
        except ValueError:
            depth = 16
        if a.shape[0] == 0:
            a = np.zeros((1, max(1, a.shape[1])), dtype=np.float32)
        write(dst_p, a, target_sr, depth)
        out = probe(dst_p)
        if not out.ok:
            return AudioInfo(path=dst_p, ok=False,
                             error="écriture invalide : %s" % out.error)
        return out
    except (_AudioError, OSError, ValueError, struct.error, MemoryError) as exc:
        return AudioInfo(path=dst_p, ok=False,
                         error="%s: %s" % (type(exc).__name__, exc))
    except Exception as exc:                            # garde-fou absolu
        log.debug("convert(%s -> %s) : erreur inattendue", src_p, dst_p, exc_info=True)
        return AudioInfo(path=dst_p, ok=False, error="erreur inattendue: %s" % exc)
