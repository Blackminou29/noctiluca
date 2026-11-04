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
from ...i18n import N_, tr
from ..theme import PAD, category_color
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
from .base import Page, avance, tool_button

log = logging.getLogger(__name__)


def _categorie(valeur) -> str:
    """Une catégorie de l'index, dans la langue de l'interface : « Autre »
    devient « Other », « Bass » reste « Bass »."""
    return "—" if valeur is None else tr(str(valeur))


def _pastille(categorie) -> str:
    """Couleur de la pastille d'une catégorie, rien si elle est vide."""
    texte = str(categorie or "").strip()
    return category_color(texte) if texte else ""


#: Paramètres montrés en encodeurs, dans cet ordre.
KNOB_PARAMS: tuple[tuple[str, str, bool], ...] = (
    ("volume", N_("Volume"), False),
    ("lpfFrequency", N_("Coupure"), False),
    ("lpfResonance", N_("Résonance"), False),
    ("oscAVolume", N_("Osc A"), False),
    ("oscBVolume", N_("Osc B"), False),
    ("reverbAmount", N_("Réverb."), False),
    ("delayFeedback", N_("Délai"), False),
    ("modFXDepth", N_("Mod FX"), False),
    ("pan", N_("Panoramique"), True),
)


class SynthsPage(Page):
    """Presets de synthé."""

    TITLE = N_("Presets")
    EMPTY_DETAIL = N_("Indiquez l'emplacement de votre carte dans les "
                      "réglages. Chaque preset s'ouvrira ici avec ses "
                      "oscillateurs, ses enveloppes et son filtre, expliqués "
                      "en français.")
    ICON = "synth"
    #: ``'synth'`` ou ``'kit'`` : la page des kits réutilise cette classe.
    KIND = "synth"

    #: Un preset a été choisi.
    presetChosen = pyqtSignal(str)
    #: Demande d'ouvrir ce preset dans le générateur, pour le faire varier.
    openInGenerator = pyqtSignal(str)
    #: Le preset choisi, pour le morceau de l'atelier : ``{"preset", "part"}``.
    toAtelier = pyqtSignal(object)

    def __init__(self, ctx, parent=None) -> None:
        super().__init__(ctx, parent)
        self._model: RowTableModel | None = None
        self._proxy = None
        self._preset = None
        self._current = ""
        self._current_category = ""
        self._audio = None

    # -- construction ------------------------------------------------------- #

    def build(self) -> None:
        outer = QVBoxLayout(self.content())
        outer.setContentsMargins(PAD, PAD, PAD, PAD)
        outer.setSpacing(8)

        header, actions = self.header(
            tr("Presets de synthé"),
            tr("Parcourir, écouter et comprendre les sons de la carte"))
        outer.addWidget(header)

        listen = tool_button(tr("Écouter"), "play", primary=True)
        listen.clicked.connect(self.guard(self._listen))
        actions.addWidget(listen)

        stop = tool_button(tr("Arrêter"), "stop")
        stop.clicked.connect(self.guard(self._stop))
        actions.addWidget(stop)

        self._use_button = tool_button(tr("Utiliser dans l'atelier"),
                                       "atelier")
        self._use_button.clicked.connect(self.guard(self._use_in_atelier))
        actions.addWidget(self._use_button)

        vary = tool_button(tr("Varier dans le générateur"), "wand")
        vary.clicked.connect(self.guard(self._vary))
        actions.addWidget(vary)

        duplicate = avance(tool_button(tr("Dupliquer"), "copy",
                                       tr("Enregistrer une copie à côté de "
                                          "l'original")))
        duplicate.clicked.connect(self.guard(self._duplicate))
        actions.addWidget(duplicate)

        row = QHBoxLayout()
        row.setSpacing(6)
        self._search = SearchBar(tr("Rechercher un preset…"))
        self._search.searchChanged.connect(self.guard(lambda _t: self._reload()))
        row.addWidget(self._search, 2)
        self._category = QComboBox()
        self._category.addItem(tr("Toutes catégories"), "")
        self._category.activated.connect(self.guard(lambda _i: self._reload()))
        row.addWidget(self._category, 1)
        holder = QWidget()
        holder.setLayout(row)
        outer.addWidget(holder)

        splitter = QSplitter(Qt.Orientation.Horizontal, self.content())
        splitter.addWidget(self._build_table())
        splitter.addWidget(self._build_detail())
        # ``setSizes`` est une **proportion** : Qt normalise les deux
        # nombres à la largeur disponible. Donner [620, 820] sur une
        # zone de 1 210 px rendait 521 px, pas 620 — d'où des colonnes
        # écrasées. Les nombres ci-dessous valent pour une zone de
        # 1 210 px (fenêtre de 1 440).
        splitter.setSizes([640, 570])
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
        tabs.addTab(self._build_summary_tab(), tr("Vue d'ensemble"))
        # Les réglages un à un et les câbles de modulation : le détail du
        # son, pour qui veut le lire comme la machine l'écrit.
        tabs.addTab(avance(self._build_params_tab()), tr("Paramètres"))
        tabs.addTab(avance(self._build_mod_tab()), tr("Modulations"))
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

        self._name = ElidedLabel(tr("Aucun preset sélectionné"))
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
        # Le message par défaut renvoie à « la liste » des échantillons : ici
        # la liste est celle des sons que **ce preset** utilise, plus bas
        # dans le même panneau.
        self._wave.set_empty_text(
            tr("Aucun échantillon affiché"),
            tr("Choisissez une ligne dans « Échantillons utilisés », en bas"))
        column.addWidget(self._wave)

        self._spectrum = SpectrumView()
        self._spectrum.setMinimumHeight(90)
        self._spectrum.set_empty_text(
            tr("Aucun signal analysé\n\n"
               "Écoutez le preset pour voir son spectre"))
        column.addWidget(self._spectrum)

        samples_label = QLabel(tr("Échantillons utilisés"))
        samples_label.setProperty("role", "subtitle")
        column.addWidget(samples_label)
        self._samples = QTableWidget(0, 2)
        self._samples.setHorizontalHeaderLabels([tr("Fichier"),
                                                 tr("Présent")])
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

        knobs = Card(tr("Principaux réglages"))
        grid = QGridLayout()
        grid.setSpacing(6)
        self._knobs: dict[str, Knob] = {}
        for index, (key, label, bipolar) in enumerate(KNOB_PARAMS):
            knob = Knob(tr(label), 25, -25 if bipolar else 0,
                        25 if bipolar else 50, bipolar)
            knob.setEnabled(False)      # lecture seule : l'édition viendra
            grid.addWidget(knob, index // 5, index % 5)
            self._knobs[key] = knob
        knobs.body().addLayout(grid)
        column.addWidget(knobs)

        envelopes = Card(tr("Enveloppes"))
        self._env1 = EnvelopeEditor(title=tr("Enveloppe 1 — amplitude"))
        self._env2 = EnvelopeEditor(title=tr("Enveloppe 2 — modulation"))
        envelopes.body().addWidget(self._env1)
        envelopes.body().addWidget(self._env2)
        column.addWidget(envelopes)

        filtre = Card(tr("Filtre"))
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

        cables_label = QLabel(tr("Câbles de modulation"))
        cables_label.setProperty("role", "subtitle")
        column.addWidget(cables_label)

        self._cables = QTableWidget(0, 3)
        self._cables.setHorizontalHeaderLabels(
            [tr("Source"), tr("Destination"), tr("Profondeur")])
        self._cables.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self._cables.verticalHeader().setVisible(False)
        self._cables.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        column.addWidget(self._cables, 1)

        knobs_label = QLabel(tr("Encodeurs assignés (modKnobs)"))
        knobs_label.setProperty("role", "subtitle")
        column.addWidget(knobs_label)

        self._modknobs = QTableWidget(0, 2)
        self._modknobs.setHorizontalHeaderLabels([tr("Paramètre"),
                                                  tr("Source")])
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

        def dossier(row):
            """Dernier segment du chemin : « Mellotron », pas « SYNTHS/... »."""
            brut = str(row["folder"] if "folder" in row.keys() else "")
            parts = [p for p in brut.replace("\\", "/").split("/") if p]
            return parts[-1] if parts else ""

        # Cinq colonnes au lieu de neuf. « Osc 1 », « Filtre » et
        # « Effets » sont repris mot pour mot dans le panneau de droite pour
        # le preset choisi ; en liste, ils poussaient le nom et le dossier
        # sous une barre de défilement horizontale. Le firmware n'aide pas à
        # choisir un son — la page Santé signale ce qu'il faut savoir.
        return [
            (tr("Nom"), get("name"), 200, left),
            (tr("Dossier"), dossier, 150, left),
            (tr("Catégorie"), get("category"), 108, left, _categorie,
             _pastille),
            (tr("Moteur"), get("mode"), 85, left),
            (tr("Taille"), get("size"), 80, right, human_size),
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
            # C'est le **nom** qui absorbe la place libre, pas le dossier :
            # une colonne étirée reçoit ce qui reste, et « Dossier » se
            # retrouvait écrasé à trente pixels dès que le panneau était un
            # peu serré.
            self._table.horizontalHeader().setSectionResizeMode(
                0, QHeaderView.ResizeMode.Stretch)
            selection = self._table.selectionModel()
            if selection is not None:
                selection.selectionChanged.connect(
                    self.guard(lambda *_a: self._on_selected()))
        else:
            self._model.set_rows(rows)

        self._count.setText(
            (tr("%d preset(s) affiché(s)") if self.KIND == "synth"
             else tr("%d kit(s) affiché(s)")) % len(rows))

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
        self._current_category = (row["category"] or "") \
            if "category" in row.keys() else ""
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
            self._description.setText(tr("Fichier illisible : %s") % exc)
            self._info.set_rows([(tr("Erreur"), str(exc))])
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
            (tr("Moteur"), sound.mode),
            (tr("Polyphonie"), sound.polyphonic),
            (tr("Oscillateur 1"), sound.osc_label(sound.osc1)),
            (tr("Oscillateur 2"), sound.osc_label(sound.osc2)),
            (tr("Filtre"), sound.filter_label()),
            (tr("Effets"), ", ".join(sound.fx_list()) or tr("aucun")),
            (tr("Unisson"), tr("%d voix, désaccord %d")
             % (sound.unison_num, sound.unison_detune)),
            (tr("Arpégiateur"),
             sound.arp.mode if sound.arp.is_on else tr("éteint")),
            (tr("Catégorie devinée"), tr(sound.category_guess())),
            (tr("Caractère"), ", ".join(sound.tonal_tags()) or "—"),
            (tr("Firmware"), sound.firmware or "—"),
        ]
        repaired = row["repaired"] if "repaired" in row.keys() else ""
        if repaired:
            details.append((tr("Réparations à la lecture"), repaired))
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
            state = QTableWidgetItem(tr("oui") if present else tr("ABSENT"))
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
            self.say(tr("Aucun preset sélectionné."))
            return
        if self.audition(self._preset.sound):
            return
        self.say(tr("Rendu du son…"))
        self.run(self._render, self._preset,
                 on_result=self.guard(self._play_rendered),
                 on_error=self.guard(
                     lambda m: self.say(tr("Rendu impossible : %s") % m)),
                 title=tr("Rendu du preset"))

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
            self.say(tr("Aucune sortie audio disponible."))
            return
        try:
            self.player.set_volume(self.ctx.settings.preview_volume)
            self.player.play_array(audio, 44100)
            self.say(tr("Lecture…"))
        except Exception as exc:  # noqa: BLE001
            log.debug("lecture impossible : %s", exc)
            self.say(tr("Lecture impossible : %s") % exc)

    def _stop(self) -> None:
        if self.player is not None:
            try:
                self.player.stop()
            except Exception as exc:  # noqa: BLE001
                log.debug("arrêt impossible : %s", exc)

    # -- vers l'atelier et le générateur ------------------------------------- #

    def _use_in_atelier(self) -> None:
        """Le preset choisi rejoint le morceau de l'atelier, à la piste de sa
        catégorie — une basse à la basse, une nappe aux accords. Rien n'est
        écrit : l'original reste tel quel sur la carte."""
        if self._preset is None or not self._current:
            self.say(tr("Choisissez d'abord un preset."))
            return
        import copy

        self.toAtelier.emit({"preset": copy.deepcopy(self._preset),
                             "part": self._current_category})

    def _vary(self) -> None:
        """Ouvre le preset choisi dans le générateur."""
        if self._preset is None or not self._current:
            self.say(tr("Choisissez d'abord un preset."))
            return
        self.openInGenerator.emit(self._current)

    # -- duplication -------------------------------------------------------- #

    def _duplicate(self) -> None:
        """Enregistre une copie du preset à côté de l'original."""
        if self._preset is None or not self._current:
            self.say(tr("Aucun preset sélectionné."))
            return
        card = self.writable_card()
        if card is None:
            return

        from ...core.sdcard import safe_deluge_name

        source = card.abs(self._current)
        stem = safe_deluge_name(tr("%s copie") % source.stem)
        target = source.with_name(f"{stem}{source.suffix}")
        index = 2
        while target.exists():
            target = source.with_name(f"{stem} {index}{source.suffix}")
            index += 1

        if self.ctx.settings.confirm_writes:
            answer = QMessageBox.question(
                self, tr("Dupliquer le preset"),
                tr("Créer « %s » dans %s ?")
                % (target.name, target.parent.name),
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
            self.say(tr("Duplication impossible : %s") % exc)
            return
        card.invalidate_cache()
        _index_written(self, [target])
        self.say(tr("Copie créée : %s") % target.name)
        self._refresh()

    # -- rafraîchissement --------------------------------------------------- #

    def _refresh(self) -> None:
        self._fill_categories()
        self._reload()

    def _fill_categories(self) -> None:
        current = self._category.currentData() or ""
        self._category.blockSignals(True)
        self._category.clear()
        self._category.addItem(tr("Toutes catégories"), "")
        try:
            for name, count in self.lib.categories(self.KIND):
                self._category.addItem(f"{tr(name)} ({count})", name)
        except Exception as exc:  # noqa: BLE001
            log.debug("catégories indisponibles : %s", exc)
        index = self._category.findData(current)
        self._category.setCurrentIndex(max(0, index))
        self._category.blockSignals(False)


def _index_written(page, paths) -> None:
    """Ajoute à l'index ce qu'on vient d'écrire, pour que les listes le montrent."""
    try:
        from ...core.scan import index_presets
        index_presets(page.sd, page.lib, list(paths))
    except Exception:  # noqa: BLE001 - l'index se rattrapera à l'analyse
        log.exception("indexation immédiate impossible")
