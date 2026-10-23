# -*- coding: utf-8 -*-
"""Identité graphique de Deluge Companion : « la façade ».

Reprend le *Guide du Synthstrom Deluge* de l'utilisateur, et cette fois
ses signatures, pas seulement sa palette :

* **une couleur par page**, comme chaque partie du livre a la sienne
  (I cyan, II ambre, III vert…). La page ne se contente plus d'un liseré :
  ses boutons principaux, ses sélections, ses onglets, ses cases et ses
  curseurs prennent **sa** teinte. :func:`accent_qss` fabrique cette
  feuille, que chaque page pose sur elle-même ;
* **la façade** de la machine : barre du haut et colonne de pads un cran
  plus sombres que les pages (``CHROME``), où les pads s'allument ;
* **l'écran OLED** du Deluge (figure o01 du guide) : noir profond, cyan
  vif — pour l'afficheur de la barre du haut et les infobulles ;
* **les pads** : carrés arrondis pleins, halo de leur couleur, reflet en
  haut ; au repos, cadre à l'or sourd et quatre points (voir
  :mod:`delugeapp.ui.art`).

La couleur d'accent choisie dans les réglages est désormais celle de la
**façade** : barre du haut, menus, fenêtres de dialogue ouvertes hors des
pages.

Le module fournit la palette, quelques utilitaires de couleur, la feuille de
style complète (:func:`qss`), sa partie colorée seule (:func:`accent_qss`)
et son application à une ``QApplication`` (:func:`apply_theme`). Les petites
images du QSS (chevrons, coches, puces) sont dessinées au vol et mises en
cache sur disque — aucun fichier externe n'est livré avec l'application.
"""
from __future__ import annotations

import hashlib
import logging
from string import Template

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPalette, QPen, QPolygonF

from delugeapp.config import CONFIG_DIR
from delugeapp.i18n import tr, untranslated

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Palette (identique au guide papier — ne pas modifier sans mettre à jour le guide)
# ---------------------------------------------------------------------------
INK = "#15181E"
INK_SOFT = "#3B424E"
GREY = "#7A828F"
GREY_LIGHT = "#C3C9D2"

#: Gris des **textes** secondaires, distinct de celui du décor.
#:
#: ``GREY`` tombait à 3,78 de contraste sur une surface relevée, là où la
#: norme demande 4,5 pour un texte courant — et c'est précisément la couleur
#: des sous-titres et des phrases d'explication. Quinze pour cent de clarté
#: en plus suffisent : 4,85 dans le pire cas. Les traits, bordures et icônes
#: gardent ``GREY`` : eux ont le droit d'être discrets.
TEXT_SOFT = "#8E95A0"
PAPER = "#FFFFFF"
PAPER_WARM = "#FAF8F4"

#: Trois niveaux de surface, **nettement distincts**. L'ancienne palette
#: les séparait de 12 points de luminance : panneaux et fond se confondaient,
#: et l'écran entier paraissait d'un seul gris. Le fond descend, les
#: panneaux montent.
PANEL_LO = "#0A0D12"        # fond de fenêtre, presque noir
PANEL = "#171C25"           # surface d'un panneau
PANEL_HI = "#222934"        # surface survolée ou surélevée

GOLD = "#C79A22"
GOLD_HI = "#EBC65C"
GOLD_LO = "#8A6A12"

PAD_RED = "#F2453D"
PAD_ORANGE = "#FF8C1A"
PAD_AMBER = "#FFC400"
PAD_YELLOW = "#F5E13C"
PAD_GREEN = "#3DD160"
PAD_MINT = "#2FD3A6"
PAD_CYAN = "#28C4E0"
PAD_BLUE = "#3E86F5"
PAD_INDIGO = "#6B5CE7"
PAD_PURPLE = "#A85BE0"
PAD_MAGENTA = "#F04FA8"
PAD_PINK = "#FF7BB0"
PAD_OFF = "#262A33"
PAD_DIM = "#3A404C"
PAD_WHITE = "#F2F4F8"

#: Pad éteint de la couverture du guide (``figs_couverture.PAD_ETEINT``) :
#: plus sombre que ``PAD_OFF``, il laisse briller les pads allumés.
PAD_ETEINT = "#191D25"

PAD_CYCLE = [PAD_RED, PAD_ORANGE, PAD_AMBER, PAD_YELLOW, PAD_GREEN, PAD_MINT,
             PAD_CYAN, PAD_BLUE, PAD_INDIGO, PAD_PURPLE, PAD_MAGENTA, PAD_PINK]

#: **Une couleur par page**, pour qu'on sache d'un coup d'œil où l'on est.
#: Les teintes viennent des pads du Deluge : l'application emprunte à la
#: machine son vocabulaire visuel au lieu d'un camaïeu de gris. La clé est
#: celle de la navigation (``DashboardPage`` -> ``Dashboard``).
PAGE_COLORS = {
    "Dashboard": PAD_AMBER,
    "Samples": PAD_CYAN,
    "Synths": PAD_PURPLE,
    "Kits": PAD_GREEN,
    "Songs": PAD_BLUE,
    "Generator": PAD_MAGENTA,
    # Le rouge du bouton d'enregistrement : on y compose le morceau.
    "Atelier": PAD_RED,
    "Toolbox": PAD_MINT,
    "Health": PAD_ORANGE,
    "Settings": PAD_INDIGO,
}

ACCENT = "#1F7A8C"
ACCENT_2 = "#C4543C"
WASH = "#EEF1F5"
WASH_2 = "#F6EEE4"

# Teintes dérivées, propres à l'interface
BORDER = "#333B48"          # bordure standard
BORDER_SOFT = "#2A3240"     # bordure discrète (panneaux) — visible, elle
BORDER_HI = "#444E5F"       # bordure survolée
#: Arête haute d'un panneau, un peu plus claire : le chanfrein d'une façade
#: éclairée d'en haut.
BORDER_TOP = "#323B4A"
#: Haut d'un panneau : le dégradé vers ``PANEL`` donne du relief sans ombre.
CARD_TOP = "#1B212B"
ALT_ROW = "#1C222C"         # ligne alternée des tables
INPUT_BG = "#111620"        # fond des champs de saisie
INPUT_FOCUS = "#19202B"
TEXT = PAD_WHITE
TEXT_DIM = GREY_LIGHT
TEXT_MUTED = "#5A6270"
GRID = "#23272F"

#: **La façade** : barre du haut, colonne de pads, barre d'état. Un cran
#: sous les panneaux et au-dessus du fond, pour que la machine encadre les
#: pages sans les écraser.
CHROME = "#0E1218"
CHROME_EDGE = "#1E2530"

#: L'écran OLED du Deluge, tel que le guide le dessine (``figs_oled.py``).
OLED_BG = "#04060A"
OLED_FG = "#FFFFFF"
OLED_DIM = "#8FB6CC"
OLED_HI = "#7FE3FF"
OLED_EDGE = "#1B3E52"

FONT_UI = "Segoe UI"
FONT_MONO = "Consolas"
FONT_UI_FALLBACK = "DejaVu Sans"
FONT_MONO_FALLBACK = "Cascadia Mono"
RADIUS = 9
PAD = 12

