# -*- coding: utf-8 -*-
"""Anglais de ``delugeapp/ui/pages/toolbox.py``."""

TEXTS = {
    "libre (non synchronisé)": "free (not synced)",
    "4 mesures": "4 bars",
    "2 mesures": "2 bars",
    "1 mesure": "1 bar",
    "1/2 — blanche": "1/2 — half note",
    "1/4 — noire": "1/4 — quarter note",
    "1/8 — croche": "1/8 — eighth note",
    "1/16 — double-croche": "1/16 — sixteenth note",
    "1/32 — triple-croche": "1/32 — thirty-second note",
    "1/64 — quadruple-croche": "1/64 — sixty-fourth note",
    "Résolution rythmique": "Rhythmic resolution",
    "Une mesure 4/4 vaut 96 << inputTickMagnitude ticks : 384 dans un "
    "morceau c1.2.1 (magnitude 2), 192 dans un morceau 3.x. Un clip de 1536 "
    "ticks fait 4 mesures en c1.2.1.":
        "A 4/4 bar is 96 << inputTickMagnitude ticks: 384 in a c1.2.1 song "
        "(magnitude 2), 192 in a 3.x song. A 1536-tick clip is 4 bars in "
        "c1.2.1.",
    "Paramètres": "Parameters",
    "Entiers 32 bits : 0x80000000 = minimum, 0x00000000 = milieu, "
    "0x7FFFFFFF = maximum. L'écran affiche 0 à 50.":
        "32-bit integers: 0x80000000 = minimum, 0x00000000 = middle, "
        "0x7FFFFFFF = maximum. The screen shows 0 to 50.",
    "Câbles de modulation": "Patch cables",
    "Échelle pleine 0x40000000, soit la MOITIÉ des autres paramètres. "
    "L'écran affiche −50 à +50.":
        "Full scale 0x40000000, i.e. HALF that of the other parameters. The "
        "screen shows −50 to +50.",
    "Notes dans un clip": "Notes in a clip",
    "22 caractères hexadécimaux par note : pos(8) longueur(8) vélocité(2) "
    "lift(2) condition(2). Le lift précède la condition.":
        "22 hexadecimal characters per note: pos(8) length(8) velocity(2) "
        "lift(2) condition(2). Lift comes before condition.",
    "Condition d'une note": "Note condition",
    "0x14 (20) = toujours. En dessous de 20, probabilité par pas de 5 %. À "
    "partir de 0x80, règle d'itération.":
        "0x14 (20) = always. Below 20, probability in steps of 5%. From 0x80 "
        "on, an iteration rule.",
    "Gammes": "Scales",
    "Firmware communautaire (c1.x) : <modeNotes> accepte des gammes de "
    "cinq, six ou sept notes, et toute gamme utilisateur. Le firmware "
    "officiel en exigeait exactement sept.":
        "Community firmware (c1.x): <modeNotes> accepts scales of five, six "
        "or seven notes, and any user scale. The official firmware required "
        "exactly seven.",
    "syncLevel": "syncLevel",
    "Valeur du fichier : 3 = 1 mesure, 5 = noire, 6 = croche, 7 = "
    "double-croche, 8 = triple-croche. 0 = libre.":
        "Value in the file: 3 = 1 bar, 5 = quarter note, 6 = eighth note, "
        "7 = sixteenth note, 8 = thirty-second note. 0 = free.",
    "Arpégiateur (c1.x)": "Arpeggiator (c1.x)",
    "arpMode=\"arp\" l'allume ; noteMode (up, down, upDown, random, "
    "asPlayed) et octaveMode (up, down, upDown, alt, random) le règlent. "
    "L'ancien attribut mode n'est plus lu dans un fichier c1.2.":
        "arpMode=\"arp\" turns it on; noteMode (up, down, upDown, random, "
        "asPlayed) and octaveMode (up, down, upDown, alt, random) set it up. "
        "The old mode attribute is no longer read in a c1.2 file.",
    "Rangées de kit": "Kit rows",
    "loopMode 1 (ONCE) joue l'échantillon jusqu'au bout : c'est ce que "
    "choisit le Deluge sous 2 secondes. 0 (CUT) l'arrête avec la note.":
        "loopMode 1 (ONCE) plays the sample to the end: it is what the Deluge "
        "picks under 2 seconds. 0 (CUT) stops it with the note.",
    "Noms de fichiers": "File names",
    "FAT32 : pas de < > : \" / \\ | ? *, ni de point ou d'espace final. 63 "
    "caractères au maximum, ASCII de préférence.":
        "FAT32: no < > : \" / \\ | ? *, and no trailing dot or space. 63 "
        "characters at most, ASCII preferably.",
    "Firmware": "Firmware",
    "Un seul fichier deluge*.bin à la racine, sinon la mise à jour est "
    "refusée.":
        "Only one deluge*.bin file at the root, otherwise the update is "
        "refused.",
    "Dossiers attendus": "Expected folders",
    "SONGS, SYNTHS, KITS, SAMPLES à la racine. Les percussions dans "
    "SAMPLES/DRUMS/<catégorie>.":
        "SONGS, SYNTHS, KITS, SAMPLES at the root. Drums in "
        "SAMPLES/DRUMS/<category>.",
    "Fréquence d'échantillonnage": "Sample rate",
    "La machine tourne à 44,1 kHz. Les autres fréquences sont converties à "
    "la lecture.":
        "The machine runs at 44.1 kHz. Other rates are converted on "
        "playback.",
    "Outils": "Tools",
    "Boîte à outils": "Toolbox",
    "Théorie, rythme, calculs et aide-mémoire":
        "Theory, rhythm, calculations and cheat sheet",
    "Théorie": "Theory",
    "Rythme": "Rhythm",
    "Calculatrice": "Calculator",
    "Mixage harmonique": "Harmonic mixing",
    "Arrangement": "Arrangement",
    "Aide-mémoire": "Cheat sheet",
    "Gamme": "Scale",
    "Tonique": "Root",
    "Valeurs à recopier dans <modeNotes> d'un morceau du Deluge":
        "Values to copy into <modeNotes> of a Deluge song",
    "Copier": "Copy",
    "Accords de la gamme": "Chords of the scale",
    "Degré": "Degree",
    "Accord": "Chord",
    "Notes": "Notes",
    "Progression": "Progression",
    "Ambiance": "Mood",
    "Couleur": "Colour",
    "selon l'ambiance": "according to the mood",
    "Mesures": "Bars",
    "Proposer": "Suggest",
    "Genre": "Genre",
    "Accords": "Chords",
    "selon le genre": "according to the genre",
    "Basse": "Bass",
    "Ajouter": "Add",
    "Arpège": "Arpeggio",
    "Mélodie": "Melody",
    "Batterie": "Drums",
    "Écouter": "Listen",
    "Arrêter": "Stop",
    "En MIDI": "As MIDI",
    "En morceau": "As a song",
    "Autre mélodie": "Another melody",
    "Autre accord": "Another chord",
    "%s %s :  %s": "%s %s:  %s",
    "Sur le Deluge : gamme utilisateur (USER), à saisir note par note — ou "
    "en recopiant <modeNotes>.":
        "On the Deluge: user scale (USER), to enter note by note — or by "
        "copying <modeNotes>.",
    "Sur le Deluge : %s.": "On the Deluge: %s.",
    "Firmware officiel (sept notes exactement) : %s.":
        "Official firmware (exactly seven notes): %s.",
    "Valeurs de <modeNotes> copiées.": "<modeNotes> values copied.",
    "%d accords proposés : %s.": "%d chords suggested: %s.",
    "Proposez d'abord une progression.": "Suggest a progression first.",
    "Choisissez d'abord un accord dans la liste.":
        "Choose a chord in the list first.",
    "%s remplacé par %s, même fonction (%s) : %s.":
        "%s replaced by %s, same function (%s): %s.",
    "libre": "free",
    "Rendu de l'accompagnement…": "Rendering the accompaniment…",
    "Rendu impossible : %s": "Rendering failed: %s",
    "Rendu de l'accompagnement": "Rendering the accompaniment",
    "Aucune sortie audio disponible.": "No audio output available.",
    "Lecture de l'accompagnement…": "Playing the accompaniment…",
    "Lecture impossible : %s": "Playback failed: %s",
    "Exporter l'accompagnement": "Export the accompaniment",
    "progression.mid": "progression.mid",
    "Fichier MIDI (*.mid)": "MIDI file (*.mid)",
    "Export impossible : %s": "Export failed: %s",
    "Accompagnement exporté : %s (%d pistes — %s)":
        "Accompaniment exported: %s (%d tracks — %s)",
    "Progression %s %s": "Progression %s %s",
    "Créez d'abord un motif.": "Create a pattern first.",
    "aucun échantillon de batterie dans la bibliothèque — lancez une analyse "
    "de la carte":
        "no drum sample in the library — run a card scan",
    "Rythme %s": "Rhythm %s",
    "Esquisse %s": "Sketch %s",
    "Motif": "Pattern",
    "Motif du genre": "Genre pattern",
    "Euclidien": "Euclidean",
    "coups": "hits",
    "pas": "steps",
    "rotation": "rotation",
    "Ajouter la piste": "Add the track",
    "Groove": "Groove",
    "Swing": "Swing",
    "Appliquer": "Apply",
    "Variation": "Variation",
    "Représentation texte, à recopier dans un carnet":
        "Text version, to copy into a notebook",
    "Variation : %s. Grosse caisse, caisse claire et clap n'ont pas bougé.":
        "Variation: %s. Kick, snare and clap did not move.",
    "Rendu du rythme…": "Rendering the rhythm…",
    "Rendu du rythme… (batterie synthétisée)":
        "Rendering the rhythm… (synthesised drums)",
    "Rendu du rythme": "Rendering the rhythm",
    "Piste %s ajoutée.": "Track %s added.",
    "Groove appliqué. Sur le Deluge : swing %s.":
        "Groove applied. On the Deluge: swing %s.",
    "Groove appliqué.": "Groove applied.",
    "Exporter le motif": "Export the pattern",
    "motif.mid": "pattern.mid",
    "Motif exporté : %s": "Pattern exported: %s",
    "Tempo": "Tempo",
    "Division": "Division",
    "Droit (ms)": "Straight (ms)",
    "Pointé (ms)": "Dotted (ms)",
    "Triolet (ms)": "Triplet (ms)",
    "Hz (LFO)": "Hz (LFO)",
    "syncLevel du Deluge": "Deluge syncLevel",
    "Mémoire et durée": "Memory and length",
    "Durée (s)": "Length (s)",
    "Fréquence": "Rate",
    "Résolution": "Bit depth",
    "Canaux": "Channels",
    "mono": "mono",
    "stéréo": "stereo",
    "Une mesure 4/4 dure %.0f ms (%s s) — 96 ticks":
        "A 4/4 bar lasts %.0f ms (%s s) — 96 ticks",
    "%s pour %d s.": "%s for %d s.",
    "La place restante sur la carte permet environ %.0f minutes "
    "d'enregistrement dans ce format.":
        "The space left on the card allows about %.0f minutes of recording "
        "in this format.",
    "Roue de Camelot": "Camelot wheel",
    "Deux morceaux s'enchaînent sans fausse note si leurs codes sont "
    "identiques, voisins d'un cran, ou s'ils échangent majeur et mineur "
    "relatif.":
        "Two tracks blend without a wrong note if their codes are identical, "
        "one step apart, or if they swap major and relative minor.",
    "Majeur": "Major",
    "Mineur relatif": "Relative minor",
    "Compatibles": "Compatible",
    "Chercher dans la bibliothèque": "Search the library",
    "Tonalité": "Key",
    "ex. Am, C, F#m": "e.g. Am, C, F#m",
    "Chercher": "Search",
    "Tonalité « %s » non comprise.": "Key “%s” not understood.",
    "Compatibles avec %s : %s": "Compatible with %s: %s",
    "Aucun échantillon : lancez l'analyse acoustique dans les réglages pour "
    "détecter les tonalités.":
        "No sample: run the acoustic analysis from the settings to detect "
        "keys.",
    "%d échantillon(s) compatible(s).": "%d compatible sample(s).",
    "Modèle de structure": "Structure template",
    "Section": "Section",
    "Durée": "Length",
    "Position": "Position",
    "Parties": "Parts",
    "Écouter la section": "Play the section",
    "Esquisse en MIDI": "Sketch as MIDI",
    "Esquisse en morceau": "Sketch as a song",
    "une progression « %s » en la mineur": "a “%s” progression in A minor",
    "celui de l'onglet Rythme": "the one from the Rhythm tab",
    "le motif du genre": "the genre's pattern",
    "L'esquisse déroule %s sur toute la structure ; rythme : %s. Chaque "
    "section ne garde que les parties de son rôle.":
        "The sketch runs %s across the whole structure; rhythm: %s. Each "
        "section keeps only the parts of its role.",
    "Choisissez d'abord une section dans le tableau.":
        "Choose a section in the table first.",
    "Cette section ne joue rien.": "This section plays nothing.",
    "Rendu de « %s » (%d mesures)…": "Rendering “%s” (%d bars)…",
    "Rendu de la section": "Rendering the section",
    "Exporter l'esquisse": "Export the sketch",
    "esquisse.mid": "sketch.mid",
    "Esquisse exportée : %s — %d pistes (%s), %d sections, %d mesures, %d "
    "min %02d s.":
        "Sketch exported: %s — %d tracks (%s), %d sections, %d bars, %d min "
        "%02d s.",
    "mesure %d — %d:%02d": "bar %d — %d:%02d",
    "%d mesures au total, soit %d min %02d s à %.0f BPM. Les sections du "
    "Deluge se règlent dans la vue Morceau.":
        "%d bars in total, i.e. %d min %02d s at %.0f BPM. Deluge sections "
        "are set in the Song view.",
    "Valeurs et limites du Deluge": "Deluge values and limits",
    "Mesuré sur une carte réelle, ou documenté par le firmware.":
        "Measured on a real card, or documented by the firmware.",
}
