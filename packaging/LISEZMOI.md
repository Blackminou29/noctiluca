# Construire et distribuer Noctiluca

Ce dossier fabrique ce que reçoivent les utilisateurs : un installateur pour
Windows, une image disque pour macOS, une AppImage pour Linux. Aucun d'eux
n'a besoin de Python : l'application et tout ce qu'elle emploie (Qt, numpy,
numba, PortAudio) sont dans le paquet.

| Système | Ce qu'on distribue | Où le construire |
|---|---|---|
| Windows 10 / 11, 64 bits | `Noctiluca-<version>-windows-x64-setup.exe` (NSIS, ~66 Mo) | ce PC, ou GitHub |
| macOS, Mac à puce Apple | `Noctiluca-<version>-macos-arm64.dmg` | un Mac, ou GitHub |
| Linux x86_64 | `Noctiluca-<version>-linux-x86_64.AppImage` (+ `.tar.gz`) | un Linux, ou GitHub |

Tout arrive dans `build/paquets/`. Le dossier `build/` n'est pas suivi par git.

PyInstaller ne construit que pour le système sur lequel il tourne : depuis
Windows, on ne fabrique que le paquet Windows. D'où la construction
automatique sur les machines de GitHub, plus bas, qui fait les trois.

## Windows, sur ce PC

Depuis la racine du projet :

```powershell
powershell -ExecutionPolicy Bypass -File packaging\construire-windows.ps1
```

Il faut Python 3.13 (lanceur `py`) et NSIS 3 (`winget install NSIS.NSIS`).
Compter cinq minutes ; `-Tests` lance d'abord la suite de tests (quatre de
plus). Le script crée son propre environnement Python (`build\venv-windows`)
aux versions exactes de `requirements-construction.txt`, sans toucher au
Python de tous les jours, et déplace la configuration de Noctiluca le temps
de la construction : vos réglages ne bougent pas.

L'installateur :

* installe pour tous les utilisateurs dans `Program Files` (demande les droits
  d'administrateur), parle français sous un Windows français, anglais ailleurs ;
* crée le raccourci du menu Démarrer, et celui du Bureau si la case reste cochée ;
* apparaît dans Paramètres ▸ Applications, avec son désinstallateur ;
* se met à jour par-dessus une version précédente, au même endroit ;
* refuse d'écrire tant que Noctiluca est ouvert ;
* relance Noctiluca à la fin **sans** les droits d'administrateur (une fenêtre
  élevée ne recevrait plus les fichiers glissés depuis l'Explorateur) ;
* s'installe aussi sans question : `setup.exe /S`, et `/D=C:\Chemin` pour le dossier.

Le désinstallateur retire ce que l'installateur a posé, fichier par fichier,
et **jamais** `%APPDATA%\Noctiluca` : réglages, index, sauvegardes de la carte.

## macOS et Linux, sur leur machine

```bash
bash packaging/construire-macos.sh     # sur un Mac
bash packaging/construire-linux.sh     # sur un Linux (paquets système : voir l'en-tête du script)
```

Même déroulé que sous Windows. Le paquet macOS vaut pour le processeur du Mac
qui le construit (arm64 sur un Mac à puce Apple). L'AppImage se lance sur les
distributions dont la bibliothèque C est au moins aussi récente que celle de
la machine qui la construit : la construire sur Ubuntu 22.04 couvre Ubuntu
22.04 et suivantes, Debian 12, Fedora 36 et suivantes.

## Les trois à la fois, par GitHub

`.github/workflows/paquets.yml` construit et vérifie les trois paquets sur
les machines de GitHub, gratuitement pour un dépôt public. Le dépôt :
**https://github.com/Blackminou29/noctiluca**.

1. chaque envoi sur `master` qui touche au code relance la construction
   (onglet **Actions**) ; une fois l'exécution terminée, les trois paquets
   sont à télécharger en bas de sa page ;
2. pour publier une version : monter `__version__` dans
   `delugeapp/__init__.py`, commiter, puis poser l'étiquette — dans GitHub
   Desktop, onglet *History*, clic droit sur le commit ▸ *Create Tag…*
   (`v1.1.0`), puis *Push origin* ; ou `git tag -a v1.1.0 -m "…"` et
   `git push --follow-tags`. Les paquets arrivent dans un **brouillon** de
   publication (onglet *Releases*), avec un texte d'accompagnement et le lien
   Ko-fi : le relire, puis *Publish release*.

Le bouton de don de la page du dépôt vient de `.github/FUNDING.yml`.

## L'autovérification

Chaque paquet est vérifié **avant** d'être emballé : l'application construite
est lancée avec `--self-test RAPPORT` (`delugeapp/autotest.py`). Elle refait
dans le paquet tout ce qui peut y manquer sans que rien ne le dise — modules,
catalogue anglais, manuel, tables du firmware, PortAudio, compilation du
moteur d'écoute par numba — puis ouvre et referme la fenêtre principale. Sa
configuration va dans un dossier temporaire, sans MIDI ni carte : on peut la
lancer sans risque chez un utilisateur dont l'application se comporte mal.
Le rapport : `build/autotest-<système>.txt`.

## Avant de distribuer

**La licence.** Noctiluca est distribué sous **GPL v3** (`LICENSE` à la
racine, choisi le 5 novembre 2026) : le paquet emporte PyQt6, sous GPL v3, et
le moteur d'écoute reprend des tables et des algorithmes du firmware du
Deluge, sous GPL v3 lui aussi. Chaque utilisateur peut recevoir le code
source, le modifier et le redistribuer. L'installateur Windows affiche la
licence, et celles des bibliothèques emportées sont jointes
(`_internal/licences/`, avec `AVIS-DE-TIERS.txt`).

**La signature.** Sans signature, Windows SmartScreen affiche « Windows a
protégé votre ordinateur » au premier lancement de l'installateur (l'utilisateur
doit cliquer « Informations complémentaires ▸ Exécuter quand même »), et
macOS refuse d'ouvrir l'application tant qu'elle n'est pas autorisée dans
Réglages Système ▸ Confidentialité et sécurité. Les deux scripts savent signer :

