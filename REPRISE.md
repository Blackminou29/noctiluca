# Point d'étape — Deluge Companion

**Dernière mise à jour :** 11 octobre 2026 (seconde passe : lien MIDI)
**État :** **application terminée et fonctionnelle.** Les cinq phases sont écrites,
`python main.py` démarre, **576 tests au vert**. Quatre modules se sont ajoutés
depuis : `core/samplefix.py` **corrige** les défauts audio que le diagnostic ne
savait que signaler, `core/slicer.py` **découpe une boucle en kit**,
`core/similarity.py` **retrouve un son par ressemblance**, et
`core/songpack.py` **sort un morceau du Deluge**. Une passe de nettoyage a
suivi : voir §3 terdecies. **L'interface a ensuite été entièrement reprise**
à la demande de l'utilisateur : voir §3 quindecies.
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
| Échantillons écrêtés | **35** | `samplefix.plan_headroom()` rend de la marge. **L'écrêtage lui-même ne se répare pas** : les sommets rabotés ne reviennent pas. |
| Échantillons à offset continu | **17** | `samplefix.plan_remove_dc()` les recentre. |
| Échantillon muet | **0** | Le code `SILENT_SAMPLE` existe (crête < 1e-4) mais aucun fichier de la carte ne le déclenche. |
| Échantillon très volumineux | **1** | `BIG_SAMPLE`, au-delà de 20 Mio : ralentit le chargement sur la machine. Signalement seulement. |
| XML illisibles | **0** | Le parseur tolérant absorbe les 1 000 fichiers. |
| XML réellement abîmés | **6** | `&` non échappé, octets non UTF-8, balise mal fermée. À ne pas confondre avec les **134** documents multi-racines, qui sont la forme *normale* du firmware 2.x et ne sont donc **pas** signalés. |
| Percussions en stéréo | **58** | `samplefix.plan_mono()` les passe en mono. Mesuré sur copie : **9,9 Mio libérés en 0,8 s**, longueurs inchangées. |
| Fréquences inhabituelles | **89** | Hors 44,1/48 kHz : converties à la lecture par la machine. `samplefix.plan_standard_rate()` les ramène à 44,1 kHz — en recalant les bornes des presets. |
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

## 3 unvicies. Lisibilité et petits écrans : encore deux mesures

### Le contraste

Calculé, pas apprécié à l'œil. Le texte principal était très au-dessus
(13 à 17 pour un seuil de 4,5), mais les **petits textes gris** — ceux qui
expliquent — tombaient à 3,78 sur une surface relevée, et deux couleurs de
page à 4,26 et 3,51 quand elles servaient de titre.

Corrigé en séparant la couleur du **texte** de celle du **décor**
(``TEXT_SOFT``), et par ``readable()``, qui éclaircit une teinte juste assez.
Cinq tests gardent la mesure.

### Une coquille a dégradé toute l'apparence en silence

En ajoutant ``TEXT_SOFT`` au thème, j'ai oublié de le déclarer dans la table
d'injection du QSS. Résultat : ``KeyError``, rempart, **style minimal**.
L'application démarrait grise et plate, et seule une ligne de journal le
disait. Deux tests vérifient désormais que la feuille se construit vraiment,
pour quatre accents différents.

### Les petits écrans

Mes captures font 1 440 px. Les largeurs de colonnes avaient été réglées
dessus, et personne n'avait regardé en dessous :

| fenêtre | listes qui débordent |
|---|---|
| 1 440 × 900 | aucune |
| 1 366 × 768 | 2 sur 4 |
| 980 × 640 | 4 sur 4 |

Trois corrections : les colonnes les moins utiles s'effacent et reviennent ;
l'aperçu, dont le minimum de 346 px réduisait la liste à **une ligne**,
devient défilant (minimum 131 px) ; la barre d'actions se replie sur ses
icônes au lieu de couper ses mots.

### Le repliement a cassé le test de couverture, et c'est tant mieux

En vidant le texte des boutons, le repliement a rendu introuvables les
explications rangées sous leur libellé : le test « aucune explication
orpheline » a signalé onze fantômes. Il avait raison de le dire — une
commande sans nom visible **et** sans clé n'est plus rattachable à son
aide.

Corrigé en donnant au bouton la mémoire de son nom : ``libelleComplet``, une
propriété Qt posée au premier repliement, que le registre d'aide sait lire.
À noter : l'échec n'apparaissait **que dans la suite complète**, parce que
la plateforme « offscreen » n'a pas de police et replie donc toujours.

