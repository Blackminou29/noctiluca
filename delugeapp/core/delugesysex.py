# -*- coding: utf-8 -*-
"""SysEx du Deluge : identité, ping, et recopie de l'écran.

Le firmware communautaire répond à quelques messages exclusifs. Ceux du tag
``release_1_2_1`` — celui de la machine de l'utilisateur — sont tous ici,
lus dans son code (``io/midi/midi_engine.cpp``, ``io/midi/sysex.h``,
``hid/hid_sysex.cpp``, ``util/pack.c``) :

* **identité** (message universel ``F0 7E 7F 06 01 F7``) : la machine répond
  avec sa version de firmware — l'application sait enfin à quoi elle parle ;
* **ping** (``F0 00 21 7B 01 00 n F7``) : la machine renvoie un « pong »
  portant le même octet ``n`` — de quoi mesurer l'aller-retour ;
* **popup** : la machine affiche « HELLO SYSEX » — de quoi l'identifier
  d'un geste, sans rien changer à son état ;
* **écran** : l'image de l'OLED (128 × 48 pixels, 768 octets en pages de
  huit lignes), complète ou par différences pendant deux secondes après
  chaque demande.

Ce que ce firmware **ne sait pas** faire par SysEx : lire ou écrire la carte.
Le transfert de fichiers par USB n'existe pas dans c1.2.1 ; écrire un morceau
ou un preset demande toujours la carte dans le lecteur du PC.

Une demande ``F0 00 21 7B 01 02 00 04 F7`` **change le type d'écran de la
machine** (``swapDisplayType``) : elle n'est volontairement pas proposée.

Module pur : ni Windows, ni Qt. Les messages s'y fabriquent et s'y lisent ;
les envoyer est l'affaire de :mod:`delugeapp.core.midiport`.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..i18n import untranslated

__all__ = [
    "DELUGE_ID", "OLED_WIDTH", "OLED_HEIGHT", "OLED_BYTES",
    "DISPLAY_FULL", "DISPLAY_FULL_RLE", "DISPLAY_STREAM",
    "DISPLAY_STREAM_FORCE", "STREAM_SECONDS",
    "identity_request", "ping", "popup", "display_request",
    "seven_segment_request", "parse",
    "Identity", "Pong", "OledFrame", "OledDelta", "SevenSegment",
    "DebugText", "OledScreen",
    "pack_8bit_to_7bit", "unpack_7bit_to_8bit", "pack_8to7_rle",
    "unpack_7to8_rle",
]

#: Identifiant SysEx de Synthstrom, suivi de l'octet de l'appareil.
DELUGE_ID = bytes((0x00, 0x21, 0x7B, 0x01))
_HEADER = bytes((0xF0,)) + DELUGE_ID

#: Commandes (``SysEx::SysexCommands``).
CMD_PING = 0x00
CMD_POPUP = 0x01
CMD_HID = 0x02
CMD_DEBUG = 0x03
CMD_PONG = 0x7F

#: Écran principal : ``oledCurrentImage[OLED_MAIN_HEIGHT_PIXELS >> 3][128]``.
OLED_WIDTH = 128
OLED_HEIGHT = 48
OLED_BYTES = OLED_WIDTH * OLED_HEIGHT // 8          # 768

#: Modes de la demande d'écran (``HIDSysex::requestOLEDDisplay``).
DISPLAY_FULL = 0          # une image, octets bruts
DISPLAY_FULL_RLE = 1      # une image, compressée
DISPLAY_STREAM = 2        # les différences pendant deux secondes
DISPLAY_STREAM_FORCE = 3  # idem, d'abord une différence pleine page
#: Durée d'un abonnement à l'écran (``midiDisplayUntil``) : il faut le
#: renouveler avant qu'il n'expire.
STREAM_SECONDS = 2.0


# --------------------------------------------------------------------------- #
# Messages à envoyer
# --------------------------------------------------------------------------- #

def identity_request() -> bytes:
    """Demande d'identité universelle, adressée à tous (``7F``)."""
    return bytes((0xF0, 0x7E, 0x7F, 0x06, 0x01, 0xF7))


