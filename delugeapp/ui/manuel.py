# -*- coding: utf-8 -*-
"""Le manuel de Noctiluca, en français et en anglais.

Le texte vit dans ``delugeapp/docs/manuel.<langue>.md``, un fichier par
langue. Ce module le lit, le met en page dans la typographie du *Guide du
Deluge* — Georgia pour le texte, Trebuchet pour les titres, surtitres d'or,
encadrés à filet de couleur, tableaux à en-tête pétrole — et l'affiche dans
une fenêtre à part : le sommaire en pads à gauche, la page de papier au
centre.

Le balisage
-----------

Volontairement petit, pour que le texte reste lisible tel quel :

==================================  =========================================
``%% …``                            commentaire, ignoré
``@partie id couleur | T | S``      ouverture de partie (treillis, chiffre)
``# Titre {#id page=Samples}``      chapitre ; ``page`` le lie à une page
``> phrase``                        l'accroche, juste sous le titre
``## Titre {#id}``                  section, ancre explicite
``### Titre``                       sous-section
``!!! astuce Titre``                encadré : astuce, attention, retenir,
                                    pro, atelier ; corps indenté de 4
``[[figure nom | légende | a ; b]]``  figure dessinée, libellés de la langue
``| a | b |``                       tableau, la première ligne en tête
``- …`` / ``1. …``                  listes ; ``1.`` donne des étapes
``**gras**``, ``*italique*``        —
```code` ``                        mot de la machine ou chemin
``[[Ctrl+R]]``                      une touche
``[Analyser]``                      le libellé d'un bouton de l'application
``[texte](#ancre)``                 renvoi dans le manuel
``[texte](app:Health#Doublons)``    ouvre une page de l'application
==================================  =========================================

**Les deux langues partagent leurs ancres** : la bascule garde la position
du lecteur, et un test exige les mêmes chapitres et sections, dans le même
ordre, des deux côtés.
"""

from __future__ import annotations

import html as _html
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from PyQt6.QtCore import QMarginsF, QSize, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QFontMetrics,
    QIcon,
    QImage,
    QKeySequence,
    QPageLayout,
    QPageSize,
    QPixmap,
    QShortcut,
    QTextCursor,
    QTextDocument,
)
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSplitter,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTextBrowser,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import i18n
from ..config import APP_NAME
from ..i18n import LANGUAGES, tr, untranslated
from . import icons, manuel_dessins as dessins
from .theme import GOLD, PAGE_COLORS

log = logging.getLogger(__name__)

#: Où vivent les deux textes du manuel.
DOSSIER = Path(__file__).resolve().parent.parent / "docs"

#: Largeur de la colonne de lecture, au plus : environ quatre-vingts signes
#: par ligne, la mesure d'une page du guide.
COLONNE_MAX = 780
#: Marge de part et d'autre de la colonne, au moins.
GOUTTIERE = 36

#: Encres du guide sur papier (``build/docxkit.py``).
ENCRE = "#1A1D23"
ENCRE_DOUCE = "#3B424E"
GRIS = "#6E7684"
SARCELLE = "#145F70"
OR = "#C79A22"
OR_SOMBRE = "#9A7610"
ROUILLE = "#A8422E"
PETROLE = "#1C4854"
ZEBRE = "#F2F5F7"
PAPIER = dessins.PAPIER
#: Fond d'une touche et d'un libellé de bouton.
FOND_TOUCHE = "#E3ECEF"
FOND_LIBELLE = "#EDE6D8"
#: Surlignage des résultats de recherche.
SURLIGNAGE = "#FFE08A"
SURLIGNAGE_COURANT = "#FFB347"

#: Les cinq encadrés du guide : couleur du filet, fond, encre du titre.
ENCADRES = {
    "astuce": ("#C79A22", "#FDF6E3", "#9A7610"),
    "attention": ("#A8422E", "#FBEDE9", "#A8422E"),
    "pro": ("#145F70", "#EAF2F4", "#145F70"),
    "retenir": ("#1F6B3A", "#EFF3EE", "#1F6B3A"),
    "atelier": ("#5B3E8C", "#F1EDF7", "#5B3E8C"),
}

#: Ce que le manuel écrit de lui-même, dans **sa** langue — qui peut ne pas
#: être celle de l'interface : on peut lire le manuel anglais dans
#: l'application en français.
LIBELLES = untranslated({
    "fr": {"astuce": "ASTUCE", "attention": "ATTENTION",
           "pro": "LE MOT DU PRO", "retenir": "À RETENIR",
           "atelier": "ATELIER", "partie": "PARTIE", "chapitre": "CHAPITRE",
           "figure": "Figure",
           "ouvrir": "Ouvrir cette page dans l'application",
           "pdf": "Noctiluca - Manuel.pdf"},
    "en": {"astuce": "TIP", "attention": "CAUTION",
           "pro": "FROM THE PROS", "retenir": "REMEMBER",
           "atelier": "WORKSHOP", "partie": "PART", "chapitre": "CHAPTER",
           "figure": "Figure",
           "ouvrir": "Open this page in the application",
           "pdf": "Noctiluca - Manual.pdf"},
})

#: Polices du guide, avec leurs replis hors de Windows.
_TEXTE = "font-family: Georgia, 'DejaVu Serif', serif;"
_TITRE = "font-family: 'Trebuchet MS', 'DejaVu Sans', 'Segoe UI', sans-serif;"
_CHASSE = "font-family: Consolas, 'Cascadia Mono', 'DejaVu Sans Mono', monospace;"


def chemin_source(langue: str) -> Path:
    """Le fichier du manuel dans cette langue."""
    return DOSSIER / ("manuel.%s.md" % i18n.normalize(langue))


# --------------------------------------------------------------------------- #
# Le document
# --------------------------------------------------------------------------- #

@dataclass
class Partie:
    numero: int
    ident: str
    titre: str
    sous_titre: str
    couleur: str


@dataclass
class Chapitre:
    numero: int
    ident: str
    titre: str
    partie: Partie | None
    couleur: str
    icone: str
    page: str = ""
    accroche: str = ""
    #: ``(ancre, titre)`` des sections, dans l'ordre.
    sections: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class Manuel:
    """Le manuel lu et mis en page, prêt pour la fenêtre."""

    langue: str
    parties: list[Partie] = field(default_factory=list)
    chapitres: list[Chapitre] = field(default_factory=list)
    html: str = ""
    #: Toutes les ancres, dans l'ordre du texte.
    ancres: list[str] = field(default_factory=list)
    #: Toutes les cibles de liens.
    liens: list[str] = field(default_factory=list)
    #: ``(nom, légende, libellés)`` de chaque figure.
    figures: list[tuple[str, str, list[str]]] = field(default_factory=list)
    #: Les libellés de boutons cités (``[Analyser]``).
    libelles: set[str] = field(default_factory=set)
    #: Ce qu'il faut dessiner, par adresse d'image (``manuel:…``).
    images: dict[str, tuple] = field(default_factory=dict)
    #: Les images qui prennent toute la largeur de la colonne.
    larges: set[str] = field(default_factory=set)
    #: Problèmes de balisage relevés à la lecture.
    erreurs: list[str] = field(default_factory=list)

    def chapitre_de_page(self, cle: str) -> Chapitre | None:
        """Le chapitre qui décrit la page ``cle`` (``Samples``…)."""
        for chapitre in self.chapitres:
            if chapitre.page == cle:
                return chapitre
        return None

    def chapitre_de(self, ancre: str) -> Chapitre | None:
        """Le chapitre qui contient l'ancre ``ancre``."""
        for chapitre in self.chapitres:
            if chapitre.ident == ancre or any(
                    a == ancre for a, _t in chapitre.sections):
                return chapitre
        return None

    def texte_brut(self) -> str:
        """Le texte sans balises, pour les tests et la recherche."""
        return _html.unescape(re.sub(r"<[^>]+>", " ", self.html))


