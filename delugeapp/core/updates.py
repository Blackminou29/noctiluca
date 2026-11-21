# -*- coding: utf-8 -*-
"""Savoir s'il existe une version plus récente de l'application, et
l'installer.

Le manuel promet « ni Internet, ni compte » : rien ne part sur le réseau
sans que l'utilisateur l'ait demandé — le menu Aide ▸ Rechercher une
nouvelle version, ou la case des réglages, **décochée par défaut**, qui le
fait au plus une fois par jour au démarrage. La seule requête est une
lecture de la page publique des versions sur GitHub ; elle n'envoie rien
d'autre que l'en-tête ``User-Agent`` de l'application.

Depuis la 1.1.0, une version plus récente peut aussi s'installer d'elle-
même, si l'utilisateur le demande (:func:`prepare`, puis :func:`launch`) :

* le fichier de son système est téléchargé depuis la page de la version,
  puis vérifié — sa taille, et son empreinte SHA-256, celle que GitHub
  publie pour chaque fichier d'une version (``digest``). Un fichier qui ne
  correspond pas est effacé, rien ne s'installe ;
* **Windows** : l'installateur se lance une fois l'application fermée, sans
  ses pages (``/S``) ; Windows demande l'autorisation d'installer ;
  l'installateur attend que l'application soit fermée, puis la rouvre
  (``/RELANCER``, ``packaging/windows/noctiluca.nsi``) ;
* **macOS** : l'application est copiée depuis l'image disque à côté de
  celle qui tourne, puis, une fois celle-ci fermée, prend sa place et se
  rouvre — l'ancienne n'est effacée qu'une fois la nouvelle en place ;
* **Linux** (l'AppImage) : le fichier est téléchargé à côté de celui qui
  tourne, puis le remplace une fois l'application fermée, et se relance.

Lancée depuis ses sources, depuis l'archive Linux, ou d'un endroit qu'elle
ne peut pas réécrire, l'application ouvre la page de la version, comme
avant.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .. import __repo__, __version__
from ..i18n import tr, untranslated

log = logging.getLogger(__name__)

__all__ = ["Asset", "Release", "Pending", "UpdateError", "API_URL",
           "latest_release", "is_newer", "due", "install_kind", "asset_for",
           "download", "prepare", "launch"]

#: La dernière version publiée, lue sur l'API publique de GitHub.
API_URL = __repo__.replace("https://github.com/",
                           "https://api.github.com/repos/") \
    + "/releases/latest"

#: Les seuls fichiers qu'on accepte de télécharger : ceux des versions du
#: dépôt.
DOWNLOADS = __repo__ + "/releases/download/"

#: Délai entre deux vérifications automatiques.
INTERVAL = timedelta(days=1)

#: Le fichier de chaque façon d'installer, par la fin de son nom
#: (``packaging/``, ``.github/workflows/paquets.yml``).
SUFFIXES = {"windows": "-windows-x64-setup.exe",
            "macos": "-macos-arm64.dmg",
            "appimage": "-linux-x86_64.AppImage"}


class UpdateError(Exception):
    """Un téléchargement ou une installation qui n'a pas abouti ; le
    message se montre tel quel."""


@dataclass(frozen=True)
class Asset:
    """Un fichier d'une version : son nom, son adresse, sa taille et son
    empreinte SHA-256 (en hexadécimal), telles que GitHub les publie."""

    name: str
    url: str
    size: int
    sha256: str


@dataclass(frozen=True)
class Release:
    """Une version publiée : son numéro, sa page et ses fichiers."""

    version: str
    url: str
    assets: tuple = ()


@dataclass(frozen=True)
class Pending:
    """Une version téléchargée, vérifiée et prête : ``file`` (l'installateur,
    l'application ou l'AppImage) remplace ``target`` à la fermeture."""

    kind: str
    file: Path
    target: Path | None
    version: str


@dataclass(frozen=True)
class DownloadProgress:
    """L'avancement d'un téléchargement, en mégaoctets
    (:func:`.ui.tasks.run_task` en fait une barre)."""

    message: str
    current: int
    total: int


def _key(version: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", str(version))[:4])


def is_newer(version: str, current: str = __version__) -> bool:
    """Vrai si ``version`` (``v1.2.0``, ``1.2``…) dépasse ``current``."""
    a, b = _key(version), _key(current)
    if not a:
        return False
    longueur = max(len(a), len(b))
    return a + (0,) * (longueur - len(a)) > b + (0,) * (longueur - len(b))


def _assets(donnees: dict) -> tuple[Asset, ...]:
    """Les fichiers d'une version qu'on saurait vérifier : sur le dépôt,
    avec une taille et une empreinte SHA-256."""
    out = []
    for fichier in donnees.get("assets") or ():
        if not isinstance(fichier, dict):
            continue
        nom = str(fichier.get("name") or "")
        url = str(fichier.get("browser_download_url") or "")
        empreinte = str(fichier.get("digest") or "")
        if not nom or "/" in nom or "\\" in nom or nom.startswith(".") \
                or not url.startswith(DOWNLOADS) \
                or not empreinte.startswith("sha256:"):
            continue
        hexa = empreinte[len("sha256:"):].lower()
        try:
            taille = int(fichier.get("size") or 0)
        except (TypeError, ValueError):
            continue
        if taille > 0 and re.fullmatch(r"[0-9a-f]{64}", hexa):
            out.append(Asset(nom, url, taille, hexa))
    return tuple(out)


def latest_release(timeout: float = 6.0, opener=None) -> Release | None:
    """La dernière version publiée, ou ``None`` (pas de réseau, réponse
    étrange). Ne lève jamais."""
    requete = urllib.request.Request(
        API_URL, headers={"User-Agent": "Noctiluca/%s" % __version__,
                          "Accept": "application/vnd.github+json"})
    try:
        ouvrir = opener or urllib.request.urlopen
        with ouvrir(requete, timeout=timeout) as reponse:
            donnees = json.loads(reponse.read(512 * 1024).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - pas de réseau : rien à dire
        log.info("vérification de version impossible : %s", exc)
        return None
    if not isinstance(donnees, dict) or donnees.get("draft") \
            or donnees.get("prerelease"):
        return None
    tag = str(donnees.get("tag_name") or "").strip()
    url = str(donnees.get("html_url") or __repo__ + "/releases")
    if not _key(tag) or not url.startswith("https://github.com/"):
        return None
    return Release(version=tag.lstrip("vV"), url=url,
                   assets=_assets(donnees))


def due(last_check: str, now: datetime | None = None) -> bool:
    """Vrai si la dernière vérification date de plus d'un jour."""
    try:
        derniere = datetime.fromisoformat(str(last_check))
    except (TypeError, ValueError):
        return True
    return (now or datetime.now()) - derniere >= INTERVAL


