# -*- coding: utf-8 -*-
"""La langue de l'interface : français ou anglais.

Le français est la langue source. Chaque texte de l'application est écrit en
français dans le code, et **c'est lui la clé** de sa traduction : les
traductions anglaises vivent dans :mod:`delugeapp.i18n.en`, un fichier par
module du code (``ui/pages/health.py`` → ``en/ui_pages_health.py``). On
trouve ainsi l'anglais d'un écran à côté de l'endroit où il se traduit.

Quatre règles, que des tests vérifient :

* un texte visible passe par :func:`tr` **au moment où il s'affiche**, jamais
  à l'import d'un module : la langue se choisit dans le menu, la fenêtre se
  reconstruit dans le même processus, et un texte traduit à l'import
  resterait dans la langue précédente ;
* une constante de module ou de classe se marque par :func:`N_`, qui ne fait
  rien, et se traduit là où elle s'affiche — ``tr(self.TITLE)`` ;
* un gabarit garde ses marques, et sa traduction porte exactement les mêmes :
  ``tr("%d fichier(s)") % n``, ``tr("Carte : {chemin}").format(chemin=c)`` ;
* un **identifiant** ne se traduit pas et se marque par :func:`untranslated` :
  une clé comparée dans le code, une balise XML, un dossier système. Ce que
  l'application **écrit** — nom de clip, de dossier, de piste MIDI — prend
  la langue de l'interface au moment de l'écriture : ``tr`` s'applique là,
  sur une clé française qui, elle, ne change pas (« Accords » s'écrit
  « Chords »).

Le journal de l'application reste en français : il sert au diagnostic, pas à
l'usage.

Ce module ne dépend que de la bibliothèque standard : le noyau s'en sert
sans toucher à Qt.
"""

from __future__ import annotations

import re
import threading

__all__ = ["LANGUAGES", "DEFAULT", "FIRST_RUN", "N_", "tr", "untranslated",
           "sources",
           "set_language", "language", "is_english", "normalize",
           "catalogue", "decimal", "integer", "clock", "day_month",
           "full_date", "plural", "tr_stored"]

#: Les langues proposées, chacune écrite dans sa propre langue : celui qui
#: ne lit pas la langue affichée doit pouvoir retrouver la sienne.
LANGUAGES: tuple[tuple[str, str], ...] = (("fr", "Français"),
                                          ("en", "English"))

#: La langue des textes du code, clés de toutes les traductions : dans
#: cette langue, :func:`tr` rend le texte tel quel.
DEFAULT = "fr"

#: La langue d'une installation neuve, et celle qu'on prend quand le réglage
#: est illisible : l'anglais, celle de la plupart de ceux qui téléchargent
#: l'application (demandé le 9 novembre 2026).
FIRST_RUN = "en"

_lang = DEFAULT
_english: dict[str, str] | None = None
_inverse: dict[str, list[str]] | None = None
_verrou = threading.Lock()


def normalize(code: object) -> str:
    """Un code de langue connu : ``"EN "`` → ``"en"``, l'inconnu →
    :data:`FIRST_RUN`."""
    texte = str(code or "").strip().lower()[:2]
    return texte if texte in dict(LANGUAGES) else FIRST_RUN


def set_language(code: object) -> str:
    """Choisit la langue de l'interface ; rend le code retenu.

    À appeler **avant** de construire la fenêtre : les textes se traduisent
    à leur création, et une fenêtre déjà bâtie ne change pas de langue.
    """
    global _lang
    _lang = normalize(code)
    if _lang == "en":
        catalogue()
    return _lang


def language() -> str:
    """Code de la langue de l'interface : ``"fr"`` ou ``"en"``."""
    return _lang


def is_english() -> bool:
    """Vrai si l'interface parle anglais."""
    return _lang == "en"


def catalogue() -> dict[str, str]:
    """Le catalogue anglais, chargé une fois — les fils de travail du noyau
    peuvent le demander en même temps que l'interface."""
    global _english
    if _english is None:
        with _verrou:
            if _english is None:
                from .en import load

                _english = load()
    return _english


def tr(text: str) -> str:
    """Le texte dans la langue de l'interface.

    En français, le texte lui-même. En anglais, sa traduction — ou le texte
    tel quel s'il n'en a pas : une donnée venue de la carte (un nom de
    dossier) passe sans dommage.
    """
    if _lang == DEFAULT or not text:
        return text
    return catalogue().get(text, text)


def sources(text: str) -> list[str]:
    """Les textes français dont ``text`` est la traduction.

    Le chemin inverse de :func:`tr`, pour qui retrouve un widget par son
    libellé : le registre d'aide désigne un bouton par « Écouter », que
    l'interface anglaise affiche « Listen ». En français, rien : le libellé
    est déjà la clé.
    """
    global _inverse
    if _lang == DEFAULT or not text:
        return []
    if _inverse is None:
        inverse: dict[str, list[str]] = {}
        for francais, anglais in catalogue().items():
            inverse.setdefault(anglais, []).append(francais)
        _inverse = inverse
    return list(_inverse.get(text, ()))


#: Une marque de gabarit : ``%d``, ``%s``, ``%.1f``, ``{nom}``.
_MARQUE = re.compile(r"%%|%[-+ 0#]*\d*(?:\.\d+)?[sdifgx]|\{\w*\}")
#: « DelugeXMLError: … » : un nom d'exception devant le message.
_EXCEPTION = re.compile(r"^([A-Z]\w*(?:Error|Exception)): (.+)$", re.S)
_gabarits: list[tuple[str, re.Pattern, str]] | None = None


