# -*- coding: utf-8 -*-
"""Sauvegarde et restauration de la carte.

Une carte de Deluge contient des mois de travail dans des fichiers XML de
quelques kilooctets. Les échantillons, eux, pèsent plus d'un gigaoctet mais
proviennent le plus souvent de banques qu'on peut retélécharger. D'où le choix
par défaut de ce module : **sauvegarder les morceaux, presets et kits sans les
échantillons** (``include_samples=False``), ce qui prend moins d'une seconde et
quelques mégaoctets, et peut donc être fait souvent.

Chaque sauvegarde est un dossier daté contenant l'arborescence telle quelle,
plus un manifeste :file:`backup.json`. Rien n'est compressé par défaut : un
dossier se parcourt et se restaure partiellement, une archive non.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from .sdcard import (
    AUDIO_EXT,
    STD_DIRS,
    SDCard,
    _is_ignored_dir,
    _is_ignored_file,
    norm_rel,
    safe_deluge_name,
)

log = logging.getLogger(__name__)

#: Nom du manifeste déposé dans chaque sauvegarde.
MANIFEST = "backup.json"

#: Format du dossier de sauvegarde : tri alphabétique = tri chronologique.
STAMP_FORMAT = "%Y-%m-%d_%Hh%M"

#: Extensions des fichiers de configuration à sauvegarder avec les XML.
CONFIG_EXT = (".xml",)

#: Fichiers de réglages présents à la racine de la carte.
ROOT_FILES = ("CommunityFeatures.XML", "MIDIFollow.XML", "SETTINGS.XML")


@dataclass
class BackupInfo:
    """Une sauvegarde existante."""

    path: Path
    when: datetime
    files: int = 0
    bytes: int = 0
    label: str = ""
    include_samples: bool = False
    zipped: bool = False
    source: str = ""

    @property
    def name(self) -> str:
        """Nom affichable : date et libellé."""
        stamp = self.when.strftime("%d/%m/%Y à %Hh%M")
        return f"{stamp} — {self.label}" if self.label else stamp

    def summary(self) -> str:
        """Résumé en une ligne."""
        kind = "avec échantillons" if self.include_samples else "sans échantillons"
        size = (f"{self.bytes / 2 ** 30:.2f} Gio" if self.bytes >= 2 ** 30
                else f"{self.bytes / 2 ** 20:.1f} Mio")
        return f"{self.name} — {self.files} fichiers, {size} ({kind})"


def _manifest_path(folder: Path) -> Path:
    return folder / MANIFEST


def _write_manifest(folder: Path, info: BackupInfo) -> None:
    """Dépose le manifeste décrivant la sauvegarde."""
    data = {
        "when": info.when.isoformat(timespec="seconds"),
        "label": info.label,
        "files": info.files,
        "bytes": info.bytes,
        "include_samples": info.include_samples,
        "zipped": info.zipped,
        "source": info.source,
    }
    try:
        _manifest_path(folder).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        log.warning("manifeste non écrit dans %s : %s", folder, exc)


def _read_manifest(folder: Path) -> BackupInfo | None:
    """Lit le manifeste d'un dossier de sauvegarde, ou le reconstitue."""
    path = _manifest_path(folder)
    when = datetime.fromtimestamp(folder.stat().st_mtime)
    info = BackupInfo(path=folder, when=when)
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            info.when = datetime.fromisoformat(data.get("when", when.isoformat()))
            info.label = str(data.get("label", ""))
            info.files = int(data.get("files", 0))
            info.bytes = int(data.get("bytes", 0))
            info.include_samples = bool(data.get("include_samples", False))
            info.zipped = bool(data.get("zipped", False))
            info.source = str(data.get("source", ""))
            return info
        except (OSError, ValueError, TypeError) as exc:
            log.debug("manifeste illisible dans %s : %s", folder, exc)
    # Pas de manifeste (sauvegarde faite à la main ?) : on mesure.
    files = 0
    size = 0
    try:
        for p in folder.rglob("*"):
            if p.is_file():
                files += 1
                size += p.stat().st_size
    except OSError:
        pass
    info.files, info.bytes = files, size
    info.include_samples = (folder / "SAMPLES").is_dir()
    return info


