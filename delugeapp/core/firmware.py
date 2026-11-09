# -*- coding: utf-8 -*-
"""Préparer une mise à jour du firmware communautaire du Deluge.

Mettre la machine à jour, c'est télécharger la version, la décompresser,
poser le seul ``.bin`` à la racine de la carte et retirer l'ancien : le
Deluge refuse de s'installer avec deux ``.bin`` à la racine (guide de mise à
jour du dépôt du firmware). Ce module fait ces gestes **sur demande
seulement** : il ne consulte le réseau que quand on le lui demande, n'écrit
qu'après le plan, range l'ancien firmware dans ``_BACKUP`` — qui ne voyage
pas vers la carte — et **ne flashe jamais rien** : c'est la machine qui
s'installe, allumée SHIFT enfoncé.

Mesuré le 8 novembre 2026 sur les versions publiées (API GitHub) : les
versions stables sont celles qui ne sont ni brouillon ni « pre-release ». La
1.3.0 se publie en ``v1.3.0.zip``, qui contient ``v1.3.0/deluge-c1_3_0.bin``
— identique, octet pour octet, au firmware de la carte de l'utilisateur —,
un ``README.txt`` et des parasites macOS, dont
``__MACOSX/v1.3.0/._deluge-c1_3_0.bin`` qu'un extracteur naïf prendrait
pour le firmware. La 1.0.0 publiait le ``.bin`` seul (``deluge-c1_0_0.bin``) ;
les 1.1 et 1.2, un ``.zip`` au nom variable.

Le guide prévient qu'un ``.bin`` vide, ou de 3,5 Mo et plus, peut rendre
inutilisable un Deluge à afficheur 7 segments au vieux chargeur de
démarrage : la taille est vérifiée (:data:`SAFE_SIZE`) avant toute écriture.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import shutil
import urllib.request
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .. import __version__
from ..i18n import decimal, tr
from .sdcard import SDCard

log = logging.getLogger(__name__)

__all__ = ["FirmwareRelease", "FirmwarePlan", "API_URL", "SAFE_SIZE",
           "version_of", "card_version", "is_newer", "latest_release",
           "download", "firmware_from", "plan_install", "install"]

#: Les versions publiées du firmware communautaire, lues sur l'API publique.
API_URL = ("https://api.github.com/repos/SynthstromAudible/DelugeFirmware/"
           "releases?per_page=20")

#: Tailles admises pour un ``.bin`` : 1,7 Mio pour la 1.3.0, 1,3 Mio pour la
#: 1.0.0 ; au-delà de 3,5 Mo, le guide craint pour les Deluge 7 segments.
SAFE_SIZE = (256 * 1024, 3 * 1024 * 1024)

#: Plus gros téléchargement accepté (les archives des préversions, qui
#: emportent un ``.elf`` de débogage, font 25 Mo).
MAX_DOWNLOAD = 64 * 1024 * 1024

_BIN_RE = re.compile(r"^deluge.*\.bin$", re.I)


@dataclass(frozen=True)
class FirmwareRelease:
    """Une version stable publiée, et le fichier qui la porte."""

    version: str            # « 1.3.0 »
    tag: str                # « v1.3.0 »
    asset: str              # « v1.3.0.zip » ou « deluge-c1_0_0.bin »
    url: str                # le fichier à télécharger
    page: str               # la page de la version, pour la lire
    size: int = 0


def version_of(text: str) -> str:
    """« 1.3.0 » tiré de « deluge-c1_3_0.bin », « c1.3.0 », « v1.3.0 »,
    « release_1_2_1 » ou « deluge-v1_3_0-beta+2026_10_18-….bin » ; ``""``
    si rien n'y ressemble. Seuls les trois premiers nombres comptent : la
    date d'une bêta n'est pas une version."""
    match = re.search(r"(\d+)[._](\d+)(?:[._](\d+))?", str(text or ""))
    if not match:
        return ""
    return ".".join(n for n in (match.group(1), match.group(2),
                                match.group(3) or "0"))


def _key(version: str) -> tuple[int, ...]:
    return tuple(int(n) for n in version.split(".")) if version else ()


def is_newer(version: str, current: str) -> bool:
    """Vrai si ``version`` dépasse ``current`` (« 1.3.0 » contre « 1.2.1 »).
    Une version inconnue n'est jamais plus récente ; contre une version
    courante inconnue, toute version l'est."""
    a, b = _key(version_of(version)), _key(version_of(current))
    if not a:
        return False
    return not b or a > b


