# -*- coding: utf-8 -*-
"""Identité graphique de Deluge Companion.

Reprend la palette du « Guide du Synthstrom Deluge » : fond `PANEL_LO`,
panneaux `PANEL`, surfaces relevées `PANEL_HI`, accent unique **or**,
carrés arrondis façon pads et trait doré sous les titres.

Le module fournit la palette, quelques utilitaires de couleur, la feuille de
style complète (`qss`) et son application à une `QApplication` (`apply_theme`).
Les petites images nécessaires au QSS (chevrons, coches, puces) sont dessinées
au vol en QPainter et mises en cache sur disque — aucun fichier externe n'est
livré avec l'application.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from string import Template

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPalette, QPen, QPolygonF
from PyQt6.QtCore import QPointF

from delugeapp.config import CONFIG_DIR

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Palette (identique au guide papier — ne pas modifier sans mettre à jour le guide)
# ---------------------------------------------------------------------------
INK = "#15181E"
INK_SOFT = "#3B424E"
GREY = "#7A828F"
GREY_LIGHT = "#C3C9D2"
PAPER = "#FFFFFF"
PAPER_WARM = "#FAF8F4"

PANEL = "#1C1F26"
PANEL_HI = "#2A2E37"
PANEL_LO = "#101319"

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

PAD_CYCLE = [PAD_RED, PAD_ORANGE, PAD_AMBER, PAD_YELLOW, PAD_GREEN, PAD_MINT,
             PAD_CYAN, PAD_BLUE, PAD_INDIGO, PAD_PURPLE, PAD_MAGENTA, PAD_PINK]

ACCENT = "#1F7A8C"
ACCENT_2 = "#C4543C"
WASH = "#EEF1F5"
WASH_2 = "#F6EEE4"

# Teintes dérivées, propres à l'interface
BORDER = "#2F343E"          # bordure standard
BORDER_SOFT = "#242833"     # bordure discrète (panneaux)
BORDER_HI = "#3A404C"       # bordure survolée
ALT_ROW = "#191D24"         # ligne alternée des tables
INPUT_BG = "#171A21"        # fond des champs de saisie
INPUT_FOCUS = "#1B1F27"
TEXT = PAD_WHITE
TEXT_DIM = GREY_LIGHT
TEXT_MUTED = "#5A6270"
GRID = "#23272F"

FONT_UI = "Segoe UI"
FONT_MONO = "Consolas"
FONT_UI_FALLBACK = "DejaVu Sans"
FONT_MONO_FALLBACK = "Cascadia Mono"
RADIUS = 8
PAD = 12

#: Dossier de cache des micro-images du QSS (chevrons, coches…).
ASSET_DIR = CONFIG_DIR / "cache" / "theme"

__all__ = [
    "INK", "INK_SOFT", "GREY", "GREY_LIGHT", "PAPER", "PAPER_WARM",
    "PANEL", "PANEL_HI", "PANEL_LO", "GOLD", "GOLD_HI", "GOLD_LO",
    "PAD_RED", "PAD_ORANGE", "PAD_AMBER", "PAD_YELLOW", "PAD_GREEN", "PAD_MINT",
    "PAD_CYAN", "PAD_BLUE", "PAD_INDIGO", "PAD_PURPLE", "PAD_MAGENTA", "PAD_PINK",
    "PAD_OFF", "PAD_DIM", "PAD_WHITE", "PAD_CYCLE",
    "ACCENT", "ACCENT_2", "WASH", "WASH_2",
    "FONT_UI", "FONT_MONO", "RADIUS", "PAD",
    "qss", "apply_theme", "pad_color", "category_color", "severity_color",
    "mix", "with_alpha", "text_on", "palette",
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


def luminance(c: str) -> float:
    """Luminance perçue 0..1 (pondération ITU-R BT.601)."""
    r, g, b = _rgb(c)
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255.0


def text_on(bg: str) -> str:
    """Couleur de texte lisible sur le fond donné (encre ou blanc de pad)."""
    return INK if luminance(bg) > 0.58 else PAD_WHITE


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


_SEVERITY_COLORS = {
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
}


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
                raise OSError("écriture PNG refusée : {}".format(path))
        value = 'url("{}")'.format(path.as_posix())
    except Exception:  # pragma: no cover - cache non accessible : on dégrade
        log.exception("Micro-image de thème indisponible (%s) — repli sans image", kind)
        value = "none"
    _ASSET_CACHE[key] = value
    return value


# ---------------------------------------------------------------------------
# Feuille de style
# ---------------------------------------------------------------------------
_QSS = Template(r"""
/* ======================================================================
   Deluge Companion — feuille de style
   Fond PANEL_LO, panneaux PANEL, accent unique or, coins arrondis.
   ====================================================================== */

