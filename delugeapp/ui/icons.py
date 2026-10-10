# -*- coding: utf-8 -*-
"""Icônes de l'application, dessinées à la main.

Aucun fichier externe : tout est tracé au :class:`QPainter`, ce qui garantit
que l'application reste un simple dossier Python et que les icônes suivent la
couleur demandée (survol, sélection, désactivation).

Les pictogrammes sont dessinés dans un carré logique de 100x100 puis mis à
l'échelle, afin que les proportions restent identiques à toutes les tailles.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)

from .theme import GOLD, PAD_CYCLE, PAD_WHITE, PANEL_LO

log = logging.getLogger(__name__)

#: Côté du repère logique de dessin.
_GRID = 100.0

#: Épaisseur de trait par défaut, dans le repère logique.
_STROKE = 8.0

#: Noms d'icônes exigés par la SPEC §5.2.
ICON_NAMES = (
    "dashboard", "samples", "synth", "kit", "song", "wand", "tools", "health",
    "settings", "play", "stop", "search", "refresh", "folder", "save",
    "export", "import", "trash", "star", "tag", "wave", "dice", "copy",
    "link", "warning", "check", "chevron-right", "chevron-down", "plus",
    "minus", "filter", "grid", "list", "info", "backup", "midi",
)


# --------------------------------------------------------------------------- #
# Primitives de dessin
# --------------------------------------------------------------------------- #

def _pen(p: QPainter, color: QColor, width: float = _STROKE,
         cap: Qt.PenCapStyle = Qt.PenCapStyle.RoundCap) -> None:
    """Prépare un stylo arrondi de la couleur demandée."""
    pen = QPen(color)
    pen.setWidthF(width)
    pen.setCapStyle(cap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)


def _fill(p: QPainter, color: QColor) -> None:
    """Passe en mode remplissage sans contour."""
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)


def _poly(points: list[tuple[float, float]]) -> QPolygonF:
    """Polygone à partir d'une liste de couples."""
    return QPolygonF([QPointF(x, y) for x, y in points])


def _rounded(p: QPainter, x: float, y: float, w: float, h: float,
             r: float = 10.0) -> None:
    """Carré arrondi, motif visuel récurrent de l'application."""
    p.drawRoundedRect(QRectF(x, y, w, h), r, r)


def _chevron(p: QPainter, color: QColor, down: bool) -> None:
    """Chevron orienté vers la droite ou vers le bas."""
    _pen(p, color, 10.0)
    if down:
        p.drawPolyline(_poly([(26, 40), (50, 64), (74, 40)]))
    else:
        p.drawPolyline(_poly([(40, 26), (64, 50), (40, 74)]))


# --------------------------------------------------------------------------- #
# Les pictogrammes
# --------------------------------------------------------------------------- #

def _draw_dashboard(p: QPainter, c: QColor) -> None:
    """Quatre tuiles : la vue d'ensemble."""
    _fill(p, c)
    _rounded(p, 16, 16, 30, 30, 7)
    _rounded(p, 54, 16, 30, 30, 7)
    _rounded(p, 16, 54, 30, 30, 7)
    _rounded(p, 54, 54, 30, 30, 7)


def _draw_samples(p: QPainter, c: QColor) -> None:
    """Forme d'onde en barres : les échantillons."""
    _pen(p, c, 9.0)
    for x, h in ((22, 18), (38, 34), (54, 26), (70, 12), (86, 22)):
        p.drawLine(QPointF(x - 8, 50 - h), QPointF(x - 8, 50 + h))


def _draw_synth(p: QPainter, c: QColor) -> None:
    """Onde sinusoïdale dans un cadre : un preset de synthé."""
    _pen(p, c, 7.0)
    _rounded(p, 14, 22, 72, 56, 10)
    path = QPainterPath(QPointF(26, 50))
    path.cubicTo(QPointF(38, 18), QPointF(44, 82), QPointF(56, 50))
    path.cubicTo(QPointF(64, 26), QPointF(70, 64), QPointF(76, 50))
    p.drawPath(path)


def _draw_kit(p: QPainter, c: QColor) -> None:
    """Grille 3x3 de pads : un kit de batterie."""
    _fill(p, c)
    for row in range(3):
        for col in range(3):
            _rounded(p, 16 + col * 25, 16 + row * 25, 18, 18, 4)


