# -*- coding: utf-8 -*-
"""Socle commun aux pages de l'application.

Chaque page respecte le contrat de la SPEC §5.5 : un signal ``status``, une
méthode :meth:`Page.refresh` appelée quand la page devient visible, et les
attributs de classe ``TITLE`` et ``ICON``.

:class:`Page` ajoute ce que les neuf pages refont sinon à l'identique :

* **un rempart autour de ``refresh``.** La SPEC §6.3 exige qu'aucune exception
  n'atteigne la boucle Qt ; les pages redéfinissent ``_refresh`` et le socle
  l'enveloppe ;
* **un état vide**, puisque l'application doit démarrer sans carte valide
  (SPEC §6.1) ;
* **des raccourcis** vers la carte, l'index et le lecteur audio, avec le
  message d'avertissement prêt à l'emploi quand la carte manque.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...config import AppContext
from .. import icons
from ..theme import GOLD, GREY, PAD
from ..widgets.common import EmptyState, SectionTitle

log = logging.getLogger(__name__)


class Page(QWidget):
    """Base de toutes les pages."""

    #: Message pour la barre d'état.
    status = pyqtSignal(str)
    #: Demande d'aller aux réglages, relayée par la fenêtre principale.
    settingsRequested = pyqtSignal()

    #: Titre affiché dans la navigation, en français.
    TITLE = "Page"
    #: Nom d'icône, parmi ceux de :data:`delugeapp.ui.icons.ICON_NAMES`.
    ICON = "info"
    #: Message de l'état vide quand la carte manque.
    EMPTY_MESSAGE = "Aucune carte SD"
    EMPTY_DETAIL = ("Indiquez l'emplacement de votre carte dans les réglages, "
                    "ou branchez-la.")
    #: Vrai si la page a besoin d'une carte valide pour montrer quoi que ce soit.
    NEEDS_CARD = True

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._built = False

        self._stack = QStackedWidget(self)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._stack)

        self._content = QWidget(self)
        self._stack.addWidget(self._content)

        self._empty = EmptyState(self.EMPTY_MESSAGE, "warning",
                                 "Ouvrir les réglages", detail=self.EMPTY_DETAIL)
        self._empty.actionClicked.connect(self.settingsRequested.emit)
        self._stack.addWidget(self._empty)

    # -- construction paresseuse -------------------------------------------- #

    def content(self) -> QWidget:
        """Widget dans lequel la page bâtit son interface."""
        return self._content

    def build(self) -> None:
        """Construit l'interface. À redéfinir par chaque page."""

    def _ensure_built(self) -> None:
        """Bâtit l'interface au premier affichage, pas à la création.

        Neuf pages construites d'emblée allongeraient le démarrage sans
        raison : l'utilisateur n'en voit qu'une à la fois.
        """
        if self._built:
            return
        self._built = True
        try:
            self.build()
        except Exception:  # noqa: BLE001 - rempart, cf. SPEC §6.3
            log.exception("construction de la page %s en échec", self.TITLE)

    # -- rafraîchissement --------------------------------------------------- #

    def refresh(self) -> None:
        """Met la page à jour. Ne laisse jamais passer d'exception."""
        self._ensure_built()
        if self.NEEDS_CARD and not self.ctx.has_card:
            self._stack.setCurrentWidget(self._empty)
            return
        self._stack.setCurrentWidget(self._content)
        try:
            self._refresh()
        except Exception:  # noqa: BLE001 - rempart, cf. SPEC §6.3
            log.exception("rafraîchissement de la page %s en échec", self.TITLE)
            self.say("Une erreur est survenue : voir le journal.")

    def _refresh(self) -> None:
        """Corps du rafraîchissement. À redéfinir."""

    def showEvent(self, event) -> None:  # noqa: N802 - API Qt
        super().showEvent(event)
        self.refresh()

    # -- confort ------------------------------------------------------------ #

    def say(self, message: str) -> None:
        """Envoie un message à la barre d'état."""
        try:
            self.status.emit(str(message))
        except Exception:  # noqa: BLE001
            log.debug("message d'état non transmis")

    @property
    def lib(self):
        """Index SQLite."""
        return self.ctx.lib

    @property
    def sd(self):
        """Carte SD, éventuellement ``None``."""
        return self.ctx.sd

    @property
    def player(self):
        """Lecteur audio partagé."""
        return self.ctx.player

    def card_or_warn(self):
        """Carte SD, ou ``None`` après un avertissement à l'utilisateur."""
        return self.ctx.sd_or_warn(self)

    def guard(self, fn: Callable[..., Any]) -> Callable[..., None]:
        """Enveloppe un gestionnaire de signal dans un ``try/except``.

        La SPEC §6.3 l'exige pour chaque gestionnaire : une exception dans un
        connecteur Qt remonte sinon jusqu'à la boucle d'événements.
        """
        def wrapper(*args, **kwargs) -> None:
            try:
                fn(*args, **kwargs)
            except Exception:  # noqa: BLE001
                log.exception("action de la page %s en échec", self.TITLE)
                self.say("Action impossible : voir le journal.")
        return wrapper

    def run(self, fn, *args, **kwargs):
        """Lance un travail long hors du fil de l'interface."""
        from ..tasks import run_task

        kwargs.setdefault("title", "Traitement…")
        return run_task(self, fn, *args, **kwargs)


def page_header(title: str, subtitle: str = "",
                color: str = GOLD) -> tuple[QWidget, QHBoxLayout]:
    """En-tête de page : titre, sous-titre, et une barre d'actions à droite.

    Retourne le widget et la disposition dans laquelle ajouter les boutons.
    """
    host = QWidget()
    layout = QHBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)

    column = QVBoxLayout()
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(0)
    heading = QLabel(title)
    heading.setProperty("role", "h1")
    column.addWidget(heading)
    if subtitle:
        hint = QLabel(subtitle)
        hint.setProperty("role", "subtitle")
        column.addWidget(hint)
    layout.addLayout(column)
    layout.addStretch(1)

    actions = QHBoxLayout()
    actions.setContentsMargins(0, 0, 0, 0)
    actions.setSpacing(6)
    layout.addLayout(actions)
    return host, actions


def tool_button(label: str, icon_name: str = "", tooltip: str = "",
                primary: bool = False, color: str = GOLD) -> QPushButton:
    """Bouton d'action d'une barre de page."""
    button = QPushButton(label)
    if icon_name:
        button.setIcon(icons.icon(icon_name, color if primary else GREY, 16))
    if tooltip:
        button.setToolTip(tooltip)
    if primary:
        button.setObjectName("Primary")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button
