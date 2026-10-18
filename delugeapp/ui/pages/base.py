# -*- coding: utf-8 -*-
"""Socle commun aux pages de l'application.

Chaque page respecte le contrat de la SPEC §5.5 : un signal ``status``, une
méthode :meth:`Page.refresh` appelée quand la page devient visible, et les
attributs de classe ``TITLE`` et ``ICON``.

:class:`Page` ajoute ce que les neuf pages refont sinon à l'identique :

* **un rempart autour de ``refresh``.** La SPEC §6.3 exige qu'aucune exception
  n'atteigne la boucle Qt ; les pages redéfinissent ``_refresh`` et le socle
  l'enveloppe ;
* **un état vide**, puisque l'application doit démarrer sans carte valide
  (SPEC §6.1) ;
* **des raccourcis** vers la carte, l'index et le lecteur audio, avec le
  message d'avertissement prêt à l'emploi quand la carte manque.
"""

from __future__ import annotations

import inspect
import logging
import unicodedata
from typing import Any, Callable

from PyQt6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPointF,
    QRectF,
    Qt,
    QVariantAnimation,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...config import AppContext
from .. import art, icons
from ..theme import (
    BORDER_SOFT,
    CARD_TOP,
    GOLD,
    GREY_LIGHT,
    PAD_WHITE,
    PANEL,
    PANEL_LO,
    TEXT_MUTED,
    _rgb,
    accent_qss,
    lit_fill,
    mix,
    page_color,
)
from ..widgets.common import EmptyState, LitPad, glow

log = logging.getLogger(__name__)


def _sans_accents(texte: str) -> str:
    """Minuscules sans accents ni ``&``, pour comparer deux libellés.

    Les onglets portent des accents (« Inutilisés », « Preset de synthé ») et
    parfois un ``&`` d'accélérateur : comparer les chaînes brutes ferait
    échouer un raccourci pour une cédille.
    """
    plie = unicodedata.normalize("NFKD", str(texte or "")).casefold()
    return "".join(c for c in plie
                   if not unicodedata.combining(c) and c != "&").strip()


def _arite(fn: Callable[..., Any]) -> int | None:
    """Nombre d'arguments positionnels que ``fn`` accepte, ``None`` = sans
    limite.

    Sert à :meth:`Page.guard` pour ne transmettre d'un signal que ce que le
    destinataire sait recevoir. Un appelable dont la signature est illisible
    — une fonction native, par exemple — est traité comme sans limite :
    mieux vaut laisser passer les arguments que refuser un appel valable.
    """
    try:
        parametres = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return None
    total = 0
    for parametre in parametres:
        if parametre.kind == inspect.Parameter.VAR_POSITIONAL:
            return None
        if parametre.kind in (inspect.Parameter.POSITIONAL_ONLY,
                              inspect.Parameter.POSITIONAL_OR_KEYWORD):
            total += 1
    return total


