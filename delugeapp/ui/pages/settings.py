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
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ... import __version__
from ...config import CONFIG_DIR
from ...core import sdcard as sdmod
from ...core.delugelink import latency_text
from ...i18n import N_, plural, tr
from ..theme import (
    GOLD,
    GREY,
    PAD,
    PAD_AMBER,
    PAD_CYCLE,
    PAD_GREEN,
    PAD_RED,
    PAD_WHITE,
)
from ..widgets.common import (Card, ElidedLabel, clear_layout,
                              human_datetime, human_size)
from .base import Page, tool_button

log = logging.getLogger(__name__)

#: Couleurs d'accent proposées, prises dans la palette du guide.
ACCENT_CHOICES: tuple[tuple[str, str], ...] = (
    (N_("Or (défaut)"), GOLD),
    (N_("Cyan"), "#28C4E0"),
    (N_("Menthe"), "#2FD3A6"),
    (N_("Ambre"), "#FFC400"),
    (N_("Magenta"), "#F04FA8"),
    (N_("Indigo"), "#6B5CE7"),
)


class SettingsPage(Page):
    """Réglages de l'application."""

    TITLE = N_("Réglages")
    ICON = "settings"
    #: Seule page utilisable sans carte : c'est elle qui en désigne une.
    NEEDS_CARD = False

    #: La carte a changé : la fenêtre principale doit tout rafraîchir.
    cardChanged = pyqtSignal(str)
    #: L'accent a changé : la feuille de style doit être réappliquée.
    accentChanged = pyqtSignal(str)
    #: L'index doit être remis à zéro.
    resetIndexRequested = pyqtSignal()
    #: Demande d'ouvrir la fenêtre « Deluge en direct ».
    liveRequested = pyqtSignal()

    def build(self) -> None:
        outer = QVBoxLayout(self.content())
        outer.setContentsMargins(PAD, PAD, PAD, PAD)
        outer.setSpacing(PAD)

        header, actions = self.header(
            tr("Réglages"),
            tr("Emplacement de la carte, audio, analyse et apparence"))
        outer.addWidget(header)

        self._detect_button = tool_button(
            tr("Détecter les cartes"), "refresh",
            tr("Chercher une carte Deluge sur les lecteurs branchés"))
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

        self._build_work_card()
        self._build_card_card()
        self._build_deluge_card()
        self._build_audio_card()
        self._build_scan_card()
        self._build_safety_card()
        self._build_appearance_card()
        self._build_about_card()
        self._column.addStretch(1)

    # -- carte SD ---------------------------------------------------------- #

    def _build_work_card(self) -> None:
        """La carte reste dans le Deluge : copie de travail et sauvegarde."""
        card = Card(tr("Carte du Deluge"))
        body = card.body()

        hint = QLabel(tr(
            "La carte reste dans le Deluge. Avec le firmware 1.3, il l'ouvre "
            "au PC par le câble USB : l'application travaille sur une "
            "<b>copie de travail</b> qu'elle tient à son image — ce que vous "
            "créez ici part sur la carte, ce que vous enregistrez sur le "
            "Deluge revient. Votre <b>sauvegarde</b>, elle, n'est que lue."))
        hint.setProperty("role", "subtitle")
        hint.setWordWrap(True)
        hint.setTextFormat(Qt.TextFormat.RichText)
        body.addWidget(hint)

        self._work_state = QLabel()
        self._work_state.setWordWrap(True)
        self._work_state.setTextFormat(Qt.TextFormat.RichText)
        body.addWidget(self._work_state)

        ligne = QHBoxLayout()
        self._work_button = tool_button(tr("Créer la copie de travail"),
                                        "refresh", primary=True)
        self._work_button.setToolTip(
            tr("Bâtit la copie de travail face à la carte du Deluge, ou la "
               "synchronise : ce que le Deluge a enregistré descend, ce que "
               "l'application a créé monte. Le plan est montré d'abord"))
        self._work_button.clicked.connect(self.guard(self._work_action))
        ligne.addWidget(self._work_button)
        self._work_deletions = tool_button(tr("Suppressions à confirmer…"),
                                           "trash")
        self._work_deletions.setToolTip(
            tr("Des fichiers supprimés dans l'application existent encore "
               "sur la carte : ils ne partent qu'avec votre accord"))
        self._work_deletions.clicked.connect(self.guard(self._work_delete))
        ligne.addWidget(self._work_deletions)
        ligne.addStretch(1)
        body.addLayout(ligne)

        self._auto_sync = QCheckBox(
            tr("Synchroniser d'office quand le Deluge est branché"))
        self._auto_sync.setToolTip(
            tr("À la connexion, après chaque écriture de l'application et au "
               "retour dans la fenêtre — jamais pendant que la machine joue"))
        self._auto_sync.toggled.connect(self.guard(self._apply_auto_sync))
        body.addWidget(self._auto_sync)

        self._backup_state = QLabel()
        self._backup_state.setWordWrap(True)
        self._backup_state.setProperty("role", "subtitle")
        body.addWidget(self._backup_state)
        ligne = QHBoxLayout()
        self._backup_choose = tool_button(tr("Choisir la sauvegarde…"),
                                          "folder")
        self._backup_choose.setToolTip(
            tr("Le dossier qui garde une copie complète de la carte, en cas "
               "de problème. L'application le lit sans jamais y écrire"))
        self._backup_choose.clicked.connect(self.guard(self._choose_backup))
        ligne.addWidget(self._backup_choose)
        self._backup_update = tool_button(tr("Mettre à jour la sauvegarde"),
                                          "backup")
        self._backup_update.setToolTip(
            tr("Écrit dans la sauvegarde : ajoute ce que la carte a de "
               "nouveau, remplace ce qui a changé en gardant l'ancienne "
               "version, et n'y supprime rien. Le plan est montré d'abord"))
        self._backup_update.clicked.connect(self.guard(self._update_backup))
        ligne.addWidget(self._backup_update)
        ligne.addStretch(1)
        body.addLayout(ligne)

        self._column.addWidget(card)

    def _card_work(self):
        return getattr(self.ctx, "card_work", None)

    def _refresh_work(self) -> None:
        """Remet la section « Carte du Deluge » à jour."""
        travail = self._card_work()
        reglages = self.ctx.settings
        usb = travail is not None and travail.files() is not None
        copie = travail is not None and travail.has_work_copy()
        lien = getattr(self.ctx, "link", None)
        branche = bool(lien is not None and lien.is_connected)
        firmware = ""
        if branche and getattr(lien, "identity", None) is not None:
            firmware = lien.identity.version

        lignes = []
        oui = '<span style="color:%s">✓</span>&nbsp;' % PAD_GREEN
        non = '<span style="color:%s">○</span>&nbsp;' % PAD_AMBER
        if usb:
            lignes.append(oui + tr("Le Deluge (firmware %s) ouvre sa carte "
                                   "par USB.") % (firmware or "1.3"))
        elif branche and lien.state().files is False:
            lignes.append(non + tr("Le Deluge (firmware %s) n'ouvre pas sa "
                                   "carte par USB : il faut le firmware 1.3, "
                                   "ou glisser la carte dans un lecteur du PC "
                                   "(« Autre emplacement » ci-dessous).")
                          % (firmware or "?"))
        else:
            lignes.append(non + tr("Branchez le Deluge en USB : la carte "
                                   "s'ouvre par le câble."))
        role = reglages.card_role(reglages.sd_path) if reglages.sd_path else ""
        if copie:
            chemin = _html(str(reglages.work_path()))
            lignes.append(oui + (tr("Copie de travail : %s") % chemin
                                 if role == "travail" else
                                 tr("Copie de travail : %s — <i>pas la carte "
                                    "de l'application en ce moment</i>")
                                 % chemin))
            if travail is not None and travail.summary():
                lignes.append("&nbsp;&nbsp;&nbsp;" + _html(travail.summary()))
        else:
            lignes.append(non + tr("Pas encore de copie de travail. Elle se "
                                   "crée face à la carte, en reprenant de "
                                   "votre sauvegarde ce qui y est déjà."))
        self._work_state.setText("".join('<p style="margin:2px 0">%s</p>' % l
                                         for l in lignes))

        self._work_button.setText(tr("Synchroniser maintenant") if copie
                                  else tr("Créer la copie de travail"))
        self._work_button.setEnabled(bool(usb and travail is not None
                                          and not travail.busy))
        attente = travail.pending_deletions() if travail is not None else []
        self._work_deletions.setVisible(bool(attente))
        self._work_deletions.setText(tr("Suppressions à confirmer (%d)…")
                                     % len(attente))
        self._auto_sync.blockSignals(True)
        self._auto_sync.setChecked(bool(reglages.auto_sync))
        self._auto_sync.blockSignals(False)

        sauvegarde = reglages.card_backup_path()
        if sauvegarde is None:
            self._backup_state.setText(
                tr("Sauvegarde de la carte : aucune choisie."))
        else:
            self._backup_state.setText(
                tr("Sauvegarde de la carte : %s — lue, jamais écrite par le "
                   "travail de l'application.") % sauvegarde)
        self._backup_update.setEnabled(bool(sauvegarde is not None and copie))

    def _work_action(self) -> None:
        travail = self._card_work()
        if travail is None:
            return
        if travail.has_work_copy():
            travail.sync("demande")
        else:
            travail.create_work_copy(self)
        self._refresh_work()

    def _work_delete(self) -> None:
        travail = self._card_work()
        if travail is not None:
            travail.confirm_deletions(self)

    def _apply_auto_sync(self, checked: bool) -> None:
        self.ctx.settings.auto_sync = bool(checked)
        self.ctx.save()

    def _choose_backup(self) -> None:
        depart = (self.ctx.settings.card_backup
                  or self.ctx.settings.sd_path or str(Path.home()))
        choisi = QFileDialog.getExistingDirectory(
            self, tr("Dossier de sauvegarde de la carte"), depart)
        if not choisi:
            return
        self.ctx.settings.card_backup = choisi
        self.ctx.save()
        self._refresh_work()

    def _update_backup(self) -> None:
        travail = self._card_work()
        if travail is not None:
            travail.update_backup(self)

    def _build_card_card(self) -> None:
        card = Card(tr("Autre emplacement de carte"))
        body = card.body()

        hint = QLabel(tr(
            "Une carte glissée dans un lecteur du PC — si le firmware du "
            "Deluge n'ouvre pas sa carte par USB —, ou un autre dossier : "
            "indiquez sa racine, celle qui contient SONGS, SYNTHS, KITS et "
            "SAMPLES. La sauvegarde de la carte s'ouvre en lecture seule : "
            "l'application n'y écrit jamais."))
        hint.setProperty("role", "subtitle")
        hint.setWordWrap(True)
        body.addWidget(hint)

        row = QHBoxLayout()
        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText(
            tr("D:\\  ou  C:\\Users\\…\\SDCARD Deluge"))
        self._path_edit.textChanged.connect(self.guard(self._on_path_typed))
        row.addWidget(self._path_edit, 1)

        browse = tool_button(tr("Parcourir…"), "folder")
        browse.clicked.connect(self.guard(self._browse))
        row.addWidget(browse)

        apply_button = tool_button(tr("Utiliser cette carte"), "check",
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
        recent_label = QLabel(tr("Chemins récents"))
        recent_label.setProperty("role", "subtitle")
        body.addWidget(recent_label)
        self._recent_box = QComboBox()
        self._recent_box.setPlaceholderText(tr("Aucun chemin récent"))
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
            self._set_state(False, tr("Ce dossier n'existe pas."))
            return
        if sdmod.is_deluge_root(path):
            card = sdmod.SDCard(path)
            free, total = card.free_space()
            if total:
                self._set_state(True, tr("Arborescence Deluge reconnue — %s "
                                         "libres sur %s.")
                                % (human_size(free), human_size(total)))
            else:
                self._set_state(True, tr("Arborescence Deluge reconnue."))
        else:
            missing = ", ".join(sdmod.SDCard(path).missing_dirs())
            self._set_state(
                False,
                tr("Dossier valide, mais ce n'est pas une carte Deluge "
                   "(manque : %s).") % missing)

    def _set_state(self, ok: bool, message: str) -> None:
        colour = PAD_GREEN if ok else PAD_RED
        mark = "✓" if ok else "✗"
        self._path_state.setText(f"{mark}  {message}")
        self._path_state.setStyleSheet(f"color: {colour};")

    def _browse(self) -> None:
        start = self._path_edit.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(
            self, tr("Choisir la racine de la carte Deluge"), start)
        if chosen:
            self._path_edit.setText(chosen)

    def _apply_path(self) -> None:
        """Enregistre le chemin saisi et prévient la fenêtre principale."""
        text = self._path_edit.text().strip().strip('"')
        if not text:
            return
        path = Path(text)
        if not path.is_dir():
            QMessageBox.warning(self, tr("Dossier introuvable"),
                                tr("Le dossier « %s » n'existe pas.") % text)
            return
        if not sdmod.is_deluge_root(path):
            answer = QMessageBox.question(
                self, tr("Ce n'est pas une carte Deluge"),
                tr("Ce dossier ne contient pas l'arborescence attendue "
                   "(SONGS, SYNTHS, KITS, SAMPLES).\n\n"
                   "L'utiliser quand même ?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return

        self.ctx.settings.sd_path = str(path)
        self.ctx.settings.add_recent(path)
        self.ctx.save()
        self.cardChanged.emit(str(path))
        self.say(tr("Carte : %s") % path)
        self._fill_recent()

    def _detect(self) -> None:
        """Cherche les cartes branchées et propose celles trouvées."""
        self.say(tr("Recherche des cartes branchées…"))
        found = sdmod.detect_sd_cards()
        clear_layout(self._detected_row)

        if not found:
            label = QLabel(tr("Aucune carte Deluge détectée automatiquement."))
            label.setProperty("role", "subtitle")
            self._detected_row.addWidget(label)
            self.say(tr("Aucune carte détectée."))
            return

        for path in found:
            button = tool_button(str(path), "save",
                                 tr("Utiliser la carte %s") % path)
            button.clicked.connect(
                self.guard(lambda _checked=False, p=path: self._use(p)))
            self._detected_row.addWidget(button)
        self._detected_row.addStretch(1)
        self.say(tr("%d carte(s) détectée(s).") % len(found))

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
        card = Card(tr("Écoute"))
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)

        self._device_box = QComboBox()
        self._device_box.addItem(tr("Périphérique par défaut"), "")
        try:
            for name in (self.player.devices() if self.player else []):
                self._device_box.addItem(name, name)
        except Exception as exc:  # noqa: BLE001 - audio indisponible
            log.debug("liste des périphériques indisponible : %s", exc)
        self._device_box.activated.connect(self.guard(self._apply_device))
        form.addRow(tr("Sortie audio"), self._device_box)

        backend = "—"
        if self.player is not None:
            backend = getattr(self.player, "backend", "—")
        self._backend_label = QLabel(backend)
        self._backend_label.setProperty("role", "subtitle")
        form.addRow(tr("Moteur"), self._backend_label)

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
        form.addRow(tr("Volume d'aperçu"), holder)

        self._autoplay = QCheckBox(
            tr("Écouter automatiquement l'échantillon sélectionné"))
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
        self.say(tr("Sortie audio : %s") % (name or tr("par défaut")))

    def _apply_volume(self, value: int) -> None:
        self._volume_label.setText(f"{value} %")
        self.ctx.settings.preview_volume = value / 100.0
        if self.player is not None:
            self.player.set_volume(value / 100.0)

    def _apply_autoplay(self, checked: bool) -> None:
        self.ctx.settings.autoplay = bool(checked)
        self.ctx.save()

    # -- le Deluge branché --------------------------------------------------- #

    def _build_deluge_card(self) -> None:
        """Le lien MIDI avec la machine, quand elle est au bout du câble."""
        card = Card(tr("Deluge branché"))
        body = card.body()

        self._midi_state = QLabel("—")
        self._midi_state.setWordWrap(True)
        body.addWidget(self._midi_state)

        self._midi_machine = QLabel("")
        self._midi_machine.setWordWrap(True)
        body.addWidget(self._midi_machine)

        hint = QLabel(tr(
            "Branchez le Deluge en USB. L'application peut alors jouer les "
            "sons <b>sur la machine</b> plutôt qu'avec son moteur approché, "
            "et régler l'instrument <b>sélectionné sur le Deluge</b> grâce "
            "au mode MIDI Follow du firmware communautaire. Choisir le "
            "preset à distance n'est pas possible : c'est une limite de la "
            "machine, pas de l'application."))
        hint.setProperty("role", "subtitle")
        hint.setWordWrap(True)
        body.addWidget(hint)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)

        self._midi_out_box = QComboBox()
        self._midi_out_box.activated.connect(self.guard(self._apply_midi_out))
        form.addRow(tr("Sortie MIDI"), self._midi_out_box)

        self._midi_in_box = QComboBox()
        self._midi_in_box.activated.connect(self.guard(self._apply_midi_in))
        form.addRow(tr("Entrée MIDI"), self._midi_in_box)

        self._midi_channel = QSpinBox()
        self._midi_channel.setRange(1, 16)
        # Un nombre de deux chiffres n'a pas besoin de toute la largeur du
        # formulaire : étiré, il laissait croire à un champ de saisie libre.
        self._midi_channel.setFixedWidth(80)
        self._midi_channel.setToolTip(
            tr("Le canal que le Deluge écoute en MIDI Follow"))
        self._midi_channel.valueChanged.connect(
            self.guard(self._apply_midi_channel))
        form.addRow(tr("Canal"), self._midi_channel)
        body.addLayout(form)

        self._midi_auto = QCheckBox(
            tr("Se connecter dès que le Deluge apparaît"))
        self._midi_auto.toggled.connect(self.guard(self._apply_midi_auto))
        body.addWidget(self._midi_auto)

        self._midi_audition = QCheckBox(
            tr("Écouter les presets sur le Deluge plutôt que sur "
               "l'ordinateur"))
        self._midi_audition.setToolTip(
            tr("Le son vient alors du vrai moteur de la machine, et non de "
               "l'approximation calculée par l'application"))
        self._midi_audition.toggled.connect(
            self.guard(self._apply_midi_audition))
        body.addWidget(self._midi_audition)

        self._midi_follow_tempo = QCheckBox(
            tr("Les outils suivent le tempo du Deluge"))
        self._midi_follow_tempo.setToolTip(
            tr("Quand la machine joue, son horloge donne le tempo des "
               "écoutes, des fichiers MIDI et des morceaux de la boîte à "
               "outils"))
        self._midi_follow_tempo.toggled.connect(
            self.guard(self._apply_midi_follow_tempo))
        body.addWidget(self._midi_follow_tempo)

        row = QHBoxLayout()
        row.setSpacing(6)
        self._midi_connect = tool_button(
            tr("Connecter"), "link",
            tr("Ouvre ou ferme les ports MIDI choisis ci-dessus"),
            primary=True)
        self._midi_connect.clicked.connect(self.guard(self._toggle_midi))
        row.addWidget(self._midi_connect)

        test = tool_button(tr("Jouer un do"), "play",
                           tr("Envoyer une note pour vérifier le câble"))
        test.clicked.connect(self.guard(self._test_midi))
        row.addWidget(test)

        panic = tool_button(tr("Tout éteindre"), "stop",
                            tr("Relâcher toutes les notes, sur tous les "
                               "canaux"))
        panic.clicked.connect(self.guard(self._panic_midi))
        row.addWidget(panic)

        self._midi_live = tool_button(
            tr("Deluge en direct…"), "wave",
            tr("Écran de la machine, tempo, notes et son sélectionné"))
        self._midi_live.clicked.connect(self.guard(self._open_live))
        row.addWidget(self._midi_live)
        row.addStretch(1)
        holder = QWidget()
        holder.setLayout(row)
        body.addWidget(holder)

        self._midi_follow = QLabel("")
        self._midi_follow.setProperty("role", "subtitle")
        self._midi_follow.setWordWrap(True)
        body.addWidget(self._midi_follow)

        # Le mode MIDI Follow est éteint sur une machine neuve : sans ces
        # réglages, rien de ce que l'application envoie n'est joué.
        self._midi_guide = QLabel("")
        self._midi_guide.setProperty("role", "subtitle")
        self._midi_guide.setWordWrap(True)
        self._midi_guide.setTextFormat(Qt.TextFormat.RichText)
        body.addWidget(self._midi_guide)

        self._column.addWidget(card)
        self._refresh_midi()

    def _refresh_midi(self) -> None:
        """Remet la section à jour : ports visibles, état, boutons."""
        from ...core import midiport

        lien = self.ctx.ensure_link()
        etat = lien.state()
        self._midi_state.setText(etat.summary())
        couleur = PAD_GREEN if etat.connected else GREY
        self._midi_state.setStyleSheet("color: %s; font-weight: 600;" % couleur)

        reglages = self.ctx.settings
        self._remplir_ports(self._midi_out_box, etat.ports_out,
                            reglages.midi_out)
        self._remplir_ports(self._midi_in_box, etat.ports_in,
                            reglages.midi_in)

        self._midi_channel.blockSignals(True)
        self._midi_channel.setValue(int(reglages.midi_channel))
        self._midi_channel.blockSignals(False)
        for case, valeur in ((self._midi_auto, reglages.midi_autoconnect),
                             (self._midi_audition, reglages.midi_audition),
                             (self._midi_follow_tempo,
                              reglages.midi_follow_tempo)):
            case.blockSignals(True)
            case.setChecked(bool(valeur))
            case.blockSignals(False)

        self._midi_connect.setText(
            tr("Déconnecter") if etat.connected else tr("Connecter"))
        self._midi_connect.setEnabled(
            bool(etat.supported) and (etat.connected or bool(etat.ports_out)))
        self._midi_audition.setEnabled(bool(etat.supported))

        self._midi_machine.setText(self._texte_machine(etat))
        self._midi_guide.setText(
            tr("<b>Sur le Deluge</b>, une fois : MIDI ▸ Follow ▸ "
               "<b>Channel A = %d</b> — sans ce réglage, la machine ignore ce "
               "que l'application joue — puis <b>Feedback = Channel A</b>, "
               "pour que le son sélectionné revienne à l'application. "
               "L'horloge, elle, sort d'elle-même (MIDI ▸ Clock ▸ Out). Un "
               "kit répond à partir de la note 36 (Follow ▸ Kit Root Note).")
            % int(reglages.midi_channel))

        if not midiport.available():
            self._midi_follow.setText(
                tr("Cette machine n'expose pas de MIDI : %s")
                % (midiport.load_error() or tr("cause inconnue")))
        else:
            n = int(etat.follow_count)
            pilotables = plural(n, N_("%d paramètre pilotable"),
                                N_("%d paramètres pilotables")) % n
            if etat.follow_source:
                origine = (tr("table lue dans %s sur la carte")
                           % etat.follow_source)
            else:
                origine = tr("table d'usine du firmware : aucun "
                             "MIDIFollow.XML lu sur la carte")
            self._midi_follow.setText(tr("MIDI Follow : %s — %s.")
                                      % (pilotables, origine))

    @staticmethod
    def _remplir_ports(boite, noms: list, choisi: str) -> None:
        """Remplit une liste de ports sans perdre le choix de l'utilisateur."""
        boite.blockSignals(True)
        boite.clear()
        boite.addItem(tr("Chercher le Deluge tout seul"), "")
        for nom in noms:
            boite.addItem(nom, nom)
        index = boite.findData(choisi) if choisi else 0
        boite.setCurrentIndex(index if index >= 0 else 0)
        boite.setEnabled(bool(noms))
        if not noms:
            boite.clear()
            boite.addItem(tr("Aucun port"), "")
        boite.blockSignals(False)

    def _apply_midi_out(self, index: int) -> None:
        self.ctx.settings.midi_out = self._midi_out_box.itemData(index) or ""
        self.ctx.save()
        self.say(tr("Sortie MIDI : %s")
                 % (self.ctx.settings.midi_out or tr("détection automatique")))

    def _apply_midi_in(self, index: int) -> None:
        self.ctx.settings.midi_in = self._midi_in_box.itemData(index) or ""
        self.ctx.save()

    def _apply_midi_channel(self, value: int) -> None:
        self.ctx.settings.midi_channel = int(value)
        self.ctx.save()
        self.ctx.ensure_link().set_channel(int(value))
        # Le guide cite le canal : il doit dire le nouveau.
        self._refresh_midi()

    def _apply_midi_auto(self, checked: bool) -> None:
        self.ctx.settings.midi_autoconnect = bool(checked)
        self.ctx.save()

    @staticmethod
    def _texte_machine(etat) -> str:
        """Ce que la machine a dit d'elle-même, en une ligne."""
        if not etat.connected:
            return ""
        morceaux = []
        if etat.firmware:
            morceaux.append(tr("Firmware %s") % etat.firmware)
        else:
            morceaux.append(tr("Pas de réponse SysEx (firmware officiel, ou "
                               "port SysEx occupé)"))
        if etat.latency_ms is not None:
            morceaux.append(tr("aller-retour %s")
                            % latency_text(etat.latency_ms))
        if etat.sysex_name and etat.sysex_name != etat.out_name:
            morceaux.append(tr("SysEx par « %s »") % etat.sysex_name)
        return " — ".join(morceaux) + "."

    def _open_live(self) -> None:
        """Ouvre la fenêtre « Deluge en direct » (la fenêtre principale la
        possède)."""
        self.liveRequested.emit()

    def _apply_midi_follow_tempo(self, checked: bool) -> None:
        self.ctx.settings.midi_follow_tempo = bool(checked)
        self.ctx.save()

    def _apply_midi_audition(self, checked: bool) -> None:
        self.ctx.settings.midi_audition = bool(checked)
        self.ctx.save()
        if checked and not self.ctx.link_connected:
            self.say(tr("Écoute sur le Deluge : il faut encore le "
                        "connecter."))

    def _toggle_midi(self) -> None:
        lien = self.ctx.ensure_link()
        if lien.is_connected:
            lien.disconnect()
            self.say(tr("Deluge déconnecté."))
        else:
            reglages = self.ctx.settings
            ouvert = lien.connect(reglages.midi_out, reglages.midi_in,
                                  card=self.sd)
            self.say(lien.state().summary() if ouvert
                     else tr("Aucun port MIDI à ouvrir."))
        self._refresh_midi()

    def _test_midi(self) -> None:
        """Un do central, une demi-seconde : de quoi entendre si ça marche."""
        lien = self.ctx.ensure_link()
        if not lien.is_connected:
            self.say(tr("Connectez d'abord le Deluge."))
            return
        lien.play_notes(60, velocity=100, seconds=0.5)
        self.say(tr("Do central envoyé sur le canal %d.") % lien.channel)

    def _panic_midi(self) -> None:
        lien = self.ctx.ensure_link()
        lien.panic()
        self.say(tr("Toutes les notes relâchées."))

    # -- analyse ------------------------------------------------------------ #

    def _build_scan_card(self) -> None:
        card = Card(tr("Analyse de la carte"))
        body = card.body()

        self._scan_hash = QCheckBox(
            tr("Calculer les empreintes (détection des doublons)"))
        self._scan_hash.setToolTip(
            tr("Peu coûteux : l'empreinte rapide lit trois blocs de 64 Kio "
               "par fichier. Les doublons sont ensuite confirmés en comparant "
               "les fichiers en entier."))
        self._scan_hash.toggled.connect(self.guard(self._apply_scan_hash))
        body.addWidget(self._scan_hash)

        self._scan_analyze = QCheckBox(
            tr("Analyse acoustique (tempo, tonalité, niveaux)"))
        self._scan_analyze.setToolTip(
            tr("Nettement plus lent : environ une minute pour 1 700 "
               "échantillons. Nécessaire aux contrôles d'écrêtage et "
               "d'offset continu de la page Santé."))
        self._scan_analyze.toggled.connect(
            self.guard(self._apply_scan_analyze))
        body.addWidget(self._scan_analyze)

        self._index_on_start = QCheckBox(
            tr("Mettre l'index à jour au démarrage"))
        self._index_on_start.setToolTip(
            tr("Relit seulement les fichiers modifiés depuis la dernière "
               "analyse : une fraction de seconde. Sans cela, ce que montre "
               "l'application peut dater d'avant vos dernières "
               "modifications."))
        self._index_on_start.toggled.connect(
            self.guard(self._apply_index_on_start))
        body.addWidget(self._index_on_start)

        row = QHBoxLayout()
        reset = tool_button(tr("Réinitialiser l'index"), "trash",
                            tr("Vide l'index SQLite. Les étiquettes, notes "
                               "et favoris sont conservés."))
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

    def _apply_index_on_start(self, checked: bool) -> None:
        self.ctx.settings.index_on_start = bool(checked)
        self.ctx.save()

    def _reset_index(self) -> None:
        answer = QMessageBox.question(
            self, tr("Réinitialiser l'index"),
            tr("L'index de la carte va être vidé, puis reconstruit à la "
               "prochaine analyse.\n\n"
               "Vos étiquettes, notes et favoris sont conservés.\n\n"
               "Continuer ?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.lib.clear()
            # Sans quoi l'accueil annonçait encore une analyse disparue.
            self.lib.set_meta("last_scan", "")
            self.lib.set_meta("last_scan_root", "")
            self.lib.vacuum()
        except Exception:  # noqa: BLE001
            log.exception("remise à zéro de l'index impossible")
            self.say(tr("Remise à zéro impossible : voir le journal."))
            return
        self.resetIndexRequested.emit()
        self.say(tr("Index vidé. Relancez une analyse."))
        self._refresh_index_label()

    def _refresh_index_label(self) -> None:
        try:
            stats = self.lib.stats()
            path = getattr(self.lib, "path", None)
            size = human_size(Path(path).stat().st_size) if path and \
                Path(path).exists() else "—"
            last = human_datetime(stats.get("last_scan"),
                                  absent=tr("jamais"))
            self._index_label.setText(
                tr("Index : %d échantillons, %d presets, %d kits, %d "
                   "morceaux — %s, dernière analyse : %s")
                % (stats.get("samples", 0), stats.get("synths", 0),
                   stats.get("kits", 0), stats.get("songs", 0), size, last))
        except Exception as exc:  # noqa: BLE001
            log.debug("état de l'index indisponible : %s", exc)
            self._index_label.setText(tr("Index indisponible."))

    # -- sûreté ------------------------------------------------------------- #

    def _build_safety_card(self) -> None:
        card = Card(tr("Sûreté des écritures"))
        body = card.body()

        hint = QLabel(tr(
            "L'application ne modifie jamais la carte sans confirmation, et "
            "toute réorganisation est d'abord présentée en simulation."))
        hint.setProperty("role", "subtitle")
        hint.setWordWrap(True)
        body.addWidget(hint)

        self._confirm = QCheckBox(
            tr("Demander confirmation avant toute écriture"))
        self._confirm.toggled.connect(self.guard(self._apply_confirm))
        body.addWidget(self._confirm)

        self._backup = QCheckBox(
            tr("Créer une copie .bak avant de réécrire un XML"))
        self._backup.toggled.connect(self.guard(self._apply_backup))
        body.addWidget(self._backup)

        row = QHBoxLayout()
        self._backup_dir = QLineEdit()
        self._backup_dir.setPlaceholderText(tr("Dossier des sauvegardes"))
        self._backup_dir.editingFinished.connect(
            self.guard(self._apply_backup_dir))
        row.addWidget(self._backup_dir, 1)
        browse = tool_button(tr("Parcourir…"), "folder")
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
            self, tr("Choisir le dossier des sauvegardes"), start)
        if chosen:
            self._backup_dir.setText(chosen)
            self._apply_backup_dir()

    # -- apparence ---------------------------------------------------------- #

    def _build_appearance_card(self) -> None:
        card = Card(tr("Apparence"))
        body = card.body()

        hint = QLabel(tr(
            "La palette est celle du Guide du Deluge. Chaque page porte sa "
            "couleur, celle de son pad dans la colonne de gauche. La couleur "
            "choisie ici est celle de la façade : la barre du haut, les "
            "menus et les fenêtres de dialogue."))
        hint.setProperty("role", "subtitle")
        hint.setWordWrap(True)
        body.addWidget(hint)

        row = QHBoxLayout()
        row.setSpacing(6)
        self._accent_buttons: list = []
        for label, colour in ACCENT_CHOICES:
            button = tool_button("", "", f"{tr(label)} — {colour}",
                                 color=colour)
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
        self.say(tr("Couleur d'accent : %s") % colour)

    # -- à propos ----------------------------------------------------------- #

    def _build_about_card(self) -> None:
        card = Card(tr("À propos"))
        body = card.body()

        title = QLabel(f"Deluge Companion {__version__}")
        title.setProperty("role", "title")
        body.addWidget(title)

        text = QLabel(tr(
            "Accompagne l'utilisation d'un Synthstrom Deluge : gestion de la "
            "carte SD, génération de presets et de kits, et outils de "
            "composition.\n\n"
            "Identité visuelle reprise du Guide du Deluge OLED."))
        text.setProperty("role", "subtitle")
        text.setWordWrap(True)
        body.addWidget(text)

        config_row = QHBoxLayout()
        config_label = QLabel(tr("Dossier de configuration :"))
        config_label.setProperty("role", "subtitle")
        config_row.addWidget(config_label)
        path = ElidedLabel(str(CONFIG_DIR))
        path.setProperty("role", "mono")
        config_row.addWidget(path, 1)
        open_button = tool_button(tr("Ouvrir"), "folder")
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
        try:
            self._refresh_midi()
        except Exception as exc:        # noqa: BLE001 - MIDI accessoire
            log.debug("état MIDI indisponible : %s", exc)
        try:
            self._refresh_work()
        except Exception as exc:        # noqa: BLE001 - l'état n'est qu'affiché
            log.debug("état de la carte indisponible : %s", exc)
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
                              (self._index_on_start, settings.index_on_start),
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


def _html(texte: str) -> str:
    return (str(texte).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))