def charger(langue: str) -> Manuel:
    """Lit et met en page le manuel de cette langue."""
    langue = i18n.normalize(langue)
    try:
        texte = chemin_source(langue).read_text(encoding="utf-8")
    except OSError as exc:
        log.error("manuel introuvable (%s) : %s", langue, exc)
        texte = ""
    return lire(texte, langue)


def lire(texte: str, langue: str) -> Manuel:
    """Le manuel, depuis son texte balisé."""
    lecteur = _Lecteur(i18n.normalize(langue))
    lecteur.lire(texte.splitlines())
    return lecteur.manuel


# --------------------------------------------------------------------------- #
# Lecture du balisage
# --------------------------------------------------------------------------- #

_ATTRIBUTS = re.compile(r"\{([^{}]*)\}\s*$")
_TITRE_MD = re.compile(r"^(#{1,3})\s+(.*)$")
_PUCE = re.compile(r"^[-*]\s+(.*)$")
_ETAPE = re.compile(r"^(\d+)[.)]\s+(.*)$")
_FIGURE = re.compile(r"^\[\[figure\s+(.*)\]\]\s*$")
_ENCADRE = re.compile(r"^!!!\s+(\w+)\s*(.*)$")
_PARTIE = re.compile(r"^@partie\s+(.*)$")

_CODE = re.compile(r"`([^`]+)`")
_TOUCHE = re.compile(r"\[\[([^\[\]]+)\]\]")
_LIEN = re.compile(r"\[([^\[\]]+)\]\(([^()\s]+)\)")
_BOUTON = re.compile(r"\[([^\[\]]+)\]")
_GRAS = re.compile(r"\*\*(.+?)\*\*")
_ITALIQUE = re.compile(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])")
_JETON = re.compile("\x00(\\d+)\x00")


def _attributs(texte: str) -> tuple[str, dict[str, str]]:
    """``Titre {#ancre page=Samples}`` -> ``("Titre", {...})``."""
    trouve = _ATTRIBUTS.search(texte)
    if not trouve:
        return texte.strip(), {}
    valeurs: dict[str, str] = {}
    for morceau in trouve.group(1).split():
        if morceau.startswith("#"):
            valeurs["id"] = morceau[1:]
        elif "=" in morceau:
            cle, valeur = morceau.split("=", 1)
            valeurs[cle.strip()] = valeur.strip()
    return texte[:trouve.start()].strip(), valeurs


def ancre_de(titre: str) -> str:
    """Une ancre tirée d'un titre, à défaut d'ancre explicite."""
    plat = unicodedata.normalize("NFKD", titre)
    plat = "".join(c for c in plat if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "-", plat).strip("-") or "section"


def _parts_de_colonnes(rangees: list[list[str]]) -> list[int]:
    """La largeur de chaque colonne d'un tableau, en pour cent.

    Qt partage sinon la largeur à parts égales : la colonne « Repère », qui
    ne contient qu'un chiffre, prenait le tiers du tableau. Chaque colonne
    reçoit une part de son plus long texte, bornée pour qu'aucune ne
    s'écrase ni n'écrase les autres.
    """
    colonnes = max(len(r) for r in rangees)
    longueurs = []
    for rang in range(colonnes):
        plus_long = max((len(re.sub(r"[\[\]`*]|\(#[^)]*\)|\(app:[^)]*\)",
                                    "", r[rang])) if rang < len(r) else 0)
                        for r in rangees)
        longueurs.append(min(55, max(6, plus_long)))
    total = float(sum(longueurs))
    parts = [max(10, int(round(100 * l / total))) for l in longueurs]
    excedent = sum(parts) - 100
    parts[parts.index(max(parts))] -= excedent
    return parts


def _typographie(texte: str, langue: str) -> str:
    """Les espaces insécables du français, devant ; : ! ? et dans « »."""
    if langue != "fr":
        return texte
    texte = re.sub(r"«\s+", "« ", texte)
    texte = re.sub(r"\s+»", " »", texte)
    return re.sub(r"\s+([:;!?])(?=\s|$|<|\x00)", " \\1", texte)


