# -*- coding: utf-8 -*-
"""Les dessins du *Guide du Deluge*, tracés au QPainter.

Le guide a trois signatures graphiques, que l'application reprend telles
quelles (``build/figs_schema.py`` et ``build/style.py`` du guide) :

* **le treillis** — des blocs de traitement (gain, oscillateur, filtre,
  mélange, modulation, matrice, retard) reliés par des pistes orthogonales,
  sur la couverture et chaque ouverture de partie. Chaque partie du livre
  y a sa couleur dominante ; chaque page de l'application aussi ;
* **le pad allumé** — carré arrondi plein, entouré d'un halo de sa couleur ;
* **le pad au repos** — cadre fin à l'or sourd et quatre points, « comme
  une diode au repos ».

Tout est **déterministe** : une même graine donne le même dessin, pour qu'une
page garde son visage d'un affichage à l'autre. Les treillis, seuls tracés
coûteux (quelques millisecondes), sont gardés en cache par taille.

Aucune dépendance au-delà de ``QtGui`` : ce module sert aussi à l'écran de
démarrage, avant que la moindre fenêtre n'existe.
"""

from __future__ import annotations

import logging
import math
import random
import zlib
from collections import OrderedDict

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)

from .theme import GOLD, GOLD_LO, PAD_CYCLE, PAD_ETEINT, mix

log = logging.getLogger(__name__)

#: Les sept symboles de traitement du treillis, dans l'ordre du guide.
KINDS = ("ampli", "onde", "anneau", "somme", "filtre", "grille", "retard")

#: Pas de la grille des blocs, en pixels logiques.
CELL = 36.0

#: Nombre de treillis gardés en mémoire (un par page et par taille).
_CACHE_MAX = 24
_CACHE: "OrderedDict[tuple, QPixmap]" = OrderedDict()


def seed_of(text: str) -> int:
    """Graine stable tirée d'un texte : la clé d'une page, par exemple.

    ``hash()`` change à chaque lancement de Python ; ``crc32`` jamais.
    """
    return zlib.crc32(str(text or "").encode("utf-8"))


def palette_for(color: str) -> list[str]:
    """Palette pondérée d'un treillis : la couleur de la page domine.

    C'est la règle du guide (``TREILLIS_EMBLEME``) : huit teintes à parts
    égales « font guirlande », plus rien ne domine et l'œil ne se pose nulle
    part. La couleur de la partie revient donc cinq fois, deux teintes du
    cycle l'accompagnent, et l'or des encodeurs deux fois.
    """
    teinte = str(color or GOLD).upper()
    try:
        rang = [c.upper() for c in PAD_CYCLE].index(teinte)
    except ValueError:
        rang = 0
    opposee = PAD_CYCLE[(rang + 6) % len(PAD_CYCLE)]
    voisine = PAD_CYCLE[(rang + 3) % len(PAD_CYCLE)]
    return [teinte] * 5 + [opposee, voisine] + [GOLD] * 2


# --------------------------------------------------------------------------- #
# Primitives
# --------------------------------------------------------------------------- #

def _qcolor(color: str, alpha: float = 1.0) -> QColor:
    couleur = QColor(color)
    couleur.setAlphaF(max(0.0, min(1.0, float(alpha))))
    return couleur


def _pen(color: str, width: float, alpha: float = 1.0) -> QPen:
    pen = QPen(_qcolor(color, alpha))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
    return pen


