# -*- coding: utf-8 -*-
"""Anglais de ``delugeapp/ui/aide.py`` : ce que fait chaque commande."""

TEXTS = {
    "Au démarrage, au plus une fois par jour, lit sur GitHub le numéro de la "
    "dernière version, et vous prévient si elle est plus récente. Rien "
    "d'autre ne part sur le réseau":
        "At start-up, at most once a day, reads the number of the latest "
        "version on GitHub, and tells you if it is newer. Nothing else goes "
        "out on the network",
    "**Écrit sur la carte.** Tire du son choisi une table d'onde — une "
    "période prélevée 64 fois, du début à la fin — et l'écrit dans "
    "SAMPLES/WAVETABLES, après votre accord":
        "**Writes to the card.** Draws a wavetable from the chosen sound — one "
        "period taken 64 times, from start to end — and writes it into "
        "SAMPLES/WAVETABLES, after your go-ahead",
    "**Écrit sur la carte.** Pose le son sur le premier pad libre des "
    "favoris d'échantillons du Deluge — ou l'en retire —, après votre accord":
        "**Writes to the card.** Puts the sound on the first free pad of the "
        "Deluge's sample favourites — or takes it off —, after your go-ahead",
    "Fait des sons d'un dossier un preset multi-échantillon : une tranche du "
    "clavier par son, la hauteur lue dans le nom ou à l'écoute. Le plan est "
    "montré avant d'écrire dans SYNTHS":
        "Turns a folder's sounds into a multisample preset: one keyboard "
        "range per sound, the pitch read from the name or by listening. The "
        "plan is shown before writing into SYNTHS",
    "Les sons que la piste a eus avant celui-ci, du plus récent au plus "
    "ancien : ce que « Autre son » a remplacé n'est pas perdu":
        "The sounds the track had before this one, newest first: what "
        "“Another sound” replaced is not lost",
    "Rend à la piste le son choisi dans la liste d'à côté ; le son actuel y "
    "prend sa place":
        "Gives the track back the sound chosen in the list next to it; the "
        "current sound takes its place there",
    "Le nom est demandé et le plan montré avant d'écrire ; aucun fichier "
    "existant n'est remplacé":
        "You are asked for a name and shown the plan before anything is "
        "written; no existing file is replaced",
    "Coupe l'écoute en cours  (Espace)": "Stops the current playback  (Space)",
    "Aller choisir l'emplacement de la carte dans les réglages":
        "Go and choose the card's location in the settings",
    "Cherche une carte Deluge sur les lecteurs branchés : est reconnu tout "
    "dossier contenant au moins deux des dossiers SONGS, SYNTHS, KITS et "
    "SAMPLES":
        "Looks for a Deluge card on the connected drives: any folder holding "
        "at least two of the SONGS, SYNTHS, KITS and SAMPLES folders is "
        "recognised",
    "Ouvre le dossier du fichier dans l'explorateur Windows — rien n'est "
    "modifié":
        "Opens the file's folder in Windows Explorer — nothing is changed",

    # -- Échantillons --------------------------------------------------------
    "Joue l'échantillon sélectionné sur l'ordinateur  (ou sur le Deluge si "
    "vous l'avez demandé dans les réglages)":
        "Plays the selected sample on the computer  (or on the Deluge if you "
        "asked for it in the settings)",
    "Filtre la liste sur le nom du fichier ; la recherche part toute seule "
    "après une courte pause":
        "Filters the list by file name; the search starts by itself after a "
        "short pause",
    "Ne montre que les échantillons d'une catégorie — celle-ci vient du "
    "dossier où ils sont rangés":
        "Shows only the samples of one category — it comes from the folder "
        "they are stored in",
    "Ne montre que les sons d'une certaine longueur : utile pour isoler les "
    "frappes courtes des nappes":
        "Shows only sounds of a certain length: handy to tell short hits "
        "from pads",
    "Ne montre que les échantillons marqués d'une étoile pleine dans "
    "l'aperçu":
        "Shows only the samples marked with a full star in the preview",
    "Marque ce son comme favori ; le filtre « Favoris » au-dessus s'en sert":
        "Marks this sound as a favourite; the “Favourites” filter above uses "
        "it",
    "Ne montre que les sons qu'aucun preset, kit ni morceau n'utilise — "
    "candidats au rangement":
        "Shows only the sounds that no preset, kit or song uses — candidates "
        "for tidying up",
    "Ne montre que les fichiers réclamés par un preset mais absents de la "
    "carte":
        "Shows only the files a preset asks for but that are missing from "
        "the card",
    "**Écrit sur la carte.** Choisissez des sons ou des presets du PC : le "
    "plan montre où chacun ira, ce qui est déjà sur la carte et ce que le "
    "Deluge refuserait, avant toute copie. Un dossier ou un pack entier se "
    "glisse sur la fenêtre  (Ctrl+I)":
        "**Writes to the card.** Choose sounds or presets on the PC: the plan "
        "shows where each one will go, what is already on the card and what "
        "the Deluge would refuse, before anything is copied. A folder or a "
        "whole pack can be dropped on the window  (Ctrl+I)",

    # -- Presets -------------------------------------------------------------
    "Rend le preset et le joue — approximation calculée par l'ordinateur, ou "
    "vrai son de la machine si le Deluge est branché et l'écoute réglée sur "
    "lui":
        "Renders the preset and plays it — an approximation computed by the "
        "computer, or the machine's real sound if the Deluge is plugged in and "
        "playback is set to it",
    "Filtre les presets sur leur nom": "Filters the presets by name",
    "Ne montre que les presets d'une catégorie, déduite de leur dossier et "
    "de leur contenu":
        "Shows only the presets of one category, worked out from their "
        "folder and their content",
    "Copie le preset sous un nouveau nom, dans le même dossier de la carte — "
    "l'original n'est pas touché":
        "Copies the preset under a new name, in the same folder of the card "
        "— the original is not touched",
    "Ouvre ce preset dans le générateur pour le muter ou en tirer des "
    "variantes — l'original n'est jamais réécrit":
        "Opens this preset in the generator to mutate it or draw variations "
        "from it — the original is never rewritten",

    # -- Kits ----------------------------------------------------------------
    "Joue l'échantillon de la rangée choisie dans le tableau":
        "Plays the sample of the row chosen in the table",
    "Joue le motif d'essai avec les sons du kit : sur le Deluge s'il est "
    "branché, sinon en rendu approché":
        "Plays the test pattern with the kit's sounds: on the Deluge if it is "
        "plugged in, otherwise as an approximate render",
    "Filtre les kits sur leur nom": "Filters the kits by name",
    "Charge un motif rythmique typique du genre, limité aux rangées que ce "
    "kit possède":
        "Loads a rhythm pattern typical of the genre, limited to the rows "
        "this kit has",
    "Écrit le motif d'essai dans un fichier .mid, à l'endroit que vous "
    "choisirez — hors de la carte":
        "Writes the test pattern to a .mid file, wherever you choose — "
        "outside the card",

    # -- Morceaux ------------------------------------------------------------
    "Filtre les morceaux sur leur nom": "Filters the songs by name",
    "Écrit le clip choisi dans un fichier .mid, à l'endroit que vous "
    "choisirez":
        "Writes the chosen clip to a .mid file, wherever you choose",
    "Écrit toutes les pistes du morceau dans un seul fichier .mid, une piste "
    "par clip":
        "Writes all the song's tracks to a single .mid file, one track per "
        "clip",
    "Copie le morceau **et tout ce dont il dépend** (presets, kits, "
    "échantillons) dans un dossier à part : de quoi l'emporter ailleurs sans "
    "rien perdre":
        "Copies the song **and everything it depends on** (presets, kits, "
        "samples) into a separate folder: enough to take it elsewhere without "
        "losing anything",
    "Écrit une page web décrivant le morceau : tempo, clips, instruments, "
    "échantillons utilisés":
        "Writes a web page describing the song: tempo, clips, instruments, "
        "samples used",

    # -- Générateur ----------------------------------------------------------
    "Fabrique un preset complet à partir du genre, du rôle et de la graine "
    "ci-dessous  (rien n'est encore écrit sur la carte)":
        "Builds a complete preset from the genre, role and seed below  "
        "(nothing is written to the card yet)",
    "Tire un genre, un rôle et une graine au hasard, puis génère":
        "Picks a genre, a role and a seed at random, then generates",
    "Repart du son actuel et en change quelques réglages : de quoi explorer "
    "autour d'une idée qui plaît":
        "Starts from the current sound and changes a few settings: a way to "
        "explore around an idea you like",
    "Joue le son généré — sur le Deluge s'il est branché et l'écoute réglée "
    "sur lui, sinon en rendu approché":
        "Plays the generated sound — on the Deluge if it is plugged in and "
        "playback is set to it, otherwise as an approximate render",
    "**Écrit sur la carte.** Demande un nom et un sous-dossier de SYNTHS, "
    "puis y écrit le preset ; un fichier du même nom n'est remplacé qu'après "
    "une question":
        "**Writes to the card.** Asks for a name and a SYNTHS subfolder, then "
        "writes the preset there; a file with the same name is only replaced "
        "after a question",
    "Ce que le son doit faire dans un morceau : une basse ne se règle pas "
    "comme une nappe":
        "What the sound has to do in a song: a bass is not set up like a pad",
    "Moteur de synthèse. « Choisi par le genre » laisse le générateur "
    "décider, ce qui donne les sons les plus typés":
        "Synthesis engine. “Chosen by the genre” lets the generator decide, "
        "which gives the most characteristic sounds",
    "Deux générations avec la même graine et les mêmes réglages donnent "
    "exactement le même son":
        "Two generations with the same seed and the same settings give "
        "exactly the same sound",
    "Crée huit cousins du son actuel ; un clic les écoute, un double-clic en "
    "adopte un":
        "Creates eight cousins of the current sound; a click plays one, a "
        "double-click adopts it",
    "Mélange le son courant avec celui choisi dans l'historique : les "
    "réglages se mélangent selon le dosage, les formes d'onde basculent à "
    "mi-chemin":
        "Blends the current sound with the one chosen in the history: the "
        "settings mix according to the amount, the waveforms switch halfway",
    "Dosage du fondu : à gauche le son courant, à droite le son choisi dans "
    "l'historique":
        "Morph amount: on the left the current sound, on the right the sound "
        "chosen in the history",
    "Fabrique plusieurs presets d'un coup et les écrit dans un dossier de la "
    "carte que vous choisirez":
        "Builds several presets at once and writes them to a folder of the "
        "card you choose",
    "Assemble un kit autour d'une machine ou d'une banque de la carte (909, "
    "Linndrum, un kit d'artiste…), choisie selon le genre, puis complète les "
    "rôles manquants  (rien n'est encore écrit)":
        "Assembles a kit around a drum machine or a bank from the card (909, "
        "Linndrum, an artist kit…), chosen for the genre, then fills in the "
        "missing roles  (nothing is written yet)",
    "**Écrit sur la carte.** Écrit le kit dans KITS/, sous le nom indiqué ; "
    "un fichier du même nom n'est remplacé qu'après une question":
        "**Writes to the card.** Writes the kit into KITS/, under the name "
        "given; a file with the same name is only replaced after a question",
    "Remplace le son de la rangée choisie dans la liste par un autre du même "
    "rôle — de la même machine d'abord, puis d'une machine voisine — sans "
    "toucher au reste du kit  (rien n'est encore écrit)":
        "Replaces the sound of the row chosen in the list with another one "
        "of the same role — from the same machine first, then from a similar "
        "machine — without touching the rest of the kit  (nothing is written "
        "yet)",
    "Oriente le choix des sons : une grosse caisse techno ne ressemble pas à "
    "une grosse caisse funk":
        "Steers the choice of sounds: a techno kick does not sound like a "
        "funk kick",
    "Même graine, même kit : de quoi retrouver un assemblage qui vous "
    "plaisait":
        "Same seed, same kit: a way to get back a combination you liked",
    "Nom du fichier qui sera écrit dans KITS/":
        "Name of the file that will be written to KITS/",
    "Limite la recherche d'échantillons à un dossier de la carte ; vide, "
    "toute la bibliothèque est candidate":
        "Limits the sample search to one folder of the card; when empty, the "
        "whole library is a candidate",

    # -- Outils --------------------------------------------------------------
    "Note de départ de la gamme": "Starting note of the scale",
    "Type de gamme : change les notes proposées et les accords ci-dessous":
        "Type of scale: changes the suggested notes and the chords below",
    "Copie la liste de notes dans le presse-papier, au format que le Deluge "
    "écrit dans ses fichiers":
        "Copies the list of notes to the clipboard, in the format the Deluge "
        "writes in its files",
    "Décale le motif d'un ou plusieurs pas, sans changer ses coups":
        "Shifts the pattern by one or more steps, without changing its hits",
    "Swing d'échantillonneur en pourcentage (58 % léger, 66 % ternaire), ou "
    "jeu derrière / devant le temps. Le même pourcentage se règle dans le "
    "swing du Deluge":
        "Sampler-style swing as a percentage (58% light, 66% triplet), or "
        "playing behind / ahead of the beat. The same percentage can be set "
        "in the Deluge's swing",
    "Swing libre ajouté au groove, de droit à ternaire":
        "Free swing added to the groove, from straight to triplet",
    "Tempo servant à tous les calculs de cette page":
        "Tempo used for all the calculations on this page",
    "Fréquence d'échantillonnage supposée pour le calcul de place":
        "Sample rate assumed for the space calculation",
    "Résolution supposée : 24 bits occupe une fois et demie la place de 16":
        "Assumed bit depth: 24 bits takes one and a half times the space of 16",
    "Une piste stéréo occupe deux fois la place d'une mono":
        "A stereo track takes twice the space of a mono one",
    "Durée totale d'audio dont vous voulez connaître le poids":
        "Total length of audio whose size you want to know",
    "Tapez une tonalité (Am, C, F#m) pour voir ses voisines sur la roue":
        "Type a key (Am, C, F#m) to see its neighbours on the wheel",
    "Montre les échantillons de la carte dans cette tonalité et dans les "
    "tonalités compatibles":
        "Shows the card's samples in this key and in the compatible keys",

    # -- Santé ---------------------------------------------------------------
    "Relit l'index déjà constitué et cherche les anomalies : ne touche pas à "
    "la carte, et prend moins d'une seconde":
        "Reads the existing index again and looks for problems: does not "
        "touch the card, and takes less than a second",
    "Montre d'abord le plan exact des opérations ; rien n'est fait avant "
    "votre accord":
        "Shows the exact plan of operations first; nothing is done without "
        "your consent",
    "Écrit le diagnostic dans une page HTML, à l'endroit que vous "
    "choisirez — hors de la carte":
        "Writes the diagnosis to an HTML page, wherever you choose — off the "
        "card",
    "Lequel des doublons garder : les autres seront proposés à la "
    "suppression":
        "Which of the duplicates to keep: the others will be offered for "
        "deletion",
    "**Écrit sur la carte.** Montre d'abord la liste exacte des fichiers à "
    "supprimer ; seuls les fichiers rigoureusement identiques, vérifiés "
    "octet par octet, sont concernés":
        "**Writes to the card.** Shows the exact list of files to delete "
        "first; only strictly identical files, checked byte by byte, are "
        "affected",
    "Cherche sur la carte des fichiers qui pourraient remplacer les "
    "échantillons manquants — ne modifie rien":
        "Looks on the card for files that could replace the missing samples "
        "— changes nothing",
    "**Écrit sur la carte.** Corrige les presets pour qu'ils pointent vers "
    "les remplaçants trouvés ; une copie .bak est laissée à côté de chaque "
    "fichier modifié":
        "**Writes to the card.** Fixes the presets so they point to the "
        "replacements found; a .bak copy is left next to each modified file",
    "**Déplace des fichiers.** Les échantillons inutilisés vont dans un "
    "dossier _UNUSED de la carte : rien n'est supprimé, tout est "
    "récupérable":
        "**Moves files.** Unused samples go into an _UNUSED folder on the "
        "card: nothing is deleted, everything can be recovered",
    "Compresse la sauvegarde : plus lente à écrire, bien plus petite sur le "
    "disque":
        "Compresses the backup: slower to write, much smaller on the disk",
    "Copie toute la carte dans le dossier de sauvegarde indiqué dans les "
    "réglages":
        "Copies the whole card to the backup folder set in the settings",
    "Montre ce qui a changé entre la sauvegarde choisie et la carte telle "
    "qu'elle est aujourd'hui":
        "Shows what changed between the chosen backup and the card as it is "
        "today",
    "**Écrase des fichiers de la carte** par ceux de la sauvegarde. Le plan "
    "exact est montré avant, et rien ne part sans votre accord":
        "**Overwrites files on the card** with those from the backup. The "
        "exact plan is shown first, and nothing happens without your consent",

    # -- Réglages ------------------------------------------------------------
    "Dossier racine de la carte : celui qui contient SONGS, SYNTHS, KITS et "
    "SAMPLES":
        "Root folder of the card: the one that holds SONGS, SYNTHS, KITS and "
        "SAMPLES",
    "Choisir un dossier dans une fenêtre, plutôt que de taper son chemin":
        "Choose a folder in a window, rather than typing its path",
    "Adopte ce chemin et relit la carte":
        "Uses this path and reads the card again",
    "Cartes utilisées récemment": "Recently used cards",
    "Cherche une carte Deluge sur les lecteurs branchés : est reconnu tout "
    "dossier qui contient au moins deux dossiers du Deluge":
        "Looks for a Deluge card on the connected drives: any folder holding "
        "at least two Deluge folders is recognised",
    "Où l'application joue ses aperçus audio":
        "Where the application plays its audio previews",
    "Volume des aperçus, sans effet sur le Deluge":
        "Volume of the previews, with no effect on the Deluge",
    "Un simple clic dans la liste joue le son, sans avoir à viser le bouton "
    "Écouter":
        "A single click in the list plays the sound, without having to aim "
        "for the Listen button",
    "Calcule une empreinte de chaque fichier : l'analyse est plus lente, "
    "mais les doublons sont détectés par leur contenu et non par leur nom":
        "Computes a fingerprint of each file: the scan is slower, but "
        "duplicates are detected by their content rather than their name",
    "Mesure tempo, tonalité et niveaux de chaque échantillon : beaucoup plus "
    "lent, mais c'est ce qui alimente la recherche par ressemblance":
        "Measures the tempo, key and levels of each sample: much slower, but "
        "it is what feeds the similarity search",
    "À chaque démarrage, relit seulement les fichiers de la carte modifiés "
    "depuis la dernière analyse, en arrière-plan — la carte n'est que lue":
        "At each start, reads again only the card files changed since the "
        "last scan, in the background — the card is only read",
    "Vide l'index de l'application. **La carte n'est pas touchée** ; il "
    "faudra relancer une analyse":
        "Empties the application's index. **The card is not touched**; you "
        "will need to run a scan again",
    "Relit chaque fichier de la carte, même ceux qui n'ont pas changé, et "
    "refait empreintes et mesures. La carte n'est que lue ; [Analyser la "
    "carte] suffit d'ordinaire":
        "Reads every file of the card again, even unchanged ones, and redoes "
        "fingerprints and measurements. The card is only read; [Scan card] "
        "is usually enough",
    "Le nom d'une étiquette à poser sur ce son — « sombre », « à garder », "
    "« live »… Entrée l'ajoute ; elle reste sur l'ordinateur, pas sur la "
    "carte":
        "The name of a tag to put on this sound — “dark”, “keeper”, "
        "“live”… Enter adds it; it stays on the computer, not on the card",
    "Pose l'étiquette écrite à côté sur le son choisi":
        "Puts the tag typed next to it on the chosen sound",
    "**Écrase des fichiers.** Remet les originaux d'un traitement précédent, "
    "gardés dans _BACKUP ; la version actuelle y est mise de côté avant":
        "**Overwrites files.** Puts back the originals of an earlier "
        "treatment, kept in _BACKUP; the current version is set aside there "
        "first",
    "Ne montre que les sons qui portent une étiquette ; il apparaît dès que "
    "vous en avez posé une":
        "Shows only the sounds that carry a tag; it appears as soon as you "
        "have put one",
    "Garde-fou : aucune écriture sur la carte sans une question préalable":
        "Safeguard: nothing is written to the card without asking first",
    "Garde-fou : chaque XML réécrit laisse une copie .bak datée à côté de lui":
        "Safeguard: each rewritten XML leaves a dated .bak copy next to it",
    "Où les sauvegardes complètes de la carte sont écrites ; vide, elles "
    "vont dans le dossier de configuration de l'application":
        "Where the full backups of the card are written; when empty, they go "
        "into the application's configuration folder",
    "Ouvre le dossier de configuration de l'application (réglages, index, "
    "journal)":
        "Opens the application's configuration folder (settings, index, log)",
    "Ouvre les ports dès que la machine apparaît, sans rien demander":
        "Opens the ports as soon as the machine appears, without asking",
    "Les presets sonneront sur le Deluge : l'instrument sélectionné sur lui "
    "prend leurs filtres, enveloppes et effets, mais garde ses propres "
    "oscillateurs":
        "Presets will sound on the Deluge: the instrument selected on it takes "
        "their filters, envelopes and effects, but keeps its own oscillators",
    "Port par lequel l'application parle au Deluge":
        "Port through which the application talks to the Deluge",
    "Port par lequel elle l'écoute ; facultatif":
        "Port through which it listens to it; optional",
    "Canal que le Deluge écoute en mode MIDI Follow : il doit être réglé sur "
    "la machine aussi (MIDI ▸ MIDI-Follow ▸ Channel ▸ Channel A)":
        "Channel the Deluge listens to in MIDI Follow mode: it must be set on "
        "the machine too (MIDI ▸ MIDI-Follow ▸ Channel ▸ Channel A)",
    "Quand la machine joue, son horloge donne le tempo des outils : écoutes, "
    "fichiers MIDI et morceaux de la boîte à outils":
        "When the machine plays, its clock sets the tempo of the tools: "
        "playback, MIDI files and songs from the toolbox",
    "Ouvre une fenêtre à garder à côté : l'écran du Deluge recopié, son "
    "tempo, les notes de ses pistes MIDI et les réglages du son sélectionné — "
    "rien n'est écrit sur la machine":
        "Opens a window to keep alongside: the Deluge's mirrored screen, its "
        "tempo, the notes of its MIDI tracks and the settings of the selected "
        "sound — nothing is written to the machine",
    "Ouvre les ports du Deluge : notes et contrôleurs par le premier, SysEx "
    "par le troisième ; la machine dit alors sa version":
        "Opens the Deluge's ports: notes and controllers through the first, "
        "SysEx through the third; the machine then reports its version",
    "Envoie une note au Deluge pour vérifier le câble":
        "Sends a note to the Deluge to check the cable",
    "Relâche toutes les notes, sur tous les canaux : le bouton de secours si "
    "un son reste coincé":
        "Releases all notes, on all channels: the emergency button if a "
        "sound gets stuck",

    # -- Tableau de bord -----------------------------------------------------
    "Ouvre le diagnostic complet de la carte":
        "Opens the card's full diagnosis",
    "Fait la chose proposée ci-contre, ou vous mène directement à l'endroit "
    "où elle se fait":
        "Does the suggested task, or takes you straight to where it is done",
    "Relit la carte et met l'index à jour  (Ctrl+R)":
        "Reads the card again and updates the index  (Ctrl+R)",
    "Interrompt l'analyse ; ce qui a déjà été lu est conservé":
        "Stops the scan; what has already been read is kept",
    "Échange tout de suite avec le Deluge branché : ce qu'il a enregistré "
    "descend, ce que l'application a créé ou reçu du PC monte  (Ctrl+Maj+D)":
        "Exchanges with the connected Deluge right now: what it saved comes "
        "down, what the application created or received from the PC goes up  "
        "(Ctrl+Shift+D)",
    "**Écrit sur la carte.** Choisir des fichiers du PC à envoyer au Deluge "
    "; le plan est montré avant toute copie. Un dossier ou un pack se glisse "
    "sur la fenêtre  (Ctrl+I)":
        "**Writes to the card.** Choose files on the PC to send to the "
        "Deluge; the plan is shown before anything is copied. A folder or a "
        "pack can be dropped on the window  (Ctrl+I)",
    "Ouvre les réglages de la carte du Deluge : copie de travail, "
    "synchronisation et sauvegarde":
        "Opens the Deluge card settings: working copy, sync and backup",
    "**Écrit dans votre sauvegarde.** Y ajoute ce qui lui manque et remplace "
    "ce qui a changé, l'ancienne version gardée à côté ; rien n'y est "
    "supprimé. Le plan est montré d'abord":
        "**Writes to your backup.** Adds what it is missing and replaces what "
        "changed, keeping the old version alongside; nothing in it is "
        "deleted. The plan is shown first",
    "(%s sans nom)": "(unnamed %s)",
    "Ouvre dans l'atelier un morceau de la carte — les derniers reçus du "
    "Deluge en tête : ses pistes, ses clips, son tempo et sa gamme deviennent "
    "ceux du projet, sa progression est lue dans ses notes. Rien n'est modifié":
        "Opens a song from the card in the studio — the latest received from "
        "the Deluge first: its tracks, its clips, its tempo and its scale "
        "become the project's, its progression is read from its notes. "
        "Nothing is changed",
    "**Écrit sur la carte.** Crée dans SONGS un morceau neuf : une section du "
    "Deluge par section du projet, leurs clips, leurs répétitions et "
    "l'arrangement complet. ":
        "**Writes to the card.** Creates a new song in SONGS: one Deluge "
        "section per project section, their clips, their repeats and the "
        "complete arrangement. ",
    "**Écrit sur la carte.** Écrit une nouvelle version du morceau d'origine "
    "(« Cool1 5 » après « Cool1 4 ») qui le contient octet pour octet, plus "
    "vos pistes, vos clips et vos sections neuves ; l'original n'est pas "
    "touché. Le plan est montré avant d'écrire":
        "**Writes to the card.** Writes a new version of the original song "
        "(“Cool1 5” after “Cool1 4”) that contains it byte for byte, plus "
        "your new tracks, clips and sections; the original is not touched. "
        "The plan is shown before writing",
    "Tonique du morceau : accords, basse et mélodie restent dans sa gamme":
        "Root of the song: chords, bass and melody stay in its scale",
    "Gamme du morceau ; le morceau écrit la donne au mode gamme du Deluge":
        "Scale of the song; the written song gives it to the Deluge's scale "
        "mode",
    "Tempo du morceau ; choisir un genre le place au milieu de sa plage":
        "Tempo of the song; choosing a genre puts it in the middle of its "
        "range",
    "Ambiance de la progression d'accords — mélancolique, house, jazz… ; par "
    "défaut, celle du genre":
        "Mood of the chord progression — melancholic, house, jazz…; by "
        "default, the genre's",
    "Triades, septièmes, neuvièmes ou suspendus ; par défaut, ce que "
    "l'ambiance appelle":
        "Triads, sevenths, ninths or suspended chords; by default, what the "
        "mood calls for",
    "Même graine et mêmes réglages, même morceau : notez-la pour retrouver "
    "une composition":
        "Same seed and same settings, same song: note it down to find a "
        "composition again",
    "Nouvelle graine au hasard": "New random seed",
    "Nature de la piste à ajouter : un kit, un synthé du Deluge, une piste "
    "MIDI vers un appareil extérieur, ou une piste CV vers un modulaire":
        "Kind of track to add: a kit, a Deluge synth, a MIDI track to an "
        "external device, or a CV track to a modular",
    "Ce que jouera la piste ajoutée": "What the added track will play",
    "Ajoute la piste au projet, avec un son du style et un premier clip  "
    "(rien n'est écrit sur la carte)":
        "Adds the track to the project, with a sound in the style and a first "
        "clip  (nothing is written to the card)",
    "Retire la piste choisie du projet, et ses cases de toutes les sections":
        "Removes the chosen track from the project, and its cells from every "
        "section",
    "Joue le son de la piste — sur le Deluge si l'écoute y est réglée, sinon "
    "en rendu approché ; une batterie joue son premier clip":
        "Plays the track's sound — on the Deluge if listening is set to it, "
        "otherwise as an approximate render; drums play their first clip",
    "Un autre son du même style pour un synthé, ou un autre kit bâti dans "
    "votre bibliothèque":
        "Another sound in the same style for a synth, or another kit built "
        "from your library",
    "Prend pour la piste un preset ou un kit de la carte, choisi dans l'index":
        "Takes a preset or a kit from the card for the track, chosen in the "
        "index",
    "Canal MIDI (1 à 16) ou sortie CV (1 ou 2) de la piste":
        "MIDI channel (1 to 16) or CV output (1 or 2) of the track",
    "Huit variantes du son, toutes dans le style : un seul aspect tiré à "
    "nouveau (filtre, enveloppes, espace…) ou un curseur poussé (plus "
    "brillant, plus sale…), le reste du son restant le même. Un son retouché "
    "à la main garde ses retouches":
        "Eight variations of the sound, all in the style: a single facet "
        "drawn again (filter, envelopes, space…) or a slider pushed "
        "(brighter, dirtier…), the rest of the sound staying the same. A "
        "sound edited by hand keeps its edits",
    "La piste prend le son de la variante choisie":
        "The track takes the sound of the chosen variation",
    "Joue le clip choisi sur l'ordinateur, avec le son de sa piste":
        "Plays the chosen clip on the computer, with its track's sound",
    "Joue le clip en boucle sur le Deluge, dans le clip que suit MIDI Follow "
    ": machine en lecture, calé sur sa mesure ; en enregistrement (REC), il "
    "s'y inscrit. Recliquez pour arrêter":
        "Loops the clip on the Deluge, in the clip MIDI Follow is following: "
        "machine playing, locked to its bar; recording (REC), it is written "
        "into it. Click again to stop",
    "Une variation du clip, ajoutée à la piste : rythme, notes, plus ou moins "
    "de notes, réponse, octave, fin de phrase — pour une batterie, ornements, "
    "remplissage, cassure, montée…":
        "A variation of the clip, added to the track: rhythm, notes, more or "
        "fewer notes, answer, octave, end of phrase — for drums, ornaments, "
        "fill, breakdown, build-up…",
    "Un clip neuf pour la piste, sur la progression du morceau":
        "A new clip for the track, on the song's progression",
    "Longueur du clip neuf": "Length of the new clip",
    "Retire le clip de la piste ; les sections qui le jouaient se taisent "
    "pour elle  (rien n'est écrit sur la carte)":
        "Removes the clip from the track; the sections that played it fall "
        "silent for it  (nothing is written to the card)",
    "Nom de la section ; ses clips le portent sur le Deluge":
        "Name of the section; its clips carry it on the Deluge",
    "Durée de la section, en mesures : ses clips y bouclent":
        "Length of the section, in bars: its clips loop in it",
    "Joue le début de la section (huit mesures au plus), toutes pistes "
    "ensemble":
        "Plays the start of the section (eight bars at most), all tracks "
        "together",
    "Ajoute une section après celle choisie, avec les mêmes clips":
        "Adds a section after the chosen one, with the same clips",
    "Retire la section choisie du morceau":
        "Removes the chosen section from the song",
    "Avance la section d'un cran dans le morceau":
        "Moves the section one step later in the song",
    "Recule la section d'un cran dans le morceau":
        "Moves the section one step earlier in the song",
    "Remplace les sections par la structure du genre — intro, montée, thème, "
    "cassure… —, avec les variations qu'elle appelle ; un morceau d'origine "
    "garde ses propres sections":
        "Replaces the sections with the genre's structure — intro, build-up, "
        "theme, breakdown… —, with the variations it calls for; a song you "
        "started from keeps its own sections",
    "Ouvre l'éditeur du son courant : oscillateurs, filtres, enveloppes, LFO, "
    "effets et modulations, chaque réglage au cran de la machine et en clair. "
    "Le son retouché rejoint l'historique  (rien n'est écrit sur la carte)":
        "Opens the editor of the current sound: oscillators, filters, "
        "envelopes, LFOs, effects and modulation, each setting at the "
        "machine's step and in plain terms. The edited sound joins the "
        "history  (nothing is written to the card)",
    "Ouvre l'éditeur du son de la piste : chaque réglage au cran de la "
    "machine, et ce qu'il vaut sur le Deluge (1,8 s, 237 Hz…). « Garder ce "
    "son » le donne à la piste  (rien n'est écrit sur la carte)":
        "Opens the editor of the track's sound: each setting at the machine's "
        "step, and what it is worth on the Deluge (1.8 s, 237 Hz…). “Keep "
        "this sound” gives it to the track  (nothing is written to the card)",
    "Donne ce son au morceau de l'atelier, à la piste de sa catégorie "
    "— une basse à la basse, une nappe aux accords —, ou le garde pour "
    "le prochain morceau. Rien n'est écrit sur la carte":
        "Gives this sound to the studio's song, on the track of its "
        "category — a bass to the bass, a pad to the chords —, or keeps it "
        "for the next song. Nothing is written to the card",
    "Fait de ce kit la batterie du morceau de l'atelier, ou du "
    "prochain : il y joue les clips de batterie, et s'écrit avec le "
    "morceau. Rien n'est écrit sur la carte":
        "Makes this kit the drums of the studio's song, or of the next "
        "one: it plays the drum clips there, and is written with the song. "
        "Nothing is written to the card",
    "Ouvre le morceau choisi dans l'atelier : ses pistes, ses clips et "
    "ses sections deviennent ceux du projet, et l'atelier le complète "
    "sans le réécrire. Rien n'est modifié":
        "Opens the chosen song in the studio: its tracks, clips and "
        "sections become the project's, and the studio completes it "
        "without rewriting it. Nothing is changed",
    "Calcule le morceau entier sur l'ordinateur, sur son arrangement et "
    "avec les sons de chaque clip, puis le joue. Rien n'est écrit":
        "Computes the whole song on the computer, along its arrangement and "
        "with each clip's sounds, then plays it. Nothing is written",
    "Calcule le clip choisi comme la machine le joue, sur toute sa boucle, "
    "puis le joue. Un double-clic sur un clip fait de même":
        "Computes the chosen clip the way the machine plays it, over its "
        "whole loop, then plays it. Double-clicking a clip does the same",
    "Arrête l'écoute, et le calcul s'il tourne encore":
        "Stops the playback, and the computation if it is still running",
    "Le son rejoint le morceau de l'atelier, à la piste de son rôle — "
    "la basse pour une basse, les accords pour une nappe —, ou le "
    "prochain morceau s'il n'y en a pas : vous l'entendez en "
    "situation, et ses variantes restent dans le style. Rien n'est "
    "écrit sur la carte":
        "The sound joins the studio's song, on the track of its role — the "
        "bass for a bass, the chords for a pad —, or the next song if "
        "there is none: you hear it in context, and its variants stay in "
        "the style. Nothing is written to the card",
    "Le kit devient la batterie du morceau de l'atelier, ou du "
    "prochain : vous l'entendez jouer les clips du morceau. Rien n'est "
    "écrit sur la carte":
        "The kit becomes the drums of the studio's song, or of the next "
        "one: you hear it play the song's clips. Nothing is written to the "
        "card",
    "Joue chaque rangée du kit construit, l'une après l'autre — rien "
    "n'est écrit":
        "Plays each row of the built kit, one after the other — nothing is "
        "written",
    "Fabrique un morceau neuf dans le style choisi : une piste par "
    "partie cochée, un premier clip chacune, et la structure du genre "
    "avec les variations qu'elle appelle. Un morceau en cours est "
    "remplacé, après une question  (rien n'est encore écrit sur la "
    "carte)":
        "Makes a new song in the chosen style: one track per ticked part, "
        "a first clip for each, and the genre's structure with the "
        "variations it calls for. A song in progress is replaced, after a "
        "question  (nothing is written to the card yet)",
    "Ouvre dans l'atelier un morceau de la carte : ses pistes, ses "
    "clips et ses sections deviennent ceux du projet. Rien n'est "
    "modifié":
        "Opens a song from the card in the studio: its tracks, clips and "
        "sections become the project's. Nothing is changed",
    "Mène à la première étape : choisir un style, puis composer":
        "Leads to the first step: choose a style, then compose",
    "Joue huit mesures du passage le plus plein du morceau, toutes "
    "pistes ensemble — rien n'est écrit":
        "Plays eight bars of the song's fullest passage, all tracks "
        "together — nothing is written",
    "Revient à l'étape d'avant ; rien de ce que vous avez fait ne se perd":
        "Goes back to the previous step; nothing you have done is lost",
    "Passe à l'étape suivante du morceau ; toutes restent ouvertes, "
    "dans l'ordre que vous voulez":
        "Moves on to the song's next step; all of them stay open, in the "
        "order you like",
    "Joue les accords du morceau, tenus, sur un son de nappe du style":
        "Plays the song's chords, held, on a pad sound of the style",
    "Tire une autre suite d'accords dans la même ambiance ; elle "
    "servira à la prochaine composition":
        "Draws another chord sequence in the same mood; it will be used "
        "for the next composition",
    "Remplace l'accord choisi dans la liste par un autre de même "
    "fonction (tonique, sous-dominante, dominante) — le reste de la "
    "suite ne bouge pas":
        "Replaces the chord chosen in the list with another of the same "
        "function (tonic, subdominant, dominant) — the rest of the "
        "sequence stays",
    "Remplace le son de la rangée choisie par un autre du même rôle — "
    "de la même machine d'abord, puis d'une voisine — sans toucher au "
    "reste du kit  (rien n'est écrit sur la carte)":
        "Replaces the sound of the chosen row with another of the same "
        "role — from the same machine first, then a neighbouring one — "
        "without touching the rest of the kit  (nothing is written to the "
        "card)",
    "Écrit le clip choisi dans un fichier .mid, à l'endroit que vous "
    "choisirez — hors de la carte ; une batterie part sur le canal 10":
        "Writes the chosen clip to a .mid file, wherever you choose — off "
        "the card; drums go on channel 10",
    "Pose le groove sur le clip de batterie choisi, toujours depuis le "
    "motif droit : un second clic remplace le premier groove au lieu "
    "de s'y ajouter":
        "Applies the groove to the chosen drum clip, always from the "
        "straight pattern: a second click replaces the first groove "
        "instead of adding to it",
    "Nombre de coups à répartir dans la rangée":
        "Number of hits to spread across the row",
    "Longueur du motif euclidien, en pas : 16 pas = une mesure en "
    "double-croches ; il se répète sur tout le clip":
        "Length of the Euclidean pattern, in steps: 16 steps = one bar of "
        "sixteenths; it repeats over the whole clip",
    "Ajoute au clip de batterie une rangée dont les coups sont "
    "répartis au mieux — sur la carte, elle reçoit une percussion de "
    "votre bibliothèque":
        "Adds to the drum clip a row whose hits are spread as evenly as "
        "possible — on the card, it gets a percussion sound from your "
        "library",
    "Façon de poser les accords ou la basse dans la mesure — tenus, en "
    "blanches, sur les contretemps, en stabs ; fondamentale, croches, "
    "roulante… Choisir une façon fait un clip neuf, joué ainsi":
        "How the chords or the bass sit in the bar — held, in half notes, "
        "on the offbeats, as stabs; root, eighths, rolling… Choosing one "
        "makes a new clip, played that way",
    "Nom du morceau dans SONGS : il est assaini pour la carte, et "
    "numéroté s'il est déjà pris":
        "Name of the song in SONGS: it is cleaned up for the card, and "
        "numbered if already taken",
    "Ouvre la page Morceaux sur le morceau qui vient d'être écrit":
        "Opens the Songs page on the song just written",
    "Ouvre une fenêtre à garder à côté : l'écran du Deluge recopié, "
    "son tempo, le son sélectionné — rien n'est écrit sur la machine":
        "Opens a window to keep alongside: the Deluge's screen mirrored, "
        "its tempo, the selected sound — nothing is written to the machine",
    "Échange tout de suite avec le Deluge branché : ce qu'il a "
    "enregistré descend, le morceau écrit ici monte  (Ctrl+Maj+D)":
        "Exchanges with the plugged-in Deluge right away: what it saved "
        "comes down, the song written here goes up  (Ctrl+Shift+D)",
    "Écrit le morceau entier dans un fichier .mid, à l'endroit que "
    "vous choisirez — hors de la carte : une piste par piste, la "
    "batterie en piste 10, le nom des sections en repères":
        "Writes the whole song to a .mid file, wherever you choose — off "
        "the card: one track per track, the drums on track 10, the section "
        "names as markers",
    "Chaque page ne montre que l'essentiel : de quoi créer sans se perdre":
        "Each page shows only the essentials: enough to create without "
        "getting lost",
    "Chaque page montre tous ses réglages et toutes ses commandes : "
    "graines, moteurs, exports, retouches de fichiers":
        "Each page shows all its settings and all its commands: seeds, "
        "engines, exports, file edits",
    "Ouvre l'atelier sur un morceau neuf — ou sur celui en cours, à "
    "l'étape où vous en étiez : style, sons, clips, structure, puis le "
    "Deluge":
        "Opens the studio on a new song — or on the current one, at the "
        "step where you were: style, sounds, clips, structure, then the "
        "Deluge",
    "Ouvre le générateur : un preset de synthé ou un kit, par genre ou "
    "au hasard, à écouter puis enregistrer sur la carte":
        "Opens the generator: a synth preset or a kit, by genre or at "
        "random, to listen to and then save on the card",
    "Choisit un morceau de la carte — les derniers reçus du Deluge en "
    "tête — et l'ouvre dans l'atelier pour le compléter. Rien n'est "
    "modifié":
        "Picks a song from the card — the latest received from the Deluge "
        "first — and opens it in the studio to complete it. Nothing is "
        "changed",
    "Ouvre la bibliothèque : échantillons, presets, kits et morceaux "
    "de la carte, à écouter et ranger":
        "Opens the library: the card's samples, presets, kits and songs, "
        "to listen to and organise",
    # La page DAW.
    "**Écrit sur la carte.** Crée dans SONGS un morceau neuf : une piste par "
    "piste retenue, un clip par section où elle joue. ":
        "**Writes to the card.** Creates a new song in SONGS: one track per "
        "track kept, one clip per section where it plays. ",
    "**Écrit sur la carte.** Une copie du morceau où chaque piste écoute son "
    "canal ; le plan est montré avant, l'original n'est pas touché":
        "**Writes to the card.** A copy of the song where each track listens "
        "to its channel; the plan is shown first, the original is not "
        "touched",
    "Calcule sur l'ordinateur une piste audio par synthé et par kit, avec "
    "l'écoute fidèle au Deluge, toutes calées au début du morceau — "
    "plusieurs minutes pour un long morceau":
        "Computes on the computer one audio track per synth and per kit, "
        "with the listening that is faithful to the Deluge, all aligned to "
        "the start of the song — several minutes for a long song",
    "Copie dans le dossier les pistes que le Deluge a exportées lui-même "
    "(Export Tracks), le rendu le plus fidèle ; grisé s'il n'y en a pas pour "
    "ce morceau":
        "Copies into the folder the tracks the Deluge exported itself "
        "(Export Tracks), the most faithful rendering; greyed out if there "
        "are none for this song",
    "Demande un dossier du PC, puis y écrit un dossier **neuf** pour le DAW, "
    "avec un lisez-moi ; le morceau et la carte ne changent pas":
        "Asks for a folder on the PC, then writes a **new** folder for the "
        "DAW in it, with a readme; the song and the card do not change",
    "Le DAW dont les réglages s'affichent pas à pas ci-dessous":
        "The DAW whose settings are shown step by step below",
    "Le style des sons générés pour les pistes devenues synthés et kits":
        "The style of the sounds generated for the tracks that become synths "
        "and kits",
    "Les sections du nouveau morceau suivent l'arrangement du projet (coupé "
    "à ses repères) ou ses scènes ; grisé si le projet n'a que l'un des "
    "deux":
        "The new song's sections follow the project's arrangement (cut at "
        "its markers) or its scenes; greyed out if the project has only one "
        "of the two",
    "Lit un fichier MIDI, un set Ableton Live, un DAWproject ou un projet "
    "Reaper, et propose ce que devient chaque piste — rien n'est encore "
    "écrit":
        "Reads a MIDI file, an Ableton Live set, a DAWproject or a Reaper "
        "project, and suggests what each track becomes — nothing is written "
        "yet",
    "Ouvre dans l'explorateur Windows le dernier dossier exporté pour le "
    "DAW, ou celui du projet ouvert — rien n'est modifié":
        "Opens in Windows Explorer the last folder exported for the DAW, or "
        "the open project's — nothing is changed",
    "Un fichier .mid : tempo, repères de section, une piste par piste du "
    "morceau, la batterie sur le canal 10. Tous les DAW l'ouvrent":
        "A .mid file: tempo, section markers, one track per track of the "
        "song, the drums on channel 10. Every DAW opens it",
    "Un set Ableton Live : une piste MIDI par piste du morceau, une scène par "
    "section, l'arrangement entier, les repères, le tempo, et les pistes "
    "audio. Bâti avec les fichiers du Live installé sur ce PC ; grisé s'il "
    "n'est pas trouvé":
        "An Ableton Live set: one MIDI track per track of the song, one scene "
        "per section, the whole arrangement, the markers, the tempo, and the "
        "audio tracks. Built from the files of the Live installed on this PC; "
        "greyed out if it is not found",
    "Un projet .dawproject : pistes, clips en boucles, arrangement, scènes, "
    "repères, et les pistes audio. Bitwig Studio l'ouvre, Studio One et "
    "Cubase l'importent":
        "A .dawproject project: tracks, looping clips, arrangement, scenes, "
        "markers, and the audio tracks. Bitwig Studio opens it, Studio One "
        "and Cubase import it",
    "Un projet Reaper .rpp : pistes, objets MIDI en boucles, repères, et les "
    "pistes audio":
        "A Reaper .rpp project: tracks, looping MIDI items, markers, and the "
        "audio tracks",
    "Une longue section de l'arrangement est coupée en tranches de cette "
    "taille, pour des clips à la mesure de la machine ; le déroulé ne "
    "change pas":
        "A long section of the arrangement is cut into slices of this size, "
        "for clips that suit the machine; the running order does not change",
    "Une piste qui écoute déjà un canal le garde ; décochée, chacune reçoit "
    "un canal libre":
        "A track that already listens to a channel keeps it; unticked, each "
        "one gets a free channel",
}
