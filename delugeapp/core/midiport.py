# -*- coding: utf-8 -*-
"""MIDI temps réel : parler au Deluge pendant qu'il est branché.

**Aucune dépendance.** Ni ``mido``, ni ``python-rtmidi``, ni ``pygame`` : rien
de tout cela n'est installé sur la machine de l'utilisateur, et le projet
tient à ne rien exiger de plus que ``numpy`` et PyQt6. Windows expose
pourtant tout ce qu'il faut dans ``winmm.dll``, que ``ctypes`` appelle
directement — la bibliothèque standard suffit.

Hors de Windows, :func:`available` rend ``False`` et tout le module devient
silencieux : aucune page ne doit cesser de fonctionner parce qu'il n'y a pas
de MIDI (SPEC §6.1).

Ce que ce module fait, et ne fait pas
-------------------------------------

Il envoie et reçoit des **messages courts** : notes, pression, molette,
changements de contrôle, horloge. C'est ce dont on a besoin pour jouer un son
sur la machine, piloter ses paramètres en MIDI Follow et suivre son tempo.

Il n'envoie **pas** de SysEx. Le firmware communautaire en propose (recopie
de l'écran, transfert de fichiers), mais cela demande des tampons
``MIDIHDR`` préparés et maintenus en vie pendant tout l'envoi : une erreur de
cycle de vie s'y paie par un plantage du processus, pas par une exception. Ce
sera un module à part, écrit en face d'un vrai Deluge.

Sûreté
------

* le rappel d'entrée est appelé par un fil de Windows : il ne fait
  qu'empiler un tuple dans une ``queue`` et n'appelle rien d'autre ;
* l'objet ``CFUNCTYPE`` est gardé sur l'instance — s'il est ramassé par le
  collecteur pendant que Windows le tient, le processus tombe ;
* toutes les entrées publiques sont tolérantes : un port disparu, un appareil
  débranché en cours de route ou un numéro invalide donnent ``False``, jamais
  une exception.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)

__all__ = [
    "MidiDevice", "MidiOut", "MidiIn",
    "available", "outputs", "inputs", "find",
    "NOTE_OFF", "NOTE_ON", "CONTROL_CHANGE", "PROGRAM_CHANGE", "PITCH_BEND",
    "CLOCK", "START", "CONTINUE", "STOP",
]

# --------------------------------------------------------------------------- #
# Messages MIDI
# --------------------------------------------------------------------------- #

NOTE_OFF = 0x80
NOTE_ON = 0x90
POLY_PRESSURE = 0xA0
CONTROL_CHANGE = 0xB0
PROGRAM_CHANGE = 0xC0
CHANNEL_PRESSURE = 0xD0
PITCH_BEND = 0xE0

#: Messages système temps réel, sans canal.
CLOCK = 0xF8
START = 0xFA
CONTINUE = 0xFB
STOP = 0xFC

#: Contrôleurs utiles au-delà de la carte MIDI Follow.
CC_ALL_SOUND_OFF = 120
CC_ALL_NOTES_OFF = 123


def _clamp7(value) -> int:
    """Ramène à 0..127, la plage d'un octet de données MIDI."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return 0
    return 0 if v < 0 else (127 if v > 127 else v)


def _channel(value) -> int:
    """Canal 1..16 côté utilisateur, 0..15 dans le message."""
    try:
        c = int(value)
    except (TypeError, ValueError):
        return 0
    return 0 if c < 1 else (15 if c > 16 else c - 1)


def short_message(status: int, data1: int = 0, data2: int = 0) -> int:
    """Encode un message court tel que ``midiOutShortMsg`` l'attend.

    Les trois octets tiennent dans un mot de 32 bits, dans l'ordre inverse de
    la lecture : statut en poids faible.
    """
    return ((int(status) & 0xFF)
            | ((_clamp7(data1) & 0x7F) << 8)
            | ((_clamp7(data2) & 0x7F) << 16))


# --------------------------------------------------------------------------- #
# Accès à winmm
# --------------------------------------------------------------------------- #

_winmm = None
_LOAD_ERROR = ""

try:
    import ctypes
    from ctypes import wintypes

    _winmm = ctypes.WinDLL("winmm")
except Exception as _exc:              # noqa: BLE001 - absent hors Windows
    ctypes = None                      # type: ignore[assignment]
    wintypes = None                    # type: ignore[assignment]
    _LOAD_ERROR = str(_exc)
    log.info("MIDI indisponible : %s", _exc)


