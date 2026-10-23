# -*- coding: utf-8 -*-
"""Réglages persistants et contexte applicatif de Deluge Companion.

Ce module est volontairement **sans dépendance Qt au niveau du module** :
il est importé aussi bien par le cœur (`delugeapp.core.*`) que par l'interface.
Les types Qt/cœur ne servent qu'aux annotations (`TYPE_CHECKING`), et le seul
endroit qui touche à PyQt6 (`AppContext.sd_or_warn`) le fait par import local.

Persistance : ``%APPDATA%/DelugeCompanion/settings.json`` (UTF-8, écriture
atomique). La lecture est tolérante : clés inconnues ignorées, clés absentes
remplacées par la valeur par défaut, types corrigés au mieux.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .i18n import N_, normalize, tr

if TYPE_CHECKING:  # pragma: no cover - uniquement pour les annotations
    from delugeapp.core.audio_out import Player
    from delugeapp.core.db import Library
    from delugeapp.core.sdcard import SDCard

log = logging.getLogger(__name__)

APP_NAME = "Deluge Companion"
APP_ORG = "DelugeCompanion"

__all__ = [
    "APP_NAME", "APP_ORG", "CONFIG_ENV",
    "CONFIG_DIR", "SETTINGS_PATH", "DB_PATH", "LOG_PATH",
    "DEFAULT_BACKUP_DIR", "Settings", "AppContext",
    "load_settings", "save_settings", "ensure_config_dir",
]


# ---------------------------------------------------------------------------
# Emplacements
# ---------------------------------------------------------------------------
def _base_dir() -> Path:
    """Dossier de configuration de l'utilisateur, selon la plateforme."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata)
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg)
    home = Path.home()
    if os.name == "nt":
        return home / "AppData" / "Roaming"
    return home / ".config"


#: Variable d'environnement qui impose le dossier de configuration.
#:
#: Deux usages. Le premier est pour l'utilisateur : une installation
#: « portable », réglages et index sur la clé USB, à côté du
#: logiciel.
#:
#: Le second est une règle de travail. Tout script qui lance la vraie
#: application doit la poser, car l'application **enregistre les
#: réglages en quittant** : un script d'essai qui coupe la confirmation
#: d'écriture pour reproduire un bogue la laisse coupée dans les
#: réglages de l'utilisateur, et sa carte perd son filet. C'est
#: arrivé.
CONFIG_ENV = "DELUGE_COMPANION_CONFIG"


def _config_dir() -> Path:
    """Dossier de configuration, que l'environnement peut imposer."""
    impose = (os.environ.get(CONFIG_ENV) or "").strip()
    if impose:
        return Path(impose).expanduser()
    return _base_dir() / APP_ORG


CONFIG_DIR: Path = _config_dir()
SETTINGS_PATH: Path = CONFIG_DIR / "settings.json"
DB_PATH: Path = CONFIG_DIR / "library.db"
LOG_PATH: Path = CONFIG_DIR / "app.log"
DEFAULT_BACKUP_DIR: Path = CONFIG_DIR / "backups"


def _default_work_dir() -> Path:
    """Copie de travail par défaut : sur la machine (1,4 Go n'ont rien à faire
    dans un profil itinérant), sauf configuration imposée."""
    if (os.environ.get(CONFIG_ENV) or "").strip():
        return CONFIG_DIR / "Carte"
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / APP_ORG / "Carte"
    return CONFIG_DIR / "Carte"


#: Où vit la copie de travail de la carte, sauf réglage contraire.
DEFAULT_WORK_DIR: Path = _default_work_dir()


def ensure_config_dir() -> Path:
    """Crée le dossier de configuration au besoin et le retourne."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        log.exception("Impossible de créer le dossier de configuration %s", CONFIG_DIR)
    return CONFIG_DIR


ensure_config_dir()


# ---------------------------------------------------------------------------
# Conversions tolérantes
# ---------------------------------------------------------------------------
_TRUE = {"1", "true", "vrai", "oui", "yes", "on"}
_FALSE = {"0", "false", "faux", "non", "no", "off", ""}


def _as_bool(value: Any, default: bool) -> bool:
    """Convertit n'importe quoi en booléen, sans jamais lever."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        low = value.strip().lower()
        if low in _TRUE:
            return True
        if low in _FALSE:
            return False
    return default