**Le seuil de repliement ne se teste pas sous « offscreen »** : cette
plateforme n'a aucune police, donc aucune largeur de texte juste. Le test
porte sur le mécanisme ; le seuil est mesuré à la main (tous les libellés
jusqu'à 1 280 px, seul le principal en dessous).

---

## 3 vicies. Rendre l'interface intuitive : ce qui se mesure

> « Le logiciel doit être très intuitif à utiliser. »

### 102 commandes sur 174 n'expliquaient rien

Première mesure, avant d'écrire quoi que ce soit : un script parcourt les
neuf pages, ouvre tous les onglets, et compte les commandes **sans
infobulle**, en écartant les rouages internes de Qt (boutons de défilement
d'une barre d'onglets, coin d'un tableau).

| page | commandes | muettes |
|---|---|---|
| Boîte à outils | 29 | **28** |
| Presets | 8 | 7 |
| Kits | 9 | 8 |
| Santé | 15 | 12 |
| Réglages | 31 | 16 |
| … | | |
| **total** | **174** | **102 (59 %)** |

Dont quatre qui **écrivent sur la carte** sans un mot : « Supprimer les
doublons », « Relier automatiquement », « Archiver dans _UNUSED »,
« Restaurer ».

### Un registre, pas cent retouches

`ui/aide.py` tient toutes les explications ; `Page._explain_controls()` les
pose après `build()`. Les clés sont les **noms d'attributs** de la page
(`@_category`), ce qui n'a demandé aucune modification des pages : les
widgets anonymes y étaient déjà rangés sous un nom stable.

L'intérêt du registre n'est pas d'économiser des lignes, c'est de rendre la
couverture **vérifiable** : quatre tests gardent le résultat, dont un qui
échoue en nommant toute commande ajoutée sans explication. Résultat :
**0 muette sur 184**.

### Le premier écran

Jamais regardé jusque-là : l'application **sans carte**, telle qu'un nouveau
venu la découvre. Un triangle d'alerte et « Aucune carte SD », pour
quelqu'un qui n'a rien fait de mal — et une seule issue, taper un chemin,
alors que l'application sait chercher toute seule. Remplacé par un accueil
en deux chemins, le plus court d'abord.

Deux détails trouvés en regardant la capture : l'invitation de l'en-tête
n'apparaissait qu'après 150 ms, la pastille du Deluge restait blanche
jusqu'au premier battement de seconde. Les deux sont peintes dès la
première image.

### « À faire maintenant »

Le tableau de bord savait déjà tout — combien de fichiers, quand la carte a
été lue, ce que le diagnostic a trouvé, s'il existe une sauvegarde. Il ne le
**disait** pas. Un bandeau donne maintenant une suggestion, une seule, la
plus urgente, avec le bouton qui l'exécute. Sur la carte réelle il affiche :
« Aucune sauvegarde de cette carte. Avant toute correction, une copie
complète évite de perdre des mois de travail. »

---

## 3 octodecies. Le Deluge branché : ce qui a été mesuré

> « Je souhaite que lorsque je connecte mon Deluge à mon PC, les deux
> machines puissent communiquer et travailler ensemble harmonieusement. »

### Ce que la carte apprend sur la machine

La racine de la carte ne contient pas que des dossiers de sons :

| fichier | ce qu'il dit |
|---|---|
| `deluge-c1_2_1.bin` | **firmware communautaire c1.2.1**, pas le firmware officiel |
| `README.txt` | *Deluge Community Firmware (beta)*, révision `4d6efd9` |
| `CommunityFeatures.XML` | 30 réglages de la communauté (un seul touche au MIDI : `syncScalingAction`) |
| `MIDIFollow.XML` | **la carte des contrôleurs du mode MIDI Follow** |

C'est le dernier qui change tout : le mode MIDI Follow agit sur
**l'instrument sélectionné sur la machine**, et ce fichier dit quel
contrôleur pilote quel paramètre. Ses noms sont presque ceux du modèle de
l'application — 31 identiques sur 56.

### Les versions de firmware présentes dans les fichiers

Relevé sur les 2 741 fichiers : `SYNTHS` porte **sept versions**
différentes (3.0.2 : 247, 3.0.4 : 271, 3.1.1 : 30, 3.1.4 : 59, 3.1.5 : 66,
4.0.1 : 65, c1.2.0 : 2) et 595 fichiers sans version du tout. `SONGS` en
porte trois. L'application doit donc rester tolérante : elle l'est déjà
(SPEC §1.2), mais c'est maintenant chiffré.

### Ce que le MIDI permet, et ce qu'il ne permet pas

**Permis** : jouer des notes avec le vrai moteur sonore, régler 52
paramètres de l'instrument sélectionné, envoyer un motif en mesure avec
l'horloge, recevoir ce qui est joué sur la machine.

**Impossible** : choisir le preset à distance. Aucun message MIDI standard
ne le fait, et le dire franchement vaut mieux que de laisser l'utilisateur
chercher le bouton.

**Pas encore fait** : le SysEx du firmware communautaire (recopie de
l'écran, transfert de fichiers). Les tampons `MIDIHDR` de `winmm` demandent
une gestion de cycle de vie qui, mal faite, plante le processus au lieu de
lever une exception — cela s'écrit en face d'un vrai Deluge.

### Trois choses apprises en chemin

1. **Aucune bibliothèque MIDI n'est installée** (`mido`, `rtmidi`, `pygame` :
   absentes). `winmm.dll` en `ctypes` suffit, et ne coûte aucune dépendance.
2. **Un motif n'est pas une suite de 0 et de 1.** J'ai cru le contraire, et
   le motif est sorti deux fois trop vite, les coups rangés dans l'ordre de
   la liste au lieu de leur position. C'est une liste éparse de `Step(pos,
   velocity, length, probability)`. La mesure qui l'a dit : 0,55 s au lieu
   de 1,0 s attendue. Après correction : ±11 ms sur 4 secondes.
3. **Les tests n'ont pas besoin du matériel.** Une fausse sortie MIDI qui
   horodate ce qu'elle reçoit suffit à vérifier que la grosse caisse tombe
   sur les pas 0, 4, 8, 12 et que chaque note allumée est éteinte.

### Ce qu'il reste à vérifier **sur la machine**

Le Deluge n'était pas branché pendant l'écriture : zéro entrée MIDI, une
seule sortie (le synthé logiciel de Windows), qui a servi de banc d'essai.
Restent à confirmer, câble en main :

* le **nom du port** tel que Windows l'annonce (la détection cherche
  « deluge » ou « synthstrom », sans tenir compte de la casse) ;
* le **canal** que le mode MIDI Follow écoute ;
* la **note de la première rangée d'un kit** — l'application part de C1
  (note 36), qui est le cas courant, mais cela n'a pas été mesuré.

---

## 3 novodecies. Le diagnostic qui changeait de réponse

Trouvé en vérifiant l'interface après avoir rendu le diagnostic de santé
automatique : le fil de travail interrogeait l'index pendant que le tableau
de bord le lisait, sur **la même connexion SQLite**.

Résultat mesuré, douze diagnostics en parallèle : « bad parameter or other
API misuse » dans le journal, ``row["rel"]`` qui lève ``IndexError`` sur des
lignes tronquées, et surtout **85 ou 90 de note selon la course**. Comme
chaque contrôle avale son erreur (`_step`), le rapport s'affichait sans rien
signaler : il était simplement faux.

``check_same_thread=False`` — présent depuis le début pour que l'analyse
écrive depuis un fil — ne protège rien : il désactive la vérification de
Python, pas la connexion. La correction tient en deux moitiés, et les deux
comptent :

1. un **verrou réentrant** autour de chaque usage de la connexion ;
2. la **matérialisation du résultat sous ce verrou** : sans elle, un curseur
   lu plus tard rouvre la fenêtre.

### Le premier test ne prouvait rien

Écrit d'abord pour guetter le dégât (lignes tronquées, notes divergentes),
il passait **aussi bien sans le verrou** : sur une carte factice la fenêtre
de course est trop étroite. Le test qui discrimine vraiment espionne la
connexion et compte les requêtes **simultanées** : avec verrou, une ;
sans, plusieurs. Vérifié en retirant le verrou — deux tests tombent, dont
celui qui reproduit l'``IndexError`` d'origine.

---

## 3 quindecies. Refonte de l'interface

> « Je trouve que l'interface utilisateur du logiciel est triste et assez
> compliqué à utiliser. » — l'utilisateur, 11 octobre 2026. Interrogé, il a
> désigné **les quatre** maux proposés : on ne sait pas où l'on est ni où
> cliquer ; les listes sont des tableaux illisibles ; c'est terne ; trop
> d'écrans, trop d'étapes. Direction choisie : « sombre et coloré, façon pads
> Deluge ».

Les règles qui en sont sorties sont dans **SPEC §5.16** et la palette dans
**SPEC §2**. Ce qui suit est ce qu'il faut savoir pour ne pas défaire le
travail.

### Une partie du mal venait de moi

Avant d'accuser le dessin : l'utilisateur démarrait sur la page **Réglages**,
avec la barre de navigation **repliée en neuf icônes anonymes**, et un clic
sur un échantillon ne jouait rien. Rien de tout cela n'était un choix de
l'application — c'étaient mes scripts d'essai qui avaient écrit
`window/page=Settings`, `window/rail=narrow` et `autoplay=false` dans l'état
réel de l'utilisateur. Le garde-fou est maintenant structurel (§3 sexdecies).

### Trois bugs de la même famille : une couleur transmise puis jetée

| Endroit | Ce qui se passait |
|---|---|
| `StatTile.__init__` | recevait `color`, ne l'appliquait jamais : six tuiles au liseré or |
| `tool_button` | n'utilisait `color` que pour l'icône, et seulement si `primary` : 22 genres gris identiques |
| `page_header` | acceptait `color` et l'ignorait entièrement : neuf en-têtes jumeaux |

Un paramètre accepté puis ignoré ne lève jamais et ne se voit pas à la
lecture ; il se voit sur une capture d'écran. D'où la méthode : **rendre
chaque page en PNG et la regarder**, cf. §4.

### Ce que la mesure a décidé

- **Colonnes de la table des échantillons : 11 → 8.** Sur les 1 741 fichiers
  réels, `sr` vaut 44 100 dans 90,7 % des cas, `bit_depth` vaut 16 dans
  87,7 %, `channels` est mono dans 69,7 %, et **`bpm` est vide dans 96,2 %
  (1 674 / 1 741)**. Quatre colonnes répétaient la même valeur ; une seule
  colonne « Format » les remplace, **vide quand le fichier est ordinaire**.
- **L'arbre des dossiers montrait deux lignes** dans un panneau de 270 px :
  la carte range tout sous `SAMPLES`, et seules les feuilles portaient un
  compte. Chaque nœud porte maintenant le total de son sous-arbre, et les
  niveaux à enfant unique sont dépliés d'office — les cinq familles de la
  carte (MULTISAMPLES 1 091, Artists 392, DRUMS 254, RESAMPLE 3, RECORD 1)
  sont visibles d'emblée.

### Deux pièges de Qt sur la largeur des listes

Les quatre listes de l'application débordaient sous une barre de défilement
horizontale, qui cachait précisément les colonnes utiles. Deux causes, aucune
évidente à la lecture du code :

* **`QSplitter.setSizes` est une proportion, pas des pixels.** Qt normalise
  les nombres à la largeur disponible : `setSizes([620, 820])` sur une zone
  de 1 210 px donne **521** px, pas 620. Les nombres du code valent pour une
  zone de 1 210 px, soit une fenêtre de 1 440.
* **Une colonne étirée reçoit ce qui reste**, et rien ne garantit que ce
  reste soit positif. « Dossier » était la colonne étirée des échantillons :
  les sept autres faisant 725 px dans une vue de 871, il lui restait
  **36 px**. C'est le **nom** qui doit s'étirer, et la somme des autres doit
  tenir dans la vue.

Mesuré après correction, sur une fenêtre de 1 440 : Échantillons 871/871,
Presets 601/601, Kits 460/461, Morceaux 460/481. Aucune barre horizontale.

### Deux mots pour deux opérations

« Analyser » désignait **deux choses différentes** à trente pixels d'écart :
relire la carte (barre d'en-tête, Ctrl+R) et chercher les anomalies dans
l'index (page Santé). La page Santé dit désormais « Diagnostiquer », et le
bouton du tableau de bord a disparu au profit de celui de l'en-tête — qui
mène d'ailleurs au tableau de bord, là où l'avancement s'affiche.

### Adresses `Page#Partie`

`go_to("Health#Sauvegardes")` ouvre la page **et** son onglet. Le signal
`navigateRequested` reste à un seul argument : c'est une adresse, pas deux
paramètres — et les tests existants n'ont pas eu à changer.
`Page.focus_on(hint)` compare les libellés d'onglets sans casse ni accents et
ne fait rien si le libellé est inconnu.

---

## 3 sexdecies. Trois fois, mes essais ont modifié les réglages réels

La troisième fois est la grave : un script de reproduction avait éteint
`confirm_writes` **et** `always_backup_before_write`, les deux filets qui
protègent une carte contenant des mois de travail. Ils sont restés éteints
pendant une heure sans que rien ne le signale.

**Ce qui a été réparé.** `DELUGE_COMPANION_CONFIG` déplace le dossier de
configuration (SPEC §4.1) ; `MainWindow._settings_store` suit la même
variable, pour que l'état de fenêtre ne parte pas non plus dans le registre ;
les modules de test la posent dans leurs quatre premières lignes, **avant
tout import de `delugeapp`**.

**Le détail qui compte.** Le garde-fou avait d'abord été posé dans
`tests/__init__.py`. Il ne protégeait rien : `unittest discover -s tests`
charge les modules à plat, sous le nom `test_core`, **sans importer le
paquet** — et c'est la commande que donne l'en-tête du fichier de tests.
Seul l'invariant
(`TestDossierDeConfiguration.test_la_suite_n_ecrit_pas_chez_l_utilisateur`)
l'a dit, à sa première exécution complète. Vérifié en retirant les lignes :
le test tombe avec le bon message.

---

## 3 septdecies. Le même preset ne rendait pas le même son

`render.render_sound` tirait la graine du bruit et des phases de LFO de
`hash(sound.name)`. **Python randomise le hachage des chaînes à chaque
démarrage** : le générateur promet qu'une graine donnée redonne le même son,
et la promesse s'arrêtait à la fin de la session.

Mesuré sur la même basse « lo-fi », graine 2, avec quarante graines de bruit
différentes : crête de **0,007 à 0,415**, médiane 0,153 — soit 35 dB d'écart
sur le même preset. Un test de rendu muet est tombé dessus un jour sur
plusieurs, ce qui en faisait une alerte qu'on apprend à ignorer.

Remplacé par `zlib.crc32` du nom : sans valeur en cryptographie, mais stable,
et c'est tout ce qu'on lui demande. Vérifié : cinq processus avec des
`PYTHONHASHSEED` différents rendent exactement 0,061508.

---

## 3 quaterdecies. Le bug qui rendait presque tous les boutons inertes

**Signalé par l'utilisateur** : l'application affichait « Action impossible :
voir le journal » sur presque chaque bouton. Le journal contenait **16
erreurs, toutes la même** :

```
TypeError: GeneratorPage._listen() takes 1 positional argument but 2 were given
```

### La cause

Le signal `clicked` de Qt émet un booléen. **PyQt le supprime normalement**
quand le destinataire n'en veut pas : il lit l'arité de l'appelable. Mais
`Page.guard`, qui entoure chaque bouton d'un `try/except`, était écrit
`wrapper(*args, **kwargs)` — **variadique**. PyQt en concluait que le
destinataire acceptait tout, et transmettait le booléen à des méthodes sans
paramètre.

**55 boutons** branchés par `guard` levaient donc cette erreur au premier
clic réel, sur toutes les pages.

`guard` calcule maintenant l'arité du destinataire (`_arite()`) et tronque
l'excédent — **jamais le nécessaire** : les gestionnaires qui veulent
vraiment l'argument (`_set_favorite(checked)`, `_apply_volume(value)`,
`_on_path_typed(text)`) continuent de le recevoir. Une seule enveloppe
variadique existait dans tout le code ; il n'y en a plus.

