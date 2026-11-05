# -*- coding: utf-8 -*-
"""Page « DAW » : le pont entre le Deluge et un logiciel de musique.

Trois sens, au choix de l'utilisateur :

* **Vers le DAW** — un morceau de la carte devient un dossier que tout DAW
  ouvre : fichier MIDI, projet DAWproject (Bitwig, Studio One, Cubase),
  projet Reaper, pistes audio rendues sur l'ordinateur ou exportées par la
  machine (:mod:`delugeapp.core.daw`) ;
* **Depuis le DAW** — un fichier MIDI, un set Ableton Live, un DAWproject ou
  un projet Reaper devient un **nouveau** morceau du Deluge, chaque piste en
  synthé, en kit ou en piste MIDI, au choix (:mod:`delugeapp.core.dawimport`) ;
* **Jouer ensemble** — une copie d'un morceau où chaque piste écoute son
  canal MIDI, pour que le DAW joue les sons du Deluge en direct
  (:mod:`delugeapp.core.dawlive`).

Rien n'écrit dans un morceau existant : l'export va dans un dossier neuf du
PC, l'import et la copie dans des fichiers neufs de ``SONGS``, après le plan
et l'accord de l'utilisateur.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...i18n import N_, decimal, tr
from ..theme import PAD
from ..widgets.common import Card, SearchBar
from .base import Page, avance, tool_button

log = logging.getLogger(__name__)

#: Saut de ligne, nommé pour que les messages en format % restent lisibles.
_NL = chr(10)

#: Les formats proposés, et ce qu'ils servent.
_FORMATS = (
    ("als", N_("Ableton Live — un set .als prêt à ouvrir")),
    ("midi", N_("MIDI — tous les DAW")),
    ("dawproject", N_("DAWproject — Bitwig Studio, Studio One, Cubase")),
    ("rpp", N_("Reaper")),
)

#: Les DAW dont le mode d'emploi du direct est écrit pas à pas.
_DAWS = (("ableton", N_("Ableton Live")), ("autre", N_("Un autre DAW")))

#: Hauteur d'une ligne de tableau qui porte une liste déroulante : à la
#: hauteur par défaut, la liste débordait sur la ligne suivante (vu sur le
#: rendu à 980 px).
_ROW = 34


def _scrolled(widget: QWidget) -> QScrollArea:
    """Une colonne qui défile au lieu d'écraser ses cartes : à 980 × 640, le
    mode d'emploi du direct s'arrêtait à sa troisième étape sur cinq."""
    zone = QScrollArea()
    zone.setWidgetResizable(True)
    zone.setFrameShape(QFrame.Shape.NoFrame)
    zone.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    zone.setWidget(widget)
    return zone


def _table(colonnes: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(colonnes))
    table.setHorizontalHeaderLabels(colonnes)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(_ROW)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    return table


class _SongList(QWidget):
    """Les morceaux de la carte, filtrés par une recherche."""

    def __init__(self, page: Page, search_name: str) -> None:
        super().__init__(page)
        self._page = page
        colonne = QVBoxLayout(self)
        colonne.setContentsMargins(0, 0, 0, 0)
        colonne.setSpacing(6)
        self.search = SearchBar(tr("Rechercher un morceau…"))
        self.search.setObjectName(search_name)
        colonne.addWidget(self.search)
        self.list = QListWidget()
        self.list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        colonne.addWidget(self.list, 1)
        self.search.searchChanged.connect(page.guard(lambda _t: self.reload()))

    def reload(self) -> None:
        courant = self.current()
        try:
            rows = self._page.lib.search_songs(self.search.text().strip())
        except Exception:  # noqa: BLE001 - simple liste
            log.exception("liste des morceaux illisible")
            rows = []
        self.list.blockSignals(True)
        self.list.clear()
        for row in rows:
            item = QListWidgetItem(row["name"] or Path(row["rel"]).stem)
            item.setData(Qt.ItemDataRole.UserRole, row["rel"])
            self.list.addItem(item)
            if row["rel"] == courant:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)

    def current(self) -> str:
        item = self.list.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole) or "") if item else ""

    def select(self, rel: str) -> bool:
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == rel:
                self.list.setCurrentItem(item)
                return True
        return False


class DawPage(Page):
    """Le Deluge et le DAW, dans les deux sens et ensemble."""

    TITLE = N_("DAW")
    ICON = "link"
    #: Les pistes audio pour le DAW se calculent comme l'écoute.
    LISTENS = True
    EMPTY_DETAIL = N_("Indiquez l'emplacement de votre carte dans les "
                      "réglages. Ses morceaux pourront alors partir vers "
                      "votre DAW, et vos projets en revenir.")

    navigateRequested = pyqtSignal(str)

    def __init__(self, ctx, parent=None) -> None:
        super().__init__(ctx, parent)
        self._to_song = None
        self._to_rel = ""
        self._machine_audio: list[Path] = []
        self._import_song = None
        self._import_path: Path | None = None
        self._routes: list = []
        self._live_rel = ""
        self._follow: set[int] = set()
        self._last_folder: Path | None = None

    # -- construction ------------------------------------------------------- #

    def build(self) -> None:
        outer = QVBoxLayout(self.content())
        outer.setContentsMargins(PAD, PAD, PAD, PAD)
        outer.setSpacing(8)
        header, actions = self.header(
            tr("DAW"), tr("Le pont entre le Deluge et votre logiciel de "
                          "musique, dans les deux sens"))
        outer.addWidget(header)
        self._reveal_button = tool_button(tr("Dans l'explorateur"), "folder")
        self._reveal_button.clicked.connect(self.guard(self._reveal))
        actions.addWidget(self._reveal_button)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_to_daw(), tr("Vers le DAW"))
        self._tabs.addTab(self._build_from_daw(), tr("Depuis le DAW"))
        self._tabs.addTab(self._build_live(), tr("Jouer ensemble"))
        outer.addWidget(self._tabs, 1)

    def _build_to_daw(self) -> QWidget:
        host = QSplitter(Qt.Orientation.Horizontal)
        self._to_list = _SongList(self, "to_daw_search")
        self._to_search = self._to_list.search
        self._to_list.list.currentItemChanged.connect(
            self.guard(lambda *_a: self._to_selected()))
        gauche = Card(tr("Morceaux"))
        gauche.body().addWidget(self._to_list)
        host.addWidget(gauche)

        droite = QWidget()
        colonne = QVBoxLayout(droite)
        colonne.setContentsMargins(0, 0, 0, 0)
        colonne.setSpacing(8)

        fiche = Card(tr("Le morceau, tel que le DAW le recevra"))
        self._to_info = QLabel(tr("Choisissez un morceau à gauche."))
        self._to_info.setWordWrap(True)
        self._to_info.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        fiche.body().addWidget(self._to_info)
        colonne.addWidget(fiche)

        dossier = Card(tr("Ce que contient le dossier"))
        self._formats: dict[str, QCheckBox] = {}
        for cle, libelle in _FORMATS:
            case = QCheckBox(tr(libelle))
            case.setChecked(True)
            dossier.body().addWidget(case)
            self._formats[cle] = case
        self._fmt_als = self._formats["als"]
        self._fmt_midi = self._formats["midi"]
        self._fmt_dawproject = self._formats["dawproject"]
        self._fmt_rpp = self._formats["rpp"]
        self._live_note = QLabel()
        self._live_note.setWordWrap(True)
        self._live_note.setProperty("role", "subtitle")
        self._live_note.setVisible(False)
        dossier.body().addWidget(self._live_note)
        self._check_live()
        self._stems_machine = QCheckBox(tr("Joindre l'export de pistes du "
                                           "Deluge"))
        self._stems_machine.setChecked(True)
        dossier.body().addWidget(self._stems_machine)
        self._stems_pc = avance(QCheckBox(tr("Rendre chaque piste sur "
                                             "l'ordinateur")))
        dossier.body().addWidget(self._stems_pc)
        self._stems_note = QLabel()
        self._stems_note.setWordWrap(True)
        self._stems_note.setProperty("role", "subtitle")
        dossier.body().addWidget(self._stems_note)
        rang = QHBoxLayout()
        rang.addStretch(1)
        self._export_button = tool_button(tr("Exporter pour le DAW…"),
                                          "export", primary=True)
        self._export_button.clicked.connect(self.guard(self._export))
        rang.addWidget(self._export_button)
        dossier.body().addLayout(rang)
        colonne.addWidget(dossier)
        colonne.addStretch(1)
        host.addWidget(_scrolled(droite))
        host.setSizes([300, 700])
        return host

    def _build_from_daw(self) -> QWidget:
        host = QWidget()
        colonne = QVBoxLayout(host)
        colonne.setContentsMargins(0, 0, 0, 0)
        colonne.setSpacing(8)

        rang = QHBoxLayout()
        self._open_project_button = tool_button(tr("Ouvrir un projet…"),
                                                "import")
        self._open_project_button.clicked.connect(
            self.guard(self._open_project))
        rang.addWidget(self._open_project_button)
        self._project_info = QLabel(tr(
            "Un fichier MIDI, un set Ableton Live (.als), un DAWproject ou un "
            "projet Reaper (.rpp)."))
        self._project_info.setWordWrap(True)
        rang.addWidget(self._project_info, 1)
        colonne.addLayout(rang)

        pistes = Card(tr("Ce que devient chaque piste"))
        self._import_table = _table([tr("Piste"), tr("Notes"),
                                     tr("Devient")])
        entete = self._import_table.horizontalHeader()
        entete.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        entete.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        entete.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        pistes.body().addWidget(self._import_table)
        colonne.addWidget(pistes, 1)

        options = QHBoxLayout()
        options.addWidget(QLabel(tr("Sections :")))
        self._import_source = QComboBox()
        self._import_source.addItem(tr("l'arrangement"), "arrangement")
        self._import_source.addItem(tr("les scènes"), "scenes")
        options.addWidget(self._import_source)
        self._import_bars = avance(QComboBox())
        for mesures in (4, 8, 16):
            self._import_bars.addItem(tr("tranches de %d mesures") % mesures,
                                      mesures)
        self._import_bars.setCurrentIndex(1)
        options.addWidget(self._import_bars)
        self._import_genre = avance(QComboBox())
        from ...core import genres

        for cle in genres.genre_keys():
            self._import_genre.addItem(genres.genre(cle).label, cle)
        indice = self._import_genre.findData("techno")
        if indice >= 0:
            self._import_genre.setCurrentIndex(indice)
        options.addWidget(self._import_genre)
        for liste in (self._import_source, self._import_bars,
                      self._import_genre):
            liste.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToContents)
        options.addStretch(1)
        self._import_button = tool_button(tr("Écrire le morceau…"), "song",
                                          primary=True)
        self._import_button.clicked.connect(self.guard(self._import))
        options.addWidget(self._import_button)
        colonne.addLayout(options)
        return host

    def _build_live(self) -> QWidget:
        host = QSplitter(Qt.Orientation.Horizontal)
        self._live_list = _SongList(self, "live_search")
        self._live_search = self._live_list.search
        self._live_list.list.currentItemChanged.connect(
            self.guard(lambda *_a: self._live_selected()))
        gauche = Card(tr("Morceaux"))
        gauche.body().addWidget(self._live_list)
        host.addWidget(gauche)

        droite = QWidget()
        colonne = QVBoxLayout(droite)
        colonne.setContentsMargins(0, 0, 0, 0)
        colonne.setSpacing(8)

        canaux = Card(tr("Le canal que chaque piste écoute"))
        self._live_table = _table([tr("Piste"), tr("Nature"), tr("Canal")])
        entete = self._live_table.horizontalHeader()
        entete.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        entete.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        # À la largeur de son titre, la liste ne montrait plus son chiffre.
        entete.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._live_table.setColumnWidth(2, 96)
        self._live_table.setMinimumHeight(6 * _ROW)
        canaux.body().addWidget(self._live_table)
        self._keep_existing = QCheckBox(tr("Garder les canaux déjà réglés"))
        self._keep_existing.setChecked(True)
        self._keep_existing.toggled.connect(
            self.guard(lambda _c: self._live_selected()))
        canaux.body().addWidget(self._keep_existing)
        self._follow_note = QLabel()
        self._follow_note.setWordWrap(True)
        self._follow_note.setProperty("role", "subtitle")
        canaux.body().addWidget(self._follow_note)
        rang = QHBoxLayout()
        rang.addStretch(1)
        self._live_button = tool_button(tr("Écrire la copie…"), "midi",
                                        primary=True)
        self._live_button.clicked.connect(self.guard(self._write_live))
        rang.addWidget(self._live_button)
        canaux.body().addLayout(rang)
        colonne.addWidget(canaux)

        guide = Card(tr("Ensuite, sur le Deluge et dans le DAW"))
        self._daw_choice = QComboBox()
        for cle, libelle in _DAWS:
            self._daw_choice.addItem(tr(libelle), cle)
        self._daw_choice.currentIndexChanged.connect(
            self.guard(lambda _i: self._show_steps()))
        guide.body().addWidget(self._daw_choice)
        self._steps = QLabel()
        self._steps.setWordWrap(True)
        self._steps.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        guide.body().addWidget(self._steps)
        colonne.addWidget(guide)
        colonne.addStretch(1)
        host.addWidget(_scrolled(droite))
        host.setSizes([300, 700])
        self._show_steps()
        return host

    # -- rafraîchissement --------------------------------------------------- #

    def _refresh(self) -> None:
        self._to_list.reload()
        self._live_list.reload()

    def reveal_item(self, rel: str) -> bool:
        """``Daw#SONGS/X.XML`` : le morceau, choisi dans les deux listes."""
        trouve = self._to_list.select(rel)
        self._live_list.select(rel)
        return trouve

    # -- vers le DAW -------------------------------------------------------- #

    def _check_live(self) -> None:
        """Le set Ableton se bâtit avec les fichiers du Live installé : sans
        Live sur le PC, la case est grisée et dit pourquoi."""
        from ...core import dawals

        probleme, live = "", None
        try:
            probleme = dawals.template_problem()
            live = dawals.find_live()
        except Exception as exc:  # noqa: BLE001 - simple vérification
            probleme = str(exc)
        self._fmt_als.setEnabled(not probleme)
        self._fmt_als.setChecked(not probleme)
        if probleme:
            self._fmt_als.setToolTip(probleme)
        if not probleme and live is not None and live.edition:
            # Le set suit l'édition de Live : dire ce qu'elle accepte.
            pistes = (str(live.max_tracks) if live.max_tracks is not None
                      else tr("toutes les"))
            scenes = (str(live.max_scenes) if live.max_scenes is not None
                      else tr("toutes les"))
            self._live_note.setText(tr(
                "Votre Live : %s %s — %s pistes et %s scènes dans le set ; les "
                "pistes de notes passent d'abord, ce qui dépasse reste dans le "
                "dossier.") % (live.version, live.edition, pistes, scenes)
                if live.limited else
                tr("Votre Live : %s %s — pistes et scènes sans limite.")
                % (live.version, live.edition))
            self._live_note.setVisible(True)

    def _to_selected(self) -> None:
        from ...core import daw

        rel = self._to_list.current()
        self._to_rel = rel
        self._to_song = None
        self._machine_audio = []
        if not rel or self.sd is None:
            self._to_info.setText(tr("Choisissez un morceau à gauche."))
            return
        try:
            song = daw.from_deluge(self.sd.abs(rel))
        except Exception as exc:  # noqa: BLE001 - morceau abîmé
            log.debug("morceau illisible %s : %s", rel, exc)
            self._to_info.setText(tr("Morceau illisible : %s") % exc)
            return
        self._to_song = song
        notes = sum(len(c.notes) for t in song.tracks for c in t.clips)
        self._to_info.setText(
            tr("%s BPM · %d piste(s) · %d clip(s) · %d notes · %d section(s) "
               "· %d mesures") % (
                decimal(song.bpm, 1), len(song.tracks),
                sum(len(t.clips) for t in song.tracks), notes,
                len(song.scenes),
                int(round(song.length / max(1, song.numerator))))
            + _NL + (tr("L'arrangement est celui du morceau.")
                     if song.arranged else
                     tr("L'arrangement est déduit des sections, jouées dans "
                        "l'ordre.")))
        self._machine_audio = daw.machine_stems(self.sd, Path(rel).stem)
        self._stems_machine.setEnabled(bool(self._machine_audio))
        if self._machine_audio:
            self._stems_note.setText(
                tr("%d piste(s) exportée(s) par le Deluge, dans %s.")
                % (len(self._machine_audio),
                   self._machine_audio[0].parent.name))
        else:
            self._stems_note.setText(tr(
                "Pas d'export de pistes du Deluge pour ce morceau : sur la "
                "machine, SELECT ▸ Export Audio ▸ Export Tracks, puis "
                "rapatriez la carte."))

    def _export(self) -> None:
        from PyQt6.QtWidgets import QFileDialog

        if self._to_song is None or self.sd is None:
            self.say(tr("Choisissez d'abord un morceau."))
            return
        formats = tuple(c for c, case in self._formats.items()
                        if case.isChecked() and case.isEnabled())
        if not formats:
            self.say(tr("Cochez au moins un format."))
            return
        depart = str(self._last_folder.parent if self._last_folder
                     else Path.home())
        dossier = QFileDialog.getExistingDirectory(
            self, tr("Où écrire le dossier pour le DAW ?"), depart)
        if not dossier:
            return
        machine = (list(self._machine_audio)
                   if self._stems_machine.isChecked()
                   and self._stems_machine.isEnabled() else [])
        rendre = self._stems_pc.isChecked() and not self._stems_pc.isHidden()
        self.say(tr("Export de %s…") % Path(self._to_rel).stem)
        self.run(self._do_export, self.sd, self._to_rel, Path(dossier),
                 formats, rendre, machine,
                 on_result=self.guard(self._export_done),
                 on_error=self.guard(
                     lambda m: self.say(tr("Échec : %s") % m)),
                 title=tr("Export pour le DAW"), modal=rendre)

    @staticmethod
    def _do_export(sd, rel, dest, formats, rendre, machine, progress=None,
                   should_stop=None):
        import tempfile

        from ...core import daw

        # Relu ici : le rendu renseigne les pistes, la fiche affichée ne
        # doit pas en hériter.
        song = daw.from_deluge(sd.abs(rel))
        with tempfile.TemporaryDirectory(prefix="deluge-daw-") as tmp:
            if rendre:
                def avance_(fait, total, nom):
                    if progress is not None:
                        progress(tr("Rendu de %s (%d/%d)")
                                 % (nom, fait + 1, total) if nom
                                 else tr("Rendu terminé"))
                daw.render_stems(song, sd, Path(tmp), progress=avance_,
                                 should_stop=should_stop)
            return daw.write_folder(song, dest, formats=formats,
                                    machine_audio=machine)

    def _export_done(self, result) -> None:
        from PyQt6.QtWidgets import QMessageBox

        if not result:
            return
        self._last_folder = Path(result["folder"])
        texte = tr("Dossier écrit : %s") % result["folder"]
        texte += _NL + _NL + _NL.join(result["files"][:16])
        if len(result["files"]) > 16:
            texte += _NL + tr("… et %d autre(s)") % (len(result["files"]) - 16)
        if result["skipped"]:
            texte += _NL + _NL + _NL.join(result["skipped"])
        QMessageBox.information(self, tr("Export pour le DAW"), texte)
        self.say(tr("%d fichier(s) dans %s — le lisez-moi dit comment "
                    "l'ouvrir dans chaque DAW.")
                 % (len(result["files"]), Path(result["folder"]).name))

    def _reveal(self) -> None:
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices

        if self._last_folder is not None and self._last_folder.exists():
            cible = self._last_folder
        elif self._import_path is not None:
            cible = self._import_path.parent
        else:
            self.say(tr("Rien à montrer : exportez un morceau ou ouvrez un "
                        "projet d'abord."))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(cible)))

    # -- depuis le DAW ------------------------------------------------------ #

    def _open_project(self) -> None:
        from PyQt6.QtWidgets import QFileDialog

        depart = str(self._import_path.parent if self._import_path
                     else Path.home())
        chemin, _f = QFileDialog.getOpenFileName(
            self, tr("Ouvrir un projet de DAW"), depart,
            tr("Projets de DAW (*.mid *.midi *.als *.dawproject *.rpp)"))
        if chemin:
            self.load_project(Path(chemin))

    def load_project(self, path: Path) -> bool:
        """Lit un projet de DAW et propose ce que devient chaque piste."""
        from ...core import dawimport

        try:
            song = dawimport.read_project(path)
        except ValueError as exc:
            self.say(tr("Projet illisible : %s") % exc)
            return False
        self._import_song = song
        self._import_path = Path(path)
        self._project_info.setText(
            tr("%s — %s BPM, %d piste(s) de notes, %d scène(s), %d repère(s)")
            % (Path(path).name, decimal(song.bpm, 1), len(song.tracks),
               len(song.scenes), len(song.markers)))
        avec_scenes = bool(song.scenes)
        self._import_source.setEnabled(avec_scenes and song.arranged)
        self._import_source.setCurrentIndex(
            1 if dawimport.uses_scenes(song) else 0)
        self._fill_import(dawimport.default_choices(song))
        if not song.tracks:
            self.say(tr("Ce projet n'a aucune piste de notes."))
        return True

    def _choice_items(self, track) -> list[tuple[str, tuple]]:
        from ...core import genres

        items = [(tr("Synthé — %s") % genres.role_label(role),
                  ("synth", role)) for role in genres.ROLES]
        items.append((tr("Kit de batterie"), ("kit", "drums")))
        items.append((tr("Piste MIDI, canal %d") % (track.channel + 1),
                      ("midi", "")))
        items.append((tr("Laisser de côté"), ("skip", "")))
        return items

    def _fill_import(self, choices) -> None:
        song = self._import_song
        self._import_table.setRowCount(0)
        if song is None:
            return
        for track, choice in zip(song.tracks, choices):
            rang = self._import_table.rowCount()
            self._import_table.insertRow(rang)
            self._import_table.setItem(rang, 0, QTableWidgetItem(track.name))
            notes = sum(len(c.notes) for c in track.clips)
            item = QTableWidgetItem(str(notes))
            item.setTextAlignment(int(Qt.AlignmentFlag.AlignRight
                                      | Qt.AlignmentFlag.AlignVCenter))
            self._import_table.setItem(rang, 1, item)
            combo = QComboBox()
            combo.setToolTip(tr("Ce que devient cette piste dans le Deluge : "
                                "un synthé au son généré pour son rôle, un "
                                "kit monté d'après ses notes General MIDI, "
                                "une piste MIDI vers un appareil extérieur, "
                                "ou rien"))
            for libelle, donnee in self._choice_items(track):
                combo.addItem(libelle, donnee)
            voulu = (choice.kind, choice.role if choice.kind == "synth"
                     else ("drums" if choice.kind == "kit" else ""))
            for i in range(combo.count()):
                if tuple(combo.itemData(i)) == voulu:
                    combo.setCurrentIndex(i)
                    break
            self._import_table.setCellWidget(rang, 2, combo)

    def import_choices(self) -> list:
        """Les choix de la table, piste par piste."""
        from ...core import dawimport

        out = []
        song = self._import_song
        for rang in range(self._import_table.rowCount()):
            combo = self._import_table.cellWidget(rang, 2)
            kind, role = tuple(combo.currentData()) if combo is not None \
                else ("skip", "")
            canal = song.tracks[rang].channel + 1 if song is not None else 1
            out.append(dawimport.ImportChoice(kind=kind, role=role or "lead",
                                              channel=canal))
        return out

    def _import(self) -> None:
        from ...core import dawimport

        song = self._import_song
        if song is None:
            self.say(tr("Ouvrez d'abord un projet de DAW."))
            return
        choix = self.import_choices()
        source = (self._import_source.currentData()
                  if self._import_source.isEnabled() else "auto")
        mesures = int(self._import_bars.currentData() or 8)
        genre = str(self._import_genre.currentData() or "techno")

        def construire(carte):
            return dawimport.build_song(song, choix, name=song.name,
                                        sd=carte, lib=self.lib, genre=genre,
                                        bars=mesures, source=source)

        self.write_song(construire, song.name)

    # -- jouer ensemble ----------------------------------------------------- #

    def _live_selected(self) -> None:
        from ...core import dawlive, midifollow

        rel = self._live_list.current()
        self._live_rel = rel
        self._routes = []
        self._live_table.setRowCount(0)
        if not rel or self.sd is None:
            return
        try:
            routes = dawlive.read_routes(self.sd, rel)
        except Exception as exc:  # noqa: BLE001 - morceau abîmé
            self.say(tr("Morceau illisible : %s") % exc)
            return
        reglages = midifollow.read_settings(self.sd)
        self._follow = {c - 1 for c in (
            getattr(reglages, "channel_a", None),
            getattr(reglages, "channel_b", None),
            getattr(reglages, "channel_c", None)) if c}
        dawlive.propose_channels(routes, avoid=self._follow,
                                 keep_existing=self._keep_existing.isChecked())
        self._routes = routes
        # Toutes les pistes visibles, dix au plus, sans défiler.
        self._live_table.setMinimumHeight(
            max(3, min(len(routes), 10)) * _ROW + 40)
        natures = {"synth": tr("synthé"), "kit": tr("kit"), "midi": "MIDI",
                   "cv": "CV", "audio": tr("audio")}
        for route in routes:
            rang = self._live_table.rowCount()
            self._live_table.insertRow(rang)
            self._live_table.setItem(rang, 0, QTableWidgetItem(route.name))
            self._live_table.setItem(rang, 1, QTableWidgetItem(
                natures.get(route.kind, route.kind)))
            if not route.can_listen:
                self._live_table.setItem(rang, 2, QTableWidgetItem("—"))
                continue
            combo = QComboBox()
            combo.setToolTip(tr("Le canal MIDI sur lequel le DAW joue cette "
                                "piste ; un kit joue chaque son sur sa note "
                                "General MIDI"))
            if route.existing is None:
                combo.addItem("—", None)
            for canal in range(16):
                combo.addItem(str(canal + 1), canal)
            indice = combo.findData(route.listens)
            combo.setCurrentIndex(max(0, indice))
            self._live_table.setCellWidget(rang, 2, combo)
        if self._follow:
            self._follow_note.setText(
                tr("MIDI Follow écoute le canal %s sur votre Deluge : les "
                   "canaux proposés l'évitent.")
                % ", ".join(str(c + 1) for c in sorted(self._follow)))
        else:
            self._follow_note.setText("")

    def _show_steps(self) -> None:
        from ...core import dawlive

        cle = self._daw_choice.currentData() or "ableton"
        self._steps.setText(_NL.join("%d. %s" % (i, etape) for i, etape in
                                     enumerate(dawlive.setup_steps(cle), 1)))

    def _routes_from_table(self) -> list:
        for rang, route in enumerate(self._routes):
            combo = self._live_table.cellWidget(rang, 2)
            if combo is None or not route.can_listen:
                continue
            voulu = combo.currentData()
            route.channel = (None if voulu is None or voulu == route.existing
                             else int(voulu))
            if route.kind == "kit" and voulu is not None \
                    and voulu == route.existing and not route.whole_kit \
                    and any(d[2] is None for d in route.drums):
                route.channel = int(voulu)
        return self._routes

    def _write_live(self) -> None:
        from PyQt6.QtWidgets import QMessageBox

        from ...core import dawlive

        if not self._live_rel or not self._routes:
            self.say(tr("Choisissez d'abord un morceau."))
            return
        carte = self.writable_card()
        if carte is None:
            return
        plan = dawlive.plan_live(carte, self._live_rel,
                                 self._routes_from_table(),
                                 follow=self._follow)
        if not plan.ok:
            self.say(tr("Copie impossible : %s.") % plan.error)
            return
        if getattr(self.ctx.settings, "confirm_writes", True):
            reponse = QMessageBox.question(
                self, tr("Écrire la copie"),
                plan.text() + _NL + _NL + tr(
                    "Écrire cette copie sur la carte ? Le morceau d'origine "
                    "n'est pas touché."),
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes)
            if reponse != QMessageBox.StandardButton.Yes:
                self.say(tr("Rien n'a été écrit."))
                return
        fait = dawlive.write_live(carte, plan, apply=True)
        if not fait.applied:
            self.say(tr("Copie non écrite : %s.") % fait.error)
            return
        try:
            from ...core.scan import index_songs

            index_songs(carte, self.lib, [carte.abs(fait.rel)])
        except Exception:  # noqa: BLE001 - l'index se rattrapera
            log.exception("indexation de la copie impossible")
        self.songWritten.emit(fait.rel)
        self.say(tr("Copie écrite : %s. Chargez-la sur le Deluge, puis "
                    "réglez le DAW comme indiqué.") % fait.rel)
        self._live_list.reload()
