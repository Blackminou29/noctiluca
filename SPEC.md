# SPEC — Deluge Companion (application Python pour Synthstrom Deluge)

**Projet racine :** `C:\Users\sebas\Desktop\Informatique\Deluge app`
**Package :** `delugeapp/` — **Point d'entrée :** `main.py` à la racine du projet.
**Python cible :** 3.11+ (testé 3.11 et 3.13, Windows).
**Dépendances autorisées :** `PyQt6`, `numpy`, `matplotlib` (optionnel), `sounddevice` (optionnel),
`Pillow` (optionnel). **Rien d'autre.** Tout import optionnel doit être protégé par `try/except ImportError`
avec dégradation gracieuse (pas de crash si absent).
**Langues de l'interface : français et anglais**, au choix dans le menu « Langue » (§5.26).
Le français est la langue **source** : chaque libellé, menu, message et infobulle s'écrit en
français dans le code, et c'est ce texte qui sert de clé à sa traduction anglaise
(`delugeapp/i18n/`). Les noms de code (classes, fonctions, variables) en anglais.

---

## 0. Règles générales impératives

1. **Encodage** : tous les fichiers `.py` en UTF-8, avec `# -*- coding: utf-8 -*-` en tête.
2. **Aucune écriture destructive sans confirmation** : toute fonction qui modifie/déplace/supprime
   sur la carte SD doit être *dry-run par défaut* (`apply: bool = False`) et retourner la liste des
   opérations prévues.
3. **Jamais de `print()`** dans `delugeapp/` — utiliser le module `logging` (`log = logging.getLogger(__name__)`).
4. **Chemins** : toujours `pathlib.Path`. Les chemins internes à la carte SD sont stockés en
   **relatif, séparateur `/`**, exactement comme le Deluge les écrit (`SAMPLES/DRUMS/Kick/808 Kick.wav`).
5. **Comparaison de chemins insensible à la casse** (la carte est en FAT32) — voir `core.sdcard.norm_rel()`.
6. Pas de travail bloquant long dans le thread UI : utiliser `QThread`/`QRunnable` (voir §6.1).
7. Chaque module core doit être importable sans Qt (`import delugeapp.core.X` ne doit jamais importer PyQt6).
8. Docstrings en français, concises.

---

## 1. Faits vérifiés sur le format Deluge (NE PAS RE-DÉDUIRE — c'est mesuré sur la carte réelle)

### 1.1 Arborescence de la carte SD
```
<racine>/
  SONGS/*.XML            morceaux
  SYNTHS/**/*.XML        presets de synthé (sous-dossiers autorisés, profondeur quelconque)
  KITS/**/*.XML          kits de batterie
  SAMPLES/               échantillons (.wav, .aiff)
    DRUMS/<Kick|Snare|HatC|HatO|Clap|Rim|TomH|TomM|TomL|Crash|Ride|China|Cowbell|Block|
           Claves|ConH|ConM|ConL|Guiro|Shaker|Tambourine|Timpany|Other>/
    MULTISAMPLES/<instrument>/...
    Artists/<nom>/...
    CLIPS/ RECORD/ RESAMPLE/ STEMS/
  deluge-*.bin           firmware (UN SEUL autorisé à la racine)
  CommunityFeatures.XML  réglages firmware communautaire
  MIDIFollow.XML
```
Dossiers à ignorer systématiquement : `System Volume Information`, `.Spotlight-V100`,
`.Trashes`, `.Trash-*`, `.fseventsd`, `$RECYCLE.BIN`, `.git`.
Fichiers à ignorer : tout nom commençant par `._` (AppleDouble macOS), `.DS_Store`, `Thumbs.db`.

### 1.2 Deux dialectes XML coexistent sur la même carte
- **Dialecte « éléments »** (firmware 2.x) : `<osc1><type>saw</type><transpose>0</transpose></osc1>`
- **Dialecte « attributs »** (firmware 3.0+) : `<osc1 type="saw" transpose="0" />`
Le lecteur doit gérer les deux de façon transparente. L'écrivain doit **conserver le dialecte
d'origine** lors d'une modification, et utiliser le dialecte « attributs » pour les fichiers créés.

### 1.3 Anomalies réelles présentes sur la carte (le parseur DOIT les absorber)
| Anomalie | Exemple | Traitement |
|---|---|---|
| Document multi-racines (fw 2.x) | `<firmwareVersion>2.0.0-beta</firmwareVersion>` puis `<sound>` en frères | envelopper dans une racine de synthèse `<delugeFile>` |
| `&` non échappé dans un attribut | `fileName="…/Tenor & Alto Sax G2.wav"` | remplacer `&` non suivi d'une entité valide par `&amp;` |
| Octets non-UTF-8 / caractères XML interdits | `name="\xff\xff…"` dans `<device>` MIDI | décoder `utf-8, errors='replace'` puis filtrer les caractères hors plage XML 1.0 |
| Déclaration XML puis contenu | — | retirer la déclaration avant d'envelopper |
Sur 1000 fichiers de la carte, ce traitement fait passer le taux d'échec de 14 % à 0,1 %.

### 1.4 Paramètres en virgule fixe
Les valeurs `0x…` sont des entiers **32 bits signés** (complément à 2).
- `0x80000000` = −2147483648 = **minimum**
- `0x00000000` = 0 = **milieu**
- `0x7FFFFFFF` = +2147483647 = **maximum**

Deux familles :
- **unipolaire** (volume, résonance, attaque, reverbAmount…) : l'écran du Deluge affiche **0 à 50**.
  `affichage = round((v + 2147483648) / 4294967295 * 50)`
- **bipolaire** (pan, patchCable amount, equalizer bass/treble…) : affichage **−25 à +25**
  (pan) ou **−50 à +50** (patch cables). `amount` de patchCable : **`0x40000000` = +50**
  (corrigé le 10/10/2026, cf. encadré ci-dessous).

> **Correction mesurée (10/10/2026) — l'échelle des câbles de modulation.**
> La rédaction initiale annonçait `0x7FFFFFFF` = +50 pour l'`amount` d'un `patchCable`,
> comme pour les autres paramètres. C'est le **double** de la réalité.
> Mesure sur les **7 025 câbles** des presets, kits et morceaux de la carte :
> * aucune valeur ne dépasse `0x40000000` (ni en positif, ni en négatif) ;
> * **1 925 valent exactement `0x3FFFFFE8` ≈ `0x40000000`** — c'est la valeur la plus
>   fréquente, cinq fois plus que la suivante, signature du maximum de l'interface ;
> * avec l'échelle `0x40000000` → 50, les profondeurs tombent exactement dans [−50, +50].
>
> L'échelle pleine est donc `model.PATCH_CABLE_FULL = 0x40000000`, soit **la moitié** de
> celle des paramètres ordinaires. Utiliser `to_display(..., scale=100)` sur l'échelle
> int32 complète divisait toutes les profondeurs affichées par deux, et faisait écrire au
> générateur des modulations deux fois trop faibles.
> Passer par `PatchCable.display()` / `PatchCable.amount_from_display()`, jamais par
> `fixedpoint.to_display` directement. Couvert par `TestPatchCableScale`.

Champs entiers bruts (pas hex) : `transpose`, `cents`, `num`, `detune`, `spread`, `syncLevel`,
`numOctaves`, `retrigPhase`, `attack`/`release` du compresseur, `rangeTopNote`,
`startMilliseconds`/`endMilliseconds`, `startSamplePos`/`endSamplePos`, `clippingAmount`, `maxVoices`.

### 1.5 Vocabulaire vérifié (valeurs réellement rencontrées + valeurs connues du firmware)
```
osc type      : sine square triangle saw analogSquare analogSaw sample wavetable
                inLeft inRight dx7 (dx7 = firmware communautaire c1.x)
lfo type      : sine triangle square saw sah rwalk warbler
mode (sound)  : subtractive fm ringmod
polyphonic    : poly mono legato choke auto (anciens fichiers : 0 = auto, 2 = choke,
                tout autre nombre = poly)
lpfMode       : 24dB 12dB 24dBDrive SVF_Band SVF_Notch (c1.x ajoute les SVF)
hpfMode       : HPLadder SVF_Band SVF_Notch
filterRoute   : H2L L2H PARA
modFXType     : none flanger chorus phaser StereoChorus TapeWarble dimension grainFX
arp mode      : off up down both random  (c1.x : arpMode off/arp + noteMode + octaveMode)
noteMode      : up down upDown asPlayed random   (c1.2.1 ; pas de « downUp »)
octaveMode    : up down upDown alt random        (c1.2.1 ; « alt » et non « alternate »)
patchCable source      : envelope1 envelope2 lfo1 lfo2 velocity note aftertouch random
                         compressor sidechain x y
patchCable destination : volume pitch lpfFrequency lpfResonance hpfFrequency hpfResonance
                         oscAVolume oscBVolume oscAPitch oscBPitch oscAPhaseWidth oscBPhaseWidth
                         oscAWavetablePosition oscBWavetablePosition noiseVolume
                         modulator1Volume modulator2Volume modulator1Pitch modulator2Pitch
                         carrier1Feedback carrier2Feedback modFXRate modFXDepth modFXFeedback
                         modFXOffset delayRate delayFeedback reverbAmount arpRate
                         arpGate stutterRate sampleRateReduction bitcrushAmount pan range
                         portamento env1Attack env1Decay env1Sustain env1Release
                         env2Attack env2Decay env2Sustain env2Release lfo1Rate lfo2Rate
                         lpfMorph hpfMorph waveFold compressorThreshold
```
`syncLevel` : 0 = off, 1..9 = 2^n divisions (7 ≈ noire/16ᵉ selon contexte).

> **Correction mesurée (12 octobre 2026).** Cette liste donnait des noms que le firmware
> ne connaît pas : `SVF_Bandpass`, `stereoChorus`, `warble`, `grain`, `sampleAndHold`,
> `randomWalk`. Les bons noms viennent du code du firmware communautaire
> (`util/functions.cpp`, `filters/filter_config.cpp`, `modulation/params/param.cpp`).
> Une chaîne inconnue est lue comme la valeur par défaut (LFO triangle, aucun effet…).
> Surtout, **une destination de câble ne porte pas toujours le nom du paramètre** :
> `oscAPulseWidth` se vise par `oscAPhaseWidth` (295 câbles sur la carte, aucun
> autrement), `modulator1Amount` par `modulator1Volume`, `bitCrush` par
> `bitcrushAmount`. La table est `model.CABLE_DESTINATIONS`.

> **Correction mesurée (15 octobre 2026) — trois noms que le firmware lit mal.**
> Lus dans le code de la machine (tag `release_1_2_1`, `util/functions.cpp` et
> `filters/filter_config.cpp`) :
> * `octaveMode="upDown"` est **relu comme `random`** (`stringToArpOctaveMode`), alors
>   que la machine l'écrit pour le mode aller-retour : ce mode ne survit pas à un
>   enregistrement ;
> * le mode de filtre **éteint** n'a pas de nom (`filterMap` s'arrête avant `OFF`) : la
>   machine écrit ce qui suit en mémoire — `lpfMode="flanger"`, six fois dans quatre
>   morceaux de la carte — et relit **tout nom inconnu comme éteint**. `"off"` s'écrit donc sans risque ;
> * l'ancien câble `destination="range"` + `rangeAdjustable="1"` (avant 3.2) est relu par
>   toutes les versions ; la machine le réécrit en `<depthControlledBy>`.

### 1.6 Notes des morceaux
`<noteRow y="81" noteDataWithLift="0x…" />` ou `noteData="0x…"`.
Blob hexadécimal, **une note par groupe fixe de caractères** :
- `noteData` → **20 caractères** : `pos(8) length(8) velocity(2) condition(2)`
- `noteDataWithLift` → **22 caractères** : `pos(8) length(8) velocity(2) lift(2) condition(2)`
  — **le lift précède la condition** (corrigé le 10/10/2026, cf. encadré ci-dessous).
Valeurs signées 32 bits pour `pos` et `length`. Résolution : **une mesure 4/4 vaut
`96 << inputTickMagnitude` ticks** (`Song::getBarLength`) — 192 dans les morceaux 3.x
(magnitude 1), **384 dans les morceaux c1.2.1** (magnitude 2), où une double-croche vaut
24 ticks. `length="1536"` fait donc 8 mesures en 3.x, **4 en c1.2.1**.
`y` = numéro de ligne (note MIDI pour un clip mélodique, index de rangée pour un kit).
`condition` : 0x14 (20) = toujours ; valeurs < 20 = probabilité (×5 %) ; ≥ 0x80 = itération.
Des valeurs 21 à 26 existent aussi sur la carte (conditions spéciales du firmware) :
les traiter comme « toujours » plutôt que comme une probabilité.

> **Correction mesurée (10/10/2026) — ordre des champs de `noteDataWithLift`.**
> La version initiale de ce paragraphe annonçait `… condition(2) lift(2)`. C'est l'inverse.
> Mesure sur les 403 notes de la carte qui portent un lift :
> l'octet en position 18–20 vaut `0x40` pour **100 %** d'entre elles — c'est le `lift`,
> dont la valeur par défaut est 64 ; l'octet en position 20–22 vaut `0x14` pour **92,8 %**
> — c'est la `condition` « toujours », le reste étant des probabilités (2 à 16) et une
> itération (134). L'ordre retenu dans `core/model.py` est donc
> `pos(8) length(8) velocity(2) lift(2) condition(2)`, couvert par le test
> `TestNotes.test_blob_22_caracteres`.

> **Correction mesurée (14 octobre 2026) — la résolution dépend du morceau.** Ce
> paragraphe disait « une noire = 24 ticks, une mesure = 96 » : c'est l'horloge
> **extérieure** (celle de la formule du tempo, §4.5), pas celle des notes. Mesuré sur
> les notes des 46 morceaux de la carte : à magnitude 1, les clips font 192, 384, 768
> ticks et l'écart minimal entre deux notes est 12 (la double-croche) ; à magnitude 2,
> 384, 1 536, 3 072 et 24. Conséquences corrigées : la page Morceaux comptait 2 à 4 fois
> trop de mesures, et les exports « Clip en MIDI » / « Morceau en MIDI » sortaient 2 à 4
> fois trop lents. `model.ticks_per_bar(m)`, `Clip.ticks_per_bar` (posé par le morceau),
> `midifile._ratio` ; l'index relit une fois les morceaux déjà analysés
> (`scan.SONG_READER`).
>
> Autre règle du lecteur (`NoteRow::readFromFile`) : sur une même rangée, une note qui
> commence **avant la fin de la précédente est ignorée**. Un écrivain doit raccourcir la
> première (`songwriter._clean_notes`).

### 1.7 Chemins d'échantillons
`fileName` est relatif à la racine SD, séparateur `/`, **casse non fiable**
(`SAMPLES/Multisamples/…` alors que le dossier réel est `SAMPLES/MULTISAMPLES`).
La résolution doit donc être insensible à la casse.

### 1.8 Ce que le Deluge lit comme échantillon

Lu dans le code du firmware de la machine (1.3 bêta, tag `beta` = commit `102cf9f`,
celui du fichier `deluge-v1_3_0-beta+2026_10_18-102cf9f.bin` de sa carte) :
`AudioFileManager::loadAudioFile`, `AudioFile::loadFile`, `isAudioFilename`.

| | accepté | refusé (`FILE_UNSUPPORTED`) |
|---|---|---|
| nom | `.wav`, `.aif`, `.aiff`, sans point initial | tout le reste, `.aifc` compris |
| conteneur | `RIFF…WAVE`, `FORM…AIFF` | `RIFX`, `RF64`/`BW64`, `FORM…AIFC` |
| codage WAV | PCM 8/16/24/32 bits, flottant 32 bits | **`WAVE_FORMAT_EXTENSIBLE` (0xFFFE)**, A-law, µ-law, flottant 64, compressés |
| AIFF | bloc `COMM` de 18 octets exactement, 8/16/24/32 bits | |
| canaux | 1 ou 2 | 3 et plus |
| fréquence | 5 000 à 96 000 Hz | au-delà |

L'en-tête étendu est écrit par beaucoup de logiciels de MAO pour le 24 bits : le Deluge
le refuse alors qu'il lirait les mêmes données sous un en-tête simple.

> **Mesuré** (18 octobre 2026) : les 1 745 échantillons de la carte et les 1 125 vrais
> WAV du PC de l'utilisateur (deux packs téléchargés) respectent tous ces règles ;
> 169 autres fichiers `.wav` du PC sont des parasites `._*` de macOS. L'écrivain de
> l'application (`wav.write`) produit des fichiers lisibles, sauf deux cas absents de
> la carte : le flottant 64 bits, et l'AIFF flottant (écrit en AIFC).

---

## 2. Identité graphique (reprise du « Guide du Deluge » de l'utilisateur)

Source : `C:\Users\sebas\Desktop\Informatique\Guide deluge\build\style.py`.
**Palette à reproduire exactement** dans `delugeapp/ui/theme.py` :
```python
INK="#15181E"  INK_SOFT="#3B424E"  GREY="#7A828F"  GREY_LIGHT="#C3C9D2"
PAPER="#FFFFFF"  PAPER_WARM="#FAF8F4"
PANEL="#171C25"  PANEL_HI="#222934"  PANEL_LO="#0A0D12"  # cf. encadré ci-dessous
GOLD="#C79A22"  GOLD_HI="#EBC65C"  GOLD_LO="#8A6A12"
PAD_RED="#F2453D"    PAD_ORANGE="#FF8C1A"  PAD_AMBER="#FFC400"  PAD_YELLOW="#F5E13C"
PAD_GREEN="#3DD160"  PAD_MINT="#2FD3A6"    PAD_CYAN="#28C4E0"   PAD_BLUE="#3E86F5"
PAD_INDIGO="#6B5CE7" PAD_PURPLE="#A85BE0"  PAD_MAGENTA="#F04FA8" PAD_PINK="#FF7BB0"
PAD_OFF="#262A33"    PAD_DIM="#3A404C"     PAD_WHITE="#F2F4F8"
ACCENT="#1F7A8C"  ACCENT_2="#C4543C"  WASH="#EEF1F5"  WASH_2="#F6EEE4"
PAD_CYCLE = [RED, ORANGE, AMBER, YELLOW, GREEN, MINT, CYAN, BLUE, INDIGO, PURPLE, MAGENTA, PINK]
```
**Langage visuel :** fond `PANEL_LO`, panneaux `PANEL`, surfaces relevées `PANEL_HI`,
texte `PAD_WHITE`, texte secondaire `GREY`. Carrés arrondis (rayon 6–10 px) partout,
façon pads. L'emblème = grille 4×4 de pads colorés dans un disque sombre cerclé d'or.

**Deux corrections au dessin d'origine**, l'une et l'autre mesurées sur l'écran :

1. **Les trois surfaces se distinguent.** Elles ne se séparaient que de douze
   points de luminance : panneau et fond se confondaient, et l'écran entier
   paraissait d'un seul gris. Le fond descend à `#0A0D12`, les panneaux
   montent à `#171C25`, les bordures deviennent visibles (`BORDER="#333B48"`).

2. **L'accent n'est plus unique.** « Accent unique = `GOLD` » donnait neuf
   écrans rigoureusement identiques : rien ne disait où l'on était. L'or
   reste l'accent de l'application (en-tête, action principale, focus), mais
   **chaque page porte sa couleur**, prise dans les pads de la machine :

   | Page | Couleur | | Page | Couleur |
   |---|---|---|---|---|
   | Tableau de bord | `PAD_AMBER` | | Générateur | `PAD_MAGENTA` |
   | Échantillons | `PAD_CYAN` | | Boîte à outils | `PAD_MINT` |
   | Presets | `PAD_PURPLE` | | Santé | `PAD_ORANGE` |
   | Kits | `PAD_GREEN` | | Réglages | `PAD_INDIGO` |
   | Morceaux | `PAD_BLUE` | | | |

   Cette couleur sert, **et toujours de la même façon** : icône et liseré du
   bouton de navigation, bande de 3 px sous l'en-tête, pad à gauche du titre
   de la page, trait et libellé des titres de section, tuiles et raccourcis
   qui mènent à cette page. Un raccourci montre la couleur de **sa
   destination**, jamais celle de la page qui l'héberge — c'est tout
   l'intérêt.
Police : `Segoe UI` puis `DejaVu Sans` en repli ; monospace `Cascadia Mono`/`Consolas`.

**Troisième temps : la façade** (14 octobre 2026, voir §5.22). L'utilisateur
jugeait l'interface « trop classique » et « manquant cruellement de fun ».
Elle reprenait la palette du guide, pas ses signatures. Elle les reprend
désormais, tracées par `ui/art.py` d'après `build/figs_schema.py` et
`build/style.py` du guide :

* **le treillis** des ouvertures de partie — blocs de traitement (gain,
  oscillateur, filtre, mélange, modulation, matrice, retard) reliés par des
  pistes orthogonales à l'or sourd — en tête de chaque page, à sa couleur ;
* **le pad allumé** (halo de sa couleur, reflet en haut) et **le pad au
  repos** (cadre à l'or sourd et quatre points, « comme une diode au
  repos ») ;
* **l'écran OLED** de la machine (`figs_oled.py`) dans la barre du haut ;
* **la typographie de la couverture** : « DELUGE » en magenta, capitales
  espacées pour les étiquettes, titres de page en capitales.

Teintes ajoutées, toutes mesurées (§5.22) :
```python
CHROME="#0E1218"  CHROME_EDGE="#1E2530"     # la façade : barre du haut, colonne, barre d'état
OLED_BG="#04060A" OLED_FG="#FFFFFF" OLED_DIM="#8FB6CC" OLED_HI="#7FE3FF" OLED_EDGE="#1B3E52"
PAD_ETEINT="#191D25"                         # pad éteint de la couverture
CARD_TOP="#1B212B" BORDER_TOP="#323B4A"      # chanfrein des panneaux
```

La couleur d'une page ne se limite plus au décor : **ses contrôles la
prennent** — bouton principal, sélections, onglets, cases, curseurs,
jauges, jusqu'aux fenêtres de dialogue qu'elle ouvre. La couleur d'accent
des réglages devient celle de **la façade** (barre du haut, menus, fenêtres
ouvertes hors des pages).

---

## 3. Arborescence des fichiers à produire

```
main.py
requirements.txt
README.md
delugeapp/
  __init__.py                 __version__ = "1.0.0"
  config.py
  i18n/
    __init__.py               # tr, N_, untranslated, plural, tr_stored, formats (§5.26)
    en/
      __init__.py             # MODULES : les fichiers du catalogue ; load()
      ui_pages_health.py      # TEXTS : un fichier par module du code, nommé d'après lui
      …
  core/
    __init__.py
    fixedpoint.py
    units.py
    dxml.py
    sdcard.py
    model.py
    wav.py
    audio_out.py
    db.py
    scan.py
    analysis.py
    deps.py
    organize.py
    health.py
    backup.py
    genres.py
    synthgen.py
    kitgen.py
    theory.py
    rhythm.py
    accomp.py
    sketch.py
    midifile.py
    render.py
    samplefix.py
    similarity.py
    slicer.py
    songpack.py
    songwriter.py               # écrire un morceau du Deluge (§4.31)
    midiport.py                 # MIDI et SysEx par winmm (§4.28)
    midifollow.py               # la carte des contrôleurs (§4.29)
    delugelink.py               # le lien vivant avec la machine (§4.30)
    delugesysex.py              # identité, ping, écran (§4.32)
    delugefiles.py              # la carte par USB, firmware 1.3 (§4.33)
    cardsync.py                 # copie de travail et synchronisation (§4.34)
    cardimport.py               # envoyer au Deluge, du PC vers la carte (§4.35)
  ui/
    __init__.py
    theme.py
    icons.py
    tasks.py
    aide.py                     # ce que fait chaque commande (§5.18)
    art.py
    songexport.py               # nommer, montrer le plan, écrire (§5.23)
    livewindow.py               # « Deluge en direct » (§5.17)
    cardwork.py                 # la copie de travail, côté interface (§5.24)
    sendfiles.py                # envoyer au Deluge : dépôt, plan, copie (§5.25)
    widgets/
      __init__.py
      common.py
      chrome.py
      padgrid.py
      waveform.py
      envelope.py
      knob.py
      piano.py
      filtercurve.py
      delugescreen.py           # l'écran de la machine, pixel pour pixel
    pages/
      __init__.py
      dashboard.py
      samples.py
      synths.py
      kits.py
      songs.py
      generator.py
      toolbox.py
      health.py
      settings.py
    mainwindow.py
tests/
  test_core.py
  test_ui.py
  test_i18n.py                  # le catalogue suit le code (§5.26)
  i18n_analyse.py               # lecture du code par son arbre, sans l'importer
  deluge_simule.py              # un Deluge simulé, fidèle aux mesures
```

