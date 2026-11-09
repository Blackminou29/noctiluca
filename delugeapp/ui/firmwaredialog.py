# -*- coding: utf-8 -*-
"""Outils ▸ Firmware du Deluge… : préparer la carte pour une mise à jour.

La version installée se lit sur la machine (SysEx) et sur la carte (le nom
de son ``.bin``). La dernière version stable ne se cherche que sur demande ;
si elle est plus récente, l'application la télécharge, montre le plan, pose
son ``.bin`` à la racine et range l'ancien dans ``_BACKUP``
(:mod:`delugeapp.core.firmware`). Elle ne flashe rien : la fin du dialogue
dit comment le Deluge s'installe lui-même.
"""

from __future__ import annotations

import logging

from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QMessageBox,
                             QVBoxLayout)

from ..core import firmware
from ..i18n import tr, untranslated
from .tasks import run_task

log = logging.getLogger(__name__)

__all__ = ["FirmwareDialog", "GUIDE_URL"]

#: Le guide de mise à jour du dépôt du firmware.
GUIDE_URL = ("https://github.com/SynthstromAudible/DelugeFirmware/wiki/"
             "Update-guide")


class FirmwareDialog(QDialog):
    """Les versions en présence, la dernière publiée, et la carte préparée."""

    def __init__(self, ctx, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.release: firmware.FirmwareRelease | None = None
        self.setWindowTitle(tr("Firmware du Deluge"))
        self.resize(620, 420)
        layout = QVBoxLayout(self)
        intro = QLabel(tr(
            "Préparer la carte pour une nouvelle version du firmware "
            "communautaire : l'application cherche la dernière version "
            "stable — seulement quand vous le demandez —, la télécharge, "
            "pose son .bin à la racine de la carte et range l'ancien dans "
            "_BACKUP. Elle ne flashe rien : c'est le Deluge qui s'installe, "
            "allumé SHIFT enfoncé."))
        intro.setWordWrap(True)
        intro.setProperty("role", "subtitle")
        layout.addWidget(intro)
        self.state = QLabel(self._state_text())
        self.state.setWordWrap(True)
        layout.addWidget(self.state)
        self.answer = QLabel("")
        self.answer.setWordWrap(True)
        self.answer.setOpenExternalLinks(True)
        layout.addWidget(self.answer, 1)

        boutons = QDialogButtonBox()
        self.check_button = boutons.addButton(
            tr("Chercher la dernière version"),
            QDialogButtonBox.ButtonRole.ActionRole)
        self.check_button.setToolTip(tr(
            "Lit la liste des versions sur GitHub — la seule requête, faite "
            "maintenant parce que vous la demandez"))
        self.prepare_button = boutons.addButton(
            tr("Préparer la carte…"), QDialogButtonBox.ButtonRole.ActionRole)
        self.prepare_button.setObjectName("Primary")
        self.prepare_button.setToolTip(tr(
            "Télécharge la version, montre le plan, pose son .bin à la "
            "racine et range l'ancien dans _BACKUP — après votre accord"))
        self.prepare_button.setEnabled(False)
        boutons.addButton(tr("Fermer"), QDialogButtonBox.ButtonRole.RejectRole)
        self.check_button.clicked.connect(self.check)
        self.prepare_button.clicked.connect(self.prepare)
        boutons.rejected.connect(self.reject)
        layout.addWidget(boutons)

    # -- ce qui est installé -------------------------------------------- #

    def _machine_version(self) -> str:
        lien = getattr(self.ctx, "link", None)
        try:
            if lien is not None and lien.is_connected:
                return firmware.version_of(lien.state().firmware)
        except Exception:  # noqa: BLE001 - la machine peut se taire
            log.debug("version de la machine illisible", exc_info=True)
        return ""

    def _current(self) -> str:
        """La version de référence : celle de la machine, sinon de la carte."""
        sd = getattr(self.ctx, "sd", None)
        return self._machine_version() or (
            firmware.card_version(sd) if sd is not None else "")

    def _state_text(self) -> str:
        sd = getattr(self.ctx, "sd", None)
        lignes = []
        machine = self._machine_version()
        lignes.append(tr("Sur la machine : %s") % (
            machine or tr("inconnue (Deluge débranché)")))
        if sd is None:
            lignes.append(tr("Sur la carte : aucune carte choisie"))
        else:
            fichiers = [p.name for p in sd.firmware_files()]
            lignes.append(tr("Sur la carte : %s") % (
                ", ".join(fichiers) if fichiers
                else tr("aucun .bin à la racine")))
        return "\n".join(lignes)

    # -- la dernière version -------------------------------------------- #

    def check(self) -> None:
        self.check_button.setEnabled(False)
        self.answer.setText(tr("Recherche de la dernière version…"))
        run_task(self, firmware.latest_release, on_result=self._known,
                 on_error=self._failed, title=tr("Version du firmware"))

    def _failed(self, message: str) -> None:
        self.check_button.setEnabled(True)
        self.prepare_button.setEnabled(False)
        self.answer.setText(tr("Échec : %s") % message)

    def _known(self, release) -> None:
        self.check_button.setEnabled(True)
        self.release = release
        if release is None:
            self.prepare_button.setEnabled(False)
            self.answer.setText(tr("Pas de réponse utilisable de GitHub : pas "
                                   "de réseau, ou une réponse inattendue."))
            return
        courante = self._current()
        lien = untranslated('<a href="%s">%s</a>') % (release.page,
                                                       tr("ses nouveautés"))
        if courante and not firmware.is_newer(release.version, courante):
            self.prepare_button.setEnabled(False)
            self.answer.setText(tr("La dernière version stable, %s, est déjà "
                                   "la vôtre (%s).") % (release.version, lien))
            return
        self.prepare_button.setEnabled(True)
        self.answer.setText(tr("La version %s est publiée (%s) ; vous avez "
                               "%s.") % (release.version, lien,
                                         courante or tr("une version "
                                                        "inconnue")))

    # -- la carte préparée ---------------------------------------------- #

    def prepare(self) -> None:
        sd = getattr(self.ctx, "sd", None)
        if self.release is None or sd is None:
            return
        try:
            sd.require_writable()
        except PermissionError as exc:
            self.answer.setText(str(exc))
            return
        self.prepare_button.setEnabled(False)
        self.answer.setText(tr("Téléchargement de %s…") % self.release.asset)
        run_task(self, self._fetch, self.release, on_result=self._fetched,
                 on_error=self._failed, title=tr("Téléchargement du firmware"))

    @staticmethod
    def _fetch(release):
        data = firmware.download(release)
        return firmware.firmware_from(data, release.asset)

    def _fetched(self, result) -> None:
        sd = self.ctx.sd
        nom, data = result
        try:
            plan = firmware.plan_install(sd, nom, data)
        except ValueError as exc:
            self._failed(str(exc))
            return
        reponse = QMessageBox.question(
            self, tr("Préparer la carte ?"),
            "\n".join(plan.lines()) + "\n\n" + tr(
                "Rien n'est flashé : le Deluge s'installera lui-même, allumé "
                "SHIFT enfoncé."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reponse != QMessageBox.StandardButton.Yes:
            self.prepare_button.setEnabled(True)
            self.answer.setText(tr("Rien n'a été écrit."))
            return
        try:
            firmware.install(sd, plan)
        except (OSError, ValueError) as exc:
            log.exception("pose du firmware impossible")
            self._failed(str(exc))
            return
        self.state.setText(self._state_text())
        self.answer.setText(self.steps())

    def steps(self) -> str:
        """Ce qu'il reste à faire, sur la machine."""
        travail = getattr(self.ctx, "card_work", None)
        copie = travail is not None and travail.working_on_copy()
        if copie:
            premier = tr(
                "1. Synchronisez avec le Deluge : le nouveau .bin part vers "
                "la carte, une demi-minute par le câble. Le retrait de "
                "l'ancien attend votre accord : Réglages ▸ Carte du Deluge ▸ "
                "Suppressions à confirmer. Acceptez-le, le Deluge refuse de "
                "s'installer avec deux .bin à la racine.")
        else:
            premier = tr("1. Éjectez proprement la carte, et remettez-la dans "
                         "le Deluge.")
        return "<br>".join((
            tr("Le firmware est posé."), premier,
            tr("2. Deluge éteint, maintenez SHIFT et allumez-le : il "
               "s'installe, en une minute au plus."),
            tr("3. Vérifiez : SHIFT et un appui sur SELECT, puis « Firmware "
               "Version »."),
            tr("Un Deluge à afficheur 7 segments ? Lisez d'abord le <a "
               "href=\"%s\">guide de mise à jour</a> (chargeur de "
               "démarrage).") % GUIDE_URL))
