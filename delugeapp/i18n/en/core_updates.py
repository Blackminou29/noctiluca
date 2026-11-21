# -*- coding: utf-8 -*-
"""Anglais de ``delugeapp/core/updates.py`` : les raisons d'un
téléchargement ou d'une installation qui n'a pas abouti."""

TEXTS: dict[str, str] = {
    "adresse refusée : %s": "address refused: %s",
    "Noctiluca, mégaoctets reçus": "Noctiluca, megabytes received",
    "téléchargement interrompu": "download interrupted",
    "le fichier dépasse la taille annoncée":
        "the file is larger than announced",
    "fichier incomplet : %d octets sur %d":
        "incomplete file: %d bytes out of %d",
    "l'empreinte SHA-256 du fichier n'est pas celle que publie GitHub":
        "the file's SHA-256 checksum is not the one GitHub publishes",
    "image disque illisible : %s": "unreadable disk image: %s",
    "l'image disque ne contient pas Noctiluca.app":
        "the disk image does not contain Noctiluca.app",
    "copie impossible : %s": "copy failed: %s",
    "AppImage introuvable": "AppImage not found",
    "application introuvable": "application not found",
    "installation automatique impossible ici":
        "automatic installation is not possible here",
}