# --------------------------------------------------------------------------- #
# L'installation
# --------------------------------------------------------------------------- #

def app_bundle(executable) -> Path | None:
    """Le paquet ``….app`` qui contient ``executable`` (macOS), ou
    ``None``."""
    chemin = Path(executable).resolve()
    for parent in chemin.parents:
        if parent.suffix == ".app":
            return parent
    return None


def install_kind(platform: str | None = None, frozen: bool | None = None,
                 environ=None, executable: str | None = None) -> str | None:
    """Comment une nouvelle version s'installerait ici : ``"windows"``,
    ``"macos"``, ``"appimage"`` — ou ``None`` : lancée depuis ses sources,
    l'archive Linux, une application qu'on ne peut pas réécrire (macOS la
    déplace en lecture seule tant qu'on ne l'a pas rangée,
    ``AppTranslocation``) ; la page de la version s'ouvre alors."""
    platform = sys.platform if platform is None else platform
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None \
        else frozen
    environ = os.environ if environ is None else environ
    if not frozen:
        return None
    if platform == "win32":
        return "windows"
    if platform == "darwin":
        paquet = app_bundle(executable or sys.executable)
        if paquet is None or "AppTranslocation" in paquet.parts \
                or not os.access(paquet.parent, os.W_OK):
            return None
        return "macos"
    if platform.startswith("linux"):
        image = environ.get("APPIMAGE") or ""
        if image and os.path.isfile(image) \
                and os.access(os.path.dirname(image) or ".", os.W_OK):
            return "appimage"
    return None


