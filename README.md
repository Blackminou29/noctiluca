# Deluge Companion

Application de bureau qui accompagne un **Synthstrom Deluge** : elle gère le
contenu de la carte SD, range les échantillons et les presets, répare les
références cassées, génère des presets de synthé et des kits, et réunit les
outils utiles au quotidien d'un producteur de musique électronique.

Tout tient dans un dossier : pas de serveur, pas de compte, pas d'accès
réseau. L'application lit la carte montée par un lecteur SD ou par l'USB du
Deluge, et écrit son index dans le profil utilisateur.

```
python main.py
```

---

## Installation

Python **3.11 ou plus récent** (développé sur 3.13).

```bash
pip install -r requirements.txt
python main.py
```

Deux paquets sont nécessaires — **PyQt6** pour l'interface et **numpy** pour
tout ce qui touche à l'audio. **sounddevice** est optionnel : sans lui,
l'application démarre normalement, mais les boutons d'écoute restent inactifs.

### Options de ligne de commande

| Option | Effet |
| --- | --- |
| `--sd CHEMIN` | utilise cette carte pour cette session, et la mémorise |
| `--reset-db` | vide l'index avant de démarrer |
| `--no-splash` | pas d'écran de démarrage |
| `--verbose` | journal détaillé sur la console |
| `--version` | affiche la version et quitte |