def paint_symbol(p: QPainter, cx: float, cy: float, side: float, kind: str,
                 color: str, width: float = 1.1, alpha: float = 1.0) -> None:
    """Symbole de traitement inscrit dans un bloc de côté ``side``.

    Repris de ``figs_schema._sym`` du guide, l'axe vertical retourné : le
    guide dessine avec l'ordonnée vers le haut, Qt vers le bas.
    """
    h = side / 2.0
    p.setPen(_pen(color, width, alpha))
    p.setBrush(Qt.BrushStyle.NoBrush)
    if kind == "ampli":                     # triangle : gain
        chemin = QPainterPath(QPointF(cx - h * 0.5, cy - h * 0.6))
        chemin.lineTo(cx + h * 0.6, cy)
        chemin.lineTo(cx - h * 0.5, cy + h * 0.6)
        chemin.closeSubpath()
        p.drawPath(chemin)
    elif kind == "onde":                    # sinusoïde : oscillateur
        chemin = QPainterPath()
        for i in range(25):
            t = -h * 0.6 + i * (h * 1.2 / 24)
            point = QPointF(cx + t, cy - math.sin(t / h * 5.0) * h * 0.42)
            if i == 0:
                chemin.moveTo(point)
            else:
                chemin.lineTo(point)
        p.drawPath(chemin)
    elif kind == "anneau":                  # croix cerclée : modulation
        p.drawEllipse(QPointF(cx, cy), h * 0.55, h * 0.55)
        d = h * 0.39
        p.drawLine(QPointF(cx - d, cy - d), QPointF(cx + d, cy + d))
        p.drawLine(QPointF(cx - d, cy + d), QPointF(cx + d, cy - d))
    elif kind == "somme":                   # plus cerclé : mélange
        p.drawEllipse(QPointF(cx, cy), h * 0.55, h * 0.55)
        p.drawLine(QPointF(cx - h * 0.35, cy), QPointF(cx + h * 0.35, cy))
        p.drawLine(QPointF(cx, cy - h * 0.35), QPointF(cx, cy + h * 0.35))
    elif kind == "filtre":                  # pente : filtre
        chemin = QPainterPath(QPointF(cx - h * 0.55, cy - h * 0.4))
        chemin.lineTo(cx, cy - h * 0.4)
        chemin.lineTo(cx + h * 0.55, cy + h * 0.45)
        p.drawPath(chemin)
    elif kind == "grille":                  # quadrillage : matrice
        for k in (-1, 1):
            p.drawLine(QPointF(cx + k * h * 0.22, cy - h * 0.5),
                       QPointF(cx + k * h * 0.22, cy + h * 0.5))
            p.drawLine(QPointF(cx - h * 0.5, cy + k * h * 0.22),
                       QPointF(cx + h * 0.5, cy + k * h * 0.22))
    elif kind == "retard":                  # deux barres : delay
        for k in (-0.25, 0.25):
            p.drawLine(QPointF(cx + k * side, cy - h * 0.45),
                       QPointF(cx + k * side, cy + h * 0.45))


def paint_glow(p: QPainter, rect: QRectF, color: str,
               strength: float = 0.35, spread: float = 0.9) -> None:
    """Halo doux autour d'un rectangle : la lumière d'un pad allumé.

    Un dégradé radial plutôt que le simple carré translucide du guide : à
    l'écran, où l'on regarde de près, le bord net du carré se voyait.
    """
    if strength <= 0:
        return
    rayon = max(rect.width(), rect.height()) * (0.5 + spread)
    degrade = QRadialGradient(rect.center(), rayon)
    degrade.setColorAt(0.0, _qcolor(color, strength))
    degrade.setColorAt(0.45, _qcolor(color, strength * 0.55))
    degrade.setColorAt(1.0, _qcolor(color, 0.0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(degrade)
    p.drawEllipse(rect.center(), rayon, rayon)


def paint_pad(p: QPainter, rect: QRectF, color: str, glow: float = 0.30,
              radius: float | None = None, sheen: bool = True) -> None:
    """Un pad allumé : halo, corps plein, reflet en haut.

    Le reflet — le haut du pad un peu plus clair — imite le silicone
    éclairé par en dessous ; sans lui, un pad ressemble à une case de
    tableur.
    """
    r = rect.width() * 0.22 if radius is None else radius
    if glow > 0:
        paint_glow(p, rect, color, glow)
    p.setPen(Qt.PenStyle.NoPen)
    if sheen:
        degrade = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        degrade.setColorAt(0.0, QColor(mix(color, "#FFFFFF", 0.24)))
        degrade.setColorAt(0.55, QColor(color))
        degrade.setColorAt(1.0, QColor(mix(color, "#000000", 0.10)))
        p.setBrush(degrade)
    else:
        p.setBrush(QColor(color))
    p.drawRoundedRect(rect, r, r)


def paint_off_pad(p: QPainter, rect: QRectF, diode: bool = True,
                  radius: float | None = None, tint: str = "",
                  alpha: float = 1.0) -> None:
    """Un pad au repos.

    ``diode`` : le cadre à l'or sourd et ses quatre points, comme la
    matrice de la couverture. Sans ``diode`` : le pad éteint plein
    (``PAD_ETEINT``), plus calme, pour les grilles denses. ``tint`` teinte
    légèrement le cadre — la couleur de la page, pour un pad qui attend.
    """
    r = rect.width() * 0.22 if radius is None else radius
    p.setBrush(_qcolor(PAD_ETEINT, alpha))
    if diode:
        p.setPen(_pen(tint or GOLD_LO, max(1.0, rect.width() * 0.035),
                      0.60 * alpha))
    else:
        p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), r, r)
    if diode and rect.width() >= 12:
        cote = max(1.2, rect.width() * 0.075)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_qcolor(tint or GOLD_LO, 0.75 * alpha))
        for dx in (0.36, 0.64):
            for dy in (0.36, 0.64):
                x = rect.x() + rect.width() * dx - cote / 2
                y = rect.y() + rect.height() * dy - cote / 2
                p.drawRect(QRectF(x, y, cote, cote))