def asset_for(release: Release, kind: str | None) -> Asset | None:
    """Le fichier de ``release`` qui s'installe de cette façon."""
    suffixe = SUFFIXES.get(kind or "")
    if not suffixe:
        return None
    return next((a for a in release.assets if a.name.endswith(suffixe)),
                None)


def _sha256(chemin: Path) -> str:
    empreinte = hashlib.sha256()
    with open(chemin, "rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            empreinte.update(bloc)
    return empreinte.hexdigest()


def download(asset: Asset, destination, progress=None, should_stop=None,
             opener=None, chunk: int = 1 << 16) -> Path:
    """Télécharge ``asset`` vers ``destination`` et le vérifie : sa taille,
    puis son empreinte SHA-256. Rend ``destination``. Un fichier déjà là et
    juste ne se télécharge pas une seconde fois ; un fichier faux est
    effacé. Lève :class:`UpdateError`."""
    destination = Path(destination)
    if not asset.url.startswith(DOWNLOADS):
        raise UpdateError(tr("adresse refusée : %s") % asset.url)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and destination.stat().st_size == asset.size \
            and _sha256(destination) == asset.sha256:
        return destination
    partiel = destination.with_name(destination.name + ".part")
    requete = urllib.request.Request(
        asset.url, headers={"User-Agent": "Noctiluca/%s" % __version__})
    message = tr("Noctiluca, mégaoctets reçus")
    total = max(1, asset.size >> 20)
    empreinte = hashlib.sha256()
    recus = 0
    try:
        ouvrir = opener or urllib.request.urlopen
        with ouvrir(requete, timeout=30) as reponse, \
                open(partiel, "wb") as sortie:
            adresse = getattr(reponse, "geturl", lambda: asset.url)()
            if not str(adresse).startswith("https://"):
                raise UpdateError(tr("adresse refusée : %s") % adresse)
            while True:
                if should_stop is not None and should_stop():
                    raise UpdateError(tr("téléchargement interrompu"))
                bloc = reponse.read(chunk)
                if not bloc:
                    break
                avant = recus >> 20
                recus += len(bloc)
                if recus > asset.size:
                    raise UpdateError(tr("le fichier dépasse la taille "
                                         "annoncée"))
                empreinte.update(bloc)
                sortie.write(bloc)
                if progress is not None and (recus >> 20) != avant:
                    progress(DownloadProgress(message, recus >> 20, total))
        if recus != asset.size:
            raise UpdateError(tr("fichier incomplet : %d octets sur %d")
                              % (recus, asset.size))
        if empreinte.hexdigest() != asset.sha256:
            raise UpdateError(tr("l'empreinte SHA-256 du fichier n'est pas "
                                 "celle que publie GitHub"))
        os.replace(partiel, destination)
    except UpdateError:
        partiel.unlink(missing_ok=True)
        raise
    except Exception as exc:  # noqa: BLE001 - réseau, disque : un message
        partiel.unlink(missing_ok=True)
        raise UpdateError(str(exc)) from exc
    return destination


def download_folder() -> Path:
    """Le dossier des installateurs et images disque téléchargés."""
    return Path(tempfile.gettempdir()) / "noctiluca-mise-a-jour"


def _stage_dmg(dmg: Path, staged: Path, run=subprocess.run) -> None:
    """Copie ``Noctiluca.app`` de l'image disque ``dmg`` vers ``staged``
    (``hdiutil``, puis ``ditto``, qui garde la signature)."""
    montage = Path(tempfile.mkdtemp(prefix="noctiluca-dmg-"))
    try:
        run(["hdiutil", "attach", "-nobrowse", "-readonly", "-noautoopen",
             "-quiet", "-mountpoint", str(montage), str(dmg)],
            check=True, timeout=180)
    except Exception as exc:  # noqa: BLE001
        raise UpdateError(tr("image disque illisible : %s") % exc) from exc
    try:
        source = montage / "Noctiluca.app"
        if not source.is_dir():
            raise UpdateError(tr("l'image disque ne contient pas "
                                 "Noctiluca.app"))
        shutil.rmtree(staged, ignore_errors=True)
        try:
            run(["ditto", str(source), str(staged)], check=True, timeout=900)
        except Exception as exc:  # noqa: BLE001
            shutil.rmtree(staged, ignore_errors=True)
            raise UpdateError(tr("copie impossible : %s") % exc) from exc
    finally:
        run(["hdiutil", "detach", "-quiet", str(montage)], timeout=120)


def prepare(release: Release, asset: Asset, kind: str, progress=None,
            should_stop=None, opener=None, environ=None,
            executable: str | None = None, run=subprocess.run) -> Pending:
    """Télécharge, vérifie et prépare ``release`` ; rien n'est remplacé
    avant :func:`launch`. Lève :class:`UpdateError`."""
    environ = os.environ if environ is None else environ
    if kind == "appimage":
        image = Path(environ.get("APPIMAGE") or "")
        if not image.is_file():
            raise UpdateError(tr("AppImage introuvable"))
        # À côté de l'actuelle : le remplacement est un simple renommage.
        nouvelle = image.with_name(".%s.nouveau" % asset.name)
        download(asset, nouvelle, progress, should_stop, opener)
        os.chmod(nouvelle, 0o755)
        return Pending("appimage", nouvelle, image, release.version)
    fichier = download(asset, download_folder() / asset.name, progress,
                       should_stop, opener)
    if kind == "windows":
        return Pending("windows", fichier, None, release.version)
    if kind == "macos":
        paquet = app_bundle(executable or sys.executable)
        if paquet is None:
            raise UpdateError(tr("application introuvable"))
        nouvelle = paquet.with_name(".Noctiluca-%s.app" % release.version)
        _stage_dmg(fichier, nouvelle, run)
        return Pending("macos", nouvelle, paquet, release.version)
    raise UpdateError(tr("installation automatique impossible ici"))


#: Ce que fait, une fois l'application fermée (le processus ``$1`` sorti),
#: le petit script qui remplace ``$3`` par ``$2`` puis le relance.
#: L'ancienne application macOS n'est effacée qu'une fois la nouvelle en
#: place, et revient si l'échange échoue.
SCRIPTS = untranslated({
    "appimage": ('while kill -0 "$1" 2>/dev/null; do sleep 0.3; done; '
                 'mv -f "$2" "$3" && exec "$3"'),
    "macos": ('while kill -0 "$1" 2>/dev/null; do sleep 0.3; done; '
              'ancien="$3.ancien"; rm -rf "$ancien"; '
              'if mv "$3" "$ancien" && mv "$2" "$3"; then rm -rf "$ancien"; '
              'elif [ -d "$ancien" ] && [ ! -e "$3" ]; then '
              'mv "$ancien" "$3"; fi; open "$3"'),
})


def launch(pending: Pending, pid: int | None = None, popen=None,
           startfile=None) -> None:
    """Lance l'installation de ``pending`` : à appeler quand la fenêtre est
    fermée. L'installateur (Windows) ou le script (macOS, Linux) attend la
    fin du processus, remplace l'application, puis la rouvre."""
    pid = os.getpid() if pid is None else int(pid)
    if pending.kind == "windows":
        ouvrir = startfile or getattr(os, "startfile")
        # ShellExecute : Windows demande l'autorisation qu'exige
        # l'installateur, là où un processus ordinaire échouerait.
        ouvrir(str(pending.file), arguments="/S /RELANCER")
        return
    script = SCRIPTS.get(pending.kind)
    if script is None or pending.target is None:
        raise UpdateError(tr("installation automatique impossible ici"))
    (popen or subprocess.Popen)(
        ["/bin/sh", "-c", script, "noctiluca-mise-a-jour", str(pid),
         str(pending.file), str(pending.target)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
