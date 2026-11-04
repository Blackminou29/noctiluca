# -*- coding: utf-8 -*-
"""Page « Mémo » : ce qu'un musicien garde sous la main.

Quatre onglets de référence, qu'on consulte en cours de morceau plutôt
qu'on n'y fabrique quelque chose :

* **Gammes et accords** — une gamme au clavier, ses accords, et le
  ``<modeNotes>`` à recopier dans le Deluge ;
* **Calculatrice** — temps de délai et de LFO selon le tempo, ``syncLevel``,
  place d'un enregistrement ;
* **Mixage harmonique** — roue de Camelot et tonalités compatibles, et les
  échantillons de la carte qui s'accordent ;
* **Aide-mémoire** — les valeurs du Deluge qu'on oublie toujours.

Ce qu'était la Boîte à outils de création — rythme, progression,
arrangement — vit dans l'atelier, appliqué au morceau en cours : un seul
endroit pour chaque geste. Aucun onglet n'a besoin de la carte, sauf la
recherche par tonalité du mixage harmonique.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ...core import rhythm as rhythm_mod
from ...core import theory as theory_mod
from ...i18n import N_, decimal, tr, untranslated
from ..theme import GOLD, PAD, PAD_CYAN
from ..widgets.common import Card
from ..widgets.piano import PianoKeys
from .base import Page, tool_button

log = logging.getLogger(__name__)

#: Correspondance ``syncLevel`` du Deluge et division rythmique.
#:
#: Calcul du firmware (``model/sync.cpp``) : la valeur écrite dans le fichier
#: vaut ``2^(3 - niveau)`` mesures, la magnitude du morceau s'annulant entre
#: la lecture et l'affichage. Les 23 arpèges synchronisés de la carte sont
#: en 7, la double-croche. Cette table était décalée d'un cran (7 annoncé en
#: croche).
SYNC_LEVELS: tuple[tuple[int, str], ...] = (
    (0, N_("libre (non synchronisé)")),
    (1, N_("4 mesures")),
    (2, N_("2 mesures")),
    (3, N_("1 mesure")),
    (4, N_("1/2 — blanche")),
    (5, N_("1/4 — noire")),
    (6, N_("1/8 — croche")),
    (7, N_("1/16 — double-croche")),
    (8, N_("1/32 — triple-croche")),
    (9, N_("1/64 — quadruple-croche")),
)

#: Aide-mémoire : limites et valeurs du Deluge, mesurées ou documentées.
CHEATSHEET: tuple[tuple[str, str], ...] = (
    (N_("Résolution rythmique"),
     N_("Une mesure 4/4 vaut 96 << inputTickMagnitude ticks : 384 dans un "
        "morceau c1.2.1 (magnitude 2), 192 dans un morceau 3.x. Un clip de "
        "1536 ticks fait 4 mesures en c1.2.1.")),
    (N_("Paramètres"),
     N_("Entiers 32 bits : 0x80000000 = minimum, 0x00000000 = milieu, "
        "0x7FFFFFFF = maximum. L'écran affiche 0 à 50.")),
    (N_("Câbles de modulation"),
     N_("Échelle pleine 0x40000000, soit la MOITIÉ des autres paramètres. "
        "L'écran affiche −50 à +50.")),
    (N_("Notes dans un clip"),
     N_("22 caractères hexadécimaux par note : pos(8) longueur(8) vélocité(2) "
        "lift(2) condition(2). Le lift précède la condition.")),
    (N_("Notes en firmware 1.3"),
     N_("Un morceau enregistré en 1.3 n'écrit plus que noteDataWithSplitProb, "
        "28 caractères par note : pos(8) longueur(8) vélocité(2) lift(2) "
        "probabilité(2) itération(4) remplissage(2).")),
    (N_("Condition d'une note"),
     N_("0x14 (20) = toujours. En dessous de 20, probabilité par pas de 5 %. "
        "À partir de 0x80, règle d'itération.")),
    (N_("Gammes"),
     N_("Firmware communautaire (c1.x) : <modeNotes> accepte des gammes de "
        "cinq, six ou sept notes, et toute gamme utilisateur. Le firmware "
        "officiel en exigeait exactement sept.")),
    (N_("syncLevel"),
     N_("Valeur du fichier : 3 = 1 mesure, 5 = noire, 6 = croche, "
        "7 = double-croche, 8 = triple-croche. 0 = libre.")),
    (N_("Arpégiateur (c1.x)"),
     N_("arpMode=\"arp\" l'allume ; noteMode (up, down, upDown, random, "
        "asPlayed) et octaveMode (up, down, upDown, alt, random) le règlent. "
        "L'ancien attribut mode n'est plus lu dans un fichier c1.2.")),
    (N_("Rangées de kit"),
     N_("loopMode 1 (ONCE) joue l'échantillon jusqu'au bout : c'est ce que "
        "choisit le Deluge sous 2 secondes. 0 (CUT) l'arrête avec la note.")),
    (N_("Noms de fichiers"),
     N_("FAT32 : pas de < > : \" / \\ | ? *, ni de point ou d'espace final. "
        "63 caractères au maximum, ASCII de préférence.")),
    (N_("Firmware"),
     N_("Un seul fichier deluge*.bin à la racine, sinon la mise à jour est "
        "refusée.")),
    (N_("Dossiers attendus"),
     N_("SONGS, SYNTHS, KITS, SAMPLES à la racine. Les percussions dans "
        "SAMPLES/DRUMS/<catégorie>.")),
    (N_("Fréquence d'échantillonnage"),
     N_("La machine tourne à 44,1 kHz. Les autres fréquences sont converties "
        "à la lecture.")),
)


class ToolboxPage(Page):
    """Le mémo du musicien."""

    TITLE = N_("Mémo")
    ICON = "memo"
    #: Seul le mixage harmonique a besoin de la carte.
    NEEDS_CARD = False

    def __init__(self, ctx, parent=None) -> None:
        super().__init__(ctx, parent)
        self._spelling: dict = {}

    def build(self) -> None:
        outer = QVBoxLayout(self.content())
        outer.setContentsMargins(PAD, PAD, PAD, PAD)
        outer.setSpacing(8)

        header, _actions = self.header(
            tr("Mémo"),
            tr("Gammes, tempos, roue de Camelot et valeurs du Deluge"))
        outer.addWidget(header)

        tabs = QTabWidget()
        tabs.addTab(self._build_theory_tab(), tr("Gammes et accords"))
        tabs.addTab(self._build_calc_tab(), tr("Calculatrice"))
        tabs.addTab(self._build_camelot_tab(), tr("Mixage harmonique"))
        tabs.addTab(self._build_cheatsheet_tab(), tr("Aide-mémoire"))
        outer.addWidget(tabs, 1)

    # -- gammes et accords --------------------------------------------------- #

    def _build_theory_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        inner = QWidget()
        column = QVBoxLayout(inner)
        column.setContentsMargins(0, PAD, 0, 0)
        column.setSpacing(PAD)

        card = Card(tr("Gamme"))
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("Tonique")))
        self._root = QComboBox()
        for midi in range(48, 72):
            self._root.addItem(theory_mod.note_to_name(midi), midi)
        self._root.setCurrentIndex(12)       # Do3
        self._root.activated.connect(self.guard(lambda _i: self._show_scale()))
        row.addWidget(self._root)

        row.addWidget(QLabel(tr("Gamme")))
        self._scale = QComboBox()
        for name in theory_mod.scale_names():
            self._scale.addItem(tr(name), name)
        self._scale.activated.connect(self.guard(lambda _i: self._show_scale()))
        row.addWidget(self._scale, 1)
        card.body().addLayout(row)

        self._piano = PianoKeys(48, 84)
        self._piano.setMinimumHeight(74)
        self._piano.noteOn.connect(self.guard(self._note_clicked))
        card.body().addWidget(self._piano)

        self._scale_notes = QLabel("")
        self._scale_notes.setWordWrap(True)
        card.body().addWidget(self._scale_notes)

        self._deluge_scale = QLabel("")
        self._deluge_scale.setProperty("role", "subtitle")
        self._deluge_scale.setWordWrap(True)
        card.body().addWidget(self._deluge_scale)

        mode_row = QHBoxLayout()
        self._mode_notes = QLineEdit()
        self._mode_notes.setReadOnly(True)
        self._mode_notes.setToolTip(
            tr("Valeurs à recopier dans <modeNotes> d'un morceau du Deluge"))
        mode_row.addWidget(QLabel(untranslated("<modeNotes>")))
        mode_row.addWidget(self._mode_notes, 1)
        copy = tool_button(tr("Copier"), "copy")
        copy.clicked.connect(self.guard(self._copy_mode_notes))
        mode_row.addWidget(copy)
        card.body().addLayout(mode_row)
        column.addWidget(card)

        chords = Card(tr("Accords de la gamme"))
        self._chords = QTableWidget(0, 3)
        self._chords.setHorizontalHeaderLabels([tr("Degré"), tr("Accord"),
                                                tr("Notes")])
        self._chords.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch)
        self._chords.verticalHeader().setVisible(False)
        self._chords.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self._chords.itemSelectionChanged.connect(
            self.guard(self._highlight_chord))
        self._chords.setMaximumHeight(260)
        chords.body().addWidget(self._chords)
        hint = QLabel(tr("Choisissez un accord : ses notes s'allument sur le "
                         "clavier. Les accords d'un morceau se choisissent "
                         "dans l'atelier, à l'étape Style."))
        hint.setProperty("role", "subtitle")
        hint.setWordWrap(True)
        chords.body().addWidget(hint)
        column.addWidget(chords)
        column.addStretch(1)

        scroll.setWidget(inner)
        return scroll

    def _show_scale(self) -> None:
        root = self._root.currentData() or 60
        scale = self._scale.currentData() or "majeur"

        notes = theory_mod.scale_notes(root, scale, octaves=1)
        self._piano.set_highlight(
            [n - root for n in notes], GOLD)
        # Les noms suivent la tonalité : do mineur s'écrit avec Lab, pas
        # avec Sol#.
        self._spelling = theory_mod.scale_spelling(root, scale)
        tonique = theory_mod.spell(root, self._spelling, with_octave=False)
        self._scale_notes.setText(
            tr("%s %s :  %s") % (
                tonique, tr(scale),
                "  ".join(theory_mod.spell(n, self._spelling,
                                           with_octave=False)
                          for n in notes[:-1])))
        exact = theory_mod.deluge_mode_notes(scale)
        self._mode_notes.setText(", ".join(str(v) for v in exact))
        name = theory_mod.deluge_scale_name(scale)
        if name == "USER":
            hint = tr("Sur le Deluge : gamme utilisateur (USER), à saisir "
                      "note par note — ou en recopiant <modeNotes>.")
        else:
            hint = tr("Sur le Deluge : %s.") % name
        officiel = theory_mod.deluge_mode_notes(scale, official=True)
        if officiel != exact:
            hint += "  " + tr("Firmware officiel (sept notes exactement) : "
                              "%s.") % ", ".join(str(v) for v in officiel)
        self._deluge_scale.setText(hint)

        self._chords.setRowCount(0)
        for symbol, chord_notes in theory_mod.diatonic_chords(root, scale):
            index = self._chords.rowCount()
            self._chords.insertRow(index)
            self._chords.setItem(index, 0, QTableWidgetItem(symbol))
            # Le nom complet, qualité comprise : « Rém », et non « Ré ».
            self._chords.setItem(
                index, 1,
                QTableWidgetItem(theory_mod.chord_symbol(
                    chord_notes[0], theory_mod.chord_quality(chord_notes),
                    spelling=self._spelling)
                    if chord_notes else "—"))
            item = QTableWidgetItem(
                "  ".join(theory_mod.spell(n, self._spelling)
                          for n in chord_notes))
            item.setData(Qt.ItemDataRole.UserRole, chord_notes)
            self._chords.setItem(index, 2, item)

    def _highlight_chord(self) -> None:
        index = self._chords.currentRow()
        if index < 0:
            return
        item = self._chords.item(index, 2)
        notes = item.data(Qt.ItemDataRole.UserRole) if item else None
        if notes:
            self._piano.set_exact_highlight(notes, PAD_CYAN)

    def _note_clicked(self, midi: int) -> None:
        self.say("%s — %s Hz — MIDI %d"
                 % (theory_mod.note_to_name(midi),
                    decimal(theory_mod.frequency(midi), 2), midi))

    def _copy_mode_notes(self) -> None:
        from PyQt6.QtWidgets import QApplication

        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self._mode_notes.text())
            self.say(tr("Valeurs de <modeNotes> copiées."))

    # -- tempo de la machine ------------------------------------------------- #

    def follow_tempo(self, bpm: int) -> bool:
        """La calculatrice prend le tempo du Deluge.

        Appelé par la fenêtre quand l'horloge de la machine change de tempo
        (réglage « Les outils suivent le tempo du Deluge »). Rend ``True``
        si le champ a changé.
        """
        try:
            tempo = int(round(float(bpm)))
        except (TypeError, ValueError):
            return False
        # La page peut exister sans avoir encore été construite.
        champ = getattr(self, "_bpm", None)
        if champ is None:
            return False
        borne = max(champ.minimum(), min(champ.maximum(), tempo))
        if champ.value() == borne:
            return False
        champ.setValue(borne)
        return True

    # -- calculatrice ------------------------------------------------------- #

    def _build_calc_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        inner = QWidget()
        column = QVBoxLayout(inner)
        column.setContentsMargins(0, PAD, 0, 0)
        column.setSpacing(PAD)

        card = Card(tr("Tempo"))
        row = QHBoxLayout()
        row.addWidget(QLabel("BPM"))
        self._bpm = QSpinBox()
        self._bpm.setRange(20, 400)
        self._bpm.setValue(128)
        self._bpm.valueChanged.connect(self.guard(lambda _v: self._calc()))
        row.addWidget(self._bpm)
        row.addStretch(1)
        self._bar_length = QLabel("")
        self._bar_length.setProperty("role", "subtitle")
        row.addWidget(self._bar_length)
        card.body().addLayout(row)

        self._delays = QTableWidget(0, 5)
        self._delays.setHorizontalHeaderLabels(
            [tr("Division"), tr("Droit (ms)"), tr("Pointé (ms)"),
             tr("Triolet (ms)"), tr("Hz (LFO)")])
        self._delays.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self._delays.verticalHeader().setVisible(False)
        self._delays.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self._delays.setMaximumHeight(230)
        card.body().addWidget(self._delays)
        column.addWidget(card)

        sync = Card(tr("syncLevel du Deluge"))
        self._sync = QTableWidget(0, 2)
        self._sync.setHorizontalHeaderLabels([untranslated("syncLevel"),
                                             tr("Division")])
        self._sync.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self._sync.verticalHeader().setVisible(False)
        self._sync.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        for level, label in SYNC_LEVELS:
            index = self._sync.rowCount()
            self._sync.insertRow(index)
            self._sync.setItem(index, 0, QTableWidgetItem(str(level)))
            self._sync.setItem(index, 1, QTableWidgetItem(tr(label)))
        self._sync.setMaximumHeight(270)
        sync.body().addWidget(self._sync)
        column.addWidget(sync)

        memory = Card(tr("Mémoire et durée"))
        grid = QGridLayout()
        grid.setSpacing(6)
        grid.addWidget(QLabel(tr("Durée (s)")), 0, 0)
        self._mem_seconds = QSpinBox()
        self._mem_seconds.setRange(1, 36000)
        self._mem_seconds.setValue(60)
        self._mem_seconds.valueChanged.connect(
            self.guard(lambda _v: self._calc_memory()))
        grid.addWidget(self._mem_seconds, 0, 1)

        grid.addWidget(QLabel(tr("Fréquence")), 0, 2)
        self._mem_rate = QComboBox()
        for rate in (22050, 32000, 44100, 48000, 96000):
            self._mem_rate.addItem(f"{rate} Hz", rate)
        self._mem_rate.setCurrentIndex(2)
        self._mem_rate.activated.connect(
            self.guard(lambda _i: self._calc_memory()))
        grid.addWidget(self._mem_rate, 0, 3)

        grid.addWidget(QLabel(tr("Résolution")), 1, 0)
        self._mem_bits = QComboBox()
        for bits in (16, 24, 32):
            self._mem_bits.addItem(f"{bits} bits", bits)
        self._mem_bits.activated.connect(
            self.guard(lambda _i: self._calc_memory()))
        grid.addWidget(self._mem_bits, 1, 1)

        grid.addWidget(QLabel(tr("Canaux")), 1, 2)
        self._mem_channels = QComboBox()
        self._mem_channels.addItem(tr("mono"), 1)
        self._mem_channels.addItem(tr("stéréo"), 2)
        self._mem_channels.activated.connect(
            self.guard(lambda _i: self._calc_memory()))
        grid.addWidget(self._mem_channels, 1, 3)
        memory.body().addLayout(grid)

        self._memory_result = QLabel("")
        self._memory_result.setWordWrap(True)
        memory.body().addWidget(self._memory_result)
        column.addWidget(memory)
        column.addStretch(1)

        scroll.setWidget(inner)
        return scroll

    def _calc(self) -> None:
        bpm = float(self._bpm.value())
        self._delays.setRowCount(0)
        for entry in rhythm_mod.delay_times(bpm):
            index = self._delays.rowCount()
            self._delays.insertRow(index)
            for column, value in enumerate((
                    tr(entry["div"]), decimal(entry["ms"], 2),
                    decimal(entry["dotted_ms"], 2),
                    decimal(entry["triplet_ms"], 2),
                    decimal(entry["hz"], 3))):
                self._delays.setItem(index, column,
                                     QTableWidgetItem(str(value)))
        bar_ms = 4 * 60000.0 / bpm
        self._bar_length.setText(
            tr("Une mesure 4/4 dure %.0f ms (%s s) — 96 ticks")
            % (bar_ms, decimal(bar_ms / 1000, 2)))
        self._calc_memory()

    def _calc_memory(self) -> None:
        seconds = int(self._mem_seconds.value())
        rate = int(self._mem_rate.currentData() or 44100)
        bits = int(self._mem_bits.currentData() or 16)
        channels = int(self._mem_channels.currentData() or 1)
        size = seconds * rate * (bits // 8) * channels

        from ..widgets.common import human_size

        free = 0
        if self.sd is not None:
            try:
                free, _total = self.sd.free_space()
            except Exception:  # noqa: BLE001
                free = 0
        text = tr("%s pour %d s.") % (human_size(size), seconds)
        if free > 0 and size > 0:
            minutes = free / (size / max(1, seconds)) / 60.0
            text += "  " + tr("La place restante sur la carte permet environ "
                              "%.0f minutes d'enregistrement dans ce "
                              "format.") % minutes
        self._memory_result.setText(text)

    # -- mixage harmonique -------------------------------------------------- #

    def _build_camelot_tab(self) -> QWidget:
        host = QWidget()
        column = QVBoxLayout(host)
        column.setContentsMargins(0, PAD, 0, 0)
        column.setSpacing(PAD)

        card = Card(tr("Roue de Camelot"))
        hint = QLabel(tr(
            "Deux morceaux s'enchaînent sans fausse note si leurs codes sont "
            "identiques, voisins d'un cran, ou s'ils échangent majeur et "
            "mineur relatif."))
        hint.setProperty("role", "subtitle")
        hint.setWordWrap(True)
        card.body().addWidget(hint)

        self._wheel = QTableWidget(12, 3)
        self._wheel.setHorizontalHeaderLabels(
            [tr("Majeur"), tr("Mineur relatif"), tr("Compatibles")])
        self._wheel.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch)
        self._wheel.verticalHeader().setVisible(False)
        self._wheel.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        card.body().addWidget(self._wheel)
        column.addWidget(card, 1)

        search = Card(tr("Chercher dans la bibliothèque"))
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("Tonalité")))
        self._key_search = QLineEdit()
        self._key_search.setPlaceholderText(tr("ex. Am, C, F#m"))
        row.addWidget(self._key_search, 1)
        find = tool_button(tr("Chercher"), "search")
        find.clicked.connect(self.guard(self._search_by_key))
        row.addWidget(find)
        search.body().addLayout(row)

        self._key_results = QListWidget()
        search.body().addWidget(self._key_results)
        column.addWidget(search, 1)
        return host

    def _fill_wheel(self) -> None:
        for index, (major, minor) in enumerate(
                theory_mod.circle_of_fifths()):
            self._wheel.setItem(
                index, 0,
                QTableWidgetItem(f"{major}  ({theory_mod.camelot(major)})"))
            self._wheel.setItem(
                index, 1,
                QTableWidgetItem(f"{minor}  ({theory_mod.camelot(minor)})"))
            compatible = theory_mod.compatible_keys(major)
            self._wheel.setItem(
                index, 2, QTableWidgetItem("  ".join(compatible)))

    def _search_by_key(self) -> None:
        """Cherche les échantillons dont la tonalité est compatible."""
        wanted = self._key_search.text().strip()
        if not wanted:
            return
        compatible = theory_mod.compatible_keys(wanted)
        if not compatible:
            self.say(tr("Tonalité « %s » non comprise.") % wanted)
            return

        self._key_results.clear()
        self._key_results.addItem(
            tr("Compatibles avec %s : %s") % (wanted, "  ".join(compatible)))
        try:
            rows = self.lib.search_samples(limit=100000)
        except Exception as exc:  # noqa: BLE001
            log.debug("index indisponible : %s", exc)
            return
        wanted_set = {k.lower() for k in compatible}
        found = 0
        for row in rows:
            key = (row["key"] or "").strip()
            if key and key.lower() in wanted_set:
                bpm = f"{row['bpm']:.0f} BPM  " if row["bpm"] else ""
                self._key_results.addItem(f"  {key:5} {bpm}{row['rel']}")
                found += 1
                if found >= 300:
                    break
        if not found:
            self._key_results.addItem(
                "  " + tr("Aucun échantillon : lancez l'analyse acoustique "
                          "dans les réglages pour détecter les tonalités."))
        self.say(tr("%d échantillon(s) compatible(s).") % found)

    # -- aide-mémoire ------------------------------------------------------- #

    def _build_cheatsheet_tab(self) -> QWidget:
        browser = QTextBrowser()
        rows = "".join(
            f"<tr><th style='text-align:left;vertical-align:top;"
            f"padding:6px 12px 6px 0;color:#C79A22;white-space:nowrap'>"
            f"{tr(title)}</th>"
            f"<td style='padding:6px 0;border-bottom:1px solid #2F343E'>"
            f"{tr(text)}</td></tr>"
            for title, text in CHEATSHEET)
        browser.setHtml(
            "<html><body style=\"font-family:'Segoe UI',sans-serif;"
            "color:#F2F4F8\">"
            "<h2 style='color:#C79A22'>%s</h2>"
            "<p style='color:#7A828F'>%s</p>"
            "<table style='border-collapse:collapse'>%s</table>"
            "</body></html>" % (
                tr("Valeurs et limites du Deluge"),
                tr("Mesuré sur une carte réelle, ou documenté par le "
                   "firmware."), rows))
        return browser

    # -- rafraîchissement --------------------------------------------------- #

    def _refresh(self) -> None:
        self._show_scale()
        self._calc()
        self._fill_wheel()
