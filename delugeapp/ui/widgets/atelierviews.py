# -*- coding: utf-8 -*-
"""Les deux vues de l'atelier, tracées comme la façade du Deluge.

* :class:`ClipView` — un clip : ses notes en pads sur un rouleau de piano,
  ou, pour une batterie, une rangée par son et un pad par double-croche ;
* :class:`SectionMatrix` — le morceau : une rangée par piste, une colonne
  par section, et dans chaque case le pad allumé du clip qu'elle joue, à la
  lettre de ce clip — la grille de la machine en disposition « grille ».

Tout est tracé au :class:`QPainter`, dans un seul widget chacun.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from ...i18n import tr
from .. import art
from ..theme import (BORDER, GOLD, GREY, PAD_OFF, PAD_WHITE, PANEL_LO,
                     TEXT_SOFT, mix, text_on)

log = logging.getLogger(__name__)

#: Couleur de chaque partie : la même dans toutes les vues de l'atelier.
PART_COLORS = {
    "Batterie": "#3DD160",      # PAD_GREEN, la couleur des kits
    "Basse": "#3E86F5",         # PAD_BLUE
    "Accords": "#A85BE0",       # PAD_PURPLE
    "Arpège": "#28C4E0",        # PAD_CYAN
    "Mélodie": "#FF8C1A",       # PAD_ORANGE
}


def part_color(part: str) -> str:
    return PART_COLORS.get(str(part or ""), GOLD)


class ClipView(QWidget):
    """Un clip, lu comme sur la machine en vue clip."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._events: list = []
        self._pattern = None
        self._rows: list[str] = []
        self._steps = 16
        self._color = GOLD
        self._empty = (tr("Aucun clip choisi"),
                       tr("Choisissez une piste et un de ses clips"))
        self._playhead: float | None = None
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)

    def sizeHint(self) -> QSize:  # noqa: N802 - API Qt
        return QSize(640, 220)

    def set_empty_text(self, title: str, detail: str = "") -> None:
        self._empty = (title, detail)
        self.update()

    def set_clip(self, clip, color: str = GOLD, rows=None) -> None:
        """Montre ``clip`` (:class:`atelier.AtelierClip`) ; ``None`` vide la
        vue. ``rows`` donne l'ordre des rangées d'une batterie, du bas vers
        le haut."""
        self._color = color or GOLD
        if clip is None:
            self._events, self._pattern, self._rows = [], None, []
            self._steps = 16
        else:
            self._steps = max(1, int(clip.bars) * 16)
            self._pattern = clip.pattern
            self._events = list(clip.events or [])
            if clip.pattern is not None:
                names = [r for r in (rows or []) if r and r
                         in clip.pattern.tracks]
                names += [n for n in clip.pattern.tracks if n not in names]
                self._rows = names
            else:
                self._rows = []
        self.update()

    def set_playhead(self, step: float | None) -> None:
        self._playhead = step
        self.update()

    def is_empty(self) -> bool:
        return not self._events and self._pattern is None

    # -- tracé --------------------------------------------------------------- #

    def paintEvent(self, event) -> None:  # noqa: N802 - API Qt
        try:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            area = QRectF(self.rect()).adjusted(1, 1, -1, -1)
            p.setPen(QPen(QColor(BORDER), 1))
            p.setBrush(QColor(PANEL_LO))
            p.drawRoundedRect(area, 12, 12)
            if self.is_empty():
                self._paint_empty(p, area)
            elif self._pattern is not None:
                self._paint_drums(p, area.adjusted(10, 10, -10, -10))
            else:
                self._paint_notes(p, area.adjusted(10, 10, -10, -10))
            p.end()
        except Exception as exc:     # noqa: BLE001 - un tracé ne casse rien
            log.debug("vue du clip non tracée : %s", exc)

    def _paint_empty(self, p: QPainter, area: QRectF) -> None:
        title, detail = self._empty
        font = QFont(self.font())
        font.setPointSizeF(font.pointSizeF() * 1.15)
        font.setBold(True)
        p.setFont(font)
        p.setPen(QColor(PAD_WHITE))
        upper = QRectF(area.left(), area.center().y() - 26, area.width(), 24)
        p.drawText(upper, Qt.AlignmentFlag.AlignCenter, title)
        p.setFont(self.font())
        p.setPen(QColor(TEXT_SOFT))
        lower = QRectF(area.left(), area.center().y() + 2, area.width(), 22)
        p.drawText(lower, Qt.AlignmentFlag.AlignCenter, detail)

    def _grid(self, p: QPainter, area: QRectF, cell_w: float) -> None:
        """Les temps et les mesures, comme les colonnes de la machine."""
        for step in range(self._steps + 1):
            x = area.left() + step * cell_w
            if step % 16 == 0:
                p.setPen(QPen(QColor(mix(GOLD, PANEL_LO, 0.35)), 1.4))
            elif step % 4 == 0:
                p.setPen(QPen(QColor(mix(GREY, PANEL_LO, 0.55)), 1))
            else:
                continue
            p.drawLine(QPointF(x, area.top()), QPointF(x, area.bottom()))

    def _paint_drums(self, p: QPainter, area: QRectF) -> None:
        rows = self._rows or ["?"]
        label_w = min(86.0, area.width() * 0.16)
        grid = area.adjusted(label_w, 0, 0, 0)
        cell_w = grid.width() / float(self._steps)
        cell_h = grid.height() / float(len(rows))
        pad = max(2.0, min(cell_w, cell_h) * 0.78)
        p.setFont(self.font())
        for index, name in enumerate(rows):
            # La rangée 0 en bas, comme sur la machine.
            top = grid.bottom() - (index + 1) * cell_h
            p.setPen(QColor(TEXT_SOFT))
            p.drawText(QRectF(area.left(), top, label_w - 6, cell_h),
                       Qt.AlignmentFlag.AlignRight
                       | Qt.AlignmentFlag.AlignVCenter, tr(name))
            hits = {}
            for step in self._pattern.tracks.get(name, []):
                hits[int(round(float(step.pos)))] = int(step.velocity)
            for col in range(self._steps):
                rect = QRectF(grid.left() + col * cell_w
                              + (cell_w - pad) / 2.0,
                              top + (cell_h - pad) / 2.0, pad, pad)
                velocity = hits.get(col)
                if velocity is None:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(PAD_OFF if (col // 4) % 2 == 0
                                      else mix(PAD_OFF, PANEL_LO, 0.4)))
                    p.drawRoundedRect(rect, pad * 0.22, pad * 0.22)
                else:
                    shade = mix(PANEL_LO, self._color,
                                0.45 + 0.55 * max(0, min(100, velocity))
                                / 100.0)
                    art.paint_pad(p, rect, shade, glow=0.0,
                                  radius=pad * 0.22, sheen=pad >= 8)
        self._paint_playhead(p, grid, cell_w)

    def _paint_notes(self, p: QPainter, area: QRectF) -> None:
        notes = [int(e.note) for e in self._events]
        low, high = min(notes), max(notes)
        if high - low < 11:
            centre = (high + low) // 2
            low, high = centre - 6, centre + 6
        low, high = low - 1, high + 1
        span = high - low + 1
        label_w = min(46.0, area.width() * 0.09)
        grid = area.adjusted(label_w, 0, 0, 0)
        cell_w = grid.width() / float(self._steps)
        row_h = grid.height() / float(span)
        # Les rangées des do, plus claires : on s'y repère.
        p.setFont(self.font())
        for note in range(low, high + 1):
            top = grid.bottom() - (note - low + 1) * row_h
            if note % 12 == 0:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(mix(PANEL_LO, PAD_WHITE, 0.05)))
                p.drawRect(QRectF(grid.left(), top, grid.width(), row_h))
                p.setPen(QColor(TEXT_SOFT))
                from ...core.theory import note_to_name

                p.drawText(QRectF(area.left(), top - 4, label_w - 4,
                                  row_h + 8),
                           Qt.AlignmentFlag.AlignRight
                           | Qt.AlignmentFlag.AlignVCenter,
                           note_to_name(note))
        self._grid(p, grid, cell_w)
        for event in self._events:
            top = grid.bottom() - (int(event.note) - low + 1) * row_h
            rect = QRectF(grid.left() + float(event.start) * cell_w + 1,
                          top + 1, max(3.0, float(event.length) * cell_w - 2),
                          max(3.0, row_h - 2))
            shade = mix(PANEL_LO, self._color,
                        0.5 + 0.5 * max(0, min(100, int(event.velocity)))
                        / 100.0)
            art.paint_pad(p, rect, shade, glow=0.0,
                          radius=min(rect.height(), rect.width()) * 0.3,
                          sheen=rect.height() >= 8)
        self._paint_playhead(p, grid, cell_w)

    def _paint_playhead(self, p: QPainter, grid: QRectF,
                        cell_w: float) -> None:
        if self._playhead is None:
            return
        x = grid.left() + (float(self._playhead) % self._steps) * cell_w
        p.setPen(QPen(QColor(GOLD), 2))
        p.drawLine(QPointF(x, grid.top()), QPointF(x, grid.bottom()))


