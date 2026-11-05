# -*- coding: utf-8 -*-
"""La façade : les pièces de la fenêtre qui imitent la machine.

* :class:`Wordmark` — le logotype, composé comme la couverture du guide :
  l'emblème, « NOCTILUCA » en magenta, « POUR DELUGE » en capitales
  espacées ;
* :class:`OledDisplay` — l'écran du Deluge dans la barre du haut. Il dit
  quelle carte est ouverte et, comme la machine affiche ses messages en
  surimpression, il reprend un instant chaque message de la barre d'état —
  en le faisant défiler s'il est trop long, comme l'OLED du Deluge ;
* :class:`NavPad` — un pad de la colonne de navigation : éteint, il garde
  la couleur de sa page en veilleuse ; choisi, il s'allume et rayonne ;
* :class:`LedButton` — un bouton rond de façade qui s'allume (lecture,
  liaison avec le Deluge) ;
* :class:`LedStrip` — le filet lumineux sous la barre du haut, à la couleur
  de la page affichée ;
* :class:`DropVeil` — le voile qui couvre la fenêtre quand on y glisse des
  fichiers à envoyer au Deluge ;
* :class:`LevelSwitch` — la bascule « SIMPLE | AVANCÉ » de la barre du haut ;
* :class:`RailGroup` — le titre d'un groupe de la colonne : CRÉER,
  BIBLIOTHÈQUE, LA CARTE.

Tout est tracé au :class:`QPainter` : ces pièces n'ont pas d'équivalent
dans les styles de Qt, et le QSS ne sait dessiner ni halo ni dégradé radial
sur un texte.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import (
    QEasingCurve,
    QPointF,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PyQt6.QtGui import (QBrush, QColor, QFont, QFontMetricsF,
                         QLinearGradient, QPainter, QPen)
from PyQt6.QtWidgets import QPushButton, QSizePolicy, QWidget

from ...i18n import tr
from .. import art, icons
from ..theme import (
    BORDER,
    BORDER_HI,
    CHROME,
    FONT_MONO,
    FONT_UI,
    GREY,
    GREY_LIGHT,
    OLED_BG,
    OLED_DIM,
    OLED_EDGE,
    OLED_FG,
    OLED_HI,
    PAD_AMBER,
    PAD_GREEN,
    PAD_MAGENTA,
    PAD_RED,
    PAD_WHITE,
    PANEL_HI,
    TEXT_MUTED,
    TEXT_SOFT,
    mix,
    readable,
    text_on,
)

log = logging.getLogger(__name__)


def _police(famille: str, points: float, poids: int = 400,
            espacement: float = 0.0, capitales: bool = False) -> QFont:
    """Police de tracé, réglée une fois pour toutes."""
    police = QFont(famille)
    police.setPointSizeF(points)
    police.setWeight(QFont.Weight(poids))
    if espacement:
        police.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, espacement)
    if capitales:
        police.setCapitalization(QFont.Capitalization.AllUppercase)
    return police


# --------------------------------------------------------------------------- #
# Logotype
# --------------------------------------------------------------------------- #

class Wordmark(QWidget):
    """L'emblème et le nom, tels que la couverture du guide les compose.

    En fenêtre étroite, « POUR DELUGE » s'efface et il ne reste que l'emblème
    et « NOCTILUCA » : la place va aux menus et à la recherche.
    """

    #: Le nom, en grand et en magenta : un nom propre, le même partout.
    NOM = "NOCTILUCA"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._compact = False
        self._nom = _police(FONT_UI, 13.5, 900, 1.6)
        self._suite = _police(FONT_UI, 7.2, 700, 3.0)
        #: La machine qu'il sert, en petit.
        self._legende = tr("POUR DELUGE")
        self.setSizePolicy(QSizePolicy.Policy.Fixed,
                           QSizePolicy.Policy.Preferred)
        self.setToolTip(tr("Noctiluca — la carte SD de votre "
                           "Deluge, ses sons et ses outils"))

    def set_compact(self, compact: bool) -> None:
        """Masque ou montre « POUR DELUGE »."""
        compact = bool(compact)
        if compact != self._compact:
            self._compact = compact
            self.updateGeometry()
            self.update()

    def is_compact(self) -> bool:
        return self._compact

    def sizeHint(self) -> QSize:  # noqa: N802 - API Qt
        largeur = 40 + QFontMetricsF(self._nom).horizontalAdvance(self.NOM)
        if not self._compact:
            largeur += 10 + QFontMetricsF(self._suite).horizontalAdvance(
                self._legende)
        return QSize(int(largeur) + 10, 40)

    def paintEvent(self, event) -> None:  # noqa: N802 - API Qt
        try:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            milieu = self.height() / 2.0
            p.drawPixmap(QRectF(2, milieu - 15, 30, 30).toRect(),
                         icons.app_icon(64).pixmap(64, 64))
            x = 40.0
            metrique = QFontMetricsF(self._nom)
            ligne = milieu + (metrique.ascent() - metrique.descent()) / 2.0
            p.setFont(self._nom)
            p.setPen(QColor(PAD_MAGENTA))
            p.drawText(QPointF(x, ligne), self.NOM)
            if not self._compact:
                x += metrique.horizontalAdvance(self.NOM) + 10
                p.setFont(self._suite)
                p.setPen(QColor(TEXT_SOFT))
                p.drawText(QPointF(x, ligne - 0.5), self._legende)
            p.end()
        except Exception as exc:        # noqa: BLE001 - un décor ne casse rien
            log.debug("logotype non tracé : %s", exc)


# --------------------------------------------------------------------------- #
# L'écran OLED
# --------------------------------------------------------------------------- #

class OledDisplay(QPushButton):
    """L'écran du Deluge, dans la barre du haut.

    Deux lignes, comme la machine : en haut une étiquette en petites
    capitales (« CARTE »), en dessous l'information en grand (« SDCARD
    DELUGE »). Un message — :meth:`flash` — prend la grande ligne quelques
    secondes et défile s'il est trop long.

    Reste un ``QPushButton`` : un clic mène aux réglages de la carte, et son
    texte (:meth:`text`) garde le libellé complet que la fenêtre y pose.
    """

    #: Tons de la grande ligne : cyan de l'écran, ambre, rouge, blanc.
    TONS = {"hi": OLED_HI, "warn": PAD_AMBER, "error": PAD_RED,
            "fg": OLED_FG, "dim": OLED_DIM}

    #: Durée d'un message par défaut, en millisecondes.
    FLASH_MS = 4500

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFlat(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._largeur = 300
        self.setFixedHeight(40)
        self._haut = "CARTE"
        self._ligne = ""
        self._ton = "hi"
        self._message = ""
        self._decalage = 0.0
        self._survol = False

        self._petite = _police(FONT_UI, 6.8, 700, 2.2, capitales=True)
        self._grande = _police(FONT_MONO, 10.5, 700)

        self._fin_message = QTimer(self)
        self._fin_message.setSingleShot(True)
        self._fin_message.timeout.connect(self._effacer_message)
        self._defilement = QTimer(self)
        self._defilement.setInterval(40)
        self._defilement.timeout.connect(self._defiler)

    # -- contenu ------------------------------------------------------------ #

    def set_display(self, haut: str, ligne: str, ton: str = "hi") -> None:
        """Change l'étiquette et la ligne principale."""
        self._haut = str(haut or "")
        self._ligne = str(ligne or "")
        self._ton = ton if ton in self.TONS else "hi"
        self.update()

    def display(self) -> tuple[str, str, str]:
        """``(étiquette, ligne, ton)`` affichés hors message."""
        return self._haut, self._ligne, self._ton

    def flash(self, message: str, ms: int | None = None) -> None:
        """Affiche un message sur la grande ligne, quelques secondes."""
        texte = " ".join(str(message or "").split())
        if not texte:
            self._effacer_message()
            return
        self._message = texte
        self._decalage = 0.0
        duree = self.FLASH_MS if ms is None or ms <= 0 else min(int(ms),
                                                                self.FLASH_MS)
        # Un message qui défile doit avoir le temps d'être lu en entier.
        if self._deborde():
            duree = max(duree, int(self._exces() / 0.05) + 2200)
            self._defilement.start()
        else:
            self._defilement.stop()
        self._fin_message.start(duree)
        self.update()

    def message(self) -> str:
        """Message en cours d'affichage, ou chaîne vide."""
        return self._message

    def _effacer_message(self) -> None:
        self._message = ""
        self._decalage = 0.0
        self._defilement.stop()
        self.update()

    # -- défilement --------------------------------------------------------- #

    def _zone_texte(self) -> QRectF:
        return QRectF(self.rect()).adjusted(14, 4, -14, -4)

    def _exces(self) -> float:
        largeur = QFontMetricsF(self._grande).horizontalAdvance(self._message)
        return max(0.0, largeur - self._zone_texte().width())

    def _deborde(self) -> bool:
        return self._exces() > 0.5

    def _defiler(self) -> None:
        exces = self._exces()
        if exces <= 0:
            self._defilement.stop()
            return
        # Une pause au début, le défilement, une pause à la fin : 2 px par
        # pas de 40 ms, la vitesse d'un texte qu'on lit en le suivant.
        self._decalage += 2.0
        if self._decalage > exces + 60:
            self._decalage = -40.0
        self.update()

    # -- géométrie ---------------------------------------------------------- #

    def set_preferred_width(self, largeur: int) -> None:
        largeur = max(150, int(largeur))
        if largeur != self._largeur:
            self._largeur = largeur
            self.setFixedWidth(largeur)
            self.updateGeometry()

    def sizeHint(self) -> QSize:  # noqa: N802 - API Qt
        return QSize(self._largeur, 40)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - API Qt
        return QSize(150, 40)

    def enterEvent(self, event) -> None:  # noqa: N802 - API Qt
        self._survol = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - API Qt
        self._survol = False
        self.update()
        super().leaveEvent(event)

    # -- tracé -------------------------------------------------------------- #

    def paintEvent(self, event) -> None:  # noqa: N802 - API Qt
        try:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            cadre = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

            # Le cadre de l'écran, puis la dalle noire en retrait.
            p.setPen(QPen(QColor(BORDER_HI if self._survol else BORDER), 1))
            p.setBrush(QColor(mix(CHROME, PANEL_HI, 0.5)))
            p.drawRoundedRect(cadre, 9, 9)
            dalle = cadre.adjusted(3, 3, -3, -3)
            p.setPen(QPen(QColor(OLED_EDGE), 1))
            p.setBrush(QColor(OLED_BG))
            p.drawRoundedRect(dalle, 6, 6)

            # Une trame de lignes très fines : on devine les pixels.
            trame = QColor(OLED_HI)
            trame.setAlphaF(0.035)
            p.setPen(QPen(trame, 1))
            y = dalle.top() + 2
            while y < dalle.bottom() - 1:
                p.drawLine(QPointF(dalle.left() + 3, y),
                           QPointF(dalle.right() - 3, y))
                y += 3

            zone = self._zone_texte()
            p.save()
            p.setClipRect(dalle.adjusted(4, 1, -4, -1))
            # Petite ligne : l'étiquette, ou la carte quand un message passe.
            p.setFont(self._petite)
            p.setPen(QColor(OLED_DIM))
            haut = self._haut
            if self._message:
                haut = self._ligne or self._haut
            metrique = QFontMetricsF(self._petite)
            p.drawText(QPointF(zone.left(), zone.top() + metrique.ascent() + 1),
                       metrique.elidedText(haut, Qt.TextElideMode.ElideRight,
                                           zone.width()))

            # Grande ligne : l'information, ou le message qui défile.
            p.setFont(self._grande)
            grande = QFontMetricsF(self._grande)
            base = zone.bottom() - grande.descent() - 1
            if self._message:
                p.setPen(QColor(OLED_FG))
                x = zone.left() - max(0.0, min(self._decalage, self._exces()))
                p.drawText(QPointF(x, base), self._message)
            else:
                couleur = QColor(self.TONS.get(self._ton, OLED_HI))
                p.setPen(couleur)
                p.drawText(QPointF(zone.left(), base),
                           grande.elidedText(self._ligne,
                                             Qt.TextElideMode.ElideMiddle,
                                             zone.width()))
            p.restore()
            p.end()
        except Exception as exc:        # noqa: BLE001 - un décor ne casse rien
            log.debug("écran OLED non tracé : %s", exc)