* { outline: 0; }

QWidget {
    color: ${TEXT};
    font-family: "${FONT_UI}", "${FONT_UI_FALLBACK}", "Noto Sans", sans-serif;
    font-size: 10pt;
    selection-background-color: ${SEL_STRONG};
    selection-color: ${TEXT};
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

/* --- Typographie applicative ---------------------------------------- */
QLabel[role="h1"]        { font-size: 17pt; font-weight: 600; color: ${TEXT}; }
QLabel[role="title"]     { font-size: 13pt; font-weight: 600; color: ${TEXT}; }
QLabel[role="section"]   { font-size: 11pt; font-weight: 600; color: ${TEXT};
                           letter-spacing: 1px; text-transform: uppercase; }
QLabel[role="subtitle"], QLabel[role="hint"] { font-size: 9pt; color: ${GREY}; }
QLabel[role="value"]     { font-size: 22pt; font-weight: 600; color: ${TEXT}; }
QLabel[role="accent"]    { color: ${ACC_HI}; font-weight: 600; }
QLabel[role="mono"], QLabel#Mono, QTextEdit#Mono, QPlainTextEdit#Mono {
    font-family: "${FONT_MONO}", "${FONT_MONO_FALLBACK}", monospace; font-size: 9pt;
}

/* --- Conteneurs ------------------------------------------------------ */
QFrame#Card, QFrame[card="true"], QGroupBox {
    background-color: ${PANEL};
    border: 1px solid ${BORDER_SOFT};
    border-radius: ${R_LG}px;
}
QFrame#Card:hover, QFrame[card="true"]:hover { border-color: ${BORDER}; }
QFrame#Tile, QFrame[tile="true"] {
    background-color: ${PANEL};
    border: 1px solid ${BORDER_SOFT};
    border-left: 3px solid ${ACC};
    border-radius: ${R_LG}px;
}
QFrame#Header, QWidget#Header {
    background-color: ${PANEL};
    border: none;
    border-bottom: 1px solid ${BORDER_SOFT};
}
QFrame#Sidebar, QWidget#Sidebar {
    background-color: ${PANEL};
    border: none;
    border-right: 1px solid ${BORDER_SOFT};
}
QFrame#Rule, QFrame[role="rule"] {
    background-color: ${ACC};
    border: none;
    min-height: 2px; max-height: 2px;
    border-radius: 1px;
}
QFrame[frameShape="4"] { background-color: ${BORDER}; border: none; min-height: 1px; max-height: 1px; }
QFrame[frameShape="5"] { background-color: ${BORDER}; border: none; min-width: 1px; max-width: 1px; }
QGroupBox {
    margin-top: 16px;
    padding: 14px 10px 10px 10px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px; padding: 0 6px;
    color: ${ACC_HI};
}