def ping(token: int = 0) -> bytes:
    """Ping : la machine renvoie un pong portant ``token`` (0..127)."""
    return _HEADER + bytes((CMD_PING, int(token) & 0x7F, 0xF7))


def popup() -> bytes:
    """Fait afficher « HELLO SYSEX » par la machine, sans rien changer."""
    return _HEADER + bytes((CMD_POPUP, 0xF7))


def display_request(mode: int = DISPLAY_STREAM_FORCE) -> bytes:
    """Demande l'image de l'écran OLED.

    Le mode 4 (« swap ») change le type d'écran de la machine : il est
    refusé ici, quoi qu'on demande.
    """
    mode = int(mode)
    if mode not in (DISPLAY_FULL, DISPLAY_FULL_RLE, DISPLAY_STREAM,
                    DISPLAY_STREAM_FORCE):
        # Une faute de programmation, pas un message pour l'utilisateur.
        raise ValueError(untranslated("mode d'écran inconnu ou interdit : %r")
                         % mode)
    return _HEADER + bytes((CMD_HID, 0x00, mode, 0xF7))


def seven_segment_request() -> bytes:
    """Demande l'afficheur à sept segments (Deluge sans OLED)."""
    return _HEADER + bytes((CMD_HID, 0x01, 0x00, 0xF7))


# --------------------------------------------------------------------------- #
# Messages reçus
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Identity:
    """Réponse à la demande d'identité."""

    major: int
    minor: int
    patch: int

    @property
    def community(self) -> bool:
        """Firmware communautaire : ses versions sont 1.x, l'officiel 4.x."""
        return self.major < 4

    @property
    def version(self) -> str:
        """Version écrite comme dans les fichiers : ``c1.2.1``, ``4.1.4``."""
        texte = "%d.%d.%d" % (self.major, self.minor, self.patch)
        return ("c" + texte) if self.community else texte


@dataclass(frozen=True)
class Pong:
    """Réponse à un ping : l'octet renvoyé tel quel."""

    token: int


@dataclass(frozen=True)
class OledFrame:
    """Une image complète de l'écran (768 octets)."""

    data: bytes


@dataclass(frozen=True)
class OledDelta:
    """Une partie de l'écran : ``data`` remplace les octets à partir de
    ``8 × start``."""

    start: int
    data: bytes


@dataclass(frozen=True)
class SevenSegment:
    """L'afficheur à sept segments : quatre octets, un par chiffre."""

    digits: bytes


@dataclass(frozen=True)
class DebugText:
    """Un message de débogage du firmware (versions de développement)."""

    text: str


def parse(message: bytes):
    """Lit un SysEx reçu ; ``None`` s'il ne vient pas d'un Deluge.

    Un message abîmé (compression illisible, longueur fausse) rend ``None``
    plutôt que de lever : il vient d'un câble, pas du programme.
    """
    data = bytes(message or b"")
    if len(data) < 5 or data[0] != 0xF0 or data[-1] != 0xF7:
        return None
    # Réponse d'identité : F0 7E 7F 06 02 00 21 7B 01 00 00 00 maj min pat 0 F7
    if data[1] == 0x7E and len(data) >= 17 and data[3] == 0x06 \
            and data[4] == 0x02:
        if data[5:9] != DELUGE_ID:
            return None
        return Identity(data[12], data[13], data[14])
    if data[1:5] != DELUGE_ID or len(data) < 7:
        return None
    commande = data[5]
    if commande == CMD_PONG:
        return Pong(data[6] if len(data) > 7 else 0)
    if commande == CMD_HID and len(data) >= 9:
        return _parse_hid(data)
    if commande == CMD_DEBUG and len(data) >= 9:
        texte = bytes(b & 0x7F for b in data[8:-1])
        return DebugText(texte.decode("ascii", "replace"))
    return None