class Page(QWidget):
    """Base de toutes les pages."""

    #: Message pour la barre d'état.
    status = pyqtSignal(str)
    #: Demande d'aller aux réglages, relayée par la fenêtre principale.
    settingsRequested = pyqtSignal()
    #: Demande de chercher une carte sur les lecteurs branchés.
    detectRequested = pyqtSignal()
    #: Un morceau vient d'être écrit dans SONGS (chemin relatif) : les
    #: autres pages — Morceaux, tableau de bord — doivent se rafraîchir.
    songWritten = pyqtSignal(str)

    #: Titre affiché dans la navigation, en français.
    TITLE = "Page"
    #: Nom d'icône, parmi ceux de :data:`delugeapp.ui.icons.ICON_NAMES`.
    ICON = "info"
    #: Message de l'état vide quand la carte manque.
    #:
    #: Ce n'est pas une erreur : c'est l'état du tout premier démarrage.
    #: L'écran accueille donc, au lieu d'alerter — et il propose d'abord le
    #: geste le plus court, qui est de laisser l'application chercher.
    EMPTY_MESSAGE = "Où est votre carte Deluge ?"
    EMPTY_DETAIL = ("Branchez la carte, ou indiquez le dossier qui la "
                    "contient. Tout le reste de l'application s'allumera "
                    "ensuite.")
    #: Second geste de l'état vide, plus rapide que le premier.
    EMPTY_ACTION2 = "Détecter la carte"
    #: Vrai si la page a besoin d'une carte valide pour montrer quoi que ce soit.
    NEEDS_CARD = True

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._built = False

        # La page prend sa couleur **avant** de créer le moindre enfant :
        # boutons principaux, sélections, onglets, cases et curseurs sont
        # teints d'emblée, au lieu d'être repeints une seconde fois.
        try:
            self.setStyleSheet(accent_qss(self.color))
        except Exception as exc:        # noqa: BLE001 - une teinte ne casse rien
            log.debug("teinte de la page %s impossible : %s", self.TITLE, exc)

        self._stack = QStackedWidget(self)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._stack)

        self._content = QWidget(self)
        self._stack.addWidget(self._content)

        # L'icône de la page, et non un triangle d'alerte : l'utilisateur
        # est au bon endroit, il lui manque seulement la carte.
        self._empty = EmptyState(self.EMPTY_MESSAGE, self.ICON,
                                 "Indiquer le dossier",
                                 detail=self.EMPTY_DETAIL,
                                 color=self.color,
                                 action2=self.EMPTY_ACTION2)
        self._empty.actionClicked.connect(self.settingsRequested.emit)
        self._empty.action2Clicked.connect(self.detectRequested.emit)
        self._stack.addWidget(self._empty)

    # -- construction paresseuse -------------------------------------------- #

    def content(self) -> QWidget:
        """Widget dans lequel la page bâtit son interface."""
        return self._content

    def build(self) -> None:
        """Construit l'interface. À redéfinir par chaque page."""

    def _ensure_built(self) -> None:
        """Bâtit l'interface au premier affichage, pas à la création.

        Neuf pages construites d'emblée allongeraient le démarrage sans
        raison : l'utilisateur n'en voit qu'une à la fois.
        """
        if self._built:
            return
        self._built = True
        try:
            self.build()
            self._tint_sections()
            self._light_up()
            self._explain_controls()
        except Exception:  # noqa: BLE001 - rempart, cf. SPEC §6.3
            log.exception("construction de la page %s en échec", self.TITLE)

    def _light_up(self) -> None:
        """Allume les boutons principaux et teint les tracés de la page.

        * le bouton principal est un pad allumé : il rayonne de la couleur
          de la page, et son icône prend l'encre qui se lit sur cette
          couleur — elle restait dorée sur fond cyan ;
        * les widgets dessinés à la main (forme d'onde, courbes, spectre,
          enveloppe) qui savent changer de couleur prennent celle de la page.
        """
        couleur = self.color
        _haut, _bas, encre = lit_fill(couleur)
        for bouton in self.findChildren(QPushButton):
            try:
                if bouton.objectName() != "Primary":
                    continue
                nom = bouton.property("iconName")
                if nom:
                    bouton.setIcon(icons.icon(str(nom), encre, 16))
                glow(bouton, couleur, 24, 0.45)
            except Exception as exc:        # noqa: BLE001 - simple décor
                log.debug("bouton principal non allumé : %s", exc)
        for widget in self.findChildren(QWidget):
            accent = getattr(widget, "set_accent", None)
            if callable(accent):
                try:
                    accent(couleur)
                except Exception as exc:    # noqa: BLE001 - simple décor
                    log.debug("teinte d'un tracé impossible : %s", exc)

    def _explain_controls(self) -> None:
        """Pose une explication sur chaque commande qui n'en a pas.

        Mesuré avant : **102 des 174 commandes de l'application
        n'expliquaient rien**, dont quatre qui écrivent sur la carte. Les
        textes vivent dans :mod:`delugeapp.ui.aide`, en un seul endroit, ce
        qui permet à un test de vérifier qu'il n'en manque aucune.
        """
        from .. import aide

        try:
            aide.expliquer(self, self.key)
        except Exception as exc:        # noqa: BLE001 - une aide ne casse rien
            log.debug("explications non posées sur %s : %s", self.TITLE, exc)

    def _tint_sections(self) -> None:
        """Donne aux titres de section la couleur de la page.

        Les trente-cinq panneaux de l'application portaient le même trait
        or : un panneau ne disait pas de quel écran il venait. Un panneau qui
        a déjà choisi sa couleur la garde — les raccourcis du tableau de bord
        montrent la teinte de **leur destination**, ce qui est le but.
        """
        from ..widgets.common import SectionTitle

        for titre in self.findChildren(SectionTitle):
            try:
                if titre.color() == GOLD:
                    titre.set_color(self.color)
            except Exception as exc:        # noqa: BLE001 - simple décor
                log.debug("teinte de section impossible : %s", exc)

    # -- rafraîchissement --------------------------------------------------- #

    def refresh(self) -> None:
        """Met la page à jour. Ne laisse jamais passer d'exception."""
        self._ensure_built()
        if self.NEEDS_CARD and not self.ctx.has_card:
            self._stack.setCurrentWidget(self._empty)
            return
        self._stack.setCurrentWidget(self._content)
        try:
            self._refresh()
        except Exception:  # noqa: BLE001 - rempart, cf. SPEC §6.3
            log.exception("rafraîchissement de la page %s en échec", self.TITLE)
            self.say("Une erreur est survenue : voir le journal.")

    def _refresh(self) -> None:
        """Corps du rafraîchissement. À redéfinir."""

    def showEvent(self, event) -> None:  # noqa: N802 - API Qt
        super().showEvent(event)
        self.refresh()

    # -- confort ------------------------------------------------------------ #

    def say(self, message: str) -> None:
        """Envoie un message à la barre d'état."""
        try:
            self.status.emit(str(message))
        except Exception:  # noqa: BLE001
            log.debug("message d'état non transmis")

    @property
    def lib(self):
        """Index SQLite."""
        return self.ctx.lib

    @property
    def sd(self):
        """Carte SD, éventuellement ``None``."""
        return self.ctx.sd

    @property
    def player(self):
        """Lecteur audio partagé."""
        return self.ctx.player

    def card_or_warn(self):
        """Carte SD, ou ``None`` après un avertissement à l'utilisateur."""
        return self.ctx.sd_or_warn(self)

    def write_song(self, build: Callable, default_name: str) -> str:
        """Écrit un morceau du Deluge construit par ``build(carte)``.

        Le parcours est celui de :func:`delugeapp.ui.songexport.export_song`
        : nom demandé, plan montré et confirmé, fichier **nouveau** dans
        SONGS, indexé aussitôt. Rend le chemin écrit, ou ``""``.
        """
        from ..songexport import export_song

        rel = export_song(self, self.ctx, build, default_name, self.say)
        if rel:
            self.songWritten.emit(rel)
        return rel

    # -- identité visuelle de la page --------------------------------------- #

    @property
    def key(self) -> str:
        """Clé de navigation : ``SamplesPage`` -> ``Samples``."""
        nom = type(self).__name__
        return nom[:-4] if nom.endswith("Page") else nom

    @property
    def color(self) -> str:
        """Couleur de la page, la même que dans la barre latérale."""
        return page_color(self.key)

    def header(self, title: str,
               subtitle: str = "") -> tuple[QWidget, QHBoxLayout]:
        """En-tête de la page, déjà teinté à sa couleur et à son icône.

        Les neuf pages appelaient ``page_header`` sans couleur et se
        ressemblaient donc toutes. Passer par la page évite d'avoir à répéter
        la teinte à chaque appel — et d'oublier de la mettre à jour.
        """
        return page_header(title, subtitle, self.color, self.ICON,
                           seed=art.seed_of(self.key))

    def focus_on(self, hint: str) -> None:
        """Place la page sur la partie désignée par ``hint``.

        ``hint`` est le libellé d'un onglet, comparé sans tenir compte de la
        casse ni des accents : ``Health#Doublons`` ouvre la santé de la carte
        **sur** son onglet des doublons. Une page sans onglets, ou un libellé
        inconnu, ne fait rien — un raccourci approximatif ne doit jamais
        empêcher d'arriver sur la page.

        Les pages qui ont mieux à proposer redéfinissent la méthode.
        """
        from PyQt6.QtWidgets import QTabWidget

        cible = _sans_accents(hint)
        if not cible:
            return
        for onglets in self.findChildren(QTabWidget):
            for index in range(onglets.count()):
                if cible in _sans_accents(onglets.tabText(index)):
                    onglets.setCurrentIndex(index)
                    return
        log.debug("partie introuvable sur %s : %r", self.TITLE, hint)

    def guard(self, fn: Callable[..., Any]) -> Callable[..., None]:
        """Enveloppe un gestionnaire de signal dans un ``try/except``.

        La SPEC §6.3 l'exige pour chaque gestionnaire : une exception dans un
        connecteur Qt remonte sinon jusqu'à la boucle d'événements.

        **L'enveloppe ne transmet que les arguments que le destinataire sait
        recevoir.** PyQt tronque d'ordinaire les arguments excédentaires d'un
        signal selon l'arité du destinataire : ``clicked(bool)`` branché sur
        une méthode sans paramètre marche donc normalement. Mais une
        enveloppe variadique défait ce mécanisme — PyQt voit un appelable qui
        accepte tout, et transmet le booléen, qui arrive à une méthode qui
        n'en veut pas :

            TypeError: _listen() takes 1 positional argument but 2 were given

        Les 55 boutons branchés par ``guard`` levaient cette erreur **au
        premier clic réel**, alors que les tests, qui appelaient les méthodes
        directement, passaient tous. D'où la troncature explicite ci-dessous,
        et un test qui clique vraiment sur chaque bouton de chaque page.
        """
        limite = _arite(fn)

        def wrapper(*args, **kwargs) -> None:
            try:
                # Un travail rendu par un fil arrive par un signal **mis en
                # file** : il peut être délivré après la fermeture de la
                # fenêtre, donc après ``AppContext.close()``. Le diagnostic
                # de santé, qui part tout seul à l'affichage, a montré trois
                # « Cannot operate on a closed database » à la fermeture.
                if getattr(self.ctx, "closed", False):
                    log.debug("contexte fermé : action ignorée sur %s",
                              self.TITLE)
                    return
                if limite is not None and len(args) > limite:
                    args = args[:limite]
                fn(*args, **kwargs)
            except Exception:  # noqa: BLE001
                log.exception("action de la page %s en échec", self.TITLE)
                self.say("Action impossible : voir le journal.")
        return wrapper

    def audition(self, sound, notes=60, seconds: float = 0.8) -> bool:
        """Fait jouer ``sound`` **par le Deluge**, s'il est branché.

        Rend ``True`` si la machine a pris le relais ; la page n'a alors plus
        rien à rendre. Rend ``False`` dans tous les autres cas — réglage non
        demandé, machine absente, envoi refusé — et la page poursuit avec son
        moteur habituel.

        Les réglages du son partent en contrôleurs juste avant la note :
        c'est le mode MIDI Follow qui les applique à l'instrument
        **sélectionné sur la machine**, que l'application ne peut pas
        choisir à distance.
        """
        try:
            if not getattr(self.ctx.settings, "midi_audition", False):
                return False
            lien = getattr(self.ctx, "link", None)
            if lien is None or not lien.is_connected or sound is None:
                return False
            if not lien.play_notes(notes, seconds=seconds, sound=sound):
                return False
            self.say("Écouté sur le Deluge (canal %d)." % lien.channel)
            return True
        except Exception as exc:        # noqa: BLE001 - l'écoute n'est pas vitale
            log.debug("écoute sur le Deluge impossible : %s", exc)
            return False

    def run(self, fn, *args, **kwargs):
        """Lance un travail long hors du fil de l'interface."""
        from ..tasks import run_task

        kwargs.setdefault("title", "Traitement…")
        return run_task(self, fn, *args, **kwargs)