class _Lecteur:
    """Lit le texte ligne à ligne et compose le HTML."""

    def __init__(self, langue: str) -> None:
        self.langue = langue
        self.libelles = LIBELLES.get(langue, LIBELLES["fr"])
        self.manuel = Manuel(langue)
        self.partie: Partie | None = None
        self.chapitre: Chapitre | None = None
        self.morceaux: list[str] = []
        self.figures = 0

    # -- blocs -------------------------------------------------------------- #

    def lire(self, lignes: list[str]) -> None:
        lignes = [l for l in lignes if not l.startswith("%%")]
        self.morceaux.extend(self._blocs(lignes, au_niveau=True))
        self.manuel.html = (
            '<html><body style="%s font-size: 11.5pt; color: %s;">%s'
            '</body></html>' % (_TEXTE, ENCRE, "\n".join(self.morceaux)))

    def _blocs(self, lignes: list[str], au_niveau: bool = False) -> list[str]:
        """Le HTML d'une suite de lignes ; ``au_niveau`` autorise parties et
        titres (pas dans un encadré)."""
        sortie: list[str] = []
        i, n = 0, len(lignes)
        while i < n:
            ligne = lignes[i]
            nette = ligne.strip()
            if not nette:
                i += 1
                continue
            if au_niveau and _PARTIE.match(nette):
                sortie.append(self._partie(_PARTIE.match(nette).group(1)))
                i += 1
                continue
            titre = _TITRE_MD.match(nette) if au_niveau else None
            if titre:
                niveau = len(titre.group(1))
                if niveau == 1:
                    accroche, i = self._accroche(lignes, i + 1)
                    sortie.append(self._chapitre(titre.group(2), accroche))
                else:
                    sortie.append(self._section(niveau, titre.group(2)))
                    i += 1
                continue
            encadre = _ENCADRE.match(nette)
            if encadre:
                corps, i = self._indente(lignes, i + 1)
                sortie.append(self._encadre(encadre.group(1),
                                            encadre.group(2), corps))
                continue
            figure = _FIGURE.match(nette)
            if figure:
                sortie.append(self._figure(figure.group(1)))
                i += 1
                continue
            if nette.startswith("|"):
                j = i
                while j < n and lignes[j].strip().startswith("|"):
                    j += 1
                sortie.append(self._tableau([l.strip() for l in lignes[i:j]]))
                i = j
                continue
            if _PUCE.match(nette) or _ETAPE.match(nette):
                ordonnee = bool(_ETAPE.match(nette))
                elements, i = self._liste(lignes, i, ordonnee)
                sortie.append(self._etapes(elements) if ordonnee
                              else self._puces(elements))
                continue
            if nette.startswith("> "):
                texte, i = self._paragraphe(lignes, i, prefixe="> ")
                sortie.append(self._accroche_html(texte))
                continue
            texte, i = self._paragraphe(lignes, i)
            sortie.append(untranslated(
                '<p align="justify" style="margin-top: 0; '
                'margin-bottom: 10px; line-height: 150%%;">%s</p>')
                % self._en_ligne(texte))
        return sortie

    @staticmethod
    def _debut_de_bloc(nette: str) -> bool:
        return bool(not nette or _TITRE_MD.match(nette)
                    or _ENCADRE.match(nette) or _FIGURE.match(nette)
                    or nette.startswith("|") or _PUCE.match(nette)
                    or _ETAPE.match(nette) or _PARTIE.match(nette)
                    or nette.startswith("> "))

    def _paragraphe(self, lignes: list[str], i: int,
                    prefixe: str = "") -> tuple[str, int]:
        """Les lignes d'un paragraphe, jusqu'au prochain bloc."""
        morceaux = []
        while i < len(lignes):
            nette = lignes[i].strip()
            if prefixe:
                if not nette.startswith(prefixe):
                    break
                morceaux.append(nette[len(prefixe):])
            else:
                if morceaux and self._debut_de_bloc(nette):
                    break
                if not nette:
                    break
                morceaux.append(nette)
            i += 1
        return " ".join(morceaux), i

    def _accroche(self, lignes: list[str], i: int) -> tuple[str, int]:
        """L'accroche d'un chapitre : les lignes ``> `` qui le suivent."""
        while i < len(lignes) and not lignes[i].strip():
            i += 1
        if i < len(lignes) and lignes[i].strip().startswith("> "):
            return self._paragraphe(lignes, i, prefixe="> ")
        return "", i

    @staticmethod
    def _indente(lignes: list[str], i: int) -> tuple[list[str], int]:
        """Le corps indenté d'un encadré."""
        corps = []
        while i < len(lignes):
            ligne = lignes[i]
            if ligne.strip() and not ligne.startswith("    "):
                break
            corps.append(ligne[4:] if ligne.startswith("    ") else "")
            i += 1
        while corps and not corps[-1].strip():
            corps.pop()
        return corps, i

    def _liste(self, lignes: list[str], i: int,
               ordonnee: bool) -> tuple[list[str], int]:
        """Les éléments d'une liste ; une ligne indentée prolonge le
        précédent, une ligne vide suivie d'un autre élément ne la coupe
        pas."""
        motif = _ETAPE if ordonnee else _PUCE
        elements: list[str] = []
        while i < len(lignes):
            ligne = lignes[i]
            nette = ligne.strip()
            trouve = motif.match(nette)
            if trouve:
                elements.append(trouve.group(trouve.lastindex))
            elif nette and ligne.startswith("  ") and elements:
                elements[-1] += " " + nette
            elif not nette:
                suivante = i + 1
                while suivante < len(lignes) and not lignes[suivante].strip():
                    suivante += 1
                if suivante < len(lignes) and motif.match(
                        lignes[suivante].strip()):
                    i = suivante
                    continue
                break
            else:
                break
            i += 1
        return elements, i

    # -- éléments ----------------------------------------------------------- #

    def _partie(self, texte: str) -> str:
        champs = [c.strip() for c in texte.split("|")]
        tete = champs[0].split()
        ident = tete[0] if tete else "partie-%d" % (len(self.manuel.parties)
                                                    + 1)
        couleur = dessins.couleur_de(tete[1] if len(tete) > 1 else "GOLD")
        partie = Partie(len(self.manuel.parties) + 1, ident,
                        champs[1] if len(champs) > 1 else ident,
                        champs[2] if len(champs) > 2 else "", couleur)
        self.manuel.parties.append(partie)
        self.partie = partie
        self.chapitre = None
        self._ancre(ident)
        adresse = "manuel:ouverture/%d" % partie.numero
        self.manuel.images[adresse] = ("ouverture", partie.numero,
                                       partie.titre, partie.sous_titre,
                                       couleur)
        self.manuel.larges.add(adresse)
        # L'ancre se pose sur un texte : sur l'image seule, Qt la reportait
        # au paragraphe suivant, et le sommaire menait sous l'ouverture.
        return ('<p style="margin-top: 26px; margin-bottom: 0; '
                'font-size: 2pt;"><a name="%s">&nbsp;</a></p>'
                '<p style="margin-top: 0; margin-bottom: 8px;">'
                '<img src="%s" width="%d" /></p>'
                % (ident, adresse, COLONNE_MAX))

    def _chapitre(self, texte: str, accroche: str) -> str:
        titre, valeurs = _attributs(texte)
        ident = valeurs.get("id") or ancre_de(titre)
        page = valeurs.get("page", "")
        if page and page not in PAGE_COLORS:
            self.manuel.erreurs.append(untranslated("page inconnue : %s")
                                       % page)
            page = ""
        couleur = dessins.couleur_de(
            valeurs.get("couleur") or page,
            self.partie.couleur if self.partie else GOLD)
        icone = valeurs.get("icone") or dessins.ICONES_PAGES.get(page, "info")
        chapitre = Chapitre(len(self.manuel.chapitres) + 1, ident, titre,
                            self.partie, couleur, icone, page, accroche)
        self.manuel.chapitres.append(chapitre)
        self.chapitre = chapitre
        self._ancre(ident)

        pad = "manuel:pad/%s/%s" % (couleur.lstrip("#"), icone)
        self.manuel.images[pad] = ("pad", couleur, icone)
        regle = "manuel:filet/%s" % OR.lstrip("#")
        self.manuel.images[regle] = ("filet", OR)
        self.manuel.larges.add(regle)
        surtitre = "%s %s · %s %d" % (
            self.libelles["partie"],
            dessins.romain(self.partie.numero) if self.partie else "",
            self.libelles["chapitre"], chapitre.numero)
        morceaux = [
            '<table width="100%%" cellspacing="0" cellpadding="0" '
            'style="margin-top: 30px;"><tr>'
            '<td width="66" valign="middle"><img src="%s" width="58" '
            'height="58" /></td>'
            '<td valign="middle">'
            '<p style="%s margin: 0; font-size: 8.5pt; font-weight: bold; '
            'color: %s; letter-spacing: 2px;"><a name="%s">%s</a></p>'
            '<p style="%s margin: 0; font-size: 23pt; font-weight: bold; '
            'color: %s;">%s</p>'
            '</td></tr></table>'
            % (pad, _TITRE, OR, ident, _html.escape(surtitre.upper()),
               _TITRE, ENCRE, self._en_ligne(titre)),
            untranslated('<p style="margin-top: 8px; margin-bottom: 0;">'
                         '<img src="%s" width="%d" height="3" /></p>')
            % (regle, COLONNE_MAX),
        ]
        if accroche:
            morceaux.append(self._accroche_html(accroche))
        if page:
            puce = "manuel:puce/%s" % couleur.lstrip("#")
            self.manuel.images[puce] = ("puce", couleur)
            self.manuel.liens.append("app:" + page)
            morceaux.append(
                '<p style="%s margin-top: 0; margin-bottom: 14px; '
                'font-size: 10pt;"><img src="%s" width="12" height="12" />'
                '&nbsp;&nbsp;<a href="app:%s" style="color: %s; '
                'text-decoration: none; font-weight: bold;">%s&nbsp;›</a>'
                '</p>' % (_TITRE, puce, page, SARCELLE,
                          _html.escape(self.libelles["ouvrir"])))
        return "\n".join(morceaux)

    def _accroche_html(self, texte: str) -> str:
        return ('<p style="%s margin-top: 14px; margin-bottom: 14px; '
                'font-size: 13pt; font-style: italic; color: %s; '
                'line-height: 140%%;">%s</p>'
                % (_TITRE, SARCELLE, self._en_ligne(texte)))

    def _section(self, niveau: int, texte: str) -> str:
        titre, valeurs = _attributs(texte)
        if niveau == 2:
            ident = valeurs.get("id") or ancre_de(titre)
            self._ancre(ident)
            if self.chapitre is not None:
                self.chapitre.sections.append((ident, titre))
            return ('<h2 style="%s font-size: 15.5pt; font-weight: bold; '
                    'color: %s; margin-top: 24px; margin-bottom: 6px;">'
                    '<a name="%s">%s</a></h2>'
                    % (_TITRE, SARCELLE, ident, self._en_ligne(titre)))
        ancre = valeurs.get("id")
        if ancre:
            self._ancre(ancre)
        contenu = (untranslated('<a name="%s">%s</a>')
                   % (ancre, self._en_ligne(titre))
                   if ancre else self._en_ligne(titre))
        return ('<h3 style="%s font-size: 12pt; font-weight: bold; '
                'color: %s; margin-top: 16px; margin-bottom: 4px;">%s</h3>'
                % (_TITRE, ENCRE, contenu))

    def _ancre(self, ident: str) -> None:
        if ident in self.manuel.ancres:
            self.manuel.erreurs.append(untranslated("ancre en double : %s")
                                       % ident)
        self.manuel.ancres.append(ident)

    def _encadre(self, sorte: str, titre: str, corps: list[str]) -> str:
        sorte = sorte.lower()
        if sorte not in ENCADRES:
            self.manuel.erreurs.append(untranslated("encadré inconnu : %s")
                                       % sorte)
            sorte = "retenir"
        filet_, fond, encre = ENCADRES[sorte]
        entete = _html.escape(self.libelles[sorte])
        if titre.strip():
            entete += (untranslated('&nbsp;&nbsp;·&nbsp;&nbsp;<span '
                                    'style="letter-spacing: 0.5px;">%s'
                                    '</span>')
                       % self._en_ligne(titre.strip()))
        serre = untranslated(('margin-bottom: 10px;', 'margin-bottom: 6px;'))
        interieur = "".join(b.replace(*serre) for b in self._blocs(corps))
        return ('<table width="100%%" cellspacing="0" cellpadding="0" '
                'style="margin-top: 8px; margin-bottom: 14px;">'
                '<tr><td width="5" bgcolor="%s"></td>'
                '<td bgcolor="%s" style="padding: 9px 14px 4px 14px; '
                'font-size: 10.5pt;">'
                '<p style="%s margin: 0 0 5px 0; font-size: 9pt; '
                'font-weight: bold; color: %s; letter-spacing: 1.6px;">%s</p>'
                '%s</td></tr></table>'
                % (filet_, fond, _TITRE, encre, entete, interieur))

    def _figure(self, texte: str) -> str:
        champs = [c.strip() for c in texte.split("|")]
        nom = champs[0]
        legende = champs[1] if len(champs) > 1 else ""
        libelles = ([l.strip() for l in champs[2].split(";")]
                    if len(champs) > 2 and champs[2] else [])
        if nom not in dessins.FIGURES:
            self.manuel.erreurs.append(untranslated("figure inconnue : %s")
                                       % nom)
        self.figures += 1
        self.manuel.figures.append((nom, legende, libelles))
        adresse = "manuel:figure/%s/%d" % (nom, self.figures)
        self.manuel.images[adresse] = ("figure", nom, tuple(libelles))
        self.manuel.larges.add(adresse)
        return ('<p align="center" style="margin-top: 12px; '
                'margin-bottom: 4px;"><img src="%s" width="%d" /></p>'
                '<p align="center" style="%s margin-top: 0; '
                'margin-bottom: 16px; font-size: 9.5pt; font-style: italic; '
                'color: %s;"><span style="color: %s; font-weight: bold;">'
                '%s %d</span>&nbsp;&nbsp;%s</p>'
                % (adresse, COLONNE_MAX, _TITRE, GRIS, OR_SOMBRE,
                   self.libelles["figure"], self.figures,
                   self._en_ligne(legende)))

    def _tableau(self, lignes: list[str]) -> str:
        rangees = []
        for ligne in lignes:
            cellules = [c.strip() for c in ligne.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c or "--") for c in cellules):
                continue
            rangees.append(cellules)
        if not rangees:
            return ""
        tete, corps = rangees[0], rangees[1:]
        html_ = [untranslated('<table width="100%" cellspacing="0" '
                              'cellpadding="7" style="margin-top: 6px; '
                              'margin-bottom: 16px;">'), "<tr>"]
        for cellule, part in zip(tete, _parts_de_colonnes(rangees)):
            html_.append('<td width="%d%%" bgcolor="%s" style="%s color: '
                         '#FFFFFF; font-weight: bold; font-size: 9.5pt;">%s'
                         '</td>' % (part, PETROLE, _TITRE,
                                    self._en_ligne(cellule)))
        html_.append("</tr>")
        for rang, rangee in enumerate(corps):
            fond = ZEBRE if rang % 2 else "#FFFFFF"
            html_.append("<tr>")
            for colonne, cellule in enumerate(rangee):
                html_.append('<td bgcolor="%s" valign="top" style="%s '
                             'font-size: 10pt; color: %s;">%s</td>'
                             % (fond, _TITRE, ENCRE,
                                self._en_ligne(cellule)))
            html_.append("</tr>")
        html_.append("</table>")
        return "".join(html_)

    def _puces(self, elements: list[str]) -> str:
        items = "".join(untranslated('<li style="margin-bottom: 5px; '
                                     'line-height: 145%%;">%s</li>')
                        % self._en_ligne(e) for e in elements)
        return untranslated('<ul style="margin-top: 0; margin-bottom: 10px; '
                            'margin-left: 4px;">%s</ul>') % items

    def _etapes(self, elements: list[str]) -> str:
        """Une liste numérotée, chiffres d'or comme les étapes du guide."""
        rangees = "".join(
            '<tr><td width="36" valign="top" align="right" style="%s '
            'font-size: 15pt; font-weight: bold; color: %s; '
            'padding: 0 12px 6px 0;">%d</td>'
            '<td valign="top" style="padding: 3px 0 8px 0; '
            'line-height: 145%%;">%s</td></tr>'
            % (_TITRE, OR, rang, self._en_ligne(e))
            for rang, e in enumerate(elements, 1))
        return untranslated('<table cellspacing="0" cellpadding="0" '
                            'style="margin-top: 2px; margin-bottom: 12px;">'
                            '%s</table>') % rangees

    # -- dans la ligne ------------------------------------------------------ #

    def _en_ligne(self, texte: str) -> str:
        """Le balisage d'une ligne en HTML : code, touches, liens, libellés
        de boutons, gras et italique — dans cet ordre, pour qu'un astérisque
        dans un chemin ne passe pas en italique."""
        jetons: list[str] = []

        def garder(fragment: str) -> str:
            jetons.append(fragment)
            return "\x00%d\x00" % (len(jetons) - 1)

        def code(trouve) -> str:
            return garder('<span style="%s font-size: 10pt; color: %s;">%s'
                          '</span>' % (_CHASSE, SARCELLE,
                                       _html.escape(trouve.group(1))))

        def touche(trouve) -> str:
            return garder('<span style="%s font-size: 9.5pt; font-weight: '
                          'bold; color: %s; background-color: %s;">'
                          '&nbsp;%s&nbsp;</span>'
                          % (_CHASSE, SARCELLE, FOND_TOUCHE,
                             _html.escape(trouve.group(1))))

        def lien(trouve) -> str:
            cible = trouve.group(2)
            self.manuel.liens.append(cible)
            avant = ""
            if cible.startswith("app:"):
                cle = cible[4:].split("#", 1)[0]
                if cle in PAGE_COLORS:
                    couleur = PAGE_COLORS[cle]
                    puce = "manuel:puce/%s" % couleur.lstrip("#")
                    self.manuel.images[puce] = ("puce", couleur)
                    avant = untranslated('<img src="%s" width="10" '
                                         'height="10" />&nbsp;') % puce
            return garder('%s<a href="%s" style="color: %s; '
                          'text-decoration: none; font-weight: bold;">%s</a>'
                          % (avant, _html.escape(cible, quote=True),
                             SARCELLE, self._simple(trouve.group(1))))

        def bouton(trouve) -> str:
            libelle = trouve.group(1)
            self.manuel.libelles.add(_html.unescape(libelle))
            return garder('<span style="%s font-size: 10pt; font-weight: '
                          'bold; color: %s; background-color: %s;">'
                          '&nbsp;%s&nbsp;</span>'
                          % (_TITRE, ENCRE, FOND_LIBELLE,
                             _html.escape(_html.unescape(libelle))))

        texte = _CODE.sub(code, texte)
        texte = _TOUCHE.sub(touche, texte)
        texte = _LIEN.sub(lien, texte)
        texte = _BOUTON.sub(bouton, texte)
        texte = self._simple(texte)
        while _JETON.search(texte):
            texte = _JETON.sub(lambda t: jetons[int(t.group(1))], texte)
        return texte

    def _simple(self, texte: str) -> str:
        """Échappement, typographie, gras et italique.

        Le gras et l'italique se posent sur le texte **réuni** : ils
        enveloppent souvent un libellé ou un mot de code déjà mis de côté
        (``**[Analyser]**``), qu'un traitement morceau par morceau ne
        verrait pas.
        """
        morceaux = re.split("(\x00\\d+\x00)", texte)
        sortie = []
        for morceau in morceaux:
            if not _JETON.fullmatch(morceau):
                morceau = _typographie(_html.escape(morceau, quote=False),
                                       self.langue)
            sortie.append(morceau)
        texte = _GRAS.sub(r"<b>\1</b>", "".join(sortie))
        return _ITALIQUE.sub(r"<i>\1</i>", texte)


