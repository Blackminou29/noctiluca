# -*- coding: utf-8 -*-
"""Modèle objet des fichiers Deluge : sons, presets de synthé, kits et morceaux.

Le module lit ET écrit les deux dialectes XML du Deluge (§1.2) : il s'appuie
sur :mod:`delugeapp.core.dxml` qui masque la différence « attribut » / « élément ».
Aucune dépendance Qt, aucune dépendance externe.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable
import xml.etree.ElementTree as ET

from . import dxml
from . import theory as _theory
from .dxml import DelugeDoc
from .fixedpoint import (
    INT32_MAX,
    INT32_MIN,
    format_fixed,
    parse_fixed,
    parse_int,
    to_display,
)

log = logging.getLogger(__name__)

__all__ = [
    "PARAM_KEYS", "PARAM_BIPOLAR", "DEFAULT_PARAMS", "DEFAULT_MOD_KNOBS",
    "EQ_KEYS", "ENV_KEYS", "TICKS_PER_BAR", "TICKS_PER_QUARTER",
    "ticks_per_bar",
    "PATCH_CABLE_FULL",
    "Zone", "SampleRange", "Osc", "Envelope", "LFO", "PatchCable",
    "Arpeggiator", "Modulator", "ModKnob", "Sound", "SynthPreset", "KitRow", "Kit",
    "Note", "NoteRow", "Clip", "Song", "tempo_from_song_attrs",
    "REPEAT_CUT", "REPEAT_ONCE", "REPEAT_LOOP", "REPEAT_STRETCH",
    "repeat_mode_for",
    "decode_notes", "encode_notes", "read_params", "write_params",
]

# --------------------------------------------------------------------------
# Constantes de format
# --------------------------------------------------------------------------

#: Résolution de l'horloge **extérieure** : 24 ticks par noire, comme une
#: horloge MIDI. C'est elle qu'emploie la formule du tempo.
TICKS_PER_QUARTER = 24
#: Une mesure 4/4 à magnitude nulle.
TICKS_PER_BAR = 96


def ticks_per_bar(input_tick_magnitude: int) -> int:
    """Ticks d'une mesure 4/4 dans un morceau de cette magnitude.

    **Correction mesurée (14 octobre 2026).** Les positions et longueurs de
    notes ne sont pas en 24e de noire : le firmware compte une mesure comme
    ``96 << inputTickMagnitude`` (``Song::getBarLength``, tag
    ``release_1_2_1``). Vérifié sur les notes des 46 morceaux de la carte :
    à magnitude 1 (les 40 morceaux 3.0.4) les clips font 192, 384, 768
    ticks et la double croche vaut 12 ; à magnitude 2 (les 6 morceaux
    c1.2.1) 384, 1 536, 3 072 et la double croche vaut 24.
    """
    m = int(input_tick_magnitude)
    return TICKS_PER_BAR << m if m >= 0 else max(1, TICKS_PER_BAR >> -m)

#: Échelle pleine d'un câble de modulation : ``0x40000000``, soit la moitié
#: de l'échelle des autres paramètres. Mesuré sur les 7 025 câbles de la
#: carte : aucune valeur ne la dépasse, et 1 925 s'y arrêtent exactement.
PATCH_CABLE_FULL = 0x40000000

#: Tous les noms de paramètres « hexadécimaux » connus, dans l'ordre d'écriture
#: du firmware (les fichiers réels de la carte suivent cet ordre).
PARAM_KEYS: tuple[str, ...] = (
    "arpeggiatorGate",
    "portamento",
    "compressorShape",
    "sidechainCompressorShape",
    "oscAVolume",
    "oscAPulseWidth",
    "oscAWavetablePosition",
    "oscAPitchAdjust",
    "oscBVolume",
    "oscBPulseWidth",
    "oscBWavetablePosition",
    "oscBPitchAdjust",
    "noiseVolume",
    "volume",
    "pan",
    "pitchAdjust",
    "lpfFrequency",
    "lpfResonance",
    "lpfMorph",
    "hpfFrequency",
    "hpfResonance",
    "hpfMorph",
    "lfo1Rate",
    "lfo2Rate",
    "modulator1Amount",
    "modulator1Feedback",
    "modulator2Amount",
    "modulator2Feedback",
    "carrier1Feedback",
    "carrier2Feedback",
    "modFXRate",
    "modFXDepth",
    "delayRate",
    "delayFeedback",
    "reverbAmount",
    "arpeggiatorRate",
    "stutterRate",
    "sampleRateReduction",
    "bitCrush",
    "modFXOffset",
    "modFXFeedback",
    "compressorThreshold",
    "waveFold",
    "ratchetProbability",
    "ratchetAmount",
    "sequenceLength",
    "rhythm",
    "tempo",
)

_PARAM_SET = frozenset(PARAM_KEYS)

#: Paramètres de l'égaliseur, rangés à part dans ``Sound.eq``.
EQ_KEYS: tuple[str, ...] = ("bass", "treble", "bassFrequency", "trebleFrequency")

#: Segments d'enveloppe, dans l'ordre ADSR.
ENV_KEYS: tuple[str, ...] = ("attack", "decay", "sustain", "release")

#: Paramètres bipolaires : 0x00000000 est le milieu, l'écran affiche -25..+25.
PARAM_BIPOLAR: frozenset[str] = frozenset({
    "pan",
    "pitchAdjust",
    "oscAPitchAdjust",
    "oscBPitchAdjust",
    "bass",
    "treble",
    "bassFrequency",
    "trebleFrequency",
})

#: Groupes imbriqués du dialecte « éléments » -> nom plat canonique.
_PARAM_GROUPS: dict[str, dict[str, str]] = {
    "lpf": {"frequency": "lpfFrequency", "resonance": "lpfResonance"},
    "hpf": {"frequency": "hpfFrequency", "resonance": "hpfResonance"},
    "delay": {"rate": "delayRate", "feedback": "delayFeedback"},
}
_GROUP_OF_FLAT: dict[str, tuple[str, str]] = {
    flat: (grp, sub) for grp, subs in _PARAM_GROUPS.items() for sub, flat in subs.items()
}

_DEFAULT_PARAMS_HEX: dict[str, str] = {
    "arpeggiatorGate": "0x00000000",
    "portamento": "0x80000000",
    "compressorShape": "0xDC28F5B2",
    "oscAVolume": "0x7FFFFFFF",
    "oscAPulseWidth": "0x00000000",
    "oscAWavetablePosition": "0x00000000",
    "oscBVolume": "0x80000000",
    "oscBPulseWidth": "0x00000000",
    "oscBWavetablePosition": "0x00000000",
    "noiseVolume": "0x80000000",
    "volume": "0x7FFFFFFF",
    "pan": "0x00000000",
    "lpfFrequency": "0x7FFFFFFF",
    "lpfResonance": "0x80000000",
    "hpfFrequency": "0x80000000",
    "hpfResonance": "0x80000000",
    "lfo1Rate": "0x1999997E",
    "lfo2Rate": "0x00000000",
    "modulator1Amount": "0x80000000",
    "modulator1Feedback": "0x80000000",
    "modulator2Amount": "0x80000000",
    "modulator2Feedback": "0x80000000",
    "carrier1Feedback": "0x80000000",
    "carrier2Feedback": "0x80000000",
    "modFXRate": "0x00000000",
    "modFXDepth": "0x00000000",
    "delayRate": "0x00000000",
    "delayFeedback": "0x80000000",
    "reverbAmount": "0x80000000",
    "arpeggiatorRate": "0x00000000",
    "stutterRate": "0x00000000",
    "sampleRateReduction": "0x80000000",
    "bitCrush": "0x80000000",
    "modFXOffset": "0x00000000",
    "modFXFeedback": "0x00000000",
    "compressorThreshold": "0x00000000",
    "lpfMorph": "0x80000000",
    "hpfMorph": "0x80000000",
    "waveFold": "0x80000000",
}

#: Paramètres dont le nom de **destination de câble** diffère du nom de
#: stockage dans ``<defaultParams>``. Table ``paramNameForFile`` du firmware
#: (``modulation/params/param.cpp``), confirmée par la carte : 295 câbles
#: visent ``oscAPhaseWidth``, aucun ``oscAPulseWidth`` ; 151 visent
#: ``modulator1Volume``. Un câble écrit avec le nom de stockage désigne une
#: destination inconnue du firmware.
CABLE_DESTINATIONS: dict[str, str] = {
    "oscAPulseWidth": "oscAPhaseWidth",
    "oscBPulseWidth": "oscBPhaseWidth",
    "bitCrush": "bitcrushAmount",
    "modulator1Amount": "modulator1Volume",
    "modulator2Amount": "modulator2Volume",
    "arpeggiatorRate": "arpRate",
    "arpeggiatorGate": "arpGate",
    "bassFrequency": "bassFreq",
    "trebleFrequency": "trebleFreq",
}
_PARAM_OF_DESTINATION = {v: k for k, v in CABLE_DESTINATIONS.items()}


def cable_destination(name: str) -> str:
    """Nom qu'un câble doit porter pour viser le paramètre ``name``."""
    return CABLE_DESTINATIONS.get(name, name)


def param_of_destination(name: str) -> str:
    """Paramètre visé par la destination de câble ``name``."""
    return _PARAM_OF_DESTINATION.get(name, name)


#: Valeurs neutres d'un preset vierge (volume au maximum, filtre ouvert).
DEFAULT_PARAMS: dict[str, int] = {k: parse_fixed(v) for k, v in _DEFAULT_PARAMS_HEX.items()}

#: Correspondance des anciennes valeurs numériques de ``polyphonic``.
#: Anciennes valeurs numériques (firmware d'avant juin 2017). Le firmware
#: ne connaît que ``0`` (auto) et ``2`` (choke) ; tout autre nombre vaut
#: ``poly`` (``stringToPolyphonyMode``). La table d'avant inventait
#: ``3`` = mono et ``4`` = legato.
_POLY_BY_NUM = {0: "auto", 2: "choke"}


def _poly_mode(raw: str) -> str:
    """Polyphonie lisible, depuis le texte ou l'ancien numéro du fichier."""
    poly = (raw or "").strip()
    if poly.lstrip("-").isdigit():
        poly = _POLY_BY_NUM.get(int(poly), "poly")
    return poly or "poly"


# --------------------------------------------------------------------------
# Petits utilitaires de lecture / écriture XML
# --------------------------------------------------------------------------

def _txt(el: ET.Element | None, name: str, default: str = "") -> str:
    """Texte d'un attribut ou d'un sous-élément, quel que soit le dialecte."""
    if el is None:
        return default
    v = dxml.get(el, name)
    return default if v is None else v