class _ActionsCompactes(QObject):
    """Réduit les boutons à leur icône quand la barre ne tient plus.

    Le texte n'est pas perdu : il revient dès que la fenêtre s'élargit, et
    l'infobulle le dit de toute façon — chaque commande s'explique
    (cf. :mod:`delugeapp.ui.aide`).
    """

    def __init__(self, host: QWidget, titre: QWidget,
                 actions: QHBoxLayout) -> None:
        super().__init__(host)
        self._host = host
        self._titre = titre
        self._actions = actions
        self._textes: dict[int, str] = {}
        #: 0 tous les textes, 1 seul le principal, 2 aucun.
        self._compact = 0
        host.installEventFilter(self)

    def eventFilter(self, objet, evenement) -> bool:   # noqa: N802 - API Qt
        # À l'affichage aussi : la première taille arrive avant que la page
        # ait montré ses enfants, et si la fenêtre ne change plus de taille
        # ensuite, aucun autre redimensionnement ne viendrait réveiller
        # l'ajusteur.
        if evenement.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self.ajuster()
        return False

    def _boutons(self) -> list:
        sortie = []
        for index in range(self._actions.count()):
            element = self._actions.itemAt(index)
            widget = element.widget() if element is not None else None
            # « Pas masqué » plutôt que « visible » : un bouton n'est visible
            # qu'une fois sa page affichée, et l'ajusteur, qui ne comptait
            # que ceux-là, ne trouvait rien à replier à sa première mesure —
            # mesuré à 980 px : six boutons coupés en plein mot, état 0.
            if isinstance(widget, QPushButton) and not widget.isHidden():
                sortie.append(widget)
        return sortie

    def ajuster(self) -> None:
        try:
            boutons = self._boutons()
            if not boutons:
                return
            for bouton in boutons:
                if id(bouton) not in self._textes:
                    self._textes[id(bouton)] = bouton.text()
                    # Le nom complet reste lisible par qui en a besoin
                    # même une fois le bouton replié : le registre d'aide
                    # s'en sert pour retrouver son explication.
                    bouton.setProperty("libelleComplet", bouton.text())

            # Les marges de l'en-tête comptent : sans elles, la barre se
            # croyait plus large qu'elle n'est et son dernier bouton sortait
            # du cadre arrondi.
            marges = 0
            disposition = self._host.layout()
            if disposition is not None:
                bords = disposition.contentsMargins()
                marges = (bords.left() + bords.right()
                          + 2 * disposition.spacing())
            dispo = (self._host.width() - marges
                     - self._titre.sizeHint().width() - 24)
            marge = self._actions.spacing() * (len(boutons) - 1)

            # Trois états, du plus bavard au plus serré. L'action
            # **principale** garde son nom le plus longtemps possible :
            # c'est celle que l'on cherche en premier.
            tout = sum(self._largeur_depliee(b)
                       for b in boutons) + marge
            sauf_principal = sum(
                self._largeur_depliee(b) if self._est_principal(b)
                else self._largeur_repliee(b)
                for b in boutons) + marge

            if tout <= dispo:
                etat = 0                  # tout le monde parle
            elif sauf_principal <= dispo:
                etat = 1                  # seul le principal parle
            else:
                etat = 2                  # que des icônes
            if etat != self._compact:
                self._replier(boutons, etat)
        except Exception as exc:       # noqa: BLE001 - un ajustement ne casse rien
            log.debug("barre d'actions non ajustée : %s", exc)

    @staticmethod
    def _est_principal(bouton) -> bool:
        return bouton.objectName() == "Primary"

    def _largeur_depliee(self, bouton) -> int:
        """Largeur qu'aurait le bouton avec son texte."""
        texte = self._textes.get(id(bouton), "")
        if not texte or bouton.text():
            return bouton.sizeHint().width()
        metrique = bouton.fontMetrics().horizontalAdvance(texte)
        return bouton.sizeHint().width() + metrique + 8

    def _largeur_repliee(self, bouton) -> int:
        """Largeur du bouton réduit à sa seule icône."""
        if not bouton.text():
            return bouton.sizeHint().width()
        metrique = bouton.fontMetrics().horizontalAdvance(bouton.text())
        return max(34, bouton.sizeHint().width() - metrique)

    def _replier(self, boutons, etat: int) -> None:
        """0 : tous les textes ; 1 : seul le principal ; 2 : aucun."""
        for bouton in boutons:
            texte = self._textes.get(id(bouton), bouton.text())
            garde = etat == 0 or (etat == 1
                                  and self._est_principal(bouton))
            if garde:
                bouton.setText(texte)
            elif bouton.text():
                # L'infobulle reprend le libellé : sans texte visible,
                # c'est elle qui nomme le bouton.
                aide = bouton.toolTip()
                if texte and texte not in aide:
                    bouton.setToolTip("%s — %s" % (texte, aide) if aide
                                      else texte)
                bouton.setText("")
        self._compact = etat


