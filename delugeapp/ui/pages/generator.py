# -*- coding: utf-8 -*-
"""Page « Générateur ».

Le cœur créatif : fabriquer des presets de synthé par genre musical ou au
hasard, les écouter, les faire varier, et enregistrer ceux qu'on garde dans
``SYNTHS/``.

Trois colonnes : les réglages à gauche, le son obtenu au centre, la file des
variations à droite. Tout rendu audio part dans un fil séparé.

La graine est affichée et modifiable : c'est elle qui rend un son
reproductible. Noter une graine suffit à retrouver exactement le même preset.
"""

from __future__ import annotations

import logging
import random

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...core import genres as genres_mod
from ...core.fixedpoint import to_display
from ..theme import PAD
from ..widgets.common import (Card, ElidedLabel, SectionTitle,
                              hint_in_list)
from ..widgets.envelope import EnvelopeEditor
from ..widgets.filtercurve import FilterCurve, SpectrumView
from ..widgets.knob import Knob
from ..widgets.waveform import WaveformView
from .base import Page, tool_button

log = logging.getLogger(__name__)

#: Curseurs macro, dans l'ordre d'affichage.
MACROS: tuple[tuple[str, str, str], ...] = (
    ("brightness", "Brillance", "Ouvre ou ferme le filtre"),
    ("movement", "Mouvement", "Intensité des LFO et de l'enveloppe de "
                              "modulation"),
    ("space", "Espace", "Réverbération et délai"),
    ("dirt", "Saleté", "Distorsion, résonance, réduction numérique"),
    ("width", "Largeur", "Unisson, désaccord, chorus"),
    ("complexity", "Complexité", "Nombre de modulations"),
)

#: Nombre de variations produites d'un coup.
VARIATION_COUNT = 8