# --------------------------------------------------------------------------- #
# Les pads de navigation
# --------------------------------------------------------------------------- #

class NavPad(QPushButton):
    """Un pad de la colonne de navigation.

    Éteint, il garde sa couleur en veilleuse — comme les pads d'un clip sur
    la machine, qui montrent leur teinte avant même d'être joués. Choisi, il
    s'allume, rayonne, et un filet de sa couleur borde la colonne. Le
    numéro à droite est celui du raccourci (``Ctrl+1`` … ``Ctrl+9``, puis
    ``Ctrl+0`` pour la dixième) ; ``None`` : pas de chiffre. Le 0 de la
    dixième page ne s'affichait pas, pris pour « aucun chiffre ».

    Reste un ``QPushButton`` cochable : les tests et la fenêtre le cliquent
    et lisent son état comme avant.
    """

    #: 40 et non 44 : avec les trois titres de groupe, la colonne doit tenir
    #: dans les 557 pixels qu'une fenêtre de 640 lui laisse.
    HAUTEUR = 40

    def __init__(self, title: str, icon_name: str, color: str,
                 number: int | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(f"  {title}", parent)
        self.setObjectName("NavButton")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(self.HAUTEUR)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)
        self._icone = icon_name
        self._couleur = color
        self._numero = None if number is None else int(number)
        self._lumiere = 0.0
        self._survol = False
        self._libelle = _police(FONT_UI, 10, 500)
        self._libelle_actif = _police(FONT_UI, 10, 700)
        self._chiffre = _police(FONT_MONO, 8, 700)

        self._animation = QVariantAnimation(self)
        self._animation.setDuration(220)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._eclairer)
        self.toggled.connect(self._basculer)

    def color(self) -> str:
        return self._couleur

    def light(self) -> float:
        """Intensité de l'éclairage, de 0 (éteint) à 1 (allumé)."""
        return self._lumiere

    def _basculer(self, coche: bool) -> None:
        self._animation.stop()
        self._animation.setStartValue(float(self._lumiere))
        self._animation.setEndValue(1.0 if coche else 0.0)
        # Hors écran (tests, rendu en image), l'animation n'aurait pas lieu :
        # l'état final est posé d'emblée si la fenêtre n'est pas visible.
        if not self.isVisible():
            self._eclairer(1.0 if coche else 0.0)
            return
        self._animation.start()

    def _eclairer(self, valeur) -> None:
        try:
            self._lumiere = max(0.0, min(1.0, float(valeur)))
        except (TypeError, ValueError):
            return
        self.update()

    def enterEvent(self, event) -> None:  # noqa: N802 - API Qt
        self._survol = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - API Qt
        self._survol = False
        self.update()
        super().leaveEvent(event)

    def sizeHint(self) -> QSize:  # noqa: N802 - API Qt
        return QSize(184, self.HAUTEUR)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - API Qt
        return QSize(48, self.HAUTEUR)

    def paintEvent(self, event) -> None:  # noqa: N802 - API Qt
        try:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            large = bool(self.text().strip())
            lumiere = self._lumiere
            couleur = self._couleur

            # Bande de l'élément actif ou survolé.
            fond = 0.12 * lumiere + (0.06 if self._survol else 0.0)
            if fond > 0.005:
                bande = QRectF(self.rect()).adjusted(6, 2, -4, -2)
                teinte = QColor(couleur)
                teinte.setAlphaF(min(0.24, fond))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(teinte)
                p.drawRoundedRect(bande, 11, 11)

            # Le filet lumineux au bord de la colonne.
            if lumiere > 0.01:
                filet = QRectF(0, 9, 3, self.height() - 18)
                art.paint_glow(p, filet, couleur, 0.35 * lumiere, 0.6)
                teinte = QColor(couleur)
                teinte.setAlphaF(lumiere)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(teinte)
                p.drawRoundedRect(filet, 1.5, 1.5)

            # Le pad.
            cote = 28.0
            x = 14.0 if large else (self.width() - cote) / 2.0
            pad = QRectF(x, (self.height() - cote) / 2.0, cote, cote)
            veille = 0.55 + (0.35 if self._survol else 0.0)
            art.paint_off_pad(p, pad, diode=False, radius=7.5)
            cadre = QColor(couleur)
            cadre.setAlphaF(veille * (1.0 - lumiere))
            p.setPen(QPen(cadre, 1.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(pad.adjusted(0.6, 0.6, -0.6, -0.6), 7, 7)
            if lumiere > 0.01:
                p.save()
                p.setOpacity(lumiere)
                art.paint_pad(p, pad, couleur, glow=0.42, radius=7.5)
                p.restore()
            # L'icône : à la couleur de la page sur le pad éteint, à l'encre
            # sur le pad allumé.
            taille = 16
            icone_eteinte = icons.icon(self._icone, couleur, taille).pixmap(
                taille, taille)
            icone_allumee = icons.icon(self._icone, text_on(couleur),
                                       taille).pixmap(taille, taille)
            coin = QPointF(pad.center().x() - taille / 2,
                           pad.center().y() - taille / 2)
            p.save()
            p.setOpacity(1.0 - lumiere)
            p.drawPixmap(coin, icone_eteinte)
            p.setOpacity(lumiere)
            p.drawPixmap(coin, icone_allumee)
            p.restore()

            if large:
                actif = self.isChecked()
                p.setFont(self._libelle_actif if actif else self._libelle)
                p.setPen(QColor(PAD_WHITE if (actif or self._survol)
                                else TEXT_SOFT))
                gauche = pad.right() + 12
                droite = self.width() - (26 if self._numero is not None
                                         else 10)
                zone = QRectF(gauche, 0, max(10.0, droite - gauche),
                              self.height())
                texte = QFontMetricsF(p.font()).elidedText(
                    self.text().strip(), Qt.TextElideMode.ElideRight,
                    zone.width())
                p.drawText(zone, int(Qt.AlignmentFlag.AlignVCenter
                                     | Qt.AlignmentFlag.AlignLeft), texte)
                if self._numero is not None:
                    p.setFont(self._chiffre)
                    chiffre = QColor(readable(couleur, CHROME) if actif
                                     else (GREY if self._survol
                                           else TEXT_MUTED))
                    p.setPen(chiffre)
                    p.drawText(QRectF(self.width() - 28, 0, 18, self.height()),
                               int(Qt.AlignmentFlag.AlignVCenter
                                   | Qt.AlignmentFlag.AlignRight),
                               str(self._numero))
            p.end()
        except Exception as exc:        # noqa: BLE001 - un décor ne casse rien
            log.debug("pad de navigation non tracé : %s", exc)


# --------------------------------------------------------------------------- #
# Boutons ronds et filet
# --------------------------------------------------------------------------- #

class LedButton(QPushButton):
    """Bouton rond de façade qui s'allume.

    ``caption`` ajoute une étiquette en petites capitales à droite de la
    pastille (« DELUGE ») ; :meth:`set_caption_visible` la retire quand la
    place manque.
    """

    def __init__(self, icon_name: str, caption: str = "",
                 parent: QWidget | None = None, size: int = 34) -> None:
        super().__init__(parent)
        self.setFlat(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._icone = icon_name
        self._legende = str(caption or "")
        self._legende_visible = bool(caption)
        self._taille = int(size)
        self._couleur = GREY
        self._allume = False
        self._survol = False
        self._police = _police(FONT_UI, 7.2, 700, 2.0, capitales=True)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._ajuster()

    def _ajuster(self) -> None:
        largeur = self._taille
        if self._legende and self._legende_visible:
            largeur += 8 + int(QFontMetricsF(self._police).horizontalAdvance(
                self._legende)) + 10
        self.setFixedSize(largeur, self._taille)

    def set_icon_name(self, name: str) -> None:
        if name != self._icone:
            self._icone = name
            self.update()

    def set_state(self, color: str, lit: bool) -> None:
        """Couleur de la pastille, et si elle rayonne."""
        self._couleur = color or GREY
        self._allume = bool(lit)
        self.update()

    def state(self) -> tuple[str, bool]:
        return self._couleur, self._allume

    def set_caption_visible(self, visible: bool) -> None:
        visible = bool(visible) and bool(self._legende)
        if visible != self._legende_visible:
            self._legende_visible = visible
            self._ajuster()
            self.update()

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
            cote = float(self._taille)
            rond = QRectF(1, 1, cote - 2, cote - 2)
            if self._legende and self._legende_visible:
                pilule = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
                p.setPen(QPen(QColor(BORDER_HI if self._survol else BORDER), 1))
                p.setBrush(QColor(mix(CHROME, PANEL_HI, 0.45)))
                p.drawRoundedRect(pilule, cote / 2, cote / 2)
            if self._allume:
                art.paint_glow(p, rond.adjusted(5, 5, -5, -5), self._couleur,
                               0.40, 0.7)
            degrade = QLinearGradient(rond.topLeft(), rond.bottomLeft())
            degrade.setColorAt(0.0, QColor("#2A313D"))
            degrade.setColorAt(1.0, QColor("#1A1F28"))
            bord = (self._couleur if self._allume
                    else (BORDER_HI if self._survol else BORDER))
            p.setPen(QPen(QColor(bord), 1.4 if self._allume else 1.0))
            p.setBrush(degrade)
            p.drawEllipse(rond)
            taille = int(cote * 0.46)
            couleur = (self._couleur if (self._allume or self._survol)
                       else GREY_LIGHT)
            icone = icons.icon(self._icone, couleur, taille).pixmap(taille,
                                                                    taille)
            p.drawPixmap(QPointF(rond.center().x() - taille / 2,
                                 rond.center().y() - taille / 2), icone)
            if self._legende and self._legende_visible:
                p.setFont(self._police)
                p.setPen(QColor(readable(self._couleur, CHROME)
                                if self._allume else TEXT_SOFT))
                zone = QRectF(cote + 6, 0, self.width() - cote - 12,
                              self.height())
                p.drawText(zone, int(Qt.AlignmentFlag.AlignVCenter
                                     | Qt.AlignmentFlag.AlignLeft),
                           self._legende)
            p.end()
        except Exception as exc:        # noqa: BLE001 - un décor ne casse rien
            log.debug("bouton de façade non tracé : %s", exc)


class LevelSwitch(QPushButton):
    """La bascule du niveau de l'interface : « SIMPLE | AVANCÉ ».

    Une pilule en deux moitiés ; celle qui est choisie s'allume à la couleur
    de la façade, comme un pad. Reste un ``QPushButton`` cochable — coché :
    avancé —, que la fenêtre, le menu et les tests actionnent comme un
    autre. Son texte est le nom du niveau qu'il allume.
    """

    HAUTEUR = 30

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setFlat(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._couleur = PAD_AMBER
        self._survol = False
        self._compact = False
        self._gauche = tr("Simple")
        self._droite = tr("Avancé")
        self.setText(self._droite)
        self._ajuster()

    def _ajuster(self) -> None:
        """Largeur des deux moitiés : le plus long libellé, et sa marge.

        Serrée sous 1 180 px de fenêtre : la bascule y prend la place de
        l'ancien « Analyser », plus étroit, et les menus ne doivent pas
        passer dans le débordement.
        """
        if self._compact:
            self._police = _police(FONT_UI, 6.6, 700, 0.8, capitales=True)
            marge = 7
        else:
            self._police = _police(FONT_UI, 7.2, 700, 1.8, capitales=True)
            marge = 20
        largeur = max(QFontMetricsF(self._police).horizontalAdvance(t.upper())
                      for t in (self._gauche, self._droite))
        self._largeur = int(2 * (largeur + marge)) + 6
        self.setFixedSize(self._largeur, self.HAUTEUR)
        self.update()

    def set_compact(self, compact: bool) -> None:
        if bool(compact) != self._compact:
            self._compact = bool(compact)
            self._ajuster()

    def is_compact(self) -> bool:
        return self._compact

    def sizeHint(self) -> QSize:  # noqa: N802 - API Qt
        # La taille fixe, et non celle que Qt tirerait du texte : la barre
        # du haut compte avec elle pour savoir ce qui tient.
        return QSize(self._largeur, self.HAUTEUR)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - API Qt
        return self.sizeHint()

    def color(self) -> str:
        return self._couleur

    def set_accent(self, color: str) -> None:
        """La couleur de la moitié allumée : celle de la façade."""
        if color:
            self._couleur = color
            self.update()

    def labels(self) -> tuple[str, str]:
        return self._gauche, self._droite

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
            cadre = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            rayon = cadre.height() / 2.0
            p.setPen(QPen(QColor(BORDER_HI if self._survol else BORDER), 1))
            p.setBrush(QColor(mix(CHROME, PANEL_HI, 0.45)))
            p.drawRoundedRect(cadre, rayon, rayon)
            moitie = (cadre.width() - 6) / 2.0
            gauche = QRectF(cadre.left() + 3, cadre.top() + 3, moitie,
                            cadre.height() - 6)
            droite = QRectF(gauche.right(), gauche.top(), moitie,
                            gauche.height())
            allumee = droite if self.isChecked() else gauche
            art.paint_pad(p, allumee, self._couleur, glow=0.0,
                          radius=allumee.height() / 2.0)
            p.setFont(self._police)
            for zone, texte in ((gauche, self._gauche), (droite, self._droite)):
                choisie = zone is allumee
                p.setPen(QColor(text_on(self._couleur) if choisie
                                else (PAD_WHITE if self._survol
                                      else TEXT_SOFT)))
                p.drawText(zone, int(Qt.AlignmentFlag.AlignCenter),
                           texte.upper())
            p.end()
        except Exception as exc:        # noqa: BLE001 - un décor ne casse rien
            log.debug("bascule de niveau non tracée : %s", exc)


class RailGroup(QWidget):
    """Le titre d'un groupe de la colonne de navigation.

    Capitales espacées et filet, comme les titres de section ; replié, il
    ne reste qu'un court filet entre deux groupes de pads.
    """

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._titre = str(title or "")
        self._compact = False
        self._police = _police(FONT_UI, 6.8, 700, 2.2, capitales=True)
        self.setFixedHeight(20)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents,
                          True)

    def title(self) -> str:
        return self._titre

    def set_compact(self, compact: bool) -> None:
        self._compact = bool(compact)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - API Qt
        try:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            milieu = self.height() / 2.0 + 3.0
            trait = QColor(BORDER)
            if self._compact:
                p.setPen(QPen(trait, 1))
                p.drawLine(QPointF(14, milieu), QPointF(self.width() - 14,
                                                        milieu))
                p.end()
                return
            p.setFont(self._police)
            p.setPen(QColor(TEXT_MUTED))
            metrique = QFontMetricsF(self._police)
            x = 16.0
            ligne = milieu + (metrique.ascent() - metrique.descent()) / 2.0
            texte = self._titre.upper()
            p.drawText(QPointF(x, ligne), texte)
            fin = x + metrique.horizontalAdvance(texte) + 8
            if fin < self.width() - 10:
                degrade = QLinearGradient(QPointF(fin, 0),
                                          QPointF(self.width() - 10, 0))
                degrade.setColorAt(0.0, trait)
                transparent = QColor(trait)
                transparent.setAlphaF(0.0)
                degrade.setColorAt(1.0, transparent)
                p.setPen(QPen(QBrush(degrade), 1))
                p.drawLine(QPointF(fin, milieu), QPointF(self.width() - 10,
                                                         milieu))
            p.end()
        except Exception as exc:        # noqa: BLE001 - un décor ne casse rien
            log.debug("titre de groupe non tracé : %s", exc)


class LedStrip(QWidget):
    """Le filet lumineux sous la barre du haut, à la couleur de la page."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._couleur = PAD_AMBER
        self.setFixedHeight(3)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents,
                          True)

    def color(self) -> str:
        return self._couleur

    def set_color(self, color: str) -> None:
        if color and color != self._couleur:
            self._couleur = color
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - API Qt
        try:
            p = QPainter(self)
            largeur = float(self.width())
            degrade = QLinearGradient(QPointF(0, 0), QPointF(largeur, 0))
            pleine = QColor(self._couleur)
            douce = QColor(self._couleur)
            douce.setAlphaF(0.25)
            degrade.setColorAt(0.0, pleine)
            degrade.setColorAt(0.55, pleine)
            degrade.setColorAt(1.0, douce)
            p.fillRect(QRectF(0, 0, largeur, 2), degrade)
            halo = QColor(self._couleur)
            halo.setAlphaF(0.22)
            p.fillRect(QRectF(0, 2, largeur, 1), halo)
            p.end()
        except Exception as exc:        # noqa: BLE001
            log.debug("filet non tracé : %s", exc)


class DropVeil(QWidget):
    """Le voile qui couvre la fenêtre pendant qu'on y glisse des fichiers.

    Le treillis du guide à la couleur du Deluge connecté, un grand pad
    allumé, et en clair ce que deviendra le dépôt : « dans la copie de
    travail, puis sur le Deluge par le câble USB ». Il ne prend aucun clic ;
    c'est la fenêtre qui reçoit le dépôt.
    """

    def __init__(self, parent: QWidget | None = None,
                 color: str = PAD_GREEN) -> None:
        super().__init__(parent)
        self._couleur = color
        self._detail = ""
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents,
                          True)
        self.hide()

    def detail(self) -> str:
        return self._detail

    def show_over(self, rect, detail: str) -> None:
        """Couvre ``rect`` et dit où partira le dépôt."""
        self._detail = str(detail or "")
        self.setGeometry(rect)
        self.raise_()
        self.show()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - API Qt
        try:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            cadre = QRectF(self.rect())
            p.fillRect(cadre, QColor(10, 13, 18, 238))
            treillis = art.circuit(int(cadre.width()), int(cadre.height()),
                                   self._couleur, seed=1906,
                                   dpr=self.devicePixelRatioF(),
                                   density=0.30, fade=(0.0, 0.0))
            p.setOpacity(0.28)
            p.drawPixmap(0, 0, treillis)
            p.setOpacity(1.0)

            bord = cadre.adjusted(18, 18, -18, -18)
            stylo = QPen(QColor(self._couleur))
            stylo.setWidthF(2.0)
            stylo.setStyle(Qt.PenStyle.DashLine)
            p.setPen(stylo)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(bord, 22, 22)

            cote = 104.0
            centre = cadre.center()
            pad = QRectF(centre.x() - cote / 2, centre.y() - cote - 14,
                         cote, cote)
            art.paint_pad(p, pad, self._couleur, glow=0.55)
            encre = text_on(self._couleur)
            p.drawPixmap(pad.adjusted(26, 26, -26, -26).toRect(),
                         icons.icon("import", encre, 52).pixmap(52, 52))

            p.setPen(QColor(PAD_WHITE))
            p.setFont(_police(FONT_UI, 17, 700, 2.5, capitales=True))
            titre = QRectF(bord.left() + 24, pad.bottom() + 22,
                           bord.width() - 48, 34)
            p.drawText(titre, int(Qt.AlignmentFlag.AlignCenter),
                       tr("Déposez pour envoyer au Deluge"))
            p.setPen(QColor(GREY_LIGHT))
            p.setFont(_police(FONT_UI, 11))
            texte = QRectF(bord.left() + 40, titre.bottom() + 6,
                           bord.width() - 80, 60)
            p.drawText(texte, int(Qt.AlignmentFlag.AlignHCenter
                                  | Qt.AlignmentFlag.AlignTop
                                  | Qt.TextFlag.TextWordWrap),
                       self._detail + "\n" + tr("Le plan de l'envoi est "
                                                 "montré avant toute copie."))
            p.end()
        except Exception as exc:        # noqa: BLE001 - un décor ne casse rien
            log.debug("voile de dépôt non tracé : %s", exc)