def card_version(sd: SDCard) -> str:
    """La version du ``.bin`` à la racine de la carte, s'il n'y en a qu'un."""
    fichiers = sd.firmware_files()
    return version_of(fichiers[0].name) if len(fichiers) == 1 else ""


def _open(url: str, timeout: float, opener, accept: str):
    requete = urllib.request.Request(
        url, headers={"User-Agent": "Noctiluca/%s" % __version__,
                      "Accept": accept})
    return (opener or urllib.request.urlopen)(requete, timeout=timeout)


def latest_release(timeout: float = 10.0,
                   opener=None) -> FirmwareRelease | None:
    """La plus récente version **stable** publiée, ou ``None`` (pas de
    réseau, réponse étrange, aucun fichier reconnu). Ne lève jamais."""
    try:
        with _open(API_URL, timeout, opener,
                   "application/vnd.github+json") as reponse:
            donnees = json.loads(reponse.read(2 * 1024 * 1024).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - pas de réseau : rien à dire
        log.info("versions du firmware illisibles : %s", exc)
        return None
    meilleure: FirmwareRelease | None = None
    for publie in donnees if isinstance(donnees, list) else ():
        if not isinstance(publie, dict) or publie.get("draft") \
                or publie.get("prerelease"):
            continue
        tag = str(publie.get("tag_name") or "")
        version = version_of(tag)
        fichier = _asset_of(publie.get("assets") or ())
        page = str(publie.get("html_url") or "")
        if not version or fichier is None \
                or not page.startswith("https://github.com/"):
            continue
        if meilleure is None or _key(version) > _key(meilleure.version):
            meilleure = FirmwareRelease(
                version=version, tag=tag, asset=fichier["name"],
                url=fichier["browser_download_url"], page=page,
                size=int(fichier.get("size") or 0))
    return meilleure


def _asset_of(assets) -> dict | None:
    """Le fichier qui porte le firmware : un ``deluge*.bin``, sinon le
    ``.zip`` ; jamais le ``.elf`` de débogage."""
    valides = [a for a in assets if isinstance(a, dict)
               and str(a.get("browser_download_url") or "").startswith(
                   "https://github.com/")]
    for a in valides:
        if _BIN_RE.match(str(a.get("name") or "")):
            return a
    for a in valides:
        if str(a.get("name") or "").lower().endswith(".zip"):
            return a
    return None


def download(release: FirmwareRelease, timeout: float = 120.0,
             opener=None) -> bytes:
    """Le fichier de la version ; lève :class:`OSError` en cas d'échec."""
    with _open(release.url, timeout, opener,
               "application/octet-stream") as reponse:
        donnees = reponse.read(MAX_DOWNLOAD + 1)
    if len(donnees) > MAX_DOWNLOAD:
        raise OSError(tr("le fichier téléchargé est anormalement gros"))
    if release.size and len(donnees) != release.size:
        raise OSError(tr("téléchargement incomplet : %d octets sur %d")
                      % (len(donnees), release.size))
    return donnees


def _check_size(data: bytes) -> None:
    bas, haut = SAFE_SIZE
    if not bas <= len(data) <= haut:
        raise ValueError(tr("le firmware fait %d octets, hors des tailles "
                            "sûres (%d à %d) : il n'est pas posé")
                         % (len(data), bas, haut))


def firmware_from(data: bytes, name: str) -> tuple[str, bytes]:
    """Le ``deluge*.bin`` contenu dans ``data`` : le fichier lui-même, ou
    l'unique ``deluge*.bin`` d'une archive, parasites macOS écartés.
    Lève :class:`ValueError` si rien de sûr n'en sort."""
    nom = Path(str(name or "")).name
    if _BIN_RE.match(nom):
        _check_size(data)
        return nom, data
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError(tr("archive illisible : %s") % exc) from exc
    trouves = []
    for entree in archive.infolist():
        parties = entree.filename.replace("\\", "/").split("/")
        base = parties[-1]
        if entree.is_dir() or "__MACOSX" in parties or base.startswith("._"):
            continue
        if _BIN_RE.match(base):
            trouves.append((base, entree))
    if len(trouves) != 1:
        raise ValueError(tr("l'archive contient %d firmware(s) au lieu "
                            "d'un seul") % len(trouves))
    base, entree = trouves[0]
    try:
        contenu = archive.read(entree)          # le CRC y est vérifié
    except (zipfile.BadZipFile, OSError) as exc:
        raise ValueError(tr("archive abîmée : %s") % exc) from exc
    _check_size(contenu)
    return base, contenu


@dataclass
class FirmwarePlan:
    """Ce que la pose du firmware fera sur la carte."""

    name: str
    data: bytes
    #: Les ``.bin`` de la racine, rangés dans ``backup`` avant la pose.
    retired: list[str] = field(default_factory=list)
    backup: str = ""

    def lines(self) -> list[str]:
        out = [tr("Poser %s à la racine de la carte (%s Mio).")
               % (self.name, decimal(len(self.data) / 2**20, 1))]
        for rel in self.retired:
            out.append(tr("Ranger l'ancien %s dans %s.") % (rel, self.backup))
        return out


def _backup_dir(sd: SDCard) -> str:
    base = "_BACKUP/firmware-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    rel, n = base, 2
    while sd.exists(rel):
        rel, n = "%s-%d" % (base, n), n + 1
    return rel


def plan_install(sd: SDCard, name: str, data: bytes) -> FirmwarePlan:
    """Le plan : le nouveau ``.bin`` posé, les anciens rangés. N'écrit rien."""
    _check_size(data)
    if not _BIN_RE.match(name):
        raise ValueError(tr("« %s » n'est pas un nom de firmware") % name)
    retires = [sd.rel(p) for p in sd.firmware_files()]
    return FirmwarePlan(name=name, data=data, retired=retires,
                        backup=_backup_dir(sd) if retires else "")


def install(sd: SDCard, plan: FirmwarePlan) -> Path:
    """Pose le firmware selon ``plan`` : les anciens ``.bin`` rangés dans
    ``_BACKUP``, le nouveau écrit par un fichier temporaire puis renommé —
    une coupure en cours de route ne laisse jamais un ``.bin`` à moitié
    écrit à la racine. Retourne le chemin du nouveau ``.bin``."""
    sd.require_writable()
    _check_size(plan.data)
    cible = sd.abs(plan.name)
    temporaire = cible.with_name(cible.name + ".noct-tmp")
    temporaire.write_bytes(plan.data)
    try:
        if plan.retired:
            dossier = sd.abs(plan.backup)
            dossier.mkdir(parents=True, exist_ok=True)
            for rel in plan.retired:
                source = sd.abs(rel)
                if source.exists():
                    shutil.move(str(source), str(dossier / source.name))
        os.replace(temporaire, cible)
    finally:
        if temporaire.exists():
            temporaire.unlink()
    sd.invalidate_cache()
    log.info("firmware %s posé à la racine (%d octets), %d ancien(s) rangé(s)"
             " dans %s", plan.name, len(plan.data), len(plan.retired),
             plan.backup or "—")
    return cible