def _draw_song(p: QPainter, c: QColor) -> None:
    """Pistes empilées de longueurs différentes : un morceau."""
    _fill(p, c)
    _rounded(p, 14, 20, 52, 16, 5)
    _rounded(p, 14, 42, 72, 16, 5)
    _rounded(p, 14, 64, 38, 16, 5)


def _draw_wand(p: QPainter, c: QColor) -> None:
    """Baguette et étincelles : la génération automatique."""
    _pen(p, c, 9.0)
    p.drawLine(QPointF(30, 74), QPointF(66, 38))
    _pen(p, c, 6.0)
    p.drawLine(QPointF(74, 20), QPointF(74, 34))
    p.drawLine(QPointF(67, 27), QPointF(81, 27))
    p.drawLine(QPointF(24, 30), QPointF(24, 40))
    p.drawLine(QPointF(19, 35), QPointF(29, 35))


def _draw_tools(p: QPainter, c: QColor) -> None:
    """Clé et curseurs : la boîte à outils."""
    _pen(p, c, 8.0)
    p.drawLine(QPointF(22, 30), QPointF(78, 30))
    p.drawLine(QPointF(22, 54), QPointF(78, 54))
    p.drawLine(QPointF(22, 78), QPointF(78, 78))
    _fill(p, c)
    p.drawEllipse(QPointF(38, 30), 9, 9)
    p.drawEllipse(QPointF(62, 54), 9, 9)
    p.drawEllipse(QPointF(46, 78), 9, 9)


def _draw_health(p: QPainter, c: QColor) -> None:
    """Électrocardiogramme : l'état de santé de la carte."""
    _pen(p, c, 8.0)
    p.drawPolyline(_poly([(14, 52), (32, 52), (42, 28), (56, 76),
                          (66, 52), (86, 52)]))


def _draw_settings(p: QPainter, c: QColor) -> None:
    """Roue dentée : les réglages."""
    _pen(p, c, 8.0)
    p.drawEllipse(QPointF(50, 50), 16, 16)
    for i in range(8):
        from math import cos, pi, sin

        a = i * pi / 4.0
        p.drawLine(QPointF(50 + 26 * cos(a), 50 + 26 * sin(a)),
                   QPointF(50 + 36 * cos(a), 50 + 36 * sin(a)))


def _draw_play(p: QPainter, c: QColor) -> None:
    """Triangle de lecture."""
    _fill(p, c)
    p.drawPolygon(_poly([(32, 22), (80, 50), (32, 78)]))


def _draw_stop(p: QPainter, c: QColor) -> None:
    """Carré d'arrêt."""
    _fill(p, c)
    _rounded(p, 28, 28, 44, 44, 6)


def _draw_search(p: QPainter, c: QColor) -> None:
    """Loupe."""
    _pen(p, c, 9.0)
    p.drawEllipse(QPointF(44, 42), 22, 22)
    p.drawLine(QPointF(60, 59), QPointF(80, 79))


def _draw_refresh(p: QPainter, c: QColor) -> None:
    """Flèche circulaire : relancer l'analyse."""
    _pen(p, c, 8.0)
    path = QPainterPath()
    path.arcMoveTo(QRectF(22, 22, 56, 56), 60)
    path.arcTo(QRectF(22, 22, 56, 56), 60, 280)
    p.drawPath(path)
    _fill(p, c)
    p.drawPolygon(_poly([(66, 10), (86, 28), (58, 34)]))


def _draw_folder(p: QPainter, c: QColor) -> None:
    """Dossier."""
    _pen(p, c, 7.0)
    path = QPainterPath(QPointF(16, 76))
    path.lineTo(QPointF(16, 30))
    path.lineTo(QPointF(42, 30))
    path.lineTo(QPointF(50, 40))
    path.lineTo(QPointF(84, 40))
    path.lineTo(QPointF(84, 76))
    path.closeSubpath()
    p.drawPath(path)


def _draw_save(p: QPainter, c: QColor) -> None:
    """Disquette : enregistrer."""
    _pen(p, c, 7.0)
    _rounded(p, 18, 18, 64, 64, 8)
    p.drawRect(QRectF(36, 18, 28, 22))
    p.drawRect(QRectF(32, 56, 36, 26))


