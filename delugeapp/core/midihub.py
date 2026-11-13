# -*- coding: utf-8 -*-
"""Le hub MIDI : l'ordinateur au centre, entre le Deluge, les claviers et le DAW.

Le Deluge n'a qu'une prise USB. Branché à l'ordinateur, il ne peut plus
accueillir un clavier : c'est à l'ordinateur de lui faire suivre ce que le
clavier joue. Ce module le fait — et, plus largement, relie n'importe quelle
entrée MIDI à n'importe quelle sortie.

Les mots
--------

* un **port** : une entrée ou une sortie MIDI que Windows nomme. Le Deluge
  est à part : il passe par le lien que l'application tient déjà avec lui
  (:mod:`delugeapp.core.delugelink`), sous l'identifiant :data:`DELUGE` —
  ses ports ne s'ouvrent pas deux fois, et un pilote qui n'accepte qu'un
  client ne refuse rien ;
* un **branchement** (:class:`Route`) : « ce qui arrive de cette entrée part
  vers cette sortie », avec ce qu'il laisse passer, le canal d'arrivée, la
  transposition et la table qui traduit les boutons d'un contrôleur ;
* le **hub** (:class:`MidiHub`) : il ouvre les ports dont ses branchements
  ont besoin — eux seuls —, et relaie.

Le chemin d'un message
----------------------

Le rappel du pilote ne fait qu'empiler (:meth:`midiport.MidiIn.set_message_tap`) ;
un fil du hub dépile et envoie. Entre les deux, un seul changement de fil :
le retard se mesure (:meth:`MidiHub.stats`) au lieu de se supposer.

Ce que le hub garantit
----------------------

* **aucune note coincée** : il sait quelles notes il a fait passer, par
  branchement. Couper un branchement, le modifier, débrancher un appareil
  ou arrêter le hub relâche ces notes-là, là où elles sont parties — et
  la pédale, et la molette ;
* **une note relâchée part où elle a été jouée**, même si l'on a changé de
  canal ou d'octave entre l'appui et le relâchement ;
* **une boucle MIDI ne s'emballe pas** : une source qui débite plus de
  :data:`RATE_MAX` messages par seconde, ou qui répète la même note plus
  de :data:`REPEAT_MAX` fois, est coupée (:meth:`MidiHub.rearm` la rend) ;
* **rien ne lève** : un port disparu, un envoi refusé, un fichier de
  réglages abîmé donnent un état lisible, jamais une exception.

Les SysEx ne traversent pas le hub : ceux du Deluge sont le dialogue de
l'application avec lui.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import sys
import tempfile
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from ..i18n import N_, decimal, plural, tr, untranslated
from . import midifollow, midiport

log = logging.getLogger(__name__)

__all__ = [
    "DELUGE", "FOLLOW_TARGETS", "RATE_MAX", "REPEAT_MAX", "Backend",
    "Endpoint", "Event", "HubStats", "MidiHub", "Route", "default_route",
    "describe_message", "describe_route", "endpoint_label", "load_config",
    "role_of", "save_config", "target_label",
]

#: Le Deluge, tel que le lien de l'application le tient.
DELUGE = "@deluge"

#: Ce qu'un branchement vers le Deluge peut viser, au sens de MIDI Follow :
#: l'instrument qu'on regarde (A, B, C), ou une piste donnée (firmware 1.3).
FOLLOW_TARGETS = ("a", "b", "c") + tuple(
    "track_%d" % n for n in range(1, midifollow.FOLLOW_TRACKS + 1))

#: Au-delà, par seconde et par source, ce n'est plus quelqu'un qui joue
#: mais une boucle : un clavier à pression par touche, dix doigts posés, en
#: envoie un millier.
RATE_MAX = 4000
#: La même note rejouée plus souvent que cela dans la seconde revient par
#: un câble.
REPEAT_MAX = 64

#: La durée au bout de laquelle un fil de Python cède la main à un autre
#: qui l'attend, tant que le hub relaie. Par défaut 5 ms — et sous Windows,
#: où cette attente suit le battement de l'ordonnanceur, 8 ms de retard
#: médian et 32 au pire dès que l'interface calcule (mesuré le 12 novembre
#: 2026 : une analyse, un tri, du texte). Sous la milliseconde, l'attente
#: n'en est plus une : 0,04 ms de médiane, 7 au pire, et le fil occupé ne
#: perd rien de mesurable. 1 ms ne change rien : il faut passer dessous.
SWITCH_INTERVAL = 0.0002

#: Retards gardés pour la statistique.
LATENCIES = 1024
#: Messages gardés pour le moniteur.
MONITOR = 256

#: Messages système sans intérêt pour personne : le « je suis là » qu'un
#: clavier envoie trois fois par seconde.
_ACTIVE_SENSING = 0xFE

#: Ce qui trahit un port virtuel — celui par lequel un DAW entend le hub.
_VIRTUEL = re.compile(
    r"loop\s*midi|loopbe|loopback|virtual|virtuel|rtp\s*midi|noctiluca"
    r"|midi\s*yoke|\bdaw\b|\biac\b|sbvmidi|tevirtual", re.I)
#: Le synthé de table d'ondes livré avec Windows, au nom que Windows lui
#: donne dans toutes les langues.
_SYNTHE = re.compile(untranslated("microsoft gs wavetable"), re.I)

_ETATS = {
    "active": N_("en service"),
    "off": N_("coupé"),
    "hub_off": N_("hub à l'arrêt"),
    "no_source": N_("la source n'est pas branchée"),
    "no_dest": N_("la destination n'est pas branchée"),
    "no_channel": N_("le Deluge n'écoute pas cette cible"),
    "tripped": N_("coupé : boucle MIDI probable"),
}


#: Qui tient la bascule des fils raccourcie, et ce qu'elle valait avant.
_PRESSES = {"nombre": 0, "avant": None}
_PRESSES_VERROU = threading.Lock()


def _presser(oui: bool) -> None:
    """Raccourcit la bascule des fils de Python pour un hub de plus, ou la
    rend quand le dernier n'en a plus besoin."""
    with _PRESSES_VERROU:
        if oui:
            if _PRESSES["nombre"] == 0:
                _PRESSES["avant"] = sys.getswitchinterval()
                if _PRESSES["avant"] > SWITCH_INTERVAL:
                    sys.setswitchinterval(SWITCH_INTERVAL)
            _PRESSES["nombre"] += 1
            return
        _PRESSES["nombre"] = max(0, _PRESSES["nombre"] - 1)
        if _PRESSES["nombre"] == 0 and _PRESSES["avant"] is not None:
            sys.setswitchinterval(_PRESSES["avant"])
            _PRESSES["avant"] = None


