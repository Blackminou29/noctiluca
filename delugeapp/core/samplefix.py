# -*- coding: utf-8 -*-
"""Correction des défauts audio des échantillons de la carte.

La page Santé sait repérer quatre défauts qu'elle ne savait que signaler :
percussions en stéréo, fréquences d'échantillonnage inhabituelles, écrêtage,
composante continue. Ce module les corrige — toujours en simulation d'abord
(``apply=False``), avec sauvegarde de l'original et mise à jour de l'index.

**Trois dangers mesurés sur la carte de référence**, et la façon dont ils sont
traités :

1. **Les bornes en trames.** 1 191 références de presets et de kits bornent
   leur échantillon en nombre de trames (``startSamplePos``). Changer la
   longueur d'un fichier décalerait leur lecture. :func:`retarget_zones`
   remet ces bornes à l'échelle dans la même opération.
2. **Les morceaux sont en lecture seule.** Les 28 morceaux qui citent des
   échantillons les bornent **tous** en trames (884 références), et
   l'application ne réécrit jamais un morceau (SPEC §0). Un fichier cité par
   un morceau est donc **écarté** des corrections qui changent sa longueur.
3. **L'écrêtage ne se répare pas.** Baisser le niveau rend de la marge, mais
   les sommets déjà rabotés ne reviennent pas. Le libellé le dit, pour ne pas
   laisser croire à une restauration.

Les corrections se répartissent donc en deux familles :

* celles qui **conservent le nombre de trames** — mono, retrait du continu,
  normalisation, fondus — sûres partout, y compris pour les morceaux ;
* celles qui **changent la longueur** — rééchantillonnage, rognage du silence
  — qui exigent la remise à l'échelle des bornes et écartent les fichiers
  cités par un morceau.
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import analysis, health, units, wav
from .db import Library
from .model import Kit, SynthPreset
from .sdcard import SDCard, norm_rel

log = logging.getLogger(__name__)

__all__ = [
    "Edit", "FixPlan", "FixResult",
    "ACTIONS", "LENGTH_SAFE", "LENGTH_CHANGING", "STANDARD_RATES",
    "DEFAULT_RATE", "DEFAULT_HEADROOM_DB", "BACKUP_ROOT",
    "song_locked_samples", "retarget_zones", "restore",
    "plan_mono", "plan_standard_rate", "plan_remove_dc", "plan_headroom",
    "plan_custom", "plan_from_health",
]

#: Toutes les corrections possibles, dans l'ordre où le moteur les applique.
ACTIONS = ("trim", "mono", "dc", "rate", "normalize", "fade", "depth")

#: Corrections qui laissent le nombre de trames intact.
LENGTH_SAFE = ("mono", "dc", "normalize", "fade", "depth")

#: Corrections qui changent la longueur du fichier.
LENGTH_CHANGING = ("rate", "trim")

#: Fréquences que le Deluge lit sans conversion à la volée — reprises de
#: ``health`` pour la même raison que les seuils ci-dessous.
STANDARD_RATES = health.GOOD_SAMPLE_RATES

#: Fréquence visée par défaut par :func:`plan_standard_rate`.
DEFAULT_RATE = 44100

#: Marge laissée par :func:`plan_headroom`, en dBFS.
DEFAULT_HEADROOM_DB = -1.0

#: Dossier des originaux, à la racine de la carte — hors de ``SAMPLES/``
#: pour que ni le Deluge ni le diagnostic ne les prennent pour des
#: échantillons (même convention que ``_UNUSED``).
BACKUP_ROOT = "_BACKUP"

#: Seuils repris de ``health`` et **non redéfinis ici** : un plan doit porter
#: exactement sur les fichiers que la page Santé signale. Les dupliquer, même
#: avec les bonnes valeurs du jour, ferait diverger les deux comptes à la
#: première retouche — c'est arrivé : 80 fichiers proposés contre 17
#: signalés, faute d'un seuil de continu à 0,002 au lieu de 0,01.
DC_THRESHOLD = health.DC_OFFSET_LIMIT

#: Proportion d'échantillons à pleine échelle au-delà de laquelle un fichier
#: est considéré comme écrêté.
CLIP_THRESHOLD = health.CLIPPED_RATIO

#: Niveau de sécurité appliqué quand le retrait du continu menace de pousser
#: un fichier à pleine échelle (cf. :func:`plan_remove_dc`).
DC_SAFE_CEILING_DB = -0.1

#: Crête au-delà de laquelle le retrait du continu doit être accompagné
#: d'une baisse de niveau.
FULL_SCALE = 0.9995

#: Codes de la page Santé que ce module sait corriger.
HEALTH_CODES = ("STEREO_DRUM", "ODD_SAMPLE_RATE", "DC_OFFSET",
                "CLIPPED_SAMPLE")


# --------------------------------------------------------------------------- #
# Une correction
# --------------------------------------------------------------------------- #

@dataclass
class Edit:
    """Une correction portant sur un fichier."""

    rel: str
    actions: dict = field(default_factory=dict)
    reason: str = ""
    before: dict = field(default_factory=dict)
    after: dict = field(default_factory=dict)
    skipped: str = ""
    error: str = ""

    @property
    def changes_length(self) -> bool:
        """Vrai si la correction modifie le nombre de trames."""
        return any(k in self.actions for k in LENGTH_CHANGING)

    @property
    def label(self) -> str:
        """Description lisible de ce qui va changer."""
        parts: list[str] = []
        if self.actions.get("mono"):
            ch = self.before.get("channels", 0)
            parts.append("%s → mono" % ("stéréo" if ch == 2 else "%d canaux" % ch
                                        if ch else "multicanal"))
        if self.actions.get("dc"):
            parts.append("retrait du continu (%+.3f)"
                         % float(self.before.get("dc_offset", 0.0)))
        rate = self.actions.get("rate")
        if rate:
            parts.append("%d → %d Hz" % (self.before.get("sr", 0), int(rate)))
        if self.actions.get("normalize") is not None:
            parts.append("niveau ramené à %.1f dBFS"
                         % float(self.actions["normalize"]))
        if self.actions.get("trim") is not None:
            parts.append("silence coupé sous %.0f dB"
                         % float(self.actions["trim"]))
        if self.actions.get("fade"):
            parts.append("fondus de %.0f ms" % float(self.actions["fade"]))
        depth = self.actions.get("depth")
        if depth:
            parts.append("%s → %s bits" % (self.before.get("bit_depth", "?"),
                                           depth))
        return ", ".join(parts) or "aucun changement"

    @property
    def name(self) -> str:
        """Nom du fichier, sans son dossier."""
        return Path(self.rel).name


@dataclass
class FixResult:
    """Ce qui s'est réellement passé après :meth:`FixPlan.apply`."""

    done: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    bytes_before: int = 0
    bytes_after: int = 0
    retargeted: list[str] = field(default_factory=list)
    zones_moved: int = 0
    backup_dir: str = ""
    applied: bool = False

    @property
    def bytes_saved(self) -> int:
        """Octets libérés (négatif si les fichiers ont grossi)."""
        return self.bytes_before - self.bytes_after

    def summary(self) -> str:
        """Résumé en une ligne."""
        if not self.applied:
            return "Simulation : %d fichier(s) seraient corrigés." % len(self.done)
        bits = ["%d fichier(s) corrigés" % len(self.done)]
        if self.failed:
            bits.append("%d en échec" % len(self.failed))
        if self.retargeted:
            bits.append("%d preset(s) recalés (%d bornes)"
                        % (len(self.retargeted), self.zones_moved))
        saved = self.bytes_saved
        if saved:
            bits.append("%s %s" % (
                "libérés" if saved > 0 else "ajoutés",
                units.human_size(abs(saved))))
        return ", ".join(bits) + "."


