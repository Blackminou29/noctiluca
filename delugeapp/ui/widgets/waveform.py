# -*- coding: utf-8 -*-
"""Affichage de forme d'onde, avec sélection, zoom et marqueurs de zone.

Reçoit l'enveloppe min/max calculée par :func:`delugeapp.core.wav.peaks` —
un tableau ``(N, 2)`` — et non le signal entier : un échantillon de 52 Mio
ne doit jamais traverser l'interface.

Trois interactions :

* **glisser** pour sélectionner une portion (``selectionChanged``) ;
* **cliquer** pour placer la tête de lecture (``positionClicked``) ;
* **molette** pour zoomer autour du pointeur, ``Maj+molette`` pour défiler.

Les marqueurs de zone correspondent au ``zone start``/``end`` d'un
oscillateur du Deluge : les déplacer émet ``zoneChanged``.
"""

from __future__ import annotations

import logging

import numpy as np
from PyQt6.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from ..theme import (
    GOLD,
    GOLD_HI,
    GREY,
    PAD_CYAN,
    PAD_WHITE,
    PANEL,
    PANEL_HI,
    PANEL_LO,
)

log = logging.getLogger(__name__)

#: Zoom maximal : on ne descend pas sous cette fraction de la durée totale.
MIN_SPAN = 0.0005

#: Tolérance de saisie d'un marqueur, en pixels.
HANDLE_GRAB_PX = 6


