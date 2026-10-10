# -*- coding: utf-8 -*-
"""Grilles de pads, à la façade du Deluge.

Trois usages, du plus simple au plus interactif :

* :class:`PadGrid` — la grille nue, qui affiche une matrice de couleurs ;
* :class:`SongPreview` — la vignette 18×8 d'un morceau, telle que la machine
  l'enregistre dans son attribut ``preview`` ;
* :class:`StepSequencer` — l'éditeur de motif rythmique, où chaque colonne est
  un pas et chaque rangée une percussion.

Tout est tracé au :class:`QPainter` dans un seul widget, et non avec un widget
par pad : une grille 16×8 en ferait 128, et l'éditeur de motif sur quatre
mesures en demanderait 512.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from ..theme import GOLD, PAD_DIM, PAD_OFF, pad_color

log = logging.getLogger(__name__)

#: Dimensions de la façade du Deluge : 16 pads jouables plus 2 de barre
#: latérale, sur 8 rangées.
DELUGE_COLS = 16
DELUGE_SIDEBAR = 2
DELUGE_ROWS = 8

#: Proportion de l'espace entre deux pads, relative à leur taille.
GAP_RATIO = 0.14


class PadGrid(QWidget):
    """Grille de pads colorés, cliquable.

    ``set_colors`` accepte une matrice ``[rangée][colonne]`` de couleurs
    hexadécimales ; une valeur vide ou ``None`` laisse le pad éteint.
    L'origine est **en haut à gauche**, comme un tableau — et non en bas à
    gauche comme sur la machine : la conversion est faite par les classes
    qui lisent les données du Deluge.
    """

    padClicked = pyqtSignal(int, int)
    padHovered = pyqtSignal(int, int)

    def __init__(self, cols: int = DELUGE_COLS, rows: int = DELUGE_ROWS,
                 parent: QWidget | None = None, interactive: bool = True,
                 min_pad: int = 10) -> None:
        super().__init__(parent)
        self._cols = max(1, int(cols))
        self._rows = max(1, int(rows))
        self._colors: list[list[str]] = [[""] * self._cols
                                         for _ in range(self._rows)]
        self._playhead: int | None = None
        self._hover: tuple[int, int] | None = None
        self._min_pad = max(4, int(min_pad))
        self._radius_ratio = 0.22
        self._sidebar_at: int | None = None

        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)
        if interactive:
            self.setMouseTracking(True)
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._interactive = bool(interactive)

    # -- géométrie --------------------------------------------------------- #

    def set_grid(self, cols: int, rows: int) -> None:
        """Change les dimensions, en effaçant le contenu."""
        self._cols = max(1, int(cols))
        self._rows = max(1, int(rows))
        self._colors = [[""] * self._cols for _ in range(self._rows)]
        self._playhead = None
        self.updateGeometry()
        self.update()

    def grid_size(self) -> tuple[int, int]:
        return self._cols, self._rows

    def set_sidebar_column(self, col: int | None) -> None:
        """Marque la colonne à partir de laquelle commence la barre latérale.

        Les pads de la barre latérale du Deluge sont séparés des pads
        jouables par un intervalle plus large ; c'est ce qui rend la vignette
        d'un morceau reconnaissable.
        """
        self._sidebar_at = None if col is None else max(0, int(col))
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802 - API Qt
        pad = max(self._min_pad, 18)
        gap = max(1, int(pad * GAP_RATIO))
        return QSize(self._cols * (pad + gap) + gap,
                     self._rows * (pad + gap) + gap)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - API Qt
        pad = self._min_pad
        gap = max(1, int(pad * GAP_RATIO))
        return QSize(self._cols * (pad + gap) + gap,
                     self._rows * (pad + gap) + gap)

    def _metrics(self) -> tuple[float, float, float, float]:
        """``(taille du pad, intervalle, décalage x, décalage y)``."""
        extra = 1 if self._sidebar_at is not None else 0
        width = max(1, self.width())
        height = max(1, self.height())
        # On cherche la plus grande taille de pad qui tienne dans les deux sens.
        by_width = width / (self._cols * (1.0 + GAP_RATIO) + GAP_RATIO
                            + extra * GAP_RATIO * 2)
        by_height = height / (self._rows * (1.0 + GAP_RATIO) + GAP_RATIO)
        pad = max(2.0, min(by_width, by_height))
        gap = pad * GAP_RATIO
        used_w = self._cols * (pad + gap) + gap + extra * gap * 2
        used_h = self._rows * (pad + gap) + gap
        return pad, gap, (width - used_w) / 2.0, (height - used_h) / 2.0

    def _cell_rect(self, x: int, y: int) -> QRectF:
        pad, gap, off_x, off_y = self._metrics()
        extra = (gap * 2 if (self._sidebar_at is not None
                             and x >= self._sidebar_at) else 0.0)
        return QRectF(off_x + gap + x * (pad + gap) + extra,
                      off_y + gap + y * (pad + gap), pad, pad)

    def _cell_at(self, px: float, py: float) -> tuple[int, int] | None:
        """Pad situé sous un point, ou ``None``.

        Calculé par division, et non en parcourant la grille : un éditeur de
        motif sur quatre mesures compte 768 pads, et les survoler tous à
        chaque mouvement de souris se verrait.
        """
        pad, gap, off_x, off_y = self._metrics()
        step = pad + gap
        if step <= 0:
            return None

        y = int((py - off_y - gap) // step)
        if not 0 <= y < self._rows:
            return None

        local_x = px - off_x - gap
        x = int(local_x // step)
        # La barre latérale est décalée d'un intervalle supplémentaire : on
        # retire ce décalage avant de diviser si l'on est au-delà.
        if self._sidebar_at is not None and x >= self._sidebar_at:
            x = int((local_x - gap * 2) // step)
        if not 0 <= x < self._cols:
            return None

        # On vérifie que le point est bien sur le pad et non dans l'intervalle.
        if not self._cell_rect(x, y).adjusted(-1, -1, 1, 1).contains(px, py):
            return None
        return x, y

    # -- contenu ----------------------------------------------------------- #

    def set_colors(self, matrix) -> None:
        """Remplace toute la matrice de couleurs.

        Les dimensions sont ajustées si la matrice ne correspond pas, pour
        qu'un appel avec des données inattendues ne lève pas.
        """
        try:
            rows = [list(row) for row in matrix]
        except TypeError:
            log.debug("matrice de pads illisible")
            return
        if not rows:
            return
        height = len(rows)
        width = max(len(row) for row in rows)
        if (width, height) != (self._cols, self._rows):
            self._cols, self._rows = max(1, width), max(1, height)
        self._colors = [
            [str(rows[y][x]) if x < len(rows[y]) and rows[y][x] else ""
             for x in range(self._cols)]
            for y in range(self._rows)
        ]
        self.updateGeometry()
        self.update()

    def set_cell(self, x: int, y: int, color: str) -> None:
        """Change la couleur d'un seul pad."""
        if 0 <= y < self._rows and 0 <= x < self._cols:
            self._colors[y][x] = str(color or "")
            self.update(self._cell_rect(x, y).toRect().adjusted(-2, -2, 2, 2))

    def cell(self, x: int, y: int) -> str:
        if 0 <= y < self._rows and 0 <= x < self._cols:
            return self._colors[y][x]
        return ""

    def clear(self) -> None:
        """Éteint tous les pads."""
        self._colors = [[""] * self._cols for _ in range(self._rows)]
        self.update()

    def set_playhead(self, col: int | None) -> None:
        """Place le curseur de lecture sur une colonne, ou le retire."""
        new = None if col is None else int(col)
        if new != self._playhead:
            self._playhead = new
            self.update()

    # -- interaction -------------------------------------------------------- #

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - API Qt
        if self._interactive and event.button() == Qt.MouseButton.LeftButton:
            cell = self._cell_at(event.position().x(), event.position().y())
            if cell is not None:
                self.padClicked.emit(cell[0], cell[1])
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - API Qt
        if not self._interactive:
            return
        cell = self._cell_at(event.position().x(), event.position().y())
        if cell != self._hover:
            self._hover = cell
            if cell is not None:
                self.padHovered.emit(cell[0], cell[1])
            self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802 - API Qt
        if self._hover is not None:
            self._hover = None
            self.update()
        super().leaveEvent(event)

    # -- tracé -------------------------------------------------------------- #

    def paintEvent(self, event) -> None:  # noqa: N802 - API Qt
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            pad, _gap, _ox, _oy = self._metrics()
            radius = pad * self._radius_ratio

            for y in range(self._rows):
                for x in range(self._cols):
                    rect = self._cell_rect(x, y)
                    colour = self._colors[y][x]
                    if colour and colour != "#000000":
                        base = QColor(colour)
                    else:
                        base = QColor(PAD_OFF)

                    if self._playhead is not None and x == self._playhead:
                        # Colonne lue : on éclaircit sans changer la teinte.
                        base = base.lighter(150)

                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(base)
                    painter.drawRoundedRect(rect, radius, radius)

                    if self._hover == (x, y):
                        pen = QPen(QColor(GOLD))
                        pen.setWidthF(max(1.0, pad * 0.09))
                        painter.setPen(pen)
                        painter.setBrush(Qt.BrushStyle.NoBrush)
                        painter.drawRoundedRect(rect, radius, radius)
            painter.end()
        except Exception as exc:  # noqa: BLE001 - un tracé ne doit rien casser
            log.debug("tracé de la grille impossible : %s", exc)