#: Dossier de cache des micro-images du QSS (chevrons, coches…).
ASSET_DIR = CONFIG_DIR / "cache" / "theme"

__all__ = [
    "INK", "INK_SOFT", "GREY", "GREY_LIGHT", "TEXT_SOFT",
    "PAPER", "PAPER_WARM",
    "PANEL", "PANEL_HI", "PANEL_LO", "GOLD", "GOLD_HI", "GOLD_LO",
    "PAD_RED", "PAD_ORANGE", "PAD_AMBER", "PAD_YELLOW", "PAD_GREEN", "PAD_MINT",
    "PAD_CYAN", "PAD_BLUE", "PAD_INDIGO", "PAD_PURPLE", "PAD_MAGENTA", "PAD_PINK",
    "PAD_OFF", "PAD_DIM", "PAD_WHITE", "PAD_ETEINT", "PAD_CYCLE",
    "CHROME", "CHROME_EDGE", "OLED_BG", "OLED_FG", "OLED_DIM", "OLED_HI",
    "OLED_EDGE",
    "luminance", "contrast", "readable",
    "PAGE_COLORS", "page_color",
    "ACCENT", "ACCENT_2", "WASH", "WASH_2",
    "FONT_UI", "FONT_MONO", "RADIUS", "PAD",
    "qss", "accent_qss", "accent_values", "lit_fill", "apply_theme",
    "pad_color", "category_color",
    "severity_color", "mix", "with_alpha", "text_on", "palette",
]


# ---------------------------------------------------------------------------
# Utilitaires de couleur
# ---------------------------------------------------------------------------
def _rgb(color: str) -> tuple[int, int, int]:
    """Décompose une couleur '#RGB' / '#RRGGBB' (ou un nom Qt) en (r, g, b)."""
    c = (color or "").strip()
    if c.startswith("#"):
        h = c[1:]
        if len(h) == 3:
            try:
                return tuple(int(ch * 2, 16) for ch in h)  # type: ignore[return-value]
            except ValueError:
                pass
        elif len(h) in (6, 8):
            try:
                return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
            except ValueError:
                pass
    q = QColor(c)
    if q.isValid():
        return (q.red(), q.green(), q.blue())
    log.warning("Couleur invalide : %r — remplacée par l'or", color)
    return _rgb(GOLD)


def _hex(r: int, g: int, b: int) -> str:
    """Compose '#RRGGBB' à partir de composantes entières."""
    clamp = lambda v: max(0, min(255, int(round(v))))  # noqa: E731
    return "#{:02X}{:02X}{:02X}".format(clamp(r), clamp(g), clamp(b))


def mix(c1: str, c2: str, t: float) -> str:
    """Mélange linéaire de deux couleurs : t=0 -> c1, t=1 -> c2."""
    t = max(0.0, min(1.0, float(t)))
    r1, g1, b1 = _rgb(c1)
    r2, g2, b2 = _rgb(c2)
    return _hex(r1 + (r2 - r1) * t, g1 + (g2 - g1) * t, b1 + (b2 - b1) * t)


def with_alpha(c: str, a: float) -> str:
    """Couleur translucide au format QSS : `with_alpha(GOLD, 0.25)`.

    `a` est une fraction 0..1 (les valeurs > 1 sont comprises comme 0..255).
    """
    r, g, b = _rgb(c)
    alpha = float(a)
    alpha = alpha * 255.0 if alpha <= 1.0 else alpha
    alpha_i = max(0, min(255, int(round(alpha))))
    return "rgba({}, {}, {}, {})".format(r, g, b, alpha_i)


def luminance(color: str) -> float:
    """Luminance relative, au sens de la norme WCAG."""
    composantes = []
    for valeur in _rgb(color):
        v = valeur / 255.0
        composantes.append(v / 12.92 if v <= 0.04045
                           else ((v + 0.055) / 1.055) ** 2.4)
    return (0.2126 * composantes[0] + 0.7152 * composantes[1]
            + 0.0722 * composantes[2])


def contrast(first: str, second: str) -> float:
    """Rapport de contraste entre deux couleurs, de 1 à 21.

    La norme demande **4,5** pour un texte courant et 3 pour un grand texte.
    En dessous de 3, beaucoup de gens ne lisent plus.
    """
    a, b = luminance(first), luminance(second)
    haut, bas = (a, b) if a >= b else (b, a)
    return (haut + 0.05) / (bas + 0.05)


def readable(color: str, on: str = "", minimum: float = 4.5) -> str:
    """Éclaircit ``color`` jusqu'à ce qu'elle se lise sur ``on``.

    Deux couleurs de page — le violet des presets (4,26) et l'indigo des
    réglages (3,51) — passaient sous le seuil quand elles servaient de
    couleur de texte. Plutôt que de corriger ces deux-là à la main, on
    corrige la règle : une couleur destinée à un texte est éclaircie juste
    ce qu'il faut, et celles qui vont déjà bien ne bougent pas.

    Le fond par défaut est celui d'un panneau, là où se posent les titres de
    section.
    """
    fond = on or PANEL
    try:
        actuel = contrast(color, fond)
    except Exception:              # noqa: BLE001 - couleur illisible
        return color
    if actuel >= minimum:
        return color
    # Vers le blanc, par pas de 2 % : trente essais suffisent largement.
    for pas in range(1, 31):
        candidat = mix(color, "#FFFFFF", pas * 0.02)
        if contrast(candidat, fond) >= minimum:
            return candidat
    return "#FFFFFF"


def text_on(bg: str) -> str:
    """Couleur de texte lisible sur le fond donné (encre ou blanc de pad).

    On garde celle des deux qui contraste le plus. Un seuil fixe de
    luminance ne convient pas : celui d'avant (0,58) avait été réglé pour
    une luminance perçue, et appliqué à la luminance WCAG il mettait du
    blanc sur le vert, le cyan ou l'or des pages (contraste 1,7 à 2,4).
    """
    if contrast(INK, bg) >= contrast(PAD_WHITE, bg):
        return INK
    return PAD_WHITE


def page_color(key: str) -> str:
    """Couleur d'une page, ou l'or par défaut pour une page inconnue."""
    return PAGE_COLORS.get(str(key or ""), GOLD)


def pad_color(i: int) -> str:
    """Couleur de pad n°`i` dans le cycle des 12 teintes du Deluge."""
    return PAD_CYCLE[int(i) % len(PAD_CYCLE)]


def category_color(name: str) -> str:
    """Couleur stable (et reproductible d'une session à l'autre) pour une catégorie."""
    key = (name or "").strip().lower()
    if not key:
        return GREY
    digest = hashlib.md5(key.encode("utf-8")).digest()
    return pad_color(digest[0])


_SEVERITY_COLORS = untranslated({
    "info": PAD_CYAN,
    "warn": PAD_AMBER,
    "warning": PAD_AMBER,
    "avertissement": PAD_AMBER,
    "error": PAD_RED,
    "erreur": PAD_RED,
    "critical": PAD_RED,
    "ok": PAD_GREEN,
    "success": PAD_GREEN,
    "succès": PAD_GREEN,
    "debug": GREY,
})


