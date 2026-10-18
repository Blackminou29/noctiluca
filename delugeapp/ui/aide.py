# -*- coding: utf-8 -*-
"""Ce que fait chaque commande, dit en une phrase.

Mesuré avant d'écrire ce module : **102 des 174 commandes de l'application
n'expliquaient rien** (59 %), dont « Supprimer les doublons », « Archiver
dans _UNUSED », « Relier automatiquement » et « Restaurer » — quatre actions
qui **écrivent sur la carte**. Un logiciel qui touche à des mois de travail
doit dire ce qu'il va faire avant de le faire, et pas seulement dans sa
documentation.

Pourquoi un registre central plutôt qu'une infobulle à chaque création
---------------------------------------------------------------------

Parce qu'on peut alors **vérifier la couverture** : un test parcourt les
neuf pages et échoue s'il reste une commande muette, ou si une explication
désigne une commande qui n'existe plus. Cent infobulles éparpillées ne se
vérifient pas.

Comment les clés sont formées
-----------------------------

* ``"@_attribut"`` — le widget est un attribut de la page
  (``self._category``). C'est le plus stable : le nom ne change pas quand on
  réécrit un libellé.
* ``"Libellé exact"`` — pour les boutons créés sur place, sans attribut.
* :data:`COMMUNES` sert aux libellés qu'on retrouve sur plusieurs pages.

Une explication **ne répète pas le libellé** : « Écouter » n'apprend rien à
qui lit « Écouter ». Elle dit ce qui va se passer, et où cela va s'écrire.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

__all__ = ["COMMUNES", "EXPLICATIONS", "expliquer", "manquantes"]


#: Ce que disent toutes les commandes qui écrivent un morceau.
_PLAN = ("Le nom est demandé et le plan montré avant d'écrire ; aucun "
         "fichier existant n'est remplacé")

#: Libellés présents sur plusieurs pages.
COMMUNES: dict[str, str] = {
    "Arrêter": "Coupe l'écoute en cours  (Espace)",
    "Indiquer le dossier": "Aller choisir l'emplacement de la carte dans "
                           "les réglages",
    "Détecter la carte": "Cherche une carte Deluge sur les lecteurs "
                         "branchés : est reconnu tout dossier contenant au "
                         "moins deux des dossiers SONGS, SYNTHS, KITS et "
                         "SAMPLES",
    "Dans l'explorateur": "Ouvre le dossier du fichier dans l'explorateur "
                          "Windows — rien n'est modifié",
}


#: Par page, puis par commande.
EXPLICATIONS: dict[str, dict[str, str]] = {

    # ---------------------------------------------------------------- #
    "Samples": {
        "@_play_button": "Joue l'échantillon sélectionné sur l'ordinateur  "
                         "(ou sur le Deluge si vous l'avez demandé dans les "
                         "réglages)",
        "@_search": "Filtre la liste sur le nom du fichier ; la recherche "
                    "part toute seule après une courte pause",
        "@_category": "Ne montre que les échantillons d'une catégorie — "
                      "celle-ci vient du dossier où ils sont rangés",
        "@_duration": "Ne montre que les sons d'une certaine longueur : "
                      "utile pour isoler les frappes courtes des nappes",
        "@_only_fav": "Ne montre que les échantillons marqués d'une étoile "
                      "pleine dans l'aperçu",
        "@_fav": "Marque ce son comme favori ; le filtre « Favoris » "
                 "au-dessus s'en sert",
        "@_only_unused": "Ne montre que les sons qu'aucun preset, kit ni "
                         "morceau n'utilise — candidats au rangement",
        "@_only_missing": "Ne montre que les fichiers réclamés par un preset "
                          "mais absents de la carte",
    },

    # ---------------------------------------------------------------- #
    "Synths": {
        "Écouter": "Rend le preset et le joue — approximation calculée par "
                   "l'ordinateur, ou vrai son de la machine si le Deluge est "
                   "branché et l'écoute réglée sur lui",
        "@_search": "Filtre les presets sur leur nom",
        "@_category": "Ne montre que les presets d'une catégorie, déduite de "
                      "leur dossier et de leur contenu",
        "Dupliquer": "Copie le preset sous un nouveau nom, dans le même "
                     "dossier de la carte — l'original n'est pas touché",
        "Varier dans le générateur": "Ouvre ce preset dans le générateur "
                                     "pour le muter ou en tirer des "
                                     "variantes — l'original n'est jamais "
                                     "réécrit",
    },

    # ---------------------------------------------------------------- #
    "Kits": {
        "Écouter la rangée": "Joue l'échantillon de la rangée choisie dans "
                             "le tableau",
        "Écouter le kit": "Joue le motif d'essai avec les sons du kit : sur "
                          "le Deluge s'il est branché, sinon en rendu "
                          "approché",
        "@_search": "Filtre les kits sur leur nom",
        "@_genre": "Charge un motif rythmique typique du genre, limité aux "
                   "rangées que ce kit possède",
        "Motif en MIDI": "Écrit le motif d'essai dans un fichier .mid, à "
                         "l'endroit que vous choisirez — hors de la carte",
        "Motif en morceau": "**Écrit sur la carte.** Crée dans SONGS un "
                            "morceau neuf : ce kit, tel qu'il est sur la "
                            "carte, et un clip qui joue le motif d'essai. "
                            + _PLAN,
    },

    # ---------------------------------------------------------------- #
    "Songs": {
        "@_search": "Filtre les morceaux sur leur nom",
        "Clip en MIDI": "Écrit le clip choisi dans un fichier .mid, à "
                        "l'endroit que vous choisirez",
        "Morceau en MIDI": "Écrit toutes les pistes du morceau dans un seul "
                           "fichier .mid, une piste par clip",
        "Rassembler…": "Copie le morceau **et tout ce dont il dépend** "
                       "(presets, kits, échantillons) dans un dossier à "
                       "part : de quoi l'emporter ailleurs sans rien perdre",
        "Rapport HTML": "Écrit une page web décrivant le morceau : tempo, "
                        "clips, instruments, échantillons utilisés",
    },

    # ---------------------------------------------------------------- #
    "Generator": {
        "Générer": "Fabrique un preset complet à partir du genre, du rôle et "
                   "de la graine ci-dessous  (rien n'est encore écrit sur la "
                   "carte)",
        "Au hasard": "Tire un genre, un rôle et une graine au hasard, puis "
                     "génère",
        "Muter": "Repart du son actuel et en change quelques réglages : de "
                 "quoi explorer autour d'une idée qui plaît",
        "Écouter": "Joue le son généré — sur le Deluge s'il est branché et "
                   "l'écoute réglée sur lui, sinon en rendu approché",
        "Enregistrer dans SYNTHS": "Écrit le preset sur la carte, dans "
                                   "SYNTHS/ — avec confirmation, et sans "
                                   "jamais écraser un fichier existant",
        "Essayer en morceau": "**Écrit sur la carte.** Crée dans SONGS un "
                              "morceau neuf où le son joue une phrase faite "
                              "pour son rôle (basse, accords, arpège, "
                              "mélodie), sur une progression et la batterie "
                              "du genre : de quoi l'essayer en situation sur "
                              "la machine. " + _PLAN,
        "Kit en morceau": "**Écrit sur la carte.** Crée dans SONGS un "
                          "morceau neuf : ce kit et un clip qui joue le "
                          "rythme de son genre. " + _PLAN,
        "@_role": "Ce que le son doit faire dans un morceau : une basse ne "
                  "se règle pas comme une nappe",
        "@_mode": "Moteur de synthèse. « Choisi par le genre » laisse le "
                  "générateur décider, ce qui donne les sons les plus "
                  "typés",
        "@_seed": "Deux générations avec la même graine et les mêmes "
                  "réglages donnent exactement le même son",
        "Produire 8 variantes": "Crée huit cousins du son actuel ; un clic "
                                "les écoute, un double-clic en adopte un",
        "Fondre": "Mélange le son courant avec celui choisi dans "
                  "l'historique : les réglages se mélangent selon le "
                  "dosage, les formes d'onde basculent à mi-chemin",
        "@_morph_amount": "Dosage du fondu : à gauche le son courant, à "
                          "droite le son choisi dans l'historique",
        "Générer un lot dans un dossier…": "Fabrique plusieurs presets d'un "
                                           "coup et les écrit dans un "
                                           "dossier de la carte que vous "
                                           "choisirez",
        "Construire le kit": "Assemble un kit autour d'une machine ou d'une "
                             "banque de la carte (909, Linndrum, un kit "
                             "d'artiste…), choisie selon le genre, puis "
                             "complète les rôles manquants  (rien n'est "
                             "encore écrit)",
        "Enregistrer dans KITS": "Écrit le kit sur la carte, dans KITS/ — "
                                 "avec confirmation",
        "Autre son": "Remplace le son de la rangée choisie dans la liste "
                     "par un autre du même rôle — de la même machine "
                     "d'abord, puis d'une machine voisine — sans toucher au "
                     "reste du kit  (rien n'est encore écrit)",
        "@_kit_genre": "Oriente le choix des sons : une grosse caisse techno "
                       "ne ressemble pas à une grosse caisse funk",
        "@_kit_seed": "Même graine, même kit : de quoi retrouver un "
                      "assemblage qui vous plaisait",
        "@_kit_name": "Nom du fichier qui sera écrit dans KITS/",
        "@_kit_folder": "Limite la recherche d'échantillons à un dossier de "
                        "la carte ; vide, toute la bibliothèque est "
                        "candidate",
    },

    # ---------------------------------------------------------------- #
    "Toolbox": {
        "@_root": "Note de départ de la gamme",
        "@_scale": "Type de gamme : change les notes proposées et les "
                   "accords ci-dessous",
        "Copier": "Copie la liste de notes dans le presse-papier, au format "
                  "que le Deluge écrit dans ses fichiers",
        "@_progression_kind": "Ambiance de la suite d'accords proposée",
        "@_progression_bars": "Nombre de mesures de la progression",
        "Proposer": "Tire une suite d'accords dans la gamme choisie",
        "En MIDI": "Écrit un fichier .mid à l'endroit que vous choisirez",
        "@_export_prog_button": "Écrit la progression et son "
                                "accompagnement dans un fichier .mid : une "
                                "piste par partie (accords, basse, arpège, "
                                "mélodie), chacune sur son canal",
        "@_export_beat_button": "Écrit le motif affiché dans un fichier .mid, "
                                "percussions sur le canal 10",
        "@_listen_prog_button": "Joue la progression avec son "
                                "accompagnement, sur des sons générés pour le "
                                "genre choisi — rien n'est écrit",
        "@_acc_genre": "Choisit le rythme des accords, le style de basse, "
                       "l'arpège et le tempo — ainsi que les sons de "
                       "l'écoute",
        "@_acc_chords": "Façon de poser les accords dans la mesure : tenus, "
                        "en blanches, sur les contretemps, en stabs "
                        "syncopés, ou en « charleston »",
        "@_acc_bass": "Style de la ligne de basse tirée des accords : "
                      "fondamentale, croches, contretemps, roulante, "
                      "octaves, syncopée ou marche",
        "@_acc_arp": "Ajoute un arpège des accords, joué au-dessus d'eux",
        "@_acc_melody": "Ajoute une mélodie : un motif repris puis varié, "
                        "les notes de l'accord sur les temps forts, une "
                        "fin sur la fondamentale ; son allure suit le genre",
        "@_melody_button": "Tire une autre mélodie sur les mêmes accords et "
                           "la fait écouter — rien n'est écrit",
        "@_prog_color": "Ce qu'on empile sur chaque degré : triades, "
                        "septièmes, neuvièmes (jouées sans fondamentale, que "
                        "tient la basse) ou accords suspendus ; « selon "
                        "l'ambiance » met des septièmes au jazz et à la "
                        "house, des neuvièmes à la deep et à l'ambient",
        "@_acc_bpm": "Tempo de l'écoute et du fichier MIDI ; il suit le "
                     "genre choisi",
        "@_acc_drums": "Ajoute la batterie : le rythme de l'onglet Rythme, "
                       "ou à défaut celui du genre, joué par des sons de la "
                       "carte — et en piste 10 dans le fichier MIDI",
        "@_chord_button": "Remplace l'accord choisi dans la liste par un "
                          "autre de même fonction (tonique, sous-dominante, "
                          "dominante) — le reste de la progression ne bouge "
                          "pas",
        "@_variation_button": "Varie le motif sans toucher à son ossature : "
                              "grosse caisse, caisse claire et clap restent ; "
                              "notes fantômes, charleys, percussion ou "
                              "charleston ouvert changent",
        "@_listen_beat_button": "Joue le motif deux fois, avec les "
                                "échantillons de la carte quand elle en a, "
                                "sinon une batterie synthétisée — rien "
                                "n'est écrit",
        "@_beat_bpm": "Tempo de l'écoute et du fichier MIDI du motif ; il "
                      "suit le genre choisi",
        "@_listen_section_button": "Joue le début de la section choisie "
                                   "dans le tableau (huit mesures au plus), "
                                   "avec les seules parties de son rôle",
        "@_export_sketch_button": "Écrit le morceau entier dans un fichier "
                                  ".mid : une piste par partie, la batterie "
                                  "en piste 10, le nom des sections en "
                                  "repères",
        "@_song_prog_button": "**Écrit sur la carte.** Crée dans SONGS un "
                              "morceau neuf : un instrument et un clip par "
                              "partie (accords, basse, arpège, mélodie, "
                              "batterie), avec les sons de l'écoute ; les "
                              "clips bouclent ensemble dès qu'on appuie sur "
                              "PLAY. " + _PLAN,
        "@_song_beat_button": "**Écrit sur la carte.** Crée dans SONGS un "
                              "morceau neuf : un kit de la carte et un clip "
                              "qui joue le motif affiché ; une piste sans "
                              "son, comme une piste euclidienne, reçoit une "
                              "percussion de la bibliothèque. " + _PLAN,
        "@_song_sketch_button": "**Écrit sur la carte.** Crée dans SONGS un "
                                "morceau à sections : chaque section du "
                                "modèle devient une section du Deluge, avec "
                                "ses clips et son nombre de répétitions. PLAY "
                                "joue la première en boucle ; lancez la "
                                "suivante et le reste s'enchaîne jusqu'à la "
                                "fin. L'arrangement (touche SONG) joue tout "
                                "le morceau d'un trait. " + _PLAN,
        "@_beat_genre": "Style du motif rythmique engendré",
        "@_beat_bars": "Longueur du motif, en mesures",
        "Motif du genre": "Engendre un rythme typique du genre choisi",
        "@_pulses": "Nombre de coups à répartir dans le motif",
        "@_steps": "Nombre de pas du motif : 16 pas = une mesure en "
                   "double-croches",
        "@_rotation": "Décale le motif d'un ou plusieurs pas, sans changer "
                      "ses coups",
        "Ajouter la piste": "Ajoute ce motif euclidien au rythme en cours, "
                            "sur une nouvelle piste",
        "@_groove": "Swing d'échantillonneur en pourcentage (58 % léger, "
                    "66 % ternaire), ou jeu derrière / devant le temps. Le "
                    "même pourcentage se règle dans le swing du Deluge",
        "@_swing": "Swing libre ajouté au groove, de droit à ternaire",
        "Appliquer": "Applique le groove au motif affiché, toujours depuis "
                     "le motif droit : un second clic ne cumule pas",
        "@_bpm": "Tempo servant à tous les calculs de cette page",
        "@_mem_rate": "Fréquence d'échantillonnage supposée pour le calcul "
                      "de place",
        "@_mem_bits": "Résolution supposée : 24 bits occupe une fois et "
                      "demie la place de 16",
        "@_mem_channels": "Une piste stéréo occupe deux fois la place d'une "
                          "mono",
        "@_mem_seconds": "Durée totale d'audio dont vous voulez connaître le "
                         "poids",
        "@_key_search": "Tapez une tonalité (Am, C, F#m) pour voir ses "
                        "voisines sur la roue",
        "Chercher": "Montre les échantillons de la carte dans cette tonalité "
                    "et dans les tonalités compatibles",
        "@_arr_genre": "Style du modèle de structure proposé",
        "@_arr_bpm": "Tempo utilisé pour convertir les sections en minutes "
                     "et en secondes",
    },

    # ---------------------------------------------------------------- #
    "Health": {
        "Diagnostiquer": "Relit l'index déjà constitué et cherche les "
                         "anomalies : ne touche pas à la carte, et prend "
                         "moins d'une seconde",
        "Corriger automatiquement": "Montre d'abord le plan exact des "
                                    "opérations ; rien n'est fait avant "
                                    "votre accord",
        "Exporter le rapport": "Écrit le diagnostic dans un fichier texte, à "
                               "l'endroit que vous choisirez",
        "@_keep": "Lequel des doublons garder : les autres seront proposés à "
                  "la suppression",
        "Supprimer les doublons": "**Écrit sur la carte.** Montre d'abord la "
                                  "liste exacte des fichiers à supprimer ; "
                                  "seuls les fichiers rigoureusement "
                                  "identiques, vérifiés octet par octet, "
                                  "sont concernés",
        "Chercher des remplaçants": "Cherche sur la carte des fichiers qui "
                                    "pourraient remplacer les échantillons "
                                    "manquants — ne modifie rien",
        "Relier automatiquement": "**Écrit sur la carte.** Corrige les "
                                  "presets pour qu'ils pointent vers les "
                                  "remplaçants trouvés ; une copie .bak est "
                                  "laissée à côté de chaque fichier modifié",
        "Archiver dans _UNUSED": "**Déplace des fichiers.** Les échantillons "
                                 "inutilisés vont dans un dossier _UNUSED de "
                                 "la carte : rien n'est supprimé, tout est "
                                 "récupérable",
        "@_zip": "Compresse la sauvegarde : plus lente à écrire, bien plus "
                 "petite sur le disque",
        "Sauvegarder maintenant": "Copie toute la carte dans le dossier de "
                                  "sauvegarde indiqué dans les réglages",
        "Comparer": "Montre ce qui a changé entre la sauvegarde choisie et "
                    "la carte telle qu'elle est aujourd'hui",
        "Restaurer": "**Écrase des fichiers de la carte** par ceux de la "
                     "sauvegarde. Le plan exact est montré avant, et rien "
                     "ne part sans votre accord",
    },

    # ---------------------------------------------------------------- #
    "Settings": {
        "@_path_edit": "Dossier racine de la carte : celui qui contient "
                       "SONGS, SYNTHS, KITS et SAMPLES",
        "Parcourir…": "Choisir un dossier dans une fenêtre, plutôt que de "
                       "taper son chemin",
        "Utiliser cette carte": "Adopte ce chemin et relit la carte",
        "@_recent_box": "Cartes utilisées récemment",
        "Détecter les cartes": "Cherche une carte Deluge sur les lecteurs "
                               "branchés : est reconnu tout dossier qui "
                               "contient au moins deux dossiers du Deluge",
        "@_device_box": "Où l'application joue ses aperçus audio",
        "@_volume": "Volume des aperçus, sans effet sur le Deluge",
        "@_autoplay": "Un simple clic dans la liste joue le son, sans avoir "
                      "à viser le bouton Écouter",
        "@_scan_hash": "Calcule une empreinte de chaque fichier : l'analyse est "
                  "plus lente, mais les doublons sont détectés par leur "
                  "contenu et non par leur nom",
        "@_scan_analyze": "Mesure tempo, tonalité et niveaux de chaque "
                     "échantillon : beaucoup plus lent, mais c'est ce qui "
                     "alimente la recherche par ressemblance",
        "@_index_on_start": "À chaque démarrage, relit seulement les "
                            "fichiers de la carte modifiés depuis la "
                            "dernière analyse, en arrière-plan — la carte "
                            "n'est que lue",
        "Réinitialiser l'index": "Vide l'index de l'application. **La carte "
                                 "n'est pas touchée** ; il faudra relancer "
                                 "une analyse",
        "@_confirm": "Garde-fou : aucune écriture sur la carte sans une "
                     "question préalable",
        "@_backup": "Garde-fou : chaque XML réécrit laisse une copie .bak "
                    "datée à côté de lui",
        "@_backup_dir": "Où les sauvegardes complètes de la carte sont "
                        "écrites ; vide, elles vont dans le dossier de "
                        "configuration de l'application",
        "Ouvrir": "Ouvre le dossier de configuration de l'application "
                  "(réglages, index, journal)",
        "@_midi_auto": "Ouvre les ports dès que la machine apparaît, sans "
                       "rien demander",
        "@_midi_audition": "Les presets sonneront sur le Deluge, avec son "
                           "vrai moteur, au lieu de l'approximation "
                           "calculée ici",
        "@_midi_out_box": "Port par lequel l'application parle au Deluge",
        "@_midi_in_box": "Port par lequel elle l'écoute ; facultatif",
        "@_midi_channel": "Canal que le Deluge écoute en mode MIDI Follow : "
                          "il doit être réglé sur la machine aussi "
                          "(MIDI ▸ Follow ▸ Channel A)",
        "@_midi_follow_tempo": "Quand la machine joue, son horloge donne "
                               "le tempo des outils : écoutes, fichiers "
                               "MIDI et morceaux de la boîte à outils",
        "@_midi_live": "Ouvre une fenêtre à garder à côté : l'écran du "
                       "Deluge recopié, son tempo, les notes tenues et les "
                       "réglages du son sélectionné — rien n'est écrit sur "
                       "la machine",
        "Connecter": "Ouvre les ports du Deluge : notes et contrôleurs par "
                     "le premier, SysEx par le troisième ; la machine dit "
                     "alors sa version",
        "Jouer un do": "Envoie une note au Deluge pour vérifier le câble",
        "Tout éteindre": "Relâche toutes les notes, sur tous les canaux : "
                         "le bouton de secours si un son reste coincé",
    },

    # ---------------------------------------------------------------- #
    "Dashboard": {
        "Voir le détail": "Ouvre le diagnostic complet de la carte",
        "@_next_button": "Fait la chose proposée ci-contre, ou vous mène "
                         "directement à l'endroit où elle se fait",
        "@_scan_button": "Relit la carte et met l'index à jour  (Ctrl+R)",
        "@_stop_button": "Interrompt l'analyse ; ce qui a déjà été lu est "
                         "conservé",
    },
}


def _cles_du_widget(page, widget) -> list[str]:
    """Les clés sous lesquelles ce widget peut être décrit."""
    cles = []
    for nom, valeur in vars(page).items():
        if valeur is widget:
            cles.append("@" + nom)
            break
    texte = ""
    # Un bouton replié sur son icône n'a plus de texte : son nom complet
    # est resté en propriété (cf. ``_ActionsCompactes``).
    try:
        complet = widget.property("libelleComplet")
    except Exception:                  # noqa: BLE001
        complet = None
    if complet:
        cles.append(str(complet))
    for lecteur in ("text", "placeholderText"):
        methode = getattr(widget, lecteur, None)
        if callable(methode):
            try:
                texte = (methode() or "").strip()
            except Exception:          # noqa: BLE001
                texte = ""
            if texte:
                break
    if texte:
        cles.append(texte)
    return cles


def expliquer(page, key: str) -> int:
    """Pose les explications manquantes sur les commandes d'une page.

    Une infobulle déjà écrite au moment de la création l'emporte : elle est
    plus proche du code, donc plus facile à garder juste.

    :return: le nombre d'explications posées.
    """
    from PyQt6.QtWidgets import (QAbstractButton, QComboBox, QDoubleSpinBox,
                                 QLineEdit, QSlider, QSpinBox)

    table = dict(COMMUNES)
    table.update(EXPLICATIONS.get(str(key), {}))
    posees = 0
    classes = (QAbstractButton, QComboBox, QSlider, QSpinBox,
               QDoubleSpinBox, QLineEdit)
    for classe in classes:
        for widget in page.findChildren(classe):
            try:
                if widget.toolTip():
                    continue
                for cle in _cles_du_widget(page, widget):
                    aide = table.get(cle)
                    if aide:
                        widget.setToolTip(aide)
                        posees += 1
                        break
            except Exception as exc:   # noqa: BLE001 - une aide ne casse rien
                log.debug("explication impossible : %s", exc)
    return posees


def manquantes(page, key: str, ignorer=()) -> list[str]:
    """Les commandes de la page qui n'expliquent toujours rien.

    Sert au test de couverture : une commande sans explication est une
    commande que l'utilisateur doit deviner.
    """
    from PyQt6.QtWidgets import (QAbstractButton, QComboBox, QDoubleSpinBox,
                                 QLineEdit, QSlider, QSpinBox)

    classes = (QAbstractButton, QComboBox, QSlider, QSpinBox,
               QDoubleSpinBox, QLineEdit)
    restantes = []
    for classe in classes:
        for widget in page.findChildren(classe):
            if widget.toolTip() or _est_interne(widget):
                continue
            cles = _cles_du_widget(page, widget)
            if any(c in ignorer for c in cles):
                continue
            restantes.append(cles[0] if cles
                             else "(%s sans nom)" % type(widget).__name__)
    return restantes


#: Noms que Qt donne à ses propres rouages : boutons de défilement d'une
#: barre d'onglets, coin d'un tableau, flèches d'un compteur. L'utilisateur
#: ne les « commande » pas, et leur écrire une aide n'aurait pas de sens.
_INTERNES_QT = {"qt_tableview_cornerbutton", "ScrollLeftButton",
                "ScrollRightButton"}
_PARENTS_INTERNES = ("QScrollBar", "QTabBar", "QHeaderView", "QSpinBox",
                     "QDoubleSpinBox", "QComboBox", "QLineEdit")


def _est_interne(widget) -> bool:
    nom = widget.objectName()
    if nom in _INTERNES_QT or nom.startswith("qt_"):
        return True
    parent = widget.parent()
    while parent is not None:
        if type(parent).__name__ in _PARENTS_INTERNES:
            return True
        parent = parent.parent()
    return False