/* --- Boutons --------------------------------------------------------- */
QPushButton {
    background-color: ${BTN_BG};
    color: ${TEXT};
    border: 1px solid ${BORDER};
    border-radius: ${R}px;
    padding: 6px 14px;
    min-height: 18px;
    font-weight: 500;
}
QPushButton:hover     { background-color: ${BTN_HOVER}; border-color: ${ACC_LO}; }
QPushButton:pressed   { background-color: ${BTN_PRESS}; border-color: ${ACC}; }
QPushButton:checked   { background-color: ${SEL_MED}; border-color: ${ACC}; color: ${ACC_HI}; }
QPushButton:checked:hover { background-color: ${SEL_STRONG}; }
QPushButton:focus     { border-color: ${ACC}; }
QPushButton:default   { border-color: ${ACC_LO}; }
QPushButton:disabled  { background-color: ${PANEL}; color: ${TEXT_MUTED}; border-color: ${BORDER_SOFT}; }
QPushButton:flat      { background: transparent; border-color: transparent; }
QPushButton:flat:hover { background-color: ${SEL_SOFT}; }

QPushButton#Primary, QPushButton[accent="true"] {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                      stop:0 ${ACC_HI}, stop:1 ${ACC});
    color: ${INK};
    border: 1px solid ${ACC_LO};
    font-weight: 600;
}
QPushButton#Primary:hover, QPushButton[accent="true"]:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                      stop:0 ${ACC_LIGHT}, stop:1 ${ACC_HI});
}
QPushButton#Primary:pressed, QPushButton[accent="true"]:pressed {
    background-color: ${ACC_LO}; color: ${PAD_WHITE};
}
QPushButton#Primary:disabled, QPushButton[accent="true"]:disabled {
    background-color: ${PANEL_HI}; color: ${TEXT_MUTED}; border-color: ${BORDER_SOFT};
}
QPushButton[danger="true"] {
    background-color: ${DANGER_BG}; color: ${PAD_RED}; border-color: ${DANGER_BORDER};
}
QPushButton[danger="true"]:hover  { background-color: ${DANGER_HOVER}; border-color: ${PAD_RED}; }
QPushButton[danger="true"]:pressed { background-color: ${PAD_RED}; color: ${INK}; }

QToolButton {
    background: transparent;
    color: ${GREY_LIGHT};
    border: 1px solid transparent;
    border-radius: ${R}px;
    padding: 4px 6px;
}
QToolButton:hover   { background-color: ${SEL_SOFT}; color: ${TEXT}; border-color: ${ACC_DIM}; }
QToolButton:pressed { background-color: ${SEL_MED}; }
QToolButton:checked { background-color: ${SEL_MED}; color: ${ACC_HI}; border-color: ${ACC}; }
QToolButton:disabled { color: ${TEXT_MUTED}; }
QToolButton::menu-indicator { image: ${IMG_DOWN}; width: 9px; height: 9px;
                              subcontrol-position: right center; right: 3px; }
QToolButton[popupMode="1"] { padding-right: 16px; }

/* --- Rail de navigation --------------------------------------------- */
QPushButton#NavButton, QToolButton#NavButton,
QPushButton[nav="true"], QToolButton[nav="true"] {
    background: transparent;
    color: ${GREY_LIGHT};
    border: none;
    border-left: 3px solid transparent;
    border-radius: ${R}px;
    padding: 9px 10px;
    text-align: left;
    font-weight: 500;
}
QPushButton#NavButton:hover, QToolButton#NavButton:hover,
QPushButton[nav="true"]:hover, QToolButton[nav="true"]:hover {
    background-color: ${SEL_SOFT}; color: ${TEXT};
}
QPushButton#NavButton:checked, QToolButton#NavButton:checked,
QPushButton[nav="true"]:checked, QToolButton[nav="true"]:checked {
    background-color: ${SEL_MED};
    color: ${ACC_HI};
    border-left: 3px solid ${ACC};
    font-weight: 600;
}

