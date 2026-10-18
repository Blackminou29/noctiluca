# -*- coding: utf-8 -*-
"""Accès à la carte SD du Deluge.

Ce module est la seule porte d'entrée vers le système de fichiers de la carte.
Il n'importe jamais PyQt6 (cf. SPEC §0.7).

Deux difficultés réelles sont traitées ici :

* **La casse des chemins n'est pas fiable.** La carte est formatée en FAT32, qui
  ignore la casse ; les XML du Deluge référencent ``SAMPLES/Multisamples/…``
  alors que le dossier s'appelle ``SAMPLES/MULTISAMPLES``. Toute résolution
  passe donc par :meth:`SDCard.resolve_sample`, insensible à la casse.
* **La carte contient des parasites** (dossiers macOS, corbeilles Windows,
  fichiers AppleDouble ``._*``) qu'il faut écarter systématiquement, sinon les
  inventaires sont faussés.
"""

from __future__ import annotations

import ctypes
import logging
import os
import re
import string
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Constantes de structure (cf. SPEC §1.1)
# --------------------------------------------------------------------------- #

STD_DIRS = ("SONGS", "SYNTHS", "KITS", "SAMPLES")

#: Dossiers techniques à ne jamais parcourir (comparaison en minuscules).
IGNORED_DIRS = frozenset(
    {
        "system volume information",
        ".spotlight-v100",
        ".trashes",
        ".fseventsd",
        ".documentrevisions-v100",
        ".temporaryitems",
        ".apdisk",
        "$recycle.bin",
        "found.000",
        ".git",
        "__pycache__",
    }
)

#: Préfixes de fichiers à ignorer (AppleDouble macOS).
IGNORED_FILES_PREFIX = ("._",)

#: Noms de fichiers à ignorer quelle que soit leur casse.
IGNORED_FILES = frozenset({".ds_store", "thumbs.db", "desktop.ini", ".apdisk"})

AUDIO_EXT = (".wav", ".aif", ".aiff")
XML_EXT = (".xml",)

#: Catégories de percussions attendues sous ``SAMPLES/DRUMS`` (cf. SPEC §1.1).
DRUM_CATEGORIES = (
    "Kick", "Snare", "HatC", "HatO", "Clap", "Rim", "TomH", "TomM", "TomL",
    "Crash", "Ride", "China", "Cowbell", "Block", "Claves", "ConH", "ConM",
    "ConL", "Guiro", "Shaker", "Tambourine", "Timpany", "Other",
)

#: Caractères interdits par FAT32 dans un nom de fichier.
FORBIDDEN_CHARS = '<>:"/\\|?*'

#: Longueur maximale d'un nom de preset accepté par le Deluge.
MAX_NAME_LEN = 63

#: Noms réservés par Windows, à refuser même si FAT32 les accepterait.
RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)

_FIRMWARE_RE = re.compile(r"^deluge.*\.bin$", re.I)
_TRASH_RE = re.compile(r"^\.trash", re.I)


# --------------------------------------------------------------------------- #
# Normalisation des chemins
# --------------------------------------------------------------------------- #

def norm_rel(rel: str) -> str:
    """Clé de comparaison d'un chemin relatif : minuscules et séparateurs ``/``.

    C'est la seule façon correcte de comparer deux chemins de la carte, parce
    que FAT32 ignore la casse (cf. SPEC §1.7).
    """
    if not rel:
        return ""
    out = str(rel).replace("\\", "/").strip().strip("/")
    while "//" in out:
        out = out.replace("//", "/")
    return out.lower()


def _is_ignored_dir(name: str) -> bool:
    """Vrai si ce nom de dossier doit être écarté de tout parcours."""
    low = name.lower()
    return low in IGNORED_DIRS or bool(_TRASH_RE.match(low))


def _is_ignored_file(name: str) -> bool:
    """Vrai si ce nom de fichier doit être écarté de tout inventaire."""
    if name.startswith(IGNORED_FILES_PREFIX):
        return True
    return name.lower() in IGNORED_FILES


def is_deluge_root(p: Path) -> bool:
    """Vrai si ``p`` ressemble à la racine d'une carte Deluge.

    Critère : au moins deux des dossiers de :data:`STD_DIRS` présents.
    """
    try:
        p = Path(p)
        if not p.is_dir():
            return False
        with os.scandir(p) as it:
            present = {e.name.upper() for e in it if e.is_dir()}
    except (OSError, ValueError):
        return False
    return sum(1 for d in STD_DIRS if d in present) >= 2