def _draw_export(p: QPainter, c: QColor) -> None:
    """Flèche sortante : exporter."""
    _pen(p, c, 8.0)
    p.drawPolyline(_poly([(30, 22), (18, 50), (30, 78)]))
    p.drawLine(QPointF(18, 50), QPointF(82, 50))
    _fill(p, c)
    p.drawPolygon(_poly([(74, 36), (90, 50), (74, 64)]))


def _draw_import(p: QPainter, c: QColor) -> None:
    """Flèche entrante : importer."""
    _pen(p, c, 8.0)
    p.drawLine(QPointF(18, 50), QPointF(74, 50))
    _fill(p, c)
    p.drawPolygon(_poly([(26, 36), (10, 50), (26, 64)]))
    _pen(p, c, 8.0)
    p.drawPolyline(_poly([(70, 22), (82, 50), (70, 78)]))


def _draw_trash(p: QPainter, c: QColor) -> None:
    """Corbeille."""
    _pen(p, c, 7.0)
    p.drawLine(QPointF(20, 30), QPointF(80, 30))
    p.drawLine(QPointF(40, 22), QPointF(60, 22))
    path = QPainterPath(QPointF(28, 30))
    path.lineTo(QPointF(33, 82))
    path.lineTo(QPointF(67, 82))
    path.lineTo(QPointF(72, 30))
    p.drawPath(path)
    p.drawLine(QPointF(50, 42), QPointF(50, 70))


def _draw_star(p: QPainter, c: QColor) -> None:
    """Étoile : favori."""
    from math import cos, pi, sin

    pts: list[tuple[float, float]] = []
    for i in range(10):
        a = -pi / 2 + i * pi / 5
        r = 38.0 if i % 2 == 0 else 16.0
        pts.append((50 + r * cos(a), 50 + r * sin(a)))
    _fill(p, c)
    p.drawPolygon(_poly(pts))


def _draw_tag(p: QPainter, c: QColor) -> None:
    """Étiquette : un tag."""
    _pen(p, c, 7.0)
    path = QPainterPath(QPointF(18, 46))
    path.lineTo(QPointF(46, 18))
    path.lineTo(QPointF(82, 18))
    path.lineTo(QPointF(82, 54))
    path.lineTo(QPointF(54, 82))
    path.closeSubpath()
    p.drawPath(path)
    _fill(p, c)
    p.drawEllipse(QPointF(66, 34), 6, 6)


def _draw_wave(p: QPainter, c: QColor) -> None:
    """Onde continue : l'audio."""
    _pen(p, c, 8.0)
    path = QPainterPath(QPointF(12, 50))
    path.cubicTo(QPointF(28, 8), QPointF(38, 92), QPointF(50, 50))
    path.cubicTo(QPointF(62, 8), QPointF(72, 92), QPointF(88, 50))
    p.drawPath(path)


def _draw_dice(p: QPainter, c: QColor) -> None:
    """Dé : le tirage aléatoire."""
    _pen(p, c, 7.0)
    _rounded(p, 18, 18, 64, 64, 12)
    _fill(p, c)
    for x, y in ((36, 36), (64, 36), (50, 50), (36, 64), (64, 64)):
        p.drawEllipse(QPointF(x, y), 6, 6)


def _draw_copy(p: QPainter, c: QColor) -> None:
    """Deux feuilles : dupliquer."""
    _pen(p, c, 7.0)
    _rounded(p, 18, 18, 46, 46, 7)
    _rounded(p, 36, 36, 46, 46, 7)


def _draw_link(p: QPainter, c: QColor) -> None:
    """Deux maillons : une dépendance."""
    _pen(p, c, 9.0)
    path = QPainterPath()
    path.arcMoveTo(QRectF(14, 32, 44, 36), 90)
    path.arcTo(QRectF(14, 32, 44, 36), 90, 180)
    p.drawPath(path)
    path2 = QPainterPath()
    path2.arcMoveTo(QRectF(42, 32, 44, 36), 270)
    path2.arcTo(QRectF(42, 32, 44, 36), 270, 180)
    p.drawPath(path2)
    p.drawLine(QPointF(38, 50), QPointF(62, 50))


