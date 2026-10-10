# -*- coding: utf-8 -*-
"""Diagnostic de santé de la carte SD.

Produit un rapport lisible : ce qui est cassé, ce qui est inutile, ce qui
gênera le Deluge. Les contrôles lisent **l'index**, pas la carte, pour que la
page reste instantanée après l'analyse ; seuls deux contrôles parcourent le
système de fichiers (dossiers vides et fichiers non audio), ce qui est rapide.

Deux principes de rédaction du rapport :

* **ne rien signaler qui ne soit un vrai problème.** 134 des 1 000 XML de la
  carte d'essai sont des documents multi-racines : c'est la forme *normale* du
  firmware 2.x, pas un défaut. Les compter comme des anomalies rendrait la page
  inutilisable. Seules les 7 réparations qui témoignent d'une vraie corruption
  sont rapportées.
* **dire quoi faire.** Chaque anomalie porte un libellé d'action, et celles qui
  sont réparables automatiquement le signalent (``auto_fixable``), ce qui
  permet à :func:`autofix` d'en construire un plan.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import organize
from .db import Library
from .organize import Plan
from .sdcard import (
    AUDIO_EXT,
    STD_DIRS,
    SDCard,
    check_name,
    norm_rel,
)

log = logging.getLogger(__name__)

#: Niveaux de gravité, du moins au plus grave.
SEVERITY = ("info", "warn", "error")

#: Fréquences d'échantillonnage que le Deluge traite sans conversion.
#: La machine tourne à 44,1 kHz ; 48 kHz est courant et passe sans heurt.
GOOD_SAMPLE_RATES = (44100, 48000)

#: Au-delà, un échantillon est long à charger (le Deluge lit depuis la carte).
BIG_SAMPLE_BYTES = 20 * 1024 * 1024

#: Limites de chemin : FAT32 s'arrête à 255 caractères, on alerte avant.
LONG_PATH_CHARS = 200

#: Profondeur d'arborescence au-delà de laquelle la navigation sur la machine
#: devient pénible.
DEEP_FOLDER_LEVELS = 8

#: Seuils d'espace libre.
LOW_SPACE_BYTES = 500 * 1024 * 1024
LOW_SPACE_RATIO = 0.05

#: Écrêtage et offset continu considérés comme gênants.
CLIPPED_RATIO = 0.001
DC_OFFSET_LIMIT = 0.01

#: Nombre d'éléments cités en exemple dans le détail d'une anomalie.
MAX_ITEMS = 2000

#: Dossiers que le Deluge crée lui-même : leur vacuité n'est pas une anomalie.
STANDARD_EMPTY_OK = frozenset({
    "samples", "samples/clips", "samples/record", "samples/resample",
    "samples/stems", "samples/drums", "samples/multisamples",
    "songs", "synths", "kits",
})

#: Réparations XML qui ne dénotent aucune corruption : le firmware 2.x écrit
#: normalement plusieurs racines dans un même fichier (cf. SPEC §1.3).
BENIGN_REPAIRS = ("multi-racines",)


@dataclass
class Issue:
    """Une anomalie du rapport de santé."""

    code: str
    severity: str
    title: str
    detail: str
    items: list[str] = field(default_factory=list)
    fix: str = ""
    auto_fixable: bool = False

    @property
    def count(self) -> int:
        """Nombre d'éléments concernés."""
        return len(self.items)


