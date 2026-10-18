# -*- coding: utf-8 -*-
"""Un Deluge simulé, pour éprouver la liaison sans la machine.

Il se branche à la place des ports d'un :class:`~delugeapp.core.delugelink.DelugeLink`
et répond comme le firmware c1.2.1 le ferait, d'après son code
(``io/midi/midi_engine.cpp``, ``hid/hid_sysex.cpp``) :

* demande d'identité -> réponse universelle portant la version ;
* ping -> pong portant le même octet ;
* demande d'image (modes 0 et 1) -> image complète, brute ou compressée ;
* abonnement à l'écran (modes 2 et 3) -> des **différences** seulement
  (``sendOLEDDataDelta``) : le mode 3 en force une qui couvre tout l'écran
  — jamais une image, mesuré sur la machine —, puis une à chaque
  changement tant que l'abonnement court ;
* sur commande du test : horloge, départ, arrêt, retour MIDI Follow, notes.

Chaque réponse part sur le **même câble** que la demande, comme
``MIDIDeviceUSB::sendSysex``.

Ce module importe ``delugeapp`` : le module de test qui l'utilise doit avoir
posé son bac à sable **avant** de l'importer.
"""

from __future__ import annotations

import time

from delugeapp.core import delugesysex as sx
from delugeapp.core import midiport
from delugeapp.core.midiport import MidiDevice, MidiMessage


class PortSimule:
    """Un port ouvert vers le Deluge simulé (sortie ou entrée)."""

    def __init__(self, machine: "DelugeSimule", cable: int, kind: str) -> None:
        self.machine = machine
        self.cable = cable
        self.kind = kind
        self.device: MidiDevice | None = None
        self.is_open = False
        self.recus: list[MidiMessage] = []
        self.envoyes: list[tuple] = []
        self.last_error = ""

    # -- ouverture -------------------------------------------------------- #

    def open(self, device) -> bool:
        if self.machine.refuse_cable == self.cable:
            self.last_error = midiport.error_text(4)
            return False
        self.device = device
        self.is_open = True
        return True

    def close(self) -> None:
        self.is_open = False
        self.device = None

    # -- sortie ----------------------------------------------------------- #

    def send_sysex(self, data: bytes) -> bool:
        if not self.is_open:
            return False
        self.envoyes.append(("sysex", bytes(data)))
        self.machine.recoit_sysex(self.cable, bytes(data))
        return True

    def control_change(self, cc, value, channel=1) -> bool:
        self.envoyes.append(("cc", int(cc), int(value), int(channel)))
        return self.is_open

    def note_on(self, note, velocity=100, channel=1) -> bool:
        self.envoyes.append(("on", int(note), int(velocity), int(channel)))
        return self.is_open

    def note_off(self, note, channel=1) -> bool:
        self.envoyes.append(("off", int(note), 0, int(channel)))
        return self.is_open

    def realtime(self, status) -> bool:
        self.envoyes.append(("rt", int(status)))
        return self.is_open

    def all_notes_off(self, channel=None) -> None:
        self.envoyes.append(("panic",))

    # -- entrée ----------------------------------------------------------- #

    def poll(self, limit: int = 512) -> list[MidiMessage]:
        sortie, self.recus = self.recus[:limit], self.recus[limit:]
        return sortie


