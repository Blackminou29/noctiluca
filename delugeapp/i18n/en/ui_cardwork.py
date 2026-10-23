# -*- coding: utf-8 -*-
"""Anglais de ``delugeapp/ui/cardwork.py``."""

TEXTS = {
    "%d fichier(s) attendent le Deluge (%s, %s par le câble)":
        "%d file(s) waiting for the Deluge (%s, %s over the cable)",
    "Synchronisation avec le Deluge…": "Syncing with the Deluge…",
    "La carte du Deluge s'ouvre par USB : créez la copie de travail pour y "
    "travailler.":
        "The Deluge's card opens over USB: create the working copy to work "
        "on it.",
    "Copie de travail synchronisée avec le Deluge.":
        "Working copy in sync with the Deluge.",
    "Le Deluge ouvre sa carte par USB : Réglages ▸ Carte du Deluge ▸ « Créer "
    "la copie de travail ».":
        "The Deluge opens its card over USB: Settings ▸ Deluge card ▸ “Create "
        "the working copy”.",
    "Fichiers en attente du Deluge": "Files waiting for the Deluge",
    "Le Deluge joue : la synchronisation attend l'arrêt.":
        "The Deluge is playing: the sync waits until it stops.",
    "Synchronisation avec le Deluge": "Syncing with the Deluge",
    "Le Deluge joue : la synchronisation s'est arrêtée et reprendra à "
    "l'arrêt (%s).":
        "The Deluge is playing: the sync paused and will resume when it "
        "stops (%s).",
    "rien d'envoyé": "nothing sent",
    "Le Deluge ne répond plus : la synchronisation reprendra à sa prochaine "
    "connexion.":
        "The Deluge no longer answers: the sync will resume at its next "
        "connection.",
    "%d reçu(s)": "%d received",
    "%d envoyé(s)": "%d sent",
    "%d changé(s) des deux côtés : les deux versions sont gardées":
        "%d changed on both sides: both versions are kept",
    "%d suppression(s) à confirmer (Réglages)":
        "%d deletion(s) to confirm (Settings)",
    "%d erreur(s) — voir le journal": "%d error(s) — see the log",
    "Deluge synchronisé : %s": "Deluge synced: %s",
    "Copie de travail à jour avec le Deluge.":
        "Working copy up to date with the Deluge.",
    "Synchronisation interrompue : %s": "Sync interrupted: %s",
    "Carte du Deluge": "Deluge card",
    "Branchez le Deluge en USB, avec le firmware 1.3 ou plus récent : c'est "
    "lui qui ouvre sa carte au PC.":
        "Plug the Deluge in over USB, with firmware 1.3 or later: it is the "
        "Deluge that opens its card to the PC.",
    "Lecture de la carte du Deluge": "Reading the Deluge's card",
    "La copie de travail sera créée dans :":
        "The working copy will be created in:",
    "•  %d fichiers repris de votre sauvegarde (%s, copie locale)":
        "•  %d files taken from your backup (%s, local copy)",
    "•  %d fichiers reçus du Deluge par USB (%s, %s)":
        "•  %d files received from the Deluge over USB (%s, %s)",
    "•  %d fichier(s) de musique dans votre sauvegarde mais pas sur la carte "
    "— proposés juste après":
        "•  %d music file(s) in your backup but not on the card — offered "
        "right after",
    "•  %d autre(s) fichier(s) de la sauvegarde, absents de la carte (ancien "
    "firmware, anciens réglages) : laissés dans la sauvegarde":
        "•  %d other file(s) from the backup, missing from the card (old "
        "firmware, old settings): left in the backup",
    "Rien n'est écrit sur la carte, sauf la date des fichiers que le Deluge "
    "a enregistrés : elle permet de voir ce qu'il réécrira. Votre sauvegarde "
    "n'est que lue.":
        "Nothing is written to the card, except the date of the files the "
        "Deluge saved: it shows what it will rewrite. Your backup is only "
        "read.",
    "Continuer ?": "Continue?",
    "Créer la copie de travail": "Create the working copy",
    "Copie de travail non créée.": "Working copy not created.",
    "… et %d autres": "… and %d more",
    "Dans la sauvegarde seulement": "In the backup only",
    "Ces fichiers sont dans votre sauvegarde, pas sur la carte du Deluge :"
    "\n\n%s\n\nSi l'application les a créés là, ils n'y sont jamais arrivés. "
    "Les reprendre dans la copie de travail, pour qu'ils partent sur le "
    "Deluge ? (S'ils ont été supprimés exprès sur la machine, répondez non : "
    "ils restent dans la sauvegarde.)":
        "These files are in your backup, not on the Deluge's card:\n\n%s\n\n"
        "If the application created them there, they never got to the card. "
        "Take them into the working copy, so they go to the Deluge? (If they "
        "were deleted on purpose on the machine, answer no: they stay in the "
        "backup.)",
    "Copie de travail de la carte": "Working copy of the card",
    "Copie de travail interrompue : relancez-la pour la terminer.":
        "Working copy interrupted: start it again to finish it.",
    "Copie de travail créée avec %d erreur(s) — voir le journal.":
        "Working copy created with %d error(s) — see the log.",
    "Copie de travail créée : l'application travaille désormais sur la carte "
    "du Deluge.":
        "Working copy created: the application now works on the Deluge's "
        "card.",
    "Supprimer aussi de la carte ?": "Delete from the card too?",
    "Ces fichiers ont été supprimés de la copie de travail :\n\n%s\n\nLes "
    "supprimer aussi de la carte du Deluge ? Votre sauvegarde, elle, les "
    "garde.":
        "These files were deleted from the working copy:\n\n%s\n\nDelete them "
        "from the Deluge's card too? Your backup keeps them.",
    "Comparaison avec la sauvegarde": "Comparison with the backup",
    "Sauvegarde de la carte": "Card backup",
    "Il faut une copie de travail et un dossier de sauvegarde.":
        "A working copy and a backup folder are needed.",
    "Comparaison avec la sauvegarde en cours…":
        "Comparing with the backup…",
    "La sauvegarde est déjà à jour.": "The backup is already up to date.",
    "Mettre à jour la sauvegarde": "Update the backup",
    "Dans %s :\n\n•  %d fichiers ajoutés\n•  %d remplacés — l'ancienne "
    "version est gardée à côté\n•  %d que la carte n'a plus : gardés\n\n%s à "
    "copier. Rien n'est supprimé. Continuer ?":
        "In %s:\n\n•  %d files added\n•  %d replaced — the old version is "
        "kept alongside\n•  %d that the card no longer has: kept\n\n%s to "
        "copy. Nothing is deleted. Continue?",
    "Mise à jour de la sauvegarde": "Updating the backup",
    "Sauvegarde mise à jour : %s.": "Backup updated: %s.",
    "Liste des fichiers du Deluge…": "Listing the Deluge's files…",
    "Liste des dossiers modifiés, sur le Deluge…":
        "Listing the changed folders on the Deluge…",
    "le Deluge a été débranché": "the Deluge was unplugged",
    "Deluge : %d / %d — %s": "Deluge: %d / %d — %s",
}
