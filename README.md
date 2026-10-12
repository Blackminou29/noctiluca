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
ouvre la page *Réglages* et affiche en haut « Aucune carte — cliquez pour
choisir ». Le chemin de la carte se change à tout moment, dans *Réglages* ou
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

Chaque page a **sa couleur**, prise dans les pads de la machine : ambre pour
le tableau de bord, cyan pour les échantillons, violet pour les presets, vert
pour les kits, bleu pour les morceaux, magenta pour le générateur, menthe
pour la boîte à outils, orange pour la santé, indigo pour les réglages.

Cette couleur se retrouve partout de la même façon : l'icône et le liseré du
bouton dans la barre de gauche, la bande sous l'en-tête, le pad à côté du
titre, les traits des panneaux. Un raccourci montre la couleur de **sa
destination** — le bouton « Sauvegarder la carte » du tableau de bord est
orange parce qu'il mène à la page *Santé*, et il y mène **directement sur
l'onglet des sauvegardes**.

Un bouton éteint attend quelque chose de vous : la plupart du temps, une
ligne choisie dans la liste.

---

## Brancher le Deluge

Reliez le Deluge au PC en USB : la pastille **Deluge** de la barre du haut
passe au vert, et l'application peut alors travailler avec la machine.

| | |
|---|---|
| **Écouter pour de vrai** | les presets sonnent sur le Deluge, avec son moteur, au lieu de l'approximation calculée par l'ordinateur |
| **Régler à distance** | 52 paramètres de l'instrument sélectionné, par le mode MIDI Follow du firmware communautaire |
| **Envoyer un motif** | le motif d'essai d'un kit part en mesure, avec l'horloge MIDI |
| **Tout éteindre** | un bouton de secours qui relâche toutes les notes, sur tous les canaux |

Deux choses à savoir :

* **le Deluge joue l'instrument sélectionné sur lui.** Aucun message MIDI ne
  permet de lui dire « charge ce preset » ; c'est une limite de la machine ;
* l'écoute sur le Deluge ne s'active pas toute seule. Elle se coche dans
  *Réglages › Deluge branché* : envoyer du son dans une machine reliée à un
  ampli ne doit pas être une surprise.

La correspondance des contrôleurs est lue dans `MIDIFollow.XML`, à la racine
de votre carte. Si vous la modifiez sur le Deluge, l'application suit.

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
    render.py audio_out.py            moteur d'écoute et sortie audio
  ui/
    mainwindow.py        assemblage des neuf pages
    theme.py icons.py    identité graphique, icônes dessinées à la main
    tasks.py             travaux longs hors du fil de l'interface
    pages/               une page par domaine
    widgets/             potentiomètre, enveloppe, forme d'onde, pads, piano…
tests/
  test_core.py           233 tests du cœur
  test_ui.py             147 tests d'interface
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

576 tests, exécutés sur une vraie carte montée en lecture, et sur des copies
jetables pour tout ce qui écrit. **Ils n'écrivent jamais dans vos réglages** :
chaque module de test déplace la configuration dans un dossier temporaire
avant d'importer quoi que ce soit, et un test vérifie que ce déplacement a
bien eu lieu. Les tests d'interface se sautent d'eux-mêmes
si PyQt6 est absent ; sans serveur graphique, `QT_QPA_PLATFORM=offscreen`
suffit.

Ils couvrent aussi les deux détails qui ont coûté le plus cher : l'échelle
d'un câble de modulation vaut la **moitié** de celle des autres paramètres
(`0x40000000`), et le tempo se calcule sur **24** ticks par noire — ce qui
donne bien 120,000 BPM pour `DEFAULT.XML`.

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
* la grille rythmique compte **24 ticks par noire**, 96 par mesure ;
  `length=1536` fait donc 16 mesures ;
* une note tient en 22 caractères hexadécimaux :
  `position(8) durée(8) vélocité(2) relâché(2) condition(2)`.