def _as_str(value: Any, default: str) -> str:
    """Convertit en chaîne (None -> défaut)."""
    if value is None:
        return default
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return default


def _as_opt_str(value: Any, default: str | None) -> str | None:
    """Convertit en chaîne ou None (chaîne vide -> None)."""
    if value is None:
        return None
    if isinstance(value, str):
        return value or None
    if isinstance(value, (int, float)):
        return str(value)
    return default


def _as_float(value: Any, default: float, lo: float, hi: float) -> float:
    """Convertit en flottant borné à [lo, hi]."""
    try:
        f = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    if f != f:  # NaN
        return default
    return max(lo, min(hi, f))


def _as_str_list(value: Any, default: list[str]) -> list[str]:
    """Convertit en liste de chaînes non vides, sans doublon, ordre conservé."""
    if isinstance(value, str):
        items: list[Any] = [value]
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        return list(default)
    out: list[str] = []
    seen: set[str] = set()
    for it in items:
        if not isinstance(it, str):
            continue
        s = it.strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def _as_color(value: Any, default: str) -> str:
    """Valide une couleur '#RRGGBB' (ou '#RGB'), sinon retourne le défaut."""
    s = _as_str(value, default).strip()
    if s.startswith("#") and len(s) in (4, 7):
        try:
            int(s[1:], 16)
        except ValueError:
            return default
        return s.upper() if len(s) == 7 else s
    return default


