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
dix pages et échoue s'il reste une commande muette, ou si une explication
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

Les textes sont en français, marqués par ``N_`` et traduits au moment de
poser l'infobulle. Un bouton désigné par son libellé français est retrouvé
aussi sous sa traduction (:func:`delugeapp.i18n.sources`).
"""

from __future__ import annotations

import logging

from ..i18n import N_, sources, tr

log = logging.getLogger(__name__)

__all__ = ["COMMUNES", "EXPLICATIONS", "expliquer", "manquantes",
           "traduire"]


#: Ce que disent toutes les commandes qui écrivent un morceau.
_PLAN = (N_("Le nom est demandé et le plan montré avant d'écrire ; aucun "
            "fichier existant n'est remplacé"))

#: Libellés présents sur plusieurs pages.
COMMUNES: dict[str, str] = {
    "Arrêter": N_("Coupe l'écoute en cours  (Espace)"),
    "Indiquer le dossier": N_("Aller choisir l'emplacement de la carte dans "
                              "les réglages"),
    "Détecter la carte": N_("Cherche une carte Deluge sur les lecteurs "
                            "branchés : est reconnu tout dossier contenant au "
                            "moins deux des dossiers SONGS, SYNTHS, KITS et "
                            "SAMPLES"),
    "Dans l'explorateur": N_("Ouvre le dossier du fichier dans l'explorateur "
                             "Windows — rien n'est modifié"),
}


#: Par page, puis par commande.
EXPLICATIONS: dict[str, dict[str, str]] = {

    # ---------------------------------------------------------------- #
    "Samples": {
        "@_play_button": N_("Joue l'échantillon sélectionné sur l'ordinateur  "
                            "(ou sur le Deluge si vous l'avez demandé dans "
                            "les réglages)"),
        "@_search": N_("Filtre la liste sur le nom du fichier ; la recherche "
                       "part toute seule après une courte pause"),
        "@_category": N_("Ne montre que les échantillons d'une catégorie — "
                         "celle-ci vient du dossier où ils sont rangés"),
        "@_duration": N_("Ne montre que les sons d'une certaine longueur : "
                         "utile pour isoler les frappes courtes des nappes"),
        "@_only_fav": N_("Ne montre que les échantillons marqués d'une étoile "
                         "pleine dans l'aperçu"),
        "@_fav": N_("Marque ce son comme favori ; le filtre « Favoris » "
                    "au-dessus s'en sert"),
        "@_tag_edit": N_("Le nom d'une étiquette à poser sur ce son — "
                         "« sombre », « à garder », « live »… Entrée "
                         "l'ajoute ; elle reste sur l'ordinateur, pas sur "
                         "la carte"),
        "@_tag_add": N_("Pose l'étiquette écrite à côté sur le son choisi"),
        "@_wavetable_button": N_("**Écrit sur la carte.** Tire du son choisi "
                                 "une table d'onde — une période prélevée "
                                 "64 fois, du début à la fin — et l'écrit "
                                 "dans SAMPLES/WAVETABLES, après votre "
                                 "accord"),
        "@_instrument_button": N_("Fait des sons d'un dossier un preset "
                                  "multi-échantillon : une tranche du clavier "
                                  "par son, la hauteur lue dans le nom ou à "
                                  "l'écoute. Le plan est montré avant "
                                  "d'écrire dans SYNTHS"),
        "@_deluge_fav_button": N_("**Écrit sur la carte.** Pose le son sur le "
                                  "premier pad libre des favoris "
                                  "d'échantillons du Deluge — ou l'en "
                                  "retire —, après votre accord"),
        "@_undo_fix_button": N_("**Écrase des fichiers.** Remet les "
                                "originaux d'un traitement précédent, gardés "
                                "dans _BACKUP ; la version actuelle y est "
                                "mise de côté avant"),
        "@_tag_filter": N_("Ne montre que les sons qui portent une "
                           "étiquette ; il apparaît dès que vous en avez "
                           "posé une"),
        "@_only_unused": N_("Ne montre que les sons qu'aucun preset, kit ni "
                            "morceau n'utilise — candidats au rangement"),
        "@_only_missing": N_("Ne montre que les fichiers réclamés par un "
                             "preset mais absents de la carte"),
        "@_send_button": N_("**Écrit sur la carte.** Choisissez des sons ou "
                            "des presets du PC : le plan montre où chacun "
                            "ira, ce qui est déjà sur la carte et ce que le "
                            "Deluge refuserait, avant toute copie. Un dossier "
                            "ou un pack entier se glisse sur la fenêtre  "
                            "(Ctrl+I)"),
    },

    # ---------------------------------------------------------------- #
    "Synths": {
        "Écouter": N_("Rend le preset et le joue — approximation calculée par "
                      "l'ordinateur, ou vrai son de la machine si le Deluge "
                      "est branché et l'écoute réglée sur lui"),
        "@_search": N_("Filtre les presets sur leur nom"),
        "@_category": N_("Ne montre que les presets d'une catégorie, déduite "
                         "de leur dossier et de leur contenu"),
        "Dupliquer": N_("Copie le preset sous un nouveau nom, dans le même "
                        "dossier de la carte — l'original n'est pas touché"),
        "Varier dans le générateur": N_("Ouvre ce preset dans le générateur "
                                        "pour le muter ou en tirer des "
                                        "variantes — l'original n'est jamais "
                                        "réécrit"),
        "@_use_button": N_("Donne ce son au morceau de l'atelier, à la piste "
                           "de sa catégorie — une basse à la basse, une nappe "
                           "aux accords —, ou le garde pour le prochain "
                           "morceau. Rien n'est écrit sur la carte"),
    },

    # ---------------------------------------------------------------- #
    "Kits": {
        "Écouter la rangée": N_("Joue l'échantillon de la rangée choisie dans "
                                "le tableau"),
        "Écouter le kit": N_("Joue le motif d'essai avec les sons du kit : "
                             "sur le Deluge s'il est branché, sinon en rendu "
                             "approché"),
        "@_search": N_("Filtre les kits sur leur nom"),
        "@_genre": N_("Charge un motif rythmique typique du genre, limité aux "
                      "rangées que ce kit possède"),
        "Motif en MIDI": N_("Écrit le motif d'essai dans un fichier .mid, à "
                            "l'endroit que vous choisirez — hors de la carte"),
        "@_use_button": N_("Fait de ce kit la batterie du morceau de "
                           "l'atelier, ou du prochain : il y joue les clips de "
                           "batterie, et s'écrit avec le morceau. Rien n'est "
                           "écrit sur la carte"),
    },

    # ---------------------------------------------------------------- #
    "Songs": {
        "@_open_button": N_("Ouvre le morceau choisi dans l'atelier : ses "
                            "pistes, ses clips et ses sections deviennent ceux "
                            "du projet, et l'atelier le complète sans le "
                            "réécrire. Rien n'est modifié"),
        "@_listen_song_button": N_("Calcule le morceau entier sur "
                                   "l'ordinateur, sur son arrangement et avec "
                                   "les sons de chaque clip, puis le joue. "
                                   "Rien n'est écrit"),
        "@_listen_clip_button": N_("Calcule le clip choisi comme la machine le "
                                   "joue, sur toute sa boucle, puis le joue. "
                                   "Un double-clic sur un clip fait de même"),
        "@_stop_button": N_("Arrête l'écoute, et le calcul s'il tourne encore"),
        "@_search": N_("Filtre les morceaux sur leur nom"),
        "Clip en MIDI": N_("Écrit le clip choisi dans un fichier .mid, à "
                           "l'endroit que vous choisirez"),
        "Morceau en MIDI": N_("Écrit toutes les pistes du morceau dans un "
                              "seul fichier .mid, une piste par clip"),
        "Rassembler…": N_("Copie le morceau **et tout ce dont il dépend** "
                          "(presets, kits, échantillons) dans un dossier à "
                          "part : de quoi l'emporter ailleurs sans rien "
                          "perdre"),
        "Rapport HTML": N_("Écrit une page web décrivant le morceau : tempo, "
                           "clips, instruments, échantillons utilisés"),
    },

    # ---------------------------------------------------------------- #
    "Daw": {
        "@_reveal_button": N_("Ouvre dans l'explorateur Windows le dernier "
                              "dossier exporté pour le DAW, ou celui du "
                              "projet ouvert — rien n'est modifié"),
        "@_to_search": N_("Filtre les morceaux sur leur nom"),
        "@_live_search": N_("Filtre les morceaux sur leur nom"),
        "@_fmt_als": N_("Un set Ableton Live : une piste MIDI par piste du "
                        "morceau, une scène par section, l'arrangement "
                        "entier, les repères, le tempo, et les pistes audio. "
                        "Bâti avec les fichiers du Live installé sur ce PC ; "
                        "grisé s'il n'est pas trouvé"),
        "@_fmt_midi": N_("Un fichier .mid : tempo, repères de section, une "
                         "piste par piste du morceau, la batterie sur le "
                         "canal 10. Tous les DAW l'ouvrent"),
        "@_fmt_dawproject": N_("Un projet .dawproject : pistes, clips en "
                               "boucles, arrangement, scènes, repères, et les "
                               "pistes audio. Bitwig Studio l'ouvre, Studio "
                               "One et Cubase l'importent"),
        "@_fmt_rpp": N_("Un projet Reaper .rpp : pistes, objets MIDI en "
                        "boucles, repères, et les pistes audio"),
        "@_stems_machine": N_("Copie dans le dossier les pistes que le Deluge "
                              "a exportées lui-même (Export Tracks), le rendu "
                              "le plus fidèle ; grisé s'il n'y en a pas pour "
                              "ce morceau"),
        "@_stems_pc": N_("Calcule sur l'ordinateur une piste audio par "
                         "synthé et par kit, avec l'écoute fidèle au Deluge, "
                         "toutes calées au début du morceau — plusieurs "
                         "minutes pour un long morceau"),
        "@_export_button": N_("Demande un dossier du PC, puis y écrit un "
                              "dossier **neuf** pour le DAW, avec un "
                              "lisez-moi ; le morceau et la carte ne changent "
                              "pas"),
        "@_open_project_button": N_("Lit un fichier MIDI, un set Ableton "
                                    "Live, un DAWproject ou un projet Reaper, "
                                    "et propose ce que devient chaque piste "
                                    "— rien n'est encore écrit"),
        "@_import_source": N_("Les sections du nouveau morceau suivent "
                              "l'arrangement du projet (coupé à ses repères) "
                              "ou ses scènes ; grisé si le projet n'a que "
                              "l'un des deux"),
        "@_import_bars": N_("Une longue section de l'arrangement est coupée "
                            "en tranches de cette taille, pour des clips à "
                            "la mesure de la machine ; le déroulé ne change "
                            "pas"),
        "@_import_genre": N_("Le style des sons générés pour les pistes "
                             "devenues synthés et kits"),
        "@_import_button": N_("**Écrit sur la carte.** Crée dans SONGS un "
                              "morceau neuf : une piste par piste retenue, "
                              "un clip par section où elle joue. ")
                           + _PLAN,
        "@_keep_existing": N_("Une piste qui écoute déjà un canal le garde ; "
                              "décochée, chacune reçoit un canal libre"),
        "@_daw_choice": N_("Le DAW dont les réglages s'affichent pas à pas "
                           "ci-dessous"),
        "@_live_button": N_("**Écrit sur la carte.** Une copie du morceau où "
                            "chaque piste écoute son canal ; le plan est "
                            "montré avant, l'original n'est pas touché"),
    },

    # ---------------------------------------------------------------- #
    "Generator": {
        "Générer": N_("Fabrique un preset complet à partir du genre, du rôle "
                      "et de la graine ci-dessous  (rien n'est encore écrit "
                      "sur la carte)"),
        "Au hasard": N_("Tire un genre, un rôle et une graine au hasard, puis "
                        "génère"),
        "Muter": N_("Repart du son actuel et en change quelques réglages : de "
                    "quoi explorer autour d'une idée qui plaît"),
        "Écouter": N_("Joue le son généré — sur le Deluge s'il est branché et "
                      "l'écoute réglée sur lui, sinon en rendu approché"),
        "Enregistrer dans SYNTHS": N_("**Écrit sur la carte.** Demande un "
                                      "nom et un sous-dossier de SYNTHS, "
                                      "puis y écrit le preset ; un fichier "
                                      "du même nom n'est remplacé qu'après "
                                      "une question"),
        "Modifier le son…": N_("Ouvre l'éditeur du son courant : oscillateurs, "
                               "filtres, enveloppes, LFO, effets et "
                               "modulations, chaque réglage au cran de la "
                               "machine et en clair. Le son retouché rejoint "
                               "l'historique  (rien n'est écrit sur la "
                               "carte)"),
        "@_try_preset_button": N_("Le son rejoint le morceau de l'atelier, à "
                                  "la piste de son rôle — la basse pour une "
                                  "basse, les accords pour une nappe —, ou "
                                  "le prochain morceau s'il n'y en a pas : "
                                  "vous l'entendez en situation, et ses "
                                  "variantes restent dans le style. Rien "
                                  "n'est écrit sur la carte"),
        "@_try_kit_button": N_("Le kit devient la batterie du morceau de "
                               "l'atelier, ou du prochain : vous l'entendez "
                               "jouer les clips du morceau. Rien n'est écrit "
                               "sur la carte"),
        "Écouter le kit": N_("Joue chaque rangée du kit construit, l'une "
                             "après l'autre — rien n'est écrit"),
        "@_role": N_("Ce que le son doit faire dans un morceau : une basse ne "
                     "se règle pas comme une nappe"),
        "@_mode": N_("Moteur de synthèse. « Choisi par le genre » laisse le "
                     "générateur décider, ce qui donne les sons les plus "
                     "typés"),
        "@_seed": N_("Deux générations avec la même graine et les mêmes "
                     "réglages donnent exactement le même son"),
        "Produire 8 variantes": N_("Crée huit cousins du son actuel ; un clic "
                                   "les écoute, un double-clic en adopte un"),
        "Fondre": N_("Mélange le son courant avec celui choisi dans "
                     "l'historique : les réglages se mélangent selon le "
                     "dosage, les formes d'onde basculent à mi-chemin"),
        "@_morph_amount": N_("Dosage du fondu : à gauche le son courant, à "
                             "droite le son choisi dans l'historique"),
        "Générer un lot dans un dossier…": N_("Fabrique plusieurs presets "
                                              "d'un coup et les écrit dans un "
                                              "dossier de la carte que vous "
                                              "choisirez"),
        "Construire le kit": N_("Assemble un kit autour d'une machine ou "
                                "d'une banque de la carte (909, Linndrum, un "
                                "kit d'artiste…), choisie selon le genre, "
                                "puis complète les rôles manquants  (rien "
                                "n'est encore écrit)"),
        "Enregistrer dans KITS": N_("**Écrit sur la carte.** Écrit le kit "
                                    "dans KITS/, sous le nom indiqué ; un "
                                    "fichier du même nom n'est remplacé "
                                    "qu'après une question"),
        "Autre son": N_("Remplace le son de la rangée choisie dans la liste "
                        "par un autre du même rôle — de la même machine "
                        "d'abord, puis d'une machine voisine — sans toucher "
                        "au reste du kit  (rien n'est encore écrit)"),
        "@_kit_genre": N_("Oriente le choix des sons : une grosse caisse "
                          "techno ne ressemble pas à une grosse caisse funk"),
        "@_kit_seed": N_("Même graine, même kit : de quoi retrouver un "
                         "assemblage qui vous plaisait"),
        "@_kit_name": N_("Nom du fichier qui sera écrit dans KITS/"),
        "@_kit_folder": N_("Limite la recherche d'échantillons à un dossier "
                           "de la carte ; vide, toute la bibliothèque est "
                           "candidate"),
    },

    # ---------------------------------------------------------------- #
    "Atelier": {
        "@_history_box": N_("Les sons que la piste a eus avant celui-ci, du "
                            "plus récent au plus ancien : ce que « Autre "
                            "son » a remplacé n'est pas perdu"),
        "@_history_button": N_("Rend à la piste le son choisi dans la liste "
                               "d'à côté ; le son actuel y prend sa place"),
        "@_compose_button": N_("Fabrique un morceau neuf dans le style "
                               "choisi : une piste par partie cochée, un "
                               "premier clip chacune, et la structure du "
                               "genre avec les variations qu'elle appelle. "
                               "Un morceau en cours est remplacé, après une "
                               "question  (rien n'est encore écrit sur la "
                               "carte)"),
        "@_import_button": N_("Ouvre dans l'atelier un morceau de la carte — "
                              "les derniers reçus du Deluge en tête : ses "
                              "pistes, ses clips, son tempo et sa gamme "
                              "deviennent ceux du projet, sa progression est "
                              "lue dans ses notes. Rien n'est modifié"),
        "Ouvrir un morceau du Deluge…": N_("Ouvre dans l'atelier un morceau "
                                           "de la carte : ses pistes, ses "
                                           "clips et ses sections deviennent "
                                           "ceux du projet. Rien n'est "
                                           "modifié"),
        "Composer un morceau": N_("Mène à la première étape : choisir un "
                                  "style, puis composer"),
        "@_listen_song_button": N_("Joue huit mesures du passage le plus "
                                   "plein du morceau, toutes pistes "
                                   "ensemble — rien n'est écrit"),
        "@_prev_button": N_("Revient à l'étape d'avant ; rien de ce que vous "
                            "avez fait ne se perd"),
        "@_next_button": N_("Passe à l'étape suivante du morceau ; toutes "
                            "restent ouvertes, dans l'ordre que vous "
                            "voulez"),
        "@_listen_chords_button": N_("Joue les accords du morceau, tenus, "
                                     "sur un son de nappe du style"),
        "@_other_chords_button": N_("Tire une autre suite d'accords dans la "
                                    "même ambiance ; elle servira à la "
                                    "prochaine composition"),
        "@_other_chord_button": N_("Remplace l'accord choisi dans la liste "
                                   "par un autre de même fonction (tonique, "
                                   "sous-dominante, dominante) — le reste de "
                                   "la suite ne bouge pas"),
        "@_kit_row_button": N_("Remplace le son de la rangée choisie par un "
                               "autre du même rôle — de la même machine "
                               "d'abord, puis d'une voisine — sans toucher "
                               "au reste du kit  (rien n'est écrit sur la "
                               "carte)"),
        "@_clip_midi_button": N_("Écrit le clip choisi dans un fichier .mid, "
                                 "à l'endroit que vous choisirez — hors de "
                                 "la carte ; une batterie part sur le canal "
                                 "10"),
        "@_groove": N_("Swing d'échantillonneur en pourcentage (58 % léger, "
                       "66 % ternaire), ou jeu derrière / devant le temps. Le "
                       "même pourcentage se règle dans le swing du Deluge"),
        "@_swing": N_("Swing libre ajouté au groove, de droit à ternaire"),
        "@_groove_button": N_("Pose le groove sur le clip de batterie choisi, "
                              "toujours depuis le motif droit : un second "
                              "clic remplace le premier groove au lieu de "
                              "s'y ajouter"),
        "@_pulses": N_("Nombre de coups à répartir dans la rangée"),
        "@_steps": N_("Longueur du motif euclidien, en pas : 16 pas = une "
                      "mesure en double-croches ; il se répète sur tout le "
                      "clip"),
        "@_rotation": N_("Décale le motif d'un ou plusieurs pas, sans changer "
                         "ses coups"),
        "@_euclid_button": N_("Ajoute au clip de batterie une rangée dont les "
                              "coups sont répartis au mieux — sur la carte, "
                              "elle reçoit une percussion de votre "
                              "bibliothèque"),
        "@_feel": N_("Façon de poser les accords ou la basse dans la mesure "
                     "— tenus, en blanches, sur les contretemps, en stabs ; "
                     "fondamentale, croches, roulante… Choisir une façon "
                     "fait un clip neuf, joué ainsi"),
        "@_song_name": N_("Nom du morceau dans SONGS : il est assaini pour la "
                          "carte, et numéroté s'il est déjà pris"),
        "@_show_song_button": N_("Ouvre la page Morceaux sur le morceau qui "
                                 "vient d'être écrit"),
        "@_live_window_button": N_("Ouvre une fenêtre à garder à côté : "
                                   "l'écran du Deluge recopié, son tempo, le "
                                   "son sélectionné — rien n'est écrit sur la "
                                   "machine"),
        "@_sync_button": N_("Échange tout de suite avec le Deluge branché : ce "
                            "qu'il a enregistré descend, le morceau écrit "
                            "ici monte  (Ctrl+Maj+D)"),
        "@_midi_button": N_("Écrit le morceau entier dans un fichier .mid, "
                            "à l'endroit que vous choisirez — hors de la "
                            "carte : une piste par piste, la batterie en "
                            "piste 10, le nom des sections en repères"),
        "@_write_button": N_("**Écrit sur la carte.** Crée dans SONGS un "
                             "morceau neuf : une section du Deluge par "
                             "section du projet, leurs clips, leurs "
                             "répétitions et l'arrangement complet. ")
                          + _PLAN,
        "@_complete_button": N_("**Écrit sur la carte.** Écrit une nouvelle "
                                "version du morceau d'origine (« Cool1 5 » "
                                "après « Cool1 4 ») qui le contient octet pour "
                                "octet, plus vos pistes, vos clips et vos "
                                "sections neuves ; l'original n'est pas "
                                "touché. Le plan est montré avant d'écrire"),
        "@_root": N_("Tonique du morceau : accords, basse et mélodie restent "
                     "dans sa gamme"),
        "@_scale": N_("Gamme du morceau ; le morceau écrit la donne au mode "
                      "gamme du Deluge"),
        "@_bpm": N_("Tempo du morceau ; choisir un genre le place au milieu de "
                    "sa plage"),
        "@_ambiance": N_("Ambiance de la progression d'accords — "
                         "mélancolique, house, jazz… ; par défaut, celle du "
                         "genre"),
        "@_chord_color": N_("Triades, septièmes, neuvièmes ou suspendus ; par "
                            "défaut, ce que l'ambiance appelle"),
        "@_seed": N_("Même graine et mêmes réglages, même morceau : notez-la "
                     "pour retrouver une composition"),
        "@_dice": N_("Nouvelle graine au hasard"),
        "@_new_kind": N_("Nature de la piste à ajouter : un kit, un synthé du "
                         "Deluge, une piste MIDI vers un appareil extérieur, "
                         "ou une piste CV vers un modulaire"),
        "@_new_part": N_("Ce que jouera la piste ajoutée"),
        "@_add_track_button": N_("Ajoute la piste au projet, avec un son du "
                                 "style et un premier clip  (rien n'est "
                                 "écrit sur la carte)"),
        "@_remove_track_button": N_("Retire la piste choisie du projet, et "
                                    "ses cases de toutes les sections"),
        "@_listen_sound_button": N_("Joue le son de la piste — sur le Deluge "
                                    "si l'écoute y est réglée, sinon en rendu "
                                    "approché ; une batterie joue son premier "
                                    "clip"),
        "@_other_sound_button": N_("Un autre son du même style pour un "
                                   "synthé, ou un autre kit bâti dans votre "
                                   "bibliothèque"),
        "@_card_sound_button": N_("Prend pour la piste un preset ou un kit de "
                                  "la carte, choisi dans l'index"),
        "@_edit_sound_button": N_("Ouvre l'éditeur du son de la piste : chaque "
                                  "réglage au cran de la machine, et ce qu'il "
                                  "vaut sur le Deluge (1,8 s, 237 Hz…). "
                                  "« Garder ce son » le donne à la piste  "
                                  "(rien n'est écrit sur la carte)"),
        "@_channel": N_("Canal MIDI (1 à 16) ou sortie CV (1 ou 2) de la "
                        "piste"),
        "@_variants_button": N_("Huit variantes du son, toutes dans le "
                                "style : un seul aspect tiré à nouveau "
                                "(filtre, enveloppes, espace…) ou un curseur "
                                "poussé (plus brillant, plus sale…), le reste "
                                "du son restant le même. Un son retouché à la "
                                "main garde ses retouches"),
        "@_adopt_button": N_("La piste prend le son de la variante choisie"),
        "@_listen_clip_button": N_("Joue le clip choisi sur l'ordinateur, "
                                   "avec le son de sa piste"),
        "@_live_button": N_("Joue le clip en boucle sur le Deluge, dans le "
                            "clip que suit MIDI Follow : machine en lecture, "
                            "calé sur sa mesure ; en enregistrement (REC), il "
                            "s'y inscrit. Recliquez pour arrêter"),
        "@_vary_button": N_("Une variation du clip, ajoutée à la piste : "
                            "rythme, notes, plus ou moins de notes, réponse, "
                            "octave, fin de phrase — pour une batterie, "
                            "ornements, remplissage, cassure, montée…"),
        "@_new_clip_button": N_("Un clip neuf pour la piste, sur la "
                                "progression du morceau"),
        "@_clip_bars": N_("Longueur du clip neuf"),
        "@_delete_clip_button": N_("Retire le clip de la piste ; les sections "
                                   "qui le jouaient se taisent pour elle  "
                                   "(rien n'est écrit sur la carte)"),
        "@_section_name": N_("Nom de la section ; ses clips le portent sur le "
                             "Deluge"),
        "@_section_bars": N_("Durée de la section, en mesures : ses clips y "
                             "bouclent"),
        "@_listen_section_button": N_("Joue le début de la section (huit "
                                      "mesures au plus), toutes pistes "
                                      "ensemble"),
        "@_add_section_button": N_("Ajoute une section après celle choisie, "
                                   "avec les mêmes clips"),
        "@_remove_section_button": N_("Retire la section choisie du "
                                      "morceau"),
        "@_left_button": N_("Avance la section d'un cran dans le morceau"),
        "@_right_button": N_("Recule la section d'un cran dans le morceau"),
        "@_structure_button": N_("Remplace les sections par la structure du "
                                 "genre — intro, montée, thème, cassure… —, "
                                 "avec les variations qu'elle appelle ; un "
                                 "morceau d'origine garde ses propres "
                                 "sections"),
    },

    # ---------------------------------------------------------------- #
    "Toolbox": {
        "@_root": N_("Note de départ de la gamme"),
        "@_scale": N_("Type de gamme : change les notes proposées et les "
                      "accords ci-dessous"),
        "Copier": N_("Copie la liste de notes dans le presse-papier, au "
                     "format que le Deluge écrit dans ses fichiers"),
        "@_bpm": N_("Tempo servant à tous les calculs de cette page"),
        "@_mem_rate": N_("Fréquence d'échantillonnage supposée pour le calcul "
                         "de place"),
        "@_mem_bits": N_("Résolution supposée : 24 bits occupe une fois et "
                         "demie la place de 16"),
        "@_mem_channels": N_("Une piste stéréo occupe deux fois la place "
                             "d'une mono"),
        "@_mem_seconds": N_("Durée totale d'audio dont vous voulez connaître "
                            "le poids"),
        "@_key_search": N_("Tapez une tonalité (Am, C, F#m) pour voir ses "
                           "voisines sur la roue"),
        "Chercher": N_("Montre les échantillons de la carte dans cette "
                       "tonalité et dans les tonalités compatibles"),
    },

    # ---------------------------------------------------------------- #
    "Health": {
        "Diagnostiquer": N_("Relit l'index déjà constitué et cherche les "
                            "anomalies : ne touche pas à la carte, et prend "
                            "moins d'une seconde"),
        "Corriger automatiquement": N_("Montre d'abord le plan exact des "
                                       "opérations ; rien n'est fait avant "
                                       "votre accord"),
        "Exporter le rapport": N_("Écrit le diagnostic dans une page HTML, "
                                  "à l'endroit que vous choisirez — hors de "
                                  "la carte"),
        "@_keep": N_("Lequel des doublons garder : les autres seront proposés "
                     "à la suppression"),
        "Supprimer les doublons": N_("**Écrit sur la carte.** Montre d'abord "
                                     "la liste exacte des fichiers à "
                                     "supprimer ; seuls les fichiers "
                                     "rigoureusement identiques, vérifiés "
                                     "octet par octet, sont concernés"),
        "Chercher des remplaçants": N_("Cherche sur la carte des fichiers qui "
                                       "pourraient remplacer les échantillons "
                                       "manquants — ne modifie rien"),
        "Relier automatiquement": N_("**Écrit sur la carte.** Corrige les "
                                     "presets pour qu'ils pointent vers les "
                                     "remplaçants trouvés ; une copie .bak "
                                     "est laissée à côté de chaque fichier "
                                     "modifié"),
        "Archiver dans _UNUSED": N_("**Déplace des fichiers.** Les "
                                    "échantillons inutilisés vont dans un "
                                    "dossier _UNUSED de la carte : rien n'est "
                                    "supprimé, tout est récupérable"),
        "@_zip": N_("Compresse la sauvegarde : plus lente à écrire, bien plus "
                    "petite sur le disque"),
        "Sauvegarder maintenant": N_("Copie toute la carte dans le dossier de "
                                     "sauvegarde indiqué dans les réglages"),
        "Comparer": N_("Montre ce qui a changé entre la sauvegarde choisie et "
                       "la carte telle qu'elle est aujourd'hui"),
        "Restaurer": N_("**Écrase des fichiers de la carte** par ceux de la "
                        "sauvegarde. Le plan exact est montré avant, et rien "
                        "ne part sans votre accord"),
    },

    # ---------------------------------------------------------------- #
    "Settings": {
        "@_path_edit": N_("Dossier racine de la carte : celui qui contient "
                          "SONGS, SYNTHS, KITS et SAMPLES"),
        "Parcourir…": N_("Choisir un dossier dans une fenêtre, plutôt que de "
                          "taper son chemin"),
        "Utiliser cette carte": N_("Adopte ce chemin et relit la carte"),
        "@_recent_box": N_("Cartes utilisées récemment"),
        "Détecter les cartes": N_("Cherche une carte Deluge sur les lecteurs "
                                  "branchés : est reconnu tout dossier qui "
                                  "contient au moins deux dossiers du Deluge"),
        "@_device_box": N_("Où l'application joue ses aperçus audio"),
        "@_volume": N_("Volume des aperçus, sans effet sur le Deluge"),
        "@_autoplay": N_("Un simple clic dans la liste joue le son, sans "
                         "avoir à viser le bouton Écouter"),
        "@_scan_hash": N_("Calcule une empreinte de chaque fichier : "
                          "l'analyse est plus lente, mais les doublons sont "
                          "détectés par leur contenu et non par leur nom"),
        "@_scan_analyze": N_("Mesure tempo, tonalité et niveaux de chaque "
                        "échantillon : beaucoup plus lent, mais c'est ce qui "
                        "alimente la recherche par ressemblance"),
        "@_index_on_start": N_("À chaque démarrage, relit seulement les "
                               "fichiers de la carte modifiés depuis la "
                               "dernière analyse, en arrière-plan — la carte "
                               "n'est que lue"),
        "Réinitialiser l'index": N_("Vide l'index de l'application. **La "
                                    "carte n'est pas touchée** ; il faudra "
                                    "relancer une analyse"),
        "@_check_updates": N_("Au démarrage, au plus une fois par jour, lit "
                              "sur GitHub le numéro de la dernière version, "
                              "et vous prévient si elle est plus récente. "
                              "Rien d'autre ne part sur le réseau"),
        "Tout réanalyser": N_("Relit chaque fichier de la carte, même ceux "
                              "qui n'ont pas changé, et refait empreintes et "
                              "mesures. La carte n'est que lue ; [Analyser la "
                              "carte] suffit d'ordinaire"),
        "@_confirm": N_("Garde-fou : aucune écriture sur la carte sans une "
                        "question préalable"),
        "@_backup": N_("Garde-fou : chaque XML réécrit laisse une copie .bak "
                       "datée à côté de lui"),
        "@_backup_dir": N_("Où les sauvegardes complètes de la carte sont "
                           "écrites ; vide, elles vont dans le dossier de "
                           "configuration de l'application"),
        "Ouvrir": N_("Ouvre le dossier de configuration de l'application "
                     "(réglages, index, journal)"),
        "@_midi_auto": N_("Ouvre les ports dès que la machine apparaît, sans "
                          "rien demander"),
        "@_midi_audition": N_("Les presets sonneront sur le Deluge : "
                              "l'instrument sélectionné sur lui prend leurs "
                              "filtres, enveloppes et effets, mais garde ses "
                              "propres oscillateurs"),
        "@_midi_out_box": N_("Port par lequel l'application parle au Deluge"),
        "@_midi_in_box": N_("Port par lequel elle l'écoute ; facultatif"),
        "@_midi_channel": N_("Canal que le Deluge écoute en mode MIDI Follow "
                             ": il doit être réglé sur la machine aussi (MIDI "
                             "▸ MIDI-Follow ▸ Channel ▸ Channel A)"),
        "@_midi_follow_tempo": N_("Quand la machine joue, son horloge donne "
                                  "le tempo des outils : écoutes, fichiers "
                                  "MIDI et morceaux de la boîte à outils"),
        "@_midi_live": N_("Ouvre une fenêtre à garder à côté : l'écran du "
                          "Deluge recopié, son tempo, les notes de ses pistes "
                          "MIDI et les réglages du son sélectionné — rien "
                          "n'est écrit sur la machine"),
        "@_level_simple": N_("Chaque page ne montre que l'essentiel : de quoi "
                             "créer sans se perdre"),
        "@_level_advanced": N_("Chaque page montre tous ses réglages et "
                               "toutes ses commandes : graines, moteurs, "
                               "exports, retouches de fichiers"),
        "Connecter": N_("Ouvre les ports du Deluge : notes et contrôleurs par "
                        "le premier, SysEx par le troisième ; la machine dit "
                        "alors sa version"),
        "Jouer un do": N_("Envoie une note au Deluge pour vérifier le câble"),
        "Tout éteindre": N_("Relâche toutes les notes, sur tous les canaux : "
                            "le bouton de secours si un son reste coincé"),
    },

    # ---------------------------------------------------------------- #
    "Dashboard": {
        "@_song_pad": N_("Ouvre l'atelier sur un morceau neuf — ou sur celui "
                         "en cours, à l'étape où vous en étiez : style, "
                         "sons, clips, structure, puis le Deluge"),
        "@_sound_pad": N_("Ouvre le générateur : un preset de synthé ou un "
                          "kit, par genre ou au hasard, à écouter puis "
                          "enregistrer sur la carte"),
        "@_continue_pad": N_("Choisit un morceau de la carte — les derniers "
                             "reçus du Deluge en tête — et l'ouvre dans "
                             "l'atelier pour le compléter. Rien n'est "
                             "modifié"),
        "@_explore_pad": N_("Ouvre la bibliothèque : échantillons, presets, "
                            "kits et morceaux de la carte, à écouter et "
                            "ranger"),
        "Voir le détail": N_("Ouvre le diagnostic complet de la carte"),
        "@_next_button": N_("Fait la chose proposée ci-contre, ou vous mène "
                            "directement à l'endroit où elle se fait"),
        "@_scan_button": N_("Relit la carte et met l'index à jour  (Ctrl+R)"),
        "@_stop_button": N_("Interrompt l'analyse ; ce qui a déjà été lu est "
                            "conservé"),
        "@_sync_button": N_("Échange tout de suite avec le Deluge branché : "
                            "ce qu'il a enregistré descend, ce que "
                            "l'application a créé ou reçu du PC monte  "
                            "(Ctrl+Maj+D)"),
        "@_send_button": N_("**Écrit sur la carte.** Choisir des fichiers du "
                            "PC à envoyer au Deluge ; le plan est montré "
                            "avant toute copie. Un dossier ou un pack se "
                            "glisse sur la fenêtre  (Ctrl+I)"),
        "@_goto_card_button": N_("Ouvre les réglages de la carte du Deluge : "
                                 "copie de travail, synchronisation et "
                                 "sauvegarde"),
        "@_backup_button": N_("**Écrit dans votre sauvegarde.** Y ajoute ce "
                              "qui lui manque et remplace ce qui a changé, "
                              "l'ancienne version gardée à côté ; rien n'y "
                              "est supprimé. Le plan est montré d'abord"),
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
        cles.extend(sources(str(complet)))
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
        cles.extend(sources(texte))
    return cles


def traduire(aide: str) -> str:
    """Une explication dans la langue de l'interface.

    Les commandes qui écrivent un morceau finissent toutes par la même
    phrase (:data:`_PLAN`) : elle se traduit à part.
    """
    if aide.endswith(_PLAN) and aide != _PLAN:
        return tr(aide[:-len(_PLAN)]) + tr(_PLAN)
    return tr(aide)


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
                        widget.setToolTip(traduire(aide))
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
                             else tr("(%s sans nom)") % type(widget).__name__)
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