class GeneratorPage(Page):
    """Générateur de presets et de kits."""

    TITLE = "Générateur"
    EMPTY_DETAIL = ("Indiquez l'emplacement de votre carte dans les réglages. "
                    "Le générateur fabriquera alors des presets et des "
                    "kits prêts à être enregistrés dessus.")
    ICON = "wand"
    #: Le générateur fonctionne sans carte : seul l'enregistrement en a besoin.
    NEEDS_CARD = False

    #: Un preset vient d'être enregistré sur la carte.
    presetSaved = pyqtSignal(str)

    def __init__(self, ctx, parent=None) -> None:
        super().__init__(ctx, parent)
        self._preset = None
        self._variations: list = []
        self._history: list = []
        self._audio = None
        self._macros: dict[str, QSlider] = {}

    # -- construction ------------------------------------------------------- #

    def build(self) -> None:
        outer = QVBoxLayout(self.content())
        outer.setContentsMargins(PAD, PAD, PAD, PAD)
        outer.setSpacing(8)

        header, actions = self.header(
            "Générateur", "Fabriquer un son par genre, ou au hasard")
        outer.addWidget(header)

        generate = tool_button("Générer", "wand", primary=True)
        generate.clicked.connect(self.guard(self._generate))
        actions.addWidget(generate)

        randomize = tool_button("Au hasard", "dice",
                                "Genre, rôle et réglages tirés au sort")
        randomize.clicked.connect(self.guard(self._randomize))
        actions.addWidget(randomize)

        mutate = tool_button("Muter", "refresh",
                             "Variante légère du son courant")
        mutate.clicked.connect(self.guard(self._mutate))
        actions.addWidget(mutate)

        listen = tool_button("Écouter", "play")
        listen.clicked.connect(self.guard(self._listen))
        actions.addWidget(listen)

        save = tool_button("Enregistrer dans SYNTHS", "save")
        save.clicked.connect(self.guard(self._save))
        actions.addWidget(save)

        song = tool_button("Essayer en morceau", "song")
        song.clicked.connect(self.guard(self._song_from_preset))
        actions.addWidget(song)

        tabs = QTabWidget()
        tabs.addTab(self._build_synth_tab(), "Preset de synthé")
        tabs.addTab(self._build_kit_tab(), "Kit de batterie")
        outer.addWidget(tabs, 1)

    def _build_synth_tab(self) -> QWidget:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_controls())
        splitter.addWidget(self._build_preview())
        splitter.addWidget(self._build_variations())
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 4)
        splitter.setStretchFactor(2, 1)
        # La colonne des genres porte deux pads par rangée : sans largeur
        # minimale, le splitter la comprime et les libellés sont coupés
        # (« Boards of Ca… », « Drum and ba… »).
        splitter.setSizes([330, 700, 320])
        return splitter

    def _build_controls(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        inner = QWidget()
        column = QVBoxLayout(inner)
        column.setContentsMargins(0, 0, PAD, 0)
        column.setSpacing(PAD)

        # -- genre
        genre_card = Card("Genre")
        self._genre_grid = QGridLayout()
        self._genre_grid.setSpacing(4)
        self._genre_buttons: dict[str, QWidget] = {}
        keys = genres_mod.genre_keys()
        for index, key in enumerate(keys):
            profile = genres_mod.genre(key)
            button = tool_button(profile.label, "", color=profile.color)
            button.setCheckable(True)
            button.setMinimumWidth(96)
            button.setSizePolicy(QSizePolicy.Policy.Expanding,
                                 QSizePolicy.Policy.Fixed)
            button.setToolTip(
                f"{profile.description}\n\n"
                f"{profile.bpm[0]}–{profile.bpm[1]} BPM")
            button.clicked.connect(
                self.guard(lambda _c=False, k=key: self._pick_genre(k)))
            self._genre_grid.addWidget(button, index // 2, index % 2)
            self._genre_buttons[key] = button
        genre_card.body().addLayout(self._genre_grid)

        self._genre_hint = QLabel("")
        self._genre_hint.setProperty("role", "subtitle")
        self._genre_hint.setWordWrap(True)
        genre_card.body().addWidget(self._genre_hint)
        column.addWidget(genre_card)

        # -- rôle et mode
        role_card = Card("Rôle et moteur")
        grid = QGridLayout()
        grid.setSpacing(6)

        grid.addWidget(QLabel("Rôle"), 0, 0)
        self._role = QComboBox()
        for role in genres_mod.ROLES:
            self._role.addItem(genres_mod.role_label(role), role)
        grid.addWidget(self._role, 0, 1)

        grid.addWidget(QLabel("Moteur"), 1, 0)
        self._mode = QComboBox()
        self._mode.addItem("Choisi par le genre", "")
        for mode, label in (("subtractive", "Soustractive"), ("fm", "FM"),
                            ("ringmod", "Ring mod")):
            self._mode.addItem(label, mode)
        grid.addWidget(self._mode, 1, 1)

        grid.addWidget(QLabel("Graine"), 2, 0)
        seed_row = QHBoxLayout()
        self._seed = QSpinBox()
        self._seed.setRange(0, 1 << 30)
        self._seed.setToolTip(
            "Deux générations avec la même graine donnent exactement le "
            "même son. Notez-la pour retrouver un preset.")
        seed_row.addWidget(self._seed, 1)
        dice = tool_button("", "dice", "Nouvelle graine au hasard")
        dice.setFixedWidth(34)
        dice.clicked.connect(self.guard(self._roll_seed))
        seed_row.addWidget(dice)
        holder = QWidget()
        holder.setLayout(seed_row)
        grid.addWidget(holder, 2, 1)
        role_card.body().addLayout(grid)
        column.addWidget(role_card)

        # -- curseurs macro
        macro_card = Card("Réglages")
        for key, label, tip in MACROS:
            row = QHBoxLayout()
            name = QLabel(label)
            name.setFixedWidth(88)
            name.setToolTip(tip)
            row.addWidget(name)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, 100)
            slider.setValue(50)
            slider.setToolTip(tip)
            row.addWidget(slider, 1)
            value = QLabel("50")
            value.setFixedWidth(28)
            value.setProperty("role", "subtitle")
            slider.valueChanged.connect(
                lambda v, lbl=value: lbl.setText(str(v)))
            row.addWidget(value)
            macro_card.body().addLayout(row)
            self._macros[key] = slider
        column.addWidget(macro_card)
        column.addStretch(1)

        scroll.setWidget(inner)
        return scroll

    def _build_preview(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        inner = QWidget()
        column = QVBoxLayout(inner)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(8)

        head = Card("")
        self._name = ElidedLabel("Aucun son généré")
        self._name.setProperty("role", "title")
        head.body().addWidget(self._name)
        self._description = QLabel(
            "Choisissez un genre et un rôle, puis cliquez « Générer ».")
        self._description.setWordWrap(True)
        head.body().addWidget(self._description)
        column.addWidget(head)

        sound = Card("Le son")
        self._wave = WaveformView()
        self._wave.setMinimumHeight(80)
        # Les deux cadres annonçaient « choisissez-en un dans la liste » et
        # « écoutez un échantillon » : il n'y a ici ni liste ni échantillon,
        # le son se fabrique. Un message d'attente qui parle d'autre chose
        # fait douter d'être au bon endroit.
        self._wave.set_empty_text(
            "Aucun son généré",
            "Choisissez un genre, puis cliquez « Générer »")
        sound.body().addWidget(self._wave)
        self._spectrum = SpectrumView()
        self._spectrum.setMinimumHeight(90)
        self._spectrum.set_empty_text(
            "Le spectre du son apparaîtra ici")
        sound.body().addWidget(self._spectrum)
        column.addWidget(sound)

        knobs = Card("Réglages obtenus")
        grid = QGridLayout()
        grid.setSpacing(6)
        self._knobs: dict[str, Knob] = {}
        for index, (key, label, bipolar) in enumerate((
                ("volume", "Volume", False),
                ("lpfFrequency", "Coupure", False),
                ("lpfResonance", "Résonance", False),
                ("oscAVolume", "Osc A", False),
                ("oscBVolume", "Osc B", False),
                ("reverbAmount", "Réverb.", False),
                ("delayFeedback", "Délai", False),
                ("modFXDepth", "Mod FX", False))):
            knob = Knob(label, 25, -25 if bipolar else 0,
                        25 if bipolar else 50, bipolar)
            knob.setEnabled(False)
            grid.addWidget(knob, index // 4, index % 4)
            self._knobs[key] = knob
        knobs.body().addLayout(grid)
        column.addWidget(knobs)

        shape = Card("Enveloppes et filtre")
        self._env1 = EnvelopeEditor(title="Enveloppe 1 — amplitude")
        shape.body().addWidget(self._env1)
        self._filter = FilterCurve()
        shape.body().addWidget(self._filter)
        column.addWidget(shape)
        column.addStretch(1)

        scroll.setWidget(inner)
        return scroll

    def _build_variations(self) -> QWidget:
        card = Card("Variations")
        body = card.body()

        hint = QLabel("Cliquez pour écouter, double-cliquez pour adopter.")
        hint.setProperty("role", "subtitle")
        hint.setWordWrap(True)
        body.addWidget(hint)

        make = tool_button("Produire 8 variantes", "copy")
        make.clicked.connect(self.guard(self._make_variations))
        body.addWidget(make)

        self._variation_list = QListWidget()
        # Les listes élident au lieu de pousser une barre de défilement
        # horizontale sous un panneau de trois cents pixels.
        self._variation_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        hint_in_list(self._variation_list,
                     "  Aucune variante pour l'instant.")
        self._variation_list.currentRowChanged.connect(
            self.guard(self._preview_variation))
        self._variation_list.itemDoubleClicked.connect(
            self.guard(lambda _i: self._adopt_variation()))
        body.addWidget(self._variation_list, 1)

        batch = tool_button("Générer un lot dans un dossier…", "export")
        batch.clicked.connect(self.guard(self._generate_batch))
        body.addWidget(batch)

        body.addWidget(SectionTitle("Historique"))
        self._history_list = QListWidget()
        self._history_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        hint_in_list(self._history_list,
                     "  Les sons générés s'empileront ici.")
        self._history_list.itemDoubleClicked.connect(
            self.guard(lambda _i: self._restore_history()))
        body.addWidget(self._history_list, 1)

        # Fondre le son courant avec un son de l'historique : les réglages
        # continus se mélangent, les choix (formes d'onde, moteur) basculent
        # à mi-chemin.
        morph_row = QHBoxLayout()
        self._morph_amount = QSlider(Qt.Orientation.Horizontal)
        self._morph_amount.setRange(0, 100)
        self._morph_amount.setValue(50)
        morph_row.addWidget(self._morph_amount, 1)
        morph = tool_button("Fondre", "refresh")
        morph.clicked.connect(self.guard(self._morph))
        morph_row.addWidget(morph)
        body.addLayout(morph_row)
        return card

    def _build_kit_tab(self) -> QWidget:
        host = QWidget()
        column = QVBoxLayout(host)
        column.setContentsMargins(PAD, PAD, PAD, PAD)
        column.setSpacing(PAD)

        card = Card("Construire un kit depuis la bibliothèque")
        body = card.body()

        hint = QLabel(
            "Le kit se construit autour d'une machine ou d'une banque de "
            "votre bibliothèque (909, Linndrum, un kit d'artiste…), choisie "
            "selon le genre ; les rôles qu'elle n'a pas sont complétés "
            "ailleurs. Chaque rangée est réglée comme le Deluge la crée : "
            "l'échantillon joué jusqu'au bout et sensible à la vélocité ; "
            "volume et panoramique suivent les kits de la carte, toms en "
            "éventail. Une rangée ne vous plaît pas ? Choisissez-la, puis "
            "« Autre son ».")
        hint.setProperty("role", "subtitle")
        hint.setWordWrap(True)
        body.addWidget(hint)

        grid = QGridLayout()
        grid.setSpacing(6)
        grid.addWidget(QLabel("Genre"), 0, 0)
        self._kit_genre = QComboBox()
        for key in genres_mod.genre_keys():
            self._kit_genre.addItem(genres_mod.genre(key).label, key)
        grid.addWidget(self._kit_genre, 0, 1)

        grid.addWidget(QLabel("Nom du kit"), 1, 0)
        self._kit_name = QLineEdit("MON KIT")
        grid.addWidget(self._kit_name, 1, 1)

        grid.addWidget(QLabel("Graine"), 2, 0)
        self._kit_seed = QSpinBox()
        self._kit_seed.setRange(0, 1 << 30)
        grid.addWidget(self._kit_seed, 2, 1)

        grid.addWidget(QLabel("Dossier à privilégier"), 3, 0)
        self._kit_folder = QLineEdit()
        self._kit_folder.setPlaceholderText(
            "facultatif — ex. SAMPLES/Artists/…")
        grid.addWidget(self._kit_folder, 3, 1)
        body.addLayout(grid)

        row = QHBoxLayout()
        build = tool_button("Construire le kit", "kit", primary=True)
        build.clicked.connect(self.guard(self._build_kit))
        row.addWidget(build)
        listen = tool_button("Écouter", "play")
        listen.clicked.connect(self.guard(self._listen_kit))
        row.addWidget(listen)
        self._reroll_button = tool_button("Autre son", "dice")
        self._reroll_button.clicked.connect(self.guard(self._reroll_kit_row))
        row.addWidget(self._reroll_button)
        save = tool_button("Enregistrer dans KITS", "save")
        save.clicked.connect(self.guard(self._save_kit))
        row.addWidget(save)
        kit_song = tool_button("Kit en morceau", "song")
        kit_song.clicked.connect(self.guard(self._song_from_kit))
        row.addWidget(kit_song)
        row.addStretch(1)
        body.addLayout(row)

        self._kit_result = QListWidget()
        body.addWidget(self._kit_result, 1)
        column.addWidget(card, 1)
        self._kit = None
        #: Échantillons déjà essayés, par rangée, pour « Autre son ».
        self._kit_tried: dict[int, set] = {}
        self._kit_rolls = 0
        return host

    # -- réglages ----------------------------------------------------------- #

    def _pick_genre(self, key: str) -> None:
        for name, button in self._genre_buttons.items():
            button.setChecked(name == key)
        profile = genres_mod.genre(key)
        self._genre_hint.setText(
            f"{profile.description}  ({profile.bpm[0]}–{profile.bpm[1]} BPM)")

    def _current_genre(self) -> str:
        for key, button in self._genre_buttons.items():
            if button.isChecked():
                return key
        return "techno"

    def _roll_seed(self) -> None:
        self._seed.setValue(random.randrange(1 << 30))

    def _options(self):
        from ...core.synthgen import GenOptions

        return GenOptions(
            genre=self._current_genre(),
            role=self._role.currentData() or "bass",
            seed=int(self._seed.value()),
            mode=self._mode.currentData() or "",
            **{key: slider.value() / 100.0
               for key, slider in self._macros.items()})

    # -- génération --------------------------------------------------------- #

    def _generate(self) -> None:
        from ...core import synthgen

        self._show_preset(synthgen.generate(self._options()))
        self.say(f"Preset généré : {self._preset.sound.name}")

    def _randomize(self) -> None:
        from ...core import synthgen

        seed = random.randrange(1 << 30)
        self._seed.setValue(seed)
        preset = synthgen.randomize(seed=seed)
        self._show_preset(preset)
        self.say(f"Son au hasard : {preset.sound.name}")

    def _mutate(self) -> None:
        if self._preset is None:
            self.say("Générez d'abord un son.")
            return
        from ...core import synthgen

        self._show_preset(synthgen.mutate(self._preset, amount=0.3))
        self.say(f"Variante : {self._preset.sound.name}")

    def start_from(self, preset) -> None:
        """Prend un preset existant comme point de départ.

        C'est la porte d'entrée depuis la page Presets : le son de la carte
        devient le son courant, que « Muter » et « Produire 8 variantes »
        font évoluer. L'original n'est jamais réécrit : « Enregistrer » en
        fait une copie, sous le nom que vous choisirez.
        """
        self._show_preset(preset)
        self.say(f"Point de départ : {preset.sound.name}. « Muter » ou "
                 f"« Produire 8 variantes » partent de lui.")

    def _show_preset(self, preset) -> None:
        """Affiche un preset et le place dans l'historique."""
        from ...core import synthgen

        self._preset = preset
        sound = preset.sound
        self._name.setText(sound.name)
        try:
            self._description.setText(synthgen.describe(preset))
        except Exception as exc:  # noqa: BLE001
            log.debug("description impossible : %s", exc)

        for key, knob in self._knobs.items():
            try:
                knob.set_value(sound.display(key))
            except Exception:  # noqa: BLE001
                knob.set_value(0)

        self._env1.set_adsr(to_display(sound.env1.attack),
                            to_display(sound.env1.decay),
                            to_display(sound.env1.sustain),
                            to_display(sound.env1.release))
        self._filter.set_filter(sound.display("lpfFrequency"),
                                sound.display("lpfResonance"),
                                sound.lpf_mode)

        self._history.insert(0, preset)
        del self._history[24:]
        self._history_list.clear()
        for item in self._history:
            self._history_list.addItem(item.sound.name)
        hint_in_list(self._history_list,
                     "  Les sons générés s'empileront ici.")

        self._render_async(preset)

    # -- écoute ------------------------------------------------------------- #

    def _render_async(self, preset) -> None:
        self.run(self._render, preset,
                 on_result=self.guard(self._rendered),
                 on_error=self.guard(
                     lambda m: self.say(f"Rendu impossible : {m}")),
                 title="Rendu du son")

    def _render(self, preset):
        from ...core import render

        return render.render_preview(preset, sr=44100, sd=self.sd)

    def _rendered(self, audio) -> None:
        if audio is None:
            return
        self._audio = audio
        try:
            self._spectrum.set_audio(audio, 44100)
        except Exception as exc:  # noqa: BLE001
            log.debug("spectre impossible : %s", exc)
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
            log.debug("enveloppe impossible : %s", exc)

        if self.ctx.settings.autoplay:
            self._play(audio)

    def _listen(self) -> None:
        if self._preset is None:
            self.say("Générez d'abord un son.")
            return
        # La machine d'abord, quand elle est là : elle sonne juste, et le
        # rendu approché n'a plus d'intérêt.
        if self.audition(self._preset.sound):
            return
        if self._audio is not None:
            self._play(self._audio)
        else:
            self._render_async(self._preset)

    def _play(self, audio) -> None:
        if self.player is None:
            self.say("Aucune sortie audio disponible.")
            return
        try:
            self.player.set_volume(self.ctx.settings.preview_volume)
            self.player.play_array(audio, 44100)
        except Exception as exc:  # noqa: BLE001
            log.debug("lecture impossible : %s", exc)
            self.say(f"Lecture impossible : {exc}")

    # -- variations --------------------------------------------------------- #

    def _make_variations(self) -> None:
        if self._preset is None:
            self.say("Générez d'abord un son.")
            return
        from ...core import synthgen

        self._variations = synthgen.variations(
            self._preset, n=VARIATION_COUNT, amount=0.3,
            seed=int(self._seed.value()))
        self._variation_list.clear()
        for index, variant in enumerate(self._variations, 1):
            item = QListWidgetItem(f"{index}.  {variant.sound.name}")
            item.setToolTip(synthgen.describe(variant))
            self._variation_list.addItem(item)
        hint_in_list(self._variation_list,
                     "  Aucune variante pour l'instant.")
        self.say(f"{len(self._variations)} variantes produites.")

    def _preview_variation(self, row: int) -> None:
        if not 0 <= row < len(self._variations):
            return
        self._render_async(self._variations[row])

    def _adopt_variation(self) -> None:
        row = self._variation_list.currentRow()
        if not 0 <= row < len(self._variations):
            return
        self._show_preset(self._variations[row])
        self.say(f"Variante adoptée : {self._preset.sound.name}")

    def _morph(self) -> None:
        """Fond le son courant avec le son choisi dans l'historique."""
        row = self._history_list.currentRow()
        if self._preset is None or not 0 <= row < len(self._history):
            self.say("Choisissez dans l'historique le son avec lequel "
                     "fondre le son courant.")
            return
        autre = self._history[row]
        if autre is self._preset:
            self.say("Choisissez un autre son que le son courant.")
            return
        from ...core import synthgen

        dosage = self._morph_amount.value() / 100.0
        mixte = synthgen.morph(self._preset, autre, dosage)
        self._show_preset(mixte)
        self.say(f"Fondu à {self._morph_amount.value()} % vers "
                 f"{autre.sound.name} : {mixte.sound.name}")

    def _restore_history(self) -> None:
        row = self._history_list.currentRow()
        if not 0 <= row < len(self._history):
            return
        self._show_preset(self._history[row])

    # -- enregistrement ----------------------------------------------------- #

    def _save(self) -> None:
        """Enregistre le preset courant dans ``SYNTHS/``."""
        if self._preset is None:
            self.say("Générez d'abord un son.")
            return
        card = self.writable_card()
        if card is None:
            return

        from ...core.sdcard import check_name, safe_deluge_name

        name, ok = QInputDialog.getText(
            self, "Enregistrer le preset",
            "Nom du preset (il sera assaini pour la carte) :",
            QLineEdit.EchoMode.Normal, self._preset.sound.name)
        if not ok or not name.strip():
            return

        folder, ok = QInputDialog.getText(
            self, "Dossier de destination",
            "Sous-dossier de SYNTHS (vide = racine de SYNTHS) :",
            QLineEdit.EchoMode.Normal, "Generes")
        if not ok:
            return

        clean = safe_deluge_name(name)
        problems = check_name(clean)
        if problems:
            QMessageBox.warning(self, "Nom refusé", "\n".join(problems))
            return

        parts = ["SYNTHS"] + [safe_deluge_name(p)
                              for p in folder.split("/") if p.strip()]
        target = card.abs("/".join(parts)) / f"{clean}.XML"
        if target.exists():
            answer = QMessageBox.question(
                self, "Le fichier existe",
                f"« {target.name} » existe déjà. Le remplacer ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            self._preset.sound.name = clean
            self._preset.save(
                target,
                backup=self.ctx.settings.always_backup_before_write)
        except Exception as exc:  # noqa: BLE001
            log.exception("enregistrement impossible")
            self.say(f"Enregistrement impossible : {exc}")
            return

        card.invalidate_cache()
        _index_written(self, [target])
        rel = card.rel(target)
        self.say(f"Preset enregistré : {rel}")
        self.presetSaved.emit(rel)

    def _generate_batch(self) -> None:
        """Produit plusieurs presets d'un coup dans un nouveau dossier."""
        card = self.writable_card()
        if card is None:
            return
        count, ok = QInputDialog.getInt(
            self, "Générer un lot",
            "Combien de presets produire ?", 8, 1, 64)
        if not ok:
            return
        folder, ok = QInputDialog.getText(
            self, "Dossier de destination",
            "Sous-dossier de SYNTHS :", QLineEdit.EchoMode.Normal,
            f"Lot {self._current_genre()}")
        if not ok or not folder.strip():
            return

        from ...core.sdcard import safe_deluge_name
        from ...core import synthgen

        target_dir = card.abs(f"SYNTHS/{safe_deluge_name(folder)}")
        base = int(self._seed.value())
        written, failed = 0, []
        chemins: list = []
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.say(f"Dossier impossible : {exc}")
            return

        for index in range(int(count)):
            options = self._options()
            options.seed = base + index
            try:
                preset = synthgen.generate(options)
                name = safe_deluge_name(preset.sound.name)
                path = target_dir / f"{name}.XML"
                suffix = 2
                while path.exists():
                    path = target_dir / f"{name} {suffix}.XML"
                    suffix += 1
                preset.save(path, backup=False)
                chemins.append(path)
                written += 1
            except Exception as exc:  # noqa: BLE001
                log.debug("preset %d du lot en échec : %s", index, exc)
                failed.append(str(exc))

        card.invalidate_cache()
        _index_written(self, chemins)
        self.say(f"{written} preset(s) écrit(s) dans "
                 f"SYNTHS/{safe_deluge_name(folder)}"
                 + (f", {len(failed)} en échec" if failed else ""))
        self.presetSaved.emit(card.rel(target_dir))

    # -- kits --------------------------------------------------------------- #

    def _build_kit(self) -> None:
        card = self.card_or_warn()
        if card is None:
            return
        from ...core import kitgen

        try:
            self._kit = kitgen.build_kit(
                card, self.lib, self._kit_name.text().strip() or "MON KIT",
                genre=self._kit_genre.currentData() or "techno",
                seed=int(self._kit_seed.value()),
                prefer_folder=self._kit_folder.text().strip())
        except Exception as exc:  # noqa: BLE001
            log.exception("construction du kit impossible")
            self.say(f"Construction impossible : {exc}")
            return

        self._kit_tried = {}
        familles = self._show_kit_rows()
        if not self._kit.rows:
            self._kit_result.addItem(
                "Aucun échantillon trouvé — lancez une analyse de la carte.")
        if self._kit.rows:
            self.say(f"Kit « {self._kit.name} » : {len(self._kit.rows)} "
                     f"rangées, autour de {familles[0]}"
                     + (f" (+ {len(familles) - 1} autre(s) famille(s))"
                        if len(familles) > 1 else "") + ".")
        else:
            self.say(f"Kit « {self._kit.name} » : aucune rangée.")

    def _show_kit_rows(self) -> list[str]:
        """Remplit la liste des rangées ; rend les familles dans l'ordre."""
        from ...core.kitgen import family_of

        selection = self._kit_result.currentRow()
        self._kit_result.clear()
        familles: list[str] = []
        for row in self._kit.rows:
            famille = family_of(row.file_name)
            if famille not in familles:
                familles.append(famille)
            self._kit_result.addItem(
                f"{row.name:<12} {row.file_name.rsplit('/', 1)[-1]}"
                f"   — {famille}")
        if 0 <= selection < self._kit_result.count():
            self._kit_result.setCurrentRow(selection)
        return familles

    def _reroll_kit_row(self) -> None:
        """Remplace le son de la rangée choisie, le reste du kit intact."""
        if self._kit is None or not self._kit.rows:
            self.say("Construisez d'abord un kit.")
            return
        index = self._kit_result.currentRow()
        if not 0 <= index < len(self._kit.rows):
            self.say("Choisissez d'abord une rangée dans la liste.")
            return
        from ...core import kitgen

        avant = self._kit.rows[index].file_name
        essayes = self._kit_tried.setdefault(index, set())
        essayes.add(avant)
        self._kit_rolls += 1
        slot = kitgen.reroll_row(
            self._kit, index, self.lib,
            genre=self._kit_genre.currentData() or "techno",
            seed=f"{self._kit_seed.value()}|{index}|{self._kit_rolls}",
            avoid=essayes)
        if slot is None:
            self.say("La bibliothèque n'a pas d'autre son pour cette rangée.")
            return
        self._show_kit_rows()
        self.say(f"{self._kit.rows[index].name} : "
                 f"{slot.rel.rsplit('/', 1)[-1]} ({slot.family}).")

    def _listen_kit(self) -> None:
        if self._kit is None:
            self.say("Construisez d'abord un kit.")
            return
        self.say("Rendu du kit…")
        self.run(self._render_kit, self._kit,
                 on_result=self.guard(
                     lambda a: self._play(a) if a is not None else None),
                 on_error=self.guard(
                     lambda m: self.say(f"Rendu impossible : {m}")),
                 title="Rendu du kit")

    def _render_kit(self, kit):
        from ...core import render

        return render.render_kit(kit, sr=44100, sd=self.sd)

    def _save_kit(self) -> None:
        if self._kit is None:
            self.say("Construisez d'abord un kit.")
            return
        card = self.writable_card()
        if card is None:
            return
        from ...core.sdcard import safe_deluge_name

        name = safe_deluge_name(self._kit.name or "MON KIT")
        target = card.abs("KITS") / f"{name}.XML"
        if target.exists():
            answer = QMessageBox.question(
                self, "Le fichier existe",
                f"« {target.name} » existe déjà. Le remplacer ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            self._kit.save(
                target,
                backup=self.ctx.settings.always_backup_before_write)
        except Exception as exc:  # noqa: BLE001
            log.exception("enregistrement du kit impossible")
            self.say(f"Enregistrement impossible : {exc}")
            return
        card.invalidate_cache()
        _index_written(self, [target])
        self.say(f"Kit enregistré : {card.rel(target)}")
        self.presetSaved.emit(card.rel(target))

    # -- morceaux du Deluge ------------------------------------------------- #

    def _genre_tempo(self, genre: str) -> int:
        low, high = genres_mod.genre(genre or "techno").bpm
        return int(round((low + high) / 2.0))

    def _song_from_preset(self) -> None:
        """Le son courant mis en situation : une phrase faite pour son rôle,
        sur une progression et la batterie du genre."""
        if self._preset is None:
            self.say("Générez d'abord un son.")
            return
        options = self._options()
        genre = options.genre or "techno"
        role = options.role or "bass"
        preset = self._preset
        bpm = self._genre_tempo(genre)

        def build(card):
            from ...core import rhythm, songwriter

            beat = rhythm.genre_beat(genre, bars=1, seed=1, fills=False)
            kit, rows, _lost = songwriter.drum_kit_for(card, self.lib, genre,
                                                       beat.tracks)
            return songwriter.preset_song(
                preset, name="", bpm=bpm, genre=genre, role=role,
                drums=rhythm.loop(beat, 4), kit=kit, row_map=rows)

        self.write_song(build, preset.sound.name or "Essai")

    def _song_from_kit(self) -> None:
        """Le kit construit, avec le rythme de son genre, en morceau."""
        if self._kit is None or not self._kit.rows:
            self.say("Construisez d'abord un kit.")
            return
        genre = self._kit_genre.currentData() or "techno"
        kit = self._kit
        bpm = self._genre_tempo(genre)

        def build(card):
            from ...core import rhythm, songwriter

            beat = rhythm.genre_beat(genre, bars=1, seed=1, fills=False)
            rows = songwriter.drum_rows(beat.tracks, kit)
            return songwriter.pattern_song(beat, kit, rows, name="", bpm=bpm,
                                           kit_name=kit.name)

        self.write_song(build, f"{self._kit.name} "
                               f"{genres_mod.genre(genre).label}")


    # -- rafraîchissement --------------------------------------------------- #

    def _refresh(self) -> None:
        if not self._genre_buttons:
            return
        if self._current_genre() == "techno" and \
                not any(b.isChecked() for b in self._genre_buttons.values()):
            self._pick_genre("techno")
        if self._seed.value() == 0:
            self._roll_seed()
            self._kit_seed.setValue(random.randrange(1 << 20))


def _index_written(page, paths) -> None:
    """Ajoute à l'index ce qu'on vient d'écrire, pour que les listes le montrent."""
    try:
        from ...core.scan import index_presets
        index_presets(page.sd, page.lib, list(paths))
    except Exception:  # noqa: BLE001 - l'index se rattrapera à l'analyse
        log.exception("indexation immédiate impossible")