---

## 4. Contrats des modules core (signatures EXACTES — à respecter à la lettre)

### 4.1 `delugeapp/config.py`
```python
APP_NAME = "Deluge Companion"
APP_ORG  = "DelugeCompanion"
CONFIG_DIR: Path            # %APPDATA%/DelugeCompanion (créé au besoin)
DB_PATH: Path               # CONFIG_DIR/library.sqlite3

@dataclass
class Settings:
    sd_path: str = ""              # racine de la carte SD (MODIFIABLE par l'utilisateur)
    recent_paths: list[str] = field(default_factory=list)
    audio_device: str | None = None
    autoplay: bool = True
    preview_volume: float = 0.8
    confirm_writes: bool = True
    always_backup_before_write: bool = True
    backup_dir: str = ""
    theme_accent: str = "#C79A22"
    language: str = "fr"
    scan_hash: bool = True         # calculer les empreintes (doublons)
    scan_analyze: bool = False     # analyse BPM/tonalité au scan (lent)
    index_on_start: bool = True    # au démarrage, analyse incrémentale en arrière-plan
                                   # (lecture seule ; 0,2 s sur la carte de référence)
    midi_out / midi_in / midi_channel / midi_autoconnect / midi_audition /
    midi_follow_tempo              # le Deluge branché (§5.17)
    work_dir: str = ""             # copie de travail ; vide = DEFAULT_WORK_DIR
    card_backup: str = ""          # sauvegarde de la carte : lue, jamais écrite
    auto_sync: bool = True         # synchroniser d'office quand le Deluge est là
    def work_path() -> Path
    def card_backup_path() -> Path | None
    def adopt_card_roles() -> bool # l'ancien dossier de travail -> sauvegarde
    def card_role(root) -> str     # "travail" | "sauvegarde" | "carte" | "dossier"
    def open_card(root) -> SDCard  # en lecture seule si c'est la sauvegarde

DEFAULT_WORK_DIR: Path         # %LOCALAPPDATA%/DelugeCompanion/Carte
def load_settings() -> Settings
def save_settings(s: Settings) -> None
AppContext.sd_or_warn(parent, write=False)   # write=True refuse la sauvegarde
```

**La sauvegarde de la carte n'est jamais un dossier de travail.**
L'utilisateur, le 18 octobre 2026 : « SDCARD Deluge est un emplacement de
sauvegarde de ma carte SD qui n'est pas destiné à être le répertoire de
travail ». L'application y avait pourtant réparé dix presets le
11 octobre — que la carte n'a jamais reçus (mesuré par USB). Désormais :
`SDCard.read_only` ; chaque fonction du cœur qui écrit appelle
`sd.require_writable()` (`songwriter.write_song`, `organize.Plan.apply`,
`samplefix.FixPlan.apply`, `deps.relink[_many]`, `slicer.save_sliced_kit`,
`slicer.export_slices`, `backup.restore_backup`) ; l'interface prévient
avant (`Page.writable_card`). Au démarrage, un dossier de travail qui n'est
ni la racine d'un lecteur ni la copie de travail devient la sauvegarde.

**`DELUGE_COMPANION_CONFIG`** impose le dossier de configuration
(`CONFIG_ENV` dans le module). Deux usages : une installation portable, et
l'isolement obligatoire de tout script ou test qui lance l'application —
celle-ci enregistre les réglages en quittant, et un script d'essai qui coupe
la confirmation d'écriture la laisserait coupée chez l'utilisateur. C'est
arrivé trois fois ; cf. §7.

### 4.2 `delugeapp/core/fixedpoint.py`
```python
INT32_MIN = -2147483648 ; INT32_MAX = 2147483647

def parse_fixed(text: str | int | None, default: int = 0) -> int
    """'0x7FFFFFFF' | '-601295438' | None -> entier signé 32 bits."""
def format_fixed(value: int) -> str          # -> '0x7FFFFFFF' (8 chiffres, majuscules)
def to_unit(value: int) -> float             # int32 -> 0.0..1.0
def from_unit(u: float) -> int               # 0.0..1.0 -> int32 (saturé)
def to_bipolar(value: int) -> float          # int32 -> -1.0..1.0
def from_bipolar(b: float) -> int
def to_display(value: int, bipolar: bool = False, scale: int = 50) -> int
    """Valeur affichée par le Deluge : 0..50 (unipolaire) ou -25..+25 (bipolaire, scale=50)."""
def from_display(disp: int, bipolar: bool = False, scale: int = 50) -> int
def parse_int(text, default: int = 0) -> int  # entier brut tolérant ('', None, '0x..')
```
Tests attendus : `to_display(parse_fixed('0x80000000'))==0`,
`to_display(parse_fixed('0x7FFFFFFF'))==50`, `to_display(parse_fixed('0x00000000'))==25`,
`format_fixed(from_display(50))=='0x7FFFFFFF'`, aller-retour stable sur 0..50.

### 4.3 `delugeapp/core/dxml.py` — lecture/écriture tolérante
```python
class DelugeXMLError(Exception): ...

@dataclass
class DelugeDoc:
    path: Path | None
    root: ET.Element          # élément racine RÉEL (<sound>, <kit>, <song>, <runtimeFeatureSettings>)
    preamble: dict[str, str]  # éléments frères hors racine (fw 2.x) : {'firmwareVersion': '2.0.0-beta', ...}
    dialect: str              # 'attr' | 'elem'
    firmware: str             # version détectée ('' si inconnue)
    repaired: list[str]       # anomalies corrigées à la lecture (pour le rapport de santé)

def repair_text(raw: bytes) -> tuple[str, list[str]]
    """Décode + répare : caractères XML invalides, '&' nu, BOM. Retourne (texte, anomalies)."""
def load(path: Path) -> DelugeDoc          # lève DelugeXMLError si irrécupérable
def loads(data: bytes, path: Path | None = None) -> DelugeDoc
def detect_dialect(root: ET.Element) -> str
def dump(doc: DelugeDoc) -> str            # sérialise au format Deluge (voir §4.3.1)
def save(doc: DelugeDoc, path: Path | None = None, backup: bool = True) -> Path
    """Écriture atomique : fichier temporaire + os.replace. backup=True -> .bak horodaté."""

# Accès indifférent au dialecte :
def get(el: ET.Element, name: str, default: str | None = None) -> str | None
    """Lit un attribut OU un sous-élément texte de même nom."""
def set_(el: ET.Element, name: str, value: str, dialect: str = 'attr') -> None
def get_child(el: ET.Element, name: str) -> ET.Element | None
def ensure_child(el: ET.Element, name: str) -> ET.Element
def iter_children(el: ET.Element, name: str) -> Iterator[ET.Element]
def remove_child(el: ET.Element, name: str) -> None
```
**§4.3.1 Style de sérialisation Deluge** (impératif pour que le Deluge relise les fichiers) :
- `<?xml version="1.0" encoding="UTF-8"?>` puis `\n`
- indentation par **tabulations**
- un élément avec > 2 attributs : un attribut par ligne, indenté d'une tabulation de plus,
  `>` ou ` />` collé au dernier attribut
- un élément avec ≤ 2 attributs et sans enfant : sur une seule ligne `<lfo1 type="sine" syncLevel="0" />`
- fins de ligne `\n`, encodage UTF-8 sans BOM
- échapper `&`, `<`, `>`, `"` dans les valeurs.

### 4.4 `delugeapp/core/sdcard.py`
```python
STD_DIRS = ("SONGS", "SYNTHS", "KITS", "SAMPLES")
IGNORED_DIRS  = frozenset({...})   # cf. §1.1
IGNORED_FILES_PREFIX = ("._",)
AUDIO_EXT = (".wav", ".aif", ".aiff")

@dataclass
class SDCard:
    root: Path
    def rel(self, p: Path) -> str            # chemin relatif '/' depuis la racine
    def abs(self, rel: str) -> Path
    def resolve_sample(self, rel: str) -> Path | None   # insensible à la casse, None si absent
    def songs(self) -> list[Path]
    def synths(self) -> list[Path]
    def kits(self) -> list[Path]
    def samples(self) -> list[Path]
    def firmware_files(self) -> list[Path]
    def is_valid(self) -> bool               # au moins 2 des STD_DIRS présents
    def free_space(self) -> tuple[int, int]  # (libre, total) en octets
    is_volume: bool                          # racine d'un lecteur (vraie carte, Deluge en USB) ;
                                             # faux pour une copie dans un dossier : l'espace
                                             # libre est alors celui du disque, et l'interface le dit

def norm_rel(rel: str) -> str        # casse basse + '/' — clé de comparaison
def detect_sd_cards() -> list[Path]  # lecteurs amovibles Windows contenant SONGS+SYNTHS
def is_deluge_root(p: Path) -> bool
def safe_deluge_name(name: str) -> str   # nom compatible FAT32 (ASCII, <= 63 car., sans <>:"/\|?*)
def check_name(name: str) -> list[str]   # liste des problèmes du nom
```