def _parse_hid(data: bytes):
    genre = data[6]
    if genre == 0x40:                       # écran OLED
        mode = data[7]
        if mode in (0, 1) and len(data) >= 10:
            charge = data[9:-1]
            octets = (unpack_7to8_rle(charge, OLED_BYTES) if mode == 1
                      else unpack_7bit_to_8bit(charge, OLED_BYTES))
            if octets is None or len(octets) != OLED_BYTES:
                return None
            return OledFrame(bytes(octets))
        if mode == 2 and len(data) >= 11:
            debut, blocs = data[8], data[9]
            octets = unpack_7to8_rle(data[10:-1], 8 * blocs)
            if octets is None or len(octets) != 8 * blocs \
                    or 8 * (debut + blocs) > OLED_BYTES:
                return None
            return OledDelta(debut, bytes(octets))
        return None
    if genre == 0x41 and len(data) >= 11:   # sept segments
        octets = unpack_7bit_to_8bit(data[9:-1], 8)
        if not octets:
            return None
        return SevenSegment(bytes(octets[:4]))
    return None


# --------------------------------------------------------------------------- #
# L'écran
# --------------------------------------------------------------------------- #

class OledScreen:
    """L'image de l'écran de la machine, tenue à jour message après message.

    Format du firmware : six pages de huit lignes, 128 octets par page ; le
    bit 0 d'un octet est le pixel du **haut** de sa colonne
    (``oledCurrentImage[y >> 3][x] |= 1 << (y & 7)``).
    """

    def __init__(self) -> None:
        self.pixels = bytearray(OLED_BYTES)
        #: Nombre d'images ou de différences appliquées.
        self.frames = 0
        #: Vrai dès que tout l'écran est arrivé — une image, ou une
        #: différence qui le couvre en entier : avant, les différences
        #: s'appliquent à un écran noir.
        self.complete = False

    def apply(self, event) -> bool:
        """Applique une image ou une différence ; ``False`` sinon."""
        if isinstance(event, OledFrame) and len(event.data) == OLED_BYTES:
            self.pixels[:] = event.data
            self.complete = True
        elif isinstance(event, OledDelta):
            debut = 8 * int(event.start)
            fin = debut + len(event.data)
            if debut < 0 or fin > OLED_BYTES:
                return False
            self.pixels[debut:fin] = event.data
            # L'abonnement forcé (mode 3) ne répond pas par une image mais
            # par une différence pleine page (``sendOLEDDataDelta``, mesuré
            # sur la machine) : c'est l'écran entier.
            if debut == 0 and fin == OLED_BYTES:
                self.complete = True
        else:
            return False
        self.frames += 1
        return True

    def clear(self) -> None:
        self.pixels[:] = bytes(OLED_BYTES)
        self.frames = 0
        self.complete = False

    def pixel(self, x: int, y: int) -> bool:
        """Vrai si le pixel ``(x, y)`` est allumé (``y`` vers le bas)."""
        if not (0 <= x < OLED_WIDTH and 0 <= y < OLED_HEIGHT):
            return False
        return bool(self.pixels[(y >> 3) * OLED_WIDTH + x] >> (y & 7) & 1)

    def lit_count(self) -> int:
        """Nombre de pixels allumés."""
        return sum(bin(octet).count("1") for octet in self.pixels)

    def text(self, on: str = "#", off: str = ".") -> str:
        """L'écran en caractères, une ligne par rangée de pixels."""
        return "\n".join(
            "".join(on if self.pixel(x, y) else off
                    for x in range(OLED_WIDTH))
            for y in range(OLED_HEIGHT))


# --------------------------------------------------------------------------- #
# Codage 7 bits — portage exact de util/pack.c
# --------------------------------------------------------------------------- #

def pack_8bit_to_7bit(src: bytes) -> bytes:
    """Le codage « Packed Data Format » de Sequential : 7 octets -> 8."""
    src = bytes(src)
    paquets = (len(src) + 6) // 7
    sortie = bytearray()
    for i in range(paquets):
        bloc = src[7 * i:7 * i + 7]
        hauts = 0
        for j, octet in enumerate(bloc):
            if octet & 0x80:
                hauts |= 1 << j
        sortie.append(hauts)
        sortie.extend(octet & 0x7F for octet in bloc)
    return bytes(sortie)