@dataclass
class FixPlan:
    """Ensemble de corrections, simulé avant d'être appliqué."""

    title: str = "Correction d'échantillons"
    edits: list[Edit] = field(default_factory=list)
    skipped: list[Edit] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.edits)

    def __bool__(self) -> bool:
        return bool(self.edits)

    def counts(self) -> dict[str, int]:
        """Nombre de fichiers par type de correction."""
        out: dict[str, int] = {}
        for edit in self.edits:
            for key in edit.actions:
                out[key] = out.get(key, 0) + 1
        return out

    @property
    def changes_length(self) -> bool:
        """Vrai si au moins une correction modifie une longueur."""
        return any(e.changes_length for e in self.edits)

    def summary(self) -> str:
        """Résumé en une ligne, pour l'en-tête d'une boîte de confirmation."""
        if not self.edits:
            return "Rien à corriger."
        libelles = {"mono": "passage en mono", "dc": "retrait du continu",
                    "rate": "rééchantillonnage", "normalize": "normalisation",
                    "trim": "coupe du silence", "fade": "fondus",
                    "depth": "profondeur"}
        parts = ["%s : %d" % (libelles.get(k, k), n)
                 for k, n in sorted(self.counts().items())]
        texte = "%d fichier(s) — %s" % (len(self.edits), ", ".join(parts))
        if self.skipped:
            texte += " ; %d écarté(s)" % len(self.skipped)
        return texte + "."

    def to_text(self) -> str:
        """Détail ligne par ligne, tel qu'il est montré avant confirmation."""
        lignes = [self.title, "=" * len(self.title), "", self.summary(), ""]
        for edit in self.edits:
            lignes.append("  %s" % edit.rel)
            lignes.append("      %s" % edit.label)
        if self.skipped:
            lignes += ["", "Écartés :"]
            for edit in self.skipped:
                lignes.append("  %s" % edit.rel)
                lignes.append("      %s" % edit.skipped)
        return "\n".join(lignes)

    # -- application -------------------------------------------------------- #

    def simulate(self, sd: SDCard, lib: Library) -> FixResult:
        """Chiffre ce que ferait le plan, sans écrire quoi que ce soit.

        C'est ce que la boîte de confirmation affiche. L'exécution, elle,
        passe par :meth:`apply`.
        """
        return self._run(sd, lib, apply=False, backup=False)

    def apply(self, sd: SDCard, lib: Library, backup: bool = True,
              progress=None, should_stop=None) -> FixResult:
        """Exécute le plan — il **écrit** sur la carte.

        La simulation exigée par la SPEC §0.2 se fait en amont : un
        ``FixPlan`` n'est qu'une intention, construite par les ``plan_*`` et
        montrée à l'utilisateur, et :meth:`simulate` la chiffre sans rien
        toucher. La signature suit celle d'``organize.Plan.apply`` : un
        ``plan.apply(sd, lib)`` qui ne ferait rien par défaut serait un piège.

        Les étapes, dans cet ordre :

        1. conversion de chaque fichier vers un temporaire, puis remplacement
           atomique de l'original (dont une copie part dans ``_BACKUP/``) ;
        2. mise à jour de la ligne d'index, mesures acoustiques comprises ;
        3. si des longueurs ont changé, remise à l'échelle des bornes des
           presets et kits qui citent ces fichiers.
        """
        return self._run(sd, lib, apply=True, backup=backup,
                         progress=progress, should_stop=should_stop)

    def _run(self, sd: SDCard, lib: Library, apply: bool,
             backup: bool = True, progress=None,
             should_stop=None) -> FixResult:
        """Corps commun de :meth:`simulate` et :meth:`apply`."""
        result = FixResult(applied=bool(apply))
        if not self.edits:
            return result

        backup_dir = _unique_backup_dir(sd)
        if apply and backup:
            result.backup_dir = sd.rel(backup_dir)

        #: fichier -> rapport trames_après / trames_avant
        ratios: dict[str, float] = {}
        total = len(self.edits)

        for index, edit in enumerate(self.edits, 1):
            if should_stop is not None and should_stop():
                log.info("correction interrompue après %d fichier(s)", index - 1)
                break
            if progress is not None:
                progress((index, total, edit.name))

            path = sd.resolve_sample(edit.rel)
            if path is None or not path.is_file():
                edit.error = "fichier introuvable"
                result.failed.append((edit.rel, edit.error))
                continue

            before = wav.probe(path)
            result.bytes_before += units.file_size(path)

            if not apply:
                # Simulation : on ne convertit rien, on retient la taille.
                result.done.append(edit.rel)
                result.bytes_after += units.file_size(path)
                continue

            ok, message, after = _convert_in_place(
                path, edit, backup_dir if backup else None, edit.rel)
            if not ok:
                edit.error = message
                result.failed.append((edit.rel, message))
                continue

            edit.after = _describe(after)
            result.done.append(edit.rel)
            result.bytes_after += units.file_size(path)

            if before.ok and after.ok and before.frames and after.frames \
                    and after.frames != before.frames:
                ratios[norm_rel(edit.rel)] = after.frames / float(before.frames)

            _reindex(sd, lib, edit.rel, path)

        if apply:
            try:
                lib.commit()
            except Exception:                       # noqa: BLE001
                log.exception("validation de l'index impossible")

        if apply and ratios:
            moved, files = retarget_zones(sd, ratios, apply=True)
            result.zones_moved = moved
            result.retargeted = files

        return result