@dataclass
class HealthReport:
    """Rapport complet, avec une note sur 100."""

    issues: list[Issue] = field(default_factory=list)
    score: int = 100
    checked: int = 0
    seconds: float = 0.0

    def by_severity(self, sev: str) -> list[Issue]:
        """Anomalies d'un niveau de gravité donné."""
        return [i for i in self.issues if i.severity == sev]

    @property
    def errors(self) -> list[Issue]:
        return self.by_severity("error")

    @property
    def warnings(self) -> list[Issue]:
        return self.by_severity("warn")

    def auto_fixable(self) -> list[Issue]:
        """Anomalies que :func:`autofix` sait traiter."""
        return [i for i in self.issues if i.auto_fixable]

    def verdict(self) -> str:
        """Appréciation d'ensemble, en français."""
        if self.score >= 95:
            return "Carte en très bon état."
        if self.score >= 80:
            return "Carte en bon état, quelques points à surveiller."
        if self.score >= 50:
            return "Carte à nettoyer."
        return "Carte à remettre en ordre sérieusement."

    def to_text(self) -> str:
        """Rapport en texte brut."""
        lines = [f"Santé de la carte : {self.score}/100 — {self.verdict()}",
                 f"{len(self.errors)} erreur(s), {len(self.warnings)} "
                 f"avertissement(s), {len(self.by_severity('info'))} remarque(s)",
                 ""]
        labels = {"error": "ERREUR", "warn": "ATTENTION", "info": "REMARQUE"}
        for sev in reversed(SEVERITY):
            for issue in self.by_severity(sev):
                lines.append(f"[{labels[sev]}] {issue.title} ({issue.count})")
                lines.append(f"    {issue.detail}")
                if issue.fix:
                    lines.append(f"    À faire : {issue.fix}")
                for item in issue.items[:10]:
                    lines.append(f"      - {item}")
                if issue.count > 10:
                    lines.append(f"      … et {issue.count - 10} autre(s)")
                lines.append("")
        if not self.issues:
            lines.append("Aucune anomalie détectée.")
        return "\n".join(lines)

    def to_html(self) -> str:
        """Rapport en HTML, pour l'afficher dans un ``QTextBrowser``."""
        # Les couleurs sont écrites en clair : le noyau ne doit pas importer
        # l'interface (SPEC §0.7). Elles reprennent la palette de `ui.theme`.
        colors = {"error": "#F2453D", "warn": "#FFC400", "info": "#28C4E0"}
        labels = {"error": "Erreur", "warn": "Attention", "info": "Remarque"}
        out = [
            "<html><body style=\"font-family:Segoe UI,sans-serif;"
            "color:#F2F4F8;background:#1C1F26;\">",
            f"<h2 style=\"color:#C79A22;margin-bottom:2px;\">Santé de la carte :"
            f" {self.score}/100</h2>",
            f"<p style=\"color:#7A828F;margin-top:0;\">{_esc(self.verdict())}</p>",
        ]
        if not self.issues:
            out.append("<p>Aucune anomalie détectée.</p>")
        for sev in reversed(SEVERITY):
            for issue in self.by_severity(sev):
                color = colors.get(sev, "#7A828F")
                out.append(
                    f"<h3 style=\"color:{color};margin-bottom:2px;\">"
                    f"{labels.get(sev, sev)} — {_esc(issue.title)} "
                    f"<span style=\"color:#7A828F;font-weight:normal;\">"
                    f"({issue.count})</span></h3>")
                out.append(f"<p style=\"margin:2px 0;\">{_esc(issue.detail)}</p>")
                if issue.fix:
                    out.append(f"<p style=\"color:#C79A22;margin:2px 0;\">"
                               f"À faire : {_esc(issue.fix)}</p>")
                if issue.items:
                    out.append("<ul style=\"color:#C3C9D2;\">")
                    for item in issue.items[:10]:
                        out.append(f"<li>{_esc(item)}</li>")
                    if issue.count > 10:
                        out.append(f"<li style=\"color:#7A828F;\">… et "
                                   f"{issue.count - 10} autre(s)</li>")
                    out.append("</ul>")
        out.append("</body></html>")
        return "\n".join(out)


def _esc(text: str) -> str:
    """Échappe le texte pour l'insérer dans du HTML."""
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def compute_score(issues: list[Issue]) -> int:
    """Note sur 100 : ``100 − (5 × erreurs + 2 × avertissements)``.

    Le barème est celui de la SPEC §4.13 et compte les **catégories**
    d'anomalies, pas les fichiers : une carte avec 300 fichiers parasites a un
    seul problème à régler, pas trois cents.
    """
    errors = sum(1 for i in issues if i.severity == "error")
    warnings = sum(1 for i in issues if i.severity == "warn")
    return max(0, min(100, 100 - (5 * errors + 2 * warnings)))


# --------------------------------------------------------------------------- #
# Les contrôles
# --------------------------------------------------------------------------- #

