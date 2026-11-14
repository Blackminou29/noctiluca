# -*- coding: utf-8 -*-
"""Page « Générateur » : un son ou un kit, pour la carte.

Fabriquer des presets de synthé par genre musical ou au hasard, les écouter,
les faire varier, et enregistrer ceux qu'on garde dans ``SYNTHS/`` ; bâtir
un kit dans la bibliothèque de la carte et l'enregistrer dans ``KITS/``. Un
son ou un kit qui plaît s'essaie aussi **dans l'atelier**, au sein d'un
morceau : rien n'est écrit, il y rejoint la piste qui lui convient.

Trois colonnes : les réglages à gauche, le son obtenu au centre, la file des
variations à droite. Les commandes de l'en-tête suivent l'onglet affiché ;
le niveau « avancé » ajoute moteur, graine, mutation, éditeur, réglages
obtenus, fondu et lots. Tout rendu audio part dans un fil séparé.

La graine est affichée et modifiable : c'est elle qui rend un son
reproductible. Noter une graine suffit à retrouver exactement le même preset.
"""

from __future__ import annotations

import logging
import random

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
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
from ...i18n import N_, tr
from ..theme import GOLD, PAD, PAGE_COLORS
from ..widgets.common import (Card, ElidedLabel, GrilleAdaptative,
                              SectionTitle, hint_in_list)
from ..widgets.envelope import EnvelopeEditor
from ..widgets.filtercurve import FilterCurve, SpectrumView
from ..widgets.knob import Knob
from ..rowsampledialog import choose_row_sample
from ..widgets.waveform import WaveformView
from .base import Page, avance, contexte, tool_button

log = logging.getLogger(__name__)

#: Curseurs macro, dans l'ordre d'affichage.
MACROS: tuple[tuple[str, str, str], ...] = (
    ("brightness", N_("Brillance"), N_("Ouvre ou ferme le filtre")),
    ("movement", N_("Mouvement"), N_("Intensité des LFO et de l'enveloppe "
                                     "de modulation")),
    ("space", N_("Espace"), N_("Réverbération et délai")),
    ("dirt", N_("Saleté"), N_("Distorsion, résonance, réduction numérique")),
    ("width", N_("Largeur"), N_("Unisson, désaccord, chorus")),
    ("complexity", N_("Complexité"), N_("Nombre de modulations")),
)

#: Nombre de variations produites d'un coup.
VARIATION_COUNT = 8

#: Les retouches, par curseur : ``(curseur, vers le bas, vers le haut)`` —
#: les clés de :data:`synthgen.NUDGES`. La complexité n'en a pas : une
#: modulation de plus ou de moins n'est pas une direction qu'on entend.
NUDGE_PAIRS: tuple[tuple[str, str, str], ...] = (
    ("brightness", N_("Plus sombre"), N_("Plus brillant")),
    ("dirt", N_("Plus propre"), N_("Plus sale")),
    ("space", N_("Plus sec"), N_("Plus d'espace")),
    ("width", N_("Plus étroit"), N_("Plus large")),
    ("movement", N_("Plus statique"), N_("Plus de mouvement")),
)

#: Les aspects qu'on peut garder quand [Générer] tire un autre son, et leur
#: nom court (:data:`synthgen.FACETS` en donne le détail).
KEEPABLE: tuple[tuple[str, str], ...] = (
    ("moteur", N_("Moteur")), ("timbre", N_("Timbre")),
    ("filtre", N_("Filtre")), ("enveloppes", N_("Enveloppes")),
    ("mouvement", N_("Mouvement")), ("largeur", N_("Largeur")),
    ("espace", N_("Espace")), ("modulations", N_("Modulations")),
)

#: Délai entre le dernier geste sur un curseur et le son refait.
SLIDER_DELAY_MS = 250


class _ColonneDeReglages(QScrollArea):
    """Une colonne de la page : elle défile en hauteur, mais le séparateur
    ne la comprime pas sous la largeur de son contenu.

    Mesuré à 980 px : il ne lui laissait que 153 px pour les 284 que
    demandent les réglages du mode avancé, et les pads de genre sortaient du
    cadre (« Aci », « Boards of »)."""

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - API Qt
        indice = super().minimumSizeHint()
        interieur = self.widget()
        if interieur is None:
            return indice
        largeur = (interieur.minimumSizeHint().width()
                   + self.verticalScrollBar().sizeHint().width()
                   + 2 * self.frameWidth())
        return QSize(max(indice.width(), largeur), indice.height())


