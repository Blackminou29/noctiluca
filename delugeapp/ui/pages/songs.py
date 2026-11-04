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

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
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

from ...i18n import N_, decimal, language, tr
from ..theme import PAD
from ..widgets.common import (
    Card,
    ElidedLabel,
    KeyValueTable,
    RowTableModel,
    SearchBar,
    configure_table,
    sorted_proxy,
)
from ..widgets.padgrid import SongPreview
from .base import Page, avance, tool_button

#: Saut de ligne, nommé pour que les messages en format % restent lisibles.
_NL = chr(10)

log = logging.getLogger(__name__)


class _PackPlan:
    """Enveloppe un ``SongPack`` pour ``PlanDialog``.

    Le dialogue n'exige de son plan que ``summary()``, ``counts()`` et
    ``to_text()`` — c'est ce qui lui permet de montrer aussi bien un plan de
    rangement qu'une correction audio. Un rassemblement s'y plie sans qu'il
    faille un second dialogue.
    """

    def __init__(self, pack) -> None:
        self._pack = pack

    def summary(self) -> str:
        return self._pack.summary()

    def to_text(self) -> str:
        return self._pack.to_text()

    def counts(self) -> dict:
        return {"copie": len(self._pack.files())}

    def __bool__(self) -> bool:
        return bool(self._pack)

    def __len__(self) -> int:
        return len(self._pack)