Réglages, index et journal vivent dans `%APPDATA%\DelugeCompanion\` sous
Windows, `~/.config/DelugeCompanion/` ailleurs : `settings.json`,
`library.db`, `app.log`.

La variable d'environnement **`DELUGE_COMPANION_CONFIG`** déplace ce dossier.
De quoi emporter le logiciel et ses réglages sur une clé USB :

```bash
DELUGE_COMPANION_CONFIG=/media/cle/deluge-companion python main.py
```

---

## Premier démarrage

**L'application s'ouvre même sans carte.** Si aucune carte n'est connue, elle
ouvre la page *Réglages*, et l'écran de la barre du haut affiche « AUCUNE
CARTE — CLIQUEZ POUR CHOISIR ». Le chemin de la carte se change à tout moment, dans *Réglages* ou
par `Ctrl+O` : il n'est écrit nulle part dans le code. Les cartes utilisées
récemment sont proposées, et les lecteurs branchés sont repérés tout seuls :
est reconnu comme carte Deluge tout emplacement portant au moins deux des
dossiers `SONGS/`, `SYNTHS/`, `KITS/`, `SAMPLES/`.

Ensuite, **Analyser la carte** (`Ctrl+R`) remplit l'index. L'analyse est
incrémentale : les fichiers inchangés ne sont pas relus, et elle s'interrompt
sans rien abîmer. Sur une carte de 1741 échantillons, le premier passage
prend quelques minutes avec l'analyse acoustique activée, puis les suivants
quelques secondes.

---

## Par où commencer

Au premier lancement, l'application demande où se trouve votre carte : soit
vous indiquez le dossier, soit vous la laissez **chercher toute seule** sur
les lecteurs branchés. Ensuite, **Analyser la carte** (`Ctrl+R`) remplit
l'index, et tout le reste s'allume.

À partir de là, le tableau de bord ouvre sur un bandeau **« À faire
maintenant »** : une suggestion, la plus utile sur le moment, avec le bouton
qui l'exécute. Pas de sauvegarde ? Il le dit avant de proposer autre chose.
Des sons manquent à des presets ? Il mène directement à l'écran qui les
retrouve.

**Chaque commande s'explique** : laissez la souris dessus une seconde. Les
actions qui écrivent sur la carte le disent avant d'être cliquées.

---

## Se repérer

L'interface reprend le *Guide du Deluge* : la façade sombre de la machine,
ses pads lumineux, son écran, et le treillis de circuits des ouvertures de
partie.

- **Chaque page a sa couleur**, prise dans les pads de la machine : ambre
  pour le tableau de bord, cyan pour les échantillons, violet pour les
  presets, vert pour les kits, bleu pour les morceaux, magenta pour le
  générateur, menthe pour la boîte à outils, orange pour la santé, indigo
  pour les réglages. Comme chaque partie du guide a la sienne, la page la
  porte partout : son pad allumé dans la colonne de gauche, le filet
  lumineux sous la barre du haut, l'en-tête et son treillis, le bouton
  principal, les sélections, les onglets, les cases et les curseurs.
- **La colonne de gauche est une rangée de pads.** Éteints, ils montrent leur
  couleur en veilleuse ; celui de la page affichée s'allume. Le chiffre à
  droite est son raccourci (`Ctrl+1` à `Ctrl+9`), et `Ctrl+B` réduit la
  colonne à ses pads.
- **L'écran en haut** est celui du Deluge : la carte ouverte et ce qu'elle
  contient. Chaque message de l'application y passe quelques secondes, et
  défile s'il est trop long, comme sur la machine. Un clic mène aux réglages
  de la carte.
- **La pastille « Deluge »** s'allume en or quand la machine est branchée, en
  vert quand elle est connectée ; verte, un clic ouvre *Deluge en direct*.

Un raccourci montre la couleur de **sa destination** — le bouton
« Sauvegarder la carte » du tableau de bord est orange parce qu'il mène à la
page *Santé*, et il y mène **directement sur l'onglet des sauvegardes**.

Un bouton éteint attend quelque chose de vous : la plupart du temps, une
ligne choisie dans la liste. Sur une fenêtre étroite, les boutons d'une page
se replient sur leur icône ; laissez la souris dessus pour lire leur nom.

La couleur choisie dans *Réglages → Apparence* est celle de la façade : la
barre du haut, les menus, et les fenêtres ouvertes hors des pages.

---

## Brancher le Deluge

Reliez le Deluge au PC en USB : la pastille **Deluge** de la barre du haut
passe au vert — l'application se connecte d'elle-même si la case en est
cochée dans *Réglages › Deluge branché* — et la machine dit sa version
(aller-retour de 0,3 ms).

### Sa carte reste dedans

Avec le **firmware 1.3**, le Deluge ouvre sa carte au PC par le câble USB.
L'application travaille alors sur une **copie de travail** qu'elle tient à
l'image de la carte : ce que vous créez part sur la carte, ce que vous
enregistrez sur le Deluge revient — à la connexion, après chaque écriture,
au retour dans la fenêtre, jamais pendant que la machine joue.
*Réglages › Carte du Deluge › Créer la copie de travail*, une fois : elle
reprend de votre sauvegarde ce qui y est déjà et ne fait passer par le câble
que le reste (une minute chez vous).

* changé des deux côtés : les deux versions sont gardées ;
* une suppression faite sur le PC ne part sur la carte **qu'avec votre
  accord** ; une suppression faite sur le Deluge part dans l'historique de
  la copie ;
* **votre sauvegarde n'est que lue**. Elle se met à jour sur commande
  (*Mettre à jour la sauvegarde*), sans que rien n'y soit jamais supprimé.

Avec le firmware 1.2.1, la carte ne s'ouvre que glissée dans un lecteur du
PC (*Réglages › Autre emplacement de carte*).

### Envoyer au Deluge, et retour

La carte restant dans la machine, l'Explorateur ne l'atteint plus : c'est
l'application qui y pose vos sons. **Glissez des fichiers ou un dossier
n'importe où sur la fenêtre** — un pack téléchargé, un bounce de votre
logiciel de MAO —, ou *Fichier › Envoyer des fichiers au Deluge* (Ctrl+I),
*Envoyer un dossier* (Ctrl+Maj+I), ou le bouton de la page *Échantillons*,
qui envoie dans le dossier choisi dans son arbre.

Le **plan** s'affiche avant toute copie : où va chaque fichier, ce qui est
déjà sur la carte, ce que le Deluge refuserait, et **combien de temps le
câble y mettra** — 45 Ko/s : un pack de 18 Mo, sept minutes ; de 271 Mo,
près d'une heure trois quarts. Les fichiers partent ensuite en arrière-plan,
ou à la prochaine connexion du Deluge ; l'écran de la barre du haut dit
combien attendent (« 3 À ENVOYER »).

* un pack qui a la forme d'une carte (`SAMPLES`, `SYNTHS`…) garde ses chemins,
  que ses presets citent ; le reste va dans le dossier d'échantillons choisi ;
* **rien d'existant n'est remplacé** : identique, il est laissé ; homonyme,
  le nouveau est numéroté (« Kick 2.wav ») ;
* les noms deviennent lisibles par le câble (« Été » devient « Ete ») et
  les presets du pack suivent ;
* un fichier que le Deluge refuserait — un WAV à en-tête étendu, comme en
  écrivent beaucoup de logiciels de MAO — est converti sans perte audible ;
  un quatre-canaux, un MP3, restent sur le PC, et le plan dit pourquoi ;
* **pendant que le Deluge joue, rien ne passe** : un transfert s'arrête entre
  deux blocs et reprend à l'arrêt.

Dans l'autre sens, le panneau **Le Deluge et le PC** du tableau de bord
liste ce qui est arrivé de la machine — un clic l'ouvre sur sa page —, et
un son de la page *Échantillons* **se glisse vers l'Explorateur ou votre
logiciel de MAO**. Quand la carte a reçu ce que votre sauvegarde n'a pas
encore, *À faire maintenant* propose de la mettre à jour. Chaque échange
s'écrit au journal, fichier par fichier.

| | |
|---|---|
| **Voir la machine** | *Deluge en direct* (Ctrl+D, ou un clic sur la pastille verte) recopie son écran au moment où il change |
| **Suivre son tempo** | l'horloge qu'elle envoie en jouant donne son tempo aux outils de composition |
| **Lire le son sélectionné** | avec le retour MIDI Follow, ses réglages s'affichent quand vous changez d'instrument ou tournez un bouton |
| **Écouter pour de vrai** | les presets sonnent sur le Deluge, avec son moteur, au lieu de l'approximation calculée par l'ordinateur |
| **Régler à distance** | 52 paramètres de l'instrument sélectionné, par le mode MIDI Follow du firmware communautaire |
| **Envoyer un motif** | le motif d'essai d'un kit part en mesure, avec l'horloge MIDI |
| **Tout éteindre** | un bouton de secours qui relâche toutes les notes, sur tous les canaux |

**Une fois, sur le Deluge** : MIDI ▸ Follow ▸ **Channel A** = le canal de
l'application (1 par défaut) — sans ce réglage, la machine ignore ce que
l'application lui joue —, puis **Feedback** = Channel A, pour que le son
sélectionné revienne à l'application. L'horloge, elle, sort d'elle-même
(MIDI ▸ Clock ▸ Out). La fenêtre *Deluge en direct* coche ces réglages à
mesure qu'elle les constate.

Trois choses à savoir :

* **le Deluge joue l'instrument sélectionné sur lui.** Aucun message MIDI ne
  permet de lui dire « charge ce preset » ; c'est une limite de la machine ;
* l'écoute sur le Deluge ne s'active pas toute seule. Elle se coche dans
  *Réglages › Deluge branché* : envoyer du son dans une machine reliée à un
  ampli ne doit pas être une surprise ;
* **se connecter ne joue rien.** L'application demande à la machine sa
  version et l'image de son écran — des messages de lecture —, rien
  d'autre. Les fichiers passent toujours par la carte : le firmware c1.2.1
  ne les ouvre pas en USB.

La correspondance des contrôleurs est lue dans `MIDIFollow.XML`, à la racine
de votre carte ; sans ce fichier, ce sont les assignations d'usine, et la
page *Réglages* le dit.

---

## Les neuf pages

| Page | Raccourci | À quoi elle sert |
| --- | --- | --- |
| **Tableau de bord** | `Ctrl+1` | l'état de la carte en un écran : contenu, espace, note de santé, ce qui demande attention |
| **Échantillons** | `Ctrl+2` | parcourir, écouter, filtrer les 1700+ échantillons ; tempo, tonalité et catégorie détectés ; étiquettes et notes ; **traitement par lot** (mono, normalisation, rééchantillonnage, fondus) |
| **Presets** | `Ctrl+3` | inspecter les presets de synthé : oscillateurs, filtre, enveloppes, modulations, échantillons employés |
| **Kits** | `Ctrl+4` | voir les kits pad par pad, repérer les pads muets ou cassés |
| **Morceaux** | `Ctrl+5` | tempo, gamme, pistes et instruments de chaque morceau (**lecture seule**) ; export MIDI et rassemblement des dépendances |
| **Générateur** | `Ctrl+6` | créer des presets de synthé et des kits : par **genre musical** ou au hasard, avec écoute avant d'écrire |
| **Outils** | `Ctrl+7` | gammes et accords, progressions, mixage harmonique, rythmes euclidiens, grooves, export MIDI |
| **Santé** | `Ctrl+8` | diagnostic complet, réparation guidée, rangement, sauvegarde |
| **Réglages** | `Ctrl+9` | carte SD, audio, analyse, apparence, sauvegardes |

Autres raccourcis : `Ctrl+R` analyser, `Ctrl+F` rechercher, `Ctrl+G`
générateur, `Ctrl+O` choisir la carte, `Ctrl+B` replier la barre latérale,
`Ctrl+,` réglages, `Espace` écouter, `F1` la liste complète, `Ctrl+Q`
quitter.

---

## La règle qui ne se négocie pas

Une carte SD de Deluge contient des mois de travail. Le programme est donc
construit autour d'un principe simple : **il ne modifie rien sans qu'on le
lui demande explicitement.**

* Tout rangement, toute réparation, toute suppression est d'abord **simulé**.
  Le plan s'affiche opération par opération ; rien n'est touché avant un clic
  de confirmation (`apply=False` par défaut dans tout le cœur du programme).
* Chaque fichier XML réécrit laisse un **`.bak` horodaté** à côté de lui.
* Un doublon n'est **jamais** proposé à la suppression sur la foi d'une
  empreinte partielle : les candidats sont confirmés octet par octet avant
  d'apparaître.
* Les **morceaux ne sont jamais réécrits.** Le format est trop riche pour
  qu'une relecture-réécriture soit sûre ; la page *Morceaux* est donc
  volontairement en lecture seule.
* Le **dialecte XML d'origine est conservé** : un fichier du firmware 2.x est
  réécrit en 2.x, un fichier 3.0+ en 3.0+. Le Deluge continue de les lire.
* La sauvegarde se fait avant les opérations risquées, et se restaure.

---

## Ce que la page *Santé* sait trouver

Vingt-deux diagnostics, dont les plus utiles en pratique :

* **échantillons manquants** — un preset cherche un fichier qui n'est plus là.
  L'application propose un remplaçant par nom, taille et empreinte, puis
  recolle toutes les références en une seule passe ;
* **échantillons orphelins** — présents sur la carte, employés par rien ;
* **doublons confirmés** ;
* **noms incompatibles FAT32**, trop longs, ou contenant des caractères que
  le Deluge n'affiche pas ;
* **pads muets** dans un kit, oscillateurs silencieux dans un preset ;
* **XML réellement corrompu**, distingué des anomalies bénignes : un fichier
  à plusieurs racines est normal en firmware 2.x et n'est pas signalé ;
* **anomalies audio** : écrêtage, composante continue, silence, fréquences
  d'échantillonnage inhabituelles, batterie en stéréo ;
* **fichiers parasites** — `.DS_Store`, `._*`, `Thumbs.db`, corbeilles.

Une note sur 100 résume l'ensemble, et la réparation automatique traite les
codes dans un ordre sûr.

### Corriger, pas seulement signaler

Quatre de ces défauts se corrigent directement : **percussions en stéréo**
passées en mono, **fréquences inhabituelles** ramenées à 44,1 kHz,
**composante continue** retirée, **marge rendue** aux fichiers écrêtés. La
même mécanique sert au traitement par lot de la page *Échantillons*, avec en
plus la coupe du silence et les fondus.

Trois précautions, qui viennent de mesures sur une vraie carte :

* les presets bornent souvent leur échantillon **en nombre de trames**. Si un
  traitement change la longueur du fichier — rééchantillonnage, coupe du
  silence — ces bornes sont **remises à l'échelle** dans la même opération ;
* un **morceau** borne aussi ses échantillons en trames, et l'application ne
  réécrit jamais un morceau. Les fichiers qu'un morceau utilise sont donc
  **écartés** des traitements qui changent leur longueur, avec le motif
  affiché ;
* l'**écrêtage ne se répare pas.** Baisser le niveau rend de la marge pour le
  mixage ; les sommets rabotés à l'enregistrement ne reviennent pas.

Chaque fichier réécrit laisse son original dans
`_BACKUP/samplefix-<date>/`, d'où un bouton de restauration le remet en place
à l'octet près.

---

## Découper une boucle en kit

Un break, une boucle de batterie, une phrase : le bouton **Découper…** de la
page *Échantillons* en fait un kit où chaque pad joue une tranche.

Les coupes se placent **sur les attaques** détectées — avec un réglage de
sensibilité, et un alignement optionnel sur le tempo pour qu'un break rejoué
reste en place — ou **en divisions égales**, ce qui suffit sur une boucle
correctement coupée : 4 secondes à 120 BPM donnent 16 tranches de 250 ms, soit
la croche juste. Les coupes s'affichent sur la forme d'onde, numérotées, et un
clic écoute la tranche visée.

**Aucun fichier audio n'est dupliqué.** Les rangées du kit pointent toutes le
même échantillon, chacune avec ses propres bornes — exactement comme le font
déjà certains kits de la carte. Un export en fichiers séparés est proposé pour
qui veut des échantillons autonomes, mais il n'apporte rien au Deluge et
occupe le double de place.

---

## Retrouver un son par ressemblance

Sur 1 700 échantillons, le nom et le dossier ne suffisent plus. Sélectionnez
un son, cliquez **Sons proches**, et la liste ne montre plus que ce qui lui
ressemble, du plus proche au plus lointain, avec un pourcentage de proximité.

La comparaison porte sur huit mesures faites pendant l'analyse : brillance,
contenu grave et aigu, étalement du spectre, caractère bruité, rapport
crête/RMS et temps d'attaque. Les fréquences et les durées sont comparées en
rapports, pas en écarts — l'oreille entend un octave, pas un nombre de hertz.

Les voisins sont souvent d'un autre dossier, et c'est normal : un kick trouve
des toms, une caisse claire trouve des rim et des cowbells. C'est ce qui se
ressemble à l'oreille, pas ce qui est rangé ensemble.

Cette recherche demande que l'**analyse acoustique** ait tourné (une case dans
*Réglages*). Elle allonge la première analyse d'une carte — comptez trois
minutes pour 1 700 échantillons au lieu d'une — puis les analyses suivantes ne
relisent que ce qui a changé.

---

## Sortir un morceau du Deluge

Deux boutons sur la page *Morceaux*, qui n'écrivent jamais sur la carte :

**Morceau en MIDI** produit un fichier MIDI multipiste, une piste par clip,
les clips de batterie sur le canal des percussions. Toutes les pistes
démarrent au début : les clips du Deluge sont des boucles de la grille de
session, et le fichier ne dit pas à quel moment chacune se déclenche. Pour un
clip seul, le bouton *Clip en MIDI* existe toujours.

**Rassembler…** copie dans un dossier le morceau, les presets qu'il nomme et
les échantillons que ces presets lisent — avec l'arborescence d'origine. Le
dossier obtenu a la forme d'une carte : le recopier à la racine d'une autre
suffit à y jouer le morceau. De quoi archiver un morceau ou le donner sans
rien oublier. La liste complète s'affiche avant la première copie, et ce qui
manquerait est signalé.

---

## Écrire un morceau pour le Deluge

Chaque outil de création sait écrire ce qu'il a produit en **morceau du
Deluge** : un fichier neuf dans `SONGS`, que la machine charge comme les
autres, avec ses instruments, ses clips et, pour une esquisse, ses sections.

| Où | Bouton | Ce que contient le morceau |
|---|---|---|
| Outils › Théorie | **En morceau** | un clip par partie — accords, basse, arpège, mélodie, batterie — avec les sons entendus à l'écoute ; tout boucle ensemble dès PLAY |
| Outils › Rythme | **En morceau** | le motif affiché, joué par un kit de vos échantillons |
| Outils › Arrangement | **Esquisse en morceau** | une section du Deluge par section du modèle, chacune avec ses clips et son nombre de répétitions |
| Kits | **Motif en morceau** | le kit choisi, tel qu'il est sur la carte, et le motif d'essai |
| Générateur | **Essayer en morceau** | le son en situation : une phrase faite pour son rôle et la batterie du genre |
| Générateur › Kit | **Kit en morceau** | le kit construit et le rythme de son genre |
| Échantillons › Découper | **Écrire en morceau** | le kit des tranches et un clip qui rejoue la boucle |

Le nom est demandé, puis le plan s'affiche — fichier, instruments, clips,
échantillons absents — avant toute écriture. **Aucun fichier existant n'est
remplacé** : un nom déjà pris est numéroté.

Une esquisse se joue de deux façons : **PLAY** fait tourner l'intro en
boucle, et lancer la section suivante déroule toute la suite jusqu'à la fin ;
la vue arrangement joue le morceau entier d'un trait. Les parties qui se
répètent tiennent dans des clips courts — quatre mesures d'accords, une
mesure de batterie — comme on les construit sur la machine.

Le format est celui qu'écrit le firmware communautaire c1.2.1. Un kit ou un
preset ancien de la carte reçoit les conversions que la machine ferait en le
chargeant ; elles ont été comparées aux morceaux que vous avez enregistrés
sur la machine. **Ces morceaux n'ont pas encore été chargés sur un Deluge** :
le premier essai sur la machine reste à faire.

---

## Génération de presets

Le générateur part d'un **profil de genre** — 22 sont fournis, de la techno
de Détroit à la jungle, du dubstep au synthwave — et en tire des presets
cohérents : forme d'onde, désaccord, filtre, enveloppes, LFO, modulations,
effets. Chaque profil porte ses plages de tempo, ses gammes favorites et dix
rôles : basse, lead, nappe, pincé, clavier, accord bref, effet, bourdon,
arpège, cloche.

Deux garanties utiles :

* un preset généré **fait du son** — un oscillateur muet, un filtre fermé,
  une enveloppe sans attaque ni tenue sont rattrapés avant l'écriture ;
* l'**écoute est hors-ligne** : le preset est rendu par le moteur interne
  (`core/render.py`) et joué sur l'ordinateur, sans passer par le Deluge.

La même mécanique produit des kits de batterie complets, en choisissant parmi
les échantillons de la carte ceux qui correspondent aux rôles du genre.

---

## Organisation du code

```
main.py                  lancement, journal, écran de démarrage, garde-fous
delugeapp/
  config.py              réglages persistants et contexte applicatif
  core/                  tout le métier, sans aucune dépendance à Qt
    sdcard.py            seule porte vers la carte (FAT32 insensible à la casse)
    dxml.py              lecture et écriture tolérantes du XML Deluge
    model.py             sons, presets, kits, morceaux
    fixedpoint.py        entiers 32 bits du Deluge <-> valeurs lisibles
    wav.py analysis.py   audio : lecture, tempo, tonalité, catégorie
    db.py scan.py        index SQLite et analyse incrémentale
    deps.py organize.py  dépendances entre fichiers, plans de rangement
    health.py backup.py  diagnostic, réparation, sauvegarde
    genres.py synthgen.py kitgen.py   génération
    theory.py rhythm.py midifile.py   théorie, rythme, export MIDI
    songwriter.py        écriture de morceaux du Deluge depuis les outils
    midiport.py          MIDI et SysEx par winmm, sans dépendance
    midifollow.py        les 52 contrôleurs du mode MIDI Follow
    delugelink.py delugesysex.py      le lien vivant avec la machine
    delugefiles.py cardsync.py        la carte par USB, la copie de travail
    cardimport.py        envoyer au Deluge : du PC vers la carte
    render.py audio_out.py            moteur d'écoute et sortie audio
  ui/
    mainwindow.py        assemblage des neuf pages
    theme.py icons.py    identité graphique, icônes dessinées à la main
    art.py               treillis de circuits et pads du guide, au QPainter
    tasks.py             travaux longs hors du fil de l'interface
    songexport.py        parcours commun des boutons « en morceau »
    livewindow.py        « Deluge en direct » : écran, tempo, son sélectionné
    cardwork.py          la copie de travail tenue à l'image de la carte
    sendfiles.py         glisser-déposer, plan et copie vers le Deluge
    pages/               une page par domaine
    widgets/             façade (écran, pads de navigation), potentiomètre,
                         enveloppe, forme d'onde, pads, piano…
