# -*- coding: utf-8 -*-
"""Page « Tableau de bord ».

La première chose que voit l'utilisateur : ce que contient sa carte, dans quel
état elle est, et les quatre ou cinq gestes qu'il fait le plus souvent.

L'analyse de la carte part d'ici, dans un fil séparé : sur la carte d'essai
elle prend deux secondes, mais sur une carte lue par un lecteur USB lent elle
peut durer bien plus, et l'interface doit rester vivante (SPEC §6.2).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...core.scan import scan_card
from ...i18n import N_, clock, day_month, integer, tr
from ..theme import (
    GOLD,
    GREY,
    PAD,
    PAD_AMBER,
    PAD_CYAN,
    PAD_GREEN,
    PAD_MAGENTA,
    PANEL_HI,
    pad_color,
    page_color,
    severity_color,
    with_alpha,
)
from ..widgets.common import (
    clear_layout,
    BusyBar,
    Card,
    ElidedLabel,
    GrilleAdaptative,
    LitPad,
    RangeeAdaptative,
    ScoreRing,
    SegmentMeter,
    StatTile,
    human_datetime,
    human_duration,
    human_size,
)
from .base import Page, tool_button

log = logging.getLogger(__name__)

#: Nombre de dossiers montrés dans la répartition.
TOP_FOLDERS = 10

#: Où l'on répare chaque sorte d'anomalie.
#:
#: Les codes viennent de ``core/health.py`` ; relevés sur la carte réelle :
#: MAC_JUNK (1 564), ORPHAN_SAMPLE (379), MISSING_SAMPLE (125),
#: ODD_SAMPLE_RATE (89), STEREO_DRUM (58), CLIPPED_SAMPLE (35), DC_OFFSET
#: (17), REPAIRED_XML (6), NON_AUDIO_IN_SAMPLES (4), BAD_NAME (2),
#: BIG_SAMPLE (1). Ceux qui n'ont pas d'onglet dédié mènent au rapport, où
#: la correction automatique les prend en charge.
ISSUE_DESTINATION: dict[str, str] = {
    "MISSING_SAMPLE": "Health#Manquants",
    "ORPHAN_SAMPLE": "Health#Inutilisés",
    "DUPLICATE_SAMPLE": "Health#Doublons",
    "NO_BACKUP": "Health#Sauvegardes",
}

#: Où s'ouvre un fichier reçu du Deluge, selon son dossier : page, et ce
#: qu'il est, en un mot.
ARRIVAL_PAGES: dict[str, tuple[str, str]] = {
    "SONGS": ("Songs", N_("morceau")),
    "SYNTHS": ("Synths", N_("preset")),
    "KITS": ("Kits", N_("kit")),
    "SAMPLES": ("Samples", N_("son")),
}

#: Le nom des pages où mènent les anomalies, pour dire où l'on va.
_PAGE_NAMES = {"Health": N_("Santé")}


def _quand(instant: float) -> str:
    """« aujourd'hui à 14h53 », « hier à 9h05 », « le 15/10 à 12h31 »."""
    moment = datetime.fromtimestamp(float(instant))
    jour = moment.date()
    if jour == date.today():
        return tr("aujourd'hui à %s") % clock(moment)
    if jour == date.today() - timedelta(days=1):
        return tr("hier à %s") % clock(moment)
    return tr("le %s à %s") % (day_month(moment), clock(moment))


def _lieu(cible: str) -> str:
    """« Health#Manquants » dit à l'utilisateur : « Santé › Manquants »."""
    page, _diese, partie = cible.partition("#")
    nom = tr(_PAGE_NAMES.get(page, page))
    return "%s › %s" % (nom, tr(partie)) if partie else nom