class SongsPage(Page):
    """Morceaux de la carte."""

    TITLE = N_("Morceaux")
    EMPTY_DETAIL = N_("Indiquez l'emplacement de votre carte dans les "
                      "réglages. Chaque morceau montrera alors ses pistes, "
                      "son tempo et tout ce dont il dépend.")
    ICON = "song"

    #: Aller sur une autre page : le morceau choisi, dans l'atelier.
    navigateRequested = pyqtSignal(str)

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

        header, actions = self.header(
            tr("Morceaux"), tr("Contenu, dépendances et ce qui manque"))
        outer.addWidget(header)

        # Un morceau de la carte se continue dans l'atelier : ses pistes et
        # ses clips y deviennent ceux du projet, et l'atelier le complète
        # sans rien en réécrire. C'est le geste qu'on fait le plus souvent
        # d'ici ; les exports viennent au niveau avancé.
        self._open_button = tool_button(tr("Ouvrir dans l'atelier"),
                                        "atelier", primary=True)
        self._open_button.clicked.connect(self.guard(self._open_in_atelier))
        actions.addWidget(self._open_button)

        export = avance(tool_button(tr("Clip en MIDI"), "export",
                                    tr("Exporter le clip sélectionné en "
                                       "fichier MIDI")))
        export.clicked.connect(self.guard(self._export_clip))
        actions.addWidget(export)

        self._song_midi = avance(tool_button(
            tr("Morceau en MIDI"), "midi",
            tr("Exporter tout le morceau : une piste MIDI par clip")))
        self._song_midi.clicked.connect(self.guard(self._export_song_midi))
        actions.addWidget(self._song_midi)

        self._pack = avance(tool_button(
            tr("Rassembler…"), "save",
            tr("Copier le morceau, ses presets et ses échantillons dans un "
               "dossier")))
        self._pack.clicked.connect(self.guard(self._export_pack))
        actions.addWidget(self._pack)

        report = avance(tool_button(tr("Rapport HTML"), "info",
                                    tr("Enregistrer une fiche du morceau")))
        report.clicked.connect(self.guard(self._export_report))
        actions.addWidget(report)

        reveal = tool_button(tr("Dans l'explorateur"), "folder")
        reveal.clicked.connect(self.guard(self._reveal))
        actions.addWidget(reveal)

        self._search = SearchBar(tr("Rechercher un morceau…"))
        self._search.searchChanged.connect(self.guard(lambda _t: self._reload()))
        outer.addWidget(self._search)

        splitter = QSplitter(Qt.Orientation.Horizontal, self.content())
        splitter.addWidget(self._build_table())
        splitter.addWidget(self._build_detail())
        # ``setSizes`` est une **proportion** : Qt normalise les deux
        # nombres à la largeur disponible. Donner [620, 820] sur une
        # zone de 1 210 px rendait 521 px, pas 620 — d'où des colonnes
        # écrasées. Les nombres ci-dessous valent pour une zone de
        # 1 210 px (fenêtre de 1 440).
        splitter.setSizes([520, 690])
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
        self._name = ElidedLabel(tr("Aucun morceau sélectionné"))
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
        tabs.addTab(self._build_clips_tab(), tr("Clips"))
        tabs.addTab(self._build_instruments_tab(), tr("Instruments"))
        tabs.addTab(self._build_samples_tab(), tr("Échantillons"))
        column.addWidget(tabs, 1)
        return host

    def _build_clips_tab(self) -> QWidget:
        self._clips = QTableWidget(0, 5)
        self._clips.setHorizontalHeaderLabels(
            [tr("Clip"), tr("Preset"), tr("Mesures"), tr("Notes"),
             tr("Section")])
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
            [tr("Nature"), tr("Nom"), tr("Dossier"), tr("Présent")])
        self._instruments.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch)
        self._instruments.verticalHeader().setVisible(False)
        self._instruments.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        return self._instruments

    def _build_samples_tab(self) -> QWidget:
        self._samples = QTableWidget(0, 2)
        self._samples.setHorizontalHeaderLabels([tr("Fichier"),
                                                 tr("Présent")])
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

        # Pas de colonne « Gamme » : le panneau de droite la donne pour le
        # morceau choisi, et sa largeur poussait les six colonnes hors du
        # panneau — une barre de défilement horizontale pour cacher ce qui
        # était déjà affiché à côté.
        return [
            (tr("Nom"), get("name"), 180, left),
            (tr("Tempo"), get("tempo"), 80, right,
             lambda v: f"{v:.0f} BPM" if v else "—"),
            (tr("Clips"), get("clips"), 60, right),
            (tr("Notes"), get("notes"), 65, right),
            (tr("Mesures"), get("bars"), 75, right,
             lambda v: f"{v:.0f}" if v else "—"),
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
        self._count.setText(tr("%d morceau(x)") % len(rows))

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
            self._stats.set_rows([(tr("Erreur"), str(exc))])
            self._preview.clear()
            for table in (self._clips, self._instruments, self._samples):
                table.setRowCount(0)
            return

        song = self._song
        self._preview.set_song(song)

        stats = song.stats()
        self._stats.set_rows([
            (tr("Tempo"), "%s BPM" % decimal(song.tempo_bpm, 1)),
            (tr("Gamme"), song.scale_name()),
            (tr("Clips de session"), stats["clips"]),
            (tr("Clips d'arrangement"), stats["arrangement_clips"]),
            (tr("Notes"), stats["notes"]),
            (tr("Plus long clip"), tr("%.0f mesures") % stats["bars"]),
            (tr("Sections"), stats["sections"]),
            (tr("Instruments"), stats["instruments"]),
            (tr("Densité"),
             tr("%s notes/mesure") % decimal(stats["density"], 1)),
            (tr("Swing"), f"{song.swing_amount}"),
            (tr("Firmware"), song.firmware or "—"),
        ])

        self._fill_clips(song)
        self._fill_instruments(song)
        self._fill_samples(song)

    def _fill_clips(self, song) -> None:
        self._clips.setRowCount(0)
        for clip in song.clips + song.arrangement_clips:
            index = self._clips.rowCount()
            self._clips.insertRow(index)
            self._clips.setItem(
                index, 0,
                QTableWidgetItem(clip.name or tr("clip %d") % (index + 1)))
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
        labels = {"sound": tr("synthé"), "kit": tr("kit"), "midi": "MIDI",
                  "cv": "CV", "audio": tr("audio")}
        for kind, name, folder in song.preset_refs():
            index = self._instruments.rowCount()
            self._instruments.insertRow(index)
            self._instruments.setItem(
                index, 0, QTableWidgetItem(labels.get(kind, kind)))
            self._instruments.setItem(index, 1, QTableWidgetItem(name or "—"))
            self._instruments.setItem(index, 2,
                                      QTableWidgetItem(folder or "—"))

            present = self._preset_exists(kind, name, folder)
            trouve = self._preset_path(kind, name, folder)
            if present is None:
                label, colour = "—", Qt.GlobalColor.gray
            elif present:
                label, colour = tr("oui"), Qt.GlobalColor.green
            else:
                label, colour = tr("ABSENT"), Qt.GlobalColor.red
            state = QTableWidgetItem(label)
            state.setForeground(colour)
            if trouve:
                state.setToolTip(trouve)
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
        return bool(self._preset_path(kind, name, folder))

    def _preset_path(self, kind: str, name: str, folder: str) -> str:
        """Chemin du preset sur la carte, cherché **comme le fait l'export**.

        Une recherche à l'emplacement exact seulement déclarait « ABSENT »
        40 instruments sur 65 que « Rassembler » trouvait et copiait : le
        dossier noté dans le morceau omet souvent la racine, ou le preset a
        été rangé depuis dans un sous-dossier.
        """
        if kind not in ("sound", "kit") or not name or self.sd is None:
            return ""
        from ...core.songpack import find_preset
        try:
            return find_preset(self.sd, kind, name, folder)
        except Exception:  # noqa: BLE001 - simple affichage
            log.exception("recherche du preset %s impossible", name)
            return ""

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
            state = QTableWidgetItem(tr("oui") if present else tr("ABSENT"))
            state.setForeground(Qt.GlobalColor.green if present
                                else Qt.GlobalColor.red)
            self._samples.setItem(index, 1, state)

    # -- actions ------------------------------------------------------------ #

    def _export_clip(self) -> None:
        """Exporte le clip sélectionné en MIDI."""
        if self._song is None:
            self.say(tr("Aucun morceau sélectionné."))
            return
        clips = self._song.clips + self._song.arrangement_clips
        index = self._clips.currentRow()
        if not 0 <= index < len(clips):
            self.say(tr("Choisissez un clip dans l'onglet « Clips »."))
            return
        clip = clips[index]
        if clip.note_count == 0:
            self.say(tr("Ce clip ne contient aucune note."))
            return

        from PyQt6.QtWidgets import QFileDialog

        from ...core import midifile

        default = f"{Path(self._current).stem} - {clip.name or index + 1}.mid"
        chosen, _f = QFileDialog.getSaveFileName(
            self, tr("Exporter le clip en MIDI"), default,
            tr("Fichier MIDI (*.mid)"))
        if not chosen:
            return
        try:
            midifile.clip_to_midi(Path(chosen), clip, self._song.tempo_bpm)
        except Exception as exc:  # noqa: BLE001
            log.exception("export MIDI impossible")
            self.say(tr("Export impossible : %s") % exc)
            return
        self.say(tr("Clip exporté : %s (%d notes)")
                 % (Path(chosen).name, clip.note_count))

    def _export_song_midi(self) -> None:
        """Exporte le morceau entier : une piste MIDI par clip."""
        if self._song is None:
            self.say(tr("Aucun morceau sélectionné."))
            return

        from PyQt6.QtWidgets import QFileDialog

        from ...core import midifile

        total = sum(c.note_count for c in self._song.clips
                    + self._song.arrangement_clips)
        if total == 0:
            self.say(tr("Ce morceau ne contient aucune note."))
            return

        default = "%s.mid" % Path(self._current).stem
        chosen, _f = QFileDialog.getSaveFileName(
            self, tr("Exporter le morceau en MIDI"), default,
            tr("Fichier MIDI (*.mid)"))
        if not chosen:
            return
        try:
            pistes = midifile.song_to_midi(Path(chosen), self._song)
        except Exception as exc:  # noqa: BLE001
            log.exception("export MIDI du morceau impossible")
            self.say(tr("Export impossible : %s") % exc)
            return
        if not pistes:
            self.say(tr("Aucun clip à exporter."))
            return
        self.say(tr("%d piste(s) exportées dans %s — les clips du Deluge "
                    "étant des boucles, toutes démarrent au début.")
                 % (pistes, Path(chosen).name))

    def _export_pack(self) -> None:
        """Rassemble le morceau et ses dépendances dans un dossier."""
        card = self.card_or_warn()
        if card is None or self._song is None or not self._current:
            self.say(tr("Aucun morceau sélectionné."))
            return

        from PyQt6.QtWidgets import QFileDialog, QMessageBox

        from ...core import songpack
        from ..widgets.common import PlanDialog

        pack = songpack.collect(card, self._current)
        if not pack:
            self.say(tr("Morceau illisible."))
            return

        dialog = PlanDialog(_PackPlan(pack), self,
                            tr("Rassembler « %s »") % pack.name)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self.say(tr("Opération annulée."))
            return

        dossier = QFileDialog.getExistingDirectory(
            self, tr("Où rassembler le morceau ?"), str(Path.home()))
        if not dossier:
            return

        cible = Path(dossier) / songpack.safe_folder_name(pack.name)
        if cible.exists() and any(cible.iterdir()):
            if QMessageBox.question(
                    self, tr("Dossier déjà utilisé"),
                    tr("%s n'est pas vide.\n\nLes fichiers de même nom "
                       "seront remplacés. Continuer ?") % cible.name,
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No) \
                    != QMessageBox.StandardButton.Yes:
                return

        self.say(tr("Copie de %d fichier(s)…") % len(pack))
        self.run(self._do_pack, card, pack, cible,
                 on_result=self.guard(self._pack_done),
                 on_error=self.guard(
                     lambda m: self.say(tr("Échec : %s") % m)),
                 title=tr("Rassemblement"))

    def _do_pack(self, card, pack, cible, progress=None, should_stop=None):
        from ...core import songpack

        copies, erreurs = songpack.write_pack(
            card, pack, cible, apply=True, progress=progress,
            should_stop=should_stop)
        return (copies, erreurs, cible)

    def _pack_done(self, result) -> None:
        if result is None:
            return
        copies, erreurs, cible = result

        from PyQt6.QtWidgets import QMessageBox

        if erreurs:
            QMessageBox.warning(
                self, tr("Rassemblement partiel"),
                tr("%d fichier(s) copiés, %d en échec :%s%s")
                % (len(copies), len(erreurs), _NL + _NL,
                   _NL.join(erreurs[:12])))
        self.say(tr("%d fichier(s) copiés dans %s. Le dossier a la forme "
                    "d'une carte : le recopier à la racine d'une autre "
                    "suffit.")
                 % (len(copies), cible))

    def _export_report(self) -> None:
        """Enregistre une fiche HTML du morceau."""
        if self._song is None:
            self.say(tr("Aucun morceau sélectionné."))
            return

        from PyQt6.QtWidgets import QFileDialog

        default = f"{Path(self._current).stem}.html"
        chosen, _f = QFileDialog.getSaveFileName(
            self, tr("Enregistrer la fiche du morceau"), default,
            tr("Page HTML (*.html)"))
        if not chosen:
            return
        try:
            Path(chosen).write_text(self._report_html(), encoding="utf-8")
        except OSError as exc:
            log.exception("écriture du rapport impossible")
            self.say(tr("Écriture impossible : %s") % exc)
            return
        self.say(tr("Fiche enregistrée : %s") % Path(chosen).name)

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
                "<h2 style='color:#F2453D'>%s</h2><ul>%s</ul>"
                % (esc(tr("Échantillons manquants (%d)") % len(missing)),
                   items))

        # Les intitulés de la fiche, dans la langue de l'interface.
        t = {nom: esc(tr(texte)) for nom, texte in (
            ("chiffres", N_("Chiffres")), ("session", N_("Clips de session")),
            ("arrangement", N_("Clips d'arrangement")), ("notes", N_("Notes")),
            ("long", N_("Plus long clip")), ("sections", N_("Sections")),
            ("instruments", N_("Instruments")), ("densite", N_("Densité")),
            ("clips", N_("Clips")), ("nom", N_("Nom")),
            ("preset", N_("Preset")), ("mesures", N_("Mesures")))}
        longueur = esc(tr("%.0f mesures") % stats["bars"])
        densite = esc(tr("%s notes par mesure")
                      % decimal(stats["density"], 1))

        return f"""<!DOCTYPE html>
<html lang="{language()}"><head><meta charset="utf-8">
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
<p class="meta">{decimal(song.tempo_bpm, 1)} BPM · {esc(song.scale_name())} ·
firmware {esc(song.firmware or '—')}</p>
<h2>{t["chiffres"]}</h2>
<table>
<tr><th>{t["session"]}</th><td>{stats['clips']}</td></tr>
<tr><th>{t["arrangement"]}</th>
<td>{stats['arrangement_clips']}</td></tr>
<tr><th>{t["notes"]}</th><td>{stats['notes']}</td></tr>
<tr><th>{t["long"]}</th><td>{longueur}</td></tr>
<tr><th>{t["sections"]}</th><td>{stats['sections']}</td></tr>
<tr><th>{t["instruments"]}</th><td>{stats['instruments']}</td></tr>
<tr><th>{t["densite"]}</th><td>{densite}</td></tr>
</table>
<h2>{t["clips"]}</h2>
<table><tr><th>{t["nom"]}</th><th>{t["preset"]}</th><th>{t["mesures"]}</th>
<th>{t["notes"]}</th></tr>
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

    def _open_in_atelier(self) -> None:
        """Le morceau choisi part dans l'atelier : ses pistes, ses clips et
        ses sections y deviennent ceux du projet — rien n'est modifié."""
        if not self._current:
            self.say(tr("Choisissez d'abord un morceau."))
            return
        self.navigateRequested.emit("Atelier#%s" % self._current)

    # -- rafraîchissement --------------------------------------------------- #

    def _refresh(self) -> None:
        self._reload()