class PageHero(QFrame):
    """L'en-tête d'une page : une ouverture de partie du guide.

    Dans le livre, chaque partie s'ouvre sur un treillis de circuits à sa
    couleur, un filet de cette couleur, et le titre en capitales. Chaque
    page de l'application fait de même : le pad allumé de la page, le titre
    en capitales, et à droite le treillis — tracé par :mod:`delugeapp.ui.art`
    à la couleur de la page, d'une graine qui lui est propre, et qui
    s'efface vers le titre pour ne jamais gêner sa lecture.

    À chaque affichage, le treillis s'allume en une demi-seconde : la page
    « s'ouvre ». Seul l'en-tête se repeint pendant ce temps, et son dessin
    est en cache.
    """

    #: Durée de l'apparition du treillis, en millisecondes.
    REVEAL_MS = 520

    def __init__(self, title: str, subtitle: str = "", color: str = GOLD,
                 icon_name: str = "", seed: int = 0,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Hero")
        self._color = color
        self._seed = int(seed)
        self._reveal = 1.0
        self.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 14, 6)
        layout.setSpacing(8)

        self.title_area = QWidget(self)
        gauche = QHBoxLayout(self.title_area)
        gauche.setContentsMargins(0, 0, 0, 0)
        gauche.setSpacing(6)
        self.pad: LitPad | None = None
        if icon_name:
            self.pad = LitPad(icon_name, color, 42, self.title_area, halo=10)
            gauche.addWidget(self.pad)

        bloc = QWidget(self.title_area)
        colonne = QVBoxLayout(bloc)
        colonne.setContentsMargins(0, 0, 0, 0)
        colonne.setSpacing(0)
        colonne.addStretch(1)
        self.heading = QLabel(title, bloc)
        self.heading.setProperty("role", "h1")
        colonne.addWidget(self.heading)
        self.hint: QLabel | None = None
        if subtitle:
            self.hint = QLabel(subtitle, bloc)
            self.hint.setProperty("role", "subtitle")
            colonne.addWidget(self.hint)
        colonne.addStretch(1)
        gauche.addWidget(bloc)
        layout.addWidget(self.title_area)
        layout.addStretch(1)

        self.actions = QHBoxLayout()
        self.actions.setContentsMargins(0, 0, 0, 0)
        self.actions.setSpacing(8)
        layout.addLayout(self.actions)
        self.setMinimumHeight(74)

        self._animation = QVariantAnimation(self)
        self._animation.setDuration(self.REVEAL_MS)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.valueChanged.connect(self._reveler)

    def color(self) -> str:
        return self._color

    def reveal(self) -> float:
        """Avancement de l'apparition du treillis, de 0 à 1."""
        return self._reveal

    def _reveler(self, valeur) -> None:
        try:
            self._reveal = max(0.0, min(1.0, float(valeur)))
        except (TypeError, ValueError):
            return
        self.update()

    def showEvent(self, event) -> None:  # noqa: N802 - API Qt
        super().showEvent(event)
        try:
            self._animation.stop()
            self._animation.start()
        except Exception as exc:        # noqa: BLE001 - un décor ne casse rien
            log.debug("apparition de l'en-tête impossible : %s", exc)

    def paintEvent(self, event) -> None:  # noqa: N802 - API Qt
        try:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            cadre = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            chemin = QPainterPath()
            chemin.addRoundedRect(cadre, 16, 16)

            # Le fond : la surface d'un panneau, qui prend la couleur de la
            # page vers la droite, là où passent les circuits.
            fond = QLinearGradient(cadre.topLeft(), cadre.topRight())
            fond.setColorAt(0.0, QColor(CARD_TOP))
            fond.setColorAt(0.45, QColor(PANEL))
            fond.setColorAt(1.0, QColor(mix(PANEL_LO, self._color, 0.10)))
            p.fillPath(chemin, fond)

            # Le treillis du guide, à la couleur de la page.
            dessin = art.circuit(self.width(), self.height(), self._color,
                                 self._seed, self.devicePixelRatioF(),
                                 density=0.46, fade=(0.30, 0.74))
            p.save()
            p.setClipPath(chemin)
            p.setOpacity(0.68 * self._reveal)
            p.drawPixmap(QPointF(0, 0), dessin)
            p.restore()

            # Le filet du guide, sous le tout : franc à gauche, estompé
            # vers la droite.
            filet = QLinearGradient(cadre.bottomLeft(), cadre.bottomRight())
            plein = QColor(self._color)
            plein.setAlphaF(0.85)
            vide = QColor(self._color)
            vide.setAlphaF(0.0)
            filet.setColorAt(0.0, plein)
            filet.setColorAt(0.55, vide)
            p.save()
            p.setClipPath(chemin)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(filet)
            p.drawRect(QRectF(cadre.left(), cadre.bottom() - 2.0,
                              cadre.width(), 2.0))
            p.restore()

            p.setPen(QPen(QColor(BORDER_SOFT), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(chemin)
            p.end()
        except Exception as exc:        # noqa: BLE001 - un décor ne casse rien
            log.debug("en-tête de page non tracé : %s", exc)


def page_header(title: str, subtitle: str = "", color: str = GOLD,
                icon_name: str = "",
                seed: int = 0) -> tuple[QWidget, QHBoxLayout]:
    """En-tête de page : titre, sous-titre, et une barre d'actions à droite.

    Retourne le widget et la disposition dans laquelle ajouter les boutons.

    L'en-tête est une « ouverture de partie » du guide (:class:`PageHero`) :
    le pad allumé de la page à gauche du titre — identique à celui de la
    colonne de navigation —, le titre en capitales, et le treillis à la
    couleur de la page. On reconnaît l'écran à sa teinte avant de lire son
    titre.
    """
    host = PageHero(title, subtitle, color, icon_name, seed)
    # Les libellés se replient sur leur icône quand la fenêtre rétrécit,
    # plutôt que d'être coupés en plein mot.
    host._actions_compactes = _ActionsCompactes(host, host.title_area,
                                                host.actions)
    return host, host.actions


def tool_button(label: str, icon_name: str = "", tooltip: str = "",
                primary: bool = False, color: str = GOLD) -> QPushButton:
    """Bouton d'action d'une barre de page.

    * un bouton **principal** est un pad allumé : plein, à la couleur de la
      page (que la feuille de la page lui donne), et il rayonne
      (:meth:`Page._light_up`). Son icône est tracée à l'encre qui se lit
      sur ce fond, et le nom de l'icône est gardé (``iconName``) pour la
      retracer quand la page connaît sa couleur ;
    * un bouton **coloré** devient un pad de la machine : sa couleur en
      veilleuse, pleine une fois choisi (voir :func:`_pad_style`). Elle
      ne servait auparavant qu'à teinter l'icône, et seulement pour un
      bouton principal : les 22 genres du générateur passaient chacun leur
      teinte et s'affichaient tous en gris identique ;
    * les autres sont des touches de façade éteintes.
    """
    button = QPushButton(label)
    if icon_name:
        button.setProperty("iconName", icon_name)
        if primary:
            teinte = lit_fill(color)[2]
        elif color and color != GOLD:
            teinte = color
        else:
            teinte = GREY_LIGHT
        button.setIcon(icons.icon(icon_name, teinte, 16))
    if tooltip:
        button.setToolTip(tooltip)
    if primary:
        button.setObjectName("Primary")
    elif color and color != GOLD:
        button.setStyleSheet(_pad_style(color))
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


def _pad_style(color: str) -> str:
    """Feuille de style d'un bouton-pad, à la couleur donnée.

    Comme sur la machine, un pad qui n'est pas joué montre déjà sa couleur
    en veilleuse ; choisi, il s'allume en plein. Les teintes passent par
    ``rgba(...)`` : c'est la syntaxe que le QSS attend. (``QColor`` ne sait
    pas la lire, mais ici c'est bien du QSS.)
    """
    rouge, vert, bleu = _rgb(color)
    haut, bas, encre = lit_fill(color)
    return (
        "QPushButton {"
        " border: 1px solid rgba(%d,%d,%d,105);"
        " border-top-color: rgba(%d,%d,%d,150);"
        " background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
        " stop:0 rgba(%d,%d,%d,58), stop:1 rgba(%d,%d,%d,28));"
        " color: %s; padding: 6px 8px; border-radius: 10px; }"
        "QPushButton:hover {"
        " background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
        " stop:0 rgba(%d,%d,%d,82), stop:1 rgba(%d,%d,%d,42));"
        " border-color: rgba(%d,%d,%d,215); }"
        "QPushButton:pressed {"
        " background-color: rgba(%d,%d,%d,120); }"
        "QPushButton:checked {"
        " background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
        " stop:0 %s, stop:1 %s);"
        " color: %s; font-weight: 700; border: 1px solid %s; }"
        "QPushButton:disabled {"
        " background-color: %s; color: %s; border-color: %s; }"
        % (rouge, vert, bleu, rouge, vert, bleu,
           rouge, vert, bleu, rouge, vert, bleu,
           PAD_WHITE,
           rouge, vert, bleu, rouge, vert, bleu, rouge, vert, bleu,
           rouge, vert, bleu,
           haut, bas, encre, haut,
           PANEL, TEXT_MUTED, BORDER_SOFT))