def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _entier(valeur, defaut: int, mini: int, maxi: int) -> int:
    try:
        v = int(valeur)
    except (TypeError, ValueError):
        return defaut
    return mini if v < mini else (maxi if v > maxi else v)


# --------------------------------------------------------------------------- #
# Un branchement
# --------------------------------------------------------------------------- #

@dataclass
class Route:
    """Ce qui arrive de ``source`` part vers ``dest``.

    Les canaux se comptent de 1 à 16 ; 0 veut dire « tous » en entrée, et
    « celui d'origine » en sortie. ``follow`` remplace le canal de sortie
    par celui que le Deluge a réglé pour cette cible MIDI Follow
    (:data:`FOLLOW_TARGETS`) : s'il le change sur la machine, le branchement
    suit.
    """

    source: str
    dest: str
    enabled: bool = True
    #: N'écouter que ce canal de la source ; 0 : tous.
    channel_in: int = 0
    #: Canal d'arrivée ; 0 : celui d'origine. Ignoré si ``follow`` est posé.
    channel_out: int = 0
    #: Cible MIDI Follow du Deluge : ``"a"``, ``"track_2"``… ou ``""``.
    follow: str = ""
    #: Transposition, en demi-tons.
    transpose: int = 0
    #: Étendue du clavier qui passe (notes de la source, avant transposition).
    low: int = 0
    high: int = 127
    notes: bool = True
    #: Molette de hauteur et pression (par canal et par touche).
    bend: bool = True
    controllers: bool = True
    programs: bool = False
    #: Horloge, départ, arrêt, reprise, position.
    clock: bool = False
    #: Contrôleur de la source -> contrôleur envoyé : les boutons d'une
    #: surface de contrôle posés sur les réglages du Deluge.
    cc_map: dict[int, int] = field(default_factory=dict)
    uid: str = field(default_factory=_uid)

    def clone(self) -> "Route":
        return Route(**{**self.__dict__, "cc_map": dict(self.cc_map)})

    def to_dict(self) -> dict:
        return {
            "uid": self.uid, "source": self.source, "dest": self.dest,
            "enabled": bool(self.enabled),
            "channel_in": int(self.channel_in),
            "channel_out": int(self.channel_out), "follow": self.follow,
            "transpose": int(self.transpose),
            "low": int(self.low), "high": int(self.high),
            "notes": bool(self.notes), "bend": bool(self.bend),
            "controllers": bool(self.controllers),
            "programs": bool(self.programs), "clock": bool(self.clock),
            "cc_map": {str(k): int(v) for k, v in sorted(self.cc_map.items())},
        }

    @classmethod
    def from_dict(cls, data) -> "Route | None":
        """Un branchement lu dans un fichier, ou ``None`` s'il ne dit pas
        d'où il part ni où il va. Tout le reste se répare."""
        if not isinstance(data, dict):
            return None
        source, dest = data.get("source"), data.get("dest")
        if not (isinstance(source, str) and source.strip()
                and isinstance(dest, str) and dest.strip()):
            return None
        suivi = data.get("follow")
        table = {}
        brute = data.get("cc_map")
        if isinstance(brute, dict):
            for cle, valeur in brute.items():
                try:
                    de, vers = int(cle), int(valeur)
                except (TypeError, ValueError):
                    continue
                if 0 <= de <= 127 and 0 <= vers <= 127:
                    table[de] = vers
        bas = _entier(data.get("low"), 0, 0, 127)
        haut = _entier(data.get("high"), 127, 0, 127)
        uid = data.get("uid")
        return cls(
            source=source.strip(), dest=dest.strip(),
            enabled=data.get("enabled") is not False,
            channel_in=_entier(data.get("channel_in"), 0, 0, 16),
            channel_out=_entier(data.get("channel_out"), 0, 0, 16),
            follow=suivi if suivi in FOLLOW_TARGETS else "",
            transpose=_entier(data.get("transpose"), 0, -60, 60),
            low=min(bas, haut), high=max(bas, haut),
            notes=data.get("notes") is not False,
            bend=data.get("bend") is not False,
            controllers=data.get("controllers") is not False,
            programs=data.get("programs") is True,
            clock=data.get("clock") is True,
            cc_map=table,
            uid=uid if isinstance(uid, str) and uid else _uid())


def default_route(source: str, dest: str) -> Route:
    """Le branchement qu'un clic propose : vers le Deluge, il vise
    l'instrument qu'on y regarde (MIDI Follow A) ; ailleurs, tout part sur
    son canal d'origine. L'horloge ne passe que si on la demande."""
    return Route(source=source, dest=dest,
                 follow="a" if dest == DELUGE and source != DELUGE else "")


# --------------------------------------------------------------------------- #
# Dire les choses
# --------------------------------------------------------------------------- #

def role_of(name: str) -> str:
    """``deluge``, ``virtual`` (un port virtuel : le DAW), ``synth`` (le
    synthé de Windows) ou ``device`` (un clavier, une surface, un
    appareil)."""
    if name == DELUGE:
        return "deluge"
    if _SYNTHE.search(name or ""):
        return "synth"
    if _VIRTUEL.search(name or ""):
        return "virtual"
    return "device"


def endpoint_label(name: str) -> str:
    """Le nom d'un port, tel que la page le montre."""
    if name == DELUGE:
        return "Deluge"
    if role_of(name) == "synth":
        return tr("Synthé de Windows")
    return str(name or "")


