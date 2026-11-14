# -*- coding: utf-8 -*-
"""Anglais de ``delugeapp/ui/pages/atelier.py`` (l'Atelier, « Studio » en anglais)."""

TEXTS = {
    "Atelier": "Studio",
    "Défaire": "Undo",
    "Refaire": "Redo",
    "Rien à défaire.": "Nothing to undo.",
    "Rien à refaire.": "Nothing to redo.",
    "Défait : %s.": "Undone: %s.",
    "Refait : %s.": "Redone: %s.",
    "Défait le dernier geste : %s  (Ctrl+Z)":
        "Undoes the last action: %s  (Ctrl+Z)",
    "Refait le geste défait : %s  (Ctrl+Y)":
        "Redoes the undone action: %s  (Ctrl+Y)",
    "Aucun geste à défaire": "No action to undo",
    "Aucun geste à refaire": "No action to redo",
    "Reprendre ce son": "Take this sound back",
    "son sans nom": "unnamed sound",
    "son repris": "sound taken back",
    "La piste reprend le son « %s ».": "The track takes back the sound “%s”.",
    "Morceau repris de votre dernière séance : %s.":
        "Song picked up from your last session: %s.",
    "tempo": "tempo",
    "composition du morceau": "composing the song",
    "son venu d'une autre page": "sound from another page",
    "kit venu d'une autre page": "kit from another page",
    "piste ajoutée": "track added",
    "piste retirée": "track removed",
    "canal": "channel",
    "autre son": "other sound",
    "autre kit": "other kit",
    "autre son pour la rangée": "other sound for the row",
    "son choisi sur la carte": "sound chosen on the card",
    "son retouché": "sound edited",
    "variante adoptée": "variant adopted",
    "style de jeu": "playing style",
    "Un clic pose une croche, tirer vers la droite l'allonge ; un clic sur "
    "une note la retire, un clic droit change sa force.":
        "A click places an eighth note, dragging to the right lengthens it; "
        "a click on a note removes it, a right-click changes its strength.",
    "coup de batterie": "drum hit",
    "note": "note",
    "%s : note ajoutée au pas %d.": "%s: note added at step %d.",
    "%s : note retirée au pas %d.": "%s: note removed at step %d.",
    "groove": "groove",
    "rangée euclidienne": "Euclidean row",
    "variation du clip": "clip variation",
    "nouveau clip": "new clip",
    "clip supprimé": "clip deleted",
    "case de la structure": "structure cell",
    "nom de section": "section name",
    "durée de section": "section length",
    "section ajoutée": "section added",
    "section retirée": "section removed",
    "section déplacée": "section moved",
    "structure du genre": "genre structure",
    "morceau ouvert": "song opened",
    "L'atelier compose sans carte ; il lui faut la carte pour écrire le "
    "morceau, et ses échantillons pour bâtir un kit.":
        "The studio composes without a card; it needs the card to write the "
        "song, and its samples to build a kit.",
    "Écrire le morceau": "Write the song",
    "Compléter le morceau": "Complete the song",
    "Style": "Style",
    "Sons": "Sounds",
    "Clips": "Clips",
    "Genre": "Genre",
    "Tonique": "Root",
    "Gamme": "Scale",
    "Tempo": "Tempo",
    "Ambiance": "Mood",
    "Celle du genre": "The genre's",
    "Couleur": "Colour",
    "Celle de l'ambiance": "The mood's",
    "Graine": "Seed",
    "Caractère des sons": "Character of the sounds",
    "Les mêmes pour tous les synthés du morceau : c'est ce qui les fait "
    "sonner ensemble.":
        "The same for every synth in the song: that is what makes them sound "
        "together.",
    "Chaque partie sur la piste de votre choix : un synthé du Deluge, une "
    "piste MIDI vers un appareil extérieur, ou une piste CV vers un modulaire "
    "(une note à la fois).":
        "Each part on the track of your choice: a Deluge synth, a MIDI track "
        "to an external device, or a CV track to a modular (one note at a "
        "time).",
    "Le morceau a-t-il une partie « %s » ?": "Does the song have a “%s” part?",
    "Où joue la partie « %s » : le Deluge lui-même, ou un appareil qu'il "
    "pilote":
        "Where the “%s” part plays: the Deluge itself, or a device it drives",
    "canal ": "channel ",
    "Canal MIDI (1 à 16), ou sortie CV (1 ou 2), de la partie « %s »":
        "MIDI channel (1 to 16), or CV output (1 or 2), of the “%s” part",
    "Pistes": "Tracks",
    "Composez un morceau, ou partez d'un des vôtres.":
        "Compose a song, or start from one of yours.",
    "Retirer": "Remove",
    "Aucune piste choisie": "No track chosen",
    "Écouter le son": "Play the sound",
    "Autre son": "Another sound",
    "Choisir sur la carte…": "Choose on the card…",
    "Canal": "Channel",
    "Variantes dans le style": "Variations in the style",
    "Le même son, un aspect tiré à nouveau ou un curseur poussé : jamais hors "
    "du genre. Cliquez pour écouter, double-cliquez pour adopter.":
        "The same sound, one facet drawn again or a slider pushed: never "
        "outside the genre. Click to listen, double-click to adopt.",
    "Proposer 8 variantes": "Suggest 8 variations",
    "Adopter": "Adopt",
    "Aucune variante pour l'instant.": "No variations yet.",
    "Clips de la piste": "Clips of the track",
    "Aucun clip.": "No clips.",
    "Écouter le clip": "Play the clip",
    "Jouer sur le Deluge": "Play on the Deluge",
    "Varier": "Vary",
    "Nouveau clip": "New clip",
    "%d mesure": "%d bar",
    "%d mesures": "%d bars",
    "Supprimer le clip": "Delete the clip",
    "Sur le Deluge, le clip joue dans le clip que suit MIDI Follow (canal A) "
    "— celui que vous avez ouvert. Machine en lecture, il part au début de sa "
    "boucle suivante, calé sur sa mesure ; en enregistrement (REC), il s'y "
    "inscrit.":
        "On the Deluge, the clip plays in the clip MIDI Follow is following "
        "(channel A) — the one you have opened. Machine playing, it starts at "
        "the beginning of its next loop, locked to its bar; recording (REC), "
        "it is written into it.",
    "Sections": "Sections",
    "Un clic sur une case fait jouer à la piste le clip suivant, puis le "
    "silence ; un clic droit le choisit dans la liste, ou ouvre le clip. Un "
    "clic sur une section la choisit. Le pad devant chaque piste la fait "
    "taire à l'écoute ; un clic droit l'isole.":
        "A click on a cell makes the track play its next clip, then silence; "
        "a right-click picks it from the list, or opens the clip. A click "
        "on a section chooses it. The pad in front of each track mutes it "
        "when listening; a right-click solos it.",
    "La section choisie": "The chosen section",
    "Nom": "Name",
    "Mesures": "Bars",
    "Écouter la section": "Play the section",
    "Arrêter": "Stop",
    "Ajouter une section": "Add a section",
    "Retirer la section": "Remove the section",
    "Structure du genre": "Genre structure",
    "Cochez au moins une partie.": "Tick at least one part.",
    "batterie synthétisée": "synthesised drums",
    "du morceau": "from the song",
    "Pas encore de son.": "No sound yet.",
    "Preset de la carte : les variantes dans le style partent d'un son "
    "fabriqué ici.":
        "Preset from the card: the variations in the style start from a sound "
        "made here.",
    "Batterie synthétisée pour l'écoute. Un kit de la carte est bâti au "
    "moment d'écrire, ou choisissez-en un.":
        "Drums synthesised for listening. A kit from the card is built when "
        "writing, or choose one.",
    "Piste MIDI : le Deluge envoie ses notes sur le canal %d, à l'appareil "
    "que vous y branchez. L'écoute de l'ordinateur la joue avec un son du "
    "style.":
        "MIDI track: the Deluge sends its notes on channel %d, to the device "
        "you plug into it. Listening on the computer plays it with a sound in "
        "the style.",
    "Piste CV : une tension de hauteur et une porte sur la sortie CV %d, vers "
    "un synthé modulaire. Une note à la fois.":
        "CV track: a pitch voltage and a gate on CV output %d, to a modular "
        "synth. One note at a time.",
    "Un kit se bâtit avec les échantillons de la carte.":
        "A kit is built from the card's samples.",
    "Aucun preset de ce type dans l'index : analysez la carte.":
        "No preset of this type in the index: analyse the card.",
    "Choisir sur la carte": "Choose on the card",
    "Le son de la piste « %s » :": "The sound of the “%s” track:",
    "Son choisi : %s.": "Sound chosen: %s.",
    "Rendu du son": "Rendering the sound",
    "%d variantes du son, toutes dans le style. Cliquez pour écouter.":
        "%d variations of the sound, all in the style. Click to listen.",
    "La piste prend le son « %s » (%s).":
        "The track takes the sound “%s” (%s).",
    "%s de %s": "%s of %s",
    "%d mes.": "%d bar(s)",
    "%d note(s) sur %d mesure(s).": "%d note(s) over %d bar(s).",
    "Déjà dans le morceau d'origine : « Dupliquer » en fait une copie à "
    "dessiner.":
        "Already in the original song: “Duplicate” makes a copy you can "
        "draw.",
    "Joué dans : %s.": "Played in: %s.",
    "Dans aucune section pour l'instant.": "In no section for now.",
    "Un clip vide ne se varie pas.": "An empty clip cannot be varied.",
    "Clip %s : « %s » de %s. Écoutez-le, puis placez-le dans une section.":
        "Clip %s: “%s” of %s. Listen to it, then place it in a section.",
    "Rendu du clip": "Rendering the clip",
    "Le clip ne joue plus sur le Deluge.":
        "The clip no longer plays on the Deluge.",
    "Le Deluge n'est pas connecté : branchez-le en USB, puis connectez-le "
    "depuis les réglages.":
        "The Deluge is not connected: plug it in over USB, then connect it "
        "from the settings.",
    "Le clip ne part pas sur le Deluge : rien à jouer.":
        "The clip does not go to the Deluge: nothing to play.",
    "Le clip part au début de sa prochaine boucle, calé sur la mesure du "
    "Deluge (canal %d).":
        "The clip starts at the beginning of its next loop, locked to the "
        "Deluge's bar (channel %d).",
    "Le Deluge est à l'arrêt : le clip joue au tempo du morceau (canal %d). "
    "Lancez la lecture sur la machine pour le caler sur sa mesure.":
        "The Deluge is stopped: the clip plays at the song's tempo (channel "
        "%d). Start playback on the machine to lock it to its bar.",
    "Le clip s'est arrêté sur le Deluge.":
        "The clip has stopped on the Deluge.",
    "%d mesures, %s": "%d bars, %s",
    "%d section(s) — %s, à %g BPM.": "%d section(s) — %s, at %g BPM.",
    "Nom de la section (elle reprend les clips de la section choisie) :":
        "Name of the section (it takes the clips of the chosen section):",
    "Refrain": "Chorus",
    "Structure du genre : %d sections, les variations qu'elles appellent "
    "ajoutées aux pistes.":
        "Genre structure: %d sections, the variations they call for added to "
        "the tracks.",
    "Cette section ne joue aucun clip.": "This section plays no clip.",
    "Rendu de la section": "Rendering the section",
    "Écoute des %d premières mesures de « %s ».":
        "Playing the first %d bars of “%s”.",
    "Rendu impossible : %s": "Rendering failed: %s",
    "Aucune sortie audio disponible.": "No audio output available.",
    "Lecture impossible : %s": "Playback failed: %s",
    "Aucun morceau dans l'index : analysez la carte.":
        "No song in the index: analyse the card.",
    "reçu du Deluge": "received from the Deluge",
    "Ouvrir un morceau du Deluge": "Open a Deluge song",
    "Le morceau sur lequel vous travaillez (les derniers reçus du Deluge en "
    "tête) :":
        "The song you are working on (the latest received from the Deluge "
        "first):",
    "ATELIER %s": "STUDIO %s",
    "Modifier le son…": "Edit the sound…",
    "Retouché à la main : les variantes dans le style gardent vos retouches.":
        "Edited by hand: the variations in the style keep your edits.",
    "%d variantes du son retouché, toutes dans le style et avec vos "
    "retouches. Cliquez pour écouter.":
        "%d variations of the edited sound, all in the style and with your "
        "edits. Click to listen.",
    "Le son d'une piste du morceau d'origine lui appartient : il ne se "
    "modifie pas ici.":
        "The sound of a track of the original song belongs to it: it is not "
        "edited here.",
    "Modifier le son — %s": "Edit the sound — %s",
    "Son retouché : %s.": "Sound edited: %s.",
    "Le son n'a pas changé.": "The sound has not changed.",
    "Choisissez un genre, un tempo et une tonalité, puis composez : "
    "tout le morceau est prêt en une seconde, et rien n'est écrit sur "
    "la carte.":
        "Choose a genre, a tempo and a key, then compose: the whole song "
        "is ready in a second, and nothing is written to the card.",
    "Écoutez le son de chaque piste. « Autre son » en tire un autre "
    "dans le même style ; les variantes le nuancent.":
        "Listen to each track's sound. “Another sound” draws a new one in "
        "the same style; the variants refine it.",
    "Ce que joue chaque piste : écoutez ses clips, variez-les, allumez "
    "ou éteignez les coups de la batterie d'un clic.":
        "What each track plays: listen to its clips, vary them, switch "
        "drum hits on or off with a click.",
    "Structure": "Structure",
    "Les sections du morceau, dans l'ordre : un clic sur une case "
    "change le clip que la piste y joue.":
        "The song's sections, in order: a click on a cell changes the clip "
        "the track plays there.",
    "Deluge": "Deluge",
    "Écrivez le morceau sur la carte : il part sur le Deluge par le "
    "câble. Parti d'un morceau de la carte, complétez-le sans y "
    "toucher.":
        "Write the song to the card: it goes to the Deluge over the cable. "
        "Started from a song on the card? Complete it without touching it.",
    "Un morceau en cinq étapes, du style au Deluge":
        "A song in five steps, from style to Deluge",
    "Ouvrir un morceau du Deluge…": "Open a Deluge song…",
    "Écouter un extrait": "Play an excerpt",
    "Pas encore de morceau": "No song yet",
    "Composer un morceau": "Compose a song",
    "Choisissez un style à l'étape 1 et composez, ou ouvrez un morceau "
    "enregistré sur le Deluge.":
        "Choose a style at step 1 and compose, or open a song saved on the "
        "Deluge.",
    "Ajouter": "Add",
    "Tempo et tonalité": "Tempo and key",
    "Les parties": "The parts",
    "Ce que le morceau contiendra : une piste par partie cochée.":
        "What the song will contain: one track per ticked part.",
    "Les accords": "The chords",
    "Écouter les accords": "Play the chords",
    "Autres accords": "Other chords",
    "Autre accord": "Another chord",
    "Le son de la piste": "The track's sound",
    "Le kit": "The kit",
    "Une rangée ne vous plaît pas ? Choisissez-la, puis « Autre son pour la "
    "rangée », ou « Choisir l'échantillon… » pour l'écouter parmi tous ceux "
    "de son rôle : le reste du kit ne bouge pas.":
        "Don't like a row? Select it, then “Another sound for the row”, or "
        "“Choose the sample…” to hear it among all those of its role: the "
        "rest of the kit stays as it is.",
    "Autre son pour la rangée": "Another sound for the row",
    "Clip en MIDI…": "Clip to MIDI…",
    "Groove": "Groove",
    "Swing": "Swing",
    "Appliquer le groove": "Apply the groove",
    "Euclidien": "Euclidean",
    "coups": "hits",
    "pas": "steps",
    "rotation": "rotation",
    "Ajouter la rangée": "Add the row",
    "Un nouveau clip, joué ainsi": "A new clip, played that way",
    "Écrire le morceau sur la carte": "Write the song to the card",
    "Nom du morceau": "Song name",
    "ATELIER TECHNO": "STUDIO TECHNO",
    "Voir dans Morceaux": "Show in Songs",
    "Compléter le morceau d'origine": "Complete the original song",
    "Le Deluge": "The Deluge",
    "Deluge en direct…": "Deluge Live…",
    "Synchroniser": "Sync",
    "Exporter": "Export",
    "Le morceau entier hors de la carte : en MIDI pour un logiciel de MAO — "
    "une piste par piste, la batterie sur le canal 10, le nom des sections "
    "en repères —, ou en audio, tel que l'ordinateur l'entend : le mélange "
    "en WAV, et à la demande une piste par fichier.":
        "The whole song off the card: as MIDI for a DAW — one track per "
        "track, the drums on channel 10, the section names as markers —, or "
        "as audio, the way the computer hears it: the mix as a WAV, and on "
        "request one track per file.",
    "Morceau en MIDI…": "Song to MIDI…",
    "Étape précédente": "Previous step",
    "Composer le morceau": "Compose the song",
    "Étape suivante": "Next step",
    "Étape %d sur %d — %s": "Step %d of %d — %s",
    "Passer à l'étape %d : %s": "Go to step %d: %s",
    "Revenir à l'étape %d : %s": "Back to step %d: %s",
    "Vous êtes à la première étape": "You are at the first step",
    "Recomposer le morceau": "Recompose the song",
    "Ces réglages valent pour la prochaine composition : « Recomposer "
    "le morceau » remplace celui en cours.":
        "These settings apply to the next composition: “Recompose the "
        "song” replaces the current one.",
    "%s %s :  %s": "%s %s:  %s",
    "Recomposer fait un morceau neuf à la place de celui en cours. "
    "L'ancien — ses sons, ses clips et ses sections — est rangé dans les "
    "brouillons, où vous le retrouverez. Rien n'est écrit sur la carte. "
    "Continuer ?":
        "Recomposing makes a new song in place of the current one. The old "
        "one — its sounds, its clips and its sections — is put away in the "
        "drafts, where you will find it again. Nothing is written to the "
        "card. Continue?",
    "Morceau composé : %d piste(s), %d section(s), %s. Écoutez chaque "
    "son, puis les clips et la structure ; écrivez-le sur la carte à "
    "la dernière étape.":
        "Song composed: %d track(s), %d section(s), %s. Listen to each "
        "sound, then the clips and the structure; write it to the card at "
        "the last step.",
    "Accords proposés : %s.": "Chords suggested: %s.",
    "Choisissez d'abord un accord dans la liste.":
        "Choose a chord in the list first.",
    "%s remplacé par %s : %s.": "%s replaced by %s: %s.",
    "Rendu des accords": "Rendering the chords",
    "« %s » jouera la partie %s du prochain morceau : choisissez un "
    "style, puis composez.":
        "“%s” will play the %s part of the next song: choose a style, then "
        "compose.",
    "« %s » joue désormais la piste « %s ». Écoutez-la dans le morceau.":
        "“%s” now plays the “%s” track. Listen to it in the song.",
    "Le kit « %s » sera la batterie du prochain morceau : choisissez "
    "un style, puis composez.":
        "The “%s” kit will be the drums of the next song: choose a style, "
        "then compose.",
    "Le kit « %s » est désormais la batterie du morceau.":
        "The “%s” kit is now the song's drums.",
    "Batterie": "Drums",
    "Retenus pour le morceau : %s.": "Kept for the song: %s.",
    "Composez un morceau à l'étape Style, ou partez d'un des vôtres.":
        "Compose a song at the Style step, or start from one of yours.",
    "%s — %d rangée(s).": "%s — %d row(s).",
    "Aucun kit de la carte : la batterie s'écoute en sons synthétisés. "
    "« Autre son » en bâtit un dans votre bibliothèque.":
        "No kit from the card: the drums play with synthesised sounds. "
        "“Another sound” builds one from your library.",
    "Piste ajoutée : %s, avec un premier clip. Placez-le dans les "
    "sections (étape Structure).":
        "Track added: %s, with a first clip. Place it in the sections "
        "(Structure step).",
    "Choisissez d'abord une rangée du kit.": "Choose a row of the kit first.",
    "La bibliothèque n'a pas d'autre son pour cette rangée.":
        "The library has no other sound for this row.",
    "%s : %s (%s).": "%s: %s (%s).",
    "selon le genre": "according to the genre",
    "Clip %s, joué « %s » : écoutez-le, puis placez-le dans une section.":
        "Clip %s, played “%s”: listen to it, then place it in a section.",
    "Un clic allume ou éteint un coup ; un clic droit change sa force.":
        "A click switches a hit on or off; a right-click changes its "
        "strength.",
    "Ce clip est déjà sur le Deluge : dupliquez-le, la copie se dessine.":
        "This clip is already on the Deluge: duplicate it, the copy can be "
        "drawn.",
    "%s : coup ajouté au pas %d.": "%s: hit added at step %d.",
    "%s : coup retiré au pas %d.": "%s: hit removed at step %d.",
    "Groove appliqué au clip %s. Sur le Deluge : swing %s.":
        "Groove applied to clip %s. On the Deluge: swing %s.",
    "Groove appliqué au clip %s.": "Groove applied to clip %s.",
    "Rangée %s ajoutée au clip %s : sur la carte, elle reçoit une "
    "percussion de votre bibliothèque.":
        "Row %s added to clip %s: on the card, it gets a percussion sound "
        "from your library.",
    "Exporter le clip": "Export the clip",
    "Fichier MIDI (*.mid)": "MIDI file (*.mid)",
    "Clip exporté : %s": "Clip exported: %s",
    "Projet tiré de « %s » : ses sections gardent leurs clips. « "
    "Compléter le morceau », à l'étape Deluge, écrit une nouvelle "
    "version qui le contient tel quel, plus vos pistes, vos clips et "
    "vos sections neuves.":
        "Project taken from “%s”: its sections keep their clips. “Complete "
        "the song”, at the Deluge step, writes a new version that contains "
        "it as is, plus your new tracks, clips and sections.",
    "Un morceau neuf, en %s, %s. À l'étape Deluge, « Écrire le morceau "
    "» en fait un morceau du Deluge, sections et arrangement compris.":
        "A new song, in %s, %s. At the Deluge step, “Write the song” turns "
        "it into a Deluge song, sections and arrangement included.",
    "Aucune section ne joue de clip.": "No section plays a clip.",
    "Rendu de l'extrait": "Rendering the excerpt",
    "Écoute de « %s », le passage le plus plein : %d mesures.":
        "Playing “%s”, the fullest passage: %d bars.",
    "« %s » est dans l'atelier : %d piste(s), %d clip(s), %d "
    "section(s). Variez ses clips, ajoutez des pistes et des sections, "
    "puis complétez-le à l'étape Deluge.":
        "“%s” is in the studio: %d track(s), %d clip(s), %d section(s). "
        "Vary its clips, add tracks and sections, then complete it at the "
        "Deluge step.",
    "Indiquez d'abord la carte, dans les réglages : le morceau s'écrit "
    "dans son dossier SONGS.":
        "Set the card first, in the settings: the song is written to its "
        "SONGS folder.",
    "Vous regardez la sauvegarde de la carte : elle ne s'écrit pas. "
    "Réglages ▸ Carte du Deluge pour travailler sur la carte.":
        "You are looking at the card's backup: it is not written to. "
        "Settings ▸ Deluge card to work on the card.",
    "Un morceau neuf dans SONGS, sections et arrangement compris ; "
    "aucun fichier n'est remplacé. Il part sur le Deluge par le câble "
    "quelques secondes après, ou à sa prochaine connexion.":
        "A new song in SONGS, sections and arrangement included; no file "
        "is replaced. It goes to the Deluge over the cable a few seconds "
        "later, or at its next connection.",
    "Un morceau neuf dans SONGS, sections et arrangement compris ; "
    "aucun fichier n'est remplacé. Remettez ensuite la carte dans le "
    "Deluge.":
        "A new song in SONGS, sections and arrangement included; no file "
        "is replaced. Then put the card back in the Deluge.",
    "Une nouvelle version de « %s », qui le contient octet pour octet, "
    "plus vos pistes, vos clips et vos sections neuves ; l'original "
    "n'est pas touché.":
        "A new version of “%s”, which contains it byte for byte, plus your "
        "new tracks, clips and sections; the original is not touched.",
    "Deluge débranché : branchez-le en USB pour jouer les clips sur la "
    "machine et y envoyer le morceau.":
        "Deluge unplugged: plug it in over USB to play the clips on the "
        "machine and send it the song.",
    "Écrit : %s. Sur le Deluge, chargez-le comme tout autre morceau "
    "(LOAD, puis SONG).":
        "Written: %s. On the Deluge, load it like any other song (LOAD, "
        "then SONG).",
    "Exporter le morceau": "Export the song",
    "Export impossible : %s.": "Export failed: %s.",
    "Morceau exporté : %s — %d piste(s), %d section(s), le nom des "
    "sections en repères.":
        "Song exported: %s — %d track(s), %d section(s), the section names "
        "as markers.",
    "Style de jeu": "Playing style",
    # -- 10 novembre 2026 : brouillons, écoute en boucle, clips à la main -- #
    "Brouillons…": "Drafts…",
    "Arrêter : coupe l'écoute en cours  (Espace)":
        "Stop: cuts the current playback  (Space)",
    "Muet": "Mute",
    "Solo": "Solo",
    "Volume": "Volume",
    "Écouter la rangée": "Play the row",
    "En boucle": "Loop",
    "Avec le morceau": "With the song",
    "Clip vide": "Empty clip",
    "Dupliquer": "Duplicate",
    "Doubler la longueur": "Double the length",
    "Hauteur": "Pitch",
    "Octave −": "Octave −",
    "Octave +": "Octave +",
    "Dupliquer la section": "Duplicate the section",
    "Solo levé : les pistes reviennent dans l'écoute.":
        "Solo lifted: the tracks are back in the listening.",
    "%s : de nouveau dans l'écoute.": "%s: back in the listening.",
    "%s : muette à l'écoute de l'ordinateur — le morceau écrit la garde.":
        "%s: muted when listening on the computer — the written song keeps "
        "it.",
    "%s : seule à l'écoute de l'ordinateur.":
        "%s: alone when listening on the computer.",
    "solo": "solo",
    "muette": "muted",
    "volume de la piste": "track volume",
    "Supprimer le brouillon": "Delete the draft",
    "Effacer ce brouillon de l'ordinateur ? Ses sons, ses clips et ses "
    "sections ne se retrouveront pas. Un morceau écrit sur la carte y reste, "
    "la carte n'est pas touchée.":
        "Erase this draft from the computer? Its sounds, its clips and its "
        "sections cannot be recovered. A song written to the card stays "
        "there, the card is not touched.",
    "Brouillon supprimé de l'ordinateur ; la carte n'est pas touchée.":
        "Draft deleted from the computer; the card is not touched.",
    "Ce brouillon est le morceau en cours.":
        "This draft is the current song.",
    "Ce brouillon ne se relit pas : %s.": "This draft cannot be read: %s.",
    "brouillon ouvert": "draft opened",
    "« %s » est de nouveau dans l'atelier, tel que vous l'aviez laissé.":
        "“%s” is back in the studio, as you left it.",
    "Rendu de la rangée": "Rendering the row",
    "%s : note de %d pas posée au pas %d.":
        "%s: note of %d steps placed at step %d.",
    "fort": "strong",
    "moyen": "medium",
    "doux": "soft",
    "force d'un coup": "strength of a hit",
    "Pas de coup à cette case : un clic gauche en pose un.":
        "No hit in this cell: a left click places one.",
    "%s, pas %d : coup %s.": "%s, step %d: %s hit.",
    "force d'une note": "strength of a note",
    "Pas de note à cette case : un clic gauche en pose une.":
        "No note in this cell: a left click places one.",
    "%s, pas %d : jeu %s.": "%s, step %d: played %s.",
    "clip vide": "empty clip",
    "Clip %s, vide : dessinez-le dans la grille, puis placez-le dans une "
    "section.":
        "Clip %s, empty: draw it in the grid, then place it in a section.",
    "clip dupliqué": "clip duplicated",
    "Clip %s : copie de %s. Retouchez-la, l'original ne bouge pas.":
        "Clip %s: copy of %s. Edit it, the original does not move.",
    "longueur doublée": "length doubled",
    "Clip non doublé : %s.": "Clip not doubled: %s.",
    "Clip %s : %d mesures, la seconde moitié répète la première — "
    "variez-la.":
        "Clip %s: %d bars, the second half repeats the first — vary it.",
    "octave du clip": "clip octave",
    "Clip non déplacé : %s.": "Clip not moved: %s.",
    "Clip %s : une octave plus haut.": "Clip %s: one octave higher.",
    "Clip %s : une octave plus bas.": "Clip %s: one octave lower.",
    "L'écoute tourne en boucle jusqu'à « Arrêter ».":
        "Listening loops until “Stop”.",
    "L'écoute joue une fois.": "Listening plays once.",
    "Le clip s'écoute avec les autres pistes du morceau.":
        "The clip plays with the song's other tracks.",
    "Le clip s'écoute seul.": "The clip plays alone.",
    "Clip %s avec le morceau : « %s », %d mesure(s).":
        "Clip %s with the song: “%s”, %d bar(s).",
    "Ce clip est vide : dessinez-y des notes.":
        "This clip is empty: draw some notes in it.",
    "Silence": "Silence",
    "Ouvrir le clip %s à l'étape Clips": "Open clip %s at the Clips step",
    "section dupliquée": "section duplicated",
    "Section non dupliquée : %s.": "Section not duplicated: %s.",
    "« %s » : la copie, %d mesures, les mêmes clips. Changez-y ce qui doit "
    "varier.":
        "“%s”: the copy, %d bars, the same clips. Change in it whatever "
        "should vary.",
    "Les pistes de cette section sont muettes : rendez-en une à l'écoute.":
        "The tracks of this section are muted: bring one back into the "
        "listening.",
    "Rien à écouter ici.": "Nothing to play here.",
    "En boucle : Espace l'arrête.": "Looping: Space stops it.",
    "Clip %s en boucle : Espace l'arrête.":
        "Clip %s looping: Space stops it.",
    "genre du morceau": "genre of the song",
    "Les sons et les clips neufs de ce morceau seront en %s.":
        "This song's new sounds and clips will be in %s.",
    "Elle prendra le tempo du genre, %d BPM, sauf si vous réglez le "
    "compteur.":
        "It will take the genre's tempo, %d BPM, unless you set the "
        "counter.",
    # Les conditions des notes (13 novembre 2026)
    "Clic gauche": "Left click",
    "Poser ou retirer des notes": "Place or remove notes",
    "%d avec une condition : la machine ne les joue pas à chaque tour.":
        "%d with a condition: the machine does not play them every loop.",
    "Clic gauche : poser ou retirer des notes.":
        "Left click: place or remove notes.",
    "Clic gauche : « %s » sur la note touchée ; un second clic la rend à "
    "« Toujours ».":
        "Left click: “%s” on the note you touch; a second click returns it "
        "to “Always”.",
    "Pas de note à cette case : « Poser ou retirer des notes » en pose une.":
        "No note in this cell: “Place or remove notes” places one.",
    "condition d'une note": "a note's condition",
    "%s, pas %d : %s.": "%s, step %d: %s.",
    "Choisir l'échantillon…": "Choose the sample…",
    "échantillon d'une rangée": "a row's sample",
    # Un clip depuis un fichier MIDI
    "Importer un clip MIDI…": "Import a MIDI clip…",
    "Choisissez d'abord une piste.": "Choose a track first.",
    "Importer un clip MIDI": "Import a MIDI clip",
    "Fichier MIDI (*.mid *.midi)": "MIDI file (*.mid *.midi)",
    "Fichier MIDI illisible : %s": "Unreadable MIDI file: %s",
    "Ce fichier MIDI n'a aucune note.": "This MIDI file has no note.",
    "%s — %d note(s)": "%s — %d note(s)",
    "La piste du fichier à reprendre dans « %s » :":
        "The file's track to take into “%s”:",
    "clip MIDI importé": "imported MIDI clip",
    "Rien à importer : %s.": "Nothing to import: %s.",
    "Clip %s : %d note(s) sur %d mesure(s), depuis %s.":
        "Clip %s: %d note(s) over %d bar(s), from %s.",
    "%d laissée(s) de côté : sans rôle de batterie, ou au-delà de seize "
    "mesures.":
        "%d left out: with no drum role, or beyond sixteen bars.",
    # Le morceau en audio
    "Morceau en audio…": "Song to audio…",
    "Le mélange seul": "The mix only",
    "Le mélange, et une piste par fichier": "The mix, and one track per file",
    "Un export audio est déjà en cours.":
        "An audio export is already running.",
    "Exporter le morceau en audio": "Export the song as audio",
    "Que faut-il écrire ?": "What should be written?",
    "Fichier WAV (*.wav)": "WAV file (*.wav)",
    "Rendu du morceau… (une quinzaine de secondes pour trois minutes)":
        "Rendering the song… (about fifteen seconds for three minutes)",
    "Rendu du morceau": "Rendering the song",
    "Export audio arrêté.": "Audio export stopped.",
    "Morceau exporté en audio : %s.": "Song exported as audio: %s.",
    "Morceau exporté en audio : %s, et %d piste(s) à côté.":
        "Song exported as audio: %s, and %d track(s) next to it.",
    "Export audio impossible : %s.": "Audio export impossible: %s.",
    # L'automation d'un clip
    "Automation": "Automation",
    "Poser la courbe": "Set the curve",
    "Retirer la courbe": "Remove the curve",
    "Montée du filtre": "Filter build-up",
    "Automation : %s.": "Automation: %s.",
    "automation d'un clip": "a clip's automation",
    "Pas d'automation : %s.": "No automation: %s.",
    "Clip %s : %s, %s.": "Clip %s: %s, %s.",
    "Ce clip n'a pas de courbe de ce réglage.":
        "This clip has no curve for this setting.",
    "automation retirée": "automation removed",
    "Clip %s : plus de courbe de %s.": "Clip %s: no more %s curve.",
    "Choisissez d'abord une section.": "Choose a section first.",
    "montée du filtre": "filter build-up",
    "Aucun synthé ne joue dans cette section.":
        "No synth plays in this section.",
    "« %s » : la coupure de %d synthé(s) s'ouvre sur toute la section — des "
    "copies des clips, les autres sections gardent les leurs.":
        "“%s”: the cutoff of %d synth(s) opens over the whole section — "
        "copies of the clips, the other sections keep theirs.",
    "Sur votre Deluge, SYNC-SCALING n'est pas encore le bouton FILL : "
    "SETTINGS ▸ COMMUNITY FEATURES ▸ Sync Scaling Action ▸ Fill mode.":
        "On your Deluge, SYNC-SCALING is not the FILL button yet: SETTINGS ▸ "
        "COMMUNITY FEATURES ▸ Sync Scaling Action ▸ Fill mode.",
}