# --------------------------------------------------------------------------- #
# Noms de fichiers compatibles Deluge / FAT32
# --------------------------------------------------------------------------- #

def safe_deluge_name(name: str) -> str:
    """Rend un nom utilisable sur la carte : ASCII, sans caractère interdit.

    Les accents sont translittérés (``Épée`` -> ``Epee``) plutôt que supprimés,
    pour que le nom reste lisible sur l'écran du Deluge.
    """
    if not name:
        return "SANS NOM"
    # Translittération des accents vers l'ASCII.
    decomposed = unicodedata.normalize("NFKD", str(name))
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    ascii_name = stripped.encode("ascii", "replace").decode("ascii")

    out = []
    for ch in ascii_name:
        if ch in FORBIDDEN_CHARS or ord(ch) < 32 or ch == "?":
            out.append(" ")
        else:
            out.append(ch)
    cleaned = "".join(out)
    # Espaces multiples réduits ; points et espaces de bord retirés, car FAT32
    # n'accepte pas un nom terminé par un point ou une espace.
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    cleaned = cleaned[:MAX_NAME_LEN].strip(" .")
    if cleaned.upper() in RESERVED_NAMES:
        cleaned += "_"
    return cleaned or "SANS NOM"


def check_name(name: str) -> list[str]:
    """Liste, en français, les problèmes d'un nom destiné à la carte.

    Retourne une liste vide si le nom est sain.
    """
    if name is None or not str(name).strip():
        return ["Le nom est vide."]
    name = str(name)
    problems: list[str] = []

    bad = sorted({c for c in name if c in FORBIDDEN_CHARS})
    if bad:
        problems.append("Caractères interdits par FAT32 : " + " ".join(bad))
    if any(ord(c) < 32 for c in name):
        problems.append("Le nom contient des caractères de contrôle.")
    try:
        name.encode("ascii")
    except UnicodeEncodeError:
        problems.append(
            "Le nom contient des caractères non ASCII ; le Deluge risque de "
            "les afficher incorrectement."
        )
    if len(name) > MAX_NAME_LEN:
        problems.append(
            f"Le nom fait {len(name)} caractères (maximum {MAX_NAME_LEN})."
        )
    if name != name.strip():
        problems.append("Le nom commence ou finit par une espace.")
    if name.endswith("."):
        problems.append("Le nom finit par un point.")
    if name.startswith("._"):
        problems.append("Le préfixe « ._ » est réservé aux fichiers macOS.")
    if name.upper() in RESERVED_NAMES:
        problems.append("Ce nom est réservé par Windows.")
    return problems


# --------------------------------------------------------------------------- #
# Détection des cartes
# --------------------------------------------------------------------------- #

_DRIVE_REMOVABLE = 2
_DRIVE_FIXED = 3


def _windows_drives() -> list[tuple[Path, int]]:
    """Lecteurs Windows présents, avec leur type ``GetDriveTypeW``."""
    found: list[tuple[Path, int]] = []
    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    except AttributeError:
        return found
    try:
        mask = int(kernel32.GetLogicalDrives())
    except OSError:
        return found
    for i, letter in enumerate(string.ascii_uppercase):
        if not mask & (1 << i):
            continue
        try:
            dtype = int(kernel32.GetDriveTypeW(ctypes.c_wchar_p(f"{letter}:\\")))
        except OSError:
            continue
        found.append((Path(f"{letter}:/"), dtype))
    return found