# --------------------------------------------------------------------------- #
# Fichiers intouchables en longueur
# --------------------------------------------------------------------------- #

def song_locked_samples(sd: SDCard) -> dict[str, list[str]]:
    """Échantillons cités par un morceau, et par lesquels.

    Un morceau borne ses échantillons en nombre de trames et ne doit jamais
    être réécrit : ces fichiers sont donc exclus de toute correction qui
    changerait leur longueur. Le dictionnaire est indexé par chemin
    normalisé.
    """
    from .model import Song

    out: dict[str, list[str]] = {}
    base = sd.abs("SONGS")
    if not base.is_dir():
        return out
    for path in sorted(base.rglob("*")):
        if path.suffix.lower() != ".xml" or path.name.startswith("._"):
            continue
        try:
            song = Song.load(path)
        except Exception as exc:                    # noqa: BLE001
            log.debug("morceau illisible (%s) : %s", path.name, exc)
            continue
        rel_song = sd.rel(path)
        for name in song.sample_paths():
            if name:
                out.setdefault(norm_rel(name), []).append(rel_song)
    return out


# --------------------------------------------------------------------------- #
# Remise à l'échelle des bornes
# --------------------------------------------------------------------------- #

def _scale(value: int, ratio: float, frames: int = -1) -> int:
    """Met une borne à l'échelle, en restant dans le fichier."""
    if value < 0:
        return value
    out = int(round(value * ratio))
    if frames >= 0:
        out = min(out, frames)
    return max(0, out)