# --------------------------------------------------------------------------- #
# Treillis
# --------------------------------------------------------------------------- #

def circuit(width: int, height: int, color: str, seed: int = 0,
            dpr: float = 1.0, density: float = 0.42,
            fade: tuple[float, float] = (0.20, 0.62)) -> QPixmap:
    """Le treillis du guide, à la couleur donnée, dans un pixmap transparent.

    ``fade`` : le dessin s'efface vers la gauche entre ces deux fractions de
    la largeur. Un en-tête pose son titre à gauche : le schéma s'estompe
    derrière le texte au lieu de se battre avec lui.

    Le résultat est mis en cache par ``(taille, couleur, graine, densité)``.
    """
    w = max(8, int(width))
    h = max(8, int(height))
    ratio = max(1.0, float(dpr))
    cle = (w, h, str(color), int(seed), round(ratio, 2), round(density, 3),
           tuple(round(v, 3) for v in fade))
    deja = _CACHE.get(cle)
    if deja is not None:
        _CACHE.move_to_end(cle)
        return deja

    pixmap = QPixmap(int(w * ratio), int(h * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(QColor(0, 0, 0, 0))
    p = QPainter(pixmap)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        _paint_circuit(p, w, h, color, random.Random(int(seed)), density)
        _fade_left(p, w, h, fade)
    except Exception:              # noqa: BLE001 - un décor ne casse rien
        log.exception("treillis impossible à dessiner")
    finally:
        p.end()

    _CACHE[cle] = pixmap
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return pixmap


def _paint_circuit(p: QPainter, w: float, h: float, color: str,
                   rng: random.Random, density: float) -> None:
    """Pistes, blocs, liaisons et semis : les quatre couches du guide."""
    palette = palette_for(color)

    # 1. La nappe de pistes, qui donne sa densité au réseau.
    pistes = int(w * h / 1300)
    for _ in range(pistes):
        px = rng.random() * w
        py = rng.random() * h
        long_ = (0.03 + rng.random() * 0.14) * w
        sens_x = 1 if rng.random() < 0.5 else -1
        sens_y = 1 if rng.random() < 0.5 else -1
        if rng.random() < 0.5:
            points = [(px, py), (px + long_ * sens_x, py),
                      (px + long_ * sens_x, py + long_ * 0.4 * sens_y)]
        else:
            points = [(px, py), (px, py + long_ * 0.4 * sens_y),
                      (px + long_ * sens_x, py + long_ * 0.4 * sens_y)]
        points = [(min(max(x, 0.0), w), min(max(y, 0.0), h))
                  for x, y in points]
        teinte = palette[rng.randrange(len(palette))]
        p.setPen(_pen(teinte, 0.9, 0.38))
        p.setBrush(Qt.BrushStyle.NoBrush)
        chemin = QPainterPath(QPointF(*points[0]))
        for x, y in points[1:]:
            chemin.lineTo(x, y)
        p.drawPath(chemin)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_qcolor(teinte, 0.62))
        p.drawEllipse(QPointF(*points[-1]), 1.6, 1.6)

    # 2. Les blocs de traitement, plus denses à droite : le schéma s'efface
    # vers le titre au lieu de s'arrêter net.
    colonnes = max(3, int(w / CELL))
    rangees = max(1, int(h / CELL))
    pas_x, pas_y = w / colonnes, h / rangees
    cote = min(pas_x, pas_y) * 0.60
    blocs: dict[tuple[int, int], tuple[float, float]] = {}
    for c in range(colonnes):
        poids = 0.25 + 0.75 * (c / max(1, colonnes - 1))
        for r in range(rangees):
            if rng.random() > density * poids:
                continue
            cx = (c + 0.5) * pas_x + rng.uniform(-1, 1) * pas_x * 0.08
            cy = (r + 0.5) * pas_y + rng.uniform(-1, 1) * pas_y * 0.08
            blocs[(c, r)] = (cx, cy)

    # 3. Les liaisons orthogonales, à l'or sourd, sous les blocs.
    for (c, r), (cx, cy) in blocs.items():
        for dc, dr in ((1, 0), (0, 1)):
            voisin = blocs.get((c + dc, r + dr))
            if voisin is None or rng.random() > 0.85:
                continue
            vx, vy = voisin
            milieu = (cx + vx) / 2
            p.setPen(_pen(GOLD_LO, 1.0, 0.85))
            p.setBrush(Qt.BrushStyle.NoBrush)
            chemin = QPainterPath(QPointF(cx, cy))
            chemin.lineTo(milieu, cy)
            chemin.lineTo(milieu, vy)
            chemin.lineTo(vx, vy)
            p.drawPath(chemin)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(GOLD))
            p.drawEllipse(QPointF(milieu, cy), 1.9, 1.9)

    for cx, cy in blocs.values():
        teinte = palette[rng.randrange(len(palette))]
        cadre = QRectF(cx - cote / 2, cy - cote / 2, cote, cote)
        # Le fond du bloc masque les pistes qui passent dessous, comme
        # sur la couverture.
        p.setPen(_pen(teinte, 1.35, 0.95))
        p.setBrush(_qcolor("#0B0D11", 0.92))
        p.drawRoundedRect(cadre, cote * 0.12, cote * 0.12)
        paint_symbol(p, cx, cy, cote, KINDS[rng.randrange(len(KINDS))],
                     teinte, 1.1, 0.95)

    # 4. Le semis de petits repères, qui donne sa profondeur au réseau.
    for _ in range(int(colonnes * rangees * 3.2)):
        px = rng.random() * w
        py = rng.random() * h
        forme = rng.randrange(3)
        p.setPen(_pen(GOLD_LO, 0.8, 0.55))
        p.setBrush(Qt.BrushStyle.NoBrush)
        if forme == 0:
            p.drawLine(QPointF(px - 2, py), QPointF(px + 2, py))
            p.drawLine(QPointF(px, py - 2), QPointF(px, py + 2))
        elif forme == 1:
            p.drawEllipse(QPointF(px, py), 1.3, 1.3)
        else:
            p.drawRect(QRectF(px - 1.2, py - 1.2, 2.4, 2.4))


def _fade_left(p: QPainter, w: float, h: float,
               fade: tuple[float, float]) -> None:
    """Efface le dessin vers la gauche (masque de transparence)."""
    debut, fin = fade
    if fin <= 0:
        return
    degrade = QLinearGradient(QPointF(w * max(0.0, debut), 0),
                              QPointF(w * max(debut + 0.01, fin), 0))
    degrade.setColorAt(0.0, QColor(0, 0, 0, 0))
    degrade.setColorAt(1.0, QColor(0, 0, 0, 255))
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(degrade)
    p.drawRect(QRectF(0, 0, w, h))
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)


def clear_cache() -> None:
    """Vide le cache des treillis (changement d'écran, tests)."""
    _CACHE.clear()


def cache_size() -> int:
    """Nombre de treillis en mémoire."""
    return len(_CACHE)
