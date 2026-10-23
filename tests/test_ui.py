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

import faulthandler
import hashlib
import os
import re
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# --------------------------------------------------------------------------- #
# Bac à sable — avant tout import de ``delugeapp``
# --------------------------------------------------------------------------- #
# Rien ici ne doit toucher aux réglages réels de l'utilisateur. Ce n'est pas
# une précaution théorique : c'est arrivé trois fois, et la dernière a éteint
# ``confirm_writes`` et ``always_backup_before_write`` — les deux filets qui
# protègent une carte contenant des mois de travail.
#
# Ces quatre lignes doivent rester **au-dessus** de l'import de ``delugeapp``,
# qui calcule ses chemins au moment de l'import. Elles sont répétées dans
# chaque module de test, et non dans ``tests/__init__.py`` : ``unittest
# discover`` charge les modules à plat, sans importer le paquet.
#
# ``TestDossierDeConfiguration.test_la_suite_n_ecrit_pas_chez_l_utilisateur``
# échoue si on les retire.
import os as _os                                             # noqa: E402
import tempfile as _tempfile                                 # noqa: E402

BAC_A_SABLE = Path(_tempfile.gettempdir()) / "deluge-companion-tests"
BAC_A_SABLE.mkdir(parents=True, exist_ok=True)
_os.environ["DELUGE_COMPANION_CONFIG"] = str(BAC_A_SABLE)


import numpy as np

try:
    from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
    from PyQt6.QtGui import QMouseEvent, QWheelEvent
    from PyQt6.QtWidgets import QApplication, QLabel, QTableView, QWidget

    HAVE_QT = True
except ImportError:  # pragma: no cover - dépend de l'installation
    HAVE_QT = False

if not HAVE_QT:  # pragma: no cover
    raise unittest.SkipTest("PyQt6 absent : tests d'interface sautés")

from delugeapp.core import (db, genres, rhythm, scan, sdcard, synthgen,
                            theory, wav)
from delugeapp.core import dxml
from delugeapp.core.model import Kit, Song, SynthPreset
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

# --------------------------------------------------------------------------- #
# Aucune fenêtre modale réelle
# --------------------------------------------------------------------------- #
# Hors écran, une fenêtre modale attend un clic qui ne viendra jamais : la
# suite se fige sans un mot. C'est arrivé deux fois le 13 octobre 2026, et
# cinq passages d'affilée n'ont pas su le reproduire — une course de minutage,
# donc. Les classes de test remplacent les dialogues dont elles ont besoin,
# puis rétablissent ce qu'elles avaient trouvé : ce sont désormais ces
# remparts qu'elles rétablissent, plus les vrais dialogues. Une fenêtre qui
# passe quand même (le résultat tardif d'un fil, la minuterie d'une fenêtre
# d'un test précédent) reçoit un refus, et le test en cours échoue en la
# nommant au lieu de figer la suite.

#: Fenêtres modales demandées sans avoir été neutralisées par le test.
_MODALES_REFUSEES: list[str] = []

#: Au-delà, un test est tenu pour figé : la pile de chaque fil est écrite et
#: le processus s'arrête. Le plus long test d'interface dure une dizaine de
#: secondes.
_DELAI_MAX_TEST = 120

#: ``(propriétaire, nom, original)`` de chaque remplacement, pour les rendre.
_ORIGINAUX: list[tuple[object, str, object]] = []


class _Refus:
    """Remplace une fonction statique de dialogue : note l'appel, refuse.

    Un objet appelable plutôt qu'une fonction : il ne se lie pas à une
    instance, et les tests qui le sauvegardent puis le rétablissent par
    simple affectation le retrouvent intact.
    """

    def __init__(self, nom: str, reponse) -> None:
        self.nom = nom
        self.reponse = reponse

    def __call__(self, *args, **kwargs):
        textes = [a for a in args if isinstance(a, str)]
        _MODALES_REFUSEES.append(
            "%s(%s)" % (self.nom, " — ".join(t[:60] for t in textes[:2])))
        return self.reponse


def _exec_refuse(dialogue, *args):
    """Remplace ``QDialog.exec`` : seule la classe de base la définit."""
    from PyQt6.QtWidgets import QDialog

    _MODALES_REFUSEES.append(
        "%s.exec(%s)" % (type(dialogue).__name__, dialogue.windowTitle()))
    return QDialog.DialogCode.Rejected


def _armer_chien_de_garde() -> bool:
    """Arme le minuteur de :data:`_DELAI_MAX_TEST` secondes.

    Rend ``False`` quand ``sys.stderr`` n'a pas de descripteur de fichier
    (certains lanceurs d'IDE) : on se passe alors de chien de garde.
    """
    try:
        faulthandler.dump_traceback_later(_DELAI_MAX_TEST, exit=True)
    except (RuntimeError, ValueError, OSError):
        return False
    return True


def _remplacer(proprietaire, nom: str, valeur) -> None:
    _ORIGINAUX.append((proprietaire, nom, vars(proprietaire)[nom]))
    setattr(proprietaire, nom, valeur)


def _poser_les_remparts() -> None:
    """Refuse les dialogues bloquants et masque les ports MIDI.

    Chaque dialogue répond « non » ou « annuler ». Aucun port MIDI n'est
    visible : Deluge branché pendant la suite, le test qui clique tout lui
    enverrait la note d'essai de la page Réglages, et les fenêtres
    principales, connectées d'elles-mêmes, prendraient ses ports.

    Une seconde pose ne fait rien : elle prendrait les remparts pour les
    originaux, et ``tearDownModule`` ne saurait plus les rendre.
    """
    from PyQt6.QtWidgets import QDialog, QFileDialog, QInputDialog, QMessageBox

    from delugeapp.core import midiport

    if _ORIGINAUX:
        return
    non = QMessageBox.StandardButton.No
    remparts = [
        (QMessageBox, "question", non), (QMessageBox, "information", non),
        (QMessageBox, "warning", non), (QMessageBox, "critical", non),
        (QMessageBox, "about", None),
        (QFileDialog, "getSaveFileName", ("", "")),
        (QFileDialog, "getOpenFileName", ("", "")),
        (QFileDialog, "getOpenFileNames", ([], "")),
        (QFileDialog, "getExistingDirectory", ""),
        (QInputDialog, "getText", ("", False)),
        (QInputDialog, "getMultiLineText", ("", False)),
        (QInputDialog, "getInt", (0, False)),
        (QInputDialog, "getDouble", (0.0, False)),
        (QInputDialog, "getItem", ("", False)),
    ]
    for classe, nom, reponse in remparts:
        _remplacer(classe, nom, _Refus("%s.%s" % (classe.__name__, nom), reponse))
    _remplacer(QDialog, "exec", _exec_refuse)
    _remplacer(midiport, "outputs", lambda: [])
    _remplacer(midiport, "inputs", lambda: [])


def setUpModule() -> None:  # noqa: N802 - API unittest
    global _APP
    _APP = QApplication.instance() or QApplication([])
    theme.apply_theme(_APP)
    _poser_les_remparts()


def tearDownModule() -> None:  # noqa: N802 - API unittest
    while _ORIGINAUX:
        proprietaire, nom, original = _ORIGINAUX.pop()
        setattr(proprietaire, nom, original)


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
        # Les nettoyages passent après tous les ``tearDown``, file d'événements
        # vidée ; ils s'exécutent dans l'ordre inverse de leur inscription.
        if _armer_chien_de_garde():
            self.addCleanup(faulthandler.cancel_dump_traceback_later)
        self.addCleanup(self._aucune_modale)
        self.addCleanup(self._aucun_rempart_epingle)

    def tearDown(self):
        for widget in self._widgets:
            widget.deleteLater()
        if _APP is not None:
            _APP.processEvents()

    def _aucune_modale(self) -> None:
        """Échoue si une fenêtre modale a été demandée sans être neutralisée."""
        refusees = list(_MODALES_REFUSEES)
        _MODALES_REFUSEES.clear()
        if refusees:
            self.fail("fenêtre modale non neutralisée, pendant ce test ou "
                      "juste avant (elle aurait figé la suite) : "
                      + " ; ".join(refusees))

    def _aucun_rempart_epingle(self) -> None:
        """Échoue si le test a laissé le rempart de ``QDialog.exec`` collé
        sur une sous-classe.

        Sauvegarder ``PlanDialog.exec`` lit la méthode **héritée** — le
        rempart —, et la réaffecter ensuite l'épingle sur ``PlanDialog`` :
        les tests suivants qui neutralisent ``QDialog.exec`` ne touchent
        plus ce dialogue, et le refus les fait échouer. Vu le 15 octobre
        2026 sous pytest, qui suit l'ordre du fichier ; ``unittest``, qui
        trie les classes, passait ``TestClicsReels`` avant les fautifs.
        """
        from PyQt6.QtWidgets import QDialog

        vues, a_voir, epingles = set(), list(QDialog.__subclasses__()), []
        while a_voir:
            classe = a_voir.pop()
            if classe in vues:
                continue
            vues.add(classe)
            a_voir.extend(classe.__subclasses__())
            if vars(classe).get("exec") is _exec_refuse:
                epingles.append(classe.__name__)
                # Décollé tout de suite : un seul test échoue, pas la suite.
                delattr(classe, "exec")
        if epingles:
            self.fail("rempart de QDialog.exec épinglé sur %s : utiliser "
                      "mock.patch.object, qui rend l'héritage"
                      % ", ".join(sorted(epingles)))

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


class TestRempartsDeLaSuite(WidgetCase):
    """Ni fenêtre modale réelle ni port MIDI réel pendant les tests d'interface.

    Une modale oubliée fait échouer le test au lieu de figer la suite ; un
    Deluge branché pendant la suite ne reçoit rien.
    """

    def test_une_modale_oubliee_repond_non_sans_attendre(self):
        import time

        from PyQt6.QtWidgets import QDialog, QFileDialog, QMessageBox

        dialogue = QDialog()
        self._widgets.append(dialogue)
        debut = time.monotonic()
        reponse = QMessageBox.question(None, "Écraser ?", "Le fichier existe.")
        code = dialogue.exec()
        chemin = QFileDialog.getSaveFileName(None, "Exporter")
        vues = list(_MODALES_REFUSEES)
        _MODALES_REFUSEES.clear()

        self.assertLess(time.monotonic() - debut, 1.0)
        self.assertEqual(reponse, QMessageBox.StandardButton.No)
        self.assertEqual(code, QDialog.DialogCode.Rejected)
        self.assertEqual(chemin, ("", ""))
        self.assertEqual(len(vues), 3, vues)
        self.assertIn("Écraser ?", vues[0])

    def test_le_test_qui_l_oublie_echoue_en_la_nommant(self):
        class Oublieux(WidgetCase):
            def test_oubli(self):
                from PyQt6.QtWidgets import QMessageBox

                QMessageBox.information(None, "Kit écrit", "12 rangées")

        resultat = unittest.TestResult()
        # Le cas seul, pas une suite : une suite rejouerait ``setUpModule`` et
        # ``tearDownModule``, qui rétablirait les vrais dialogues en plein
        # milieu de la suite — le test suivant s'est figé ainsi.
        Oublieux("test_oubli").run(resultat)
        _armer_chien_de_garde()     # le test imbriqué a désarmé le minuteur

        self.assertEqual(len(resultat.failures), 1, resultat.errors)
        self.assertIn("QMessageBox.information(Kit écrit",
                      resultat.failures[0][1])

    def test_aucun_port_midi_n_est_visible(self):
        from delugeapp.core import midiport
        from delugeapp.core.delugelink import DelugeLink

        self.assertEqual(midiport.outputs(), [])
        self.assertEqual(midiport.inputs(), [])
        self.assertIsNone(midiport.find("out"))
        self.assertFalse(DelugeLink().connect())


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

        # D'abord marquer le contexte fermé : un fil qui finit pendant
        # ``stop_all`` rend son résultat par un signal mis en file, délivré
        # plus bas par ``processEvents`` — après que les sous-classes ont
        # rétabli leurs dialogues. ``Page.guard`` l'ignore alors, comme il le
        # fait dans l'application après ``AppContext.close()``.
        self.ctx.closed = True
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
    """Le contrat de la SPEC §5.5, vérifié sur les dix pages."""

    def _pages(self):
        from delugeapp.ui.pages.atelier import AtelierPage
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
                GeneratorPage, AtelierPage, ToolboxPage, HealthPage,
                SettingsPage)

    def test_les_dix_pages_existent(self):
        self.assertEqual(len(self._pages()), 10)

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

    def test_la_liste_des_chemins_recents_ne_se_dit_pas_vide(self):
        """Vu le 22 octobre 2026 : deux chemins récents, et la liste
        affichait « Aucun chemin récent » — le texte d'attente, montré tant
        qu'aucune ligne n'est choisie."""
        self.ctx.settings.recent_paths = []
        page = self._page()
        self.assertEqual(page._recent_box.placeholderText(),
                         "Aucun chemin récent")
        autre = Path(self._tmp.name) / "autre"
        self.ctx.settings.recent_paths = [str(self.root), str(autre)]
        page._fill_recent()
        self.assertEqual(page._recent_box.count(), 2)
        self.assertEqual(page._recent_box.currentIndex(), -1)
        self.assertEqual(page._recent_box.placeholderText(),
                         "2 chemin(s) déjà utilisé(s) — choisir…")


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

    def _rapport(self, *codes):
        """Un rapport de santé factice portant les anomalies demandées."""
        from delugeapp.core import health

        issues = [health.Issue(code=code, severity="warn", title=code,
                               detail="", items=["x"] * nombre)
                  for code, nombre in codes]
        return health.HealthReport(score=80, issues=issues)

    def test_la_suggestion_suit_l_urgence_reelle(self):
        """Une seule suggestion, et la plus urgente.

        On ne propose pas de fabriquer des presets à quelqu'un dont la carte
        n'a jamais été sauvegardée : l'ordre est celui du risque, pas celui
        des fonctions.
        """
        from delugeapp.ui.pages.dashboard import DashboardPage

        page = self.open(DashboardPage)
        plein = {"samples": 1741, "synths": 911, "kits": 43, "songs": 46}

        # 1. Carte jamais lue : rien d'autre ne compte.
        vide = page._next_suggestion({}, self._rapport(("NO_BACKUP", 1)))
        self.assertIsNotNone(vide)
        self.assertEqual(vide[2], "@scan")

        # 2. Pas de sauvegarde : avant toute correction.
        cas = page._next_suggestion(
            plein, self._rapport(("NO_BACKUP", 1), ("MISSING_SAMPLE", 125)))
        self.assertEqual(cas[2], "Health#Sauvegardes")

        # 3. Sauvegarde faite : les sons manquants passent devant.
        cas = page._next_suggestion(
            plein, self._rapport(("MISSING_SAMPLE", 125),
                                 ("DUPLICATE_SAMPLE", 4)))
        self.assertEqual(cas[2], "Health#Manquants")
        self.assertIn("125", cas[0])

        # 4. Puis les doublons.
        cas = page._next_suggestion(plein,
                                    self._rapport(("DUPLICATE_SAMPLE", 4)))
        self.assertEqual(cas[2], "Health#Doublons")

        # 5. Quelques orphelins ne méritent pas qu'on dérange l'utilisateur.
        cas = page._next_suggestion(plein,
                                    self._rapport(("ORPHAN_SAMPLE", 12)))
        self.assertTrue(cas[2].startswith("Generator"))

        # 6. Tout va bien : on propose de créer.
        cas = page._next_suggestion(plein, self._rapport())
        self.assertTrue(cas[2].startswith("Generator"), cas[2])

    def test_sans_carte_aucune_suggestion(self):
        from delugeapp.ui.pages.dashboard import DashboardPage

        page = self.open(DashboardPage)
        vraie = page.ctx.sd
        page.ctx.sd = None
        try:
            self.assertIsNone(page._next_suggestion({}, None))
        finally:
            page.ctx.sd = vraie

    def test_le_bandeau_mene_ou_il_annonce(self):
        from delugeapp.ui.pages.dashboard import DashboardPage

        page = self.open(DashboardPage)
        recus = []
        page.navigateRequested.connect(recus.append)
        page._next_target = "Health#Doublons"
        page._next_button.click()
        _APP.processEvents()
        self.assertEqual(recus, ["Health#Doublons"])

    def test_une_anomalie_mene_a_l_endroit_ou_on_la_repare(self):
        """Annoncer un problème sans dire où le résoudre, c'est une étape
        de plus à deviner."""
        from delugeapp.ui.pages.dashboard import (ISSUE_DESTINATION,
                                                  DashboardPage,
                                                  _LigneAnomalie)

        page = self.open(DashboardPage)
        recus = []
        page.navigateRequested.connect(recus.append)

        lignes = page.findChildren(_LigneAnomalie)
        if not lignes:
            self.skipTest("aucune anomalie à afficher sur cet index")
        for ligne in lignes:
            self.assertTrue(ligne.cible, "une ligne sans destination")
            self.assertTrue(ligne.toolTip(), "une ligne sans explication")
        lignes[0].clicked.emit()
        _APP.processEvents()
        self.assertEqual(recus, [lignes[0].cible])

    def test_les_destinations_visent_des_onglets_qui_existent(self):
        """Une adresse « Page#Partie » qui ne tombe nulle part est muette :
        on arriverait sur la page, sur le mauvais onglet, sans rien dire."""
        from delugeapp.ui.pages.dashboard import ISSUE_DESTINATION
        from delugeapp.ui.pages.health import HealthPage
        from PyQt6.QtWidgets import QTabWidget

        page = self.open(HealthPage)
        onglets = page.findChildren(QTabWidget)
        self.assertTrue(onglets, "la page Santé n'a plus d'onglets")
        libelles = {onglets[0].tabText(i).casefold()
                    for i in range(onglets[0].count())}
        from delugeapp.core import health

        for code, adresse in ISSUE_DESTINATION.items():
            nom, _, partie = adresse.partition("#")
            self.assertEqual(nom, "Health", code)
            self.assertIn(partie.casefold(), libelles, code)
            # Et le code visé doit exister : une destination pour une
            # anomalie que le noyau n'émet plus ne sert personne.
            self.assertIn(code, health.ISSUE_CODES, code)


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

    def test_dupliquer_montre_la_copie_dans_la_liste(self):
        """« Copie créée », mais la liste ne la montrait qu'après une
        analyse complète : la copie n'entrait pas dans l'index."""
        from unittest import mock

        from PyQt6.QtWidgets import QAbstractButton, QMessageBox

        from delugeapp.ui.pages.synths import SynthsPage

        page = self.open(SynthsPage)
        avant = page._model.rowCount()
        page._table.selectRow(0)
        bouton = next(b for b in page.findChildren(QAbstractButton)
                      if _libelle(b) == "Dupliquer")
        with mock.patch.object(QMessageBox, "question",
                               return_value=QMessageBox.StandardButton.Yes):
            bouton.click()
        _APP.processEvents()
        self.assertEqual(page._model.rowCount(), avant + 1)
        copies = [r["rel"] for r in self.lib.search_presets(kind="synth")
                  if "copie" in r["rel"]]
        self.assertEqual(len(copies), 1)

    def test_ecouter_sur_le_deluge_joue_la_phrase_de_l_apercu(self):
        """Réglage « Écouter sur le Deluge » coché, machine branchée : le
        clic sur « Écouter » fait jouer à la machine la phrase de l'aperçu
        de l'ordinateur — une note après l'autre —, réglages du son compris,
        et l'ordinateur ne rend rien."""
        from PyQt6.QtWidgets import QAbstractButton

        from delugeapp.core.render import preview_notes
        from delugeapp.ui.pages import base
        from delugeapp.ui.pages.synths import SynthsPage

        class Lien:
            is_connected = True
            channel = 1

            def __init__(self):
                self.joues = []

            def play_notes(self, notes, seconds=0.6, gap=0.0, sound=None,
                           **_k):
                self.joues.append((notes, seconds, gap, sound))
                return True

        lien = Lien()
        self.ctx.link = lien
        self.addCleanup(setattr, self.ctx, "link", None)
        self.ctx.settings.midi_audition = True
        page = self.open(SynthsPage)
        rendus = []
        page.run = lambda *a, **k: rendus.append(a)
        page._table.selectRow(0)
        _APP.processEvents()
        bouton = next(b for b in page.findChildren(QAbstractButton)
                      if _libelle(b) == "Écouter")
        bouton.click()
        _APP.processEvents()
        self.assertEqual(len(lien.joues), 1)
        notes, secondes, ecart, son = lien.joues[0]
        phrase = preview_notes(page._preset.sound)
        self.assertGreater(len(phrase), 1)
        self.assertEqual(notes, [[n] for n in phrase])
        self.assertEqual((secondes, ecart),
                         (base.PHRASE_NOTE, base.PHRASE_GAP))
        self.assertIs(son, page._preset.sound)
        self.assertEqual(rendus, [], "l'ordinateur ne doit rien rendre")

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

    def test_un_preset_range_ailleurs_n_est_pas_absent(self):
        """La page disait « ABSENT » pour 40 instruments sur 65 que
        « Rassembler » trouvait et copiait."""
        from delugeapp.core import songpack
        from delugeapp.ui.pages.songs import SongsPage

        (self.root / "SYNTHS" / "RANGE").mkdir()
        (self.root / "SYNTHS" / "BASSE.XML").rename(
            self.root / "SYNTHS" / "RANGE" / "BASSE.XML")
        self.sd.invalidate_cache()
        page = self.open(SongsPage)
        page._table.selectRow(0)
        self.assertEqual(page._instruments.item(0, 3).text(), "oui")
        self.assertEqual(page._instruments.item(0, 3).toolTip(),
                         "SYNTHS/RANGE/BASSE.XML")
        pack = songpack.collect(self.sd, "SONGS/M.XML")
        self.assertIn("SYNTHS/RANGE/BASSE.XML", pack.presets)

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
        # La virgule du français, comme partout ailleurs dans l'interface.
        self.assertEqual(quarter, "500,00")
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
        self.assertEqual(len(win._classes), 10)
        self.assertEqual(len(win._buttons), 10)
        # Qt ajoute un menu interne sans titre (le débordement) : on ne
        # garde que les menus nommés.
        titres = [m.title() for m in win.menuBar().findChildren(QMenu)
                  if m.title()]
        self.assertEqual(titres,
                         ["&Fichier", "&Édition", "&Outils", "&Langue",
                          "&Aide"])

    def test_les_pages_sont_creees_au_premier_affichage(self):
        """Dix pages construites au démarrage, ce serait dix fois trop."""
        win = self.window()
        self.assertEqual(len(win._pages), 1,
                         "une seule page doit exister au démarrage")
        for key in win._classes:
            win.go_to(key)
            _APP.processEvents()
        self.assertEqual(len(win._pages), 10)

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
        """``Ctrl+1`` à ``Ctrl+9``, ``Ctrl+0`` pour la dixième page, plus
        ``Espace`` pour l'écoute."""
        win = self.window()
        sequences = {a.shortcut().toString() for a in win.actions()}
        for index in range(10):
            self.assertIn(f"Ctrl+{index}", sequences)
        self.assertIn("Space", sequences)
        # La septième, l'Atelier, et la dixième, les Réglages.
        for touche, page in (("Ctrl+7", "Atelier"), ("Ctrl+0", "Settings")):
            action = next(a for a in win.actions()
                          if a.shortcut().toString() == touche)
            action.trigger()
            _APP.processEvents()
            self.assertEqual(win._current_key(), page, touche)

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
        self.assertEqual(len(win._buttons), 10, "les boutons restent")
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
        """Le champ devient celui de la fenêtre qui recevra le clavier.

        ``hasFocus()`` exigeait en plus que la fenêtre soit active — ce que
        l'application ne décide pas quand d'autres fenêtres vivent encore :
        le test échouait de loin en loin dans la suite complète.
        """
        win = self.window()
        win._focus_search()
        _APP.processEvents()
        self.assertIs(win.focusWidget(), win._search)

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

        sauvegarde = (config_mod.CONFIG_DIR, config_mod.DB_PATH,
                      config_mod.load_settings, audio_out.Player)
        config_mod.CONFIG_DIR = self.home
        config_mod.DB_PATH = self.home / "library.db"
        config_mod.load_settings = lambda: config_mod.Settings()
        audio_out.Player = FauxLecteur
        try:
            return self.entry._build_context(self.entry._parse_args(argv))
        finally:
            (config_mod.CONFIG_DIR, config_mod.DB_PATH,
             config_mod.load_settings, audio_out.Player) = sauvegarde

    def test_un_second_lancement_montre_la_fenetre_ouverte(self):
        """Deux fenêtres se disputeraient le Deluge branché (vu le
        22 octobre 2026 : deux programmes sur ses ports, chaque réponse
        reçue deux fois). Le second lancement appelle le premier, qui se
        montre, et s'efface."""
        import time
        import uuid

        nom = "DelugeCompanion-test-%s" % uuid.uuid4().hex[:8]

        class Fenetre:
            def __init__(self):
                self.gestes = []

            def showNormal(self):
                self.gestes.append("normal")

            def raise_(self):
                self.gestes.append("devant")

            def activateWindow(self):
                self.gestes.append("active")

        self.assertFalse(self.entry._already_running(nom))
        premiere = self.entry._Instance(nom)
        self.addCleanup(premiere.server.close)
        self.assertTrue(premiere.listening)
        premiere.window = Fenetre()
        self.assertTrue(self.entry._already_running(nom))
        fin = time.monotonic() + 2.0
        while not premiere.window.gestes and time.monotonic() < fin:
            _APP.processEvents()
            time.sleep(0.01)
        self.assertEqual(premiere.window.gestes,
                         ["normal", "devant", "active"])
        premiere.server.close()
        self.assertFalse(self.entry._already_running(nom))

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

        from unittest import mock

        vues: list = []
        # ``exec`` est hérité de ``QDialog`` : ``mock.patch`` rend l'héritage
        # en partant (cf. ``WidgetCase._aucun_rempart_epingle``).
        remplacement = mock.patch.object(
            QMessageBox, "exec", lambda box: vues.append(box.text()) or 0)
        remplacement.start()
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
            remplacement.stop()

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

    def test_les_boutons_standard_parlent_francais(self):
        """« Yes » et « No » au milieu d'une application en français."""
        from PyQt6.QtWidgets import QMessageBox

        traducteur = self.entry._translate_qt(_APP)
        if traducteur is None:
            self.skipTest("traduction de Qt absente de cette installation")
        try:
            boite = QMessageBox()
            boite.setStandardButtons(QMessageBox.StandardButton.Yes
                                     | QMessageBox.StandardButton.No)
            texte = boite.button(QMessageBox.StandardButton.Yes).text()
            self.assertIn("Oui", texte.replace("&", ""))
            boite.deleteLater()
        finally:
            _APP.removeTranslator(traducteur)

    def test_ecran_de_demarrage(self):
        """La couverture du guide en petit, tracée à la densité de l'écran :
        sa taille **logique** est fixe, quel que soit l'agrandissement."""
        splash = self.entry._splash(_APP)
        try:
            image = splash.pixmap()
            ratio = image.devicePixelRatio()
            self.assertEqual(round(image.width() / ratio),
                             self.entry.SPLASH_SIZE[0])
            self.assertEqual(round(image.height() / ratio),
                             self.entry.SPLASH_SIZE[1])
        finally:
            splash.close()


# --------------------------------------------------------------------------- #
# Correction des défauts audio, côté interface
# --------------------------------------------------------------------------- #

class SampleFixUICase(PageCase):
    """Base des tests de correction audio : une carte avec de vrais défauts.

    Les boîtes modales sont neutralisées, ``PlanDialog`` compris : sans cela
    la suite se bloquerait sur la confirmation, qui est précisément ce que le
    code impose avant toute écriture.
    """

    def setUp(self):
        super().setUp()
        from PyQt6.QtWidgets import QDialog, QMessageBox

        from delugeapp.core import scan as scan_mod
        from delugeapp.ui.widgets.common import PlanDialog

        # Une percussion stéréo et un fichier à 32 kHz : deux des quatre
        # défauts que samplefix sait corriger.
        t = np.linspace(0, 0.3, 13230, endpoint=False, dtype=np.float32)
        stereo = np.stack([0.6 * np.sin(2 * np.pi * 70 * t),
                           0.6 * np.sin(2 * np.pi * 71 * t)], axis=1)
        wav.write(self.root / "SAMPLES/DRUMS/Kick/stereo.wav",
                  stereo.astype(np.float32), 44100)
        wav.write(self.root / "SAMPLES/DRUMS/Snare/32k.wav",
                  (0.4 * np.random.default_rng(5).standard_normal(9600)
                   ).astype(np.float32), 32000)
        scan_mod.scan_card(self.sd, self.lib, compute_hash=True, analyze=True)

        from unittest import mock

        self.reponse = QDialog.DialogCode.Accepted
        # ``exec`` est hérité de ``QDialog`` : le sauvegarder puis le
        # réaffecter épinglait sur ``PlanDialog`` le rempart de la suite (cf.
        # ``WidgetCase._aucun_rempart_epingle``). ``mock.patch`` rend
        # l'héritage.
        self._plan_exec = mock.patch.object(PlanDialog, "exec",
                                            lambda _self: self.reponse)
        self._plan_exec.start()

        self._orig_boxes = (QMessageBox.question, QMessageBox.information,
                            QMessageBox.warning)
        QMessageBox.question = staticmethod(
            lambda *a, **k: QMessageBox.StandardButton.Yes)
        QMessageBox.information = staticmethod(lambda *a, **k: None)
        QMessageBox.warning = staticmethod(lambda *a, **k: None)

    def tearDown(self):
        from PyQt6.QtWidgets import QMessageBox

        self._plan_exec.stop()
        (QMessageBox.question, QMessageBox.information,
         QMessageBox.warning) = self._orig_boxes
        super().tearDown()

    def attendre(self, ms: int = 6000) -> None:
        """Laisse tourner la boucle Qt le temps qu'un travail se termine."""
        from PyQt6.QtCore import QEventLoop, QTimer

        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()


