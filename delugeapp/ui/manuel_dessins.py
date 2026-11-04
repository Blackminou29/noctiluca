# -*- coding: utf-8 -*-
"""Les dessins du manuel : ouvertures de partie, pads de chapitre, figures.

Tout est tracé au QPainter, dans le langage du *Guide du Deluge* que
l'application reprend déjà (:mod:`.art`) :

* **l'ouverture de partie** est celle du guide — le treillis à la couleur de
  la partie, le cartouche sombre au chiffre romain, la rangée de pads ;
* **le pad de chapitre** est le pad allumé de la colonne de gauche, avec
  l'icône de la page qu'il décrit ;
* **les figures** sont des schémas sur papier, comme celles du guide : des
  panneaux sombres, des pads, des numéros d'or.

Aucune figure n'écrit de phrase de son cru : ses légendes viennent du texte
du manuel, dans sa langue (``[[figure nom | légende | libellés]]``). Les
dessins sont donc les mêmes en français et en anglais, et seul le texte
change. :data:`FIGURES` dit combien de libellés chacune attend ; un test le
vérifie sur les deux manuels.

Les images sont rendues à deux fois leur taille logique : le manuel les
réduit à la largeur de sa colonne, et elles restent nettes sur un écran à
haute densité comme dans le PDF.
"""

from __future__ import annotations

import logging
import math
import random
from typing import Callable

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
)

from ..i18n import untranslated
from . import art, icons
from .theme import (
    GOLD,
    GOLD_HI,
    GOLD_LO,
    GREY,
    INK,
    INK_SOFT,
    OLED_BG,
    OLED_DIM,
    OLED_EDGE,
    OLED_HI,
    PAD_AMBER,
    PAD_BLUE,
    PAD_CYAN,
    PAD_CYCLE,
    PAD_GREEN,
    PAD_MAGENTA,
    PAD_MINT,
    PAD_ORANGE,
    PAD_PURPLE,
    PAD_RED,
    PAD_WHITE,
    PAGE_COLORS,
    PANEL,
    PANEL_LO,
    lit_fill,
)

log = logging.getLogger(__name__)

#: Polices du guide : Trebuchet pour les titres et les schémas.
TITRES = untranslated(["Trebuchet MS", "DejaVu Sans", "Segoe UI"])
#: Encre des libellés sur papier, et leur gris.
ENCRE = "#1A1D23"
ENCRE_DOUCE = "#6E7684"
#: Fond des pages du manuel : le papier chaud du guide.
PAPIER = "#FAF8F4"
#: Fond des ouvertures de partie (``PANEL`` du guide).
FOND_OUVERTURE = "#1C1F26"
CARTOUCHE = "#101319"

#: Les onze pages, dans l'ordre de la colonne de gauche : l'accueil, ce qui
#: crée, la bibliothèque et le pont vers le DAW, puis la carte.
ORDRE_PAGES = ("Dashboard", "Atelier", "Generator", "Toolbox", "Samples",
               "Synths", "Kits", "Songs", "Daw", "Health", "Settings")

#: Les pages qui ouvrent un groupe de la colonne : Créer, Bibliothèque, La
#: carte.
GROUPES_PAGES = ("Atelier", "Samples", "Health")

#: L'icône de chaque page, celle de son pad dans la colonne de gauche.
ICONES_PAGES = {"Dashboard": "home", "Samples": "samples",
                "Synths": "synth", "Kits": "kit", "Songs": "song",
                "Daw": "link",
                "Generator": "wand", "Atelier": "atelier", "Toolbox": "memo",
                "Health": "health", "Settings": "settings"}

#: Les couleurs des cinq étapes de l'atelier, celles de sa barre d'étapes.
COULEURS_ETAPES = (PAD_RED, PAD_PURPLE, PAD_GREEN, PAD_BLUE, PAD_AMBER)

#: Échelle de rendu : les images sont dessinées deux fois plus grandes que
#: leur taille logique.
ECHELLE = 2.0

#: Corps des libellés des figures, dessinées sur 1 000 points de large. Le
#: manuel les réduit à sa colonne : 780 points au plus, 600 dans une fenêtre
#: de 980. Mesuré : à 9,5 points, une légende y tombait sous les 6 points,
#: illisible ; à 12,5, elle reste au-dessus de 7,5.
TITRE_FIG = 15.0
TEXTE_FIG = 12.5


