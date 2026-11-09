# -*- coding: utf-8 -*-
"""Signaler un problème : un rapport à relire, puis la page des tickets.

Depuis la publication, d'autres que l'auteur se servent de l'application, et
leur journal est la seule fenêtre sur ce qui leur arrive. Ce dialogue
rassemble ce qui aide à comprendre — version, système, fin du journal — dans
un texte **que l'utilisateur relit et modifie** avant que rien ne parte. Le
chemin de son dossier personnel y est remplacé par ``~``. Rien n'est envoyé
par l'application : le rapport est copié, et la page « New issue » de GitHub
s'ouvre dans le navigateur, où l'on colle ce que l'on veut.
"""

from __future__ import annotations

import logging
import os
import platform
import urllib.parse
from pathlib import Path

from PyQt6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QLabel,
                             QPlainTextEdit, QVBoxLayout)

from .. import __repo__, __version__
from ..i18n import tr

log = logging.getLogger(__name__)

__all__ = ["report_text", "issue_url", "ReportDialog", "LOG_LINES"]

#: Lignes du journal jointes au rapport.
LOG_LINES = 60


def _anonyme(texte: str) -> str:
    """Le dossier personnel remplacé par ``~``, dans ses deux écritures."""
    maison = str(Path.home())
    for forme in {maison, maison.replace("\\", "/")}:
        if forme and len(forme) > 3:
            texte = texte.replace(forme, "~")
    nom = os.environ.get("USERNAME") or os.environ.get("USER") or ""
    if len(nom) >= 3:
        texte = texte.replace(nom, "<utilisateur>")
    return texte


def _journal(path: Path | None, lignes: int = LOG_LINES) -> str:
    if path is None:
        return ""
    try:
        with open(path, encoding="utf-8", errors="replace") as flux:
            fin = flux.readlines()[-lignes:]
    except OSError:
        return ""
    return "".join(fin).rstrip()


def report_text(ctx=None, log_path: Path | None = None,
                detail: str = "") -> str:
    """Le rapport : de quoi reproduire, l'erreur s'il y en a une (``detail``,
    sa trace), et la fin du journal."""
    try:
        from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR
    except ImportError:            # pragma: no cover - PyQt6 est requis
        PYQT_VERSION_STR = QT_VERSION_STR = "?"
    try:
        from ..core import dsp
        compile_ = tr("oui") if dsp.compiled() else tr("non")
    except Exception:  # noqa: BLE001 - un détail du rapport
        compile_ = "?"
    settings = getattr(ctx, "settings", None)
    lien = getattr(ctx, "link", None)
    deluge = "—"
    try:
        if lien is not None and lien.is_connected:
            deluge = lien.state().summary()
    except Exception:  # noqa: BLE001
        pass
    lignes = [
        "Noctiluca %s" % __version__,
        tr("Système : %s") % platform.platform(),
        tr("Python %s · PyQt %s · Qt %s · écoute compilée : %s") % (
            platform.python_version(), PYQT_VERSION_STR, QT_VERSION_STR,
            compile_),
        tr("Langue : %s · niveau : %s") % (
            getattr(settings, "language", "?"),
            getattr(settings, "interface_level", "?")),
        tr("Deluge : %s") % deluge,
        "",
        tr("Ce qui s'est passé :"),
        "",
        "",
        tr("Ce que j'attendais :"),
        "",
        "",
    ]
    if detail.strip():
        lignes += [tr("L'erreur :"), "```", detail.rstrip(), "```", ""]
    journal = _journal(log_path)
    if journal:
        lignes += [tr("Fin du journal (app.log) :"), "```", journal, "```"]
    return _anonyme("\n".join(lignes))


def issue_url(rapport: str) -> str:
    """La page « New issue », le début du rapport déjà rempli. Le journal,
    trop long pour une adresse, se colle depuis le presse-papiers."""
    tete = rapport.split("```", 1)[0].rstrip()
    corps = tete + "\n\n" + tr("(Le rapport complet, journal compris, est "
                               "dans le presse-papiers : collez-le ici.)")
    return "%s/issues/new?%s" % (__repo__, urllib.parse.urlencode(
        {"title": "", "body": corps}, quote_via=urllib.parse.quote))


class ReportDialog(QDialog):
    """Le rapport à relire ; copié, puis la page des tickets ouverte."""

    def __init__(self, ctx, log_path: Path | None = None, parent=None,
                 detail: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Signaler un problème"))
        self.resize(720, 560)
        layout = QVBoxLayout(self)
        intro = QLabel(tr(
            "Ce rapport aide à comprendre ce qui s'est passé. Relisez-le, "
            "complétez-le et retirez-en ce que vous voulez : rien ne part "
            "sans vous. « Ouvrir la page des problèmes » le copie, puis ouvre "
            "GitHub dans votre navigateur, où vous le collez."))
        intro.setWordWrap(True)
        intro.setProperty("role", "subtitle")
        layout.addWidget(intro)
        self.text = QPlainTextEdit(report_text(ctx, log_path, detail))
        layout.addWidget(self.text, 1)
        boutons = QDialogButtonBox()
        self.copy_button = boutons.addButton(
            tr("Copier le rapport"), QDialogButtonBox.ButtonRole.ActionRole)
        self.copy_button.setToolTip(tr("Copie le texte ci-dessus dans le "
                                       "presse-papiers"))
        self.open_button = boutons.addButton(
            tr("Ouvrir la page des problèmes"),
            QDialogButtonBox.ButtonRole.AcceptRole)
        self.open_button.setObjectName("Primary")
        self.open_button.setToolTip(tr("Copie le rapport, puis ouvre la page "
                                       "« New issue » du dépôt sur GitHub"))
        boutons.addButton(tr("Fermer"), QDialogButtonBox.ButtonRole.RejectRole)
        self.copy_button.clicked.connect(self.copy)
        self.open_button.clicked.connect(self.open_issue)
        boutons.rejected.connect(self.reject)
        layout.addWidget(boutons)
        self.opened_url = ""

    def copy(self) -> None:
        QApplication.clipboard().setText(self.text.toPlainText())

    def open_issue(self) -> None:
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices

        self.copy()
        self.opened_url = issue_url(self.text.toPlainText())
        QDesktopServices.openUrl(QUrl(self.opened_url))
        self.accept()
