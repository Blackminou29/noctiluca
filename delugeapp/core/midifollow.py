# -*- coding: utf-8 -*-
"""MIDI Follow : piloter l'instrument sélectionné sur le Deluge.

Le firmware communautaire propose un mode **MIDI Follow** : les contrôleurs
reçus agissent sur l'instrument actuellement sélectionné sur la machine, quel
qu'il soit. La correspondance « paramètre -> numéro de contrôleur » est un
fichier de la carte, ``MIDIFollow.XML``, que l'utilisateur peut modifier.

Ce module lit ce fichier et le traduit dans le vocabulaire de
``core/model.py``, pour qu'un preset de l'application puisse être **envoyé
tel quel** à la machine : les réglages affichés par le générateur deviennent
les réglages du son qui sonne.

Mesuré sur la carte de l'utilisateur (firmware communautaire c1.2.1)
---------------------------------------------------------------------

56 entrées, dont :

* **31 portent déjà le nom de l'application** (``lpfFrequency``, ``pan``,
  ``reverbAmount``, ``modFXDepth``…) ;
* **23 demandent une traduction** (``volumePostFX`` -> ``volume``,
  ``oscAPitch`` -> ``oscAPitchAdjust``, ``arpGate`` -> ``arpeggiatorGate``,
  les huit segments d'enveloppe, les deux fréquences de l'égaliseur…) ;
* **3 n'ont pas d'équivalent** dans le modèle : ``modulator1Pitch``,
  ``modulator2Pitch`` et ``volumePostReverbSend``. Elles sont déclarées
  ici pour mémoire, et simplement ignorées ;
* **1 n'a pas de contrôleur** : ``stutterRate`` vaut 255, hors de la plage
  0..127. Une valeur supérieure à 127 veut dire « non assigné », et doit
  être écartée — l'envoyer produirait un message illégal.

Le fichier n'est pas une garantie : l'utilisateur peut avoir changé ses
assignations, et une autre carte en aura d'autres. On lit donc toujours la
carte quand elle est là, et les valeurs ci-dessous ne servent que de repli.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .fixedpoint import INT32_MAX, INT32_MIN, to_unit

log = logging.getLogger(__name__)

__all__ = [
    "FOLLOW_FILE", "DEFAULT_CC", "FOLLOW_TO_PARAM", "SANS_EQUIVALENT",
    "load_map", "cc_value", "sound_messages",
]

#: Nom du fichier, à la racine de la carte.
FOLLOW_FILE = "MIDIFollow.XML"

#: Correspondances par défaut du firmware, **relevées sur la carte réelle**.
#: Clés : les noms du firmware, tels qu'ils apparaissent dans le fichier.
DEFAULT_CC: dict[str, int] = {
    "oscAVolume": 21, "oscAPitch": 12, "oscAPhaseWidth": 23,
    "carrier1Feedback": 24, "oscAWavetablePosition": 25, "noiseVolume": 41,
    "oscBVolume": 26, "oscBPitch": 13, "oscBPhaseWidth": 28,
    "carrier2Feedback": 29, "oscBWavetablePosition": 30,
    "modulator1Volume": 54, "modulator1Pitch": 14, "modulator1Feedback": 55,
    "modulator2Volume": 56, "modulator2Pitch": 15, "modulator2Feedback": 57,
    "stutterRate": 255, "volumePostFX": 7, "pitch": 3, "pan": 10,
    "sampleRateReduction": 63, "bitcrushAmount": 62, "portamento": 5,
    "waveFold": 19, "env1Release": 72, "env1Sustain": 76, "env1Decay": 75,
    "env1Attack": 73, "lpfMorph": 70, "lpfResonance": 71, "lpfFrequency": 74,
    "env2Release": 80, "env2Sustain": 79, "env2Decay": 78, "env2Attack": 77,
    "hpfMorph": 83, "hpfResonance": 82, "hpfFrequency": 81,
    "volumePostReverbSend": 61, "compressorShape": 60, "bass": 86,
    "bassFreq": 84, "arpRate": 51, "arpGate": 50, "treble": 87,
    "trebleFreq": 85, "lfo1Rate": 58, "modFXOffset": 18, "modFXFeedback": 17,
    "modFXDepth": 93, "modFXRate": 16, "lfo2Rate": 59, "reverbAmount": 91,
    "delayRate": 53, "delayFeedback": 52,
}

#: Nom du firmware -> clé de ``core/model.py``.
#:
#: Les enveloppes s'écrivent ``env1.attack`` : elles ne vivent pas dans
#: ``Sound.params`` mais dans ``Sound.env1`` et ``Sound.env2``.
FOLLOW_TO_PARAM: dict[str, str] = {
    "oscAPitch": "oscAPitchAdjust",
    "oscAPhaseWidth": "oscAPulseWidth",
    "oscBPitch": "oscBPitchAdjust",
    "oscBPhaseWidth": "oscBPulseWidth",
    "modulator1Volume": "modulator1Amount",
    "modulator2Volume": "modulator2Amount",
    "volumePostFX": "volume",
    "pitch": "pitchAdjust",
    "bitcrushAmount": "bitCrush",
    "bassFreq": "bassFrequency",
    "trebleFreq": "trebleFrequency",
    "arpRate": "arpeggiatorRate",
    "arpGate": "arpeggiatorGate",
    "env1Attack": "env1.attack",
    "env1Decay": "env1.decay",
    "env1Sustain": "env1.sustain",
    "env1Release": "env1.release",
    "env2Attack": "env2.attack",
    "env2Decay": "env2.decay",
    "env2Sustain": "env2.sustain",
    "env2Release": "env2.release",
}

#: Paramètres du firmware sans équivalent dans le modèle de l'application.
#: Déclarés pour que leur absence soit un choix lisible, et non un oubli.
SANS_EQUIVALENT: frozenset[str] = frozenset({
    "modulator1Pitch",       # hauteur du modulateur FM : pas lue par le modèle
    "modulator2Pitch",
    "volumePostReverbSend",  # volume avant réverbération, distinct de `volume`
})


def _param_key(nom_firmware: str) -> str:
    """Clé de l'application pour un nom du firmware, ou chaîne vide."""
    if nom_firmware in SANS_EQUIVALENT:
        return ""
    return FOLLOW_TO_PARAM.get(nom_firmware, nom_firmware)


