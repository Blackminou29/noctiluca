#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Point d'entrée de Noctiluca.

Lance l'application : journal, réglages, index, carte, lecteur audio, thème,
puis la fenêtre principale.

Deux précautions valent d'être signalées :

* **un hook d'exception** remplace celui de Python. Sans lui, une erreur
  imprévue dans un gestionnaire Qt disparaît sur la sortie d'erreur — que
  personne ne regarde quand l'application est lancée depuis une icône. Ici
  elle part dans le journal **et** s'affiche dans une boîte lisible.
* **le démarrage ne dépend pas de la carte.** Un index illisible, un
  périphérique audio absent, une carte débranchée : chacun est rattrapé, et
  l'application s'ouvre quand même (SPEC §6.1).

Usage :

    python main.py [--sd CHEMIN] [--reset-db] [--no-splash] [--version]

et, pour vérifier un paquet construit (:mod:`delugeapp.autotest`) :

    Noctiluca --self-test [RAPPORT]
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import sys
import traceback
from pathlib import Path

#: Taille et rotation du journal, conformément à la SPEC §5.7.
LOG_MAX_BYTES = 1024 * 1024
LOG_BACKUPS = 3


def _setup_logging(verbose: bool = False) -> Path | None:
    """Installe le journal tournant et la sortie console.

    Retourne le chemin du fichier, ou ``None`` s'il n'a pas pu être ouvert —
    cas d'un dossier en lecture seule, qui ne doit pas empêcher le
    démarrage.
    """
    from delugeapp.config import ensure_config_dir

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S")

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(logging.DEBUG if verbose else logging.WARNING)
    console.setFormatter(fmt)
    root.addHandler(console)

    try:
        path = ensure_config_dir() / "app.log"
        handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS,
            encoding="utf-8")
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(fmt)
        root.addHandler(handler)
        return path
    except OSError as exc:
        root.warning("journal non disponible : %s", exc)
        return None


#: Le traducteur de Qt installé, à retirer quand la langue change.
_qt_translator = None


def _translate_qt(app, language: str = "fr"):
    """Les boutons standard de Qt dans la langue de l'interface.

    En français, « Oui », « Non », « Annuler » : les questions posées par
    ``QMessageBox`` affichaient « Yes » et « No » au milieu d'une
    application en français. La traduction est livrée avec PyQt6 ; il
    suffisait de la charger. En anglais, Qt parle déjà la langue : le
    traducteur français est retiré, sinon il resterait d'une fenêtre à
    l'autre.

    Rend le traducteur installé, ou ``None``.
    """
    global _qt_translator
    try:
        from PyQt6.QtCore import QLibraryInfo, QLocale, QTranslator

        if _qt_translator is not None:
            app.removeTranslator(_qt_translator)
            _qt_translator = None
        if language != "fr":
            return None
        traducteur = QTranslator(app)
        dossier = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        if (traducteur.load(QLocale(QLocale.Language.French), "qtbase", "_",
                            dossier)
                and app.installTranslator(traducteur)):
            _qt_translator = traducteur
            return traducteur
    except Exception:  # noqa: BLE001 - une traduction absente ne bloque rien
        logging.getLogger("delugeapp").debug("traduction de Qt indisponible")
    return None


def _choose_language() -> str:
    """Prend la langue des réglages, avant même la ligne de commande : son
    aide parle ainsi la langue choisie. Rend le code retenu."""
    from delugeapp import i18n

    try:
        from delugeapp.config import load_settings

        return i18n.set_language(load_settings().language)
    except Exception:  # noqa: BLE001 - des réglages illisibles : le défaut
        return i18n.set_language(i18n.FIRST_RUN)


def _log_reprises(log: logging.Logger) -> None:
    """Inscrit au journal les dossiers repris de l'ancien nom.

    Le renommage a lieu à l'import de ``delugeapp.config``, avant que le
    journal ne soit ouvert : il est raconté ici.
    """
    from delugeapp.config import REPRISES

    for ancien, nouveau, fait in REPRISES:
        if fait:
            log.info("dossier repris de l'ancien nom : %s -> %s",
                     ancien, nouveau)
        else:
            log.warning("dossier de l'ancien nom gardé tel quel, renommage "
                        "impossible (retenté au prochain lancement) : %s",
                        ancien)


