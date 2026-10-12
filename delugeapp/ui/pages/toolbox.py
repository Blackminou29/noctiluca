# -*- coding: utf-8 -*-
"""Page « Outils ».

Six onglets qui répondent aux questions qu'un producteur se pose en cours de
morceau, et qu'il résout d'habitude avec une calculatrice et un carnet :

* **Théorie** — gammes, accords, progressions, et le ``<modeNotes>`` à
  recopier dans le Deluge ;
* **Rythme** — motifs euclidiens et idiomatiques, groove, export MIDI ;
* **Calculatrice** — temps de délai, fréquences de notes, mémoire ;
* **Mixage harmonique** — roue de Camelot et tonalités compatibles ;
* **Arrangement** — modèles de structure par genre ;
* **Aide-mémoire** — les valeurs du Deluge qu'on oublie toujours.

Aucun onglet n'a besoin de la carte, sauf la recherche par tonalité du
mixage harmonique.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QScrollArea,
    QSpinBox,
    QSlider,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ...core import genres as genres_mod
from ...core import rhythm as rhythm_mod
from ...core import theory as theory_mod
from ..theme import GOLD, PAD, PAD_CYAN
from ..widgets.common import Card
from ..widgets.padgrid import StepSequencer
from ..widgets.piano import PianoKeys
from .base import Page, tool_button

log = logging.getLogger(__name__)

#: Modèles de structure par genre : ``(section, mesures)``.
ARRANGEMENTS: dict[str, tuple[tuple[str, int], ...]] = {
    "techno": (("Intro", 16), ("Montée", 16), ("Thème", 32), ("Cassure", 16),
               ("Thème 2", 32), ("Final", 16)),
    "house": (("Intro", 16), ("Couplet", 16), ("Montée", 8), ("Refrain", 32),
              ("Cassure", 16), ("Refrain 2", 32), ("Final", 16)),
    "trance": (("Intro", 16), ("Montée", 32), ("Cassure", 16),
               ("Explosion", 32), ("Thème", 32), ("Final", 16)),
    "dnb": (("Intro", 16), ("Montée", 16), ("Chute", 32), ("Cassure", 16),
            ("Chute 2", 32), ("Final", 8)),
    "ambient": (("Apparition", 32), ("Développement", 64),
                ("Point culminant", 32), ("Dissipation", 48)),
    "lofi": (("Intro", 8), ("Boucle A", 16), ("Boucle B", 16),
             ("Pont", 8), ("Boucle A", 16), ("Sortie", 8)),
}

#: Correspondance ``syncLevel`` du Deluge et division rythmique.
#:
#: Le firmware code la synchronisation en puissances de deux ; cette table
#: évite de la redécouvrir à chaque fois.
SYNC_LEVELS: tuple[tuple[int, str], ...] = (
    (0, "libre (non synchronisé)"),
    (1, "8 mesures"),
    (2, "4 mesures"),
    (3, "2 mesures"),
    (4, "1 mesure"),
    (5, "1/2 — blanche"),
    (6, "1/4 — noire"),
    (7, "1/8 — croche"),
    (8, "1/16 — double-croche"),
    (9, "1/32 — triple-croche"),
)

#: Aide-mémoire : limites et valeurs du Deluge, mesurées ou documentées.
CHEATSHEET: tuple[tuple[str, str], ...] = (
    ("Résolution rythmique",
     "24 ticks par noire, 96 par mesure 4/4. Un clip de 1536 ticks fait "
     "16 mesures."),
    ("Paramètres",
     "Entiers 32 bits : 0x80000000 = minimum, 0x00000000 = milieu, "
     "0x7FFFFFFF = maximum. L'écran affiche 0 à 50."),
    ("Câbles de modulation",
     "Échelle pleine 0x40000000, soit la MOITIÉ des autres paramètres. "
     "L'écran affiche −50 à +50."),
    ("Notes dans un clip",
     "22 caractères hexadécimaux par note : pos(8) longueur(8) vélocité(2) "
     "lift(2) condition(2). Le lift précède la condition."),
    ("Condition d'une note",
     "0x14 (20) = toujours. En dessous de 20, probabilité par pas de 5 %. "
     "À partir de 0x80, règle d'itération."),
    ("Gammes",
     "<modeNotes> attend exactement sept intervalles : l'écran réserve "
     "sept rangées de pads par octave."),
    ("Noms de fichiers",
     "FAT32 : pas de < > : \" / \\ | ? *, ni de point ou d'espace final. "
     "63 caractères au maximum, ASCII de préférence."),
    ("Firmware",
     "Un seul fichier deluge*.bin à la racine, sinon la mise à jour est "
     "refusée."),
    ("Dossiers attendus",
     "SONGS, SYNTHS, KITS, SAMPLES à la racine. Les percussions dans "
     "SAMPLES/DRUMS/<catégorie>."),
    ("Fréquence d'échantillonnage",
     "La machine tourne à 44,1 kHz. Les autres fréquences sont converties "
     "à la lecture."),
)


class ToolboxPage(Page):
    """Boîte à outils de composition."""

    TITLE = "Outils"
    ICON = "tools"
    #: Seul le mixage harmonique a besoin de la carte.
    NEEDS_CARD = False

    def __init__(self, ctx, parent=None) -> None:
        super().__init__(ctx, parent)
        self._pattern = None
        self._progression: list = []

    def build(self) -> None:
        outer = QVBoxLayout(self.content())
        outer.setContentsMargins(PAD, PAD, PAD, PAD)
        outer.setSpacing(8)

        header, _actions = self.header(
            "Boîte à outils",
            "Théorie, rythme, calculs et aide-mémoire")
        outer.addWidget(header)

        tabs = QTabWidget()
        tabs.addTab(self._build_theory_tab(), "Théorie")
        tabs.addTab(self._build_rhythm_tab(), "Rythme")
        tabs.addTab(self._build_calc_tab(), "Calculatrice")
        tabs.addTab(self._build_camelot_tab(), "Mixage harmonique")
        tabs.addTab(self._build_arrangement_tab(), "Arrangement")
        tabs.addTab(self._build_cheatsheet_tab(), "Aide-mémoire")
        outer.addWidget(tabs, 1)

    # -- théorie ------------------------------------------------------------ #

    def _build_theory_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        inner = QWidget()
        column = QVBoxLayout(inner)
        column.setContentsMargins(0, PAD, 0, 0)
        column.setSpacing(PAD)

        card = Card("Gamme")
        row = QHBoxLayout()
        row.addWidget(QLabel("Tonique"))
        self._root = QComboBox()
        for midi in range(48, 72):
            self._root.addItem(theory_mod.note_to_name(midi), midi)
        self._root.setCurrentIndex(12)       # Do3
        self._root.activated.connect(self.guard(lambda _i: self._show_scale()))
        row.addWidget(self._root)

        row.addWidget(QLabel("Gamme"))
        self._scale = QComboBox()
        for name in theory_mod.scale_names():
            self._scale.addItem(name, name)
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

        mode_row = QHBoxLayout()
        self._mode_notes = QLineEdit()
        self._mode_notes.setReadOnly(True)
        self._mode_notes.setToolTip(
            "Valeurs à recopier dans <modeNotes> d'un morceau du Deluge")
        mode_row.addWidget(QLabel("<modeNotes>"))
        mode_row.addWidget(self._mode_notes, 1)
        copy = tool_button("Copier", "copy")
        copy.clicked.connect(self.guard(self._copy_mode_notes))
        mode_row.addWidget(copy)
        card.body().addLayout(mode_row)
        column.addWidget(card)

        chords = Card("Accords de la gamme")
        self._chords = QTableWidget(0, 3)
        self._chords.setHorizontalHeaderLabels(["Degré", "Accord", "Notes"])
        self._chords.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch)
        self._chords.verticalHeader().setVisible(False)
        self._chords.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self._chords.itemSelectionChanged.connect(
            self.guard(self._highlight_chord))
        self._chords.setMaximumHeight(220)
        chords.body().addWidget(self._chords)
        column.addWidget(chords)

        prog = Card("Progression")
        prog_row = QHBoxLayout()
        prog_row.addWidget(QLabel("Ambiance"))
        self._progression_kind = QComboBox()
        for name in theory_mod.progression_names():
            self._progression_kind.addItem(name, name)
        prog_row.addWidget(self._progression_kind, 1)
        prog_row.addWidget(QLabel("Mesures"))
        self._progression_bars = QSpinBox()
        self._progression_bars.setRange(2, 16)
        self._progression_bars.setValue(4)
        prog_row.addWidget(self._progression_bars)
        make = tool_button("Proposer", "wand", primary=True)
        make.clicked.connect(self.guard(self._make_progression))
        prog_row.addWidget(make)
        export = tool_button("En MIDI", "export")
        export.clicked.connect(self.guard(self._export_progression))
        prog_row.addWidget(export)
        prog.body().addLayout(prog_row)

        self._progression_list = QListWidget()
        self._progression_list.setMaximumHeight(140)
        self._progression_list.currentRowChanged.connect(
            self.guard(self._highlight_progression))
        prog.body().addWidget(self._progression_list)
        column.addWidget(prog)
        column.addStretch(1)

        scroll.setWidget(inner)
        return scroll

    def _show_scale(self) -> None:
        root = self._root.currentData() or 60
        scale = self._scale.currentData() or "majeur"

        notes = theory_mod.scale_notes(root, scale, octaves=1)
        self._piano.set_highlight(
            [n - root for n in notes], GOLD)
        self._scale_notes.setText(
            f"{theory_mod.note_to_name(root, with_octave=False)} {scale} :  "
            + "  ".join(theory_mod.note_to_name(n, with_octave=False)
                        for n in notes[:-1]))
        self._mode_notes.setText(
            ", ".join(str(v) for v in theory_mod.deluge_mode_notes(scale)))

        self._chords.setRowCount(0)
        for symbol, chord_notes in theory_mod.diatonic_chords(root, scale):
            index = self._chords.rowCount()
            self._chords.insertRow(index)
            self._chords.setItem(index, 0, QTableWidgetItem(symbol))
            self._chords.setItem(
                index, 1,
                QTableWidgetItem(theory_mod.note_to_name(
                    chord_notes[0], with_octave=False) if chord_notes else "—"))
            item = QTableWidgetItem(
                "  ".join(theory_mod.note_to_name(n) for n in chord_notes))
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
        self.say(f"{theory_mod.note_to_name(midi)} — "
                 f"{theory_mod.frequency(midi):.2f} Hz — MIDI {midi}")

    def _copy_mode_notes(self) -> None:
        from PyQt6.QtWidgets import QApplication

        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self._mode_notes.text())
            self.say("Valeurs de <modeNotes> copiées.")

    def _make_progression(self) -> None:
        root = self._root.currentData() or 60
        scale = self._scale.currentData() or "majeur"
        self._progression = theory_mod.progression(
            root, scale, self._progression_kind.currentData() or "",
            bars=int(self._progression_bars.value()))
        self._progression_list.clear()
        for chord in self._progression:
            notes = "  ".join(theory_mod.note_to_name(n)
                              for n in chord["notes"])
            self._progression_list.addItem(
                f"{chord['degree']:<5} {chord['symbol']:<7} {notes}")
        self.say(f"{len(self._progression)} accords proposés.")

    def _highlight_progression(self, row: int) -> None:
        if not 0 <= row < len(self._progression):
            return
        self._piano.set_exact_highlight(
            self._progression[row]["notes"], PAD_CYAN)

    def _export_progression(self) -> None:
        if not self._progression:
            self.say("Proposez d'abord une progression.")
            return
        from ...core import midifile

        chosen, _f = QFileDialog.getSaveFileName(
            self, "Exporter la progression", "progression.mid",
            "Fichier MIDI (*.mid)")
        if not chosen:
            return
        try:
            midifile.progression_to_midi(Path(chosen), self._progression, 120)
        except Exception as exc:  # noqa: BLE001
            log.exception("export MIDI impossible")
            self.say(f"Export impossible : {exc}")
            return
        self.say(f"Progression exportée : {Path(chosen).name}")

    # -- rythme ------------------------------------------------------------- #

    def _build_rhythm_tab(self) -> QWidget:
        host = QWidget()
        column = QVBoxLayout(host)
        column.setContentsMargins(0, PAD, 0, 0)
        column.setSpacing(PAD)

        card = Card("Motif")
        grid = QGridLayout()
        grid.setSpacing(6)

        grid.addWidget(QLabel("Genre"), 0, 0)
        self._beat_genre = QComboBox()
        for key in genres_mod.genre_keys():
            self._beat_genre.addItem(genres_mod.genre(key).label, key)
        grid.addWidget(self._beat_genre, 0, 1)

        grid.addWidget(QLabel("Mesures"), 0, 2)
        self._beat_bars = QSpinBox()
        self._beat_bars.setRange(1, 4)
        grid.addWidget(self._beat_bars, 0, 3)

        from_genre = tool_button("Motif du genre", "wand", primary=True)
        from_genre.clicked.connect(self.guard(self._beat_from_genre))
        grid.addWidget(from_genre, 0, 4)

        grid.addWidget(QLabel("Euclidien"), 1, 0)
        euclid_row = QHBoxLayout()
        self._pulses = QSpinBox()
        self._pulses.setRange(0, 32)
        self._pulses.setValue(5)
        self._pulses.setPrefix("coups ")
        euclid_row.addWidget(self._pulses)
        self._steps = QSpinBox()
        self._steps.setRange(1, 32)
        self._steps.setValue(16)
        self._steps.setPrefix("pas ")
        euclid_row.addWidget(self._steps)
        self._rotation = QSpinBox()
        self._rotation.setRange(0, 31)
        self._rotation.setPrefix("rotation ")
        euclid_row.addWidget(self._rotation)
        holder = QWidget()
        holder.setLayout(euclid_row)
        grid.addWidget(holder, 1, 1, 1, 3)

        euclid = tool_button("Ajouter la piste", "plus")
        euclid.clicked.connect(self.guard(self._add_euclid))
        grid.addWidget(euclid, 1, 4)
        card.body().addLayout(grid)

        groove_row = QHBoxLayout()
        groove_row.addWidget(QLabel("Groove"))
        self._groove = QComboBox()
        for name in rhythm_mod.groove_names():
            self._groove.addItem(name, name)
        groove_row.addWidget(self._groove)
        groove_row.addWidget(QLabel("Swing"))
        self._swing = QSlider(Qt.Orientation.Horizontal)
        self._swing.setRange(0, 100)
        groove_row.addWidget(self._swing, 1)
        apply_groove = tool_button("Appliquer", "check")
        apply_groove.clicked.connect(self.guard(self._apply_groove))
        groove_row.addWidget(apply_groove)
        export = tool_button("En MIDI", "export")
        export.clicked.connect(self.guard(self._export_beat))
        groove_row.addWidget(export)
        card.body().addLayout(groove_row)

        self._sequencer = StepSequencer()
        self._sequencer.setMinimumHeight(130)
        card.body().addWidget(self._sequencer)

        self._ascii = QPlainTextEdit()
        self._ascii.setReadOnly(True)
        self._ascii.setMaximumHeight(130)
        self._ascii.setProperty("role", "mono")
        self._ascii.setToolTip("Représentation texte, à recopier dans un carnet")
        card.body().addWidget(self._ascii)
        column.addWidget(card, 1)
        return host

    def _beat_from_genre(self) -> None:
        self._pattern = rhythm_mod.genre_beat(
            self._beat_genre.currentData() or "techno",
            bars=int(self._beat_bars.value()), seed=1)
        self._show_pattern()

    def _add_euclid(self) -> None:
        """Ajoute une piste euclidienne au motif courant."""
        pulses = int(self._pulses.value())
        steps = int(self._steps.value())
        rotation = int(self._rotation.value())

        if self._pattern is None:
            self._pattern = rhythm_mod.Pattern(name="Euclidien", steps=steps)
        name = f"E({pulses},{steps})"
        if rotation:
            name += f"+{rotation}"

        cells = rhythm_mod.euclid(pulses, steps, rotation)
        self._pattern.tracks[name] = [
            rhythm_mod.Step(pos=i, velocity=100)
            for i, on in enumerate(cells) if on]
        self._show_pattern()
        self.say(f"Piste {name} ajoutée.")

    def _apply_groove(self) -> None:
        if self._pattern is None:
            self.say("Créez d'abord un motif.")
            return
        pattern = rhythm_mod.apply_groove(
            self._pattern, self._groove.currentData() or "droit", 1.0)
        swing = self._swing.value() / 100.0
        if swing > 0:
            pattern = rhythm_mod.swing(pattern, swing)
        self._pattern = pattern
        self._show_pattern()
        self.say("Groove appliqué.")

    def _show_pattern(self) -> None:
        if self._pattern is None:
            return
        self._sequencer.set_pattern(self._pattern)
        self._ascii.setPlainText(self._pattern.ascii())

    def _export_beat(self) -> None:
        pattern = self._sequencer.pattern() or self._pattern
        if pattern is None or not any(pattern.tracks.values()):
            self.say("Créez d'abord un motif.")
            return
        from ...core import midifile

        chosen, _f = QFileDialog.getSaveFileName(
            self, "Exporter le motif", "motif.mid", "Fichier MIDI (*.mid)")
        if not chosen:
            return
        try:
            midifile.pattern_to_midi(Path(chosen), pattern, None, 128)
        except Exception as exc:  # noqa: BLE001
            log.exception("export MIDI impossible")
            self.say(f"Export impossible : {exc}")
            return
        self.say(f"Motif exporté : {Path(chosen).name}")

    # -- calculatrice ------------------------------------------------------- #

    def _build_calc_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        inner = QWidget()
        column = QVBoxLayout(inner)
        column.setContentsMargins(0, PAD, 0, 0)
        column.setSpacing(PAD)

        card = Card("Tempo")
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
            ["Division", "Droit (ms)", "Pointé (ms)", "Triolet (ms)",
             "Hz (LFO)"])
        self._delays.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self._delays.verticalHeader().setVisible(False)
        self._delays.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self._delays.setMaximumHeight(230)
        card.body().addWidget(self._delays)
        column.addWidget(card)

        sync = Card("syncLevel du Deluge")
        self._sync = QTableWidget(0, 2)
        self._sync.setHorizontalHeaderLabels(["syncLevel", "Division"])
        self._sync.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self._sync.verticalHeader().setVisible(False)
        self._sync.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        for level, label in SYNC_LEVELS:
            index = self._sync.rowCount()
            self._sync.insertRow(index)
            self._sync.setItem(index, 0, QTableWidgetItem(str(level)))
            self._sync.setItem(index, 1, QTableWidgetItem(label))
        self._sync.setMaximumHeight(270)
        sync.body().addWidget(self._sync)
        column.addWidget(sync)

        memory = Card("Mémoire et durée")
        grid = QGridLayout()
        grid.setSpacing(6)
        grid.addWidget(QLabel("Durée (s)"), 0, 0)
        self._mem_seconds = QSpinBox()
        self._mem_seconds.setRange(1, 36000)
        self._mem_seconds.setValue(60)
        self._mem_seconds.valueChanged.connect(
            self.guard(lambda _v: self._calc_memory()))
        grid.addWidget(self._mem_seconds, 0, 1)

        grid.addWidget(QLabel("Fréquence"), 0, 2)
        self._mem_rate = QComboBox()
        for rate in (22050, 32000, 44100, 48000, 96000):
            self._mem_rate.addItem(f"{rate} Hz", rate)
        self._mem_rate.setCurrentIndex(2)
        self._mem_rate.activated.connect(
            self.guard(lambda _i: self._calc_memory()))
        grid.addWidget(self._mem_rate, 0, 3)

        grid.addWidget(QLabel("Résolution"), 1, 0)
        self._mem_bits = QComboBox()
        for bits in (16, 24, 32):
            self._mem_bits.addItem(f"{bits} bits", bits)
        self._mem_bits.activated.connect(
            self.guard(lambda _i: self._calc_memory()))
        grid.addWidget(self._mem_bits, 1, 1)

        grid.addWidget(QLabel("Canaux"), 1, 2)
        self._mem_channels = QComboBox()
        self._mem_channels.addItem("mono", 1)
        self._mem_channels.addItem("stéréo", 2)
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
                    entry["div"], f"{entry['ms']:.2f}",
                    f"{entry['dotted_ms']:.2f}",
                    f"{entry['triplet_ms']:.2f}", f"{entry['hz']:.3f}")):
                self._delays.setItem(index, column,
                                     QTableWidgetItem(str(value)))
        bar_ms = 4 * 60000.0 / bpm
        self._bar_length.setText(
            f"Une mesure 4/4 dure {bar_ms:.0f} ms "
            f"({bar_ms / 1000:.2f} s) — 96 ticks")
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
        text = f"{human_size(size)} pour {seconds} s."
        if free > 0 and size > 0:
            minutes = free / (size / max(1, seconds)) / 60.0
            text += (f"  La place restante sur la carte permet environ "
                     f"{minutes:.0f} minutes d'enregistrement dans ce "
                     f"format.")
        self._memory_result.setText(text)

    # -- mixage harmonique -------------------------------------------------- #

    def _build_camelot_tab(self) -> QWidget:
        host = QWidget()
        column = QVBoxLayout(host)
        column.setContentsMargins(0, PAD, 0, 0)
        column.setSpacing(PAD)

        card = Card("Roue de Camelot")
        hint = QLabel(
            "Deux morceaux s'enchaînent sans fausse note si leurs codes sont "
            "identiques, voisins d'un cran, ou s'ils échangent majeur et "
            "mineur relatif.")
        hint.setProperty("role", "subtitle")
        hint.setWordWrap(True)
        card.body().addWidget(hint)

        self._wheel = QTableWidget(12, 3)
        self._wheel.setHorizontalHeaderLabels(
            ["Majeur", "Mineur relatif", "Compatibles"])
        self._wheel.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch)
        self._wheel.verticalHeader().setVisible(False)
        self._wheel.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        card.body().addWidget(self._wheel)
        column.addWidget(card, 1)

        search = Card("Chercher dans la bibliothèque")
        row = QHBoxLayout()
        row.addWidget(QLabel("Tonalité"))
        self._key_search = QLineEdit()
        self._key_search.setPlaceholderText("ex. Am, C, F#m")
        row.addWidget(self._key_search, 1)
        find = tool_button("Chercher", "search")
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
            self.say(f"Tonalité « {wanted} » non comprise.")
            return

        self._key_results.clear()
        self._key_results.addItem(
            f"Compatibles avec {wanted} : {'  '.join(compatible)}")
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
                "  Aucun échantillon : lancez l'analyse acoustique dans les "
                "réglages pour détecter les tonalités.")
        self.say(f"{found} échantillon(s) compatible(s).")

    # -- arrangement -------------------------------------------------------- #

    def _build_arrangement_tab(self) -> QWidget:
        host = QWidget()
        column = QVBoxLayout(host)
        column.setContentsMargins(0, PAD, 0, 0)
        column.setSpacing(PAD)

        card = Card("Modèle de structure")
        row = QHBoxLayout()
        row.addWidget(QLabel("Genre"))
        self._arr_genre = QComboBox()
        for key in ARRANGEMENTS:
            self._arr_genre.addItem(genres_mod.genre(key).label, key)
        self._arr_genre.activated.connect(
            self.guard(lambda _i: self._show_arrangement()))
        row.addWidget(self._arr_genre, 1)
        row.addWidget(QLabel("BPM"))
        self._arr_bpm = QSpinBox()
        self._arr_bpm.setRange(20, 400)
        self._arr_bpm.setValue(128)
        self._arr_bpm.valueChanged.connect(
            self.guard(lambda _v: self._show_arrangement()))
        row.addWidget(self._arr_bpm)
        card.body().addLayout(row)

        self._arrangement = QTableWidget(0, 4)
        self._arrangement.setHorizontalHeaderLabels(
            ["Section", "Mesures", "Durée", "Position"])
        self._arrangement.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self._arrangement.verticalHeader().setVisible(False)
        self._arrangement.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        card.body().addWidget(self._arrangement)

        self._arr_total = QLabel("")
        self._arr_total.setProperty("role", "subtitle")
        card.body().addWidget(self._arr_total)
        column.addWidget(card, 1)
        return host

    def _show_arrangement(self) -> None:
        key = self._arr_genre.currentData() or "techno"
        bpm = float(self._arr_bpm.value())
        sections = ARRANGEMENTS.get(key, ARRANGEMENTS["techno"])
        bar_seconds = 4 * 60.0 / bpm

        self._arrangement.setRowCount(0)
        position = 0
        for index, (name, bars) in enumerate(sections):
            row = self._arrangement.rowCount()
            self._arrangement.insertRow(row)
            item = QTableWidgetItem(name)
            item.setForeground(Qt.GlobalColor.white)
            self._arrangement.setItem(row, 0, item)
            self._arrangement.setItem(row, 1, QTableWidgetItem(str(bars)))
            seconds = bars * bar_seconds
            self._arrangement.setItem(
                row, 2,
                QTableWidgetItem(f"{int(seconds // 60)}:{int(seconds % 60):02d}"))
            start = position * bar_seconds
            self._arrangement.setItem(
                row, 3,
                QTableWidgetItem(f"mesure {position + 1} — "
                                 f"{int(start // 60)}:{int(start % 60):02d}"))
            position += bars

        total = position * bar_seconds
        self._arr_total.setText(
            f"{position} mesures au total, soit "
            f"{int(total // 60)} min {int(total % 60):02d} s à {bpm:.0f} BPM. "
            f"Les sections du Deluge se règlent dans la vue Morceau.")

    # -- aide-mémoire ------------------------------------------------------- #

    def _build_cheatsheet_tab(self) -> QWidget:
        browser = QTextBrowser()
        rows = "".join(
            f"<tr><th style='text-align:left;vertical-align:top;"
            f"padding:6px 12px 6px 0;color:#C79A22;white-space:nowrap'>"
            f"{title}</th>"
            f"<td style='padding:6px 0;border-bottom:1px solid #2F343E'>"
            f"{text}</td></tr>"
            for title, text in CHEATSHEET)
        browser.setHtml(
            "<html><body style=\"font-family:'Segoe UI',sans-serif;"
            "color:#F2F4F8\">"
            "<h2 style='color:#C79A22'>Valeurs et limites du Deluge</h2>"
            "<p style='color:#7A828F'>Mesuré sur une carte réelle, "
            "ou documenté par le firmware.</p>"
            f"<table style='border-collapse:collapse'>{rows}</table>"
            "</body></html>")
        return browser

    # -- rafraîchissement --------------------------------------------------- #

    def _refresh(self) -> None:
        self._show_scale()
        self._calc()
        self._fill_wheel()
        self._show_arrangement()
        if self._pattern is None:
            self._beat_from_genre()
