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
* sur commande du test : horloge, départ, arrêt, retour MIDI Follow, notes ;
* les contrôleurs MIDI Follow reçus, appliqués au son sélectionné selon le
  réglage **Takeover** — Jump, Pickup ou Scale (:class:`Boutons`) ;
* firmware 1.3 et une carte (``carte=dossier``) : les fichiers par USB,
  comme ``storage/smsysex.cpp`` (:class:`CarteUsb`). La 1.2.1 ignore ces
  commandes.

Chaque réponse part sur le **même câble** que la demande, comme
``MIDIDeviceUSB::sendSysex``.

Ce module importe ``delugeapp`` : le module de test qui l'utilise doit avoir
posé son bac à sable **avant** de l'importer.
"""

from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path

from delugeapp.core import delugesysex as sx
from delugeapp.core import midiport
from delugeapp.core.delugefiles import fat_stamp, from_fat
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
        #: Destinataire direct des SysEx (``MidiIn.set_sysex_tap``).
        self.tap = None

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
        machine = self.machine
        if not self.is_open:
            return False
        if machine.salve is not None:
            # La machine perd ce qui arrive pendant qu'elle traite : au-delà
            # de ``salve`` contrôleurs sans qu'elle ait eu à répondre à un
            # SysEx, les suivants sont perdus (mesuré le 22 octobre 2026).
            if machine.en_attente >= machine.salve:
                machine.cc_perdus += 1
                return True
            machine.en_attente += 1
        if int(channel) == machine.canal_follow:
            machine.boutons.recoit(int(cc), int(value))
        return True

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

    def set_sysex_tap(self, tap) -> None:
        self.tap = tap

    def poll(self, limit: int = 512) -> list[MidiMessage]:
        sortie, self.recus = self.recus[:limit], self.recus[limit:]
        return sortie


class Boutons:
    """Les réglages du son sélectionné, et ce que la machine fait d'un
    contrôleur reçu en MIDI Follow selon son réglage **Takeover**.

    Transcription de ``MidiTakeover::calculateKnobPos``
    (``io/midi/midi_takeover.cpp``, firmware 1.3, commit 102cf9f) pour Jump,
    Pickup et Scale. Les positions vont de −64 à +64 ; un contrôleur ``c``
    vaut la position ``c − 64``, sauf 127 qui vaut +64. Seuls les numéros
    présents dans :attr:`position` sont assignés à un réglage.
    """

    def __init__(self, mode: str = "jump") -> None:
        self.mode = mode
        #: Contrôleur -> position du bouton qu'il pilote.
        self.position: dict[int, int] = {}
        #: ``midiFollow.previousKnobPos`` : la dernière valeur reçue.
        self.precedente: dict[int, int] = {}

    @staticmethod
    def _arrondi(x: float) -> int:
        """``std::round`` : la moitié s'éloigne de zéro."""
        return int(math.copysign(math.floor(abs(x) + 0.5), x))

    def recoit(self, cc: int, valeur: int) -> None:
        if cc not in self.position:
            return
        bouton = self.position[cc]
        midi = valeur - 64 if valeur < 127 else 64
        nouveau = bouton
        if self.mode == "jump":
            nouveau = midi
            self.precedente[cc] = nouveau
        else:
            precedente = self.precedente.setdefault(cc, midi)
            if ((precedente <= bouton and midi >= bouton)
                    or (precedente >= bouton and midi <= bouton)):
                nouveau = midi
            elif self.mode == "scale" and midi != precedente:
                x = float(nouveau)
                ecart = midi - precedente
                if ecart > 0:
                    reste = 64 - midi
                    if reste:
                        x = max(x + (64 - bouton) * (ecart / reste), nouveau)
                else:
                    reste = midi + 64
                    if reste:
                        x = min(x + (bouton + 64) * (ecart / reste), nouveau)
                nouveau = max(-64, min(64, self._arrondi(x)))
            self.precedente[cc] = midi
        self.position[cc] = nouveau

    def valeur(self, cc: int) -> int:
        """Ce que la machine renverrait : ``position + 64``, borné à 127
        (``toDataByte``)."""
        return max(0, min(127, self.position[cc] + 64))