# --------------------------------------------------------------------------- #
# Les images
# --------------------------------------------------------------------------- #

_IMAGES: dict[tuple, QImage] = {}


def image(adresse: str, manuel: Manuel) -> QImage:
    """Le dessin d'une adresse ``manuel:…``, rendu une fois puis gardé."""
    spec = manuel.images.get(adresse)
    if spec is None:
        return QImage()
    cle = (manuel.langue,) + tuple(spec)
    deja = _IMAGES.get(cle)
    if deja is not None:
        return deja
    sorte = spec[0]
    try:
        if sorte == "ouverture":
            rendu = dessins.ouverture(spec[1], spec[2], spec[3], spec[4])
        elif sorte == "figure":
            rendu = dessins.figure(spec[1], list(spec[2]))
        elif sorte == "pad":
            rendu = dessins.pad_chapitre(spec[1], spec[2])
        elif sorte == "puce":
            rendu = dessins.puce(spec[1])
        elif sorte == "filet":
            rendu = dessins.filet(spec[1])
        else:
            rendu = QImage()
    except Exception:                   # noqa: BLE001 - un dessin ne casse rien
        log.exception("image du manuel impossible : %s", adresse)
        rendu = QImage()
    _IMAGES[cle] = rendu
    return rendu


# --------------------------------------------------------------------------- #
# La page de lecture
# --------------------------------------------------------------------------- #

