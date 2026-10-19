# -*- coding: utf-8 -*-
"""Écriture de morceaux : faire d'une création un fichier ``SONGS/*.XML``.

Les outils de création de l'application — progression et accompagnement,
motif rythmique, esquisse d'arrangement, preset et kit générés, kit d'essai,
boucle découpée — s'arrêtaient à un fichier MIDI ou à un preset. Ce module
en fait un **morceau du Deluge**, prêt à jouer : instruments intégrés, un clip
par partie, sections enchaînées et arrangement.

Le format est celui qu'écrit le firmware communautaire c1.2.1 de la machine
(``Song::writeToFile``, tag ``release_1_2_1``), relevé sur les six morceaux
c1.2.1 de la carte :

* ``inputTickMagnitude`` vaut 2 : une mesure fait 384 ticks, une
  double-croche 24 ;
* un instrument est **intégré** au morceau : le ``<sound>`` ou le ``<kit>``
  du preset, privé de ses paramètres (``<defaultParams>``). Ceux-ci passent
  dans **chaque clip** : ``<soundParams>`` pour un synthé, ``<kitParams>``
  pour un kit, et un ``<soundParams>`` par rangée de kit. L'arpégiateur d'un
  synthé passe lui aussi dans le clip ;
* une section passe à la suivante après ``numRepeats`` boucles de son plus
  long clip (``Session::armNextSection``). En disposition « rangées », la
  suivante est celle du clip **d'en dessous** : les clips de la première
  section occupent donc les index les plus élevés, en haut de l'écran ;
* l'arrangement place des **instances** de ces mêmes clips de session
  (``clipInstances`` : position, longueur, index du clip). Une instance plus
  longue que son clip le fait boucler.

**Un preset ancien ne s'intègre pas tel quel.** Le firmware lit tout le
morceau avec la version déclarée par ``<song>`` : un preset 3.x ou sans
version, recopié sans précaution, serait lu comme du c1.2.1. Pire, un attribut
``firmwareVersion`` laissé dans un ``<sound>`` **change la version de lecture
de tout le reste du fichier** (``tryReadingFirmwareTagFromFile``). Ce module
retire donc ces attributs et applique lui-même les conversions que la
machine fait en chargeant un preset ancien (:func:`upgrade_sound`,
:func:`upgrade_kit`).

**Règle de non-destruction.** Un morceau écrit ici est toujours un fichier
**nouveau** : un nom déjà pris est numéroté, jamais remplacé, et
:func:`write_song` simule par défaut.
"""

from __future__ import annotations

import copy
import logging
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..i18n import N_, decimal, plural, tr
from . import dxml
from .fixedpoint import format_fixed, parse_fixed
from .model import Note, encode_notes, ticks_per_bar
from .sdcard import SDCard, check_name, safe_deluge_name

log = logging.getLogger(__name__)

__all__ = [
    "FIRMWARE", "MAGNITUDE", "BAR", "STEP", "MAX_SECTIONS",
    "Track", "ClipSpec", "SectionSpec", "SongSpec", "SongWrite",
    "tempo_attrs", "synth_track", "kit_track", "upgrade_sound", "upgrade_kit",
    "events_to_rows", "pattern_rows", "fold", "build", "preview",
    "write_song", "free_song_name", "ascii_label",
    # Recettes, une par outil de création.
    "PART_ORDER", "part_label", "ROLE_PART", "key_of", "part_roles",
    "part_presets", "drum_rows", "drum_kit_for", "progression_song",
    "pattern_song", "sketch_song", "preset_song", "slices_song",
    "loop_tempo",
]

#: Version écrite dans le morceau : celle de la machine.
FIRMWARE = "c1.2.1"
EARLIEST = "4.1.0-alpha"
#: ``inputTickMagnitude`` d'un morceau neuf en c1.2.1 (``DEFAULT.XML``).
MAGNITUDE = 2
#: Ticks d'une mesure 4/4 et d'une double-croche à cette magnitude.
BAR = ticks_per_bar(MAGNITUDE)
STEP = BAR // 16
#: Le firmware connaît douze sections (``kMaxNumSections``).
MAX_SECTIONS = 12
#: Nombre de pads d'une vignette : 8 rangées de 16, plus 2 colonnes.
PREVIEW_ROWS, PREVIEW_COLS = 8, 18

INT32_MIN = -(1 << 31)
INT32_MAX = (1 << 31) - 1

# --------------------------------------------------------------------------- #
# Valeurs d'un morceau neuf : ``SONGS/DEFAULT.XML`` de la carte (c1.2.1)
# --------------------------------------------------------------------------- #

_REVERB = (("roomSize", "1288490112"), ("dampening", "1546188288"),
           ("width", "2147483647"), ("hpf", "0"), ("pan", "0"),
           ("model", "1"))
_REVERB_COMPRESSOR = (("attack", "0"), ("release", "0"),
                      ("volume", "-21474836"), ("shape", "-601295438"),
                      ("syncLevel", "4"))
_DELAY = (("pingPong", "1"), ("analog", "0"), ("syncLevel", "7"),
          ("syncType", "0"))
_SIDECHAIN_SONG = (("attack", "327244"), ("release", "936"),
                   ("syncLevel", "6"), ("syncType", "0"))
_AUDIO_COMPRESSOR = (("attack", "83886080"), ("release", "83886080"),
                     ("thresh", "0"), ("ratio", "1073741824"),
                     ("compHPF", "0"), ("compBlend", "2147483647"))
#: Paramètres globaux d'un morceau (et d'un kit neuf), dans l'ordre écrit.
_GLOBAL_PARAMS = (
    ("reverbAmount", "0x80000000"), ("volume", "0x3504F334"),
    ("pan", "0x00000000"), ("sidechainCompressorShape", "0xDC28F5B2"),
    ("modFXDepth", "0x00000000"), ("modFXRate", "0xE0000000"),
    ("stutterRate", "0x00000000"), ("sampleRateReduction", "0x80000000"),
    ("bitCrush", "0x80000000"), ("modFXOffset", "0x00000000"),
    ("modFXFeedback", "0x80000000"), ("compressorThreshold", "0x00000000"),
    ("lpfMorph", "0x80000000"), ("hpfMorph", "0x80000000"),
)
_GLOBAL_GROUPS = (
    ("delay", (("rate", "0x00000000"), ("feedback", "0x80000000"))),
    ("lpf", (("frequency", "0x7FFFFFFF"), ("resonance", "0x80000000"))),
    ("hpf", (("frequency", "0x80000000"), ("resonance", "0x80000000"))),
    ("equalizer", (("bass", "0x00000000"), ("treble", "0x00000000"),
                   ("bassFrequency", "0x00000000"),
                   ("trebleFrequency", "0x00000000"))),
)
#: Attributs d'un instrument propres au morceau (``Output::writeDataToFile``).
_DEFAULT_VELOCITY = "64"
#: Attributs « effets globaux » d'un kit dans un morceau (``SONG1.XML``).
_KIT_GLOBAL_ATTRS = (("modFXCurrentParam", "feedback"),
                     ("currentFilterType", "lpf"), ("modFXType", "none"),
                     ("lpfMode", "24dB"), ("hpfMode", "HPLadder"),
                     ("filterRoute", "H2L"))
#: Ce qui appartient au fichier de preset et pas à l'instrument d'un morceau.
_PRESET_ONLY = frozenset({"firmwareVersion", "earliestCompatibleFirmware",
                          "presetName", "presetFolder", "presetSlot",
                          "presetSubSlot"})


# --------------------------------------------------------------------------- #
# Versions de firmware
# --------------------------------------------------------------------------- #

def _version_key(text: str) -> tuple:
    """Clé de comparaison d'une version, dans l'ordre du firmware.

    ``FirmwareVersion`` range les versions officielles avant les
    communautaires ; un fichier sans version compte pour l'officielle 0.0.0.
    Une préversion (``-beta``, ``-alpha``) passe avant la version finale.
    """
    raw = str(text or "").strip()
    community = raw[:1].lower() == "c"
    if community:
        raw = raw[1:]
    base, _sep, suffix = raw.partition("-")
    numbers = []
    for part in base.split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        numbers.append(int(digits) if digits else 0)
    while len(numbers) < 3:
        numbers.append(0)
    # Sans suffixe, la version finale passe après toute préversion.
    tag = (1, "") if not suffix else (0, suffix.lower())
    return (1 if community else 0, tuple(numbers[:3]), tag)


def _older(version: str, than: str) -> bool:
    """Vrai si ``version`` précède ``than`` pour le firmware."""
    return _version_key(version) < _version_key(than)


# --------------------------------------------------------------------------- #
# Lecture et écriture indifférentes au dialecte
# --------------------------------------------------------------------------- #

def _value(el: ET.Element | None, name: str) -> str | None:
    """Valeur d'un attribut ou d'un enfant texte (dialectes 3.x et 2.x)."""
    if el is None:
        return None
    if name in el.attrib:
        return el.attrib[name]
    child = el.find(name)
    if child is not None and len(child) == 0:
        return (child.text or "").strip()
    return None


def _assign(el: ET.Element, name: str, value: str) -> None:
    """Fixe une valeur là où elle se trouve déjà (attribut ou enfant)."""
    child = el.find(name)
    if name not in el.attrib and child is not None and len(child) == 0:
        child.text = str(value)
    else:
        el.set(name, str(value))


def _remove(el: ET.Element, name: str) -> None:
    """Retire un attribut et tout enfant de ce nom."""
    el.attrib.pop(name, None)
    for child in list(el):
        if child.tag == name:
            el.remove(child)


