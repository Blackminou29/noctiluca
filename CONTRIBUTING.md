# Contribuer à Noctiluca — *Contributing to Noctiluca*

*English below.*

## Signaler un problème

Dans l'application : **Aide ▸ Signaler un problème…** prépare un rapport (version, système, fin du journal, votre dossier personnel remplacé par `~`), que vous relisez avant de l'envoyer. Il ouvre la page des tickets du dépôt, où vous le collez.

## Traduire l'interface

Le français est la langue source ; l'anglais est la seule traduction complète. Une troisième langue est bienvenue, mais elle demande un peu de code : voici exactement quoi.

### Comment le texte est rangé

- Tout texte visible s'écrit **en français** dans le code, dans `tr("…")` — ou `N_("…")` pour une constante traduite à l'affichage.
- Ses traductions vivent dans `delugeapp/i18n/en/`, **un fichier par module** du code : `ui_pages_samples.py` pour `delugeapp/ui/pages/samples.py`, `core_health.py` pour `delugeapp/core/health.py`. Chaque fichier définit `TEXTS`, un dictionnaire du français vers la langue. Les gabarits gardent leurs marques (`%s`, `%d`) dans le même ordre.
- La liste des fichiers est explicite : `MODULES`, dans `delugeapp/i18n/en/__init__.py` (une application empaquetée ne sait pas toujours lister ses propres modules).
- Le manuel est un fichier par langue : `delugeapp/docs/manuel.fr.md` et `manuel.en.md`, avec **les mêmes ancres** (`{#atelier}`), chapitres et figures. Chaque commande y est citée sous son libellé exact, entre crochets : `[Analyser la carte]`.

### Ce que vérifient les tests

`python -m unittest tests.test_i18n` échoue sur une clé sans traduction, une traduction orpheline, un gabarit qui perd ses marques, ou un texte visible écrit hors de `tr()`. `tests.test_ui.TestInterfaceEnAnglais` ouvre chaque page en anglais et y cherche du français ; `TestLeManuelDecritChaqueCommande` vérifie que chaque commande est décrite dans les deux manuels.

### Ajouter une langue

Aujourd'hui, le code ne connaît que `fr` et `en` :

1. `LANGUAGES`, dans `delugeapp/i18n/__init__.py` : ajouter le code et le nom de la langue, écrit dans la langue elle-même (« Deutsch »).
2. `catalogue()` et les règles de forme — pluriel, virgule décimale, séparateur des milliers, heure — testent aujourd'hui `_lang == "en"` : il faut les généraliser à la nouvelle langue.
3. Un dossier `delugeapp/i18n/<code>/`, copie de `en/` avec les mêmes fichiers et la même liste `MODULES`, et un `manuel.<code>.md`.
4. Les tests de `tests/test_i18n.py` qui parcourent `en/` doivent parcourir chaque langue.

Une traduction se relit **par quelqu'un qui joue du Deluge dans cette langue** : les termes suivent le manuel de la machine quand il les nomme (Mod FX, Arpeggiator…).

## Le code

Avant d'écrire une ligne, lisez `SPEC.md` (le contrat) et `REPRISE.md` (ce qui a été mesuré, et les pistes écartées). Rien sur le format des fichiers du Deluge ne se code sans avoir été mesuré sur une vraie carte, ou lu dans le code du firmware de la version visée. La suite : `python -m unittest discover -s tests`.

---

## Reporting a problem

In the application: **Help ▸ Report a problem…** prepares a report (version, system, end of the log, your home folder replaced by `~`) that you read before sending it. It opens the repository's issues page, where you paste it.

## Translating the interface

French is the source language; English is the only complete translation. A third language is welcome, but it needs a little code — here is exactly what.

- Every visible text is written **in French** in the code, inside `tr("…")` — or `N_("…")` for a constant translated when shown.
- Its translations live in `delugeapp/i18n/en/`, **one file per code module**, each defining `TEXTS` (French → language). Templates keep their markers (`%s`, `%d`) in the same order. The file list is explicit: `MODULES` in `delugeapp/i18n/en/__init__.py`.
- The manual is one file per language (`delugeapp/docs/manuel.fr.md`, `manuel.en.md`) with **the same anchors**, chapters and figures; every command is quoted by its exact label in brackets.
- `python -m unittest tests.test_i18n` fails on a missing or orphan translation, a template that loses its markers, or a visible text outside `tr()`.

To add a language: add it to `LANGUAGES` (`delugeapp/i18n/__init__.py`); generalise `catalogue()` and the form rules (plural, decimal comma, thousands separator, time), which test `_lang == "en"` today; create `delugeapp/i18n/<code>/` with the same files as `en/`, and `manuel.<code>.md`; make the tests walk every language. A translation should be proofread **by someone who plays the Deluge in that language**.

## The code

Read `SPEC.md` (the contract) and `REPRISE.md` (what was measured, and the paths ruled out) first. Nothing about the Deluge's file formats is coded without being measured on a real card or read in the firmware source of the targeted version. The suite: `python -m unittest discover -s tests`.
