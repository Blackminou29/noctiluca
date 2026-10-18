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
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QSlider,
    QSpinBox,
    QSplitter,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...core import samplefix, similarity, slicer, wav
from ..theme import GREY, PAD, category_color
from ..widgets.common import (
    clear_layout,
    Card,
    ElidedLabel,
    KeyValueTable,
    RowTableModel,
    SearchBar,
    StarRating,
    PlanDialog,
    TagChip,
    configure_table,
    human_duration,
    human_size,
    sorted_proxy,
)
from ..widgets.waveform import WaveformView
from .base import Page, tool_button

log = logging.getLogger(__name__)


def _pastille(categorie) -> str:
    """Couleur de la pastille d'une catégorie, rien si elle est vide."""
    texte = str(categorie or "").strip()
    return category_color(texte) if texte else ""


#: Saut de ligne, nommé pour que les messages restent lisibles en format %.
NL = chr(10)

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


class _SampleModel(RowTableModel):
    """Les échantillons, qu'on peut glisser hors de l'application.

    Un son glissé de la liste vers l'Explorateur ou un logiciel de MAO y
    arrive tel qu'il est dans la copie de travail : un enregistrement fait
    sur le Deluge se retravaille sur le PC sans passer par un dossier caché.
    """

    def __init__(self, columns, rows, page) -> None:
        super().__init__(columns, rows, page)
        self._page = page

    def flags(self, index):  # noqa: D102 - API Qt
        drapeaux = super().flags(index)
        if index.isValid():
            drapeaux |= Qt.ItemFlag.ItemIsDragEnabled
        return drapeaux

    def mimeTypes(self) -> list[str]:  # noqa: N802 - API Qt
        return ["text/uri-list"]

    def mimeData(self, indexes):  # noqa: N802 - API Qt
        lignes = sorted({index.row() for index in indexes})
        return self._page.mime_for_rows([self.row_at(i) for i in lignes])


