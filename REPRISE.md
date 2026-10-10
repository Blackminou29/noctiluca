# Point d'étape — Deluge Companion

**Dernière mise à jour :** 10 octobre 2026
**État :** **application terminée et fonctionnelle.** Les cinq phases sont écrites,
`python main.py` démarre, 380 tests au vert.
**Objet :** ce qui a été construit, ce qui a été mesuré, et ce qu'il faut savoir avant
de modifier quoi que ce soit.

---

## 1. Ce qu'est le projet

Application Python (PyQt6) accompagnant l'utilisation d'un Synthstrom Deluge :
gestion complète de la carte SD (échantillons, presets, kits, morceaux), générateur de
presets de synthé par genre musical ou aléatoire, et boîte à outils de production
électronique. Interface en français, identité visuelle reprise du *Guide du Deluge OLED*.

**Le contrat d'architecture complet est dans [`SPEC.md`](SPEC.md)** : signatures exactes de
tous les modules, format XML du Deluge, palette graphique, description de chacune des
9 pages. C'est le document de référence.

> `SPEC.md` contient désormais **trois encadrés « Correction mesurée »** (§1.6, §4.5, §4.9).
> Ce sont des points où la rédaction initiale était fausse et où la mesure sur la carte a
> tranché. Ne pas revenir en arrière dessus : voir §2 ci-dessous.

---

## 2. Faits techniques acquis (mesurés sur `SDCARD Deluge`)

- **Volume réel utile** : **1 741 échantillons**, **911 presets de synthé**, **43 kits**,
  **46 morceaux** — soit 2 741 fichiers et 1,33 Gio d'audio.
  ⚠️ La carte contient *en plus* 8 491 `.wav` bruts si l'on compte tout : la différence est
  faite de **2 812 fichiers AppleDouble `._*`** et de **3 938 fichiers dans les corbeilles**
  (`.Trashes`, `.Trash-59016`). Le filtrage de `core/sdcard.py` est donc indispensable, et
  le chiffre de « 8 491 échantillons » annoncé dans les notes précédentes était un comptage
  brut, pas la bibliothèque réelle.
- **Deux dialectes XML coexistent** : firmware 2.x écrit `<type>saw</type>`,
  firmware 3.0+ écrit `type="saw"`. Lire les deux, **préserver celui d'origine** en écriture.
- **Le parseur tolérant absorbe tout** : sur les 1 000 XML de la carte (954 presets/kits +
  46 morceaux), l'analyse complète rapporte **0 erreur**. Les trois anomalies traitées sont
  les documents multi-racines, les `&` non échappés et les octets non-UTF-8.
- **Notes décodées** : `noteDataWithLift` = 22 caractères hexadécimaux par note, dans l'ordre
  `pos(8) length(8) velocity(2) lift(2) condition(2)` — **le lift précède la condition**,
  contrairement à ce qu'annonçait la première version de la SPEC. Mesure : sur les 403 notes
  de la carte qui en portent, l'octet 18‑20 vaut `0x40` à 100 % (c'est le lift, défaut 64) et
  l'octet 20‑22 vaut `0x14` à 92,8 % (c'est la condition « toujours »).
  Validation croisée : les 1 753 notes de la carte tombent **toutes** dans les bornes de leur
  clip, avec une longueur > 0 et une vélocité dans 0‑127.