def romain(nombre: int) -> str:
    """``4`` -> ``IV`` : les parties du guide sont numérotées ainsi."""
    valeurs = ((10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"))
    reste, texte = max(1, int(nombre)), ""
    for valeur, lettres in valeurs:
        while reste >= valeur:
            texte += lettres
            reste -= valeur
    return texte


def couleur_de(nom: str, defaut: str = GOLD) -> str:
    """Une couleur désignée par une clé de page, un nom de la palette
    (``PAD_GREEN``, ``GOLD``) ou un code ``#RRGGBB``."""
    texte = str(nom or "").strip()
    if not texte:
        return defaut
    if texte.startswith("#") and len(texte) == 7:
        return texte.upper()
    if texte in PAGE_COLORS:
        return PAGE_COLORS[texte]
    from . import theme

    valeur = getattr(theme, texte.upper(), None)
    return valeur if isinstance(valeur, str) and valeur.startswith("#") \
        else defaut


# --------------------------------------------------------------------------- #
# Infrastructure
# --------------------------------------------------------------------------- #

class _Toile:
    """Une image et son peintre, en unités logiques.

    ``with _Toile(1000, 400) as (p, toile):`` — le peintre est fermé à la
    sortie, même si le dessin lève : un ``QPainter`` resté ouvert sur une
    image fait planter Qt à la destruction de celle-ci.
    """

    def __init__(self, largeur: float, hauteur: float,
                 fond: str | None = PAPIER) -> None:
        self.largeur = float(largeur)
        self.hauteur = float(hauteur)
        self.image = QImage(int(round(largeur * ECHELLE)),
                            int(round(hauteur * ECHELLE)),
                            QImage.Format.Format_ARGB32_Premultiplied)
        self.image.fill(QColor(fond) if fond else QColor(0, 0, 0, 0))
        self.peintre = QPainter()

    def __enter__(self):
        p = self.peintre
        p.begin(self.image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.scale(ECHELLE, ECHELLE)
        return p, self

    def __exit__(self, *_exc) -> bool:
        if self.peintre.isActive():
            self.peintre.end()
        return False


def _police(taille: float, graisse: int = 400, espacement: float = 0.0,
            italique: bool = False) -> QFont:
    police = QFont()
    police.setFamilies(list(TITRES))
    police.setPointSizeF(float(taille))
    police.setWeight(QFont.Weight(int(graisse)))
    police.setItalic(bool(italique))
    if espacement:
        police.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing,
                                float(espacement))
    return police


def _crayon(couleur: str, largeur: float = 1.0, alpha: float = 1.0,
            pointille: bool = False) -> QPen:
    teinte = QColor(couleur)
    teinte.setAlphaF(max(0.0, min(1.0, alpha)))
    crayon = QPen(teinte)
    crayon.setWidthF(largeur)
    crayon.setCapStyle(Qt.PenCapStyle.RoundCap)
    crayon.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    if pointille:
        crayon.setDashPattern([3.0, 2.5])
    return crayon


def _texte(p: QPainter, x: float, y: float, texte: str, police: QFont,
           couleur: str, aligne: str = "gauche", largeur: float = 0.0,
           lignes: int = 1) -> float:
    """Écrit ``texte`` ; rend la hauteur occupée.

    ``aligne`` : ``gauche``, ``centre`` ou ``droite`` par rapport à ``x``.
    Avec une ``largeur``, le texte passe à la ligne, sur ``lignes`` lignes au
    plus, et la dernière s'élide.
    """
    p.setFont(police)
    p.setPen(QColor(couleur))
    metrique = QFontMetricsF(police)
    morceaux = [str(texte or "")]
    if largeur > 0:
        morceaux = _couper(str(texte or ""), metrique, largeur, lignes)
    hauteur = metrique.height()
    for rang, morceau in enumerate(morceaux):
        mesure = metrique.horizontalAdvance(morceau)
        if aligne == "centre":
            depart = x - mesure / 2.0
        elif aligne == "droite":
            depart = x - mesure
        else:
            depart = x
        p.drawText(QPointF(depart, y + metrique.ascent() + rang * hauteur),
                   morceau)
    return hauteur * len(morceaux)


def _couper(texte: str, metrique: QFontMetricsF, largeur: float,
            lignes: int) -> list[str]:
    """Le texte en lignes qui tiennent dans ``largeur``."""
    mots = texte.split()
    resultat: list[str] = []
    courante = ""
    for mot in mots:
        essai = (courante + " " + mot).strip()
        if metrique.horizontalAdvance(essai) <= largeur or not courante:
            courante = essai
        else:
            resultat.append(courante)
            courante = mot
    if courante:
        resultat.append(courante)
    if len(resultat) > lignes:
        reste = " ".join(resultat[lignes - 1:])
        resultat = resultat[:lignes - 1] + [metrique.elidedText(
            reste, Qt.TextElideMode.ElideRight, largeur)]
    return resultat or [""]


def _boite(p: QPainter, rect: QRectF, fond: str, bord: str | None = None,
           rayon: float = 8.0, largeur: float = 1.0) -> None:
    p.setPen(_crayon(bord, largeur) if bord else Qt.PenStyle.NoPen)
    p.setBrush(QColor(fond))
    p.drawRoundedRect(rect, rayon, rayon)


def _fleche(p: QPainter, x1: float, y1: float, x2: float, y2: float,
            couleur: str = INK_SOFT, largeur: float = 1.6,
            deux_sens: bool = False, pointille: bool = False) -> None:
    """Une flèche droite, à pointe pleine — celle des schémas du guide."""
    p.setPen(_crayon(couleur, largeur, pointille=pointille))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    pointes = [((x1, y1), (x2, y2))]
    if deux_sens:
        pointes.append(((x2, y2), (x1, y1)))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(couleur))
    for (ax, ay), (bx, by) in pointes:
        angle = math.atan2(by - ay, bx - ax)
        longueur = 8.0 + largeur
        chemin = QPainterPath(QPointF(bx, by))
        chemin.lineTo(bx - longueur * math.cos(angle - 0.42),
                      by - longueur * math.sin(angle - 0.42))
        chemin.lineTo(bx - longueur * math.cos(angle + 0.42),
                      by - longueur * math.sin(angle + 0.42))
        chemin.closeSubpath()
        p.drawPath(chemin)


def _numero(p: QPainter, x: float, y: float, nombre: int,
            rayon: float = 11.0) -> None:
    """Le repère numéroté d'une figure : un disque d'or, chiffre à l'encre."""
    p.setPen(_crayon("#FFFFFF", 1.6))
    p.setBrush(QColor(GOLD))
    p.drawEllipse(QPointF(x, y), rayon, rayon)
    police = _police(rayon * 0.95, 800)
    p.setFont(police)
    p.setPen(QColor(INK))
    metrique = QFontMetricsF(police)
    texte = str(nombre)
    p.drawText(QPointF(x - metrique.horizontalAdvance(texte) / 2.0,
                       y + (metrique.ascent() - metrique.descent()) / 2.0),
               texte)


def _repere(p: QPainter, nombre: int, cible: tuple[float, float],
            pastille: tuple[float, float]) -> None:
    """Un numéro relié par un filet à l'élément qu'il désigne."""
    p.setPen(_crayon(GOLD, 1.2))
    p.drawLine(QPointF(*cible), QPointF(*pastille))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(GOLD))
    p.drawEllipse(QPointF(*cible), 2.6, 2.6)
    _numero(p, pastille[0], pastille[1], nombre)


def _pad_icone(p: QPainter, rect: QRectF, couleur: str, icone: str = "",
               halo: float = 0.30) -> None:
    """Un pad allumé, avec l'icône d'une page à l'encre qui se lit dessus."""
    art.paint_pad(p, rect, couleur, glow=halo)
    if icone:
        encre = lit_fill(couleur)[2]
        cote = int(rect.width() * 0.56 * ECHELLE)
        pixmap = icons.icon(icone, encre, cote).pixmap(cote, cote)
        interieur = QRectF(rect.center().x() - rect.width() * 0.28,
                           rect.center().y() - rect.height() * 0.28,
                           rect.width() * 0.56, rect.height() * 0.56)
        p.drawPixmap(interieur, pixmap, QRectF(pixmap.rect()))


def _libelle(libelles: list[str], rang: int) -> str:
    return libelles[rang] if 0 <= rang < len(libelles) else ""


# --------------------------------------------------------------------------- #
# Éléments de page
# --------------------------------------------------------------------------- #