### 4.5 `delugeapp/core/model.py` — modèle objet (lecture ET écriture)
Toutes les classes exposent `from_xml(el, dialect) -> Self` et `to_xml(el, dialect) -> None`
(écrit dans l'élément fourni).
```python
@dataclass
class Zone:         start: int = 0; end: int = -1; unit: str = "samples"  # 'samples' | 'ms'
@dataclass
class SampleRange:  top_note: int = 127; file_name: str = ""; transpose: int = 0
                    cents: int = 0; zone: Zone = Zone()
@dataclass
class Osc:
    type: str = "square"; transpose: int = 0; cents: int = 0; retrig_phase: int = -1
    file_name: str = ""; loop_mode: int = 0; reversed: int = 0
    time_stretch_enable: int = 0; time_stretch_amount: int = 0
    zone: Zone | None = None; ranges: list[SampleRange] = []
    wavetable_position: int = 0
    @property
    def is_sample(self) -> bool
@dataclass
class Envelope:     attack:int=INT32_MIN; decay:int=INT32_MIN; sustain:int=INT32_MAX; release:int=INT32_MIN
@dataclass
class LFO:          type: str = "triangle"; sync_level: int = 0; sync_type: int = 0
@dataclass
class PatchCable:   source: str; destination: str; amount: int; range_amount: int | None = None
@dataclass
class Arpeggiator:  mode:str="off"; num_octaves:int=2; sync_level:int=7; arp_mode:str=""
                    note_mode:str=""; octave_mode:str=""; mpe_velocity:str=""
@dataclass
class ModKnob:      controls_param: str = ""; patch_amount_from_source: str = ""
@dataclass
class Sound:
    name: str = ""
    mode: str = "subtractive"          # subtractive | fm | ringmod
    polyphonic: str = "poly"
    voice_priority: int = 1
    lpf_mode: str = "24dB"; hpf_mode: str = ""; filter_route: str = ""
    mod_fx_type: str = "none"
    clipping_amount: int = 0; max_voices: int = 0; transpose: int = 0
    osc1: Osc; osc2: Osc
    lfo1: LFO; lfo2: LFO
    unison_num: int = 1; unison_detune: int = 8; unison_spread: int = 0
    env1: Envelope; env2: Envelope
    params: dict[str, int]             # TOUS les paramètres hex de <defaultParams>/<soundParams>
    patch_cables: list[PatchCable]
    eq: dict[str, int]                 # bass treble bassFrequency trebleFrequency
    arp: Arpeggiator
    mod_knobs: list[ModKnob]
    delay_ping_pong: int = 1; delay_analog: int = 0; delay_sync_level: int = 7
    comp_sync_level: int = 6; comp_attack: int = 327244; comp_release: int = 936
    firmware: str = ""
    def param(self, key: str, default: int = INT32_MIN) -> int
    def set_param(self, key: str, value: int) -> None
    def display(self, key: str) -> int                 # 0..50 pour l'affichage
    def summary(self) -> dict                          # {'oscs':…, 'filter':…, 'fx':[…]}
    def sample_paths(self) -> list[str]                # tous les fileName référencés
    def category_guess(self) -> str                    # 'Bass'|'Lead'|'Pad'|'Pluck'|'Keys'|'FX'|'Drone'|'Arp'|'Autre'
    def tonal_tags(self) -> list[str]                  # ex. ['brillant','résonant','long release']

PARAM_KEYS: tuple[str, ...]            # liste ordonnée de tous les noms de paramètres hex connus
PARAM_BIPOLAR: frozenset[str]          # paramètres bipolaires (pan, eq…)
DEFAULT_PARAMS: dict[str, int]         # valeurs neutres d'un preset vierge
DEFAULT_MOD_KNOBS: list[ModKnob]       # 16 modKnobs par défaut (cf. presets d'usine)

@dataclass
class SynthPreset:
    path: Path | None; name: str; folder: str; sound: Sound; doc: DelugeDoc | None
    @classmethod
    def load(cls, path: Path) -> SynthPreset
    def save(self, path: Path | None = None, backup: bool = True) -> Path
    @classmethod
    def new(cls, name: str = "NEW") -> SynthPreset    # preset neutre jouable

@dataclass
class KitRow:  name: str; sound: Sound
@dataclass
class Kit:
    path: Path | None; name: str; rows: list[KitRow]; params: dict[str, int]
    lpf_mode: str; mod_fx_type: str; doc: DelugeDoc | None
    @classmethod
    def load(cls, path: Path) -> Kit
    def save(self, path=None, backup=True) -> Path
    def sample_paths(self) -> list[str]
    @classmethod
    def new(cls, name: str = "KIT") -> Kit

@dataclass
class Note:      pos:int; length:int; velocity:int; condition:int; lift:int = 0
@dataclass
class NoteRow:   y:int; notes:list[Note]; muted:bool=False; colour_offset:int=0
@dataclass
class Clip:
    name:str; length:int; section:int; colour_offset:int
    preset_name:str; preset_folder:str; is_kit:bool
    note_rows:list[NoteRow]
    @property
    def bars(self) -> float          # length / ticks_per_bar (96 << inputTickMagnitude,
                                     # posé par le morceau : 384 en c1.2.1)
    @property
    def note_count(self) -> int
@dataclass
class Song:
    path: Path | None; name: str
    tempo_bpm: float; root_note: int; mode_notes: list[int]
    swing_amount: int; swing_interval: int
    clips: list[Clip]; arrangement_clips: list[Clip]
    instruments: list[dict]          # {'kind':'sound'|'kit'|'midi'|'cv', 'name':…, 'folder':…}
    preview: str                     # hex de la vignette 144 pads
    firmware: str; doc: DelugeDoc | None
    @classmethod
    def load(cls, path: Path) -> Song
    def sample_paths(self) -> list[str]
    def scale_name(self) -> str      # 'Do majeur', 'La mineur', 'Ré dorien'…
    def stats(self) -> dict          # {'clips':…, 'notes':…, 'bars':…, 'sections':…, 'density':…}
    def preview_colors(self) -> list[list[str]]   # matrice 8x18 de couleurs hex depuis `preview`,
                                                  # première ligne = rangée du HAUT (le fichier
                                                  # commence par celle du bas, cf. §5.23)

def tempo_from_song_attrs(time_per_timer_tick: int, timer_tick_fraction: int,
                          input_tick_magnitude: int) -> float
    """BPM = 60 / ((timePerTimerTick + fraction/2^32) * 2^inputTickMagnitude / 44100 * 48)
       — utiliser la formule du firmware : voir implémentation de référence ci-dessous."""
```
> **Formule tempo Deluge** — *corrigée le 10/10/2026 sur les 46 morceaux de la carte* :
> `ticks = time_per_timer_tick + (timer_tick_fraction & 0xFFFFFFFF) / 4294967296`
> `samples_per_tick = ticks * (2 ** input_tick_magnitude)`
> `bpm = 44100.0 * 60.0 / (samples_per_tick * 24.0)`
>
> Deux points que la rédaction initiale avait manqués :
> 1. **`timer_tick_fraction` est une fraction NON SIGNÉE**, alors que l'attribut XML est écrit
>    en entier 32 bits signé (`timerTickFraction="-1342177280"`). Sans le `& 0xFFFFFFFF`,
>    8 morceaux sur 46 tombent à ~0,3 BPM de la bonne valeur.
> 2. **Le diviseur est 24, pas 48** — 24 ticks par noire, conformément au §1.6 de ce même
>    document. Preuves : `DEFAULT.XML` donne alors exactement **120 BPM** (défaut d'usine du
>    Deluge) au lieu de 60, et les 46 morceaux donnent **tous** un BPM entier, dans une plage
>    de 69 à 124 BPM. Avec 48, la plage était 34–62 BPM, invraisemblable pour ce répertoire.
>
> Ces 24 ticks sont ceux de l'horloge extérieure : **les notes**, elles, comptent
> `96 << inputTickMagnitude` ticks par mesure (§1.6, corrigé le 14 octobre 2026) — un clip
> de `length=1536` fait 4 mesures en c1.2.1. Si le calcul donne une valeur hors
> de [20, 400], retourner 120.0 et journaliser le rejet.
> Couvert par les tests `TestTempo.*`.

### 4.6 `delugeapp/core/wav.py` — audio sans dépendance externe
```python
@dataclass
class AudioInfo:
    path: Path; sample_rate: int; channels: int; bit_depth: int; frames: int
    duration: float; fmt: str            # 'pcm' | 'float' | 'aiff'
    loop_start: int | None; loop_end: int | None      # chunk 'smpl' si présent
    root_note: int | None                             # chunk 'smpl' MIDI unity note
    ok: bool; error: str = ""

def probe(path: Path) -> AudioInfo                    # lecture des en-têtes seulement (rapide)
def read(path: Path, max_frames: int | None = None, mono: bool = False) -> tuple[np.ndarray, int]
    """Retourne (données float32 dans [-1,1], forme (frames, channels) ou (frames,) si mono, sr)."""
def write(path: Path, data: np.ndarray, sample_rate: int, bit_depth: int = 16) -> None
def peaks(path: Path, buckets: int = 1200) -> np.ndarray
    """Enveloppe min/max pour affichage : tableau (buckets, 2) float32. Lecture par blocs."""
def convert(src: Path, dst: Path, sample_rate: int | None = None, bit_depth: int | None = None,
            mono: bool | None = None, normalize_db: float | None = None,
            trim_silence_db: float | None = None, fade_ms: float = 0.0) -> AudioInfo
```
Formats à gérer en lecture : WAV PCM 8/16/24/32 bits, WAV float 32/64, WAV extensible
(`WAVE_FORMAT_EXTENSIBLE`), AIFF/AIFF-C PCM. Ne jamais lever d'exception : retourner
`AudioInfo(ok=False, error=…)`.

```python
DELUGE_MIN_RATE = 5000; DELUGE_MAX_RATE = 96000; DELUGE_EXT = (".wav", ".aif", ".aiff")
def deluge_problem(path) -> tuple[str, bool]   # ("", False) si le Deluge le lit,
                                               # sinon (raison, réparable par convert)
```
`deluge_problem` applique les règles du firmware (§1.8) en parcourant les blocs comme lui ;
*réparable* : en-tête étendu, RIFX, RF64, AIFC, A-law/µ-law, flottant 64, résolution
inhabituelle, fréquence hors bornes — à condition que l'application sache lire le
fichier. Jamais réparable : trois canaux et plus, codage compressé, fichier abîmé.

### 4.7 `delugeapp/core/audio_out.py`
```python
class Player:
    """Lecture d'aperçu. Utilise sounddevice si disponible, sinon winsound (WAV 16 bits), sinon muet."""
    def __init__(self) -> None
    @property
    def available(self) -> bool
    @property
    def backend(self) -> str                  # 'sounddevice' | 'winsound' | 'none'
    def devices(self) -> list[str]
    def set_device(self, name: str | None) -> None
    def set_volume(self, v: float) -> None
    def play_file(self, path: Path, loop: bool = False) -> None
    def play_array(self, data: np.ndarray, sample_rate: int, loop: bool = False) -> None
    def stop(self) -> None
    @property
    def is_playing(self) -> bool
    def position(self) -> float               # secondes écoulées (0.0 si inconnu)
```

### 4.8 `delugeapp/core/db.py` — index SQLite
Schéma (créé/migré par `init_db`) :
```sql
meta(key TEXT PRIMARY KEY, value TEXT)
samples(id INTEGER PK, rel TEXT UNIQUE, name TEXT, folder TEXT, ext TEXT, size INT, mtime REAL,
        sr INT, channels INT, bit_depth INT, frames INT, duration REAL,
        hash TEXT, peak REAL, rms REAL, bpm REAL, key TEXT, category TEXT,
        used_count INT DEFAULT 0, ok INT DEFAULT 1, error TEXT)
presets(id INTEGER PK, rel TEXT UNIQUE, kind TEXT, name TEXT, folder TEXT, size INT, mtime REAL,
        firmware TEXT, mode TEXT, category TEXT, osc1 TEXT, osc2 TEXT, filter TEXT,
        fx TEXT, uses_samples INT, summary TEXT, ok INT DEFAULT 1, error TEXT)
songs(id INTEGER PK, rel TEXT UNIQUE, name TEXT, size INT, mtime REAL, firmware TEXT,
      tempo REAL, scale TEXT, clips INT, notes INT, bars REAL, instruments INT,
      preview TEXT, ok INT DEFAULT 1, error TEXT)
links(src_kind TEXT, src_rel TEXT, dst_rel TEXT, dst_norm TEXT, missing INT)
tags(id INTEGER PK, name TEXT UNIQUE, color TEXT)
item_tags(kind TEXT, rel TEXT, tag_id INT)
ratings(kind TEXT, rel TEXT, stars INT, favorite INT, notes TEXT, PRIMARY KEY(kind, rel))
```
Index : `links(dst_norm)`, `samples(hash)`, `samples(folder)`, `presets(kind, folder)`.

Colonnes ajoutées après la rédaction initiale, car les contrôles de santé du §4.13 les
exigent : `samples.rel_norm`, `samples.hash_full`, `samples.dc_offset`, `samples.clipped`,
`presets.rel_norm`, `presets.repaired`, `songs.rel_norm`, `songs.repaired`.

> **Règle de migration (établie le 10/10/2026).** `CREATE TABLE IF NOT EXISTS` ne modifie
> **pas** une table déjà présente : une base écrite par une version antérieure garde ses
> anciennes colonnes, et toute insertion citant une colonne neuve échoue. Monter
> `SCHEMA_VERSION` ne suffit donc pas. `Library` procède en trois temps, dans cet ordre :
> 1. créer les tables manquantes ;
> 2. `ALTER TABLE … ADD COLUMN` pour chaque colonne absente (`Library._ADDED_COLUMNS`) —
>    les données de l'utilisateur (tags, notes, favoris) sont **conservées** ;
> 3. **créer les index seulement ensuite** — un index portant sur une colonne encore absente
>    fait échouer tout le script, ce qui s'est produit avec `idx_samples_hashf`.
>
> Après une montée de version, `Library.needs_rescan` vaut vrai : les colonnes neuves sont
> vides jusqu'à la prochaine analyse. Couvert par `TestLibraryAndScan` et vérifié sur une
> base v1 réelle.
```python
class Library:
    def __init__(self, db_path: Path)
    def close(self) -> None
    def init_db(self) -> None
    def clear(self) -> None
    def begin(self) / def commit(self)
    def upsert_sample(self, row: dict) -> None
    def upsert_preset(self, row: dict) -> None
    def upsert_song(self, row: dict) -> None
    def replace_links(self, src_kind: str, src_rel: str, dsts: list[tuple[str,bool]]) -> None
    def search_samples(self, text: str = "", folder: str = "", category: str = "",
                       tag: str = "", min_dur: float = 0, max_dur: float = 0,
                       only_unused: bool = False, only_missing: bool = False,
                       favorite: bool = False, limit: int = 5000) -> list[sqlite3.Row]
    def search_presets(self, kind: str = "synth", text: str = "", folder: str = "",
                       category: str = "", tag: str = "", limit: int = 5000) -> list[sqlite3.Row]
    def search_songs(self, text: str = "") -> list[sqlite3.Row]
    def folders(self, kind: str) -> list[tuple[str, int]]
    def stats(self) -> dict
    def duplicates(self) -> list[list[sqlite3.Row]]        # groupes par hash identique
    def unused_samples(self) -> list[sqlite3.Row]
    def missing_links(self) -> list[sqlite3.Row]
    def set_rating(self, kind, rel, stars=None, favorite=None, notes=None) -> None
    def get_rating(self, kind, rel) -> dict
    def add_tag(self, kind, rel, tag: str, color: str = "") -> None
    def remove_tag(self, kind, rel, tag: str) -> None
    def tags_of(self, kind, rel) -> list[str]
    def all_tags(self) -> list[tuple[str, str, int]]
    def recompute_usage(self) -> None                       # met à jour samples.used_count
```

**L'index est sûr entre fils d'exécution.** ``check_same_thread=False`` ne
rend pas une connexion SQLite partageable : il désactive seulement la
vérification de Python. La connexion est donc enveloppée dans un proxy qui
prend un verrou réentrant (``Library.lock``, public) **et matérialise le
résultat sous ce verrou** : un curseur lu plus tard, pendant qu'un autre fil
interroge la même connexion, entrelace les appels à SQLite. Mesuré avant
correction, sur douze diagnostics de santé lancés en parallèle : « bad
parameter or other API misuse », des lignes tronquées, et **deux notes
différentes pour la même carte** (85 ou 90 selon la course). Un contrôle de
santé avale ses erreurs : le rapport avait l'air normal.

### 4.9 `delugeapp/core/scan.py`
```python
@dataclass
class ScanProgress: phase:str; current:int; total:int; message:str
@dataclass
class ScanResult:   samples:int; presets:int; kits:int; songs:int; errors:list[str]; seconds:float

def scan_card(sd: SDCard, lib: Library, *, compute_hash: bool = True,
              analyze: bool = False, full: bool = True,
              progress: Callable[[ScanProgress], None] | None = None,
              should_stop: Callable[[], bool] | None = None) -> ScanResult
    """Indexe toute la carte. `full=False` = incrémental (mtime/size inchangés -> ignoré).
       Doit rester interruptible et ne jamais lever : toute erreur va dans ScanResult.errors."""
def file_hash(path: Path, quick: bool = True) -> str
    """quick=True : SHA-1 sur taille + 64 Kio de tête + 64 Kio de MILIEU + 64 Kio de queue.
       Sinon SHA-1 complet."""
def confirm_duplicates(sd, lib, progress=None, should_stop=None) -> list[list[str]]
    """Confirme par empreinte COMPLÈTE les seuls groupes soupçonnés. Obligatoire."""
```

> **Correction mesurée (10/10/2026) — l'empreinte rapide ne prouve pas un doublon.**
> La rédaction initiale ne prenait que la tête et la queue du fichier. Sur cette carte, les
> fichiers `SAMPLES/Artists/Danny Taurus/MoDrama/Upper{01,14,20}.wav` ont **la même taille**
> et **les mêmes 64 Kio de tête et de queue** (du silence), alors qu'ils diffèrent sur
> **1 407 blocs de 1 Kio sur 1 722**. L'empreinte initiale les déclarait donc doublons :
> proposés à la suppression, l'utilisateur perdait trois échantillons bien réels.
>
> Deux corrections, les deux nécessaires :
> 1. l'empreinte rapide intègre désormais **un bloc du milieu** — ce qui suffit à écarter ce
>    cas précis (la carte ne contient en réalité **aucun** doublon) ;
> 2. mais un bloc de plus ne démontre rien, donc **`Library.duplicates()` ne renvoie que des
>    groupes confirmés octet pour octet**. `Library.duplicate_candidates()` donne les
>    soupçons, `scan.confirm_duplicates()` les vérifie en lisant les fichiers en entier — ce
>    qui reste peu coûteux, puisque seuls les candidats sont relus.
>
> **Règle à maintenir : jamais de suppression proposée sur la foi d'une empreinte partielle.**
> Couvert par `TestLibraryAndScan.test_empreinte_rapide_ne_suffit_pas` et
> `test_doublon_reel_est_confirme`.

### 4.10 `delugeapp/core/analysis.py` (numpy seul)
```python
def detect_bpm(data: np.ndarray, sr: int, lo: float = 60, hi: float = 200) -> tuple[float, float]
    """(bpm, confiance 0..1) par flux spectral + autocorrélation de l'enveloppe d'attaque."""
def detect_key(data: np.ndarray, sr: int) -> tuple[str, float]
    """('C#m', confiance) via chromagramme + corrélation aux profils Krumhansl-Schmuckler."""
def loudness(data: np.ndarray) -> dict      # {'peak_db','rms_db','crest','dc_offset','true_peak_db'}
def spectral(data: np.ndarray, sr: int) -> dict   # {'centroid','rolloff85','flatness','bandwidth'}
def transients(data: np.ndarray, sr: int, sensitivity: float = 1.0) -> np.ndarray  # positions (frames)
def silence_bounds(data: np.ndarray, threshold_db: float = -60.0) -> tuple[int, int]
def classify_drum(name: str, info: dict, spec: dict) -> str
    """Catégorie DRUMS du Deluge ('Kick','Snare','HatC',…) par nom + descripteurs."""
def estimate_root_note(data: np.ndarray, sr: int) -> int | None   # note MIDI fondamentale
def note_name(midi: int, french: bool = True) -> str              # 60 -> 'Do3' / 'C3'
def chromagram(data: np.ndarray, sr: int) -> np.ndarray           # (12,)
```
Algorithmes : DFT par `np.fft.rfft` sur fenêtres de Hann 2048/hop 512. Ne jamais dépasser
30 s de signal (sous-échantillonner) pour rester rapide.

### 4.11 `delugeapp/core/deps.py`
```python
@dataclass
class DepGraph:
    used_by: dict[str, list[tuple[str, str]]]   # norm_rel(sample) -> [(kind, rel_source), …]
    missing: list[tuple[str, str, str]]          # (kind, source_rel, sample_rel)
    unused: list[str]
    def usage_count(self, rel: str) -> int

def build_graph(sd: SDCard, lib: Library) -> DepGraph
def samples_of_song(song: Song) -> list[str]
def presets_of_song(song: Song) -> list[tuple[str, str]]     # (folder, name)
def relink(sd: SDCard, old_rel: str, new_rel: str, apply: bool = False,
           progress=None) -> list[tuple[Path, int]]
    """Réécrit fileName dans TOUS les XML concernés. Retourne [(fichier, nb remplacements)].
       apply=False -> simulation."""
def find_replacement(sd: SDCard, missing_rel: str, lib: Library) -> list[str]
    """Candidats de remplacement pour un échantillon manquant (même nom, nom proche, même durée)."""
```

### 4.12 `delugeapp/core/organize.py`
```python
@dataclass
class Op:   kind:str; src:Path; dst:Path|None; note:str      # kind: 'move'|'rename'|'delete'|'mkdir'|'relink'
@dataclass
class Plan:
    ops: list[Op]
    size: int = 0      # octets concernés quand le plan les a comptés (parasites)
    def summary(self) -> str
    def apply(self, sd: SDCard, lib: Library, progress=None) -> tuple[int, list[str]]
        """Exécute. Déplace d'abord, puis relink les XML. Retourne (réussies, erreurs)."""

def plan_auto_classify_drums(sd, lib) -> Plan        # range SAMPLES/**/ vers SAMPLES/DRUMS/<cat>/
def plan_dedupe(sd, lib, keep: str = "shortest_path") -> Plan
def plan_rename(sd, items: list[str], pattern: str, apply_case: str = "") -> Plan
    """pattern accepte {name} {n} {n:03} {folder} {cat} {bpm} {key} {sr} {dur}"""
def plan_flatten(sd, folder: str) -> Plan
def plan_group_by(sd, lib, key: str) -> Plan          # key: 'category'|'bpm'|'key'|'duration'|'artist'
def plan_purge_junk(sd) -> Plan                       # ._*, .DS_Store, Thumbs.db ; corbeilles et
                                                      # dossiers système élagués du parcours (os.scandir :
                                                      # 0,82 s -> 0,04 s sur 16 936 fichiers)
def plan_archive_unused(sd, lib, dest: str = "_UNUSED") -> Plan
def plan_fix_names(sd, lib) -> Plan                   # noms non compatibles FAT32/Deluge
def suggest_folder(name: str, category: str) -> str
```

### 4.13 `delugeapp/core/health.py`
```python
SEVERITY = ("info", "warn", "error")
@dataclass
class Issue:
    code:str; severity:str; title:str; detail:str
    items:list[str]; fix:str = ""; auto_fixable:bool = False
@dataclass
class HealthReport:
    issues:list[Issue]; score:int                     # 0..100
    def by_severity(self, sev) -> list[Issue]
    def to_text(self) -> str
    def to_html(self) -> str

def check_card(sd: SDCard, lib: Library, progress=None) -> HealthReport
def autofix(sd: SDCard, lib: Library, codes: list[str], apply: bool = False) -> Plan
```
Contrôles attendus (codes) : `MISSING_SAMPLE`, `ORPHAN_SAMPLE`, `DUPLICATE_SAMPLE`,
`MAC_JUNK`, `MULTI_FIRMWARE`, `NO_FIRMWARE`, `BAD_NAME`, `LONG_PATH`, `DEEP_FOLDER`,
`UNREADABLE_XML`, `REPAIRED_XML`, `ODD_SAMPLE_RATE`, `BIG_SAMPLE`, `EMPTY_FOLDER`,
`MISSING_STD_DIR`, `LOW_SPACE`, `NON_AUDIO_IN_SAMPLES`, `DC_OFFSET`, `CLIPPED_SAMPLE`,
`SILENT_SAMPLE`, `STEREO_DRUM`, `NO_BACKUP`.
Score : 100 − (5 × erreurs + 2 × avertissements), borné à [0, 100].

### 4.14 `delugeapp/core/backup.py`
```python
@dataclass
class BackupInfo: path:Path; when:datetime; files:int; bytes:int; label:str

def list_backups(backup_dir: Path) -> list[BackupInfo]
def create_backup(sd: SDCard, backup_dir: Path, label: str = "",
                  include_samples: bool = True, zip_it: bool = False,
                  progress=None, should_stop=None) -> BackupInfo
def restore_backup(info: BackupInfo, sd: SDCard, progress=None) -> tuple[int, list[str]]
def diff_backup(info: BackupInfo, sd: SDCard) -> dict   # {'added':[…],'removed':[…],'changed':[…]}
def snapshot_xml(path: Path) -> Path                    # copie .bak horodatée d'un seul fichier
```

### 4.15 `delugeapp/core/genres.py`
```python
@dataclass
class GenreProfile:
    key:str; label:str; color:str; bpm:tuple[int,int]
    description:str
    osc_types:list[tuple[str,float]]          # (type, poids)
    filter_mode:list[tuple[str,float]]
    cutoff:tuple[int,int]                     # en unités d'affichage 0..50
    resonance:tuple[int,int]
    env1:dict[str,tuple[int,int]]             # attack/decay/sustain/release en 0..50
    env2:dict[str,tuple[int,int]]
    unison:tuple[int,int]; detune:tuple[int,int]
    lfo_rate:tuple[int,int]; lfo_types:list[str]
    fx:dict[str,tuple[int,int]]               # reverbAmount, delayFeedback, delayRate, modFXDepth…
    cable_recipes:list[list[tuple[str,str,tuple[int,int]]]]   # jeux de patch cables alternatifs
    arp_probability:float
    roles:dict[str, dict]                     # surcharges par rôle : bass/lead/pad/pluck/keys/fx/drone/arp

GENRES: dict[str, GenreProfile]
ROLES: tuple[str, ...] = ("bass","lead","pad","pluck","keys","stab","fx","drone","arp","bell")
def genre(key: str) -> GenreProfile
def genre_keys() -> list[str]
```
**Genres à fournir (au moins 18)** : `acid`, `techno`, `detroit`, `minimal`, `house`, `deep_house`,
`trance`, `psytrance`, `dnb`, `jungle`, `dubstep`, `ambient`, `berlin_school`, `synthwave`,
`lofi`, `idm`, `industrial`, `electro`, `hardcore`, `downtempo`, `funk`, `boards_of_canada`.
Chaque profil doit avoir une `description` en français d'une phrase, une couleur de `PAD_CYCLE`,
et une plage de BPM réaliste.

### 4.16 `delugeapp/core/synthgen.py` — générateur de presets
```python
@dataclass
class GenOptions:
    genre:str = "techno"; role:str = "bass"; seed:int | None = None
    brightness:float = 0.5      # 0..1, décale le cutoff
    movement:float = 0.5        # 0..1, intensité des LFO/enveloppes de modulation
    space:float = 0.5           # 0..1, reverb/delay
    dirt:float = 0.5            # 0..1, distorsion/bitcrush/résonance
    width:float = 0.5           # 0..1, unison/detune/chorus
    complexity:float = 0.5      # 0..1, nombre de patch cables
    mode:str = ""               # '' = choisi par le genre ; sinon subtractive|fm|ringmod
    use_samples:list[str] = []  # échantillons à utiliser (osc type 'sample')
    name:str = ""

def generate(opts: GenOptions) -> SynthPreset
def randomize(seed: int | None = None, role: str = "") -> SynthPreset
def mutate(preset: SynthPreset, amount: float = 0.25, seed=None) -> SynthPreset
def morph(a: SynthPreset, b: SynthPreset, t: float) -> SynthPreset      # t 0..1
def variations(preset: SynthPreset, n: int = 8, amount: float = 0.3, seed=None) -> list[SynthPreset]
def describe(preset: SynthPreset) -> str        # description du son, dans la langue de l'interface
def suggest_name(opts: GenOptions, seed: int) -> str
    """Nom évocateur à partir d'un lexique FR/EN : 'ACID GROWL 3', 'NEON PAD'…"""
```
Exigences : le preset produit doit **toujours être audible et jouable** — volume principal non nul,
au moins un oscillateur audible, enveloppe 1 avec un sustain ou un decay non nul, cutoff jamais
totalement fermé sans modulation qui l'ouvre. Toute génération est **reproductible** à partir
de `seed`. `generate()` doit utiliser `random.Random(seed)` — jamais le `random` global.

> **Correction mesurée (13 octobre 2026) — ce que le firmware et la carte imposent.**
> - **Arpégiateur** : un fichier qui se déclare c1.2.0 ou plus récent n'a plus son attribut
>   `mode` lu (`sound.cpp` de la 1.2.1). Il faut écrire `arpMode="arp"`, `noteMode`
>   (`up`, `down`, `upDown`, `random`, `asPlayed`) et `octaveMode` (`up`, `down`, `upDown`,
>   `alt`, `random`). Le générateur écrit les deux, `mode` restant pour les vieux firmwares.
> - **`syncLevel`** (valeur du fichier) : `2^(3 − niveau)` mesures — 5 = noire,
>   7 = double-croche. Les arpèges se tirent en 6, 7 ou 8, jamais 9 (quadruple-croche).
> - **Playabilité** : `velocity → volume` est posé sur **tous** les presets (778 réels sur 911).
> - **Recalage** : les plages par rôle visent l'écart interquartile des 911 presets de la carte.
>   Plausibilité mesurée (médiane générée dans l'écart interquartile réel) : **56 % → 97 %**,
>   les six signatures de genre contrôlées tenant toujours.
> - **FM** : `Sound.modulator1`/`modulator2` (accord en demi-tons et cents, `toModulator1`),
>   tirés dans la distribution des 145 presets FM de la carte ; écrits seulement en FM.

> **Correction mesurée (14 octobre 2026) — les traits que le générateur ignorait.**
> Relevés par rôle sur les 911 presets, et tenus à quelques points près (880 tirages par rôle) :
> portamento (33 % des basses, 25 % des leads ; facteur de genre `GenreProfile.glide` :
> 70 % des basses acid, 20 % des basses house), saturation `clippingAmount` 2 à 5 (27 à 56 %
> selon le rôle, modulée par le curseur de saleté), synchro du délai (croche pour les sons
> joués, double-croche pour nappes et bourdons), passe-haut, effet de modulation (11 à 38 %
> selon le rôle, chorus pour basses et claviers, phaser pour leads et nappes), mode de jeu des
> basses et leads (un tiers poly, un tiers legato, un quart mono), variantes « analog » des
> formes d'onde. **La graine du tirage mêle graine, genre et rôle** (`"{seed}|{genre}|{rôle}"`) :
> une même graine ne fait plus les mêmes choix dans tous les genres. Une graine donne donc un
> autre son qu'avant ce recalage — la reproductibilité vaut à version égale du générateur.

### 4.17 `delugeapp/core/kitgen.py`
```python
@dataclass
class KitSlot: role:str; rel:str; name:str; family:str   # role: 'Kick','Snare','HatC',…
def build_kit(sd: SDCard, lib: Library, name: str, genre: str = "techno",
              seed: int | None = None, slots: list[str] | None = None,
              prefer_folder: str = "") -> Kit
    """Kit bâti autour d'une famille principale (machine ou banque), complété ailleurs."""
def family_of(rel: str) -> str        # '909', 'Linndrum', 'SAMPLES/Artists/…/Y2K', 'Synthstrom n°'
def library_families(lib: Library) -> dict[str, dict[str, list]]   # famille -> rôle -> lignes
def kit_from_folder(sd: SDCard, folder: str, name: str = "") -> Kit
def suggest_slots(genre: str) -> list[str]
def row_role(row: KitRow) -> str      # rôle d'une rangée : son nom (« HATC ») ou son fichier
def reroll_row(kit: Kit, index: int, lib: Library, genre: str = "techno",
               seed=None, avoid=()) -> KitSlot | None
    """Autre échantillon du même rôle pour une rangée : même famille d'abord, puis les
    familles du genre ; jamais un fichier du kit ni un de `avoid` (déjà essayés).
    None s'il n'y a plus de candidat — la rangée reste alors telle quelle."""
DEFAULT_SLOTS: tuple[str, ...]
GENRE_AFFINITY: dict[str, tuple[str, ...]]   # machines qu'un genre appelle ('909' pour la techno…)
ROLE_VOLUME: dict[str, int]                  # médianes réelles : grosse caisse 38, ride 30…
ROLE_PAN: dict[str, int]                     # médianes réelles : TomL +9, TomH −12, ride +5…
```
Les rangées sont réglées comme le Deluge les crée (`Kit.add_row`) : enveloppe ouverte
(attaque 0, sustain 50, release 0), `velocity → volume` à pleine échelle, fin de zone = longueur
réelle, et `loopMode` selon `model.repeat_mode_for(secondes)` : `ONCE` (1) sous 2,002 s,
`CUT` (0) au-delà — la règle du firmware (`sample_browser.cpp`, `slicer.cpp`). Mesuré sur les
523 rangées des 43 kits de la carte : `loopMode` 1 dans 83 %, `velocity → volume` sur 505.
Familles par kit : 9,9 → **1,9** ; rôle confirmé par le nom ou le dossier : 100 %.
Volume et panoramique par rôle : médianes des 523 rangées réelles (41 kits sur 43 règlent leurs
rangées une à une). Pas de compensation selon le niveau des fichiers : la loi du paramètre
`volume` du firmware n'a pas été établie, et rien ne se code sur une loi supposée.

### 4.18 `delugeapp/core/theory.py`
```python
NOTE_NAMES_FR = ("Do","Do#","Ré","Mib","Mi","Fa","Fa#","Sol","Sol#","La","Sib","Si")
NOTE_NAMES_EN = ("C","C#","D","D#","E","F","F#","G","G#","A","A#","B")
SCALES: dict[str, tuple[int, ...]]        # >=20 gammes : majeur, mineur naturel/harmonique/mélodique,
                                          # dorien, phrygien, lydien, mixolydien, locrien,
                                          # pentatonique maj/min, blues, gamme par tons,
                                          # diminuée, hongroise, japonaise (in sen), arabe (hijaz)…
CHORDS: dict[str, tuple[int, ...]]        # maj, min, dim, aug, 6, m6, 7, maj7, m7, m7b5, dim7,
                                          # sus2, sus4, 9, maj9, m9, add9, 11, 13, 7b9, 7#9…
PROGRESSIONS: dict[str, list[list[str]]]  # par genre/humeur : ['i','VI','III','VII'] …
CHORD_COLORS: dict[str, str]              # triades, septièmes, neuvièmes, suspendus
AMBIANCE_COLORS: dict[str, str]           # jazz/house -> septièmes, deep/ambient -> neuvièmes

def scale_notes(root: int, scale: str, octaves: int = 1) -> list[int]
def chord_notes(root: int, chord: str, inversion: int = 0, voicing: str = "close") -> list[int]
def diatonic_chords(root: int, scale: str, sevenths: bool = False) -> list[tuple[str, list[int]]]
def colored_chord(root: int, scale: str, degree: int, color: str = "triades"
                  ) -> tuple[list[int], list[int], str]   # (empilement, notes jouées, suffixe)
    """Neuvièmes jouées SANS fondamentale (tierce, quinte, septième, neuvième : la basse tient
    la fondamentale) ; pas de neuvième mineure, pas de « sus4 » sur une quarte augmentée."""
def progression(root: int, scale: str, name: str = "", seed=None, bars: int = 4,
                color: str = "") -> list[dict]
    """[{'degree':'i','symbol':'i','name':'Lam','root':57,'quality':'min',
         'notes':[57,60,64],'bass':45,'bars':1,'color':'triades',
         'function':'tonique'}, …]
    Le nom vient de la fondamentale et de la qualité AVANT conduite des voix (le VI de la
    mineur s'appelait « La » quand on le lisait sur la note grave déplacée)."""
FUNCTIONS: dict[int, str]       # degré -> tonique (I, iii, vi), sous-dominante (ii, IV), dominante (V, vii°)
def substitute(progression, position, root, scale, seed=None) -> list[dict]
    """Nouvelle progression où l'accord `position` prend un autre degré de même fonction,
    même couleur, ni égal à lui ni (sauf faute d'autre choix) à ses voisins ; l'accord
    suivant est reconduit depuis lui. L'originale n'est pas modifiée."""
def circle_of_fifths() -> list[tuple[str, str]]          # (majeur, relatif mineur)
def camelot(key_name: str) -> str                        # '8A', '5B'… pour le mixage harmonique
def compatible_keys(key_name: str) -> list[str]
def note_to_name(midi: int, french: bool = True, with_octave: bool = True) -> str
def name_to_note(name: str) -> int
def deluge_mode_notes(scale: str, official: bool = False) -> list[int]
    """<modeNotes> : la gamme telle quelle (c1.x accepte 5, 6 ou 7 notes) ; official=True
    donne sept valeurs, une gamme courte étant complétée par son mode parent."""
def deluge_scale_name(scale: str) -> str      # 'PENTATONIC MINOR', … ou 'USER'
def scale_spelling(root: int, scale: str, french: bool = True) -> dict[int, str]
    """Orthographe selon la tonalité : do mineur = Do Ré Mib Fa Sol Lab Sib."""
def spell(midi: int, spelling: dict | None, with_octave: bool = True, french: bool = True) -> str
def chord_quality(notes: list[int]) -> str     # clé de CHORDS d'après les intervalles réels
def transpose(notes: list[int], semis: int) -> list[int]
def voice_leading(a: list[int], b: list[int]) -> list[int]  # b réagencé pour minimiser le mouvement
def frequency(midi: int, a4: float = 440.0) -> float
```

### 4.19 `delugeapp/core/rhythm.py`
```python
@dataclass
class Step: pos:int; velocity:int; length:int; probability:int = 100; grid:int|None = None
    # pos en pas, fractionnaire après swing/groove ; velocity et probability en POUR-CENT
    # (1..100) ; grid = case d'origine, pour réappliquer un groove depuis le motif droit
@dataclass
class Pattern:
    name:str; steps:int; ppq:int = 24              # 24 ticks par noire -> pas de 1/16 = 6 ticks
    tracks:dict[str, list[Step]]                   # 'Kick' -> [Step…]
    def to_notes(self, row_map: dict[str, int]) -> dict[int, list[Note]]
    def ascii(self) -> str

def euclid(pulses: int, steps: int, rotate: int = 0) -> list[bool]
def euclid_pattern(spec: dict[str, tuple[int,int,int]]) -> Pattern
def genre_beat(genre: str, bars: int = 1, seed=None, fills: bool = True) -> Pattern
    """Motifs idiomatiques : four-on-the-floor, breakbeat, amen, half-time, gabber…"""
def humanize(p: Pattern, timing: float = 0.0, velocity: float = 0.0, seed=None) -> Pattern
def swing(p: Pattern, amount: float) -> Pattern
def polyrhythm(a: int, b: int, steps: int) -> list[bool]
GROOVES: dict[str, list[float]]                     # ticks de retard : 'MPC 54 %'…'MPC 71 %',
                                                    # 'laid-back', 'en avant', 'droit'
def swing_offsets(percent: float) -> list[float]    # swing MPC : (2·p/100 − 1)·6 ticks
def deluge_swing(groove: str) -> int | None         # réglage de swing du Deluge équivalent
def apply_groove(p: Pattern, groove: str, strength: float = 1.0) -> Pattern
def straighten(p: Pattern) -> Pattern               # chaque pas remis à sa case d'origine
BACKBONE = ("Kick", "Snare", "Clap")                # jamais un coup retiré par une variation
VARIATIONS: dict[str, str]                          # fantômes, charleys, percussion, grosse caisse, ouverture
def variation(p: Pattern, genre: str = "", seed=None, amount: float = 0.5) -> Pattern
    """Ornements tirés (1 à 3 selon amount), ossature intacte ; pas de charleys serrés
    pour ambient, downtempo, dubstep, Boards of Canada."""
def loop(p: Pattern, bars: int) -> Pattern           # motif répété sur `bars` mesures
def delay_times(bpm: float) -> list[dict]
    """Table des temps de delay/LFO : [{'div':'1/8','ms':…,'hz':…,'dotted_ms':…,'triplet_ms':…}, …]"""
def bars_to_ticks(bars: float) -> int               # 96 ticks / mesure 4/4
```

### 4.20 `delugeapp/core/midifile.py` (écriture MIDI pure stdlib)
```python
@dataclass
class MidiTrack: name:str; channel:int; events:list[tuple[int,int,int,int]]  # (tick, note, vel, dur)
def write_midi(path: Path, tracks: list[MidiTrack], bpm: float = 120.0, ppq: int = 96,
               markers: list[tuple[int, str]] | None = None) -> None   # repères (méta 0x06)
def pattern_to_midi(path: Path, pattern: Pattern, row_map: dict[str,int], bpm: float) -> None
def progression_to_midi(path: Path, chords: list[dict], bpm: float, ppq: int = 96) -> None
def parts_to_midi(path: Path, parts: dict[str, list[NoteEvent]], bpm: float,
                  ppq: int = 96, markers=None) -> int   # une piste par partie, chacune
                                                        # sur son canal ; repères en pas
def clip_to_midi(path: Path, clip: Clip, bpm: float) -> None
```

### 4.20 bis `delugeapp/core/accomp.py` — accompagnement d'une progression
```python
@dataclass
class NoteEvent: start:float; length:float; note:int; velocity:int = 90   # pas de 1/16, pour-cent
CHORD_STYLES: dict[str, tuple[tuple[float, float], ...]]  # tenu, blanches, contretemps, stabs, charleston
BASS_STYLES: dict[str, str]          # fondamentale, pulsée, contretemps, roulante, octaves, syncopée,
                                     # marche, acide (303 : silences, accents, octaves, glissés)
GENRE_STYLES: dict[str, tuple[str, str, bool]]            # genre -> (accords, basse, arpège ?)
def chord_part(progression, style="tenu", velocity=80) -> list[NoteEvent]
def bass_part(progression, style="fondamentale", velocity=92) -> list[NoteEvent]
def arp_part(progression, order="montant", rate=2, octaves=1, velocity=76, seed=None) -> list[NoteEvent]
MELODY_STYLES: dict[str, str]        # posée, chantante, syncopée
GENRE_MELODY: dict[str, str]         # genre -> allure
def melody_part(progression, root=None, scale="", style="", genre="", seed=None,
                velocity=92) -> list[NoteEvent]
    """Phrases de quatre mesures A A B fin ; notes de l'accord sur les temps forts ; la
    mesure 2 reprend la 1 en marche ; mouvement surtout conjoint ; fin sur la fondamentale."""
def drum_part(pattern, bars=None) -> list[NoteEvent]  # motif -> notes General MIDI (GM_DRUMS)
def accompany(progression, genre="", chords="", bass="", arp=None, arp_order="montant",
              arp_rate=1, seed=None, melody=False, melody_style="", root=None, scale="",
              drums=None) -> dict[str, list[NoteEvent]]   # + 'Batterie' si drums (un Pattern)
def total_steps(parts) -> float
```
Canaux MIDI (`midifile.PART_CHANNELS`) : accords 1, basse 2, arpège 3, mélodie 4, batterie 10
(0 à 3 et 9 dans le fichier). Un glissé de la basse acide chevauche la note suivante, toujours
d'une autre hauteur : deux notes identiques qui se chevauchent se couperaient en MIDI.

### 4.20 ter `delugeapp/core/sketch.py` — esquisse d'un morceau
```python
ARRANGEMENTS: dict[str, tuple[tuple[str, int], ...]]   # modèle de structure par genre
SECTION_KINDS: dict[str, str]        # intro, montée, pic, cassure, fin
SECTION_PARTS: dict[str, tuple[str, ...]]
    # intro/fin : batterie légère + accords ; montée : + basse, arpège ;
    # pic : tout, mélodie comprise ; cassure : accords, arpège, mélodie
LIGHT_DRUMS = ("Kick", "HatC", "HatO", "Shaker", "Ride", "Rim")
GENRE_AMBIANCE: dict[str, str]       # ambiance de progression par défaut d'un genre
def section_kind(name: str) -> str   # « Refrain final » -> pic (les mots du sommet d'abord)
def plan(genre, arp=None, melody=True) -> list[Section]   # Section(name, kind, start, bars, parts)
def default_progression(genre, seed=None, root=57, scale="mineur") -> list[dict]
def sketch(progression, genre="techno", pattern=None, root=None, scale="", arp=None,
           melody=True, seed=None) -> Sketch    # Sketch(parts, sections, drums, bars) ; .markers()
def excerpt(result, index, max_bars=8) -> tuple[dict, Pattern | None, int]   # début d'une section, ramené à 0
```
La progression tourne sur toute la structure ; chaque section ne garde que les parties de son
rôle ; les sections au sommet jouent une variation du rythme (`rhythm.variation`) et une crash
marque leur entrée.
Écoute : `render.render_parts(parts, sounds, bpm, sr, sd)` — chaque partie jouée par un son généré
pour le genre ; une même note de même durée n'est rendue qu'une fois (quatre mesures : ~1 s).

### 4.21 `delugeapp/core/render.py` — moteur d'écoute hors-ligne (approximation du Deluge)
```python
def render_sound(sound: Sound, note: int = 48, seconds: float = 2.5, sr: int = 44100,
                 gate: float = 0.7, velocity: float = 0.9,
                 sd: SDCard | None = None) -> np.ndarray
    """Rend un son mono/stéréo float32. Gère : subtractive (2 osc + noise + unison + detune),
       fm (2 opérateurs), ringmod ; filtres LPF 12/24 dB et HPF ; enveloppes ADSR ;
       LFO1 (globale) et LFO2 ; patch cables les plus courants ; distorsion (clipping),
       bitcrush, sample rate reduction ; delay et reverb simples ; chorus/flanger/phaser.
       Si osc type == 'sample' et `sd` fourni, lit l'échantillon et le transpose."""
def render_preview(preset: SynthPreset, notes: list[int] | None = None, sr: int = 44100,
                   sd: SDCard | None = None) -> np.ndarray
    """Petite phrase (par défaut accord/arpège selon la catégorie) pour l'audition."""
def render_kit(kit: Kit, pattern: Pattern | None = None, bpm: float = 128, sr: int = 44100,
               sd: SDCard | None = None) -> np.ndarray
SYNTH_DRUM_ROLES: tuple[str, ...]    # les 22 rôles de la batterie synthétisée
def synth_drum(role: str, sr: int = 44100, velocity: float = 1.0) -> np.ndarray
    """Coup de batterie calculé (sinus tombants, bruit filtré par bande, partiels
    inharmoniques) : grosse caisse ~47 Hz, toms graves → aigus, charleys ~12 kHz."""
def render_pattern(pattern, bpm=120.0, sr=44100, kit=None, sd=None, bars=None,
                   tail=0.8) -> np.ndarray
    """Motif bouclé sur `bars` mesures ; chaque piste jouée par la rangée du kit de même nom,
    sinon par la batterie synthétisée (une piste euclidienne sonne aussi)."""
def mix(*tracks, levels=None) -> np.ndarray   # somme de rendus de longueurs différentes
def spectrum(data: np.ndarray, sr: int, n: int = 4096) -> tuple[np.ndarray, np.ndarray]
```
Qualité attendue : plausible, pas exact. Aucune dépendance hors numpy. Doit rendre 2,5 s
en moins de 400 ms.

### 4.22 `delugeapp/core/samplefix.py` — correction des défauts audio

Corrige les quatre défauts que `health` ne savait que signaler : percussions en
stéréo, fréquence d'échantillonnage inhabituelle, écrêtage, composante
continue. Les plans sont des **intentions** : `simulate()` les chiffre sans
rien écrire, `apply()` exécute.

```python
ACTIONS = ("trim", "mono", "dc", "rate", "normalize", "fade", "depth")
LENGTH_SAFE = ("mono", "dc", "normalize", "fade", "depth")   # trames inchangées
LENGTH_CHANGING = ("rate", "trim")                           # trames modifiées
HEALTH_CODES = ("STEREO_DRUM", "ODD_SAMPLE_RATE", "DC_OFFSET", "CLIPPED_SAMPLE")
BACKUP_ROOT = "_BACKUP"        # à la racine de la carte, comme _UNUSED

# Seuils et fréquences : IMPORTÉS de health, jamais redéfinis.
DC_THRESHOLD = health.DC_OFFSET_LIMIT
CLIP_THRESHOLD = health.CLIPPED_RATIO
STANDARD_RATES = health.GOOD_SAMPLE_RATES

@dataclass
class Edit:
    rel: str; actions: dict; reason: str
    before: dict; after: dict; skipped: str; error: str
    @property changes_length -> bool
    @property label -> str          # « stéréo → mono », « 32000 → 44100 Hz »…

@dataclass
class FixPlan:
    title: str; edits: list[Edit]; skipped: list[Edit]
    def counts() -> dict[str,int]; def summary() -> str; def to_text() -> str
    @property changes_length -> bool
    def simulate(sd, lib) -> FixResult                       # n'écrit rien
    def apply(sd, lib, backup=True, progress=None, should_stop=None) -> FixResult

@dataclass
class FixResult:
    done: list[str]; failed: list[tuple[str,str]]
    bytes_before: int; bytes_after: int
    retargeted: list[str]; zones_moved: int
    backup_dir: str; applied: bool
    @property bytes_saved -> int; def summary() -> str

def plan_mono(sd, lib, rels=None) -> FixPlan
def plan_standard_rate(sd, lib, rels=None, rate=44100) -> FixPlan
def plan_remove_dc(sd, lib, rels=None) -> FixPlan
def plan_headroom(sd, lib, rels=None, target_db=-1.0) -> FixPlan
def plan_custom(sd, lib, rels, mono=False, rate=None, dc=False,
                normalize_db=None, trim_db=None, fade_ms=0.0, depth=None) -> FixPlan
def plan_from_health(sd, lib, codes: list[str]) -> FixPlan
def song_locked_samples(sd) -> dict[str, list[str]]
def retarget_zones(sd, ratios: dict[str,float], apply=False) -> tuple[int, list[str]]
def restore(sd, backup_rel: str, lib=None, apply=False) -> tuple[int, list[str]]
```

`wav.convert()` gagne un paramètre `remove_dc: bool = False`. Ordre des
traitements : coupe du silence → mono/stéréo → **retrait du continu** →
rééchantillonnage → normalisation → fondus.

#### 4.22.1 Correction mesurée — les bornes en trames

**1 191 des 1 497 références de presets et de kits de la carte réelle bornent
leur échantillon en nombre de trames** (`startSamplePos`, `endSamplePos`,
`startLoopPos`, `endLoopPos`) ; les 306 autres sont en millisecondes. Changer
le nombre de trames d'un fichier décale donc la lecture des presets qui le
citent. `retarget_zones()` remet ces bornes à l'échelle dans la même
opération ; les zones en millisecondes sont laissées telles quelles, puisque
la durée réelle du fichier n'a pas bougé.

#### 4.22.2 Correction mesurée — les morceaux interdisent de changer la longueur

**Les 28 morceaux qui citent des échantillons les bornent tous en trames**
(884 références). `Song` étant volontairement en lecture seule (§0),
l'application ne peut pas recaler un morceau. Tout fichier cité par un
morceau est donc **écarté** des corrections qui changent sa longueur
(`rate`, `trim`), avec le motif en clair dans `FixPlan.skipped`. Les
corrections qui conservent les trames restent permises.

#### 4.22.3 Correction mesurée — recentrer peut écrêter

Retirer la composante continue d'un fichier déjà chaud le pousse à pleine
échelle : un signal dont les sommets atteignent 0,9999 avec un continu de
+0,062 sature une fois recentré. Trois fichiers de la carte d'essai
basculaient ainsi dans l'écrêtage, le diagnostic passant de 35 à 38 fichiers
écrêtés **après** une correction censée améliorer les choses.
`plan_remove_dc()` accompagne donc le retrait d'une baisse de niveau à
`DC_SAFE_CEILING_DB` dès que `peak + |dc| >= 0,9995` — ce qui met à l'échelle
au lieu de raboter.

#### 4.22.4 Ce que la correction ne fait pas

**L'écrêtage ne se répare pas.** `plan_headroom()` rend de la marge en
abaissant le niveau ; les sommets rabotés à l'enregistrement ne reviennent
pas. Le libellé doit le dire, pour ne pas laisser croire à une restauration.

#### 4.22.5 Sauvegarde

Chaque fichier réécrit laisse son original dans
`_BACKUP/samplefix-<horodatage>/<chemin relatif à la carte>`. Deux points
impératifs :

* le chemin conservé est celui **de la carte**, pas celui du disque : une
  première version stockait `_BACKUP/…/Users/sebas/AppData/…`, et la
  restauration recréait cette arborescence absurde dans la carte au lieu de
  remettre le fichier à sa place ;
* l'horodatage à la seconde ne suffit pas à distinguer deux exécutions
  lancées coup sur coup : un suffixe numérique est ajouté si le dossier
  existe déjà.

`_BACKUP/` est à la racine de la carte, hors de `SAMPLES/`, pour que ni le
Deluge ni `NON_AUDIO_IN_SAMPLES` ne prennent les copies pour des
échantillons.

### 4.23 `delugeapp/core/slicer.py` — découpage d'une boucle en kit

```python
MODES = ("transients", "grid", "manual")
DEFAULT_SLICES = 16
MAX_SLICES = 32
MIN_SLICE_MS = 20.0
MAX_ROW_NAME = 12

@dataclass
class Slice:
    start: int; end: int; label: str          # `end` EXCLUSIF
    @property frames -> int
    def seconds(sr) -> float
    def zone() -> Zone

@dataclass
class SliceSet:
    rel: str; sr: int; frames: int
    slices: list[Slice]; bpm: float; mode: str
    @property duration -> float; @property covered -> int
    def summary() -> str; def to_text() -> str
    def quantize(bpm, division=16) -> SliceSet

def detect_slices(data, sr, sensitivity=1.0, max_slices=16) -> list[int]
def grid_slices(frames, sr, count=16) -> list[int]
def slice_sample(sd, rel, mode="transients", count=16, sensitivity=1.0,
                 bpm=0.0, positions=None, lib=None, quantize=False) -> SliceSet
def slices_to_kit(sliceset, name="") -> Kit
def save_sliced_kit(sd, sliceset, name="", folder="KITS",
                    apply=False) -> tuple[str, str]
def render_slice(sd, sliceset, index) -> np.ndarray
def export_slices(sd, sliceset, folder, apply=False,
                  bit_depth=None) -> tuple[list[str], list[str]]
```

#### 4.23.1 Fait vérifié — le Deluge joue des portions de fichier

Un découpage **ne duplique aucun fichier audio** : les rangées du kit pointent
toutes le même échantillon avec leurs propres `startSamplePos` /
`endSamplePos`. Ce n'est pas une hypothèse, c'est mesuré sur la carte réelle :

* **19 zones** ne jouent qu'une portion de leur fichier. `021 hodeur 1.XML`
  joue les 10 à 55 % de six enregistrements ; `015 Andrew Stirton Frugal.XML`
  démarre `frugalriser.wav` à la trame **113 403** (donc `start > 0`
  fonctionne) ;
* **un kit de la carte référence déjà deux fois le même fichier avec des
  bornes différentes** (`snare smack.wav` dans
  `020 Leonard Ludvigsen Beatbox.XML`), c'est-à-dire un découpage à deux
  tranches.

Les bornes sont **exclusives** : une zone qui couvre tout le fichier porte
`endSamplePos` égal au nombre de trames, pas au dernier indice (`clap1.wav` :
384 → 12259 pour 12259 trames).

Le plus gros kit de la carte compte **19 rangées**. Rien dans le format ne
plafonne ce nombre ; `MAX_SLICES = 32` est un choix d'ergonomie.

#### 4.23.2 `grid` ne s'aligne PAS sur le tempo

Sur une boucle correctement coupée, la division égale **est déjà** la grille
musicale : les 4,0 s de `Bricky-NoKS-120.wav` donnent 16 tranches de 250 ms,
soit la croche à 120 BPM. Ramener ces bornes sur un tempo *détecté* —
120,2 BPM au lieu de 120 — déplaçait les coupes et faisait sortir une tranche
à 256 ms : **l'alignement dégradait un découpage déjà juste.**

L'alignement n'a de sens que pour les coupes issues des attaques, qui tombent
réellement à côté de la grille. Il est donc dans `SliceSet.quantize()`, et là
seulement.

#### 4.23.3 Les tranches trop courtes se filtrent sur les BORNES

Une tranche sous `MIN_SLICE_MS` ne produit qu'un clic. La première version
fusionnait une tranche trop courte dans la précédente — mais la **première**
tranche n'a pas de précédente, et restait à 30 trames. Le filtrage porte donc
sur les bornes : on ne garde une borne que si elle est à `MIN_SLICE_MS` au
moins de la dernière retenue, et une queue trop courte rejoint la tranche
précédente.

#### 4.23.4 Garanties

* les tranches **couvrent tout le fichier**, sans trou ni chevauchement :
  `slices[0].start == 0`, `slices[-1].end == frames`, et
  `slices[i].end == slices[i+1].start` ;
* `save_sliced_kit(..., apply=False)` n'écrit rien et retourne le chemin
  prévu ;
* **un kit existant n'est jamais écrasé** : le nom est numéroté ;
* `export_slices()` existe pour sortir des échantillons autonomes, mais n'est
  pas le mode normal : la somme des trames exportées doit égaler celle du
  fichier d'origine.

### 4.24 `delugeapp/core/similarity.py` — recherche par ressemblance

```python
FEATURES = ("centroid", "rolloff", "flatness", "bandwidth",
            "low_ratio", "high_ratio", "crest", "attack")
LOG_FEATURES = {"centroid", "rolloff", "bandwidth", "crest", "attack"}
WEIGHTS = {...}            # low_ratio et attack pèsent le plus

@dataclass
class Match:
    rel: str; distance: float; row: object
    @property closeness -> int          # 0–100, indicatif

@dataclass
class Space:
    rels: list[str]; vectors: np.ndarray; rows: dict; index: dict
    def has(rel) -> bool

def build_space(lib, rows=None, folder="", category="") -> Space
def similar(lib, rel, limit=20, space=None, same_category=False,
            max_distance=0.0) -> list[Match]
def describe(row) -> str
```

Le schéma de l'index passe en **version 4** : huit colonnes s'ajoutent à
`samples` (`centroid`, `rolloff`, `flatness`, `bandwidth`, `low_ratio`,
`high_ratio`, `crest`, `attack`), remplies par `scan_card(analyze=True)`.
`analysis.attack_time(data, sr)` complète `analysis.spectral()`, qui existait
mais que `scan` n'appelait pas : les descripteurs étaient calculables et
jamais conservés.

#### 4.24.1 Normalisation

Les grandeurs en hertz et en secondes passent au **logarithme** : l'oreille
entend des rapports. Chaque dimension est ensuite divisée par l'écart-type de
la population, puis pondérée. Une dimension d'écart-type nul est neutralisée
plutôt que divisée par zéro. **Une ligne dont un seul descripteur manque est
écartée** : un vecteur incomplet donnerait des voisins faux sans le signaler.

#### 4.24.2 Mesure de qualité

Sur la carte de référence, en comparant la catégorie des 5 plus proches
voisins à celle du départ, sur les 22 catégories d'au moins 12 fichiers :

* **aucune catégorie ne fait moins bien que le hasard** ;
* la **marge disponible gagnée** — `(mesuré − hasard) / (1 − hasard)` — vaut
  0,45 en médiane, jusqu'à 0,99 ;
* facteur brut : médiane **10,8×** le hasard, jusqu'à 24×.

⚠️ **Deux pièges dans cette mesure, tous deux rencontrés.** La moyenne
*pondérée* est trompeuse, parce qu'une bibliothèque pèse 46 % de la carte et
domine numérateur comme dénominateur (elle ramenait le résultat à 2,8×). Et
le *facteur brut* a un plafond arithmétique : une catégorie occupant 46,1 %
ne peut pas dépasser 2,17×, si bien qu'exiger 3× d'elle est impossible même
avec une recherche parfaite. D'où la marge gagnée, bornée à 1.

Les voisins sont musicalement justes et pas toujours du même dossier : un
kick trouve des toms, une caisse claire trouve des rim et des cowbells. Le
score par catégorie **sous-estime** donc la qualité réelle.

#### 4.24.3 Ce que ce module ne fait PAS

**Pas de détection de quasi-doublons.** Le descripteur est aveugle à la
hauteur, et une bibliothèque multi-échantillon est faite de fichiers de même
timbre et de même longueur à des hauteurs différentes. Mesuré : à une
distance de 0,45 le regroupement avale 59 % de la bibliothèque ; serré à 0,12
**avec** une durée à 2 % près, les 15 paires trouvées sont **toutes** deux
notes voisines du même instrument (`Cello B3` avec `Cello C4`).
`Library.duplicates()` répond déjà à la question du doublon, octet pour
octet. Ne pas remplacer une certitude par une ressemblance.

#### 4.24.4 Coût

Construction de l'espace : **0,017 s** pour 1 741 échantillons (8 nombres
chacun). En revanche l'analyse acoustique complète de la carte passe de
**76 s à 203 s**, le temps de mesurer les descripteurs. Elle reste désactivée
par défaut (`scan_analyze`), et une analyse incrémentale saute les fichiers
inchangés.

#### 4.24.5 `needs_rescan` doit être lu

`Library.init_db` posait déjà `needs_rescan` lors d'une mise à niveau du
schéma, mais **rien ne le lisait**. `scan_card` le consulte maintenant :
une analyse incrémentale est forcée en complète quand le drapeau est levé,
sinon les colonnes neuves resteraient vides — les fichiers n'ayant pas
changé, elles seraient sautées. Le drapeau n'est baissé qu'au terme d'une
analyse **complète et acoustique**.

⚠️ `Library.needs_rescan` est une **propriété**, pas une méthode.

### 4.25 `delugeapp/core/songpack.py` — rassembler un morceau

Réunit dans un dossier tout ce dont un morceau a besoin : le morceau, les
presets qu'il nomme, les échantillons que ces presets lisent.

```python
STD_DIRS = ("SONGS", "SYNTHS", "KITS", "SAMPLES")

@dataclass
class SongPack:
    song_rel: str; name: str
    presets: list[str]; samples: list[str]
    missing_presets: list[str]; missing_samples: list[str]
    bytes_total: int
    def files() -> list[str]
    @property complete -> bool
    def summary() -> str; def to_text() -> str

def collect(sd, song_rel) -> SongPack
def write_pack(sd, pack, dest, apply=False, progress=None,
               should_stop=None) -> tuple[list[str], list[str]]
def safe_folder_name(name) -> str
```

Le dossier produit **a la forme d'une carte** : le recopier à la racine d'une
autre suffit à y jouer le morceau.

**Rien n'est déplacé ni modifié sur la carte** : tout est copié, et un test
compare l'empreinte de chaque fichier avant et après. `apply=False` (défaut)
ne crée même pas le dossier.

#### 4.25.1 Un morceau nomme ses presets, il ne les situe pas

Un morceau porte `presetName` et `presetFolder`, pas un chemin. La casse n'est
pas fiable (FAT32) et le dossier annoncé peut omettre la racine — `acid`
plutôt que `SYNTHS/acid`. `_find_preset()` essaie donc, dans l'ordre : le
dossier annoncé tel quel, le même préfixé de `SYNTHS/` ou `KITS/`, puis le
premier preset de ce nom où qu'il soit.

#### 4.25.2 Deux sources d'échantillons

Les échantillons viennent **à la fois** du morceau (il embarque une copie des
définitions d'instruments) **et** des presets qu'il nomme. Les deux sont
nécessaires : un morceau peut citer un échantillon qu'aucun preset de la carte
ne lit.

#### 4.25.3 Mesure

Sur les 46 morceaux de la carte de référence : inventaire complet en
**0,7 s**, soit 15 ms par morceau, et **46 morceaux complets sur 46** — les
125 références cassées de la carte sont dans des presets qu'aucun morceau
n'utilise. Le morceau le plus lourd réunit 22 fichiers pour 1,2 Mio.

### 4.26 `midifile.song_to_midi` — le morceau entier en MIDI

```python
def song_to_midi(path, song, max_clips=64) -> int   # nombre de pistes écrites
```

Une piste MIDI par clip, les clips de kit sur le canal des percussions.
Retourne 0 — et **n'écrit rien** — si aucun clip ne porte de note.

⚠️ **Toutes les pistes démarrent au même point, et c'est une contrainte des
données, pas un raccourci.** Les clips du Deluge vivent dans une grille de
session : ce sont des boucles qu'on déclenche, et le fichier ne porte aucune
position absolue pour elles. Vérifié : **aucun des 46 morceaux de la carte
n'utilise la vue arrangement**, et aucun attribut de position n'apparaît dans
leur XML. Inventer un placement dans le temps serait une fiction.

### 4.27 `delugeapp/core/units.py` — grandeurs mises en forme

```python
BYTE_UNITS = ("o", "Kio", "Mio", "Gio")

def human_size(size: int | float | None) -> str      # « 1,4 Mio », None -> « — »
def human_duration(seconds: int | float | None) -> str   # « 3 min 07 s »
def file_size(path: Path | str) -> int               # 0 si illisible
```

**Une seule implémentation, pour le noyau et pour l'interface.**
`ui/widgets/common.py` réexporte `human_size` et `human_duration` ; les noms
y restent valables, tout l'affichage les appelle déjà.

⚠️ **Il y en a eu trois.** Une dans l'interface, et deux recopiées dans
`core/samplefix.py` et `core/songpack.py` — où elles écrivaient le séparateur
décimal **à l'anglaise**. Les messages de correction d'échantillons et de
rassemblement de morceau annonçaient donc « libérés 9.9 Mio » au milieu d'une
application en français. Ce module n'importe que la bibliothèque standard :
le noyau peut s'en servir sans toucher à Qt.

---

### 4.28 `delugeapp/core/midiport.py` — MIDI temps réel, sans dépendance

```python
def available() -> bool                      # winmm chargé ?
def outputs() -> list[MidiDevice]            # ports de sortie
def inputs() -> list[MidiDevice]
def cable_of(name: str) -> int               # « MIDIOUT3 (Deluge) » -> 3
def deluge_ports(kind="out", devices=None) -> list[MidiDevice]   # par câble
def find(kind="out", cable=None) -> MidiDevice | None            # le Deluge
def error_text(code: int) -> str             # MMSYSERR_* en clair
def short_message(status, data1=0, data2=0) -> int
class MidiDevice: index, name, kind ; is_deluge, cable
class MidiOut:  open/close/send/send_sysex(data, timeout=2.0)/note_on/
                note_off/control_change/program_change/pitch_bend/realtime/
                all_notes_off/play_note ; last_error
class MidiIn(maxsize=4096, sysex=True):  open/close/poll -> list[MidiMessage]
                                          ; dropped ; set_sysex_tap(tap)
@dataclass(frozen=True)
class MidiMessage: status, data1, data2, millis, stamp=0, data=b"",
                   arrived=0.0               # kind, channel, is_sysex
```

**Aucune bibliothèque tierce.** Ni `mido`, ni `python-rtmidi`, ni `pygame` :
aucune n'est installée chez l'utilisateur, et le projet ne dépend que de
`numpy` et PyQt6. Windows expose tout dans `winmm.dll`, appelé par `ctypes`.
Hors Windows, `available()` rend `False` et tout devient silencieux.

Règles non négociables :

* **les octets de données sont bornés à 0..127** avant l'envoi : un message
  illégal bloque le flux de certains appareils ;
* **le rappel d'entrée ne fait qu'empiler** dans une `queue` — il est appelé
  par un fil de Windows, et une exception qui remonterait dans du code C
  tuerait le processus ;
* **l'objet `CFUNCTYPE` est gardé sur l'instance** tant que le port est
  ouvert : s'il est ramassé pendant que Windows le tient, le processus tombe ;
* `all_notes_off` envoie un `note off` pour **chaque note réellement
  allumée**, en plus du CC 123 que certains appareils ignorent ;
* **SysEx en entrée** : six tampons `MIDIHDR` de 4 096 octets, préparés à
  l'ouverture. Le rappel ne fait que recoller les morceaux et noter le
  tampon à rendre : `midiInAddBuffer` est **interdit dans le rappel**
  (documentation WinMM). Un fil de recyclage le rend, et il ne connaît que
  *sa* session : un fil en retard ne peut pas rendre un tampon à un port
  rouvert. Fermeture dans cet ordre : `midiInStop`, `midiInReset` (qui rend
  tous les tampons), fin du fil, `midiInUnprepareHeader` de chacun,
  `midiInClose`. Les rappels d'une session close, et un tampon que Windows
  refuse de rendre, sont **gardés** (`_RAPPELS_GARDES`, `_TAMPONS_GARDES`) :
  un rappel tardif sur une mémoire libérée tue le processus ;
* **SysEx en sortie** : `midiOutLongMsg`, puis attente de `MHDR_DONE` (deux
  secondes au plus) avant `midiOutUnprepareHeader` ; `MIDIERR_STILLPLAYING`
  (65) veut dire « attendre », pas « échouer » ;
* **`arrived`** est l'instant de réception (`perf_counter`), posé par le
  rappel : un aller-retour se mesure avec lui, pas au moment où la file est
  vidée ;
* **fermer un port qui n'a rien joué n'envoie rien.** `close()` n'éteint —
  seize CC 123, puis `midiOutReset`, qui peut émettre un relâchement par note
  et un CC 64 par canal — que si le port a porté un message de canal pendant
  la session. Avant, chaque fermeture le faisait, port des SysEx compris :
  du bruit pour une machine à qui l'on n'avait rien joué. Mesuré ensuite,
  l'application entière face au Deluge : connexion, écran recopié, fermeture
  — **0 message court, 7 SysEx de lecture**.

> **Mesuré sur le Deluge branché** (15 octobre 2026, firmware c1.2.1,
> Windows 11). Trois câbles dans chaque sens : `Deluge`,
> `MIDIOUT2 (Deluge)`, `MIDIOUT3 (Deluge)` en sortie ; `Deluge`,
> `MIDIIN2 (Deluge)`, `MIDIIN3 (Deluge)` en entrée. Identité reçue en
> 2,8 ms ; aller-retour d'un ping **0,3 ms**, compté à l'arrivée ; image de
> l'écran en 110 octets compressée, 888 brute, les deux décodages
> identiques ; aucune perte ; ports refermés, **aucun tampon gardé**.

### 4.29 `delugeapp/core/midifollow.py` — la carte des contrôleurs

```python
DEFAULT_CC: dict[str, int]            # noms du firmware -> CC (mesurés)
FOLLOW_TO_PARAM: dict[str, str]       # noms du firmware -> clés du modèle
SANS_EQUIVALENT: frozenset[str]
HALF_RANGE = {"oscAPulseWidth", "oscBPulseWidth"}
PARAM_LABELS: dict[str, str]          # clé -> libellé (les 52), traduit par label_of
def load_map(card=None, path=None) -> dict[str, int]   # clé app -> CC
def load_map_with_source(card=None, path=None) -> tuple[dict[str, int], str]
                                      # "" : valeurs d'usine du firmware
FOLLOW_PLACES = ("SETTINGS/MIDIFollow.XML", "MIDIFollow.XML")   # 1.3, puis avant
@dataclass(frozen=True)
class FollowSettings: channel_a, channel_b, channel_c, kit_root_note, feedback
def read_settings(card=None, path=None) -> FollowSettings | None
def reverse_map(mapping) -> dict[int, str]             # CC -> clé
def cc_value(raw: int, key: str = "") -> int           # 32 bits -> 0..127
def raw_from_cc(value: int, key: str = "") -> int      # 0..127 -> 32 bits
def label_of(key: str) -> str
def sound_messages(sound, mapping=None, keys=None) -> list[tuple[int, int]]
```

**La conversion est celle du firmware, à l'unité près** (`release_1_2_1`) :
une valeur reçue devient la position de bouton `cc − 64`, et 127 vaut le
maximum (`INT32_MAX`) ; dans l'autre sens, `((v + 2^24) >> 25) + 64`, et
tout ce qui dépasse `0x7F000000` vaut 127. Les largeurs d'impulsion
(`HALF_RANGE`) n'occupent que la moitié positive : `v >> 24`.

**Sur une machine neuve, MIDI Follow est éteint** — canaux A, B et C non
réglés (`resetMidiFollowSettings`) — **et son retour aussi**. Rien ne revient
tant que l'utilisateur n'a pas réglé MIDI ▸ Follow ▸ Channel A, puis
Feedback. Retour actif, la machine envoie chaque paramètre appris au
changement d'instrument, puis à chaque bouton tourné. Un kit répond à partir
de la note 36 (Follow ▸ Kit Root Note). L'interface dit d'où vient la table
(`load_map_with_source`) : sans `MIDIFollow.XML` lu, ce sont les valeurs
d'usine, et l'annoncer « lue sur la carte » serait faux.

> **Mesuré en firmware 1.3** (18 octobre 2026). Le fichier a déménagé dans
> `SETTINGS/MIDIFollow.XML`, ses assignations s'appellent `<cc_mappings>`
> (`<defaultCCMappings>` en 1.2.1) — faute de le reconnaître, canaux et
> note de base passaient pour des contrôleurs —, elles sont **79** (les 52
> d'avant, inchangées, plus enveloppes 3 et 4, LFO 3 et 4, probabilités
> d'arpège…), et le fichier porte enfin **les réglages de la machine** :
> `<settings><channels><a><channel>` vaut le canal **+ 1** (256 = aucun),
> `<kit_root_note><note>`, `<feedback><channel>a</channel>`. Chez
> l'utilisateur : Channel A = 1, retour sur A, note 36. `read_settings` les
> lit ; « Deluge en direct » les constate au lieu de les réclamer, et
> signale un canal différent de celui de l'application.

**Mesuré sur la carte de l'utilisateur** (firmware communautaire c1.2.1,
`MIDIFollow.XML`, 56 entrées) :

| | |
|---|---|
| noms déjà identiques à ceux du modèle | **31** (`lpfFrequency`, `pan`, `reverbAmount`…) |
| noms à traduire | **21** (`volumePostFX`→`volume`, `oscAPitch`→`oscAPitchAdjust`, les 8 segments d'enveloppe…) |
| sans équivalent dans le modèle | **3** (`modulator1Pitch`, `modulator2Pitch`, `volumePostReverbSend`) |
| sans contrôleur assigné | **1** (`stutterRate` = 255, hors de 0..127) |
| **pilotables** | **52** |

Une valeur hors de 0..127 veut dire « non assigné » et doit être écartée.
Un paramètre **absent du son n'est pas envoyé** : écrire une valeur par
défaut écraserait sur la machine un réglage que l'application ne connaît pas.

### 4.30 `delugeapp/core/delugelink.py` — jouer sur la machine

```python
SYSEX_CABLE = 3; CLOCK_TIMEOUT = 1.0; CLOCK_WINDOW = 24; SCREEN_REFRESH = 1.0
IDENTITY_RETRY = 2.0; IDENTITY_TRIES = 3
def tempo_from_ticks(stamps) -> float | None   # horodatages du pilote, en ms
def latency_text(ms) -> str                    # « 0,3 ms », « 41 ms »

class DelugeLink:
    connect(out_name="", in_name="", card=None) -> bool   # câbles 1 et 3
    disconnect() / close()
    state() -> LinkState                 # ports, noms, résumé dans la langue de l'interface
    service() -> set[str]                # identity, ping, screen, tempo,
                                         # transport, params, notes
    identify() / ping() / hello() / set_screen(on) -> bool   # SysEx
    identity, latency_ms, screen, segments, tempo, running, machine, held,
    follow_source                        # ce que la machine a dit
    files: DelugeFiles | None            # la carte par USB (§4.33), créé à la
    wait_files(timeout) -> bool | None   # connexion, sondé en arrière-plan
    machine_values() -> dict[str, int]   # comme son écran : 0..50, ±25
    send_sound(sound, keys=None) -> int  # nombre de contrôleurs envoyés
    send_param(key, raw) -> bool         # un bouton qui tourne
    play_notes(notes, velocity, seconds, gap, sound) -> bool   # sans bloquer
    play_pattern(pattern, bpm, row_notes, repeats, clock, channel) -> bool
    stop_playing() / panic() / poll_input()

@dataclass
class LinkState: supported, out_name, in_name, deluge_out, deluge_in,
                 ports_out, ports_in, follow_count, follow_source, sysex_name,
                 firmware, latency_ms, tempo, running, clock_alive, screen_on,
                 screen_frames, feedback, error, files
                                          # connected, verified, summary()
```

**Les notes par le premier câble, les SysEx par le troisième.** Le firmware
ne fait rien d'autre du troisième, et chaque réponse repart par le câble de
la demande (`MIDIDeviceUSB::sendSysex`) : la recopie de l'écran n'encombre
donc pas les notes. Sans troisième câble, les SysEx passent par le premier.
`connect` n'envoie que deux SysEx de lecture — identité, ping —, jamais une
note ni un contrôleur.

**Le service.** Ce qui arrive s'accumule dans des files ; `service()` les
vide, met l'état à jour, renouvelle l'abonnement à l'écran avant ses deux
secondes et redemande l'identité (trois fois au plus) tant que la machine se
tait. La fenêtre principale l'appelle toutes les 40 ms et réagit aux
évènements rendus. Le tempo se lit sur les horodatages **du pilote**, sur une
noire d'impulsions ; une horloge muette depuis une seconde vaut « arrêté ».

> **Mesuré sur la machine** (15 octobre 2026). Connexion en 82 ms, identité
> présente dès le premier service, pings de 0,31 à 0,39 ms. L'abonnement
> forcé (mode 3) ne répond **pas par une image** mais par une différence qui
> couvre tout l'écran (début 0, 96 blocs) : `OledScreen.complete` la compte
> comme une image. Écran immobile : rien n'est envoyé (un seul message en
> six secondes). « Faire signe » : une différence 3 ms plus tard (blocs 19
> à 76), une autre à 801 ms quand le message s'efface, et l'écran revient à
> l'identique. Machine à l'arrêt : ni horloge ni rien d'autre sur le premier
> câble.

**Le Deluge joue l'instrument sélectionné sur lui.** Aucun message MIDI
standard ne permet de lui dire « charge ce preset » : c'est une limite de la
machine, et l'interface le dit au lieu de laisser croire à un pilotage
complet.

**Un motif n'est pas une suite de 0 et de 1.** `pattern.tracks[nom]` est une
liste éparse de `Step(pos, velocity, length, probability)` ; la grille se lit
dans `pattern.steps`, `pattern.ppq` et `pattern.ticks_per_step`. Mesuré :
16 pas, 24 ppq, 6 ticks par pas, soit une double-croche par pas et deux
secondes la mesure à 120 BPM. Le séquenceur vise des instants **absolus**
depuis le départ, sinon l'erreur s'accumule : mesuré à ±11 ms sur 4 secondes.

### 4.31 `delugeapp/core/songwriter.py` — écrire un morceau du Deluge

Fait d'une création de l'application un fichier `SONGS/*.XML` neuf, au format qu'écrit
la machine (c1.2.1, `Song::writeToFile`), relevé sur `DEFAULT.XML` et les cinq autres
morceaux c1.2.1 de la carte.

```python
FIRMWARE = "c1.2.1"; MAGNITUDE = 2; BAR = 384; STEP = 24; MAX_SECTIONS = 12

@dataclass
class Track:      kind: str; name: str; folder: str; body: Element; params: Element
                  arp: dict; drum_params: list[Element]; samples: list[str]
                  unconverted: list[str]
@dataclass
class ClipSpec:   track: int; length: int; rows: dict[int, list[Note]]
                  section: int = 0; name: str = ""; playing: bool = True
@dataclass
class SectionSpec: name: str; length: int
@dataclass
class SongSpec:   name: str; bpm: float; root: int; mode_notes: tuple
                  tracks: list[Track]; clips: list[ClipSpec]
                  sections: list[SectionSpec] = []; summary: list[str] = []

synth_track(source, name="", folder="SYNTHS", version=None, sd=None, arp=None) -> Track
kit_track(source, name="", folder="KITS", version=None, sd=None) -> Track
upgrade_sound(sound, version, sd=None) -> list[str]     # conversions d'époque
upgrade_kit(kit, version, sd=None) -> list[str]
events_to_rows(events, length, offset=0.0) -> dict[int, list[Note]]
pattern_rows(pattern, row_map, length=None, start=0.0, end=None) -> (rows, length)
fold(rows, length) -> (rows, length)                    # plus courte boucle exacte
tempo_attrs(bpm, magnitude=2) -> (timePerTimerTick, timerTickFraction)
build(spec) -> DelugeDoc
write_song(sd, spec, apply=False) -> SongWrite          # simule par défaut
free_song_name(sd, name) -> str                         # jamais un nom pris, ni DEFAULT

# Recettes, une par outil
progression_song(parts, *, name, bpm, genre, root, scale, sounds=None,
                 drums=None, kit=None, row_map=None) -> SongSpec
pattern_song(pattern, kit, row_map, *, name, bpm, version=None, kit_name="",
             folder="KITS") -> SongSpec
sketch_song(result, *, name, bpm, genre, root, scale, sounds=None, kit=None,
            row_map=None) -> SongSpec
preset_song(preset, *, name, bpm, genre, role, seed=1, root=57, scale="mineur",
            drums=None, kit=None, row_map=None) -> SongSpec
slices_song(sliceset, *, name, bpm=None) -> SongSpec
part_presets(parts, genre, seed=7) -> dict        # les sons de l'écoute, arpège éteint
drum_kit_for(sd, lib, genre, tracks, base=None, seed=1) -> (Kit|None, {piste: rangée}, perdues)
drum_rows(tracks, kit) -> dict[str, int]          # même nom, sinon même rôle
```

**Ce qui va où.** Un instrument est **intégré** : le `<sound>` ou le `<kit>` du preset
sans ses paramètres. Ses `<defaultParams>` deviennent le `<soundParams>` de **chaque**
clip (synthé), le `<kitParams>` (kit) et un `<soundParams>` par rangée de kit
(`<noteRow drumIndex=…>`, une rangée par son, dans l'ordre des sons). L'arpégiateur d'un
synthé passe dans le clip, son `syncLevel` en **valeur interne** (fichier + 1 −
magnitude : 7 devient 6 — `DEFAULT.XML`) ; celui d'une rangée de kit reste dans le son.
Attributs propres au morceau devant l'instrument : `presetName`, `presetFolder`,
`defaultVelocity="64"`, `isArmedForRecording`, `activeModFunction`, `clipInstances`,
`colour`. Un clip retrouve son instrument par type, nom et dossier **sans la casse**
(`getInstrumentFromPresetSlot`) : les noms sont rendus uniques.

**Sections.** Une section passe à la suivante après `numRepeats` boucles de son **plus
long clip** (`armNextSection`, quantification sur le plus long clip actif) ; 0 = sans fin.
En disposition « rangées » (`sessionLayout="0"`, celle des six morceaux c1.2.1), la
suivante est la section du clip **d'en dessous** : les clips de la première section ont
les index les plus élevés. La dernière section arrête la lecture. L'enchaînement ne part
qu'après le **lancement** d'une section pendant la lecture : PLAY joue la première en
boucle, lancer la deuxième déroule la suite. L'arrangement (`clipInstances` : position,
longueur, index de session ; bit 31 pour un clip réservé à l'arrangement) place les mêmes
clips ; une instance plus longue que son clip le fait boucler.

**Un preset ancien ne s'intègre pas tel quel.** Le morceau entier est lu avec la version
de `<song>` ; **un `firmwareVersion` laissé dans un `<sound>` ou un `<kit>` change la
version de lecture de tout ce qui suit** (`tryReadingFirmwareTagFromFile` est appelé par
les lecteurs de son et de kit). Les déclarations de version sont retirées à toute
profondeur, et les conversions que fait la machine en chargeant un preset ancien sont
appliquées :

| avant | conversion |
|---|---|
| c1.2.0 | ancien `mode` d'arpège éclaté en `arpMode`/`noteMode`/`octaveMode` (`off`, `up`, `down`, `both` → arp/up/alt, `random`) ; son FM : `lpfMode`/`hpfMode` éteints |
| 4.0.0-beta | câbles d'expression si aucun câble ne part d'aftertouch, x ou y : aftertouch → volume `0x2A3D7094`, y → lpfFrequency `0x19999990` (FM : y → modulator1Volume `0x1333332C`), rangés après les câbles de même destination |
| 2.1.0-beta | bornes `start/endMilliseconds` → trames (`ms × fréquence / 1000`, entier ; une fin qui dépasse la longueur d'au plus 45 trames vaut la longueur ; inversé : bornes retournées) |
| 1.2.0 | compensation de résonance (`oldResonanceCompensation`, `shiftVolumeByDB` avec son défaut) puis résonance à mi-course ramenée à 0 si le filtre est ouvert ; au niveau du kit, la règle du passe-haut teste la résonance du **passe-bas** (comme le firmware) |

Polyphonie numérique (`0`, `2`) réécrite en clair ; `<compressor>` renommé
`<sidechain>` (les deux sont lus) ; `maxVoices="0"` — que les premiers presets générés
écrivaient pour les sons non polyphoniques — remis à 8, la valeur que la machine écrit pour
**tous** ses sons (94 sur 94 dans les morceaux de la carte, legato et auto compris) et
qu'elle lirait comme un plafond de zéro voix (`AudioEngine::solicitVoice`).

**Mesure.** Chaque instrument des six morceaux c1.2.1 a été reconstruit depuis son preset
d'origine et comparé à ce que la machine a écrit : TB01 (3.1.5) dans `DEFAULT.XML`
ressort **à l'identique** ; le TR-808 sans version de `SONG1.XML` aussi pour ce qui
dépend des conversions — bornes à la trame près, résonances, câbles. Les écarts restants
sont des retouches de l'utilisateur (valeurs de potentiomètre, multiples de 2^25 ;
automatisations ; types d'oscillateur changés).

**Notes.** Positions et durées en ticks du morceau (24 par double-croche) ; vélocités en
pourcentage ramenées à 1–127 comme `Pattern.to_notes` ; notes triées, coupées au bout
du clip, chevauchements raccourcis. `fold` replie une partie sur sa plus courte boucle
exacte (période qui divise la longueur, aucune note à cheval) : les accords d'une
progression de quatre mesures sur une section de seize tiennent dans un clip de quatre.
Une crash à l'entrée d'une section au sommet empêche ce repli : la batterie de cette
section garde sa longueur entière (32 mesures pour un thème techno), plutôt qu'une
boucle d'une mesure qui frapperait la crash à chaque tour.
Un clip de synthé n'est « dans la gamme » (`inKeyMode="1"`) que si toutes ses notes y
sont ; un clip de kit l'est toujours, comme les écrit la machine.

**Non-destruction.** `write_song` simule sans `apply` et rend le plan (fichier, tempo,
instruments, clips, sections, échantillons absents, bornes non converties). Le fichier
est toujours **nouveau** : nom assaini, numéroté s'il est pris (`Essai 2`), jamais
`DEFAULT` (le morceau de départ de la machine) ; un fichier apparu entre la simulation et
l'écriture n'est pas remplacé.

**Non vérifié sur la machine.** Tout ce qui précède vient du code du firmware et des
fichiers de la carte ; aucun morceau écrit ici n'a encore été chargé sur le Deluge.

### 4.32 `delugeapp/core/delugesysex.py` — ce que le firmware dit en SysEx

Lu dans le code de la machine (`release_1_2_1` : `io/midi/midi_engine.cpp`,
`hid/hid_sysex.cpp`, `util/pack.c`), puis vérifié sur elle.

```python
DELUGE_ID = b"\x00\x21\x7b\x01"
CMD_PING = 0x00; CMD_POPUP = 0x01; CMD_HID = 0x02; CMD_DEBUG = 0x03; CMD_PONG = 0x7F
OLED_WIDTH = 128; OLED_HEIGHT = 48; OLED_BYTES = 768
DISPLAY_FULL = 0; DISPLAY_FULL_RLE = 1; DISPLAY_STREAM = 2; DISPLAY_STREAM_FORCE = 3
STREAM_SECONDS = 2.0
def identity_request() -> bytes            # F0 7E 7F 06 01 F7
def ping(token=0) -> bytes                 # le pong rend le même octet
def popup() -> bytes                       # « HELLO SYSEX », un instant
def display_request(mode=DISPLAY_STREAM_FORCE) -> bytes   # mode 4 : ValueError
def seven_segment_request() -> bytes
def parse(message) -> Identity | Pong | OledFrame | OledDelta | SevenSegment
                      | DebugText | None
class OledScreen: pixels, frames, complete ; apply(event), clear(),
                  pixel(x, y), lit_count(), text()
pack_8bit_to_7bit / unpack_7bit_to_8bit / pack_8to7_rle / unpack_7to8_rle
```

* **Lecture seule.** Le mode 4 (`swapDisplayType`) change le type d'écran de
  la machine : `display_request(4)` lève, il ne part jamais.
* **L'écran** : 128 × 48, six pages de huit lignes, 128 octets par page, bit
  0 = pixel du haut. Une différence porte un début et une longueur en blocs
  de huit octets.
* **Le firmware c1.2.1 n'ouvre pas ses fichiers en USB** : pas de transfert
  par SysEx, la carte reste le seul chemin pour les fichiers.
* Les tests gardent **des octets venus de la machine** — l'image « SYNTH /
  TB01 » (110 octets) et la réponse d'identité : un portage fautif et des
  vecteurs qu'il aurait produits seraient d'accord entre eux. Notre codeur
  redonne exactement les 110 octets émis.

### 4.33 `delugeapp/core/delugefiles.py` — la carte, par le câble USB

Le firmware **1.3** ouvre sa carte au PC par SysEx
(`storage/smsysex.cpp`) ; la 1.2.1 non. Lu dans le code, puis mesuré sur la
machine de l'utilisateur, mise à jour pour l'occasion.

```python
BLOCK = 1024; MAX_INCOMING = 1024; DIR_LINES = 25; MAX_PATH = 256; TIMEOUT = 5.0
READ_RATE = 155 Kio/s; WRITE_RATE = 45 Kio/s; READ_AHEAD = 2   # mesurés, cf. plus bas
STOPPED = -2; NOT_CONNECTED = -3          # codes du client, à côté des FRESULT
def fat_stamp(epoch) -> (date, heure)     # FAT, heure locale, 2 s
def from_fat(date, heure) -> float
def result_text(code) -> str              # FRESULT, dans la langue de l'interface
def cable_time(read_bytes=0, write_bytes=0) -> str   # « environ 7 min »
@dataclass(frozen=True)
class CardEntry: name, size, date, time, attr ; is_dir, stamp, mtime, addressable
class FileError(OSError): code, path
class DelugeFiles(send, timeout=5.0):
    feed(data, arrived) -> bool           # branché sur MidiIn.set_sysex_tap
    probe(timeout=1.5) -> bool            # ping JSON ; la 1.2.1 se tait
    open_session(tag) -> int              # numéros de message réservés
    listdir(chemin) / exists(chemin) / walk(chemin, skip, progress)
    read(chemin, progress) -> bytes       # deux demandes en vol
    write_new(chemin, data, mtime, progress)  # jamais sur un nom pris
    replace(chemin, data, mtime, progress)    # sans fenêtre de perte
    mkdir / rename / delete / touch
    stop_check: Callable[[], bool] | None # consulté entre deux blocs -> STOPPED
```

**Deux lectures d'avance, pas plus.** La machine met chaque SysEx de fichiers reçu en
file (`smSysex::sysexReceived`, `deluge::deque`) et les traite un à un toutes les
0,2 ms (`handleNextSysEx`, tâche répétée) : envoyer la demande suivante sans attendre la
réponse est prévu. Mais elle **jette en silence** ce qui dépasse 1 024 paquets USB en
attente d'envoi (`ConnectedUSBMIDIDevice::bufferMessage`, `MIDI_SEND_BUFFER_LEN_RING`), et
une réponse de lecture de 1 024 octets en occupe environ 410 : deux tiennent, trois
pourraient se perdre. Mesuré sur la machine, lecture seule : 126 à 129 Ko/s une demande
à la fois, **154 à 160 Ko/s** avec deux, contenus identiques, aucune perte.

**L'écriture, elle, reste une demande à la fois** — 45 Ko/s. Mesuré sans rien écrire (un
ping que le firmware ne lit pas au-delà de son nom) : un SysEx de 1 000 octets met
11 ms du PC à la machine ; un bloc d'écriture de 848 octets en prend 18 en tout. Les
7 ms restantes (travail de la carte, réponse) se chevaucheraient avec l'envoi suivant —
gain possible, mais qui ne se vérifie qu'en écrivant : à mesurer avec l'accord de
l'utilisateur, dans un dossier neuf.

**S'arrêter entre deux blocs.** `stop_check` est consulté avant chaque bloc lu ou écrit
et à chaque dossier parcouru : un fichier de 8 Mo met trois minutes à monter, et l'on
ne joue pas sur le Deluge pendant qu'on écrit sur sa carte. Une écriture interrompue
retire son temporaire de la carte ; l'original n'a pas bougé. Plus de port (câble
débranché) : `NOT_CONNECTED`, aussitôt, sans attendre cinq secondes de délai.

Protocole : requête `F0 00 21 7B 01 04 <msgId> <JSON> [00 <7 bits>] F7`,
réponse en `05` (en `04`, numéro 0, pour `session`). Le JSON de la machine
n'échappe rien.

**Ce que le code de la machine impose — et que ce module s'interdit :**

* `open` en écriture **écrase** (`FA_CREATE_ALWAYS`) : on n'ouvre en
  écriture qu'un nom temporaire neuf (`~DCxxxx.TMP`), puis `rename`, que la
  machine refuse sur un nom pris (`FR_EXIST`) ;
* `move` et `copy` **écrasent** la destination quand le renommage échoue :
  jamais envoyés (un test le vérifie face au simulateur, qui les imite) ;
* un SysEx **reçu** de plus de **1 024 octets** est abandonné sans réponse
  (`incomingSysexBuffer[1024]`) : un bloc d'écriture de 1 024 octets codés
  en faisait 1 230, et restait sans réponse. Les blocs écrits sont taillés
  pour tenir (848 octets) ;
* le bit 7 des noms se perd en route (le « è » de « dièse », 0x8A, arrive
  en 0x0A) : lecture tolérante, nom abîmé mis à part (`unreachable`) ; un
  nom non ASCII n'est jamais envoyé ;
* **la machine n'a pas d'horloge** : ce qu'elle enregistre porte la date
  nulle.

> **Mesuré sur la machine** (firmware 1.3.0, 18 octobre 2026). Ping 1 ms ;
> une page de dossier 5 à 17 ms ; toute la carte (4 318 fichiers, 182
> dossiers) parcourue en 3,6 s ; lecture 113 à 128 Ko/s, écriture 45 Ko/s ;
> contenus relus identiques octet pour octet. Essai d'écriture accordé par
> l'utilisateur, dans un dossier neuf retiré ensuite : fichier neuf,
> relecture, refus d'écrire sur un nom pris (l'original intact),
> remplacement sans temporaire laissé, datation — tout vérifié.

### 4.34 `delugeapp/core/cardsync.py` — la copie de travail

```python
META_DIR = ".deluge-companion"; MANIFEST = META_DIR + "/synchro.json"
EXCHANGES = META_DIR + "/echanges.json"; BACKUP_STATE = META_DIR + "/sauvegarde.json"
MAX_EXCHANGES = 200; MAX_NAMED = 300
def is_junk(rel) -> bool              # corbeilles, Spotlight, ._*, temporaires
                                      # (~DC*, .dc-tmp, .tmp~, *.xxxxxxxx.tmp),
                                      # .bak et _BACKUP/ : restent sur le PC
def scan_local(work) -> dict[str, LocalFile]
def load_manifest(work) / save_manifest(work, records)
class UsbCard(files, should_stop=None) / FolderCard(root)   # par USB, ou un dossier
def plan_sync(card, local, manifest, backup=None) -> SyncPlan
def apply_plan(plan, transport, work, manifest, *, allow_card_deletes=False,
               progress=None, should_stop=None) -> SyncResult
SyncResult: done, errors, renamed, stopped, items[(nature, chemin)], lost
def pending_changes(work) -> [(chemin, taille)]       # ce qui attend le Deluge
@dataclass class Exchange: when, reason, seconds, received, sent, conflicts,
                           removed, deleted, errors, counts, stopped ; summary()
def exchange_of(result, reason, seconds) -> Exchange
def record_exchange(work, exchange) -> bool           # rien si l'échange est vide
def load_exchanges(work, limit=None) -> [Exchange]    # le plus récent d'abord
def recent_arrivals(work, limit=12, since=0) -> [(instant, chemin)]
def update_backup(work, backup, apply=False, progress, should_stop) -> BackupUpdate
def backup_state(work, backup=None) -> {"updated", "same"}
SyncPlan.actions: Action(kind, rel, size, date, time, on_card, source)
    kind ∈ adopt | copy_backup | pull | push | conflict | delete_local | delete_card
```

Synchronisation **à trois voies** — la carte, la copie, le manifeste de la
dernière fois :

* changé sur la carte seulement -> **reçu** ; dans la copie seulement ->
  **envoyé** (`write_new` si la carte ne l'a pas, `replace` sinon) ;
* changé des deux côtés -> **conflit** : la version du Deluge garde le nom,
  celle du PC devient « … (PC) » des deux côtés ; rien n'est écrasé ;
* supprimé sur le Deluge -> retiré de la copie, **dans son historique**
  (`.deluge-companion/historique/<date>/`) ;
* supprimé sur le PC -> **proposé** (`needs_consent`), jamais fait sans
  `allow_card_deletes` ;
* disparu des deux côtés -> oublié du manifeste.

**La première fois**, la copie se bâtit face à la carte depuis la
sauvegarde : même chemin, même taille, date décalée d'un fuseau constant ->
copié localement (`copy_backup`). Mesuré : 4 295 fichiers sur 4 318 à
exactement −7 200 s (une copie faite sur un Mac) ; la sauvegarde comptait
en plus 4,2 Go de corbeilles et d'index de macOS. Copie de travail créée
face au vrai Deluge, en isolement et sans rien écrire sur la carte :
2 734 fichiers repris, 23 reçus par USB, **52 s** ; 2 757 fichiers à la
bonne taille, 15 tirés au hasard relus identiques ; sauvegarde inchangée.

**Ce que la sauvegarde a seule** (`SyncPlan.backup_only`, `backup_music()`)
n'est jamais repris d'office — un fichier supprimé exprès sur le Deluge
reviendrait —, mais **proposé** à la création de la copie de travail, pour
la musique seulement (morceaux, presets, kits, échantillons) ;
`take_from_backup` le recopie dans la copie, d'où la synchronisation
l'envoie. Mesuré chez l'utilisateur : `KITS/COMPAGNON 1.XML`, créé par
l'application **dans la sauvegarde** le 15 octobre, jamais arrivé sur la
carte ; les quatre autres (ancien firmware, réglages déplacés par la 1.3,
`README.txt`) restent dans la sauvegarde.

**Reconnaître ce que le Deluge réécrit** : il date tout à zéro ; après
chaque réception d'un fichier à date nulle, l'application le **date** sur
la carte (métadonnée seule). Une réécriture par la machine le remet à zéro :
le changement se voit sans relire le contenu.

**La sauvegarde** ne change que par `update_backup(..., apply=True)` :
ajouts, remplacements (l'ancienne version gardée dans
`<sauvegarde>/.deluge-companion/remplaces/<date>/`), **aucune
suppression** — ce que la carte n'a plus reste dans la sauvegarde.

**Ne relire que ce qui a bougé.** Le plan comparait le contenu de chaque fichier commun :
1,4 Go lus à chaque fois, **11,3 s à froid et 3,4 s ensuite** chez l'utilisateur — dans
le fil de l'interface. Un fichier vérifié identique est désormais retenu dans
`BACKUP_STATE` (taille et date des deux côtés) et n'est relu que si l'un d'eux bouge ;
la mémoire ne vaut que pour la sauvegarde qu'elle nomme. `updated` garde la date de la
dernière mise à jour faite par l'application.

**Ce qui attend, ce qui a voyagé.** `pending_changes` compte, sans le câble, ce que la
prochaine synchronisation enverrait (0,11 s sur les 2 758 fichiers). Chaque
synchronisation qui a fait quelque chose est gardée (`record_exchange`) : ce qui est
reçu, envoyé, changé des deux côtés, retiré, supprimé avec accord, les erreurs, la
durée — les noms jusqu'à `MAX_NAMED` par échange, les nombres toujours. Une
synchronisation qui n'a rien fait (celle du retour dans la fenêtre, le plus souvent)
n'est pas gardée. `recent_arrivals` en tire la musique reçue du Deluge encore présente.

**S'arrêter proprement.** `apply_plan` s'arrête sur `STOPPED` (demandé : la machine
joue, la fenêtre se ferme) sans compter d'erreur, et sur `NOT_CONNECTED` ou deux délais
dépassés de suite (`lost`) au lieu d'attendre cinq secondes par fichier restant. Ce qui
est fait reste au manifeste. Un conflit écrit d'abord la version du PC sur la carte, puis
la copie locale : un arrêt entre les deux ne laisse rien de local à moitié fait.

> **Mesuré** (18 octobre 2026) : le manifeste de l'utilisateur dit que les dix presets
> `rephazer` réparés dans la copie de travail sont partis sur la carte à 14 h 53 ; son
> journal n'en disait rien. Les échanges s'y écrivent désormais (`ui/cardwork.py`).

### 4.35 `delugeapp/core/cardimport.py` — envoyer au Deluge

Depuis que la carte reste dans la machine, l'Explorateur ne l'atteint plus : ce module
pose sur la carte de l'application — la copie de travail, d'où la synchronisation
l'envoie, ou une carte dans un lecteur — les sons, presets, kits, morceaux et packs du PC.

```python
CARD_DIRS = ("SAMPLES", "SYNTHS", "KITS", "SONGS")
def card_name(nom) -> str                 # ASCII, sans interdit FAT32, jamais tronqué
def card_path(rel) -> str
def scan_sources(chemins, progress=None, should_stop=None) -> ImportScan
ImportScan: found [Found(path, size, kind, pack_rel, loose_rel, problem, fixable, refs)],
            ignored [(chemin, raison)], junk, stopped ; has_loose_samples
def card_files(racine) -> {clé : (chemin, taille)}
def sample_folders(racine, depth=2) -> [str]           # SAMPLES, SAMPLES/DRUMS…
def plan_import(scan, card_root, dest="SAMPLES", existing=None) -> ImportPlan
ImportPlan: items [ImportItem(source, rel, kind, size, action, reason, original)],
            ignored, junk, dest, missing {xml : [réfs]}, retarget {xml : {ancienne : nouvelle}}
    action ∈ copy | convert | same | kept | refused ; to_copy, bytes_to_copy(),
    cable_time(), summary(), to_text(), counts(), empty
def apply_import(plan, sd, progress=None, should_stop=None) -> ImportResult
ImportResult: written, converted, errors, stopped ; summary()
```

**Où va chaque fichier.**

* un dossier déposé qui **a la forme d'une carte** — un enfant `SAMPLES`, `SYNTHS`,
  `KITS` ou `SONGS`, cherché jusqu'à deux niveaux (« TJ SYNTHS/SYNTHS ») — garde ses
  chemins : ses presets les citent ;
* le reste est **en vrac** : les sons vont sous le dossier de destination (`SAMPLES` par
  défaut, celui choisi dans l'arbre de la page Échantillons, ou celui du dialogue), en
  gardant le nom du dossier déposé ; un preset (`<sound>`) va dans `SYNTHS`, un kit
  (`<kit>`) dans `KITS`, un morceau (`<song>`) dans `SONGS` ;
* un XML d'une autre racine (réglages de la machine), un MP3, un fichier MIDI, la
  documentation, un firmware : **restent sur le PC**, avec leur raison ;
* `._*`, `.DS_Store`, `__MACOSX`, les `.reapeaks` et `.asd` : écartés sans un mot.

**Rien d'existant n'est remplacé.** Un fichier identique, octet pour octet, est « déjà
sur la carte » ; un homonyme différent fait numéroter le nouveau (« Kick 2.wav ») — sauf
dans un pack, où la carte garde le sien (« laissé tel quel »), le dire valant mieux
que casser les chemins des presets. La copie ouvre un fichier **neuf** en exclusif : un
fichier apparu entre le plan et la copie n'est pas écrasé. La sauvegarde, en lecture
seule, refuse (`PermissionError`).

**Les noms passent par le câble.** Le bit 7 s'y perd (mesuré) : `card_name` translittère
(« Été » -> « Ete »), remplace les interdits de FAT32 par « _ », retire point et espace
finaux, évite les noms réservés de Windows, et ne tronque rien — sauf un chemin au-delà
de 240 signes. Dans un pack, **les presets suivent** : leurs références aux fichiers
renommés sont réécrites dans la copie (`retarget`).

**Ce que la machine refuserait** (§1.8) n'est pas copié tel quel : converti par
`wav.convert` dans un dossier temporaire hors de la carte, revérifié, puis copié ;
refusé avec sa raison quand ce n'est pas réparable. Un preset dont un échantillon
resterait introuvable est signalé (`missing`).

> **Mesuré** sur les deux packs téléchargés de l'utilisateur, face à sa copie de
> travail, en simulation : « TJontheRoad Delugetions Free Pack » — 77 fichiers,
> 18,3 Mio, environ 7 min par le câble, 6 parasites écartés, ses 36 presets dans
> `SYNTHS` ; « postsolarpunk Multisamples » — 1 094 fichiers, 271 Mio, **environ
> 1 h 43** par le câble, ses 766 références toutes résolues. Lecture des en-têtes et
> plan : 0,02 à 0,27 s.

---

## 5. Contrats de l'interface

### 5.1 `delugeapp/ui/theme.py`
```python
# Toutes les constantes de §2, plus :
FONT_UI = "Segoe UI"; FONT_MONO = "Consolas"
RADIUS = 8; PAD = 12
def qss(accent: str = GOLD) -> str          # feuille de style complète de l'application
def apply_theme(app: QApplication, accent: str = GOLD) -> None
def pad_color(i: int) -> str                # PAD_CYCLE[i % 12]
def category_color(name: str) -> str        # couleur stable par nom de catégorie (hash)
def severity_color(sev: str) -> str
def mix(c1: str, c2: str, t: float) -> str
def with_alpha(c: str, a: float) -> str     # 'rgba(…)'
def accent_qss(accent: str) -> str          # la seule partie colorée, que chaque page pose sur elle
def accent_values(accent: str) -> dict      # teintes dérivées d'un accent
def lit_fill(color: str) -> tuple[str, str, str]   # (haut, bas, encre) d'un pad allumé, lisible à 4,5
```
`qss(accent)` = partie commune + `accent_qss(accent)`. **Toute propriété de
couleur d'un contrôle vit dans la partie colorée, avec tous ses états** —
voir §5.22.
Le QSS doit couvrir : `QMainWindow`, `QWidget`, `QLineEdit`, `QPushButton` (normal/hover/pressed/
checked/disabled), `QToolButton`, `QComboBox` + vue déroulante, `QTableView`/`QTreeView` +
`QHeaderView` (lignes alternées, sélection en or translucide), `QScrollBar` fins, `QSlider`,
`QProgressBar`, `QTabWidget`, `QSplitter`, `QMenu`, `QToolTip`, `QGroupBox`, `QCheckBox`,
`QRadioButton`, `QSpinBox`/`QDoubleSpinBox`, `QStatusBar`, `QDialog`, `QListView`, `QTextEdit`.

### 5.2 `delugeapp/ui/icons.py`
```python
def icon(name: str, color: str = PAD_WHITE, size: int = 20) -> QIcon
    """Icônes dessinées en QPainter (aucun fichier externe). Noms requis :
       dashboard, samples, synth, kit, song, wand, tools, health, settings, play, stop, search,
       refresh, folder, save, export, import, trash, star, tag, wave, dice, copy, link, warning,
       check, chevron-right, chevron-down, chevron-left, plus, minus, filter, grid, list, info,
       backup, midi."""
def app_icon(size: int = 256) -> QIcon      # emblème : 4x4 pads colorés, disque sombre, anneau or
def pad_pixmap(colors, size=64) -> QPixmap
```

### 5.3 `delugeapp/ui/tasks.py`
```python
class Worker(QObject):
    progress = pyqtSignal(object); finished = pyqtSignal(object); failed = pyqtSignal(str)
    def __init__(self, fn, *args, **kwargs)
    def run(self) -> None
    def cancel(self) -> None
    @property
    def cancelled(self) -> bool
def run_task(parent, fn, *args, on_result=None, on_progress=None, on_error=None,
             title="Traitement…", modal=False, **kwargs) -> Worker
    """Lance fn dans un QThread, affiche une barre de progression dans la barre d'état
       (ou une QProgressDialog si modal). La fonction reçoit `progress=` et `should_stop=`
       si elle les accepte (inspection par `inspect.signature`)."""
```

### 5.4 Widgets (`delugeapp/ui/widgets/`)
```python
# common.py
class Card(QFrame)          # panneau arrondi avec titre optionnel et trait or
    def __init__(self, title="", parent=None); def body(self) -> QVBoxLayout
class StatTile(QFrame)      # grande valeur + libellé + couleur de pad + icône
    def __init__(self, label, value="—", color=GOLD, icon_name="", parent=None)
    def set_value(self, v): ...
class SectionTitle(QWidget) # titre + trait or (title_block du guide)
class TagChip(QWidget)      # étiquette colorée cliquable, signal clicked/removed
class SearchBar(QLineEdit)  # avec icône loupe et effacement, signal searchChanged (debounce 250 ms)
class Badge(QLabel)
class EmptyState(QWidget)   # illustration + message + bouton d'action
class BusyBar(QProgressBar)
class ElidedLabel(QLabel)
class StarRating(QWidget)   # 0..5 étoiles, signal changed(int)
class KeyValueTable(QTableWidget)   # affichage clé/valeur en lecture seule
class LitPad(QWidget)       # icône sur un pad allumé, halo compris
class PadEmblem(QWidget)    # l'emblème du guide, qui joue tant qu'il est visible
class ScoreRing(QLabel)     # note de santé dans une couronne d'encodeur (setText comme un QLabel)
class SegmentMeter(QWidget) # jauge en segments, comme une rangée de pads
class GrilleAdaptative(QObject)  # grille qui passe de N à M colonnes selon la place visible
class RangeeAdaptative(QObject)  # rangée de panneaux qui s'empile quand la place manque
def glow(widget, color, blur=26, alpha=0.55)  # halo d'un pad allumé, éteint avec son bouton
def pad_dot(color, size=11) -> QPixmap        # pastille d'une ligne de liste, en cache
# RowTableModel : colonne (libellé, extracteur, largeur, alignement[, formateur[, pastille]]),
# `pastille(valeur brute) -> couleur` pose un petit pad devant le texte (DecorationRole).

# chrome.py — la façade
class Wordmark(QWidget)     # emblème, « DELUGE » magenta, « COMPANION » espacé ; set_compact
class OledDisplay(QPushButton)   # l'écran : set_display(étiquette, ligne, ton), flash(message)
class NavPad(QPushButton)   # pad de navigation cochable : veilleuse, allumage animé, raccourci
class LedButton(QPushButton)     # bouton rond qui s'allume : set_state(couleur, allumé)
class LedStrip(QWidget)     # filet lumineux à la couleur de la page

# art.py (ui/) — dessins du guide, QtGui seul
def circuit(w, h, color, seed=0, dpr=1.0, density=0.42, fade=(0.20, 0.62)) -> QPixmap  # en cache
def paint_pad(p, rect, color, glow=0.30, radius=None, sheen=True)
def paint_off_pad(p, rect, diode=True, radius=None, tint="", alpha=1.0)
def paint_glow(p, rect, color, strength=0.35, spread=0.9)
def palette_for(color) -> list[str]   # la couleur de la page cinq fois sur neuf

# padgrid.py
class PadGrid(QWidget)
    """Grille de pads façade Deluge (par défaut 16x8). set_colors(matrice), signal padClicked(x,y),
       padHovered(x,y). Utilisé pour la vignette des morceaux, l'éditeur de motifs, le visualiseur."""
    def set_grid(self, cols, rows); def set_colors(self, m); def set_cell(self, x, y, color)
    def set_playhead(self, col: int | None)
class SongPreview(PadGrid)  # 18x8 depuis Song.preview_colors()
class StepSequencer(PadGrid)# édition de Pattern, signal patternChanged(Pattern)

# waveform.py
class WaveformView(QWidget)
    """Affiche des pics (numpy (N,2)), sélection par glisser, curseur de lecture, zoom molette,
       marqueurs de zone (start/end), grille temporelle. Signaux : selectionChanged(a,b),
       positionClicked(t), zoneChanged(start,end)."""
    def set_peaks(self, peaks, duration, sample_rate=44100)
    def set_position(self, t); def set_zone(self, a, b); def clear()

# envelope.py
class EnvelopeEditor(QWidget)
    """ADSR interactif (4 poignées). Signal changed(dict) avec attack/decay/sustain/release en 0..50."""
    def set_adsr(self, a, d, s, r); def adsr(self) -> tuple[int,int,int,int]

# knob.py
class Knob(QWidget)
    """Encodeur doré (cf. style.py). Molette et glisser vertical. Signal valueChanged(int).
       Affiche le nom et la valeur 0..50 (ou -25..25 si bipolaire)."""
    def __init__(self, label="", value=25, minimum=0, maximum=50, bipolar=False, color=GOLD)

# piano.py
class PianoKeys(QWidget)
    """Clavier 3 octaves, notes surlignables (gamme/accord), signal noteOn(int)/noteOff(int)."""
    def set_highlight(self, notes: list[int], color=GOLD); def set_range(self, lo, hi)

# filtercurve.py
class FilterCurve(QWidget)  # réponse LPF/HPF + résonance, mise à jour en direct
class SpectrumView(QWidget) # spectre (depuis render.spectrum) en échelle log
```

### 5.5 Pages (`delugeapp/ui/pages/`)
Chaque page est une `QWidget` avec ce contrat :
```python
class XxxPage(QWidget):
    status = pyqtSignal(str)                 # message pour la barre d'état
    def __init__(self, ctx: AppContext, parent=None)
    def refresh(self) -> None                # appelée quand la page devient visible ou après un scan
    TITLE: str ; ICON: str                   # titre (français, marqué N_) et nom d'icône
```
`AppContext` (défini dans `mainwindow.py`, importable sans cycle — le placer dans `delugeapp/ui/context.py`
si nécessaire… **NON : le placer dans `delugeapp/config.py`** pour éviter tout cycle) :
```python
@dataclass
class AppContext:
    settings: Settings
    sd: SDCard | None
    lib: Library
    player: Player           # instance unique
    def sd_or_warn(self, parent) -> SDCard | None   # affiche un avertissement si pas de carte
```
> **Note d'implémentation :** `AppContext` vit dans `delugeapp/config.py` et n'importe **aucun**
> module UI. Ses champs `sd`, `lib`, `player` sont typés en commentaire pour éviter les imports
> circulaires (`from __future__ import annotations` + `typing.TYPE_CHECKING`).

**dashboard.py — « Tableau de bord »**
Vignettes statistiques (échantillons, presets, kits, morceaux, espace libre, score de santé),
bouton de scan, carte détectée, 3 dernières anomalies, morceaux récents, actions rapides
(Générer un preset, Construire un kit, Sauvegarder, Nettoyer), répartition des échantillons
par dossier (barres colorées PAD_CYCLE), rappel de sauvegarde.

**samples.py — « Échantillons »**
Arbre des dossiers à gauche ; table filtrable à droite (nom, dossier, durée, SR, bits, canaux,
taille, BPM, tonalité, utilisations, note) ; panneau d'aperçu en bas (WaveformView + lecture +
infos + étiquettes + étoiles) ; barre de recherche + filtres (catégorie, durée, inutilisés,
manquants, favoris) ; actions : lecture, révéler dans l'explorateur, renommer, déplacer,
convertir (lot), normaliser, couper le silence, mono/stéréo, rééchantillonner, détecter BPM/
tonalité, marquer, supprimer, voir les utilisations, remplacer partout. Import par glisser-déposer
vers un dossier de la carte, avec conversion automatique si nécessaire.

**synths.py — « Presets »**
Liste des presets SYNTHS (arbre par dossier + table : nom, dossier, moteur, oscillateurs,
filtre, fx, firmware, catégorie) ; panneau de détail : résumé lisible du son, Knobs des
principaux paramètres (volume, cutoff, résonance, ADSR ×2, LFO, fx), EnvelopeEditor,
FilterCurve, liste des patch cables, modKnobs, échantillons utilisés ; boutons :
Écouter (render), Dupliquer, Renommer, Déplacer, Éditer (modifie et enregistre le XML),
Variations, Comparer deux presets (diff des paramètres), Exporter la fiche.

**kits.py — « Kits »**
Table des kits ; détail : rangées du kit avec le nom, l'échantillon, sa présence (✓/✗),
l'enveloppe, le volume, le pan ; audition d'une rangée ; remplacer un échantillon ;
créer un kit (kitgen) ; construire depuis un dossier ; détecter les rangées cassées ;
StepSequencer pour essayer un motif et l'exporter en MIDI.

**songs.py — « Morceaux »**
Table des morceaux (nom, BPM, tonalité, clips, notes, mesures, firmware, taille, date) ;
détail : SongPreview (vignette 18×8 en couleurs), statistiques, liste des clips
(nom, preset, longueur, notes, section), instruments utilisés, échantillons utilisés avec
état, presets manquants ; actions : rapport HTML, export MIDI d'un clip, ouvrir le dossier,
dupliquer, renommer.

**generator.py — « Générateur »**
Le cœur créatif. Colonne gauche : choix du genre (grille de pastilles colorées avec
description et plage BPM), du rôle, curseurs macro (Brillance, Mouvement, Espace, Saleté,
Largeur, Complexité), graine (avec bouton dé), mode moteur. Centre : aperçu du son généré —
description française, EnvelopeEditor, FilterCurve, SpectrumView, WaveformView du rendu,
Knobs principaux. Droite : file de variations (8 vignettes cliquables), historique.
Barre d'action : Générer, Aléatoire total, Muter, Morpher entre deux, Écouter, Enregistrer
dans SYNTHS/<dossier> (avec choix du nom et du sous-dossier), Générer un lot (n presets
dans un nouveau dossier). Onglet secondaire : générateur de kit (kitgen) avec choix des rôles.

**toolbox.py — « Outils »**
Onglets :
- *Théorie* : tonique + gamme -> PianoKeys surligné, notes, accords diatoniques, générateur
  de progression (par genre/humeur), voicings, export MIDI, `<modeNotes>` à recopier dans le Deluge.
- *Rythme* : générateur euclidien (pulses/steps/rotation par piste) + motifs par genre +
  groove + humanisation -> StepSequencer, export MIDI, ASCII à recopier.
- *Calculatrice* : BPM -> temps de delay/LFO (droite/pointée/triolet, Hz, syncLevel Deluge),
  table des fréquences de notes, durée d'une mesure, conversion ticks/mesures,
  taille mémoire d'un échantillon, temps d'enregistrement restant.
- *Mixage harmonique* : roue de Camelot cliquable, tonalités compatibles, recherche dans la
  bibliothèque par tonalité/BPM compatibles.
- *Arrangement* : modèles de structure par genre (intro/build/drop/break…) avec durée en
  mesures et barre visuelle, conseils, export en sections de morceau Deluge.
- *Aide-mémoire Deluge* : raccourcis essentiels, plages de valeurs, correspondance
  syncLevel ↔ division rythmique, limites de la machine.

**health.py — « Santé »**
Bouton d'analyse ; score en grand (jauge colorée) ; liste des anomalies par gravité avec
le détail des fichiers concernés ; sélection multiple -> « Corriger automatiquement »
(affiche le plan avant application) ; onglet Doublons (groupes, choix du gardé) ;
onglet Manquants (avec suggestions de remplacement et bouton relier) ;
onglet Inutilisés (archiver) ; onglet Sauvegardes (créer/restaurer/comparer) ;
export du rapport en HTML.

**settings.py — « Réglages »**
**Chemin de la carte SD modifiable** (champ + parcourir + détection automatique des lecteurs
amovibles + validation visuelle + chemins récents), dossier de sauvegarde, périphérique audio
et volume d'aperçu, options de scan (empreintes, analyse), confirmations et sauvegardes
automatiques avant écriture, couleur d'accent, à propos (version, palette, crédits, lien vers
le guide de l'utilisateur), bouton « Réinitialiser l'index ».

### 5.6 `delugeapp/ui/mainwindow.py`
```python
class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext)
```
- Colonne de gauche : une rangée de `NavPad` (212 px, repliable à 64 px) avec les 9 pages ;
  la page affichée s'allume à sa couleur, les autres restent en veilleuse.
- **Une seule barre du haut** (56 px, `CHROME`) : logotype, **barre de menus intégrée**
  (`menuBar()` rend celle-ci), écran OLED de la carte (cliquable : ouvre les réglages ; reprend
  chaque message de la barre d'état), pastille du Deluge, recherche globale, « Analyser »,
  touche de lecture ronde. Elle se resserre sous 1 360 et 1 180 px. Dessous, un filet lumineux
  à la couleur de la page.
- `QStackedWidget` pour les pages, création paresseuse (page instanciée au premier affichage).
- Barre d'état : message, barre de progression des tâches, indicateur de lecture, espace libre.
- Menus : Fichier (Choisir la carte, Scanner, Sauvegarder, Quitter), Édition, Outils, Aide (À propos, Raccourcis).
- Raccourcis : `Ctrl+R` scanner, `Ctrl+F` recherche, `Ctrl+G` générateur, `Espace` écouter/arrêter,
  `Ctrl+,` réglages, `F1` aide, `Ctrl+1..9` pages.
- Restaure la géométrie et la dernière page via `QSettings`.
- Au démarrage : si `settings.sd_path` est vide ou invalide -> propose la détection automatique
  puis un dialogue de choix de dossier, et affiche l'`EmptyState` du tableau de bord.

### 5.7 `main.py`
```python
#!/usr/bin/env python3
# Lance l'application. Gère --sd <chemin>, --reset-db, --no-splash, --version.
# Installe un hook d'exception qui affiche une QMessageBox lisible + trace dans le journal.
# Journal : %APPDATA%/DelugeCompanion/app.log (RotatingFileHandler, 1 Mo, 3 fichiers).
```

---

### 5.11 Correction audio dans l'interface

`PlanDialog` vit dans `ui/widgets/common.py` (et non plus dans la page Santé)
parce que deux pages s'en servent. Il n'exige de son plan que `summary()`,
`counts()` et `to_text()`, ce qui lui permet d'afficher aussi bien un
`organize.Plan` qu'un `samplefix.FixPlan`. Il avertit en rouge quand le plan
comporte des suppressions **ou** quand `plan.changes_length` est vrai.

* **Page Santé** — les quatre codes de `samplefix.HEALTH_CODES` reçoivent une
  case à cocher au même titre que les codes de `health.AUTOFIX_CODES`, et le
  bouton « Corriger » s'active même si aucune anomalie `organize` n'est
  présente. Les codes cochés sont répartis entre les deux moteurs, chacun
  avec sa propre confirmation.
* **Page Échantillons** — un bouton « Traiter… » ouvre `ProcessDialog`
  (mono, continu, normalisation, coupe du silence, fondus,
  rééchantillonnage), puis `plan_custom` → `PlanDialog` → exécution dans un
  fil. La page émet `cardModified` pour que les autres se rafraîchissent.

⚠️ **En Qt 6.11, `ItemIsUserCheckable` fait partie des drapeaux par défaut
d'un `QListWidgetItem`.** Tester ce drapeau pour savoir si un élément porte
une case renvoie vrai partout ; ce qui fait apparaître la case, c'est l'appel
à `setCheckState`, donc la présence de `CheckStateRole`.

### 5.12 Découpage dans l'interface

`WaveformView` gagne `set_markers(times, active=-1)`, `markers()` et
`marker_at(x)` : des coupes numérotées, la tranche active légèrement remplie.
La transparence se règle avec `QColor.setAlphaF` — `theme.with_alpha` rend une
chaîne QSS `rgba(...)` que `QColor` **ne sait pas lire**.

La page Échantillons gagne un bouton « Découper… » qui ouvre `SliceDialog` :
onde avec les coupes, choix du placement (attaques / divisions égales), nombre
de tranches, sensibilité, alignement sur le tempo, tableau des tranches avec
écoute au clic, puis « Écrire le kit » ou « Exporter en fichiers… ». Le
découpage porte sur **une** boucle à la fois.

### 5.13 Recherche par ressemblance dans l'interface

`RowTableModel` gagne `set_columns()`, symétrique de `set_rows()` : la page
Échantillons ajoute une colonne « Proximité » dans la vue « sons proches » et
la retire en revenant à la liste.

Le bouton « Sons proches » bascule : il entre dans la vue, puis devient
« Toute la liste ». Les lignes y sont des `ScoredRow`, une enveloppe autour de
la ligne d'index — un `sqlite3.Row` ne se modifie pas — qui ajoute
`closeness` et `distance` sans toucher aux extracteurs de colonnes.

### 5.14 Exports de la page Morceaux

La page reste **entièrement en lecture seule** pour la carte : ses deux
nouveaux boutons écrivent ailleurs.

* « Morceau en MIDI » — `midifile.song_to_midi`, avec un message qui dit
  explicitement que les clips étant des boucles, toutes les pistes démarrent
  au début ;
* « Rassembler… » — `songpack.collect` puis `PlanDialog` puis
  `songpack.write_pack` dans un fil. La classe `_PackPlan` enveloppe un
  `SongPack` pour le dialogue : celui-ci n'exige que `summary()`, `counts()`
  et `to_text()`, ce qui évite un second dialogue de confirmation.

### 5.15 `Page.guard` ne transmet que ce que le destinataire accepte

```python
def guard(self, fn) -> Callable[..., None]   # try/except + troncature
def _arite(fn) -> int | None                 # None = variadique
```

⚠️ **Une enveloppe variadique défait la troncature d'arguments de PyQt.**
PyQt supprime normalement les arguments excédentaires d'un signal selon
l'arité du destinataire : `clicked(bool)` branché sur une méthode sans
paramètre fonctionne. Mais un `wrapper(*args, **kwargs)` paraît accepter
tout, et le booléen arrive à une méthode qui n'en veut pas :

```
TypeError: _listen() takes 1 positional argument but 2 were given
```

**55 boutons** étaient inertes pour cette raison. `guard` tronque donc
explicitement, en préservant les gestionnaires qui attendent vraiment un
argument. **Ne pas réintroduire d'enveloppe variadique** autour d'un
connecteur Qt.

#### 5.15.1 Les tests doivent cliquer, pas appeler

Un test qui appelle `page._methode()` ne vérifie pas ce que fait
l'utilisateur. `tests/test_ui.py::TestClicsReels` clique **réellement** sur
chaque bouton de chaque page, sur une carte jetable, toutes boîtes modales
neutralisées — dont `QDialog.exec` sur la **classe de base**, ce qui couvre
tous les dialogues de l'application, et les `QInputDialog` de la page
Générateur. Vérifié par retrait du correctif : 56 échecs sans, 0 avec.

#### 5.15.2 Toute la surface interactive est couverte

Trois classes se partagent le travail, sur la fixture commune
`InteractionCase` (hériter d'une classe de tests les rejouerait) :

| Classe | Ce qu'elle actionne |
|---|---|
| `TestClicsReels` | chaque bouton de chaque page |
| `TestInteractionsReelles` | onglets, lignes de tableau, listes déroulantes, cases à cocher, curseurs, champs de saisie |
| `TestMenusEtRaccourcis` | chaque entrée de menu et chaque raccourci de la fenêtre principale |

Mesuré à l'écriture : **398 interactions hors boutons, 0 erreur**. Les
boutons étaient donc le seul chemin cassé, parce que seuls eux passaient par
une enveloppe variadique branchée sur un signal porteur d'un argument
indésirable. Les autres connexions guardées emploient des lambdas à la bonne
arité (`lambda _t:`, `lambda _i:`) ou des méthodes qui veulent vraiment
l'argument (`_set_favorite(checked)`, `_apply_volume(value)`).

La fenêtre principale protège ses actions avec `_safely`, **un rempart
distinct de `Page.guard`** : il a maintenant son propre test.

### 5.18 Aucune commande ne laisse deviner

```python
# delugeapp/ui/aide.py
COMMUNES: dict[str, str]                     # libellés partagés
EXPLICATIONS: dict[str, dict[str, str]]      # par page, puis par commande
def expliquer(page, key) -> int              # pose les infobulles manquantes
def manquantes(page, key) -> list[str]       # ce qui n'explique toujours rien
```

**Mesuré avant** : 102 des 174 commandes de l'application (59 %)
n'expliquaient rien, dont « Supprimer les doublons », « Relier
automatiquement », « Archiver dans _UNUSED » et « Restaurer » — quatre
actions qui écrivent sur la carte. **Après** : 0 sur 184.

Règles :

* les clés sont `"@_attribut"` (le widget est un attribut de la page, le
  plus stable) ou le libellé exact ; `COMMUNES` sert aux libellés partagés ;
* une explication **ne répète pas le libellé** et dit ce qui va se passer,
  pas ce que le bouton s'appelle ; une action qui écrit sur la carte
  **l'annonce en gras** ;
* une infobulle posée à la création l'emporte : elle est plus proche du
  code ;
* quatre tests gardent l'état : aucune commande muette, aucune explication
  orpheline, les quatre actions destructrices annoncent qu'elles écrivent,
  et une explication n'est jamais son propre libellé.

### 5.19 Le premier écran accueille

Sans carte, les neuf pages montraient un triangle d'alerte et « Aucune carte
SD ». C'est pourtant l'état normal du premier démarrage. Désormais :
l'icône **de la page** dans sa couleur, « Où est votre carte Deluge ? », et
**deux chemins** — « Indiquer le dossier » et « Détecter la carte », le
second étant le plus court (`EmptyState(action2=…)`, `Page.detectRequested`).

L'en-tête est juste **dès la première image** : l'invitation « Aucune carte
— cliquez pour choisir » et la pastille du Deluge étaient peintes après
150 ms, puis après une seconde. Et « Analyser » est éteint tant qu'il n'y a
pas de carte : ne pas proposer ce qui ne peut pas marcher.

### 5.20 « À faire maintenant »

Un bandeau en tête du tableau de bord donne **une** suggestion, la plus
urgente, avec le bouton qui l'exécute ou qui mène à l'endroit exact. L'ordre
suit le risque, pas les fonctions :

1. carte jamais lue → analyser ;
2. aucune sauvegarde → sauvegarder (avant toute correction) ;
3. échantillons manquants → les retrouver ;
4. doublons → les voir ;
5. plus de 200 orphelins → les ranger ;
6. rien à signaler → générer un preset.

`_fill_health` rend son rapport pour que le bandeau s'en serve : le
recalculer serait absurde. Trois tests fixent l'ordre, le cas sans carte, et
le fait que le bouton mène où il annonce.

### 5.21 Lisible, et à toutes les tailles

**Le contraste se calcule** : ``theme.contrast`` et ``theme.readable``. La
norme demande 4,5 pour un texte courant. Mesuré avant correction :

| texte | fond | ratio |
|---|---|---|
| secondaire | surface relevée | **3,78** |
| secondaire | panneau | 4,41 |
| titre « Presets » (violet) | panneau | 4,26 |
| titre « Réglages » (indigo) | panneau | **3,51** |

Deux règles en découlent :

* ``TEXT_SOFT`` (#8E95A0) pour les **textes** secondaires, distinct de
  ``GREY`` qui reste celui du décor : éclaircir le gris en bloc aurait aussi
  éclairci traits et icônes, qui ont le droit d'être discrets ;
* ``readable(couleur)`` éclaircit une teinte **juste** assez pour atteindre
  4,5 ; un titre de section garde la couleur exacte de sa page pour son
  trait, et la variante lisible pour son libellé. Les teintes déjà
  lisibles ne bougent pas.

**La feuille de style doit se construire.** ``qss()`` attrape une
substitution manquante et rend un style minimal : l'application démarre,
mais grise et plate, et seule une ligne de journal le dit. C'est arrivé en
ajoutant ``TEXT_SOFT`` sans le déclarer. Deux tests le vérifient, pour
l'accent par défaut et pour trois autres.

**Les listes tiennent à toutes les tailles.** Mesuré : les largeurs avaient
été réglées pour 1 440 px ; à 1 366 × 768 deux listes débordaient, à
980 × 640 les quatre. ``_ColonnesAdaptatives`` cache les dernières colonnes
— elles sont déclarées par ordre d'importance — et les redonne dès que la
place revient. La première ne disparaît jamais. Vérifié de 980 à 1 920 :
aucun débordement.

**L'aperçu cède la place à la liste.** Son minimum atteignait 346 px : sur
un portable de 720 px de haut, la liste tombait à **une ligne visible**.
Placé dans une zone défilante, son minimum tombe à 131 px et la liste garde
cinq lignes.

**La barre d'actions se replie** plutôt que de couper ses libellés en plein
mot (« Dans l'explorat »). Trois états : tous les textes, seul le principal,
que des icônes — et l'infobulle nomme toujours le bouton. Le seuil dépend
de la police, donc il ne se teste pas sous la plateforme « offscreen » : le
test porte sur le mécanisme, la mesure du seuil se fait à la main.

### 5.22 La façade : le guide, pas seulement sa palette

L'interface reprenait la palette du guide et restait un tableau de bord de
bureautique : barre de menus Windows, rail de texte, cartes identiques,
tableaux partout. Elle reprend maintenant ses signatures (§2).

**Chaque page pose sa couleur sur elle-même** : `Page.__init__` appelle
`setStyleSheet(accent_qss(self.color))` avant de créer le moindre enfant.
Piège de Qt, et règle qui en découle : la feuille d'un parent l'emporte
**toujours** sur celle de l'application, quelle que soit la spécificité des
sélecteurs. Si la page fixait le fond des boutons sans fixer celui des
boutons désactivés, un bouton éteint garderait le fond vif de la page — et
de même pour le survol, l'appui, l'état coché. Toute propriété de couleur
d'un contrôle vit donc dans la partie colorée, **avec tous ses états** ; la
partie commune ne garde que la géométrie et les conteneurs.

**`Page._light_up()`** suit `build()` : chaque bouton `#Primary` rayonne de la
couleur de la page (`glow`, éteint avec le bouton) et son icône est retracée
à l'encre qui se lit sur elle (`iconName`) ; chaque widget qui a
`set_accent` (forme d'onde, courbe de filtre, spectre, enveloppe) prend la
couleur de la page. Les encodeurs restent dorés, comme sur la machine.

**Les listes portent la couleur de leurs catégories** : une pastille devant
la catégorie d'un échantillon ou d'un preset, comme la couleur d'un clip sur
la machine (`category_color`, stable d'une session à l'autre).

**L'en-tête de page est une ouverture de partie** (`PageHero`) : pad allumé,
titre en capitales, treillis à la couleur de la page tiré d'une graine
propre (`art.seed_of(clé)`), qui s'efface vers le titre et apparaît en une
demi-seconde à chaque affichage. Le contrat `page_header() -> (hôte,
actions)` est inchangé.

**Mesuré, et corrigé :**

| défaut | mesure | correction |
|---|---|---|
| bouton principal violet, indigo | bas 4,43, haut 4,42 | `lit_fill` pousse chaque extrémité à 4,5 |
| barre d'actions à 980 px | 6 boutons coupés, ajusteur à l'état 0 | réveil à l'affichage, boutons « non masqués » |
| tableau de bord à 980 px | 900 px demandés pour 720 | tuiles sur 2 colonnes, panneaux empilés, phrase repliée |
| répartition des échantillons | jauge dessinée sur le nom | politique fixe du libellé élidé |
| questions de `QMessageBox` | « Yes », « No » | traduction `qtbase_fr` chargée au lancement |

Tous, sauf le premier, dataient d'avant la refonte : ils ne se voyaient
qu'à 980 px, en faisant défiler le tableau de bord, ou en ouvrant une
question.

**Les adaptations observent la place visible**, pas leur propre largeur : un
contenu trop large ne rétrécit jamais de lui-même, il pousse la page sous
une barre de défilement horizontale. `GrilleAdaptative` et
`RangeeAdaptative` écoutent donc la zone visible du défilement.

**Ce qui ne change pas** : l'ordre et les clés des pages, les raccourcis,
les menus et leurs actions, les adresses `Page#Partie`, le registre
d'explications, les attributs que les tests lisent (`_card_button.text()`,
`_score.text()`, `_tiles[…]._value`…). L'écran OLED est un `QPushButton` dont
le texte garde le chemin complet ; l'anneau de note est un `QLabel`.

### 5.17 Le Deluge branché

* **Pastille dans l'en-tête** : grise s'il est absent, or s'il est détecté
  mais pas connecté, verte s'il est connecté (infobulle : firmware, tempo).
  Un clic connecte quand c'est le geste évident, ouvre « Deluge en direct »
  quand la machine est connectée, et mène aux réglages sinon.
* **« Deluge en direct »** (`ui/livewindow.py` ; Outils ▸ Deluge en direct,
  Ctrl+D ; Réglages ; pastille) : une fenêtre à garder à côté. L'écran de la
  machine recopié — la recopie part à l'ouverture —, « Faire signe »,
  « Vérifier », « Tout éteindre » ; le tempo et la lecture lus dans
  l'horloge ; les notes tenues et leur accord ; le son sélectionné, d'après
  le retour MIDI Follow ; les réglages à faire sur la machine, cochés à
  mesure que le lien les constate. Recopie arrêtée : un message, **jamais
  une image figée** qu'on prendrait pour la machine. Déconnectée : le
  bouton se décoche ; reconnectée fenêtre ouverte : la recopie reprend.
  Fermer la fenêtre arrête l'abonnement.
* **Le tempo de la machine passe aux outils** (`midi_follow_tempo`, actif
  par défaut) : les trois tempos de la boîte à outils suivent l'horloge
  quand son arrondi change ; une page ouverte pendant que la machine joue le
  prend une fois, à sa première visite — ensuite l'utilisateur décide.
* **Surveillance au battement de seconde** : énumérer les ports coûte
  quelques microsecondes, moins cher qu'un bouton « rafraîchir ». Le
  branchement et le débranchement sont annoncés dans la barre d'état ; un
  débranchement referme le port, qui pointerait sinon sur un appareil
  disparu.
* **Réglages** : section « Deluge branché » — état, ce que la machine a
  dit d'elle (firmware, aller-retour, port SysEx), ports, canal, connexion
  automatique, écoute sur la machine, suivi du tempo, « Jouer un do »,
  « Tout éteindre », « Deluge en direct… », et les réglages à faire **sur**
  le Deluge (Follow ▸ Channel A, Feedback).
* **Écoute** : `Page.audition(sound)` rend `True` quand la machine a pris le
  relais ; la page retombe sinon sur son rendu habituel. Le réglage est
  explicite (`midi_audition`), parce qu'envoyer du son dans une machine
  branchée sur un ampli ne doit jamais être une surprise.
* **Anomalies cliquables** : chaque anomalie du tableau de bord mène à
  l'onglet qui la répare, via `ISSUE_DESTINATION` et les adresses
  `Page#Partie` de §5.16. `health.ISSUE_CODES` fige le vocabulaire des
  codes, et deux tests vérifient qu'aucune destination ne vise un code mort.

### 5.16 Refonte de l'interface : où suis-je, que puis-je faire

L'utilisateur a jugé l'interface « triste et assez compliquée à utiliser » et
a désigné quatre maux : on ne sait pas où l'on est ni où cliquer ; les listes
sont des tableaux illisibles ; c'est terne ; il y a trop d'écrans et trop
d'étapes. Les règles qui en découlent :

**Où suis-je.** Une couleur par page (§2), déclinée partout de la même
manière. `Page.color` et `Page.header()` la posent sans que chaque page ait à
la répéter ; `Page._tint_sections()` l'applique après `build()` à tous les
`SectionTitle` **qui n'ont pas choisi la leur** — un panneau qui montre une
autre destination garde la couleur de cette destination.

**Où cliquer.** Une seule action principale par écran (`#Primary`, plus
grande et pleine) ; les actions qui exigent une sélection sont **éteintes**
tant qu'il n'y en a pas, au lieu de répondre « Aucune sélection » après coup.
Un contrôle qui ne mène nulle part n'affiche pas de curseur de main
(`StatTile.set_clickable`). Deux commandes différentes ne portent pas le même
mot : la barre d'en-tête garde « Analyser » (relire la carte), la page Santé
dit « Diagnostiquer » (lire l'index).

**Les listes.** Une colonne qui répète la même valeur partout ne mérite pas
une colonne. Mesuré sur 1 741 échantillons : `sr` vaut 44 100 dans 90,7 % des
cas, `bit_depth` vaut 16 dans 87,7 %, et **`bpm` est vide dans 96,2 %**. Les
onze colonnes tombent à huit, dont une colonne « Format » qui ne montre que
l'exception (vide quand le fichier est 44 100/16/mono). Une colonne de chemin
montre le dernier segment (« Mellotron »), pas le chemin entier tronqué.

**Les vides.** Un écran vide est un moment où l'utilisateur a besoin qu'on le
guide : c'est le pire endroit pour économiser l'encre. Tout vide porte un
emblème à la couleur de la page, dit ce qui manque et propose le geste
(`EmptyState`, `hint_in_list`, `WaveformView.set_empty_text`,
`SpectrumView.set_empty_text`). Un message d'attente doit parler de **cet**
écran : « choisissez-en un dans la liste » n'a aucun sens dans le générateur,
où il n'y a pas de liste.

**Moins d'étapes.** `MainWindow.go_to` accepte une adresse `Page#Partie` :
`Health#Sauvegardes` ouvre la page **et** son onglet. `Page.focus_on(hint)`
compare le libellé des onglets sans tenir compte de la casse ni des accents,
et ne fait rien si le libellé est inconnu — un raccourci approximatif ne doit
jamais empêcher d'arriver sur la page. Le diagnostic de santé part de
lui-même au premier affichage (il lit l'index, ne touche pas à la carte,
0,7 s sur la carte réelle) plutôt que d'attendre un clic devant deux cadres
vides.

### 5.23 Des morceaux du Deluge depuis les outils de création

Un bouton par outil, tous sur le même parcours (`ui/songexport.export_song`,
`Page.write_song`) : construire le morceau (une erreur d'usage s'annonce avant toute
question), demander le nom (`QInputDialog.getText`), montrer le plan et le faire
confirmer si « Confirmer chaque écriture » est coché (`QMessageBox.question`), écrire,
indexer (`scan.index_songs`, qui **ne marque pas** la relecture des morceaux comme faite),
émettre `Page.songWritten(rel)` — la fenêtre rafraîchit alors toutes les pages.

| page | bouton | morceau |
|---|---|---|
| Outils › Théorie | `_song_prog_button` « En morceau » | une piste et un clip par partie (accords, basse, arpège, mélodie) avec **les sons de l'écoute** (`part_presets`), plus la batterie si cochée ; tout boucle ensemble |
| Outils › Rythme | `_song_beat_button` « En morceau » | le motif affiché, joué par le kit de l'écoute complété (`drum_kit_for`) : une piste sans son reçoit une percussion |
| Outils › Arrangement | `_song_sketch_button` « Esquisse en morceau » | une section du Deluge par section du modèle, répétitions calculées, arrangement complet |
| Kits | « Motif en morceau » | le kit de la carte **tel qu'il est dans son fichier** (conversions d'époque) et le motif d'essai |
| Générateur › Preset | « Essayer en morceau » | le son, une phrase faite pour son rôle et la batterie du genre ; son arpège est gardé |
| Générateur › Kit | « Kit en morceau » | le kit construit et le rythme de son genre |
| Échantillons › Découper | « Écrire en morceau » (dialogue) | le kit des tranches et un clip qui rejoue chaque tranche à sa place |

Les explications de l'aide annoncent toutes « **Écrit sur la carte.** ». Tests :
`TestMorceauxDepuisLesOutils` et `TestBoucleDecoupeeEnMorceau` cliquent chaque bouton sur
une carte jetable et relisent le fichier ; `TestSongWriter` couvre le module.

**Vignettes.** La première rangée du `preview` d'un morceau est celle **du bas**
(`imageStore[0]`) ; `Song.preview_colors` rend désormais la matrice première ligne en
haut. Avant le 15 octobre 2026, la page Morceaux montrait les vignettes à l'envers. Les
morceaux écrits ici portent une vignette de leur vue Morceau : une rangée par clip, la
section et l'état dans la barre latérale.

---

### 5.24 La carte reste dans le Deluge

`ui/cardwork.py` (`CardWork`, porté par la fenêtre et posé sur
`ctx.card_work`) tient la copie de travail à l'image de la carte :

* **à la connexion** d'un Deluge qui ouvre sa carte (évènement `files` du
  lien) : synchronisation, ou invitation à créer la copie de travail ;
* **après chaque écriture** de l'application (`cardModified`,
  `presetSaved`, `songWritten`) : envoi deux secondes après la dernière ;
* **au retour dans la fenêtre** (au plus toutes les 30 s) : réception de ce
  que le Deluge a enregistré ;
* **jamais pendant que la machine joue** : sa carte sert à jouer ; la
  synchronisation attend l'arrêt (`on_transport`).

Ce qui est reçu passe à l'index par l'analyse incrémentale du tableau de
bord. Créer la copie de travail montre d'abord le plan (combien repris de
la sauvegarde, combien par le câble, en combien de temps), puis la copie
devient la carte de l'application et l'analyse part.

**Réglages ▸ Carte du Deluge** : état (le Deluge ouvre-t-il sa carte ?
quelle copie ?), « Créer la copie de travail » / « Synchroniser
maintenant », « Suppressions à confirmer (N)… », synchronisation d'office,
la sauvegarde (« lue, jamais écrite »), « Choisir la sauvegarde… »,
« Mettre à jour la sauvegarde ». L'ancienne section devient « Autre
emplacement de carte » : une carte glissée dans un lecteur du PC, pour un
firmware sans accès USB. Menu Outils ▸ « Synchroniser avec le Deluge »
(Ctrl+Maj+D). L'en-tête dit sur quoi l'on travaille : « CARTE DU DELUGE ·
COPIE DE TRAVAIL », ou « SAUVEGARDE · LECTURE SEULE ».

### 5.25 Le PC et le Deluge, dans les deux sens

**Envoyer au Deluge** (`ui/sendfiles.py`) — un seul parcours, d'où qu'on parte :
glisser-déposer de fichiers ou de dossiers **n'importe où sur la fenêtre** ; Fichier ▸
« Envoyer des fichiers au Deluge… » (Ctrl+I) et « Envoyer un dossier au Deluge… »
(Ctrl+Maj+I) ; « Envoyer au Deluge… » de la page Échantillons (dans le dossier choisi
dans son arbre) ; « Envoyer des fichiers… » du tableau de bord.

1. la lecture de ce qui est déposé (`scan_sources`) part hors du fil de l'interface ;
2. `SendDialog` montre le plan : résumé, destination des sons hors d'un pack (le plan se
   recalcule au changement), où part l'envoi et combien de temps le câble y mettra
   (« Le Deluge ne doit pas jouer pendant l'envoi » ; au-delà de 30 min, conseil de
   n'envoyer qu'une partie), avertissements (refusés, convertis, laissés, échantillons
   introuvables), détail en chasse fixe — par la feuille de style (`role="mono"`), un
   `setFont` y serait écrasé ;
3. « Envoyer » : `apply_import` dans un fil, avec une boîte de progression ;
4. l'index relit ce qui est arrivé (`update_index`), `_card_written` lance la
   synchronisation : sur la copie de travail, les fichiers partent sur le Deluge deux
   secondes plus tard, ou à sa prochaine connexion.

Rien n'est écrit sans le plan accepté. Ce qui n'est pas du Deluge le dit (« Rien à
envoyer au Deluge », avec les raisons) ; la sauvegarde refuse (« Rien n'est écrit
ici »). Le dépôt est traité **après** son retour (`QTimer.singleShot(0)`) : une question
posée pendant le dépôt figerait l'Explorateur qui l'attend. Les champs de recherche
n'acceptent plus de dépôt (ils y écrivaient l'adresse du fichier).

**Le voile** (`chrome.DropVeil`) couvre la fenêtre pendant le glisser : le treillis du
guide en vert, un grand pad allumé, « DÉPOSEZ POUR ENVOYER AU DELUGE », et où partira le
dépôt (`where_it_goes` : la copie de travail puis le câble, la prochaine connexion, une
carte dans un lecteur, ou la sauvegarde qui refusera).

**Vers le PC** : la liste des échantillons se glisse vers l'Explorateur ou un logiciel de
MAO (`_SampleModel` : `ItemIsDragEnabled`, `mimeData` en adresses de fichiers) — une
copie, la carte n'est pas touchée.

**« Le Deluge et le PC »**, panneau du tableau de bord, juste sous « À faire
maintenant », à la couleur de la pastille du Deluge connecté : un pad d'état (vert, la
carte s'ouvre par USB ; or, branché sans firmware 1.3 ; gris, débranché ; ambre,
synchronisation), ce qui attend le Deluge et le temps du câble, le dernier échange,
« Reçu du Deluge » (six derniers fichiers de musique, chacun ouvre sa page sur lui :
`Songs#SONGS/Cool1.XML`), « Synchroniser », « Envoyer des fichiers… », la zone de dépôt.
Sur la sauvegarde ouverte : « lecture seule » et « Carte du Deluge… ». Sur une carte
ouverte directement : la copie y est immédiate.

**La sauvegarde en retard.** `CardWork.check_backup` compare, hors du fil de l'interface
et sans rien dans la barre d'état (`run_task(quiet=True)`), la carte à la sauvegarde :
au démarrage et après chaque réception. « À faire maintenant » propose alors « Mettre à
jour la sauvegarde » — avant les échantillons manquants ; avec le miroir de la carte
réglé, « Aucune sauvegarde de cette carte » ne s'affiche plus, puisqu'il en est une. Le
panneau ne répète pas la phrase que le bandeau dit déjà, et le bandeau se recalcule sur
le dernier diagnostic quand seul l'état de la carte change. Un clic sur « Mettre à jour »
pendant une comparaison attend sa réponse.

**L'en-tête** dit ce qui attend : « COPIE DE TRAVAIL · 3 À ENVOYER », ou
« SYNCHRONISATION… ». Le compte (`refresh_pending`) passe hors du fil de l'interface —
dans le fil, il figeait la fenêtre 0,3 s de plus au démarrage (mesuré : 0,52 s sans,
0,84 s avec ; 0,57 s une fois déplacé) — et porte un numéro : un compte ancien, fini
après une synchronisation, ne la contredit pas.

**Pendant que la machine joue**, un transfert s'arrête entre deux blocs
(`UsbCard(should_stop)`), et reprend à l'arrêt (`on_transport`) : « Le Deluge joue : la
synchronisation s'est arrêtée et reprendra à l'arrêt ». Débranché pendant un transfert :
« reprendra à sa prochaine connexion ». Chaque échange est gardé et écrit au journal :
« Deluge — synchronisation (écriture) : 2 envoyé(s), en 0,4 s », puis un fichier par
ligne tant qu'ils sont quarante au plus.

**Ouvrir un fichier par son chemin** : `Page.focus_on` reconnaît un chemin de la carte ;
`Page.reveal_item` le sélectionne dans la liste de la page, en retirant d'abord recherche,
filtres et dossier qui le cacheraient.

### 5.26 Deux langues : français et anglais

**Choisir.** Le menu « Langue », entre « Outils » et « Aide », propose « Français » et
« English », chacun écrit dans sa propre langue : qui ne lit pas la langue affichée doit
retrouver la sienne. La langue retenue est cochée. Le choix est enregistré tout de suite
(`Settings.language`, `"fr"` ou `"en"`, normalisé à la lecture — l'inconnu donne le
français), puis une question, **posée dans les deux langues**, propose de redémarrer :

- « Oui » : `MainWindow.restart()` ferme la fenêtre comme à l'ordinaire (question si un
  traitement tourne, état et page gardés, fils arrêtés, contexte fermé) et lève
  `restart_requested` ; `main._run_windows` reconstruit alors contexte et fenêtre **dans le
  même processus**, dans la nouvelle langue. L'index ne se vide qu'au premier démarrage,
  même si `--reset-db` était demandé ;