tests/
  test_core.py           646 tests du cœur
  test_ui.py             344 tests d'interface
  deluge_simule.py       un Deluge simulé, qui répond comme la vraie machine
SPEC.md                  contrat d'architecture : formats, règles, budgets
```

`core/` ne connaît pas Qt : il s'utilise tel quel depuis un script. `ui/` ne
touche jamais la carte directement — il passe par `core/`, et tout travail
long part dans un fil séparé pour que la fenêtre reste vivante.

---

## Tests

```bash
python -m unittest discover -s tests
```

990 tests, exécutés sur une vraie carte montée en lecture, et sur des copies
jetables pour tout ce qui écrit. **Ils n'écrivent jamais dans vos réglages** :
chaque module de test déplace la configuration dans un dossier temporaire
avant d'importer quoi que ce soit, et un test vérifie que ce déplacement a
bien eu lieu. Les tests d'interface se sautent d'eux-mêmes
si PyQt6 est absent ; sans serveur graphique, `QT_QPA_PLATFORM=offscreen`
suffit. **Aucun ne touche au Deluge branché** : les ports MIDI sont masqués,
et la liaison s'éprouve face à un Deluge simulé qui répond comme la vraie
machine, mesurée.

Ils couvrent aussi les deux détails qui ont coûté le plus cher : l'échelle
d'un câble de modulation vaut la **moitié** de celle des autres paramètres
(`0x40000000`), et le tempo se calcule sur **24** ticks par noire — ce qui
donne bien 120,000 BPM pour `DEFAULT.XML` — alors que les notes, elles,
comptent `96 << inputTickMagnitude` ticks par mesure.

---

## Notes de format

Mesuré sur une carte réelle — 1741 échantillons, 911 presets, 43 kits,
46 morceaux — et consigné dans `SPEC.md` :

* **deux dialectes XML** cohabitent : `<type>saw</type>` en firmware 2.x,
  `type="saw"` à partir de 3.0 ;
* trois anomalies réelles doivent être tolérées à la lecture : documents à
  plusieurs racines, `&` non échappé, octets non-UTF-8 ;
* les paramètres sont des **entiers 32 bits signés** : `0x80000000` au
  minimum, `0x00000000` au milieu, `0x7FFFFFFF` au maximum, affichés de 0 à
  50 — sauf les câbles de modulation, pleine échelle `0x40000000`, affichés
  de −50 à +50 ;
* la grille des notes compte **`96 << inputTickMagnitude` ticks par
  mesure** : 192 dans un morceau 3.x, 384 dans un morceau c1.2.1, où
  `length=1536` fait donc 4 mesures (les 24 ticks par noire sont ceux de
  l'horloge, pour le tempo) ;
* une note tient en 22 caractères hexadécimaux :
  `position(8) durée(8) vélocité(2) relâché(2) condition(2)`.
