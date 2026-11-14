# -*- coding: utf-8 -*-
"""Anglais de ``delugeapp/core/atelier.py`` : le projet de l'atelier, ses pistes
et la lecture d'un morceau."""

TEXTS = {
    "Kit": "Kit",
    "Synthé": "Synth",
    "MIDI": "MIDI",
    "CV": "CV",
    "généré": "generated",
    "%s (MIDI %d)": "%s (MIDI %d)",
    "%s (CV %d)": "%s (CV %d)",
    "nature de piste inconnue : %s": "unknown track kind: %s",
    "ATELIER": "STUDIO",
    "piste inconnue": "unknown track",
    "clip inconnu": "unknown clip",
    "clip sans motif": "clip without a pattern",
    "Section": "Section",
    "ajoutez au moins une section": "add at least one section",
    "le Deluge connaît %d sections au plus":
        "the Deluge knows %d sections at most",
    "aucune section ne joue de clip": "no section plays a clip",
    "la batterie n'a pas de kit : branchez la carte, ou choisissez un kit":
        "the drums have no kit: plug in the card, or choose a kit",
    "Style : %s, %s": "Style: %s, %s",
    "%s : %d clip(s)": "%s: %d clip(s)",
    "morceau illisible": "unreadable song",
    "morceau": "song",
    "Section %d": "Section %d",
    "Rangée %d": "Row %d",
    "ce projet ne part pas d'un morceau de la carte":
        "this project does not start from a song on the card",
    "le morceau n'a plus de section libre (%d au plus)":
        "the song has no free section left (%d at most)",
    "la batterie ajoutée n'a pas de kit": "the added drums have no kit",
    "%s : piste introuvable dans le morceau":
        "%s: track not found in the song",
    "%s, %s : la piste y a déjà son clip ; il reste":
        "%s, %s: the track already has its clip there; it stays",
    "%s, %s : la piste y a déjà un clip ; le nouveau irait dans une section "
    "neuve":
        "%s, %s: the track already has a clip there; the new one would go "
        "into a new section",
    "rien à ajouter : le projet ne contient que ce que le morceau a déjà":
        "nothing to add: the project only holds what the song already has",
    "case hors du clip": "cell outside the clip",
    "ce clip est déjà sur le Deluge": "this clip is already on the Deluge",
    "brouillon d'une autre version": "draft from another version",
    "vide": "empty",
    "copie": "copy",
    "un clip ne dépasse pas %d mesures": "a clip cannot exceed %d bars",
    "une batterie ne se transpose pas": "drums cannot be transposed",
    "les notes sortiraient de l'étendue du clavier":
        "the notes would leave the range of the keyboard",
    "section inconnue": "unknown section",
    # Un clip depuis un fichier MIDI (13 novembre 2026)
    "Piste %d": "Track %d",
    "piste MIDI inconnue": "unknown MIDI track",
    "aucune note à reprendre dans cette piste":
        "no note to take from this track",
    "MIDI importé": "imported MIDI",
    "aucune note de batterie General MIDI dans cette piste":
        "no General MIDI drum note in this track",
    # Le morceau entier en audio
    "Piste %d sur %d : %s": "Track %d of %d: %s",
    "aucune piste ne sonne : placez des clips dans les sections":
        "no track plays: place clips in the sections",
    "Écriture de %s": "Writing %s",
    "Piste": "Track",
    # L'automation d'un clip (14 novembre 2026)
    "seul un clip de synthé porte une automation":
        "only a synth clip carries automation",
    "réglage inconnu : %s": "unknown setting: %s",
    "montée": "build-up",
}
