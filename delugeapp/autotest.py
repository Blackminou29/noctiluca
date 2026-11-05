# -*- coding: utf-8 -*-
"""Autovérification d'une application empaquetée.

Un paquet construit par PyInstaller n'est pas le dossier des sources. Un
module importé par son seul nom (le catalogue anglais), un fichier de données
(les tables du firmware, le manuel), une bibliothèque chargée à la demande
(PortAudio, le compilateur de numba) peuvent y manquer sans que rien ne le
dise — jusqu'à ce que l'utilisateur clique au mauvais endroit.

``Noctiluca --self-test [RAPPORT]`` refait donc, dans le paquet même, chacun
de ces chemins, puis ouvre et referme la fenêtre principale. Le rapport va
dans ``RAPPORT`` (une application fenêtrée n'a pas de console), ou sur la
sortie d'erreur ; le code de sortie vaut 0 si tout est en ordre, 1 sinon.
Les scripts de ``packaging/`` le lancent sur chaque paquet avant de
l'emballer.

Le rapport est un journal : il ne se traduit pas, comme ``app.log``.

Rien n'y touche à l'utilisateur :

* la configuration va dans un dossier temporaire neuf, posé **avant**
  l'import de :mod:`delugeapp.config`, qui calcule ses chemins à l'import —
  et renommerait sinon les dossiers de l'ancien nom ;
* l'état de la fenêtre suit la configuration (``fenetre.ini``) : rien
  n'arrive dans le registre ;
* aucun port MIDI n'est visible, aucune carte n'est cherchée, et toute
  fenêtre modale répond « non ».
"""

from __future__ import annotations

import importlib
import logging
import os
import pkgutil
import platform
import shutil
import sys
import tempfile
import time
from pathlib import Path

log = logging.getLogger("delugeapp.autotest")

#: La variable de :data:`delugeapp.config.CONFIG_ENV`, recopiée : la lire
#: là-bas importerait la configuration avant que son dossier soit posé.
CONFIG_ENV = "NOCTILUCA_CONFIG"


def _isoler() -> tuple[Path | None, bool]:
    """Le dossier de configuration de la vérification, et s'il est à
    effacer ensuite.

    Toujours un dossier neuf. Si la configuration est déjà importée (une
    vérification lancée depuis la suite de tests), elle doit avoir été
    déplacée : la vérification refuse de travailler chez l'utilisateur, et
    rend ``None``.
    """
    if "delugeapp.config" in sys.modules:
        from delugeapp import config

        if not config.config_impose():
            log.error("ÉCHEC   configuration réelle déjà chargée : "
                      "vérification refusée")
            return None, False
        return config.CONFIG_DIR, False
    dossier = Path(tempfile.mkdtemp(prefix="noctiluca-autotest-"))
    os.environ[CONFIG_ENV] = str(dossier)
    return dossier, True


def _verifier(nom: str, fonction) -> bool:
    """Lance une vérification. Elle inscrit elle-même son résultat ; ce qui
    lui échappe est inscrit ici, avec sa trace."""
    try:
        return bool(fonction())
    except Exception:  # noqa: BLE001 - chaque défaut est un résultat
        log.exception("ÉCHEC   %s : erreur inattendue", nom)
        return False


# --------------------------------------------------------------------------- #
# Les vérifications
# --------------------------------------------------------------------------- #

def _qt(app) -> bool:
    """La plateforme graphique, et la traduction de Qt que ``main.py``
    charge en français (« Oui », « Non », « Annuler »)."""
    from PyQt6.QtCore import QLibraryInfo, QLocale, QTranslator

    dossier = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    traducteur = QTranslator(app)
    if not traducteur.load(QLocale(QLocale.Language.French), "qtbase", "_",
                           dossier):
        log.error("ÉCHEC   qt : qtbase_fr introuvable dans %s", dossier)
        return False
    log.info("ok      qt : plateforme %s, Qt traduit en français",
             app.platformName())
    return True


def _modules() -> bool:
    """Chaque module du paquet s'importe."""
    import delugeapp

    noms = [m.name for m in pkgutil.walk_packages(delugeapp.__path__,
                                                  "delugeapp.")]
    for nom in noms:
        importlib.import_module(nom)
    log.info("ok      modules : %d importés", len(noms))
    return True


