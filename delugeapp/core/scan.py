# -*- coding: utf-8 -*-
"""Analyse de la carte SD et remplissage de l'index.

C'est le point de passage obligé entre la carte et le reste de l'application.
Trois exigences gouvernent ce module (cf. SPEC §4.9 et §6.2) :

* **ne jamais lever** — un fichier illisible devient une ligne ``ok=0`` avec son
  message d'erreur, et l'analyse continue ;
* **rester interruptible** — ``should_stop`` est consulté à chaque fichier ;
* **rester rapide** — les en-têtes audio sont lus seuls (pas les données), les
  empreintes sont calculées sur 128 Kio au lieu du fichier entier, et le mode
  incrémental saute tout ce dont la taille et la date n'ont pas changé.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import wav
from .db import Library
from .model import Kit, Song, SynthPreset
from .sdcard import SDCard, norm_rel

log = logging.getLogger(__name__)

#: Taille des blocs lus en tête et en queue pour une empreinte rapide.
HASH_CHUNK = 64 * 1024

#: Durée minimale pour qu'une détection de tempo ait un sens : en dessous,
#: l'échantillon ne contient pas assez de temps pour qu'une période se dégage.
MIN_BPM_SECONDS = 4.0

#: Seuils de confiance au-dessous desquels la mesure n'est pas enregistrée.
MIN_BPM_CONFIDENCE = 0.4
MIN_KEY_CONFIDENCE = 0.35


@dataclass
class ScanProgress:
    """Avancement transmis à l'interface pendant l'analyse."""

    phase: str = ""
    current: int = 0
    total: int = 0
    message: str = ""


@dataclass
class ScanResult:
    """Bilan d'une analyse."""

    samples: int = 0
    presets: int = 0
    kits: int = 0
    songs: int = 0
    errors: list[str] = field(default_factory=list)
    seconds: float = 0.0
    stopped: bool = False
    skipped: int = 0

    def summary(self) -> str:
        """Phrase de bilan, affichable dans la barre d'état."""
        parts = [
            f"{self.samples} échantillons",
            f"{self.presets} presets",
            f"{self.kits} kits",
            f"{self.songs} morceaux",
        ]
        text = "Analyse terminée : " + ", ".join(parts)
        if self.skipped:
            text += f" ({self.skipped} inchangés)"
        text += f" en {self.seconds:.1f} s"
        if self.errors:
            text += f" — {len(self.errors)} erreur(s)"
        if self.stopped:
            text = "Analyse interrompue : " + ", ".join(parts)
        return text