def unpack_7bit_to_8bit(src: bytes, limit: int | None = None
                        ) -> bytes | None:
    """Inverse de :func:`pack_8bit_to_7bit` ; ``None`` si trop long."""
    src = bytes(src)
    paquets = (len(src) + 7) // 8
    manquants = 8 * paquets - len(src)
    if manquants == 7:              # un octet de poids seul : « bizarre »
        paquets -= 1
        manquants = 0
    longueur = 7 * paquets - manquants
    if limit is not None and longueur > limit:
        return None
    sortie = bytearray()
    for i in range(paquets):
        hauts = src[8 * i]
        for j in range(7):
            position = 8 * i + 1 + j
            if position >= len(src):
                break
            octet = src[position] & 0x7F
            if hauts & (1 << j):
                octet |= 0x80
            sortie.append(octet)
    return bytes(sortie)


_MAX_DENSE = 5
_MAX_REP = 31 + 127
_DENSE_OFFSET = {2: 0, 3: 4, 4: 12, 5: 28}


def pack_8to7_rle(src: bytes) -> bytes:
    """Compression du firmware pour l'écran (``pack_8to7_rle``).

    Ses séquences : un « dense » de 2 à 5 octets (``premier`` < 64 porte les
    bits de poids fort) ou une répétition (``premier`` = 64 + 2 × longueur +
    bit de poids fort, prolongée d'un octet au-delà de 30).
    """
    src = bytes(src)
    d = bytearray()
    s = 0
    i = 0
    n = len(src)
    while s < n:
        k = s
        val = src[s]
        s += 1
        while s < n and (s - k) < _MAX_REP:
            if src[s] != val:
                break
            s += 1
        dense = k - i
        rep = s - k
        if rep < 2:
            dense += rep
            rep = 0
            if dense < _MAX_DENSE and s < n:
                continue
        if dense > 0:
            if dense == 1:
                d.append(64 + (1 << 1) + (1 if src[i] & 0x80 else 0))
                d.append(src[i] & 0x7F)
            else:
                hauts = 0
                for j in range(dense):
                    if src[i + j] & 0x80:
                        hauts |= 1 << j
                d.append(_DENSE_OFFSET[dense] + hauts)
                d.extend(src[i + j] & 0x7F for j in range(dense))
        if rep > 0:
            premier = 64 + (1 if val & 0x80 else 0)
            if rep < 31:
                d.append(premier + (rep << 1))
            else:
                d.append(premier + (31 << 1))
                d.append(rep - 31)
            d.append(val & 0x7F)
        i = s
    return bytes(d)


def unpack_7to8_rle(src: bytes, limit: int | None = None) -> bytes | None:
    """Décompression (``unpack_7to8_rle``) ; ``None`` si le flux est abîmé."""
    src = bytes(src)
    d = bytearray()
    s = 0
    n = len(src)
    while s + 1 < n:
        premier = src[s]
        s += 1
        if premier < 64:
            if premier < 4:
                taille, decalage = 2, 0
            elif premier < 12:
                taille, decalage = 3, 4
            elif premier < 28:
                taille, decalage = 4, 12
            elif premier < 60:
                taille, decalage = 5, 28
            else:
                return None
            if taille > n - s:
                return None
            if limit is not None and len(d) + taille > limit:
                return None
            hauts = premier - decalage
            for j in range(taille):
                octet = src[s + j] & 0x7F
                if hauts & (1 << j):
                    octet |= 0x80
                d.append(octet)
            s += taille
        else:
            premier -= 64
            haut = premier & 1
            repetitions = premier >> 1
            if repetitions == 31:
                repetitions = 31 + src[s]
                s += 1
                if s == n:
                    return None
            octet = src[s] + 128 * haut
            s += 1
            if limit is not None and len(d) + repetitions > limit:
                return None
            d.extend(bytes((octet & 0xFF,)) * repetitions)
    return bytes(d)
