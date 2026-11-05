# -*- coding: utf-8 -*-
"""Lecture audio d'aperçu (aucune dépendance obligatoire).

Trois backends, choisis automatiquement dans cet ordre :
  * ``sounddevice`` : flux non bloquant à callback, volume, boucle, position ;
  * ``winsound``    : repli Windows (un WAV 16 bits temporaire est écrit) ;
  * ``none``        : silencieux mais non bloquant (l'interface continue de
    fonctionner, la position avance comme si le son était joué).

La classe :class:`Player` est sûre vis-à-vis des threads : deux verrous sont
utilisés, ``_api_lock`` pour les appels PortAudio (jamais pris par le callback)
et ``_state_lock`` pour l'état partagé avec le callback. L'ordre d'acquisition
est toujours ``_api_lock`` puis ``_state_lock``, ce qui exclut tout interblocage.
"""

from __future__ import annotations

import atexit
import logging
import os
import tempfile
import threading
import time
from pathlib import Path

import numpy as np

from . import wav

log = logging.getLogger(__name__)

__all__ = ["Player"]

# --- Dépendances optionnelles ---------------------------------------------

try:                                    # pilote audio temps réel (optionnel)
    import sounddevice as _sd
except ImportError:
    _sd = None
except Exception as _exc:               # PortAudio absent ou DLL illisible
    log.info("sounddevice indisponible : %s", _exc)
    _sd = None

try:                                    # repli Windows
    import winsound as _winsound
except ImportError:
    _winsound = None

#: Taux d'échantillonnage utilisé quand rien n'est connu.
DEFAULT_SR = 44100


def _as_frames(data) -> np.ndarray:
    """Normalise un tableau en float32 de forme ``(frames, channels)``."""
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
        a = a.reshape(a.shape[0], -1)
    a = np.nan_to_num(a, nan=0.0, posinf=1.0, neginf=-1.0)
    return np.ascontiguousarray(a, dtype=np.float32)


def _fit_channels(a: np.ndarray, target: int) -> np.ndarray:
    """Adapte le nombre de canaux (duplication mono, troncature au-delà)."""
    ch = a.shape[1]
    if ch == target:
        return a
    if ch == 1:
        return np.ascontiguousarray(np.repeat(a, target, axis=1))
    if ch > target:
        return np.ascontiguousarray(a[:, :target])
    pad = np.zeros((a.shape[0], target - ch), dtype=np.float32)
    return np.ascontiguousarray(np.concatenate([a, pad], axis=1))