def detect_sd_cards() -> list[Path]:
    """Cartes Deluge branchées, détectées automatiquement.

    Sur Windows : parcourt les lecteurs amovibles puis les lecteurs fixes
    (une carte lue par un lecteur USB est souvent déclarée « fixe »).
    Sur les autres systèmes : passe en revue les points de montage usuels.
    Les emplacements sans arborescence Deluge sont écartés.
    """
    cards: list[Path] = []
    seen: set[str] = set()

    def _add(p: Path) -> None:
        key = str(p).lower()
        if key in seen:
            return
        seen.add(key)
        if is_deluge_root(p):
            cards.append(p)

    drives = _windows_drives()
    if drives:
        # Les amovibles d'abord : c'est le cas le plus probable.
        for root, dtype in drives:
            if dtype == _DRIVE_REMOVABLE:
                _add(root)
        for root, dtype in drives:
            if dtype == _DRIVE_FIXED:
                _add(root)
        return cards

    for base in ("/media", "/mnt", "/run/media", "/Volumes"):
        b = Path(base)
        try:
            if not b.is_dir():
                continue
            with os.scandir(b) as it:
                entries = [e for e in it if e.is_dir()]
        except OSError:
            continue
        for entry in entries:
            _add(Path(entry.path))
            # Cas /run/media/<utilisateur>/<étiquette>
            try:
                with os.scandir(entry.path) as sub_it:
                    subs = [s for s in sub_it if s.is_dir()]
            except OSError:
                continue
            for sub in subs:
                _add(Path(sub.path))
    return cards


# --------------------------------------------------------------------------- #
# La carte
# --------------------------------------------------------------------------- #