### Pourquoi 557 tests ne l'avaient pas vu

Ils appelaient les méthodes **directement** :

```python
page._process()      # ce que faisaient les tests : marche
bouton.click()       # ce que fait l'utilisateur : TypeError
```

Et le test de lancement visitait les neuf pages sans rien actionner. Le trou
était de méthode : je vérifiais le code écrit, pas le chemin emprunté par
l'utilisateur.

`TestClicsReels` clique désormais **réellement** sur chaque bouton de chaque
page et échoue si le rempart de `guard` a dû absorber quoi que ce soit.
Preuve qu'il attrape le bug : **56 échecs** quand on retire le correctif,
0 avec. Un test qui passe avant et après ne prouve rien — cette vérification
par retrait est à refaire pour tout correctif de ce genre.

⚠️ **Pour que ce test ne se bloque pas**, il neutralise `QDialog.exec` **sur
la classe de base** — ce qui couvre d'un coup `PlanDialog`, `ProcessDialog`,
`SliceDialog` et tout dialogue à venir — ainsi que les trois `QInputDialog`
de la page Générateur, que j'avais oubliés au premier essai : le test
attendait indéfiniment une saisie.

### Et le reste de la surface ? Mesuré aussi

Le bug venant d'un chemin non emprunté par les tests, j'ai sondé **tout** ce
qu'un utilisateur peut toucher avant d'écrire la suite : onglets, lignes de
tableau, listes déroulantes, cases à cocher, curseurs, champs de saisie,
entrées de menu, raccourcis. **398 interactions, 0 erreur.**

