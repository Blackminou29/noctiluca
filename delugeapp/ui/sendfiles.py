# -*- coding: utf-8 -*-
"""Envoyer au Deluge, côté interface : du glisser-déposer au plan confirmé.

D'où qu'on parte — des fichiers glissés sur la fenêtre, le bouton de la page
Échantillons, le menu Fichier, le tableau de bord —, le parcours est le même :

1. lire ce qui est déposé, hors du fil de l'interface (en-têtes, XML) ;
2. montrer le plan : où va chaque fichier, ce qui est déjà sur la carte, ce
   que la machine refuserait, combien de temps le câble y mettra ;
3. copier sur la carte de l'application — la copie de travail, d'où la
   synchronisation l'envoie au Deluge, ou la carte d'un lecteur ;
4. indexer ce qui est arrivé, et laisser la synchronisation faire le reste.

Depuis que la carte reste dans le Deluge, l'Explorateur ne l'atteint plus :
c'était, avant ce module, la seule façon d'y mettre ses propres sons.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
)

from ..core import cardimport
from ..core.delugefiles import WRITE_RATE
from . import tasks
from .theme import PAD, PAD_AMBER

log = logging.getLogger(__name__)

__all__ = ["SendDialog", "local_paths", "send_files"]

#: Au-delà, le plan conseille de n'envoyer qu'une partie.
LONG_SECONDS = 30 * 60


def local_paths(mime) -> list[Path]:
    """Les fichiers et dossiers locaux d'un glisser-déposer."""
    if mime is None or not mime.hasUrls():
        return []
    sortie = []
    for url in mime.urls():
        if url.isLocalFile():
            chemin = Path(url.toLocalFile())
            if chemin.exists():
                sortie.append(chemin)
    return sortie


def where_it_goes(ctx) -> str:
    """Où part ce qu'on envoie, en une phrase — pour le dialogue et pour le
    voile du glisser-déposer."""
    sd = getattr(ctx, "sd", None)
    if sd is None:
        return ""
    role = ctx.settings.card_role(sd.root)
    if role == "sauvegarde":
        return ("La sauvegarde est ouverte, en lecture seule : rien n'y sera "
                "copié.")
    if role == "travail":
        travail = getattr(ctx, "card_work", None)
        if travail is not None and travail.files() is not None:
            return ("Dans la copie de travail, puis sur le Deluge par le "
                    "câble USB.")
        return ("Dans la copie de travail : ils partiront sur le Deluge à sa "
                "prochaine connexion.")
    if role == "carte":
        return "Directement sur la carte, dans le lecteur du PC."
    return "Dans le dossier de la carte, %s." % sd.root


def _context(ctx, plan: cardimport.ImportPlan) -> str:
    """Le chemin que prendra l'envoi, et le temps qu'il prendra."""
    texte = where_it_goes(ctx)
    sd = getattr(ctx, "sd", None)
    if sd is None or ctx.settings.card_role(sd.root) != "travail" \
            or plan.empty:
        return texte
    texte += " Par le câble : %s." % plan.cable_time()
    texte += (" Le Deluge ne doit pas jouer pendant l'envoi : la "
              "synchronisation s'arrête quand il joue, et reprend à l'arrêt.")
    if plan.bytes_to_copy() / WRITE_RATE > LONG_SECONDS:
        texte += (" C'est long : vous pouvez n'envoyer qu'une partie, en "
                  "glissant seulement les dossiers utiles.")
    return texte


class SendDialog(QDialog):
    """Le plan d'un envoi vers le Deluge, avant toute copie.

    La destination des sons « en vrac » se choisit ici, et le plan se
    recalcule aussitôt — la lecture coûteuse de ce qui est déposé, elle, est
    déjà faite.
    """

    def __init__(self, scan: cardimport.ImportScan, card_root: Path,
                 dest: str = "SAMPLES",
                 context: Callable[[cardimport.ImportPlan], str] | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Envoyer au Deluge")
        self.resize(900, 600)
        self._scan = scan
        self._root = Path(card_root)
        self._context = context
        self._existing = cardimport.card_files(self._root)
        self._plan = cardimport.ImportPlan()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAD, PAD, PAD, PAD)
        layout.setSpacing(8)

        self._summary = QLabel()
        self._summary.setProperty("role", "title")
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)

        self._dest_box: QComboBox | None = None
        if scan.has_loose_samples:
            ligne = QHBoxLayout()
            etiquette = QLabel("Les sons hors d'un pack vont dans")
            etiquette.setProperty("role", "subtitle")
            ligne.addWidget(etiquette)
            self._dest_box = QComboBox()
            self._dest_box.setToolTip(
                "Un dossier de SAMPLES : les sons y gardent le nom du "
                "dossier déposé. Les packs à la forme de la carte gardent, "
                "eux, leurs propres chemins — leurs presets les citent")
            dossiers = cardimport.sample_folders(self._root)
            voulu = cardimport.card_path(dest) or "SAMPLES"
            if voulu not in dossiers:
                dossiers.append(voulu)
            self._dest_box.addItems(dossiers)
            self._dest_box.setCurrentText(voulu)
            self._dest_box.currentIndexChanged.connect(
                lambda _i: self._recompute())
            ligne.addWidget(self._dest_box, 1)
            layout.addLayout(ligne)
        self._dest = dest or "SAMPLES"

        self._where = QLabel()
        self._where.setWordWrap(True)
        layout.addWidget(self._where)

        self._warnings = QLabel()
        self._warnings.setWordWrap(True)
        self._warnings.setStyleSheet("color: %s; font-weight: 600;"
                                     % PAD_AMBER)
        layout.addWidget(self._warnings)

        self._detail = QPlainTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        # Par la feuille de style : un ``setFont`` serait écrasé par celle de
        # l'application (vu sur le tempo de « Deluge en direct »).
        self._detail.setProperty("role", "mono")
        layout.addWidget(self._detail, 1)

        boutons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        self._ok = boutons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok.setText("Envoyer")
        self._ok.setObjectName("Primary")
        self._ok.setToolTip("Copie les fichiers prévus sur la carte ; rien "
                            "d'existant n'est remplacé")
        boutons.button(QDialogButtonBox.StandardButton.Cancel).setText(
            "Annuler")
        boutons.accepted.connect(self.accept)
        boutons.rejected.connect(self.reject)
        layout.addWidget(boutons)
        self._recompute()

    @property
    def plan(self) -> cardimport.ImportPlan:
        return self._plan

    def destination(self) -> str:
        return (self._dest_box.currentText() if self._dest_box is not None
                else self._dest)

    def _recompute(self) -> None:
        self._plan = cardimport.plan_import(self._scan, self._root,
                                            self.destination(),
                                            existing=self._existing)
        plan = self._plan
        self._summary.setText(plan.summary())
        self._where.setText(self._context(plan) if self._context else "")
        self._warnings.setText("\n".join(_warnings(plan)))
        self._warnings.setVisible(bool(self._warnings.text()))
        self._detail.setPlainText(plan.to_text())
        self._ok.setEnabled(not plan.empty)