def _strip_versions(el: ET.Element) -> None:
    """Retire toute déclaration de version, à toute profondeur.

    Laissée dans un morceau, elle changerait la version de lecture de tout ce
    qui la suit (``XMLDeserializer::tryReadingFirmwareTagFromFile``).
    """
    for node in list(el.iter()):
        for name in ("firmwareVersion", "earliestCompatibleFirmware"):
            node.attrib.pop(name, None)
        for child in list(node):
            if child.tag in ("firmwareVersion", "earliestCompatibleFirmware"):
                node.remove(child)


def _hex(value: str | None, default: int) -> int:
    """Paramètre hexadécimal lu, ou ``default`` s'il est absent ou illisible."""
    if value is None or not str(value).strip():
        return default
    try:
        return parse_fixed(value)
    except (TypeError, ValueError):
        return default


def _param(params: ET.Element | None, name: str,
           group: tuple[str, str] | None = None) -> str | None:
    """Paramètre d'un ``<defaultParams>`` : plat, ou dans un groupe."""
    if params is None:
        return None
    flat = _value(params, name)
    if flat is not None:
        return flat
    if group is not None:
        return _value(params.find(group[0]), group[1])
    return None


def _set_param(params: ET.Element, name: str, value: int,
               group: tuple[str, str] | None = None) -> None:
    """Écrit un paramètre là où il se trouve (plat ou groupé)."""
    text = format_fixed(int(value))
    if _value(params, name) is not None or group is None:
        _assign(params, name, text)
        return
    holder = params.find(group[0])
    if holder is None:
        holder = ET.SubElement(params, group[0])
    _assign(holder, group[1], text)


# --------------------------------------------------------------------------- #
# Conversions des presets anciens (ce que fait la machine en les chargeant)
# --------------------------------------------------------------------------- #

#: ``oldResonanceCompensation`` (``lookuptables.cpp``).
_OLD_RESONANCE = (8192, 4915, 2764, 1024, 0, 0, 0, 0, 0)
#: ``dbIntervals`` (``functions.cpp``).
_DB_INTERVALS = (24.0, 12.1, 7.0, 5.0, 3.9, 3.2, 2.6, 2.4, 2.0, 1.8, 1.7,
                 1.5, 1.4, 1.3, 1.2, 1.1)
#: Câbles posés par ``Sound::setupDefaultExpressionPatching`` : 33, 20 et 15
#: unités de câble (21 474 836 par unité).
_AFTERTOUCH_VOLUME = "0x2A3D7094"
_Y_LPF = "0x19999990"
_Y_MODULATOR = "0x1333332C"
#: Polyphonie numérique des anciens fichiers (``stringToPolyphonyMode``).
_OLD_POLYPHONY = {"0": "auto", "2": "choke", "1": "poly"}
#: ``kMaxNumPatchCables``.
_MAX_CABLES = 15
#: Ancien ``mode`` d'arpège -> (arpMode, noteMode, octaveMode)
#: (``oldModeToArpMode``, ``oldModeToArpNoteMode``,
#: ``oldModeToArpOctaveMode``).
_OLD_ARP = {"off": ("off", "up", "up"), "up": ("arp", "up", "up"),
            "down": ("arp", "down", "down"), "both": ("arp", "up", "alt"),
            "random": ("arp", "random", "random")}


def _resonance_compensation_db(resonance: int) -> float:
    """Gain de compensation d'un fichier d'avant 1.2.0, en dB.

    ``interpolateTableSigned(résonance + 2^31, 32, oldResonanceCompensation,
    3) / (1024 << 16)`` : 8 dB à résonance nulle, plus rien à mi-course.
    """
    x = (int(resonance) + (1 << 31)) & 0xFFFFFFFF
    which = x >> 29
    strength2 = (x >> 13) & 0xFFFF
    strength1 = 65536 - strength2
    value = (_OLD_RESONANCE[which] * strength1
             + _OLD_RESONANCE[which + 1] * strength2)
    return float(np.float32(value) / np.float32(1024 << 16))


def _shift_volume_db(old: int, offset: float) -> int:
    """``shiftVolumeByDB`` du firmware, défaut compris.

    La position dans l'intervalle y est calculée par une division entière
    (``howFarUpInterval / 268435456``), qui vaut toujours 0 : le décalage
    repart du bas de l'intervalle. On reproduit ce que fait la machine, pas ce
    qu'elle voulait faire.
    """
    positive = (int(old) + (1 << 31)) & 0xFFFFFFFF
    interval = positive >> 28
    if interval < 1:
        return int(old)
    offset = np.float32(offset)
    how_far = np.float32(0.0)
    while True:
        db_this = np.float32(_DB_INTERVALS[interval])
        left = (np.float32(1.0) - how_far) * db_this
        if left > offset:
            wanted = np.float32(offset / left)
            new_how_far = np.float32(how_far + wanted)
            new_positive = (interval << 28) + int(new_how_far
                                                   * np.float32(268435456))
            break
        interval += 1
        if interval == 16:
            new_positive = 0xFFFFFFFF
            break
        offset = np.float32(offset - left)
        how_far = np.float32(0.0)
    return int(new_positive) - (1 << 31)


def _cables(params: ET.Element) -> list[ET.Element]:
    holder = params.find("patchCables")
    return list(holder) if holder is not None else []


def _add_cable(params: ET.Element, source: str, destination: str,
               amount: str) -> None:
    """Ajoute un câble après les câbles de même destination.

    C'est l'ordre dans lequel la machine les réécrit : groupés par
    destination, dans l'ordre de leur première apparition (``DEFAULT.XML`` et
    ``SONG1.XML``).
    """
    holder = params.find("patchCables")
    if holder is None:
        holder = ET.SubElement(params, "patchCables")
    cable = ET.Element("patchCable")
    cable.set("source", source)
    cable.set("destination", destination)
    cable.set("amount", amount)
    index = len(holder)
    for position, existing in enumerate(list(holder)):
        if _value(existing, "destination") == destination:
            index = position + 1
    holder.insert(index, cable)


def _expression_patching(params: ET.Element, fm: bool) -> None:
    """``Sound::possiblySetupDefaultExpressionPatching`` (avant 4.0.0-beta)."""
    sources = {_value(c, "source") for c in _cables(params)}
    if sources & {"aftertouch", "x", "y"}:
        return
    if len(_cables(params)) >= _MAX_CABLES:
        return
    _add_cable(params, "aftertouch", "volume", _AFTERTOUCH_VOLUME)
    if len(_cables(params)) >= _MAX_CABLES:
        return
    if fm:
        _add_cable(params, "y", "modulator1Volume", _Y_MODULATOR)
    else:
        _add_cable(params, "y", "lpfFrequency", _Y_LPF)


def _sound_resonance(params: ET.Element) -> None:
    """``Sound::compensateVolumeForResonance`` (fichiers d'avant 1.2.0)."""
    resonance = _hex(_param(params, "lpfResonance"), INT32_MIN)
    db = _resonance_compensation_db(resonance)
    if db > 0.1:
        volume = _param(params, "volume")
        if volume is not None:
            _set_param(params, "volume", _shift_volume_db(_hex(volume, 0), db))
    frequency = _param(params, "lpfFrequency")
    if frequency is None or _param(params, "lpfResonance") is None:
        return
    patched = any(_value(c, "destination") == "lpfFrequency"
                  for c in _cables(params))
    if (not patched and _hex(frequency, 0) >= 2147483602
            and -23 <= resonance <= 0):
        _set_param(params, "lpfResonance", INT32_MIN)


def _kit_resonance(params: ET.Element) -> None:
    """``Kit::compensateInstrumentVolumeForResonance`` puis
    ``GlobalEffectable::compensateVolumeForResonance`` (avant 1.2.0)."""
    lpf_res = ("lpf", "resonance")
    hpf_res = ("hpf", "resonance")
    raw = _param(params, "lpfResonance", lpf_res)
    if raw is None:
        return
    resonance = _hex(raw, INT32_MIN)
    db = _resonance_compensation_db(resonance)
    if db > 0.1:
        volume = _param(params, "volume")
        if volume is not None:
            _set_param(params, "volume", _shift_volume_db(_hex(volume, 0), db))
    frequency = _hex(_param(params, "lpfFrequency", ("lpf", "frequency")),
                     INT32_MAX)
    if frequency >= 2147483602 and resonance == 0:
        resonance = INT32_MIN
        _set_param(params, "lpfResonance", resonance, lpf_res)
    hpf_frequency = _hex(_param(params, "hpfFrequency", ("hpf", "frequency")),
                         INT32_MIN)
    # Le firmware teste la résonance du **passe-bas** ici, pas celle du
    # passe-haut : on reproduit sa lecture.
    if hpf_frequency == INT32_MIN and resonance == -1073741824:
        _set_param(params, "hpfResonance", INT32_MIN, hpf_res)


