# -*- coding: utf-8 -*-
"""La carte du Deluge, côté interface : copie de travail et synchronisation.

La carte reste dans la machine ; le firmware 1.3 l'ouvre par USB
(:mod:`delugeapp.core.delugefiles`). L'application travaille sur une copie
de travail (:mod:`delugeapp.core.cardsync`) que ce module tient à l'image de
la carte, sans que l'utilisateur ait à y penser :

* **à la connexion** d'un Deluge qui le permet : synchronisation, ou
  proposition de créer la copie de travail ;
* **après chaque écriture** de l'application (un morceau, un preset, une
  réparation, des fichiers envoyés du PC) : ce qui a changé part sur la
  carte, deux secondes après la dernière écriture, pour grouper ;
* **au retour dans la fenêtre** : ce que le Deluge a enregistré descend ;
* **pendant que la machine joue**, rien : sa carte sert à jouer. Un
  transfert en cours s'arrête entre deux blocs dès qu'elle démarre, et
  reprend à l'arrêt — un fichier de 8 Mo met trois minutes à monter.

Chaque échange est gardé (:func:`cardsync.record_exchange`) et écrit au
journal : le 18 octobre, dix presets réparés étaient partis sur la carte
sans que rien, nulle part, ne le dise.

Les suppressions ne partent jamais sans accord ; la sauvegarde de la carte
ne change que sur commande (« Mettre à jour la sauvegarde »).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QMessageBox

from ..core import cardsync
from ..core.delugefiles import NOT_CONNECTED, STOPPED, FileError, cable_time
from ..core.units import human_size
from ..i18n import tr, untranslated
from . import tasks

log = logging.getLogger(__name__)

__all__ = ["CardWork"]

#: Délai qui groupe les écritures de l'application avant l'envoi.
WRITE_DELAY_MS = 2000
#: Au retour dans la fenêtre, pas plus d'une synchronisation par…
FOCUS_INTERVAL = 30.0
#: Au-delà, les fichiers d'un échange ne sont plus nommés un par un au
#: journal : la création de la copie de travail en compte 2 757.
LOG_NAMED = 40


class CardWork(QObject):
    """Tient la copie de travail à l'image de la carte du Deluge."""

    #: L'état a changé : en-tête, tableau de bord et réglages se redessinent.
    stateChanged = pyqtSignal()
    #: La copie de travail a reçu des fichiers : l'index doit les voir.
    workChanged = pyqtSignal()

    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.ctx = window.ctx
        self._busy = False
        self._pending: str | None = None
        self._last_sync = 0.0
        #: Fichiers de la sauvegarde que l'utilisateur a choisi de reprendre.
        self._repris: list[str] = []
        #: Dernier plan calculé, et ce qui en a été fait.
        self.last_plan: cardsync.SyncPlan | None = None
        self.last_result: cardsync.SyncResult | None = None
        #: Ce qui attend d'être envoyé au Deluge : ``[(chemin, taille)]``.
        self.pending: list[tuple[str, int]] = []
        #: Numéro du dernier compte demandé : un compte plus ancien, fini
        #: après une synchronisation, ne doit pas la contredire.
        self._generation = 0
        #: Ce que la sauvegarde n'a pas encore, dernière comparaison.
        self.backup_plan: cardsync.BackupUpdate | None = None
        self._backup_busy = False
        #: Une mise à jour demandée pendant une comparaison : elle attend sa
        #: réponse au lieu de se perdre.
        self._backup_wanted = None
        #: Phrase d'état, pour l'en-tête et les réglages.
        self.message = ""
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(WRITE_DELAY_MS)
        self._timer.timeout.connect(
            lambda: self.sync(untranslated("écriture")))

    # -- état ---------------------------------------------------------------- #

    def files(self):
        """Le client de fichiers USB, si la machine branchée le permet."""
        lien = getattr(self.ctx, "link", None)
        if lien is None or not lien.is_connected:
            return None
        client = getattr(lien, "files", None)
        return client if client is not None and client.supported else None

    def work_path(self) -> Path:
        return self.ctx.settings.work_path()

    def has_work_copy(self) -> bool:
        return (self.work_path() / cardsync.MANIFEST).is_file()

    def working_on_copy(self) -> bool:
        sd = self.ctx.sd
        return bool(sd is not None
                    and self.ctx.settings.card_role(sd.root) == "travail")

    @property
    def busy(self) -> bool:
        return self._busy

    def _playing(self) -> bool:
        lien = getattr(self.ctx, "link", None)
        return bool(lien is not None and getattr(lien, "running", False))

    def pending_deletions(self) -> list[cardsync.Action]:
        plan = self.last_plan
        return list(plan.needs_consent) if plan is not None else []

    def pending_bytes(self) -> int:
        return sum(taille for _rel, taille in self.pending)

    def pending_text(self) -> str:
        """« 3 fichiers attendent le Deluge (1,2 Mio, quelques secondes) »."""
        if not self.pending:
            return ""
        octets = self.pending_bytes()
        return (tr("%d fichier(s) attendent le Deluge (%s, %s par le câble)")
                % (len(self.pending), human_size(octets),
                   cable_time(write_bytes=octets)))

    def summary(self) -> str:
        """Une phrase sur la carte, pour l'utilisateur."""
        if self._busy:
            return tr("Synchronisation avec le Deluge…")
        if self.message:
            return self.message
        if self.pending and self.working_on_copy():
            return self.pending_text() + "."
        if self.files() is None:
            return ""
        if not self.has_work_copy():
            return tr("La carte du Deluge s'ouvre par USB : créez la copie "
                      "de travail pour y travailler.")
        return tr("Copie de travail synchronisée avec le Deluge.")

    def exchanges(self, limit: int | None = None) -> list[cardsync.Exchange]:
        """Les échanges gardés, le plus récent d'abord."""
        if not self.has_work_copy():
            return []
        return cardsync.load_exchanges(self.work_path(), limit)

    def arrivals(self, limit: int = 8) -> list[tuple[float, str]]:
        """La musique reçue du Deluge, la plus récente d'abord."""
        if not self.has_work_copy():
            return []
        return cardsync.recent_arrivals(self.work_path(), limit)

    def backup_missing(self) -> int:
        """Combien de fichiers de la carte la sauvegarde n'a pas encore."""
        plan = self.backup_plan
        return len(plan.added) + len(plan.replaced) if plan is not None else 0

    def _say(self, texte: str, duree: int = 8000) -> None:
        self.message = texte
        try:
            self.window.statusBar().showMessage(texte, duree)
        except Exception as exc:       # noqa: BLE001
            log.debug("barre d'état indisponible : %s", exc)
        self.stateChanged.emit()

    # -- déclencheurs ---------------------------------------------------------- #

    def on_start(self) -> None:
        """Au démarrage, sur la copie de travail : ce qui attend, et ce que
        la sauvegarde n'a pas — la comparaison part hors du fil de
        l'interface."""
        if not self.working_on_copy():
            return
        self.refresh_pending()
        self.check_backup()

    def on_files_known(self) -> None:
        """Le lien sait désormais si la carte s'ouvre par USB."""
        if self.files() is None:
            self.stateChanged.emit()
            return
        if not self.has_work_copy():
            self._say(tr("Le Deluge ouvre sa carte par USB : Réglages ▸ "
                         "Carte du Deluge ▸ « Créer la copie de travail »."),
                      0)
            return
        if getattr(self.ctx.settings, "auto_sync", True):
            self.sync(untranslated("connexion"))

    def on_card_written(self) -> None:
        """L'application vient d'écrire dans sa copie de travail."""
        if not self.working_on_copy():
            return
        self.refresh_pending()
        if self.files() is not None \
                and getattr(self.ctx.settings, "auto_sync", True):
            self._timer.start()

    def on_focus(self) -> None:
        """Retour dans la fenêtre : le Deluge a peut-être enregistré."""
        if (self.working_on_copy() and self.files() is not None
                and getattr(self.ctx.settings, "auto_sync", True)
                and time.monotonic() - self._last_sync > FOCUS_INTERVAL):
            self.sync(untranslated("retour"))

    def on_transport(self) -> None:
        """La machine s'arrête : une synchronisation attendait peut-être."""
        if self._pending is not None and not self._playing():
            raison, self._pending = self._pending, None
            self.sync(raison)

    def refresh_pending(self) -> None:
        """Recompte, hors du fil de l'interface, ce qui attend le Deluge.

        0,11 s sur les 2 758 fichiers de l'utilisateur — mais fait dans le
        fil de l'interface au démarrage, la fenêtre restait figée 0,3 s de
        plus (mesuré : 0,52 s sans lui, 0,84 s avec).
        """
        self._generation += 1
        if not self.working_on_copy():
            if self.pending:
                self.pending = []
                self.stateChanged.emit()
            return
        generation = self._generation
        tasks.run_task(
            self.window, cardsync.pending_changes, self.work_path(),
            title=tr("Fichiers en attente du Deluge"), quiet=True,
            on_result=lambda r, g=generation: self._pending_counted(g, r),
            on_error=lambda m: log.debug("en attente non comptés : %s", m))

    def _pending_counted(self, generation: int, attente) -> None:
        if generation != self._generation:
            return                      # un compte plus récent existe
        self.pending = list(attente)
        self.stateChanged.emit()

    # -- synchroniser ------------------------------------------------------------ #

    def sync(self, raison: str = "", allow_card_deletes: bool = False) -> bool:
        """Synchronise en arrière-plan. ``False`` si ce n'est pas possible
        maintenant (rien de branché, déjà en cours, machine qui joue)."""
        client = self.files()
        if client is None or not self.has_work_copy():
            return False
        if self._busy or self._playing():
            self._pending = raison or "attente"
            if self._playing():
                self._say(tr("Le Deluge joue : la synchronisation attend "
                             "l'arrêt."), 6000)
            return False
        self._busy = True
        self.stateChanged.emit()
        tasks.run_task(
            self.window, _synchronise, client, self.work_path(),
            self.ctx.settings.card_backup_path(), allow_card_deletes,
            raison, self._playing,
            title=tr("Synchronisation avec le Deluge"),
            on_result=self._done, on_error=self._failed)
        return True

    def _done(self, resultat) -> None:
        plan, effet, secondes, attente, raison = resultat
        self._busy = False
        self._last_sync = time.monotonic()
        self.last_plan, self.last_result = plan, effet
        self._generation += 1
        self.pending = attente
        echange = self._keep(effet, raison, secondes)
        recus = sum(effet.done.get(k, 0) for k in
                    ("pull", "copy_backup", "conflict", "delete_local"))
        if effet.stopped and not effet.lost and self._playing():
            # Arrêté entre deux blocs parce que la machine s'est mise à
            # jouer : la suite part à l'arrêt.
            self._pending = raison or "reprise"
            texte = (tr("Le Deluge joue : la synchronisation s'est arrêtée "
                        "et reprendra à l'arrêt (%s).")
                     % (echange.summary() if not echange.empty
                        else tr("rien d'envoyé")))
        elif effet.lost:
            texte = tr("Le Deluge ne répond plus : la synchronisation "
                       "reprendra à sa prochaine connexion.")
        else:
            texte = self._phrase(effet, plan)
        self._say(texte, 10000)
        if recus or effet.renamed:
            self.workChanged.emit()
            self.check_backup()
        if self._pending is not None and not self._playing():
            raison, self._pending = self._pending, None
            QTimer.singleShot(0, lambda: self.sync(raison))

    @staticmethod
    def _phrase(effet: cardsync.SyncResult, plan: cardsync.SyncPlan) -> str:
        recus = sum(effet.done.get(k, 0) for k in
                    ("pull", "copy_backup", "conflict", "delete_local"))
        envoyes = effet.done.get("push", 0) + effet.done.get("conflict", 0)
        morceaux = []
        if recus:
            morceaux.append(tr("%d reçu(s)") % recus)
        if envoyes:
            morceaux.append(tr("%d envoyé(s)") % envoyes)
        if effet.renamed:
            morceaux.append(tr("%d changé(s) des deux côtés : les deux "
                               "versions sont gardées") % len(effet.renamed))
        if plan.needs_consent:
            morceaux.append(tr("%d suppression(s) à confirmer (Réglages)")
                            % len(plan.needs_consent))
        if effet.errors:
            morceaux.append(tr("%d erreur(s) — voir le journal")
                            % len(effet.errors))
        return ((tr("Deluge synchronisé : %s") % ", ".join(morceaux))
                if morceaux
                else tr("Copie de travail à jour avec le Deluge."))

    def _keep(self, effet: cardsync.SyncResult, raison: str,
              secondes: float) -> cardsync.Exchange:
        """Garde l'échange dans la copie de travail, et le dit au journal."""
        echange = cardsync.exchange_of(effet, raison, secondes)
        try:
            cardsync.record_exchange(self.work_path(), echange)
        except OSError as exc:
            log.warning("échange avec le Deluge non gardé : %s", exc)
        _journal(echange)
        return echange

    def _failed(self, message: str) -> None:
        self._busy = False
        self._pending = None
        self._say(tr("Synchronisation interrompue : %s") % message, 0)

    # -- créer la copie de travail ------------------------------------------------- #

    def create_work_copy(self, parent=None) -> None:
        """Bâtit la copie de travail face à la carte : depuis la sauvegarde
        pour ce qui y est déjà, par le câble pour le reste. Le plan est
        montré avant la moindre copie."""
        client = self.files()
        if client is None:
            QMessageBox.information(
                parent or self.window, tr("Carte du Deluge"),
                tr("Branchez le Deluge en USB, avec le firmware 1.3 ou plus "
                   "récent : c'est lui qui ouvre sa carte au PC."))
            return
        if self._busy:
            return
        self._busy = True
        self.stateChanged.emit()
        travail = self.work_path()
        sauvegarde = self.ctx.settings.card_backup_path()
        tasks.run_task(
            self.window, _plan_only, client, travail, sauvegarde,
            title=tr("Lecture de la carte du Deluge"),
            on_result=lambda r: self._confirm_creation(parent, r),
            on_error=self._failed)

    def _confirm_creation(self, parent, plan) -> None:
        self._busy = False
        self.stateChanged.emit()
        reprises = plan.of("copy_backup")
        cable = plan.of("pull")
        lignes = [tr("La copie de travail sera créée dans :"), "",
                  "    %s" % self.work_path(), ""]
        if reprises:
            lignes.append(tr("•  %d fichiers repris de votre sauvegarde (%s, "
                             "copie locale)")
                          % (len(reprises),
                             human_size(sum(a.size for a in reprises))))
        if cable:
            octets = sum(a.size for a in cable)
            lignes.append(tr("•  %d fichiers reçus du Deluge par USB (%s, %s)")
                          % (len(cable), human_size(octets),
                             cable_time(read_bytes=octets)))
        musique = plan.backup_music()
        autres = len(plan.backup_only) - len(musique)
        if musique:
            lignes.append(tr("•  %d fichier(s) de musique dans votre "
                             "sauvegarde mais pas sur la carte — proposés "
                             "juste après") % len(musique))
        if autres:
            lignes.append(tr("•  %d autre(s) fichier(s) de la sauvegarde, "
                             "absents de la carte (ancien firmware, anciens "
                             "réglages) : laissés dans la sauvegarde")
                          % autres)
        lignes += ["", tr("Rien n'est écrit sur la carte, sauf la date des "
                          "fichiers que le Deluge a enregistrés : elle permet "
                          "de voir ce qu'il réécrira. Votre sauvegarde n'est "
                          "que lue."),
                   "", tr("Continuer ?")]
        if QMessageBox.question(
                parent or self.window, tr("Créer la copie de travail"),
                "\n".join(lignes)) != QMessageBox.StandardButton.Yes:
            self._say(tr("Copie de travail non créée."), 6000)
            return
        self._repris = []
        musique = plan.backup_music()
        if musique:
            noms = "\n".join("  •  %s" % r for r, _ in musique[:12])
            if len(musique) > 12:
                noms += "\n  " + tr("… et %d autres") % (len(musique) - 12)
            if QMessageBox.question(
                    parent or self.window, tr("Dans la sauvegarde seulement"),
                    tr("Ces fichiers sont dans votre sauvegarde, pas sur la "
                       "carte du Deluge :\n\n%s\n\nSi l'application les a "
                       "créés là, ils n'y sont jamais arrivés. Les reprendre "
                       "dans la copie de travail, pour qu'ils partent sur le "
                       "Deluge ? (S'ils ont été supprimés exprès sur la "
                       "machine, répondez non : ils restent dans la "
                       "sauvegarde.)") % noms
            ) == QMessageBox.StandardButton.Yes:
                self._repris = [r for r, _ in musique]
        client = self.files()
        if client is None:
            return
        self._busy = True
        self.stateChanged.emit()
        tasks.run_task(
            self.window, _apply_creation, plan, client, self.work_path(),
            title=tr("Copie de travail de la carte"), modal=True,
            on_result=self._created, on_error=self._failed)

    def _created(self, resultat) -> None:
        self._busy = False
        self._last_sync = time.monotonic()
        plan, effet, secondes = resultat
        self.last_plan, self.last_result = plan, effet
        self._keep(effet, untranslated("création"), secondes)
        if effet.stopped:
            self._say(tr("Copie de travail interrompue : relancez-la pour la "
                         "terminer."), 0)
            return
        if effet.errors:
            self._say(tr("Copie de travail créée avec %d erreur(s) — voir le "
                         "journal.") % len(effet.errors), 0)
        else:
            self._say(tr("Copie de travail créée : l'application travaille "
                         "désormais sur la carte du Deluge."), 10000)
        # Ce que la sauvegarde avait seule, et que l'utilisateur reprend :
        # dans la copie de travail, d'où la synchronisation l'enverra.
        repris = getattr(self, "_repris", [])
        sauvegarde = self.ctx.settings.card_backup_path()
        if repris and sauvegarde is not None:
            n = cardsync.take_from_backup(sauvegarde, self.work_path(), repris)
            if n:
                QTimer.singleShot(0, lambda: self.sync("reprise"))
        # La copie de travail devient la carte de l'application.
        changer = getattr(self.window, "_card_changed", None)
        if callable(changer):
            changer(str(self.work_path()))
        analyser = getattr(self.window, "scan_card", None)
        if callable(analyser):
            analyser()
        self.check_backup()

    # -- suppressions et sauvegarde ------------------------------------------------ #

    def confirm_deletions(self, parent=None) -> None:
        """Les fichiers supprimés sur le PC : les supprimer aussi de la carte ?"""
        attente = self.pending_deletions()
        if not attente:
            return
        noms = "\n".join("  •  %s" % a.rel for a in attente[:12])
        if len(attente) > 12:
            noms += "\n  " + tr("… et %d autres") % (len(attente) - 12)
        if QMessageBox.question(
                parent or self.window, tr("Supprimer aussi de la carte ?"),
                tr("Ces fichiers ont été supprimés de la copie de travail :"
                   "\n\n%s\n\nLes supprimer aussi de la carte du Deluge ? "
                   "Votre sauvegarde, elle, les garde.") % noms
        ) == QMessageBox.StandardButton.Yes:
            self.sync("suppressions", allow_card_deletes=True)

    def check_backup(self) -> None:
        """Compare, hors du fil de l'interface, la sauvegarde à la carte : le
        tableau de bord dit ensuite ce qu'elle n'a pas encore."""
        sauvegarde = self.ctx.settings.card_backup_path()
        if (self._backup_busy or sauvegarde is None or not sauvegarde.is_dir()
                or not self.has_work_copy()):
            return
        self._backup_busy = True
        tasks.run_task(
            self.window, cardsync.update_backup, self.work_path(), sauvegarde,
            False, title=tr("Comparaison avec la sauvegarde"), quiet=True,
            on_result=self._backup_checked, on_error=self._backup_failed)

    def _backup_checked(self, plan) -> None:
        self._backup_busy = False
        self.backup_plan = plan
        self.stateChanged.emit()
        demande, self._backup_wanted = self._backup_wanted, None
        sauvegarde = self.ctx.settings.card_backup_path()
        if demande is not None and sauvegarde is not None:
            self._ask_backup(demande, sauvegarde, plan)

    def _backup_failed(self, message: str) -> None:
        self._backup_busy = False
        self._backup_wanted = None
        log.warning("comparaison avec la sauvegarde impossible : %s", message)

    def update_backup(self, parent=None) -> None:
        """Met la sauvegarde à l'image de la carte, sans rien y supprimer.

        Le plan se calcule hors du fil de l'interface : il comparait le
        contenu de 1,4 Go dans la fenêtre, figée 3 à 11 s (mesuré).
        """
        sauvegarde = self.ctx.settings.card_backup_path()
        if sauvegarde is None or not self.has_work_copy():
            QMessageBox.information(
                parent or self.window, tr("Sauvegarde de la carte"),
                tr("Il faut une copie de travail et un dossier de "
                   "sauvegarde."))
            return
        if self._backup_busy:
            # Une comparaison tourne déjà : sa réponse servira.
            self._backup_wanted = parent or self.window
            self._say(tr("Comparaison avec la sauvegarde en cours…"), 4000)
            return
        self._backup_busy = True
        tasks.run_task(
            self.window, cardsync.update_backup, self.work_path(), sauvegarde,
            False, title=tr("Comparaison avec la sauvegarde"),
            on_result=lambda plan: self._ask_backup(parent, sauvegarde, plan),
            on_error=self._backup_failed)

    def _ask_backup(self, parent, sauvegarde: Path, plan) -> None:
        self._backup_busy = False
        self.backup_plan = plan
        self.stateChanged.emit()
        if not plan.added and not plan.replaced:
            self._say(tr("La sauvegarde est déjà à jour."), 6000)
            return
        if QMessageBox.question(
                parent or self.window, tr("Mettre à jour la sauvegarde"),
                tr("Dans %s :\n\n•  %d fichiers ajoutés\n•  %d remplacés — "
                   "l'ancienne version est gardée à côté\n•  %d que la carte "
                   "n'a plus : gardés\n\n%s à copier. Rien n'est supprimé. "
                   "Continuer ?") % (sauvegarde, len(plan.added),
                                     len(plan.replaced), len(plan.kept),
                                     human_size(plan.bytes))
        ) != QMessageBox.StandardButton.Yes:
            return
        self._backup_busy = True
        tasks.run_task(
            self.window, cardsync.update_backup, self.work_path(), sauvegarde,
            True, title=tr("Mise à jour de la sauvegarde"), modal=True,
            on_result=self._backup_updated, on_error=self._backup_failed)

    def _backup_updated(self, rapport) -> None:
        self._backup_busy = False
        log.info("sauvegarde de la carte mise à jour : %s", rapport.summary())
        self.backup_plan = cardsync.BackupUpdate(kept=list(rapport.kept),
                                                 errors=list(rapport.errors))
        self._say(tr("Sauvegarde mise à jour : %s.") % rapport.summary(),
                  10000)