def severity_color(sev: str) -> str:
    """Couleur associée à une gravité ('info', 'warn', 'error', 'ok')."""
    return _SEVERITY_COLORS.get((sev or "").strip().lower(), GREY)


# ---------------------------------------------------------------------------
# Micro-images du QSS (dessinées, mises en cache sur disque)
# ---------------------------------------------------------------------------
_ASSET_CACHE: dict[tuple[str, str, int], str] = {}


def _draw_asset(img: QImage, kind: str, color: str, s: int) -> None:
    """Dessine le pictogramme `kind` dans l'image carrée `img` de côté `s`."""
    p = QPainter(img)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        col = QColor(color)
        pen = QPen(col)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        if kind in ("chevron-down", "chevron-up", "chevron-right", "chevron-left"):
            pen.setWidthF(max(1.2, s * 0.15))
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            a, b, c = 0.28, 0.5, 0.72
            if kind == "chevron-down":
                pts = [(a, 0.40), (b, 0.64), (c, 0.40)]
            elif kind == "chevron-up":
                pts = [(a, 0.62), (b, 0.38), (c, 0.62)]
            elif kind == "chevron-right":
                pts = [(0.40, a), (0.64, b), (0.40, c)]
            else:
                pts = [(0.62, a), (0.38, b), (0.62, c)]
            p.drawPolyline(QPolygonF([QPointF(x * s, y * s) for x, y in pts]))
        elif kind == "check":
            pen.setWidthF(max(1.4, s * 0.17))
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            pts = [(0.22, 0.53), (0.42, 0.73), (0.79, 0.29)]
            p.drawPolyline(QPolygonF([QPointF(x * s, y * s) for x, y in pts]))
        elif kind == "dash":
            pen.setWidthF(max(1.4, s * 0.17))
            p.setPen(pen)
            p.drawLine(QPointF(0.24 * s, 0.5 * s), QPointF(0.76 * s, 0.5 * s))
        elif kind == "dot":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawEllipse(QPointF(0.5 * s, 0.5 * s), 0.27 * s, 0.27 * s)
        elif kind in ("tri-down", "tri-up"):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            if kind == "tri-down":
                pts = [(0.22, 0.38), (0.78, 0.38), (0.5, 0.68)]
            else:
                pts = [(0.22, 0.62), (0.78, 0.62), (0.5, 0.32)]
            p.drawPolygon(QPolygonF([QPointF(x * s, y * s) for x, y in pts]))
        else:  # repli : petit carré arrondi plein
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(int(0.3 * s), int(0.3 * s), int(0.4 * s), int(0.4 * s),
                              s * 0.1, s * 0.1)
    finally:
        p.end()


def _asset(kind: str, color: str, size: int = 12) -> str:
    """Retourne la valeur QSS `url("…")` de la micro-image demandée (ou `none`)."""
    key = (kind, color, size)
    cached = _ASSET_CACHE.get(key)
    if cached is not None:
        return cached
    value = "none"
    try:
        ASSET_DIR.mkdir(parents=True, exist_ok=True)
        name = "{}-{}-{}.png".format(kind, color.lstrip("#").lower(), size)
        path = ASSET_DIR / name
        if not path.is_file():
            img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
            img.fill(QColor(0, 0, 0, 0))
            _draw_asset(img, kind, color, size)
            if not img.save(str(path), "PNG"):
                raise OSError(tr("écriture PNG refusée : {}").format(path))
        value = 'url("{}")'.format(path.as_posix())
    except Exception:  # pragma: no cover - cache non accessible : on dégrade
        log.exception("Micro-image de thème indisponible (%s) — repli sans image", kind)
        value = "none"
    _ASSET_CACHE[key] = value
    return value


# ---------------------------------------------------------------------------
# Feuille de style
# ---------------------------------------------------------------------------
#
# Elle est en **deux parties**, et la séparation n'est pas cosmétique.
#
# Chaque page pose sur elle-même la partie colorée, à sa couleur. Or Qt ne
# départage pas deux feuilles par la spécificité de leurs sélecteurs : la
# feuille d'un parent l'emporte **toujours** sur celle de l'application.
# Si la page fixait le fond des boutons sans fixer celui des boutons
# désactivés, un bouton éteint garderait le fond vif de la page — le
# survol, l'appui et l'état coché disparaîtraient de même.
#
# D'où la règle : **toute propriété de couleur d'un contrôle vit dans la
# partie colorée, avec tous ses états** ; la base ne garde que la géométrie
# (marges, rayons, polices) et la couleur des conteneurs, que la page ne
# touche pas.

