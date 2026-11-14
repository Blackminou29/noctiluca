# Améliorations possibles — Noctiluca

**Relevé du 7 novembre 2026**, tenu à jour depuis. **Une ligne s'efface dès que la tâche est faite** ; le détail de ce qui a été fait, mesuré et vérifié est dans `REPRISE.md` (§3 quinquagies et suivants). Il ne reste ici que ce qui n'est pas fait.

---

## 1. À signaler au firmware

### 1.1 Le nom de contrôleur fait de 0xFF

Un contrôleur Novation branché sur le Deluge (vendorId 0x1235) est enregistré avec un nom de **32 octets 0xFF** (`ATELIER AMBIENT`, `Truc 1`). Vérifié dans le code de la 1.3.0 : le pilote USB remplit son tampon de 0xFF avant de demander le nom de l'appareil, puis le recopie sans vérifier qu'un descripteur est arrivé (`r_usb_hmidi_driver.c`). Le signalement, en anglais et prêt à poster, est dans `C:\Users\sebas\dfw\ISSUE-nom-0xFF.md`. **À poster par toi** sur le dépôt DelugeFirmware : c'est ton compte.

### 1.2 L'horloge d'un DAW sous Windows 11

Le correctif du firmware (un octet temps réel reçu sous le code USB 0x5) est proposé au dépôt officiel : [#5276](https://github.com/SynthstromAudible/DelugeFirmware/pull/5276). À suivre : l'autorisation de ses vérifications par un mainteneur, leurs remarques, et l'étiquette « backport: release/1.3 » qu'eux seuls peuvent poser. Tant qu'il n'est pas dans une version officielle, une mise à jour officielle du firmware le retirera de ta machine ; en attendant, c'est le Deluge qui mène l'horloge.

---

## 2. L'écoute sur le PC : ce qui reste approché

* l'étirement des échantillons ;
* le balayage d'une table d'onde (on entend le cycle de la position) ;
* de l'arpégiateur, ce qui tire au sort ou découpe le pas (rythmes, longueur de séquence, « ratchets », probabilités, accords, étalements), le mode « pattern » et la vitesse libre (non synchronisée) : l'écoute joue le cœur — pas, ordres des notes et des octaves, répétitions, durée.

Mesuré le 8 novembre sur ta carte : **aucun son ne s'en sert** (`timeStretchEnable` à 0 dans les 1 205 sons à échantillon, aucune table d'onde, aucun arpégiateur allumé). Ce qui se porte se vérifie contre une transcription du code du firmware, comme les autres étages ; l'écoute sur la machine, elle, attend un son qui s'en serve.

---

## 3. Diffusion et maintenance

### 3.1 Les tests sur GitHub

Au prochain passage sur GitHub (Windows, macOS, Linux) : vérifier que l'interblocage entre Qt et Python corrigé le 9 novembre ne revient pas, et que les tests du hub MIDI passent hors de Windows (corrigés le 14 novembre, vérifiés ici seulement en simulant une machine sans MIDI). Journal lisible seulement par toi, connecté.

### 3.2 Le MIDI hors Windows