def _plat(caractere: str) -> str:
    """Un caractère sans son accent, en minuscule, **un pour un** : la
    recherche compare des positions, qui doivent rester alignées."""
    base = "".join(c for c in unicodedata.normalize("NFKD", caractere)
                   if not unicodedata.combining(c))
    minuscule = (base if len(base) == 1 else caractere).lower()
    return minuscule[:1] or caractere


class PageDeLecture(QTextBrowser):
    """La page de papier : colonne centrée, images à sa largeur."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.manuel: Manuel | None = None
        self.colonne = COLONNE_MAX
        self.setOpenLinks(False)
        self.setObjectName("PageManuel")
        self.document().setUndoRedoEnabled(False)
        self.document().setDocumentMargin(0)
        self.setStyleSheet(
            "QTextBrowser#PageManuel { background-color: %s; color: %s; "
            "border: none; padding: 0; selection-background-color: %s; "
            "selection-color: %s; }" % (PAPIER, ENCRE, "#F3D98B", ENCRE))
        self.viewport().setAutoFillBackground(True)

    def loadResource(self, sorte, adresse):  # noqa: N802 - API Qt
        if isinstance(adresse, QUrl) and adresse.scheme() == "manuel" \
                and self.manuel is not None:
            rendu = image(adresse.toString(), self.manuel)
            if not rendu.isNull():
                return rendu
            return QImage(1, 1, QImage.Format.Format_ARGB32_Premultiplied)
        return super().loadResource(sorte, adresse)

    def afficher(self, manuel: Manuel) -> None:
        self.manuel = manuel
        self.setHtml(manuel.html)
        self.ajuster()

    def resizeEvent(self, event) -> None:  # noqa: N802 - API Qt
        super().resizeEvent(event)
        self.ajuster()

    def ajuster(self) -> None:
        """Centre la colonne et met les grandes images à sa largeur."""
        largeur = self.viewport().width()
        colonne = max(320, min(COLONNE_MAX, largeur - 2 * GOUTTIERE))
        marge = max(12.0, (largeur - colonne) / 2.0)
        document = self.document()
        cadre = document.rootFrame()
        format_ = cadre.frameFormat()
        if (abs(format_.leftMargin() - marge) > 0.5
                or abs(format_.rightMargin() - marge) > 0.5):
            format_.setLeftMargin(marge)
            format_.setRightMargin(marge)
            format_.setTopMargin(10)
            format_.setBottomMargin(60)
            cadre.setFrameFormat(format_)
        if colonne != self.colonne:
            self.colonne = colonne
            self._redimensionner_images(colonne)

    def _redimensionner_images(self, colonne: int) -> None:
        if self.manuel is None:
            return
        document = self.document()
        curseur = QTextCursor(document)
        bloc = document.begin()
        while bloc.isValid():
            iterateur = bloc.begin()
            while not iterateur.atEnd():
                fragment = iterateur.fragment()
                format_ = fragment.charFormat()
                if format_.isImageFormat():
                    image_ = format_.toImageFormat()
                    if image_.name() in self.manuel.larges \
                            and abs(image_.width() - colonne) > 0.5:
                        image_.setWidth(colonne)
                        curseur.setPosition(fragment.position())
                        curseur.setPosition(
                            fragment.position() + fragment.length(),
                            QTextCursor.MoveMode.KeepAnchor)
                        curseur.setCharFormat(image_)
                iterateur += 1
            bloc = bloc.next()
        document.markContentsDirty(0, document.characterCount())

    # -- où en est-on ------------------------------------------------------- #

    def positions(self) -> list[tuple[str, float]]:
        """``(ancre, hauteur)`` de chaque ancre, dans l'ordre du texte."""
        document = self.document()
        disposition = document.documentLayout()
        trouvees: list[tuple[str, float]] = []
        bloc = document.begin()
        while bloc.isValid():
            iterateur = bloc.begin()
            while not iterateur.atEnd():
                format_ = iterateur.fragment().charFormat()
                for nom in format_.anchorNames():
                    trouvees.append(
                        (nom, disposition.blockBoundingRect(bloc).top()))
                iterateur += 1
            bloc = bloc.next()
        return trouvees

    def ancre_visible(self) -> str:
        """La dernière ancre passée en haut de la page."""
        haut = self.verticalScrollBar().value() + 40
        courante = ""
        for nom, hauteur in self.positions():
            if hauteur <= haut:
                courante = nom
            else:
                break
        return courante

    # -- recherche ---------------------------------------------------------- #

    def trouver_tout(self, cherche: str) -> list[tuple[int, int]]:
        """Toutes les occurrences, sans tenir compte des accents ni de la
        casse : « echantillon » trouve « Échantillons »."""
        aiguille = "".join(_plat(c) for c in cherche.strip())
        if len(aiguille) < 2:
            return []
        brut = self.document().toRawText()
        plat = "".join(_plat(c) for c in brut)
        trouvees = []
        depart = plat.find(aiguille)
        while depart >= 0:
            trouvees.append((depart, depart + len(aiguille)))
            depart = plat.find(aiguille, depart + len(aiguille))
        return trouvees

    def surligner(self, plages: list[tuple[int, int]],
                  courante: int = -1) -> None:
        selections = []
        for rang, (debut, fin) in enumerate(plages):
            selection = QTextEdit.ExtraSelection()
            curseur = QTextCursor(self.document())
            curseur.setPosition(debut)
            curseur.setPosition(fin, QTextCursor.MoveMode.KeepAnchor)
            selection.cursor = curseur
            selection.format.setBackground(QColor(
                SURLIGNAGE_COURANT if rang == courante else SURLIGNAGE))
            selections.append(selection)
        self.setExtraSelections(selections)
        if 0 <= courante < len(plages):
            curseur = QTextCursor(self.document())
            curseur.setPosition(plages[courante][0])
            self.setTextCursor(curseur)
            self.ensureCursorVisible()


