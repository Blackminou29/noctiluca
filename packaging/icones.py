# -*- coding: utf-8 -*-
"""Les images des paquets, tirées du dessin même de l'application.

L'emblème n'existe dans aucun fichier : ``delugeapp.ui.icons.app_icon`` le
trace à la taille demandée. Ce script le rend à chaque taille qu'attend un
système — un tracé par taille, net jusqu'au 16 × 16 de la barre des
tâches — et les réunit :

* ``noctiluca.ico``  : Windows (l'exécutable, l'installateur, le
  désinstallateur) ;
* ``noctiluca.icns`` : macOS ;
* ``noctiluca.png``  : Linux (512 × 512) ;
* ``installateur.bmp`` : le bandeau des pages d'accueil et de fin de
  l'installateur Windows, dans la typographie de l'écran de démarrage.

Usage :

    python packaging/icones.py DOSSIER

La configuration est déplacée dans un dossier temporaire **avant** l'import
de ``delugeapp`` : ``delugeapp.config`` calcule ses chemins à l'import, et
renommerait sinon les dossiers de l'ancien nom chez qui construit.
"""

from __future__ import annotations

import io
import os
import shutil
import sys
import tempfile
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent

#: Les tailles d'une icône Windows, et celles d'une icône macOS.
TAILLES_ICO = (16, 20, 24, 32, 40, 48, 64, 128, 256)
TAILLES_ICNS = (16, 32, 64, 128, 256, 512, 1024)

#: Le bandeau des pages d'accueil et de fin d'un installateur NSIS
#: (``MUI_WELCOMEFINISHPAGE_BITMAP``), en pixels.
BANDEAU = (164, 314)


def _isoler() -> str:
    """Rend le dossier de configuration temporaire, à effacer ensuite."""
    dossier = tempfile.mkdtemp(prefix="noctiluca-icones-")
    os.environ["NOCTILUCA_CONFIG"] = dossier
    # La plateforme « offscreen » n'a pas de polices sous Windows : le nom du
    # bandeau sortait en carrés. Elle ne sert que sur un Linux sans écran
    # (la construction automatique), où elle lit les polices du système.
    if sys.platform.startswith("linux") and not (
            os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(RACINE))
    return dossier


def _image(pixmap):
    """Un ``QPixmap`` en image Pillow RGBA."""
    from PIL import Image
    from PyQt6.QtCore import QBuffer, QIODevice

    tampon = QBuffer()
    tampon.open(QIODevice.OpenModeFlag.WriteOnly)
    pixmap.save(tampon, "PNG")
    return Image.open(io.BytesIO(bytes(tampon.data()))).convert("RGBA")


def _emblemes(tailles) -> dict[int, object]:
    from delugeapp.ui import icons

    return {t: _image(icons.app_icon(t).pixmap(t, t)) for t in tailles}


def _bandeau(chemin: Path) -> None:
    """Le bandeau de l'installateur : le treillis, l'emblème, le nom.

    Rien n'y dépend de la langue : il sert aux deux installateurs, français
    et anglais.
    """
    from PyQt6.QtCore import QPointF, QRectF, Qt
    from PyQt6.QtGui import (QColor, QFont, QImage, QLinearGradient,
                             QPainter)

    from delugeapp import __version__
    from delugeapp.ui import art, icons
    from delugeapp.ui.theme import FONT_UI, PAD_MAGENTA, TEXT_SOFT

    largeur, hauteur = BANDEAU
    haut, bas = QColor("#0B0D11"), QColor("#171B23")

    def fond_a(y: float) -> QColor:
        """La couleur du fond à la hauteur ``y`` : le voile doit s'y fondre,
        sans laisser de ligne au pied du treillis."""
        t = y / hauteur
        return QColor(*(round(a + t * (b - a)) for a, b in (
            (haut.red(), bas.red()), (haut.green(), bas.green()),
            (haut.blue(), bas.blue()))))

    image = QImage(largeur, hauteur, QImage.Format.Format_RGB32)
    p = QPainter(image)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        fond = QLinearGradient(QPointF(0, 0), QPointF(0, hauteur))
        fond.setColorAt(0.0, haut)
        fond.setColorAt(1.0, bas)
        p.fillRect(QRectF(0, 0, largeur, hauteur), fond)

        p.setOpacity(0.9)
        p.drawPixmap(QPointF(0, 0), art.circuit(
            largeur, 132, PAD_MAGENTA, art.seed_of("Deluge"), 1.0,
            density=0.55, fade=(0.0, 0.0)))
        p.setOpacity(1.0)
        voile = QLinearGradient(QPointF(0, 84), QPointF(0, 134))
        transparent = fond_a(84)
        transparent.setAlpha(0)
        voile.setColorAt(0.0, transparent)
        voile.setColorAt(1.0, fond_a(134))
        p.fillRect(QRectF(0, 84, largeur, 50), voile)

        cote = 76
        p.drawPixmap(QRectF((largeur - cote) / 2, 134, cote, cote).toRect(),
                     icons.app_icon(cote * 2).pixmap(cote * 2, cote * 2))

        def police(points, poids, espacement=0.0):
            f = QFont(FONT_UI)
            f.setPointSizeF(points)
            f.setWeight(QFont.Weight(poids))
            if espacement:
                f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing,
                                   espacement)
            return f

        centre = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
        p.setFont(police(13.5, 800, 1.2))
        p.setPen(QColor(PAD_MAGENTA))
        p.drawText(QRectF(0, 220, largeur, 30), centre, "NOCTILUCA")
        p.fillRect(QRectF((largeur - 56) / 2, 251, 56, 2), QColor(PAD_MAGENTA))
        p.setFont(police(5.5, 600, 2.4))
        p.setPen(QColor(TEXT_SOFT))
        p.drawText(QRectF(0, 264, largeur, 14), centre, "SYNTHSTROM DELUGE")
        p.setFont(police(5.5, 700, 2.4))
        p.setPen(QColor(PAD_MAGENTA))
        p.drawText(QRectF(0, 284, largeur, 14), centre,
                   f"VERSION {__version__}")
    finally:
        p.end()
    # NSIS ne lit que le BMP 24 bits.
    if not image.convertToFormat(QImage.Format.Format_RGB888).save(
            str(chemin), "BMP"):
        raise SystemExit(f"bandeau non écrit : {chemin}")


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        sys.stderr.write(__doc__.split("Usage :")[1].split("La config")[0])
        return 2
    configuration = _isoler()
    try:
        return _ecrire(Path(argv[0]))
    finally:
        shutil.rmtree(configuration, ignore_errors=True)


def _ecrire(sortie: Path) -> int:
    sortie.mkdir(parents=True, exist_ok=True)

    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])  # noqa: F841 - les QPixmap l'exigent

    ico = _emblemes(TAILLES_ICO)
    plus_grande = ico[max(TAILLES_ICO)]
    plus_grande.save(sortie / "noctiluca.ico", format="ICO",
                     sizes=[(t, t) for t in TAILLES_ICO],
                     append_images=[ico[t] for t in TAILLES_ICO[:-1]])

    icns = _emblemes(TAILLES_ICNS)
    icns[1024].save(sortie / "noctiluca.icns", format="ICNS",
                    append_images=[icns[t] for t in TAILLES_ICNS[:-1]])
    icns[512].save(sortie / "noctiluca.png")

    _bandeau(sortie / "installateur.bmp")
    for nom in ("noctiluca.ico", "noctiluca.icns", "noctiluca.png",
                "installateur.bmp"):
        print(f"{sortie / nom}  ({(sortie / nom).stat().st_size} octets)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
