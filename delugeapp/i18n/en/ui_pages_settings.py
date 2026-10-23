# -*- coding: utf-8 -*-
"""Anglais de ``delugeapp/ui/pages/settings.py``."""

TEXTS = {
    "Or (défaut)": "Gold (default)",
    "Cyan": "Cyan",
    "Menthe": "Mint",
    "Ambre": "Amber",
    "Magenta": "Magenta",
    "Indigo": "Indigo",
    "Réglages": "Settings",
    "Emplacement de la carte, audio, analyse et apparence":
        "Card location, audio, scanning and appearance",
    "Détecter les cartes": "Detect cards",
    "Chercher une carte Deluge sur les lecteurs branchés":
        "Look for a Deluge card on the connected drives",
    "Carte du Deluge": "Deluge card",
    "La carte reste dans le Deluge. Avec le firmware 1.3, il l'ouvre au PC "
    "par le câble USB : l'application travaille sur une <b>copie de "
    "travail</b> qu'elle tient à son image — ce que vous créez ici part sur "
    "la carte, ce que vous enregistrez sur le Deluge revient. Votre "
    "<b>sauvegarde</b>, elle, n'est que lue.":
        "The card stays in the Deluge. With firmware 1.3, it opens the card "
        "to the PC over the USB cable: the application works on a "
        "<b>working copy</b> that it keeps identical to the card — what you "
        "create here goes to the card, what you save on the Deluge comes "
        "back. Your <b>backup</b> is only ever read.",
    "Créer la copie de travail": "Create the working copy",
    "Bâtit la copie de travail face à la carte du Deluge, ou la "
    "synchronise : ce que le Deluge a enregistré descend, ce que "
    "l'application a créé monte. Le plan est montré d'abord":
        "Builds the working copy from the Deluge's card, or syncs it: what "
        "the Deluge saved comes down, what the application created goes up. "
        "The plan is shown first",
    "Suppressions à confirmer…": "Deletions to confirm…",
    "Des fichiers supprimés dans l'application existent encore sur la "
    "carte : ils ne partent qu'avec votre accord":
        "Files deleted in the application still exist on the card: they are "
        "only removed with your consent",
    "Synchroniser d'office quand le Deluge est branché":
        "Sync automatically when the Deluge is plugged in",
    "À la connexion, après chaque écriture de l'application et au retour "
    "dans la fenêtre — jamais pendant que la machine joue":
        "On connection, after each write by the application and when you "
        "come back to the window — never while the machine is playing",
    "Choisir la sauvegarde…": "Choose the backup…",
    "Le dossier qui garde une copie complète de la carte, en cas de "
    "problème. L'application le lit sans jamais y écrire":
        "The folder that keeps a full copy of the card, in case of trouble. "
        "The application reads it and never writes to it",
    "Mettre à jour la sauvegarde": "Update the backup",
    "Écrit dans la sauvegarde : ajoute ce que la carte a de nouveau, "
    "remplace ce qui a changé en gardant l'ancienne version, et n'y supprime "
    "rien. Le plan est montré d'abord":
        "Writes to the backup: adds what is new on the card, replaces what "
        "changed while keeping the old version, and deletes nothing in it. "
        "The plan is shown first",
    "Le Deluge (firmware %s) ouvre sa carte par USB.":
        "The Deluge (firmware %s) opens its card over USB.",
    "Le Deluge (firmware %s) n'ouvre pas sa carte par USB : il faut le "
    "firmware 1.3, ou glisser la carte dans un lecteur du PC (« Autre "
    "emplacement » ci-dessous).":
        "The Deluge (firmware %s) does not open its card over USB: firmware "
        "1.3 is needed, or put the card in a drive of the PC (“Other "
        "location” below).",
    "Branchez le Deluge en USB : la carte s'ouvre par le câble.":
        "Plug the Deluge in over USB: the card opens through the cable.",
    "Copie de travail : %s": "Working copy: %s",
    "Copie de travail : %s — <i>pas la carte de l'application en ce "
    "moment</i>":
        "Working copy: %s — <i>not the application's card at the moment</i>",
    "Pas encore de copie de travail. Elle se crée face à la carte, en "
    "reprenant de votre sauvegarde ce qui y est déjà.":
        "No working copy yet. It is created from the card, taking from your "
        "backup what is already in it.",
    "Synchroniser maintenant": "Sync now",
    "Suppressions à confirmer (%d)…": "Deletions to confirm (%d)…",
    "Sauvegarde de la carte : aucune choisie.":
        "Card backup: none chosen.",
    "Sauvegarde de la carte : %s — lue, jamais écrite par le travail de "
    "l'application.":
        "Card backup: %s — read, never written by the application's work.",
    "Dossier de sauvegarde de la carte": "Card backup folder",
    "Autre emplacement de carte": "Other card location",
    "Une carte glissée dans un lecteur du PC — si le firmware du Deluge "
    "n'ouvre pas sa carte par USB —, ou un autre dossier : indiquez sa "
    "racine, celle qui contient SONGS, SYNTHS, KITS et SAMPLES. La "
    "sauvegarde de la carte s'ouvre en lecture seule : l'application n'y "
    "écrit jamais.":
        "A card put in a drive of the PC — if the Deluge's firmware does not "
        "open its card over USB — or another folder: give its root, the one "
        "that holds SONGS, SYNTHS, KITS and SAMPLES. The card's backup opens "
        "read-only: the application never writes to it.",
    "D:\\  ou  C:\\Users\\…\\SDCARD Deluge":
        "D:\\  or  C:\\Users\\…\\SDCARD Deluge",
    "Parcourir…": "Browse…",
    "Utiliser cette carte": "Use this card",
    "Chemins récents": "Recent paths",
    "Aucun chemin récent": "No recent path",
    "%d chemin(s) déjà utilisé(s) — choisir…":
        "%d path(s) used before — choose…",
    "Ce dossier n'existe pas.": "This folder does not exist.",
    "Arborescence Deluge reconnue — %s libres sur %s.":
        "Deluge folder tree recognised — %s free out of %s.",
    "Arborescence Deluge reconnue.": "Deluge folder tree recognised.",
    "Dossier valide, mais ce n'est pas une carte Deluge (manque : %s).":
        "Valid folder, but it is not a Deluge card (missing: %s).",
    "Choisir la racine de la carte Deluge":
        "Choose the root of the Deluge card",
    "Dossier introuvable": "Folder not found",
    "Le dossier « %s » n'existe pas.": "The folder “%s” does not exist.",
    "Ce n'est pas une carte Deluge": "This is not a Deluge card",
    "Ce dossier ne contient pas l'arborescence attendue (SONGS, SYNTHS, "
    "KITS, SAMPLES).\n\nL'utiliser quand même ?":
        "This folder does not contain the expected folder tree (SONGS, "
        "SYNTHS, KITS, SAMPLES).\n\nUse it anyway?",
    "Carte : %s": "Card: %s",
    "Recherche des cartes branchées…": "Looking for connected cards…",
    "Aucune carte Deluge détectée automatiquement.":
        "No Deluge card detected automatically.",
    "Aucune carte détectée.": "No card detected.",
    "Utiliser la carte %s": "Use the card %s",
    "%d carte(s) détectée(s).": "%d card(s) detected.",
    "Écoute": "Listening",
    "Périphérique par défaut": "Default device",
    "Sortie audio": "Audio output",
    "Moteur": "Engine",
    "Volume d'aperçu": "Preview volume",
    "Écouter automatiquement l'échantillon sélectionné":
        "Play the selected sample automatically",
    "Sortie audio : %s": "Audio output: %s",
    "par défaut": "default",
    "Deluge branché": "Connected Deluge",
    "Branchez le Deluge en USB. L'application peut alors jouer les sons "
    "<b>sur la machine</b> plutôt qu'avec son moteur approché, et régler "
    "l'instrument <b>sélectionné sur le Deluge</b> grâce au mode MIDI Follow "
    "du firmware communautaire. Choisir le preset à distance n'est pas "
    "possible : c'est une limite de la machine, pas de l'application.":
        "Plug the Deluge in over USB. The application can then play sounds "
        "<b>on the machine</b> rather than with its approximate engine, and "
        "adjust the instrument <b>selected on the Deluge</b> thanks to the "
        "community firmware's MIDI Follow mode. Choosing the preset remotely "
        "is not possible: that is a limit of the machine, not of the "
        "application.",
    "Sortie MIDI": "MIDI output",
    "Entrée MIDI": "MIDI input",
    "Le canal que le Deluge écoute en MIDI Follow":
        "The channel the Deluge listens to in MIDI Follow",
    "Canal": "Channel",
    "Se connecter dès que le Deluge apparaît":
        "Connect as soon as the Deluge appears",
    "Écouter les presets sur le Deluge plutôt que sur l'ordinateur":
        "Play presets on the Deluge rather than on the computer",
    "Le Deluge joue alors : l'instrument sélectionné sur lui prend les "
    "réglages du preset qu'un bouton pilote — filtres, enveloppes, effets —, "
    "mais garde ses propres oscillateurs":
        "The Deluge then plays: the instrument selected on it takes the "
        "preset's knob settings — filters, envelopes, effects — but keeps its "
        "own oscillators",
    "Les outils suivent le tempo du Deluge":
        "The tools follow the Deluge's tempo",
    "Quand la machine joue, son horloge donne le tempo des écoutes, des "
    "fichiers MIDI et des morceaux de la boîte à outils":
        "When the machine plays, its clock sets the tempo of playback, MIDI "
        "files and songs in the toolbox",
    "Connecter": "Connect",
    "Ouvre ou ferme les ports MIDI choisis ci-dessus":
        "Opens or closes the MIDI ports chosen above",
    "Jouer un do": "Play a C",
    "Envoyer une note pour vérifier le câble":
        "Send a note to check the cable",
    "Tout éteindre": "All notes off",
    "Relâcher toutes les notes, sur tous les canaux":
        "Release all notes, on all channels",
    "Deluge en direct…": "Deluge Live…",
    "Écran de la machine, tempo, notes et son sélectionné":
        "The machine's screen, tempo, notes and selected sound",
    "Déconnecter": "Disconnect",
    "<b>Sur le Deluge</b>, une fois : MIDI ▸ MIDI-Follow ▸ Channel ▸ "
    "<b>Channel A = %d</b> — sans ce réglage, la machine ignore ce que "
    "l'application joue — puis MIDI-Follow ▸ Feedback ▸ <b>Channel = A</b>, "
    "pour que le son sélectionné revienne à l'application. L'horloge, elle, "
    "sort d'elle-même (MIDI ▸ Clock ▸ Output). Un kit répond à partir de la "
    "note 36 (MIDI-Follow ▸ Kit Root Note).":
        "<b>On the Deluge</b>, once: MIDI ▸ MIDI-Follow ▸ Channel ▸ "
        "<b>Channel A = %d</b> — without this setting, the machine ignores "
        "what the application plays — then MIDI-Follow ▸ Feedback ▸ "
        "<b>Channel = A</b>, so that the selected sound comes back to the "
        "application. The clock goes out by itself (MIDI ▸ Clock ▸ Output). A "
        "kit responds from note 36 (MIDI-Follow ▸ Kit Root Note).",
    "Cette machine n'expose pas de MIDI : %s":
        "This computer exposes no MIDI: %s",
    "cause inconnue": "unknown cause",
    "%d paramètre pilotable": "%d controllable parameter",
    "%d paramètres pilotables": "%d controllable parameters",
    "table lue dans %s sur la carte": "table read from %s on the card",
    "table d'usine du firmware : aucun MIDIFollow.XML lu sur la carte":
        "firmware's factory table: no MIDIFollow.XML read on the card",
    "MIDI Follow : %s — %s.": "MIDI Follow: %s — %s.",
    "Chercher le Deluge tout seul": "Find the Deluge automatically",
    "Aucun port": "No port",
    "Sortie MIDI : %s": "MIDI output: %s",
    "détection automatique": "automatic detection",
    "Firmware %s": "Firmware %s",
    "Pas de réponse SysEx (firmware officiel, ou port SysEx occupé)":
        "No SysEx reply (official firmware, or SysEx port busy)",
    "aller-retour %s": "round trip %s",
    "SysEx par « %s »": "SysEx through “%s”",
    "Écoute sur le Deluge : il faut encore le connecter.":
        "Playing on the Deluge: it still needs to be connected.",
    "Deluge déconnecté.": "Deluge disconnected.",
    "Aucun port MIDI à ouvrir.": "No MIDI port to open.",
    "Connectez d'abord le Deluge.": "Connect the Deluge first.",
    "Do central envoyé sur le canal %d.": "Middle C sent on channel %d.",
    "Toutes les notes relâchées.": "All notes released.",
    "Analyse de la carte": "Card scanning",
    "Calculer les empreintes (détection des doublons)":
        "Compute fingerprints (duplicate detection)",
    "Peu coûteux : l'empreinte rapide lit trois blocs de 64 Kio par "
    "fichier. Les doublons sont ensuite confirmés en comparant les fichiers "
    "en entier.":
        "Cheap: the quick fingerprint reads three 64 KiB blocks per file. "
        "Duplicates are then confirmed by comparing the whole files.",
    "Analyse acoustique (tempo, tonalité, niveaux)":
        "Acoustic analysis (tempo, key, levels)",
    "Nettement plus lent : environ une minute pour 1 700 échantillons. "
    "Nécessaire aux contrôles d'écrêtage et d'offset continu de la page "
    "Santé.":
        "Much slower: about a minute for 1,700 samples. Needed for the "
        "clipping and DC offset checks of the Health page.",
    "Mettre l'index à jour au démarrage": "Update the index at start-up",
    "Relit seulement les fichiers modifiés depuis la dernière analyse : une "
    "fraction de seconde. Sans cela, ce que montre l'application peut dater "
    "d'avant vos dernières modifications.":
        "Reads again only the files changed since the last scan: a fraction "
        "of a second. Without it, what the application shows may predate "
        "your latest changes.",
    "Réinitialiser l'index": "Reset the index",
    "Vide l'index SQLite. Les étiquettes, notes et favoris sont conservés.":
        "Empties the SQLite index. Tags, ratings and favourites are kept.",
    "L'index de la carte va être vidé, puis reconstruit à la prochaine "
    "analyse.\n\nVos étiquettes, notes et favoris sont conservés.\n\n"
    "Continuer ?":
        "The card index will be emptied, then rebuilt at the next scan.\n\n"
        "Your tags, ratings and favourites are kept.\n\nContinue?",
    "Remise à zéro impossible : voir le journal.": "Reset failed: see the log.",
    "Index vidé. Relancez une analyse.": "Index emptied. Run a scan again.",
    "jamais": "never",
    "Index : %d échantillons, %d presets, %d kits, %d morceaux — %s, "
    "dernière analyse : %s":
        "Index: %d samples, %d presets, %d kits, %d songs — %s, last scan: %s",
    "Index indisponible.": "Index unavailable.",
    "Sûreté des écritures": "Write safety",
    "L'application ne modifie jamais la carte sans confirmation, et toute "
    "réorganisation est d'abord présentée en simulation.":
        "The application never changes the card without confirmation, and "
        "any reorganisation is first shown as a dry run.",
    "Demander confirmation avant toute écriture":
        "Ask for confirmation before any write",
    "Créer une copie .bak avant de réécrire un XML":
        "Create a .bak copy before rewriting an XML",
    "Dossier des sauvegardes": "Backup folder",
    "Choisir le dossier des sauvegardes": "Choose the backup folder",
    "Apparence": "Appearance",
    "La palette est celle du Guide du Deluge. Chaque page porte sa couleur, "
    "celle de son pad dans la colonne de gauche. La couleur choisie ici est "
    "celle de la façade : la barre du haut, les menus et les fenêtres de "
    "dialogue.":
        "The palette is the Deluge Guide's. Each page wears its colour, the "
        "one of its pad in the left column. The colour chosen here is the "
        "front panel's: the top bar, the menus and the dialog windows.",
    "Couleur d'accent : %s": "Accent colour: %s",
    "À propos": "About",
    "Accompagne l'utilisation d'un Synthstrom Deluge : gestion de la carte "
    "SD, génération de presets et de kits, et outils de composition.\n\n"
    "Identité visuelle reprise du Guide du Deluge OLED.":
        "A companion for the Synthstrom Deluge: SD card management, preset "
        "and kit generation, and songwriting tools.\n\nVisual identity taken "
        "from the Deluge OLED Guide.",
    "Dossier de configuration :": "Configuration folder:",
    "Ouvrir": "Open",
}
