%% Manuel de Deluge Companion — texte français, langue source.
%% Le balisage est décrit en tête de delugeapp/ui/manuel.py.
%% Les ancres {#…} sont communes aux deux langues : ne pas les traduire.

@partie prise-en-main GOLD | Prendre en main | Installer l'application, s'y repérer, et faire ses premiers pas en dix minutes

# Bienvenue {#bienvenue icone=info}

> Deluge Companion accompagne votre Synthstrom Deluge sur l'ordinateur : il range sa carte, la soigne, et fabrique des sons et des morceaux qu'elle saura jouer.

Le Deluge est une machine qui se suffit à elle-même. Mais tout ce qu'elle sait — vos morceaux, vos presets, vos kits, des milliers d'échantillons — vit sur une petite carte SD, et cette carte, la machine ne vous aide guère à la tenir en ordre. Un échantillon déplacé rend un kit muet sans prévenir ; un preset en double ne se repère pas sur l'écran ; une sauvegarde, on y pense toujours après.

Deluge Companion est l'atelier qui manquait à côté de la machine. Il lit la carte, vous montre ce qu'elle contient et dans quel état elle est, répare ce qui est cassé, et ajoute une série d'outils de création qui écrivent directement dans le format du Deluge.

## Ce que fait l'application {#ce-que-fait}

- **Parcourir la carte** : les échantillons avec leur forme d'onde, leur tempo et leur tonalité ; les presets de synthé avec leurs oscillateurs, filtres et modulations ; les kits rangée par rangée ; les morceaux, clip par clip.
- **Écouter** chaque son d'un clic — calculé par l'ordinateur, ou joué par le Deluge lui-même s'il est branché.
- **Soigner la carte** : vingt et un contrôles, une note sur 100, des réparations guidées (échantillons manquants, doublons, noms interdits, fichiers parasites, défauts audio) et des sauvegardes.
- **Créer** : des presets de synthé par genre musical, des kits de batterie tirés de votre bibliothèque, des progressions d'accords, des rythmes, des structures de morceau — et les écrire **en morceaux du Deluge**, prêts à charger sur la machine.
- **Composer** dans l'atelier : un morceau entier dans un style — sons, clips et leurs variations, sections —, joué en direct sur le Deluge, écrit en morceau neuf, ou ajouté à un des vôtres dans une nouvelle version.
- **Travailler avec le Deluge branché** : sa carte reste dedans et s'ouvre par le câble USB, son écran se recopie sur l'ordinateur, son tempo pilote les outils.

## Ce qu'elle ne fait pas {#ce-quelle-ne-fait-pas}

- Elle **ne remplace pas le séquenceur** du Deluge : on ne compose pas un morceau note à note dans l'application.
- Elle **ne réécrit jamais un morceau** existant : le format est trop riche pour qu'une relecture-réécriture soit sûre. Elle en crée de nouveaux, à côté.
- Elle **ne peut pas charger un preset sur la machine à distance** : aucun message MIDI ne le permet. Le Deluge joue toujours l'instrument sélectionné sur lui.
- Elle n'a besoin **ni d'Internet, ni d'un compte** : tout se passe sur votre ordinateur.

## La règle d'or {#regle-dor}

!!! retenir Rien ne s'écrit sans votre accord
    Une carte de Deluge contient des mois de travail. L'application ne modifie rien sans qu'on le lui demande : tout rangement, toute réparation, toute suppression est d'abord **simulé**, et le plan exact — fichier par fichier — s'affiche avant le moindre changement. Chaque fichier XML réécrit laisse une copie `.bak` à côté de lui. Le chapitre [La règle de non-destruction](#non-destruction) détaille ces garde-fous.

## Comment lire ce manuel {#lire-ce-manuel}

Le manuel reprend les conventions du *Guide du Deluge*.

| Écriture | Signification |
|---|---|
| [Analyser] | un bouton, une case ou un onglet de l'application, tel qu'il est écrit à l'écran |
| [[Ctrl+R]] | une touche ou une combinaison de touches |
| `SAMPLES/DRUMS` | un dossier, un fichier, ou un mot du Deluge |
| Réglages ▸ Carte du Deluge | un chemin : la page, puis la partie de la page |
| [Ouvrir la santé de la carte](app:Health) | un lien qui ouvre la page dans l'application |

Cinq sortes d'encadrés ponctuent le texte, comme dans le guide :

!!! astuce Un raccourci, une façon plus rapide
    Les astuces font gagner du temps ; on peut s'en passer.

!!! attention Un piège à connaître
    Ce qui peut surprendre, ou faire perdre du travail si on l'ignore.

!!! pro Une habitude qui a fait ses preuves
    Ce que font les utilisateurs aguerris, et pourquoi.

!!! atelier Pas à pas
    Un exercice à faire en lisant, l'application ouverte à côté.

Ce manuel s'ouvre par **Aide ▸ Manuel**, ou par la touche [[F1]] : il s'ouvre alors directement au chapitre de la page que vous regardez. La colonne de gauche est son sommaire ; le champ de recherche, en haut, ignore les accents et les majuscules ; les boutons [Français] et [English] changent sa langue sans quitter votre page ; [PDF…] l'enregistre pour l'imprimer.

# Installation et démarrage {#installation icone=settings}

> Quelques minutes suffisent : Python, deux bibliothèques, et l'application s'ouvre — même sans carte.

## Ce qu'il faut {#prerequis}

- **Windows**, de préférence : c'est là que l'application est développée et que le lien MIDI avec le Deluge fonctionne. Elle démarre aussi ailleurs, sans ce lien.
- **Python 3.11** ou plus récent.
- Deux bibliothèques obligatoires : **PyQt6** pour l'interface et **numpy** pour l'audio.
- Une bibliothèque facultative : **sounddevice**, pour écouter les sons sur l'ordinateur. Sans elle, tout fonctionne, mais les boutons d'écoute restent muets.
- Pour le lien avec la machine : un câble USB, et le **firmware communautaire** du Deluge — la version 1.3 ou plus récente pour que la carte s'ouvre par le câble.

## Installer {#installer}

Dans le dossier de l'application, une seule commande installe ce qu'il faut :

`pip install -r requirements.txt`

Puis l'application se lance par :

`python main.py`

Un écran de démarrage aux couleurs du guide s'affiche le temps du chargement, puis la fenêtre principale s'ouvre.

**Une seule fenêtre à la fois** : relancer l'application ramène au premier plan celle qui est déjà ouverte. Deux fenêtres se disputeraient le Deluge branché : chacune synchroniserait sa carte, et chaque réponse de la machine arriverait aux deux.

## Les options de lancement {#options}

| Option | Effet |
|---|---|
| `--sd CHEMIN` | utilise cette carte pour la session, et la retient |
| `--reset-db` | vide l'index avant de démarrer ; il se reconstruit à la prochaine analyse |
| `--no-splash` | sans écran de démarrage |
| `--verbose` | journal détaillé dans la console |
| `--version` | affiche la version, puis quitte |

!!! pro Emporter l'application sur une clé
    La variable d'environnement `DELUGE_COMPANION_CONFIG` déplace le dossier des réglages, de l'index et du journal. Pointée vers une clé USB, elle rend l'installation portable : réglages compris.

## Le premier démarrage {#premier-demarrage}

L'application s'ouvre **même sans carte** : c'est le cas normal la première fois. Si elle trouve une carte du Deluge sur un lecteur branché, elle propose de l'utiliser. Sinon, elle ouvre la page Réglages, et l'écran de la barre du haut affiche « AUCUNE CARTE — CLIQUEZ POUR CHOISIR ».

Chaque page montre alors le même accueil : « Où est votre carte Deluge ? », et deux boutons — [Indiquer le dossier], qui mène aux réglages, et [Détecter la carte], qui cherche seul sur les lecteurs branchés.

Le chapitre suivant présente la fenêtre ; le chapitre [La carte et l'index](#carte-et-index) explique comment désigner votre carte et la faire lire.

# Se repérer dans la fenêtre {#se-reperer icone=grid}

> La fenêtre reprend la façade du Deluge : une rangée de pads lumineux à gauche, un écran en haut, et une couleur par page.

[[figure fenetre | La fenêtre principale et ses dix repères, décrits ci-dessous. | ]]

| Repère | Élément | Rôle |
|---|---|---|
| 1 | La colonne de pads | les dix pages ; le pad de la page affichée s'allume |
| 2 | Les menus | Fichier, Édition, Outils, Langue, Aide |
| 3 | L'écran | la carte ouverte, et chaque message de l'application |
| 4 | La pastille « Deluge » | l'état de la machine branchée ; un clic agit |
| 5 | La recherche | cherche un échantillon par son nom, depuis n'importe quelle page |
| 6 | [Analyser] | relit la carte et met l'index à jour |
| 7 | La touche de lecture | écoute ou arrête, comme [[Espace]] |
| 8 | Le filet lumineux | la couleur de la page affichée |
| 9 | L'en-tête de la page | son treillis, son titre, ses actions |
| 10 | La barre d'état | les messages, l'avancement, l'espace libre |

## Une couleur par page {#couleurs}

Comme chaque partie du guide a la sienne, chaque page de l'application porte une couleur, prise dans les pads de la machine. Elle se retrouve partout : le pad de la colonne, le filet sous la barre du haut, l'en-tête, le bouton principal, les sélections, les onglets, les cases et les curseurs.

[[figure pages | Les dix pages et leur raccourci clavier. | Tableau de bord ; Échantillons ; Presets ; Kits ; Morceaux ; Générateur ; Atelier ; Outils ; Santé ; Réglages]]

La couleur dit aussi **où mène un raccourci** : sur le tableau de bord, le bouton [Sauvegarder la carte] est orange parce qu'il mène à la page Santé — et il y mène directement sur l'onglet des sauvegardes.

## La colonne de pads {#colonne}

Un clic sur un pad ouvre sa page ; le chiffre à droite est son raccourci, de [[Ctrl+1]] à [[Ctrl+9]], puis [[Ctrl+0]] pour la dixième. Le bouton [Replier], en bas, réduit la colonne à ses seuls pads pour donner la place aux listes ; [[Ctrl+B]] fait de même. La colonne repliée se déplie par le même geste.

## La barre du haut {#barre-du-haut}

**Les menus** regroupent les commandes générales :

| Menu | Ce qu'il contient |
|---|---|
| Fichier | choisir la carte [[Ctrl+O]], l'analyser [[Ctrl+R]], la sauvegarder, envoyer des fichiers [[Ctrl+I]] ou un dossier [[Ctrl+Maj+I]] au Deluge, quitter [[Ctrl+Q]] |
| Édition | rechercher [[Ctrl+F]], les réglages [[Ctrl+,]] |
| Outils | le générateur [[Ctrl+G]], la boîte à outils, la santé de la carte, Deluge en direct [[Ctrl+D]], synchroniser avec le Deluge [[Ctrl+Maj+D]], replier la colonne [[Ctrl+B]] |
| Langue | Français ou English |
| Aide | ce manuel [[F1]], les premiers pas, les raccourcis clavier, à propos |

**L'écran** est celui du Deluge. En grand, le nom de la carte ouverte ; en petit, ce qu'elle contient ou ce qui l'attend. Chaque message de l'application y passe quelques secondes — et défile s'il est trop long, comme sur la machine. Un clic sur l'écran ouvre les réglages de la carte.

[[figure ecrans | Trois états de l'écran : la carte du Deluge, la sauvegarde, aucune carte. | COPIE DE TRAVAIL · 3 À ENVOYER ; CARTE DU DELUGE ; vous travaillez sur la copie tenue à l'image de la carte, trois fichiers attendent le Deluge ; SAUVEGARDE · LECTURE SEULE ; SDCARD DELUGE ; la sauvegarde est ouverte, rien n'y sera écrit ; AUCUNE CARTE ; CLIQUEZ POUR CHOISIR ; un clic mène aux réglages de la carte]]

**La pastille « Deluge »** dit où en est la machine. Elle n'apparaît que si l'ordinateur sait parler MIDI.

[[figure pastille | Les trois états de la pastille. | Grise ; aucun Deluge au bout du câble ; Or ; le Deluge est branché, un clic le connecte ; Verte ; connecté, un clic ouvre Deluge en direct]]

**La recherche** — « Rechercher partout… » — cherche un **échantillon** par son nom : elle ouvre la page Échantillons et y filtre la liste. [[Ctrl+F]] y place le curseur.

**[Analyser]** relit la carte (voir [L'analyse et l'index](#analyse)). Il reste éteint tant qu'aucune carte n'est indiquée. Sa couleur est celle de la façade, réglable dans Réglages ▸ Apparence.

**La touche de lecture**, ronde, arrête le son en cours, ou relance l'écoute de la page. Elle s'allume en vert pendant une lecture. [[Espace]] fait la même chose.

## L'en-tête de page et ses actions {#en-tete}

Chaque page s'ouvre sur un en-tête à sa couleur : un pad allumé, le titre en capitales, une phrase qui dit à quoi sert la page, et le treillis de circuits du guide. Dessous, la **barre d'actions** porte les boutons de la page. Le bouton **principal** — un seul par écran — est plein et lumineux.

!!! retenir Un bouton éteint attend quelque chose de vous
    La plupart du temps, une ligne choisie dans la liste. [Découper…], par exemple, ne s'allume que lorsqu'un seul échantillon est sélectionné, puisque le découpage porte sur une boucle à la fois.

Sur une fenêtre étroite, les boutons de la barre se replient sur leur icône plutôt que de couper leur nom. Laissez la souris dessus : l'infobulle dit leur nom.

## Chaque commande s'explique {#infobulles}

Laissez la souris une seconde sur n'importe quel bouton, case, liste ou curseur : une infobulle dit **ce qui va se passer** — pas son nom, que vous lisez déjà. La plupart des commandes qui écrivent sur la carte le disent d'entrée, en gras : « **Écrit sur la carte.** » — on le sait avant de cliquer. Le chapitre [La règle de non-destruction](#ce-qui-ecrit) les réunit toutes.

## La barre d'état {#barre-etat}

En bas de la fenêtre : le dernier message de l'application, une barre d'avancement pendant un travail long, « ● lecture » pendant une écoute, et l'espace libre de la carte.

## Les travaux longs {#travaux-longs}

Une analyse, un traitement d'échantillons, une sauvegarde, une synchronisation : tout ce qui prend du temps part en arrière-plan, et la fenêtre reste utilisable. Si vous quittez pendant un travail, l'application demande confirmation avant de l'interrompre.

## Changer de langue {#langue}

Le menu **Langue** propose « Français » et « English », chacun écrit dans sa langue. Le choix est retenu aussitôt, puis l'application propose de redémarrer — la question est posée dans les deux langues. Refuser garde le choix pour le prochain démarrage.

!!! pro Ce que l'application écrit prend la langue du moment
    Les noms qu'elle donne à ce qu'elle écrit — clips d'un morceau, pistes d'un fichier MIDI, dossiers d'un rangement — suivent la langue de l'interface au moment de l'écriture : « Accords » en français, « Chords » en anglais. Ce qui est déjà sur la carte ne change pas.

# La carte et l'index {#carte-et-index icone=save}

> L'application ne travaille jamais à l'aveugle : elle lit votre carte une fois, en tient un index, et toutes les pages s'en servent.

## Trois façons d'ouvrir la carte {#trois-facons}

| Situation | Où l'indiquer | Ce que fait l'application |
|---|---|---|
| La carte reste dans le Deluge, branché en USB (firmware 1.3 ou plus) | Réglages ▸ Carte du Deluge | elle travaille sur une **copie de travail** tenue à l'image de la carte |
| La carte est glissée dans un lecteur du PC | Réglages ▸ Autre emplacement de carte | elle travaille directement sur la carte |
| Un dossier : une copie de la carte, une sauvegarde | Réglages ▸ Autre emplacement de carte | elle y travaille ; la **sauvegarde** déclarée s'ouvre en lecture seule |

La première façon est la plus confortable : la carte ne quitte plus la machine. Elle a son chapitre, [La carte reste dans le Deluge](#carte-dans-le-deluge).

## Désigner la carte {#designer}

Dans Réglages ▸ Autre emplacement de carte, tapez le chemin de la **racine** de la carte — le dossier qui contient `SONGS`, `SYNTHS`, `KITS` et `SAMPLES` — ou cherchez-le avec [Parcourir…]. Le champ vérifie ce que vous tapez, au fil de la frappe : « Arborescence Deluge reconnue », avec l'espace libre, ou ce qui manque. [Utiliser cette carte] l'adopte.

[Détecter les cartes], en haut de la page, cherche sur tous les lecteurs branchés : est reconnu comme carte du Deluge tout emplacement qui contient **au moins deux** des dossiers `SONGS`, `SYNTHS`, `KITS` et `SAMPLES`. Chaque carte trouvée devient un bouton. Les **chemins récents** restent proposés dans une liste. Le menu Fichier ▸ Choisir la carte… [[Ctrl+O]] ouvre directement le choix d'un dossier.

## L'analyse et l'index {#analyse}

Quand une carte est indiquée, il faut la **lire** : [Analyser], dans la barre du haut, ou [[Ctrl+R]]. L'analyse parcourt la carte et remplit l'**index** — une petite base de données, rangée sur l'ordinateur et non sur la carte — avec ce qu'elle trouve : chaque échantillon, chaque preset, chaque kit, chaque morceau, et ce qui relie les uns aux autres.

- L'analyse **ne modifie rien** sur la carte : elle ne fait que lire.
- Elle est **incrémentale** : la deuxième fois, seuls les fichiers changés sont relus. Une carte de 1 700 échantillons se lit en quelques minutes la première fois, puis en quelques secondes.
- Elle s'**interrompt** sans dommage : [Arrêter], sur le tableau de bord, garde ce qui est déjà lu.
- Au démarrage, l'application relit d'elle-même ce qui a changé depuis la dernière fois (une fraction de seconde) : la case [Mettre l'index à jour au démarrage], dans les réglages.

Deux options, dans Réglages ▸ Analyse de la carte, décident de ce que l'analyse mesure :

| Option | Par défaut | Ce qu'elle apporte | Son coût |
|---|---|---|---|
| [Calculer les empreintes (détection des doublons)] | cochée | les doublons se reconnaissent à leur contenu, pas à leur nom | presque rien : trois petits blocs lus par fichier |
| [Analyse acoustique (tempo, tonalité, niveaux)] | décochée | tempo, tonalité, niveaux de chaque son : la recherche par ressemblance, le mixage harmonique, les contrôles d'écrêtage et de continu | nettement plus lent : une minute de plus pour 1 700 sons, la première fois |

!!! astuce Cochez l'analyse acoustique une fois
    Elle allonge la première lecture, puis les suivantes ne relisent que ce qui a changé. C'est elle qui fait vivre « Sons proches », la recherche par tonalité et la moitié des contrôles audio de la santé.

## Quand relancer l'analyse {#quand-analyser}

Les écritures de l'application mettent l'index à jour d'elles-mêmes, comme les fichiers reçus du Deluge. Relancez l'analyse quand la carte a changé **hors de l'application** : des fichiers copiés à la main sur une carte glissée dans le PC, par exemple. En cas de doute, elle ne coûte rien : ce qui n'a pas changé n'est pas relu.

[Réinitialiser l'index], dans les réglages, vide l'index pour le reconstruire à la prochaine analyse. La carte n'est pas touchée, et vos notes, favoris et étiquettes sont conservés.

# Premiers pas en dix minutes {#premiers-pas icone=play}

> Un parcours guidé, de la carte indiquée au premier morceau écrit pour le Deluge.

!!! atelier Votre première séance
    Gardez ce manuel ouvert à côté de l'application, et suivez les étapes dans l'ordre. Rien de ce qui suit ne modifie votre carte sans vous le demander.

1. **Indiquez la carte.** Si l'application vous a proposé une carte détectée, acceptez. Sinon, ouvrez [Réglages](app:Settings), puis désignez la racine de la carte — ou, si votre Deluge a le firmware 1.3, branchez-le et créez la copie de travail (voir [Créer la copie de travail](#creer-copie)).
2. **Lisez-la.** Cliquez [Analyser], en haut. La barre d'état montre l'avancement ; la première lecture prend quelques minutes sur une grosse carte.
3. **Regardez le tableau de bord.** Les tuiles disent ce que contient la carte ; l'anneau, sa note de santé. Le bandeau « À faire maintenant » propose la chose la plus utile du moment, avec le bouton qui la fait.
4. **Sauvegardez.** Si le bandeau le propose, suivez-le : [Sauvegarder] mène à l'onglet des sauvegardes de la page Santé, où [Sauvegarder maintenant] copie vos morceaux, presets et kits en moins d'une seconde.
5. **Écoutez un son.** Ouvrez [Échantillons](app:Samples), choisissez un dossier dans l'arbre, puis un son dans la liste : un clic l'écoute. [[Espace]] arrête.
6. **Fabriquez un preset.** Ouvrez le [Générateur](app:Generator), choisissez un genre — Techno, par exemple — et un rôle, Basse. [Générer], puis [Écouter]. Pas convaincu ? [Muter] le fait varier, [Produire 8 variantes] en propose huit cousins.
7. **Gardez-le.** [Enregistrer dans SYNTHS] demande un nom et un dossier, puis l'écrit sur la carte.
8. **Essayez-le en situation.** [Essayer en morceau] écrit dans `SONGS` un morceau neuf où votre son joue une phrase faite pour son rôle, sur la batterie du genre. Chargez-le sur le Deluge et appuyez sur PLAY.
9. **Branchez le Deluge.** Câble USB, et la pastille « Deluge » de la barre du haut passe à l'or puis au vert. Le chapitre [Brancher le Deluge](#brancher) dit les deux réglages à faire une fois sur la machine.

!!! astuce F1, partout
    Sur n'importe quelle page, [[F1]] ouvre ce manuel au chapitre qui la décrit.

@partie pages PAD_YELLOW | Les dix pages | Une page par domaine, chacune à la couleur de son pad

# Tableau de bord {#tableau-de-bord page=Dashboard}

> L'état de la carte en un écran : ce qu'elle contient, sa santé, et la prochaine chose à faire.

Le tableau de bord est la page d'accueil. Il se lit de haut en bas : d'abord ce qui demande votre attention, puis le contenu, puis les détails.

## À faire maintenant {#a-faire}

Le bandeau du haut ne donne **qu'une** suggestion — la plus utile à cet instant — et le bouton qui l'exécute ou qui mène à l'endroit exact. Son pad prend la couleur de la page où il mène. L'ordre suit le risque, pas les fonctions :

| Situation | Suggestion | Bouton |
|---|---|---|
| la carte n'a jamais été lue | l'analyser | [Analyser la carte] |
| aucune sauvegarde de la carte | sauvegarder, avant toute correction | [Sauvegarder] |
| la sauvegarde n'a pas encore ce que le Deluge a enregistré | la mettre à jour | [Mettre à jour la sauvegarde] |
| des presets réclament des échantillons absents | les retrouver | [Les retrouver] |
| des fichiers en double | les voir | [Voir les doublons] |
| plus de 200 échantillons inutilisés | les ranger | [Les ranger] |
| rien à signaler | fabriquer un son | [Générer un preset] |

## Le Deluge et le PC {#deluge-et-pc}

Ce panneau dit où en est le lien avec la machine, ce qui attend de partir vers elle, et ce qui en est arrivé. Son pad change de couleur :

| Pad | Signification |
|---|---|
| vert | le Deluge est branché, et sa carte s'ouvre par le câble USB |
| or | le Deluge est branché, mais sa carte ne s'ouvre pas par USB : il faut le firmware 1.3 |
| ambre | synchronisation en cours |
| gris | le Deluge est débranché ; ou bien la sauvegarde est ouverte, en lecture seule |
| cyan | la carte est ouverte directement, dans un lecteur du PC |

Ses commandes : [Synchroniser], pour échanger tout de suite avec le Deluge ; [Envoyer des fichiers…], pour choisir des sons ou des presets du PC à poser sur la carte ; et, quand la sauvegarde est ouverte, [Carte du Deluge…], qui mène aux réglages. La liste **Reçu du Deluge** montre les six derniers morceaux, presets, kits ou sons arrivés de la machine : un clic ouvre chacun sur sa page, sélectionné. Si votre sauvegarde a du retard sur la carte, une ligne le dit, avec [Mettre à jour la sauvegarde].

Le cadre en pointillé le rappelle : des fichiers glissés n'importe où sur la fenêtre partent sur le Deluge (voir [Échanger des fichiers](#echanges)).

## Contenu de la carte {#contenu}

Six tuiles : **Échantillons**, **Presets de synthé**, **Kits**, **Morceaux** — un clic ouvre la page correspondante —, la **durée d'audio** totale des échantillons, et l'**espace libre**. Sur un dossier plutôt qu'une carte, cette dernière tuile dit « Libre sur le disque » : ce sont les chiffres du disque de l'ordinateur.

## Carte {#carte}

Le chemin de la carte, une jauge de remplissage, l'espace occupé dont celui des échantillons, et la date de la dernière analyse. Tant que la carte n'a jamais été lue, le bouton [Analyser la carte] s'y affiche ; pendant une analyse, [Arrêter] l'interrompt sans rien perdre de ce qui est lu.

## État de santé {#etat-sante}

La note de santé dans son anneau, l'appréciation d'ensemble, et les trois anomalies les plus graves. **Chaque anomalie est un lien** : un clic mène à l'onglet de la page Santé qui la répare. [Voir le détail] ouvre le diagnostic complet. Tant que la carte n'a pas été analysée, aucune note n'est affichée : annoncer une carte en bon état sans l'avoir lue serait un mensonge.

## Actions rapides {#actions-rapides}

Six raccourcis, chacun à la couleur de sa destination, qui mènent **à l'onglet exact** : [Générer un preset], [Construire un kit], [Chercher les doublons], [Échantillons manquants], [Sauvegarder la carte] et [Boîte à outils].

## Répartition des échantillons {#repartition}

Les dix dossiers qui contiennent le plus d'échantillons, regroupés au deuxième niveau (`SAMPLES/DRUMS` plutôt que chacun de ses sous-dossiers), chacun avec une rangée de pads qui se lit comme un niveau sur la machine.

# Échantillons {#echantillons page=Samples}

> Toute la bibliothèque de sons : parcourir, écouter, filtrer, traiter, découper, et retrouver un son par ressemblance.

[[figure echantillons | Le plan de la page Échantillons. | Actions ; écouter, traiter, découper, sons proches, envoyer ; Filtres ; recherche, catégorie, durée, inutilisés, favoris, manquants ; Dossiers ; l'arbre de la carte, un clic filtre la liste ; La liste ; un clic choisit, glisser vers le PC copie ; L'aperçu ; forme d'onde, format, note, favori, usages]]

## La liste {#liste-echantillons}

Chaque ligne est un échantillon de la carte. Les colonnes, dans l'ordre de leur importance — sur une fenêtre étroite, les dernières s'effacent :

| Colonne | Contenu |
|---|---|
| Nom | le nom du fichier |
| Dossier | le dernier dossier du chemin (« Kick » plutôt que le chemin entier) |
| Catégorie | déduite du dossier ; une pastille de couleur la repère |
| Durée | la longueur du son |
| Tonalité | détectée par l'analyse acoustique |
| Format | **vide quand tout est normal** (44,1 kHz, 16 bits, mono) ; sinon ce qui sort de l'ordinaire : « 48 k », « 24 b », « stéréo » |
| Taille | le poids du fichier |
| Usages | combien de presets, kits ou morceaux s'en servent |

Un clic sur un en-tête trie la colonne. Un clic sur une ligne choisit le son et l'affiche dans l'aperçu ; [[Ctrl]] ou [[Maj]] en choisissent plusieurs. Le compte des sons affichés est écrit sous la liste.

## Chercher et filtrer {#filtres}

- Le champ « Rechercher un échantillon… » filtre sur le nom ; la recherche part seule après une courte pause.
- [Toutes catégories] ne garde qu'une catégorie ; chacune dit combien elle compte de sons.
- [Toutes durées] isole les sons par longueur : très courts (moins d'une demi-seconde), courts, moyens, longs (plus de dix secondes).
- [Inutilisés] ne montre que les sons qu'aucun preset, kit ni morceau ne cite.
- [Favoris] ne montre que les sons marqués comme favoris.
- [Manquants] ne montre que les fichiers réclamés par un preset mais absents de la carte.

## L'arbre des dossiers {#arbre}

À gauche, l'arborescence des échantillons, avec le nombre de sons de chaque dossier. Un clic sur un dossier limite la liste à son contenu ; le dossier choisi est aussi celui où partent les sons que vous envoyez au Deluge depuis cette page.

## L'aperçu {#apercu}

En bas : le nom et le chemin du son, sa **forme d'onde**, et une fiche — durée, format complet, taille, et, si l'analyse acoustique a tourné, tempo, tonalité et catégorie. À droite :

- la **Note**, de une à cinq étoiles ;
- la case [Favori], que le filtre [Favoris] utilise ;
- ses **étiquettes**, s'il en a — la croix d'une étiquette la retire ;
- combien de fichiers de la carte l'utilisent.

!!! retenir Notes et favoris restent sur l'ordinateur
    Ils sont gardés dans l'index de l'application, pas sur la carte : le Deluge ne les voit pas, et une réinitialisation de l'index les conserve.

## Écouter {#ecouter-echantillon}

[Écouter] joue le son choisi ; [Arrêter] coupe. Par défaut, **un simple clic dans la liste** suffit à écouter : la case [Écouter automatiquement l'échantillon sélectionné], dans Réglages ▸ Écoute, en décide. [[Espace]] arrête ou relance l'écoute depuis n'importe où, et un clic sur la forme d'onde rejoue le son depuis le début. Le volume d'écoute se règle dans les réglages ; il n'a aucun effet sur le Deluge.

[Dans l'explorateur] ouvre le dossier du son dans l'Explorateur Windows, sans rien modifier.

## Traiter… {#traiter}

[Traiter…] applique un ou plusieurs traitements à **tous les sons sélectionnés**. Une fenêtre propose :

| Traitement | Effet |
|---|---|
| [Mélanger en mono] | un seul canal : la taille est divisée par deux, la longueur ne change pas |
| [Retirer la composante continue] | recentre la forme d'onde sur zéro |
| [Normaliser la crête à] | monte ou baisse le niveau pour que la crête atteigne la valeur choisie (−1 dBFS par défaut) |
| [Couper le silence sous] | retire le silence au début et à la fin, sous le seuil choisi (−60 dB par défaut) |
| [Fondus d'entrée et de sortie de] | de courts fondus, pour éviter les clics (5 ms par défaut) |
| [Rééchantillonner à] | convertit à 44 100, 48 000, 32 000 ou 22 050 Hz |

[Simuler] ne traite rien : il calcule le **plan**, fichier par fichier, et l'affiche. Rien n'est écrit avant que vous l'acceptiez. Le traitement part ensuite en arrière-plan.

!!! attention Ce qui change la longueur d'un son
    Le rééchantillonnage et la coupe du silence changent la longueur des fichiers. Les presets qui bornent ce son en nombre d'échantillons sont **recalés dans la même opération**. Mais un morceau n'est jamais réécrit : les sons qu'un morceau utilise sont donc **écartés** de ces deux traitements, et le plan dit pourquoi.

Les originaux sont mis de côté dans le dossier `_BACKUP` à la racine de la carte, à l'octet près. Sur la copie de travail, ce dossier reste sur l'ordinateur et ne part pas sur le Deluge.

!!! pro L'écrêtage ne se répare pas
    Baisser le niveau d'un son écrêté rend de la marge pour le mixage ; les sommets rabotés à l'enregistrement, eux, ne reviennent pas.

## Découper… {#decouper}

Un break, une boucle de batterie, une phrase : [Découper…] en fait un **kit où chaque pad joue une tranche**. Choisissez **un seul** son, puis cliquez.

[[figure boucle | Une boucle découpée : les coupes sur la forme d'onde, un pad par tranche. | les coupes, posées sur les attaques ; un pad par tranche, sur le même fichier ; Aucun fichier audio n'est dupliqué : chaque rangée du kit joue une portion de la boucle.]]

La fenêtre montre la forme d'onde avec ses coupes numérotées, et règle leur placement :

- [Sur les attaques] pose les coupes là où le son frappe. Le curseur **Sensibilité** en trouve plus ou moins ; la case [Aligner sur le tempo] ramène les coupes sur la grille, pour qu'un break rejoué reste en place.
- [En divisions égales] coupe en parts égales — ce qui suffit pour une boucle bien coupée : quatre secondes à 120 BPM donnent seize tranches d'une double-croche.
- **Tranches** fixe leur nombre, jusqu'à 32 (16 par défaut).

Le tableau donne le début, la durée et la longueur de chaque tranche. Un clic sur une ligne, ou sur la forme d'onde, **écoute la tranche** ; [Écouter] la rejoue.

Trois façons de conclure :

- [Écrire le kit] écrit un kit dans `KITS` : chaque rangée joue sa portion du **même fichier**. Rien n'est dupliqué, et rien n'occupe plus de place.
- [Exporter en fichiers…] écrit chaque tranche dans son propre fichier, dans un dossier `SAMPLES/… TRANCHES`. Ce n'est pas nécessaire pour jouer le découpage sur le Deluge, et cela double la place occupée : la fenêtre le rappelle avant d'écrire.
- [Écrire en morceau] écrit dans `SONGS` un morceau neuf : le kit des tranches, et un clip qui rejoue la boucle tranche par tranche, chacune à sa place.

[Fermer] quitte sans rien écrire.

## Sons proches {#sons-proches}

Sur des milliers d'échantillons, le nom et le dossier ne suffisent plus. Choisissez un son, cliquez [Sons proches] : la liste ne montre plus que ce qui lui **ressemble**, du plus proche au plus lointain, avec une colonne **Proximité** en pour cent. Le bouton devient [Toute la liste], qui ramène la liste entière.

La comparaison porte sur huit mesures faites par l'analyse acoustique : brillance, contenu grave et aigu, étalement du spectre, caractère bruité, rapport crête sur moyenne, temps d'attaque. Les voisins viennent souvent d'un autre dossier, et c'est voulu : un kick trouve des toms, une caisse claire trouve des rimshots. C'est ce qui se ressemble à l'oreille, pas ce qui est rangé ensemble.

!!! attention Il faut l'analyse acoustique
    Un son sans mesures acoustiques ne peut pas être comparé : l'application le dit. Cochez « Analyse acoustique » dans les réglages, puis relancez l'analyse.

## Du PC au Deluge, et retour {#envoyer-depuis-echantillons}

[Envoyer au Deluge…] choisit des fichiers sur l'ordinateur et les pose sur la carte, **dans le dossier choisi dans l'arbre**. Le plan est montré avant toute copie (voir [Échanger des fichiers](#echanges)).

Dans l'autre sens, **glissez des lignes de la liste** vers l'Explorateur ou votre logiciel de musique : ils en reçoivent une copie. La carte n'est pas touchée.

# Presets {#presets page=Synths}

> Les presets de synthé de la carte : les parcourir, les écouter, et comprendre ce qui fait leur son.

## La liste {#liste-presets}

Chaque ligne est un preset du dossier `SYNTHS` : son **nom**, son **dossier**, sa **catégorie** (déduite de son dossier et de son contenu, avec sa pastille de couleur), son **moteur** de synthèse et sa **taille**. Le champ « Rechercher un preset… » filtre sur le nom, [Toutes catégories] sur la catégorie. Le compte est écrit sous la liste.

## Vue d'ensemble {#vue-ensemble}

Le premier onglet du panneau de droite décrit le preset choisi :

- une **description** en une phrase, puis une fiche : moteur, polyphonie, les deux oscillateurs, le filtre, les effets, l'unisson, l'arpégiateur, la catégorie devinée, le caractère du son, la version du firmware qui l'a écrit — et, s'il y en a eu, les **réparations faites à la lecture** d'un fichier abîmé ;
- la **forme d'onde** de l'échantillon choisi dans la liste « Échantillons utilisés » ;
- le **spectre** du son, qui apparaît après une écoute ;
- **Échantillons utilisés** : chaque fichier que le preset lit, et s'il est présent — « oui », ou « ABSENT » en rouge.

## Paramètres et Modulations {#parametres}

[Paramètres] montre les principaux réglages en encodeurs, de 0 à 50 comme sur l'écran du Deluge (le panoramique de −25 à +25) : volume, coupure et résonance du filtre, niveau des deux oscillateurs, réverbération, délai, effet de modulation. Dessous, les deux **enveloppes** et la **courbe du filtre**. Ces encodeurs se lisent ; ils ne se tournent pas.

[Modulations] liste les **câbles de modulation** — source, destination, profondeur — et les **encodeurs assignés** du preset (ses `modKnobs`).

## Écouter un preset {#ecouter-preset}

[Écouter] fait jouer le preset. L'ordinateur calcule une **approximation** du son avec son propre moteur : fidèle dans l'esprit, pas au détail près. Si le Deluge est branché et que la case « Écouter les presets sur le Deluge » est cochée dans les réglages, c'est **la machine** qui joue : l'instrument sélectionné sur elle prend les filtres, enveloppes et effets du preset, avec ses propres oscillateurs (voir [Écouter sur la machine](#ecouter-sur-la-machine)). [Arrêter] coupe.

## Dupliquer, varier {#dupliquer}

- [Dupliquer] enregistre une copie du preset **à côté de l'original**, sous le nom « … copie », après confirmation. L'original n'est pas touché.
- [Varier dans le générateur] ouvre le preset dans le [Générateur](app:Generator), comme point de départ : [Muter] ou [Produire 8 variantes] en tirent des cousins. L'original n'est jamais réécrit.

# Kits {#kits page=Kits}

> Les kits de batterie rangée par rangée : ce que joue chaque pad, et surtout ce qui ne joue plus.

## La liste et le détail {#liste-kits}

À gauche, les kits de la carte : nom, dossier, nombre de rangées, taille ; le champ « Rechercher un kit… » filtre sur le nom. À droite, le kit choisi : une phrase résume son état — « 16 rangée(s), toutes jouables », ou combien n'ont pas d'échantillon jouable.

Le tableau **Rangées** donne, pour chaque rangée : son nom, son échantillon, s'il est **présent** (« oui », « ABSENT », ou « vide » pour une rangée sans son), son volume, son decay et sa polyphonie.

!!! retenir Le Deluge ne prévient pas
    Une rangée dont l'échantillon a disparu reste muette sur la machine, sans message. C'est ici qu'on la voit — et la page [Santé](app:Health#Manquants) sait lui trouver un remplaçant.

## Écouter {#ecouter-kit}

- [Écouter la rangée] joue l'échantillon de la rangée choisie. Avec l'écoute automatique, un clic sur la rangée suffit.
- [Écouter le kit] joue le **motif d'essai** avec les sons du kit, à 128 BPM. Si le Deluge est branché et l'écoute réglée sur lui, le motif part **sur la machine** : les rangées y répondent à partir de la note 36 (C1).
- [Arrêter] coupe.

## Le motif d'essai {#motif-essai}

Sous le tableau, une grille de pas : une ligne par rangée, seize pas par mesure. [Motif de départ] y charge le rythme typique d'un genre, **limité aux rangées que le kit possède** (KICK, SNARE, HAT…). Cliquez les pads pour ajouter ou retirer des coups. Un kit mélodique, sans nom de batterie, part d'une grille vide sur ses premières rangées : la page le dit.

- [Motif en MIDI] écrit le motif dans un fichier `.mid`, à l'endroit choisi, hors de la carte.
- [Motif en morceau] écrit dans `SONGS` un morceau neuf : ce kit, tel qu'il est sur la carte, et un clip qui joue le motif (voir [Écrire des morceaux pour le Deluge](#morceaux-pour-le-deluge)).

# Morceaux {#morceaux page=Songs}

> Ce que contient chaque morceau, ce dont il dépend, et ce qui lui manque — en lecture seule.

!!! retenir Une page qui ne modifie jamais un morceau
    Un preset se regénère, un échantillon se retélécharge ; un morceau est du travail. Rien sur cette page n'écrit dans un fichier de morceau. Ses exports écrivent **ailleurs**, à l'endroit que vous choisissez.

## La liste et la fiche {#liste-morceaux}

À gauche, les morceaux : nom, tempo, nombre de clips, de notes, de mesures ; le champ « Rechercher un morceau… » filtre sur le nom. À droite, le morceau choisi : une **vignette** en couleurs, celle de la vue Morceau de la machine, et une fiche — tempo, gamme, clips de session et d'arrangement, notes, plus long clip, sections, instruments, densité en notes par mesure, swing, firmware.

## Clips, Instruments, Échantillons {#onglets-morceaux}

| Onglet | Ce qu'il liste |
|---|---|
| [Clips] | chaque clip : son nom, son preset, sa longueur en mesures, son nombre de notes, sa section |
| [Instruments] | chaque instrument — synthé, kit, MIDI, CV, audio —, son nom, son dossier, et s'il est **présent** sur la carte |
| [Échantillons] | chaque fichier audio dont le morceau dépend, et s'il est présent |

Un preset ou un échantillon marqué « ABSENT » rendra le morceau muet par endroits sur la machine.

## Exporter {#exporter-morceau}

- [Clip en MIDI] écrit le clip choisi dans l'onglet Clips en fichier `.mid`.
- [Morceau en MIDI] écrit tout le morceau dans un seul fichier MIDI, **une piste par clip**, la batterie sur le canal des percussions. Toutes les pistes démarrent au début : les clips du Deluge sont des boucles de la grille de session, et le fichier ne sait pas quand chacune se déclenche.
- [Rassembler…] copie dans un dossier de votre choix le morceau, **les presets qu'il nomme et les échantillons qu'ils lisent**, avec leur arborescence d'origine. Le dossier obtenu a la forme d'une carte : recopié à la racine d'une autre, le morceau y joue tel quel. La liste complète s'affiche avant la première copie, et ce qui manque est signalé.
- [Rapport HTML] enregistre une fiche du morceau en page web : chiffres, clips, instruments, échantillons manquants.
- [Dans l'explorateur] ouvre le dossier du morceau.

!!! pro Archiver un morceau fini
    [Rassembler…] est la bonne façon de mettre un morceau à l'abri ou de le donner : rien n'est oublié, pas même l'échantillon rangé ailleurs qu'un preset réclame.

# Générateur {#generateur page=Generator}

> Fabriquer des presets de synthé et des kits de batterie, par genre musical ou au hasard, les écouter, puis garder ceux qui plaisent.

[[figure generateur | Le plan de l'onglet « Preset de synthé ». | Actions ; générer, au hasard, muter, écouter, enregistrer ; Réglages ; genre, rôle, moteur, graine, six curseurs ; Le son ; description, forme d'onde, spectre, réglages ; Variations ; huit variantes, l'historique, le fondu]]

La page a deux onglets : [Preset de synthé] et [Kit de batterie].

## Choisir un genre et un rôle {#genre-role}

À gauche, **vingt-deux genres**, chacun un pad à sa couleur : Acid, Ambient, Berlin school, Boards of Canada, Deep house, Detroit, Downtempo, Drum and bass, Dubstep, Electro, Funk, Hardcore, House, IDM, Industrial, Jungle, Lo-fi, Minimal, Psytrance, Synthwave, Techno, Trance. L'infobulle de chacun décrit son caractère et sa plage de tempo.

Dessous :

- **Rôle** — ce que le son doit faire dans un morceau : Basse, Lead, Nappe, Pincé, Clavier, Accord bref, Effet, Bourdon, Arpège, Cloche. Une basse ne se règle pas comme une nappe.
- **Moteur** — [Choisi par le genre], qui donne les sons les plus typés, ou Soustractive, FM, Ring mod.
- **Graine** — le nombre qui rend un son reproductible : deux générations avec la même graine et les mêmes réglages donnent **exactement** le même son. Le dé en tire une nouvelle.

**Six curseurs** orientent le résultat : **Brillance** (le filtre), **Mouvement** (LFO et enveloppe de modulation), **Espace** (réverbération et délai), **Saleté** (distorsion, résonance, réduction numérique), **Largeur** (unisson, désaccord, chorus) et **Complexité** (le nombre de modulations).

## Générer et écouter {#generer}

- [Générer] fabrique un preset complet à partir du genre, du rôle, des curseurs et de la graine. Rien n'est encore écrit sur la carte.
- [Au hasard] tire un genre, un rôle et une graine, puis génère.
- [Muter] repart du son actuel et en change quelques réglages : de quoi explorer autour d'une idée qui plaît.
- [Écouter] joue le son — calculé par l'ordinateur, ou par le Deluge s'il est branché et l'écoute réglée sur lui.
- [Modifier le son…] ouvre l'éditeur du son courant : chaque réglage à la main, au cran de la machine et en clair (voir [Modifier un son à la main](#atelier-modifier-son)). Le son retouché rejoint l'historique.

Au centre, le son obtenu : son nom et sa description, sa forme d'onde et son spectre, ses **réglages obtenus** en encodeurs, son enveloppe d'amplitude et sa courbe de filtre.

!!! retenir Un preset généré fait du son
    Un oscillateur muet, un filtre fermé, une enveloppe sans attaque ni tenue sont rattrapés avant l'écriture.

!!! retenir L'écoute de l'ordinateur suit les lois du Deluge
    Durées d'enveloppe, coupures du filtre, vitesses des LFO, volumes, glissé et modulations se calculent comme dans le firmware de la machine : un decay de 13 dure 1,8 seconde ici comme sur le Deluge. Le timbre exact du filtre et des effets reste approché ; pour l'entendre tel quel, essayez le son sur la machine avec [Essayer en morceau].

## Variations, historique, fondu {#variations}

À droite :

- [Produire 8 variantes] crée huit cousins du son actuel. **Un clic** sur une variante l'écoute, **un double-clic** l'adopte.
- **Historique** : chaque son généré s'y empile ; un double-clic le rappelle.
- **Fondre** : choisissez un son dans l'historique, réglez le curseur — à gauche le son courant, à droite le son choisi — puis cliquez [Fondre]. Les réglages continus se mélangent selon le dosage ; les choix tranchés, comme les formes d'onde, basculent à mi-chemin.
- [Générer un lot dans un dossier…] fabrique d'un coup jusqu'à 64 presets du genre choisi et les écrit dans un sous-dossier de `SYNTHS`.

## Garder un son {#enregistrer-preset}

[Enregistrer dans SYNTHS] demande un **nom** — assaini pour la carte — puis un **sous-dossier** de `SYNTHS` (« Generes » par défaut ; vide, la racine de `SYNTHS`). Si un fichier porte déjà ce nom, l'application demande avant de le remplacer — et, avec le garde-fou des réglages, garde une copie `.bak` de l'ancien.

[Essayer en morceau] écrit dans `SONGS` un morceau neuf où le son joue une phrase faite pour son rôle — basse, accords, arpège, mélodie — sur une progression et la batterie du genre : de quoi l'entendre **en situation** sur la machine.

## Construire un kit {#construire-kit}

L'onglet [Kit de batterie] assemble un kit **à partir de vos échantillons**. Le kit se construit autour d'une machine ou d'une banque de votre bibliothèque — une 909, une Linndrum, un kit d'artiste —, choisie selon le genre ; les rôles qu'elle n'a pas sont complétés ailleurs. Chaque rangée est réglée comme le Deluge la crée : l'échantillon joué jusqu'au bout et sensible à la vélocité ; volume et panoramique suivent les kits de la carte, toms en éventail.

- **Genre** oriente le choix des sons : une grosse caisse techno ne ressemble pas à une grosse caisse funk.
- **Nom du kit** est le nom du fichier qui sera écrit dans `KITS`.
- **Graine** : même graine, même kit.
- **Dossier à privilégier**, facultatif, limite la recherche à un dossier de la carte, par exemple `SAMPLES/Artists/…`.

[Construire le kit] l'assemble — rien n'est encore écrit. [Écouter] le joue. Une rangée ne vous plaît pas ? Choisissez-la dans la liste, puis [Autre son] : un autre son du même rôle la remplace, de la même machine d'abord, d'une machine voisine ensuite. [Enregistrer dans KITS] l'écrit dans `KITS`, sous le nom du kit ; si ce nom est déjà pris, l'application demande avant de remplacer le fichier. [Kit en morceau] écrit un morceau neuf : ce kit et un clip qui joue le rythme de son genre.

!!! attention Le kit puise dans l'index
    Sans analyse de la carte, le générateur de kits ne trouve aucun échantillon. Lancez [Analyser] d'abord.

# Atelier {#atelier page=Atelier}

> Composer un morceau du premier son à l'arrangement : un style, des sons, des clips et leurs variations, des sections — puis l'écrire pour le Deluge, ou compléter un morceau commencé sur la machine.

[[figure atelier | Les quatre onglets de l'atelier, la grille des sections, et les trois chemins vers le Deluge. | Style ; le genre, la tonalité, le tempo, le caractère des sons et les parties ; Sons ; un son par piste, et huit variantes dans le style ; Clips ; des clips et leurs variations, sur la progression du morceau ; Morceau ; les sections, et le clip que chaque piste y joue ; La grille des sections ; une rangée par piste, une colonne par section, une lettre par clip — une case éteinte se tait ; Jouer sur le Deluge ; en direct, dans le clip que suit MIDI Follow, calé sur sa mesure ; Écrire le morceau ; un morceau neuf dans SONGS, sections et arrangement compris ; Compléter le morceau ; une nouvelle version du vôtre, l'original intact]]

La page suit l'ordre du travail, en quatre onglets : Style, Sons, Clips et Morceau. Les quatre boutons de l'en-tête la pilotent : [Composer] fabrique un morceau neuf, [Partir d'un morceau…] ouvre un des vôtres, [Écrire le morceau] et [Compléter le morceau] l'écrivent sur la carte. Jusque-là, **rien n'est écrit** : l'atelier compose même sans carte, et ne la demande que pour écrire, ou pour bâtir un kit avec vos échantillons.

## Le style {#atelier-style}

À gauche, les vingt-deux **genres** du générateur, un pad chacun ; l'infobulle décrit le caractère du genre et sa plage de tempo. En choisir un place le tempo au milieu de cette plage.

- **Tonique** et **Gamme** — accords, basse et mélodie restent dans la gamme ; le morceau écrit la donne au mode gamme du Deluge.
- **Tempo**, en BPM.
- **Ambiance** — celle de la progression d'accords : mélancolique, house, jazz… Par défaut, celle du genre.
- **Couleur** — triades, septièmes, neuvièmes ou accords suspendus. Par défaut, ce que l'ambiance appelle.
- **Graine** — même graine et mêmes réglages, même morceau ; le dé en tire une nouvelle.

**Caractère des sons** reprend les six curseurs du générateur — Brillance, Mouvement, Espace, Saleté, Largeur, Complexité —, mais pour **tous** les synthés du morceau à la fois : c'est ce qui les fait sonner ensemble.

**Les pistes** dit quelles parties le morceau contient : [Batterie], [Basse], [Accords], [Arpège], [Mélodie]. Pour chacune, la liste à côté dit où elle joue :

| Nature | Où joue la partie |
|---|---|
| Kit | un kit du Deluge, bâti avec vos échantillons — c'est la batterie |
| Synthé | un synthé du Deluge, dont le son est généré dans le style |
| MIDI | un appareil extérieur, que le Deluge pilote sur le canal choisi (1 à 16) |
| CV | un synthé modulaire, par la sortie CV choisie (1 ou 2) — une note à la fois |

[Composer] fabrique alors le projet : une piste par partie cochée, un son dans le style pour chacune, un premier clip, et la **structure du genre** — intro, montée, thème, cassure… — avec les variations qu'elle appelle : une batterie allégée pour l'intro, sans grosse caisse pour la cassure, ornée pour le sommet ; au second sommet, la mélodie répond à la première et la basse s'enrichit.

## Les sons {#atelier-sons}

À gauche, les pistes du projet, chacune à la couleur de sa partie ; à droite, le son de la piste choisie, son nom et sa description.

- [Écouter le son] le joue — sur le Deluge si l'écoute y est réglée, sinon en rendu approché ; une batterie joue son premier clip.
- [Autre son] en tire un autre du même style pour un synthé ; pour une batterie, un autre kit bâti dans votre bibliothèque.
- [Choisir sur la carte…] prend pour la piste un preset ou un kit de la carte, choisi dans l'index.
- Une piste MIDI ou CV montre son **canal**, qui se change ici.

**Variantes dans le style** : [Proposer 8 variantes] en propose huit du son de la piste. Chacune ne touche qu'**un** aspect : soit un aspect tiré à nouveau — le timbre, le filtre, les enveloppes, le mouvement, l'espace, la largeur, les modulations —, soit un curseur poussé — plus brillant, plus sombre, plus sale, plus large, plus d'espace… Le reste du son ne bouge pas, et rien ne sort du genre. Un clic écoute une variante ; un double-clic, ou [Adopter], la donne à la piste.

!!! retenir Plus sale, c'est le même son en plus sale
    Chaque décision du son — la coupure, la saturation, la forme des LFO — a son propre tirage. Pousser la saleté ne change donc que ce qui dépend d'elle : on obtient le même son, en plus sale, et non un autre son.

Sous la liste, deux menus et deux boutons ajoutent ou retirent une piste : la **nature** de la piste (kit, synthé, MIDI, CV), la **partie** qu'elle jouera, puis [Ajouter la piste] — avec un son dans le style et un premier clip — ou [Retirer], qui la retire aussi de toutes les sections.

## Modifier un son à la main {#atelier-modifier-son}

[Modifier le son…] ouvre l'éditeur du son de la piste choisie, un synthé neuf ; le son d'une piste du morceau d'origine lui appartient et ne se modifie pas ici. Le même éditeur s'ouvre depuis le [Générateur](#generer).

Ses sept onglets suivent les menus du Deluge : **Voix** (moteur, jeu, transposition, glissé, volume, panoramique, unisson), **Oscillateurs** (formes, accords, niveaux, largeur d'impulsion, bruit ; les modulateurs en FM), **Filtres** (passe-bas et passe-haut, avec leur courbe), **Enveloppes**, **LFO**, **Effets** (réverbération, délai, mod FX, saturation, réductions, égaliseur) et **Modulations**. Passer en FM éteint les filtres, comme sur la machine.

Chaque encodeur montre le cran que vous liriez sur la machine, de 0 à 50, et dessous **ce qu'il vaut sur le Deluge**, calculé par les lois de son firmware : « 1,8 s » pour un decay de 13, « 237 Hz » pour une coupure de 19. Un encodeur se règle en glissant vers le haut ou vers le bas, à la molette ou aux flèches du clavier ; Maj affine le geste, un double-clic le ramène au milieu. Les enveloppes se tirent aussi à la souris, sur leur courbe.

Dans **Modulations**, chaque ligne relie une source à un réglage, avec une profondeur de −50 à +50 et une polarité ; à côté, ce que fait la modulation : « ±4,0 octave(s) », « ±0,34 demi-ton ». [Ajouter une modulation] en crée une, [Retirer] l'enlève.

!!! retenir Au repos, une enveloppe tire le réglage vers le bas
    Sans polarité, une source va de −1 à +1 : une enveloppe vaut −1 au repos et tire la coupure sous son cran. Unipolaire, elle va de 0 à 1 et ne fait qu'ouvrir.

[Écouter] joue le son tel qu'il est réglé ; avec [Écouter en réglant], il se rejoue un instant après chaque geste. Sous les onglets, une ligne résume ce qui a changé. [Revenir au son de départ] oublie tout, [Annuler] ferme sans rien changer, [Garder ce son] donne le son à la piste. Rien n'est écrit sur la carte : le son le sera avec le morceau. La piste se dit alors retouchée à la main, et ses **variantes dans le style gardent vos retouches** : chacune change au son retouché ce qu'elle aurait changé au son généré. Un réglage que vous avez tourné l'est d'autant ; une forme d'onde ou un type de filtre que vous avez choisis restent, sauf si la variante a pour objet de les changer (« Autre timbre », « Autre filtre ») ; une modulation que vous avez ajoutée reste, une modulation retirée le reste. Une variante qui ne changerait plus rien — la coupure déjà au maximum pour « Plus brillant » — laisse sa place à la suivante.

## Les clips {#atelier-clips}

Une piste a ses clips, nommés A, B, C… : la liste dit d'où vient chacun — généré, variation d'un autre, ou repris du morceau d'origine — et sa longueur. Dessous, le clip lui-même : les rangées d'une batterie, de bas en haut, ou les notes d'un synthé sur leur hauteur. Une ligne dit combien il a de notes et dans quelles sections il joue.

- [Écouter le clip] le joue sur l'ordinateur, avec le son de sa piste.
- [Varier] ouvre le menu des variations ; la variation choisie s'**ajoute** à la piste comme un clip neuf, l'original reste.
- [Nouveau clip] en fabrique un autre, de la longueur choisie à côté (une, deux, quatre ou huit mesures), sur la progression du morceau.
- [Supprimer le clip] le retire ; les sections qui le jouaient se taisent pour cette piste.

| Pour un synthé | Pour une batterie |
|---|---|
| **rythme** — le même dessin, décalé : anticipations, notes répétées | **ornements** — notes fantômes, charleys, percussion ; l'ossature intacte |
| **notes** — le même rythme, d'autres notes : voisines, quinte, renversements | **remplissage** — un roulement sur la fin de la dernière mesure |
| **plus** — des notes de passage, des levées, des relances | **légère** — ni caisse claire ni clap, pour une intro ou une fin |
| **moins** — les temps forts seuls, tenus | **cassure** — sans grosse caisse : la tension retombe |
| **réponse** — la première moitié gardée, la seconde lui répond | **doublée** — des charleys deux fois plus serrés |
| **octave** — des sauts d'octave, ou le registre déplacé | **demi-temps** — la caisse claire sur le troisième temps |
| **fin** — la dernière mesure prépare le retour au début | **montée** — un roulement qui s'accélère jusqu'à la fin |

Une variation garde la tonalité et la progression : une note qui bouge reste dans la gamme, et la quinte d'une basse est celle de l'accord du moment.

## Jouer sur le Deluge {#atelier-direct}

[Jouer sur le Deluge] envoie le clip à la machine, en boucle, sur le canal réglé pour le Deluge — celui que suit [MIDI Follow](#midi-follow). Le Deluge le joue donc **dans le clip ouvert** sur la machine. Si elle est en lecture, le clip part au début de sa boucle suivante, calé sur son horloge ; à l'arrêt, il joue au tempo du morceau. Un nouveau clic sur le bouton l'arrête.

!!! attention En enregistrement, le clip s'inscrit
    Machine en enregistrement (REC), les notes entrent dans le clip ouvert, comme si vous les jouiez : ouvrez d'abord, sur le Deluge, le clip qui doit les recevoir. Rien d'autre n'est envoyé — ni réglage, ni fichier.

Le Deluge doit être branché et connecté ([Se connecter](#se-connecter)), et MIDI Follow réglé sur la machine ([Deux réglages sur la machine](#reglages-machine)).

## Le morceau {#atelier-morceau}

La grille montre le morceau entier : **une rangée par piste, une colonne par section**, et dans chaque case la lettre du clip que la piste y joue. Un clic sur une case fait jouer à la piste son clip suivant, puis le silence, puis à nouveau le premier. Un clic sur l'en-tête d'une section la choisit. Les clips repris d'un morceau de la carte ont un contour pointillé.

**La section choisie** se règle dessous : son **nom** — que ses clips portent sur le Deluge — et sa **durée** en mesures, sur laquelle ses clips bouclent.

- [Écouter la section] joue son début — huit mesures au plus —, toutes pistes ensemble ; [Arrêter] coupe l'écoute.
- [Ajouter une section] en ajoute une après celle choisie, avec les mêmes clips ; [Retirer la section] la retire.
- Les deux flèches la déplacent d'un cran dans le morceau.
- [Structure du genre] remplace les sections par celles du genre, avec leurs variations. Partant d'un de vos morceaux, ses sections restent, et celles du genre s'ajoutent après.

Une ligne résume le tout : le nombre de sections, de mesures, la durée et le tempo.

## Écrire le morceau {#atelier-ecrire}

[Écrire le morceau] en fait un morceau du Deluge, dans `SONGS` : une section du Deluge par section du projet, chacune avec ses clips et son nombre de répétitions, et l'arrangement complet pour la vue SONG. Les synthés y portent leur son ; la batterie, un kit bâti avec vos échantillons, ou celui que vous avez choisi sur la carte ; les pistes MIDI et CV, leur canal. Le parcours est celui de tout [morceau écrit](#parcours-morceau) : un nom, le plan, puis l'écriture d'un fichier neuf.

## Partir d'un morceau, et le compléter {#atelier-completer}

[Partir d'un morceau…] ouvre dans l'atelier un morceau de la carte — les derniers reçus du Deluge en tête de liste. Ses pistes, ses clips, son tempo et sa gamme deviennent ceux du projet ; sa progression d'accords est lue dans ses notes, pour que les clips neufs s'y accordent. Ses clips se varient comme les autres — une variation est toujours un clip neuf —, et l'on ajoute des pistes, des clips et des sections.

[Compléter le morceau] écrit alors une **nouvelle version** : « Cool1 5 » après « Cool1 4 ». Elle contient le morceau d'origine **octet pour octet**, plus ce que vous avez ajouté : les pistes neuves, leurs clips, et les sections neuves avec les leurs. Le plan détaille chaque ajout avant d'écrire. Le fichier écrit est relu aussitôt : si le morceau d'origine n'y est pas intact, rien n'est écrit.

!!! retenir Le morceau d'origine n'est jamais réécrit
    La nouvelle version est un fichier à côté de l'ancien ; chargez-la sur le Deluge comme tout morceau. Les sections existantes gardent leur durée et leurs clips ; elles reçoivent ceux des pistes neuves, et d'une piste qui n'y jouait rien. Une piste qui y a déjà son clip le garde : en disposition grille, le Deluge n'en montre qu'un par piste et par section. Placez le nouveau dans une section neuve — le plan signale chaque cas.

Le morceau doit venir d'un firmware 1.2 ou plus récent. Un morceau plus ancien, ou au format 2.x, est refusé : enregistrez-le une fois sur le Deluge, qui le convertit, puis recommencez. Les notes neuves sont écrites dans le format du morceau ; le Deluge connaît 24 sections au plus en firmware 1.3, 12 avant.

## Travailler en même temps que la machine {#atelier-simultane}

L'atelier et le Deluge travaillent sur le même morceau de deux façons, qui se complètent :

1. **En direct** — un clip fait dans l'atelier part sur la machine avec [Jouer sur le Deluge], calé sur sa mesure ; en enregistrement, il entre dans le clip ouvert. Le morceau grandit sur la machine elle-même.
2. **Par le fichier** — enregistrez le morceau sur le Deluge ; il arrive dans l'application par la [synchronisation](#carte-dans-le-deluge). Ouvrez-le avec [Partir d'un morceau…], composez, puis [Compléter le morceau] : la nouvelle version repart vers la carte, et se charge sur la machine.

# Boîte à outils {#boite-a-outils page=Toolbox}

> Les questions qu'on se pose en cours de morceau, et qu'on résout d'habitude avec une calculatrice et un carnet.

La page s'appelle « Outils » dans la colonne de gauche. Six onglets ; aucun n'a besoin de la carte, sauf la recherche par tonalité et les sons de batterie des écoutes.

## Théorie {#theorie}

**Gamme.** Choisissez une **Tonique** et une **Gamme** parmi vingt-sept — des modes classiques aux gammes du monde (hijaz, hirajoshi, in sen…). Le clavier surligne ses notes, la liste les nomme, et la ligne `<modeNotes>` donne la gamme telle que le Deluge l'écrit dans ses morceaux ; [Copier] la place dans le presse-papier.

**Accords de la gamme.** Le tableau donne chaque degré, son accord et ses notes ; un clic sur une ligne surligne l'accord sur le clavier.

**Progression.** Choisissez une **Ambiance** (pop, mélancolique, house, deep, techno, trance, ambient, jazz, blues, épique, tendu, lumineux), une **Couleur** — triades, septièmes, neuvièmes, accords suspendus, ou « selon l'ambiance » — et un nombre de **Mesures** (2 à 16), puis [Proposer]. La suite d'accords s'affiche dans la liste.

**L'accompagnement** pose cette progression dans le temps. **Genre** règle le rythme des accords, le style de basse, l'arpège, le tempo et les sons de l'écoute ; **Accords** et **Basse** peuvent forcer un style (accords tenus, en blanches, sur les contretemps, en stabs, en charleston ; basse sur la fondamentale, pulsée, sur les contretemps, roulante, en octaves, syncopée, en marche, acide). La ligne **Ajouter** coche les parties facultatives : [Arpège], [Mélodie], [Batterie].

- [Écouter] joue la progression et son accompagnement, sur des sons générés pour le genre ; [Arrêter] coupe. Rien n'est écrit.
- [Autre accord] remplace l'accord choisi dans la liste par un autre de même fonction ; le reste ne bouge pas.
- [Autre mélodie] tire une autre mélodie sur les mêmes accords, et la fait écouter.
- [En MIDI] écrit un fichier `.mid` : une piste par partie, chacune sur son canal, la batterie en piste 10.
- [En morceau] écrit dans `SONGS` un morceau neuf : un instrument et un clip par partie, avec les sons de l'écoute ; les clips bouclent ensemble dès qu'on appuie sur PLAY.

## Rythme {#rythme}

- **Genre** et **Mesures** (1 à 4), puis [Motif du genre] : un rythme typique s'affiche dans la grille.
- **Euclidien** : un nombre de **coups** répartis le plus régulièrement possible sur un nombre de **pas**, décalé par la **rotation** ; [Ajouter la piste] l'ajoute au motif en cours.
- **Groove** : swing d'échantillonneur en pourcentage (MPC 54 % à 71 %), jeu « laid-back » derrière le temps ou « en avant » ; le curseur **Swing** en ajoute librement. [Appliquer] part toujours du motif droit : un second clic ne cumule pas. Quand c'est possible, la barre d'état donne le réglage de swing équivalent sur le Deluge.
- [Variation] varie le motif sans toucher à son ossature : grosse caisse, caisse claire et clap restent.
- [Écouter] joue le motif deux fois, avec les échantillons de la carte quand elle en a, sinon une batterie synthétisée ; **BPM** règle le tempo. [Arrêter] coupe.
- [En MIDI] écrit le motif, percussions sur le canal 10 ; [En morceau] écrit un morceau neuf : un kit de vos échantillons et un clip qui joue le motif.

La grille se modifie au clic. Sous elle, le motif en texte, à recopier dans un carnet.

## Calculatrice {#calculatrice}

- **Tempo** : pour le BPM choisi, la durée d'une mesure, et un tableau des divisions — droites, pointées, en triolet — en millisecondes, avec la fréquence d'un LFO calé dessus. De quoi régler un délai ou un LFO à la main.
- **syncLevel du Deluge** : la correspondance entre la valeur écrite dans les fichiers et la division rythmique (7 = double-croche).
- **Mémoire et durée** : le poids d'un enregistrement selon sa durée, sa fréquence, sa résolution et ses canaux — et combien de minutes la place restante sur la carte permet d'enregistrer dans ce format.

## Mixage harmonique {#mixage-harmonique}

La **roue de Camelot** : chaque tonalité majeure, sa relative mineure, leurs codes et les tonalités compatibles. Deux morceaux s'enchaînent sans fausse note si leurs codes sont identiques, voisins d'un cran, ou s'ils échangent majeur et mineur relatif.

**Chercher dans la bibliothèque** : tapez une tonalité (Am, C, F#m), puis [Chercher] — la liste montre les échantillons de la carte dans cette tonalité ou une tonalité compatible, avec leur tempo. Il faut l'analyse acoustique.

## Arrangement {#arrangement}

Un **modèle de structure** par genre : intro, montée, thème, cassure, final… Le tableau donne chaque section, sa longueur en mesures, sa durée, sa position, et les **parties** qu'elle fait jouer ; le total s'affiche en minutes au tempo choisi.

L'esquisse reprend la progression de l'onglet Théorie s'il y en a une, et le rythme de l'onglet Rythme s'il est du même genre ; sinon, ceux du genre. Une phrase sous le tableau dit ce qu'elle utilise.

- [Écouter la section] joue le début de la section choisie — huit mesures au plus —, avec les seules parties de son rôle.
- [Esquisse en MIDI] écrit le morceau entier en fichier MIDI, une piste par partie, le nom des sections en repères.
- [Esquisse en morceau] écrit dans `SONGS` un morceau **à sections** : chaque section du modèle devient une section du Deluge, avec ses clips et son nombre de répétitions.

## Aide-mémoire {#aide-memoire}

Les valeurs du Deluge qu'on oublie toujours : résolution rythmique, échelle des paramètres et des câbles de modulation, format des notes, conditions de probabilité, gammes, `syncLevel`, arpégiateur, rangées de kit, règles des noms de fichiers, firmware, dossiers attendus, fréquence d'échantillonnage.

!!! astuce Le tempo du Deluge
    Quand le Deluge branché joue, son horloge peut donner le tempo des écoutes, des fichiers MIDI et des morceaux de cette page : la case [Les outils suivent le tempo du Deluge], dans les réglages, cochée par défaut.

# Santé de la carte {#sante page=Health}

> Ce qui va mal sur la carte, et comment le réparer — toujours en montrant le plan d'abord.

## Diagnostiquer {#diagnostiquer}

[Diagnostiquer] cherche les anomalies dans l'index déjà constitué : il **ne relit pas la carte** et prend moins d'une seconde. Il part de lui-même à la première visite. Le diagnostic n'a de sens qu'après une analyse : sans index, il n'y a rien à juger.

Le résultat s'affiche dans l'onglet [Rapport] : la **note sur 100**, une appréciation, la liste des **anomalies** classées par gravité, et le **détail** de celle que vous choisissez — ce qu'elle signifie, les fichiers concernés, et comment la corriger.

[[figure sante | La note de santé, et ce que dit sa couleur sur le tableau de bord. | 90 et plus ; carte en très bon état ; 70 à 89 ; quelques points à surveiller ; 40 à 69 ; une carte à nettoyer ; moins de 40 ; à remettre en ordre]]

La note part de 100 et perd **5 points par sorte d'erreur** et **2 par sorte d'avertissement** : elle compte les catégories de défauts, pas les fichiers. Trois cents fichiers parasites sont un seul problème à régler, pas trois cents.

## Ce que le diagnostic sait trouver {#controles}

| Anomalie | Gravité | Correction automatique |
|---|---|---|
| Dossiers standards absents | erreur | oui : les créer |
| Plusieurs fichiers de firmware à la racine | erreur | — |
| Échantillons référencés mais absents | erreur | oui : relier au remplaçant de même nom |
| Fichiers XML illisibles | erreur | — |
| Espace libre faible | avertissement | — |
| Échantillons en double | avertissement | oui : n'en garder qu'un |
| Fichiers XML réparés à la lecture | avertissement | — |
| Noms de fichiers problématiques | avertissement | oui : renommer |
| Chemins trop longs (plus de 200 caractères) | avertissement | — |
| Échantillons écrêtés | avertissement | oui : rendre de la marge |
| Composante continue | avertissement | oui : la retirer |
| Échantillons muets | avertissement | — |
| Fichiers parasites (`._*`, `.DS_Store`, `Thumbs.db`…) | avertissement | oui : les supprimer |
| Aucune sauvegarde | avertissement | — |
| Échantillons jamais utilisés | information | oui : les archiver dans `_UNUSED` |
| Fréquences d'échantillonnage inhabituelles | information | oui : convertir en 44,1 kHz |
| Échantillons très volumineux (plus de 20 Mio) | information | — |
| Percussions en stéréo | information | oui : passer en mono |
| Arborescence très profonde (plus de 8 niveaux) | information | — |
| Fichiers non audio dans `SAMPLES` | information | — |
| Dossiers vides | information | oui : les supprimer |

Un fichier XML à plusieurs racines est normal dans les anciens firmwares : il n'est pas signalé. Les contrôles d'écrêtage, de continu et de silence demandent l'analyse acoustique.

## Corriger automatiquement {#corriger}

Dans le rapport, **cochez** les anomalies à corriger — seules celles qui le permettent ont une case —, puis [Corriger automatiquement]. Le **plan exact** s'affiche : chaque fichier, chaque opération, en rouge ce qui supprime. Rien n'est fait avant votre accord.

L'ordre des opérations est imposé par la prudence : les références cassées sont réparées **avant** tout archivage, parce qu'un échantillon paraît inutilisé justement quand la référence qui le désigne est cassée.

[Exporter le rapport] enregistre le diagnostic en page HTML, à l'endroit choisi.

## Doublons {#doublons}

Les groupes de fichiers **rigoureusement identiques**, vérifiés octet par octet — une empreinte partielle ne suffit pas : elle a déjà déclaré identiques des fichiers qui différaient. Le tableau donne chaque groupe, ses fichiers et la place gaspillée.

[Exemplaire à conserver] décide lequel garder : [Chemin le plus court], le plus long, [Le plus utilisé], le plus ancien ou le plus récent. [Supprimer les doublons] montre d'abord la liste exacte des fichiers à supprimer ; les presets qui citaient un doublon sont redirigés vers l'exemplaire gardé.

## Manquants {#manquants}

Les échantillons réclamés par un preset, un kit ou un morceau, mais absents de la carte — avec qui les réclame.

- [Chercher des remplaçants] cherche sur la carte des fichiers qui pourraient les remplacer, par le nom, la taille et l'empreinte. Rien n'est modifié.
- [Relier automatiquement] corrige les presets pour qu'ils pointent vers le remplaçant trouvé — **seulement** quand il porte exactement le même nom de fichier : rediriger vers un nom approchant serait un pari, pas une réparation. Une copie `.bak` reste à côté de chaque fichier modifié.

## Inutilisés {#inutilises}

Les échantillons qu'aucun fichier de la carte ne cite, avec leur durée et leur taille. Ce n'est pas un défaut : une bibliothèque garde des sons en réserve. [Archiver dans _UNUSED] les **déplace** dans un dossier `_UNUSED` à la racine de la carte ; rien n'est supprimé, tout se récupère.

## Sauvegardes {#sauvegardes}

Une sauvegarde copie la carte dans le **dossier des sauvegardes** (Réglages ▸ Sûreté des écritures), dans un sous-dossier daté.

- Par défaut, elle copie les **morceaux, presets et kits**, avec les réglages et les favoris de la machine (le dossier `SETTINGS` du firmware 1.3) : quelques mégaoctets, moins d'une seconde — de quoi sauvegarder souvent.
- [Inclure les échantillons] ajoute les sons : plus d'un gigaoctet sur une carte bien remplie, à réserver aux sauvegardes complètes.
- [Compresser en .zip] la regroupe en une archive, plus lente à écrire, bien plus petite.

[Sauvegarder maintenant] la crée. Dans le tableau — date, libellé, nombre de fichiers, taille — choisissez une sauvegarde, puis :

- [Comparer] montre ce qui a changé depuis : fichiers modifiés, ajoutés, retirés ;
- [Restaurer] remet sur la carte les fichiers de la sauvegarde. Le nombre de fichiers remplacés est annoncé d'abord, et leurs versions actuelles sont mises à l'abri dans une sauvegarde « avant restauration ».

!!! attention Restaurer écrase
    C'est la seule action de la page qui remplace des fichiers de la carte par d'autres. Elle se confirme, et garde les versions remplacées — mais vérifiez avec [Comparer] avant.

!!! pro Deux sauvegardes, deux usages
    Ces sauvegardes datées sont faites **par l'application**. La « sauvegarde de la carte » déclarée dans Réglages ▸ Carte du Deluge est autre chose : votre copie complète de la carte, que l'application lit sans jamais y écrire, et met à jour sur commande (voir [La sauvegarde de la carte](#sauvegarde-carte)).

# Réglages {#reglages page=Settings}

> L'emplacement de la carte, le Deluge branché, l'écoute, l'analyse, la sûreté des écritures et l'apparence.

C'est la seule page qui fonctionne sans carte : c'est elle qui en désigne une. [Détecter les cartes], dans l'en-tête, cherche une carte Deluge sur les lecteurs branchés. Les sections, de haut en bas :

## Carte du Deluge {#reglages-carte-deluge}

L'état du lien — le Deluge ouvre-t-il sa carte par USB ? existe-t-il une copie de travail, et où ? — et ses commandes : [Créer la copie de travail], qui devient [Synchroniser maintenant] une fois la copie créée ; [Suppressions à confirmer…], quand des fichiers supprimés dans l'application existent encore sur la carte ; la case [Synchroniser d'office quand le Deluge est branché] (cochée par défaut) ; [Choisir la sauvegarde…] et [Mettre à jour la sauvegarde]. Tout est expliqué au chapitre [La carte reste dans le Deluge](#carte-dans-le-deluge).

## Autre emplacement de carte {#reglages-autre}

Pour une carte glissée dans un lecteur du PC, ou un dossier : le champ du chemin, vérifié au fil de la frappe, [Parcourir…], [Utiliser cette carte], les cartes détectées et les **chemins récents**. Voir [Désigner la carte](#designer).

## Deluge branché {#reglages-deluge}

L'état de la liaison MIDI et ce que la machine a dit d'elle (firmware, temps d'aller-retour) ; la **Sortie MIDI** et l'**Entrée MIDI** — « Chercher le Deluge tout seul » convient presque toujours ; le **Canal** (1 par défaut) ; trois cases : [Se connecter dès que le Deluge apparaît] (cochée), [Écouter les presets sur le Deluge plutôt que sur l'ordinateur] (décochée) et [Les outils suivent le tempo du Deluge] (cochée) ; les boutons [Connecter], [Jouer un do], [Tout éteindre] et [Deluge en direct…] ; enfin les réglages à faire **sur la machine**. Voir [Brancher le Deluge](#brancher).

## Écoute {#reglages-ecoute}

La **Sortie audio** des écoutes (le périphérique par défaut, ou un autre), le moteur audio utilisé, le **Volume d'aperçu** — sans effet sur le Deluge —, et la case [Écouter automatiquement l'échantillon sélectionné] (cochée).

## Analyse de la carte {#reglages-analyse}

Les cases [Calculer les empreintes (détection des doublons)], [Analyse acoustique (tempo, tonalité, niveaux)] et [Mettre l'index à jour au démarrage], le bouton [Réinitialiser l'index], et l'état de l'index : combien d'échantillons, presets, kits et morceaux, sa taille, la date de la dernière analyse. Voir [L'analyse et l'index](#analyse).

## Sûreté des écritures {#reglages-surete}

Deux garde-fous, cochés par défaut — **laissez-les** :

- [Demander confirmation avant toute écriture] : aucune écriture sur la carte sans une question préalable ;
- [Créer une copie .bak avant de réécrire un XML] : chaque preset ou kit réécrit laisse une copie datée à côté de lui.

Dessous, le **dossier des sauvegardes** faites depuis la page Santé ; vide, elles vont dans le dossier de configuration de l'application.

## Apparence et À propos {#reglages-apparence}

**Apparence** : six couleurs pour la façade — or, cyan, menthe, ambre, magenta, indigo. Elle teinte la barre du haut, les menus et les fenêtres ouvertes hors des pages ; chaque page garde sa propre couleur. **À propos** : la version, et le **dossier de configuration**, que [Ouvrir] montre dans l'Explorateur.

@partie deluge PAD_GREEN | Le Deluge branché | La machine au bout du câble USB : sa carte, son écran, son tempo

# Brancher le Deluge {#brancher icone=midi}

> Un câble USB, deux réglages sur la machine, et l'application peut jouer sur le Deluge, lire son écran et suivre son tempo.

## Ce qu'il faut {#brancher-prerequis}

- Un câble USB entre le Deluge et l'ordinateur, sous Windows.
- Le **firmware communautaire** : c'est lui qui répond aux messages de l'application (version, écran). Avec la version **1.3** ou plus récente, la carte s'ouvre en plus par le câble.

## Se connecter {#se-connecter}

Branchez le câble : la pastille « Deluge » de la barre du haut passe **à l'or**. Si la case [Se connecter dès que le Deluge apparaît] est cochée — c'est le réglage par défaut —, l'application se connecte d'elle-même et la pastille passe **au vert**. Sinon, un clic sur la pastille or connecte ; [Connecter], dans les réglages, fait de même.

Le Deluge expose plusieurs ports MIDI : l'application envoie notes et contrôleurs par le premier et dialogue en SysEx par le troisième. La machine dit alors sa version, et le temps d'aller-retour est mesuré. Débranché en cours de route, le lien se referme proprement, et la barre d'état l'annonce.

!!! retenir Se connecter ne joue rien
    À la connexion, l'application demande à la machine sa version, mesure le temps d'aller-retour et lui demande si sa carte s'ouvre par USB — des messages de lecture —, et rien d'autre. Aucune note ne part sans que vous la demandiez.

## Deux réglages sur la machine {#reglages-machine}

Le mode **MIDI Follow** du firmware communautaire est éteint sur une machine neuve. Une fois pour toutes, dans le menu des réglages du Deluge ([[SHIFT + SELECT]]) :

1. **MIDI ▸ MIDI-Follow ▸ Channel ▸ Channel A** = le canal de l'application (1 par défaut). Sans ce réglage, la machine ignore ce que l'application lui joue.
2. **MIDI ▸ MIDI-Follow ▸ Feedback ▸ Channel** = A, pour que les réglages du son sélectionné reviennent à l'application.

L'horloge MIDI, elle, sort d'elle-même : **MIDI ▸ Clock ▸ Output** est actif d'usine. Un kit répond à partir de la note 36 (**MIDI ▸ MIDI-Follow ▸ Kit Root Note**). Ces chemins sont les mêmes en firmware 1.2.1 et 1.3.

Avec le firmware 1.3, la machine écrit ces réglages sur sa carte, dans `SETTINGS/MIDIFollow.XML` : l'application les y lit, et la fenêtre [Deluge en direct](#en-direct) les coche dès l'ouverture, sans attendre que la machine les manifeste.

## Vérifier le câble {#verifier}

[Jouer un do] envoie un do central d'une demi-seconde à l'instrument sélectionné : si vous l'entendez, tout est en place. [Tout éteindre] relâche toutes les notes sur tous les canaux — le bouton de secours si un son reste coincé.

## Écouter sur la machine {#ecouter-sur-la-machine}

Cochez [Écouter les presets sur le Deluge plutôt que sur l'ordinateur] : [Écouter], sur les pages Presets et Générateur, fait alors jouer **le moteur de la machine** au lieu de l'approximation de l'ordinateur ; [Écouter le kit] envoie le motif d'essai au Deluge. Cette écoute ne s'active jamais toute seule : envoyer du son dans une machine branchée sur un ampli ne doit pas être une surprise.

Ce qui part : les réglages du preset **qu'un bouton pilote** — filtres, enveloppes, effets, volumes, une cinquantaine —, puis **la petite phrase que l'ordinateur jouerait**, choisie selon la catégorie du preset : quatre notes graves pour une basse, un accord égrené pour une nappe, une montée pour un lead. Une note toutes les 0,55 seconde, chacune tenue une demi-seconde. Ce qui ne part pas : la forme d'onde des oscillateurs, un échantillon, le mode de l'arpégiateur — aucun contrôleur ne les porte. Vous entendez donc **les oscillateurs de l'instrument sélectionné, réglés comme le preset**. Un preset à l'attaque très lente peut ne presque rien faire entendre en une demi-seconde.

Le Deluge **perd** les contrôleurs qui arrivent pendant qu'il traite les précédents, ou pendant qu'il envoie l'image de son écran. L'application attend donc qu'il ait lu chaque réglage avant d'envoyer le suivant : l'écoute part en une seconde environ. Fenêtre [Deluge en direct](#en-direct) ouverte, la recopie de l'écran se tait le temps de l'envoi, ce qui ajoute jusqu'à deux secondes.

!!! retenir Le réglage Takeover de la machine
    [[SHIFT + SELECT]] ▸ MIDI ▸ **Takeover** dit ce que le Deluge fait d'une valeur reçue. En **Jump** (réglage d'usine), il la prend. En **Pickup** ou **Scale**, il l'ignore tant qu'elle n'a pas « rattrapé » la position du bouton. L'application fait rattraper chaque bouton : quand le retour MIDI Follow lui a dit où il est, elle part de cette position ; sinon, machine à l'arrêt, elle le fait passer un instant par ses deux extrêmes. Machine en lecture et position inconnue, la valeur part seule — en Pickup ou en Scale, elle est alors ignorée. Le mode **Relative**, fait pour les encodeurs sans fin, n'est pas pris en charge.

!!! attention Le Deluge joue l'instrument sélectionné sur lui
    Aucun message MIDI ne permet de lui dire « charge ce preset » : c'est une limite de la machine. Les réglages du preset écouté partent en contrôleurs MIDI Follow juste avant la note, et s'appliquent **à l'instrument sélectionné sur le Deluge**. Son son change donc jusqu'à ce que vous le rechargiez — rien n'est enregistré sur la carte tant que vous ne sauvegardez pas sur la machine. Pour écouter sans risque, chargez d'abord un morceau sans importance.

## Le tempo du Deluge {#tempo}

Quand la machine joue, son horloge MIDI donne son tempo. Avec la case [Les outils suivent le tempo du Deluge] (cochée par défaut), les tempos de la boîte à outils le prennent dès que son arrondi change ; une page ouverte pendant que la machine joue le prend une fois, à sa première visite — ensuite, c'est vous qui décidez.

## La table des contrôleurs {#midi-follow}

Les contrôleurs que le mode MIDI Follow comprend sont lus sur votre carte, dans `SETTINGS/MIDIFollow.XML` avec le firmware 1.3 — à la racine de la carte avec les firmwares plus anciens. Sans ce fichier, ce sont les assignations d'usine : 52 paramètres pilotables. Le fichier du firmware 1.3 en déclare davantage — 79 sur la machine qui a servi à vérifier ce manuel, les réglages d'arpège compris. La section Deluge branché des réglages dit laquelle des deux tables est en usage, et combien de paramètres sont pilotables.

# La carte reste dans le Deluge {#carte-dans-le-deluge icone=refresh}

> Avec le firmware 1.3, la carte ne quitte plus la machine : l'application travaille sur une copie tenue à son image, par le câble USB.

[[figure flux | Le Deluge, la copie de travail et la sauvegarde. | LE DELUGE ; sa carte SD reste dedans ; câble USB, firmware 1.3 ; COPIE DE TRAVAIL ; sur le PC, tenue à l'image de la carte ; à la connexion, après chaque écriture, au retour dans la fenêtre — jamais pendant que la machine joue ; DELUGE COMPANION ; SAUVEGARDE ; votre copie complète de la carte, lue et jamais écrite par le travail courant ; mise à jour sur commande, rien n'y est supprimé]]

## Pourquoi une copie de travail {#pourquoi-copie}

Lire des milliers de fichiers par le câble USB prendrait des heures : il lit environ 170 Ko par seconde, et en écrit 60. Parcourir leur liste, en revanche, ne prend que quelques secondes — 3,4 s pour près de 3 000 fichiers, mesurées sur une vraie carte. L'application garde donc sur l'ordinateur une **copie de travail** de la carte, et la tient à son image en n'échangeant **que ce qui a changé** : ce que le Deluge a enregistré **descend**, ce que l'application a créé ou modifié **monte**.

## Créer la copie de travail {#creer-copie}

Une fois, Deluge branché : Réglages ▸ Carte du Deluge ▸ [Créer la copie de travail]. Le **plan** s'affiche d'abord : combien de fichiers seront **repris de votre sauvegarde** (une copie locale, rapide), combien viendront **par le câble**, et en combien de temps. Un fichier de votre sauvegarde identique à celui de la carte n'a pas besoin de traverser le câble.

La copie devient alors la carte de l'application, et l'analyse part. L'écran de la barre du haut affiche « CARTE DU DELUGE · COPIE DE TRAVAIL ».

!!! retenir Ce que la création écrit sur la carte
    Rien, sauf la date des fichiers que le Deluge a enregistrés : la machine n'a pas d'horloge et date tout de zéro. Cette date permet ensuite de voir ce qu'il réécrira. Votre sauvegarde, elle, n'est que lue.

## Quand la synchronisation a lieu {#quand-synchroniser}

Avec la case [Synchroniser d'office quand le Deluge est branché], l'application échange d'elle-même :

- **à la connexion** du Deluge ;
- **après chaque écriture** de l'application — deux secondes après la dernière. Seuls les dossiers que l'application a touchés sont relus sur la carte : quelques centièmes de seconde, au lieu des trois secondes et demie d'un parcours complet. Ce que vous avez enregistré sur la machine descend, lui, à la connexion, au retour dans la fenêtre ou sur demande ;
- **au retour dans la fenêtre**, au plus toutes les trente secondes, pour recevoir ce que vous avez enregistré sur la machine ;
- et **jamais pendant que la machine joue** : sa carte sert à jouer. Un transfert en cours s'arrête entre deux blocs, et reprend à l'arrêt.

À tout moment : [Synchroniser] sur le tableau de bord, [Synchroniser maintenant] dans les réglages, ou Outils ▸ Synchroniser avec le Deluge [[Ctrl+Maj+D]]. L'écran dit ce qui attend : « COPIE DE TRAVAIL · 3 À ENVOYER », ou « SYNCHRONISATION… ».

## Les règles des échanges {#regles-echanges}

| Situation | Ce qui se passe |
|---|---|
| un fichier changé sur le Deluge | il descend dans la copie de travail |
| un fichier créé ou modifié dans l'application | il monte sur la carte |
| un fichier changé **des deux côtés** | les deux versions sont gardées : celle du Deluge garde le nom, celle du PC devient « … (PC) » |
| un fichier supprimé dans l'application | il ne disparaît de la carte **qu'avec votre accord** : [Suppressions à confirmer…] |
| un fichier supprimé sur le Deluge | la version de la copie part dans son historique, jamais à la poubelle |
| le Deluge débranché pendant un transfert | l'échange reprend à la prochaine connexion |

Chaque échange s'écrit au journal de l'application, fichier par fichier.

## La sauvegarde de la carte {#sauvegarde-carte}

Réglages ▸ Carte du Deluge ▸ [Choisir la sauvegarde…] désigne le dossier qui garde votre **copie complète de la carte**. L'application le **lit** — pour créer la copie de travail sans tout faire passer par le câble — mais **n'y écrit jamais** au fil du travail. Ouvert comme carte, il s'ouvre **en lecture seule** : l'écran affiche « SAUVEGARDE · LECTURE SEULE ».

[Mettre à jour la sauvegarde] y fait entrer ce que la carte a de nouveau : le plan annonce les fichiers ajoutés, les fichiers remplacés — **l'ancienne version gardée à côté** — et ceux que la carte n'a plus, qui sont **gardés**. Rien n'y est jamais supprimé. Quand la sauvegarde a du retard sur la carte, « À faire maintenant » le propose.

## Avec un firmware plus ancien {#ancien-firmware}

Avec le firmware 1.2.1, la carte ne s'ouvre pas par le câble. Glissez-la dans un lecteur de l'ordinateur et indiquez-la dans Réglages ▸ Autre emplacement de carte : l'application y travaille directement. Le lien MIDI — écoute sur la machine, écran, tempo — fonctionne quand même.

# Échanger des fichiers {#echanges icone=import}

> Poser sur la carte des sons et des presets venus du PC, et en sortir ce que le Deluge a enregistré.

## Envoyer au Deluge {#envoyer}

La carte restant dans la machine, l'Explorateur ne l'atteint plus : c'est l'application qui y pose vos fichiers. Quatre chemins, un seul parcours :

- **glissez des fichiers ou un dossier n'importe où sur la fenêtre** — un pack téléchargé, un bounce de votre logiciel de musique. Un voile vert annonce « DÉPOSEZ POUR ENVOYER AU DELUGE » et où partira l'envoi ;
- Fichier ▸ Envoyer des fichiers au Deluge… [[Ctrl+I]] ;
- Fichier ▸ Envoyer un dossier au Deluge… [[Ctrl+Maj+I]] ;
- [Envoyer au Deluge…] sur la page Échantillons, qui envoie dans le dossier choisi dans son arbre, ou [Envoyer des fichiers…] sur le tableau de bord.

## Le plan avant l'envoi {#plan-envoi}

Avant toute copie, le **plan** s'affiche : où va chaque fichier, ce qui est déjà sur la carte, ce que le Deluge refuserait, et **combien de temps le câble y mettra** — environ 60 Ko/s : un pack de 18 Mo prend cinq minutes, un de 271 Mo près d'une heure vingt. Au-delà d'une demi-heure, le plan conseille de n'envoyer qu'une partie. Une liste règle le dossier de `SAMPLES` où vont les sons hors d'un pack. [Envoyer] lance la copie ; [Annuler] ne copie rien.

Les règles :

- un pack qui a **la forme d'une carte** (`SAMPLES`, `SYNTHS`…) garde ses chemins, que ses presets citent ;
- **rien d'existant n'est remplacé** : un fichier identique est laissé ; un homonyme différent fait numéroter le nouveau (« Kick 2.wav ») ;
- les noms deviennent **transmissibles** : sans accents ni caractères interdits (« Été » devient « Ete »), et les presets du pack suivent ;
- un fichier que le Deluge refuserait — un WAV à en-tête étendu, comme en écrivent beaucoup de logiciels — est **converti sans perte audible** ;
- ce qui n'est pas pour le Deluge — un MP3, un fichier à quatre canaux, de la documentation — reste sur le PC, et le plan dit pourquoi.

Les fichiers partent ensuite en arrière-plan sur le Deluge, ou à sa prochaine connexion. La sauvegarde ouverte en lecture seule refuse les envois : « Rien n'est écrit ici ».

!!! attention Le Deluge ne doit pas jouer pendant l'envoi
    Pendant que la machine joue, rien ne passe : le transfert s'arrête entre deux blocs, et reprend à l'arrêt.

## Du Deluge vers le PC {#vers-le-pc}

- Le panneau **Le Deluge et le PC** du tableau de bord liste ce qui est arrivé de la machine ; un clic ouvre chaque fichier sur sa page.
- Sur la page Échantillons, **glissez un son** vers l'Explorateur ou votre logiciel de musique : il en reçoit une copie, tel qu'il est dans la copie de travail. Un enregistrement fait sur le Deluge se retravaille ainsi sur le PC.
- Les exports — [Morceau en MIDI], [Rassembler…], [Motif en MIDI] — écrivent sur l'ordinateur, à l'endroit choisi.

# Deluge en direct {#en-direct icone=wave}

> Une fenêtre à garder à côté de l'application : l'écran de la machine, son tempo, les notes de ses pistes MIDI, et le son sélectionné.

Elle s'ouvre par Outils ▸ Deluge en direct [[Ctrl+D]], par [Deluge en direct…] dans les réglages, ou d'un clic sur la pastille verte. Elle ne fait que **lire** : rien n'est écrit sur la machine.

## Ses quatre panneaux {#panneaux-direct}

| Panneau | Ce qu'il montre |
|---|---|
| Écran de la machine | l'écran OLED du Deluge, recopié au moment où il change |
| Tempo et notes | le tempo lu dans l'horloge, « En lecture » ou « À l'arrêt », les notes tenues sur une **piste MIDI** du Deluge et l'accord qu'elles forment. Un synthé ou un kit joué sur les pads n'envoie pas ses notes : « Aucune note reçue » ne signale pas une panne |
| Son sélectionné sur la machine | les réglages que le retour MIDI Follow renvoie quand vous changez d'instrument ou tournez un bouton |
| Réglages à faire sur le Deluge | la liste des réglages nécessaires, cochés à mesure que la liaison les constate |

## Ses boutons {#boutons-direct}

- [Recopier l'écran] démarre ou arrête la recopie. Elle part d'elle-même à l'ouverture. Arrêtée, la fenêtre l'écrit en clair : elle ne montre jamais une image figée qu'on prendrait pour la machine.
- [Faire signe] affiche « HELLO SYSEX » un instant sur le Deluge : de quoi vérifier qu'on parle bien à lui.
- [Vérifier] redemande sa version à la machine et mesure l'aller-retour.
- [Tout éteindre] relâche toutes les notes.
- [Connecter] ou [Déconnecter], et [Réglages MIDI…], qui mène à la section Deluge branché des réglages.

Fermer la fenêtre arrête la recopie de l'écran.

!!! attention L'économiseur d'écran du firmware 1.3
    Au repos, le Deluge en 1.3 remplace son écran par une animation — des traits qui tombent en diagonale (mode « Deluge »), un champ d'étoiles, ou le noir. La recopie montre fidèlement cette animation, et le message de [Faire signe] reste caché dessous. Seul un geste sur la machine — un bouton, un encodeur — la réveille ; ni le MIDI ni l'application ne le peuvent. Son mode et son délai se règlent dans **Settings ▸ Defaults ▸ Screensaver**.

# Écrire des morceaux pour le Deluge {#morceaux-pour-le-deluge icone=song}

> Chaque outil de création sait écrire ce qu'il a produit en morceau du Deluge : un fichier neuf dans SONGS, que la machine charge comme les autres.

## Les neuf boutons {#boutons-morceau}

| Où | Bouton | Ce que contient le morceau |
|---|---|---|
| Outils ▸ Théorie | [En morceau] | un clip par partie — accords, basse, arpège, mélodie, batterie —, avec les sons entendus à l'écoute ; tout boucle ensemble dès PLAY |
| Outils ▸ Rythme | [En morceau] | le motif affiché, joué par un kit de vos échantillons |
| Outils ▸ Arrangement | [Esquisse en morceau] | une section du Deluge par section du modèle, chacune avec ses clips et son nombre de répétitions |
| Kits | [Motif en morceau] | le kit choisi, tel qu'il est sur la carte, et le motif d'essai |
| Générateur | [Essayer en morceau] | le son en situation : une phrase faite pour son rôle, et la batterie du genre |
| Générateur ▸ Kit de batterie | [Kit en morceau] | le kit construit et le rythme de son genre |
| Échantillons ▸ Découper… | [Écrire en morceau] | le kit des tranches, et un clip qui rejoue la boucle |
| Atelier | [Écrire le morceau] | le morceau composé : une section du Deluge par section, leurs clips, leurs répétitions et l'arrangement complet |
| Atelier | [Compléter le morceau] | votre morceau octet pour octet, plus les pistes, les clips et les sections ajoutés — dans une nouvelle version |

## Le parcours {#parcours-morceau}

1. L'application construit le morceau ; une erreur d'usage — rien à écrire, pas de carte — s'annonce avant toute question.
2. Elle demande son **nom**, assaini pour la carte.
3. Elle montre le **plan** : le fichier, les instruments, les clips, les échantillons absents de la carte.
4. Elle écrit, puis indexe le nouveau morceau : il apparaît aussitôt sur la page Morceaux.
5. Sur la copie de travail, le Deluge branché le reçoit **de lui-même** : deux secondes après l'écriture, la synchronisation relit les seuls dossiers touchés — quelques centièmes de seconde —, puis envoie le fichier à environ 60 Ko/s : une demi-seconde pour un morceau de 33 Ko, trois pour une esquisse de 165 Ko. Il se charge ensuite sur la machine comme tout autre morceau.

**Aucun fichier existant n'est remplacé** : un nom déjà pris est numéroté.

## Jouer une esquisse {#jouer-esquisse}

Une esquisse à sections se joue de deux façons sur la machine. **PLAY** fait tourner la première section en boucle ; lancez la suivante, et la suite s'enchaîne jusqu'à la fin. La vue **arrangement** (touche SONG) joue le morceau entier d'un trait. Les parties qui se répètent tiennent dans des clips courts — quatre mesures d'accords, une mesure de batterie —, comme on les construit sur la machine.

!!! retenir Éprouvé sur la machine
    Le 22 octobre 2026, trois morceaux écrits par l'application — une progression avec sa batterie, une esquisse à six sections, un motif sur le kit TR-808 — ont été envoyés par le câble, chargés et joués sur un Deluge en firmware 1.3. Le format écrit est celui du firmware communautaire 1.2.1, que la 1.3 lit aussi, et les conversions des presets anciens ont été comparées aux morceaux enregistrés sur la machine. Chaque morceau est un fichier neuf : il ne touche à rien de ce que la carte contient déjà.

@partie reference PAD_PINK | Référence | Les garde-fous, les raccourcis, les pannes courantes et le vocabulaire

# La règle de non-destruction {#non-destruction icone=check}

> L'application est construite autour d'un principe : elle ne modifie rien sans qu'on le lui demande explicitement.

[[figure plan | Les quatre temps de toute écriture sur la carte. | Vous demandez ; un clic sur un bouton qui écrit ; Le plan ; chaque fichier, chaque opération, avant tout ; Votre accord ; rien ne part sans lui ; L'écriture ; avec une copie .bak de tout XML réécrit]]

## Les garde-fous {#garde-fous}

- **Tout est simulé d'abord.** Rangement, réparation, suppression, traitement, envoi : le plan s'affiche opération par opération, et rien n'est touché avant un clic de confirmation. Un plan qui supprime ou qui change la longueur de fichiers le signale en rouge.
- **Chaque XML réécrit laisse un `.bak` daté** à côté de lui (Réglages ▸ Sûreté des écritures).
- **Un doublon n'est supprimé que s'il est identique octet par octet**, jamais sur la foi d'une empreinte partielle.
- **Les morceaux ne sont jamais réécrits.** L'application en crée de nouveaux ; elle ne modifie pas les vôtres. Même [Compléter le morceau] écrit une nouvelle version, à côté de l'ancienne.
- **Le dialecte d'origine est conservé** : un fichier d'un ancien firmware est réécrit dans son format, et le Deluge continue de le lire.
- **Rien ne se perd** : l'archivage déplace dans `_UNUSED`, les traitements audio gardent les originaux dans `_BACKUP`, la restauration garde les versions remplacées, la synchronisation range dans l'historique ce qu'elle retire.
- **La sauvegarde de la carte n'est que lue**, et ne reçoit jamais de suppression.

## Ce qui écrit sur la carte {#ce-qui-ecrit}

Voici réunies toutes les commandes qui écrivent sur la carte. Chacune montre son plan ou pose une question avant d'écrire — seul [Enregistrer dans KITS] écrit d'emblée quand le nom choisi est libre, puisqu'il ne remplace rien :

| Page | Commandes |
|---|---|
| Échantillons | [Traiter…], [Écrire le kit], [Exporter en fichiers…], [Écrire en morceau], [Envoyer au Deluge…] |
| Presets | [Dupliquer] |
| Kits | [Motif en morceau] |
| Générateur | [Enregistrer dans SYNTHS], [Générer un lot dans un dossier…], [Essayer en morceau], [Enregistrer dans KITS], [Kit en morceau] |
| Atelier | [Écrire le morceau], [Compléter le morceau] |
| Outils | les trois boutons « en morceau » |
| Santé | [Corriger automatiquement], [Supprimer les doublons], [Relier automatiquement], [Archiver dans _UNUSED], [Restaurer] |
| Réglages | [Créer la copie de travail], [Synchroniser maintenant], [Suppressions à confirmer…], [Mettre à jour la sauvegarde] — cette dernière écrit dans votre sauvegarde |

La page Morceaux, elle, n'écrit jamais sur la carte.

# Raccourcis clavier {#raccourcis icone=list}

> Les combinaisons de la fenêtre principale et de ce manuel.

| Raccourci | Action |
|---|---|
| [[Ctrl+1]] à [[Ctrl+9]], [[Ctrl+0]] | aller à la page correspondante, dans l'ordre de la colonne ; [[Ctrl+0]] pour la dixième, Réglages |
| [[Ctrl+R]] | analyser la carte |
| [[Ctrl+F]] | rechercher un échantillon, depuis n'importe quelle page |
| [[Ctrl+O]] | choisir la carte |
| [[Ctrl+G]] | le générateur |
| [[Ctrl+,]] | les réglages |
| [[Ctrl+I]] | envoyer des fichiers au Deluge |
| [[Ctrl+Maj+I]] | envoyer un dossier au Deluge |
| [[Ctrl+D]] | Deluge en direct |
| [[Ctrl+Maj+D]] | synchroniser avec le Deluge |
| [[Ctrl+B]] | replier ou déplier la colonne de gauche |
| [[Espace]] | écouter, ou arrêter l'écoute |
| [[F1]] | ce manuel, au chapitre de la page affichée |
| [[Ctrl+Q]] | quitter |

Dans la fenêtre du manuel :

| Raccourci | Action |
|---|---|
| [[Ctrl+F]] | chercher dans le manuel |
| [[Entrée]] ou [[F3]] | occurrence suivante |
| [[Maj+F3]] | occurrence précédente |
| [[Échap]] | vider la recherche, puis fermer le manuel |

Aide ▸ Raccourcis clavier rappelle la première liste dans une petite fenêtre.

# Questions et dépannage {#depannage icone=warning}

> Les situations courantes, et ce qu'il faut faire.

## Les pages sont vides {#pages-vides}

Aucune carte n'est indiquée, ou elle n'a pas encore été lue. Indiquez-la ([Désigner la carte](#designer)), puis [Analyser]. L'écran de la barre du haut dit ce qu'il en est : « AUCUNE CARTE », ou « CARTE · pas encore analysée ».

## « Ce dossier ne contient pas d'arborescence Deluge » {#pas-une-carte}

Vous avez désigné un dossier qui ne contient pas au moins deux des dossiers `SONGS`, `SYNTHS`, `KITS`, `SAMPLES`. Remontez d'un niveau : il faut la **racine** de la carte, pas l'un de ses dossiers.

## Je n'entends rien {#pas-de-son}

- Le paquet **sounddevice** est-il installé ? Sans lui, les écoutes sur l'ordinateur sont muettes.
- Vérifiez la **Sortie audio** et le **Volume d'aperçu** dans Réglages ▸ Écoute.
- Si « Écouter les presets sur le Deluge » est cochée, le son sort **de la machine** : vérifiez ses réglages MIDI Follow et son volume.

## Un bouton reste gris {#bouton-gris}

Il attend une sélection : un son, un preset, une rangée. Son infobulle dit ce qu'il fera. [Découper…] et [Sons proches] veulent un seul son ; [Analyser] veut une carte.

## La pastille « Deluge » reste grise {#pastille-grise}

L'ordinateur ne voit pas la machine. Vérifiez le câble — certains câbles USB ne transportent que le courant —, que le Deluge est allumé, et qu'aucun autre logiciel n'occupe ses ports MIDI. Hors de Windows, le lien MIDI n'est pas disponible.

## Le Deluge ignore ce que l'application joue {#deluge-ignore}

Le réglage **MIDI ▸ MIDI-Follow ▸ Channel ▸ Channel A** de la machine doit valoir le canal de l'application (1 par défaut, Réglages ▸ Deluge branché). Rappel : la machine joue **l'instrument sélectionné sur elle**. [Jouer un do] permet de vérifier.

## L'écoute sur le Deluge ne change pas le son {#ecoute-sans-effet}

- Le Deluge applique les réglages à **l'instrument sélectionné sur lui** : est-ce bien celui que vous écoutez ? En vue morceau, c'est le dernier clip ouvert.
- [[SHIFT + SELECT]] ▸ MIDI ▸ **Takeover** est sur **Relative** : l'application ne sait pas lui parler ainsi. Choisissez Jump, Pickup ou Scale.
- La machine joue, le retour MIDI Follow est éteint, et Takeover est sur Pickup ou Scale : les valeurs sont ignorées. Arrêtez la lecture, ou allumez le retour (MIDI-Follow ▸ Feedback ▸ Channel = A).

Pour voir ce que la machine applique, allumez **MIDI-Follow ▸ Display Param** : le nom et la valeur de chaque réglage reçu s'affichent sur son écran. Voir [Écouter sur la machine](#ecouter-sur-la-machine).

## L'écran recopié montre des traits qui tombent {#economiseur}

C'est l'économiseur d'écran du firmware 1.3 : la machine est au repos, et la recopie montre exactement ce qu'elle affiche. Touchez un bouton ou un encodeur du Deluge pour le réveiller ; Settings ▸ Defaults ▸ Screensaver en règle le mode et le délai.

## « Pas de réponse SysEx » {#pas-de-sysex}

Le Deluge n'a pas répondu aux questions de l'application : il a le firmware officiel, ou un autre logiciel occupe son port SysEx. Les notes passent quand même ; la version, l'écran et la carte par USB demandent le firmware communautaire.

## « Sons proches » refuse de chercher {#sons-proches-refuse}

Le son choisi n'a pas de mesures acoustiques. Cochez « Analyse acoustique » dans Réglages ▸ Analyse de la carte, puis relancez l'analyse. Il en va de même pour la tonalité des sons et la recherche par tonalité.

## Le Deluge joue, et rien ne se synchronise {#sync-attend}

C'est voulu : la carte sert à jouer, et l'application attend l'arrêt de la lecture pour échanger. La barre d'état l'annonce.

## La carte n'est pas à jour dans l'application {#index-ancien}

Des fichiers ont été copiés sur la carte en dehors de l'application. [Analyser] relit ce qui a changé. Si l'index semble vraiment incohérent, [Réinitialiser l'index] le reconstruit, sans toucher à la carte ni à vos notes.

## Où trouver le journal ? {#journal}

Dans le dossier de configuration, fichier `app.log` : Réglages ▸ À propos ▸ [Ouvrir]. Une erreur imprévue s'affiche dans une boîte, et sa trace complète s'y écrit. Le journal reste en français, quelle que soit la langue : il sert au diagnostic.

## L'application s'est fermée pendant un travail {#fermeture}

Rien d'écrit à moitié ne reste sur la carte : une sauvegarde interrompue est supprimée pour ne pas passer pour complète, une synchronisation reprend à la prochaine connexion, et un traitement d'échantillons garde ses originaux dans `_BACKUP`.

# Glossaire {#glossaire icone=tag}

> Les mots de l'application et du Deluge, en une phrase chacun.

| Terme | Définition |
|---|---|
| Analyse | la lecture de la carte qui remplit l'index ; elle ne modifie rien |
| Analyse acoustique | les mesures faites sur chaque son : tempo, tonalité, niveaux, timbre |
| Arrangement | la vue du Deluge où le morceau se déroule sur une ligne de temps |
| Câble de modulation | une liaison entre une source (LFO, enveloppe, vélocité…) et un paramètre |
| Camelot | une notation des tonalités qui dit d'un coup d'œil lesquelles s'enchaînent |
| Clip | une boucle de notes d'un instrument, sur la grille de session |
| Composante continue | un décalage de la forme d'onde au-dessus ou au-dessous de zéro ; elle gaspille de la marge |
| Copie de travail | la copie de la carte que l'application tient à son image par USB |
| Diagnostic | la recherche d'anomalies dans l'index ; il ne relit pas la carte |
| Doublon | un fichier rigoureusement identique à un autre, octet par octet |
| Écrêtage | un son saturé, dont les sommets ont été coupés à l'enregistrement |
| Empreinte | un résumé du contenu d'un fichier, qui reconnaît les doublons |
| Firmware communautaire | le firmware ouvert du Deluge (versions c1.x) ; il répond aux messages de l'application |
| Graine | le nombre qui rend une génération reproductible |
| Index | la base de données de l'application sur la carte ; elle vit sur l'ordinateur |
| Kit | un instrument de batterie : une rangée par son |
| MIDI Follow | le mode du firmware communautaire où les contrôleurs reçus pilotent l'instrument sélectionné |
| Orphelin | un échantillon qu'aucun preset, kit ni morceau ne cite |
| Plan | la liste exacte des opérations, montrée avant toute écriture |
| Preset | un son de synthé enregistré dans `SYNTHS` |
| Rangée | une ligne d'un kit : un son, et ses réglages |
| Section | un groupe de clips qui jouent ensemble dans un morceau du Deluge |
| Sauvegarde de la carte | votre copie complète de la carte, lue sans jamais être écrite par le travail courant |
| SysEx | les messages MIDI propres à une machine ; ceux du Deluge donnent sa version et son écran |
| `syncLevel` | la valeur qui cale un LFO, un délai ou un arpège sur le tempo |

# Où l'application range ses fichiers {#fichiers icone=folder}

> Rien n'est caché : voici où vit chaque chose.

| Quoi | Où |
|---|---|
| Réglages | `settings.json`, dans le dossier de configuration |
| Index | `library.db`, dans le dossier de configuration |
| Journal | `app.log`, dans le dossier de configuration (un Mo au plus, et les trois précédents à côté : `app.log.1` à `app.log.3`) |
| Sauvegardes de la page Santé | le dossier choisi dans les réglages ; par défaut `backups`, dans le dossier de configuration |
| Copie de travail | `%LOCALAPPDATA%\DelugeCompanion\Carte`, sauf réglage contraire |
| Historique de la synchronisation | `.deluge-companion` dans la copie de travail |
| Originaux des traitements audio | `_BACKUP` à la racine de la carte |
| Échantillons archivés | `_UNUSED` à la racine de la carte |
| Copies avant réécriture | un `.bak` daté, à côté de chaque XML réécrit |

Le **dossier de configuration** est `%APPDATA%\DelugeCompanion` sous Windows, `~/.config/DelugeCompanion` ailleurs. La variable d'environnement `DELUGE_COMPANION_CONFIG` le déplace — et la copie de travail avec lui. Réglages ▸ À propos ▸ [Ouvrir] l'affiche dans l'Explorateur.
