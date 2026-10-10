# -*- coding: utf-8 -*-
"""Page « Morceaux ».

Les morceaux sont la seule chose qu'on ne peut pas refaire : un preset se
regénère, un échantillon se retélécharge, mais un morceau est du travail. La
page est donc **entièrement en lecture seule** — rien ici n'écrit dans un
fichier de morceau, conformément au choix pris dans
:class:`delugeapp.core.model.Song`.

Elle répond à deux questions pratiques : « qu'y a-t-il dans ce morceau » et
« est-ce qu'il lui manque quelque chose » — un preset supprimé ou un
échantillon déplacé rend un morceau muet par endroits sans que la machine le
signale.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSplitter,
    QTabWidget,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..theme import PAD, PAD_GREEN, PAD_RED
from ..widgets.common import (
    Card,
    ElidedLabel,
    KeyValueTable,
    RowTableModel,
    SearchBar,
    configure_table,
    human_size,
    sorted_proxy,
)
from ..widgets.padgrid import SongPreview
from .base import Page, page_header, tool_button

log = logging.getLogger(__name__)


class SongsPage(Page):
    """Morceaux de la carte."""

    TITLE = "Morceaux"
    ICON = "song"

    def __init__(self, ctx, parent=None) -> None:
        super().__init__(ctx, parent)
        self._model: RowTableModel | None = None
        self._proxy = None
        self._song = None
        self._current = ""

    # -- construction ------------------------------------------------------- #

    def build(self) -> None:
        outer = QVBoxLayout(self.content())
        outer.setContentsMargins(PAD, PAD, PAD, PAD)
        outer.setSpacing(8)

        header, actions = page_header(
            "Morceaux", "Contenu, dépendances et ce qui manque")
        outer.addWidget(header)

        export = tool_button("Clip en MIDI", "export",
                             "Exporter le clip sélectionné en fichier MIDI",
                             primary=True)
        export.clicked.connect(self.guard(self._export_clip))
        actions.addWidget(export)

        report = tool_button("Rapport HTML", "info",
                             "Enregistrer une fiche du morceau")
        report.clicked.connect(self.guard(self._export_report))
        actions.addWidget(report)

        reveal = tool_button("Dans l'explorateur", "folder")
        reveal.clicked.connect(self.guard(self._reveal))
        actions.addWidget(reveal)

        self._search = SearchBar("Rechercher un morceau…")
        self._search.searchChanged.connect(self.guard(lambda _t: self._reload()))
        outer.addWidget(self._search)

        splitter = QSplitter(Qt.Orientation.Horizontal, self.content())
        splitter.addWidget(self._build_table())
        splitter.addWidget(self._build_detail())
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
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
        self._name = ElidedLabel("Aucun morceau sélectionné")
        self._name.setProperty("role", "title")
        head.body().addWidget(self._name)

        row = QHBoxLayout()
        self._preview = SongPreview()
        self._preview.setMinimumSize(230, 104)
        self._preview.setMaximumHeight(130)
        row.addWidget(self._preview, 1)
        self._stats = KeyValueTable()
        self._stats.setMaximumHeight(170)
        row.addWidget(self._stats, 1)
        head.body().addLayout(row)
        column.addWidget(head)

        tabs = QTabWidget()
        tabs.addTab(self._build_clips_tab(), "Clips")
        tabs.addTab(self._build_instruments_tab(), "Instruments")
        tabs.addTab(self._build_samples_tab(), "Échantillons")
        column.addWidget(tabs, 1)
        return host

    def _build_clips_tab(self) -> QWidget:
        self._clips = QTableWidget(0, 5)
        self._clips.setHorizontalHeaderLabels(
            ["Clip", "Preset", "Mesures", "Notes", "Section"])
        self._clips.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self._clips.verticalHeader().setVisible(False)
        self._clips.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._clips.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        return self._clips

    def _build_instruments_tab(self) -> QWidget:
        self._instruments = QTableWidget(0, 4)
        self._instruments.setHorizontalHeaderLabels(
            ["Nature", "Nom", "Dossier", "Présent"])
        self._instruments.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch)
        self._instruments.verticalHeader().setVisible(False)
        self._instruments.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        return self._instruments

    def _build_samples_tab(self) -> QWidget:
        self._samples = QTableWidget(0, 2)
        self._samples.setHorizontalHeaderLabels(["Fichier", "Présent"])
        self._samples.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self._samples.verticalHeader().setVisible(False)
        self._samples.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        return self._samples

    # -- colonnes ----------------------------------------------------------- #

    def _columns(self) -> list:
        left = Qt.AlignmentFlag.AlignLeft
        right = Qt.AlignmentFlag.AlignRight

        def get(key, default=None):
            return lambda row: (row[key] if key in row.keys() else default)

        return [
            ("Nom", get("name"), 170, left),
            ("Tempo", get("tempo"), 75, right,
             lambda v: f"{v:.0f} BPM" if v else "—"),
            ("Gamme", get("scale"), 130, left),
            ("Clips", get("clips"), 60, right),
            ("Notes", get("notes"), 65, right),
            ("Mesures", get("bars"), 75, right,
             lambda v: f"{v:.0f}" if v else "—"),
            ("Firmware", get("firmware"), 80, left),
            ("Taille", get("size"), 80, right, human_size),
        ]

    # -- chargement --------------------------------------------------------- #

    def _reload(self) -> None:
        try:
            rows = self.lib.search_songs(self._search.text().strip())
        except Exception:  # noqa: BLE001
            log.exception("recherche de morceaux en échec")
            rows = []

        if self._model is None:
            self._model = RowTableModel(self._columns(), rows, self)
            self._proxy = sorted_proxy(self._model, self)
            self._table.setModel(self._proxy)
            configure_table(self._table, self._model)
            selection = self._table.selectionModel()
            if selection is not None:
                selection.selectionChanged.connect(
                    self.guard(lambda *_a: self._on_selected()))
        else:
            self._model.set_rows(rows)
        self._count.setText(f"{len(rows)} morceau(x)")

    def _on_selected(self) -> None:
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
        self._current = row["rel"] if "rel" in row.keys() else ""
        self._load_song(self._current, row)

    def _load_song(self, rel: str, row) -> None:
        from ...core.model import Song

        self._name.setText(Path(rel).stem or "—")
        if self.sd is None:
            return
        try:
            self._song = Song.load(self.sd.abs(rel))
        except Exception as exc:  # noqa: BLE001
            log.debug("morceau illisible %s : %s", rel, exc)
            self._song = None
            self._stats.set_rows([("Erreur", str(exc))])
            self._preview.clear()
            for table in (self._clips, self._instruments, self._samples):
                table.setRowCount(0)
            return

        song = self._song
        self._preview.set_song(song)

        stats = song.stats()
        self._stats.set_rows([
            ("Tempo", f"{song.tempo_bpm:.1f} BPM"),
            ("Gamme", song.scale_name()),
            ("Clips de session", stats["clips"]),
            ("Clips d'arrangement", stats["arrangement_clips"]),
            ("Notes", stats["notes"]),
            ("Plus long clip", f"{stats['bars']:.0f} mesures"),
            ("Sections", stats["sections"]),
            ("Instruments", stats["instruments"]),
            ("Densité", f"{stats['density']:.1f} notes/mesure"),
            ("Swing", f"{song.swing_amount}"),
            ("Firmware", song.firmware or "—"),
        ])

        self._fill_clips(song)
        self._fill_instruments(song)
        self._fill_samples(song)

    def _fill_clips(self, song) -> None:
        self._clips.setRowCount(0)
        for clip in song.clips + song.arrangement_clips:
            index = self._clips.rowCount()
            self._clips.insertRow(index)
            self._clips.setItem(index, 0,
                                QTableWidgetItem(clip.name or f"clip {index + 1}"))
            preset = clip.preset_name or "—"
            if clip.preset_folder:
                preset = f"{preset}  ({clip.preset_folder})"
            item = QTableWidgetItem(preset)
            item.setToolTip(preset)
            self._clips.setItem(index, 1, item)
            self._clips.setItem(index, 2,
                                QTableWidgetItem(f"{clip.bars:.0f}"))
            self._clips.setItem(index, 3,
                                QTableWidgetItem(str(clip.note_count)))
            self._clips.setItem(index, 4,
                                QTableWidgetItem(str(clip.section)))

    def _fill_instruments(self, song) -> None:
        """Instruments du morceau, avec la présence du preset sur la carte."""
        self._instruments.setRowCount(0)
        labels = {"sound": "synthé", "kit": "kit", "midi": "MIDI",
                  "cv": "CV", "audio": "audio"}
        for kind, name, folder in song.preset_refs():
            index = self._instruments.rowCount()
            self._instruments.insertRow(index)
            self._instruments.setItem(
                index, 0, QTableWidgetItem(labels.get(kind, kind)))
            self._instruments.setItem(index, 1, QTableWidgetItem(name or "—"))
            self._instruments.setItem(index, 2,
                                      QTableWidgetItem(folder or "—"))

            present = self._preset_exists(kind, name, folder)
            if present is None:
                label, colour = "—", Qt.GlobalColor.gray
            elif present:
                label, colour = "oui", Qt.GlobalColor.green
            else:
                label, colour = "ABSENT", Qt.GlobalColor.red
            state = QTableWidgetItem(label)
            state.setForeground(colour)
            self._instruments.setItem(index, 3, state)

    def _preset_exists(self, kind: str, name: str,
                       folder: str) -> bool | None:
        """Vrai si le preset d'un instrument existe sur la carte.

        Les instruments MIDI et CV n'ont pas de fichier : ils rendent
        ``None``, qu'il ne faut pas confondre avec « absent ».
        """
        if kind not in ("sound", "kit") or not name:
            return None
        if self.sd is None:
            return None
        base = folder or ("KITS" if kind == "kit" else "SYNTHS")
        for suffix in (".XML", ".xml"):
            if self.sd.resolve_sample(f"{base}/{name}{suffix}") is not None:
                return True
        return False

    def _fill_samples(self, song) -> None:
        self._samples.setRowCount(0)
        for ref in song.sample_paths():
            index = self._samples.rowCount()
            self._samples.insertRow(index)
            item = QTableWidgetItem(ref)
            item.setToolTip(ref)
            self._samples.setItem(index, 0, item)
            present = (self.sd is not None
                       and self.sd.resolve_sample(ref) is not None)
            state = QTableWidgetItem("oui" if present else "ABSENT")
            state.setForeground(Qt.GlobalColor.green if present
                                else Qt.GlobalColor.red)
            self._samples.setItem(index, 1, state)

    # -- actions ------------------------------------------------------------ #

    def _export_clip(self) -> None:
        """Exporte le clip sélectionné en MIDI."""
        if self._song is None:
            self.say("Aucun morceau sélectionné.")
            return
        clips = self._song.clips + self._song.arrangement_clips
        index = self._clips.currentRow()
        if not 0 <= index < len(clips):
            self.say("Choisissez un clip dans l'onglet « Clips ».")
            return
        clip = clips[index]
        if clip.note_count == 0:
            self.say("Ce clip ne contient aucune note.")
            return

        from PyQt6.QtWidgets import QFileDialog

        from ...core import midifile

        default = f"{Path(self._current).stem} - {clip.name or index + 1}.mid"
        chosen, _f = QFileDialog.getSaveFileName(
            self, "Exporter le clip en MIDI", default,
            "Fichier MIDI (*.mid)")
        if not chosen:
            return
        try:
            midifile.clip_to_midi(Path(chosen), clip, self._song.tempo_bpm)
        except Exception as exc:  # noqa: BLE001
            log.exception("export MIDI impossible")
            self.say(f"Export impossible : {exc}")
            return
        self.say(f"Clip exporté : {Path(chosen).name} "
                 f"({clip.note_count} notes)")

    def _export_report(self) -> None:
        """Enregistre une fiche HTML du morceau."""
        if self._song is None:
            self.say("Aucun morceau sélectionné.")
            return

        from PyQt6.QtWidgets import QFileDialog

        default = f"{Path(self._current).stem}.html"
        chosen, _f = QFileDialog.getSaveFileName(
            self, "Enregistrer la fiche du morceau", default,
            "Page HTML (*.html)")
        if not chosen:
            return
        try:
            Path(chosen).write_text(self._report_html(), encoding="utf-8")
        except OSError as exc:
            log.exception("écriture du rapport impossible")
            self.say(f"Écriture impossible : {exc}")
            return
        self.say(f"Fiche enregistrée : {Path(chosen).name}")

    def _report_html(self) -> str:
        """Fiche du morceau en HTML, aux couleurs de l'application."""
        song = self._song
        stats = song.stats()

        def esc(text) -> str:
            return (str(text).replace("&", "&amp;").replace("<", "&lt;")
                    .replace(">", "&gt;"))

        rows = "".join(
            f"<tr><td>{esc(c.name or '—')}</td>"
            f"<td>{esc(c.preset_name or '—')}</td>"
            f"<td>{c.bars:.0f}</td><td>{c.note_count}</td></tr>"
            for c in song.clips + song.arrangement_clips)

        missing = [ref for ref in song.sample_paths()
                   if self.sd is None
                   or self.sd.resolve_sample(ref) is None]
        missing_html = ""
        if missing:
            items = "".join(f"<li>{esc(m)}</li>" for m in missing)
            missing_html = (
                f"<h2 style='color:#F2453D'>Échantillons manquants "
                f"({len(missing)})</h2><ul>{items}</ul>")

        return f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8">