def list_backups(backup_dir: Path) -> list[BackupInfo]:
    """Sauvegardes présentes dans ``backup_dir``, la plus récente d'abord."""
    base = Path(backup_dir)
    out: list[BackupInfo] = []
    if not base.is_dir():
        return out
    try:
        entries = list(os.scandir(base))
    except OSError as exc:
        log.debug("dossier de sauvegarde illisible %s : %s", base, exc)
        return out

    for entry in entries:
        path = Path(entry.path)
        try:
            if entry.is_dir():
                info = _read_manifest(path)
                if info is not None:
                    out.append(info)
            elif entry.is_file() and path.suffix.lower() == ".zip":
                out.append(_read_zip_info(path))
        except OSError as exc:
            log.debug("sauvegarde illisible %s : %s", path, exc)
    out.sort(key=lambda i: i.when, reverse=True)
    return out


def _read_zip_info(path: Path) -> BackupInfo:
    """Description d'une archive, d'après le manifeste qu'elle contient.

    Sans lui, le libellé devenait le nom du fichier et une archive faite
    *avec* les échantillons passait pour une archive sans : la comparer à la
    carte déclarait alors chaque échantillon « supprimé ».
    """
    stat = path.stat()
    info = BackupInfo(path=path, when=datetime.fromtimestamp(stat.st_mtime),
                      files=_zip_count(path), bytes=stat.st_size,
                      label=path.stem, zipped=True)
    try:
        with zipfile.ZipFile(path) as zf:
            data = json.loads(zf.read(MANIFEST).decode("utf-8"))
        info.when = datetime.fromisoformat(data.get("when", info.when.isoformat()))
        info.label = str(data.get("label", ""))
        info.include_samples = bool(data.get("include_samples", False))
        info.source = str(data.get("source", ""))
        # Le manifeste compte les fichiers copiés, sans lui-même.
        info.files = int(data.get("files", info.files))
    except (OSError, KeyError, ValueError, TypeError, zipfile.BadZipFile) as exc:
        log.debug("manifeste absent ou illisible dans %s : %s", path, exc)
    return info


def _zip_count(path: Path) -> int:
    """Nombre d'entrées d'une archive, 0 si elle est illisible."""
    try:
        with zipfile.ZipFile(path) as zf:
            return len(zf.namelist())
    except (OSError, zipfile.BadZipFile):
        return 0


def _files_to_backup(sd: SDCard, include_samples: bool) -> list[Path]:
    """Fichiers à sauvegarder, parasites écartés."""
    out: list[Path] = []
    for top in STD_DIRS:
        if top == "SAMPLES" and not include_samples:
            continue
        base = sd.abs(top)
        if not base.is_dir():
            continue
        try:
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = [d for d in dirnames if not _is_ignored_dir(d)]
                for name in filenames:
                    if _is_ignored_file(name):
                        continue
                    if top == "SAMPLES":
                        if not name.lower().endswith(AUDIO_EXT):
                            continue
                    elif not name.lower().endswith(CONFIG_EXT):
                        continue
                    out.append(Path(dirpath) / name)
        except OSError as exc:
            log.debug("parcours de %s impossible : %s", base, exc)

    # Réglages de la racine : petits mais précieux.
    for name in ROOT_FILES:
        candidate = sd.resolve_sample(name)
        if candidate is not None and candidate.is_file():
            out.append(candidate)
    return out