def _install_excepthook() -> None:
    """Détourne les exceptions non rattrapées vers le journal et l'écran."""
    from delugeapp.i18n import tr

    log = logging.getLogger("delugeapp")

    def handler(kind, value, tb) -> None:
        if issubclass(kind, KeyboardInterrupt):
            sys.__excepthook__(kind, value, tb)
            return
        log.critical("exception non rattrapée",
                     exc_info=(kind, value, tb))
        detail = "".join(traceback.format_exception(kind, value, tb))
        try:
            from PyQt6.QtWidgets import QApplication, QMessageBox

            if QApplication.instance() is None:
                return
            box = QMessageBox()
            box.setIcon(QMessageBox.Icon.Critical)
            box.setWindowTitle(tr("Erreur inattendue"))
            box.setText(tr(
                "Une erreur inattendue est survenue.\n\n"
                "L'application reste ouverte, mais l'action en cours a "
                "échoué. Le détail est dans le journal."))
            box.setInformativeText(f"{kind.__name__} : {value}")
            box.setDetailedText(detail)
            signaler = box.addButton(tr("Signaler ce problème…"),
                                     QMessageBox.ButtonRole.ActionRole)
            signaler.setToolTip(tr("Ouvre le rapport, détail de l'erreur "
                                   "compris, à relire avant tout envoi"))
            box.setDefaultButton(box.addButton(QMessageBox.StandardButton.Ok))
            box.exec()
            if box.clickedButton() is signaler:
                _report_error(detail)
        except Exception:  # noqa: BLE001 - on ne fait pas d'erreur sur l'erreur
            log.exception("affichage de l'erreur impossible")

    sys.excepthook = handler


def _report_error(detail: str) -> None:
    """Le rapport d'Aide ▸ Signaler un problème, l'erreur déjà dedans."""
    from PyQt6.QtWidgets import QApplication

    from delugeapp.config import LOG_PATH
    from delugeapp.ui.report import ReportDialog

    fenetre = next((w for w in QApplication.topLevelWidgets()
                    if getattr(w, "ctx", None) is not None), None)
    ReportDialog(getattr(fenetre, "ctx", None), LOG_PATH, fenetre,
                 detail=detail).exec()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    from delugeapp.i18n import tr

    parser = argparse.ArgumentParser(
        prog="main.py",
        description=tr("Noctiluca — gestion de carte SD, génération de "
                       "presets et outils de composition pour Synthstrom "
                       "Deluge."))
    parser.add_argument("--sd", metavar=tr("CHEMIN"),
                        help=tr("emplacement de la carte SD à utiliser"))
    parser.add_argument("--reset-db", action="store_true",
                        help=tr("vide l'index avant de démarrer"))
    parser.add_argument("--no-splash", action="store_true",
                        help=tr("ne pas afficher l'écran de démarrage"))
    parser.add_argument("--verbose", action="store_true",
                        help=tr("journal détaillé sur la console"))
    parser.add_argument("--version", action="store_true",
                        help=tr("affiche la version et quitte"))
    return parser.parse_args(argv)


