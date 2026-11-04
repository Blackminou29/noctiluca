# -*- coding: utf-8 -*-
"""Page « Atelier » : un morceau en cinq étapes, du style au Deluge.

C'est le parcours de création de l'application. Une barre d'étapes le
montre en entier, et chaque étape ne fait qu'une chose :

1. **Style** — le genre, le tempo, la tonalité, les parties ; puis
   « Composer » : tout le morceau est prêt en une seconde ;
2. **Sons** — le son de chaque piste, ses variantes **dans le style**, un
   kit dont on change une rangée ;
3. **Clips** — ce que joue chaque piste : écouter, varier, dessiner la
   batterie à la souris, la faire jouer **sur le Deluge** ;
4. **Structure** — la grille des sections : quel clip chaque piste joue
   dans chacune ;
5. **Deluge** — écrire le morceau sur la carte, ou compléter celui d'où
   l'on est parti, sans rien en réécrire.

« Étape suivante » mène de l'une à l'autre ; toutes restent ouvertes, dans
le désordre si l'on veut. Le niveau « avancé » ajoute les réglages fins —
graine, couleur des accords, caractère des sons, nature et canal des
pistes, groove, rangées euclidiennes, jeu des accords et de la basse,
exports MIDI. Ce qui vivait dans la Boîte à outils (rythme, progression,
arrangement) est ici, appliqué au morceau en cours.

Le cœur est dans :mod:`delugeapp.core.atelier` ; la page ne fait que le
montrer et le faire jouer. Tout rendu audio part dans un fil.
"""

from __future__ import annotations

import copy
import logging
import random

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...core import atelier, genres as genres_mod, rhythm, theory, variation
from ...i18n import N_, plural, tr
from ..theme import PAD, PAD_CYAN
from ..widgets.atelierviews import (STEP_COLORS, ClipView, SectionMatrix,
                                    StepBar, part_color)
from ..widgets.common import (Card, EmptyState, GrilleAdaptative,
                              hint_in_list, pad_dot)
from ..widgets.piano import PianoKeys
from .base import Page, avance, tool_button
# Les curseurs du style : ceux du Générateur, avec leurs explications.
from .generator import MACROS

log = logging.getLogger(__name__)

#: Gammes proposées : celles qu'on joue en musique électronique d'abord.
SCALES = ("mineur", "majeur", "dorien", "phrygien", "mixolydien", "lydien",
          "mineur harmonique", "pentatonique mineure",
          "pentatonique majeure", "blues")

#: Longueurs proposées pour un clip neuf, en mesures.
CLIP_BARS = (1, 2, 4, 8)

#: Les rangées qu'une batterie de l'atelier montre toujours, même sans coup :
#: de quoi ajouter un clap ou un charleston à la souris.
BASIC_ROWS = ("Kick", "Snare", "Clap", "HatC", "HatO")

#: Les étapes, dans l'ordre du travail : leur nom, et ce qu'on y fait.
STEPS: tuple[tuple[str, str], ...] = (
    (N_("Style"),
     N_("Choisissez un genre, un tempo et une tonalité, puis composez : tout "
        "le morceau est prêt en une seconde, et rien n'est écrit sur la "
        "carte.")),
    (N_("Sons"),
     N_("Écoutez le son de chaque piste. « Autre son » en tire un autre dans "
        "le même style ; les variantes le nuancent.")),
    (N_("Clips"),
     N_("Ce que joue chaque piste : écoutez ses clips, variez-les, allumez "
        "ou éteignez les coups de la batterie d'un clic.")),
    (N_("Structure"),
     N_("Les sections du morceau, dans l'ordre : un clic sur une case change "
        "le clip que la piste y joue.")),
    (N_("Deluge"),
     N_("Écrivez le morceau sur la carte : il part sur le Deluge par le "
        "câble. Parti d'un morceau de la carte, complétez-le sans y "
        "toucher.")),
)

#: Index des étapes, pour lire le code.
STYLE, SONS, CLIPS, STRUCTURE, DELUGE = range(5)


