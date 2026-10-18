# -*- coding: utf-8 -*-
"""« Deluge en direct » : la machine branchée, vue depuis l'ordinateur.

Une fenêtre à part, qu'on garde ouverte à côté de l'application pendant
qu'on travaille sur la machine :

* **l'écran du Deluge**, recopié en direct (SysEx du firmware
  communautaire) ;
* **son tempo** et son état de lecture, lus dans l'horloge MIDI qu'il envoie ;
* **les notes tenues**, et l'accord qu'elles forment ;
* **le son sélectionné** : les réglages que la machine renvoie en mode MIDI
  Follow quand on change d'instrument ou qu'on tourne un bouton ;
* **les réglages à faire sur la machine**, cochés au fur et à mesure que la
  liaison les constate.

La fenêtre ne fait que lire l'état du lien : c'est la fenêtre principale qui
le fait vivre (:meth:`delugeapp.core.delugelink.DelugeLink.service`). Ouverte
seule — dans un test, par exemple — elle peut s'en charger elle-même
(``drive=True``).
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core import midifollow
from ..core.delugelink import latency_text
from ..core import theory as theory_mod
from .theme import (FONT_MONO, GREY, OLED_HI, PAD, PAD_AMBER, PAD_CYAN,
                    PAD_GREEN, PANEL_LO)
from .widgets.common import Card
from .widgets.delugescreen import DelugeScreenView

log = logging.getLogger(__name__)

__all__ = ["DelugeLiveWindow", "checklist"]

#: Rafraîchissement de la fenêtre, en millisecondes.
REFRESH_MS = 100


def checklist(state, channel: int) -> list[tuple[bool, str]]:
    """Les réglages qui font marcher la liaison, et ce que l'on en voit.

    Rend des couples ``(fait, phrase)`` : la phrase dit ce qui est constaté,
    ou ce qu'il reste à faire **sur la machine**, menu par menu (intitulés
    du firmware, ``gui/l10n/g_english.cpp``).
    """
    lignes: list[tuple[bool, str]] = []
    if state.connected:
        lignes.append((True, "USB : port « %s » ouvert." % state.out_name))
    else:
        detecte = any("deluge" in nom.casefold()
                      for nom in getattr(state, "ports_out", []) or [])
        if detecte:
            phrase = "USB : Deluge détecté — « Connecter » ouvre ses ports."
        else:
            phrase = "USB : branchez le Deluge, puis « Connecter »."
        lignes.append((False, phrase + (" %s." % state.error
                                        if state.error else "")))
        return lignes
    if state.firmware:
        lignes.append((True, "Firmware %s%s." % (
            state.firmware,
            " (communautaire)" if state.firmware.startswith("c") else "")))
    else:
        lignes.append((False, "Firmware : la machine n'a pas répondu en "
                       "SysEx. Le firmware officiel ne le fait pas ; le "
                       "communautaire, si."))
    if state.latency_ms is not None:
        lignes.append((True, "Liaison vérifiée : aller-retour %s."
                       % latency_text(state.latency_ms)))
    if state.feedback:
        lignes.append((True, "MIDI Follow : %s du son sélectionné." % (
            "1 réglage reçu" if state.feedback == 1
            else "%d réglages reçus" % state.feedback)))
    else:
        lignes.append((False, "MIDI Follow, sur le Deluge : MIDI ▸ Follow ▸ "
                       "Channel A = %d, puis Feedback = Channel A. Changez "
                       "ensuite d'instrument : ses réglages arrivent ici."
                       % channel))
    if state.clock_alive:
        lignes.append((True, "Horloge reçue : %s BPM."
                       % _bpm(state.tempo)))
    elif state.tempo is not None:
        lignes.append((True, "Horloge : dernier tempo %s BPM (machine "
                       "arrêtée)." % _bpm(state.tempo)))
    else:
        lignes.append((False, "Horloge : lancez la lecture sur le Deluge. "
                       "Elle part par défaut (MIDI ▸ Clock ▸ Out)."))
    return lignes


def _bpm(tempo) -> str:
    if tempo is None:
        return "—"
    return ("%.1f" % float(tempo)).replace(".", ",")


class DelugeLiveWindow(QWidget):
    """La fenêtre « Deluge en direct »."""

    #: Demande d'aller aux réglages MIDI de l'application.
    settingsRequested = pyqtSignal()

    def __init__(self, ctx, parent: QWidget | None = None,
                 drive: bool = False) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.ctx = ctx
        self._drive = bool(drive)
        self._frames = -1
        self._dernier_etat = None
        self.setObjectName("LiveWindow")
        self.setWindowTitle("Deluge en direct — Deluge Companion")
        self.resize(980, 660)
        self.setStyleSheet("QWidget#LiveWindow { background: %s; }"
                           % PANEL_LO)
        self._build()
        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self.refresh)

    # -- construction ------------------------------------------------------- #

    def _build(self) -> None:
        colonne = QVBoxLayout(self)
        colonne.setContentsMargins(PAD, PAD, PAD, PAD)
        colonne.setSpacing(PAD)

        entete = QHBoxLayout()
        titre = QLabel("DELUGE EN DIRECT")
        titre.setProperty("role", "title")
        entete.addWidget(titre)
        entete.addStretch(1)
        self._etat = QLabel("—")
        self._etat.setProperty("role", "subtitle")
        entete.addWidget(self._etat)
        colonne.addLayout(entete)

        haut = QHBoxLayout()
        haut.setSpacing(PAD)
        ecran = Card("Écran de la machine", color=PAD_CYAN)
        self.screen_view = DelugeScreenView()
        ecran.body().addWidget(self.screen_view, 1)
        boutons = QHBoxLayout()
        self.mirror_button = QPushButton("Recopier l'écran")
        self.mirror_button.setCheckable(True)
        self.mirror_button.setToolTip(
            "La machine envoie ce qui change sur son écran, au moment où "
            "cela change ; l'abonnement est renouvelé chaque seconde. Rien "
            "n'est modifié sur le Deluge")
        self.mirror_button.toggled.connect(self._toggle_mirror)
        boutons.addWidget(self.mirror_button)
        self.hello_button = QPushButton("Faire signe")
        self.hello_button.setToolTip(
            "Le Deluge affiche « HELLO SYSEX » un instant : de quoi vérifier, "
            "sur la machine, que c'est bien elle qui est connectée. Rien "
            "d'autre ne change")
        self.hello_button.clicked.connect(self._hello)
        boutons.addWidget(self.hello_button)
        self.check_button = QPushButton("Vérifier")
        self.check_button.setToolTip(
            "Redemande sa version à la machine et mesure l'aller-retour")
        self.check_button.clicked.connect(self._check)
        boutons.addWidget(self.check_button)
        self.panic_button = QPushButton("Tout éteindre")
        self.panic_button.setToolTip(
            "Relâche toutes les notes, sur tous les canaux")
        self.panic_button.clicked.connect(self._panic)
        boutons.addWidget(self.panic_button)
        boutons.addStretch(1)
        ecran.body().addLayout(boutons)
        haut.addWidget(ecran, 3)

        jeu = Card("Tempo et notes", color=PAD_GREEN)
        self.tempo_label = QLabel("—")
        # La taille passe par la feuille de style du label : celle de
        # l'application (« QWidget { font-size: 10pt } ») l'emporte sur un
        # ``setFont`` — le tempo s'affichait en petit.
        self.tempo_label.setStyleSheet(
            "color: %s; font-family: '%s'; font-size: 30pt; "
            "font-weight: 800;" % (OLED_HI, FONT_MONO))
        jeu.body().addWidget(self.tempo_label)
        self.transport_label = QLabel("Horloge muette")
        jeu.body().addWidget(self.transport_label)
        self.notes_label = QLabel("Aucune note tenue")
        self.notes_label.setWordWrap(True)
        jeu.body().addWidget(self.notes_label)
        self.chord_label = QLabel("")
        self.chord_label.setStyleSheet(
            "font-family: '%s'; font-size: 18pt; font-weight: 800;"
            % FONT_MONO)
        jeu.body().addWidget(self.chord_label)
        jeu.body().addStretch(1)
        haut.addWidget(jeu, 2)
        colonne.addLayout(haut, 3)

        bas = QHBoxLayout()
        bas.setSpacing(PAD)
        son = Card("Son sélectionné sur la machine", color=PAD_AMBER)
        self.params_table = QTableWidget(0, 2)
        self.params_table.setHorizontalHeaderLabels(["Réglage", "Valeur"])
        self.params_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self.params_table.verticalHeader().setVisible(False)
        self.params_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        son.body().addWidget(self.params_table, 1)
        self.params_hint = QLabel(
            "Rien de reçu : activez le retour MIDI Follow sur la machine, "
            "puis changez d'instrument.")
        self.params_hint.setProperty("role", "subtitle")
        self.params_hint.setWordWrap(True)
        son.body().addWidget(self.params_hint)
        bas.addWidget(son, 3)

        reglages = Card("Réglages à faire sur le Deluge", color=GREY)
        self.checklist_label = QLabel("")
        self.checklist_label.setWordWrap(True)
        self.checklist_label.setTextFormat(Qt.TextFormat.RichText)
        reglages.body().addWidget(self.checklist_label)
        ligne = QHBoxLayout()
        self.connect_button = QPushButton("Connecter")
        self.connect_button.setToolTip(
            "Ouvre les ports du Deluge : notes et contrôleurs par le "
            "premier, SysEx par le troisième")
        self.connect_button.clicked.connect(self._connect)
        ligne.addWidget(self.connect_button)
        self.settings_button = QPushButton("Réglages MIDI…")
        self.settings_button.setToolTip(
            "Ports, canal, écoute sur la machine : la page Réglages")
        self.settings_button.clicked.connect(self.settingsRequested.emit)
        ligne.addWidget(self.settings_button)
        ligne.addStretch(1)
        reglages.body().addLayout(ligne)
        reglages.body().addStretch(1)
        bas.addWidget(reglages, 2)
        colonne.addLayout(bas, 2)

    # -- cycle de vie ------------------------------------------------------- #

    def showEvent(self, event) -> None:  # noqa: N802 - API Qt
        super().showEvent(event)
        self._timer.start()
        lien = getattr(self.ctx, "link", None)
        # Ouvrir la fenêtre, c'est vouloir voir l'écran : la recopie part
        # d'elle-même si la machine est là.
        if lien is not None and lien.is_connected \
                and not self.mirror_button.isChecked():
            self.mirror_button.setChecked(True)
        self.refresh()

    def closeEvent(self, event) -> None:  # noqa: N802 - API Qt
        self._timer.stop()
        lien = getattr(self.ctx, "link", None)
        if lien is not None:
            try:
                lien.set_screen(False)
            except Exception as exc:    # noqa: BLE001
                log.debug("recopie non arrêtée : %s", exc)
        self.mirror_button.blockSignals(True)
        self.mirror_button.setChecked(False)
        self.mirror_button.blockSignals(False)
        super().closeEvent(event)

    # -- actions ------------------------------------------------------------ #

    def _lien(self):
        lien = getattr(self.ctx, "link", None)
        return lien if lien is not None and lien.is_connected else None

    def _toggle_mirror(self, on: bool) -> None:
        lien = self._lien()
        if lien is None:
            if on:
                self.mirror_button.blockSignals(True)
                self.mirror_button.setChecked(False)
                self.mirror_button.blockSignals(False)
            return
        lien.set_screen(bool(on))
        if not on:
            self.screen_view.clear("Recopie arrêtée.")
            self._frames = -1

    def _hello(self) -> None:
        lien = self._lien()
        if lien is not None:
            lien.hello()

    def _check(self) -> None:
        lien = self._lien()
        if lien is not None:
            lien.identify()
            lien.ping()

    def _panic(self) -> None:
        lien = self._lien()
        if lien is not None:
            lien.panic()

    def _connect(self) -> None:
        lien = self.ctx.ensure_link()
        if lien.is_connected:
            lien.disconnect()
        else:
            reglages = self.ctx.settings
            lien.connect(reglages.midi_out, reglages.midi_in,
                         card=getattr(self.ctx, "sd", None))
            if lien.is_connected and self.isVisible():
                self.mirror_button.setChecked(True)
        self.refresh()

    # -- affichage ---------------------------------------------------------- #

    def refresh(self) -> None:
        """Relit l'état du lien et met la fenêtre à jour."""
        try:
            self._refresh()
        except Exception:               # noqa: BLE001 - rempart, cf. SPEC §6.3
            log.exception("fenêtre « Deluge en direct » non rafraîchie")

    def _refresh(self) -> None:
        lien = getattr(self.ctx, "link", None)
        if lien is not None and self._drive and lien.is_connected:
            lien.service()
        etat = lien.state() if lien is not None else None
        connecte = bool(etat is not None and etat.connected)
        canal = int(getattr(self.ctx.settings, "midi_channel", 1) or 1)

        self.connect_button.setText("Déconnecter" if connecte
                                    else "Connecter")
        for bouton in (self.mirror_button, self.hello_button,
                       self.check_button, self.panic_button):
            bouton.setEnabled(connecte)

        if etat is None:
            self._etat.setText("Aucun lien MIDI.")
        else:
            self._etat.setText(etat.summary())
        self.checklist_label.setText(self._checklist_html(etat, canal))

        if not connecte:
            if self.mirror_button.isChecked():
                # La recopie meurt avec la connexion : le bouton le dit, et
                # la reconnexion la relancera.
                self.mirror_button.blockSignals(True)
                self.mirror_button.setChecked(False)
                self.mirror_button.blockSignals(False)
            if not self.screen_view.is_empty() or self._frames != -2:
                self.screen_view.clear("Le Deluge n'est pas connecté.")
                self._frames = -2
            self.tempo_label.setText("—")
            self.transport_label.setText("Horloge muette")
            self.notes_label.setText("Aucune note tenue")
            self.chord_label.setText("")
            self._fill_params({})
            return

        if self._frames == -2 and self.isVisible() \
                and not self.mirror_button.isChecked():
            # Connecté pendant que la fenêtre était ouverte (pastille,
            # reconnexion automatique) : l'ouvrir, c'était vouloir voir
            # l'écran.
            self.mirror_button.setChecked(True)
        # Recopie arrêtée : l'écran garde son message, pas une image figée
        # qu'on prendrait pour la machine.
        if self.mirror_button.isChecked() \
                and lien.screen.frames != self._frames:
            self._frames = lien.screen.frames
            if lien.screen.frames:
                self.screen_view.set_pixels(bytes(lien.screen.pixels))
            else:
                self.screen_view.clear("En attente de l'image… Un Deluge "
                                       "au firmware officiel ne l'envoie pas.")
        self.tempo_label.setText("%s BPM" % _bpm(etat.tempo)
                                 if etat.tempo is not None else "— BPM")
        if etat.running:
            self.transport_label.setText("▶  En lecture")
            self.transport_label.setStyleSheet("color: %s;" % PAD_GREEN)
        elif etat.tempo is not None:
            self.transport_label.setText("■  À l'arrêt")
            self.transport_label.setStyleSheet("color: %s;" % GREY)
        else:
            self.transport_label.setText("Horloge muette")
            self.transport_label.setStyleSheet("color: %s;" % GREY)

        tenues = sorted(lien.held)
        if tenues:
            self.notes_label.setText("  ".join(
                theory_mod.note_to_name(n) for n in tenues))
        else:
            self.notes_label.setText("Aucune note tenue")
        self.chord_label.setText(theory_mod.name_chord(tenues))
        self._fill_params(lien.machine_values())

    def _checklist_html(self, etat, canal: int) -> str:
        if etat is None:
            return ""
        lignes = []
        for fait, phrase in checklist(etat, canal):
            couleur = PAD_GREEN if fait else PAD_AMBER
            marque = "✓" if fait else "○"
            lignes.append('<p style="margin:2px 0"><span style="color:%s">'
                          "%s</span>&nbsp;%s</p>"
                          % (couleur, marque, _echappe(phrase)))
        return "".join(lignes)

    def _fill_params(self, valeurs: dict[str, int]) -> None:
        ordre = list(midifollow.PARAM_LABELS)
        cles = sorted(valeurs, key=lambda c: (ordre.index(c) if c in ordre
                                              else len(ordre), c))
        actuel = [(self.params_table.item(r, 0).text(),
                   self.params_table.item(r, 1).text())
                  for r in range(self.params_table.rowCount())]
        voulu = [(midifollow.label_of(c), str(valeurs[c])) for c in cles]
        if actuel != voulu:
            self.params_table.setRowCount(len(voulu))
            for rang, (nom, valeur) in enumerate(voulu):
                self.params_table.setItem(rang, 0, QTableWidgetItem(nom))
                item = QTableWidgetItem(valeur)
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight
                                      | Qt.AlignmentFlag.AlignVCenter)
                self.params_table.setItem(rang, 1, item)
        self.params_hint.setVisible(not voulu)


def _echappe(texte: str) -> str:
    return (str(texte).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))
