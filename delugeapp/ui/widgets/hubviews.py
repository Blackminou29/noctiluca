# -*- coding: utf-8 -*-
"""La baie de brassage du hub MIDI, dessinée comme une grille de pads.

Les **sources** en rangées — claviers, surfaces de contrôle, le Deluge, les
ports venus du DAW —, les **destinations** en colonnes. Un pad allumé au
croisement : ce que joue la source part vers la destination. Un clic sur un
pad éteint branche, un clic sur un pad allumé le choisit pour le régler.

Le widget ne sait rien du MIDI : la page lui donne les ports
(:meth:`PatchMatrix.set_ports`), l'état de chaque croisement
(:meth:`PatchMatrix.set_cells`) et ce qui vient de passer
(:meth:`PatchMatrix.pulse`).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from PyQt6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PyQt6.QtWidgets import QSizePolicy, QToolTip, QWidget

from ...i18n import tr
from .. import art
from ..theme import (BORDER, GOLD, GREY, PAD_AMBER, PAD_CYAN, PAD_PINK,
                     PAD_PURPLE, PAD_RED, PAD_WHITE, PANEL_LO, TEXT_MUTED,
                     TEXT_SOFT, mix, text_on)

log = logging.getLogger(__name__)

__all__ = ["PatchCell", "PatchMatrix", "ROLE_COLORS", "role_color"]

#: La couleur de chaque sorte de port : l'or de la façade pour le Deluge,
#: le rose de la page DAW pour un port virtuel, le violet des presets pour
#: le synthé de Windows, le cyan pour un clavier ou une surface.
ROLE_COLORS = {"deluge": GOLD, "virtual": PAD_PINK, "synth": PAD_PURPLE,
               "device": PAD_CYAN}

#: Durée pendant laquelle un passage reste visible, en secondes.
ECLAT = 0.35


def role_color(role: str) -> str:
    return ROLE_COLORS.get(str(role or ""), PAD_CYAN)


@dataclass(frozen=True)
class PatchCell:
    """Un croisement branché : son état, sa marque, son infobulle.

    ``state`` : ``active``, ``off`` (coupé), ``waiting`` (il attend un
    appareil, un réglage ou le hub) ou ``tripped`` (coupé pour emballement).
    ``tag`` : ce que le pad affiche — « A », « P2 », « 10 », « = ».
    """

    state: str = "active"
    tag: str = ""
    tip: str = ""


class PatchMatrix(QWidget):
    """Sources en rangées, destinations en colonnes, un pad par croisement."""

    #: Un clic sur un croisement : source, destination.
    cellClicked = pyqtSignal(str, str)
    #: Un clic droit sur un croisement branché : source, destination, point.
    cellMenuRequested = pyqtSignal(str, str, object)

    LABEL_W = 226
    HEAD_H = 62
    ROW_H = 46
    COL_W = 132

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._sources: list = []
        self._dests: list = []
        self._cells: dict[tuple[str, str], PatchCell] = {}
        self._selected: tuple[str, str] | None = None
        self._hover: tuple[int, int] | None = None
        self._accent = GOLD
        #: Instant du dernier passage, par source, destination, croisement.
        self._eclats: dict = {}
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Fixed)

    # -- données ------------------------------------------------------------ #

    def set_accent(self, color: str) -> None:
        """La couleur des pads allumés : celle de la page."""
        self._accent = str(color or GOLD)
        self.update()

    def set_ports(self, sources, dests) -> None:
        """Les ports (:class:`delugeapp.core.midihub.Endpoint`)."""
        self._sources = list(sources)
        self._dests = list(dests)
        self.updateGeometry()
        self.update()

    def set_cells(self, cells: dict) -> None:
        """``{(source, destination): PatchCell}`` pour chaque branchement."""
        self._cells = dict(cells)
        self.update()

    def set_selected(self, source: str = "", dest: str = "") -> None:
        nouveau = (source, dest) if source and dest else None
        if nouveau != self._selected:
            self._selected = nouveau
            self.update()

    def selected(self) -> tuple[str, str] | None:
        return self._selected

    def sources(self) -> list[str]:
        return [b.name for b in self._sources]

    def destinations(self) -> list[str]:
        return [b.name for b in self._dests]

    def pulse(self, sources=(), dests=(), cells=()) -> None:
        """Ce qui vient de passer : ces ports et ces croisements brillent un
        instant."""
        maintenant = time.monotonic()
        for nom in sources:
            self._eclats[("s", nom)] = maintenant
        for nom in dests:
            self._eclats[("d", nom)] = maintenant
        for cle in cells:
            self._eclats[("c",) + tuple(cle)] = maintenant
        self.update()

    def fading(self) -> bool:
        """Vrai tant qu'un éclat n'est pas retombé : la page redessine."""
        limite = time.monotonic() - ECLAT
        self._eclats = {c: t for c, t in self._eclats.items() if t > limite}
        return bool(self._eclats)

    def _eclat(self, *cle) -> float:
        instant = self._eclats.get(cle)
        if instant is None:
            return 0.0
        return max(0.0, 1.0 - (time.monotonic() - instant) / ECLAT)

    # -- géométrie ---------------------------------------------------------- #

    def sizeHint(self) -> QSize:  # noqa: N802 - API Qt
        cols = max(1, len(self._dests))
        rows = max(1, len(self._sources))
        return QSize(self.LABEL_W + cols * self.COL_W + 8,
                     self.HEAD_H + rows * self.ROW_H + 8)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - API Qt
        return self.sizeHint()

    def _cell_rect(self, col: int, row: int) -> QRectF:
        return QRectF(self.LABEL_W + col * self.COL_W + 10,
                      self.HEAD_H + row * self.ROW_H + 5,
                      self.COL_W - 20, self.ROW_H - 10)

    def cell_center(self, source: str, dest: str) -> QPointF:
        """Le centre du croisement — pour viser un clic."""
        row, col = self.sources().index(source), \
            self.destinations().index(dest)
        return self._cell_rect(col, row).center()

    def _hit(self, x: float, y: float) -> tuple[int, int] | None:
        if x < self.LABEL_W or y < self.HEAD_H:
            return None
        col = int((x - self.LABEL_W) // self.COL_W)
        row = int((y - self.HEAD_H) // self.ROW_H)
        if 0 <= col < len(self._dests) and 0 <= row < len(self._sources):
            return col, row
        return None

    def _noms(self, hit: tuple[int, int]) -> tuple[str, str]:
        col, row = hit
        return self._sources[row].name, self._dests[col].name

    @staticmethod
    def forbidden(source: str, dest: str) -> bool:
        """Un appareil ne se branche pas sur lui-même."""
        return source == dest

    # -- souris ------------------------------------------------------------- #

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
        hit = self._hit(event.position().x(), event.position().y())
        if hit is None:
            return
        source, dest = self._noms(hit)
        if self.forbidden(source, dest):
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.cellClicked.emit(source, dest)
        elif event.button() == Qt.MouseButton.RightButton \
                and (source, dest) in self._cells:
            self.cellMenuRequested.emit(source, dest,
                                        event.globalPosition().toPoint())

    def tip_at(self, x: float, y: float) -> str:
        """Ce que dit le croisement sous la souris."""
        hit = self._hit(x, y)
        if hit is None:
            return ""
        source, dest = self._noms(hit)
        if self.forbidden(source, dest):
            return tr("Un appareil ne se branche pas sur lui-même")
        cellule = self._cells.get((source, dest))
        if cellule is not None:
            return cellule.tip
        return tr("Cliquer pour brancher « %s » sur « %s »") % (
            self._sources[hit[1]].label, self._dests[hit[0]].label)

    def event(self, event) -> bool:  # noqa: A003 - API Qt
        if event.type() == QEvent.Type.ToolTip:
            texte = self.tip_at(event.pos().x(), event.pos().y())
            if texte:
                QToolTip.showText(event.globalPos(), texte, self)
            else:
                QToolTip.hideText()
            return True
        return super().event(event)

    # -- dessin ------------------------------------------------------------- #

    def _led(self, p: QPainter, centre: QPointF, bout, eclat: float) -> None:
        """La diode d'un port : à sa couleur s'il est là, vive s'il est
        ouvert, blanche l'instant d'un passage, rouge s'il est coupé."""
        couleur = role_color(bout.role)
        if bout.tripped:
            couleur = PAD_RED
        if not bout.present:
            p.setPen(QPen(QColor(TEXT_MUTED), 1.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(centre, 4.5, 4.5)
            return
        if bout.open or bout.tripped:
            art.paint_glow(p, QRectF(centre.x() - 5, centre.y() - 5, 10, 10),
                           couleur, 0.30 + 0.5 * eclat, 0.9)
        p.setPen(Qt.PenStyle.NoPen)
        teinte = mix(couleur, "#FFFFFF", 0.75 * eclat) if eclat else (
            couleur if bout.open or bout.tripped
            else mix(PANEL_LO, couleur, 0.45))
        p.setBrush(QColor(teinte))
        p.drawEllipse(centre, 5.0, 5.0)

    @staticmethod
    def _sous_titre(bout) -> str:
        if bout.tripped:
            return tr("coupé : boucle probable")
        if not bout.present:
            return tr("débranché")
        return {"deluge": tr("la machine"),
                "virtual": tr("port virtuel — le DAW"),
                "synth": tr("pour essayer sans appareil"),
                }.get(bout.role, tr("clavier ou surface"))

    def paintEvent(self, event) -> None:  # noqa: N802 - API Qt
        try:
            self._paint()
        except Exception as exc:     # noqa: BLE001 - un décor ne casse rien
            log.debug("baie de brassage non tracée : %s", exc)

    def _paint(self) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        base = QFont(self.font())
        bold = QFont(base)
        bold.setBold(True)
        petit = QFont(base)
        petit.setPointSizeF(max(6.5, base.pointSizeF() - 1.5))
        accent = self._accent

        # Le coin : de quel côté on lit.
        p.setFont(petit)
        p.setPen(QColor(TEXT_MUTED))
        p.drawText(QRectF(8, self.HEAD_H - 20, self.LABEL_W - 16, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   tr("CE QUI ARRIVE DE…"))
        p.drawText(QRectF(8, 4, self.LABEL_W - 16, 16),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   tr("…PART VERS"))

        # Les destinations, en tête de colonne.
        for col, bout in enumerate(self._dests):
            left = self.LABEL_W + col * self.COL_W
            tete = QRectF(left + 4, 4, self.COL_W - 8, self.HEAD_H - 10)
            survol = self._hover is not None and self._hover[0] == col
            p.setPen(QPen(QColor(mix(BORDER, role_color(bout.role), 0.5)
                                 if survol else BORDER), 1))
            p.setBrush(QColor(PANEL_LO))
            p.drawRoundedRect(tete, 8, 8)
            self._led(p, QPointF(tete.left() + 13, tete.top() + 14), bout,
                      self._eclat("d", bout.name))
            p.setFont(bold)
            p.setPen(QColor(PAD_WHITE if bout.present else TEXT_SOFT))
            p.drawText(QRectF(tete.left() + 24, tete.top() + 3,
                              tete.width() - 30, 22),
                       Qt.AlignmentFlag.AlignLeft
                       | Qt.AlignmentFlag.AlignVCenter,
                       QFontMetricsF(bold).elidedText(
                           bout.label, Qt.TextElideMode.ElideRight,
                           tete.width() - 30))
            p.setFont(petit)
            p.setPen(QColor(TEXT_SOFT))
            p.drawText(QRectF(tete.left() + 8, tete.top() + 26,
                              tete.width() - 14, 20),
                       Qt.AlignmentFlag.AlignLeft
                       | Qt.AlignmentFlag.AlignVCenter,
                       QFontMetricsF(petit).elidedText(
                           self._sous_titre(bout),
                           Qt.TextElideMode.ElideRight, tete.width() - 14))

        # Les sources, en tête de rangée, puis leurs croisements.
        for row, bout in enumerate(self._sources):
            top = self.HEAD_H + row * self.ROW_H
            if row % 2 == 0:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(mix(PANEL_LO, "#FFFFFF", 0.025)))
                p.drawRoundedRect(
                    QRectF(2, top + 1, self.LABEL_W
                           + len(self._dests) * self.COL_W, self.ROW_H - 2),
                    8, 8)
            self._led(p, QPointF(16, top + self.ROW_H / 2.0), bout,
                      self._eclat("s", bout.name))
            p.setFont(bold)
            p.setPen(QColor(PAD_WHITE if bout.present else TEXT_SOFT))
            p.drawText(QRectF(30, top + 5, self.LABEL_W - 36, 20),
                       Qt.AlignmentFlag.AlignLeft
                       | Qt.AlignmentFlag.AlignVCenter,
                       QFontMetricsF(bold).elidedText(
                           bout.label, Qt.TextElideMode.ElideRight,
                           self.LABEL_W - 36))
            p.setFont(petit)
            p.setPen(QColor(TEXT_SOFT))
            p.drawText(QRectF(30, top + 24, self.LABEL_W - 36, 16),
                       Qt.AlignmentFlag.AlignLeft
                       | Qt.AlignmentFlag.AlignVCenter,
                       QFontMetricsF(petit).elidedText(
                           self._sous_titre(bout),
                           Qt.TextElideMode.ElideRight, self.LABEL_W - 36))
            for col, cible in enumerate(self._dests):
                self._pad(p, col, row, bout, cible, accent, bold)
        p.end()

    def _pad(self, p: QPainter, col: int, row: int, source, dest,
             accent: str, bold: QFont) -> None:
        rect = self._cell_rect(col, row)
        cle = (source.name, dest.name)
        cellule = self._cells.get(cle)
        survol = self._hover == (col, row)
        if self.forbidden(*cle):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(TEXT_MUTED))
            p.drawEllipse(rect.center(), 2.5, 2.5)
            return
        if cellule is None:
            # Un pad éteint a la teinte du panneau : sans son liseré, une
            # rangée sans branchement paraissait vide (vu sur le rendu).
            art.paint_off_pad(p, rect, diode=False, radius=9)
            p.setPen(QPen(QColor(BORDER), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 9, 9)
            if survol:
                p.setPen(QPen(QColor(accent), 1.6))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(rect, 9, 9)
                p.setFont(bold)
                p.setPen(QColor(accent))
                p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "+")
        else:
            teinte = {"tripped": PAD_RED, "waiting": PAD_AMBER}.get(
                cellule.state, accent)
            if cellule.state in ("active", "tripped"):
                eclat = self._eclat("c", *cle)
                art.paint_pad(p, rect, mix(teinte, "#FFFFFF", 0.55 * eclat),
                              glow=0.22 + 0.35 * eclat, radius=9)
                encre = text_on(teinte)
            else:
                # Coupé ou en attente : le pad garde sa place, en veilleuse.
                art.paint_off_pad(p, rect, diode=False, radius=9)
                trait = QPen(QColor(teinte), 1.4)
                if cellule.state == "waiting":
                    trait.setStyle(Qt.PenStyle.DashLine)
                p.setPen(trait)
                p.setBrush(QColor(mix(PANEL_LO, teinte, 0.14)))
                p.drawRoundedRect(rect.adjusted(0.7, 0.7, -0.7, -0.7), 9, 9)
                encre = mix(teinte, "#FFFFFF", 0.25)
            p.setFont(bold)
            p.setPen(QColor(encre))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter,
                       "!" if cellule.state == "tripped" else cellule.tag)
            if survol:
                p.setPen(QPen(QColor(GREY), 1.2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(rect.adjusted(-2, -2, 2, 2), 10, 10)
        if self._selected == cle:
            p.setPen(QPen(QColor(PAD_WHITE), 2.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect.adjusted(-3, -3, 3, 3), 11, 11)