- **Tempo** : `BPM = 44100 × 60 / (samples_par_tick × 24)`, avec `timerTickFraction` lu en
  **non signé**. La première version de la SPEC divisait par 48 et lisait la fraction en
  signé ; les deux étaient faux. Preuve : `DEFAULT.XML` donne alors exactement **120 BPM**
  (défaut d'usine) et les 46 morceaux donnent **tous** un BPM entier, entre 69 et 124.
- **La casse des chemins n'est pas fiable** (`SAMPLES/Multisamples` contre `MULTISAMPLES`).
  Sur Windows, le système étant lui-même insensible à la casse, cela ne change rien en
  pratique ; la résolution insensible à la casse de `SDCard.resolve_sample()` reste nécessaire
  pour lire la carte depuis macOS ou Linux, et accélère le travail grâce à son cache de
  dossiers.
- **125 références d'échantillons sont réellement cassées** : les presets de `SYNTHS/rephazer/`
  pointent vers `SAMPLES/REPHAZER/X-SELECTED/…`, dossier **absent** de la carte. Ce ne sont
  pas des faux positifs.
- **379 échantillons (373 Mio) ne sont utilisés par rien.**
- **La carte ne contient aucun doublon**, et c'est un point délicat : voir §4.9 de la SPEC.
  Une empreinte partielle déclarait trois multi-échantillons identiques alors qu'ils
  diffèrent sur 1 407 blocs sur 1 722. **Aucune suppression ne doit jamais être proposée sur
  la foi d'une empreinte partielle.**
- **Paramètres en virgule fixe** : entiers 32 bits signés, `0x80000000` = minimum,
  `0x00000000` = milieu, `0x7FFFFFFF` = maximum, affichés 0–50 sur la machine.
- **Exception : les câbles de modulation.** L'échelle pleine d'un `patchCable` est
  `0x40000000`, soit **la moitié** de celle des autres paramètres. Mesuré sur les
  7 025 câbles de la carte : aucun ne dépasse cette valeur et 1 925 s'y arrêtent exactement.
  Toujours passer par `PatchCable.display()` / `amount_from_display()`, jamais par
  `fixedpoint.to_display` directement — l'erreur divisait toutes les profondeurs par deux.

---

## 3. État de la construction

| Phase | Contenu | État |
|---|---|---|
| **1 — Fondations** | `fixedpoint`, `dxml`, `sdcard`, `model`, `wav`, `audio_out`, `config`, `theme`, `icons`, `tasks` | **terminée** |
| **2 — Services** | les 21 modules du noyau : `db`, `scan`, `analysis`, `deps`, `organize`, `health`, `backup`, `genres`, `synthgen`, `kitgen`, `theory`, `rhythm`, `midifile`, `render` | **terminée** |
| **3 — Widgets** | `common`, `padgrid`, `waveform`, `envelope`, `knob`, `piano`, `filtercurve` — 20 classes | **terminée** |
| **4 — Pages** | les 9 pages : tableau de bord, échantillons, presets, kits, morceaux, générateur, outils, santé, réglages | **terminée** |
| 5 — Intégration | `mainwindow`, `main.py`, README, captures de contrôle | en attente |

### Fichiers écrits

```
SPEC.md                           contrat d'architecture (référence)
delugeapp/config.py          388  Settings + AppContext, persistance JSON
delugeapp/core/fixedpoint.py 212  conversions virgule fixe Deluge
delugeapp/core/dxml.py       744  lecture/écriture XML tolérante (les 3 anomalies)
delugeapp/core/sdcard.py     495  parcours de la carte, résolution insensible à la casse
delugeapp/core/model.py     1862  Sound/Osc/Kit/Song/Clip/Note <-> XML
delugeapp/core/wav.py       1094  lecteur/écrivain WAV + AIFF sans dépendance
delugeapp/core/audio_out.py  553  lecture d'aperçu (sounddevice / winsound / muet)
delugeapp/core/db.py         814  index SQLite + migration de schéma non destructive
delugeapp/core/scan.py       576  analyse de la carte, incrémentale et interruptible
delugeapp/core/analysis.py   731  tempo, tonalité, hauteur, niveaux, classement percussions
delugeapp/core/deps.py       396  graphe des dépendances, réaffectation des références
delugeapp/core/organize.py   648  plans de réorganisation (simulation puis application)
delugeapp/core/health.py     868  22 contrôles de santé + réparation automatique
delugeapp/core/backup.py     498  sauvegarde, comparaison, restauration
delugeapp/core/genres.py     706  22 profils sonores par genre, surchargés par rôle
delugeapp/core/synthgen.py   733  générateur de presets : genre, hasard, mutation, morphing
delugeapp/core/kitgen.py     249  assemblage de kits depuis la bibliothèque
delugeapp/core/theory.py     611  25 gammes, 28 accords, progressions, Camelot
delugeapp/core/rhythm.py     523  euclidien, grooves, swing, tables de délai
delugeapp/core/midifile.py   284  écriture MIDI standard, stdlib seule
delugeapp/core/render.py     817  moteur d'écoute hors-ligne (numpy seul)
delugeapp/ui/theme.py        898  palette et feuille de style complète
delugeapp/ui/icons.py        566  36 icônes dessinées au QPainter + emblème
delugeapp/ui/tasks.py        253  Worker/run_task — travaux longs hors du fil UI
delugeapp/ui/widgets/
  common.py                  807  panneaux, tuiles, recherche, RowTableModel
  padgrid.py                 390  grille de pads, vignette de morceau, séquenceur
  waveform.py                385  forme d'onde : sélection, zoom, zones
  envelope.py                299  éditeur ADSR à quatre poignées
  knob.py                    242  encodeur rotatif doré
  piano.py                   262  clavier 3 octaves, surlignage de gammes
  filtercurve.py             323  réponse de filtre + spectre, axe log
delugeapp/ui/pages/
  base.py                    216  socle : rempart, état vide, raccourcis
  settings.py                613  chemin de la carte, audio, analyse, accent
  dashboard.py               512  tuiles, analyse, santé, répartition
  samples.py                 549  table filtrable, aperçu, étiquettes
  synths.py                  588  détail d'un preset, écoute par rendu
  kits.py                    424  rangées, rangées cassées, motif d'essai
  songs.py                   480  vignette, clips, dépendances, export MIDI
  generator.py               766  génération, variations, lots, kits
  toolbox.py                 824  théorie, rythme, calculs, Camelot, mémo
  health.py                  850  diagnostic, réparation, doublons, sauvegardes
tests/test_core.py          3107  233 tests du noyau, sans Qt
tests/test_ui.py            1428  97 tests d'interface, hors écran
```

### Mesures de performance (carte réelle, 2 741 fichiers)

| Opération | Durée |
|---|---|
| Analyse complète avec empreintes | **1,9 à 7,6 s** (selon le cache disque) |
| Analyse incrémentale, rien de changé | **0,1 s** (2 741 fichiers sautés) |
| Lecture des 46 morceaux | 0,1 s |

L'objectif de la SPEC (« moins de 3 minutes ») est largement tenu.

---

## 3 bis. Ce que l'application trouve sur la carte de l'utilisateur

Mesuré en simulation, sans rien modifier. C'est le bilan que la page Santé affichera :

| Constat | Chiffre | Action possible |
|---|---|---|
| Références d'échantillons cassées | **125** | **Toutes réparables** : les presets `SYNTHS/rephazer/` cherchent `SAMPLES/REPHAZER/X-SELECTED/…` alors que les fichiers sont dans `SAMPLES/MULTISAMPLES/REPHAZER X-SELECTED/…`. `deps.relink_many()` corrige les 10 presets en un passage. |
| Fichiers parasites | **1 564** (6,2 Mio) | 1 537 AppleDouble `._*` + 27 `.DS_Store`. Vérifié : aucun fichier audio ou XML réel n'est visé. |
| Échantillons inutilisés | **379** (373 Mio) | Archivables dans `_UNUSED/` (déplacés, jamais supprimés). |
| Doublons | **0** | Aucun, après vérification octet pour octet. L'empreinte partielle en annonçait 1 à tort. |
| Noms incompatibles FAT32 | **2** | `Nils says....XML` et `04-Nils says....XML` finissent par un point. |
| Échantillons écrêtés | **35** | Signalement seulement. |
| Échantillons à offset continu | **17** | Signalement seulement. |
| Échantillon muet | **0** | Le code `SILENT_SAMPLE` existe (crête < 1e-4) mais aucun fichier de la carte ne le déclenche. |
| Échantillon très volumineux | **1** | `BIG_SAMPLE`, au-delà de 20 Mio : ralentit le chargement sur la machine. Signalement seulement. |
| XML illisibles | **0** | Le parseur tolérant absorbe les 1 000 fichiers. |
| XML réellement abîmés | **6** | `&` non échappé, octets non UTF-8, balise mal fermée. À ne pas confondre avec les **134** documents multi-racines, qui sont la forme *normale* du firmware 2.x et ne sont donc **pas** signalés. |
| Percussions en stéréo | **58** | Passer en mono libérerait ~30 Mio. |
| Fréquences inhabituelles | **89** | Hors 44,1/48 kHz : converties à la lecture par la machine. |
| Fichiers non audio dans SAMPLES | **4** | Fichiers `.reapeaks` laissés par Reaper. |

**Note de santé de la carte : 85/100**, analyse acoustique comprise (76 s pour les
1 741 échantillons). Sans elle — `scan_card(analyze=False)` — les contrôles d'écrêtage et
d'offset continu ne peuvent pas se prononcer et la note monte à **89/100** : c'est une
absence de mesure, pas une carte en meilleur état. Après réparation automatique des
références cassées et des parasites, elle passe à **100/100** (vérifié sur une copie).

Les échantillons les plus utilisés sont les percussions 808 (`808 Kick.wav`, `808 Snare.wav`,
`808 Closed hihat.wav`… : 28 usages chacun).

---

## 3 ter. Garanties du générateur de presets

Vérifié par les tests, sur **2 200 presets** (22 genres × 10 rôles × 10 graines) :

- **aucun preset muet.** Volume général, oscillateur audible, enveloppe d'amplitude et
  ouverture du filtre sont contrôlés avant que le preset soit rendu (`_ensure_audible`).
  Attention : `wavetable` compte comme un type lu depuis la carte (`Osc.is_sample`), donc
  **muet sans fichier** — le générateur l'écarte quand aucun échantillon n'est fourni.
- **reproductibilité stricte.** Une graine redonne le même son, même si un autre module
  appelle `random.seed()` entre-temps : le tirage passe par une instance `random.Random`
  propre, jamais par le hasard global. Couvert par
  `TestSynthGen.test_n_utilise_pas_le_hasard_global`.
- **XML complet.** Comparé à un vrai preset de la carte en dialecte « attributs »
  (`SYNTHS/acid/TB01.XML`, firmware 3.1.5) : **aucun paramètre présent chez le preset réel
  n'est absent du preset généré**. L'aller-retour écriture/lecture est stable à l'octet.
- **les six curseurs ont un effet mesurable** (brillance, mouvement, espace, saleté,
  largeur, complexité), et le genre comme le rôle influencent le nom : sans cela, une série
  entière de presets s'appelait « VELVET ».

---

## 3 quater. Boîte à outils de composition

Trois modules entièrement arithmétiques : ni carte, ni audio, ni numpy, ni Qt.

| Module | Contenu | Vérifications |
|---|---|---|
| `theory` | 25 gammes, 28 accords, 12 ambiances de progression, cycle des quintes, Camelot | **Tous** les noms de notes se relisent sur 24–108 dans les deux langues ; accords diatoniques conformes aux manuels (`I ii iii IV V vi vii°` en majeur, `i ii° III iv v VI VII` en mineur) ; codes Camelot vérifiés sur la vraie roue (C=8B, Am=8A, F#m=11A) |
| `rhythm` | euclidien (Bjorklund), 11 motifs de genre, 9 grooves MPC, swing, humanisation, tables de délai | **`E(3,8)` = `x..x..x.`** (exigence SPEC §7) et `E(5,8)` = `x.xx.xx.` ; le nombre de coups est exact pour toutes les combinaisons jusqu'à 32 pas ; 1/4 à 120 BPM = 500 ms ; `bars_to_ticks(16)` = 1536 |
| `midifile` | SMF type 1, stdlib seule | Relu par **un analyseur indépendant** écrit dans les tests : en-tête, blocs, délais en longueur variable, aucune note laissée allumée, aucun octet superflu. Un vrai clip de la carte (87 notes) ressort avec ses 87 notes et son tempo |

**Contrainte du Deluge à ne pas oublier :** `<modeNotes>` veut **exactement sept**
intervalles, parce que l'écran réserve sept rangées de pads par octave.
`theory.deluge_mode_notes()` complète les gammes de cinq notes et réduit celles de huit ;
c'est vérifié pour les 25 gammes.

---

## 3 quinquies. Moteur d'écoute

`core/render.py` permet d'entendre un preset avant de l'écrire sur la carte. Objectif de la
SPEC §4.21 : « plausible, pas exact », **2,5 s en moins de 400 ms**.

| Mesure | Résultat |
|---|---|
| Rendu de 2,5 s, cas courant | **48 ms** |
| Rendu de 2,5 s, pire cas (unisson 8, nappe, tous effets) | **71 ms** |
| 88 combinaisons genre × rôle | 0 rendu muet, 0 saturation, 0 valeur non finie |
| Hiérarchie spectrale | basse 999 Hz < nappe 4 905 Hz < lead 7 282 Hz |

Trois choix techniques imposés par le budget, à ne pas « simplifier » par la suite :

- **tables d'onde à bandes limitées par octave**, lues par interpolation — l'addition
  d'harmoniques coûterait dix fois plus pour 12 voix d'unisson ;
- **filtre appliqué par blocs en fréquentiel** avec recouvrement de moitié : une récursion
  échantillon par échantillon en Python consommerait à elle seule tout le budget ;
- **réverbération par convolution FFT** d'une réponse impulsionnelle synthétique.

⚠️ Le centroïde spectral en fonction de la coupure est une **courbe en U**, pas une droite :
en dessous de la fondamentale jouée, le filtre coupe la fondamentale elle-même, le niveau
s'écroule de 30 dB et le centroïde remonte faute de mieux. Tout test de filtre doit donc
comparer des coupures situées **au-dessus** de la note jouée.

---

## 3 sexies. Widgets : ce qu'il faut savoir avant de bâtir les pages

| Widget | À retenir |
|---|---|
| `RowTableModel` | **Le contrat de colonne sépare l'extraction de la mise en forme** : `(libellé, extracteur, largeur, alignement[, formateur])`. L'extracteur rend la valeur **brute**, le formateur l'habille. Si l'extracteur formate lui-même, le tri se fait sur le texte et « 99,9 Kio » passe avant « 988,0 Kio ». |
| `configure_table` / `sorted_proxy` | Règlent le tri sur `EditRole`. Un `QSortFilterProxyModel` trie sur `DisplayRole` par défaut : sans ce réglage, toutes les colonnes numériques se trient alphabétiquement. |
| `SearchBar` | Signal différé de 250 ms, immédiat sur Entrée. Ne pas brancher `textChanged` directement sur une requête. |
| `PadGrid` | Origine **en haut à gauche**, contrairement à la machine. Tout est tracé dans un seul widget : ne pas créer un widget par pad. |
| `WaveformView` | Reçoit l'enveloppe de `wav.peaks()`, **jamais** le signal entier — un échantillon de la carte pèse jusqu'à 52 Mio. |
| `Knob`, `EnvelopeEditor` | Travaillent dans l'échelle de l'écran du Deluge (0–50), pas en pourcentage. Conversion par `fixedpoint.from_display`. |
| `FilterCurve` | Réutilise `render._response` et `render._cutoff_hz` : la courbe affichée est exactement celle que le rendu applique. Vérifié : à 1,4 kHz de coupure et 24 dB/octave, 10 kHz mesure −68 dB, soit la pente théorique. |

---

## 3 septies. Pages : ce qu'il faut savoir

Toutes héritent de `ui/pages/base.py`, qui apporte le rempart autour de `refresh`
(SPEC §6.3), l'état vide sans carte (SPEC §6.1), `Page.guard()` pour les gestionnaires de
signaux, et `Page.run()` pour les travaux longs.

| Page | Particularité |
|---|---|
| `settings` | **Seule page utilisable sans carte** (`NEEDS_CARD = False`), puisque c'est elle qui en désigne une. Valide le chemin au fil de la saisie. |
| `dashboard` | L'analyse part d'ici, dans un fil séparé, interruptible. **N'affiche aucun score de santé avant la première analyse** : sur un index vide les contrôles ne trouvent rien et la note monterait à 98/100. |
| `samples` | 1 741 lignes en 130 ms grâce à `RowTableModel`. Recherche différée de 250 ms. |
| `synths`, `kits` | L'écoute passe par `render`, dans un fil séparé. Les rangées de kit affichent la présence réelle de l'échantillon. |
| `songs` | **Lecture seule**, comme `core.model.Song`. Signale les presets et échantillons manquants, qu'un morceau ne révèle pas sur la machine. |
| `generator` | La graine est affichée et modifiable : c'est elle qui rend un son reproductible. |
| `toolbox` | Six onglets, tous indépendants de la carte sauf la recherche par tonalité. |
| `health` | **Aucune opération ne s'exécute sans que `PlanDialog` ait montré la liste exacte** (SPEC §0.2). |

> ⚠️ **Un `QThread` encore en cours à la fin du processus le fait planter.** Vérifié : le
> programme meurt pendant la destruction des objets Qt. `ui/tasks.py` tient donc un registre
> des travaux actifs, et **`mainwindow.closeEvent` appelle `tasks.stop_all()`** avant de
> rendre la main. C'est fait, et c'est couvert par
> `TestMainWindowFermeture.test_fermeture_pendant_un_travail_arrete_les_fils` : fermer la
> fenêtre pendant une analyse laisse maintenant `tasks.active_count() == 0` et le processus
> sort avec le code 0. **Ne pas retirer cet appel.**

> ⚠️ **`Settings.backup_path` est une méthode, pas une propriété.** L'oubli produisait un
> `TypeError` au moment de sauvegarder — il était présent dans trois pages à la fois.

---

## 3 octies. La fenêtre principale et le lancement

`ui/mainwindow.py` (668 lignes) assemble les neuf pages ; `main.py` (278 lignes) démarre
l'ensemble. Ce qu'il faut savoir avant d'y toucher :

| Point | Détail |
|---|---|
| **Pages paresseuses** | Une page n'est construite qu'à son premier affichage. Au démarrage, une seule existe. En construire neuf allongerait le lancement sans que l'utilisateur en voie plus d'une. |
| **Câblage par nom de signal** | `_connect_page()` branche `navigateRequested`, `scanFinished`, `cardModified`, `presetSaved`, `cardChanged`, `accentChanged`, `resetIndexRequested` **s'ils existent**, sans supposer leur présence. Ajouter un signal à une page suffit donc à le brancher. |
| **Clé de navigation** | `DashboardPage` → `"Dashboard"` : le nom de la classe sans « Page ». Une clé inconnue est ignorée, pas fatale. |
| **Choix de la carte différé** | `_check_card()` part 150 ms après l'affichage, pour que la fenêtre soit visible derrière la boîte de dialogue. |
| **Démarrage sans carte** | Cas normal (SPEC §6.1) : la fenêtre s'ouvre sur les réglages avec « Indiquez l'emplacement de votre carte SD pour commencer. ». Vérifié dans les quatre cas : aucune carte, chemin invalide, dossier sans arborescence Deluge, carte réelle. |
| **`QSettings` natif** | La géométrie, la page courante et l'état de la barre latérale vont dans le registre Windows. **Les tests détournent `_settings_store()` vers un fichier `.ini` jetable** — sans quoi ils écraseraient les réglages réels. |
| **Rempart sur les menus** | `_safely()` entoure chaque action de menu : une exception devient un message dans la barre d'état (SPEC §6.3). |
| **`main.py` tolère tout sauf l'index** | Carte absente, chemin absurde, périphérique audio manquant, dossier de journal en lecture seule : chacun est rattrapé et l'application s'ouvre quand même. Seul un index illisible arrête le démarrage, avec un message explicite. |
| **Hook d'exception** | `_install_excepthook()` envoie toute erreur non rattrapée dans le journal **et** dans une boîte avec le détail dépliable. Sans lui, une erreur dans un gestionnaire Qt disparaît sur une sortie d'erreur que personne ne lit quand l'application est lancée depuis une icône. |

> ⚠️ **Un test de page peut écraser les réglages réels de l'utilisateur.** Plusieurs pages
> appellent `ctx.save()`, et `config.save_settings()` écrit dans `config.SETTINGS_PATH`,
> c'est-à-dire `%APPDATA%/DelugeCompanion/settings.json`. C'est arrivé : après une série de
> tests, le `sd_path` enregistré pointait vers un dossier temporaire effacé depuis.
> `PageCase.setUp` détourne donc `config.CONFIG_DIR` **et** `config.SETTINGS_PATH` vers le
> bac à sable du test, et `TestMainWindowCarte.test_aucune_ecriture_dans_les_reglages_reels`
> compare l'octet près le vrai fichier avant et après. Toute nouvelle classe de test qui
> construit un `AppContext` doit hériter de `PageCase`, ou refaire ce détournement.

---

## 4. Comment reprendre

`SPEC.md` est auto-suffisant. Chaque module y a ses signatures exactes. L'ordre des
dépendances est celui du tableau du §3. Pour la suite, demander :

> Lis `SPEC.md` et implémente `<liste de fichiers>` en respectant les signatures à la lettre.
> Vérifie sur la vraie carte `SDCARD Deluge`.

**Tout est écrit.** Les cinq phases sont terminées : 21 modules de noyau, 7 widgets,
9 pages, la fenêtre principale et le point d'entrée : **25 156 lignes de code**
et **5 310 lignes de tests**. **380 tests au vert** (233 pour le noyau, 147 pour l'interface).

### Lancer et vérifier

```bash
cd "C:\Users\sebas\Desktop\Informatique\Deluge app"
PY="C:/Users/sebas/AppData/Local/Programs/Python/Python313/python.exe"
"$PY" main.py                                # l'application
"$PY" -m unittest discover -s tests -t .     # 380 tests, doit afficher OK
```

Les tests d'interface ont besoin d'un affichage ; sans serveur graphique,
`QT_QPA_PLATFORM=offscreen` suffit. Ils durent environ 45 secondes au total.

### Si le travail reprend

Il n'y a plus de phase à écrire. Les pistes qui restent ouvertes, par ordre d'intérêt :

1. **Écriture des morceaux.** `core.model.Song` est en lecture seule par choix (voir §6).
   L'ouvrir en écriture demanderait de prouver, sur les 46 morceaux de la carte, qu'un
   aller-retour lecture/écriture est stable à l'octet — ce n'est pas démontré aujourd'hui.
2. **Export de kits vers un autre format** (Ableton, MPC), à partir de `core.kitgen`.
3. **Conversion en mono des 58 percussions stéréo** : le diagnostic les signale déjà,
   la conversion elle-même n'est pas implémentée.
4. **Empaquetage** (`PyInstaller`) pour lancer l'application sans Python installé.

Dans tous les cas : `SPEC.md` reste le contrat, et la règle du §6 ne se négocie pas.

---

## 5. Environnement

- **Python :** `C:\Users\sebas\AppData\Local\Programs\Python\Python313\python.exe`
  (PyQt6 6.11, numpy 2.2.6, matplotlib, sounddevice, Pillow installés et vérifiés).
- **Dépendances obligatoires :** PyQt6 et numpy, déclarées dans `requirements.txt`.
  `sounddevice` est optionnel et protégé par `try/except ImportError` : sans lui,
  l'application démarre mais les boutons d'écoute restent inactifs. `matplotlib` et
  `Pillow` sont installés sur la machine mais **ne sont utilisés par aucun module** —
  ne pas les ajouter aux dépendances.
- **Carte SD de travail :** `SDCARD Deluge/` — **exclue de git** (`.gitignore`).
  Le chemin est modifiable depuis les réglages de l'application.
- **Index SQLite :** `%APPDATA%/DelugeCompanion/` — supprimable sans rien perdre d'autre
  que le temps d'une nouvelle analyse. Tags, notes et favoris survivent à une réanalyse
  (`Library.clear()` les conserve, `clear_all()` les efface).

---

## 6. Précaution

Aucun code n'écrit sur la carte SD sans confirmation : les opérations de réorganisation sont
conçues en *simulation par défaut* (`apply=False`) et toute écriture XML crée une sauvegarde
`.bak` horodatée. `Song` est **volontairement en lecture seule** : l'application ne réécrit
jamais un morceau, pour ne pas risquer le travail de l'utilisateur. Cette règle est au §0 de
`SPEC.md` et doit être maintenue par toute reprise.