class TestHealthPageAudioFix(SampleFixUICase):
    """La page Santé sait maintenant corriger, pas seulement signaler."""

    def _page(self):
        from delugeapp.core import health as health_mod
        from delugeapp.ui.pages.health import HealthPage

        page = self.open(HealthPage)
        report = health_mod.check_card(self.sd, self.lib)
        page._report = report
        page._fill_report(report)
        _APP.processEvents()
        return page, report

    def test_les_defauts_audio_recoivent_une_case(self):
        """Une case n'apparaît que si ``setCheckState`` a été appelé.

        Attention : en Qt 6.11, ``ItemIsUserCheckable`` fait partie des
        drapeaux par défaut d'un ``QListWidgetItem``. Tester ce drapeau
        renverrait vrai pour tous les éléments ; c'est la présence de
        ``CheckStateRole`` qui distingue.
        """
        from delugeapp.core import samplefix

        page, report = self._page()
        avec_case = set()
        for index in range(page._issues.count()):
            item = page._issues.item(index)
            if item.data(Qt.ItemDataRole.CheckStateRole) is not None:
                avec_case.add(item.data(Qt.ItemDataRole.UserRole))

        attendus = {i.code for i in report.issues
                    if i.auto_fixable or i.code in samplefix.HEALTH_CODES}
        self.assertEqual(avec_case, attendus)
        audio = {i.code for i in report.issues
                 if i.code in samplefix.HEALTH_CODES}
        self.assertTrue(audio, "la carte d'essai devait porter des défauts")
        self.assertTrue(audio <= avec_case)

    def test_le_bouton_corriger_s_active_pour_l_audio_seul(self):
        """Même sans anomalie réparable par ``organize``, le bouton sert."""
        from delugeapp.core import health as health_mod
        from delugeapp.core import samplefix
        from delugeapp.ui.pages.health import HealthPage

        page = self.open(HealthPage)
        audio_seul = health_mod.HealthReport(
            issues=[health_mod.Issue("STEREO_DRUM", "info", "Stéréo", "",
                                     ["SAMPLES/DRUMS/Kick/stereo.wav"])],
            score=98)
        page._report = audio_seul
        page._fill_report(audio_seul)
        _APP.processEvents()
        self.assertFalse(audio_seul.auto_fixable())
        self.assertIn("STEREO_DRUM", samplefix.HEALTH_CODES)
        self.assertTrue(page._fix_button.isEnabled())

    def test_la_correction_convertit_vraiment_les_fichiers(self):
        from delugeapp.core import samplefix

        page, report = self._page()
        for index in range(page._issues.count()):
            item = page._issues.item(index)
            if item.data(Qt.ItemDataRole.UserRole) in samplefix.HEALTH_CODES:
                item.setCheckState(Qt.CheckState.Checked)
        coches = page._checked_codes()
        self.assertTrue(coches)

        messages: list = []
        page.status.connect(messages.append)
        page._autofix()
        self.attendre()

        info = wav.probe(self.root / "SAMPLES/DRUMS/Kick/stereo.wav")
        self.assertEqual(info.channels, 1, messages)
        info = wav.probe(self.root / "SAMPLES/DRUMS/Snare/32k.wav")
        self.assertEqual(info.sample_rate, samplefix.DEFAULT_RATE)
        self.assertTrue(
            list((self.root / samplefix.BACKUP_ROOT).glob("samplefix-*")),
            "les originaux devaient être sauvegardés")

    def test_un_refus_de_confirmation_n_ecrit_rien(self):
        """La confirmation est la dernière barrière : elle doit tenir."""
        from PyQt6.QtWidgets import QDialog

        from delugeapp.core import samplefix

        avant = (self.root / "SAMPLES/DRUMS/Kick/stereo.wav").read_bytes()
        page, _report = self._page()
        for index in range(page._issues.count()):
            item = page._issues.item(index)
            if item.data(Qt.ItemDataRole.UserRole) in samplefix.HEALTH_CODES:
                item.setCheckState(Qt.CheckState.Checked)

        self.reponse = QDialog.DialogCode.Rejected
        messages: list = []
        page.status.connect(messages.append)
        page._autofix()
        self.attendre(1200)

        self.assertEqual(
            (self.root / "SAMPLES/DRUMS/Kick/stereo.wav").read_bytes(), avant)
        self.assertFalse((self.root / samplefix.BACKUP_ROOT).exists())
        self.assertTrue(any("annul" in m.lower() for m in messages), messages)

    def test_rien_de_coche(self):
        page, _report = self._page()
        messages: list = []
        page.status.connect(messages.append)
        page._autofix()        # ne doit pas lever
        self.attendre(400)


class TestProcessDialog(WidgetCase):
    """Le dialogue de traitement par lot n'est qu'un formulaire."""

    def _dialog(self, count: int = 3):
        from delugeapp.ui.pages.samples import ProcessDialog

        dialog = ProcessDialog(count)
        self.shown(dialog, 480, 420)
        return dialog

    def test_rien_de_coche_ne_demande_rien(self):
        actions = self._dialog().actions()
        self.assertFalse(actions["mono"])
        self.assertFalse(actions["dc"])
        self.assertIsNone(actions["normalize_db"])
        self.assertIsNone(actions["trim_db"])
        self.assertIsNone(actions["rate"])
        self.assertEqual(actions["fade_ms"], 0.0)

    def test_les_cases_pilotent_les_actions(self):
        from delugeapp.core import samplefix

        dialog = self._dialog()
        dialog._mono.setChecked(True)
        dialog._dc.setChecked(True)
        dialog._norm.setChecked(True)
        dialog._norm_db.setValue(-2.5)
        dialog._trim.setChecked(True)
        dialog._trim_db.setValue(-55.0)
        dialog._fade.setChecked(True)
        dialog._fade_ms.setValue(8.0)
        dialog._rate.setChecked(True)
        dialog._rate_box.setCurrentIndex(0)

        actions = dialog.actions()
        self.assertTrue(actions["mono"])
        self.assertTrue(actions["dc"])
        self.assertAlmostEqual(actions["normalize_db"], -2.5)
        self.assertAlmostEqual(actions["trim_db"], -55.0)
        self.assertAlmostEqual(actions["fade_ms"], 8.0)
        self.assertEqual(actions["rate"], samplefix.STANDARD_RATES[0])

    def test_le_dialogue_annonce_le_dossier_de_sauvegarde(self):
        from PyQt6.QtWidgets import QLabel

        from delugeapp.core import samplefix

        dialog = self._dialog(12)
        textes = " ".join(w.text() for w in dialog.findChildren(QLabel))
        self.assertIn("12", textes)
        self.assertIn(samplefix.BACKUP_ROOT, textes)


class TestSamplesPageProcess(SampleFixUICase):
    """Le traitement par lot depuis la page Échantillons."""

    def _page(self):
        from delugeapp.ui.pages.samples import SamplesPage

        page = self.open(SamplesPage)
        _APP.processEvents()
        return page

    def test_sans_selection_il_ne_se_passe_rien(self):
        page = self._page()
        page._table.clearSelection()
        page._process()            # ne doit pas lever
        self.assertFalse((self.root / "_BACKUP").exists())

    def test_traitement_de_la_selection(self):
        from delugeapp.ui.pages.samples import ProcessDialog

        page = self._page()
        page._table.selectAll()
        _APP.processEvents()
        self.assertTrue(page._selected_rows())

        from unittest import mock

        orig_actions = ProcessDialog.actions
        # ``exec`` est hérité : ``mock.patch`` rend l'héritage en partant.
        remplacement = mock.patch.object(ProcessDialog, "exec",
                                         lambda _self: 1)
        remplacement.start()
        ProcessDialog.actions = lambda _self: {
            "mono": False, "dc": False, "normalize_db": -6.0,
            "trim_db": None, "fade_ms": 0.0, "rate": None}
        messages: list = []
        page.status.connect(messages.append)
        try:
            page._process()
            self.attendre()
        finally:
            remplacement.stop()
            ProcessDialog.actions = orig_actions

        data, _sr = wav.read(self.root / "SAMPLES/DRUMS/Kick/k.wav")
        crete = 20.0 * np.log10(max(float(np.max(np.abs(data))), 1e-9))
        self.assertAlmostEqual(crete, -6.0, delta=0.3, msg=str(messages))
        self.assertTrue(any("corrig" in m for m in messages), messages)

    def test_la_page_annonce_que_la_carte_a_change(self):
        """``cardModified`` existe, et le mainwindow le branche par son nom."""
        from delugeapp.ui.pages.samples import SamplesPage

        self.assertTrue(hasattr(SamplesPage, "cardModified"))
        page = self._page()
        vus: list = []
        page.cardModified.connect(lambda: vus.append(1))
        page.cardModified.emit()
        self.assertEqual(len(vus), 1)


class TestPlanDialogAvertissements(WidgetCase):
    """``PlanDialog`` doit dire ce que le plan va changer."""

    def test_un_plan_qui_change_des_longueurs_est_signale(self):
        from PyQt6.QtWidgets import QLabel

        from delugeapp.core import samplefix
        from delugeapp.ui.widgets.common import PlanDialog

        plan = samplefix.FixPlan(title="Essai")
        plan.edits.append(samplefix.Edit(rel="SAMPLES/a.wav",
                                         actions={"rate": 44100},
                                         before={"sr": 32000}))
        plan.skipped.append(samplefix.Edit(rel="SAMPLES/b.wav",
                                           actions={"rate": 44100},
                                           skipped="cité par un morceau"))
        self.assertTrue(plan.changes_length)

        dialog = PlanDialog(plan, None, "Essai")
        self.shown(dialog, 700, 500)
        textes = " ".join(w.text() for w in dialog.findChildren(QLabel))
        self.assertIn("longueurs", textes)
        self.assertIn("écarté", textes)

    def test_un_plan_sans_changement_de_longueur_n_avertit_pas(self):
        from PyQt6.QtWidgets import QLabel

        from delugeapp.core import samplefix
        from delugeapp.ui.widgets.common import PlanDialog

        plan = samplefix.FixPlan(title="Essai")
        plan.edits.append(samplefix.Edit(rel="SAMPLES/a.wav",
                                         actions={"mono": True},
                                         before={"channels": 2}))
        dialog = PlanDialog(plan, None, "Essai")
        self.shown(dialog, 700, 500)
        textes = " ".join(w.text() for w in dialog.findChildren(QLabel))
        self.assertNotIn("longueurs", textes)


# --------------------------------------------------------------------------- #
# Découpage d'une boucle en kit, côté interface
# --------------------------------------------------------------------------- #

class TestWaveformMarkers(WidgetCase):
    """Les marqueurs multiples ajoutés à ``WaveformView``."""

    def _view(self):
        view = WaveformView()
        peaks = np.stack([-np.abs(np.sin(np.linspace(0, 20, 400))),
                          np.abs(np.sin(np.linspace(0, 20, 400)))],
                         axis=1).astype(np.float32)
        self.shown(view, 600, 120)
        view.set_peaks(peaks, 4.0, 44100)
        return view

    def test_les_marqueurs_sont_tries_et_bornes(self):
        view = self._view()
        view.set_markers([2.0, 0.0, -1.0, 1.0])
        self.assertEqual(view.markers(), [0.0, 0.0, 1.0, 2.0])

    def test_marqueurs_illisibles(self):
        view = self._view()
        view.set_markers(["x", None])      # ne doit pas lever
        self.assertEqual(view.markers(), [])

    def test_marker_at_rend_la_tranche_visee(self):
        view = self._view()
        view.set_markers([0.0, 1.0, 2.0, 3.0])
        self.assertEqual(view.marker_at(2), 0)
        self.assertEqual(view.marker_at(view.width() - 2), 3)
        view.set_markers([])
        self.assertEqual(view.marker_at(10), -1)

    def test_clear_oublie_les_marqueurs(self):
        view = self._view()
        view.set_markers([0.0, 1.0], active=1)
        view.clear()
        self.assertEqual(view.markers(), [])

    def test_le_trace_avec_marqueurs_ne_leve_pas(self):
        view = self._view()
        view.set_markers([0.0, 0.5, 1.0, 2.5], active=2)
        _APP.processEvents()
        image = view.grab().toImage()
        self.assertFalse(image.isNull())


class SliceUICase(PageCase):
    """Base des tests de découpage : une boucle rythmique dans la carte."""

    def setUp(self):
        super().setUp()
        from PyQt6.QtWidgets import QMessageBox

        from delugeapp.core import scan as scan_mod

        sr = 44100
        frames = 88200                      # 2 s, soit 4 temps à 120 BPM
        signal = np.zeros(frames, dtype=np.float32)
        pas = sr // 8
        for index in range(8):
            debut = index * pas
            duree = min(pas // 2, frames - debut)
            t = np.arange(duree, dtype=np.float32) / sr
            signal[debut:debut + duree] = (
                (0.9 if index % 2 == 0 else 0.4)
                * np.sin(2 * np.pi * 180 * t) * np.exp(-t * 40)
            ).astype(np.float32)
        self.boucle = "SAMPLES/DRUMS/Kick/boucle.wav"
        wav.write(self.root / self.boucle, signal, sr)
        scan_mod.scan_card(self.sd, self.lib, compute_hash=True, analyze=True)

        self.reponse = QMessageBox.StandardButton.Yes
        self._boxes = (QMessageBox.question, QMessageBox.information,
                       QMessageBox.warning)
        QMessageBox.question = staticmethod(lambda *a, **k: self.reponse)
        QMessageBox.information = staticmethod(lambda *a, **k: None)
        QMessageBox.warning = staticmethod(lambda *a, **k: None)

    def tearDown(self):
        from PyQt6.QtWidgets import QMessageBox

        (QMessageBox.question, QMessageBox.information,
         QMessageBox.warning) = self._boxes
        super().tearDown()

    def dialog(self, rel: str = ""):
        from delugeapp.ui.pages.samples import SliceDialog

        dlg = SliceDialog(self.ctx, rel or self.boucle)
        self.shown(dlg, 900, 620)
        _APP.processEvents()
        return dlg


class TestSliceDialog(SliceUICase):
    """Le dialogue de découpage."""

    def test_le_dialogue_decoupe_des_l_ouverture(self):
        dlg = self.dialog()
        self.assertTrue(dlg.sliceset)
        self.assertEqual(dlg._list.rowCount(), len(dlg.sliceset))
        self.assertEqual(len(dlg._wave.markers()), len(dlg.sliceset))
        self.assertIn("tranches", dlg._summary.text())
        self.assertTrue(dlg._write.isEnabled())

    def test_changer_de_mode_recalcule(self):
        dlg = self.dialog()
        dlg._mode.setCurrentIndex(1)            # divisions égales
        _APP.processEvents()
        longueurs = {s.frames for s in dlg.sliceset.slices}
        self.assertLessEqual(len(longueurs), 2)
        self.assertFalse(dlg._sens.isEnabled(),
                         "la sensibilité ne concerne que les attaques")
        self.assertFalse(dlg._quant.isEnabled())

        dlg._mode.setCurrentIndex(0)            # attaques
        _APP.processEvents()
        self.assertTrue(dlg._sens.isEnabled())

    def test_le_nombre_de_tranches_se_regle(self):
        dlg = self.dialog()
        dlg._mode.setCurrentIndex(1)
        dlg._count.setValue(4)
        _APP.processEvents()
        self.assertEqual(len(dlg.sliceset), 4)
        self.assertEqual(dlg._list.rowCount(), 4)

    def test_selectionner_une_ligne_met_le_marqueur_en_valeur(self):
        dlg = self.dialog()
        dlg._mode.setCurrentIndex(1)
        dlg._count.setValue(8)
        _APP.processEvents()
        dlg._list.selectRow(3)
        _APP.processEvents()
        self.assertEqual(dlg._wave._marker_active, 3)

    def test_un_clic_sur_l_onde_choisit_la_tranche(self):
        dlg = self.dialog()
        dlg._mode.setCurrentIndex(1)
        dlg._count.setValue(8)
        _APP.processEvents()
        cible = dlg.sliceset.slices[5]
        dlg._on_wave_clicked(cible.start / dlg.sliceset.sr + 0.001)
        _APP.processEvents()
        self.assertEqual(dlg._list.currentRow(), 5)

    def test_ecrire_le_kit(self):
        dlg = self.dialog()
        dlg._mode.setCurrentIndex(1)
        dlg._count.setValue(8)
        _APP.processEvents()

        avant = {p.relative_to(self.root).as_posix()
                 for p in self.root.rglob("*") if p.is_file()}
        dlg._do_write()
        _APP.processEvents()

        self.assertTrue(dlg.written)
        chemin = self.root / dlg.written
        self.assertTrue(chemin.is_file())

        apres = {p.relative_to(self.root).as_posix()
                 for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(apres - avant, {dlg.written},
                         "le découpage ne doit créer que le kit")

        kit = Kit.load(chemin)
        self.assertEqual(len(kit.rows), len(dlg.sliceset))
        self.assertEqual(len({r.file_name for r in kit.rows}), 1,
                         "aucun fichier audio ne doit être dupliqué")
        for row, tranche in zip(kit.rows, dlg.sliceset.slices):
            zone = row.sound.osc1.zone
            self.assertIsNotNone(zone)
            self.assertEqual((zone.start, zone.end),
                             (tranche.start, tranche.end))

    def test_un_refus_n_ecrit_rien(self):
        from PyQt6.QtWidgets import QMessageBox

        dlg = self.dialog()
        self.reponse = QMessageBox.StandardButton.No
        avant = {p.relative_to(self.root).as_posix()
                 for p in self.root.rglob("*") if p.is_file()}
        dlg._do_write()
        _APP.processEvents()
        apres = {p.relative_to(self.root).as_posix()
                 for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(avant, apres)
        self.assertEqual(dlg.written, "")

    def test_exporter_en_fichiers(self):
        dlg = self.dialog()
        dlg._mode.setCurrentIndex(1)
        dlg._count.setValue(4)
        _APP.processEvents()
        dlg._do_export()
        _APP.processEvents()

        dossier = self.root / "SAMPLES" / ("%s TRANCHES"
                                           % Path(self.boucle).stem[:16])
        fichiers = sorted(dossier.glob("*.wav"))
        self.assertEqual(len(fichiers), len(dlg.sliceset))
        total = sum(wav.probe(f).frames for f in fichiers)
        self.assertEqual(total, dlg.sliceset.frames)

    def test_un_echantillon_illisible_n_empeche_pas_l_ouverture(self):
        casse = "SAMPLES/DRUMS/Kick/casse.wav"
        (self.root / casse).write_bytes(b"pas du tout un wav")
        dlg = self.dialog(casse)              # ne doit pas lever
        self.assertEqual(len(dlg.sliceset), 0)
        self.assertFalse(dlg._write.isEnabled())

    def test_sans_lecteur_audio_l_ecoute_ne_casse_rien(self):
        dlg = self.dialog()
        self.assertIsNone(self.ctx.player)
        dlg._list.selectRow(0)
        dlg._play_selected()                  # ne doit pas lever


class TestSamplesPageSlice(SliceUICase):
    """Le bouton « Découper… » de la page Échantillons."""

    def _page(self):
        from delugeapp.ui.pages.samples import SamplesPage

        page = self.open(SamplesPage)
        _APP.processEvents()
        return page

    def test_le_bouton_existe(self):
        page = self._page()
        self.assertIn("Découper", _libelle(page._slice_button))

    def test_sans_selection_rien_ne_se_passe(self):
        page = self._page()
        page._table.clearSelection()
        page._slice()                         # ne doit pas lever
        self.assertFalse(list((self.root / "KITS").glob("boucle*.XML")))

    def test_une_selection_multiple_est_refusee(self):
        """Le découpage porte sur une boucle à la fois."""
        page = self._page()
        page._table.selectAll()
        _APP.processEvents()
        self.assertGreater(len(page._selected_rows()), 1,
                           "la carte d'essai doit contenir plusieurs "
                           "échantillons")
        avant = {p.relative_to(self.root).as_posix()
                 for p in self.root.rglob("*") if p.is_file()}
        page._slice()
        _APP.processEvents()
        apres = {p.relative_to(self.root).as_posix()
                 for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(avant, apres)


# --------------------------------------------------------------------------- #
# Recherche par ressemblance, côté interface
# --------------------------------------------------------------------------- #

class TestSamplesPageSimilar(PageCase):
    """Le bouton « Sons proches » de la page Échantillons."""

    def setUp(self):
        super().setUp()
        from PyQt6.QtWidgets import QMessageBox

        from delugeapp.core import scan as scan_mod

        # Trois graves et trois aigus : deux familles franches, de quoi
        # vérifier que les voisins ne sont pas pris au hasard.
        sr = 44100
        rng = np.random.default_rng(13)
        for index in range(3):
            t = np.linspace(0, 0.25, int(0.25 * sr), endpoint=False,
                            dtype=np.float32)
            wav.write(self.root / ("SAMPLES/DRUMS/Kick/g%d.wav" % index),
                      (0.8 * np.sin(2 * np.pi * (55 + index * 3) * t)
                       * np.exp(-t * 18)).astype(np.float32), sr)
            n = int(0.12 * sr)
            bruit = rng.standard_normal(n).astype(np.float32)
            aigu = np.diff(bruit, prepend=np.float32(0.0))
            wav.write(self.root / ("SAMPLES/DRUMS/Snare/a%d.wav" % index),
                      (0.5 * aigu).astype(np.float32), sr)
        scan_mod.scan_card(self.sd, self.lib, compute_hash=True, analyze=True)

        self._boxes = (QMessageBox.information, QMessageBox.warning)
        QMessageBox.information = staticmethod(lambda *a, **k: None)
        QMessageBox.warning = staticmethod(lambda *a, **k: None)

    def tearDown(self):
        from PyQt6.QtWidgets import QMessageBox

        (QMessageBox.information, QMessageBox.warning) = self._boxes
        super().tearDown()

    def _page(self):
        from delugeapp.ui.pages.samples import SamplesPage

        page = self.open(SamplesPage)
        _APP.processEvents()
        return page

    def _select(self, page, fragment: str) -> str:
        """Sélectionne la ligne dont le chemin contient ``fragment``."""
        for ligne in range(page._proxy.rowCount()):
            index = page._proxy.index(ligne, 0)
            row = page._model.row_at(page._proxy.mapToSource(index).row())
            if row is not None and fragment in str(row["rel"]):
                page._table.selectRow(ligne)
                _APP.processEvents()
                return str(row["rel"])
        self.fail("ligne introuvable pour %r" % fragment)

    def test_le_bouton_existe(self):
        page = self._page()
        self.assertIn("proches", _libelle(page._similar_button))

    def test_sans_selection_rien_ne_se_passe(self):
        page = self._page()
        page._table.clearSelection()
        page._toggle_similar()          # ne doit pas lever
        self.assertEqual(page._similar_to, "")

    def test_la_vue_proche_filtre_et_ordonne(self):
        page = self._page()
        depart = self._select(page, "Kick/g0.wav")
        total = page._proxy.rowCount()

        page._toggle_similar()
        _APP.processEvents()

        self.assertEqual(page._similar_to, depart)
        self.assertLess(page._proxy.rowCount(), total,
                        "la vue proche doit restreindre la liste")
        self.assertNotIn("g0.wav",
                         [str(r["rel"]) for r in page._model.rows()][:1],
                         "le son de départ ne doit pas figurer en tête")

        # Les lignes portent une proximité décroissante.
        proximites = [r["closeness"] for r in page._model.rows()]
        self.assertTrue(proximites)
        self.assertEqual(proximites, sorted(proximites, reverse=True))

        # Et la colonne de proximité est apparue.
        titres = [c[0] for c in page._model.columns()]
        self.assertEqual(titres[0], "Proximité")

    def test_le_bouton_fait_aller_et_retour(self):
        page = self._page()
        self._select(page, "Kick/g0.wav")
        total = page._proxy.rowCount()

        page._toggle_similar()
        _APP.processEvents()
        self.assertEqual(page._similar_button.text(), "Toute la liste")

        page._toggle_similar()
        _APP.processEvents()
        self.assertEqual(page._similar_to, "")
        self.assertIn("proches", _libelle(page._similar_button))
        self.assertEqual(page._proxy.rowCount(), total)
        titres = [c[0] for c in page._model.columns()]
        self.assertNotEqual(titres[0], "Proximité",
                            "la colonne de proximité doit disparaître")

    def test_les_voisins_sont_de_la_bonne_famille(self):
        page = self._page()
        self._select(page, "Kick/g0.wav")
        page._toggle_similar()
        _APP.processEvents()

        premiers = [str(r["rel"]) for r in page._model.rows()][:2]
        graves = sum(1 for rel in premiers if "/Kick/" in rel)
        self.assertGreaterEqual(graves, 1,
                                "les premiers voisins d'un grave : %s"
                                % premiers)

    def test_un_son_sans_descripteur_est_refuse(self):
        page = self._page()
        self.lib.con.execute("UPDATE samples SET attack = NULL "
                             "WHERE rel LIKE '%g0.wav'")
        self.lib.commit()
        page._space = None
        self._select(page, "Kick/g0.wav")
        page._toggle_similar()          # ne doit pas lever
        self.assertEqual(page._similar_to, "",
                         "un son non analysé ne doit pas entrer dans la vue")

    def test_la_ligne_enrichie_se_comporte_comme_une_ligne(self):
        from delugeapp.ui.pages.samples import ScoredRow

        row = self.lib.get("sample", "SAMPLES/DRUMS/Kick/g0.wav")
        enrichie = ScoredRow(row, 87, 0.14)
        self.assertEqual(enrichie["closeness"], 87)
        self.assertAlmostEqual(enrichie["distance"], 0.14)
        self.assertEqual(enrichie["rel"], row["rel"])
        self.assertIn("closeness", enrichie.keys())
        self.assertIn("rel", enrichie.keys())


# --------------------------------------------------------------------------- #
# Exports de la page Morceaux
# --------------------------------------------------------------------------- #

class TestSongsPageExport(PageCase):
    """Export MIDI du morceau entier, et rassemblement des dépendances."""

    def setUp(self):
        super().setUp()
        from PyQt6.QtWidgets import QDialog, QMessageBox

        from delugeapp.ui.widgets.common import PlanDialog

        from unittest import mock

        self.reponse = QDialog.DialogCode.Accepted
        # ``exec`` est hérité de ``QDialog`` : le sauvegarder puis le
        # réaffecter épinglait sur ``PlanDialog`` le rempart de la suite (cf.
        # ``WidgetCase._aucun_rempart_epingle``). ``mock.patch`` rend
        # l'héritage.
        self._plan_exec = mock.patch.object(PlanDialog, "exec",
                                            lambda _self: self.reponse)
        self._plan_exec.start()

        self._boxes = (QMessageBox.question, QMessageBox.information,
                       QMessageBox.warning)
        QMessageBox.question = staticmethod(
            lambda *a, **k: QMessageBox.StandardButton.Yes)
        QMessageBox.information = staticmethod(lambda *a, **k: None)
        QMessageBox.warning = staticmethod(lambda *a, **k: None)

    def tearDown(self):
        from PyQt6.QtWidgets import QMessageBox

        self._plan_exec.stop()
        (QMessageBox.question, QMessageBox.information,
         QMessageBox.warning) = self._boxes
        super().tearDown()

    def _page(self):
        from delugeapp.ui.pages.songs import SongsPage

        page = self.open(SongsPage)
        _APP.processEvents()
        page._table.selectRow(0)
        _APP.processEvents()
        return page

    def _attendre(self, ms: int = 4000) -> None:
        from PyQt6.QtCore import QEventLoop, QTimer

        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    # -- MIDI --------------------------------------------------------------- #

    def test_les_boutons_existent(self):
        page = self._page()
        self.assertIn("MIDI", _libelle(page._song_midi))
        self.assertIn("Rassembler", _libelle(page._pack))

    def test_export_midi_du_morceau(self):
        from PyQt6.QtWidgets import QFileDialog

        page = self._page()
        self.assertIsNotNone(page._song, "aucun morceau chargé")

        cible = Path(self._tmp.name) / "morceau.mid"
        original = QFileDialog.getSaveFileName
        QFileDialog.getSaveFileName = staticmethod(
            lambda *a, **k: (str(cible), ""))
        messages: list = []
        page.status.connect(messages.append)
        try:
            page._export_song_midi()
            _APP.processEvents()
        finally:
            QFileDialog.getSaveFileName = original

        self.assertTrue(cible.is_file(), messages)
        donnees = cible.read_bytes()
        self.assertEqual(donnees[:4], b"MThd")
        self.assertGreaterEqual(int.from_bytes(donnees[10:12], "big"), 2)
        self.assertTrue(any("piste" in m for m in messages), messages)

    def test_un_morceau_sans_note_ne_s_exporte_pas(self):
        from PyQt6.QtWidgets import QFileDialog

        page = self._page()
        page._song.clips = []
        page._song.arrangement_clips = []

        cible = Path(self._tmp.name) / "vide.mid"
        original = QFileDialog.getSaveFileName
        QFileDialog.getSaveFileName = staticmethod(
            lambda *a, **k: (str(cible), ""))
        messages: list = []
        page.status.connect(messages.append)
        try:
            page._export_song_midi()
            _APP.processEvents()
        finally:
            QFileDialog.getSaveFileName = original

        self.assertFalse(cible.exists())
        self.assertTrue(any("aucune note" in m.lower() for m in messages),
                        messages)

    # -- rassemblement ------------------------------------------------------ #

    def test_rassemblement_dans_un_dossier(self):
        from PyQt6.QtWidgets import QFileDialog

        page = self._page()
        dossier = Path(self._tmp.name) / "ailleurs"
        dossier.mkdir()
        original = QFileDialog.getExistingDirectory
        QFileDialog.getExistingDirectory = staticmethod(
            lambda *a, **k: str(dossier))
        messages: list = []
        page.status.connect(messages.append)
        try:
            page._export_pack()
            self._attendre()
        finally:
            QFileDialog.getExistingDirectory = original

        produits = [p for p in dossier.rglob("*") if p.is_file()]
        self.assertTrue(produits, messages)
        racines = {p.relative_to(dossier).parts[1] for p in produits}
        self.assertTrue(racines <= {"SONGS", "SYNTHS", "KITS", "SAMPLES"},
                        racines)
        self.assertIn("SONGS", racines)

        from delugeapp.core.model import Song

        copie = next(p for p in dossier.rglob("*.XML")
                     if p.parent.name.upper() == "SONGS")
        relu = Song.load(copie)
        copie_sd = sdcard.SDCard(copie.parent.parent)
        absents = [r for r in relu.sample_paths()
                   if copie_sd.resolve_sample(r) is None]
        self.assertEqual(absents, [], "la copie est incomplète")

    def test_un_refus_de_confirmation_ne_copie_rien(self):
        from PyQt6.QtWidgets import QDialog, QFileDialog

        page = self._page()
        dossier = Path(self._tmp.name) / "refus"
        dossier.mkdir()
        self.reponse = QDialog.DialogCode.Rejected
        original = QFileDialog.getExistingDirectory
        QFileDialog.getExistingDirectory = staticmethod(
            lambda *a, **k: str(dossier))
        try:
            page._export_pack()
            self._attendre(800)
        finally:
            QFileDialog.getExistingDirectory = original

        self.assertEqual([p for p in dossier.rglob("*") if p.is_file()], [])

    def test_le_rassemblement_ne_touche_pas_la_carte(self):
        from PyQt6.QtWidgets import QFileDialog

        page = self._page()
        avant = {p.relative_to(self.root).as_posix():
                 hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in self.root.rglob("*") if p.is_file()}

        dossier = Path(self._tmp.name) / "copie"
        dossier.mkdir()
        original = QFileDialog.getExistingDirectory
        QFileDialog.getExistingDirectory = staticmethod(
            lambda *a, **k: str(dossier))
        try:
            page._export_pack()
            self._attendre()
        finally:
            QFileDialog.getExistingDirectory = original

        apres = {p.relative_to(self.root).as_posix():
                 hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(apres, avant)

    def test_sans_morceau_selectionne(self):
        from delugeapp.ui.pages.songs import SongsPage

        page = self.open(SongsPage)
        page._song = None
        page._current = ""
        page._export_song_midi()        # ne doit pas lever
        page._export_pack()             # ne doit pas lever

    def test_le_plan_enveloppe_se_comporte_comme_un_plan(self):
        """``PlanDialog`` n'exige que summary/counts/to_text."""
        from delugeapp.core import songpack
        from delugeapp.ui.pages.songs import _PackPlan

        pack = songpack.collect(self.sd, "SONGS/M.XML")
        plan = _PackPlan(pack)
        self.assertTrue(plan.summary())
        self.assertIn("copie", plan.counts())
        self.assertEqual(plan.counts()["copie"], len(pack.files()))
        self.assertIn(pack.song_rel, plan.to_text())
        self.assertEqual(len(plan), len(pack))


# --------------------------------------------------------------------------- #
# Le test qui manquait : cliquer vraiment sur les boutons
# --------------------------------------------------------------------------- #

class InteractionCase(PageCase):
    """Fixture commune aux tests d'interaction : toutes les sorties fermées.

    Séparée des tests eux-mêmes pour que les deux classes qui l'utilisent ne
    rejouent pas les tests de l'autre — hériter d'un ``TestCase`` qui porte
    des tests les fait tourner deux fois.
    """

    def _pages(self):
        from delugeapp.ui.pages.atelier import AtelierPage
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
                GeneratorPage, AtelierPage, ToolboxPage, HealthPage,
                SettingsPage)


class TestClicsReels(InteractionCase):
    """Chaque bouton de chaque page doit supporter un **vrai clic**.

    C'est le trou qui a laissé passer 55 boutons cassés. Les tests appelaient
    les méthodes directement — ``page._listen()`` — alors que Qt les appelle
    avec l'argument du signal : ``clicked(bool)``. PyQt tronque d'ordinaire
    les arguments excédentaires selon l'arité du destinataire, mais
    ``Page.guard`` enveloppait tout dans un ``wrapper(*args, **kwargs)``
    variadique : PyQt croyait donc que le destinataire voulait tout, et le
    booléen arrivait à une méthode sans paramètre.

        TypeError: GeneratorPage._listen() takes 1 positional argument
                   but 2 were given

    L'utilisateur voyait « Action impossible : voir le journal » sur presque
    chaque bouton. Rien dans la suite ne l'attrapait.
    """

    def setUp(self):
        super().setUp()
        from PyQt6.QtWidgets import (QDialog, QFileDialog, QInputDialog,
                                     QMessageBox)

        # Toutes les portes de sortie sont fermées : un clic ne doit donc
        # rien écrire. On teste le branchement, pas les actions.
        #
        # ``QDialog.exec`` est neutralisé **sur la classe de base**, ce qui
        # couvre d'un coup PlanDialog, ProcessDialog, SliceDialog et tout
        # dialogue à venir : aucun n'a sa propre ``exec``. Sans cela le test
        # se bloque sur la première boîte modale — et il s'est bloqué, sur
        # les ``QInputDialog`` de la page Générateur, que j'avais oubliés.
        self._sauvegardes = {
            "question": QMessageBox.question,
            "information": QMessageBox.information,
            "warning": QMessageBox.warning,
            "critical": QMessageBox.critical,
            "about": QMessageBox.about,
            "save": QFileDialog.getSaveFileName,
            "open": QFileDialog.getOpenFileName,
            "opens": QFileDialog.getOpenFileNames,
            "dir": QFileDialog.getExistingDirectory,
            "text": QInputDialog.getText,
            "int": QInputDialog.getInt,
            "item": QInputDialog.getItem,
            "exec": QDialog.exec,
        }
        QMessageBox.question = staticmethod(
            lambda *a, **k: QMessageBox.StandardButton.No)
        QMessageBox.information = staticmethod(lambda *a, **k: None)
        QMessageBox.warning = staticmethod(lambda *a, **k: None)
        QMessageBox.critical = staticmethod(lambda *a, **k: None)
        QMessageBox.about = staticmethod(lambda *a, **k: None)
        QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: ("", ""))
        QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: ("", ""))
        QFileDialog.getOpenFileNames = staticmethod(lambda *a, **k: ([], ""))
        QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: "")
        QInputDialog.getText = staticmethod(lambda *a, **k: ("", False))
        QInputDialog.getInt = staticmethod(lambda *a, **k: (0, False))
        QInputDialog.getItem = staticmethod(lambda *a, **k: ("", False))
        QDialog.exec = lambda _self: QDialog.DialogCode.Rejected

    def tearDown(self):
        from PyQt6.QtWidgets import (QDialog, QFileDialog, QInputDialog,
                                     QMessageBox)

        s = self._sauvegardes
        QMessageBox.question = s["question"]
        QMessageBox.information = s["information"]
        QMessageBox.warning = s["warning"]
        QMessageBox.critical = s["critical"]
        QMessageBox.about = s["about"]
        QFileDialog.getSaveFileName = s["save"]
        QFileDialog.getOpenFileName = s["open"]
        QFileDialog.getOpenFileNames = s["opens"]
        QFileDialog.getExistingDirectory = s["dir"]
        QInputDialog.getText = s["text"]
        QInputDialog.getInt = s["int"]
        QInputDialog.getItem = s["item"]
        QDialog.exec = s["exec"]
        super().tearDown()

    @staticmethod
    def _choisir_une_ligne(page) -> None:
        """Choisit la première ligne de chaque liste de la page.

        Les actions qui portent sur une sélection sont éteintes tant que rien
        n'est choisi. Sans ce geste — celui que fait l'utilisateur avant de
        cliquer — le test ne verrait d'elles qu'un bouton gris et les
        laisserait hors de sa surveillance.
        """
        from PyQt6.QtWidgets import (QListWidget, QTableView, QTableWidget,
                                     QTreeWidget)

        for table in (page.findChildren(QTableView)
                      + page.findChildren(QTableWidget)):
            modele = table.model()
            if modele is not None and modele.rowCount() > 0:
                table.selectRow(0)
        for liste in page.findChildren(QListWidget):
            if liste.count():
                liste.setCurrentRow(0)
        for arbre in page.findChildren(QTreeWidget):
            if arbre.topLevelItemCount():
                arbre.setCurrentItem(arbre.topLevelItem(0))
        _APP.processEvents()

    def test_chaque_bouton_supporte_un_vrai_clic(self):
        """Aucun clic ne doit produire d'erreur dans le journal."""
        from PyQt6.QtWidgets import QAbstractButton

        from delugeapp.ui import tasks

        total = 0
        for cls in self._pages():
            page = self.open(cls)
            self._choisir_une_ligne(page)

            tous = page.findChildren(QAbstractButton)
            self.assertTrue(tous, "%s : aucun bouton" % cls.__name__)
            # Un bouton éteint par manque de sélection s'allumera plus tard :
            # son branchement doit tenir tout autant. On l'allume de force
            # pour le cliquer, après avoir essayé ceux qui l'étaient déjà.
            boutons = ([b for b in tous if b.isEnabled()]
                       + [b for b in tous if not b.isEnabled()])
            for bouton in boutons:
                etiquette = bouton.text() or bouton.toolTip() or "(sans nom)"
                with self.subTest(page=cls.__name__, bouton=etiquette[:40]):
                    bouton.setEnabled(True)
                    # ``assertNoLogs`` échoue si le rempart de ``Page.guard``
                    # a dû absorber quoi que ce soit.
                    with self.assertNoLogs("delugeapp.ui.pages.base",
                                           level="ERROR"):
                        bouton.click()
                        _APP.processEvents()
                total += 1
            tasks.stop_all(2000)

        self.assertGreater(total, 40,
                           "trop peu de boutons essayés : %d" % total)

    def test_un_clic_atteint_vraiment_la_methode(self):
        """Sans cela, le test précédent passerait même si rien n'arrivait."""
        from delugeapp.ui.pages.base import Page

        class Fausse(Page):
            TITLE = "Essai"
            NEEDS_CARD = False

            def __init__(self, ctx, parent=None):
                super().__init__(ctx, parent)
                self.appels = 0
                self.recus = None

            def build(self):
                from PyQt6.QtWidgets import QPushButton, QVBoxLayout

                layout = QVBoxLayout(self.content())
                self.sans_arg = QPushButton("sans argument")
                self.sans_arg.clicked.connect(self.guard(self._sans_arg))
                layout.addWidget(self.sans_arg)

                self.avec_arg = QPushButton("avec argument")
                self.avec_arg.clicked.connect(self.guard(self._avec_arg))
                layout.addWidget(self.avec_arg)

            def _sans_arg(self):
                self.appels += 1

            def _avec_arg(self, coche):
                self.recus = coche

        page = Fausse(self.ctx)
        self.shown(page, 300, 200)
        page.refresh()
        _APP.processEvents()

        page.sans_arg.click()
        _APP.processEvents()
        self.assertEqual(page.appels, 1,
                         "la méthode sans argument n'a pas été appelée")

        # Un destinataire qui veut l'argument doit encore le recevoir.
        page.avec_arg.click()
        _APP.processEvents()
        self.assertIs(page.recus, False,
                      "l'argument du signal n'est plus transmis")

    def test_guard_transmet_ce_qui_est_attendu(self):
        """``guard`` tronque l'excédent, jamais le nécessaire."""
        from delugeapp.ui.pages.base import Page

        page = Page(self.ctx)
        self.shown(page, 200, 100)
        vus: list = []

        page.guard(lambda: vus.append(()))(1, 2, 3)
        page.guard(lambda a: vus.append((a,)))(1, 2, 3)
        page.guard(lambda a, b: vus.append((a, b)))(1, 2, 3)
        page.guard(lambda *a: vus.append(a))(1, 2, 3)

        self.assertEqual(vus, [(), (1,), (1, 2), (1, 2, 3)])

    def test_un_resultat_tardif_n_atteint_pas_une_page_fermee(self):
        """Un fil rend son résultat par un signal **mis en file**.

        Il peut donc être délivré après la fermeture de la fenêtre, donc
        après ``AppContext.close()``. C'est arrivé dès que le diagnostic de
        santé est parti tout seul à l'affichage : trois « Cannot operate on
        a closed database » dans le journal, à chaque fermeture.
        """
        from delugeapp.ui.pages.base import Page

        page = Page(self.ctx)
        self.shown(page, 200, 100)
        appels = []
        rappel = page.guard(lambda: appels.append(1))

        rappel()
        self.assertEqual(appels, [1], "le rappel normal ne passe pas")

        self.ctx.closed = True
        try:
            rappel()
            self.assertEqual(
                appels, [1],
                "un résultat tardif a atteint une page dont le contexte "
                "est fermé")
        finally:
            self.ctx.closed = False

    def test_fermer_le_contexte_le_marque_ferme(self):
        """Sans ce drapeau, le rempart précédent ne peut rien savoir."""
        from delugeapp.config import AppContext, Settings

        ctx = AppContext(settings=Settings())
        self.assertFalse(ctx.closed)
        ctx.close()
        self.assertTrue(ctx.closed)

    def test_guard_absorbe_toujours_les_exceptions(self):
        """La troncature ne doit pas avoir désarmé le rempart (SPEC §6.3)."""
        from delugeapp.ui.pages.base import Page

        page = Page(self.ctx)
        self.shown(page, 200, 100)
        messages: list = []
        page.status.connect(messages.append)

        def boum():
            raise RuntimeError("volontaire")

        with self.assertLogs("delugeapp.ui.pages.base", level="ERROR"):
            page.guard(boum)()
        self.assertTrue(messages)

    def test_l_arite_est_calculee_juste(self):
        import functools

        from delugeapp.ui.pages.base import _arite

        def sans_arg():
            pass

        def deux(a, b=1):
            pass

        def variadique(*a):
            pass

        def seulement_nommes(*, x=1):
            pass

        cas = [(sans_arg, 0), (deux, 2), (variadique, None),
               (seulement_nommes, 0), (lambda: None, 0),
               (lambda _x: None, 1),
               (functools.partial(deux, 1), 1),
               (print, None)]
        for fn, attendu in cas:
            with self.subTest(fn=getattr(fn, "__name__", type(fn).__name__)):
                self.assertEqual(_arite(fn), attendu)


class TestInteractionsReelles(InteractionCase):
    """Tout ce qu'un utilisateur peut toucher, et pas seulement les boutons.

    Complète :class:`TestClicsReels`, qui a attrapé 55 boutons inertes, sur
    le reste de la surface : onglets, lignes de tableau, listes déroulantes,
    cases à cocher, curseurs, champs de saisie. Mesuré à l'écriture :
    **398 interactions, 0 erreur** — les boutons étaient bien le seul chemin
    cassé, parce que seuls eux passaient par une enveloppe variadique
    branchée sur un signal porteur d'un argument indésirable.

    Le test reste utile : c'est le filet qui dira si une prochaine retouche
    casse un de ces chemins.
    """

    def _toucher_tout(self, page, nom_page: str) -> int:
        """Touche chaque widget interactif de la page. Retourne le compte."""
        from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox,
                                     QLineEdit, QSlider, QSpinBox,
                                     QTabWidget, QTableView, QTableWidget)

        total = 0

        for onglets in page.findChildren(QTabWidget):
            for index in range(onglets.count()):
                with self.subTest(page=nom_page,
                                  onglet=onglets.tabText(index)):
                    with self.assertNoLogs("delugeapp.ui.pages.base",
                                           level="ERROR"):
                        onglets.setCurrentIndex(index)
                        _APP.processEvents()
                total += 1

        tables = (page.findChildren(QTableView)
                  + page.findChildren(QTableWidget))
        for table in tables:
            modele = table.model()
            lignes = modele.rowCount() if modele is not None else 0
            for ligne in range(min(lignes, 3)):
                with self.subTest(page=nom_page, ligne=ligne):
                    with self.assertNoLogs("delugeapp.ui.pages.base",
                                           level="ERROR"):
                        table.selectRow(ligne)
                        _APP.processEvents()
                total += 1

        for combo in page.findChildren(QComboBox):
            for index in range(combo.count()):
                with self.subTest(page=nom_page,
                                  liste=combo.itemText(index)[:24]):
                    with self.assertNoLogs("delugeapp.ui.pages.base",
                                           level="ERROR"):
                        combo.setCurrentIndex(index)
                        # ``activated`` n'est émis que par l'utilisateur :
                        # plusieurs pages n'écoutent que celui-là.
                        combo.activated.emit(index)
                        _APP.processEvents()
                total += 1

        for case in page.findChildren(QCheckBox):
            for etat in (not case.isChecked(), case.isChecked()):
                with self.subTest(page=nom_page, case=case.text()[:24]):
                    with self.assertNoLogs("delugeapp.ui.pages.base",
                                           level="ERROR"):
                        case.setChecked(etat)
                        _APP.processEvents()
                total += 1

        curseurs = (page.findChildren(QSlider) + page.findChildren(QSpinBox)
                    + page.findChildren(QDoubleSpinBox))
        for curseur in curseurs:
            bas, haut = curseur.minimum(), curseur.maximum()
            for valeur in (bas, (bas + haut) / 2, haut):
                with self.subTest(page=nom_page,
                                  curseur=type(curseur).__name__):
                    with self.assertNoLogs("delugeapp.ui.pages.base",
                                           level="ERROR"):
                        curseur.setValue(type(bas)(valeur))
                        _APP.processEvents()
                total += 1

        for champ in page.findChildren(QLineEdit):
            for texte in ("essai", ""):
                with self.subTest(page=nom_page, saisie=texte or "(vide)"):
                    with self.assertNoLogs("delugeapp.ui.pages.base",
                                           level="ERROR"):
                        champ.setText(texte)
                        champ.returnPressed.emit()
                        _APP.processEvents()
                total += 1

        return total

    def test_toute_la_surface_interactive_des_pages(self):
        from delugeapp.ui import tasks

        total = 0
        for cls in self._pages():
            page = self.open(cls)
            total += self._toucher_tout(page, cls.__name__)
            tasks.stop_all(2000)

        self.assertGreater(total, 150,
                           "trop peu d'interactions essayées : %d" % total)