def _int(el: ET.Element | None, name: str, default: int = 0) -> int:
    """Entier brut tolérant lu sur un attribut ou un sous-élément."""
    if el is None:
        return default
    v = dxml.get(el, name)
    return default if v is None else parse_int(v, default)


def _fx(el: ET.Element | None, name: str, default: int = INT32_MIN) -> int:
    """Paramètre en virgule fixe (entier 32 bits signé)."""
    if el is None:
        return default
    v = dxml.get(el, name)
    return default if v is None else parse_fixed(v, default)


def _has(el: ET.Element | None, name: str) -> bool:
    """Vrai si l'attribut ou le sous-élément existe."""
    return el is not None and dxml.get(el, name) is not None


def _set(el: ET.Element, name: str, value, dialect: str = "attr") -> None:
    """Écrit une valeur (convertie en texte) dans le dialecte demandé."""
    dxml.set_(el, name, str(value), dialect)


def _drop(el: ET.Element, name: str) -> None:
    """Supprime l'attribut ET le sous-élément de même nom."""
    el.attrib.pop(name, None)
    dxml.remove_child(el, name)


def _params_element(el: ET.Element) -> ET.Element | None:
    """Retourne l'élément de paramètres du nœud (quel que soit son nom)."""
    for tag in ("defaultParams", "soundParams", "kitParams", "songParams"):
        ch = dxml.get_child(el, tag)
        if ch is not None:
            return ch
    return None


def _ensure_params_element(el: ET.Element, fallback: str = "defaultParams") -> ET.Element:
    """Comme :func:`_params_element`, mais crée l'élément au besoin."""
    ch = _params_element(el)
    return ch if ch is not None else dxml.ensure_child(el, fallback)


def read_params(el: ET.Element | None) -> dict[str, int]:
    """Lit tous les paramètres hex d'un ``<defaultParams>``/``<soundParams>``.

    Les groupes imbriqués (``<lpf><frequency>``…) sont aplatis vers leurs noms
    canoniques (``lpfFrequency``). Les noms plats l'emportent sur les groupes.
    """
    out: dict[str, int] = {}
    if el is None:
        return out
    for tag, subs in _PARAM_GROUPS.items():
        grp = dxml.get_child(el, tag)
        if grp is None:
            continue
        for sub, flat in subs.items():
            raw = dxml.get(grp, sub)
            if raw is not None:
                out[flat] = parse_fixed(raw)
    for key, raw in el.attrib.items():
        if key in _PARAM_SET:
            out[key] = parse_fixed(raw)
    for child in el:
        if child.tag in _PARAM_SET and len(child) == 0:
            out[child.tag] = parse_fixed(child.text)
    return out


def write_params(el: ET.Element, params: dict[str, int], dialect: str = "attr",
                 nested: bool = False) -> None:
    """Écrit les paramètres hex dans l'élément fourni.

    ``nested=True`` produit les groupes ``<lpf>``/``<hpf>``/``<delay>`` attendus
    par le firmware pour les paramètres globaux d'un kit ou d'un morceau.
    """
    for key in PARAM_KEYS:
        if key not in params:
            continue
        value = format_fixed(params[key])
        grp = _GROUP_OF_FLAT.get(key)
        if nested and grp is not None:
            tag, sub = grp
            _drop(el, key)
            _set(dxml.ensure_child(el, tag), sub, value, dialect)
        else:
            if grp is not None:
                g = dxml.get_child(el, grp[0])
                if g is not None:
                    _drop(g, grp[1])
                    if len(g) == 0 and not g.attrib:
                        el.remove(g)
            _set(el, key, value, dialect)


def _folder_of(path: Path | None, kind: str) -> str:
    """Dossier « à la Deluge » d'un fichier : ``SYNTHS/boards of deluge/4``."""
    if path is None:
        return kind
    parts = list(path.parent.parts)
    for i in range(len(parts) - 1, -1, -1):
        if parts[i].upper() == kind.upper():
            return "/".join([kind] + parts[i + 1:])
    return parts[-1] if parts else kind


# --------------------------------------------------------------------------
# Oscillateurs, enveloppes, LFO, câbles de modulation
# --------------------------------------------------------------------------

@dataclass
class Zone:
    """Portion d'un échantillon jouée par un oscillateur."""

    start: int = 0
    end: int = -1
    unit: str = "samples"          # 'samples' | 'ms'
    start_loop: int = -1
    end_loop: int = -1

    @classmethod
    def from_xml(cls, el: ET.Element, dialect: str = "attr") -> "Zone":
        """Lit une <zone> (positions en échantillons ou en millisecondes)."""
        z = cls()
        if _has(el, "startSamplePos") or _has(el, "endSamplePos"):
            z.unit = "samples"
            z.start = _int(el, "startSamplePos", 0)
            z.end = _int(el, "endSamplePos", -1)
        elif _has(el, "startMilliseconds") or _has(el, "endMilliseconds"):
            z.unit = "ms"
            z.start = _int(el, "startMilliseconds", 0)
            z.end = _int(el, "endMilliseconds", -1)
        z.start_loop = _int(el, "startLoopPos", -1)
        z.end_loop = _int(el, "endLoopPos", -1)
        return z

    def to_xml(self, el: ET.Element, dialect: str = "attr") -> None:
        """Écrit la zone dans l'élément fourni."""
        if self.unit == "ms":
            _set(el, "startMilliseconds", self.start, dialect)
            _set(el, "endMilliseconds", self.end, dialect)
        else:
            _set(el, "startSamplePos", self.start, dialect)
            _set(el, "endSamplePos", self.end, dialect)
        if self.start_loop >= 0:
            _set(el, "startLoopPos", self.start_loop, dialect)
        if self.end_loop >= 0:
            _set(el, "endLoopPos", self.end_loop, dialect)


@dataclass
class SampleRange:
    """Une tranche de clavier d'un oscillateur multi-échantillon."""

    top_note: int = 127
    file_name: str = ""
    transpose: int = 0
    cents: int = 0
    zone: Zone = field(default_factory=Zone)

    @classmethod
    def from_xml(cls, el: ET.Element, dialect: str = "attr") -> "SampleRange":
        """Lit un <sampleRange>."""
        zel = dxml.get_child(el, "zone")
        return cls(
            top_note=_int(el, "rangeTopNote", 127),
            file_name=_txt(el, "fileName", ""),
            transpose=_int(el, "transpose", 0),
            cents=_int(el, "cents", 0),
            zone=Zone.from_xml(zel, dialect) if zel is not None else Zone(),
        )

    def to_xml(self, el: ET.Element, dialect: str = "attr") -> None:
        """Écrit la tranche dans l'élément fourni."""
        # La dernière tranche n'a pas de note haute : 127 est la valeur lue
        # en son absence, on ne l'ajoute donc pas.
        if self.top_note != 127 or _has(el, "rangeTopNote"):
            _set(el, "rangeTopNote", self.top_note, dialect)
        _set(el, "fileName", self.file_name, dialect)
        if self.transpose or _has(el, "transpose"):
            _set(el, "transpose", self.transpose, dialect)
        if self.cents or _has(el, "cents"):
            _set(el, "cents", self.cents, dialect)
        self.zone.to_xml(dxml.ensure_child(el, "zone"), dialect)


@dataclass
class Osc:
    """Oscillateur (forme d'onde, échantillon ou wavetable)."""

    type: str = "square"
    transpose: int = 0
    cents: int = 0
    retrig_phase: int = -1
    file_name: str = ""
    loop_mode: int = 0
    reversed: int = 0
    time_stretch_enable: int = 0
    time_stretch_amount: int = 0
    zone: Zone | None = None
    ranges: list[SampleRange] = field(default_factory=list)
    wavetable_position: int = 0

    @property
    def is_sample(self) -> bool:
        """Vrai si l'oscillateur lit un fichier de la carte."""
        return self.type in ("sample", "wavetable")

    @property
    def is_audible(self) -> bool:
        """Vrai si le type produit un son sans échantillon manquant."""
        if self.type in ("inLeft", "inRight"):
            return True
        if self.is_sample:
            return bool(self.file_name or self.ranges)
        return True

    @classmethod
    def from_xml(cls, el: ET.Element, dialect: str = "attr") -> "Osc":
        """Lit un <osc1>/<osc2>."""
        o = cls(
            type=_txt(el, "type", "square"),
            transpose=_int(el, "transpose", 0),
            cents=_int(el, "cents", 0),
            retrig_phase=_int(el, "retrigPhase", -1),
            file_name=_txt(el, "fileName", ""),
            loop_mode=_int(el, "loopMode", 0),
            reversed=_int(el, "reversed", 0),
            time_stretch_enable=_int(el, "timeStretchEnable", 0),
            time_stretch_amount=_int(el, "timeStretchAmount", 0),
            wavetable_position=_int(el, "wavetablePosition", 0),
        )
        zel = dxml.get_child(el, "zone")
        if zel is not None:
            o.zone = Zone.from_xml(zel, dialect)
        rel = dxml.get_child(el, "sampleRanges")
        if rel is not None:
            o.ranges = [SampleRange.from_xml(r, dialect)
                        for r in dxml.iter_children(rel, "sampleRange")]
        return o

    def to_xml(self, el: ET.Element, dialect: str = "attr") -> None:
        """Écrit l'oscillateur dans l'élément fourni."""
        _set(el, "type", self.type, dialect)
        _set(el, "transpose", self.transpose, dialect)
        _set(el, "cents", self.cents, dialect)
        _set(el, "retrigPhase", self.retrig_phase, dialect)
        if self.is_sample:
            _set(el, "loopMode", self.loop_mode, dialect)
            _set(el, "reversed", self.reversed, dialect)
            _set(el, "timeStretchEnable", self.time_stretch_enable, dialect)
            _set(el, "timeStretchAmount", self.time_stretch_amount, dialect)
            if self.file_name:
                _set(el, "fileName", self.file_name, dialect)
        if self.zone is not None:
            self.zone.to_xml(dxml.ensure_child(el, "zone"), dialect)
        if self.ranges:
            holder = dxml.ensure_child(el, "sampleRanges")
            # Tranches existantes réutilisées, appariées par fichier.
            anciens: dict[str, list[ET.Element]] = {}
            for old in list(holder):
                anciens.setdefault(_txt(old, "fileName", ""), []).append(old)
                holder.remove(old)
            for rng in self.ranges:
                pool = anciens.get(rng.file_name)
                sub = pool.pop(0) if pool else ET.Element("sampleRange")
                holder.append(sub)
                rng.to_xml(sub, dialect)

    def sample_paths(self) -> list[str]:
        """Tous les fichiers référencés par cet oscillateur."""
        out: list[str] = []
        if self.file_name:
            out.append(self.file_name)
        out.extend(r.file_name for r in self.ranges if r.file_name)
        return out