Les boutons étaient donc bien le seul chemin cassé : les autres connexions
guardées emploient des lambdas à la bonne arité ou des méthodes qui veulent
vraiment l'argument. La sonde est devenue `TestInteractionsReelles` et
`TestMenusEtRaccourcis` — le filet qui dira si une retouche future casse un
de ces chemins. La fenêtre principale protège ses actions avec `_safely`,
**un rempart distinct de `Page.guard`**, qui n'était pas davantage exercé :
il a maintenant son test.

### Deux leçons de la reproduction sur la vraie carte

- **140 boutons cliqués, 0 erreur** après correctif : le scénario de
  l'utilisateur passe.
- Mon script de reproduction a **créé `KITS/MON KIT.XML` sur la vraie
  carte**, en cliquant « Enregistrer le kit » sans discernement. Ce n'est
  **pas** un défaut de l'application : `_save_kit` n'écrit sans question que
  pour un fichier **nouveau**, et demande confirmation avant tout
  remplacement — un bouton « Enregistrer » qui enregistre fait son travail.
  Le fichier a été retiré. **Ne jamais relancer un clic-sur-tout sur la vraie
  carte** : ce test appartient à une carte jetable, et c'est là qu'il vit.

---

## 3 terdecies. Passe de nettoyage après quatre modules