class _LigneAnomalie(QWidget):
    """Ligne d'anomalie cliquable, qui mène là où on la répare."""

    clicked = pyqtSignal()

    def __init__(self, cible: str, parent=None) -> None:
        super().__init__(parent)
        self.cible = cible
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "QWidget:hover { background-color: %s; border-radius: 4px; }"
            % PANEL_HI)

    def mouseReleaseEvent(self, event) -> None:      # noqa: N802 - API Qt
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class DashboardPage(Page):
    """Vue d'ensemble de la carte."""

    TITLE = N_("Tableau de bord")
    ICON = "dashboard"

    #: Demande d'aller sur une autre page, par son nom de classe abrégé.
    navigateRequested = pyqtSignal(str)
    #: L'analyse vient de se terminer : les autres pages doivent se rafraîchir.
    scanFinished = pyqtSignal()
    #: Envoyer des fichiers du PC au Deluge : la fenêtre ouvre le choix.
    sendRequested = pyqtSignal(list, str)
    #: Synchroniser tout de suite avec le Deluge branché.
    syncRequested = pyqtSignal()
    #: Mettre la sauvegarde de la carte à jour (le plan est montré d'abord).
    backupRequested = pyqtSignal()

    def __init__(self, ctx, parent=None) -> None:
        super().__init__(ctx, parent)
        self._worker = None
        #: Vrai pendant la mise à jour automatique du démarrage : son bilan
        #: dit ce qui a été relu, pas le contenu entier de la carte.
        self._auto_scan = False
        self._tiles: dict[str, StatTile] = {}
        #: Statistiques et diagnostic du dernier rafraîchissement : le
        #: bandeau se recalcule sur eux quand seul l'état de la carte change.
        self._dernier_etat: tuple | None = None

    # -- construction ------------------------------------------------------- #

    def build(self) -> None:
        outer = QVBoxLayout(self.content())
        outer.setContentsMargins(PAD, PAD, PAD, PAD)
        outer.setSpacing(PAD)

        # Rien dans la barre d'actions de la page : les commandes de
        # l'analyse descendent dans la carte « Carte », aux côtés de la date
        # de la dernière analyse — c'est là qu'on apprend qu'elle manque. La
        # barre d'en-tête de la fenêtre garde le « Analyser » global
        # (Ctrl+R), un seul au lieu de deux voisins identiques.
        header, _actions = self.header(
            tr("Tableau de bord"), tr("Ce que contient la carte, et son état"))
        outer.addWidget(header)

        self._progress = BusyBar()
        self._progress.setVisible(False)
        outer.addWidget(self._progress)

        self._progress_label = QLabel()
        self._progress_label.setProperty("role", "subtitle")
        self._progress_label.setVisible(False)
        outer.addWidget(self._progress_label)

        scroll = QScrollArea(self.content())
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        inner = QWidget()
        column = QVBoxLayout(inner)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(PAD)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

        column.addWidget(self._build_next_step())
        column.addWidget(self._build_exchanges())
        column.addWidget(self._build_tiles())
        column.addWidget(self._build_card_info())

        row = QHBoxLayout()
        row.setSpacing(PAD)
        row.addWidget(self._build_health(), 1)
        row.addWidget(self._build_actions(), 1)
        holder = QWidget()
        holder.setLayout(row)
        column.addWidget(holder)

        column.addWidget(self._build_folders())
        column.addStretch(1)

        # La page s'adapte à la place **visible**, pas à sa propre largeur :
        # un contenu trop large ne rétrécit jamais de lui-même, il pousse la
        # page sous une barre de défilement horizontale. Mesuré à 980 px.
        self._grille_tuiles = GrilleAdaptative(
            scroll.viewport(), self._tiles_grid,
            [self._tiles[cle] for cle in self._tile_order], 3, 2, 930)
        self._rangee_sante = RangeeAdaptative(scroll.viewport(), row, 900)

    def _build_next_step(self) -> QWidget:
        """Le bandeau « et maintenant ? », caché quand il n'a rien à dire."""
        self._next_card = Card(tr("À faire maintenant"), color=self.color)
        body = self._next_card.body()

        row = QHBoxLayout()
        row.setSpacing(10)

        # Le pad de la suggestion, allumé à la couleur de l'endroit où elle
        # mène : sauvegarder est orange comme la santé, générer est magenta
        # comme le générateur.
        self._next_icon = LitPad("refresh", self.color, 34, halo=8)
        row.addWidget(self._next_icon)

        self._next_text = QLabel("—")
        self._next_text.setWordWrap(True)
        row.addWidget(self._next_text, 1)

        self._next_button = tool_button("", "", primary=True)
        self._next_button.clicked.connect(self.guard(self._do_next_step))
        row.addWidget(self._next_button)

        holder = QWidget()
        holder.setLayout(row)
        body.addWidget(holder)
        self._next_target = ""
        self._next_card.setVisible(False)
        return self._next_card

    def _do_next_step(self) -> None:
        """Le bouton du bandeau : analyser, ou aller là où ça se répare."""
        if self._next_target == "@scan":
            self._start_scan()
            return
        if self._next_target == "@backup":
            self.backupRequested.emit()
            return
        if self._next_target:
            self.navigateRequested.emit(self._next_target)

    def _fill_next_step(self, stats: dict, report=None) -> None:
        """Choisit **la** suggestion la plus utile, et la montre.

        L'ordre est celui de l'urgence réelle, pas celui des fonctions :
        on ne propose pas de fabriquer des presets à quelqu'un dont la carte
        n'a jamais été sauvegardée.
        """
        suggestion = self._next_suggestion(stats, report)
        if suggestion is None:
            self._next_card.setVisible(False)
            self._next_target = ""
            return

        texte, bouton, cible, icone, teinte = suggestion
        self._next_target = cible
        self._next_text.setText(texte)
        self._next_button.setText(bouton)
        self._next_icon.set_icon(icone)
        self._next_icon.set_color(teinte)
        self._next_card.setVisible(True)

    def _next_suggestion(self, stats: dict, report=None):
        """``(phrase, bouton, destination, icône, couleur)`` ou ``None``."""
        if self.sd is None:
            return None

        compte = sum(int((stats or {}).get(cle, 0) or 0)
                     for cle in ("samples", "synths", "kits", "songs"))
        if compte == 0:
            return (tr("Cette carte n'a jamais été lue. L'analyse construit "
                       "l'index qui fait vivre toutes les autres pages — "
                       "elle ne modifie rien."),
                    tr("Analyser la carte"), "@scan", "refresh", self.color)

        anomalies = {i.code: i for i in getattr(report, "issues", ())}

        # Le diagnostic ne connaît que les sauvegardes faites par
        # l'application ; le miroir de la carte que l'utilisateur garde
        # (« SDCARD Deluge ») en est une aussi. Avec lui, la question n'est
        # plus « aucune sauvegarde » mais « ce qui lui manque » — juste
        # en dessous.
        manque = anomalies.get("NO_BACKUP")
        miroir = self.ctx.settings.card_backup_path()
        if manque is not None and (miroir is None or not miroir.is_dir()):
            return (tr("Aucune sauvegarde de cette carte. Avant toute "
                       "correction, une copie complète évite de perdre des "
                       "mois de travail."),
                    tr("Sauvegarder"), "Health#Sauvegardes", "backup",
                    page_color("Health"))

        # Ce que le Deluge vient d'enregistrer n'est nulle part ailleurs que
        # sur sa carte et dans la copie de travail : la sauvegarde de
        # l'utilisateur ne le reçoit que sur commande.
        travail = getattr(self.ctx, "card_work", None)
        en_retard = travail.backup_missing() if (
            travail is not None and travail.working_on_copy()) else 0
        if en_retard:
            return (tr("Votre sauvegarde n'a pas encore %d fichier(s) de la "
                       "carte — ce que vous avez enregistré sur le Deluge ou "
                       "créé ici depuis sa dernière mise à jour.") % en_retard,
                    tr("Mettre à jour la sauvegarde"), "@backup", "backup",
                    page_color("Health"))

        absents = anomalies.get("MISSING_SAMPLE")
        if absents is not None and absents.count:
            return (tr("%d échantillon(s) réclamé(s) par des presets sont "
                       "absents de la carte : ces pads resteront muets sur "
                       "la machine.") % absents.count,
                    tr("Les retrouver"), "Health#Manquants", "warning",
                    page_color("Health"))

        doublons = anomalies.get("DUPLICATE_SAMPLE")
        if doublons is not None and doublons.count:
            return (tr("%d fichier(s) en double, vérifiés octet par octet "
                       ": de la place à récupérer sans rien perdre.")
                    % doublons.count,
                    tr("Voir les doublons"), "Health#Doublons", "copy",
                    page_color("Health"))

        inutilises = anomalies.get("ORPHAN_SAMPLE")
        if inutilises is not None and inutilises.count > 200:
            return (tr("%d échantillons ne servent à aucun preset, kit ni "
                       "morceau. Les archiver allège la carte sans rien "
                       "supprimer.") % inutilises.count,
                    tr("Les ranger"), "Health#Inutilisés", "folder",
                    page_color("Health"))

        # Rien ne cloche : on propose de créer, ce pour quoi la carte est
        # faite.
        return (tr("La carte est en ordre. De quoi fabriquer un son : le "
                   "générateur part d'un genre et vous rend un preset prêt "
                   "à enregistrer."),
                tr("Générer un preset"), "Generator#Preset de synthé",
                "wand", page_color("Generator"))

    # -- le Deluge et le PC ---------------------------------------------------- #

    def _build_exchanges(self) -> QWidget:
        """« Le Deluge et le PC » : où en est le lien, ce qui attend le Deluge,
        ce qui en est arrivé, et la porte d'entrée des fichiers du PC.

        Le panneau a la couleur de la pastille du Deluge connecté. Avant lui,
        un échange ne laissait qu'un message de dix secondes dans la barre
        d'état, et rien ne disait ce qui attendait la prochaine connexion.
        """
        card = Card(tr("Le Deluge et le PC"), color=PAD_GREEN)
        self._exchanges_card = card
        body = card.body()

        haut = QHBoxLayout()
        haut.setContentsMargins(0, 0, 0, 0)
        haut.setSpacing(10)
        self._link_pad = LitPad("midi", GREY, 34, halo=8)
        haut.addWidget(self._link_pad)
        textes = QVBoxLayout()
        textes.setSpacing(2)
        self._link_state = QLabel("—")
        self._link_state.setWordWrap(True)
        textes.addWidget(self._link_state)
        self._link_detail = QLabel("")
        self._link_detail.setProperty("role", "subtitle")
        self._link_detail.setWordWrap(True)
        textes.addWidget(self._link_detail)
        haut.addLayout(textes, 1)
        self._sync_button = tool_button(tr("Synchroniser"), "refresh",
                                        color=PAD_GREEN)
        # Une lambda, pas ``emit`` lui-même : ``emit`` accepte tout, et
        # ``guard`` lui transmettrait le booléen de ``clicked``.
        self._sync_button.clicked.connect(
            self.guard(lambda: self.syncRequested.emit()))
        haut.addWidget(self._sync_button)
        self._send_button = tool_button(tr("Envoyer des fichiers…"),
                                        "import", color=PAD_GREEN)
        self._send_button.clicked.connect(
            self.guard(lambda: self.sendRequested.emit([], "")))
        haut.addWidget(self._send_button)
        self._goto_card_button = tool_button(tr("Carte du Deluge…"),
                                             "settings",
                                             color=page_color("Settings"))
        self._goto_card_button.clicked.connect(
            self.guard(lambda: self.navigateRequested.emit("Settings")))
        haut.addWidget(self._goto_card_button)
        hote = QWidget()
        hote.setLayout(haut)
        body.addWidget(hote)

        self._arrivals_title = QLabel(tr("Reçu du Deluge"))
        self._arrivals_title.setProperty("role", "subtitle")
        body.addWidget(self._arrivals_title)
        self._arrivals = QVBoxLayout()
        self._arrivals.setSpacing(2)
        body.addLayout(self._arrivals)

        ligne = QHBoxLayout()
        ligne.setContentsMargins(0, 0, 0, 0)
        self._backup_text = QLabel("")
        self._backup_text.setWordWrap(True)
        ligne.addWidget(self._backup_text, 1)
        self._backup_button = tool_button(tr("Mettre à jour la sauvegarde"),
                                          "backup",
                                          color=page_color("Health"))
        self._backup_button.clicked.connect(
            self.guard(lambda: self.backupRequested.emit()))
        ligne.addWidget(self._backup_button)
        self._backup_row = QWidget()
        self._backup_row.setLayout(ligne)
        body.addWidget(self._backup_row)

        self._drop_hint = QLabel(tr(
            "Glissez sur la fenêtre des sons, des presets ou un pack entier : "
            "ils partent sur le Deluge, le plan montré d'abord."))
        self._drop_hint.setWordWrap(True)
        self._drop_hint.setProperty("role", "subtitle")
        self._drop_hint.setStyleSheet(
            "QLabel { border: 1px dashed %s; border-radius: 8px;"
            " padding: 8px 10px; }" % with_alpha(PAD_GREEN, 0.55))
        body.addWidget(self._drop_hint)
        return card

    def refresh_exchanges(self) -> None:
        """Redessine le panneau « Le Deluge et le PC », et le bandeau qui
        peut en dépendre : l'état de la carte change — une comparaison avec
        la sauvegarde aboutit, une synchronisation finit — sans que le reste
        du tableau de bord ait bougé. Le diagnostic n'est pas relancé."""
        if not self._built or self.sd is None:
            return
        try:
            if self._dernier_etat is not None:
                self._fill_next_step(*self._dernier_etat)
            self._fill_exchanges()
        except Exception:  # noqa: BLE001 - rempart, cf. SPEC §6.3
            log.exception("panneau des échanges non rempli")

    def _fill_exchanges(self) -> None:
        travail = getattr(self.ctx, "card_work", None)
        role = self.ctx.settings.card_role(self.sd.root)
        lien = getattr(self.ctx, "link", None)
        connecte = bool(lien is not None and lien.is_connected)
        usb = bool(travail is not None and travail.files() is not None)
        sur_la_copie = role == "travail" and travail is not None

        self._sync_button.setVisible(sur_la_copie)
        self._send_button.setVisible(role != "sauvegarde")
        self._goto_card_button.setVisible(role == "sauvegarde")
        self._drop_hint.setVisible(role != "sauvegarde")
        clear_layout(self._arrivals)
        arrivees = travail.arrivals(6) if sur_la_copie else []
        self._arrivals_title.setVisible(bool(arrivees))
        for quand, rel in arrivees:
            self._arrivals.addWidget(self._arrival_row(quand, rel))
        manque = travail.backup_missing() if sur_la_copie else 0
        # Le bandeau « à faire maintenant » le dit déjà : pas deux fois.
        self._backup_row.setVisible(bool(manque)
                                    and self._next_target != "@backup")
        if manque:
            self._backup_text.setText(
                tr("Votre sauvegarde n'a pas encore %d fichier(s) de la "
                   "carte.") % manque)

        if role == "sauvegarde":
            self._set_link(GREY, "backup",
                           tr("Vous regardez la sauvegarde de la carte, en "
                              "lecture seule."),
                           tr("Pour échanger avec le Deluge, l'application "
                              "travaille sur sa carte : Réglages ▸ Carte du "
                              "Deluge."))
            return
        if not sur_la_copie:
            self._set_link(PAD_CYAN, "folder",
                           tr("Carte ouverte directement dans un lecteur du "
                              "PC.") if role == "carte"
                           else tr("Carte ouverte directement."),
                           tr("Ce que vous y envoyez est copié tout de suite. "
                              "Avec le firmware 1.3, la carte peut rester "
                              "dans le Deluge : Réglages ▸ Carte du Deluge."))
            return

        if travail.busy:
            couleur, icone, etat = (PAD_AMBER, "refresh",
                                    tr("Synchronisation avec le Deluge…"))
        elif usb:
            couleur, icone, etat = (PAD_GREEN, "midi",
                                    tr("Deluge branché : sa carte s'ouvre par "
                                       "le câble USB."))
        elif connecte:
            couleur, icone, etat = (GOLD, "midi",
                                    tr("Deluge branché, mais sa carte ne "
                                       "s'ouvre pas par USB : il faut le "
                                       "firmware 1.3."))
        else:
            couleur, icone, etat = GREY, "midi", tr("Deluge débranché.")
        details = [travail.pending_text() + "." if travail.pending
                   else tr("Tout ce qui est ici est aussi sur le Deluge.")]
        derniers = travail.exchanges(1)
        if derniers:
            details.append(tr("Dernier échange %s : %s.")
                           % (_quand(derniers[0].when), derniers[0].summary()))
        self._set_link(couleur, icone, etat, " ".join(details))
        self._sync_button.setEnabled(usb and not travail.busy)

    def _set_link(self, couleur: str, icone: str, etat: str,
                  detail: str) -> None:
        self._link_pad.set_color(couleur)
        self._link_pad.set_icon(icone)
        self._link_state.setText(etat)
        self._link_detail.setText(detail)

    def _arrival_row(self, quand: float, rel: str) -> QWidget:
        """Une ligne « reçu du Deluge », qui ouvre le fichier sur sa page."""
        cle, nature = ARRIVAL_PAGES.get(rel.split("/", 1)[0].upper(),
                                        ("Samples", N_("fichier")))
        cible = "%s#%s" % (cle, rel)
        ligne = _LigneAnomalie(cible)
        disposition = QHBoxLayout(ligne)
        disposition.setContentsMargins(0, 2, 0, 2)
        disposition.setSpacing(8)
        pastille = QLabel("●")
        pastille.setStyleSheet("color: %s;" % page_color(cle))
        disposition.addWidget(pastille)
        disposition.addWidget(ElidedLabel(Path(rel).stem), 1)
        for texte, largeur in ((tr(nature), 70), (_quand(quand), 130)):
            etiquette = QLabel(texte)
            etiquette.setProperty("role", "subtitle")
            etiquette.setFixedWidth(largeur)
            disposition.addWidget(etiquette)
        fleche = QLabel("›")
        fleche.setStyleSheet("color: %s;" % GREY)
        disposition.addWidget(fleche)
        ligne.setToolTip(tr("%s\n\nCliquez pour l'ouvrir.") % rel)
        ligne.clicked.connect(
            self.guard(lambda _c=False, d=cible: self.navigateRequested.emit(d)))
        return ligne

    def _build_tiles(self) -> QWidget:
        """Les six tuiles chiffrées."""
        card = Card(tr("Contenu de la carte"), color=self.color)
        grid = QGridLayout()
        grid.setSpacing(8)

        # Chaque tuile qui mène à une page prend **la couleur de cette
        # page** : le cyan veut dire « échantillons » partout dans
        # l'application, dans la barre latérale comme ici. Les deux tuiles
        # qui ne mènent nulle part gardent une teinte neutre et n'affichent
        # pas de curseur de main : une tuile qui ne réagit pas ne doit pas
        # faire croire qu'elle est cliquable.
        definitions = (
            ("samples", tr("Échantillons"), "samples", page_color("Samples"),
             "Samples"),
            ("synths", tr("Presets de synthé"), "synth", page_color("Synths"),
             "Synths"),
            ("kits", tr("Kits"), "kit", page_color("Kits"), "Kits"),
            ("songs", tr("Morceaux"), "song", page_color("Songs"), "Songs"),
            ("audio", tr("Durée d'audio"), "wave", pad_color(5), ""),
            ("space", tr("Espace libre"), "backup", pad_color(7), ""),
        )
        self._tiles_grid = grid
        self._tile_order = [definition[0] for definition in definitions]
        for index, (key, label, icon, colour, target) in enumerate(definitions):
            tile = StatTile(label, "—", colour, icon)
            tile.set_clickable(bool(target))
            if target:
                tile.clicked.connect(
                    self.guard(lambda _c=False, t=target:
                               self.navigateRequested.emit(t)))
                tile.setToolTip(tr("Ouvrir la page « %s »") % label)
            grid.addWidget(tile, index // 3, index % 3)
            self._tiles[key] = tile
        card.body().addLayout(grid)
        return card

    def _build_card_info(self) -> QWidget:
        card = Card(tr("Carte"), color=self.color)
        body = card.body()

        self._card_path = ElidedLabel("—")
        self._card_path.setProperty("role", "mono")
        body.addWidget(self._card_path)

        self._space_bar = QProgressBar()
        self._space_bar.setTextVisible(False)
        self._space_bar.setFixedHeight(8)
        body.addWidget(self._space_bar)

        self._card_detail = QLabel("—")
        self._card_detail.setProperty("role", "subtitle")
        # Retour à la ligne : sans lui, la phrase sur la copie dans un
        # dossier imposait sa longueur entière (900 px) comme largeur
        # minimale, et tout le tableau de bord partait sous une barre de
        # défilement horizontale dès 980 px.
        self._card_detail.setWordWrap(True)
        body.addWidget(self._card_detail)

        row = QHBoxLayout()
        row.setSpacing(8)
        self._last_scan = QLabel("—")
        self._last_scan.setProperty("role", "subtitle")
        self._last_scan.setWordWrap(True)
        row.addWidget(self._last_scan, 1)

        self._scan_button = tool_button(
            tr("Analyser la carte"), "refresh",
            tr("Relit la carte et met l'index à jour  (Ctrl+R)"), primary=True)
        self._scan_button.clicked.connect(self.guard(self._start_scan))
        row.addWidget(self._scan_button)

        self._stop_button = tool_button(tr("Arrêter"), "stop",
                                        tr("Interrompre l'analyse en cours"))
        self._stop_button.clicked.connect(self.guard(self._stop_scan))
        self._stop_button.setVisible(False)
        row.addWidget(self._stop_button)

        body.addLayout(row)
        return card

    def _build_health(self) -> QWidget:
        card = Card(tr("État de santé"), color=page_color("Health"))
        body = card.body()

        row = QHBoxLayout()
        row.setSpacing(14)
        self._score = ScoreRing(size=84)
        row.addWidget(self._score)
        self._verdict = QLabel(tr("Analyse non lancée"))
        self._verdict.setProperty("role", "subtitle")
        self._verdict.setWordWrap(True)
        row.addWidget(self._verdict, 1)
        body.addLayout(row)

        self._issues = QVBoxLayout()
        self._issues.setSpacing(3)
        body.addLayout(self._issues)

        open_health = tool_button(tr("Voir le détail"), "health",
                                  tr("Ouvrir le diagnostic complet"),
                                  color=page_color("Health"))
        open_health.clicked.connect(
            self.guard(lambda: self.navigateRequested.emit("Health")))
        body.addWidget(open_health)
        return card

    def _build_actions(self) -> QWidget:
        """Six raccourcis, chacun à la couleur de sa destination.

        C'étaient six boutons gris identiques, dont deux doublaient la barre
        latérale (« Réglages ») et deux menaient au même écran sans dire où
        (« Nettoyer la carte »). Chacun porte maintenant la teinte de sa page
        et mène **à l'onglet exact** : trois clics économisés sur une
        sauvegarde, et le gris ne cache plus la hiérarchie.
        """
        card = Card(tr("Actions rapides"), color=self.color)
        grid = QGridLayout()
        grid.setSpacing(6)
        shortcuts = (
            (tr("Générer un preset"), "wand", "Generator#Preset de synthé",
             tr("Fabriquer un son de synthé par genre")),
            (tr("Construire un kit"), "kit", "Generator#Kit de batterie",
             tr("Assembler un kit de batterie à partir de la carte")),
            (tr("Chercher les doublons"), "copy", "Health#Doublons",
             tr("Trouver les échantillons présents plusieurs fois")),
            (tr("Échantillons manquants"), "warning", "Health#Manquants",
             tr("Les sons que des presets réclament sans les trouver")),
            (tr("Sauvegarder la carte"), "backup", "Health#Sauvegardes",
             tr("Copier la carte avant d'y toucher")),
            (tr("Boîte à outils"), "tools", "Toolbox",
             tr("Gammes, tempos, conversions et aide-mémoire")),
        )
        for index, (label, icon, target, aide) in enumerate(shortcuts):
            button = tool_button(label, icon, aide,
                                 color=page_color(target.split("#")[0]))
            button.setSizePolicy(QSizePolicy.Policy.Expanding,
                                 QSizePolicy.Policy.Fixed)
            button.setMinimumHeight(42)
            button.clicked.connect(
                self.guard(lambda _c=False, t=target:
                           self.navigateRequested.emit(t)))
            grid.addWidget(button, index // 2, index % 2)
        card.body().addLayout(grid)
        return card

    def _build_folders(self) -> QWidget:
        card = Card(tr("Répartition des échantillons"),
                    color=page_color("Samples"))
        self._folders = QVBoxLayout()
        self._folders.setSpacing(4)
        card.body().addLayout(self._folders)
        return card

    # -- analyse ------------------------------------------------------------ #

    def update_index(self) -> bool:
        """Relit les fichiers modifiés depuis la dernière analyse.

        Appelé au démarrage par la fenêtre : une analyse **incrémentale**,
        qui ne fait que lire la carte. Rend ``False`` s'il n'y a rien à faire
        — pas de carte, index vide (la première analyse reste un geste de
        l'utilisateur), ou analyse déjà en cours.
        """
        if self.sd is None or self._worker is not None:
            return False
        self._ensure_built()
        stats = self._stats()
        if not any(int(stats.get(cle, 0) or 0)
                   for cle in ("samples", "synths", "kits", "songs")):
            return False
        self._auto_scan = True
        self._start_scan(full=False)
        return self._worker is not None

    def _start_scan(self, full: bool = True) -> None:
        """Lance l'analyse de la carte dans un fil séparé."""
        card = self.card_or_warn()
        if card is None:
            return
        if self._worker is not None:
            self.say(tr("Une analyse est déjà en cours."))
            return

        settings = self.ctx.settings
        self._scan_button.setEnabled(False)
        self._stop_button.setVisible(True)
        self._progress.setVisible(True)
        self._progress.set_busy(True)
        self._progress_label.setVisible(True)
        self._progress_label.setText(tr("Inventaire de la carte…"))

        self._worker = self.run(
            scan_card, card, self.lib,
            compute_hash=bool(settings.scan_hash),
            analyze=bool(settings.scan_analyze),
            full=bool(full),
            on_result=self.guard(self._scan_done),
            on_progress=self._scan_progress,
            on_error=self.guard(self._scan_failed),
            title=tr("Analyse de la carte"))

    def _stop_scan(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.say(tr("Arrêt demandé…"))

    def _scan_progress(self, payload) -> None:
        """Affiche l'avancement sans jamais lever."""
        try:
            message = getattr(payload, "message", "") or ""
            current = getattr(payload, "current", 0) or 0
            total = getattr(payload, "total", 0) or 0
            self._progress.set_progress(int(current), int(total))
            self._progress_label.setText(
                f"{message} ({current}/{total})" if total else message)
        except Exception as exc:  # noqa: BLE001
            log.debug("affichage de l'avancement impossible : %s", exc)

    def _scan_end(self) -> None:
        self._worker = None
        self._scan_button.setEnabled(True)
        self._stop_button.setVisible(False)
        self._progress.setVisible(False)
        self._progress_label.setVisible(False)

    def _scan_done(self, result) -> None:
        automatique, self._auto_scan = self._auto_scan, False
        self._scan_end()
        if result is None:
            return
        if automatique:
            relus = (result.samples + result.presets + result.kits
                     + result.songs - result.skipped)
            self.say(tr("Index à jour : rien n'a changé sur la carte.")
                     if relus <= 0 else
                     tr("Index à jour : %d fichier(s) relu(s) depuis la "
                        "dernière analyse.") % relus)
        else:
            self.say(result.summary())
        if result.errors:
            log.warning("analyse terminée avec %d erreur(s)",
                        len(result.errors))
        # La fenêtre répond à ``scanFinished`` en rafraîchissant la page
        # visible — celle-ci, le plus souvent. Se rafraîchir aussi soi-même
        # coûtait un second diagnostic de santé après chaque analyse ; on ne
        # le fait que si personne n'écoute.
        if self.receivers(self.scanFinished) == 0:
            self._refresh()
        self.scanFinished.emit()

    def _scan_failed(self, message: str) -> None:
        self._auto_scan = False
        self._scan_end()
        self.say(tr("Analyse impossible : %s") % message)

    # -- rafraîchissement --------------------------------------------------- #

    def _refresh(self) -> None:
        stats = self._stats()
        self._fill_tiles(stats)
        self._fill_card_info(stats)
        rapport = self._fill_health(stats)
        self._dernier_etat = (stats, rapport)
        self._fill_next_step(stats, rapport)
        self.refresh_exchanges()
        self._fill_folders()

    def _stats(self) -> dict:
        try:
            return self.lib.stats()
        except Exception as exc:  # noqa: BLE001
            log.debug("statistiques indisponibles : %s", exc)
            return {}

    def _fill_tiles(self, stats: dict) -> None:
        self._tiles["samples"].set_value(integer(stats.get("samples", 0)))
        self._tiles["synths"].set_value(stats.get("synths", 0))
        self._tiles["kits"].set_value(stats.get("kits", 0))
        self._tiles["songs"].set_value(stats.get("songs", 0))
        self._tiles["audio"].set_value(
            human_duration(stats.get("sample_seconds", 0)))

        free, total = (0, 0)
        if self.sd is not None:
            try:
                free, total = self.sd.free_space()
            except Exception as exc:  # noqa: BLE001
                log.debug("espace disque indisponible : %s", exc)
        self._tiles["space"].set_value(human_size(free) if total else "—")
        # Sur une copie dans un dossier, ces chiffres sont ceux du disque de
        # l'ordinateur, pas ceux d'une carte.
        sur_carte = self.sd is None or self.sd.is_volume
        self._tiles["space"].set_label(
            tr("Espace libre") if sur_carte else tr("Libre sur le disque"))

    def _fill_card_info(self, stats: dict) -> None:
        if self.sd is None:
            self._card_path.setText(tr("Aucune carte"))
            return
        self._card_path.setText(str(self.sd.root))

        free, total = 0, 0
        try:
            free, total = self.sd.free_space()
        except Exception as exc:  # noqa: BLE001
            log.debug("espace disque indisponible : %s", exc)

        if total > 0:
            used = total - free
            self._space_bar.setRange(0, 100)
            self._space_bar.setValue(int(round(used / total * 100)))
            echantillons = human_size(stats.get('sample_bytes', 0))
            if self.sd.is_volume:
                self._card_detail.setText(
                    tr("%s utilisés sur %s — dont %s d'échantillons")
                    % (human_size(used), human_size(total), echantillons))
            else:
                self._card_detail.setText(
                    tr("Copie dans un dossier : %s d'échantillons. Le disque "
                       "qui la contient a %s libres sur %s — une carte SD, "
                       "elle, fait souvent 32 Gio.")
                    % (echantillons, human_size(free), human_size(total)))
        else:
            self._space_bar.setRange(0, 100)
            self._space_bar.setValue(0)
            self._card_detail.setText(tr("Espace disque indisponible."))

        last = stats.get("last_scan") or ""
        # Carte déjà analysée : le « Analyser » de l'en-tête suffit, et le
        # bouton de la page s'efface au lieu de crier.
        self._scan_button.setVisible(not last)
        if last:
            self._last_scan.setText(
                tr("Dernière analyse : %s") % human_datetime(last))
        else:
            self._last_scan.setText(
                tr("Carte jamais analysée — lancez l'analyse pour remplir "
                   "les pages."))

    def _fill_health(self, stats: dict | None = None):
        """Résume la santé : score et trois anomalies les plus graves.

        Rend le rapport, dont le bandeau « à faire maintenant » se sert :
        le calculer une seconde fois pour lui serait absurde.

        Le diagnostic reste dans le fil de l'interface : 0,21 s sur la carte
        de l'utilisateur. Il ne l'a pas toujours été — 0,96 s, lancé deux fois
        à chaque visite, soit deux secondes de fenêtre figée — avant que le
        repérage des fichiers parasites ne passe à ``os.scandir`` et que la
        fenêtre ne cesse de rafraîchir deux fois chaque page affichée.

        **Tant que la carte n'a pas été analysée, aucun score n'est affiché.**
        Sur un index vide, les contrôles ne trouvent rien à signaler et la
        note monte à 98/100 : annoncer « carte en très bon état » alors que
        rien n'a été vérifié serait un mensonge.
        """
        clear_layout(self._issues)

        if self.sd is None:
            return None

        counted = sum(int((stats or {}).get(key, 0) or 0)
                      for key in ("samples", "synths", "kits", "songs"))
        if counted == 0:
            self._score.setText("—")
            self._score.set_color(GREY)
            self._verdict.setText(
                tr("Carte pas encore analysée : l'état de santé sera calculé "
                   "après la première analyse."))
            return None
        try:
            from ...core import health as health_mod

            report = health_mod.check_card(
                self.sd, self.lib,
                backup_dir=self.ctx.settings.backup_path())
        except Exception as exc:  # noqa: BLE001
            log.debug("diagnostic impossible : %s", exc)
            self._score.setText("—")
            self._verdict.setText(tr("Diagnostic indisponible."))
            return None

        self._score.setText(f"{report.score}")
        self._score.set_color(self._score_colour(report.score))
        self._verdict.setText(report.verdict())

        worst = sorted(report.issues,
                       key=lambda i: ({"error": 0, "warn": 1, "info": 2}
                                      .get(i.severity, 3), -i.count))
        for issue in worst[:3]:
            cible = ISSUE_DESTINATION.get(issue.code, "Health#Rapport")
            row = _LigneAnomalie(cible)
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 2, 0, 2)
            layout.setSpacing(6)

            dot = QLabel("●")
            dot.setStyleSheet(f"color: {severity_color(issue.severity)};")
            layout.addWidget(dot)

            text = ElidedLabel(f"{issue.title} ({issue.count})")
            layout.addWidget(text, 1)

            fleche = QLabel("›")
            fleche.setStyleSheet(f"color: {GREY};")
            layout.addWidget(fleche)

            row.setToolTip(tr("%s\n\nCliquez pour ouvrir « %s ».")
                           % (issue.detail, _lieu(cible)))
            row.clicked.connect(
                self.guard(lambda _c=False, d=cible:
                           self.navigateRequested.emit(d)))
            self._issues.addWidget(row)

        if not worst:
            ok = QLabel(tr("Aucune anomalie détectée."))
            ok.setStyleSheet(f"color: {PAD_GREEN};")
            self._issues.addWidget(ok)
        return report

    @staticmethod
    def _score_colour(score: int) -> str:
        if score >= 90:
            return PAD_GREEN
        if score >= 70:
            return GOLD
        if score >= 40:
            return "#FF8C1A"
        return PAD_MAGENTA

    def _fill_folders(self) -> None:
        """Barres colorées montrant où se trouvent les échantillons."""
        clear_layout(self._folders)

        try:
            folders = self.lib.folders("sample")
        except Exception as exc:  # noqa: BLE001
            log.debug("répartition indisponible : %s", exc)
            folders = []
        if not folders:
            empty = QLabel(tr("Lancez une analyse pour voir la répartition."))
            empty.setProperty("role", "subtitle")
            self._folders.addWidget(empty)
            return

        # On regroupe par dossier de deuxième niveau : « SAMPLES/DRUMS »
        # plutôt que chacun de ses vingt sous-dossiers.
        grouped: dict[str, int] = {}
        for name, count in folders:
            parts = [p for p in str(name).split("/") if p]
            key = "/".join(parts[:2]) if len(parts) > 1 else (parts[0]
                                                              if parts else "—")
            grouped[key] = grouped.get(key, 0) + int(count)

        ranked = sorted(grouped.items(), key=lambda kv: -kv[1])[:TOP_FOLDERS]
        biggest = max((count for _n, count in ranked), default=1)

        for index, (name, count) in enumerate(ranked):
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(8)

            label = ElidedLabel(name)
            label.setFixedWidth(220)
            # Politique fixe : celle d'un libellé élidé est « ignorée », et
            # la disposition lui donnait alors zéro pixel malgré sa largeur
            # fixe — la barre voisine se dessinait par-dessus le nom du
            # dossier. Le défaut datait d'avant la refonte ; il ne se voyait
            # qu'en faisant défiler le tableau de bord.
            label.setSizePolicy(QSizePolicy.Policy.Fixed,
                                QSizePolicy.Policy.Preferred)
            label.setToolTip(name)
            layout.addWidget(label)

            # Une rangée de pads plutôt qu'une barre : la répartition se lit
            # comme un niveau sur la machine.
            bar = SegmentMeter(segments=32, color=pad_color(index))
            bar.set_value(int(count), int(biggest))
            layout.addWidget(bar, 1)

            value = QLabel(str(count))
            value.setFixedWidth(60)
            value.setAlignment(Qt.AlignmentFlag.AlignRight
                               | Qt.AlignmentFlag.AlignVCenter)
            value.setProperty("role", "subtitle")
            layout.addWidget(value)

            self._folders.addWidget(row)