def _build_context(args: argparse.Namespace):
    """Construit l'``AppContext``, en rattrapant chaque défaillance.

    La langue des réglages est prise ici, avant que la fenêtre ne se
    construise : c'est ainsi qu'un changement de langue s'applique au
    redémarrage de la fenêtre.
    """
    from delugeapp import i18n
    from delugeapp.config import (CONFIG_DIR, DB_PATH, AppContext,
                                  load_settings, save_settings)
    from delugeapp.core import cardsync
    from delugeapp.core.audio_out import Player
    from delugeapp.core.db import Library
    from delugeapp.core.sdcard import SDCard

    log = logging.getLogger("delugeapp")
    settings = load_settings()
    i18n.set_language(settings.language)

    # Le dossier de synchronisation de la copie de travail porte encore
    # l'ancien nom chez qui l'a créée avant. (Celui de la sauvegarde, qu'on
    # n'écrit pas d'office, attend sa prochaine mise à jour.)
    if cardsync.adopt_legacy_meta(settings.work_path()):
        log.info("dossier de synchronisation repris dans %s",
                 settings.work_path())

    if args.sd:
        settings.sd_path = str(Path(args.sd).expanduser())
        settings.add_recent(settings.sd_path)

    # Un dossier de travail qui n'était qu'une copie de la carte devient ce
    # qu'il est : sa sauvegarde, qu'on lit sans l'écrire.
    if settings.adopt_card_roles():
        log.info("« %s » reconnu comme sauvegarde de la carte",
                 settings.card_backup)
        try:
            save_settings(settings)
        except Exception:  # noqa: BLE001
            log.exception("réglages non enregistrés")

    # L'index : son absence ne doit pas empêcher le démarrage, mais sans lui
    # les pages n'ont rien à montrer, donc on le signale clairement.
    try:
        library = Library(DB_PATH)
        if args.reset_db:
            library.clear()
            library.vacuum()
            log.info("index vidé à la demande")
    except Exception:
        log.exception("index inutilisable")
        raise SystemExit(i18n.tr(
            "L'index de la carte n'a pas pu être ouvert. "
            "Vérifiez les droits sur {dossier}.").format(dossier=CONFIG_DIR))

    card = None
    if settings.sd_path.strip():
        try:
            card = settings.open_card(Path(settings.sd_path))
        except Exception:  # noqa: BLE001 - chemin absurde
            log.exception("carte SD inutilisable : %s", settings.sd_path)

    try:
        player = Player()
        player.set_volume(settings.preview_volume)
        if settings.audio_device:
            player.set_device(settings.audio_device)
        log.info("sortie audio : %s", player.backend)
    except Exception:  # noqa: BLE001 - pas d'audio : l'application marche
        log.exception("sortie audio indisponible")
        player = None

    return AppContext(settings=settings, sd=card, lib=library, player=player)


#: Taille logique de l'écran de démarrage.
SPLASH_SIZE = (520, 300)


def _splash(app):
    """Écran de démarrage : la couverture du guide, en petit.

    Le treillis en haut, puis la typographie du plat : « POUR SYNTHSTROM
    DELUGE » en capitales espacées, « NOCTILUCA » en magenta et son filet.
    Tracé à la densité de l'écran, pour rester net sur un affichage agrandi.
    """
    from PyQt6.QtCore import QPointF, QRectF
    from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPixmap
    from PyQt6.QtWidgets import QSplashScreen

    from delugeapp import __version__
    from delugeapp.i18n import tr
    from delugeapp.ui import art, icons
    from delugeapp.ui.theme import FONT_UI, PAD_MAGENTA, TEXT_SOFT

    largeur, hauteur = SPLASH_SIZE
    try:
        ratio = max(1.0, float(app.devicePixelRatio()))
    except Exception:  # noqa: BLE001 - écran inconnu
        ratio = 1.0
    pixmap = QPixmap(int(largeur * ratio), int(hauteur * ratio))
    pixmap.setDevicePixelRatio(ratio)
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        fond = QLinearGradient(QPointF(0, 0), QPointF(0, hauteur))
        fond.setColorAt(0.0, QColor("#0B0D11"))
        fond.setColorAt(1.0, QColor("#171B23"))
        painter.fillRect(QRectF(0, 0, largeur, hauteur), fond)

        dessin = art.circuit(largeur, 150, PAD_MAGENTA, art.seed_of("Deluge"),
                             ratio, density=0.5, fade=(0.0, 0.0))
        painter.setOpacity(0.9)
        painter.drawPixmap(QPointF(0, 6), dessin)
        painter.setOpacity(1.0)

        # Le pied du dessin s'efface dans le fond, comme sur la couverture.
        voile = QLinearGradient(QPointF(0, 110), QPointF(0, 160))
        voile.setColorAt(0.0, QColor(11, 13, 17, 0))
        voile.setColorAt(1.0, QColor(13, 16, 21, 255))
        painter.fillRect(QRectF(0, 110, largeur, 50), voile)

        painter.drawPixmap(QRectF(34, 176, 76, 76).toRect(),
                           icons.app_icon(152).pixmap(152, 152))

        def police(points, poids, espacement=0.0):
            f = QFont(FONT_UI)
            f.setPointSizeF(points)
            f.setWeight(QFont.Weight(poids))
            if espacement:
                f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing,
                                   espacement)
            return f

        x = 132.0
        painter.setFont(police(7.5, 600, 4.0))
        painter.setPen(QColor(TEXT_SOFT))
        painter.drawText(QPointF(x, 188), tr("POUR SYNTHSTROM DELUGE"))
        painter.setFont(police(27, 800, 1.5))
        painter.setPen(QColor(PAD_MAGENTA))
        painter.drawText(QPointF(x, 238), "NOCTILUCA")
        painter.fillRect(QRectF(x, 258, 92, 2.5), QColor(PAD_MAGENTA))
        painter.setFont(police(7, 700, 3.0))
        painter.drawText(QPointF(x, 280), f"VERSION {__version__}")
    finally:
        painter.end()

    splash = QSplashScreen(pixmap)
    splash.show()
    app.processEvents()
    return splash


