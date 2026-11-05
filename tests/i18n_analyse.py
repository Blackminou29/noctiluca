# -*- coding: utf-8 -*-
"""Lecture du code pour les tests de traduction, sans l'importer.

Le code est lu par son arbre syntaxique : on y trouve les textes passés à
``tr`` et ``N_`` (les clés du catalogue), les textes visibles qui n'y
passent pas (des oublis), et les appels à ``tr`` faits à l'import d'un
module (des textes qui resteraient dans la langue précédente).

Sert à ``test_i18n.py`` ; se lance aussi seul pour un module :

    python tests/i18n_analyse.py delugeapp/ui/mainwindow.py
"""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
PAQUET = RACINE / "delugeapp"
CATALOGUE = PAQUET / "i18n" / "en"

#: Les fonctions dont un texte littéral est une clé du catalogue.
TRADUIRE = {"tr", "N_"}
#: Les fonctions dont tout le contenu est exempté. ``tirage("glissé")``
#: (``core/synthgen.py``) nomme une graine, pas un texte : le traduire
#: changerait chaque son généré.
EXEMPTER = {"untranslated", "tirage", "tirages"}
#: Noms propres, identiques dans les deux langues.
NOMS_PROPRES = {"Noctiluca", "Deluge Companion", "Synthstrom Deluge",
                "MIDI Follow",
                "Deluge",
                # Noms de genres musicaux (``core/genres.py``).
                "Deep house", "Drum and bass", "Berlin school",
                "Boards of Canada"}

#: Les fonctions qui affichent un texte, et la place de ce texte parmi
#: leurs arguments (``"*"`` : chaque élément d'une liste). Un littéral passé
#: là est lu par l'utilisateur, même d'un seul mot sans accent
#: (« Analyser ») — ce que l'heuristique de :func:`visible` ne voit pas.
AFFICHAGE: dict[str, tuple] = {
    "QPushButton": (0,), "QLabel": (0,), "QCheckBox": (0,),
    "QRadioButton": (0,), "QGroupBox": (0,), "QAction": (0,),
    "QToolButton": (0,), "QTableWidgetItem": (0,), "QListWidgetItem": (0,),
    "setText": (0,), "setToolTip": (0,), "setPlaceholderText": (0,),
    "setWindowTitle": (0,), "setStatusTip": (0,), "setTitle": (0,),
    "setLabelText": (0,), "showMessage": (0,), "setSuffix": (0,),
    "setPrefix": (0,), "setSpecialValueText": (0,), "addMenu": (0,),
    "addItem": (0, 1), "addItems": ("*",), "addTab": (1,), "insertTab": (2,),
    "setTabText": (1,), "setTabToolTip": (1,),
    "setHorizontalHeaderLabels": ("*",), "setVerticalHeaderLabels": ("*",),
    "setHeaderLabels": ("*",), "tool_button": (0, 2, "tooltip"),
    "header": (0, 1), "page_header": (0, 1), "say": (0,),
    "getSaveFileName": (1, 3), "getOpenFileName": (1, 3),
    "getOpenFileNames": (1, 3), "getExistingDirectory": (1,),
    "getText": (1, 2), "getItem": (1, 2), "getInt": (1, 2),
    "getDouble": (1, 2), "QProgressDialog": (0, 1), "addRow": (0,),
    "Card": (0,), "SectionTitle": (0,), "StatTile": (0,), "EmptyState": (0, 2),
}
#: Vocabulaire interne du noyau : des mots français qui servent de clés —
#: noms de parties d'un accompagnement, rôles de sections, ambiances,
#: gammes. Ils sont comparés dans le code : on ne les traduit pas là, mais
#: à l'affichage et à l'écriture sur la carte (noms de clips), où leur
#: définition les marque par ``N_``.
IDENTIFIANTS = {
    "Accords", "Basse", "Arpège", "Mélodie", "Batterie", "Batterie légère",
    "montée", "cassure", "pic", "intro", "fin",
    "pulsée", "syncopée", "posée", "aléatoire",
    "septièmes", "neuvièmes", "triades", "suspendus",
    "fantômes", "grosse caisse",
    # Variations d'un clip (``core/variation.py``) et gammes.
    "légère", "doublée", "réponse",
    "mineur harmonique", "pentatonique mineure", "pentatonique majeure",
}

#: Unités, identiques dans les deux langues.
UNITES = {"dB", "dBFS", "ms", "Hz", "kHz", "s", "BPM", "bits", "st", "ct",
          "min", "%"}