def target_label(follow: str, channel: int | None = None) -> str:
    """Une cible MIDI Follow en clair : « l'instrument sélectionné
    (canal 1) », « la piste 3 (canal non réglé sur le Deluge) »."""
    if follow in ("a", "b", "c"):
        quoi = tr("l'instrument sélectionné — MIDI Follow %s") % follow.upper()
    elif follow.startswith("track_"):
        quoi = tr("la piste %s") % follow[6:]
    else:
        return tr("canal %d") % channel if channel else tr("canal d'origine")
    if channel:
        return tr("%s, canal %d") % (quoi, channel)
    return tr("%s, canal non réglé sur le Deluge") % quoi


def describe_route(route: Route, channel: int | None = None) -> str:
    """Un branchement en une phrase."""
    passe = [mot for vrai, mot in (
        (route.notes, tr("notes")),
        (route.bend, tr("molette et pression")),
        (route.controllers, tr("contrôleurs")),
        (route.programs, tr("programmes")),
        (route.clock, tr("horloge")),
    ) if vrai]
    if route.follow:
        vers = target_label(route.follow, channel)
    elif route.channel_out:
        vers = tr("canal %d") % route.channel_out
    else:
        vers = tr("canal d'origine")
    phrase = tr("« %s » vers « %s » : %s") % (
        endpoint_label(route.source), endpoint_label(route.dest), vers)
    if route.transpose:
        phrase += tr(", transposé de %+d demi-tons") % route.transpose
    if route.cc_map:
        phrase += ", " + (plural(len(route.cc_map), N_("%d bouton traduit"),
                                 N_("%d boutons traduits"))
                          % len(route.cc_map))
    return phrase + " — " + (", ".join(passe) if passe
                             else tr("rien ne passe"))


def describe_message(status: int, data1: int = 0, data2: int = 0) -> str:
    """Un message court en clair, pour le moniteur."""
    from .theory import note_to_name

    statut = int(status) & 0xFF
    if statut >= 0xF0:
        return {
            midiport.CLOCK: tr("horloge"),
            midiport.START: tr("départ"),
            midiport.CONTINUE: tr("reprise"),
            midiport.STOP: tr("arrêt"),
            midiport.SONG_POSITION: tr("position"),
        }.get(statut, tr("message système %02X") % statut)
    canal = (statut & 0x0F) + 1
    genre = statut & 0xF0
    if genre == midiport.NOTE_ON and data2 > 0:
        quoi = tr("note %s, force %d") % (note_to_name(data1), data2)
    elif genre in (midiport.NOTE_ON, midiport.NOTE_OFF):
        quoi = tr("note %s relâchée") % note_to_name(data1)
    elif genre == midiport.CONTROL_CHANGE:
        quoi = tr("contrôleur %d = %d") % (data1, data2)
    elif genre == midiport.PROGRAM_CHANGE:
        quoi = tr("programme %d") % (data1 + 1)
    elif genre == midiport.PITCH_BEND:
        quoi = tr("molette %+d") % (((data2 << 7) | data1) - 8192)
    elif genre == midiport.CHANNEL_PRESSURE:
        quoi = tr("pression %d") % data1
    else:
        quoi = tr("pression %s = %d") % (note_to_name(data1), data2)
    return tr("%s (canal %d)") % (quoi, canal)


# --------------------------------------------------------------------------- #
# Les ports
# --------------------------------------------------------------------------- #

class _EntreeDuLien:
    """Le Deluge comme source : un auditeur posé sur le lien."""

    def __init__(self, lien, pousser) -> None:
        self._lien = lien
        lien.set_listener(pousser)

    def close(self) -> None:
        try:
            self._lien.set_listener(None)
        except Exception as exc:       # noqa: BLE001
            log.debug("auditeur du lien non retiré : %s", exc)


class _SortieDuLien:
    """Le Deluge comme destination : le port des notes du lien, qui reste
    à lui — le hub ne le ferme jamais."""

    def __init__(self, lien) -> None:
        self._lien = lien

    def send(self, status: int, data1: int = 0, data2: int = 0) -> bool:
        return self._lien.send_short(status, data1, data2)

    def close(self) -> None:
        return None


class Backend:
    """Les ports de la machine, vus par le hub.

    ``link`` rend le lien avec le Deluge, ou ``None`` : ses ports sont
    retirés de la liste et remplacés par :data:`DELUGE`, présent quand le
    lien est connecté. Les essais remplacent cette classe par des ports
    simulés.
    """

    def __init__(self, link=None) -> None:
        self._link = link if callable(link) else (lambda: link)
        self.last_error = ""

    def _lien(self):
        try:
            return self._link()
        except Exception as exc:       # noqa: BLE001
            log.debug("lien indisponible : %s", exc)
            return None

    def _connecte(self):
        lien = self._lien()
        return lien if lien is not None and lien.is_connected else None

    @staticmethod
    def _du_lien(appareil, pris: set[str]) -> bool:
        return appareil.is_deluge or appareil.name in pris

    def _pris(self, sens: str) -> set[str]:
        lien = self._connecte()
        lire = getattr(lien, "open_ports", None)
        if lire is None:
            return set()
        try:
            return set(lire().get(sens, ()))
        except Exception as exc:       # noqa: BLE001
            log.debug("ports du lien illisibles : %s", exc)
            return set()

    def inputs(self) -> list[str]:
        pris = self._pris("in")
        noms = [d.name for d in midiport.inputs()
                if not self._du_lien(d, pris)]
        lien = self._connecte()
        if lien is not None and getattr(lien, "can_listen", False):
            noms.insert(0, DELUGE)
        return noms

    def outputs(self) -> list[str]:
        pris = self._pris("out")
        noms = [d.name for d in midiport.outputs()
                if not self._du_lien(d, pris)]
        if self._connecte() is not None:
            noms.insert(0, DELUGE)
        return noms

    def deluge_detected(self) -> bool:
        """Vrai si un Deluge est au bout du câble, connecté ou non."""
        return (self._connecte() is not None
                or midiport.find("out") is not None)

    def open_input(self, name: str, push):
        """Ouvre l'entrée ``name`` ; chaque message court va à
        ``push(statut, data1, data2, instant)``. Rend de quoi la fermer,
        ou ``None``."""
        self.last_error = ""
        if name == DELUGE:
            lien = self._connecte()
            if lien is None or not getattr(lien, "can_listen", False):
                return None
            return _EntreeDuLien(lien, push)
        appareil = next((d for d in midiport.inputs() if d.name == name), None)
        if appareil is None:
            return None
        port = midiport.MidiIn(sysex=False)
        if not port.open(appareil):
            self.last_error = port.last_error
            return None

        def robinet(statut, data1, data2, instant) -> bool:
            push(statut, data1, data2, instant)
            return True                  # rien ne s'empile dans le port

        port.set_message_tap(robinet)
        return port

    def open_output(self, name: str):
        """Ouvre la sortie ``name`` ; rend de quoi envoyer et fermer, ou
        ``None``."""
        self.last_error = ""
        if name == DELUGE:
            lien = self._connecte()
            return _SortieDuLien(lien) if lien is not None else None
        appareil = next((d for d in midiport.outputs() if d.name == name),
                        None)
        if appareil is None:
            return None
        # Le hub relâche lui-même ce qu'il a fait passer : la fermeture
        # n'a rien à éteindre de plus.
        port = midiport.MidiOut(reset_on_close=False)
        if not port.open(appareil):
            self.last_error = port.last_error
            return None
        return port


