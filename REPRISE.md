# Point d'étape — Deluge Companion

**Dernière mise à jour :** 20 septembre 2026, ~23 h 55
**Objet :** où en est la construction de l'application, et comment reprendre si la session est interrompue.

---

## 1. Ce qu'est le projet

Application Python (PyQt6) accompagnant l'utilisation d'un Synthstrom Deluge :
gestion complète de la carte SD (échantillons, presets, kits, morceaux), générateur de
presets de synthé par genre musical ou aléatoire, et boîte à outils de production
électronique. Interface en français, identité visuelle reprise du *Guide du Deluge OLED*.

**Le contrat d'architecture complet est dans [`SPEC.md`](SPEC.md)** (1 083 lignes) :
signatures exactes de tous les modules, format XML du Deluge, palette graphique,
description de chacune des 9 pages. C'est le document de référence — il a été rédigé à
partir de mesures faites sur la vraie carte, pas de suppositions.

---

## 2. Faits techniques acquis (mesurés sur `SDCARD Deluge`, 5,3 Go)

Ces constats ont coûté du temps à établir ; ils sont détaillés au §1 de `SPEC.md`.

- **Volume réel** : 8 491 fichiers `.wav`, 6 115 fichiers `.XML` (954 presets et kits).
- **Deux dialectes XML coexistent** : firmware 2.x écrit `<type>saw</type>`,
  firmware 3.0+ écrit `type="saw"`. Il faut lire les deux et **préserver celui d'origine**
  en écriture.
- **14 % des XML de la carte sont invalides** pour un parseur strict. Trois causes réelles :
  1. documents **multi-racines** (`<firmwareVersion>` frère de `<sound>` en firmware 2.x) ;
  2. **`&` non échappé** dans les attributs (`fileName=".../Tenor & Alto Sax G2.wav"`) ;
  3. **octets non-UTF-8** dans les noms de périphériques MIDI.
  Le parseur tolérant de `core/dxml.py` ramène l'échec à ~0,1 %.
- **La casse des chemins d'échantillons n'est pas fiable** : les XML référencent
  `SAMPLES/Multisamples/…` alors que le dossier réel est `SAMPLES/MULTISAMPLES`.
  FAT32 s'en moque, Python non → toute résolution doit être insensible à la casse,
  sinon la détection d'échantillons manquants produit des centaines de faux positifs.
- **Format des notes décodé** : `noteDataWithLift` = **22 caractères hexadécimaux par note**
  (pos 8, longueur 8, vélocité 2, condition 2, lift 2) ; `noteData` = 20 caractères.
  Résolution : 24 ticks par noire, 96 ticks par mesure.
- **Paramètres en virgule fixe** : entiers 32 bits signés, `0x80000000` = minimum,
  `0x00000000` = milieu, `0x7FFFFFFF` = maximum, affichés 0–50 sur la machine.

---

## 3. État de la construction

La construction est menée par un *workflow* de 21 agents répartis en 5 phases successives
(chaque phase attend la précédente, parce qu'elle code contre le code réellement produit).

| Phase | Contenu | État |
|---|---|---|
| **1 — Fondations** | `fixedpoint`, `dxml`, `sdcard`, `model`, `wav`, `audio_out`, `config`, `theme`, `icons`, `tasks` | **en cours** |
| 2 — Services | `db`+`scan`, `analysis`, `deps`+`organize`, `health`+`backup`, `genres`+`synthgen`, `kitgen`+`render`, `theory`+`rhythm`+`midifile` | en attente |
| 3 — Widgets | `common`, `padgrid`, `waveform`, `envelope`, `knob`, `piano`, `filtercurve` | en attente |
| 4 — Pages | tableau de bord, échantillons, presets, kits, morceaux, générateur, outils, santé, réglages | en attente |
| 5 — Intégration | `mainwindow`, `main.py`, tests, README, résolution des écarts d'API, captures de contrôle | en attente |

### Fichiers déjà écrits

```
SPEC.md                        1083  contrat d'architecture (référence)
delugeapp/config.py             388  Settings + AppContext, persistance JSON
delugeapp/core/fixedpoint.py    212  conversions virgule fixe Deluge
delugeapp/core/dxml.py          713  lecture/écriture XML tolérante (les 3 anomalies)
delugeapp/core/model.py        1103  Sound/Osc/Kit/Song/Clip/Note ↔ XML
delugeapp/core/wav.py          1094  lecteur/écrivain WAV + AIFF sans dépendance
```

Restent à écrire : `audio_out.py`, `theme.py`, `icons.py`, `tasks.py`, puis toutes les
phases 2 à 5 (≈ 30 fichiers).

---

## 4. Comment reprendre

### 4.1 Reprendre le workflow là où il s'est arrêté

Le workflow est repris via son script et son identifiant d'exécution ; les agents déjà
terminés renvoient leur résultat en cache et ne sont pas relancés :

- **Script :** `C:\Users\sebas\.claude\projects\C--Users-sebas-Desktop-Informatique-Deluge-app\83d2c5f0-1ed7-4498-b517-a9a7536dffcc\workflows\scripts\build-deluge-companion-wf_eb4a9994-d6c.js`
- **Run ID :** `wf_eb4a9994-d6c`

Dans une nouvelle session Claude Code, demander : *« reprends le workflow
`wf_eb4a9994-d6c` à partir de son script »*.

### 4.2 Reprendre sans le workflow

`SPEC.md` est auto-suffisant. Chaque module y a ses signatures exactes ; il suffit de
demander l'implémentation des fichiers manquants en indiquant :

> Lis `SPEC.md` et implémente `<liste de fichiers>` en respectant les signatures à la lettre.
> Vérifie sur la vraie carte `SDCARD Deluge`.

L'ordre des dépendances est celui du tableau du §3.

### 4.3 Vérifier l'état du code

```bash
cd "C:\Users\sebas\Desktop\Informatique\Deluge app"
"C:/Users/sebas/AppData/Local/Programs/Python/Python313/python.exe" -c "import delugeapp.core.dxml, delugeapp.core.model, delugeapp.core.wav; print('ok')"
```

L'application ne démarre pas encore : `main.py` et `delugeapp/ui/mainwindow.py`
sont produits en phase 5.

---

## 5. Environnement

- **Python recommandé :** `C:\Users\sebas\AppData\Local\Programs\Python\Python313\python.exe`
  (PyQt6 6.11, numpy 2.2.6, matplotlib, sounddevice, Pillow déjà installés).
- **Dépendances obligatoires :** PyQt6, numpy. Tout le reste est optionnel et protégé
  par `try/except ImportError` (notamment `sounddevice` : sans lui, repli sur `winsound`).
- **Carte SD de travail :** `SDCARD Deluge/` — 5,3 Go, **exclue de git** (`.gitignore`).
  Le chemin est modifiable depuis les réglages de l'application, comme demandé.
- **Identité graphique :** palette reprise de
  `C:\Users\sebas\Desktop\Informatique\Guide deluge\build\style.py`
  (`PANEL #1C1F26`, or `#C79A22`, 12 couleurs de pads).

---

## 6. Précaution

Aucun code de l'application n'écrit sur la carte SD sans confirmation : toutes les
opérations de réorganisation sont conçues en *simulation par défaut* (`apply=False`) et
toute écriture XML crée une sauvegarde `.bak` horodatée. Cette règle est au §0 de `SPEC.md`
et doit être maintenue par toute reprise.
