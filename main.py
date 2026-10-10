#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Point d'entrée de Deluge Companion.

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
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
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


def _install_excepthook() -> None:
    """Détourne les exceptions non rattrapées vers le journal et l'écran."""
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
            box.setWindowTitle("Erreur inattendue")
            box.setText(
                "Une erreur inattendue est survenue.\n\n"
                "L'application reste ouverte, mais l'action en cours a "
                "échoué. Le détail est dans le journal.")
            box.setInformativeText(f"{kind.__name__} : {value}")
            box.setDetailedText(detail)
            box.exec()
        except Exception:  # noqa: BLE001 - on ne fait pas d'erreur sur l'erreur
            log.exception("affichage de l'erreur impossible")

    sys.excepthook = handler


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Deluge Companion — gestion de carte SD, génération de "
                    "presets et outils de composition pour Synthstrom "
                    "Deluge.")
    parser.add_argument("--sd", metavar="CHEMIN",
                        help="emplacement de la carte SD à utiliser")
    parser.add_argument("--reset-db", action="store_true",
                        help="vide l'index avant de démarrer")
    parser.add_argument("--no-splash", action="store_true",
                        help="ne pas afficher l'écran de démarrage")
    parser.add_argument("--verbose", action="store_true",
                        help="journal détaillé sur la console")
    parser.add_argument("--version", action="store_true",
                        help="affiche la version et quitte")
    return parser.parse_args(argv)


def _build_context(args: argparse.Namespace):
    """Construit l'``AppContext``, en rattrapant chaque défaillance."""
    from delugeapp.config import CONFIG_DIR, AppContext, load_settings
    from delugeapp.core.audio_out import Player
    from delugeapp.core.db import Library
    from delugeapp.core.sdcard import SDCard

    log = logging.getLogger("delugeapp")
    settings = load_settings()

    if args.sd:
        settings.sd_path = str(Path(args.sd).expanduser())
        settings.add_recent(settings.sd_path)

    # L'index : son absence ne doit pas empêcher le démarrage, mais sans lui
    # les pages n'ont rien à montrer, donc on le signale clairement.
    try:
        library = Library(CONFIG_DIR / "library.db")
        if args.reset_db:
            library.clear()
            library.vacuum()
            log.info("index vidé à la demande")
    except Exception:
        log.exception("index inutilisable")
        raise SystemExit(
            "L'index de la carte n'a pas pu être ouvert. "
            f"Vérifiez les droits sur {CONFIG_DIR}.")

    card = None
    if settings.sd_path.strip():
        try:
            card = SDCard(Path(settings.sd_path))
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


def _splash(app):
    """Écran de démarrage : l'emblème sur un fond sombre."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QColor, QPainter, QPixmap
    from PyQt6.QtWidgets import QSplashScreen

    from delugeapp import __version__
    from delugeapp.config import APP_NAME
    from delugeapp.ui import icons
    from delugeapp.ui.theme import GOLD, GREY, PANEL_LO

    pixmap = QPixmap(420, 240)
    pixmap.fill(QColor(PANEL_LO))
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.drawPixmap(170, 36, icons.app_icon(80).pixmap(80, 80))
        font = painter.font()
        font.setPointSize(15)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(GOLD))
        painter.drawText(pixmap.rect().adjusted(0, 60, 0, 0),
                         Qt.AlignmentFlag.AlignCenter, APP_NAME)
        font.setPointSize(9)
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(QColor(GREY))
        painter.drawText(pixmap.rect().adjusted(0, 108, 0, 0),
                         Qt.AlignmentFlag.AlignCenter,
                         f"version {__version__}")
    finally:
        painter.end()

    splash = QSplashScreen(pixmap)
    splash.show()
    app.processEvents()
    return splash


def main(argv: list[str] | None = None) -> int:
    """Lance l'application. Retourne le code de sortie."""
    args = _parse_args(argv)

    if args.version:
        from delugeapp import __version__

        sys.stdout.write(f"Deluge Companion {__version__}\n")
        return 0

    log_path = _setup_logging(args.verbose)
    log = logging.getLogger("delugeapp")
    log.info("démarrage de Deluge Companion")

    try:
        from PyQt6.QtWidgets import QApplication
    except ImportError:
        sys.stderr.write(
            "PyQt6 est nécessaire pour lancer l'application.\n"
            "Installez-le avec :  pip install PyQt6 numpy\n")
        return 2

    from delugeapp.config import APP_NAME, APP_ORG
    from delugeapp.ui import icons, tasks
    from delugeapp.ui.theme import GOLD, apply_theme

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ORG)
    app.setApplicationDisplayName(APP_NAME)

    _install_excepthook()

    splash = None
    if not args.no_splash:
        try:
            splash = _splash(app)
        except Exception:  # noqa: BLE001 - un écran d'attente est accessoire
            log.exception("écran de démarrage impossible")

    ctx = _build_context(args)
    apply_theme(app, ctx.settings.theme_accent or GOLD)
    app.setWindowIcon(icons.app_icon(256))

    from delugeapp.ui.mainwindow import MainWindow

    window = MainWindow(ctx)
    window.show()
    if splash is not None:
        splash.finish(window)
    if log_path is not None:
        log.info("journal : %s", log_path)

    try:
        return app.exec()
    finally:
        # Rempart : si la boucle Qt se termine autrement que par la fermeture
        # de la fenêtre, les fils doivent tout de même être arrêtés — un
        # QThread encore vivant fait planter le processus à la sortie.
        tasks.stop_all(3000)
        try:
            ctx.close()
        except Exception:  # noqa: BLE001
            log.exception("fermeture du contexte en échec")
        log.info("arrêt de Deluge Companion")


if __name__ == "__main__":
    raise SystemExit(main())
