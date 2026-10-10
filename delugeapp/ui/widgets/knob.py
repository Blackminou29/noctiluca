# -*- coding: utf-8 -*-
"""Encodeur rotatif doré, à l'image des potentiomètres du Deluge.

Se règle au glisser vertical ou à la molette, comme un encodeur de la
machine. Affiche la valeur **dans l'échelle de l'écran du Deluge** — 0 à 50,
ou −25 à +25 en bipolaire — et non en pourcentage : c'est le nombre que
l'utilisateur lit sur son appareil.
"""

from __future__ import annotations

import logging
from math import cos, radians, sin

from PyQt6.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from ..theme import GOLD, GOLD_HI, GREY, PAD_WHITE, PANEL_HI, PANEL_LO

log = logging.getLogger(__name__)

#: Course du bouton : 270 degrés, de 225° à −45° comme un potentiomètre.
START_ANGLE = 225.0
SWEEP = 270.0

#: Nombre de pixels de glisser pour parcourir toute la course.
DRAG_RANGE_PX = 160.0


class Knob(QWidget):
    """Un encodeur rotatif."""

    valueChanged = pyqtSignal(int)

    def __init__(self, label: str = "", value: int = 25, minimum: int = 0,
                 maximum: int = 50, bipolar: bool = False, color: str = GOLD,
                 parent: QWidget | None = None, diameter: int = 46) -> None:
        super().__init__(parent)
        self._label = str(label or "")
        self._min = int(minimum)
        self._max = max(int(maximum), self._min + 1)
        self._bipolar = bool(bipolar)
        self._color = color
        self._diameter = max(24, int(diameter))
        self._value = self._clamp(value)
        self._drag_y: float | None = None
        self._drag_value = self._value

        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip(self._label)

    # -- valeur ------------------------------------------------------------ #

    def _clamp(self, value) -> int:
        try:
            return max(self._min, min(self._max, int(round(float(value)))))
        except (TypeError, ValueError):
            return self._min

    def value(self) -> int:
        return self._value

    def set_value(self, value: int, notify: bool = False) -> None:
        """Change la valeur ; n'émet le signal que si ``notify``."""
        new = self._clamp(value)
        if new == self._value:
            return
        self._value = new
        self.update()
        if notify:
            self._emit()

    def set_range(self, minimum: int, maximum: int) -> None:
        self._min = int(minimum)
        self._max = max(int(maximum), self._min + 1)
        self._value = self._clamp(self._value)
        self.update()

    def label(self) -> str:
        return self._label

    def set_label(self, text: str) -> None:
        self._label = str(text or "")
        self.setToolTip(self._label)
        self.update()

    def display_text(self) -> str:
        """Valeur telle qu'elle s'écrit : ``32`` ou ``+12``."""
        if self._bipolar and self._value > 0:
            return f"+{self._value}"
        return str(self._value)

    def _emit(self) -> None:
        try:
            self.valueChanged.emit(self._value)
        except Exception:  # noqa: BLE001 - un abonné ne doit rien casser
            log.exception("abonné à valueChanged en échec")

    # -- géométrie --------------------------------------------------------- #

    def sizeHint(self) -> QSize:  # noqa: N802 - API Qt
        extra = 30 if self._label else 16
        return QSize(self._diameter + 12, self._diameter + extra)

    def _dial_rect(self) -> QRectF:
        size = min(self.width() - 8, self._diameter)
        left = (self.width() - size) / 2.0
        top = 4.0 if not self._label else 16.0
        return QRectF(left, top, size, size)

    def _ratio(self) -> float:
        span = max(1, self._max - self._min)
        return (self._value - self._min) / float(span)

    # -- interaction -------------------------------------------------------- #

    def mousePressEvent(self, event) -> None:  # noqa: N802 - API Qt
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_y = event.position().y()
            self._drag_value = self._value
            self.setFocus(Qt.FocusReason.MouseFocusReason)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - API Qt
        if self._drag_y is None:
            return
        # Glisser vers le haut augmente, comme sur un potentiomètre.
        delta = self._drag_y - event.position().y()
        span = self._max - self._min
        # Maj enfoncée : réglage fin, quatre fois moins sensible.
        travel = DRAG_RANGE_PX
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            travel *= 4.0
        self.set_value(self._drag_value + (delta / travel) * span, notify=True)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - API Qt
        self._drag_y = None

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - API Qt
        """Double-clic : retour à la valeur neutre."""
        neutral = 0 if self._bipolar else (self._min + self._max) // 2
        self.set_value(neutral, notify=True)

    def wheelEvent(self, event) -> None:  # noqa: N802 - API Qt
        steps = event.angleDelta().y() / 120.0
        amount = 1 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier \
            else max(1, (self._max - self._min) // 25)
        self.set_value(self._value + int(steps) * amount, notify=True)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - API Qt
        key = event.key()
        step = max(1, (self._max - self._min) // 50)
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Right):
            self.set_value(self._value + step, notify=True)
        elif key in (Qt.Key.Key_Down, Qt.Key.Key_Left):
            self.set_value(self._value - step, notify=True)
        elif key == Qt.Key.Key_Home:
            self.set_value(self._min, notify=True)
        elif key == Qt.Key.Key_End:
            self.set_value(self._max, notify=True)
        else:
            super().keyPressEvent(event)

    # -- tracé -------------------------------------------------------------- #

    def paintEvent(self, event) -> None:  # noqa: N802 - API Qt
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            dial = self._dial_rect()

            if self._label:
                painter.setPen(QPen(QColor(GREY)))
                font = painter.font()
                font.setPointSize(8)
                painter.setFont(font)
                painter.drawText(QRectF(0, 0, self.width(), 14),
                                 Qt.AlignmentFlag.AlignCenter, self._label)

            thickness = max(3.0, dial.width() * 0.10)
            track = dial.adjusted(thickness, thickness, -thickness, -thickness)

            # Piste complète, en fond.
            pen = QPen(QColor(PANEL_HI))
            pen.setWidthF(thickness)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawArc(track, int(START_ANGLE * 16),
                            int(-SWEEP * 16))

            # Portion active.
            ratio = self._ratio()
            if self._bipolar:
                # Depuis le centre, dans un sens ou dans l'autre.
                centre = 0.5
                span = ratio - centre
                begin = START_ANGLE - SWEEP * min(centre, ratio)
                length = -SWEEP * abs(span)
                if span < 0:
                    begin = START_ANGLE - SWEEP * centre
                    length = SWEEP * abs(span)
            else:
                begin = START_ANGLE
                length = -SWEEP * ratio

            pen.setColor(QColor(self._color))
            painter.setPen(pen)
            painter.drawArc(track, int(begin * 16), int(length * 16))

            # Corps du bouton.
            inner = track.adjusted(thickness, thickness, -thickness, -thickness)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(PANEL_LO))
            painter.drawEllipse(inner)

            # Index.
            angle = radians(START_ANGLE - SWEEP * ratio)
            centre_x = inner.center().x()
            centre_y = inner.center().y()
            radius = inner.width() / 2.0
            pen.setColor(QColor(GOLD_HI))
            pen.setWidthF(max(1.5, thickness * 0.5))
            painter.setPen(pen)
            painter.drawLine(
                int(centre_x + cos(angle) * radius * 0.35),
                int(centre_y - sin(angle) * radius * 0.35),
                int(centre_x + cos(angle) * radius * 0.88),
                int(centre_y - sin(angle) * radius * 0.88))

            # Valeur, au centre.
            painter.setPen(QPen(QColor(PAD_WHITE)))
            font = painter.font()
            font.setPointSize(max(7, int(inner.width() * 0.26)))
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(inner, Qt.AlignmentFlag.AlignCenter,
                             self.display_text())
            painter.end()
        except Exception as exc:  # noqa: BLE001 - un tracé ne doit rien casser
            log.debug("tracé de l'encodeur impossible : %s", exc)
