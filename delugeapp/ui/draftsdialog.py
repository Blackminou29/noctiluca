# -*- coding: utf-8 -*-
"""Les brouillons de l'atelier : la liste des morceaux gardés sur l'ordinateur.

Chaque morceau que l'atelier remplace — on recompose, on ouvre un morceau du
Deluge — ou écrit sur la carte est rangé (:mod:`delugeapp.core.atelierstore`).
Ce dialogue les montre, le plus récent en tête : un nom, un résumé, la date,
et s'il a été écrit sur la carte. [Ouvrir] en remet un dans l'atelier, tel
qu'il était ; [Supprimer] l'efface de l'ordinateur. La carte n'est jamais
touchée.

Le dialogue ne lit ni n'écrit rien lui-même : la page lui donne les fiches,
et répond à ses deux demandes.
"""

from __future__ import annotations

import logging
from datetime import datetime

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QListWidget,
                             QListWidgetItem, QVBoxLayout)

from ..i18n import clock, full_date, tr
from .pages.base import tool_button
from .theme import GOLD, accent_qss
from .widgets.common import hint_in_list

log = logging.getLogger(__name__)

__all__ = ["DraftsDialog"]


def _when(saved: float) -> str:
    """« aujourd'hui à 21h35 », ou la date entière."""
    try:
        moment = datetime.fromtimestamp(float(saved))
    except (OverflowError, OSError, ValueError):
        return ""
    if moment.date() == datetime.now().date():
        return tr("aujourd'hui à %s") % clock(moment)
    return tr("le %s à %s") % (full_date(moment), clock(moment))


class DraftsDialog(QDialog):
    """La liste des brouillons : en rouvrir un, en supprimer."""

    #: [Supprimer] : l'identifiant du brouillon à retirer. La page le
    #: retire, puis appelle :meth:`forget`.
    deleteRequested = pyqtSignal(str)

    def __init__(self, entries, summary=None, current: str = "",
                 color: str = GOLD, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Brouillons de l'atelier"))
        self.setMinimumSize(560, 380)
        try:
            self.setStyleSheet(accent_qss(color))
        except Exception as exc:        # noqa: BLE001 - une teinte, rien de plus
            log.debug("teinte des brouillons impossible : %s", exc)
        self._summary = summary
        self._current = str(current or "")
        self._chosen = ""

        column = QVBoxLayout(self)
        column.setContentsMargins(16, 14, 16, 14)
        column.setSpacing(10)
        hint = QLabel(tr(
            "Les morceaux de l'atelier gardés sur cet ordinateur : chaque "
            "morceau que vous remplacez ou écrivez sur la carte est rangé "
            "ici, avec ses sons, ses clips et ses sections. Ouvrez-en un "
            "pour le reprendre là où vous l'aviez laissé — le morceau en "
            "cours prend alors sa place dans la liste."))
        hint.setProperty("role", "subtitle")
        hint.setWordWrap(True)
        column.addWidget(hint)

        self._list = QListWidget()
        self._list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setWordWrap(True)
        self._list.currentRowChanged.connect(lambda _r: self._update())
        self._list.itemDoubleClicked.connect(lambda _i: self._open())
        column.addWidget(self._list, 1)

        row = QHBoxLayout()
        row.setSpacing(8)
        self._open_button = tool_button(tr("Ouvrir"), "import", primary=True,
                                        color=color)
        self._open_button.setToolTip(tr(
            "Remet le brouillon choisi dans l'atelier, tel que vous l'aviez "
            "laissé ; le morceau en cours est rangé à sa place"))
        self._open_button.clicked.connect(lambda _c=False: self._open())
        row.addWidget(self._open_button)
        self._delete_button = tool_button(tr("Supprimer"), "trash")
        self._delete_button.setToolTip(tr(
            "Efface le brouillon choisi de cet ordinateur — pour de bon. Un "
            "morceau écrit sur la carte y reste"))
        self._delete_button.clicked.connect(lambda _c=False: self._delete())
        row.addWidget(self._delete_button)
        row.addStretch(1)
        self._close_button = tool_button(tr("Fermer"))
        self._close_button.setToolTip(tr("Ferme la liste sans rien changer"))
        self._close_button.clicked.connect(lambda _c=False: self.reject())
        row.addWidget(self._close_button)
        column.addLayout(row)

        self._fill(list(entries or ()))

    # -- la liste ----------------------------------------------------------- #

    def _line(self, entry) -> str:
        details = []
        if self._summary is not None:
            try:
                details.append(self._summary(entry))
            except Exception as exc:    # noqa: BLE001 - un résumé manque
                log.debug("résumé d'un brouillon impossible : %s", exc)
        if entry.meta.get("written"):
            details.append(tr("écrit sur la carte"))
        if entry.ident == self._current:
            details.append(tr("le morceau en cours"))
        details.append(_when(entry.saved))
        return "%s\n%s" % (entry.name or tr("Sans nom"),
                           " · ".join(d for d in details if d))

    def _fill(self, entries) -> None:
        self._list.clear()
        for entry in entries:
            item = QListWidgetItem(self._line(entry))
            item.setData(Qt.ItemDataRole.UserRole, entry.ident)
            self._list.addItem(item)
        if self._list.count():
            self._list.setCurrentRow(0)
        else:
            hint_in_list(self._list, "  " + tr(
                "Aucun brouillon pour l'instant : le premier morceau que "
                "vous remplacerez ou écrirez viendra ici."))
        self._update()

    def idents(self) -> list[str]:
        """Les brouillons listés, dans l'ordre."""
        return [self._list.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self._list.count())
                if self._list.item(i).data(Qt.ItemDataRole.UserRole)]

    def _ident(self) -> str:
        item = self._list.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole) or "") if item else ""

    def _update(self) -> None:
        ident = self._ident()
        self._open_button.setEnabled(bool(ident) and ident != self._current)
        self._delete_button.setEnabled(bool(ident))

    # -- les deux gestes ---------------------------------------------------- #

    def chosen(self) -> str:
        """L'identifiant du brouillon à ouvrir, une fois le dialogue
        accepté."""
        return self._chosen

    def _open(self) -> None:
        ident = self._ident()
        if not ident or ident == self._current:
            return
        self._chosen = ident
        self.accept()

    def _delete(self) -> None:
        ident = self._ident()
        if ident:
            self.deleteRequested.emit(ident)

    def forget(self, ident: str) -> None:
        """Retire de la liste un brouillon supprimé."""
        for row in range(self._list.count()):
            if self._list.item(row).data(Qt.ItemDataRole.UserRole) == ident:
                self._list.takeItem(row)
                break
        if not self._list.count():
            self._fill([])
        self._update()
