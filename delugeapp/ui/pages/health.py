# -*- coding: utf-8 -*-
"""Page « Santé ».

Montre ce qui va mal sur la carte, et le répare — mais **jamais sans montrer
d'abord le plan exact des opérations**. C'est la règle du §0.2 de la SPEC, et
c'est ici qu'elle compte le plus : cette page peut déplacer des centaines de
fichiers et en supprimer.

Quatre onglets en plus du rapport : les doublons (confirmés octet pour octet),
les références cassées avec leurs remplaçants possibles, les échantillons
inutilisés, et les sauvegardes.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..theme import GOLD, PAD, PAD_GREEN, PAD_RED, severity_color
from ..widgets.common import (
    BusyBar,
    Card,
    EmptyState,
    PlanDialog,
    human_size,
)
from ...core import samplefix
from .base import Page, tool_button

log = logging.getLogger(__name__)


class HealthPage(Page):
    """Diagnostic et réparation de la carte."""

    TITLE = "Santé"
    EMPTY_DETAIL = ("Indiquez l'emplacement de votre carte dans les réglages. "
                    "Le diagnostic cherchera ensuite les doublons, les "
                    "sons manquants et les fichiers abîmés.")
    ICON = "health"

    #: La carte a changé : les autres pages doivent se rafraîchir.
    cardModified = pyqtSignal()

    def __init__(self, ctx, parent=None) -> None:
        super().__init__(ctx, parent)
        self._report = None
        #: Vrai dès que le diagnostic automatique a été tenté, pour ne pas
        #: le relancer à chaque fois que l'on revient sur la page.
        self._auto_done = False

    # -- construction ------------------------------------------------------- #

    def build(self) -> None:
        outer = QVBoxLayout(self.content())
        outer.setContentsMargins(PAD, PAD, PAD, PAD)
        outer.setSpacing(8)

        header, actions = self.header(
            "Santé de la carte", "Ce qui va mal, et comment le réparer")
        outer.addWidget(header)

        # Pas « Analyser » : la barre d'en-tête a déjà ce mot, pour relire
        # la carte. Ici on ne relit rien, on cherche ce qui va mal dans ce
        # que l'index contient déjà.
        analyse = tool_button(
            "Diagnostiquer", "health",
            "Cherche les anomalies dans l'index — sans relire la carte",
            primary=True)
        analyse.clicked.connect(self.guard(self._run_check))
        actions.addWidget(analyse)

        self._fix_button = tool_button(
            "Corriger automatiquement", "check",
            "Montre d'abord le plan exact des opérations")
        self._fix_button.clicked.connect(self.guard(self._autofix))
        self._fix_button.setEnabled(False)
        actions.addWidget(self._fix_button)

        export = tool_button("Exporter le rapport", "export")
        export.clicked.connect(self.guard(self._export))
        actions.addWidget(export)

        self._progress = BusyBar()
        self._progress.setVisible(False)
        outer.addWidget(self._progress)

        tabs = QTabWidget()
        tabs.addTab(self._build_report_tab(), "Rapport")
        tabs.addTab(self._build_duplicates_tab(), "Doublons")
        tabs.addTab(self._build_missing_tab(), "Manquants")
        tabs.addTab(self._build_unused_tab(), "Inutilisés")
        tabs.addTab(self._build_backup_tab(), "Sauvegardes")
        self._tabs = tabs
        outer.addWidget(tabs, 1)

    def _build_report_tab(self) -> QWidget:
        """Deux états : l'invitation à diagnostiquer, puis le rapport.

        Montrer des cadres vides revient à montrer une panne. Tant qu'aucun
        rapport n'existe, la page dit ce qu'elle fera et propose de le faire.
        """
        self._report_stack = QStackedWidget()

        self._report_empty = EmptyState(
            "Aucun diagnostic pour l'instant",
            "health", "Diagnostiquer",
            detail=("Le diagnostic lit l'index déjà constitué : il ne touche "
                    "pas à la carte, et prend moins d'une seconde. Il cherche "
                    "les doublons, les échantillons manquants, les fichiers "
                    "écrêtés et les presets abîmés."),
            color=self.color)
        self._report_empty.actionClicked.connect(self.guard(self._run_check))
        self._report_stack.addWidget(self._report_empty)

        host = QWidget()
        column = QVBoxLayout(host)
        column.setContentsMargins(0, PAD, 0, 0)
        column.setSpacing(8)

        head = QHBoxLayout()
        self._score = QLabel("—")
        self._score.setProperty("role", "value")
        head.addWidget(self._score)
        self._verdict = QLabel("Lancez une analyse.")
        self._verdict.setProperty("role", "subtitle")
        self._verdict.setWordWrap(True)
        head.addWidget(self._verdict, 1)
        column.addLayout(head)

        row = QHBoxLayout()
        row.setSpacing(8)

        left = Card("Anomalies")
        hint = QLabel("Cochez celles à corriger automatiquement.")
        hint.setProperty("role", "subtitle")
        left.body().addWidget(hint)
        self._issues = QListWidget()
        self._issues.currentRowChanged.connect(
            self.guard(self._show_issue))
        left.body().addWidget(self._issues)
        row.addWidget(left, 2)

        right = Card("Détail")
        self._detail = QTextBrowser()
        self._detail.setOpenExternalLinks(False)
        right.body().addWidget(self._detail)
        row.addWidget(right, 3)

        holder = QWidget()
        holder.setLayout(row)
        column.addWidget(holder, 1)

        self._report_stack.addWidget(host)
        return self._report_stack

    def _build_duplicates_tab(self) -> QWidget:
        host = QWidget()
        column = QVBoxLayout(host)
        column.setContentsMargins(0, PAD, 0, 0)
        column.setSpacing(8)

        hint = QLabel(
            "Groupes de fichiers **rigoureusement identiques**, vérifiés "
            "octet par octet. Une empreinte partielle ne suffit pas : elle "
            "déclarait identiques trois multi-échantillons qui diffèrent sur "
            "1 407 blocs.")
        hint.setProperty("role", "subtitle")
        hint.setWordWrap(True)
        column.addWidget(hint)

        row = QHBoxLayout()
        keep_label = QLabel("Exemplaire à conserver")
        keep_label.setProperty("role", "subtitle")
        row.addWidget(keep_label)
        self._keep = QComboBox()
        for label, value in (("Chemin le plus court", "shortest_path"),
                             ("Chemin le plus long", "longest_path"),
                             ("Le plus utilisé", "most_used"),
                             ("Le plus ancien", "oldest"),
                             ("Le plus récent", "newest")):
            self._keep.addItem(label, value)
        row.addWidget(self._keep)
        row.addStretch(1)
        dedupe = tool_button("Supprimer les doublons", "trash")
        dedupe.clicked.connect(self.guard(self._dedupe))
        row.addWidget(dedupe)
        column.addLayout(row)

        self._duplicates = QTableWidget(0, 3)
        self._duplicates.setHorizontalHeaderLabels(
            ["Groupe", "Fichiers", "Gaspillage"])
        self._duplicates.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self._duplicates.verticalHeader().setVisible(False)
        self._duplicates.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        column.addWidget(self._duplicates, 1)
        return host

    def _build_missing_tab(self) -> QWidget:
        host = QWidget()
        column = QVBoxLayout(host)
        column.setContentsMargins(0, PAD, 0, 0)
        column.setSpacing(8)

        hint = QLabel(
            "Échantillons réclamés par un preset, un kit ou un morceau, mais "
            "absents de la carte. Un remplaçant portant exactement le même "
            "nom de fichier peut être relié automatiquement.")
        hint.setProperty("role", "subtitle")
        hint.setWordWrap(True)
        column.addWidget(hint)

        row = QHBoxLayout()
        row.addStretch(1)
        search = tool_button("Chercher des remplaçants", "search")
        search.clicked.connect(self.guard(self._find_replacements))
        row.addWidget(search)
        relink = tool_button("Relier automatiquement", "link", primary=True)
        relink.clicked.connect(self.guard(self._relink))
        row.addWidget(relink)
        column.addLayout(row)

        self._missing = QTableWidget(0, 3)
        self._missing.setHorizontalHeaderLabels(
            ["Échantillon réclamé", "Réclamé par", "Remplaçant proposé"])
        self._missing.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self._missing.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch)
        self._missing.verticalHeader().setVisible(False)
        self._missing.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        column.addWidget(self._missing, 1)
        return host

    def _build_unused_tab(self) -> QWidget:
        host = QWidget()
        column = QVBoxLayout(host)
        column.setContentsMargins(0, PAD, 0, 0)
        column.setSpacing(8)

        hint = QLabel(
            "Échantillons qu'aucun fichier de la carte ne cite. Ce n'est pas "
            "un défaut : votre bibliothèque peut contenir des sons en "
            "réserve. L'archivage les **déplace**, il ne les supprime pas.")
        hint.setProperty("role", "subtitle")
        hint.setWordWrap(True)
        column.addWidget(hint)

        row = QHBoxLayout()
        self._unused_total = QLabel("")
        self._unused_total.setProperty("role", "subtitle")
        row.addWidget(self._unused_total)
        row.addStretch(1)
        archive = tool_button("Archiver dans _UNUSED", "export")
        archive.clicked.connect(self.guard(self._archive_unused))
        row.addWidget(archive)
        column.addLayout(row)

        self._unused = QTableWidget(0, 3)
        self._unused.setHorizontalHeaderLabels(
            ["Fichier", "Durée", "Taille"])
        self._unused.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self._unused.verticalHeader().setVisible(False)
        self._unused.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        column.addWidget(self._unused, 1)
        return host

    def _build_backup_tab(self) -> QWidget:
        host = QWidget()
        column = QVBoxLayout(host)
        column.setContentsMargins(0, PAD, 0, 0)
        column.setSpacing(8)

        hint = QLabel(
            "Les morceaux, presets et kits de la carte tiennent dans "
            "quelques mégaoctets : une sauvegarde sans les échantillons "
            "prend moins d'une seconde et peut donc être faite souvent.")
        hint.setProperty("role", "subtitle")
        hint.setWordWrap(True)
        column.addWidget(hint)

        row = QHBoxLayout()
        self._with_samples = QCheckBox("Inclure les échantillons")
        self._with_samples.setToolTip(
            "Plus d'un gigaoctet sur cette carte : à réserver aux "
            "sauvegardes complètes.")
        row.addWidget(self._with_samples)
        self._zip = QCheckBox("Compresser en .zip")
        row.addWidget(self._zip)
        row.addStretch(1)

        create = tool_button("Sauvegarder maintenant", "backup", primary=True)
        create.clicked.connect(self.guard(self._create_backup))
        row.addWidget(create)
        compare = tool_button("Comparer", "copy")
        compare.clicked.connect(self.guard(self._diff_backup))
        row.addWidget(compare)
        restore = tool_button("Restaurer", "import")
        restore.clicked.connect(self.guard(self._restore_backup))
        row.addWidget(restore)
        column.addLayout(row)

        self._backups = QTableWidget(0, 4)
        self._backups.setHorizontalHeaderLabels(
            ["Date", "Libellé", "Fichiers", "Taille"])
        self._backups.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self._backups.verticalHeader().setVisible(False)
        self._backups.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._backups.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        column.addWidget(self._backups, 1)
        return host

    # -- diagnostic --------------------------------------------------------- #

    def _run_check(self) -> None:
        card = self.card_or_warn()
        if card is None:
            return
        self._progress.setVisible(True)
        self._progress.set_busy(True)
        self.say("Diagnostic en cours…")
        self.run(self._check, card,
                 on_result=self.guard(self._check_done),
                 on_error=self.guard(self._check_failed),
                 title="Diagnostic")

    def _vaut_le_coup(self) -> bool:
        """Y a-t-il de quoi diagnostiquer ?

        Sur un index vide, les contrôles ne trouvent rien à redire et la note
        monte à 98/100 : annoncer « carte en très bon état » alors que rien
        n'a été lu serait un mensonge — le tableau de bord se garde déjà de
        le faire. On attend donc la première analyse de la carte.
        """
        if self.sd is None:
            return False
        try:
            stats = self.lib.stats()
        except Exception as exc:        # noqa: BLE001
            log.debug("statistiques indisponibles : %s", exc)
            return False
        return any(int(stats.get(cle, 0) or 0) > 0
                   for cle in ("samples", "synths", "kits", "songs"))

    def _check(self, card):
        from ...core import health as health_mod

        return health_mod.check_card(
            card, self.lib, backup_dir=self.ctx.settings.backup_path())

    def _check_done(self, report) -> None:
        self._progress.setVisible(False)
        self._report = report
        if report is None:
            return
        self._fill_report(report)
        self._fill_duplicates()
        self._fill_missing()
        self._fill_unused()
        self._fill_backups()
        self.say(f"Diagnostic : {report.score}/100 — {report.verdict()}")

    def _check_failed(self, message: str) -> None:
        self._progress.setVisible(False)
        self.say(f"Diagnostic impossible : {message}")

    def _fill_report(self, report) -> None:
        self._report_stack.setCurrentIndex(1)
        self._score.setText(str(report.score))
        self._score.setStyleSheet(f"color: {self._colour(report.score)};")
        self._verdict.setText(report.verdict())

        self._issues.clear()
        order = {"error": 0, "warn": 1, "info": 2}
        for issue in sorted(report.issues,
                            key=lambda i: (order.get(i.severity, 3),
                                           -i.count)):
            item = QListWidgetItem(f"{issue.title}  ({issue.count})")
            item.setForeground(Qt.GlobalColor.white)
            item.setData(Qt.ItemDataRole.UserRole, issue.code)
            if issue.auto_fixable or issue.code in samplefix.HEALTH_CODES:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
                item.setToolTip("Réparable automatiquement")
            else:
                item.setToolTip("À corriger à la main")
            item.setForeground(
                Qt.GlobalColor.white)
            self._issues.addItem(item)

        self._fix_button.setEnabled(
            bool(report.auto_fixable())
            or any(i.code in samplefix.HEALTH_CODES for i in report.issues))
        if report.issues:
            self._issues.setCurrentRow(0)
        else:
            self._detail.setHtml(
                "<p style='color:#3DD160'>Aucune anomalie détectée.</p>")

    @staticmethod
    def _colour(score: int) -> str:
        if score >= 90:
            return PAD_GREEN
        if score >= 70:
            return GOLD
        return PAD_RED

    def _show_issue(self, row: int) -> None:
        if self._report is None or not 0 <= row < self._issues.count():
            return
        code = self._issues.item(row).data(Qt.ItemDataRole.UserRole)
        issue = next((i for i in self._report.issues if i.code == code), None)
        if issue is None:
            return

        def esc(text) -> str:
            return (str(text).replace("&", "&amp;").replace("<", "&lt;")
                    .replace(">", "&gt;"))

        items = "".join(f"<li>{esc(x)}</li>" for x in issue.items[:400])
        more = ("" if issue.count <= 400 else
                f"<p style='color:#7A828F'>… et {issue.count - 400} autre(s)</p>")
        fix = (f"<p style='color:#C79A22'>À faire : {esc(issue.fix)}</p>"
               if issue.fix else "")
        self._detail.setHtml(
            f"<h3 style='color:{severity_color(issue.severity)}'>"
            f"{esc(issue.title)}</h3>"
            f"<p>{esc(issue.detail)}</p>{fix}"
            f"<ul style='color:#C3C9D2'>{items}</ul>{more}")

    def _checked_codes(self) -> list[str]:
        out = []
        for index in range(self._issues.count()):
            item = self._issues.item(index)
            if item.checkState() == Qt.CheckState.Checked:
                out.append(item.data(Qt.ItemDataRole.UserRole))
        return out

    # -- réparation --------------------------------------------------------- #

    def _autofix(self) -> None:
        """Construit le plan, le montre, puis l'applique si accepté."""
        card = self.card_or_warn()
        if card is None or self._report is None:
            return
        codes = self._checked_codes()
        if not codes:
            QMessageBox.information(
                self, "Rien à corriger",
                "Cochez dans la liste les anomalies à corriger.")
            return

        from ...core import health as health_mod

        # Deux familles de corrections, deux moteurs : ``health.autofix``
        # déplace et relie des fichiers, ``samplefix`` réécrit leur contenu.
        # Chacune a sa confirmation, pour que l'utilisateur voie exactement
        # ce que chaque moteur va faire.
        audio = [c for c in codes if c in samplefix.HEALTH_CODES]
        autres = [c for c in codes if c not in samplefix.HEALTH_CODES]
        fait = False

        if autres:
            plan = health_mod.autofix(card, self.lib, autres, apply=False)
            if plan:
                fait = True
                self._apply_plan(plan, "Correction automatique")

        if audio:
            fix = samplefix.plan_from_health(card, self.lib, audio)
            if fix:
                fait = True
                self._apply_fix(fix)

        if not fait:
            self.say("Rien à faire pour les anomalies cochées.")

    def _apply_plan(self, plan, title: str) -> None:
        """Montre le plan et l'applique après accord explicite."""
        card = self.card_or_warn()
        if card is None:
            return
        dialog = PlanDialog(plan, self, title)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self.say("Opération annulée.")
            return

        self.say("Application du plan…")
        self.run(self._do_apply, plan, card,
                 on_result=self.guard(self._plan_done),
                 on_error=self.guard(
                     lambda m: self.say(f"Échec : {m}")),
                 title=title)

    def _do_apply(self, plan, card):
        return plan.apply(card, self.lib)

    # -- correction audio --------------------------------------------------- #

    def _apply_fix(self, plan) -> None:
        """Montre un plan de correction audio, puis l'exécute si accepté."""
        card = self.card_or_warn()
        if card is None:
            return
        dialog = PlanDialog(plan, self, "Correction des défauts audio")
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self.say("Correction annulée.")
            return

        self.say("Correction des fichiers…")
        self.run(self._do_fix, plan, card,
                 on_result=self.guard(self._fix_done),
                 on_error=self.guard(lambda m: self.say(f"Échec : {m}")),
                 title="Correction audio")

    def _do_fix(self, plan, card, progress=None, should_stop=None):
        return plan.apply(card, self.lib, progress=progress,
                          should_stop=should_stop)

    def _fix_done(self, result) -> None:
        if result is None:
            return
        if result.failed:
            detail = "\n".join("%s : %s" % (rel, msg)
                               for rel, msg in result.failed[:12])
            QMessageBox.warning(
                self, "Correction partielle",
                "%d fichier(s) corrigés, %d en échec :\n\n%s"
                % (len(result.done), len(result.failed), detail))
        if result.backup_dir:
            self.say("%s Originaux conservés dans %s."
                     % (result.summary(), result.backup_dir))
        else:
            self.say(result.summary())
        self.cardModified.emit()
        self._run_check()

    def _plan_done(self, result) -> None:
        if result is None:
            return
        done, errors = result
        if errors:
            QMessageBox.warning(
                self, "Opérations partiellement effectuées",
                f"{done} opération(s) réussie(s), {len(errors)} en échec :\n\n"
                + "\n".join(errors[:12]))
        self.say(f"{done} opération(s) effectuée(s), "
                 f"{len(errors)} erreur(s).")
        self.cardModified.emit()
        self._run_check()

    # -- doublons ----------------------------------------------------------- #

    def _fill_duplicates(self) -> None:
        self._duplicates.setRowCount(0)
        try:
            groups = self.lib.duplicates()
        except Exception as exc:  # noqa: BLE001
            log.debug("doublons indisponibles : %s", exc)
            return
        for index, group in enumerate(groups, 1):
            row = self._duplicates.rowCount()
            self._duplicates.insertRow(row)
            self._duplicates.setItem(row, 0, QTableWidgetItem(str(index)))
            names = "   =   ".join(r["rel"] for r in group)
            item = QTableWidgetItem(names)
            item.setToolTip(names.replace("   =   ", "\n= "))
            self._duplicates.setItem(row, 1, item)
            wasted = sum(r["size"] or 0 for r in group[1:])
            self._duplicates.setItem(row, 2,
                                     QTableWidgetItem(human_size(wasted)))

    def _dedupe(self) -> None:
        card = self.card_or_warn()
        if card is None:
            return
        from ...core import organize

        plan = organize.plan_dedupe(card, self.lib,
                                    keep=self._keep.currentData()
                                    or "shortest_path")
        if not plan:
            self.say("Aucun doublon confirmé à supprimer.")
            return
        self._apply_plan(plan, "Suppression des doublons")

    # -- manquants ---------------------------------------------------------- #

    def _fill_missing(self) -> None:
        self._missing.setRowCount(0)
        try:
            links = self.lib.missing_links()
        except Exception as exc:  # noqa: BLE001
            log.debug("références cassées indisponibles : %s", exc)
            return
        # Regroupées par échantillon : un même fichier manque souvent à
        # plusieurs presets.
        grouped: dict[str, list[str]] = {}
        for link in links:
            grouped.setdefault(link["dst_rel"], []).append(link["src_rel"])

        for ref, sources in sorted(grouped.items()):
            row = self._missing.rowCount()
            self._missing.insertRow(row)
            item = QTableWidgetItem(ref)
            item.setToolTip(ref)
            self._missing.setItem(row, 0, item)
            label = (sources[0] if len(sources) == 1
                     else f"{len(sources)} fichiers")
            source_item = QTableWidgetItem(label)
            source_item.setToolTip("\n".join(sources))
            self._missing.setItem(row, 1, source_item)
            self._missing.setItem(row, 2, QTableWidgetItem("—"))

    def _find_replacements(self) -> None:
        card = self.card_or_warn()
        if card is None:
            return
        self.say("Recherche de remplaçants…")
        self.run(self._search_replacements, card,
                 on_result=self.guard(self._show_replacements),
                 on_error=self.guard(
                     lambda m: self.say(f"Recherche impossible : {m}")),
                 title="Recherche de remplaçants")

    def _search_replacements(self, card):
        from ...core import deps

        return deps.find_replacements_bulk(card, self.lib)

    def _show_replacements(self, found) -> None:
        if not found:
            self.say("Aucun remplaçant trouvé.")
            return
        exact = 0
        for row in range(self._missing.rowCount()):
            ref = self._missing.item(row, 0).text()
            candidates = found.get(ref) or []
            if not candidates:
                self._missing.setItem(row, 2,
                                      QTableWidgetItem("aucun"))
                continue
            best = candidates[0]
            same_name = (Path(best).name.lower()
                         == Path(ref).name.lower())
            if same_name:
                exact += 1
            item = QTableWidgetItem(best)
            item.setToolTip("\n".join(candidates[:8]))
            item.setForeground(Qt.GlobalColor.green if same_name
                               else Qt.GlobalColor.yellow)
            self._missing.setItem(row, 2, item)
        self.say(f"{exact} remplaçant(s) de nom identique sur "
                 f"{self._missing.rowCount()} référence(s) cassée(s).")

    def _relink(self) -> None:
        """Répare les références cassées dont le remplaçant est certain."""
        card = self.card_or_warn()
        if card is None:
            return
        from ...core import health as health_mod

        plan = health_mod.autofix(card, self.lib, ["MISSING_SAMPLE"],
                                  apply=False)
        if not plan:
            self.say("Aucune référence cassée ne peut être reliée "
                     "automatiquement.")
            return
        self._apply_plan(plan, "Réparation des références")

    # -- inutilisés --------------------------------------------------------- #

    def _fill_unused(self) -> None:
        from ..widgets.common import human_duration

        self._unused.setRowCount(0)
        try:
            rows = self.lib.unused_samples()
        except Exception as exc:  # noqa: BLE001
            log.debug("inutilisés indisponibles : %s", exc)
            return
        total = sum(r["size"] or 0 for r in rows)
        self._unused_total.setText(
            f"{len(rows)} échantillon(s), {human_size(total)} au total")
        for row in rows[:5000]:
            index = self._unused.rowCount()
            self._unused.insertRow(index)
            item = QTableWidgetItem(row["rel"])
            item.setToolTip(row["rel"])
            self._unused.setItem(index, 0, item)
            self._unused.setItem(
                index, 1, QTableWidgetItem(human_duration(row["duration"])))
            self._unused.setItem(
                index, 2, QTableWidgetItem(human_size(row["size"])))

    def _archive_unused(self) -> None:
        card = self.card_or_warn()
        if card is None:
            return
        from ...core import organize

        plan = organize.plan_archive_unused(card, self.lib)
        if not plan:
            self.say("Aucun échantillon inutilisé.")
            return
        self._apply_plan(plan, "Archivage des échantillons inutilisés")

    # -- sauvegardes -------------------------------------------------------- #

    def _backup_dir(self) -> Path:
        return Path(self.ctx.settings.backup_path())

    def _fill_backups(self) -> None:
        from ...core import backup as backup_mod

        self._backups.setRowCount(0)
        try:
            items = backup_mod.list_backups(self._backup_dir())
        except Exception as exc:  # noqa: BLE001
            log.debug("sauvegardes indisponibles : %s", exc)
            return
        for info in items:
            row = self._backups.rowCount()
            self._backups.insertRow(row)
            self._backups.setItem(
                row, 0,
                QTableWidgetItem(info.when.strftime("%d/%m/%Y %Hh%M")))
            label = info.label or "—"
            if info.zipped:
                label += "  (archive)"
            if info.include_samples:
                label += "  (avec échantillons)"
            self._backups.setItem(row, 1, QTableWidgetItem(label))
            self._backups.setItem(row, 2,
                                  QTableWidgetItem(str(info.files)))
            self._backups.setItem(row, 3,
                                  QTableWidgetItem(human_size(info.bytes)))
            self._backups.item(row, 0).setData(Qt.ItemDataRole.UserRole,
                                               str(info.path))

    def _selected_backup(self):
        from ...core import backup as backup_mod

        row = self._backups.currentRow()
        if row < 0:
            return None
        wanted = self._backups.item(row, 0).data(Qt.ItemDataRole.UserRole)
        for info in backup_mod.list_backups(self._backup_dir()):
            if str(info.path) == wanted:
                return info
        return None

    def _create_backup(self) -> None:
        card = self.card_or_warn()
        if card is None:
            return
        from ...core import backup as backup_mod

        self.say("Sauvegarde en cours…")
        self.run(backup_mod.create_backup, card, self._backup_dir(),
                 label="manuelle",
                 include_samples=self._with_samples.isChecked(),
                 zip_it=self._zip.isChecked(),
                 on_result=self.guard(self._backup_done),
                 on_error=self.guard(
                     lambda m: self.say(f"Sauvegarde impossible : {m}")),
                 title="Sauvegarde")

    def _backup_done(self, info) -> None:
        if info is None:
            return
        self.say(f"Sauvegarde créée : {info.summary()}")
        self._fill_backups()

    def _diff_backup(self) -> None:
        card = self.card_or_warn()
        if card is None:
            return
        info = self._selected_backup()
        if info is None:
            self.say("Choisissez une sauvegarde.")
            return
        from ...core import backup as backup_mod

        diff = backup_mod.diff_backup(info, card)
        lines = [
            f"Inchangés : {diff['unchanged']}",
            f"Modifiés depuis la sauvegarde : {len(diff['changed'])}",
            f"Ajoutés depuis la sauvegarde : {len(diff['added'])}",
            f"Retirés depuis la sauvegarde : {len(diff['removed'])}",
        ]
        for key, title in (("changed", "Modifiés"), ("added", "Ajoutés"),
                           ("removed", "Retirés")):
            if diff[key]:
                lines.append("")
                lines.append(f"{title} :")
                lines += [f"  {x}" for x in diff[key][:20]]
                if len(diff[key]) > 20:
                    lines.append(f"  … et {len(diff[key]) - 20} autre(s)")

        box = QMessageBox(self)
        box.setWindowTitle("Comparaison avec la sauvegarde")
        box.setText(f"Sauvegarde du {info.when.strftime('%d/%m/%Y à %Hh%M')}")
        box.setDetailedText("\n".join(lines))
        box.exec()

    def _restore_backup(self) -> None:
        card = self.card_or_warn()
        if card is None:
            return
        info = self._selected_backup()
        if info is None:
            self.say("Choisissez une sauvegarde.")
            return

        from ...core import backup as backup_mod

        # On montre d'abord ce qui serait écrasé : une restauration remplace
        # les fichiers de la carte, c'est irréversible.
        count, _errors = backup_mod.restore_backup(info, card, apply=False)
        if count == 0:
            QMessageBox.information(
                self, "Rien à restaurer",
                "La carte est déjà identique à cette sauvegarde.")
            return

        answer = QMessageBox.warning(
            self, "Restaurer la sauvegarde",
            f"{count} fichier(s) de la carte vont être remplacés par ceux "
            f"de la sauvegarde du "
            f"{info.when.strftime('%d/%m/%Y à %Hh%M')}.\n\n"
            f"Cette opération est irréversible.\n\nContinuer ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.say("Restauration…")
        self.run(backup_mod.restore_backup, info, card,
                 on_result=self.guard(self._restore_done),
                 on_error=self.guard(
                     lambda m: self.say(f"Restauration impossible : {m}")),
                 title="Restauration")

    def _restore_done(self, result) -> None:
        if result is None:
            return
        restored, errors = result
        self.say(f"{restored} fichier(s) restauré(s), "
                 f"{len(errors)} erreur(s).")
        self.cardModified.emit()

    # -- export ------------------------------------------------------------- #

    def _export(self) -> None:
        if self._report is None:
            self.say("Lancez d'abord une analyse.")
            return
        from PyQt6.QtWidgets import QFileDialog

        chosen, _f = QFileDialog.getSaveFileName(
            self, "Exporter le rapport de santé", "sante-carte.html",
            "Page HTML (*.html)")
        if not chosen:
            return
        try:
            Path(chosen).write_text(self._report.to_html(), encoding="utf-8")
        except OSError as exc:
            log.exception("écriture du rapport impossible")
            self.say(f"Écriture impossible : {exc}")
            return
        self.say(f"Rapport enregistré : {Path(chosen).name}")

    # -- rafraîchissement --------------------------------------------------- #

    def _refresh(self) -> None:
        # Le diagnostic n'est **pas** relancé à chaque affichage : il part
        # tout seul la première fois, puis reste à la demande. Sans cela, la
        # page s'ouvrait sur deux cadres vides et il fallait deviner qu'un
        # bouton les remplirait.
        self._fill_backups()
        if self._report is None and not self._auto_done and self._vaut_le_coup():
            self._auto_done = True
            self._run_check()
            return
        if self._report is None:
            self._fill_duplicates()
            self._fill_missing()
            self._fill_unused()
