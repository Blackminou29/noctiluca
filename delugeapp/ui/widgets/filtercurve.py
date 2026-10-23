# -*- coding: utf-8 -*-
"""Courbe de réponse d'un filtre, et affichage de spectre.

:class:`FilterCurve` trace la réponse en fréquence d'un passe-bas ou d'un
passe-haut résonant, telle que :mod:`delugeapp.core.render` la calcule. Les
deux affichages partagent une abscisse **logarithmique**, de 20 Hz à 20 kHz :
c'est la seule échelle sur laquelle une octave occupe partout la même largeur,
et donc la seule qui corresponde à ce qu'on entend.

:class:`SpectrumView` affiche le résultat de
:func:`delugeapp.core.render.spectrum`.
"""

from __future__ import annotations

import logging
from math import log10

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from ...i18n import tr
from ..theme import (
    GOLD,
    GREY,
    PAD_CYAN,
    PAD_WHITE,
    PANEL_HI,
    PANEL_LO,
    mix,
)

log = logging.getLogger(__name__)

#: Bornes de l'axe des fréquences, en hertz.
F_MIN = 20.0
F_MAX = 20000.0

#: Bornes de l'axe des niveaux, en décibels.
DB_MIN = -48.0
DB_MAX = 18.0

#: Fréquences portant une étiquette.
F_TICKS = (50, 100, 200, 500, 1000, 2000, 5000, 10000)


def _freq_label(hz: float) -> str:
    """``2000`` -> ``2k``."""
    return f"{int(hz / 1000)}k" if hz >= 1000 else f"{int(hz)}"


class _LogAxis(QWidget):
    """Base commune : une grille logarithmique en fréquence."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(90)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Preferred)

    def sizeHint(self) -> QSize:  # noqa: N802 - API Qt
        return QSize(320, 130)

    def _plot(self) -> QRectF:
        return QRectF(6.0, 6.0, max(20.0, self.width() - 12.0),
                      max(20.0, self.height() - 20.0))

    def _x_of(self, hz: float) -> float:
        """Abscisse d'une fréquence, en échelle logarithmique."""
        plot = self._plot()
        value = max(F_MIN, min(F_MAX, float(hz)))
        ratio = (log10(value) - log10(F_MIN)) / (log10(F_MAX) - log10(F_MIN))
        return plot.left() + ratio * plot.width()

    def _y_of_db(self, db: float) -> float:
        plot = self._plot()
        ratio = (max(DB_MIN, min(DB_MAX, float(db))) - DB_MIN) / (DB_MAX - DB_MIN)
        return plot.bottom() - ratio * plot.height()

    def _draw_background(self, painter: QPainter) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(PANEL_LO))
        painter.drawRoundedRect(QRectF(0, 0, self.width(), self.height()),
                                6, 6)

    def _draw_grid(self, painter: QPainter, labels: bool = True) -> None:
        plot = self._plot()
        painter.setPen(QPen(QColor(PANEL_HI), 1, Qt.PenStyle.DotLine))
        for hz in F_TICKS:
            x = self._x_of(hz)
            painter.drawLine(int(x), int(plot.top()), int(x),
                             int(plot.bottom()))
        for db in (-36, -24, -12, 0, 12):
            y = self._y_of_db(db)
            painter.drawLine(int(plot.left()), int(y), int(plot.right()),
                             int(y))

        if not labels:
            return
        painter.setPen(QPen(QColor(GREY)))
        font = painter.font()
        font.setPointSize(7)
        painter.setFont(font)
        for hz in F_TICKS:
            x = self._x_of(hz)
            painter.drawText(QRectF(x - 18, plot.bottom() + 2, 36, 14),
                             Qt.AlignmentFlag.AlignCenter, _freq_label(hz))


def _set_accent(widget, color: str) -> None:
    """Change la couleur de la courbe et redessine."""
    widget._accent = color or widget._accent
    widget.update()