Le MIDI ne passe que par `winmm` ([midiport.py](delugeapp/core/midiport.py)). Les paquets Mac et Linux ne parlent donc pas au Deluge branché : ni copie de travail par USB, ni écoute sur la machine, ni hub. Deux voies : `python-rtmidi` (une dépendance, dont le paquet pour Python 3.13 sous Linux n'est pas assuré), ou CoreMIDI et ALSA par `ctypes`, comme pour `winmm`. Dans les deux cas, il faut un Mac ou un Linux avec le Deluge : les noms de ses ports ne se mesurent qu'avec la machine. De même pour le routage « MIDI To » des sets Live (`Dev:Deluge{16D0-0CE2-0-out-0}`, mesuré sous Windows seulement).

### 3.3 L'installateur et la signature

Jamais essayés : la désinstallation ; le refus quand l'application est ouverte ; les paquets Mac et Linux chez un vrai utilisateur. Les essais demandent ta présence (fenêtre UAC). La signature évite l'avertissement SmartScreen ; la demande à la fondation SignPath vient de l'auteur (`packaging/LISEZMOI.md`).

### 3.4 Plus loin

* **Une troisième langue** : l'allemand ou le japonais, où la communauté du Deluge est importante. Le guide des traducteurs est écrit (`CONTRIBUTING.md`) ; il manque quelqu'un qui joue du Deluge dans cette langue.
* **Découper les tests** : `test_core.py` dépasse 13 000 lignes.

---

## 4. Ce que les essais du 9 novembre ont laissé ouvert

* **Le Deluge s'est figé** après l'envoi du pack (77 fichiers en 299 s) ; Windows a perdu l'appareil, il a fallu le redémarrer. Cause inconnue. À surveiller au prochain gros envoi : si cela se reproduit, envoyer par lots plus petits.
* **Ensuite, plus aucune note ne passait**, alors que les SysEx répondaient. Après le redémarrage du service MIDI de Windows (`Restart-Service midisrv`, en administrateur), tout est revenu, sans preuve que ce soit lui. Si cela se reproduit : redémarrer ce service, ou le PC, et le noter.

---

## 5. Ce qui attend la machine et ton accord

* **Un favori posé sur la machine**, puis retrouvé dans l'application.
* **Outils ▸ [Firmware du Deluge…]** le jour d'une nouvelle version stable : la machine s'installe-t-elle avec le `.bin` posé ?
* **L'atelier** : charger « Calm Down 2 » complété.
* **L'atelier** : écrire un morceau dont le **volume d'une piste** a été réglé, avec un **clip doublé** et un coup **doux** (vélocité 40), et l'entendre sur la machine.
* **L'automation** : écrire depuis l'atelier un morceau avec [Montée du filtre] sur une section, et l'entendre s'ouvrir sur la machine (format lu dans le firmware et sur ta carte, jamais encore joué par elle depuis l'atelier).
* **Les conditions des notes** : écrire depuis l'atelier un morceau dont la batterie porte une note à 50 %, une charley « 2 sur 2 » ([Varier] ▸ vivante) et un roulement FILL, puis l'écouter sur la machine. Pour le roulement : **régler d'abord SETTINGS ▸ COMMUNITY FEATURES ▸ Sync Scaling Action ▸ Fill mode** (sur ta carte, il est sur « Sync Scaling »).
* **L'écoute de ce qui vient d'être porté** (14 novembre), comparée à la machine sur un même son : un **arpège** (accord tenu, modes « up » puis « upDown », deux octaves), un **filtre SVF** (passe-bas « notch » puis passe-haut « band »), un **tape warble**, et un morceau dont le **compresseur maître** a un seuil réglé. Ta carte n'en contient aucun : il faut les régler sur la machine, sauver, puis écouter le même morceau dans la page Morceaux.
* **Le hub MIDI**, éprouvé sur des ports simulés seulement :
  * **Un clavier USB sur le Deluge** : page Hub MIDI ([[Ctrl+M]]), [Brancher sur le Deluge] ; jouer dans un clip de synthé, puis de kit (à partir de la note 36) ; la molette, la pédale ; débrancher le clavier en tenant une note — elle doit s'éteindre.
  * **Le retard réel** par `winmm` : le moniteur (mode avancé) l'affiche.
  * **Une surface et ses boutons** : [Apprendre un bouton], le poser sur « Fréquence du filtre » ; ton Takeover est en Pickup, le bouton doit croiser la valeur avant de la prendre.
  * **Deux surfaces sur deux pistes** : SHIFT + SELECT ▸ MIDI ▸ MIDI-Follow ▸ Channel ▸ Channel Track 1 et 2, laisser la carte se synchroniser, puis « La piste 1 » et « La piste 2 » dans la fiche.
  * **Avec Live** : un port en boucle (outils de Windows MIDI Services, ou loopMIDI) doit paraître dans la grille ; y brancher le clavier, le choisir comme entrée dans Live.
* **Relectures** : le manuel devant la machine (surtout la partie III), et l'anglais par quelqu'un qui joue du Deluge en anglais.
* **Rappels** : *Display Param* est peut-être resté allumé (MIDI-Follow ▸ Display Param). Sur la carte restent, de nos essais : `SONGS/Cool1 DAW.XML` et `SAMPLES/RESAMPLE/ESSAI SIDECHAIN/output_000.wav`. Sur le PC, dans `Desktop\musique\Cool1 — pour le DAW` : les trois sets Live de l'essai. Sur le Deluge, SETTINGS ▸ MIDI ▸ Clock ▸ Output est sur ON, et le firmware est la 1.3.0 corrigée ; l'officiel est rangé dans `_BACKUP/firmware-20261109-111704` de la copie de travail. `C:\Users\sebas\dfw` (≈ 2 Go) sert encore si les relecteurs de #5276 demandent une retouche ; à supprimer ensuite.