class DelugeSimule:
    """La machine : trois câbles dans chaque sens, comme en USB."""

    NOMS_SORTIE = {1: "Deluge", 2: "MIDIOUT2 (Deluge)",
                   3: "MIDIOUT3 (Deluge)"}
    NOMS_ENTREE = {1: "Deluge", 2: "MIDIIN2 (Deluge)", 3: "MIDIIN3 (Deluge)"}

    def __init__(self, version=(1, 2, 1), cables: int = 3) -> None:
        self.version = version
        self.cables = cables
        self.sorties = {c: PortSimule(self, c, "out")
                        for c in range(1, cables + 1)}
        self.entrees = {c: PortSimule(self, c, "in")
                        for c in range(1, cables + 1)}
        self.ecran = bytearray(sx.OLED_BYTES)
        #: ``oledDeltaImage`` : l'écran tel qu'il est parti la dernière
        #: fois ; ``None`` tant que rien n'est parti.
        self.envoye: bytearray | None = None
        self.abonne_jusqu = 0.0
        self.cable_ecran = 0
        self.demandes: list[bytes] = []
        self.refuse_cable = 0
        self.horloge_ms = 0.0
        #: Faire taire la machine (une machine qui ne répond pas).
        self.muette = False

    # -- ce que voit le système ------------------------------------------- #

    def devices(self, kind: str) -> list[MidiDevice]:
        noms = self.NOMS_SORTIE if kind == "out" else self.NOMS_ENTREE
        decalage = 1 if kind == "out" else 0   # le synthé GS avant, en sortie
        appareils = [MidiDevice(decalage + c - 1, noms[c], kind)
                     for c in range(1, self.cables + 1)]
        if kind == "out":
            appareils.insert(0, MidiDevice(0, "Microsoft GS Wavetable Synth",
                                           "out"))
        return appareils

    def brancher(self, lien) -> None:
        """Remplace les ports du lien par ceux de la machine simulée."""
        lien._out = self.sorties[1]
        lien._in = self.entrees[1]
        lien._sx_out = self.sorties.get(3) or PortSimule(self, 9, "out")
        lien._sx_in = self.entrees.get(3) or PortSimule(self, 9, "in")

    # -- réponses ---------------------------------------------------------- #

    def recoit_sysex(self, cable: int, data: bytes) -> None:
        self.demandes.append(data)
        if self.muette:
            return
        if data == sx.identity_request():
            reponse = bytes((0xF0, 0x7E, 0x7F, 0x06, 0x02)) + sx.DELUGE_ID \
                + bytes((0, 0, 0)) + bytes(self.version) + bytes((0, 0xF7))
            self._repond(cable, reponse)
            return
        if data[:5] != bytes((0xF0,)) + sx.DELUGE_ID:
            return
        commande = data[5]
        if commande == sx.CMD_PING:
            jeton = data[6] if len(data) >= 8 else 0
            self._repond(cable, bytes((0xF0,)) + sx.DELUGE_ID
                         + bytes((0x7F, jeton, 0xF7)))
        elif commande == sx.CMD_HID and data[6] == 0 and data[7] in (2, 3):
            self.abonne_jusqu = time.monotonic() + sx.STREAM_SECONDS
            self.cable_ecran = cable
            self._envoie_difference(force=data[7] == 3)
        elif commande == sx.CMD_HID and data[6] == 0 and data[7] in (0, 1):
            self._envoie_image(cable, rle=data[7] == 1)

    def _repond(self, cable: int, data: bytes) -> None:
        port = self.entrees.get(cable)
        if port is not None and port.is_open:
            port.recus.append(MidiMessage(0xF0, 0, 0,
                                          int(time.monotonic() * 1000), 0,
                                          bytes(data), time.perf_counter()))

    def _envoie_image(self, cable: int, rle: bool = True) -> None:
        entete = bytes((0xF0,)) + sx.DELUGE_ID + bytes((0x02, 0x40,
                                                        1 if rle else 0, 0))
        charge = (sx.pack_8to7_rle(bytes(self.ecran)) if rle
                  else sx.pack_8bit_to_7bit(bytes(self.ecran)))
        self._repond(cable, entete + charge + b"\xf7")

    def _envoie_difference(self, force: bool = False) -> None:
        """``sendOLEDDataDelta`` : de la première à la dernière zone de
        quatre octets changée depuis le dernier envoi, arrondie aux blocs
        de huit — tout l'écran si ``force``."""
        mots = sx.OLED_BYTES // 4
        if force or self.envoye is None:
            premier, dernier = 0, mots - 1
        else:
            changes = [i for i in range(mots)
                       if self.ecran[4 * i:4 * i + 4]
                       != self.envoye[4 * i:4 * i + 4]]
            if not changes:
                return
            premier, dernier = changes[0], changes[-1]
        debut = premier // 2
        blocs = dernier // 2 - debut + 1
        donnees = bytes(self.ecran[8 * debut:8 * (debut + blocs)])
        if self.envoye is None:
            self.envoye = bytearray(sx.OLED_BYTES)
        self.envoye[8 * debut:8 * (debut + blocs)] = donnees
        self._repond(self.cable_ecran,
                     bytes((0xF0,)) + sx.DELUGE_ID
                     + bytes((0x02, 0x40, 0x02, debut, blocs))
                     + sx.pack_8to7_rle(donnees) + b"\xf7")

    def dessine(self, debut_bloc: int, octets: bytes) -> None:
        """Change l'écran ; envoie la différence si quelqu'un est abonné
        (le firmware le fait à chaque rafraîchissement de l'écran)."""
        debut = 8 * debut_bloc
        self.ecran[debut:debut + len(octets)] = octets
        if self.abonne_jusqu >= time.monotonic() and self.cable_ecran:
            self._envoie_difference()

    # -- ce que joue la machine -------------------------------------------- #

    def court(self, status: int, d1: int = 0, d2: int = 0,
              stamp: int = 0) -> None:
        port = self.entrees[1]
        if port.is_open:
            port.recus.append(MidiMessage(status, d1, d2,
                                          int(time.monotonic() * 1000),
                                          int(stamp), b"",
                                          time.perf_counter()))

    def horloge(self, bpm: float, impulsions: int = 25) -> None:
        """Des impulsions d'horloge au tempo donné, horodatées par le pilote."""
        ecart = 60000.0 / (bpm * 24.0)
        for _ in range(impulsions):
            self.horloge_ms += ecart
            self.court(midiport.CLOCK, stamp=int(round(self.horloge_ms)))