class DelugeSimule:
    """La machine : trois câbles dans chaque sens, comme en USB."""

    NOMS_SORTIE = {1: "Deluge", 2: "MIDIOUT2 (Deluge)",
                   3: "MIDIOUT3 (Deluge)"}
    NOMS_ENTREE = {1: "Deluge", 2: "MIDIIN2 (Deluge)", 3: "MIDIIN3 (Deluge)"}

    def __init__(self, version=(1, 2, 1), cables: int = 3,
                 carte: Path | None = None) -> None:
        self.version = version
        #: Les fichiers servis par USB (firmware 1.3 et une carte).
        self.carte_usb = CarteUsb(carte) if carte is not None else None
        #: SysEx reçus trop longs pour la machine (plus de 1 024 octets).
        self.trop_longs: list[int] = []
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
        #: MIDI-Follow ▸ Channel ▸ Channel A, et le son qu'il pilote.
        self.canal_follow = 1
        self.boutons = Boutons()
        #: Contrôleurs que la machine prend d'affilée avant d'en perdre —
        #: 3 sur la vraie, d'une salve ; ``None`` : aucun perdu. Un SysEx
        #: reçu (elle y répond après avoir tout lu) remet le compte à zéro.
        self.salve: int | None = None
        self.en_attente = 0
        self.cc_perdus = 0

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
        self.en_attente = 0
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
        if len(data) > 1024:
            # ``incomingSysexBuffer[1024]`` : la machine abandonne sans répondre.
            self.trop_longs.append(len(data))
            return
        if commande == 0x04:
            # La 1.2.1 ignore la commande ; la 1.3 sert ses fichiers.
            if tuple(self.version) >= (1, 3, 0) and self.carte_usb is not None:
                reponse = self.carte_usb.traite(data)
                if reponse is not None:
                    self._repond(cable, reponse)
            return
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
        if (port is not None and port.is_open and port.tap is not None
                and port.tap(bytes(data), time.perf_counter())):
            return
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

    def retour_midi_follow(self) -> None:
        """Le retour complet du son sélectionné, comme au départ de la
        lecture en vue clip (``playback_handler.cpp``)."""
        for cc in sorted(self.boutons.position):
            self.court(0xB0 | (self.canal_follow - 1), cc,
                       self.boutons.valeur(cc))

    def horloge(self, bpm: float, impulsions: int = 25) -> None:
        """Des impulsions d'horloge au tempo donné, horodatées par le pilote."""
        ecart = 60000.0 / (bpm * 24.0)
        for _ in range(impulsions):
            self.horloge_ms += ecart
            self.court(midiport.CLOCK, stamp=int(round(self.horloge_ms)))


# --------------------------------------------------------------------------- #
# La carte par USB (firmware 1.3, ``storage/smsysex.cpp``)
# --------------------------------------------------------------------------- #

