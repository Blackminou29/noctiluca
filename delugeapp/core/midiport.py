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

Ce que ce module fait
---------------------

Il envoie et reçoit des **messages courts** — notes, pression, molette,
contrôleurs, horloge — et des **messages exclusifs (SysEx)**, par lesquels le
firmware communautaire donne sa version et recopie son écran
(:mod:`delugeapp.core.delugesysex`).

Le Deluge se présente en USB avec **trois ports** (« câbles ») dans chaque
sens (``io/midi/r_usb_pmidi_descriptor.c``) : les deux premiers portent les
notes, les contrôleurs et l'horloge, le troisième ne sert qu'aux SysEx
(``upstreamUSBMIDIDevice_port3`` : « not used for channel data »). Windows
les nomme selon son pilote — « Deluge », « MIDIOUT2 (Deluge) »,
« MIDIIN3 (Deluge) » avec le pilote classique ; d'autres noms avec les
services MIDI 2.0 de Windows 11. :attr:`MidiDevice.cable` lit le numéro dans
toutes ces formes.

Sûreté
------

* les rappels d'entrée viennent d'un fil de Windows : ils ne font que copier
  et empiler, n'appellent aucune fonction multimédia et ne prennent aucun
  verrou de ce module. Rendre un tampon SysEx au pilote
  (``midiInAddBuffer``) se fait dans un fil à part : la documentation de
  Windows l'interdit dans le rappel, qui peut sinon bloquer ;
* l'objet ``CFUNCTYPE`` d'un rappel n'est **jamais** relâché : un pilote
  peut encore l'appeler juste après la fermeture, et un rappel ramassé par
  le collecteur fait tomber le processus ;
* un tampon envoyé au pilote reste vivant jusqu'à ce que le pilote le rende
  (``MHDR_DONE``) ; s'il ne le rend jamais, il est gardé plutôt que libéré ;
* toutes les entrées publiques sont tolérantes : un port disparu, un appareil
  débranché en cours de route ou un numéro invalide donnent ``False``, jamais
  une exception.
"""

from __future__ import annotations

import logging
import queue
import re
import threading
import time
from dataclasses import dataclass

from ..i18n import N_, tr

log = logging.getLogger(__name__)

__all__ = [
    "MidiDevice", "MidiOut", "MidiIn", "MidiMessage",
    "available", "outputs", "inputs", "find", "deluge_ports", "cable_of",
    "error_text",
    "NOTE_OFF", "NOTE_ON", "CONTROL_CHANGE", "PROGRAM_CHANGE", "PITCH_BEND",
    "SYSEX", "CLOCK", "START", "CONTINUE", "STOP",
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

#: Début d'un message exclusif.
SYSEX = 0xF0
#: Messages système temps réel, sans canal.
CLOCK = 0xF8
START = 0xFA
CONTINUE = 0xFB
STOP = 0xFC

#: Contrôleurs utiles au-delà de la carte MIDI Follow.
CC_ALL_SOUND_OFF = 120
CC_ALL_NOTES_OFF = 123

#: Taille et nombre des tampons de réception SysEx. Le plus long message du
#: Deluge — une image d'écran non compressée — fait 888 octets.
SYSEX_BUFFER_SIZE = 4096
SYSEX_BUFFERS = 6

#: Codes d'erreur de ``winmm`` que l'on sait expliquer.
_ERREURS = {
    1: N_("erreur inconnue du système MIDI"),
    2: N_("port introuvable — l'appareil a peut-être été débranché"),
    4: N_("port déjà utilisé par une autre application (fermez-la, ou "
          "choisissez un autre port)"),
    6: N_("pilote MIDI absent"),
    7: N_("mémoire insuffisante"),
    11: N_("paramètre refusé par le pilote"),
    65: N_("un message est encore en cours d'envoi"),
    67: N_("le pilote n'a pas répondu"),
}


def error_text(code: int) -> str:
    """Explication d'un code d'erreur ``MMRESULT``, dans la langue de
    l'interface."""
    try:
        code = int(code)
    except (TypeError, ValueError):
        return tr("erreur MIDI")
    if code in _ERREURS:
        return tr(_ERREURS[code])
    return tr("erreur MIDI %d") % code


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