def create_backup(sd: SDCard, backup_dir: Path, label: str = "",
                  include_samples: bool = False, zip_it: bool = False,
                  progress: Callable[[str], None] | None = None,
                  should_stop: Callable[[], bool] | None = None,
                  ) -> BackupInfo:
    """Sauvegarde la carte dans un sous-dossier daté de ``backup_dir``.

    :param include_samples: ``False`` par défaut — seuls les morceaux,
        presets, kits et réglages sont copiés. C'est ce qui permet de
        sauvegarder souvent : quelques mégaoctets au lieu de plusieurs
        gigaoctets.
    :param zip_it: regroupe la sauvegarde en une archive ``.zip``.
    :param should_stop: interrompt la copie ; la sauvegarde partielle est
        alors **supprimée**, pour ne pas laisser croire à une sauvegarde
        complète.

    Ne lève pas pour un fichier illisible : il est simplement omis et
    journalisé. Lève ``OSError`` si le dossier de destination est inutilisable.
    """
    base = Path(backup_dir)
    # Dans SAMPLES, SYNTHS, KITS ou SONGS, la sauvegarde se recopierait
    # elle-même en cours de route, et le Deluge listerait ses copies comme
    # des presets et des morceaux.
    for top in STD_DIRS:
        dossier = sd.abs(top)
        try:
            base.resolve().relative_to(dossier.resolve())
        except (ValueError, OSError):
            continue
        raise OSError("le dossier de sauvegarde est dans %s, sur la carte "
                      "elle-même : choisissez-en un autre" % top)
    base.mkdir(parents=True, exist_ok=True)

    when = datetime.now()
    stamp = when.strftime(STAMP_FORMAT)
    suffix = f"_{safe_deluge_name(label)}" if label else ""
    folder = base / f"{stamp}{suffix}"
    index = 2
    while folder.exists():
        folder = base / f"{stamp}{suffix} ({index})"
        index += 1
    folder.mkdir(parents=True)

    def _report(text: str) -> None:
        if progress is not None:
            try:
                progress(text)
            except Exception:  # noqa: BLE001
                pass

    _report("Inventaire des fichiers à sauvegarder…")
    files = _files_to_backup(sd, include_samples)
    copied = 0
    total = 0
    interrupted = False

    for i, src in enumerate(files, 1):
        if should_stop is not None and should_stop():
            interrupted = True
            break
        rel = sd.rel(src)
        dst = folder / rel
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied += 1
            total += dst.stat().st_size
        except (OSError, shutil.Error) as exc:
            log.warning("fichier non sauvegardé %s : %s", rel, exc)
        if i % 50 == 0 or i == len(files):
            _report(f"Sauvegarde — {i}/{len(files)} fichiers")

    info = BackupInfo(path=folder, when=when, files=copied, bytes=total,
                      label=label, include_samples=include_samples,
                      source=str(sd.root))

    if interrupted:
        log.info("sauvegarde interrompue : le dossier partiel est supprimé")
        shutil.rmtree(folder, ignore_errors=True)
        info.path = folder
        info.files = 0
        info.bytes = 0
        return info

    _write_manifest(folder, info)

    if zip_it:
        _report("Compression…")
        archive = folder.with_suffix(".zip")
        try:
            # ``strict_timestamps=False`` est indispensable : le format ZIP ne
            # sait pas représenter une date antérieure à 1980, et deux presets
            # de la carte d'essai sont datés du 31/12/1979. Sans cela, toute la
            # compression échouait à cause de deux fichiers.
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED,
                                 strict_timestamps=False) as zf:
                for p in sorted(folder.rglob("*")):
                    if p.is_file():
                        zf.write(p, p.relative_to(folder).as_posix())
            shutil.rmtree(folder, ignore_errors=True)
            info.path = archive
            info.zipped = True
            info.bytes = archive.stat().st_size
        except (OSError, zipfile.BadZipFile) as exc:
            log.error("compression impossible : %s", exc)
            # Le dossier reste la sauvegarde ; une archive tronquée à côté de
            # lui passerait pour une seconde sauvegarde.
            try:
                archive.unlink()
            except OSError:
                pass

    log.info("sauvegarde créée : %s", info.summary())
    return info