class CarteUsb:
    """Les fichiers de la carte tels que le firmware 1.3 les sert en SysEx.

    Un dossier du disque tient lieu de carte. Les comportements sont ceux du
    code de la machine, y compris les dangereux — c'est ce qui permet de
    prouver que le client ne s'y expose pas :

    * ``open`` en écriture crée **et écrase** (``FA_CREATE_ALWAYS``), et
      fabrique les dossiers manquants ;
    * ``rename`` refuse une destination existante (``FR_EXIST``) ;
    * ``move`` et ``copy`` écrasent la destination ;
    * le bit 7 des noms se perd en route (mesuré : « è » arrive en ``\\n``) ;
    * quatre fichiers ouverts au plus, le plus ancien est refermé d'office.
    """

    def __init__(self, racine: Path) -> None:
        self.racine = Path(racine)
        self.ouverts: dict[int, dict] = {}
        self.fid = 1
        self.horloge = 1
        self.sessions = 0
        #: Chaque commande reçue : ``(nom, objet JSON)``.
        self.commandes: list[tuple[str, dict]] = []

    # -- chemins, insensibles à la casse comme FAT --------------------------- #

    def _vers(self, chemin: str) -> Path:
        courant = self.racine
        for part in [p for p in str(chemin).split("/") if p]:
            trouve = None
            if courant.is_dir():
                for enfant in courant.iterdir():
                    if enfant.name.casefold() == part.casefold():
                        trouve = enfant
                        break
            courant = trouve if trouve is not None else courant / part
        return courant

    # -- réponses ------------------------------------------------------------ #

    @staticmethod
    def _reponse(cmd: int, msg_id: int, objet: dict,
                 donnees: bytes | None = None) -> bytes:
        texte = json.dumps(objet, ensure_ascii=False)
        brut = texte.encode("cp437", errors="replace")
        brut = bytes(b & 0x7F for b in brut)        # le bit 7 se perd
        corps = bytes((0xF0,)) + sx.DELUGE_ID + bytes((cmd, msg_id)) + brut
        if donnees is not None:
            corps += b"\x00" + sx.pack_8bit_to_7bit(donnees)
        return corps + b"\xf7"

    def traite(self, data: bytes) -> bytes | None:
        msg_id = data[6]
        corps = data[7:-1]
        zero = corps.find(b"\x00")
        texte, brut = (corps, b"") if zero < 0 else (corps[:zero],
                                                     corps[zero + 1:])
        objet = json.loads(texte.decode("ascii"))
        nom, args = next(iter(objet.items()))
        self.commandes.append((nom, args))
        methode = getattr(self, "_" + nom, None)
        if methode is None:
            return None
        if nom == "session":
            return self._reponse(0x04, 0, methode(args))
        resultat = methode(args, brut) if nom == "write" else methode(args)
        if isinstance(resultat, tuple):
            return self._reponse(0x05, msg_id, *resultat)
        return self._reponse(0x05, msg_id, resultat)

    # -- commandes ------------------------------------------------------------ #

    def _ping(self, args):
        return {"^ping": {}}

    def _session(self, args):
        self.sessions += 1
        sid = self.sessions
        return {"^session": {"sid": sid, "tag": args.get("tag", ""),
                             "midBase": sid << 3, "midMin": (sid << 3) + 1,
                             "midMax": (sid << 3) + 7}}

    @staticmethod
    def _date(p: Path) -> tuple[int, int]:
        mtime = p.stat().st_mtime
        if mtime <= from_fat(0x21, 0) + 1:
            return 0, 0
        return fat_stamp(mtime)

    def _dir(self, args):
        dossier = self._vers(args.get("path", "/"))
        if not dossier.is_dir():
            return {"^dir": {"list": [], "err": 5}}
        offset = int(args.get("offset", 0))
        lignes = min(25, int(args.get("lines", 20)))
        entrees = sorted(dossier.iterdir(), key=lambda p: p.name.casefold())
        page = []
        for p in entrees[offset:offset + lignes]:
            date, heure = self._date(p)
            page.append({"name": p.name,
                         "size": 0 if p.is_dir() else p.stat().st_size,
                         "date": date, "time": heure,
                         "attr": 0x10 if p.is_dir() else 0x20})
        return {"^dir": {"list": page, "err": 0}}

    def _open(self, args):
        cible = self._vers(args.get("path", ""))
        ecriture = bool(int(args.get("write", 0)))
        if len(self.ouverts) >= 4:                # le plus ancien est refermé
            del self.ouverts[min(self.ouverts,
                                 key=lambda f: self.ouverts[f]["vu"])]
        if ecriture:
            cible.parent.mkdir(parents=True, exist_ok=True)
            cible.write_bytes(b"")                # FA_CREATE_ALWAYS
        elif not cible.is_file():
            return {"^open": {"fid": 0, "size": 0, "err": 4}}
        fid = self.fid
        self.fid += 1
        self.horloge += 1
        self.ouverts[fid] = {"chemin": cible, "vu": self.horloge}
        return {"^open": {"fid": fid, "size": cible.stat().st_size, "err": 0}}

    def _read(self, args):
        fid = int(args.get("fid", 0))
        f = self.ouverts.get(fid)
        addr, taille = int(args.get("addr", 0)), min(1024, int(args.get("size",
                                                                       1024)))
        if f is None:
            return ({"^read": {"fid": fid, "addr": addr, "size": 0,
                               "err": 12}}, b"")
        f["vu"] = self.horloge = self.horloge + 1
        bloc = f["chemin"].read_bytes()[addr:addr + taille]
        return ({"^read": {"fid": fid, "addr": addr, "size": len(bloc),
                           "err": 0}}, bloc)

    def _write(self, args, brut):
        fid = int(args.get("fid", 0))
        f = self.ouverts.get(fid)
        addr, taille = int(args.get("addr", 0)), min(1024, int(args.get("size",
                                                                       1024)))
        donnees = sx.unpack_7bit_to_8bit(brut, taille)[:taille]
        if f is None:
            return {"^write": {"fid": fid, "addr": addr, "size": taille,
                               "err": 12}}
        f["vu"] = self.horloge = self.horloge + 1
        contenu = bytearray(f["chemin"].read_bytes())
        contenu[addr:addr + len(donnees)] = donnees
        f["chemin"].write_bytes(bytes(contenu))
        return {"^write": {"fid": fid, "addr": addr, "size": len(donnees),
                           "err": 0}}

    def _close(self, args):
        fid = int(args.get("fid", 0))
        err = 0 if self.ouverts.pop(fid, None) is not None else 9
        return {"^close": {"fid": fid, "err": err}}

    def _delete(self, args):
        cible = self._vers(args.get("path", ""))
        if not cible.exists():
            return {"^delete": {"err": 4}}
        if cible.is_dir():
            if any(cible.iterdir()):
                return {"^delete": {"err": 7}}
            cible.rmdir()
        else:
            cible.unlink()
        return {"^delete": {"err": 0}}

    def _mkdir(self, args):
        cible = self._vers(args.get("path", ""))
        if cible.exists():
            return {"^mkdir": {"path": args.get("path"), "err": 8}}
        if not cible.parent.is_dir():
            return {"^mkdir": {"path": args.get("path"), "err": 5}}
        cible.mkdir()
        return {"^mkdir": {"path": args.get("path"), "err": 0}}

    def _rename(self, args):
        source, cible = self._vers(args["from"]), self._vers(args["to"])
        reponse = {"from": args["from"], "to": args["to"]}
        if not source.exists():
            return {"^rename": dict(reponse, err=4)}
        if cible.exists():
            return {"^rename": dict(reponse, err=8)}
        source.rename(cible)
        return {"^rename": dict(reponse, err=0)}

    def _utime(self, args):
        cible = self._vers(args.get("path", ""))
        if not cible.exists():
            return {"^utime": {"err": 4}}
        mtime = from_fat(int(args.get("date", 0)), int(args.get("time", 0)))
        os.utime(cible, (mtime, mtime))
        return {"^utime": {"err": 0}}

    def _move(self, args):                        # écrase : jamais à envoyer
        source, cible = self._vers(args["from"]), self._vers(args["to"])
        cible.write_bytes(source.read_bytes())
        source.unlink()
        return {"^move": {"err": 0}}

    def _copy(self, args):                        # écrase : jamais à envoyer
        source, cible = self._vers(args["from"]), self._vers(args["to"])
        cible.write_bytes(source.read_bytes())
        return {"^copy": {"err": 0}}
