# -*- coding: utf-8 -*-
"""Briques d'interface communes à toutes les pages.

Ces widgets portent les noms d'objet et les propriétés que la feuille de style
de :mod:`delugeapp.ui.theme` attend (``QFrame#Card``, ``QFrame#Tile``,
``QLabel[role="value"]``…). Leur apparence vient donc du thème : on ne fixe
ici que ce que le QSS ne sait pas faire, c'est-à-dire la structure et les
tracés au :class:`QPainter`.

Contient aussi :class:`RowTableModel`, le modèle de tableau que les pages
doivent utiliser pour les grandes listes. La SPEC §6.5 interdit
``QTableWidget`` au-delà de quelques centaines de lignes : la bibliothèque de
l'utilisateur en compte 1 741, et un ``QTableWidget`` y crée autant d'objets
graphiques que de cellules.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Sequence

from PyQt6.QtCore import (
    QAbstractTableModel,
    QEvent,
    QObject,
    QModelIndex,
    QRectF,
    QSize,
    QSortFilterProxyModel,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...core import units as _units
from .. import art, icons
from ..theme import (
    BORDER_SOFT,
    BORDER_TOP,
    GOLD,
    GREY,
    PAD,
    PAD_CYCLE,
    PAD_DIM,
    PAD_RED,
    PAD_WHITE,
    PANEL_HI,
    RADIUS,
    TEXT_SOFT,
    _rgb,
    mix,
    readable,
    text_on,
    with_alpha,
)

log = logging.getLogger(__name__)

#: Délai avant émission d'une recherche, en millisecondes (cf. SPEC §5.4).
SEARCH_DEBOUNCE_MS = 250


# --------------------------------------------------------------------------- #
# Titres et panneaux
# --------------------------------------------------------------------------- #

#: Hauteur d'un titre de section : une ligne, le pad, le filet.
SECTION_HEIGHT = 24


class SectionTitle(QWidget):
    """Titre de section à la manière du guide : un petit pad allumé, le
    libellé en capitales espacées, puis un filet qui s'efface vers la droite.

    Le filet était sous le libellé, sur une seconde ligne : il est passé à
    sa droite, sur la même ligne. Chaque panneau y gagne huit pixels, et le
    titre ressemble à une sérigraphie de façade plutôt qu'à un intertitre
    de document.
    """

    def __init__(self, title: str = "", parent: QWidget | None = None,
                 color: str = GOLD) -> None:
        super().__init__(parent)
        self._color = color
        # Hauteur fixe : sans cela le titre s'étire quand le panneau est plus
        # haut que son contenu, et son filet part flotter soixante pixels
        # plus bas, détaché du libellé qu'il souligne.
        self.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Fixed)
        self.setFixedHeight(SECTION_HEIGHT)
        layout = QHBoxLayout(self)
        # La marge de gauche est la place du pad.
        layout.setContentsMargins(19, 0, 0, 0)
        layout.setSpacing(0)

        self._label = QLabel(title, self)
        self._label.setProperty("role", "section")
        if color != GOLD:
            self._label.setStyleSheet("color: %s;" % readable(color))
        layout.addWidget(self._label)
        layout.addStretch(1)

    def setText(self, text: str) -> None:
        """Change le libellé."""
        self._label.setText(text)

    def text(self) -> str:
        return self._label.text()

    def color(self) -> str:
        """Couleur actuelle du titre."""
        return self._color

    def set_color(self, color: str) -> None:
        """Change la couleur du trait **et du libellé**.

        Le libellé suivait l'accent global du thème : tous les titres de
        l'application avaient donc la même teinte, quelle que soit la page.

        Le **trait** garde la couleur exacte de la page ; le **libellé**
        prend la variante lisible. Mesuré : le violet des presets tombait à
        4,26 de contraste et l'indigo des réglages à 3,51, là où un texte
        courant en demande 4,5.
        """
        self._color = color
        self._label.setStyleSheet("color: %s;" % readable(color))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - API Qt
        super().paintEvent(event)
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            milieu = self.height() / 2.0

            # Le petit pad allumé, à gauche du libellé.
            pad = QRectF(2.0, milieu - 4.5, 9.0, 9.0)
            art.paint_pad(painter, pad, self._color, glow=0.45, radius=2.5)

            # Le filet : franc près du libellé, estompé vers la droite. Les
            # couleurs passent par setAlphaF : `theme.with_alpha` rend une
            # chaîne « rgba(…) » destinée au QSS, que QColor ne sait pas lire.
            texte = self._label.geometry()
            debut = float(texte.right() + 12)
            fin = float(self.width() - 2)
            if fin - debut > 8:
                start = QColor(self._color)
                start.setAlphaF(0.65)
                middle = QColor(self._color)
                middle.setAlphaF(0.22)
                end = QColor(self._color)
                end.setAlphaF(0.0)
                gradient = QLinearGradient(debut, 0.0, fin, 0.0)
                gradient.setColorAt(0.0, start)
                gradient.setColorAt(0.4, middle)
                gradient.setColorAt(1.0, end)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(gradient)
                painter.drawRect(QRectF(debut, milieu - 0.5, fin - debut, 1.2))
            painter.end()
        except Exception as exc:  # noqa: BLE001 - un tracé ne doit rien casser
            log.debug("tracé du titre de section impossible : %s", exc)


class Card(QFrame):
    """Panneau arrondi, avec un titre optionnel et son trait or.

    Le contenu s'ajoute dans :meth:`body`, qui est la disposition réservée à
    l'appelant — les marges et le titre restent sous le contrôle du widget.
    """

    def __init__(self, title: str = "", parent: QWidget | None = None,
                 color: str = GOLD) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setProperty("card", "true")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(PAD, PAD, PAD, PAD)
        outer.setSpacing(8)

        self._title: SectionTitle | None = None
        if title:
            self._title = SectionTitle(title, self, color=color)
            outer.addWidget(self._title)

        self._body = QVBoxLayout()
        self._body.setContentsMargins(0, 0, 0, 0)
        self._body.setSpacing(6)
        outer.addLayout(self._body)

    def body(self) -> QVBoxLayout:
        """Disposition dans laquelle placer le contenu."""
        return self._body

    def set_title(self, title: str) -> None:
        """Change le titre, ou l'ajoute s'il n'y en avait pas."""
        if self._title is None:
            self._title = SectionTitle(title, self)
            layout = self.layout()
            if layout is not None:
                layout.insertWidget(0, self._title)
        else:
            self._title.setText(title)


