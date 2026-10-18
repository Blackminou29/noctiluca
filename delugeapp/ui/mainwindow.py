# -*- coding: utf-8 -*-
"""Fenêtre principale : assemble les neuf pages.

Barre latérale à gauche, en-tête en haut, pages au centre, barre d'état en
bas. Les pages sont **créées au premier affichage** : en construire neuf au
démarrage allongerait le lancement sans que l'utilisateur en voie plus d'une.

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
from pathlib import Path

from PyQt6.QtCore import QSettings, Qt, QTimer
from PyQt6.QtGui import QAction, QKeySequence
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
from ..config import APP_NAME, AppContext
from ..core import sdcard as sdmod
from . import icons, tasks
from .theme import (
    GOLD,
    GREY,
    PAD_GREEN,
    apply_theme,
    lit_fill,
    page_color,
)
from .widgets.chrome import LedButton, LedStrip, NavPad, OledDisplay, Wordmark
from .widgets.common import BusyBar, SearchBar, glow, human_size

log = logging.getLogger(__name__)

#: Largeurs de la barre latérale, dépliée et repliée. 212 px : le pad, le
#: libellé en gras de la page choisie (« Tableau de bord ») et le chiffre de
#: son raccourci tiennent sans troncature.
RAIL_WIDE = 212
RAIL_NARROW = 64

#: Hauteur de la barre du haut : celle de l'écran OLED et de ses marges.
TOPBAR_HEIGHT = 56

#: Largeurs de fenêtre sous lesquelles la barre du haut se resserre : la
#: recherche et l'écran rétrécissent, « COMPANION » et l'étiquette du
#: Deluge s'effacent. Mesuré : à 980 px, tout tient sans que les menus
#: passent dans le débordement.
TOPBAR_MEDIUM = 1360
TOPBAR_NARROW = 1180

#: Clés de persistance de la géométrie et de la page courante.
_GEOMETRY_KEY = "window/geometry"
_STATE_KEY = "window/state"
_PAGE_KEY = "window/page"
_RAIL_KEY = "window/rail"


def _page_classes():
    """Les neuf pages, dans l'ordre de la barre latérale.

    Importées ici et non au niveau du module : chaque page tire ses propres
    dépendances, et les charger toutes à l'import ralentirait le démarrage
    sans raison.
    """
    from .pages.dashboard import DashboardPage
    from .pages.generator import GeneratorPage
    from .pages.health import HealthPage
    from .pages.kits import KitsPage
    from .pages.samples import SamplesPage
    from .pages.settings import SettingsPage
    from .pages.songs import SongsPage
    from .pages.synths import SynthsPage
    from .pages.toolbox import ToolboxPage

    return (DashboardPage, SamplesPage, SynthsPage, KitsPage, SongsPage,
            GeneratorPage, ToolboxPage, HealthPage, SettingsPage)


def _short_name(cls) -> str:
    """``DashboardPage`` -> ``Dashboard`` : la clé de navigation."""
    name = cls.__name__
    return name[:-4] if name.endswith("Page") else name


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
        #: Dernier tempo de la machine transmis aux pages (arrondi).
        self._tempo_suivi: int | None = None

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
        row.setSpacing(8)

        self._wordmark = Wordmark(host)
        row.addWidget(self._wordmark)
        row.addSpacing(6)
        row.addWidget(self._menubar, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addStretch(1)

        # L'écran du Deluge : la carte ouverte, et les messages de la barre
        # d'état en surimpression. Un clic mène aux réglages de la carte.
        self._card_button = OledDisplay(host)
        self._card_button.setToolTip(
            "Emplacement de la carte — cliquez pour le changer")
        self._card_button.clicked.connect(
            lambda: self.go_to("Settings"))
        row.addWidget(self._card_button)

        # Pastille du Deluge : éteinte tant qu'il n'est pas là, or quand il
        # est détecté, verte et rayonnante dès qu'il est connecté. C'est la
        # première chose qu'on regarde quand on vient de brancher un câble.
        self._deluge_chip = LedButton("midi", "Deluge", host)
        self._deluge_chip.clicked.connect(self.guard_deluge_chip)
        row.addWidget(self._deluge_chip)

        self._search = SearchBar("Rechercher partout…")
        self._search.setFixedWidth(240)
        self._search.searchChanged.connect(self._global_search)
        row.addWidget(self._search)

        self._scan_button = QPushButton("Analyser", host)
        self._scan_button.setObjectName("Primary")
        self._scan_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._scan_button.setToolTip("Relire la carte  (Ctrl+R)")
        self._scan_button.clicked.connect(self.scan_card)
        row.addWidget(self._scan_button)
        self._light_scan_button(self.ctx.settings.theme_accent or GOLD)

        # La touche PLAY de la machine : ronde, verte et rayonnante pendant
        # une lecture.
        self._play_button = LedButton("play", "", host)
        self._play_button.setToolTip("Écouter ou arrêter  (Espace)")
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

    def _light_scan_button(self, accent: str) -> None:
        """« Analyser » est le pad allumé de la façade, à sa couleur."""
        encre = lit_fill(accent)[2]
        self._scan_button.setIcon(icons.icon("refresh", encre, 16))
        glow(self._scan_button, accent, 22, 0.45)

    def _fit_header(self, largeur: int) -> None:
        """Resserre la barre du haut quand la fenêtre rétrécit.

        Mesuré : à 980 px, la barre complète demandait 1 100 px et ses menus
        passaient dans un débordement « » ». L'écran et la recherche
        rétrécissent, « COMPANION » et l'étiquette « DELUGE » s'effacent ;
        tout revient en élargissant.
        """
        try:
            if largeur >= TOPBAR_MEDIUM:
                ecran, recherche, compact, legende = 330, 240, False, True
            elif largeur >= TOPBAR_NARROW:
                ecran, recherche, compact, legende = 260, 200, False, False
            else:
                ecran, recherche, compact, legende = 196, 150, True, False
            self._card_button.set_preferred_width(ecran)
            self._search.setFixedWidth(recherche)
            self._wordmark.set_compact(compact)
            self._deluge_chip.set_caption_visible(legende)
        except Exception as exc:       # noqa: BLE001 - un ajustement ne casse rien
            log.debug("barre du haut non ajustée : %s", exc)

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
            teinte, etat = GOLD, "détecté — cliquez pour connecter"
        else:
            teinte, etat = GREY, "absent"
        self._deluge_chip.set_state(teinte, connecte or detecte)
        self._deluge_chip.setToolTip("Deluge %s" % etat)

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
                        "Deluge branché : " + lien.state().summary(), 8000)
            else:
                self.statusBar().showMessage(
                    "Deluge branché. Connectez-le dans les réglages.", 8000)
        elif connecte and not present:
            # Débranché pendant l'utilisation : on referme proprement, sinon
            # le port reste ouvert sur un appareil qui n'existe plus.
            lien.disconnect()
            self.statusBar().showMessage("Deluge débranché.", 6000)

        self._deluge_seen = present
        self._refresh_deluge_chip()

    # -- liaison vivante ---------------------------------------------------- #

    @staticmethod
    def _chip_details(lien) -> str:
        """Infobulle de la pastille quand la machine est connectée."""
        etat = lien.state()
        morceaux = ["connecté"]
        if etat.firmware:
            morceaux.append("firmware %s" % etat.firmware)
        if etat.tempo is not None:
            tempo = ("%.1f" % etat.tempo).replace(".", ",")
            morceaux.append("%s BPM%s" % (tempo,
                                          " ▶" if etat.running else ""))
        morceaux.append("cliquez pour le voir en direct")
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
                "Deluge identifié : firmware %s." % lien.identity.version,
                6000)
            reglages = self._pages.get("Settings")
            if reglages is not None and hasattr(reglages, "_refresh_midi"):
                self._safely(reglages._refresh_midi)
        if "tempo" in evenements and lien.tempo is not None \
                and getattr(self.ctx.settings, "midi_follow_tempo", True):
            self._follow_tempo(lien.tempo)
        if evenements & {"identity", "ping", "tempo", "transport"}:
            self._refresh_deluge_chip()

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
                "Tempo du Deluge : %d BPM, repris par les outils." % arrondi,
                4000)

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
        column.setContentsMargins(4, 12, 8, 10)
        column.setSpacing(2)

        for index, (key, cls) in enumerate(self._classes.items(), 1):
            # Chaque page est un pad de sa couleur : éteint, il la montre
            # en veilleuse ; choisi, il s'allume. La colonne devient une
            # rangée de pads de la machine, et l'on repère une destination à
            # la teinte avant même d'avoir lu l'étiquette. Le chiffre est
            # celui du raccourci.
            button = NavPad(cls.TITLE, cls.ICON, page_color(key), index,
                            self._rail)
            button.setToolTip(f"{cls.TITLE}  (Ctrl+{index})")
            button.setProperty("navColor", page_color(key))
            button.clicked.connect(
                lambda _c=False, k=key: self.go_to(k))
            column.addWidget(button)
            self._buttons[key] = button

        column.addStretch(1)

        self._fold_button = QPushButton("  Replier", self._rail)
        self._fold_button.setObjectName("NavButton")
        self._fold_button.setIcon(icons.icon("chevron-left", GREY, 14))
        self._fold_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._fold_button.setToolTip(
            "Réduire la colonne à ses pads, pour donner la place aux "
            "listes  (Ctrl+B)")
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
            button.setText(f"  {cls.TITLE}" if self._rail_wide else "")
        self._fold_button.setText("  Replier" if self._rail_wide else "")
        self._fold_button.setIcon(
            icons.icon("chevron-left" if self._rail_wide else "chevron-right",
                       GREY, 14))
        self._fold_button.setToolTip(
            "Réduire la colonne à ses pads, pour donner la place aux "
            "listes  (Ctrl+B)" if self._rail_wide else
            "Déplier la colonne et ses étiquettes  (Ctrl+B)")

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
        bar.showMessage("Prêt.")

    def _tick(self) -> None:
        """Met à jour les indicateurs de la barre d'état."""
        try:
            player = self.ctx.player
            playing = bool(player is not None and player.is_playing)
            self._playing.setText("● lecture" if playing else "")
            self._playing.setStyleSheet(
                f"color: {PAD_GREEN};" if playing else "")
            self._play_button.set_icon_name("stop" if playing else "play")
            self._play_button.set_state(PAD_GREEN if playing else GREY,
                                        playing)

            busy = tasks.active_count()
            self._progress.setVisible(busy > 0)
            if busy > 0:
                self._progress.set_busy(True)

            self._poll_midi()
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
        for cle, nom in (("samples", "sons"), ("synths", "presets"),
                         ("kits", "kits"), ("songs", "morceaux")):
            valeur = int((stats or {}).get(cle, 0) or 0)
            if valeur:
                morceaux.append(f"{valeur:,} {nom}".replace(",", " "))
        return " · ".join(morceaux)

    def _refresh_header(self) -> None:
        """Met à jour l'écran de la carte et l'espace libre.

        Le texte du bouton garde le chemin complet, comme avant ; l'écran
        en montre le nom en grand, et le contenu de la carte en petit.
        """
        path = self.ctx.settings.sd_path
        nom = Path(path).name if path else ""
        if self.ctx.has_card:
            self._card_button.setText(f"  {path}")
            contenu = self._card_counts()
            etiquette = ("CARTE · " + contenu) if contenu else (
                "CARTE · pas encore analysée")
            self._card_button.set_display(etiquette, (nom or path).upper(),
                                          "hi")
            self._card_button.setToolTip(
                f"{path}\n\nCliquez pour changer de carte.")
        elif path:
            self._card_button.setText(f"  {path}  (invalide)")
            self._card_button.set_display("CARTE INTROUVABLE",
                                          (nom or path).upper(), "error")
            self._card_button.setToolTip(
                f"{path}\n\nCe dossier ne contient pas d'arborescence "
                f"Deluge. Cliquez pour en choisir un autre.")
        else:
            self._card_button.setText("  Aucune carte — cliquez pour choisir")
            self._card_button.set_display("AUCUNE CARTE",
                                          "CLIQUEZ POUR CHOISIR", "warn")
            self._card_button.setToolTip(
                "Aucune carte choisie. Cliquez pour indiquer où elle est.")

        free = total = 0
        if self.ctx.sd is not None:
            try:
                free, total = self.ctx.sd.free_space()
            except Exception:  # noqa: BLE001
                free = total = 0
        if not total:
            self._space.setText("")
        elif self.ctx.sd.is_volume:
            self._space.setText(f"{human_size(free)} libres")
        else:
            self._space.setText(f"{human_size(free)} libres sur le disque")

        # Ne pas proposer ce qui ne peut pas marcher : sans carte, « Analyser »
        # ne pouvait que répondre par un avertissement. Un bouton éteint qui
        # dit pourquoi vaut mieux qu'un bouton vif qui refuse.
        prete = bool(self.ctx.has_card)
        self._scan_button.setEnabled(prete)
        self._scan_button.setToolTip(
            "Relire la carte et mettre l'index à jour  (Ctrl+R)" if prete
            else "Indiquez d'abord l'emplacement de la carte")

    # -- menus et raccourcis ------------------------------------------------ #

    def _build_menus(self) -> None:
        bar = self.menuBar()

        file_menu = bar.addMenu("&Fichier")
        self._add_action(file_menu, "Choisir la carte…", self._choose_card,
                         "Ctrl+O")
        self._add_action(file_menu, "Analyser la carte", self.scan_card,
                         "Ctrl+R")
        self._add_action(file_menu, "Sauvegarder la carte",
                         lambda: self.go_to("Health"))
        file_menu.addSeparator()
        self._add_action(file_menu, "Quitter", self.close, "Ctrl+Q")

        edit_menu = bar.addMenu("&Édition")
        self._add_action(edit_menu, "Rechercher", self._focus_search, "Ctrl+F")
        self._add_action(edit_menu, "Réglages…",
                         lambda: self.go_to("Settings"), "Ctrl+,")

        tools_menu = bar.addMenu("&Outils")
        self._add_action(tools_menu, "Générateur de presets",
                         lambda: self.go_to("Generator"), "Ctrl+G")
        self._add_action(tools_menu, "Boîte à outils",
                         lambda: self.go_to("Toolbox"))
        self._add_action(tools_menu, "Santé de la carte",
                         lambda: self.go_to("Health"))
        self._add_action(tools_menu, "Deluge en direct",
                         self.open_live_window, "Ctrl+D")
        tools_menu.addSeparator()
        self._add_action(tools_menu, "Replier la barre latérale",
                         self.toggle_rail, "Ctrl+B")

        help_menu = bar.addMenu("&Aide")
        self._add_action(help_menu, "Raccourcis clavier", self._show_shortcuts,
                         "F1")
        self._add_action(help_menu, "À propos", self._show_about)

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
                "Action impossible : voir le journal.", 8000)

    def _build_shortcuts(self) -> None:
        """``Ctrl+1`` à ``Ctrl+9`` pour les pages, ``Espace`` pour l'écoute."""
        for index, key in enumerate(self._classes, 1):
            action = QAction(self)
            action.setShortcut(QKeySequence(f"Ctrl+{index}"))
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
                f"La page « {cls.TITLE} » n'a pas pu être ouverte.", 8000)
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
            "cardModified": self.refresh_all,
            "presetSaved": lambda _rel: self.refresh_all(),
            "songWritten": lambda _rel: self.refresh_all(),
            "cardChanged": self._card_changed,
            "accentChanged": self._accent_changed,
            "resetIndexRequested": self.refresh_all,
            "openInGenerator": self._open_in_generator,
            "liveRequested": self.open_live_window,
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
            self.statusBar().showMessage(f"Preset illisible : {rel}", 8000)
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

    # -- actions ------------------------------------------------------------ #

    def scan_card(self) -> None:
        """Lance l'analyse depuis le tableau de bord, qui la porte déjà."""
        self.go_to("Dashboard")
        page = self._pages.get("Dashboard")
        starter = getattr(page, "_start_scan", None)
        if callable(starter):
            starter()

    def toggle_play(self) -> None:
        """Arrête la lecture en cours, ou relance l'écoute de la page."""
        player = self.ctx.player
        if player is None:
            return
        try:
            if player.is_playing:
                player.stop()
                self.statusBar().showMessage("Lecture arrêtée.", 4000)
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
                    "Nouvelle carte : lancez « Analyser la carte » pour "
                    "l'indexer.", 0)
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
                f"Carte : {self.ctx.settings.sd_path}", 6000)
            self._match_index_to_card()
            self._update_index_on_start()
            return

        found = []
        try:
            found = sdmod.detect_sd_cards()
        except Exception as exc:  # noqa: BLE001
            log.debug("détection impossible : %s", exc)

        if found:
            lines = "\n".join(f"  •  {p}" for p in found[:6])
            answer = QMessageBox.question(
                self, "Carte Deluge détectée",
                f"{len(found)} carte(s) trouvée(s) :\n\n{lines}\n\n"
                f"Utiliser « {found[0]} » ?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes)
            if answer == QMessageBox.StandardButton.Yes:
                self._card_changed(str(found[0]))
                return

        # Aucune carte : on ouvre les réglages, qui expliquent quoi faire.
        self.go_to("Settings")
        self.statusBar().showMessage(
            "Indiquez l'emplacement de votre carte SD pour commencer.",
            0)

    def _choose_card(self) -> None:
        start = self.ctx.settings.sd_path or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(
            self, "Choisir la racine de la carte Deluge", start)
        if chosen:
            self._card_changed(chosen)

    def _card_changed(self, path: str) -> None:
        """Change de carte : reconstruit ``ctx.sd`` et rafraîchit tout."""
        text = str(path or "").strip()
        if not text:
            return
        self.ctx.settings.sd_path = text
        self.ctx.settings.add_recent(text)
        self.ctx.sd = sdmod.SDCard(Path(text))
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
                f"Carte : {text} — lancez une analyse (Ctrl+R).", 0)
        else:
            self.statusBar().showMessage(
                f"« {text} » ne contient pas d'arborescence Deluge.", 0)

    def _accent_changed(self, colour: str) -> None:
        """Réapplique la feuille de style avec le nouvel accent."""
        app = QApplication.instance()
        if app is None:
            return
        try:
            apply_theme(app, colour)
            # Le bouton « Analyser » est le pad allumé de la façade : son
            # icône et son halo suivent la nouvelle couleur.
            self._light_scan_button(colour)
            self.statusBar().showMessage(
                "Couleur d'accent appliquée à la façade.", 4000)
        except Exception:  # noqa: BLE001
            log.exception("application du thème impossible")

    # -- aide --------------------------------------------------------------- #

    def _show_shortcuts(self) -> None:
        rows = [
            ("Ctrl+R", "Analyser la carte"),
            ("Ctrl+F", "Recherche globale"),
            ("Ctrl+G", "Générateur"),
            ("Ctrl+,", "Réglages"),
            ("Ctrl+O", "Choisir la carte"),
            ("Ctrl+B", "Replier la barre latérale"),
            ("Espace", "Écouter / arrêter"),
            ("Ctrl+1 … Ctrl+9", "Aller à la page correspondante"),
            ("F1", "Cette fenêtre"),
            ("Ctrl+Q", "Quitter"),
        ]
        body = "".join(
            f"<tr><td style='padding:3px 16px 3px 0;color:#C79A22;"
            f"white-space:nowrap'><b>{key}</b></td>"
            f"<td style='padding:3px 0'>{label}</td></tr>"
            for key, label in rows)
        QMessageBox.information(
            self, "Raccourcis clavier",
            f"<table style='border-collapse:collapse'>{body}</table>")

    def _show_about(self) -> None:
        QMessageBox.about(
            self, f"À propos de {APP_NAME}",
            f"<h3>{APP_NAME} {__version__}</h3>"
            f"<p>Accompagne l'utilisation d'un Synthstrom Deluge : gestion "
            f"de la carte SD, génération de presets et de kits, outils de "
            f"composition.</p>"
            f"<p style='color:#7A828F'>Identité visuelle reprise du Guide du "
            f"Deluge OLED.<br>"
            f"Aucune écriture sur la carte sans confirmation.</p>")

    # -- persistance et fermeture ------------------------------------------- #

    def _settings_store(self) -> QSettings:
        """Où l'état de la fenêtre est conservé.

        D'ordinaire le registre de l'utilisateur. Mais si la configuration a
        été déplacée (``DELUGE_COMPANION_CONFIG``), l'état de la fenêtre
        suit : une installation portable emporte tout, et un script d'essai
        n'écrit plus dans le registre réel. J'y ai laissé une fois
        ``rail = narrow`` et ``page = Settings`` : l'utilisateur a démarré
        sur les réglages, navigation repliée en neuf icônes anonymes.
        """
        from ..config import APP_ORG, CONFIG_ENV, CONFIG_DIR
        import os

        if (os.environ.get(CONFIG_ENV) or "").strip():
            return QSettings(str(CONFIG_DIR / "fenetre.ini"),
                             QSettings.Format.IniFormat)
        return QSettings(APP_ORG, APP_NAME)

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
            answer = QMessageBox.question(
                self, "Un traitement est en cours",
                f"{busy} traitement(s) en cours.\n\n"
                f"Quitter maintenant les interrompra. Continuer ?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return

        self._ticker.stop()
        self._link_timer.stop()
        if self._live_window is not None:
            self._live_window.close()
        self._save_state()
        stubborn = tasks.stop_all(4000)
        if stubborn:
            log.warning("%d fil(s) interrompu(s) de force", stubborn)
        try:
            self.ctx.close()
        except Exception:  # noqa: BLE001
            log.exception("fermeture du contexte en échec")
        super().closeEvent(event)