def _retarget_zone(zone, ratio: float) -> int:
    """Remet une zone à l'échelle ; retourne le nombre de bornes déplacées."""
    if zone is None or zone.unit != "samples":
        # Une zone en millisecondes survit à un rééchantillonnage : la durée
        # réelle du fichier, elle, n'a pas bougé.
        return 0
    moved = 0
    for attr in ("start", "end", "start_loop", "end_loop"):
        old = getattr(zone, attr)
        new = _scale(old, ratio)
        if new != old:
            setattr(zone, attr, new)
            moved += 1
    return moved


def retarget_zones(sd: SDCard, ratios: dict[str, float],
                   apply: bool = False) -> tuple[int, list[str]]:
    """Remet à l'échelle les bornes des presets citant les fichiers modifiés.

    ``ratios`` associe un chemin **normalisé** d'échantillon au rapport
    ``trames_après / trames_avant``. Retourne ``(bornes déplacées, presets
    concernés)``. Avec ``apply=False``, rien n'est écrit : seul le compte est
    retourné.

    Les morceaux sont volontairement ignorés : ils sont en lecture seule, et
    c'est à l'appelant d'avoir écarté en amont les fichiers qu'ils citent.
    """
    if not ratios:
        return 0, []

    total = 0
    touched: list[str] = []

    for folder, cls in (("SYNTHS", SynthPreset), ("KITS", Kit)):
        base = sd.abs(folder)
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.suffix.lower() != ".xml" or path.name.startswith("._"):
                continue
            try:
                obj = cls.load(path)
            except Exception as exc:                # noqa: BLE001
                log.debug("preset illisible (%s) : %s", path.name, exc)
                continue

            moved = 0
            for sound in _sounds_of(obj):
                for osc in (sound.osc1, sound.osc2):
                    if osc is None:
                        continue
                    ratio = ratios.get(norm_rel(osc.file_name or ""))
                    if ratio is not None:
                        moved += _retarget_zone(osc.zone, ratio)
                    for rng in osc.ranges:
                        ratio = ratios.get(norm_rel(rng.file_name or ""))
                        if ratio is not None:
                            moved += _retarget_zone(rng.zone, ratio)

            if not moved:
                continue
            total += moved
            touched.append(sd.rel(path))
            if apply:
                try:
                    obj.save(path, backup=True)
                except Exception:                   # noqa: BLE001
                    log.exception("recalage de %s impossible", path.name)
                    total -= moved
                    touched.pop()

    return total, touched


