# -*- coding: utf-8 -*-
"""Anglais de ``delugeapp/core/dawlive.py`` : le DAW joue les sons du
Deluge, chaque piste sur son canal."""

TEXTS = {
    "%s : aucun canal libre, n'écoute pas":
        "%s: no free channel, does not listen",
    "%s : canal %d (%s)": "%s: channel %d (%s)",
    "%s : canal %d (%s), %d sons sur leurs notes General MIDI":
        "%s: channel %d (%s), %d sounds on their General MIDI notes",
    "%s : n'écoute pas (une piste %s renvoie ce qu'elle reçoit)":
        "%s: does not listen (a %s track passes on what it receives)",
    "%s : piste audio, n'écoute pas": "%s: audio track, does not listen",
    "%s DAW": "%s DAW",
    "%s existe déjà : rien n'a été écrit":
        "%s already exists: nothing was written",
    "%s n'écoute pas le canal prévu : rien n'est écrit":
        "%s does not listen to the planned channel: nothing is written",
    "Attention : %s écoutent ensemble le canal %d":
        "Warning: %s all listen to channel %d",
    "Attention : le canal %d est aussi celui de MIDI Follow ; ce que le DAW "
    "y envoie joue aussi la piste choisie sur la machine":
        "Warning: channel %d is also the MIDI Follow channel; what the DAW "
        "sends there also plays the track selected on the machine",
    "Chargez la copie sur le Deluge.": "Load the copy on the Deluge.",
    "Choisissez qui mène le tempo : le DAW envoie son horloge au Deluge, ou "
    "suit la sienne.":
        "Choose who leads the tempo: the DAW sends its clock to the Deluge, "
        "or follows the Deluge's.",
    "Dans les réglages MIDI du DAW, activez le port du Deluge en entrée et "
    "en sortie.":
        "In the DAW's MIDI settings, enable the Deluge port as input and "
        "output.",
    "Le morceau %s reste tel quel ; la copie le contient octet pour octet, "
    "plus ce qui suit.":
        "The song %s stays as it is; the copy holds it byte for byte, plus "
        "what follows.",
    "Live ▸ Préférences ▸ Link, Tempo & MIDI : sur le port du Deluge, "
    "cochez Piste en entrée et en sortie.":
        "Live ▸ Preferences ▸ Link, Tempo & MIDI: on the Deluge port, tick "
        "Track for input and output.",
    "Nouveau fichier : %s": "New file: %s",
    "Pour chaque piste du tableau : une piste MIDI dans Live, « MIDI To » "
    "sur le Deluge, et le canal indiqué.":
        "For each track in the table: a MIDI track in Live, \"MIDI To\" set "
        "to the Deluge, and the channel shown.",
    "Pour chaque piste du tableau : une piste MIDI du DAW qui sort vers le "
    "Deluge, sur le canal indiqué.":
        "For each track in the table: a DAW MIDI track that outputs to the "
        "Deluge, on the channel shown.",
    "Pour que le Deluge suive le tempo de Live : cochez aussi Sync en "
    "sortie ; pour que Live suive le Deluge : Sync en entrée, et réglez "
    "Live sur l'horloge externe (bouton EXT).":
        "For the Deluge to follow Live's tempo: also tick Sync for output; "
        "for Live to follow the Deluge: Sync for input, and set Live to the "
        "external clock (EXT button).",
    "Pour suivre le tempo du DAW : SETTINGS ▸ MIDI ▸ Clock ▸ Input sur ON. "
    "Pour le mener : Clock ▸ Output sur ON.":
        "To follow the DAW's tempo: SETTINGS ▸ MIDI ▸ Clock ▸ Input ON. To "
        "lead it: Clock ▸ Output ON.",
    "au lieu du canal %d": "instead of channel %d",
    "ce fichier n'est pas un morceau du Deluge":
        "this file is not a Deluge song",
    "chaque piste écoute déjà son canal : il n'y a rien à changer":
        "every track already listens to its channel: there is nothing to "
        "change",
    "des éléments du morceau ont disparu":
        "elements of the song have disappeared",
    "déjà réglé": "already set",
    "le fichier ne redonne pas l'original : rien n'est écrit":
        "the file does not give back the original: nothing is written",
    "le fichier ne se relit pas : %s": "the file cannot be read back: %s",
    "le morceau a changé depuis sa lecture : rien n'est écrit":
        "the song has changed since it was read: nothing is written",
    "lecture impossible : %s": "could not read: %s",
    "nouveau": "new",
    "un élément du morceau a changé : rien n'est écrit":
        "an element of the song has changed: nothing is written",
    "écriture impossible : %s": "could not write: %s",
}