/* --- Saisie ---------------------------------------------------------- */
QLineEdit, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit, QTextBrowser,
QDateEdit, QTimeEdit, QDateTimeEdit, QKeySequenceEdit {
    background-color: ${INPUT_BG};
    color: ${TEXT};
    border: 1px solid ${BORDER};
    border-radius: ${R}px;
    padding: 5px 9px;
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
QLineEdit#Search, QLineEdit[search="true"] {
    padding-left: 30px; border-radius: 15px; min-height: 22px;
}
QTextBrowser { padding: 10px; }

QSpinBox::up-button, QDoubleSpinBox::up-button,
QDateEdit::up-button, QTimeEdit::up-button {
    subcontrol-origin: border; subcontrol-position: top right;
    width: 17px; margin: 2px 2px 0 0;
    border: none; border-radius: 4px; background: transparent;
}
QSpinBox::down-button, QDoubleSpinBox::down-button,
QDateEdit::down-button, QTimeEdit::down-button {
    subcontrol-origin: border; subcontrol-position: bottom right;
    width: 17px; margin: 0 2px 2px 0;
    border: none; border-radius: 4px; background: transparent;
}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
    background-color: ${SEL_MED};
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
    background-color: ${INPUT_BG};
    color: ${TEXT};
    border: 1px solid ${BORDER};
    border-radius: ${R}px;
    padding: 5px 9px;
    padding-right: 26px;
    min-height: 18px;
}
QComboBox:hover { border-color: ${BORDER_HI}; }
QComboBox:focus, QComboBox:on { border-color: ${ACC}; background-color: ${INPUT_FOCUS}; }
QComboBox:disabled { background-color: ${PANEL}; color: ${TEXT_MUTED}; border-color: ${BORDER_SOFT}; }
QComboBox::drop-down {
    subcontrol-origin: padding; subcontrol-position: top right;
    width: 24px; border: none; background: transparent;
}
QComboBox::down-arrow { image: ${IMG_DOWN}; width: 11px; height: 11px; }
QComboBox::down-arrow:on, QComboBox::down-arrow:hover { image: ${IMG_DOWN_HI}; }
QComboBox::down-arrow:disabled { image: none; }
QComboBox QAbstractItemView {
    background-color: ${PANEL};
    border: 1px solid ${BORDER_HI};
    border-radius: ${R}px;
    padding: 4px;
    margin-top: 2px;
    outline: 0;
    selection-background-color: ${SEL_MED};
    selection-color: ${ACC_HI};
}
QComboBox QAbstractItemView::item { min-height: 22px; padding: 3px 8px; border-radius: 5px; }
QComboBox QAbstractItemView::item:hover { background-color: ${SEL_SOFT}; }

/* --- Vues (tables, arbres, listes) ----------------------------------- */
QAbstractItemView {
    background-color: ${PANEL};
    alternate-background-color: ${ALT_ROW};
    color: ${TEXT};
    border: 1px solid ${BORDER_SOFT};
    border-radius: ${R}px;
    gridline-color: ${GRID};
    selection-background-color: ${SEL_STRONG};
    selection-color: ${TEXT};
    outline: 0;
}
QTableView, QTreeView, QListView { show-decoration-selected: 1; }
QTableView::item, QTreeView::item, QListView::item {
    padding: 4px 6px; border: none; color: ${TEXT};
}
QTableView::item:hover, QTreeView::item:hover, QListView::item:hover {
    background-color: ${SEL_SOFT};
}
QTableView::item:selected, QTreeView::item:selected, QListView::item:selected {
    background-color: ${SEL_STRONG}; color: ${TEXT};
}
QTableView::item:selected:!active, QTreeView::item:selected:!active,
QListView::item:selected:!active { background-color: ${SEL_MED}; color: ${TEXT}; }
QTableView::item:disabled, QTreeView::item:disabled { color: ${TEXT_MUTED}; }
QListView::item { border-radius: 6px; margin: 1px 2px; }
QTreeView::item { border-radius: 5px; }
QTreeView::branch { background: transparent; }
QTreeView::branch:has-children:!has-siblings:closed,
QTreeView::branch:closed:has-children:has-siblings { image: ${IMG_RIGHT}; }
QTreeView::branch:open:has-children:!has-siblings,
QTreeView::branch:open:has-children:has-siblings { image: ${IMG_DOWN}; }
QHeaderView { background: transparent; border: none; }
QHeaderView::section {
    background-color: ${PANEL_HI};
    color: ${GREY_LIGHT};
    padding: 6px 8px;
    border: none;
    border-right: 1px solid ${PANEL_LO};
    border-bottom: 2px solid ${ACC_LO};
    font-weight: 600;
}
QHeaderView::section:hover   { background-color: ${HDR_HOVER}; color: ${TEXT}; }
QHeaderView::section:checked { color: ${ACC_HI}; border-bottom-color: ${ACC}; }
QHeaderView::section:first   { border-top-left-radius: ${R}px; }
QHeaderView::section:last    { border-right: none; border-top-right-radius: ${R}px; }
QHeaderView::section:vertical {
    border-right: 2px solid ${ACC_LO}; border-bottom: 1px solid ${PANEL_LO};
}
QHeaderView::down-arrow { image: ${IMG_DOWN_HI}; width: 9px; height: 9px;
                          subcontrol-position: center right; right: 6px; }