def _sounds_of(obj) -> list:
    """Les ``Sound`` d'un preset de synthé ou d'un kit."""
    sound = getattr(obj, "sound", None)
    if sound is not None:
        return [sound]
    return [row.sound for row in (getattr(obj, "rows", None) or [])
            if getattr(row, "sound", None) is not None]


# --------------------------------------------------------------------------- #
# Conversion d'un fichier
# --------------------------------------------------------------------------- #

def _convert_in_place(path: Path, edit: Edit, backup_dir: Path | None,
                      rel: str) -> tuple[bool, str, wav.AudioInfo]:
    """Convertit un fichier sur place, original sauvegardé au préalable.

    L'écriture passe par un temporaire voisin puis ``os.replace`` : si la
    conversion échoue à mi-chemin, l'original est encore intact.

    ``rel`` est le chemin **relatif à la carte** : c'est lui qui donne sa
    place à la copie de sauvegarde.
    """
    tmp = path.with_name(path.name + ".samplefix-tmp")
    actions = edit.actions
    try:
        info = wav.convert(
            path, tmp,
            sample_rate=int(actions["rate"]) if actions.get("rate") else None,
            bit_depth=actions.get("depth"),
            mono=True if actions.get("mono") else None,
            remove_dc=bool(actions.get("dc")),
            normalize_db=(float(actions["normalize"])
                          if actions.get("normalize") is not None else None),
            trim_silence_db=(float(actions["trim"])
                             if actions.get("trim") is not None else None),
            fade_ms=float(actions.get("fade") or 0.0),
        )
        if not info.ok:
            _unlink(tmp)
            return False, info.error or "conversion impossible", info

        if backup_dir is not None:
            if not _backup(path, backup_dir, rel):
                _unlink(tmp)
                return False, "sauvegarde de l'original impossible", info

        os.replace(tmp, path)
        return True, "", wav.probe(path)
    except OSError as exc:
        _unlink(tmp)
        return False, "%s: %s" % (type(exc).__name__, exc), wav.AudioInfo(path=path)


def _backup(path: Path, backup_dir: Path, rel: str) -> bool:
    """Copie l'original sous ``_BACKUP/…`` en conservant l'arborescence.

    L'arborescence conservée est celle **de la carte** : la copie de
    ``SAMPLES/DRUMS/Clap/x.wav`` va dans
    ``_BACKUP/samplefix-<date>/SAMPLES/DRUMS/Clap/x.wav``. Une première
    version prenait le chemin relatif à la racine du disque, ce qui enterrait
    la copie sous ``_BACKUP/…/Users/sebas/AppData/…`` — et la restauration
    recréait alors cette arborescence absurde dans la carte au lieu de
    remettre le fichier à sa place.
    """
    inner = str(rel or "").replace("\\", "/").strip("/")
    if not inner:
        log.error("sauvegarde sans chemin relatif : %s", path)
        return False
    try:
        dest = backup_dir / inner
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        return True
    except (OSError, ValueError):
        log.exception("sauvegarde de %s impossible", path)
        return False


def _unique_backup_dir(sd: SDCard) -> Path:
    """Dossier de sauvegarde propre à cette exécution.

    L'horodatage à la seconde ne suffit pas : deux corrections lancées coup
    sur coup tombaient dans le même dossier, et une restauration remettait
    alors en place les originaux des deux.
    """
    base = sd.abs(BACKUP_ROOT)
    stamp = time.strftime("%Y-%m-%d_%H%M%S")
    candidate = base / ("samplefix-%s" % stamp)
    suffix = 2
    while candidate.exists():
        candidate = base / ("samplefix-%s-%d" % (stamp, suffix))
        suffix += 1
    return candidate


def _unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        log.debug("temporaire non supprimé : %s", path)


def _describe(info: wav.AudioInfo) -> dict:
    """Les champs d'un ``AudioInfo`` utiles au rapport."""
    return {"sr": info.sample_rate, "channels": info.channels,
            "bit_depth": info.bit_depth, "frames": info.frames,
            "duration": round(info.duration, 4)}


