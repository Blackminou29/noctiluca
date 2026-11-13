# -*- coding: utf-8 -*-
"""Page « Hub MIDI » : l'ordinateur au centre, entre le Deluge, les claviers
et le DAW.

Le Deluge n'a qu'une prise USB : relié à l'ordinateur, il ne peut plus
recevoir un clavier. La page fait de l'ordinateur la baie de brassage —
chaque clavier, chaque surface de contrôle, le Deluge et les ports du DAW y
sont une rangée ou une colonne, et un pad allumé au croisement dit « ce qui
arrive d'ici part là » (:mod:`delugeapp.core.midihub`).

* **la grille** : un clic sur un pad éteint branche, un clic sur un pad
  allumé le choisit ;
* **le branchement choisi** : où il arrive sur le Deluge (l'instrument qu'on
  regarde, ou une piste), l'octave, ce qu'il laisse passer, et les boutons
  d'une surface posés sur les réglages du Deluge ;
* **ce qui passe** : le moniteur, et le retard mesuré.

Le hub tourne tant que l'application est ouverte, quelle que soit la page
affichée : c'est la fenêtre qui le fait vivre, la page ne fait que le
montrer et le régler. Rien n'est écrit sur la carte.
"""

from __future__ import annotations

import logging
import time

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QMenu,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core import midifollow, midihub, midiport
from ...core.midihub import DELUGE
from ...i18n import N_, plural, tr
from .. import icons
from ..theme import PAD, text_on
from ..widgets.common import Card, RangeeAdaptative, RangeeSouple
from ..widgets.hubviews import PatchCell, PatchMatrix
from .base import Page, avance, tool_button

log = logging.getLogger(__name__)

#: Battement de la page, en millisecondes : éclats, moniteur, états.
BEAT_MS = 100
#: Lignes gardées dans le moniteur.
MONITOR_LINES = 200


def _phrase(texte: str) -> str:
    """``texte`` en phrase : sa majuscule et son point, sans toucher au
    reste — « le Deluge » garde la sienne."""
    texte = str(texte or "").strip()
    if not texte:
        return ""
    return texte[:1].upper() + texte[1:] + ("" if texte[-1] in ".!?" else ".")