QHeaderView::up-arrow   { image: ${IMG_UP_HI}; width: 9px; height: 9px;
                          subcontrol-position: center right; right: 6px; }
QTableCornerButton::section { background-color: ${PANEL_HI}; border: none; }

/* --- Barres de défilement (fines, sans flèche) ------------------------ */
QScrollBar:vertical   { background: transparent; width: 11px; margin: 2px 2px 2px 0; border: none; }
QScrollBar:horizontal { background: transparent; height: 11px; margin: 0 2px 2px 2px; border: none; }
QScrollBar::handle:vertical {
    background-color: ${SCROLL}; border-radius: 4px; min-height: 30px; margin: 0 2px;
}
QScrollBar::handle:horizontal {
    background-color: ${SCROLL}; border-radius: 4px; min-width: 30px; margin: 2px 0;
}
QScrollBar::handle:hover   { background-color: ${SCROLL_HI}; }
QScrollBar::handle:pressed { background-color: ${ACC}; }
QScrollBar::add-line, QScrollBar::sub-line {
    width: 0; height: 0; border: none; background: transparent;
}
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QAbstractScrollArea::corner { background: transparent; border: none; }

/* --- Curseurs et jauges ---------------------------------------------- */
QSlider { background: transparent; }
QSlider::groove:horizontal { height: 5px; background-color: ${PANEL_HI}; border-radius: 2px; }
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 ${ACC_LO}, stop:1 ${ACC});
    border-radius: 2px;
}
QSlider::add-page:horizontal { background-color: ${PANEL_HI}; border-radius: 2px; }
QSlider::handle:horizontal {
    width: 14px; height: 14px; margin: -5px 0; border-radius: 7px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 ${ACC_HI}, stop:1 ${ACC});
    border: 1px solid ${ACC_LO};
}
QSlider::handle:horizontal:hover { background: ${ACC_HI}; border-color: ${ACC_HI}; }
QSlider::groove:vertical { width: 5px; background-color: ${PANEL_HI}; border-radius: 2px; }
QSlider::add-page:vertical {
    background: qlineargradient(x1:0, y1:1, x2:0, y2:0, stop:0 ${ACC_LO}, stop:1 ${ACC});
    border-radius: 2px;
}
QSlider::sub-page:vertical { background-color: ${PANEL_HI}; border-radius: 2px; }
QSlider::handle:vertical {
    width: 14px; height: 14px; margin: 0 -5px; border-radius: 7px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 ${ACC_HI}, stop:1 ${ACC});
    border: 1px solid ${ACC_LO};
}
QSlider::handle:disabled { background: ${PANEL_HI}; border-color: ${BORDER}; }