class FilterCurve(_LogAxis):
    """Réponse d'un filtre résonant, mise à jour en direct.

    Les valeurs d'entrée sont celles de l'écran du Deluge, de 0 à 50 : c'est
    ce que manipulent les encodeurs de la page des presets, et la conversion
    en hertz utilise la même courbe que le moteur de rendu, pour que ce qu'on
    voit corresponde à ce qu'on entend.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._accent = GOLD
        self._cutoff = 40
        self._resonance = 10
        self._mode = "24dB"
        self._hpf_cutoff: int | None = None

    def set_accent(self, color: str) -> None:
        """Trace la réponse à la couleur de la page qui l'accueille."""
        _set_accent(self, color)

    def accent(self) -> str:
        return self._accent

    def set_filter(self, cutoff: int, resonance: int,
                   mode: str = "24dB") -> None:
        """Règle le passe-bas, en unités d'affichage 0..50."""
        self._cutoff = max(0, min(50, int(cutoff)))
        self._resonance = max(0, min(50, int(resonance)))
        self._mode = str(mode or "24dB")
        self.update()

    def set_hpf(self, cutoff: int | None) -> None:
        """Ajoute un passe-haut à la courbe, ou le retire."""
        self._hpf_cutoff = None if cutoff is None else max(0, min(50, int(cutoff)))
        self.update()

    def filter_settings(self) -> tuple[int, int, str]:
        return self._cutoff, self._resonance, self._mode

    def _response_db(self, freqs: np.ndarray) -> np.ndarray:
        """Réponse combinée des deux filtres, en décibels.

        Reprend ``render._response``, ``render._cutoff_hz`` et
        ``render._hpf_hz`` pour que la courbe affichée soit exactement celle
        que le rendu applique — aux lois du firmware (:mod:`paramlaws`).
        """
        from ...core.render import _cutoff_hz, _hpf_hz, _resonance_q, _response

        poles = 2 if self._mode == "12dB" else 4
        cutoff = _cutoff_hz(self._cutoff / 50.0)
        q = _resonance_q(self._resonance / 50.0)
        response = _response(freqs, cutoff, q, poles)

        if self._hpf_cutoff is not None:
            hp_cut = _hpf_hz(self._hpf_cutoff / 50.0)
            response = response * _response(freqs, hp_cut, 0.707, 2,
                                            high_pass=True)
        magnitude = np.abs(response)
        return 20.0 * np.log10(np.maximum(magnitude, 1e-6))

    def paintEvent(self, event) -> None:  # noqa: N802 - API Qt
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            self._draw_background(painter)
            self._draw_grid(painter)

            plot = self._plot()
            width = max(8, int(plot.width()))
            # Un point par pixel, répartis logarithmiquement.
            ratios = np.linspace(0.0, 1.0, width)
            freqs = F_MIN * (F_MAX / F_MIN) ** ratios
            db = self._response_db(freqs.astype(np.float64))

            path = QPainterPath()
            for index in range(width):
                point = QPointF(plot.left() + index,
                                self._y_of_db(float(db[index])))
                if index == 0:
                    path.moveTo(point)
                else:
                    path.lineTo(point)

            filled = QPainterPath(path)
            filled.lineTo(plot.right(), plot.bottom())
            filled.lineTo(plot.left(), plot.bottom())
            filled.closeSubpath()

            gradient = QLinearGradient(0.0, plot.top(), 0.0, plot.bottom())
            top = QColor(self._accent)
            top.setAlphaF(0.30)
            bottom = QColor(self._accent)
            bottom.setAlphaF(0.02)
            gradient.setColorAt(0.0, top)
            gradient.setColorAt(1.0, bottom)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(gradient)
            painter.drawPath(filled)

            pen = QPen(QColor(mix(self._accent, PAD_WHITE, 0.30)))
            pen.setWidthF(2.0)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)

            # Repère de coupure.
            from ...core.render import _cutoff_hz

            cutoff_hz = _cutoff_hz(self._cutoff / 50.0)
            x = self._x_of(cutoff_hz)
            repere = QColor(PAD_WHITE)
            repere.setAlphaF(0.55)
            painter.setPen(QPen(repere, 1, Qt.PenStyle.DashLine))
            painter.drawLine(int(x), int(plot.top()), int(x),
                             int(plot.bottom()))

            painter.setPen(QPen(QColor(GREY)))
            font = painter.font()
            font.setPointSize(7)
            painter.setFont(font)
            painter.drawText(
                QRectF(plot.left() + 4, plot.top() + 2, plot.width() - 8, 14),
                Qt.AlignmentFlag.AlignLeft,
                tr("%s · coupure %sHz · résonance %s")
                % (self._mode, _freq_label(cutoff_hz), self._resonance))
            painter.end()
        except Exception as exc:  # noqa: BLE001 - un tracé ne doit rien casser
            log.debug("tracé de la courbe de filtre impossible : %s", exc)