def check_card(sd: SDCard, lib: Library,
               progress: Callable[[str], None] | None = None,
               backup_dir: Path | None = None) -> HealthReport:
    """Passe la carte en revue et retourne un rapport.

    :param backup_dir: dossier des sauvegardes. S'il est fourni, l'absence de
        sauvegarde récente est signalée ; sinon le contrôle est sauté.

    Ne lève jamais : un contrôle en échec est journalisé et ignoré, pour qu'un
    défaut du diagnostic ne prive pas l'utilisateur de tout le reste.
    """
    import time

    started = time.monotonic()
    issues: list[Issue] = []

    def _step(label: str, fn: Callable[[], Issue | None]) -> None:
        if progress is not None:
            try:
                progress(label)
            except Exception:  # noqa: BLE001
                pass
        try:
            issue = fn()
        except Exception as exc:  # noqa: BLE001 - un contrôle ne bloque rien
            log.exception("contrôle « %s » en échec", label)
            return
        if issue is not None and issue.items:
            issues.append(issue)

    _step("Structure de la carte", lambda: _check_std_dirs(sd))
    _step("Firmware", lambda: _check_firmware(sd))
    _step("Espace libre", lambda: _check_space(sd))
    _step("Références d'échantillons", lambda: _check_missing(lib))
    _step("Échantillons inutilisés", lambda: _check_orphans(lib))
    _step("Doublons", lambda: _check_duplicates(lib))
    _step("Fichiers illisibles", lambda: _check_unreadable(lib))
    _step("XML réparés", lambda: _check_repaired(lib))
    _step("Noms de fichiers", lambda: _check_names(lib))
    _step("Longueur des chemins", lambda: _check_long_paths(lib))
    _step("Profondeur des dossiers", lambda: _check_deep_folders(lib))
    _step("Fréquences d'échantillonnage", lambda: _check_sample_rates(lib))
    _step("Gros échantillons", lambda: _check_big_samples(lib))
    _step("Percussions en stéréo", lambda: _check_stereo_drums(lib))
    _step("Échantillons écrêtés", lambda: _check_clipped(lib))
    _step("Offset continu", lambda: _check_dc_offset(lib))
    _step("Échantillons muets", lambda: _check_silent(lib))
    _step("Fichiers parasites", lambda: _check_mac_junk(sd))
    _step("Fichiers non audio", lambda: _check_non_audio(sd))
    _step("Dossiers vides", lambda: _check_empty_folders(sd))
    _step("Sauvegardes", lambda: _check_backup(backup_dir))

    stats = {}
    try:
        stats = lib.stats()
    except Exception as exc:  # noqa: BLE001
        log.debug("statistiques indisponibles : %s", exc)

    report = HealthReport(issues=issues, score=compute_score(issues))
    report.checked = int(stats.get("samples", 0)) + int(stats.get("synths", 0)) \
        + int(stats.get("kits", 0)) + int(stats.get("songs", 0))
    report.seconds = time.monotonic() - started
    log.info("santé : %d/100, %d anomalie(s) en %.1f s",
             report.score, len(issues), report.seconds)
    return report


# -- structure -------------------------------------------------------------- #

def _check_std_dirs(sd: SDCard) -> Issue | None:
    missing = sd.missing_dirs()
    if not missing:
        return None
    return Issue(
        "MISSING_STD_DIR", "error",
        "Dossiers standards absents",
        "Le Deluge attend ces dossiers à la racine de la carte ; sans eux, il "
        "ne trouvera ni les morceaux ni les presets.",
        items=list(missing),
        fix="Créer les dossiers manquants à la racine.",
        auto_fixable=True,
    )


def _check_firmware(sd: SDCard) -> Issue | None:
    files = sd.firmware_files()
    if len(files) > 1:
        return Issue(
            "MULTI_FIRMWARE", "error",
            "Plusieurs fichiers de firmware à la racine",
            "Le Deluge n'accepte qu'un seul fichier « deluge*.bin ». Avec "
            "plusieurs, la mise à jour est refusée.",
            items=[p.name for p in files],
            fix="Ne garder que la version voulue.",
        )
    if not files:
        return Issue(
            "NO_FIRMWARE", "info",
            "Aucun fichier de firmware",
            "Ce n'est pas un défaut : le firmware n'a besoin d'être présent "
            "que pour une mise à jour.",
            items=["aucun fichier deluge*.bin à la racine"],
        )
    return None