def _backup_files(info: BackupInfo) -> dict[str, Path | str]:
    """``{chemin relatif: source}`` du contenu d'une sauvegarde.

    Pour une archive, la valeur est le nom de l'entrée dans le zip.
    """
    out: dict[str, Path | str] = {}
    if info.zipped:
        try:
            with zipfile.ZipFile(info.path) as zf:
                for name in zf.namelist():
                    if name.endswith("/") or name == MANIFEST:
                        continue
                    out[name.replace("\\", "/")] = name
        except (OSError, zipfile.BadZipFile) as exc:
            log.error("archive illisible %s : %s", info.path, exc)
        return out

    try:
        for p in info.path.rglob("*"):
            if p.is_file() and p.name != MANIFEST:
                out[p.relative_to(info.path).as_posix()] = p
    except OSError as exc:
        log.error("sauvegarde illisible %s : %s", info.path, exc)
    return out


def restore_backup(info: BackupInfo, sd: SDCard,
                   progress: Callable[[str], None] | None = None,
                   apply: bool = True,
                   safety_dir: Path | None = None) -> tuple[int, list[str]]:
    """Recopie une sauvegarde sur la carte.

    **Écrase les fichiers de la carte** par ceux de la sauvegarde : c'est la
    raison d'être d'une restauration, et l'appelant doit avoir fait confirmer.
    Les fichiers identiques sont ignorés, ce qui rend l'opération rapide et
    limite l'usure de la carte.

    :param apply: ``False`` compte ce qui serait restauré sans rien écrire.
    :param safety_dir: dossier des sauvegardes. S'il est donné, chaque
        fichier de la carte **sur le point d'être écrasé** y est d'abord
        copié, dans une sauvegarde « avant restauration » qui se restaure
        comme les autres. Sans elle, restaurer par erreur une vieille
        sauvegarde effaçait tout le travail fait depuis. Un fichier qu'on
        n'a pas pu mettre à l'abri n'est pas écrasé.
    :returns: ``(fichiers restaurés, erreurs)``.
    """
    if apply:
        sd.require_writable()
    errors: list[str] = []
    restored = 0
    files = _backup_files(info)
    if not files:
        return 0, [f"Sauvegarde vide ou illisible : {info.path}"]

    def _report(text: str) -> None:
        if progress is not None:
            try:
                progress(text)
            except Exception:  # noqa: BLE001
                pass

    archive: zipfile.ZipFile | None = None
    if info.zipped:
        try:
            archive = zipfile.ZipFile(info.path)
        except (OSError, zipfile.BadZipFile) as exc:
            return 0, [f"Archive illisible : {exc}"]

    abri: Path | None = None
    abrites = 0
    abrites_octets = 0

    def _mettre_a_l_abri(dst: Path, rel: str) -> bool:
        """Copie le fichier actuel avant de l'écraser. Faux si impossible."""
        nonlocal abri, abrites, abrites_octets
        if safety_dir is None or not dst.is_file():
            return True
        try:
            if abri is None:
                base = Path(safety_dir)
                stamp = datetime.now().strftime(STAMP_FORMAT)
                abri = base / f"{stamp}_avant restauration"
                index = 2
                while abri.exists():
                    abri = base / f"{stamp}_avant restauration ({index})"
                    index += 1
                abri.mkdir(parents=True)
            copie = abri / rel
            copie.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dst, copie)
            abrites += 1
            abrites_octets += copie.stat().st_size
            return True
        except (OSError, shutil.Error) as exc:
            errors.append(f"{rel} : copie de sécurité impossible ({exc}), "
                          f"fichier laissé tel quel")
            return False

    try:
        for i, (rel, source) in enumerate(sorted(files.items()), 1):
            if ".." in rel.replace("\\", "/").split("/") or ":" in rel:
                errors.append(f"{rel} : chemin hors de la carte, ignoré")
                continue
            dst = sd.abs(rel)
            try:
                if archive is not None:
                    data = archive.read(str(source))
                    if dst.is_file() and dst.read_bytes() == data:
                        continue
                    if apply:
                        if not _mettre_a_l_abri(dst, rel):
                            continue
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        dst.write_bytes(data)
                else:
                    src = Path(source)
                    if (dst.is_file()
                            and dst.stat().st_size == src.stat().st_size
                            and dst.read_bytes() == src.read_bytes()):
                        continue
                    if apply:
                        if not _mettre_a_l_abri(dst, rel):
                            continue
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dst)
                restored += 1
            except (OSError, shutil.Error, zipfile.BadZipFile) as exc:
                errors.append(f"{rel} : {exc}")
            if i % 50 == 0:
                _report(f"Restauration — {i}/{len(files)}")
    finally:
        if archive is not None:
            archive.close()
        if abri is not None:
            _write_manifest(abri, BackupInfo(
                path=abri, when=datetime.now(), files=abrites,
                bytes=abrites_octets, label="avant restauration",
                include_samples=(abri / "SAMPLES").is_dir(),
                source=str(sd.root)))

    if apply:
        sd.invalidate_cache()
    log.info("restauration : %d fichier(s)%s, %d erreur(s)", restored,
             "" if apply else " (simulation)", len(errors))
    return restored, errors