class TestLisibilite(unittest.TestCase):
    """Les textes doivent se lire, et cela se calcule.

    Mesuré avant correction : le gris des sous-titres — celui des phrases
    qui **expliquent** — tombait à 3,78 de contraste sur une surface
    relevée, et deux couleurs de page servant de titre à 4,26 et 3,51. La
    norme WCAG demande 4,5 pour un texte courant.
    """

    #: Seuil d'un texte courant.
    SEUIL = 4.5

    def test_la_feuille_de_style_se_construit_vraiment(self):
        """Une coquille dans le thème dégradait **toute** l'apparence en
        silence.

        ``qss()`` attrape l'erreur de substitution et rend un style minimal :
        l'application démarre, mais grise et plate, et seule une ligne de
        journal le dit. C'est arrivé en ajoutant ``TEXT_SOFT`` sans le
        déclarer dans la table d'injection.
        """
        with self.assertNoLogs("delugeapp.ui.theme", level="ERROR"):
            feuille = theme.qss()
        self.assertGreater(len(feuille), 5000,
                           "style minimal : la substitution a échoué")
        # Quelques jetons qui doivent y être, dont le dernier ajouté.
        for jeton in (theme.PAD_WHITE, theme.PANEL, theme.TEXT_SOFT,
                      "QPushButton", "QTableView"):
            self.assertIn(jeton, feuille, jeton)
        self.assertNotIn("${", feuille, "une variable n'a pas été remplacée")

    def test_chaque_accent_donne_une_feuille_complete(self):
        """L'utilisateur peut choisir son accent : aucun ne doit casser."""
        for accent in (theme.GOLD, "#2FAF6F", "#F04FA8", "#6B5CE7"):
            with self.assertNoLogs("delugeapp.ui.theme", level="ERROR"):
                feuille = theme.qss(accent)
            self.assertGreater(len(feuille), 5000, accent)

    def test_le_calcul_de_contraste_est_juste(self):
        """Deux repères connus : noir sur blanc vaut 21, une couleur sur
        elle-même vaut 1."""
        self.assertAlmostEqual(theme.contrast("#000000", "#FFFFFF"), 21.0,
                               places=1)
        self.assertAlmostEqual(theme.contrast("#3DD160", "#3DD160"), 1.0,
                               places=3)

    def test_les_textes_se_lisent_sur_tous_les_fonds(self):
        fonds = {"fond de fenêtre": theme.PANEL_LO,
                 "panneau": theme.PANEL,
                 "surface relevée": theme.PANEL_HI,
                 "ligne alternée": theme.ALT_ROW,
                 "champ de saisie": theme.INPUT_BG}
        textes = {"texte principal": theme.PAD_WHITE,
                  "texte secondaire": theme.TEXT_SOFT,
                  "accent": theme.GOLD}
        faibles = []
        for nom_texte, couleur in textes.items():
            for nom_fond, fond in fonds.items():
                rapport = theme.contrast(couleur, fond)
                if rapport < self.SEUIL:
                    faibles.append("%s sur %s : %.2f"
                                   % (nom_texte, nom_fond, rapport))
        self.assertEqual(faibles, [], "; ".join(faibles))

    def test_chaque_couleur_de_page_se_lit_en_titre(self):
        """``readable`` éclaircit juste ce qu'il faut, et pas davantage."""
        for cle, couleur in theme.PAGE_COLORS.items():
            lisible = theme.readable(couleur)
            self.assertGreaterEqual(
                theme.contrast(lisible, theme.PANEL), self.SEUIL,
                "%s : %s" % (cle, lisible))

    def test_le_texte_d_un_bouton_colore_se_lit(self):
        """Blanc sur vert, cyan ou or : 1,7 à 2,4 de contraste.

        ``text_on`` gardait un seuil réglé pour une luminance perçue alors
        que ``luminance`` était devenue celle de la norme WCAG, bien plus
        basse pour les teintes moyennes : tous les boutons principaux
        colorés écrivaient en blanc.
        """
        for cle, couleur in theme.PAGE_COLORS.items():
            with self.subTest(page=cle):
                choisi = theme.contrast(theme.text_on(couleur), couleur)
                meilleur = max(theme.contrast(theme.INK, couleur),
                               theme.contrast(theme.PAD_WHITE, couleur))
                self.assertEqual(choisi, meilleur)
                self.assertGreater(choisi, 4.0)

    def test_une_couleur_deja_lisible_n_est_pas_touchee(self):
        """Sinon toutes les teintes dériveraient vers le blanc."""
        for cle in ("Samples", "Kits", "Toolbox", "Dashboard"):
            couleur = theme.PAGE_COLORS[cle]
            self.assertEqual(theme.readable(couleur), couleur, cle)

    def test_le_titre_de_section_garde_la_couleur_exacte_pour_son_trait(self):
        """Le trait dit la page, le libellé doit se lire : deux besoins."""
        titre = common.SectionTitle("Essai", color=theme.PAGE_COLORS["Settings"])
        self.assertEqual(titre.color(), theme.PAGE_COLORS["Settings"])
        feuille = titre._label.styleSheet()
        self.assertIn(theme.readable(theme.PAGE_COLORS["Settings"]).lower(),
                      feuille.lower())


class TestPetitEcran(MainWindowCase):
    """Les listes doivent tenir à toutes les tailles de fenêtre.

    Mes largeurs de colonnes avaient été réglées pour 1 440 px — la taille
    de mes captures, pas celle d'un portable. Mesuré avant correction : à
    1 366 × 768, les listes Kits et Morceaux débordaient ; à 980 × 640, les
    quatre. Une barre de défilement horizontale cachait alors exactement les
    colonnes qu'on venait de rendre lisibles.
    """

    #: La fenêtre ne descend pas en dessous (``setMinimumSize``).
    TAILLES = ((1920, 1080), (1440, 900), (1366, 768), (1180, 720),
               (980, 640))

    LISTES = ("Samples", "Synths", "Kits", "Songs")

    def _mesurer(self, win, largeur, hauteur):
        win.resize(largeur, hauteur)
        for _ in range(6):
            _APP.processEvents()
        resultats = {}
        for cle in self.LISTES:
            win.go_to(cle)
            for _ in range(6):
                _APP.processEvents()
            table = win._pages[cle]._table
            entete = table.horizontalHeader()
            visibles = [i for i in range(entete.count())
                        if not table.isColumnHidden(i)]
            somme = sum(entete.sectionSize(i) for i in visibles)
            resultats[cle] = (len(visibles), entete.count(), somme,
                              table.viewport().width())
        return resultats

    def test_aucune_liste_ne_deborde_jamais(self):
        win = self.window()
        debordements = []
        for largeur, hauteur in self.TAILLES:
            for cle, (vis, total, somme, vue) in self._mesurer(
                    win, largeur, hauteur).items():
                if somme > vue:
                    debordements.append(
                        "%s à %d×%d : %d px pour %d"
                        % (cle, largeur, hauteur, somme, vue))
                self.assertGreaterEqual(
                    vis, 1, "%s à %d : plus une seule colonne"
                    % (cle, largeur))
        self.assertEqual(debordements, [], "; ".join(debordements))

    def test_toutes_les_colonnes_reviennent_en_grand(self):
        """Cacher est provisoire : rien ne doit rester perdu."""
        win = self.window()
        petit = self._mesurer(win, 980, 640)
        grand = self._mesurer(win, 1440, 900)
        for cle in self.LISTES:
            self.assertLess(petit[cle][0], grand[cle][0] + 1, cle)
            self.assertEqual(grand[cle][0], grand[cle][1],
                             "%s : %d colonnes sur %d à 1440 px"
                             % (cle, grand[cle][0], grand[cle][1]))

    def test_la_barre_d_actions_se_replie_au_lieu_d_etre_coupee(self):
        """À 1 180 px, la page Échantillons affichait « Dans l'explorat ».

        Un libellé coupé en plein mot est pire que pas de libellé : chaque
        bouton ayant son explication, il peut se réduire à son icône.

        **Le seuil ne se teste pas ici.** Il dépend de la largeur réelle du
        texte, et la plateforme « offscreen » des tests n'a aucune police
        installée : toutes les mesures y sont fausses. Mesuré à la main sur
        la vraie plateforme : tous les libellés jusqu'à 1 280 px, seul le
        principal en dessous, et tout revient en s'élargissant. Ce test
        vérifie le mécanisme, qui lui ne dépend d'aucune police.
        """
        from delugeapp.ui.pages.base import _ActionsCompactes

        win = self.window()
        win.go_to("Samples")
        for _ in range(6):
            _APP.processEvents()
        page = win._pages["Samples"]

        ajusteurs = page.findChildren(_ActionsCompactes)
        self.assertTrue(ajusteurs, "aucune barre d'actions adaptative")
        ajusteur = ajusteurs[0]
        boutons = ajusteur._boutons()
        self.assertGreaterEqual(len(boutons), 4)
        # Les vrais libellés sont ceux que l'ajusteur a mémorisés : sans
        # police, la barre peut déjà s'être repliée, et lire le texte
        # affiché rendrait des chaînes vides.
        ajusteur.ajuster()
        libelles = dict(ajusteur._textes)
        self.assertTrue(all(libelles.values()),
                        "l'ajusteur n'a pas mémorisé les libellés")
        principal = [b for b in boutons if b.objectName() == "Primary"]
        self.assertTrue(principal, "la page n'a pas d'action principale")

        # État 1 : seul le principal parle.
        ajusteur._replier(boutons, 1)
        for bouton in boutons:
            if bouton is principal[0]:
                self.assertTrue(bouton.text())
            else:
                self.assertFalse(bouton.text())
                self.assertIn(libelles[id(bouton)], bouton.toolTip(),
                              "l'infobulle ne nomme plus le bouton")

        # État 2 : plus aucun texte, mais toujours nommables.
        ajusteur._replier(boutons, 2)
        for bouton in boutons:
            self.assertFalse(bouton.text())
            self.assertIn(libelles[id(bouton)], bouton.toolTip())

        # État 0 : tout revient, à l'identique.
        ajusteur._replier(boutons, 0)
        for bouton in boutons:
            self.assertEqual(bouton.text(), libelles[id(bouton)])

    def test_ajuster_la_barre_ne_leve_jamais(self):
        """Même sans police, sans largeur, sans boutons."""
        from delugeapp.ui.pages.base import _ActionsCompactes

        win = self.window()
        for cle in list(win._classes):
            win.go_to(cle)
            for _ in range(3):
                _APP.processEvents()
            for ajusteur in win._pages[cle].findChildren(_ActionsCompactes):
                ajusteur.ajuster()
                ajusteur.ajuster()

    def test_le_nom_reste_toujours_visible(self):
        """Une liste sans nom ne sert à rien, quelle que soit la place."""
        win = self.window()
        for largeur, hauteur in self.TAILLES:
            win.resize(largeur, hauteur)
            for _ in range(4):
                _APP.processEvents()
            for cle in self.LISTES:
                win.go_to(cle)
                for _ in range(4):
                    _APP.processEvents()
                table = win._pages[cle]._table
                self.assertFalse(table.isColumnHidden(0),
                                 "%s à %d px" % (cle, largeur))


class TestChaqueCommandeSExplique(MainWindowCase):
    """Aucune commande ne doit laisser l'utilisateur deviner.

    Mesuré avant d'écrire ``ui/aide.py`` : **102 des 174 commandes
    n'expliquaient rien** (59 %), dont « Supprimer les doublons »,
    « Archiver dans _UNUSED », « Relier automatiquement » et « Restaurer » —
    quatre actions qui écrivent sur la carte.

    Ce test garde le résultat : une commande ajoutée sans explication le
    fait échouer, en la nommant.
    """

    def _toutes_les_pages(self):
        from PyQt6.QtWidgets import QTabWidget

        win = self.window()
        for cle in list(win._classes):
            win.go_to(cle)
            for _ in range(4):
                _APP.processEvents()
            page = win._pages[cle]
            # Les onglets cachés comptent : leurs commandes existent.
            for onglets in page.findChildren(QTabWidget):
                for index in range(onglets.count()):
                    onglets.setCurrentIndex(index)
                    _APP.processEvents()
            yield cle, page

    def test_aucune_commande_muette(self):
        from delugeapp.ui import aide

        muettes = {}
        total = 0
        for cle, page in self._toutes_les_pages():
            restantes = aide.manquantes(page, cle)
            total += 1
            if restantes:
                muettes[cle] = restantes
        self.assertEqual(total, 10, "les dix pages n'ont pas été visitées")
        self.assertEqual(
            muettes, {},
            "commandes sans explication : %s"
            % "; ".join("%s : %s" % (k, ", ".join(v))
                        for k, v in muettes.items()))

    def test_les_actions_qui_ecrivent_le_disent(self):
        """Une action destructrice annonce qu'elle écrit.

        C'est la règle de non-destruction appliquée à l'interface : la
        carte contient des mois de travail, et le moment de l'apprendre
        n'est pas après le clic.
        """
        from delugeapp.ui import aide

        attendu = ("Supprimer les doublons", "Relier automatiquement",
                   "Archiver dans _UNUSED", "Restaurer")
        sante = aide.EXPLICATIONS["Health"]
        for libelle in attendu:
            self.assertIn(libelle, sante, libelle)
            texte = sante[libelle]
            self.assertTrue(
                any(mot in texte for mot in
                    ("Écrit sur la carte", "Déplace des fichiers",
                     "Écrase des fichiers")),
                "« %s » n'annonce pas qu'elle touche à la carte : %s"
                % (libelle, texte))

    def test_aucune_explication_ne_designe_un_fantome(self):
        """Une explication pour une commande disparue trompe le lecteur."""
        from delugeapp.ui import aide

        vues: dict[str, set] = {}
        for cle, page in self._toutes_les_pages():
            trouvees = set()
            from PyQt6.QtWidgets import (QAbstractButton, QComboBox,
                                         QDoubleSpinBox, QLineEdit, QSlider,
                                         QSpinBox)
            for classe in (QAbstractButton, QComboBox, QSlider, QSpinBox,
                           QDoubleSpinBox, QLineEdit):
                for widget in page.findChildren(classe):
                    trouvees.update(aide._cles_du_widget(page, widget))
            vues[cle] = trouvees

        fantomes = []
        for cle, table in aide.EXPLICATIONS.items():
            for libelle in table:
                if libelle not in vues.get(cle, set()):
                    fantomes.append("%s / %s" % (cle, libelle))
        self.assertEqual(fantomes, [],
                         "explications sans commande : %s"
                         % ", ".join(fantomes))

    def test_une_explication_n_est_pas_le_libelle(self):
        """Répéter « Écouter » sous le bouton « Écouter » n'apprend rien."""
        from delugeapp.ui import aide

        for cle, table in aide.EXPLICATIONS.items():
            for libelle, texte in table.items():
                self.assertNotEqual(texte.strip().casefold(),
                                    libelle.strip().casefold(),
                                    "%s / %s" % (cle, libelle))
                self.assertGreater(len(texte), 20,
                                   "%s / %s : trop courte" % (cle, libelle))


