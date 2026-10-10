# -*- coding: utf-8 -*-
"""Page « Réglages ».

C'est la seule page qui fonctionne sans carte valide — et pour cause : c'est
ici qu'on en désigne une. Le cahier des charges demandait explicitement que
l'emplacement de la carte soit **modifiable depuis l'application**, avec
détection automatique des lecteurs amovibles.

Le champ du chemin valide ce qu'on y tape en direct : un dossier qui n'est pas
une arborescence Deluge le dit tout de suite, plutôt que de laisser les autres
pages vides sans explication.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ... import __version__
from ...config import CONFIG_DIR, save_settings
from ...core import sdcard as sdmod
from .. import icons
from ..theme import (
    GOLD,
    GREY,
    PAD,
    PAD_CYCLE,
    PAD_GREEN,
    PAD_RED,
    PAD_WHITE,
)
from ..widgets.common import Card, ElidedLabel, human_size
from .base import Page, page_header, tool_button

log = logging.getLogger(__name__)

#: Couleurs d'accent proposées, prises dans la palette du guide.
ACCENT_CHOICES: tuple[tuple[str, str], ...] = (
    ("Or (défaut)", GOLD),
    ("Cyan", "#28C4E0"),
    ("Menthe", "#2FD3A6"),
    ("Ambre", "#FFC400"),
    ("Magenta", "#F04FA8"),
    ("Indigo", "#6B5CE7"),
)


class SettingsPage(Page):
    """Réglages de l'application."""

    TITLE = "Réglages"
    ICON = "settings"
    #: Seule page utilisable sans carte : c'est elle qui en désigne une.
    NEEDS_CARD = False

    #: La carte a changé : la fenêtre principale doit tout rafraîchir.
    cardChanged = pyqtSignal(str)
    #: L'accent a changé : la feuille de style doit être réappliquée.
    accentChanged = pyqtSignal(str)
    #: L'index doit être remis à zéro.
    resetIndexRequested = pyqtSignal()

    def build(self) -> None:
        outer = QVBoxLayout(self.content())
        outer.setContentsMargins(PAD, PAD, PAD, PAD)
        outer.setSpacing(PAD)

        header, actions = page_header(
            "Réglages",
            "Emplacement de la carte, audio, analyse et apparence")
        outer.addWidget(header)

        self._detect_button = tool_button(
            "Détecter les cartes", "refresh",
            "Chercher une carte Deluge sur les lecteurs branchés")
        self._detect_button.clicked.connect(self.guard(self._detect))
        actions.addWidget(self._detect_button)

        # Zone défilante : la page est longue sur un petit écran.
        scroll = QScrollArea(self.content())
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        inner = QWidget()
        self._column = QVBoxLayout(inner)
        self._column.setContentsMargins(0, 0, 0, 0)
        self._column.setSpacing(PAD)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

        self._build_card_card()
        self._build_audio_card()
        self._build_scan_card()
        self._build_safety_card()
        self._build_appearance_card()
        self._build_about_card()
        self._column.addStretch(1)

    # -- carte SD ---------------------------------------------------------- #

    def _build_card_card(self) -> None:
        card = Card("Carte SD du Deluge")
        body = card.body()

        hint = QLabel(
            "Indiquez le dossier racine de la carte — celui qui contient "
            "SONGS, SYNTHS, KITS et SAMPLES. Une sauvegarde de la carte sur "
            "le disque dur fait tout aussi bien l'affaire.")
        hint.setProperty("role", "subtitle")
        hint.setWordWrap(True)
        body.addWidget(hint)

        row = QHBoxLayout()
        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText(
            r"D:\  ou  C:\Users\…\SDCARD Deluge")
        self._path_edit.textChanged.connect(self.guard(self._on_path_typed))
        row.addWidget(self._path_edit, 1)

        browse = tool_button("Parcourir…", "folder")
        browse.clicked.connect(self.guard(self._browse))
        row.addWidget(browse)

        apply_button = tool_button("Utiliser cette carte", "check",
                                   primary=True)
        apply_button.clicked.connect(self.guard(self._apply_path))
        row.addWidget(apply_button)
        body.addLayout(row)

        self._path_state = QLabel()
        self._path_state.setWordWrap(True)
        body.addWidget(self._path_state)

        # Cartes détectées automatiquement.
        self._detected_row = QHBoxLayout()
        self._detected_row.setSpacing(6)
        body.addLayout(self._detected_row)

        # Chemins récents.
        recent_label = QLabel("Chemins récents")
        recent_label.setProperty("role", "subtitle")
        body.addWidget(recent_label)
        self._recent_box = QComboBox()
        self._recent_box.setPlaceholderText("Aucun chemin récent")
        self._recent_box.activated.connect(self.guard(self._pick_recent))
        body.addWidget(self._recent_box)

        self._column.addWidget(card)

    def _on_path_typed(self, text: str) -> None:
        """Valide le chemin au fil de la saisie, sans rien enregistrer."""
        path = Path(str(text).strip().strip('"'))
        if not text.strip():
            self._path_state.setText("")
            return
        if not path.is_dir():
            self._set_state(False, "Ce dossier n'existe pas.")
            return
        if sdmod.is_deluge_root(path):
            card = sdmod.SDCard(path)
            free, total = card.free_space()
            detail = ""
            if total:
                detail = (f" — {human_size(free)} libres sur "
                          f"{human_size(total)}")
            self._set_state(True, f"Arborescence Deluge reconnue{detail}.")
        else:
            missing = ", ".join(sdmod.SDCard(path).missing_dirs())
            self._set_state(
                False,
                f"Dossier valide, mais ce n'est pas une carte Deluge "
                f"(manque : {missing}).")

    def _set_state(self, ok: bool, message: str) -> None:
        colour = PAD_GREEN if ok else PAD_RED
        mark = "✓" if ok else "✗"
        self._path_state.setText(f"{mark}  {message}")
        self._path_state.setStyleSheet(f"color: {colour};")

    def _browse(self) -> None:
        start = self._path_edit.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(
            self, "Choisir la racine de la carte Deluge", start)
        if chosen:
            self._path_edit.setText(chosen)

    def _apply_path(self) -> None:
        """Enregistre le chemin saisi et prévient la fenêtre principale."""
        text = self._path_edit.text().strip().strip('"')
        if not text:
            return
        path = Path(text)
        if not path.is_dir():
            QMessageBox.warning(self, "Dossier introuvable",
                                f"Le dossier « {text} » n'existe pas.")
            return
        if not sdmod.is_deluge_root(path):
            answer = QMessageBox.question(
                self, "Ce n'est pas une carte Deluge",
                "Ce dossier ne contient pas l'arborescence attendue "
                "(SONGS, SYNTHS, KITS, SAMPLES).\n\n"
                "L'utiliser quand même ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return

        self.ctx.settings.sd_path = str(path)
        self.ctx.settings.add_recent(path)
        self.ctx.save()
        self.cardChanged.emit(str(path))
        self.say(f"Carte : {path}")
        self._fill_recent()

    def _detect(self) -> None:
        """Cherche les cartes branchées et propose celles trouvées."""
        self.say("Recherche des cartes branchées…")
        found = sdmod.detect_sd_cards()
        while self._detected_row.count():
            item = self._detected_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not found:
            label = QLabel("Aucune carte Deluge détectée automatiquement.")
            label.setProperty("role", "subtitle")
            self._detected_row.addWidget(label)
            self.say("Aucune carte détectée.")
            return

        for path in found:
            button = tool_button(str(path), "save",
                                 f"Utiliser la carte {path}")
            button.clicked.connect(
                self.guard(lambda _checked=False, p=path: self._use(p)))
            self._detected_row.addWidget(button)
        self._detected_row.addStretch(1)
        self.say(f"{len(found)} carte(s) détectée(s).")

    def _use(self, path: Path) -> None:
        self._path_edit.setText(str(path))
        self._apply_path()

    def _fill_recent(self) -> None:
        self._recent_box.blockSignals(True)
        self._recent_box.clear()
        for item in self.ctx.settings.recent_paths:
            self._recent_box.addItem(item)
        self._recent_box.setCurrentIndex(-1)
        self._recent_box.blockSignals(False)

    def _pick_recent(self, index: int) -> None:
        text = self._recent_box.itemText(index)
        if text:
            self._path_edit.setText(text)
            self._apply_path()

    # -- audio -------------------------------------------------------------- #

    def _build_audio_card(self) -> None:
        card = Card("Écoute")
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)

        self._device_box = QComboBox()
        self._device_box.addItem("Périphérique par défaut", "")
        try:
            for name in (self.player.devices() if self.player else []):
                self._device_box.addItem(name, name)
        except Exception as exc:  # noqa: BLE001 - audio indisponible
            log.debug("liste des périphériques indisponible : %s", exc)
        self._device_box.activated.connect(self.guard(self._apply_device))
        form.addRow("Sortie audio", self._device_box)

        backend = "—"
        if self.player is not None:
            backend = getattr(self.player, "backend", "—")
        self._backend_label = QLabel(backend)
        self._backend_label.setProperty("role", "subtitle")
        form.addRow("Moteur", self._backend_label)

        volume_row = QHBoxLayout()
        self._volume = QSlider(Qt.Orientation.Horizontal)
        self._volume.setRange(0, 100)
        self._volume.valueChanged.connect(self.guard(self._apply_volume))
        self._volume_label = QLabel("80 %")
        self._volume_label.setFixedWidth(46)
        volume_row.addWidget(self._volume, 1)
        volume_row.addWidget(self._volume_label)
        holder = QWidget()
        holder.setLayout(volume_row)
        form.addRow("Volume d'aperçu", holder)

        self._autoplay = QCheckBox(
            "Écouter automatiquement l'échantillon sélectionné")
        self._autoplay.toggled.connect(self.guard(self._apply_autoplay))
        form.addRow("", self._autoplay)

        card.body().addLayout(form)
        self._column.addWidget(card)

    def _apply_device(self, index: int) -> None:
        name = self._device_box.itemData(index) or None
        self.ctx.settings.audio_device = name
        self.ctx.save()
        if self.player is not None:
            self.player.set_device(name)
        self.say(f"Sortie audio : {name or 'par défaut'}")

    def _apply_volume(self, value: int) -> None:
        self._volume_label.setText(f"{value} %")
        self.ctx.settings.preview_volume = value / 100.0
        if self.player is not None:
            self.player.set_volume(value / 100.0)

    def _apply_autoplay(self, checked: bool) -> None:
        self.ctx.settings.autoplay = bool(checked)
        self.ctx.save()

    # -- analyse ------------------------------------------------------------ #

    def _build_scan_card(self) -> None:
        card = Card("Analyse de la carte")
        body = card.body()

        self._scan_hash = QCheckBox(
            "Calculer les empreintes (détection des doublons)")
        self._scan_hash.setToolTip(
            "Peu coûteux : l'empreinte rapide lit trois blocs de 64 Kio par "
            "fichier. Les doublons sont ensuite confirmés en comparant les "
            "fichiers en entier.")
        self._scan_hash.toggled.connect(self.guard(self._apply_scan_hash))
        body.addWidget(self._scan_hash)

        self._scan_analyze = QCheckBox(
            "Analyse acoustique (tempo, tonalité, niveaux)")
        self._scan_analyze.setToolTip(
            "Nettement plus lent : environ une minute pour 1 700 "
            "échantillons. Nécessaire aux contrôles d'écrêtage et d'offset "
            "continu de la page Santé.")
        self._scan_analyze.toggled.connect(
            self.guard(self._apply_scan_analyze))
        body.addWidget(self._scan_analyze)

        row = QHBoxLayout()
        reset = tool_button("Réinitialiser l'index", "trash",
                            "Vide l'index SQLite. Les étiquettes, notes et "
                            "favoris sont conservés.")
        reset.clicked.connect(self.guard(self._reset_index))
        row.addWidget(reset)
        row.addStretch(1)
        body.addLayout(row)

        self._index_label = QLabel()
        self._index_label.setProperty("role", "subtitle")
        self._index_label.setWordWrap(True)
        body.addWidget(self._index_label)

        self._column.addWidget(card)

    def _apply_scan_hash(self, checked: bool) -> None:
        self.ctx.settings.scan_hash = bool(checked)
        self.ctx.save()

    def _apply_scan_analyze(self, checked: bool) -> None:
        self.ctx.settings.scan_analyze = bool(checked)
        self.ctx.save()

    def _reset_index(self) -> None:
        answer = QMessageBox.question(
            self, "Réinitialiser l'index",
            "L'index de la carte va être vidé, puis reconstruit à la "
            "prochaine analyse.\n\n"
            "Vos étiquettes, notes et favoris sont conservés.\n\n"
            "Continuer ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.lib.clear()
            self.lib.vacuum()
        except Exception:  # noqa: BLE001
            log.exception("remise à zéro de l'index impossible")
            self.say("Remise à zéro impossible : voir le journal.")
            return
        self.resetIndexRequested.emit()
        self.say("Index vidé. Relancez une analyse.")
        self._refresh_index_label()

    def _refresh_index_label(self) -> None:
        try:
            stats = self.lib.stats()
            path = getattr(self.lib, "path", None)
            size = human_size(Path(path).stat().st_size) if path and \
                Path(path).exists() else "—"
            last = stats.get("last_scan") or "jamais"
            self._index_label.setText(
                f"Index : {stats.get('samples', 0)} échantillons, "
                f"{stats.get('synths', 0)} presets, {stats.get('kits', 0)} "
                f"kits, {stats.get('songs', 0)} morceaux — {size}, "
                f"dernière analyse : {last}")
        except Exception as exc:  # noqa: BLE001
            log.debug("état de l'index indisponible : %s", exc)
            self._index_label.setText("Index indisponible.")

    # -- sûreté ------------------------------------------------------------- #

    def _build_safety_card(self) -> None:
        card = Card("Sûreté des écritures")
        body = card.body()

        hint = QLabel(
            "L'application ne modifie jamais la carte sans confirmation, et "
            "toute réorganisation est d'abord présentée en simulation.")
        hint.setProperty("role", "subtitle")
        hint.setWordWrap(True)
        body.addWidget(hint)

        self._confirm = QCheckBox("Demander confirmation avant toute écriture")
        self._confirm.toggled.connect(self.guard(self._apply_confirm))
        body.addWidget(self._confirm)

        self._backup = QCheckBox(
            "Créer une copie .bak avant de réécrire un XML")
        self._backup.toggled.connect(self.guard(self._apply_backup))
        body.addWidget(self._backup)

        row = QHBoxLayout()
        self._backup_dir = QLineEdit()
        self._backup_dir.setPlaceholderText("Dossier des sauvegardes")
        self._backup_dir.editingFinished.connect(
            self.guard(self._apply_backup_dir))
        row.addWidget(self._backup_dir, 1)
        browse = tool_button("Parcourir…", "folder")
        browse.clicked.connect(self.guard(self._browse_backup))
        row.addWidget(browse)
        body.addLayout(row)

        self._column.addWidget(card)

    def _apply_confirm(self, checked: bool) -> None:
        self.ctx.settings.confirm_writes = bool(checked)
        self.ctx.save()

    def _apply_backup(self, checked: bool) -> None:
        self.ctx.settings.always_backup_before_write = bool(checked)
        self.ctx.save()

    def _apply_backup_dir(self) -> None:
        self.ctx.settings.backup_dir = self._backup_dir.text().strip()
        self.ctx.save()

    def _browse_backup(self) -> None:
        start = self._backup_dir.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(
            self, "Choisir le dossier des sauvegardes", start)
        if chosen:
            self._backup_dir.setText(chosen)
            self._apply_backup_dir()

    # -- apparence ---------------------------------------------------------- #

    def _build_appearance_card(self) -> None:
        card = Card("Apparence")
        body = card.body()

        hint = QLabel(
            "La palette est reprise du Guide du Deluge. Seule la couleur "
            "d'accent se change.")
        hint.setProperty("role", "subtitle")
        hint.setWordWrap(True)
        body.addWidget(hint)

        row = QHBoxLayout()
        row.setSpacing(6)
        self._accent_buttons: list = []
        for label, colour in ACCENT_CHOICES:
            button = tool_button("", "", f"{label} — {colour}", color=colour)
            button.setFixedSize(34, 26)
            button.setStyleSheet(
                f"QPushButton {{ background-color: {colour};"
                f" border: 2px solid {colour}; border-radius: 6px; }}")
            button.clicked.connect(
                self.guard(lambda _c=False, v=colour: self._apply_accent(v)))
            row.addWidget(button)
            self._accent_buttons.append((colour, button))
        row.addStretch(1)
        body.addLayout(row)

        # Aperçu de la palette des pads, à titre indicatif.
        grid = QGridLayout()
        grid.setSpacing(3)
        for index, colour in enumerate(PAD_CYCLE):
            swatch = QLabel()
            swatch.setFixedSize(22, 14)
            swatch.setStyleSheet(
                f"background-color: {colour}; border-radius: 3px;")
            swatch.setToolTip(colour)
            grid.addWidget(swatch, 0, index)
        holder = QWidget()
        holder.setLayout(grid)
        body.addWidget(holder)

        self._column.addWidget(card)

    def _apply_accent(self, colour: str) -> None:
        self.ctx.settings.theme_accent = colour
        self.ctx.save()
        self.accentChanged.emit(colour)
        self.say(f"Couleur d'accent : {colour}")

    # -- à propos ----------------------------------------------------------- #

    def _build_about_card(self) -> None:
        card = Card("À propos")
        body = card.body()

        title = QLabel(f"Deluge Companion {__version__}")
        title.setProperty("role", "title")
        body.addWidget(title)

        text = QLabel(
            "Accompagne l'utilisation d'un Synthstrom Deluge : gestion de la "
            "carte SD, génération de presets et de kits, et outils de "
            "composition.\n\n"
            "Identité visuelle reprise du Guide du Deluge OLED.")
        text.setProperty("role", "subtitle")
        text.setWordWrap(True)
        body.addWidget(text)

        config_row = QHBoxLayout()
        config_label = QLabel("Dossier de configuration :")
        config_label.setProperty("role", "subtitle")
        config_row.addWidget(config_label)
        path = ElidedLabel(str(CONFIG_DIR))
        path.setProperty("role", "mono")
        config_row.addWidget(path, 1)
        open_button = tool_button("Ouvrir", "folder")
        open_button.clicked.connect(self.guard(self._open_config_dir))
        config_row.addWidget(open_button)
        body.addLayout(config_row)

        self._column.addWidget(card)

    def _open_config_dir(self) -> None:
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(CONFIG_DIR)))

    # -- rafraîchissement --------------------------------------------------- #

    def _refresh(self) -> None:
        settings = self.ctx.settings

        self._path_edit.blockSignals(True)
        self._path_edit.setText(settings.sd_path)
        self._path_edit.blockSignals(False)
        self._on_path_typed(settings.sd_path)
        self._fill_recent()

        index = self._device_box.findData(settings.audio_device or "")
        self._device_box.setCurrentIndex(max(0, index))
        if self.player is not None:
            self._backend_label.setText(getattr(self.player, "backend", "—"))

        self._volume.blockSignals(True)
        self._volume.setValue(int(round(settings.preview_volume * 100)))
        self._volume.blockSignals(False)
        self._volume_label.setText(f"{self._volume.value()} %")

        for widget, value in ((self._autoplay, settings.autoplay),
                              (self._scan_hash, settings.scan_hash),
                              (self._scan_analyze, settings.scan_analyze),
                              (self._confirm, settings.confirm_writes),
                              (self._backup,
                               settings.always_backup_before_write)):
            widget.blockSignals(True)
            widget.setChecked(bool(value))
            widget.blockSignals(False)

        self._backup_dir.setText(settings.backup_dir
                                 or str(settings.backup_path()))

        # L'accent courant est mis en évidence.
        for colour, button in self._accent_buttons:
            selected = colour.lower() == (settings.theme_accent or "").lower()
            border = PAD_WHITE if selected else colour
            button.setStyleSheet(
                f"QPushButton {{ background-color: {colour};"
                f" border: 2px solid {border}; border-radius: 6px; }}")

        self._refresh_index_label()
