# -*- coding: utf-8 -*-
"""Fenêtre principale : assemble les dix pages.

Barre latérale à gauche, en-tête en haut, pages au centre, barre d'état en
bas. Les pages sont **créées au premier affichage** : en construire dix au
démarrage allongerait le lancement sans que l'utilisateur en voie plus d'une.

La colonne range les pages **par intention**, et non par sorte de fichier :
l'accueil, puis *créer* (l'atelier, le générateur, le mémo), puis la
*bibliothèque* (échantillons, presets, kits, morceaux), enfin *la carte*
(santé, réglages). La barre du haut porte la bascule « Simple | Avancé » :
l'essentiel de chaque page, ou tout.

Deux points qui ne sont pas de simples détails d'assemblage :

* **la fermeture arrête les fils de travail.** Un ``QThread`` encore en cours
  quand l'interpréteur se termine fait planter le processus — vérifié.
  :meth:`MainWindow.closeEvent` appelle donc ``tasks.stop_all()`` puis
  ``ctx.close()`` avant de rendre la main ;
* **le démarrage sans carte est un cas normal**, pas une erreur : la fenêtre
  s'ouvre, propose la détection automatique, et les pages affichent leur état
  vide (SPEC §6.1).
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QSettings, Qt, QTimer
from PyQt6.QtGui import QAction, QActionGroup, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenuBar,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from .. import i18n
from ..config import APP_NAME, AppContext
from ..core import sdcard as sdmod
from ..i18n import LANGUAGES, N_, decimal, integer, tr, untranslated
from . import icons, tasks
from .theme import (
    GOLD,
    GREY,
    PAD_AMBER,
    PAD_GREEN,
    apply_theme,
    page_color,
)
from .widgets.chrome import (DropVeil, LedButton, LedStrip, LevelSwitch,
                             NavPad, OledDisplay, RailGroup, Wordmark)
from .widgets.common import BusyBar, SearchBar, human_size

log = logging.getLogger(__name__)

#: Largeurs de la barre latérale, dépliée et repliée. 212 px : le pad, le
#: libellé en gras de la page choisie (« Tableau de bord ») et le chiffre de
#: son raccourci tiennent sans troncature.
RAIL_WIDE = 212
RAIL_NARROW = 64

#: Hauteur de la barre du haut : celle de l'écran OLED et de ses marges.
TOPBAR_HEIGHT = 56

#: Largeurs de fenêtre sous lesquelles la barre du haut se resserre : la
#: recherche et l'écran rétrécissent, « POUR DELUGE » et l'étiquette du
#: Deluge s'effacent. Mesuré : à 980 px, tout tient sans que les menus
#: passent dans le débordement.
TOPBAR_MEDIUM = 1360
TOPBAR_NARROW = 1180

#: Ce que l'écran et la recherche peuvent céder aux menus, au plus : en
#: deçà, le nom de la carte et le mot cherché ne se lisent plus.
HEADER_SCREEN_MIN = 150
HEADER_SEARCH_MIN = 110
#: Marge gardée en plus : le style arrondit les largeurs des boutons.
HEADER_SLACK = 8

#: Clés de persistance de la géométrie et de la page courante.
_GEOMETRY_KEY = "window/geometry"
_STATE_KEY = "window/state"
_PAGE_KEY = "window/page"
_RAIL_KEY = "window/rail"


def _page_classes():
    """Les onze pages, dans l'ordre de la barre latérale.

    Importées ici et non au niveau du module : chaque page tire ses propres
    dépendances, et les charger toutes à l'import ralentirait le démarrage
    sans raison.

    L'ordre suit l'intention, pas la sorte de fichier : on part de
    l'accueil ; on crée (un morceau dans l'atelier, un son dans le
    générateur, le mémo sous la main) ; on puise dans sa bibliothèque ; on
    prend soin de la carte. Les clés internes ne changent pas : l'aide, le
    manuel et les adresses ``Page#Partie`` les citent. Le pont vers le DAW
    suit les morceaux, qu'il emporte et rapporte.
    """
    from .pages.atelier import AtelierPage
    from .pages.dashboard import DashboardPage
    from .pages.daw import DawPage
    from .pages.generator import GeneratorPage
    from .pages.health import HealthPage
    from .pages.kits import KitsPage
    from .pages.samples import SamplesPage
    from .pages.settings import SettingsPage
    from .pages.songs import SongsPage
    from .pages.synths import SynthsPage
    from .pages.toolbox import ToolboxPage

    return (DashboardPage, AtelierPage, GeneratorPage, ToolboxPage,
            SamplesPage, SynthsPage, KitsPage, SongsPage, DawPage, HealthPage,
            SettingsPage)


def _page_digit(index: int) -> int | None:
    """Le chiffre du raccourci de la page de rang ``index`` (depuis 1) :
    ``Ctrl+1`` à ``Ctrl+9``, puis ``Ctrl+0`` pour la dixième ; la onzième,
    les Réglages, n'en a pas — elle garde ``Ctrl+,``."""
    return index % 10 if index <= 10 else None


#: Le titre de chaque groupe de la colonne, posé avant sa première page.
RAIL_GROUPS: dict[str, str] = {
    "Atelier": N_("Créer"),
    "Samples": N_("Bibliothèque"),
    "Health": N_("La carte"),
}


#: La question du redémarrage, par (langue choisie, langue de la phrase).
#: Volontairement bilingue : elle s'affiche dans les deux langues à la fois.
_RESTART_TEXT: dict[tuple[str, str], str] = untranslated({
    ("en", "en"): "Noctiluca will restart in English. Restart now?",
    ("en", "fr"): "Noctiluca va redémarrer en anglais. Redémarrer "
                  "maintenant ?",
    ("fr", "fr"): "Noctiluca va redémarrer en français. Redémarrer "
                  "maintenant ?",
    ("fr", "en"): "Noctiluca will restart in French. Restart now?",
})

#: Ce que dit la barre d'état quand le redémarrage est remis à plus tard,
#: dans la langue encore affichée.
_LATER_TEXT: dict[str, str] = untranslated({
    "fr": "La nouvelle langue s'appliquera au prochain démarrage.",
    "en": "The new language will apply at the next start.",
})


def _short_name(cls) -> str:
    """``DashboardPage`` -> ``Dashboard`` : la clé de navigation."""
    name = cls.__name__
    return name[:-4] if name.endswith("Page") else name


def adopt_window_state(source: QSettings, cible: QSettings) -> int:
    """Recopie l'état de fenêtre de ``source`` dans ``cible``, vide.

    Sert une fois, au changement de nom : sans elle, la fenêtre se rouvrait
    à sa taille d'origine, sur l'accueil. ``source`` n'est pas touchée.
    Rend le nombre de clés reprises.
    """
    if cible.allKeys():
        return 0
    cles = source.allKeys()
    for cle in cles:
        cible.setValue(cle, source.value(cle))
    if cles:
        cible.sync()
        log.info("état de la fenêtre repris de l'ancien nom (%d clés)",
                 len(cles))
    return len(cles)