class TestMenusEtRaccourcis(MainWindowCase):
    """Chaque entrée de menu et chaque raccourci doit s'actionner.

    La fenêtre principale protège ses actions avec ``_safely``, pas avec
    ``Page.guard`` — ce sont deux remparts distincts, et celui-ci n'était
    pas plus exercé que l'autre.
    """

    def setUp(self):
        super().setUp()
        from PyQt6.QtWidgets import QDialog, QFileDialog, QInputDialog

        self._sorties = {
            "save": QFileDialog.getSaveFileName,
            "open": QFileDialog.getOpenFileName,
            "opens": QFileDialog.getOpenFileNames,
            "dir": QFileDialog.getExistingDirectory,
            "text": QInputDialog.getText,
            "int": QInputDialog.getInt,
            "exec": QDialog.exec,
        }
        QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: ("", ""))
        QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: ("", ""))
        QFileDialog.getOpenFileNames = staticmethod(lambda *a, **k: ([], ""))
        QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: "")
        QInputDialog.getText = staticmethod(lambda *a, **k: ("", False))
        QInputDialog.getInt = staticmethod(lambda *a, **k: (0, False))
        QDialog.exec = lambda _self: QDialog.DialogCode.Rejected

    def tearDown(self):
        from PyQt6.QtWidgets import QDialog, QFileDialog, QInputDialog

        s = self._sorties
        QFileDialog.getSaveFileName = s["save"]
        QFileDialog.getOpenFileName = s["open"]
        QFileDialog.getOpenFileNames = s["opens"]
        QFileDialog.getExistingDirectory = s["dir"]
        QInputDialog.getText = s["text"]
        QInputDialog.getInt = s["int"]
        QDialog.exec = s["exec"]
        super().tearDown()

    def test_chaque_entree_de_menu_s_actionne(self):
        from PyQt6.QtWidgets import QMenu

        from delugeapp.ui import tasks

        win = self.window()
        essayees = 0
        for menu in win.menuBar().findChildren(QMenu):
            for action in menu.actions():
                libelle = action.text()
                if action.isSeparator() or not action.isEnabled():
                    continue
                if "Quitter" in libelle:        # fermerait la fenêtre
                    continue
                # Changer de langue ferme la fenêtre pour la rouvrir : son
                # test est dans test_i18n.
                if action in win._language_actions.values():
                    continue
                with self.subTest(menu=libelle):
                    with self.assertNoLogs("delugeapp.ui.mainwindow",
                                           level="ERROR"):
                        action.trigger()
                        _APP.processEvents()
                essayees += 1
        tasks.stop_all(3000)
        self.assertGreaterEqual(essayees, 10,
                                "trop peu d'entrées de menu : %d" % essayees)

    def test_chaque_raccourci_s_actionne(self):
        from delugeapp.ui import tasks

        win = self.window()
        essayes = 0
        for action in win.actions():
            raccourci = action.shortcut().toString()
            if not raccourci:
                continue
            with self.subTest(raccourci=raccourci):
                with self.assertNoLogs("delugeapp.ui.mainwindow",
                                       level="ERROR"):
                    action.trigger()
                    _APP.processEvents()
            essayes += 1
        tasks.stop_all(3000)
        # Ctrl+1..9 pour les pages, plus Espace pour l'écoute.
        self.assertGreaterEqual(essayes, 10,
                                "trop peu de raccourcis : %d" % essayes)

    def test_une_action_de_menu_fautive_reste_absorbee(self):
        """``_safely`` est l'équivalent de ``guard`` pour la fenêtre."""
        win = self.window()

        def boum():
            raise RuntimeError("volontaire")

        with self.assertLogs("delugeapp.ui.mainwindow", level="ERROR"):
            win._safely(boum)
        self.assertIn("Action impossible", win.statusBar().currentMessage())


# --------------------------------------------------------------------------- #
# Aides à la composition et générateurs (13 octobre 2026)
# --------------------------------------------------------------------------- #

def _libelle(bouton) -> str:
    """Le nom d'un bouton, même replié sur son icône.

    Une barre d'actions trop étroite vide le texte de ses boutons et garde
    leur nom dans la propriété ``libelleComplet``. La plateforme
    « offscreen » des tests n'a aucune police : la barre s'y replie dès
    qu'elle est affichée. Lire ``text()`` mesurait donc la largeur d'une
    police absente, pas le nom du bouton.
    """
    return str(bouton.property("libelleComplet") or bouton.text())


def _bouton(page, libelle=None, attribut=None):
    """Le bouton de la page, par son attribut ou son libellé."""
    from PyQt6.QtWidgets import QAbstractButton

    if attribut:
        return getattr(page, attribut)
    # Une barre d'actions trop étroite replie ses boutons en icônes ; le
    # libellé complet reste dans la propriété ``libelleComplet``.
    return next(b for b in page.findChildren(QAbstractButton)
                if libelle in (b.text(), b.property("libelleComplet")))


class TestOutilsDeComposition(PageCase):
    """Chaque test **clique**, comme le fait l'utilisateur."""

    def _page(self):
        from delugeapp.ui.pages.toolbox import ToolboxPage

        return self.open(ToolboxPage)

    def test_appliquer_deux_fois_ne_plante_ni_ne_cumule(self):
        page = self._page()
        page._beat_from_genre()
        index = [page._groove.itemData(i)
                 for i in range(page._groove.count())].index("MPC 62 %")
        page._groove.setCurrentIndex(index)
        bouton = _bouton(page, "Appliquer")
        with self.assertNoLogs("delugeapp.ui", level="ERROR"):
            bouton.click()
            premier = {t: [s.pos for s in st]
                       for t, st in page._pattern.tracks.items()}
            bouton.click()
        second = {t: [s.pos for s in st]
                  for t, st in page._pattern.tracks.items()}
        self.assertEqual(premier, second, "le groove s'est cumulé")

    def test_les_accords_portent_leur_qualite(self):
        page = self._page()
        noms = [page._chords.item(i, 1).text() for i in range(7)]
        self.assertEqual(noms, ["Do", "Rém", "Mim", "Fa", "Sol", "Lam",
                                "Si°"])
        self.assertIn("MAJOR", page._deluge_scale.text())

    def test_une_gamme_courte_garde_ses_notes(self):
        page = self._page()
        index = [page._scale.itemData(i) for i in range(page._scale.count())
                 ].index("pentatonique mineure")
        page._scale.setCurrentIndex(index)
        page._show_scale()
        self.assertEqual(page._mode_notes.text(), "0, 3, 5, 7, 10")
        self.assertIn("PENTATONIC MINOR", page._deluge_scale.text())

    def test_progression_nommee_puis_exportee(self):
        from unittest import mock

        from PyQt6.QtWidgets import QFileDialog

        page = self._page()
        messages = []
        page.status.connect(messages.append)
        _bouton(page, "Proposer").click()
        _APP.processEvents()
        self.assertEqual(page._progression_list.count(),
                         page._progression_bars.value())
        cible = Path(self._tmp.name) / "accomp.mid"
        page._acc_arp.setChecked(True)
        with mock.patch.object(QFileDialog, "getSaveFileName",
                               return_value=(str(cible), "")):
            _bouton(page, attribut="_export_prog_button").click()
        self.assertTrue(cible.is_file())
        self.assertIn("3 pistes", messages[-1])

    def test_ecouter_l_accompagnement(self):
        import time

        from delugeapp.ui import tasks

        page = self._page()
        _bouton(page, "Proposer").click()
        joue = []
        page._play_audio = lambda audio: joue.append(audio)
        _bouton(page, attribut="_listen_prog_button").click()
        for _ in range(400):
            if joue:
                break
            _APP.processEvents()
            time.sleep(0.01)
        tasks.stop_all(2000)
        self.assertTrue(joue, "le rendu n'est jamais revenu")
        self.assertGreater(joue[0].shape[0], 44100)

    def _choisir(self, combo, valeur):
        index = [combo.itemData(i) for i in range(combo.count())].index(valeur)
        combo.setCurrentIndex(index)

    def test_la_couleur_des_accords_choisie_est_jouee(self):
        page = self._page()
        self._choisir(page._prog_color, "septièmes")
        _bouton(page, "Proposer").click()
        self.assertTrue(page._progression)
        for accord in page._progression:
            with self.subTest(accord=accord["name"]):
                self.assertEqual(len(accord["notes"]), 4)
                self.assertIn(accord["quality"], ("m7", "maj7", "7", "m7b5"))

    def test_la_melodie_part_dans_le_fichier_midi(self):
        from unittest import mock

        from PyQt6.QtWidgets import QFileDialog

        page = self._page()
        messages = []
        page.status.connect(messages.append)
        _bouton(page, "Proposer").click()
        page._acc_melody.setChecked(True)
        cible = Path(self._tmp.name) / "melodie.mid"
        with mock.patch.object(QFileDialog, "getSaveFileName",
                               return_value=(str(cible), "")):
            _bouton(page, attribut="_export_prog_button").click()
        self.assertTrue(cible.is_file())
        self.assertIn("mélodie", messages[-1])
        self.assertIn(f"{len(page._parts())} pistes", messages[-1])

    def test_autre_melodie_garde_les_accords(self):
        import time

        from delugeapp.ui import tasks

        page = self._page()
        _bouton(page, "Proposer").click()
        accords = [c["notes"] for c in page._progression]
        page._acc_melody.setChecked(True)
        avant = [e.note for e in page._parts()["Mélodie"]]
        joue = []
        page._play_audio = lambda audio: joue.append(audio)
        page._acc_melody.setChecked(False)
        _bouton(page, attribut="_melody_button").click()
        for _ in range(400):
            if joue:
                break
            _APP.processEvents()
            time.sleep(0.01)
        tasks.stop_all(2000)
        self.assertTrue(joue, "la mélodie n'a pas été jouée")
        self.assertTrue(page._acc_melody.isChecked())
        self.assertEqual([c["notes"] for c in page._progression], accords)
        apres = [e.note for e in page._parts()["Mélodie"]]
        self.assertTrue(apres)
        self.assertNotEqual(avant, apres)

    def test_table_des_synchros(self):
        from delugeapp.ui.pages.toolbox import SYNC_LEVELS

        self.assertIn("double-croche", dict(SYNC_LEVELS)[7])
        self.assertIn("1 mesure", dict(SYNC_LEVELS)[3])

    def test_chaque_genre_a_sa_structure(self):
        from delugeapp.core import genres
        from delugeapp.ui.pages.toolbox import ARRANGEMENTS

        self.assertEqual(set(ARRANGEMENTS), set(genres.GENRES))


class TestFondreDansLeGenerateur(PageCase):
    """``synthgen.morph`` existait sans commande pour s'en servir."""

    def test_fondre_avec_un_son_de_l_historique(self):
        from delugeapp.ui.pages.generator import GeneratorPage

        page = self.open(GeneratorPage)
        _bouton(page, "Générer").click()
        premier = page._preset
        page._seed.setValue(page._seed.value() + 1)
        _bouton(page, "Générer").click()
        self.assertEqual(len(page._history), 2)
        page._history_list.setCurrentRow(1)          # le premier son
        page._morph_amount.setValue(100)
        with self.assertNoLogs("delugeapp.ui", level="ERROR"):
            _bouton(page, "Fondre").click()
        # À 100 %, les formes d'onde sont celles du son choisi.
        self.assertEqual(page._preset.sound.osc1.type,
                         premier.sound.osc1.type)
        self.assertEqual(len(page._history), 3)


class TestOutilsDeCompositionSuite(PageCase):
    """Écouter le rythme, le varier, l'entendre avec l'accompagnement,
    changer un accord, esquisser le morceau. Chaque test clique."""

    def _page(self):
        from delugeapp.ui.pages.toolbox import ToolboxPage

        return self.open(ToolboxPage)

    def _ecoute(self, page, bouton):
        import time

        from delugeapp.ui import tasks

        joue = []
        page._play_audio = lambda audio: joue.append(audio)
        bouton.click()
        for _ in range(500):
            if joue:
                break
            _APP.processEvents()
            time.sleep(0.01)
        tasks.stop_all(2000)
        self.assertTrue(joue, "le rendu n'est jamais revenu")
        return joue[0]

    def _exporte(self, page, bouton, nom):
        from unittest import mock

        from PyQt6.QtWidgets import QFileDialog

        messages = []
        page.status.connect(messages.append)
        cible = Path(self._tmp.name) / nom
        with mock.patch.object(QFileDialog, "getSaveFileName",
                               return_value=(str(cible), "")):
            bouton.click()
        self.assertTrue(cible.is_file(), messages)
        return cible.read_bytes(), messages[-1]

    @staticmethod
    def _choisir(combo, valeur):
        index = [combo.itemData(i) for i in range(combo.count())].index(valeur)
        combo.setCurrentIndex(index)
        combo.activated.emit(index)

    def test_le_rythme_s_ecoute(self):
        page = self._page()
        page._beat_bpm.setValue(120)
        audio = self._ecoute(page, page._listen_beat_button)
        # Deux passages d'une mesure à 120 BPM : quatre secondes au moins.
        self.assertGreaterEqual(audio.shape[0], 4 * 44100)
        self.assertGreater(float(np.abs(audio).max()), 0.1)

    def test_une_variation_garde_l_ossature(self):
        page = self._page()
        _bouton(page, "Motif du genre").click()
        avant = {st.pos for st in page._pattern.tracks["Kick"]}
        page._variation_button.click()
        apres = {st.pos for st in page._pattern.tracks["Kick"]}
        self.assertLessEqual(avant, apres)
        self.assertIn(" — ", page._pattern.name)

    def test_le_tempo_du_rythme_suit_le_genre_jusque_dans_le_fichier(self):
        import struct

        page = self._page()
        self._choisir(page._beat_genre, "dnb")
        bas, haut = genres.genre("dnb").bpm
        self.assertEqual(page._beat_bpm.value(), round((bas + haut) / 2))
        _bouton(page, "Motif du genre").click()
        donnees, _m = self._exporte(page, page._export_beat_button,
                                    "motif.mid")
        i = donnees.index(b"\xff\x51\x03")
        micros = struct.unpack(">I", b"\x00" + donnees[i + 3:i + 6])[0]
        self.assertAlmostEqual(60_000_000 / micros, page._beat_bpm.value(),
                               delta=0.5)

    def test_la_batterie_rejoint_l_accompagnement(self):
        page = self._page()
        _bouton(page, "Proposer").click()
        page._acc_drums.setChecked(True)
        donnees, message = self._exporte(page, page._export_prog_button,
                                         "avec_batterie.mid")
        self.assertIn("batterie", message)
        self.assertIn(0x99, donnees)
        audio = self._ecoute(page, page._listen_prog_button)
        self.assertGreater(audio.shape[0], 44100)

    def test_autre_accord_ne_change_que_l_accord_choisi(self):
        page = self._page()
        _bouton(page, "Proposer").click()
        messages = []
        page.status.connect(messages.append)
        page._progression_list.setCurrentRow(-1)
        page._chord_button.click()
        self.assertIn("Choisissez d'abord un accord", messages[-1])
        avant = [dict(c) for c in page._progression]
        page._progression_list.setCurrentRow(1)
        page._chord_button.click()
        apres = page._progression
        self.assertNotEqual(apres[1]["degree"], avant[1]["degree"])
        self.assertEqual(apres[1]["function"], avant[1]["function"])
        self.assertEqual([c["name"] for i, c in enumerate(apres) if i != 1],
                         [c["name"] for i, c in enumerate(avant) if i != 1])
        self.assertIn(apres[1]["name"], page._progression_list.item(1).text())

    def test_l_arrangement_s_ecoute_et_s_exporte(self):
        page = self._page()
        self._choisir(page._arr_genre, "house")
        parties = page._arrangement.item(0, 4).text()
        self.assertIn("accords", parties)
        self.assertNotIn("basse", parties)            # l'intro
        page._arrangement.selectRow(3)                # le refrain
        audio = self._ecoute(page, page._listen_section_button)
        self.assertGreater(audio.shape[0], 8 * 44100)
        donnees, message = self._exporte(page, page._export_sketch_button,
                                         "esquisse.mid")
        self.assertIn(b"Intro", donnees)
        self.assertIn(b"Refrain 2", donnees)
        self.assertIn("7 sections", message)


class TestAuditDUsageReel(MainWindowCase):
    """Ce que l'audit sur la carte de l'utilisateur a montré (14 octobre)."""

    def _compte_rafraichissements(self, page):
        appels = []
        vrai = page._refresh

        def compte():
            appels.append(1)
            return vrai()

        page._refresh = compte
        return appels

    def test_une_page_ne_se_rafraichit_qu_une_fois_par_visite(self):
        """Elle se rafraîchissait deux fois : par son ``showEvent`` puis par
        ``go_to``. Le tableau de bord payait deux diagnostics de santé."""
        win = self.window()
        win.go_to("Synths")
        _pump(50)
        win.go_to("Dashboard")
        _pump(50)
        tableau = win._pages["Dashboard"]
        appels = self._compte_rafraichissements(tableau)
        win.go_to("Synths")
        win.go_to("Dashboard")
        _pump(50)
        self.assertEqual(len(appels), 1)
        # Déjà affichée, elle se rafraîchit quand même sur demande.
        win.go_to("Dashboard")
        self.assertEqual(len(appels), 2)

    def _reparer_hors_application(self):
        """Le preset cassé est réparé, comme par une autre session."""
        import os

        chemin = self.root / "SYNTHS" / "CASSE.XML"
        preset = SynthPreset.load(chemin)
        preset.sound.osc1.file_name = "SAMPLES/DRUMS/Kick/k.wav"
        preset.save(chemin, backup=False)
        plus_tard = chemin.stat().st_mtime + 10
        os.utime(chemin, (plus_tard, plus_tard))

    def _attendre_l_analyse(self, win):
        import time

        page = win._pages["Dashboard"]
        for _ in range(300):
            _pump(20)
            if page._worker is None:
                break
            time.sleep(0.01)

    def test_l_index_se_met_a_jour_au_demarrage(self):
        self.assertTrue(self.lib.missing_links())
        self._reparer_hors_application()
        messages = []
        win = self.mw.MainWindow(self.ctx)
        win.statusBar().messageChanged.connect(messages.append)
        self.shown(win, 1200, 800)
        _pump(300)
        self._attendre_l_analyse(win)
        self.assertEqual(self.lib.missing_links(), [])
        self.assertTrue(any("Index à jour : 1 fichier" in m
                            for m in messages), messages)

    def test_l_espace_d_un_dossier_n_est_pas_celui_d_une_carte(self):
        """Une copie dans un dossier affichait l'espace du disque entier
        (474,7 Gio) comme celui de la carte."""
        from pathlib import Path as Chemin

        self.assertFalse(self.sd.is_volume)
        self.assertTrue(sdcard.SDCard(Chemin(Chemin.cwd().anchor)).is_volume)
        win = self.window()
        tableau = win._pages["Dashboard"]
        self.assertEqual(tableau._tiles["space"]._label.text(),
                         "Libre sur le disque")
        self.assertIn("Copie dans un dossier", tableau._card_detail.text())
        self.assertIn("sur le disque", win._space.text())

    def test_le_reglage_coupe_la_mise_a_jour(self):
        self._reparer_hors_application()
        self.ctx.settings.index_on_start = False
        win = self.window()
        self._attendre_l_analyse(win)
        self.assertTrue(self.lib.missing_links())


class TestAutreSonDuKit(PageCase):
    """Remplacer un son d'un kit généré sans tout reconstruire."""

    def _page_avec_kit(self):
        from delugeapp.ui.pages.generator import GeneratorPage

        page = self.open(GeneratorPage)
        _bouton(page, "Construire le kit").click()
        self.assertTrue(page._kit.rows)
        return page

    def test_seule_la_rangee_choisie_change(self):
        page = self._page_avec_kit()
        noms = [r.name for r in page._kit.rows]
        self.assertIn("KICK", noms)
        index = noms.index("KICK")
        avant = [r.file_name for r in page._kit.rows]
        page._kit_result.setCurrentRow(index)
        messages = []
        page.status.connect(messages.append)
        with self.assertNoLogs("delugeapp.ui", level="ERROR"):
            _bouton(page, "Autre son").click()
        apres = [r.file_name for r in page._kit.rows]
        self.assertNotEqual(apres[index], avant[index])
        self.assertEqual([f for i, f in enumerate(apres) if i != index],
                         [f for i, f in enumerate(avant) if i != index])
        self.assertIn(apres[index].rsplit("/", 1)[-1],
                      page._kit_result.item(index).text())
        # La carte factice n'a que deux grosses caisses : la suivante est
        # refusée plutôt que de revenir à la première.
        _bouton(page, "Autre son").click()
        self.assertIn("pas d'autre son", messages[-1])
        self.assertEqual(page._kit.rows[index].file_name, apres[index])

    def test_sans_rangee_choisie_on_le_dit(self):
        page = self._page_avec_kit()
        page._kit_result.setCurrentRow(-1)
        messages = []
        page.status.connect(messages.append)
        _bouton(page, "Autre son").click()
        self.assertIn("Choisissez d'abord une rangée", messages[-1])


class TestVarierDansLeGenerateur(MainWindowCase):
    """La page Presets annonçait ce passage ; il n'existait pas."""

    def test_un_preset_de_la_carte_devient_le_point_de_depart(self):
        win = self.window()
        win.go_to("Synths")
        _APP.processEvents()
        synths = win._pages["Synths"]
        synths._table.selectRow(0)
        _APP.processEvents()
        attendu = synths._preset.sound.name
        _bouton(synths, "Varier dans le générateur").click()
        _APP.processEvents()
        generateur = win._pages.get("Generator")
        self.assertIsNotNone(generateur)
        self.assertIs(win._stack.currentWidget(), generateur)
        self.assertEqual(generateur._preset.sound.name, attendu)
        # Muter part bien de lui.
        _bouton(generateur, "Muter").click()
        self.assertEqual(len(generateur._history), 2)


# --------------------------------------------------------------------------- #
# La façade : refonte graphique d'après le guide (14 octobre 2026)
# --------------------------------------------------------------------------- #

class TestLaFacadeTheme(unittest.TestCase):
    """La partie colorée du thème, et les teintes nouvelles."""

    SEUIL = 4.5

    #: Les couleurs de page, et celles que l'utilisateur peut choisir pour la
    #: façade dans les réglages.
    TEINTES = (list(theme.PAGE_COLORS.values())
               + [theme.GOLD, "#28C4E0", "#2FD3A6", "#FFC400", "#F04FA8",
                  "#6B5CE7"])

    def test_la_partie_coloree_se_construit_pour_chaque_teinte(self):
        """Chaque page pose sur elle-même la partie colorée : aucune teinte
        ne doit la casser, et la teinte doit y figurer."""
        for teinte in self.TEINTES:
            with self.subTest(teinte=teinte):
                with self.assertNoLogs("delugeapp.ui.theme", level="ERROR"):
                    feuille = theme.accent_qss(teinte)
                self.assertGreater(len(feuille), 3000)
                self.assertNotIn("${", feuille)
                self.assertIn(teinte.upper(), feuille.upper())

    def test_la_partie_coloree_porte_tous_les_etats(self):
        """Qt fait gagner la feuille d'un parent sur celle de l'application,
        quelle que soit la spécificité : si la page fixait le fond d'un
        bouton sans fixer celui du bouton désactivé, un bouton éteint
        garderait le fond vif de la page."""
        feuille = theme.accent_qss(theme.PAD_CYAN)
        for selecteur in ("QPushButton:disabled", "QPushButton#Primary:disabled",
                          "QPushButton:hover", "QPushButton:pressed",
                          "QPushButton:checked", "QCheckBox::indicator:checked",
                          "QTabBar::tab:selected", "QComboBox:disabled"):
            with self.subTest(selecteur=selecteur):
                self.assertIn(selecteur, feuille)

    def test_un_bouton_allume_se_lit_de_haut_en_bas(self):
        """Mesuré : le bas du bouton violet tombait à 4,43, le haut du
        bouton indigo à 4,42."""
        for teinte in self.TEINTES:
            haut, bas, encre = theme.lit_fill(teinte)
            with self.subTest(teinte=teinte):
                self.assertGreaterEqual(theme.contrast(encre, haut), self.SEUIL)
                self.assertGreaterEqual(theme.contrast(encre, bas), self.SEUIL)

    def test_les_textes_de_la_facade_se_lisent(self):
        paires = {
            "texte secondaire sur la façade": (theme.TEXT_SOFT, theme.CHROME),
            "texte principal sur la façade": (theme.PAD_WHITE, theme.CHROME),
            "étiquette de l'écran": (theme.OLED_DIM, theme.OLED_BG),
            "ligne de l'écran": (theme.OLED_HI, theme.OLED_BG),
        }
        for nom, (texte, fond) in paires.items():
            with self.subTest(paire=nom):
                self.assertGreaterEqual(theme.contrast(texte, fond), self.SEUIL)


class TestLaFacadeDessins(WidgetCase):
    """Le treillis et les pads du guide, tracés au QPainter."""

    def test_le_treillis_est_deterministe(self):
        """Une même graine donne le même dessin : une page garde son visage
        d'un affichage à l'autre."""
        from delugeapp.ui import art

        art.clear_cache()
        premier = art.circuit(320, 80, theme.PAD_CYAN, 7).toImage()
        art.clear_cache()
        second = art.circuit(320, 80, theme.PAD_CYAN, 7).toImage()
        self.assertEqual(premier, second)
        autre = art.circuit(320, 80, theme.PAD_CYAN, 8).toImage()
        self.assertNotEqual(premier, autre)

    def test_le_treillis_est_garde_en_cache(self):
        from delugeapp.ui import art

        art.clear_cache()
        a = art.circuit(200, 60, theme.PAD_GREEN, 3)
        b = art.circuit(200, 60, theme.PAD_GREEN, 3)
        self.assertIs(a, b)
        self.assertEqual(art.cache_size(), 1)

    def test_le_treillis_dessine_quelque_chose(self):
        from delugeapp.ui import art

        image = art.circuit(300, 90, theme.PAD_MAGENTA, 11,
                            fade=(0.0, 0.0)).toImage()
        allumes = sum(1 for y in range(0, image.height(), 3)
                      for x in range(0, image.width(), 3)
                      if image.pixelColor(x, y).alpha() > 0)
        self.assertGreater(allumes, 200)

    def test_la_couleur_de_la_page_domine(self):
        """La règle du guide : huit teintes à parts égales font guirlande."""
        from delugeapp.ui import art

        palette = art.palette_for(theme.PAD_BLUE)
        self.assertEqual(palette.count(theme.PAD_BLUE), 5)
        self.assertGreater(palette.count(theme.PAD_BLUE),
                           len(palette) - palette.count(theme.PAD_BLUE))


class TestLaFacadeWidgets(WidgetCase):
    """Les pièces nouvelles : anneau, jauge, emblème, titres, grilles."""

    def test_l_anneau_lit_la_note_ecrite(self):
        anneau = self.shown(common.ScoreRing(size=80), 80, 80)
        anneau.setText("83")
        self.assertEqual(anneau.score(), 83)
        anneau.setText("—")
        self.assertIsNone(anneau.score())
        anneau.set_color(theme.PAD_GREEN)
        self.assertEqual(anneau.color(), theme.PAD_GREEN)
        anneau.repaint()

    def test_la_jauge_allume_en_proportion(self):
        jauge = self.shown(common.SegmentMeter(segments=20), 300, 12)
        jauge.set_value(0, 100)
        self.assertEqual(jauge.lit(), 0)
        jauge.set_value(1, 1000)
        self.assertEqual(jauge.lit(), 1, "une valeur non nulle se voit")
        jauge.set_value(50, 100)
        self.assertEqual(jauge.lit(), 10)
        jauge.set_value(500, 100)
        self.assertEqual(jauge.lit(), 20)

    def test_l_embleme_ne_joue_que_visible(self):
        """Une page cachée ne doit rien coûter."""
        embleme = common.PadEmblem(theme.PAD_CYAN, "samples")
        self.assertFalse(embleme.is_running())
        self.shown(embleme, 140, 140)
        self.assertTrue(embleme.is_running())
        embleme._tick()
        embleme.hide()
        self.assertFalse(embleme.is_running())

    def test_le_titre_de_section_tient_sur_une_ligne(self):
        titre = self.shown(common.SectionTitle("Essai"), 300, 40)
        self.assertEqual(titre.height(), common.SECTION_HEIGHT)
        titre.set_color(theme.PAD_ORANGE)
        titre.repaint()

    def test_la_grille_passe_sur_deux_colonnes_quand_la_place_manque(self):
        from PyQt6.QtWidgets import QGridLayout

        hote = QWidget()
        grille = QGridLayout(hote)
        tuiles = [QLabel(str(i)) for i in range(6)]
        adaptative = common.GrilleAdaptative(hote, grille, tuiles, 3, 2, 900)
        self.shown(hote, 1000, 200)
        self.assertEqual(adaptative.colonnes(), 3)
        hote.resize(700, 200)
        _APP.processEvents()
        self.assertEqual(adaptative.colonnes(), 2)
        self.assertEqual(grille.getItemPosition(grille.indexOf(tuiles[5])),
                         (2, 1, 1, 1))
        hote.resize(1000, 200)
        _APP.processEvents()
        self.assertEqual(adaptative.colonnes(), 3, "la place revenue, tout revient")

    def test_la_rangee_s_empile_quand_la_place_manque(self):
        from PyQt6.QtWidgets import QHBoxLayout

        hote = QWidget()
        rangee = QHBoxLayout(hote)
        rangee.addWidget(QLabel("santé"))
        rangee.addWidget(QLabel("actions"))
        adaptative = common.RangeeAdaptative(hote, rangee, 880)
        self.shown(hote, 1000, 200)
        self.assertFalse(adaptative.empilee())
        hote.resize(600, 200)
        _APP.processEvents()
        self.assertTrue(adaptative.empilee())

    def test_une_categorie_porte_sa_pastille(self):
        """Comme la couleur d'un clip sur la machine : une pastille devant le
        texte, rien quand la valeur est vide."""
        from PyQt6.QtCore import Qt as _Qt
        from PyQt6.QtGui import QPixmap

        colonnes = [("Nom", lambda r: r["nom"], 120, _Qt.AlignmentFlag.AlignLeft),
                    ("Catégorie", lambda r: r["cat"], 100,
                     _Qt.AlignmentFlag.AlignLeft, None,
                     lambda v: theme.category_color(v) if v else "")]
        modele = common.RowTableModel(colonnes, [{"nom": "a", "cat": "Bass"},
                                                 {"nom": "b", "cat": ""}])
        role = _Qt.ItemDataRole.DecorationRole
        pastille = modele.data(modele.index(0, 1), role)
        self.assertIsInstance(pastille, QPixmap)
        self.assertIsNone(modele.data(modele.index(1, 1), role))
        self.assertIsNone(modele.data(modele.index(0, 0), role),
                          "une colonne sans pastille n'en montre pas")
        self.assertEqual(modele.data(modele.index(0, 1)), "Bass",
                         "le texte reste celui de la catégorie")

    def test_un_halo_s_eteint_avec_son_bouton(self):
        """Un bouton désactivé qui rayonnerait promettrait un clic qu'il
        refuse."""
        from PyQt6.QtWidgets import QPushButton

        bouton = self.shown(QPushButton("Allumé"), 120, 40)
        effet = common.glow(bouton, theme.PAD_MINT)
        self.assertTrue(effet.isEnabled())
        bouton.setEnabled(False)
        self.assertFalse(effet.isEnabled())
        bouton.setEnabled(True)
        self.assertTrue(effet.isEnabled())


