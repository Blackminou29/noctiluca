# -*- coding: utf-8 -*-
"""Anglais de ``delugeapp/core/health.py`` : le diagnostic de la carte."""

TEXTS = {
    "Carte en très bon état.": "Card in very good shape.",
    "Carte en bon état, quelques points à surveiller.":
        "Card in good shape, a few things to keep an eye on.",
    "Carte à nettoyer.": "Card needs a clean-up.",
    "Carte à remettre en ordre sérieusement.":
        "Card needs a serious tidy-up.",
    "Santé de la carte : %d/100 — %s": "Card health: %d/100 — %s",
    "%d erreur(s), %d avertissement(s), %d remarque(s)":
        "%d error(s), %d warning(s), %d note(s)",
    "ERREUR": "ERROR",
    "ATTENTION": "WARNING",
    "REMARQUE": "NOTE",
    "À faire : %s": "To do: %s",
    "… et %d autre(s)": "… and %d more",
    "Aucune anomalie détectée.": "No problem found.",
    "Erreur": "Error",
    "Attention": "Warning",
    "Remarque": "Note",
    "Santé de la carte : %d/100": "Card health: %d/100",
    "Structure de la carte": "Card structure",
    "Firmware": "Firmware",
    "Espace libre": "Free space",
    "Références d'échantillons": "Sample references",
    "Échantillons inutilisés": "Unused samples",
    "Doublons": "Duplicates",
    "Fichiers illisibles": "Unreadable files",
    "XML réparés": "Repaired XML",
    "Noms de fichiers": "File names",
    "Longueur des chemins": "Path length",
    "Profondeur des dossiers": "Folder depth",
    "Fréquences d'échantillonnage": "Sample rates",
    "Gros échantillons": "Large samples",
    "Percussions en stéréo": "Stereo drums",
    "Échantillons écrêtés": "Clipped samples",
    "Offset continu": "DC offset",
    "Échantillons muets": "Silent samples",
    "Fichiers parasites": "Junk files",
    "Fichiers non audio": "Non-audio files",
    "Dossiers vides": "Empty folders",
    "Sauvegardes": "Backups",
    "Dossiers standards absents": "Standard folders missing",
    "Le Deluge attend ces dossiers à la racine de la carte ; sans eux, il ne "
    "trouvera ni les morceaux ni les presets.":
        "The Deluge expects these folders at the root of the card; without "
        "them, it will find neither the songs nor the presets.",
    "Créer les dossiers manquants à la racine.":
        "Create the missing folders at the root.",
    "Plusieurs fichiers de firmware à la racine":
        "Several firmware files at the root",
    "Le Deluge n'accepte qu'un seul fichier « deluge*.bin ». Avec plusieurs, "
    "la mise à jour est refusée.":
        "The Deluge accepts only one “deluge*.bin” file. With several, the "
        "update is refused.",
    "Ne garder que la version voulue.": "Keep only the version you want.",
    "Aucun fichier de firmware": "No firmware file",
    "Ce n'est pas un défaut : le firmware n'a besoin d'être présent que pour "
    "une mise à jour.":
        "This is not a fault: the firmware only needs to be there for an "
        "update.",
    "aucun fichier deluge*.bin à la racine": "no deluge*.bin file at the root",
    "Espace libre faible": "Low free space",
    "Il reste %.0f Mio sur %s Gio. Le Deluge a besoin de place pour "
    "enregistrer et rééchantillonner.":
        "%.0f MiB left out of %s GiB. The Deluge needs room to record and "
        "resample.",
    "%.0f Mio libres": "%.0f MiB free",
    "Archiver les échantillons inutilisés ou libérer de la place.":
        "Archive the unused samples or free up some space.",
    "Échantillons référencés mais absents": "Samples referenced but missing",
    "%d preset(s), kit(s) ou morceau(x) réclament %d échantillon(s) "
    "introuvable(s) sur la carte. Le Deluge restera muet sur ces sons.":
        "%d preset(s), kit(s) or song(s) ask for %d sample(s) that cannot be "
        "found on the card. The Deluge will stay silent on those sounds.",
    "Chercher un remplaçant pour chacun, ou recopier les fichiers manquants "
    "sur la carte.":
        "Find a replacement for each one, or copy the missing files back "
        "onto the card.",
    "Échantillons jamais utilisés": "Samples never used",
    "%d échantillon(s) (%.0f Mio) ne sont cités par aucun preset, kit ni "
    "morceau de cette carte. Ce n'est pas un défaut : votre bibliothèque peut "
    "contenir des sons en réserve.":
        "%d sample(s) (%.0f MiB) are used by no preset, kit or song on this "
        "card. This is not a fault: your library may hold sounds in reserve.",
    "Les archiver dans un dossier à part s'il faut libérer de la place.":
        "Archive them into a separate folder if space needs freeing.",
    "Échantillons en double": "Duplicate samples",
    "%d groupe(s) de fichiers rigoureusement identiques, %.0f Mio en trop. "
    "La comparaison a été faite octet par octet, ce ne sont pas de simples "
    "homonymes.":
        "%d group(s) of strictly identical files, %.0f MiB too many. The "
        "comparison was made byte by byte; these are not just files with the "
        "same name.",
    "Ne garder qu'un exemplaire ; les références seront redirigées.":
        "Keep a single copy; references will be redirected.",
    "Fichiers XML illisibles": "Unreadable XML files",
    "Ces fichiers n'ont pu être interprétés, même par le lecteur tolérant. "
    "Le Deluge les refusera aussi.":
        "These files could not be parsed, even by the tolerant reader. The "
        "Deluge will refuse them too.",
    "Restaurer ces fichiers depuis une sauvegarde, ou les supprimer.":
        "Restore these files from a backup, or delete them.",
    "Fichiers XML réparés à la lecture": "XML files repaired when read",
    "Ces fichiers comportent des anomalies de syntaxe (caractères illégaux, "
    "« & » non échappé, balises mal fermées) que le lecteur a contournées. "
    "Le Deluge, lui, peut les refuser.":
        "These files have syntax problems (illegal characters, unescaped "
        "“&”, badly closed tags) that the reader worked around. The Deluge "
        "may refuse them.",
    "Réenregistrer ces presets depuis l'application pour obtenir un XML "
    "propre.":
        "Save these presets again from the application to get clean XML.",
    "Noms de fichiers problématiques": "Problematic file names",
    "Caractères interdits par FAT32, nom terminé par un point ou une espace, "
    "accents : autant de noms que le Deluge peut afficher de travers ou "
    "refuser.":
        "Characters forbidden by FAT32, names ending with a dot or a space, "
        "accents: all names the Deluge may display wrongly or refuse.",
    "Renommer ces fichiers en ASCII sans caractère spécial.":
        "Rename these files in plain ASCII without special characters.",
    "Chemins trop longs": "Paths too long",
    "Ces chemins dépassent %d caractères. FAT32 s'arrête à 255, et le Deluge "
    "peut tronquer avant.":
        "These paths exceed %d characters. FAT32 stops at 255, and the Deluge "
        "may truncate earlier.",
    "Raccourcir les noms de dossiers intermédiaires.":
        "Shorten the names of the intermediate folders.",
    "Arborescence très profonde": "Very deep folder tree",
    "Plus de %d niveaux de dossiers : la navigation sur l'écran de la "
    "machine devient fastidieuse.":
        "More than %d folder levels: browsing on the machine's screen becomes "
        "tedious.",
    "Mettre à plat les dossiers les plus enfouis.":
        "Flatten the most deeply buried folders.",
    "Fréquences d'échantillonnage inhabituelles": "Unusual sample rates",
    "Le Deluge tourne à 44,1 kHz. Ces fichiers (%s) seront convertis à la "
    "lecture, ce qui consomme du calcul sans rien apporter.":
        "The Deluge runs at 44.1 kHz. These files (%s) will be converted on "
        "playback, which costs processing for no benefit.",
    "Convertir ces échantillons en 44,1 kHz.":
        "Convert these samples to 44.1 kHz.",
    "Échantillons très volumineux": "Very large samples",
    "Au-delà de %.0f Mio, le chargement depuis la carte se fait sentir au "
    "déclenchement.":
        "Beyond %.0f MiB, loading from the card can be felt when the sound "
        "is triggered.",
    "%s (%.0f Mio)": "%s (%.0f MiB)",
    "Raccourcir ou rééchantillonner ces fichiers.":
        "Shorten or resample these files.",
    "%d percussion(s) sont stéréo. Dans un kit, une percussion mono suffit "
    "presque toujours : passer en mono libérerait environ %.0f Mio et un peu "
    "de calcul.":
        "%d drum sample(s) are stereo. In a kit, a mono drum is almost always "
        "enough: going mono would free about %.0f MiB and a little "
        "processing.",
    "Convertir ces échantillons en mono.": "Convert these samples to mono.",
    "Ces fichiers saturent : une partie de la forme d'onde est coupée net. "
    "La distorsion est déjà dans le fichier, et elle ressortira amplifiée "
    "dans le mixage.":
        "These files clip: part of the waveform is cut off. The distortion is "
        "already in the file, and it will come out amplified in the mix.",
    "%s (%s %% d'échantillons à fond)": "%s (%s%% of samples at full scale)",
    "Réduire le niveau à la source, ou remplacer ces échantillons.":
        "Lower the level at the source, or replace these samples.",
    "Échantillons avec une composante continue": "Samples with a DC offset",
    "La forme d'onde n'est pas centrée sur zéro : cela gaspille de la "
    "dynamique, peut faire claquer le début du son et perturbe les mesures "
    "de niveau.":
        "The waveform is not centred on zero: it wastes dynamic range, can "
        "make the start of the sound click and upsets level measurements.",
    "%s (offset %+.3f)": "%s (offset %+.3f)",
    "Appliquer un filtre coupe-continu lors de la conversion.":
        "Apply a DC-blocking filter during conversion.",
    "Ces fichiers ne contiennent aucun signal audible : ils occupent de la "
    "place sans rien jouer.":
        "These files contain no audible signal: they take up space without "
        "playing anything.",
    "Vérifier puis supprimer ces fichiers.": "Check, then delete these files.",
    "%d fichiers créés par macOS ou Windows (« ._* », « .DS_Store », « "
    "Thumbs.db ») occupent %s Mio. Le Deluge peut les afficher comme des "
    "presets fantômes dans ses listes.":
        "%d files created by macOS or Windows (“._*”, “.DS_Store”, "
        "“Thumbs.db”) take up %s MiB. The Deluge may show them as ghost "
        "presets in its lists.",
    "Les supprimer : ils ne servent à rien sur la carte.":
        "Delete them: they serve no purpose on the card.",
    "Fichiers non audio dans SAMPLES": "Non-audio files in SAMPLES",
    "Ces fichiers ne sont ni des WAV ni des AIFF : fichiers d'accompagnement "
    "d'un logiciel de montage, notes, images… Le Deluge les ignore, mais ils "
    "encombrent la navigation.":
        "These files are neither WAV nor AIFF: side files from an editing "
        "program, notes, images… The Deluge ignores them, but they clutter "
        "browsing.",
    "Les déplacer hors du dossier SAMPLES.":
        "Move them out of the SAMPLES folder.",
    "Ces dossiers ne contiennent rien et allongent inutilement les listes de "
    "la machine.":
        "These folders contain nothing and needlessly lengthen the machine's "
        "lists.",
    "Les supprimer.": "Delete them.",
    "Aucune sauvegarde": "No backup",
    "Les morceaux et presets d'une carte représentent des mois de travail "
    "dans des fichiers de quelques kilooctets. Une sauvegarde sans les "
    "échantillons prend moins d'une seconde.":
        "A card's songs and presets represent months of work in files of a "
        "few kilobytes. A backup without the samples takes less than a "
        "second.",
    "Créer une sauvegarde depuis la page Sauvegardes.":
        "Create a backup from the Backups page.",
    "Sauvegarde ancienne": "Old backup",
    "La dernière sauvegarde date de %d jours.":
        "The last backup is %d days old.",
    "Créer une nouvelle sauvegarde.": "Create a new backup.",
    "Réparation automatique": "Automatic repair",
    "dossier standard du Deluge": "standard Deluge folder",
    "dossier vide": "empty folder",
    "Réaffectation des références cassées": "Relinking broken references",
    "référence cassée redirigée vers %s": "broken reference redirected to %s",
}