@dataclass
class Envelope:
    """Enveloppe ADSR en virgule fixe."""

    attack: int = INT32_MIN
    decay: int = INT32_MIN
    sustain: int = INT32_MAX
    release: int = INT32_MIN

    @classmethod
    def from_xml(cls, el: ET.Element, dialect: str = "attr") -> "Envelope":
        """Lit un <envelope1>/<envelope2>."""
        return cls(
            attack=_fx(el, "attack", INT32_MIN),
            decay=_fx(el, "decay", INT32_MIN),
            sustain=_fx(el, "sustain", INT32_MAX),
            release=_fx(el, "release", INT32_MIN),
        )

    def to_xml(self, el: ET.Element, dialect: str = "attr") -> None:
        """Écrit l'enveloppe dans l'élément fourni."""
        for key in ENV_KEYS:
            _set(el, key, format_fixed(getattr(self, key)), dialect)

    def display(self) -> tuple[int, int, int, int]:
        """Les quatre segments en unités d'affichage 0..50."""
        return (to_display(self.attack), to_display(self.decay),
                to_display(self.sustain), to_display(self.release))


@dataclass
class LFO:
    """Oscillateur basse fréquence."""

    type: str = "triangle"
    sync_level: int = 0
    sync_type: int = 0

    @classmethod
    def from_xml(cls, el: ET.Element, dialect: str = "attr") -> "LFO":
        """Lit un <lfo1>/<lfo2>."""
        return cls(
            type=_txt(el, "type", "triangle"),
            sync_level=_int(el, "syncLevel", 0),
            sync_type=_int(el, "syncType", 0),
        )

    def to_xml(self, el: ET.Element, dialect: str = "attr") -> None:
        """Écrit le LFO dans l'élément fourni."""
        _set(el, "type", self.type, dialect)
        _set(el, "syncLevel", self.sync_level, dialect)


@dataclass
class PatchCable:
    """Câble de modulation : source -> destination, avec une profondeur."""

    source: str = ""
    destination: str = ""
    amount: int = 0
    #: Sources qui font varier la profondeur de ce câble
    #: (``<depthControlledBy>``) : ``[(source, profondeur)]``. Il peut y en
    #: avoir plusieurs — « 5. Boc Pad » en a deux, ``lfo2`` et ``random``.
    depth_cables: list[tuple[str, int]] = field(default_factory=list)

    @classmethod
    def from_xml(cls, el: ET.Element, dialect: str = "attr") -> "PatchCable":
        """Lit un <patchCable> (y compris son <depthControlledBy>)."""
        cable = cls(
            source=_txt(el, "source", ""),
            destination=_txt(el, "destination", ""),
            amount=_fx(el, "amount", 0),
        )
        depth = dxml.get_child(el, "depthControlledBy")
        if depth is not None:
            cable.depth_cables = [
                (_txt(inner, "source", ""), _fx(inner, "amount", 0))
                for inner in dxml.iter_children(depth, "patchCable")]
        return cable

    def to_xml(self, el: ET.Element, dialect: str = "attr") -> None:
        """Écrit le câble dans l'élément fourni.

        Les câbles de profondeur déjà présents sont réutilisés, appariés par
        source, pour que leurs attributs inconnus du modèle survivent.
        """
        _set(el, "source", self.source, dialect)
        if self.destination:
            _set(el, "destination", cable_destination(self.destination),
                 dialect)
        _set(el, "amount", format_fixed(self.amount), dialect)
        if not self.depth_cables:
            dxml.remove_child(el, "depthControlledBy")
            return
        depth = dxml.ensure_child(el, "depthControlledBy")
        anciens: dict[str, list[ET.Element]] = {}
        for inner in list(depth):
            anciens.setdefault(_txt(inner, "source", ""), []).append(inner)
            depth.remove(inner)
        for source, amount in self.depth_cables:
            pool = anciens.get(source)
            inner = pool.pop(0) if pool else ET.Element("patchCable")
            depth.append(inner)
            _set(inner, "source", source, dialect)
            _set(inner, "amount", format_fixed(amount), dialect)

    def display(self) -> int:
        """Profondeur affichée par le Deluge : -50..+50.

        L'échelle pleine d'un câble de modulation est
        :data:`PATCH_CABLE_FULL` = ``0x40000000``, et **non** ``0x7FFFFFFF``
        comme pour les autres paramètres — mesuré sur les 7 025 câbles de la
        carte : aucun ne dépasse cette valeur, et 1 925 s'y arrêtent
        exactement, ce qui est la signature du maximum de l'interface.
        Passer par l'échelle des paramètres ordinaires divisait toutes les
        profondeurs par deux.
        """
        return max(-50, min(50, int(round(
            self.amount / float(PATCH_CABLE_FULL) * 50.0))))

    @staticmethod
    def amount_from_display(depth: int) -> int:
        """Entier 32 bits correspondant à une profondeur affichée -50..+50."""
        try:
            value = max(-50, min(50, int(depth)))
        except (TypeError, ValueError):
            value = 0
        return int(round(value / 50.0 * PATCH_CABLE_FULL))

    def set_display(self, depth: int) -> None:
        """Règle la profondeur depuis la valeur affichée par le Deluge."""
        self.amount = self.amount_from_display(depth)


@dataclass
class Modulator:
    """Un modulateur du moteur FM (``<modulator1>``/``<modulator2>``).

    En FM, le Deluge ne lit plus les formes d'onde des oscillateurs : deux
    porteuses sinusoïdales sont modulées par deux modulateurs, dont
    l'**accord** fait tout le timbre. Mesuré sur les 145 presets FM de la
    carte : le premier modulateur est à l'unisson dans 54 cas, et sinon à
    l'octave (±12), à la double octave (±24) ou sur un rapport inharmonique
    (+28, +7) ; le second envoie sa sortie dans le premier
    (``toModulator1``) dans 57 cas.
    """

    transpose: int = 0
    cents: int = 0
    retrig_phase: int = -1
    to_modulator1: int = 0

    @classmethod
    def from_xml(cls, el: ET.Element, dialect: str = "attr") -> "Modulator":
        """Lit un ``<modulator1>`` ou un ``<modulator2>``."""
        return cls(transpose=_int(el, "transpose", 0),
                   cents=_int(el, "cents", 0),
                   retrig_phase=_int(el, "retrigPhase", -1),
                   to_modulator1=_int(el, "toModulator1", 0))

    def to_xml(self, el: ET.Element, dialect: str = "attr",
               second: bool = False) -> None:
        """Écrit le modulateur ; ``second`` pour ``<modulator2>``."""
        _set(el, "transpose", self.transpose, dialect)
        _set(el, "cents", self.cents, dialect)
        if self.retrig_phase != -1 or _has(el, "retrigPhase"):
            _set(el, "retrigPhase", self.retrig_phase, dialect)
        if second:
            _set(el, "toModulator1", self.to_modulator1, dialect)


@dataclass
class Arpeggiator:
    """Réglages de l'arpégiateur (firmwares 2.x/3.x et communautaire c1.x)."""

    mode: str = "off"
    num_octaves: int = 2
    sync_level: int = 7
    arp_mode: str = ""
    note_mode: str = ""
    octave_mode: str = ""
    mpe_velocity: str = ""

    @property
    def is_on(self) -> bool:
        """Vrai si l'arpégiateur est actif dans l'un ou l'autre des dialectes."""
        if self.arp_mode:
            return self.arp_mode not in ("off", "0")
        return self.mode not in ("", "off", "0")

    @classmethod
    def from_xml(cls, el: ET.Element, dialect: str = "attr") -> "Arpeggiator":
        """Lit un <arpeggiator>."""
        return cls(
            mode=_txt(el, "mode", "off"),
            num_octaves=_int(el, "numOctaves", 2),
            sync_level=_int(el, "syncLevel", 7),
            arp_mode=_txt(el, "arpMode", ""),
            note_mode=_txt(el, "noteMode", ""),
            octave_mode=_txt(el, "octaveMode", ""),
            mpe_velocity=_txt(el, "mpeVelocity", ""),
        )

    def to_xml(self, el: ET.Element, dialect: str = "attr") -> None:
        """Écrit l'arpégiateur dans l'élément fourni."""
        _set(el, "mode", self.mode, dialect)
        _set(el, "numOctaves", self.num_octaves, dialect)
        _set(el, "syncLevel", self.sync_level, dialect)
        for name, value in (("arpMode", self.arp_mode),
                            ("noteMode", self.note_mode),
                            ("octaveMode", self.octave_mode),
                            ("mpeVelocity", self.mpe_velocity)):
            if value:
                _set(el, name, value, dialect)


@dataclass
class ModKnob:
    """Affectation d'un des 16 encodeurs « gold » du Deluge."""

    controls_param: str = ""
    patch_amount_from_source: str = ""

    @classmethod
    def from_xml(cls, el: ET.Element, dialect: str = "attr") -> "ModKnob":
        """Lit un <modKnob>."""
        return cls(
            controls_param=_txt(el, "controlsParam", ""),
            patch_amount_from_source=_txt(el, "patchAmountFromSource", ""),
        )

    def to_xml(self, el: ET.Element, dialect: str = "attr") -> None:
        """Écrit l'affectation dans l'élément fourni."""
        _set(el, "controlsParam", self.controls_param, dialect)
        if self.patch_amount_from_source:
            _set(el, "patchAmountFromSource", self.patch_amount_from_source, dialect)


#: Les 16 modKnobs des presets d'usine Synthstrom.
DEFAULT_MOD_KNOBS: list[ModKnob] = [
    ModKnob("pan"),
    ModKnob("volumePostFX"),
    ModKnob("lpfResonance"),
    ModKnob("lpfFrequency"),
    ModKnob("env1Release"),
    ModKnob("env1Attack"),
    ModKnob("delayFeedback"),
    ModKnob("delayRate"),
    ModKnob("reverbAmount"),
    ModKnob("volumePostReverbSend", "compressor"),
    ModKnob("pitch", "lfo1"),
    ModKnob("lfo1Rate"),
    ModKnob("env2Decay"),
    ModKnob("lpfFrequency", "envelope1"),
    ModKnob("lpfFrequency", "velocity"),
    ModKnob("sampleRateReduction"),
]


# --------------------------------------------------------------------------
# Son complet (preset de synthé ou rangée de kit)
# --------------------------------------------------------------------------