class TestLaFacadePages(PageCase):
    """Chaque page porte sa couleur, jusque dans ses contrôles."""

    def _pages(self):
        from delugeapp.ui.pages.generator import GeneratorPage
        from delugeapp.ui.pages.health import HealthPage
        from delugeapp.ui.pages.samples import SamplesPage
        from delugeapp.ui.pages.synths import SynthsPage

        return (SamplesPage, SynthsPage, GeneratorPage, HealthPage)

    def test_chaque_page_pose_sa_couleur(self):
        for cls in self._pages():
            page = self.open(cls)
            with self.subTest(page=cls.__name__):
                self.assertIn(page.color.upper(), page.styleSheet().upper())

    def test_le_bouton_principal_rayonne_de_la_couleur_de_la_page(self):
        from PyQt6.QtWidgets import QGraphicsDropShadowEffect, QPushButton

        for cls in self._pages():
            page = self.open(cls)
            principaux = [b for b in page.findChildren(QPushButton)
                          if b.objectName() == "Primary"]
            with self.subTest(page=cls.__name__):
                self.assertTrue(principaux, "aucun bouton principal")
                for bouton in principaux:
                    effet = bouton.graphicsEffect()
                    self.assertIsInstance(effet, QGraphicsDropShadowEffect)
                    self.assertEqual(effet.color().name().upper(),
                                     page.color.upper())

    def test_les_traces_prennent_la_couleur_de_la_page(self):
        """Une forme d'onde dorée sur la page cyan parlait d'un autre écran."""
        from delugeapp.ui.pages.samples import SamplesPage
        from delugeapp.ui.pages.synths import SynthsPage

        echantillons = self.open(SamplesPage)
        self.assertEqual(echantillons._wave.accent(), echantillons.color)
        presets = self.open(SynthsPage)
        self.assertEqual(presets._env1.accent(), presets.color)
        self.assertEqual(presets._filter.accent(), presets.color)
        self.assertEqual(presets._spectrum.accent(), presets.color)

    def test_l_en_tete_est_une_ouverture_de_partie(self):
        from delugeapp.ui.pages.base import PageHero
        from delugeapp.ui.pages.kits import KitsPage

        page = self.open(KitsPage)
        entetes = page.findChildren(PageHero)
        self.assertEqual(len(entetes), 1)
        entete = entetes[0]
        self.assertEqual(entete.color(), page.color)
        self.assertEqual(entete.heading.text(), "Kits")
        entete.repaint()

    def test_la_barre_d_actions_se_replie_des_le_premier_affichage(self):
        """Mesuré à 980 px : six boutons coupés en plein mot, ajusteur à
        l'état 0. Il ne comptait que les boutons *visibles* ; or la première
        taille arrive avant que la page ait montré ses enfants, et si la
        fenêtre ne change plus de taille, rien ne le réveillait.

        Le test n'appelle pas ``ajuster`` : il vérifie que l'affichage seul
        suffit à le faire tourner, boutons compris."""
        from delugeapp.ui.pages.base import page_header, tool_button

        hote, actions = page_header("Essai", "sous-titre", theme.PAD_CYAN,
                                    "samples")
        for libelle in ("Un", "Deux", "Trois", "Quatre"):
            actions.addWidget(tool_button(libelle, "play"))
        ajusteur = hote._actions_compactes
        self.assertEqual(ajusteur._textes, {})
        self.shown(hote, 500, 80)
        self.assertEqual(sorted(ajusteur._textes.values()),
                         sorted(["Un", "Deux", "Trois", "Quatre"]))

    def test_la_repartition_ne_recouvre_plus_les_dossiers(self):
        """Le libellé élidé avait une politique « ignorée » : la disposition
        lui donnait zéro pixel, et la jauge se dessinait sur le nom."""
        from delugeapp.ui.pages.dashboard import DashboardPage

        page = self.open(DashboardPage)
        page._fill_folders()
        _APP.processEvents()
        jauges = page.findChildren(common.SegmentMeter)
        self.assertTrue(jauges, "aucune jauge de répartition")
        for jauge in jauges:
            rangee = jauge.parentWidget()
            libelle = next(w for w in rangee.findChildren(common.ElidedLabel))
            self.assertGreaterEqual(jauge.geometry().left(),
                                    libelle.geometry().right(),
                                    "la jauge recouvre le nom du dossier")

    def test_la_phrase_de_la_carte_se_replie(self):
        """Sans retour à la ligne, elle imposait 900 px au tableau de bord."""
        from delugeapp.ui.pages.dashboard import DashboardPage

        page = self.open(DashboardPage)
        self.assertTrue(page._card_detail.wordWrap())


class TestLaFacadeFenetre(MainWindowCase):
    """La barre du haut, la colonne de pads et l'écran."""

    def test_les_menus_vivent_dans_la_barre_du_haut(self):
        win = self.window()
        barre = win.menuBar()
        self.assertIs(barre, win._menubar)
        parent = barre.parentWidget()
        self.assertEqual(parent.objectName(), "Header",
                         "la barre de menus n'est pas dans la façade")

    def test_cliquer_un_pad_mene_a_sa_page_et_l_allume(self):
        win = self.window()
        pad = win._buttons["Kits"]
        pad.click()
        _pump(320)
        self.assertIs(win._stack.currentWidget(), win._pages["Kits"])
        self.assertTrue(pad.isChecked())
        self.assertAlmostEqual(pad.light(), 1.0, places=2)
        self.assertAlmostEqual(win._buttons["Dashboard"].light(), 0.0,
                               places=2)
        self.assertEqual(win._accent_strip.color(), theme.page_color("Kits"))

    def test_l_ecran_montre_la_carte(self):
        win = self.window()
        etiquette, ligne, ton = win._card_button.display()
        self.assertEqual(ligne, self.root.name.upper())
        self.assertTrue(etiquette.startswith("CARTE"))
        self.assertEqual(ton, "hi")

    def test_l_ecran_reprend_les_messages(self):
        """Comme la machine : un message passe sur l'écran, puis s'efface."""
        win = self.window()
        win.statusBar().showMessage("Index à jour.", 3000)
        self.assertEqual(win._card_button.message(), "Index à jour.")
        win.statusBar().clearMessage()
        self.assertEqual(win._card_button.message(), "")

    def test_un_long_message_defile(self):
        win = self.window()
        win._card_button.set_preferred_width(160)
        win.statusBar().showMessage("x" * 300)
        self.assertTrue(win._card_button._defilement.isActive())
        win._card_button._defiler()
        self.assertGreater(win._card_button._decalage, 0)

    def test_cliquer_l_ecran_mene_aux_reglages(self):
        win = self.window()
        win._card_button.click()
        _APP.processEvents()
        self.assertIs(win._stack.currentWidget(), win._pages["Settings"])

    def test_sans_carte_l_ecran_invite_a_la_choisir(self):
        win = self.window()
        win.ctx.settings.sd_path = ""
        win.ctx.sd = None
        win._refresh_header()
        etiquette, ligne, ton = win._card_button.display()
        self.assertEqual((etiquette, ton), ("AUCUNE CARTE", "warn"))
        self.assertIn("Aucune carte", win._card_button.text())

    def test_la_barre_du_haut_se_resserre(self):
        """À 980 px, la barre complète demandait 1 100 px.

        Les menus passent avant l'écran et la recherche : avec le menu
        Langue, « Aide » sortait de la barre en français, à 980 px comme à
        1 360 px, sans que rien ne le montre.

        La plateforme des tests n'a aucune police : ses menus mesurent le
        double de la réalité. Le test vérifie donc la règle — les menus
        tiennent, ou l'écran et la recherche ont cédé tout ce qu'ils
        pouvaient. La mesure avec de vraies polices (304 px de menus en
        français, 280 en anglais) a été faite sur la vraie plateforme.
        """
        win = self.window()
        for largeur in (980, 1180, 1360):
            win.resize(largeur, 800)
            _APP.processEvents()
            barre = win.menuBar()
            if barre.width() < barre.sizeHint().width():
                self.assertEqual(
                    (win._card_button.sizeHint().width(),
                     win._search.width()),
                    (self.mw.HEADER_SCREEN_MIN, self.mw.HEADER_SEARCH_MIN),
                    "menus coupés à %d px sans que l'écran et la recherche "
                    "aient tout cédé" % largeur)
        win._fit_header(980)
        self.assertTrue(win._wordmark.is_compact())
        self.assertLessEqual(win._card_button.sizeHint().width(), 196)
        self.assertGreaterEqual(win._card_button.sizeHint().width(),
                                self.mw.HEADER_SCREEN_MIN)
        # Assez large pour tout, même avec les menus démesurés de la
        # plateforme des tests : l'écran retrouve sa pleine largeur.
        win._fit_header(2400)
        self.assertFalse(win._wordmark.is_compact())
        self.assertEqual(win._card_button.sizeHint().width(), 330)

    def test_la_pastille_du_deluge_reste_eteinte_sans_machine(self):
        win = self.window()
        win._refresh_deluge_chip()
        couleur, allumee = win._deluge_chip.state()
        self.assertFalse(allumee)
        self.assertEqual(couleur, theme.GREY)

    def test_cliquer_la_pastille_sans_machine_mene_aux_reglages(self):
        from delugeapp.core import midiport

        if not midiport.available():
            self.skipTest("MIDI indisponible : la pastille est cachée")
        win = self.window()
        win._deluge_chip.click()
        _APP.processEvents()
        self.assertIs(win._stack.currentWidget(), win._pages["Settings"])

    def test_replier_la_colonne_garde_les_pads(self):
        win = self.window()
        win._fold_button.click()
        _APP.processEvents()
        self.assertEqual(win._rail.width(), self.mw.RAIL_NARROW)
        for bouton in win._buttons.values():
            self.assertEqual(bouton.text(), "")
            bouton.repaint()
        win._fold_button.click()
        _APP.processEvents()
        self.assertEqual(win._rail.width(), self.mw.RAIL_WIDE)

    def test_la_touche_lecture_s_eteint_sans_lecteur(self):
        win = self.window()
        win._tick()
        couleur, allumee = win._play_button.state()
        self.assertFalse(allumee)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestMorceauxDepuisLesOutils(PageCase):
    """Chaque outil de création écrit un morceau du Deluge — en **cliquant**,
    sur la carte jetable du test.

    Le nom est donné par ``QInputDialog.getText`` et le plan confirmé par
    ``QMessageBox.question``, tous deux remplacés le temps du clic.
    """

    def _clic(self, bouton, nom="Essai", reponse=None):
        """Clique en répondant ``nom`` puis ``reponse`` aux deux questions."""
        from unittest import mock

        from PyQt6.QtWidgets import QInputDialog, QMessageBox

        reponse = reponse or QMessageBox.StandardButton.Yes
        with mock.patch.object(QInputDialog, "getText",
                               return_value=(nom, bool(nom))) as texte, \
                mock.patch.object(QMessageBox, "question",
                                  return_value=reponse) as question:
            with self.assertNoLogs("delugeapp.ui", level="ERROR"):
                bouton.click()
                _APP.processEvents()
        return texte, question

    def _morceau(self, nom="Essai"):
        chemin = self.root / "SONGS" / f"{nom}.XML"
        self.assertTrue(chemin.is_file(), "aucun morceau écrit")
        return Song.load(chemin), dxml.load(chemin).root

    def _toolbox(self):
        from delugeapp.ui.pages.toolbox import ToolboxPage

        page = self.open(ToolboxPage)
        self.messages = []
        self.ecrits = []
        page.status.connect(self.messages.append)
        page.songWritten.connect(self.ecrits.append)
        return page

    def test_la_progression_part_en_morceau(self):
        page = self._toolbox()
        _bouton(page, "Proposer").click()
        page._acc_drums.setChecked(True)
        self._clic(_bouton(page, attribut="_song_prog_button"))
        song, root = self._morceau()
        self.assertEqual((song.firmware, song.input_tick_magnitude),
                         ("c1.2.1", 2))
        self.assertAlmostEqual(song.tempo_bpm, page._acc_bpm.value(),
                               places=2)
        noms = [c.get("clipName") for c in root.find("sessionClips")]
        self.assertIn("Accords", noms)
        self.assertIn("Basse", noms)
        self.assertIn("Batterie", noms)
        self.assertEqual(self.ecrits, ["SONGS/Essai.XML"])
        self.assertIn("Morceau écrit : SONGS/Essai.XML", self.messages[-1])
        self.assertTrue(self.lib.search_songs("Essai"),
                        "le morceau n'est pas indexé")

    def test_refuser_le_plan_n_ecrit_rien(self):
        from PyQt6.QtWidgets import QMessageBox

        page = self._toolbox()
        _bouton(page, "Proposer").click()
        avant = sorted(p.name for p in (self.root / "SONGS").iterdir())
        _texte, question = self._clic(
            _bouton(page, attribut="_song_prog_button"),
            reponse=QMessageBox.StandardButton.No)
        self.assertTrue(question.called)
        self.assertIn("Nouveau fichier : SONGS/Essai.XML",
                      question.call_args.args[2])
        self.assertEqual(sorted(p.name for p in
                                (self.root / "SONGS").iterdir()), avant)
        self.assertEqual(self.messages[-1], "Rien n'a été écrit.")
        # Annuler le nom n'écrit rien non plus, sans même poser la question.
        _texte, question = self._clic(
            _bouton(page, attribut="_song_prog_button"), nom="")
        self.assertFalse(question.called)
        self.assertEqual(sorted(p.name for p in
                                (self.root / "SONGS").iterdir()), avant)

    def test_sans_confirmation_le_morceau_s_ecrit_directement(self):
        self.ctx.settings.confirm_writes = False
        page = self._toolbox()
        _bouton(page, "Proposer").click()
        _texte, question = self._clic(
            _bouton(page, attribut="_song_prog_button"))
        self.assertFalse(question.called)
        self._morceau()

    def test_un_nom_pris_n_est_jamais_remplace(self):
        page = self._toolbox()
        _bouton(page, "Proposer").click()
        bouton = _bouton(page, attribut="_song_prog_button")
        self._clic(bouton)
        premier = (self.root / "SONGS" / "Essai.XML").read_bytes()
        self._clic(bouton)
        self.assertEqual((self.root / "SONGS" / "Essai.XML").read_bytes(),
                         premier)
        self._morceau("Essai 2")

    def test_le_motif_part_en_morceau(self):
        page = self._toolbox()
        _bouton(page, "Motif du genre").click()
        self._clic(_bouton(page, attribut="_song_beat_button"))
        song, root = self._morceau()
        self.assertEqual(root.find("instruments")[0].tag, "kit")
        self.assertEqual(song.stats()["clips"], 1)
        self.assertGreater(song.stats()["notes"], 0)

    def test_un_motif_vide_est_refuse_avant_toute_question(self):
        page = self._toolbox()
        # La page s'ouvre sur le motif du genre : on le vide d'abord.
        page._pattern = rhythm.Pattern(name="vide")
        page._sequencer.set_pattern(page._pattern)
        _texte, question = self._clic(
            _bouton(page, attribut="_song_beat_button"))
        self.assertFalse(_texte.called)
        self.assertEqual(self.messages[-1], "Créez d'abord un motif.")

    def test_l_esquisse_part_en_morceau_a_sections(self):
        page = self._toolbox()
        self._clic(_bouton(page, attribut="_song_sketch_button"))
        _song, root = self._morceau()
        repetitions = [int(s.get("numRepeats"))
                       for s in root.find("sections")]
        self.assertGreaterEqual(repetitions[0], 1)
        self.assertGreater(sum(1 for r in repetitions if r), 3)
        self.assertTrue(all(i.get("clipInstances")
                            for i in root.find("instruments")))
        haut = list(root.find("sessionClips"))[-1]
        self.assertEqual((haut.get("section"), haut.get("isPlaying")),
                         ("0", "1"))

    def test_le_motif_d_essai_d_un_kit_part_en_morceau(self):
        from delugeapp.ui.pages.kits import KitsPage

        page = self.open(KitsPage)
        page._table.selectRow(0)
        _APP.processEvents()
        self._clic(_bouton(page, "Motif en morceau"))
        _song, root = self._morceau()
        kit = root.find("instruments/kit")
        self.assertEqual((kit.get("presetName"), kit.get("presetFolder")),
                         ("KIT", "KITS"))
        self.assertEqual([s.findtext("name") or s.get("name")
                          for s in kit.find("soundSources")],
                         ["KICK", "SNARE"])

    def test_un_kit_ancien_de_la_carte_est_converti(self):
        """Un kit 2.x sans version borne ses échantillons en millisecondes ;
        la machine ignore ces bornes dans un morceau c1.2.1. La page doit
        passer la carte pour qu'elles deviennent des trames."""
        from delugeapp.ui.pages.kits import KitsPage

        (self.root / "KITS" / "VIEUX.XML").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>' '<kit>'
            '<lpfMode>24dB</lpfMode><modFXType>none</modFXType>'
            '<defaultParams><volume>0x3504F334</volume></defaultParams>'
            '<soundSources><sound><name>KICK</name><osc1><type>sample</type>'
            '<fileName>SAMPLES/DRUMS/Kick/k.wav</fileName><zone>'
            '<startMilliseconds>10</startMilliseconds>'
            '<endMilliseconds>300</endMilliseconds></zone></osc1>'
            '<osc2><type>sample</type><fileName></fileName></osc2>'
            '<polyphonic>0</polyphonic><mode>subtractive</mode>'
            '<defaultParams><volume>0x3851EB64</volume></defaultParams>'
            '</sound></soundSources></kit>', encoding="utf-8")
        scan.scan_card(self.sd, self.lib, compute_hash=False)
        page = self.open(KitsPage)
        modele = page._table.model()
        ligne = next(r for r in range(modele.rowCount())
                     if modele.index(r, 0).data() == "VIEUX")
        page._table.selectRow(ligne)
        _APP.processEvents()
        self.assertEqual(page._current, "KITS/VIEUX.XML")
        self._clic(_bouton(page, "Motif en morceau"))
        _song, root = self._morceau()
        zone = root.find("instruments/kit/soundSources/sound/osc1/zone")
        # k.wav : 13 230 trames à 44,1 kHz.
        self.assertEqual((zone.get("startSamplePos"),
                          zone.get("endSamplePos")), ("441", "13230"))
        self.assertIsNone(zone.find("startMilliseconds"))

    def test_le_generateur_essaie_son_son_en_morceau(self):
        from delugeapp.ui.pages.generator import GeneratorPage

        page = self.open(GeneratorPage)
        _bouton(page, "Générer").click()
        self._clic(_bouton(page, "Essayer en morceau"))
        song, root = self._morceau()
        self.assertEqual(root.find("instruments")[0].get("presetName"),
                         page._preset.sound.name)
        self.assertGreaterEqual(song.stats()["clips"], 1)

    def test_le_kit_construit_part_en_morceau(self):
        from delugeapp.ui.pages.generator import GeneratorPage

        page = self.open(GeneratorPage)
        _bouton(page, "Construire le kit").click()
        self.assertTrue(page._kit.rows)
        self._clic(_bouton(page, "Kit en morceau"))
        _song, root = self._morceau()
        self.assertEqual(root.find("instruments")[0].tag, "kit")


class TestBoucleDecoupeeEnMorceau(SliceUICase):
    """Le découpeur écrit aussi un morceau qui rejoue la boucle."""

    def test_la_boucle_decoupee_part_en_morceau(self):
        from unittest import mock

        from PyQt6.QtWidgets import QInputDialog

        dlg = self.dialog()
        self.assertTrue(dlg._song.isEnabled())
        with mock.patch.object(QInputDialog, "getText",
                               return_value=("Boucle", True)):
            dlg._song.click()
            _APP.processEvents()
        self.assertEqual(dlg.written_song, "SONGS/Boucle.XML")
        song = Song.load(self.root / "SONGS" / "Boucle.XML")
        notes = song.clips[0].note_count
        self.assertEqual(notes, len(dlg.sliceset.slices))
        self.assertIn("Morceau écrit", dlg._summary.text())


# --------------------------------------------------------------------------- #
# « Deluge en direct »
# --------------------------------------------------------------------------- #

def _deluge_simule():
    """Le module ``tests/deluge_simule.py``, quelle que soit la façon dont la
    suite est lancée (``discover -s tests`` ou ``tests.test_ui``)."""
    import sys

    dossier = str(Path(__file__).resolve().parent)
    if dossier not in sys.path:
        sys.path.insert(0, dossier)
    import deluge_simule

    return deluge_simule


class TestDelugeEnDirect(MainWindowCase):
    """La fenêtre « Deluge en direct », et ce qui y mène, face au Deluge
    simulé (``tests/deluge_simule.py``) — qui répond comme la vraie machine,
    mesurée le 15 octobre 2026.

    Les ports du système sont remplacés, le temps du test, par ceux de la
    machine simulée ; ``mock.patch`` rend ensuite les remparts de la suite.
    Aucun vrai port n'est ouvert.
    """

    def setUp(self):
        super().setUp()
        from unittest import mock

        from delugeapp.core import midiport

        self.machine = _deluge_simule().DelugeSimule()
        for nom, valeur in (("outputs", lambda: self.machine.devices("out")),
                            ("inputs", lambda: self.machine.devices("in")),
                            ("available", lambda: True)):
            remplacement = mock.patch.object(midiport, nom, valeur)
            remplacement.start()
            self.addCleanup(remplacement.stop)
        self.lien = self.ctx.ensure_link()
        self.machine.brancher(self.lien)
        self.addCleanup(self.lien.disconnect)

    # -- outils ------------------------------------------------------------- #

    def _fenetre(self):
        from delugeapp.ui.livewindow import DelugeLiveWindow

        return self.shown(DelugeLiveWindow(self.ctx, drive=True), 980, 660)

    def _clic(self, bouton):
        self.assertTrue(bouton.isEnabled(), _libelle(bouton))
        bouton.click()
        _APP.processEvents()

    def _connectee(self):
        """La fenêtre, connectée par son bouton, l'écran déjà arrivé."""
        fenetre = self._fenetre()
        self._clic(fenetre.connect_button)
        self.assertTrue(self.lien.is_connected)
        fenetre.refresh()
        return fenetre

    @staticmethod
    def _allume(fenetre, x: int, y: int) -> bool:
        from PyQt6.QtGui import QColor

        return (fenetre.screen_view._image.pixelColor(x, y)
                == QColor(theme.OLED_HI))

    # -- la fenêtre seule ---------------------------------------------------- #

    def test_sans_machine_tout_dort_et_la_fenetre_le_dit(self):
        fenetre = self._fenetre()
        self.assertFalse(self.lien.is_connected)
        self.assertEqual(fenetre.connect_button.text(), "Connecter")
        for bouton in (fenetre.mirror_button, fenetre.hello_button,
                       fenetre.check_button, fenetre.panic_button):
            self.assertFalse(bouton.isEnabled(), _libelle(bouton))
        self.assertTrue(fenetre.screen_view.is_empty())
        # Branché mais pas connecté : la liste dit ce que dit l'en-tête.
        self.assertIn("Deluge détecté", fenetre._etat.text())
        self.assertIn("Deluge détecté", fenetre.checklist_label.text())
        self.assertEqual(self.machine.demandes, [])

    def test_debranche_la_liste_demande_de_brancher(self):
        from delugeapp.core.delugelink import LinkState
        from delugeapp.ui.livewindow import checklist

        absent = LinkState(supported=True, ports_out=["Microsoft GS "
                                                      "Wavetable Synth"])
        self.assertEqual(checklist(absent, 1), [
            (False, "USB : branchez le Deluge, puis « Connecter ».")])

    def test_la_liste_lit_les_reglages_ecrits_par_la_machine(self):
        """En 1.3, le Deluge écrit ses réglages MIDI Follow sur sa carte :
        la liste les constate au lieu de les supposer."""
        from delugeapp.core.delugelink import LinkState
        from delugeapp.core.midifollow import FollowSettings
        from delugeapp.ui.livewindow import checklist

        etat = LinkState(supported=True, out_name="Deluge", in_name="Deluge",
                         firmware="c1.3.0", files=True)

        def phrases(follow, canal=1):
            return [(fait, p) for fait, p in checklist(etat, canal, follow)]

        accorde = phrases(FollowSettings(channel_a=1, feedback="a"))
        self.assertIn((True, "Carte ouverte par USB : la copie de travail se "
                       "tient à son image."), accorde)
        self.assertTrue(any(fait and "Channel A = 1 (lu sur sa carte)" in p
                            for fait, p in accorde))
        self.assertFalse(any("Feedback" in p for _, p in accorde))
        ecart = phrases(FollowSettings(channel_a=3, feedback="a"), canal=1)
        self.assertTrue(any(not fait and "suit le canal 3" in p
                            for fait, p in ecart))
        eteint = phrases(FollowSettings())
        self.assertTrue(any(not fait and "MIDI Follow est éteint" in p
                            for fait, p in eteint))
        sans_retour = phrases(FollowSettings(channel_a=1))
        # L'intitulé du firmware (``gui/ui/menus.cpp``) : le retour se règle
        # dans MIDI-Follow ▸ Feedback ▸ Channel.
        self.assertTrue(any(not fait and "Feedback ▸ Channel = A" in p
                            for fait, p in sans_retour))

    def test_connecter_ouvre_les_bons_ports_et_recopie_l_ecran(self):
        from delugeapp.core import delugesysex as sx

        self.machine.ecran[0] = 0xFF            # colonne 0, lignes 0 à 7
        fenetre = self._connectee()
        self.assertEqual(fenetre.connect_button.text(), "Déconnecter")
        # Ouvrir la fenêtre, c'est vouloir voir l'écran.
        self.assertTrue(fenetre.mirror_button.isChecked())
        self.assertTrue(self.lien.screen_on)
        self.assertFalse(fenetre.screen_view.is_empty())
        self.assertTrue(self._allume(fenetre, 0, 0))
        self.assertTrue(self._allume(fenetre, 0, 7))
        self.assertFalse(self._allume(fenetre, 0, 8))
        self.assertFalse(self._allume(fenetre, 1, 0))
        # Rien par le premier câble ; les SysEx par le troisième.
        self.assertEqual(self.machine.sorties[1].envoyes, [])
        self.assertIn(sx.display_request(sx.DISPLAY_STREAM_FORCE),
                      [e[1] for e in self.machine.sorties[3].envoyes])
        self.assertIn("Firmware c1.2.1", fenetre.checklist_label.text())
        self.assertIn("Deluge c1.2.1", fenetre._etat.text())

    def test_l_ecran_suit_la_machine_puis_la_recopie_s_arrete(self):
        fenetre = self._connectee()
        self.machine.dessine(3, bytes([0x0F] * 8))   # x 24 à 31, lignes 0 à 3
        fenetre.refresh()
        self.assertTrue(self._allume(fenetre, 24, 3))
        self.assertFalse(self._allume(fenetre, 24, 4))
        self._clic(fenetre.mirror_button)
        self.assertFalse(fenetre.mirror_button.isChecked())
        self.assertFalse(self.lien.screen_on)
        self.assertTrue(fenetre.screen_view.is_empty())
        # Les rafraîchissements suivants ne remettent pas une image figée.
        self.machine.dessine(5, bytes([0xFF] * 8))
        fenetre.refresh()
        fenetre.refresh()
        self.assertTrue(fenetre.screen_view.is_empty())

    def test_debranchee_puis_rebranchee_la_recopie_reprend(self):
        fenetre = self._connectee()
        self.assertTrue(self.lien.screen_on)
        self.lien.disconnect()          # ce que fait la fenêtre principale
        fenetre.refresh()
        self.assertFalse(fenetre.mirror_button.isChecked())
        self.assertTrue(fenetre.screen_view.is_empty())
        self.machine.ecran[0] = 0x01
        self.assertTrue(self.lien.connect())    # reconnexion automatique
        fenetre.refresh()
        self.assertTrue(fenetre.mirror_button.isChecked())
        self.assertTrue(self.lien.screen_on)
        fenetre.refresh()
        self.assertTrue(self._allume(fenetre, 0, 0))

    def test_faire_signe_verifier_et_tout_eteindre(self):
        from delugeapp.core import delugesysex as sx

        fenetre = self._connectee()
        self._clic(fenetre.hello_button)
        self.assertEqual(self.machine.demandes[-1], sx.popup())
        self._clic(fenetre.check_button)
        self.assertEqual(self.machine.demandes[-2], sx.identity_request())
        self.assertEqual(self.machine.demandes[-1][:6],
                         bytes((0xF0,)) + sx.DELUGE_ID + bytes((sx.CMD_PING,)))
        fenetre.refresh()
        # Le simulateur répond tout de suite : sous les dix
        # millisecondes, une décimale (« 0 ms » mentirait).
        self.assertRegex(fenetre.checklist_label.text(),
                         r"aller-retour \d,\d ms")
        self._clic(fenetre.panic_button)
        self.assertIn(("panic",), self.machine.sorties[1].envoyes)

    def test_tempo_lecture_notes_et_accord_de_la_machine(self):
        from delugeapp.core import midiport

        fenetre = self._connectee()
        self.machine.court(midiport.START)
        self.machine.horloge(124.0)
        for note in (60, 64, 67):
            self.machine.court(0x90, note, 100)
        fenetre.refresh()
        self.assertAlmostEqual(self.lien.tempo, 124.0, delta=0.3)
        self.assertEqual(fenetre.tempo_label.text(),
                         "%s BPM" % ("%.1f" % self.lien.tempo).replace(".", ","))
        self.assertIn("En lecture", fenetre.transport_label.text())
        self.assertEqual(fenetre.notes_label.text(), "  ".join(
            theory.note_to_name(n) for n in (60, 64, 67)))
        accord = theory.name_chord([60, 64, 67])
        self.assertTrue(accord)
        self.assertEqual(fenetre.chord_label.text(), accord)
        self.assertIn("Horloge reçue", fenetre.checklist_label.text())
        self.machine.court(0x80, 64, 0)
        self.machine.court(midiport.STOP)
        fenetre.refresh()
        self.assertIn("À l'arrêt", fenetre.transport_label.text())
        self.assertEqual(fenetre.notes_label.text(), "  ".join(
            theory.note_to_name(n) for n in (60, 67)))

    def test_sans_note_la_fenetre_dit_qui_en_envoie(self):
        """Le 22 octobre 2026, vingt minutes d'écoute de la machine — lecture
        lancée, instruments changés, boutons tournés — et aucune note reçue :
        le code du firmware ne fait sortir que celles des pistes MIDI.
        « Aucune note tenue » laissait croire à une panne."""
        fenetre = self._connectee()
        fenetre.refresh()
        self.assertIn("Aucune note reçue", fenetre.notes_label.text())
        self.assertIn("pistes MIDI", fenetre.notes_label.text())
        self.assertEqual(fenetre.chord_label.text(), "")

    def test_le_son_selectionne_arrive_par_le_retour_midi_follow(self):
        from delugeapp.core import midifollow

        fenetre = self._connectee()
        self.assertTrue(fenetre.params_hint.isVisible())
        cle = next(c for c in midifollow.PARAM_LABELS
                   if c in self.lien.follow_map)
        cc = self.lien.follow_map[cle]
        canal = self.lien.channel
        self.machine.court(0xB0 | (canal - 1), cc, 100)
        self.machine.court(0xB0 | (canal % 16), cc, 10)   # un autre canal
        fenetre.refresh()
        self.assertEqual(fenetre.params_table.rowCount(), 1)
        self.assertEqual(fenetre.params_table.item(0, 0).text(),
                         midifollow.label_of(cle))
        self.assertEqual(fenetre.params_table.item(0, 1).text(),
                         str(self.lien.machine_values()[cle]))
        self.assertFalse(fenetre.params_hint.isVisible())
        self.assertIn("1 réglage reçu", fenetre.checklist_label.text())

    def test_le_tempo_et_l_accord_se_lisent_de_loin(self):
        """Posée par ``setFont``, la taille était écrasée par la feuille de
        style de l'application : le tempo sortait en 10 points."""
        fenetre = self._connectee()
        for label, minimum in ((fenetre.tempo_label, 24.0),
                               (fenetre.chord_label, 16.0)):
            label.ensurePolished()
            self.assertGreaterEqual(label.font().pointSizeF(), minimum)
            self.assertTrue(label.font().bold())

    def test_fermer_la_fenetre_arrete_la_recopie(self):
        fenetre = self._connectee()
        self.assertTrue(self.lien.screen_on)
        fenetre.close()
        _APP.processEvents()
        self.assertFalse(self.lien.screen_on)
        self.assertFalse(fenetre.mirror_button.isChecked())

    def test_chaque_commande_de_la_fenetre_s_explique(self):
        from delugeapp.ui import aide

        fenetre = self._connectee()
        self.assertEqual(aide.manquantes(fenetre, "Live"), [])

    # -- ce qui y mène, depuis la fenêtre principale ------------------------- #

    def _principale_connectee(self):
        win = self.window()
        if not self.lien.is_connected:
            self.assertTrue(self.lien.connect())
        win._service_link()
        return win

    def test_la_pastille_et_le_menu_ouvrent_la_fenetre(self):
        from PyQt6.QtGui import QAction

        win = self._principale_connectee()
        win._refresh_deluge_chip()
        self.assertIn("firmware c1.2.1", win._deluge_chip.toolTip())
        self.assertIn("en direct", win._deluge_chip.toolTip())
        win._deluge_chip.click()
        _APP.processEvents()
        self.assertIsNotNone(win._live_window)
        self.assertTrue(win._live_window.isVisible())
        win._live_window.close()
        _APP.processEvents()
        action = next(a for a in win.findChildren(QAction)
                      if a.text().replace("&", "") == "Deluge en direct")
        self.assertEqual(action.shortcut().toString(), "Ctrl+D")
        action.trigger()
        _APP.processEvents()
        self.assertTrue(win._live_window.isVisible())

    def test_reglages_midi_mene_a_la_page_reglages(self):
        win = self._principale_connectee()
        win.open_live_window()
        _APP.processEvents()
        self._clic(win._live_window.settings_button)
        self.assertIs(win._stack.currentWidget(), win._pages.get("Settings"))

    def test_les_reglages_disent_d_ou_vient_la_table_midi_follow(self):
        """La carte des tests n'a pas de MIDIFollow.XML : la table est celle
        d'usine, et la page ne doit pas dire l'avoir lue sur la carte."""
        win = self._principale_connectee()
        win.go_to("Settings")
        _APP.processEvents()
        page = win._pages["Settings"]
        page.refresh()
        texte = page._midi_follow.text()
        self.assertIn("d'usine", texte)
        self.assertNotIn("lue dans", texte)
        (self.root / "MIDIFollow.XML").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<defaults><defaultCCMappings>"
            "<lpfFrequency>99</lpfFrequency>"
            "</defaultCCMappings></defaults>", encoding="utf-8")
        self.lien.load_follow_map(self.sd)
        page.refresh()
        self.assertIn("1 paramètre pilotable — table lue dans MIDIFollow.XML",
                      page._midi_follow.text())

    def test_les_reglages_ouvrent_la_fenetre_et_retiennent_le_suivi(self):
        import json

        win = self.window()
        win.go_to("Settings")
        _APP.processEvents()
        page = win._pages["Settings"]
        self._clic(page._midi_live)
        self.assertIsNotNone(win._live_window)
        self.assertTrue(win._live_window.isVisible())
        avant = bool(self.ctx.settings.midi_follow_tempo)
        self._clic(page._midi_follow_tempo)
        self.assertEqual(self.ctx.settings.midi_follow_tempo, not avant)
        enregistre = json.loads(self._config_mod.SETTINGS_PATH.read_text(
            encoding="utf-8"))
        self.assertEqual(enregistre["midi_follow_tempo"], not avant)

    def test_le_tempo_de_la_machine_passe_aux_outils(self):
        from delugeapp.core import midiport

        win = self._principale_connectee()
        self.assertIsNone(win._pages.get("Toolbox"))
        # La machine joue avant que la boîte à outils soit ouverte : elle
        # prend le tempo à sa première visite. 111 BPM : aucun genre ne le
        # donne par défaut (132, d'abord choisi, est celui de l'acid).
        self.machine.court(midiport.START)
        self.machine.horloge(111.0)
        win._service_link()
        self.assertAlmostEqual(self.lien.tempo, 111.0, delta=0.3)
        win.go_to("Toolbox")
        _APP.processEvents()
        boite = win._pages["Toolbox"]
        self.assertEqual(boite._acc_bpm.value(), 111)
        # Puis elle le suit…
        self.machine.horloge(96.0)
        win._service_link()
        self.assertEqual(boite._acc_bpm.value(), 96)
        self.assertEqual(boite._beat_bpm.value(), 96)
        # … tant que le réglage le demande.
        self.ctx.settings.midi_follow_tempo = False
        self.machine.horloge(150.0)
        win._service_link()
        self.assertEqual(boite._acc_bpm.value(), 96)