# --------------------------------------------------------------------------- #
# La fenêtre
# --------------------------------------------------------------------------- #

class _DelegueSommaire(QStyledItemDelegate):
    """Écrit le sommaire dans la couleur de chaque entrée.

    La feuille de style de l'application fixe la couleur du texte des
    listes, et Qt ignore alors celle des éléments : les parties perdaient la
    couleur de leur ouverture. Le fond, la sélection et l'icône restent
    dessinés par le style ; seul le texte l'est ici.
    """

    def paint(self, peintre, option, index) -> None:  # noqa: D102 - API Qt
        vue = QStyleOptionViewItem(option)
        self.initStyleOption(vue, index)
        texte = vue.text
        vue.text = ""
        style = vue.widget.style() if vue.widget is not None \
            else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, vue,
                          peintre, vue.widget)
        cadre = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText,
                                     vue, vue.widget)
        pinceau = index.data(Qt.ItemDataRole.ForegroundRole)
        couleur = (pinceau.color() if hasattr(pinceau, "color")
                   else QColor(TEXTE_SOMMAIRE))
        if vue.state & QStyle.StateFlag.State_Selected \
                and not hasattr(pinceau, "color"):
            couleur = QColor("#FFFFFF")
        peintre.save()
        peintre.setFont(vue.font)
        peintre.setPen(couleur)
        elide = QFontMetrics(vue.font).elidedText(
            texte, Qt.TextElideMode.ElideRight, cadre.width() - 4)
        peintre.drawText(cadre.adjusted(3, 0, 0, 0),
                         int(Qt.AlignmentFlag.AlignVCenter
                             | Qt.AlignmentFlag.AlignLeft), elide)
        peintre.restore()


#: Le texte des chapitres dans le sommaire, et celui des sections.
TEXTE_SOMMAIRE = "#E6E9EE"
TEXTE_SECTION = "#9AA1AC"

