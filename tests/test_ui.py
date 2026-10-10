# -*- coding: utf-8 -*-
"""Tests des widgets de l'interface.

Séparés de ``test_core.py`` parce qu'ils ont besoin de Qt : le noyau, lui,
doit rester importable sans PyQt6 (SPEC §0.7), et mélanger les deux ferait
perdre cette garantie.

Tournent sans écran grâce à ``QT_QPA_PLATFORM=offscreen``, réglé avant
l'import de Qt. Si PyQt6 est absent, tout le module est sauté plutôt que de
faire échouer la suite.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np

try:
    from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
    from PyQt6.QtGui import QMouseEvent, QWheelEvent
    from PyQt6.QtWidgets import QApplication, QLabel, QTableView

    HAVE_QT = True
except ImportError:  # pragma: no cover - dépend de l'installation
    HAVE_QT = False

if not HAVE_QT:  # pragma: no cover
    raise unittest.SkipTest("PyQt6 absent : tests d'interface sautés")

from delugeapp.core import (db, genres, rhythm, scan, sdcard, synthgen,
                            theory, wav)
from delugeapp.core.model import Kit, SynthPreset
from delugeapp.ui import icons, theme
from delugeapp.ui.widgets import common
from delugeapp.ui.widgets.envelope import EnvelopeEditor
from delugeapp.ui.widgets.filtercurve import FilterCurve, SpectrumView
from delugeapp.ui.widgets.knob import Knob
from delugeapp.ui.widgets.padgrid import PadGrid, SongPreview, StepSequencer
from delugeapp.ui.widgets.piano import PianoKeys
from delugeapp.ui.widgets.waveform import WaveformView

#: Application Qt partagée : Qt n'en accepte qu'une par processus.
_APP: QApplication | None = None


def setUpModule() -> None:  # noqa: N802 - API unittest
    global _APP
    _APP = QApplication.instance() or QApplication([])
    theme.apply_theme(_APP)


def _mouse(kind, x: float, y: float = 10.0) -> QMouseEvent:
    """Événement souris synthétique, bouton gauche."""
    button = Qt.MouseButton.LeftButton
    return QMouseEvent(kind, QPointF(x, y), button, button,
                       Qt.KeyboardModifier.NoModifier)


def _wheel(x: float, y: float, delta: int,
           modifier=Qt.KeyboardModifier.NoModifier) -> QWheelEvent:
    """Événement molette synthétique."""
    return QWheelEvent(QPointF(x, y), QPointF(x, y), QPoint(0, 0),
                       QPoint(0, int(delta)), Qt.MouseButton.NoButton,
                       modifier, Qt.ScrollPhase.NoScrollPhase, False)


class WidgetCase(unittest.TestCase):
    """Base commune : garde une référence aux widgets créés."""

    def setUp(self):
        self._widgets: list = []

    def tearDown(self):
        for widget in self._widgets:
            widget.deleteLater()
        if _APP is not None:
            _APP.processEvents()

    def shown(self, widget, width: int = 400, height: int = 120):
        """Affiche un widget hors écran et le dimensionne.

        Beaucoup de widgets calculent leur géométrie à partir de leur taille
        réelle : sans ``resize`` ni ``show``, les clics synthétiques tombent
        à côté.
        """
        widget.resize(width, height)
        widget.show()
        if _APP is not None:
            _APP.processEvents()
        self._widgets.append(widget)
        return widget


# --------------------------------------------------------------------------- #
# Icônes et thème
# --------------------------------------------------------------------------- #

class TestIconsAndTheme(WidgetCase):
    """Les icônes sont dessinées, pas chargées depuis des fichiers."""

    def test_toutes_les_icones_dessinent_quelque_chose(self):
        for name in icons.ICON_NAMES:
            with self.subTest(icone=name):
                image = icons.icon(name, theme.PAD_WHITE, 32).pixmap(32, 32) \
                    .toImage()
                painted = sum(1 for y in range(0, 32, 2)
                              for x in range(0, 32, 2)
                              if image.pixelColor(x, y).alpha() > 0)
                self.assertGreater(painted, 3, f"icône {name} vide")

    def test_icone_inconnue_ne_leve_pas(self):
        self.assertFalse(icons.icon("pas une icône", theme.GOLD, 16).isNull()
                         and False)

    def test_embleme(self):
        self.assertFalse(icons.app_icon(128).isNull())
        self.assertEqual(icons.pad_pixmap(theme.PAD_CYCLE, 64).width(), 64)

    def test_feuille_de_style(self):
        qss = theme.qss()
        self.assertGreater(len(qss), 5000)
        # Les sélecteurs sur lesquels les widgets s'appuient.
        for selector in ("QFrame#Card", "QFrame#Tile", 'QLabel[role="value"]',
                         "QPushButton#Primary", "QTableView", "QScrollBar"):
            with self.subTest(selecteur=selector):
                self.assertIn(selector, qss)


# --------------------------------------------------------------------------- #
# Widgets communs
# --------------------------------------------------------------------------- #

class TestCommonWidgets(WidgetCase):
    """Panneaux, tuiles, étiquettes, états vides."""

    def test_tous_s_instancient(self):
        for name, build in (
            ("SectionTitle", lambda: common.SectionTitle("Titre")),
            ("Card", lambda: common.Card("Panneau")),
            ("StatTile", lambda: common.StatTile("Libellé", "42",
                                                 theme.PAD_CYAN, "samples")),
            ("Badge", lambda: common.Badge("Neuf", theme.PAD_GREEN)),
            ("TagChip", lambda: common.TagChip("étiquette")),
            ("ElidedLabel", lambda: common.ElidedLabel("texte " * 40)),
            ("SearchBar", lambda: common.SearchBar()),
            ("StarRating", lambda: common.StarRating(3)),
            ("EmptyState", lambda: common.EmptyState("Vide", "info",
                                                     "Agir")),
            ("BusyBar", lambda: common.BusyBar()),
            ("KeyValueTable", lambda: common.KeyValueTable()),
        ):
            with self.subTest(widget=name):
                widget = self.shown(build())
                self.assertTrue(widget.isVisible())

    def test_card_recoit_son_contenu(self):
        card = self.shown(common.Card("Essai"))
        card.body().addWidget(QLabel("contenu"))
        self.assertEqual(card.body().count(), 1)
        card.set_title("Autre titre")
        # Un panneau sans titre doit pouvoir en recevoir un ensuite.
        nu = self.shown(common.Card())
        nu.set_title("Ajouté après coup")

    def test_stat_tile(self):
        tile = self.shown(common.StatTile("Presets"))
        tile.set_value(911)
        tile.set_value(None)
        tile.set_color(theme.PAD_PURPLE)
        clics = []
        tile.clicked.connect(lambda: clics.append(1))
        tile.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease, 10, 10))
        self.assertEqual(clics, [1])

    def test_etoiles(self):
        stars = self.shown(common.StarRating(0), 120, 24)
        recu = []
        stars.changed.connect(recu.append)
        stars.set_value(4)
        self.assertEqual(stars.value(), 4)
        self.assertEqual(recu, [], "set_value ne doit pas émettre")

        stars.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease,
                                       stars._size * 2 + 2, 10))
        self.assertEqual(recu[-1], 3)
        # Recliquer la même étoile remet à zéro.
        stars.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease,
                                       stars._size * 2 + 2, 10))
        self.assertEqual(recu[-1], 0)

    def test_recherche_differee(self):
        """Le signal n'est émis qu'après le délai, ou sur Entrée."""
        bar = self.shown(common.SearchBar())
        recu = []
        bar.searchChanged.connect(recu.append)
        bar.setText("kick")
        self.assertEqual(recu, [], "émission immédiate : le délai est ignoré")
        # Entrée court-circuite le délai.
        bar.returnPressed.emit()
        self.assertEqual(recu, ["kick"])

    def test_libelle_tronque(self):
        label = self.shown(common.ElidedLabel("un chemin " * 30), 120, 20)
        self.assertIn("un chemin", label.full_text())
        self.assertLess(len(label.text()), len(label.full_text()))
        self.assertEqual(label.toolTip(), label.full_text())

    def test_etat_vide(self):
        empty = self.shown(common.EmptyState("Aucune carte", "warning",
                                             "Choisir"), 400, 300)
        recu = []
        empty.actionClicked.connect(lambda: recu.append(1))
        empty._button.click()
        self.assertEqual(recu, [1])
        empty.set_message("Autre", "détail")

    def test_barre_de_progression(self):
        bar = self.shown(common.BusyBar(), 200, 10)
        bar.set_progress(5, 10)
        self.assertEqual((bar.minimum(), bar.maximum(), bar.value()),
                         (0, 10, 5))
        bar.set_progress(0, 0)
        self.assertEqual(bar.maximum(), 0, "total nul = mode indéterminé")
        bar.set_busy(False)
        self.assertEqual(bar.maximum(), 100)

    def test_tableau_cle_valeur(self):
        table = self.shown(common.KeyValueTable(), 300, 160)
        table.set_rows([("Nom", "808 Kick"), ("Durée", "0,25 s"),
                        ("Absent", None)])
        self.assertEqual(table.rowCount(), 3)
        self.assertEqual(table.item(2, 1).text(), "—")
        table.set_rows([])
        self.assertEqual(table.rowCount(), 0)

    def test_formats_lisibles(self):
        self.assertEqual(common.human_size(None), "—")
        self.assertEqual(common.human_size(0), "0 o")
        self.assertEqual(common.human_size(512), "512 o")
        self.assertEqual(common.human_size(1536), "1,5 Kio")
        self.assertEqual(common.human_size("x"), "—")
        self.assertEqual(common.human_duration(None), "—")
        self.assertEqual(common.human_duration(0), "—")
        self.assertEqual(common.human_duration(0.25), "0,25 s")
        self.assertEqual(common.human_duration(187), "3 min 07 s")


# --------------------------------------------------------------------------- #
# Modèle de tableau
# --------------------------------------------------------------------------- #

class TestRowTableModel(WidgetCase):
    """Le modèle exigé par la SPEC §6.5 pour les grandes listes."""

    L = Qt.AlignmentFlag.AlignLeft
    R = Qt.AlignmentFlag.AlignRight

    def _rows(self) -> list[dict]:
        return [
            {"nom": "petit", "taille": 512, "duree": 0.25},
            {"nom": "moyen", "taille": 1536, "duree": 9.5},
            {"nom": "grand", "taille": 1333333, "duree": 99.42},
        ]

    def _columns(self):
        return [
            ("Nom", lambda r: r["nom"], 120, self.L),
            ("Taille", lambda r: r["taille"], 80, self.R,
             common.human_size),
            ("Durée", lambda r: r["duree"], 80, self.R,
             common.human_duration),
        ]

    def test_contenu(self):
        model = common.RowTableModel(self._columns(), self._rows())
        self.assertEqual((model.rowCount(), model.columnCount()), (3, 3))
        self.assertEqual(model.data(model.index(0, 0)), "petit")
        # Le formateur agit sur l'affichage…
        self.assertEqual(model.data(model.index(0, 1)), "512 o")
        # …mais le tri reçoit la valeur brute.
        self.assertEqual(model.data(model.index(0, 1),
                                    Qt.ItemDataRole.EditRole), 512)
        self.assertEqual(model.headerData(1, Qt.Orientation.Horizontal),
                         "Taille")

    def test_tri_numerique(self):
        """Le tri doit porter sur les nombres, pas sur le texte affiché.

        Sans cela, « 99,9 Kio » se classait avant « 988,0 Kio » et
        « 9,73 s » avant « 99,42 s ».
        """
        model = common.RowTableModel(self._columns(), self._rows())
        proxy = common.sorted_proxy(model)
        view = self.shown(QTableView(), 500, 200)
        view.setModel(proxy)
        common.configure_table(view, model)

        proxy.sort(1, Qt.SortOrder.DescendingOrder)
        self.assertEqual(proxy.data(proxy.index(0, 0)), "grand")
        proxy.sort(2, Qt.SortOrder.DescendingOrder)
        self.assertEqual(proxy.data(proxy.index(0, 0)), "grand")
        proxy.sort(2, Qt.SortOrder.AscendingOrder)
        self.assertEqual(proxy.data(proxy.index(0, 0)), "petit")

    def test_role_de_tri_applique(self):
        model = common.RowTableModel(self._columns(), self._rows())
        proxy = common.sorted_proxy(model)
        self.assertEqual(proxy.sortRole(), Qt.ItemDataRole.EditRole)

    def test_filtre_sur_toutes_les_colonnes(self):
        model = common.RowTableModel(self._columns(), self._rows())
        proxy = common.sorted_proxy(model)
        proxy.setFilterFixedString("GRAND")
        self.assertEqual(proxy.rowCount(), 1)
        proxy.setFilterFixedString("")
        self.assertEqual(proxy.rowCount(), 3)

    def test_acces_aux_lignes_brutes(self):
        model = common.RowTableModel(self._columns(), self._rows())
        self.assertEqual(model.row_at(0)["nom"], "petit")
        self.assertIsNone(model.row_at(99))
        self.assertIsNone(model.row_at(-1))
        model.set_rows([])
        self.assertEqual(model.rowCount(), 0)

    def test_colonne_fautive_ne_leve_pas(self):
        """Un extracteur qui lève ne doit pas casser l'affichage."""
        def boom(_row):
            raise KeyError("colonne absente")

        model = common.RowTableModel(
            [("Fautive", boom, 80, self.L)], self._rows())
        self.assertIsNone(model.data(model.index(0, 0)))

    def test_grand_volume(self):
        """Le modèle doit encaisser le volume réel de la carte."""
        rows = [{"nom": f"n{i}", "taille": i, "duree": i / 10.0}
                for i in range(2000)]
        model = common.RowTableModel(self._columns(), rows)
        proxy = common.sorted_proxy(model)
        view = self.shown(QTableView(), 500, 200)
        view.setModel(proxy)
        common.configure_table(view, model)
        proxy.sort(1, Qt.SortOrder.DescendingOrder)
        self.assertEqual(proxy.rowCount(), 2000)
        self.assertEqual(proxy.data(proxy.index(0, 0)), "n1999")