def _reindex(sd: SDCard, lib: Library, rel: str, path: Path) -> None:
    """Remet la ligne d'index d'un échantillon à jour après conversion.

    Les mesures acoustiques sont **recalculées**, pas effacées : laisser
    l'ancien ``dc_offset`` dans l'index ferait reparaître l'anomalie au
    prochain diagnostic alors qu'elle vient d'être corrigée.
    """
    row: dict = {"rel": rel, "ok": 1, "error": ""}
    try:
        stat = path.stat()
        row["size"] = stat.st_size
        row["mtime"] = stat.st_mtime
    except OSError:
        pass

    info = wav.probe(path)
    if info.ok:
        row.update({"sr": info.sample_rate, "channels": info.channels,
                    "bit_depth": info.bit_depth, "frames": info.frames,
                    "duration": info.duration})
    else:
        row.update({"ok": 0, "error": info.error})

    try:
        data, _sr = wav.read(path, max_frames=None)
        if data.size:
            levels = analysis.loudness(data)
            row["peak"] = float(np.max(np.abs(data)))
            row["rms"] = float(np.sqrt(np.mean(np.square(data,
                                                         dtype=np.float64))))
            row["dc_offset"] = levels["dc_offset"]
            row["clipped"] = levels["clipped"]
    except Exception as exc:                        # noqa: BLE001
        log.debug("mesures impossibles après conversion de %s : %s", rel, exc)

    try:
        from .scan import file_hash

        row["hash"] = file_hash(path, quick=True)
        row["hash_full"] = ""
    except Exception as exc:                        # noqa: BLE001
        log.debug("empreinte impossible pour %s : %s", rel, exc)

    lib.upsert_sample(row)


# --------------------------------------------------------------------------- #
# Construction des plans
# --------------------------------------------------------------------------- #

def _rows(lib: Library, rels: list[str] | None) -> list:
    """Lignes d'index des échantillons demandés, ou de tous."""
    if rels is None:
        return lib.search_samples(limit=100000)
    wanted = {norm_rel(r) for r in rels}
    return [r for r in lib.search_samples(limit=100000)
            if norm_rel(r["rel"]) in wanted]


def _before(row) -> dict:
    """Ce que l'index sait d'un échantillon avant correction."""
    def _get(key, default=0):
        try:
            value = row[key]
        except (KeyError, IndexError):
            return default
        return default if value is None else value

    return {"sr": int(_get("sr")), "channels": int(_get("channels")),
            "bit_depth": int(_get("bit_depth")), "frames": int(_get("frames")),
            "size": int(_get("size")), "peak": float(_get("peak", 0.0)),
            "dc_offset": float(_get("dc_offset", 0.0)),
            "clipped": float(_get("clipped", 0.0)),
            "category": str(_get("category", "") or "")}


def _guard_length(plan: FixPlan, edit: Edit, locked: dict) -> None:
    """Range l'édition dans le plan, ou l'écarte si un morceau la bloque."""
    if edit.changes_length:
        songs = locked.get(norm_rel(edit.rel))
        if songs:
            edit.skipped = (
                "cité par %d morceau(x) — %s ; un morceau borne ses "
                "échantillons en trames et n'est jamais réécrit"
                % (len(songs), ", ".join(sorted(songs)[:2])))
            plan.skipped.append(edit)
            return
    plan.edits.append(edit)


def plan_mono(sd: SDCard, lib: Library,
              rels: list[str] | None = None) -> FixPlan:
    """Passe en mono les percussions enregistrées en stéréo.

    Sans ``rels``, la sélection reprend le critère du diagnostic : un fichier
    sous ``SAMPLES/DRUMS`` à plus d'un canal. L'opération conserve le nombre
    de trames, elle est donc sûre même pour les fichiers cités par un
    morceau.
    """
    plan = FixPlan(title="Percussions stéréo → mono")
    for row in _rows(lib, rels):
        rel = row["rel"]
        info = _before(row)
        if info["channels"] <= 1:
            continue
        # Le critère est exactement celui du diagnostic : sous
        # ``SAMPLES/DRUMS/`` et nulle part ailleurs. Chercher un segment
        # « drums » n'importe où dans le chemin ratisserait plus large que ce
        # que la page Santé annonce.
        if rels is None and not norm_rel(rel).startswith("samples/drums/"):
            continue
        plan.edits.append(Edit(
            rel=rel, actions={"mono": True},
            reason="STEREO_DRUM", before=info))
    return plan


