# -*- coding: utf-8 -*-
"""Les vues de l'atelier, tracées comme la façade du Deluge.

* :class:`StepBar` — les cinq étapes du morceau, une rangée de pads
  numérotés reliés par une piste : où l'on est, et ce qui vient ensuite ;
* :class:`ClipView` — un clip : ses notes en pads sur un rouleau de piano,
  ou, pour une batterie, une rangée par son et un pad par double-croche —
  qu'un clic allume ou éteint ;
* :class:`SectionMatrix` — le morceau : une rangée par piste, une colonne
  par section, et dans chaque case le pad allumé du clip qu'elle joue, à la
  lettre de ce clip — la grille de la machine en disposition « grille ».

Tout est tracé au :class:`QPainter`, dans un seul widget chacun.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PyQt6.QtWidgets import QHBoxLayout, QPushButton, QSizePolicy, QWidget

from ...i18n import tr
from .. import art
from ..theme import (BORDER, BORDER_HI, GOLD, GREY, PAD_AMBER, PAD_BLUE,
                     PAD_GREEN, PAD_OFF, PAD_PURPLE, PAD_RED, PAD_WHITE,
                     PANEL_LO, TEXT_SOFT, mix, readable, text_on)

log = logging.getLogger(__name__)

#: La couleur de chaque étape : le rouge de l'atelier pour le départ, puis
#: celle de ce qu'on y fait — les sons au violet des presets, les clips au
#: vert des kits, la structure au bleu des morceaux, le Deluge à l'ambre.
STEP_COLORS = (PAD_RED, PAD_PURPLE, PAD_GREEN, PAD_BLUE, PAD_AMBER)


class StepButton(QPushButton):
    """Une étape : un pad numéroté et son nom en capitales.

    Choisie, elle s'allume ; franchie, son pad reste éclairé en veilleuse ;
    à venir, il est éteint. Reste un ``QPushButton`` cochable, que la page
    et les tests cliquent comme un autre.
    """

    HAUTEUR = 40

    def __init__(self, number: int, title: str, color: str,
                 parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)
        self.setFixedHeight(self.HAUTEUR)
        self._numero = int(number)
        self._couleur = color
        self._franchie = False
        self._survol = False
        self._police = QFont(self.font())
        self._police.setPointSizeF(max(7.5, self._police.pointSizeF() * 0.92))
        self._police.setBold(True)
        self._police.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.4)
        self._police.setCapitalization(QFont.Capitalization.AllUppercase)
        self._chiffre = QFont(self._police)
        self._chiffre.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0)

    def color(self) -> str:
        return self._couleur

    def set_done(self, done: bool) -> None:
        """Étape déjà franchie : son pad garde une lueur."""
        if bool(done) != self._franchie:
            self._franchie = bool(done)
            self.update()

    def is_done(self) -> bool:
        return self._franchie

    def sizeHint(self) -> QSize:  # noqa: N802 - API Qt
        largeur = QFontMetricsF(self._police).horizontalAdvance(
            self.text().upper())
        return QSize(int(largeur) + 64, self.HAUTEUR)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - API Qt
        return QSize(44, self.HAUTEUR)

    def enterEvent(self, event) -> None:  # noqa: N802 - API Qt
        self._survol = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - API Qt
        self._survol = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 - API Qt
        try:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            actif = self.isChecked()
            cote = 28.0
            pad = QRectF(8.0, (self.height() - cote) / 2.0, cote, cote)
            if actif:
                bande = QRectF(self.rect()).adjusted(2, 2, -2, -2)
                teinte = QColor(self._couleur)
                teinte.setAlphaF(0.14)
                p.setPen(QPen(QColor(mix(self._couleur, PANEL_LO, 0.35)), 1))
                p.setBrush(teinte)
                p.drawRoundedRect(bande, 12, 12)
                art.paint_pad(p, pad, self._couleur, glow=0.45, radius=7.5)
            elif self._franchie:
                art.paint_pad(p, pad, mix(PANEL_LO, self._couleur, 0.55),
                              glow=0.0, radius=7.5)
            else:
                art.paint_off_pad(p, pad, diode=False, radius=7.5)
                cadre = QColor(self._couleur)
                cadre.setAlphaF(0.75 if self._survol else 0.45)
                p.setPen(QPen(cadre, 1.2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(pad.adjusted(0.6, 0.6, -0.6, -0.6), 7, 7)
            p.setFont(self._chiffre)
            p.setPen(QColor(text_on(self._couleur) if (actif or self._franchie)
                            else readable(self._couleur, PANEL_LO)))
            p.drawText(pad, int(Qt.AlignmentFlag.AlignCenter),
                       str(self._numero))
            if self.width() >= 70:
                p.setFont(self._police)
                p.setPen(QColor(PAD_WHITE if (actif or self._survol)
                                else TEXT_SOFT))
                zone = QRectF(pad.right() + 10, 0,
                              self.width() - pad.right() - 14, self.height())
                texte = QFontMetricsF(self._police).elidedText(
                    self.text().upper(), Qt.TextElideMode.ElideRight,
                    zone.width())
                p.drawText(zone, int(Qt.AlignmentFlag.AlignVCenter
                                     | Qt.AlignmentFlag.AlignLeft), texte)
            p.end()
        except Exception as exc:     # noqa: BLE001 - un tracé ne casse rien
            log.debug("étape non tracée : %s", exc)


class StepBar(QWidget):
    """Les étapes du morceau, de gauche à droite, reliées par une piste.

    Un clic sur une étape émet :attr:`stepClicked` ; la page dit laquelle
    est affichée (:meth:`set_current`) et jusqu'où l'on est allé
    (:meth:`set_reached`).
    """

    stepClicked = pyqtSignal(int)

    def __init__(self, titles, colors=STEP_COLORS,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        rangee = QHBoxLayout(self)
        rangee.setContentsMargins(0, 0, 0, 0)
        rangee.setSpacing(18)
        self.buttons: list[StepButton] = []
        for index, titre in enumerate(titles):
            bouton = StepButton(index + 1, titre,
                                colors[index % len(colors)], self)
            bouton.clicked.connect(
                lambda _c=False, i=index: self.stepClicked.emit(i))
            rangee.addWidget(bouton)
            self.buttons.append(bouton)
        self._courante = 0
        self.set_current(0)

    def current(self) -> int:
        return self._courante

    def set_current(self, index: int) -> None:
        self._courante = int(index)
        for rang, bouton in enumerate(self.buttons):
            bouton.setChecked(rang == self._courante)
        self.update()

    def set_reached(self, last: int) -> None:
        """Les étapes jusqu'à ``last`` comprise sont franchies."""
        for rang, bouton in enumerate(self.buttons):
            bouton.set_done(rang <= int(last))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - API Qt
        """La piste qui relie les pads, comme les pistes du treillis."""
        try:
            if len(self.buttons) < 2:
                return
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            for gauche, droite in zip(self.buttons, self.buttons[1:]):
                y = gauche.geometry().center().y()
                x1 = gauche.geometry().right() - 2
                x2 = droite.geometry().left() + 4
                franchie = droite.is_done() or droite.isChecked()
                stylo = QPen(QColor(mix(PANEL_LO, droite.color(), 0.6)
                                    if franchie else BORDER_HI), 1.6)
                p.setPen(stylo)
                p.drawLine(QPointF(x1, y), QPointF(x2, y))
            p.end()
        except Exception as exc:     # noqa: BLE001
            log.debug("piste des étapes non tracée : %s", exc)

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
    """Un clip, lu comme sur la machine en vue clip.

    Une batterie se dessine à la souris quand la vue est modifiable
    (:meth:`set_clip` avec ``editable``) : un clic sur une case émet
    :attr:`hitToggled` avec la rangée et le pas, et la page allume ou éteint
    le coup. Un clip de synthé aussi : :attr:`noteToggled` donne la hauteur
    et le pas, et la page ajoute la note ou retire celle qu'on a touchée.
    """

    #: Un clic dans la grille d'une batterie : (rangée, pas).
    hitToggled = pyqtSignal(str, int)
    #: Un clic dans la grille d'un synthé : (note MIDI, pas).
    noteToggled = pyqtSignal(int, int)

    #: Hauteurs montrées au moins, pour un clip de synthé qu'on dessine.
    EDIT_SPAN = 24

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._events: list = []
        self._pattern = None
        self._rows: list[str] = []
        self._steps = 16
        self._color = GOLD
        self._editable = False
        self._hover: tuple[str, int] | None = None
        self._empty = (tr("Aucun clip choisi"),
                       tr("Choisissez une piste et un de ses clips"))
        self._playhead: float | None = None
        #: Plage de hauteurs d'un clip de synthé qu'on dessine : gardée d'un
        #: clic à l'autre, sans quoi la grille sautait dès qu'on retirait la
        #: note la plus haute.
        self._note_range: tuple[int, int] | None = None
        self._clip_id: int | None = None
        self.setMinimumHeight(150)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)

    def sizeHint(self) -> QSize:  # noqa: N802 - API Qt
        return QSize(640, 220)

    def set_empty_text(self, title: str, detail: str = "") -> None:
        self._empty = (title, detail)
        self.update()

    def set_clip(self, clip, color: str = GOLD, rows=None,
                 editable: bool = False) -> None:
        """Montre ``clip`` (:class:`atelier.AtelierClip`) ; ``None`` vide la
        vue. ``rows`` donne l'ordre des rangées d'une batterie, du bas vers
        le haut ; une vue modifiable les montre toutes, même sans coup, pour
        qu'on puisse en ajouter."""
        self._color = color or GOLD
        self._editable = bool(editable) and clip is not None
        self._hover = None
        meme = clip is not None and id(clip) == self._clip_id
        self._clip_id = id(clip) if clip is not None else None
        if clip is None:
            self._events, self._pattern, self._rows = [], None, []
            self._steps = 16
        else:
            self._steps = max(1, int(clip.bars) * 16)
            self._pattern = clip.pattern
            self._events = list(clip.events or [])
            if clip.pattern is not None:
                names = [r for r in (rows or []) if r and (
                    self._editable or r in clip.pattern.tracks)]
                names += [n for n in clip.pattern.tracks if n not in names]
                self._rows = names
            else:
                self._rows = []
                self._note_range = self._span_for(
                    self._note_range if meme and self._editable else None)
        self.setCursor(Qt.CursorShape.PointingHandCursor if self._editable
                       else Qt.CursorShape.ArrowCursor)
        self.update()

    def is_editable(self) -> bool:
        return self._editable

    def _span_for(self, kept: tuple[int, int] | None) -> tuple[int, int]:
        """Les hauteurs que montre un clip de synthé : celles de ses notes,
        une de plus de part et d'autre ; deux octaves au moins quand on le
        dessine, autour de ses notes ou du do 4 d'un clip vide."""
        notes = [int(e.note) for e in self._events]
        if notes:
            low, high = min(notes), max(notes)
        else:
            low = high = 60
        minimum = self.EDIT_SPAN if self._editable else 12
        if high - low < minimum - 1:
            centre = (high + low) // 2
            low, high = centre - minimum // 2, centre + minimum // 2
        low, high = max(0, low - 1), min(127, high + 1)
        if kept is not None:
            low, high = min(low, kept[0]), max(high, kept[1])
        return low, high

    def _note_geometry(self) -> tuple[QRectF, QRectF, float, float, int]:
        """``(zone, grille, largeur d'un pas, hauteur d'une note, plus basse
        note)`` d'un clip de synthé."""
        area = QRectF(self.rect()).adjusted(11, 11, -11, -11)
        low, high = self._note_range or self._span_for(None)
        label_w = min(46.0, area.width() * 0.09)
        grid = area.adjusted(label_w, 0, 0, 0)
        return (area, grid, grid.width() / float(self._steps),
                grid.height() / float(high - low + 1), low)

    def note_at(self, x: float, y: float) -> tuple[int, int] | None:
        """La case d'un synthé sous un point : ``(note, pas)``."""
        if self._pattern is not None or self._clip_id is None:
            return None
        _area, grid, cell_w, row_h, low = self._note_geometry()
        if not grid.contains(QPointF(x, y)) or cell_w <= 0 or row_h <= 0:
            return None
        col = int((x - grid.left()) // cell_w)
        note = low + int((grid.bottom() - y) // row_h)
        if not 0 <= col < self._steps:
            return None
        return note, col

    def note_center(self, note: int, step: int) -> QPointF:
        """Le centre de la case ``(note, step)`` — pour viser un clic."""
        _area, grid, cell_w, row_h, low = self._note_geometry()
        return QPointF(grid.left() + (int(step) + 0.5) * cell_w,
                       grid.bottom() - (int(note) - low + 0.5) * row_h)

    def rows(self) -> list[str]:
        """Les rangées d'une batterie, du bas vers le haut."""
        return list(self._rows)

    def _drum_geometry(self) -> tuple[QRectF, QRectF, float, float]:
        """``(zone, grille, largeur d'une case, hauteur d'une rangée)``."""
        area = QRectF(self.rect()).adjusted(11, 11, -11, -11)
        label_w = min(86.0, area.width() * 0.16)
        grid = area.adjusted(label_w, 0, 0, 0)
        rows = max(1, len(self._rows))
        return (area, grid, grid.width() / float(self._steps),
                grid.height() / float(rows))

    def cell_at(self, x: float, y: float) -> tuple[str, int] | None:
        """La case d'une batterie sous un point : ``(rangée, pas)``."""
        if self._pattern is None or not self._rows:
            return None
        _area, grid, cell_w, cell_h = self._drum_geometry()
        if not grid.contains(QPointF(x, y)) or cell_w <= 0 or cell_h <= 0:
            return None
        col = int((x - grid.left()) // cell_w)
        index = int((grid.bottom() - y) // cell_h)
        if not (0 <= col < self._steps and 0 <= index < len(self._rows)):
            return None
        return self._rows[index], col

    def cell_center(self, row: str, step: int) -> QPointF:
        """Le centre de la case ``(row, step)`` — pour viser un clic."""
        _area, grid, cell_w, cell_h = self._drum_geometry()
        index = self._rows.index(row)
        return QPointF(grid.left() + (int(step) + 0.5) * cell_w,
                       grid.bottom() - (index + 0.5) * cell_h)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - API Qt
        if not self._editable:
            return
        x, y = event.position().x(), event.position().y()
        case = self.cell_at(x, y) if self._pattern is not None \
            else self.note_at(x, y)
        if case != self._hover:
            self._hover = case
            self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802 - API Qt
        if self._hover is not None:
            self._hover = None
            self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - API Qt
        if self._editable and event.button() == Qt.MouseButton.LeftButton:
            x, y = event.position().x(), event.position().y()
            if self._pattern is not None:
                case = self.cell_at(x, y)
                if case is not None:
                    self.hitToggled.emit(case[0], case[1])
            else:
                case = self.note_at(x, y)
                if case is not None:
                    self.noteToggled.emit(case[0], case[1])
        super().mouseReleaseEvent(event)

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
            if self.is_empty() and not self._editable:
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
                if self._hover == (name, col):
                    p.setPen(QPen(QColor(GOLD), 1.6))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawRoundedRect(rect, pad * 0.22, pad * 0.22)
        self._paint_playhead(p, grid, cell_w)

    def _paint_notes(self, p: QPainter, area: QRectF) -> None:
        low, high = self._note_range or self._span_for(None)
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
        if self._editable:
            # Un trait par demi-ton : de quoi viser une hauteur à la souris.
            p.setPen(QPen(QColor(mix(PANEL_LO, GREY, 0.25)), 1))
            for note in range(low + 1, high + 1):
                y = grid.bottom() - (note - low) * row_h
                p.drawLine(QPointF(grid.left(), y), QPointF(grid.right(), y))
        if self._editable and self._hover is not None \
                and isinstance(self._hover[0], int):
            note, col = self._hover
            top = grid.bottom() - (int(note) - low + 1) * row_h
            p.setPen(QPen(QColor(GOLD), 1.4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(grid.left() + col * cell_w + 1, top + 1,
                                     max(3.0, cell_w - 2),
                                     max(3.0, row_h - 2)), 3, 3)
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