def _sample_markers(sound: ET.Element, sd: SDCard | None) -> list[str]:
    """Bornes en millisecondes -> trames (fichiers d'avant 2.1.0-beta).

    ``SampleHolderForVoice`` : une borne déjà en trames l'emporte ; une fin
    qui dépasse la longueur d'au plus 45 trames est ramenée à la longueur ;
    un échantillon inversé voit ses bornes retournées. Rend les
    échantillons qu'il a fallu laisser en millisecondes, faute de fichier.
    """
    from . import wav

    left: list[str] = []
    for osc in sound.iter():
        if osc.tag not in ("osc1", "osc2", "sampleRange"):
            continue
        zone = osc.find("zone")
        if zone is None:
            continue
        start_ms = _ms(zone, "startMilliseconds", "startSeconds")
        end_ms = _ms(zone, "endMilliseconds", "endSeconds")
        rel = _value(osc, "fileName") or ""
        if not rel:
            # Oscillateur sans fichier : la machine écrit 0 et 0.
            _drop_ms(zone)
            _assign(zone, "startSamplePos", "0")
            _assign(zone, "endSamplePos", "0")
            continue
        if not start_ms and not end_ms:
            # Rien à convertir : la machine ne réécrit pas ces bornes nulles.
            _drop_ms(zone)
            continue
        path = sd.resolve_sample(rel) if sd is not None else None
        info = None
        if path is not None:
            try:
                info = wav.probe(path)
            except Exception as exc:  # noqa: BLE001 - laissé tel quel
                log.debug("échantillon illisible %s : %s", rel, exc)
        if info is None or not info.frames or not info.sample_rate:
            left.append(rel)
            continue
        length, rate = int(info.frames), int(info.sample_rate)
        start = int(_value(zone, "startSamplePos") or 0)
        end = int(_value(zone, "endSamplePos") or 0)
        converted = False
        if start_ms and not start:
            start = start_ms * rate // 1000
            converted = True
        if end_ms and (not end or end == length):
            end = end_ms * rate // 1000
            if length < end <= length + 45:
                end = length
            converted = True
        if converted and _value(osc, "reversed") == "1":
            start, end = length - end, length - start
            start = max(0, start)
        _drop_ms(zone)
        _assign(zone, "startSamplePos", str(int(start)))
        _assign(zone, "endSamplePos", str(int(end)))
    return left


def _drop_ms(zone: ET.Element) -> None:
    for name in ("startMilliseconds", "endMilliseconds", "startSeconds",
                 "endSeconds"):
        _remove(zone, name)


def _ms(zone: ET.Element, ms_name: str, s_name: str) -> int:
    total = 0
    for name, factor in ((s_name, 1000), (ms_name, 1)):
        raw = _value(zone, name)
        if raw:
            try:
                total += int(float(raw)) * factor
            except ValueError:
                pass
    return total


def _arp_modes(arp: ET.Element | None, version: str) -> tuple[str, str, str]:
    """``(arpMode, noteMode, octaveMode)`` d'un ``<arpeggiator>`` de preset."""
    if arp is None:
        return "off", "up", "up"
    modes = ["off", "up", "up"]
    old = _value(arp, "mode")
    if old is not None and _older(version, "c1.2.0"):
        modes = list(_OLD_ARP.get(old.strip(), _OLD_ARP["off"]))
    for index, name in enumerate(("arpMode", "noteMode", "octaveMode")):
        explicit = _value(arp, name)
        if explicit:
            modes[index] = explicit
    return modes[0], modes[1], modes[2]


def upgrade_sound(sound: ET.Element, version: str, sd: SDCard | None = None,
                  ) -> list[str]:
    """Met un ``<sound>`` (preset ou rangée) au niveau d'un morceau c1.2.1.

    Applique, selon la version du fichier d'origine, ce que la machine fait
    en le chargeant : ancien mode d'arpège éclaté (avant c1.2.0), filtres
    coupés en FM (avant c1.2.0), câbles d'expression par défaut (avant
    4.0.0-beta), bornes en millisecondes (avant 2.1.0-beta), compensation de
    résonance (avant 1.2.0). Modifie ``sound`` ; rend les échantillons dont
    les bornes n'ont pas pu être converties.
    """
    _strip_versions(sound)
    fm = (_value(sound, "mode") or "").strip() == "fm"
    # Polyphonie des fichiers d'avant juin 2017, en chiffres : la machine la
    # lit (« 0 » = auto, « 2 » = choke, ``stringToPolyphonyMode``) et la
    # réécrit en toutes lettres.
    polyphony = _value(sound, "polyphonic")
    if polyphony in _OLD_POLYPHONY:
        _assign(sound, "polyphonic", _OLD_POLYPHONY[polyphony])
    # Un plafond de zéro voix, écrit par les premiers presets générés : la
    # machine écrit 8 pour tous ses sons et ne produit jamais 0.
    if (_value(sound, "maxVoices") or "").strip() == "0":
        _assign(sound, "maxVoices", "8")
    params = sound.find("defaultParams")

    if _older(version, "c1.2.0"):
        arp = sound.find("arpeggiator")
        if arp is not None and not _value(arp, "arpMode"):
            arp_mode, note_mode, octave_mode = _arp_modes(arp, version)
            arp.set("arpMode", arp_mode)
            arp.set("noteMode", note_mode)
            arp.set("octaveMode", octave_mode)
        if fm:
            _assign(sound, "lpfMode", "off")
            _assign(sound, "hpfMode", "off")

    left: list[str] = []
    if _older(version, "2.1.0-beta"):
        left = _sample_markers(sound, sd)
    if params is not None:
        if _older(version, "1.2.0") and not fm:
            _sound_resonance(params)
        if _older(version, "4.0.0-beta"):
            _expression_patching(params, fm)
    # Nom actuel de l'ancien compresseur (``<compressor>`` = sidechain, lu
    # sous les deux noms par ``ModControllableAudio::readTagFromFile``).
    for child in sound:
        if child.tag == "compressor":
            child.tag = "sidechain"
    return left


def upgrade_kit(kit: ET.Element, version: str, sd: SDCard | None = None,
                ) -> list[str]:
    """Met un ``<kit>`` et ses rangées au niveau d'un morceau c1.2.1."""
    _strip_versions(kit)
    params = kit.find("defaultParams")
    if params is not None and _older(version, "1.2.0"):
        _kit_resonance(params)
    for child in kit:
        if child.tag == "compressor":
            child.tag = "sidechain"
    left: list[str] = []
    sources = kit.find("soundSources")
    for sound in (sources if sources is not None else []):
        if sound.tag == "sound":
            left.extend(upgrade_sound(sound, version, sd))
    return left


# --------------------------------------------------------------------------- #
# Pistes : un instrument du morceau
# --------------------------------------------------------------------------- #

@dataclass
class Track:
    """Un instrument du morceau, prêt à être intégré.

    ``body`` est le ``<sound>`` ou le ``<kit>`` sans ses paramètres ;
    ``params`` le bloc de paramètres qui ira dans chaque clip ; pour un kit,
    ``drum_params`` en donne un par rangée.
    """

    kind: str
    name: str
    folder: str
    body: ET.Element
    params: ET.Element
    arp: dict[str, str] = field(default_factory=dict)
    drum_params: list[ET.Element] = field(default_factory=list)
    drum_names: list[str] = field(default_factory=list)
    samples: list[str] = field(default_factory=list)
    #: Échantillons dont les bornes anciennes n'ont pas pu être converties.
    unconverted: list[str] = field(default_factory=list)

    @property
    def is_kit(self) -> bool:
        return self.kind == "kit"


def _source_element(source, tag: str) -> tuple[ET.Element, str]:
    """Copie de travail de l'élément d'un preset, et sa version."""
    if isinstance(source, ET.Element):
        return copy.deepcopy(source), ""
    doc = getattr(source, "doc", None)
    version = getattr(doc, "firmware", "") if doc is not None else ""
    if doc is not None and doc.root is not None:
        root = copy.deepcopy(doc.root)
    else:
        root = ET.Element(tag)
    if root.tag != tag:
        found = root if root.tag == tag else root.find(tag)
        root = found if found is not None else ET.Element(tag)
    # Le modèle peut avoir changé depuis la lecture (preset généré, kit
    # assemblé) : on réécrit ce qu'il connaît dans la copie.
    if tag == "sound" and getattr(source, "sound", None) is not None:
        source.sound.to_xml(root, getattr(doc, "dialect", "attr")
                            if doc is not None else "attr")
        version = version or source.sound.firmware or FIRMWARE
    elif tag == "kit" and hasattr(source, "rows"):
        source.to_xml(root, getattr(doc, "dialect", "attr")
                      if doc is not None else "attr")
        version = version or FIRMWARE
    return root, version or FIRMWARE


def _sample_refs(el: ET.Element) -> list[str]:
    out: list[str] = []
    for node in el.iter():
        if node.tag in ("osc1", "osc2", "sampleRange"):
            rel = _value(node, "fileName")
            if rel and rel not in out:
                out.append(rel)
    return out


def _empty_sound_params() -> ET.Element:
    return ET.Element("defaultParams")


def synth_track(source, name: str = "", folder: str = "SYNTHS",
                version: str | None = None, sd: SDCard | None = None,
                arp: bool | None = None) -> Track:
    """Prépare un synthé : un :class:`~delugeapp.core.model.SynthPreset` ou un
    élément ``<sound>`` (``version`` dit alors de quel firmware il vient).

    :param arp: ``False`` éteint l'arpégiateur (une partie déjà arpégée note
        par note), ``True`` l'allume ; ``None`` garde celui du preset.
    """
    element, found = _source_element(source, "sound")
    version = version if version is not None else found
    unconverted = upgrade_sound(element, version, sd)
    params = element.find("defaultParams")
    params = copy.deepcopy(params) if params is not None \
        else _empty_sound_params()
    arp_el = element.find("arpeggiator")
    arp_mode, note_mode, octave_mode = _arp_modes(arp_el, version)
    if arp is False:
        arp_mode = "off"
    elif arp is True:
        arp_mode = "arp"
    sync = _int_value(_value(arp_el, "syncLevel"), 7)
    arp_attrs = {
        "mode": arp_mode,
        # Le clip garde la valeur **interne** : fichier + 1 − magnitude
        # (``convertSyncLevelFromFileValueToInternalValue``). Le preset TB01
        # écrit 7, ``DEFAULT.XML`` porte 6 dans son clip.
        "syncLevel": str(_internal_sync(sync)),
        "numOctaves": str(_int_value(_value(arp_el, "numOctaves"), 2)),
        "syncType": str(_int_value(_value(arp_el, "syncType"), 0)),
        "arpMode": arp_mode,
        "noteMode": note_mode,
        "octaveMode": octave_mode,
        "mpeVelocity": _value(arp_el, "mpeVelocity") or "off",
    }
    body = ET.Element("sound")
    for key, value in element.attrib.items():
        if key in _PRESET_ONLY or key == "name":
            continue
        body.set(key, value)
    for child in element:
        if child.tag in ("defaultParams", "arpeggiator", "name") \
                or child.tag in _PRESET_ONLY:
            continue
        body.append(child)
    label = name or _value(element, "name") or getattr(source, "name", "")
    return Track(kind="sound", name=_label(label, "SYNTH"),
                 folder=folder or "SYNTHS", body=body, params=params,
                 arp=arp_attrs, samples=_sample_refs(body),
                 unconverted=unconverted)


