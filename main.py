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


def _translate_qt(app):
    """Les boutons standard de Qt en français : « Oui », « Non », « Annuler ».

    Les questions posées par ``QMessageBox`` affichaient « Yes » et « No »
    au milieu d'une application entièrement en français. La traduction est
    livrée avec PyQt6 ; il suffisait de la charger.

    Rend le traducteur installé, ou ``None`` s'il n'a pas pu l'être.
    """
    try:
        from PyQt6.QtCore import QLibraryInfo, QLocale, QTranslator

        traducteur = QTranslator(app)
        dossier = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        if (traducteur.load(QLocale(QLocale.Language.French), "qtbase", "_",
                            dossier)
                and app.installTranslator(traducteur)):
            return traducteur
    except Exception:  # noqa: BLE001 - une traduction absente ne bloque rien
        logging.getLogger("delugeapp").debug("traduction de Qt indisponible")
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
    from delugeapp.config import (CONFIG_DIR, AppContext, load_settings,
                                  save_settings)
    from delugeapp.core.audio_out import Player
    from delugeapp.core.db import Library
    from delugeapp.core.sdcard import SDCard

    log = logging.getLogger("delugeapp")
    settings = load_settings()

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

    Le treillis en haut, puis la typographie du plat : « COMPANION » en
    capitales espacées, « SYNTHSTROM » en blanc, « DELUGE » en magenta et
    son filet. Tracé à la densité de l'écran, pour rester net sur un
    affichage agrandi.
    """
    from PyQt6.QtCore import QPointF, QRectF
    from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPixmap
    from PyQt6.QtWidgets import QSplashScreen

    from delugeapp import __version__
    from delugeapp.ui import art, icons
    from delugeapp.ui.theme import (FONT_UI, PAD_MAGENTA, PAD_WHITE,
                                    TEXT_SOFT)

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
        painter.drawText(QPointF(x, 188), "COMPANION")
        painter.setFont(police(19, 800, 1.0))
        painter.setPen(QColor(PAD_WHITE))
        painter.drawText(QPointF(x, 218), "SYNTHSTROM")
        painter.setPen(QColor(PAD_MAGENTA))
        painter.drawText(QPointF(x, 248), "DELUGE")
        painter.fillRect(QRectF(x, 258, 92, 2.5), QColor(PAD_MAGENTA))
        painter.setFont(police(7, 700, 3.0))
        painter.drawText(QPointF(x, 280), f"VERSION {__version__}")
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
    _translate_qt(app)

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