# --------------------------------------------------------------------------- #
# Le journal
# --------------------------------------------------------------------------- #

def _journal(echange: cardsync.Exchange) -> None:
    """Écrit un échange au journal de l'application : ce qui a été reçu et
    envoyé, fichier par fichier tant qu'ils sont peu nombreux."""
    if echange.empty:
        log.debug("synchronisation (%s) : rien à faire", echange.reason)
        return
    log.info("Deluge — synchronisation (%s) : %s, en %.1f s",
             echange.reason or "demande", echange.summary(), echange.seconds)
    # Le journal reste en français.
    listes = untranslated((("reçu", echange.received),
                           ("envoyé", echange.sent),
                           ("retiré de la copie", echange.removed),
                           ("supprimé de la carte", echange.deleted)))
    if sum(len(liste) for _verbe, liste in listes) <= LOG_NAMED:
        for verbe, liste in listes:
            for rel in liste:
                log.info("  %s : %s", verbe, rel)
    for rel, nouveau in echange.conflicts:
        log.info("  changé des deux côtés : %s — la version du PC devient %s",
                 rel, nouveau)
    for erreur in echange.errors:
        log.warning("  %s", erreur)


# --------------------------------------------------------------------------- #
# Travaux de fond
# --------------------------------------------------------------------------- #