if _winmm is not None:

    class _MIDIOUTCAPS(ctypes.Structure):
        _fields_ = [
            ("wMid", wintypes.WORD),
            ("wPid", wintypes.WORD),
            ("vDriverVersion", wintypes.UINT),
            ("szPname", wintypes.WCHAR * 32),
            ("wTechnology", wintypes.WORD),
            ("wVoices", wintypes.WORD),
            ("wNotes", wintypes.WORD),
            ("wChannelMask", wintypes.WORD),
            ("dwSupport", wintypes.DWORD),
        ]

    class _MIDIINCAPS(ctypes.Structure):
        _fields_ = [
            ("wMid", wintypes.WORD),
            ("wPid", wintypes.WORD),
            ("vDriverVersion", wintypes.UINT),
            ("szPname", wintypes.WCHAR * 32),
            ("dwSupport", wintypes.DWORD),
        ]

    _CALLBACK_FUNCTION = 0x00030000
    _MIDI_IN_PROC = ctypes.WINFUNCTYPE(
        None, wintypes.HANDLE, wintypes.UINT,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
    _MIM_DATA = 0x3C3


def available() -> bool:
    """Vrai si la machine sait faire du MIDI temps réel."""
    return _winmm is not None


def load_error() -> str:
    """Pourquoi le MIDI n'est pas disponible, pour l'afficher à l'utilisateur."""
    return _LOAD_ERROR


# --------------------------------------------------------------------------- #
# Appareils
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class MidiDevice:
    """Un port MIDI, tel que le système le nomme."""

    index: int
    name: str
    kind: str                      # "out" ou "in"

    @property
    def is_deluge(self) -> bool:
        """Vrai si le nom du port désigne un Deluge.

        Windows nomme un appareil USB par sa chaîne produit, tronquée à
        31 caractères. Le Deluge s'annonce « Deluge » ; selon les pilotes on
        voit aussi « Synthstrom » ou un nom générique précédé du port
        (« 2- Deluge »). On cherche donc le mot, pas l'égalité.
        """
        bas = self.name.casefold()
        return "deluge" in bas or "synthstrom" in bas

    def __str__(self) -> str:
        return self.name


def _devices(kind: str) -> list[MidiDevice]:
    if _winmm is None:
        return []
    out = []
    try:
        if kind == "out":
            nombre = int(_winmm.midiOutGetNumDevs())
        else:
            nombre = int(_winmm.midiInGetNumDevs())
    except Exception as exc:           # noqa: BLE001
        log.debug("énumération MIDI impossible : %s", exc)
        return []

    for index in range(max(0, nombre)):
        try:
            if kind == "out":
                caps = _MIDIOUTCAPS()
                code = _winmm.midiOutGetDevCapsW(
                    index, ctypes.byref(caps), ctypes.sizeof(caps))
            else:
                caps = _MIDIINCAPS()
                code = _winmm.midiInGetDevCapsW(
                    index, ctypes.byref(caps), ctypes.sizeof(caps))
            if code != 0:
                log.debug("port %s %d illisible (code %d)", kind, index, code)
                continue
            out.append(MidiDevice(index, str(caps.szPname), kind))
        except Exception as exc:       # noqa: BLE001
            log.debug("port %s %d illisible : %s", kind, index, exc)
    return out


def outputs() -> list[MidiDevice]:
    """Ports de sortie MIDI."""
    return _devices("out")


def inputs() -> list[MidiDevice]:
    """Ports d'entrée MIDI."""
    return _devices("in")


def find(kind: str = "out") -> MidiDevice | None:
    """Le Deluge parmi les ports, ou ``None``."""
    for appareil in (outputs() if kind == "out" else inputs()):
        if appareil.is_deluge:
            return appareil
    return None


# --------------------------------------------------------------------------- #
# Sortie
# --------------------------------------------------------------------------- #

class MidiOut:
    """Un port de sortie MIDI ouvert.

    L'objet est sûr vis-à-vis des fils : un verrou protège la poignée, parce
    que l'envoi d'un motif se fait depuis un fil de travail pendant que
    l'interface peut fermer le port.
    """

    def __init__(self) -> None:
        self._handle = None
        self._device: MidiDevice | None = None
        self._lock = threading.RLock()
        #: Notes en cours, pour pouvoir toutes les relâcher.
        self._sounding: set[tuple[int, int]] = set()

    # -- état ------------------------------------------------------------- #

    @property
    def is_open(self) -> bool:
        return self._handle is not None

    @property
    def device(self) -> MidiDevice | None:
        return self._device

    # -- ouverture -------------------------------------------------------- #

    def open(self, device: MidiDevice | int | None) -> bool:
        """Ouvre un port. Rend ``False`` plutôt que de lever."""
        if _winmm is None or device is None:
            return False
        index = device.index if isinstance(device, MidiDevice) else int(device)
        with self._lock:
            self.close()
            handle = ctypes.c_void_p()
            try:
                code = _winmm.midiOutOpen(ctypes.byref(handle), index,
                                          None, None, 0)
            except Exception as exc:   # noqa: BLE001
                log.warning("ouverture MIDI impossible : %s", exc)
                return False
            if code != 0:
                log.warning("ouverture du port MIDI %d refusée (code %d)",
                            index, code)
                return False
            self._handle = handle
            if isinstance(device, MidiDevice):
                self._device = device
            else:
                self._device = next(
                    (d for d in outputs() if d.index == index),
                    MidiDevice(index, "port %d" % index, "out"))
            log.info("sortie MIDI ouverte : %s", self._device.name)
            return True

    def open_deluge(self) -> bool:
        """Ouvre le Deluge s'il est branché."""
        return self.open(find("out"))

    def close(self) -> None:
        """Ferme le port, après avoir éteint ce qui sonnait encore."""
        with self._lock:
            if self._handle is None:
                return
            try:
                self.all_notes_off()
                _winmm.midiOutReset(self._handle)
                _winmm.midiOutClose(self._handle)
            except Exception as exc:   # noqa: BLE001
                log.debug("fermeture MIDI imparfaite : %s", exc)
            self._handle = None
            self._device = None
            self._sounding.clear()

    # -- envoi ------------------------------------------------------------ #

    def send(self, status: int, data1: int = 0, data2: int = 0) -> bool:
        """Envoie un message court. ``False`` si le port n'est pas ouvert."""
        with self._lock:
            if self._handle is None:
                return False
            try:
                code = _winmm.midiOutShortMsg(
                    self._handle, short_message(status, data1, data2))
            except Exception as exc:   # noqa: BLE001
                log.debug("envoi MIDI impossible : %s", exc)
                return False
            if code != 0:
                log.debug("message MIDI refusé (code %d)", code)
                return False
            return True

    def note_on(self, note: int, velocity: int = 100, channel: int = 1) -> bool:
        canal = _channel(channel)
        touche = _clamp7(note)
        if self.send(NOTE_ON | canal, touche, _clamp7(velocity)):
            self._sounding.add((canal, touche))
            return True
        return False

    def note_off(self, note: int, channel: int = 1) -> bool:
        canal = _channel(channel)
        touche = _clamp7(note)
        self._sounding.discard((canal, touche))
        return self.send(NOTE_OFF | canal, touche, 0)

    def control_change(self, cc: int, value: int, channel: int = 1) -> bool:
        return self.send(CONTROL_CHANGE | _channel(channel),
                         _clamp7(cc), _clamp7(value))

    def program_change(self, program: int, channel: int = 1) -> bool:
        return self.send(PROGRAM_CHANGE | _channel(channel), _clamp7(program))

    def pitch_bend(self, value: int = 8192, channel: int = 1) -> bool:
        """Molette de hauteur, 0..16383 (8192 = centre)."""
        try:
            v = int(value)
        except (TypeError, ValueError):
            v = 8192
        v = 0 if v < 0 else (16383 if v > 16383 else v)
        return self.send(PITCH_BEND | _channel(channel), v & 0x7F, v >> 7)

    def realtime(self, status: int) -> bool:
        """Horloge, départ, arrêt : des messages d'un seul octet."""
        return self.send(status, 0, 0)

    def all_notes_off(self, channel: int | None = None) -> None:
        """Éteint tout, et pas seulement en théorie.

        ``CC 123`` ne suffit pas partout : certains appareils l'ignorent. On
        envoie donc aussi un ``note off`` pour chaque note que **nous** avons
        allumée, ce qui couvre le cas réel — une note restée coincée parce que
        l'application a été fermée en pleine écoute.
        """
        with self._lock:
            if self._handle is None:
                return
            canaux = range(16) if channel is None else [_channel(channel)]
            for note, touche in sorted(self._sounding):
                if channel is None or note == _channel(channel):
                    self.send(NOTE_OFF | note, touche, 0)
            self._sounding = {
                (c, n) for (c, n) in self._sounding if c not in set(canaux)}
            for canal in canaux:
                self.send(CONTROL_CHANGE | canal, CC_ALL_NOTES_OFF, 0)

    # -- confort ----------------------------------------------------------- #

    def play_note(self, note: int, velocity: int = 100, seconds: float = 0.4,
                  channel: int = 1) -> None:
        """Joue une note et la relâche. **Bloque** le temps de la tenir.

        À appeler depuis un fil de travail, jamais depuis l'interface.
        """
        if not self.note_on(note, velocity, channel):
            return
        try:
            time.sleep(max(0.0, float(seconds)))
        finally:
            self.note_off(note, channel)

    def __enter__(self) -> "MidiOut":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


# --------------------------------------------------------------------------- #
# Entrée
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class MidiMessage:
    """Un message reçu, avec l'instant où Windows l'a horodaté."""

    status: int
    data1: int
    data2: int
    millis: int

    @property
    def kind(self) -> int:
        """Type de message, sans le canal."""
        return self.status & 0xF0 if self.status < 0xF0 else self.status

    @property
    def channel(self) -> int:
        """Canal 1..16, ou 0 pour un message système."""
        return (self.status & 0x0F) + 1 if self.status < 0xF0 else 0

    @property
    def is_note_on(self) -> bool:
        return self.kind == NOTE_ON and self.data2 > 0

    @property
    def is_note_off(self) -> bool:
        return self.kind == NOTE_OFF or (self.kind == NOTE_ON
                                         and self.data2 == 0)


class MidiIn:
    """Écoute un port d'entrée et empile ce qui arrive.

    Le rappel vient d'un fil de Windows : il ne fait qu'empiler. L'interface
    vide la file quand elle veut, avec :meth:`poll`.
    """

    def __init__(self, maxsize: int = 4096) -> None:
        self._handle = None
        self._device: MidiDevice | None = None
        self._queue: "queue.Queue[MidiMessage]" = queue.Queue(maxsize=maxsize)
        self._proc = None              # doit survivre tant que le port est ouvert
        self._lock = threading.RLock()
        self._perdus = 0

    @property
    def is_open(self) -> bool:
        return self._handle is not None

    @property
    def device(self) -> MidiDevice | None:
        return self._device

    @property
    def dropped(self) -> int:
        """Messages perdus parce que la file débordait."""
        return self._perdus

    def open(self, device: MidiDevice | int | None) -> bool:
        if _winmm is None or device is None:
            return False
        index = device.index if isinstance(device, MidiDevice) else int(device)
        with self._lock:
            self.close()

            def _rappel(_hmi, msg, _inst, param1, _param2):
                # Appelé par un fil de Windows. Rien d'autre qu'un empilement,
                # et surtout aucune exception qui remonterait dans du code C.
                try:
                    if msg == _MIM_DATA:
                        brut = int(param1 or 0) & 0xFFFFFFFF
                        self._push(brut & 0xFF, (brut >> 8) & 0x7F,
                                   (brut >> 16) & 0x7F)
                except Exception:      # noqa: BLE001 - jamais vers le C
                    pass

            self._proc = _MIDI_IN_PROC(_rappel)
            handle = ctypes.c_void_p()
            try:
                code = _winmm.midiInOpen(ctypes.byref(handle), index,
                                         self._proc, None,
                                         _CALLBACK_FUNCTION)
            except Exception as exc:   # noqa: BLE001
                log.warning("ouverture de l'entrée MIDI impossible : %s", exc)
                self._proc = None
                return False
            if code != 0:
                log.warning("entrée MIDI %d refusée (code %d)", index, code)
                self._proc = None
                return False
            self._handle = handle
            self._device = (device if isinstance(device, MidiDevice)
                            else next((d for d in inputs()
                                       if d.index == index),
                                      MidiDevice(index, "port %d" % index,
                                                 "in")))
            try:
                _winmm.midiInStart(self._handle)
            except Exception as exc:   # noqa: BLE001
                log.warning("démarrage de l'entrée MIDI impossible : %s", exc)
                self.close()
                return False
            log.info("entrée MIDI ouverte : %s", self._device.name)
            return True

    def open_deluge(self) -> bool:
        return self.open(find("in"))

    def _push(self, status: int, data1: int, data2: int) -> None:
        try:
            self._queue.put_nowait(
                MidiMessage(status, data1, data2, int(time.monotonic() * 1000)))
        except queue.Full:
            self._perdus += 1

    def poll(self, limit: int = 512) -> list[MidiMessage]:
        """Rend ce qui est arrivé depuis le dernier appel."""
        recus = []
        for _ in range(max(1, int(limit))):
            try:
                recus.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return recus

    def close(self) -> None:
        with self._lock:
            if self._handle is None:
                self._proc = None
                return
            try:
                _winmm.midiInStop(self._handle)
                _winmm.midiInReset(self._handle)
                _winmm.midiInClose(self._handle)
            except Exception as exc:   # noqa: BLE001
                log.debug("fermeture de l'entrée MIDI imparfaite : %s", exc)
            self._handle = None
            self._device = None
            # Le rappel n'est relâché qu'après la fermeture : Windows pourrait
            # encore l'appeler entre le stop et le close.
            self._proc = None

    def __enter__(self) -> "MidiIn":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()