if ctypes is not None:

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

    class _MIDIHDR(ctypes.Structure):
        """``MIDIHDR`` : le tampon d'un message long. 120 octets en 64 bits."""

        _fields_ = [
            ("lpData", ctypes.c_void_p),
            ("dwBufferLength", wintypes.DWORD),
            ("dwBytesRecorded", wintypes.DWORD),
            ("dwUser", ctypes.c_size_t),
            ("dwFlags", wintypes.DWORD),
            ("lpNext", ctypes.c_void_p),
            ("reserved", ctypes.c_size_t),
            ("dwOffset", wintypes.DWORD),
            ("dwReserved", ctypes.c_size_t * 8),
        ]

    _CALLBACK_FUNCTION = 0x00030000
    _MIDI_IN_PROC = ctypes.WINFUNCTYPE(
        None, wintypes.HANDLE, wintypes.UINT,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)

_MIM_DATA = 0x3C3
_MIM_LONGDATA = 0x3C4
_MIM_LONGERROR = 0x3C6
_MHDR_DONE = 0x00000001
_MIDIERR_STILLPLAYING = 65

#: Rappels jamais relâchés (voir « Sûreté » plus haut).
_RAPPELS_GARDES: list = []
#: Tampons qu'un pilote n'a jamais rendus : gardés, jamais libérés.
_TAMPONS_GARDES: list = []


def available() -> bool:
    """Vrai si la machine sait faire du MIDI temps réel."""
    return _winmm is not None


def load_error() -> str:
    """Pourquoi le MIDI n'est pas disponible, pour l'afficher à l'utilisateur."""
    return _LOAD_ERROR


# --------------------------------------------------------------------------- #
# Appareils
# --------------------------------------------------------------------------- #

#: Les formes du numéro de port, de la plus sûre à la plus vague.
_CABLE = (
    re.compile(r"midi(?:in|out)\s*(\d+)", re.I),      # « MIDIOUT2 (Deluge) »
    re.compile(r"\[(\d+)\]"),                          # « Deluge [2] »
    re.compile(r"\bport\s*(\d+)", re.I),               # « Deluge Port 2 »
    re.compile(r"\bmidi\s+(\d+)\b", re.I),             # « Deluge MIDI 2 »
    re.compile(r"\((\d+)\)\s*$"),                      # « Deluge (2) »
    re.compile(r"\s(\d+)\s*$"),                        # « Deluge 2 »
)
#: « 2- Deluge » : Windows numérote ainsi un **second appareil** identique,
#: pas un second port.
_INSTANCE = re.compile(r"^\s*(\d+)\s*-\s*")


def cable_of(name: str) -> int:
    """Numéro de port USB (« câble », à partir de 1) lu dans le nom."""
    texte = _INSTANCE.sub("", str(name or ""))
    for motif in _CABLE:
        trouve = motif.search(texte)
        if trouve:
            try:
                return max(1, int(trouve.group(1)))
            except ValueError:
                continue
    return 1


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
        31 caractères. Le Deluge s'annonce « Deluge » (fabricant
        « Synthstrom Audible ») ; selon les pilotes on voit aussi
        « MIDIOUT2 (Deluge) » ou un nom précédé du numéro d'appareil
        (« 2- Deluge »). On cherche donc le mot, pas l'égalité.
        """
        bas = self.name.casefold()
        return "deluge" in bas or "synthstrom" in bas

    @property
    def cable(self) -> int:
        """Port USB de l'appareil : 1 et 2 pour les notes, 3 pour les SysEx."""
        return cable_of(self.name)

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