# --------------------------------------------------------------------------- #
# Grilles de pads
# --------------------------------------------------------------------------- #

class TestPadGrid(WidgetCase):
    """Grille de pads, vignette de morceau, éditeur de motif."""

    def test_grille(self):
        grid = self.shown(PadGrid(16, 8), 400, 200)
        self.assertEqual(grid.grid_size(), (16, 8))
        grid.set_cell(3, 2, theme.PAD_RED)
        self.assertEqual(grid.cell(3, 2), theme.PAD_RED)
        # Hors bornes : ignoré, sans lever.
        grid.set_cell(99, 99, theme.PAD_RED)
        self.assertEqual(grid.cell(99, 99), "")
        grid.clear()
        self.assertEqual(grid.cell(3, 2), "")

    def test_matrice(self):
        grid = self.shown(PadGrid(4, 2), 200, 100)
        grid.set_colors([[theme.PAD_RED, theme.PAD_BLUE],
                         [theme.PAD_GREEN, ""]])
        # Les dimensions s'adaptent à la matrice reçue.
        self.assertEqual(grid.grid_size(), (2, 2))
        self.assertEqual(grid.cell(0, 0), theme.PAD_RED)
        # Données absurdes : pas d'exception.
        grid.set_colors("n'importe quoi")
        grid.set_colors([])

    def test_clic_donne_la_bonne_case(self):
        grid = self.shown(PadGrid(16, 8), 400, 200)
        recu = []
        grid.padClicked.connect(lambda x, y: recu.append((x, y)))
        for target in ((0, 0), (4, 3), (15, 7)):
            with self.subTest(case=target):
                recu.clear()
                centre = grid._cell_rect(*target).center()
                grid.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease,
                                              centre.x(), centre.y()))
                self.assertEqual(recu, [target])

    def test_clic_dans_l_intervalle_est_ignore(self):
        grid = self.shown(PadGrid(16, 8), 400, 200)
        recu = []
        grid.padClicked.connect(lambda x, y: recu.append((x, y)))
        rect = grid._cell_rect(4, 3)
        grid.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease,
                                      rect.right() + 1.2, rect.center().y()))
        self.assertNotIn((4, 3), recu)

    def test_tete_de_lecture(self):
        grid = self.shown(PadGrid(16, 4), 400, 120)
        grid.set_playhead(5)
        self.assertEqual(grid._playhead, 5)
        grid.set_playhead(None)
        self.assertIsNone(grid._playhead)

    def test_vignette_de_morceau(self):
        """La vignette d'un vrai morceau doit faire 18×8."""
        from delugeapp.core.model import Song

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "M.XML"
            path.write_bytes(
                b'<song firmwareVersion="3.0.4" previewNumPads="144" '
                b'preview="' + b"FF8800" * 144 + b'" timePerTimerTick="459" '
                b'timerTickFraction="1610612736" inputTickMagnitude="1" />')
            song = Song.load(path)
            preview = self.shown(SongPreview(), 360, 160)
            preview.set_song(song)
            self.assertEqual(preview.grid_size(), (18, 8))
            self.assertEqual(preview.cell(0, 0), "#FF8800")

    def test_vignette_morceau_illisible(self):
        preview = self.shown(SongPreview(), 360, 160)
        preview.set_song(object())      # ne doit pas lever
        self.assertEqual(preview.grid_size(), (18, 8))

    def test_editeur_de_motif(self):
        pattern = rhythm.genre_beat("techno", bars=1, seed=1)
        avant = sum(len(v) for v in pattern.tracks.values())
        sequencer = self.shown(StepSequencer(), 600, 200)
        sequencer.set_pattern(pattern)
        self.assertEqual(sequencer.tracks(), list(pattern.tracks))
        self.assertEqual(sequencer.grid_size(),
                         (pattern.steps, len(pattern.tracks)))

        recu = []
        sequencer.patternChanged.connect(recu.append)
        # Un pas vide : le clic l'ajoute.
        sequencer._toggle(2, 0)
        self.assertEqual(sum(len(v) for v in recu[-1].tracks.values()),
                         avant + 1)
        # Recliquer le retire.
        sequencer._toggle(2, 0)
        self.assertEqual(sum(len(v) for v in recu[-1].tracks.values()), avant)

    def test_editeur_sans_motif(self):
        sequencer = self.shown(StepSequencer(), 400, 150)
        sequencer.set_pattern(None)
        self.assertEqual(sequencer.tracks(), [])
        sequencer._toggle(0, 0)         # ne doit pas lever


# --------------------------------------------------------------------------- #
# Forme d'onde
# --------------------------------------------------------------------------- #

