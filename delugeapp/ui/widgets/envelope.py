# -*- coding: utf-8 -*-
"""Éditeur d'enveloppe ADSR, à quatre poignées déplaçables.

Le tracé montre la forme réelle de l'enveloppe : attaque, chute vers le
niveau de maintien, maintien, puis extinction. Les quatre poignées se
déplacent à la souris, et les valeurs restent exprimées dans l'échelle de
l'écran du Deluge, de 0 à 50.

La durée affichée n'est pas linéaire : sur la machine comme ici, passer de 0
à 1 allonge l'attaque de quelques millisecondes, alors que passer de 49 à 50
l'allonge de plusieurs centaines. Le tracé respecte cette progression pour
que la courbe ressemble à ce qu'on entend.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from ..theme import GOLD, GOLD_HI, GREY, PAD_WHITE, PANEL_HI, PANEL_LO

log = logging.getLogger(__name__)

#: Rayon des poignées, en pixels.
HANDLE_R = 5.0

#: Largeur réservée au maintien, en fraction de la largeur utile : le
#: maintien n'a pas de durée propre, mais il faut lui laisser une place
#: visible pour que la courbe se lise.
SUSTAIN_WIDTH = 0.22

#: Échelle maximale d'une valeur de temps.
MAX_VALUE = 50


class EnvelopeEditor(QWidget):
    """Enveloppe ADSR interactive."""

    changed = pyqtSignal(dict)

    def __init__(self, parent: QWidget | None = None, color: str = GOLD,
                 title: str = "") -> None:
        super().__init__(parent)
        self._a = 0
        self._d = 20
        self._s = 30
        self._r = 16
        self._color = color
        self._title = str(title or "")
        self._drag = ""
        self.setMinimumHeight(110)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Preferred)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # -- valeurs ----------------------------------------------------------- #

    @staticmethod
    def _clamp(value) -> int:
        try:
            return max(0, min(MAX_VALUE, int(round(float(value)))))
        except (TypeError, ValueError):
            return 0

    def set_adsr(self, a: int, d: int, s: int, r: int,
                 notify: bool = False) -> None:
        """Règle les quatre valeurs, en unités d'affichage 0..50."""
        self._a = self._clamp(a)
        self._d = self._clamp(d)
        self._s = self._clamp(s)
        self._r = self._clamp(r)
        self.update()
        if notify:
            self._emit()

    def adsr(self) -> tuple[int, int, int, int]:
        """``(attaque, decay, sustain, release)`` en unités d'affichage."""
        return self._a, self._d, self._s, self._r

    def set_title(self, title: str) -> None:
        self._title = str(title or "")
        self.update()

    def _emit(self) -> None:
        try:
            self.changed.emit({"attack": self._a, "decay": self._d,
                               "sustain": self._s, "release": self._r})
        except Exception:  # noqa: BLE001 - un abonné ne doit rien casser
            log.exception("abonné à changed en échec")

    # -- géométrie --------------------------------------------------------- #

    def sizeHint(self) -> QSize:  # noqa: N802 - API Qt
        return QSize(260, 130)

    def _plot(self) -> QRectF:
        """Zone de tracé, marges comprises."""
        top = 18.0 if self._title else 10.0
        return QRectF(10.0, top, max(20.0, self.width() - 20.0),
                      max(20.0, self.height() - top - 16.0))

    @staticmethod
    def _time_ratio(value: int) -> float:
        """Place une durée 0..50 sur une échelle perceptive.

        Une racine carrée donne aux petites valeurs la place qu'elles méritent
        à l'œil : sans elle, toutes les attaques courtes se tasseraient contre
        le bord gauche, là où se fait justement le réglage le plus fin.
        """
        return (max(0, min(MAX_VALUE, value)) / float(MAX_VALUE)) ** 0.6

    def _points(self) -> dict[str, QPointF]:
        """Les quatre points caractéristiques de la courbe."""
        plot = self._plot()
        # Les trois phases temporelles se partagent la largeur restante.
        free = 1.0 - SUSTAIN_WIDTH
        total = max(1e-6, self._time_ratio(self._a) + self._time_ratio(self._d)
                    + self._time_ratio(self._r))
        share_a = self._time_ratio(self._a) / total * free
        share_d = self._time_ratio(self._d) / total * free

        x0 = plot.left()
        x_attack = x0 + plot.width() * share_a
        x_decay = x_attack + plot.width() * share_d
        x_sustain = x_decay + plot.width() * SUSTAIN_WIDTH
        x_end = plot.right()

        y_top = plot.top()
        y_bottom = plot.bottom()
        y_sustain = y_bottom - (self._s / float(MAX_VALUE)) * plot.height()

        return {
            "start": QPointF(x0, y_bottom),
            "attack": QPointF(x_attack, y_top),
            "decay": QPointF(x_decay, y_sustain),
            "sustain": QPointF(x_sustain, y_sustain),
            "release": QPointF(x_end, y_bottom),
        }

    def _handle_at(self, x: float, y: float) -> str:
        """Nom de la poignée saisie, ou chaîne vide."""
        points = self._points()
        for name in ("attack", "decay", "sustain", "release"):
            point = points[name]
            if (abs(point.x() - x) <= HANDLE_R * 2.2
                    and abs(point.y() - y) <= HANDLE_R * 3.0):
                return name
        return ""

    # -- interaction -------------------------------------------------------- #

    def mousePressEvent(self, event) -> None:  # noqa: N802 - API Qt
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._drag = self._handle_at(event.position().x(),
                                    event.position().y())
        self.setFocus(Qt.FocusReason.MouseFocusReason)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - API Qt
        if not self._drag:
            self.setCursor(
                Qt.CursorShape.SizeAllCursor
                if self._handle_at(event.position().x(), event.position().y())
                else Qt.CursorShape.ArrowCursor)
            return

        plot = self._plot()
        x = max(plot.left(), min(plot.right(), event.position().x()))
        y = max(plot.top(), min(plot.bottom(), event.position().y()))

        # Chaque poignée ne commande que ce qu'elle représente : l'abscisse
        # pour les durées, l'ordonnée pour le niveau de maintien.
        if self._drag == "attack":
            share = (x - plot.left()) / max(1.0, plot.width())
            self._a = self._from_share(share)
        elif self._drag == "decay":
            points = self._points()
            share = (x - points["attack"].x()) / max(1.0, plot.width())
            self._d = self._from_share(share)
            self._s = self._clamp(
                (plot.bottom() - y) / max(1.0, plot.height()) * MAX_VALUE)
        elif self._drag == "sustain":
            self._s = self._clamp(
                (plot.bottom() - y) / max(1.0, plot.height()) * MAX_VALUE)
        elif self._drag == "release":
            points = self._points()
            share = (x - points["sustain"].x()) / max(1.0, plot.width())
            self._r = self._from_share(share)
        self.update()
        self._emit()

    @staticmethod
    def _from_share(share: float) -> int:
        """Inverse de :meth:`_time_ratio`, pour un partage de largeur."""
        share = max(0.0, min(1.0, share))
        # On inverse l'exposant 0,6 et la part de largeur allouée.
        return EnvelopeEditor._clamp(
            ((share / max(1e-6, 1.0 - SUSTAIN_WIDTH)) ** (1.0 / 0.6))
            * MAX_VALUE * 1.6)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - API Qt
        self._drag = ""

    def keyPressEvent(self, event) -> None:  # noqa: N802 - API Qt
        """Flèches : règle le maintien, le plus souvent modifié."""
        if event.key() == Qt.Key.Key_Up:
            self._s = self._clamp(self._s + 1)
        elif event.key() == Qt.Key.Key_Down:
            self._s = self._clamp(self._s - 1)
        else:
            super().keyPressEvent(event)
            return
        self.update()
        self._emit()

    # -- tracé -------------------------------------------------------------- #

    def paintEvent(self, event) -> None:  # noqa: N802 - API Qt
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(PANEL_LO))
            painter.drawRoundedRect(QRectF(0, 0, self.width(), self.height()),
                                    6, 6)

            if self._title:
                painter.setPen(QPen(QColor(GREY)))
                font = painter.font()
                font.setPointSize(8)
                painter.setFont(font)
                painter.drawText(QRectF(8, 2, self.width() - 16, 14),
                                 Qt.AlignmentFlag.AlignLeft, self._title)

            plot = self._plot()
            points = self._points()

            # Lignes de niveau, discrètes.
            painter.setPen(QPen(QColor(PANEL_HI), 1, Qt.PenStyle.DotLine))
            for fraction in (0.25, 0.5, 0.75):
                y = plot.bottom() - plot.height() * fraction
                painter.drawLine(int(plot.left()), int(y),
                                 int(plot.right()), int(y))

            # Courbe remplie.
            path = QPainterPath(points["start"])
            path.lineTo(points["attack"])
            path.lineTo(points["decay"])
            path.lineTo(points["sustain"])
            path.lineTo(points["release"])

            filled = QPainterPath(path)
            filled.lineTo(plot.right(), plot.bottom())
            filled.lineTo(plot.left(), plot.bottom())
            filled.closeSubpath()

            gradient = QLinearGradient(0.0, plot.top(), 0.0, plot.bottom())
            top_colour = QColor(self._color)
            top_colour.setAlphaF(0.34)
            bottom_colour = QColor(self._color)
            bottom_colour.setAlphaF(0.03)
            gradient.setColorAt(0.0, top_colour)
            gradient.setColorAt(1.0, bottom_colour)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(gradient)
            painter.drawPath(filled)

            pen = QPen(QColor(self._color))
            pen.setWidthF(2.0)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)

            # Poignées.
            for name in ("attack", "decay", "sustain", "release"):
                point = points[name]
                painter.setPen(QPen(QColor(PANEL_LO), 1.5))
                painter.setBrush(QColor(GOLD_HI if self._drag == name
                                        else PAD_WHITE))
                painter.drawEllipse(point, HANDLE_R, HANDLE_R)

            # Valeurs, en bas.
            painter.setPen(QPen(QColor(GREY)))
            font = painter.font()
            font.setPointSize(8)
            font.setBold(False)
            painter.setFont(font)
            painter.drawText(
                QRectF(8, self.height() - 15, self.width() - 16, 14),
                Qt.AlignmentFlag.AlignLeft,
                f"A {self._a}   D {self._d}   S {self._s}   R {self._r}")
            painter.end()
        except Exception as exc:  # noqa: BLE001 - un tracé ne doit rien casser
            log.debug("tracé de l'enveloppe impossible : %s", exc)