QProgressBar {
    background-color: ${PANEL_HI};
    border: none;
    border-radius: 6px;
    min-height: 12px; max-height: 18px;
    text-align: center;
    color: ${GREY_LIGHT};
    font-size: 8pt;
}
QProgressBar::chunk {
    border-radius: 6px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 ${ACC_LO}, stop:0.55 ${ACC}, stop:1 ${ACC_HI});
}
QProgressBar[thin="true"] { min-height: 6px; max-height: 6px; border-radius: 3px; }
QProgressBar[thin="true"]::chunk { border-radius: 3px; }

/* --- Onglets ---------------------------------------------------------- */
QTabWidget::pane {
    border: 1px solid ${BORDER_SOFT};
    border-radius: ${R_LG}px;
    background-color: ${PANEL};
    top: -1px;
}
QTabWidget::tab-bar { alignment: left; left: 6px; }
QTabBar { background: transparent; qproperty-drawBase: 0; }
QTabBar::tab {
    background: transparent;
    color: ${GREY};
    border: none;
    border-bottom: 2px solid transparent;
    border-top-left-radius: ${R}px;
    border-top-right-radius: ${R}px;
    padding: 7px 16px;
    margin-right: 2px;
    min-width: 40px;
}
QTabBar::tab:hover    { color: ${TEXT}; background-color: ${SEL_SOFT}; }
QTabBar::tab:selected { color: ${ACC_HI}; background-color: ${PANEL};
                        border-bottom: 2px solid ${ACC}; font-weight: 600; }
QTabBar::tab:disabled { color: ${TEXT_MUTED}; }
QTabBar::tab:left, QTabBar::tab:right { padding: 12px 7px; }

/* --- Séparateurs ------------------------------------------------------ */
QSplitter { background: transparent; }
QSplitter::handle { background: transparent; }
QSplitter::handle:horizontal { width: 6px; }
QSplitter::handle:vertical   { height: 6px; }
QSplitter::handle:hover      { background-color: ${SEL_SOFT}; }
QSplitter::handle:pressed    { background-color: ${SEL_MED}; }

/* --- Menus et barres -------------------------------------------------- */
QMenuBar {
    background-color: ${PANEL};
    color: ${GREY_LIGHT};
    border: none;
    border-bottom: 1px solid ${BORDER_SOFT};
    padding: 2px 4px;
}
QMenuBar::item { background: transparent; padding: 5px 10px; border-radius: 6px; }
QMenuBar::item:selected { background-color: ${SEL_MED}; color: ${ACC_HI}; }
QMenuBar::item:pressed  { background-color: ${SEL_STRONG}; color: ${ACC_HI}; }
QMenu {
    background-color: ${PANEL};
    color: ${TEXT};
    border: 1px solid ${BORDER_HI};
    border-radius: ${R_LG}px;
    padding: 6px;
}
QMenu::item { background: transparent; padding: 6px 26px 6px 28px; border-radius: 6px; }
QMenu::item:selected { background-color: ${SEL_MED}; color: ${ACC_HI}; }
QMenu::item:disabled { color: ${TEXT_MUTED}; }
QMenu::separator { height: 1px; background-color: ${BORDER}; margin: 5px 10px; }
QMenu::icon { left: 8px; }
QMenu::indicator { width: 14px; height: 14px; left: 9px; }
QMenu::indicator:checked { image: ${IMG_CHECK_GOLD}; }
QMenu::right-arrow { image: ${IMG_RIGHT}; width: 9px; height: 9px; right: 8px; }
QToolBar {
    background-color: ${PANEL};
    border: none;
    border-bottom: 1px solid ${BORDER_SOFT};
    spacing: 4px; padding: 4px;
}
QToolBar::separator { background-color: ${BORDER}; width: 1px; margin: 5px 6px; }
QStatusBar {
    background-color: ${PANEL};
    color: ${GREY_LIGHT};
    border: none;
    border-top: 1px solid ${BORDER_SOFT};
}
QStatusBar::item { border: none; }
QStatusBar QLabel { color: ${GREY_LIGHT}; padding: 0 4px; }
QSizeGrip { background: transparent; width: 12px; height: 12px; }
QToolTip {
    background-color: ${PANEL_HI};
    color: ${TEXT};
    border: 1px solid ${ACC_LO};
    border-radius: 6px;
    padding: 5px 8px;
    font-size: 9pt;
    opacity: 240;
}