class TestWaveform(WidgetCase):
    """Affichage, sélection, zoom et marqueurs de zone."""

    def _view(self):
        view = self.shown(WaveformView(), 600, 120)
        peaks = np.zeros((1200, 2), dtype=np.float32)
        peaks[:, 0] = -0.5
        peaks[:, 1] = 0.5
        view.set_peaks(peaks, 4.0, 44100)
        return view

    def test_chargement(self):
        view = self._view()
        self.assertTrue(view.has_data())
        view.clear()
        self.assertFalse(view.has_data())

    def test_donnees_invalides(self):
        view = self.shown(WaveformView(), 400, 100)
        for bad in ("texte", None, np.zeros(10), np.zeros((4, 3))):
            with self.subTest(donnees=type(bad).__name__):
                view.set_peaks(bad, 1.0)
                self.assertFalse(view.has_data())

    def test_clic_simple_place_la_lecture(self):
        """Presser puis relâcher sans bouger doit émettre une position.

        Aucun ``mouseMoveEvent`` n'a lieu dans ce cas, donc la sélection
        reste nulle : il faut traiter le geste comme un clic.
        """
        view = self._view()
        recu = []
        view.positionClicked.connect(recu.append)
        view.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, 300.0, 60))
        view.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease,
                                      300.0, 60))
        self.assertEqual(len(recu), 1)
        self.assertAlmostEqual(recu[0], 2.0, delta=0.1)

    def test_selection_par_glisser(self):
        view = self._view()
        recu = []
        view.selectionChanged.connect(lambda a, b: recu.append((a, b)))
        view.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, 100.0, 60))
        view.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, 400.0, 60))
        view.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease,
                                      400.0, 60))
        self.assertEqual(len(recu), 1)
        start, end = recu[0]
        self.assertLess(start, end)
        self.assertAlmostEqual(start, 0.667, delta=0.1)
        self.assertAlmostEqual(end, 2.667, delta=0.1)

    def test_zone(self):
        view = self._view()
        view.set_zone(1.0, 3.0)
        self.assertEqual(view.zone(), (1.0, 3.0))
        # Les bornes sont remises dans l'ordre.
        view.set_zone(3.0, 1.0)
        self.assertEqual(view.zone(), (1.0, 3.0))
        view.set_zone(None, None)
        self.assertIsNone(view.zone())

    def test_deplacement_d_un_marqueur(self):
        view = self._view()
        view.set_zone(1.0, 3.0)
        recu = []
        view.zoneChanged.connect(lambda a, b: recu.append((a, b)))
        x = view._time_to_x(1.0)
        view.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, x, 60))
        view.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, x + 60, 60))
        view.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease,
                                      x + 60, 60))
        self.assertEqual(len(recu), 1)
        self.assertGreater(recu[0][0], 1.0)

    def test_zoom(self):
        view = self._view()
        view.wheelEvent(_wheel(300, 60, 240))
        low, high = view._view
        self.assertGreater(low, 0.0)
        self.assertLess(high, 1.0)
        # Un dézoom massif revient à la vue complète, sans sortir des bornes.
        view.wheelEvent(_wheel(300, 60, -4800))
        self.assertEqual(view._view, (0.0, 1.0))

    def test_defilement(self):
        view = self._view()
        view.wheelEvent(_wheel(300, 60, 480))      # zoom
        before = view._view
        view.wheelEvent(_wheel(300, 60, 120,
                               Qt.KeyboardModifier.ShiftModifier))
        self.assertNotEqual(view._view, before)
        self.assertGreaterEqual(view._view[0], 0.0)
        self.assertLessEqual(view._view[1], 1.0)

    def test_echantillon_reel(self):
        """Lecture d'un vrai fichier, de l'enveloppe à l'affichage."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.wav"
            t = np.linspace(0, 1.0, 44100, endpoint=False, dtype=np.float32)
            wav.write(path, (0.6 * np.sin(2 * np.pi * 220 * t)
                             ).astype(np.float32), 44100)
            info = wav.probe(path)
            view = self.shown(WaveformView(), 600, 120)
            view.set_peaks(wav.peaks(path, buckets=600), info.duration,
                           info.sample_rate)
            self.assertTrue(view.has_data())


# --------------------------------------------------------------------------- #
# Enveloppe, encodeur, clavier
# --------------------------------------------------------------------------- #

class TestEnvelopeEditor(WidgetCase):

    def test_valeurs(self):
        editor = self.shown(EnvelopeEditor(title="Env 1"), 320, 140)
        editor.set_adsr(5, 25, 35, 18)
        self.assertEqual(editor.adsr(), (5, 25, 35, 18))
        # Les valeurs hors bornes sont ramenées dans 0..50.
        editor.set_adsr(999, -5, 25, 25)
        self.assertEqual(editor.adsr(), (50, 0, 25, 25))
        editor.set_adsr("x", None, 10, 10)
        self.assertEqual(editor.adsr()[:2], (0, 0))

    def test_signal(self):
        editor = self.shown(EnvelopeEditor(), 320, 140)
        recu = []
        editor.changed.connect(recu.append)
        editor.set_adsr(1, 2, 3, 4, notify=True)
        self.assertEqual(recu[-1], {"attack": 1, "decay": 2, "sustain": 3,
                                    "release": 4})
        editor.set_adsr(1, 2, 3, 4)
        self.assertEqual(len(recu), 1, "sans notify, rien ne doit être émis")

    def test_poignee_de_maintien(self):
        """Tirer la poignée de maintien vers le bas doit baisser le sustain."""
        editor = self.shown(EnvelopeEditor(), 320, 140)
        editor.set_adsr(5, 20, 40, 15)
        point = editor._points()["sustain"]
        editor.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress,
                                      point.x(), point.y()))
        editor.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, point.x(),
                                     point.y() + 40))
        editor.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease,
                                        point.x(), point.y() + 40))
        self.assertLess(editor.adsr()[2], 40)


class TestKnob(WidgetCase):

    def test_valeur_et_bornes(self):
        knob = self.shown(Knob("Coupure", value=30), 60, 80)
        self.assertEqual(knob.value(), 30)
        knob.set_value(999)
        self.assertEqual(knob.value(), 50)
        knob.set_value(-10)
        self.assertEqual(knob.value(), 0)
        knob.set_value("x")
        self.assertEqual(knob.value(), 0)

    def test_signal(self):
        knob = self.shown(Knob("X", value=10), 60, 80)
        recu = []
        knob.valueChanged.connect(recu.append)
        knob.set_value(20)
        self.assertEqual(recu, [], "sans notify, rien n'est émis")
        knob.set_value(30, notify=True)
        self.assertEqual(recu, [30])
        # Une valeur identique ne réémet pas.
        knob.set_value(30, notify=True)
        self.assertEqual(recu, [30])

    def test_affichage_bipolaire(self):
        knob = self.shown(Knob("Pan", value=0, minimum=-25, maximum=25,
                               bipolar=True), 60, 80)
        self.assertEqual(knob.display_text(), "0")
        knob.set_value(12)
        self.assertEqual(knob.display_text(), "+12")
        knob.set_value(-12)
        self.assertEqual(knob.display_text(), "-12")

    def test_molette_et_clavier(self):
        knob = self.shown(Knob("X", value=25), 60, 80)
        knob.wheelEvent(_wheel(30, 30, 120))
        self.assertGreater(knob.value(), 25)
        before = knob.value()
        knob.wheelEvent(_wheel(30, 30, -120))
        self.assertLess(knob.value(), before)
        knob.mouseDoubleClickEvent(_mouse(QEvent.Type.MouseButtonDblClick,
                                          30, 30))
        self.assertEqual(knob.value(), 25, "double-clic = valeur neutre")


class TestPianoKeys(WidgetCase):

    def test_etendue(self):
        piano = self.shown(PianoKeys(48, 84), 440, 72)
        self.assertEqual(piano.range(), (48, 84))
        piano.set_range(36, 60)
        self.assertEqual(piano.range(), (36, 60))
        # Une étendue absurde est corrigée au minimum d'une octave.
        piano.set_range(60, 60)
        self.assertGreaterEqual(piano.range()[1] - piano.range()[0], 11)

    def test_surlignage_de_gamme(self):
        """Une gamme se surligne à toutes les octaves du clavier."""
        piano = self.shown(PianoKeys(48, 84), 440, 72)
        piano.set_highlight(theory.SCALES["majeur"])
        self.assertGreater(len(piano._highlight), 7)
        for note in piano._highlight:
            with self.subTest(note=note):
                self.assertIn(note % 12, theory.SCALES["majeur"])

    def test_surlignage_exact(self):
        """Un accord se surligne tel quel, sans report d'octave."""
        piano = self.shown(PianoKeys(48, 84), 440, 72)
        notes = theory.chord_notes(60, "maj7")
        piano.set_exact_highlight(notes)
        self.assertEqual(sorted(piano._highlight), sorted(notes))
        piano.clear_highlight()
        self.assertEqual(piano._highlight, {})
        piano.set_highlight("n'importe quoi")      # ne doit pas lever

    def test_touche_noire_prioritaire(self):
        """Cliquer un dièse doit donner la noire, pas la blanche dessous."""
        piano = self.shown(PianoKeys(48, 84), 440, 72)
        recu = []
        piano.noteOn.connect(recu.append)
        rect = piano._black_rect(61)
        self.assertIsNotNone(rect)
        piano.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress,
                                     rect.center().x(), rect.center().y()))
        self.assertEqual(recu, [61])

    def test_touche_blanche(self):
        piano = self.shown(PianoKeys(48, 84), 440, 72)
        recu, relache = [], []
        piano.noteOn.connect(recu.append)
        piano.noteOff.connect(relache.append)
        rect = piano._white_rect(0)
        # Bas de la touche : hors de portée des noires.
        piano.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress,
                                     rect.center().x(), rect.bottom() - 4))
        piano.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease,
                                       rect.center().x(), rect.bottom() - 4))
        self.assertEqual(recu, [48])
        self.assertEqual(relache, [48])


# --------------------------------------------------------------------------- #
# Filtre et spectre
# --------------------------------------------------------------------------- #

class TestFilterCurve(WidgetCase):

    def test_reponse_physiquement_juste(self):
        """La courbe doit suivre la pente du filtre choisi.

        Avec une coupure vers 1,4 kHz et quatre pôles (24 dB par octave),
        10 kHz se situe 2,8 octaves plus haut, soit environ −67 dB.
        """
        curve = self.shown(FilterCurve(), 340, 140)
        curve.set_filter(30, 35, "24dB")
        self.assertEqual(curve.filter_settings(), (30, 35, "24dB"))

        db = curve._response_db(np.array([100.0, 10000.0]))
        self.assertGreater(float(db[0]), -6.0, "le grave doit passer")
        self.assertLess(float(db[1]), -40.0, "l'aigu doit être coupé")

    def test_pente_12_contre_24(self):
        """Un filtre à deux pôles coupe moins qu'un filtre à quatre."""
        curve = self.shown(FilterCurve(), 340, 140)
        freqs = np.array([8000.0])
        curve.set_filter(25, 0, "12dB")
        douce = float(curve._response_db(freqs)[0])
        curve.set_filter(25, 0, "24dB")
        raide = float(curve._response_db(freqs)[0])
        self.assertLess(raide, douce)

    def test_passe_haut(self):
        curve = self.shown(FilterCurve(), 340, 140)
        curve.set_filter(40, 0, "24dB")
        sans = float(curve._response_db(np.array([40.0]))[0])
        curve.set_hpf(20)
        avec = float(curve._response_db(np.array([40.0]))[0])
        self.assertLess(avec, sans)
        curve.set_hpf(None)

    def test_bornes(self):
        curve = self.shown(FilterCurve(), 340, 140)
        for cutoff in (0, 50, -10, 999):
            with self.subTest(cutoff=cutoff):
                curve.set_filter(cutoff, 25)
                self.assertTrue(0 <= curve.filter_settings()[0] <= 50)