_CATEGORY_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Arp", ("arp ", " arp", "arpeg", "sequence", "seq ")),
    ("Bass", ("bass", "basse", " sub", "sub ", "808", "reese", "wobble",
              "growl", "upright")),
    ("Pluck", ("pluck", "plk", "harp", "kalimba", "marimba", "koto",
               "guitar", "guitare", "pizz", "banjo", "sitar")),
    ("Pad", ("pad", "string", "choir", "chorale", "atmos", "ambient",
             "warm", "nappe", "ensemble")),
    ("Keys", ("keys", "key ", "piano", "rhodes", "organ", "orgue", "clav",
              "wurli", "mellotron", "bell", "cloche", "vibe", "celest",
              "accordion", "harmonium", "flute", "sax", "brass", "horn",
              "violin", "cello", "viola")),
    ("Drone", ("drone", "texture", "swell", "wind")),
    ("FX", ("fx", "noise", "riser", "sweep", "impact", "zap", "glitch",
            "sfx", "stab", "scratch", "siren")),
    ("Lead", ("lead", "solo", "acid", "hoover", "supersaw", "screech")),
)


@dataclass
class Sound:
    """Un son Deluge complet : oscillateurs, filtre, enveloppes, modulations."""

    name: str = ""
    mode: str = "subtractive"
    polyphonic: str = "poly"
    voice_priority: int = 1
    lpf_mode: str = "24dB"
    hpf_mode: str = ""
    filter_route: str = ""
    mod_fx_type: str = "none"
    clipping_amount: int = 0
    max_voices: int = 0
    transpose: int = 0
    osc1: Osc = field(default_factory=Osc)
    osc2: Osc = field(default_factory=Osc)
    lfo1: LFO = field(default_factory=LFO)
    lfo2: LFO = field(default_factory=LFO)
    unison_num: int = 1
    unison_detune: int = 8
    unison_spread: int = 0
    env1: Envelope = field(default_factory=Envelope)
    env2: Envelope = field(default_factory=Envelope)
    params: dict[str, int] = field(default_factory=dict)
    patch_cables: list[PatchCable] = field(default_factory=list)
    eq: dict[str, int] = field(default_factory=dict)
    arp: Arpeggiator = field(default_factory=Arpeggiator)
    modulator1: Modulator = field(default_factory=Modulator)
    modulator2: Modulator = field(default_factory=Modulator)
    mod_knobs: list[ModKnob] = field(default_factory=list)
    delay_ping_pong: int = 1
    delay_analog: int = 0
    delay_sync_level: int = 7
    comp_sync_level: int = 6
    comp_attack: int = 327244
    comp_release: int = 936
    firmware: str = ""

    # -- accès aux paramètres -------------------------------------------

    def param(self, key: str, default: int = INT32_MIN) -> int:
        """Valeur brute d'un paramètre (cherchée dans params puis eq)."""
        if key in self.params:
            return self.params[key]
        if key in self.eq:
            return self.eq[key]
        return default

    def set_param(self, key: str, value: int) -> None:
        """Fixe un paramètre (saturé sur 32 bits signés)."""
        value = int(max(INT32_MIN, min(INT32_MAX, int(value))))
        if key in EQ_KEYS:
            self.eq[key] = value
        else:
            self.params[key] = value

    def display(self, key: str) -> int:
        """Valeur affichée par le Deluge : 0..50 (ou -25..+25 si bipolaire)."""
        raw = self.param(key, DEFAULT_PARAMS.get(key, INT32_MIN))
        return to_display(raw, bipolar=key in PARAM_BIPOLAR)

    # -- lecture XML ------------------------------------------------------

    @classmethod
    def from_xml(cls, el: ET.Element, dialect: str = "attr") -> "Sound":
        """Lit un <sound> : preset, rangée de kit ou instrument de morceau."""
        snd = cls()
        snd.name = _txt(el, "name", "") or _txt(el, "presetName", "")
        snd.mode = _txt(el, "mode", "subtractive") or "subtractive"
        snd.polyphonic = _poly_mode(_txt(el, "polyphonic", "poly"))
        snd.voice_priority = _int(el, "voicePriority", 1)
        snd.lpf_mode = _txt(el, "lpfMode", "24dB") or "24dB"
        snd.hpf_mode = _txt(el, "hpfMode", "")
        snd.filter_route = _txt(el, "filterRoute", "")
        snd.mod_fx_type = _txt(el, "modFXType", "none") or "none"
        snd.clipping_amount = _int(el, "clippingAmount", 0)
        snd.max_voices = _int(el, "maxVoices", 0)
        snd.transpose = _int(el, "transpose", 0)
        snd.firmware = _txt(el, "firmwareVersion", "")

        for attr, tag in (("osc1", "osc1"), ("osc2", "osc2")):
            sub = dxml.get_child(el, tag)
            if sub is not None:
                setattr(snd, attr, Osc.from_xml(sub, dialect))

        for attr, tag in (("lfo1", "lfo1"), ("lfo2", "lfo2")):
            sub = dxml.get_child(el, tag)
            if sub is not None:
                setattr(snd, attr, LFO.from_xml(sub, dialect))

        uni = dxml.get_child(el, "unison")
        if uni is not None:
            snd.unison_num = _int(uni, "num", 1)
            snd.unison_detune = _int(uni, "detune", 8)
            snd.unison_spread = _int(uni, "spread", 0)

        dly = dxml.get_child(el, "delay")
        if dly is not None:
            snd.delay_ping_pong = _int(dly, "pingPong", 1)
            snd.delay_analog = _int(dly, "analog", 0)
            snd.delay_sync_level = _int(dly, "syncLevel", 7)

        comp = dxml.get_child(el, "compressor")
        if comp is None:
            comp = dxml.get_child(el, "sidechain")
        if comp is not None:
            snd.comp_sync_level = _int(comp, "syncLevel", 6)
            snd.comp_attack = _int(comp, "attack", 327244)
            snd.comp_release = _int(comp, "release", 936)

        arp = dxml.get_child(el, "arpeggiator")
        if arp is not None:
            snd.arp = Arpeggiator.from_xml(arp, dialect)

        for attr, tag in (("modulator1", "modulator1"),
                          ("modulator2", "modulator2")):
            sub = dxml.get_child(el, tag)
            if sub is not None:
                setattr(snd, attr, Modulator.from_xml(sub, dialect))

        knobs = dxml.get_child(el, "modKnobs")
        if knobs is not None:
            snd.mod_knobs = [ModKnob.from_xml(k, dialect)
                             for k in dxml.iter_children(knobs, "modKnob")]

        pel = _params_element(el)
        if pel is not None:
            snd.read_param_element(pel, dialect)
        return snd

    def read_param_element(self, pel: ET.Element, dialect: str = "attr") -> None:
        """Lit un bloc <defaultParams>/<soundParams> dans ce son."""
        self.params.update(read_params(pel))
        for attr, tag in (("env1", "envelope1"), ("env2", "envelope2")):
            sub = dxml.get_child(pel, tag)
            if sub is not None:
                setattr(self, attr, Envelope.from_xml(sub, dialect))
        eq = dxml.get_child(pel, "equalizer")
        if eq is not None:
            for key in EQ_KEYS:
                raw = dxml.get(eq, key)
                if raw is not None:
                    self.eq[key] = parse_fixed(raw)
        cables = dxml.get_child(pel, "patchCables")
        if cables is not None:
            self.patch_cables = [PatchCable.from_xml(c, dialect)
                                 for c in dxml.iter_children(cables, "patchCable")]

    # -- écriture XML -----------------------------------------------------

    def to_xml(self, el: ET.Element, dialect: str = "attr") -> None:
        """Écrit le son dans l'élément fourni (les clés inconnues survivent)."""
        if self.name and dxml.get(el, "presetName") is None:
            _set(el, "name", self.name, dialect)
        # Les vieux fichiers écrivent ``0``/``1`` : on ne les traduit que si
        # la polyphonie a réellement changé.
        ancien = dxml.get(el, "polyphonic")
        if ancien is None or _poly_mode(ancien) != self.polyphonic:
            _set(el, "polyphonic", self.polyphonic, dialect)
        _set(el, "voicePriority", self.voice_priority, dialect)
        _set(el, "mode", self.mode, dialect)
        _set(el, "lpfMode", self.lpf_mode, dialect)
        if self.hpf_mode:
            _set(el, "hpfMode", self.hpf_mode, dialect)
        if self.filter_route:
            _set(el, "filterRoute", self.filter_route, dialect)
        _set(el, "modFXType", self.mod_fx_type, dialect)
        if self.clipping_amount or _has(el, "clippingAmount"):
            _set(el, "clippingAmount", self.clipping_amount, dialect)
        if self.max_voices or _has(el, "maxVoices"):
            _set(el, "maxVoices", self.max_voices, dialect)
        if self.transpose or _has(el, "transpose"):
            _set(el, "transpose", self.transpose, dialect)

        self.osc1.to_xml(dxml.ensure_child(el, "osc1"), dialect)
        self.osc2.to_xml(dxml.ensure_child(el, "osc2"), dialect)
        self.lfo1.to_xml(dxml.ensure_child(el, "lfo1"), dialect)
        lfo2 = dxml.ensure_child(el, "lfo2")
        _set(lfo2, "type", self.lfo2.type, dialect)
        if self.lfo2.sync_level or _has(lfo2, "syncLevel"):
            _set(lfo2, "syncLevel", self.lfo2.sync_level, dialect)

        uni = dxml.ensure_child(el, "unison")
        _set(uni, "num", self.unison_num, dialect)
        _set(uni, "detune", self.unison_detune, dialect)
        if self.unison_spread or _has(uni, "spread"):
            _set(uni, "spread", self.unison_spread, dialect)

        dly = dxml.ensure_child(el, "delay")
        _set(dly, "pingPong", self.delay_ping_pong, dialect)
        _set(dly, "analog", self.delay_analog, dialect)
        _set(dly, "syncLevel", self.delay_sync_level, dialect)

        comp = dxml.get_child(el, "compressor")
        if comp is None:
            comp = dxml.get_child(el, "sidechain")
        if comp is None:
            comp = dxml.ensure_child(el, "compressor")
        _set(comp, "syncLevel", self.comp_sync_level, dialect)
        _set(comp, "attack", self.comp_attack, dialect)
        _set(comp, "release", self.comp_release, dialect)

        self.write_param_element(_ensure_params_element(el), dialect)
        self.arp.to_xml(dxml.ensure_child(el, "arpeggiator"), dialect)

        # Les modulateurs ne s'écrivent que si le son est en FM ou s'ils
        # existaient déjà : un preset soustractif n'en a pas besoin.
        for attr, tag, second in (("modulator1", "modulator1", False),
                                  ("modulator2", "modulator2", True)):
            if self.mode == "fm" or dxml.get_child(el, tag) is not None:
                getattr(self, attr).to_xml(dxml.ensure_child(el, tag),
                                           dialect, second=second)

        if self.mod_knobs:
            holder = dxml.ensure_child(el, "modKnobs")
            for old in list(holder):
                holder.remove(old)
            for knob in self.mod_knobs:
                knob.to_xml(ET.SubElement(holder, "modKnob"), dialect)

    def write_param_element(self, pel: ET.Element, dialect: str = "attr") -> None:
        """Écrit paramètres, enveloppes, câbles et égaliseur de ce son."""
        write_params(pel, self.params, dialect, nested=False)
        self.env1.to_xml(dxml.ensure_child(pel, "envelope1"), dialect)
        self.env2.to_xml(dxml.ensure_child(pel, "envelope2"), dialect)
        holder = dxml.ensure_child(pel, "patchCables")
        # On réutilise les câbles existants, appariés par source et
        # destination : repartir d'éléments vierges perdait ce que le modèle
        # ignore (``rangeAdjustable`` sur 151 presets de la carte).
        anciens: dict[tuple[str, str], list[ET.Element]] = {}
        for old in list(holder):
            key = (_txt(old, "source", ""), _txt(old, "destination", ""))
            anciens.setdefault(key, []).append(old)
            holder.remove(old)
        for cable in self.patch_cables:
            pool = (anciens.get((cable.source, cable.destination))
                    or anciens.get((cable.source,
                                    cable_destination(cable.destination))))
            el = pool.pop(0) if pool else ET.Element("patchCable")
            holder.append(el)
            cable.to_xml(el, dialect)
        if self.eq:
            eq = dxml.ensure_child(pel, "equalizer")
            for key in EQ_KEYS:
                if key in self.eq:
                    _set(eq, key, format_fixed(self.eq[key]), dialect)

    # -- analyse ----------------------------------------------------------

    def sample_paths(self) -> list[str]:
        """Tous les ``fileName`` référencés par ce son, sans doublon."""
        out: list[str] = []
        for osc in (self.osc1, self.osc2):
            for rel in osc.sample_paths():
                if rel not in out:
                    out.append(rel)
        return out

    def uses_samples(self) -> bool:
        """Vrai si au moins un oscillateur lit un fichier."""
        return bool(self.sample_paths())

    def osc_label(self, osc: Osc) -> str:
        """Description courte d'un oscillateur pour l'affichage."""
        if osc.is_sample:
            if osc.ranges:
                return "multi-échantillon (%d)" % len(osc.ranges)
            if osc.file_name:
                return "échantillon " + osc.file_name.rsplit("/", 1)[-1]
            return osc.type
        label = osc.type
        if osc.transpose:
            label += " %+d" % osc.transpose
        return label

    def fx_list(self) -> list[str]:
        """Effets réellement actifs, en français."""
        fx: list[str] = []
        if self.mod_fx_type and self.mod_fx_type != "none":
            fx.append({"flanger": "flanger", "chorus": "chorus",
                       "phaser": "phaser", "StereoChorus": "chorus stéréo",
                       "TapeWarble": "warble", "grainFX": "granulaire",
                       "dimension": "dimension",
                       }.get(self.mod_fx_type, self.mod_fx_type))
        if self.display("reverbAmount") >= 3:
            fx.append("réverbération")
        if self.display("delayFeedback") >= 3:
            fx.append("delay")
        if self.clipping_amount > 0:
            fx.append("saturation")
        if self.display("bitCrush") >= 3:
            fx.append("bitcrush")
        if self.display("sampleRateReduction") >= 3:
            fx.append("décimation")
        if self.display("waveFold") >= 3:
            fx.append("wavefolder")
        if any(self.eq.get(k, 0) for k in ("bass", "treble")):
            fx.append("égaliseur")
        if any(c.source in ("compressor", "sidechain") for c in self.patch_cables):
            fx.append("sidechain")
        return fx

    def filter_label(self) -> str:
        """Description du filtre : mode, coupure et résonance affichées."""
        parts = ["LPF %s" % (self.lpf_mode or "24dB")]
        parts.append("coupure %d" % self.display("lpfFrequency"))
        parts.append("résonance %d" % self.display("lpfResonance"))
        if self.display("hpfFrequency") > 0:
            parts.append("HPF %d" % self.display("hpfFrequency"))
        return " · ".join(parts)

    def summary(self) -> dict:
        """Résumé lisible du son pour l'interface et l'index."""
        osc1 = self.osc_label(self.osc1)
        osc2 = self.osc_label(self.osc2) if self.display("oscBVolume") > 0 else ""
        oscs = osc1 + (" + " + osc2 if osc2 else "")
        fx = self.fx_list()
        cat = self.category_guess()
        text = "%s — %s — %s" % (oscs, self.filter_label(), ", ".join(fx) or "sans effet")
        return {
            "oscs": oscs,
            "osc1": osc1,
            "osc2": osc2,
            "filter": self.filter_label(),
            "fx": fx,
            "mode": self.mode,
            "poly": self.polyphonic,
            "unison": self.unison_num,
            "cables": len(self.patch_cables),
            "samples": self.sample_paths(),
            "env1": self.env1.display(),
            "env2": self.env2.display(),
            "category": cat,
            "tags": self.tonal_tags(),
            "text": text,
        }

    def category_guess(self) -> str:
        """Catégorie probable du son, d'après son nom puis son acoustique."""
        name = (self.name or "").lower()
        padded = " " + name + " "
        for cat, keys in _CATEGORY_HINTS:
            if any(k in padded for k in keys):
                return cat

        a1, d1, s1, r1 = self.env1.display()
        cutoff = self.display("lpfFrequency")
        res = self.display("lpfResonance")
        noise = self.display("noiseVolume")
        crush = max(self.display("bitCrush"), self.display("sampleRateReduction"))
        mono = self.polyphonic in ("mono", "legato")
        poly = self.polyphonic in ("poly", "auto")
        low = self.transpose + self.osc1.transpose
        ranges = len(self.osc1.ranges) + len(self.osc2.ranges)

        if self.arp.is_on:
            return "Arp"
        if ranges >= 3:
            return "Keys"
        if noise >= 35 or crush >= 25 or (self.mode == "ringmod" and r1 >= 30):
            return "FX"
        if a1 >= 20 and s1 >= 40 and r1 >= 32:
            return "Drone"
        if poly and r1 >= 25 and s1 >= 18 and (a1 >= 12 or self.unison_num >= 3):
            return "Pad"
        if low <= -12 and (mono or self.max_voices == 1) and cutoff <= 34 and r1 <= 24:
            return "Bass"
        if low <= -18 and cutoff <= 28:
            return "Bass"
        if a1 <= 3 and d1 <= 24 and s1 <= 10 and r1 <= 20:
            return "Pluck"
        if mono and cutoff >= 20 and a1 <= 14:
            return "Lead"
        if a1 >= 25 and r1 >= 30:
            return "Drone"
        if poly and a1 <= 12 and r1 <= 36:
            return "Keys"
        if res >= 30 and cutoff <= 25:
            return "Bass"
        return "Autre"

    def tonal_tags(self) -> list[str]:
        """Étiquettes descriptives en français (timbre, enveloppe, effets)."""
        a1, d1, s1, r1 = self.env1.display()
        cutoff = self.display("lpfFrequency")
        res = self.display("lpfResonance")
        tags: list[str] = []
        if cutoff >= 42:
            tags.append("brillant")
        elif cutoff <= 14:
            tags.append("sombre")
        if res >= 28:
            tags.append("résonant")
        if a1 >= 18:
            tags.append("attaque lente")
        elif a1 <= 2 and d1 <= 16:
            tags.append("percussif")
        if r1 >= 34:
            tags.append("long release")
        elif r1 <= 6:
            tags.append("court")
        if s1 >= 45:
            tags.append("tenu")
        if self.unison_num >= 3:
            tags.append("unisson")
        if self.unison_detune >= 20:
            tags.append("détuné")
        if self.mode == "fm":
            tags.append("FM")
        elif self.mode == "ringmod":
            tags.append("ring mod")
        if self.uses_samples():
            tags.append("échantillon")
        if self.arp.is_on:
            tags.append("arpégé")
        if self.clipping_amount > 0:
            tags.append("saturé")
        if max(self.display("bitCrush"), self.display("sampleRateReduction")) >= 8:
            tags.append("lo-fi")
        if self.display("reverbAmount") >= 12:
            tags.append("réverbéré")
        if self.display("delayFeedback") >= 28:
            tags.append("delay")
        if self.display("noiseVolume") >= 12:
            tags.append("bruité")
        if self.mod_fx_type not in ("", "none"):
            tags.append(self.mod_fx_type)
        tags.append("mono" if self.polyphonic in ("mono", "legato") else "polyphonique")
        low = self.transpose + self.osc1.transpose
        if low <= -12:
            tags.append("grave")
        elif low >= 12:
            tags.append("aigu")
        if len(self.patch_cables) >= 6:
            tags.append("très modulé")
        return tags