class FenetreManuel(QMainWindow):
    """Le manuel, dans une fenêtre à garder à côté de l'application."""

    #: Un lien demande une page de l'application : ``Health#Doublons``.
    navigateRequested = pyqtSignal(str)
    #: Un lien demande la fenêtre « Deluge en direct ».
    liveRequested = pyqtSignal()

    def __init__(self, langue: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowTitle(tr("Manuel — %s") % APP_NAME)
        self.setWindowIcon(icons.app_icon(256))
        self.resize(1220, 860)
        self.setMinimumSize(900, 560)
        self._manuels: dict[str, Manuel] = {}
        self.manuel: Manuel | None = None
        self._resultats: list[tuple[int, int]] = []
        self._rang = -1
        self._ancre_suivie = ""
        self._elements: dict[str, QTreeWidgetItem] = {}

        centre = QWidget(self)
        colonne = QVBoxLayout(centre)
        colonne.setContentsMargins(0, 0, 0, 0)
        colonne.setSpacing(0)
        colonne.addWidget(self._barre())

        self._separateur = QSplitter(Qt.Orientation.Horizontal, centre)
        self._sommaire = QTreeWidget()
        self._sommaire.setObjectName("SommaireManuel")
        self._sommaire.setHeaderHidden(True)
        self._sommaire.setIndentation(14)
        self._sommaire.setMinimumWidth(220)
        self._sommaire.setIconSize(QSize(14, 14))
        self._sommaire.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._sommaire.itemClicked.connect(
            lambda element, _c: self._aller_a(element))
        self._sommaire.setItemDelegate(_DelegueSommaire(self._sommaire))
        self._sommaire.setStyleSheet(
            "QTreeWidget#SommaireManuel { background-color: #0E1218; "
            "border: none; border-right: 1px solid #1E2530; padding: 8px 4px; "
            "show-decoration-selected: 0; }"
            "QTreeWidget#SommaireManuel::item { padding: 4px 4px; "
            "border-radius: 5px; }"
            "QTreeWidget#SommaireManuel::item:selected, "
            "QTreeWidget#SommaireManuel::item:hover { "
            "background-color: #1B212B; }"
            "QTreeWidget#SommaireManuel::branch:selected { "
            "background-color: transparent; }")
        self._separateur.addWidget(self._sommaire)

        self.page = PageDeLecture()
        self.page.anchorClicked.connect(self._lien)
        self.page.verticalScrollBar().valueChanged.connect(
            lambda _v: self._suivre.start())
        self._separateur.addWidget(self.page)
        self._separateur.setStretchFactor(0, 0)
        self._separateur.setStretchFactor(1, 1)
        self._separateur.setSizes([290, 930])
        colonne.addWidget(self._separateur, 1)
        self.setCentralWidget(centre)

        # Le sommaire suit la lecture, sans recalculer à chaque pixel.
        self._suivre = QTimer(self)
        self._suivre.setSingleShot(True)
        self._suivre.setInterval(120)
        self._suivre.timeout.connect(self._suivre_lecture)

        for touches, action in (("Ctrl+F", self._viser_recherche),
                                ("F3", lambda: self._suivant(1)),
                                ("Shift+F3", lambda: self._suivant(-1)),
                                ("Escape", self._echap)):
            raccourci = QShortcut(QKeySequence(touches), self)
            raccourci.activated.connect(action)

        self.set_language(langue or i18n.language())

    # -- construction ------------------------------------------------------- #

    def _barre(self) -> QWidget:
        from .widgets.chrome import Wordmark

        barre = QFrame(self)
        barre.setObjectName("BarreManuel")
        barre.setFixedHeight(56)
        barre.setStyleSheet(
            "QFrame#BarreManuel { background-color: #0E1218; "
            "border-bottom: 3px solid %s; }" % GOLD)
        ligne = QHBoxLayout(barre)
        ligne.setContentsMargins(12, 0, 12, 0)
        ligne.setSpacing(8)
        self._logotype = Wordmark(barre)
        ligne.addWidget(self._logotype)
        titre = QLabel(tr("MANUEL"))
        titre.setStyleSheet("color: %s; font-weight: 800; "
                            "letter-spacing: 3px; font-size: 10pt;" % GOLD)
        ligne.addWidget(titre)
        ligne.addStretch(1)

        self._champ = QLineEdit()
        self._champ.setPlaceholderText(tr("Chercher dans le manuel…"))
        self._champ.setClearButtonEnabled(True)
        self._champ.setMinimumWidth(150)
        self._champ.setMaximumWidth(280)
        self._champ.setToolTip(tr("Les accents et les majuscules ne comptent "
                                  "pas  (Ctrl+F, puis Entrée pour la suite)"))
        self._champ.textChanged.connect(lambda _t: self._attente.start())
        self._champ.returnPressed.connect(lambda: self._suivant(1))
        ligne.addWidget(self._champ)
        self._attente = QTimer(self)
        self._attente.setSingleShot(True)
        self._attente.setInterval(220)
        self._attente.timeout.connect(self._chercher)

        self._precedent = QPushButton()
        self._precedent.setIcon(icons.icon("chevron-left", "#C3C9D2", 14))
        self._precedent.setToolTip(tr("Occurrence précédente  (Maj+F3)"))
        self._precedent.clicked.connect(lambda: self._suivant(-1))
        self._suivant_bouton = QPushButton()
        self._suivant_bouton.setIcon(icons.icon("chevron-right", "#C3C9D2",
                                                14))
        self._suivant_bouton.setToolTip(tr("Occurrence suivante  (F3)"))
        self._suivant_bouton.clicked.connect(lambda: self._suivant(1))
        for bouton in (self._precedent, self._suivant_bouton):
            bouton.setFixedWidth(30)
            ligne.addWidget(bouton)
        self._compte = QLabel("")
        self._compte.setFixedWidth(70)
        self._compte.setStyleSheet("color: #8E95A0;")
        ligne.addWidget(self._compte)

        # Chaque langue écrite dans la sienne, comme le menu Langue.
        self._langues = QButtonGroup(self)
        self._langues.setExclusive(True)
        self._boutons_langue: dict[str, QPushButton] = {}
        for code, nom in LANGUAGES:
            bouton = QPushButton(nom)
            bouton.setCheckable(True)
            bouton.setToolTip(tr("Lire le manuel dans cette langue"))
            bouton.clicked.connect(
                lambda _c=False, c=code: self.set_language(c))
            self._langues.addButton(bouton)
            self._boutons_langue[code] = bouton
            ligne.addWidget(bouton)

        self._pdf = QPushButton(tr("PDF…"))
        self._pdf.setIcon(icons.icon("export", "#C3C9D2", 16))
        self._pdf.setToolTip(tr("Enregistrer le manuel en PDF, pour le lire "
                                "ou l'imprimer hors de l'application"))
        self._pdf.clicked.connect(self.exporter_pdf)
        ligne.addWidget(self._pdf)
        return barre

    def resizeEvent(self, event) -> None:  # noqa: N802 - API Qt
        super().resizeEvent(event)
        # « POUR DELUGE » s'efface en fenêtre étroite, comme dans la fenêtre
        # principale : la place va à la recherche.
        self._logotype.set_compact(self.width() < 1150)

    # -- langue et contenu -------------------------------------------------- #

    def manuel_de(self, langue: str) -> Manuel:
        langue = i18n.normalize(langue)
        if langue not in self._manuels:
            self._manuels[langue] = charger(langue)
        return self._manuels[langue]

    def set_language(self, langue: str) -> None:
        """Change la langue du manuel en gardant la place du lecteur."""
        langue = i18n.normalize(langue)
        for code, bouton in self._boutons_langue.items():
            bouton.setChecked(code == langue)
        if self.manuel is not None and self.manuel.langue == langue:
            return
        ancre = self.page.ancre_visible() if self.manuel is not None else ""
        self.manuel = self.manuel_de(langue)
        self.page.afficher(self.manuel)
        self._remplir_sommaire()
        if ancre:
            QTimer.singleShot(0, lambda: self.aller(ancre))
        if self._champ.text().strip():
            self._chercher()

    def _remplir_sommaire(self) -> None:
        self._sommaire.clear()
        self._elements = {}
        if self.manuel is None:
            return
        parents: dict[int, QTreeWidgetItem] = {}
        for partie in self.manuel.parties:
            element = QTreeWidgetItem(
                ["%s · %s" % (dessins.romain(partie.numero),
                              partie.titre.upper())])
            element.setData(0, Qt.ItemDataRole.UserRole, partie.ident)
            element.setForeground(0, QColor(partie.couleur))
            police = element.font(0)
            police.setBold(True)
            police.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.0)
            element.setFont(0, police)
            self._sommaire.addTopLevelItem(element)
            element.setExpanded(True)
            parents[partie.numero] = element
            self._elements[partie.ident] = element
        for chapitre in self.manuel.chapitres:
            element = QTreeWidgetItem(["%d  %s" % (chapitre.numero,
                                                   chapitre.titre)])
            element.setData(0, Qt.ItemDataRole.UserRole, chapitre.ident)
            element.setIcon(0, QIcon(QPixmap.fromImage(
                dessins.puce(chapitre.couleur))))
            element.setToolTip(0, chapitre.titre)
            parent = parents.get(chapitre.partie.numero) \
                if chapitre.partie else None
            if parent is not None:
                parent.addChild(element)
            else:
                self._sommaire.addTopLevelItem(element)
            self._elements[chapitre.ident] = element
            for ancre, titre in chapitre.sections:
                sous = QTreeWidgetItem([titre])
                sous.setData(0, Qt.ItemDataRole.UserRole, ancre)
                sous.setForeground(0, QColor(TEXTE_SECTION))
                sous.setToolTip(0, titre)
                element.addChild(sous)
                self._elements[ancre] = sous

    # -- navigation --------------------------------------------------------- #

    def aller(self, ancre: str) -> None:
        """Place la lecture sur ``ancre`` : un chapitre ou une section."""
        if not ancre:
            return
        self.page.scrollToAnchor(ancre)
        self._marquer(ancre)

    def montrer_page(self, cle: str) -> None:
        """Ouvre le chapitre de la page ``cle`` de l'application, ou le
        début du manuel si elle n'en a pas."""
        chapitre = self.manuel.chapitre_de_page(cle) if self.manuel else None
        if chapitre is not None:
            self.aller(chapitre.ident)
        elif self.manuel is not None and self.manuel.chapitres:
            self.aller(self.manuel.chapitres[0].ident)

    def _aller_a(self, element: QTreeWidgetItem) -> None:
        ancre = element.data(0, Qt.ItemDataRole.UserRole)
        if ancre:
            self.aller(str(ancre))

    def _marquer(self, ancre: str) -> None:
        """Le sommaire montre où l'on est : le chapitre ouvert, la section
        choisie."""
        if ancre == self._ancre_suivie:
            return
        self._ancre_suivie = ancre
        element = self._elements.get(ancre)
        if element is None:
            return
        chapitre = self.manuel.chapitre_de(ancre) if self.manuel else None
        for ident, autre in self._elements.items():
            if autre.childCount() and autre.parent() is not None:
                autre.setExpanded(chapitre is not None
                                  and ident == chapitre.ident)
        self._sommaire.blockSignals(True)
        self._sommaire.setCurrentItem(element)
        self._sommaire.scrollToItem(element)
        self._sommaire.blockSignals(False)

    def _suivre_lecture(self) -> None:
        ancre = self.page.ancre_visible()
        if ancre:
            self._marquer(ancre)

    def _lien(self, adresse: QUrl) -> None:
        texte = adresse.toString()
        if texte.startswith("#"):
            self.aller(texte[1:])
        elif adresse.scheme() == "app":
            cible = texte[4:]
            if cible == "@live":
                self.liveRequested.emit()
            else:
                self.navigateRequested.emit(cible)
        elif adresse.scheme() in ("http", "https", "mailto"):
            QDesktopServices.openUrl(adresse)
        elif adresse.fragment():
            self.aller(adresse.fragment())

    # -- recherche ---------------------------------------------------------- #

    def _viser_recherche(self) -> None:
        self._champ.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self._champ.selectAll()

    def _chercher(self) -> None:
        self._resultats = self.page.trouver_tout(self._champ.text())
        self._rang = -1
        if self._resultats:
            debut = self.page.cursorForPosition(
                self.page.viewport().rect().topLeft()).position()
            self._rang = next((rang for rang, (d, _f)
                               in enumerate(self._resultats) if d >= debut),
                              0)
        self._montrer_resultat()

    def _suivant(self, sens: int) -> None:
        if not self._resultats:
            self._chercher()
            if not self._resultats:
                return
        self._rang = (self._rang + sens) % len(self._resultats)
        self._montrer_resultat()

    def _montrer_resultat(self) -> None:
        self.page.surligner(self._resultats, self._rang)
        texte = self._champ.text().strip()
        if not texte or len(texte) < 2:
            self._compte.setText("")
        elif not self._resultats:
            self._compte.setText(tr("aucun"))
        else:
            self._compte.setText("%d / %d" % (self._rang + 1,
                                              len(self._resultats)))

    def _echap(self) -> None:
        if self._champ.hasFocus() and self._champ.text():
            self._champ.clear()
        else:
            self.close()

    # -- PDF ---------------------------------------------------------------- #

    def exporter_pdf(self) -> str:
        """Enregistre le manuel en PDF, au format A4 ; rend le chemin."""
        if self.manuel is None:
            return ""
        nom = LIBELLES[self.manuel.langue]["pdf"]
        chemin, _filtre = QFileDialog.getSaveFileName(
            self, tr("Enregistrer le manuel en PDF"), str(Path.home() / nom),
            tr("Document PDF (*.pdf)"))
        if not chemin:
            return ""
        try:
            ecrire_pdf(self.manuel, Path(chemin))
        except Exception as exc:        # noqa: BLE001 - l'écriture peut échouer
            log.exception("manuel en PDF impossible")
            self.statusBar().showMessage(tr("PDF impossible : %s") % exc,
                                         8000)
            return ""
        self.statusBar().showMessage(tr("Manuel enregistré : %s") % chemin,
                                     8000)
        return chemin