class HubPage(Page):
    """Le hub MIDI : qui joue quoi, et comment."""

    TITLE = N_("Hub MIDI")
    ICON = "hub"
    NEEDS_CARD = False
    #: La lettre de son raccourci, ``Ctrl+M`` : les chiffres vont aux pages
    #: qui les avaient déjà.
    SHORTCUT = "M"

    navigateRequested = pyqtSignal(str)

    def __init__(self, ctx, parent=None) -> None:
        super().__init__(ctx, parent)
        #: Le branchement choisi (identifiant), ou ``""``.
        self._uid = ""
        #: Ce que la page montrait au dernier battement : rien ne se
        #: redessine tant que rien n'a changé.
        self._signature = None
        self._counts: dict = {}
        self._seq = 0
        #: Rang du dernier contrôleur vu quand l'apprentissage a commencé.
        self._learn_rank: int | None = None
        self._filling = False
        self._timer = QTimer(self)
        self._timer.setInterval(BEAT_MS)
        # La méthode elle-même, pas ``guard`` : PyQt débranche une méthode
        # liée quand la page est détruite, pas une fermeture — par
        # ``guard``, la minuterie tirait sur une page en cours de
        # destruction, et la suite de tests tombait net (12 novembre 2026,
        # comme pour le brouillon de l'atelier le 7). ``_tick`` a son
        # propre rempart.
        self._timer.timeout.connect(self._tick)

    # -- construction ------------------------------------------------------- #

    def build(self) -> None:
        outer = QVBoxLayout(self.content())
        outer.setContentsMargins(PAD, PAD, PAD, PAD)
        outer.setSpacing(8)
        header, actions = self.header(
            tr("Hub MIDI"), tr("L'ordinateur au centre : vos claviers, le "
                               "Deluge et le DAW, reliés d'ici"))
        outer.addWidget(header)
        # Un pad de la machine : sa couleur en veilleuse à l'arrêt, pleine
        # en marche — sur le treillis de l'en-tête, un simple liseré ne se
        # lisait pas.
        self._power_button = tool_button(tr("Hub en marche"), "hub",
                                         color=self.color)
        self._power_button.setCheckable(True)
        self._power_button.clicked.connect(self.guard(self._toggle_power))
        actions.addWidget(self._power_button)
        self._panic_button = tool_button(tr("Tout éteindre"), "stop")
        self._panic_button.clicked.connect(self.guard(self._panic))
        actions.addWidget(self._panic_button)

        corps = QWidget()
        colonne = QVBoxLayout(corps)
        colonne.setContentsMargins(0, 0, 0, 0)
        colonne.setSpacing(8)
        colonne.addWidget(self._build_patch())
        bas = QHBoxLayout()
        bas.setSpacing(8)
        bas.addWidget(self._build_route(), 3)
        bas.addWidget(self._build_monitor(), 2)
        colonne.addLayout(bas)
        # Fenêtre étroite : la fiche et le moniteur passent l'un sous
        # l'autre au lieu de se disputer 700 pixels.
        self._bottom_row = RangeeAdaptative(corps, bas, seuil=900)
        colonne.addWidget(self._build_daw())
        colonne.addStretch(1)

        zone = QScrollArea()
        zone.setWidgetResizable(True)
        zone.setFrameShape(QFrame.Shape.NoFrame)
        zone.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        zone.setWidget(corps)
        self._scroll = zone
        outer.addWidget(zone, 1)

    def _build_patch(self) -> QWidget:
        carte = Card(tr("Qui joue quoi"))
        self._hint = QLabel()
        self._hint.setWordWrap(True)
        self._hint.setProperty("role", "subtitle")
        carte.body().addWidget(self._hint)

        # Ce que la page propose de faire tout de suite.
        self._offer = QWidget()
        offre = QHBoxLayout(self._offer)
        offre.setContentsMargins(0, 0, 0, 0)
        self._offer_label = QLabel()
        self._offer_label.setWordWrap(True)
        offre.addWidget(self._offer_label, 1)
        self._suggest_button = tool_button(tr("Brancher sur le Deluge"),
                                           "midi", primary=True)
        self._suggest_button.clicked.connect(self.guard(self._suggest))
        offre.addWidget(self._suggest_button)
        self._connect_button = tool_button(tr("Connecter le Deluge"), "link")
        self._connect_button.clicked.connect(self.guard(self._connect_deluge))
        offre.addWidget(self._connect_button)
        carte.body().addWidget(self._offer)

        self._matrix = PatchMatrix()
        self._matrix.cellClicked.connect(self.guard(self._cell_clicked))
        self._matrix.cellMenuRequested.connect(self.guard(self._cell_menu))
        defilante = QScrollArea()
        defilante.setWidgetResizable(False)
        defilante.setFrameShape(QFrame.Shape.NoFrame)
        defilante.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        defilante.setWidget(self._matrix)
        self._matrix_area = defilante
        carte.body().addWidget(defilante)
        self._state_label = QLabel()
        self._state_label.setProperty("role", "subtitle")
        carte.body().addWidget(self._state_label)
        return carte

    def _build_route(self) -> QWidget:
        carte = Card(tr("Le branchement choisi"))
        self._route_card = carte
        self._route_title = QLabel(tr("Aucun branchement choisi"))
        self._route_title.setStyleSheet("font-weight: 700;")
        carte.body().addWidget(self._route_title)
        self._route_text = QLabel(tr(
            "Cliquez un pad de la grille : éteint, il branche la source sur "
            "la destination ; allumé, il se règle ici."))
        self._route_text.setWordWrap(True)
        self._route_text.setProperty("role", "subtitle")
        self._route_text.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        carte.body().addWidget(self._route_text)

        self._form = QWidget()
        forme = QVBoxLayout(self._form)
        forme.setContentsMargins(0, 4, 0, 0)
        forme.setSpacing(6)

        self._enabled_box = QCheckBox(tr("En service"))
        self._enabled_box.clicked.connect(self.guard(self._set_enabled))
        forme.addWidget(self._enabled_box)

        rang = QHBoxLayout()
        rang.addWidget(QLabel(tr("Arrive sur :")))
        self._target_box = QComboBox()
        self._target_box.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._target_box.setMinimumContentsLength(24)
        self._target_box.activated.connect(self.guard(self._set_target))
        rang.addWidget(self._target_box, 1)
        forme.addLayout(rang)

        # Des rangées souples : à 980 px, cinq cases sur une ligne poussaient
        # toute la page hors de la fenêtre.
        rang = RangeeSouple()
        self._octave_down_button = tool_button(tr("Octave −"), "minus")
        self._octave_down_button.clicked.connect(
            self.guard(lambda: self._shift(-12)))
        rang.addWidget(self._octave_down_button)
        self._octave_up_button = tool_button(tr("Octave +"), "plus")
        self._octave_up_button.clicked.connect(
            self.guard(lambda: self._shift(12)))
        rang.addWidget(self._octave_up_button)
        self._transpose_spin = avance(QSpinBox())
        self._transpose_spin.setRange(-60, 60)
        self._transpose_spin.setSuffix(tr(" demi-tons"))
        self._transpose_spin.valueChanged.connect(
            self.guard(self._set_transpose))
        rang.addWidget(self._transpose_spin)
        self._transpose_label = QLabel()
        rang.addWidget(self._transpose_label)
        forme.addLayout(rang)

        # Mode avancé : ce que le branchement écoute et laisse passer.
        fin = avance(QWidget())
        self._fine = fin
        fine = QVBoxLayout(fin)
        fine.setContentsMargins(0, 0, 0, 0)
        fine.setSpacing(6)
        rang = RangeeSouple()
        rang.addWidget(QLabel(tr("Écoute :")))
        self._channel_in_box = QComboBox()
        self._channel_in_box.addItem(tr("tous les canaux de la source"), 0)
        for canal in range(1, 17):
            self._channel_in_box.addItem(tr("son canal %d seulement") % canal,
                                         canal)
        self._channel_in_box.activated.connect(
            self.guard(self._set_channel_in))
        rang.addWidget(self._channel_in_box)
        rang.addWidget(QLabel(tr("Touches :")))
        self._low_spin = QSpinBox()
        self._high_spin = QSpinBox()
        for compteur in (self._low_spin, self._high_spin):
            compteur.setRange(0, 127)
            compteur.valueChanged.connect(self.guard(self._set_range))
        rang.addWidget(self._low_spin)
        rang.addWidget(QLabel("–"))
        rang.addWidget(self._high_spin)
        self._range_label = QLabel()
        self._range_label.setProperty("role", "subtitle")
        rang.addWidget(self._range_label)
        fine.addLayout(rang)

        rang = RangeeSouple()
        rang.addWidget(QLabel(tr("Laisse passer :")))
        self._passes: dict[str, QCheckBox] = {}
        for nom, libelle in (("notes", N_("Notes")),
                             ("bend", N_("Molette et pression")),
                             ("controllers", N_("Contrôleurs")),
                             ("programs", N_("Programmes")),
                             ("clock", N_("Horloge et transport"))):
            case = QCheckBox(tr(libelle))
            case.clicked.connect(self.guard(
                lambda _c=False, n=nom: self._set_pass(n)))
            rang.addWidget(case)
            self._passes[nom] = case
        self._pass_notes = self._passes["notes"]
        self._pass_bend = self._passes["bend"]
        self._pass_controllers = self._passes["controllers"]
        self._pass_programs = self._passes["programs"]
        self._pass_clock = self._passes["clock"]
        fine.addLayout(rang)

        titre = QLabel(tr("Les boutons de la surface de contrôle"))
        titre.setStyleSheet("font-weight: 700;")
        fine.addWidget(titre)
        self._cc_table = QTableWidget(0, 2)
        self._cc_table.setHorizontalHeaderLabels(
            [tr("Bouton tourné"), tr("Ce qu'il règle")])
        entete = self._cc_table.horizontalHeader()
        entete.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        entete.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._cc_table.verticalHeader().setVisible(False)
        self._cc_table.verticalHeader().setDefaultSectionSize(32)
        self._cc_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self._cc_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._cc_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self._cc_table.setMinimumHeight(4 * 32 + 30)
        fine.addWidget(self._cc_table)
        rang = QHBoxLayout()
        self._learn_button = tool_button(tr("Apprendre un bouton"), "plus")
        self._learn_button.setCheckable(True)
        self._learn_button.clicked.connect(self.guard(self._toggle_learn))
        rang.addWidget(self._learn_button)
        self._forget_button = tool_button(tr("Oublier ce bouton"), "trash")
        self._forget_button.clicked.connect(self.guard(self._forget))
        rang.addWidget(self._forget_button)
        rang.addStretch(1)
        fine.addLayout(rang)
        forme.addWidget(fin)

        rang = QHBoxLayout()
        self._rearm_button = tool_button(tr("Rétablir la source"), "refresh")
        self._rearm_button.clicked.connect(self.guard(self._rearm))
        rang.addWidget(self._rearm_button)
        rang.addStretch(1)
        self._remove_button = tool_button(tr("Retirer le branchement"),
                                          "trash")
        self._remove_button.clicked.connect(self.guard(self._remove))
        rang.addWidget(self._remove_button)
        forme.addLayout(rang)
        carte.body().addWidget(self._form)
        carte.body().addStretch(1)
        return carte

    def _build_monitor(self) -> QWidget:
        carte = avance(Card(tr("Ce qui passe")))
        self._monitor_card = carte
        self._monitor_list = QListWidget()
        self._monitor_list.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection)
        # Une ligne trop longue passe à la suivante plutôt que de se couper.
        self._monitor_list.setWordWrap(True)
        self._monitor_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._monitor_list.setMinimumHeight(140)
        carte.body().addWidget(self._monitor_list, 1)
        self._stats_label = QLabel()
        self._stats_label.setWordWrap(True)
        self._stats_label.setProperty("role", "subtitle")
        carte.body().addWidget(self._stats_label)
        rang = QHBoxLayout()
        rang.addStretch(1)
        self._clear_button = tool_button(tr("Vider le moniteur"), "trash")
        self._clear_button.clicked.connect(self.guard(self._clear_monitor))
        rang.addWidget(self._clear_button)
        carte.body().addLayout(rang)
        return carte

    def _build_daw(self) -> QWidget:
        carte = Card(tr("Et le DAW ?"))
        self._daw_label = QLabel()
        self._daw_label.setWordWrap(True)
        self._daw_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        carte.body().addWidget(self._daw_label)
        return carte

    # -- le hub ------------------------------------------------------------- #

    def _hub(self):
        return self.ctx.ensure_hub()

    def _changed(self) -> None:
        """Un branchement a changé : l'enregistrer, et tout remontrer."""
        self.ctx.save_hub()
        self._show()

    def showEvent(self, event) -> None:  # noqa: N802 - API Qt
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802 - API Qt
        self._timer.stop()
        self._stop_learning()
        super().hideEvent(event)

    def _level_changed(self, advanced: bool) -> None:
        self._show_route()

    # -- affichage ---------------------------------------------------------- #

    def _refresh(self) -> None:
        hub = self._hub()
        self.ctx.refresh_hub_follow()
        hub.rescan()
        self._show()

    def _etat(self, hub):
        """Tout ce que la page montre, pour savoir s'il faut redessiner."""
        return (hub.enabled,
                tuple((b.name, b.present, b.open, b.tripped)
                      for b in hub.sources()),
                tuple((b.name, b.present, b.open)
                      for b in hub.destinations()),
                tuple((r.uid, hub.state(r.uid), hub.channel_for(r),
                       tuple(sorted(r.to_dict().items(), key=str)))
                      for r in hub.routes),
                hub.deluge_detected())

    def _show(self) -> None:
        hub = self._hub()
        self._signature = self._etat(hub)
        sources, dests = hub.sources(), hub.destinations()
        routes = hub.routes
        if self._uid and not any(r.uid == self._uid for r in routes):
            self._uid = ""

        cellules = {}
        for route in routes:
            code = hub.state(route.uid)
            etat = code if code in ("active", "off", "tripped") else "waiting"
            cellules[(route.source, route.dest)] = PatchCell(
                etat, self._tag(route), self._tip(hub, route, code))
        self._matrix.set_accent(self.color)
        self._matrix.set_ports(sources, dests)
        self._matrix.set_cells(cellules)
        self._matrix.setFixedSize(self._matrix.sizeHint())
        self._matrix_area.setFixedHeight(
            self._matrix.sizeHint().height()
            + self._matrix_area.horizontalScrollBar().sizeHint().height())
        self._matrix_area.setVisible(bool(sources) and bool(dests))
        choisi = hub.route(self._uid) if self._uid else None
        self._matrix.set_selected(*((choisi.source, choisi.dest)
                                    if choisi else ("", "")))

        self._power_button.blockSignals(True)
        self._power_button.setChecked(hub.enabled)
        self._power_button.blockSignals(False)
        # Allumé, le pad est plein : son icône prend l'encre qui s'y lit.
        self._power_button.setIcon(icons.icon(
            "hub", text_on(self.color) if hub.enabled else self.color, 16))
        self._hint.setText(self._hint_text(hub, sources, dests))
        self._state_label.setText(hub.summary())
        self._show_offer(hub, sources, dests)
        self._show_route()
        self._daw_label.setText(self._daw_text(sources, dests))

    def _hint_text(self, hub, sources, dests) -> str:
        if not midiport.available():
            return tr("Sur cet ordinateur, l'application ne sait pas parler "
                      "MIDI : le hub attend Windows.")
        if not any(b.present for b in sources):
            return tr(
                "Branchez un clavier ou une surface de contrôle en USB : il "
                "paraîtra ici, en rangée. Le Deluge et les autres sorties "
                "sont les colonnes. Un pad allumé à leur croisement, et ce "
                "que vous jouez part vers la machine.")
        if not hub.enabled:
            return tr("Le hub est à l'arrêt : ses ports sont rendus aux "
                      "autres logiciels. [Hub en marche] le relance.")
        return tr("Un pad éteint : cliquez pour brancher la rangée sur la "
                  "colonne. Un pad allumé : cliquez pour le régler "
                  "dessous ; un clic droit le coupe ou le retire.")

    def _candidate(self, hub, sources, dests) -> str:
        """Le premier clavier présent qui n'est relié à rien, si le Deluge
        est là pour le recevoir."""
        if not any(b.name == DELUGE and b.present for b in dests):
            return ""
        relies = {r.source for r in hub.routes}
        for bout in sources:
            if (bout.present and bout.role == "device"
                    and bout.name not in relies):
                return bout.name
        return ""

    def _show_offer(self, hub, sources, dests) -> None:
        candidat = self._candidate(hub, sources, dests)
        deluge_la = any(b.name == DELUGE and b.present for b in dests)
        a_connecter = (not deluge_la and hub.deluge_detected())
        self._suggest_button.setVisible(bool(candidat))
        self._connect_button.setVisible(a_connecter)
        if candidat:
            self._offer_label.setText(tr(
                "« %s » n'est relié à rien. Branché sur le Deluge, il joue "
                "l'instrument que vous y regardez.")
                % midihub.endpoint_label(candidat))
        elif a_connecter:
            self._offer_label.setText(tr(
                "Le Deluge est au bout du câble, mais pas connecté : le hub "
                "ne le voit pas encore."))
        self._offer.setVisible(bool(candidat) or a_connecter)

    @staticmethod
    def _tag(route) -> str:
        """Ce que le pad d'un branchement affiche : sa cible, en deux
        signes."""
        if route.follow in ("a", "b", "c"):
            return route.follow.upper()
        if route.follow.startswith("track_"):
            return tr("P%s") % route.follow[6:]
        return str(route.channel_out) if route.channel_out else "="

    def _tip(self, hub, route, code: str) -> str:
        lignes = [midihub.describe_route(route, hub.channel_for(route)),
                  _phrase(hub.state_text(code))]
        conseil = hub.advice(route)
        if conseil:
            lignes.append(conseil)
        return "\n".join(lignes)

    # -- le branchement choisi ---------------------------------------------- #

    def _route(self):
        return self._hub().route(self._uid) if self._uid else None

    def _show_route(self) -> None:
        if not self._built:
            return
        hub = self._hub()
        route = self._route()
        self._form.setVisible(route is not None)
        if route is None:
            self._route_title.setText(tr("Aucun branchement choisi"))
            self._route_text.setText(tr(
                "Cliquez un pad de la grille : éteint, il branche la source "
                "sur la destination ; allumé, il se règle ici."))
            self._stop_learning()
            return
        code = hub.state(route.uid)
        self._route_title.setText("« %s »  →  « %s »" % (
            midihub.endpoint_label(route.source),
            midihub.endpoint_label(route.dest)))
        phrases = [_phrase(hub.state_text(code))]
        erreur = (hub.port_error(route.source) or hub.port_error(route.dest))
        if erreur and code in ("no_source", "no_dest"):
            phrases.append(_phrase(erreur))
        conseil = hub.advice(route)
        if conseil:
            phrases.append(conseil)
        if route.dest == DELUGE and route.follow in ("a", "b", "c"):
            phrases.append(tr(
                "Le Deluge joue l'instrument du clip où vous êtes ; un kit "
                "répond à partir de la note %d.") % self._kit_root())
        self._route_text.setText(" ".join(phrases))

        self._filling = True
        try:
            self._enabled_box.setChecked(route.enabled)
            self._fill_targets(hub, route)
            self._transpose_spin.setValue(route.transpose)
            self._transpose_label.setText(self._transpose_text(route))
            self._channel_in_box.setCurrentIndex(
                max(0, self._channel_in_box.findData(route.channel_in)))
            self._low_spin.setValue(route.low)
            self._high_spin.setValue(route.high)
            self._range_label.setText(self._range_text(route))
            for nom, case in self._passes.items():
                case.setChecked(bool(getattr(route, nom)))
            self._fill_cc(route)
        finally:
            self._filling = False
        self._rearm_button.setVisible(code == "tripped")
        self._forget_button.setEnabled(self._cc_table.rowCount() > 0)

    def _kit_root(self) -> int:
        note = getattr(self._hub().follow, "kit_root_note", None)
        return int(note) if note is not None else 36

    @staticmethod
    def _transpose_text(route) -> str:
        if not route.transpose:
            return tr("à la hauteur jouée")
        octaves, reste = divmod(abs(route.transpose), 12)
        signe = "+" if route.transpose > 0 else "−"
        if reste == 0:
            return signe + (plural(octaves, N_("%d octave"), N_("%d octaves"))
                            % octaves)
        return tr("%s%d demi-tons") % (signe, abs(route.transpose))

    @staticmethod
    def _range_text(route) -> str:
        from ...core.theory import note_to_name

        if route.low <= 0 and route.high >= 127:
            return tr("tout le clavier")
        return tr("de %s à %s") % (note_to_name(route.low),
                                   note_to_name(route.high))

    def _targets(self, hub, route) -> list[tuple[str, str]]:
        """Les arrivées proposées : les cibles MIDI Follow du Deluge
        d'abord — celles qu'il a réglées, toutes en mode avancé —, puis les
        canaux. La donnée est une chaîne, ``follow:a`` ou ``channel:10`` :
        Qt ne sait pas comparer un tuple Python, et ``findData`` ne le
        retrouvait pas."""
        choix: list[tuple[str, str]] = []
        if route.dest == DELUGE:
            reglages = hub.follow
            for cible in midihub.FOLLOW_TARGETS:
                connu = reglages.channel_of(cible) if reglages else None
                if not (cible == "a" or connu is not None
                        or route.follow == cible
                        or (self.advanced() and cible.startswith("track_"))):
                    continue
                canal = hub.channel_for(midihub.Route(
                    route.source, route.dest, follow=cible))
                libelle = midihub.target_label(cible, canal)
                choix.append((libelle[:1].upper() + libelle[1:],
                              "follow:" + cible))
        choix.append((tr("Le canal d'origine"), "channel:0"))
        for canal in range(1, 17):
            choix.append((tr("Canal %d") % canal, "channel:%d" % canal))
        return choix

    def _fill_targets(self, hub, route) -> None:
        self._target_box.clear()
        voulu = ("follow:" + route.follow if route.follow
                 else "channel:%d" % route.channel_out)
        for libelle, donnee in self._targets(hub, route):
            self._target_box.addItem(libelle, donnee)
            if donnee == voulu:
                self._target_box.setCurrentIndex(self._target_box.count() - 1)

    def _follow_params(self) -> list[tuple[str, int]]:
        """Les réglages du Deluge qu'un contrôleur pilote en MIDI Follow :
        (libellé, numéro), dans l'ordre des libellés."""
        lien = getattr(self.ctx, "link", None)
        table = dict(getattr(lien, "follow_map", None) or {})
        if not table:
            try:
                table = midifollow.load_map(self.ctx.sd)
            except Exception:  # noqa: BLE001 - un fichier de la carte
                log.debug("table MIDI Follow illisible", exc_info=True)
                table = {}
        return sorted(((midifollow.label_of(cle), int(cc))
                       for cle, cc in table.items()),
                      key=lambda couple: couple[0].casefold())

    def _fill_cc(self, route) -> None:
        """La table des boutons : un contrôleur reçu par ligne, et ce qu'il
        devient — un réglage du Deluge, ou un autre numéro."""
        table = self._cc_table
        table.setRowCount(0)
        params = self._follow_params() if route.dest == DELUGE else []
        for recu, envoye in sorted(route.cc_map.items()):
            ligne = table.rowCount()
            table.insertRow(ligne)
            item = QTableWidgetItem(tr("Contrôleur %d") % recu)
            item.setData(Qt.ItemDataRole.UserRole, int(recu))
            table.setItem(ligne, 0, item)
            choix = QComboBox()
            choix.setToolTip(tr(
                "Ce que ce bouton règle à l'arrivée : un réglage du son du "
                "Deluge, ou un numéro de contrôleur"))
            connus = set()
            for libelle, numero in params:
                choix.addItem(tr("%s  (contrôleur %d)") % (libelle, numero),
                              numero)
                connus.add(numero)
            for numero in range(128):
                if numero not in connus:
                    choix.addItem(tr("Contrôleur %d") % numero, numero)
            choix.setCurrentIndex(max(0, choix.findData(int(envoye))))
            choix.activated.connect(self.guard(
                lambda _i=0, r=int(recu), c=choix: self._set_cc(r, c)))
            table.setCellWidget(ligne, 1, choix)

    # -- gestes sur la grille ----------------------------------------------- #

    def select(self, uid: str) -> None:
        """Choisit un branchement : la grille l'entoure, la fiche le montre."""
        self._stop_learning()
        self._uid = str(uid or "")
        self._show()

    def _cell_clicked(self, source: str, dest: str) -> None:
        hub = self._hub()
        route = hub.find(source, dest)
        if route is None:
            try:
                route = hub.connect(source, dest)
            except ValueError as exc:
                self.say(str(exc))
                return
            self.ctx.save_hub()
            self.say(tr("Branché : %s.") % midihub.describe_route(
                route, hub.channel_for(route)))
        self.select(route.uid)

    def cell_menu(self, source: str, dest: str) -> QMenu | None:
        """Le menu d'un croisement branché : couper ou remettre, retirer."""
        route = self._hub().find(source, dest)
        if route is None:
            return None
        menu = QMenu(self)
        bascule = menu.addAction(tr("Couper") if route.enabled
                                 else tr("Remettre en service"))
        bascule.triggered.connect(self.guard(
            lambda _c=False, u=route.uid, e=not route.enabled:
            self._enable(u, e)))
        retirer = menu.addAction(tr("Retirer le branchement"))
        retirer.triggered.connect(self.guard(
            lambda _c=False, u=route.uid: self._remove_uid(u)))
        return menu

    def _cell_menu(self, source: str, dest: str, point) -> None:
        menu = self.cell_menu(source, dest)
        if menu is not None:
            menu.exec(point)

    def _suggest(self) -> None:
        hub = self._hub()
        candidat = self._candidate(hub, hub.sources(), hub.destinations())
        if candidat:
            self._cell_clicked(candidat, DELUGE)

    def _connect_deluge(self) -> None:
        lien = self.ctx.ensure_link()
        if not lien.is_connected:
            reglages = self.ctx.settings
            lien.connect(reglages.midi_out, reglages.midi_in,
                         card=self.ctx.sd)
        self.say(lien.state().summary())
        self._refresh()

    # -- gestes sur le hub -------------------------------------------------- #

    def _toggle_power(self) -> None:
        hub = self._hub()
        hub.set_enabled(self._power_button.isChecked())
        self._changed()
        self.say(hub.summary())

    def _panic(self) -> None:
        notes = self._hub().panic()
        self.say(tr("Tout est éteint : %s, et le silence demandé à chaque "
                    "sortie.") % (plural(notes, N_("%d note relâchée"),
                                         N_("%d notes relâchées")) % notes))

    def _rearm(self) -> None:
        route = self._route()
        if route is not None:
            self._hub().rearm(route.source)
            self._show()

    # -- gestes sur le branchement ------------------------------------------ #

    def _update(self, **changes) -> None:
        if self._filling or not self._uid:
            return
        self._hub().update(self._uid, **changes)
        self._changed()

    def _enable(self, uid: str, enabled: bool) -> None:
        self._hub().update(uid, enabled=bool(enabled))
        self._changed()

    def _set_enabled(self) -> None:
        self._update(enabled=self._enabled_box.isChecked())

    def _set_target(self) -> None:
        sorte, _, valeur = str(self._target_box.currentData() or "") \
            .partition(":")
        if sorte == "follow":
            self._update(follow=valeur)
        elif sorte == "channel" and valeur.isdigit():
            self._update(follow="", channel_out=int(valeur))

    def _shift(self, demi_tons: int) -> None:
        route = self._route()
        if route is not None:
            self._update(transpose=max(-60, min(60, route.transpose
                                                + int(demi_tons))))

    def _set_transpose(self) -> None:
        self._update(transpose=self._transpose_spin.value())

    def _set_channel_in(self) -> None:
        self._update(channel_in=int(self._channel_in_box.currentData() or 0))

    def _set_range(self) -> None:
        self._update(low=self._low_spin.value(), high=self._high_spin.value())

    def _set_pass(self, nom: str) -> None:
        self._update(**{nom: self._passes[nom].isChecked()})

    def _remove_uid(self, uid: str) -> None:
        if self._hub().remove(uid):
            if uid == self._uid:
                self._uid = ""
            self._changed()
            self.say(tr("Branchement retiré ; ce qu'il tenait est relâché."))

    def _remove(self) -> None:
        if self._uid:
            self._remove_uid(self._uid)

    # -- les boutons d'une surface ------------------------------------------ #

    def _set_cc(self, recu: int, choix: QComboBox) -> None:
        route = self._route()
        if route is None or self._filling:
            return
        table = dict(route.cc_map)
        table[int(recu)] = int(choix.currentData())
        self._update(cc_map=table)

    def _forget(self) -> None:
        route = self._route()
        ligne = self._cc_table.currentRow()
        if route is None or ligne < 0:
            return
        recu = self._cc_table.item(ligne, 0).data(Qt.ItemDataRole.UserRole)
        table = {k: v for k, v in route.cc_map.items() if k != recu}
        self._update(cc_map=table)

    def _toggle_learn(self) -> None:
        route = self._route()
        if route is None or not self._learn_button.isChecked():
            self._stop_learning()
            return
        dernier = self._hub().last_controller(route.source)
        self._learn_rank = dernier[2] if dernier else 0
        self.say(tr("Tournez un bouton de « %s » : il s'ajoutera à la "
                    "table.") % midihub.endpoint_label(route.source))

    def _stop_learning(self) -> None:
        self._learn_rank = None
        bouton = getattr(self, "_learn_button", None)
        if bouton is not None and bouton.isChecked():
            bouton.setChecked(False)

    def _learn(self, hub) -> None:
        """Le bouton tourné pendant l'apprentissage entre dans la table."""
        route = self._route()
        if route is None or self._learn_rank is None:
            return
        dernier = hub.last_controller(route.source)
        if dernier is None or dernier[2] <= self._learn_rank:
            return
        numero = int(dernier[0])
        self._stop_learning()
        table = dict(route.cc_map)
        table.setdefault(numero, numero)
        self._update(cc_map=table)
        for ligne in range(self._cc_table.rowCount()):
            if self._cc_table.item(ligne, 0).data(
                    Qt.ItemDataRole.UserRole) == numero:
                self._cc_table.selectRow(ligne)
        self.say(tr("Contrôleur %d appris : choisissez ce qu'il règle.")
                 % numero)

    # -- le battement ------------------------------------------------------- #

    def _tick(self) -> None:
        """La minuterie : :meth:`_beat`, sous rempart, et plus rien une fois
        le contexte fermé."""
        if getattr(self.ctx, "closed", False):
            self._timer.stop()
            return
        try:
            self._beat()
        except Exception:  # noqa: BLE001 - rempart, cf. SPEC §6.3
            log.exception("battement du hub en échec")

    def _beat(self) -> None:
        """Dix fois par seconde : ce qui vient de passer brille, le
        moniteur s'allonge, et la page se redessine si un appareil ou un
        état a changé."""
        if not self._built:
            return
        hub = self._hub()
        if self._etat(hub) != self._signature:
            self._show()
        self._pulse(hub)
        self._feed_monitor(hub)
        self._learn(hub)
        if self._matrix.fading():
            self._matrix.update()

    def _pulse(self, hub) -> None:
        comptes = {("s", b.name): b.count for b in hub.sources()}
        comptes.update({("d", b.name): b.count for b in hub.destinations()})
        par_route = hub.counts()
        routes = {r.uid: r for r in hub.routes}
        for uid, nombre in par_route.items():
            if uid in routes:
                comptes[("c", routes[uid].source, routes[uid].dest)] = nombre
        avant, self._counts = self._counts, comptes
        if not avant:
            return
        changes = [cle for cle, n in comptes.items() if n != avant.get(cle, 0)]
        if changes:
            self._matrix.pulse(
                sources=[c[1] for c in changes if c[0] == "s"],
                dests=[c[1] for c in changes if c[0] == "d"],
                cells=[c[1:] for c in changes if c[0] == "c"])

    def _feed_monitor(self, hub) -> None:
        nouveaux = hub.monitor(self._seq)
        if nouveaux:
            self._seq = nouveaux[-1].seq
            liste = self._monitor_list
            for evenement in nouveaux[-MONITOR_LINES:]:
                liste.addItem(self._line(evenement))
            while liste.count() > MONITOR_LINES:
                liste.takeItem(0)
            liste.scrollToBottom()
        stats = hub.stats()
        texte = stats.summary()
        if stats.clock:
            texte += " · " + (plural(stats.clock, N_("%d top d'horloge"),
                                     N_("%d tops d'horloge")) % stats.clock)
        self._stats_label.setText(texte)

    @staticmethod
    def _line(evenement) -> str:
        heure = time.strftime("%H:%M:%S", time.localtime(evenement.at))
        suite = (tr("→ %d") % evenement.delivered if evenement.delivered
                 else tr("→ nulle part"))
        return "%s  %s — %s  %s" % (
            heure, midihub.endpoint_label(evenement.source),
            midihub.describe_message(evenement.status, evenement.data1,
                                     evenement.data2), suite)

    def _clear_monitor(self) -> None:
        self._monitor_list.clear()

    # -- le DAW ------------------------------------------------------------- #

    @staticmethod
    def _daw_text(sources, dests) -> str:
        virtuels = sorted({b.label for b in list(sources) + list(dests)
                           if b.role == "virtual" and b.present})
        if virtuels:
            return tr(
                "Ports virtuels trouvés : %s. Ce que vous branchez sur l'un "
                "d'eux arrive dans le DAW, qui l'ouvre comme une entrée "
                "MIDI ; ce que le DAW y envoie paraît ici en rangée, à "
                "brancher sur le Deluge. Un port virtuel rend ce qu'on lui "
                "envoie : ne le branchez pas sur ce qui l'alimente.") \
                % ", ".join("« %s »" % nom for nom in virtuels)
        return tr(
            "Aucun port virtuel sur ce PC. Votre DAW peut ouvrir lui-même le "
            "clavier et le Deluge, en même temps que le hub : Windows 11 "
            "partage les ports. Pour que le hub parle au DAW — et choisir "
            "d'ici ce qu'il reçoit —, créez une paire de ports en boucle : "
            "avec l'application « MIDI Settings » des outils de Windows "
            "MIDI Services, à installer, ou avec loopMIDI. Ils paraîtront "
            "dans la grille, sous leur nom.")