class GeneratorPage(Page):
    """Générateur de presets et de kits."""

    TITLE = N_("Générateur")
    EMPTY_DETAIL = N_("Indiquez l'emplacement de votre carte dans les "
                      "réglages. Le générateur fabriquera alors des presets "
                      "et des kits prêts à être enregistrés dessus.")
    ICON = "wand"
    #: Le générateur fonctionne sans carte : seul l'enregistrement en a besoin.
    NEEDS_CARD = False
    LISTENS = True

    #: Un preset vient d'être enregistré sur la carte.
    presetSaved = pyqtSignal(str)
    #: Un son ou un kit à essayer dans l'atelier : ``{"preset", "part",
    #: "options", "edited"}`` ou ``{"kit"}``.
    toAtelier = pyqtSignal(object)

    def __init__(self, ctx, parent=None) -> None:
        super().__init__(ctx, parent)
        self._preset = None
        #: Les variantes de la liste : ``(preset, réglages ou None, libellé,
        #: retouchée)``.
        self._variations: list[tuple] = []
        self._history: list = []
        self._audio = None
        self._macros: dict[str, QSlider] = {}
        #: Les réglages qui ont fait le son courant, quand c'est le
        #: générateur qui l'a fait : l'atelier en tirera ses variantes.
        self._preset_options = None
        self._preset_edited = False
        #: Les réglages, l'état de retouche et le geste qui l'a fait (« Plus
        #: sombre »…) de chaque son de l'historique.
        self._history_meta: dict[int, tuple] = {}
        #: Les graines propres des aspects du son courant
        #: (``GenOptions.facets``) : une variante adoptée les y laisse.
        self._facets: dict[str, int] = {}
        self._macro_values: dict[str, QLabel] = {}
        self._nudge_buttons: list = []
        self._keep_buttons: dict[str, QWidget] = {}
        self._slider_timer = QTimer(self)
        self._slider_timer.setSingleShot(True)
        self._slider_timer.setInterval(SLIDER_DELAY_MS)
        # Une minuterie se branche sur une méthode liée : par ``guard``, elle
        # tirerait sur une page détruite.
        self._slider_timer.timeout.connect(self._sliders_settled)

    # -- construction ------------------------------------------------------- #

    def build(self) -> None:
        outer = QVBoxLayout(self.content())
        outer.setContentsMargins(PAD, PAD, PAD, PAD)
        outer.setSpacing(8)

        header, actions = self.header(
            tr("Générateur"),
            tr("Un son ou un kit pour votre carte, par genre ou au hasard"))
        outer.addWidget(header)

        # Les commandes du son de synthé : elles ne paraissent que sur son
        # onglet. Celles du kit, que sur le sien — un « Générer » au-dessus
        # du kit ne disait pas ce qu'il allait générer.
        self._generate_button = contexte(
            tool_button(tr("Générer"), "wand", primary=True), "preset")
        self._generate_button.clicked.connect(self.guard(self._generate_new))
        actions.addWidget(self._generate_button)

        randomize = contexte(tool_button(
            tr("Au hasard"), "dice",
            tr("Genre, rôle et réglages tirés au sort")), "preset")
        randomize.clicked.connect(self.guard(self._randomize))
        actions.addWidget(randomize)

        mutate = contexte(avance(tool_button(
            tr("Muter"), "refresh", tr("Variante légère du son courant"))),
            "preset")
        mutate.clicked.connect(self.guard(self._mutate))
        actions.addWidget(mutate)

        listen = contexte(tool_button(tr("Écouter"), "play"), "preset")
        listen.clicked.connect(self.guard(self._listen))
        actions.addWidget(listen)

        self._edit_button = contexte(avance(tool_button(
            tr("Modifier le son…"), "settings")), "preset")
        self._edit_button.clicked.connect(self.guard(self._edit))
        actions.addWidget(self._edit_button)

        save = contexte(tool_button(tr("Enregistrer dans SYNTHS"), "save"),
                        "preset")
        save.clicked.connect(self.guard(self._save))
        actions.addWidget(save)

        self._try_preset_button = contexte(tool_button(
            tr("Essayer dans l'atelier"), "atelier"), "preset")
        self._try_preset_button.clicked.connect(
            self.guard(self._preset_to_atelier))
        actions.addWidget(self._try_preset_button)

        self._build_kit_actions(actions)

        tabs = QTabWidget()
        tabs.addTab(self._build_synth_tab(), tr("Preset de synthé"))
        tabs.addTab(self._build_kit_tab(), tr("Kit de batterie"))
        tabs.currentChanged.connect(self.guard(
            lambda index: self.set_context("kit" if index == 1
                                           else "preset")))
        self._contexte = "preset"
        outer.addWidget(tabs, 1)

    def _build_kit_actions(self, actions) -> None:
        """Les commandes du kit, dans l'en-tête, pour son seul onglet."""
        build = contexte(tool_button(tr("Construire le kit"), "kit",
                                     primary=True), "kit")
        build.clicked.connect(self.guard(self._build_kit))
        actions.addWidget(build)
        listen = contexte(tool_button(tr("Écouter le kit"), "play"), "kit")
        listen.clicked.connect(self.guard(self._listen_kit))
        actions.addWidget(listen)
        self._reroll_button = contexte(tool_button(tr("Autre son"), "dice"),
                                       "kit")
        self._reroll_button.clicked.connect(self.guard(self._reroll_kit_row))
        actions.addWidget(self._reroll_button)
        self._pick_sample_button = contexte(tool_button(
            tr("Choisir l'échantillon…"), "list"), "kit")
        self._pick_sample_button.clicked.connect(
            self.guard(self._pick_kit_sample))
        actions.addWidget(self._pick_sample_button)
        save = contexte(tool_button(tr("Enregistrer dans KITS"), "save"),
                        "kit")
        save.clicked.connect(self.guard(self._save_kit))
        actions.addWidget(save)
        self._try_kit_button = contexte(tool_button(
            tr("Essayer dans l'atelier"), "atelier"), "kit")
        self._try_kit_button.clicked.connect(
            self.guard(self._kit_to_atelier))
        actions.addWidget(self._try_kit_button)

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

    def _level_changed(self, advanced: bool) -> None:
        # Les réglages du mode avancé élargissent la colonne : le séparateur
        # relit sa largeur minimale.
        for nom in ("_controls_scroll", "_preview_scroll"):
            colonne = getattr(self, nom, None)
            if colonne is not None:
                colonne.updateGeometry()

    def _build_controls(self) -> QWidget:
        scroll = _ColonneDeReglages()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._controls_scroll = scroll
        inner = QWidget()
        column = QVBoxLayout(inner)
        column.setContentsMargins(0, 0, PAD, 0)
        column.setSpacing(PAD)

        # -- genre
        genre_card = Card(tr("Genre"))
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
                f"{tr(profile.description)}\n\n"
                f"{profile.bpm[0]}–{profile.bpm[1]} BPM")
            button.clicked.connect(
                self.guard(lambda _c=False, k=key: self._pick_genre(k)))
            self._genre_grid.addWidget(button, index // 2, index % 2)
            self._genre_buttons[key] = button
        genre_card.body().addLayout(self._genre_grid)
        # Deux pads par rangée, un seul quand la colonne rétrécit : à 980 px,
        # la seconde colonne sortait du cadre (« ards of Ca… », « Drum a… »).
        self._genre_colonnes = GrilleAdaptative(
            scroll.viewport(), self._genre_grid,
            list(self._genre_buttons.values()), 2, 1, 270)

        self._genre_hint = QLabel("")
        self._genre_hint.setProperty("role", "subtitle")
        self._genre_hint.setWordWrap(True)
        genre_card.body().addWidget(self._genre_hint)
        column.addWidget(genre_card)

        # -- rôle, puis moteur et graine au niveau avancé
        role_card = Card(tr("Rôle du son"))
        grid = QGridLayout()
        grid.setSpacing(6)

        grid.addWidget(QLabel(tr("Rôle")), 0, 0)
        self._role = QComboBox()
        for role in genres_mod.ROLES:
            self._role.addItem(genres_mod.role_label(role), role)
        grid.addWidget(self._role, 0, 1)

        grid.addWidget(avance(QLabel(tr("Moteur"))), 1, 0)
        self._mode = avance(QComboBox())
        self._mode.addItem(tr("Choisi par le genre"), "")
        for mode, label in (("subtractive", tr("Soustractive")), ("fm", "FM"),
                            ("ringmod", tr("Ring mod"))):
            self._mode.addItem(label, mode)
        grid.addWidget(self._mode, 1, 1)

        grid.addWidget(avance(QLabel(tr("Graine"))), 2, 0)
        # La graine du son courant : [Générer] en tire une autre à chaque
        # clic ; en taper une, puis Entrée, refait exactement ce son-là.
        self._seed = avance(QSpinBox())
        self._seed.setRange(0, 1 << 30)
        self._seed.setToolTip(
            tr("La graine du son affiché. Deux générations avec la même "
               "graine et les mêmes réglages donnent exactement le même "
               "son : tapez-en une, puis Entrée, pour retrouver un preset."))
        self._seed.editingFinished.connect(self.guard(self._seed_entered))
        grid.addWidget(self._seed, 2, 1)
        # Les listes et la graine se resserrent : à 980 px, en mode avancé,
        # cette carte demandait 274 px à elle seule, et la colonne des genres
        # en perdait sa seconde rangée de pads.
        for liste in (self._role, self._mode):
            liste.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            liste.setMinimumContentsLength(7)
        self._seed.setMinimumWidth(72)
        role_card.body().addLayout(grid)
        column.addWidget(role_card)

        # -- aspects gardés : [Générer] tire un autre son, sauf eux
        keep_card = avance(Card(tr("Garder en générant")))
        keep_hint = QLabel(tr("Les aspects allumés restent quand « Générer » "
                              "tire un autre son."))
        keep_hint.setProperty("role", "subtitle")
        keep_hint.setWordWrap(True)
        keep_card.body().addWidget(keep_hint)
        keep_grid = QGridLayout()
        keep_grid.setSpacing(4)
        from ...core import synthgen

        for index, (facet, label) in enumerate(KEEPABLE):
            button = tool_button(
                tr(label), "",
                tr("Allumé, « Générer » tire un autre son sans toucher à "
                   "ceci : %s") % tr(synthgen.FACETS[facet]),
                color=PAGE_COLORS.get("Generator", GOLD))
            button.setCheckable(True)
            button.setSizePolicy(QSizePolicy.Policy.Expanding,
                                 QSizePolicy.Policy.Fixed)
            keep_grid.addWidget(button, index // 2, index % 2)
            self._keep_buttons[facet] = button
        keep_card.body().addLayout(keep_grid)
        column.addWidget(keep_card)

        # -- curseurs macro : ils orientent le prochain son, et retouchent
        # le son affiché quand c'est le générateur qui l'a fait.
        macro_card = Card(tr("Réglages"))
        for key, label, tip in MACROS:
            row = QHBoxLayout()
            name = QLabel(tr(label))
            name.setFixedWidth(88)
            name.setToolTip(tr(tip))
            row.addWidget(name)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, 100)
            slider.setValue(50)
            slider.setToolTip(tr(tip))
            row.addWidget(slider, 1)
            value = QLabel("50")
            value.setFixedWidth(28)
            value.setProperty("role", "subtitle")
            slider.valueChanged.connect(
                lambda v, lbl=value: lbl.setText(str(v)))
            slider.valueChanged.connect(self._slider_moved)
            row.addWidget(value)
            macro_card.body().addLayout(row)
            self._macros[key] = slider
            self._macro_values[key] = value
        column.addWidget(macro_card)
        column.addStretch(1)

        scroll.setWidget(inner)
        return scroll

    def _build_preview(self) -> QWidget:
        scroll = _ColonneDeReglages()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._preview_scroll = scroll
        inner = QWidget()
        column = QVBoxLayout(inner)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(8)

        head = Card("")
        self._name = ElidedLabel(tr("Aucun son généré"))
        self._name.setProperty("role", "title")
        head.body().addWidget(self._name)
        self._description = QLabel(
            tr("Choisissez un genre et un rôle, puis cliquez « Générer »."))
        self._description.setWordWrap(True)
        head.body().addWidget(self._description)
        column.addWidget(head)
        column.addWidget(self._build_nudges(scroll))

        sound = Card(tr("Le son"))
        self._wave = WaveformView()
        self._wave.setMinimumHeight(80)
        # Les deux cadres annonçaient « choisissez-en un dans la liste » et
        # « écoutez un échantillon » : il n'y a ici ni liste ni échantillon,
        # le son se fabrique. Un message d'attente qui parle d'autre chose
        # fait douter d'être au bon endroit.
        self._wave.set_empty_text(
            tr("Aucun son généré"),
            tr("Choisissez un genre, puis cliquez « Générer »"))
        sound.body().addWidget(self._wave)
        self._spectrum = SpectrumView()
        self._spectrum.setMinimumHeight(90)
        self._spectrum.set_empty_text(
            tr("Le spectre du son apparaîtra ici"))
        sound.body().addWidget(self._spectrum)
        column.addWidget(sound)

        knobs = avance(Card(tr("Réglages obtenus")))
        grid = QGridLayout()
        grid.setSpacing(6)
        self._knobs: dict[str, Knob] = {}
        for index, (key, label, bipolar) in enumerate((
                ("volume", tr("Volume"), False),
                ("lpfFrequency", tr("Coupure"), False),
                ("lpfResonance", tr("Résonance"), False),
                ("oscAVolume", tr("Osc A"), False),
                ("oscBVolume", tr("Osc B"), False),
                ("reverbAmount", tr("Réverb."), False),
                ("delayFeedback", tr("Délai"), False),
                ("modFXDepth", tr("Mod FX"), False))):
            knob = Knob(label, 25, -25 if bipolar else 0,
                        25 if bipolar else 50, bipolar)
            knob.setEnabled(False)
            grid.addWidget(knob, index // 4, index % 4)
            self._knobs[key] = knob
        knobs.body().addLayout(grid)
        # Quatre encodeurs par rangée, deux quand la colonne rétrécit : à
        # 980 px, en mode avancé, ils demandaient 276 px sur 153.
        self._knob_colonnes = GrilleAdaptative(
            scroll.viewport(), grid, list(self._knobs.values()), 4, 2, 300)
        column.addWidget(knobs)

        shape = avance(Card(tr("Enveloppes et filtre")))
        self._env1 = EnvelopeEditor(title=tr("Enveloppe 1 — amplitude"))
        shape.body().addWidget(self._env1)
        self._filter = FilterCurve()
        shape.body().addWidget(self._filter)
        column.addWidget(shape)
        column.addStretch(1)

        scroll.setWidget(inner)
        return scroll

    def _build_nudges(self, scroll) -> QWidget:
        """Les pads « Retoucher » : le même son, un curseur poussé d'un
        cinquième de sa course (:func:`synthgen.nudged`). Le reste du son ne
        bouge pas ; un son retouché à la main garde ses retouches."""
        card = Card(tr("Retoucher"))
        self._nudge_hint = QLabel(tr(
            "Le même son, poussé dans une direction ; le reste ne bouge "
            "pas."))
        self._nudge_hint.setProperty("role", "subtitle")
        self._nudge_hint.setWordWrap(True)
        card.body().addWidget(self._nudge_hint)
        grid = QGridLayout()
        grid.setSpacing(6)
        colonnes = []
        for macro, down, up in NUDGE_PAIRS:
            label = dict((k, n) for k, n, _t in MACROS)[macro]
            host = QWidget()
            box = QVBoxLayout(host)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(2)
            title = QLabel(tr(label))
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            title.setProperty("role", "subtitle")
            box.addWidget(title)
            pair = QHBoxLayout()
            pair.setSpacing(4)
            for key, icon in ((down, "minus"), (up, "plus")):
                button = tool_button("", icon, tr(
                    "%s — le même son, le reste ne bouge pas  (rien n'est "
                    "écrit sur la carte)") % tr(key))
                button.setAccessibleName(tr(key))
                button.setProperty("nudge", key)
                button.setMinimumWidth(30)
                button.setSizePolicy(QSizePolicy.Policy.Expanding,
                                     QSizePolicy.Policy.Fixed)
                button.clicked.connect(
                    self.guard(lambda _c=False, k=key: self._nudge(k)))
                pair.addWidget(button)
                self._nudge_buttons.append(button)
            box.addLayout(pair)
            colonnes.append(host)
        card.body().addLayout(grid)
        # Cinq curseurs côte à côte, trois quand la colonne rétrécit.
        self._nudge_colonnes = GrilleAdaptative(
            scroll.viewport(), grid, colonnes, 5, 3, 330)
        self._set_nudges_enabled(False)
        return card

    def _build_variations(self) -> QWidget:
        card = Card(tr("Variations"))
        body = card.body()

        hint = QLabel(tr("Cliquez pour écouter, double-cliquez pour adopter."))
        hint.setProperty("role", "subtitle")
        hint.setWordWrap(True)
        body.addWidget(hint)

        make = tool_button(tr("Produire 8 variantes"), "copy")
        make.clicked.connect(self.guard(self._make_variations))
        body.addWidget(make)

        self._variation_list = QListWidget()
        # Les listes élident au lieu de pousser une barre de défilement
        # horizontale sous un panneau de trois cents pixels — l'élision ne
        # joue qu'une fois la barre interdite (vu à 980 px).
        self._variation_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._variation_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        hint_in_list(self._variation_list,
                     "  " + tr("Aucune variante pour l'instant."))
        self._variation_list.currentRowChanged.connect(
            self.guard(self._preview_variation))
        self._variation_list.itemDoubleClicked.connect(
            self.guard(lambda _i: self._adopt_variation()))
        body.addWidget(self._variation_list, 1)

        batch = avance(tool_button(tr("Générer un lot dans un dossier…"),
                                   "export"))
        batch.clicked.connect(self.guard(self._generate_batch))
        body.addWidget(batch)

        body.addWidget(SectionTitle(tr("Historique")))
        self._history_list = QListWidget()
        self._history_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._history_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        hint_in_list(self._history_list,
                     "  " + tr("Les sons générés s'empileront ici."))
        self._history_list.itemDoubleClicked.connect(
            self.guard(lambda _i: self._restore_history()))
        body.addWidget(self._history_list, 1)

        # Fondre le son courant avec un son de l'historique : les réglages
        # continus se mélangent, les choix (formes d'onde, moteur) basculent
        # à mi-chemin.
        morph_host = avance(QWidget())
        morph_row = QHBoxLayout(morph_host)
        morph_row.setContentsMargins(0, 0, 0, 0)
        self._morph_amount = QSlider(Qt.Orientation.Horizontal)
        self._morph_amount.setRange(0, 100)
        self._morph_amount.setValue(50)
        morph_row.addWidget(self._morph_amount, 1)
        morph = tool_button(tr("Fondre"), "refresh")
        morph.clicked.connect(self.guard(self._morph))
        morph_row.addWidget(morph)
        body.addWidget(morph_host)
        return card

    def _build_kit_tab(self) -> QWidget:
        host = QWidget()
        column = QVBoxLayout(host)
        column.setContentsMargins(PAD, PAD, PAD, PAD)
        column.setSpacing(PAD)

        card = Card(tr("Construire un kit depuis la bibliothèque"))
        body = card.body()

        hint = QLabel(tr(
            "Le kit se construit autour d'une machine ou d'une banque de "
            "votre bibliothèque (909, Linndrum, un kit d'artiste…), choisie "
            "selon le genre ; les rôles qu'elle n'a pas sont complétés "
            "ailleurs. Chaque rangée est réglée comme le Deluge la crée : "
            "l'échantillon joué jusqu'au bout et sensible à la vélocité ; "
            "volume et panoramique suivent les kits de la carte, toms en "
            "éventail. Une rangée ne vous plaît pas ? Choisissez-la, puis "
            "« Autre son » — ou « Choisir l'échantillon… » pour l'écouter "
            "parmi tous ceux de son rôle."))
        hint.setProperty("role", "subtitle")
        hint.setWordWrap(True)
        body.addWidget(hint)

        grid = QGridLayout()
        grid.setSpacing(6)
        grid.addWidget(QLabel(tr("Genre")), 0, 0)
        self._kit_genre = QComboBox()
        for key in genres_mod.genre_keys():
            self._kit_genre.addItem(genres_mod.genre(key).label, key)
        grid.addWidget(self._kit_genre, 0, 1)

        grid.addWidget(QLabel(tr("Nom du kit")), 1, 0)
        self._kit_name = QLineEdit(tr("MON KIT"))
        grid.addWidget(self._kit_name, 1, 1)

        grid.addWidget(avance(QLabel(tr("Graine"))), 2, 0)
        self._kit_seed = avance(QSpinBox())
        self._kit_seed.setRange(0, 1 << 30)
        grid.addWidget(self._kit_seed, 2, 1)

        grid.addWidget(avance(QLabel(tr("Dossier à privilégier"))), 3, 0)
        self._kit_folder = avance(QLineEdit())
        self._kit_folder.setPlaceholderText(
            tr("facultatif — ex. SAMPLES/Artists/…"))
        grid.addWidget(self._kit_folder, 3, 1)
        body.addLayout(grid)

        # Les rangées voulues : celles du genre d'abord, à retoucher. Un rôle
        # que la bibliothèque n'a pas reste éteint.
        roles_head = QHBoxLayout()
        roles_head.addWidget(SectionTitle(tr("Rangées")), 1)
        self._genre_roles_button = tool_button(
            tr("Celles du genre"), "refresh",
            tr("Rallume les rangées que le genre conseille, et elles "
               "seules"))
        self._genre_roles_button.clicked.connect(
            self.guard(self._suggest_kit_roles))
        roles_head.addWidget(self._genre_roles_button)
        body.addLayout(roles_head)
        from ...core import kitgen

        roles_grid = QGridLayout()
        roles_grid.setSpacing(4)
        self._kit_roles: dict[str, QWidget] = {}
        for index, role in enumerate(kitgen.ROLES):
            pad = tool_button(tr(role), "", tr(
                "Allumée, le kit aura une rangée « %s »") % tr(role),
                color=PAGE_COLORS.get("Generator", GOLD))
            pad.setCheckable(True)
            pad.setSizePolicy(QSizePolicy.Policy.Expanding,
                              QSizePolicy.Policy.Fixed)
            roles_grid.addWidget(pad, index // 6, index % 6)
            self._kit_roles[role] = pad
        body.addLayout(roles_grid)
        self._kit_roles_colonnes = GrilleAdaptative(
            host, roles_grid, list(self._kit_roles.values()), 6, 4, 760)
        self._kit_genre.currentIndexChanged.connect(
            self.guard(lambda _i: self._suggest_kit_roles()))
        self._suggest_kit_roles()

        self._kit_result = QListWidget()
        self._kit_result.itemDoubleClicked.connect(
            self.guard(lambda _i: self._pick_kit_sample()))
        body.addWidget(self._kit_result, 1)
        column.addWidget(card, 1)
        self._kit = None
        #: Échantillons déjà essayés, par rangée, pour « Autre son ».
        self._kit_tried: dict[int, set] = {}
        self._kit_rolls = 0
        # Défilant : à 980 × 700, les pads des rangées et la liste
        # demandaient plus que la hauteur offerte, et les pads se
        # chevauchaient (vu au rendu).
        self._kit_result.setMinimumHeight(140)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(host)
        return scroll

    # -- réglages ----------------------------------------------------------- #

    def _pick_genre(self, key: str) -> None:
        for name, button in self._genre_buttons.items():
            button.setChecked(name == key)
        profile = genres_mod.genre(key)
        self._genre_hint.setText(
            f"{tr(profile.description)}  "
            f"({profile.bpm[0]}–{profile.bpm[1]} BPM)")

    def _current_genre(self) -> str:
        for key, button in self._genre_buttons.items():
            if button.isChecked():
                return key
        return "techno"

    def _roll_seed(self) -> None:
        self._seed.setValue(random.randrange(1 << 30))

    def _options(self):
        """Les réglages affichés à gauche, avec les graines propres des
        aspects du son courant."""
        from ...core.synthgen import GenOptions

        return GenOptions(
            genre=self._current_genre(),
            role=self._role.currentData() or "bass",
            seed=int(self._seed.value()),
            mode=self._mode.currentData() or "",
            wavetables=self._wavetables(),
            facets=dict(self._facets),
            **{key: slider.value() / 100.0
               for key, slider in self._macros.items()})

    def _kept_facets(self) -> list[str]:
        """Les aspects allumés dans « Garder en générant »."""
        return [facet for facet, button in self._keep_buttons.items()
                if button.isChecked()]

    def _set_macro(self, key: str, value: float) -> None:
        """Place un curseur sans que la page refasse le son."""
        slider = self._macros.get(key)
        if slider is None:
            return
        slider.blockSignals(True)
        slider.setValue(int(round(float(value) * 100)))
        slider.blockSignals(False)
        label = self._macro_values.get(key)
        if label is not None:
            label.setText(str(slider.value()))

    def _show_options(self, options) -> None:
        """Les réglages de gauche reprennent ceux du son affiché : genre,
        rôle, moteur, graine, curseurs et graines des aspects. C'est d'eux
        que partent la retouche, les curseurs et le prochain « Générer »."""
        if options is None:
            return
        if options.genre in self._genre_buttons:
            self._pick_genre(options.genre)
        index = self._role.findData(options.role)
        if index >= 0:
            self._role.setCurrentIndex(index)
        index = self._mode.findData(options.mode or "")
        if index >= 0:
            self._mode.setCurrentIndex(index)
        if options.seed is not None:
            self._seed.blockSignals(True)
            self._seed.setValue(int(options.seed))
            self._seed.blockSignals(False)
        for key in self._macros:
            self._set_macro(key, getattr(options, key, 0.5))
        self._facets = dict(options.facets or {})
        self._slider_timer.stop()

    def _wavetables(self) -> list[str]:
        """Les tables d'onde de la carte (``SAMPLES/WAVETABLES``) : un genre
        qui emploie ce moteur peut alors s'en servir."""
        from ...core import wavetable

        if not self.ctx.has_card:
            return []
        try:
            rows = self.lib.search_samples(folder=wavetable.FOLDER,
                                           limit=500)
        except Exception:  # noqa: BLE001 - sans index, pas de table
            return []
        return sorted(r["rel"] for r in rows)

    # -- génération --------------------------------------------------------- #

    def _generate(self) -> None:
        """Le son que donnent les réglages affichés, graine comprise :
        reproductible."""
        from ...core import synthgen

        options = self._options()
        self._show_preset(synthgen.generate(options), options=options)
        self.say(tr("Preset généré : %s") % self._preset.sound.name)

    def _generate_new(self) -> None:
        """[Générer] : un autre son du genre et du rôle choisis, sous une
        nouvelle graine — sauf pour les aspects allumés dans « Garder en
        générant ».

        Avant, le bouton reprenait la graine affichée : au niveau simple, où
        la graine est cachée, recliquer redonnait le même son."""
        from ...core import synthgen

        seed = random.randrange(1 << 30)
        kept = self._kept_facets()
        options = synthgen.reseeded(self._options(), seed, keep=kept)
        self._show_preset(synthgen.generate(options), options=options)
        if kept:
            self.say(tr("Preset généré : %s — gardés : %s")
                     % (self._preset.sound.name,
                        ", ".join(tr(dict(KEEPABLE)[f]).lower()
                                  for f in kept)))
        else:
            self.say(tr("Preset généré : %s") % self._preset.sound.name)

    def _seed_entered(self) -> None:
        """Une graine tapée, puis Entrée : le son de cette graine-là."""
        options = self._preset_options
        if options is not None and options.seed == int(self._seed.value()):
            return
        self._facets = {}
        self._generate()

    def _randomize(self) -> None:
        from ...core import synthgen

        options = synthgen.random_options(seed=random.randrange(1 << 30))
        options.wavetables = self._wavetables()
        preset = synthgen.generate(options)
        self._show_preset(preset, options=options)
        self.say(tr("Son au hasard : %s") % preset.sound.name)

    # -- retouches ---------------------------------------------------------- #

    def _set_nudges_enabled(self, enabled: bool) -> None:
        for button in self._nudge_buttons:
            button.setEnabled(bool(enabled))
        if enabled:
            self._nudge_hint.setText(tr(
                "Le même son, poussé dans une direction ; le reste ne bouge "
                "pas."))
        elif self._preset is None:
            self._nudge_hint.setText(tr(
                "Générez un son : ces pads le pousseront dans une direction."))
        else:
            self._nudge_hint.setText(tr(
                "Ce son ne vient pas du générateur : il ne sait pas le "
                "refaire. « Modifier le son… » le retouche à la main."))

    def _restyle(self, after, note: str) -> None:
        """Le son courant refait avec ``after`` ; ses retouches à la main
        suivent."""
        from ...core import synthgen

        before = self._preset_options
        edited = self._preset.sound if self._preset_edited else None
        preset = synthgen.restyled(before, after, edited)
        self._show_preset(preset, options=after, edited=self._preset_edited,
                          note=note)

    def _nudge(self, label: str) -> None:
        """Un pad « Retoucher » : le curseur poussé, le reste du son
        identique."""
        if self._preset is None or self._preset_options is None:
            self._set_nudges_enabled(False)
            self.say(self._nudge_hint.text())
            return
        from ...core import synthgen

        after = synthgen.nudged(self._preset_options, label)
        if after is None:
            self.say(tr("%s : le curseur est déjà en butée.") % tr(label))
            return
        self._restyle(after, tr(label))
        self.say(tr("%s : %s") % (tr(label), self._preset.sound.name))

    def _slider_moved(self, _value: int = 0) -> None:
        self._slider_timer.start()

    def _sliders_settled(self) -> None:
        """Les curseurs retouchent le son affiché, quand c'est le
        générateur qui l'a fait : même graine, même genre, seuls bougent
        les réglages que règle le curseur."""
        try:
            if self._preset is None or self._preset_options is None:
                return
            before = self._preset_options
            changed = [(key, label) for key, label, _t in MACROS
                       if abs(self._macros[key].value() / 100.0
                              - float(getattr(before, key, 0.5))) > 1e-6]
            if not changed:
                return
            from dataclasses import replace

            after = replace(before, facets=dict(before.facets or {}),
                            use_samples=list(before.use_samples or []))
            for key, _label in changed:
                setattr(after, key, self._macros[key].value() / 100.0)
            note = ", ".join("%s %d" % (tr(label), self._macros[key].value())
                             for key, label in changed)
            self._restyle(after, note)
            self.say(tr("Retouché : %s") % note)
        except Exception:  # noqa: BLE001 - une minuterie ne passe pas par guard
            log.exception("retouche par les curseurs impossible")

    def _mutate(self) -> None:
        if self._preset is None:
            self.say(tr("Générez d'abord un son."))
            return
        from ...core import synthgen

        self._show_preset(synthgen.mutate(self._preset, amount=0.3))
        self.say(tr("Variante : %s") % self._preset.sound.name)

    def start_from(self, preset) -> None:
        """Prend un preset existant comme point de départ.

        C'est la porte d'entrée depuis la page Presets : le son de la carte
        devient le son courant, que « Muter » et « Produire 8 variantes »
        font évoluer. L'original n'est jamais réécrit : « Enregistrer » en
        fait une copie, sous le nom que vous choisirez.
        """
        self._show_preset(preset)
        self.say(tr("Point de départ : %s. « Muter » ou « Produire 8 "
                    "variantes » partent de lui.") % preset.sound.name)

    def _show_preset(self, preset, options=None, edited: bool = False,
                     note: str = "") -> None:
        """Affiche un preset et le place dans l'historique.

        ``options`` : les réglages qui l'ont fait, quand c'est le générateur
        — les réglages de gauche les reprennent, et retouches, curseurs et
        variantes partent d'eux ; ``edited`` : il a été retouché à la main
        depuis ; ``note`` : le geste qui l'a fait, montré dans l'historique.
        """
        from ...core import synthgen

        self._preset = preset
        self._preset_options = options
        self._preset_edited = bool(edited)
        self._history_meta[id(preset)] = (options, bool(edited), note)
        self._show_options(options)
        self._set_nudges_enabled(options is not None)
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
            meta = self._history_meta.get(id(item), ())
            geste = meta[2] if len(meta) > 2 else ""
            self._history_list.addItem(
                f"{item.sound.name}  · {geste}" if geste else item.sound.name)
        hint_in_list(self._history_list,
                     "  " + tr("Les sons générés s'empileront ici."))

        self._render_async(preset)

    # -- écoute ------------------------------------------------------------- #

    def _render_async(self, preset) -> None:
        self.run(self._render, preset,
                 on_result=self.guard(self._rendered),
                 on_error=self.guard(
                     lambda m: self.say(tr("Rendu impossible : %s") % m)),
                 title=tr("Rendu du son"))

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
            self.say(tr("Générez d'abord un son."))
            return
        # La machine d'abord, quand elle est là : elle sonne juste, et le
        # rendu approché n'a plus d'intérêt.
        if self.audition(self._preset.sound):
            return
        if self._audio is not None:
            self._play(self._audio)
        else:
            self._render_async(self._preset)

    def _edit(self) -> None:
        """Ouvre l'éditeur sur le son courant ; le son retouché rejoint
        l'historique, comme un son généré."""
        if self._preset is None:
            self.say(tr("Générez d'abord un son."))
            return
        import copy

        from PyQt6.QtWidgets import QDialog

        from ..theme import PAGE_COLORS
        from ..widgets.soundeditor import SoundEditorDialog

        dialog = SoundEditorDialog(
            self.ctx, self._preset.sound,
            title=tr("Modifier le son — %s") % self._preset.sound.name,
            color=PAGE_COLORS.get("Generator", PAGE_COLORS.get("Atelier")),
            parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        changes = dialog.changes()
        preset = copy.deepcopy(self._preset)
        preset.sound = dialog.edited_sound()
        preset.name = preset.sound.name or preset.name
        self._show_preset(preset, options=self._preset_options,
                          edited=self._preset_edited or bool(changes))
        if changes:
            self.say(tr("Son retouché : %s.") % " · ".join(changes[:3]))
        else:
            self.say(tr("Le son n'a pas changé."))

    def _play(self, audio) -> None:
        if self.player is None:
            self.say(tr("Aucune sortie audio disponible."))
            return
        try:
            self.player.set_volume(self.ctx.settings.preview_volume)
            self.player.play_array(audio, 44100)
        except Exception as exc:  # noqa: BLE001
            log.debug("lecture impossible : %s", exc)
            self.say(tr("Lecture impossible : %s") % exc)

    # -- variations --------------------------------------------------------- #

    def _make_variations(self) -> None:
        """Huit variantes du son courant. Dans le style quand c'est le
        générateur qui l'a fait : chacune tire à nouveau un seul aspect ou
        pousse un seul curseur, sans quitter le genre ni le rôle — et garde
        les retouches faites à la main. Un son venu d'ailleurs (la carte, un
        fondu) n'a pas de réglages à refaire : ses variantes le mutent."""
        if self._preset is None:
            self.say(tr("Générez d'abord un son."))
            return
        from ...core import synthgen

        seed = random.randrange(1 << 30)
        options = self._preset_options
        if options is None:
            self._variations = [
                (preset, None, "", False) for preset in synthgen.variations(
                    self._preset, n=VARIATION_COUNT, amount=0.3, seed=seed)]
        else:
            if self._preset_edited:
                found = synthgen.edited_variations(
                    options, self._preset.sound, VARIATION_COUNT, seed=seed)
            else:
                found = synthgen.style_variations(options, VARIATION_COUNT,
                                                  seed=seed)
            self._variations = [(v.preset, v.options, tr(v.label),
                                 v.retouched or self._preset_edited)
                                for v in found]
        self._variation_list.clear()
        for index, (preset, _o, label, _r) in enumerate(self._variations, 1):
            # Une variante dans le style garde le nom du son : c'est ce
            # qu'elle change qui la distingue.
            item = QListWidgetItem(f"{index}.  {label or preset.sound.name}")
            item.setToolTip(f"{preset.sound.name} — "
                            f"{synthgen.describe(preset)}")
            self._variation_list.addItem(item)
        hint_in_list(self._variation_list,
                     "  " + tr("Aucune variante pour l'instant."))
        self.say(tr("%d variantes produites.") % len(self._variations))

    def _preview_variation(self, row: int) -> None:
        if not 0 <= row < len(self._variations):
            return
        self._render_async(self._variations[row][0])

    def _adopt_variation(self) -> None:
        row = self._variation_list.currentRow()
        if not 0 <= row < len(self._variations):
            return
        preset, options, label, retouched = self._variations[row]
        self._show_preset(preset, options=options, edited=retouched,
                          note=label)
        self.say(tr("Variante adoptée : %s") % self._preset.sound.name)

    def _morph(self) -> None:
        """Fond le son courant avec le son choisi dans l'historique."""
        row = self._history_list.currentRow()
        if self._preset is None or not 0 <= row < len(self._history):
            self.say(tr("Choisissez dans l'historique le son avec lequel "
                        "fondre le son courant."))
            return
        autre = self._history[row]
        if autre is self._preset:
            self.say(tr("Choisissez un autre son que le son courant."))
            return
        from ...core import synthgen

        dosage = self._morph_amount.value() / 100.0
        mixte = synthgen.morph(self._preset, autre, dosage)
        self._show_preset(mixte)
        self.say(tr("Fondu à %d %% vers %s : %s")
                 % (self._morph_amount.value(), autre.sound.name,
                    mixte.sound.name))

    def _restore_history(self) -> None:
        row = self._history_list.currentRow()
        if not 0 <= row < len(self._history):
            return
        preset = self._history[row]
        options, edited, note = self._history_meta.get(id(preset),
                                                       (None, False, ""))
        self._show_preset(preset, options=options, edited=edited, note=note)

    # -- enregistrement ----------------------------------------------------- #

    def _save(self) -> None:
        """Enregistre le preset courant dans ``SYNTHS/``."""
        if self._preset is None:
            self.say(tr("Générez d'abord un son."))
            return
        card = self.writable_card()
        if card is None:
            return

        from ...core.sdcard import check_name, safe_deluge_name

        name, ok = QInputDialog.getText(
            self, tr("Enregistrer le preset"),
            tr("Nom du preset (il sera assaini pour la carte) :"),
            QLineEdit.EchoMode.Normal, self._preset.sound.name)
        if not ok or not name.strip():
            return

        folder, ok = QInputDialog.getText(
            self, tr("Dossier de destination"),
            tr("Sous-dossier de SYNTHS (vide = racine de SYNTHS) :"),
            QLineEdit.EchoMode.Normal, tr("Generes"))
        if not ok:
            return

        clean = safe_deluge_name(name)
        problems = check_name(clean)
        if problems:
            QMessageBox.warning(self, tr("Nom refusé"), "\n".join(problems))
            return

        parts = ["SYNTHS"] + [safe_deluge_name(p)
                              for p in folder.split("/") if p.strip()]
        target = card.abs("/".join(parts)) / f"{clean}.XML"
        if target.exists():
            answer = QMessageBox.question(
                self, tr("Le fichier existe"),
                tr("« %s » existe déjà. Le remplacer ?") % target.name,
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
            self.say(tr("Enregistrement impossible : %s") % exc)
            return

        card.invalidate_cache()
        _index_written(self, [target])
        rel = card.rel(target)
        self.say(tr("Preset enregistré : %s") % rel)
        self.presetSaved.emit(rel)

    def _generate_batch(self) -> None:
        """Produit plusieurs presets d'un coup dans un nouveau dossier."""
        card = self.writable_card()
        if card is None:
            return
        count, ok = QInputDialog.getInt(
            self, tr("Générer un lot"),
            tr("Combien de presets produire ?"), 8, 1, 64)
        if not ok:
            return
        folder, ok = QInputDialog.getText(
            self, tr("Dossier de destination"),
            tr("Sous-dossier de SYNTHS :"), QLineEdit.EchoMode.Normal,
            tr("Lot %s") % self._current_genre())
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
            self.say(tr("Dossier impossible : %s") % exc)
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
        dossier = "SYNTHS/%s" % safe_deluge_name(folder)
        self.say(tr("%d preset(s) écrit(s) dans %s, %d en échec")
                 % (written, dossier, len(failed)) if failed else
                 tr("%d preset(s) écrit(s) dans %s") % (written, dossier))
        self.presetSaved.emit(card.rel(target_dir))

    # -- kits --------------------------------------------------------------- #

    def _suggest_kit_roles(self) -> None:
        """Les rangées que le genre conseille, allumées, et elles seules."""
        from ...core import kitgen

        suggested = set(kitgen.suggest_slots(
            self._kit_genre.currentData() or "techno"))
        for role, pad in self._kit_roles.items():
            pad.setChecked(role in suggested and pad.isEnabled())

    def _mark_kit_roles(self) -> None:
        """Éteint les rôles dont la bibliothèque n'a aucun échantillon — sans
        index, tous restent possibles."""
        from ...core import kitgen

        available = None
        if self.ctx.has_card:
            try:
                available = kitgen.available_roles(self.lib)
            except Exception as exc:  # noqa: BLE001 - sans index, tout reste
                log.debug("rôles de la bibliothèque illisibles : %s", exc)
        for role, pad in self._kit_roles.items():
            usable = not available or role in available
            pad.setEnabled(usable)
            if not usable:
                pad.setChecked(False)
            pad.setToolTip(
                tr("Allumée, le kit aura une rangée « %s »") % tr(role)
                if usable else
                tr("La bibliothèque n'a aucun échantillon « %s »") % tr(role))

    def _kit_slots(self) -> list[str]:
        from ...core import kitgen

        return kitgen.ordered_slots(
            self._kit_genre.currentData() or "techno",
            [r for r, pad in self._kit_roles.items() if pad.isChecked()])

    def _build_kit(self) -> None:
        card = self.card_or_warn()
        if card is None:
            return
        from ...core import kitgen

        slots = self._kit_slots()
        if not slots:
            self.say(tr("Allumez au moins une rangée."))
            return
        try:
            self._kit = kitgen.build_kit(
                card, self.lib, self._kit_name.text().strip() or tr("MON KIT"),
                genre=self._kit_genre.currentData() or "techno",
                seed=int(self._kit_seed.value()), slots=slots,
                prefer_folder=self._kit_folder.text().strip())
        except Exception as exc:  # noqa: BLE001
            log.exception("construction du kit impossible")
            self.say(tr("Construction impossible : %s") % exc)
            return

        self._kit_tried = {}
        familles = self._show_kit_rows()
        if not self._kit.rows:
            self._kit_result.addItem(
                tr("Aucun échantillon trouvé — lancez une analyse de la "
                   "carte."))
        if self._kit.rows and len(familles) > 1:
            self.say(tr("Kit « %s » : %d rangées, autour de %s (+ %d "
                        "autre(s) famille(s)).")
                     % (self._kit.name, len(self._kit.rows),
                        tr(familles[0]), len(familles) - 1))
        elif self._kit.rows:
            self.say(tr("Kit « %s » : %d rangées, autour de %s.")
                     % (self._kit.name, len(self._kit.rows),
                        tr(familles[0])))
        else:
            self.say(tr("Kit « %s » : aucune rangée.") % self._kit.name)

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
                f"   — {tr(famille)}")
        if 0 <= selection < self._kit_result.count():
            self._kit_result.setCurrentRow(selection)
        return familles

    def _reroll_kit_row(self) -> None:
        """Remplace le son de la rangée choisie, le reste du kit intact."""
        if self._kit is None or not self._kit.rows:
            self.say(tr("Construisez d'abord un kit."))
            return
        index = self._kit_result.currentRow()
        if not 0 <= index < len(self._kit.rows):
            self.say(tr("Choisissez d'abord une rangée dans la liste."))
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
            self.say(tr("La bibliothèque n'a pas d'autre son pour cette "
                        "rangée."))
            return
        self._show_kit_rows()
        self.say(tr("%s : %s (%s).")
                 % (self._kit.rows[index].name,
                    slot.rel.rsplit("/", 1)[-1], tr(slot.family)))

    def _pick_kit_sample(self) -> None:
        """L'échantillon de la rangée choisie, choisi à l'oreille parmi tous
        ceux de son rôle (:class:`RowSampleDialog`)."""
        if self._kit is None or not self._kit.rows:
            self.say(tr("Construisez d'abord un kit."))
            return
        index = self._kit_result.currentRow()
        if not 0 <= index < len(self._kit.rows):
            self.say(tr("Choisissez d'abord une rangée dans la liste."))
            return
        from ...core import kitgen

        chosen = choose_row_sample(
            self, self._kit, index,
            genre=self._kit_genre.currentData() or "techno")
        if chosen is None:
            return
        slot = kitgen.use_sample(self._kit, index, chosen)
        if slot is None:
            return
        self._show_kit_rows()
        self.say(tr("%s : %s (%s).")
                 % (self._kit.rows[index].name,
                    slot.rel.rsplit("/", 1)[-1], tr(slot.family)))

    def _listen_kit(self) -> None:
        if self._kit is None:
            self.say(tr("Construisez d'abord un kit."))
            return
        self.say(tr("Rendu du kit…"))
        self.run(self._render_kit, self._kit,
                 on_result=self.guard(
                     lambda a: self._play(a) if a is not None else None),
                 on_error=self.guard(
                     lambda m: self.say(tr("Rendu impossible : %s") % m)),
                 title=tr("Rendu du kit"))

    def _render_kit(self, kit):
        from ...core import render

        return render.render_kit(kit, sr=44100, sd=self.sd)

    def _save_kit(self) -> None:
        if self._kit is None:
            self.say(tr("Construisez d'abord un kit."))
            return
        card = self.writable_card()
        if card is None:
            return
        from ...core.sdcard import safe_deluge_name

        name = safe_deluge_name(self._kit.name or tr("MON KIT"))
        target = card.abs("KITS") / f"{name}.XML"
        if target.exists():
            answer = QMessageBox.question(
                self, tr("Le fichier existe"),
                tr("« %s » existe déjà. Le remplacer ?") % target.name,
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
            self.say(tr("Enregistrement impossible : %s") % exc)
            return
        card.invalidate_cache()
        _index_written(self, [target])
        self.say(tr("Kit enregistré : %s") % card.rel(target))
        self.presetSaved.emit(card.rel(target))

    # -- vers l'atelier ------------------------------------------------------ #

    def _preset_to_atelier(self) -> None:
        """Le son courant rejoint le morceau de l'atelier, à la piste de son
        rôle — ou le prochain morceau, s'il n'y en a pas encore. Rien n'est
        écrit : on l'écoute en situation, et le morceau s'écrit à la
        dernière étape de l'atelier."""
        if self._preset is None:
            self.say(tr("Générez d'abord un son."))
            return
        import copy

        options = self._preset_options
        role = options.role if options is not None \
            else (self._role.currentData() or "lead")
        self.toAtelier.emit({
            "preset": copy.deepcopy(self._preset), "part": role,
            "options": copy.deepcopy(options),
            "edited": self._preset_edited})

    def _kit_to_atelier(self) -> None:
        """Le kit construit devient la batterie du morceau de l'atelier."""
        if self._kit is None or not self._kit.rows:
            self.say(tr("Construisez d'abord un kit."))
            return
        import copy

        self.toAtelier.emit({"kit": copy.deepcopy(self._kit)})


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
        # Les rôles que la bibliothèque n'a pas s'éteignent ; au premier
        # passage, ceux du genre s'allument.
        first = not any(pad.isChecked() for pad in self._kit_roles.values())
        self._mark_kit_roles()
        if first:
            self._suggest_kit_roles()


def _index_written(page, paths) -> None:
    """Ajoute à l'index ce qu'on vient d'écrire, pour que les listes le montrent."""
    try:
        from ...core.scan import index_presets
        index_presets(page.sd, page.lib, list(paths))
    except Exception:  # noqa: BLE001 - l'index se rattrapera à l'analyse
        log.exception("indexation immédiate impossible")