# ---------------------------------------------------------------------------
# Réglages
# ---------------------------------------------------------------------------
@dataclass
class Settings:
    """Préférences de l'utilisateur, sérialisées en JSON."""

    sd_path: str = ""
    recent_paths: list[str] = field(default_factory=list)
    audio_device: str | None = None
    autoplay: bool = True
    preview_volume: float = 0.8
    confirm_writes: bool = True
    always_backup_before_write: bool = True
    backup_dir: str = ""
    theme_accent: str = "#C79A22"
    language: str = "fr"
    scan_hash: bool = True
    scan_analyze: bool = False
    #: Au démarrage, relire les fichiers de la carte modifiés depuis la
    #: dernière analyse (0,2 s sur la carte de l'utilisateur). Sans cela,
    #: l'index gardait 125 références « manquantes » qu'une réparation
    #: faite depuis avait rétablies.
    index_on_start: bool = True

    # -- lien avec le Deluge branché --------------------------------------
    #: Nom du port de sortie MIDI, vide = chercher le Deluge tout seul.
    midi_out: str = ""
    #: Nom du port d'entrée MIDI, vide = chercher le Deluge tout seul.
    midi_in: str = ""
    #: Canal des notes et des contrôleurs (1..16).
    midi_channel: int = 1
    #: Se connecter dès que le Deluge apparaît.
    midi_autoconnect: bool = True
    #: Écouter **sur la machine** plutôt qu'avec le moteur approché.
    midi_audition: bool = False
    #: Les tempos des outils suivent celui du Deluge quand son horloge arrive.
    midi_follow_tempo: bool = True

    # -- la carte du Deluge ------------------------------------------------
    #: Copie de travail de la carte, tenue à son image par USB (firmware
    #: 1.3) ; vide = l'emplacement par défaut.
    work_dir: str = ""
    #: Sauvegarde complète de la carte : **lue, jamais écrite** — sauf par
    #: « Mettre à jour la sauvegarde », qui n'y supprime rien.
    card_backup: str = ""
    #: Synchroniser d'office la copie de travail quand le Deluge est branché.
    auto_sync: bool = True

    # -- sérialisation ----------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        """Dictionnaire JSON-sérialisable des réglages."""
        return {
            "sd_path": self.sd_path,
            "recent_paths": list(self.recent_paths),
            "audio_device": self.audio_device,
            "autoplay": bool(self.autoplay),
            "preview_volume": float(self.preview_volume),
            "confirm_writes": bool(self.confirm_writes),
            "always_backup_before_write": bool(self.always_backup_before_write),
            "backup_dir": self.backup_dir,
            "theme_accent": self.theme_accent,
            "language": self.language,
            "scan_hash": bool(self.scan_hash),
            "scan_analyze": bool(self.scan_analyze),
            "index_on_start": bool(self.index_on_start),
            "midi_out": self.midi_out,
            "midi_in": self.midi_in,
            "midi_channel": int(self.midi_channel),
            "midi_autoconnect": bool(self.midi_autoconnect),
            "midi_audition": bool(self.midi_audition),
            "midi_follow_tempo": bool(self.midi_follow_tempo),
            "work_dir": self.work_dir,
            "card_backup": self.card_backup,
            "auto_sync": bool(self.auto_sync),
        }

    @classmethod
    def from_dict(cls, data: Any) -> "Settings":
        """Construit des réglages depuis un dictionnaire quelconque.

        Les clés inconnues sont ignorées, les clés manquantes ou mal typées
        reprennent la valeur par défaut.
        """
        s = cls()
        if not isinstance(data, dict):
            if data is not None:
                log.warning("Réglages ignorés : format inattendu (%s)", type(data).__name__)
            return s
        known = {f.name for f in fields(cls)}
        unknown = [k for k in data if k not in known and not str(k).startswith("_")]
        if unknown:
            log.debug("Clés de réglages inconnues ignorées : %s",
                      ", ".join(sorted(str(k) for k in unknown)))
        g = data.get
        s.sd_path = _as_str(g("sd_path"), s.sd_path)
        s.recent_paths = _as_str_list(g("recent_paths"), s.recent_paths)
        s.audio_device = _as_opt_str(g("audio_device"), s.audio_device)
        s.autoplay = _as_bool(g("autoplay"), s.autoplay)
        s.preview_volume = _as_float(g("preview_volume"), s.preview_volume, 0.0, 1.0)
        s.confirm_writes = _as_bool(g("confirm_writes"), s.confirm_writes)
        s.always_backup_before_write = _as_bool(
            g("always_backup_before_write"), s.always_backup_before_write)
        s.backup_dir = _as_str(g("backup_dir"), s.backup_dir)
        s.theme_accent = _as_color(g("theme_accent"), s.theme_accent)
        s.language = normalize(_as_str(g("language"), s.language))
        s.scan_hash = _as_bool(g("scan_hash"), s.scan_hash)
        s.scan_analyze = _as_bool(g("scan_analyze"), s.scan_analyze)
        s.index_on_start = _as_bool(g("index_on_start"), s.index_on_start)
        s.midi_out = _as_str(g("midi_out"), s.midi_out)
        s.midi_in = _as_str(g("midi_in"), s.midi_in)
        s.midi_channel = int(_as_float(g("midi_channel"),
                                       float(s.midi_channel), 1.0, 16.0))
        s.midi_autoconnect = _as_bool(g("midi_autoconnect"),
                                      s.midi_autoconnect)
        s.midi_audition = _as_bool(g("midi_audition"), s.midi_audition)
        s.midi_follow_tempo = _as_bool(g("midi_follow_tempo"),
                                       s.midi_follow_tempo)
        s.work_dir = _as_str(g("work_dir"), s.work_dir)
        s.card_backup = _as_str(g("card_backup"), s.card_backup)
        s.auto_sync = _as_bool(g("auto_sync"), s.auto_sync)
        return s

    # -- confort ----------------------------------------------------------
    def add_recent(self, path: str | Path, limit: int = 10) -> None:
        """Place `path` en tête des chemins récents (sans doublon)."""
        p = str(path).strip()
        if not p:
            return
        low = p.lower()
        kept = [r for r in self.recent_paths if r.lower() != low]
        self.recent_paths = [p] + kept
        if limit > 0:
            del self.recent_paths[limit:]

    def backup_path(self) -> Path:
        """Dossier de sauvegarde effectif (défaut : %APPDATA%/…/backups)."""
        return Path(self.backup_dir) if self.backup_dir.strip() else DEFAULT_BACKUP_DIR

    def sd_root(self) -> Path | None:
        """Racine de la carte SD sous forme de `Path`, ou None si non réglée."""
        return Path(self.sd_path) if self.sd_path.strip() else None

    def work_path(self) -> Path:
        """Copie de travail de la carte."""
        return Path(self.work_dir) if self.work_dir.strip() else DEFAULT_WORK_DIR

    def card_backup_path(self) -> Path | None:
        """Sauvegarde de la carte, ou ``None``."""
        return Path(self.card_backup) if self.card_backup.strip() else None

    def adopt_card_roles(self) -> bool:
        """Reconnaît une ancienne carte de travail pour ce qu'elle est.

        Avant la copie de travail, l'application travaillait dans le dossier
        indiqué — chez l'utilisateur, la **sauvegarde** de sa carte. Un
        dossier qui n'est ni la racine d'un lecteur ni la copie de travail
        devient la sauvegarde. Rend ``True`` si un réglage a changé.
        """
        from .core.sdcard import is_drive_root

        if self.card_backup.strip() or not self.sd_path.strip():
            return False
        chemin = Path(self.sd_path)
        if is_drive_root(chemin) or same_folder(chemin, self.work_path()):
            return False
        self.card_backup = str(chemin)
        return True

    def card_role(self, root: Path | str | None) -> str:
        """``travail``, ``sauvegarde``, ``carte`` (un lecteur) ou ``dossier``."""
        from .core.sdcard import is_drive_root

        if root is None or not str(root).strip():
            return ""
        if same_folder(root, self.work_path()):
            return "travail"
        sauvegarde = self.card_backup_path()
        if sauvegarde is not None and same_folder(root, sauvegarde):
            return "sauvegarde"
        if is_drive_root(Path(root)):
            return "carte"
        return "dossier"

    def open_card(self, root: Path | str) -> "SDCard":
        """La carte à ``root``, en lecture seule si c'est la sauvegarde."""
        from .core.sdcard import SDCard

        if self.card_role(root) == "sauvegarde":
            return SDCard(Path(root), read_only=True,
                          read_only_reason=BACKUP_READ_ONLY)
        return SDCard(Path(root))