class SongPreview(PadGrid):
    """Vignette d'un morceau : la matrice 18×8 que le Deluge enregistre.

    Les deux dernières colonnes sont la barre latérale de la machine ; elles
    sont donc détachées visuellement.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(DELUGE_COLS + DELUGE_SIDEBAR, DELUGE_ROWS, parent,
                        interactive=False, min_pad=6)
        self.set_sidebar_column(DELUGE_COLS)

    def set_song(self, song) -> None:
        """Affiche la vignette d'un :class:`~delugeapp.core.model.Song`."""
        try:
            self.set_colors(song.preview_colors())
        except Exception as exc:  # noqa: BLE001
            log.debug("vignette de morceau illisible : %s", exc)
            self.clear()


class StepSequencer(PadGrid):
    """Éditeur de motif rythmique : une rangée par piste, une colonne par pas.

    Cliquer un pad ajoute ou retire un coup. Le motif modifié est émis par
    :attr:`patternChanged`, prêt à être converti en notes de clip par
    ``Pattern.to_notes``.
    """

    patternChanged = pyqtSignal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(16, 4, parent, interactive=True, min_pad=12)
        self._pattern = None
        self._tracks: list[str] = []
        self.padClicked.connect(self._toggle)

    def pattern(self):
        """Motif en cours d'édition."""
        return self._pattern

    def tracks(self) -> list[str]:
        """Noms des pistes, dans l'ordre d'affichage."""
        return list(self._tracks)

    def set_pattern(self, pattern) -> None:
        """Charge un :class:`~delugeapp.core.rhythm.Pattern`."""
        self._pattern = pattern
        if pattern is None:
            self._tracks = []
            self.set_grid(16, 4)
            return
        self._tracks = list(pattern.tracks)
        self.set_grid(max(1, int(pattern.steps)), max(1, len(self._tracks)))
        self._refresh()

    def _refresh(self) -> None:
        """Recolorie la grille d'après le motif."""
        if self._pattern is None:
            return
        matrix = [[""] * self._cols for _ in range(self._rows)]
        for y, track in enumerate(self._tracks):
            colour = pad_color(y)
            for step in self._pattern.tracks.get(track, ()):
                x = int(round(float(step.pos)))
                if not 0 <= x < self._cols:
                    continue
                if step.probability < 100:
                    # Un coup probabiliste est affiché en demi-teinte.
                    matrix[y][x] = QColor(colour).darker(170).name()
                elif step.velocity >= 90:
                    matrix[y][x] = colour
                else:
                    matrix[y][x] = QColor(colour).darker(135).name()
        self.set_colors(matrix)

    def _toggle(self, x: int, y: int) -> None:
        """Ajoute ou retire un coup au pad cliqué."""
        if self._pattern is None or not 0 <= y < len(self._tracks):
            return
        from ...core.rhythm import Step

        track = self._tracks[y]
        steps = self._pattern.tracks.setdefault(track, [])
        existing = [s for s in steps if int(round(float(s.pos))) == x]
        if existing:
            for step in existing:
                steps.remove(step)
        else:
            steps.append(Step(pos=x, velocity=100))
            steps.sort(key=lambda s: s.pos)
        self._refresh()
        try:
            self.patternChanged.emit(self._pattern)
        except Exception:  # noqa: BLE001 - un abonné ne doit rien casser
            log.exception("abonné à patternChanged en échec")

    def paintEvent(self, event) -> None:  # noqa: N802 - API Qt
        super().paintEvent(event)
        # Repères de temps : un trait plus clair tous les quatre pas, qui
        # rend la pulsation lisible.
        try:
            if self._cols < 8:
                return
            painter = QPainter(self)
            pad, gap, _ox, _oy = self._metrics()
            pen = QPen(QColor(PAD_DIM))
            pen.setWidthF(1.0)
            painter.setPen(pen)
            for x in range(4, self._cols, 4):
                rect = self._cell_rect(x, 0)
                top = self._cell_rect(x, 0).top() - gap * 0.5
                bottom = self._cell_rect(x, self._rows - 1).bottom() + gap * 0.5
                line_x = rect.left() - gap * 0.5
                painter.drawLine(int(line_x), int(top), int(line_x), int(bottom))
            painter.end()
        except Exception as exc:  # noqa: BLE001
            log.debug("tracé des repères impossible : %s", exc)