def _dispose(window) -> None:
    """Détruit une fenêtre fermée avant d'en bâtir une autre : ses minuteries
    et ses pages ne doivent pas survivre à côté de la nouvelle."""
    from PyQt6.QtCore import QCoreApplication, QEvent

    try:
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None,
                                          QEvent.Type.DeferredDelete.value)
    except RuntimeError:
        pass                            # déjà détruite par Qt


#: Le canal local par lequel une fenêtre qu'on relance appelle la première
#: (``QLocalServer`` : un tube nommé sous Windows).
INSTANCE_NAME = "Noctiluca-instance"


def _already_running(name: str = INSTANCE_NAME) -> bool:
    """Une fenêtre est-elle déjà ouverte ? Si oui, elle est priée de se
    montrer, et celle qu'on lance n'a plus qu'à s'effacer.

    Deux fenêtres se disputeraient le Deluge branché : chacune
    synchroniserait sa carte, et chaque réponse de la machine arrive aux
    deux — vu le 22 octobre 2026, sous Windows 11, plusieurs programmes
    ouvrent ses ports en même temps.
    """
    from PyQt6.QtNetwork import QLocalSocket

    socket = QLocalSocket()
    socket.connectToServer(name)
    if not socket.waitForConnected(300):
        return False
    socket.write(b"montrer\n")
    socket.flush()
    socket.waitForBytesWritten(300)
    socket.disconnectFromServer()
    return True


class _Instance:
    """L'oreille de la fenêtre ouverte : un second lancement la montre."""

    def __init__(self, name: str = INSTANCE_NAME) -> None:
        from PyQt6.QtNetwork import QLocalServer

        self.window = None
        self.server = QLocalServer()
        # Un canal laissé par un arrêt brutal (Linux, macOS) empêcherait
        # d'écouter ; sous Windows, il disparaît avec le processus.
        QLocalServer.removeServer(name)
        self.listening = self.server.listen(name)
        if not self.listening:
            logging.getLogger("delugeapp").warning(
                "canal d'instance indisponible : %s",
                self.server.errorString())
        self.server.newConnection.connect(self._appel)

    def _appel(self) -> None:
        while self.server.hasPendingConnections():
            self.server.nextPendingConnection().disconnectFromServer()
        fenetre = self.window
        if fenetre is not None:
            logging.getLogger("delugeapp").info(
                "second lancement : la fenêtre ouverte est montrée")
            fenetre.showNormal()
            fenetre.raise_()
            fenetre.activateWindow()