def plan_standard_rate(sd: SDCard, lib: Library,
                       rels: list[str] | None = None,
                       rate: int = DEFAULT_RATE) -> FixPlan:
    """Ramène les échantillons à une fréquence que le Deluge lit directement.

    Cette correction **change la longueur** du fichier : les bornes des
    presets sont remises à l'échelle, et les fichiers cités par un morceau
    sont écartés.
    """
    target = int(rate) if int(rate) > 0 else DEFAULT_RATE
    plan = FixPlan(title="Rééchantillonnage à %d Hz" % target)
    locked = song_locked_samples(sd)
    for row in _rows(lib, rels):
        info = _before(row)
        if info["sr"] <= 0 or info["sr"] == target:
            continue
        if rels is None and info["sr"] in STANDARD_RATES:
            continue
        _guard_length(plan, Edit(
            rel=row["rel"], actions={"rate": target},
            reason="ODD_SAMPLE_RATE", before=info), locked)
    return plan


def plan_remove_dc(sd: SDCard, lib: Library,
                   rels: list[str] | None = None) -> FixPlan:
    """Retire la composante continue des échantillons qui en portent une.

    **Recentrer un fichier déjà chaud le pousse à pleine échelle.** Un signal
    dont les sommets négatifs atteignent −0,986 avec un continu de −0,0135
    arrive exactement à −1,0 une fois recentré : trois fichiers de la carte
    d'essai basculaient ainsi dans l'écrêtage, le diagnostic passant de 35 à
    38 fichiers écrêtés après une correction censée améliorer les choses.
    Dans ce cas, le retrait est donc accompagné d'une baisse de niveau — ce
    qui met à l'échelle au lieu de raboter.
    """
    plan = FixPlan(title="Retrait de la composante continue")
    for row in _rows(lib, rels):
        info = _before(row)
        if rels is None and abs(info["dc_offset"]) < DC_THRESHOLD:
            continue
        actions: dict = {"dc": True}
        if info["peak"] + abs(info["dc_offset"]) >= FULL_SCALE:
            actions["normalize"] = DC_SAFE_CEILING_DB
        plan.edits.append(Edit(
            rel=row["rel"], actions=actions,
            reason="DC_OFFSET", before=info))
    return plan


def plan_headroom(sd: SDCard, lib: Library, rels: list[str] | None = None,
                  target_db: float = DEFAULT_HEADROOM_DB) -> FixPlan:
    """Rend de la marge aux échantillons écrêtés.

    **Ce n'est pas une réparation de l'écrêtage** : les sommets rabotés à
    l'enregistrement ne reviennent pas. Baisser le niveau évite seulement que
    le fichier sature de nouveau en sortie, et rend de la place au mixage.
    """
    plan = FixPlan(title="Marge rendue aux échantillons écrêtés")
    for row in _rows(lib, rels):
        info = _before(row)
        if rels is None and info["clipped"] < CLIP_THRESHOLD:
            continue
        plan.edits.append(Edit(
            rel=row["rel"], actions={"normalize": float(target_db)},
            reason="CLIPPED_SAMPLE", before=info))
    return plan


def plan_custom(sd: SDCard, lib: Library, rels: list[str],
                mono: bool = False, rate: int | None = None,
                dc: bool = False, normalize_db: float | None = None,
                trim_db: float | None = None, fade_ms: float = 0.0,
                depth: int | None = None) -> FixPlan:
    """Plan libre, pour le traitement par lot de la page Échantillons."""
    actions: dict = {}
    if mono:
        actions["mono"] = True
    if rate:
        actions["rate"] = int(rate)
    if dc:
        actions["dc"] = True
    if normalize_db is not None:
        actions["normalize"] = float(normalize_db)
    if trim_db is not None:
        actions["trim"] = float(trim_db)
    if fade_ms:
        actions["fade"] = float(fade_ms)
    if depth:
        actions["depth"] = int(depth)

    plan = FixPlan(title="Traitement de %d échantillon(s)" % len(rels or []))
    if not actions or not rels:
        return plan

    locked = song_locked_samples(sd) if any(
        k in actions for k in LENGTH_CHANGING) else {}
    # Le rognage retire le silence de tête : tout le contenu recule d'un
    # nombre de trames inconnu du recalage, qui ne sait que mettre les bornes
    # à l'échelle. Une tranche de preset ou un pad de kit découpé jouerait
    # alors le mauvais passage : ces fichiers ne sont pas rognés.
    cited: dict[str, list[str]] = {}
    if "trim" in actions:
        try:
            from .deps import build_graph
            graph = build_graph(sd, lib)
            for rel in rels:
                users = [src for _kind, src in graph.users_of(rel)]
                if users:
                    cited[norm_rel(rel)] = users
        except Exception:                           # noqa: BLE001
            log.exception("dépendances indisponibles : rognage refusé")
            cited = {norm_rel(r): ["(dépendances inconnues)"] for r in rels}
    known = {norm_rel(r["rel"]): r for r in _rows(lib, list(rels))}
    for rel in rels:
        row = known.get(norm_rel(rel))
        info = _before(row) if row is not None else {}
        edit = Edit(rel=rel, actions=dict(actions), reason="manuel",
                    before=info)
        users = cited.get(norm_rel(rel))
        if users:
            edit.skipped = (
                "cité par %d preset(s) ou kit(s) — %s ; le rognage décale le "
                "début du son et leurs bornes ne peuvent pas être recalées"
                % (len(users), ", ".join(sorted(users)[:2])))
            plan.skipped.append(edit)
            continue
        if actions.get("mono") and info.get("channels", 0) == 1:
            # Déjà mono : inutile de réécrire le fichier pour rien.
            reste = {k: v for k, v in actions.items() if k != "mono"}
            if not reste:
                edit.skipped = "déjà en mono"
                plan.skipped.append(edit)
                continue
            edit.actions = reste
        _guard_length(plan, edit, locked)
    return plan