def _check_space(sd: SDCard) -> Issue | None:
    free, total = sd.free_space()
    if total <= 0:
        return None
    if free > LOW_SPACE_BYTES and free / total > LOW_SPACE_RATIO:
        return None
    return Issue(
        "LOW_SPACE", "warn",
        "Espace libre faible",
        f"Il reste {free / 2 ** 20:.0f} Mio sur {total / 2 ** 30:.1f} Gio. "
        f"Le Deluge a besoin de place pour enregistrer et rééchantillonner.",
        items=[f"{free / 2 ** 20:.0f} Mio libres"],
        fix="Archiver les échantillons inutilisés ou libérer de la place.",
    )


# -- dépendances ------------------------------------------------------------ #

def _check_missing(lib: Library) -> Issue | None:
    rows = lib.missing_links()
    if not rows:
        return None
    samples = sorted({r["dst_rel"] for r in rows})
    sources = sorted({r["src_rel"] for r in rows})
    return Issue(
        "MISSING_SAMPLE", "error",
        "Échantillons référencés mais absents",
        f"{len(sources)} preset(s), kit(s) ou morceau(x) réclament "
        f"{len(samples)} échantillon(s) introuvable(s) sur la carte. Le Deluge "
        f"restera muet sur ces sons.",
        items=samples[:MAX_ITEMS],
        fix="Chercher un remplaçant pour chacun, ou recopier les fichiers "
            "manquants sur la carte.",
        auto_fixable=True,
    )


def _check_orphans(lib: Library) -> Issue | None:
    rows = lib.unused_samples()
    if not rows:
        return None
    total = sum(r["size"] or 0 for r in rows)
    return Issue(
        "ORPHAN_SAMPLE", "info",
        "Échantillons jamais utilisés",
        f"{len(rows)} échantillon(s) ({total / 2 ** 20:.0f} Mio) ne sont cités "
        f"par aucun preset, kit ni morceau de cette carte. Ce n'est pas un "
        f"défaut : votre bibliothèque peut contenir des sons en réserve.",
        items=[r["rel"] for r in rows[:MAX_ITEMS]],
        fix="Les archiver dans un dossier à part s'il faut libérer de la place.",
        auto_fixable=True,
    )


def _check_duplicates(lib: Library) -> Issue | None:
    groups = lib.duplicates()
    if not groups:
        return None
    wasted = sum(sum(r["size"] or 0 for r in g[1:]) for g in groups)
    items = [" = ".join(r["rel"] for r in g) for g in groups[:MAX_ITEMS]]
    return Issue(
        "DUPLICATE_SAMPLE", "warn",
        "Échantillons en double",
        f"{len(groups)} groupe(s) de fichiers rigoureusement identiques, "
        f"{wasted / 2 ** 20:.0f} Mio en trop. La comparaison a été faite octet "
        f"par octet, ce ne sont pas de simples homonymes.",
        items=items,
        fix="Ne garder qu'un exemplaire ; les références seront redirigées.",
        auto_fixable=True,
    )


# -- lisibilité des fichiers ------------------------------------------------ #

def _check_unreadable(lib: Library) -> Issue | None:
    items: list[str] = []
    try:
        for table in ("presets", "songs"):
            rows = lib.con.execute(
                f"SELECT rel, error FROM {table} WHERE ok = 0").fetchall()
            items += [f"{r['rel']} — {r['error']}" for r in rows]
    except Exception as exc:  # noqa: BLE001
        log.debug("lecture des fichiers illisibles impossible : %s", exc)
        return None
    if not items:
        return None
    return Issue(
        "UNREADABLE_XML", "error",
        "Fichiers XML illisibles",
        "Ces fichiers n'ont pu être interprétés, même par le lecteur "
        "tolérant. Le Deluge les refusera aussi.",
        items=sorted(items)[:MAX_ITEMS],
        fix="Restaurer ces fichiers depuis une sauvegarde, ou les supprimer.",
    )