def _compiler_gabarits() -> list[tuple[str, re.Pattern, str]]:
    """Les gabarits du catalogue, prêts à reconnaître un texte rempli :
    ``(début fixe, motif, traduction)``, le plus précis d'abord.

    Un gabarit de moins de quatre lettres fixes — « %s à %s », « %s : %s »
    — reconnaîtrait n'importe quel texte : il est écarté."""
    global _gabarits
    if _gabarits is None:
        gabarits = []
        for francais, anglais in catalogue().items():
            morceaux = _MARQUE.split(francais)
            marques = _MARQUE.findall(francais)
            lettres = sum(c.isalpha() for c in "".join(morceaux))
            if lettres < 4 or not any(m != "%%" for m in marques):
                continue
            motif = re.escape(morceaux[0])
            for marque, morceau in zip(marques, morceaux[1:]):
                motif += "%" if marque == "%%" else "(.+?)"
                motif += re.escape(morceau)
            gabarits.append((lettres, morceaux[0],
                             re.compile(motif + r"\Z", re.S), anglais))
        gabarits.sort(key=lambda g: -g[0])
        _gabarits = [g[1:] for g in gabarits]
    return _gabarits


def _remplir(gabarit: str, valeurs: tuple[str, ...]) -> str:
    """Le gabarit traduit, ses marques remplacées par les valeurs lues."""
    restantes = iter(valeurs)
    return _MARQUE.sub(lambda m: "%" if m.group() == "%%"
                       else next(restantes, ""), gabarit)


def tr_stored(text: str) -> str:
    """Un texte **gardé en français** — dans l'index, dans l'historique —
    traduit au moment où il s'affiche.

    Un tel texte a été rempli avant d'être gardé : « 3 '&' non échappé(s)
    corrigé(s) ». :func:`tr` n'y trouve pas de clé ; on reconnaît alors le
    gabarit dont il est issu, et on remplit sa traduction avec les mêmes
    valeurs. Les morceaux séparés par « ; » se traduisent un à un, et un nom
    d'exception en tête est conservé. Un texte inconnu passe tel quel.
    """
    if _lang == DEFAULT or not text:
        return text
    table = catalogue()
    if text in table:
        return table[text]
    if " ; " in text:
        return "; ".join(tr_stored(morceau) for morceau in text.split(" ; "))
    exception = _EXCEPTION.match(text)
    if exception:
        return "%s: %s" % (exception.group(1), tr_stored(exception.group(2)))
    for debut, motif, anglais in _compiler_gabarits():
        if text.startswith(debut):
            trouve = motif.match(text)
            if trouve:
                return _remplir(anglais, trouve.groups())
    return text


def N_(text: str) -> str:
    """Marque un texte à traduire **plus tard**, là où il s'affiche.

    Sert aux constantes : un titre de page, une liste de libellés. La
    fonction ne fait rien ; elle désigne le texte aux tests, qui exigent sa
    traduction.
    """
    return text


def plural(count: int, one: str, many: str) -> str:
    """Le gabarit au singulier ou au pluriel, selon la règle de la langue.

    Le français garde le singulier jusqu'à un (« 0 fichier »), l'anglais
    seulement pour un (« 0 files »). Les deux gabarits se marquent par
    ``N_`` à l'appel : ``plural(n, N_("%d fichier"), N_("%d fichiers")) % n``.
    """
    singulier = count == 1 if _lang == "en" else abs(count) <= 1
    return tr(one if singulier else many)


def untranslated(value):
    """Marque une valeur qui **ne se traduit pas** : un identifiant comparé
    dans le code, un texte technique (XML, dossier système), un nom propre.
    Ne fait rien ; elle peut envelopper une table entière."""
    return value


def decimal(value: float, digits: int = 1) -> str:
    """Nombre à virgule dans l'usage de la langue : ``1,5`` ou ``1.5``."""
    texte = "%.*f" % (int(digits), float(value))
    return texte if _lang == "en" else texte.replace(".", ",")


def integer(value: int) -> str:
    """Entier avec séparateur de milliers : ``12 345`` ou ``12,345``."""
    texte = "{:,}".format(int(value))
    return texte if _lang == "en" else texte.replace(",", " ")


#: Les mois en anglais, écrits ici plutôt que demandés à ``strftime`` : sa
#: réponse dépend de la langue du système, pas de celle de l'interface.
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep",
           "Oct", "Nov", "Dec")


def clock(moment) -> str:
    """L'heure d'un ``datetime`` : ``14h53`` ou ``14:53``."""
    return moment.strftime("%H:%M" if _lang == "en" else "%Hh%M")


def day_month(moment) -> str:
    """Le jour et le mois : ``15/10`` ou ``15 Oct``."""
    if _lang == "en":
        return "%d %s" % (moment.day, _MONTHS[moment.month - 1])
    return moment.strftime("%d/%m")


def full_date(moment) -> str:
    """La date entière : ``15/10/2026`` ou ``15 Oct 2026``."""
    if _lang == "en":
        return "%d %s %d" % (moment.day, _MONTHS[moment.month - 1],
                             moment.year)
    return moment.strftime("%d/%m/%Y")