def kit_track(source, name: str = "", folder: str = "KITS",
              version: str | None = None, sd: SDCard | None = None) -> Track:
    """Prépare un kit : un :class:`~delugeapp.core.model.Kit` ou un élément
    ``<kit>``."""
    element, found = _source_element(source, "kit")
    version = version if version is not None else found
    unconverted = upgrade_kit(element, version, sd)
    params = element.find("defaultParams")
    params = copy.deepcopy(params) if params is not None else _kit_params()
    body = ET.Element("kit")
    for key, value in element.attrib.items():
        if key in _PRESET_ONLY or key == "name":
            continue
        body.set(key, value)
    for key, value in _KIT_GLOBAL_ATTRS:
        if _value(element, key) is None:
            body.set(key, value)
    drum_params: list[ET.Element] = []
    drum_names: list[str] = []
    for child in element:
        if child.tag in ("defaultParams", "name") or child.tag in _PRESET_ONLY:
            continue
        if child.tag == "soundSources":
            sources = ET.Element("soundSources")
            for sound in child:
                if sound.tag != "sound":
                    continue
                own = sound.find("defaultParams")
                drum_params.append(copy.deepcopy(own) if own is not None
                                   else _empty_sound_params())
                drum_names.append(_value(sound, "name") or "")
                kept = ET.Element("sound")
                for key, value in sound.attrib.items():
                    kept.set(key, value)
                for sub in sound:
                    if sub.tag != "defaultParams":
                        kept.append(sub)
                sources.append(kept)
            body.append(sources)
        else:
            body.append(child)
    for tag, values in (("delay", _DELAY), ("sidechain", _SIDECHAIN_SONG),
                        ("audioCompressor", _AUDIO_COMPRESSOR)):
        if body.find(tag) is None:
            extra = ET.Element(tag)
            for key, value in values:
                extra.set(key, value)
            # Avant les rangées, là où la machine les écrit.
            sources_at = [i for i, c in enumerate(body)
                          if c.tag == "soundSources"]
            body.insert(sources_at[0] if sources_at else len(body), extra)
    label = name or getattr(source, "name", "") or _value(element, "name")
    return Track(kind="kit", name=_label(label, "KIT"),
                 folder=folder or "KITS", body=body, params=params,
                 drum_params=drum_params, drum_names=drum_names,
                 samples=_sample_refs(body), unconverted=unconverted)


def _kit_params() -> ET.Element:
    params = ET.Element("defaultParams")
    for key, value in _GLOBAL_PARAMS:
        params.set(key, value)
    for tag, values in _GLOBAL_GROUPS:
        group = ET.SubElement(params, tag)
        for key, value in values:
            group.set(key, value)
    return params


def _int_value(raw: str | None, default: int) -> int:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def _internal_sync(file_value: int) -> int:
    """Valeur interne d'un ``syncLevel`` de fichier, à la magnitude 2."""
    if file_value == 0:
        return 0
    return max(1, min(9, file_value + 1 - MAGNITUDE))


def _label(text: str, fallback: str) -> str:
    """Nom lisible par la machine : ASCII, sans caractère interdit."""
    clean = safe_deluge_name(text or "") if text else ""
    return clean if clean and clean != tr("SANS NOM") else fallback


def ascii_label(text: str) -> str:
    """Nom de clip : ASCII (l'écran de la machine n'a pas d'accents)."""
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.encode("ascii", "ignore").decode("ascii").strip()[:31]


# --------------------------------------------------------------------------- #
# Clips, sections, morceau
# --------------------------------------------------------------------------- #

@dataclass
class ClipSpec:
    """Un clip : ``rows`` donne les notes par rangée — note MIDI pour un
    synthé, index de rangée pour un kit. ``length`` est en ticks (384 par
    mesure)."""

    track: int
    length: int
    rows: dict[int, list[Note]] = field(default_factory=dict)
    section: int = 0
    name: str = ""
    playing: bool = True
    colour: int | None = None

    @property
    def note_count(self) -> int:
        return sum(len(notes) for notes in self.rows.values())


@dataclass
class SectionSpec:
    """Une section jouée dans l'ordre ; ``length`` en ticks."""

    name: str
    length: int


@dataclass
class SongSpec:
    """Tout ce qu'il faut pour écrire un morceau."""

    name: str
    bpm: float = 120.0
    root: int = 0
    mode_notes: tuple[int, ...] = (0, 2, 4, 5, 7, 9, 11)
    tracks: list[Track] = field(default_factory=list)
    clips: list[ClipSpec] = field(default_factory=list)
    #: Sections dans l'ordre de jeu : elles fixent les enchaînements et
    #: l'arrangement. Sans section, tous les clips bouclent ensemble.
    sections: list[SectionSpec] = field(default_factory=list)
    #: Ce que le morceau contient, en une ligne par élément, pour le plan.
    summary: list[str] = field(default_factory=list)

    @property
    def samples(self) -> list[str]:
        out: list[str] = []
        for track in self.tracks:
            for rel in track.samples:
                if rel not in out:
                    out.append(rel)
        return out


def tempo_attrs(bpm: float, magnitude: int = MAGNITUDE) -> tuple[int, int]:
    """``timePerTimerTick`` et ``timerTickFraction`` d'un tempo.

    ``Song::setBPMInner`` : un tick d'horloge dure ``110250 / (BPM × 2^m)``
    échantillons, rangé en virgule fixe 32.32 ; la fraction s'écrit en
    entier signé. 120 BPM donnent 229 et −1342177280, comme ``DEFAULT.XML``.
    """
    bpm = max(1.0, min(999.0, float(bpm)))
    ticks = 110250.0 / (bpm * (2 ** int(magnitude)))
    big = int(ticks * 4294967296.0)
    whole, fraction = big >> 32, big & 0xFFFFFFFF
    if fraction >= 1 << 31:
        fraction -= 1 << 32
    return whole, fraction


def _clean_notes(notes: list[Note], length: int) -> list[Note]:
    """Notes triées, dans le clip, sans chevauchement.

    Le firmware **ignore** une note qui commence avant la fin de la
    précédente sur la même rangée (``NoteRow::readFromFile`` : ``pos <
    minPos``) : on raccourcit la première plutôt que de perdre la seconde.
    """
    kept: list[Note] = []
    for note in sorted(notes, key=lambda n: (int(n.pos), -int(n.length))):
        pos = int(note.pos)
        if pos < 0 or pos >= length:
            continue
        if kept and kept[-1].pos == pos:
            continue
        span = max(1, min(int(note.length), length - pos))
        velocity = max(1, min(127, int(note.velocity)))
        if kept and kept[-1].pos + kept[-1].length > pos:
            kept[-1].length = max(1, pos - kept[-1].pos)
        kept.append(Note(pos=pos, length=span, velocity=velocity,
                         condition=int(note.condition), lift=int(note.lift
                                                                 or 64)))
    return kept


