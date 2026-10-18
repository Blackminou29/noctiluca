# -*- coding: utf-8 -*-
"""Le lien avec le Deluge branché : écouter sur la machine, pas à côté.

L'application sait déjà rendre un son approchant (``core/render.py``), mais
elle le dit elle-même : c'est une **approximation**. Quand le Deluge est là,
autant lui demander. Ce module réunit :

* :mod:`delugeapp.core.midiport` — les ports, les messages courts et les
  SysEx ;
* :mod:`delugeapp.core.midifollow` — un preset traduit en contrôleurs, et
  l'inverse ;
* :mod:`delugeapp.core.delugesysex` — identité, ping, écran recopié.

Ce que la machine accepte, et ce qu'elle n'accepte pas
-------------------------------------------------------

**Le Deluge joue l'instrument qui est sélectionné sur lui.** Aucun message
MIDI standard ne permet de lui dire « charge ce preset-ci » : c'est une
limite de la machine, pas un manque de l'application. En mode **MIDI
Follow** (firmware communautaire), les notes et les contrôleurs reçus sur le
canal A agissent sur cet instrument-là, quel qu'il soit. Ce mode est
**éteint** sur une machine neuve : aucun canal n'y est réglé
(``resetMidiFollowSettings``) — c'est le premier réglage à faire.

Dans l'autre sens, la machine envoie d'elle-même :

* son **horloge** (24 impulsions par noire), son départ et son arrêt —
  réglage d'usine (``midiOutClockEnabled``) : l'application en déduit le
  tempo et l'état de lecture ;
* si l'on active le **retour MIDI Follow**, la valeur de **chaque
  paramètre appris** à chaque changement d'instrument, puis à chaque bouton
  tourné (``sendCCWithoutModelStackForMidiFollowFeedback``) : l'application
  lit le son sélectionné ;
* par SysEx, sur demande : sa version, un pong, l'image de son écran.

Tout cela sans rien installer, et sans jamais lever : si rien n'est branché,
chaque méthode rend ``False`` et l'application continue.

Le service
----------

Ce qui arrive de la machine s'accumule dans des files. :meth:`DelugeLink.service`
les vide, met l'état à jour et entretient ce qui doit l'être (abonnement à
l'écran, nouvelle demande d'identité) ; l'interface l'appelle quelques
dizaines de fois par seconde et redessine selon les évènements rendus.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field

from . import delugesysex, midifollow, midiport

log = logging.getLogger(__name__)

__all__ = ["DelugeLink", "LinkState", "NOTE_C3", "SYSEX_CABLE",
           "latency_text", "tempo_from_ticks"]

#: Do central, celui que le Deluge appelle C3 et le MIDI note 60.
NOTE_C3 = 60

#: Au-delà, on refuse d'envoyer : un flot pareil ne vient pas d'un geste
#: d'utilisateur mais d'une boucle qui s'emballe.
MAX_MESSAGES = 256

#: Le port USB que le firmware réserve aux SysEx.
SYSEX_CABLE = 3

#: Une horloge muette depuis plus longtemps est arrêtée.
CLOCK_TIMEOUT = 1.0
#: Impulsions retenues pour estimer le tempo : une noire.
CLOCK_WINDOW = 24
#: Renouvellement de l'abonnement à l'écran, avant ses deux secondes.
SCREEN_REFRESH = 1.0
#: Nouvelle demande d'identité tant que la machine n'a pas répondu.
IDENTITY_RETRY = 2.0
IDENTITY_TRIES = 3


def latency_text(ms: float) -> str:
    """Un aller-retour lisible : « 0,3 ms », « 12 ms ».

    En USB, le Deluge répond en un tiers de milliseconde (mesuré) : arrondi
    à l'unité, cela s'afficherait « 0 ms ».
    """
    ms = max(0.0, float(ms))
    if ms < 10.0:
        return ("%.1f ms" % ms).replace(".", ",")
    return "%.0f ms" % ms


def tempo_from_ticks(stamps) -> float | None:
    """Tempo en BPM d'une suite d'horodatages d'horloge, en millisecondes.

    24 impulsions par noire : ``BPM = 60 000 / (écart moyen × 24)``.
    L'écart moyen se prend entre la première et la dernière impulsion — les
    gigues du transport USB se compensent alors au lieu de s'additionner.
    """
    valeurs = [float(s) for s in stamps or ()]
    if len(valeurs) < 3:
        return None
    duree = valeurs[-1] - valeurs[0]
    if duree <= 0:
        return None
    ecart = duree / (len(valeurs) - 1)
    bpm = 60000.0 / (ecart * 24.0)
    if not 10.0 <= bpm <= 999.0:
        return None
    return bpm


@dataclass
class LinkState:
    """Ce que l'interface a besoin de savoir, en un objet."""

    supported: bool = False          # la machine sait faire du MIDI
    out_name: str = ""               # port de sortie ouvert
    in_name: str = ""                # port d'entrée ouvert
    deluge_out: bool = False         # ce port est bien un Deluge
    deluge_in: bool = False
    ports_out: list[str] = field(default_factory=list)
    ports_in: list[str] = field(default_factory=list)
    follow_count: int = 0            # assignations MIDI Follow connues
    #: Fichier d'où vient la table MIDI Follow ; ``""`` : valeurs d'usine.
    follow_source: str = ""
    sysex_name: str = ""             # port des SysEx (le troisième câble)
    firmware: str = ""               # « c1.2.1 » quand la machine a répondu
    latency_ms: float | None = None  # aller-retour du dernier ping
    tempo: float | None = None       # tempo de la machine, d'après l'horloge
    running: bool = False            # la machine joue
    clock_alive: bool = False        # horloge reçue il y a moins d'une seconde
    screen_on: bool = False          # recopie de l'écran demandée
    screen_frames: int = 0           # images ou différences reçues
    feedback: int = 0                # paramètres reçus en retour MIDI Follow
    error: str = ""                  # dernière erreur d'ouverture, en clair

    @property
    def connected(self) -> bool:
        """Vrai si l'on peut au moins envoyer quelque chose."""
        return bool(self.out_name)

    @property
    def verified(self) -> bool:
        """Vrai si la machine a répondu : identité ou pong reçus."""
        return bool(self.firmware) or self.latency_ms is not None

    def summary(self) -> str:
        """Phrase d'état, prête pour la barre de statut."""
        if not self.supported:
            return "MIDI indisponible sur cette machine."
        if not self.out_name:
            if self.error:
                return "Deluge non connecté : %s." % self.error
            if any("deluge" in n.casefold() for n in self.ports_out):
                return "Deluge détecté, mais pas encore connecté."
            return "Aucun Deluge détecté. Branchez-le en USB."
        qui = "Deluge" if self.deluge_out else self.out_name
        if self.firmware:
            qui += " " + self.firmware
        if self.in_name:
            return "Connecté à %s, dans les deux sens." % qui
        return "Connecté à %s (envoi seulement)." % qui