_QSS_BASE = Template(r"""
/* ======================================================================
   Deluge Companion — feuille de style, partie commune
   Façade CHROME, fond PANEL_LO, panneaux PANEL, coins arrondis de pads.
   ====================================================================== */

* { outline: 0; }

QWidget {
    color: ${TEXT};
    font-family: "${FONT_UI}", "${FONT_UI_FALLBACK}", "Noto Sans", sans-serif;
    font-size: 10pt;
}
QMainWindow, QDialog, QMessageBox, QFileDialog, QInputDialog, QWizard {
    background-color: ${PANEL_LO};
}
QLabel, QCheckBox, QRadioButton, QSplitter, QTabWidget, QStackedWidget,
QScrollArea, QToolBox, QWidget#Page {
    background: transparent;
}
QScrollArea > QWidget > QWidget { background: transparent; }
QLabel:disabled { color: ${TEXT_MUTED}; }

/* --- Typographie : capitales espacées du guide ------------------------ */
QLabel[role="h1"]        { font-size: 19pt; font-weight: 800; color: ${TEXT};
                           letter-spacing: 1px; text-transform: uppercase; }
QLabel[role="eyebrow"]   { font-size: 7.5pt; font-weight: 700; color: ${TEXT_SOFT};
                           letter-spacing: 3px; text-transform: uppercase; }
QLabel[role="title"]     { font-size: 13.5pt; font-weight: 700; color: ${TEXT}; }
QLabel[role="section"]   { font-size: 8.5pt; font-weight: 800;
                           letter-spacing: 2px; text-transform: uppercase; }
QLabel[role="subtitle"], QLabel[role="hint"] { font-size: 9pt;
                                              color: ${TEXT_SOFT}; }
QLabel[role="caption"]   { font-size: 7.8pt; font-weight: 700; color: ${TEXT_SOFT};
                           letter-spacing: 1.5px; text-transform: uppercase; }
QLabel[role="value"]     { font-size: 24pt; font-weight: 800; color: ${TEXT};
                           letter-spacing: -0.5px; }
QLabel[role="mono"], QLabel#Mono, QTextEdit#Mono, QPlainTextEdit#Mono,
QTextEdit[role="mono"], QPlainTextEdit[role="mono"] {
    font-family: "${FONT_MONO}", "${FONT_MONO_FALLBACK}", monospace; font-size: 9pt;
}

/* --- Conteneurs ------------------------------------------------------ */
QFrame#Card, QFrame[card="true"], QGroupBox {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                      stop:0 ${CARD_TOP}, stop:1 ${PANEL});
    border: 1px solid ${BORDER_SOFT};
    border-top-color: ${BORDER_TOP};
    border-radius: ${R_LG}px;
}
QFrame#Card:hover, QFrame[card="true"]:hover {
    border-color: ${BORDER}; border-top-color: ${BORDER_HI};
}
QFrame#Tile, QFrame[tile="true"] {
    background-color: ${PANEL};
    border: 1px solid ${BORDER_SOFT};
    border-radius: ${R_LG}px;
}
QFrame#Header, QWidget#Header {
    background-color: ${CHROME};
    border: none;
    border-bottom: 1px solid ${CHROME_EDGE};
}
QFrame#Sidebar, QWidget#Sidebar {
    background-color: ${CHROME};
    border: none;
    border-right: 1px solid ${CHROME_EDGE};
}
QFrame[frameShape="4"] { background-color: ${BORDER}; border: none; min-height: 1px; max-height: 1px; }
QFrame[frameShape="5"] { background-color: ${BORDER}; border: none; min-width: 1px; max-width: 1px; }
QGroupBox {
    margin-top: 18px;
    padding: 16px 10px 10px 10px;
    font-weight: 700;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px; padding: 0 6px;
}

/* --- Boutons : la géométrie (les couleurs sont dans la partie colorée) */
QPushButton {
    border-radius: ${R}px;
    padding: 6px 14px;
    min-height: 20px;
    font-weight: 600;
}
QPushButton#Primary, QPushButton[accent="true"] {
    border-radius: ${R_BTN}px;
    padding: 6px 18px;
    font-weight: 700;
}
QToolButton {
    border-radius: ${R}px;
    padding: 4px 6px;
}
QToolButton::menu-indicator { image: ${IMG_DOWN}; width: 9px; height: 9px;
                              subcontrol-position: right center; right: 3px; }
QToolButton[popupMode="1"] { padding-right: 16px; }
QPushButton#NavButton, QToolButton#NavButton,
QPushButton[nav="true"], QToolButton[nav="true"] {
    border-radius: ${R}px;
    padding: 9px 10px;
    text-align: left;
    font-weight: 500;
}

/* --- Saisie ---------------------------------------------------------- */
QLineEdit, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit, QTextBrowser,
QDateEdit, QTimeEdit, QDateTimeEdit, QKeySequenceEdit {
    border-radius: ${R}px;
    padding: 5px 10px;
}
QLineEdit#Search, QLineEdit[search="true"] {
    padding-left: 30px; border-radius: 17px; min-height: 22px;
}
QTextBrowser { padding: 10px; }

QSpinBox::up-button, QDoubleSpinBox::up-button,
QDateEdit::up-button, QTimeEdit::up-button {
    subcontrol-origin: border; subcontrol-position: top right;
    width: 18px; margin: 3px 3px 0 0;
    border: none; border-radius: 5px; background: transparent;
}
QSpinBox::down-button, QDoubleSpinBox::down-button,
QDateEdit::down-button, QTimeEdit::down-button {
    subcontrol-origin: border; subcontrol-position: bottom right;
    width: 18px; margin: 0 3px 3px 0;
    border: none; border-radius: 5px; background: transparent;
}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow, QDateEdit::up-arrow, QTimeEdit::up-arrow {
    image: ${IMG_TRI_UP}; width: 8px; height: 8px;
}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow, QDateEdit::down-arrow, QTimeEdit::down-arrow {
    image: ${IMG_TRI_DOWN}; width: 8px; height: 8px;
}
QSpinBox::up-arrow:disabled, QSpinBox::down-arrow:disabled,
QDoubleSpinBox::up-arrow:disabled, QDoubleSpinBox::down-arrow:disabled { image: none; }

/* --- Listes déroulantes ---------------------------------------------- */
QComboBox {
    border-radius: ${R}px;
    padding: 5px 10px;
    padding-right: 28px;
    min-height: 20px;
}
QComboBox::drop-down {
    subcontrol-origin: padding; subcontrol-position: top right;
    width: 26px; border: none; background: transparent;
}
QComboBox QAbstractItemView {
    border-radius: ${R_LG}px;
    padding: 5px;
    margin-top: 3px;
    outline: 0;
}
QComboBox QAbstractItemView::item { min-height: 24px; padding: 3px 10px; border-radius: 7px; }

/* --- Vues (tables, arbres, listes) ----------------------------------- */
QAbstractItemView { outline: 0; border-radius: ${R_LG}px; }
QTableView, QTreeView, QListView { show-decoration-selected: 1; }
QTableView::item, QTreeView::item, QListView::item {
    padding: 4px 8px; border: none;
}
QListView::item { border-radius: 8px; margin: 1px 3px; }
QTreeView::item { border-radius: 6px; }
QTreeView::branch { background: transparent; }
QTreeView::branch:has-children:!has-siblings:closed,
QTreeView::branch:closed:has-children:has-siblings { image: ${IMG_RIGHT}; }
QTreeView::branch:open:has-children:!has-siblings,
QTreeView::branch:open:has-children:has-siblings { image: ${IMG_DOWN}; }
QHeaderView { background: transparent; border: none; }
QHeaderView::section {
    padding: 8px 8px 7px 8px;
    font-weight: 700;
    font-size: 8.5pt;
}
QHeaderView::section:first   { border-top-left-radius: ${R_LG}px; }
QHeaderView::section:last    { border-top-right-radius: ${R_LG}px; }
QTableCornerButton::section { background-color: ${PANEL}; border: none; }

/* --- Barres de défilement (fines, sans flèche) ------------------------ */
QScrollBar:vertical   { background: transparent; width: 10px; margin: 3px 2px 3px 0; border: none; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 0 3px 2px 3px; border: none; }
QScrollBar::handle:vertical   { border-radius: 4px; min-height: 30px; margin: 0 2px; }
QScrollBar::handle:horizontal { border-radius: 4px; min-width: 30px; margin: 2px 0; }
QScrollBar::add-line, QScrollBar::sub-line {
    width: 0; height: 0; border: none; background: transparent;
}
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QAbstractScrollArea::corner { background: transparent; border: none; }

/* --- Curseurs et jauges ---------------------------------------------- */
QSlider { background: transparent; }
QSlider::groove:horizontal { height: 4px; border-radius: 2px; }
QSlider::sub-page:horizontal, QSlider::add-page:horizontal { border-radius: 2px; }
QSlider::handle:horizontal { width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; }
QSlider::groove:vertical { width: 4px; border-radius: 2px; }
QSlider::add-page:vertical, QSlider::sub-page:vertical { border-radius: 2px; }
QSlider::handle:vertical { width: 16px; height: 16px; margin: 0 -6px; border-radius: 8px; }

QProgressBar {
    border: none;
    border-radius: 6px;
    min-height: 10px; max-height: 18px;
    text-align: center;
    font-size: 8pt;
}
QProgressBar::chunk { border-radius: 6px; }
QProgressBar[thin="true"] { min-height: 6px; max-height: 6px; border-radius: 3px; }
QProgressBar[thin="true"]::chunk { border-radius: 3px; }

/* --- Onglets : des pastilles, comme les boutons de mode de la machine - */
QTabWidget::pane {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                      stop:0 ${CARD_TOP}, stop:1 ${PANEL});
    border: 1px solid ${BORDER_SOFT};
    border-top-color: ${BORDER_TOP};
    border-radius: ${R_LG}px;
    top: 0px;
}
QTabWidget::tab-bar { alignment: left; left: 2px; }
QTabBar { background: transparent; qproperty-drawBase: 0; }
QTabBar::tab {
    border-radius: 15px;
    padding: 6px 16px;
    margin: 0 4px 8px 0;
    min-width: 40px;
    font-weight: 600;
}
QTabBar::tab:left, QTabBar::tab:right { padding: 12px 7px; margin: 0 8px 4px 0; }

/* --- Séparateurs ------------------------------------------------------ */
QSplitter { background: transparent; }
QSplitter::handle { background: transparent; }
QSplitter::handle:horizontal { width: 8px; }
QSplitter::handle:vertical   { height: 8px; }

/* --- Menus et barres -------------------------------------------------- */
QMenuBar { border: none; padding: 0 2px; spacing: 2px; }
QMenuBar::item { padding: ${MENU_ITEM_PAD}px 11px; border-radius: 8px; margin: 0; }
QMenu {
    border-radius: ${R_LG}px;
    padding: 6px;
}
QMenu::item { padding: 7px 28px 7px 28px; border-radius: 7px; }
QMenu::separator { height: 1px; margin: 5px 10px; }
QMenu::icon { left: 8px; }
QMenu::indicator { width: 14px; height: 14px; left: 9px; }
QMenu::right-arrow { image: ${IMG_RIGHT}; width: 9px; height: 9px; right: 8px; }
QToolBar {
    background-color: ${CHROME};
    border: none;
    border-bottom: 1px solid ${CHROME_EDGE};
    spacing: 4px; padding: 4px;
}
QToolBar::separator { background-color: ${BORDER}; width: 1px; margin: 5px 6px; }
QStatusBar {
    background-color: ${CHROME};
    color: ${TEXT_SOFT};
    border: none;
    border-top: 1px solid ${CHROME_EDGE};
    font-family: "${FONT_MONO}", "${FONT_MONO_FALLBACK}", monospace;
    font-size: 8.5pt;
    min-height: 24px;
}
QStatusBar::item { border: none; }
QStatusBar QLabel { color: ${TEXT_SOFT}; padding: 0 6px; font-size: 8.5pt; }
QSizeGrip { background: transparent; width: 12px; height: 12px; }

/* --- Cases et boutons radio : des petits pads ------------------------- */
QCheckBox, QRadioButton { spacing: 8px; padding: 2px; color: ${TEXT}; }
QCheckBox:disabled, QRadioButton:disabled { color: ${TEXT_MUTED}; }
QCheckBox::indicator, QRadioButton::indicator { width: 17px; height: 17px; }
QCheckBox::indicator { border-radius: 5px; }
QRadioButton::indicator { border-radius: 9px; }

/* --- Divers ----------------------------------------------------------- */
QDockWidget {
    color: ${GREY_LIGHT};
    titlebar-close-icon: none; titlebar-normal-icon: none;
}
QDockWidget::title {
    background-color: ${PANEL_HI}; padding: 6px 10px;
    border-top-left-radius: ${R}px; border-top-right-radius: ${R}px;
}
QDialogButtonBox { button-layout: 3; }
QDialogButtonBox QPushButton { min-width: 88px; }
QMessageBox QLabel { color: ${TEXT}; }
QToolBox::tab { border-radius: ${R}px; padding: 6px; }
QListWidget#Variations::item { margin: 3px; padding: 6px; border-radius: ${R}px; }
""")