class ProcessDialog(QDialog):
    """Choix des traitements à appliquer à une sélection d'échantillons.

    Le dialogue ne fait que **composer une intention** : c'est
    ``samplefix.plan_custom`` qui en tire un plan, et ``PlanDialog`` qui le
    montre fichier par fichier avant la moindre écriture.
    """

    def __init__(self, count: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Traiter les échantillons")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAD, PAD, PAD, PAD)
        layout.setSpacing(8)

        titre = QLabel("%d échantillon(s) sélectionné(s)" % count)
        titre.setProperty("role", "title")
        layout.addWidget(titre)

        form = QFormLayout()
        form.setSpacing(6)

        self._mono = QCheckBox("Mélanger en mono")
        self._mono.setToolTip(
            "Divise la taille par deux. La longueur ne change pas.")
        form.addRow(self._mono)

        self._dc = QCheckBox("Retirer la composante continue")
        form.addRow(self._dc)

        self._norm = QCheckBox("Normaliser la crête à")
        self._norm_db = QDoubleSpinBox()
        self._norm_db.setRange(-24.0, 0.0)
        self._norm_db.setDecimals(1)
        self._norm_db.setSingleStep(0.5)
        self._norm_db.setValue(samplefix.DEFAULT_HEADROOM_DB)
        self._norm_db.setSuffix("  dBFS")
        form.addRow(self._norm, self._norm_db)

        self._trim = QCheckBox("Couper le silence sous")
        self._trim_db = QDoubleSpinBox()
        self._trim_db.setRange(-90.0, -20.0)
        self._trim_db.setDecimals(0)
        self._trim_db.setValue(-60.0)
        self._trim_db.setSuffix("  dB")
        form.addRow(self._trim, self._trim_db)

        self._fade = QCheckBox("Fondus d'entrée et de sortie de")
        self._fade_ms = QDoubleSpinBox()
        self._fade_ms.setRange(0.5, 500.0)
        self._fade_ms.setDecimals(1)
        self._fade_ms.setValue(5.0)
        self._fade_ms.setSuffix("  ms")
        form.addRow(self._fade, self._fade_ms)

        self._rate = QCheckBox("Rééchantillonner à")
        self._rate_box = QComboBox()
        for value in samplefix.STANDARD_RATES + (32000, 22050):
            self._rate_box.addItem("%d Hz" % value, value)
        form.addRow(self._rate, self._rate_box)

        layout.addLayout(form)

        note = QLabel(
            "Le rééchantillonnage et la coupe du silence changent la "
            "longueur des fichiers : les bornes des presets qui les citent "
            "sont recalées, et les fichiers utilisés par un morceau sont "
            "écartés. Les originaux sont conservés dans "
            "<b>%s/</b>." % samplefix.BACKUP_ROOT)
        note.setWordWrap(True)
        note.setStyleSheet("color: %s;" % GREY)
        layout.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText("Simuler")
        ok.setObjectName("Primary")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(
            "Annuler")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def actions(self) -> dict:
        """Les traitements cochés, prêts pour ``samplefix.plan_custom``."""
        return {
            "mono": self._mono.isChecked(),
            "dc": self._dc.isChecked(),
            "normalize_db": (self._norm_db.value()
                             if self._norm.isChecked() else None),
            "trim_db": (self._trim_db.value()
                        if self._trim.isChecked() else None),
            "fade_ms": self._fade_ms.value() if self._fade.isChecked() else 0.0,
            "rate": (self._rate_box.currentData()
                     if self._rate.isChecked() else None),
        }


class ScoredRow:
    """Une ligne d'index augmentée d'une proximité.

    ``sqlite3.Row`` ne se modifie pas : on l'enveloppe plutôt que de la
    recopier en dictionnaire, pour que les extracteurs de colonnes
    continuent de fonctionner à l'identique.
    """

    __slots__ = ("_row", "closeness", "distance")

    def __init__(self, row, closeness: int, distance: float) -> None:
        self._row = row
        self.closeness = closeness
        self.distance = distance

    def keys(self):
        return list(self._row.keys()) + ["closeness", "distance"]

    def __getitem__(self, key):
        if key == "closeness":
            return self.closeness
        if key == "distance":
            return self.distance
        return self._row[key]


class SliceDialog(QDialog):
    """Découpe une boucle en kit, avec les coupes visibles sur l'onde.

    Rien n'est écrit tant que « Écrire le kit » n'a pas été actionné : le
    dialogue ne manipule qu'un :class:`slicer.SliceSet`, qui n'est qu'une
    liste de bornes.
    """

    def __init__(self, ctx, rel: str, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.rel = rel
        self.sliceset = slicer.SliceSet(rel=rel, sr=0, frames=0)
        self.written = ""
        #: Morceau écrit depuis ce dialogue (chemin relatif), s'il y en a un.
        self.written_song = ""

        self.setWindowTitle("Découper en kit — %s" % Path(rel).name)
        self.resize(900, 620)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAD, PAD, PAD, PAD)
        layout.setSpacing(8)

        self._title = QLabel(rel)
        self._title.setProperty("role", "title")
        layout.addWidget(self._title)

        self._wave = WaveformView()
        self._wave.setMinimumHeight(150)
        self._wave.positionClicked.connect(self._on_wave_clicked)
        layout.addWidget(self._wave, 1)

        layout.addWidget(self._build_controls())

        self._summary = QLabel("")
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)

        self._list = QTableWidget(0, 4)
        self._list.setHorizontalHeaderLabels(
            ["#", "Début", "Durée", "Trames"])
        self._list.verticalHeader().setVisible(False)
        self._list.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._list.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self._list.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self._list.itemSelectionChanged.connect(self._on_row_picked)
        self._list.setMaximumHeight(170)
        layout.addWidget(self._list)

        buttons = QDialogButtonBox()
        self._write = buttons.addButton(
            "Écrire le kit", QDialogButtonBox.ButtonRole.AcceptRole)
        self._write.setObjectName("Primary")
        self._export = buttons.addButton(
            "Exporter en fichiers…", QDialogButtonBox.ButtonRole.ActionRole)
        self._song = buttons.addButton(
            "Écrire en morceau", QDialogButtonBox.ButtonRole.ActionRole)
        self._song.setToolTip(
            "Écrit sur la carte un morceau neuf dans SONGS : le kit des "
            "tranches et un clip qui rejoue la boucle tranche par tranche, à "
            "sa place. Aucun fichier existant n'est remplacé.")
        buttons.addButton("Fermer", QDialogButtonBox.ButtonRole.RejectRole)
        self._write.clicked.connect(self._do_write)
        self._export.clicked.connect(self._do_export)
        self._song.clicked.connect(self._do_song)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._load()
        self._recompute()

    # -- construction ------------------------------------------------------- #

    def _build_controls(self) -> QWidget:
        box = QGroupBox("Coupes")
        row = QHBoxLayout(box)
        row.setSpacing(10)

        self._mode = QComboBox()
        self._mode.addItem("Sur les attaques", "transients")
        self._mode.addItem("En divisions égales", "grid")
        self._mode.currentIndexChanged.connect(self._recompute)
        row.addWidget(QLabel("Placement :"))
        row.addWidget(self._mode)

        self._count = QSpinBox()
        self._count.setRange(1, slicer.MAX_SLICES)
        self._count.setValue(slicer.DEFAULT_SLICES)
        self._count.valueChanged.connect(self._recompute)
        row.addWidget(QLabel("Tranches :"))
        row.addWidget(self._count)

        self._sens = QSlider(Qt.Orientation.Horizontal)
        self._sens.setRange(20, 300)
        self._sens.setValue(100)
        self._sens.setFixedWidth(120)
        self._sens.setToolTip("Sensibilité de la détection d'attaques")
        self._sens.valueChanged.connect(self._recompute)
        row.addWidget(QLabel("Sensibilité :"))
        row.addWidget(self._sens)

        self._quant = QCheckBox("Aligner sur le tempo")
        self._quant.setToolTip(
            "Ramène les coupes détectées sur la grille : un break rejoué "
            "reste en place.")
        self._quant.stateChanged.connect(self._recompute)
        row.addWidget(self._quant)

        row.addStretch(1)

        self._listen = tool_button("Écouter", "play",
                                   "Écouter la tranche sélectionnée")
        self._listen.clicked.connect(self._play_selected)
        row.addWidget(self._listen)
        return box

    def _load(self) -> None:
        """Charge l'enveloppe de l'échantillon dans la vue."""
        card = self.ctx.sd
        path = card.resolve_sample(self.rel) if card is not None else None
        if path is None:
            self._wave.clear()
            return
        try:
            info = wav.probe(path)
            peaks = wav.peaks(path, buckets=1400)
            self._wave.set_peaks(peaks, info.duration, info.sample_rate)
            self._title.setText(
                "%s — %.2f s, %d Hz, %d canal(aux)"
                % (self.rel, info.duration, info.sample_rate, info.channels))
        except Exception as exc:  # noqa: BLE001 - un aperçu n'est pas vital
            log.debug("aperçu impossible pour %s : %s", self.rel, exc)
            self._wave.clear()

    # -- calcul des coupes -------------------------------------------------- #

    def _recompute(self) -> None:
        card = self.ctx.sd
        if card is None:
            return
        mode = self._mode.currentData() or "transients"
        attaques = mode == "transients"
        self._sens.setEnabled(attaques)
        self._quant.setEnabled(attaques)
        try:
            self.sliceset = slicer.slice_sample(
                card, self.rel, mode=mode, count=self._count.value(),
                sensitivity=self._sens.value() / 100.0, lib=self.ctx.lib,
                quantize=attaques and self._quant.isChecked())
        except Exception as exc:  # noqa: BLE001
            log.exception("découpage impossible")
            self._summary.setText("Découpage impossible : %s" % exc)
            return

        self._wave.set_markers(
            [s.start / float(self.sliceset.sr or 1)
             for s in self.sliceset.slices])
        self._fill_list()
        self._summary.setText(self.sliceset.summary())
        self._write.setEnabled(bool(self.sliceset))
        self._export.setEnabled(bool(self.sliceset))
        self._song.setEnabled(bool(self.sliceset))

    def _fill_list(self) -> None:
        sr = float(self.sliceset.sr or 1)
        self._list.setRowCount(len(self.sliceset))
        for index, tranche in enumerate(self.sliceset.slices):
            valeurs = ("%d" % (index + 1),
                       "%.3f s" % (tranche.start / sr),
                       "%.0f ms" % (tranche.seconds(self.sliceset.sr) * 1000),
                       "%d" % tranche.frames)
            for colonne, texte in enumerate(valeurs):
                item = QTableWidgetItem(texte)
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight
                                      | Qt.AlignmentFlag.AlignVCenter)
                self._list.setItem(index, colonne, item)

    # -- écoute ------------------------------------------------------------- #

    def _on_wave_clicked(self, seconds: float) -> None:
        """Un clic sur l'onde sélectionne et joue la tranche visée."""
        sr = float(self.sliceset.sr or 1)
        index = -1
        for position, tranche in enumerate(self.sliceset.slices):
            if seconds >= tranche.start / sr:
                index = position
        if index >= 0:
            self._list.selectRow(index)

    def _on_row_picked(self) -> None:
        index = self._list.currentRow()
        self._wave.set_markers(
            [s.start / float(self.sliceset.sr or 1)
             for s in self.sliceset.slices], active=index)
        if index >= 0:
            self._play_selected()

    def _play_selected(self) -> None:
        index = self._list.currentRow()
        player = self.ctx.player
        card = self.ctx.sd
        if player is None or card is None or index < 0:
            return
        try:
            bloc = slicer.render_slice(card, self.sliceset, index)
            if bloc.size:
                player.play_array(bloc, self.sliceset.sr)
        except Exception as exc:  # noqa: BLE001
            log.debug("écoute de la tranche impossible : %s", exc)

    # -- écriture ----------------------------------------------------------- #

    def _do_write(self) -> None:
        card = self.ctx.sd_or_warn(self, write=True)
        if card is None or not self.sliceset:
            return
        rel, message = slicer.save_sliced_kit(card, self.sliceset,
                                              apply=False)
        if not rel:
            QMessageBox.warning(self, "Découpage", message)
            return
        if QMessageBox.question(
                self, "Écrire le kit",
                "%s\n\nChaque rangée jouera une portion de %s : aucun "
                "fichier audio n'est dupliqué.\n\nContinuer ?"
                % (message, Path(self.rel).name),
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes) \
                != QMessageBox.StandardButton.Yes:
            return

        rel, message = slicer.save_sliced_kit(card, self.sliceset, apply=True)
        if not rel:
            QMessageBox.warning(self, "Découpage", message)
            return
        self.written = rel
        try:
            # Indexé tout de suite, pour que la page Kits le montre.
            from ...core.scan import index_presets
            index_presets(card, self.ctx.lib, [card.abs(rel)])
        except Exception:  # noqa: BLE001 - l'index se rattrapera à l'analyse
            log.exception("indexation du kit découpé impossible")
        QMessageBox.information(self, "Kit écrit", message)
        self.accept()

    def _do_song(self) -> None:
        """La boucle découpée, rejouée par un clip, en morceau du Deluge."""
        if not self.sliceset:
            return
        from ...core import songwriter
        from ..songexport import export_song

        sliceset = self.sliceset
        rel = export_song(
            self, self.ctx,
            lambda card: songwriter.slices_song(sliceset, name=""),
            Path(self.rel).stem, self._summary.setText)
        if rel:
            self.written_song = rel


    def _do_export(self) -> None:
        card = self.ctx.sd_or_warn(self, write=True)
        if card is None or not self.sliceset:
            return
        dossier = "SAMPLES/%s TRANCHES" % Path(self.rel).stem[:16]
        prevus, erreurs = slicer.export_slices(card, self.sliceset, dossier,
                                               apply=False)
        if erreurs:
            QMessageBox.warning(self, "Export", "\n".join(erreurs[:8]))
            return
        if QMessageBox.question(
                self, "Exporter les tranches",
                "%d fichiers seraient écrits dans %s.\n\nCe n'est pas "
                "nécessaire pour jouer le découpage sur le Deluge : le kit "
                "suffit et n'occupe rien de plus.\n\nContinuer ?"
                % (len(prevus), dossier),
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) \
                != QMessageBox.StandardButton.Yes:
            return

        ecrits, erreurs = slicer.export_slices(card, self.sliceset, dossier,
                                               apply=True)
        if erreurs:
            QMessageBox.warning(
                self, "Export partiel",
                "%d fichiers écrits, %d en échec :%s%s"
                % (len(ecrits), len(erreurs), NL + NL,
                   NL.join(erreurs[:8])))
        else:
            QMessageBox.information(
                self, "Export terminé",
                "%d fichiers écrits dans %s." % (len(ecrits), dossier))
        self.written = dossier