class DelugeLink:
    """Lien vivant avec la machine. Un seul par application."""

    def __init__(self) -> None:
        self._out = midiport.MidiOut()
        self._in = midiport.MidiIn()
        #: Le troisième câble, réservé aux SysEx, quand le Deluge l'expose.
        self._sx_out = midiport.MidiOut()
        self._sx_in = midiport.MidiIn()
        self._follow: dict[str, int] = {}
        self._reverse: dict[int, str] = {}
        #: Fichier d'où vient la table MIDI Follow ; ``""`` : valeurs
        #: d'usine du firmware.
        self.follow_source = ""
        self._channel = 1
        self._lock = threading.RLock()
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()
        self.last_error = ""
        self._reset_live()

    def _reset_live(self) -> None:
        """Oublie tout ce que la machine a dit : nouvelle connexion."""
        #: Réponse à la demande d'identité (:class:`delugesysex.Identity`).
        self.identity = None
        self._ident_sent = 0.0
        self._ident_tries = 0
        self._ping_token = 0
        self._ping_sent = 0.0
        #: Aller-retour du dernier ping, en millisecondes.
        self.latency_ms: float | None = None
        #: L'écran recopié.
        self.screen = delugesysex.OledScreen()
        self._screen_on = False
        self._screen_sent = 0.0
        #: Afficheur à sept segments, pour un Deluge sans OLED.
        self.segments = b""
        self._ticks: deque = deque(maxlen=CLOCK_WINDOW + 1)
        self._tick_seen = 0.0
        #: Tempo de la machine (BPM), d'après son horloge.
        self.tempo: float | None = None
        #: La machine joue (départ ou reprise reçus, pas encore d'arrêt).
        self.running = False
        #: Valeurs reçues en retour MIDI Follow : clé -> valeur 32 bits.
        self.machine: dict[str, int] = {}
        self.machine_seen = 0.0
        #: Notes tenues sur la machine (ou sur un clavier qui la traverse).
        self.held: set[int] = set()

    # -- état --------------------------------------------------------------- #

    @property
    def channel(self) -> int:
        """Canal MIDI utilisé pour les notes et les contrôleurs (1..16)."""
        return self._channel

    def set_channel(self, channel: int) -> None:
        try:
            c = int(channel)
        except (TypeError, ValueError):
            c = 1
        self._channel = max(1, min(16, c))

    @property
    def is_connected(self) -> bool:
        return self._out.is_open

    @property
    def follow_map(self) -> dict[str, int]:
        return dict(self._follow)

    @property
    def clock_alive(self) -> bool:
        """Vrai si l'horloge de la machine est arrivée récemment."""
        return bool(self._tick_seen
                    and time.monotonic() - self._tick_seen < CLOCK_TIMEOUT)

    @property
    def screen_on(self) -> bool:
        return self._screen_on

    def state(self) -> LinkState:
        """Instantané complet, sans rien ouvrir ni fermer."""
        sorties = midiport.outputs()
        entrees = midiport.inputs()
        sysex = self._sx_out if self._sx_out.is_open else self._out
        return LinkState(
            supported=midiport.available(),
            out_name=self._out.device.name if self._out.device else "",
            in_name=self._in.device.name if self._in.device else "",
            deluge_out=bool(self._out.device and self._out.device.is_deluge),
            deluge_in=bool(self._in.device and self._in.device.is_deluge),
            ports_out=[d.name for d in sorties],
            ports_in=[d.name for d in entrees],
            follow_count=len(self._follow),
            follow_source=self.follow_source,
            sysex_name=sysex.device.name if getattr(sysex, "device", None)
            else "",
            firmware=self.identity.version if self.identity else "",
            latency_ms=self.latency_ms,
            tempo=self.tempo,
            running=self.running,
            clock_alive=self.clock_alive,
            screen_on=self._screen_on,
            screen_frames=self.screen.frames,
            feedback=len(self.machine),
            error=self.last_error,
        )

    # -- connexion ---------------------------------------------------------- #

    def load_follow_map(self, card=None) -> int:
        """Charge la carte MIDI Follow. Rend le nombre d'assignations."""
        try:
            self._follow, self.follow_source = \
                midifollow.load_map_with_source(card)
        except Exception as exc:       # noqa: BLE001
            log.debug("carte MIDI Follow illisible : %s", exc)
            self._follow, self.follow_source = dict(), ""
        self._reverse = midifollow.reverse_map(self._follow)
        return len(self._follow)

    def connect(self, out_name: str = "", in_name: str = "",
                card=None) -> bool:
        """Ouvre les ports. Sans nom, cherche le Deluge tout seul.

        Les notes passent par le **premier** port du Deluge, les SysEx par
        le **troisième** s'il existe : le firmware ne fait rien d'autre de
        celui-ci, et la recopie de l'écran n'y encombre pas les notes.
        L'entrée est facultative : son absence ne fait pas échouer la
        connexion.
        """
        with self._lock:
            self.stop_playing()
            self._close_ports()
            self._reset_live()
            self.last_error = ""
            if not self._follow:
                self.load_follow_map(card)

            sorties = midiport.outputs()
            entrees = midiport.inputs()
            sortie = self._pick(sorties, out_name)
            if sortie is None:
                log.info("aucun port de sortie MIDI à ouvrir")
                return False
            if not self._out.open(sortie):
                self.last_error = getattr(self._out, "last_error", "") or ""
                return False

            entree = self._pick(entrees, in_name)
            if entree is not None and not self._in.open(entree):
                log.info("entrée MIDI %s indisponible : %s", entree.name,
                         getattr(self._in, "last_error", ""))

            if sortie.is_deluge:
                self._open_sysex(sorties, entrees, sortie, entree)
            self.identify()
            self.ping()
            return True

    def _open_sysex(self, sorties, entrees, sortie, entree) -> None:
        """Ouvre le troisième câble du Deluge, s'il existe."""
        sx_out = next((d for d in midiport.deluge_ports("out", sorties)
                       if d.cable == SYSEX_CABLE), None)
        sx_in = next((d for d in midiport.deluge_ports("in", entrees)
                      if d.cable == SYSEX_CABLE), None)
        if sx_out is None or sx_in is None or sx_out.index == sortie.index:
            return
        if entree is not None and sx_in.index == entree.index:
            return
        # Les deux sens ou rien : une demande sur un câble reçoit sa réponse
        # sur le même câble (``MIDIDeviceUSB::sendSysex``).
        if self._sx_out.open(sx_out) and not self._sx_in.open(sx_in):
            self._sx_out.close()

    @staticmethod
    def _pick(appareils: list, nom: str, cable: int = 1):
        """Le port demandé par son nom, sinon celui du Deluge, sinon rien.

        Parmi les ports du Deluge, celui du câble ``cable`` d'abord : c'est
        le premier qui porte les notes et le retour MIDI Follow.
        """
        if nom:
            for appareil in appareils:
                if appareil.name == nom:
                    return appareil
            # Nom enregistré dans les réglages mais appareil débranché :
            # on ne se rabat pas en silence sur un autre, sauf s'il s'agit
            # d'un Deluge — c'est la machine que l'utilisateur vise.
            log.info("port MIDI « %s » introuvable", nom)
        deluges = midiport.deluge_ports("out", list(appareils))
        for appareil in deluges:
            if appareil.cable == cable:
                return appareil
        return deluges[0] if deluges else None

    def _close_ports(self) -> None:
        for port in (self._out, self._in, self._sx_out, self._sx_in):
            try:
                port.close()
            except Exception as exc:   # noqa: BLE001
                log.debug("fermeture d'un port imparfaite : %s", exc)

    def disconnect(self) -> None:
        with self._lock:
            self.stop_playing()
            self._close_ports()
            self._reset_live()

    def close(self) -> None:
        """Alias de :meth:`disconnect`, pour ``AppContext.close``."""
        self.disconnect()

    # -- SysEx -------------------------------------------------------------- #

    def _send_sysex(self, message: bytes) -> bool:
        port = self._sx_out if self._sx_out.is_open else self._out
        envoi = getattr(port, "send_sysex", None)
        if envoi is None or not port.is_open:
            return False
        try:
            return bool(envoi(message))
        except Exception as exc:       # noqa: BLE001
            log.debug("SysEx non envoyé : %s", exc)
            return False

    def identify(self) -> bool:
        """Demande sa version à la machine ; la réponse arrive au service."""
        self._ident_sent = time.monotonic()
        self._ident_tries += 1
        return self._send_sysex(delugesysex.identity_request())

    def ping(self) -> bool:
        """Mesure l'aller-retour ; le résultat arrive au service."""
        self._ping_token = (self._ping_token + 1) & 0x7F
        self._ping_sent = time.perf_counter()
        return self._send_sysex(delugesysex.ping(self._ping_token))

    def hello(self) -> bool:
        """La machine affiche « HELLO SYSEX » : de quoi la reconnaître."""
        return self._send_sysex(delugesysex.popup())

    def set_screen(self, on: bool) -> bool:
        """Recopie de l'écran : on s'abonne, ou on laisse l'abonnement
        expirer (deux secondes, côté machine)."""
        self._screen_on = bool(on)
        if not self._screen_on:
            return True
        self._screen_sent = time.monotonic()
        return self._send_sysex(delugesysex.display_request(
            delugesysex.DISPLAY_STREAM_FORCE))

    # -- service ------------------------------------------------------------ #

    def service(self) -> set[str]:
        """Vide les files, met l'état à jour, entretient les abonnements.

        Rend les évènements survenus : ``identity``, ``ping``, ``screen``,
        ``tempo``, ``transport``, ``params``, ``notes``.
        """
        evenements: set[str] = set()
        if not self.is_connected:
            return evenements
        maintenant = time.monotonic()
        messages = list(self._in.poll())
        if self._sx_in.is_open:
            messages.extend(self._sx_in.poll())
        for message in messages:
            try:
                self._handle(message, maintenant, evenements)
            except Exception as exc:   # noqa: BLE001 - un message ne casse rien
                log.debug("message MIDI ignoré : %s", exc)

        if self._screen_on and maintenant - self._screen_sent >= SCREEN_REFRESH:
            self._screen_sent = maintenant
            self._send_sysex(delugesysex.display_request(
                delugesysex.DISPLAY_STREAM))
        if (self.identity is None and self._ident_tries < IDENTITY_TRIES
                and maintenant - self._ident_sent >= IDENTITY_RETRY):
            self.identify()
        if self.running and self._tick_seen and not self.clock_alive:
            # L'horloge s'est tue : la machine s'est arrêtée sans dire STOP
            # (câble tiré, horloge coupée dans ses réglages). Le dernier
            # tempo connu reste affiché, éteint.
            self.running = False
            evenements.add("transport")
        return evenements

    def _handle(self, message, maintenant: float, evenements: set) -> None:
        if getattr(message, "is_sysex", False):
            self._handle_sysex(message.data, evenements,
                               getattr(message, "arrived", 0.0))
            return
        statut = int(message.status)
        if statut == midiport.CLOCK:
            self._ticks.append(message.stamp or message.millis)
            self._tick_seen = maintenant
            tempo = tempo_from_ticks(self._ticks)
            if tempo is not None and (self.tempo is None
                                      or abs(tempo - self.tempo) >= 0.05):
                self.tempo = tempo
                evenements.add("tempo")
            return
        if statut in (midiport.START, midiport.CONTINUE):
            self.running = True
            if statut == midiport.START:
                self._ticks.clear()
            evenements.add("transport")
            return
        if statut == midiport.STOP:
            self.running = False
            evenements.add("transport")
            return
        genre = message.kind
        if genre == midiport.CONTROL_CHANGE:
            if message.channel != self._channel:
                return
            cle = self._reverse.get(int(message.data1))
            if cle is None:
                return
            self.machine[cle] = midifollow.raw_from_cc(message.data2, cle)
            self.machine_seen = maintenant
            evenements.add("params")
            return
        if genre in (midiport.NOTE_ON, midiport.NOTE_OFF):
            note = int(message.data1) & 0x7F
            if message.is_note_on:
                self.held.add(note)
            else:
                self.held.discard(note)
            evenements.add("notes")

    def _handle_sysex(self, data: bytes, evenements: set,
                      arrivee: float = 0.0) -> None:
        evenement = delugesysex.parse(data)
        if isinstance(evenement, delugesysex.Identity):
            self.identity = evenement
            evenements.add("identity")
            log.info("Deluge identifié : firmware %s", evenement.version)
        elif isinstance(evenement, delugesysex.Pong):
            if evenement.token == self._ping_token and self._ping_sent:
                # L'instant d'arrivée, pas celui du service : la machine
                # répond en 2 à 3 ms, le service ne passe que toutes les
                # 40 ms (mesuré : 41 ms affichées sans cela).
                fin = arrivee if arrivee >= self._ping_sent \
                    else time.perf_counter()
                self.latency_ms = (fin - self._ping_sent) * 1000.0
                self._ping_sent = 0.0
                evenements.add("ping")
        elif isinstance(evenement, (delugesysex.OledFrame,
                                    delugesysex.OledDelta)):
            if self.screen.apply(evenement):
                evenements.add("screen")
        elif isinstance(evenement, delugesysex.SevenSegment):
            self.segments = evenement.digits
            evenements.add("screen")
        elif isinstance(evenement, delugesysex.DebugText):
            log.debug("Deluge : %s", evenement.text.strip())

    def machine_values(self) -> dict[str, int]:
        """Valeurs des paramètres reçus en retour, comme l'écran de la
        machine les montre : 0..50, ou −25..+25 pour un paramètre centré."""
        from .fixedpoint import to_display
        from .model import PARAM_BIPOLAR

        return {cle: to_display(brut, bipolar=cle in PARAM_BIPOLAR)
                for cle, brut in self.machine.items()}

    # -- envoi ------------------------------------------------------------- #

    def send_sound(self, sound, keys: list[str] | None = None) -> int:
        """Envoie les réglages d'un son à l'instrument sélectionné.

        Rend le nombre de contrôleurs réellement envoyés.
        """
        if not self._out.is_open or sound is None:
            return 0
        try:
            messages = midifollow.sound_messages(sound, self._follow, keys)
        except Exception as exc:       # noqa: BLE001
            log.debug("conversion en contrôleurs impossible : %s", exc)
            return 0
        if len(messages) > MAX_MESSAGES:
            log.warning("%d contrôleurs demandés : on s'arrête à %d",
                        len(messages), MAX_MESSAGES)
            messages = messages[:MAX_MESSAGES]
        envoyes = 0
        for cc, valeur in messages:
            if self._out.control_change(cc, valeur, self._channel):
                envoyes += 1
        log.debug("%d contrôleurs envoyés", envoyes)
        return envoyes

    def send_param(self, key: str, raw: int) -> bool:
        """Un seul paramètre : ce qu'il faut quand un bouton tourne."""
        cc = self._follow.get(str(key))
        if cc is None or not self._out.is_open:
            return False
        return self._out.control_change(cc, midifollow.cc_value(raw, key),
                                        self._channel)

    def note_on(self, note: int = NOTE_C3, velocity: int = 100) -> bool:
        return self._out.note_on(note, velocity, self._channel)

    def note_off(self, note: int = NOTE_C3) -> bool:
        return self._out.note_off(note, self._channel)

    def panic(self) -> None:
        """Tout éteindre, sur tous les canaux. Le bouton de secours."""
        self.stop_playing()
        self._out.all_notes_off()

    # -- jeu dans le temps --------------------------------------------------- #

    def play_notes(self, notes, velocity: int = 100, seconds: float = 0.6,
                   gap: float = 0.0, sound=None) -> bool:
        """Joue une note, un accord ou une suite, **sans bloquer**.

        ``notes`` accepte un entier, une liste d'entiers (accord joué
        ensemble) ou une liste de listes (suite d'accords). ``sound``, s'il
        est donné, est envoyé en contrôleurs juste avant.
        """
        suite = _as_steps(notes)
        if not suite or not self._out.is_open:
            return False

        def travail() -> None:
            if sound is not None:
                self.send_sound(sound)
            for accord in suite:
                if self._stop.is_set():
                    break
                for note in accord:
                    self._out.note_on(note, velocity, self._channel)
                _wait(self._stop, seconds)
                for note in accord:
                    self._out.note_off(note, self._channel)
                if gap:
                    _wait(self._stop, gap)

        return self._start(travail)

    def play_pattern(self, pattern, bpm: float = 120.0,
                     row_notes: dict[str, int] | None = None,
                     repeats: int = 1, clock: bool = False,
                     channel: int | None = None) -> bool:
        """Joue un motif de ``core/rhythm.py`` en mesure.

        **Une piste n'est pas une suite de 0 et de 1.** C'est une liste
        éparse de ``Step(pos, velocity, length, probability)`` : j'ai d'abord
        cru le contraire, et le motif sortait deux fois trop vite, les coups
        rangés dans l'ordre de la liste au lieu de leur position. La grille
        se lit dans ``pattern.steps``, ``pattern.ppq`` et
        ``pattern.ticks_per_step`` — mesuré : 16 pas, 24 ppq, 6 ticks par
        pas, soit une double-croche par pas et deux secondes la mesure à
        120 BPM.

        :param row_notes: nom de piste -> note MIDI. À défaut, la table
            General MIDI de ``core/midifile.py``, celle que l'export MIDI
            utilise déjà. **Sur le Deluge, les rangées d'un kit répondent à
            des notes consécutives à partir de 36** (``midiFollowKitRootNote``,
            réglage d'usine) : passer la correspondance du kit chargé donne
            un résultat juste, la table GM n'étant qu'un repli.
        :param clock: envoie aussi l'horloge MIDI pour que la machine suive
            le tempo — 24 impulsions par noire, comme la norme.
        :param channel: canal forcé ; par défaut celui du lien. Les
            percussions General MIDI vivent sur le canal 10.

        La probabilité d'un pas est ignorée, comme le fait déjà
        ``pattern_to_midi`` : on joue ce qui est écrit.
        """
        from .midifile import GM_DRUMS

        pistes = dict(getattr(pattern, "tracks", {}) or {})
        if not pistes or not self._out.is_open:
            return False
        pas_total = int(getattr(pattern, "steps", 0) or 0)
        if pas_total <= 0:
            return False

        ppq = int(getattr(pattern, "ppq", 24) or 24)
        ticks_par_pas = int(getattr(pattern, "ticks_per_step", 6) or 6)
        canal = self._channel if channel is None else int(channel)

        notes = dict(row_notes or {})
        for index, nom in enumerate(pistes):
            notes.setdefault(nom, GM_DRUMS.get(nom, 36 + index))

        tempo = float(bpm) if bpm and bpm > 0 else 120.0
        duree_tick = 60.0 / tempo / ppq
        # L'horloge MIDI bat 24 fois par noire, quel que soit le ppq du motif.
        impulsions_par_pas = max(1, int(round(24 * ticks_par_pas / ppq)))
        duree_impulsion = duree_tick * ticks_par_pas / impulsions_par_pas
        tours = max(1, int(repeats))
        total = pas_total * impulsions_par_pas

        # Agenda, en impulsions d'horloge : ce qui s'allume et ce qui
        # s'éteint. La position d'un pas peut être fractionnaire — c'est
        # ainsi que le swing et les grooves décalent les coups ; la tronquer
        # au pas entier, comme avant, jouait le motif sans son swing.
        debuts: dict[int, list[tuple[int, int]]] = {}
        fins: dict[int, list[int]] = {}
        for nom, pas in pistes.items():
            note = int(notes.get(nom, 36))
            for step in pas:
                position = float(getattr(step, "pos", 0))
                if not 0 <= position < pas_total:
                    continue
                debut = min(total - 1,
                            int(round(position * impulsions_par_pas)))
                vitesse = max(1, min(127, int(
                    getattr(step, "velocity", 100) * 127 // 100)))
                longueur = max(1.0, float(getattr(step, "length", 1)))
                fin = min(total, debut + max(
                    1, int(round(longueur * impulsions_par_pas))))
                debuts.setdefault(debut, []).append((note, vitesse))
                fins.setdefault(fin, []).append(note)

        def travail() -> None:
            if clock:
                self._out.realtime(midiport.START)
            try:
                depart = time.monotonic()
                impulsion = 0
                for _tour in range(tours):
                    for index in range(total):
                        cible = depart + impulsion * duree_impulsion
                        retard = cible - time.monotonic()
                        if retard > 0:
                            _wait(self._stop, retard)
                        if self._stop.is_set():
                            return
                        for note in fins.get(index, ()):
                            self._out.note_off(note, canal)
                        for note, vitesse in debuts.get(index, ()):
                            self._out.note_on(note, vitesse, canal)
                        if clock:
                            self._out.realtime(midiport.CLOCK)
                        impulsion += 1
                    for note in fins.get(total, ()):
                        self._out.note_off(note, canal)
            finally:
                if clock:
                    self._out.realtime(midiport.STOP)
                self._out.all_notes_off(canal)

        return self._start(travail)

    @property
    def is_playing(self) -> bool:
        worker = self._worker
        return bool(worker and worker.is_alive())

    def stop_playing(self, timeout: float = 2.0) -> None:
        """Arrête le jeu en cours et attend que le fil ait fini."""
        self._stop.set()
        worker = self._worker
        if worker is not None and worker.is_alive():
            worker.join(max(0.1, float(timeout)))
            if worker.is_alive():
                log.warning("le fil de jeu MIDI ne s'arrête pas")
        self._worker = None
        self._stop.clear()

    def _start(self, travail) -> bool:
        with self._lock:
            self.stop_playing()
            self._stop.clear()

            def enveloppe() -> None:
                try:
                    travail()
                except Exception:      # noqa: BLE001 - un fil ne doit rien casser
                    log.exception("jeu MIDI interrompu")
                finally:
                    try:
                        self._out.all_notes_off(self._channel)
                    except Exception:  # noqa: BLE001
                        pass

            self._worker = threading.Thread(target=enveloppe,
                                            name="deluge-midi", daemon=True)
            self._worker.start()
            return True

    # -- écoute -------------------------------------------------------------- #

    def poll_input(self, limit: int = 512) -> list:
        """Les messages reçus depuis le dernier appel, **sans** les traiter.

        L'interface passe par :meth:`service`, qui les traite ; cette
        méthode reste pour qui veut les messages bruts.
        """
        return self._in.poll(limit)


def _as_steps(notes) -> list[list[int]]:
    """Normalise une note, un accord ou une suite d'accords."""
    if notes is None:
        return []
    if isinstance(notes, int):
        return [[notes]]
    suite: list[list[int]] = []
    for element in notes:
        if isinstance(element, int):
            suite.append([element])
        else:
            accord = [int(n) for n in element if isinstance(n, (int, float))]
            if accord:
                suite.append(accord)
    return suite


def _wait(stop: threading.Event, seconds: float) -> None:
    """Attend, mais répond tout de suite à une demande d'arrêt."""
    if seconds > 0:
        stop.wait(seconds)
