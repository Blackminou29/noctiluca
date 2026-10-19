# Point d'étape — Deluge Companion

**Dernière mise à jour :** 19 octobre 2026 (l'interface en anglais, §3 duotricies)
**État :** **application terminée et fonctionnelle.** Les cinq phases sont écrites,
`python main.py` démarre, **la suite complète passe** (le nombre exact est dans le dernier
§ daté). Deux audits de bugs (§3 duovicies) puis trois passes sur les générateurs et la
composition (§3 tervicies, quatervicies et quinvicies) ont suivi. Quatre modules se sont ajoutés
depuis : `core/samplefix.py` **corrige** les défauts audio que le diagnostic ne
savait que signaler, `core/slicer.py` **découpe une boucle en kit**,
`core/similarity.py` **retrouve un son par ressemblance**, et
`core/songpack.py` **sort un morceau du Deluge**. Une passe de nettoyage a
suivi : voir §3 terdecies. **L'interface a ensuite été entièrement reprise**
à la demande de l'utilisateur : voir §3 quindecies, puis **redessinée d'après le
guide** (« la façade ») : voir §3 septvicies. **Chaque outil de création écrit
désormais un morceau du Deluge** (`core/songwriter.py`) : voir §3 octovicies.
**L'application travaille avec le Deluge branché en USB** — écran recopié,
tempo, son sélectionné, mesuré sur la machine : voir §3 novovicies. **Sa carte
reste dans la machine** : firmware 1.3, copie de travail synchronisée par USB, la
sauvegarde de l'utilisateur seulement lue — voir §3 tricies. **Les échanges vont dans
les deux sens** : envoyer au Deluge les sons et packs du PC, voir ce qui attend et ce
qui est arrivé, glisser un son vers le logiciel de MAO — voir §3 untricies. **L'interface parle français
ou anglais**, au choix dans le menu « Langue » — voir §3 duotricies.
**Objet :** ce qui a été construit, ce qui a été mesuré, et ce qu'il faut savoir avant
de modifier quoi que ce soit.

---

## 1. Ce qu'est le projet

Application Python (PyQt6) accompagnant l'utilisation d'un Synthstrom Deluge :
gestion complète de la carte SD (échantillons, presets, kits, morceaux), générateur de
presets de synthé par genre musical ou aléatoire, et boîte à outils de production
électronique. Interface en français ou en anglais (le français est la langue source),
identité visuelle reprise du *Guide du Deluge OLED*.

**Le contrat d'architecture complet est dans [`SPEC.md`](SPEC.md)** : signatures exactes de
tous les modules, format XML du Deluge, palette graphique, description de chacune des
9 pages. C'est le document de référence.

> `SPEC.md` contient plusieurs encadrés **« Correction mesurée »** (dont §1.5, §1.6, §4.5,
> §4.9 ; la résolution des notes, au §1.6, a été corrigée le 14 octobre 2026).
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
| `rhythm` | euclidien (Bjorklund), 11 motifs de genre, 9 grooves MPC, swing, humanisation, tables de délai | **`E(3,8)` = `x..x..x.`** (exigence SPEC §7) et `E(5,8)` = `x.xx.xx.` ; le nombre de coups est exact pour toutes les combinaisons jusqu'à 32 pas ; 1/4 à 120 BPM = 500 ms ; `bars_to_ticks(16)` = 1536 (grille **interne** de l'appli, 96 par mesure ; un morceau c1.2.1 en compte 384 : voir §3 octovicies) |
| `midifile` | SMF type 1, stdlib seule | Relu par **un analyseur indépendant** écrit dans les tests : en-tête, blocs, délais en longueur variable, aucune note laissée allumée, aucun octet superflu. Un vrai clip de la carte (87 notes) ressort avec ses 87 notes et son tempo |

~~**Contrainte du Deluge à ne pas oublier :** `<modeNotes>` veut **exactement sept**
intervalles.~~ **Fausse pour la machine de l'utilisateur** (voir §3 tervicies) : c'était la
règle du firmware officiel. Le firmware communautaire c1.2.1 propose des gammes de cinq et
six notes, et un morceau de la carte (« Truc 1 ») est enregistré à cinq notes.
`theory.deluge_mode_notes()` rend la gamme telle quelle ; `official=True` garde l'ancien
comportement, en complétant par le mode parent.

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

## 3 duotricies. L'interface en anglais (19 octobre 2026)

> « Je souhaite que le logiciel soit traduit en anglais et qu'il soit possible de
> choisir dans la barre de menu entre le français ou l'anglais. »

### Ce qui existe maintenant

| | |
|---|---|
| `delugeapp/i18n/` | `tr`, `N_`, `untranslated`, `plural`, `sources`, `tr_stored`, et les formats de nombres, d'heures et de dates ; ne dépend que de la bibliothèque standard |
| `i18n/en/` | la traduction : 2 025 phrases, un fichier par module du code (`ui/pages/health.py` → `ui_pages_health.py`), listés dans `MODULES` |
| menu « Langue » | entre « Outils » et « Aide » : « Français », « English », la langue retenue cochée ; choix enregistré tout de suite, question posée dans les deux langues |
| `MainWindow.restart` et `main._run_windows` | « Oui » ferme la fenêtre comme à l'ordinaire, puis contexte et fenêtre se reconstruisent dans le même processus, dans la nouvelle langue |
| `tests/i18n_analyse.py` | lit le code par son arbre syntaxique : clés, oublis, appels à l'import ; `python tests/i18n_analyse.py <fichier>` donne le squelette de ce qui manque |

Les règles d'écriture, ce qui ne se traduit pas et les formats sont dans **SPEC §5.26** —
à lire avant d'ajouter un texte.

### Les choix

* **Le français reste la langue source**, et la clé de la traduction : le code se lit
  comme avant, et un texte oublié s'affiche en français plutôt qu'en clé illisible.
* **Ce que l'application écrit prend la langue de l'interface**, à la demande de
  l'utilisateur (« nomme en anglais quand l'interface est en anglais ») : noms de clips
  des morceaux (« Chords », « Build-up Bass », « Loop »), dossiers d'un rangement par
  durée (« Under 1 s »), dossiers de sauvegarde (« _manual », « _before restoring »),
  pistes et repères MIDI, nom de repli « UNTITLED ». `tr()` s'applique au moment
  d'écrire, sur une clé française qui ne bouge pas : les parties (« Accords ») et les
  sections (« Montée ») restent les clés du code, et le manifeste d'une sauvegarde garde
  son libellé en clé. Les noms des presets générés (« ACID GROWL ») étaient déjà en
  anglais. Ce qui est déjà sur la carte ne change pas quand on change de langue.