def _plan_with(carte: cardsync.UsbCard, travail: Path,
               sauvegarde: Path | None, progress=None) -> cardsync.SyncPlan:
    if progress is not None:
        progress(tr("Liste des fichiers du Deluge…"))
    arbre = carte.walk()
    Path(travail).mkdir(parents=True, exist_ok=True)
    plan = cardsync.plan_sync(arbre, cardsync.scan_local(travail),
                              cardsync.load_manifest(travail),
                              backup=sauvegarde)
    plan.unreachable = carte.unreachable
    return plan


def _plan_only(client, travail: Path, sauvegarde: Path | None,
               progress=None, should_stop=None) -> cardsync.SyncPlan:
    return _plan_with(cardsync.UsbCard(client, should_stop), travail,
                      sauvegarde, progress)


def _apply_creation(plan, client, travail: Path, progress=None,
                    should_stop=None):
    debut = time.monotonic()
    carte = cardsync.UsbCard(client, should_stop)
    manifeste = cardsync.load_manifest(travail)

    def suivre(i, n, rel):
        if progress is not None:
            progress((i, n))

    effet = cardsync.apply_plan(plan, carte, travail, manifeste,
                                progress=suivre, should_stop=should_stop)
    return plan, effet, time.monotonic() - debut


def _synchronise(client, travail: Path, sauvegarde: Path | None,
                 allow_card_deletes: bool, raison: str = "", playing=None,
                 progress=None, should_stop=None):
    """Une synchronisation complète, hors du fil de l'interface.

    Elle s'arrête entre deux blocs si l'on ferme la fenêtre ou si la machine
    se met à jouer (``playing``) : ce qui est fait reste acquis.
    """
    debut = time.monotonic()

    def arret() -> bool:
        return bool((should_stop is not None and should_stop())
                    or (playing is not None and playing()))

    carte = cardsync.UsbCard(client, arret)
    try:
        plan = _plan_with(carte, travail, sauvegarde, progress)
    except FileError as exc:
        # Arrêté — ou débranché — pendant le parcours de la carte : rien
        # n'a bougé, la synchronisation reprendra.
        if exc.code not in (STOPPED, NOT_CONNECTED):
            raise
        effet = cardsync.SyncResult(stopped=True,
                                    lost=exc.code == NOT_CONNECTED)
        if effet.lost:
            effet.errors.append(tr("le Deluge a été débranché"))
        return (cardsync.SyncPlan(), effet, time.monotonic() - debut,
                cardsync.pending_changes(travail), raison)
    manifeste = cardsync.load_manifest(travail)

    def suivre(i, n, rel):
        if progress is not None and rel:
            progress(tr("Deluge : %d / %d — %s") % (i + 1, n, rel))

    effet = cardsync.apply_plan(plan, carte, travail, manifeste,
                                allow_card_deletes=allow_card_deletes,
                                progress=suivre, should_stop=arret)
    attente = cardsync.pending_changes(travail)
    return plan, effet, time.monotonic() - debut, attente, raison