def _run_windows(app, args: argparse.Namespace, splash=None,
                 instance: _Instance | None = None) -> int:
    """Ouvre la fenêtre, et la rouvre tant qu'elle demande un redémarrage.

    Changer de langue redémarre la fenêtre dans le même processus : elle se
    ferme comme à l'ordinaire — question si un travail tourne, état gardé,
    fils arrêtés, contexte fermé —, puis tout se reconstruit, réglages,
    index, carte et lecteur, dans la nouvelle langue. Les textes se
    traduisent à leur création : seule une fenêtre neuve change de langue.
    """
    from delugeapp import i18n
    from delugeapp.ui import icons, tasks
    from delugeapp.ui.mainwindow import MainWindow
    from delugeapp.ui.theme import GOLD, apply_theme

    log = logging.getLogger("delugeapp")
    code = 0
    while True:
        ctx = _build_context(args)
        _translate_qt(app, i18n.language())
        apply_theme(app, ctx.settings.theme_accent or GOLD)
        app.setWindowIcon(icons.app_icon(256))

        window = MainWindow(ctx)
        if instance is not None:
            instance.window = window
        window.show()
        if splash is not None:
            splash.finish(window)
            splash = None

        try:
            code = app.exec()
        finally:
            # Rempart : si la boucle Qt se termine autrement que par la
            # fermeture de la fenêtre, les fils doivent tout de même être
            # arrêtés — un QThread encore vivant fait planter le processus
            # à la sortie.
            tasks.stop_all(3000)
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                log.exception("fermeture du contexte en échec")

        if not getattr(window, "restart_requested", False):
            return code
        log.info("redémarrage de la fenêtre (langue : %s)",
                 ctx.settings.language)
        # L'index ne se vide qu'au premier démarrage, s'il était demandé.
        args.reset_db = False
        _dispose(window)


def _sorties_sures() -> None:
    """Donne une sortie à qui écrit sur la console.

    Empaquetée en application fenêtrée (``packaging/``), l'application n'a
    pas de console : ``sys.stdout`` et ``sys.stderr`` valent ``None``, et
    le premier ``write`` — ``--version``, une bibliothèque bavarde — lève
    une exception.
    """
    for nom in ("stdout", "stderr"):
        if getattr(sys, nom) is None:
            setattr(sys, nom, open(os.devnull, "w", encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    """Lance l'application. Retourne le code de sortie."""
    _sorties_sures()
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["--self-test"]:
        # Avant tout le reste : l'autovérification pose son propre dossier
        # de configuration, que la lecture de la langue importerait.
        from delugeapp import autotest

        return autotest.run(argv[1] if len(argv) > 1 else None)
    _choose_language()
    from delugeapp.i18n import tr

    args = _parse_args(argv)

    if args.version:
        from delugeapp import __version__

        sys.stdout.write(f"Noctiluca {__version__}\n")
        return 0

    log_path = _setup_logging(args.verbose)
    log = logging.getLogger("delugeapp")
    log.info("démarrage de Noctiluca")
    _log_reprises(log)

    try:
        from PyQt6.QtWidgets import QApplication
    except ImportError:
        sys.stderr.write(tr(
            "PyQt6 est nécessaire pour lancer l'application.\n"
            "Installez-le avec :  pip install PyQt6 numpy\n"))
        return 2

    from delugeapp.config import APP_NAME, APP_ORG

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ORG)
    app.setApplicationDisplayName(APP_NAME)

    _install_excepthook()

    if _already_running():
        log.info("déjà ouverte : la fenêtre existante est montrée")
        return 0
    instance = _Instance()

    splash = None
    if not args.no_splash:
        try:
            splash = _splash(app)
        except Exception:  # noqa: BLE001 - un écran d'attente est accessoire
            log.exception("écran de démarrage impossible")
    if log_path is not None:
        log.info("journal : %s", log_path)

    try:
        return _run_windows(app, args, splash, instance)
    finally:
        log.info("arrêt de Noctiluca")


if __name__ == "__main__":
    raise SystemExit(main())