#: Ce qu'on dit quand une action voudrait écrire dans la sauvegarde.
BACKUP_READ_ONLY = N_(
    "Ce dossier est la sauvegarde de la carte : l'application le lit, elle "
    "n'y écrit jamais. Elle travaille sur la carte du Deluge, par sa copie "
    "de travail — Réglages ▸ Carte du Deluge.")


def same_folder(a: Path | str, b: Path | str) -> bool:
    """Même dossier, à la casse et aux séparateurs près."""
    try:
        return (os.path.normcase(os.path.abspath(str(a))).rstrip("\\/")
                == os.path.normcase(os.path.abspath(str(b))).rstrip("\\/"))
    except (TypeError, ValueError):
        return False


def load_settings() -> Settings:
    """Lit les réglages sur le disque ; valeurs par défaut en cas d'échec."""
    path = SETTINGS_PATH
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        log.info("Aucun fichier de réglages : valeurs par défaut (%s)", path)
        return Settings()
    except OSError:
        log.exception("Lecture des réglages impossible : %s", path)
        return Settings()
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        log.exception("Réglages illisibles (JSON invalide) : %s", path)
        return Settings()
    s = Settings.from_dict(data)
    log.debug("Réglages chargés depuis %s", path)
    return s


def save_settings(s: Settings) -> None:
    """Écrit les réglages (atomique : fichier temporaire + remplacement)."""
    ensure_config_dir()
    try:
        payload = json.dumps(s.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
    except (TypeError, ValueError):
        log.exception("Réglages non sérialisables")
        return
    tmp_name = ""
    try:
        fd, tmp_name = tempfile.mkstemp(prefix="settings-", suffix=".tmp", dir=str(CONFIG_DIR))
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(payload)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, SETTINGS_PATH)
        tmp_name = ""
        log.debug("Réglages enregistrés dans %s", SETTINGS_PATH)
    except OSError:
        log.exception("Enregistrement des réglages impossible : %s", SETTINGS_PATH)
    finally:
        if tmp_name:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Contexte applicatif
# ---------------------------------------------------------------------------
_NO_CARD_TITLE = N_("Carte SD introuvable")
_NO_CARD_TEXT = N_(
    "Aucune carte SD Deluge valide n'est sélectionnée.\n\n"
    "Ouvrez « Réglages » pour indiquer le dossier de la carte, ou lancez la "
    "détection automatique des lecteurs amovibles."
)


