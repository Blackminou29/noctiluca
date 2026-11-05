# -*- coding: utf-8 -*-
"""La carte du Deluge, par USB : lire et écrire ses fichiers sans la sortir.

Le firmware communautaire **1.3** ajoute un accès aux fichiers par SysEx
(``storage/smsysex.cpp``) : la carte reste dans la machine, le PC la lit et
l'écrit par le câble USB. Le firmware 1.2.1 ne le fait pas — sa carte ne
s'ouvre alors que glissée dans un lecteur du PC. :meth:`DelugeFiles.probe`
le dit sans rien risquer : la 1.2.1 ignore la commande.

Le protocole, lu dans le code de la machine
-------------------------------------------

* requête : ``F0 00 21 7B 01 04 <msgId> <JSON> F7`` ; pour une écriture, le
  JSON est suivi d'un ``00`` et des données en 7 bits (``util/pack.c``) ;
* réponse : ``F0 00 21 7B 01 05 <msgId> <JSON> [00 <données>] F7`` — sauf la
  réponse à ``session``, qui part en ``04`` avec le numéro 0 ;
* commandes : ``ping``, ``session``, ``dir`` (25 entrées par page),
  ``open``, ``read`` et ``write`` (1 024 octets au plus par bloc),
  ``close``, ``delete``, ``mkdir``, ``rename``, ``utime`` ; quatre fichiers
  ouverts au plus, le plus ancien est refermé d'office ;
* le JSON de la machine **n'échappe rien**, et ses noms sont en page de code
  437 (``FF_LFN_UNICODE 0``, ``FF_CODE_PAGE 437``) — dont le bit 7 se perd
  en route : un nom accentué revient déformé ;
* **la machine n'a pas d'horloge** : ce qu'elle enregistre porte la date
  nulle (mesuré : ``Calm Down.XML`` et les quatre ``Cool1``, réenregistrés
  sur elle). Une date posée par l'application qui retombe à zéro veut donc
  dire « réécrit par le Deluge ».

Mesuré sur la machine (firmware 1.3.0, 18 octobre 2026) : ping en 1 ms,
une page de dossier en 5 à 17 ms, lecture à 113-129 Ko/s une requête à la
fois et 156 à 159 Ko/s avec deux d'avance, écriture à 61 Ko/s avec deux
blocs en vol (48 un à un), contenu identique octet pour octet à la
sauvegarde. Cinq gigaoctets ne se
transfèrent donc pas : seules les différences voyagent.

Ce que ce module s'interdit
---------------------------

La carte contient des mois de travail ; le firmware, lui, n'a pas de filet :

* ``open`` en écriture **écrase** toujours (``FA_CREATE_ALWAYS``) : on
  n'ouvre jamais en écriture qu'un nom temporaire neuf, puis on le renomme ;
* ``rename`` refuse une destination existante (``FR_EXIST``) — c'est le
  seul déplacement employé. ``move`` et ``copy``, eux, **écrasent** la
  destination quand le renommage échoue : ils ne sont jamais envoyés ;
* un nom non ASCII ne peut pas voyager dans un SysEx (octets de données
  < 0x80) : il est refusé à l'aller, et signalé s'il en revient.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from . import delugesysex
from ..i18n import N_, tr

log = logging.getLogger(__name__)

__all__ = ["BLOCK", "CardEntry", "DelugeFiles", "FileError", "NOT_CONNECTED",
           "READ_RATE", "STOPPED", "WRITE_RATE", "cable_time", "fat_stamp",
           "from_fat", "result_text"]

#: Commande des requêtes, et des réponses.
JSON_REQUEST = 0x04
JSON_REPLY = 0x05
#: Taille d'un bloc lu (``blockBufferMax``).
BLOCK = 1024
#: Longueur maximale d'un SysEx **reçu** par la machine, en-tête et ``F7``
#: compris (``incomingSysexBuffer[1024]``) : au-delà, elle l'abandonne sans
#: répondre. Mesuré : un bloc d'écriture de 1 024 octets, une fois codé en
#: 7 bits, en faisait 1 230 — et restait sans réponse.
MAX_INCOMING = 1024
#: Entrées par page de dossier (``MAX_DIR_LINES``).
DIR_LINES = 25
#: Chemin le plus long que la machine accepte (``createPathDirectories``).
MAX_PATH = 256
#: Attente d'une réponse. La machine traite les fichiers dans sa boucle
#: principale, et attend que la carte soit libre : en pleine lecture d'un
#: morceau, cela peut prendre un moment.
TIMEOUT = 5.0
#: Attribut « dossier » de FatFs (``AM_DIR``).
AM_DIR = 0x10

#: Débits mesurés sur la machine de l'utilisateur (firmware 1.3, câble USB,
#: 18 octobre 2026). Lecture avec deux requêtes d'avance : 156 à 159 Ko/s,
#: contre 126 à 129 une à la fois. Écriture : 45 Ko/s — un SysEx de
#: 1 000 octets met à lui seul 11 ms à passer du PC à la machine.
READ_RATE = 155 * 1024
#: Avec deux blocs en vol (:data:`WRITE_AHEAD`) : 61 à 63 Ko/s mesurés le
#: 22 octobre 2026, 48 à 50 un à la fois.
WRITE_RATE = 60 * 1024
#: Requêtes de lecture gardées en vol. Pas plus de deux : la machine jette
#: **en silence** ce qui dépasse 1 024 paquets USB en attente d'envoi
#: (``ConnectedUSBMIDIDevice::bufferMessage``), et une réponse de 1 024
#: octets en occupe environ 410.
READ_AHEAD = 2
#: Blocs d'écriture gardés en vol : deux gagnent un quart, trois rien de
#: plus (mesuré, voir :meth:`DelugeFiles._write_blocks`).
WRITE_AHEAD = 2

#: Codes propres au client, à côté des ``FRESULT`` de la machine.
STOPPED = -2           # transfert interrompu à la demande
NOT_CONNECTED = -3     # plus de port : le câble est débranché

#: Codes ``FRESULT`` de FatFs, en clair (``fatfs/ff.h``).
_RESULTATS = {
    0: N_("réussi"),
    1: N_("erreur matérielle de la carte"),
    2: N_("erreur interne du système de fichiers"),
    3: N_("carte non prête"),
    4: N_("fichier introuvable"),
    5: N_("dossier introuvable"),
    6: N_("nom invalide"),
    7: N_("accès refusé ou dossier plein"),
    8: N_("existe déjà"),
    9: N_("fichier non ouvert"),
    10: N_("carte protégée en écriture"),
    11: N_("lecteur invalide"),
    12: N_("fichier non ouvert sur la machine"),
    13: N_("aucun système de fichiers FAT"),
    14: N_("formatage interrompu"),
    15: N_("délai dépassé"),
    16: N_("fichier verrouillé"),
    17: N_("mémoire insuffisante"),
    18: N_("trop de fichiers ouverts"),
    19: N_("paramètre invalide"),
}
FR_OK, FR_NO_FILE, FR_NO_PATH, FR_EXIST = 0, 4, 5, 8


def result_text(code: int) -> str:
    """Un code ``FRESULT`` en clair, dans la langue de l'interface."""
    texte = _RESULTATS.get(int(code))
    return tr(texte) if texte else tr("erreur %d") % int(code)


