# -*- coding: utf-8 -*-
"""Anglais de ``delugeapp/ui/pages/hub.py`` : la page Hub MIDI. Un
« branchement » y est un *patch*, comme sur une baie de brassage."""

TEXTS = {
    # -- en-tête ------------------------------------------------------------ #
    "Hub MIDI": "MIDI hub",
    "L'ordinateur au centre : vos claviers, le Deluge et le DAW, reliés "
    "d'ici":
        "The computer at the centre: your keyboards, the Deluge and the "
        "DAW, patched from here",
    "Hub en marche": "Hub running",
    "Tout éteindre": "All notes off",

    # -- la grille ---------------------------------------------------------- #
    "Qui joue quoi": "Who plays what",
    "Brancher sur le Deluge": "Patch to the Deluge",
    "Connecter le Deluge": "Connect the Deluge",
    "Sur cet ordinateur, l'application ne sait pas parler MIDI : le hub "
    "attend Windows.":
        "On this computer, the application cannot speak MIDI: the hub "
        "needs Windows.",
    "Branchez un clavier ou une surface de contrôle en USB : il paraîtra "
    "ici, en rangée. Le Deluge et les autres sorties sont les colonnes. Un "
    "pad allumé à leur croisement, et ce que vous jouez part vers la "
    "machine.":
        "Plug in a USB keyboard or control surface: it will show up here, "
        "as a row. The Deluge and the other outputs are the columns. A lit "
        "pad where they cross, and what you play goes to the machine.",
    "Le hub est à l'arrêt : ses ports sont rendus aux autres logiciels. "
    "[Hub en marche] le relance.":
        "The hub is stopped: its ports are given back to the other "
        "programs. [Hub running] starts it again.",
    "Un pad éteint : cliquez pour brancher la rangée sur la colonne. Un pad "
    "allumé : cliquez pour le régler dessous ; un clic droit le coupe ou le "
    "retire.":
        "An unlit pad: click to patch the row to the column. A lit pad: "
        "click to set it below; a right-click turns it off or removes it.",
    "« %s » n'est relié à rien. Branché sur le Deluge, il joue l'instrument "
    "que vous y regardez.":
        "“%s” is not patched to anything. Patched to the Deluge, it plays "
        "the instrument you are looking at there.",
    "Le Deluge est au bout du câble, mais pas connecté : le hub ne le voit "
    "pas encore.":
        "The Deluge is at the end of the cable, but not connected: the hub "
        "does not see it yet.",
    "P%s": "T%s",

    # -- le branchement choisi ---------------------------------------------- #
    "Le branchement choisi": "The selected patch",
    "Aucun branchement choisi": "No patch selected",
    "Cliquez un pad de la grille : éteint, il branche la source sur la "
    "destination ; allumé, il se règle ici.":
        "Click a pad of the grid: unlit, it patches the source to the "
        "destination; lit, it is set here.",
    "Le Deluge joue l'instrument du clip où vous êtes ; un kit répond à "
    "partir de la note %d.":
        "The Deluge plays the instrument of the clip you are in; a kit "
        "answers from note %d upwards.",
    "En service": "Active",
    "Arrive sur :": "Arrives on:",
    "Octave −": "Octave −",
    "Octave +": "Octave +",
    " demi-tons": " semitones",
    "à la hauteur jouée": "at the pitch played",
    "%d octave": "%d octave",
    "%d octaves": "%d octaves",
    "%s%d demi-tons": "%s%d semitones",
    "Écoute :": "Listens to:",
    "tous les canaux de la source": "all the source's channels",
    "son canal %d seulement": "its channel %d only",
    "Touches :": "Keys:",
    "tout le clavier": "the whole keyboard",
    "de %s à %s": "from %s to %s",
    "Laisse passer :": "Lets through:",
    "Notes": "Notes",
    "Molette et pression": "Bend and pressure",
    "Contrôleurs": "Controllers",
    "Programmes": "Programs",
    "Horloge et transport": "Clock and transport",
    "Le canal d'origine": "The original channel",
    "Canal %d": "Channel %d",
    "Rétablir la source": "Restore the source",
    "Retirer le branchement": "Remove the patch",

    # -- les boutons d'une surface ----------------------------------------- #
    "Les boutons de la surface de contrôle": "The control surface's knobs",
    "Bouton tourné": "Knob turned",
    "Ce qu'il règle": "What it sets",
    "Apprendre un bouton": "Learn a knob",
    "Oublier ce bouton": "Forget this knob",
    "Contrôleur %d": "Controller %d",
    "%s  (contrôleur %d)": "%s  (controller %d)",
    "Ce que ce bouton règle à l'arrivée : un réglage du son du Deluge, ou "
    "un numéro de contrôleur":
        "What this knob sets on arrival: a setting of the Deluge's sound, "
        "or a controller number",
    "Tournez un bouton de « %s » : il s'ajoutera à la table.":
        "Turn a knob of “%s”: it will be added to the table.",
    "Contrôleur %d appris : choisissez ce qu'il règle.":
        "Controller %d learnt: choose what it sets.",

    # -- gestes -------------------------------------------------------------- #
    "Branché : %s.": "Patched: %s.",
    "Couper": "Turn off",
    "Remettre en service": "Turn back on",
    "Tout est éteint : %s, et le silence demandé à chaque sortie.":
        "Everything is off: %s, and silence requested from each output.",
    "%d note relâchée": "%d note released",
    "%d notes relâchées": "%d notes released",
    "Branchement retiré ; ce qu'il tenait est relâché.":
        "Patch removed; what it held is released.",

    # -- le moniteur ---------------------------------------------------------- #
    "Ce qui passe": "What goes through",
    "Vider le moniteur": "Clear the monitor",
    "%d top d'horloge": "%d clock tick",
    "%d tops d'horloge": "%d clock ticks",
    "→ %d": "→ %d",
    "→ nulle part": "→ nowhere",

    # -- le DAW ---------------------------------------------------------------- #
    "Et le DAW ?": "And the DAW?",
    "Ports virtuels trouvés : %s. Ce que vous branchez sur l'un d'eux "
    "arrive dans le DAW, qui l'ouvre comme une entrée MIDI ; ce que le DAW "
    "y envoie paraît ici en rangée, à brancher sur le Deluge. Un port "
    "virtuel rend ce qu'on lui envoie : ne le branchez pas sur ce qui "
    "l'alimente.":
        "Virtual ports found: %s. What you patch to one of them arrives in "
        "the DAW, which opens it as a MIDI input; what the DAW sends to it "
        "shows up here as a row, to patch to the Deluge. A virtual port "
        "gives back what it is sent: do not patch it to what feeds it.",
    "Aucun port virtuel sur ce PC. Votre DAW peut ouvrir lui-même le "
    "clavier et le Deluge, en même temps que le hub : Windows 11 partage "
    "les ports. Pour que le hub parle au DAW — et choisir d'ici ce qu'il "
    "reçoit —, créez une paire de ports en boucle : avec l'application « MIDI "
    "Settings » des outils de Windows MIDI Services, à installer, ou avec "
    "loopMIDI. Ils paraîtront dans la grille, sous leur nom.":
        "No virtual port on this PC. Your DAW can open the keyboard and the "
        "Deluge itself, at the same time as the hub: Windows 11 shares the "
        "ports. For the hub to talk to the DAW — and to choose from here "
        "what it receives — create a pair of loopback ports: with the “MIDI "
        "Settings” application of the Windows MIDI Services tools, to be "
        "installed, or with loopMIDI. They will show up in the grid, under "
        "their name.",
}
