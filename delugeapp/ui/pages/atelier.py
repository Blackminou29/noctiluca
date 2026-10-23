# -*- coding: utf-8 -*-
"""Page « Atelier » : composer un morceau, du premier son à l'arrangement.

Quatre onglets, dans l'ordre du travail :

1. **Style** — le genre, la tonalité, le tempo, l'ambiance des accords, les
   six curseurs que partagent tous les sons du morceau, et les pistes :
   kit, synthés, MIDI (un appareil extérieur), CV (un modulaire) ;
2. **Sons** — le son de chaque piste, et ses variantes **dans le style** :
   un aspect tiré à nouveau, ou un curseur poussé ;
3. **Clips** — les clips de chaque piste et leurs variations, à écouter ici
   ou **sur le Deluge**, calés sur sa mesure quand il joue ;
4. **Morceau** — la matrice des sections : quel clip chaque piste joue
   dans chacune ; puis le morceau écrit sur la carte, ou ajouté au morceau
   d'où l'on est parti, sans rien en réécrire.

Le cœur est dans :mod:`delugeapp.core.atelier` ; la page ne fait que le
montrer et le faire jouer. Tout rendu audio part dans un fil.
"""

from __future__ import annotations

import copy
import logging
import random

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...core import atelier, genres as genres_mod, theory, variation
from ...i18n import N_, plural, tr
from ..theme import PAD
from ..widgets.atelierviews import ClipView, SectionMatrix, part_color
from ..widgets.common import Card, GrilleAdaptative, hint_in_list, pad_dot
from .base import Page, tool_button
# Les curseurs du style : ceux du Générateur, avec leurs explications.
from .generator import MACROS

log = logging.getLogger(__name__)

#: Gammes proposées : celles qu'on joue en musique électronique d'abord.
SCALES = ("mineur", "majeur", "dorien", "phrygien", "mixolydien", "lydien",
          "mineur harmonique", "pentatonique mineure",
          "pentatonique majeure", "blues")

#: Longueurs proposées pour un clip neuf, en mesures.
CLIP_BARS = (1, 2, 4, 8)