#: Les boîtes de ``QMessageBox`` : titre et texte. Gardées à part, pour ne
#: pas confondre ``QMessageBox.warning`` avec ``log.warning``.
BOITES = {"question", "information", "warning", "critical", "about"}
#: Les appels du journal : il reste en français.
JOURNAL = {"debug", "info", "warning", "error", "exception", "critical"}
JOURNAUX = {"log", "logging", "logger", "_log", "LOG", "root"}

_FRANCAIS = re.compile(r"[àâäéèêëîïôöùûüçœÀÂÄÉÈÊËÎÏÔÖÙÛÜÇŒ«»…]")
_MOT = re.compile(r"[A-Za-zÀ-ÿ]{2,}")
_TECHNIQUE = re.compile(
    r"(SELECT |INSERT |UPDATE |CREATE |DELETE FROM| WHERE |qlineargradient|"
    r"border:|border-|padding:|font-|background|rgba\(|color:|margin:|"
    r"QPushButton|QLabel|QWidget|QFrame|%\(asctime\)|\{\s*$|"
    r"^(Segoe UI|DejaVu Sans|DejaVu Sans Mono|Cascadia Mono|Noto Sans)$|"
    r"url\(|\.png$|[=<>] \?|LIKE \?|\bJOIN\b|^PRAGMA |= excluded\.|"
    r"^\w\.\w+ = \d$|"
    r"^(Dashboard|Samples|Synths|Kits|Songs|Generator|Toolbox|Health|Settings)#)")

_RACCOURCI = re.compile(
    r"(?:Ctrl|Maj|Shift|Alt)\+\S*|%\(?\w*\)?[-.\d]*[sdfi]|\{\w*(?::[^{}]*)?\}"
    r"|\.(?:mid|xml|XML|wav|WAV|html|txt|zip|bak|png)\b")

#: Marques d'un gabarit ``%`` (sans le drapeau espace, qui confondrait
#: « 100 % des » avec un ``% d``).
_POURCENT = re.compile(
    r"%(?:\([A-Za-z_]\w*\))?[-#0+]*(?:\*|\d+)?(?:\.(?:\*|\d+))?[sdifrxXeEgGc%]")
#: Marques d'un gabarit ``str.format``.
_ACCOLADE = re.compile(r"(?<!\{)\{([A-Za-z_]\w*|\d*)(?:![rsa])?(?::[^{}]*)?\}(?!\})")


def sources() -> list[Path]:
    """Les modules du code dont les textes se traduisent."""
    fichiers = [p for p in sorted(PAQUET.rglob("*.py"))
                if "i18n" not in p.relative_to(PAQUET).parts]
    fichiers.append(RACINE / "main.py")
    return fichiers


def nom_catalogue(chemin: Path) -> str:
    """``delugeapp/ui/pages/health.py`` → ``ui_pages_health``."""
    chemin = Path(chemin).resolve()
    try:
        relatif = chemin.relative_to(PAQUET)
    except ValueError:
        relatif = chemin.relative_to(RACINE)
    return "_".join(relatif.with_suffix("").parts)


def visible(texte: str) -> bool:
    """Ce texte a-t-il l'air d'être lu par l'utilisateur ?"""
    t = texte.strip()
    if t in NOMS_PROPRES or texte in IDENTIFIANTS:
        return False
    # Raccourcis et marques de gabarit ne sont pas des mots.
    t = _RACCOURCI.sub("", t).strip()
    if not t or not _MOT.search(t) or _TECHNIQUE.search(t):
        return False
    if _FRANCAIS.search(t):
        return True
    return " " in t and bool(re.search(r"[a-zà-ÿ]{3,}", t))


def affiche(texte: str) -> bool:
    """Un littéral passé à une fonction d'affichage est-il un mot à
    traduire ? Les sigles (``BPM``, ``MIDI``) et les symboles non."""
    t = _RACCOURCI.sub("", texte).strip()
    if not t or t in NOMS_PROPRES or t in UNITES or not _MOT.search(t):
        return False
    return not (t.upper() == t and len(t) <= 6)