class MainWindow(QMainWindow):
    """Fenêtre de l'application."""

    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self._pages: dict[str, object] = {}
        self._buttons: dict[str, QPushButton] = {}
        self._classes = {_short_name(c): c for c in _page_classes()}
        self._rail_wide = True
        #: Le Deluge était-il là au dernier battement ? ``None`` tant qu'on
        #: n'a pas encore regardé, pour ne pas annoncer une « apparition »
        #: au démarrage alors qu'il était déjà branché.
        self._deluge_seen: bool | None = None
        #: La fenêtre « Deluge en direct », créée au premier appel.
        self._live_window = None
        #: La fenêtre du manuel, créée au premier appel.
        self._manual_window = None
        #: Dernier tempo de la machine transmis aux pages (arrondi).
        self._tempo_suivi: int | None = None
        #: Vrai quand la fenêtre se ferme pour se rouvrir — dans une autre
        #: langue. ``main.py`` la reconstruit alors au lieu de quitter.
        self.restart_requested = False
        #: Les entrées du menu Langue, par code.
        self._language_actions: dict[str, QAction] = {}
        # Un morceau laissé dans l'atelier à la dernière séance : l'accueil
        # propose de le reprendre avant même que l'atelier soit ouvert.
        if getattr(ctx, "atelier_state", None) is None:
            try:
                from .pages.atelier import draft_state

                ctx.atelier_state = draft_state()
            except Exception:  # noqa: BLE001 - une fiche abîmée ne bloque rien
                log.debug("fiche du brouillon de l'atelier illisible",
                          exc_info=True)

        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.setWindowIcon(icons.app_icon(256))
        self.resize(1360, 860)
        self.setMinimumSize(980, 640)

        central = QWidget(self)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        # La barre de menus vit **dans** la barre du haut : une seule bande
        # de façade, au lieu d'une barre de menus Windows posée sur un
        # bandeau. :meth:`menuBar` la rend, comme Qt le ferait.
        self._menubar = QMenuBar()
        outer.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_rail())

        self._stack = QStackedWidget(self)
        body.addWidget(self._stack, 1)
        outer.addLayout(body, 1)
        self.setCentralWidget(central)
        # Des fichiers du PC glissés n'importe où sur la fenêtre partent vers
        # la carte du Deluge : depuis qu'elle reste dans la machine,
        # l'Explorateur ne l'atteint plus.
        self.setAcceptDrops(True)
        self._drop_veil = DropVeil(central)

        self._build_status_bar()
        self._build_menus()
        self._build_shortcuts()
        # L'en-tête dit tout de suite où en est la carte et le Deluge : sans
        # cela, l'invitation n'apparaît qu'après les 150 ms du premier
        # contrôle, et la pastille reste blanche jusqu'au premier battement.
        # **Après** la barre d'état : l'en-tête y écrit l'espace libre.
        self._refresh_header()
        self._safely(self._refresh_deluge_chip)

        self._restore_state()
        self._fit_header(self.width())
        #: Réponse de la vérification de version, posée par son fil :
        #: ``(demandée, version ou None)`` ; relevée par :meth:`_tick`.
        self._update_answer = None
        #: La première écoute muette a-t-elle été expliquée ?
        self._silence_told = False
        if getattr(ctx.settings, "check_updates", False):
            from ..core import updates

            if updates.due(ctx.settings.last_update_check):
                # Une minuterie de la fenêtre, branchée sur une méthode : une
                # fermeture la débranche (voir la minuterie du brouillon de
                # l'atelier).
                self._update_timer = QTimer(self)
                self._update_timer.setSingleShot(True)
                self._update_timer.timeout.connect(self._auto_update_check)
                self._update_timer.start(4000)
        # Le choix de la carte se fait après l'affichage, pour que la fenêtre
        # soit visible derrière la boîte de dialogue.
        QTimer.singleShot(150, self._check_card)

    # -- en-tête ------------------------------------------------------------ #

    def menuBar(self) -> QMenuBar:  # noqa: N802 - API Qt
        """La barre de menus, logée dans la barre du haut.

        Qt la placerait sur sa propre ligne, au-dessus de tout : une bande
        grise de plus, et l'allure d'un logiciel de bureautique. Elle est
        ici un élément de la façade, entre le logotype et l'écran.
        """
        return self._menubar

    def _build_header(self) -> QWidget:
        host = QFrame(self)
        host.setObjectName("Header")
        host.setFixedHeight(TOPBAR_HEIGHT)
        row = QHBoxLayout(host)
        row.setContentsMargins(12, 0, 12, 0)
        # 6 et non 8 : seize pixels gagnés à 980 px, où la bascule du niveau
        # « ADVANCED », en anglais, poussait le menu Aide dans le débordement.
        row.setSpacing(6)
        self._header_row = row

        self._wordmark = Wordmark(host)
        row.addWidget(self._wordmark)
        row.addSpacing(6)
        row.addWidget(self._menubar, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addStretch(1)

        # L'écran du Deluge : la carte ouverte, et les messages de la barre
        # d'état en surimpression. Un clic mène aux réglages de la carte.
        self._card_button = OledDisplay(host)
        self._card_button.setToolTip(
            tr("Emplacement de la carte — cliquez pour le changer"))
        self._card_button.clicked.connect(
            lambda: self.go_to("Settings"))
        row.addWidget(self._card_button)

        # Pastille du Deluge : éteinte tant qu'il n'est pas là, or quand il
        # est détecté, verte et rayonnante dès qu'il est connecté. C'est la
        # première chose qu'on regarde quand on vient de brancher un câble.
        self._deluge_chip = LedButton("midi", "Deluge", host)
        self._deluge_chip.clicked.connect(self.guard_deluge_chip)
        row.addWidget(self._deluge_chip)

        self._search = SearchBar(tr("Rechercher partout…"))
        self._search.setFixedWidth(240)
        self._search.searchChanged.connect(self._global_search)
        row.addWidget(self._search)

        # « Analyser » était le bouton le plus visible de l'application, et
        # le moins utile depuis que l'index se tient à jour tout seul (au
        # démarrage, après chaque échange avec le Deluge). Il vit désormais
        # sur l'accueil, dans le menu Fichier et sous Ctrl+R ; sa place va à
        # la bascule du niveau : l'essentiel de chaque page, ou tout.
        self._level_switch = LevelSwitch(host)
        self._level_switch.setChecked(self.ctx.settings.advanced)
        self._level_switch.setToolTip(
            tr("Simple : l'essentiel de chaque page. Avancé : tous les "
               "réglages et toutes les commandes  (Ctrl+E)"))
        self._level_switch.set_accent(self.ctx.settings.theme_accent or GOLD)
        self._level_switch.clicked.connect(
            lambda checked=False: self._safely(
                lambda: self.set_interface_level(
                    "avance" if checked else "simple")))
        row.addWidget(self._level_switch)

        # La touche PLAY de la machine : ronde, verte et rayonnante pendant
        # une lecture.
        self._play_button = LedButton("play", "", host)
        self._play_button.setToolTip(tr("Écouter ou arrêter  (Espace)"))
        self._play_button.clicked.connect(self.toggle_play)
        row.addWidget(self._play_button)

        # Le filet lumineux sous la barre, à la couleur de la page affichée :
        # un repère permanent de « où suis-je », visible même du coin de
        # l'œil.
        conteneur = QWidget(self)
        colonne = QVBoxLayout(conteneur)
        colonne.setContentsMargins(0, 0, 0, 0)
        colonne.setSpacing(0)
        colonne.addWidget(host)
        self._accent_strip = LedStrip(conteneur)
        colonne.addWidget(self._accent_strip)
        return conteneur

    def _fit_header(self, largeur: int) -> None:
        """Resserre la barre du haut quand la fenêtre rétrécit.

        Mesuré : à 980 px, la barre complète demandait 1 100 px et ses menus
        passaient dans un débordement « » ». L'écran et la recherche
        rétrécissent, « POUR DELUGE » et l'étiquette « DELUGE » s'effacent ;
        tout revient en élargissant.

        Les menus passent avant l'écran et la recherche, qui leur cèdent ce
        qu'il faut. La largeur des menus dépend de la langue : avec le menu
        Langue, il manquait 56 px en français à 980 px, et 20 px encore à
        1 360 px — « Aide » sortait de la barre sans que rien ne le montre.
        """
        try:
            if largeur >= TOPBAR_MEDIUM:
                ecran, recherche, compact, legende = 330, 240, False, True
            elif largeur >= TOPBAR_NARROW:
                ecran, recherche, compact, legende = 260, 200, False, False
            else:
                ecran, recherche, compact, legende = 196, 150, True, False
            self._wordmark.set_compact(compact)
            self._deluge_chip.set_caption_visible(legende)
            self._level_switch.set_compact(compact)
            manque = self._header_demand(ecran, recherche) - int(largeur)
            if manque > 0:
                # Moitié chacun, dans la limite de ce qui reste lisible.
                cede_ecran = min(manque - manque // 2, ecran - HEADER_SCREEN_MIN)
                ecran -= cede_ecran
                recherche -= min(manque - cede_ecran,
                                 recherche - HEADER_SEARCH_MIN)
            self._card_button.set_preferred_width(ecran)
            self._search.setFixedWidth(recherche)
        except Exception as exc:       # noqa: BLE001 - un ajustement ne casse rien
            log.debug("barre du haut non ajustée : %s", exc)

    def _header_demand(self, ecran: int, recherche: int) -> int:
        """Largeur que demande la barre du haut, écran et recherche à ces
        largeurs, menus entiers."""
        row = self._header_row
        marges = row.contentsMargins()
        total = marges.left() + marges.right() + HEADER_SLACK
        elements = 0
        for index in range(row.count()):
            element = row.itemAt(index)
            widget = element.widget()
            if widget is None:
                total += element.sizeHint().width()
            elif widget.isHidden():
                continue
            elif widget is self._card_button:
                total += ecran
            elif widget is self._search:
                total += recherche
            else:
                total += widget.sizeHint().width()
            elements += 1
        return total + row.spacing() * max(0, elements - 1)

    def resizeEvent(self, event) -> None:  # noqa: N802 - API Qt
        super().resizeEvent(event)
        self._fit_header(self.width())

    def guard_deluge_chip(self) -> None:
        """Un clic sur la pastille : connecter, ou voir la machine.

        Quand la machine est détectée mais pas encore connectée, le geste
        évident est de la connecter — pas d'ouvrir une page pour y chercher
        un bouton. Une fois connectée, le clic ouvre « Deluge en direct » :
        son écran, son tempo, le son sélectionné. Sans machine, il mène aux
        réglages.
        """
        self._safely(self._deluge_chip_clicked)

    def _deluge_chip_clicked(self) -> None:
        from ..core import midiport

        lien = self.ctx.ensure_link()
        if lien.is_connected:
            self.open_live_window()
            return
        if midiport.find("out") is not None:
            reglages = self.ctx.settings
            if lien.connect(reglages.midi_out, reglages.midi_in,
                            card=self.ctx.sd):
                self.statusBar().showMessage(lien.state().summary(), 6000)
                self._refresh_deluge_chip()
                return
        self.go_to("Settings")

    def _refresh_deluge_chip(self) -> None:
        """Couleur et infobulle de la pastille, selon ce qui est branché."""
        from ..core import midiport

        if not midiport.available():
            self._deluge_chip.setVisible(False)
            return

        lien = self.ctx.link
        connecte = bool(lien is not None and lien.is_connected)
        detecte = midiport.find("out") is not None
        self._deluge_chip.setVisible(True)

        if connecte:
            teinte, etat = PAD_GREEN, self._chip_details(lien)
        elif detecte:
            teinte, etat = GOLD, tr("détecté — cliquez pour connecter")
        else:
            teinte, etat = GREY, tr("absent")
        self._deluge_chip.set_state(teinte, connecte or detecte)
        self._deluge_chip.setToolTip(tr("Deluge %s") % etat)

    def _poll_midi(self) -> None:
        """Surveille l'apparition et la disparition de la machine.

        Appelé une fois par seconde par le battement de la barre d'état.
        Énumérer les ports coûte quelques microsecondes : c'est moins cher
        que de demander à l'utilisateur de cliquer sur « rafraîchir ».
        """
        from ..core import midiport

        if not midiport.available():
            return
        present = midiport.find("out") is not None
        lien = self.ctx.link
        connecte = bool(lien is not None and lien.is_connected)

        if present and not connecte and self._deluge_seen is not True:
            # Il vient d'apparaître — ou il était déjà là au démarrage, ce
            # qui mérite la même attention : ``None`` compte comme « pas
            # encore vu ».
            if self.ctx.settings.midi_autoconnect:
                lien = self.ctx.ensure_link()
                reglages = self.ctx.settings
                if lien.connect(reglages.midi_out, reglages.midi_in,
                                card=self.ctx.sd):
                    self.statusBar().showMessage(
                        tr("Deluge branché : %s") % lien.state().summary(),
                        8000)
            else:
                self.statusBar().showMessage(
                    tr("Deluge branché. Connectez-le dans les réglages."), 8000)
        elif connecte and not present:
            # Débranché pendant l'utilisation : on referme proprement, sinon
            # le port reste ouvert sur un appareil qui n'existe plus.
            lien.disconnect()
            self.statusBar().showMessage(tr("Deluge débranché."), 6000)

        self._deluge_seen = present
        self._refresh_deluge_chip()

    # -- liaison vivante ---------------------------------------------------- #

    @staticmethod
    def _chip_details(lien) -> str:
        """Infobulle de la pastille quand la machine est connectée."""
        etat = lien.state()
        morceaux = [tr("connecté")]
        if etat.firmware:
            morceaux.append(tr("firmware %s") % etat.firmware)
        if etat.tempo is not None:
            morceaux.append("%s BPM%s" % (decimal(etat.tempo, 1),
                                          " ▶" if etat.running else ""))
        morceaux.append(tr("cliquez pour le voir en direct"))
        return " — ".join(morceaux)

    def _service_link(self) -> None:
        """Fait vivre le lien : la machine parle, l'application écoute."""
        lien = self.ctx.link
        if lien is None or not lien.is_connected:
            return
        try:
            evenements = lien.service()
        except Exception as exc:       # noqa: BLE001 - un battement ne casse rien
            log.debug("service du lien MIDI : %s", exc)
            return
        if not evenements:
            return
        if "identity" in evenements and lien.identity is not None:
            self.statusBar().showMessage(
                tr("Deluge identifié : firmware %s.") % lien.identity.version,
                6000)
            reglages = self._pages.get("Settings")
            if reglages is not None and hasattr(reglages, "_refresh_midi"):
                self._safely(reglages._refresh_midi)
        if "tempo" in evenements and lien.tempo is not None \
                and getattr(self.ctx.settings, "midi_follow_tempo", True):
            self._follow_tempo(lien.tempo)
        if evenements & {"identity", "ping", "tempo", "transport"}:
            self._refresh_deluge_chip()
        if "files" in evenements:
            self._safely(self.card_work.on_files_known)
        if "transport" in evenements:
            self._safely(self.card_work.on_transport)

    # -- la copie de travail ------------------------------------------------ #

    def _card_written(self) -> None:
        """L'application a écrit : rafraîchir, et envoyer au Deluge."""
        self.refresh_all()
        self._safely(self.card_work.on_card_written)

    def _work_received(self) -> None:
        """Le Deluge a envoyé des fichiers : l'index doit les voir."""
        page = self._pages.get("Dashboard") or self._create_page("Dashboard")
        if page is not None and hasattr(page, "update_index"):
            self._safely(page.update_index)
        self.refresh_all()

    def _card_work_changed(self) -> None:
        self._refresh_header()
        for cle, methode in (("Settings", "_refresh_work"),
                             ("Dashboard", "refresh_exchanges")):
            page = self._pages.get(cle)
            if page is not None and hasattr(page, methode):
                self._safely(getattr(page, methode))

    def sync_deluge(self) -> None:
        """Menu : synchroniser maintenant, ou créer la copie de travail."""
        if self.card_work.files() is None:
            self.statusBar().showMessage(
                tr("Le Deluge n'ouvre pas sa carte par USB : branchez-le, avec "
                   "le firmware 1.3 ou plus récent."), 8000)
            return
        if not self.card_work.has_work_copy():
            self.card_work.create_work_copy(self)
            return
        self.card_work.sync("demande")

    # -- du PC vers le Deluge ------------------------------------------------- #

    @staticmethod
    def _start_folder() -> str:
        telechargements = Path.home() / "Downloads"
        return str(telechargements if telechargements.is_dir()
                   else Path.home())

    def send_to_deluge(self, paths=None, dest: str = "") -> None:
        """Envoie des fichiers du PC vers la carte du Deluge.

        Le plan est montré avant toute copie (:mod:`.sendfiles`). Sans
        ``paths``, une fenêtre de choix s'ouvre — pour un dossier ou un
        pack entier, :meth:`send_folder_to_deluge`, ou un glisser-déposer.
        """
        from .sendfiles import send_files

        chemins = [p for p in (paths or []) if p]
        if not chemins:
            chemins, _filtre = QFileDialog.getOpenFileNames(
                self, tr("Envoyer au Deluge"), self._start_folder(),
                tr("Sons, presets, kits et morceaux du Deluge "
                   "(*.wav *.WAV *.aif *.aiff *.xml *.XML);;"
                   "Tous les fichiers (*)"))
        if chemins:
            send_files(self, chemins, dest or self._drop_destination())

    def send_folder_to_deluge(self) -> None:
        """Envoie un dossier entier — un pack téléchargé, par exemple."""
        from .sendfiles import send_files

        dossier = QFileDialog.getExistingDirectory(
            self, tr("Envoyer un dossier au Deluge"), self._start_folder())
        if dossier:
            send_files(self, [dossier], self._drop_destination())

    def _drop_destination(self) -> str:
        """Le dossier d'échantillons choisi sur la page Échantillons, s'il y
        en a un : on dépose là où l'on regarde."""
        page = self._stack.currentWidget()
        dossier = str(getattr(page, "_folder", "") or "")
        return dossier if dossier.upper().startswith("SAMPLES") else ""

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - API Qt
        from .sendfiles import local_paths, where_it_goes

        try:
            if local_paths(event.mimeData()):
                event.acceptProposedAction()
                self._drop_veil.show_over(
                    self.centralWidget().rect(),
                    where_it_goes(self.ctx)
                    or tr("Choisissez d'abord la carte, dans les réglages."))
                return
        except Exception as exc:       # noqa: BLE001 - un dépôt ne casse rien
            log.debug("dépôt refusé : %s", exc)
        event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802 - API Qt
        if self._drop_veil.isVisible():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802 - API Qt
        self._drop_veil.hide()
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802 - API Qt
        from .sendfiles import local_paths

        self._drop_veil.hide()
        chemins = local_paths(event.mimeData())
        if not chemins:
            event.ignore()
            return
        event.acceptProposedAction()
        destination = self._drop_destination()
        # Après le dépôt, pas pendant : l'Explorateur attend que le dépôt
        # se termine, et une question posée ici le figerait avec nous.
        QTimer.singleShot(0, lambda: self._safely(
            lambda: self.send_to_deluge(chemins, destination)))

    def changeEvent(self, event) -> None:  # noqa: N802 - API Qt
        super().changeEvent(event)
        try:
            from PyQt6.QtCore import QEvent

            if event.type() == QEvent.Type.ActivationChange \
                    and self.isActiveWindow():
                self.card_work.on_focus()
        except Exception as exc:       # noqa: BLE001 - un retour ne casse rien
            log.debug("retour dans la fenêtre : %s", exc)

    def _follow_tempo(self, bpm: float) -> None:
        """Les pages qui ont un tempo prennent celui de la machine.

        Seulement quand le tempo arrondi change : l'horloge fluctue d'un
        dixième, et réécrire les champs à chaque impulsion empêcherait de
        les modifier à la main.
        """
        arrondi = int(round(float(bpm)))
        if arrondi == self._tempo_suivi:
            return
        self._tempo_suivi = arrondi
        suivis = 0
        for page in self._pages.values():
            suivre = getattr(page, "follow_tempo", None)
            if suivre is None:
                continue
            try:
                if suivre(arrondi):
                    suivis += 1
            except Exception as exc:   # noqa: BLE001
                log.debug("tempo non transmis à une page : %s", exc)
        if suivis:
            self.statusBar().showMessage(
                tr("Tempo du Deluge : %d BPM, repris par les outils.")
                % arrondi, 4000)

    def open_live_window(self) -> None:
        """Ouvre — ou ramène devant — la fenêtre « Deluge en direct »."""
        from .livewindow import DelugeLiveWindow

        if self._live_window is None:
            self._live_window = DelugeLiveWindow(self.ctx, self)
            self._live_window.settingsRequested.connect(
                lambda: (self.go_to("Settings"), self.raise_(),
                         self.activateWindow()))
        self._live_window.show()
        self._live_window.raise_()
        self._live_window.activateWindow()


    # -- barre latérale ----------------------------------------------------- #

    def _build_rail(self) -> QWidget:
        self._rail = QFrame(self)
        self._rail.setObjectName("Sidebar")
        self._rail.setFixedWidth(RAIL_WIDE)

        column = QVBoxLayout(self._rail)
        column.setContentsMargins(4, 10, 8, 8)
        column.setSpacing(2)
        #: Les titres de groupe, que le repli réduit à un filet.
        self._rail_groups: list[RailGroup] = []

        for index, (key, cls) in enumerate(self._classes.items(), 1):
            groupe = RAIL_GROUPS.get(key)
            if groupe:
                titre = RailGroup(tr(groupe), self._rail)
                column.addSpacing(4)
                column.addWidget(titre)
                self._rail_groups.append(titre)
            # Chaque page est un pad de sa couleur : éteint, il la montre
            # en veilleuse ; choisi, il s'allume. La colonne devient une
            # rangée de pads de la machine, et l'on repère une destination à
            # la teinte avant même d'avoir lu l'étiquette. Le chiffre est
            # celui du raccourci.
            # La dixième prend le 0, comme sur un clavier ; la onzième, les
            # Réglages, garde Ctrl+,.
            chiffre = _page_digit(index)
            button = NavPad(tr(cls.TITLE), cls.ICON, page_color(key), chiffre,
                            self._rail)
            button.setToolTip("%s  (Ctrl+%s)" % (
                tr(cls.TITLE), chiffre if chiffre is not None else ","))
            button.setProperty("navColor", page_color(key))
            button.clicked.connect(
                lambda _c=False, k=key: self.go_to(k))
            column.addWidget(button)
            self._buttons[key] = button

        column.addStretch(1)

        self._fold_button = QPushButton("  " + tr("Replier"), self._rail)
        self._fold_button.setObjectName("NavButton")
        self._fold_button.setIcon(icons.icon("chevron-left", GREY, 14))
        self._fold_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._fold_button.setToolTip(
            tr("Réduire la colonne à ses pads, pour donner la place aux "
               "listes  (Ctrl+B)"))
        self._fold_button.clicked.connect(self.toggle_rail)
        column.addWidget(self._fold_button)
        return self._rail

    def toggle_rail(self) -> None:
        """Replie ou déplie la barre latérale."""
        self._rail_wide = not self._rail_wide
        self._rail.setFixedWidth(RAIL_WIDE if self._rail_wide
                                 else RAIL_NARROW)
        for key, button in self._buttons.items():
            cls = self._classes[key]
            button.setText("  " + tr(cls.TITLE) if self._rail_wide else "")
        for titre in self._rail_groups:
            titre.set_compact(not self._rail_wide)
        self._fold_button.setText("  " + tr("Replier") if self._rail_wide
                                  else "")
        self._fold_button.setIcon(
            icons.icon("chevron-left" if self._rail_wide else "chevron-right",
                       GREY, 14))
        self._fold_button.setToolTip(
            tr("Réduire la colonne à ses pads, pour donner la place aux "
               "listes  (Ctrl+B)") if self._rail_wide else
            tr("Déplier la colonne et ses étiquettes  (Ctrl+B)"))

    # -- barre d'état ------------------------------------------------------- #

    def _tint_header(self, teinte: str) -> None:
        """Teinte le filet lumineux à la couleur de la page affichée."""
        try:
            self._accent_strip.set_color(teinte)
        except Exception as exc:        # noqa: BLE001 - simple décor
            log.debug("teinte d'en-tête impossible : %s", exc)

    def _build_status_bar(self) -> None:
        bar = self.statusBar()

        self._progress = BusyBar()
        self._progress.setFixedWidth(160)
        self._progress.setVisible(False)
        bar.addPermanentWidget(self._progress)

        self._playing = QLabel("")
        self._playing.setFixedWidth(90)
        bar.addPermanentWidget(self._playing)

        self._space = QLabel("")
        bar.addPermanentWidget(self._space)

        # Comme la machine affiche ses messages en surimpression sur son
        # écran, l'écran de la barre du haut reprend chaque message de la
        # barre d'état quelques secondes : on le lit là où l'on regarde.
        bar.messageChanged.connect(self._card_button.flash)

        # L'indicateur de lecture et l'espace libre se rafraîchissent seuls.
        self._ticker = QTimer(self)
        self._ticker.setInterval(1000)
        self._ticker.timeout.connect(self._tick)
        self._ticker.start()

        # La liaison vivante : ce que la machine envoie (horloge, écran,
        # réglages, notes) est traité vingt-cinq fois par seconde, et ne
        # coûte rien quand rien n'arrive.
        self._link_timer = QTimer(self)
        self._link_timer.setInterval(40)
        self._link_timer.timeout.connect(self._service_link)
        self._link_timer.start()

        # La carte reste dans le Deluge : la copie de travail se tient à son
        # image (firmware 1.3, par USB). Les pages l'interrogent par le
        # contexte.
        from .cardwork import CardWork

        self.card_work = CardWork(self)
        self.ctx.card_work = self.card_work
        self.card_work.stateChanged.connect(self._card_work_changed)
        self.card_work.workChanged.connect(self._work_received)
        bar.showMessage(tr("Prêt."))

    def _tick(self) -> None:
        """Met à jour les indicateurs de la barre d'état."""
        try:
            player = self.ctx.player
            playing = bool(player is not None and player.is_playing)
            # Sans sortie audio, la lecture avance en silence : l'indicateur
            # le dit, et la première fois la barre d'état dit pourquoi.
            muette = playing and not player.available
            self._playing.setText(tr("● lecture muette") if muette
                                  else tr("● lecture") if playing else "")
            self._playing.setStyleSheet(
                f"color: {PAD_AMBER};" if muette
                else f"color: {PAD_GREEN};" if playing else "")
            self._playing.setToolTip(player.silence_reason() if muette else "")
            silences = getattr(player, "silent_plays", 0) if player else 0
            if silences and not getattr(self, "_silence_told", False):
                self._silence_told = True
                self.statusBar().showMessage(
                    tr("Rien ne s'entend : %s.") % player.silence_reason(),
                    15000)
            self._play_button.set_icon_name("stop" if playing else "play")
            self._play_button.set_state(PAD_GREEN if playing else GREY,
                                        playing)

            busy = tasks.active_count()
            self._progress.setVisible(busy > 0)
            if busy > 0:
                self._progress.set_busy(True)

            self._poll_midi()
            if self._update_answer is not None:
                answer, self._update_answer = self._update_answer, None
                self._update_known(*answer)
        except Exception as exc:  # noqa: BLE001 - un indicateur ne casse rien
            log.debug("barre d'état : %s", exc)

    def _card_counts(self) -> str:
        """Le contenu de la carte en une ligne d'écran, ou rien."""
        try:
            stats = self.ctx.lib.stats() if self.ctx.lib is not None else {}
        except Exception as exc:  # noqa: BLE001 - l'index peut manquer
            log.debug("statistiques indisponibles : %s", exc)
            return ""
        morceaux = []
        for cle, nom in (("samples", N_("sons")), ("synths", N_("presets")),
                         ("kits", N_("kits")), ("songs", N_("morceaux"))):
            valeur = int((stats or {}).get(cle, 0) or 0)
            if valeur:
                morceaux.append("%s %s" % (integer(valeur), tr(nom)))
        return " · ".join(morceaux)

    def _refresh_header(self) -> None:
        """Met à jour l'écran de la carte et l'espace libre.

        Le texte du bouton garde le chemin complet, comme avant ; l'écran
        en montre le nom en grand, et le contenu de la carte en petit.
        """
        path = self.ctx.settings.sd_path
        nom = Path(path).name if path else ""
        role = self.ctx.settings.card_role(path) if path else ""
        if self.ctx.has_card:
            self._card_button.setText(f"  {path}")
            contenu = self._card_counts()
            etiquette = (tr("CARTE · %s") % contenu) if contenu else (
                tr("CARTE · pas encore analysée"))
            grand = (nom or path).upper()
            infobulle = tr("%s\n\nCliquez pour changer de carte.") % path
            travail = getattr(self, "card_work", None)
            if role == "travail":
                grand = tr("CARTE DU DELUGE")
                etiquette = (tr("COPIE DE TRAVAIL · %s") % contenu) \
                    if contenu else tr("COPIE DE TRAVAIL")
                # Ce qui attend le Deluge se lit là où l'on regarde.
                if travail is not None and travail.busy:
                    etiquette = tr("COPIE DE TRAVAIL · SYNCHRONISATION…")
                elif travail is not None and travail.pending:
                    etiquette = (tr("COPIE DE TRAVAIL · %d À ENVOYER")
                                 % len(travail.pending))
                etat = travail.summary() if travail is not None else ""
                infobulle = (tr("Copie de travail de la carte, tenue à son "
                                "image par USB :\n%s\n\n%s")
                             % (path, etat)).strip()
            elif role == "sauvegarde":
                etiquette = tr("SAUVEGARDE · LECTURE SEULE")
                infobulle = (tr("%s\n\nLa sauvegarde de la carte : "
                                "l'application la lit, elle n'y écrit jamais. "
                                "Réglages ▸ Carte du Deluge pour travailler "
                                "sur la carte.") % path)
            self._card_button.set_display(etiquette, grand,
                                          "warn" if role == "sauvegarde"
                                          else "hi")
            self._card_button.setToolTip(infobulle)
        elif path:
            self._card_button.setText("  " + tr("%s  (invalide)") % path)
            self._card_button.set_display(tr("CARTE INTROUVABLE"),
                                          (nom or path).upper(), "error")
            self._card_button.setToolTip(
                tr("%s\n\nCe dossier ne contient pas d'arborescence "
                   "Deluge. Cliquez pour en choisir un autre.") % path)
        else:
            self._card_button.setText(
                "  " + tr("Aucune carte — cliquez pour choisir"))
            self._card_button.set_display(tr("AUCUNE CARTE"),
                                          tr("CLIQUEZ POUR CHOISIR"), "warn")
            self._card_button.setToolTip(
                tr("Aucune carte choisie. Cliquez pour indiquer où elle est."))

        free = total = 0
        if self.ctx.sd is not None:
            try:
                free, total = self.ctx.sd.free_space()
            except Exception:  # noqa: BLE001
                free = total = 0
        if not total:
            self._space.setText("")
        elif self.ctx.sd.is_volume:
            self._space.setText(tr("%s libres") % human_size(free))
        else:
            self._space.setText(tr("%s libres sur le disque")
                                % human_size(free))

    # -- menus et raccourcis ------------------------------------------------ #

    def _build_menus(self) -> None:
        bar = self.menuBar()

        file_menu = bar.addMenu(tr("&Fichier"))
        self._add_action(file_menu, tr("Choisir la carte…"), self._choose_card,
                         "Ctrl+O")
        self._add_action(file_menu, tr("Analyser la carte"), self.scan_card,
                         "Ctrl+R")
        self._add_action(file_menu, tr("Sauvegarder la carte"),
                         lambda: self.go_to("Health"))
        file_menu.addSeparator()
        self._add_action(file_menu, tr("Envoyer des fichiers au Deluge…"),
                         self.send_to_deluge, "Ctrl+I")
        self._add_action(file_menu, tr("Envoyer un dossier au Deluge…"),
                         self.send_folder_to_deluge, "Ctrl+Shift+I")
        file_menu.addSeparator()
        self._add_action(file_menu, tr("Quitter"), self.close, "Ctrl+Q")

        edit_menu = bar.addMenu(tr("&Édition"))
        self._add_action(edit_menu, tr("Rechercher"), self._focus_search,
                         "Ctrl+F")
        self._add_action(edit_menu, tr("Réglages…"),
                         lambda: self.go_to("Settings"), "Ctrl+,")

        tools_menu = bar.addMenu(tr("&Outils"))
        self._add_action(tools_menu, tr("Nouveau morceau"), self.new_song,
                         "Ctrl+N")
        self._add_action(tools_menu, tr("Ouvrir un morceau du Deluge…"),
                         self.open_song_in_atelier)
        self._add_action(tools_menu, tr("Générateur de presets"),
                         lambda: self.go_to("Generator"), "Ctrl+G")
        self._add_action(tools_menu, tr("Mémo"),
                         lambda: self.go_to("Toolbox"))
        self._add_action(tools_menu, tr("Santé de la carte"),
                         lambda: self.go_to("Health"))
        tools_menu.addSeparator()
        self._add_action(tools_menu, tr("Deluge en direct"),
                         self.open_live_window, "Ctrl+D")
        self._add_action(tools_menu, tr("Synchroniser avec le Deluge"),
                         self.sync_deluge, "Ctrl+Shift+D")
        self._add_action(tools_menu, tr("Firmware du Deluge…"),
                         self.open_firmware)
        tools_menu.addSeparator()
        self._level_action = self._add_action(
            tools_menu, tr("Mode avancé"), self.toggle_level, "Ctrl+E")
        self._level_action.setCheckable(True)
        self._level_action.setChecked(self.ctx.settings.advanced)
        self._add_action(tools_menu, tr("Replier la barre latérale"),
                         self.toggle_rail, "Ctrl+B")

        self._build_language_menu(bar)

        help_menu = bar.addMenu(tr("&Aide"))
        self._add_action(help_menu, tr("Manuel"), self.open_manual, "F1")
        self._add_action(help_menu, tr("Premiers pas"),
                         lambda: self.open_manual("premiers-pas"))
        help_menu.addSeparator()
        self._add_action(help_menu, tr("Raccourcis clavier"),
                         self._show_shortcuts)
        help_menu.addSeparator()
        self._add_action(help_menu, tr("Signaler un problème…"),
                         self.report_problem)
        self._add_action(help_menu, tr("Rechercher une nouvelle version"),
                         lambda: self.check_for_update(manual=True))
        self._add_action(help_menu, tr("À propos"), self._show_about)

    def _build_language_menu(self, bar) -> None:
        """Le menu Langue : chaque langue écrite dans la sienne.

        « Français » et « English » ne se traduisent pas : qui a choisi par
        mégarde une langue qu'il ne lit pas doit retrouver la sienne d'un
        coup d'œil. La langue retenue est cochée — celle des réglages, qui
        peut attendre le prochain démarrage.
        """
        menu = bar.addMenu(tr("&Langue"))
        groupe = QActionGroup(self)
        groupe.setExclusive(True)
        choisie = i18n.normalize(self.ctx.settings.language)
        for code, nom in LANGUAGES:
            action = QAction(nom, self)
            action.setCheckable(True)
            action.setChecked(code == choisie)
            action.setData(code)
            action.triggered.connect(
                lambda _checked=False, c=code:
                self._safely(lambda: self.choose_language(c)))
            groupe.addAction(action)
            menu.addAction(action)
            self._language_actions[code] = action
        self._language_menu = menu

    def _add_action(self, menu, label: str, slot, shortcut: str = "") -> QAction:
        action = QAction(label, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(lambda _checked=False: self._safely(slot))
        menu.addAction(action)
        return action

    def _safely(self, slot) -> None:
        """Exécute une action de menu sans laisser passer d'exception."""
        try:
            slot()
        except Exception:  # noqa: BLE001 - rempart, cf. SPEC §6.3
            log.exception("action de menu en échec")
            self.statusBar().showMessage(
                tr("Action impossible : voir le journal."), 8000)

    def _build_shortcuts(self) -> None:
        """``Ctrl+1`` à ``Ctrl+0`` pour les pages, ``Espace`` pour l'écoute."""
        for index, key in enumerate(self._classes, 1):
            chiffre = _page_digit(index)
            if chiffre is None:
                continue
            action = QAction(self)
            action.setShortcut(QKeySequence(f"Ctrl+{chiffre}"))
            action.triggered.connect(
                lambda _c=False, k=key: self.go_to(k))
            self.addAction(action)

        play = QAction(self)
        play.setShortcut(QKeySequence(Qt.Key.Key_Space))
        play.triggered.connect(lambda _c=False: self._safely(self.toggle_play))
        self.addAction(play)

    # -- navigation --------------------------------------------------------- #

    def go_to(self, key: str) -> None:
        """Affiche une page, en la créant si c'est la première fois.

        ``key`` peut être une adresse : ``"Health#Doublons"`` ouvre la santé
        de la carte et la place sur son onglet des doublons. Le raccourci du
        tableau de bord amène ainsi directement là où le travail se fait, au
        lieu de laisser l'utilisateur chercher parmi cinq onglets.
        """
        key, _, partie = str(key or "").partition("#")
        if key not in self._classes:
            log.debug("page inconnue : %r", key)
            return
        page = self._pages.get(key)
        nouvelle = page is None
        if page is None:
            page = self._create_page(key)
            if page is None:
                return
        # Une page qui devient visible se rafraîchit d'elle-même
        # (``Page.showEvent``). La rafraîchir ici aussi la faisait travailler
        # deux fois à chaque visite — deux diagnostics de santé d'une seconde
        # pour le tableau de bord, mesurés sur la carte de l'utilisateur. On
        # ne le fait donc que si elle était déjà affichée : aucun événement
        # d'affichage ne viendra alors.
        deja_affichee = (self._stack.currentWidget() is page
                         and page.isVisible())
        self._stack.setCurrentWidget(page)
        for name, button in self._buttons.items():
            # Le pad de la page s'allume, les autres retombent en veilleuse :
            # on sait où l'on est sans avoir à comparer neuf icônes.
            button.setChecked(name == key)
        self._tint_header(page_color(key))
        if deja_affichee:
            try:
                page.refresh()
            except Exception:  # noqa: BLE001 - la page a déjà son rempart
                log.exception("rafraîchissement de %s en échec", key)
        if nouvelle:
            self._safely(lambda: self._offer_tempo(page))
        if partie:
            self._safely(lambda: page.focus_on(partie))

    def _offer_tempo(self, page) -> None:
        """Une page ouverte pendant que la machine joue prend son tempo.

        Les pages ne se construisent qu'à leur première visite : sans cela,
        une page ouverte après l'arrivée de l'horloge garderait le tempo du
        genre. Une seule fois — ensuite, c'est l'utilisateur qui décide.
        """
        lien = self.ctx.link
        suivre = getattr(page, "follow_tempo", None)
        if (suivre is None or lien is None or not lien.is_connected
                or lien.tempo is None
                or not getattr(self.ctx.settings, "midi_follow_tempo", True)):
            return
        suivre(int(round(float(lien.tempo))))

    def _create_page(self, key: str):
        """Instancie une page et branche ses signaux."""
        cls = self._classes[key]
        try:
            page = cls(self.ctx, self)
        except Exception:  # noqa: BLE001
            log.exception("création de la page %s impossible", key)
            self.statusBar().showMessage(
                tr("La page « %s » n'a pas pu être ouverte.") % tr(cls.TITLE),
                8000)
            return None

        self._pages[key] = page
        self._stack.addWidget(page)
        self._connect_page(key, page)
        return page

    def _connect_page(self, key: str, page) -> None:
        """Branche les signaux d'une page sur la fenêtre."""
        page.status.connect(
            lambda message: self.statusBar().showMessage(message, 10000))
        page.settingsRequested.connect(lambda: self.go_to("Settings"))

        # Chaque page expose les signaux qui lui sont propres ; on les
        # branche s'ils existent, sans supposer leur présence.
        connections = {
            "navigateRequested": self.go_to,
            "detectRequested": self._check_card,
            "scanFinished": self.refresh_all,
            "cardModified": self._card_written,
            "presetSaved": lambda _rel: self._card_written(),
            "songWritten": lambda _rel: self._card_written(),
            "cardChanged": self._card_changed,
            "accentChanged": self._accent_changed,
            "resetIndexRequested": self.refresh_all,
            "fullScanRequested": lambda: self._safely(
                lambda: self.scan_card(full=True)),
            "openInGenerator": self._open_in_generator,
            "liveRequested": self.open_live_window,
            "sendRequested": self.send_to_deluge,
            "syncRequested": self.sync_deluge,
            "backupRequested": lambda: self.card_work.update_backup(self),
            "toAtelier": lambda offre: self._safely(
                lambda: self._to_atelier(offre)),
            "levelChanged": lambda niveau: self._safely(
                lambda: self.set_interface_level(niveau)),
            "songRequested": lambda: self._safely(self.open_song_in_atelier),
        }
        for name, slot in connections.items():
            signal = getattr(page, name, None)
            if signal is None or not hasattr(signal, "connect"):
                continue
            try:
                signal.connect(slot)
            except TypeError as exc:
                log.debug("signal %s.%s non branché : %s", key, name, exc)

    def _open_in_generator(self, rel: str) -> None:
        """Ouvre un preset de la carte dans le générateur."""
        card = self.ctx.sd
        if card is None or not rel:
            return
        from ..core.model import SynthPreset

        try:
            preset = SynthPreset.load(card.abs(rel))
        except Exception:  # noqa: BLE001
            log.exception("preset illisible pour le générateur : %s", rel)
            self.statusBar().showMessage(tr("Preset illisible : %s") % rel,
                                         8000)
            return
        self.go_to("Generator")
        page = self._pages.get("Generator")
        starter = getattr(page, "start_from", None)
        if callable(starter):
            starter(preset)

    def refresh_all(self) -> None:
        """Rafraîchit la page visible, et marque les autres à rafraîchir.

        Les pages cachées se rafraîchissent d'elles-mêmes à leur prochain
        affichage (``showEvent``) : inutile de les parcourir maintenant.
        """
        self._refresh_header()
        current = self._stack.currentWidget()
        if current is not None and hasattr(current, "refresh"):
            try:
                current.refresh()
            except Exception:  # noqa: BLE001
                log.exception("rafraîchissement en échec")

    # -- le niveau de l'interface ------------------------------------------ #

    def set_interface_level(self, level: str) -> None:
        """« simple » ou « avance » : retenu, puis appliqué à toutes les pages.

        La bascule de la barre du haut, le menu et les réglages disent tous
        trois le même état ; seules les pages déjà bâties se réarrangent, les
        autres liront le niveau à leur premier affichage.
        """
        from ..config import normalize_level

        level = normalize_level(level)
        self.ctx.settings.interface_level = level
        try:
            self.ctx.save()
        except Exception:  # noqa: BLE001
            log.exception("enregistrement du niveau impossible")
        avance = level == "avance"
        for temoin in (self._level_switch, getattr(self, "_level_action",
                                                   None)):
            if temoin is not None and temoin.isChecked() != avance:
                temoin.blockSignals(True)
                temoin.setChecked(avance)
                temoin.blockSignals(False)
        for page in self._pages.values():
            appliquer = getattr(page, "apply_level", None)
            if callable(appliquer):
                try:
                    appliquer()
                except Exception:  # noqa: BLE001
                    log.exception("niveau non appliqué à une page")
        self._fit_header(self.width())
        self.statusBar().showMessage(
            tr("Mode avancé : tous les réglages et toutes les commandes sont "
               "visibles.") if avance else
            tr("Mode simple : l'essentiel de chaque page ; le reste revient "
               "en mode avancé."), 6000)

    def toggle_level(self) -> None:
        """Passe d'un niveau à l'autre  (Ctrl+E)."""
        self.set_interface_level(
            "simple" if self.ctx.settings.advanced else "avance")

    # -- l'atelier ------------------------------------------------------------ #

    def new_song(self) -> None:
        """Un morceau neuf : l'atelier, à sa première étape."""
        self.go_to("Atelier#Style")

    def open_song_in_atelier(self) -> None:
        """Ouvre dans l'atelier un morceau de la carte, choisi dans la liste."""
        self.go_to("Atelier")
        page = self._pages.get("Atelier")
        choisir = getattr(page, "_import_song", None)
        if callable(choisir):
            choisir()

    def _to_atelier(self, offre) -> None:
        """Un son ou un kit d'une autre page rejoint le morceau de l'atelier.

        ``offre`` : ``{"preset", "part", "options", "edited"}`` ou
        ``{"kit"}``. L'atelier vient devant, sur l'étape où l'on écoute.
        """
        offre = dict(offre or {})
        self.go_to("Atelier")
        page = self._pages.get("Atelier")
        if page is None:
            return
        if offre.get("kit") is not None:
            page.offer_kit(offre["kit"])
        elif offre.get("preset") is not None:
            page.offer_preset(offre["preset"], offre.get("part", ""),
                              options=offre.get("options"),
                              edited=bool(offre.get("edited")))

    # -- actions ------------------------------------------------------------ #

    def scan_card(self, full: bool = False) -> None:
        """Lance l'analyse depuis le tableau de bord, qui la porte déjà.

        Incrémentale (Ctrl+R, menu Fichier) ; ``full`` relit toute la carte
        (Réglages ▸ [Tout réanalyser]).
        """
        self.go_to("Dashboard")
        page = self._pages.get("Dashboard")
        starter = getattr(page, "_start_scan", None)
        if callable(starter):
            starter(full=bool(full))

    def toggle_play(self) -> None:
        """Arrête la lecture en cours, ou relance l'écoute de la page."""
        player = self.ctx.player
        if player is None:
            return
        try:
            if player.is_playing:
                player.stop()
                self.statusBar().showMessage(tr("Lecture arrêtée."), 4000)
                return
        except Exception as exc:  # noqa: BLE001
            log.debug("état du lecteur indisponible : %s", exc)

        page = self._stack.currentWidget()
        for name in ("_play", "_listen", "_listen_row"):
            action = getattr(page, name, None)
            if callable(action):
                try:
                    action()
                except Exception:  # noqa: BLE001
                    log.exception("écoute impossible")
                return

    def _focus_search(self) -> None:
        self._search.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self._search.selectAll()

    def _global_search(self, text: str) -> None:
        """Renvoie la recherche vers la page des échantillons."""
        if not text:
            return
        self.go_to("Samples")
        page = self._pages.get("Samples")
        field = getattr(page, "_search", None)
        if field is not None:
            field.setText(text)
            reload = getattr(page, "_reload", None)
            if callable(reload):
                reload()

    # -- carte SD ----------------------------------------------------------- #

    def _match_index_to_card(self) -> None:
        """Écarte l'index s'il décrit une autre carte que celle choisie."""
        if self.ctx.sd is None or self.ctx.lib is None:
            return
        from ..core.scan import forget_other_card

        try:
            if forget_other_card(self.ctx.sd, self.ctx.lib):
                self.statusBar().showMessage(
                    tr("Nouvelle carte : lancez « Analyser la carte » pour "
                       "l'indexer."), 0)
        except Exception:  # noqa: BLE001
            log.exception("comparaison de l'index et de la carte impossible")

    def _update_index_on_start(self) -> None:
        """Relit en arrière-plan ce qui a changé sur la carte depuis la
        dernière analyse : une fraction de seconde, en lecture seule.

        Mesuré sur la carte de l'utilisateur : son index annonçait encore
        125 échantillons manquants et une note de 85, alors qu'une
        réparation les avait rétablis depuis ; 10 fichiers relus en 0,2 s
        ramenaient la note à 90.
        """
        if not getattr(self.ctx.settings, "index_on_start", True):
            return
        page = self._pages.get("Dashboard") or self._create_page("Dashboard")
        if page is None:
            return
        try:
            page.update_index()
        except Exception:  # noqa: BLE001 - l'index se rattrapera à la main
            log.exception("mise à jour de l'index au démarrage impossible")

    def _check_card(self) -> None:
        """Au démarrage : propose une carte si aucune n'est valide."""
        self._refresh_header()
        if self.ctx.has_card:
            self.statusBar().showMessage(
                tr("Carte : %s") % self.ctx.settings.sd_path, 6000)
            self._match_index_to_card()
            self._update_index_on_start()
            self._safely(self.card_work.on_start)
            return

        found = []
        try:
            found = sdmod.detect_sd_cards()
        except Exception as exc:  # noqa: BLE001
            log.debug("détection impossible : %s", exc)

        if found:
            lines = "\n".join(f"  •  {p}" for p in found[:6])
            answer = QMessageBox.question(
                self, tr("Carte Deluge détectée"),
                tr("%d carte(s) trouvée(s) :\n\n%s\n\nUtiliser « %s » ?")
                % (len(found), lines, found[0]),
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes)
            if answer == QMessageBox.StandardButton.Yes:
                self._card_changed(str(found[0]))
                return

        # Aucune carte : on ouvre les réglages, qui expliquent quoi faire.
        self.go_to("Settings")
        self.statusBar().showMessage(
            tr("Indiquez l'emplacement de votre carte SD pour commencer."),
            0)

    def _choose_card(self) -> None:
        start = self.ctx.settings.sd_path or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(
            self, tr("Choisir la racine de la carte Deluge"), start)
        if chosen:
            self._card_changed(chosen)

    def _card_changed(self, path: str) -> None:
        """Change de carte : reconstruit ``ctx.sd`` et rafraîchit tout."""
        text = str(path or "").strip()
        if not text:
            return
        self.ctx.settings.sd_path = text
        self.ctx.settings.add_recent(text)
        self.ctx.sd = self.ctx.settings.open_card(Path(text))
        try:
            self.ctx.save()
        except Exception:  # noqa: BLE001
            log.exception("enregistrement des réglages impossible")
        self._match_index_to_card()
        # La table MIDI Follow est propre à chaque carte.
        if self.ctx.link is not None:
            try:
                self.ctx.link.load_follow_map(self.ctx.sd)
            except Exception:  # noqa: BLE001
                log.exception("relecture de MIDI Follow impossible")

        self._safely(self.card_work.refresh_pending)
        self._refresh_header()
        # Les pages déjà créées voient une carte différente : elles doivent
        # toutes être rafraîchies, pas seulement la visible.
        for page in self._pages.values():
            try:
                page.refresh()
            except Exception:  # noqa: BLE001
                log.exception("rafraîchissement après changement de carte")

        if self.ctx.has_card:
            self.statusBar().showMessage(
                tr("Carte : %s — lancez une analyse (Ctrl+R).") % text, 0)
        else:
            self.statusBar().showMessage(
                tr("« %s » ne contient pas d'arborescence Deluge.") % text, 0)

    def _accent_changed(self, colour: str) -> None:
        """Réapplique la feuille de style avec le nouvel accent."""
        app = QApplication.instance()
        if app is None:
            return
        try:
            apply_theme(app, colour)
            # La bascule du niveau est le pad allumé de la façade : elle
            # suit la nouvelle couleur.
            self._level_switch.set_accent(colour)
            self.statusBar().showMessage(
                tr("Couleur d'accent appliquée à la façade."), 4000)
        except Exception:  # noqa: BLE001
            log.exception("application du thème impossible")

    # -- langue ------------------------------------------------------------- #

    def choose_language(self, code: str) -> None:
        """Menu Langue : retient la langue, puis propose de redémarrer.

        Les textes se traduisent à la création des widgets : seule une
        fenêtre neuve change de langue. Le choix est enregistré tout de
        suite — « Plus tard » le garde pour le prochain démarrage — et la
        question est posée **dans les deux langues** : celui qui vient de
        choisir une langue qu'il lit mal doit comprendre ce qui va se
        passer.
        """
        code = i18n.normalize(code)
        self.ctx.settings.language = code
        try:
            self.ctx.save()
        except Exception:  # noqa: BLE001
            log.exception("enregistrement de la langue impossible")
        self._mark_language(code)
        if code == i18n.language():
            return
        affichee = i18n.language()
        lignes = [_RESTART_TEXT[(code, code)]]
        if affichee != code:
            lignes.append(_RESTART_TEXT[(code, affichee)])
        reponse = QMessageBox.question(
            self, untranslated("Langue / Language"), "\n".join(lignes),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        if reponse == QMessageBox.StandardButton.Yes:
            self.restart()
        else:
            self.statusBar().showMessage(
                _LATER_TEXT[affichee], 8000)

    def _mark_language(self, code: str) -> None:
        """Coche la langue retenue dans le menu."""
        for cle, action in self._language_actions.items():
            action.setChecked(cle == code)

    def restart(self) -> bool:
        """Ferme la fenêtre pour qu'elle se rouvre aussitôt.

        La fermeture est l'ordinaire : question si un traitement tourne,
        état et page gardés, fils arrêtés, contexte fermé. ``main.py`` voit
        ``restart_requested`` et reconstruit tout. Rend ``False`` si
        l'utilisateur a préféré laisser finir un traitement.
        """
        self.restart_requested = True
        if not self.close():
            self.restart_requested = False
            return False
        app = QApplication.instance()
        if app is not None:
            app.quit()
        return True

    # -- aide --------------------------------------------------------------- #

    def open_manual(self, ancre: str = "") -> None:
        """Ouvre le manuel — ou le ramène devant —, au chapitre de la page
        affichée, ou sur ``ancre`` si elle est donnée.

        Il s'ouvre dans la langue de l'interface ; sa fenêtre permet d'en
        changer. Un lien du manuel vers une page de l'application ramène la
        fenêtre principale devant, sur cette page.
        """
        from .manuel import FenetreManuel

        if self._manual_window is None:
            self._manual_window = FenetreManuel(i18n.language())
            self._manual_window.navigateRequested.connect(
                lambda cible: self._safely(lambda: self._from_manual(cible)))
            self._manual_window.liveRequested.connect(
                lambda: self._safely(self.open_live_window))
        fenetre = self._manual_window
        if ancre:
            fenetre.aller(ancre)
        else:
            fenetre.montrer_page(self._current_key())
        fenetre.show()
        fenetre.raise_()
        fenetre.activateWindow()

    def _from_manual(self, cible: str) -> None:
        """Un lien du manuel demande une page : elle vient devant."""
        self.go_to(cible)
        self.raise_()
        self.activateWindow()

    def _current_key(self) -> str:
        """La clé de la page affichée (``Samples``…), ou rien."""
        courante = self._stack.currentWidget()
        for cle, page in self._pages.items():
            if page is courante:
                return cle
        return ""

    def _show_shortcuts(self) -> None:
        rows = [
            ("Ctrl+N", tr("Nouveau morceau, dans l'atelier")),
            ("Ctrl+E", tr("Mode simple ou avancé")),
            ("Ctrl+R", tr("Analyser la carte")),
            ("Ctrl+F", tr("Recherche globale")),
            ("Ctrl+G", tr("Générateur")),
            ("Ctrl+,", tr("Réglages")),
            ("Ctrl+O", tr("Choisir la carte")),
            ("Ctrl+I", tr("Envoyer des fichiers au Deluge (ou glissez-les "
                          "sur la fenêtre)")),
            (tr("Ctrl+Maj+D"), tr("Synchroniser avec le Deluge")),
            ("Ctrl+D", tr("Deluge en direct")),
            ("Ctrl+B", tr("Replier la barre latérale")),
            ("Ctrl+Z, Ctrl+Y", tr("Dans l'atelier : défaire, puis refaire "
                                  "le dernier geste")),
            (tr("Espace"), tr("Écouter / arrêter")),
            ("Ctrl+1 … Ctrl+0", tr("Aller à la page correspondante, de "
                                   "l'accueil à la santé de la carte")),
            ("F1", tr("Le manuel, au chapitre de la page affichée")),
            ("Ctrl+Q", tr("Quitter")),
        ]
        body = "".join(
            f"<tr><td style='padding:3px 16px 3px 0;color:#C79A22;"
            f"white-space:nowrap'><b>{key}</b></td>"
            f"<td style='padding:3px 0'>{label}</td></tr>"
            for key, label in rows)
        QMessageBox.information(
            self, tr("Raccourcis clavier"),
            f"<table style='border-collapse:collapse'>{body}</table>")

    # -- signaler un problème, nouvelles versions ------------------------ #

    def open_firmware(self) -> None:
        """Préparer la carte pour une nouvelle version du firmware."""
        from .firmwaredialog import FirmwareDialog

        FirmwareDialog(self.ctx, self).exec()

    def report_problem(self) -> None:
        """Le rapport à relire, puis la page des tickets sur GitHub."""
        from ..config import LOG_PATH
        from .report import ReportDialog

        ReportDialog(self.ctx, LOG_PATH, self).exec()

    def check_for_update(self, manual: bool = True) -> None:
        """Lit la dernière version publiée, dans un fil : le réseau peut
        être lent, ou absent. Rien ne part sans qu'on l'ait demandé — le
        menu, ou la case des réglages."""
        import threading

        from ..core import updates

        self.ctx.settings.last_update_check = datetime.now().isoformat(
            timespec="seconds")
        self._safely(self.ctx.save)
        if manual:
            self.statusBar().showMessage(
                tr("Recherche d'une nouvelle version…"), 5000)

        def lire() -> None:
            self._update_answer = (manual, updates.latest_release())

        threading.Thread(target=lire, name="versions", daemon=True).start()

    def _auto_update_check(self) -> None:
        self._safely(lambda: self.check_for_update(manual=False))

    def _update_known(self, manual: bool, release) -> None:
        from ..core import updates

        if release is not None and updates.is_newer(release.version):
            self._safely(lambda: self._announce_update(release))
        elif manual and release is None:
            QMessageBox.information(
                self, tr("Nouvelle version"),
                tr("La page des versions n'a pas répondu : pas de réseau, "
                   "ou GitHub indisponible. Réessayez plus tard."))
        elif manual:
            QMessageBox.information(
                self, tr("Nouvelle version"),
                tr("Vous avez la dernière version : %s %s.")
                % (APP_NAME, __version__))

    def _announce_update(self, release) -> None:
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices

        self.statusBar().showMessage(
            tr("%s %s est disponible.") % (APP_NAME, release.version), 15000)
        answer = QMessageBox.question(
            self, tr("Nouvelle version"),
            tr("%s %s est disponible (vous avez la %s). Ouvrir sa page de "
               "téléchargement ?") % (APP_NAME, release.version, __version__),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        if answer == QMessageBox.StandardButton.Yes:
            QDesktopServices.openUrl(QUrl(release.url))

    def _show_about(self) -> None:
        QMessageBox.about(
            self, tr("À propos de %s") % APP_NAME,
            f"<h3>{APP_NAME} {__version__}</h3>"
            "<p>%s</p><p>%s</p><p style='color:#7A828F'>%s<br>%s</p>" % (
                tr("Accompagne l'utilisation d'un Synthstrom Deluge : "
                   "gestion de la carte SD, génération de presets et de "
                   "kits, outils de composition."),
                tr("Le manuel s'ouvre par la touche F1, au chapitre de la "
                   "page affichée."),
                tr("Identité visuelle reprise du Guide du Deluge OLED."),
                tr("Aucune écriture sur la carte sans confirmation.")))

    # -- persistance et fermeture ------------------------------------------- #

    def _settings_store(self) -> QSettings:
        """Où l'état de la fenêtre est conservé.

        D'ordinaire le registre de l'utilisateur. Mais si la configuration a
        été déplacée (``NOCTILUCA_CONFIG``), l'état de la fenêtre
        suit : une installation portable emporte tout, et un script d'essai
        n'écrit plus dans le registre réel. J'y ai laissé une fois
        ``rail = narrow`` et ``page = Settings`` : l'utilisateur a démarré
        sur les réglages, navigation repliée en neuf icônes anonymes.

        La première fois sous le nouveau nom, l'état gardé sous l'ancien
        (« Deluge Companion ») est repris.
        """
        from ..config import (APP_ORG, CONFIG_DIR, LEGACY_APP_NAME,
                              LEGACY_APP_ORG, config_impose)

        if config_impose():
            return QSettings(str(CONFIG_DIR / "fenetre.ini"),
                             QSettings.Format.IniFormat)
        store = QSettings(APP_ORG, APP_NAME)
        if not store.allKeys():
            adopt_window_state(QSettings(LEGACY_APP_ORG, LEGACY_APP_NAME),
                               store)
        return store

    def _restore_state(self) -> None:
        """Restaure la géométrie et la dernière page consultée."""
        store = self._settings_store()
        try:
            geometry = store.value(_GEOMETRY_KEY)
            if geometry is not None:
                self.restoreGeometry(geometry)
            state = store.value(_STATE_KEY)
            if state is not None:
                self.restoreState(state)
            if store.value(_RAIL_KEY, "wide") == "narrow":
                self.toggle_rail()
        except Exception as exc:  # noqa: BLE001 - réglages illisibles
            log.debug("géométrie non restaurée : %s", exc)

        wanted = str(store.value(_PAGE_KEY, "Dashboard") or "Dashboard")
        self.go_to(wanted if wanted in self._classes else "Dashboard")

    def _save_state(self) -> None:
        store = self._settings_store()
        try:
            store.setValue(_GEOMETRY_KEY, self.saveGeometry())
            store.setValue(_STATE_KEY, self.saveState())
            store.setValue(_RAIL_KEY, "wide" if self._rail_wide else "narrow")
            current = self._stack.currentWidget()
            for key, page in self._pages.items():
                if page is current:
                    store.setValue(_PAGE_KEY, key)
                    break
            store.sync()
        except Exception as exc:  # noqa: BLE001
            log.debug("géométrie non enregistrée : %s", exc)

    def closeEvent(self, event) -> None:  # noqa: N802 - API Qt
        """Arrête les travaux en cours avant de quitter.

        **Indispensable** : un ``QThread`` encore en train de tourner quand
        l'interpréteur se termine fait planter le processus. Si un travail est
        en cours, on demande confirmation avant de l'interrompre.
        """
        busy = tasks.active_count()
        if busy:
            texte = (tr("%d traitement(s) en cours.\n\nRedémarrer maintenant "
                        "les interrompra. Continuer ?")
                     if self.restart_requested else
                     tr("%d traitement(s) en cours.\n\nQuitter maintenant les "
                        "interrompra. Continuer ?"))
            answer = QMessageBox.question(
                self, tr("Un traitement est en cours"), texte % busy,
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return

        self._ticker.stop()
        self._link_timer.stop()
        # Le morceau de l'atelier, tel qu'on le laisse : il revient au
        # prochain lancement — après un changement de langue aussi.
        atelier_page = self._pages.get("Atelier")
        if atelier_page is not None and getattr(atelier_page, "_built",
                                                False):
            atelier_page.save_draft()
        if self._live_window is not None:
            self._live_window.close()
        if self._manual_window is not None:
            self._manual_window.close()
        self._save_state()
        stubborn = tasks.stop_all(4000)
        if stubborn:
            log.warning("%d fil(s) interrompu(s) de force", stubborn)
        try:
            self.ctx.close()
        except Exception:  # noqa: BLE001
            log.exception("fermeture du contexte en échec")
        super().closeEvent(event)