# --------------------------------------------------------------------------
# Preset de synthé
# --------------------------------------------------------------------------

_NEW_FIRMWARE = "c1.2.1"
_NEW_COMPAT = "4.1.0-alpha"


def _new_doc(tag: str, firmware: str = _NEW_FIRMWARE) -> DelugeDoc:
    """Crée un document Deluge vierge au dialecte « attributs »."""
    root = ET.Element(tag)
    root.set("firmwareVersion", firmware)
    root.set("earliestCompatibleFirmware", _NEW_COMPAT)
    return DelugeDoc(path=None, root=root, preamble={}, dialect="attr",
                     firmware=firmware, repaired=[])


def _root_of(doc: DelugeDoc, tag: str) -> ET.Element:
    """Élément utile du document (racine réelle ou premier enfant nommé)."""
    if doc.root.tag == tag:
        return doc.root
    child = dxml.get_child(doc.root, tag)
    if child is not None:
        return child
    for el in doc.root.iter(tag):
        return el
    return doc.root


@dataclass
class SynthPreset:
    """Un fichier ``SYNTHS/**/*.XML``."""

    path: Path | None = None
    name: str = ""
    folder: str = ""
    sound: Sound = field(default_factory=Sound)
    doc: DelugeDoc | None = None

    @classmethod
    def load(cls, path: Path) -> "SynthPreset":
        """Charge un preset depuis la carte SD."""
        path = Path(path)
        doc = dxml.load(path)
        root = _root_of(doc, "sound")
        sound = Sound.from_xml(root, doc.dialect)
        if not sound.name:
            sound.name = path.stem
        if not sound.firmware:
            sound.firmware = doc.firmware
        return cls(path=path, name=path.stem,
                   folder=_folder_of(path, "SYNTHS"), sound=sound, doc=doc)

    def save(self, path: Path | None = None, backup: bool = True) -> Path:
        """Écrit le preset (écriture atomique, sauvegarde .bak optionnelle)."""
        target = Path(path) if path is not None else self.path
        if target is None:
            raise ValueError("Aucun chemin de destination pour ce preset.")
        if self.doc is None:
            self.doc = _new_doc("sound", self.sound.firmware or _NEW_FIRMWARE)
        root = _root_of(self.doc, "sound")
        self.sound.to_xml(root, self.doc.dialect)
        out = dxml.save(self.doc, target, backup=backup)
        self.path = out
        self.name = out.stem
        self.folder = _folder_of(out, "SYNTHS")
        return out

    @classmethod
    def new(cls, name: str = "NEW") -> "SynthPreset":
        """Preset neutre réellement jouable (saw, filtre ouvert, sustain plein)."""
        sound = Sound()
        sound.name = name
        sound.mode = "subtractive"
        sound.polyphonic = "poly"
        sound.voice_priority = 1
        sound.lpf_mode = "24dB"
        sound.hpf_mode = "HPLadder"
        sound.filter_route = "H2L"
        sound.mod_fx_type = "none"
        sound.max_voices = 8
        sound.osc1 = Osc(type="saw", transpose=0, cents=0, retrig_phase=-1)
        sound.osc2 = Osc(type="square", transpose=0, cents=0, retrig_phase=-1)
        sound.lfo1 = LFO("triangle", 0)
        sound.lfo2 = LFO("triangle", 0)
        sound.env1 = Envelope(attack=INT32_MIN, decay=parse_fixed("0xE6666654"),
                              sustain=INT32_MAX, release=INT32_MIN)
        sound.env2 = Envelope(attack=parse_fixed("0xE6666654"),
                              decay=parse_fixed("0xE6666654"),
                              sustain=parse_fixed("0xFFFFFFE9"),
                              release=parse_fixed("0xE6666654"))
        sound.params = dict(DEFAULT_PARAMS)
        sound.eq = {k: 0 for k in EQ_KEYS}
        sound.patch_cables = []
        sound.arp = Arpeggiator()
        sound.mod_knobs = [ModKnob(k.controls_param, k.patch_amount_from_source)
                           for k in DEFAULT_MOD_KNOBS]
        sound.firmware = _NEW_FIRMWARE
        doc = _new_doc("sound")
        preset = cls(path=None, name=name, folder="SYNTHS", sound=sound, doc=doc)
        sound.to_xml(doc.root, "attr")
        return preset

    def sample_paths(self) -> list[str]:
        """Échantillons utilisés par ce preset."""
        return self.sound.sample_paths()

    def copy(self, name: str = "") -> "SynthPreset":
        """Duplique le preset en mémoire (sans chemin).

        Le document d'origine est copié avec le son : le modèle ne connaît
        qu'une partie du format, et repartir d'un document vierge perdait le
        reste. Mesuré sur la carte : 516 presets sur 911 sortaient abîmés
        d'une duplication — accord des modulateurs FM, synchro d'oscillateur,
        affectations MIDI, compresseur.
        """
        import copy as _copy
        doc = None
        if self.doc is not None:
            doc = _copy.deepcopy(self.doc)
            doc.path = None
        clone = SynthPreset(path=None, name=name or self.name, folder=self.folder,
                            sound=_copy.deepcopy(self.sound), doc=doc)
        clone.sound.name = clone.name
        return clone