Quatre modules écrits coup sur coup laissent des traces. Ce qui a été trouvé
en les relisant, et corrigé :

### Trois copies du même formateur, dont deux fausses

`human_size` existait dans `ui/widgets/common.py`, et je l'avais **recopiée
deux fois** dans `core/samplefix.py` et `core/songpack.py`. Les copies du
noyau écrivaient le séparateur décimal **à l'anglaise** :

```
core      : 5.5 Mio
interface : 5,5 Mio
```

Les messages de correction d'échantillons et de rassemblement de morceau
sortaient donc avec un point, au milieu d'une application en français. Même
chose pour `_size()`, recopié à l'identique.

Tout est maintenant dans **`core/units.py`** — `human_size`,
`human_duration`, `file_size` — et `common.py` le réexporte, si bien que les
appels de l'interface restent inchangés. Le module ne dépend que de la
bibliothèque standard : le noyau peut l'utiliser sans toucher à Qt.

Un test vérifie que `common.human_size is units.human_size`, un autre que
`samplefix` et `songpack` n'ont **plus** de copie privée, un troisième
qu'aucun message ne porte de point décimal.

### 44 imports inutilisés dans 17 fichiers

Dont une partie que j'avais moi-même rendus inutiles en déplaçant
`PlanDialog` hors de la page Santé (`QDialogButtonBox`, `QPlainTextEdit`).
Le détecteur ne retire un nom que s'il n'apparaît **qu'une fois** dans tout le
fichier, c'est-à-dire sur sa propre ligne d'import : un nom employé dans une
annotation en chaîne ou dans `__all__` est donc épargné. Les 557 tests
passent après coup, et les 51 modules s'importent tous.

### Quatre fonctions publiques mortes — testées, pas supprimées

`fixedpoint.to_bipolar`, `fixedpoint.from_bipolar`, `rhythm.beat_names` et
`theory.chord_names` n'étaient appelées par rien, tests compris. Elles font
partie de la surface documentée des modules et sont parallèles aux
accesseurs employés ailleurs (`genre_keys`, `scale_names`) : les supprimer
casserait un contrat pour gagner douze lignes. **Mortes et non testées**
était le vrai risque — elles auraient cédé au premier usage. Elles sont
désormais couvertes.

### Ce que la passe a confirmé

| Contrôle | Résultat |
|---|---|
| Un module de `core/` importe-t-il Qt ? | **non** — les 25 s'importent avec PyQt6 bloqué |
| `core/` importe-t-il `ui/` ? | **non** |
| Artefacts de mes correctifs textuels (lignes vides, séparateurs orphelins, espaces en fin de ligne) | **aucun** sur les 14 fichiers retouchés |

> ⚠️ Les 439 lignes de plus de 79 caractères et les 113 « deux lignes vides
> manquantes » que signale un contrôle naïf sont **le style du dépôt depuis
> l'origine**, pas des dégâts : les séparateurs de section
> (`# ---- #`) tiennent lieu de respiration. Ne pas lancer de reformatage
> massif : ce serait du bruit dans l'historique, sans rien corriger.

---

## 3 duodecies. Sortir un morceau du Deluge (`core/songpack.py`)

Deux boutons sur la page Morceaux, qui **n'écrivent jamais sur la carte** —
la page reste en lecture seule, conformément au §6.

### Rassembler les dépendances

`collect()` inventorie le morceau, les presets qu'il nomme et les
échantillons que ces presets lisent ; `write_pack()` les copie dans un
dossier **en conservant l'arborescence**, si bien que le résultat a la forme
d'une carte : le recopier à la racine d'une autre suffit à y jouer le morceau.

Deux points que la lecture du format impose :

- **un morceau nomme ses presets, il ne les situe pas.** Il porte
  `presetName` et `presetFolder`, pas un chemin ; la casse n'est pas fiable
  (FAT32) et le dossier annoncé peut omettre la racine — `acid` plutôt que
  `SYNTHS/acid`. `_find_preset()` essaie donc le dossier tel quel, puis
  préfixé, puis le premier preset de ce nom où qu'il soit ;