- « Non » : la barre d'état dit, dans la langue encore affichée, que la nouvelle langue
  s'appliquera au prochain démarrage.

`main._choose_language()` lit la langue avant même la ligne de commande : son aide parle la
langue choisie. Les boutons standard de Qt (« Oui », « Non », « Annuler ») viennent de la
traduction `qtbase_fr` livrée avec PyQt6, installée **seulement** en français — sinon elle
resterait d'une fenêtre à l'autre.

**Écrire un texte.** Quatre règles, vérifiées par `tests/test_i18n.py` :

1. un texte visible passe par `tr()` **au moment où il s'affiche**, jamais à l'import d'un
   module : la fenêtre se reconstruit dans le même processus, et un texte traduit à
   l'import resterait dans la langue précédente ;
2. une constante de module ou de classe se marque par `N_()`, qui ne fait rien, et se
   traduit là où elle s'affiche — `tr(self.TITLE)` ;
3. un gabarit garde ses marques, et sa traduction porte exactement les mêmes :
   `tr("%d fichier(s)") % n` ; une f-string devient un gabarit. Le pluriel passe par
   `plural(n, N_("%d mesure"), N_("%d mesures"))` : le français garde le singulier jusqu'à
   un (« 0 mesure »), l'anglais seulement pour un (« 0 bars ») ;