def _textes_affiches(noeud: ast.Call) -> list[ast.Constant]:
    """Les littéraux qu'un appel d'affichage montre à l'utilisateur."""
    nom = _nom_appel(noeud)
    f = noeud.func
    if nom in BOITES and isinstance(f, ast.Attribute) \
            and isinstance(f.value, ast.Name) and f.value.id == "QMessageBox":
        places: tuple = (1, 2)
    elif nom == "addItem":
        # ``addItem(texte, donnée)`` ou ``addItem(icône, texte, donnée)`` :
        # la donnée n'est pas lue par l'utilisateur.
        premier = noeud.args[0] if noeud.args else None
        places = ((0,) if isinstance(premier, ast.Constant)
                  or isinstance(premier, ast.Call) and _nom_appel(premier)
                  in TRADUIRE else (1,))
    elif nom in AFFICHAGE:
        places = AFFICHAGE[nom]
    else:
        return []
    candidats = []
    for place in places:
        if place == "*":
            for arg in noeud.args[:1]:
                if isinstance(arg, (ast.List, ast.Tuple)):
                    candidats.extend(arg.elts)
        elif isinstance(place, int):
            if place < len(noeud.args):
                candidats.append(noeud.args[place])
        else:
            candidats.extend(m.value for m in noeud.keywords
                             if m.arg == place)
    for mot in noeud.keywords:
        if mot.arg in ("detail", "action2", "subtitle", "tooltip", "hint"):
            candidats.append(mot.value)
    return [c for c in candidats
            if isinstance(c, ast.Constant) and isinstance(c.value, str)]


def marques(texte: str) -> tuple[list[str], list[str]]:
    """Les marques d'un gabarit : ``%`` dans l'ordre, ``{}`` triées."""
    return (_POURCENT.findall(texte),
            sorted(m.group(1) for m in _ACCOLADE.finditer(texte)))


@dataclass
class Analyse:
    chemin: Path
    #: Clé -> lignes où elle apparaît.
    cles: dict[str, list[int]] = field(default_factory=dict)
    #: ``(ligne, texte)`` des appels à ``tr`` exécutés à l'import.
    a_l_import: list[tuple[int, str]] = field(default_factory=list)
    #: ``(ligne, texte)`` des textes visibles qui ne passent pas par ``tr``.
    oublis: list[tuple[int, str]] = field(default_factory=list)


def _nom_appel(noeud: ast.Call) -> str:
    f = noeud.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return ""


def _est_journal(noeud: ast.Call) -> bool:
    f = noeud.func
    if isinstance(f, ast.Attribute) and f.attr in JOURNAL:
        base = f.value
        return ((isinstance(base, ast.Name) and base.id in JOURNAUX)
                or isinstance(base, ast.Call))
    return False