def _draw_warning(p: QPainter, c: QColor) -> None:
    """Triangle d'alerte."""
    _pen(p, c, 8.0)
    path = QPainterPath(QPointF(50, 16))
    path.lineTo(QPointF(88, 82))
    path.lineTo(QPointF(12, 82))
    path.closeSubpath()
    p.drawPath(path)
    p.drawLine(QPointF(50, 40), QPointF(50, 60))
    _fill(p, c)
    p.drawEllipse(QPointF(50, 72), 4.5, 4.5)


def _draw_check(p: QPainter, c: QColor) -> None:
    """Coche : tout va bien."""
    _pen(p, c, 11.0)
    p.drawPolyline(_poly([(20, 52), (41, 73), (82, 30)]))


def _draw_plus(p: QPainter, c: QColor) -> None:
    """Signe plus."""
    _pen(p, c, 10.0)
    p.drawLine(QPointF(50, 24), QPointF(50, 76))
    p.drawLine(QPointF(24, 50), QPointF(76, 50))


def _draw_minus(p: QPainter, c: QColor) -> None:
    """Signe moins."""
    _pen(p, c, 10.0)
    p.drawLine(QPointF(24, 50), QPointF(76, 50))


def _draw_filter(p: QPainter, c: QColor) -> None:
    """Entonnoir : filtrer une liste."""
    _pen(p, c, 8.0)
    p.drawPolyline(_poly([(16, 24), (84, 24), (58, 52), (58, 84),
                          (42, 76), (42, 52), (16, 24)]))


def _draw_grid(p: QPainter, c: QColor) -> None:
    """Grille serrée : l'affichage en vignettes."""
    _fill(p, c)
    for row in range(3):
        for col in range(3):
            _rounded(p, 18 + col * 24, 18 + row * 24, 16, 16, 3)


def _draw_list(p: QPainter, c: QColor) -> None:
    """Liste à puces : l'affichage en tableau."""
    _fill(p, c)
    for y in (28, 50, 72):
        p.drawEllipse(QPointF(22, y), 5, 5)
        _rounded(p, 36, y - 5, 46, 10, 4)


def _draw_info(p: QPainter, c: QColor) -> None:
    """Cercle d'information."""
    _pen(p, c, 7.0)
    p.drawEllipse(QPointF(50, 50), 34, 34)
    p.drawLine(QPointF(50, 46), QPointF(50, 70))
    _fill(p, c)
    p.drawEllipse(QPointF(50, 32), 5, 5)


def _draw_backup(p: QPainter, c: QColor) -> None:
    """Pile de disques : la sauvegarde."""
    _pen(p, c, 7.0)
    for y in (30, 50, 70):
        p.drawEllipse(QRectF(20, y - 9, 60, 18))
    p.drawLine(QPointF(20, 30), QPointF(20, 70))
    p.drawLine(QPointF(80, 30), QPointF(80, 70))


def _draw_midi(p: QPainter, c: QColor) -> None:
    """Prise DIN 5 broches : le MIDI."""
    _pen(p, c, 7.0)
    p.drawEllipse(QPointF(50, 50), 34, 34)
    _fill(p, c)
    from math import cos, pi, sin

    for i in range(5):
        a = pi + i * pi / 4.0
        p.drawEllipse(QPointF(50 + 20 * cos(a), 50 + 20 * sin(a)), 5.5, 5.5)


#: Table des fonctions de dessin, par nom d'icône.
_DRAW = {
    "dashboard": _draw_dashboard,
    "samples": _draw_samples,
    "synth": _draw_synth,
    "kit": _draw_kit,
    "song": _draw_song,
    "wand": _draw_wand,
    "tools": _draw_tools,
    "health": _draw_health,
    "settings": _draw_settings,
    "play": _draw_play,
    "stop": _draw_stop,
    "search": _draw_search,
    "refresh": _draw_refresh,
    "folder": _draw_folder,
    "save": _draw_save,
    "export": _draw_export,
    "import": _draw_import,
    "trash": _draw_trash,
    "star": _draw_star,
    "tag": _draw_tag,
    "wave": _draw_wave,
    "dice": _draw_dice,
    "copy": _draw_copy,
    "link": _draw_link,
    "warning": _draw_warning,
    "check": _draw_check,
    "chevron-right": lambda p, c: _chevron(p, c, down=False),
    "chevron-down": lambda p, c: _chevron(p, c, down=True),
    "plus": _draw_plus,
    "minus": _draw_minus,
    "filter": _draw_filter,
    "grid": _draw_grid,
    "list": _draw_list,
    "info": _draw_info,
    "backup": _draw_backup,
    "midi": _draw_midi,
}


