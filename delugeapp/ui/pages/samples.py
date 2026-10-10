# -*- coding: utf-8 -*-
"""Page « Échantillons ».

La page la plus fréquentée : parcourir, écouter, trier et ranger la
bibliothèque. Sur la carte d'essai elle affiche 1 741 lignes, d'où deux
contraintes tenues ici :

* **table en modèle/vue** (:class:`~delugeapp.ui.widgets.common.RowTableModel`
  et un ``QSortFilterProxyModel``), jamais un ``QTableWidget`` — la SPEC §6.5
  l'interdit à ce volume ;
* **recherche différée** de 250 ms, sinon chaque frappe relancerait une
  requête sur toute la bibliothèque.

Les actions qui modifient la carte passent toutes par un plan de
:mod:`delugeapp.core.organize` montré avant application : rien n'est déplacé
ni supprimé sans que l'utilisateur ait vu la liste exacte des opérations.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QSplitter,
    QTableView,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core import wav
from ..theme import GOLD, GREY, PAD, PAD_GREEN, PAD_RED, category_color
from ..widgets.common import (
    Card,
    ElidedLabel,
    KeyValueTable,
    RowTableModel,
    SearchBar,
    StarRating,
    TagChip,
    configure_table,
    human_duration,
    human_size,
    sorted_proxy,
)
from ..widgets.waveform import WaveformView
from .base import Page, page_header, tool_button

log = logging.getLogger(__name__)

#: Filtres de durée proposés, en secondes.
DURATION_FILTERS: tuple[tuple[str, float, float], ...] = (
    ("Toutes durées", 0.0, 0.0),
    ("Très court (< 0,5 s)", 0.0, 0.5),
    ("Court (0,5 à 2 s)", 0.5, 2.0),
    ("Moyen (2 à 10 s)", 2.0, 10.0),
    ("Long (plus de 10 s)", 10.0, 0.0),
)

#: Nombre de pics calculés pour l'aperçu.
PEAK_BUCKETS = 1400


class SamplesPage(Page):
    """Bibliothèque d'échantillons."""

    TITLE = "Échantillons"
    ICON = "samples"

    #: Un échantillon a été choisi : utile aux autres pages (générateur).
    sampleChosen = pyqtSignal(str)

    def __init__(self, ctx, parent=None) -> None:
        super().__init__(ctx, parent)
        self._model: RowTableModel | None = None
        self._proxy = None
        self._current: str = ""
        self._folder = ""

    # -- construction ------------------------------------------------------- #

    def build(self) -> None:
        outer = QVBoxLayout(self.content())
        outer.setContentsMargins(PAD, PAD, PAD, PAD)
        outer.setSpacing(8)

        header, actions = page_header(
            "Échantillons", "Parcourir, écouter et ranger la bibliothèque")
        outer.addWidget(header)

        self._play_button = tool_button("Écouter", "play", primary=True)
        self._play_button.clicked.connect(self.guard(self._play))
        actions.addWidget(self._play_button)

        stop = tool_button("Arrêter", "stop")
        stop.clicked.connect(self.guard(self._stop))
        actions.addWidget(stop)

        reveal = tool_button("Dans l'explorateur", "folder",
                             "Ouvrir le dossier contenant le fichier")
        reveal.clicked.connect(self.guard(self._reveal))
        actions.addWidget(reveal)

        outer.addWidget(self._build_filters())

        splitter = QSplitter(Qt.Orientation.Horizontal, self.content())
        splitter.addWidget(self._build_tree())
        right = QSplitter(Qt.Orientation.Vertical)
        right.addWidget(self._build_table())
        right.addWidget(self._build_preview())
        right.setStretchFactor(0, 3)
        right.setStretchFactor(1, 2)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        outer.addWidget(splitter, 1)

        self._count = QLabel()
        self._count.setProperty("role", "subtitle")
        outer.addWidget(self._count)

    def _build_filters(self) -> QWidget:
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        self._search = SearchBar("Rechercher un échantillon…")
        self._search.searchChanged.connect(self.guard(lambda _t: self._reload()))
        row.addWidget(self._search, 2)

        self._category = QComboBox()
        self._category.addItem("Toutes catégories", "")
        self._category.activated.connect(self.guard(lambda _i: self._reload()))
        row.addWidget(self._category, 1)

        self._duration = QComboBox()
        for label, low, high in DURATION_FILTERS:
            self._duration.addItem(label, (low, high))
        self._duration.activated.connect(self.guard(lambda _i: self._reload()))
        row.addWidget(self._duration, 1)

        self._only_unused = QCheckBox("Inutilisés")
        self._only_unused.setToolTip(
            "Échantillons qu'aucun preset, kit ni morceau ne cite")
        self._only_unused.toggled.connect(self.guard(lambda _c: self._reload()))
        row.addWidget(self._only_unused)

        self._only_fav = QCheckBox("Favoris")
        self._only_fav.toggled.connect(self.guard(lambda _c: self._reload()))
        row.addWidget(self._only_fav)

        self._only_missing = QCheckBox("Manquants")
        self._only_missing.setToolTip(
            "Fichiers réclamés par un preset mais absents de la carte")
        self._only_missing.toggled.connect(
            self.guard(lambda _c: self._reload()))
        row.addWidget(self._only_missing)
        return host

    def _build_tree(self) -> QWidget:
        card = Card("Dossiers")
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setMinimumWidth(190)
        self._tree.itemSelectionChanged.connect(
            self.guard(self._on_folder_selected))
        card.body().addWidget(self._tree)
        return card

    def _build_table(self) -> QWidget:
        card = Card("")
        self._table = QTableView()
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        card.body().addWidget(self._table)
        return card

    def _build_preview(self) -> QWidget:
        card = Card("Aperçu")
        body = card.body()

        self._name = ElidedLabel("Aucun échantillon sélectionné")
        self._name.setProperty("role", "title")
        body.addWidget(self._name)

        self._path = ElidedLabel("")
        self._path.setProperty("role", "mono")
        body.addWidget(self._path)

        self._wave = WaveformView()
        self._wave.setMinimumHeight(90)
        self._wave.positionClicked.connect(self.guard(self._play_from))
        body.addWidget(self._wave, 1)

        row = QHBoxLayout()
        self._info = KeyValueTable()
        self._info.setMaximumHeight(150)
        row.addWidget(self._info, 2)

        side = QVBoxLayout()
        side.setSpacing(6)

        stars_row = QHBoxLayout()
        stars_label = QLabel("Note")
        stars_label.setProperty("role", "subtitle")
        stars_row.addWidget(stars_label)
        self._stars = StarRating(0)
        self._stars.changed.connect(self.guard(self._set_stars))
        stars_row.addWidget(self._stars)
        stars_row.addStretch(1)
        side.addLayout(stars_row)

        self._fav = QCheckBox("Favori")
        self._fav.toggled.connect(self.guard(self._set_favorite))
        side.addWidget(self._fav)

        tags_label = QLabel("Étiquettes")
        tags_label.setProperty("role", "subtitle")
        side.addWidget(tags_label)
        self._tags_row = QHBoxLayout()
        self._tags_row.setSpacing(4)
        tags_host = QWidget()
        tags_host.setLayout(self._tags_row)
        side.addWidget(tags_host)

        self._usage = QLabel("")
        self._usage.setProperty("role", "subtitle")
        self._usage.setWordWrap(True)
        side.addWidget(self._usage)
        side.addStretch(1)

        side_host = QWidget()
        side_host.setLayout(side)
        row.addWidget(side_host, 1)
        body.addLayout(row)
        return card

    # -- colonnes ----------------------------------------------------------- #

    def _columns(self) -> list:
        """Colonnes de la table.

        L'extracteur rend la **valeur brute** et le formateur l'habille : la
        colonne se trie alors numériquement (cf. ``RowTableModel``).
        """
        left = Qt.AlignmentFlag.AlignLeft
        right = Qt.AlignmentFlag.AlignRight

        def get(key, default=None):
            return lambda row: (row[key] if key in row.keys() else default)

        return [
            ("Nom", get("name"), 220, left),
            ("Dossier", get("folder"), 230, left),
            ("Catégorie", get("category"), 110, left),
            ("Durée", get("duration"), 80, right, human_duration),
            ("Hz", get("sr"), 70, right,
             lambda v: f"{int(v):,}".replace(",", " ") if v else "—"),
            ("Bits", get("bit_depth"), 55, right),
            ("Can.", get("channels"), 50, right,
             lambda v: {1: "mono", 2: "stéréo"}.get(v, str(v or "—"))),
            ("Taille", get("size"), 90, right, human_size),
            ("BPM", get("bpm"), 65, right,
             lambda v: f"{v:.0f}" if v else "—"),
            ("Tonalité", get("key"), 75, left),
            ("Usages", get("used_count"), 70, right),
        ]

    # -- chargement --------------------------------------------------------- #

    def _reload(self) -> None:
        """Interroge l'index et remplit la table."""
        low, high = self._duration.currentData() or (0.0, 0.0)
        try:
            rows = self.lib.search_samples(
                text=self._search.text().strip(),
                folder=self._folder,
                category=self._category.currentData() or "",
                min_dur=low, max_dur=high,
                only_unused=self._only_unused.isChecked(),
                only_missing=self._only_missing.isChecked(),
                favorite=self._only_fav.isChecked(),
                limit=100000)
        except Exception:  # noqa: BLE001
            log.exception("recherche d'échantillons en échec")
            rows = []

        if self._model is None:
            self._model = RowTableModel(self._columns(), rows, self)
            self._proxy = sorted_proxy(self._model, self)
            self._table.setModel(self._proxy)
            configure_table(self._table, self._model)
            self._table.horizontalHeader().setSectionResizeMode(
                1, QHeaderView.ResizeMode.Stretch)
            selection = self._table.selectionModel()
            if selection is not None:
                selection.selectionChanged.connect(
                    self.guard(lambda *_a: self._on_row_selected()))
        else:
            self._model.set_rows(rows)

        total = len(rows)
        suffix = ""
        if self._only_missing.isChecked():
            suffix = " — fichiers réclamés par un preset mais absents"
        self._count.setText(f"{total} échantillon(s) affiché(s){suffix}")

    def _fill_tree(self) -> None:
        """Arbre des dossiers, construit depuis les chemins indexés."""
        self._tree.blockSignals(True)
        self._tree.clear()

        root = QTreeWidgetItem(["Tous les échantillons"])
        root.setData(0, Qt.ItemDataRole.UserRole, "")
        self._tree.addTopLevelItem(root)

        try:
            folders = self.lib.folders("sample")
        except Exception as exc:  # noqa: BLE001
            log.debug("dossiers indisponibles : %s", exc)
            folders = []

        nodes: dict[str, QTreeWidgetItem] = {"": root}
        for name, count in sorted(folders):
            parts = [p for p in str(name).split("/") if p]
            path = ""
            parent = root
            for part in parts:
                path = f"{path}/{part}" if path else part
                node = nodes.get(path)
                if node is None:
                    node = QTreeWidgetItem([part])
                    node.setData(0, Qt.ItemDataRole.UserRole, path)
                    parent.addChild(node)
                    nodes[path] = node
                parent = node
            # Le compte s'affiche sur la feuille.
            parent.setText(0, f"{parts[-1] if parts else name}  ({count})")

        root.setExpanded(True)
        self._tree.setCurrentItem(root)
        self._tree.blockSignals(False)

    def _on_folder_selected(self) -> None:
        item = self._tree.currentItem()
        self._folder = (item.data(0, Qt.ItemDataRole.UserRole) or ""
                        if item is not None else "")
        self._reload()

    # -- sélection ---------------------------------------------------------- #

    def _selected_rows(self) -> list:
        """Lignes brutes sélectionnées."""
        if self._model is None or self._proxy is None:
            return []
        out = []
        selection = self._table.selectionModel()
        if selection is None:
            return []
        for index in selection.selectedRows():
            row = self._model.row_at(self._proxy.mapToSource(index).row())
            if row is not None:
                out.append(row)
        return out

    def _on_row_selected(self) -> None:
        rows = self._selected_rows()
        if not rows:
            return
        row = rows[0]
        rel = row["rel"] if "rel" in row.keys() else ""
        self._show(rel, row)
        if self.ctx.settings.autoplay:
            self._play()

    def _show(self, rel: str, row) -> None:
        """Remplit le panneau d'aperçu."""
        self._current = rel
        self._name.setText(Path(rel).stem or "—")
        self._path.setText(rel)
        self.sampleChosen.emit(rel)

        path = self.sd.resolve_sample(rel) if self.sd is not None else None
        if path is None:
            self._wave.clear()
            self._info.set_rows([("Fichier", "introuvable sur la carte")])
            self._usage.setText("")
            return

        info = wav.probe(path)
        if info.ok:
            try:
                self._wave.set_peaks(wav.peaks(path, buckets=PEAK_BUCKETS),
                                     info.duration, info.sample_rate)
            except Exception as exc:  # noqa: BLE001
                log.debug("enveloppe illisible pour %s : %s", rel, exc)
                self._wave.clear()
        else:
            self._wave.clear()

        details: list[tuple[str, object]] = [
            ("Durée", human_duration(info.duration) if info.ok else "—"),
            ("Fréquence", f"{info.sample_rate} Hz" if info.ok else "—"),
            ("Résolution", f"{info.bit_depth} bits" if info.ok else "—"),
            ("Canaux", {1: "mono", 2: "stéréo"}.get(info.channels,
                                                    str(info.channels))
             if info.ok else "—"),
            ("Taille", human_size(row["size"] if "size" in row.keys() else 0)),
            ("Format", info.fmt if info.ok else "—"),
        ]
        if not info.ok and info.error:
            details.append(("Erreur", info.error))
        for key in ("bpm", "key", "category"):
            if key in row.keys() and row[key]:
                label = {"bpm": "Tempo", "key": "Tonalité",
                         "category": "Catégorie"}[key]
                value = (f"{row[key]:.0f} BPM" if key == "bpm"
                         else row[key])
                details.append((label, value))
        self._info.set_rows(details)

        # Notation et étiquettes.
        try:
            rating = self.lib.get_rating("sample", rel)
        except Exception:  # noqa: BLE001
            rating = {"stars": 0, "favorite": 0}
        self._stars.set_value(int(rating.get("stars", 0)))
        self._fav.blockSignals(True)
        self._fav.setChecked(bool(rating.get("favorite")))
        self._fav.blockSignals(False)
        self._fill_tags(rel)

        count = row["used_count"] if "used_count" in row.keys() else 0
        if count:
            self._usage.setText(f"Utilisé par {count} fichier(s).")
        else:
            self._usage.setText("Utilisé par aucun fichier de la carte.")

    def _fill_tags(self, rel: str) -> None:
        while self._tags_row.count():
            item = self._tags_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        try:
            tags = self.lib.tags_of("sample", rel)
        except Exception:  # noqa: BLE001
            tags = []
        for name in tags:
            chip = TagChip(name, category_color(name))
            chip.removed.connect(self.guard(self._remove_tag))
            self._tags_row.addWidget(chip)
        self._tags_row.addStretch(1)

    # -- actions ------------------------------------------------------------ #

    def _play(self) -> None:
        if not self._current or self.player is None or self.sd is None:
            return
        path = self.sd.resolve_sample(self._current)
        if path is None:
            self.say("Fichier introuvable.")
            return
        try:
            self.player.set_volume(self.ctx.settings.preview_volume)
            self.player.play_file(path)
        except Exception as exc:  # noqa: BLE001 - audio indisponible
            log.debug("lecture impossible : %s", exc)
            self.say(f"Lecture impossible : {exc}")

    def _play_from(self, _seconds: float) -> None:
        """Le moteur d'aperçu ne sait pas démarrer à une position donnée."""
        self._play()

    def _stop(self) -> None:
        if self.player is not None:
            try:
                self.player.stop()
            except Exception as exc:  # noqa: BLE001
                log.debug("arrêt impossible : %s", exc)

    def _reveal(self) -> None:
        if not self._current or self.sd is None:
            return
        path = self.sd.resolve_sample(self._current)
        if path is None:
            self.say("Fichier introuvable.")
            return
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def _set_stars(self, value: int) -> None:
        if not self._current:
            return
        self.lib.set_rating("sample", self._current, stars=int(value))
        self.say(f"Note : {value}/5")

    def _set_favorite(self, checked: bool) -> None:
        if not self._current:
            return
        self.lib.set_rating("sample", self._current, favorite=bool(checked))

    def _remove_tag(self, name: str) -> None:
        if not self._current:
            return
        self.lib.remove_tag("sample", self._current, name)
        self._fill_tags(self._current)

    def add_tag(self, name: str) -> None:
        """Ajoute une étiquette à l'échantillon courant."""
        if not self._current or not name.strip():
            return
        self.lib.add_tag("sample", self._current, name.strip(),
                         category_color(name.strip()))
        self._fill_tags(self._current)

    # -- rafraîchissement --------------------------------------------------- #

    def _refresh(self) -> None:
        self._fill_categories()
        self._fill_tree()
        self._reload()

    def _fill_categories(self) -> None:
        current = self._category.currentData() or ""
        self._category.blockSignals(True)
        self._category.clear()
        self._category.addItem("Toutes catégories", "")
        try:
            for name, count in self.lib.categories("sample"):
                self._category.addItem(f"{name} ({count})", name)
        except Exception as exc:  # noqa: BLE001
            log.debug("catégories indisponibles : %s", exc)
        index = self._category.findData(current)
        self._category.setCurrentIndex(max(0, index))
        self._category.blockSignals(False)