def analyser(chemin: Path) -> Analyse:
    source = Path(chemin).read_text(encoding="utf-8")
    arbre = ast.parse(source)
    resultat = Analyse(Path(chemin))

    docstrings: set[int] = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, (ast.Module, ast.ClassDef, ast.FunctionDef,
                              ast.AsyncFunctionDef)):
            corps = noeud.body
            if (corps and isinstance(corps[0], ast.Expr)
                    and isinstance(corps[0].value, ast.Constant)
                    and isinstance(corps[0].value.value, str)):
                docstrings.add(id(corps[0].value))

    def visiter(noeud, dans_fonction: bool, contexte: str) -> None:
        """``contexte`` : "" (libre), "cle", "exempt" ou "journal"."""
        if isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef,
                              ast.Lambda)):
            # Les valeurs par défaut s'évaluent à la définition, donc à
            # l'import quand la fonction est au niveau du module.
            for defaut in (noeud.args.defaults + noeud.args.kw_defaults):
                if defaut is not None:
                    visiter(defaut, dans_fonction, contexte)
            for decor in getattr(noeud, "decorator_list", []):
                visiter(decor, dans_fonction, contexte)
            corps = noeud.body if isinstance(noeud.body, list) else [noeud.body]
            for enfant in corps:
                visiter(enfant, True, contexte)
            return
        if isinstance(noeud, ast.Dict) and contexte == "":
            # Une clé de table est un identifiant de recherche (« Écouter »
            # désigne un bouton) ; une clé affichée passe par ``N_``.
            for cle, valeur in zip(noeud.keys, noeud.values):
                if cle is not None and not (isinstance(cle, ast.Constant)
                                            and isinstance(cle.value, str)):
                    visiter(cle, dans_fonction, contexte)
                visiter(valeur, dans_fonction, contexte)
            return
        if isinstance(noeud, ast.AnnAssign):
            # L'annotation est du code, pas un texte : ``lib: "Library"``.
            visiter(noeud.target, dans_fonction, contexte)
            if noeud.value is not None:
                visiter(noeud.value, dans_fonction, contexte)
            return
        if isinstance(noeud, ast.Call):
            nom = _nom_appel(noeud)
            if nom in TRADUIRE:
                if nom == "tr" and not dans_fonction:
                    premier = noeud.args[0] if noeud.args else None
                    texte = (premier.value if isinstance(premier, ast.Constant)
                             else ast.unparse(premier) if premier else "")
                    resultat.a_l_import.append((noeud.lineno, str(texte)))
                if noeud.args and isinstance(noeud.args[0], ast.Constant) \
                        and isinstance(noeud.args[0].value, str):
                    cle = noeud.args[0].value
                    resultat.cles.setdefault(cle, []).append(noeud.lineno)
                visiter(noeud.func, dans_fonction, contexte)
                for arg in noeud.args[1:]:
                    visiter(arg, dans_fonction, contexte)
                if noeud.args and not isinstance(noeud.args[0], ast.Constant):
                    visiter(noeud.args[0], dans_fonction, contexte)
                for mot in noeud.keywords:
                    visiter(mot.value, dans_fonction, contexte)
                return
            if nom in EXEMPTER:
                for enfant in ast.iter_child_nodes(noeud):
                    visiter(enfant, dans_fonction, "exempt")
                return
            if _est_journal(noeud):
                for enfant in ast.iter_child_nodes(noeud):
                    visiter(enfant, dans_fonction, "journal")
                return
            if contexte == "":
                for texte in _textes_affiches(noeud):
                    if affiche(texte.value) and not visible(texte.value):
                        resultat.oublis.append((texte.lineno, texte.value))
        if isinstance(noeud, ast.JoinedStr):
            if contexte == "":
                texte = "".join(v.value for v in noeud.values
                                if isinstance(v, ast.Constant))
                if visible(texte):
                    resultat.oublis.append((noeud.lineno, "f" + repr(texte)))
            for v in noeud.values:
                if isinstance(v, ast.FormattedValue):
                    visiter(v.value, dans_fonction, contexte)
            return
        if isinstance(noeud, ast.Constant) and isinstance(noeud.value, str):
            if contexte == "" and id(noeud) not in docstrings \
                    and visible(noeud.value):
                resultat.oublis.append((noeud.lineno, noeud.value))
            return
        for enfant in ast.iter_child_nodes(noeud):
            visiter(enfant, dans_fonction, contexte)

    for enfant in arbre.body:
        visiter(enfant, False, "")
    return resultat


def lire_catalogue(nom: str) -> dict[str, str] | None:
    """Le ``TEXTS`` d'un fichier du catalogue, lu sans l'importer."""
    chemin = CATALOGUE / f"{nom}.py"
    if not chemin.is_file():
        return None
    arbre = ast.parse(chemin.read_text(encoding="utf-8"))
    for noeud in arbre.body:
        if isinstance(noeud, (ast.Assign, ast.AnnAssign)):
            cibles = (noeud.targets if isinstance(noeud, ast.Assign)
                      else [noeud.target])
            if any(isinstance(c, ast.Name) and c.id == "TEXTS"
                   for c in cibles):
                return ast.literal_eval(noeud.value)
    return {}


def rapport(chemin: Path, squelette: bool = True) -> str:
    """Ce qui manque à un module, lisible par un humain."""
    analyse = analyser(chemin)
    nom = nom_catalogue(chemin)
    textes = lire_catalogue(nom) or {}
    lignes = [f"== {chemin} -> en/{nom}.py : {len(analyse.cles)} clés"]
    manquantes = [c for c in analyse.cles if c not in textes]
    orphelines = [c for c in textes if c not in analyse.cles]
    for ligne, texte in analyse.a_l_import:
        lignes.append(f"  À L'IMPORT l.{ligne}: {texte[:80]!r}")
    for ligne, texte in analyse.oublis:
        lignes.append(f"  OUBLI l.{ligne}: {texte[:110]!r}")
    for cle in orphelines:
        lignes.append(f"  ORPHELINE: {cle[:90]!r}")
    for cle, valeur in textes.items():
        if cle in analyse.cles and marques(cle) != marques(valeur):
            lignes.append(f"  GABARIT: {cle[:70]!r} {marques(cle)} != "
                          f"{marques(valeur)}")
    if manquantes:
        lignes.append(f"  MANQUANTES : {len(manquantes)}")
        if squelette:
            for cle in manquantes:
                lignes.append(f"    {cle!r}: \"\",")
    return "\n".join(lignes)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    cibles = [Path(a) for a in sys.argv[1:]] or sources()
    for cible in cibles:
        print(rapport(cible.resolve() if cible.is_absolute()
                      else (RACINE / cible).resolve()))