def _check_repaired(lib: Library) -> Issue | None:
    """Ne retient que les réparations qui dénotent une vraie corruption.

    Un document multi-racines est la forme normale du firmware 2.x : sur la
    carte d'essai, 134 fichiers sur 140 sont dans ce cas. Les signaler ferait
    passer une carte saine pour une carte abîmée.
    """
    items: list[str] = []
    try:
        for table in ("presets", "songs"):
            rows = lib.con.execute(
                f"SELECT rel, repaired FROM {table} "
                f"WHERE repaired IS NOT NULL AND repaired <> ''").fetchall()
            for row in rows:
                note = row["repaired"]
                if any(benign in note for benign in BENIGN_REPAIRS):
                    continue
                items.append(f"{row['rel']} — {note}")
    except Exception as exc:  # noqa: BLE001
        log.debug("lecture des réparations impossible : %s", exc)
        return None
    if not items:
        return None
    return Issue(
        "REPAIRED_XML", "warn",
        "Fichiers XML réparés à la lecture",
        "Ces fichiers comportent des anomalies de syntaxe (caractères "
        "illégaux, « & » non échappé, balises mal fermées) que le lecteur a "
        "contournées. Le Deluge, lui, peut les refuser.",
        items=sorted(items)[:MAX_ITEMS],
        fix="Réenregistrer ces presets depuis l'application pour obtenir un "
            "XML propre.",
    )


# -- noms et chemins -------------------------------------------------------- #

def _all_rows(lib: Library):
    """Toutes les lignes indexées, avec leur nature."""
    out = []
    try:
        out += [("sample", r) for r in lib.search_samples(limit=100000)]
        out += [("synth", r) for r in lib.search_presets(kind="synth",
                                                         limit=100000)]
        out += [("kit", r) for r in lib.search_presets(kind="kit", limit=100000)]
        out += [("song", r) for r in lib.search_songs()]
    except Exception as exc:  # noqa: BLE001
        log.debug("parcours de l'index impossible : %s", exc)
    return out


def _check_names(lib: Library) -> Issue | None:
    items: list[str] = []
    for _kind, row in _all_rows(lib):
        problems = check_name(Path(row["rel"]).stem)
        if problems:
            items.append(f"{row['rel']} — {problems[0]}")
    if not items:
        return None
    return Issue(
        "BAD_NAME", "warn",
        "Noms de fichiers problématiques",
        "Caractères interdits par FAT32, nom terminé par un point ou une "
        "espace, accents : autant de noms que le Deluge peut afficher de "
        "travers ou refuser.",
        items=sorted(items)[:MAX_ITEMS],
        fix="Renommer ces fichiers en ASCII sans caractère spécial.",
        auto_fixable=True,
    )


def _check_long_paths(lib: Library) -> Issue | None:
    items = [row["rel"] for _k, row in _all_rows(lib)
             if len(row["rel"]) > LONG_PATH_CHARS]
    if not items:
        return None
    return Issue(
        "LONG_PATH", "warn",
        "Chemins trop longs",
        f"Ces chemins dépassent {LONG_PATH_CHARS} caractères. FAT32 s'arrête "
        f"à 255, et le Deluge peut tronquer avant.",
        items=sorted(items)[:MAX_ITEMS],
        fix="Raccourcir les noms de dossiers intermédiaires.",
    )


def _check_deep_folders(lib: Library) -> Issue | None:
    items = [row["rel"] for _k, row in _all_rows(lib)
             if row["rel"].count("/") + 1 > DEEP_FOLDER_LEVELS]
    if not items:
        return None
    return Issue(
        "DEEP_FOLDER", "info",
        "Arborescence très profonde",
        f"Plus de {DEEP_FOLDER_LEVELS} niveaux de dossiers : la navigation "
        f"sur l'écran de la machine devient fastidieuse.",
        items=sorted(items)[:MAX_ITEMS],
        fix="Mettre à plat les dossiers les plus enfouis.",
    )


# -- qualité audio ---------------------------------------------------------- #

def _check_sample_rates(lib: Library) -> Issue | None:
    rows = [r for r in lib.search_samples(limit=100000)
            if r["sr"] and r["sr"] not in GOOD_SAMPLE_RATES]
    if not rows:
        return None
    rates = sorted({r["sr"] for r in rows})
    return Issue(
        "ODD_SAMPLE_RATE", "info",
        "Fréquences d'échantillonnage inhabituelles",
        f"Le Deluge tourne à 44,1 kHz. Ces fichiers "
        f"({', '.join(f'{r} Hz' for r in rates)}) seront convertis à la "
        f"lecture, ce qui consomme du calcul sans rien apporter.",
        items=[f"{r['rel']} ({r['sr']} Hz)" for r in rows[:MAX_ITEMS]],
        fix="Convertir ces échantillons en 44,1 kHz.",
    )


