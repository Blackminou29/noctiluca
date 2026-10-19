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
import random
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
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

from ...core import accomp as accomp_mod
from ...core import genres as genres_mod
from ...core import rhythm as rhythm_mod
from ...core import sketch as sketch_mod
from ...core import songwriter as songwriter_mod
from ...core import theory as theory_mod
from ...i18n import N_, decimal, tr, untranslated
from ..theme import GOLD, PAD, PAD_CYAN
from ..widgets.common import Card
from ..widgets.padgrid import StepSequencer
from ..widgets.piano import PianoKeys
from .base import Page, tool_button

log = logging.getLogger(__name__)

#: Modèle de structure de chaque genre (voir :mod:`delugeapp.core.sketch`).
ARRANGEMENTS = sketch_mod.ARRANGEMENTS

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
    """Boîte à outils de composition."""

    TITLE = N_("Outils")
    ICON = "tools"
    #: Seul le mixage harmonique a besoin de la carte.
    NEEDS_CARD = False

    def __init__(self, ctx, parent=None) -> None:
        super().__init__(ctx, parent)
        self._pattern = None
        self._progression: list = []
        self._progression_key: tuple = (None, "")
        self._melody_seed = 1
        self._pattern_base = None
        self._chord_rolls = 0
        #: Kits d'écoute bâtis sur la carte, par genre et pistes.
        self._listen_kits: dict = {}
        self._spelling: dict = {}

    def build(self) -> None:
        outer = QVBoxLayout(self.content())
        outer.setContentsMargins(PAD, PAD, PAD, PAD)
        outer.setSpacing(8)

        header, _actions = self.header(
            tr("Boîte à outils"),
            tr("Théorie, rythme, calculs et aide-mémoire"))
        outer.addWidget(header)

        tabs = QTabWidget()
        tabs.addTab(self._build_theory_tab(), tr("Théorie"))
        tabs.addTab(self._build_rhythm_tab(), tr("Rythme"))
        tabs.addTab(self._build_calc_tab(), tr("Calculatrice"))
        tabs.addTab(self._build_camelot_tab(), tr("Mixage harmonique"))
        tabs.addTab(self._build_arrangement_tab(), tr("Arrangement"))
        tabs.addTab(self._build_cheatsheet_tab(), tr("Aide-mémoire"))
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
        self._chords.setMaximumHeight(220)
        chords.body().addWidget(self._chords)
        column.addWidget(chords)

        prog = Card(tr("Progression"))
        prog_row = QHBoxLayout()
        prog_row.addWidget(QLabel(tr("Ambiance")))
        self._progression_kind = QComboBox()
        for name in theory_mod.progression_names():
            self._progression_kind.addItem(tr(name), name)
        prog_row.addWidget(self._progression_kind, 1)
        prog_row.addWidget(QLabel(tr("Couleur")))
        self._prog_color = QComboBox()
        self._prog_color.addItem(tr("selon l'ambiance"), "")
        for color, aide in theory_mod.CHORD_COLORS.items():
            self._prog_color.addItem(tr(color), color)
            self._prog_color.setItemData(self._prog_color.count() - 1,
                                         tr(aide),
                                         Qt.ItemDataRole.ToolTipRole)
        prog_row.addWidget(self._prog_color)
        prog_row.addWidget(QLabel(tr("Mesures")))
        self._progression_bars = QSpinBox()
        self._progression_bars.setRange(2, 16)
        self._progression_bars.setValue(4)
        prog_row.addWidget(self._progression_bars)
        make = tool_button(tr("Proposer"), "wand", primary=True)
        make.clicked.connect(self.guard(self._make_progression))
        prog_row.addWidget(make)
        prog.body().addLayout(prog_row)

        # L'accompagnement : comment poser la progression dans le temps.
        acc_row = QHBoxLayout()
        acc_row.addWidget(QLabel(tr("Genre")))
        self._acc_genre = QComboBox()
        for key in genres_mod.genre_keys():
            self._acc_genre.addItem(genres_mod.genre(key).label, key)
        self._acc_genre.activated.connect(
            self.guard(lambda _i: self._genre_tempo()))
        acc_row.addWidget(self._acc_genre)
        acc_row.addWidget(QLabel(tr("Accords")))
        self._acc_chords = QComboBox()
        self._acc_chords.addItem(tr("selon le genre"), "")
        for style in accomp_mod.CHORD_STYLES:
            self._acc_chords.addItem(tr(style), style)
        acc_row.addWidget(self._acc_chords)
        acc_row.addWidget(QLabel(tr("Basse")))
        self._acc_bass = QComboBox()
        self._acc_bass.addItem(tr("selon le genre"), "")
        for style, aide in accomp_mod.BASS_STYLES.items():
            self._acc_bass.addItem(tr(style), style)
            self._acc_bass.setItemData(self._acc_bass.count() - 1, tr(aide),
                                       Qt.ItemDataRole.ToolTipRole)
        acc_row.addWidget(self._acc_bass)
        acc_row.addWidget(QLabel("BPM"))
        self._acc_bpm = QSpinBox()
        self._acc_bpm.setRange(40, 220)
        self._acc_bpm.setValue(124)
        acc_row.addWidget(self._acc_bpm)
        acc_row.addStretch(1)
        prog.body().addLayout(acc_row)

        # Les parties facultatives sur leur propre ligne : sur la même que
        # le genre et les styles, la page débordait à 980 pixels.
        extra_row = QHBoxLayout()
        extra_row.addWidget(QLabel(tr("Ajouter")))
        self._acc_arp = QCheckBox(tr("Arpège"))
        extra_row.addWidget(self._acc_arp)
        self._acc_melody = QCheckBox(tr("Mélodie"))
        extra_row.addWidget(self._acc_melody)
        self._acc_drums = QCheckBox(tr("Batterie"))
        extra_row.addWidget(self._acc_drums)
        extra_row.addStretch(1)
        prog.body().addLayout(extra_row)

        # Les listes de ces deux rangées peuvent rétrécir : à leur largeur
        # naturelle, la page débordait sous une barre de défilement
        # horizontale à 980 pixels, « Proposer » et le tempo coupés.
        for liste in (self._progression_kind, self._prog_color,
                      self._acc_genre, self._acc_chords, self._acc_bass):
            liste.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            liste.setMinimumContentsLength(7)

        play_row = QHBoxLayout()
        self._listen_prog_button = tool_button(tr("Écouter"), "play")
        self._listen_prog_button.clicked.connect(
            self.guard(self._listen_progression))
        play_row.addWidget(self._listen_prog_button)
        stop = tool_button(tr("Arrêter"), "stop")
        stop.clicked.connect(self.guard(self._stop_audio))
        play_row.addWidget(stop)
        self._export_prog_button = tool_button(tr("En MIDI"), "export")
        self._export_prog_button.clicked.connect(
            self.guard(self._export_progression))
        play_row.addWidget(self._export_prog_button)
        self._song_prog_button = tool_button(tr("En morceau"), "song")
        self._song_prog_button.clicked.connect(
            self.guard(self._song_from_progression))
        play_row.addWidget(self._song_prog_button)
        self._melody_button = tool_button(tr("Autre mélodie"), "dice")
        self._melody_button.clicked.connect(self.guard(self._other_melody))
        play_row.addWidget(self._melody_button)
        self._chord_button = tool_button(tr("Autre accord"), "dice")
        self._chord_button.clicked.connect(self.guard(self._other_chord))
        play_row.addWidget(self._chord_button)
        play_row.addStretch(1)
        prog.body().addLayout(play_row)

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

    def _make_progression(self) -> None:
        root = self._root.currentData() or 60
        scale = self._scale.currentData() or "majeur"
        self._progression = theory_mod.progression(
            root, scale, self._progression_kind.currentData() or "",
            bars=int(self._progression_bars.value()),
            color=self._prog_color.currentData() or "")
        # La mélodie se tire dans la gamme de la progression, même si l'on
        # change de gamme ensuite sans en proposer une nouvelle.
        self._progression_key = (root, scale)
        self._melody_seed = random.randrange(1 << 20)
        self._show_progression()
        self.say(tr("%d accords proposés : %s.")
                 % (len(self._progression),
                    " – ".join(c["name"] for c in self._progression)))

    def _show_progression(self) -> None:
        """Remplit la liste des accords ; garde la ligne choisie."""
        root, scale = self._progression_key
        spelling = theory_mod.scale_spelling(root if root is not None else 60,
                                             scale or "majeur")
        selection = self._progression_list.currentRow()
        self._progression_list.clear()
        for chord in self._progression:
            notes = "  ".join(theory_mod.spell(n, spelling)
                              for n in chord["notes"])
            fonction = tr(chord.get("function", ""))
            # Des séparateurs plutôt qu'un alignement par espaces : la police
            # est proportionnelle, et « IIImaj9 Mibmaj9 » décalait tout.
            self._progression_list.addItem(
                f"{chord['symbol']}   ·   {chord['name']}   ·   {notes}"
                + (f"   ({fonction})" if fonction else ""))
        if 0 <= selection < self._progression_list.count():
            self._progression_list.setCurrentRow(selection)

    def _other_chord(self) -> None:
        """Remplace l'accord choisi par un autre de même fonction."""
        if not self._progression:
            self.say(tr("Proposez d'abord une progression."))
            return
        index = self._progression_list.currentRow()
        if not 0 <= index < len(self._progression):
            self.say(tr("Choisissez d'abord un accord dans la liste."))
            return
        root, scale = self._progression_key
        avant = self._progression[index]["name"]
        self._chord_rolls += 1
        self._progression = theory_mod.substitute(
            self._progression, index, root, scale,
            seed=self._melody_seed + self._chord_rolls)
        self._show_progression()
        apres = self._progression[index]
        self.say(tr("%s remplacé par %s, même fonction (%s) : %s.")
                 % (avant, apres["name"],
                    tr(apres.get("function") or N_("libre")),
                    " – ".join(c["name"] for c in self._progression)))

    def _highlight_progression(self, row: int) -> None:
        if not 0 <= row < len(self._progression):
            return
        self._piano.set_exact_highlight(
            self._progression[row]["notes"], PAD_CYAN)

    def _genre_tempo(self) -> None:
        """Le tempo suit le genre choisi : le milieu de sa plage."""
        key = self._acc_genre.currentData() or "techno"
        low, high = genres_mod.genre(key).bpm
        self._acc_bpm.setValue(int(round((low + high) / 2.0)))

    def _parts(self) -> dict:
        """Les parties d'accompagnement de la progression courante."""
        root, scale = getattr(self, "_progression_key", (None, ""))
        return accomp_mod.accompany(
            self._progression,
            genre=self._acc_genre.currentData() or "",
            chords=self._acc_chords.currentData() or "",
            bass=self._acc_bass.currentData() or "",
            arp=True if self._acc_arp.isChecked() else None,
            melody=self._acc_melody.isChecked(),
            root=root, scale=scale,
            seed=self._melody_seed,
            drums=self._current_beat() if self._acc_drums.isChecked()
            else None)

    def _current_beat(self):
        """Le rythme de l'onglet Rythme, sinon celui du genre choisi ici."""
        if self._pattern is not None and any(self._pattern.tracks.values()):
            return self._pattern
        return rhythm_mod.genre_beat(self._acc_genre.currentData() or "techno",
                                     bars=1, seed=1)

    def _drum_kit(self, genre: str, tracks):
        """Un kit de la carte pour faire sonner les pistes, ou ``None``.

        Bâti par :func:`delugeapp.core.kitgen.build_kit` dans la
        bibliothèque indexée ; sans carte, ou pour une piste qu'elle ne
        couvre pas, la batterie synthétisée prend le relais.
        """
        if self.sd is None or self.lib is None:
            return None
        from ...core import kitgen

        roles = tuple(sorted(t for t in tracks if t in kitgen.ROLE_VOLUME))
        key = (genre, roles)
        if key not in self._listen_kits:
            try:
                kit = kitgen.build_kit(self.sd, self.lib, "ECOUTE",
                                       genre=genre, seed=1,
                                       slots=list(roles))
            except Exception as exc:  # noqa: BLE001 - l'écoute se rabat
                log.debug("kit d'écoute impossible : %s", exc)
                kit = None
            self._listen_kits[key] = kit if kit is not None and kit.rows \
                else None
        return self._listen_kits[key]

    def _other_melody(self) -> None:
        """Une autre mélodie sur les mêmes accords, puis on l'écoute."""
        if not self._progression:
            self._make_progression()
        if not self._progression:
            return
        self._melody_seed = (self._melody_seed + 1) % (1 << 20)
        self._acc_melody.setChecked(True)
        self._listen_progression()

    def _listen_progression(self) -> None:
        if not self._progression:
            self._make_progression()
        if not self._progression:
            return
        parts = self._parts()
        genre = self._acc_genre.currentData() or "techno"
        drums = (rhythm_mod.loop(self._current_beat(),
                                 max(1, len(self._progression)))
                 if self._acc_drums.isChecked() else None)
        kit = self._drum_kit(genre, drums.tracks) if drums else None
        self.say(tr("Rendu de l'accompagnement…"))
        self.run(self._render_parts, parts, genre,
                 int(self._acc_bpm.value()), drums, kit, self.sd,
                 on_result=self.guard(self._play_audio),
                 on_error=self.guard(
                     lambda m: self.say(tr("Rendu impossible : %s") % m)),
                 title=tr("Rendu de l'accompagnement"))

    @staticmethod
    def _render_parts(parts: dict, genre: str, bpm: int, drums=None,
                      kit=None, sd=None):
        """Joue chaque partie avec un son généré pour le genre (fil séparé).

        ``drums`` : le motif de batterie, joué par ``kit`` (des échantillons
        de la carte) ou, à défaut, par la batterie synthétisée.
        """
        from ...core import render

        styles = accomp_mod.genre_styles(genre)
        # Les sons de l'export en morceau : les mêmes, tirés au même endroit.
        sounds = {name: preset.sound for name, preset in
                  songwriter_mod.part_presets(parts, genre).items()}
        log.debug("accompagnement %s : %s", genre, styles)
        tonal = render.render_parts(parts, sounds, bpm=bpm, sr=44100)
        if drums is None or not drums.tracks:
            return tonal
        beat = render.render_pattern(drums, bpm=bpm, sr=44100, kit=kit,
                                     sd=sd)
        return render.mix(tonal, beat, levels=(1.0, 0.85))

    def _play_audio(self, audio) -> None:
        if audio is None or self.player is None:
            self.say(tr("Aucune sortie audio disponible."))
            return
        try:
            self.player.set_volume(self.ctx.settings.preview_volume)
            self.player.play_array(audio, 44100)
            self.say(tr("Lecture de l'accompagnement…"))
        except Exception as exc:  # noqa: BLE001
            log.debug("lecture impossible : %s", exc)
            self.say(tr("Lecture impossible : %s") % exc)

    def _stop_audio(self) -> None:
        if self.player is not None:
            try:
                self.player.stop()
            except Exception as exc:  # noqa: BLE001
                log.debug("arrêt impossible : %s", exc)

    def _export_progression(self) -> None:
        if not self._progression:
            self.say(tr("Proposez d'abord une progression."))
            return
        from ...core import midifile

        chosen, _f = QFileDialog.getSaveFileName(
            self, tr("Exporter l'accompagnement"), tr("progression.mid"),
            tr("Fichier MIDI (*.mid)"))
        if not chosen:
            return
        try:
            pistes = midifile.parts_to_midi(
                Path(chosen), self._parts(), int(self._acc_bpm.value()))
        except Exception as exc:  # noqa: BLE001
            log.exception("export MIDI impossible")
            self.say(tr("Export impossible : %s") % exc)
            return
        noms = ", ".join(tr(n).lower() for n in self._parts())
        self.say(tr("Accompagnement exporté : %s (%d pistes — %s)")
                 % (Path(chosen).name, pistes, noms))

    # -- tempo de la machine ------------------------------------------------- #

    def follow_tempo(self, bpm: int) -> bool:
        """Les trois tempos de la page prennent celui du Deluge.

        Appelé par la fenêtre quand l'horloge de la machine change de tempo
        (réglage « Les outils suivent le tempo du Deluge »). Rend ``True``
        si un champ a changé.
        """
        try:
            tempo = int(round(float(bpm)))
        except (TypeError, ValueError):
            return False
        change = False
        # La page peut exister sans avoir encore été construite.
        for champ in (getattr(self, "_acc_bpm", None),
                      getattr(self, "_beat_bpm", None),
                      getattr(self, "_arr_bpm", None)):
            if champ is None:
                continue
            borne = max(champ.minimum(), min(champ.maximum(), tempo))
            if champ.value() != borne:
                champ.setValue(borne)
                change = True
        return change

    # -- morceaux du Deluge -------------------------------------------------- #

    def _beat_kit(self, card, genre: str, tracks):
        """Le kit qui jouera la batterie : celui de l'écoute, complété.

        Les pistes que le kit d'écoute ne couvre pas (une piste
        euclidienne…) reçoivent un son de percussion de la carte : sur la
        machine, une piste sans rangée resterait muette.
        """
        base = self._drum_kit(genre, tracks)
        kit, rows, lost = songwriter_mod.drum_kit_for(
            card, self.lib, genre, tracks, base=base)
        if lost:
            log.info("pistes sans son dans le morceau : %s", ", ".join(lost))
        return kit, rows

    def _song_from_progression(self) -> None:
        """La progression et son accompagnement, en morceau du Deluge."""
        if not self._progression:
            self.say(tr("Proposez d'abord une progression."))
            return
        genre = self._acc_genre.currentData() or "techno"
        bpm = int(self._acc_bpm.value())
        root, scale = self._progression_key
        parts = self._parts()
        progression = list(self._progression)
        with_drums = self._acc_drums.isChecked()

        def build(card):
            drums = kit = rows = None
            if with_drums:
                drums = rhythm_mod.loop(self._current_beat(),
                                        max(1, len(progression)))
                kit, rows = self._beat_kit(card, genre, drums.tracks)
            return songwriter_mod.progression_song(
                parts, name="", bpm=bpm, genre=genre, root=root, scale=scale,
                drums=drums, kit=kit, row_map=rows)

        tonique = theory_mod.spell(
            root if root is not None else 60,
            theory_mod.scale_spelling(root if root is not None else 60,
                                      scale or "majeur"),
            with_octave=False)
        self.write_song(build, tr("Progression %s %s")
                        % (tonique, tr(scale or "majeur")))

    def _song_from_beat(self) -> None:
        """Le motif affiché, joué par un kit de la carte, en morceau."""
        pattern = self._sequencer.pattern() or self._pattern
        if pattern is None or not any(pattern.tracks.values()):
            self.say(tr("Créez d'abord un motif."))
            return
        genre = self._beat_genre.currentData() or "techno"
        bpm = int(self._beat_bpm.value())

        def build(card):
            kit, rows = self._beat_kit(card, genre, pattern.tracks)
            if kit is None:
                raise ValueError(tr("aucun échantillon de batterie dans la "
                                    "bibliothèque — lancez une analyse de la "
                                    "carte"))
            return songwriter_mod.pattern_song(pattern, kit, rows, name="",
                                               bpm=bpm)

        self.write_song(build, tr("Rythme %s") % genres_mod.genre(genre).label)

    def _song_from_sketch(self) -> None:
        """L'esquisse entière, en morceau à sections."""
        genre = self._arr_genre.currentData() or "techno"
        bpm = int(self._arr_bpm.value())
        result = self._sketch()
        if self._progression:
            root, scale = self._progression_key
        else:
            root, scale = 57, "mineur"

        def build(card):
            kit = rows = None
            if result.drums is not None and result.drums.tracks:
                kit, rows = self._beat_kit(card, genre, result.drums.tracks)
            return songwriter_mod.sketch_song(
                result, name="", bpm=bpm, genre=genre, root=root,
                scale=scale, kit=kit, row_map=rows)

        self.write_song(build,
                        tr("Esquisse %s") % genres_mod.genre(genre).label)


    # -- rythme ------------------------------------------------------------- #

    def _build_rhythm_tab(self) -> QWidget:
        host = QWidget()
        column = QVBoxLayout(host)
        column.setContentsMargins(0, PAD, 0, 0)
        column.setSpacing(PAD)

        card = Card(tr("Motif"))
        grid = QGridLayout()
        grid.setSpacing(6)

        grid.addWidget(QLabel(tr("Genre")), 0, 0)
        self._beat_genre = QComboBox()
        for key in genres_mod.genre_keys():
            self._beat_genre.addItem(genres_mod.genre(key).label, key)
        self._beat_genre.activated.connect(
            self.guard(lambda _i: self._beat_tempo()))
        grid.addWidget(self._beat_genre, 0, 1)

        grid.addWidget(QLabel(tr("Mesures")), 0, 2)
        self._beat_bars = QSpinBox()
        self._beat_bars.setRange(1, 4)
        grid.addWidget(self._beat_bars, 0, 3)

        from_genre = tool_button(tr("Motif du genre"), "wand", primary=True)
        from_genre.clicked.connect(self.guard(self._beat_from_genre))
        grid.addWidget(from_genre, 0, 4)

        grid.addWidget(QLabel(tr("Euclidien")), 1, 0)
        euclid_row = QHBoxLayout()
        self._pulses = QSpinBox()
        self._pulses.setRange(0, 32)
        self._pulses.setValue(5)
        self._pulses.setPrefix(tr("coups") + " ")
        euclid_row.addWidget(self._pulses)
        self._steps = QSpinBox()
        self._steps.setRange(1, 32)
        self._steps.setValue(16)
        self._steps.setPrefix(tr("pas") + " ")
        euclid_row.addWidget(self._steps)
        self._rotation = QSpinBox()
        self._rotation.setRange(0, 31)
        self._rotation.setPrefix(tr("rotation") + " ")
        euclid_row.addWidget(self._rotation)
        holder = QWidget()
        holder.setLayout(euclid_row)
        grid.addWidget(holder, 1, 1, 1, 3)

        euclid = tool_button(tr("Ajouter la piste"), "plus")
        euclid.clicked.connect(self.guard(self._add_euclid))
        grid.addWidget(euclid, 1, 4)
        card.body().addLayout(grid)

        groove_row = QHBoxLayout()
        groove_row.addWidget(QLabel(tr("Groove")))
        self._groove = QComboBox()
        for name in rhythm_mod.groove_names():
            self._groove.addItem(tr(name), name)
        groove_row.addWidget(self._groove)
        groove_row.addWidget(QLabel(tr("Swing")))
        self._swing = QSlider(Qt.Orientation.Horizontal)
        self._swing.setRange(0, 100)
        groove_row.addWidget(self._swing, 1)
        apply_groove = tool_button(tr("Appliquer"), "check")
        apply_groove.clicked.connect(self.guard(self._apply_groove))
        groove_row.addWidget(apply_groove)
        self._export_beat_button = tool_button(tr("En MIDI"), "export")
        self._export_beat_button.clicked.connect(
            self.guard(self._export_beat))
        groove_row.addWidget(self._export_beat_button)
        self._song_beat_button = tool_button(tr("En morceau"), "song")
        self._song_beat_button.clicked.connect(
            self.guard(self._song_from_beat))
        groove_row.addWidget(self._song_beat_button)
        card.body().addLayout(groove_row)

        listen_row = QHBoxLayout()
        self._variation_button = tool_button(tr("Variation"), "dice")
        self._variation_button.clicked.connect(self.guard(self._variation))
        listen_row.addWidget(self._variation_button)
        self._listen_beat_button = tool_button(tr("Écouter"), "play")
        self._listen_beat_button.clicked.connect(
            self.guard(self._listen_beat))
        listen_row.addWidget(self._listen_beat_button)
        stop_beat = tool_button(tr("Arrêter"), "stop")
        stop_beat.clicked.connect(self.guard(self._stop_audio))
        listen_row.addWidget(stop_beat)
        listen_row.addWidget(QLabel("BPM"))
        self._beat_bpm = QSpinBox()
        self._beat_bpm.setRange(40, 220)
        self._beat_bpm.setValue(128)
        listen_row.addWidget(self._beat_bpm)
        listen_row.addStretch(1)
        card.body().addLayout(listen_row)

        self._sequencer = StepSequencer()
        self._sequencer.setMinimumHeight(130)
        card.body().addWidget(self._sequencer)

        self._ascii = QPlainTextEdit()
        self._ascii.setReadOnly(True)
        self._ascii.setMaximumHeight(130)
        self._ascii.setProperty("role", "mono")
        self._ascii.setToolTip(
            tr("Représentation texte, à recopier dans un carnet"))
        card.body().addWidget(self._ascii)
        column.addWidget(card, 1)
        return host

    def _beat_from_genre(self) -> None:
        self._pattern = rhythm_mod.genre_beat(
            self._beat_genre.currentData() or "techno",
            bars=int(self._beat_bars.value()), seed=1)
        self._pattern_base = self._pattern
        self._show_pattern()

    def _beat_tempo(self) -> None:
        """Le tempo du rythme suit le genre : le milieu de sa plage."""
        low, high = genres_mod.genre(
            self._beat_genre.currentData() or "techno").bpm
        self._beat_bpm.setValue(int(round((low + high) / 2.0)))

    def _variation(self) -> None:
        """Une variation du motif du genre, ossature intacte."""
        if self._pattern_base is None:
            self._beat_from_genre()
        genre = self._beat_genre.currentData() or "techno"
        self._pattern = rhythm_mod.variation(
            self._pattern_base, genre, seed=random.randrange(1 << 30))
        self._show_pattern()
        self.say(tr("Variation : %s. Grosse caisse, caisse claire et clap "
                    "n'ont pas bougé.") % self._pattern.name.split(" — ")[-1])

    def _listen_beat(self) -> None:
        """Joue le motif deux fois, avec les sons de la carte s'il y en a."""
        pattern = self._sequencer.pattern() or self._pattern
        if pattern is None or not any(pattern.tracks.values()):
            self.say(tr("Créez d'abord un motif."))
            return
        genre = self._beat_genre.currentData() or "techno"
        kit = self._drum_kit(genre, pattern.tracks)
        bars = max(2, int(round(pattern.bars)) * 2)
        self.say(tr("Rendu du rythme…") if kit else
                 tr("Rendu du rythme… (batterie synthétisée)"))
        self.run(self._render_beat, pattern, int(self._beat_bpm.value()),
                 kit, self.sd, bars,
                 on_result=self.guard(self._play_audio),
                 on_error=self.guard(
                     lambda m: self.say(tr("Rendu impossible : %s") % m)),
                 title=tr("Rendu du rythme"))

    @staticmethod
    def _render_beat(pattern, bpm: int, kit, sd, bars: int):
        from ...core import render

        return render.render_pattern(pattern, bpm=bpm, sr=44100, kit=kit,
                                     sd=sd, bars=bars)

    def _add_euclid(self) -> None:
        """Ajoute une piste euclidienne au motif courant."""
        pulses = int(self._pulses.value())
        steps = int(self._steps.value())
        rotation = int(self._rotation.value())

        if self._pattern is None:
            self._pattern = rhythm_mod.Pattern(name=tr("Euclidien"),
                                               steps=steps)
        name = f"E({pulses},{steps})"
        if rotation:
            name += f"+{rotation}"

        cells = rhythm_mod.euclid(pulses, steps, rotation)
        self._pattern.tracks[name] = [
            rhythm_mod.Step(pos=i, velocity=100)
            for i, on in enumerate(cells) if on]
        # Une variation partira désormais de ce motif-ci, piste comprise.
        self._pattern_base = self._pattern
        self._show_pattern()
        self.say(tr("Piste %s ajoutée.") % name)

    def _apply_groove(self) -> None:
        if self._pattern is None:
            self.say(tr("Créez d'abord un motif."))
            return
        # Toujours depuis le motif droit : appliquer deux fois un groove le
        # cumulait, et le second clic plantait sur les positions décalées.
        # Les pas ajoutés ou retirés dans la grille sont conservés.
        groove = self._groove.currentData() or "droit"
        pattern = rhythm_mod.apply_groove(
            rhythm_mod.straighten(self._pattern), groove, 1.0)
        swing = self._swing.value() / 100.0
        if swing > 0:
            pattern = rhythm_mod.swing(pattern, swing)
        self._pattern = pattern
        self._show_pattern()
        equivalent = rhythm_mod.deluge_swing(groove)
        if equivalent is not None and swing <= 0:
            self.say(tr("Groove appliqué. Sur le Deluge : swing %s.")
                     % equivalent)
        else:
            self.say(tr("Groove appliqué."))

    def _show_pattern(self) -> None:
        if self._pattern is None:
            return
        self._sequencer.set_pattern(self._pattern)
        self._ascii.setPlainText(self._pattern.ascii())

    def _export_beat(self) -> None:
        pattern = self._sequencer.pattern() or self._pattern
        if pattern is None or not any(pattern.tracks.values()):
            self.say(tr("Créez d'abord un motif."))
            return
        from ...core import midifile

        chosen, _f = QFileDialog.getSaveFileName(
            self, tr("Exporter le motif"), tr("motif.mid"),
            tr("Fichier MIDI (*.mid)"))
        if not chosen:
            return
        try:
            midifile.pattern_to_midi(Path(chosen), pattern, None,
                                     int(self._beat_bpm.value()))
        except Exception as exc:  # noqa: BLE001
            log.exception("export MIDI impossible")
            self.say(tr("Export impossible : %s") % exc)
            return
        self.say(tr("Motif exporté : %s") % Path(chosen).name)

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

    # -- arrangement -------------------------------------------------------- #

    def _build_arrangement_tab(self) -> QWidget:
        host = QWidget()
        column = QVBoxLayout(host)
        column.setContentsMargins(0, PAD, 0, 0)
        column.setSpacing(PAD)

        card = Card(tr("Modèle de structure"))
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("Genre")))
        self._arr_genre = QComboBox()
        for key in genres_mod.genre_keys():
            self._arr_genre.addItem(genres_mod.genre(key).label, key)
        self._arr_genre.activated.connect(
            self.guard(lambda _i: self._arrangement_genre()))
        row.addWidget(self._arr_genre, 1)
        row.addWidget(QLabel("BPM"))
        self._arr_bpm = QSpinBox()
        self._arr_bpm.setRange(20, 400)
        self._arr_bpm.setValue(128)
        self._arr_bpm.valueChanged.connect(
            self.guard(lambda _v: self._show_arrangement()))
        row.addWidget(self._arr_bpm)
        card.body().addLayout(row)

        self._arrangement = QTableWidget(0, 5)
        self._arrangement.setHorizontalHeaderLabels(
            [tr("Section"), tr("Mesures"), tr("Durée"), tr("Position"),
             tr("Parties")])
        entete = self._arrangement.horizontalHeader()
        for colonne in range(4):
            entete.setSectionResizeMode(
                colonne, QHeaderView.ResizeMode.ResizeToContents)
        entete.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self._arrangement.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._arrangement.verticalHeader().setVisible(False)
        self._arrangement.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        card.body().addWidget(self._arrangement)

        self._arr_total = QLabel("")
        self._arr_total.setProperty("role", "subtitle")
        card.body().addWidget(self._arr_total)

        sketch_row = QHBoxLayout()
        self._listen_section_button = tool_button(tr("Écouter la section"),
                                                  "play")
        self._listen_section_button.clicked.connect(
            self.guard(self._listen_section))
        sketch_row.addWidget(self._listen_section_button)
        stop = tool_button(tr("Arrêter"), "stop")
        stop.clicked.connect(self.guard(self._stop_audio))
        sketch_row.addWidget(stop)
        self._export_sketch_button = tool_button(tr("Esquisse en MIDI"),
                                                 "export")
        self._export_sketch_button.clicked.connect(
            self.guard(self._export_sketch))
        sketch_row.addWidget(self._export_sketch_button)
        self._song_sketch_button = tool_button(tr("Esquisse en morceau"),
                                               "song")
        self._song_sketch_button.clicked.connect(
            self.guard(self._song_from_sketch))
        sketch_row.addWidget(self._song_sketch_button)
        sketch_row.addStretch(1)
        card.body().addLayout(sketch_row)

        self._arr_source = QLabel("")
        self._arr_source.setProperty("role", "subtitle")
        self._arr_source.setWordWrap(True)
        card.body().addWidget(self._arr_source)
        column.addWidget(card, 1)
        return host

    def _arrangement_genre(self) -> None:
        """Le tempo suit le genre, puis la structure se redessine."""
        low, high = genres_mod.genre(
            self._arr_genre.currentData() or "techno").bpm
        self._arr_bpm.blockSignals(True)
        self._arr_bpm.setValue(int(round((low + high) / 2.0)))
        self._arr_bpm.blockSignals(False)
        self._show_arrangement()

    def _sketch(self):
        """L'esquisse : les accords de l'onglet Théorie et le rythme de
        l'onglet Rythme s'ils existent, sinon ceux du genre."""
        genre = self._arr_genre.currentData() or "techno"
        if self._progression:
            progression = self._progression
            root, scale = self._progression_key
        else:
            progression = sketch_mod.default_progression(genre, seed=1)
            root, scale = 57, "mineur"
        pattern = (self._pattern
                   if self._pattern is not None
                   and (self._beat_genre.currentData() or "") == genre
                   else None)
        return sketch_mod.sketch(progression, genre, pattern=pattern,
                                 root=root, scale=scale, seed=1)

    def _sketch_sources(self) -> str:
        genre = self._arr_genre.currentData() or "techno"
        accords = (" – ".join(c["name"] for c in self._progression)
                   if self._progression else
                   tr("une progression « %s » en la mineur")
                   % tr(sketch_mod.GENRE_AMBIANCE.get(genre, "pop")))
        rythme = (tr("celui de l'onglet Rythme")
                  if self._pattern is not None
                  and (self._beat_genre.currentData() or "") == genre
                  else tr("le motif du genre"))
        return (tr("L'esquisse déroule %s sur toute la structure ; rythme : "
                   "%s. Chaque section ne garde que les parties de son "
                   "rôle.") % (accords, rythme))

    def _listen_section(self) -> None:
        index = self._arrangement.currentRow()
        if index < 0:
            self.say(tr("Choisissez d'abord une section dans le tableau."))
            return
        result = self._sketch()
        parts, drums, bars = sketch_mod.excerpt(result, index, max_bars=8)
        if not parts and drums is None:
            self.say(tr("Cette section ne joue rien."))
            return
        genre = self._arr_genre.currentData() or "techno"
        kit = self._drum_kit(genre, drums.tracks) if drums else None
        section = result.sections[index]
        self.say(tr("Rendu de « %s » (%d mesures)…")
                 % (tr(section.name), bars))
        self.run(self._render_parts, parts, genre,
                 int(self._arr_bpm.value()), drums, kit, self.sd,
                 on_result=self.guard(self._play_audio),
                 on_error=self.guard(
                     lambda m: self.say(tr("Rendu impossible : %s") % m)),
                 title=tr("Rendu de la section"))

    def _export_sketch(self) -> None:
        from ...core import midifile

        chosen, _f = QFileDialog.getSaveFileName(
            self, tr("Exporter l'esquisse"), tr("esquisse.mid"),
            tr("Fichier MIDI (*.mid)"))
        if not chosen:
            return
        result = self._sketch()
        try:
            pistes = midifile.parts_to_midi(
                Path(chosen), result.parts, int(self._arr_bpm.value()),
                markers=result.markers())
        except Exception as exc:  # noqa: BLE001
            log.exception("export de l'esquisse impossible")
            self.say(tr("Export impossible : %s") % exc)
            return
        minutes = result.bars * 4 * 60.0 / float(self._arr_bpm.value())
        self.say(tr("Esquisse exportée : %s — %d pistes (%s), %d sections, "
                    "%d mesures, %d min %02d s.")
                 % (Path(chosen).name, pistes,
                    ", ".join(tr(n).lower() for n in result.parts),
                    len(result.sections), result.bars, int(minutes // 60),
                    int(minutes % 60)))

    def _show_arrangement(self) -> None:
        key = self._arr_genre.currentData() or "techno"
        bpm = float(self._arr_bpm.value())
        sections = ARRANGEMENTS.get(key, ARRANGEMENTS["techno"])
        roles = sketch_mod.plan(key)
        bar_seconds = 4 * 60.0 / bpm

        self._arrangement.setRowCount(0)
        position = 0
        for index, (name, bars) in enumerate(sections):
            row = self._arrangement.rowCount()
            self._arrangement.insertRow(row)
            item = QTableWidgetItem(tr(name))
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
                QTableWidgetItem(tr("mesure %d — %d:%02d")
                                 % (position + 1, int(start // 60),
                                    int(start % 60))))
            if index < len(roles):
                parties = QTableWidgetItem(
                    ", ".join(tr(p).lower() for p in roles[index].parts))
                parties.setToolTip(
                    tr(sketch_mod.SECTION_KINDS.get(roles[index].kind, "")))
                self._arrangement.setItem(row, 4, parties)
            position += bars

        total = position * bar_seconds
        self._arr_total.setText(
            tr("%d mesures au total, soit %d min %02d s à %.0f BPM. Les "
               "sections du Deluge se règlent dans la vue Morceau.")
            % (position, int(total // 60), int(total % 60), bpm))
        self._arr_source.setText(self._sketch_sources())

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
        if not self._progression:
            self._genre_tempo()
        self._show_scale()
        self._calc()
        self._fill_wheel()
        if self._pattern is None:
            self._beat_tempo()
            self._beat_from_genre()
        self._show_arrangement()