class SpectrumView(_LogAxis):
    """Spectre d'un signal, en échelle logarithmique.

    Alimenté par :func:`delugeapp.core.render.spectrum`, qui rend déjà des
    décibels relatifs au maximum.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._accent = PAD_CYAN
        self._freqs: np.ndarray | None = None
        self._db: np.ndarray | None = None
        # Réglable : « écoutez un échantillon » ne veut rien dire dans
        # le générateur, où le son n'existe pas encore : il s'y fabrique.
        self._empty_text = tr("Aucun signal analysé\n\n"
                              "Écoutez un échantillon pour voir son "
                              "spectre")

    def set_accent(self, color: str) -> None:
        """Trace le spectre à la couleur de la page qui l'accueille."""
        _set_accent(self, color)

    def accent(self) -> str:
        return self._accent

    def set_empty_text(self, texte: str) -> None:
        """Change ce qui s'affiche quand aucun spectre n'est chargé."""
        self._empty_text = str(texte or "")
        self.update()

    def set_spectrum(self, freqs, db) -> None:
        """Charge un spectre : fréquences et amplitudes en dB."""
        try:
            f = np.asarray(freqs, dtype=np.float64)
            d = np.asarray(db, dtype=np.float64)
            if f.size != d.size or f.size == 0:
                raise ValueError(tr("tailles incompatibles : %d/%d")
                                 % (f.size, d.size))
            self._freqs, self._db = f, d
        except Exception as exc:  # noqa: BLE001 - données inattendues
            log.debug("spectre illisible : %s", exc)
            self._freqs = self._db = None
        self.update()

    def set_audio(self, data, sample_rate: int = 44100) -> None:
        """Calcule et affiche le spectre d'un signal."""
        try:
            from ...core.render import spectrum

            self.set_spectrum(*spectrum(data, sample_rate))
        except Exception as exc:  # noqa: BLE001
            log.debug("calcul du spectre impossible : %s", exc)
            self.clear()

    def clear(self) -> None:
        self._freqs = self._db = None
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - API Qt
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            self._draw_background(painter)
            self._draw_grid(painter)

            plot = self._plot()
            if self._freqs is None or self._db is None:
                # La grille est déjà tracée : le cadre n'est pas en panne, il
                # manque un son. On le dit, et on dit quoi faire.
                painter.setPen(QPen(QColor(GREY)))
                painter.drawText(plot,
                                 Qt.AlignmentFlag.AlignCenter,
                                 self._empty_text)
                painter.end()
                return

            # Un point par pixel : on interpole le spectre sur l'axe log.
            width = max(8, int(plot.width()))
            ratios = np.linspace(0.0, 1.0, width)
            targets = F_MIN * (F_MAX / F_MIN) ** ratios
            values = np.interp(targets, self._freqs, self._db,
                               left=DB_MIN, right=DB_MIN)

            path = QPainterPath()
            for index in range(width):
                point = QPointF(plot.left() + index,
                                self._y_of_db(float(values[index])))
                if index == 0:
                    path.moveTo(point)
                else:
                    path.lineTo(point)

            filled = QPainterPath(path)
            filled.lineTo(plot.right(), plot.bottom())
            filled.lineTo(plot.left(), plot.bottom())
            filled.closeSubpath()

            gradient = QLinearGradient(0.0, plot.top(), 0.0, plot.bottom())
            top = QColor(self._accent)
            top.setAlphaF(0.34)
            bottom = QColor(self._accent)
            bottom.setAlphaF(0.02)
            gradient.setColorAt(0.0, top)
            gradient.setColorAt(1.0, bottom)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(gradient)
            painter.drawPath(filled)

            pen = QPen(QColor(self._accent))
            pen.setWidthF(1.6)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
            painter.end()
        except Exception as exc:  # noqa: BLE001 - un tracé ne doit rien casser
            log.debug("tracé du spectre impossible : %s", exc)