def cable_time(read_bytes: int = 0, write_bytes: int = 0) -> str:
    """Durée d'un transfert par le câble, en clair : « environ 7 min »."""
    secondes = (max(0, int(read_bytes)) / READ_RATE
                + max(0, int(write_bytes)) / WRITE_RATE)
    if secondes < 10:
        return tr("quelques secondes")
    if secondes < 90:
        return tr("environ %d s") % round(secondes, -1)
    if secondes < 3600:
        return tr("environ %d min") % max(2, round(secondes / 60))
    heures, minutes = divmod(int(round(secondes / 60)), 60)
    return tr("environ %d h %02d") % (heures, minutes)


class FileError(OSError):
    """Une opération refusée par la machine, ou restée sans réponse."""

    def __init__(self, message: str, code: int = -1, path: str = "") -> None:
        super().__init__(message)
        self.code = int(code)
        self.path = path


# --------------------------------------------------------------------------- #
# Dates FAT
# --------------------------------------------------------------------------- #

def fat_stamp(epoch: float) -> tuple[int, int]:
    """``(date, heure)`` au format FAT, en heure **locale** comme la carte.

    Deux secondes de résolution ; avant 1980, la date de 1980.
    """
    t = datetime.fromtimestamp(float(epoch))
    if t.year < 1980:
        t = datetime(1980, 1, 1)
    date = ((t.year - 1980) << 9) | (t.month << 5) | t.day
    heure = (t.hour << 11) | (t.minute << 5) | (t.second // 2)
    return date, heure


def from_fat(date: int, heure: int) -> float:
    """Instant (secondes depuis 1970) d'une date FAT, lue en heure locale."""
    try:
        t = datetime(1980 + ((date >> 9) & 0x7F), max(1, (date >> 5) & 0x0F),
                     max(1, date & 0x1F), (heure >> 11) & 0x1F,
                     (heure >> 5) & 0x3F, min(59, (heure & 0x1F) * 2))
        return t.timestamp()
    except (ValueError, OverflowError, OSError):
        return 0.0


@dataclass(frozen=True)
class CardEntry:
    """Une entrée de dossier, telle que la machine la décrit."""

    name: str
    size: int = 0
    date: int = 0
    time: int = 0
    attr: int = 0

    @property
    def is_dir(self) -> bool:
        return bool(self.attr & AM_DIR)

    @property
    def stamp(self) -> int:
        """Date et heure FAT en un seul entier, pour comparer."""
        return ((int(self.date) & 0xFFFF) << 16) | (int(self.time) & 0xFFFF)

    @property
    def mtime(self) -> float:
        return from_fat(self.date, self.time)

    @property
    def addressable(self) -> bool:
        """Faux si le nom ne peut pas voyager dans un SysEx."""
        return _ascii(self.name)


def _ascii(texte: str) -> bool:
    return all(32 <= ord(c) < 127 for c in texte)


def _join(dossier: str, nom: str) -> str:
    return dossier.rstrip("/") + "/" + nom


def _parent(chemin: str) -> tuple[str, str]:
    chemin = "/" + chemin.strip("/")
    dossier, _, nom = chemin.rpartition("/")
    return dossier or "/", nom


# --------------------------------------------------------------------------- #
# Le client
# --------------------------------------------------------------------------- #

class DelugeFiles:
    """Les fichiers de la carte, par le câble USB.

    :param send: envoie un SysEx complet ; rend ``False`` s'il n'est pas
        parti (``DelugeLink._send_sysex``).

    Les réponses arrivent par :meth:`feed`, que le lien appelle depuis le
    fil du pilote MIDI pour chaque SysEx JSON reçu — sans attendre la
    cadence de son service. Une seule requête à la fois : la machine les
    traite dans l'ordre, et une réponse se reconnaît à son numéro.
    """

    def __init__(self, send: Callable[[bytes], bool],
                 timeout: float = TIMEOUT) -> None:
        self._send = send
        self._timeout = float(timeout)
        self._replies: "queue.Queue[tuple[bytes, float]]" = queue.Queue()
        self._lock = threading.RLock()
        self._ids = list(range(1, 8))
        self._next = 0
        self._session = 0
        #: ``True``, ``False``, ou ``None`` tant qu'on n'a pas demandé.
        self.supported: bool | None = None
        #: Aller-retour du dernier ping, en millisecondes.
        self.latency_ms: float | None = None
        #: Noms vus sur la carte qu'on ne peut pas atteindre (non ASCII).
        self.unreachable: list[str] = []
        #: Consulté entre deux blocs : vrai, le transfert s'arrête
        #: (:data:`STOPPED`). Un fichier de 8 Mo met trois minutes à monter :
        #: attendre sa fin pour s'arrêter, c'est jouer sur le Deluge pendant
        #: qu'on écrit sur sa carte, ou fermer l'application sur un fil
        #: qu'il faudrait tuer.
        self.stop_check: Callable[[], bool] | None = None

    # -- réception ------------------------------------------------------- #

    @staticmethod
    def is_reply(data: bytes) -> bool:
        """Vrai pour un SysEx de fichiers (requête ou réponse JSON)."""
        return (len(data) >= 8 and data[0] == 0xF0
                and data[1:5] == delugesysex.DELUGE_ID
                and data[5] in (JSON_REQUEST, JSON_REPLY))

    def feed(self, data: bytes, arrived: float = 0.0) -> bool:
        """Remet une réponse au client. Rend ``True`` si elle était pour lui."""
        if not self.is_reply(bytes(data)):
            return False
        self._replies.put((bytes(data), float(arrived or time.perf_counter())))
        return True

    # -- requêtes --------------------------------------------------------- #

    def _msg_id(self) -> int:
        self._next = (self._next + 1) % len(self._ids)
        return self._ids[self._next]

    @staticmethod
    def _compose(commande: dict, msg_id: int,
                 payload: bytes | None = None) -> bytes:
        texte = json.dumps(commande, ensure_ascii=True,
                           separators=(",", ":")).encode("ascii")
        corps = bytes((0xF0,)) + delugesysex.DELUGE_ID \
            + bytes((JSON_REQUEST, msg_id)) + texte
        if payload is not None:
            corps += b"\x00" + delugesysex.pack_8bit_to_7bit(payload)
        return corps + b"\xf7"

    def _emit(self, corps: bytes) -> None:
        if not self._send(corps):
            raise FileError(tr("le Deluge n'est pas connecté"),
                            code=NOT_CONNECTED)

    def _check_stop(self, chemin: str = "") -> None:
        """Lève :data:`STOPPED` si l'on a demandé l'arrêt."""
        arret = self.stop_check
        if arret is not None and arret():
            raise FileError(tr("transfert interrompu"), code=STOPPED, path=chemin)

    def request(self, commande: dict, payload: bytes | None = None,
                timeout: float | None = None) -> tuple[dict, bytes]:
        """Envoie une commande, attend sa réponse : ``(objet, données)``.

        ``données`` est déjà décodé du 7 bits. Lève :class:`FileError` sans
        réponse dans le délai.
        """
        with self._lock:
            session = "session" in commande
            msg_id = 0 if session else self._msg_id()
            corps = self._compose(commande, msg_id, payload)
            self._vider()
            depart = time.perf_counter()
            self._emit(corps)
            limite = time.monotonic() + (self._timeout if timeout is None
                                         else float(timeout))
            while True:
                reste = limite - time.monotonic()
                if reste <= 0:
                    raise FileError(tr("le Deluge n'a pas répondu à « %s »")
                                    % next(iter(commande)), code=15)
                try:
                    data, arrivee = self._replies.get(timeout=reste)
                except queue.Empty:
                    continue
                attendu = JSON_REQUEST if session else JSON_REPLY
                if data[5] != attendu or data[6] != msg_id:
                    log.debug("réponse de fichiers ignorée (%02x, %d)",
                              data[5], data[6])
                    continue
                objet, donnees = self._decode(data)
                self.latency_ms = (arrivee - depart) * 1000.0
                return objet, donnees

    def _vider(self) -> None:
        while True:
            try:
                self._replies.get_nowait()
            except queue.Empty:
                return

    @staticmethod
    def _decode(data: bytes) -> tuple[dict, bytes]:
        corps = bytes(data[7:-1]) if data[-1:] == b"\xf7" else bytes(data[7:])
        zero = corps.find(b"\x00")
        texte, brut = (corps, b"") if zero < 0 else (corps[:zero],
                                                     corps[zero + 1:])
        try:
            # Les noms de la machine sont en page de code 437, mais leur bit 7
            # se perd en route (mesuré : le « è » de « dièse », 0x8A, arrive
            # en 0x0A, un saut de ligne). Lecture tolérante : le nom abîmé
            # est gardé tel quel, et :attr:`CardEntry.addressable` l'écarte.
            objet = json.loads(texte.decode("cp437"), strict=False)
        except (ValueError, UnicodeDecodeError) as exc:
            raise FileError(tr("réponse illisible du Deluge : %s") % exc) from exc
        if not isinstance(objet, dict):
            raise FileError(tr("réponse inattendue du Deluge"))
        return objet, delugesysex.unpack_7bit_to_8bit(brut) if brut else b""

    @staticmethod
    def _part(objet: dict, cle: str) -> dict:
        partie = objet.get(cle)
        if not isinstance(partie, dict):
            raise FileError(tr("réponse sans « %s »") % cle)
        return partie

    def _check(self, partie: dict, quoi: str, chemin: str = "") -> None:
        code = int(partie.get("err", 0) or 0)
        if code:
            raise FileError("%s%s : %s" % (quoi, " " + chemin if chemin else "",
                                           result_text(code)),
                            code=code, path=chemin)

    @staticmethod
    def _path(chemin: str) -> str:
        """Chemin absolu de la carte, vérifié avant de partir."""
        propre = "/" + str(chemin or "").replace("\\", "/").strip("/")
        if not _ascii(propre):
            raise FileError(tr("nom non ASCII, impossible à transmettre en "
                               "SysEx : %s") % propre, code=6, path=propre)
        if len(propre) > MAX_PATH:
            raise FileError(tr("chemin trop long pour la machine : %s") % propre,
                            code=6, path=propre)
        return propre

    # -- disponibilité ---------------------------------------------------- #

    def probe(self, timeout: float = 1.5) -> bool:
        """La machine sait-elle donner ses fichiers ? Puis ouvre une session.

        La 1.2.1 ignore la commande : pas de réponse, et rien d'autre.
        """
        try:
            depart = time.perf_counter()
            objet, _ = self.request({"ping": {}}, timeout=timeout)
            self.supported = "^ping" in objet
            self.latency_ms = (time.perf_counter() - depart) * 1000.0
        except FileError:
            self.supported = False
            return False
        if self.supported:
            try:
                self.open_session()
            except FileError as exc:
                log.info("session de fichiers refusée : %s", exc)
        return bool(self.supported)

    def open_session(self, tag: str = "Noctiluca") -> int:
        """Réserve un jeu de numéros de message à l'application.

        Le firmware renvoie ``tag`` tel quel et choisit la session par
        ancienneté d'usage, quel qu'il soit (``smSysex::assignSession``,
        identique de la bêta 1.3 à la 1.3.0) : le nom n'y change rien.
        """
        objet, _ = self.request({"session": {"tag": tag}})
        partie = self._part(objet, "^session")
        mini = int(partie.get("midMin", 1))
        maxi = int(partie.get("midMax", 7))
        if 0 < mini <= maxi < 0x80:
            self._ids = list(range(mini, maxi + 1))
            self._next = 0
        self._session = int(partie.get("sid", 0))
        return self._session

    # -- lecture ----------------------------------------------------------- #

    def listdir(self, chemin: str = "/") -> list[CardEntry]:
        """Le contenu d'un dossier, toutes pages réunies."""
        chemin = self._path(chemin)
        entrees: list[CardEntry] = []
        offset = 0
        while True:
            objet, _ = self.request({"dir": {"path": chemin, "offset": offset,
                                             "lines": DIR_LINES}})
            partie = self._part(objet, "^dir")
            self._check(partie, tr("lecture du dossier"), chemin)
            page = partie.get("list") or []
            for e in page:
                nom = str(e.get("name", ""))
                if nom in ("", ".", ".."):
                    continue
                entrees.append(CardEntry(nom, int(e.get("size", 0)),
                                         int(e.get("date", 0)),
                                         int(e.get("time", 0)),
                                         int(e.get("attr", 0))))
            if len(page) < DIR_LINES:
                return entrees
            offset += len(page)

    def exists(self, chemin: str) -> CardEntry | None:
        """L'entrée de ``chemin``, ou ``None`` — sans tenir compte de la
        casse, comme FAT."""
        dossier, nom = _parent(self._path(chemin))
        try:
            entrees = self.listdir(dossier)
        except FileError as exc:
            if exc.code in (FR_NO_FILE, FR_NO_PATH):
                return None
            raise
        cle = nom.casefold()
        return next((e for e in entrees if e.name.casefold() == cle), None)

    def walk(self, chemin: str = "/", skip: Callable[[str], bool] | None = None,
             progress: Callable[[str], None] | None = None
             ) -> dict[str, CardEntry]:
        """Toute l'arborescence sous ``chemin`` : ``{chemin relatif: entrée}``.

        Les dossiers figurent aussi. Un nom non ASCII est noté dans
        :attr:`unreachable` et son contenu n'est pas parcouru.
        """
        racine = self._path(chemin)
        trouve: dict[str, CardEntry] = {}
        a_voir = [racine]
        while a_voir:
            dossier = a_voir.pop()
            self._check_stop(dossier)
            if progress is not None:
                progress(dossier)
            for e in self.listdir(dossier):
                complet = _join(dossier, e.name)
                rel = complet[len(racine):].strip("/") if racine != "/" \
                    else complet.strip("/")
                if skip is not None and skip(rel):
                    continue
                if not e.addressable:
                    self.unreachable.append(rel)
                    continue
                trouve[rel] = e
                if e.is_dir:
                    a_voir.append(complet)
        return trouve

    def read(self, chemin: str,
             progress: Callable[[int, int], None] | None = None) -> bytes:
        """Le contenu d'un fichier."""
        chemin = self._path(chemin)
        self._check_stop(chemin)
        objet, _ = self.request({"open": {"path": chemin}})
        partie = self._part(objet, "^open")
        self._check(partie, "ouverture", chemin)
        fid, taille = int(partie.get("fid", 0)), int(partie.get("size", 0))
        try:
            recu = self._read_blocks(fid, taille, chemin, progress)
        finally:
            self._close(fid)
        if len(recu) != taille:
            raise FileError(tr("lecture incomplète de %s : %d octets sur %d")
                            % (chemin, len(recu), taille), path=chemin)
        return recu

    def _read_blocks(self, fid: int, taille: int, chemin: str,
                     progress: Callable[[int, int], None] | None) -> bytes:
        """Les ``taille`` octets du fichier ouvert ``fid``, en gardant
        :data:`READ_AHEAD` demandes en vol.

        La machine traite ses requêtes en file (``smSysex::handleNextSysEx``)
        et répond dans l'ordre ; chaque réponse se reconnaît à son numéro.
        Mesuré sur elle : 156 à 159 Ko/s au lieu de 126 à 129 une à la fois,
        contenu identique octet pour octet.
        """
        blocs: dict[int, bytes] = {}
        en_vol: dict[int, int] = {}             # numéro -> adresse demandée
        prochaine, recu, fin = 0, 0, taille
        with self._lock:
            self._vider()
            while prochaine < fin or en_vol:
                self._check_stop(chemin)
                while len(en_vol) < READ_AHEAD and prochaine < fin:
                    numero = self._msg_id()
                    while numero in en_vol:
                        numero = self._msg_id()
                    self._emit(self._compose(
                        {"read": {"fid": fid, "addr": prochaine,
                                  "size": BLOCK}}, numero))
                    en_vol[numero] = prochaine
                    prochaine += BLOCK
                data = self._next_reply(en_vol, "read")
                adresse = en_vol.pop(data[6])
                objet, donnees = self._decode(data)
                partie = self._part(objet, "^read")
                self._check(partie, "lecture", chemin)
                n = int(partie.get("size", 0))
                if len(donnees) < n:
                    raise FileError(tr("bloc tronqué en lecture de %s") % chemin,
                                    path=chemin)
                if n <= 0:
                    # Plus court qu'annoncé : ne plus rien demander au-delà.
                    fin = min(fin, adresse)
                    continue
                blocs[adresse] = donnees[:n]
                recu += n
                if progress is not None:
                    progress(recu, taille)
        sortie = bytearray()
        for adresse in sorted(blocs):
            if adresse != len(sortie):
                break                            # un trou : incomplet
            sortie.extend(blocs[adresse])
        return bytes(sortie)

    def _next_reply(self, en_vol: dict[int, int], quoi: str) -> bytes:
        """La prochaine réponse à l'une des demandes en vol."""
        limite = time.monotonic() + self._timeout
        while True:
            reste = limite - time.monotonic()
            if reste <= 0:
                raise FileError(tr("le Deluge n'a pas répondu à « %s »") % quoi,
                                code=15)
            try:
                data, _arrivee = self._replies.get(timeout=reste)
            except queue.Empty:
                continue
            if data[5] != JSON_REPLY or data[6] not in en_vol:
                log.debug("réponse de fichiers ignorée (%02x, %d)",
                          data[5], data[6])
                continue
            return data

    def _close(self, fid: int) -> None:
        try:
            objet, _ = self.request({"close": {"fid": int(fid)}})
            partie = self._part(objet, "^close")
            if int(partie.get("err", 0) or 0):
                log.debug("fermeture de %d : %s", fid,
                          result_text(partie["err"]))
        except FileError as exc:
            log.debug("fermeture de %d impossible : %s", fid, exc)

    # -- écriture ---------------------------------------------------------- #

    def write_new(self, chemin: str, data: bytes,
                  mtime: float | None = None,
                  progress: Callable[[int, int], None] | None = None) -> None:
        """Écrit un fichier **qui n'existe pas encore**.

        Le contenu part sous un nom temporaire, puis est renommé : la
        machine refuse de renommer sur un nom pris (``FR_EXIST``), et rien
        d'existant n'est donc jamais écrasé, même si un autre fichier du
        même nom apparaît entre-temps.
        """
        chemin = self._path(chemin)
        if self.exists(chemin) is not None:
            raise FileError(tr("existe déjà sur la carte : %s") % chemin,
                            code=FR_EXIST, path=chemin)
        temporaire = self._temporary(chemin)
        self._upload(temporaire, bytes(data), progress)
        try:
            self.rename(temporaire, chemin)
        except FileError:
            self._delete_quietly(temporaire)
            raise
        if mtime is not None:
            self.touch(chemin, mtime)
        self._verify_size(chemin, len(data))

    def replace(self, chemin: str, data: bytes, mtime: float | None = None,
                progress: Callable[[int, int], None] | None = None) -> None:
        """Remplace un fichier existant, sans fenêtre où il n'existerait pas
        en entier.

        Le nouveau contenu part sous un nom temporaire ; l'ancien est mis de
        côté sous un autre ; le nouveau prend le nom ; l'ancien n'est
        supprimé qu'ensuite. Un échec en route remet l'ancien en place.
        """
        chemin = self._path(chemin)
        if self.exists(chemin) is None:
            return self.write_new(chemin, data, mtime, progress)
        temporaire = self._temporary(chemin)
        self._upload(temporaire, bytes(data), progress)
        ancien = self._temporary(chemin, "OLD")
        try:
            self.rename(chemin, ancien)
        except FileError:
            self._delete_quietly(temporaire)
            raise
        try:
            self.rename(temporaire, chemin)
        except FileError:
            self.rename(ancien, chemin)          # l'ancien revient
            self._delete_quietly(temporaire)
            raise
        self._delete_quietly(ancien)
        if mtime is not None:
            self.touch(chemin, mtime)
        self._verify_size(chemin, len(data))

    def _temporary(self, chemin: str, suffixe: str = "TMP") -> str:
        dossier, _ = _parent(chemin)
        try:
            pris = {e.name.casefold() for e in self.listdir(dossier)}
        except FileError as exc:
            if exc.code not in (FR_NO_FILE, FR_NO_PATH):
                raise
            pris = set()
        for i in range(1, 0x10000):
            nom = "~DC%04X.%s" % ((int(time.time() * 1000) + i) & 0xFFFF,
                                  suffixe)
            if nom.casefold() not in pris:
                return _join(dossier, nom)
        raise FileError(tr("aucun nom temporaire libre dans %s") % dossier)

    def _upload(self, chemin: str, data: bytes,
                progress: Callable[[int, int], None] | None) -> None:
        # « write »: 1 crée — et écrase : on n'ouvre ainsi qu'un nom neuf.
        objet, _ = self.request({"open": {"path": chemin, "write": 1}})
        partie = self._part(objet, "^open")
        self._check(partie, tr("création"), chemin)
        fid = int(partie.get("fid", 0))
        try:
            # Un fichier vide est déjà complet : l'ouverture l'a créé.
            self._write_blocks(fid, data, chemin, progress)
        except FileError:
            self._close(fid)
            self._delete_quietly(chemin)
            raise
        self._close(fid)

    def _write_blocks(self, fid: int, data: bytes, chemin: str,
                      progress: Callable[[int, int], None] | None) -> None:
        """Envoie ``data`` dans le fichier ouvert ``fid``, en gardant
        :data:`WRITE_AHEAD` blocs en vol.

        La machine range ses requêtes dans une file (``SysExQ``, une
        ``deque``) et les traite dans l'ordre ; chaque bloc porte son
        adresse, et chaque réponse son numéro. Mesuré sur elle le 22 octobre
        2026, fichiers de 150 Ko relus identiques : 48 à 50 Ko/s un bloc à la
        fois, 61 à 63 avec deux en vol, rien de plus avec trois.
        """
        en_vol: dict[int, int] = {}             # numéro -> taille du bloc
        envoye = confirme = 0
        with self._lock:
            self._vider()
            while envoye < len(data) or en_vol:
                self._check_stop(chemin)
                while len(en_vol) < WRITE_AHEAD and envoye < len(data):
                    bloc = data[envoye:envoye + self._write_block(fid, envoye)]
                    numero = self._msg_id()
                    while numero in en_vol:
                        numero = self._msg_id()
                    self._emit(self._compose(
                        {"write": {"fid": fid, "addr": envoye,
                                   "size": len(bloc)}}, numero, bloc))
                    en_vol[numero] = len(bloc)
                    envoye += len(bloc)
                reponse = self._next_reply(en_vol, "write")
                taille = en_vol.pop(reponse[6])
                objet, _ = self._decode(reponse)
                partie = self._part(objet, "^write")
                self._check(partie, tr("écriture"), chemin)
                if int(partie.get("size", -1)) != taille:
                    raise FileError(tr("bloc écrit incomplet : %s") % chemin,
                                    path=chemin)
                confirme += taille
                if progress is not None:
                    progress(confirme, len(data))

    @staticmethod
    def _write_block(fid: int, addr: int) -> int:
        """La plus grande charge d'écriture qui tienne dans un SysEx reçu.

        Message : 7 octets d'en-tête, le JSON, ``00``, les données en 7 bits
        (huit octets pour sept), ``F7``.
        """
        texte = json.dumps({"write": {"fid": int(fid), "addr": int(addr),
                                      "size": BLOCK}},
                           separators=(",", ":"))
        place = MAX_INCOMING - 7 - len(texte) - 2
        n = min(BLOCK, place * 7 // 8)
        while n > 0 and n + (n + 6) // 7 > place:
            n -= 1
        return max(1, n)

    def _verify_size(self, chemin: str, taille: int) -> None:
        entree = self.exists(chemin)
        if entree is None or entree.size != taille:
            raise FileError(tr("vérification après écriture : %s fait %s octets "
                               "au lieu de %d") % (chemin, getattr(entree, "size",
                                                               "?"), taille),
                            path=chemin)

    def _delete_quietly(self, chemin: str) -> None:
        try:
            self.delete(chemin)
        except FileError as exc:
            log.debug("nettoyage de %s impossible : %s", chemin, exc)

    # -- opérations simples ------------------------------------------------- #

    def mkdir(self, chemin: str, mtime: float | None = None) -> None:
        chemin = self._path(chemin)
        commande: dict = {"path": chemin}
        if mtime is not None:
            commande["date"], commande["time"] = fat_stamp(mtime)
        objet, _ = self.request({"mkdir": commande})
        partie = self._part(objet, "^mkdir")
        if int(partie.get("err", 0) or 0) != FR_EXIST:
            self._check(partie, tr("création du dossier"), chemin)

    def rename(self, ancien: str, nouveau: str) -> None:
        """Renomme ; refusé si ``nouveau`` existe (``FR_EXIST``)."""
        ancien, nouveau = self._path(ancien), self._path(nouveau)
        objet, _ = self.request({"rename": {"from": ancien, "to": nouveau}})
        self._check(self._part(objet, "^rename"), "renommage", ancien)

    def delete(self, chemin: str) -> None:
        """Supprime un fichier, ou un dossier vide."""
        chemin = self._path(chemin)
        objet, _ = self.request({"delete": {"path": chemin}})
        self._check(self._part(objet, "^delete"), "suppression", chemin)

    def touch(self, chemin: str, mtime: float) -> None:
        """Date de modification, au format de la carte."""
        chemin = self._path(chemin)
        date, heure = fat_stamp(mtime)
        objet, _ = self.request({"utime": {"path": chemin, "date": date,
                                           "time": heure}})
        self._check(self._part(objet, "^utime"), "datation", chemin)