@dataclass
class SDCard:
    """Une carte SD de Deluge, montée à l'emplacement ``root``.

    Les chemins internes sont toujours manipulés en relatif avec des ``/``,
    exactement comme le Deluge les écrit (cf. SPEC §0.4).
    """

    root: Path
    #: Cache de résolution insensible à la casse : dossier relatif normalisé
    #: -> {nom en minuscules: nom réel}. Rempli à la demande.
    _dir_cache: dict[str, dict[str, str]] = field(
        default_factory=dict, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        self.root = Path(self.root)

    # -- conversions de chemins -------------------------------------------- #

    def rel(self, p: Path) -> str:
        """Chemin de ``p`` relatif à la racine, séparateur ``/``.

        Si ``p`` est hors de la carte, son nom seul est retourné.
        """
        p = Path(p)
        try:
            return p.relative_to(self.root).as_posix()
        except ValueError:
            pass
        # Repli : comparaison insensible à la casse, utile quand la casse de la
        # lettre de lecteur diffère (``c:\\`` contre ``C:\\``).
        try:
            rp, rr = str(p.resolve()), str(self.root.resolve())
            # Frontière de dossier exigée : sans elle, « SDCARD Deluge 2 »
            # passait pour un sous-dossier de « SDCARD Deluge ».
            if rp.lower() == rr.lower():
                return ""
            prefix = rr.rstrip("\\/") + os.sep
            if rp.lower().startswith(prefix.lower()):
                return rp[len(prefix):].replace("\\", "/").strip("/")
        except OSError:
            pass
        return p.name

    def abs(self, rel: str) -> Path:
        """Chemin absolu correspondant au chemin relatif ``rel``."""
        clean = str(rel or "").replace("\\", "/").strip("/")
        return self.root / clean if clean else self.root

    # -- résolution insensible à la casse ---------------------------------- #

    def _listing(self, rel_dir: str) -> dict[str, str]:
        """Table ``nom en minuscules -> nom réel`` du dossier ``rel_dir``."""
        key = norm_rel(rel_dir)
        cached = self._dir_cache.get(key)
        if cached is not None:
            return cached
        table: dict[str, str] = {}
        try:
            with os.scandir(self.abs(rel_dir)) as it:
                for entry in it:
                    table[entry.name.lower()] = entry.name
        except OSError:
            table = {}
        self._dir_cache[key] = table
        return table

    def resolve_sample(self, rel: str) -> Path | None:
        """Résout un ``fileName`` de XML vers un fichier réel, ou ``None``.

        La résolution est insensible à la casse, segment par segment : sans
        cela, la détection d'échantillons manquants produit des centaines de
        faux positifs (cf. SPEC §1.7).
        """
        clean = str(rel or "").replace("\\", "/").strip("/")
        if not clean:
            return None
        # Un ``fileName`` ne sort jamais de la carte : « .. » ou un lecteur
        # désigneraient un fichier que les réparations pourraient réécrire.
        if ".." in clean.split("/") or ":" in clean:
            return None

        # Le chemin peut déjà être correct : un seul appel système suffit alors.
        direct = self.abs(clean)
        try:
            if direct.exists():
                return direct
        except OSError:
            return None

        parts = [seg for seg in clean.split("/") if seg and seg != "."]
        if not parts:
            return None

        current = ""
        for seg in parts:
            real = self._listing(current).get(seg.lower())
            if real is None:
                return None
            current = f"{current}/{real}" if current else real

        candidate = self.abs(current)
        try:
            return candidate if candidate.exists() else None
        except OSError:
            return None

    def invalidate_cache(self) -> None:
        """Vide le cache de résolution (après une écriture sur la carte)."""
        self._dir_cache.clear()

    # -- inventaires -------------------------------------------------------- #

    def _walk(self, rel_dir: str, exts: tuple[str, ...],
              recursive: bool = True) -> list[Path]:
        """Fichiers de ``rel_dir`` dont l'extension est dans ``exts``.

        Les dossiers et fichiers parasites sont écartés. Ne lève jamais.
        """
        base = self.abs(rel_dir)
        if not base.is_dir():
            # Le dossier peut exister sous une autre casse.
            resolved = self.resolve_sample(rel_dir)
            if resolved is None or not resolved.is_dir():
                return []
            base = resolved

        out: list[Path] = []
        stack = [base]
        while stack:
            current = stack.pop()
            try:
                with os.scandir(current) as it:
                    entries = list(it)
            except OSError as exc:
                log.debug("dossier illisible %s : %s", current, exc)
                continue
            for entry in entries:
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                except OSError:
                    continue
                if is_dir:
                    if recursive and not _is_ignored_dir(entry.name):
                        stack.append(Path(entry.path))
                    continue
                name = entry.name
                if _is_ignored_file(name):
                    continue
                if exts and not name.lower().endswith(exts):
                    continue
                out.append(Path(entry.path))
        out.sort(key=lambda p: str(p).lower())
        return out

    def songs(self) -> list[Path]:
        """Tous les morceaux de ``SONGS/``."""
        return self._walk("SONGS", XML_EXT)

    def synths(self) -> list[Path]:
        """Tous les presets de synthé de ``SYNTHS/`` (sous-dossiers inclus)."""
        return self._walk("SYNTHS", XML_EXT)

    def kits(self) -> list[Path]:
        """Tous les kits de ``KITS/`` (sous-dossiers inclus)."""
        return self._walk("KITS", XML_EXT)

    def samples(self) -> list[Path]:
        """Tous les échantillons audio de ``SAMPLES/`` (sous-dossiers inclus)."""
        return self._walk("SAMPLES", AUDIO_EXT)

    def firmware_files(self) -> list[Path]:
        """Fichiers de firmware ``deluge*.bin`` présents à la racine.

        Le Deluge n'en accepte qu'un seul : plusieurs fichiers constituent une
        anomalie, signalée par la page Santé.
        """
        out: list[Path] = []
        try:
            with os.scandir(self.root) as it:
                for entry in it:
                    if entry.is_file() and _FIRMWARE_RE.match(entry.name):
                        out.append(Path(entry.path))
        except OSError as exc:
            log.debug("racine illisible %s : %s", self.root, exc)
        out.sort(key=lambda p: p.name.lower())
        return out

    # -- état --------------------------------------------------------------- #

    def is_valid(self) -> bool:
        """Vrai si la racine contient au moins deux dossiers standards."""
        return is_deluge_root(self.root)

    def missing_dirs(self) -> list[str]:
        """Dossiers standards absents de la carte."""
        try:
            with os.scandir(self.root) as it:
                present = {e.name.upper() for e in it if e.is_dir()}
        except OSError:
            return list(STD_DIRS)
        return [d for d in STD_DIRS if d not in present]

    @property
    def is_volume(self) -> bool:
        """Vrai si la carte est la racine d'un lecteur : une vraie carte SD,
        ou le Deluge branché en stockage USB.

        Faux pour une copie dans un dossier de l'ordinateur — le cas de la
        carte de référence. L'espace libre est alors celui du disque entier
        (474,7 Gio), qu'il ne faut pas présenter comme celui d'une carte.
        """
        try:
            return os.path.ismount(str(self.root))
        except (OSError, ValueError):
            return False

    def free_space(self) -> tuple[int, int]:
        """``(octets libres, octets totaux)``. ``(0, 0)`` si indisponible."""
        try:
            import shutil

            total, _used, free = shutil.disk_usage(self.root)
            return free, total
        except (OSError, ValueError) as exc:
            log.debug("espace disque indisponible pour %s : %s", self.root, exc)
            return 0, 0