# --------------------------------------------------------------------------- #
# Un branchement en service
# --------------------------------------------------------------------------- #

class _Voie:
    """Un branchement, sa sortie, et ce qu'il a fait passer."""

    __slots__ = ("route", "sink", "channel", "held", "pedals", "bends",
                 "count")

    def __init__(self, route: Route, sink, channel: int) -> None:
        self.route = route
        self.sink = sink
        #: Canal d'arrivée résolu (1..16), 0 : celui d'origine.
        self.channel = channel
        #: (canal, note) reçus -> (canal, note) envoyés.
        self.held: dict[tuple[int, int], tuple[int, int]] = {}
        #: Canaux d'arrivée où la pédale est enfoncée.
        self.pedals: set[int] = set()
        #: Canaux d'arrivée où la molette n'est pas au centre.
        self.bends: set[int] = set()
        self.count = 0

    def handle(self, status: int, data1: int, data2: int) -> bool:
        """Fait passer un message, ou non. Rend ``True`` s'il est parti."""
        route = self.route
        envoi = self.sink.send
        if status >= 0xF0:
            if not route.clock or status not in midiport.TRANSPORT:
                return False
            return bool(envoi(status, data1, data2))
        canal = status & 0x0F
        if route.channel_in and canal != route.channel_in - 1:
            return False
        sortie = self.channel - 1 if self.channel else canal
        genre = status & 0xF0

        if genre == midiport.NOTE_ON and data2 > 0:
            if not route.notes or not route.low <= data1 <= route.high:
                return False
            note = data1 + route.transpose
            if not 0 <= note <= 127:
                return False
            cle = (canal, data1)
            avant = self.held.get(cle)
            if avant is not None and avant != (sortie, note):
                envoi(midiport.NOTE_OFF | avant[0], avant[1], 0)
            self.held[cle] = (sortie, note)
            return bool(envoi(midiport.NOTE_ON | sortie, note, data2))

        if genre in (midiport.NOTE_ON, midiport.NOTE_OFF):
            # Le relâchement part où l'appui est parti — et nulle part si
            # l'appui n'est pas passé.
            cible = self.held.pop((canal, data1), None)
            if cible is None:
                return False
            return bool(envoi(genre | cible[0], cible[1], data2))

        if genre == midiport.CONTROL_CHANGE:
            if not route.controllers:
                return False
            numero = route.cc_map.get(data1, data1)
            if numero == 64:
                if data2 >= 64:
                    self.pedals.add(sortie)
                else:
                    self.pedals.discard(sortie)
            return bool(envoi(genre | sortie, numero, data2))

        if genre == midiport.PROGRAM_CHANGE:
            return bool(route.programs and envoi(genre | sortie, data1, 0))

        if not route.bend:
            return False
        if genre == midiport.POLY_PRESSURE:
            cible = self.held.get((canal, data1))
            if cible is None:
                return False
            return bool(envoi(genre | cible[0], cible[1], data2))
        if genre == midiport.PITCH_BEND:
            if (data1, data2) == (0, 64):
                self.bends.discard(sortie)
            else:
                self.bends.add(sortie)
        return bool(envoi(genre | sortie, data1, data2))

    def release(self) -> int:
        """Relâche ce que le branchement tenait : notes, pédale, molette.
        Rend le nombre de notes relâchées."""
        envoi = self.sink.send
        notes = list(self.held.values())
        self.held.clear()
        for canal, note in notes:
            envoi(midiport.NOTE_OFF | canal, note, 0)
        for canal in sorted(self.pedals):
            envoi(midiport.CONTROL_CHANGE | canal, 64, 0)
        self.pedals.clear()
        for canal in sorted(self.bends):
            envoi(midiport.PITCH_BEND | canal, 0, 64)
        self.bends.clear()
        return len(notes)


class _Fusible:
    """Le débit d'une source, compté par seconde."""

    __slots__ = ("start", "count", "repeats", "tripped")

    def __init__(self) -> None:
        self.start = 0.0
        self.count = 0
        self.repeats: dict[tuple[int, int, int], int] = {}
        self.tripped = False


# --------------------------------------------------------------------------- #
# Ce que la page lit
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Endpoint:
    """Un port, tel que la page le montre."""

    name: str
    label: str
    role: str
    #: Le système le voit en ce moment.
    present: bool
    #: Le hub le tient ouvert.
    open: bool
    #: Messages vus (une entrée) ou envoyés (une sortie) depuis le départ.
    count: int = 0
    #: Sa source est coupée pour emballement.
    tripped: bool = False


@dataclass(frozen=True)
class Event:
    """Un message passé par le hub."""

    seq: int
    at: float
    source: str
    status: int
    data1: int
    data2: int
    #: Nombre de branchements qui l'ont fait passer.
    delivered: int