class Player:
    """Lecture d'aperçu d'un échantillon ou d'un tableau numpy.

    Utilise ``sounddevice`` s'il est disponible, sinon ``winsound``
    (WAV 16 bits temporaire), sinon un backend muet mais non bloquant.
    """

    def __init__(self) -> None:
        self._api_lock = threading.RLock()      # protège les appels PortAudio
        self._state_lock = threading.RLock()    # partagé avec le callback
        self._volume = 0.8
        self._device_name: str | None = None
        self._device_index: int | None = None
        self._stream = None
        self._stream_sr = 0
        self._stream_ch = 0
        self._stream_dev: int | None = None
        self._data: np.ndarray | None = None
        self._sr = DEFAULT_SR
        self._pos = 0
        self._loop = False
        self._playing = False
        self._start_time = 0.0
        self._duration = 0.0
        self._tmp_files: list[Path] = []
        self._max_ch_cache: dict[int | None, int] = {}
        self._backend = self._pick_backend()
        atexit.register(self._shutdown)

    # -- choix du backend ---------------------------------------------------

    @staticmethod
    def _pick_backend() -> str:
        """Détermine le backend utilisable au démarrage."""
        if _sd is not None:
            try:
                devs = _sd.query_devices()
                if any(int(d.get("max_output_channels", 0)) > 0 for d in devs):
                    return "sounddevice"
                log.info("Aucune sortie audio détectée par sounddevice.")
            except Exception as exc:
                log.info("sounddevice inutilisable (%s), repli.", exc)
        if _winsound is not None:
            return "winsound"
        return "none"

    # -- propriétés ---------------------------------------------------------

    @property
    def available(self) -> bool:
        """Vrai si un son peut réellement être entendu."""
        return self._backend != "none"

    @property
    def backend(self) -> str:
        """Nom du backend : 'sounddevice', 'winsound' ou 'none'."""
        return self._backend

    @property
    def is_playing(self) -> bool:
        """Vrai si une lecture est en cours."""
        with self._state_lock:
            if not self._playing:
                return False
            if self._backend == "sounddevice":
                return True
            if self._loop:
                return True
            if self._duration <= 0:
                self._playing = False
                return False
            if (time.monotonic() - self._start_time) >= self._duration:
                self._playing = False
                return False
            return True

    # -- périphériques ------------------------------------------------------

    def devices(self) -> list[str]:
        """Liste des périphériques de sortie disponibles (vide si inconnu)."""
        if _sd is None or self._backend != "sounddevice":
            return []
        try:
            out: list[str] = []
            for d in _sd.query_devices():
                if int(d.get("max_output_channels", 0)) > 0:
                    name = str(d.get("name", "")).strip()
                    if name and name not in out:
                        out.append(name)
            return out
        except Exception as exc:
            log.debug("devices() : %s", exc)
            return []

    def set_device(self, name: str | None) -> None:
        """Choisit le périphérique de sortie (``None`` = celui par défaut)."""
        index: int | None = None
        if name and _sd is not None and self._backend == "sounddevice":
            try:
                devs = list(_sd.query_devices())
                low = name.strip().lower()
                for i, d in enumerate(devs):
                    if int(d.get("max_output_channels", 0)) <= 0:
                        continue
                    if str(d.get("name", "")).strip() == name.strip():
                        index = i
                        break
                if index is None:
                    for i, d in enumerate(devs):
                        if int(d.get("max_output_channels", 0)) <= 0:
                            continue
                        if low in str(d.get("name", "")).strip().lower():
                            index = i
                            break
                if index is None:
                    log.warning("Périphérique audio introuvable : %s", name)
            except Exception as exc:
                log.debug("set_device(%s) : %s", name, exc)
        with self._api_lock:
            changed = (index != self._device_index)
            self._device_name = name or None
            self._device_index = index
            if changed:
                self._close_stream()

    def set_volume(self, v: float) -> None:
        """Règle le volume d'aperçu (0.0 à 2.0, 1.0 = niveau du fichier)."""
        try:
            val = float(v)
        except (TypeError, ValueError):
            return
        val = min(max(val, 0.0), 2.0)
        with self._state_lock:
            self._volume = val

    # -- lecture ------------------------------------------------------------

    def play_file(self, path: Path, loop: bool = False) -> None:
        """Joue un fichier audio. N'échoue jamais bruyamment."""
        p = Path(path)
        try:
            if self._backend == "winsound":
                self._play_file_winsound(p, loop)
                return
            if self._backend == "none":
                info = wav.probe(p)
                self._start_silent(info.duration if info.ok else 0.0, loop)
                return
            data, sr = wav.read(p)
            if sr <= 0 or data.size == 0:
                log.warning("Fichier audio illisible : %s", p)
                self.stop()
                return
            self.play_array(data, sr, loop)
        except Exception:
            log.debug("play_file(%s) : erreur", p, exc_info=True)
            self.stop()

    def play_array(self, data: np.ndarray, sample_rate: int,
                   loop: bool = False) -> None:
        """Joue un tableau numpy (float dans [-1, 1] ou entier)."""
        try:
            arr = _as_frames(data)
            sr = int(sample_rate) if int(sample_rate) > 0 else DEFAULT_SR
            if arr.shape[0] == 0:
                self.stop()
                return
            if self._backend == "sounddevice":
                self._play_sounddevice(arr, sr, bool(loop))
            elif self._backend == "winsound":
                self._play_winsound_array(arr, sr, bool(loop))
            else:
                self._start_silent(arr.shape[0] / float(sr), bool(loop))
        except Exception:
            log.debug("play_array : erreur", exc_info=True)
            self.stop()

    def stop(self) -> None:
        """Arrête immédiatement la lecture et libère les ressources."""
        with self._api_lock:
            if self._backend == "sounddevice":
                self._close_stream()
            elif self._backend == "winsound" and _winsound is not None:
                try:
                    _winsound.PlaySound(None, _winsound.SND_PURGE)
                except Exception as exc:
                    log.debug("winsound stop : %s", exc)
            with self._state_lock:
                self._playing = False
                self._loop = False
                self._pos = 0
                self._duration = 0.0
            self._purge_temp()

    def position(self) -> float:
        """Secondes écoulées depuis le début de la lecture (0.0 si inconnu)."""
        with self._state_lock:
            if not self._playing:
                return 0.0
            if self._backend == "sounddevice":
                if self._sr <= 0:
                    return 0.0
                return float(self._pos) / float(self._sr)
            elapsed = time.monotonic() - self._start_time
            if elapsed < 0:
                return 0.0
            if self._loop and self._duration > 0:
                return float(elapsed % self._duration)
            if self._duration > 0:
                return float(min(elapsed, self._duration))
            return float(elapsed)

    # -- backend sounddevice ------------------------------------------------

    def _play_sounddevice(self, arr: np.ndarray, sr: int, loop: bool) -> None:
        with self._api_lock:
            target_ch = self._output_channels(arr.shape[1])
            arr = _fit_channels(arr, target_ch)
            need_new = (self._stream is None or self._stream_sr != sr
                        or self._stream_ch != target_ch
                        or self._stream_dev != self._device_index)
            if need_new:
                self._close_stream()
            else:
                self._stop_stream_only()
            with self._state_lock:
                self._data = arr
                self._sr = sr
                self._pos = 0
                self._loop = loop
                self._duration = arr.shape[0] / float(sr)
                self._start_time = time.monotonic()
                self._playing = True
            if need_new:
                try:
                    self._stream = _sd.OutputStream(
                        samplerate=sr, channels=target_ch, dtype="float32",
                        device=self._device_index, callback=self._callback,
                        finished_callback=self._on_finished)
                    self._stream_sr = sr
                    self._stream_ch = target_ch
                    self._stream_dev = self._device_index
                except Exception as exc:
                    log.warning("Ouverture du flux audio impossible : %s", exc)
                    self._stream = None
                    with self._state_lock:
                        self._playing = False
                    self._fallback_after_failure(arr, sr, loop)
                    return
            try:
                self._stream.start()
            except Exception as exc:
                log.warning("Démarrage du flux audio impossible : %s", exc)
                self._close_stream()
                with self._state_lock:
                    self._playing = False
                self._fallback_after_failure(arr, sr, loop)

    def _output_channels(self, wanted: int) -> int:
        """Nombre de canaux à ouvrir pour le périphérique courant (mis en cache)."""
        dev = self._device_index
        maxi = self._max_ch_cache.get(dev)
        if maxi is None:
            maxi = 2
            if _sd is not None:
                try:
                    info = _sd.query_devices(dev if dev is not None else None, "output")
                    maxi = max(1, int(info.get("max_output_channels", 2)))
                except Exception:
                    maxi = 2
            self._max_ch_cache[dev] = maxi
        return max(1, min(max(wanted, 1), maxi, 2))

    def _callback(self, outdata, frames, time_info, status) -> None:
        """Callback PortAudio : ne prend que ``_state_lock`` (jamais bloquant)."""
        if status:
            log.debug("état du flux audio : %s", status)
        done = False
        with self._state_lock:
            data = self._data
            if data is None or not self._playing:
                outdata[:] = 0.0
                raise _sd.CallbackStop()
            n = data.shape[0]
            pos = self._pos
            vol = np.float32(self._volume)
            loop = self._loop
            filled = 0
            while filled < frames:
                if pos >= n:
                    if loop and n > 0:
                        pos = 0
                    else:
                        break
                take = min(frames - filled, n - pos)
                outdata[filled:filled + take, :] = data[pos:pos + take] * vol
                pos += take
                filled += take
            if filled < frames:
                outdata[filled:, :] = 0.0
                done = True
            self._pos = pos
            if done:
                self._playing = False
        if done:
            raise _sd.CallbackStop()

    def _on_finished(self) -> None:
        """Appelé par PortAudio quand le flux s'arrête."""
        with self._state_lock:
            self._playing = False

    def _stop_stream_only(self) -> None:
        """Arrête le flux sans le fermer (réutilisation immédiate)."""
        stream = self._stream
        if stream is None:
            return
        try:
            stream.stop()
        except Exception as exc:
            log.debug("stop du flux : %s", exc)
            self._close_stream()

    def _close_stream(self) -> None:
        """Ferme le flux courant (appelé hors de ``_state_lock``)."""
        stream = self._stream
        self._stream = None
        self._stream_sr = 0
        self._stream_ch = 0
        self._stream_dev = None
        if stream is None:
            return
        try:
            stream.stop()
        except Exception as exc:
            log.debug("arrêt du flux : %s", exc)
        try:
            stream.close()
        except Exception as exc:
            log.debug("fermeture du flux : %s", exc)

    def _fallback_after_failure(self, arr: np.ndarray, sr: int, loop: bool) -> None:
        """Bascule vers winsound (ou le silence) si PortAudio refuse de jouer."""
        if _winsound is not None:
            log.info("Bascule du backend audio vers winsound.")
            self._backend = "winsound"
            self._play_winsound_array(arr, sr, loop)
        else:
            self._backend = "none"
            self._start_silent(arr.shape[0] / float(sr), loop)

    # -- backend winsound ---------------------------------------------------

    def _play_file_winsound(self, p: Path, loop: bool) -> None:
        """Joue un fichier via winsound, en le convertissant si nécessaire."""
        info = wav.probe(p)
        if not info.ok:
            log.warning("Fichier audio illisible : %s (%s)", p, info.error)
            self.stop()
            return
        with self._state_lock:
            vol = self._volume
        direct = (info.fmt == "pcm" and info.bit_depth == 16
                  and info.channels <= 2 and abs(vol - 1.0) < 0.01
                  and p.suffix.lower() == ".wav")
        if direct:
            self._winsound_play_path(p, loop, info.duration, temporary=False)
            return
        data, sr = wav.read(p)
        if sr <= 0 or data.size == 0:
            log.warning("Fichier audio illisible : %s", p)
            self.stop()
            return
        self._play_winsound_array(data, sr, loop)

    def _play_winsound_array(self, arr: np.ndarray, sr: int, loop: bool) -> None:
        """Écrit un WAV 16 bits temporaire puis le joue."""
        arr = _as_frames(arr)
        with self._state_lock:
            vol = np.float32(self._volume)
        out = np.clip(arr * vol, -1.0, 1.0).astype(np.float32)
        tmp = self._new_temp_path()
        try:
            wav.write(tmp, out, sr, 16)
        except Exception as exc:
            log.warning("Écriture du fichier d'aperçu impossible : %s", exc)
            self.stop()
            return
        self._winsound_play_path(tmp, loop, out.shape[0] / float(sr), temporary=True)

    def _winsound_play_path(self, p: Path, loop: bool, duration: float,
                            temporary: bool) -> None:
        """Lance ``winsound.PlaySound`` en mode asynchrone."""
        if _winsound is None:
            self._start_silent(duration, loop)
            return
        flags = _winsound.SND_FILENAME | _winsound.SND_ASYNC | _winsound.SND_NODEFAULT
        if loop:
            flags |= _winsound.SND_LOOP
        with self._api_lock:
            try:
                _winsound.PlaySound(None, _winsound.SND_PURGE)
            except Exception:
                pass
            self._purge_temp(keep=p if temporary else None)
            if temporary:
                self._tmp_files.append(p)
            try:
                _winsound.PlaySound(str(p), flags)
            except Exception as exc:
                log.warning("Lecture winsound impossible : %s", exc)
                self._start_silent(duration, loop)
                return
            with self._state_lock:
                self._data = None
                self._sr = DEFAULT_SR
                self._pos = 0
                self._loop = bool(loop)
                self._duration = float(max(0.0, duration))
                self._start_time = time.monotonic()
                self._playing = True

    # -- backend silencieux -------------------------------------------------

    def _start_silent(self, duration: float, loop: bool) -> None:
        """Simule une lecture : non bloquante, position cohérente, aucun son."""
        with self._state_lock:
            self._data = None
            self._pos = 0
            self._loop = bool(loop)
            self._duration = float(max(0.0, duration))
            self._start_time = time.monotonic()
            self._playing = self._duration > 0.0 or bool(loop)

    # -- fichiers temporaires ----------------------------------------------

    def _new_temp_path(self) -> Path:
        """Chemin d'un nouveau WAV temporaire d'aperçu."""
        d = Path(tempfile.gettempdir()) / "Noctiluca"
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:
            d = Path(tempfile.gettempdir())
        return d / ("apercu_%d_%d.wav" % (os.getpid(), int(time.monotonic() * 1000)))

    def _purge_temp(self, keep: Path | None = None) -> None:
        """Supprime les WAV temporaires qui ne servent plus."""
        rest: list[Path] = []
        for f in self._tmp_files:
            if keep is not None and f == keep:
                rest.append(f)
                continue
            try:
                f.unlink()
            except OSError:
                rest.append(f)               # encore verrouillé : plus tard
        self._tmp_files = rest

    def _shutdown(self) -> None:
        """Nettoyage à la fermeture de l'application."""
        try:
            self.stop()
        except Exception:
            pass
        try:
            self._purge_temp()
        except Exception:
            pass