@dataclass
class AppContext:
    """Objets partagés par toutes les pages de l'interface.

    Vit dans `config.py` (et non dans l'UI) pour éviter tout import circulaire :
    les types `SDCard`, `Library` et `Player` ne sont résolus qu'à l'analyse
    statique.
    """

    settings: Settings
    sd: "SDCard | None" = None
    lib: "Library" = None  # type: ignore[assignment]
    player: "Player" = None  # type: ignore[assignment]
    #: Lien MIDI avec le Deluge branché. ``None`` tant que personne ne l'a
    #: demandé : ouvrir un port a un coût, et l'application doit démarrer
    #: aussi vite sans machine qu'avec.
    link: Any = None
    #: Vrai une fois ``close()`` appelé. L'interface s'en sert pour ne pas
    #: interroger une base déjà fermée : un travail lancé dans un fil rend
    #: son résultat par un signal **mis en file**, qui peut arriver après la
    #: fermeture de la fenêtre. Cf. ``Page.guard``.
    closed: bool = False

    # -- carte SD ---------------------------------------------------------
    @property
    def has_card(self) -> bool:
        """Vrai si une carte SD valide est disponible."""
        sd = self.sd
        if sd is None:
            return False
        try:
            return bool(sd.is_valid())
        except Exception:  # pragma: no cover - carte retirée, lecteur absent…
            log.exception("Validation de la carte SD impossible")
            return False

    def ensure_link(self):
        """Le lien MIDI avec le Deluge, créé au premier besoin.

        Créer l'objet n'ouvre aucun port : il se contente de lire la carte
        MIDI Follow de la carte SD. C'est la connexion qui ouvre, et elle est
        toujours demandée explicitement — par les réglages, ou par la
        reconnexion automatique quand la machine apparaît.
        """
        if self.link is None:
            from delugeapp.core.delugelink import DelugeLink

            lien = DelugeLink()
            lien.set_channel(getattr(self.settings, "midi_channel", 1))
            lien.load_follow_map(self.sd)
            self.link = lien
        return self.link

    @property
    def link_connected(self) -> bool:
        """Vrai si un port MIDI est ouvert. Ne crée rien."""
        return bool(self.link is not None and self.link.is_connected)

    def sd_or_warn(self, parent: Any = None,
                   write: bool = False) -> "SDCard | None":
        """Retourne la carte SD, ou affiche un avertissement et retourne None.

        ``write=True`` : l'action va écrire. Une carte en lecture seule — la
        sauvegarde de la carte — est alors refusée, avec sa raison.
        """
        if self.has_card:
            if not (write and getattr(self.sd, "read_only", False)):
                return self.sd
            raison = tr(getattr(self.sd, "read_only_reason", "")
                        or N_("Cet emplacement est en lecture seule."))
            log.info("Écriture refusée : %s", raison)
            self._inform(parent, tr("Rien n'est écrit ici"), raison)
            return None
        log.warning("Action refusée : carte SD absente ou invalide (%s)",
                    self.settings.sd_path or "aucun chemin")
        try:
            # Import local : `config` ne dépend pas de Qt au niveau du module.
            from PyQt6.QtWidgets import QApplication, QMessageBox
        except ImportError:  # pragma: no cover - sans interface graphique
            return None
        if QApplication.instance() is None:
            # Sans QApplication, construire un QMessageBox ferait avorter le processus.
            return None
        try:
            QMessageBox.warning(parent, tr(_NO_CARD_TITLE), tr(_NO_CARD_TEXT))
        except Exception:  # pragma: no cover - pas de QApplication
            log.exception("Affichage de l'avertissement « carte SD » impossible")
        return None

    @staticmethod
    def _inform(parent: Any, titre: str, texte: str) -> None:
        try:
            from PyQt6.QtWidgets import QApplication, QMessageBox
        except ImportError:  # pragma: no cover - sans interface graphique
            return
        if QApplication.instance() is None:
            return
        try:
            QMessageBox.information(parent, titre, texte)
        except Exception:  # pragma: no cover
            log.exception("Affichage d'une information impossible")

    # -- confort ----------------------------------------------------------
    def save(self) -> None:
        """Enregistre les réglages courants."""
        save_settings(self.settings)

    def close(self) -> None:
        """Libère proprement les ressources (lecteur audio, base de données)."""
        self.closed = True
        player = getattr(self, "player", None)
        stop = getattr(player, "stop", None)
        if callable(stop):
            try:
                stop()
            except Exception:
                log.exception("Arrêt du lecteur audio impossible")
        for name in ("link", "player", "lib"):
            obj = getattr(self, name, None)
            close = getattr(obj, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    log.exception("Fermeture de %s impossible", name)