class AtelierPage(Page):
    """L'atelier du compositeur."""

    TITLE = N_("Atelier")
    ICON = "atelier"
    EMPTY_DETAIL = N_("L'atelier compose sans carte ; il lui faut la carte "
                      "pour écrire le morceau, et ses échantillons pour "
                      "bâtir un kit.")
    #: On compose et on écoute sans carte : seule l'écriture en a besoin.
    NEEDS_CARD = False

    def __init__(self, ctx, parent=None) -> None:
        super().__init__(ctx, parent)
        self._project: atelier.Project | None = None
        self._uid: int | None = None
        self._clip_key: str | None = None
        self._section = 0
        self._variants: list = []
        self._genre = "techno"
        self._macros: dict[str, QSlider] = {}
        self._genre_buttons: dict[str, object] = {}
        self._part_checks: dict[str, QCheckBox] = {}
        self._part_kinds: dict[str, QComboBox] = {}
        self._part_channels: dict[str, QSpinBox] = {}
        self._live_timer = QTimer(self)
        self._live_timer.setInterval(250)
        self._live_timer.timeout.connect(self.guard(self._watch_live))

    # -- construction ------------------------------------------------------- #

    def build(self) -> None:
        outer = QVBoxLayout(self.content())
        outer.setContentsMargins(PAD, PAD, PAD, PAD)
        outer.setSpacing(8)

        header, actions = self.header(
            tr("Atelier"),
            tr("Du premier son à l'arrangement : un morceau, ses pistes, "
               "ses clips"))
        outer.addWidget(header)

        self._compose_button = tool_button(tr("Composer"), "wand",
                                           primary=True)
        self._compose_button.clicked.connect(self.guard(self._compose))
        actions.addWidget(self._compose_button)

        self._import_button = tool_button(tr("Partir d'un morceau…"),
                                          "import")
        self._import_button.clicked.connect(self.guard(self._import_song))
        actions.addWidget(self._import_button)

        self._write_button = tool_button(tr("Écrire le morceau"), "song")
        self._write_button.clicked.connect(self.guard(self._write_song))
        actions.addWidget(self._write_button)

        self._complete_button = tool_button(tr("Compléter le morceau"),
                                            "save")
        self._complete_button.clicked.connect(self.guard(self._complete))
        actions.addWidget(self._complete_button)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_style_tab(), tr("Style"))
        self._tabs.addTab(self._build_sounds_tab(), tr("Sons"))
        self._tabs.addTab(self._build_clips_tab(), tr("Clips"))
        self._tabs.addTab(self._build_song_tab(), tr("Morceau"))
        outer.addWidget(self._tabs, 1)
        self._pick_genre("techno")
        self._update_actions()

    # -- onglet Style ----------------------------------------------------- #

    def _build_style_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        inner = QWidget()
        row = QGridLayout(inner)
        row.setContentsMargins(0, PAD, 0, 0)
        row.setSpacing(PAD)

        genre_card = Card(tr("Genre"))
        grid = QGridLayout()
        grid.setSpacing(4)
        for key in genres_mod.genre_keys():
            profile = genres_mod.genre(key)
            button = tool_button(profile.label, "", color=profile.color)
            button.setCheckable(True)
            button.setMinimumWidth(92)
            button.setSizePolicy(QSizePolicy.Policy.Expanding,
                                 QSizePolicy.Policy.Fixed)
            button.setToolTip("%s\n\n%d–%d BPM" % (
                tr(profile.description), profile.bpm[0], profile.bpm[1]))
            button.clicked.connect(
                self.guard(lambda _c=False, k=key: self._pick_genre(k)))
            self._genre_buttons[key] = button
        genre_card.body().addLayout(grid)
        # Trois pads par rangée, deux quand le panneau rétrécit : à 980 px,
        # « Boards of Canada » sortait coupé.
        self._genre_grid = GrilleAdaptative(
            genre_card, grid, list(self._genre_buttons.values()), 3, 2, 470)
        self._genre_hint = QLabel("")
        self._genre_hint.setProperty("role", "subtitle")
        self._genre_hint.setWordWrap(True)
        genre_card.body().addWidget(self._genre_hint)
        genre_card.body().addStretch(1)

        music_host = QWidget()
        column = QVBoxLayout(music_host)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(PAD)
        music = Card(tr("Tonalité et tempo"))
        form = QGridLayout()
        form.setSpacing(6)
        form.addWidget(QLabel(tr("Tonique")), 0, 0)
        self._root = QComboBox()
        for pc in range(12):
            self._root.addItem(theory.note_to_name(48 + pc,
                                                   with_octave=False), 48 + pc)
        self._root.setCurrentIndex(9)                    # la
        form.addWidget(self._root, 0, 1)
        form.addWidget(QLabel(tr("Gamme")), 1, 0)
        self._scale = QComboBox()
        for name in SCALES:
            if name in theory.SCALES:
                self._scale.addItem(tr(name), name)
        form.addWidget(self._scale, 1, 1)
        form.addWidget(QLabel(tr("Tempo")), 2, 0)
        self._bpm = QSpinBox()
        self._bpm.setRange(40, 250)
        self._bpm.setSuffix(" BPM")
        form.addWidget(self._bpm, 2, 1)
        form.addWidget(QLabel(tr("Ambiance")), 3, 0)
        self._ambiance = QComboBox()
        self._ambiance.addItem(tr("Celle du genre"), "")
        for name in theory.progression_names():
            self._ambiance.addItem(tr(name), name)
        form.addWidget(self._ambiance, 3, 1)
        form.addWidget(QLabel(tr("Couleur")), 4, 0)
        self._chord_color = QComboBox()
        self._chord_color.addItem(tr("Celle de l'ambiance"), "")
        for name in theory.CHORD_COLORS:
            self._chord_color.addItem(tr(name), name)
        form.addWidget(self._chord_color, 4, 1)
        form.addWidget(QLabel(tr("Graine")), 5, 0)
        seed_row = QHBoxLayout()
        self._seed = QSpinBox()
        self._seed.setRange(0, 1 << 30)
        self._seed.setValue(1)
        seed_row.addWidget(self._seed, 1)
        self._dice = tool_button("", "dice")
        self._dice.setFixedWidth(34)
        self._dice.clicked.connect(self.guard(self._roll_seed))
        seed_row.addWidget(self._dice)
        holder = QWidget()
        holder.setLayout(seed_row)
        form.addWidget(holder, 5, 1)
        music.body().addLayout(form)
        column.addWidget(music)

        sound = Card(tr("Caractère des sons"))
        hint = QLabel(tr("Les mêmes pour tous les synthés du morceau : c'est "
                         "ce qui les fait sonner ensemble."))
        hint.setProperty("role", "subtitle")
        hint.setWordWrap(True)
        sound.body().addWidget(hint)
        for key, label, tip in MACROS:
            line = QHBoxLayout()
            name = QLabel(tr(label))
            name.setFixedWidth(88)
            name.setToolTip(tr(tip))
            line.addWidget(name)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, 100)
            slider.setValue(50)
            slider.setToolTip(tr(tip))
            line.addWidget(slider, 1)
            sound.body().addLayout(line)
            self._macros[key] = slider
        column.addWidget(sound)
        column.addStretch(1)

        tracks = Card(tr("Les pistes"))
        hint = QLabel(tr("Chaque partie sur la piste de votre choix : un "
                         "synthé du Deluge, une piste MIDI vers un appareil "
                         "extérieur, ou une piste CV vers un modulaire "
                         "(une note à la fois)."))
        hint.setProperty("role", "subtitle")
        hint.setWordWrap(True)
        tracks.body().addWidget(hint)
        table = QGridLayout()
        table.setSpacing(6)
        for index, part in enumerate(atelier.PARTS):
            check = QCheckBox(tr(part))
            check.setChecked(part != "Arpège")
            check.setToolTip(tr("Le morceau a-t-il une partie « %s » ?")
                             % tr(part))
            table.addWidget(check, index, 0)
            kinds = QComboBox()
            for kind in atelier.KINDS:
                if part in atelier.parts_for_kind(kind):
                    kinds.addItem(tr(atelier.KINDS[kind]), kind)
            kinds.setToolTip(tr("Où joue la partie « %s » : le Deluge "
                                "lui-même, ou un appareil qu'il "
                                "pilote") % tr(part))
            kinds.currentIndexChanged.connect(
                self.guard(lambda _i, p=part: self._kind_changed(p)))
            table.addWidget(kinds, index, 1)
            channel = QSpinBox()
            channel.setRange(1, 16)
            channel.setPrefix(tr("canal "))
            channel.setValue(1 + index)
            channel.setToolTip(tr("Canal MIDI (1 à 16), ou sortie CV (1 ou "
                                  "2), de la partie « %s »") % tr(part))
            table.addWidget(channel, index, 2)
            self._part_checks[part] = check
            self._part_kinds[part] = kinds
            self._part_channels[part] = channel
            self._kind_changed(part)
        tracks.body().addLayout(table)
        tracks.body().addStretch(1)

        # Trois panneaux côte à côte ; deux, puis le troisième dessous, quand
        # la place **visible** manque (mesuré à 980 px : 732 px visibles, le
        # panneau des pistes sortait de l'écran ; les trois en demandent
        # 310 + 327 + 377, marges comprises 1060).
        self._style_grid = GrilleAdaptative(
            scroll.viewport(), row, [genre_card, music_host, tracks], 3, 2,
            1080)
        scroll.setWidget(inner)
        return scroll

    def _kind_changed(self, part: str) -> None:
        kind = self._part_kinds[part].currentData()
        spin = self._part_channels[part]
        spin.setVisible(kind in ("midi", "cv"))
        spin.setMaximum(2 if kind == "cv" else 16)

    # -- onglet Sons ------------------------------------------------------ #

    def _build_sounds_tab(self) -> QWidget:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = Card(tr("Pistes"))
        self._track_list = QListWidget()
        self._track_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._track_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        hint_in_list(self._track_list,
                     "  " + tr("Composez un morceau, ou partez d'un des "
                               "vôtres."))
        self._track_list.currentRowChanged.connect(
            self.guard(lambda _r: self._track_selected(self._track_list)))
        left.body().addWidget(self._track_list, 1)
        adder = QHBoxLayout()
        self._new_kind = QComboBox()
        for kind, label in atelier.KINDS.items():
            self._new_kind.addItem(tr(label), kind)
        adder.addWidget(self._new_kind)
        self._new_part = QComboBox()
        for part in atelier.PARTS:
            self._new_part.addItem(tr(part), part)
        adder.addWidget(self._new_part)
        left.body().addLayout(adder)
        buttons = QHBoxLayout()
        self._add_track_button = tool_button(tr("Ajouter la piste"), "plus")
        self._add_track_button.clicked.connect(self.guard(self._add_track))
        buttons.addWidget(self._add_track_button)
        self._remove_track_button = tool_button(tr("Retirer"), "minus")
        self._remove_track_button.clicked.connect(
            self.guard(self._remove_track))
        buttons.addWidget(self._remove_track_button)
        left.body().addLayout(buttons)
        splitter.addWidget(left)

        right = QWidget()
        column = QVBoxLayout(right)
        column.setContentsMargins(0, 0, 0, 0)
        detail = Card(tr("Le son"))
        self._sound_title = QLabel(tr("Aucune piste choisie"))
        self._sound_title.setProperty("role", "title")
        detail.body().addWidget(self._sound_title)
        self._sound_text = QLabel("")
        self._sound_text.setWordWrap(True)
        detail.body().addWidget(self._sound_text)
        line = QHBoxLayout()
        self._listen_sound_button = tool_button(tr("Écouter le son"), "play")
        self._listen_sound_button.clicked.connect(
            self.guard(self._listen_sound))
        line.addWidget(self._listen_sound_button)
        self._other_sound_button = tool_button(tr("Autre son"), "dice")
        self._other_sound_button.clicked.connect(
            self.guard(self._other_sound))
        line.addWidget(self._other_sound_button)
        line.addStretch(1)
        detail.body().addLayout(line)
        # Deux rangées : à 980 px, quatre boutons sur une seule coupaient
        # chacun leur libellé (« Modifier le so »).
        line = QHBoxLayout()
        self._card_sound_button = tool_button(tr("Choisir sur la carte…"),
                                              "folder")
        self._card_sound_button.clicked.connect(
            self.guard(self._choose_from_card))
        line.addWidget(self._card_sound_button)
        self._edit_sound_button = tool_button(tr("Modifier le son…"),
                                              "settings")
        self._edit_sound_button.clicked.connect(self.guard(self._edit_sound))
        line.addWidget(self._edit_sound_button)
        line.addStretch(1)
        detail.body().addLayout(line)
        channel_line = QHBoxLayout()
        self._channel_label = QLabel(tr("Canal"))
        channel_line.addWidget(self._channel_label)
        self._channel = QSpinBox()
        self._channel.setRange(1, 16)
        self._channel.valueChanged.connect(
            self.guard(lambda _v: self._channel_changed()))
        channel_line.addWidget(self._channel)
        channel_line.addStretch(1)
        detail.body().addLayout(channel_line)
        column.addWidget(detail)

        variants = Card(tr("Variantes dans le style"))
        hint = QLabel(tr("Le même son, un aspect tiré à nouveau ou un "
                         "curseur poussé : jamais hors du genre. Cliquez "
                         "pour écouter, double-cliquez pour adopter."))
        hint.setProperty("role", "subtitle")
        hint.setWordWrap(True)
        variants.body().addWidget(hint)
        line = QHBoxLayout()
        self._variants_button = tool_button(tr("Proposer 8 variantes"),
                                            "copy")
        self._variants_button.clicked.connect(
            self.guard(self._make_variants))
        line.addWidget(self._variants_button)
        self._adopt_button = tool_button(tr("Adopter"), "check")
        self._adopt_button.clicked.connect(self.guard(self._adopt_variant))
        line.addWidget(self._adopt_button)
        line.addStretch(1)
        variants.body().addLayout(line)
        self._variant_list = QListWidget()
        self._variant_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        hint_in_list(self._variant_list,
                     "  " + tr("Aucune variante pour l'instant."))
        self._variant_list.currentRowChanged.connect(
            self.guard(lambda _r: self._listen_variant()))
        self._variant_list.itemDoubleClicked.connect(
            self.guard(lambda _i: self._adopt_variant()))
        self._variant_list.setMinimumHeight(140)
        variants.body().addWidget(self._variant_list, 1)
        column.addWidget(variants, 1)
        # Défilante : à 980 × 700, la description du son se chevauchait,
        # écrasée sous sa hauteur minimale.
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        right_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right_scroll.setWidget(right)
        splitter.addWidget(right_scroll)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        return splitter

    # -- onglet Clips ----------------------------------------------------- #

    def _build_clips_tab(self) -> QWidget:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = Card(tr("Pistes"))
        self._clip_tracks = QListWidget()
        self._clip_tracks.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._clip_tracks.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        hint_in_list(self._clip_tracks, "  " + tr("Aucune piste."))
        self._clip_tracks.currentRowChanged.connect(
            self.guard(lambda _r: self._track_selected(self._clip_tracks)))
        left.body().addWidget(self._clip_tracks, 1)
        splitter.addWidget(left)

        right = QWidget()
        column = QVBoxLayout(right)
        column.setContentsMargins(0, 0, 0, 0)
        clips = Card(tr("Clips de la piste"))
        self._clip_list = QListWidget()
        self._clip_list.setFlow(QListWidget.Flow.LeftToRight)
        self._clip_list.setWrapping(True)
        self._clip_list.setMaximumHeight(82)
        self._clip_list.setSpacing(4)
        hint_in_list(self._clip_list, "  " + tr("Aucun clip."))
        self._clip_list.currentRowChanged.connect(
            self.guard(lambda _r: self._clip_selected()))
        clips.body().addWidget(self._clip_list)
        self._clip_view = ClipView()
        clips.body().addWidget(self._clip_view, 1)
        self._clip_info = QLabel("")
        self._clip_info.setProperty("role", "subtitle")
        self._clip_info.setWordWrap(True)
        clips.body().addWidget(self._clip_info)

        line = QHBoxLayout()
        self._listen_clip_button = tool_button(tr("Écouter le clip"), "play")
        self._listen_clip_button.clicked.connect(
            self.guard(self._listen_clip))
        line.addWidget(self._listen_clip_button)
        self._live_button = tool_button(tr("Jouer sur le Deluge"), "midi")
        self._live_button.setCheckable(True)
        self._live_button.clicked.connect(self.guard(self._toggle_live))
        line.addWidget(self._live_button)
        self._vary_button = tool_button(tr("Varier"), "refresh")
        self._vary_menu = QMenu(self._vary_button)
        self._vary_button.setMenu(self._vary_menu)
        line.addWidget(self._vary_button)
        line.addStretch(1)
        clips.body().addLayout(line)
        # Deux rangées : à 980 px, une seule coupait chaque libellé.
        line = QHBoxLayout()
        self._new_clip_button = tool_button(tr("Nouveau clip"), "plus")
        self._new_clip_button.clicked.connect(self.guard(self._new_clip))
        line.addWidget(self._new_clip_button)
        self._clip_bars = QComboBox()
        for bars in CLIP_BARS:
            self._clip_bars.addItem(plural(bars, N_("%d mesure"),
                                           N_("%d mesures")) % bars, bars)
        self._clip_bars.setCurrentIndex(2)
        line.addWidget(self._clip_bars)
        self._delete_clip_button = tool_button(tr("Supprimer le clip"),
                                               "trash")
        self._delete_clip_button.clicked.connect(
            self.guard(self._delete_clip))
        line.addWidget(self._delete_clip_button)
        line.addStretch(1)
        clips.body().addLayout(line)
        self._live_hint = QLabel(tr(
            "Sur le Deluge, le clip joue dans le clip que suit MIDI Follow "
            "(canal A) — celui que vous avez ouvert. Machine en lecture, il "
            "part au début de sa boucle suivante, calé sur sa mesure ; en "
            "enregistrement (REC), il s'y inscrit."))
        self._live_hint.setProperty("role", "subtitle")
        self._live_hint.setWordWrap(True)
        clips.body().addWidget(self._live_hint)
        column.addWidget(clips, 1)
        splitter.addWidget(right)
        left.setMinimumWidth(210)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([260, 1000])
        return splitter

    # -- onglet Morceau --------------------------------------------------- #

    def _build_song_tab(self) -> QWidget:
        # Défilante : à 980 × 700, la grille et ses boutons demandent plus
        # que la hauteur offerte, et Qt les faisait se chevaucher.
        scroll_page = QScrollArea()
        scroll_page.setWidgetResizable(True)
        scroll_page.setFrameShape(QScrollArea.Shape.NoFrame)
        host = QWidget()
        column = QVBoxLayout(host)
        column.setContentsMargins(0, PAD, 0, 0)
        column.setSpacing(PAD)
        self._song_origin = QLabel("")
        self._song_origin.setProperty("role", "subtitle")
        self._song_origin.setWordWrap(True)
        column.addWidget(self._song_origin)

        card = Card(tr("Sections"))
        self._matrix = SectionMatrix()
        self._matrix.cellClicked.connect(self.guard(self._cell_clicked))
        self._matrix.sectionClicked.connect(
            self.guard(self._section_clicked))
        scroll = QScrollArea()
        # La matrice demande sa taille entière (``minimumSizeHint``) : la
        # zone l'étend, et défile au-delà. Sans cela, elle restait à sa
        # taille de création, une case et demie.
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(self._matrix)
        scroll.setMinimumHeight(220)
        card.body().addWidget(scroll, 1)
        hint = QLabel(tr("Un clic sur une case fait jouer à la piste le clip "
                         "suivant, puis le silence. Un clic sur une section "
                         "la choisit."))
        hint.setProperty("role", "subtitle")
        hint.setWordWrap(True)
        card.body().addWidget(hint)
        column.addWidget(card, 1)

        edit = Card(tr("La section choisie"))
        line = QHBoxLayout()
        line.addWidget(QLabel(tr("Nom")))
        self._section_name = QLineEdit()
        self._section_name.editingFinished.connect(
            self.guard(self._rename_section))
        line.addWidget(self._section_name, 1)
        line.addWidget(QLabel(tr("Mesures")))
        self._section_bars = QSpinBox()
        self._section_bars.setRange(1, 128)
        self._section_bars.valueChanged.connect(
            self.guard(lambda _v: self._resize_section()))
        line.addWidget(self._section_bars)
        edit.body().addLayout(line)
        line = QHBoxLayout()
        self._listen_section_button = tool_button(tr("Écouter la section"),
                                                  "play")
        self._listen_section_button.clicked.connect(
            self.guard(self._listen_section))
        line.addWidget(self._listen_section_button)
        self._stop_button = tool_button(tr("Arrêter"), "stop")
        self._stop_button.clicked.connect(self.guard(self._stop))
        line.addWidget(self._stop_button)
        line.addStretch(1)
        edit.body().addLayout(line)
        # Deux rangées : à 980 px, une seule coupait chaque libellé.
        line = QHBoxLayout()
        self._add_section_button = tool_button(tr("Ajouter une section"),
                                               "plus")
        self._add_section_button.clicked.connect(
            self.guard(self._add_section))
        line.addWidget(self._add_section_button)
        self._remove_section_button = tool_button(tr("Retirer la section"),
                                                  "minus")
        self._remove_section_button.clicked.connect(
            self.guard(self._remove_section))
        line.addWidget(self._remove_section_button)
        self._left_button = tool_button("", "chevron-left")
        self._left_button.setFixedWidth(34)
        self._left_button.clicked.connect(
            self.guard(lambda: self._move_section(-1)))
        line.addWidget(self._left_button)
        self._right_button = tool_button("", "chevron-right")
        self._right_button.setFixedWidth(34)
        self._right_button.clicked.connect(
            self.guard(lambda: self._move_section(1)))
        line.addWidget(self._right_button)
        self._structure_button = tool_button(tr("Structure du genre"),
                                             "grid")
        self._structure_button.clicked.connect(
            self.guard(self._default_structure))
        line.addWidget(self._structure_button)
        line.addStretch(1)
        edit.body().addLayout(line)
        self._song_summary = QLabel("")
        self._song_summary.setProperty("role", "subtitle")
        self._song_summary.setWordWrap(True)
        edit.body().addWidget(self._song_summary)
        column.addWidget(edit)
        scroll_page.setWidget(host)
        return scroll_page

    # -- état --------------------------------------------------------------- #

    def _refresh(self) -> None:
        self._fill_tracks()
        self._fill_song()
        self._update_actions()

    def _track(self):
        if self._project is None or self._uid is None:
            return None
        return self._project.track(self._uid)

    def _clip(self):
        track = self._track()
        if track is None or self._clip_key is None:
            return None
        return track.clip(self._clip_key)

    def _update_actions(self) -> None:
        project = self._project
        track = self._track()
        clip = self._clip()
        has = project is not None
        self._write_button.setEnabled(has and bool(project.sections))
        self._complete_button.setEnabled(has and bool(project.song_rel))
        for widget in (self._add_track_button, self._new_kind,
                       self._new_part, self._add_section_button,
                       self._structure_button):
            widget.setEnabled(has)
        self._remove_track_button.setEnabled(track is not None)
        synth = track is not None and track.kind == "synth"
        self._listen_sound_button.setEnabled(
            track is not None and (track.kind != "kit" or bool(track.clips)))
        self._other_sound_button.setEnabled(
            track is not None and track.kind in ("synth", "kit"))
        self._card_sound_button.setEnabled(
            track is not None and track.kind in ("synth", "kit"))
        self._edit_sound_button.setEnabled(
            synth and track.preset is not None and track.existing is None)
        self._variants_button.setEnabled(synth and track.options is not None)
        self._adopt_button.setEnabled(bool(self._variants)
                                      and self._variant_list.currentRow() >= 0)
        external = track is not None and track.kind in ("midi", "cv")
        self._channel.setVisible(external)
        self._channel_label.setVisible(external)
        for widget in (self._listen_clip_button, self._live_button,
                       self._vary_button, self._delete_clip_button):
            widget.setEnabled(clip is not None)
        self._new_clip_button.setEnabled(track is not None)
        self._clip_bars.setEnabled(track is not None)
        sections = project.sections if has else []
        current = 0 <= self._section < len(sections)
        for widget in (self._section_name, self._section_bars,
                       self._listen_section_button,
                       self._remove_section_button, self._left_button,
                       self._right_button):
            widget.setEnabled(current)

    # -- le style ---------------------------------------------------------- #

    def _pick_genre(self, key: str) -> None:
        self._genre = key
        for name, button in self._genre_buttons.items():
            button.setChecked(name == key)
        profile = genres_mod.genre(key)
        self._genre_hint.setText("%s — %d–%d BPM" % (
            tr(profile.description), profile.bpm[0], profile.bpm[1]))
        self._bpm.setValue(int(round(sum(profile.bpm) / 2.0)))
        # Les parties du genre : l'arpège quand il en a l'habitude.
        from ...core import accomp

        self._part_checks["Arpège"].setChecked(accomp.genre_styles(key)[2])

    def _roll_seed(self) -> None:
        self._seed.setValue(random.randrange(1, 1 << 20))

    def _style(self) -> atelier.Style:
        return atelier.Style(
            genre=self._genre, bpm=float(self._bpm.value()),
            root=int(self._root.currentData() or 57),
            scale=str(self._scale.currentData() or "mineur"),
            ambiance=str(self._ambiance.currentData() or ""),
            color=str(self._chord_color.currentData() or ""),
            macros={k: s.value() / 100.0 for k, s in self._macros.items()},
            seed=int(self._seed.value()))

    def _compose(self) -> None:
        """Un morceau neuf : les pistes cochées, un clip chacune, la
        structure du genre."""
        style = self._style()
        kinds = {}
        wanted = []
        for part in atelier.PARTS:
            if not self._part_checks[part].isChecked():
                continue
            wanted.append(part)
            kinds[part] = self._part_kinds[part].currentData()
        if not wanted:
            self.say(tr("Cochez au moins une partie."))
            return
        sd = self.sd if self.ctx.has_card else None
        lib = self.lib if sd is not None else None
        project = atelier.Project(style=style)
        project.progression = atelier._progression(style)
        for part in wanted:
            kind = kinds[part]
            atelier.add_track(project, kind, part,
                              channel=self._part_channels[part].value(),
                              sd=sd, lib=lib)
        project.sections = atelier.default_sections(project)
        self._set_project(project)
        self._tabs.setCurrentIndex(3)
        self.say(tr("Morceau composé : %d piste(s), %d section(s), %s. "
                    "Écoutez une section, variez les clips, puis écrivez-le "
                    "sur la carte.") % (
            len(project.tracks), len(project.sections),
            self._duration_text(project)))

    def _set_project(self, project) -> None:
        self._stop()
        self._project = project
        self._uid = project.tracks[0].uid if project.tracks else None
        self._clip_key = None
        self._section = 0
        self._forget_variants()
        self._refresh()

    # -- les pistes et les sons ------------------------------------------ #

    def _fill_tracks(self) -> None:
        project = self._project
        for widget in (self._track_list, self._clip_tracks):
            widget.blockSignals(True)
            widget.clear()
            for track in (project.tracks if project is not None else []):
                item = QListWidgetItem(QIcon(pad_dot(part_color(track.part), 12)),
                                       self._track_text(track))
                item.setData(Qt.ItemDataRole.UserRole, track.uid)
                widget.addItem(item)
            index = project.index_of(self._uid) if project is not None \
                and self._uid is not None else -1
            widget.setCurrentRow(index)
            widget.blockSignals(False)
        self._show_track()

    def _track_text(self, track) -> str:
        kind = tr(atelier.KINDS[track.kind])
        if track.kind in ("midi", "cv"):
            kind = "%s %d" % (kind, track.channel)
        sound = ""
        if track.kind == "synth" and track.preset is not None:
            sound = track.preset.name
        elif track.kind == "kit":
            sound = getattr(track.kit, "name", "") or tr("batterie "
                                                         "synthétisée")
        text = "%s · %s" % (tr(track.part), kind)
        if track.existing is not None:
            text += " · " + tr("du morceau")
        return text + (" · " + sound if sound else "")

    def _track_selected(self, source: QListWidget) -> None:
        item = source.currentItem()
        if item is None:
            return
        self._uid = item.data(Qt.ItemDataRole.UserRole)
        self._clip_key = None
        self._forget_variants()
        other =self._clip_tracks if source is self._track_list \
            else self._track_list
        other.blockSignals(True)
        other.setCurrentRow(source.currentRow())
        other.blockSignals(False)
        self._show_track()

    def _show_track(self) -> None:
        track = self._track()
        if track is None:
            self._sound_title.setText(tr("Aucune piste choisie"))
            self._sound_text.setText(tr("Composez un morceau dans l'onglet "
                                        "Style, ou partez d'un des vôtres."))
            self._fill_clips()
            self._update_actions()
            return
        self._sound_title.setText(atelier.track_label(track))
        self._sound_text.setText(self._sound_description(track))
        self._channel.blockSignals(True)
        self._channel.setMaximum(2 if track.kind == "cv" else 16)
        self._channel.setValue(track.channel)
        self._channel.blockSignals(False)
        self._fill_vary_menu(track)
        self._fill_clips()
        self._update_actions()

    def _sound_description(self, track) -> str:
        from ...core import synthgen

        if track.kind == "synth":
            if track.preset is None:
                return tr("Pas encore de son.")
            text = "%s\n%s" % (track.preset.name,
                               synthgen.describe(track.preset))
            if track.options is None:
                text += "\n" + tr("Preset de la carte : les variantes dans "
                                  "le style partent d'un son fabriqué ici.")
            if track.edited:
                text += "\n" + tr("Retouché à la main : les variantes dans le "
                                  "style gardent vos retouches.")
            return text
        if track.kind == "kit":
            kit = track.kit
            if kit is None:
                return tr("Batterie synthétisée pour l'écoute. Un kit de la "
                          "carte est bâti au moment d'écrire, ou choisissez-"
                          "en un.")
            rows = ", ".join(r.name for r in kit.rows[:12])
            return tr("%s — %d rangée(s) : %s") % (kit.name, len(kit.rows),
                                                   rows)
        if track.kind == "midi":
            return tr("Piste MIDI : le Deluge envoie ses notes sur le canal "
                      "%d, à l'appareil que vous y branchez. L'écoute de "
                      "l'ordinateur la joue avec un son du style.") \
                % track.channel
        return tr("Piste CV : une tension de hauteur et une porte sur la "
                  "sortie CV %d, vers un synthé modulaire. Une note à la "
                  "fois.") % track.channel

    def _add_track(self) -> None:
        if self._project is None:
            return
        kind = self._new_kind.currentData()
        part = self._new_part.currentData()
        if part not in atelier.parts_for_kind(kind):
            part = atelier.parts_for_kind(kind)[0]
        sd = self.sd if self.ctx.has_card else None
        track = atelier.add_track(self._project, kind, part,
                                  sd=sd, lib=self.lib if sd else None,
                                  channel=self._free_channel(kind))
        self._uid = track.uid
        self._refresh()
        self.say(tr("Piste ajoutée : %s, avec un premier clip. Placez-le "
                    "dans les sections (onglet Morceau).")
                 % atelier.track_label(track))

    def _free_channel(self, kind: str) -> int:
        used = {t.channel for t in self._project.tracks if t.kind == kind}
        for channel in range(1, 3 if kind == "cv" else 17):
            if channel not in used:
                return channel
        return 1

    def _remove_track(self) -> None:
        track = self._track()
        if track is None:
            return
        atelier.remove_track(self._project, track.uid)
        self._uid = self._project.tracks[0].uid if self._project.tracks \
            else None
        self._refresh()

    def _channel_changed(self) -> None:
        track = self._track()
        if track is None or track.kind not in ("midi", "cv"):
            return
        track.channel = int(self._channel.value())
        self._fill_tracks()

    def _other_sound(self) -> None:
        track = self._track()
        if track is None:
            return
        if track.kind == "synth":
            atelier.regenerate_sound(self._project, track.uid)
            self._forget_variants()
            self._fill_tracks()
            self._listen_sound()
        elif track.kind == "kit":
            if not self.ctx.has_card:
                self.say(tr("Un kit se bâtit avec les échantillons de la "
                            "carte."))
                return
            track.kit = atelier._build_kit(self.sd, self.lib,
                                           self._project.style,
                                           random.randrange(1 << 30))
            self._fill_tracks()

    def _choose_from_card(self) -> None:
        track = self._track()
        if track is None or track.kind not in ("synth", "kit"):
            return
        card = self.card_or_warn()
        if card is None:
            return
        kind = "kit" if track.kind == "kit" else "synth"
        rows = list(self.lib.search_presets(kind=kind, limit=5000))
        if not rows:
            self.say(tr("Aucun preset de ce type dans l'index : analysez "
                        "la carte."))
            return
        labels = ["%s  (%s)" % (r["name"], r["folder"]) for r in rows]
        choice, ok = QInputDialog.getItem(
            self, tr("Choisir sur la carte"),
            tr("Le son de la piste « %s » :") % atelier.track_label(track),
            labels, 0, False)
        if not ok or choice not in labels:
            return
        rel = rows[labels.index(choice)]["rel"]
        from ...core.model import Kit, SynthPreset

        if kind == "kit":
            track.kit = Kit.load(card.abs(rel))
        else:
            track.preset = SynthPreset.load(card.abs(rel))
            track.options = None
            track.edited = False
            self._forget_variants()
        self._fill_tracks()
        self.say(tr("Son choisi : %s.") % rel)

    def _edit_sound(self) -> None:
        """Ouvre l'éditeur sur le son de la piste ; « Garder ce son » le lui
        donne, « Annuler » ne touche à rien."""
        track = self._track()
        if track is None or track.kind != "synth" or track.preset is None:
            return
        if track.existing is not None:
            self.say(tr("Le son d'une piste du morceau d'origine lui "
                        "appartient : il ne se modifie pas ici."))
            return
        from ..theme import PAGE_COLORS
        from ..widgets.soundeditor import SoundEditorDialog

        dialog = SoundEditorDialog(
            self.ctx, track.preset.sound,
            title=tr("Modifier le son — %s") % atelier.track_label(track),
            color=PAGE_COLORS.get("Atelier", PAGE_COLORS.get("Generator")),
            parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        changes = dialog.changes()
        atelier.edit_sound(self._project, track.uid, dialog.edited_sound())
        # Les variantes proposées avant ne portent pas ces retouches.
        self._forget_variants()
        self._fill_tracks()
        if changes:
            self.say(tr("Son retouché : %s.") % " · ".join(changes[:3]))
        else:
            self.say(tr("Le son n'a pas changé."))

    def _listen_sound(self) -> None:
        """Le son de la piste : une phrase pour un synthé, le premier clip
        pour une batterie (un kit s'entend en jouant)."""
        track = self._track()
        if track is None:
            return
        if track.kind == "kit":
            if track.clips:
                self._render_clip(track, track.clips[0].key)
            return
        sound = atelier.listen_sounds(self._project).get(
            atelier._part_key(track))
        if sound is None or self.audition(sound):
            return
        from ...core import render

        self.run(render.render_sound, sound, 48, 2.0, 44100,
                 on_result=self.guard(self._play_audio),
                 title=tr("Rendu du son"))

    def _make_variants(self) -> None:
        track = self._track()
        if track is None or track.options is None:
            return
        self._variants = atelier.sound_variations(
            self._project, track.uid, 8, seed=random.randrange(1 << 30))
        self._variant_list.blockSignals(True)
        self._variant_list.clear()
        for variant in self._variants:
            self._variant_list.addItem("%s — %s" % (tr(variant.label),
                                                    variant.preset.name))
        self._variant_list.blockSignals(False)
        self._update_actions()
        if track.edited:
            self.say(tr("%d variantes du son retouché, toutes dans le style "
                        "et avec vos retouches. Cliquez pour écouter.")
                     % len(self._variants))
            return
        self.say(tr("%d variantes du son, toutes dans le style. Cliquez "
                    "pour écouter.") % len(self._variants))

    def _forget_variants(self) -> None:
        """Les variantes proposées ne valent que pour le son qui les a
        données."""
        self._variants = []
        self._variant_list.clear()
        hint_in_list(self._variant_list,
                     "  " + tr("Aucune variante pour l'instant."))

    def _listen_variant(self) -> None:
        row = self._variant_list.currentRow()
        self._update_actions()
        if not 0 <= row < len(self._variants):
            return
        sound = self._variants[row].preset.sound
        if self.audition(sound):
            return
        from ...core import render

        self.run(render.render_sound, sound, 48, 2.0, 44100,
                 on_result=self.guard(self._play_audio),
                 title=tr("Rendu du son"))

    def _adopt_variant(self) -> None:
        row = self._variant_list.currentRow()
        track = self._track()
        if track is None or not 0 <= row < len(self._variants):
            return
        choice = self._variants[row]
        atelier.adopt_sound(self._project, track.uid, choice)
        self._fill_tracks()
        self.say(tr("La piste prend le son « %s » (%s).") % (
            choice.preset.name, tr(choice.label)))

    # -- les clips ----------------------------------------------------------- #

    def _fill_vary_menu(self, track) -> None:
        self._vary_menu.clear()
        table = variation.DRUMS if track.is_drums else variation.MELODIC
        for key, description in table.items():
            action = self._vary_menu.addAction(
                "%s — %s" % (tr(key).capitalize(), tr(description)))
            action.triggered.connect(
                self.guard(lambda _c=False, k=key: self._vary(k)))

    def _fill_clips(self) -> None:
        track = self._track()
        self._clip_list.blockSignals(True)
        self._clip_list.clear()
        if track is not None:
            for clip in track.clips:
                origin = tr(clip.origin)
                if clip.parent:
                    origin = tr("%s de %s") % (origin, clip.parent)
                item = QListWidgetItem(QIcon(pad_dot(part_color(track.part), 12)),
                                       "%s · %s · %s" % (
                                           clip.key, origin,
                                           tr("%d mes.") % clip.bars))
                item.setData(Qt.ItemDataRole.UserRole, clip.key)
                self._clip_list.addItem(item)
            if self._clip_key is None and track.clips:
                self._clip_key = track.clips[0].key
            keys = [c.key for c in track.clips]
            self._clip_list.setCurrentRow(keys.index(self._clip_key)
                                          if self._clip_key in keys else -1)
        self._clip_list.blockSignals(False)
        self._show_clip()

    def _clip_selected(self) -> None:
        item = self._clip_list.currentItem()
        self._clip_key = item.data(Qt.ItemDataRole.UserRole) if item \
            else None
        self._show_clip()

    def _show_clip(self) -> None:
        track = self._track()
        clip = self._clip()
        if clip is None:
            self._clip_view.set_clip(None)
            self._clip_info.setText("")
        else:
            rows = atelier.drum_rows(track) if track.is_drums else None
            self._clip_view.set_clip(clip, part_color(track.part), rows)
            used = [s.name for s in self._project.sections
                    if s.cells.get(track.uid) == clip.key]
            text = tr("%d note(s) sur %d mesure(s).") % (clip.note_count,
                                                         clip.bars)
            if clip.existing is not None:
                text += " " + tr("Déjà dans le morceau d'origine.")
            if used:
                text += " " + tr("Joué dans : %s.") % ", ".join(
                    tr(n) for n in used)
            else:
                text += " " + tr("Dans aucune section pour l'instant.")
            self._clip_info.setText(text)
        self._update_actions()

    def _vary(self, how: str) -> None:
        track = self._track()
        clip = self._clip()
        if track is None or clip is None:
            return
        if not clip.note_count:
            self.say(tr("Un clip vide ne se varie pas."))
            return
        new = atelier.vary_clip(self._project, track.uid, clip.key, how)
        self._clip_key = new.key
        self._fill_clips()
        self.say(tr("Clip %s : « %s » de %s. Écoutez-le, puis placez-le dans "
                    "une section.") % (new.key, tr(how), clip.key))

    def _new_clip(self) -> None:
        track = self._track()
        if track is None:
            return
        bars = int(self._clip_bars.currentData() or 4)
        clip = atelier.generate_clip(self._project, track.uid, bars=bars,
                                     seed=random.randrange(1 << 30))
        self._clip_key = clip.key
        self._fill_clips()

    def _delete_clip(self) -> None:
        track = self._track()
        clip = self._clip()
        if track is None or clip is None:
            return
        atelier.remove_clip(self._project, track.uid, clip.key)
        self._clip_key = None
        self._fill_clips()
        self._fill_song()

    def _listen_clip(self) -> None:
        track = self._track()
        clip = self._clip()
        if track is not None and clip is not None:
            self._render_clip(track, clip.key)

    def _render_clip(self, track, key: str) -> None:
        parts, drums, _bars = atelier.clip_parts(self._project, track.uid,
                                                 key)
        self._render(parts, drums, tr("Rendu du clip"))

    # -- jouer sur le Deluge --------------------------------------------- #

    def _toggle_live(self) -> None:
        link = getattr(self.ctx, "link", None)
        if not self._live_button.isChecked():
            if link is not None:
                link.stop_playing()
            self._live_timer.stop()
            self.say(tr("Le clip ne joue plus sur le Deluge."))
            return
        track = self._track()
        clip = self._clip()
        if link is None or not link.is_connected:
            self._live_button.setChecked(False)
            self.say(tr("Le Deluge n'est pas connecté : branchez-le en USB, "
                        "puis connectez-le depuis les réglages."))
            return
        if track is None or clip is None:
            self._live_button.setChecked(False)
            return
        notes, steps = atelier.live_notes(self._project, track.uid, clip.key,
                                          kit_root=self._kit_root())
        running = link.transport.snapshot()[0]
        if not link.play_synced(notes, steps, loops=0,
                                bpm=self._project.style.tempo()):
            self._live_button.setChecked(False)
            self.say(tr("Le clip ne part pas sur le Deluge : rien à jouer."))
            return
        self._live_timer.start()
        if running:
            self.say(tr("Le clip part au début de sa prochaine boucle, calé "
                        "sur la mesure du Deluge (canal %d).") % link.channel)
        else:
            self.say(tr("Le Deluge est à l'arrêt : le clip joue au tempo du "
                        "morceau (canal %d). Lancez la lecture sur la "
                        "machine pour le caler sur sa mesure.")
                     % link.channel)

    def _watch_live(self) -> None:
        link = getattr(self.ctx, "link", None)
        if link is None or not link.is_playing:
            self._live_timer.stop()
            if self._live_button.isChecked():
                self._live_button.setChecked(False)
                self.say(tr("Le clip s'est arrêté sur le Deluge."))

    def _kit_root(self) -> int:
        try:
            from ...core import midifollow

            settings = midifollow.read_settings(self.sd) if self.sd else None
            return int(settings.kit_root_note) if settings else 36
        except Exception:            # noqa: BLE001 - l'usine : 36
            return 36

    # -- le morceau ------------------------------------------------------- #

    def _fill_song(self) -> None:
        project = self._project
        if project is None:
            self._matrix.set_project([], [])
            self._song_origin.setText(tr(
                "Composez un morceau (onglet Style, puis « Composer »), ou "
                "partez d'un des vôtres : ses pistes et ses clips deviennent "
                "ceux de l'atelier."))
            self._song_summary.setText("")
            return
        tracks = [(t.uid, atelier.track_label(t), part_color(t.part))
                  for t in project.tracks]
        sections = [(tr(s.name), s.bars, dict(s.cells))
                    for s in project.sections]
        existing = {(t.uid, c.key): True for t in project.tracks
                    for c in t.clips if c.existing is not None}
        if self._section >= len(project.sections):
            self._section = max(0, len(project.sections) - 1)
        self._matrix.set_project(tracks, sections, self._section, existing)
        if project.song_rel:
            self._song_origin.setText(tr(
                "Projet tiré de « %s » : ses sections gardent leurs clips. "
                "« Compléter le morceau » écrit une nouvelle version qui le "
                "contient tel quel, plus vos pistes, vos clips et vos "
                "sections neuves.") % project.song_name)
        else:
            self._song_origin.setText(tr(
                "Un morceau neuf, en %s, %s. « Écrire le morceau » en fait "
                "un morceau du Deluge, sections et arrangement compris.") % (
                genres_mod.genre(project.style.genre).label,
                theory.note_to_name(project.style.root, with_octave=False)
                + " " + tr(project.style.scale)))
        self._show_section()

    def _duration_text(self, project) -> str:
        from ...core.units import human_duration

        seconds = project.bars * 4 * 60.0 / project.style.tempo()
        return tr("%d mesures, %s") % (project.bars, human_duration(seconds))

    def _show_section(self) -> None:
        project = self._project
        if project is None or not project.sections:
            self._section_name.setText("")
            self._song_summary.setText("")
            self._update_actions()
            return
        section = project.sections[self._section]
        self._section_name.blockSignals(True)
        self._section_name.setText(tr(section.name))
        self._section_name.blockSignals(False)
        self._section_bars.blockSignals(True)
        self._section_bars.setValue(int(section.bars))
        self._section_bars.blockSignals(False)
        self._song_summary.setText(tr("%d section(s) — %s, à %g BPM.") % (
            len(project.sections), self._duration_text(project),
            project.style.tempo()))
        self._update_actions()

    def _section_clicked(self, index: int) -> None:
        self._section = int(index)
        self._matrix.set_current(self._section)
        self._show_section()

    def _cell_clicked(self, index: int, uid: int) -> None:
        project = self._project
        track = project.track(uid) if project else None
        if track is None:
            return
        self._section = int(index)
        section = project.sections[self._section]
        keys = [c.key for c in track.clips] + [None]
        current = section.cells.get(uid)
        following = keys[(keys.index(current) + 1) % len(keys)] \
            if current in keys else keys[0]
        atelier.set_cell(project, self._section, uid, following)
        self._fill_song()

    def _rename_section(self) -> None:
        project = self._project
        if project is None or not project.sections:
            return
        text = self._section_name.text().strip()
        if text:
            section = project.sections[self._section]
            if text != tr(section.name):
                section.name = text
                from ...core import sketch

                section.kind = sketch.section_kind(text)
            self._fill_song()

    def _resize_section(self) -> None:
        project = self._project
        if project is None or not project.sections:
            return
        project.sections[self._section].bars = int(self._section_bars.value())
        self._fill_song()

    def _add_section(self) -> None:
        if self._project is None:
            return
        name, ok = QInputDialog.getText(
            self, tr("Ajouter une section"),
            tr("Nom de la section (elle reprend les clips de la section "
               "choisie) :"), QLineEdit.EchoMode.Normal, tr("Refrain"))
        if not ok or not name.strip():
            return
        index = self._section + 1 if self._project.sections else 0
        atelier.add_section(self._project, name.strip(), bars=16,
                            index=index)
        if self._project.sections and index > 0:
            # Reprend les clips de la section choisie, pas de la précédente
            # dans la liste : c'est celle qu'on regarde.
            self._project.sections[index].cells = dict(
                self._project.sections[self._section].cells)
        self._section = index
        self._fill_song()

    def _remove_section(self) -> None:
        if self._project is None:
            return
        atelier.remove_section(self._project, self._section)
        self._section = max(0, self._section - 1)
        self._fill_song()

    def _move_section(self, offset: int) -> None:
        if self._project is None:
            return
        self._section = atelier.move_section(self._project, self._section,
                                             offset)
        self._fill_song()

    def _default_structure(self) -> None:
        if self._project is None:
            return
        if self._project.song_rel:
            kept = [s for s in self._project.sections
                    if s.existing is not None]
            self._project.sections = kept + [
                s for s in atelier.default_sections(self._project)]
        else:
            self._project.sections = atelier.default_sections(self._project)
        self._section = 0
        self._refresh()
        self.say(tr("Structure du genre : %d sections, les variations "
                    "qu'elles appellent ajoutées aux pistes.")
                 % len(self._project.sections))

    def _listen_section(self) -> None:
        if self._project is None:
            return
        parts, drums, bars = atelier.section_parts(self._project,
                                                   self._section)
        if not parts and drums is None:
            self.say(tr("Cette section ne joue aucun clip."))
            return
        self._render(parts, drums, tr("Rendu de la section"))
        self.say(tr("Écoute des %d premières mesures de « %s ».")
                 % (bars, tr(self._project.sections[self._section].name)))

    # -- écouter --------------------------------------------------------- #

    def _render(self, parts: dict, drums, title: str) -> None:
        project = self._project
        sounds = atelier.listen_sounds(project)
        sounds = {k: copy.deepcopy(v) for k, v in sounds.items() if k in parts}
        kit = next((t.kit for t in project.tracks
                    if t.is_drums and t.kit is not None), None)
        self.run(_render_mix, parts, sounds, drums, project.style.tempo(),
                 kit, self.sd if self.ctx.has_card else None,
                 on_result=self.guard(self._play_audio),
                 on_error=self.guard(
                     lambda m: self.say(tr("Rendu impossible : %s") % m)),
                 title=title)

    def _play_audio(self, audio) -> None:
        if audio is None or self.player is None:
            self.say(tr("Aucune sortie audio disponible."))
            return
        try:
            self.player.set_volume(self.ctx.settings.preview_volume)
            self.player.play_array(audio, 44100)
        except Exception as exc:     # noqa: BLE001
            log.debug("lecture impossible : %s", exc)
            self.say(tr("Lecture impossible : %s") % exc)

    def _stop(self) -> None:
        if self.player is not None:
            try:
                self.player.stop()
            except Exception as exc:  # noqa: BLE001
                log.debug("arrêt impossible : %s", exc)
        link = getattr(self.ctx, "link", None)
        if link is not None and self._live_button.isChecked():
            link.stop_playing()
            self._live_button.setChecked(False)

    # -- la carte -------------------------------------------------------- #

    def _import_song(self) -> None:
        card = self.card_or_warn()
        if card is None:
            return
        rows = list(self.lib.search_songs(""))
        if not rows:
            self.say(tr("Aucun morceau dans l'index : analysez la carte."))
            return
        recent = self._recent_songs()
        rows.sort(key=lambda r: (r["rel"] not in recent,
                                 recent.get(r["rel"], 0) * -1,
                                 str(r["name"]).casefold()))
        labels = []
        for row in rows:
            label = str(row["name"])
            if row["rel"] in recent:
                label += "  — " + tr("reçu du Deluge")
            labels.append(label)
        choice, ok = QInputDialog.getItem(
            self, tr("Partir d'un morceau"),
            tr("Le morceau sur lequel vous travaillez (les derniers reçus du "
               "Deluge en tête) :"), labels, 0, False)
        if not ok or choice not in labels:
            return
        rel = rows[labels.index(choice)]["rel"]
        self.open_song(rel)

    def open_song(self, rel: str) -> bool:
        """Ouvre dans l'atelier le morceau ``rel`` de la carte."""
        from ...core.model import Song

        card = self.sd
        if card is None:
            return False
        song = Song.load(card.abs(rel))
        project = atelier.from_song(song, card)
        project.song_rel = rel
        project.style.genre = self._genre
        self._set_project(project)
        self._tabs.setCurrentIndex(3)
        self.say(tr("« %s » est dans l'atelier : %d piste(s), %d clip(s), "
                    "%d section(s). Variez ses clips, ajoutez des pistes et "
                    "des sections, puis complétez-le.") % (
            song.name, len(project.tracks),
            sum(len(t.clips) for t in project.tracks),
            len(project.sections)))
        return True

    def _recent_songs(self) -> dict:
        """Les morceaux reçus du Deluge depuis peu : ``{chemin: instant}``.

        Ce que l'utilisateur vient d'enregistrer sur la machine est très
        probablement ce sur quoi il travaille."""
        try:
            from ...core import cardsync

            if self.sd is None:
                return {}
            out = {}
            for when, rel in cardsync.recent_arrivals(self.sd.root, limit=30):
                if str(rel).upper().startswith("SONGS/"):
                    out.setdefault(rel, when)
            return out
        except Exception as exc:     # noqa: BLE001 - un tri, rien de plus
            log.debug("arrivées récentes illisibles : %s", exc)
            return {}

    def focus_on(self, hint: str) -> None:
        """``Atelier#SONGS/Cool1.XML`` ouvre ce morceau dans l'atelier."""
        text = str(hint or "")
        if text.upper().startswith("SONGS/"):
            self._ensure_built()
            try:
                self.open_song(text)
            except Exception as exc:  # noqa: BLE001
                log.debug("morceau non ouvert dans l'atelier : %s", exc)
            return
        super().focus_on(hint)

    def _write_song(self) -> None:
        project = self._project
        if project is None:
            return
        name = project.song_name or tr("ATELIER %s") % genres_mod.genre(
            project.style.genre).label.upper()
        self.write_song(lambda card: atelier.to_song_spec(
            project, name, sd=card, lib=self.lib), name)

    def _complete(self) -> None:
        project = self._project
        if project is None or not project.song_rel:
            return
        from ..songexport import export_insert

        rel = export_insert(self, self.ctx,
                            lambda card: atelier.insertion_plan(
                                project, card, self.lib)[0], self.say)
        if rel:
            self.songWritten.emit(rel)


def _render_mix(parts: dict, sounds: dict, drums, bpm: float, kit=None,
                sd=None, should_stop=None):
    """Les parties et la batterie mêlées (fil séparé) ; ``None`` si l'arrêt
    est demandé en cours de rendu."""
    from ...core import render

    tonal = render.render_parts(parts, sounds, bpm=bpm, sr=44100,
                                should_stop=should_stop) if parts else None
    if should_stop is not None and should_stop():
        return None
    beat = None
    if drums is not None and drums.tracks:
        beat = render.render_pattern(drums, bpm=bpm, sr=44100, kit=kit, sd=sd)
    if tonal is None:
        return beat
    if beat is None:
        return tonal
    return render.mix(tonal, beat, levels=(1.0, 0.85))
