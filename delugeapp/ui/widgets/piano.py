# -*- coding: utf-8 -*-
"""Clavier de piano, pour écouter et pour montrer une gamme ou un accord.

Sert à deux choses dans l'application : jouer un preset à la souris, et
**voir** ce que proposent les outils de théorie — les notes d'une gamme, d'un
accord ou d'une progression sont surlignées sur le clavier, ce qui est plus
parlant qu'une liste de noms.

Les touches noires sont dessinées par-dessus les blanches et testées en
premier au clic, comme sur un vrai clavier : sans cela, cliquer un dièse
déclencherait la touche blanche située dessous.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from ..theme import GOLD, GREY, INK, PAD_WHITE, PANEL_HI, PANEL_LO, mix

log = logging.getLogger(__name__)

#: Demi-tons des touches noires dans une octave.
BLACK_SEMITONES = (1, 3, 6, 8, 10)

#: Largeur d'une touche noire, en fraction d'une touche blanche.
BLACK_WIDTH_RATIO = 0.62

#: Hauteur d'une touche noire, en fraction de la hauteur totale.
BLACK_HEIGHT_RATIO = 0.62


class PianoKeys(QWidget):
    """Clavier de trois octaves par défaut."""

    noteOn = pyqtSignal(int)
    noteOff = pyqtSignal(int)

    def __init__(self, lo: int = 48, hi: int = 84,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._lo = int(lo)
        self._hi = max(int(hi), self._lo + 11)
        self._highlight: dict[int, str] = {}
        self._pressed: int | None = None
        self._hover: int | None = None

        self.setMinimumHeight(56)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Preferred)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # -- étendue et surlignage --------------------------------------------- #

    def set_range(self, lo: int, hi: int) -> None:
        """Change l'étendue du clavier, en notes MIDI."""
        self._lo = max(0, int(lo))
        self._hi = max(int(hi), self._lo + 11)
        self.update()

    def range(self) -> tuple[int, int]:
        return self._lo, self._hi

    def set_highlight(self, notes, color: str = GOLD) -> None:
        """Surligne un ensemble de notes, en remplaçant le surlignage précédent.

        Les notes sont surlignées **à toutes les octaves** du clavier : une
        gamme s'affiche ainsi en entier, ce qui est le but.
        """
        self._highlight = {}
        self.add_highlight(notes, color)

    def add_highlight(self, notes, color: str = GOLD) -> None:
        """Ajoute des notes au surlignage, sans effacer l'existant."""
        try:
            wanted = {int(n) % 12 for n in (notes or [])}
        except (TypeError, ValueError):
            log.debug("liste de notes à surligner illisible")
            return
        for note in range(self._lo, self._hi + 1):
            if note % 12 in wanted:
                self._highlight[note] = color
        self.update()

    def set_exact_highlight(self, notes, color: str = GOLD) -> None:
        """Surligne exactement ces notes, sans les reporter aux autres octaves.

        C'est ce qu'il faut pour montrer un accord dans son renversement :
        reporter les notes à toutes les octaves effacerait justement
        l'information de voicing.
        """
        self._highlight = {}
        try:
            for note in (notes or []):
                self._highlight[int(note)] = color
        except (TypeError, ValueError):
            log.debug("liste de notes à surligner illisible")
        self.update()

    def clear_highlight(self) -> None:
        self._highlight = {}
        self.update()

    # -- géométrie --------------------------------------------------------- #

    def sizeHint(self) -> QSize:  # noqa: N802 - API Qt
        return QSize(max(240, self._white_count() * 14), 72)

    def _white_notes(self) -> list[int]:
        return [n for n in range(self._lo, self._hi + 1)
                if n % 12 not in BLACK_SEMITONES]

    def _white_count(self) -> int:
        return max(1, len(self._white_notes()))

    def _white_width(self) -> float:
        return max(4.0, self.width() / float(self._white_count()))

    def _white_rect(self, index: int) -> QRectF:
        width = self._white_width()
        return QRectF(index * width, 0.0, width - 1.0, float(self.height()))

    def _black_rect(self, note: int) -> QRectF | None:
        """Rectangle d'une touche noire, placée entre ses deux blanches."""
        whites = self._white_notes()
        # La blanche qui précède immédiatement cette noire.
        below = [i for i, w in enumerate(whites) if w < note]
        if not below:
            return None
        index = below[-1]
        width = self._white_width()
        black_w = width * BLACK_WIDTH_RATIO
        return QRectF((index + 1) * width - black_w / 2.0, 0.0, black_w,
                      self.height() * BLACK_HEIGHT_RATIO)

    def _note_at(self, x: float, y: float) -> int | None:
        """Note sous le pointeur, les noires étant testées d'abord."""
        for note in range(self._lo, self._hi + 1):
            if note % 12 not in BLACK_SEMITONES:
                continue
            rect = self._black_rect(note)
            if rect is not None and rect.contains(x, y):
                return note
        for index, note in enumerate(self._white_notes()):
            if self._white_rect(index).contains(x, y):
                return note
        return None

    # -- interaction -------------------------------------------------------- #

    def mousePressEvent(self, event) -> None:  # noqa: N802 - API Qt
        if event.button() != Qt.MouseButton.LeftButton:
            return
        note = self._note_at(event.position().x(), event.position().y())
        if note is None:
            return
        self._pressed = note
        self.update()
        try:
            self.noteOn.emit(int(note))
        except Exception:  # noqa: BLE001 - un abonné ne doit rien casser
            log.exception("abonné à noteOn en échec")

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - API Qt
        note = self._note_at(event.position().x(), event.position().y())
        if note != self._hover:
            self._hover = note
            self.update()
        # Glisser d'une touche à l'autre : on enchaîne les notes, comme un
        # glissando au doigt.
        if self._pressed is not None and note is not None \
                and note != self._pressed:
            self._release()
            self._pressed = note
            try:
                self.noteOn.emit(int(note))
            except Exception:  # noqa: BLE001
                log.exception("abonné à noteOn en échec")
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - API Qt
        self._release()
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802 - API Qt
        self._hover = None
        self._release()
        self.update()
        super().leaveEvent(event)

    def _release(self) -> None:
        if self._pressed is None:
            return
        note, self._pressed = self._pressed, None
        try:
            self.noteOff.emit(int(note))
        except Exception:  # noqa: BLE001
            log.exception("abonné à noteOff en échec")

    # -- tracé -------------------------------------------------------------- #

    def paintEvent(self, event) -> None:  # noqa: N802 - API Qt
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            self._draw_white(painter)
            self._draw_black(painter)
            painter.end()
        except Exception as exc:  # noqa: BLE001 - un tracé ne doit rien casser
            log.debug("tracé du clavier impossible : %s", exc)

    def _draw_white(self, painter: QPainter) -> None:
        from ..theme import FONT_UI

        whites = self._white_notes()
        for index, note in enumerate(whites):
            rect = self._white_rect(index)
            colour = QColor(PAD_WHITE)
            if note == self._pressed:
                colour = QColor(GOLD)
            elif note in self._highlight:
                colour = QColor(mix(self._highlight[note], PAD_WHITE, 0.45))
            elif note == self._hover:
                colour = QColor(mix(PAD_WHITE, GOLD, 0.12))

            painter.setPen(QPen(QColor(PANEL_HI), 1))
            painter.setBrush(colour)
            painter.drawRect(rect)

            # Repère d'octave sur chaque do.
            if note % 12 == 0 and rect.width() > 14:
                painter.setPen(QPen(QColor(GREY)))
                font = painter.font()
                font.setPointSize(7)
                painter.setFont(font)
                painter.drawText(
                    QRectF(rect.left(), rect.bottom() - 14, rect.width(), 13),
                    Qt.AlignmentFlag.AlignCenter,
                    f"Do{note // 12 - 2}")

    def _draw_black(self, painter: QPainter) -> None:
        for note in range(self._lo, self._hi + 1):
            if note % 12 not in BLACK_SEMITONES:
                continue
            rect = self._black_rect(note)
            if rect is None:
                continue
            colour = QColor(INK)
            if note == self._pressed:
                colour = QColor(GOLD).darker(130)
            elif note in self._highlight:
                colour = QColor(mix(self._highlight[note], INK, 0.55))
            elif note == self._hover:
                colour = QColor(mix(INK, GOLD, 0.25))

            painter.setPen(QPen(QColor(PANEL_LO), 1))
            painter.setBrush(colour)
            painter.drawRect(rect)