def _check_big_samples(lib: Library) -> Issue | None:
    rows = [r for r in lib.search_samples(limit=100000)
            if (r["size"] or 0) > BIG_SAMPLE_BYTES]
    if not rows:
        return None
    return Issue(
        "BIG_SAMPLE", "info",
        "Échantillons très volumineux",
        f"Au-delà de {BIG_SAMPLE_BYTES / 2 ** 20:.0f} Mio, le chargement "
        f"depuis la carte se fait sentir au déclenchement.",
        items=[f"{r['rel']} ({(r['size'] or 0) / 2 ** 20:.0f} Mio)"
               for r in sorted(rows, key=lambda r: -(r["size"] or 0))[:MAX_ITEMS]],
        fix="Raccourcir ou rééchantillonner ces fichiers.",
    )


def _check_stereo_drums(lib: Library) -> Issue | None:
    rows = [r for r in lib.search_samples(limit=100000)
            if (r["channels"] or 1) > 1
            and norm_rel(r["rel"]).startswith("samples/drums/")]
    if not rows:
        return None
    wasted = sum((r["size"] or 0) // 2 for r in rows)
    return Issue(
        "STEREO_DRUM", "info",
        "Percussions en stéréo",
        f"{len(rows)} percussion(s) sont stéréo. Dans un kit, une percussion "
        f"mono suffit presque toujours : passer en mono libérerait environ "
        f"{wasted / 2 ** 20:.0f} Mio et un peu de calcul.",
        items=[r["rel"] for r in rows[:MAX_ITEMS]],
        fix="Convertir ces échantillons en mono.",
    )


def _needs_analysis(lib: Library, column: str) -> bool:
    """Vrai si la colonne de mesure n'a jamais été remplie."""
    try:
        row = lib.con.execute(
            f"SELECT COUNT(*) FROM samples WHERE {column} IS NOT NULL"
        ).fetchone()
        return not row or not row[0]
    except Exception:  # noqa: BLE001
        return True


def _check_clipped(lib: Library) -> Issue | None:
    if _needs_analysis(lib, "clipped"):
        return None
    rows = [r for r in lib.search_samples(limit=100000)
            if (r["clipped"] or 0) > CLIPPED_RATIO]
    if not rows:
        return None
    return Issue(
        "CLIPPED_SAMPLE", "warn",
        "Échantillons écrêtés",
        "Ces fichiers saturent : une partie de la forme d'onde est coupée "
        "net. La distorsion est déjà dans le fichier, et elle ressortira "
        "amplifiée dans le mixage.",
        items=[f"{r['rel']} ({(r['clipped'] or 0) * 100:.1f} % d'échantillons "
               f"à fond)" for r in rows[:MAX_ITEMS]],
        fix="Réduire le niveau à la source, ou remplacer ces échantillons.",
    )


def _check_dc_offset(lib: Library) -> Issue | None:
    if _needs_analysis(lib, "dc_offset"):
        return None
    rows = [r for r in lib.search_samples(limit=100000)
            if abs(r["dc_offset"] or 0.0) > DC_OFFSET_LIMIT]
    if not rows:
        return None
    return Issue(
        "DC_OFFSET", "warn",
        "Échantillons avec une composante continue",
        "La forme d'onde n'est pas centrée sur zéro : cela gaspille de la "
        "dynamique, peut faire claquer le début du son et perturbe les "
        "mesures de niveau.",
        items=[f"{r['rel']} (offset {r['dc_offset']:+.3f})"
               for r in rows[:MAX_ITEMS]],
        fix="Appliquer un filtre coupe-continu lors de la conversion.",
    )


def _check_silent(lib: Library) -> Issue | None:
    if _needs_analysis(lib, "peak"):
        return None
    rows = [r for r in lib.search_samples(limit=100000)
            if r["peak"] is not None and (r["peak"] or 0) < 1e-4]
    if not rows:
        return None
    return Issue(
        "SILENT_SAMPLE", "warn",
        "Échantillons muets",
        "Ces fichiers ne contiennent aucun signal audible : ils occupent de "
        "la place sans rien jouer.",
        items=[r["rel"] for r in rows[:MAX_ITEMS]],
        fix="Vérifier puis supprimer ces fichiers.",
    )


# -- propreté du système de fichiers ---------------------------------------- #

def _check_mac_junk(sd: SDCard) -> Issue | None:
    plan = organize.plan_purge_junk(sd)
    if not plan.ops:
        return None
    total = 0
    for op in plan.ops:
        try:
            total += op.src.stat().st_size
        except OSError:
            pass
    return Issue(
        "MAC_JUNK", "warn",
        "Fichiers parasites",
        f"{len(plan.ops)} fichiers créés par macOS ou Windows "
        f"(« ._* », « .DS_Store », « Thumbs.db ») occupent "
        f"{total / 2 ** 20:.1f} Mio. Le Deluge peut les afficher comme des "
        f"presets fantômes dans ses listes.",
        items=[sd.rel(op.src) for op in plan.ops[:MAX_ITEMS]],
        fix="Les supprimer : ils ne servent à rien sur la carte.",
        auto_fixable=True,
    )


def _check_non_audio(sd: SDCard) -> Issue | None:
    from .sdcard import _is_ignored_dir, _is_ignored_file

    items: list[str] = []
    base = sd.abs("SAMPLES")
    if not base.is_dir():
        return None
    try:
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if not _is_ignored_dir(d)]
            for name in filenames:
                if _is_ignored_file(name):
                    continue
                if not name.lower().endswith(AUDIO_EXT):
                    items.append(sd.rel(Path(dirpath) / name))
    except OSError as exc:
        log.debug("parcours de SAMPLES impossible : %s", exc)
    if not items:
        return None
    return Issue(
        "NON_AUDIO_IN_SAMPLES", "info",
        "Fichiers non audio dans SAMPLES",
        "Ces fichiers ne sont ni des WAV ni des AIFF : fichiers "
        "d'accompagnement d'un logiciel de montage, notes, images… Le Deluge "
        "les ignore, mais ils encombrent la navigation.",
        items=sorted(items)[:MAX_ITEMS],
        fix="Les déplacer hors du dossier SAMPLES.",
    )