def diff_backup(info: BackupInfo, sd: SDCard) -> dict:
    """Compare une sauvegarde à l'état actuel de la carte.

    :returns: ``{'added': […], 'removed': […], 'changed': […],
        'unchanged': n}`` où *added* désigne ce qui est **sur la carte mais
        pas dans la sauvegarde**, et *removed* ce qui est dans la sauvegarde
        mais plus sur la carte.
    """
    out: dict = {"added": [], "removed": [], "changed": [], "unchanged": 0}
    backup = _backup_files(info)
    if not backup:
        return out

    current = {sd.rel(p): p
               for p in _files_to_backup(sd, info.include_samples)}
    current_norm = {norm_rel(k): k for k in current}

    archive: zipfile.ZipFile | None = None
    if info.zipped:
        try:
            archive = zipfile.ZipFile(info.path)
        except (OSError, zipfile.BadZipFile) as exc:
            log.error("archive illisible : %s", exc)
            return out

    try:
        for rel, source in backup.items():
            key = current_norm.get(norm_rel(rel))
            if key is None:
                out["removed"].append(rel)
                continue
            live = current[key]
            try:
                if archive is not None:
                    same = live.read_bytes() == archive.read(str(source))
                else:
                    src = Path(source)
                    same = (live.stat().st_size == src.stat().st_size
                            and live.read_bytes() == src.read_bytes())
            except OSError as exc:
                log.debug("comparaison impossible pour %s : %s", rel, exc)
                continue
            if same:
                out["unchanged"] += 1
            else:
                out["changed"].append(rel)

        backup_norm = {norm_rel(k) for k in backup}
        for rel in current:
            if norm_rel(rel) not in backup_norm:
                out["added"].append(rel)
    finally:
        if archive is not None:
            archive.close()

    for key in ("added", "removed", "changed"):
        out[key].sort()
    return out


def delete_backup(info: BackupInfo) -> bool:
    """Supprime une sauvegarde. Retourne vrai si elle a bien disparu."""
    try:
        if info.path.is_dir():
            shutil.rmtree(info.path)
        elif info.path.exists():
            info.path.unlink()
        return not info.path.exists()
    except OSError as exc:
        log.error("suppression de la sauvegarde %s impossible : %s",
                  info.path, exc)
        return False


def snapshot_xml(path: Path) -> Path:
    """Copie horodatée d'un seul fichier, à côté de lui.

    C'est le filet de sécurité d'une modification ponctuelle, indépendant des
    sauvegardes complètes. Le nom porte la date à la seconde, ce qui évite
    d'écraser une copie précédente.
    """
    src = Path(path)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = src.with_suffix(src.suffix + f".{stamp}.bak")
    index = 2
    while dst.exists():
        dst = src.with_suffix(src.suffix + f".{stamp}-{index}.bak")
        index += 1
    try:
        shutil.copy2(src, dst)
    except (OSError, shutil.Error) as exc:
        log.error("copie de sécurité de %s impossible : %s", src, exc)
        raise
    return dst