def _catalogue() -> bool:
    """Le catalogue anglais, dont les fichiers s'importent par leur nom :
    l'analyse de PyInstaller ne les voit pas."""
    from delugeapp.i18n import en

    textes = en.load()
    if not textes:
        log.error("ÉCHEC   catalogue : vide")
        return False
    log.info("ok      catalogue : %d textes en anglais", len(textes))
    return True


def _manuel() -> bool:
    """Les deux textes du manuel."""
    from delugeapp.ui import manuel

    tailles = [len((manuel.DOSSIER / f"manuel.{langue}.md")
                   .read_text(encoding="utf-8")) for langue in ("fr", "en")]
    log.info("ok      manuel : fr et en (%d et %d caractères)", *tailles)
    return True


def _tables() -> bool:
    """Les tables du firmware, lues par l'écoute."""
    from delugeapp.core import dsp

    log.info("ok      tables : tables du firmware (%d valeurs pour "
             "tanHSmall)", len(dsp.table("tanHSmall")))
    return True


def _audio() -> bool:
    """sounddevice et sa bibliothèque PortAudio.

    Sous Windows et macOS, PortAudio est dans le paquet. Sous Linux, il
    vient du système (``libportaudio2``) : sans lui, l'application vit,
    muette — un manque, pas un échec.
    """
    from delugeapp.core import audio_out

    if audio_out._sd is not None:
        log.info("ok      audio : %s",
                 audio_out._sd.get_portaudio_version()[1])
        return True
    if sys.platform.startswith("linux"):
        log.warning("MANQUE  audio : PortAudio absent du système, "
                    "écoute muette (paquet libportaudio2)")
        return True
    log.error("ÉCHEC   audio : sounddevice ou PortAudio absent du paquet")
    return False


def _ecoute() -> bool:
    """Un son rendu par les boucles compilées : numba, llvmlite, et le
    dossier où numba garde son code (un paquet n'a pas de sources à côté
    desquelles l'écrire)."""
    from delugeapp.core import dsp, render, synthgen

    if not dsp.compiled():
        log.error("ÉCHEC   ecoute : numba absent, l'écoute tournerait en "
                  "Python, dix fois plus lente")
        return False
    preset = synthgen.generate(synthgen.GenOptions(genre="techno", seed=1))
    debut = time.perf_counter()
    audio = render.render_sound(preset.sound, seconds=0.5)
    duree = time.perf_counter() - debut
    compilees = [b for b in vars(dsp).values()
                 if isinstance(b, dsp._Boucle) and b._compiled_fn is not None]
    if not dsp.compiled() or not compilees:
        log.error("ÉCHEC   ecoute : une boucle n'a pas compilé (voir plus "
                  "haut)")
        return False
    if not float(abs(audio).max()) > 1e-3:
        log.error("ÉCHEC   ecoute : rendu silencieux")
        return False
    log.info("ok      ecoute : %d boucles compilées, une demi-seconde "
             "rendue en %.1f s", len(compilees), duree)
    # Empaqueté, numba ne voit pas de sources à côté desquelles garder son
    # code : il le range chez l'utilisateur (%LOCALAPPDATA%\numba). Sans
    # cache, chaque lancement recompilerait — quelques secondes à la
    # première écoute.
    cache = getattr(getattr(compilees[0]._compiled_fn, "_cache", None),
                    "_cache_path", None)
    log.info("        cache du code compilé : %s", cache or "aucun")
    return True


def _refuser_les_modales() -> None:
    """Chaque dialogue répond « non » : hors écran, une fenêtre modale
    figerait la vérification sans un mot."""
    from PyQt6.QtWidgets import QDialog, QFileDialog, QMessageBox

    non = QMessageBox.StandardButton.No
    for nom in ("question", "information", "warning", "critical"):
        setattr(QMessageBox, nom, staticmethod(lambda *a, **k: non))
    QMessageBox.about = staticmethod(lambda *a, **k: None)
    QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: "")
    QDialog.exec = lambda self: QDialog.DialogCode.Rejected.value