/* --- Cases et boutons radio ------------------------------------------- */
QCheckBox, QRadioButton { spacing: 8px; padding: 2px; color: ${TEXT}; }
QCheckBox:disabled, QRadioButton:disabled { color: ${TEXT_MUTED}; }
QCheckBox::indicator, QRadioButton::indicator { width: 16px; height: 16px; }
QCheckBox::indicator {
    border: 1px solid ${BORDER_HI}; border-radius: 5px; background-color: ${INPUT_BG};
}
QCheckBox::indicator:hover { border-color: ${ACC}; }
QCheckBox::indicator:checked {
    background-color: ${ACC}; border-color: ${ACC}; image: ${IMG_CHECK_DARK};
}
QCheckBox::indicator:checked:hover { background-color: ${ACC_HI}; border-color: ${ACC_HI}; }
QCheckBox::indicator:indeterminate {
    background-color: ${ACC_LO}; border-color: ${ACC_LO}; image: ${IMG_DASH_DARK};
}
QCheckBox::indicator:disabled { background-color: ${PANEL}; border-color: ${BORDER_SOFT}; }
QRadioButton::indicator {
    border: 1px solid ${BORDER_HI}; border-radius: 8px; background-color: ${INPUT_BG};
}
QRadioButton::indicator:hover { border-color: ${ACC}; }
QRadioButton::indicator:checked {
    background-color: ${ACC}; border-color: ${ACC}; image: ${IMG_DOT_DARK};
}
QRadioButton::indicator:disabled { background-color: ${PANEL}; border-color: ${BORDER_SOFT}; }

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
QToolBox::tab {
    background-color: ${PANEL_HI}; color: ${GREY_LIGHT};
    border: 1px solid ${BORDER_SOFT}; border-radius: ${R}px; padding: 6px;
}
QToolBox::tab:selected { color: ${ACC_HI}; border-color: ${ACC_LO}; }
QListWidget#Variations::item { margin: 3px; padding: 6px; border-radius: ${R}px; }
""")


def _theme_values(accent: str) -> dict[str, str]:
    """Calcule toutes les valeurs injectées dans la feuille de style."""
    acc = accent if accent and accent.startswith("#") else GOLD
    acc_hi = mix(acc, PAPER, 0.32)
    acc_light = mix(acc, PAPER, 0.55)
    acc_lo = mix(acc, INK, 0.45)
    acc_dim = mix(acc, PANEL, 0.62)
    return {
        # palette de base
        "INK": INK, "GREY": GREY, "GREY_LIGHT": GREY_LIGHT,
        "PANEL": PANEL, "PANEL_HI": PANEL_HI, "PANEL_LO": PANEL_LO,
        "PAD_WHITE": PAD_WHITE, "PAD_RED": PAD_RED,
        "TEXT": TEXT, "TEXT_MUTED": TEXT_MUTED,
        "BORDER": BORDER, "BORDER_SOFT": BORDER_SOFT, "BORDER_HI": BORDER_HI,
        "ALT_ROW": ALT_ROW, "GRID": GRID,
        "INPUT_BG": INPUT_BG, "INPUT_FOCUS": INPUT_FOCUS,
        # accent
        "ACC": acc, "ACC_HI": acc_hi, "ACC_LIGHT": acc_light,
        "ACC_LO": acc_lo, "ACC_DIM": acc_dim,
        "SEL_SOFT": with_alpha(acc, 0.10),
        "SEL_MED": with_alpha(acc, 0.20),
        "SEL_STRONG": with_alpha(acc, 0.34),
        # surfaces dérivées
        "BTN_BG": PANEL_HI,
        "BTN_HOVER": mix(PANEL_HI, acc, 0.16),
        "BTN_PRESS": mix(PANEL_LO, acc, 0.10),
        "HDR_HOVER": mix(PANEL_HI, acc, 0.14),
        "SCROLL": mix(PANEL_HI, PAD_WHITE, 0.10),
        "SCROLL_HI": mix(PANEL_HI, acc, 0.45),
        "DANGER_BG": mix(PANEL_HI, PAD_RED, 0.12),
        "DANGER_HOVER": mix(PANEL_HI, PAD_RED, 0.28),
        "DANGER_BORDER": mix(BORDER, PAD_RED, 0.40),
        # typographie et géométrie
        "FONT_UI": FONT_UI, "FONT_UI_FALLBACK": FONT_UI_FALLBACK,
        "FONT_MONO": FONT_MONO, "FONT_MONO_FALLBACK": FONT_MONO_FALLBACK,
        "R": str(RADIUS), "R_LG": str(RADIUS + 2),
        # micro-images
        "IMG_DOWN": _asset("chevron-down", GREY_LIGHT, 12),
        "IMG_DOWN_HI": _asset("chevron-down", acc_hi, 12),
        "IMG_UP_HI": _asset("chevron-up", acc_hi, 12),
        "IMG_RIGHT": _asset("chevron-right", GREY_LIGHT, 12),
        "IMG_TRI_UP": _asset("tri-up", GREY_LIGHT, 10),
        "IMG_TRI_DOWN": _asset("tri-down", GREY_LIGHT, 10),
        "IMG_CHECK_DARK": _asset("check", PANEL_LO, 14),
        "IMG_CHECK_GOLD": _asset("check", acc_hi, 14),
        "IMG_DASH_DARK": _asset("dash", PANEL_LO, 14),
        "IMG_DOT_DARK": _asset("dot", PANEL_LO, 10),
    }


def qss(accent: str = GOLD) -> str:
    """Feuille de style complète de l'application, pour l'accent donné."""
    try:
        return _QSS.substitute(_theme_values(accent))
    except Exception:  # pragma: no cover - modèle incohérent : ne jamais casser l'UI
        log.exception("Construction du QSS impossible — style minimal appliqué")
        return "QWidget {{ background-color: {}; color: {}; }}".format(PANEL_LO, PAD_WHITE)


def palette(accent: str = GOLD) -> QPalette:
    """Palette Qt assortie au thème (pour ce que le QSS ne peint pas)."""
    acc = QColor(accent if accent.startswith("#") else GOLD)
    p = QPalette()
    roles = QPalette.ColorRole
    p.setColor(roles.Window, QColor(PANEL_LO))
    p.setColor(roles.WindowText, QColor(PAD_WHITE))
    p.setColor(roles.Base, QColor(PANEL))
    p.setColor(roles.AlternateBase, QColor(ALT_ROW))
    p.setColor(roles.ToolTipBase, QColor(PANEL_HI))
    p.setColor(roles.ToolTipText, QColor(PAD_WHITE))
    p.setColor(roles.Text, QColor(PAD_WHITE))
    p.setColor(roles.PlaceholderText, QColor(GREY))
    p.setColor(roles.Button, QColor(PANEL_HI))
    p.setColor(roles.ButtonText, QColor(PAD_WHITE))
    p.setColor(roles.BrightText, QColor(PAD_AMBER))
    p.setColor(roles.Link, acc)
    p.setColor(roles.LinkVisited, QColor(mix(accent, INK, 0.35)))
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
    acc = accent if accent and accent.startswith("#") else GOLD
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