_QSS_ACCENT = Template(r"""
/* ======================================================================
   Partie colorée : tout ce qui prend la teinte de la page (ou de la
   façade). Chaque propriété y figure avec TOUS ses états — voir la note
   en tête des feuilles.
   ====================================================================== */

QWidget {
    selection-background-color: ${SEL_STRONG};
    selection-color: ${TEXT};
}
QLabel[role="section"]   { color: ${ACC_TEXT}; }
QLabel[role="accent"]    { color: ${ACC_TEXT}; font-weight: 600; }
QFrame#Rule, QFrame[role="rule"] {
    background-color: ${ACC};
    border: none;
    min-height: 2px; max-height: 2px;
    border-radius: 1px;
}
QGroupBox::title { color: ${ACC_TEXT}; }

/* --- Boutons : des touches de façade --------------------------------- */
QPushButton {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                      stop:0 ${BTN_TOP}, stop:1 ${BTN_BOTTOM});
    color: ${TEXT};
    border: 1px solid ${BORDER};
    border-top-color: ${BTN_EDGE};
}
QPushButton:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                      stop:0 ${BTN_HOVER_TOP}, stop:1 ${BTN_HOVER_BOTTOM});
    border-color: ${ACC_DIM};
}
QPushButton:pressed   { background-color: ${BTN_PRESS}; border-color: ${ACC}; }
QPushButton:checked   { background-color: ${SEL_MED}; border-color: ${ACC}; color: ${ACC_TEXT}; }
QPushButton:checked:hover { background-color: ${SEL_STRONG}; }
QPushButton:focus     { border-color: ${ACC_DIM}; }
QPushButton:default   { border-color: ${ACC_DIM}; }
QPushButton:disabled  {
    background-color: ${PANEL}; color: ${TEXT_MUTED};
    border-color: ${BORDER_SOFT};
}
QPushButton:flat      { background: transparent; border-color: transparent; }
QPushButton:flat:hover { background-color: ${SEL_SOFT}; }

/* Action principale : un pad allumé. Pleine, à la couleur de la page,
   impossible à confondre avec les touches éteintes qui l'entourent. */
QPushButton#Primary, QPushButton[accent="true"] {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                      stop:0 ${PRI_TOP}, stop:1 ${PRI_BOTTOM});
    color: ${ACC_INK};
    border: 1px solid ${ACC};
    border-top-color: ${PRI_EDGE};
}
QPushButton#Primary:hover, QPushButton[accent="true"]:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                      stop:0 ${PRI_HOVER_TOP}, stop:1 ${PRI_TOP});
    border-color: ${PRI_EDGE};
}
QPushButton#Primary:pressed, QPushButton[accent="true"]:pressed {
    background-color: ${ACC_LO}; color: ${PAD_WHITE}; border-color: ${ACC_LO};
}
QPushButton#Primary:focus, QPushButton[accent="true"]:focus { border-color: ${PRI_EDGE}; }
QPushButton#Primary:checked, QPushButton[accent="true"]:checked {
    background-color: ${PRI_BOTTOM}; color: ${ACC_INK};
}
QPushButton#Primary:disabled, QPushButton[accent="true"]:disabled {
    background-color: ${PANEL_HI}; color: ${TEXT_MUTED}; border-color: ${BORDER_SOFT};
}
QPushButton[danger="true"] {
    background-color: ${DANGER_BG}; color: ${PAD_RED}; border-color: ${DANGER_BORDER};
}
QPushButton[danger="true"]:hover  { background-color: ${DANGER_HOVER}; border-color: ${PAD_RED}; }
QPushButton[danger="true"]:pressed { background-color: ${PAD_RED}; color: ${INK}; }
QPushButton[danger="true"]:disabled {
    background-color: ${PANEL}; color: ${TEXT_MUTED}; border-color: ${BORDER_SOFT};
}

QToolButton {
    background: transparent;
    color: ${GREY_LIGHT};
    border: 1px solid transparent;
}
QToolButton:hover   { background-color: ${SEL_SOFT}; color: ${TEXT}; border-color: ${ACC_DIM}; }
QToolButton:pressed { background-color: ${SEL_MED}; }
QToolButton:checked { background-color: ${SEL_MED}; color: ${ACC_TEXT}; border-color: ${ACC}; }
QToolButton:disabled { color: ${TEXT_MUTED}; }

QPushButton#NavButton, QToolButton#NavButton,
QPushButton[nav="true"], QToolButton[nav="true"] {
    background: transparent;
    color: ${TEXT_SOFT};
    border: none;
}
QPushButton#NavButton:hover, QToolButton#NavButton:hover,
QPushButton[nav="true"]:hover, QToolButton[nav="true"]:hover {
    background-color: ${SEL_SOFT}; color: ${TEXT};
}
QPushButton#NavButton:checked, QToolButton#NavButton:checked,
QPushButton[nav="true"]:checked, QToolButton[nav="true"]:checked {
    background-color: ${SEL_MED}; color: ${TEXT};
}

/* --- Saisie ---------------------------------------------------------- */
QLineEdit, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit, QTextBrowser,
QDateEdit, QTimeEdit, QDateTimeEdit, QKeySequenceEdit {
    background-color: ${INPUT_BG};
    color: ${TEXT};
    border: 1px solid ${BORDER};
    selection-background-color: ${SEL_STRONG};
    selection-color: ${TEXT};
}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QTextEdit:hover,
QPlainTextEdit:hover { border-color: ${BORDER_HI}; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTextEdit:focus,
QPlainTextEdit:focus, QDateEdit:focus, QTimeEdit:focus {
    border-color: ${ACC}; background-color: ${INPUT_FOCUS};
}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled,
QTextEdit:disabled, QPlainTextEdit:disabled {
    background-color: ${PANEL}; color: ${TEXT_MUTED}; border-color: ${BORDER_SOFT};
}
QLineEdit[readOnly="true"] { background-color: ${PANEL}; color: ${GREY_LIGHT}; }
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
    background-color: ${SEL_MED};
}

/* --- Listes déroulantes ---------------------------------------------- */
QComboBox {
    background-color: ${INPUT_BG};
    color: ${TEXT};
    border: 1px solid ${BORDER};
}
QComboBox:hover { border-color: ${BORDER_HI}; }
QComboBox:focus, QComboBox:on { border-color: ${ACC}; background-color: ${INPUT_FOCUS}; }
QComboBox:disabled { background-color: ${PANEL}; color: ${TEXT_MUTED}; border-color: ${BORDER_SOFT}; }
QComboBox::down-arrow { image: ${IMG_DOWN}; width: 11px; height: 11px; }
QComboBox::down-arrow:on, QComboBox::down-arrow:hover { image: ${IMG_DOWN_HI}; }
QComboBox::down-arrow:disabled { image: none; }
QComboBox QAbstractItemView {
    background-color: ${PANEL};
    border: 1px solid ${BORDER_HI};
    selection-background-color: ${SEL_MED};
    selection-color: ${ACC_TEXT};
}
QComboBox QAbstractItemView::item:hover { background-color: ${SEL_SOFT}; }

/* --- Vues (tables, arbres, listes) ----------------------------------- */
QAbstractItemView {
    background-color: ${PANEL};
    alternate-background-color: ${ALT_ROW};
    color: ${TEXT};
    border: 1px solid ${BORDER_SOFT};
    gridline-color: ${GRID};
    selection-background-color: ${SEL_STRONG};
    selection-color: ${TEXT};
}
QTableView::item, QTreeView::item, QListView::item { color: ${TEXT}; }
QTableView::item:hover, QTreeView::item:hover, QListView::item:hover {
    background-color: ${SEL_SOFT};
}
QTableView::item:selected, QTreeView::item:selected, QListView::item:selected {
    background-color: ${SEL_STRONG}; color: ${TEXT};
}
QTableView::item:selected:!active, QTreeView::item:selected:!active,
QListView::item:selected:!active { background-color: ${SEL_MED}; color: ${TEXT}; }
QTableView::item:disabled, QTreeView::item:disabled { color: ${TEXT_MUTED}; }
QHeaderView::section {
    background-color: ${PANEL};
    color: ${TEXT_SOFT};
    border: none;
    border-bottom: 1px solid ${BORDER};
}
QHeaderView::section:hover   { background-color: ${HDR_HOVER}; color: ${TEXT}; }
QHeaderView::section:checked { color: ${ACC_TEXT}; border-bottom: 2px solid ${ACC}; }
QHeaderView::section:vertical {
    border-bottom: 1px solid ${PANEL_LO}; border-right: 2px solid ${ACC_LO};
}
QHeaderView::down-arrow { image: ${IMG_DOWN_HI}; width: 9px; height: 9px;
                          subcontrol-position: center right; right: 6px; }
QHeaderView::up-arrow   { image: ${IMG_UP_HI}; width: 9px; height: 9px;
                          subcontrol-position: center right; right: 6px; }

/* --- Barres de défilement --------------------------------------------- */
QScrollBar::handle:vertical, QScrollBar::handle:horizontal { background-color: ${SCROLL}; }
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {
    background-color: ${SCROLL_HI};
}
QScrollBar::handle:vertical:pressed, QScrollBar::handle:horizontal:pressed {
    background-color: ${ACC};
}

/* --- Curseurs et jauges ---------------------------------------------- */
QSlider::groove:horizontal, QSlider::groove:vertical { background-color: ${PANEL_HI}; }
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 ${ACC_LO}, stop:1 ${ACC});
}
QSlider::add-page:horizontal { background-color: ${PANEL_HI}; }
QSlider::add-page:vertical {
    background: qlineargradient(x1:0, y1:1, x2:0, y2:0, stop:0 ${ACC_LO}, stop:1 ${ACC});
}
QSlider::sub-page:vertical { background-color: ${PANEL_HI}; }
QSlider::handle:horizontal, QSlider::handle:vertical {
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.4, fy:0.35,
                stop:0 ${ACC_LIGHT}, stop:0.55 ${ACC}, stop:1 ${ACC_LO});
    border: 2px solid ${PANEL_LO};
}
QSlider::handle:horizontal:hover, QSlider::handle:vertical:hover {
    background: ${ACC_HI}; border-color: ${ACC_DIM};
}
QSlider::handle:horizontal:disabled, QSlider::handle:vertical:disabled {
    background: ${PANEL_HI}; border-color: ${BORDER};
}

QProgressBar {
    background-color: ${PANEL_HI};
    color: ${GREY_LIGHT};
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 ${ACC_LO}, stop:0.55 ${ACC}, stop:1 ${ACC_HI});
}

/* --- Onglets ---------------------------------------------------------- */
QTabBar::tab {
    background: transparent;
    color: ${TEXT_SOFT};
    border: 1px solid transparent;
}
QTabBar::tab:hover    { color: ${TEXT}; background-color: ${SEL_SOFT}; border-color: ${BORDER_SOFT}; }
QTabBar::tab:selected { color: ${ACC_TEXT}; background-color: ${SEL_MED}; border-color: ${ACC_DIM}; }
QTabBar::tab:disabled { color: ${TEXT_MUTED}; }

/* --- Séparateurs ------------------------------------------------------ */
QSplitter::handle:hover   { background-color: ${SEL_SOFT}; }
QSplitter::handle:pressed { background-color: ${SEL_MED}; }

/* --- Menus et barres -------------------------------------------------- */
QMenuBar {
    background-color: ${CHROME};
    color: ${TEXT_SOFT};
}
QMenuBar::item { background: transparent; color: ${TEXT_SOFT}; }
QMenuBar::item:selected { background-color: ${SEL_MED}; color: ${TEXT}; }
QMenuBar::item:pressed  { background-color: ${SEL_STRONG}; color: ${TEXT}; }
QMenu {
    background-color: ${PANEL};
    color: ${TEXT};
    border: 1px solid ${BORDER_HI};
}
QMenu::item { background: transparent; color: ${TEXT}; }
QMenu::item:selected { background-color: ${SEL_MED}; color: ${ACC_TEXT}; }
QMenu::item:disabled { color: ${TEXT_MUTED}; }
QMenu::separator { background-color: ${BORDER}; }
QMenu::indicator:checked { image: ${IMG_CHECK_ACC}; }
QToolTip {
    background-color: ${OLED_BG};
    color: ${TEXT};
    border: 1px solid ${ACC_DIM};
    border-radius: 8px;
    padding: 6px 9px;
    font-size: 9pt;
    opacity: 245;
}

/* --- Cases et boutons radio ------------------------------------------- */
QCheckBox::indicator, QRadioButton::indicator {
    border: 1px solid ${BORDER_HI}; background-color: ${INPUT_BG};
}
QCheckBox::indicator:hover, QRadioButton::indicator:hover { border-color: ${ACC}; }
QCheckBox::indicator:checked {
    background-color: ${ACC}; border-color: ${ACC}; image: ${IMG_CHECK_INK};
}
QCheckBox::indicator:checked:hover { background-color: ${ACC_HI}; border-color: ${ACC_HI}; }
QCheckBox::indicator:indeterminate {
    background-color: ${ACC_LO}; border-color: ${ACC_LO}; image: ${IMG_DASH_INK};
}
QRadioButton::indicator:checked {
    background-color: ${ACC}; border-color: ${ACC}; image: ${IMG_DOT_INK};
}
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {
    background-color: ${PANEL}; border-color: ${BORDER_SOFT};
}

QToolBox::tab {
    background-color: ${PANEL_HI}; color: ${GREY_LIGHT};
    border: 1px solid ${BORDER_SOFT};
}
QToolBox::tab:selected { color: ${ACC_TEXT}; border-color: ${ACC_LO}; }
""")


