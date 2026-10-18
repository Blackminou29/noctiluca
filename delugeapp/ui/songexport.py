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
   numéroté, aucun fichier n'est remplacé ;
5. l'indexer tout de suite, pour que la page Morceaux le montre.
"""

from __future__ import annotations

import logging
from typing import Callable

from PyQt6.QtWidgets import QInputDialog, QLineEdit, QMessageBox

log = logging.getLogger(__name__)

__all__ = ["export_song"]


def export_song(parent, ctx, build: Callable, default_name: str,
                say: Callable[[str], None]) -> str:
    """Construit, fait nommer, confirme puis écrit un morceau.

    :param build: ``build(carte) -> SongSpec`` ; une ``ValueError`` y porte
        un message destiné à l'utilisateur.
    :param say: affiche un message d'état.
    :returns: le chemin relatif écrit, ou ``""`` si rien ne l'a été.
    """
    from ..core import songwriter

    card = ctx.sd_or_warn(parent, write=True)
    if card is None:
        return ""
    try:
        spec = build(card)
    except ValueError as exc:
        say(f"Morceau impossible : {exc}.")
        return ""
    except Exception as exc:  # noqa: BLE001 - rempart, cf. SPEC §6.3
        log.exception("construction du morceau impossible")
        say(f"Morceau impossible : {exc}")
        return ""

    name, ok = QInputDialog.getText(
        parent, "Écrire un morceau",
        "Nom du morceau, dans SONGS (il sera assaini pour la carte) :",
        QLineEdit.EchoMode.Normal, default_name)
    if not ok or not str(name or "").strip():
        return ""
    spec.name = str(name).strip()

    plan = songwriter.write_song(card, spec, apply=False)
    if not plan.ok:
        say(f"Morceau impossible : {plan.error}.")
        return ""
    if getattr(ctx.settings, "confirm_writes", True):
        answer = QMessageBox.question(
            parent, "Écrire le morceau",
            plan.text() + "\n\nÉcrire ce nouveau fichier sur la carte ? "
            "Aucun fichier existant n'est remplacé.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        if answer != QMessageBox.StandardButton.Yes:
            say("Rien n'a été écrit.")
            return ""

    done = songwriter.write_song(card, spec, apply=True)
    if not done.applied:
        say(f"Morceau non écrit : {done.error}.")
        return ""
    try:
        from ..core.scan import index_songs

        index_songs(card, ctx.lib, [card.abs(done.rel)])
    except Exception:  # noqa: BLE001 - l'index se rattrapera à l'analyse
        log.exception("indexation du morceau impossible")
    absents = (f" — {len(done.missing)} échantillon(s) absent(s) de la "
               f"carte" if done.missing else "")
    say(f"Morceau écrit : {done.rel}{absents}. Il se charge sur le Deluge "
        f"comme tout autre morceau.")
    return done.rel
