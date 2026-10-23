# -*- coding: utf-8 -*-
"""Anglais de ``delugeapp/ui/livewindow.py``.

Les intitulés des menus du Deluge (« MIDI ▸ MIDI-Follow ▸ Channel ▸
Channel A ») sont ceux du firmware, déjà en anglais : ils restent tels quels.
"""

TEXTS = {
    "USB : port « %s » ouvert.": "USB: port “%s” open.",
    "USB : Deluge détecté — « Connecter » ouvre ses ports.":
        "USB: Deluge detected — “Connect” opens its ports.",
    "USB : branchez le Deluge, puis « Connecter ».":
        "USB: plug in the Deluge, then “Connect”.",
    "Firmware %s (communautaire).": "Firmware %s (community).",
    "Firmware %s.": "Firmware %s.",
    "Firmware : la machine n'a pas répondu en SysEx. Le firmware officiel ne "
    "le fait pas ; le communautaire, si.":
        "Firmware: the machine did not answer over SysEx. The official "
        "firmware does not; the community one does.",
    "Liaison vérifiée : aller-retour %s.": "Link checked: round trip %s.",
    "Carte ouverte par USB : la copie de travail se tient à son image.":
        "Card open over USB: the working copy stays identical to it.",
    "Sur le Deluge, MIDI Follow est éteint : MIDI ▸ MIDI-Follow ▸ Channel ▸ "
    "Channel A = %d.":
        "On the Deluge, MIDI Follow is off: MIDI ▸ MIDI-Follow ▸ Channel ▸ "
        "Channel A = %d.",
    "Le Deluge suit le canal %d, l'application joue sur le canal %d : "
    "accordez-les (Réglages, ou MIDI ▸ MIDI-Follow ▸ Channel ▸ Channel A).":
        "The Deluge follows channel %d, the application plays on channel %d: "
        "make them match (Settings, or MIDI ▸ MIDI-Follow ▸ Channel ▸ "
        "Channel A).",
    "MIDI Follow réglé sur la machine : Channel A = %d (lu sur sa carte).":
        "MIDI Follow set on the machine: Channel A = %d (read from its card).",
    "Retour MIDI Follow éteint : MIDI ▸ MIDI-Follow ▸ Feedback ▸ Channel = "
    "A, pour que le son sélectionné revienne ici.":
        "MIDI Follow feedback is off: MIDI ▸ MIDI-Follow ▸ Feedback ▸ "
        "Channel = A, so that the selected sound comes back here.",
    "MIDI Follow : %s du son sélectionné.":
        "MIDI Follow: %s from the selected sound.",
    "%d réglage reçu": "%d setting received",
    "%d réglages reçus": "%d settings received",
    "MIDI Follow, sur le Deluge : MIDI ▸ MIDI-Follow ▸ Channel ▸ Channel A "
    "= %d, puis Feedback ▸ Channel = A. Changez ensuite d'instrument : ses "
    "réglages arrivent ici.":
        "MIDI Follow, on the Deluge: MIDI ▸ MIDI-Follow ▸ Channel ▸ Channel A "
        "= %d, then Feedback ▸ Channel = A. Then change instrument: its "
        "settings arrive here.",
    "Changez d'instrument sur le Deluge : ses réglages arrivent ici.":
        "Change instrument on the Deluge: its settings arrive here.",
    "Horloge reçue : %s BPM.": "Clock received: %s BPM.",
    "Horloge : dernier tempo %s BPM (machine arrêtée).":
        "Clock: last tempo %s BPM (machine stopped).",
    "Horloge : lancez la lecture sur le Deluge. Elle part par défaut (MIDI ▸ "
    "Clock ▸ Output).":
        "Clock: start playback on the Deluge. It is sent by default (MIDI ▸ "
        "Clock ▸ Output).",
    "Deluge en direct — Deluge Companion": "Deluge Live — Deluge Companion",
    "DELUGE EN DIRECT": "DELUGE LIVE",
    "Écran de la machine": "The machine's screen",
    "Recopier l'écran": "Mirror the screen",
    "La machine envoie ce qui change sur son écran, au moment où cela "
    "change ; l'abonnement est renouvelé chaque seconde. Rien n'est modifié "
    "sur le Deluge":
        "The machine sends what changes on its screen, as it changes; the "
        "subscription is renewed every second. Nothing is changed on the "
        "Deluge",
    "Faire signe": "Say hello",
    "Le Deluge affiche « HELLO SYSEX » un instant : de quoi vérifier, sur la "
    "machine, que c'est bien elle qui est connectée. Rien d'autre ne change":
        "The Deluge shows “HELLO SYSEX” for a moment: a way to check, on the "
        "machine, that it is the one connected. Nothing else changes",
    "Vérifier": "Check",
    "Redemande sa version à la machine et mesure l'aller-retour":
        "Asks the machine for its version again and measures the round trip",
    "Tout éteindre": "All notes off",
    "Relâche toutes les notes, sur tous les canaux":
        "Releases all notes, on all channels",
    "Tempo et notes": "Tempo and notes",
    "Horloge muette": "Clock silent",
    "Aucune note tenue": "No note held",
    "Aucune note reçue — seules les pistes MIDI du Deluge envoient leurs "
    "notes, pas ses synthés ni ses kits.":
        "No note received — only the Deluge's MIDI tracks send their notes, "
        "not its synths or kits.",
    "Son sélectionné sur la machine": "Sound selected on the machine",
    "Réglage": "Setting",
    "Valeur": "Value",
    "Rien de reçu : activez le retour MIDI Follow sur la machine, puis "
    "changez d'instrument.":
        "Nothing received: turn on MIDI Follow feedback on the machine, then "
        "change instrument.",
    "Réglages à faire sur le Deluge": "Settings to make on the Deluge",
    "Connecter": "Connect",
    "Ouvre les ports du Deluge : notes et contrôleurs par le premier, SysEx "
    "par le troisième":
        "Opens the Deluge's ports: notes and controllers through the first, "
        "SysEx through the third",
    "Réglages MIDI…": "MIDI settings…",
    "Ports, canal, écoute sur la machine : la page Réglages":
        "Ports, channel, playing on the machine: the Settings page",
    "Recopie arrêtée.": "Mirroring stopped.",
    "Déconnecter": "Disconnect",
    "Aucun lien MIDI.": "No MIDI link.",
    "Le Deluge n'est pas connecté.": "The Deluge is not connected.",
    "En attente de l'image… Un Deluge au firmware officiel ne l'envoie pas.":
        "Waiting for the image… A Deluge on the official firmware does not "
        "send it.",
    "▶  En lecture": "▶  Playing",
    "■  À l'arrêt": "■  Stopped",
    "Le retour MIDI Follow est actif sur la machine : changez d'instrument "
    "ou tournez un bouton, ses réglages arrivent ici.":
        "MIDI Follow feedback is on on the machine: change instrument or turn "
        "a knob, its settings arrive here.",
}
