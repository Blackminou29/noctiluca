# -*- coding: utf-8 -*-
"""L'écran du Deluge, recopié pixel pour pixel.

La machine envoie son image en SysEx (:mod:`delugeapp.core.delugesysex`) :
128 × 48 pixels, six pages de huit lignes. Ce widget la dessine agrandie
d'un facteur **entier** — un pixel de la machine devient un carré net, comme
sur la dalle — dans la dalle noire de la façade, pixels allumés à la couleur
de l'écran du guide.
"""

from __future__ import annotations

import logging

import numpy as np
from PyQt6.QtCore import QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from ...core.delugesysex import OLED_HEIGHT, OLED_WIDTH
from ...i18n import tr
from ..theme import FONT_UI, OLED_BG, OLED_DIM, OLED_EDGE, OLED_HI

log = logging.getLogger(__name__)

__all__ = ["DelugeScreenView", "screen_bits"]


def screen_bits(pixels: bytes) -> np.ndarray:
    """L'écran en tableau ``48 × 128`` de 0 et de 1, ligne 0 en haut.

    Un octet couvre huit lignes d'une colonne, bit 0 en haut
    (``oledCurrentImage[y >> 3][x] |= 1 << (y & 7)``).
    """
    brut = np.frombuffer(bytes(pixels), dtype=np.uint8)
    if brut.size != OLED_WIDTH * OLED_HEIGHT // 8:
        return np.zeros((OLED_HEIGHT, OLED_WIDTH), dtype=np.uint8)
    pages = brut.reshape(OLED_HEIGHT // 8, 1, OLED_WIDTH)
    bits = np.unpackbits(pages, axis=1, bitorder="little")
    return bits.reshape(OLED_HEIGHT, OLED_WIDTH)


class DelugeScreenView(QWidget):
    """La dalle de l'écran, et l'image de la machine dedans."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Preferred)
        self.setMinimumSize(OLED_WIDTH * 2 + 24, OLED_HEIGHT * 2 + 24)
        self._image = QImage(OLED_WIDTH, OLED_HEIGHT,
                             QImage.Format.Format_RGB32)
        self._image.fill(QColor(OLED_BG))
        self._vide = True
        self._texte = tr("L'écran du Deluge n'est pas recopié.")
        self._allume = QColor(OLED_HI)
        self._eteint = QColor(OLED_BG)

    # -- contenu ------------------------------------------------------------ #

    def set_pixels(self, pixels: bytes) -> None:
        """Remplace l'image par celle de la machine."""
        try:
            bits = screen_bits(pixels)
            allume = self._allume.rgb() & 0xFFFFFFFF
            eteint = self._eteint.rgb() & 0xFFFFFFFF
            couleurs = np.where(bits.astype(bool), np.uint32(allume),
                                np.uint32(eteint)).astype(np.uint32)
            image = QImage(couleurs.tobytes(), OLED_WIDTH, OLED_HEIGHT,
                           OLED_WIDTH * 4, QImage.Format.Format_RGB32)
            # ``copy`` : l'image doit posséder ses octets, le tableau numpy
            # va disparaître.
            self._image = image.copy()
            self._vide = False
        except Exception as exc:        # noqa: BLE001 - une image ne casse rien
            log.debug("écran du Deluge non converti : %s", exc)
        self.update()

    def clear(self, texte: str = "") -> None:
        """Revient à la dalle vide, avec un message."""
        self._image.fill(self._eteint)
        self._vide = True
        if texte:
            self._texte = texte
        self.update()

    def is_empty(self) -> bool:
        return self._vide

    def scale(self) -> int:
        """Agrandissement entier qui tient dans le widget."""
        largeur = max(1, self.width() - 24)
        hauteur = max(1, self.height() - 24)
        return max(1, min(largeur // OLED_WIDTH, hauteur // OLED_HEIGHT))

    def sizeHint(self) -> QSize:  # noqa: N802 - API Qt
        return QSize(OLED_WIDTH * 4 + 24, OLED_HEIGHT * 4 + 24)

    def heightForWidth(self, largeur: int) -> int:  # noqa: N802 - API Qt
        echelle = max(1, (largeur - 24) // OLED_WIDTH)
        return OLED_HEIGHT * echelle + 24

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - API Qt
        return True

    # -- tracé -------------------------------------------------------------- #

    def paintEvent(self, event) -> None:  # noqa: N802 - API Qt
        try:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            echelle = self.scale()
            largeur, hauteur = OLED_WIDTH * echelle, OLED_HEIGHT * echelle
            x = (self.width() - largeur) / 2.0
            y = (self.height() - hauteur) / 2.0
            dalle = QRectF(x - 10, y - 10, largeur + 20, hauteur + 20)
            p.setPen(QPen(QColor(OLED_EDGE), 1.2))
            p.setBrush(QColor(OLED_BG))
            p.drawRoundedRect(dalle, 10, 10)
            if self._vide:
                p.setPen(QColor(OLED_DIM))
                police = QFont(FONT_UI)
                police.setPointSizeF(9.5)
                p.setFont(police)
                p.drawText(dalle, Qt.AlignmentFlag.AlignCenter
                           | Qt.TextFlag.TextWordWrap, self._texte)
            else:
                # Agrandissement au plus proche : des pixels nets.
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform,
                                False)
                p.drawImage(QRectF(x, y, largeur, hauteur), self._image)
            p.end()
        except Exception as exc:        # noqa: BLE001 - un décor ne casse rien
            log.debug("écran du Deluge non tracé : %s", exc)