* **L'index et l'historique gardent leurs textes en français** (anomalies réparées des
  XML, résumé d'un kit) et `tr_stored` les traduit à l'affichage — vérifié sur la vraie
  sauvegarde : « 70 unescaped '&' fixed », « XML structure rebuilt by the tolerant
  parser ». La page Santé reconnaît toujours les documents multi-racines à leur note.
* **Le journal reste en français** : il sert au diagnostic.
* **Changer de langue redémarre la fenêtre**, pas le processus : les textes se
  traduisent à la création des widgets ; retraduire une fenêtre vivante aurait demandé
  de toucher chacune des neuf pages.

### Pièges rencontrés

* **Le test qui clique chaque entrée de menu cliquait aussi « English »** : la fenêtre se
  fermait pour redémarrer, et la suite du test tournait sur un contexte fermé jusqu'au
  chien de garde (2 min). Les entrées de langue sont écartées là, et ont leur test.
* **Un remplacement de `QMessageBox.question` défait par `addCleanup` passe après le
  `tearDown`** de `MainWindowCase` : il rendait aux tests suivants la réponse « oui » de
  la fixture, et deux tests des garde-fous tombaient. Bornés au corps du test
  (`ExitStack`).
* **Une phrase, une traduction** : le catalogue se fond en un dictionnaire.
  « Lecture impossible : %s » voulait dire « jouer » partout sauf dans le découpage, où
  il s'agissait de lire un fichier : le français y est devenu « Lecture de l'échantillon
  impossible ».
* **Un heredoc Bash abîme les « \ »** (déjà noté) : deux fois encore pendant cette passe ;
  les correctifs qui en contiennent s'écrivent avec l'outil d'écriture.

### Vérifié

* **1 030 tests** sous unittest et sous pytest (646 noyau, 355 interface, 29 traduction).
* `test_i18n` : aucun texte visible hors de `tr`/`N_` dans les 71 modules lus, aucun `tr`
  à l'import, aucune clé sans traduction ni traduction orpheline, mêmes marques dans
  chaque gabarit, une seule traduction par phrase. Quatre mutations (traduction retirée,
  marque perdue, texte oublié, `tr` à l'import) font chacune échouer la suite ;
  quatre autres retirent la traduction d'un nom écrit (clips, dossier de rangement,
  dossier de sauvegarde, pistes MIDI) et sont attrapées de même.
* `TestInterfaceEnAnglais` : 8 606 textes relevés sur les neuf pages et tous leurs
  onglets, **aucun en français** (459 signalés quand l'interface est en français) ; les
  commandes s'expliquent aussi en anglais. `TestClicsEnAnglais` : chaque bouton cliqué,
  2 538 textes relevés (barre d'état, boîtes, dialogues), aucun en français (543 en
  français). `TestMenuLangue`, `TestRedemarrageDansLeMemeProcessus` : le choix gardé, la
  fenêtre rouverte dans l'autre langue, la traduction de Qt retirée en anglais.
* Rendus en anglais à 980 et 1 360 px, défilés, sans carte puis avec la sauvegarde
  indexée en lecture seule (index dans un dossier temporaire) : tout en anglais, la barre
  de menus tient à 980 px. Réglages réels intacts.
* Trois coupures vues à 980 px **existent à l'identique en français** et ne tiennent pas
  à la traduction : la liste « Couleur » de la progression (Outils), la description du
  genre (Générateur), l'en-tête « Instrument » des clips (Morceaux).

### À voir avec l'utilisateur

1. La relecture de l'anglais par quelqu'un qui joue du Deluge en anglais : les
   termes suivent le manuel quand il les nomme (Mod FX, Arpeggiator, Pan…).
2. **Fait** le 19 octobre 2026 : ce que l'application écrit se nomme dans la langue de
   l'interface (ci-dessus).

---

## 3 untricies. Le PC et le Deluge, dans les deux sens (18 octobre 2026)

> « Améliorer le workflow entre le déluge et le PC. »

### Le constat, d'abord : le journal et la copie de travail de l'utilisateur

* **Il s'en sert.** À 14 h 48, il a créé la copie de travail face au Deluge en 1.3,
  attendu une analyse complète (112 s), fait une sauvegarde, puis réparé les dix presets
  `rephazer` dans la copie. Le manifeste dit qu'ils sont partis sur la carte à 14 h 53 —
  **son journal n'en disait rien** : aucune synchronisation n'y laissait de trace.
* **Plus rien ne pouvait aller du PC vers la carte.** La carte restant dans la machine,
  l'Explorateur ne l'atteint plus, et l'application ne savait envoyer que ce qu'elle
  fabrique. Sur le PC : 1 294 WAV dans deux packs téléchargés (« postsolarpunk
  Multisamples », 271 Mio ; « TJontheRoad Delugetions Free Pack », 18 Mio), dont 169
  parasites `._*` de macOS.
* **Dans l'autre sens**, ce que le Deluge enregistre arrive dans un dossier caché
  (`%LOCALAPPDATA%`) : aucune liste, aucun glisser vers le logiciel de MAO.
* **« Mettre à jour la sauvegarde » figeait la fenêtre** : son plan compare le contenu
  de 1,4 Go dans le fil de l'interface — 11,3 s à froid, 3,4 s ensuite (mesuré, en
  simulation). Il trouve 13 fichiers que la sauvegarde n'a pas : ce que le Deluge a
  enregistré aujourd'hui (`Cool1`, `Calm Down`, quatre rééchantillonnages…).

### Ce qu'il fallait savoir avant d'écrire

* **Ce que la machine lit** (SPEC §1.8), dans le code de son firmware (tag `beta` =
  commit `102cf9f`, celui de sa carte) : `RIFF/WAVE` ou `FORM/AIFF`, PCM 8 à 32 bits ou
  flottant 32, mono ou stéréo, 5 à 96 kHz — et **l'en-tête `WAVE_FORMAT_EXTENSIBLE` est
  refusé**. La carte et le PC de l'utilisateur respectent tous ces règles ; le contrôle
  sert à ce qui viendra d'ailleurs.
* **La machine met ses requêtes de fichiers en file** (`smSysex::sysexReceived`) et en
  traite une toutes les 0,2 ms ; mais elle jette en silence ce qui dépasse 1 024 paquets
  USB en attente d'envoi. D'où deux lectures d'avance, pas trois. Mesuré, lecture
  seule : **126-129 → 154-160 Ko/s**, contenus identiques, aucune perte — confirmé
  ensuite avec le code de l'application.
* **L'écriture est bornée par le câble** : un SysEx de 1 000 octets met 11 ms du PC à la
  machine (mesuré par un ping allongé, sans rien écrire) ; un bloc d'écriture 18 ms. Le
  chevauchement gagnerait peut-être les 7 ms restantes : ça ne se vérifie qu'en
  écrivant, donc pas sans l'utilisateur.

### Ce qui existe maintenant

| | |
|---|---|
| `core/cardimport.py` | de ce qui est déposé au plan, puis à la copie : packs à la forme de la carte, sons en vrac, presets, kits, morceaux ; parasites écartés ; règles du firmware ; noms transmissibles ; rien d'existant remplacé |
| `wav.deluge_problem` | pourquoi le Deluge refuserait un fichier, et si une conversion sans perte audible le répare |
| `ui/sendfiles.py` | le parcours d'envoi et `SendDialog`, le plan montré avant toute copie |
| la fenêtre | dépôt de fichiers n'importe où, sous un voile (`chrome.DropVeil`) ; Fichier ▸ Envoyer des fichiers / un dossier (Ctrl+I, Ctrl+Maj+I) ; l'écran OLED dit « N À ENVOYER » |
| tableau de bord | panneau « Le Deluge et le PC » : état, ce qui attend, dernier échange, « Reçu du Deluge » cliquable, envoi, zone de dépôt ; « À faire maintenant » propose de mettre la sauvegarde à jour |
| Échantillons | « Envoyer au Deluge… » vers le dossier choisi ; la liste se glisse vers l'Explorateur ou le logiciel de MAO |
| `cardsync` | historique des échanges (`echanges.json`), ce qui attend, arrêt propre (`STOPPED`, câble débranché, machine muette), sauvegarde comparée sans tout relire (`sauvegarde.json`), temporaires jamais envoyés |
| `delugefiles` | deux lectures d'avance, arrêt entre deux blocs, `NOT_CONNECTED` immédiat, `cable_time` |
| `cardwork` | transfert arrêté quand la machine joue et repris à l'arrêt ; chaque échange gardé et écrit au journal ; ce qui attend compté hors du fil de l'interface ; sauvegarde comparée en arrière-plan |

### Sur les vrais packs, en simulation

« TJontheRoad » : 77 fichiers, 18,3 Mio, **environ 7 min** par le câble, 6 parasites
écartés, ses 36 presets dans `SYNTHS` comme le prévoit le pack. « postsolarpunk » :
1 094 fichiers, 271 Mio, **environ 1 h 43** — le plan le dit avant de copier ; ses 766
références se résolvent toutes. Lecture et plan : moins de 0,3 s.

### Ce que les images et l'audit ont trouvé

* La phrase sur la sauvegarde apparaissait **deux fois** (bandeau et panneau) ; puis le
  bandeau ne suivait pas la fin de la comparaison faite en arrière-plan. Corrigés.
* « Aucune sauvegarde de cette carte » s'affichait alors que le miroir de la carte en est
  une : le diagnostic ne connaît que les sauvegardes de l'application. Avec le miroir
  réglé, la question devient « ce qui lui manque ».
* Le détail du plan n'était pas en chasse fixe : un `setFont` écrasé par la feuille de
  style, comme le tempo de « Deluge en direct ». Passé par `role="mono"`.
* **Audit sur les vraies données** (copie fantôme en liens physiques, index réel copié,
  aucun port MIDI, empreintes avant/après) : **mon compte de ce qui attend, fait dans le
  fil de l'interface, figeait la fenêtre 0,3 s de plus au démarrage** — 0,52 s sans lui,
  0,84 s avec, à quatre reprises contre un témoin. Passé dans un fil : 0,57 s. Et tout
  travail de fond effaçait, en finissant, le message de la barre d'état :
  `run_task(quiet=True)` pour ceux que l'utilisateur n'a pas demandés.

### Mes tests étaient fautifs, une fois

Le bandeau attendu ne venait pas : « Aucune sauvegarde » passait avant — et c'était la
règle qui était fausse, pas le test (ci-dessus). Les clics réels ont en revanche trouvé
deux vrais défauts de mon code : `guard(signal.emit)` transmettait le booléen du clic
à un signal sans argument — la famille des 55 boutons inertes — et deux classes de tests
ne neutralisaient pas `getOpenFileNames`, qu'aucun bouton n'utilisait jusque-là.

### Vérifié

* **990 tests** sous unittest et sous pytest ; **25 garde-fous** de cette passe
  éprouvés en les retirant un à un (`retirer_echanges.py`) — chacun fait tomber son test.
* Réglages, index, journal et copie de travail de l'utilisateur inchangés (dates et
  tailles relevées au début de la session) ; sauvegarde inchangée ; rien d'écrit sur la
  carte du Deluge — seules des lectures, et deux mesures de débit en lecture.
* Rendus à 1 440 et 980 px : tableau de bord dans chaque état, voile, plan, page
  Échantillons ; puis sur les vraies données.

### À vérifier sur la machine, avec l'utilisateur

1. **Un premier envoi réel** : le pack « TJontheRoad » (7 min) — les presets s'ouvrent-ils,
   les kicks sonnent-ils ?
2. **La lecture détectée** : l'arrêt pendant que la machine joue repose sur son horloge
   et ses messages START/STOP, jamais encore vus sur sa machine (§3 novovicies). Sans
   horloge MIDI en sortie, l'application ne saurait pas qu'elle joue.
3. **Écrire plus vite** : deux blocs d'écriture en vol, mesurés dans un dossier neuf
   qu'on retire — avec son accord.
4. L'historique commence maintenant : les arrivées d'aujourd'hui (antérieures) n'y sont
   pas ; elles apparaîtront à la prochaine réception.

---

## 3 tricies. La carte reste dans le Deluge (18 octobre 2026)

> « Le dossier SDCARD Deluge est un emplacement de sauvegarde de ma carte SD
> qui n'est pas destiné à être le répertoire de travail mais une sauvegarde
> de la carte en cas de problème. Le logiciel doit être capable de
> travailler directement sur la carte du Deluge relié au PC. »

### Le constat, mesuré

* **En firmware 1.2.1, impossible** : branché, le Deluge n'est qu'un
  périphérique MIDI ; le code le confirme (seules `USB_CFG_PMIDI_USE` et
  `USB_CFG_HMIDI_USE` sont compilées). Sa carte ne s'ouvre qu'au PC, dans
  un lecteur.
* **Le firmware 1.3** (bêta du 18 octobre 2026) ouvre la carte par SysEx
  (`storage/smsysex.cpp`). Question posée à l'utilisateur : il a mis sa
  machine à jour. Identité reçue : 1.3.0.
* L'application travaillait **dans la sauvegarde**. Preuve qu'il le fallait
  corriger : le 11 octobre, elle y avait réparé dix presets `rephazer` que
  la carte n'a jamais reçus (mesuré par USB, tailles différentes).

### Mesuré sur la machine (lecture seule, puis un essai accordé)

