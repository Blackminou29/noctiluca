# -*- coding: utf-8 -*-
"""Anglais de ``delugeapp/ui/aide.py`` : ce que fait chaque commande."""

TEXTS = {
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
    "**Écrit sur la carte.** Crée dans SONGS un morceau neuf : ce kit, tel "
    "qu'il est sur la carte, et un clip qui joue le motif d'essai. ":
        "**Writes to the card.** Creates a new song in SONGS: this kit, as it "
        "is on the card, and a clip that plays the test pattern. ",

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
    "**Écrit sur la carte.** Crée dans SONGS un morceau neuf où le son joue "
    "une phrase faite pour son rôle (basse, accords, arpège, mélodie), sur "
    "une progression et la batterie du genre : de quoi l'essayer en situation "
    "sur la machine. ":
        "**Writes to the card.** Creates a new song in SONGS where the sound "
        "plays a phrase made for its role (bass, chords, arpeggio, melody), "
        "over a progression and the genre's drums: a way to try it in context "
        "on the machine. ",
    "**Écrit sur la carte.** Crée dans SONGS un morceau neuf : ce kit et un "
    "clip qui joue le rythme de son genre. ":
        "**Writes to the card.** Creates a new song in SONGS: this kit and a "
        "clip that plays its genre's rhythm. ",
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
    "Ambiance de la suite d'accords proposée":
        "Mood of the suggested chord sequence",
    "Nombre de mesures de la progression": "Number of bars in the progression",
    "Tire une suite d'accords dans la gamme choisie":
        "Draws a chord sequence in the chosen scale",
    "Écrit un fichier .mid à l'endroit que vous choisirez":
        "Writes a .mid file wherever you choose",
    "Écrit la progression et son accompagnement dans un fichier .mid : une "
    "piste par partie (accords, basse, arpège, mélodie), chacune sur son "
    "canal":
        "Writes the progression and its accompaniment to a .mid file: one "
        "track per part (chords, bass, arpeggio, melody), each on its own "
        "channel",
    "Écrit le motif affiché dans un fichier .mid, percussions sur le canal 10":
        "Writes the displayed pattern to a .mid file, drums on channel 10",
    "Joue la progression avec son accompagnement, sur des sons générés pour "
    "le genre choisi — rien n'est écrit":
        "Plays the progression with its accompaniment, on sounds generated "
        "for the chosen genre — nothing is written",
    "Choisit le rythme des accords, le style de basse, l'arpège et le tempo "
    "— ainsi que les sons de l'écoute":
        "Chooses the chord rhythm, the bass style, the arpeggio and the tempo "
        "— as well as the sounds used for playback",
    "Façon de poser les accords dans la mesure : tenus, en blanches, sur les "
    "contretemps, en stabs syncopés, ou en « charleston »":
        "How the chords sit in the bar: held, in half notes, on the "
        "off-beats, as syncopated stabs, or as a “charleston”",
    "Style de la ligne de basse tirée des accords : fondamentale, croches, "
    "contretemps, roulante, octaves, syncopée ou marche":
        "Style of the bass line drawn from the chords: root, eighth notes, "
        "off-beat, rolling, octaves, syncopated or walking",
    "Ajoute un arpège des accords, joué au-dessus d'eux":
        "Adds an arpeggio of the chords, played above them",
    "Ajoute une mélodie : un motif repris puis varié, les notes de l'accord "
    "sur les temps forts, une fin sur la fondamentale ; son allure suit le "
    "genre":
        "Adds a melody: a motif repeated then varied, chord notes on the "
        "strong beats, an ending on the root; its feel follows the genre",
    "Tire une autre mélodie sur les mêmes accords et la fait écouter — rien "
    "n'est écrit":
        "Draws another melody over the same chords and plays it — nothing is "
        "written",
    "Ce qu'on empile sur chaque degré : triades, septièmes, neuvièmes "
    "(jouées sans fondamentale, que tient la basse) ou accords suspendus ; "
    "« selon l'ambiance » met des septièmes au jazz et à la house, des "
    "neuvièmes à la deep et à l'ambient":
        "What is stacked on each degree: triads, sevenths, ninths (played "
        "without the root, which the bass holds) or suspended chords; "
        "“according to the mood” gives sevenths to jazz and house, ninths to "
        "deep house and ambient",
    "Tempo de l'écoute et du fichier MIDI ; il suit le genre choisi":
        "Tempo of the playback and of the MIDI file; it follows the chosen "
        "genre",
    "Ajoute la batterie : le rythme de l'onglet Rythme, ou à défaut celui du "
    "genre, joué par des sons de la carte — et en piste 10 dans le fichier "
    "MIDI":
        "Adds drums: the rhythm from the Rhythm tab, or else the genre's, "
        "played with sounds from the card — and on track 10 in the MIDI file",
    "Remplace l'accord choisi dans la liste par un autre de même fonction "
    "(tonique, sous-dominante, dominante) — le reste de la progression ne "
    "bouge pas":
        "Replaces the chord chosen in the list with another one of the same "
        "function (tonic, subdominant, dominant) — the rest of the "
        "progression stays as it is",
    "Varie le motif sans toucher à son ossature : grosse caisse, caisse "
    "claire et clap restent ; notes fantômes, charleys, percussion ou "
    "charleston ouvert changent":
        "Varies the pattern without touching its backbone: kick, snare and "
        "clap stay; ghost notes, hi-hats, percussion or open hi-hat change",
    "Joue le motif deux fois, avec les échantillons de la carte quand elle "
    "en a, sinon une batterie synthétisée — rien n'est écrit":
        "Plays the pattern twice, with the card's samples when it has some, "
        "otherwise with synthesised drums — nothing is written",
    "Tempo de l'écoute et du fichier MIDI du motif ; il suit le genre choisi":
        "Tempo of the pattern's playback and MIDI file; it follows the chosen "
        "genre",
    "Joue le début de la section choisie dans le tableau (huit mesures au "
    "plus), avec les seules parties de son rôle":
        "Plays the beginning of the section chosen in the table (eight bars "
        "at most), with only the parts of its role",
    "Écrit le morceau entier dans un fichier .mid : une piste par partie, la "
    "batterie en piste 10, le nom des sections en repères":
        "Writes the whole song to a .mid file: one track per part, drums on "
        "track 10, section names as markers",
    "**Écrit sur la carte.** Crée dans SONGS un morceau neuf : un instrument "
    "et un clip par partie (accords, basse, arpège, mélodie, batterie), avec "
    "les sons de l'écoute ; les clips bouclent ensemble dès qu'on appuie sur "
    "PLAY. ":
        "**Writes to the card.** Creates a new song in SONGS: one instrument "
        "and one clip per part (chords, bass, arpeggio, melody, drums), with "
        "the playback sounds; the clips loop together as soon as you press "
        "PLAY. ",
    "**Écrit sur la carte.** Crée dans SONGS un morceau neuf : un kit de la "
    "carte et un clip qui joue le motif affiché ; une piste sans son, comme "
    "une piste euclidienne, reçoit une percussion de la bibliothèque. ":
        "**Writes to the card.** Creates a new song in SONGS: a kit from the "
        "card and a clip that plays the displayed pattern; a track without a "
        "sound, such as a Euclidean track, gets a percussion sound from the "
        "library. ",
    "**Écrit sur la carte.** Crée dans SONGS un morceau à sections : chaque "
    "section du modèle devient une section du Deluge, avec ses clips et son "
    "nombre de répétitions. PLAY joue la première en boucle ; lancez la "
    "suivante et le reste s'enchaîne jusqu'à la fin. L'arrangement (touche "
    "SONG) joue tout le morceau d'un trait. ":
        "**Writes to the card.** Creates a song with sections: each section "
        "of the template becomes a Deluge section, with its clips and its "
        "number of repeats. PLAY loops the first one; launch the next one and "
        "the rest follows through to the end. The arrangement (SONG button) "
        "plays the whole song in one go. ",
    "Style du motif rythmique engendré": "Style of the generated rhythm pattern",
    "Longueur du motif, en mesures": "Length of the pattern, in bars",
    "Engendre un rythme typique du genre choisi":
        "Generates a rhythm typical of the chosen genre",
    "Nombre de coups à répartir dans le motif":
        "Number of hits to spread across the pattern",
    "Nombre de pas du motif : 16 pas = une mesure en double-croches":
        "Number of steps in the pattern: 16 steps = one bar of sixteenth notes",
    "Décale le motif d'un ou plusieurs pas, sans changer ses coups":
        "Shifts the pattern by one or more steps, without changing its hits",
    "Ajoute ce motif euclidien au rythme en cours, sur une nouvelle piste":
        "Adds this Euclidean pattern to the current rhythm, on a new track",
    "Swing d'échantillonneur en pourcentage (58 % léger, 66 % ternaire), ou "
    "jeu derrière / devant le temps. Le même pourcentage se règle dans le "
    "swing du Deluge":
        "Sampler-style swing as a percentage (58% light, 66% triplet), or "
        "playing behind / ahead of the beat. The same percentage can be set "
        "in the Deluge's swing",
    "Swing libre ajouté au groove, de droit à ternaire":
        "Free swing added to the groove, from straight to triplet",
    "Applique le groove au motif affiché, toujours depuis le motif droit : "
    "un second clic ne cumule pas":
        "Applies the groove to the displayed pattern, always from the "
        "straight pattern: a second click does not add up",
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
    "Style du modèle de structure proposé":
        "Style of the suggested structure template",
    "Tempo utilisé pour convertir les sections en minutes et en secondes":
        "Tempo used to convert the sections into minutes and seconds",

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
    "Fabrique un morceau neuf dans le style de l'onglet Style : une piste par "
    "partie cochée, un premier clip chacune, et la structure du genre avec "
    "les variations qu'elle appelle  (rien n'est encore écrit sur la carte)":
        "Makes a new song in the style of the Style tab: one track per ticked "
        "part, a first clip each, and the genre's structure with the "
        "variations it calls for  (nothing is written to the card yet)",
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
}