class LitPad(QWidget):
    """Une icône posée sur un pad allumé, avec son halo.

    C'est la pièce qui dit « cette chose a une couleur et elle est active » :
    en-tête de page, tuiles du tableau de bord, raccourcis. Le widget réserve
    autour du pad la place de son halo, pour que la lumière ne soit pas
    coupée net par le bord.
    """

    def __init__(self, icon_name: str, color: str = GOLD, size: int = 44,
                 parent: QWidget | None = None, glow: float = 0.42,
                 halo: int = 8) -> None:
        super().__init__(parent)
        self._icon = str(icon_name or "")
        self._color = color
        self._size = max(12, int(size))
        self._glow = float(glow)
        self._halo = max(0, int(halo))
        cote = self._size + 2 * self._halo
        self.setFixedSize(cote, cote)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents,
                          True)

    def color(self) -> str:
        return self._color

    def set_color(self, color: str) -> None:
        self._color = color or GOLD
        self.update()

    def set_icon(self, icon_name: str) -> None:
        self._icon = str(icon_name or "")
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - API Qt
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            pad = QRectF(self._halo, self._halo, self._size, self._size)
            art.paint_pad(painter, pad, self._color, glow=self._glow,
                          radius=self._size * 0.26)
            if self._icon:
                taille = int(self._size * 0.52)
                pixmap = icons.icon(self._icon, text_on(self._color),
                                    taille).pixmap(taille, taille)
                painter.drawPixmap(
                    int(pad.center().x() - taille / 2),
                    int(pad.center().y() - taille / 2), pixmap)
            painter.end()
        except Exception as exc:  # noqa: BLE001 - un décor ne casse rien
            log.debug("pad allumé non tracé : %s", exc)


class StatTile(QFrame):
    """Grande valeur, libellé, couleur de pad et icône : la tuile du tableau
    de bord.

    L'icône est posée sur un pad allumé, et la tuile prend un voile de sa
    couleur qui s'estompe vers la droite : six tuiles se distinguent d'un
    coup d'œil, comme six rangées de pads.
    """

    clicked = pyqtSignal()

    def __init__(self, label: str, value: str = "—", color: str = GOLD,
                 icon_name: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Tile")
        self.setProperty("tile", "true")
        self._color = color
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 6, PAD, 6)
        layout.setSpacing(6)

        self._badge: LitPad | None = None
        if icon_name:
            self._badge = LitPad(icon_name, color, 40, self, halo=9)
            layout.addWidget(self._badge)

        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)

        self._value = QLabel(str(value), self)
        self._value.setProperty("role", "value")
        column.addWidget(self._value)

        self._label = QLabel(label, self)
        self._label.setProperty("role", "caption")
        column.addWidget(self._label)

        layout.addLayout(column, 1)
        self.set_color(color)

    def set_clickable(self, clickable: bool) -> None:
        """Dit si la tuile mène quelque part.

        Le curseur de main était posé sur les six tuiles, y compris sur
        « Durée d'audio » et « Espace libre », qui ne mènent nulle part : la
        promesse d'un clic qui ne venait jamais.
        """
        self.setCursor(Qt.CursorShape.PointingHandCursor if clickable
                       else Qt.CursorShape.ArrowCursor)

    def set_value(self, v: Any) -> None:
        """Met à jour la valeur affichée."""
        self._value.setText("—" if v is None else str(v))

    def set_label(self, text: str) -> None:
        self._label.setText(text)

    def set_color(self, color: str) -> None:
        """Change la couleur du pad, du voile de fond et du survol.

        Appelée **depuis le constructeur** : sans cela la couleur passée à
        la création restait dans ``self._color`` sans jamais atteindre la
        feuille de style, et les six tuiles du tableau de bord portaient
        toutes le liseré or du style global — alors que leurs icônes,
        elles, étaient bien colorées.
        """
        self._color = color
        if self._badge is not None:
            self._badge.set_color(color)
        r, g, b = _rgb(color)
        self.setStyleSheet(
            "QFrame#Tile {"
            " border: 1px solid %s; border-top-color: %s;"
            " background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,"
            " stop:0 rgba(%d,%d,%d,34), stop:0.55 rgba(%d,%d,%d,8),"
            " stop:1 rgba(%d,%d,%d,0)); }"
            "QFrame#Tile:hover {"
            " border-color: rgba(%d,%d,%d,140);"
            " background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,"
            " stop:0 rgba(%d,%d,%d,60), stop:0.6 rgba(%d,%d,%d,16),"
            " stop:1 rgba(%d,%d,%d,4)); }" % (
                BORDER_SOFT, BORDER_TOP,
                r, g, b, r, g, b, r, g, b,
                r, g, b,
                r, g, b, r, g, b, r, g, b))

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - API Qt
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


# --------------------------------------------------------------------------- #
# Étiquettes
# --------------------------------------------------------------------------- #

