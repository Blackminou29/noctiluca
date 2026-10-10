# -*- coding: utf-8 -*-
"""Page « Presets ».

Parcourt les 911 presets de synthé de la carte d'essai, et montre pour chacun
ce qui fait son caractère : oscillateurs, filtre, enveloppes, modulations,
effets. Le son peut être écouté sans passer par le Deluge, grâce au moteur de
:mod:`delugeapp.core.render`.

L'écoute est calculée dans un fil séparé. Un rendu de 2,5 s prend environ
50 ms, mais un preset à huit voix d'unisson avec tous les effets peut monter à
70 ms, et le faire dans le fil de l'interface se verrait au défilement.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QScrollArea,
    QSplitter,
    QTableView,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.fixedpoint import to_display
from ..theme import GOLD, GREY, PAD, PAD_GREEN, PAD_RED, category_color
from ..widgets.common import (
    Card,
    ElidedLabel,
    KeyValueTable,
    RowTableModel,
    SearchBar,
    configure_table,
    human_size,
    sorted_proxy,
)
from ..widgets.envelope import EnvelopeEditor
from ..widgets.filtercurve import FilterCurve, SpectrumView
from ..widgets.knob import Knob
from ..widgets.waveform import WaveformView
from .base import Page, page_header, tool_button

log = logging.getLogger(__name__)

#: Paramètres montrés en encodeurs, dans cet ordre.
KNOB_PARAMS: tuple[tuple[str, str, bool], ...] = (
    ("volume", "Volume", False),
    ("lpfFrequency", "Coupure", False),
    ("lpfResonance", "Résonance", False),
    ("oscAVolume", "Osc A", False),
    ("oscBVolume", "Osc B", False),
    ("reverbAmount", "Réverb.", False),
    ("delayFeedback", "Délai", False),
    ("modFXDepth", "Mod FX", False),
    ("pan", "Panoramique", True),
)


class SynthsPage(Page):
    """Presets de synthé."""

    TITLE = "Presets"
    ICON = "synth"
    #: ``'synth'`` ou ``'kit'`` : la page des kits réutilise cette classe.
    KIND = "synth"

    #: Un preset a été choisi (utile au générateur pour partir de celui-ci).
    presetChosen = pyqtSignal(str)

    def __init__(self, ctx, parent=None) -> None:
        super().__init__(ctx, parent)
        self._model: RowTableModel | None = None
        self._proxy = None
        self._preset = None
        self._current = ""
        self._audio = None

    # -- construction ------------------------------------------------------- #

    def build(self) -> None:
        outer = QVBoxLayout(self.content())
        outer.setContentsMargins(PAD, PAD, PAD, PAD)
        outer.setSpacing(8)

        header, actions = page_header(
            "Presets de synthé",
            "Parcourir, écouter et comprendre les sons de la carte")
        outer.addWidget(header)

        listen = tool_button("Écouter", "play", primary=True)
        listen.clicked.connect(self.guard(self._listen))
        actions.addWidget(listen)

        stop = tool_button("Arrêter", "stop")
        stop.clicked.connect(self.guard(self._stop))
        actions.addWidget(stop)

        duplicate = tool_button("Dupliquer", "copy",
                                "Enregistrer une copie à côté de l'original")
        duplicate.clicked.connect(self.guard(self._duplicate))
        actions.addWidget(duplicate)

        row = QHBoxLayout()
        row.setSpacing(6)
        self._search = SearchBar("Rechercher un preset…")
        self._search.searchChanged.connect(self.guard(lambda _t: self._reload()))
        row.addWidget(self._search, 2)
        self._category = QComboBox()
        self._category.addItem("Toutes catégories", "")
        self._category.activated.connect(self.guard(lambda _i: self._reload()))
        row.addWidget(self._category, 1)
        holder = QWidget()
        holder.setLayout(row)
        outer.addWidget(holder)

        splitter = QSplitter(Qt.Orientation.Horizontal, self.content())
        splitter.addWidget(self._build_table())
        splitter.addWidget(self._build_detail())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 4)
        outer.addWidget(splitter, 1)

        self._count = QLabel()
        self._count.setProperty("role", "subtitle")
        outer.addWidget(self._count)

    def _build_table(self) -> QWidget:
        card = Card("")
        self._table = QTableView()
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        card.body().addWidget(self._table)
        return card

    def _build_detail(self) -> QWidget:
        tabs = QTabWidget()
        tabs.addTab(self._build_summary_tab(), "Vue d'ensemble")
        tabs.addTab(self._build_params_tab(), "Paramètres")
        tabs.addTab(self._build_mod_tab(), "Modulations")
        self._tabs = tabs
        return tabs

    def _build_summary_tab(self) -> QWidget:
        host = QScrollArea()
        host.setWidgetResizable(True)
        host.setFrameShape(QScrollArea.Shape.NoFrame)
        inner = QWidget()
        column = QVBoxLayout(inner)
        column.setContentsMargins(PAD, PAD, PAD, PAD)
        column.setSpacing(8)

        self._name = ElidedLabel("Aucun preset sélectionné")
        self._name.setProperty("role", "title")
        column.addWidget(self._name)

        self._path = ElidedLabel("")
        self._path.setProperty("role", "mono")
        column.addWidget(self._path)

        self._description = QLabel("")
        self._description.setWordWrap(True)
        column.addWidget(self._description)

        self._info = KeyValueTable()
        self._info.setMaximumHeight(190)
        column.addWidget(self._info)

        self._wave = WaveformView()
        self._wave.setMinimumHeight(80)
        column.addWidget(self._wave)

        self._spectrum = SpectrumView()
        self._spectrum.setMinimumHeight(90)
        column.addWidget(self._spectrum)

        samples_label = QLabel("Échantillons utilisés")
        samples_label.setProperty("role", "subtitle")
        column.addWidget(samples_label)
        self._samples = QTableWidget(0, 2)
        self._samples.setHorizontalHeaderLabels(["Fichier", "Présent"])
        self._samples.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self._samples.verticalHeader().setVisible(False)
        self._samples.setMaximumHeight(150)
        self._samples.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        column.addWidget(self._samples)
        column.addStretch(1)

        host.setWidget(inner)
        return host

    def _build_params_tab(self) -> QWidget:
        host = QScrollArea()
        host.setWidgetResizable(True)
        host.setFrameShape(QScrollArea.Shape.NoFrame)
        inner = QWidget()
        column = QVBoxLayout(inner)
        column.setContentsMargins(PAD, PAD, PAD, PAD)
        column.setSpacing(PAD)

        knobs = Card("Principaux réglages")
        grid = QGridLayout()
        grid.setSpacing(6)
        self._knobs: dict[str, Knob] = {}
        for index, (key, label, bipolar) in enumerate(KNOB_PARAMS):
            knob = Knob(label, 25, -25 if bipolar else 0, 25 if bipolar else 50,
                        bipolar)
            knob.setEnabled(False)      # lecture seule : l'édition viendra
            grid.addWidget(knob, index // 5, index % 5)
            self._knobs[key] = knob
        knobs.body().addLayout(grid)
        column.addWidget(knobs)

        envelopes = Card("Enveloppes")
        self._env1 = EnvelopeEditor(title="Enveloppe 1 — amplitude")
        self._env2 = EnvelopeEditor(title="Enveloppe 2 — modulation")
        envelopes.body().addWidget(self._env1)
        envelopes.body().addWidget(self._env2)
        column.addWidget(envelopes)

        filtre = Card("Filtre")
        self._filter = FilterCurve()
        filtre.body().addWidget(self._filter)
        column.addWidget(filtre)
        column.addStretch(1)

        host.setWidget(inner)
        return host

    def _build_mod_tab(self) -> QWidget:
        host = QWidget()
        column = QVBoxLayout(host)
        column.setContentsMargins(PAD, PAD, PAD, PAD)
        column.setSpacing(8)

        cables_label = QLabel("Câbles de modulation")
        cables_label.setProperty("role", "subtitle")
        column.addWidget(cables_label)

        self._cables = QTableWidget(0, 3)
        self._cables.setHorizontalHeaderLabels(
            ["Source", "Destination", "Profondeur"])
        self._cables.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self._cables.verticalHeader().setVisible(False)
        self._cables.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        column.addWidget(self._cables, 1)

        knobs_label = QLabel("Encodeurs assignés (modKnobs)")
        knobs_label.setProperty("role", "subtitle")
        column.addWidget(knobs_label)

        self._modknobs = QTableWidget(0, 2)
        self._modknobs.setHorizontalHeaderLabels(["Paramètre", "Source"])
        self._modknobs.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self._modknobs.verticalHeader().setVisible(False)
        self._modknobs.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        column.addWidget(self._modknobs, 1)
        return host

    # -- colonnes ----------------------------------------------------------- #

    def _columns(self) -> list:
        left = Qt.AlignmentFlag.AlignLeft
        right = Qt.AlignmentFlag.AlignRight

        def get(key, default=None):
            return lambda row: (row[key] if key in row.keys() else default)

        return [
            ("Nom", get("name"), 200, left),
            ("Dossier", get("folder"), 200, left),
            ("Catégorie", get("category"), 95, left),
            ("Moteur", get("mode"), 90, left),
            ("Osc 1", get("osc1"), 110, left),
            ("Filtre", get("filter"), 120, left),
            ("Effets", get("fx"), 150, left),
            ("Firmware", get("firmware"), 85, left),
            ("Taille", get("size"), 80, right, human_size),
        ]

    # -- chargement --------------------------------------------------------- #

    def _reload(self) -> None:
        try:
            rows = self.lib.search_presets(
                kind=self.KIND,
                text=self._search.text().strip(),
                category=self._category.currentData() or "",
                limit=100000)
        except Exception:  # noqa: BLE001
            log.exception("recherche de presets en échec")
            rows = []

        if self._model is None:
            self._model = RowTableModel(self._columns(), rows, self)
            self._proxy = sorted_proxy(self._model, self)
            self._table.setModel(self._proxy)
            configure_table(self._table, self._model)
            self._table.horizontalHeader().setSectionResizeMode(
                1, QHeaderView.ResizeMode.Stretch)
            selection = self._table.selectionModel()
            if selection is not None:
                selection.selectionChanged.connect(
                    self.guard(lambda *_a: self._on_selected()))
        else:
            self._model.set_rows(rows)

        label = "preset(s)" if self.KIND == "synth" else "kit(s)"
        self._count.setText(f"{len(rows)} {label} affiché(s)")

    def _selected_row(self):
        if self._model is None or self._proxy is None:
            return None
        selection = self._table.selectionModel()
        if selection is None:
            return None
        rows = selection.selectedRows()
        if not rows:
            return None
        return self._model.row_at(self._proxy.mapToSource(rows[0]).row())

    def _on_selected(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        rel = row["rel"] if "rel" in row.keys() else ""
        self._current = rel
        self.presetChosen.emit(rel)
        self._load_preset(rel, row)

    def _load_preset(self, rel: str, row) -> None:
        """Charge le preset et remplit les trois onglets."""
        from ...core.model import SynthPreset

        self._name.setText(Path(rel).stem or "—")
        self._path.setText(rel)

        if self.sd is None:
            return
        path = self.sd.abs(rel)
        try:
            self._preset = SynthPreset.load(path)
        except Exception as exc:  # noqa: BLE001 - 14 % des XML sont abîmés
            log.debug("preset illisible %s : %s", rel, exc)
            self._preset = None
            self._description.setText(f"Fichier illisible : {exc}")
            self._info.set_rows([("Erreur", str(exc))])
            self._wave.clear()
            self._spectrum.clear()
            self._samples.setRowCount(0)
            self._cables.setRowCount(0)
            self._modknobs.setRowCount(0)
            return

        sound = self._preset.sound
        self._fill_summary(rel, row, sound)
        self._fill_params(sound)
        self._fill_modulations(sound)

    def _fill_summary(self, rel: str, row, sound) -> None:
        from ...core import synthgen

        try:
            self._description.setText(synthgen.describe(self._preset))
        except Exception as exc:  # noqa: BLE001
            log.debug("description impossible : %s", exc)
            self._description.setText("")

        details: list[tuple[str, object]] = [
            ("Moteur", sound.mode),
            ("Polyphonie", sound.polyphonic),
            ("Oscillateur 1", sound.osc_label(sound.osc1)),
            ("Oscillateur 2", sound.osc_label(sound.osc2)),
            ("Filtre", sound.filter_label()),
            ("Effets", ", ".join(sound.fx_list()) or "aucun"),
            ("Unisson", f"{sound.unison_num} voix, "
                        f"désaccord {sound.unison_detune}"),
            ("Arpégiateur", sound.arp.mode if sound.arp.is_on else "éteint"),
            ("Catégorie devinée", sound.category_guess()),
            ("Caractère", ", ".join(sound.tonal_tags()) or "—"),
            ("Firmware", sound.firmware or "—"),
        ]
        repaired = row["repaired"] if "repaired" in row.keys() else ""
        if repaired:
            details.append(("Réparations à la lecture", repaired))
        self._info.set_rows(details)

        # Échantillons utilisés, avec leur présence réelle.
        paths = sound.sample_paths()
        self._samples.setRowCount(0)
        for ref in paths:
            index = self._samples.rowCount()
            self._samples.insertRow(index)
            item = QTableWidgetItem(ref)
            item.setToolTip(ref)
            self._samples.setItem(index, 0, item)
            present = (self.sd is not None
                       and self.sd.resolve_sample(ref) is not None)
            state = QTableWidgetItem("oui" if present else "ABSENT")
            state.setForeground(Qt.GlobalColor.green if present
                                else Qt.GlobalColor.red)
            self._samples.setItem(index, 1, state)

    def _fill_params(self, sound) -> None:
        for key, knob in self._knobs.items():
            try:
                knob.set_value(sound.display(key))
            except Exception:  # noqa: BLE001
                knob.set_value(0)

        self._env1.set_adsr(to_display(sound.env1.attack),
                            to_display(sound.env1.decay),
                            to_display(sound.env1.sustain),
                            to_display(sound.env1.release))
        self._env2.set_adsr(to_display(sound.env2.attack),
                            to_display(sound.env2.decay),
                            to_display(sound.env2.sustain),
                            to_display(sound.env2.release))
        self._filter.set_filter(sound.display("lpfFrequency"),
                                sound.display("lpfResonance"),
                                sound.lpf_mode)
        self._filter.set_hpf(sound.display("hpfFrequency")
                             if sound.hpf_mode else None)

    def _fill_modulations(self, sound) -> None:
        self._cables.setRowCount(0)
        for cable in sound.patch_cables:
            index = self._cables.rowCount()
            self._cables.insertRow(index)
            self._cables.setItem(index, 0, QTableWidgetItem(cable.source))
            self._cables.setItem(index, 1,
                                 QTableWidgetItem(cable.destination))
            depth = cable.display()
            self._cables.setItem(
                index, 2, QTableWidgetItem(f"{depth:+d}"))

        self._modknobs.setRowCount(0)
        for knob in sound.mod_knobs:
            if not (knob.controls_param or knob.patch_amount_from_source):
                continue
            index = self._modknobs.rowCount()
            self._modknobs.insertRow(index)
            self._modknobs.setItem(
                index, 0, QTableWidgetItem(knob.controls_param or "—"))
            self._modknobs.setItem(
                index, 1,
                QTableWidgetItem(knob.patch_amount_from_source or "—"))

    # -- écoute ------------------------------------------------------------- #

    def _listen(self) -> None:
        """Rend le preset et le joue, hors du fil de l'interface."""
        if self._preset is None:
            self.say("Aucun preset sélectionné.")
            return
        self.say("Rendu du son…")
        self.run(self._render, self._preset,
                 on_result=self.guard(self._play_rendered),
                 on_error=self.guard(
                     lambda m: self.say(f"Rendu impossible : {m}")),
                 title="Rendu du preset")

    def _render(self, preset):
        """Travail de fond : rendu audio du preset."""
        from ...core import render

        return render.render_preview(preset, sr=44100, sd=self.sd)

    def _play_rendered(self, audio) -> None:
        if audio is None:
            return
        self._audio = audio
        try:
            self._spectrum.set_audio(audio, 44100)
        except Exception as exc:  # noqa: BLE001
            log.debug("spectre impossible : %s", exc)

        # Enveloppe du rendu, pour voir la forme du son obtenu.
        try:
            import numpy as np

            mono = audio.mean(axis=1) if audio.ndim > 1 else audio
            buckets = 900
            step = max(1, mono.size // buckets)
            usable = mono[:step * buckets].reshape(buckets, step)
            peaks = np.stack([usable.min(axis=1), usable.max(axis=1)],
                             axis=1).astype("float32")
            self._wave.set_peaks(peaks, mono.size / 44100.0, 44100)
        except Exception as exc:  # noqa: BLE001
            log.debug("enveloppe du rendu impossible : %s", exc)

        if self.player is None:
            self.say("Aucune sortie audio disponible.")
            return
        try:
            self.player.set_volume(self.ctx.settings.preview_volume)
            self.player.play_array(audio, 44100)
            self.say("Lecture…")
        except Exception as exc:  # noqa: BLE001
            log.debug("lecture impossible : %s", exc)
            self.say(f"Lecture impossible : {exc}")

    def _stop(self) -> None:
        if self.player is not None:
            try:
                self.player.stop()
            except Exception as exc:  # noqa: BLE001
                log.debug("arrêt impossible : %s", exc)

    # -- duplication -------------------------------------------------------- #

    def _duplicate(self) -> None:
        """Enregistre une copie du preset à côté de l'original."""
        if self._preset is None or not self._current:
            self.say("Aucun preset sélectionné.")
            return
        card = self.card_or_warn()
        if card is None:
            return

        from ...core.sdcard import safe_deluge_name

        source = card.abs(self._current)
        stem = safe_deluge_name(f"{source.stem} copie")
        target = source.with_name(f"{stem}{source.suffix}")
        index = 2
        while target.exists():
            target = source.with_name(f"{stem} {index}{source.suffix}")
            index += 1

        if self.ctx.settings.confirm_writes:
            answer = QMessageBox.question(
                self, "Dupliquer le preset",
                f"Créer « {target.name} » dans {target.parent.name} ?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes)
            if answer != QMessageBox.StandardButton.Yes:
                return

        try:
            copy = self._preset.copy(target.stem)
            copy.save(target, backup=False)
        except Exception as exc:  # noqa: BLE001
            log.exception("duplication impossible")
            self.say(f"Duplication impossible : {exc}")
            return
        card.invalidate_cache()
        self.say(f"Copie créée : {target.name}")
        self._refresh()

    # -- rafraîchissement --------------------------------------------------- #

    def _refresh(self) -> None:
        self._fill_categories()
        self._reload()

    def _fill_categories(self) -> None:
        current = self._category.currentData() or ""
        self._category.blockSignals(True)
        self._category.clear()
        self._category.addItem("Toutes catégories", "")
        try:
            for name, count in self.lib.categories(self.KIND):
                self._category.addItem(f"{name} ({count})", name)
        except Exception as exc:  # noqa: BLE001
            log.debug("catégories indisponibles : %s", exc)
        index = self._category.findData(current)
        self._category.setCurrentIndex(max(0, index))
        self._category.blockSignals(False)