- **les échantillons viennent de deux sources** : du morceau lui-même, qui
  embarque une copie des définitions d'instruments, **et** des presets qu'il
  nomme. Un morceau peut citer un échantillon qu'aucun preset de la carte ne
  lit.

Mesuré sur les 46 morceaux : inventaire complet en **0,7 s** (15 ms par
morceau), **46 complets sur 46**. Les 125 références cassées de la carte sont
dans des presets qu'aucun morceau n'utilise — ce qui confirme au passage que
les échantillons REPHAZER ne servent à rien pour l'instant.

### Export MIDI du morceau entier

`midifile.song_to_midi()` écrit une piste par clip, les kits sur le canal des
percussions, et retourne 0 sans rien écrire si aucun clip ne porte de note.

> ⚠️ **Toutes les pistes démarrent au même point, et c'est une contrainte des
> données.** Les clips du Deluge sont des boucles de la grille de session :
> le fichier ne porte **aucune position absolue** pour elles. Vérifié —
> **aucun des 46 morceaux n'utilise la vue arrangement**, et aucun attribut
> de position n'apparaît dans leur XML. Ne pas « améliorer » cela en
> inventant un placement dans le temps : ce serait une fiction. Le message de
> la page le dit à l'utilisateur.

### Deux erreurs dans mes propres tests

- l'empreinte de la carte était prise **avant** que le test ne crée le
  morceau : la comparaison trouvait un fichier de plus et accusait le code ;
- `safe_deluge_name("")` rend déjà `SANS NOM`. Mon repli `or "MORCEAU"` ne
  pouvait donc jamais s'appliquer, et inventait une seconde convention pour
  rien. Le repli a été retiré.

---

## 3 undecies. Recherche par ressemblance (`core/similarity.py`)

Sélectionner un son et voir ce qui lui ressemble, sur 1 741 échantillons.

**Le schéma de l'index passe en version 4** : huit colonnes s'ajoutent à
`samples` (`centroid`, `rolloff`, `flatness`, `bandwidth`, `low_ratio`,
`high_ratio`, `crest`, `attack`). Elles étaient **calculables depuis le début
et jamais conservées** : `analysis.spectral()` existait, `scan` ne l'appelait
pas.

### Qualité mesurée

Sur la carte réelle, catégorie des 5 plus proches voisins contre catégorie du
départ, sur les 22 catégories d'au moins 12 fichiers :

| Mesure | Résultat |
|---|---|
| Catégories sous le hasard | **aucune** |
| Marge disponible gagnée, `(mesuré − hasard) / (1 − hasard)` | médiane **0,45**, max 0,99 |
| Facteur brut | médiane **10,8×**, max 24× |
| Construction de l'espace | **0,017 s** pour 1 741 vecteurs |

⚠️ **Deux pièges dans cette mesure, tous deux rencontrés avant d'arriver au
bon chiffre :**

1. la **moyenne pondérée** est trompeuse. Sur cette carte, « catégorie »
   désigne surtout la bibliothèque d'origine, et `Sonic Bloom Mellotron` pèse
   802 fichiers sur 1 741 — 46 %. Elle domine numérateur et dénominateur, et
   ramenait le résultat à 2,8× alors que chaque catégorie battait le hasard
   de 4 à 24 fois ;
2. le **facteur brut a un plafond arithmétique**. Une catégorie occupant
   46,1 % ne peut pas dépasser 100/46,1 = 2,17× : exiger 3× d'elle est
   impossible même avec une recherche parfaite. Elle atteignait 2,1×, c'est-à-
   dire la quasi-perfection, et mon test la déclarait en échec.

D'où la **marge gagnée**, bornée à 1, qui vaut 0 pour le hasard et 1 pour une
recherche parfaite quelle que soit la taille de la catégorie.

Et un point à ne pas corriger en croyant bien faire : **les voisins sont
souvent d'un autre dossier, et c'est juste.** Un kick trouve des toms
(`808 Tom medium`, `909 Tom low`), une caisse claire trouve des rim et des
cowbells. Le score par catégorie **sous-estime** donc la qualité réelle.

### Ce que ce module ne fait pas, et pourquoi

**Pas de détection de quasi-doublons.** La fonction a existé puis a été
retirée après mesure :

- à une distance de 0,45, le regroupement avale **59 % de la bibliothèque**
  en 200 groupes, et met `8 Choir G#2` avec `Orchestra B3` et un saxophone ;
- serré à 0,12 **et** avec une durée à 2 % près — critère censé isoler le même
  son réencodé — les 15 paires trouvées sont **toutes** deux notes voisines du
  même instrument multi-échantillon : `Cello B3` avec `Cello C4`,
  `MK2 Brass F#3` avec `MK2 Brass G3`.

La cause est structurelle : le descripteur est aveugle à la hauteur, et une
bibliothèque multi-échantillon est précisément faite de fichiers de même
timbre et de même longueur à des hauteurs différentes. `Library.duplicates()`
répond déjà juste, octet pour octet. Un test de non-régression vérifie que la
fonction n'est pas revenue.

### Coût, et le drapeau qui ne servait à rien

L'analyse acoustique complète de la carte passe de **76 s à 203 s**. Elle
reste désactivée par défaut (`scan_analyze`), et l'incrémental saute les
fichiers inchangés.

> ⚠️ **`Library.init_db` posait `needs_rescan` depuis toujours et personne ne
> le lisait.** Sans cela, après une mise à niveau du schéma, une analyse
> incrémentale sauterait les fichiers inchangés et les colonnes neuves
> resteraient vides pour de bon. `scan_card` consulte maintenant le drapeau et
> force l'analyse complète ; il ne le baisse qu'au terme d'une analyse
> **complète et acoustique**.