def deluge_ports(kind: str = "out",
                 devices: list[MidiDevice] | None = None) -> list[MidiDevice]:
    """Les ports du Deluge, du premier câble au dernier.

    Un second Deluge branché (« 2- Deluge ») vient après le premier.
    """
    tous = devices if devices is not None else (
        outputs() if kind == "out" else inputs())
    candidats = [d for d in tous if d.is_deluge]

    def cle(d: MidiDevice):
        instance = _INSTANCE.match(d.name)
        return (int(instance.group(1)) if instance else 1, d.cable, d.index)

    return sorted(candidats, key=cle)


def find(kind: str = "out", cable: int | None = None) -> MidiDevice | None:
    """Le Deluge parmi les ports, ou ``None``.

    Sans ``cable``, le port des notes (câble 1) s'il se distingue, sinon le
    premier port du Deluge. Avec ``cable``, ce port-là seulement.
    """
    ports = deluge_ports(kind)
    if not ports:
        return None
    if cable is None:
        for port in ports:
            if port.cable == 1:
                return port
        return ports[0]
    for port in ports:
        if port.cable == int(cable):
            return port
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
        #: Vrai dès qu'un message de canal est parti : à la fermeture, il y
        #: a peut-être quelque chose à éteindre. Sinon, rien.
        self._canal = False
        #: Dernière erreur d'ouverture, en clair (vide si aucune).
        self.last_error = ""

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
                self.last_error = str(exc)
                return False
            if code != 0:
                self.last_error = error_text(code)
                log.warning("ouverture du port MIDI %d refusée : %s",
                            index, self.last_error)
                return False
            self.last_error = ""
            self._handle = handle
            self._canal = False
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
        """Ferme le port, après avoir éteint ce qui sonnait encore.

        Un port qui n'a porté **aucun message de canal** — celui des SysEx,
        ou un port seulement ouvert pour parler à la machine — se ferme sans
        rien envoyer. Avant, chaque fermeture envoyait seize « All Notes
        Off » et un ``midiOutReset`` (qui peut émettre un relâchement par
        note et un CC 64 par canal) : du bruit pour une machine à qui l'on
        n'avait rien joué.
        """
        with self._lock:
            if self._handle is None:
                return
            try:
                if self._canal:
                    self.all_notes_off()
                    _winmm.midiOutReset(self._handle)
                code = _winmm.midiOutClose(self._handle)
                if code == _MIDIERR_STILLPLAYING:
                    # Un tampon encore chez le pilote : il faut le reprendre.
                    _winmm.midiOutReset(self._handle)
                    _winmm.midiOutClose(self._handle)
            except Exception as exc:   # noqa: BLE001
                log.debug("fermeture MIDI imparfaite : %s", exc)
            self._handle = None
            self._device = None
            self._sounding.clear()
            self._canal = False

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
            if int(status) < SYSEX:
                self._canal = True
            return True

    def send_sysex(self, data: bytes, timeout: float = 2.0) -> bool:
        """Envoie un message exclusif complet (``F0 … F7``).

        Le tampon est préparé, confié au pilote, puis **attendu** jusqu'à ce
        que le pilote le rende (``MHDR_DONE``) : le libérer avant ferait
        lire au pilote une mémoire rendue. Au-delà de ``timeout``, l'envoi est
        abandonné (``midiOutReset``) ; un tampon jamais rendu est gardé.
        """
        message = bytes(data or b"")
        if len(message) < 3 or message[0] != SYSEX or message[-1] != 0xF7:
            return False
        if any(b & 0x80 for b in message[1:-1]):
            log.debug("SysEx refusé : octet de données au-dessus de 127")
            return False
        with self._lock:
            if self._handle is None or _winmm is None:
                return False
            tampon = ctypes.create_string_buffer(message, len(message))
            entete = _MIDIHDR()
            entete.lpData = ctypes.cast(tampon, ctypes.c_void_p)
            entete.dwBufferLength = len(message)
            entete.dwBytesRecorded = len(message)
            taille = ctypes.sizeof(entete)
            try:
                code = _winmm.midiOutPrepareHeader(
                    self._handle, ctypes.byref(entete), taille)
            except Exception as exc:   # noqa: BLE001
                log.debug("SysEx impossible à préparer : %s", exc)
                return False
            if code != 0:
                log.debug("SysEx refusé à la préparation : %s",
                          error_text(code))
                return False
            envoye = False
            try:
                code = _winmm.midiOutLongMsg(
                    self._handle, ctypes.byref(entete), taille)
                if code != 0:
                    log.debug("SysEx refusé : %s", error_text(code))
                    return False
                limite = time.monotonic() + max(0.05, float(timeout))
                while not entete.dwFlags & _MHDR_DONE:
                    if time.monotonic() > limite:
                        log.warning("SysEx sans réponse du pilote : abandon")
                        _winmm.midiOutReset(self._handle)
                        break
                    time.sleep(0.001)
                envoye = bool(entete.dwFlags & _MHDR_DONE)
                return envoye
            except Exception as exc:   # noqa: BLE001
                log.debug("SysEx interrompu : %s", exc)
                return False
            finally:
                if not self._unprepare_out(entete, taille):
                    _TAMPONS_GARDES.append((tampon, entete))

    def _unprepare_out(self, entete, taille: int) -> bool:
        """Rend le tampon ; ``False`` si le pilote le tient encore."""
        for _ in range(400):
            try:
                code = _winmm.midiOutUnprepareHeader(
                    self._handle, ctypes.byref(entete), taille)
            except Exception as exc:   # noqa: BLE001
                log.debug("tampon SysEx non rendu : %s", exc)
                return False
            if code != _MIDIERR_STILLPLAYING:
                return code == 0
            time.sleep(0.005)
        return False

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
    """Un message reçu.

    ``millis`` : l'instant de réception, en millisecondes (horloge monotone
    du processus). ``stamp`` : l'horodatage du pilote, en millisecondes
    depuis l'ouverture du port — plus fiable pour mesurer un tempo, parce
    qu'il ne dépend pas de l'ordonnancement des fils. ``data`` : le message
    entier pour un SysEx (``status`` vaut alors ``0xF0``). ``arrived`` :
    l'instant de réception en secondes de :func:`time.perf_counter`, pour
    mesurer un aller-retour sans compter l'attente dans la file (``0.0``
    quand il n'est pas connu).
    """

    status: int
    data1: int
    data2: int
    millis: int
    stamp: int = 0
    data: bytes = b""
    arrived: float = 0.0

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

    @property
    def is_sysex(self) -> bool:
        return self.status == SYSEX