class CarteUsbCase(MainWindowCase):
    """Base des tests de la carte restée dans le Deluge : le Deluge simulé
    en firmware 1.3, qui sert ses fichiers comme ``storage/smsysex.cpp``,
    une carte, et la sauvegarde de l'utilisateur — jamais écrite."""

    def setUp(self):
        super().setUp()
        import time as _time
        from unittest import mock

        from delugeapp.core import midiport
        from delugeapp.core.delugefiles import from_fat

        self._time = _time
        base = Path(self._tmp.name)
        self.carte = base / "carte_deluge"
        self.sauvegarde = base / "SDCARD Deluge"
        for rel, donnees, decale in (("SONGS/A.XML", b"<song a/>", True),
                                     ("SYNTHS/P.XML", b"<sound p/>", True),
                                     ("SAMPLES/K.WAV", bytes(range(256)) * 8,
                                      True),
                                     ("SONGS/NEUF.XML", b"<song neuf/>",
                                      False)):
            p = self.carte / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(donnees)
            if decale:
                os.utime(p, (1_700_000_000, 1_700_000_000))
                q = self.sauvegarde / rel
                q.parent.mkdir(parents=True, exist_ok=True)
                q.write_bytes(donnees)
                os.utime(q, (1_700_000_000 - 7200, 1_700_000_000 - 7200))
            else:
                nul = from_fat(0x21, 0)          # enregistré par le Deluge
                os.utime(p, (nul, nul))
        self.empreinte_sauvegarde = self._empreinte(self.sauvegarde)

        reglages = self.ctx.settings
        reglages.work_dir = str(base / "copie de travail")
        reglages.card_backup = str(self.sauvegarde)
        reglages.midi_autoconnect = False
        self.machine = _deluge_simule().DelugeSimule(version=(1, 3, 0),
                                                     carte=self.carte)
        for nom, valeur in (("outputs", lambda: self.machine.devices("out")),
                            ("inputs", lambda: self.machine.devices("in")),
                            ("available", lambda: True)):
            remplacement = mock.patch.object(midiport, nom, valeur)
            remplacement.start()
            self.addCleanup(remplacement.stop)
        self.lien = self.ctx.ensure_link()
        self.machine.brancher(self.lien)
        self.addCleanup(self.lien.disconnect)
        self.assertTrue(self.lien.connect())
        self.assertTrue(self.lien.wait_files(5.0))

    def tearDown(self):
        self.assertEqual(self._empreinte(self.sauvegarde),
                         self.empreinte_sauvegarde,
                         "la sauvegarde a changé")
        super().tearDown()

    @staticmethod
    def _empreinte(racine):
        h = hashlib.sha256()
        for p in sorted(Path(racine).rglob("*")):
            if p.is_file():
                st = p.stat()
                h.update(str((p.relative_to(racine).as_posix(), st.st_size,
                              st.st_mtime_ns)).encode())
        return h.hexdigest()

    def _attendre(self, condition, delai=20.0):
        from delugeapp.ui import tasks

        fin = self._time.monotonic() + delai
        while self._time.monotonic() < fin:
            _APP.processEvents()
            # La condition n'est lue qu'une fois les fils arrêtés : sous
            # Windows, lire un fichier qu'un fil est en train de remplacer
            # est refusé — c'était mon test qui échouait, pas la copie.
            if tasks.active_count() == 0:
                try:
                    if condition():
                        return True
                except OSError:
                    pass
            self._time.sleep(0.01)
        return False

    def _avec_copie(self):
        """La fenêtre, la copie de travail créée depuis les Réglages."""
        win = self.window()
        travail = win.card_work
        win._service_link()
        win.go_to("Settings")
        page = win._pages["Settings"]
        page._refresh_work()
        self.assertEqual(page._work_button.text(), "Créer la copie de travail")
        self.assertTrue(page._work_button.isEnabled())
        page._work_button.click()
        self.assertTrue(self._attendre(travail.has_work_copy),
                        travail.message)
        self.assertTrue(self._attendre(lambda: not travail.busy))
        return win, travail, page


class TestCopieDeTravail(CarteUsbCase):
    """La carte reste dans le Deluge : copie de travail et synchronisation,
    depuis l'interface."""

    # -- créer ----------------------------------------------------------------- #

    def test_creer_la_copie_de_travail_depuis_les_reglages(self):
        win, travail, page = self._avec_copie()
        copie = Path(self.ctx.settings.work_dir)
        for rel in ("SONGS/A.XML", "SYNTHS/P.XML", "SAMPLES/K.WAV",
                    "SONGS/NEUF.XML"):
            self.assertEqual((copie / rel).read_bytes(),
                             (self.carte / rel).read_bytes(), rel)
        # La copie de travail est désormais la carte de l'application.
        self.assertEqual(self.ctx.settings.card_role(self.ctx.sd.root),
                         "travail")
        self.assertFalse(self.ctx.sd.read_only)
        page._refresh_work()
        self.assertEqual(page._work_button.text(), "Synchroniser maintenant")
        self.assertIn("CARTE DU DELUGE", win._card_button.toolTip().upper())
        # Seule la date du fichier enregistré par le Deluge a changé sur la
        # carte : ce qui permettra de voir sa prochaine réécriture.
        lectures = {n for n, _ in self.machine.carte_usb.commandes}
        self.assertFalse(lectures & {"write", "delete", "rename", "move",
                                     "copy"}, lectures)

    def test_la_musique_de_la_sauvegarde_seule_est_proposee(self):
        """Mesuré chez l'utilisateur : un kit créé par l'application dans la
        sauvegarde, le 15 octobre, n'était jamais arrivé sur la carte."""
        for rel, donnees in (("KITS/COMPAGNON 1.XML", b"<kit compagnon/>"),
                             ("README.txt", b"ancien")):
            p = self.sauvegarde / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(donnees)
        self.empreinte_sauvegarde = self._empreinte(self.sauvegarde)
        win, travail, _page = self._avec_copie()
        self.assertTrue(self._attendre(
            lambda: (self.carte / "KITS/COMPAGNON 1.XML").exists()
            and not travail.busy))
        self.assertEqual((self.carte / "KITS/COMPAGNON 1.XML").read_bytes(),
                         b"<kit compagnon/>")
        self.assertFalse((self.carte / "README.txt").exists())

    # -- ensuite ---------------------------------------------------------------- #

    def test_ce_que_l_application_ecrit_part_sur_la_carte(self):
        win, travail, _page = self._avec_copie()
        travail._timer.setInterval(10)
        nouveau = Path(self.ctx.settings.work_dir) / "SONGS" / "CREE.XML"
        nouveau.write_bytes(b"<song cree/>")
        win._card_written()
        self.assertTrue(self._attendre(
            lambda: (self.carte / "SONGS/CREE.XML").exists()))
        self.assertEqual((self.carte / "SONGS/CREE.XML").read_bytes(),
                         b"<song cree/>")
        self.assertIn("envoyé", travail.message)

    def test_ce_que_le_deluge_enregistre_revient(self):
        from delugeapp.core.delugefiles import from_fat

        win, travail, _page = self._avec_copie()
        p = self.carte / "SONGS" / "A.XML"
        p.write_bytes(b"<song A/>")               # réenregistré sur la machine
        nul = from_fat(0x21, 0)
        os.utime(p, (nul, nul))
        win.sync_deluge()
        self.assertTrue(self._attendre(
            lambda: (Path(self.ctx.settings.work_dir) / "SONGS/A.XML")
            .read_bytes() == b"<song A/>"))

    def test_pendant_la_lecture_la_synchronisation_attend(self):
        win, travail, _page = self._avec_copie()
        self.lien.running = True
        self.assertFalse(travail.sync("essai"))
        self.assertIn("joue", travail.message)
        self.lien.running = False
        travail.on_transport()
        self.assertTrue(self._attendre(lambda: not travail.busy))
        self.assertIn("Deluge", travail.message)

    def test_une_suppression_attend_l_accord(self):
        win, travail, page = self._avec_copie()
        (Path(self.ctx.settings.work_dir) / "SONGS" / "A.XML").unlink()
        win.sync_deluge()
        self.assertTrue(self._attendre(lambda: not travail.busy
                                       and travail.last_plan is not None
                                       and travail.pending_deletions()))
        self.assertTrue((self.carte / "SONGS/A.XML").exists())
        page._refresh_work()
        self.assertFalse(page._work_deletions.isHidden())
        page._work_deletions.click()             # la question répond « oui »
        self.assertTrue(self._attendre(
            lambda: not (self.carte / "SONGS/A.XML").exists()))

    def test_la_sauvegarde_ouverte_refuse_d_ecrire(self):
        from PyQt6.QtWidgets import QMessageBox

        vus = []
        QMessageBox.information = staticmethod(
            lambda *a, **k: vus.append(a[1] if len(a) > 1 else ""))
        self.ctx.sd = self.ctx.settings.open_card(self.sauvegarde)
        self.assertTrue(self.ctx.sd.read_only)
        self.assertIsNone(self.ctx.sd_or_warn(None, write=True))
        self.assertEqual(vus, ["Rien n'est écrit ici"])
        self.assertIs(self.ctx.sd_or_warn(None), self.ctx.sd)

    def test_chaque_commande_de_la_section_s_explique(self):
        from delugeapp.ui import aide

        win = self.window()
        win.go_to("Settings")
        page = win._pages["Settings"]
        for bouton in (page._work_button, page._work_deletions,
                       page._backup_choose, page._backup_update,
                       page._auto_sync):
            self.assertTrue(bouton.toolTip(), _libelle(bouton))
        self.assertEqual(aide.manquantes(page, "Settings"), [])


# --------------------------------------------------------------------------- #
# Le PC et le Deluge, dans les deux sens (18 octobre 2026)
# --------------------------------------------------------------------------- #

def _son_court(chemin, frequence=220.0):
    """Un son court, écrit par l'écrivain de l'application."""
    t = np.linspace(0, 0.05, 2205, endpoint=False)
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    wav.write(chemin, (0.5 * np.sin(2 * np.pi * frequence * t))
              .astype(np.float32), 44100, 16)
    return chemin


def _pack_tj(racine):
    """Un pack à l'image de « TJontheRoad Delugetions », téléchargé chez
    l'utilisateur : ses presets sous ``TJ SYNTHS/SYNTHS``, ses sons sous
    ``TJ SAMPLES``, et les parasites de macOS venus de l'archive."""
    racine = Path(racine)
    _son_court(racine / "TJ SAMPLES" / "TJ Kick" / "00-KICK.wav", 60)
    preset = racine / "TJ SYNTHS" / "SYNTHS" / "Amb Air.XML"
    preset.parent.mkdir(parents=True, exist_ok=True)
    SynthPreset.new("Amb Air").save(preset, backup=False)
    for parasite in ("TJ SAMPLES/TJ Kick/._00-KICK.wav",
                     "__MACOSX/TJ SAMPLES/._00-KICK.wav"):
        p = racine / parasite
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\x00\x05\x16\x07")
    return racine


def _deposer(fenetre, *chemins):
    """Un glisser-déposer de fichiers sur la fenêtre, comme depuis
    l'Explorateur : entrée, survol, dépôt. Rend ``(accepté à l'entrée,
    voile visible, ce que dit le voile, dépôt accepté)``."""
    from PyQt6.QtCore import QMimeData, QPoint, QPointF, QUrl
    from PyQt6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent

    donnees = QMimeData()
    donnees.setUrls([QUrl.fromLocalFile(str(c)) for c in chemins])
    point = QPoint(300, 300)
    bouton, touches = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
    entree = QDragEnterEvent(point, Qt.DropAction.CopyAction, donnees,
                             bouton, touches)
    QApplication.sendEvent(fenetre, entree)
    voile = (fenetre._drop_veil.isVisible(), fenetre._drop_veil.detail())
    QApplication.sendEvent(fenetre, QDragMoveEvent(
        point, Qt.DropAction.CopyAction, donnees, bouton, touches))
    depot = QDropEvent(QPointF(point), Qt.DropAction.CopyAction, donnees,
                       bouton, touches)
    QApplication.sendEvent(fenetre, depot)
    return entree.isAccepted(), voile[0], voile[1], depot.isAccepted()


def _attendre_les_fils(condition, delai=20.0):
    """Fait tourner la boucle Qt jusqu'à ce que les fils soient finis et la
    condition vraie."""
    import time as _time

    from delugeapp.ui import tasks

    fin = _time.monotonic() + delai
    while _time.monotonic() < fin:
        _APP.processEvents()
        if tasks.active_count() == 0:
            try:
                if condition():
                    return True
            except OSError:
                pass
        _time.sleep(0.01)
    return False


class TestEnvoyerAuDelugeFenetre(MainWindowCase):
    """Des fichiers du PC vers la carte, depuis la fenêtre : glisser-déposer,
    menu Fichier, page Échantillons. La carte est ici un dossier ouvert
    directement ; le plan est accepté en remplaçant ``SendDialog.exec``,
    comme le ferait un clic sur « Envoyer »."""

    def setUp(self):
        super().setUp()
        self.pc = Path(self._tmp.name) / "pc"
        self.pack = _pack_tj(self.pc / "TJ Pack")

    def _dialogue(self, reponse):
        from unittest import mock

        from PyQt6.QtWidgets import QDialog

        from delugeapp.ui.sendfiles import SendDialog

        code = (QDialog.DialogCode.Accepted if reponse
                else QDialog.DialogCode.Rejected)
        vus = []

        def exec_(dialogue):
            vus.append(dialogue.plan)
            return code

        remplacement = mock.patch.object(SendDialog, "exec", exec_)
        remplacement.start()
        self.addCleanup(remplacement.stop)
        return vus

    def test_glisser_un_pack_sur_la_fenetre(self):
        plans = self._dialogue(True)
        win = self.window()
        accepte, voile, detail, depose = _deposer(win, self.pack)
        self.assertTrue(accepte)
        self.assertTrue(voile)
        self.assertIn("dossier de la carte", detail)
        self.assertTrue(depose)
        self.assertFalse(win._drop_veil.isVisible())
        self.assertTrue(_attendre_les_fils(
            lambda: (self.root / "SYNTHS" / "Amb Air.XML").is_file()))
        self.assertTrue((self.root / "SAMPLES" / "TJ Pack" / "TJ SAMPLES"
                         / "TJ Kick" / "00-KICK.wav").is_file())
        self.assertFalse(list(self.root.rglob("._*")))
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0].junk, 2)
        # L'index le voit sans nouvelle analyse complète.
        self.assertTrue(_attendre_les_fils(
            lambda: "SYNTHS/Amb Air.XML" in self.lib.known_files("synth")))

    def test_annuler_ne_copie_rien(self):
        self._dialogue(False)
        win = self.window()
        avant = sorted(p.relative_to(self.root).as_posix()
                       for p in self.root.rglob("*"))
        _deposer(win, self.pack)
        self.assertTrue(_attendre_les_fils(
            lambda: "Rien n'a été envoyé" in win.statusBar().currentMessage()))
        self.assertEqual(sorted(p.relative_to(self.root).as_posix()
                                for p in self.root.rglob("*")), avant)

    def test_ce_qui_n_est_pas_du_deluge_le_dit(self):
        from unittest import mock

        from PyQt6.QtWidgets import QMessageBox

        (self.pc / "lisez-moi.txt").write_text("merci")
        (self.pc / "chanson.mp3").write_bytes(b"ID3")
        vus = []
        with mock.patch.object(QMessageBox, "information",
                               lambda *a, **k: vus.append(a[1:3])):
            win = self.window()
            _deposer(win, self.pc / "lisez-moi.txt", self.pc / "chanson.mp3")
            self.assertTrue(_attendre_les_fils(lambda: vus))
        titre, texte = vus[0]
        self.assertEqual(titre, "Rien à envoyer au Deluge")
        self.assertIn("WAV", texte)

    def test_la_sauvegarde_refuse_l_envoi(self):
        from unittest import mock

        from PyQt6.QtWidgets import QMessageBox

        self.ctx.settings.card_backup = str(self.root)
        self.ctx.sd = self.ctx.settings.open_card(self.root)
        self.assertTrue(self.ctx.sd.read_only)
        avant = sorted(p.name for p in self.root.rglob("*"))
        vus = []
        with mock.patch.object(QMessageBox, "information",
                               lambda *a, **k: vus.append(a[1])):
            win = self.window()
            accepte, _voile, detail, _depose = _deposer(win, self.pack)
            self.assertTrue(_attendre_les_fils(lambda: vus))
        self.assertIn("lecture seule", detail)
        self.assertEqual(vus, ["Rien n'est écrit ici"])
        self.assertEqual(sorted(p.name for p in self.root.rglob("*")), avant)

    def test_le_menu_fichier_envoie_un_dossier(self):
        from unittest import mock

        from PyQt6.QtWidgets import QFileDialog

        self._dialogue(True)
        win = self.window()
        action = next(a for entree in win.menuBar().actions()
                      if entree.menu() is not None
                      for a in entree.menu().actions()
                      if a.text() == "Envoyer un dossier au Deluge…")
        with mock.patch.object(QFileDialog, "getExistingDirectory",
                               lambda *a, **k: str(self.pack)):
            action.trigger()
            self.assertTrue(_attendre_les_fils(
                lambda: (self.root / "SYNTHS" / "Amb Air.XML").is_file()))

    def test_la_page_echantillons_envoie_dans_le_dossier_choisi(self):
        from unittest import mock

        from PyQt6.QtWidgets import QFileDialog

        self._dialogue(True)
        son = _son_court(self.pc / "loose.wav")
        win = self.window()
        win.go_to("Samples")
        page = win._pages["Samples"]
        cible = None
        a_voir = [page._tree.topLevelItem(0)]
        while a_voir:
            item = a_voir.pop()
            if item.data(0, Qt.ItemDataRole.UserRole) == "SAMPLES/DRUMS/Kick":
                cible = item
            a_voir.extend(item.child(i) for i in range(item.childCount()))
        page._tree.setCurrentItem(cible)
        self.assertEqual(page._folder, "SAMPLES/DRUMS/Kick")
        with mock.patch.object(QFileDialog, "getOpenFileNames",
                               lambda *a, **k: ([str(son)], "")):
            page._send_button.click()
            self.assertTrue(_attendre_les_fils(
                lambda: (self.root / "SAMPLES/DRUMS/Kick/loose.wav").is_file()))

    def test_un_son_se_glisse_hors_de_la_liste(self):
        win = self.window()
        win.go_to("Samples")
        page = win._pages["Samples"]
        self.assertTrue(page._table.dragEnabled())
        modele = page._model
        index = modele.index(0, 0)
        self.assertTrue(modele.flags(index) & Qt.ItemFlag.ItemIsDragEnabled)
        donnees = modele.mimeData([index])
        adresses = [Path(u.toLocalFile()) for u in donnees.urls()]
        self.assertEqual(len(adresses), 1)
        self.assertTrue(adresses[0].is_file())
        self.assertEqual(adresses[0].parent.parent.parent.name, "SAMPLES")

    def test_un_fichier_s_ouvre_sur_sa_page_malgre_les_filtres(self):
        win = self.window()
        win.go_to("Samples")
        page = win._pages["Samples"]
        page._search.setText("zzz")
        page._reload()
        self.assertEqual(page._model.rowCount(), 0)
        win.go_to("Samples#SAMPLES/DRUMS/Snare/s.wav")
        lignes = page._selected_rows()
        self.assertEqual([r["rel"] for r in lignes],
                         ["SAMPLES/DRUMS/Snare/s.wav"])
        self.assertEqual(page._search.text(), "")
        win.go_to("Songs#SONGS/M.XML")
        songs = win._pages["Songs"]
        indexes = songs._table.selectionModel().selectedRows()
        self.assertEqual(
            songs._model.row_at(songs._proxy.mapToSource(indexes[0]).row())
            ["rel"], "SONGS/M.XML")


class TestLeDelugeEtLePC(CarteUsbCase):
    """L'envoi et la synchronisation face au Deluge simulé : ce qui attend,
    ce qui part, ce qui s'arrête, ce qui se raconte."""

    def _dialogue_accepte(self):
        from unittest import mock

        from PyQt6.QtWidgets import QDialog

        from delugeapp.ui.sendfiles import SendDialog

        remplacement = mock.patch.object(
            SendDialog, "exec", lambda _d: QDialog.DialogCode.Accepted)
        remplacement.start()
        self.addCleanup(remplacement.stop)

    def test_ce_qui_est_envoye_part_sur_le_deluge_et_se_raconte(self):
        self._dialogue_accepte()
        win, travail, _page = self._avec_copie()
        travail._timer.setInterval(10)
        pack = _pack_tj(Path(self._tmp.name) / "pc" / "TJ Pack")
        with self.assertLogs("delugeapp.ui.cardwork", level="INFO") as journal:
            accepte, _voile, detail, _depose = _deposer(win, pack)
            self.assertIn("par le câble USB", detail)
            self.assertTrue(self._attendre(
                lambda: (self.carte / "SYNTHS" / "Amb Air.XML").is_file()
                and not travail.busy and not travail.pending))
        self.assertTrue((self.carte / "SAMPLES" / "TJ Pack" / "TJ SAMPLES"
                         / "TJ Kick" / "00-KICK.wav").is_file())
        dernier = travail.exchanges(1)[0]
        self.assertIn("SYNTHS/Amb Air.XML", dernier.sent)
        self.assertTrue(any("envoyé : SYNTHS/Amb Air.XML" in ligne
                            for ligne in journal.output), journal.output)
        self.assertNotIn("À ENVOYER", win._card_button._haut)

    def test_debranche_les_fichiers_attendent_puis_partent(self):
        win, travail, _page = self._avec_copie()
        self.lien.disconnect()
        self.assertIsNone(travail.files())
        nouveau = Path(self.ctx.settings.work_dir) / "SONGS" / "ATTENTE.XML"
        nouveau.write_bytes(b"<song attente/>")
        win._card_written()
        # Compté hors du fil de l'interface.
        self.assertTrue(self._attendre(
            lambda: travail.pending == [("SONGS/ATTENTE.XML", 15)]))
        self.assertIn("1 À ENVOYER", win._card_button._haut)
        win.go_to("Dashboard")
        tableau = win._pages["Dashboard"]
        self.assertEqual(tableau._link_state.text(), "Deluge débranché.")
        self.assertIn("1 fichier(s) attendent le Deluge",
                      tableau._link_detail.text())
        self.assertFalse(tableau._sync_button.isEnabled())
        # Rebranché : il part à la connexion.
        self.machine.brancher(self.lien)
        self.assertTrue(self.lien.connect())
        self.assertTrue(self.lien.wait_files(5.0))
        travail.on_files_known()
        self.assertTrue(self._attendre(
            lambda: (self.carte / "SONGS/ATTENTE.XML").is_file()
            and not travail.busy))
        self.assertEqual(travail.pending, [])
        self.assertNotIn("À ENVOYER", win._card_button._haut)

    def test_quand_le_deluge_joue_l_envoi_s_arrete_puis_reprend(self):
        win, travail, _page = self._avec_copie()
        travail._timer.setInterval(10)
        carte_usb = self.machine.carte_usb
        vrai = carte_usb.traite
        lien = self.lien

        def traite(data):
            reponse = vrai(data)
            if carte_usb.commandes and carte_usb.commandes[-1][0] == "write":
                lien.running = True            # on appuie sur PLAY
            return reponse

        carte_usb.traite = traite
        gros = Path(self.ctx.settings.work_dir) / "SAMPLES" / "GROS.WAV"
        contenu = bytes((i * 13) % 256 for i in range(20_000))
        gros.write_bytes(contenu)
        win._card_written()
        self.assertTrue(self._attendre(
            lambda: not travail.busy and "reprendra" in travail.message))
        self.assertFalse((self.carte / "SAMPLES/GROS.WAV").exists())
        self.assertFalse([p for p in self.carte.rglob("~DC*")])
        # On arrête la lecture : l'envoi reprend, et va au bout.
        carte_usb.traite = vrai
        lien.running = False
        travail.on_transport()
        self.assertTrue(self._attendre(
            lambda: (self.carte / "SAMPLES/GROS.WAV").is_file()
            and not travail.busy))
        self.assertEqual((self.carte / "SAMPLES/GROS.WAV").read_bytes(),
                         contenu)

    def test_ce_qui_est_arrive_du_deluge_s_ouvre_d_un_clic(self):
        win, travail, _page = self._avec_copie()
        # La création a reçu NEUF.XML par le câble ; la page Morceaux doit
        # l'avoir indexé.
        self.assertTrue(self._attendre(
            lambda: "SONGS/NEUF.XML" in self.ctx.lib.known_files("song")))
        win.go_to("Dashboard")
        tableau = win._pages["Dashboard"]
        tableau.refresh_exchanges()
        lignes = [tableau._arrivals.itemAt(i).widget()
                  for i in range(tableau._arrivals.count())]
        self.assertEqual([l.cible for l in lignes], ["Songs#SONGS/NEUF.XML"])
        self.assertTrue(tableau._arrivals_title.isVisibleTo(tableau))
        lignes[0].mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease, 5))
        self.assertIs(win._stack.currentWidget(), win._pages["Songs"])
        songs = win._pages["Songs"]
        indexes = songs._table.selectionModel().selectedRows()
        self.assertEqual(
            songs._model.row_at(songs._proxy.mapToSource(indexes[0]).row())
            ["rel"], "SONGS/NEUF.XML")

    def test_la_sauvegarde_se_compare_et_se_met_a_jour_hors_du_fil(self):
        import threading
        from unittest import mock

        from delugeapp.core import cardsync

        win, travail, _page = self._avec_copie()
        self.assertTrue(self._attendre(lambda: travail.backup_plan
                                       is not None))
        # NEUF.XML est sur la carte, pas dans la sauvegarde.
        self.assertEqual(travail.backup_missing(), 1)
        win.go_to("Dashboard")
        tableau = win._pages["Dashboard"]
        tableau.refresh()
        self.assertIn("sauvegarde n'a pas encore 1 fichier",
                      tableau._next_text.text())
        # Le bandeau le dit : le panneau ne le répète pas.
        self.assertFalse(tableau._backup_row.isVisibleTo(tableau))
        fils = []
        vrai = cardsync.update_backup

        def espion(*args, **kwargs):
            fils.append(threading.current_thread() is threading.main_thread())
            return vrai(*args, **kwargs)

        with mock.patch.object(cardsync, "update_backup", espion):
            tableau._next_button.click()          # « oui » à la question
            self.assertTrue(self._attendre(
                lambda: (self.sauvegarde / "SONGS/NEUF.XML").is_file()
                and len(fils) == 2))
        self.assertEqual(fils, [False, False])
        self.assertEqual((self.sauvegarde / "SONGS/NEUF.XML").read_bytes(),
                         b"<song neuf/>")
        self.assertEqual(travail.backup_missing(), 0)
        # Le bandeau a suivi sans nouveau diagnostic.
        self.assertNotIn("sauvegarde n'a pas encore",
                         tableau._next_text.text())
        # Mise à jour demandée : c'est la seule écriture voulue ici.
        self.empreinte_sauvegarde = self._empreinte(self.sauvegarde)

    def test_un_compte_ancien_ne_contredit_pas_la_synchronisation(self):
        from delugeapp.core import cardsync

        _win, travail, _page = self._avec_copie()
        travail.refresh_pending()
        ancien = travail._generation
        # Une synchronisation finit avant le compte : c'est elle qui a raison.
        travail._done((cardsync.SyncPlan(), cardsync.SyncResult(), 0.1, [],
                       "essai"))
        travail._pending_counted(ancien, [("SONGS/PERIME.XML", 1)])
        self.assertEqual(travail.pending, [])
        self.assertTrue(self._attendre(lambda: True))
        self.assertEqual(travail.pending, [])

    def test_un_travail_discret_n_efface_pas_le_message(self):
        win, travail, _page = self._avec_copie()
        win.statusBar().showMessage("12 fichier(s) posé(s) sur la carte.")
        travail.refresh_pending()
        travail.check_backup()
        self.assertTrue(self._attendre(lambda: True))
        self.assertEqual(win.statusBar().currentMessage(),
                         "12 fichier(s) posé(s) sur la carte.")

    def test_une_mise_a_jour_demandee_pendant_la_comparaison_attend(self):
        win, travail, _page = self._avec_copie()
        self.assertTrue(self._attendre(lambda: travail.backup_plan
                                       is not None))
        travail.check_backup()            # une comparaison repart…
        self.assertTrue(travail._backup_busy)
        travail.update_backup(win)        # … et l'on clique pendant ce temps
        self.assertTrue(self._attendre(
            lambda: (self.sauvegarde / "SONGS/NEUF.XML").is_file()))
        self.empreinte_sauvegarde = self._empreinte(self.sauvegarde)