| | |
|---|---|
| ping, page de dossier | 1 ms ; 5 à 17 ms |
| toute la carte | 4 318 fichiers, 182 dossiers, **3,6 s** |
| lecture, écriture | 113 à 128 Ko/s ; **45 Ko/s** |
| la carte et la sauvegarde | 4 295 fichiers communs, même taille, **tous à −7 200 s** (copie faite sur un Mac) ; 23 différents ou nouveaux (6,3 Mo) ; la sauvegarde a 4,2 Go de plus — des corbeilles et l'index Spotlight |
| ce que le Deluge enregistre | **date nulle** (pas d'horloge) : `Calm Down.XML`, les quatre `Cool1` |
| `SETTINGS/MIDIFollow.XML` | déménagé en 1.3 ; `<cc_mappings>` (79 assignations, les 52 d'avant inchangées) ; **les réglages de la machine** : Channel A = 1, retour sur A, note 36 |
| essai d'écriture (accordé) | dossier neuf, fichier écrit, relu, refus d'écrire sur un nom pris, remplacement, datation, dossier retiré : tout vérifié |
| copie de travail (isolée, rien écrit sur la carte) | 2 734 fichiers repris de la sauvegarde + 23 par le câble en **52 s** ; 2 757 fichiers justes ; 15 relus identiques |

### Ce que le code de la machine impose

* `open` en écriture **écrase** ; `move` et `copy` **écrasent** si la
  destination existe. Le client n'écrit que sous un nom temporaire neuf et
  ne déplace que par `rename`, qui refuse un nom pris.
* Un SysEx reçu de plus de **1 024 octets** est abandonné **sans réponse** :
  le premier essai d'écriture est resté muet — un bloc de 1 024 octets
  codés en faisait 1 230. Le simulateur ne l'avait pas vu, il le rejette
  désormais aussi.
* Le bit 7 des noms se perd : « dièse » revient « di\nse ». Lecture
  tolérante ; ces noms — quatre fichiers parasites de macOS — sont mis à
  part.

### Ce qui existe maintenant

| | |
|---|---|
| `core/delugefiles.py` | le client USB : sonde, session, dossiers, lecture, écriture sans jamais écraser |
| `core/cardsync.py` | copie de travail, synchronisation à trois voies, mise à jour de la sauvegarde |
| `ui/cardwork.py` | l'orchestration : à la connexion, après chaque écriture, au retour dans la fenêtre — jamais pendant que la machine joue |
| Réglages ▸ Carte du Deluge | état, « Créer la copie de travail » / « Synchroniser maintenant », suppressions à confirmer, sauvegarde |
| `SDCard.read_only` | la sauvegarde s'ouvre en lecture seule ; chaque fonction qui écrit le vérifie |
| `midifollow` | le fichier de la 1.3, ses réglages lus ; « Deluge en direct » les constate |

### Les règles

* Ce que le Deluge change **descend** ; ce que l'application crée **monte**.
* Changé des deux côtés : les **deux versions** restent (« … (PC) »).
* Supprimé sur le Deluge : retiré de la copie, **gardé dans son
  historique**. Supprimé sur le PC : **proposé**, jamais fait seul.
* La sauvegarde : lue ; mise à jour **sur commande**, sans rien y
  supprimer, les versions remplacées gardées à côté.
* Ce que la sauvegarde a **seule** n'est jamais repris d'office, mais la
  musique en est proposée à la création de la copie : le journal de
  l'utilisateur montre qu'il avait créé, le 15 octobre, un kit
  `COMPAGNON 1` — enregistré par l'application dans la sauvegarde, jamais
  arrivé sur la carte.

### Pièges de méthode

* Mon Deluge simulé acceptait des messages que la machine refuse ; il les
  refuse maintenant. La règle reste : **un simulateur se vérifie contre la
  machine**.
* Les heredocs de l'outil Bash mangent les barres obliques inverses : des
  `\\n` devenus de vrais sauts de ligne, des continuations de ligne
  avalées. Écrire ce genre de correctif avec l'outil d'écriture.

### Vérifié

* **946 tests** (618 du cœur, 328 d'interface), sous pytest et
  sous unittest ; 15 garde-fous de cette passe éprouvés en les retirant.
* Réglages et index réels de l'utilisateur inchangés ; sauvegarde
  inchangée.

### À faire par l'utilisateur, une fois

Réglages ▸ Carte du Deluge ▸ **Créer la copie de travail** (le Deluge
branché). Au démarrage, l'application aura reconnu `SDCARD Deluge` comme
sauvegarde : elle s'y ouvre en lecture seule jusque-là.

---

## 3 novovicies. Le Deluge branché, en direct (15 octobre 2026)

> « Le logiciel doit être capable de travailler avec un déluge qui serait
> branché sur le port usb du PC. Il faut améliorer la compatibilité entre le
> logiciel et la machine et la capacité de travail en direct. »

Puis, en cours de travail : « J'ai branché le déluge en usb à mon pc. » Ce
qui suit a donc été **mesuré sur la machine**, et pas seulement déduit du
code de son firmware (`release_1_2_1`), qui a servi de plan.

### Ce qui existe maintenant

| | |
|---|---|
| `core/delugesysex.py` | le SysEx du firmware : identité, ping, message à l'écran, image OLED (complète, différences, abonnement), 7 segments, codages 7 bits portés de `util/pack.c` |
| `core/midiport.py` | SysEx en entrée et en sortie (tampons `MIDIHDR`, fil de recyclage), les trois câbles USB, l'instant d'arrivée de chaque message |
| `core/midifollow.py` | conversion exacte du firmware dans les deux sens, libellés français des 52 paramètres, provenance de la table |
| `core/delugelink.py` | `service()` : identité, aller-retour, écran recopié, tempo et lecture d'après l'horloge, notes tenues, son sélectionné d'après le retour MIDI Follow |
| `ui/livewindow.py` | la fenêtre « Deluge en direct » (Ctrl+D, pastille verte, page Réglages) |
| `ui/widgets/delugescreen.py` | l'écran de la machine, pixel pour pixel, agrandi d'un facteur entier |
| `tests/deluge_simule.py` | un Deluge simulé qui répond comme la vraie machine |

Dans l'existant : la pastille, machine connectée, ouvre la fenêtre en
direct ; la page Réglages montre ce que la machine a dit d'elle et les
réglages à faire sur le Deluge ; les outils de composition suivent son tempo
(`midi_follow_tempo`, actif par défaut).

### Mesuré sur la machine

| | |
|---|---|
| ports (Windows 11) | sorties `Deluge`, `MIDIOUT2 (Deluge)`, `MIDIOUT3 (Deluge)` ; entrées `Deluge`, `MIDIIN2 (Deluge)`, `MIDIIN3 (Deluge)` |
| identité | `F0 7E 7F 06 02 00 21 7B 01 00 00 00 01 02 01 00 F7` → **c1.2.1**, reçue en 2,8 ms |
| aller-retour | **0,31 à 0,39 ms**, compté à l'arrivée du pong |
| écran | 110 octets compressé, 888 brut, décodages identiques ; « SYNTH / TB01 », à l'endroit ; notre codeur redonne les 110 octets exacts |
| abonnement (mode 3) | une **différence pleine page**, pas une image ; ensuite, rien tant que l'écran ne change pas |
| « Faire signe » | une différence 3 ms plus tard (blocs 19 à 76), une autre à 801 ms quand le message s'efface ; l'écran revient à l'identique |
| application entière | connexion automatique au battement d'une seconde, fenêtre ouverte par la pastille, recopie, fermeture : **0 message court, 7 SysEx de lecture**, 0 tampon gardé |

**Pas encore vu sur la machine**, parce qu'il faut un geste de
l'utilisateur : l'horloge (lancer la lecture), le retour MIDI Follow
(régler Follow ▸ Channel A, puis Feedback), les notes jouées. Le simulateur
les couvre d'après le code du firmware ; c'est la prochaine mesure à faire,
câble en main.

### Ce que les mesures ont corrigé

1. **L'aller-retour s'affichait 41 ms** : il était compté au passage du
   service, toutes les 40 ms. Il se compte à l'arrivée du pong
   (`MidiMessage.arrived`). Et 0,3 ms arrondi à l'unité donnait « 0 ms » :
   `latency_text` garde une décimale sous les dix millisecondes.
2. **L'écran ne passait jamais « complet »** : l'abonnement forcé répond
   par une différence qui couvre tout l'écran, pas par une image. Mon
   simulateur envoyait une image — c'est pour cela que les tests n'avaient
   rien vu. Il répond désormais comme la machine.
3. **Fermer un port envoyait seize « All Notes Off » et un
   `midiOutReset`**, port des SysEx compris, y compris pendant mes essais
   « en lecture seule ». Le firmware n'en fait qu'un relâchement des notes
   reçues en MIDI — rien sur les sons ni sur le morceau —, mais c'était du
   bruit envoyé sans raison : un port qui n'a rien joué se ferme désormais
   sans rien envoyer.
4. Sans carte, la page Réglages annonçait la table MIDI Follow « lue dans
   MIDIFollow.XML sur la carte » : elle dit maintenant d'où elle vient.

### Ce que les rendus ont montré

* **Le tempo s'affichait en 10 points** au lieu de 30 : un `setFont`
  accepté, puis écrasé par la feuille de style de l'application. Passé par
  la feuille de style du label ; un test mesure la police réellement
  appliquée (il lit 10,0 avec l'ancien code).
* Recopie arrêtée, la fenêtre remettait **une image figée** au
  rafraîchissement suivant ; débranchée puis rebranchée, elle restait
  cochée sans abonnement, écran bloqué sur « En attente ». Corrigé, testé.
* Une page ouverte **après** l'arrivée de l'horloge gardait le tempo de son
  genre : elle le prend désormais à sa première visite. Le premier test le
  « prouvait » par hasard — 132 BPM, c'est aussi le tempo par défaut de
  l'acid, premier genre de la liste. Il joue maintenant à 111 BPM, qu'aucun
  genre ne donne.

### Deux pièges dans mes propres vérifications

* **Un `.pyc` périmé.** Mon script de retrait a remplacé un appel par un
  texte de *même longueur* et restauré le fichier dans la *même seconde* :
  Python, qui ne compare que la taille et la seconde, a gardé le code
  mutilé. Le rendu affichait « 0 ms » avec un source juste. Les essais de
  retrait tournent désormais avec `PYTHONDONTWRITEBYTECODE=1`.
* **Un rempart épinglé.** Trois classes de test « restauraient »
  `PlanDialog.exec` (et une `QMessageBox.exec`) en réaffectant la méthode
  héritée — le rempart de la suite —, qui restait collée sur la
  sous-classe. Sous pytest, qui suit l'ordre du fichier, `TestClicsReels`
  échouait ; sous unittest, qui trie les classes, rien ne se voyait.
  `mock.patch.object` partout, et `WidgetCase._aucun_rempart_epingle` échoue
  dès qu'un test l'oublie.

### Vérifié

* **902 tests** (583 du cœur, 319 d'interface), sous unittest
  **et** sous pytest ; chaque correctif éprouvé en le retirant.
* Réglages et index réels inchangés (`settings.json` 3fb1bea31e2e9db7,
  `library.db` 9e4f93ecc8779543), avant et après chaque passage.
* Rendus de la fenêtre et des réglages à 1440 et 980 px, face au simulateur
  (avec l'écran capturé sur la machine) et face à la vraie machine.

---

## 3 octovicies. Des morceaux pour le Deluge, depuis chaque outil (15 octobre 2026)

> « J'aimerais qu'il soit possible d'exporter les progressions créées sous forme
> de chanson pour qu'elles soient directement exploitables dans le Deluge. Faire
> de même avec tous les outils de création, ce logiciel est destiné à gagner du
> temps dans la création musicale avec le Deluge. » — l'utilisateur.

Le contrat est dans **SPEC §4.31** (module) et **SPEC §5.23** (interface). Ce
qui suit est ce qu'il faut savoir pour ne pas le défaire.

### Ce qui existe

`core/songwriter.py` fait d'une création un fichier `SONGS/*.XML` **neuf**, au
format c1.2.1 de la machine. Sept boutons, un par outil, passent par le même
parcours (`ui/songexport.py`) : construire, nommer, montrer le plan, confirmer
selon le réglage, écrire, indexer.

| Outil | Bouton | Morceau |
|---|---|---|
| Outils › Théorie | En morceau | un clip par partie avec les sons de l'écoute, batterie comprise |
| Outils › Rythme | En morceau | le motif, joué par le kit de l'écoute complété |
| Outils › Arrangement | Esquisse en morceau | sections enchaînées et arrangement complet |
| Kits | Motif en morceau | le kit de la carte, tel qu'en son fichier, et le motif d'essai |
| Générateur | Essayer en morceau | le son dans une phrase faite pour son rôle, sur la batterie du genre |
| Générateur › Kit | Kit en morceau | le kit construit et le rythme du genre |
| Découper (dialogue) | Écrire en morceau | le kit des tranches et un clip qui rejoue la boucle |

### Mesuré avant d'écrire : la résolution était fausse

Une mesure ne vaut pas 96 ticks mais **`96 << inputTickMagnitude`** : 192 dans
les 40 morceaux 3.x, **384 dans les morceaux c1.2.1** (mesuré sur les notes des
46 morceaux). Trois défauts visibles en venaient, corrigés et testés :

- la page Morceaux annonçait **2 à 4 fois trop de mesures** ;
- « Clip en MIDI » et « Morceau en MIDI » sortaient **2 à 4 fois trop lents** ;
- l'index gardait ces nombres : il relit une fois les morceaux
  (`scan.SONG_READER = "2"`), et `index_songs` — qui indexe un morceau neuf —
  ne marque pas cette relecture comme faite.

L'aide-mémoire de la Boîte à outils disait aussi « 1 536 ticks = 16 mesures » :
corrigé.

### Ce que le firmware impose, lu dans son code

Tout vient du tag `release_1_2_1` et des six morceaux c1.2.1 de la carte :

- un instrument est **intégré**, ses paramètres passent dans **chaque** clip
  (`soundParams`, `kitParams`, un `soundParams` par rangée de kit) ;
- l'arpège d'un synthé passe dans le clip avec sa synchro en **valeur interne**
  (7 devient 6 : TB01 et `DEFAULT.XML`) ;
- une note qui commence avant la fin de la précédente, sur la même rangée, est
  **ignorée** à la lecture : on raccourcit la première ;
- un clip retrouve son instrument par nom et dossier **sans la casse** : deux
  homonymes, et le second se tairait — les noms sont rendus uniques ;
- une section passe à la suivante après `numRepeats` boucles de son plus long
  clip ; en disposition « rangées », la suivante est celle du clip **d'en
  dessous**, d'où la première section en haut ; l'enchaînement ne part que si
  l'on **lance** une section pendant la lecture (PLAY seul fait tourner la
  première) ;
- **un `firmwareVersion` laissé dans un son ou un kit change la version de
  lecture de tout le reste du fichier** : un preset 3.x recopié tel quel aurait
  fait lire les clips suivants comme du 3.x. Retiré à toute profondeur.

### Un preset ancien : les conversions de la machine, comparées à la machine

En chargeant un preset ancien, la machine le convertit ; intégré tel quel dans
un morceau c1.2.1, il serait lu comme du c1.2.1. `upgrade_sound` / `upgrade_kit`
appliquent ces conversions (arpège éclaté et filtres FM avant c1.2.0, câbles
d'expression avant 4.0.0-beta, bornes en millisecondes avant 2.1.0-beta,
compensation de résonance avant 1.2.0 — défaut de `shiftVolumeByDB` compris).

**Contrôle** (`scratchpad/valider_integration.py`, lecture seule) : chaque
instrument des six morceaux c1.2.1 a été reconstruit depuis son preset
d'origine et comparé au morceau. **TB01 ressort à l'identique.** Le TR-808 sans
version (27 kits de la carte sont dans ce cas, dont les kits d'usine) ressort
identique pour tout ce qui dépend des conversions : bornes **à la trame près**,
y compris la règle « une fin qui dépasse de 45 trames au plus vaut la longueur »
(501 ms → 22 051 trames), résonances, câbles. Les écarts restants sont des
retouches de l'utilisateur sur la machine : valeurs de potentiomètre (multiples
de 2^25), automatisations, oscillateurs changés.

Trois bizarreries du firmware notées en chemin (SPEC §1.5) : le mode de filtre
éteint s'écrit `"flanger"` (`filterMap` n'a pas de nom pour `OFF`) et tout nom
inconnu se relit éteint ; `octaveMode="upDown"` se relit **aléatoire** ; les
câbles « range » d'avant 3.2 sont lus par toutes les versions.

### Défauts préexistants trouvés en chemin

- **Les vignettes de morceau s'affichaient à l'envers** dans la page Morceaux :
  le fichier commence par la rangée du bas (vérifié sur « Truc 1 » et
  « Nimp1 » avec leur défilement), la grille de l'appli dessine la première
  ligne en haut. `Song.preview_colors` retourne la matrice.
- **Les sons de l'écoute gardaient `arpMode="arp"`** quand le générateur leur
  avait donné un arpège : sans effet dans le rendu de l'appli, qui ignore
  l'arpégiateur, mais la machine l'aurait joué par-dessus l'arpège écrit.
  L'écoute et l'export partagent désormais `songwriter.part_presets`.
- **Le générateur écrivait `maxVoices="0"`** pour les sons non polyphoniques
  (basses et leads en legato ou mono, sons « auto »). La machine écrit 8 pour
  chacun des 94 sons des morceaux de la carte, quelle que soit la polyphonie,
  ne produit jamais 0 (son menu le remplace par 127) et compare chaque nouvelle
  voix à ce plafond. `synthgen` écrit désormais 8 ; un 0 hérité redevient 8
  dans un morceau. Aucun preset de la carte ne porte ce 0 : les deux seuls
  `maxVoices` de SYNTHS valent 8.
- **L'onglet Théorie débordait à 980 pixels** sous une barre horizontale,
  « Proposer » et le tempo coupés (déjà visible sur les rendus du 14) : ses
  listes peuvent rétrécir.

### Mes tests étaient fautifs, deux fois

Une vélocité attendue à 127 alors que la note fournie était déjà brute (100) ;
un « motif vide » qui ne l'était pas, la page s'ouvrant sur le motif du genre.
Le code était juste.

### Vérifié en retirant les correctifs

Onze garde-fous du module retirés un à un (`retirer_correctifs_songwriter.py`,
`retirer_trois.py`) : chacun fait échouer son test, et passe une fois rétabli.
Trois retraits ne prouvaient d'abord rien — l'un parce qu'un garde-fou était en
double (le nom `DEFAULT`, simplifié), deux parce que mon retrait ne reproduisait
pas le vrai défaut ; corrigés et refaits. Même chose pour l'orientation des
vignettes.

### Ce qu'il reste à vérifier **sur la machine**

Rien de ce qui précède n'a été chargé sur un Deluge. Au premier essai :

1. un morceau « En morceau » de la Théorie : sons, tempo, gamme (mode gamme des
   clips), boucles courtes ;
2. une esquisse : PLAY fait-il tourner l'intro seule ? lancer la deuxième
   section déroule-t-il la suite jusqu'à l'arrêt final ? la vue arrangement
   joue-t-elle les instances plus longues que leur clip en boucle ?
3. un « Motif en morceau » sur le **TR-808** : les pads sonnent-ils comme le
   kit chargé directement (bornes, volumes) ?
4. le nom des clips et la vignette dans le navigateur de morceaux.

### Le vocabulaire écrit, comparé à celui de la machine

`scratchpad/vocabulaire_ecrit.py` relève chaque couple (balise, attribut) des
morceaux écrits ici et le cherche dans les morceaux écrits par la machine.
Restent dix couples, tous lus par le firmware mais omis par lui à leur valeur
par défaut : `clippingAmount="0"`, `<midiKnobs>` vide, `transpose`, `cents` et
`retrigPhase` d'un oscillateur à échantillon, `fileName` vide, `transpose` d'un
synthé. **Ce contrôle a trouvé un défaut** : la page Kits intégrait un kit
ancien sans passer la carte, et ses bornes en millisecondes restaient telles
quelles — la machine les aurait ignorées et joué chaque échantillon en entier.
`pattern_song(sd=…)` ; testé en cliquant sur un vrai kit 2.x de la carte
jetable, et prouvé en retirant le correctif.

### Contrôles

847 tests au vert (544 du cœur, 303 d'interface). Empreintes de `settings.json`
et `library.db` identiques avant et après chaque script et chaque suite. Rendus
PNG à 1 440 et 980 pixels, tous les onglets, sur la vraie carte. Le dossier
`SONGS` de la carte n'a reçu aucun fichier : les essais écrivent dans des
cartes jetables.

---

## 3 septvicies. La façade : refonte graphique d'après le guide (14 octobre 2026)

> « Retravailler entièrement le design de l'UI de l'application. Celle-ci
> doit être moderne, intuitive et respecter le thème de couleur du guide
> deluge. Le design actuel est trop classique et manque cruellement de
> fun. » — l'utilisateur.

Les règles qui en sortent sont dans **SPEC §2 (troisième temps)** et
**SPEC §5.22**. Ce qui suit est ce qu'il faut savoir pour ne pas défaire le
travail.

### Le diagnostic, sur images

Avant d'écrire une ligne : les 23 écrans rendus en PNG sur la vraie carte
(neuf pages, tous les onglets). L'interface reprenait la **palette** du guide,
pas ses **signatures**. Barre de menus Windows posée sur un bandeau, rail de
texte, neuf pages faites des mêmes panneaux sombres et de tableaux. Et un
accent unique — le cyan choisi par l'utilisateur — qui se battait avec la
couleur de la page : bouton cyan sur la page magenta du générateur, à côté
d'encodeurs dorés.

Le guide, lui (`Guide deluge/build/style.py`, `figs_schema.py`,
`figs_couverture.py`, `figs_oled.py`) : un treillis de circuits
multicolores sur la couverture et chaque ouverture de partie, des pads
lumineux avec halo, des pads éteints « comme une diode au repos », l'écran
OLED noir et cyan, des capitales espacées, et **une couleur dominante par
partie**.

### Ce qui a été fait

- **`ui/art.py`** trace les algorithmes du guide au QPainter : le treillis
  (`circuit`, en cache, déterministe par graine), le pad allumé, le pad au
  repos, le halo.
- **Chaque page porte sa couleur jusque dans ses contrôles** : bouton
  principal (pad allumé qui rayonne), sélections, onglets en pastilles,
  cases, curseurs, fenêtres de dialogue qu'elle ouvre. Forme d'onde,
  enveloppes, courbe de filtre et spectre prennent la couleur de la page ;
  les encodeurs restent dorés, comme sur la machine.
- **La façade** : une seule barre du haut, menus intégrés, logotype de la
  couverture, **écran OLED** (la carte, son contenu, et chaque message de la
  barre d'état en surimpression, qui défile s'il est long), pastille du
  Deluge, touche de lecture ronde, filet lumineux à la couleur de la page.
  La colonne de gauche est une **rangée de pads** : veilleuse de leur
  couleur, allumage animé, chiffre du raccourci.
- **Les pages** : en-tête « ouverture de partie » (pad, titre en capitales,
  treillis qui s'allume à l'affichage) ; titres de section sur une ligne
  (petit pad, capitales espacées, filet) ; tuiles-pads ; note de santé dans
  une couronne d'encodeur ; répartition des échantillons en segments ;
  grilles de pads avec halo et reflet ; état vide animé (l'emblème du guide
  qui joue, le pad de la page en médaillon) ; écran de démarrage composé
  comme la couverture.
- **Les listes** gagnent une pastille de couleur devant la catégorie des
  échantillons et des presets, comme la couleur d'un clip sur la machine ;
  leurs lignes passent de 24 à 28 px.
- La couleur d'accent des réglages devient celle de **la façade**. Le texte
  de la carte « Apparence » le dit.

### Une règle de Qt qui commande toute la feuille de style

La feuille posée sur une page l'emporte **toujours** sur celle de
l'application, quelle que soit la spécificité des sélecteurs. D'où la
séparation de `theme.py` en deux parties : toute propriété de couleur d'un
contrôle vit dans la partie colorée, **avec tous ses états**. Sinon un bouton
désactivé garderait le fond vif de la page. Un test vérifie la présence des
états, un autre que chaque page pose bien sa couleur.

### Ce que la mesure a trouvé

| sur la carte de l'utilisateur | mesure | correction |
|---|---|---|
| bouton principal violet / indigo | bas 4,43, haut 4,42 | `lit_fill` pousse chaque extrémité à 4,5 |
| barre d'actions à 980 px | 6 boutons coupés en plein mot, ajusteur à l'état 0 | réveil à l'affichage, boutons « non masqués » |
| tableau de bord à 980 px | 900 px demandés pour 720 visibles | tuiles sur 2 colonnes, panneaux empilés |
| phrase « Copie dans un dossier… » | 900 px de largeur minimale | retour à la ligne |
| répartition des échantillons | la jauge se dessinait sur le nom du dossier | politique fixe du libellé élidé |
| `QMessageBox` | « Yes », « No » | traduction `qtbase_fr` de PyQt6 chargée |

**Tous, sauf le premier, dataient d'avant la refonte** (le premier tient aux
dégradés qu'elle a introduits). Ils ne se voyaient qu'à 980 px, en faisant
défiler le tableau de bord, ou en ouvrant une question — ce que mes captures
précédentes ne faisaient pas. Le script de rendu photographie désormais le
bas des pages qui défilent.

L'ajusteur de la barre d'actions mérite une note : il ne comptait que les
boutons *visibles*. Or la première taille d'un en-tête arrive avant que la
page ait montré ses enfants ; si la fenêtre ne change plus de taille
ensuite, rien ne le réveillait. La mesure à la main du 12 octobre
(§3 unvicies) passait parce qu'elle redimensionnait la fenêtre.

### Mes tests étaient fautifs

Le réveil de l'ajusteur a fait échouer quatre tests. Ils lisaient le
**texte affiché** d'un bouton (`_similar_button.text()`) ; la plateforme
« offscreen » n'a aucune police, la barre s'y replie dès l'affichage, et le
nom part dans la propriété `libelleComplet`. Ils lisent maintenant le nom
(`_libelle`), comme le faisait déjà l'aide `_bouton`. Un cinquième attendait
le mot « accent » dans le message de changement de couleur ; il y est
revenu.

### Vérifié en retirant les correctifs

Chaque correctif retiré seul fait échouer son test, sauf un : l'ajusteur a
deux moitiés qui suffisent chacune (réveil à l'affichage, comptage des
boutons non masqués). Les deux retirées ensemble, le test échoue ; remises,
il passe.

### Contrôles

- Empreintes de `settings.json` et `library.db` réels identiques avant et
  après chaque rendu et chaque suite ; aucun fichier de la carte modifié
  (`find -newer` sur un repère posé au début).
- `main.main()` lancé pour de vrai trois secondes, configuration isolée :
  code 0, aucune exception, aucune erreur au journal.
- Aucun import inutilisé dans les modules touchés (analyse de l'AST).
- Rendus regardés à 1 440 × 900 (tous les onglets, bas des pages), à
  980 × 640, et sans carte.

Tests : **798 au vert** (762 + 35 pour la façade + 1 pour la traduction).

---

## 3 sexvicies. Audit d'usage réel : la carte et le journal de l'utilisateur (14 octobre 2026)

Demande : « continuer à améliorer le logiciel ». Plutôt que de choisir au jugé, deux sources
réelles : **le journal de l'utilisateur** (`%APPDATA%/DelugeCompanion/app.log`, lu sans le
modifier) et **un audit d'usage** — la fenêtre complète sur la vraie carte, avec une copie de
son index réel et une configuration isolée, en ne faisant que naviguer. Script : il chronomètre
le démarrage et chaque page, compte les diagnostics de santé, mesure les blocages du fil de
l'interface (minuteur de 20 ms) et relève le journal. Empreintes de `settings.json` et de
`library.db` identiques avant et après, aucun fichier de la carte modifié.

### Ce que le journal disait

- Le diagnostic de santé tournait **deux fois de suite** à chaque démarrage et à chaque retour
  au tableau de bord.
- Le 11 octobre, « Relier automatiquement » avait réécrit 125 références dans 10 presets
  REPHAZER ; le diagnostic suivant gardait les mêmes 12 anomalies. Vérifié sur la carte : les
  125 fichiers cités **existent tous**. La réparation avait réussi ; l'index ne l'avait pas vue
  (défaut corrigé depuis par l'audit du 12 octobre — reproduit sur une carte jetable : le code
  actuel remet l'index à jour), mais **l'index de l'utilisateur était resté faux** : 125
  « manquants » et une note de 85 au lieu de 90, sans rien pour le rattraper.

### Ce que l'audit a mesuré, et corrigé

| Sur la carte de l'utilisateur | Avant | Après |
|---|---|---|
| Fenêtre créée et affichée | 2,29 s | **0,52 s** |
| Diagnostics au démarrage (fil de l'interface) | 2 × 0,98 s | 2 × 0,20 s, dont un après la mise à jour de l'index |
| Fenêtre figée au retour sur le tableau de bord | **2,0 s** | **0,24 s** |
| Recherche des fichiers parasites | 0,82 s | **0,037 s**, plan identique (1 564 opérations) |

- **Chaque page se rafraîchissait deux fois par visite** : `go_to` la rendait visible — son
  `showEvent` la rafraîchit — puis appelait `refresh()` à son tour. Il ne le fait plus que si
  la page était déjà affichée. Même doublon après chaque analyse : le tableau de bord se
  rafraîchissait puis émettait `scanFinished`, auquel la fenêtre répond en rafraîchissant la
  page visible ; il ne se rafraîchit plus lui-même que si personne n'écoute.
- **90 % du diagnostic** partaient dans `organize.plan_purge_junk` : `rglob` parcourait tout,
  corbeilles comprises, puis un chemin relatif et un `stat` par fichier (16 936). Désormais
  `os.scandir`, dossiers ignorés élagués, tailles lues dans l'entrée de répertoire et gardées
  dans le plan (`Plan.size`) — le diagnostic les redemandait au disque.
- La docstring du tableau de bord affirmait « le diagnostic lit l'index, il est donc
  instantané » : 0,96 s mesuré. Corrigée avec les chiffres.
- **Index mis à jour au démarrage** (réglage « Mettre l'index à jour au démarrage », actif par
  défaut) : analyse incrémentale en arrière-plan, en lecture seule. Sur la copie de l'index
  réel : 10 fichiers relus en 0,20 s, manquants 125 → 0, note 85 → 90. Le message de la barre
  d'état dit ce qui a été relu, pas le contenu entier de la carte.
- **L'espace d'un dossier n'est pas celui d'une carte** : une copie dans un dossier affichait
  « 125,1 Gio d'espace libre » et « 349,6 Gio utilisés sur 474,7 Gio », chiffres du disque de
  l'ordinateur. `SDCard.is_volume` distingue la racine d'un lecteur ; sinon la tuile dit
  « Libre sur le disque » et la carte « Copie dans un dossier… ».

> ⚠️ **Mon test était fautif.** `test_focus_sur_la_recherche` a échoué une fois dans la suite
> complète, jamais seul : il exigeait `hasFocus()`, donc une fenêtre **active**, ce que
> l'application ne décide pas quand d'autres fenêtres de test vivent encore. Il vérifie
> maintenant que le champ est le widget de focus de sa fenêtre (`focusWidget()`), et échoue
> toujours si la commande ne fait rien.

Tests : **762 au vert**.

---

## 3 quinvicies. Outils de composition : du fragment au morceau (14 octobre 2026)

Demande : « améliorer encore les outils de composition ». L'inventaire de la Boîte à outils
montrait des pièces qui ne se rejoignaient pas : on proposait des accords, une basse, une
mélodie, un rythme et une structure, mais **le rythme ne s'écoutait pas**, « Motif du
genre » rendait toujours le même motif, **l'export MIDI du rythme était figé à 128 BPM**
quel que soit le genre (défaut), la batterie ne jouait jamais avec l'accompagnement, et
l'arrangement n'était qu'un tableau de durées.

### Écouter et varier le rythme

- **Batterie synthétisée** (`render.synth_drum`, 22 rôles) pour écouter sans carte, ou une
  piste que la carte ne couvre pas ; avec une carte, les pistes sont jouées par un kit bâti
  dans la bibliothèque (`kitgen.build_kit`). Mesuré : grosse caisse à 47 Hz, toms dans l'ordre
  grave → aigu (97, 136, 187 Hz), caisse claire vers 4 kHz, charleys vers 12 kHz. Le premier
  jet était faux — grosse caisse à 1,65 de crête, caisse claire à 11,7 kHz — parce que le bruit
  n'était éclairci que par une différence première : il est désormais filtré par bande.
- **Variation** (`rhythm.variation`) : notes fantômes, charleys serrés, percussion
  euclidienne, grosse caisse syncopée, charleston ouvert. Sur 440 variations (22 genres ×
  20 graines), **aucun coup de grosse caisse, de caisse claire ou de clap retiré**. Les
  charleys serrés sont écartés des genres clairsemés : ils multipliaient par 4,6 la densité
  d'un motif dub.
- Le tempo suit le genre, et le fichier MIDI porte le tempo affiché.

### Assembler

- **Batterie dans l'accompagnement** (case « Batterie ») : le rythme de l'onglet Rythme,
  ou celui du genre, sous les accords, à l'écoute comme en MIDI (piste 10).
- **Basse acide** (style « acide », par défaut en acid) : deux mesures de 303 en alternance,
  silences, accents, octaves et glissés. Un glissé chevauche la note suivante, **toujours
  d'une autre hauteur** : deux notes identiques qui se chevauchent se coupent en MIDI.
- **Autre accord** : l'accord choisi est remplacé par un autre de **même fonction**
  (tonique, sous-dominante, dominante ; `theory.FUNCTIONS`, `theory.substitute`), et la
  fonction s'affiche dans la liste. Sur 1 728 remplacements : même fonction 100 %, aucune
  note hors gamme, progression d'origine intacte ; dans 1,7 % des cas le seul candidat
  égale un voisin, accepté faute d'autre choix. La fabrication d'un accord a été extraite de
  `progression()` : vérifié sur 4 800 cas, sa sortie est identique à l'octet près.
- **Esquisse du morceau** (`core/sketch.py`, onglet Arrangement) : la progression tourne sur
  tout le modèle du genre ; chaque section ne garde que les parties de son rôle (intro et
  fin : batterie légère et accords ; montée : + basse, arpège ; sommet : tout, mélodie
  comprise, batterie variée et crash d'entrée ; cassure : ni grosse caisse ni basse). Sur les
  22 genres : **aucune note hors de ses sections**, pas de caisse claire en intro, pas de
  batterie en cassure, quelques millisecondes de calcul. « Écouter la section » joue le
  début d'une section (8 mesures au plus) ; « Esquisse en MIDI » écrit le morceau entier,
  une piste par partie, **le nom des sections en repères** (méta-événement 0x06, affiché
  par les logiciels de MAO).

> ⚠️ « Refrain final » contient « final » : il était pris pour une fin. Les mots du sommet
> sont cherchés avant ceux de la fin (`sketch.section_kind`).

### Ce que les images ont montré

- L'onglet Théorie **débordait à 980 pixels** après l'ajout de la case « Batterie » :
  « Proposer » coupé, barre de défilement horizontale. Les parties facultatives ont leur
  ligne.
- Le motif en texte de l'onglet Rythme n'a **jamais** été en chasse fixe : le thème visait
  `QPlainTextEdit#Mono` (nom d'objet) et le widget portait la propriété `role="mono"`. Les
  colonnes s'alignent maintenant.
- La colonne « Position » de l'arrangement était tronquée depuis que « Parties » s'étire.

Tests : **757 au vert**.

---

## 3 quatervicies. Générateurs et composition : seconde passe (14 octobre 2026)

Demande : « continuer à améliorer l'aide à la composition et la génération des presets et
kits ». Même méthode que la passe précédente : mesurer d'abord sur la carte ce que le
générateur fait autrement que l'utilisateur et les presets d'usine.

### Presets : les traits que la première mesure ne regardait pas

Le contrôle de plausibilité ne portait que sur des réglages numériques. Un second contrôle,
par traits, compare la part des presets qui portent chaque réglage, rôle par rôle (911 presets
réels, 880 tirages par rôle) :

| Trait | Presets réels | Avant | Après |
|---|---|---|---|
| Portamento (basses / leads) | 33 % / 25 % | **jamais** | 33 % / 26 % |
| Saturation `clippingAmount` | 27 à 56 % selon le rôle | **jamais** (curseur de saleté > 0,5 seulement) | 25 à 56 % |
| Synchro du délai | croche dominante, double-croche pour nappes et bourdons | toujours double-croche | idem réel |
| Passe-haut sur les basses / bourdons | 23 % / 49 % | 0 % / 0 % | 17 % / 42 % |
| Effet de modulation (basse… arpège) | 15 % … 38 % | 35 % pour tous | 16 % … 40 % |
| Basses : poly / legato / mono | 34 / 33 / 23 % | 13 / 22 / 65 % (poids) | 37 / 36 / 25 % |

Le glissé dépend du genre (`GenreProfile.glide`) : 70 % des basses acid — la 303 —, 38 % en
techno, 20 % en house. Contrôle numérique : **98 %** (102/104), **6 signatures de genre sur 6**.

> ⚠️ **Ma mesure était fausse, et elle cachait un défaut du produit.** Les deux contrôles
> tiraient les 22 genres avec les **mêmes douze graines** : `random.Random(graine)` donnait
> la même suite aux 22 genres, donc 12 tirages distincts et non 264. Les pourcentages de
> mode de jeu ou d'effet n'avaient pas de sens — le « 5 signatures sur 6 » d'un premier essai
> venait de là. Côté produit, cela voulait dire que **la graine 42 faisait les mêmes choix
> dans tous les genres**, comme le générateur de kits avant sa correction. La graine mêle
> désormais graine, genre et rôle ; conséquence assumée : une graine ne redonne plus le son
> d'avant cette passe (la reproductibilité vaut à version égale).

Écartés après mesure : les **tables d'onde** (aucun fichier sur la carte, aucun preset qui
s'en sert) et les presets à échantillon (4 %).

### Kits : l'espace et l'équilibre des vrais kits

Mesuré sur les 523 rangées : grosse caisse, caisse claire, clap et charleys au centre ; toms
en éventail (tom grave +9, tom aigu −12), ride à droite (+5), crash et shaker un peu à gauche.
41 kits sur 43 règlent le volume rangée par rangée ; médianes par rôle (grosse caisse 38,
caisse claire 39, ride 30). Le générateur mettait tout au centre et la grosse caisse à 44 :
`ROLE_PAN`, `ROLE_VOLUME`.

**« Autre son »** (page Générateur, onglet Kit) remplace l'échantillon de la rangée choisie :
même machine d'abord, puis une machine voisine du genre ; jamais un fichier déjà dans le kit
ni un son déjà essayé pour la rangée — sans cette mémoire, une famille de deux caisses
claires faisait la navette à chaque clic (`kitgen.reroll_row`).

Écarté : **équilibrer les rangées selon le niveau de leurs fichiers.** Il faudrait la loi
du paramètre `volume` du firmware, que je n'ai pas établie ; je ne code pas sur une loi
supposée.

### Composition

- **Couleur des accords** (`theory.colored_chord`, choix « Couleur » de la Boîte à outils) :
  triades, septièmes, neuvièmes, suspendus. Les ambiances jazz et house prennent des
  septièmes, deep et ambient des neuvièmes : en triades, une progression « jazz » sonnait
  comme une comptine. Les neuvièmes se jouent **sans fondamentale** (tierce, quinte,
  septième, neuvième — la basse tient la fondamentale) ; jouées avec, la conduite des voix
  en faisait une grappe de secondes (Sol9 = fa-sol-la-si). Pas de neuvième mineure (le ii de
  la mineur reste demi-diminué), pas de « sus4 » sur une quarte augmentée. Mesuré sur
  73 728 accords : **0 note hors gamme**, noms reconnus (`m9`, `maj9`, `sus2`…).
- **Mélodie** (`accomp.melody_part`, case « Mélodie », bouton « Autre mélodie ») : phrases
  de quatre mesures A A B fin, la mesure 2 reprenant la 1 en marche sur le nouvel accord.
  Sur 132 000 notes (22 genres × 12 ambiances × 3 gammes) : **0 note hors gamme**, **100 %
  des temps forts sur une note de l'accord**, intervalle médian d'un ton (96 % au plus une
  quarte, aucun saut au-delà de l'octave), **fin sur la fondamentale du dernier accord dans
  100 % des cas**. L'allure suit le genre (posée, chantante, syncopée). En MIDI, la mélodie
  est la quatrième piste, canal 4.

> ⚠️ **Une réécriture retirée après mesure.** J'avais aussi refait `voice_leading` pour
> qu'elle choisisse un renversement entier plutôt que de déplacer chaque note. Mesuré à
> voicings égaux sur 41 472 accords : aucune grappe dans un cas comme dans l'autre, même
> mouvement moyen (2,70), dérive 2,0 contre 2,2 demi-tons. C'est le voicing sans
> fondamentale qui supprimait les grappes, pas la nouvelle conduite : l'ancienne fonction
> est restée. Le test qui garde ce point a été renommé en conséquence, et il échoue si l'on
> remet la fondamentale dans les neuvièmes.

Écarté : **importer un fichier MIDI sur le Deluge.** Le firmware c1.2.1 n'en lit pas (aucune
trace de `MThd` ni de `.mid` dans ses sources) : les exports MIDI servent au logiciel de MAO.

Tests : **733 au vert**. Les nouveaux échouent sans les modifications ; vérifié par retrait
pour les deux qui auraient pu passer par hasard (effet de modulation par rôle, neuvièmes).

---

## 3 tervicies. Générateurs et aides à la composition (13 octobre 2026)

Demande de l'utilisateur : « améliorer les fonctions de génération de preset et de kit ainsi
que toutes les fonctions d'aide à la composition ». Méthode : comparer ce que produisent les
générateurs à **ce que contient la carte**, et vérifier le format dans le **code source du
firmware c1.2.1** (`release_1_2_1` du dépôt communautaire, celui de la machine) quand la carte
n'a pas d'exemple. Tout ce qui suit est mesuré ; les scripts sont décrits pour être refaits.

### Ce qui ne marchait pas sur la machine

- **L'arpégiateur des presets générés restait éteint.** La 1.2.1 ne lit plus l'attribut
  `mode` d'un fichier qui se déclare c1.2.0 ou plus récent (`sound.cpp`) ; nos presets sont
  estampillés c1.2.1. Il faut `arpMode="arp"`, `noteMode`, `octaveMode` — écrits désormais,
  `mode` gardé pour les vieux firmwares. Les 59 arpèges de la carte sont tous dans de vieux
  fichiers, d'où l'absence d'exemple.
- **Les kits générés coupaient chaque coup.** Rangées en `loopMode` 0 (CUT : l'échantillon
  s'arrête avec la note) et enveloppe à sustain nul. Les 523 rangées réelles : `loopMode` 1
  (ONCE) dans 83 %, enveloppe ouverte A0 D20 S50 R0, `velocity → volume` sur 505. Le firmware
  choisit ONCE sous 2,002 s (`sample_browser.cpp`, `slicer.cpp`) : `model.repeat_mode_for()`.
  Le découpeur écrivait aussi CUT en croyant « ne pas boucler ».
- **`syncLevel` décalé d'un cran** dans la table de la Boîte à outils (7 annoncé croche) :
  calcul du firmware (`sync.cpp`), `2^(3 − niveau)` mesures — 7 = double-croche, ce que
  confirment les 23 arpèges synchronisés de la carte. Le générateur tirait des arpèges en 9
  (quadruple-croche).

### Presets : plus plausibles, genres préservés

Script de mesure : pour chaque rôle, la médiane générée tombe-t-elle dans l'écart
interquartile des vrais presets de la même catégorie (911 presets, `category_guess`) ?
L'enveloppe 2 est exclue (les vrais presets la laissent à sa valeur par défaut). Six
signatures de genre sont contrôlées en même temps (résonance acid > house, unisson trance >
deep house, réverb ambient > techno…).

| | Avant | Après |
|---|---|---|
| Plausibilité | 58/104 (**56 %**) | 101/104 (**97 %**) |
| Signatures de genre tenues | 5/6 | **6/6** |
| `velocity → volume` présent | au hasard | **100 %** (médiane 45 ; carte 50) |

Les écarts corrigés allaient tous dans le même sens : résonance médiane 15,5 contre 4 à 7,
unisson 5 sur les nappes contre 1, délai 20 partout, réverbération 20 sur les basses contre
0, basses sans tenue (sustain 3 contre 35), jamais de ring mod pour les effets (21 effets
réels sur 41). Les trois écarts restants (résonance des leads, désaccord des nappes, câbles
des bourdons) viennent des genres et sont laissés : niveler au-delà effacerait leurs
différences.

Et trois nouveautés : la **FM accordée** (`Sound.modulator1/2`, tirés dans la distribution
des 145 presets FM de la carte — l'unisson d'avant donnait la même couleur à tous), le
**LFO synchronisé** par genre (80 % en dubstep : c'est le « wobble »), et l'**aperçu FM**
qui module enfin avec les modulateurs (centroïde 6 100 Hz contre 5 012 Hz à l'unisson).

### Kits : autour d'une machine

`SAMPLES/DRUMS` est la bibliothèque d'usine, rangée par instrument et nommée par machine
(« 909 Kick dry », « Linndrum Snare ») ; huit banques d'artistes couvrent 4 à 7 rôles. Le
kit se bâtit désormais autour d'une **famille** (`kitgen.family_of`), choisie selon le genre
(`GENRE_AFFINITY` : 909 pour la techno, CR78/KR55 pour le lo-fi, 808 pour l'electro).

| Sur 60 kits (6 genres × 10 graines) | Avant | Après |
|---|---|---|
| Familles par kit | 9,9 | **1,9** |
| Rôles remplis | — | 620/620 |
| Rôle confirmé par le nom ou le dossier | — | 100 % |
| Échantillons distincts | 142 (sur 40 kits) | 158 |

> ⚠️ **Deux pièges trouvés en mesurant.** Le tirage se faisait dans les 12 premiers
> candidats **par ordre alphabétique** : 62 grosses caisses sur 74 ne sortaient jamais. Et
> mon motif de fichier numéroté (`07-KICK`) attrapait « 909 Snare » : la 909 semblait n'avoir
> ni caisse claire ni clap, et n'était jamais choisie — le défaut était dans mon expression.

L'analyse rangeait aussi les catégories « Hatc », « Toml »… (`title()` sur un chemin en
minuscules) : elles reprennent l'orthographe du Deluge.

### Aides à la composition

- **Progressions nommées juste** : le VI de la mineur s'appelait « La » (note grave après
  conduite des voix, qualité ignorée) ; c'est « Fa », et les noms suivent la **tonalité** —
  do mineur s'écrit avec Lab, pas Sol# (`theory.scale_spelling`). Chaque accord porte sa
  basse ; « ø7 » pour le demi-diminué.
- **Gammes du Deluge** : `deluge_mode_notes` rend la vraie gamme pour c1.x, avec le nom que
  la machine affiche (`deluge_scale_name` : `PENTATONIC MINOR`, `HIRAJOSHI`… ou `USER`) ;
  Marva et Arabian ajoutées.
- **Accompagnement** (`core/accomp.py`, nouveau) : basse en sept styles, accords en cinq
  rythmes, arpège ; chaque genre a ses habitudes. **Écouter** joue les parties sur des sons
  générés pour le genre (`render.render_parts`, quatre mesures en ~1 s) ; **En MIDI** écrit une
  piste par partie, chacune sur son canal.
- **Rythme** : vélocités en pour-cent (l'ancien 105 ± 6 écrêtait tous les accents à 127), vrai
  break **amen**, two-step de **drum and bass**, motifs trance, psytrance, motorik, synthwave,
  boom bap ; **polyrythme** exact (3 contre 4 sur 16 pas mettait 4 coups au 3) ; **grooves MPC**
  aux vrais pourcentages (les anciens « MPC 16B », « MPC 54 » n'existaient sur aucune MPC) avec
  l'équivalent du swing du Deluge ; « Appliquer » **ne plantait plus au second clic** et ne
  cumule plus (`Step.grid`, `straighten`) ; le jeu sur la machine garde le swing.
- **Générateur** : « Varier dans le générateur » depuis la page Presets (le signal existait
  sans être relié), « Fondre » (le morphing existait sans commande).
- Modèles de structure pour les 22 genres ; aide-mémoire corrigé (gammes, `syncLevel`,
  arpégiateur c1.x, rangées de kit).

Les tests de cette passe échouent tous sans les modifications, sauf « un preset soustractif
n'écrit pas de modulateur », qui garde la frontière de la nouveauté. Suite complète :
**709 tests au vert** en 106 s.

### La suite de tests ne se fige plus en silence

Deux fois dans la journée, la suite complète (~110 s d'habitude) a tourné plus de dix
minutes sans rien écrire ; cinq passages d'affilée sous surveillance n'ont pas su le
reproduire. **Cause exacte non prouvée.** Le code montre en revanche une porte ouverte : à
la fin d'un test, les classes rétablissaient les **vrais** dialogues avant que
`tasks.stop_all` et `processEvents` n'aient vidé la file, et le contexte n'était jamais
marqué fermé — un résultat tardif atteignait donc la page, et toute fenêtre modale réelle
attend hors écran un clic qui ne vient jamais. Quatre protections dans les tests :

- **plus de modale réelle** : `setUpModule` remplace chaque dialogue bloquant (`QMessageBox`,
  `QFileDialog`, `QInputDialog`, `QDialog.exec`) par un refus qui répond « non » et le
  note ; le test en cours **échoue en nommant la fenêtre**. Les classes qui rétablissent
  « l'original » rétablissent désormais ce refus. Contre-épreuve : sans lui, le test
  `TestRempartsDeLaSuite` se fige (tué au bout de 20 s) ; avec, il passe en 45 ms ;
- `PageCase.tearDown` marque le contexte fermé **avant** d'arrêter les fils : `Page.guard`
  ignore alors les résultats tardifs, comme dans l'application ;
- un **chien de garde** (`faulthandler`) : un test d'interface qui dépasse 120 s écrit la
  pile de chaque fil et arrête le processus. Si un blocage revient, l'échec ou la pile dira
  où ;
- **aucun port MIDI réel** : `connect` sans nom de port ne choisit que le Deluge, et
  `midi_autoconnect` vaut « oui » par défaut. Deluge branché pendant la suite, les fenêtres
  principales des tests auraient pris ses ports et le test qui clique tout lui aurait envoyé
  la note d'essai des Réglages. Les tests d'interface ne voient plus aucun port ; le seul
  test qui ouvre un vrai port (`TestMidiPort`) écarte le Deluge, à qui il aurait envoyé un
  CC 74 — la coupure du filtre en MIDI Follow.

⚠️ Piège rencontré en écrivant le test : lancer un cas imbriqué **par une suite**
(`loadTestsFromTestCase(...).run()`) rejoue `setUpModule` et `tearDownModule` du module —
qui a rétabli les vrais dialogues au milieu de la suite, et le test suivant s'est figé.
Lancer le cas seul (`Cas("test").run(resultat)`).

---

## 3 duovicies. Audit des bugs et incohérences (12 octobre 2026)

Relecture complète du cœur et des pages, chaque défaut **mesuré sur la carte** avant
correction. Les 19 tests de `TestAuditOctobre` (test_core) et les trois ajoutés à
test_ui échouent tous sur le code d'avant : vérifié en retirant les corrections.

### Ce qui abîmait des fichiers

- **« Dupliquer » perdait des données dans 516 presets sur 911.** `SynthPreset.copy()`
  jetait le document d'origine : modulateurs FM (145 presets, le son changeait),
  synchro d'oscillateur, affectations MIDI, compresseur. La copie garde désormais le
  document. Mesure après : **911 sur 911** sans aucune valeur perdue.
- **`depthControlledBy` réécrit faux** : une seule source de profondeur lue, réécrite
  avec la source du câble *extérieur*. « 5. Boc Pad » en a deux (`lfo2`, `random`).
  `PatchCable.range_amount` est remplacé par `depth_cables`.
- **Câbles et tranches recréés à neuf** à chaque enregistrement : `rangeAdjustable`
  (151 presets) disparaissait. Ils sont maintenant réutilisés, appariés par
  source/destination ou par fichier. `polyphonic="1"` n'est plus traduit s'il n'a pas
  changé ; la dernière tranche ne reçoit plus de `rangeTopNote="127"`.
- **`wav.convert` effaçait `smpl`, `cue `, `acid`, `LIST`…** : 228 fichiers portent un
  bloc `smpl`, 184 avec une boucle. Toute correction audio les effaçait. Ils sont
  reportés, positions recalées si la fréquence change ou si le silence de tête est rogné.
- **Rogner un fichier cité par un preset** mettait ses bornes à l'échelle alors que le
  contenu avait *reculé* : la tranche jouait le mauvais passage. Ces fichiers sont
  maintenant écartés du rognage, comme ceux des morceaux.
- **Restaurer après un rééchantillonnage** laissait les bornes à l'échelle du fichier
  converti. `samplefix.restore` les recale en sens inverse.
- **Recentrer un fichier chaud l'écrêtait** (5 des 17 fichiers à continu). La page Santé
  s'en gardait déjà ; le traitement par lot, non. `convert` abaisse le gain au lieu
  d'écrêter.

### Ce qui pouvait casser des références

- **Doublon supprimé malgré une réécriture ratée** : `relink_many` avalait en silence
  les XML illisibles et les écritures refusées, puis `Plan.apply` supprimait. Il les
  rapporte (`failures=`) et le doublon est gardé.
- **Noms avec `&`** : le pré-filtre cherchait le nom brut, le XML contient `&amp;`.
- **`dxml.save` écrasait même si la copie `.bak` échouait.** Il refuse désormais.
- **`SDCard.rel`** prenait « SDCARD Deluge 2 » pour un sous-dossier de « SDCARD Deluge » ;
  **`resolve_sample`** acceptait `..` dans un `fileName`. Les deux sont fermés, ainsi
  qu'une entrée `..` dans une archive à restaurer.

### Ce que l'interface affichait de faux

- **Texte blanc sur les boutons verts, cyan, or** (contraste 1,7 à 2,4) : `text_on`
  gardait un seuil réglé pour l'ancienne `luminance`, redéfinie en WCAG plus bas dans
  le même fichier. Il choisit maintenant la couleur la plus contrastée.
- **Page Morceaux : 40 instruments sur 65 « ABSENT »** que « Rassembler » trouvait et
  copiait. La page cherche maintenant comme l'export (`songpack.find_preset`).
- **Un preset dupliqué ou généré n'apparaissait dans aucune liste** avant une analyse
  complète : `scan.index_presets` l'indexe aussitôt.
- **Après un rangement, le diagnostic montrait encore les anomalies corrigées** :
  l'index gardait les anciens chemins. `Library.move` suit le fichier, ses
  dépendances, ses favoris et ses étiquettes.
- **Archives `.zip`** : le manifeste n'était pas lu ; une archive *avec* échantillons
  passait pour une archive sans, et sa comparaison déclarait tout « supprimé ».
- **Deux tables de gammes divergentes** dans `model.py` (une « hongroise » et un
  « in sen » faux), « Ré# » ici et « Mib » ailleurs : tout passe par `theory`.

### Seconde passe : l'index, les doublons et le vocabulaire du firmware

Treize tests de `TestAuditOctobreSuite`, tous en échec sur le code d'avant.

- **Un fichier modifié restait « doublon confirmé »** : la ligne réindexée gardait
  son ancienne empreinte complète, et la déduplication proposait de supprimer un
  fichier devenu différent. Toute réindexation efface désormais les empreintes.
- **Changer de carte gardait l'index de l'ancienne.** Les plans appliquaient ses
  empreintes aux fichiers de *même chemin* de la nouvelle — exactement le cas de
  `SDCARD Deluge` et de la carte réelle. `scan.forget_other_card` l'écarte
  (favoris et notes gardés), au changement de carte, au démarrage et à l'analyse.
- **Dernier filet** : `Plan.apply` recompare chaque doublon à l'octet près
  *avant* de rediriger ses références ; s'il diffère, rien ne bouge.
- **Les fichiers disparus restaient indexés** pour toujours. L'analyse les retire ;
  les références vers eux deviennent « cassées », et redeviennent saines si le
  fichier revient (un preset inchangé n'est pas relu en analyse incrémentale).
- **Vocabulaire du firmware** — relevé dans le code du firmware communautaire, la
  carte ne contenant aucun exemple : `SVF_Band` (et non `SVF_Bandpass`),
  `StereoChorus`, `TapeWarble`, `grainFX`, LFO `sah` et `rwalk`. Ancienne
  polyphonie : seuls `0` et `2` ont un sens, tout autre nombre vaut `poly`.
- **Destinations de câble** : `oscAPulseWidth` se vise par `oscAPhaseWidth`
  (295 câbles sur la carte), `bitCrush` par `bitcrushAmount`… Sur 1 800 presets
  d'essai, le générateur écrivait ~1 600 câbles vers une destination inconnue. Le
  moteur d'écoute ignorait, lui, les 295 câbles réels. Table :
  `model.CABLE_DESTINATIONS` (midifollow.py la connaissait déjà).
- **Restaurer une sauvegarde** écrasait le travail récent sans recours. Les
  versions remplacées vont d'abord dans une sauvegarde « avant restauration ».
- **Jouer un motif sur le Deluge** tronquait les positions fractionnaires : le
  swing disparaissait. L'agenda est désormais à la résolution de l'horloge.
- Plus petits : renommer un preset cité par un morceau cassait le lien (écarté) ;
  un dossier de sauvegarde dans `SAMPLES/` se recopiait lui-même (refusé) ;
  `MIDIFollow.XML` est lu dans sa seule section d'assignations ; « Réinitialiser
  l'index » effaçait l'index mais pas la date de dernière analyse.

### Écart à la règle, laissé en l'état

`deps.relink` réécrit aussi les **morceaux** (`SONGS/`), alors que §6 dit que
l'application n'en réécrit jamais. Mesuré : les 46 morceaux ressortent du sérialiseur
avec un arbre XML identique (seule la mise en forme change), et une copie `.bak` est
laissée. Exclure les morceaux empêcherait de réparer leurs références : à trancher.

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

> **Vérifié le 15 octobre 2026** (§3 novovicies). Les ports s'appellent
> `Deluge`, `MIDIOUT2 (Deluge)`, `MIDIOUT3 (Deluge)` (entrées : `MIDIIN2`,
> `MIDIIN3`). Le canal n'est pas une constante : c'est un réglage de la
> machine, MIDI ▸ Follow ▸ Channel A, **éteint par défaut** — l'interface
> dit de le régler. La note 36 est la valeur d'usine de Follow ▸ Kit Root
> Note (code du firmware). Le SysEx, annoncé ici « pas encore fait », est
> écrit et vérifié sur la machine ; le transfert de fichiers, lui, n'existe
> pas dans le firmware c1.2.1.

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

**Tout est écrit.** Les cinq phases sont terminées, et des modules s'y sont
ajoutés depuis (`samplefix`, `slicer`, `similarity`, `songpack`, `units`,
`delugelink`, `midiport`, `midifollow`, `accomp`, `sketch`…). **798 tests au
vert** au 14 octobre 2026 ; le nombre exact de chaque passe est dans son § daté.

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
  quittant (§3 sexdecies) ;
- **rendre aussi à 980 × 640, faire défiler les pages jusqu'en bas, et
  rendre sans carte.** Trois défauts anciens (§3 septvicies) ne se voyaient
  qu'ainsi : une jauge dessinée sur le nom d'un dossier en bas du tableau
  de bord, une phrase qui imposait 900 px, une barre d'actions coupée en
  plein mot. Copier l'index réel dans la configuration isolée, masquer les
  ports MIDI, refuser les modales, et comparer les empreintes des réglages
  réels avant et après.

### Lancer et vérifier

```bash
cd "C:\Users\sebas\Desktop\Informatique\Deluge app"
PY="C:/Users/sebas/AppData/Local/Programs/Python/Python313/python.exe"
"$PY" main.py                                # l'application
"$PY" -m unittest discover -s tests          # 798 tests, doit afficher OK
```

Les tests d'interface ont besoin d'un affichage ; sans serveur graphique,
`QT_QPA_PLATFORM=offscreen` suffit. La suite complète dure environ 105 secondes.

Un audit d'usage réel (§3 sexvicies) se refait sans risque : configuration isolée, copie de
l'index de l'utilisateur, navigation seule, empreintes avant et après. C'est lui, et le
journal `app.log` de l'utilisateur, qui ont trouvé les défauts que la suite ne voyait pas.

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