def ecrire_pdf(manuel: Manuel, chemin: Path) -> None:
    """Le manuel en PDF A4 : un document à part, aux images à la largeur de
    la page imprimée."""
    from PyQt6.QtPrintSupport import QPrinter

    imprimante = QPrinter(QPrinter.PrinterMode.HighResolution)
    imprimante.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    imprimante.setOutputFileName(str(chemin))
    marge = 10.0
    imprimante.setPageLayout(QPageLayout(
        QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Portrait,
        QMarginsF(marge, marge, marge, marge), QPageLayout.Unit.Millimeter))
    imprimante.setDocName(APP_NAME)

    document = QTextDocument()
    document.setUndoRedoEnabled(False)
    document.setDocumentMargin(0)
    # À l'impression, Qt ajoute 2 cm de marge de chaque côté, et compte en
    # pixels de 96 par pouce : la colonne fait donc la largeur de la page,
    # moins les deux marges et ces 4 cm. Des images plus larges débordaient
    # de la page.
    utile = QPageSize(QPageSize.PageSizeId.A4).size(
        QPageSize.Unit.Millimeter).width() - 2 * marge - 40.0
    largeur = int(utile / 25.4 * 96) - 6
    for adresse in manuel.images:
        rendu = image(adresse, manuel)
        if not rendu.isNull():
            document.addResource(QTextDocument.ResourceType.ImageResource,
                                 QUrl(adresse), rendu)
    # Sur le papier, « Ouvrir cette page dans l'application » ne mène nulle
    # part : la ligne disparaît.
    html_ = re.sub(untranslated(r'<p[^>]*><img[^>]*/>&nbsp;&nbsp;<a '
                                r'href="app:[^"]*"[^>]*>.*?</a></p>'),
                   "", manuel.html)
    document.setHtml(re.sub(r'width="%d"' % COLONNE_MAX,
                            'width="%d"' % largeur, html_))
    impression = getattr(document, "print_", None) or getattr(document,
                                                               "print")
    impression(imprimante)