class SamplesPage(Page):
    """Bibliothèque d'échantillons."""

    TITLE = "Échantillons"
    EMPTY_DETAIL = ("Indiquez l'emplacement de votre carte dans les réglages. "
                    "Vous retrouverez ici toute la bibliothèque : forme "
                    "d'onde, écoute d'un clic, étiquettes et sons proches.")
    ICON = "samples"

    #: Un échantillon a été choisi : utile aux autres pages (générateur).
    sampleChosen = pyqtSignal(str)

    #: Émis après un traitement par lot : la carte a changé sur le disque, les
    #: autres pages (dont la note de santé) doivent se rafraîchir. Le nom est
    #: celui que ``mainwindow._connect_page`` reconnaît.
    cardModified = pyqtSignal()
    #: Des fichiers du PC à envoyer au Deluge, et le dossier choisi ici.
    sendRequested = pyqtSignal(list, str)

    def __init__(self, ctx, parent=None) -> None:
        super().__init__(ctx, parent)
        self._model: RowTableModel | None = None
        self._proxy = None
        self._current: str = ""
        self._folder = ""
        #: Espace de comparaison, construit à la demande puis conservé :
        #: 1 741 vecteurs de huit nombres, soit une poignée de kilo-octets.
        self._space = None
        #: Son de référence de la vue « sons proches », vide hors de ce mode.
        self._similar_to: str = ""
        self._similar_rows: list = []
        self._with_closeness = False

    # -- construction ------------------------------------------------------- #

    def build(self) -> None:
        outer = QVBoxLayout(self.content())
        outer.setContentsMargins(PAD, PAD, PAD, PAD)
        outer.setSpacing(8)

        header, actions = self.header(
            "Échantillons", "Parcourir, écouter et ranger la bibliothèque")
        outer.addWidget(header)

        self._play_button = tool_button("Écouter", "play", primary=True)
        self._play_button.clicked.connect(self.guard(self._play))
        actions.addWidget(self._play_button)

        stop = tool_button("Arrêter", "stop")
        stop.clicked.connect(self.guard(self._stop))
        actions.addWidget(stop)

        self._reveal_button = tool_button(
            "Dans l'explorateur", "folder",
            "Ouvrir le dossier contenant le fichier")
        self._reveal_button.clicked.connect(self.guard(self._reveal))
        actions.addWidget(self._reveal_button)

        self._process_button = tool_button(
            "Traiter…", "tools",
            "Mono, normalisation, rééchantillonnage, fondus… sur la "
            "sélection")
        self._process_button.clicked.connect(self.guard(self._process))
        actions.addWidget(self._process_button)

        self._slice_button = tool_button(
            "Découper…", "grid",
            "Découper une boucle en kit : un pad par tranche")
        self._slice_button.clicked.connect(self.guard(self._slice))
        actions.addWidget(self._slice_button)

        self._similar_button = tool_button(
            "Sons proches", "search",
            "Trouver les échantillons qui ressemblent au son sélectionné")
        self._similar_button.clicked.connect(self.guard(self._toggle_similar))
        actions.addWidget(self._similar_button)

        self._send_button = tool_button("Envoyer au Deluge…", "import")
        self._send_button.clicked.connect(self.guard(self._send))
        actions.addWidget(self._send_button)

        # Rien n'est sélectionné au premier affichage : les actions qui
        # portent sur un son restent éteintes jusqu'au premier clic dans la
        # liste.
        self._update_actions(0)

        outer.addWidget(self._build_filters())

        splitter = QSplitter(Qt.Orientation.Horizontal, self.content())
        splitter.addWidget(self._build_tree())
        right = QSplitter(Qt.Orientation.Vertical)
        right.addWidget(self._build_table())
        right.addWidget(self._build_preview())
        right.setStretchFactor(0, 3)
        right.setStretchFactor(1, 2)
        splitter.addWidget(right)
        # 300 px pour l'arbre : « MULTISAMPLES  (1091) » tient entièrement,
        # alors qu'à 250 il s'élidait dès le deuxième niveau.
        # ``setSizes`` est une **proportion** : Qt normalise les deux
        # nombres à la largeur disponible. Donner [620, 820] sur une
        # zone de 1 210 px rendait 521 px, pas 620 — d'où des colonnes
        # écrasées. Les nombres ci-dessous valent pour une zone de
        # 1 210 px (fenêtre de 1 440).
        splitter.setSizes([300, 910])
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
        card = Card("Dossiers", color=self.color)
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setMinimumWidth(190)
        # Vingt pixels d'indentation par niveau coupaient « MULTISAMPLES »
        # dès le troisième étage, dans un panneau de 250 px.
        self._tree.setIndentation(13)
        self._tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._tree.itemSelectionChanged.connect(
            self.guard(self._on_folder_selected))
        card.body().addWidget(self._tree)
        return card

    def _build_table(self) -> QWidget:
        card = Card("")
        self._table = QTableView()
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        # Un son glissé hors de la liste arrive dans l'Explorateur ou le
        # logiciel de MAO : c'est une copie, la carte n'est pas touchée.
        self._table.setDragEnabled(True)
        self._table.setDragDropMode(
            QAbstractItemView.DragDropMode.DragOnly)
        self._table.setDefaultDropAction(Qt.DropAction.CopyAction)
        card.body().addWidget(self._table)
        return card

    def _build_preview(self) -> QWidget:
        """L'aperçu, **défilable** : il cède la place à la liste.

        Mesuré : son minimum atteignait 346 px, surtout à cause de la forme
        d'onde. Sur un portable de 720 px de haut, la liste tombait à
        **une seule ligne visible** — une liste qui ne liste plus rien. Dans
        une zone défilante, l'aperçu garde sa hauteur naturelle quand il y a
        la place, et se parcourt quand il n'y en a pas.
        """
        card = Card("Aperçu", color=self.color)
        exterieur = card.body()
        defilante = QScrollArea()
        defilante.setWidgetResizable(True)
        defilante.setFrameShape(QScrollArea.Shape.NoFrame)
        interieur = QWidget()
        body = QVBoxLayout(interieur)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(6)
        defilante.setWidget(interieur)
        exterieur.addWidget(defilante)

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
        self._stars.setToolTip(
            "Note de 1 à 5 étoiles, gardée dans l'index de l'application "
            "et non sur la carte")
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

    def _columns(self, with_closeness: bool = False) -> list:
        """Colonnes de la table.

        L'extracteur rend la **valeur brute** et le formateur l'habille : la
        colonne se trie alors numériquement (cf. ``RowTableModel``).

        ``with_closeness`` ajoute la colonne de proximité, utile seulement en
        recherche par ressemblance.
        """
        left = Qt.AlignmentFlag.AlignLeft
        right = Qt.AlignmentFlag.AlignRight

        def get(key, default=None):
            return lambda row: (row[key] if key in row.keys() else default)

        proximite = [("Proximité", get("closeness"), 90, right,
                      lambda v: "%d %%" % v if v is not None else "—")] \
            if with_closeness else []

        def dossier(row):
            """Dernier segment du chemin : « Kick », pas « SAMPLES/…/Kick »."""
            brut = str((row["folder"] if "folder" in row.keys() else "") or "")
            return brut.rstrip("/").rsplit("/", 1)[-1]

        def format_court(row):
            """Ce qui sort de l'ordinaire, et rien quand tout est normal.

            Mesuré sur la carte : 90,7 % des fichiers sont en 44,1 kHz,
            87,7 % en 16 bits, 69,7 % en mono, et 100 % en WAV. Trois
            colonnes répétaient donc la même valeur sur presque chaque
            ligne. Elles sont remplacées par une seule, vide dans le cas
            courant : l'exception saute aux yeux au lieu de se noyer.
            """
            def champ(nom, defaut=None):
                return row[nom] if nom in row.keys() else defaut

            bouts = []
            sr = champ("sr")
            if sr and int(sr) != 44100:
                bouts.append("%g k" % (int(sr) / 1000.0))
            bits = champ("bit_depth")
            if bits and int(bits) != 16:
                bouts.append("%d b" % int(bits))
            if (champ("channels") or 1) > 1:
                bouts.append("stéréo")
            return " · ".join(bouts)

        return proximite + [
            ("Nom", get("name"), 260, left),
            ("Dossier", dossier, 130, left),
            ("Catégorie", get("category"), 132, left, None, _pastille),
            ("Durée", get("duration"), 80, right, human_duration),
            ("Tonalité", get("key"), 70, left),
            # Vide = format courant. Rempli = ce qui mérite un regard.
            ("Format", format_court, 100, left),
            ("Taille", get("size"), 85, right, human_size),
            ("Usages", get("used_count"), 65, right),
        ]

    # -- chargement --------------------------------------------------------- #

    # -- recherche par ressemblance ----------------------------------------- #

    def _toggle_similar(self) -> None:
        """Entre dans la vue « sons proches », ou en ressort."""
        if self._similar_to:
            self._leave_similar()
            return

        rows = self._selected_rows()
        if not rows:
            QMessageBox.information(
                self, "Aucune sélection",
                "Sélectionnez le son dont vous cherchez les semblables.")
            return

        rel = rows[0]["rel"]
        if self._space is None:
            self._space = similarity.build_space(self.lib)
        if not self._space.has(rel):
            QMessageBox.information(
                self, "Pas encore analysé",
                "Ce son n'a pas de descripteurs acoustiques.\n\n"
                "Lancez une analyse de la carte avec l'analyse acoustique "
                "activée (Réglages), puis recommencez.")
            return

        matches = similarity.similar(self.lib, rel, limit=60,
                                     space=self._space)
        if not matches:
            self.say("Aucun son proche trouvé.")
            return

        self._similar_to = rel
        self._similar_rows = [
            ScoredRow(m.row, m.closeness, m.distance) for m in matches
            if m.row is not None]
        self._similar_button.setText("Toute la liste")
        self._reload()
        self.say("%d son(s) proches de %s — %s"
                 % (len(self._similar_rows), Path(rel).name,
                    similarity.describe(self._space.rows.get(
                        similarity.norm_rel(rel)))))

    def _leave_similar(self) -> None:
        """Revient à la liste complète."""
        if not self._similar_to:
            return
        self._similar_to = ""
        self._similar_rows = []
        self._similar_button.setText("Sons proches")
        self._reload()

    def _reload(self) -> None:
        """Interroge l'index et remplit la table."""
        if self._similar_to:
            self._fill_table(self._similar_rows, with_closeness=True)
            self._count.setText(
                "%d son(s) proches de « %s », du plus proche au plus "
                "lointain" % (len(self._similar_rows),
                              Path(self._similar_to).name))
            return

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

        self._fill_table(rows)

        total = len(rows)
        suffix = ""
        if self._only_missing.isChecked():
            suffix = " — fichiers réclamés par un preset mais absents"
        self._count.setText(f"{total} échantillon(s) affiché(s){suffix}")

    def _fill_table(self, rows, with_closeness: bool = False) -> None:
        """Pose les lignes dans la table, en ajustant les colonnes."""
        if self._model is None:
            self._model = _SampleModel(self._columns(with_closeness),
                                       rows, self)
            self._proxy = sorted_proxy(self._model, self)
            self._table.setModel(self._proxy)
            configure_table(self._table, self._model)
            # C'est le **nom** qui absorbe la place libre. Étirer « Dossier »
            # revenait à lui donner ce qui reste après les autres : trente-six
            # pixels, de quoi n'afficher que des points de suspension.
            self._table.horizontalHeader().setSectionResizeMode(
                0, QHeaderView.ResizeMode.Stretch)
            selection = self._table.selectionModel()
            if selection is not None:
                selection.selectionChanged.connect(
                    self.guard(lambda *_a: self._on_row_selected()))
        else:
            if with_closeness != self._with_closeness:
                self._model.set_columns(self._columns(with_closeness))
            self._model.set_rows(rows)
        self._with_closeness = with_closeness
        # Le remplissage vide la sélection : les actions qui en dépendent
        # doivent s'éteindre avec elle, sans attendre un clic.
        self._update_actions(len(self._selected_rows()))

    def _fill_tree(self) -> None:
        """Arbre des dossiers, construit depuis les chemins indexés.

        **Chaque nœud porte le total de ce qu'il contient**, sous-dossiers
        compris : le compte n'était posé que sur les feuilles, et les nœuds
        visibles — les seuls que l'on voit sans déplier — n'affichaient rien.

        **Les niveaux de passage sont dépliés d'office.** La carte range tout
        sous « SAMPLES » : l'arbre s'ouvrait donc sur deux lignes, dont une
        inutile, dans un panneau de 270 pixels. On déplie tant qu'un dossier
        n'a qu'un seul enfant, puis un cran de plus : les cinq familles de la
        carte sont visibles d'emblée.
        """
        self._tree.blockSignals(True)
        self._tree.clear()

        try:
            folders = self.lib.folders("sample")
        except Exception as exc:  # noqa: BLE001
            log.debug("dossiers indisponibles : %s", exc)
            folders = []

        # Totaux cumulés : chaque segment d'un chemin reçoit le compte de
        # toutes les feuilles qui passent par lui.
        totaux: dict[str, int] = {}
        for name, count in folders:
            segments = [s for s in str(name).split("/") if s]
            for profondeur in range(len(segments)):
                chemin = "/".join(segments[:profondeur + 1])
                totaux[chemin] = totaux.get(chemin, 0) + int(count)

        total = sum(int(c) for _n, c in folders)
        root = QTreeWidgetItem(["Tous les sons  (%d)" % total])
        root.setData(0, Qt.ItemDataRole.UserRole, "")
        self._tree.addTopLevelItem(root)

        nodes: dict[str, QTreeWidgetItem] = {"": root}
        for name, _count in sorted(folders):
            parts = [p for p in str(name).split("/") if p]
            path = ""
            parent = root
            for part in parts:
                path = f"{path}/{part}" if path else part
                node = nodes.get(path)
                if node is None:
                    node = QTreeWidgetItem(
                        ["%s  (%d)" % (part, totaux.get(path, 0))])
                    node.setData(0, Qt.ItemDataRole.UserRole, path)
                    node.setToolTip(0, path)
                    parent.addChild(node)
                    nodes[path] = node
                parent = node

        root.setExpanded(True)
        self._deplier_les_passages(root)
        self._tree.setCurrentItem(root)
        self._tree.blockSignals(False)

    @staticmethod
    def _deplier_les_passages(item) -> None:
        """Déplie les dossiers à enfant unique, puis un niveau de plus.

        Un dossier qui n'a qu'un enfant n'offre aucun choix : le replier ne
        cache rien et coûte un clic. On descend donc la chaîne, et on ouvre
        encore le premier niveau qui, lui, offre un vrai choix.
        """
        courant = item
        while courant.childCount() == 1:
            courant.setExpanded(True)
            courant = courant.child(0)
        courant.setExpanded(True)

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
        self._update_actions(len(rows))
        if not rows:
            return
        row = rows[0]
        rel = row["rel"] if "rel" in row.keys() else ""
        self._show(rel, row)
        if self.ctx.settings.autoplay:
            self._play()

    def _update_actions(self, combien: int) -> None:
        """Éteint les actions qui exigent une sélection.

        Elles répondaient par une boîte « Aucune sélection » : un
        avertissement après coup, là où un bouton éteint dit avant le clic ce
        qui manque. « Découper » ne s'allume que sur **un seul** son, comme
        le fait le découpage lui-même.
        """
        for bouton, mini, maxi in (
                (self._play_button, 1, None),
                (self._process_button, 1, None),
                (self._slice_button, 1, 1),
                (self._similar_button, 1, 1)):
            assez = combien >= mini and (maxi is None or combien <= maxi)
            bouton.setEnabled(bool(assez))
        self._reveal_button.setEnabled(combien >= 1)
        # « Sons proches » sert aussi à sortir de ce mode : il reste allumé
        # tant qu'on y est, sinon on ne pourrait plus revenir à la liste.
        if self._similar_to:
            self._similar_button.setEnabled(True)

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

        # Une seule ligne de format : « 44 100 Hz · 16 bits · mono ».
        # Quatre lignes séparées répétaient ce que la colonne « Format » de
        # la table dit déjà, et volaient la hauteur à la forme d'onde.
        if info.ok:
            canaux = {1: "mono", 2: "stéréo"}.get(info.channels,
                                                  "%d canaux" % info.channels)
            format_long = "%s Hz · %d bits · %s" % (
                "{:,}".format(int(info.sample_rate)).replace(",", " "),
                info.bit_depth, canaux)
            if info.fmt and info.fmt.lower() not in ("pcm", "wav"):
                format_long += " · %s" % info.fmt
        else:
            format_long = "—"

        details: list[tuple[str, object]] = [
            ("Durée", human_duration(info.duration) if info.ok else "—"),
            ("Format", format_long),
            ("Taille", human_size(row["size"] if "size" in row.keys() else 0)),
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
        clear_layout(self._tags_row)
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

    # -- du PC vers le Deluge, et retour ---------------------------------------- #

    def _send(self) -> None:
        """Choisir des fichiers du PC à envoyer au Deluge, dans le dossier
        choisi dans l'arbre s'il y en a un."""
        from PyQt6.QtWidgets import QFileDialog

        depart = Path.home() / "Downloads"
        choisis, _filtre = QFileDialog.getOpenFileNames(
            self, "Envoyer au Deluge",
            str(depart if depart.is_dir() else Path.home()),
            "Sons, presets, kits et morceaux du Deluge "
            "(*.wav *.WAV *.aif *.aiff *.xml *.XML);;Tous les fichiers (*)")
        if choisis:
            dossier = self._folder if self._folder.upper().startswith(
                "SAMPLES") else ""
            self.sendRequested.emit(list(choisis), dossier)

    def mime_for_rows(self, rows):
        """Les fichiers de ces lignes, pour un glisser vers le PC."""
        from PyQt6.QtCore import QMimeData, QUrl

        if self.sd is None:
            return None
        adresses = []
        for row in rows:
            try:
                rel = row["rel"]
            except (KeyError, IndexError, TypeError):
                continue
            chemin = self.sd.resolve_sample(rel)
            if chemin is not None:
                adresses.append(QUrl.fromLocalFile(str(chemin)))
        if not adresses:
            return None
        donnees = QMimeData()
        donnees.setUrls(adresses)
        return donnees

    def _clear_filters(self) -> None:
        """Retire aussi le dossier choisi dans l'arbre : un son reçu du
        Deluge s'affiche dans la liste entière."""
        racine = self._tree.topLevelItem(0) if self._tree.topLevelItemCount() \
            else None
        if racine is not None:
            self._tree.blockSignals(True)
            self._tree.setCurrentItem(racine)
            self._tree.blockSignals(False)
        super()._clear_filters()

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

    # -- découpage ---------------------------------------------------------- #

    def _slice(self) -> None:
        """Ouvre le découpeur sur l'échantillon sélectionné."""
        card = self.card_or_warn()
        if card is None:
            return
        rows = self._selected_rows()
        if not rows:
            QMessageBox.information(
                self, "Aucune sélection",
                "Sélectionnez la boucle à découper dans la liste.")
            return
        if len(rows) > 1:
            QMessageBox.information(
                self, "Un seul échantillon",
                "Le découpage porte sur une boucle à la fois : "
                "%d sont sélectionnées." % len(rows))
            return

        dialog = SliceDialog(self.ctx, rows[0]["rel"], self)
        dialog.exec()
        if dialog.written_song:
            self.songWritten.emit(dialog.written_song)
        if dialog.written:
            self.say("Découpage écrit : %s" % dialog.written)
            self.cardModified.emit()
            self._reload()

    # -- traitement par lot ------------------------------------------------- #

    def _process(self) -> None:
        """Traite la sélection : choix, simulation, confirmation, exécution."""
        card = self.writable_card()
        if card is None:
            return
        rows = self._selected_rows()
        if not rows:
            QMessageBox.information(
                self, "Aucune sélection",
                "Sélectionnez les échantillons à traiter dans la liste.")
            return

        dialog = ProcessDialog(len(rows), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        rels = [r["rel"] for r in rows]
        plan = samplefix.plan_custom(card, self.lib, rels,
                                     **dialog.actions())
        if not plan:
            motif = (plan.skipped[0].skipped if plan.skipped
                     else "aucun traitement coché")
            self.say("Rien à faire : %s." % motif)
            return

        confirm = PlanDialog(plan, self, "Traitement des échantillons")
        if confirm.exec() != QDialog.DialogCode.Accepted:
            self.say("Traitement annulé.")
            return

        self.say("Traitement de %d fichier(s)…" % len(plan))
        self.run(self._do_process, plan, card,
                 on_result=self.guard(self._process_done),
                 on_error=self.guard(lambda m: self.say("Échec : %s" % m)),
                 title="Traitement")

    def _do_process(self, plan, card, progress=None, should_stop=None):
        return plan.apply(card, self.lib, progress=progress,
                          should_stop=should_stop)

    def _process_done(self, result) -> None:
        if result is None:
            return
        if result.failed:
            detail = NL.join("%s : %s" % (rel, msg)
                             for rel, msg in result.failed[:12])
            QMessageBox.warning(
                self, "Traitement partiel",
                "%d fichier(s) traités, %d en échec :%s%s"
                % (len(result.done), len(result.failed), NL + NL, detail))
        if result.backup_dir:
            self.say("%s Originaux dans %s."
                     % (result.summary(), result.backup_dir))
        else:
            self.say(result.summary())
        self.cardModified.emit()
        self._reload()

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