def _fenetre(app) -> bool:
    """La fenêtre principale, ouverte puis refermée comme par l'utilisateur :
    thème, pages, état gardé, contexte fermé."""
    from PyQt6.QtCore import QEventLoop, QTimer

    from delugeapp.config import DB_PATH, AppContext, load_settings
    from delugeapp.core import midiport
    from delugeapp.core.audio_out import Player
    from delugeapp.core.db import Library
    from delugeapp.ui import mainwindow, tasks
    from delugeapp.ui.theme import GOLD, apply_theme

    midiport.outputs = lambda: []
    midiport.inputs = lambda: []
    mainwindow.sdmod.detect_sd_cards = lambda: []
    _refuser_les_modales()

    settings = load_settings()
    settings.midi_autoconnect = False
    try:
        player = Player()
    except Exception:  # noqa: BLE001 - sans audio, l'application vit
        log.warning("MANQUE  fenetre : aucune sortie audio", exc_info=True)
        player = None
    ctx = AppContext(settings=settings, lib=Library(DB_PATH), player=player)
    apply_theme(app, GOLD)
    fenetre = mainwindow.MainWindow(ctx)
    fenetre.resize(1200, 800)
    fenetre.show()
    boucle = QEventLoop()
    QTimer.singleShot(600, boucle.quit)        # l'amorçage différé
    boucle.exec()
    pages = len(fenetre._classes)
    fermee = fenetre.close()
    tasks.stop_all(3000)
    if not fermee:
        log.error("ÉCHEC   fenetre : elle a refusé de se fermer")
        return False
    log.info("ok      fenetre : %d pages, ouverte et refermée", pages)
    return True


# --------------------------------------------------------------------------- #
# Lancement
# --------------------------------------------------------------------------- #

def _journal(rapport: str | None) -> logging.Handler:
    """Le rapport : un fichier, ou la sortie d'erreur."""
    if rapport:
        sortie: logging.Handler = logging.FileHandler(rapport, mode="w",
                                                      encoding="utf-8")
    else:
        sortie = logging.StreamHandler(sys.stderr)
    sortie.setFormatter(logging.Formatter("%(message)s"))
    sortie.setLevel(logging.INFO)
    logging.getLogger().addHandler(sortie)
    return sortie


def run(rapport: str | None = None, fenetre: bool = True) -> int:
    """Vérifie l'application telle qu'elle est installée. Rend 0 si tout
    l'essentiel est en ordre, 1 sinon.

    :param rapport: fichier où écrire le rapport ; sans lui, la sortie
        d'erreur.
    :param fenetre: ouvrir aussi la fenêtre principale. La suite de tests
        s'en passe : ses propres cas l'ouvrent déjà, remparts posés.
    """
    sortie = _journal(rapport)
    racine = logging.getLogger()
    niveau = racine.level
    racine.setLevel(logging.INFO)
    try:
        dossier, a_effacer = _isoler()
        if dossier is None:
            return 1
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

        from PyQt6.QtWidgets import QApplication

        from delugeapp import __version__

        log.info("Noctiluca %s : autovérification", __version__)
        log.info("système : %s %s, Python %s, %s", platform.system(),
                 platform.machine(), platform.python_version(),
                 "empaqueté" if getattr(sys, "frozen", False)
                 else "depuis les sources")
        log.info("exécutable : %s", sys.executable)
        log.info("configuration : %s", dossier)

        app = QApplication.instance() or QApplication(sys.argv[:1])
        bilan = [_verifier("qt", lambda: _qt(app)),
                 _verifier("modules", _modules),
                 _verifier("catalogue", _catalogue),
                 _verifier("manuel", _manuel),
                 _verifier("tables", _tables),
                 _verifier("audio", _audio),
                 _verifier("ecoute", _ecoute)]
        if fenetre:
            bilan.append(_verifier("fenetre", lambda: _fenetre(app)))
        echecs = bilan.count(False)
        if echecs:
            log.error("%d vérification(s) en échec", echecs)
        else:
            log.info("tout est en ordre")
        if a_effacer:
            shutil.rmtree(dossier, ignore_errors=True)
        return 1 if echecs else 0
    except Exception:  # noqa: BLE001 - le rapport doit tout dire
        log.exception("autovérification interrompue")
        return 1
    finally:
        racine.removeHandler(sortie)
        racine.setLevel(niveau)
        sortie.close()