# --------------------------------------------------------------------------- #
# L'interface en anglais (19 octobre 2026)
# --------------------------------------------------------------------------- #

#: Une lettre accentuée : l'anglais de l'interface n'en a aucune.
_ACCENTS = re.compile(r"[éèêëàâçùûôîïœÉÈÊÀÂÇÔÎ]")
#: Des mots qui ne sont qu'en français, et qu'un texte oublié contient
#: presque toujours.
_MOTS_FRANCAIS = re.compile(
    r"\b(le|la|les|des|du|une|aucun|aucune|avec|pour|dans|sur|est|sont|pas|"
    r"vous|votre|vos|carte|morceaux?|fichiers?|dossiers?|réglages|santé|"
    r"rien|encore|ici|cette|ces|mais|ou bien)\b", re.IGNORECASE)
#: Ce qui reste en français par choix : le nom de la langue dans son menu.
_FRANCAIS_PERMIS = {"Français"}


def _textes_visibles(fenetre) -> list[tuple[str, str]]:
    """``(origine, texte)`` de ce que la fenêtre — ou une page, un
    dialogue — montre ou explique : textes,
    titres, info-bulles, entrées de listes, en-têtes et premières lignes des
    tableaux, menus."""
    from PyQt6.QtCore import Qt as _Qt
    from PyQt6.QtGui import QAction
    from PyQt6.QtWidgets import (QAbstractButton, QAbstractItemView,
                                 QComboBox, QGroupBox, QLineEdit, QMenu,
                                 QPlainTextEdit, QTabWidget, QTextEdit)

    textes: list[tuple[str, str]] = []

    def noter(origine: str, texte) -> None:
        if isinstance(texte, str) and texte.strip():
            textes.append((origine, texte))

    noter("titre de fenêtre", fenetre.windowTitle())
    for w in fenetre.findChildren(QWidget):
        nom = type(w).__name__
        noter(nom + " (info-bulle)", w.toolTip())
        noter(nom + " (barre d'état)", w.statusTip())
        if isinstance(w, QLabel):
            noter(nom, w.text())
        elif isinstance(w, QAbstractButton):
            noter(nom, w.text())
        elif isinstance(w, QGroupBox):
            noter(nom, w.title())
        elif isinstance(w, QLineEdit):
            noter(nom + " (indication)", w.placeholderText())
        elif isinstance(w, QComboBox):
            for i in range(w.count()):
                noter(nom, w.itemText(i))
        elif isinstance(w, QTabWidget):
            for i in range(w.count()):
                noter("onglet", w.tabText(i))
                noter("onglet (info-bulle)", w.tabToolTip(i))
        elif isinstance(w, QMenu):
            noter("menu", w.title())
        elif isinstance(w, (QTextEdit, QPlainTextEdit)):
            # Le texte du manuel cite exprès des mots de l'autre langue
            # (« Français », « Été » devient « Ete ») : il est vérifié à
            # part, par ``TestLeManuelSeLit``.
            if w.objectName() != "PageManuel":
                noter(nom, w.toPlainText())
            noter(nom + " (indication)", w.placeholderText())
        if isinstance(w, QAbstractItemView) and w.model() is not None:
            modele = w.model()
            try:
                colonnes = modele.columnCount()
            except TypeError:           # un modèle de liste : une colonne
                colonnes = 1
            for c in range(colonnes):
                noter(nom + " (en-tête)", modele.headerData(
                    c, _Qt.Orientation.Horizontal,
                    _Qt.ItemDataRole.DisplayRole))
            for r in range(min(modele.rowCount(), 40)):
                for c in range(colonnes):
                    noter(nom + " (cellule)", modele.data(modele.index(r, c)))
    for action in fenetre.findChildren(QAction):
        noter("action", action.text())
        noter("action (info-bulle)", action.toolTip())
        noter("action (barre d'état)", action.statusTip())
    if hasattr(fenetre, "statusBar"):
        noter("barre d'état", fenetre.statusBar().currentMessage())
    return textes


def _a_l_air_francais(texte: str) -> bool:
    propre = texte.replace("&", "").strip()
    if propre in _FRANCAIS_PERMIS:
        return False
    return bool(_ACCENTS.search(propre) or _MOTS_FRANCAIS.search(propre))


class TestInterfaceEnAnglais(MainWindowCase):
    """L'interface entière en anglais, sans un mot de français oublié.

    Le test que l'analyse du code ne remplace pas : un texte composé à
    l'exécution, une constante traduite au mauvais endroit, une aide
    retrouvée par son libellé français — seul l'écran les montre.
    """

    def setUp(self):
        super().setUp()
        from delugeapp import i18n

        i18n.set_language("en")
        self.addCleanup(i18n.set_language, "fr")

    def _toutes_les_pages(self, win):
        from PyQt6.QtWidgets import QTabWidget

        for cle in list(win._classes):
            win.go_to(cle)
            for _ in range(4):
                _APP.processEvents()
            page = win._pages[cle]
            for onglets in page.findChildren(QTabWidget):
                for index in range(onglets.count()):
                    onglets.setCurrentIndex(index)
                    _APP.processEvents()
            yield cle, page

    def test_aucun_texte_francais_a_l_ecran(self):
        win = self.window()
        trouves: dict[str, set[str]] = {}
        pages = lus = 0
        for cle, _page in self._toutes_les_pages(win):
            pages += 1
            for origine, texte in _textes_visibles(win):
                lus += 1
                # Le dossier de la carte d'essai s'appelle « carte » : une
                # donnée, pas un texte de l'interface.
                if _a_l_air_francais(texte.replace(str(self.root), "")):
                    trouves.setdefault(texte[:120], set()).add(
                        "%s, %s" % (cle, origine))
        self.assertEqual(pages, 10, "les dix pages n'ont pas été visitées")
        # Mesuré le 19 octobre 2026 : 8 606 textes lus, dont 459 distincts
        # signalés quand l'interface est en français. Un relevé qui ne lit
        # plus rien passerait sans rien prouver.
        self.assertGreater(lus, 4000, "le relevé n'a presque rien lu")
        self.assertEqual(
            trouves, {},
            "%d texte(s) en français dans l'interface anglaise :\n%s"
            % (len(trouves), "\n".join(
                "  %r  ← %s" % (t, " ; ".join(sorted(o)[:2]))
                for t, o in sorted(trouves.items()))))

    def test_chaque_commande_s_explique_aussi_en_anglais(self):
        """Le registre d'aide désigne les commandes par leur libellé
        français : en anglais, il doit les retrouver quand même."""
        from delugeapp.ui import aide

        win = self.window()
        muettes = {}
        for cle, page in self._toutes_les_pages(win):
            restantes = aide.manquantes(page, cle)
            if restantes:
                muettes[cle] = restantes
        self.assertEqual(
            muettes, {},
            "commandes sans explication en anglais : %s"
            % "; ".join("%s : %s" % (k, ", ".join(v))
                        for k, v in muettes.items()))

    def test_ce_qu_ouvrent_les_menus_est_en_anglais(self):
        """Fenêtre « en direct », raccourcis, à propos, boîtes : ce qu'ouvre
        chaque entrée de menu parle anglais."""
        import contextlib
        from unittest import mock

        from PyQt6.QtWidgets import (QApplication, QDialog, QFileDialog,
                                     QMenu, QMessageBox)

        from delugeapp.ui import tasks

        vus: list[tuple[str, str]] = []

        def boite(nom, reponse):
            def repondre(*args, **kwargs):
                vus.extend((nom, v) for v in list(args) + list(kwargs.values())
                           if isinstance(v, str))
                return reponse
            return staticmethod(repondre)

        def dialogue(fenetre):
            vus.extend(_textes_visibles(fenetre))
            return QDialog.DialogCode.Rejected

        non = QMessageBox.StandardButton.No
        # Défaits avant le ``tearDown`` : défaits après, ils rendraient
        # aux tests suivants les dialogues de la classe de base, qui
        # répondent « oui ».
        with contextlib.ExitStack() as portes:
            for classe, nom, reponse in (
                    (QMessageBox, "question", non),
                    (QMessageBox, "information", None),
                    (QMessageBox, "warning", None),
                    (QMessageBox, "critical", None),
                    (QMessageBox, "about", None),
                    (QFileDialog, "getExistingDirectory", ""),
                    (QFileDialog, "getOpenFileName", ("", "")),
                    (QFileDialog, "getOpenFileNames", ([], "")),
                    (QFileDialog, "getSaveFileName", ("", ""))):
                portes.enter_context(mock.patch.object(
                    classe, nom,
                    boite("%s.%s" % (classe.__name__, nom), reponse)))
            portes.enter_context(mock.patch.object(QDialog, "exec", dialogue))

            win = self.window()
            avant = set(QApplication.topLevelWidgets())
            essayees = 0
            for menu in win.menuBar().findChildren(QMenu):
                for action in menu.actions():
                    if (action.isSeparator() or not action.isEnabled()
                            or action.text() == "Quit"
                            or action in win._language_actions.values()):
                        continue
                    action.trigger()
                    _APP.processEvents()
                    vus.append(("barre d'état",
                                win.statusBar().currentMessage()))
                    essayees += 1
            tasks.stop_all(3000)
            _APP.processEvents()
            ouvertes = [w for w in QApplication.topLevelWidgets()
                        if w not in avant and w.isVisible()]
            for fenetre in ouvertes:
                vus.extend(_textes_visibles(fenetre))
                fenetre.close()

        trouves = sorted({t[:120] for _o, t in vus
                          if _a_l_air_francais(t.replace(str(self.root), ""))})
        self.assertGreaterEqual(essayees, 10)
        self.assertTrue(ouvertes, "aucune fenêtre ouverte par les menus")
        self.assertEqual(trouves, [], "\n".join(trouves))

    def test_les_menus_parlent_anglais(self):
        win = self.window()
        titres = [a.text().replace("&", "") for a in win.menuBar().actions()]
        self.assertEqual(titres, ["File", "Edit", "Tools", "Language", "Help"])


class TestMenuLangue(MainWindowCase):
    """Le menu Langue : le choix est gardé, la fenêtre se rouvre."""

    def setUp(self):
        super().setUp()
        from delugeapp import i18n

        self.i18n = i18n
        self.addCleanup(i18n.set_language, "fr")

    def _action(self, win, code: str):
        from PyQt6.QtWidgets import QMenu

        menus = {m.title().replace("&", ""): m
                 for m in win.menuBar().findChildren(QMenu)}
        self.assertIn("Langue", menus)
        libelle = dict(self.i18n.LANGUAGES)[code]
        actions = [a for a in menus["Langue"].actions()
                   if a.text().replace("&", "") == libelle]
        self.assertEqual(len(actions), 1, libelle)
        return actions[0]

    def test_le_menu_coche_la_langue_affichee(self):
        win = self.window()
        self.assertTrue(self._action(win, "fr").isChecked())
        self.assertFalse(self._action(win, "en").isChecked())

    def test_choisir_l_anglais_redemarre_la_fenetre(self):
        from delugeapp.config import load_settings

        win = self.window()
        self.answer = self.mw.QMessageBox.StandardButton.Yes
        self._action(win, "en").trigger()
        _APP.processEvents()
        self.assertTrue(win.restart_requested)
        self.assertFalse(win.isVisible(), "la fenêtre devait se fermer")
        self.assertEqual(self.ctx.settings.language, "en")
        # Gardé sur le disque : c'est là que le redémarrage le relira.
        self.assertEqual(load_settings().language, "en")
        # La fenêtre elle-même ne change pas de langue : c'est la suivante.
        self.assertEqual(self.i18n.language(), "fr")

    def test_plus_tard_garde_le_choix_pour_le_prochain_demarrage(self):
        from delugeapp.config import load_settings

        win = self.window()
        self.answer = self.mw.QMessageBox.StandardButton.No
        self._action(win, "en").trigger()
        _APP.processEvents()
        self.assertFalse(win.restart_requested)
        self.assertTrue(win.isVisible())
        self.assertEqual(load_settings().language, "en")
        self.assertTrue(self._action(win, "en").isChecked())
        message = win.statusBar().currentMessage()
        self.assertIn("prochain démarrage", message)

    def test_la_langue_affichee_ne_redemande_rien(self):
        win = self.window()
        self._action(win, "fr").trigger()
        _APP.processEvents()
        self.assertFalse(win.restart_requested)
        self.assertTrue(win.isVisible())


class TestRedemarrageDansLeMemeProcessus(WidgetCase):
    """``main._run_windows`` rebâtit contexte et fenêtre tant que la fenêtre
    demande un redémarrage, et la seconde parle la langue choisie."""

    def test_la_fenetre_se_rouvre_dans_la_nouvelle_langue(self):
        import argparse
        from unittest import mock

        import main as lanceur
        from delugeapp import i18n
        from delugeapp.ui import mainwindow, theme as theme_mod

        self.addCleanup(i18n.set_language, "fr")
        langues = iter(["fr", "en"])
        contextes, fenetres, traductions = [], [], []

        class Contexte:
            def __init__(self):
                self.settings = mock.Mock(theme_accent="", language="")
                self.ferme = False

            def close(self):
                self.ferme = True

        def batir(args):
            ctx = Contexte()
            ctx.settings.language = i18n.set_language(next(langues))
            contextes.append(ctx)
            return ctx

        class Fenetre:
            def __init__(self, ctx):
                self.langue = i18n.language()
                # La première demande un redémarrage, la seconde non.
                self.restart_requested = not fenetres
                fenetres.append(self)

            def show(self):
                pass

            def deleteLater(self):
                pass

        app = mock.Mock()
        app.exec.return_value = 0
        args = argparse.Namespace(reset_db=True)
        def traduire(_app, code):
            traductions.append(code)

        with mock.patch.object(lanceur, "_build_context", batir), \
                mock.patch.object(lanceur, "_translate_qt", traduire), \
                mock.patch.object(mainwindow, "MainWindow", Fenetre), \
                mock.patch.object(theme_mod, "apply_theme",
                                  lambda *a, **k: None):
            code = lanceur._run_windows(app, args)

        self.assertEqual(code, 0)
        self.assertEqual([f.langue for f in fenetres], ["fr", "en"])
        self.assertEqual(traductions, ["fr", "en"])
        self.assertTrue(all(c.ferme for c in contextes))
        # L'index ne se vide qu'au premier démarrage.
        self.assertFalse(args.reset_db)

    def test_les_boutons_de_qt_suivent_la_langue(self):
        """« Oui / Non » en français ; en anglais, le traducteur français
        est retiré, sinon il resterait d'une fenêtre à l'autre."""
        from PyQt6.QtCore import QCoreApplication

        import main as lanceur

        # Rendre l'application de test telle qu'on l'a trouvée.
        self.addCleanup(lanceur._translate_qt, _APP,
                        "en" if lanceur._qt_translator is None else "fr")
        if lanceur._translate_qt(_APP, "fr") is None:
            self.skipTest("traduction française de Qt absente")
        self.assertEqual(QCoreApplication.translate("QPlatformTheme", "&Yes"),
                         "&Oui")
        self.assertIsNone(lanceur._translate_qt(_APP, "en"))
        self.assertIsNone(lanceur._qt_translator)
        self.assertEqual(QCoreApplication.translate("QPlatformTheme", "&Yes"),
                         "&Yes")


class TestClicsEnAnglais(InteractionCase):
    """Chaque bouton cliqué dans l'interface anglaise : ce qui s'affiche
    ensuite — barre d'état, boîtes, dialogues, sélecteurs de fichiers — est
    en anglais aussi.

    Le relevé de l'état initial ne voit pas les textes composés en réponse
    à un geste : « 3 fichier(s) corrigés », le titre d'un plan, le filtre
    d'un sélecteur de fichiers.
    """

    def setUp(self):
        super().setUp()
        from unittest import mock

        from PyQt6.QtWidgets import (QDialog, QFileDialog, QInputDialog,
                                     QMessageBox)

        from delugeapp import i18n

        i18n.set_language("en")
        self.addCleanup(i18n.set_language, "fr")
        self.vus: list[tuple[str, str]] = []

        def boite(nom, reponse):
            def repondre(*args, **kwargs):
                for valeur in list(args) + list(kwargs.values()):
                    if isinstance(valeur, str):
                        self.vus.append((nom, valeur))
                return reponse
            return staticmethod(repondre)

        def dialogue(fenetre):
            self.vus.extend(("dialogue %s, %s" % (type(fenetre).__name__, o),
                             t) for o, t in _textes_visibles(fenetre))
            return QDialog.DialogCode.Rejected

        non = QMessageBox.StandardButton.No
        portes = [
            (QMessageBox, "question", non), (QMessageBox, "information", None),
            (QMessageBox, "warning", None), (QMessageBox, "critical", None),
            (QMessageBox, "about", None),
            (QFileDialog, "getSaveFileName", ("", "")),
            (QFileDialog, "getOpenFileName", ("", "")),
            (QFileDialog, "getOpenFileNames", ([], "")),
            (QFileDialog, "getExistingDirectory", ""),
            (QInputDialog, "getText", ("", False)),
            (QInputDialog, "getMultiLineText", ("", False)),
            (QInputDialog, "getInt", (0, False)),
            (QInputDialog, "getDouble", (0.0, False)),
            (QInputDialog, "getItem", ("", False)),
        ]
        for classe, nom, reponse in portes:
            porte = mock.patch.object(
                classe, nom, boite("%s.%s" % (classe.__name__, nom), reponse))
            porte.start()
            self.addCleanup(porte.stop)
        porte = mock.patch.object(QDialog, "exec", dialogue)
        porte.start()
        self.addCleanup(porte.stop)

    def test_ce_qu_affiche_un_clic_est_en_anglais(self):
        from PyQt6.QtWidgets import QAbstractButton

        from delugeapp.ui import tasks

        boutons = 0
        for cls in self._pages():
            page = self.open(cls)
            page.status.connect(
                lambda m, n=cls.__name__: self.vus.append(
                    ("%s, barre d'état" % n, m)))
            TestClicsReels._choisir_une_ligne(page)
            tous = page.findChildren(QAbstractButton)
            for bouton in ([b for b in tous if b.isEnabled()]
                           + [b for b in tous if not b.isEnabled()]):
                bouton.setEnabled(True)
                bouton.click()
                _APP.processEvents()
                boutons += 1
            tasks.stop_all(2000)
            _APP.processEvents()
            self.vus.extend(("%s, après les clics, %s" % (cls.__name__, o), t)
                            for o, t in _textes_visibles(page))

        trouves: dict[str, set[str]] = {}
        for origine, texte in self.vus:
            if _a_l_air_francais(texte.replace(str(self.root), "")):
                trouves.setdefault(texte[:120], set()).add(origine)
        self.assertGreater(boutons, 40, "trop peu de boutons cliqués")
        self.assertGreater(len(self.vus), 2000,
                           "le relevé n'a presque rien lu")
        self.assertEqual(
            trouves, {},
            "%d texte(s) en français après un clic :\n%s"
            % (len(trouves), "\n".join(
                "  %r  ← %s" % (t, " ; ".join(sorted(o)[:2]))
                for t, o in sorted(trouves.items()))))

# --------------------------------------------------------------------------- #
# Le manuel (21 octobre 2026)
# --------------------------------------------------------------------------- #

#: Ce que le manuel anglais cite en français, exprès : le nom de la langue,
#: l'exemple d'un clip nommé dans la langue de l'interface, d'un nom
#: assaini, et des noms de dossiers écrits par l'application.
_CITATIONS_FRANCAISES = ("Français", "“Accords”", "“Été”", "TRANCHES",
                         "Carte")


def _manuels() -> dict:
    from delugeapp.ui import manuel

    return {langue: manuel.charger(langue) for langue in ("fr", "en")}


class TestLeManuelSeLit(WidgetCase):
    """Le texte des deux manuels : bien formé, complet, et le même des deux
    côtés — mêmes chapitres, mêmes sections, mêmes figures, mêmes liens."""

    @classmethod
    def setUpClass(cls):
        cls.manuels = _manuels()

    def test_les_deux_manuels_se_lisent_sans_erreur(self):
        for langue, m in self.manuels.items():
            with self.subTest(langue=langue):
                self.assertEqual(m.erreurs, [])
                self.assertGreaterEqual(len(m.parties), 4)
                self.assertGreaterEqual(len(m.chapitres), 20)
                # Mesuré à l'écriture : 13 500 mots en français, 12 600 en
                # anglais. Un manuel tronqué par une erreur de lecture
                # tomberait bien en dessous.
                self.assertGreater(len(m.texte_brut().split()), 10000)

    def test_les_deux_langues_ont_la_meme_structure(self):
        """La bascule de langue garde la place du lecteur par les ancres :
        elles doivent être les mêmes, dans le même ordre."""
        fr, en = self.manuels["fr"], self.manuels["en"]
        self.assertEqual(fr.ancres, en.ancres)
        self.assertEqual(
            [(c.ident, c.page, [a for a, _t in c.sections])
             for c in fr.chapitres],
            [(c.ident, c.page, [a for a, _t in c.sections])
             for c in en.chapitres])
        self.assertEqual([(f[0], len(f[2])) for f in fr.figures],
                         [(f[0], len(f[2])) for f in en.figures])
        self.assertEqual(sorted(set(fr.liens)), sorted(set(en.liens)))

    def test_chaque_page_a_son_chapitre(self):
        """F1 ouvre le chapitre de la page affichée : les dix en ont un."""
        from delugeapp.ui.mainwindow import _page_classes, _short_name

        for langue, m in self.manuels.items():
            for classe in _page_classes():
                cle = _short_name(classe)
                with self.subTest(langue=langue, page=cle):
                    self.assertIsNotNone(m.chapitre_de_page(cle))

    def test_chaque_renvoi_mene_quelque_part(self):
        from delugeapp.ui.mainwindow import _page_classes, _short_name

        pages = {_short_name(c) for c in _page_classes()}
        for langue, m in self.manuels.items():
            for lien in m.liens:
                with self.subTest(langue=langue, lien=lien):
                    if lien.startswith("#"):
                        self.assertIn(lien[1:], m.ancres)
                    else:
                        self.assertTrue(lien.startswith("app:"), lien)
                        cible = lien[4:]
                        self.assertTrue(cible == "@live"
                                        or cible.split("#")[0] in pages)

    def test_chaque_figure_a_ses_libelles_et_se_dessine(self):
        from delugeapp.ui import manuel_dessins as dessins

        for langue, m in self.manuels.items():
            for nom, legende, libelles in m.figures:
                with self.subTest(langue=langue, figure=nom):
                    self.assertIn(nom, dessins.FIGURES)
                    self.assertEqual(len(libelles), dessins.FIGURES[nom][1])
                    self.assertTrue(legende.strip())
                    self.assertFalse(dessins.figure(nom, libelles).isNull())

    def test_chaque_image_se_dessine(self):
        from delugeapp.ui import manuel

        for langue, m in self.manuels.items():
            for adresse in m.images:
                with self.subTest(langue=langue, image=adresse):
                    self.assertFalse(manuel.image(adresse, m).isNull())

    def test_le_balisage_ne_se_voit_pas(self):
        """Un reste de balisage à l'écran trahit une erreur de lecture."""
        for langue, m in self.manuels.items():
            texte = m.texte_brut()
            for reste in ("**", "[[", "]]", "!!!", "@partie", "{#", "\x00",
                          "](#", "](app:"):
                with self.subTest(langue=langue, reste=reste):
                    self.assertNotIn(reste, texte)

    def test_le_francais_a_ses_espaces_insecables(self):
        """Comme dans le guide : jamais une espace ordinaire devant « : »,
        « ; », « ? », « ! », ni dans les guillemets."""
        texte = self.manuels["fr"].texte_brut()
        fautes = re.findall(r"\S {1}[:;?!](?=\s)|« \S|\S »", texte)
        self.assertEqual(fautes, [])

    def test_le_manuel_anglais_est_en_anglais(self):
        texte = self.manuels["en"].texte_brut()
        for citation in _CITATIONS_FRANCAISES:
            texte = texte.replace(citation, "")
        phrases = [p.strip() for p in re.split(r"(?<=[.:!?])\s+|\n", texte)
                   if p.strip()]
        francaises = [p[:100] for p in phrases if _a_l_air_francais(p)]
        self.assertGreater(len(phrases), 500)
        self.assertEqual(francaises, [])

    def test_la_recherche_ignore_accents_et_majuscules(self):
        from delugeapp.ui import manuel

        page = self.shown(manuel.PageDeLecture(), 900, 600)
        page.afficher(self.manuels["fr"])
        plages = page.trouver_tout("ECHANTILLON")
        self.assertGreater(len(plages), 50)
        brut = page.document().toRawText()
        for debut, fin in plages[:20]:
            self.assertEqual(manuel.ancre_de(brut[debut:fin]), "echantillon")


class TestLeManuelDansLAide(MainWindowCase):
    """Aide ▸ Manuel : chaque geste est fait comme l'utilisateur le fait —
    menu, touche, clic dans le sommaire, clic sur un bouton."""

    def _action(self, win, libelle: str):
        from PyQt6.QtWidgets import QMenu

        for menu in win.menuBar().findChildren(QMenu):
            for action in menu.actions():
                if action.text().replace("&", "") == libelle:
                    return action
        self.fail("entrée de menu introuvable : %s" % libelle)

    def _manuel(self, win):
        fenetre = win._manual_window
        self.assertIsNotNone(fenetre, "le manuel ne s'est pas ouvert")
        self._widgets.append(fenetre)
        _pump(150)
        return fenetre

    def _chapitre_lu(self, fenetre) -> str:
        chapitre = fenetre.manuel.chapitre_de(fenetre.page.ancre_visible())
        return chapitre.ident if chapitre is not None else ""

    def test_f1_ouvre_le_manuel_au_chapitre_de_la_page(self):
        win = self.window()
        action = self._action(win, "Manuel")
        self.assertEqual(action.shortcut().toString(), "F1")
        for cle, chapitre in (("Kits", "kits"), ("Health", "sante"),
                              ("Toolbox", "boite-a-outils")):
            with self.subTest(page=cle):
                win.go_to(cle)
                _APP.processEvents()
                action.trigger()
                fenetre = self._manuel(win)
                self.assertTrue(fenetre.isVisible())
                self.assertEqual(self._chapitre_lu(fenetre), chapitre)
                self.assertEqual(fenetre._sommaire.currentItem().data(
                    0, Qt.ItemDataRole.UserRole), chapitre)

    def test_premiers_pas(self):
        win = self.window()
        self._action(win, "Premiers pas").trigger()
        self.assertEqual(self._chapitre_lu(self._manuel(win)), "premiers-pas")

    def test_le_manuel_parle_la_langue_de_l_interface(self):
        from delugeapp import i18n

        i18n.set_language("en")
        self.addCleanup(i18n.set_language, "fr")
        win = self.window()
        self._action(win, "Manual").trigger()
        fenetre = self._manuel(win)
        self.assertEqual(fenetre.manuel.langue, "en")
        self.assertIn("Card health", fenetre.page.toPlainText())

    def test_un_lien_ouvre_la_page_de_l_application(self):
        from PyQt6.QtCore import QUrl

        win = self.window()
        win.open_manual("non-destruction")
        fenetre = self._manuel(win)
        fenetre.page.anchorClicked.emit(QUrl("app:Health#Manquants"))
        _pump(150)
        sante = win._pages["Health"]
        self.assertIs(win._stack.currentWidget(), sante)
        self.assertEqual(sante._tabs.tabText(sante._tabs.currentIndex()),
                         "Manquants")

    def test_un_renvoi_deplace_la_lecture(self):
        from PyQt6.QtCore import QUrl

        win = self.window()
        win.open_manual("bienvenue")
        fenetre = self._manuel(win)
        fenetre.page.anchorClicked.emit(QUrl("#non-destruction"))
        _pump(150)
        self.assertEqual(self._chapitre_lu(fenetre), "non-destruction")

    def test_un_clic_dans_le_sommaire_mene_au_chapitre(self):
        from PyQt6.QtTest import QTest

        win = self.window()
        win.open_manual("bienvenue")
        fenetre = self._manuel(win)
        sommaire = fenetre._sommaire
        element = fenetre._elements["glossaire"]
        sommaire.scrollToItem(element)
        _APP.processEvents()
        QTest.mouseClick(sommaire.viewport(), Qt.MouseButton.LeftButton,
                         pos=sommaire.visualItemRect(element).center())
        _pump(150)
        self.assertEqual(self._chapitre_lu(fenetre), "glossaire")

    def test_la_bascule_de_langue_garde_la_place(self):
        win = self.window()
        win.open_manual("sauvegardes")
        fenetre = self._manuel(win)
        self.assertEqual(self._chapitre_lu(fenetre), "sante")
        fenetre._boutons_langue["en"].click()
        _pump(150)
        self.assertEqual(fenetre.manuel.langue, "en")
        self.assertIn("Back up now", fenetre.page.toPlainText())
        self.assertEqual(self._chapitre_lu(fenetre), "sante")
        fenetre._boutons_langue["fr"].click()
        _pump(150)
        self.assertEqual(fenetre.manuel.langue, "fr")
        self.assertEqual(self._chapitre_lu(fenetre), "sante")

    def test_la_recherche_se_tape_et_se_parcourt(self):
        from PyQt6.QtTest import QTest

        win = self.window()
        win.open_manual("bienvenue")
        fenetre = self._manuel(win)
        QTest.keyClicks(fenetre._champ, "copie de travail")
        _pump(400)
        total = len(fenetre._resultats)
        self.assertGreater(total, 10)
        premier = fenetre._rang
        self.assertTrue(fenetre._compte.text().endswith("/ %d" % total))
        QTest.keyClick(fenetre._champ, Qt.Key.Key_Return)
        self.assertEqual(fenetre._rang, (premier + 1) % total)
        fenetre._precedent.click()
        self.assertEqual(fenetre._rang, premier)
        self.assertEqual(len(fenetre.page.extraSelections()), total)

    def test_le_pdf_s_ecrit(self):
        from unittest import mock

        from PyQt6.QtWidgets import QFileDialog

        win = self.window()
        win.open_manual()
        fenetre = self._manuel(win)
        cible = Path(self._tmp.name) / "manuel.pdf"
        with mock.patch.object(QFileDialog, "getSaveFileName",
                               staticmethod(lambda *a, **k: (str(cible),
                                                             ""))):
            fenetre._pdf.click()
        self.assertTrue(cible.is_file())
        self.assertGreater(cible.stat().st_size, 100_000)
        try:
            from PyQt6.QtPdf import QPdfDocument
        except ImportError:             # QtPdf est facultatif
            return
        document = QPdfDocument(None)
        document.load(str(cible))
        # Mesuré à l'écriture : une soixantaine de pages A4.
        self.assertGreater(document.pageCount(), 30)

    def test_le_manuel_se_ferme_avec_l_application(self):
        win = self.window()
        win.open_manual()
        fenetre = self._manuel(win)
        win.close()
        _APP.processEvents()
        self.assertFalse(fenetre.isVisible())


