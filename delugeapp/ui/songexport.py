# -*- coding: utf-8 -*-
"""Écrire un morceau du Deluge depuis un outil de création.

Un seul parcours pour tous les boutons « en morceau » de l'application :

1. construire le morceau (:mod:`delugeapp.core.songwriter`) — une erreur
   d'usage, comme un motif vide, s'annonce avant toute question ;
2. demander son nom ;
3. montrer le plan — fichier, instruments, clips, échantillons absents —
   et le faire confirmer si les écritures doivent l'être (réglage
   « Confirmer chaque écriture ») ;
4. écrire un fichier **nouveau** dans ``SONGS`` : un nom déjà pris est
   numéroté, aucun fichier n'est remplacé — sauf un morceau que l'atelier a
   écrit lui-même et que la carte garde à l'octet près, s'il le demande
   (``written``) ;
5. l'indexer tout de suite, pour que la page Morceaux le montre.
"""

from __future__ import annotations

import logging
from typing import Callable

from PyQt6.QtWidgets import QInputDialog, QLineEdit, QMessageBox

from ..i18n import tr

log = logging.getLogger(__name__)

__all__ = ["export_song", "export_insert"]


def _replaceable(card, name: str, written: dict | None) -> tuple[str, str]:
    """Le morceau de ce nom, si l'appelant l'a écrit et qu'il n'a pas bougé :
    ``(chemin, empreinte)``, sinon ``("", "")``."""
    from ..core import songwriter
    from ..core.sdcard import norm_rel, safe_deluge_name

    if not written:
        return "", ""
    wanted = norm_rel("SONGS/%s.XML" % safe_deluge_name(name or ""))
    for rel, sha in written.items():
        if norm_rel(rel) != wanted:
            continue
        path = card.abs(rel)
        if path.is_file() and songwriter.file_sha256(path) == sha:
            return rel, sha
    return "", ""