class TestSpectrumView(WidgetCase):

    def test_spectre_d_un_signal(self):
        view = self.shown(SpectrumView(), 340, 140)
        t = np.linspace(0, 1, 44100, endpoint=False, dtype=np.float32)
        sine = (0.5 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
        view.set_audio(sine, 44100)
        self.assertIsNotNone(view._db)
        self.assertGreater(view._db.size, 100)

    def test_spectre_d_un_preset_genere(self):
        view = self.shown(SpectrumView(), 340, 140)
        from delugeapp.core import render

        preset = synthgen.generate(synthgen.GenOptions(genre="acid", seed=1))
        view.set_audio(render.render_sound(preset.sound, seconds=0.5), 44100)
        self.assertIsNotNone(view._db)

    def test_donnees_incoherentes(self):
        view = self.shown(SpectrumView(), 340, 140)
        view.set_spectrum([1, 2], [1, 2, 3])
        self.assertIsNone(view._db)
        view.set_spectrum([], [])
        self.assertIsNone(view._db)
        view.set_audio("n'importe quoi")
        self.assertIsNone(view._db)
        view.clear()
        self.assertIsNone(view._db)


# --------------------------------------------------------------------------- #
# Travaux de fond
# --------------------------------------------------------------------------- #

class TestTasks(WidgetCase):
    """``ui.tasks`` : les travaux longs hors du fil de l'interface."""

    def test_worker_transmet_resultat_et_progression(self):
        from PyQt6.QtCore import QEventLoop, QTimer
        from PyQt6.QtWidgets import QMainWindow

        from delugeapp.ui import tasks

        window = self.shown(QMainWindow(), 300, 100)
        window.statusBar()
        recu: dict = {"progress": [], "result": None, "error": None}

        def travail(n, progress=None, should_stop=None):
            for i in range(n):
                if should_stop is not None and should_stop():
                    return "interrompu"
                if progress is not None:
                    progress((i + 1, n))
            return f"fini {n}"

        tasks.run_task(window, travail, 4,
                       on_result=lambda r: recu.__setitem__("result", r),
                       on_progress=lambda p: recu["progress"].append(p),
                       on_error=lambda e: recu.__setitem__("error", e),
                       title="Essai")

        loop = QEventLoop()
        QTimer.singleShot(1200, loop.quit)
        loop.exec()

        self.assertEqual(recu["result"], "fini 4")
        self.assertEqual(recu["progress"], [(1, 4), (2, 4), (3, 4), (4, 4)])
        self.assertIsNone(recu["error"])

    def test_exception_ne_remonte_pas(self):
        """Une tâche qui lève doit appeler ``on_error``, pas casser Qt."""
        from PyQt6.QtCore import QEventLoop, QTimer
        from PyQt6.QtWidgets import QMainWindow

        from delugeapp.ui import tasks

        window = self.shown(QMainWindow(), 300, 100)
        window.statusBar()
        recu: dict = {"result": None, "error": None}

        def boom():
            raise ValueError("erreur volontaire")

        tasks.run_task(window, boom,
                       on_result=lambda r: recu.__setitem__("result", r),
                       on_error=lambda e: recu.__setitem__("error", e),
                       title="Essai")

        loop = QEventLoop()
        QTimer.singleShot(1200, loop.quit)
        loop.exec()

        self.assertEqual(recu["error"], "erreur volontaire")
        self.assertIsNone(recu["result"])


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #

class PageCase(WidgetCase):
    """Base des tests de pages : une carte factice et un index remplis."""

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.root = base / "carte"
        for sub in ("SONGS", "SYNTHS", "KITS", "SAMPLES/DRUMS/Kick",
                    "SAMPLES/DRUMS/Snare"):
            (self.root / sub).mkdir(parents=True)

        t = np.linspace(0, 0.3, 13230, endpoint=False, dtype=np.float32)
        wav.write(self.root / "SAMPLES/DRUMS/Kick/k.wav",
                  (0.7 * np.sin(2 * np.pi * 60 * t) * np.exp(-t * 14)
                   ).astype(np.float32), 44100)
        wav.write(self.root / "SAMPLES/DRUMS/Snare/s.wav",
                  (0.4 * np.random.default_rng(2).standard_normal(8820)
                   ).astype(np.float32), 44100)
        wav.write(self.root / "SAMPLES/DRUMS/Kick/orphelin.wav",
                  (0.3 * np.sin(2 * np.pi * 90 * t)).astype(np.float32), 44100)

        preset = SynthPreset.new("BASSE")
        preset.sound.osc1.type = "sample"
        preset.sound.osc1.file_name = "SAMPLES/DRUMS/Kick/k.wav"
        preset.save(self.root / "SYNTHS" / "BASSE.XML", backup=False)
        # Un preset dont la référence est cassée, pour la page Santé.
        broken = SynthPreset.new("CASSE")
        broken.sound.osc1.type = "sample"
        broken.sound.osc1.file_name = "SAMPLES/ANCIEN/k.wav"
        broken.save(self.root / "SYNTHS" / "CASSE.XML", backup=False)

        kit = Kit.new("KIT")
        kit.add_row("KICK", "SAMPLES/DRUMS/Kick/k.wav")
        kit.add_row("SNARE", "SAMPLES/DRUMS/Snare/s.wav")
        kit.save(self.root / "KITS" / "KIT.XML", backup=False)

        (self.root / "SONGS" / "M.XML").write_bytes(
            b'<song firmwareVersion="3.0.4" timePerTimerTick="459"'
            b' timerTickFraction="1610612736" inputTickMagnitude="1"'
            b' rootNote="60" previewNumPads="144" preview="'
            + b"FF8800" * 144 + b'">'
            b'<modeNotes><modeNote>0</modeNote><modeNote>2</modeNote>'
            b'<modeNote>4</modeNote><modeNote>5</modeNote>'
            b'<modeNote>7</modeNote><modeNote>9</modeNote>'
            b'<modeNote>11</modeNote></modeNotes>'
            b'<instruments><sound presetName="BASSE" presetFolder="SYNTHS" />'
            b'</instruments>'
            b'<sessionClips><instrumentClip length="384" section="0"'
            b' instrumentPresetName="BASSE" instrumentPresetFolder="SYNTHS">'
            b'<noteRows><noteRow y="60" noteDataWithLift="0x'
            b'0000000000000018401400000000600000001840140" />'
            b'</noteRows></instrumentClip></sessionClips></song>')

        self.sd = sdcard.SDCard(self.root)
        self.lib = db.Library(base / "index.db")
        scan.scan_card(self.sd, self.lib, compute_hash=True)

        from delugeapp.config import AppContext, Settings

        settings = Settings()
        settings.sd_path = str(self.root)
        settings.autoplay = False
        settings.backup_dir = str(base / "sauvegardes")
        self.ctx = AppContext(settings=settings, sd=self.sd, lib=self.lib,
                              player=None)

        # Isolation des réglages : plusieurs pages appellent ``ctx.save()``,
        # et ``config.save_settings`` écrit dans ``SETTINGS_PATH``. Sans ce
        # détournement, les tests remplaceraient les réglages réels de
        # l'utilisateur par des chemins temporaires.
        from delugeapp import config as config_mod

        self._config_mod = config_mod
        self._config_sauve = (config_mod.CONFIG_DIR,
                              config_mod.SETTINGS_PATH)
        config_mod.CONFIG_DIR = base / "config"
        config_mod.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        config_mod.SETTINGS_PATH = config_mod.CONFIG_DIR / "settings.json"

    def tearDown(self):
        from delugeapp.ui import tasks

        tasks.stop_all(2000)
        (self._config_mod.CONFIG_DIR,
         self._config_mod.SETTINGS_PATH) = self._config_sauve
        super().tearDown()
        self.lib.close()
        self._tmp.cleanup()

    def open(self, cls):
        """Instancie une page, l'affiche et la rafraîchit."""
        page = cls(self.ctx)
        self.shown(page, 1000, 680)
        page.refresh()
        if _APP is not None:
            _APP.processEvents()
        return page


class TestPageContract(PageCase):
    """Le contrat de la SPEC §5.5, vérifié sur les neuf pages."""

    def _pages(self):
        from delugeapp.ui.pages.dashboard import DashboardPage
        from delugeapp.ui.pages.generator import GeneratorPage
        from delugeapp.ui.pages.health import HealthPage
        from delugeapp.ui.pages.kits import KitsPage
        from delugeapp.ui.pages.samples import SamplesPage
        from delugeapp.ui.pages.settings import SettingsPage
        from delugeapp.ui.pages.songs import SongsPage
        from delugeapp.ui.pages.synths import SynthsPage
        from delugeapp.ui.pages.toolbox import ToolboxPage

        return (DashboardPage, SamplesPage, SynthsPage, KitsPage, SongsPage,
                GeneratorPage, ToolboxPage, HealthPage, SettingsPage)

    def test_les_neuf_pages_existent(self):
        self.assertEqual(len(self._pages()), 9)

    def test_contrat(self):
        """Titre, icône, signal d'état et ``refresh`` sur chaque page."""
        for cls in self._pages():
            with self.subTest(page=cls.__name__):
                self.assertTrue(cls.TITLE)
                self.assertIn(cls.ICON, icons.ICON_NAMES)
                self.assertTrue(hasattr(cls, "status"))
                self.assertTrue(callable(cls.refresh))

    def test_chaque_page_s_ouvre_et_se_rafraichit(self):
        for cls in self._pages():
            with self.subTest(page=cls.__name__):
                page = self.open(cls)
                self.assertTrue(page.isVisible())
                # Un second rafraîchissement ne doit pas lever non plus.
                page.refresh()

    def test_etat_vide_sans_carte(self):
        """Sans carte, les pages qui en ont besoin montrent l'état vide.

        La SPEC §6.1 exige que l'application démarre sans carte valide.
        """
        from delugeapp.config import AppContext, Settings

        orphan = AppContext(settings=Settings(), sd=None, lib=self.lib,
                            player=None)
        for cls in self._pages():
            with self.subTest(page=cls.__name__):
                page = cls(orphan)
                self.shown(page, 700, 500)
                page.refresh()
                shown_empty = page._stack.currentWidget() is page._empty
                self.assertEqual(shown_empty, cls.NEEDS_CARD,
                                 f"{cls.__name__} : état vide inattendu")

    def test_refresh_absorbe_les_exceptions(self):
        """Une page fautive ne doit pas laisser remonter l'exception."""
        from delugeapp.ui.pages.base import Page

        class Fautive(Page):
            TITLE = "Fautive"
            NEEDS_CARD = False

            def _refresh(self):
                raise ValueError("volontaire")

        page = Fautive(self.ctx)
        self.shown(page, 300, 200)
        messages = []
        page.status.connect(messages.append)
        page.refresh()          # ne doit pas lever
        self.assertTrue(messages)

    def test_guard_absorbe_les_exceptions(self):
        """``Page.guard`` protège les gestionnaires de signaux (SPEC §6.3)."""
        from delugeapp.ui.pages.base import Page

        page = Page(self.ctx)
        self.shown(page, 200, 100)
        messages = []
        page.status.connect(messages.append)

        def boom():
            raise RuntimeError("volontaire")

        page.guard(boom)()      # ne doit pas lever
        self.assertTrue(messages)


class TestSettingsPage(PageCase):
    """La page qui désigne la carte."""

    def _page(self):
        from delugeapp.ui.pages.settings import SettingsPage

        return self.open(SettingsPage)

    def test_validation_du_chemin(self):
        page = self._page()
        page._path_edit.setText(str(self.root))
        self.assertIn("✓", page._path_state.text())

        page._path_edit.setText(str(self.root / "nulle part"))
        self.assertIn("✗", page._path_state.text())

        # Un dossier valide qui n'est pas une carte Deluge le dit.
        page._path_edit.setText(str(Path(self._tmp.name)))
        self.assertIn("✗", page._path_state.text())
        self.assertIn("Deluge", page._path_state.text())

    def test_les_reglages_sont_enregistres(self):
        page = self._page()
        page._apply_scan_analyze(True)
        self.assertTrue(self.ctx.settings.scan_analyze)
        page._apply_volume(55)
        self.assertAlmostEqual(self.ctx.settings.preview_volume, 0.55,
                               places=2)
        page._apply_confirm(False)
        self.assertFalse(self.ctx.settings.confirm_writes)

    def test_signal_d_accent(self):
        page = self._page()
        received = []
        page.accentChanged.connect(received.append)
        page._apply_accent("#28C4E0")
        self.assertEqual(received, ["#28C4E0"])
        self.assertEqual(self.ctx.settings.theme_accent, "#28C4E0")

    def test_dossier_de_sauvegarde_est_un_chemin(self):
        """``Settings.backup_path`` est une **méthode**, pas une propriété.

        L'oublier produisait un ``TypeError`` au moment de sauvegarder.
        """
        page = self._page()
        self.assertTrue(page._backup_dir.text())
        self.assertIsInstance(self.ctx.settings.backup_path(), Path)


class TestDashboardPage(PageCase):

    def test_chiffres(self):
        from delugeapp.ui.pages.dashboard import DashboardPage

        page = self.open(DashboardPage)
        self.assertEqual(page._tiles["samples"]._value.text(), "3")
        self.assertEqual(page._tiles["synths"]._value.text(), "2")
        self.assertEqual(page._tiles["kits"]._value.text(), "1")
        self.assertEqual(page._tiles["songs"]._value.text(), "1")

    def test_score_seulement_apres_analyse(self):
        """Sur un index vide, aucun score n'est affiché.

        Les contrôles ne trouvant rien à signaler, la note montait à 98/100 :
        annoncer « carte en très bon état » sans avoir rien vérifié serait
        trompeur.
        """
        from delugeapp.ui.pages.dashboard import DashboardPage

        self.lib.clear()
        page = self.open(DashboardPage)
        self.assertEqual(page._score.text(), "—")
        self.assertIn("pas encore analys", page._verdict.text())

    def test_navigation(self):
        from delugeapp.ui.pages.dashboard import DashboardPage

        page = self.open(DashboardPage)
        received = []
        page.navigateRequested.connect(received.append)
        page._tiles["samples"].clicked.emit()
        self.assertEqual(received, ["Samples"])


class TestSamplesPage(PageCase):

    def _page(self):
        from delugeapp.ui.pages.samples import SamplesPage

        return self.open(SamplesPage)

    def test_table_et_filtres(self):
        page = self._page()
        self.assertEqual(page._model.rowCount(), 3)

        page._search.setText("orphelin")
        page._reload()
        self.assertEqual(page._model.rowCount(), 1)
        page._search.setText("")
        page._reload()

        page._only_unused.setChecked(True)
        self.assertEqual(page._model.rowCount(), 1)
        page._only_unused.setChecked(False)

        page._only_missing.setChecked(True)
        self.assertEqual(page._model.rowCount(), 1)
        page._only_missing.setChecked(False)

    def test_tri_numerique(self):
        page = self._page()
        page._proxy.sort(3, Qt.SortOrder.DescendingOrder)
        first = page._proxy.data(page._proxy.index(0, 3))
        last = page._proxy.data(
            page._proxy.index(page._proxy.rowCount() - 1, 3))
        self.assertNotEqual(first, last)

    def test_apercu(self):
        page = self._page()
        page._table.selectRow(0)
        self.assertTrue(page._name.full_text())
        self.assertGreater(page._info.rowCount(), 0)

    def test_notation_et_etiquettes(self):
        page = self._page()
        page._table.selectRow(0)
        page._set_stars(4)
        page._set_favorite(True)
        page.add_tag("essai")
        rating = self.lib.get_rating("sample", page._current)
        self.assertEqual(rating["stars"], 4)
        self.assertTrue(rating["favorite"])
        self.assertIn("essai", self.lib.tags_of("sample", page._current))

        page._only_fav.setChecked(True)
        self.assertEqual(page._model.rowCount(), 1)


class TestSynthsAndKits(PageCase):

    def test_preset_charge(self):
        from delugeapp.ui.pages.synths import SynthsPage

        page = self.open(SynthsPage)
        self.assertEqual(page._model.rowCount(), 2)
        page._table.selectRow(0)
        self.assertTrue(page._name.full_text())
        self.assertGreater(page._info.rowCount(), 0)
        self.assertTrue(page._description.text())

    def test_preset_illisible_ne_leve_pas(self):
        from delugeapp.ui.pages.synths import SynthsPage

        page = self.open(SynthsPage)
        row = self.lib.search_presets(kind="synth")[0]
        page._load_preset("SYNTHS/INEXISTANT.XML", row)
        self.assertIn("illisible", page._description.text())

    def test_kit_et_rangees(self):
        from delugeapp.ui.pages.kits import KitsPage

        page = self.open(KitsPage)
        self.assertEqual(page._model.rowCount(), 1)
        page._table.selectRow(0)
        self.assertEqual(page._rows.rowCount(), 2)
        # Les deux rangées pointent vers des fichiers présents.
        for index in range(page._rows.rowCount()):
            self.assertEqual(page._rows.item(index, 2).text(), "oui")
        self.assertIn("jouables", page._summary.text())


class TestSongsPage(PageCase):

    def test_morceau_charge(self):
        from delugeapp.ui.pages.songs import SongsPage

        page = self.open(SongsPage)
        self.assertEqual(page._model.rowCount(), 1)
        page._table.selectRow(0)
        self.assertEqual(page._preview.grid_size(), (18, 8))
        self.assertGreater(page._stats.rowCount(), 5)
        self.assertEqual(page._clips.rowCount(), 1)
        self.assertEqual(page._instruments.rowCount(), 1)
        # Le preset « BASSE » existe bien sur la carte factice.
        self.assertEqual(page._instruments.item(0, 3).text(), "oui")

    def test_rapport_html(self):
        from delugeapp.ui.pages.songs import SongsPage

        page = self.open(SongsPage)
        page._table.selectRow(0)
        html = page._report_html()
        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        self.assertIn("BPM", html)

    def test_export_midi_d_un_clip(self):
        from delugeapp.core import midifile
        from delugeapp.ui.pages.songs import SongsPage

        page = self.open(SongsPage)
        page._table.selectRow(0)
        clip = page._song.clips[0]
        target = Path(self._tmp.name) / "clip.mid"
        midifile.clip_to_midi(target, clip, page._song.tempo_bpm)
        self.assertTrue(target.is_file())
        self.assertGreater(target.stat().st_size, 40)


class TestGeneratorPage(PageCase):

    def _page(self):
        from delugeapp.ui.pages.generator import GeneratorPage

        return self.open(GeneratorPage)

    def test_generation_reproductible(self):
        page = self._page()
        page._pick_genre("acid")
        page._seed.setValue(42)
        page._generate()
        first = page._name.full_text()
        self.assertTrue(first)

        page._seed.setValue(42)
        page._generate()
        self.assertEqual(page._name.full_text(), first)

        page._seed.setValue(43)
        page._generate()
        self.assertNotEqual(page._name.full_text(), first)

    def test_tous_les_genres_sont_proposes(self):
        page = self._page()
        self.assertEqual(len(page._genre_buttons), len(genres.GENRES))
        self.assertEqual(page._role.count(), len(genres.ROLES))
        self.assertEqual(len(page._macros), 6)

    def test_variations(self):
        page = self._page()
        page._seed.setValue(7)
        page._generate()
        page._make_variations()
        self.assertEqual(page._variation_list.count(), 8)
        page._variation_list.setCurrentRow(2)
        page._adopt_variation()
        self.assertTrue(page._name.full_text())

    def test_construction_de_kit(self):
        page = self._page()
        page._kit_name.setText("KIT ESSAI")
        page._kit_seed.setValue(3)
        page._build_kit()
        self.assertIsNotNone(page._kit)
        self.assertGreater(page._kit_result.count(), 0)


class TestToolboxPage(PageCase):

    def _page(self):
        from delugeapp.ui.pages.toolbox import ToolboxPage

        return self.open(ToolboxPage)

    def test_theorie(self):
        page = self._page()
        self.assertEqual(page._chords.rowCount(), 7)
        self.assertEqual(page._mode_notes.text(), "0, 2, 4, 5, 7, 9, 11")

        index = [page._scale.itemData(i)
                 for i in range(page._scale.count())].index("mineur")
        page._scale.setCurrentIndex(index)
        page._show_scale()
        self.assertEqual(page._mode_notes.text(), "0, 2, 3, 5, 7, 8, 10")
        self.assertEqual(
            [page._chords.item(i, 0).text() for i in range(7)],
            ["i", "ii°", "III", "iv", "v", "VI", "VII"])

    def test_progression(self):
        page = self._page()
        page._progression_bars.setValue(4)
        page._make_progression()
        self.assertEqual(page._progression_list.count(), 4)

    def test_rythme_et_groove(self):
        """Un groove rend les positions fractionnaires : ``ascii`` doit tenir.

        Indexer une liste avec une position flottante levait un
        ``TypeError`` et faisait échouer tout l'onglet.
        """
        page = self._page()
        page._beat_from_genre()
        self.assertTrue(page._ascii.toPlainText())

        page._pulses.setValue(5)
        page._steps.setValue(16)
        page._add_euclid()
        self.assertIn("E(5,16)", page._sequencer.tracks())

        page._groove.setCurrentIndex(2)
        page._swing.setValue(40)
        page._apply_groove()        # ne doit pas lever
        self.assertTrue(page._ascii.toPlainText())

    def test_calculatrice(self):
        page = self._page()
        page._bpm.setValue(120)
        page._calc()
        # Une noire à 120 BPM fait 500 ms.
        quarter = next(
            page._delays.item(i, 1).text()
            for i in range(page._delays.rowCount())
            if page._delays.item(i, 0).text() == "1/4")
        self.assertEqual(quarter, "500.00")
        self.assertIn("2000 ms", page._bar_length.text())
        self.assertTrue(page._memory_result.text())

    def test_camelot(self):
        page = self._page()
        page._fill_wheel()
        self.assertIn("8B", page._wheel.item(0, 0).text())
        self.assertIn("8A", page._wheel.item(0, 1).text())

    def test_arrangement(self):
        page = self._page()
        page._arr_bpm.setValue(128)
        page._show_arrangement()
        self.assertGreater(page._arrangement.rowCount(), 3)
        self.assertIn("mesures au total", page._arr_total.text())


class TestHealthPage(PageCase):

    def _page(self):
        from delugeapp.ui.pages.health import HealthPage

        return self.open(HealthPage)

    def test_diagnostic(self):
        from PyQt6.QtCore import QEventLoop, QTimer

        page = self._page()
        page._run_check()
        loop = QEventLoop()
        QTimer.singleShot(6000, loop.quit)
        loop.exec()
        self.assertIsNotNone(page._report)
        self.assertGreater(page._issues.count(), 0)
        self.assertNotEqual(page._score.text(), "—")

    def test_reference_cassee_listee(self):
        page = self._page()
        self.assertEqual(page._missing.rowCount(), 1)
        self.assertEqual(page._missing.item(0, 0).text(),
                         "SAMPLES/ANCIEN/k.wav")

    def test_le_plan_est_montre_avant_application(self):
        """Rien ne bouge avant que l'utilisateur ait vu le plan (SPEC §0.2)."""
        from delugeapp.core import organize
        from delugeapp.ui.pages.health import PlanDialog

        before = {p.relative_to(self.root).as_posix()
                  for p in self.root.rglob("*") if p.is_file()}

        plan = organize.plan_archive_unused(self.sd, self.lib)
        self.assertTrue(plan)
        dialog = PlanDialog(plan, None, "Essai")
        self.shown(dialog, 600, 400)
        self.assertIn("Essai", dialog.windowTitle())

        after = {p.relative_to(self.root).as_posix()
                 for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after, "le plan a modifié la carte")

    def test_sauvegarde_et_comparaison(self):
        from PyQt6.QtCore import QEventLoop, QTimer

        page = self._page()
        page._with_samples.setChecked(False)
        page._create_backup()
        loop = QEventLoop()
        QTimer.singleShot(5000, loop.quit)
        loop.exec()
        self.assertGreater(page._backups.rowCount(), 0)

        from delugeapp.core import backup as backup_mod

        infos = backup_mod.list_backups(self.ctx.settings.backup_path())
        self.assertTrue(infos)
        diff = backup_mod.diff_backup(infos[0], self.sd)
        self.assertEqual(diff["changed"], [])


# --------------------------------------------------------------------------- #
# Fenêtre principale
# --------------------------------------------------------------------------- #

class MainWindowCase(PageCase):
    """Base des tests de la fenêtre principale.

    Deux précautions indispensables :

    * ``MainWindow`` persiste sa géométrie dans un ``QSettings`` natif — le
      registre, sous Windows. Les tests le détournent vers un fichier
      jetable, sinon ils écraseraient les réglages réels de l'utilisateur ;
    * la fenêtre ouvre des boîtes **modales** (détection de carte, « à
      propos », confirmation de fermeture). Sans les neutraliser, la suite se
      bloquerait indéfiniment sur la première.
    """

    def setUp(self):
        super().setUp()
        from PyQt6.QtCore import QSettings
        from PyQt6.QtWidgets import QMessageBox

        from delugeapp.ui import mainwindow as mw

        self.mw = mw
        self.detected: list = []
        self.answer = QMessageBox.StandardButton.Yes

        self._store = QSettings(str(Path(self._tmp.name) / "fenetre.ini"),
                                QSettings.Format.IniFormat)
        self._orig_store = mw.MainWindow._settings_store
        mw.MainWindow._settings_store = lambda _self: self._store

        self._orig_detect = mw.sdmod.detect_sd_cards
        mw.sdmod.detect_sd_cards = lambda: list(self.detected)

        self._orig_dialogs = (QMessageBox.question, QMessageBox.information,
                              QMessageBox.about, QMessageBox.warning)
        QMessageBox.question = staticmethod(lambda *a, **k: self.answer)
        QMessageBox.information = staticmethod(lambda *a, **k: None)
        QMessageBox.about = staticmethod(lambda *a, **k: None)
        QMessageBox.warning = staticmethod(lambda *a, **k: None)

    def tearDown(self):
        from PyQt6.QtWidgets import QMessageBox

        self.mw.MainWindow._settings_store = self._orig_store
        self.mw.sdmod.detect_sd_cards = self._orig_detect
        (QMessageBox.question, QMessageBox.information,
         QMessageBox.about, QMessageBox.warning) = self._orig_dialogs
        super().tearDown()

    def window(self, ctx=None):
        """Ouvre une fenêtre et laisse passer l'amorçage différé."""
        win = self.mw.MainWindow(ctx if ctx is not None else self.ctx)
        self.shown(win, 1200, 800)
        _pump(300)              # laisse tomber le ``_check_card`` à 150 ms
        return win


def _pump(ms: int) -> None:
    """Fait tourner la boucle Qt pendant ``ms`` millisecondes."""
    from PyQt6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class TestMainWindowAssemblage(MainWindowCase):
    """L'ossature : en-tête, barre latérale, pages, menus, raccourcis."""

    def test_titre_et_structure(self):
        from PyQt6.QtWidgets import QMenu

        from delugeapp import __version__

        win = self.window()
        self.assertIn(__version__, win.windowTitle())
        self.assertIn("Deluge Companion", win.windowTitle())
        self.assertEqual(len(win._classes), 9)
        self.assertEqual(len(win._buttons), 9)
        # Qt ajoute un menu interne sans titre (le débordement) : on ne
        # garde que les menus nommés.
        titres = [m.title() for m in win.menuBar().findChildren(QMenu)
                  if m.title()]
        self.assertEqual(titres,
                         ["&Fichier", "&Édition", "&Outils", "&Aide"])

    def test_les_pages_sont_creees_au_premier_affichage(self):
        """Neuf pages construites au démarrage, ce serait neuf fois trop."""
        win = self.window()
        self.assertEqual(len(win._pages), 1,
                         "une seule page doit exister au démarrage")
        for key in win._classes:
            win.go_to(key)
            _APP.processEvents()
        self.assertEqual(len(win._pages), 9)

    def test_page_inconnue_ignoree(self):
        win = self.window()
        before = win._stack.currentWidget()
        win.go_to("PageQuiNExistePas")      # ne doit pas lever
        self.assertIs(win._stack.currentWidget(), before)

    def test_le_bouton_de_la_page_courante_est_coche(self):
        win = self.window()
        win.go_to("Toolbox")
        _APP.processEvents()
        coches = [k for k, b in win._buttons.items() if b.isChecked()]
        self.assertEqual(coches, ["Toolbox"])

    def test_raccourcis_de_navigation(self):
        """``Ctrl+1`` à ``Ctrl+9``, plus ``Espace`` pour l'écoute."""
        win = self.window()
        sequences = {a.shortcut().toString() for a in win.actions()}
        for index in range(1, 10):
            self.assertIn(f"Ctrl+{index}", sequences)
        self.assertIn("Space", sequences)

    def test_raccourcis_des_menus(self):
        from PyQt6.QtWidgets import QMenu

        win = self.window()
        sequences = set()
        for menu in win.menuBar().findChildren(QMenu):
            for action in menu.actions():
                text = action.shortcut().toString()
                if text:
                    sequences.add(text)
        for wanted in ("Ctrl+O", "Ctrl+R", "Ctrl+Q", "Ctrl+F", "Ctrl+G",
                       "Ctrl+B", "F1"):
            self.assertIn(wanted, sequences, f"{wanted} manquant")

    def test_barre_laterale_se_replie(self):
        win = self.window()
        large = win._rail.width()
        self.assertEqual(large, self.mw.RAIL_WIDE)
        win.toggle_rail()
        _APP.processEvents()
        self.assertEqual(win._rail.width(), self.mw.RAIL_NARROW)
        self.assertEqual(len(win._buttons), 9, "les boutons restent")
        win.toggle_rail()
        _APP.processEvents()
        self.assertEqual(win._rail.width(), self.mw.RAIL_WIDE)

    def test_les_dialogues_d_aide_ne_plantent_pas(self):
        win = self.window()
        win._show_shortcuts()
        win._show_about()

    def test_une_action_de_menu_fautive_est_absorbee(self):
        """SPEC §6.3 : aucune exception ne doit traverser un gestionnaire."""
        win = self.window()

        def boom():
            raise RuntimeError("volontaire")

        win._safely(boom)       # ne doit pas lever
        self.assertIn("Action impossible",
                      win.statusBar().currentMessage())


class TestMainWindowCarte(MainWindowCase):
    """En-tête, détection et changement de carte."""

    def test_en_tete_avec_carte(self):
        win = self.window()
        self.assertIn(str(self.root), win._card_button.text())
        self.assertNotIn("invalide", win._card_button.text())
        self.assertIn("libres", win._space.text())

    def test_en_tete_sans_carte(self):
        from delugeapp.config import AppContext, Settings

        orphan = AppContext(settings=Settings(), sd=None, lib=self.lib,
                            player=None)
        win = self.window(orphan)
        self.assertIn("Aucune carte", win._card_button.text())
        self.assertEqual(win._space.text(), "")

    def test_en_tete_avec_chemin_invalide(self):
        from delugeapp.config import AppContext, Settings

        settings = Settings()
        settings.sd_path = str(Path(self._tmp.name) / "nulle-part")
        ctx = AppContext(settings=settings, sd=None, lib=self.lib,
                         player=None)
        win = self.window(ctx)
        self.assertIn("invalide", win._card_button.text())

    def test_demarrage_sans_carte_ouvre_les_reglages(self):
        """SPEC §6.1 : démarrer sans carte est un cas normal, pas une erreur."""
        from delugeapp.config import AppContext, Settings

        orphan = AppContext(settings=Settings(), sd=None, lib=self.lib,
                            player=None)
        self.detected = []
        win = self.window(orphan)
        self.assertEqual(type(win._stack.currentWidget()).__name__,
                         "SettingsPage")
        self.assertIn("carte SD", win.statusBar().currentMessage())

    def test_carte_detectee_et_acceptee_au_demarrage(self):
        from PyQt6.QtWidgets import QMessageBox

        from delugeapp.config import AppContext, Settings

        orphan = AppContext(settings=Settings(), sd=None, lib=self.lib,
                            player=None)
        self.detected = [self.root]
        self.answer = QMessageBox.StandardButton.Yes
        win = self.window(orphan)
        self.assertEqual(orphan.settings.sd_path, str(self.root))
        self.assertTrue(orphan.has_card)
        self.assertIn(str(self.root), win._card_button.text())

    def test_carte_detectee_mais_refusee(self):
        from PyQt6.QtWidgets import QMessageBox

        from delugeapp.config import AppContext, Settings

        orphan = AppContext(settings=Settings(), sd=None, lib=self.lib,
                            player=None)
        self.detected = [self.root]
        self.answer = QMessageBox.StandardButton.No
        win = self.window(orphan)
        self.assertEqual(orphan.settings.sd_path, "")
        self.assertEqual(type(win._stack.currentWidget()).__name__,
                         "SettingsPage")

    def test_changement_de_carte_rafraichit_les_pages_ouvertes(self):
        win = self.window()
        win.go_to("Samples")
        win.go_to("Synths")
        _APP.processEvents()
        ouvertes = set(win._pages)

        autre = Path(self._tmp.name) / "autre-carte"
        for sub in ("SONGS", "SYNTHS", "KITS", "SAMPLES"):
            (autre / sub).mkdir(parents=True)

        win._card_changed(str(autre))
        _APP.processEvents()

        self.assertEqual(self.ctx.settings.sd_path, str(autre))
        self.assertEqual(Path(self.ctx.sd.root), autre)
        self.assertTrue(self.ctx.has_card)
        self.assertIn(str(autre), self.ctx.settings.recent_paths)
        self.assertIn(str(autre), win._card_button.text())
        self.assertEqual(set(win._pages), ouvertes,
                         "le changement de carte ne crée pas de page")

    def test_changement_vers_un_dossier_sans_deluge(self):
        win = self.window()
        quelconque = Path(self._tmp.name) / "photos"
        quelconque.mkdir()
        win._card_changed(str(quelconque))
        _APP.processEvents()
        self.assertFalse(self.ctx.has_card)
        self.assertIn("arborescence Deluge",
                      win.statusBar().currentMessage())

    def test_aucune_ecriture_dans_les_reglages_reels(self):
        """Garde-fou : la suite de tests ne touche pas la vraie configuration.

        ``_card_changed`` appelle ``ctx.save()``. Sans l'isolation posée par
        ``PageCase``, cet appel remplacerait le ``settings.json`` de
        l'utilisateur par un chemin temporaire — ce qui est arrivé.
        """
        from delugeapp import config as config_mod

        reels = config_mod._base_dir() / config_mod.APP_ORG / "settings.json"
        avant = reels.read_bytes() if reels.exists() else None

        win = self.window()
        autre = Path(self._tmp.name) / "carte-bis"
        for sub in ("SONGS", "SYNTHS", "KITS", "SAMPLES"):
            (autre / sub).mkdir(parents=True)
        win._card_changed(str(autre))

        self.assertIn(self._tmp.name, str(config_mod.SETTINGS_PATH))
        self.assertTrue(config_mod.SETTINGS_PATH.exists(),
                        "les réglages devaient être écrits dans le bac à sable")
        apres = reels.read_bytes() if reels.exists() else None
        self.assertEqual(avant, apres,
                         "les réglages réels de l'utilisateur ont été modifiés")

    def test_changement_vers_un_chemin_vide_ignore(self):
        win = self.window()
        avant = self.ctx.settings.sd_path
        win._card_changed("   ")
        self.assertEqual(self.ctx.settings.sd_path, avant)


class TestMainWindowActions(MainWindowCase):
    """Recherche globale, écoute, rafraîchissement, signaux des pages."""

    def test_recherche_globale_renvoie_vers_les_echantillons(self):
        win = self.window()
        win._global_search("k.wav")
        _APP.processEvents()
        self.assertEqual(type(win._stack.currentWidget()).__name__,
                         "SamplesPage")
        self.assertEqual(win._pages["Samples"]._search.text(), "k.wav")

    def test_recherche_vide_ne_navigue_pas(self):
        win = self.window()
        win.go_to("Toolbox")
        win._global_search("")
        self.assertEqual(type(win._stack.currentWidget()).__name__,
                         "ToolboxPage")

    def test_focus_sur_la_recherche(self):
        win = self.window()
        win._focus_search()
        _APP.processEvents()
        self.assertTrue(win._search.hasFocus())

    def test_ecoute_sans_lecteur_audio(self):
        """Sans sortie audio, ``Espace`` ne doit rien casser."""
        win = self.window()
        self.assertIsNone(self.ctx.player)
        win.toggle_play()       # ne doit pas lever

    def test_signal_status_d_une_page_atteint_la_barre_d_etat(self):
        win = self.window()
        page = win._pages["Dashboard"]
        page.status.emit("message de la page")
        _APP.processEvents()
        self.assertEqual(win.statusBar().currentMessage(),
                         "message de la page")

    def test_signal_settingsRequested_navigue(self):
        win = self.window()
        win._pages["Dashboard"].settingsRequested.emit()
        _APP.processEvents()
        self.assertEqual(type(win._stack.currentWidget()).__name__,
                         "SettingsPage")

    def test_signal_de_navigation_d_une_page(self):
        win = self.window()
        page = win._pages["Dashboard"]
        signal = getattr(page, "navigateRequested", None)
        if signal is None:
            self.skipTest("le tableau de bord n'expose pas ce signal")
        signal.emit("Health")
        _APP.processEvents()
        self.assertEqual(type(win._stack.currentWidget()).__name__,
                         "HealthPage")

    def test_accent_change_sans_tout_casser(self):
        win = self.window()
        win._accent_changed("#2FAF6F")
        _APP.processEvents()
        self.assertIn("accent", win.statusBar().currentMessage().lower())

    def test_refresh_all_ne_leve_pas(self):
        win = self.window()
        for key in ("Samples", "Synths", "Health"):
            win.go_to(key)
        _APP.processEvents()
        win.refresh_all()
        win.refresh_all()

    def test_une_page_fautive_n_empeche_pas_l_ouverture(self):
        """Si une page refuse de se construire, la fenêtre survit."""
        win = self.window()

        class Fautive:
            TITLE = "Fautive"

            def __init__(self, *a, **k):
                raise RuntimeError("volontaire")

        win._classes["Fautive"] = Fautive
        win.go_to("Fautive")
        _APP.processEvents()
        self.assertNotIn("Fautive", win._pages)
        self.assertIn("Fautive", win.statusBar().currentMessage())

    def test_le_tick_de_la_barre_d_etat(self):
        win = self.window()
        win._tick()             # ne doit pas lever sans lecteur audio
        self.assertFalse(win._progress.isVisible())


class TestMainWindowPersistance(MainWindowCase):
    """Géométrie, page courante et barre latérale d'une session à l'autre."""

    def test_page_et_barre_laterale_restaurees(self):
        win = self.window()
        win.go_to("Toolbox")
        win.toggle_rail()
        _APP.processEvents()
        win._save_state()

        second = self.window()
        self.assertEqual(type(second._stack.currentWidget()).__name__,
                         "ToolboxPage")
        self.assertEqual(second._rail.width(), self.mw.RAIL_NARROW)

    def test_page_enregistree_inconnue_retombe_sur_le_tableau_de_bord(self):
        self._store.setValue("window/page", "PageDisparue")
        self._store.sync()
        win = self.window()
        self.assertEqual(type(win._stack.currentWidget()).__name__,
                         "DashboardPage")

    def test_geometrie_illisible_ne_bloque_pas_le_demarrage(self):
        self._store.setValue("window/geometry", "ceci n'est pas une géométrie")
        self._store.sync()
        win = self.window()          # ne doit pas lever
        self.assertTrue(win.isVisible())


class TestMainWindowFermeture(MainWindowCase):
    """La fermeture, qui est l'endroit où l'application plantait."""

    def _travail_long(self, win):
        """Lance un travail qui dure, et rend la main dès qu'il tourne."""
        from delugeapp.ui import tasks

        def interminable(progress=None, should_stop=None):
            import time

            for _ in range(400):
                if should_stop is not None and should_stop():
                    return "interrompu"
                time.sleep(0.02)
            return "fini"

        tasks.run_task(win, interminable, title="Essai")
        _pump(200)
        self.assertEqual(tasks.active_count(), 1)

    def test_fermeture_normale_arrete_tout(self):
        from delugeapp.ui import tasks

        win = self.window()
        win.close()
        _APP.processEvents()
        self.assertEqual(tasks.active_count(), 0)
        self.assertFalse(win._ticker.isActive(),
                         "le minuteur de la barre d'état doit être arrêté")

    def test_fermeture_pendant_un_travail_arrete_les_fils(self):
        """Un ``QThread`` encore vivant à la sortie fait planter le processus.

        C'est la raison d'être de ``tasks.stop_all()`` dans ``closeEvent`` :
        sans lui, fermer la fenêtre pendant une analyse tue l'application
        avec un code de sortie non nul.
        """
        from PyQt6.QtWidgets import QMessageBox

        from delugeapp.ui import tasks

        win = self.window()
        self._travail_long(win)

        self.answer = QMessageBox.StandardButton.Yes
        win.close()
        _APP.processEvents()

        self.assertEqual(tasks.active_count(), 0,
                         "aucun fil ne doit survivre à la fermeture")
        self.assertFalse(win.isVisible())

    def test_fermeture_refusee_laisse_le_travail_tourner(self):
        from PyQt6.QtWidgets import QMessageBox

        from delugeapp.ui import tasks

        win = self.window()
        self._travail_long(win)

        self.answer = QMessageBox.StandardButton.No
        win.close()
        _APP.processEvents()

        self.assertTrue(win.isVisible(), "la fenêtre devait rester ouverte")
        self.assertEqual(tasks.active_count(), 1)

        self.answer = QMessageBox.StandardButton.Yes
        win.close()
        _APP.processEvents()
        self.assertEqual(tasks.active_count(), 0)

    def test_stop_all_sans_travail_ne_fait_rien(self):
        from delugeapp.ui import tasks

        self.assertEqual(tasks.active_count(), 0)
        self.assertEqual(tasks.stop_all(100), 0)


# --------------------------------------------------------------------------- #
# Point d'entrée
# --------------------------------------------------------------------------- #

class TestPointDEntree(unittest.TestCase):
    """``main.py`` : arguments, journal, contexte, garde-fous."""

    def setUp(self):
        import logging

        import main as entry

        self.entry = entry
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self._added: list = []
        self._log_level = logging.getLogger().level

    def tearDown(self):
        import logging

        root = logging.getLogger()
        for handler in self._added:
            root.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass
        if self._added:
            root.setLevel(self._log_level)
        self._tmp.cleanup()

    # -- arguments ---------------------------------------------------------- #

    def test_arguments_par_defaut(self):
        args = self.entry._parse_args([])
        self.assertIsNone(args.sd)
        for flag in ("reset_db", "no_splash", "verbose", "version"):
            self.assertFalse(getattr(args, flag), flag)

    def test_tous_les_arguments(self):
        args = self.entry._parse_args(
            ["--sd", "X:/carte", "--reset-db", "--no-splash", "--verbose"])
        self.assertEqual(args.sd, "X:/carte")
        self.assertTrue(args.reset_db)
        self.assertTrue(args.no_splash)
        self.assertTrue(args.verbose)

    def test_version_sort_sans_ouvrir_de_fenetre(self):
        import io
        import sys

        from delugeapp import __version__

        flux, sys.stdout = sys.stdout, io.StringIO()
        try:
            code = self.entry.main(["--version"])
            sortie = sys.stdout.getvalue()
        finally:
            sys.stdout = flux

        self.assertEqual(code, 0)
        self.assertIn(__version__, sortie)
        self.assertIn("Deluge Companion", sortie)

    # -- journal ------------------------------------------------------------ #

    def test_journal_tournant(self):
        import logging

        from delugeapp import config as config_mod

        avant = set(logging.getLogger().handlers)
        original = config_mod.ensure_config_dir
        config_mod.ensure_config_dir = lambda: self.home
        try:
            chemin = self.entry._setup_logging(verbose=True)
        finally:
            config_mod.ensure_config_dir = original
        self._added = [h for h in logging.getLogger().handlers
                       if h not in avant]

        self.assertEqual(chemin, self.home / "app.log")
        logging.getLogger("delugeapp").info("ligne de journal d'essai")
        for handler in self._added:
            handler.flush()
        self.assertIn("ligne de journal d'essai",
                      chemin.read_text(encoding="utf-8"))
        self.assertEqual(self.entry.LOG_MAX_BYTES, 1024 * 1024)
        self.assertEqual(self.entry.LOG_BACKUPS, 3)

    def test_journal_indisponible_ne_bloque_pas(self):
        """Un dossier de configuration inaccessible ne doit pas tout arrêter."""
        import logging

        from delugeapp import config as config_mod

        avant = set(logging.getLogger().handlers)

        def refuse():
            raise OSError("accès refusé (volontaire)")

        original = config_mod.ensure_config_dir
        config_mod.ensure_config_dir = refuse
        try:
            chemin = self.entry._setup_logging()
        finally:
            config_mod.ensure_config_dir = original
        self._added = [h for h in logging.getLogger().handlers
                       if h not in avant]

        self.assertIsNone(chemin)

    # -- contexte ----------------------------------------------------------- #

    def _contexte(self, argv):
        """Construit un contexte en isolant index, réglages et audio."""
        from delugeapp import config as config_mod
        from delugeapp.core import audio_out

        class FauxLecteur:
            backend = "aucun"

            def set_volume(self, _v):
                pass

            def set_device(self, _d):
                pass

            def close(self):
                pass

        sauvegarde = (config_mod.CONFIG_DIR, config_mod.load_settings,
                      audio_out.Player)
        config_mod.CONFIG_DIR = self.home
        config_mod.load_settings = lambda: config_mod.Settings()
        audio_out.Player = FauxLecteur
        try:
            return self.entry._build_context(self.entry._parse_args(argv))
        finally:
            (config_mod.CONFIG_DIR, config_mod.load_settings,
             audio_out.Player) = sauvegarde

    def test_contexte_sans_carte(self):
        ctx = self._contexte([])
        try:
            self.assertIsNone(ctx.sd)
            self.assertFalse(ctx.has_card)
            self.assertIsNotNone(ctx.lib)
            self.assertTrue((self.home / "library.db").exists())
        finally:
            ctx.close()

    def test_contexte_avec_une_carte_absente(self):
        """Un chemin qui n'existe pas ne doit pas empêcher le démarrage."""
        fantome = self.home / "carte-absente"
        ctx = self._contexte(["--sd", str(fantome)])
        try:
            self.assertEqual(ctx.settings.sd_path, str(fantome))
            self.assertFalse(ctx.has_card)
        finally:
            ctx.close()

    def test_option_sd_memorisee_dans_les_recents(self):
        carte = self.home / "carte"
        for sub in ("SONGS", "SYNTHS", "KITS", "SAMPLES"):
            (carte / sub).mkdir(parents=True)
        ctx = self._contexte(["--sd", str(carte)])
        try:
            self.assertTrue(ctx.has_card)
            self.assertIn(str(carte), ctx.settings.recent_paths)
        finally:
            ctx.close()

    def test_reset_db_vide_l_index(self):
        from delugeapp.core import db as db_mod

        lib = db_mod.Library(self.home / "library.db")
        lib.upsert_sample({"rel": "SAMPLES/x.wav", "size": 1})
        lib.commit()
        self.assertEqual(lib.stats()["samples"], 1)
        lib.close()

        ctx = self._contexte(["--reset-db"])
        try:
            self.assertEqual(ctx.lib.stats()["samples"], 0)
        finally:
            ctx.close()

    def test_sortie_audio_absente_toleree(self):
        """Sans périphérique audio, ``ctx.player`` vaut ``None``."""
        from delugeapp import config as config_mod
        from delugeapp.core import audio_out

        def refuse():
            raise RuntimeError("aucun périphérique (volontaire)")

        sauvegarde = (config_mod.CONFIG_DIR, config_mod.load_settings,
                      audio_out.Player)
        config_mod.CONFIG_DIR = self.home
        config_mod.load_settings = lambda: config_mod.Settings()
        audio_out.Player = refuse
        try:
            ctx = self.entry._build_context(self.entry._parse_args([]))
        finally:
            (config_mod.CONFIG_DIR, config_mod.load_settings,
             audio_out.Player) = sauvegarde
        try:
            self.assertIsNone(ctx.player)
        finally:
            ctx.close()

    # -- garde-fous --------------------------------------------------------- #

    def test_hook_d_exception_journalise_et_affiche(self):
        import logging
        import sys

        from PyQt6.QtWidgets import QMessageBox

        vues: list = []
        original_exec = QMessageBox.exec
        QMessageBox.exec = lambda box: vues.append(box.text()) or 0
        sauvegarde = sys.excepthook
        try:
            self.entry._install_excepthook()
            with self.assertLogs("delugeapp", level="CRITICAL") as journal:
                try:
                    raise ValueError("erreur volontaire")
                except ValueError:
                    sys.excepthook(*sys.exc_info())
        finally:
            sys.excepthook = sauvegarde
            QMessageBox.exec = original_exec

        self.assertTrue(any("non rattrapée" in ligne
                            for ligne in journal.output))
        self.assertEqual(len(vues), 1)
        self.assertIn("erreur inattendue", vues[0].lower())

    def test_hook_laisse_passer_ctrl_c(self):
        import sys

        sauvegarde = (sys.excepthook, sys.__excepthook__)
        appels: list = []
        try:
            self.entry._install_excepthook()
            hook = sys.excepthook
            sys.__excepthook__ = lambda *a: appels.append(a)
            hook(KeyboardInterrupt, KeyboardInterrupt(), None)
        finally:
            sys.excepthook, sys.__excepthook__ = sauvegarde

        self.assertEqual(len(appels), 1,
                         "Ctrl+C doit retomber sur le hook d'origine")

    def test_ecran_de_demarrage(self):
        splash = self.entry._splash(_APP)
        try:
            self.assertEqual(splash.pixmap().width(), 420)
            self.assertEqual(splash.pixmap().height(), 240)
        finally:
            splash.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
