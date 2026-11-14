# -*- coding: utf-8 -*-
"""Choisir soi-même l'échantillon d'une rangée de kit.

[Autre son] en tire un au hasard, qu'on entend aussitôt ; quand on cherche
*la* caisse claire, il fallait cliquer jusqu'à tomber dessus. Ce dialogue
montre tous les sons du même rôle que la bibliothèque connaît
(:func:`delugeapp.core.kitgen.row_candidates`) — ceux de la même machine
d'abord, puis ceux qui conviennent au genre, puis les autres — et **joue
chacun dès qu'on le choisit**. Un filtre resserre la liste par le nom ou la
machine. [Utiliser ce son] (ou un double-clic) le met à la rangée.

Le dialogue ne touche ni au kit ni à la carte : la page lui donne la liste,
et reprend le son choisi.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QVBoxLayout)

from ..core import units
from ..i18n import tr
from .pages.base import tool_button
from .theme import GOLD, accent_qss
from .widgets.common import hint_in_list

log = logging.getLogger(__name__)

__all__ = ["RowSampleDialog", "choose_row_sample"]


def choose_row_sample(page, kit, index: int, genre: str = "techno"):
    """Ouvre le choix de l'échantillon de la rangée ``index`` du kit, sur
    la bibliothèque de la page ; chaque son s'écoute sur l'ordinateur. Rend
    le candidat retenu, ou ``None`` (fermé, ou rien à proposer — la page le
    dit alors)."""
    from ..core import kitgen

    candidates = kitgen.row_candidates(kit, index, page.lib, genre=genre)
    if len([c for c in candidates if not c.get("current")]) == 0:
        page.say(tr("La bibliothèque n'a pas d'autre son pour cette "
                    "rangée."))
        return None
    row = kit.rows[index]

    def play(candidate) -> None:
        player, card = page.player, page.sd
        if player is None or card is None:
            return
        player.set_volume(page.ctx.settings.preview_volume)
        player.play_file(card.abs(candidate["rel"]))

    dialog = RowSampleDialog(candidates, kitgen.row_role(row),
                             row_name=row.name, play=play,
                             color=getattr(page, "color", GOLD), parent=page)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.chosen()


class RowSampleDialog(QDialog):
    """La liste des sons qui peuvent jouer une rangée ; un clic l'écoute."""

    def __init__(self, candidates, role: str, row_name: str = "",
                 play=None, color: str = GOLD, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Choisir l'échantillon — %s")
                            % (row_name or tr(role)))
        self.setMinimumSize(560, 420)
        try:
            self.setStyleSheet(accent_qss(color))
        except Exception as exc:        # noqa: BLE001 - une teinte, rien de plus
            log.debug("teinte du choix d'échantillon impossible : %s", exc)
        self._candidates = list(candidates or ())
        self._play = play
        self._chosen: dict | None = None

        column = QVBoxLayout(self)
        column.setContentsMargins(16, 14, 16, 14)
        column.setSpacing(10)
        hint = QLabel(tr(
            "Les sons de votre bibliothèque qui peuvent jouer cette rangée "
            "(%s) : ceux de la même machine d'abord, puis ceux qui "
            "conviennent au genre. Un clic en écoute un.") % tr(role))
        hint.setProperty("role", "subtitle")
        hint.setWordWrap(True)
        column.addWidget(hint)

        self._filter = QLineEdit()
        self._filter.setPlaceholderText(tr("Filtrer par nom ou machine…"))
        self._filter.setToolTip(tr("Ne garde que les sons dont le nom ou la "
                                   "machine contient ces lettres"))
        self._filter.setClearButtonEnabled(True)
        self._filter.textChanged.connect(lambda _t: self._fill())
        column.addWidget(self._filter)

        self._list = QListWidget()
        self._list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.currentRowChanged.connect(lambda _r: self._listen())
        self._list.itemDoubleClicked.connect(lambda _i: self._use())
        column.addWidget(self._list, 1)

        row = QHBoxLayout()
        row.setSpacing(8)
        self._use_button = tool_button(tr("Utiliser ce son"), "check",
                                       primary=True, color=color)
        self._use_button.setToolTip(tr(
            "Met le son choisi à la rangée ; son nom, son volume et son "
            "panoramique suivent son rôle  (rien n'est écrit sur la carte)"))
        self._use_button.clicked.connect(lambda _c=False: self._use())
        row.addWidget(self._use_button)
        self._listen_button = tool_button(tr("Écouter"), "play")
        self._listen_button.setToolTip(tr("Rejoue le son choisi"))
        self._listen_button.clicked.connect(lambda _c=False: self._listen())
        row.addWidget(self._listen_button)
        row.addStretch(1)
        self._close_button = tool_button(tr("Fermer"))
        self._close_button.setToolTip(tr("Ferme la liste ; la rangée garde "
                                         "son son"))
        self._close_button.clicked.connect(lambda _c=False: self.reject())
        row.addWidget(self._close_button)
        column.addLayout(row)
        self._fill()

    # -- la liste ----------------------------------------------------------- #

    def _line(self, candidate: dict) -> str:
        details = [tr(candidate.get("family") or "")]
        if candidate.get("duration"):
            details.append(units.human_duration(float(candidate["duration"])))
        if candidate.get("current"):
            details.append(tr("le son actuel"))
        return "%s   — %s" % (candidate.get("name") or "",
                              " · ".join(d for d in details if d))

    def _fill(self) -> None:
        wanted = self._filter.text().strip().casefold()
        self._list.blockSignals(True)
        self._list.clear()
        for index, candidate in enumerate(self._candidates):
            text = self._line(candidate)
            if wanted and wanted not in text.casefold():
                continue
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setToolTip(str(candidate.get("rel") or ""))
            self._list.addItem(item)
        self._list.blockSignals(False)
        if not self._list.count():
            hint_in_list(self._list, "  " + (
                tr("Aucun son ne correspond au filtre.") if wanted else
                tr("La bibliothèque n'a pas d'autre son de ce rôle : "
                   "lancez une analyse de la carte.")))
        self._update()

    def count(self) -> int:
        """Combien de sons la liste montre."""
        return sum(1 for i in range(self._list.count())
                   if self._list.item(i).data(Qt.ItemDataRole.UserRole)
                   is not None)

    def _candidate(self) -> dict | None:
        item = self._list.currentItem()
        if item is None:
            return None
        index = item.data(Qt.ItemDataRole.UserRole)
        if index is None:
            return None
        return self._candidates[int(index)]

    def _update(self) -> None:
        candidate = self._candidate()
        self._use_button.setEnabled(candidate is not None
                                    and not candidate.get("current"))
        self._listen_button.setEnabled(candidate is not None)

    # -- écouter, choisir --------------------------------------------------- #

    def _listen(self) -> None:
        self._update()
        candidate = self._candidate()
        if candidate is None or self._play is None:
            return
        try:
            self._play(candidate)
        except Exception as exc:        # noqa: BLE001 - une écoute, rien de plus
            log.debug("écoute d'un candidat impossible : %s", exc)

    def chosen(self) -> dict | None:
        """Le son retenu, une fois le dialogue accepté."""
        return self._chosen

    def _use(self) -> None:
        candidate = self._candidate()
        if candidate is None or candidate.get("current"):
            return
        self._chosen = candidate
        self.accept()