def plan_from_health(sd: SDCard, lib: Library,
                     codes: list[str]) -> FixPlan:
    """Rassemble en un plan les corrections des codes de santé demandés."""
    wanted = [c for c in (codes or []) if c in HEALTH_CODES]
    plan = FixPlan(title="Correction des défauts audio")
    builders = {
        "STEREO_DRUM": plan_mono,
        "ODD_SAMPLE_RATE": plan_standard_rate,
        "DC_OFFSET": plan_remove_dc,
        "CLIPPED_SAMPLE": plan_headroom,
    }
    # Un même fichier peut relever de deux défauts : les corrections sont
    # alors fusionnées en une seule réécriture.
    fusion: dict[str, Edit] = {}
    for code in wanted:
        sous_plan = builders[code](sd, lib)
        plan.skipped += sous_plan.skipped
        for edit in sous_plan.edits:
            cle = norm_rel(edit.rel)
            if cle in fusion:
                fusion[cle].actions.update(edit.actions)
                fusion[cle].reason += "+" + edit.reason
            else:
                fusion[cle] = edit
    plan.edits = list(fusion.values())
    return plan


# --------------------------------------------------------------------------- #
# Retour en arrière
# --------------------------------------------------------------------------- #

def restore(sd: SDCard, backup_rel: str, lib: Library | None = None,
            apply: bool = False) -> tuple[int, list[str]]:
    """Remet en place les originaux d'une sauvegarde de correction.

    Retourne ``(nombre de fichiers, erreurs)``. Avec ``apply=False``, rien
    n'est écrit : seul le compte est retourné, pour pouvoir l'annoncer.
    """
    base = sd.abs(backup_rel)
    if not base.is_dir():
        return 0, ["sauvegarde introuvable : %s" % backup_rel]

    count = 0
    errors: list[str] = []
    #: fichier -> trames_originales / trames_actuelles, pour défaire le
    #: recalage des bornes fait lors de la correction.
    ratios: dict[str, float] = {}
    for src in sorted(base.rglob("*")):
        if not src.is_file():
            continue
        inner = src.relative_to(base)
        dest = sd.abs(str(inner))
        count += 1
        if not apply:
            continue
        try:
            current = wav.probe(dest) if dest.is_file() else None
            original = wav.probe(src)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            if (current is not None and current.ok and original.ok
                    and current.frames and original.frames
                    and current.frames != original.frames):
                ratios[norm_rel(inner.as_posix())] = (
                    original.frames / float(current.frames))
            if lib is not None:
                _reindex(sd, lib, sd.rel(dest), dest)
        except OSError as exc:
            errors.append("%s : %s" % (inner, exc))
    if apply and ratios:
        # Sans cela, les bornes restaient à l'échelle du fichier converti.
        retarget_zones(sd, ratios, apply=True)
    if apply and lib is not None:
        try:
            lib.commit()
        except Exception:                           # noqa: BLE001
            log.exception("validation de l'index impossible")
    return count, errors