# --------------------------------------------------------------------------- #
# Fabrication des icônes
# --------------------------------------------------------------------------- #

def _render(name: str, color: str, size: int) -> QPixmap:
    """Dessine l'icône ``name`` et retourne son pixmap."""
    size = max(8, int(size))
    pm = QPixmap(size, size)
    pm.fill(QColor(0, 0, 0, 0))
    draw = _DRAW.get(name)
    if draw is None:
        log.debug("icône inconnue : %r", name)
        return pm
    p = QPainter(pm)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.scale(size / _GRID, size / _GRID)
        draw(p, QColor(color))
    except (ValueError, TypeError) as exc:
        log.debug("échec du dessin de l'icône %r : %s", name, exc)
    finally:
        p.end()
    return pm


@lru_cache(maxsize=512)
def _cached_icon(name: str, color: str, size: int) -> QIcon:
    """Icône mise en cache : les barres d'outils en redemandent beaucoup."""
    return QIcon(_render(name, color, size))


def icon(name: str, color: str = PAD_WHITE, size: int = 20) -> QIcon:
    """Icône de l'application, dessinée dans la couleur demandée.

    Les noms disponibles sont ceux de :data:`ICON_NAMES`. Un nom inconnu rend
    une icône vide plutôt que de lever, pour ne jamais casser une barre
    d'outils.
    """
    return _cached_icon(str(name), str(color), int(size))


def pad_pixmap(colors, size: int = 64) -> QPixmap:
    """Grille carrée de pads colorés.

    ``colors`` est une suite de couleurs ; la grille prend la plus petite
    taille carrée capable de les contenir (4 couleurs -> 2x2, 16 -> 4x4).
    """
    cols = list(colors) or [PAD_WHITE]
    side = max(1, int(len(cols) ** 0.5 + 0.999))
    size = max(8, int(size))
    pm = QPixmap(size, size)
    pm.fill(QColor(0, 0, 0, 0))

    gap = size / (side * 8.0)
    cell = (size - gap * (side + 1)) / side
    radius = max(1.0, cell * 0.22)

    p = QPainter(pm)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        for i, col in enumerate(cols[: side * side]):
            row, column = divmod(i, side)
            x = gap + column * (cell + gap)
            y = gap + row * (cell + gap)
            p.setBrush(QColor(col))
            p.drawRoundedRect(QRectF(x, y, cell, cell), radius, radius)
    finally:
        p.end()
    return pm


def app_icon(size: int = 256) -> QIcon:
    """Emblème de l'application : grille 4x4 de pads dans un disque cerclé d'or.

    C'est la reprise directe du langage visuel du *Guide du Deluge*
    (cf. SPEC §2).
    """
    size = max(16, int(size))
    pm = QPixmap(size, size)
    pm.fill(QColor(0, 0, 0, 0))
    s = size / 100.0

    p = QPainter(pm)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.scale(s, s)

        # Disque sombre.
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(PANEL_LO))
        p.drawEllipse(QPointF(50, 50), 48, 48)

        # Anneau d'or.
        ring = QPen(QColor(GOLD))
        ring.setWidthF(5.0)
        p.setPen(ring)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(50, 50), 45.5, 45.5)

        # Grille 4x4 de pads, dans l'ordre du cycle de couleurs.
        p.setPen(Qt.PenStyle.NoPen)
        cell, gap, origin = 13.0, 3.5, 25.75
        for i in range(16):
            row, col = divmod(i, 4)
            p.setBrush(QColor(PAD_CYCLE[i % len(PAD_CYCLE)]))
            p.drawRoundedRect(
                QRectF(origin + col * (cell + gap) - cell / 2,
                       origin + row * (cell + gap) - cell / 2,
                       cell, cell),
                3.0, 3.0,
            )
    finally:
        p.end()
    return QIcon(pm)