def file_hash(path: Path, quick: bool = True) -> str:
    """Empreinte SHA-1 d'un fichier.

    ``quick=True`` (défaut) : empreinte de la taille, puis de 64 Kio pris en
    tête, au milieu et en queue. C'est le seul moyen de repérer des doublons
    sur une carte de plusieurs gigaoctets en un temps acceptable.

    **Une empreinte rapide ne prouve rien.** Mesuré sur cette carte : les
    fichiers ``SAMPLES/Artists/Danny Taurus/MoDrama/Upper{01,14,20}.wav`` ont
    la même taille et les mêmes 64 Kio de tête et de queue (du silence) alors
    qu'ils diffèrent sur 1 407 blocs de 1 Kio. Le bloc du milieu les
    départage, mais rien ne garantit qu'un autre jeu de multi-échantillons ne
    tromperait pas la mesure à son tour. Tout ce qui est présenté à
    l'utilisateur comme un doublon doit donc passer par
    :func:`confirm_duplicates`, qui compare les fichiers en entier.
    """
    h = hashlib.sha1()
    try:
        size = path.stat().st_size
        h.update(str(size).encode("ascii"))
        with open(path, "rb") as fp:
            if not quick or size <= 3 * HASH_CHUNK:
                for block in iter(lambda: fp.read(1024 * 1024), b""):
                    h.update(block)
            else:
                h.update(fp.read(HASH_CHUNK))
                fp.seek((size - HASH_CHUNK) // 2)
                h.update(fp.read(HASH_CHUNK))
                fp.seek(-HASH_CHUNK, 2)
                h.update(fp.read(HASH_CHUNK))
    except OSError as exc:
        log.debug("empreinte impossible pour %s : %s", path, exc)
        return ""
    return h.hexdigest()


def confirm_duplicates(sd: SDCard, lib: Library,
                       progress: Callable[[ScanProgress], None] | None = None,
                       should_stop: Callable[[], bool] | None = None,
                       ) -> list[list[str]]:
    """Confirme les doublons par une empreinte **complète**.

    Ne lit en entier que les fichiers des groupes déjà soupçonnés par
    l'empreinte rapide — en pratique une poignée, pas toute la carte. Les
    empreintes obtenues sont enregistrées, après quoi
    :meth:`Library.duplicates` ne renvoie plus que des groupes réellement
    identiques.

    Retourne les groupes confirmés, sous forme de listes de chemins relatifs.
    """
    candidates = lib.duplicate_candidates()
    files = [row["rel"] for group in candidates for row in group]
    total = len(files)
    if not total:
        _emit(progress, "dupes", 0, 0, "Aucun doublon soupçonné")
        return []

    _emit(progress, "dupes", 0, total,
          f"Vérification de {total} fichiers soupçonnés en double…")
    digests: dict[str, str] = {}
    lib.begin()
    for i, rel in enumerate(files, 1):
        if should_stop is not None and should_stop():
            lib.commit()
            return []
        path = sd.resolve_sample(rel)
        if path is None:
            continue
        digest = file_hash(path, quick=False)
        if digest:
            digests[rel] = digest
            lib.set_full_hash(rel, digest)
        if i % 10 == 0:
            _emit(progress, "dupes", i, total, f"Vérification — {Path(rel).name}")
    lib.commit()
    _emit(progress, "dupes", total, total, "Doublons vérifiés")

    confirmed: dict[str, list[str]] = {}
    for rel, digest in digests.items():
        confirmed.setdefault(digest, []).append(rel)
    groups = [sorted(rels) for rels in confirmed.values() if len(rels) > 1]
    rejected = len(candidates) - len(groups)
    if rejected > 0:
        log.info("%d groupe(s) soupçonné(s) écarté(s) après comparaison "
                 "complète : l'empreinte rapide s'était trompée", rejected)
    return groups


def _emit(progress: Callable[[ScanProgress], None] | None, phase: str,
          current: int, total: int, message: str) -> None:
    """Transmet l'avancement sans jamais laisser l'affichage casser l'analyse."""
    if progress is None:
        return
    try:
        progress(ScanProgress(phase, current, total, message))
    except Exception as exc:  # noqa: BLE001 - l'affichage ne doit rien interrompre
        log.debug("rapport d'avancement en échec : %s", exc)


def _unchanged(known: dict[str, tuple[int, float]], rel: str,
               stat_result) -> bool:
    """Vrai si taille et date de modification sont inchangées depuis l'index."""
    prev = known.get(rel)
    if prev is None:
        return False
    size, mtime = prev
    return size == stat_result.st_size and abs(mtime - stat_result.st_mtime) < 1e-6


# --------------------------------------------------------------------------- #
# Échantillons
# --------------------------------------------------------------------------- #

def _scan_samples(sd: SDCard, lib: Library, paths: list[Path], *,
                  compute_hash: bool, analyze: bool, full: bool,
                  result: ScanResult,
                  progress: Callable[[ScanProgress], None] | None,
                  should_stop: Callable[[], bool] | None) -> bool:
    """Indexe les échantillons. Retourne ``False`` si l'analyse est interrompue."""
    known = {} if full else lib.known_files("sample")
    total = len(paths)
    lib.begin()
    for i, path in enumerate(paths, 1):
        if should_stop is not None and should_stop():
            lib.commit()
            return False
        rel = sd.rel(path)
        try:
            st = path.stat()
        except OSError as exc:
            result.errors.append(f"{rel} : {exc}")
            continue

        if not full and _unchanged(known, rel, st):
            result.skipped += 1
            result.samples += 1
            if i % 200 == 0:
                _emit(progress, "samples", i, total, f"Échantillons — {path.name}")
            continue

        row: dict = {
            "rel": rel,
            "name": path.stem,
            "folder": str(Path(rel).parent).replace("\\", "/"),
            "ext": path.suffix.lower().lstrip("."),
            "size": st.st_size,
            "mtime": st.st_mtime,
            "category": _sample_category(rel),
            "ok": 1,
            "error": "",
        }

        info = wav.probe(path)
        if info.ok:
            row.update({
                "sr": info.sample_rate,
                "channels": info.channels,
                "bit_depth": info.bit_depth,
                "frames": info.frames,
                "duration": info.duration,
            })
        else:
            row.update({"ok": 0, "error": info.error})
            result.errors.append(f"{rel} : {info.error}")

        # Le fichier a changé (ou n'était pas indexé) : ses empreintes
        # anciennes ne valent plus rien. Gardée, l'empreinte complète le
        # déclarait encore identique à son ancien jumeau, et la déduplication
        # proposait de supprimer un fichier devenu différent.
        row["hash_full"] = ""
        row["hash"] = file_hash(path, quick=True) if compute_hash else ""

        if analyze and info.ok and info.frames > 0:
            row.update(_analyze_sample(path, result, rel))

        lib.upsert_sample(row)
        result.samples += 1

        if i % 50 == 0:
            lib.commit()
            lib.begin()
            _emit(progress, "samples", i, total, f"Échantillons — {path.name}")
    lib.commit()
    _emit(progress, "samples", total, total, "Échantillons analysés")
    return True


def _analyze_sample(path: Path, result: ScanResult, rel: str) -> dict:
    """Mesures acoustiques d'un échantillon (coûteux : option ``analyze``).

    ``analysis`` n'est pas encore écrit à ce stade du projet : on se limite
    donc aux mesures que ``wav`` permet déjà, et l'import est protégé pour que
    l'arrivée du module enrichisse automatiquement l'analyse.
    """
    out: dict = {}
    try:
        data, sr = wav.read(path, max_frames=sr_limit(), mono=True)
    except Exception as exc:  # noqa: BLE001 - un échantillon abîmé ne bloque rien
        result.errors.append(f"{rel} : analyse impossible ({exc})")
        return out
    if data.size == 0:
        return out

    import numpy as np

    out["peak"] = float(np.max(np.abs(data)))
    out["rms"] = float(np.sqrt(np.mean(np.square(data, dtype=np.float64))))

    try:
        from . import analysis  # noqa: PLC0415 - optionnel tant que non écrit
    except ImportError:
        return out

    # Offset continu et écrêtage : ce sont les deux défauts qu'un producteur
    # veut connaître avant de charger l'échantillon dans un morceau. La page
    # Santé les lit ensuite dans l'index, sans relire la carte.
    try:
        levels = analysis.loudness(data)
        out["dc_offset"] = levels["dc_offset"]
        out["clipped"] = levels["clipped"]
        out["crest"] = levels["crest"]
    except Exception as exc:  # noqa: BLE001
        log.debug("mesure de niveau de %s en échec : %s", rel, exc)

    # Descripteurs spectraux : ils tiennent en huit nombres et permettent de
    # chercher un son par ressemblance sans relire la carte. Les calculer
    # ici ne coûte presque rien — le fichier est déjà décodé en mémoire —
    # alors que les recalculer à la demande imposerait de tout relire.
    try:
        spec = analysis.spectral(data, sr)
        out["centroid"] = spec["centroid"]
        out["rolloff"] = spec["rolloff85"]
        out["flatness"] = spec["flatness"]
        out["bandwidth"] = spec["bandwidth"]
        out["low_ratio"] = spec["low_ratio"]
        out["high_ratio"] = spec["high_ratio"]
        out["attack"] = round(analysis.attack_time(data, sr), 5)
    except Exception as exc:  # noqa: BLE001
        log.debug("descripteurs spectraux de %s en échec : %s", rel, exc)
    try:
        # Le tempo n'a de sens que sur une matière assez longue pour contenir
        # plusieurs temps. Mesuré sur la carte : sur un échantillon tenu
        # (nappe, note isolée de multi-échantillon), la détection renvoie une
        # valeur plausible mais arbitraire. Mieux vaut ne rien afficher qu'un
        # tempo inventé, d'où le double garde-fou durée + confiance.
        duration = data.size / float(sr) if sr else 0.0
        if duration >= MIN_BPM_SECONDS:
            bpm, confidence = analysis.detect_bpm(data, sr)
            if confidence >= MIN_BPM_CONFIDENCE and bpm > 0:
                out["bpm"] = round(float(bpm), 2)
        key, key_conf = analysis.detect_key(data, sr)
        if key_conf >= MIN_KEY_CONFIDENCE and key:
            out["key"] = key
    except Exception as exc:  # noqa: BLE001
        log.debug("analyse acoustique de %s en échec : %s", rel, exc)
    return out


def sr_limit() -> int:
    """Nombre maximal d'images lues pour l'analyse acoustique (30 s à 48 kHz)."""
    return 30 * 48000


def _sample_category(rel: str) -> str:
    """Catégorie déduite de l'emplacement : ``SAMPLES/DRUMS/Kick/…`` -> ``Kick``."""
    # Seuls les dossiers comptent : un fichier posé à même ``SAMPLES/`` ou
    # ``SAMPLES/DRUMS/`` prenait son propre nom pour catégorie (« Kick01.Wav »).
    parts = [p for p in norm_rel(rel).split("/") if p][:-1]
    if len(parts) >= 3 and parts[0] == "samples" and parts[1] == "drums":
        # Les catégories de percussion gardent l'orthographe du Deluge :
        # « HatC », pas « Hatc » — ``title()`` sur le chemin en minuscules
        # écrivait « Hatc », « Toml », et une recherche par catégorie (exacte)
        # ne les retrouvait plus.
        from .analysis import DRUM_CATEGORIES

        for category in DRUM_CATEGORIES:
            if category.lower() == parts[2]:
                return category
        return parts[2].title()
    if len(parts) >= 3 and parts[0] == "samples" \
            and parts[1] in ("multisamples", "artists"):
        return parts[2].title()
    if len(parts) == 2 and parts[0] == "samples" \
            and parts[1] not in ("drums", "multisamples", "artists"):
        return parts[1].title()
    if len(parts) > 2 and parts[0] == "samples":
        return parts[1].title()
    return ""


# --------------------------------------------------------------------------- #
# Presets, kits, morceaux
# --------------------------------------------------------------------------- #

def _scan_presets(sd: SDCard, lib: Library, paths: list[Path], kind: str, *,
                  full: bool, result: ScanResult,
                  progress: Callable[[ScanProgress], None] | None,
                  should_stop: Callable[[], bool] | None) -> bool:
    """Indexe les presets de synthé (``kind='synth'``) ou les kits."""
    known = {} if full else lib.known_files(kind)
    total = len(paths)
    label = "Presets" if kind == "synth" else "Kits"
    lib.begin()
    for i, path in enumerate(paths, 1):
        if should_stop is not None and should_stop():
            lib.commit()
            return False
        rel = sd.rel(path)
        try:
            st = path.stat()
        except OSError as exc:
            result.errors.append(f"{rel} : {exc}")
            continue

        if not full and _unchanged(known, rel, st):
            result.skipped += 1
            if kind == "synth":
                result.presets += 1
            else:
                result.kits += 1
            continue

        row: dict = {
            "rel": rel, "kind": kind, "name": path.stem,
            "folder": str(Path(rel).parent).replace("\\", "/"),
            "size": st.st_size, "mtime": st.st_mtime, "ok": 1, "error": "",
        }
        samples: list[tuple[str, bool]] = []

        try:
            if kind == "synth":
                preset = SynthPreset.load(path)
                sound = preset.sound
                row.update({
                    "firmware": sound.firmware,
                    "mode": sound.mode,
                    "category": sound.category_guess(),
                    "osc1": sound.osc_label(sound.osc1),
                    "osc2": sound.osc_label(sound.osc2),
                    "filter": sound.filter_label(),
                    "fx": ", ".join(sound.fx_list()),
                    "summary": " ".join(sound.tonal_tags()),
                })
                refs = preset.sample_paths()
                if preset.doc is not None:
                    row["repaired"] = " ; ".join(preset.doc.repaired)
            else:
                kit = Kit.load(path)
                row.update({
                    "firmware": getattr(kit, "firmware", "") or "",
                    "mode": "kit",
                    "category": "Kit",
                    "filter": kit.lpf_mode,
                    "fx": kit.mod_fx_type,
                    "summary": f"{len(kit.rows)} rangées",
                })
                refs = kit.sample_paths()
                if kit.doc is not None:
                    row["repaired"] = " ; ".join(kit.doc.repaired)
            row["uses_samples"] = 1 if refs else 0
            samples = [(ref, sd.resolve_sample(ref) is None) for ref in refs]
        except Exception as exc:  # noqa: BLE001 - 14 % des XML sont abîmés
            row.update({"ok": 0, "error": f"{type(exc).__name__}: {exc}"})
            result.errors.append(f"{rel} : {exc}")

        lib.upsert_preset(row)
        lib.replace_links(kind, rel, samples)
        if kind == "synth":
            result.presets += 1
        else:
            result.kits += 1

        if i % 50 == 0:
            lib.commit()
            lib.begin()
            _emit(progress, kind, i, total, f"{label} — {path.name}")
    lib.commit()
    _emit(progress, kind, total, total, f"{label} analysés")
    return True


def _same_root(a: str, b: str) -> bool:
    import os

    def _norm(p: str) -> str:
        return os.path.normcase(os.path.abspath(str(p))).rstrip("\\/")

    return _norm(a) == _norm(b)


def forget_other_card(sd: SDCard, lib: Library) -> bool:
    """Vide l'index s'il décrit une **autre** carte que ``sd``.

    L'index est unique : changer de carte laissait celui de l'ancienne en
    place. Les pages montraient alors ses fichiers, et les plans de
    rangement appliquaient ses empreintes aux fichiers de **même chemin**
    de la nouvelle carte — une sauvegarde de la carte et la carte elle-même
    ont justement les mêmes chemins, avec des contenus qui ont pu diverger.

    Favoris, notes et étiquettes sont conservés. Retourne ``True`` si
    l'index a été vidé.
    """
    racine = lib.get_meta("last_scan_root", "") or ""
    if not racine or _same_root(racine, str(sd.root)):
        return False
    log.info("index de %s écarté : la carte est désormais %s",
             racine, sd.root)
    lib.clear()
    lib.set_meta("last_scan_root", "")
    lib.set_meta("last_scan", "")
    return True


def index_presets(sd: SDCard, lib: Library, paths: list[Path]) -> None:
    """Indexe tout de suite des presets ou kits qu'on vient d'écrire.

    Sans cela, un preset dupliqué ou généré n'apparaissait dans aucune liste
    avant la prochaine analyse complète, alors que l'application venait
    d'annoncer « Copie créée ». La nature se déduit du dossier.
    """
    synths, kits = [], []
    for path in paths or ():
        top = norm_rel(sd.rel(Path(path))).split("/", 1)[0]
        (kits if top == "kits" else synths).append(Path(path))
    result = ScanResult()
    for kind, group in (("synth", synths), ("kit", kits)):
        if group:
            _scan_presets(sd, lib, group, kind, full=True, result=result,
                          progress=None, should_stop=None)
    lib.recompute_usage()


def index_songs(sd: SDCard, lib: Library, paths: list[Path]) -> None:
    """Indexe tout de suite des morceaux qu'on vient d'écrire.

    Ne touche pas à la version de lecture enregistrée dans l'index : elle
    dit que **tous** les morceaux ont été relus, ce qu'une poignée de
    fichiers neufs ne prouve pas.
    """
    result = ScanResult()
    _scan_songs(sd, lib, [Path(p) for p in paths or ()], full=True,
                result=result, progress=None, should_stop=None,
                mark_reader=False)
    lib.recompute_usage()


#: Version de la lecture des morceaux. Quand elle change, les morceaux déjà
#: indexés sont relus une fois, même inchangés : le 14 octobre 2026, leur
#: nombre de mesures était faux d'un facteur 2 à 4 (résolution des notes,
#: voir ``model.ticks_per_bar``), et l'analyse incrémentale ne relit pas un
#: fichier qui n'a pas bougé.
SONG_READER = "2"


def _scan_songs(sd: SDCard, lib: Library, paths: list[Path], *, full: bool,
                result: ScanResult,
                progress: Callable[[ScanProgress], None] | None,
                should_stop: Callable[[], bool] | None,
                mark_reader: bool = True) -> bool:
    """Indexe les morceaux.

    ``mark_reader`` : noter dans l'index que les morceaux ont été lus par la
    lecture actuelle (:data:`SONG_READER`) — seulement quand on les a tous
    vus.
    """
    relire = lib.get_meta("song_reader") != SONG_READER
    known = {} if (full or relire) else lib.known_files("song")
    total = len(paths)
    lib.begin()
    for i, path in enumerate(paths, 1):
        if should_stop is not None and should_stop():
            lib.commit()
            return False
        rel = sd.rel(path)
        try:
            st = path.stat()
        except OSError as exc:
            result.errors.append(f"{rel} : {exc}")
            continue

        if not full and _unchanged(known, rel, st):
            result.skipped += 1
            result.songs += 1
            continue

        row: dict = {
            "rel": rel, "name": path.stem, "size": st.st_size,
            "mtime": st.st_mtime, "ok": 1, "error": "",
        }
        samples: list[tuple[str, bool]] = []
        try:
            song = Song.load(path)
            stats = song.stats()
            row.update({
                "firmware": song.firmware,
                "tempo": song.tempo_bpm,
                "scale": song.scale_name(),
                "clips": stats["clips"],
                "notes": stats["notes"],
                "bars": stats["bars"],
                "instruments": stats["instruments"],
                "preview": song.preview,
            })
            samples = [(ref, sd.resolve_sample(ref) is None)
                       for ref in song.sample_paths()]
            if song.doc is not None:
                row["repaired"] = " ; ".join(song.doc.repaired)
        except Exception as exc:  # noqa: BLE001
            row.update({"ok": 0, "error": f"{type(exc).__name__}: {exc}"})
            result.errors.append(f"{rel} : {exc}")

        lib.upsert_song(row)
        lib.replace_links("song", rel, samples)
        result.songs += 1

        if i % 20 == 0:
            lib.commit()
            lib.begin()
            _emit(progress, "songs", i, total, f"Morceaux — {path.name}")
    lib.commit()
    if mark_reader:
        lib.set_meta("song_reader", SONG_READER)
    _emit(progress, "songs", total, total, "Morceaux analysés")
    return True


# --------------------------------------------------------------------------- #
# Point d'entrée
# --------------------------------------------------------------------------- #

def scan_card(sd: SDCard, lib: Library, *, compute_hash: bool = True,
              analyze: bool = False, full: bool = True,
              progress: Callable[[ScanProgress], None] | None = None,
              should_stop: Callable[[], bool] | None = None) -> ScanResult:
    """Indexe toute la carte dans ``lib``.

    :param compute_hash: calcule l'empreinte des échantillons (détection des
        doublons). Peu coûteux en mode rapide.
    :param analyze: mesures acoustiques (crête, RMS, et tempo/tonalité dès que
        ``core.analysis`` existe). Nettement plus lent : désactivé par défaut.
    :param full: ``False`` saute les fichiers dont taille et date n'ont pas
        changé depuis la dernière analyse.
    :param progress: rappel recevant un :class:`ScanProgress`.
    :param should_stop: rappel consulté à chaque fichier ; s'il retourne vrai,
        l'analyse s'arrête proprement et ``ScanResult.stopped`` vaut ``True``.

    Ne lève jamais : toute erreur est accumulée dans ``ScanResult.errors``.
    """
    started = time.monotonic()
    result = ScanResult()

    # Après une mise à niveau du schéma, les colonnes neuves sont vides et
    # une analyse incrémentale les laisserait vides : les fichiers n'ont pas
    # changé, donc elle les sauterait. ``Library.init_db`` pose
    # ``needs_rescan`` dans ce cas ; c'est ici qu'il sert, et c'est la seule
    # chose qui le lisait jusqu'ici.
    if not full and lib.needs_rescan:          # propriété, pas méthode
        log.info("index mis à niveau : analyse complète forcée")
        full = True

    if not sd.is_valid():
        result.errors.append(
            "La carte ne contient pas l'arborescence attendue "
            f"({', '.join(sd.missing_dirs())} absent(s))."
        )
        result.seconds = time.monotonic() - started
        return result

    if forget_other_card(sd, lib):
        full = True

    try:
        _emit(progress, "listing", 0, 0, "Inventaire de la carte…")
        sd.invalidate_cache()
        samples = sd.samples()
        synths = sd.synths()
        kits = sd.kits()
        songs = sd.songs()

        steps = (
            lambda: _scan_samples(sd, lib, samples, compute_hash=compute_hash,
                                  analyze=analyze, full=full, result=result,
                                  progress=progress, should_stop=should_stop),
            lambda: _scan_presets(sd, lib, synths, "synth", full=full,
                                  result=result, progress=progress,
                                  should_stop=should_stop),
            lambda: _scan_presets(sd, lib, kits, "kit", full=full,
                                  result=result, progress=progress,
                                  should_stop=should_stop),
            lambda: _scan_songs(sd, lib, songs, full=full, result=result,
                                progress=progress, should_stop=should_stop),
        )
        for step in steps:
            if not step():
                result.stopped = True
                break

        if not result.stopped:
            # Ce qui a disparu de la carte quitte l'index : sans cela, un
            # fichier effacé restait « inutilisé », « en double »… pour
            # toujours.
            present = {
                "sample": [sd.rel(p) for p in samples],
                "synth": [sd.rel(p) for p in synths],
                "kit": [sd.rel(p) for p in kits],
                "song": [sd.rel(p) for p in songs],
            }
            for kind, rels in present.items():
                gone = lib.purge_absent(kind, rels)
                if gone:
                    log.info("%d %s disparu(s) retiré(s) de l'index",
                             gone, kind)
            lib.refresh_missing_links()

        _emit(progress, "usage", 0, 0, "Calcul des dépendances…")
        lib.recompute_usage()

        # Les doublons ne sont affirmés qu'après comparaison complète des
        # fichiers soupçonnés : l'empreinte rapide produit des faux positifs
        # (cf. file_hash).
        if compute_hash and not result.stopped:
            try:
                confirm_duplicates(sd, lib, progress=progress,
                                   should_stop=should_stop)
            except Exception as exc:  # noqa: BLE001
                log.exception("vérification des doublons en échec")
                result.errors.append(f"Vérification des doublons : {exc}")
        if not result.stopped:
            lib.set_meta("last_scan", datetime.now().isoformat(timespec="seconds"))
            lib.set_meta("last_scan_root", str(sd.root))
            # Le drapeau ne se lève qu'au terme d'une analyse complète ET
            # acoustique : sans ``analyze``, les descripteurs restent nuls et
            # il faudra bien y revenir.
            if full and analyze:
                lib.clear_rescan_flag()
    except Exception as exc:  # noqa: BLE001 - rempart ultime, SPEC §4.9
        log.exception("échec inattendu de l'analyse")
        result.errors.append(f"Échec inattendu : {type(exc).__name__}: {exc}")

    result.seconds = time.monotonic() - started
    log.info(result.summary())
    return result