def _check_empty_folders(sd: SDCard) -> Issue | None:
    from .sdcard import _is_ignored_dir, _is_ignored_file

    items: list[str] = []
    for top in STD_DIRS:
        base = sd.abs(top)
        if not base.is_dir():
            continue
        try:
            for dirpath, dirnames, filenames in os.walk(base, topdown=False):
                dirnames[:] = [d for d in dirnames if not _is_ignored_dir(d)]
                keep = [f for f in filenames if not _is_ignored_file(f)]
                if keep or dirnames:
                    continue
                rel = sd.rel(Path(dirpath))
                # Les dossiers que le Deluge crée lui-même peuvent être vides.
                if norm_rel(rel) in STANDARD_EMPTY_OK:
                    continue
                items.append(rel)
        except OSError as exc:
            log.debug("parcours de %s impossible : %s", top, exc)
    if not items:
        return None
    return Issue(
        "EMPTY_FOLDER", "info",
        "Dossiers vides",
        "Ces dossiers ne contiennent rien et allongent inutilement les "
        "listes de la machine.",
        items=sorted(items)[:MAX_ITEMS],
        fix="Les supprimer.",
    )


def _check_backup(backup_dir: Path | None) -> Issue | None:
    """Signale l'absence de sauvegarde, ou une sauvegarde trop ancienne."""
    if backup_dir is None:
        return None
    from datetime import datetime

    from . import backup as backup_mod

    try:
        backups = backup_mod.list_backups(Path(backup_dir))
    except Exception as exc:  # noqa: BLE001
        log.debug("liste des sauvegardes indisponible : %s", exc)
        return None

    if not backups:
        return Issue(
            "NO_BACKUP", "warn",
            "Aucune sauvegarde",
            "Les morceaux et presets d'une carte représentent des mois de "
            "travail dans des fichiers de quelques kilooctets. Une sauvegarde "
            "sans les échantillons prend moins d'une seconde.",
            items=[str(backup_dir)],
            fix="Créer une sauvegarde depuis la page Sauvegardes.",
        )

    age = (datetime.now() - backups[0].when).days
    if age < 30:
        return None
    return Issue(
        "NO_BACKUP", "info",
        "Sauvegarde ancienne",
        f"La dernière sauvegarde date de {age} jours.",
        items=[backups[0].summary()],
        fix="Créer une nouvelle sauvegarde.",
    )


# --------------------------------------------------------------------------- #
# Réparation automatique
# --------------------------------------------------------------------------- #