> ⚠️ **`Library.needs_rescan` est une propriété, pas une méthode** — comme
> `Settings.backup_path` est une méthode, pas une propriété. Les deux pièges
> se sont déjà payés en `TypeError`.

---

## 3 decies. Découpage d'une boucle en kit (`core/slicer.py`)

Un break devient un kit où chaque pad joue une tranche. **Aucun fichier audio
n'est dupliqué** : les rangées pointent toutes le même échantillon avec leurs
propres bornes.

**Ce n'est pas une hypothèse sur le format, c'est mesuré :**

- **19 zones de la carte ne jouent qu'une portion de leur fichier.**
  `021 hodeur 1.XML` joue les 10 à 55 % de six enregistrements, et
  `015 Andrew Stirton Frugal.XML` démarre `frugalriser.wav` à la trame
  **113 403** — donc `start > 0` fonctionne sur la machine.
- **Un kit de la carte référence déjà deux fois le même fichier avec des
  bornes différentes** (`snare smack.wav` dans
  `020 Leonard Ludvigsen Beatbox.XML`) : c'est littéralement un découpage à
  deux tranches, écrit par quelqu'un d'autre avant moi.
- **Les bornes sont exclusives** : `clap1.wav` porte `endSamplePos = 12259`
  pour 12 259 trames, pas 12 258.
- Le plus gros kit de la carte compte **19 rangées**. `MAX_SLICES = 32` est un
  choix d'ergonomie, pas une limite du format.

**Deux pièges rencontrés, à ne pas réintroduire :**

- **le mode « grille » ne doit PAS s'aligner sur le tempo.** Sur une boucle
  correctement coupée, la division égale *est* la grille : les 4,0 s de
  `Bricky-NoKS-120.wav` donnent 16 tranches de 250,0 ms, soit la croche à
  120 BPM. Ma première version ramenait ces bornes sur le tempo **détecté**
  (120,2 BPM), ce qui déplaçait les coupes et faisait sortir une tranche à
  256 ms : l'alignement dégradait un découpage déjà juste. L'alignement est
  réservé aux coupes issues des attaques (`SliceSet.quantize`).
- **les tranches trop courtes se filtrent sur les bornes, pas après coup.**
  Fusionner une tranche trop courte dans la précédente marche partout sauf au
  début : la **première** tranche n'a pas de précédente, et restait à
  30 trames — le clic qu'on voulait éviter. On ne garde désormais une borne
  que si elle est à `MIN_SLICE_MS` au moins de la dernière retenue.

Garanties couvertes par les tests : les tranches couvrent tout le fichier sans
trou ni chevauchement, les bornes survivent à l'aller-retour XML, un kit
existant n'est jamais écrasé (le nom est numéroté), et `apply=False` n'écrit
rien.

Côté interface : `WaveformView.set_markers()` affiche les coupes numérotées,
et `SliceDialog` (page Échantillons, bouton « Découper… ») laisse choisir le
placement, le nombre, la sensibilité, l'alignement, puis écouter chaque
tranche avant d'écrire.

> ⚠️ **`theme.with_alpha` rend une chaîne QSS `rgba(...)` que `QColor` ne sait
> pas lire** — `QColor(with_alpha(GOLD, 0.18)).isValid()` vaut `False`. La
> transparence d'un tracé se règle avec `QColor.setAlphaF`. Le piège s'est
> présenté deux fois : une fois dans les widgets communs, une fois ici.

---

## 3 nonies. Correction des défauts audio (`core/samplefix.py`)

Le diagnostic repérait quatre défauts qu'il ne savait pas corriger. C'est fait.
`plan_mono`, `plan_standard_rate`, `plan_remove_dc`, `plan_headroom`,
`plan_custom` et `plan_from_health` produisent un `FixPlan` ; `simulate()` le
chiffre sans rien écrire, `apply()` l'exécute.

**Trois dangers mesurés sur la carte réelle. Ne pas les perdre de vue en
touchant à ce module :**

| Danger | Mesure | Traitement |
|---|---|---|
| **Bornes en trames** | **1 191 des 1 497** références de presets et de kits bornent leur échantillon en trames (`startSamplePos`) ; 306 sont en millisecondes | `retarget_zones()` remet les bornes à l'échelle dans la même opération. Les zones en millisecondes sont laissées intactes : la durée réelle du fichier n'a pas changé |
| **Morceaux en lecture seule** | les **28** morceaux qui citent des échantillons les bornent **tous** en trames (884 références) | tout fichier cité par un morceau est **écarté** des corrections qui changent sa longueur, motif affiché. Mono, continu, normalisation et fondus restent permis : ils gardent les trames |
| **Recentrer peut écrêter** | `Kick.wav` : crête 0,9999 **et** continu +0,062. Trois fichiers basculaient dans l'écrêtage, le diagnostic passant de 35 à **38** après une correction censée améliorer les choses | `plan_remove_dc()` ajoute une baisse à −0,1 dBFS dès que `peak + |dc| ≥ 0,9995`, ce qui met à l'échelle au lieu de raboter |

**Deux bugs trouvés en vérifiant, et qu'il ne faut pas réintroduire :**

- **la sauvegarde se faisait sous le chemin absolu.** `path.relative_to(path.anchor)`
  donnait `Users/sebas/AppData/…/carte/SAMPLES/…`, donc les originaux
  finissaient dans `_BACKUP/samplefix-…/Users/sebas/…` et la restauration
  recréait cette arborescence **dans la carte** au lieu de remettre le fichier
  à sa place. Rien n'était jamais restauré, et la carte se remplissait de
  dossiers parasites. La copie se fait désormais sous le chemin **relatif à la
  carte**, et un test compare chaque fichier à l'octet après restauration.