class SectionMatrix(QWidget):
    """Le morceau : pistes en rangées, sections en colonnes.

    Chaque case est le pad du clip que la piste joue dans la section, à la
    couleur de sa partie et à la lettre de son clip ; une case éteinte, la
    piste se tait. Un clic sur une case émet :attr:`cellClicked`, un clic
    sur l'en-tête d'une section :attr:`sectionClicked`.
    """

    cellClicked = pyqtSignal(int, int)          # section, piste (uid)
    sectionClicked = pyqtSignal(int)

    LABEL_W = 150
    HEAD_H = 46
    ROW_H = 42
    COL_W = 92

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tracks: list[tuple[int, str, str]] = []    # uid, nom, couleur
        self._sections: list[tuple[str, int, dict]] = []
        self._current = -1
        self._hover: tuple[int, int] | None = None
        self._origins: dict[tuple[int, str], bool] = {}
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Preferred)

    def set_project(self, tracks, sections, current: int = -1,
                    existing: dict | None = None) -> None:
        """``tracks`` : ``[(uid, nom, couleur)]`` ; ``sections`` :
        ``[(nom, mesures, {uid: clé})]`` ; ``existing`` : ``{(uid, clé):
        vrai}`` pour les clips déjà sur la carte (tracés d'un liseré)."""
        self._tracks = list(tracks)
        self._sections = list(sections)
        self._current = int(current)
        self._origins = dict(existing or {})
        self.updateGeometry()
        self.update()

    def set_current(self, index: int) -> None:
        self._current = int(index)
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802 - API Qt
        cols = max(1, len(self._sections))
        rows = max(1, len(self._tracks))
        return QSize(self.LABEL_W + cols * self.COL_W + 12,
                     self.HEAD_H + rows * self.ROW_H + 12)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - API Qt
        return self.sizeHint()

    def _cell_rect(self, col: int, row: int) -> QRectF:
        return QRectF(self.LABEL_W + col * self.COL_W + 4,
                      self.HEAD_H + row * self.ROW_H + 4,
                      self.COL_W - 8, self.ROW_H - 8)

    def _hit(self, x: float, y: float) -> tuple[int, int] | None:
        if x < self.LABEL_W:
            return None
        col = int((x - self.LABEL_W) // self.COL_W)
        if not 0 <= col < len(self._sections):
            return None
        if y < self.HEAD_H:
            return col, -1
        row = int((y - self.HEAD_H) // self.ROW_H)
        if not 0 <= row < len(self._tracks):
            return None
        return col, row

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - API Qt
        hit = self._hit(event.position().x(), event.position().y())
        if hit != self._hover:
            self._hover = hit
            self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802 - API Qt
        self._hover = None
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - API Qt
        if event.button() != Qt.MouseButton.LeftButton:
            return
        hit = self._hit(event.position().x(), event.position().y())
        if hit is None:
            return
        col, row = hit
        if row < 0:
            self.sectionClicked.emit(col)
        else:
            self.cellClicked.emit(col, self._tracks[row][0])

    def paintEvent(self, event) -> None:  # noqa: N802 - API Qt
        try:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            base = QFont(self.font())
            bold = QFont(base)
            bold.setBold(True)
            for row, (_uid, name, color) in enumerate(self._tracks):
                top = self.HEAD_H + row * self.ROW_H
                dot = QRectF(6, top + self.ROW_H / 2.0 - 7, 14, 14)
                art.paint_pad(p, dot, color, glow=0.0, radius=3)
                p.setFont(base)
                p.setPen(QColor(PAD_WHITE))
                p.drawText(QRectF(26, top, self.LABEL_W - 30, self.ROW_H),
                           Qt.AlignmentFlag.AlignVCenter
                           | Qt.AlignmentFlag.AlignLeft,
                           p.fontMetrics().elidedText(
                               name, Qt.TextElideMode.ElideRight,
                               self.LABEL_W - 32))
            for col, (title, bars, cells) in enumerate(self._sections):
                left = self.LABEL_W + col * self.COL_W
                head = QRectF(left + 3, 4, self.COL_W - 6, self.HEAD_H - 10)
                current = col == self._current
                p.setPen(QPen(QColor(GOLD if current else BORDER),
                              1.6 if current else 1))
                p.setBrush(QColor(mix(PANEL_LO, GOLD, 0.16) if current
                                  else PANEL_LO))
                p.drawRoundedRect(head, 8, 8)
                p.setFont(bold)
                p.setPen(QColor(PAD_WHITE))
                p.drawText(head.adjusted(4, 2, -4, -head.height() / 2.0),
                           Qt.AlignmentFlag.AlignCenter,
                           p.fontMetrics().elidedText(
                               title, Qt.TextElideMode.ElideRight,
                               int(head.width() - 8)))
                p.setFont(base)
                p.setPen(QColor(TEXT_SOFT))
                p.drawText(head.adjusted(4, head.height() / 2.0, -4, -2),
                           Qt.AlignmentFlag.AlignCenter,
                           tr("%d mes.") % int(bars))
                for row, (uid, _name, color) in enumerate(self._tracks):
                    rect = self._cell_rect(col, row)
                    key = cells.get(uid)
                    if key:
                        if current:
                            art.paint_glow(p, rect, color, 0.20, 0.45)
                        art.paint_pad(p, rect, color, glow=0.0, radius=8)
                        if self._origins.get((uid, key)):
                            p.setPen(QPen(QColor(mix(color, "#FFFFFF", 0.7)),
                                          1.4, Qt.PenStyle.DotLine))
                            p.setBrush(Qt.BrushStyle.NoBrush)
                            p.drawRoundedRect(rect.adjusted(3, 3, -3, -3),
                                              6, 6)
                        p.setFont(bold)
                        p.setPen(QColor(text_on(color)))
                        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, key)
                    else:
                        art.paint_off_pad(p, rect, diode=False, radius=8)
                    if self._hover == (col, row):
                        p.setPen(QPen(QColor(GOLD), 1.8))
                        p.setBrush(Qt.BrushStyle.NoBrush)
                        p.drawRoundedRect(rect, 8, 8)
            p.end()
        except Exception as exc:     # noqa: BLE001
            log.debug("matrice des sections non tracée : %s", exc)
