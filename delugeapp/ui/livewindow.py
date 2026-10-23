# -*- coding: utf-8 -*-
"""« Deluge en direct » : la machine branchée, vue depuis l'ordinateur.

Une fenêtre à part, qu'on garde ouverte à côté de l'application pendant
qu'on travaille sur la machine :

* **l'écran du Deluge**, recopié en direct (SysEx du firmware
  communautaire) ;
* **son tempo** et son état de lecture, lus dans l'horloge MIDI qu'il envoie ;
* **les notes tenues**, et l'accord qu'elles forment — celles des pistes MIDI
  du Deluge : un synthé ou un kit joué sur ses pads joue sa voix en interne
  et n'envoie aucune note (code du firmware : ``SoundInstrument`` contre
  ``MIDIInstrument``) ;
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
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core import midifollow
from ..core.delugelink import latency_text
from ..core import theory as theory_mod
from ..i18n import decimal, plural, N_, tr
from .theme import (FONT_MONO, GREY, OLED_HI, PAD, PAD_AMBER, PAD_CYAN,
                    PAD_GREEN, PANEL_LO)
from .widgets.common import Card
from .widgets.delugescreen import DelugeScreenView

log = logging.getLogger(__name__)

__all__ = ["DelugeLiveWindow", "checklist"]

#: Rafraîchissement de la fenêtre, en millisecondes.
REFRESH_MS = 100


def checklist(state, channel: int,
              follow=None) -> list[tuple[bool, str]]:
    """Les réglages qui font marcher la liaison, et ce que l'on en voit.

    Rend des couples ``(fait, phrase)`` : la phrase dit ce qui est constaté,
    ou ce qu'il reste à faire **sur la machine**, menu par menu (intitulés
    du firmware, ``gui/l10n/g_english.cpp``).
    """
    lignes: list[tuple[bool, str]] = []
    if state.connected:
        lignes.append((True, tr("USB : port « %s » ouvert.")
                       % state.out_name))
    else:
        detecte = any("deluge" in nom.casefold()
                      for nom in getattr(state, "ports_out", []) or [])
        if detecte:
            phrase = tr("USB : Deluge détecté — « Connecter » ouvre ses "
                        "ports.")
        else:
            phrase = tr("USB : branchez le Deluge, puis « Connecter ».")
        lignes.append((False, phrase + (" %s." % state.error
                                        if state.error else "")))
        return lignes
    if state.firmware:
        lignes.append((True, (tr("Firmware %s (communautaire).")
                              if state.firmware.startswith("c")
                              else tr("Firmware %s.")) % state.firmware))
    else:
        lignes.append((False, tr("Firmware : la machine n'a pas répondu en "
                                 "SysEx. Le firmware officiel ne le fait "
                                 "pas ; le communautaire, si.")))
    if state.latency_ms is not None:
        lignes.append((True, tr("Liaison vérifiée : aller-retour %s.")
                       % latency_text(state.latency_ms)))
    if getattr(state, "files", None):
        lignes.append((True, tr("Carte ouverte par USB : la copie de travail "
                                "se tient à son image.")))
    if follow is not None:
        # Le firmware 1.3 écrit ses réglages sur la carte : on les lit au
        # lieu de les supposer.
        a = follow.channel_a
        if a is None:
            lignes.append((False, tr("Sur le Deluge, MIDI Follow est "
                                     "éteint : MIDI ▸ MIDI-Follow ▸ Channel "
                                     "▸ Channel A = %d.") % channel))
        elif a != channel:
            lignes.append((False, tr("Le Deluge suit le canal %d, "
                                     "l'application joue sur le canal %d : "
                                     "accordez-les (Réglages, ou MIDI ▸ "
                                     "MIDI-Follow ▸ Channel ▸ Channel A).")
                           % (a, channel)))
        else:
            lignes.append((True, tr("MIDI Follow réglé sur la machine : "
                                    "Channel A = %d (lu sur sa carte).") % a))
        if a is not None and follow.feedback != "a":
            lignes.append((False, tr("Retour MIDI Follow éteint : MIDI ▸ "
                                     "MIDI-Follow ▸ Feedback ▸ Channel = A, "
                                     "pour que le son sélectionné revienne "
                                     "ici.")))
    if state.feedback:
        lignes.append((True, tr("MIDI Follow : %s du son sélectionné.")
                       % (plural(state.feedback, N_("%d réglage reçu"),
                                 N_("%d réglages reçus")) % state.feedback)))
    elif follow is None:
        lignes.append((False, tr("MIDI Follow, sur le Deluge : MIDI ▸ "
                                 "MIDI-Follow ▸ Channel ▸ Channel A = %d, "
                                 "puis Feedback ▸ Channel = A. Changez "
                                 "ensuite d'instrument : ses réglages "
                                 "arrivent ici.") % channel))
    elif follow.channel_a == channel and follow.feedback == "a":
        lignes.append((False, tr("Changez d'instrument sur le Deluge : ses "
                                 "réglages arrivent ici.")))
    if state.clock_alive:
        lignes.append((True, tr("Horloge reçue : %s BPM.")
                       % _bpm(state.tempo)))
    elif state.tempo is not None:
        lignes.append((True, tr("Horloge : dernier tempo %s BPM (machine "
                                "arrêtée).") % _bpm(state.tempo)))
    else:
        lignes.append((False, tr("Horloge : lancez la lecture sur le Deluge. "
                                 "Elle part par défaut (MIDI ▸ Clock ▸ "
                                 "Output).")))
    return lignes


def _bpm(tempo) -> str:
    if tempo is None:
        return "—"
    return decimal(float(tempo), 1)


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
        self.setWindowTitle(tr("Deluge en direct — Deluge Companion"))
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
        titre = QLabel(tr("DELUGE EN DIRECT"))
        titre.setProperty("role", "title")
        entete.addWidget(titre)
        entete.addStretch(1)
        self._etat = QLabel("—")
        self._etat.setProperty("role", "subtitle")
        entete.addWidget(self._etat)
        colonne.addLayout(entete)

        haut = QHBoxLayout()
        haut.setSpacing(PAD)
        ecran = Card(tr("Écran de la machine"), color=PAD_CYAN)
        self.screen_view = DelugeScreenView()
        ecran.body().addWidget(self.screen_view, 1)
        boutons = QHBoxLayout()
        self.mirror_button = QPushButton(tr("Recopier l'écran"))
        self.mirror_button.setCheckable(True)
        self.mirror_button.setToolTip(
            tr("La machine envoie ce qui change sur son écran, au moment où "
               "cela change ; l'abonnement est renouvelé chaque seconde. Rien "
               "n'est modifié sur le Deluge"))
        self.mirror_button.toggled.connect(self._toggle_mirror)
        boutons.addWidget(self.mirror_button)
        self.hello_button = QPushButton(tr("Faire signe"))
        self.hello_button.setToolTip(
            tr("Le Deluge affiche « HELLO SYSEX » un instant : de quoi "
               "vérifier, sur la machine, que c'est bien elle qui est "
               "connectée. Rien d'autre ne change"))
        self.hello_button.clicked.connect(self._hello)
        boutons.addWidget(self.hello_button)
        self.check_button = QPushButton(tr("Vérifier"))
        self.check_button.setToolTip(
            tr("Redemande sa version à la machine et mesure l'aller-retour"))
        self.check_button.clicked.connect(self._check)
        boutons.addWidget(self.check_button)
        self.panic_button = QPushButton(tr("Tout éteindre"))
        self.panic_button.setToolTip(
            tr("Relâche toutes les notes, sur tous les canaux"))
        self.panic_button.clicked.connect(self._panic)
        boutons.addWidget(self.panic_button)
        boutons.addStretch(1)
        ecran.body().addLayout(boutons)
        haut.addWidget(ecran, 3)

        jeu = Card(tr("Tempo et notes"), color=PAD_GREEN)
        self.tempo_label = QLabel("—")
        # La taille passe par la feuille de style du label : celle de
        # l'application (« QWidget { font-size: 10pt } ») l'emporte sur un
        # ``setFont`` — le tempo s'affichait en petit.
        self.tempo_label.setStyleSheet(
            "color: %s; font-family: '%s'; font-size: 30pt; "
            "font-weight: 800;" % (OLED_HI, FONT_MONO))
        jeu.body().addWidget(self.tempo_label)
        self.transport_label = QLabel(tr("Horloge muette"))
        jeu.body().addWidget(self.transport_label)
        self.notes_label = QLabel(tr("Aucune note tenue"))
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
        son = Card(tr("Son sélectionné sur la machine"), color=PAD_AMBER)
        self.params_table = QTableWidget(0, 2)
        self.params_table.setHorizontalHeaderLabels([tr("Réglage"),
                                                     tr("Valeur")])
        self.params_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self.params_table.verticalHeader().setVisible(False)
        self.params_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        son.body().addWidget(self.params_table, 1)
        self.params_hint = QLabel(
            tr("Rien de reçu : activez le retour MIDI Follow sur la machine, "
               "puis changez d'instrument."))
        self.params_hint.setProperty("role", "subtitle")
        self.params_hint.setWordWrap(True)
        son.body().addWidget(self.params_hint)
        bas.addWidget(son, 3)

        reglages = Card(tr("Réglages à faire sur le Deluge"), color=GREY)
        self.checklist_label = QLabel("")
        self.checklist_label.setWordWrap(True)
        self.checklist_label.setTextFormat(Qt.TextFormat.RichText)
        self.checklist_label.setAlignment(Qt.AlignmentFlag.AlignTop
                                          | Qt.AlignmentFlag.AlignLeft)
        # Dans une zone défilante : sept constats ne tiennent pas dans une
        # fenêtre de 660 pixels de haut, et le dernier — l'horloge — était
        # coupé à mi-phrase (vu face à la machine, 21 octobre 2026).
        defilante = QScrollArea()
        defilante.setWidgetResizable(True)
        defilante.setFrameShape(QFrame.Shape.NoFrame)
        defilante.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        defilante.setWidget(self.checklist_label)
        reglages.body().addWidget(defilante, 1)
        ligne = QHBoxLayout()
        self.connect_button = QPushButton(tr("Connecter"))
        self.connect_button.setToolTip(
            tr("Ouvre les ports du Deluge : notes et contrôleurs par le "
               "premier, SysEx par le troisième"))
        self.connect_button.clicked.connect(self._connect)
        ligne.addWidget(self.connect_button)
        self.settings_button = QPushButton(tr("Réglages MIDI…"))
        self.settings_button.setToolTip(
            tr("Ports, canal, écoute sur la machine : la page Réglages"))
        self.settings_button.clicked.connect(self.settingsRequested.emit)
        ligne.addWidget(self.settings_button)
        ligne.addStretch(1)
        reglages.body().addLayout(ligne)
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
            self.screen_view.clear(tr("Recopie arrêtée."))
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

        self.connect_button.setText(tr("Déconnecter") if connecte
                                    else tr("Connecter"))
        for bouton in (self.mirror_button, self.hello_button,
                       self.check_button, self.panic_button):
            bouton.setEnabled(connecte)

        if etat is None:
            self._etat.setText(tr("Aucun lien MIDI."))
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
                self.screen_view.clear(tr("Le Deluge n'est pas connecté."))
                self._frames = -2
            self.tempo_label.setText("—")
            self.transport_label.setText(tr("Horloge muette"))
            self.notes_label.setText(tr("Aucune note tenue"))
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
                self.screen_view.clear(tr("En attente de l'image… Un Deluge "
                                          "au firmware officiel ne l'envoie "
                                          "pas."))
        self.tempo_label.setText("%s BPM" % _bpm(etat.tempo)
                                 if etat.tempo is not None else "— BPM")
        if etat.running:
            self.transport_label.setText(tr("▶  En lecture"))
            self.transport_label.setStyleSheet("color: %s;" % PAD_GREEN)
        elif etat.tempo is not None:
            self.transport_label.setText(tr("■  À l'arrêt"))
            self.transport_label.setStyleSheet("color: %s;" % GREY)
        else:
            self.transport_label.setText(tr("Horloge muette"))
            self.transport_label.setStyleSheet("color: %s;" % GREY)

        tenues = sorted(lien.held)
        if tenues:
            self.notes_label.setText("  ".join(
                theory_mod.note_to_name(n) for n in tenues))
        else:
            # Connecté, sans note : le dire sans laisser croire à une panne.
            self.notes_label.setText(tr("Aucune note reçue — seules les "
                                        "pistes MIDI du Deluge envoient "
                                        "leurs notes, pas ses synthés ni "
                                        "ses kits."))
        self.chord_label.setText(theory_mod.name_chord(tenues))
        self._fill_params(lien.machine_values())
        follow = self._follow()
        if (follow is not None and follow.channel_a is not None
                and follow.feedback == "a"):
            self.params_hint.setText(tr("Le retour MIDI Follow est actif sur "
                                        "la machine : changez d'instrument "
                                        "ou tournez un bouton, ses réglages "
                                        "arrivent ici."))
        else:
            self.params_hint.setText(tr("Rien de reçu : activez le retour "
                                        "MIDI Follow sur la machine, puis "
                                        "changez d'instrument."))

    def _follow(self):
        """Les réglages MIDI Follow écrits par la machine sur sa carte (1.3),
        relus seulement quand le fichier change."""
        carte = getattr(self.ctx, "sd", None)
        if carte is None:
            return None
        try:
            chemin = midifollow._card_file(carte)
            cle = (str(chemin), chemin.stat().st_mtime_ns) if chemin else None
        except OSError:
            cle = None
        if cle != getattr(self, "_follow_key", "?"):
            self._follow_key = cle
            self._follow_value = midifollow.read_settings(carte) if cle \
                else None
        return self._follow_value

    def _checklist_html(self, etat, canal: int) -> str:
        if etat is None:
            return ""
        lignes = []
        for fait, phrase in checklist(etat, canal, self._follow()):
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