@dataclass(frozen=True)
class HubStats:
    """Le travail du hub, mesuré."""

    relayed: int = 0
    #: Retard entre l'arrivée d'un message et son départ, en millisecondes.
    median_ms: float | None = None
    worst_ms: float | None = None
    #: Tops d'horloge relayés (ils ne passent pas par le moniteur).
    clock: int = 0

    def summary(self) -> str:
        if not self.relayed or self.median_ms is None:
            return tr("Rien n'est encore passé.")
        return tr("%s — retard médian %s ms, au pire %s ms") % (
            plural(self.relayed, N_("%d message relayé"),
                   N_("%d messages relayés")) % self.relayed,
            decimal(self.median_ms, 2), decimal(self.worst_ms or 0.0, 1))


# --------------------------------------------------------------------------- #
# Le hub
# --------------------------------------------------------------------------- #

class MidiHub:
    """Relie des entrées MIDI à des sorties. Un seul par application."""

    def __init__(self, backend: Backend | None = None) -> None:
        self._backend = backend if backend is not None else Backend()
        self._lock = threading.RLock()
        self._routes: list[Route] = []
        self._enabled = True
        self._queue: "queue.SimpleQueue" = queue.SimpleQueue()
        self._thread: threading.Thread | None = None
        self._ins: dict[str, object] = {}
        self._outs: dict[str, object] = {}
        self._voies: dict[str, _Voie] = {}
        #: Source -> voies en service : ce que lit le fil du hub.
        self._table: dict[str, tuple[_Voie, ...]] = {}
        self._fusibles: dict[str, _Fusible] = {}
        self._follow: midifollow.FollowSettings | None = None
        self._follow_default = 1
        self._present_in: list[str] = []
        self._present_out: list[str] = []
        self._seen: dict[str, int] = {}
        self._sent: dict[str, int] = {}
        self._latences: deque = deque(maxlen=LATENCIES)
        self._relayes = 0
        self._tops = 0
        self._moniteur: deque = deque(maxlen=MONITOR)
        self._seq = 0
        #: Dernier contrôleur vu par source : (numéro, valeur, rang).
        self._dernier_cc: dict[str, tuple[int, int, int]] = {}
        #: Erreurs d'ouverture, par port.
        self._erreurs: dict[str, str] = {}
        #: Vrai une fois :meth:`close` appelé : plus rien ne se rouvre.
        self._closed = False
        #: Vrai tant que ce hub tient la bascule des fils raccourcie
        #: (:data:`SWITCH_INTERVAL`).
        self._presse = False

    # -- configuration ------------------------------------------------------ #

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        """Met le hub en marche, ou l'arrête : à l'arrêt, ses ports sont
        rendus aux autres logiciels."""
        with self._lock:
            self._enabled = bool(enabled)
        self.rescan()

    @property
    def routes(self) -> list[Route]:
        """Les branchements, en copies."""
        with self._lock:
            return [r.clone() for r in self._routes]

    def route(self, uid: str) -> Route | None:
        with self._lock:
            for route in self._routes:
                if route.uid == uid:
                    return route.clone()
        return None

    def find(self, source: str, dest: str) -> Route | None:
        with self._lock:
            for route in self._routes:
                if route.source == source and route.dest == dest:
                    return route.clone()
        return None

    @staticmethod
    def refusal(source: str, dest: str) -> str:
        """Pourquoi ``source`` ne se branche pas sur ``dest`` ; ``""`` si
        rien ne s'y oppose."""
        if not source or not dest:
            return tr("Il manque la source ou la destination.")
        if source == dest:
            return tr("Un appareil ne se branche pas sur lui-même : ce qu'il "
                      "envoie lui reviendrait, en boucle.")
        return ""

    def set_routes(self, routes) -> None:
        """Remplace tous les branchements."""
        gardes, vus = [], set()
        for route in routes or ():
            if not isinstance(route, Route) or route.uid in vus:
                continue
            if self.refusal(route.source, route.dest):
                continue
            vus.add(route.uid)
            gardes.append(route.clone())
        with self._lock:
            self._routes = gardes
        self.rescan()

    def connect(self, source: str, dest: str, **reglages) -> Route:
        """Branche ``source`` sur ``dest`` ; rend le branchement — celui
        qui existait déjà, s'il y en avait un. Lève ``ValueError`` avec la
        raison s'il est refusé."""
        raison = self.refusal(source, dest)
        if raison:
            raise ValueError(raison)
        existant = self.find(source, dest)
        if existant is not None:
            return existant
        route = self._regle(default_route(source, dest), reglages)
        with self._lock:
            self._routes.append(route.clone())
        self.rescan()
        return route

    @staticmethod
    def _regle(route: Route, changes: dict) -> Route:
        """``route`` avec ``changes``, chaque valeur ramenée dans ses
        bornes ; ni son identité ni ses deux bouts ne changent."""
        fiche = route.to_dict()
        for nom, valeur in changes.items():
            if nom in fiche and nom not in ("uid", "source", "dest"):
                fiche[nom] = valeur
        return Route.from_dict(fiche) or route

    def update(self, uid: str, **changes) -> Route | None:
        """Change des réglages d'un branchement. Ce qu'il tenait est
        relâché avant : une note en cours ne reste pas sur l'ancien canal."""
        with self._lock:
            rang = next((i for i, r in enumerate(self._routes)
                         if r.uid == uid), None)
            if rang is None:
                return None
            self._routes[rang] = self._regle(self._routes[rang], changes)
        self.rescan()
        return self.route(uid)

    def remove(self, uid: str) -> bool:
        with self._lock:
            avant = len(self._routes)
            self._routes = [r for r in self._routes if r.uid != uid]
            retire = len(self._routes) != avant
        if retire:
            self.rescan()
        return retire

    def set_follow(self, settings, default_channel: int = 1) -> None:
        """Dit au hub ce que le Deluge écoute en MIDI Follow : les réglages
        lus sur sa carte, et le canal A à défaut (un firmware qui ne les y
        écrit pas)."""
        canal = _entier(default_channel, 1, 1, 16)
        with self._lock:
            if settings == self._follow and canal == self._follow_default:
                return
            self._follow = settings
            self._follow_default = canal
        self.rescan()

    @property
    def follow(self):
        """Les réglages MIDI Follow du Deluge donnés au hub, ou ``None``."""
        return self._follow

    def channel_for(self, route: Route) -> int | None:
        """Le canal d'arrivée d'un branchement : 0 pour « celui d'origine »,
        ``None`` si sa cible MIDI Follow n'est pas réglée sur le Deluge."""
        if not route.follow:
            return int(route.channel_out)
        reglages = self._follow
        canal = reglages.channel_of(route.follow) if reglages else None
        if canal is None and route.follow == "a":
            # Rien de lu sur la carte, ou une copie qui retarde : le canal A
            # des réglages de l'application. Si la machine ne l'écoute pas,
            # elle ignore ce qui arrive — :meth:`advice` le dit.
            return self._follow_default
        return canal

    def advice(self, route: Route) -> str:
        """Ce qu'il reste à régler **sur le Deluge** pour qu'un branchement
        y soit entendu ; ``""`` si rien ne manque à ce qu'on sait."""
        if route.dest != DELUGE or not route.follow:
            return ""
        reglages = self._follow
        connu = reglages.channel_of(route.follow) if reglages else None
        if connu is not None:
            return ""
        if route.follow in ("a", "b", "c"):
            lettre = route.follow.upper()
            if reglages is None:
                return tr(
                    "Sur le Deluge, vérifiez que MIDI ▸ MIDI-Follow ▸ Channel "
                    "▸ Channel %s vaut %d : sans ce réglage, la machine "
                    "ignore ce qu'elle reçoit.") % (
                        lettre, self._follow_default)
            return tr(
                "D'après sa carte, le Deluge n'écoute pas MIDI Follow %s : "
                "réglez MIDI ▸ MIDI-Follow ▸ Channel ▸ Channel %s.") % (
                    lettre, lettre)
        return tr(
            "Le Deluge n'a pas de canal pour la piste %s : réglez MIDI ▸ "
            "MIDI-Follow ▸ Channel ▸ Channel Track %s (firmware 1.3), puis "
            "laissez la carte se synchroniser.") % (
                route.follow[6:], route.follow[6:])

    # -- les ports ---------------------------------------------------------- #

    def rescan(self) -> bool:
        """Accorde les ports ouverts aux branchements et à ce qui est
        branché : ouvre ce qui manque, ferme ce qui ne sert plus ou a
        disparu. À appeler quand la configuration change, et une fois par
        seconde pour suivre les appareils. Rend ``True`` si quelque chose a
        changé."""
        try:
            return self._rescan()
        except Exception:               # noqa: BLE001 - jamais vers l'appelant
            log.exception("hub MIDI : accord des ports en échec")
            return False

    def _rescan(self) -> bool:
        if self._closed:
            return False
        entrees = list(self._backend.inputs())
        sorties = list(self._backend.outputs())
        with self._lock:
            change = (entrees != self._present_in
                      or sorties != self._present_out)
            self._present_in, self._present_out = entrees, sorties
            actifs = [r for r in self._routes if r.enabled] \
                if self._enabled else []
            veut_in = {r.source for r in actifs} & set(entrees)
            veut_out = {r.dest for r in actifs} & set(sorties)

            # Fermer d'abord : ce qui ne sert plus, ce qui a disparu.
            for nom in [n for n in self._ins if n not in veut_in]:
                self._fermer_voies(source=nom)
                self._fermer(self._ins.pop(nom))
                change = True
            for nom in [n for n in self._outs if n not in veut_out]:
                self._fermer_voies(dest=nom)
                self._fermer(self._outs.pop(nom))
                change = True

            for nom in sorted(veut_out - set(self._outs)):
                port = self._backend.open_output(nom)
                if port is None:
                    self._noter_erreur(nom)
                    continue
                self._erreurs.pop(nom, None)
                self._outs[nom] = port
                change = True
            for nom in sorted(veut_in - set(self._ins)):
                port = self._backend.open_input(nom, self._pousseur(nom))
                if port is None:
                    self._noter_erreur(nom)
                    continue
                self._erreurs.pop(nom, None)
                self._ins[nom] = port
                change = True

            change = self._accorder_voies(actifs) or change
            if self._ins and self._thread is None:
                self._demarrer()
            self._cadencer()
        return change

    def _cadencer(self) -> None:
        """Raccourcit la bascule des fils de Python tant qu'une entrée est
        ouverte, et la rend ensuite (:data:`SWITCH_INTERVAL`)."""
        if bool(self._ins) != self._presse:
            self._presse = bool(self._ins)
            _presser(self._presse)

    def _noter_erreur(self, nom: str) -> None:
        erreur = getattr(self._backend, "last_error", "") or ""
        if erreur and self._erreurs.get(nom) != erreur:
            log.warning("hub MIDI : port « %s » refusé : %s", nom, erreur)
        if erreur:
            self._erreurs[nom] = erreur

    @staticmethod
    def _fermer(port) -> None:
        try:
            port.close()
        except Exception as exc:       # noqa: BLE001
            log.debug("hub MIDI : fermeture imparfaite : %s", exc)

    def _pousseur(self, nom: str):
        """Ce que le rappel du pilote appelle : empiler, rien d'autre."""
        empiler = self._queue.put

        def pousser(statut, data1, data2, instant) -> None:
            if statut != _ACTIVE_SENSING:
                empiler((nom, statut, data1, data2, instant))

        return pousser

    def _fermer_voies(self, source: str = "", dest: str = "") -> None:
        for uid, voie in list(self._voies.items()):
            if voie.route.source == source or voie.route.dest == dest:
                self._relacher(voie)
                del self._voies[uid]

    @staticmethod
    def _relacher(voie: _Voie) -> None:
        try:
            voie.release()
        except Exception as exc:       # noqa: BLE001
            log.debug("hub MIDI : relâchement imparfait : %s", exc)

    def _accorder_voies(self, actifs: list[Route]) -> bool:
        """Une voie par branchement en service ; celles dont rien n'a
        changé gardent ce qu'elles tiennent."""
        change = False
        voulues: dict[str, _Voie] = {}
        for route in actifs:
            sortie = self._outs.get(route.dest)
            canal = self.channel_for(route)
            if (sortie is None or route.source not in self._ins
                    or canal is None):
                continue
            voie = self._voies.get(route.uid)
            if (voie is not None and voie.sink is sortie
                    and voie.channel == canal
                    and voie.route.to_dict() == route.to_dict()):
                voulues[route.uid] = voie
                continue
            if voie is not None:
                self._relacher(voie)
            voulues[route.uid] = _Voie(route.clone(), sortie, canal)
            change = True
        for uid, voie in self._voies.items():
            if uid not in voulues:
                self._relacher(voie)
                change = True
        self._voies = voulues
        table: dict[str, list[_Voie]] = {}
        for voie in voulues.values():
            table.setdefault(voie.route.source, []).append(voie)
        self._table = {nom: tuple(voies) for nom, voies in table.items()}
        return change

    # -- le fil ------------------------------------------------------------- #

    def _demarrer(self) -> None:
        self._thread = threading.Thread(target=self._tourner, name="hub-midi",
                                        daemon=True)
        self._thread.start()

    def _tourner(self) -> None:
        prendre = self._queue.get
        while True:
            message = prendre()
            if message is None:
                return
            if isinstance(message, threading.Event):
                message.set()            # :meth:`flush` : tout est passé
                continue
            try:
                self._relayer(*message)
            except Exception:           # noqa: BLE001 - le fil ne meurt pas
                log.exception("hub MIDI : message non relayé")

    def _relayer(self, source: str, status: int, data1: int, data2: int,
                 arrived: float) -> None:
        with self._lock:
            voies = self._table.get(source)
            top = status == midiport.CLOCK
            if not top:
                self._seen[source] = self._seen.get(source, 0) + 1
                if status & 0xF0 == midiport.CONTROL_CHANGE:
                    self._dernier_cc[source] = (data1, data2,
                                                self._seq + 1)
            if self._saute(source, status, data1, data2):
                return
            partis = 0
            for voie in voies or ():
                if voie.handle(status, data1, data2):
                    partis += 1
                    voie.count += 1
                    if not top:
                        dest = voie.route.dest
                        self._sent[dest] = self._sent.get(dest, 0) + 1
            if partis:
                self._relayes += 1
                if arrived:
                    self._latences.append(time.perf_counter() - arrived)
            if top:
                self._tops += partis
                return
            self._seq += 1
            self._moniteur.append(Event(self._seq, time.time(), source,
                                        status, data1, data2, partis))

    def _saute(self, source: str, status: int, data1: int,
               data2: int) -> bool:
        """Compte le débit de la source ; la coupe si elle s'emballe. Rend
        ``True`` si le message ne doit pas passer."""
        fusible = self._fusibles.get(source)
        if fusible is None:
            fusible = self._fusibles[source] = _Fusible()
        if fusible.tripped:
            return True
        maintenant = time.perf_counter()
        if maintenant - fusible.start >= 1.0:
            fusible.start = maintenant
            fusible.count = 0
            fusible.repeats.clear()
        fusible.count += 1
        repetitions = 0
        if status & 0xF0 == midiport.NOTE_ON and data2 > 0:
            cle = (status, data1, data2)
            repetitions = fusible.repeats.get(cle, 0) + 1
            fusible.repeats[cle] = repetitions
        if fusible.count <= RATE_MAX and repetitions <= REPEAT_MAX:
            return False
        fusible.tripped = True
        log.warning("hub MIDI : « %s » s'emballe (%d messages dans la "
                    "seconde) — coupée", source, fusible.count)
        for voie in self._table.get(source, ()):
            self._relacher(voie)
        return True

    def rearm(self, source: str = "") -> None:
        """Rend une source coupée pour emballement — toutes, sans nom."""
        with self._lock:
            for nom, fusible in self._fusibles.items():
                if not source or nom == source:
                    fusible.tripped = False
                    fusible.count = 0
                    fusible.repeats.clear()
                    fusible.start = time.perf_counter()

    def flush(self, timeout: float = 2.0) -> bool:
        """Attend que tout ce qui est arrivé soit relayé (pour les essais).
        Rend ``False`` si le fil n'a pas suivi."""
        if self._thread is None:
            return self._queue.empty()
        fait = threading.Event()
        self._queue.put(fait)
        return fait.wait(timeout)

    # -- gestes ------------------------------------------------------------- #

    def panic(self) -> int:
        """Relâche tout ce que le hub tient, puis demande le silence à
        chaque sortie ouverte, sur les seize canaux. Rend le nombre de notes
        qu'il tenait."""
        notes = 0
        with self._lock:
            for voie in self._voies.values():
                try:
                    notes += voie.release()
                except Exception as exc:   # noqa: BLE001
                    log.debug("hub MIDI : relâchement imparfait : %s", exc)
            for port in self._outs.values():
                for canal in range(16):
                    try:
                        port.send(midiport.CONTROL_CHANGE | canal,
                                  midiport.CC_ALL_NOTES_OFF, 0)
                    except Exception as exc:   # noqa: BLE001
                        log.debug("hub MIDI : silence non demandé : %s", exc)
                        break
        return notes

    def close(self) -> None:
        """Arrête le hub : notes relâchées, ports fermés, fil arrêté."""
        with self._lock:
            self._closed = True
            for voie in self._voies.values():
                self._relacher(voie)
            self._voies = {}
            self._table = {}
            for port in list(self._ins.values()) + list(self._outs.values()):
                self._fermer(port)
            self._ins, self._outs = {}, {}
            self._cadencer()
            fil, self._thread = self._thread, None
        if fil is not None:
            self._queue.put(None)
            fil.join(2.0)
            if fil.is_alive():
                log.warning("hub MIDI : le fil ne s'arrête pas")

    # -- ce que la page lit ------------------------------------------------- #

    def state(self, uid: str) -> str:
        """L'état d'un branchement : ``active``, ``off``, ``hub_off``,
        ``no_source``, ``no_dest``, ``no_channel`` ou ``tripped``."""
        with self._lock:
            route = next((r for r in self._routes if r.uid == uid), None)
            if route is None:
                return ""
            if not self._enabled:
                return "hub_off"
            if not route.enabled:
                return "off"
            fusible = self._fusibles.get(route.source)
            if fusible is not None and fusible.tripped:
                return "tripped"
            if route.source not in self._ins:
                return "no_source"
            if route.dest not in self._outs:
                return "no_dest"
            if self.channel_for(route) is None:
                return "no_channel"
            return "active"

    @staticmethod
    def state_text(code: str) -> str:
        """Un état en clair."""
        return tr(_ETATS[code]) if code in _ETATS else ""

    def port_error(self, name: str) -> str:
        """Pourquoi un port présent ne s'est pas ouvert ; ``""`` sinon."""
        return self._erreurs.get(name, "")

    def _bouts(self, presents: list[str], ouverts: dict, comptes: dict,
               cote: str) -> list[Endpoint]:
        noms = list(presents)
        for route in self._routes:
            nom = getattr(route, cote)
            if nom not in noms:
                noms.append(nom)
        bouts = []
        for nom in noms:
            fusible = self._fusibles.get(nom) if cote == "source" else None
            bouts.append(Endpoint(
                name=nom, label=endpoint_label(nom), role=role_of(nom),
                present=nom in presents, open=nom in ouverts,
                count=comptes.get(nom, 0),
                tripped=bool(fusible is not None and fusible.tripped)))
        return bouts

    def sources(self) -> list[Endpoint]:
        """Les entrées : celles que le système voit, puis celles qu'un
        branchement attend."""
        with self._lock:
            return self._bouts(self._present_in, self._ins, self._seen,
                               "source")

    def destinations(self) -> list[Endpoint]:
        with self._lock:
            return self._bouts(self._present_out, self._outs, self._sent,
                               "dest")

    def deluge_detected(self) -> bool:
        detecter = getattr(self._backend, "deluge_detected", None)
        try:
            return bool(detecter()) if detecter is not None else False
        except Exception as exc:       # noqa: BLE001
            log.debug("hub MIDI : détection du Deluge : %s", exc)
            return False

    def counts(self) -> dict[str, int]:
        """Messages relayés par branchement (identifiant -> nombre)."""
        with self._lock:
            return {uid: voie.count for uid, voie in self._voies.items()}

    def stats(self) -> HubStats:
        with self._lock:
            retards = sorted(self._latences)
            relayes, tops = self._relayes, self._tops
        if not retards:
            return HubStats(relayed=relayes, clock=tops)
        return HubStats(relayed=relayes, clock=tops,
                        median_ms=retards[len(retards) // 2] * 1000.0,
                        worst_ms=retards[-1] * 1000.0)

    def monitor(self, after: int = 0) -> list[Event]:
        """Les messages passés depuis le rang ``after``."""
        with self._lock:
            return [e for e in self._moniteur if e.seq > after]

    def last_controller(self, source: str) -> tuple[int, int, int] | None:
        """Le dernier contrôleur venu de ``source`` : (numéro, valeur,
        rang) — de quoi apprendre un bouton en le tournant."""
        with self._lock:
            return self._dernier_cc.get(source)

    def overview(self) -> tuple[int, int, bool]:
        """Le hub en trois nombres : branchements, branchements en service,
        et si une source est coupée pour emballement."""
        with self._lock:
            coupe = any(f.tripped for f in self._fusibles.values())
            actifs = sum(1 for v in self._voies.values()
                         if not (self._fusibles.get(v.route.source)
                                 and self._fusibles[v.route.source].tripped))
            return len(self._routes), actifs, coupe

    def summary(self) -> str:
        """L'état du hub en une phrase, pour la barre d'état."""
        total, actifs, _coupe = self.overview()
        marche = self._enabled
        if not total:
            return tr("Hub MIDI : aucun branchement.")
        if not marche:
            return tr("Hub MIDI à l'arrêt.")
        return tr("Hub MIDI : %s en service sur %d.") % (
            plural(actifs, N_("%d branchement"), N_("%d branchements"))
            % actifs, total)


# --------------------------------------------------------------------------- #
# Le fichier des branchements
# --------------------------------------------------------------------------- #

def load_config(path) -> tuple[bool, list[Route]]:
    """Lit ``hub.json`` : (hub en marche, branchements). Un fichier absent
    ou abîmé donne un hub en marche et sans branchement."""
    try:
        brut = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return True, []
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        log.warning("branchements du hub illisibles (%s) : %s", path, exc)
        return True, []
    if not isinstance(brut, dict):
        return True, []
    routes, vus = [], set()
    lus = brut.get("routes")
    for element in lus if isinstance(lus, list) else ():
        route = Route.from_dict(element)
        if (route is None or route.uid in vus
                or MidiHub.refusal(route.source, route.dest)):
            continue
        vus.add(route.uid)
        routes.append(route)
    return brut.get("enabled") is not False, routes


def save_config(path, enabled: bool, routes) -> bool:
    """Écrit ``hub.json`` d'un seul geste (fichier temporaire, puis
    remplacement). Rend ``False`` si l'écriture a échoué."""
    cible = Path(path)
    contenu = json.dumps(
        {"version": 1, "enabled": bool(enabled),
         "routes": [r.to_dict() for r in routes]},
        ensure_ascii=False, indent=2)
    temporaire = ""
    try:
        cible.parent.mkdir(parents=True, exist_ok=True)
        fd, temporaire = tempfile.mkstemp(prefix="hub-", suffix=".tmp",
                                          dir=str(cible.parent))
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fichier:
            fichier.write(contenu + "\n")
        os.replace(temporaire, cible)
        temporaire = ""
        return True
    except OSError as exc:
        log.warning("branchements du hub non enregistrés (%s) : %s",
                    cible, exc)
        return False
    finally:
        if temporaire:
            try:
                os.unlink(temporaire)
            except OSError:
                pass