def ouverture(numero: int, titre: str, sous_titre: str, couleur: str,
              largeur: float = 1000.0) -> QImage:
    """L'ouverture d'une partie : le treillis, le cartouche, les pads.

    Reprise des ouvertures du guide (``figs_couverture``), couchée en
    bandeau : le treillis occupe le haut, le cartouche au chiffre romain
    vient s'y poser, la rangée de pads ferme le bas.
    """
    hauteur = largeur * 0.40
    teinte = couleur_de(couleur)
    with _Toile(largeur, hauteur, FOND_OUVERTURE) as (p, _t):
        haut = hauteur * 0.70
        treillis = art.circuit(int(largeur), int(haut), teinte,
                               seed=art.seed_of("manuel-%d" % numero),
                               density=0.36, fade=(0.0, 0.0))
        p.drawPixmap(QRectF(0, 6, largeur, haut), treillis,
                     QRectF(treillis.rect()))

        # Le cartouche, posé dans le treillis, haut juste de ce qu'il
        # porte : le chiffre, son filet, le titre, la phrase.
        larg_cartouche = largeur * 0.56
        police_titre = _police(22, 800, 1.6)
        police_sous = _police(13, 400)
        lignes_titre = _couper(str(titre or "").upper(),
                               QFontMetricsF(police_titre),
                               larg_cartouche * 0.86, 2)
        lignes_sous = _couper(str(sous_titre or ""),
                              QFontMetricsF(police_sous),
                              larg_cartouche * 0.80, 2) if sous_titre else []
        contenu = (QFontMetricsF(_police(34, 900)).height() + 18
                   + QFontMetricsF(police_titre).height() * len(lignes_titre)
                   + (8 + QFontMetricsF(police_sous).height()
                      * len(lignes_sous) if lignes_sous else 0))
        cartouche = QRectF(largeur * 0.22, 0, larg_cartouche, contenu + 44)
        cartouche.moveCenter(QPointF(largeur / 2.0, haut * 0.56))
        _boite(p, cartouche, CARTOUCHE, rayon=14)
        cx = cartouche.center().x()
        y = cartouche.top() + 22
        y += _texte(p, cx, y, romain(numero), _police(34, 900), teinte,
                    "centre")
        p.setPen(_crayon(teinte, 3.0))
        p.drawLine(QPointF(cx - cartouche.width() * 0.22, y + 6),
                   QPointF(cx + cartouche.width() * 0.22, y + 6))
        y += 18
        y += _texte(p, cx, y, str(titre or "").upper(), police_titre,
                    PAD_WHITE, "centre", cartouche.width() * 0.86, 2)
        if lignes_sous:
            _texte(p, cx, y + 8, sous_titre, police_sous, "#B9C0CB",
                   "centre", cartouche.width() * 0.80, 2)

        # La rangée de pads : la couleur de la partie domine, comme sur les
        # ouvertures du guide.
        tirage = random.Random(art.seed_of("pads-%d" % numero))
        palette = art.palette_for(teinte)
        rangees, colonnes = 2, 24
        marge = largeur * 0.05
        pas = (largeur - 2 * marge) / colonnes
        cote = pas * 0.74
        y0 = hauteur - (rangees * pas) - hauteur * 0.035
        for r in range(rangees):
            for c in range(colonnes):
                cadre = QRectF(marge + c * pas + (pas - cote) / 2,
                               y0 + r * pas + (pas - cote) / 2, cote, cote)
                if tirage.random() < 0.45:
                    art.paint_pad(p, cadre,
                                  palette[tirage.randrange(len(palette))],
                                  glow=0.22, sheen=False)
                else:
                    art.paint_off_pad(p, cadre)
    return _t.image


def pad_chapitre(couleur: str, icone: str, cote: float = 46.0) -> QImage:
    """Le pad allumé qui ouvre un chapitre, avec son icône.

    Sur le papier, le halo est celui des figures du guide (``style.pad``) :
    un carré arrondi translucide, un peu plus grand que le pad. Le halo
    radial de l'écran sombre débordait de l'image et s'y coupait net.
    """
    teinte = couleur_de(couleur)
    marge = cote * 0.18
    with _Toile(cote + 2 * marge, cote + 2 * marge, None) as (p, _t):
        halo = QColor(teinte)
        halo.setAlphaF(0.22)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(halo)
        p.drawRoundedRect(QRectF(marge * 0.15, marge * 0.15,
                                 cote + marge * 1.7, cote + marge * 1.7),
                          cote * 0.30, cote * 0.30)
        _pad_icone(p, QRectF(marge, marge, cote, cote), teinte, icone,
                   halo=0.0)
    return _t.image


def puce(couleur: str, cote: float = 14.0) -> QImage:
    """Un petit pad allumé, pour le sommaire et les liens vers une page."""
    marge = cote * 0.15
    with _Toile(cote + 2 * marge, cote + 2 * marge, None) as (p, _t):
        art.paint_pad(p, QRectF(marge, marge, cote, cote),
                      couleur_de(couleur), glow=0.0)
    return _t.image


def filet(couleur: str, largeur: float = 1000.0) -> QImage:
    """Le filet d'or sous un titre de chapitre."""
    with _Toile(largeur, 3, couleur_de(couleur)) as (_p, _t):
        pass
    return _t.image


# --------------------------------------------------------------------------- #
# Figures
# --------------------------------------------------------------------------- #