4. ce que l'application **écrit** — noms de clips d'un morceau (« Chords », « Build-up
   Bass »), dossiers d'un rangement par durée (« Under 1 s »), dossiers de sauvegarde,
   pistes et repères d'un export MIDI, nom de repli « SANS NOM » / « UNTITLED » — prend
   la langue de l'interface **au moment de l'écriture** : `tr()` s'applique là, sur une
   clé française qui ne change pas (`songwriter.part_label("Arpège")` → « Arpege » ou
   « Arpeggio », ASCII pour l'écran de la machine). Ce qui est déjà sur la carte ne
   change pas quand on change de langue. Les **identifiants**, eux, ne se traduisent pas
   (`untranslated()`) : clés comparées dans le code (parties « Accords », rôles de
   sections), balises XML, dossiers système, catégories « Bass » ou « Autre » gardées
   telles quelles dans l'index et traduites là où elles s'affichent. Le libellé d'une
   sauvegarde reste une clé dans son manifeste ; seul le nom de son dossier se traduit.

La traduction anglaise d'un module vit dans `i18n/en/`, dans le fichier nommé d'après lui
(`ui/pages/health.py` → `en/ui_pages_health.py`), listé dans `en.MODULES`. Une même phrase
a une seule traduction dans tout le catalogue ; deux sens différents s'écrivent donc
différemment en français (« Lecture impossible » joue un son ; « Lecture de l'échantillon
impossible » lit un fichier). `python tests/i18n_analyse.py <fichier>` liste ce qui manque
à un module et en donne le squelette.

**Les textes gardés.** Ce que l'index et l'historique conservent reste en français, quelle
que soit la langue : les anomalies réparées à la lecture d'un XML (`dxml`, marquées `N_`),
le résumé d'un kit (« 16 rangées »). La page Santé écarte les documents multi-racines en
cherchant « multi-racines » dans la note gardée : cette note ne doit pas changer avec la
langue. Ces textes se traduisent **à l'affichage** par `tr_stored()` : la clé exacte, ou le
gabarit dont le texte est issu, rempli avec les mêmes valeurs (« 70 '&' non échappé(s)
corrigé(s) » → « 70 unescaped '&' fixed »), morceau par morceau entre « ; ». Un gabarit de
moins de quatre lettres fixes (« %s à %s », « %s : %s ») reconnaîtrait n'importe quelle
phrase : il est écarté. Le journal (`app.log`) reste en français : il sert au diagnostic.

**Nombres, dates, unités, notes.** `decimal(1.5)` → « 1,5 » / « 1.5 » ; `integer(12345)` →
« 12 345 » / « 12,345 » ; `clock` → « 14h53 » / « 14:53 » ; `full_date` → « 15/10/2026 » /
« 15 Oct 2026 » (les mois anglais sont écrits dans le code : `strftime` suit la langue du
système, pas celle de l'interface) ; `human_size` → « 1,5 Mio » / « 1.5 MiB » ; les notes →
« Do3 Lam Sib3 » / « C3 Am Bb3 ». Lire un nom de note marche dans les deux langues.

**Mesures (19 octobre 2026).** 2 025 phrases traduites dans 54 fichiers. L'interface
anglaise, ses neuf pages et tous leurs onglets parcourus, montre 8 606 textes — libellés,
titres, infobulles, entrées de listes, en-têtes et premières lignes des tableaux — dont
**aucun** en français ; le même relevé en signale 459 distincts quand l'interface est en
français. Chaque bouton cliqué en anglais (barre d'état, boîtes, dialogues, sélecteurs de
fichiers : 2 538 textes) : aucun français ; 543 en français. Les commandes s'expliquent
aussi en anglais : le registre d'aide désigne un bouton par son libellé français, et
`sources()` retrouve ce libellé derrière l'anglais affiché.

## 6. Contraintes de robustesse

1. **L'application doit démarrer même sans carte SD valide** (toutes les pages affichent un
   `EmptyState` explicite).
2. Le scan d'une carte de 8 500 échantillons + 6 100 XML doit rester utilisable : progression
   affichée, annulable, < 3 minutes avec empreintes rapides.
3. Aucune exception non capturée ne doit atteindre la boucle Qt : chaque `refresh()` et chaque
   gestionnaire de signal enveloppe son corps dans `try/except` avec journalisation.
   **Et aucun résultat tardif ne doit réveiller une page éteinte** : un travail
   lancé dans un fil rend son résultat par un signal *mis en file*, qui peut
   être délivré après `AppContext.close()`. `AppContext.closed` le dit, et
   `Page.guard` s'arrête là. Sans ce rempart, le diagnostic de santé — qui
   part tout seul à l'affichage — laissait trois « Cannot operate on a
   closed database » dans le journal à chaque fermeture.
4. Toute écriture sur la carte passe par `dxml.save(..., backup=True)` si
   `settings.always_backup_before_write`.
5. Les listes de 8 500 lignes doivent utiliser `QAbstractTableModel` + `QTableView`
   (**jamais** `QTableWidget` pour ces volumes) avec tri et filtrage via `QSortFilterProxyModel`.

---

## 7. Tests (`tests/test_core.py`)

**Bac à sable obligatoire.** Les quatre premières lignes de chaque module de
test posent `DELUGE_COMPANION_CONFIG` sur un dossier temporaire, **avant tout
import de `delugeapp`** — qui calcule ses chemins à l'import. Elles sont
répétées dans chaque module, et non dans `tests/__init__.py` : `unittest
discover` charge les modules à plat, sans importer le paquet, et le garde-fou
posé dans le paquet ne protégeait donc rien de la commande réellement
employée. `MainWindow._settings_store` suit la même variable, pour que l'état
de fenêtre n'aille pas non plus dans le registre réel.

`TestDossierDeConfiguration.test_la_suite_n_ecrit_pas_chez_l_utilisateur`
échoue si on retire ces lignes — vérifié en les retirant.

Pourquoi tant de soin : mes propres essais ont trois fois modifié les
réglages réels de l'utilisateur, dont une fois en éteignant `confirm_writes`
et `always_backup_before_write`, les deux filets qui protègent une carte
contenant des mois de travail.

**Remplacer une méthode héritée : `mock.patch.object`.** Sauvegarder
`PlanDialog.exec` lit la méthode **héritée** de `QDialog` — le rempart de
la suite — et la réaffecter ensuite l'épingle sur `PlanDialog` : les tests
suivants qui neutralisent `QDialog.exec` ne touchent plus ce dialogue. Vu le
15 octobre 2026 sous pytest, qui suit l'ordre du fichier ; `unittest`, qui
trie les classes, le masquait. `WidgetCase._aucun_rempart_epingle` échoue
désormais dès qu'un test l'oublie, dans n'importe quel ordre.

**Éprouver un correctif en le retirant : sans `.pyc`.** Python juge un
`.pyc` à jour sur la taille et la *seconde* du source. Une mutation de même
longueur, restaurée dans la même seconde, laisse le code mutilé en cache :
lancer les essais avec `PYTHONDONTWRITEBYTECODE=1`.

`unittest` (stdlib). Doit passer sans carte SD (créer une carte factice dans un `tempfile.TemporaryDirectory`).
Couvrir : conversions fixed-point (aller-retour), réparation XML des 3 anomalies de §1.3,
lecture/écriture d'un preset (le XML réécrit doit se relire à l'identique), décodage des blobs de
notes (20 et 22 caractères), calcul du tempo, lecture/écriture WAV 16/24/32 bits,
gammes/accords, euclidien (E(3,8) = `x..x..x.`), génération de preset reproductible pour une
graine donnée, plan d'organisation en simulation qui ne touche à rien.
