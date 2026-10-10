# -*- coding: utf-8 -*-
"""Page « Tableau de bord ».

La première chose que voit l'utilisateur : ce que contient sa carte, dans quel
état elle est, et les quatre ou cinq gestes qu'il fait le plus souvent.

L'analyse de la carte part d'ici, dans un fil séparé : sur la carte d'essai
elle prend deux secondes, mais sur une carte lue par un lecteur USB lent elle
peut durer bien plus, et l'interface doit rester vivante (SPEC §6.2).
"""

from __future__ import annotations

import logging
from datetime import datetime

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...core.scan import scan_card
from ..theme import (
    GOLD,
    GREY,
    PAD,
    PAD_CYAN,
    PAD_GREEN,
    PAD_MAGENTA,
    PAD_WHITE,
    PANEL_HI,
    pad_color,
    severity_color,
)
from ..widgets.common import (
    BusyBar,
    Card,
    ElidedLabel,
    StatTile,
    human_duration,
    human_size,
)
from .base import Page, page_header, tool_button

log = logging.getLogger(__name__)

#: Nombre de dossiers montrés dans la répartition.
TOP_FOLDERS = 10


class DashboardPage(Page):
    """Vue d'ensemble de la carte."""

    TITLE = "Tableau de bord"
    ICON = "dashboard"

    #: Demande d'aller sur une autre page, par son nom de classe abrégé.
    navigateRequested = pyqtSignal(str)
    #: L'analyse vient de se terminer : les autres pages doivent se rafraîchir.
    scanFinished = pyqtSignal()

    def __init__(self, ctx, parent=None) -> None:
        super().__init__(ctx, parent)
        self._worker = None
        self._tiles: dict[str, StatTile] = {}

    # -- construction ------------------------------------------------------- #

    def build(self) -> None:
        outer = QVBoxLayout(self.content())
        outer.setContentsMargins(PAD, PAD, PAD, PAD)
        outer.setSpacing(PAD)

        header, actions = page_header(
            "Tableau de bord", "Ce que contient la carte, et son état")
        outer.addWidget(header)

        self._scan_button = tool_button(
            "Analyser la carte", "refresh",
            "Relit la carte et met l'index à jour", primary=True)
        self._scan_button.clicked.connect(self.guard(self._start_scan))
        actions.addWidget(self._scan_button)

        self._stop_button = tool_button("Arrêter", "stop")
        self._stop_button.clicked.connect(self.guard(self._stop_scan))
        self._stop_button.setVisible(False)
        actions.addWidget(self._stop_button)

        self._progress = BusyBar()
        self._progress.setVisible(False)
        outer.addWidget(self._progress)

        self._progress_label = QLabel()
        self._progress_label.setProperty("role", "subtitle")
        self._progress_label.setVisible(False)
        outer.addWidget(self._progress_label)

        scroll = QScrollArea(self.content())
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        inner = QWidget()
        column = QVBoxLayout(inner)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(PAD)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

        column.addWidget(self._build_tiles())
        column.addWidget(self._build_card_info())

        row = QHBoxLayout()
        row.setSpacing(PAD)
        row.addWidget(self._build_health(), 1)
        row.addWidget(self._build_actions(), 1)
        holder = QWidget()
        holder.setLayout(row)
        column.addWidget(holder)

        column.addWidget(self._build_folders())
        column.addStretch(1)

    def _build_tiles(self) -> QWidget:
        """Les six tuiles chiffrées."""
        card = Card("Contenu de la carte")
        grid = QGridLayout()
        grid.setSpacing(8)

        definitions = (
            ("samples", "Échantillons", "samples", PAD_CYAN, "Samples"),
            ("synths", "Presets de synthé", "synth", pad_color(9), "Synths"),
            ("kits", "Kits", "kit", pad_color(4), "Kits"),
            ("songs", "Morceaux", "song", pad_color(1), "Songs"),
            ("audio", "Durée d'audio", "wave", pad_color(5), ""),
            ("space", "Espace libre", "backup", pad_color(7), ""),
        )
        for index, (key, label, icon, colour, target) in enumerate(definitions):
            tile = StatTile(label, "—", colour, icon)
            if target:
                tile.clicked.connect(
                    self.guard(lambda _c=False, t=target:
                               self.navigateRequested.emit(t)))
                tile.setToolTip(f"Ouvrir la page « {label} »")
            grid.addWidget(tile, index // 3, index % 3)
            self._tiles[key] = tile
        card.body().addLayout(grid)
        return card

    def _build_card_info(self) -> QWidget:
        card = Card("Carte")
        body = card.body()

        self._card_path = ElidedLabel("—")
        self._card_path.setProperty("role", "mono")
        body.addWidget(self._card_path)

        self._space_bar = QProgressBar()
        self._space_bar.setTextVisible(False)
        self._space_bar.setFixedHeight(8)
        body.addWidget(self._space_bar)

        self._card_detail = QLabel("—")
        self._card_detail.setProperty("role", "subtitle")
        body.addWidget(self._card_detail)

        self._last_scan = QLabel("—")
        self._last_scan.setProperty("role", "subtitle")
        body.addWidget(self._last_scan)
        return card

    def _build_health(self) -> QWidget:
        card = Card("État de santé")
        body = card.body()

        row = QHBoxLayout()
        self._score = QLabel("—")
        self._score.setProperty("role", "value")
        row.addWidget(self._score)
        self._verdict = QLabel("Analyse non lancée")
        self._verdict.setProperty("role", "subtitle")
        self._verdict.setWordWrap(True)
        row.addWidget(self._verdict, 1)
        body.addLayout(row)

        self._issues = QVBoxLayout()
        self._issues.setSpacing(3)
        body.addLayout(self._issues)

        open_health = tool_button("Voir le détail", "health")
        open_health.clicked.connect(
            self.guard(lambda: self.navigateRequested.emit("Health")))
        body.addWidget(open_health)
        return card

    def _build_actions(self) -> QWidget:
        card = Card("Actions rapides")
        grid = QGridLayout()
        grid.setSpacing(6)
        shortcuts = (
            ("Générer un preset", "wand", "Generator"),
            ("Construire un kit", "kit", "Generator"),
            ("Boîte à outils", "tools", "Toolbox"),
            ("Sauvegarder", "backup", "Health"),
            ("Nettoyer la carte", "check", "Health"),
            ("Réglages", "settings", "Settings"),
        )
        for index, (label, icon, target) in enumerate(shortcuts):
            button = tool_button(label, icon)
            button.setSizePolicy(QSizePolicy.Policy.Expanding,
                                 QSizePolicy.Policy.Fixed)
            button.clicked.connect(
                self.guard(lambda _c=False, t=target:
                           self.navigateRequested.emit(t)))
            grid.addWidget(button, index // 2, index % 2)
        card.body().addLayout(grid)
        return card

    def _build_folders(self) -> QWidget:
        card = Card("Répartition des échantillons")
        self._folders = QVBoxLayout()
        self._folders.setSpacing(4)
        card.body().addLayout(self._folders)
        return card

    # -- analyse ------------------------------------------------------------ #

    def _start_scan(self, full: bool = True) -> None:
        """Lance l'analyse de la carte dans un fil séparé."""
        card = self.card_or_warn()
        if card is None:
            return
        if self._worker is not None:
            self.say("Une analyse est déjà en cours.")
            return

        settings = self.ctx.settings
        self._scan_button.setEnabled(False)
        self._stop_button.setVisible(True)
        self._progress.setVisible(True)
        self._progress.set_busy(True)
        self._progress_label.setVisible(True)
        self._progress_label.setText("Inventaire de la carte…")

        self._worker = self.run(
            scan_card, card, self.lib,
            compute_hash=bool(settings.scan_hash),
            analyze=bool(settings.scan_analyze),
            full=bool(full),
            on_result=self.guard(self._scan_done),
            on_progress=self._scan_progress,
            on_error=self.guard(self._scan_failed),
            title="Analyse de la carte")

    def _stop_scan(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.say("Arrêt demandé…")

    def _scan_progress(self, payload) -> None:
        """Affiche l'avancement sans jamais lever."""
        try:
            message = getattr(payload, "message", "") or ""
            current = getattr(payload, "current", 0) or 0
            total = getattr(payload, "total", 0) or 0
            self._progress.set_progress(int(current), int(total))
            self._progress_label.setText(
                f"{message} ({current}/{total})" if total else message)
        except Exception as exc:  # noqa: BLE001
            log.debug("affichage de l'avancement impossible : %s", exc)

    def _scan_end(self) -> None:
        self._worker = None
        self._scan_button.setEnabled(True)
        self._stop_button.setVisible(False)
        self._progress.setVisible(False)
        self._progress_label.setVisible(False)

    def _scan_done(self, result) -> None:
        self._scan_end()
        if result is None:
            return
        self.say(result.summary())
        if result.errors:
            log.warning("analyse terminée avec %d erreur(s)",
                        len(result.errors))
        self._refresh()
        self.scanFinished.emit()

    def _scan_failed(self, message: str) -> None:
        self._scan_end()
        self.say(f"Analyse impossible : {message}")

    # -- rafraîchissement --------------------------------------------------- #

    def _refresh(self) -> None:
        stats = self._stats()
        self._fill_tiles(stats)
        self._fill_card_info(stats)
        self._fill_health(stats)
        self._fill_folders()

    def _stats(self) -> dict:
        try:
            return self.lib.stats()
        except Exception as exc:  # noqa: BLE001
            log.debug("statistiques indisponibles : %s", exc)
            return {}

    def _fill_tiles(self, stats: dict) -> None:
        self._tiles["samples"].set_value(f"{stats.get('samples', 0):,}"
                                         .replace(",", " "))
        self._tiles["synths"].set_value(stats.get("synths", 0))
        self._tiles["kits"].set_value(stats.get("kits", 0))
        self._tiles["songs"].set_value(stats.get("songs", 0))
        self._tiles["audio"].set_value(
            human_duration(stats.get("sample_seconds", 0)))

        free, total = (0, 0)
        if self.sd is not None:
            try:
                free, total = self.sd.free_space()
            except Exception as exc:  # noqa: BLE001
                log.debug("espace disque indisponible : %s", exc)
        self._tiles["space"].set_value(human_size(free) if total else "—")

    def _fill_card_info(self, stats: dict) -> None:
        if self.sd is None:
            self._card_path.setText("Aucune carte")
            return
        self._card_path.setText(str(self.sd.root))

        free, total = 0, 0
        try:
            free, total = self.sd.free_space()
        except Exception as exc:  # noqa: BLE001
            log.debug("espace disque indisponible : %s", exc)

        if total > 0:
            used = total - free
            self._space_bar.setRange(0, 100)
            self._space_bar.setValue(int(round(used / total * 100)))
            self._card_detail.setText(
                f"{human_size(used)} utilisés sur {human_size(total)} — "
                f"dont {human_size(stats.get('sample_bytes', 0))} "
                f"d'échantillons")
        else:
            self._space_bar.setRange(0, 100)
            self._space_bar.setValue(0)
            self._card_detail.setText("Espace disque indisponible.")

        last = stats.get("last_scan") or ""
        if last:
            try:
                when = datetime.fromisoformat(last)
                self._last_scan.setText(
                    "Dernière analyse : "
                    + when.strftime("%d/%m/%Y à %Hh%M"))
            except ValueError:
                self._last_scan.setText(f"Dernière analyse : {last}")
        else:
            self._last_scan.setText(
                "Carte jamais analysée — lancez l'analyse pour remplir "
                "les pages.")

    def _fill_health(self, stats: dict | None = None) -> None:
        """Résume la santé : score et trois anomalies les plus graves.

        Le diagnostic lit l'index, il est donc instantané : inutile de le
        reporter dans un fil séparé.

        **Tant que la carte n'a pas été analysée, aucun score n'est affiché.**
        Sur un index vide, les contrôles ne trouvent rien à signaler et la
        note monte à 98/100 : annoncer « carte en très bon état » alors que
        rien n'a été vérifié serait un mensonge.
        """
        while self._issues.count():
            item = self._issues.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if self.sd is None:
            return

        counted = sum(int((stats or {}).get(key, 0) or 0)
                      for key in ("samples", "synths", "kits", "songs"))
        if counted == 0:
            self._score.setText("—")
            self._score.setStyleSheet(f"color: {GREY};")
            self._verdict.setText(
                "Carte pas encore analysée : l'état de santé sera calculé "
                "après la première analyse.")
            return
        try:
            from ...core import health as health_mod

            report = health_mod.check_card(
                self.sd, self.lib,
                backup_dir=self.ctx.settings.backup_path())
        except Exception as exc:  # noqa: BLE001
            log.debug("diagnostic impossible : %s", exc)
            self._score.setText("—")
            self._verdict.setText("Diagnostic indisponible.")
            return

        self._score.setText(f"{report.score}")
        self._score.setStyleSheet(
            f"color: {self._score_colour(report.score)};")
        self._verdict.setText(report.verdict())

        worst = sorted(report.issues,
                       key=lambda i: ({"error": 0, "warn": 1, "info": 2}
                                      .get(i.severity, 3), -i.count))
        for issue in worst[:3]:
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(6)

            dot = QLabel("●")
            dot.setStyleSheet(f"color: {severity_color(issue.severity)};")
            layout.addWidget(dot)

            text = ElidedLabel(f"{issue.title} ({issue.count})")
            text.setToolTip(issue.detail)
            layout.addWidget(text, 1)
            self._issues.addWidget(row)

        if not worst:
            ok = QLabel("Aucune anomalie détectée.")
            ok.setStyleSheet(f"color: {PAD_GREEN};")
            self._issues.addWidget(ok)

    @staticmethod
    def _score_colour(score: int) -> str:
        if score >= 90:
            return PAD_GREEN
        if score >= 70:
            return GOLD
        if score >= 40:
            return "#FF8C1A"
        return PAD_MAGENTA

    def _fill_folders(self) -> None:
        """Barres colorées montrant où se trouvent les échantillons."""
        while self._folders.count():
            item = self._folders.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        try:
            folders = self.lib.folders("sample")
        except Exception as exc:  # noqa: BLE001
            log.debug("répartition indisponible : %s", exc)
            folders = []
        if not folders:
            empty = QLabel("Lancez une analyse pour voir la répartition.")
            empty.setProperty("role", "subtitle")
            self._folders.addWidget(empty)
            return

        # On regroupe par dossier de deuxième niveau : « SAMPLES/DRUMS »
        # plutôt que chacun de ses vingt sous-dossiers.
        grouped: dict[str, int] = {}
        for name, count in folders:
            parts = [p for p in str(name).split("/") if p]
            key = "/".join(parts[:2]) if len(parts) > 1 else (parts[0]
                                                              if parts else "—")
            grouped[key] = grouped.get(key, 0) + int(count)

        ranked = sorted(grouped.items(), key=lambda kv: -kv[1])[:TOP_FOLDERS]
        biggest = max((count for _n, count in ranked), default=1)

        for index, (name, count) in enumerate(ranked):
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(8)

            label = ElidedLabel(name)
            label.setFixedWidth(220)
            label.setToolTip(name)
            layout.addWidget(label)

            bar = QProgressBar()
            bar.setTextVisible(False)
            bar.setFixedHeight(10)
            bar.setRange(0, int(biggest))
            bar.setValue(int(count))
            colour = pad_color(index)
            bar.setStyleSheet(
                f"QProgressBar {{ background-color: {PANEL_HI};"
                f" border: none; border-radius: 5px; }}"
                f"QProgressBar::chunk {{ background-color: {colour};"
                f" border-radius: 5px; }}")
            layout.addWidget(bar, 1)

            value = QLabel(str(count))
            value.setFixedWidth(60)
            value.setAlignment(Qt.AlignmentFlag.AlignRight
                               | Qt.AlignmentFlag.AlignVCenter)
            value.setProperty("role", "subtitle")
            layout.addWidget(value)

            self._folders.addWidget(row)