def export_song(parent, ctx, build: Callable, default_name: str,
                say: Callable[[str], None],
                written: dict | None = None) -> str:
    """Construit, fait nommer, confirme puis écrit un morceau.

    :param build: ``build(carte) -> SongSpec`` ; une ``ValueError`` y porte
        un message destiné à l'utilisateur.
    :param say: affiche un message d'état.
    :param written: morceaux que l'appelant a écrits, chemin -> empreinte
        (``atelier.Project.written``). Si le nom choisi en désigne un que la
        carte garde tel quel, l'application propose de le remplacer.
    :returns: le chemin relatif écrit, ou ``""`` si rien ne l'a été.
    """
    from ..core import songwriter

    card = ctx.sd_or_warn(parent, write=True)
    if card is None:
        return ""
    try:
        spec = build(card)
    except ValueError as exc:
        say(tr("Morceau impossible : %s.") % exc)
        return ""
    except Exception as exc:  # noqa: BLE001 - rempart, cf. SPEC §6.3
        log.exception("construction du morceau impossible")
        say(tr("Morceau impossible : %s") % exc)
        return ""

    name, ok = QInputDialog.getText(
        parent, tr("Écrire un morceau"),
        tr("Nom du morceau, dans SONGS (il sera assaini pour la carte) :"),
        QLineEdit.EchoMode.Normal, default_name)
    if not ok or not str(name or "").strip():
        return ""
    spec.name = str(name).strip()

    replace, sha = _replaceable(card, spec.name, written)
    if replace:
        answer = QMessageBox.question(
            parent, tr("Remplacer le morceau ?"),
            tr("« %s » est le morceau que l'atelier a écrit, et ni vous ni le "
               "Deluge ne l'avez changé depuis.\n\nOui : la nouvelle version "
               "prend sa place ; l'ancienne est gardée dans _BACKUP.\nNon : "
               "la nouvelle version s'écrit à côté, sous un nom numéroté.")
            % replace,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes)
        if answer == QMessageBox.StandardButton.Cancel:
            say(tr("Rien n'a été écrit."))
            return ""
        if answer != QMessageBox.StandardButton.Yes:
            replace, sha = "", ""

    plan = songwriter.write_song(card, spec, apply=False, replace=replace,
                                 expected_sha=sha)
    if not plan.ok:
        say(tr("Morceau impossible : %s.") % plan.error)
        return ""
    if getattr(ctx.settings, "confirm_writes", True):
        question = (tr("Remplacer ce morceau sur la carte ? L'ancienne "
                       "version est gardée dans _BACKUP.") if replace else
                    tr("Écrire ce nouveau fichier sur la carte ? Aucun "
                       "fichier existant n'est remplacé."))
        answer = QMessageBox.question(
            parent, tr("Écrire le morceau"),
            plan.text() + "\n\n" + question,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        if answer != QMessageBox.StandardButton.Yes:
            say(tr("Rien n'a été écrit."))
            return ""

    done = songwriter.write_song(card, spec, apply=True, replace=replace,
                                 expected_sha=sha)
    if not done.applied:
        say(tr("Morceau non écrit : %s.") % done.error)
        return ""
    try:
        from ..core.scan import index_songs

        index_songs(card, ctx.lib, [card.abs(done.rel)])
    except Exception:  # noqa: BLE001 - l'index se rattrapera à l'analyse
        log.exception("indexation du morceau impossible")
    if done.missing:
        say(tr("Morceau écrit : %s — %d échantillon(s) absent(s) de la carte. "
               "Il se charge sur le Deluge comme tout autre morceau.")
            % (done.rel, len(done.missing)))
    else:
        say(tr("Morceau écrit : %s. Il se charge sur le Deluge comme tout "
               "autre morceau.") % done.rel)
    return done.rel


def export_insert(parent, ctx, build_plan: Callable,
                  say: Callable[[str], None]) -> str:
    """Complète un morceau de la carte : plan montré, confirmé, puis écrit.

    Le morceau d'origine n'est jamais touché : le plan
    (:func:`delugeapp.core.songinsert.plan_insert`) décrit un fichier
    **nouveau**, numéroté comme le fait la machine, qui contient l'original
    octet pour octet plus les ajouts — et la preuve en est refaite avant
    d'écrire.

    :param build_plan: ``build_plan(carte) -> InsertPlan`` ; une
        ``ValueError`` y porte un message destiné à l'utilisateur.
    :returns: le chemin relatif écrit, ou ``""``.
    """
    from ..core import songinsert

    card = ctx.sd_or_warn(parent, write=True)
    if card is None:
        return ""
    try:
        plan = build_plan(card)
    except ValueError as exc:
        say(tr("Morceau impossible à compléter : %s.") % exc)
        return ""
    except Exception as exc:  # noqa: BLE001 - rempart, cf. SPEC §6.3
        log.exception("plan du morceau complété impossible")
        say(tr("Morceau impossible à compléter : %s") % exc)
        return ""
    if not plan.ok:
        say(tr("Morceau impossible à compléter : %s.") % plan.error)
        return ""
    if getattr(ctx.settings, "confirm_writes", True):
        answer = QMessageBox.question(
            parent, tr("Compléter le morceau"),
            plan.text() + "\n\n" + tr("Écrire cette nouvelle version sur la "
                                       "carte ? Le morceau d'origine n'est "
                                       "pas touché."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        if answer != QMessageBox.StandardButton.Yes:
            say(tr("Rien n'a été écrit."))
            return ""
    done = songinsert.write_insert(card, plan, apply=True)
    if not done.applied:
        say(tr("Morceau non écrit : %s.") % done.error)
        return ""
    try:
        from ..core.scan import index_songs

        index_songs(card, ctx.lib, [card.abs(done.rel)])
    except Exception:  # noqa: BLE001 - l'index se rattrapera à l'analyse
        log.exception("indexation du morceau impossible")
    say(tr("Nouvelle version écrite : %s. Chargez-la sur le Deluge ; "
           "l'original reste tel quel.") % done.rel)
    return done.rel