class TestLeManuelDecritChaqueCommande(MainWindowCase):
    """Chaque bouton et chaque case des dix pages est cité dans le manuel,
    sous le libellé qu'il porte à l'écran, dans les deux langues.

    Le pendant de ``TestChaqueCommandeSExplique`` : une commande ajoutée
    sans un mot dans le manuel fait échouer la suite.
    """

    def _libelles_des_pages(self, win) -> dict[str, set[str]]:
        from PyQt6.QtWidgets import QAbstractButton, QTabWidget

        from delugeapp.core import genres

        # Les genres du générateur sont des noms propres, cités en liste.
        exclus = {genres.genre(c).label for c in genres.genre_keys()}
        vus: dict[str, set[str]] = {}
        for cle in list(win._classes):
            win.go_to(cle)
            for _ in range(4):
                _APP.processEvents()
            page = win._pages[cle]
            onglets = page.findChildren(QTabWidget) or [None]
            for groupe in onglets:
                for index in range(groupe.count() if groupe else 1):
                    if groupe is not None:
                        groupe.setCurrentIndex(index)
                        _APP.processEvents()
                    for bouton in page.findChildren(QAbstractButton):
                        libelle = _libelle(bouton).replace("&", "").strip()
                        if (libelle and libelle not in exclus
                                and bouton.isVisibleTo(page)):
                            vus.setdefault(cle, set()).add(libelle)
        return vus

    def _verifier(self, langue: str) -> None:
        from delugeapp.ui import manuel

        cites = manuel.charger(langue).libelles
        win = self.window()
        absents = {cle: sorted(l for l in libelles if l not in cites)
                   for cle, libelles in self._libelles_des_pages(win).items()}
        absents = {cle: l for cle, l in absents.items() if l}
        self.assertEqual(absents, {},
                         "commandes que le manuel %s ne cite pas" % langue)

    def test_en_francais(self):
        self._verifier("fr")

    def test_en_anglais(self):
        from delugeapp import i18n

        i18n.set_language("en")
        self.addCleanup(i18n.set_language, "fr")
        self._verifier("en")


# --------------------------------------------------------------------------- #
# L'Atelier
# --------------------------------------------------------------------------- #

class AtelierCase(PageCase):
    """La page Atelier, sur la carte jetable du test, **en cliquant**.

    Les questions — un nom, un plan, un morceau à choisir — sont remplacées
    le temps du clic ; rien ne part vers une vraie machine.
    """

    def _page(self):
        from delugeapp.ui.pages.atelier import AtelierPage

        page = self.open(AtelierPage)
        self.messages = []
        self.ecrits = []
        page.status.connect(self.messages.append)
        page.songWritten.connect(self.ecrits.append)
        return page

    def _clic(self, bouton):
        self.assertTrue(bouton.isEnabled(), _libelle(bouton))
        with self.assertNoLogs("delugeapp.ui", level="ERROR"):
            bouton.click()
            _APP.processEvents()

    def _onglet(self, page, index):
        page._tabs.setCurrentIndex(index)
        _APP.processEvents()

    def _composer(self, page, genre="techno", basse_midi=False):
        self._clic(page._genre_buttons[genre])
        if basse_midi:
            combo = page._part_kinds["Basse"]
            combo.setCurrentIndex(combo.findData("midi"))
        self._clic(page._compose_button)
        self.assertIsNotNone(page._project)
        return page._project

    def _choisir(self, liste, rang):
        """Un clic sur la ligne ``rang`` d'une liste."""
        from PyQt6.QtCore import QPoint
        from PyQt6.QtTest import QTest

        item = liste.item(rang)
        liste.scrollToItem(item)
        centre = liste.visualItemRect(item).center()
        QTest.mouseClick(liste.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier,
                         QPoint(centre.x(), centre.y()))
        _APP.processEvents()

    def _piste(self, page, partie, liste):
        """Choisit dans ``liste`` la piste qui joue ``partie``."""
        rang = next(i for i, t in enumerate(page._project.tracks)
                    if t.part == partie)
        self._choisir(liste, rang)
        self.assertEqual(page._track().part, partie)
        return page._track()

    def _case(self, page, colonne, rangee):
        """Un clic dans la grille : ``rangee`` -1 pour l'en-tête."""
        from PyQt6.QtCore import QPoint
        from PyQt6.QtTest import QTest

        m = page._matrix
        x = m.LABEL_W + colonne * m.COL_W + m.COL_W // 2
        y = (m.HEAD_H // 2 if rangee < 0
             else m.HEAD_H + rangee * m.ROW_H + m.ROW_H // 2)
        QTest.mouseClick(m, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, QPoint(x, y))
        _APP.processEvents()

    def _ecrire(self, page, nom="Essai"):
        from unittest import mock

        from PyQt6.QtWidgets import QInputDialog, QMessageBox

        with mock.patch.object(QInputDialog, "getText",
                               return_value=(nom, True)), \
                mock.patch.object(QMessageBox, "question",
                                  return_value=QMessageBox.StandardButton.Yes):
            self._clic(page._write_button)
        chemin = self.root / "SONGS" / f"{nom}.XML"
        self.assertTrue(chemin.is_file(), "aucun morceau écrit")
        return chemin

    def _morceaux(self):
        return {p.name for p in (self.root / "SONGS").iterdir()}


class TestLAtelierCompose(AtelierCase):
    """Du style au morceau, dans la page."""

    def test_composer_un_morceau(self):
        page = self._page()
        self.assertFalse(page._write_button.isEnabled())
        self.assertFalse(page._complete_button.isEnabled())
        projet = self._composer(page)
        parties = [p for p, c in page._part_checks.items() if c.isChecked()]
        self.assertEqual([t.part for t in projet.tracks], parties)
        self.assertTrue(all(t.clips for t in projet.tracks))
        self.assertGreaterEqual(len(projet.sections), 4)
        self.assertEqual(projet.style.genre, "techno")
        self.assertTrue(page._write_button.isEnabled())
        self.assertFalse(page._complete_button.isEnabled(),
                         "un morceau neuf ne se complète pas")
        self.assertEqual(page._tabs.currentIndex(), 3)
        self.assertTrue(self.messages[-1].startswith("Morceau composé"))

    def test_sans_partie_cochee_rien_n_est_compose(self):
        page = self._page()
        for case in page._part_checks.values():
            if case.isChecked():
                self._clic(case)
        self._clic(page._compose_button)
        self.assertIsNone(page._project)
        self.assertEqual(self.messages[-1], "Cochez au moins une partie.")

    def test_une_basse_midi_garde_son_canal(self):
        page = self._page()
        page._part_channels["Basse"].setValue(5)
        projet = self._composer(page, basse_midi=True)
        basse = next(t for t in projet.tracks if t.part == "Basse")
        self.assertEqual((basse.kind, basse.channel), ("midi", 5))
        self._onglet(page, 1)
        self._piste(page, "Basse", page._track_list)
        self.assertTrue(page._channel.isVisibleTo(page))
        self.assertEqual(page._channel.value(), 5)

    def test_huit_variantes_et_l_adoption(self):
        page = self._page()
        self._composer(page)
        self._onglet(page, 1)
        piste = self._piste(page, "Accords", page._track_list)
        avant = piste.preset.name
        self.assertFalse(page._adopt_button.isEnabled())
        self._clic(page._variants_button)
        self.assertEqual(page._variant_list.count(), 8)
        self._choisir(page._variant_list, 2)
        self._clic(page._adopt_button)
        self.assertNotEqual(piste.preset.name, avant)
        self.assertEqual(piste.preset.name, page._variants[2].preset.name)
        self.assertTrue(self.messages[-1].startswith("La piste prend le son"))

    def test_ajouter_et_retirer_une_piste(self):
        page = self._page()
        projet = self._composer(page)
        self._onglet(page, 1)
        avant = len(projet.tracks)
        page._new_kind.setCurrentIndex(page._new_kind.findData("cv"))
        self._clic(page._add_track_button)
        self.assertEqual(len(projet.tracks), avant + 1)
        neuve = projet.tracks[-1]
        self.assertEqual(neuve.kind, "cv")
        self.assertIn(neuve.channel, (1, 2))
        self.assertTrue(neuve.clips)
        self._clic(page._remove_track_button)
        self.assertEqual(len(projet.tracks), avant)
        self.assertFalse(any(neuve.uid in s.cells for s in projet.sections))


class TestLAtelierClips(AtelierCase):
    """Les clips et leurs variations."""

    def test_varier_ajoute_un_clip_et_garde_l_original(self):
        page = self._page()
        self._composer(page)
        self._onglet(page, 2)
        piste = self._piste(page, "Basse", page._clip_tracks)
        self._choisir(page._clip_list, 0)
        original = piste.clips[0]
        notes = [(e.start, e.note) for e in original.events]
        avant = len(piste.clips)
        actions = page._vary_menu.actions()
        self.assertEqual(len(actions), 7)
        actions[1].trigger()                 # « notes »
        _APP.processEvents()
        self.assertEqual(len(piste.clips), avant + 1)
        self.assertEqual([(e.start, e.note) for e in original.events], notes)
        self.assertEqual(page._clip_key, piste.clips[-1].key)
        self.assertIn("« notes » de A", self.messages[-1])

    def test_une_cassure_retire_la_grosse_caisse(self):
        page = self._page()
        self._composer(page)
        self._onglet(page, 2)
        piste = self._piste(page, "Batterie", page._clip_tracks)
        self._choisir(page._clip_list, 0)
        self.assertIn("Kick", piste.clips[0].pattern.tracks)
        action = next(a for a in page._vary_menu.actions()
                      if a.text().startswith("Cassure"))
        action.trigger()
        _APP.processEvents()
        self.assertNotIn("Kick", piste.clips[-1].pattern.tracks)

    def test_nouveau_clip_puis_suppression(self):
        page = self._page()
        projet = self._composer(page)
        self._onglet(page, 2)
        piste = self._piste(page, "Mélodie", page._clip_tracks)
        page._clip_bars.setCurrentIndex(page._clip_bars.findData(2))
        self._clic(page._new_clip_button)
        neuf = piste.clips[-1]
        self.assertEqual(neuf.bars, 2)
        self.assertEqual(page._clip_key, neuf.key)
        projet.sections[0].cells[piste.uid] = neuf.key
        self._clic(page._delete_clip_button)
        self.assertNotIn(neuf.key, [c.key for c in piste.clips])
        self.assertNotIn(neuf.key, [s.cells.get(piste.uid)
                                    for s in projet.sections])

    def test_ecouter_sans_sortie_audio_le_dit(self):
        page = self._page()
        self._composer(page)
        self._onglet(page, 2)
        self._piste(page, "Accords", page._clip_tracks)
        self._choisir(page._clip_list, 0)
        self._clic(page._listen_clip_button)
        self.assertTrue(_attendre_les_fils(
            lambda: "Aucune sortie audio disponible." in self.messages))

    def test_jouer_sur_le_deluge_sans_machine(self):
        page = self._page()
        self._composer(page)
        self._onglet(page, 2)
        self._piste(page, "Basse", page._clip_tracks)
        self._choisir(page._clip_list, 0)
        self._clic(page._live_button)
        self.assertFalse(page._live_button.isChecked())
        self.assertTrue(self.messages[-1].startswith(
            "Le Deluge n'est pas connecté"))


class TestLAtelierMorceau(AtelierCase):
    """La grille des sections, et les deux écritures."""

    def test_la_grille_se_clique(self):
        page = self._page()
        projet = self._composer(page)
        self._onglet(page, 3)
        self._case(page, 1, -1)
        self.assertEqual(page._section, 1)
        self.assertEqual(page._section_name.text(),
                         projet.sections[1].name)
        piste = projet.tracks[0]
        cles = [c.key for c in piste.clips] + [None]
        vus = []
        for _ in range(len(cles)):
            self._case(page, 0, 0)
            vus.append(projet.sections[0].cells.get(piste.uid))
        self.assertEqual(sorted(vus, key=str), sorted(cles, key=str),
                         "chaque clip, puis le silence")

    def test_ajouter_deplacer_retirer_une_section(self):
        from unittest import mock

        from PyQt6.QtWidgets import QInputDialog

        page = self._page()
        projet = self._composer(page)
        self._onglet(page, 3)
        self._case(page, 1, -1)
        cases = dict(projet.sections[1].cells)
        avant = len(projet.sections)
        with mock.patch.object(QInputDialog, "getText",
                               return_value=("Pont", True)):
            self._clic(page._add_section_button)
        self.assertEqual(len(projet.sections), avant + 1)
        self.assertEqual((projet.sections[2].name, page._section),
                         ("Pont", 2))
        self.assertEqual(projet.sections[2].cells, cases)
        self._clic(page._right_button)
        self.assertEqual(projet.sections[3].name, "Pont")
        self._clic(page._left_button)
        self._clic(page._left_button)
        self.assertEqual(projet.sections[1].name, "Pont")
        self._clic(page._remove_section_button)
        self.assertEqual(len(projet.sections), avant)
        self.assertNotIn("Pont", [s.name for s in projet.sections])

    def test_structure_du_genre(self):
        page = self._page()
        projet = self._composer(page)
        attendu = [s.name for s in projet.sections]
        self._onglet(page, 3)
        while len(projet.sections) > 1:
            self._clic(page._remove_section_button)
        self._clic(page._structure_button)
        self.assertEqual([s.name for s in projet.sections], attendu)

    def test_ecrire_le_morceau_sur_la_carte(self):
        page = self._page()
        projet = self._composer(page, basse_midi=True)
        chemin = self._ecrire(page)
        song = Song.load(chemin)
        racine = dxml.load(chemin).root
        self.assertEqual(self.ecrits, ["SONGS/Essai.XML"])
        self.assertEqual(len({c.section for c in song.clips}),
                         len([s for s in projet.sections if s.cells]))
        self.assertIsNotNone(racine.find("instruments/midi"),
                             "la basse MIDI n'a pas sa piste")
        self.assertIsNotNone(racine.find("instruments/kit"))
        self.assertTrue(self.lib.search_songs("Essai"))

    def test_partir_d_un_morceau_et_le_completer(self):
        from unittest import mock

        from PyQt6.QtWidgets import QInputDialog, QMessageBox

        page = self._page()
        self._composer(page)
        original = self._ecrire(page).read_bytes()
        avant = self._morceaux()

        with mock.patch.object(QInputDialog, "getItem",
                               return_value=("Essai", True)):
            self._clic(page._import_button)
        projet = page._project
        self.assertEqual(projet.song_rel, "SONGS/Essai.XML")
        self.assertTrue(page._complete_button.isEnabled())
        self.assertTrue(all(t.existing is not None for t in projet.tracks))

        # Une piste neuve, jouée dans une section neuve.
        self._onglet(page, 1)
        page._new_kind.setCurrentIndex(page._new_kind.findData("synth"))
        page._new_part.setCurrentIndex(page._new_part.findData("Arpège"))
        self._clic(page._add_track_button)
        neuve = projet.tracks[-1]
        self._onglet(page, 3)
        self._case(page, len(projet.sections) - 1, -1)
        with mock.patch.object(QInputDialog, "getText",
                               return_value=("Pont", True)):
            self._clic(page._add_section_button)
        colonne = page._section
        projet.sections[colonne].cells.pop(neuve.uid, None)
        self._case(page, colonne, len(projet.tracks) - 1)
        self.assertEqual(projet.sections[colonne].cells.get(neuve.uid),
                         neuve.clips[0].key)

        with mock.patch.object(QMessageBox, "question",
                               return_value=QMessageBox.StandardButton.Yes
                               ) as question:
            self._clic(page._complete_button)
        self.assertIn("reste tel quel", question.call_args.args[2])
        neufs = self._morceaux() - avant
        self.assertEqual(len(neufs), 1, neufs)
        nouveau = self.root / "SONGS" / neufs.pop()
        self.assertEqual((self.root / "SONGS" / "Essai.XML").read_bytes(),
                         original, "l'original a changé")
        avant_song = Song.load(self.root / "SONGS" / "Essai.XML")
        apres_song = Song.load(nouveau)
        self.assertGreater(len(apres_song.clips), len(avant_song.clips))
        self.assertEqual(len(apres_song.instruments),
                         len(avant_song.instruments) + 1)
        self.assertTrue(self.messages[-1].startswith(
            "Nouvelle version écrite"))
        self.assertEqual(self.ecrits[-1], "SONGS/" + nouveau.name)

    def test_refuser_le_plan_ne_complete_rien(self):
        from unittest import mock

        from PyQt6.QtWidgets import QInputDialog, QMessageBox

        page = self._page()
        self._composer(page)
        self._ecrire(page)
        with mock.patch.object(QInputDialog, "getItem",
                               return_value=("Essai", True)):
            self._clic(page._import_button)
        with mock.patch.object(QInputDialog, "getText",
                               return_value=("Pont", True)):
            self._clic(page._add_section_button)
        avant = self._morceaux()
        with mock.patch.object(QMessageBox, "question",
                               return_value=QMessageBox.StandardButton.No):
            self._clic(page._complete_button)
        self.assertEqual(self._morceaux(), avant)
        self.assertEqual(self.messages[-1], "Rien n'a été écrit.")

    def test_un_morceau_du_firmware_officiel_est_refuse(self):
        """``M.XML`` vient du firmware 3.0.4 : l'atelier l'ouvre, mais ne
        le complète pas — et le dit."""
        page = self._page()
        self.assertTrue(page.open_song("SONGS/M.XML"))
        avant = self._morceaux()
        self._clic(page._complete_button)
        self.assertEqual(self._morceaux(), avant)
        self.assertTrue(self.messages[-1].startswith(
            "Morceau impossible à compléter"), self.messages[-1])


class TestLAtelierSurLeDeluge(AtelierCase):
    """[Jouer sur le Deluge], face au Deluge simulé : les notes partent sur
    le canal du lien, et s'arrêtent au second clic."""

    def setUp(self):
        super().setUp()
        from unittest import mock

        from delugeapp.core import midiport

        self.machine = _deluge_simule().DelugeSimule()
        for nom, valeur in (("outputs", lambda: self.machine.devices("out")),
                            ("inputs", lambda: self.machine.devices("in")),
                            ("available", lambda: True)):
            remplacement = mock.patch.object(midiport, nom, valeur)
            remplacement.start()
            self.addCleanup(remplacement.stop)
        self.lien = self.ctx.ensure_link()
        self.machine.brancher(self.lien)
        self.addCleanup(self.lien.disconnect)

    def test_le_clip_part_sur_la_machine_puis_s_arrete(self):
        self.assertTrue(self.lien.connect())
        page = self._page()
        self._composer(page)
        self._onglet(page, 2)
        # La batterie : sa grosse caisse part sur le premier temps.
        self._piste(page, "Batterie", page._clip_tracks)
        self._choisir(page._clip_list, 0)
        sortie = self.machine.sorties[1]
        sortie.envoyes.clear()
        self._clic(page._live_button)
        self.assertTrue(page._live_button.isChecked())
        self.assertIn("à l'arrêt", self.messages[-1])
        _pump(1500)
        notes = [e for e in sortie.envoyes if e[0] == "on"]
        self.assertTrue(notes, "aucune note partie")
        self.assertEqual({e[3] for e in notes}, {self.lien.channel})
        self._clic(page._live_button)
        _pump(100)
        self.assertFalse(page._live_button.isChecked())
        self.assertFalse(self.lien.is_playing)
        self.assertEqual(self.messages[-1],
                         "Le clip ne joue plus sur le Deluge.")


# --------------------------------------------------------------------------- #
# L'éditeur de son
# --------------------------------------------------------------------------- #

def _editeur(son=None, ctx=None):
    from delugeapp.core import synthgen
    from delugeapp.ui.widgets.soundeditor import SoundEditorDialog

    if son is None:
        son = synthgen.generate(synthgen.GenOptions(
            genre="house", role="pad", seed=4)).sound

    class _Ctx:
        player = None
        has_card = False
        sd = None

    dialogue = SoundEditorDialog(ctx or _Ctx(), son)
    dialogue.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    dialogue.show()
    _APP.processEvents()
    return son, dialogue


def _tourner(encodeur, touche, fois=1):
    """Un vrai geste sur un encodeur : les flèches, Début, Fin."""
    from PyQt6.QtTest import QTest

    for _ in range(fois):
        QTest.keyClick(encodeur, touche)
    _APP.processEvents()


class TestEditeurDeSon(WidgetCase):
    """L'éditeur, manipulé comme l'utilisateur : encodeurs au clavier,
    listes, boutons. Il travaille sur une copie."""

    def tearDown(self):
        if getattr(self, "dialogue", None) is not None:
            self.dialogue.close()
        super().tearDown()

    def test_un_cran_change_le_son_et_ce_qu_il_vaut(self):
        son, self.dialogue = _editeur()
        avant = son.display("lpfFrequency")
        editeur = self.dialogue.editor
        editeur.tabs.setCurrentIndex(2)                       # Filtres
        reglage = editeur._controls["lpfFrequency"]
        _tourner(reglage.knob, Qt.Key.Key_End)
        self.assertEqual(reglage.knob.value(), 50)
        self.assertEqual(reglage.caption.text(), "20,2 kHz")
        self.assertEqual(self.dialogue.edited_sound().display("lpfFrequency"),
                         50)
        self.assertEqual(son.display("lpfFrequency"), avant,
                         "l'original a changé")
        self.assertIn("Coupure", self.dialogue.summary.text())
        _tourner(reglage.knob, Qt.Key.Key_Down, 31)
        self.assertEqual(reglage.caption.text(), "237 Hz")

    def test_la_fm_montre_ses_modulateurs_et_eteint_les_filtres(self):
        _son, self.dialogue = _editeur()
        editeur = self.dialogue.editor
        self.assertTrue(editeur._controls["modulator1Amount"].isHidden())
        moteur = editeur._controls["mode"].combo
        moteur.setCurrentIndex(moteur.findData("fm"))
        _APP.processEvents()
        self.assertFalse(editeur._controls["modulator1Amount"].isHidden())
        self.assertTrue(editeur._controls["osc1.type"].isHidden())
        self.assertEqual(self.dialogue.edited_sound().lpf_mode, "Off")
        self.assertEqual(editeur._controls["lpf_mode"].combo.currentData(),
                         "Off")

    def test_ajouter_regler_et_retirer_une_modulation(self):
        _son, self.dialogue = _editeur()
        editeur = self.dialogue.editor
        editeur.tabs.setCurrentIndex(6)
        avant = len(editeur._cable_rows)
        editeur.add_cable_button.click()
        _APP.processEvents()
        self.assertEqual(len(editeur._cable_rows), avant + 1)
        ligne = editeur._cable_rows[-1]
        ligne["destination"].setCurrentIndex(
            ligne["destination"].findData("pitch"))
        ligne["depth"].setValue(5)
        _APP.processEvents()
        self.assertEqual(ligne["effect"].text(), "±0,34 demi-ton")
        cable = self.dialogue.edited_sound().patch_cables[-1]
        self.assertEqual((cable.destination, cable.display()), ("pitch", 5))
        ligne["remove"].click()
        _APP.processEvents()
        self.assertEqual(len(editeur._cable_rows), avant)

    def test_revenir_au_son_de_depart(self):
        son, self.dialogue = _editeur()
        reglage = self.dialogue.editor._controls["volume"]
        _tourner(reglage.knob, Qt.Key.Key_Home)
        self.assertEqual(self.dialogue.edited_sound().display("volume"), 0)
        self.dialogue.reset_button.click()
        _APP.processEvents()
        self.assertEqual(self.dialogue.edited_sound().display("volume"),
                         son.display("volume"))
        self.assertEqual(reglage.knob.value(), son.display("volume"))
        self.assertEqual(self.dialogue.changes(), [])

    def test_garder_ou_annuler(self):
        from PyQt6.QtWidgets import QDialog

        _son, self.dialogue = _editeur()
        self.dialogue.keep_button.click()
        self.assertEqual(self.dialogue.result(), QDialog.DialogCode.Accepted)
        _son, autre = _editeur()
        autre.cancel_button.click()
        self.assertEqual(autre.result(), QDialog.DialogCode.Rejected)
        autre.close()

    def test_ecouter_sans_sortie_audio_le_dit(self):
        _son, self.dialogue = _editeur()
        self.dialogue.listen_button.click()
        self.assertEqual(self.dialogue.summary.text(),
                         "Aucune sortie audio disponible.")


def _exec_avec_retouche(dialogue):
    """Remplace ``exec`` : l'utilisateur ouvre le filtre à fond, garde."""
    from PyQt6.QtWidgets import QDialog

    dialogue.editor.tabs.setCurrentIndex(2)
    _tourner(dialogue.editor._controls["lpfFrequency"].knob, Qt.Key.Key_End)
    dialogue.keep_button.click()
    return QDialog.DialogCode.Accepted


class TestEditeurDansLesPages(AtelierCase):
    """[Modifier le son…] dans l'Atelier et le Générateur."""

    def test_l_atelier_retouche_le_son_d_une_piste(self):
        from unittest import mock

        from delugeapp.ui.widgets.soundeditor import SoundEditorDialog

        page = self._page()
        self._composer(page)
        self._onglet(page, 1)
        piste = self._piste(page, "Accords", page._track_list)
        self.assertTrue(page._edit_sound_button.isEnabled())
        with mock.patch.object(SoundEditorDialog, "exec",
                               _exec_avec_retouche):
            self._clic(page._edit_sound_button)
        self.assertTrue(piste.edited)
        self.assertEqual(piste.preset.sound.display("lpfFrequency"), 50)
        self.assertIn("Retouché à la main", page._sound_text.text())
        self.assertTrue(self.messages[-1].startswith("Son retouché"))
        # Le morceau écrit porte la retouche.
        from delugeapp.core.fixedpoint import to_display as _to_display

        chemin = self._ecrire(page)
        racine = dxml.load(chemin).root
        clip = next(c for c in racine.find("sessionClips")
                    if c.get("instrumentPresetName") == piste.preset.name)
        self.assertEqual(_to_display(
            clip.find("soundParams").get("lpfFrequency")), 50)

    def test_les_variantes_gardent_la_retouche(self):
        """Les huit variantes d'un son retouché portent la retouche ; celles
        proposées avant elle s'effacent."""
        from unittest import mock

        from delugeapp.core import atelier, soundedit, synthgen
        from delugeapp.ui.widgets.soundeditor import SoundEditorDialog

        page = self._page()
        self._composer(page)
        self._onglet(page, 1)
        piste = self._piste(page, "Accords", page._track_list)
        self._clic(page._variants_button)
        self.assertEqual(len(page._variants), 8)
        with mock.patch.object(SoundEditorDialog, "exec",
                               _exec_avec_retouche):
            self._clic(page._edit_sound_button)
        self.assertEqual(page._variants, [])
        self.assertFalse(page._adopt_button.isEnabled())
        self.assertIn("gardent vos retouches", page._sound_text.text())
        self._clic(page._variants_button)
        self.assertEqual(len(page._variants), 8)
        self.assertIn("avec vos retouches", self.messages[-1])
        genere = atelier._generate(piste.options).sound
        for v in page._variants:
            with self.subTest(variante=v.label):
                ecart = soundedit.value(synthgen.generate(v.options).sound,
                                        "lpfFrequency") \
                    - soundedit.value(genere, "lpfFrequency")
                # Coupure ouverte à fond, déplacée de ce que la variante
                # change.
                self.assertEqual(v.preset.sound.display("lpfFrequency"),
                                 max(0, min(50, 50 + ecart)))
        self._choisir(page._variant_list, 3)
        self._clic(page._adopt_button)
        self.assertIs(piste.preset, page._variants[3].preset)
        self.assertTrue(piste.edited)
        self.assertIn("gardent vos retouches", page._sound_text.text())

    def test_annuler_ne_touche_a_rien(self):
        from unittest import mock

        from PyQt6.QtWidgets import QDialog

        from delugeapp.ui.widgets.soundeditor import SoundEditorDialog

        def regler_puis_annuler(dialogue):
            _tourner(dialogue.editor._controls["volume"].knob,
                     Qt.Key.Key_Home)
            dialogue.cancel_button.click()
            return QDialog.DialogCode.Rejected

        page = self._page()
        self._composer(page)
        self._onglet(page, 1)
        piste = self._piste(page, "Accords", page._track_list)
        avant = piste.preset
        volume = avant.sound.display("volume")
        with mock.patch.object(SoundEditorDialog, "exec",
                               regler_puis_annuler):
            self._clic(page._edit_sound_button)
        self.assertIs(piste.preset, avant)
        self.assertEqual(piste.preset.sound.display("volume"), volume)
        self.assertFalse(piste.edited)

    def test_une_piste_midi_ne_se_retouche_pas(self):
        page = self._page()
        self._composer(page, basse_midi=True)
        self._onglet(page, 1)
        self._piste(page, "Basse", page._track_list)
        self.assertFalse(page._edit_sound_button.isEnabled())

    def test_le_generateur_retouche_son_son(self):
        from unittest import mock

        from delugeapp.ui.pages.generator import GeneratorPage
        from delugeapp.ui.widgets.soundeditor import SoundEditorDialog

        page = self.open(GeneratorPage)
        messages = []
        page.status.connect(messages.append)
        self._clic(_bouton(page, "Générer"))
        historique = len(page._history)
        with mock.patch.object(SoundEditorDialog, "exec",
                               _exec_avec_retouche):
            self._clic(page._edit_button)
        self.assertEqual(len(page._history), historique + 1)
        self.assertEqual(page._preset.sound.display("lpfFrequency"), 50)
        self.assertTrue(messages[-1].startswith("Son retouché"))
