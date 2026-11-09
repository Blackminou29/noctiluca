# Améliorations possibles — Noctiluca

**Relevé du 7 novembre 2026**, sur `master` (`c28827d`, v1.0.0 publiée), complété le soir même, repris le 8 novembre, puis le 9 après les essais sur la machine.

Les pistes faites ont été retirées. Leur détail (ce qui a été fait, mesuré et vérifié) est dans `REPRISE.md` : au §3 quinquagies pour le 7 novembre, au §3 unquinquagies pour le 8, au §3 duoquinquagies pour les essais du 9. Il ne reste ici que ce qui n'est pas fait, avec la raison. Tout ce qui reste attend la machine, ta décision, ou quelqu'un d'autre.

---

## 1. À signaler au firmware

### 1.1 Le nom de contrôleur fait de 0xFF

Un contrôleur MIDI appris sur la machine est enregistré avec un nom de **32 octets 0xFF** (`<device name="ÿÿÿ…">`, dans `ATELIER AMBIENT` et `Truc 1`). L'application le tolère. Il ressemble pourtant à un défaut du firmware : un nom d'appareil jamais initialisé. Il serait à signaler sur le dépôt DelugeFirmware, après vérification dans le code de la 1.3.0. **Par toi** : c'est ton compte.

### 1.2 L'horloge d'un DAW sous Windows 11

Mesuré le 9 novembre : le Deluge joue les notes de Live, mais ignore son horloge, son Start et son Stop. Le pilote USB MIDI 2 de Windows les envoie avec le code USB **0x5** au lieu de **0xF** ; le firmware prend tout code inférieur à 8 (hors 2 et 3) pour un morceau de SysEx et le jette (`MidiEngine::checkIncomingUsbMidi`). Microsoft a écrit le correctif (`Device.cpp` de microsoft/MIDI : « Some devices ignore it sent as CIN 0x5 »), mais il attend son drapeau de déploiement (`Feature_Servicing_MIDI2USBSystemRealTimeCin`). En attendant, c'est le Deluge qui mène ; le mode d'emploi de la page DAW et le manuel le disent.

**Le correctif du firmware est fait et vérifié** (REPRISE §3 duoquinquagies) : un octet temps réel reçu sous le code 0x5 est pris comme temps réel, et ne coupe plus un SysEx en cours. Compilé sur la 1.3.0, installé sur ta machine : Live mène, le Deluge démarre, suit le tempo et s'arrête ; 3 122 pings SysEx sur 3 122 reviennent sous l'horloge.