class MidiIn:
    """Écoute un port d'entrée et empile ce qui arrive.

    Le rappel vient d'un fil de Windows : il ne fait qu'empiler. L'interface
    vide la file quand elle veut, avec :meth:`poll`.

    Les SysEx arrivent dans des tampons confiés d'avance au pilote. Le rappel
    copie le tampon rempli puis le signale à un fil de recyclage, qui le rend
    au pilote : ``midiInAddBuffer`` n'a pas sa place dans le rappel.
    """

    def __init__(self, maxsize: int = 4096, sysex: bool = True) -> None:
        self._handle = None
        self._device: MidiDevice | None = None
        self._queue: "queue.Queue[MidiMessage]" = queue.Queue(maxsize=maxsize)
        self._proc = None
        self._lock = threading.RLock()
        self._perdus = 0
        self._sysex = bool(sysex)
        self._entetes: list = []
        self._tampons: list = []
        self._adresses: dict[int, int] = {}
        self._a_rendre: "queue.Queue[int | None]" = queue.Queue()
        self._recycleur: threading.Thread | None = None
        #: Signal de fin de la session ouverte : le fil de recyclage d'une
        #: session ne touche jamais aux tampons d'une autre.
        self._fin = threading.Event()
        #: SysEx en cours de réassemblage (un message peut couvrir plusieurs
        #: tampons).
        self._morceau = bytearray()
        #: Destinataire direct de certains SysEx — l'accès aux fichiers de la
        #: carte, qui attend chaque réponse pour envoyer la suite : appelé
        #: depuis le fil du pilote, il rend ``True`` s'il garde le message.
        self._tap = None
        #: Dernière erreur d'ouverture, en clair.
        self.last_error = ""

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
        # Fermer **avant** de prendre le verrou : la fermeture attend le fil
        # de recyclage, qui peut attendre ce verrou.
        self.close()
        with self._lock:

            def _rappel(_hmi, msg, _inst, param1, param2):
                # Appelé par un fil de Windows. Copier, empiler, rien d'autre,
                # et surtout aucune exception qui remonterait dans du code C.
                try:
                    if msg == _MIM_DATA:
                        brut = int(param1 or 0) & 0xFFFFFFFF
                        self._push(brut & 0xFF, (brut >> 8) & 0xFF,
                                   (brut >> 16) & 0xFF,
                                   int(param2 or 0) & 0xFFFFFFFF)
                    elif msg in (_MIM_LONGDATA, _MIM_LONGERROR):
                        self._long(msg, int(param1 or 0),
                                   int(param2 or 0) & 0xFFFFFFFF)
                except Exception:      # noqa: BLE001 - jamais vers le C
                    pass

            proc = _MIDI_IN_PROC(_rappel)
            _RAPPELS_GARDES.append(proc)
            self._proc = proc
            handle = ctypes.c_void_p()
            try:
                code = _winmm.midiInOpen(ctypes.byref(handle), index,
                                         proc, None, _CALLBACK_FUNCTION)
            except Exception as exc:   # noqa: BLE001
                log.warning("ouverture de l'entrée MIDI impossible : %s", exc)
                self.last_error = str(exc)
                return False
            if code != 0:
                self.last_error = error_text(code)
                log.warning("entrée MIDI %d refusée : %s", index,
                            self.last_error)
                return False
            self.last_error = ""
            self._handle = handle
            self._fin = threading.Event()
            self._device = (device if isinstance(device, MidiDevice)
                            else next((d for d in inputs()
                                       if d.index == index),
                                      MidiDevice(index, "port %d" % index,
                                                 "in")))
            if self._sysex:
                self._prepare_buffers()
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

    # -- tampons SysEx ------------------------------------------------------ #

    def _prepare_buffers(self) -> None:
        """Confie les tampons au pilote et lance le fil de recyclage."""
        taille = ctypes.sizeof(_MIDIHDR)
        for numero in range(SYSEX_BUFFERS):
            tampon = ctypes.create_string_buffer(SYSEX_BUFFER_SIZE)
            entete = _MIDIHDR()
            entete.lpData = ctypes.cast(tampon, ctypes.c_void_p)
            entete.dwBufferLength = SYSEX_BUFFER_SIZE
            entete.dwUser = numero
            try:
                code = _winmm.midiInPrepareHeader(
                    self._handle, ctypes.byref(entete), taille)
                if code == 0:
                    code = _winmm.midiInAddBuffer(
                        self._handle, ctypes.byref(entete), taille)
            except Exception as exc:   # noqa: BLE001
                log.debug("tampon SysEx refusé : %s", exc)
                code = -1
            self._tampons.append(tampon)
            self._entetes.append(entete)
            self._adresses[ctypes.addressof(entete)] = numero
            if code != 0:
                log.debug("tampon SysEx %d refusé : %s", numero,
                          error_text(code))
        self._a_rendre = queue.Queue()
        self._recycleur = threading.Thread(
            target=self._recycler,
            args=(self._a_rendre, self._fin, self._handle, self._entetes),
            name="midi-sysex", daemon=True)
        self._recycleur.start()

    def _long(self, msg: int, adresse: int, stamp: int) -> None:
        """Rappel : un tampon SysEx est revenu du pilote."""
        numero = self._adresses.get(adresse)
        if numero is None:
            return
        entete = self._entetes[numero]
        recus = int(entete.dwBytesRecorded)
        if recus and msg == _MIM_LONGDATA:
            self._assemble(ctypes.string_at(entete.lpData, recus), stamp)
        self._a_rendre.put_nowait(numero)

    def _assemble(self, morceau: bytes, stamp: int) -> None:
        """Recolle un SysEx réparti sur plusieurs tampons."""
        if morceau[:1] == bytes((SYSEX,)):
            self._morceau = bytearray(morceau)
        elif self._morceau:
            self._morceau.extend(morceau)
        else:
            return                       # suite d'un message perdu
        if self._morceau and self._morceau[-1] == 0xF7:
            complet = bytes(self._morceau)
            self._morceau = bytearray()
            tap = self._tap
            if tap is not None:
                try:
                    if tap(complet, time.perf_counter()):
                        return
                except Exception as exc:   # noqa: BLE001 - fil du pilote
                    log.debug("SysEx refusé par son destinataire : %s", exc)
            self._push(SYSEX, 0, 0, stamp, complet)
        elif len(self._morceau) > 64 * SYSEX_BUFFER_SIZE:
            self._morceau = bytearray()  # jamais terminé : abandon

    def _recycler(self, file, fin, handle, entetes) -> None:
        """Fil de recyclage : rend au pilote les tampons lus.

        Il ne connaît que **sa** session (file, signal, poignée, tampons) :
        un fil en retard ne peut pas rendre un tampon à un port rouvert.
        """
        taille = ctypes.sizeof(_MIDIHDR)
        while True:
            numero = file.get()
            if numero is None or fin.is_set():
                return
            with self._lock:
                if fin.is_set():
                    return
                entete = entetes[numero]
                entete.dwBytesRecorded = 0
                try:
                    code = _winmm.midiInAddBuffer(
                        handle, ctypes.byref(entete), taille)
                except Exception as exc:   # noqa: BLE001
                    log.debug("tampon SysEx non rendu : %s", exc)
                    continue
                if code != 0:
                    log.debug("tampon SysEx non rendu : %s", error_text(code))

    # -- file ----------------------------------------------------------------- #

    def _push(self, status: int, data1: int, data2: int, stamp: int = 0,
              data: bytes = b"") -> None:
        try:
            self._queue.put_nowait(MidiMessage(
                status, data1, data2, int(time.monotonic() * 1000),
                int(stamp), data, time.perf_counter()))
        except queue.Full:
            self._perdus += 1

    def set_sysex_tap(self, tap) -> None:
        """Confie certains SysEx à ``tap(données, instant) -> bool`` dès leur
        arrivée, au lieu de la file. ``None`` le retire."""
        self._tap = tap

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
        """Ferme le port : stop, reset (le pilote rend les tampons), fil de
        recyclage arrêté, tampons libérés, port fermé — dans cet ordre."""
        with self._lock:
            if self._handle is None:
                return
            handle = self._handle
            self._fin.set()
        try:
            _winmm.midiInStop(handle)
            _winmm.midiInReset(handle)
        except Exception as exc:       # noqa: BLE001
            log.debug("arrêt de l'entrée MIDI imparfait : %s", exc)
        recycleur = self._recycleur
        if recycleur is not None:
            self._a_rendre.put(None)
            recycleur.join(2.0)
            if recycleur.is_alive():
                log.warning("le fil de recyclage SysEx ne s'arrête pas")
        with self._lock:
            taille = ctypes.sizeof(_MIDIHDR) if ctypes is not None else 0
            for entete, tampon in zip(self._entetes, self._tampons):
                try:
                    code = _winmm.midiInUnprepareHeader(
                        handle, ctypes.byref(entete), taille)
                except Exception as exc:   # noqa: BLE001
                    log.debug("tampon SysEx non libéré : %s", exc)
                    code = -1
                if code != 0:
                    _TAMPONS_GARDES.append((tampon, entete))
            try:
                _winmm.midiInClose(handle)
            except Exception as exc:   # noqa: BLE001
                log.debug("fermeture de l'entrée MIDI imparfaite : %s", exc)
            self._handle = None
            self._device = None
            self._entetes = []
            self._tampons = []
            self._adresses = {}
            self._recycleur = None
            self._morceau = bytearray()
            # Le rappel, lui, reste dans ``_RAPPELS_GARDES`` : un pilote peut
            # encore l'appeler après la fermeture.
            self._proc = None

    def __enter__(self) -> "MidiIn":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()