- **deux exécutions à la même seconde partageaient leur dossier de
  sauvegarde** : restaurer l'une restaurait les deux. Un suffixe numérique est
  ajouté si le dossier existe déjà.

**Un choix d'API à conserver :** `FixPlan.apply(sd, lib)` **écrit**, comme
`organize.Plan.apply`. La première version prenait un `apply=False` par défaut,
si bien que `plan.apply(sd, lib)` ne faisait rien — un piège à bugs silencieux.
La simulation a son propre nom, `simulate()`.

**Les seuils ne sont pas redéfinis** : `DC_THRESHOLD`, `CLIP_THRESHOLD` et
`STANDARD_RATES` sont importés de `health`. Les avoir dupliqués faisait
proposer 80 fichiers là où la page en signalait 17.

Côté interface : `PlanDialog` a quitté la page Santé pour `ui/widgets/common.py`,
puisque deux pages s'en servent ; il n'exige de son plan que `summary()`,
`counts()` et `to_text()`, et avertit quand `plan.changes_length` est vrai. La
page Échantillons gagne un bouton « Traiter… » et le signal `cardModified`.

> ⚠️ **En Qt 6.11, `ItemIsUserCheckable` fait partie des drapeaux par défaut
> d'un `QListWidgetItem`.** Un test qui vérifie ce drapeau pour savoir si une
> anomalie est cochable passe quoi qu'il arrive. Ce qui fait apparaître la
> case, c'est `setCheckState`, donc la présence de `CheckStateRole`.

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

**Tout est écrit.** Les cinq phases sont terminées, et cinq modules s'y sont
ajoutés (`samplefix`, `slicer`, `similarity`, `songpack`, `units`) :
26 modules de noyau, 7 widgets, 9 pages, la fenêtre principale et le point
d'entrée. **566 tests au vert** (364 pour le noyau, 202 pour l'interface).

### Regarder l'interface, pas seulement la tester

Les trois bugs de couleur ci-dessus passaient tous les tests : un paramètre
ignoré ne lève pas. Le seul moyen de les voir est de **rendre les pages en
image**. Le script de rendu tient en quarante lignes ; deux pièges :

- **pas de plateforme « offscreen »** pour cela : elle n'a aucune police
  installée et tout le texte sort en carrés. Utiliser la vraie plateforme
  avec `WA_DontShowOnScreen` — la fenêtre est mise en page et peinte sans
  jamais apparaître ;
- **poser `DELUGE_COMPANION_CONFIG` avant tout import de `delugeapp`**, sans
  quoi le script écrit les réglages et l'état de fenêtre de l'utilisateur en
  quittant (§3 sexdecies).

### Lancer et vérifier

```bash
cd "C:\Users\sebas\Desktop\Informatique\Deluge app"
PY="C:/Users/sebas/AppData/Local/Programs/Python/Python313/python.exe"
"$PY" main.py                                # l'application
"$PY" -m unittest discover -s tests -t .     # 566 tests, doit afficher OK
```

Les tests d'interface ont besoin d'un affichage ; sans serveur graphique,
`QT_QPA_PLATFORM=offscreen` suffit. La suite complète dure environ 70 secondes.

Deux contrôles à refaire après toute modification touchant à l'écriture :

```bash
# 1. les réglages réels ne doivent pas bouger
sha256sum "$APPDATA/DelugeCompanion/settings.json"   # avant et après la suite
# 2. la carte ne doit porter aucune trace
find "SDCARD Deluge" -name "_BACKUP" -o -name "*.samplefix-tmp" \
     -o -name "*TRANCHES*" -o -name "*.bak"
```

### Si le travail reprend

Il n'y a plus de phase à écrire. Les pistes qui restent ouvertes, par ordre d'intérêt :

1. **Écriture des morceaux.** `core.model.Song` est en lecture seule par choix (voir §6).
   L'ouvrir en écriture demanderait de prouver, sur les 46 morceaux de la carte, qu'un
   aller-retour lecture/écriture est stable à l'octet — ce n'est pas démontré aujourd'hui.
   Entre-temps, `core/songpack.py` couvre le besoin le plus courant — sortir un morceau
   de la machine — sans rien réécrire.
2. **Export de kits vers un autre format** (Ableton, MPC), à partir de `core.kitgen`.
   Le découpage par zones (`core.slicer`) donne déjà la matière : il suffirait de
   traduire les bornes.

> **Piste écartée après mesure : construire des instruments multi-échantillons.**
> Les bibliothèques de la carte sont **déjà entièrement cartographiées** — 23
> instruments Mellotron de 35 plages chacun, tous joués par un preset. Les seuls
> dossiers inexploités sont les 4 dossiers REPHAZER (48 fichiers), et ils le sont
> uniquement parce que les presets qui les citent ont des chemins cassés, ce que
> la page Santé répare déjà. Il n'y avait rien à construire.
3. **Empaquetage** (`PyInstaller`) pour lancer l'application sans Python installé.
4. **Déclippage réel** des 35 fichiers écrêtés (reconstruction des sommets par
   interpolation), au lieu de la simple baisse de niveau actuelle.
5. **Descripteur sensible à la hauteur** (chroma, fréquence fondamentale) : il
   permettrait enfin de distinguer « le même son » d'« une autre note du même
   instrument », et donc de rouvrir la question des quasi-doublons que
   §3 undecies a dû abandonner.

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