class Badge(QLabel):
    """Petite pastille de texte colorée."""

    def __init__(self, text: str = "", color: str = GOLD,
                 parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.set_color(color)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def set_color(self, color: str) -> None:
        """Applique une couleur de fond translucide et un texte assorti."""
        self.setStyleSheet(
            f"QLabel {{ background-color: {with_alpha(color, 0.18)};"
            f" color: {color}; border: 1px solid {with_alpha(color, 0.45)};"
            f" border-radius: {RADIUS - 2}px; padding: 1px 7px;"
            f" font-size: 8pt; font-weight: 600; }}")


class TagChip(QWidget):
    """Étiquette cliquable, avec une croix de retrait optionnelle."""

    clicked = pyqtSignal(str)
    removed = pyqtSignal(str)

    def __init__(self, name: str, color: str = GOLD, removable: bool = True,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._name = name
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._label = QPushButton(name, self)
        self._label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._label.setFlat(True)
        self._label.clicked.connect(lambda: self.clicked.emit(self._name))
        self._label.setStyleSheet(
            f"QPushButton {{ background-color: {with_alpha(color, 0.16)};"
            f" color: {color}; border: 1px solid {with_alpha(color, 0.40)};"
            f" border-top-left-radius: {RADIUS}px;"
            f" border-bottom-left-radius: {RADIUS}px;"
            f" border-top-right-radius: {0 if removable else RADIUS}px;"
            f" border-bottom-right-radius: {0 if removable else RADIUS}px;"
            f" padding: 2px 8px; font-size: 8pt; }}"
            f"QPushButton:hover {{ background-color: {with_alpha(color, 0.28)}; }}")
        layout.addWidget(self._label)

        if removable:
            close = QToolButton(self)
            close.setIcon(icons.icon("minus", color, 12))
            close.setCursor(Qt.CursorShape.PointingHandCursor)
            close.setToolTip(f"Retirer l'étiquette « {name} »")
            close.clicked.connect(lambda: self.removed.emit(self._name))
            close.setStyleSheet(
                f"QToolButton {{ background-color: {with_alpha(color, 0.16)};"
                f" border: 1px solid {with_alpha(color, 0.40)};"
                f" border-left: none;"
                f" border-top-right-radius: {RADIUS}px;"
                f" border-bottom-right-radius: {RADIUS}px;"
                f" padding: 2px 5px; }}"
                f"QToolButton:hover {{ background-color: {with_alpha(color, 0.30)}; }}")
            layout.addWidget(close)

    def name(self) -> str:
        return self._name


class ElidedLabel(QLabel):
    """Libellé qui coupe son texte avec des points de suspension.

    Un ``QLabel`` ordinaire impose sa largeur au conteneur dès que le texte
    est long ; celui-ci s'adapte et montre l'intégralité en infobulle.
    """

    def __init__(self, text: str = "", parent: QWidget | None = None,
                 mode: Qt.TextElideMode = Qt.TextElideMode.ElideRight) -> None:
        super().__init__(parent)
        self._full = text
        self._mode = mode
        self.setSizePolicy(QSizePolicy.Policy.Ignored,
                           QSizePolicy.Policy.Preferred)
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 - API Qt
        self._full = str(text or "")
        self.setToolTip(self._full)
        super().setText(self._elided())

    def full_text(self) -> str:
        return self._full

    def _elided(self) -> str:
        metrics = self.fontMetrics()
        width = max(16, self.width() - 2)
        return metrics.elidedText(self._full, self._mode, width)

    def resizeEvent(self, event) -> None:  # noqa: N802 - API Qt
        super().resizeEvent(event)
        super().setText(self._elided())


# --------------------------------------------------------------------------- #
# Saisie
# --------------------------------------------------------------------------- #

class SearchBar(QLineEdit):
    """Champ de recherche avec loupe, effacement, et émission différée.

    Le signal :attr:`searchChanged` n'est émis qu'après
    :data:`SEARCH_DEBOUNCE_MS` d'inactivité : sans cela, chaque frappe
    relancerait une requête sur les 1 741 échantillons de la carte.
    """

    searchChanged = pyqtSignal(str)

    def __init__(self, placeholder: str = "Rechercher…",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)
        # Des fichiers glissés sur la fenêtre partent vers le Deluge : le
        # champ ne doit pas les avaler en y écrivant leur adresse.
        self.setAcceptDrops(False)
        self.addAction(icons.icon("search", GREY, 16),
                       QLineEdit.ActionPosition.LeadingPosition)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(SEARCH_DEBOUNCE_MS)
        self._timer.timeout.connect(self._emit)
        self.textChanged.connect(lambda _t: self._timer.start())
        # Entrée déclenche immédiatement, sans attendre le délai.
        self.returnPressed.connect(self._emit_now)

    def _emit(self) -> None:
        try:
            self.searchChanged.emit(self.text().strip())
        except Exception:  # noqa: BLE001 - un abonné ne doit rien casser
            log.exception("abonné à searchChanged en échec")

    def _emit_now(self) -> None:
        self._timer.stop()
        self._emit()

    def showEvent(self, event) -> None:            # noqa: N802 - API Qt
        """Nomme la croix d'effacement, que Qt crée sans infobulle.

        Elle n'existe pas encore à la construction : Qt l'ajoute au premier
        affichage. C'est une commande visible comme une autre, elle doit se
        présenter.
        """
        super().showEvent(event)
        try:
            for bouton in self.findChildren(QToolButton):
                if not bouton.toolTip():
                    bouton.setToolTip("Effacer la recherche")
        except Exception as exc:                   # noqa: BLE001
            log.debug("croix d'effacement sans infobulle : %s", exc)


class StarRating(QWidget):
    """Note de 0 à 5 étoiles, modifiable au clic."""

    changed = pyqtSignal(int)

    def __init__(self, value: int = 0, parent: QWidget | None = None,
                 size: int = 16, editable: bool = True) -> None:
        super().__init__(parent)
        self._value = max(0, min(5, int(value)))
        self._hover = -1
        self._size = max(8, int(size))
        self._editable = bool(editable)
        self.setFixedHeight(self._size + 4)
        self.setMinimumWidth(self._size * 5 + 8)
        self.setMouseTracking(True)
        if editable:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:  # noqa: N802 - API Qt
        return QSize(self._size * 5 + 8, self._size + 4)

    def value(self) -> int:
        return self._value

    def set_value(self, value: int) -> None:
        """Change la note sans émettre de signal."""
        self._value = max(0, min(5, int(value)))
        self.update()

    def _star_at(self, x: int) -> int:
        return max(0, min(4, int(x // max(1, self._size))))

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - API Qt
        if self._editable:
            self._hover = self._star_at(int(event.position().x()))
            self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802 - API Qt
        self._hover = -1
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - API Qt
        if not self._editable or event.button() != Qt.MouseButton.LeftButton:
            return
        index = self._star_at(int(event.position().x())) + 1
        # Recliquer la même étoile remet la note à zéro : c'est le seul moyen
        # de retirer une note d'un seul geste.
        self._value = 0 if index == self._value else index
        self.update()
        self.changed.emit(self._value)

    def paintEvent(self, event) -> None:  # noqa: N802 - API Qt
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            shown = self._hover + 1 if self._hover >= 0 else self._value
            for i in range(5):
                if i < self._value:
                    color = GOLD
                elif i < shown:
                    color = mix(GOLD, PANEL_HI, 0.55)
                else:
                    # Plus clair que le panneau : une étoile vide doit se
                    # voir, sinon la note semble absente.
                    color = PAD_DIM
                pixmap = icons.icon("star", color, self._size).pixmap(
                    self._size, self._size)
                painter.drawPixmap(i * self._size + 2, 2, pixmap)
            painter.end()
        except Exception as exc:  # noqa: BLE001
            log.debug("tracé des étoiles impossible : %s", exc)


# --------------------------------------------------------------------------- #
# États et progression
# --------------------------------------------------------------------------- #

#: Les huit pads allumés de l'emblème du guide (``figures/emblem.png``),
#: en ``(rangée, colonne, couleur)``.
EMBLEM_PADS = (
    (0, 1, "#6B5CE7"), (0, 3, "#FF8C1A"), (1, 0, "#3E86F5"),
    (1, 2, "#F04FA8"), (2, 1, "#FFC400"), (2, 3, "#3DD160"),
    (3, 0, "#F2453D"), (3, 2, "#28C4E0"),
)


class PadEmblem(QWidget):
    """L'emblème du guide — seize pads dans un disque cerclé d'or — qui joue.

    Les huit pads de l'emblème restent allumés en veilleuse ; d'autres
    s'allument au hasard et s'éteignent doucement, comme une grille de
    Deluge qui attend qu'on la touche. L'animation ne tourne que tant que
    l'emblème est visible : une page cachée ne coûte rien.

    ``icon_name`` pose en médaillon le pad de la page, à sa couleur : on
    reconnaît l'écran même quand il est vide.
    """

    #: Cadence de l'animation, en millisecondes.
    TICK_MS = 190

    def __init__(self, color: str = GOLD, icon_name: str = "",
                 size: int = 112, parent: QWidget | None = None,
                 animated: bool = True) -> None:
        super().__init__(parent)
        import random

        self._color = color
        self._icon = str(icon_name or "")
        self._size = max(48, int(size))
        self.setFixedSize(self._size + 22, self._size + 22)
        self._niveaux = [[0.0] * 4 for _ in range(4)]
        self._teintes = [[color] * 4 for _ in range(4)]
        self._hasard = random.Random(art.seed_of(color))
        self._animated = bool(animated)
        self._timer = QTimer(self)
        self._timer.setInterval(self.TICK_MS)
        self._timer.timeout.connect(self._tick)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents,
                          True)

    def is_running(self) -> bool:
        """Vrai si l'animation tourne."""
        return self._timer.isActive()

    def showEvent(self, event) -> None:  # noqa: N802 - API Qt
        super().showEvent(event)
        if self._animated:
            self._timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802 - API Qt
        self._timer.stop()
        super().hideEvent(event)

    def _tick(self) -> None:
        for rangee in self._niveaux:
            for colonne in range(4):
                rangee[colonne] *= 0.78
        rangee = self._hasard.randrange(4)
        colonne = self._hasard.randrange(4)
        self._niveaux[rangee][colonne] = 1.0
        # La couleur de la page revient une fois sur deux : l'emblème
        # « joue » dans la teinte de l'écran qu'il habite.
        if self._hasard.random() < 0.5:
            self._teintes[rangee][colonne] = self._color
        else:
            self._teintes[rangee][colonne] = PAD_CYCLE[
                self._hasard.randrange(len(PAD_CYCLE))]
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - API Qt
        try:
            from ..theme import GOLD as OR, PANEL_LO

            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            cote = float(self._size)
            disque = QRectF(4, 4, cote, cote)
            centre = disque.center()

            # Le halo tient dans le widget : un rayon plus grand que sa
            # demi-largeur était coupé net, et l'on voyait un carré.
            demi = min(self.width(), self.height()) / 2.0
            lueur = QRectF(0, 0, demi, demi)
            lueur.moveCenter(centre)
            art.paint_glow(painter, lueur, self._color, 0.24, 0.48)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#1C1F26"))
            painter.drawEllipse(centre, cote / 2 - 4, cote / 2 - 4)
            anneau = QPen(QColor(OR))
            anneau.setWidthF(max(2.0, cote * 0.035))
            painter.setPen(anneau)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(centre, cote / 2 - 2, cote / 2 - 2)

            cellule = cote * 0.135
            ecart = cote * 0.042
            origine = centre.x() - (4 * cellule + 3 * ecart) / 2
            haut = centre.y() - (4 * cellule + 3 * ecart) / 2
            veille = {(r, c): teinte for r, c, teinte in EMBLEM_PADS}
            for r in range(4):
                for c in range(4):
                    rect = QRectF(origine + c * (cellule + ecart),
                                  haut + r * (cellule + ecart),
                                  cellule, cellule)
                    art.paint_off_pad(painter, rect, diode=False,
                                      radius=cellule * 0.24)
                    if (r, c) in veille:
                        painter.save()
                        painter.setOpacity(0.72)
                        art.paint_pad(painter, rect, veille[(r, c)],
                                      glow=0.0, radius=cellule * 0.24)
                        painter.restore()
                    niveau = self._niveaux[r][c]
                    if niveau > 0.03:
                        painter.save()
                        painter.setOpacity(niveau)
                        art.paint_pad(painter, rect, self._teintes[r][c],
                                      glow=0.30, radius=cellule * 0.24)
                        painter.restore()

            if self._icon:
                badge = 38.0
                rect = QRectF(disque.right() - badge + 6,
                              disque.bottom() - badge + 6, badge, badge)
                painter.setPen(QPen(QColor(PANEL_LO), 4))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(rect.adjusted(-2, -2, 2, 2), 12, 12)
                # Halo serré : le médaillon est près du bord du widget, un
                # halo plus large y était coupé net.
                art.paint_glow(painter, rect, self._color, 0.32, 0.12)
                art.paint_pad(painter, rect, self._color, glow=0.0,
                              radius=10)
                taille = int(badge * 0.52)
                pixmap = icons.icon(self._icon, text_on(self._color),
                                    taille).pixmap(taille, taille)
                painter.drawPixmap(int(rect.center().x() - taille / 2),
                                   int(rect.center().y() - taille / 2),
                                   pixmap)
            painter.end()
        except Exception as exc:  # noqa: BLE001 - un décor ne casse rien
            log.debug("emblème non tracé : %s", exc)


_PASTILLES: dict[str, Any] = {}


def pad_dot(color: str, size: int = 11):
    """Petit pad allumé, pour une ligne de liste. Gardé en cache par couleur."""
    from PyQt6.QtGui import QPixmap

    cle = "%s/%d" % (color, size)
    deja = _PASTILLES.get(cle)
    if deja is not None:
        return deja
    image = QPixmap(size, size)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        art.paint_pad(painter, QRectF(0.5, 0.5, size - 1, size - 1), color,
                      glow=0.0, radius=size * 0.26)
    finally:
        painter.end()
    _PASTILLES[cle] = image
    return image


class GrilleAdaptative(QObject):
    """Range des widgets en grille, sur plus ou moins de colonnes selon la
    place.

    Mesuré à 980 px : les six tuiles du tableau de bord demandaient 900 px
    sur trois colonnes pour 720 disponibles, et le tableau de bord entier
    partait sous une barre de défilement horizontale — le bouton
    « Sauvegarder » coupé net. En dessous de ``seuil``, la grille passe sur
    ``etroit`` colonnes, et revient à ``large`` dès que la place revient.
    """

    def __init__(self, hote: QWidget, grille, widgets, large: int = 3,
                 etroit: int = 2, seuil: int = 900) -> None:
        super().__init__(hote)
        self._hote = hote
        self._grille = grille
        self._widgets = list(widgets)
        self._large = max(1, int(large))
        self._etroit = max(1, int(etroit))
        self._seuil = int(seuil)
        self._colonnes = 0
        hote.installEventFilter(self)
        self.ranger(self._large)

    def colonnes(self) -> int:
        """Nombre de colonnes en usage."""
        return self._colonnes

    def eventFilter(self, objet, evenement) -> bool:   # noqa: N802 - API Qt
        if evenement.type() == QEvent.Type.Resize:
            largeur = self._hote.width()
            self.ranger(self._large if largeur >= self._seuil
                        else self._etroit)
        return False

    def ranger(self, colonnes: int) -> None:
        if colonnes == self._colonnes:
            return
        try:
            for widget in self._widgets:
                self._grille.removeWidget(widget)
            for index, widget in enumerate(self._widgets):
                self._grille.addWidget(widget, index // colonnes,
                                       index % colonnes)
            for colonne in range(max(self._large, self._etroit)):
                self._grille.setColumnStretch(
                    colonne, 1 if colonne < colonnes else 0)
            self._colonnes = colonnes
        except Exception as exc:       # noqa: BLE001 - une disposition ne casse rien
            log.debug("grille non réarrangée : %s", exc)


class RangeeAdaptative(QObject):
    """Une rangée de panneaux qui s'empile quand la place manque.

    Deux panneaux côte à côte demandent chacun leur largeur minimale ; sur
    une fenêtre étroite, ils passent l'un sous l'autre au lieu de pousser la
    page sous une barre de défilement horizontale.
    """

    def __init__(self, hote: QWidget, rangee, seuil: int = 880) -> None:
        super().__init__(hote)
        self._hote = hote
        self._rangee = rangee
        self._seuil = int(seuil)
        hote.installEventFilter(self)

    def empilee(self) -> bool:
        """Vrai si les panneaux sont l'un sous l'autre."""
        from PyQt6.QtWidgets import QBoxLayout

        return self._rangee.direction() == QBoxLayout.Direction.TopToBottom

    def eventFilter(self, objet, evenement) -> bool:   # noqa: N802 - API Qt
        if evenement.type() == QEvent.Type.Resize:
            from PyQt6.QtWidgets import QBoxLayout

            sens = (QBoxLayout.Direction.LeftToRight
                    if self._hote.width() >= self._seuil
                    else QBoxLayout.Direction.TopToBottom)
            if self._rangee.direction() != sens:
                self._rangee.setDirection(sens)
        return False


class SegmentMeter(QWidget):
    """Une jauge en segments, comme une rangée de pads ou un vumètre.

    Les segments allumés prennent la couleur donnée, les autres restent au
    repos : une barre pleine se lit comme une quantité, une rangée de pads
    comme un niveau — et c'est le vocabulaire de la machine.
    """

    def __init__(self, parent: QWidget | None = None, segments: int = 24,
                 color: str = GOLD) -> None:
        super().__init__(parent)
        self._segments = max(4, int(segments))
        self._color = color
        self._value = 0.0
        self._maximum = 1.0
        self.setFixedHeight(12)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:  # noqa: N802 - API Qt
        # Sans taille conseillée valide, la disposition donnait zéro pixel
        # au libellé voisin et la jauge se dessinait par-dessus.
        return QSize(240, 12)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - API Qt
        return QSize(self._segments * 4, 12)

    def set_color(self, color: str) -> None:
        self._color = color or GOLD
        self.update()

    def set_value(self, value: float, maximum: float) -> None:
        """Valeur et maximum de la jauge."""
        self._value = max(0.0, float(value or 0))
        self._maximum = max(1e-9, float(maximum or 1))
        self.update()

    def lit(self) -> int:
        """Nombre de segments allumés (au moins un pour une valeur non nulle)."""
        if self._value <= 0:
            return 0
        part = min(1.0, self._value / self._maximum)
        return max(1, int(round(part * self._segments)))

    def paintEvent(self, event) -> None:  # noqa: N802 - API Qt
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            ecart = 3.0
            largeur = (self.width() - ecart * (self._segments - 1)) / float(
                self._segments)
            if largeur <= 1:
                return
            hauteur = float(self.height())
            allumes = self.lit()
            painter.setPen(Qt.PenStyle.NoPen)
            for index in range(self._segments):
                rect = QRectF(index * (largeur + ecart), 0, largeur, hauteur)
                if index < allumes:
                    art.paint_pad(painter, rect, self._color, glow=0.0,
                                  radius=2.5)
                else:
                    painter.setBrush(QColor(PANEL_HI))
                    painter.drawRoundedRect(rect, 2.5, 2.5)
            painter.end()
        except Exception as exc:  # noqa: BLE001 - un décor ne casse rien
            log.debug("jauge non tracée : %s", exc)


class ScoreRing(QLabel):
    """La note de santé dans une couronne, comme la bague d'un encodeur.

    Reste un ``QLabel`` : la page y écrit la note avec ``setText`` comme
    avant, et l'anneau suit — un arc de 270 degrés, plein en proportion de
    la note sur 100, à la couleur que :meth:`set_color` lui donne. Sans
    note (« — »), seule la piste éteinte est tracée.
    """

    def __init__(self, parent: QWidget | None = None, size: int = 96) -> None:
        super().__init__("—", parent)
        self._color = GREY
        self.setFixedSize(int(size), int(size))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setProperty("role", "value")

    def color(self) -> str:
        return self._color

    def set_color(self, color: str) -> None:
        """Couleur de l'arc et du chiffre."""
        self._color = color or GREY
        self.setStyleSheet("color: %s;" % readable(self._color))
        self.update()

    def score(self) -> int | None:
        """Note affichée, ou ``None`` s'il n'y en a pas."""
        try:
            return max(0, min(100, int(str(self.text()).strip())))
        except ValueError:
            return None

    def paintEvent(self, event) -> None:  # noqa: N802 - API Qt
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            epaisseur = max(5.0, self.width() * 0.075)
            # Le halo est deux fois plus large que l'arc : la marge doit
            # le contenir, sinon il est coupé net par le bord du widget.
            marge = epaisseur * 1.25
            cadre = QRectF(self.rect()).adjusted(marge, marge, -marge, -marge)
            piste = QPen(QColor(PANEL_HI))
            piste.setWidthF(epaisseur)
            piste.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(piste)
            painter.drawArc(cadre, 225 * 16, -270 * 16)
            note = self.score()
            if note:
                angle = int(-270 * 16 * note / 100.0)
                halo = QColor(self._color)
                halo.setAlphaF(0.22)
                trait = QPen(halo)
                trait.setWidthF(epaisseur * 2.2)
                trait.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(trait)
                painter.drawArc(cadre, 225 * 16, angle)
                trait = QPen(QColor(self._color))
                trait.setWidthF(epaisseur)
                trait.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(trait)
                painter.drawArc(cadre, 225 * 16, angle)
            painter.end()
        except Exception as exc:  # noqa: BLE001 - un décor ne casse rien
            log.debug("anneau de note non tracé : %s", exc)
        super().paintEvent(event)


class _Halo(QObject):
    """Tient le halo d'un bouton principal, et l'éteint avec le bouton.

    Un bouton désactivé qui rayonnerait promettrait un clic qu'il refuse.
    """

    def __init__(self, button, effect) -> None:
        super().__init__(button)
        self._button = button
        self._effect = effect
        button.installEventFilter(self)
        self.sync()

    def sync(self) -> None:
        try:
            self._effect.setEnabled(self._button.isEnabled())
        except RuntimeError:            # bouton déjà détruit
            pass

    def eventFilter(self, objet, evenement) -> bool:   # noqa: N802 - API Qt
        if evenement.type() == QEvent.Type.EnabledChange:
            self.sync()
        return False


def glow(widget, color: str, blur: float = 26.0,
         alpha: float = 0.55) -> QGraphicsDropShadowEffect | None:
    """Fait rayonner un widget de la couleur donnée : un pad allumé.

    Pour un bouton, le halo suit son état : il s'éteint quand le bouton est
    désactivé. Rappeler la fonction change simplement la couleur.
    """
    try:
        effet = widget.graphicsEffect()
        if not isinstance(effet, QGraphicsDropShadowEffect):
            effet = QGraphicsDropShadowEffect(widget)
            effet.setOffset(0, 0)
            widget.setGraphicsEffect(effet)
            if isinstance(widget, QPushButton):
                widget._halo = _Halo(widget, effet)
        teinte = QColor(color)
        teinte.setAlphaF(max(0.0, min(1.0, float(alpha))))
        effet.setColor(teinte)
        effet.setBlurRadius(float(blur))
        return effet
    except Exception as exc:            # noqa: BLE001 - un décor ne casse rien
        log.debug("halo impossible : %s", exc)
        return None


class EmptyState(QWidget):
    """Message affiché quand il n'y a rien à montrer.

    La SPEC §6.1 exige que l'application démarre sans carte valide : toutes
    les pages doivent pouvoir afficher un état vide explicite, qui dit quoi
    faire plutôt que de laisser un panneau blanc.
    """

    actionClicked = pyqtSignal()
    #: Second geste, facultatif : souvent le plus rapide des deux.
    action2Clicked = pyqtSignal()

    def __init__(self, message: str = "Rien à afficher.",
                 icon_name: str = "info", action: str = "",
                 parent: QWidget | None = None, detail: str = "",
                 color: str = GOLD, action2: str = "") -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAD * 2, PAD * 3, PAD * 2, PAD * 3)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # L'emblème était gris sur gris, à peine visible : un vide ressemblait
        # à une panne. C'est désormais celui du guide, une grille de pads qui
        # joue doucement, avec le pad de la page en médaillon — on voit tout
        # de suite que l'écran est en ordre, simplement qu'il attend.
        self._emblem = PadEmblem(color, icon_name, 112, self)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self._emblem)
        row.addStretch(1)
        layout.addLayout(row)

        # Les deux textes vivent dans un bloc de largeur limitée, lui-même
        # centré : une phrase étalée sur quatorze cents pixels ne se lit
        # pas, l'œil perd la ligne. Un conteneur, et non une largeur
        # maximale posée sur les étiquettes : un ``QLabel`` à retour à la
        # ligne placé avec un drapeau d'alignement perd la négociation de sa
        # hauteur, et son texte se retrouve coupé en deux.
        bloc = QWidget(self)
        bloc.setMinimumWidth(430)      # le titre tient sur une ligne
        bloc.setMaximumWidth(620)      # et la phrase garde une mesure lisible
        colonne = QVBoxLayout(bloc)
        colonne.setContentsMargins(0, 0, 0, 0)
        colonne.setSpacing(8)

        self._message = QLabel(message, bloc)
        self._message.setProperty("role", "title")
        self._message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._message.setWordWrap(True)
        colonne.addWidget(self._message)

        self._detail = QLabel(detail, bloc)
        self._detail.setProperty("role", "subtitle")
        self._detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._detail.setWordWrap(True)
        self._detail.setVisible(bool(detail))
        colonne.addWidget(self._detail)

        ligne = QHBoxLayout()
        ligne.addStretch(1)
        ligne.addWidget(bloc)
        ligne.addStretch(1)
        layout.addLayout(ligne)

        self._button: QPushButton | None = None
        self._button2: QPushButton | None = None
        if action or action2:
            row = QHBoxLayout()
            row.setSpacing(8)
            row.addStretch(1)
            if action:
                self._button = QPushButton(action, self)
                self._button.setObjectName("Primary")
                self._button.setCursor(Qt.CursorShape.PointingHandCursor)
                self._button.clicked.connect(self.actionClicked.emit)
                glow(self._button, color, 24, 0.50)
                row.addWidget(self._button)
            if action2:
                self._button2 = QPushButton(action2, self)
                self._button2.setCursor(Qt.CursorShape.PointingHandCursor)
                self._button2.clicked.connect(self.action2Clicked.emit)
                row.addWidget(self._button2)
            row.addStretch(1)
            layout.addLayout(row)

    def set_message(self, message: str, detail: str = "") -> None:
        """Change le message, et le détail s'il est fourni."""
        self._message.setText(message)
        self._detail.setText(detail)
        self._detail.setVisible(bool(detail))


class BusyBar(QProgressBar):
    """Barre de progression, qui bascule en mode indéterminé si besoin."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTextVisible(False)
        self.setFixedHeight(6)
        self.setRange(0, 100)

    def set_busy(self, busy: bool = True) -> None:
        """Mode indéterminé : l'avancement est inconnu."""
        if busy:
            self.setRange(0, 0)
        else:
            self.setRange(0, 100)

    def set_progress(self, current: int, total: int) -> None:
        """Avancement chiffré. Un total nul passe en mode indéterminé."""
        if total <= 0:
            self.set_busy(True)
            return
        self.setRange(0, int(total))
        self.setValue(max(0, min(int(total), int(current))))


# --------------------------------------------------------------------------- #
# Tableaux
# --------------------------------------------------------------------------- #

class KeyValueTable(QTableWidget):
    """Tableau clé/valeur en lecture seule, pour les panneaux de détail.

    Les volumes y sont faibles — quelques dizaines de lignes — donc
    ``QTableWidget`` convient ; pour les grandes listes, utiliser
    :class:`RowTableModel`.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(0, 2, parent)
        self.horizontalHeader().setVisible(False)
        self.verticalHeader().setVisible(False)
        self.setShowGrid(False)
        self.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)

    def set_rows(self, rows: Sequence[tuple[str, Any]]) -> None:
        """Remplace le contenu par une suite de couples ``(clé, valeur)``."""
        self.setRowCount(0)
        for key, value in rows or ():
            row = self.rowCount()
            self.insertRow(row)

            key_item = QTableWidgetItem(str(key))
            key_item.setForeground(QColor(TEXT_SOFT))
            self.setItem(row, 0, key_item)

            text = "—" if value is None or value == "" else str(value)
            value_item = QTableWidgetItem(text)
            value_item.setForeground(QColor(PAD_WHITE))
            value_item.setToolTip(text)
            self.setItem(row, 1, value_item)
        self.resizeRowsToContents()


#: Description d'une colonne :
#: ``(libellé, extracteur, largeur, alignement)``,
#: ``(libellé, extracteur, largeur, alignement, formateur)`` ou
#: ``(libellé, extracteur, largeur, alignement, formateur, pastille)`` — la
#: pastille est une fonction de la valeur brute qui rend une couleur (ou une
#: chaîne vide), tracée en petit pad devant le texte ; le formateur peut
#: alors valoir ``None``.
#:
#: **L'extracteur rend la valeur BRUTE**, et le formateur optionnel la met en
#: forme pour l'affichage. Cette séparation n'est pas un raffinement : un
#: ``QSortFilterProxyModel`` trie sur ce que le modèle lui donne, donc si
#: l'extracteur formatait lui-même, une colonne de tailles se classerait
#: « 99,9 Kio » avant « 988,0 Kio » et une colonne de durées « 9,73 s » avant
#: « 99,42 s ». Le modèle rend la valeur brute pour ``EditRole`` — le rôle de
#: tri réglé par :func:`configure_table` — et le texte mis en forme pour
#: ``DisplayRole``.
Column = tuple[str, Callable[[Any], Any], int, Qt.AlignmentFlag]


class RowTableModel(QAbstractTableModel):
    """Modèle de tableau pour les grandes listes.

    À utiliser avec un ``QTableView`` et un ``QSortFilterProxyModel``, comme
    l'exige la SPEC §6.5 : la bibliothèque de l'utilisateur compte 1 741
    échantillons, et un ``QTableWidget`` créerait un objet graphique par
    cellule.

    Les colonnes sont décrites par des quadruplets
    ``(libellé, extracteur, largeur conseillée, alignement)``. L'extracteur
    reçoit la ligne brute — typiquement un ``sqlite3.Row`` — et rend ce qu'il
    faut afficher.
    """

    def __init__(self, columns: Sequence[Column],
                 rows: Sequence[Any] | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._columns = list(columns)
        self._rows: list[Any] = list(rows or [])

    # -- contenu ----------------------------------------------------------- #

    def set_rows(self, rows: Sequence[Any]) -> None:
        """Remplace toutes les lignes."""
        self.beginResetModel()
        self._rows = list(rows or [])
        self.endResetModel()

    def set_columns(self, columns: Sequence[Column]) -> None:
        """Remplace les colonnes affichées.

        Sert aux vues qui ajoutent une colonne selon le mode — par exemple
        la proximité en recherche par ressemblance. Les lignes sont
        conservées : seule la façon de les lire change.
        """
        self.beginResetModel()
        self._columns = list(columns)
        self.endResetModel()

    def rows(self) -> list[Any]:
        return self._rows

    def row_at(self, index: int) -> Any | None:
        """Ligne brute à cette position, ou ``None`` si hors bornes."""
        if 0 <= int(index) < len(self._rows):
            return self._rows[int(index)]
        return None

    def columns(self) -> list[Column]:
        return list(self._columns)

    # -- API Qt ------------------------------------------------------------ #

    def rowCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        if parent is not None and parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        if parent is not None and parent.isValid():
            return 0
        return len(self._columns)

    def data(self, index: QModelIndex,
             role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        row = self.row_at(index.row())
        if row is None or not 0 <= index.column() < len(self._columns):
            return None
        column = self._columns[index.column()]
        label, extract, _width, alignment = column[0], column[1], column[2], column[3]
        formatter = column[4] if len(column) > 4 else None

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole,
                    Qt.ItemDataRole.EditRole):
            try:
                value = extract(row)
            except Exception as exc:  # noqa: BLE001 - une colonne fautive
                log.debug("colonne « %s » illisible : %s", label, exc)
                return None
            # EditRole est le rôle de tri : il rend la valeur brute, pour que
            # les nombres se trient comme des nombres.
            if role == Qt.ItemDataRole.EditRole:
                return value
            if formatter is not None:
                try:
                    return formatter(value)
                except Exception as exc:  # noqa: BLE001
                    log.debug("mise en forme de « %s » impossible : %s",
                              label, exc)
                    return None
            return "—" if value is None else str(value)

        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(alignment | Qt.AlignmentFlag.AlignVCenter)

        # Sixième élément facultatif : la couleur d'une pastille posée
        # devant le texte — la couleur d'une catégorie, comme celle d'un
        # clip sur la machine.
        if role == Qt.ItemDataRole.DecorationRole and len(column) > 5:
            pastille = column[5]
            if pastille is None:
                return None
            try:
                couleur = pastille(extract(row))
            except Exception as exc:  # noqa: BLE001 - une pastille ne casse rien
                log.debug("pastille de « %s » impossible : %s", label, exc)
                return None
            return pad_dot(couleur) if couleur else None
        return None

    def headerData(self, section: int, orientation: Qt.Orientation,  # noqa: N802
                   role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if orientation != Qt.Orientation.Horizontal:
            return None
        if not 0 <= section < len(self._columns):
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return self._columns[section][0]
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(self._columns[section][3]
                       | Qt.AlignmentFlag.AlignVCenter)
        return None

    def apply_widths(self, view) -> None:
        """Applique les largeurs conseillées à un ``QTableView``.

        Une largeur de 0 laisse la colonne s'étirer.
        """
        header = view.horizontalHeader()
        for index, column in enumerate(self._columns):
            width = int(column[2])
            if width > 0:
                view.setColumnWidth(index, int(width))
                header.setSectionResizeMode(
                    index, QHeaderView.ResizeMode.Interactive)
            else:
                header.setSectionResizeMode(
                    index, QHeaderView.ResizeMode.Stretch)


#: Place garantie à la première colonne, celle du nom. En dessous, une
#: liste ne sert plus à rien : autant cacher tout le reste.
MIN_PREMIERE_COLONNE = 150


class _ColonnesAdaptatives(QObject):
    """Cache les dernières colonnes quand la largeur manque.

    Les colonnes sont déclarées dans l'ordre d'importance : le nom d'abord,
    les détails ensuite. On garde donc toujours la première, puis on ajoute
    les suivantes tant qu'elles tiennent. Tout revient dès que la fenêtre
    s'agrandit : rien n'est perdu, seulement remis à plus tard.
    """

    def __init__(self, view, model) -> None:
        super().__init__(view)
        self._view = view
        self._model = model
        view.viewport().installEventFilter(self)
        self.ajuster()

    def eventFilter(self, objet, evenement) -> bool:   # noqa: N802 - API Qt
        if evenement.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self.ajuster()
        return False

    def ajuster(self) -> None:
        try:
            colonnes = self._model.columns()
            dispo = self._view.viewport().width()
            if dispo <= 0 or not colonnes:
                return
            # Si la première colonne s'étire, elle sait rétrécir : on ne lui
            # réserve que son minimum vital. Sinon elle gardera sa largeur
            # conseillée, et il faut la compter en entier — sans quoi les
            # dernières colonnes débordent quand même.
            etiree = (self._view.horizontalHeader().sectionResizeMode(0)
                      == QHeaderView.ResizeMode.Stretch)
            cumul = (MIN_PREMIERE_COLONNE if etiree
                     else max(40, int(colonnes[0][2]) or 120))
            for index, colonne in enumerate(colonnes):
                if index:
                    cumul += max(40, int(colonne[2]) or 120)
                # La première reste toujours : une liste sans nom ne sert
                # à rien.
                cache = index > 0 and cumul > dispo
                if self._view.isColumnHidden(index) != cache:
                    self._view.setColumnHidden(index, cache)
        except Exception as exc:       # noqa: BLE001 - un ajustement ne casse rien
            log.debug("ajustement des colonnes impossible : %s", exc)


def configure_table(view, model: RowTableModel | None = None,
                    sortable: bool = True) -> None:
    """Règle un ``QTableView`` comme les pages l'attendent.

    Lignes alternées, sélection par ligne entière, pas d'édition, hauteur de
    ligne compacte.

    **Règle le tri sur ``EditRole``**, ce qui est indispensable : par défaut
    un ``QSortFilterProxyModel`` trie sur le texte affiché, et une colonne de
    durées se classait alors « 9,73 s » avant « 99,42 s ».
    :meth:`RowTableModel.data` rend la valeur brute pour ``EditRole``, donc
    les nombres se trient comme des nombres et les tailles comme des tailles.
    """
    view.setAlternatingRowColors(True)
    view.setSelectionBehavior(view.SelectionBehavior.SelectRows)
    view.setSelectionMode(view.SelectionMode.ExtendedSelection)
    view.setEditTriggers(view.EditTrigger.NoEditTriggers)
    view.setShowGrid(False)
    view.verticalHeader().setVisible(False)
    # 28 px : la ligne respire, et la sélection se lit comme une bande
    # plutôt que comme un surlignage serré.
    view.verticalHeader().setDefaultSectionSize(28)
    view.horizontalHeader().setHighlightSections(False)
    view.setWordWrap(False)
    if sortable:
        view.setSortingEnabled(True)

    attached = view.model()
    setter = getattr(attached, "setSortRole", None)
    if callable(setter):
        try:
            setter(Qt.ItemDataRole.EditRole)
        except (TypeError, RuntimeError) as exc:
            log.debug("rôle de tri non applicable : %s", exc)

    if model is not None:
        model.apply_widths(view)
        # Le nom prend la place libre, partout : c'est ce qu'on lit en
        # premier, et deux listes sur quatre ne le faisaient pas.
        try:
            view.horizontalHeader().setSectionResizeMode(
                0, QHeaderView.ResizeMode.Stretch)
        except Exception as exc:       # noqa: BLE001
            log.debug("colonne de nom non étirée : %s", exc)
        # Les largeurs conseillées valent pour une fenêtre large ; sur un
        # portable, mieux vaut montrer quatre colonnes lisibles que huit
        # sous une barre de défilement.
        view._colonnes_adaptatives = _ColonnesAdaptatives(view, model)


def sorted_proxy(model: RowTableModel,
                 parent: QWidget | None = None) -> QSortFilterProxyModel:
    """Proxy de tri et de filtrage réglé pour :class:`RowTableModel`.

    Trie sur la valeur brute, filtre sans tenir compte de la casse, et
    cherche dans **toutes** les colonnes.
    """
    proxy = QSortFilterProxyModel(parent)
    proxy.setSourceModel(model)
    proxy.setSortRole(Qt.ItemDataRole.EditRole)
    proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    proxy.setFilterKeyColumn(-1)
    proxy.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    return proxy


def mono_font(size: int = 9) -> QFont:
    """Police à largeur fixe du thème, pour les chemins et les valeurs hex."""
    from ..theme import FONT_MONO, FONT_MONO_FALLBACK

    font = QFont(FONT_MONO)
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPointSize(int(size))
    if not font.exactMatch():
        font.setFamily(FONT_MONO_FALLBACK)
    return font


class PlanDialog(QDialog):
    """Montre le plan d'opérations avant de l'appliquer.

    Aucune réorganisation ne part sans que l'utilisateur ait lu cette liste :
    c'est la dernière barrière avant que des fichiers bougent.
    """

    def __init__(self, plan, parent=None, title: str = "Plan d'opérations") -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(820, 540)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAD, PAD, PAD, PAD)
        layout.setSpacing(8)

        summary = QLabel(plan.summary())
        summary.setProperty("role", "title")
        summary.setWordWrap(True)
        layout.addWidget(summary)

        counts = plan.counts()
        if counts.get("delete"):
            self._warn(layout,
                       f"⚠ {counts['delete']} suppression(s) : cette "
                       f"opération est irréversible.")
        # Un plan de correction audio qui change la longueur des fichiers
        # déplace aussi les bornes des presets : il faut le dire.
        if getattr(plan, "changes_length", False):
            self._warn(layout,
                       "⚠ Des longueurs de fichiers vont changer. Les bornes "
                       "des presets et des kits qui les citent sont remises à "
                       "l'échelle automatiquement ; les fichiers utilisés par "
                       "un morceau sont écartés.")
        skipped = getattr(plan, "skipped", None)
        if skipped:
            note = QLabel("%d fichier(s) écarté(s) — voir le détail."
                          % len(skipped))
            note.setStyleSheet(f"color: {GOLD};")
            note.setWordWrap(True)
            layout.addWidget(note)

        detail = QPlainTextEdit()
        detail.setReadOnly(True)
        detail.setPlainText(plan.to_text())
        detail.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(detail, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText("Appliquer")
        ok.setObjectName("Primary")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(
            "Annuler")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _warn(layout, texte: str) -> None:
        """Ajoute un avertissement en rouge au-dessus du détail."""
        label = QLabel(texte)
        label.setStyleSheet(f"color: {PAD_RED}; font-weight: 600;")
        label.setWordWrap(True)
        layout.addWidget(label)


def hint_in_list(liste, texte: str) -> bool:
    """Pose un texte d'attente dans une liste vide.

    Une ``QListWidget`` vide est un rectangle gris : rien ne dit s'il
    manque une donnée, s'il faut cliquer quelque part, ou si le logiciel
    est en panne. L'élément posé ici n'est ni sélectionnable ni actif ;
    les appelants bornent de toute façon leurs index sur leurs propres
    données, pas sur le nombre de lignes affichées.

    :return: vrai si la liste était vide et que le texte a été posé.
    """
    from PyQt6.QtWidgets import QListWidgetItem

    try:
        if liste.count():
            return False
        item = QListWidgetItem(str(texte or ""))
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setForeground(QColor(TEXT_SOFT))
        liste.addItem(item)
        return True
    except Exception as exc:        # noqa: BLE001 - simple décor
        log.debug("texte d'attente impossible : %s", exc)
        return False


def clear_layout(layout) -> None:
    """Vide une disposition de ses widgets, **immédiatement**.

    ``deleteLater()`` seul ne suffit pas : il diffère la destruction à la
    prochaine itération de la boucle Qt, et le widget reste visible
    entre-temps. Si l'appelant repeuple la disposition dans la foulée,
    l'ancien contenu se dessine **sous** le nouveau — c'est le
    chevauchement qu'on voyait sur le tableau de bord à chaque
    rafraîchissement. ``setParent(None)`` le retire de l'affichage tout de
    suite ; ``deleteLater`` libère ensuite la mémoire sans risque.
    """
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
            continue
        enfant = item.layout()
        if enfant is not None:
            clear_layout(enfant)
            enfant.deleteLater()


#: Mise en forme des grandeurs : **une seule implémentation**, dans
#: ``core/units.py``, pour que le noyau et l'interface écrivent la même
#: chose. Il y en a eu trois, et les deux copies du noyau utilisaient le
#: point décimal à l'anglaise : « 9.9 Mio » au milieu d'une application en
#: français. Les noms restent exportés ici, puisque tout l'affichage les
#: appelle déjà.
human_size = _units.human_size
human_duration = _units.human_duration
human_datetime = _units.human_datetime