def _warnings(plan: cardimport.ImportPlan) -> list[str]:
    c = plan.counts()
    lignes = []
    if c.get("refused"):
        lignes.append("⚠ %d fichier(s) que le Deluge refuserait ne partiront "
                      "pas — leur raison est dans le détail." % c["refused"])
    if c.get("convert"):
        lignes.append("%d fichier(s) seront convertis pour que le Deluge les "
                      "lise, sans perte audible." % c["convert"])
    if c.get("kept"):
        lignes.append("%d fichier(s) du pack existent déjà sur la carte avec "
                      "un autre contenu : la carte garde les siens."
                      % c["kept"])
    if plan.missing:
        lignes.append("⚠ %d preset(s), kit(s) ou morceau(x) citent des "
                      "échantillons introuvables : ces sons resteront muets."
                      % len(plan.missing))
    return lignes


# --------------------------------------------------------------------------- #
# Le parcours
# --------------------------------------------------------------------------- #

def send_files(window, paths, dest: str = "") -> bool:
    """Lance l'envoi de ``paths`` vers la carte. Rend ``False`` si rien ne
    peut partir (pas de carte, la sauvegarde, rien de déposé)."""
    ctx = window.ctx
    chemins = [Path(p) for p in (paths or ()) if p]
    if not chemins:
        return False
    sd = ctx.sd_or_warn(window, write=True)
    if sd is None:
        return False
    tasks.run_task(
        window, cardimport.scan_sources, chemins,
        title="Lecture de ce qui est déposé",
        on_result=lambda scan: _show_plan(window, sd, scan, dest),
        on_error=lambda m: window.statusBar().showMessage(
            "Lecture impossible : %s" % m, 8000))
    return True


def _show_plan(window, sd, scan: cardimport.ImportScan, dest: str) -> None:
    if getattr(window.ctx, "closed", False):
        return
    if not scan.found:
        lignes = ["  •  %s — %s" % (Path(c).name, r)
                  for c, r in scan.ignored[:10]]
        if len(scan.ignored) > 10:
            lignes.append("  … et %d autres" % (len(scan.ignored) - 10))
        QMessageBox.information(
            window, "Rien à envoyer au Deluge",
            "Rien de ce qui est déposé n'est un son, un preset, un kit ou un "
            "morceau du Deluge." + ("\n\n" + "\n".join(lignes)
                                    if lignes else ""))
        return
    dialogue = SendDialog(scan, sd.root, dest or "SAMPLES",
                          lambda plan: _context(window.ctx, plan), window)
    if dialogue.exec() != QDialog.DialogCode.Accepted:
        window.statusBar().showMessage("Rien n'a été envoyé.", 4000)
        return
    plan = dialogue.plan
    if plan.empty:
        return
    tasks.run_task(
        window, cardimport.apply_import, plan, sd,
        title="Copie sur la carte", modal=True,
        on_result=lambda r: _sent(window, r),
        on_error=lambda m: QMessageBox.warning(
            window, "Envoi interrompu", "La copie s'est arrêtée : %s" % m))


def _sent(window, resultat: cardimport.ImportResult) -> None:
    if getattr(window.ctx, "closed", False):
        return
    texte = resultat.summary()
    travail = getattr(window.ctx, "card_work", None)
    sd = window.ctx.sd
    if (resultat.written and sd is not None
            and window.ctx.settings.card_role(sd.root) == "travail"):
        texte += (" — en route vers le Deluge" if travail is not None
                  and travail.files() is not None
                  else " — ils partiront à la prochaine connexion du Deluge")
    window.statusBar().showMessage(texte + ".", 10000)
    if resultat.written:
        # L'index les voit tout de suite : une analyse incrémentale, qui ne
        # relit que les fichiers nouveaux.
        page = window._pages.get("Dashboard") or window._create_page(
            "Dashboard")
        if page is not None and hasattr(page, "update_index"):
            page.update_index()
        window._card_written()
    if resultat.errors:
        QMessageBox.warning(
            window, "Envoi incomplet",
            "%d fichier(s) n'ont pas pu être copiés :\n\n%s"
            % (len(resultat.errors), "\n".join(resultat.errors[:10])))