<title>{esc(song.name)}</title>
<style>
 body {{ font-family: "Segoe UI", sans-serif; background:#1C1F26;
        color:#F2F4F8; padding:24px; }}
 h1 {{ color:#C79A22; margin-bottom:2px; }}
 h2 {{ color:#C79A22; margin-top:24px; font-size:14pt; }}
 table {{ border-collapse:collapse; width:100%; margin-top:8px; }}
 th, td {{ text-align:left; padding:4px 8px; border-bottom:1px solid #2F343E; }}
 th {{ color:#7A828F; font-weight:600; }}
 .meta {{ color:#7A828F; }}
</style></head><body>
<h1>{esc(song.name)}</h1>
<p class="meta">{song.tempo_bpm:.1f} BPM · {esc(song.scale_name())} ·
firmware {esc(song.firmware or '—')}</p>
<h2>Chiffres</h2>
<table>
<tr><th>Clips de session</th><td>{stats['clips']}</td></tr>
<tr><th>Clips d'arrangement</th><td>{stats['arrangement_clips']}</td></tr>
<tr><th>Notes</th><td>{stats['notes']}</td></tr>
<tr><th>Plus long clip</th><td>{stats['bars']:.0f} mesures</td></tr>
<tr><th>Sections</th><td>{stats['sections']}</td></tr>
<tr><th>Instruments</th><td>{stats['instruments']}</td></tr>
<tr><th>Densité</th><td>{stats['density']:.1f} notes par mesure</td></tr>
</table>
<h2>Clips</h2>
<table><tr><th>Nom</th><th>Preset</th><th>Mesures</th><th>Notes</th></tr>
{rows}</table>
{missing_html}
</body></html>"""

    def _reveal(self) -> None:
        if not self._current or self.sd is None:
            return
        path = self.sd.abs(self._current)
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    # -- rafraîchissement --------------------------------------------------- #

    def _refresh(self) -> None:
        self._reload()