class AtelierPage(Page):
    """L'atelier du compositeur."""

    TITLE = N_("Atelier")
    ICON = "atelier"
    EMPTY_DETAIL = N_("L'atelier compose sans carte ; il lui faut la carte "
                      "pour écrire le morceau, et ses échantillons pour "
                      "bâtir un kit.")
    #: On compose et on écoute sans carte : seule l'écriture en a besoin.
    NEEDS_CARD = False

    #: Ouvrir « Deluge en direct ».
    liveRequested = pyqtSignal()
    #: Échanger tout de suite avec le Deluge branché.
    syncRequested = pyqtSignal()
    #: Aller sur une autre page : le morceau écrit, dans Morceaux.
    navigateRequested = pyqtSignal(str)

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
        #: Le style a changé depuis la composition : « Recomposer ».
        self._style_dirty = False
        #: La progression proposée avant de composer ; ``None`` : celle du
        #: style.
        self._chords: list[dict] | None = None
        self._chords_seed = 0
        self._chord_rolls = 0
        #: Sons et kit arrivés d'une autre page avant qu'un morceau existe :
        #: partie -> (preset, réglages du générateur, retouché), et le kit.
        self._pending_sounds: dict[str, tuple] = {}
        self._pending_kit = None
        #: Échantillons déjà essayés par rangée du kit, pour « Autre son ».
        self._kit_tried: dict[int, set] = {}
        self._kit_rolls = 0
        #: La dernière étape atteinte, pour la barre d'étapes.
        self._reached = 0
        self._last_written = ""
        self._live_timer = QTimer(self)
        self._live_timer.setInterval(250)
        self._live_timer.timeout.connect(self.guard(self._watch_live))

    # -- construction ------------------------------------------------------- #

    def build(self) -> None:
        outer = QVBoxLayout(self.content())
        outer.setContentsMargins(PAD, PAD, PAD, PAD)
        outer.setSpacing(8)

        header, actions = self.header(
            tr("Atelier"), tr("Un morceau en cinq étapes, du style au Deluge"))
        outer.addWidget(header)

        self._import_button = tool_button(tr("Ouvrir un morceau du Deluge…"),
                                          "import")
        self._import_button.clicked.connect(self.guard(self._import_song))
        actions.addWidget(self._import_button)

        self._listen_song_button = tool_button(tr("Écouter un extrait"),
                                               "play", color=self.color)
        self._listen_song_button.clicked.connect(
            self.guard(self._listen_extract))
        actions.addWidget(self._listen_song_button)

        self._stop_button = tool_button(tr("Arrêter"), "stop")
        self._stop_button.clicked.connect(self.guard(self._stop))
        actions.addWidget(self._stop_button)

        self._steps_bar = StepBar([tr(titre) for titre, _ in STEPS])
        self._steps_bar.stepClicked.connect(self.guard(self.show_step))
        for (titre, aide), bouton in zip(STEPS, self._steps_bar.buttons):
            bouton.setToolTip("%s — %s" % (tr(titre), tr(aide)))
        outer.addWidget(self._steps_bar)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(PAD)
        self._track_column = self._build_track_column()
        body.addWidget(self._track_column)

        # Les étapes sont les onglets d'un ``QTabWidget`` dont la barre est
        # cachée : la barre d'étapes la remplace, et les raccourcis
        # ``Atelier#Clips`` trouvent toujours leur onglet par son nom.
        self._tabs = QTabWidget()
        self._tabs.tabBar().hide()
        self._tabs.setDocumentMode(True)
        self._tabs.addTab(self._build_style_step(), tr("Style"))
        self._tabs.addTab(self._wrap_step(self._build_sounds_step(), SONS),
                          tr("Sons"))
        self._tabs.addTab(self._wrap_step(self._build_clips_step(), CLIPS),
                          tr("Clips"))
        self._tabs.addTab(self._wrap_step(self._build_song_step(), STRUCTURE),
                          tr("Structure"))
        self._tabs.addTab(self._wrap_step(self._build_deluge_step(), DELUGE),
                          tr("Deluge"))
        self._tabs.currentChanged.connect(self.guard(self._step_changed))
        body.addWidget(self._tabs, 1)
        outer.addLayout(body, 1)

        outer.addWidget(self._build_footer())
        self._pick_genre("techno")
        self._show_scale()
        self._step_changed(STYLE)
        self._update_actions()

    def _wrap_step(self, content: QWidget, step: int) -> QWidget:
        """Une étape, et ce qu'elle montre tant qu'il n'y a pas de morceau :
        un mot sur ce qui manque, et les deux façons de commencer."""
        pile = QStackedWidget()
        vide = EmptyState(tr("Pas encore de morceau"), "atelier",
                          tr("Composer un morceau"),
                          detail=tr("Choisissez un style à l'étape 1 et "
                                    "composez, ou ouvrez un morceau "
                                    "enregistré sur le Deluge."),
                          color=STEP_COLORS[step],
                          action2=tr("Ouvrir un morceau du Deluge…"))
        vide.actionClicked.connect(self.guard(lambda: self.show_step(STYLE)))
        vide.action2Clicked.connect(self.guard(self._import_song))
        pile.addWidget(content)
        pile.addWidget(vide)
        pile.setProperty("etape", step)
        return pile

    # -- la colonne des pistes -------------------------------------------- #

    def _build_track_column(self) -> QWidget:
        """Les pistes du morceau, communes aux étapes Sons et Clips."""
        card = Card(tr("Pistes"))
        card.setMinimumWidth(220)
        card.setMaximumWidth(320)
        self._track_list = QListWidget()
        self._track_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._track_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        hint_in_list(self._track_list,
                     "  " + tr("Composez un morceau, ou partez d'un des "
                               "vôtres."))
        self._track_list.currentRowChanged.connect(
            self.guard(lambda _r: self._track_selected()))
        card.body().addWidget(self._track_list, 1)
        # Les étapes Sons et Clips montrent la même liste : un seul widget,
        # sous ses deux noms d'autrefois.
        self._clip_tracks = self._track_list

        adder = QHBoxLayout()
        adder.setSpacing(6)
        self._new_part = QComboBox()
        for part in atelier.PARTS:
            self._new_part.addItem(tr(part), part)
        adder.addWidget(self._new_part, 1)
        self._new_kind = avance(QComboBox())
        for kind, label in atelier.KINDS.items():
            self._new_kind.addItem(tr(label), kind)
        self._new_kind.setCurrentIndex(self._new_kind.findData("synth"))
        adder.addWidget(self._new_kind, 1)
        card.body().addLayout(adder)
        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        # « Ajouter » et non « Ajouter la piste » : la liste juste au-dessus
        # dit laquelle, et la colonne n'a que 220 px à 980 de large.
        self._add_track_button = tool_button(tr("Ajouter"), "plus")
        self._add_track_button.clicked.connect(self.guard(self._add_track))
        buttons.addWidget(self._add_track_button)
        self._remove_track_button = tool_button(tr("Retirer"), "minus")
        self._remove_track_button.clicked.connect(
            self.guard(self._remove_track))
        buttons.addWidget(self._remove_track_button)
        card.body().addLayout(buttons)
        return card

    # -- étape 1 : le style ----------------------------------------------- #

    def _build_style_step(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        inner = QWidget()
        row = QGridLayout(inner)
        row.setContentsMargins(0, 0, 0, 0)
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
                self.guard(lambda _c=False, k=key: self._genre_clicked(k)))
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
        music = Card(tr("Tempo et tonalité"))
        form = QGridLayout()
        form.setSpacing(6)
        form.addWidget(QLabel(tr("Tempo")), 0, 0)
        self._bpm = QSpinBox()
        self._bpm.setRange(40, 250)
        self._bpm.setSuffix(" BPM")
        self._bpm.valueChanged.connect(self.guard(lambda _v:
                                                  self._tempo_changed()))
        form.addWidget(self._bpm, 0, 1)
        form.addWidget(QLabel(tr("Tonique")), 1, 0)
        self._root = QComboBox()
        for pc in range(12):
            self._root.addItem(theory.note_to_name(48 + pc,
                                                   with_octave=False), 48 + pc)
        self._root.setCurrentIndex(9)                    # la
        self._root.currentIndexChanged.connect(
            self.guard(lambda _i: self._key_changed()))
        form.addWidget(self._root, 1, 1)
        form.addWidget(QLabel(tr("Gamme")), 2, 0)
        self._scale = QComboBox()
        for name in SCALES:
            if name in theory.SCALES:
                self._scale.addItem(tr(name), name)
        self._scale.currentIndexChanged.connect(
            self.guard(lambda _i: self._key_changed()))
        form.addWidget(self._scale, 2, 1)
        form.addWidget(QLabel(tr("Ambiance")), 3, 0)
        self._ambiance = QComboBox()
        self._ambiance.addItem(tr("Celle du genre"), "")
        for name in theory.progression_names():
            self._ambiance.addItem(tr(name), name)
        self._ambiance.currentIndexChanged.connect(
            self.guard(lambda _i: self._harmony_changed()))
        form.addWidget(self._ambiance, 3, 1)
        couleur = avance(QLabel(tr("Couleur")))
        form.addWidget(couleur, 4, 0)
        self._chord_color = avance(QComboBox())
        self._chord_color.addItem(tr("Celle de l'ambiance"), "")
        for name in theory.CHORD_COLORS:
            self._chord_color.addItem(tr(name), name)
        self._chord_color.currentIndexChanged.connect(
            self.guard(lambda _i: self._harmony_changed()))
        form.addWidget(self._chord_color, 4, 1)
        graine = avance(QLabel(tr("Graine")))
        form.addWidget(graine, 5, 0)
        seed_row = QHBoxLayout()
        seed_row.setContentsMargins(0, 0, 0, 0)
        self._seed = QSpinBox()
        self._seed.setRange(0, 1 << 30)
        self._seed.setValue(1)
        self._seed.valueChanged.connect(self.guard(lambda _v:
                                                   self._harmony_changed()))
        seed_row.addWidget(self._seed, 1)
        self._dice = tool_button("", "dice")
        self._dice.setFixedWidth(34)
        self._dice.clicked.connect(self.guard(self._roll_seed))
        seed_row.addWidget(self._dice)
        holder = avance(QWidget())
        holder.setLayout(seed_row)
        form.addWidget(holder, 5, 1)
        music.body().addLayout(form)
        # La gamme sur un clavier : ce que « la mineur » veut dire, en
        # notes qu'on voit.
        self._piano = PianoKeys(48, 72)
        self._piano.setMinimumHeight(54)
        self._piano.setMaximumHeight(70)
        music.body().addWidget(self._piano)
        self._scale_notes = QLabel("")
        self._scale_notes.setProperty("role", "subtitle")
        self._scale_notes.setWordWrap(True)
        music.body().addWidget(self._scale_notes)
        column.addWidget(music)
        column.addWidget(self._build_chords_card())
        column.addStretch(1)

        parts_host = QWidget()
        parts_column = QVBoxLayout(parts_host)
        parts_column.setContentsMargins(0, 0, 0, 0)
        parts_column.setSpacing(PAD)
        tracks = Card(tr("Les parties"))
        hint = QLabel(tr("Ce que le morceau contiendra : une piste par "
                         "partie cochée."))
        hint.setProperty("role", "subtitle")
        hint.setWordWrap(True)
        tracks.body().addWidget(hint)
        detail = avance(QLabel(tr(
            "Chaque partie sur la piste de votre choix : un synthé du "
            "Deluge, une piste MIDI vers un appareil extérieur, ou une piste "
            "CV vers un modulaire (une note à la fois).")))
        detail.setProperty("role", "subtitle")
        detail.setWordWrap(True)
        tracks.body().addWidget(detail)
        table = QGridLayout()
        table.setSpacing(6)
        for index, part in enumerate(atelier.PARTS):
            check = QCheckBox(tr(part))
            check.setChecked(part != "Arpège")
            check.setToolTip(tr("Le morceau a-t-il une partie « %s » ?")
                             % tr(part))
            check.toggled.connect(self.guard(lambda _c: self._style_touched()))
            table.addWidget(check, index, 0)
            kinds = avance(QComboBox())
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
        self._pending_note = QLabel("")
        self._pending_note.setProperty("role", "subtitle")
        self._pending_note.setWordWrap(True)
        self._pending_note.setVisible(False)
        tracks.body().addWidget(self._pending_note)
        tracks.body().addStretch(1)
        parts_column.addWidget(tracks)

        sound = avance(Card(tr("Caractère des sons")))
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
            slider.valueChanged.connect(
                self.guard(lambda _v: self._style_touched()))
            line.addWidget(slider, 1)
            sound.body().addLayout(line)
            self._macros[key] = slider
        parts_column.addWidget(sound)
        parts_column.addStretch(1)

        # Trois colonnes côte à côte ; deux, puis la troisième dessous, quand
        # la place **visible** manque (mesuré à 980 px).
        self._style_grid = GrilleAdaptative(
            scroll.viewport(), row, [genre_card, music_host, parts_host], 3,
            2, 1080)
        scroll.setWidget(inner)
        return scroll

    def _build_chords_card(self) -> QWidget:
        """Les accords du morceau — ce qu'étaient la progression de la Boîte
        à outils : les voir, les entendre, en tirer d'autres."""
        card = avance(Card(tr("Les accords")))
        self._chords_label = QLabel("")
        self._chords_label.setWordWrap(True)
        card.body().addWidget(self._chords_label)
        self._chords_list = QListWidget()
        self._chords_list.setMaximumHeight(118)
        self._chords_list.currentRowChanged.connect(
            self.guard(self._highlight_chord))
        card.body().addWidget(self._chords_list)
        line = QHBoxLayout()
        line.setSpacing(6)
        self._listen_chords_button = tool_button(tr("Écouter les accords"),
                                                 "play")
        self._listen_chords_button.clicked.connect(
            self.guard(self._listen_chords))
        line.addWidget(self._listen_chords_button)
        self._other_chords_button = tool_button(tr("Autres accords"), "dice")
        self._other_chords_button.clicked.connect(
            self.guard(self._other_chords))
        line.addWidget(self._other_chords_button)
        self._other_chord_button = tool_button(tr("Autre accord"), "refresh")
        self._other_chord_button.clicked.connect(
            self.guard(self._other_chord))
        line.addWidget(self._other_chord_button)
        line.addStretch(1)
        card.body().addLayout(line)
        return card

    def _kind_changed(self, part: str) -> None:
        kind = self._part_kinds[part].currentData()
        spin = self._part_channels[part]
        # Le canal n'a de sens que pour une piste MIDI ou CV : il ne paraît
        # que pour elles — donc jamais au niveau simple, où l'on ne choisit
        # pas la nature des pistes.
        spin.setVisible(kind in ("midi", "cv"))
        spin.setMaximum(2 if kind == "cv" else 16)
        if self._built:
            self._style_touched()

    # -- étape 2 : les sons ----------------------------------------------- #

    def _build_sounds_step(self) -> QWidget:
        column_host = QWidget()
        column = QVBoxLayout(column_host)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(PAD)
        detail = Card(tr("Le son de la piste"))
        self._sound_title = QLabel(tr("Aucune piste choisie"))
        self._sound_title.setProperty("role", "title")
        detail.body().addWidget(self._sound_title)
        self._sound_text = QLabel("")
        self._sound_text.setWordWrap(True)
        detail.body().addWidget(self._sound_text)
        line = QHBoxLayout()
        line.setSpacing(6)
        self._listen_sound_button = tool_button(tr("Écouter le son"), "play",
                                                primary=True)
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
        line.setSpacing(6)
        self._card_sound_button = tool_button(tr("Choisir sur la carte…"),
                                              "folder")
        self._card_sound_button.clicked.connect(
            self.guard(self._choose_from_card))
        line.addWidget(self._card_sound_button)
        self._edit_sound_button = avance(tool_button(tr("Modifier le son…"),
                                                     "settings"))
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

        # Une batterie : ses rangées, et un autre son pour celle qu'on
        # choisit — ce que faisait l'onglet Kit du générateur.
        self._kit_card = Card(tr("Le kit"))
        hint = QLabel(tr("Une rangée ne vous plaît pas ? Choisissez-la, puis "
                         "« Autre son pour la rangée » : le reste du kit ne "
                         "bouge pas."))
        hint.setProperty("role", "subtitle")
        hint.setWordWrap(True)
        self._kit_card.body().addWidget(hint)
        self._kit_rows = QListWidget()
        self._kit_rows.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self._kit_rows.setMinimumHeight(120)
        self._kit_rows.currentRowChanged.connect(
            self.guard(lambda _r: self._update_actions()))
        self._kit_card.body().addWidget(self._kit_rows, 1)
        line = QHBoxLayout()
        self._kit_row_button = tool_button(tr("Autre son pour la rangée"),
                                           "dice")
        self._kit_row_button.clicked.connect(self.guard(self._reroll_kit_row))
        line.addWidget(self._kit_row_button)
        line.addStretch(1)
        self._kit_card.body().addLayout(line)
        column.addWidget(self._kit_card, 1)

        self._variants_card = Card(tr("Variantes dans le style"))
        hint = QLabel(tr("Le même son, un aspect tiré à nouveau ou un "
                         "curseur poussé : jamais hors du genre. Cliquez "
                         "pour écouter, double-cliquez pour adopter."))
        hint.setProperty("role", "subtitle")
        hint.setWordWrap(True)
        self._variants_card.body().addWidget(hint)
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
        self._variants_card.body().addLayout(line)
        self._variant_list = QListWidget()
        self._variant_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        hint_in_list(self._variant_list,
                     "  " + tr("Aucune variante pour l'instant."))
        self._variant_list.currentRowChanged.connect(
            self.guard(lambda _r: self._listen_variant()))
        self._variant_list.itemDoubleClicked.connect(
            self.guard(lambda _i: self._adopt_variant()))
        self._variant_list.setMinimumHeight(140)
        self._variants_card.body().addWidget(self._variant_list, 1)
        column.addWidget(self._variants_card, 1)
        # Défilante : à 980 × 700, la description du son se chevauchait,
        # écrasée sous sa hauteur minimale.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(column_host)
        return scroll

    # -- étape 3 : les clips ---------------------------------------------- #

    def _build_clips_step(self) -> QWidget:
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
        self._clip_view.hitToggled.connect(self.guard(self._hit_toggled))
        clips.body().addWidget(self._clip_view, 1)
        self._clip_info = QLabel("")
        self._clip_info.setProperty("role", "subtitle")
        self._clip_info.setWordWrap(True)
        clips.body().addWidget(self._clip_info)

        line = QHBoxLayout()
        line.setSpacing(6)
        self._listen_clip_button = tool_button(tr("Écouter le clip"), "play",
                                               primary=True)
        self._listen_clip_button.clicked.connect(
            self.guard(self._listen_clip))
        line.addWidget(self._listen_clip_button)
        self._vary_button = tool_button(tr("Varier"), "refresh")
        self._vary_menu = QMenu(self._vary_button)
        self._vary_button.setMenu(self._vary_menu)
        line.addWidget(self._vary_button)
        self._live_button = tool_button(tr("Jouer sur le Deluge"), "midi")
        self._live_button.setCheckable(True)
        self._live_button.clicked.connect(self.guard(self._toggle_live))
        line.addWidget(self._live_button)
        line.addStretch(1)
        clips.body().addLayout(line)
        # Deux rangées : à 980 px, une seule coupait chaque libellé.
        line = QHBoxLayout()
        line.setSpacing(6)
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
        self._clip_midi_button = avance(tool_button(tr("Clip en MIDI…"),
                                                    "export"))
        self._clip_midi_button.clicked.connect(self.guard(self._clip_to_midi))
        line.addWidget(self._clip_midi_button)
        line.addStretch(1)
        clips.body().addLayout(line)
        clips.body().addWidget(self._build_clip_tools())

        self._live_hint = avance(QLabel(tr(
            "Sur le Deluge, le clip joue dans le clip que suit MIDI Follow "
            "(canal A) — celui que vous avez ouvert. Machine en lecture, il "
            "part au début de sa boucle suivante, calé sur sa mesure ; en "
            "enregistrement (REC), il s'y inscrit.")))
        self._live_hint.setProperty("role", "subtitle")
        self._live_hint.setWordWrap(True)
        clips.body().addWidget(self._live_hint)
        # Défilante : à 980 × 640, la grille, sa légende et deux rangées de
        # boutons demandaient plus que la hauteur offerte, et la légende se
        # dessinait sur la batterie.
        self._clip_view.setMinimumHeight(190)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(clips)
        return scroll

    def _build_clip_tools(self) -> QWidget:
        """Les réglages fins d'un clip — ceux de l'onglet Rythme et de la
        progression d'autrefois : groove, rangées euclidiennes, jeu des
        accords et de la basse. Au niveau avancé seulement."""
        outils = avance(QWidget())
        colonne = QVBoxLayout(outils)
        colonne.setContentsMargins(0, 4, 0, 0)
        colonne.setSpacing(6)

        self._drum_tools = QWidget()
        rangees = QVBoxLayout(self._drum_tools)
        rangees.setContentsMargins(0, 0, 0, 0)
        rangees.setSpacing(6)
        line = QHBoxLayout()
        line.setSpacing(6)
        line.addWidget(QLabel(tr("Groove")))
        self._groove = QComboBox()
        for name in rhythm.groove_names():
            self._groove.addItem(tr(name), name)
        line.addWidget(self._groove)
        line.addWidget(QLabel(tr("Swing")))
        self._swing = QSlider(Qt.Orientation.Horizontal)
        self._swing.setRange(0, 100)
        line.addWidget(self._swing, 1)
        self._groove_button = tool_button(tr("Appliquer le groove"), "check")
        self._groove_button.clicked.connect(self.guard(self._apply_groove))
        line.addWidget(self._groove_button)
        rangees.addLayout(line)
        line = QHBoxLayout()
        line.setSpacing(6)
        line.addWidget(QLabel(tr("Euclidien")))
        self._pulses = QSpinBox()
        self._pulses.setRange(0, 32)
        self._pulses.setValue(5)
        self._pulses.setPrefix(tr("coups") + " ")
        line.addWidget(self._pulses)
        self._steps = QSpinBox()
        self._steps.setRange(1, 32)
        self._steps.setValue(16)
        self._steps.setPrefix(tr("pas") + " ")
        line.addWidget(self._steps)
        self._rotation = QSpinBox()
        self._rotation.setRange(0, 31)
        self._rotation.setPrefix(tr("rotation") + " ")
        line.addWidget(self._rotation)
        self._euclid_button = tool_button(tr("Ajouter la rangée"), "plus")
        self._euclid_button.clicked.connect(self.guard(self._add_euclid))
        line.addWidget(self._euclid_button)
        line.addStretch(1)
        rangees.addLayout(line)
        colonne.addWidget(self._drum_tools)

        self._feel_tools = QWidget()
        line = QHBoxLayout(self._feel_tools)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(6)
        # « Style de jeu » et non « Jeu », qui nomme déjà la polyphonie
        # d'un son dans l'éditeur : deux sens, deux mots.
        line.addWidget(QLabel(tr("Style de jeu")))
        self._feel = QComboBox()
        self._feel.activated.connect(self.guard(lambda _i:
                                                self._feel_changed()))
        line.addWidget(self._feel, 1)
        hint = QLabel(tr("Un nouveau clip, joué ainsi"))
        hint.setProperty("role", "subtitle")
        line.addWidget(hint)
        colonne.addWidget(self._feel_tools)
        return outils

    # -- étape 4 : la structure ------------------------------------------- #

    def _build_song_step(self) -> QWidget:
        # Défilante : à 980 × 700, la grille et ses boutons demandent plus
        # que la hauteur offerte, et Qt les faisait se chevaucher.
        scroll_page = QScrollArea()
        scroll_page.setWidgetResizable(True)
        scroll_page.setFrameShape(QScrollArea.Shape.NoFrame)
        host = QWidget()
        column = QVBoxLayout(host)
        column.setContentsMargins(0, 0, 0, 0)
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
        # zone l'étend, et défile au-delà.
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
        line.setSpacing(6)
        self._listen_section_button = tool_button(tr("Écouter la section"),
                                                  "play", primary=True)
        self._listen_section_button.clicked.connect(
            self.guard(self._listen_section))
        line.addWidget(self._listen_section_button)
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
        line.addStretch(1)
        edit.body().addLayout(line)
        # Deux rangées : à 980 px, une seule coupait chaque libellé.
        line = QHBoxLayout()
        line.setSpacing(6)
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

    # -- étape 5 : sur le Deluge ------------------------------------------ #

    def _build_deluge_step(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        host = QWidget()
        column = QVBoxLayout(host)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(PAD)

        write = Card(tr("Écrire le morceau sur la carte"))
        self._write_hint = QLabel("")
        self._write_hint.setProperty("role", "subtitle")
        self._write_hint.setWordWrap(True)
        write.body().addWidget(self._write_hint)
        line = QHBoxLayout()
        line.setSpacing(6)
        line.addWidget(QLabel(tr("Nom du morceau")))
        self._song_name = QLineEdit()
        self._song_name.setPlaceholderText(tr("ATELIER TECHNO"))
        self._song_name.setMaxLength(60)
        line.addWidget(self._song_name, 1)
        self._write_button = tool_button(tr("Écrire le morceau"), "song",
                                         primary=True)
        self._write_button.clicked.connect(self.guard(self._write_song))
        line.addWidget(self._write_button)
        write.body().addLayout(line)
        self._write_result = QLabel("")
        self._write_result.setWordWrap(True)
        self._write_result.setVisible(False)
        write.body().addWidget(self._write_result)
        line = QHBoxLayout()
        self._show_song_button = tool_button(tr("Voir dans Morceaux"),
                                             "song")
        self._show_song_button.clicked.connect(
            self.guard(self._show_written_song))
        self._show_song_button.setVisible(False)
        line.addWidget(self._show_song_button)
        line.addStretch(1)
        write.body().addLayout(line)
        column.addWidget(write)

        self._complete_card = Card(tr("Compléter le morceau d'origine"))
        self._complete_hint = QLabel("")
        self._complete_hint.setProperty("role", "subtitle")
        self._complete_hint.setWordWrap(True)
        self._complete_card.body().addWidget(self._complete_hint)
        line = QHBoxLayout()
        self._complete_button = tool_button(tr("Compléter le morceau"),
                                            "save")
        self._complete_button.clicked.connect(self.guard(self._complete))
        line.addWidget(self._complete_button)
        line.addStretch(1)
        self._complete_card.body().addLayout(line)
        column.addWidget(self._complete_card)

        machine = Card(tr("Le Deluge"))
        self._deluge_state = QLabel("")
        self._deluge_state.setWordWrap(True)
        machine.body().addWidget(self._deluge_state)
        line = QHBoxLayout()
        line.setSpacing(6)
        self._live_window_button = tool_button(tr("Deluge en direct…"),
                                               "wave")
        self._live_window_button.clicked.connect(
            self.guard(lambda: self.liveRequested.emit()))
        line.addWidget(self._live_window_button)
        self._sync_button = tool_button(tr("Synchroniser"), "refresh")
        self._sync_button.clicked.connect(
            self.guard(lambda: self.syncRequested.emit()))
        line.addWidget(self._sync_button)
        line.addStretch(1)
        machine.body().addLayout(line)
        column.addWidget(machine)

        export = avance(Card(tr("Exporter")))
        hint = QLabel(tr("Le morceau entier dans un fichier MIDI, pour un "
                         "logiciel de MAO : une piste par piste, la batterie "
                         "sur le canal 10, le nom des sections en repères."))
        hint.setProperty("role", "subtitle")
        hint.setWordWrap(True)
        export.body().addWidget(hint)
        line = QHBoxLayout()
        self._midi_button = tool_button(tr("Morceau en MIDI…"), "export")
        self._midi_button.clicked.connect(self.guard(self._song_to_midi))
        line.addWidget(self._midi_button)
        line.addStretch(1)
        export.body().addLayout(line)
        column.addWidget(export)
        column.addStretch(1)
        scroll.setWidget(host)
        return scroll

    # -- le pied de page : d'une étape à l'autre --------------------------- #

    def _build_footer(self) -> QWidget:
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 2, 0, 0)
        row.setSpacing(8)
        self._prev_button = tool_button(tr("Étape précédente"),
                                        "chevron-left")
        self._prev_button.clicked.connect(
            self.guard(lambda: self.show_step(self._tabs.currentIndex() - 1)))
        row.addWidget(self._prev_button)
        self._step_hint = QLabel("")
        self._step_hint.setProperty("role", "subtitle")
        self._step_hint.setWordWrap(True)
        row.addWidget(self._step_hint, 1)
        self._style_note = QLabel("")
        self._style_note.setProperty("role", "subtitle")
        self._style_note.setWordWrap(True)
        self._style_note.setVisible(False)
        row.addWidget(self._style_note, 1)
        self._compose_button = tool_button(tr("Composer le morceau"), "wand",
                                           primary=True)
        self._compose_button.clicked.connect(self.guard(self._compose))
        row.addWidget(self._compose_button)
        self._next_button = tool_button(tr("Étape suivante"),
                                        "chevron-right")
        self._next_button.clicked.connect(
            self.guard(lambda: self.show_step(self._tabs.currentIndex() + 1)))
        row.addWidget(self._next_button)
        return host

    # -- les étapes --------------------------------------------------------- #

    def show_step(self, index: int) -> None:
        """Affiche l'étape ``index`` (0 à 4)."""
        index = max(0, min(len(STEPS) - 1, int(index)))
        if self._tabs.currentIndex() != index:
            self._tabs.setCurrentIndex(index)
        else:
            self._step_changed(index)

    def current_step(self) -> int:
        return self._tabs.currentIndex()

    def _step_changed(self, index: int) -> None:
        index = int(index)
        self._steps_bar.set_current(index)
        if self._project is not None:
            self._reached = max(self._reached, index)
        self._steps_bar.set_reached(self._reached - 1 if self._project
                                    is None else max(self._reached, index))
        # La liste des pistes ne sert qu'aux sons et aux clips.
        self._track_column.setVisible(index in (SONS, CLIPS)
                                      and self._project is not None)
        titre, aide = STEPS[index]
        self._step_hint.setText(tr("Étape %d sur %d — %s") % (
            index + 1, len(STEPS), tr(aide)))
        self._prev_button.setEnabled(index > 0)
        self._next_button.setEnabled(index < len(STEPS) - 1)
        if index < len(STEPS) - 1:
            self._next_button.setToolTip(
                tr("Passer à l'étape %d : %s") % (index + 2,
                                                  tr(STEPS[index + 1][0])))
        self._prev_button.setToolTip(
            tr("Revenir à l'étape %d : %s") % (index, tr(STEPS[index - 1][0]))
            if index > 0 else tr("Vous êtes à la première étape"))
        self._compose_button.setVisible(index == STYLE)
        self._style_note.setVisible(index == STYLE and self._style_dirty
                                    and self._project is not None)
        self._step_hint.setVisible(not self._style_note.isVisible())
        self._fill_empty_steps()
        self._update_hero()
        if index == DELUGE:
            self._fill_deluge_step()

    def _fill_empty_steps(self) -> None:
        """Chaque étape montre son contenu, ou ce qui lui manque."""
        for rang in range(1, self._tabs.count()):
            pile = self._tabs.widget(rang)
            if isinstance(pile, QStackedWidget):
                pile.setCurrentIndex(0 if self._project is not None else 1)

    def _update_hero(self) -> None:
        """Le sous-titre de l'en-tête dit quel morceau est en cours."""
        hint = getattr(self._hero, "hint", None)
        project = self._project
        if project is None:
            self.ctx.atelier_state = None
            if hint is not None:
                hint.setText(tr("Un morceau en cinq étapes, du style au "
                                "Deluge"))
            return
        if project.song_rel:
            debut = "« %s »" % project.song_name
        else:
            debut = genres_mod.genre(project.style.genre).label
        resume = "%s · %s · %s" % (
            debut, theory.note_to_name(project.style.root, with_octave=False)
            + " " + tr(project.style.scale),
            self._duration_text(project) if project.sections
            else "%g BPM" % project.style.tempo())
        if hint is not None:
            hint.setText(resume)
        # L'accueil propose de reprendre ce morceau, à l'étape où l'on en
        # était : le nom de l'étape reste en français, traduit à l'affichage.
        self.ctx.atelier_state = {
            "summary": resume,
            "step": STEPS[max(0, self._tabs.currentIndex())][0]}

    # -- état --------------------------------------------------------------- #

    def _refresh(self) -> None:
        self._fill_tracks()
        self._fill_song()
        self._fill_chords()
        self._update_hero()
        self._step_changed(self._tabs.currentIndex())
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
        self._complete_card.setVisible(has and bool(project.song_rel))
        self._listen_song_button.setEnabled(has and bool(project.sections))
        self._midi_button.setEnabled(has and bool(project.sections))
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
        drums = track is not None and track.is_drums
        self._kit_card.setVisible(drums)
        self._variants_card.setVisible(not drums)
        kit = getattr(track, "kit", None) if drums else None
        self._kit_row_button.setEnabled(
            kit is not None and bool(getattr(kit, "rows", None))
            and self._kit_rows.currentRow() >= 0 and self.ctx.has_card
            and track.existing is None)
        external = track is not None and track.kind in ("midi", "cv")
        self._channel.setVisible(external)
        self._channel_label.setVisible(external)
        for widget in (self._listen_clip_button, self._live_button,
                       self._vary_button, self._delete_clip_button,
                       self._clip_midi_button):
            widget.setEnabled(clip is not None)
        self._new_clip_button.setEnabled(track is not None)
        self._clip_bars.setEnabled(track is not None)
        new_drum = drums and clip is not None and clip.existing is None
        self._drum_tools.setVisible(drums)
        for widget in (self._groove_button, self._euclid_button):
            widget.setEnabled(new_drum)
        feels = atelier.feels_for(track.part) if track is not None \
            and not drums and track.existing is None else ()
        self._feel_tools.setVisible(bool(feels))
        sections = project.sections if has else []
        current = 0 <= self._section < len(sections)
        for widget in (self._section_name, self._section_bars,
                       self._listen_section_button,
                       self._remove_section_button, self._left_button,
                       self._right_button):
            widget.setEnabled(current)
        self._compose_button.setText(
            tr("Recomposer le morceau") if has and not project.song_rel
            else tr("Composer le morceau"))

    # -- le style ---------------------------------------------------------- #

    def _genre_clicked(self, key: str) -> None:
        """Un clic sur un pad de genre. Celui du genre en cours reste
        allumé et ne défait rien : ni le tempo, ni les accords retouchés."""
        if key == self._genre:
            self._genre_buttons[key].setChecked(True)
            return
        self._pick_genre(key)

    def _pick_genre(self, key: str) -> None:
        self._genre = key
        for name, button in self._genre_buttons.items():
            button.setChecked(name == key)
        profile = genres_mod.genre(key)
        self._genre_hint.setText("%s — %d–%d BPM" % (
            tr(profile.description), profile.bpm[0], profile.bpm[1]))
        self._bpm.blockSignals(True)
        self._bpm.setValue(int(round(sum(profile.bpm) / 2.0)))
        self._bpm.blockSignals(False)
        self._tempo_changed()
        # Les parties du genre : l'arpège quand il en a l'habitude.
        from ...core import accomp

        self._part_checks["Arpège"].setChecked(accomp.genre_styles(key)[2])
        self._harmony_changed()

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

    def _tempo_changed(self) -> None:
        """Le tempo s'applique tout de suite au morceau en cours : il ne
        demande rien de refaire."""
        if self._project is not None:
            self._project.style.bpm = float(self._bpm.value())
            if self._built:
                self._update_hero()
                self._show_section()

    def _style_touched(self) -> None:
        """Un réglage du style a changé : il vaudra pour la prochaine
        composition. Le morceau en cours, lui, ne bouge pas."""
        if not self._built or self._project is None:
            return
        self._style_dirty = True
        self._style_note.setText(tr(
            "Ces réglages valent pour la prochaine composition : « Recomposer "
            "le morceau » remplace celui en cours."))
        if self._tabs.currentIndex() == STYLE:
            self._style_note.setVisible(True)
            self._step_hint.setVisible(False)

    def _key_changed(self) -> None:
        self._show_scale()
        self._harmony_changed()

    def _harmony_changed(self) -> None:
        """La tonalité, l'ambiance, la couleur ou la graine ont changé : les
        accords proposés aussi."""
        if not self._built:
            return
        self._chords = None
        self._chord_rolls = 0
        self._fill_chords()
        self._style_touched()

    def _show_scale(self) -> None:
        if not hasattr(self, "_piano"):
            return
        root = int(self._root.currentData() or 57)
        scale = str(self._scale.currentData() or "mineur")
        notes = theory.scale_notes(root, scale, octaves=2)
        self._piano.set_exact_highlight([n for n in notes if n <= 72],
                                        self.color)
        spelling = theory.scale_spelling(root, scale)
        self._scale_notes.setText(tr("%s %s :  %s") % (
            theory.spell(root, spelling, with_octave=False), tr(scale),
            "  ".join(theory.spell(n, spelling, with_octave=False)
                      for n in theory.scale_notes(root, scale,
                                                  octaves=1)[:-1])))

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
        if self._project is not None:
            answer = QMessageBox.question(
                self, tr("Recomposer le morceau"),
                tr("Recomposer remplace le morceau en cours — ses sons, ses "
                   "clips et ses sections. Rien n'est écrit sur la carte. "
                   "Continuer ?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        sd = self.sd if self.ctx.has_card else None
        lib = self.lib if sd is not None else None
        project = atelier.Project(style=style)
        project.progression = list(self._chords) if self._chords \
            else atelier._progression(style)
        for part in wanted:
            kind = kinds[part]
            atelier.add_track(project, kind, part,
                              channel=self._part_channels[part].value(),
                              sd=sd, lib=lib)
        self._apply_pending(project)
        project.sections = atelier.default_sections(project)
        self._style_dirty = False
        self._reached = SONS
        self._set_project(project)
        self.show_step(SONS)
        self.say(tr("Morceau composé : %d piste(s), %d section(s), %s. "
                    "Écoutez chaque son, puis les clips et la structure ; "
                    "écrivez-le sur la carte à la dernière étape.") % (
            len(project.tracks), len(project.sections),
            self._duration_text(project)))

    def _set_project(self, project) -> None:
        self._stop()
        self._project = project
        self._uid = project.tracks[0].uid if project.tracks else None
        self._clip_key = None
        self._section = 0
        self._forget_variants()
        self._kit_tried = {}
        self._write_result.setVisible(False)
        self._show_song_button.setVisible(False)
        if not self._song_name.text().strip() or not project.song_rel:
            self._song_name.setText(self._default_name(project))
        self._refresh()

    def _default_name(self, project) -> str:
        if project.song_name:
            return project.song_name
        return tr("ATELIER %s") % genres_mod.genre(
            project.style.genre).label.upper()

    # -- les accords --------------------------------------------------------- #

    def _current_chords(self) -> list[dict]:
        if self._project is not None and not self._style_dirty:
            return list(self._project.progression)
        if self._chords is None:
            style = self._style()
            self._chords = atelier._progression(
                style, seed=style.seed + self._chords_seed)
        return list(self._chords)

    def _fill_chords(self) -> None:
        if not hasattr(self, "_chords_list"):
            return
        chords = self._current_chords()
        root = int(self._root.currentData() or 57)
        scale = str(self._scale.currentData() or "mineur")
        spelling = theory.scale_spelling(root, scale)
        selection = self._chords_list.currentRow()
        self._chords_list.blockSignals(True)
        self._chords_list.clear()
        for chord in chords:
            notes = "  ".join(theory.spell(n, spelling)
                              for n in chord.get("notes", []))
            self._chords_list.addItem("%s   ·   %s   ·   %s" % (
                chord.get("symbol", ""), chord.get("name", ""), notes))
        if 0 <= selection < self._chords_list.count():
            self._chords_list.setCurrentRow(selection)
        self._chords_list.blockSignals(False)
        self._chords_label.setText(" – ".join(c.get("name", "")
                                              for c in chords))
        # Toujours ouverts : morceau composé, la suite retouchée vaut pour la
        # prochaine composition, comme tout réglage du style.
        self._other_chord_button.setEnabled(self._chords_list.count() > 0)
        self._other_chords_button.setEnabled(True)

    def _highlight_chord(self, row: int) -> None:
        chords = self._current_chords()
        if 0 <= row < len(chords):
            self._piano.set_exact_highlight(chords[row].get("notes", []),
                                            PAD_CYAN)

    def _other_chords(self) -> None:
        """Une autre progression, dans la même ambiance."""
        self._chords_seed += 1
        self._chords = None
        self._style_touched()
        self._fill_chords()
        self.say(tr("Accords proposés : %s.") % self._chords_label.text())

    def _other_chord(self) -> None:
        """Remplace l'accord choisi par un autre de même fonction."""
        index = self._chords_list.currentRow()
        chords = self._current_chords()
        if not 0 <= index < len(chords):
            self.say(tr("Choisissez d'abord un accord dans la liste."))
            return
        root = int(self._root.currentData() or 57)
        scale = str(self._scale.currentData() or "mineur")
        avant = chords[index].get("name", "")
        self._chord_rolls += 1
        self._chords = theory.substitute(chords, index, root, scale,
                                         seed=self._chords_seed
                                         + self._chord_rolls)
        # Morceau composé : la suite retouchée part de la sienne, et vaut
        # pour la prochaine composition.
        self._style_touched()
        self._fill_chords()
        self.say(tr("%s remplacé par %s : %s.") % (
            avant, self._chords[index].get("name", ""),
            self._chords_label.text()))

    def _listen_chords(self) -> None:
        """Les accords seuls, tenus, avec un son de nappe du style."""
        from ...core import accomp

        chords = self._current_chords()
        style = self._style() if self._project is None \
            else self._project.style
        parts = {"Accords#0": accomp.chord_part(chords, "tenu")}
        _opts, preset = atelier._sound_for(style, "Accords", style.seed)
        self.run(_render_mix, parts, {"Accords#0": preset.sound}, None,
                 style.tempo(), None, None,
                 on_result=self.guard(self._play_audio),
                 on_error=self.guard(
                     lambda m: self.say(tr("Rendu impossible : %s") % m)),
                 title=tr("Rendu des accords"))

    # -- les sons venus d'ailleurs ---------------------------------------- #

    def offer_preset(self, preset, part: str = "", options=None,
                     edited: bool = False) -> str:
        """Un son d'une autre page — un preset de la carte, un son du
        générateur — rejoint le morceau.

        Sans morceau, il est retenu pour le prochain : l'étape Style le dit.
        Avec un morceau, il va à la piste choisie si c'est un synthé neuf,
        sinon à la première qui joue sa partie. Rend le message dit.
        """
        self._ensure_built()
        part = part if part in atelier.parts_for_kind("synth") \
            else atelier.part_for(part)
        if self._project is None:
            self._pending_sounds[part] = (copy.deepcopy(preset), options,
                                          edited)
            self._part_checks[part].setChecked(True)
            self._show_pending()
            self.show_step(STYLE)
            message = tr("« %s » jouera la partie %s du prochain morceau : "
                         "choisissez un style, puis composez.") % (
                preset.name, tr(part).lower())
        else:
            track = atelier.use_preset(self._project, preset, part,
                                       uid=self._uid, options=options,
                                       edited=edited)
            self._uid = track.uid
            self._clip_key = None
            self._forget_variants()
            self._refresh()
            self.show_step(SONS)
            message = tr("« %s » joue désormais la piste « %s ». Écoutez-la "
                         "dans le morceau.") % (
                preset.name, atelier.track_label(track))
        self.say(message)
        return message

    def offer_kit(self, kit) -> str:
        """Un kit d'une autre page devient la batterie du morceau."""
        self._ensure_built()
        if self._project is None:
            self._pending_kit = copy.deepcopy(kit)
            self._part_checks["Batterie"].setChecked(True)
            self._show_pending()
            self.show_step(STYLE)
            message = tr("Le kit « %s » sera la batterie du prochain "
                         "morceau : choisissez un style, puis composez.") \
                % kit.name
        else:
            track = atelier.use_kit(self._project, kit)
            self._uid = track.uid
            self._clip_key = None
            self._refresh()
            self.show_step(SONS)
            message = tr("Le kit « %s » est désormais la batterie du "
                         "morceau.") % kit.name
        self.say(message)
        return message

    def _show_pending(self) -> None:
        noms = ["%s : %s" % (tr(part), preset.name)
                for part, (preset, _o, _e) in self._pending_sounds.items()]
        if self._pending_kit is not None:
            noms.insert(0, "%s : %s" % (tr("Batterie"),
                                        self._pending_kit.name))
        self._pending_note.setText(
            tr("Retenus pour le morceau : %s.") % " · ".join(noms)
            if noms else "")
        self._pending_note.setVisible(bool(noms))

    def _apply_pending(self, project) -> None:
        """Les sons retenus prennent leur piste dans le morceau composé."""
        for part, (preset, options, edited) in self._pending_sounds.items():
            atelier.use_preset(project, preset, part, options=options,
                               edited=edited)
        if self._pending_kit is not None:
            atelier.use_kit(project, self._pending_kit)
        self._pending_sounds = {}
        self._pending_kit = None
        self._show_pending()

    # -- les pistes et les sons ------------------------------------------ #

    def _fill_tracks(self) -> None:
        project = self._project
        widget = self._track_list
        widget.blockSignals(True)
        widget.clear()
        for track in (project.tracks if project is not None else []):
            item = QListWidgetItem(QIcon(pad_dot(part_color(track.part), 12)),
                                   self._track_text(track))
            item.setData(Qt.ItemDataRole.UserRole, track.uid)
            item.setToolTip(self._track_text(track))
            widget.addItem(item)
        if project is None or not project.tracks:
            hint_in_list(widget, "  " + tr("Composez un morceau, ou partez "
                                           "d'un des vôtres."))
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

    def _track_selected(self) -> None:
        item = self._track_list.currentItem()
        if item is None or item.data(Qt.ItemDataRole.UserRole) is None:
            return
        self._uid = item.data(Qt.ItemDataRole.UserRole)
        self._clip_key = None
        self._forget_variants()
        self._show_track()

    def _show_track(self) -> None:
        track = self._track()
        if track is None:
            self._sound_title.setText(tr("Aucune piste choisie"))
            self._sound_text.setText(tr("Composez un morceau à l'étape "
                                        "Style, ou partez d'un des vôtres."))
            self._fill_kit_rows()
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
        self._fill_feels(track)
        self._fill_kit_rows()
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
            return tr("%s — %d rangée(s).") % (kit.name, len(kit.rows))
        if track.kind == "midi":
            return tr("Piste MIDI : le Deluge envoie ses notes sur le canal "
                      "%d, à l'appareil que vous y branchez. L'écoute de "
                      "l'ordinateur la joue avec un son du style.") \
                % track.channel
        return tr("Piste CV : une tension de hauteur et une porte sur la "
                  "sortie CV %d, vers un synthé modulaire. Une note à la "
                  "fois.") % track.channel

    def _fill_kit_rows(self) -> None:
        track = self._track()
        self._kit_rows.blockSignals(True)
        selection = self._kit_rows.currentRow()
        self._kit_rows.clear()
        kit = getattr(track, "kit", None) if track is not None \
            and track.is_drums else None
        if kit is not None:
            from ...core.kitgen import family_of

            for row in kit.rows:
                famille = family_of(row.file_name)
                self._kit_rows.addItem("%s   ·   %s   ·   %s" % (
                    row.name, str(row.file_name).rsplit("/", 1)[-1],
                    tr(famille)))
            if 0 <= selection < self._kit_rows.count():
                self._kit_rows.setCurrentRow(selection)
        else:
            hint_in_list(self._kit_rows, "  " + tr(
                "Aucun kit de la carte : la batterie s'écoute en sons "
                "synthétisés. « Autre son » en bâtit un dans votre "
                "bibliothèque."))
        self._kit_rows.blockSignals(False)

    def _add_track(self) -> None:
        if self._project is None:
            return
        part = self._new_part.currentData()
        # Au niveau avancé, la nature choisie fait foi et la partie s'y
        # plie ; au niveau simple, la nature suit la partie : un kit pour la
        # batterie, un synthé du Deluge pour le reste.
        kind = self._new_kind.currentData() if self.advanced() else ""
        if kind not in atelier.KINDS:
            kind = "kit" if part == "Batterie" else "synth"
        if part not in atelier.parts_for_kind(kind):
            part = atelier.parts_for_kind(kind)[0]
        sd = self.sd if self.ctx.has_card else None
        track = atelier.add_track(self._project, kind, part,
                                  sd=sd, lib=self.lib if sd else None,
                                  channel=self._free_channel(kind))
        self._uid = track.uid
        self._refresh()
        self.say(tr("Piste ajoutée : %s, avec un premier clip. Placez-le "
                    "dans les sections (étape Structure).")
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
            self._kit_tried = {}
            self._fill_tracks()

    def _reroll_kit_row(self) -> None:
        """Un autre son pour la rangée choisie du kit, le reste intact."""
        track = self._track()
        kit = getattr(track, "kit", None) if track is not None else None
        index = self._kit_rows.currentRow()
        if kit is None or not 0 <= index < len(kit.rows):
            self.say(tr("Choisissez d'abord une rangée du kit."))
            return
        from ...core import kitgen

        essayes = self._kit_tried.setdefault(index, set())
        essayes.add(kit.rows[index].file_name)
        self._kit_rolls += 1
        slot = kitgen.reroll_row(
            kit, index, self.lib, genre=self._project.style.genre,
            seed="%d|%d|%d" % (self._project.style.seed, index,
                               self._kit_rolls),
            avoid=essayes)
        if slot is None:
            self.say(tr("La bibliothèque n'a pas d'autre son pour cette "
                        "rangée."))
            return
        self._fill_kit_rows()
        self.say(tr("%s : %s (%s).") % (kit.rows[index].name,
                                        slot.rel.rsplit("/", 1)[-1],
                                        tr(slot.family)))

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
            self._kit_tried = {}
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

    def _fill_feels(self, track) -> None:
        self._feel.blockSignals(True)
        self._feel.clear()
        self._feel.addItem(tr("selon le genre"), "")
        for feel in atelier.feels_for(track.part):
            self._feel.addItem(tr(feel), feel)
        index = self._feel.findData(track.feel)
        self._feel.setCurrentIndex(max(0, index))
        self._feel.blockSignals(False)

    def _feel_changed(self) -> None:
        """Le jeu d'une piste d'accords ou de basse : un clip neuf, joué
        ainsi, que l'on compare aussitôt à l'ancien."""
        track = self._track()
        if track is None or not atelier.feels_for(track.part):
            return
        track.feel = str(self._feel.currentData() or "")
        bars = int(self._clip_bars.currentData() or 4)
        clip = atelier.generate_clip(self._project, track.uid, bars=bars,
                                     seed=random.randrange(1 << 30))
        self._clip_key = clip.key
        self._fill_clips()
        self.say(tr("Clip %s, joué « %s » : écoutez-le, puis placez-le "
                    "dans une section.") % (
            clip.key, tr(track.feel) if track.feel else tr("selon le genre")))

    def _fill_clips(self) -> None:
        track = self._track()
        self._clip_list.blockSignals(True)
        self._clip_list.clear()
        if track is not None:
            for clip in track.clips:
                origin = tr(clip.origin)
                if clip.parent:
                    origin = tr("%s de %s") % (origin, clip.parent)
                item = QListWidgetItem(QIcon(pad_dot(part_color(track.part),
                                                     12)),
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
            rows = None
            editable = False
            if track.is_drums:
                rows = atelier.drum_rows(track)
                editable = clip.existing is None
                if editable:
                    rows = list(rows) + [r for r in BASIC_ROWS
                                         if r not in rows]
            self._clip_view.set_clip(clip, part_color(track.part), rows,
                                     editable=editable)
            used = [s.name for s in self._project.sections
                    if s.cells.get(track.uid) == clip.key]
            text = tr("%d note(s) sur %d mesure(s).") % (clip.note_count,
                                                         clip.bars)
            if clip.existing is not None:
                text += " " + tr("Déjà dans le morceau d'origine.")
            elif editable:
                text += " " + tr("Un clic dans la grille allume ou éteint un "
                                 "coup.")
            if used:
                text += " " + tr("Joué dans : %s.") % ", ".join(
                    tr(n) for n in used)
            else:
                text += " " + tr("Dans aucune section pour l'instant.")
            self._clip_info.setText(text)
        self._update_actions()

    def _hit_toggled(self, row: str, step: int) -> None:
        """Un clic dans la grille de la batterie."""
        track = self._track()
        clip = self._clip()
        if track is None or clip is None or not track.is_drums:
            return
        if clip.existing is not None:
            self.say(tr("Ce clip est déjà sur le Deluge : variez-le pour en "
                        "faire un neuf, que vous pourrez dessiner."))
            return
        allume = atelier.toggle_hit(self._project, track.uid, clip.key,
                                    row, step)
        self._show_clip()
        self.say((tr("%s : coup ajouté au pas %d.") if allume else
                  tr("%s : coup retiré au pas %d.")) % (tr(row), step + 1))

    def _apply_groove(self) -> None:
        track = self._track()
        clip = self._clip()
        if track is None or clip is None or not track.is_drums:
            return
        groove = self._groove.currentData() or "droit"
        swing = self._swing.value() / 100.0
        atelier.groove_clip(self._project, track.uid, clip.key, groove, swing)
        self._show_clip()
        equivalent = rhythm.deluge_swing(groove)
        if equivalent is not None and swing <= 0:
            self.say(tr("Groove appliqué au clip %s. Sur le Deluge : swing "
                        "%s.") % (clip.key, equivalent))
        else:
            self.say(tr("Groove appliqué au clip %s.") % clip.key)

    def _add_euclid(self) -> None:
        track = self._track()
        clip = self._clip()
        if track is None or clip is None or not track.is_drums:
            return
        nom = atelier.add_euclid(self._project, track.uid, clip.key,
                                 int(self._pulses.value()),
                                 int(self._steps.value()),
                                 int(self._rotation.value()))
        self._show_clip()
        self.say(tr("Rangée %s ajoutée au clip %s : sur la carte, elle "
                    "reçoit une percussion de votre bibliothèque.")
                 % (nom, clip.key))

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

    def _clip_to_midi(self) -> None:
        """Le clip choisi dans un fichier MIDI, hors de la carte."""
        track = self._track()
        clip = self._clip()
        if track is None or clip is None:
            return
        chosen, _f = QFileDialog.getSaveFileName(
            self, tr("Exporter le clip"),
            "%s %s.mid" % (tr(track.part), clip.key),
            tr("Fichier MIDI (*.mid)"))
        if not chosen:
            return
        from pathlib import Path

        from ...core import midifile

        bpm = self._project.style.tempo()
        if track.is_drums:
            midifile.pattern_to_midi(Path(chosen), clip.pattern, None, bpm)
        else:
            midifile.parts_to_midi(Path(chosen),
                                   {track.part: list(clip.events)}, bpm)
        self.say(tr("Clip exporté : %s") % Path(chosen).name)

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

    # -- la structure ------------------------------------------------------ #

    def _fill_song(self) -> None:
        project = self._project
        if project is None:
            self._matrix.set_project([], [])
            self._song_origin.setText("")
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
                "« Compléter le morceau », à l'étape Deluge, écrit une "
                "nouvelle version qui le contient tel quel, plus vos pistes, "
                "vos clips et vos sections neuves.") % project.song_name)
        else:
            self._song_origin.setText(tr(
                "Un morceau neuf, en %s, %s. À l'étape Deluge, « Écrire le "
                "morceau » en fait un morceau du Deluge, sections et "
                "arrangement compris.") % (
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
        self._update_hero()

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
        self._update_hero()

    def _remove_section(self) -> None:
        if self._project is None:
            return
        atelier.remove_section(self._project, self._section)
        self._section = max(0, self._section - 1)
        self._fill_song()
        self._update_hero()

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

    def _listen_extract(self) -> None:
        """Le passage le plus plein du morceau, huit mesures au plus."""
        if self._project is None:
            return
        index = atelier.fullest_section(self._project)
        if index < 0:
            self.say(tr("Aucune section ne joue de clip."))
            return
        parts, drums, bars = atelier.section_parts(self._project, index)
        self._render(parts, drums, tr("Rendu de l'extrait"))
        self.say(tr("Écoute de « %s », le passage le plus plein : %d "
                    "mesures.") % (tr(self._project.sections[index].name),
                                   bars))

    def _listen(self) -> None:
        """La touche Espace : ce que l'étape affichée a de plus parlant."""
        step = self._tabs.currentIndex()
        if step == SONS:
            self._listen_sound()
        elif step == CLIPS:
            self._listen_clip()
        elif step == STRUCTURE:
            self._listen_section()
        elif self._project is not None:
            self._listen_extract()
        else:
            self._listen_chords()

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

    # -- le tempo de la machine ----------------------------------------- #

    def follow_tempo(self, bpm: int) -> bool:
        """Le tempo du morceau prend celui du Deluge quand son horloge
        change. Rend ``True`` si le champ a changé."""
        champ = getattr(self, "_bpm", None)
        if champ is None:
            return False
        try:
            tempo = max(champ.minimum(), min(champ.maximum(),
                                             int(round(float(bpm)))))
        except (TypeError, ValueError):
            return False
        if champ.value() == tempo:
            return False
        champ.setValue(tempo)
        return True

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
            self, tr("Ouvrir un morceau du Deluge"),
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
        self._ensure_built()
        song = Song.load(card.abs(rel))
        project = atelier.from_song(song, card)
        project.song_rel = rel
        project.style.genre = self._genre
        self._style_dirty = False
        self._reached = STRUCTURE
        self._set_project(project)
        self._song_name.setText(project.song_name)
        self.show_step(STRUCTURE)
        self.say(tr("« %s » est dans l'atelier : %d piste(s), %d clip(s), "
                    "%d section(s). Variez ses clips, ajoutez des pistes et "
                    "des sections, puis complétez-le à l'étape Deluge.") % (
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
        """``Atelier#SONGS/Cool1.XML`` ouvre ce morceau dans l'atelier ;
        ``Atelier#Clips`` ouvre l'étape des clips."""
        text = str(hint or "")
        if text.upper().startswith("SONGS/"):
            self._ensure_built()
            try:
                self.open_song(text)
            except Exception as exc:  # noqa: BLE001
                log.debug("morceau non ouvert dans l'atelier : %s", exc)
            return
        super().focus_on(hint)

    def _fill_deluge_step(self) -> None:
        """Ce que deviendra le morceau écrit, et où en est la machine."""
        role = self.ctx.settings.card_role(self.sd.root) \
            if self.ctx.has_card else ""
        if not self.ctx.has_card:
            texte = tr("Indiquez d'abord la carte, dans les réglages : le "
                       "morceau s'écrit dans son dossier SONGS.")
        elif role == "sauvegarde":
            texte = tr("Vous regardez la sauvegarde de la carte : elle ne "
                       "s'écrit pas. Réglages ▸ Carte du Deluge pour "
                       "travailler sur la carte.")
        elif role == "travail":
            texte = tr("Un morceau neuf dans SONGS, sections et arrangement "
                       "compris ; aucun fichier n'est remplacé. Il part sur "
                       "le Deluge par le câble quelques secondes après, ou "
                       "à sa prochaine connexion.")
        else:
            texte = tr("Un morceau neuf dans SONGS, sections et arrangement "
                       "compris ; aucun fichier n'est remplacé. Remettez "
                       "ensuite la carte dans le Deluge.")
        self._write_hint.setText(texte)
        project = self._project
        if project is not None and project.song_rel:
            self._complete_hint.setText(tr(
                "Une nouvelle version de « %s », qui le contient octet pour "
                "octet, plus vos pistes, vos clips et vos sections neuves ; "
                "l'original n'est pas touché.") % project.song_name)
        lien = getattr(self.ctx, "link", None)
        travail = getattr(self.ctx, "card_work", None)
        connecte = bool(lien is not None and lien.is_connected)
        if connecte:
            etat = lien.state().summary()
        else:
            etat = tr("Deluge débranché : branchez-le en USB pour jouer les "
                      "clips sur la machine et y envoyer le morceau.")
        if travail is not None and getattr(travail, "pending", None):
            etat += " " + travail.pending_text() + "."
        self._deluge_state.setText(etat)
        self._sync_button.setEnabled(role == "travail")
        self._sync_button.setVisible(role == "travail")

    def _write_song(self) -> None:
        project = self._project
        if project is None:
            return
        name = self._song_name.text().strip() or self._default_name(project)
        rel = self.write_song(lambda card: atelier.to_song_spec(
            project, name, sd=card, lib=self.lib), name)
        if rel:
            self._written(rel)

    def _written(self, rel: str) -> None:
        self._last_written = rel
        self._reached = DELUGE
        self._write_result.setText(tr(
            "Écrit : %s. Sur le Deluge, chargez-le comme tout autre morceau "
            "(LOAD, puis SONG).") % rel)
        self._write_result.setVisible(True)
        self._show_song_button.setVisible(True)
        self._step_changed(self._tabs.currentIndex())

    def _show_written_song(self) -> None:
        if self._last_written:
            self.navigateRequested.emit("Songs#%s" % self._last_written)

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
            self._written(rel)

    def _song_to_midi(self) -> None:
        """Le morceau entier dans un fichier MIDI, hors de la carte."""
        project = self._project
        if project is None:
            return
        chosen, _f = QFileDialog.getSaveFileName(
            self, tr("Exporter le morceau"),
            "%s.mid" % (self._song_name.text().strip()
                        or self._default_name(project)),
            tr("Fichier MIDI (*.mid)"))
        if not chosen:
            return
        from pathlib import Path

        try:
            pistes = atelier.export_midi(project, Path(chosen))
        except ValueError as exc:
            self.say(tr("Export impossible : %s.") % exc)
            return
        self.say(tr("Morceau exporté : %s — %d piste(s), %d section(s), le "
                    "nom des sections en repères.") % (
            Path(chosen).name, pistes, len(project.sections)))


def _render_mix(parts: dict, sounds: dict, drums, bpm: float, kit=None,
                sd=None, should_stop=None):
    """Les parties et la batterie mêlées (fil séparé) ; ``None`` si l'arrêt
    est demandé en cours de rendu.

    Les deux sortent au niveau de la machine (:mod:`.render`) : on les
    additionne telles quelles et seul le mélange est ramené sous la pleine
    échelle — ramenés chacun de leur côté, puis dosés à 0,85, ils perdaient
    l'équilibre du morceau. La carte sert aussi aux parties : un son à
    échantillon y jouait une dent de scie."""
    from ...core import render

    tonal = render.render_parts(parts, sounds, bpm=bpm, sr=44100, sd=sd,
                                should_stop=should_stop,
                                normalize=False) if parts else None
    if should_stop is not None and should_stop():
        return None
    beat = None
    if drums is not None and drums.tracks:
        beat = render.render_pattern(drums, bpm=bpm, sr=44100, kit=kit, sd=sd,
                                     normalize=False)
    if tonal is None and beat is None:
        return None
    return render.mix(*(t for t in (tonal, beat) if t is not None))