class WaveformView(QWidget):
    """Forme d'onde d'un échantillon."""

    selectionChanged = pyqtSignal(float, float)
    positionClicked = pyqtSignal(float)
    zoneChanged = pyqtSignal(float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._peaks: np.ndarray | None = None
        self._duration = 0.0
        self._sample_rate = 44100
        self._position: float | None = None
        self._zone: tuple[float, float] | None = None
        self._selection: tuple[float, float] | None = None

        # Fenêtre visible, en fraction de la durée totale.
        self._view = (0.0, 1.0)
        self._drag: str = ""          # '', 'select', 'zone_a', 'zone_b'
        self._drag_from = 0.0

        self.setMinimumHeight(70)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # -- contenu ----------------------------------------------------------- #

    def set_peaks(self, peaks, duration: float,
                  sample_rate: int = 44100) -> None:
        """Charge une enveloppe ``(N, 2)`` et la durée qu'elle couvre."""
        try:
            array = np.asarray(peaks, dtype=np.float32)
            if array.ndim != 2 or array.shape[1] != 2 or array.size == 0:
                raise ValueError(f"forme inattendue : {array.shape}")
            self._peaks = array
        except Exception as exc:  # noqa: BLE001 - données inattendues
            log.debug("enveloppe illisible : %s", exc)
            self._peaks = None
        self._duration = max(0.0, float(duration or 0.0))
        self._sample_rate = max(1, int(sample_rate or 44100))
        self._view = (0.0, 1.0)
        self._selection = None
        self._position = None
        self.update()

    def clear(self) -> None:
        """Vide l'affichage."""
        self._peaks = None
        self._duration = 0.0
        self._position = None
        self._zone = None
        self._selection = None
        self._view = (0.0, 1.0)
        self.update()

    def has_data(self) -> bool:
        return self._peaks is not None and self._duration > 0

    def set_position(self, t: float | None) -> None:
        """Place la tête de lecture, en secondes."""
        self._position = None if t is None else max(0.0, float(t))
        self.update()

    def set_zone(self, a: float | None, b: float | None) -> None:
        """Place les marqueurs de zone, en secondes."""
        if a is None or b is None:
            self._zone = None
        else:
            start, end = sorted((max(0.0, float(a)), max(0.0, float(b))))
            self._zone = (start, end)
        self.update()

    def zone(self) -> tuple[float, float] | None:
        return self._zone

    def selection(self) -> tuple[float, float] | None:
        return self._selection

    def set_selection(self, a: float | None, b: float | None) -> None:
        if a is None or b is None:
            self._selection = None
        else:
            self._selection = tuple(sorted((float(a), float(b))))  # type: ignore[assignment]
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802 - API Qt
        return QSize(420, 110)

    # -- conversions temps <-> pixels -------------------------------------- #

    def _x_to_time(self, x: float) -> float:
        if self._duration <= 0:
            return 0.0
        low, high = self._view
        ratio = max(0.0, min(1.0, x / max(1.0, self.width())))
        return (low + ratio * (high - low)) * self._duration

    def _time_to_x(self, t: float) -> float:
        if self._duration <= 0:
            return 0.0
        low, high = self._view
        span = max(1e-9, high - low)
        return ((t / self._duration) - low) / span * self.width()

    # -- interaction -------------------------------------------------------- #

    def _handle_at(self, x: float) -> str:
        """``'zone_a'``/``'zone_b'`` si le pointeur saisit un marqueur."""
        if self._zone is None:
            return ""
        for name, value in (("zone_a", self._zone[0]), ("zone_b", self._zone[1])):
            if abs(self._time_to_x(value) - x) <= HANDLE_GRAB_PX:
                return name
        return ""

    def mousePressEvent(self, event) -> None:  # noqa: N802 - API Qt
        if not self.has_data() or event.button() != Qt.MouseButton.LeftButton:
            return
        x = event.position().x()
        handle = self._handle_at(x)
        if handle:
            self._drag = handle
            return
        self._drag = "select"
        self._drag_from = self._x_to_time(x)
        self._selection = None
        self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - API Qt
        if not self.has_data():
            return
        x = event.position().x()
        if not self._drag:
            # Curseur de redimensionnement au-dessus d'un marqueur.
            self.setCursor(Qt.CursorShape.SizeHorCursor if self._handle_at(x)
                           else Qt.CursorShape.CrossCursor)
            return

        now = self._x_to_time(x)
        if self._drag == "select":
            self._selection = tuple(sorted((self._drag_from, now)))  # type: ignore[assignment]
        elif self._drag == "zone_a" and self._zone is not None:
            self._zone = (min(now, self._zone[1]), self._zone[1])
        elif self._drag == "zone_b" and self._zone is not None:
            self._zone = (self._zone[0], max(now, self._zone[0]))
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - API Qt
        if not self._drag:
            return
        kind, self._drag = self._drag, ""
        try:
            if kind == "select":
                if self._selection is None:
                    # Presser puis relâcher sans bouger : c'est un clic, et
                    # c'est le geste le plus courant — placer la tête de
                    # lecture. Sans ce cas, aucun `mouseMoveEvent` n'ayant eu
                    # lieu, la sélection restait nulle et rien n'était émis.
                    self.set_position(self._drag_from)
                    self.positionClicked.emit(self._drag_from)
                else:
                    start, end = self._selection
                    if end - start < self._duration * 1e-4:
                        # Glisser d'un pixel : à traiter comme un clic.
                        self._selection = None
                        self.set_position(start)
                        self.positionClicked.emit(start)
                    else:
                        self.selectionChanged.emit(start, end)
            elif kind.startswith("zone") and self._zone is not None:
                self.zoneChanged.emit(self._zone[0], self._zone[1])
        except Exception:  # noqa: BLE001 - un abonné ne doit rien casser
            log.exception("abonné de la forme d'onde en échec")
        self.update()

    def wheelEvent(self, event) -> None:  # noqa: N802 - API Qt
        if not self.has_data():
            return
        low, high = self._view
        span = high - low
        steps = event.angleDelta().y() / 120.0

        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            # Défilement latéral.
            shift = -steps * span * 0.15
            low, high = low + shift, high + shift
        else:
            # Zoom centré sur le pointeur, pour que ce qu'on regarde reste
            # sous la souris.
            anchor = low + span * max(0.0, min(
                1.0, event.position().x() / max(1.0, self.width())))
            factor = 0.82 ** steps
            new_span = max(MIN_SPAN, min(1.0, span * factor))
            low = anchor - (anchor - low) * (new_span / span)
            high = low + new_span

        if high - low > 1.0:
            low, high = 0.0, 1.0
        if low < 0.0:
            low, high = 0.0, high - low
        if high > 1.0:
            low, high = low - (high - 1.0), 1.0
        self._view = (max(0.0, low), min(1.0, high))
        self.update()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - API Qt
        if event.key() in (Qt.Key.Key_Escape,):
            self._selection = None
            self._view = (0.0, 1.0)
            self.update()
            return
        super().keyPressEvent(event)

    # -- tracé -------------------------------------------------------------- #

    def paintEvent(self, event) -> None:  # noqa: N802 - API Qt
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            rect = QRectF(0, 0, self.width(), self.height())

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(PANEL_LO))
            painter.drawRect(rect)

            if not self.has_data():
                painter.setPen(QPen(QColor(GREY)))
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter,
                                 "Aucun échantillon sélectionné")
                painter.end()
                return

            middle = self.height() / 2.0
            self._draw_grid(painter, middle)
            self._draw_selection(painter)
            self._draw_wave(painter, middle)
            self._draw_zone(painter)
            self._draw_position(painter)
            painter.end()
        except Exception as exc:  # noqa: BLE001 - un tracé ne doit rien casser
            log.debug("tracé de la forme d'onde impossible : %s", exc)

    def _draw_grid(self, painter: QPainter, middle: float) -> None:
        """Repères temporels, espacés d'un pas lisible."""
        painter.setPen(QPen(QColor(PANEL_HI), 1))
        painter.drawLine(0, int(middle), self.width(), int(middle))

        low, high = self._view
        visible = max(1e-6, (high - low) * self._duration)
        # Pas « rond » le plus proche d'un repère tous les 90 pixels.
        target = visible / max(1.0, self.width() / 90.0)
        step = 0.001
        for candidate in (0.001, 0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0,
                          5.0, 10.0, 30.0, 60.0):
            step = candidate
            if candidate >= target:
                break

        start = low * self._duration
        first = step * int(start / step)
        t = first
        painter.setPen(QPen(QColor(PANEL_HI), 1, Qt.PenStyle.DotLine))
        while t <= high * self._duration:
            x = self._time_to_x(t)
            if 0 <= x <= self.width():
                painter.drawLine(int(x), 0, int(x), self.height())
            t += step

    def _draw_wave(self, painter: QPainter, middle: float) -> None:
        """Enveloppe min/max, rééchantillonnée à la largeur du widget."""
        assert self._peaks is not None
        low, high = self._view
        total = self._peaks.shape[0]
        first = int(low * total)
        last = max(first + 1, int(high * total))
        window = self._peaks[first:last]
        if window.size == 0:
            return

        width = max(1, self.width())
        scale = (self.height() / 2.0) * 0.92

        # Une colonne de pixels par pixel : on agrège l'enveloppe par tranche.
        indices = np.linspace(0, window.shape[0], width + 1).astype(np.int64)
        gradient = QLinearGradient(0.0, 0.0, 0.0, float(self.height()))
        gradient.setColorAt(0.0, QColor(GOLD_HI))
        gradient.setColorAt(0.5, QColor(GOLD))
        gradient.setColorAt(1.0, QColor(GOLD_HI))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)

        for x in range(width):
            a, b = indices[x], max(indices[x] + 1, indices[x + 1])
            slice_ = window[a:b]
            if slice_.size == 0:
                continue
            lo = float(np.min(slice_[:, 0]))
            hi = float(np.max(slice_[:, 1]))
            top = middle - hi * scale
            bottom = middle - lo * scale
            painter.drawRect(QRectF(x, top, 1.0, max(1.0, bottom - top)))

    def _draw_selection(self, painter: QPainter) -> None:
        if self._selection is None:
            return
        start, end = self._selection
        x1, x2 = self._time_to_x(start), self._time_to_x(end)
        colour = QColor(PAD_CYAN)
        colour.setAlphaF(0.18)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(colour)
        painter.drawRect(QRectF(x1, 0, max(1.0, x2 - x1), self.height()))

    def _draw_zone(self, painter: QPainter) -> None:
        """Marqueurs de début et de fin de zone, avec leurs poignées."""
        if self._zone is None:
            return
        for value in self._zone:
            x = self._time_to_x(value)
            if not -4 <= x <= self.width() + 4:
                continue
            painter.setPen(QPen(QColor(PAD_WHITE), 1))
            painter.drawLine(int(x), 0, int(x), self.height())
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(PAD_WHITE))
            painter.drawRect(QRectF(x - 3, 0, 6, 5))
            painter.drawRect(QRectF(x - 3, self.height() - 5, 6, 5))

    def _draw_position(self, painter: QPainter) -> None:
        if self._position is None:
            return
        x = self._time_to_x(self._position)
        if not 0 <= x <= self.width():
            return
        painter.setPen(QPen(QColor(PAD_CYAN), 2))
        painter.drawLine(int(x), 0, int(x), self.height())