* Windows : un certificat de signature de code, puis
  `construire-windows.ps1 -Certificat <empreinte SHA-1>` ;
* macOS : le programme développeur d'Apple (99 $ par an), puis les variables
  `MACOS_SIGN_IDENTITY`, `APPLE_ID`, `APPLE_TEAM_ID`, `APPLE_APP_PASSWORD`
  (voir l'en-tête de `construire-macos.sh`). Ces deux chemins n'ont pas encore
  été essayés : faute de certificat, rien n'a pu l'être.

**Le lien MIDI n'existe que sous Windows.** `core/midiport.py` parle à
`winmm.dll`. Sous macOS et Linux, tout ce qui passe par le câble — écran
recopié, carte lue par USB, jeu en direct, pont vers le DAW joué par le
Deluge — reste éteint ; la carte s'y lit par un lecteur de cartes. Le manuel
le dit à l'utilisateur.

**Les noms.** L'éditeur affiché (« Sébastien Abalain ») est en tête de
`noctiluca.spec` et de `windows/noctiluca.nsi` ; l'identifiant macOS
(`fr.abalain.noctiluca`) dans `noctiluca.spec`. Celui-ci ne doit plus changer
une fois l'application distribuée : macOS y attache les autorisations
accordées par l'utilisateur.

**La version** vient de `delugeapp/__init__.py` (`__version__`) : les noms des
paquets, l'installateur et la fiche de l'exécutable la suivent.

## Les fichiers

| Fichier | Rôle |
|---|---|
| `requirements-construction.txt` | versions exactes de la construction |
| `icones.py` | `.ico`, `.icns`, `.png` et bandeau de l'installateur, tirés du dessin de l'application |
| `noctiluca.spec` | la recette PyInstaller, commune aux trois systèmes |
| `AVIS-DE-TIERS.txt` | composants tiers et leurs licences, joint au paquet |
| `construire-windows.ps1` | Windows : environnement, icônes, PyInstaller, autovérification, NSIS |
| `windows/noctiluca.nsi` | l'installateur NSIS |
| `construire-macos.sh`, `macos/entitlements.plist` | macOS : `.app`, notarisation, `.dmg` |
| `construire-linux.sh`, `linux/` | Linux : AppImage et archive |
| `../.github/workflows/paquets.yml` | les trois, sur les machines de GitHub |
