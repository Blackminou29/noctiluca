# -*- coding: utf-8 -*-
"""Page « Kits ».

Un kit du Deluge est une liste de rangées, chacune tenant un échantillon et
ses réglages. Ce qui compte ici, c'est de voir **quelles rangées sont
cassées** : un kit dont trois pads ne jouent rien est frustrant sur scène, et
le Deluge ne le signale pas.

La table des kits réutilise :class:`~delugeapp.ui.pages.synths.SynthsPage`
pour la liste, mais le panneau de détail est propre aux kits.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSplitter,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.fixedpoint import to_display
from ...i18n import N_, tr, tr_stored
from ..theme import PAD, PAD_GREEN, PAD_RED
from ..widgets.common import (
    Card,
    ElidedLabel,
    RowTableModel,
    SearchBar,
    configure_table,
    human_size,
    sorted_proxy,
)
from ..widgets.padgrid import StepSequencer
from .base import Page, tool_button

log = logging.getLogger(__name__)


class KitsPage(Page):
    """Kits de batterie."""

    TITLE = N_("Kits")
    EMPTY_DETAIL = N_("Indiquez l'emplacement de votre carte dans les "
                      "réglages. Vous verrez ici les rangées de chaque kit, "
                      "les sons qu'elles utilisent et celles qui sont "
                      "cassées.")
    ICON = "kit"
    #: Aide du séquenceur d'essai, quand le motif a bien des rangées.
    AIDE_MOTIF = N_("Cliquez les pads pour composer un motif, puis écoutez "
                    "le kit ou exportez le motif en MIDI.")

    kitChosen = pyqtSignal(str)

    def __init__(self, ctx, parent=None) -> None:
        super().__init__(ctx, parent)
        self._model: RowTableModel | None = None
        self._proxy = None
        self._kit = None
        self._current = ""
        self._pattern = None

    # -- construction ------------------------------------------------------- #

    def build(self) -> None:
        outer = QVBoxLayout(self.content())
        outer.setContentsMargins(PAD, PAD, PAD, PAD)
        outer.setSpacing(8)

        header, actions = self.header(
            tr("Kits"), tr("Rangées, échantillons et rangées cassées"))
        outer.addWidget(header)

        listen = tool_button(tr("Écouter la rangée"), "play", primary=True)
        listen.clicked.connect(self.guard(self._listen_row))
        actions.addWidget(listen)

        listen_all = tool_button(tr("Écouter le kit"), "wave")
        listen_all.clicked.connect(self.guard(self._listen_kit))
        actions.addWidget(listen_all)

        stop = tool_button(tr("Arrêter"), "stop")
        stop.clicked.connect(self.guard(self._stop))
        actions.addWidget(stop)

        export = tool_button(tr("Motif en MIDI"), "export",
                             tr("Exporter le motif d'essai en fichier MIDI"))
        export.clicked.connect(self.guard(self._export_midi))
        actions.addWidget(export)

        song = tool_button(tr("Motif en morceau"), "song")
        song.clicked.connect(self.guard(self._song_from_motif))
        actions.addWidget(song)

        row = QHBoxLayout()
        self._search = SearchBar(tr("Rechercher un kit…"))
        self._search.searchChanged.connect(self.guard(lambda _t: self._reload()))
        row.addWidget(self._search, 1)
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
        splitter.setSizes([500, 710])
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 5)
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
        host = QWidget()
        column = QVBoxLayout(host)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(8)

        head = Card("")
        self._name = ElidedLabel(tr("Aucun kit sélectionné"))
        self._name.setProperty("role", "title")
        head.body().addWidget(self._name)
        self._path = ElidedLabel("")
        self._path.setProperty("role", "mono")
        head.body().addWidget(self._path)
        self._summary = QLabel("")
        self._summary.setWordWrap(True)
        head.body().addWidget(self._summary)
        column.addWidget(head)

        rows_card = Card(tr("Rangées"))
        self._rows = QTableWidget(0, 6)
        self._rows.setHorizontalHeaderLabels(
            [tr("Rangée"), tr("Échantillon"), tr("Présent"), tr("Volume"),
             tr("Decay"), tr("Polyphonie")])
        self._rows.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self._rows.verticalHeader().setVisible(False)
        self._rows.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._rows.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self._rows.itemSelectionChanged.connect(
            self.guard(self._on_row_selected))
        rows_card.body().addWidget(self._rows)
        column.addWidget(rows_card, 2)

        seq_card = Card(tr("Motif d'essai"))
        self._seq_hint = QLabel(tr(self.AIDE_MOTIF))
        self._seq_hint.setProperty("role", "subtitle")
        self._seq_hint.setWordWrap(True)
        seq_card.body().addWidget(self._seq_hint)

        genre_row = QHBoxLayout()
        genre_label = QLabel(tr("Motif de départ"))
        genre_label.setProperty("role", "subtitle")
        genre_row.addWidget(genre_label)
        self._genre = QComboBox()
        from ...core import genres as genres_mod

        for key in genres_mod.genre_keys():
            self._genre.addItem(genres_mod.genre(key).label, key)
        self._genre.activated.connect(self.guard(lambda _i: self._load_beat()))
        genre_row.addWidget(self._genre, 1)
        seq_card.body().addLayout(genre_row)

        self._sequencer = StepSequencer()
        self._sequencer.setMinimumHeight(110)
        seq_card.body().addWidget(self._sequencer)
        column.addWidget(seq_card, 1)
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

        # Quatre colonnes au lieu de cinq : le panneau de gauche sert à
        # **choisir** un kit, celui de droite à le lire. « Firmware »
        # poussait les autres hors du cadre, sous une barre de défilement
        # horizontale.
        return [
            (tr("Nom"), get("name"), 190, left),
            (tr("Dossier"), dossier, 100, left),
            # « 16 rangées », gardé en français dans l'index.
            (tr("Rangées"), get("summary"), 90, left,
             lambda v: "—" if v is None else tr_stored(str(v))),
            (tr("Taille"), get("size"), 80, right, human_size),
        ]

    # -- chargement --------------------------------------------------------- #

    def _reload(self) -> None:
        try:
            rows = self.lib.search_presets(
                kind="kit", text=self._search.text().strip(), limit=100000)
        except Exception:  # noqa: BLE001
            log.exception("recherche de kits en échec")
            rows = []

        if self._model is None:
            self._model = RowTableModel(self._columns(), rows, self)
            self._proxy = sorted_proxy(self._model, self)
            self._table.setModel(self._proxy)
            configure_table(self._table, self._model)
            selection = self._table.selectionModel()
            if selection is not None:
                selection.selectionChanged.connect(
                    self.guard(lambda *_a: self._on_kit_selected()))
        else:
            self._model.set_rows(rows)
        self._count.setText(tr("%d kit(s)") % len(rows))

    def _on_kit_selected(self) -> None:
        if self._model is None or self._proxy is None:
            return
        selection = self._table.selectionModel()
        if selection is None:
            return
        indexes = selection.selectedRows()
        if not indexes:
            return
        row = self._model.row_at(self._proxy.mapToSource(indexes[0]).row())
        if row is None:
            return
        rel = row["rel"] if "rel" in row.keys() else ""
        self._current = rel
        self.kitChosen.emit(rel)
        self._load_kit(rel)

    def _load_kit(self, rel: str) -> None:
        """Charge le kit et remplit la table des rangées."""
        from ...core.model import Kit

        self._name.setText(Path(rel).stem or "—")
        self._path.setText(rel)
        if self.sd is None:
            return
        try:
            self._kit = Kit.load(self.sd.abs(rel))
        except Exception as exc:  # noqa: BLE001
            log.debug("kit illisible %s : %s", rel, exc)
            self._kit = None
            self._summary.setText(tr("Fichier illisible : %s") % exc)
            self._rows.setRowCount(0)
            return

        kit = self._kit
        self._rows.setRowCount(0)
        broken = 0
        for row in kit.rows:
            index = self._rows.rowCount()
            self._rows.insertRow(index)
            self._rows.setItem(index, 0, QTableWidgetItem(row.name or "—"))

            ref = row.file_name or ""
            # Le nom du fichier suffit : les huit rangées d'un kit viennent
            # presque toujours du même dossier, et répéter
            # « SAMPLES/ARTISTS/Phil Elverum/ » huit fois pousse le nom hors
            # de la colonne. Le chemin entier reste dans l'infobulle.
            court = ref.replace("\\", "/").rsplit("/", 1)[-1]
            file_item = QTableWidgetItem(court
                                         or tr("— aucun échantillon —"))
            file_item.setToolTip(ref)
            self._rows.setItem(index, 1, file_item)

            if not ref:
                present, label = False, tr("vide")
            else:
                present = self.sd.resolve_sample(ref) is not None
                label = tr("oui") if present else tr("ABSENT")
            if not present:
                broken += 1
            state = QTableWidgetItem(label)
            state.setForeground(Qt.GlobalColor.green if present
                                else Qt.GlobalColor.red)
            self._rows.setItem(index, 2, state)

            sound = row.sound
            self._rows.setItem(index, 3,
                               QTableWidgetItem(str(sound.display("volume"))))
            self._rows.setItem(
                index, 4, QTableWidgetItem(str(to_display(sound.env1.decay))))
            self._rows.setItem(index, 5,
                               QTableWidgetItem(sound.polyphonic or "—"))

        total = len(kit.rows)
        if broken:
            self._summary.setText(
                tr("%d rangée(s), dont %d sans échantillon jouable — ces "
                   "pads resteront muets sur la machine.") % (total, broken))
            self._summary.setStyleSheet(f"color: {PAD_RED};")
        else:
            self._summary.setText(
                tr("%d rangée(s), toutes jouables.") % total)
            self._summary.setStyleSheet(f"color: {PAD_GREEN};")

        self._load_beat()

    def _load_beat(self) -> None:
        """Charge un motif idiomatique, limité aux rangées du kit."""
        if self._kit is None:
            return
        from ...core import rhythm

        genre = self._genre.currentData() or "techno"
        pattern = rhythm.genre_beat(genre, bars=1, seed=1, fills=False)

        # On ne garde que les pistes qui correspondent à une rangée du kit :
        # un motif qui déclenche des rangées absentes ne produirait rien.
        available = {row.name.upper() for row in self._kit.rows}
        pattern.tracks = {name: steps
                          for name, steps in pattern.tracks.items()
                          if name.upper() in available}
        if not pattern.tracks:
            # Aucune correspondance de nom : on retombe sur les premières
            # rangées du kit, pour que l'essai soit possible malgré tout.
            #
            # Et on **le dit** : une grille entièrement éteinte sous un
            # motif choisi ressemble à une panne. Beaucoup de kits de la
            # carte sont mélodiques (CHOR, GONG, GUIT…) et ne portent aucun
            # nom de batterie ; le motif n'a alors rien à déclencher.
            names = [row.name for row in self._kit.rows[:4]]
            pattern.tracks = {name: [] for name in names}
            self._seq_hint.setText(
                tr("Aucune rangée de ce kit ne porte un nom de batterie "
                   "(KICK, SNARE, HAT…) : le motif « %s » n'a rien à "
                   "déclencher ici. La grille part vide sur les premières "
                   "rangées — cliquez les pads pour composer le vôtre.")
                % self._genre.currentText())
        else:
            self._seq_hint.setText(tr(self.AIDE_MOTIF))
        self._pattern = pattern
        self._sequencer.set_pattern(pattern)

    def _on_row_selected(self) -> None:
        if self.ctx.settings.autoplay:
            self._listen_row()

    # -- écoute ------------------------------------------------------------- #

    def _selected_kit_row(self):
        if self._kit is None:
            return None
        index = self._rows.currentRow()
        if not 0 <= index < len(self._kit.rows):
            return None
        return self._kit.rows[index]

    def _listen_row(self) -> None:
        row = self._selected_kit_row()
        if row is None:
            self.say(tr("Choisissez une rangée."))
            return
        self.say(tr("Rendu de « %s »…") % row.name)
        self.run(self._render_row, row.sound,
                 on_result=self.guard(self._play),
                 on_error=self.guard(
                     lambda m: self.say(tr("Rendu impossible : %s") % m)),
                 title=tr("Rendu de la rangée"))

    def _render_row(self, sound):
        from ...core import render

        return render.render_sound(sound, note=60, seconds=1.4, sr=44100,
                                   gate=0.5, sd=self.sd)

    def _listen_kit(self) -> None:
        if self._kit is None:
            self.say(tr("Aucun kit sélectionné."))
            return
        if self._jouer_sur_le_deluge():
            return
        self.say(tr("Rendu du kit…"))
        self.run(self._render_kit, self._kit, self._pattern,
                 on_result=self.guard(self._play),
                 on_error=self.guard(
                     lambda m: self.say(tr("Rendu impossible : %s") % m)),
                 title=tr("Rendu du kit"))

    def _jouer_sur_le_deluge(self) -> bool:
        """Envoie le motif d'essai à la machine, si elle est branchée.

        **Les notes des rangées sont une hypothèse.** Sur le Deluge, les
        rangées d'un kit répondent à des notes consécutives, mais la note de
        départ dépend du réglage de la machine : faute de Deluge sous la
        main pour le mesurer, on part de C1 (note 36) pour la première
        rangée, ce qui est le cas le plus courant. Si les mauvais sons
        partent, c'est ici qu'il faudra corriger — et le dire dans
        REPRISE.md plutôt que de laisser deviner.
        """
        if not getattr(self.ctx.settings, "midi_audition", False):
            return False
        lien = getattr(self.ctx, "link", None)
        if lien is None or not lien.is_connected or self._pattern is None:
            return False
        rangees = {row.name: 36 + index
                   for index, row in enumerate(self._kit.rows)}
        if not lien.play_pattern(self._pattern, bpm=128, row_notes=rangees,
                                 repeats=2):
            return False
        self.say(tr("Motif joué sur le Deluge (canal %d, rangées à partir "
                    "de C1).") % lien.channel)
        return True

    def _render_kit(self, kit, pattern):
        from ...core import render

        return render.render_kit(kit, pattern=pattern, bpm=128, sr=44100,
                                 sd=self.sd)

    def _play(self, audio) -> None:
        if audio is None or self.player is None:
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

    # -- export ------------------------------------------------------------- #

    def _export_midi(self) -> None:
        """Exporte le motif d'essai en fichier MIDI."""
        pattern = self._sequencer.pattern()
        if pattern is None or not any(pattern.tracks.values()):
            self.say(tr("Composez d'abord un motif."))
            return

        from PyQt6.QtWidgets import QFileDialog

        from ...core import midifile

        default = "%s.mid" % (Path(self._current).stem or tr("motif"))
        chosen, _filter = QFileDialog.getSaveFileName(
            self, tr("Exporter le motif en MIDI"), default,
            tr("Fichier MIDI (*.mid)"))
        if not chosen:
            return
        try:
            midifile.pattern_to_midi(Path(chosen), pattern, None, 128)
        except Exception as exc:  # noqa: BLE001
            log.exception("export MIDI impossible")
            self.say(tr("Export impossible : %s") % exc)
            return
        self.say(tr("Motif exporté : %s") % Path(chosen).name)

    # -- morceau du Deluge -------------------------------------------------- #

    def _song_from_motif(self) -> None:
        """Le motif d'essai, joué par ce kit, en morceau du Deluge.

        Le kit est repris **tel qu'il est sur la carte**, et non tel que
        l'application le comprend : les conversions que la machine ferait en
        le chargeant (kit ancien, bornes en millisecondes…) sont appliquées
        par :func:`delugeapp.core.songwriter.kit_track`.
        """
        pattern = self._sequencer.pattern()
        if pattern is None or not any(pattern.tracks.values()):
            self.say(tr("Composez d'abord un motif."))
            return
        if self._kit is None or not self._current:
            self.say(tr("Choisissez d'abord un kit."))
            return
        rel = self._current
        model = self._kit

        def build(card):
            from ...core import dxml, songwriter

            doc = dxml.load(card.abs(rel))
            root = doc.root if doc.root.tag == "kit" else doc.root.find("kit")
            if root is None:
                raise ValueError(tr("ce fichier ne contient pas de kit"))
            rows = songwriter.drum_rows(pattern.tracks, model)
            dossier = str(Path(rel).parent).replace("\\", "/")
            return songwriter.pattern_song(
                pattern, root, rows, name="", bpm=128, version=doc.firmware,
                kit_name=Path(rel).stem,
                folder=dossier if dossier not in ("", ".") else "KITS",
                sd=card)

        self.write_song(build, tr("%s motif") % Path(rel).stem)


    # -- rafraîchissement --------------------------------------------------- #

    def _refresh(self) -> None:
        self._reload()
