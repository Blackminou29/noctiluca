# -*- coding: utf-8 -*-
"""Anglais de ``delugeapp/core/midihub.py`` : le hub MIDI, ses branchements
(« patches »), leurs états et les messages du moniteur."""

TEXTS = {
    # -- états d'un branchement ------------------------------------------- #
    "en service": "active",
    "coupé": "off",
    "hub à l'arrêt": "hub stopped",
    "la source n'est pas branchée": "the source is not plugged in",
    "la destination n'est pas branchée":
        "the destination is not plugged in",
    "le Deluge n'écoute pas cette cible":
        "the Deluge does not listen to this target",
    "coupé : boucle MIDI probable": "cut: probable MIDI loop",

    # -- les ports et les cibles ------------------------------------------ #
    "Synthé de Windows": "Windows synth",
    "l'instrument sélectionné — MIDI Follow %s":
        "the selected instrument — MIDI Follow %s",
    "la piste %s": "track %s",
    "canal %d": "channel %d",
    "canal d'origine": "original channel",
    "%s, canal %d": "%s, channel %d",
    "%s, canal non réglé sur le Deluge": "%s, channel not set on the Deluge",

    # -- un branchement en une phrase ------------------------------------- #
    "notes": "notes",
    "molette et pression": "bend and pressure",
    "contrôleurs": "controllers",
    "programmes": "programs",
    "horloge": "clock",
    "« %s » vers « %s » : %s": "“%s” to “%s”: %s",
    ", transposé de %+d demi-tons": ", transposed by %+d semitones",
    "%d bouton traduit": "%d knob translated",
    "%d boutons traduits": "%d knobs translated",
    "rien ne passe": "nothing passes",

    # -- un message en clair ---------------------------------------------- #
    "départ": "start",
    "reprise": "continue",
    "arrêt": "stop",
    "position": "position",
    "message système %02X": "system message %02X",
    "note %s, force %d": "note %s, velocity %d",
    "note %s relâchée": "note %s released",
    "contrôleur %d = %d": "controller %d = %d",
    "programme %d": "program %d",
    "molette %+d": "bend %+d",
    "pression %d": "pressure %d",
    "pression %s = %d": "pressure %s = %d",
    "%s (canal %d)": "%s (channel %d)",

    # -- refus et conseils ------------------------------------------------- #
    "Il manque la source ou la destination.":
        "The source or the destination is missing.",
    "Un appareil ne se branche pas sur lui-même : ce qu'il envoie lui "
    "reviendrait, en boucle.":
        "A device cannot be patched to itself: what it sends would come "
        "back to it, in a loop.",
    "Sur le Deluge, vérifiez que MIDI ▸ MIDI-Follow ▸ Channel ▸ Channel %s "
    "vaut %d : sans ce réglage, la machine ignore ce qu'elle reçoit.":
        "On the Deluge, check that MIDI ▸ MIDI-Follow ▸ Channel ▸ Channel "
        "%s is %d: without this setting, the machine ignores what it "
        "receives.",
    "D'après sa carte, le Deluge n'écoute pas MIDI Follow %s : réglez MIDI "
    "▸ MIDI-Follow ▸ Channel ▸ Channel %s.":
        "According to its card, the Deluge does not listen to MIDI Follow "
        "%s: set MIDI ▸ MIDI-Follow ▸ Channel ▸ Channel %s.",
    "Le Deluge n'a pas de canal pour la piste %s : réglez MIDI ▸ "
    "MIDI-Follow ▸ Channel ▸ Channel Track %s (firmware 1.3), puis laissez "
    "la carte se synchroniser.":
        "The Deluge has no channel for track %s: set MIDI ▸ MIDI-Follow ▸ "
        "Channel ▸ Channel Track %s (firmware 1.3), then let the card "
        "synchronise.",

    # -- mesures et état --------------------------------------------------- #
    "Rien n'est encore passé.": "Nothing has passed yet.",
    "%s — retard médian %s ms, au pire %s ms":
        "%s — median delay %s ms, worst %s ms",
    "%d message relayé": "%d message relayed",
    "%d messages relayés": "%d messages relayed",
    "Hub MIDI : aucun branchement.": "MIDI hub: no patch.",
    "Hub MIDI à l'arrêt.": "MIDI hub stopped.",
    "Hub MIDI : %s en service sur %d.": "MIDI hub: %s active out of %d.",
    "%d branchement": "%d patch",
    "%d branchements": "%d patches",
}