# --------------------------------------------------------------------------
# Kit de batterie
# --------------------------------------------------------------------------

_DEFAULT_KIT_PARAMS_HEX: dict[str, str] = {
    "volume": "0x3504F334",
    "pan": "0x00000000",
    "lpfFrequency": "0x7FFFFFFF",
    "lpfResonance": "0x80000000",
    "hpfFrequency": "0x80000000",
    "hpfResonance": "0x80000000",
    "delayRate": "0x00000000",
    "delayFeedback": "0x80000000",
    "reverbAmount": "0x80000000",
    "modFXDepth": "0x00000000",
    "modFXRate": "0xE0000000",
    "modFXOffset": "0x00000000",
    "modFXFeedback": "0x80000000",
    "stutterRate": "0x00000000",
    "sampleRateReduction": "0x80000000",
    "bitCrush": "0x80000000",
}

#: Paramètres globaux neutres d'un kit vierge.
DEFAULT_KIT_PARAMS: dict[str, int] = {
    k: parse_fixed(v) for k, v in _DEFAULT_KIT_PARAMS_HEX.items()
}


#: Modes de lecture d'un échantillon (``loopMode``), dans l'ordre de
#: l'énumération ``SampleRepeatMode`` du firmware : ``CUT`` s'arrête avec la
#: note, ``ONCE`` joue jusqu'au bout, ``LOOP`` boucle, ``STRETCH`` étire.
REPEAT_CUT, REPEAT_ONCE, REPEAT_LOOP, REPEAT_STRETCH = 0, 1, 2, 3

#: Durée sous laquelle le firmware joue un échantillon jusqu'au bout quand
#: on le charge dans un kit (``sample_browser.cpp`` et ``slicer.cpp`` :
#: ``mSec < 2002 ? ONCE : CUT``).
ONCE_MAX_SECONDS = 2.002


def repeat_mode_for(seconds: float | None) -> int:
    """Mode de lecture qu'adopterait le Deluge pour un échantillon de cette durée.

    Une percussion courte se joue jusqu'au bout quelle que soit la longueur
    de la note ; un son long s'arrête avec elle. Durée inconnue : jusqu'au
    bout, le cas des percussions.
    """
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return REPEAT_ONCE
    return REPEAT_ONCE if value < ONCE_MAX_SECONDS else REPEAT_CUT


@dataclass
class KitRow:
    """Une rangée de kit : un nom et le son complet qui la produit."""

    name: str = ""
    sound: Sound = field(default_factory=Sound)

    @property
    def file_name(self) -> str:
        """Échantillon principal de la rangée ('' si aucun)."""
        paths = self.sound.sample_paths()
        return paths[0] if paths else ""


@dataclass
class Kit:
    """Un fichier ``KITS/**/*.XML``."""

    path: Path | None = None
    name: str = ""
    rows: list[KitRow] = field(default_factory=list)
    params: dict[str, int] = field(default_factory=dict)
    lpf_mode: str = "24dB"
    mod_fx_type: str = "none"
    doc: DelugeDoc | None = None

    @classmethod
    def from_xml(cls, el: ET.Element, dialect: str = "attr") -> "Kit":
        """Lit un <kit> (fichier de kit ou instrument d'un morceau)."""
        kit = cls()
        kit.name = _txt(el, "presetName", "") or _txt(el, "name", "")
        kit.lpf_mode = _txt(el, "lpfMode", "24dB") or "24dB"
        kit.mod_fx_type = _txt(el, "modFXType", "none") or "none"
        kit.params = read_params(_params_element(el))
        sources = dxml.get_child(el, "soundSources")
        if sources is not None:
            for sub in dxml.iter_children(sources, "sound"):
                snd = Sound.from_xml(sub, dialect)
                kit.rows.append(KitRow(name=snd.name, sound=snd))
        return kit

    def to_xml(self, el: ET.Element, dialect: str = "attr") -> None:
        """Écrit le kit dans l'élément fourni."""
        _set(el, "lpfMode", self.lpf_mode, dialect)
        _set(el, "modFXType", self.mod_fx_type, dialect)
        if self.params:
            write_params(_ensure_params_element(el), self.params, dialect, nested=True)
        sources = dxml.ensure_child(el, "soundSources")
        existing = list(dxml.iter_children(sources, "sound"))
        for i, row in enumerate(self.rows):
            if i < len(existing):
                sub = existing[i]
            else:
                sub = ET.SubElement(sources, "sound")
            row.sound.name = row.name or row.sound.name
            row.sound.to_xml(sub, dialect)
        for extra in existing[len(self.rows):]:
            sources.remove(extra)

    @classmethod
    def load(cls, path: Path) -> "Kit":
        """Charge un kit depuis la carte SD."""
        path = Path(path)
        doc = dxml.load(path)
        root = _root_of(doc, "kit")
        kit = cls.from_xml(root, doc.dialect)
        kit.path = path
        kit.name = path.stem
        kit.doc = doc
        return kit

    def save(self, path: Path | None = None, backup: bool = True) -> Path:
        """Écrit le kit (écriture atomique, sauvegarde .bak optionnelle)."""
        target = Path(path) if path is not None else self.path
        if target is None:
            raise ValueError("Aucun chemin de destination pour ce kit.")
        if self.doc is None:
            self.doc = _new_doc("kit")
        root = _root_of(self.doc, "kit")
        self.to_xml(root, self.doc.dialect)
        out = dxml.save(self.doc, target, backup=backup)
        self.path = out
        self.name = out.stem
        return out

    def sample_paths(self) -> list[str]:
        """Tous les échantillons utilisés par les rangées du kit."""
        out: list[str] = []
        for row in self.rows:
            for rel in row.sound.sample_paths():
                if rel not in out:
                    out.append(rel)
        return out

    @classmethod
    def new(cls, name: str = "KIT") -> "Kit":
        """Kit vierge prêt à recevoir des rangées."""
        doc = _new_doc("kit")
        kit = cls(path=None, name=name, rows=[], params=dict(DEFAULT_KIT_PARAMS),
                  lpf_mode="24dB", mod_fx_type="none", doc=doc)
        kit.to_xml(doc.root, "attr")
        return kit

    def add_row(self, name: str, file_name: str = "",
                seconds: float | None = None,
                frames: int | None = None) -> KitRow:
        """Ajoute une rangée jouant l'échantillon donné, comme le Deluge la crée.

        Mesuré sur les 523 rangées des 43 kits de la carte : enveloppe grande
        ouverte (attaque 0, sustain 50, release 0) dans la quasi-totalité,
        ``velocity → volume`` à pleine échelle sur 505, et l'échantillon joué
        jusqu'au bout (``loopMode`` 1) dans 83 % des cas.

        :param seconds: durée de l'échantillon, si on la connaît. Elle fixe
            le mode de lecture selon la règle du firmware
            (:func:`repeat_mode_for`) ; à défaut, la rangée joue l'échantillon
            jusqu'au bout.
        :param frames: longueur en trames, écrite comme fin de zone — c'est ce
            que fait le Deluge en chargeant un échantillon.
        """
        snd = Sound()
        snd.name = name
        snd.polyphonic = "auto"
        snd.mode = "subtractive"
        snd.lpf_mode = "24dB"
        snd.mod_fx_type = "none"
        snd.params = dict(DEFAULT_PARAMS)
        snd.eq = {k: 0 for k in EQ_KEYS}
        snd.env1 = Envelope(attack=INT32_MIN, decay=parse_fixed("0xE6666654"),
                            sustain=INT32_MAX, release=INT32_MIN)
        snd.env2 = Envelope(attack=parse_fixed("0xE6666654"),
                            decay=parse_fixed("0xE6666654"),
                            sustain=parse_fixed("0xFFFFFFE9"),
                            release=parse_fixed("0xE6666654"))
        snd.mod_knobs = [ModKnob(k.controls_param, k.patch_amount_from_source)
                         for k in DEFAULT_MOD_KNOBS]
        if file_name:
            end = int(frames) if frames and int(frames) > 0 else -1
            snd.osc1 = Osc(type="sample", file_name=file_name,
                           loop_mode=repeat_mode_for(seconds),
                           zone=Zone(start=0, end=end, unit="samples"))
        else:
            snd.osc1 = Osc(type="square")
        snd.osc2 = Osc(type="sample")
        snd.set_param("oscBVolume", INT32_MIN)
        # Sans ce câble, la vélocité ne change rien au volume d'un pad.
        snd.patch_cables = [PatchCable("velocity", "volume",
                                       PatchCable.amount_from_display(50))]
        row = KitRow(name=name, sound=snd)
        self.rows.append(row)
        return row