def _valid_accent(accent: str) -> str:
    """L'accent demandé s'il est utilisable, l'or sinon."""
    texte = str(accent or "").strip()
    if texte.startswith("#") and QColor(texte).isValid():
        return texte
    return GOLD


def _lisible_sous(fond: str, encre: str, minimum: float = 4.5) -> str:
    """Pousse ``fond`` juste assez pour que ``encre`` s'y lise.

    Mesuré : le bas du bouton violet tombait à 4,43, le haut du bouton
    indigo à 4,42. On éclaircit un fond sous l'encre noire, on fonce un
    fond sous le blanc, par pas de 2 %, et un fond déjà lisible ne bouge
    pas.
    """
    if contrast(encre, fond) >= minimum:
        return fond
    cible = PAPER if encre == INK else INK
    for pas in range(1, 31):
        candidat = mix(fond, cible, pas * 0.02)
        if contrast(encre, candidat) >= minimum:
            return candidat
    return fond


def lit_fill(color: str) -> tuple[str, str, str]:
    """Remplissage d'un pad allumé : ``(haut, bas, encre)`` du dégradé.

    Sur une teinte claire, l'encre est noire et le dégradé s'éclaircit vers
    le haut ; sur une teinte sombre, l'encre est blanche et le dégradé fonce
    vers le bas. Les deux extrémités sont poussées juste assez pour que
    l'encre s'y lise à 4,5.
    """
    teinte = _valid_accent(color)
    encre = text_on(teinte)
    if encre == INK:
        return (_lisible_sous(mix(teinte, PAPER, 0.28), encre),
                _lisible_sous(teinte, encre), encre)
    return (_lisible_sous(teinte, encre),
            _lisible_sous(mix(teinte, INK, 0.22), encre), encre)


