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
from dataclasses import dataclass
from pathlib import Path

from ..i18n import N_, tr
from .fixedpoint import INT32_MAX, INT32_MIN

log = logging.getLogger(__name__)

__all__ = [
    "FOLLOW_FILE", "DEFAULT_CC", "FOLLOW_TO_PARAM", "SANS_EQUIVALENT",
    "HALF_RANGE", "PARAM_LABELS", "label_of", "load_map", "cc_value",
    "raw_from_cc", "reverse_map", "sound_messages",
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


#: Nom français de chaque paramètre pilotable, dans l'ordre où la fenêtre
#: « Deluge en direct » les range : sources, filtres, enveloppes, effets.
PARAM_LABELS: dict[str, str] = {
    "volume": N_("Volume"),
    "pan": N_("Panoramique"),
    "pitchAdjust": N_("Hauteur"),
    "portamento": N_("Portamento"),
    "oscAVolume": N_("Osc A — niveau"),
    "oscAPitchAdjust": N_("Osc A — hauteur"),
    "oscAPulseWidth": N_("Osc A — largeur"),
    "oscAWavetablePosition": N_("Osc A — table"),
    "carrier1Feedback": N_("Osc A — réinjection"),
    "oscBVolume": N_("Osc B — niveau"),
    "oscBPitchAdjust": N_("Osc B — hauteur"),
    "oscBPulseWidth": N_("Osc B — largeur"),
    "oscBWavetablePosition": N_("Osc B — table"),
    "carrier2Feedback": N_("Osc B — réinjection"),
    "noiseVolume": N_("Bruit"),
    "modulator1Amount": N_("Modulateur 1"),
    "modulator1Feedback": N_("Modulateur 1 — réinjection"),
    "modulator2Amount": N_("Modulateur 2"),
    "modulator2Feedback": N_("Modulateur 2 — réinjection"),
    "lpfFrequency": N_("Passe-bas — coupure"),
    "lpfResonance": N_("Passe-bas — résonance"),
    "lpfMorph": N_("Passe-bas — morph"),
    "hpfFrequency": N_("Passe-haut — coupure"),
    "hpfResonance": N_("Passe-haut — résonance"),
    "hpfMorph": N_("Passe-haut — morph"),
    "env1.attack": N_("Enveloppe 1 — attaque"),
    "env1.decay": N_("Enveloppe 1 — déclin"),
    "env1.sustain": N_("Enveloppe 1 — maintien"),
    "env1.release": N_("Enveloppe 1 — relâche"),
    "env2.attack": N_("Enveloppe 2 — attaque"),
    "env2.decay": N_("Enveloppe 2 — déclin"),
    "env2.sustain": N_("Enveloppe 2 — maintien"),
    "env2.release": N_("Enveloppe 2 — relâche"),
    "lfo1Rate": N_("LFO 1 — vitesse"),
    "lfo2Rate": N_("LFO 2 — vitesse"),
    "arpeggiatorRate": N_("Arpège — vitesse"),
    "arpeggiatorGate": N_("Arpège — durée"),
    "modFXRate": N_("Mod FX — vitesse"),
    "modFXDepth": N_("Mod FX — profondeur"),
    "modFXFeedback": N_("Mod FX — réinjection"),
    "modFXOffset": N_("Mod FX — décalage"),
    "delayRate": N_("Délai — temps"),
    "delayFeedback": N_("Délai — réinjection"),
    "reverbAmount": N_("Réverbération"),
    "compressorShape": N_("Compresseur"),
    "waveFold": N_("Repliement"),
    "sampleRateReduction": N_("Décimation"),
    "bitCrush": N_("Bitcrush"),
    "bass": N_("Graves"),
    "bassFrequency": N_("Graves — fréquence"),
    "treble": N_("Aigus"),
    "trebleFrequency": N_("Aigus — fréquence"),
}


def label_of(key: str) -> str:
    """Nom d'un paramètre dans la langue de l'interface, ou sa clé à défaut."""
    return tr(PARAM_LABELS.get(str(key), str(key)))


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
    return load_map_with_source(card, path)[0]


def load_map_with_source(card=None, path: Path | None = None
                         ) -> tuple[dict[str, int], str]:
    """Comme :func:`load_map`, avec la provenance de la table : le nom du
    fichier lu, ou ``""`` quand ce sont les valeurs d'usine du firmware.

    L'interface le dit : annoncer « lus sur la carte » sans carte, c'était
    affirmer une lecture qui n'avait pas eu lieu.
    """
    brut = dict(DEFAULT_CC)
    source = ""
    fichier = Path(path) if path is not None else _card_file(card)
    if fichier is not None:
        lu = _read_file(fichier)
        if lu:
            brut = lu
            source = fichier.name
            log.info("MIDI Follow : %d assignations lues dans %s",
                     len(lu), fichier.name)

    sortie: dict[str, int] = {}
    for nom, cc in brut.items():
        if not 0 <= int(cc) <= 127:
            continue
        cle = _param_key(nom)
        if cle:
            sortie[cle] = int(cc)
    return sortie, source


#: Où le firmware range le fichier : ``SETTINGS/`` depuis la 1.3
#: (``MIDI_FOLLOW_XML``, mesuré sur la carte), la racine avant.
FOLLOW_PLACES = ("SETTINGS/" + FOLLOW_FILE, FOLLOW_FILE)


def _card_file(card) -> Path | None:
    if card is None:
        return None
    racine = getattr(card, "root", None)
    if racine is None:
        return None
    for place in FOLLOW_PLACES:
        try:
            chemin = Path(racine) / place
            if chemin.is_file():
                return chemin
        except OSError as exc:         # noqa: BLE001
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

    # Seules les assignations comptent : une autre section numérique (canal,
    # réglage ajouté par un firmware futur) deviendrait sinon un contrôleur.
    # Mesuré sur la 1.3 : faute de reconnaître ``cc_mappings``, ses canaux
    # et sa note de base passaient pour 28 contrôleurs de plus.
    for nom in ("cc_mappings", "defaultCCMappings"):
        section = racine.find(".//" + nom)
        if section is not None:
            racine = section
            break

    sortie: dict[str, int] = {}
    for element in racine.iter():
        if len(element):
            continue
        texte = (element.text or "").strip()
        if not texte.lstrip("-").isdigit():
            continue
        sortie[element.tag] = int(texte)
    return sortie


@dataclass(frozen=True)
class FollowSettings:
    """Les réglages MIDI Follow **de la machine**, tels que la 1.3 les
    enregistre dans ``SETTINGS/MIDIFollow.XML``.

    Les canaux sont comptés de 1 à 16 ; ``None`` veut dire « non réglé »
    (le firmware écrit le canal + 1, et 256 pour « aucun »).
    """

    channel_a: int | None = None
    channel_b: int | None = None
    channel_c: int | None = None
    kit_root_note: int | None = None
    #: ``"a"``, ``"b"``, ``"c"`` ou ``None`` (retour éteint).
    feedback: str | None = None


def read_settings(card=None, path: Path | None = None) -> FollowSettings | None:
    """Les réglages de la machine, ou ``None`` si le fichier n'en porte pas
    (firmware 1.2.1 : ils vivaient dans sa mémoire, pas sur la carte)."""
    from . import dxml

    fichier = Path(path) if path is not None else _card_file(card)
    if fichier is None:
        return None
    try:
        racine = getattr(dxml.load(fichier), "root", None)
    except Exception as exc:           # noqa: BLE001 - fichier utilisateur
        log.debug("MIDIFollow.XML illisible : %s", exc)
        return None
    if racine is None:
        return None
    section = racine.find(".//settings")
    if section is None:
        return None

    def canal(nom: str) -> int | None:
        texte = (section.findtext("channels/%s/channel" % nom) or "").strip()
        if not texte.isdigit():
            return None
        valeur = int(texte)
        return valeur if 1 <= valeur <= 16 else None

    note = (section.findtext("kit_root_note/note") or "").strip()
    retour = (section.findtext("feedback/channel") or "").strip().lower()
    return FollowSettings(
        channel_a=canal("a"), channel_b=canal("b"), channel_c=canal("c"),
        kit_root_note=int(note) if note.isdigit() else None,
        feedback=retour if retour in ("a", "b", "c") else None)


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


#: Paramètres que le firmware règle sur une demi-échelle (0 à 2^31) :
#: ``(valeur >> 24) - 64`` au lieu de ``(valeur + 2^24) >> 25``
#: (``PatchedParamSet::paramValueToKnobPos``).
HALF_RANGE: frozenset[str] = frozenset({"oscAPulseWidth", "oscBPulseWidth"})


def cc_value(raw: int, key: str = "") -> int:
    """Valeur 0..127 qui place un paramètre 32 bits sur ``raw``.

    **Calcul du firmware** (tag ``release_1_2_1``) : une position de bouton
    vaut ``(valeur + 2^24) >> 25`` (``ParamCollection::paramValueToKnobPos``),
    de −64 à +64, et le contrôleur reçu en mode « saut » devient
    ``position = cc − 64``, sauf 127 qui vaut +64, le maximum
    (``MidiTakeover::calculateKnobPos``). L'ancienne règle de trois
    (``to_unit × 127``) tombait souvent un cran à côté.
    """
    v = int(max(INT32_MIN, min(INT32_MAX, int(raw))))
    if key in HALF_RANGE:
        return max(0, min(127, v >> 24))
    if v >= 0x7F000000:
        return 127
    return max(0, min(127, ((v + (1 << 24)) >> 25) + 64))


def raw_from_cc(value: int, key: str = "") -> int:
    """Valeur 32 bits d'un paramètre d'après un contrôleur reçu.

    Inverse de :func:`cc_value`, pour lire le **retour** du mode MIDI
    Follow : la machine envoie ``position + 64`` (128 pour le maximum, un
    octet que le MIDI n'autorise pas — on le prend pour le maximum).
    """
    try:
        c = int(value)
    except (TypeError, ValueError):
        return 0
    position = c - 64
    if position >= 64 or c >= 128:
        return INT32_MAX
    if key in HALF_RANGE:
        return max(0, c) << 24
    return max(-64, position) << 25


def reverse_map(mapping: dict[str, int] | None = None) -> dict[int, str]:
    """Contrôleur -> clé de l'application (la première, en cas de doublon)."""
    carte = mapping if mapping is not None else load_map()
    sortie: dict[int, str] = {}
    for cle in sorted(carte):
        sortie.setdefault(int(carte[cle]), cle)
    return sortie


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
        messages.append((int(cc), cc_value(brut, cle)))
        vus.add(int(cc))
    return messages