def _fenetre(libelles: list[str]) -> QImage:
    """La fenêtre principale et ses dix repères."""
    largeur, hauteur = 1000.0, 600.0
    with _Toile(largeur, hauteur) as (p, _t):
        cadre = QRectF(70, 40, 860, 520)
        _boite(p, cadre.adjusted(-2, -2, 2, 2), "#2A2E37", rayon=12)
        _boite(p, cadre, PANEL_LO, rayon=10)

        # La barre du haut.
        barre = QRectF(cadre.left(), cadre.top(), cadre.width(), 46)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#0E1218"))
        p.drawRoundedRect(barre, 10, 10)
        p.drawRect(QRectF(barre.left(), barre.top() + 20, barre.width(), 26))
        logo = icons.app_icon(64).pixmap(64, 64)
        p.drawPixmap(QRectF(barre.left() + 12, barre.top() + 9, 28, 28), logo,
                     QRectF(logo.rect()))
        _texte(p, barre.left() + 46, barre.top() + 12, "DELUGE",
               _police(11, 900, 1.2), PAD_MAGENTA)
        p.setPen(Qt.PenStyle.NoPen)
        for rang in range(5):
            p.setBrush(QColor("#3A414D"))
            p.drawRoundedRect(QRectF(barre.left() + 130 + rang * 42,
                                     barre.top() + 19, 30, 8), 3, 3)
        ecran = QRectF(barre.left() + 380, barre.top() + 7, 190, 32)
        _boite(p, ecran, OLED_BG, OLED_EDGE, rayon=5)
        p.setBrush(QColor(OLED_DIM))
        p.drawRoundedRect(QRectF(ecran.left() + 10, ecran.top() + 7, 70, 4),
                          2, 2)
        p.setBrush(QColor("#FFFFFF"))
        p.drawRoundedRect(QRectF(ecran.left() + 10, ecran.top() + 16, 120,
                                 8), 2, 2)
        art.paint_pad(p, QRectF(barre.left() + 584, barre.top() + 15, 16, 16),
                      PAD_GREEN, glow=0.5)
        _boite(p, QRectF(barre.left() + 612, barre.top() + 10, 120, 26),
               "#151A22", "#333B48", rayon=13)
        # L'interrupteur Simple / Avancé : la moitié du niveau choisi est
        # allumée à la couleur de la façade.
        bouton = QRectF(barre.left() + 742, barre.top() + 10, 66, 26)
        _boite(p, bouton, "#151A22", "#333B48", rayon=13)
        moitie = QRectF(bouton.left() + 2, bouton.top() + 2,
                        bouton.width() / 2.0 - 2, bouton.height() - 4)
        p.save()
        p.setClipRect(cadre)
        art.paint_glow(p, moitie, GOLD, 0.30, spread=0.4)
        p.restore()
        _boite(p, moitie, GOLD, rayon=11)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#4A515E"))
        p.drawRoundedRect(QRectF(bouton.center().x() + 7,
                                 bouton.center().y() - 2, 18, 4), 2, 2)
        lecture = QRectF(barre.left() + 820, barre.top() + 9, 28, 28)
        _boite(p, lecture, "#1B212B", "#3A414D", rayon=14)
        p.setBrush(QColor(PAD_WHITE))
        p.setPen(Qt.PenStyle.NoPen)
        triangle = QPainterPath(QPointF(lecture.left() + 11,
                                        lecture.top() + 8))
        triangle.lineTo(lecture.left() + 20, lecture.center().y())
        triangle.lineTo(lecture.left() + 11, lecture.bottom() - 8)
        triangle.closeSubpath()
        p.drawPath(triangle)

        # Le filet lumineux, à la couleur de la page affichée.
        teinte = PAGE_COLORS["Samples"]
        p.setBrush(QColor(teinte))
        p.drawRect(QRectF(cadre.left(), barre.bottom(), cadre.width(), 3))

        # La colonne de pads.
        colonne = QRectF(cadre.left(), barre.bottom() + 3, 150,
                         cadre.bottom() - barre.bottom() - 3 - 26)
        p.setBrush(QColor("#0E1218"))
        p.drawRect(colonne)
        groupes = 0
        for rang, cle in enumerate(ORDRE_PAGES):
            if cle in GROUPES_PAGES:
                # Le titre du groupe, en petites capitales, et son filet.
                groupes += 1
                y_titre = colonne.top() + 8 + rang * 36 + (groupes - 1) * 16
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor("#5A6270"))
                p.drawRoundedRect(QRectF(colonne.left() + 12, y_titre + 2,
                                         38, 4), 2, 2)
                p.setPen(_crayon(GOLD, 1.0, 0.45))
                p.drawLine(QPointF(colonne.left() + 56, y_titre + 4),
                           QPointF(colonne.right() - 10, y_titre + 4))
            y = colonne.top() + 10 + rang * 36 + groupes * 16
            cellule = QRectF(colonne.left() + 12, y, 26, 26)
            couleur = PAGE_COLORS[cle]
            if cle == "Samples":
                _boite(p, QRectF(colonne.left() + 6, y - 5, 138, 36),
                       "#1B212B", rayon=8)
                _pad_icone(p, cellule, couleur, ICONES_PAGES[cle], 0.4)
            else:
                art.paint_off_pad(p, cellule, diode=False)
                p.setPen(_crayon(couleur, 1.4, 0.8))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(cellule.adjusted(1, 1, -1, -1), 5, 5)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#C8CDD5" if cle == "Samples" else "#4A515E"))
            p.drawRoundedRect(QRectF(colonne.left() + 48, y + 9, 64, 8), 3, 3)
            if rang < 10:
                _texte(p, colonne.left() + 136, y + 5, str((rang + 1) % 10),
                       _police(8, 700), "#5A6270", "droite")

        # L'en-tête de la page : son treillis, son pad, son titre.
        zone = QRectF(colonne.right() + 16, barre.bottom() + 16,
                      cadre.right() - colonne.right() - 32, 70)
        treillis = art.circuit(int(zone.width()), int(zone.height()), teinte,
                               seed=art.seed_of("Samples"), density=0.42)
        p.drawPixmap(zone, treillis, QRectF(treillis.rect()))
        _pad_icone(p, QRectF(zone.left() + 4, zone.top() + 14, 34, 34),
                   teinte, "samples", 0.45)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(PAD_WHITE))
        p.drawRoundedRect(QRectF(zone.left() + 50, zone.top() + 18, 150, 12),
                          3, 3)
        p.setBrush(QColor("#5A6270"))
        p.drawRoundedRect(QRectF(zone.left() + 50, zone.top() + 38, 210, 7),
                          3, 3)
        actions = QRectF(zone.left(), zone.bottom() + 8, zone.width(), 26)
        for rang in range(6):
            x = actions.left() + rang * 84
            if rang == 0:
                art.paint_glow(p, QRectF(x, actions.top(), 76, 24), teinte,
                               0.3)
                _boite(p, QRectF(x, actions.top(), 76, 24), teinte, rayon=6)
            else:
                _boite(p, QRectF(x, actions.top(), 76, 24), "#1B212B",
                       "#333B48", rayon=6)

        # Les panneaux de la page.
        corps = QRectF(zone.left(), actions.bottom() + 12, zone.width(),
                       colonne.bottom() - actions.bottom() - 24)
        gauche = QRectF(corps.left(), corps.top(), 150, corps.height())
        droite = QRectF(gauche.right() + 10, corps.top(),
                        corps.width() - 160, corps.height() * 0.56)
        bas = QRectF(droite.left(), droite.bottom() + 10, droite.width(),
                     corps.bottom() - droite.bottom() - 10)
        for panneau in (gauche, droite, bas):
            _boite(p, panneau, PANEL, "#2A3240", rayon=8)
        for rang in range(7):
            y = droite.top() + 12 + rang * 20
            if y + 8 > droite.bottom():
                break
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(teinte if rang == 2 else "#3A414D"))
            p.drawRoundedRect(QRectF(droite.left() + 12, y, 8, 8), 2, 2)
            p.setBrush(QColor("#4A515E"))
            p.drawRoundedRect(QRectF(droite.left() + 28, y + 1,
                                     120 + (rang * 37) % 90, 6), 3, 3)
        onde = QPainterPath(QPointF(bas.left() + 14, bas.center().y()))
        for i in range(1, 160):
            x = bas.left() + 14 + i * (bas.width() - 28) / 159.0
            amplitude = math.exp(-i / 70.0) * (bas.height() * 0.32)
            onde.lineTo(x, bas.center().y() + math.sin(i * 0.9) * amplitude)
        p.setPen(_crayon(teinte, 1.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(onde)

        # La barre d'état.
        etat = QRectF(cadre.left(), cadre.bottom() - 26, cadre.width(), 26)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#0E1218"))
        p.drawRoundedRect(etat, 10, 10)
        p.drawRect(QRectF(etat.left(), etat.top(), etat.width(), 12))
        p.setBrush(QColor("#4A515E"))
        p.drawRoundedRect(QRectF(etat.left() + 14, etat.top() + 10, 180, 6),
                          3, 3)
        p.drawRoundedRect(QRectF(etat.right() - 110, etat.top() + 10, 90, 6),
                          3, 3)

        # Les repères.
        reperes = (
            (1, (colonne.left() + 25, colonne.top() + 160), (40, 260)),
            (2, (barre.left() + 175, barre.top() + 23), (245, 18)),
            (3, (ecran.center().x(), ecran.top()), (ecran.center().x(), 18)),
            (4, (barre.left() + 592, barre.top() + 15), (662, 18)),
            (5, (barre.left() + 672, barre.top() + 10), (720, 18)),
            (6, (bouton.center().x(), bouton.top()), (bouton.center().x(),
                                                       18)),
            (7, (lecture.right(), lecture.center().y()), (958, 63)),
            (8, (cadre.right() - 40, barre.bottom() + 1.5), (958, 120)),
            (9, (zone.right() - 30, zone.top() + 30), (958, 190)),
            (10, (etat.right() - 60, etat.center().y()), (958, 548)),
        )
        for nombre, cible, pastille in reperes:
            _repere(p, nombre, cible, pastille)
    return _t.image


def _pages(libelles: list[str]) -> QImage:
    """Les onze pages, chacune à la couleur de son pad, et leur raccourci :
    ``Ctrl+1`` à ``Ctrl+0``, puis ``Ctrl+,`` pour les Réglages."""
    largeur, hauteur = 1000.0, 200.0
    with _Toile(largeur, hauteur) as (p, _t):
        pas = largeur / float(len(ORDRE_PAGES))
        for rang, cle in enumerate(ORDRE_PAGES):
            cx = pas * rang + pas / 2.0
            cellule = QRectF(cx - 28, 22, 56, 56)
            _pad_icone(p, cellule, PAGE_COLORS[cle], ICONES_PAGES[cle], 0.42)
            _texte(p, cx, 94, _libelle(libelles, rang), _police(13, 700),
                   ENCRE, "centre", pas - 4, 2)
            _texte(p, cx, 158, "Ctrl+%d" % ((rang + 1) % 10) if rang < 10
                   else "Ctrl+,", _police(11.5, 600), ENCRE_DOUCE, "centre")
    return _t.image


def _flux(libelles: list[str]) -> QImage:
    """La carte reste dans le Deluge : copie de travail et sauvegarde."""
    largeur, hauteur = 1000.0, 490.0
    lib = lambda rang: _libelle(libelles, rang)   # noqa: E731 - lisibilité
    with _Toile(largeur, hauteur) as (p, _t):
        # Le Deluge, sa façade et sa carte.
        deluge = QRectF(40, 70, 300, 210)
        _boite(p, deluge, PANEL, "#3A414D", rayon=14, largeur=1.4)
        ecran = QRectF(deluge.left() + 18, deluge.top() + 18, 110, 34)
        _boite(p, ecran, OLED_BG, OLED_EDGE, rayon=4)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(OLED_DIM))
        p.drawRoundedRect(QRectF(ecran.left() + 8, ecran.top() + 8, 40, 4),
                          2, 2)
        p.setBrush(QColor(OLED_HI))
        p.drawRoundedRect(QRectF(ecran.left() + 8, ecran.top() + 17, 76, 8),
                          2, 2)
        tirage = random.Random(7)
        for r in range(6):
            for c in range(12):
                cellule = QRectF(deluge.left() + 18 + c * 22,
                                 deluge.top() + 66 + r * 22, 17, 17)
                if tirage.random() < 0.4:
                    art.paint_pad(p, cellule,
                                  PAD_CYCLE[tirage.randrange(12)], glow=0.0,
                                  sheen=False)
                else:
                    art.paint_off_pad(p, cellule, diode=False)
        carte = QRectF(deluge.right() - 96, deluge.top() + 18, 74, 34)
        _boite(p, carte, GOLD, rayon=4)
        _texte(p, carte.center().x(), carte.top() + 8, "SD",
               _police(10, 900), INK, "centre")
        _texte(p, deluge.center().x(), deluge.bottom() + 12, lib(0),
               _police(TITRE_FIG, 800, 1.0), ENCRE, "centre")
        _texte(p, deluge.center().x(), deluge.bottom() + 38, lib(1),
               _police(TEXTE_FIG), ENCRE_DOUCE, "centre", 300, 2)

        # La copie de travail, sur le PC.
        copie = QRectF(620, 104, 340, 128)
        _boite(p, copie, "#EAF2F4", "#145F70", rayon=12, largeur=1.6)
        _pad_icone(p, QRectF(copie.left() + 18, copie.top() + 18, 40, 40),
                   PAD_GREEN, "refresh", 0.3)
        _texte(p, copie.left() + 72, copie.top() + 18, lib(3),
               _police(TITRE_FIG, 800, 1.0), "#145F70")
        _texte(p, copie.left() + 72, copie.top() + 46, lib(4),
               _police(TEXTE_FIG), ENCRE_DOUCE, largeur=copie.width() - 86,
               lignes=3)

        # Le câble, dans les deux sens.
        _fleche(p, deluge.right() + 14, copie.center().y(),
                copie.left() - 14, copie.center().y(), PAD_GREEN, 3.0,
                deux_sens=True)
        _texte(p, (deluge.right() + copie.left()) / 2.0,
               copie.center().y() - 48, lib(2), _police(13, 700),
               "#1F6B3A", "centre", 260, 2)
        _texte(p, (deluge.right() + copie.left()) / 2.0,
               copie.center().y() + 12, lib(5), _police(11.5), ENCRE_DOUCE,
               "centre", 260, 5)

        # L'application, au-dessus de la copie.
        appli = QRectF(copie.left() + 40, 14, copie.width() - 80, 50)
        _boite(p, appli, PANEL_LO, GOLD, rayon=10, largeur=1.4)
        logo = icons.app_icon(64).pixmap(64, 64)
        p.drawPixmap(QRectF(appli.left() + 12, appli.top() + 10, 30, 30),
                     logo, QRectF(logo.rect()))
        _texte(p, appli.left() + 52, appli.top() + 13, lib(6),
               _police(13, 800, 1.0), PAD_WHITE)
        _fleche(p, appli.center().x(), appli.bottom() + 4,
                appli.center().x(), copie.top() - 4, GOLD, 2.0,
                deux_sens=True)

        # La sauvegarde, lue et jamais écrite par le travail courant.
        sauvegarde = QRectF(620, 344, 340, 128)
        _boite(p, sauvegarde, "#FDF6E3", GOLD_LO, rayon=12, largeur=1.4)
        _pad_icone(p, QRectF(sauvegarde.left() + 18, sauvegarde.top() + 18,
                             40, 40), PAD_ORANGE, "backup", 0.3)
        _texte(p, sauvegarde.left() + 72, sauvegarde.top() + 18, lib(7),
               _police(TITRE_FIG, 800, 1.0), "#8A6A12")
        _texte(p, sauvegarde.left() + 72, sauvegarde.top() + 46, lib(8),
               _police(TEXTE_FIG), ENCRE_DOUCE,
               largeur=sauvegarde.width() - 86, lignes=3)
        _fleche(p, copie.center().x() - 60, copie.bottom() + 6,
                copie.center().x() - 60, sauvegarde.top() - 6, "#8A6A12", 2.0,
                pointille=True)
        _texte(p, copie.center().x() - 72, copie.bottom() + 24, lib(9),
               _police(11.5, 600), "#8A6A12", "droite", 250, 3)
    return _t.image


def _plan(libelles: list[str]) -> QImage:
    """Rien ne s'écrit sans plan : les quatre temps d'une écriture."""
    largeur, hauteur = 1000.0, 205.0
    couleurs = (PAD_CYAN, PAD_AMBER, PAD_GREEN, PAD_ORANGE)
    icones = ("search", "list", "check", "save")
    with _Toile(largeur, hauteur) as (p, _t):
        pas = largeur / 4.0
        for rang in range(4):
            cx = pas * rang + pas / 2.0
            _pad_icone(p, QRectF(cx - 28, 18, 56, 56), couleurs[rang],
                       icones[rang], 0.4)
            _numero(p, cx - 30, 20, rang + 1, 10)
            _texte(p, cx, 88, _libelle(libelles, rang * 2),
                   _police(TITRE_FIG, 800), ENCRE, "centre", pas - 20, 1)
            _texte(p, cx, 116, _libelle(libelles, rang * 2 + 1),
                   _police(TEXTE_FIG), ENCRE_DOUCE, "centre", pas - 24, 4)
            if rang < 3:
                _fleche(p, cx + 40, 46, cx + pas - 40, 46, GREY, 1.8)
    return _t.image


def _pastille(libelles: list[str]) -> QImage:
    """Les trois états de la pastille « Deluge » de la barre du haut."""
    largeur, hauteur = 1000.0, 175.0
    etats = ((GREY, False), (GOLD, True), (PAD_GREEN, True))
    with _Toile(largeur, hauteur) as (p, _t):
        pas = largeur / 3.0
        for rang, (couleur, allume) in enumerate(etats):
            cx = pas * rang + pas / 2.0
            puce_ = QRectF(cx - 70, 22, 140, 40)
            _boite(p, puce_, "#0E1218", "#2A3240", rayon=20)
            led = QRectF(puce_.left() + 14, puce_.top() + 12, 16, 16)
            if allume:
                art.paint_pad(p, led, couleur, glow=0.6, radius=8)
            else:
                art.paint_off_pad(p, led, diode=False, radius=8)
            _texte(p, puce_.left() + 40, puce_.top() + 11, "DELUGE",
                   _police(10, 800, 1.4),
                   PAD_WHITE if allume else "#7A828F")
            _texte(p, cx, 74, _libelle(libelles, rang * 2),
                   _police(TITRE_FIG, 800), ENCRE, "centre", pas - 20)
            _texte(p, cx, 102, _libelle(libelles, rang * 2 + 1),
                   _police(TEXTE_FIG), ENCRE_DOUCE, "centre", pas - 30, 3)
    return _t.image


def _sante(libelles: list[str]) -> QImage:
    """La note de santé, et ce que dit sa couleur."""
    largeur, hauteur = 1000.0, 200.0
    notes = ((96, PAD_GREEN), (78, GOLD), (52, PAD_ORANGE), (24, PAD_MAGENTA))
    with _Toile(largeur, hauteur) as (p, _t):
        pas = largeur / 4.0
        for rang, (note, couleur) in enumerate(notes):
            cx = pas * rang + pas / 2.0
            centre = QPointF(cx, 58)
            rayon = 38.0
            p.setPen(_crayon("#DDE1E6", 7))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(QRectF(cx - rayon, 58 - rayon, 2 * rayon, 2 * rayon),
                      225 * 16, -270 * 16)
            p.setPen(_crayon(couleur, 7))
            p.drawArc(QRectF(cx - rayon, 58 - rayon, 2 * rayon, 2 * rayon),
                      225 * 16, int(-270 * 16 * note / 100.0))
            _texte(p, centre.x(), 58 - 15, str(note), _police(18, 900),
                   ENCRE, "centre")
            _texte(p, cx, 108, _libelle(libelles, rang * 2),
                   _police(TITRE_FIG, 800), ENCRE, "centre", pas - 20)
            _texte(p, cx, 136, _libelle(libelles, rang * 2 + 1),
                   _police(TEXTE_FIG), ENCRE_DOUCE, "centre", pas - 24, 3)
    return _t.image


def _gabarit(libelles: list[str], zones: tuple, teinte: str,
             hauteur: float = 400.0) -> QImage:
    """Le plan d'une page : des zones numérotées, la légende à côté.

    ``zones`` : ``(x, y, largeur, hauteur, garni)`` en fractions de la zone
    de page ; ``garni`` dit comment la remplir (``liste``, ``onde``,
    ``arbre``, ``pads``, ``boutons``, ``curseurs``, ``rien``).
    """
    largeur = 1000.0
    with _Toile(largeur, hauteur) as (p, _t):
        page = QRectF(30, 20, 560, hauteur - 40)
        _boite(p, page.adjusted(-2, -2, 2, 2), "#2A2E37", rayon=10)
        _boite(p, page, PANEL_LO, rayon=9)
        tirage = random.Random(art.seed_of(teinte))
        for rang, (fx, fy, fl, fh, garni) in enumerate(zones):
            zone = QRectF(page.left() + 10 + fx * (page.width() - 20),
                          page.top() + 10 + fy * (page.height() - 20),
                          fl * (page.width() - 20) - 6,
                          fh * (page.height() - 20) - 6)
            _boite(p, zone, PANEL, "#2A3240", rayon=7)
            _garnir(p, zone, garni, teinte, tirage)
            _numero(p, zone.left() + 2, zone.top() + 2, rang + 1, 10)
            y = 24 + rang * ((hauteur - 40) / max(1, len(zones)))
            _numero(p, 630, y + 11, rang + 1, 12)
            _texte(p, 654, y, _libelle(libelles, rang * 2),
                   _police(TITRE_FIG, 800), ENCRE, largeur=336)
            _texte(p, 654, y + 26, _libelle(libelles, rang * 2 + 1),
                   _police(TEXTE_FIG), ENCRE_DOUCE, largeur=336, lignes=2)
    return _t.image


def _garnir(p: QPainter, zone: QRectF, garni: str, teinte: str,
            tirage: random.Random) -> None:
    """Remplit une zone de plan de page d'un motif qui dit ce qu'elle est."""
    p.setPen(Qt.PenStyle.NoPen)
    interieur = zone.adjusted(16, 16, -10, -8)
    if garni in ("liste", "arbre"):
        for rang in range(int(interieur.height() // 16)):
            y = interieur.top() + rang * 16
            retrait = (rang % 3) * 10 if garni == "arbre" else 0
            p.setBrush(QColor(teinte if rang == 1 else "#3A414D"))
            p.drawRoundedRect(QRectF(interieur.left() + retrait, y + 3, 7, 7),
                              2, 2)
            p.setBrush(QColor("#4A515E"))
            p.drawRoundedRect(QRectF(interieur.left() + retrait + 13, y + 4,
                                     min(interieur.width() - retrait - 16,
                                         40 + tirage.random() * 140), 5),
                              2, 2)
    elif garni == "onde":
        chemin = QPainterPath()
        for i in range(120):
            x = interieur.left() + i * interieur.width() / 119.0
            amplitude = math.exp(-i / 55.0) * interieur.height() * 0.40
            y = interieur.center().y() + math.sin(i * 0.8) * amplitude
            if i == 0:
                chemin.moveTo(x, y)
            else:
                chemin.lineTo(x, y)
        p.setPen(_crayon(teinte, 1.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(chemin)
    elif garni == "pads":
        colonnes = max(1, int(interieur.width() // 20))
        rangees = max(1, int(interieur.height() // 20))
        for r in range(rangees):
            for c in range(colonnes):
                cellule = QRectF(interieur.left() + c * 20,
                                 interieur.top() + r * 20, 15, 15)
                if tirage.random() < 0.35:
                    art.paint_pad(p, cellule, teinte, glow=0.0, sheen=False)
                else:
                    art.paint_off_pad(p, cellule, diode=False)
    elif garni == "boutons":
        x = interieur.left()
        premier = True
        while x + 50 < interieur.right():
            cadre = QRectF(x, interieur.top(), 50, min(20.0,
                                                      interieur.height()))
            _boite(p, cadre, teinte if premier else "#1B212B",
                   None if premier else "#333B48", rayon=5)
            premier = False
            x += 58
    elif garni == "filtres":
        recherche = QRectF(interieur.left(), interieur.top() - 4,
                           interieur.width() * 0.34, 18)
        _boite(p, recherche, "#111620", "#333B48", rayon=9)
        p.setPen(_crayon("#7A828F", 1.3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(recherche.left() + 11, recherche.center().y()),
                      4, 4)
        x = recherche.right() + 8
        for largeur_ in (70.0, 70.0):
            _boite(p, QRectF(x, recherche.top(), largeur_, 18), "#111620",
                   "#333B48", rayon=5)
            x += largeur_ + 8
        while x + 52 < interieur.right():
            case = QRectF(x, recherche.top() + 4, 10, 10)
            _boite(p, case, teinte if x < recherche.right() + 200 else
                   "#111620", "#444E5F", rayon=2)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#4A515E"))
            p.drawRoundedRect(QRectF(x + 15, recherche.top() + 7, 30, 4), 2,
                              2)
            x += 56
    elif garni == "curseurs":
        for rang in range(int(interieur.height() // 18)):
            y = interieur.top() + rang * 18 + 6
            p.setBrush(QColor("#3A414D"))
            p.drawRoundedRect(QRectF(interieur.left(), y, interieur.width(),
                                     4), 2, 2)
            curseur = interieur.left() + interieur.width() * (
                0.2 + tirage.random() * 0.6)
            p.setBrush(QColor(teinte))
            p.drawRoundedRect(QRectF(interieur.left(), y,
                                     curseur - interieur.left(), 4), 2, 2)
            p.setBrush(QColor(PAD_WHITE))
            p.drawEllipse(QPointF(curseur, y + 2), 5, 5)


def _echantillons(libelles: list[str]) -> QImage:
    teinte = PAGE_COLORS["Samples"]
    zones = ((0.0, 0.0, 1.0, 0.10, "boutons"), (0.0, 0.11, 1.0, 0.09,
                                                 "filtres"),
             (0.0, 0.21, 0.30, 0.79, "arbre"), (0.30, 0.21, 0.70, 0.45,
                                                 "liste"),
             (0.30, 0.66, 0.70, 0.34, "onde"))
    return _gabarit(libelles, zones, teinte, 430)


def _generateur(libelles: list[str]) -> QImage:
    teinte = PAGE_COLORS["Generator"]
    zones = ((0.0, 0.0, 1.0, 0.10, "boutons"), (0.0, 0.11, 0.30, 0.89,
                                                 "curseurs"),
             (0.30, 0.11, 0.45, 0.89, "onde"), (0.75, 0.11, 0.25, 0.89,
                                                "liste"))
    return _gabarit(libelles, zones, teinte, 400)


def _atelier(libelles: list[str]) -> QImage:
    """L'atelier : les cinq étapes en chaîne, la grille des sections, et
    les trois chemins vers le Deluge."""
    largeur, hauteur = 1000.0, 500.0
    icones = ("dice", "synth", "grid", "song", "save")
    # Les couleurs des parties, celles de la page : batterie, basse,
    # accords, mélodie.
    parties = (PAD_GREEN, PAD_BLUE, PAD_PURPLE, PAD_ORANGE)
    grille = ("BAACB", " AAAB", "AAAAA", "  AA ")
    sorties = ((PAD_CYAN, "midi"), (PAD_AMBER, "save"), (PAD_MINT, "plus"))
    nombre = len(COULEURS_ETAPES)
    with _Toile(largeur, hauteur) as (p, _t):
        pas = largeur / float(nombre)
        for rang, (couleur, icone) in enumerate(zip(COULEURS_ETAPES,
                                                    icones)):
            cx = pas * rang + pas / 2.0
            _pad_icone(p, QRectF(cx - 26, 18, 52, 52), couleur, icone, 0.4)
            _numero(p, cx - 28, 20, rang + 1, 10)
            _texte(p, cx, 84, _libelle(libelles, rang * 2),
                   _police(TITRE_FIG, 800), ENCRE, "centre", pas - 16, 1)
            _texte(p, cx, 110, _libelle(libelles, rang * 2 + 1),
                   _police(TEXTE_FIG), ENCRE_DOUCE, "centre", pas - 18, 4)
            if rang < nombre - 1:
                _fleche(p, cx + 36, 44, cx + pas - 36, 44, GREY, 1.8)
        p.setPen(_crayon("#DDD8CF", 1.0))
        p.drawLine(QPointF(30, 226), QPointF(largeur - 30, 226))

        # La grille : une rangée par piste, une colonne par section.
        _texte(p, 40, 240, _libelle(libelles, 10), _police(TITRE_FIG, 800),
               ENCRE, largeur=480)
        gauche, haut, case_l, case_h, ecart = 70.0, 276.0, 80.0, 26.0, 6.0
        for colonne in range(5):
            entete = QRectF(gauche + colonne * (case_l + ecart), haut,
                            case_l, 20)
            _boite(p, entete, CARTOUCHE, GOLD if colonne == 0 else "#3A414D",
                   rayon=5, largeur=1.4 if colonne == 0 else 1.0)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(OLED_DIM if colonne else OLED_HI))
            p.drawRoundedRect(QRectF(entete.left() + 12, entete.top() + 8,
                                     case_l * 0.45, 4), 2, 2)
        for rangee, (couleur, motif) in enumerate(zip(parties, grille)):
            y = haut + 32 + rangee * (case_h + ecart)
            art.paint_pad(p, QRectF(42, y + 6, 14, 14), couleur, glow=0.0,
                          radius=3, sheen=False)
            for colonne, lettre in enumerate(motif):
                case = QRectF(gauche + colonne * (case_l + ecart), y,
                              case_l, case_h)
                if lettre == " ":
                    # Une case muette : la piste se tait dans la section.
                    _boite(p, case, "#EFEBE4", "#D9D3C8", rayon=6)
                    continue
                art.paint_pad(p, case, couleur, glow=0.0, radius=6,
                              sheen=False)
                _texte(p, case.center().x(), case.top() + 4, lettre,
                       _police(12.0, 800), lit_fill(couleur)[2], "centre")
        _texte(p, 40, 442, _libelle(libelles, 11), _police(TEXTE_FIG),
               ENCRE_DOUCE, largeur=480, lignes=2)

        # Les trois chemins vers la machine.
        droite = gauche + 5 * (case_l + ecart)
        for rang, (couleur, icone) in enumerate(sorties):
            y = 244 + rang * 84
            _pad_icone(p, QRectF(620, y, 44, 44), couleur, icone, 0.3)
            _fleche(p, droite + 6, 360, 612, y + 22, GREY, 1.4)
            _texte(p, 678, y, _libelle(libelles, 12 + rang * 2),
                   _police(TITRE_FIG, 800), ENCRE, largeur=300)
            _texte(p, 678, y + 24, _libelle(libelles, 13 + rang * 2),
                   _police(TEXTE_FIG), ENCRE_DOUCE, largeur=300, lignes=2)
    return _t.image


def _ecrans(libelles: list[str]) -> QImage:
    """L'écran de la barre du haut, dans ses trois états principaux."""
    largeur, hauteur = 1000.0, 175.0
    styles = ((OLED_DIM, "#FFFFFF"), (PAD_AMBER, "#FFFFFF"),
              (PAD_AMBER, "#FFFFFF"))
    with _Toile(largeur, hauteur) as (p, _t):
        pas = largeur / 3.0
        for rang, (petit, grand) in enumerate(styles):
            cx = pas * rang + pas / 2.0
            ecran = QRectF(cx - 150, 16, 300, 66)
            _boite(p, ecran.adjusted(-3, -3, 3, 3), "#0E1218", rayon=8)
            _boite(p, ecran, OLED_BG, OLED_EDGE, rayon=6)
            _texte(p, ecran.left() + 14, ecran.top() + 9,
                   _libelle(libelles, rang * 3), _police(10, 700, 1.0),
                   petit, largeur=ecran.width() - 28)
            _texte(p, ecran.left() + 14, ecran.top() + 30,
                   _libelle(libelles, rang * 3 + 1), _police(15, 800, 0.5),
                   grand, largeur=ecran.width() - 28)
            _texte(p, cx, 96, _libelle(libelles, rang * 3 + 2),
                   _police(TEXTE_FIG), ENCRE_DOUCE, "centre", pas - 24, 3)
    return _t.image


def _boucle(libelles: list[str]) -> QImage:
    """Une boucle découpée : les coupes sur l'onde, un pad par tranche."""
    largeur, hauteur = 1000.0, 250.0
    teinte = PAGE_COLORS["Samples"]
    with _Toile(largeur, hauteur) as (p, _t):
        onde = QRectF(40, 20, 600, 120)
        _boite(p, onde, PANEL_LO, "#2A3240", rayon=8)
        tirage = random.Random(11)
        attaques = [0.0, 0.11, 0.24, 0.37, 0.5, 0.61, 0.75, 0.87]
        chemin = QPainterPath()
        for i in range(600):
            t = i / 599.0
            depuis = max(a for a in attaques if a <= t + 1e-9)
            enveloppe = math.exp(-(t - depuis) * 26.0)
            y = onde.center().y() + (tirage.random() * 2 - 1) * enveloppe * 48
            x = onde.left() + 10 + t * (onde.width() - 20)
            if i == 0:
                chemin.moveTo(x, y)
            else:
                chemin.lineTo(x, y)
        p.setPen(_crayon(teinte, 0.9))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(chemin)
        for rang, a in enumerate(attaques):
            x = onde.left() + 10 + a * (onde.width() - 20)
            p.setPen(_crayon(GOLD_HI, 1.4))
            p.drawLine(QPointF(x, onde.top() + 6), QPointF(x, onde.bottom()
                                                           - 6))
            _texte(p, x + 4, onde.top() + 6, str(rang + 1), _police(10, 800),
                   GOLD_HI)
        _texte(p, onde.center().x(), onde.bottom() + 10,
               _libelle(libelles, 0), _police(13, 700), ENCRE, "centre",
               onde.width())

        # Le kit : un pad par tranche, tous sur le même fichier.
        kit = QRectF(700, 20, 260, 120)
        _boite(p, kit, PANEL, "#2A3240", rayon=8)
        for rang in range(8):
            c, r = rang % 4, rang // 4
            cellule = QRectF(kit.left() + 22 + c * 58, kit.top() + 14 + r * 52,
                             42, 42)
            art.paint_pad(p, cellule, PAD_CYCLE[(rang * 3) % 12], glow=0.25)
            _texte(p, cellule.center().x(), cellule.top() + 12,
                   str(rang + 1), _police(10, 900), INK, "centre")
        _texte(p, kit.center().x(), kit.bottom() + 10, _libelle(libelles, 1),
               _police(13, 700), ENCRE, "centre", kit.width() + 60)
        _fleche(p, onde.right() + 8, onde.center().y(), kit.left() - 8,
                onde.center().y(), GREY, 1.8)
        _texte(p, largeur / 2.0, 196, _libelle(libelles, 2),
               _police(TEXTE_FIG),
               ENCRE_DOUCE, "centre", 860, 2)
    return _t.image


#: Les figures, et combien de libellés chacune attend.
FIGURES: dict[str, tuple[Callable[[list[str]], QImage], int]] = {
    "fenetre": (_fenetre, 0),
    "pages": (_pages, 11),
    "flux": (_flux, 10),
    "plan": (_plan, 8),
    "pastille": (_pastille, 6),
    "sante": (_sante, 8),
    "echantillons": (_echantillons, 10),
    "generateur": (_generateur, 8),
    "atelier": (_atelier, 18),
    "ecrans": (_ecrans, 9),
    "boucle": (_boucle, 3),
}


def figure(nom: str, libelles: list[str]) -> QImage:
    """La figure ``nom``, avec ses libellés ; une image vide si elle
    n'existe pas ou ne se dessine pas — un dessin manqué ne doit pas priver
    le lecteur du texte qui l'entoure."""
    entree = FIGURES.get(nom)
    if entree is None:
        log.warning("figure inconnue dans le manuel : %s", nom)
        return QImage()
    try:
        return entree[0](list(libelles))
    except Exception:                   # noqa: BLE001 - un dessin ne casse rien
        log.exception("figure %s impossible à dessiner", nom)
        return QImage()