def events_to_rows(events, length: int, offset: float = 0.0
                   ) -> dict[int, list[Note]]:
    """Notes d'une partie (:class:`~delugeapp.core.accomp.NoteEvent`, en pas
    de double-croche) -> rangées d'un clip de synthé, en ticks.

    ``offset`` (en pas) est retranché : il ramène une section au début de son
    clip. Les vélocités en pourcentage deviennent 1–127 comme dans
    :meth:`~delugeapp.core.rhythm.Pattern.to_notes`.
    """
    rows: dict[int, list[Note]] = {}
    for event in events or ():
        pos = int(round((float(event.start) - offset) * STEP))
        span = max(1, int(round(float(event.length) * STEP)))
        velocity = max(1, min(127, int(int(event.velocity) * 127 // 100)))
        rows.setdefault(int(event.note), []).append(
            Note(pos=pos, length=span, velocity=velocity, condition=20,
                 lift=64))
    out = {y: _clean_notes(notes, length) for y, notes in rows.items()}
    return {y: notes for y, notes in out.items() if notes}


def pattern_rows(pattern, row_map: dict[str, int], length: int | None = None,
                 start: float = 0.0, end: float | None = None
                 ) -> tuple[dict[int, list[Note]], int]:
    """Motif rythmique -> rangées d'un clip de kit.

    Les pas sont convertis à la résolution du morceau : 24 ticks par
    double-croche quand le motif compte 16 pas par mesure, 32 s'il en
    compte 12. ``start``/``end`` (en pas) découpent une tranche du motif.
    Rend ``(rangées, longueur du clip en ticks)``.
    """
    steps_total = max(1, int(getattr(pattern, "steps", 16) or 16))
    bars = max(1.0, steps_total / 16.0)
    per_bar = steps_total / bars
    per_step = BAR / per_bar
    first = float(start)
    last = float(end) if end is not None else float(steps_total)
    if length is None:
        length = int(round((last - first) * per_step))
        length = max(STEP, length)
    rows: dict[int, list[Note]] = {}
    for track, steps in (getattr(pattern, "tracks", None) or {}).items():
        row = row_map.get(track)
        if row is None:
            continue
        for step in steps:
            pos_steps = float(step.pos)
            if not first <= pos_steps < last:
                continue
            probability = int(getattr(step, "probability", 100) or 100)
            condition = 20 if probability >= 100 else max(
                0, min(20, int(probability / 5)))
            rows.setdefault(int(row), []).append(Note(
                pos=int(round((pos_steps - first) * per_step)),
                length=max(1, int(round(float(getattr(step, "length", 1)
                                              or 1) * per_step))),
                velocity=max(1, min(127, int(step.velocity * 127 // 100))),
                condition=condition, lift=64))
    out = {y: _clean_notes(notes, length) for y, notes in rows.items()}
    return {y: notes for y, notes in out.items() if notes}, int(length)


def fold(rows: dict[int, list[Note]], length: int
         ) -> tuple[dict[int, list[Note]], int]:
    """Plus courte boucle qui rejoue exactement le clip.

    Une partie qui se répète — les accords d'une progression de quatre
    mesures sur une section de seize, une batterie d'une mesure — tient dans
    un clip court qui boucle, comme on les fait sur la machine. La période
    doit diviser la longueur, et aucune note ne doit en déborder ; sinon le
    clip garde sa longueur.
    """
    bars = length // BAR
    if bars <= 1 or bars * BAR != length:
        return rows, length
    for period_bars in range(1, bars):
        if bars % period_bars:
            continue
        period = period_bars * BAR
        if _repeats(rows, period, bars // period_bars):
            folded = {y: [Note(pos=n.pos, length=n.length,
                               velocity=n.velocity, condition=n.condition,
                               lift=n.lift)
                          for n in notes if n.pos < period]
                      for y, notes in rows.items()}
            return {y: n for y, n in folded.items() if n}, period
    return rows, length


def _repeats(rows: dict[int, list[Note]], period: int, count: int) -> bool:
    for notes in rows.values():
        slices: dict[int, list[tuple]] = {}
        for note in notes:
            within = note.pos % period
            if within + note.length > period:
                return False
            slices.setdefault(note.pos // period, []).append(
                (within, note.length, note.velocity, note.condition,
                 note.lift))
        reference = slices.get(0, [])
        if not reference:
            return False
        if any(slices.get(k, []) != reference for k in range(count)):
            return False
    return bool(rows)


# --------------------------------------------------------------------------- #
# Assemblage du XML
# --------------------------------------------------------------------------- #

def _visual_row(note: int, root: int, mode_notes: tuple[int, ...]) -> int:
    """``Song::getYVisualFromYNote`` en mode gamme."""
    relative = note - root
    within = (relative + 120) % 12
    octave = (relative + 120 - within) // 12 - 10
    visual = 0
    for index, interval in enumerate(mode_notes):
        if interval <= within:
            visual = index
    return visual + octave * len(mode_notes) + root


def _in_scale(note: int, root: int, mode_notes: tuple[int, ...]) -> bool:
    return (note - root) % 12 in set(mode_notes)


def _y_scroll(rows: dict[int, list[Note]], in_key: bool, root: int,
              mode_notes: tuple[int, ...]) -> int:
    """Défilement qui centre les notes du clip sur les huit rangées."""
    if not rows:
        return 60 if not in_key else _visual_row(60, root, mode_notes)
    values = sorted(_visual_row(y, root, mode_notes) if in_key else y
                    for y in rows)
    low, high = values[0], values[-1]
    spread = high - low
    if spread >= 7:
        return low
    return low - (7 - spread) // 2


#: Couleur (``colourOffset``) d'un clip, par piste : des teintes espacées.
_COLOUR_STEP = 13


def _ordered_attrs(el: ET.Element, pairs) -> None:
    for key, value in pairs:
        el.set(key, str(value))


def _global_params(tag: str, tempo: int | None) -> ET.Element:
    el = ET.Element(tag)
    _ordered_attrs(el, _GLOBAL_PARAMS)
    el.set("tempo", "0x%08X" % (int(tempo) & 0xFFFFFFFF) if tempo is not None
           else "0x00000000")
    for name, values in _GLOBAL_GROUPS:
        _ordered_attrs(ET.SubElement(el, name), values)
    return el


def _unique_names(spec: SongSpec) -> list[str]:
    """Nom de chaque piste, rendu unique par type et par dossier.

    Un clip retrouve son instrument par son type, son nom et son dossier, la
    casse ignorée (``Song::getInstrumentFromPresetSlot``) : deux synthés
    homonymes, et les clips du second joueraient le premier.
    """
    seen: set[tuple[str, str, str]] = set()
    names: list[str] = []
    for track in spec.tracks:
        base = track.name or ("KIT" if track.is_kit else "SYNTH")
        candidate, index = base, 2
        while (track.kind, track.folder.upper(), candidate.upper()) in seen:
            candidate = "%s %d" % (base, index)
            index += 1
        seen.add((track.kind, track.folder.upper(), candidate.upper()))
        names.append(candidate)
    return names


def _clip_element(spec: SongSpec, clip: ClipSpec, name: str,
                  colour: int) -> ET.Element:
    track = spec.tracks[clip.track]
    el = ET.Element("instrumentClip")
    rows = clip.rows
    if track.is_kit:
        # Ce que la machine écrit pour les cinq clips de kit des morceaux
        # c1.2.1 de la carte ; la gamme n'y change rien.
        in_key = True
        y_scroll = 0
    else:
        in_key = all(_in_scale(y, spec.root, spec.mode_notes) for y in rows)
        y_scroll = _y_scroll(rows, in_key, spec.root, spec.mode_notes)
    el.set("clipName", ascii_label(clip.name))
    el.set("inKeyMode", "1" if in_key else "0")
    el.set("yScroll", str(y_scroll))
    el.set("yScrollKeyboard", "50")
    if track.is_kit:
        el.set("affectEntire", "0")
    el.set("instrumentPresetName", name)
    el.set("instrumentPresetFolder", track.folder)
    el.set("isPlaying", "1" if clip.playing else "0")
    el.set("isSoloing", "0")
    el.set("isArmedForRecording", "1")
    el.set("length", str(int(clip.length)))
    el.set("colourOffset", str(int(colour)))
    el.set("section", str(int(clip.section)))
    el.set("keyboardLayout", "4" if track.is_kit else "0")
    el.set("keyboardRowInterval", "5")
    el.set("drumsScrollOffset", "0")
    el.set("drumsEdgeSize", "4")
    el.set("inKeyScrollOffset", "21")
    el.set("inKeyRowInterval", "3")

    if track.is_kit:
        params = copy.deepcopy(track.params)
        params.tag = "kitParams"
        el.append(params)
    else:
        arp = ET.SubElement(el, "arpeggiator")
        for key in ("mode", "syncLevel", "numOctaves", "syncType", "arpMode",
                    "noteMode", "octaveMode", "mpeVelocity"):
            arp.set(key, track.arp.get(key, ""))
        params = copy.deepcopy(track.params)
        params.tag = "soundParams"
        el.append(params)

    controls = ET.SubElement(el, "columnControls")
    ET.SubElement(controls, "leftCol").set("type", "velocity")
    ET.SubElement(controls, "rightCol").set("type", "mod")

    holder = ET.SubElement(el, "noteRows")
    if track.is_kit:
        # Une rangée par son du kit, dans l'ordre des sons : c'est ainsi que
        # la machine les écrit, et chaque rangée porte les réglages du son.
        for drum, drum_params in enumerate(track.drum_params):
            row = ET.SubElement(holder, "noteRow")
            row.set("colourOffset", str((drum * 7) % 72))
            notes = rows.get(drum, [])
            if notes:
                row.set("noteDataWithLift", encode_notes(notes, True))
            row.set("drumIndex", str(drum))
            sound_params = copy.deepcopy(drum_params)
            sound_params.tag = "soundParams"
            row.append(sound_params)
    else:
        for y in sorted(rows):
            row = ET.SubElement(holder, "noteRow")
            row.set("y", str(int(y)))
            row.set("noteDataWithLift", encode_notes(rows[y], True))
    if len(holder) == 0:
        el.remove(holder)
    return el


def _session_order(spec: SongSpec) -> list[int]:
    """Index des clips de ``spec`` dans l'ordre des ``sessionClips``.

    La première section en haut (index les plus élevés) : en disposition
    « rangées », la machine passe à la section du clip d'en dessous.
    """
    by_section = sorted(range(len(spec.clips)),
                        key=lambda i: (spec.clips[i].section, i))
    return list(reversed(by_section))


def _section_repeats(spec: SongSpec) -> dict[int, int]:
    """Répétitions de chaque section : sa longueur sur son plus long clip."""
    out: dict[int, int] = {}
    for index, section in enumerate(spec.sections[:MAX_SECTIONS]):
        lengths = [c.length for c in spec.clips if c.section == index]
        if not lengths:
            continue
        longest = max(lengths)
        out[index] = max(1, int(round(section.length / float(longest))))
    return out


def _instances(spec: SongSpec, order: list[int]) -> dict[int, str]:
    """``clipInstances`` de chaque piste : un clip par section, à sa place."""
    if not spec.sections:
        return {}
    starts, position = [], 0
    for section in spec.sections:
        starts.append(position)
        position += int(section.length)
    session_index = {clip: rank for rank, clip in enumerate(order)}
    per_track: dict[int, list[tuple[int, int, int]]] = {}
    for clip_index, clip in enumerate(spec.clips):
        if not 0 <= clip.section < len(spec.sections):
            continue
        per_track.setdefault(clip.track, []).append(
            (starts[clip.section], int(spec.sections[clip.section].length),
             session_index[clip_index]))
    out: dict[int, str] = {}
    for track, instances in per_track.items():
        instances.sort()
        blob, last_end = ["0x"], 0
        for pos, length, code in instances:
            if pos < last_end or length <= 0:
                continue
            blob.append("%08X%08X%08X" % (pos, length, code))
            last_end = pos + length
        if len(blob) > 1:
            out[track] = "".join(blob)
    return out


def _instrument_element(track: Track, name: str,
                        instances: str | None) -> ET.Element:
    el = ET.Element(track.body.tag)
    el.set("presetName", name)
    el.set("presetFolder", track.folder)
    el.set("defaultVelocity", _DEFAULT_VELOCITY)
    el.set("isArmedForRecording", "0")
    el.set("activeModFunction", "0")
    if instances:
        el.set("clipInstances", instances)
    el.set("colour", "0")
    for key, value in track.body.attrib.items():
        el.set(key, value)
    for child in track.body:
        el.append(copy.deepcopy(child))
    return el


#: Couleurs de la vignette, par piste (les teintes des parties de l'appli).
_PREVIEW_COLOURS = ((0, 200, 220), (255, 170, 0), (220, 60, 220),
                    (60, 220, 90), (255, 70, 70), (90, 120, 255),
                    (240, 230, 60), (255, 120, 180))
_SECTION_COLOURS = ((255, 80, 0), (0, 160, 255), (180, 0, 255),
                    (0, 220, 120), (255, 0, 120), (255, 200, 0),
                    (0, 255, 255), (120, 255, 0), (255, 120, 0),
                    (120, 0, 255), (255, 0, 0), (0, 120, 255))


def preview(spec: SongSpec, order: list[int], y_scroll: int) -> str:
    """Vignette de la vue morceau telle qu'elle s'ouvrira : une rangée par
    clip, la rangée 0 **en bas** comme sur la machine, les notes de chaque
    clip réparties sur seize pads, la section et l'état dans la barre."""
    grid = [[(0, 0, 0)] * PREVIEW_COLS for _ in range(PREVIEW_ROWS)]
    for y in range(PREVIEW_ROWS):
        rank = y_scroll + y
        if not 0 <= rank < len(order):
            continue
        clip = spec.clips[order[rank]]
        colour = _PREVIEW_COLOURS[clip.track % len(_PREVIEW_COLOURS)]
        dim = tuple(c // 6 for c in colour)
        lit = [False] * 16
        span = max(1, clip.length)
        for notes in clip.rows.values():
            for note in notes:
                lit[min(15, note.pos * 16 // span)] = True
        for x in range(16):
            grid[y][x] = colour if lit[x] else dim
        grid[y][16] = (0, 200, 0) if clip.playing else (60, 50, 0)
        grid[y][17] = _SECTION_COLOURS[clip.section % len(_SECTION_COLOURS)]
    return "".join("%02X%02X%02X" % pixel for row in grid for pixel in row)


def build(spec: SongSpec) -> dxml.DelugeDoc:
    """Le document du morceau, au format c1.2.1."""
    if not spec.tracks or not spec.clips:
        raise ValueError(tr("un morceau sans instrument ni clip ne s'écrit "
                            "pas"))
    if len(spec.sections) > MAX_SECTIONS:
        raise ValueError(tr("au plus %d sections") % MAX_SECTIONS)
    order = _session_order(spec)
    names = _unique_names(spec)
    repeats = _section_repeats(spec)
    instances = _instances(spec, order)
    y_scroll = len(order) - PREVIEW_ROWS
    total = sum(s.length for s in spec.sections) or max(
        c.length for c in spec.clips)
    zoom = 192
    while zoom * 16 < total and zoom < 192 * 64:
        zoom *= 2
    time_per_tick, fraction = tempo_attrs(spec.bpm)

    root = ET.Element("song")
    _ordered_attrs(root, (
        ("firmwareVersion", FIRMWARE),
        ("earliestCompatibleFirmware", EARLIEST),
        ("previewNumPads", "144"),
        ("preview", preview(spec, order, y_scroll)),
        ("arrangementAutoScrollOn", "0"),
        ("xScroll", "0"), ("xZoom", "24"),
        ("yScrollSongView", y_scroll),
        ("yScrollArrangementView", len(spec.tracks) - PREVIEW_ROWS),
        ("xScrollArrangementView", "0"),
        ("xZoomArrangementView", zoom),
        ("timePerTimerTick", time_per_tick),
        ("timerTickFraction", fraction),
        ("rootNote", int(spec.root) % 12),
        ("inputTickMagnitude", MAGNITUDE),
        ("swingAmount", "0"), ("swingInterval", "7"),
        ("affectEntire", "0"), ("activeModFunction", "1"),
        ("modFXCurrentParam", "feedback"), ("currentFilterType", "lpf"),
        ("modFXType", "none"), ("lpfMode", "24dB"), ("hpfMode", "HPLadder"),
        ("filterRoute", "H2L"),
        ("songGridScrollX", "0"), ("songGridScrollY", "0"),
        ("sessionLayout", "0"),
    ))
    mode = ET.SubElement(root, "modeNotes")
    for interval in sorted(set(int(v) % 12 for v in spec.mode_notes)):
        ET.SubElement(mode, "modeNote").text = str(interval)
    reverb = ET.SubElement(root, "reverb")
    _ordered_attrs(reverb, _REVERB)
    _ordered_attrs(ET.SubElement(reverb, "compressor"), _REVERB_COMPRESSOR)
    _ordered_attrs(ET.SubElement(root, "delay"), _DELAY)
    _ordered_attrs(ET.SubElement(root, "sidechain"), _SIDECHAIN_SONG)
    _ordered_attrs(ET.SubElement(root, "audioCompressor"), _AUDIO_COMPRESSOR)
    root.append(_global_params("songParams",
                               int(round(float(spec.bpm) * 100))))

    instruments = ET.SubElement(root, "instruments")
    for index, track in enumerate(spec.tracks):
        instruments.append(_instrument_element(track, names[index],
                                               instances.get(index)))

    sections = ET.SubElement(root, "sections")
    for index in range(MAX_SECTIONS):
        section = ET.SubElement(sections, "section")
        section.set("id", str(index))
        section.set("numRepeats", str(repeats.get(index, 0)))

    session = ET.SubElement(root, "sessionClips")
    for clip_index in order:
        clip = spec.clips[clip_index]
        colour = clip.colour if clip.colour is not None else (
            (clip.track * _COLOUR_STEP) % 72 - 60)
        session.append(_clip_element(spec, clip, names[clip.track], colour))

    scales = ET.SubElement(root, "scales")
    ET.SubElement(scales, "userScale").text = "0"
    ET.SubElement(scales, "disabledPresetScales").text = "0"
    return dxml.DelugeDoc(path=None, root=root, preamble={}, dialect="attr",
                          firmware=FIRMWARE, repaired=[])


# --------------------------------------------------------------------------- #
# Écriture sur la carte
# --------------------------------------------------------------------------- #

#: Noms que la machine réserve : ``DEFAULT.XML`` est le morceau de départ.
_RESERVED = frozenset({"DEFAULT"})


@dataclass
class SongWrite:
    """Résultat d'une écriture, simulée ou réelle."""

    rel: str = ""
    applied: bool = False
    lines: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.rel) and not self.error

    @property
    def name(self) -> str:
        return Path(self.rel).stem if self.rel else ""

    def text(self) -> str:
        """Le plan en clair, pour la fenêtre de confirmation."""
        return "\n".join(self.lines)


def free_song_name(sd: SDCard, name: str) -> str:
    """Chemin relatif libre dans ``SONGS`` : un nom pris est numéroté."""
    base = safe_deluge_name(name or "MORCEAU")
    rel = "SONGS/%s.XML" % base
    index = 2
    while sd.abs(rel).exists() or Path(rel).stem.upper() in _RESERVED:
        rel = "SONGS/%s %d.XML" % (base, index)
        index += 1
        if index > 999:
            raise ValueError(tr("trop de morceaux portent déjà ce nom"))
    return rel


def write_song(sd: SDCard, spec: SongSpec, apply: bool = False) -> SongWrite:
    """Écrit le morceau dans ``SONGS`` — **simule** sans ``apply``.

    Le nom est assaini pour la carte, et numéroté s'il est pris : aucun
    fichier existant n'est jamais remplacé. Le résultat donne le plan
    (instruments, clips, échantillons absents) que l'interface montre avant
    de confirmer.
    """
    result = SongWrite()
    try:
        rel = free_song_name(sd, spec.name)
    except ValueError as exc:
        result.error = str(exc)
        return result
    problems = check_name(Path(rel).stem)
    if problems:
        result.error = " ".join(problems)
        return result
    result.rel = rel
    missing = [s for s in spec.samples if sd.resolve_sample(s) is None]
    result.missing = missing
    result.lines = _plan_lines(spec, rel, missing)
    try:
        doc = build(spec)
    except ValueError as exc:
        result.error = str(exc)
        return result
    if not apply:
        return result
    sd.require_writable()
    target = sd.abs(rel)
    if target.exists():
        # Créé entre la simulation et l'écriture : on ne remplace rien.
        result.error = tr("%s existe déjà : rien n'a été écrit") % rel
        return result
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        dxml.save(doc, target, backup=False)
    except (OSError, dxml.DelugeXMLError) as exc:
        log.exception("écriture du morceau impossible : %s", rel)
        result.error = tr("écriture impossible : %s") % exc
        return result
    sd.invalidate_cache()
    result.applied = True
    log.info("morceau écrit : %s (%d clips, %d instruments)", rel,
             len(spec.clips), len(spec.tracks))
    return result


def _plan_lines(spec: SongSpec, rel: str, missing: list[str]) -> list[str]:
    lines = [tr("Nouveau fichier : %s") % rel,
             tr("Tempo : %g BPM — %d instrument(s), %d clip(s)")
             % (round(float(spec.bpm), 2), len(spec.tracks),
                len(spec.clips))]
    if spec.sections:
        lines.append(tr("Sections : %s")
                     % " → ".join(tr(s.name) for s in spec.sections))
    lines.extend(spec.summary)
    if missing:
        lines.append(tr("%d échantillon(s) absent(s) de la carte : ces sons "
                        "resteront muets.") % len(missing))
    unconverted = sorted({rel for t in spec.tracks for rel in t.unconverted})
    if unconverted:
        lines.append(tr("%d échantillon(s) ancien(s) gardent leurs bornes "
                        "d'origine.") % len(unconverted))
    return lines


# --------------------------------------------------------------------------- #
# Recettes : un morceau par outil de création
# --------------------------------------------------------------------------- #

#: Ordre des parties d'un accompagnement, de bas en haut de l'écran.
PART_ORDER = ("Accords", "Basse", "Arpège", "Mélodie")


def part_label(part: str) -> str:
    """Nom de clip d'une partie, dans la langue de l'interface au moment où
    le morceau s'écrit : « Arpege » ou « Arpeggio ». ASCII : l'écran de la
    machine n'a pas d'accents. La partie elle-même (« Arpège ») reste la
    clé, en français."""
    return ascii_label(tr(part))

#: Pistes de batterie sans rôle connu (motif euclidien…) : on leur donne un
#: rôle de percussion libre, dans cet ordre.
SPARE_ROLES = ("Rim", "Shaker", "Claves", "Block", "Cowbell", "Tambourine",
               "ConH", "ConM", "ConL", "Guiro", "TomH", "TomM", "TomL",
               "Ride", "Crash")


def key_of(root: int | None, scale: str) -> tuple[int, tuple[int, ...]]:
    """Tonique (0–11) et ``<modeNotes>`` d'une gamme de l'application."""
    from . import theory

    if root is None:
        return 0, (0, 2, 4, 5, 7, 9, 11)
    notes = tuple(theory.deluge_mode_notes(scale or "majeur"))
    return int(root) % 12, notes


def part_roles(parts: dict) -> dict[str, str]:
    """Rôle du son de chaque partie, comme à l'écoute : une nappe pour des
    accords tenus, un accord bref sinon."""
    tenus = not any(e.length < 4 for e in parts.get("Accords", []))
    return {"Accords": "pad" if tenus else "stab", "Basse": "bass",
            "Arpège": "pluck", "Mélodie": "lead"}


def part_presets(parts: dict, genre: str, seed: int = 7) -> dict:
    """Les sons générés pour jouer chaque partie (ceux de l'écoute).

    L'arpégiateur est éteint, ``arpMode`` compris : l'arpège est déjà écrit
    note par note, et la machine, elle, lit ``arpMode`` — éteindre le seul
    ``mode`` laissait l'arpégiateur des sons générés en marche.
    """
    from . import synthgen

    out = {}
    for name, role in part_roles(parts).items():
        if name in parts:
            preset = synthgen.generate(synthgen.GenOptions(
                genre=genre or "techno", role=role, seed=seed))
            preset.sound.arp.mode = "off"
            preset.sound.arp.arp_mode = "off"
            out[name] = preset
    return out


def drum_rows(tracks, kit) -> dict[str, int]:
    """Rangée du kit qui joue chaque piste : même nom, sinon même rôle."""
    from .kitgen import row_role

    rows = list(getattr(kit, "rows", None) or [])
    by_name = {str(r.name or "").strip().upper(): i for i, r in enumerate(rows)}
    by_role: dict[str, int] = {}
    for index, row in enumerate(rows):
        by_role.setdefault(row_role(row).upper(), index)
    out: dict[str, int] = {}
    for track in tracks:
        key = str(track or "").strip().upper()
        if key in by_name:
            out[track] = by_name[key]
        elif key in by_role:
            out[track] = by_role[key]
    return out


def drum_kit_for(sd: SDCard, lib, genre: str, tracks, base=None,
                 seed: int = 1, name: str = "BATTERIE"):
    """Un kit de la carte qui joue toutes les pistes d'un motif.

    ``base`` (le kit de l'écoute, s'il existe) est complété, jamais modifié :
    les pistes qu'il ne couvre pas reçoivent un rôle — le leur s'il est
    connu, une percussion libre sinon — puis un échantillon de la
    bibliothèque. Rend ``(kit, {piste: rangée}, pistes sans son)`` ; ``kit``
    vaut ``None`` si la bibliothèque n'a rien à proposer.
    """
    from . import kitgen

    tracks = list(tracks)
    kit = copy.deepcopy(base) if base is not None and base.rows else None
    mapping = drum_rows(tracks, kit) if kit is not None else {}
    missing = [t for t in tracks if t not in mapping]
    if missing:
        known = {r.lower(): r for r in kitgen.ROLE_VOLUME}
        used = {kitgen.row_role(r) for r in (kit.rows if kit else [])}
        wanted: dict[str, str] = {}
        spare = [r for r in SPARE_ROLES if r not in used]
        for track in missing:
            role = known.get(str(track).strip().lower())
            if role is None or role in used:
                role = spare.pop(0) if spare else None
            if role is not None:
                wanted[track] = role
                used.add(role)
                if role in spare:
                    spare.remove(role)
        if wanted:
            try:
                extra = kitgen.build_kit(sd, lib, name,
                                         genre=genre or "techno", seed=seed,
                                         slots=list(wanted.values()))
            except Exception as exc:  # noqa: BLE001 - le kit reste partiel
                log.debug("kit complémentaire impossible : %s", exc)
                extra = None
            if extra is not None and extra.rows:
                new_rows = list(extra.rows)
                if kit is None:
                    kit = extra
                    kit.rows = []
                for row in new_rows:
                    role = kitgen.row_role(row)
                    for track, wanted_role in wanted.items():
                        if wanted_role == role and track not in mapping:
                            kit.rows.append(row)
                            mapping[track] = len(kit.rows) - 1
                            break
    if kit is not None and not kit.rows:
        kit = None
    lost = [t for t in tracks if t not in mapping]
    return kit, mapping, lost


def _synth_tracks(parts: dict, sounds: dict, arp: bool | None = False
                  ) -> tuple[list[Track], dict[str, int]]:
    tracks: list[Track] = []
    index: dict[str, int] = {}
    for part in PART_ORDER:
        preset = sounds.get(part)
        if part not in parts or not parts[part] or preset is None:
            continue
        tracks.append(synth_track(preset, arp=arp))
        index[part] = len(tracks) - 1
    return tracks, index


def _bars_text(length: int) -> str:
    bars = length / float(BAR)
    if abs(bars - round(bars)) < 1e-9:
        bars = int(round(bars))
        return plural(bars, N_("%d mesure"), N_("%d mesures")) % bars
    return tr("%s mesure") % decimal(bars, 2).rstrip("0").rstrip(",.")


def _add_drums(tracks, clips, summary, drums, kit, row_map, length=None,
               section: int = 0, playing: bool = True,
               label: str = "") -> None:
    if drums is None or kit is None or not row_map:
        return
    if not any(t.is_kit for t in tracks):
        tracks.append(kit_track(kit))
    track = next(i for i, t in enumerate(tracks) if t.is_kit)
    rows, clip_length = pattern_rows(drums, row_map, length=length)
    if not rows:
        return
    rows, clip_length = fold(rows, clip_length)
    clips.append(ClipSpec(track=track, length=clip_length, rows=rows,
                          section=section, playing=playing,
                          name=label or part_label("Batterie")))
    summary.append(tr("Batterie : kit %s, %d rangée(s), clip de %s") % (
        tracks[track].name, len(tracks[track].drum_params),
        _bars_text(clip_length)))


def progression_song(parts: dict, *, name: str, bpm: float, genre: str = "",
                     root: int | None = None, scale: str = "",
                     sounds: dict | None = None, drums=None, kit=None,
                     row_map: dict | None = None) -> SongSpec:
    """La progression et son accompagnement : un clip par partie, qui
    bouclent ensemble dès qu'on appuie sur PLAY.

    :param parts: les parties de :func:`delugeapp.core.accomp.accompany` ;
        la « Batterie » en notes General MIDI y est ignorée au profit de
        ``drums``, le motif, joué par ``kit`` selon ``row_map``.
    :param sounds: ``{partie: SynthPreset}`` ; à défaut, ceux de l'écoute.
    """
    from .accomp import total_steps

    tonal = {k: v for k, v in (parts or {}).items() if k != "Batterie" and v}
    if not tonal:
        raise ValueError(tr("aucune partie à écrire"))
    sounds = sounds if sounds is not None else part_presets(tonal, genre)
    length = int(total_steps(tonal)) * STEP
    tracks, index = _synth_tracks(tonal, sounds)
    clips: list[ClipSpec] = []
    summary: list[str] = []
    for part, track in index.items():
        rows, clip_length = fold(events_to_rows(tonal[part], length), length)
        clips.append(ClipSpec(track=track, length=clip_length, rows=rows,
                              name=part_label(part)))
        summary.append(tr("%s : %s, clip de %s") % (
            tr(part), tracks[track].name, _bars_text(clip_length)))
    _add_drums(tracks, clips, summary, drums, kit, row_map, length)
    key_root, mode = key_of(root, scale)
    return SongSpec(name=name, bpm=bpm, root=key_root, mode_notes=mode,
                    tracks=tracks, clips=clips, summary=summary)


def pattern_song(pattern, kit, row_map: dict, *, name: str, bpm: float,
                 version: str | None = None, kit_name: str = "",
                 folder: str = "KITS", sd: SDCard | None = None) -> SongSpec:
    """Un motif rythmique joué par un kit : un clip qui boucle.

    ``kit`` est un :class:`~delugeapp.core.model.Kit` (généré) ou l'élément
    ``<kit>`` d'un kit de la carte, avec sa ``version`` et son nom. ``sd``
    est **nécessaire** pour un kit d'avant 2.1 : ses bornes en millisecondes
    ne se convertissent qu'en lisant les échantillons — sans elle, la machine
    ignorerait ces bornes et jouerait chaque échantillon en entier.
    """
    track = kit_track(kit, name=kit_name, version=version, folder=folder,
                      sd=sd)
    rows, length = pattern_rows(pattern, row_map)
    if not rows:
        raise ValueError(tr("le motif ne joue aucune rangée du kit"))
    rows, length = fold(rows, length)
    clip = ClipSpec(track=0, length=length, rows=rows,
                    name=part_label("Batterie"))
    summary = [tr("Batterie : kit %s, %d rangée(s), clip de %s") % (
        track.name, len(track.drum_params), _bars_text(length))]
    return SongSpec(name=name, bpm=bpm, tracks=[track], clips=[clip],
                    summary=summary)


def sketch_song(result, *, name: str, bpm: float, genre: str = "",
                root: int | None = None, scale: str = "",
                sounds: dict | None = None, kit=None,
                row_map: dict | None = None) -> SongSpec:
    """L'esquisse : une section du Deluge par section du modèle.

    Chaque section a ses clips — la partie que son rôle appelle, réduite à
    sa plus courte boucle — et un nombre de répétitions qui couvre sa durée :
    lancée pendant la lecture, une section enchaîne toutes les suivantes
    jusqu'à la fin. L'arrangement place les mêmes clips sur toute la durée
    du morceau.
    """
    sections = list(getattr(result, "sections", []) or [])
    if not sections:
        raise ValueError(tr("esquisse vide"))
    if len(sections) > MAX_SECTIONS:
        raise ValueError(tr("le Deluge connaît %d sections au plus")
                         % MAX_SECTIONS)
    parts = {k: v for k, v in (result.parts or {}).items()
             if k != "Batterie" and v}
    sounds = sounds if sounds is not None else part_presets(parts, genre)
    tracks, index = _synth_tracks(parts, sounds)
    drums = getattr(result, "drums", None)
    with_drums = drums is not None and kit is not None and bool(row_map)
    if with_drums:
        tracks.append(kit_track(kit))
    kit_index = len(tracks) - 1 if with_drums else None
    clips: list[ClipSpec] = []
    for number, section in enumerate(sections):
        first = int(section.start) * 16
        last = first + int(section.bars) * 16
        span = int(section.bars) * BAR
        playing = number == 0
        for part, track in index.items():
            if part not in section.parts:
                continue
            events = [e for e in parts[part] if first <= e.start < last]
            rows = events_to_rows(events, span, offset=first)
            if not rows:
                continue
            rows, clip_length = fold(rows, span)
            clips.append(ClipSpec(track=track, length=clip_length, rows=rows,
                                  section=number, playing=playing,
                                  name="%s %s" % (tr(section.name),
                                                  part_label(part))))
        if kit_index is not None and any(p.startswith("Batterie")
                                         for p in section.parts):
            rows, _length = pattern_rows(drums, row_map, length=span,
                                         start=first, end=last)
            if rows:
                rows, clip_length = fold(rows, span)
                clips.append(ClipSpec(track=kit_index, length=clip_length,
                                      rows=rows, section=number,
                                      playing=playing,
                                      name="%s %s" % (
                                          tr(section.name),
                                          part_label("Batterie"))))
    if not clips:
        raise ValueError(tr("aucune partie à écrire"))
    key_root, mode = key_of(root, scale)
    summary = [tr("Parties : %s") % ", ".join(
        tr(p) for p in [p for p in PART_ORDER if p in index]
        + (["Batterie"] if kit_index is not None else []))]
    return SongSpec(name=name, bpm=bpm, root=key_root, mode_notes=mode,
                    tracks=tracks, clips=clips, summary=summary,
                    sections=[SectionSpec(s.name, int(s.bars) * BAR)
                              for s in sections])


#: Partie qui fait entendre un son, selon son rôle.
ROLE_PART = {"bass": "Basse", "lead": "Mélodie", "pluck": "Arpège",
             "arp": "Arpège", "pad": "Accords", "keys": "Accords",
             "stab": "Accords", "drone": "Accords", "bell": "Accords",
             "fx": "Accords"}


def preset_song(preset, *, name: str, bpm: float, genre: str = "",
                role: str = "", seed: int = 1, root: int = 57,
                scale: str = "mineur", drums=None, kit=None,
                row_map: dict | None = None) -> SongSpec:
    """Un preset mis en situation : une phrase de quatre mesures faite pour
    son rôle (basse, accords, arpège, mélodie), sur une progression du genre,
    avec la batterie du genre si la carte en fournit une.

    Le preset garde **son** arpégiateur : s'il est allumé, la phrase devient
    des accords tenus (ou la fondamentale, pour une basse), que la machine
    arpège elle-même.
    """
    from . import accomp, sketch

    progression = sketch.default_progression(genre, seed=seed, root=root,
                                             scale=scale)
    part = ROLE_PART.get(str(role or "").lower(), "Accords")
    sound = getattr(preset, "sound", None)
    arp_on = bool(sound is not None and sound.arp.is_on)
    if arp_on and part != "Basse":
        part = "Accords"
    styles = accomp.genre_styles(genre)
    if part == "Basse":
        events = accomp.bass_part(progression,
                                  "fondamentale" if arp_on else styles[1])
    elif part == "Mélodie":
        events = accomp.melody_part(progression, root=root, scale=scale,
                                    genre=genre, seed=seed)
    elif part == "Arpège":
        events = accomp.arp_part(progression, seed=seed)
    else:
        held = arp_on or str(role).lower() in ("pad", "drone", "bell", "fx",
                                               "keys")
        events = accomp.chord_part(progression, "tenu" if held else styles[0])
    parts = {part: events}
    track = synth_track(preset, arp=None)
    length = int(accomp.total_steps(parts)) * STEP
    rows, clip_length = fold(events_to_rows(events, length), length)
    tracks = [track]
    clips = [ClipSpec(track=0, length=clip_length, rows=rows,
                      name=part_label(part))]
    summary = [tr("%s : %s, clip de %s") % (tr(part), track.name,
                                            _bars_text(clip_length))]
    _add_drums(tracks, clips, summary, drums, kit, row_map, length)
    key_root, mode = key_of(root, scale)
    return SongSpec(name=name, bpm=bpm, root=key_root, mode_notes=mode,
                    tracks=tracks, clips=clips, summary=summary)


def slices_song(sliceset, *, name: str, bpm: float | None = None) -> SongSpec:
    """La boucle découpée, rejouée : le kit des tranches et un clip qui
    déclenche chaque tranche à sa place d'origine.

    Le tempo est celui de la boucle s'il est connu ; sinon celui qui fait
    tenir la boucle dans un nombre entier de mesures, entre 80 et 180 BPM.
    """
    from . import slicer

    if not sliceset or not sliceset.sr:
        raise ValueError(tr("aucune tranche"))
    seconds = sliceset.duration
    if not bpm or bpm <= 0:
        bpm = float(sliceset.bpm or 0) or loop_tempo(seconds)
    per_second = (BAR / 4.0) * float(bpm) / 60.0
    quarter = BAR // 4
    length = max(quarter, int(round(seconds * per_second / quarter)) * quarter)
    kit = slicer.slices_to_kit(sliceset, name)
    rows: dict[int, list[Note]] = {}
    for index, part in enumerate(sliceset.slices):
        pos = int(round(part.start / float(sliceset.sr) * per_second))
        span = max(1, int(round(part.frames / float(sliceset.sr)
                                * per_second)))
        notes = _clean_notes([Note(pos=pos, length=span, velocity=127,
                                   condition=20, lift=64)], length)
        if notes:
            rows[index] = notes
    track = kit_track(kit)
    clip = ClipSpec(track=0, length=length, rows=rows,
                    name=ascii_label(tr("Boucle")))
    summary = [tr("Boucle : %d tranche(s) de %s, clip de %s à %g BPM") % (
        len(sliceset.slices), Path(sliceset.rel).name, _bars_text(length),
        round(float(bpm), 2))]
    return SongSpec(name=name, bpm=float(bpm), tracks=[track], clips=[clip],
                    summary=summary)


def loop_tempo(seconds: float, low: float = 80.0, high: float = 180.0
               ) -> float:
    """Tempo qui fait tenir une boucle dans un nombre entier de mesures.

    Le plus proche de 120 BPM parmi 1, 2, 4, 8 ou 16 mesures ; 120 si rien
    ne tombe entre ``low`` et ``high``.
    """
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return 120.0
    if seconds <= 0:
        return 120.0
    best = None
    for bars in (1, 2, 4, 8, 16):
        tempo = bars * 4 * 60.0 / seconds
        if low <= tempo <= high and (best is None
                                     or abs(tempo - 120) < abs(best - 120)):
            best = tempo
    return round(best, 2) if best is not None else 120.0
