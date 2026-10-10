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
    QModelIndex,
    QRectF,
    QSize,
    QSortFilterProxyModel,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import icons
from ..theme import (
    GOLD,
    GREY,
    PAD,
    PAD_WHITE,
    PANEL_HI,
    RADIUS,
    mix,
    with_alpha,
)

log = logging.getLogger(__name__)

#: Délai avant émission d'une recherche, en millisecondes (cf. SPEC §5.4).
SEARCH_DEBOUNCE_MS = 250


# --------------------------------------------------------------------------- #
# Titres et panneaux
# --------------------------------------------------------------------------- #

class SectionTitle(QWidget):
    """Titre de section suivi d'un trait or, comme dans le guide du Deluge."""

    def __init__(self, title: str = "", parent: QWidget | None = None,
                 color: str = GOLD) -> None:
        super().__init__(parent)
        self._color = color
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 6)
        layout.setSpacing(4)

        self._label = QLabel(title, self)
        self._label.setProperty("role", "section")
        layout.addWidget(self._label)

        self._rule = QWidget(self)
        self._rule.setFixedHeight(2)
        self._rule.setSizePolicy(QSizePolicy.Policy.Expanding,
                                 QSizePolicy.Policy.Fixed)
        layout.addWidget(self._rule)

    def setText(self, text: str) -> None:
        """Change le libellé."""
        self._label.setText(text)

    def text(self) -> str:
        return self._label.text()

    def set_color(self, color: str) -> None:
        """Change la couleur du trait."""
        self._color = color
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - API Qt
        super().paintEvent(event)
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            rect = self._rule.geometry()
            # Trait franc à gauche, estompé vers la droite. On construit les
            # couleurs avec setAlphaF : `theme.with_alpha` rend une chaîne
            # « rgba(…) » destinée au QSS, que QColor ne sait pas lire.
            start = QColor(self._color)
            middle = QColor(self._color)
            middle.setAlphaF(0.35)
            end = QColor(self._color)
            end.setAlphaF(0.0)

            gradient = QLinearGradient(float(rect.x()), 0.0,
                                       float(rect.x() + max(1, rect.width())),
                                       0.0)
            gradient.setColorAt(0.0, start)
            gradient.setColorAt(0.45, middle)
            gradient.setColorAt(1.0, end)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(gradient)
            painter.drawRect(QRectF(rect.x(), rect.y(),
                                    max(1, rect.width()), rect.height()))
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


class StatTile(QFrame):
    """Grande valeur, libellé, couleur de pad et icône : la tuile du tableau
    de bord."""

    clicked = pyqtSignal()

    def __init__(self, label: str, value: str = "—", color: str = GOLD,
                 icon_name: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Tile")
        self.setProperty("tile", "true")
        self._color = color
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(PAD, 10, PAD, 10)
        layout.setSpacing(10)

        if icon_name:
            badge = QLabel(self)
            badge.setPixmap(icons.icon(icon_name, color, 26).pixmap(26, 26))
            badge.setFixedSize(30, 30)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(badge)

        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)

        self._value = QLabel(str(value), self)
        self._value.setProperty("role", "value")
        column.addWidget(self._value)

        self._label = QLabel(label, self)
        self._label.setProperty("role", "subtitle")
        column.addWidget(self._label)

        layout.addLayout(column, 1)

    def set_value(self, v: Any) -> None:
        """Met à jour la valeur affichée."""
        self._value.setText("—" if v is None else str(v))

    def set_label(self, text: str) -> None:
        self._label.setText(text)

    def set_color(self, color: str) -> None:
        """Change la couleur du liseré gauche."""
        self._color = color
        self.setStyleSheet(f"QFrame#Tile {{ border-left: 3px solid {color}; }}")

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
                    color = PANEL_HI
                pixmap = icons.icon("star", color, self._size).pixmap(
                    self._size, self._size)
                painter.drawPixmap(i * self._size + 2, 2, pixmap)
            painter.end()
        except Exception as exc:  # noqa: BLE001
            log.debug("tracé des étoiles impossible : %s", exc)


# --------------------------------------------------------------------------- #
# États et progression
# --------------------------------------------------------------------------- #

class EmptyState(QWidget):
    """Message affiché quand il n'y a rien à montrer.

    La SPEC §6.1 exige que l'application démarre sans carte valide : toutes
    les pages doivent pouvoir afficher un état vide explicite, qui dit quoi
    faire plutôt que de laisser un panneau blanc.
    """

    actionClicked = pyqtSignal()

    def __init__(self, message: str = "Rien à afficher.",
                 icon_name: str = "info", action: str = "",
                 parent: QWidget | None = None, detail: str = "") -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAD * 2, PAD * 3, PAD * 2, PAD * 3)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        emblem = QLabel(self)
        emblem.setPixmap(icons.icon(icon_name, mix(GREY, PANEL_HI, 0.3), 56)
                         .pixmap(56, 56))
        emblem.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(emblem)

        self._message = QLabel(message, self)
        self._message.setProperty("role", "title")
        self._message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._message.setWordWrap(True)
        layout.addWidget(self._message)

        self._detail = QLabel(detail, self)
        self._detail.setProperty("role", "subtitle")
        self._detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._detail.setWordWrap(True)
        self._detail.setVisible(bool(detail))
        layout.addWidget(self._detail)

        self._button: QPushButton | None = None
        if action:
            self._button = QPushButton(action, self)
            self._button.setObjectName("Primary")
            self._button.setCursor(Qt.CursorShape.PointingHandCursor)
            self._button.clicked.connect(self.actionClicked.emit)
            row = QHBoxLayout()
            row.addStretch(1)
            row.addWidget(self._button)
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
            key_item.setForeground(QColor(GREY))
            self.setItem(row, 0, key_item)

            text = "—" if value is None or value == "" else str(value)
            value_item = QTableWidgetItem(text)
            value_item.setForeground(QColor(PAD_WHITE))
            value_item.setToolTip(text)
            self.setItem(row, 1, value_item)
        self.resizeRowsToContents()


#: Description d'une colonne :
#: ``(libellé, extracteur, largeur, alignement)`` ou
#: ``(libellé, extracteur, largeur, alignement, formateur)``.
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
    view.verticalHeader().setDefaultSectionSize(24)
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


def human_size(size: int | float | None) -> str:
    """Taille lisible : ``1,4 Mio``. ``None`` rend un tiret, pas « 0 o »."""
    if size is None:
        return "—"
    try:
        value = float(size)
    except (TypeError, ValueError):
        return "—"
    for unit in ("o", "Kio", "Mio", "Gio"):
        if value < 1024 or unit == "Gio":
            if unit == "o":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}".replace(".", ",")
        value /= 1024.0
    return "—"


def human_duration(seconds: int | float | None) -> str:
    """Durée lisible : ``1,25 s`` ou ``3 min 07 s``."""
    try:
        value = float(seconds or 0)
    except (TypeError, ValueError):
        return "—"
    if value <= 0:
        return "—"
    if value < 60:
        return f"{value:.2f} s".replace(".", ",")
    minutes, rest = divmod(int(round(value)), 60)
    return f"{minutes} min {rest:02d} s"
