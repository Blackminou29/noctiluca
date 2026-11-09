# -*- coding: utf-8 -*-
"""Anglais de ``delugeapp/ui/pages/samples.py``."""

TEXTS = {
    "Toutes durées": "All lengths",
    "Très court (< 0,5 s)": "Very short (< 0.5 s)",
    "Court (0,5 à 2 s)": "Short (0.5 to 2 s)",
    "Moyen (2 à 10 s)": "Medium (2 to 10 s)",
    "Long (plus de 10 s)": "Long (over 10 s)",
    "Traiter les échantillons": "Process samples",
    "%d échantillon(s) sélectionné(s)": "%d sample(s) selected",
    "Mélanger en mono": "Mix down to mono",
    "Divise la taille par deux. La longueur ne change pas.":
        "Halves the size. The length does not change.",
    "Retirer la composante continue": "Remove DC offset",
    "Normaliser la crête à": "Normalise peak to",
    "Couper le silence sous": "Trim silence below",
    "Fondus d'entrée et de sortie de": "Fade in and out of",
    "Rééchantillonner à": "Resample to",
    "Le rééchantillonnage et la coupe du silence changent la longueur des "
    "fichiers : les bornes des presets qui les citent sont recalées, et les "
    "fichiers utilisés par un morceau sont écartés. Les originaux sont "
    "conservés dans <b>%s/</b>.":
        "Resampling and trimming silence change the length of the files: the "
        "start and end points of the presets that use them are adjusted, and "
        "files used by a song are left out. The originals are kept in "
        "<b>%s/</b>.",
    "Simuler": "Preview",
    "Annuler": "Cancel",
    "Découper en kit — %s": "Slice into a kit — %s",
    "Début": "Start",
    "Durée": "Length",
    "Trames": "Frames",
    "Écrire le kit": "Write the kit",
    "Exporter en fichiers…": "Export as files…",
    "Écrire en morceau": "Write as a song",
    "Écrit sur la carte un morceau neuf dans SONGS : le kit des tranches et "
    "un clip qui rejoue la boucle tranche par tranche, à sa place. Aucun "
    "fichier existant n'est remplacé.":
        "Writes a new song to the card, in SONGS: the kit of slices and a "
        "clip that replays the loop slice by slice, in place. No existing "
        "file is replaced.",
    "Fermer": "Close",
    "Coupes": "Cuts",
    "Sur les attaques": "On the transients",
    "En divisions égales": "In equal divisions",
    "Placement :": "Placement:",
    "Tranches :": "Slices:",
    "Sensibilité de la détection d'attaques":
        "Sensitivity of the transient detection",
    "Sensibilité :": "Sensitivity:",
    "Aligner sur le tempo": "Snap to tempo",
    "Ramène les coupes détectées sur la grille : un break rejoué reste en "
    "place.":
        "Moves the detected cuts onto the grid: a replayed break stays in "
        "time.",
    "Écouter": "Listen",
    "Écouter la tranche sélectionnée": "Play the selected slice",
    "%s — %s s, %d Hz, %d canal(aux)": "%s — %s s, %d Hz, %d channel(s)",
    "Découpage impossible : %s": "Slicing failed: %s",
    "Découpage": "Slicing",
    "%s\n\nChaque rangée jouera une portion de %s : aucun fichier audio "
    "n'est dupliqué.\n\nContinuer ?":
        "%s\n\nEach row will play a portion of %s: no audio file is "
        "duplicated.\n\nContinue?",
    "Kit écrit": "Kit written",
    "Export": "Export",
    "Exporter les tranches": "Export the slices",
    "%d fichiers seraient écrits dans %s.\n\nCe n'est pas nécessaire pour "
    "jouer le découpage sur le Deluge : le kit suffit et n'occupe rien de "
    "plus.\n\nContinuer ?":
        "%d files would be written to %s.\n\nThis is not needed to play the "
        "slices on the Deluge: the kit is enough and takes no extra "
        "space.\n\nContinue?",
    "Export partiel": "Partial export",
    "%d fichiers écrits, %d en échec :%s%s": "%d files written, %d failed:%s%s",
    "Export terminé": "Export done",
    "%d fichiers écrits dans %s.": "%d files written to %s.",
    "Échantillons": "Samples",
    "Indiquez l'emplacement de votre carte dans les réglages. Vous "
    "retrouverez ici toute la bibliothèque : forme d'onde, écoute d'un clic, "
    "étiquettes et sons proches.":
        "Set your card's location in the settings. You will find the whole "
        "library here: waveform, one-click playback, tags and similar sounds.",
    "Parcourir, écouter et ranger la bibliothèque":
        "Browse, listen to and tidy up the library",
    "Arrêter": "Stop",
    "Dans l'explorateur": "Show in Explorer",
    "Ouvrir le dossier contenant le fichier":
        "Open the folder containing the file",
    "Traiter…": "Process…",
    "Table d'onde…": "Wavetable…",
    "Une table d'onde pour le moteur wavetable du Deluge, tirée du son "
    "choisi":
        "A wavetable for the Deluge's wavetable engine, drawn from the chosen "
        "sound",
    "Table d'onde": "Wavetable",
    "Nom de la table, dans %s :": "Name of the table, in %s:",
    "Table d'onde impossible : %s.": "Wavetable not possible: %s.",
    "Écrire %s : %d cycles de %d échantillons, prélevés du début à la fin de "
    "« %s ». Aucun fichier existant n'est remplacé.%sContinuer ?":
        "Write %s: %d cycles of %d samples, taken from start to end of “%s”. "
        "No existing file is replaced.%sContinue?",
    "Table d'onde écrite : %s. Sur le Deluge, choisissez-la pour un "
    "oscillateur de type WAVETABLE ; le générateur s'en sert aussi.":
        "Wavetable written: %s. On the Deluge, choose it for an oscillator of "
        "type WAVETABLE; the generator uses it too.",
    "Sur un pad du Deluge": "On a Deluge pad",
    "Retirer du pad du Deluge": "Take off the Deluge pad",
    "Sur le Deluge : banque %d, pad %d.": "On the Deluge: bank %d, pad %d.",
    "Les 256 pads de favoris du Deluge sont pris.":
        "All 256 favourite pads of the Deluge are taken.",
    "Favori impossible : %s.": "Favourite not possible: %s.",
    "« %s » quitte le pad %d de la banque %d des favoris d'échantillons du "
    "Deluge.":
        "“%s” leaves pad %d of bank %d of the Deluge's sample favourites.",
    "« %s » va sur le pad %d de la banque %d des favoris d'échantillons du "
    "Deluge.":
        "“%s” goes onto pad %d of bank %d of the Deluge's sample favourites.",
    "%s est réécrit ; l'ancienne version est gardée dans _BACKUP. Si le "
    "navigateur d'échantillons du Deluge est ouvert, quittez-le avant "
    "l'envoi : il réécrit cette banque au moindre pad changé.":
        "%s is rewritten; the old version is kept in _BACKUP. If the "
        "Deluge's sample browser is open, leave it before sending: it "
        "rewrites this bank at the slightest pad change.",
    "Favoris du Deluge": "Deluge favourites",
    "Continuer ?": "Continue?",
    "Favoris du Deluge mis à jour : %s.": "Deluge favourites updated: %s.",
    "Créer un instrument — %s": "Create an instrument — %s",
    "Chaque son du dossier devient une tranche du clavier, jusqu'à "
    "mi-chemin du suivant — comme le Deluge le ferait. La hauteur vient du "
    "nom du fichier quand il la donne (« A1 », « C#3 »), sinon de l'écoute. "
    "Une couche de vélocité devient un preset : le Deluge n'en joue qu'une "
    "par tranche.":
        "Each sound of the folder becomes a range of the keyboard, up to "
        "halfway to the next one — as the Deluge would do it. The pitch comes "
        "from the file name when it gives it (“A1”, “C#3”), otherwise from "
        "listening. A velocity layer becomes a preset: the Deluge plays only "
        "one per range.",
    "Le nom du preset ; une couche de vélocité y ajoute la sienne":
        "The preset's name; a velocity layer adds its own",
    "Nom :": "Name:",
    "Le sous-dossier de SYNTHS où l'écrire":
        "The SYNTHS subfolder to write it into",
    "Dossier dans SYNTHS :": "Folder in SYNTHS:",
    "Lue dans": "Read from",
    "Jusqu'à": "Up to",
    "Preset": "Preset",
    "Créer l'instrument": "Create the instrument",
    "Écrit le ou les presets dans SYNTHS, après votre accord ; aucun fichier "
    "n'est remplacé, les échantillons ne sont pas touchés":
        "Writes the preset(s) into SYNTHS, after your go-ahead; no file is "
        "replaced, the samples are not touched",
    "Joue l'instrument sur l'ordinateur : une gamme de do, sur toute son "
    "étendue":
        "Plays the instrument on the computer: a scale of Cs, over its whole "
        "span",
    "Créer un instrument": "Create an instrument",
    "Écrire sur la carte :%s%s%sAucun fichier existant n'est remplacé.":
        "Write to the card:%s%s%sNo existing file is replaced.",
    "Créer un instrument…": "Create an instrument…",
    "Un preset multi-échantillon avec les sons du dossier":
        "A multisample preset with the folder's sounds",
    "Choisissez un dossier dans l'arbre, ou un des sons du dossier dans la "
    "liste.":
        "Choose a folder in the tree, or one of the folder's sounds in the "
        "list.",
    "Lecture des hauteurs de %s…": "Reading the pitches of %s…",
    "Hauteurs des sons": "Pitches of the sounds",
    "Aucun son de %s dont la hauteur soit connue : ni dans son nom, ni à "
    "l'écoute.":
        "No sound of %s whose pitch is known: neither in its name nor by "
        "listening.",
    "Instrument écrit : %s. Il se charge sur le Deluge comme tout preset.":
        "Instrument written: %s. It loads on the Deluge like any preset.",
    "Annuler un traitement…": "Undo a treatment…",
    "Remettre les originaux gardés par un traitement précédent":
        "Put back the originals kept by an earlier treatment",
    "Annuler un traitement": "Undo a treatment",
    "Aucun traitement à annuler : les originaux d'un traitement sont gardés "
    "dans _BACKUP, à la racine de la carte, et il n'y en a pas.":
        "No treatment to undo: the originals of a treatment are kept in "
        "_BACKUP, at the root of the card, and there are none.",
    "%s — %d fichier(s)": "%s — %d file(s)",
    "Traitement dont remettre les originaux :":
        "Treatment whose originals to put back:",
    "%d fichier(s) vont être remis tels qu'avant ce traitement. Leur version "
    "actuelle est gardée dans _BACKUP.%sContinuer ?":
        "%d file(s) will be put back as they were before this treatment. "
        "Their current version is kept in _BACKUP.%sContinue?",
    "Remise des originaux…": "Putting the originals back…",
    "Annulation d'un traitement": "Undoing a treatment",
    "Annulation partielle": "Partial undo",
    "%d fichier(s) remis, %d en échec :%s%s":
        "%d file(s) put back, %d failed:%s%s",
    "%d fichier(s) remis tels qu'avant le traitement.":
        "%d file(s) put back as they were before the treatment.",
    "Mono, normalisation, rééchantillonnage, fondus… sur la sélection":
        "Mono, normalisation, resampling, fades… on the selection",
    "Découper…": "Slice…",
    "Découper une boucle en kit : un pad par tranche":
        "Slice a loop into a kit: one pad per slice",
    "Sons proches": "Similar sounds",
    "Trouver les échantillons qui ressemblent au son sélectionné":
        "Find the samples that sound like the selected one",
    "Envoyer au Deluge…": "Send to the Deluge…",
    "Rechercher un échantillon…": "Search for a sample…",
    "Toutes catégories": "All categories",
    "Inutilisés": "Unused",
    "Échantillons qu'aucun preset, kit ni morceau ne cite":
        "Samples that no preset, kit or song uses",
    "Favoris": "Favourites",
    "Toutes étiquettes": "All tags",
    "Nouvelle étiquette…": "New tag…",
    "Ajouter": "Add",
    "Choisissez d'abord un échantillon.": "Choose a sample first.",
    "Étiquette « %s » ajoutée.": "Tag “%s” added.",
    "Manquants": "Missing",
    "Fichiers réclamés par un preset mais absents de la carte":
        "Files a preset asks for but that are missing from the card",
    "Dossiers": "Folders",
    "Aperçu": "Preview",
    "Aucun échantillon sélectionné": "No sample selected",
    "Note": "Rating",
    "Note de 1 à 5 étoiles, gardée dans l'index de l'application et non sur "
    "la carte":
        "Rating from 1 to 5 stars, kept in the application's index and not "
        "on the card",
    "Favori": "Favourite",
    "Étiquettes": "Tags",
    "Proximité": "Closeness",
    "stéréo": "stereo",
    "Nom": "Name",
    "Dossier": "Folder",
    "Catégorie": "Category",
    "Tonalité": "Key",
    "Format": "Format",
    "Taille": "Size",
    "Usages": "Uses",
    "Aucune sélection": "Nothing selected",
    "Sélectionnez le son dont vous cherchez les semblables.":
        "Select the sound you want to find look-alikes for.",
    "Pas encore analysé": "Not analysed yet",
    "Ce son n'a pas de descripteurs acoustiques.\n\nLancez une analyse de la "
    "carte avec l'analyse acoustique activée (Réglages), puis recommencez.":
        "This sound has no acoustic descriptors.\n\nRun a card scan with "
        "acoustic analysis turned on (Settings), then try again.",
    "Aucun son proche trouvé.": "No similar sound found.",
    "Toute la liste": "Full list",
    "%d son(s) proches de %s — %s": "%d sound(s) similar to %s — %s",
    "%d son(s) proches de « %s », du plus proche au plus lointain":
        "%d sound(s) similar to “%s”, from closest to farthest",
    "%d échantillon(s) affiché(s) — fichiers réclamés par un preset mais "
    "absents":
        "%d sample(s) shown — files a preset asks for but that are missing",
    "%d échantillon(s) affiché(s)": "%d sample(s) shown",
    "Tous les sons  (%d)": "All sounds  (%d)",
    "Fichier": "File",
    "introuvable sur la carte": "not found on the card",
    "mono": "mono",
    "%d canaux": "%d channels",
    "%s Hz · %d bits · %s": "%s Hz · %d bits · %s",
    "Erreur": "Error",
    "Tempo": "Tempo",
    "Utilisé par %d fichier(s).": "Used by %d file(s).",
    "Utilisé par aucun fichier de la carte.": "Used by no file on the card.",
    "Fichier introuvable.": "File not found.",
    "Lecture impossible : %s": "Playback failed: %s",
    "Envoyer au Deluge": "Send to the Deluge",
    "Sons, presets, kits et morceaux du Deluge (*.wav *.WAV *.aif *.aiff "
    "*.xml *.XML);;Tous les fichiers (*)":
        "Deluge sounds, presets, kits and songs (*.wav *.WAV *.aif *.aiff "
        "*.xml *.XML);;All files (*)",
    "Note : %d/5": "Rating: %d/5",
    "Sélectionnez la boucle à découper dans la liste.":
        "Select the loop to slice in the list.",
    "Un seul échantillon": "One sample only",
    "Le découpage porte sur une boucle à la fois : %d sont sélectionnées.":
        "Slicing works on one loop at a time: %d are selected.",
    "Découpage écrit : %s": "Slices written: %s",
    "Sélectionnez les échantillons à traiter dans la liste.":
        "Select the samples to process in the list.",
    "aucun traitement coché": "no processing ticked",
    "Rien à faire : %s.": "Nothing to do: %s.",
    "Traitement des échantillons": "Processing samples",
    "Traitement annulé.": "Processing cancelled.",
    "Traitement de %d fichier(s)…": "Processing %d file(s)…",
    "Échec : %s": "Failed: %s",
    "Traitement": "Processing",
    "Traitement partiel": "Partial processing",
    "%d fichier(s) traités, %d en échec :%s%s":
        "%d file(s) processed, %d failed:%s%s",
    "%s Originaux dans %s.": "%s Originals in %s.",
    "%s : %s": "%s: %s",
}