def load_map(card=None, path: Path | None = None) -> dict[str, int]:
    """Carte « clé de l'application -> numéro de contrôleur ».

    :param card: une :class:`~delugeapp.core.sdcard.SDCard`, dont on lira le
        ``MIDIFollow.XML`` à la racine.
    :param path: un fichier précis, qui l'emporte sur ``card``.

    Sans fichier lisible, on rend les valeurs par défaut du firmware. Les
    assignations hors de 0..127 — le ``255`` de ``stutterRate`` — sont
    écartées : elles veulent dire « non assigné ».
    """
    brut = dict(DEFAULT_CC)
    fichier = Path(path) if path is not None else _card_file(card)
    if fichier is not None:
        lu = _read_file(fichier)
        if lu:
            brut = lu
            log.info("MIDI Follow : %d assignations lues dans %s",
                     len(lu), fichier.name)

    sortie: dict[str, int] = {}
    for nom, cc in brut.items():
        if not 0 <= int(cc) <= 127:
            continue
        cle = _param_key(nom)
        if cle:
            sortie[cle] = int(cc)
    return sortie


def _card_file(card) -> Path | None:
    if card is None:
        return None
    racine = getattr(card, "root", None)
    if racine is None:
        return None
    try:
        chemin = Path(racine) / FOLLOW_FILE
        return chemin if chemin.is_file() else None
    except OSError as exc:             # noqa: BLE001
        log.debug("MIDIFollow.XML inaccessible : %s", exc)
        return None


def _read_file(chemin: Path) -> dict[str, int]:
    """Lit le fichier. Un fichier abîmé rend un dictionnaire vide."""
    from . import dxml

    try:
        doc = dxml.load(chemin)
    except Exception as exc:           # noqa: BLE001 - fichier utilisateur
        log.debug("MIDIFollow.XML illisible : %s", exc)
        return {}
    racine = getattr(doc, "root", None)
    if racine is None:
        return {}

    sortie: dict[str, int] = {}
    for element in racine.iter():
        if len(element):
            continue
        texte = (element.text or "").strip()
        if not texte.lstrip("-").isdigit():
            continue
        sortie[element.tag] = int(texte)
    return sortie


def _raw_value(sound, cle: str) -> int | None:
    """Valeur brute 32 bits d'une clé, enveloppes comprises."""
    if "." in cle:
        groupe, _, segment = cle.partition(".")
        env = getattr(sound, groupe, None)
        valeur = getattr(env, segment, None) if env is not None else None
        return int(valeur) if isinstance(valeur, int) else None
    if cle in getattr(sound, "params", {}):
        return int(sound.params[cle])
    if cle in getattr(sound, "eq", {}):
        return int(sound.eq[cle])
    return None


def cc_value(raw: int) -> int:
    """Valeur 0..127 d'un paramètre 32 bits.

    Le firmware étale un contrôleur sur toute la plage du paramètre :
    ``0x80000000`` -> 0, ``0x7FFFFFFF`` -> 127. C'est exactement ce que
    ``to_unit`` calcule déjà pour l'affichage.
    """
    v = int(max(INT32_MIN, min(INT32_MAX, int(raw))))
    return max(0, min(127, int(round(to_unit(v) * 127))))


def sound_messages(sound, mapping: dict[str, int] | None = None,
                   keys: list[str] | None = None) -> list[tuple[int, int]]:
    """Les contrôleurs à envoyer pour reproduire un son sur la machine.

    :param sound: un :class:`~delugeapp.core.model.Sound`.
    :param mapping: la carte rendue par :func:`load_map` ; les valeurs par
        défaut si elle manque.
    :param keys: pour n'envoyer qu'une partie des paramètres — un seul quand
        l'utilisateur tourne un bouton, par exemple.
    :return: une liste de couples ``(contrôleur, valeur)``, dans un ordre
        stable, sans doublon.

    Un paramètre absent du son n'est pas envoyé : écrire une valeur par
    défaut écraserait sur la machine un réglage que l'application ne connaît
    pas.
    """
    carte = mapping if mapping is not None else load_map()
    voulues = list(keys) if keys else sorted(carte)
    messages: list[tuple[int, int]] = []
    vus: set[int] = set()
    for cle in voulues:
        cc = carte.get(cle)
        if cc is None or cc in vus:
            continue
        brut = _raw_value(sound, cle)
        if brut is None:
            continue
        messages.append((int(cc), cc_value(brut)))
        vus.add(int(cc))
    return messages