def _base_values() -> dict[str, str]:
    """Valeurs de la partie commune : palette, géométrie, micro-images."""
    return {
        "INK": INK, "GREY": GREY, "GREY_LIGHT": GREY_LIGHT,
        "TEXT_SOFT": TEXT_SOFT,
        "PANEL": PANEL, "PANEL_HI": PANEL_HI, "PANEL_LO": PANEL_LO,
        "PAD_WHITE": PAD_WHITE,
        "TEXT": TEXT, "TEXT_MUTED": TEXT_MUTED,
        "BORDER": BORDER, "BORDER_SOFT": BORDER_SOFT, "BORDER_HI": BORDER_HI,
        "BORDER_TOP": BORDER_TOP, "CARD_TOP": CARD_TOP,
        "CHROME": CHROME, "CHROME_EDGE": CHROME_EDGE,
        "FONT_UI": FONT_UI, "FONT_UI_FALLBACK": FONT_UI_FALLBACK,
        "FONT_MONO": FONT_MONO, "FONT_MONO_FALLBACK": FONT_MONO_FALLBACK,
        "R": str(RADIUS), "R_BTN": str(RADIUS + 1), "R_LG": str(RADIUS + 5),
        "MENU_ITEM_PAD": "6",
        "IMG_DOWN": _asset("chevron-down", GREY_LIGHT, 12),
        "IMG_RIGHT": _asset("chevron-right", GREY_LIGHT, 12),
        "IMG_TRI_UP": _asset("tri-up", GREY_LIGHT, 10),
        "IMG_TRI_DOWN": _asset("tri-down", GREY_LIGHT, 10),
    }