# --------------------------------------------------------------------------
# Notes, rangées, clips
# --------------------------------------------------------------------------

def _s32(value: int) -> int:
    """Interprète un entier 32 bits non signé en complément à deux."""
    value &= 0xFFFFFFFF
    return value - 0x100000000 if value >= 0x80000000 else value


@dataclass
class Note:
    """Une note d'un clip. ``pos``/``length`` sont en ticks du morceau :
    ``96 << inputTickMagnitude`` par mesure (voir :func:`ticks_per_bar`)."""

    pos: int = 0
    length: int = 24
    velocity: int = 64
    condition: int = 20
    lift: int = 64

    @property
    def probability(self) -> float:
        """Probabilité de déclenchement (1.0 = toujours)."""
        if self.condition >= 20:
            return 1.0
        return max(0.0, min(1.0, self.condition * 0.05))

    @property
    def is_iteration(self) -> bool:
        """Vrai si la condition est une règle d'itération (>= 0x80)."""
        return self.condition >= 0x80


def decode_notes(blob: str | None, with_lift: bool = False) -> list[Note]:
    """Décode un blob ``noteData`` (20 car./note) ou ``noteDataWithLift`` (22).

    Disposition vérifiée sur la carte réelle :
    ``pos(8) length(8) velocity(2) [lift(2)] condition(2)``.
    ``pos`` et ``length`` sont des entiers 32 bits signés.
    """
    if not blob:
        return []
    text = blob.strip()
    if text[:2].lower() == "0x":
        text = text[2:]
    step = 22 if with_lift else 20
    notes: list[Note] = []
    for i in range(0, len(text) - step + 1, step):
        chunk = text[i:i + step]
        try:
            pos = _s32(int(chunk[0:8], 16))
            length = _s32(int(chunk[8:16], 16))
            velocity = int(chunk[16:18], 16)
            if with_lift:
                lift = int(chunk[18:20], 16)
                condition = int(chunk[20:22], 16)
            else:
                lift = 64
                condition = int(chunk[18:20], 16)
        except ValueError:
            log.debug("Groupe de note illisible : %r", chunk)
            continue
        notes.append(Note(pos=pos, length=length, velocity=velocity,
                          condition=condition, lift=lift))
    return notes


def encode_notes(notes: Iterable[Note], with_lift: bool = True) -> str:
    """Encode une liste de notes en blob hexadécimal Deluge (préfixe ``0x``)."""
    parts = ["0x"]
    for note in notes:
        parts.append("%08X" % (int(note.pos) & 0xFFFFFFFF))
        parts.append("%08X" % (int(note.length) & 0xFFFFFFFF))
        parts.append("%02X" % (int(note.velocity) & 0xFF))
        if with_lift:
            parts.append("%02X" % (int(note.lift or 64) & 0xFF))
        parts.append("%02X" % (int(note.condition) & 0xFF))
    return "".join(parts)


@dataclass
class NoteRow:
    """Une ligne de notes d'un clip (note MIDI ou rangée de kit)."""

    y: int = 0
    notes: list[Note] = field(default_factory=list)
    muted: bool = False
    colour_offset: int = 0

    @classmethod
    def from_xml(cls, el: ET.Element, dialect: str = "attr") -> "NoteRow":
        """Lit un <noteRow> et décode son blob de notes."""
        raw_lift = dxml.get(el, "noteDataWithLift")
        raw = dxml.get(el, "noteData")
        if raw_lift is not None:
            notes = decode_notes(raw_lift, with_lift=True)
        else:
            notes = decode_notes(raw, with_lift=False)
        return cls(
            y=_int(el, "y", 0),
            notes=notes,
            muted=_txt(el, "muted", "0") in ("1", "true"),
            colour_offset=_int(el, "colourOffset", 0),
        )

    def to_xml(self, el: ET.Element, dialect: str = "attr") -> None:
        """Écrit la rangée (toujours au format ``noteDataWithLift``)."""
        _set(el, "y", self.y, dialect)
        if self.colour_offset:
            _set(el, "colourOffset", self.colour_offset, dialect)
        if self.muted:
            _set(el, "muted", 1, dialect)
        _drop(el, "noteData")
        _set(el, "noteDataWithLift", encode_notes(self.notes, True), dialect)

    @property
    def note_count(self) -> int:
        """Nombre de notes de la rangée."""
        return len(self.notes)


@dataclass
class Clip:
    """Un clip de morceau (session ou arrangement)."""

    name: str = ""
    length: int = TICKS_PER_BAR
    section: int = 0
    colour_offset: int = 0
    preset_name: str = ""
    preset_folder: str = ""
    is_kit: bool = False
    note_rows: list[NoteRow] = field(default_factory=list)
    #: Ticks d'une mesure dans le morceau qui contient ce clip : le morceau
    #: le pose à la lecture, d'après son ``inputTickMagnitude``.
    ticks_per_bar: int = TICKS_PER_BAR

    @property
    def bars(self) -> float:
        """Longueur en mesures 4/4, à la résolution du morceau."""
        return self.length / float(max(1, self.ticks_per_bar))

    @property
    def ticks_per_quarter(self) -> float:
        """Ticks d'une noire dans ce clip."""
        return max(1, self.ticks_per_bar) / 4.0

    @property
    def note_count(self) -> int:
        """Nombre total de notes du clip."""
        return sum(len(r.notes) for r in self.note_rows)

    @classmethod
    def from_xml(cls, el: ET.Element, dialect: str = "attr") -> "Clip":
        """Lit un <instrumentClip> ou un <audioClip>."""
        kit_el = dxml.get_child(el, "kit")
        folder = _txt(el, "instrumentPresetFolder", "") or _txt(el, "presetFolder", "")
        clip = cls(
            name=_txt(el, "clipName", ""),
            length=_int(el, "length", TICKS_PER_BAR),
            section=_int(el, "section", 0),
            colour_offset=_int(el, "colourOffset", 0),
            preset_name=_txt(el, "instrumentPresetName", "") or _txt(el, "presetName", ""),
            preset_folder=folder,
            is_kit=(kit_el is not None
                    or dxml.get_child(el, "kitParams") is not None
                    or folder.upper().startswith("KITS")),
        )
        rows = dxml.get_child(el, "noteRows")
        if rows is not None:
            clip.note_rows = [NoteRow.from_xml(r, dialect)
                              for r in dxml.iter_children(rows, "noteRow")]
        return clip

    def to_xml(self, el: ET.Element, dialect: str = "attr") -> None:
        """Écrit le clip dans l'élément fourni."""
        if self.name:
            _set(el, "clipName", self.name, dialect)
        _set(el, "length", self.length, dialect)
        _set(el, "section", self.section, dialect)
        _set(el, "colourOffset", self.colour_offset, dialect)
        if self.preset_name:
            _set(el, "instrumentPresetName", self.preset_name, dialect)
        if self.preset_folder:
            _set(el, "instrumentPresetFolder", self.preset_folder, dialect)
        holder = dxml.ensure_child(el, "noteRows")
        for old in list(holder):
            holder.remove(old)
        for row in self.note_rows:
            row.to_xml(ET.SubElement(holder, "noteRow"), dialect)

    def notes_flat(self) -> list[tuple[int, Note]]:
        """Toutes les notes du clip sous la forme (y, note), triées par temps."""
        out = [(r.y, n) for r in self.note_rows for n in r.notes]
        out.sort(key=lambda item: (item[1].pos, item[0]))
        return out

    def density(self) -> float:
        """Notes par mesure."""
        bars = self.bars
        return (self.note_count / bars) if bars > 0 else 0.0


# --------------------------------------------------------------------------
# Morceaux
# --------------------------------------------------------------------------

#: Noms de notes en français, par demi-ton depuis Do — ceux de
#: :mod:`~delugeapp.core.theory`, pour que l'application n'écrive pas
#: « Ré# » ici et « Mib » ailleurs.
NOTE_NAMES_FR = _theory.NOTE_NAMES_FR

#: Gammes reconnues, par intervalles depuis la tonique. Construite depuis
#: :data:`~delugeapp.core.theory.SCALES`, seule table de l'application : deux
#: copies avaient divergé (une « hongroise » et un « in sen » faux). Quand deux
#: noms partagent les mêmes intervalles, le premier de la table l'emporte.
SCALE_MODES: dict[tuple[int, ...], str] = {}
for _nom, _intervalles in _theory.SCALES.items():
    SCALE_MODES.setdefault(tuple(sorted(set(_intervalles))), _nom)
del _nom, _intervalles

#: Tags XML pouvant contenir les instruments d'un morceau (fw 2.x : ``tracks``).
_INSTRUMENT_HOLDERS = ("instruments", "tracks")

#: Tags XML pouvant contenir les clips de session (fw 2.x : ``tracks``).
_SESSION_HOLDERS = ("sessionClips", "tracks")

#: Tags XML des clips d'arrangement selon le firmware.
_ARRANGEMENT_HOLDERS = ("arrangementOnlyClips", "arrangementOnlyTracks")

#: Correspondance tag d'instrument -> nature.
_INSTRUMENT_KINDS = {
    "sound": "sound",
    "kit": "kit",
    "midiChannel": "midi",
    "cvChannel": "cv",
    "audioOutput": "audio",
    "track": "sound",
}

#: Tags de clips rencontrés dans les conteneurs de clips.
_CLIP_TAGS = ("instrumentClip", "audioClip", "clip", "track")