#: Anomalies que :func:`autofix` sait traiter, et le plan correspondant.
AUTOFIX_CODES = ("MAC_JUNK", "BAD_NAME", "ORPHAN_SAMPLE", "DUPLICATE_SAMPLE",
                 "MISSING_STD_DIR", "MISSING_SAMPLE", "EMPTY_FOLDER")


def autofix(sd: SDCard, lib: Library, codes: list[str],
            apply: bool = False) -> Plan:
    """Construit un plan réparant les anomalies demandées.

    ``apply=False`` (défaut) retourne le plan sans rien exécuter : c'est à
    l'appelant d'appeler :meth:`Plan.apply` après confirmation de
    l'utilisateur (cf. SPEC §0.2).

    Les codes inconnus ou non réparables sont ignorés avec une trace.
    """
    wanted = set(codes or [])
    plan = Plan(title="Réparation automatique")

    for code in wanted - set(AUTOFIX_CODES):
        log.info("anomalie %s non réparable automatiquement", code)

    # L'ordre n'est pas libre : réparer les références AVANT d'archiver quoi
    # que ce soit. Un échantillon paraît inutilisé précisément parce que les
    # références qui le désignent sont cassées — c'est le cas des 130
    # échantillons « rephazer » de la carte d'essai. Archiver d'abord
    # déplaçait la cible de la réparation, et les 125 références restaient
    # cassées.
    relink_targets: set[str] = set()
    if "MISSING_SAMPLE" in wanted:
        try:
            relink = _plan_relink_missing(sd, lib)
            plan.ops += relink.ops
            relink_targets = {norm_rel(sd.rel(op.dst))
                              for op in relink.ops if op.dst is not None}
        except Exception:  # noqa: BLE001
            log.exception("construction du correctif MISSING_SAMPLE en échec")

    ordered = [c for c in ("MISSING_STD_DIR", "MAC_JUNK", "BAD_NAME",
                           "DUPLICATE_SAMPLE", "ORPHAN_SAMPLE", "EMPTY_FOLDER")
               if c in wanted]
    for code in ordered:
        try:
            if code == "MAC_JUNK":
                plan.ops += organize.plan_purge_junk(sd).ops
            elif code == "BAD_NAME":
                plan.ops += organize.plan_fix_names(sd, lib).ops
            elif code == "ORPHAN_SAMPLE":
                # Ne pas archiver un échantillon qui sert de cible à une
                # réparation de référence : il est sur le point de redevenir
                # utilisé.
                plan.ops += [
                    op for op in organize.plan_archive_unused(sd, lib).ops
                    if norm_rel(sd.rel(op.src)) not in relink_targets
                ]
            elif code == "DUPLICATE_SAMPLE":
                plan.ops += organize.plan_dedupe(sd, lib).ops
            elif code == "MISSING_STD_DIR":
                plan.ops += [organize.Op("mkdir", sd.abs(d), None,
                                         "dossier standard du Deluge")
                             for d in sd.missing_dirs()]
            elif code == "EMPTY_FOLDER":
                issue = _check_empty_folders(sd)
                if issue is not None:
                    plan.ops += [organize.Op("delete", sd.abs(rel), None,
                                             "dossier vide")
                                 for rel in issue.items]
        except Exception:  # noqa: BLE001
            log.exception("construction du correctif %s en échec", code)

    if apply:
        plan.apply(sd, lib)
    return plan


def _plan_relink_missing(sd: SDCard, lib: Library) -> Plan:
    """Plan de réaffectation des références cassées dont on a un remplaçant.

    Seul le **premier** candidat de chaque référence est retenu, et seulement
    quand il porte exactement le même nom de fichier : rediriger vers un
    fichier au nom approchant serait un pari, pas une réparation.
    """
    from . import deps

    plan = Plan(title="Réaffectation des références cassées")
    try:
        candidates = deps.find_replacements_bulk(sd, lib)
    except Exception as exc:  # noqa: BLE001
        log.exception("recherche de remplaçants en échec")
        return plan

    for missing, found in candidates.items():
        if not found:
            continue
        best = found[0]
        if Path(best).name.lower() != Path(missing).name.lower():
            continue
        plan.ops.append(organize.Op(
            "relink", sd.abs(missing), sd.abs(best),
            f"référence cassée redirigée vers {best}"))
    return plan