**Proposé au dépôt officiel le 9 novembre** : [#5276](https://github.com/SynthstromAudible/DelugeFirmware/pull/5276), étiqueté automatiquement « area: midi » et « type: fix ». Ses vérifications (compilation, mise en forme, tests) attendent qu'un mainteneur les autorise, comme pour tout premier contributeur. À suivre : leurs remarques, et l'étiquette « backport: release/1.3 » qu'eux seuls peuvent poser. Tant qu'il n'est pas dans une version officielle, une mise à jour officielle du firmware le retirera de ta machine.

---

## 2. L'écoute sur le PC : ce qui reste approché

Le sidechain, le LFO 1 global et le glissé en fréquence sont portés du firmware depuis le 8 novembre ; le sidechain a été comparé à la machine le 9 (26,3 % contre 26,6 %). Restent approchés :

* l'étirement des échantillons ;
* le filtre SVF ;
* le « tape warble » ;
* le limiteur du compresseur maître ;
* le balayage d'une table d'onde (on entend le cycle de la position).

L'arpégiateur n'a pas été vérifié sur la machine.

**Pourquoi ils restent** : mesuré le 8 novembre sur ta carte, **aucun son ne s'en sert**. `timeStretchEnable` est à 0 dans les 1 205 sons à échantillon, aucun filtre n'est en SVF, aucun mod FX n'est un « warble », aucun oscillateur n'est une table d'onde, aucun arpégiateur n'est allumé. Les porter à l'aveugle n'apporterait rien d'audible chez toi, et rien ne permettrait de les vérifier.

---

## 3. Diffusion et maintenance

### 3.1 Le premier passage des tests sur GitHub

Le workflow lance la suite sur Windows, macOS et Linux. Premier passage le 9 novembre (commit de la 1.0.1), journal lu grâce à toi : quatre échecs, **corrigés** (à revoir au passage suivant sur GitHub, macOS compris) —

* Linux : un nom de morceau pris ne se voyait pas s'il différait par la casse (« Essai.XML » contre « ESSAI.XML »), alors que la FAT du Deluge les confond : **vrai défaut**, aussi pour les instruments, découpes, tables d'onde et firmware — `SDCard.exists`, casse confondue ;
* Linux : un dossier « pesait » 4 096 octets (`units.file_size` : 0 hors fichier) ;
* Windows de GitHub : le synthé GS de Microsoft déclaré mais impossible à ouvrir (pas de service audio) — le test passe son tour **seulement là** ;
* Windows de GitHub : l'étape des clips a dépassé le délai de garde de 2 minutes et arrêté la suite — 10 minutes sur GitHub.

macOS n'a pas encore tourné (machines macos-14 retirées par GitHub, passé à macos-15 pour la 1.0.2). L'étape signale sans bloquer les paquets.

### 3.2 Le MIDI hors Windows

Le MIDI ne passe que par `winmm` ([midiport.py](delugeapp/core/midiport.py)). Les paquets Mac et Linux ne parlent donc pas au Deluge branché : ni copie de travail par USB, ni écoute sur la machine. Deux voies :

* `python-rtmidi` : une dépendance de plus, que le module refuse par principe, et dont le paquet pour Python 3.13 sous Linux n'est pas assuré. La construction des trois paquets pourrait casser ;
* CoreMIDI et ALSA par `ctypes`, comme pour `winmm` : sans dépendance, mais plus long à écrire.

Dans les deux cas, il faut un Mac ou un Linux avec le Deluge : les noms de ses ports sur ces systèmes ne se mesurent qu'avec la machine. Il en va de même pour le routage « MIDI To » des sets Live : l'identifiant de la sortie du Deluge (`Dev:Deluge{16D0-0CE2-0-out-0}`) n'a été mesuré que sous Windows.

### 3.3 L'installateur et la signature

Jamais essayés (REPRISE §3 octoquadragies et novoquadragies) :

* la désinstallation ;
* la mise à jour par-dessus la 1.0.0 ;
* le refus quand l'application est ouverte ;
* les paquets Mac et Linux chez un vrai utilisateur.

À essayer avec l'installateur de la 1.0.2 (la mise à jour par-dessus la 1.0.0 en premier) : les essais demandent ta présence (fenêtre UAC). La signature évite l'avertissement SmartScreen, et la demande à la fondation SignPath vient de l'auteur. La marche à suivre est dans `packaging/LISEZMOI.md`.

### 3.4 Plus loin

* **Une troisième langue** : l'allemand ou le japonais, où la communauté du Deluge est importante. Le guide des traducteurs est écrit (`CONTRIBUTING.md`) ; il manque quelqu'un qui joue du Deluge dans cette langue.
* **Découper les tests** : `test_core.py` dépasse 13 000 lignes et la suite complète prend près de 5 minutes. Écarté pour l'instant : le gain est faible, et l'on risque de casser les garde-fous de chaque module.
* **Convertir le FLAC et le MP3 à l'envoi** : « Envoyer au Deluge » les écarte en conseillant de les exporter en WAV ([cardimport.py](delugeapp/core/cardimport.py)). Les convertir demanderait une dépendance (`soundfile`). À ne faire que si des utilisateurs le demandent : ton journal n'en montre aucun cas.
* **Écouter un morceau entier plus vite** : un quart de minute de calcul pour un morceau de trois minutes, et le LFO 1 global en ajoute 40 % sur les morceaux de l'atelier. Jouer le début pendant que la suite se calcule demanderait un lecteur qui reçoit le son par morceaux.

---

## 4. Ce que les essais du 9 novembre ont laissé ouvert

* **Le Deluge s'est figé** après l'envoi du pack (77 fichiers en 299 s, fini à 08:16:30) ; Windows a perdu l'appareil, il a fallu le redémarrer. Cause inconnue. À surveiller au prochain gros envoi : si cela se reproduit, envoyer par lots plus petits.
* **Ensuite, plus aucune note ne passait** (ni de Live, ni de l'application), alors que les SysEx répondaient en 0,4 ms. Ni le rebranchement du câble ni la fermeture des logiciels n'y ont rien changé. Après le redémarrage du service MIDI de Windows (`Restart-Service midisrv`, en administrateur), tout est revenu, sans que l'on puisse prouver que c'est lui. Si cela se reproduit : redémarrer ce service, ou le PC, et le noter.
* **La santé est passée de 92 à 90** (11 anomalies au lieu de 9) après les essais. Probablement les fichiers d'essai (l'export du sidechain dans `SAMPLES/RESAMPLE`, un dossier `SAMPLES/ESSAI COMPANION` resté vide dans la copie de travail) : à regarder.

---

## 5. Ce qui attend encore la machine et ton accord

* **Un favori posé sur la machine**, puis retrouvé dans l'application (le sens application → machine est vérifié).
* **Outils ▸ [Firmware du Deluge…]** le jour d'une nouvelle version stable : la machine s'installe-t-elle avec le `.bin` posé ?
* **L'atelier** : charger « Calm Down 2 » complété.
* **Relectures** : le manuel devant la machine (surtout la partie III), et l'anglais par quelqu'un qui joue du Deluge en anglais.
* **Rappels** : *Display Param* est peut-être resté allumé (MIDI-Follow ▸ Display Param). Sur la carte restent, de nos essais : `SONGS/Cool1 DAW.XML` (la copie pour Live) et `SAMPLES/RESAMPLE/ESSAI SIDECHAIN/output_000.wav` (l'export du sidechain). Sur le PC, dans `Desktop\musique\Cool1 — pour le DAW` : les trois sets Live de l'essai. Sur le Deluge, SETTINGS ▸ MIDI ▸ Clock ▸ Output est sur ON, et le firmware est la 1.3.0 corrigée (« 1.3.0-dev-156500e-dirty ») ; l'officiel est rangé dans `_BACKUP/firmware-20261109-111704` de la copie de travail. `C:\Users\sebas\dfw` (≈ 2 Go : le firmware cloné et sa chaîne de compilation) sert encore si les relecteurs de #5276 demandent une retouche ; à supprimer ensuite.

---

## Ordre proposé

1. **Les tests sur GitHub** (3.1 : ils échouent sous Linux, à lire dans le journal de l'exécution) et **l'installateur** (3.3), avec la construction de la 1.0.2.
2. **Les points ouverts par les essais** (§4) : la santé, puis la surveillance du prochain gros envoi.
3. **L'horloge sous Windows** (1.2) : suivre la proposition #5276 jusqu'à son acceptation.
4. **Le MIDI sur Mac et Linux** (3.2), quand un Mac ou un Linux sera à portée avec le Deluge.