#: Bornes de tempo plausibles ; hors de cet intervalle, le calcul est rejeté.
TEMPO_MIN, TEMPO_MAX = 20.0, 400.0
TEMPO_FALLBACK = 120.0


def tempo_from_song_attrs(time_per_timer_tick: int, timer_tick_fraction: int,
                          input_tick_magnitude: int) -> float:
    """Tempo en BPM à partir des attributs d'horloge d'un ``<song>``.

    Le Deluge ne stocke pas le tempo mais la durée d'un tick en échantillons :

    * ``ticks = timePerTimerTick + timerTickFraction / 2**32`` ;
    * ``timerTickFraction`` est une **fraction non signée** — l'attribut XML est
      écrit en entier 32 bits signé, il faut donc le ramener en non signé, sinon
      8 morceaux sur 46 de la carte tombent à ~0,3 BPM près de la bonne valeur ;
    * ``samples_par_tick = ticks * 2**inputTickMagnitude`` ;
    * ``BPM = 44100 * 60 / (samples_par_tick * 24)`` — 24 ticks par noire,
      conformément à :data:`TICKS_PER_QUARTER`.

    Vérifié sur les 46 morceaux de la carte : 45 donnent un BPM entier et
    ``DEFAULT.XML`` donne exactement 120 BPM (défaut d'usine du Deluge).

    Retourne :data:`TEMPO_FALLBACK` si le résultat sort de
    ``[TEMPO_MIN, TEMPO_MAX]``.
    """
    try:
        tptt = int(time_per_timer_tick)
        frac = int(timer_tick_fraction) & 0xFFFFFFFF
        mag = int(input_tick_magnitude)
    except (TypeError, ValueError):
        return TEMPO_FALLBACK
    if tptt <= 0 or not -32 <= mag <= 32:
        return TEMPO_FALLBACK

    ticks = tptt + frac / 4294967296.0
    samples_per_tick = ticks * (2.0 ** mag)
    if samples_per_tick <= 0:
        return TEMPO_FALLBACK
    bpm = 44100.0 * 60.0 / (samples_per_tick * TICKS_PER_QUARTER)
    if not TEMPO_MIN <= bpm <= TEMPO_MAX:
        log.debug("tempo hors bornes (%.3f BPM) : repli sur %.1f",
                  bpm, TEMPO_FALLBACK)
        return TEMPO_FALLBACK
    # Le firmware vise des valeurs au demi-BPM : on arrondit le bruit de calcul.
    return round(bpm, 3)


def _first_child(el: ET.Element, names: Iterable[str]) -> ET.Element | None:
    """Premier enfant dont le tag figure dans ``names``."""
    for name in names:
        found = dxml.get_child(el, name)
        if found is not None:
            return found
    return None


@dataclass
class Song:
    """Un fichier ``SONGS/*.XML``.

    La classe est **en lecture seule** : l'application n'écrit jamais un
    morceau, pour ne pas risquer d'abîmer le travail de l'utilisateur
    (cf. SPEC §0.2). Le document d'origine reste disponible via ``doc``.
    """

    path: Path | None = None
    name: str = ""
    tempo_bpm: float = TEMPO_FALLBACK
    root_note: int = 0
    mode_notes: list[int] = field(default_factory=list)
    #: ``inputTickMagnitude`` : fixe la résolution des notes (voir
    #: :func:`ticks_per_bar`). 1 pour les morceaux 3.x, 2 pour c1.2.1.
    input_tick_magnitude: int = 0
    swing_amount: int = 0
    swing_interval: int = 7
    clips: list[Clip] = field(default_factory=list)
    arrangement_clips: list[Clip] = field(default_factory=list)
    instruments: list[dict] = field(default_factory=list)
    preview: str = ""
    firmware: str = ""
    doc: DelugeDoc | None = None

    # -- lecture ---------------------------------------------------------- #

    @classmethod
    def from_xml(cls, el: ET.Element, dialect: str = "attr") -> "Song":
        """Lit un élément ``<song>``."""
        song = cls(
            tempo_bpm=tempo_from_song_attrs(
                _int(el, "timePerTimerTick", 1),
                _int(el, "timerTickFraction", 0),
                _int(el, "inputTickMagnitude", 0),
            ),
            root_note=_int(el, "rootNote", 0),
            swing_amount=_int(el, "swingAmount", 0),
            swing_interval=_int(el, "swingInterval", 7),
            preview=_txt(el, "preview", ""),
            input_tick_magnitude=_int(el, "inputTickMagnitude", 0),
        )

        modes = dxml.get_child(el, "modeNotes")
        if modes is not None:
            for note_el in dxml.iter_children(modes, "modeNote"):
                raw = (note_el.text or "").strip()
                if raw:
                    song.mode_notes.append(parse_int(raw, 0))

        holder = _first_child(el, _INSTRUMENT_HOLDERS)
        if holder is not None:
            for child in list(holder):
                kind = _INSTRUMENT_KINDS.get(child.tag)
                if kind is None:
                    continue
                song.instruments.append({
                    "kind": kind,
                    "name": _txt(child, "presetName", "") or _txt(child, "name", ""),
                    "folder": _txt(child, "presetFolder", ""),
                })

        song.clips = cls._read_clips(el, _SESSION_HOLDERS, dialect)
        song.arrangement_clips = cls._read_clips(el, _ARRANGEMENT_HOLDERS, dialect)
        # Un clip ne connaît pas sa résolution : c'est le morceau qui la
        # porte. Sans elle, un clip de 1 536 ticks passait pour 16 mesures
        # dans un morceau c1.2.1, où il en fait 4.
        mesure = song.ticks_per_bar
        for clip in song.clips + song.arrangement_clips:
            clip.ticks_per_bar = mesure
        return song

    @property
    def ticks_per_bar(self) -> int:
        """Ticks d'une mesure 4/4 dans ce morceau."""
        return ticks_per_bar(self.input_tick_magnitude)

    @staticmethod
    def _read_clips(el: ET.Element, holders: Iterable[str],
                    dialect: str) -> list[Clip]:
        """Clips contenus dans le premier conteneur trouvé parmi ``holders``."""
        holder = _first_child(el, holders)
        if holder is None:
            return []
        out: list[Clip] = []
        for child in list(holder):
            if child.tag not in _CLIP_TAGS:
                continue
            try:
                out.append(Clip.from_xml(child, dialect))
            except (ValueError, TypeError, AttributeError) as exc:
                log.debug("clip illisible (%s) : %s", child.tag, exc)
        return out

    @classmethod
    def load(cls, path: Path) -> "Song":
        """Charge un morceau depuis la carte SD."""
        path = Path(path)
        doc = dxml.load(path)
        root = _root_of(doc, "song")
        song = cls.from_xml(root, doc.dialect)
        song.path = path
        song.name = path.stem
        song.firmware = doc.firmware
        song.doc = doc
        return song

    # -- dépendances ------------------------------------------------------- #

    def sample_paths(self) -> list[str]:
        """Tous les ``fileName`` d'échantillons référencés par le morceau.

        Les instruments du morceau embarquent leur propre définition de son :
        on parcourt donc le XML d'origine, qui est la source complète.
        """
        if self.doc is None:
            return []
        seen: dict[str, None] = {}
        for el in self.doc.root.iter():
            value = dxml.get(el, "fileName")
            if value:
                seen.setdefault(value.replace("\\", "/").strip("/"), None)
        return list(seen)

    def preset_refs(self) -> list[tuple[str, str, str]]:
        """Presets utilisés : ``(nature, nom, dossier)`` sans doublon."""
        seen: dict[tuple[str, str, str], None] = {}
        for inst in self.instruments:
            key = (inst.get("kind", ""), inst.get("name", ""),
                   inst.get("folder", ""))
            if key[1]:
                seen.setdefault(key, None)
        for clip in self.clips + self.arrangement_clips:
            if clip.preset_name:
                kind = "kit" if clip.is_kit else "sound"
                seen.setdefault((kind, clip.preset_name, clip.preset_folder), None)
        return list(seen)

    # -- lecture musicale -------------------------------------------------- #

    def scale_name(self) -> str:
        """Nom français de la gamme : ``Do majeur``, ``La mineur``, ``Ré dorien``."""
        tonic = NOTE_NAMES_FR[self.root_note % 12]
        if not self.mode_notes:
            return tonic
        intervals = tuple(sorted({n % 12 for n in self.mode_notes}))
        mode = SCALE_MODES.get(intervals)
        if mode is None:
            return f"{tonic} (gamme libre, {len(intervals)} notes)"
        return f"{tonic} {mode}"

    def stats(self) -> dict:
        """Chiffres de synthèse du morceau."""
        all_clips = self.clips + self.arrangement_clips
        notes = sum(c.note_count for c in all_clips)
        bars = max((c.bars for c in all_clips), default=0.0)
        sections = len({c.section for c in self.clips})
        total_bars = sum(c.bars for c in all_clips)
        return {
            "clips": len(self.clips),
            "arrangement_clips": len(self.arrangement_clips),
            "notes": notes,
            "bars": bars,
            "sections": sections,
            "instruments": len(self.instruments),
            "density": (notes / total_bars) if total_bars > 0 else 0.0,
        }

    def preview_colors(self) -> list[list[str]]:
        """Vignette du morceau en matrice 8x18 de couleurs ``#RRGGBB``.

        Le Deluge écrit ``previewNumPads="144"`` pads de 3 octets (6 caractères
        hexadécimaux), rangée par rangée : 8 rangées de 16 pads plus les
        2 colonnes de la barre latérale.

        **La première rangée écrite est celle du bas** (``imageStore[0]``),
        comme partout dans le firmware. Mesuré sur la carte : « Truc 1 », 3
        clips et ``yScrollSongView`` −5, allume les rangées 5 à 7 — ses clips
        sont en haut de l'écran ; « Nimp1 », 5 clips à −2, allume les
        rangées 2 à 6. La matrice rendue est donc **retournée**, première
        ligne en haut, comme la dessine :class:`~delugeapp.ui.widgets.padgrid.PadGrid`.
        Avant le 15 octobre 2026, les vignettes s'affichaient à l'envers.
        """
        rows, cols = 8, 18
        blank = "#000000"
        grid = [[blank] * cols for _ in range(rows)]
        blob = (self.preview or "").strip()
        if blob.lower().startswith("0x"):
            blob = blob[2:]
        if len(blob) < rows * cols * 6:
            return grid
        for r in range(rows):
            for c in range(cols):
                off = (r * cols + c) * 6
                chunk = blob[off:off + 6]
                try:
                    int(chunk, 16)
                except ValueError:
                    continue
                grid[rows - 1 - r][c] = "#" + chunk.upper()
        return grid