def accent_values(accent: str) -> dict[str, str]:
    """Toutes les teintes dérivées d'un accent, celles de la partie colorée.

    Le bouton principal se lit dans les deux sens : sur une teinte claire
    (or, cyan, vert) il écrit à l'encre et son dégradé s'éclaircit vers le
    haut ; sur une teinte sombre (indigo) il écrit en blanc, et le dégradé
    **fonce** au lieu d'éclaircir — sans quoi le haut du bouton perdait le
    contraste que le bas avait.
    """
    acc = _valid_accent(accent)
    acc_hi = mix(acc, PAPER, 0.28)
    acc_light = mix(acc, PAPER, 0.50)
    acc_lo = mix(acc, INK, 0.45)
    pri_top, pri_bottom, encre = lit_fill(acc)
    if encre == INK:
        pri_hover_top = _lisible_sous(acc_light, encre)
        pri_edge = acc_light
    else:
        pri_hover_top = _lisible_sous(mix(acc, PAPER, 0.10), encre)
        pri_edge = acc_hi
    return {
        "ACC": acc, "ACC_HI": acc_hi, "ACC_LIGHT": acc_light,
        "ACC_LO": acc_lo, "ACC_DIM": mix(acc, PANEL, 0.55),
        "ACC_TEXT": readable(acc, PANEL),
        "ACC_INK": encre,
        "PRI_TOP": pri_top, "PRI_BOTTOM": pri_bottom,
        "PRI_HOVER_TOP": pri_hover_top, "PRI_EDGE": pri_edge,
        "SEL_SOFT": with_alpha(acc, 0.10),
        "SEL_MED": with_alpha(acc, 0.20),
        "SEL_STRONG": with_alpha(acc, 0.32),
        "BTN_TOP": "#272E3A", "BTN_BOTTOM": "#1F2530", "BTN_EDGE": "#3A4352",
        "BTN_HOVER_TOP": mix("#272E3A", acc, 0.16),
        "BTN_HOVER_BOTTOM": mix("#1F2530", acc, 0.10),
        "BTN_PRESS": mix(PANEL_LO, acc, 0.12),
        "HDR_HOVER": mix(PANEL, acc, 0.10),
        "SCROLL": mix(PANEL_HI, PAD_WHITE, 0.10),
        "SCROLL_HI": mix(PANEL_HI, acc, 0.50),
        "DANGER_BG": mix(PANEL_HI, PAD_RED, 0.12),
        "DANGER_HOVER": mix(PANEL_HI, PAD_RED, 0.28),
        "DANGER_BORDER": mix(BORDER, PAD_RED, 0.40),
        "INK": INK, "GREY_LIGHT": GREY_LIGHT, "TEXT": TEXT,
        "TEXT_SOFT": TEXT_SOFT, "TEXT_MUTED": TEXT_MUTED,
        "PANEL": PANEL, "PANEL_HI": PANEL_HI, "PANEL_LO": PANEL_LO,
        "PAD_WHITE": PAD_WHITE, "PAD_RED": PAD_RED,
        "BORDER": BORDER, "BORDER_SOFT": BORDER_SOFT, "BORDER_HI": BORDER_HI,
        "ALT_ROW": ALT_ROW, "GRID": GRID,
        "INPUT_BG": INPUT_BG, "INPUT_FOCUS": INPUT_FOCUS,
        "CHROME": CHROME, "OLED_BG": OLED_BG,
        "IMG_DOWN": _asset("chevron-down", GREY_LIGHT, 12),
        "IMG_DOWN_HI": _asset("chevron-down", acc_hi, 12),
        "IMG_UP_HI": _asset("chevron-up", acc_hi, 12),
        "IMG_CHECK_INK": _asset("check", encre if encre == INK else PAD_WHITE, 14),
        "IMG_CHECK_ACC": _asset("check", acc_hi, 14),
        "IMG_DASH_INK": _asset("dash", PANEL_LO, 14),
        "IMG_DOT_INK": _asset("dot", encre if encre == INK else PAD_WHITE, 10),
    }


def accent_qss(accent: str) -> str:
    """La seule partie colorée de la feuille, à la teinte donnée.

    C'est ce que chaque page pose sur elle-même : ses boutons, sélections,
    onglets, cases et curseurs prennent alors **sa** couleur, et l'on sait
    où l'on est même sans regarder la navigation.
    """
    try:
        return _QSS_ACCENT.substitute(accent_values(accent))
    except Exception:  # pragma: no cover - modèle incohérent : ne jamais casser l'UI
        log.exception("Partie colorée du QSS impossible (%s)", accent)
        return ""


def qss(accent: str = GOLD) -> str:
    """Feuille de style complète de l'application, pour l'accent donné."""
    try:
        return (_QSS_BASE.substitute(_base_values())
                + _QSS_ACCENT.substitute(accent_values(accent)))
    except Exception:  # pragma: no cover - modèle incohérent : ne jamais casser l'UI
        log.exception("Construction du QSS impossible — style minimal appliqué")
        return "QWidget {{ background-color: {}; color: {}; }}".format(PANEL_LO, PAD_WHITE)


def palette(accent: str = GOLD) -> QPalette:
    """Palette Qt assortie au thème (pour ce que le QSS ne peint pas)."""
    acc = QColor(_valid_accent(accent))
    p = QPalette()
    roles = QPalette.ColorRole
    p.setColor(roles.Window, QColor(PANEL_LO))
    p.setColor(roles.WindowText, QColor(PAD_WHITE))
    p.setColor(roles.Base, QColor(PANEL))
    p.setColor(roles.AlternateBase, QColor(ALT_ROW))
    p.setColor(roles.ToolTipBase, QColor(OLED_BG))
    p.setColor(roles.ToolTipText, QColor(PAD_WHITE))
    p.setColor(roles.Text, QColor(PAD_WHITE))
    p.setColor(roles.PlaceholderText, QColor(GREY))
    p.setColor(roles.Button, QColor(PANEL_HI))
    p.setColor(roles.ButtonText, QColor(PAD_WHITE))
    p.setColor(roles.BrightText, QColor(PAD_AMBER))
    p.setColor(roles.Link, acc)
    p.setColor(roles.LinkVisited, QColor(mix(acc.name(), INK, 0.35)))
    p.setColor(roles.Highlight, acc)
    p.setColor(roles.HighlightedText, QColor(INK))
    p.setColor(roles.Light, QColor(PANEL_HI))
    p.setColor(roles.Midlight, QColor(BORDER))
    p.setColor(roles.Dark, QColor(PANEL_LO))
    p.setColor(roles.Mid, QColor(BORDER_SOFT))
    p.setColor(roles.Shadow, QColor("#000000"))
    dis = QPalette.ColorGroup.Disabled
    p.setColor(dis, roles.WindowText, QColor(TEXT_MUTED))
    p.setColor(dis, roles.Text, QColor(TEXT_MUTED))
    p.setColor(dis, roles.ButtonText, QColor(TEXT_MUTED))
    p.setColor(dis, roles.Highlight, QColor(PANEL_HI))
    p.setColor(dis, roles.HighlightedText, QColor(GREY))
    return p


def apply_theme(app, accent: str = GOLD) -> None:
    """Applique le thème complet (style Fusion + palette + QSS + police)."""
    acc = _valid_accent(accent)
    try:
        app.setStyle("Fusion")
    except Exception:  # pragma: no cover - style indisponible
        log.exception("Style « Fusion » indisponible")
    try:
        QFont.insertSubstitutions(FONT_UI, [FONT_UI_FALLBACK, "Noto Sans"])
        QFont.insertSubstitutions(FONT_MONO, [FONT_MONO_FALLBACK, "DejaVu Sans Mono"])
        font = QFont(FONT_UI, 10)
        font.setStyleHint(QFont.StyleHint.SansSerif)
        app.setFont(font)
    except Exception:  # pragma: no cover
        log.exception("Police de l'interface non appliquée")
    try:
        app.setPalette(palette(acc))
    except Exception:  # pragma: no cover
        log.exception("Palette non appliquée")
    app.setStyleSheet(qss(acc))
    log.debug("Thème appliqué (accent %s)", acc)
