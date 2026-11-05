# -*- coding: utf-8 -*-
"""Moteur d'écoute hors-ligne : entendre un preset sans passer par le Deluge.

Un preset généré doit pouvoir être écouté dans l'application avant d'être
écrit sur la carte. Depuis le 23 octobre 2026, ce moteur ne se contente
plus d'un son « plausible » : il **refait les calculs du firmware de la
machine** (communautaire 1.3, commit ``102cf9f``), étage par étage, par
:mod:`.dsp`.

* **La voix** se calcule par blocs de 128 échantillons, comme sur la
  machine : enveloppes et LFO une fois par bloc, paramètres repatchés
  (:mod:`.paramlaws`), amplitudes en rampe d'un bloc au suivant.
  Oscillateurs lus dans les tables du firmware, unisson compensé en
  ``1/√n`` *avant* le filtre, bruit uniforme, FM à deux modulateurs
  additionnés qui modulent les deux porteuses, modulation en anneau ;
  échelle à transistors échantillon par échantillon avec ses compensations
  de niveau ; volume et enveloppe 1 après le filtre ; saturation adoucie.
* **Le son** : panoramique linéaire, réduction d'échantillonnage et de
  résolution, chorus, flanger ou phaser, égaliseur, delay (ping-pong,
  analogique), envoi vers la réverbération, volume post-effets — le réglage
  ``volume`` d'un preset est ce volume-là, et non celui de la voix.
* **Le morceau** : une réverbération partagée (« Mutable », celle d'un
  morceau neuf, ou Freeverb), puis le compresseur maître au repos et la
  sortie (gain de base 0,85 du compresseur d'un morceau, et sa saturation
  adoucie qui arrondit l'extrême aigu) : un mélange de 2²⁴ sort à 0,29 de
  pleine échelle.

Les signaux circulent à l'échelle des entiers du firmware (±2³¹) jusqu'à la
sortie. Les échantillons se lisent comme sur la machine : en stéréo s'ils le
sont, par sinus cardinal fenêtré quand ils sont transposés. Restent
approchés : l'étirement temporel, le glissé, le LFO 1 global (il repart à
chaque note), la compression par son et le sidechain.

Vérifié contre un export de pistes de la machine le 23 octobre 2026 (SPEC
§4.41) : douze sons d'essai, niveaux à 0,1 dB près.

Budget : SPEC §4.21, 2,5 secondes rendues en moins de 600 ms au pire cas (une
nappe à huit voix d'unisson) ; un preset de la carte rend 1,5 s en 0,1 s
(médiane). Les voix d'une écoute de plusieurs parties se calculent en
parallèle (:func:`render_parts`), quand :mod:`.dsp` est compilé par numba :
une section de huit mesures en 0,3 à 1 s, au lieu de 4 à 9. Dépend de numpy,
et de numba s'il est installé.
"""

from __future__ import annotations

import logging
import math
import os
import threading
import zlib
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, wait
from functools import lru_cache

import numpy as np

from . import dsp
from . import paramlaws as laws
from .fixedpoint import INT32_MIN
from .model import Kit, Sound, SynthPreset, param_of_destination
from .sdcard import SDCard

log = logging.getLogger(__name__)

#: Fréquence de calcul : celle du Deluge. Un rendu demandé à une autre
#: fréquence est calculé à 44,1 kHz puis rééchantillonné.
ENGINE_RATE = dsp.SR

#: Durée maximale laissée à l'extinction d'une note : un release de 50 dure
#: 27 s sur la machine, l'écoute s'arrête avant.
MAX_TAIL_S = 4.0

#: Destinations de modulation entendues par le rendu. Les autres sont
#: ignorées avec une trace : le Deluge en accepte une cinquantaine.
KNOWN_DESTINATIONS = (
    "lpfFrequency", "lpfResonance", "lpfMorph", "hpfFrequency",
    "hpfResonance", "hpfMorph", "pitch", "volume", "oscAVolume",
    "oscBVolume", "oscAPitch", "oscBPitch", "oscAPulseWidth",
    "oscBPulseWidth", "noiseVolume", "modFXDepth", "modFXRate",
    "reverbAmount", "delayFeedback", "delayRate", "pan", "lfo1Rate",
    "lfo2Rate", "modulator1Amount", "modulator2Amount", "modulator1Pitch",
    "modulator2Pitch", "modulator1Feedback", "modulator2Feedback",
    "carrier1Feedback", "carrier2Feedback", "env1Attack", "env1Decay",
    "env1Sustain", "env1Release", "env2Attack", "env2Decay", "env2Sustain",
    "env2Release", "volumePostFX",
)

#: Tempo supposé pour l'aperçu d'un LFO synchronisé : un preset n'a pas de
#: tempo, c'est le morceau qui le donne.
PREVIEW_BPM = 120.0

#: La réverbération d'un morceau neuf du firmware 1.3 (``Song::Song``) :
#: modèle « Mutable », taille 0,6, amortissement 0,72, largeur 1, filtres
#: ouverts. C'est aussi celle des morceaux que l'application écrit.
PREVIEW_REVERB = dsp.ReverbSettings()

#: Le volume d'un morceau neuf (``SONGS/DEFAULT.XML``), celui qu'écrit
#: l'atelier : il règle l'envoi vers la réverbération de chaque son
#: (``Song::renderAudio`` passe ``volumePostFX >> 1``), soit 2²⁶.
SONG_VOLUME = 0x3504F334


def _volume_factor(raw: int) -> float:
    """``f²`` d'un volume de fichier (``getFinalParameterValueVolume`` sur
    ``valeur >> 2``) : 1 au réglage 25, 2 pour 0x3504F334, 4 en butée."""
    f = 1.0 + laws.raw_unit(raw)
    return f * f


#: ``reverbAmountAdjust`` que le morceau passe à ses sons.
SONG_REVERB_ADJUST = float(1 << 25) * _volume_factor(SONG_VOLUME)


def kit_gain(kit) -> float:
    """Le gain de l'étage d'un kit (``GlobalEffectableForClip::renderOutput``)
    : son volume, majoré d'un quart, puis ses filtres ouverts (−20 %) —
    ``f² · 0,50``, l'unité au volume que l'atelier écrit."""
    raw = (getattr(kit, "params", None) or {}).get("volume", SONG_VOLUME)
    try:
        raw = int(raw)
    except (TypeError, ValueError):
        raw = SONG_VOLUME
    return _volume_factor(raw) / 2.0 * 1.25 * (
        math.floor(float(1 << 31) * 1720000000.0 / dsp.Q32) * 2.0 / dsp.Q31)


def synced_hz(sync_level: int, bpm: float = PREVIEW_BPM) -> float:
    """Fréquence d'un LFO calé sur le tempo, d'après son ``syncLevel``.

    Valeur de fichier, calcul du firmware (``sync.cpp``) : la durée vaut
    ``2^(3 - niveau)`` mesures — 3 = une mesure, 5 = une noire,
    7 = une double-croche. La magnitude du morceau s'annule entre la lecture
    du fichier et l'affichage, d'où une formule qui n'en dépend pas.
    """
    try:
        level = int(sync_level)
        tempo = float(bpm)
    except (TypeError, ValueError):
        return 2.0
    if level <= 0 or tempo <= 0:
        return 0.0
    bars = 2.0 ** (3 - level)
    seconds = bars * 4.0 * 60.0 / tempo
    return 1.0 / seconds if seconds > 0 else 0.0

#: Sources de modulation reconnues.
KNOWN_SOURCES = ("envelope1", "envelope2", "lfo1", "lfo2", "velocity", "note",
                 "random", "aftertouch")


# --------------------------------------------------------------------------- #
# Conversion des paramètres
# --------------------------------------------------------------------------- #

def _unit(sound: Sound, key: str, default: float = 0.5) -> float:
    """Paramètre ramené dans [0, 1] depuis l'échelle d'affichage 0..50."""
    try:
        return max(0.0, min(1.0, sound.display(key) / 50.0))
    except Exception:  # noqa: BLE001 - paramètre absent
        return default


def _u(sound: Sound, key: str, default: float = 25.0) -> float:
    """Réglage −1..+1 lu dans l'entier du fichier, comme le firmware ;
    ``default`` (en affichage 0..50) s'il manque.

    Ni ``Sound.display`` ni l'affichage arrondi : le premier rend 0 pour un
    réglage absent (la hauteur générale d'un preset qui ne la porte pas
    tombait à −4 octaves), et montre le panoramique en bipolaire, 0 au
    centre — lu comme un réglage 0, il envoyait tout à gauche.
    """
    if key not in getattr(sound, "params", {}):
        return float(laws.unit(default))
    try:
        return laws.raw_unit(sound.param(key))
    except Exception:  # noqa: BLE001 - paramètre illisible
        return float(laws.unit(default))


def _display(sound: Sound, key: str, default: float = 25.0) -> float:
    """Réglage en affichage continu 0..50 (cf. :func:`_u`)."""
    return (_u(sound, key, default) + 1.0) * 25.0


def _cutoff_hz(unit: float) -> float:
    """Coupure du passe-bas en hertz, depuis le réglage ramené à 0..1 :
    loi du firmware (:func:`.paramlaws.lpf_hz`)."""
    return float(laws.lpf_hz(laws.exp_octaves("lpfFrequency",
                                              float(unit) * 50.0)))


def _hpf_hz(unit: float) -> float:
    """Coupure du passe-haut en hertz, depuis le réglage ramené à 0..1."""
    return float(laws.hpf_hz(laws.exp_octaves("hpfFrequency",
                                              float(unit) * 50.0)))



class _Patch:
    """Ce que les câbles ajoutent à chaque paramètre, comme le patcher du
    firmware : des **octaves** pour un paramètre exponentiel, un **facteur**
    ``Π(1 + v·a)`` pour un paramètre linéaire ou de volume, un **ajout**
    ``Σ v·a`` pour un paramètre hybride (largeur d'impulsion, panoramique)
    et pour les durées d'enveloppe lues dans la table des vitesses.

    Les valeurs sont des scalaires ou des tableaux numpy, selon les sources.
    """

    def __init__(self) -> None:
        self.octaves: dict[str, object] = {}
        self.factors: dict[str, object] = {}
        self.adds: dict[str, object] = {}

    def __contains__(self, name: str) -> bool:
        return name in self.octaves or name in self.factors \
            or name in self.adds

    def keys(self):
        return set(self.octaves) | set(self.factors) | set(self.adds)

    def oct(self, name: str):
        return self.octaves.get(name, 0.0)

    def factor(self, name: str):
        return self.factors.get(name, 1.0)

    def add(self, name: str):
        return self.adds.get(name, 0.0)


#: Durées d'enveloppe que le firmware lit dans la table des vitesses : un
#: câble s'y ajoute en unités de réglage, pas en octaves.
_RATE_PARAMS = {"env1Decay", "env1Release", "env2Decay", "env2Release",
                "env3Decay", "env3Release", "env4Decay", "env4Release"}


def _patch(sound: Sound, sources: dict, only: set[str] | None = None
           ) -> _Patch:
    """Additionne les câbles du son, source par source (lois du firmware).

    ``sources`` : valeurs **bipolaires** −1..+1 des sources (scalaires ou
    tableaux), sauf l'aftertouch, unipolaire. ``only`` : ne garder que ces
    sources — les durées d'enveloppe se calculent avec les seules sources
    constantes de la note.
    """
    out = _Patch()
    for cable in sound.patch_cables:
        # Le câble vise ``oscAPhaseWidth`` quand le paramètre s'appelle
        # ``oscAPulseWidth`` : sans cette traduction, les 295 câbles de
        # largeur d'impulsion de la carte restaient muets à l'écoute.
        destination = param_of_destination(cable.destination)
        if destination not in KNOWN_DESTINATIONS:
            log.debug("destination de modulation ignorée : %s",
                      cable.destination)
            continue
        if only is not None and cable.source not in only:
            continue
        value = sources.get(cable.source)
        if value is None:
            log.debug("source de modulation ignorée : %s", cable.source)
            continue
        value = laws.to_polarity(value, cable.source,
                                 getattr(cable, "polarity", ""))
        strength = laws.cable_strength(cable.amount)
        kind = laws.param_class(destination)
        if destination in _RATE_PARAMS:
            out.adds[destination] = out.add(destination) \
                + np.asarray(value) * strength
        elif kind == "exp":
            out.octaves[destination] = out.oct(destination) \
                + laws.cable_octaves(value, strength, destination,
                                     cable.source)
        elif kind in ("linear", "volume"):
            out.factors[destination] = out.factor(destination) \
                * laws.cable_factor(value, strength)
        else:
            out.adds[destination] = out.add(destination) \
                + np.asarray(value) * strength
    return out


def _modulations(sound: Sound, n: int, sr: int, sources: dict) -> _Patch:
    """Les modulations du son, pour ``n`` échantillons (cf. :func:`_patch`).
    Gardé pour les appels existants : ``destination in _modulations(...)``
    dit si un câble est entendu."""
    return _patch(sound, sources)


# --------------------------------------------------------------------------- #
# Valeurs finales des paramètres, à l'échelle du firmware
# --------------------------------------------------------------------------- #

#: Valeurs neutres (``getParamNeutralValue``) : celle d'un paramètre au
#: réglage 25 et sans câble.
NEUTRAL = {
    "oscAVolume": 134217728.0, "oscBVolume": 134217728.0,
    "volume": 134217728.0, "noiseVolume": 134217728.0,
    "volumePostFX": 134217728.0, "volumePostReverbSend": 134217728.0,
    "reverbAmount": 134217728.0, "modulator1Amount": 33554432.0,
    "modulator2Amount": 33554432.0, "lpfFrequency": 2000000.0,
    "hpfFrequency": 2672947.0, "lfo1Rate": 121739.0, "lfo2Rate": 121739.0,
    "modFXRate": 121739.0, "lpfResonance": 268435450.0,
    "hpfResonance": 268435450.0, "lpfMorph": 268435450.0,
    "hpfMorph": 268435450.0, "env1Sustain": 1073741824.0,
    "env2Sustain": 1073741824.0, "delayFeedback": 1073741824.0,
    "modulator1Feedback": 5931642.0, "modulator2Feedback": 5931642.0,
    "carrier1Feedback": 5931642.0, "carrier2Feedback": 5931642.0,
    "delayRate": 16777216.0, "pitch": 16777216.0, "oscAPitch": 16777216.0,
    "oscBPitch": 16777216.0, "modulator1Pitch": 16777216.0,
    "modulator2Pitch": 16777216.0, "modFXDepth": 526133494.0,
}

#: Le réglage de preset d'un paramètre, quand son nom diffère de celui de
#: la destination des câbles. ``None`` : rien dans le fichier, seuls les
#: câbles le déplacent. Le ``volume`` d'un preset règle le volume
#: post-effets du son (``Sound::readParamTagFromFile``) ; le volume de la
#: voix, que visent les câbles ``volume``, n'est jamais enregistré.
_PRESET_OF = {
    "pitch": "pitchAdjust", "oscAPitch": "oscAPitchAdjust",
    "oscBPitch": "oscBPitchAdjust", "volume": None,
    "volumePostFX": "volume", "volumePostReverbSend": None,
    "modulator1Pitch": None, "modulator2Pitch": None,
}


def _preset_u(sound: Sound, name: str, default: float = 25.0) -> float:
    """Le réglage −1..+1 d'un paramètre, lu sous son nom de preset."""
    key = _PRESET_OF.get(name, name)
    if key is None:
        return 0.0
    return _u(sound, key, default)


def _blocks(value, nb: int) -> np.ndarray:
    """Un scalaire ou un tableau par bloc, étendu à ``nb`` blocs."""
    arr = np.asarray(value, dtype=np.float64)
    if arr.ndim == 0:
        return np.full(nb, float(arr))
    return arr[:nb]


def _final_volume(sound: Sound, name: str, mod: _Patch, nb: int,
                  default: float = 25.0) -> np.ndarray:
    """Valeur finale d'un paramètre de volume : ``neutre · f²``, ``f`` le
    produit du réglage ``1 + u`` et des câbles, borné à 4."""
    f = np.clip((1.0 + _preset_u(sound, name, default))
                * _blocks(mod.factor(name), nb), 0.0, 4.0)
    return np.minimum(NEUTRAL[name] * f * f, dsp.Q31 - 1.0)


def _final_linear(sound: Sound, name: str, mod: _Patch, nb: int,
                  default: float = 25.0) -> np.ndarray:
    """Valeur finale d'un paramètre linéaire : ``neutre · f``."""
    f = np.clip((1.0 + _preset_u(sound, name, default))
                * _blocks(mod.factor(name), nb), 0.0, 4.0)
    return np.minimum(NEUTRAL[name] * f, dsp.Q31 - 1.0)


def _final_exp(sound: Sound, name: str, mod: _Patch, nb: int,
               default: float = 25.0) -> np.ndarray:
    """Valeur finale d'un paramètre exponentiel : ``getExp(neutre,
    octaves)``, octaves du réglage et des câbles."""
    octaves = laws.exp_range(name) * _preset_u(sound, name, default) \
        + _blocks(mod.oct(name), nb)
    return dsp.get_exp(NEUTRAL[name], octaves)


def _final_hybrid(sound: Sound, name: str, mod: _Patch, nb: int,
                  default: float = 25.0) -> np.ndarray:
    """Valeur −1..+1 d'un paramètre hybride (largeur, panoramique) :
    réglage et câbles additionnés."""
    return np.clip(_preset_u(sound, name, default)
                   + _blocks(mod.add(name), nb), -1.0, 1.0)


def _patched(sound: Sound, name: str) -> bool:
    """Un câble vise-t-il ce paramètre ?"""
    return any(param_of_destination(c.destination) == name
               for c in sound.patch_cables)


def _env_rates(sound: Sound, env, index: int, static: _Patch
               ) -> tuple[float, float, float, float]:
    """``(attaque, decay, palier, release)`` d'une enveloppe, en valeurs du
    firmware : vitesses en pas par échantillon, palier sur 2³¹. ``static`` :
    les câbles des sources constantes de la note."""
    prefix = "env%d" % index
    attack = float(laws.attack_rate(
        6.0 * laws.raw_unit(env.attack)
        + np.mean(static.oct(prefix + "Attack"))))
    decay = float(laws.decay_rate(
        laws.raw_unit(env.decay) + np.mean(static.add(prefix + "Decay"))))
    release = float(laws.release_rate(
        laws.raw_unit(env.release) + np.mean(static.add(prefix + "Release"))))
    sustain = 1073741824.0 * (1.0 + laws.raw_unit(env.sustain)) \
        * float(np.mean(static.factor(prefix + "Sustain")))
    return attack, decay, min(max(sustain, 0.0), dsp.Q31 - 1.0), release


def _env_times(sound: Sound, env, index: int, static: _Patch
               ) -> tuple[float, float, float, float]:
    """``(attaque, decay, sustain, release)`` d'une enveloppe, en secondes
    et en niveau 0..1, selon le firmware."""
    attack, decay, sustain, release = _env_rates(sound, env, index, static)
    steps = float(1 << 23) / ENGINE_RATE
    return (0.0 if attack > 245632 else steps / max(attack, 1e-9),
            steps / max(decay, 1e-9), sustain / dsp.Q31,
            steps / max(release, 1e-9))


def _ramp(values: np.ndarray, n: int, start: float,
          jumps: np.ndarray | None = None) -> np.ndarray:
    """La rampe d'amplitude du firmware : dans chaque bloc, la valeur va
    linéairement de celle du bloc précédent à la sienne. ``start`` : la
    valeur d'avant le premier bloc ; ``jumps`` : blocs qui sautent sans
    rampe (``shouldAvoidIncrementing``)."""
    values = np.asarray(values, dtype=np.float64)
    prev = np.empty_like(values)
    prev[0] = start
    prev[1:] = values[:-1]
    if jumps is not None:
        prev = np.where(jumps, values, prev)
    frac = (np.arange(1, dsp.BLOCK + 1, dtype=np.float64)) / dsp.BLOCK
    ramp = prev[:, None] + (values - prev)[:, None] * frac[None, :]
    return ramp.ravel()[:n]


# --------------------------------------------------------------------------- #
# Filtres : modes et réponse
# --------------------------------------------------------------------------- #

_LPF_MODES = {"12db": "12dB", "24db": "24dB", "24dbdrive": "24dBDrive",
              # Le SVF n'est pas porté : aucun son de la carte ne s'en sert.
              "svf_band": "12dB", "svf_notch": "12dB"}


def _community_at_least(firmware: str, version: tuple[int, ...]) -> bool:
    """Le son vient-il d'un firmware communautaire au moins aussi récent ?
    Une version sans ``c`` est un firmware officiel, plus ancien que tous.
    Sans version, le son est réputé récent."""
    text = str(firmware or "").strip().lower()
    if not text:
        return True
    if not text.startswith("c"):
        return False
    parts = []
    for piece in text[1:].split("-")[0].split("."):
        try:
            parts.append(int(piece))
        except ValueError:
            break
    return tuple(parts) >= tuple(version)


def _filter_modes(sound: Sound) -> tuple[str | None, str | None, str]:
    """``(passe-bas, passe-haut, routage)`` tels que le firmware les rend :
    un son FM venu d'un firmware antérieur au communautaire 1.2.0 a ses
    filtres éteints (``Sound::readFromFile``)."""
    lpf = str(sound.lpf_mode or "24dB").lower()
    hpf = str(sound.hpf_mode or "HPLadder").lower()
    lpf_mode = None if lpf == "off" else _LPF_MODES.get(lpf, "24dB")
    hpf_mode = None if hpf == "off" else "HPLadder"
    if sound.mode == "fm" and not _community_at_least(sound.firmware,
                                                      (1, 2, 0)):
        lpf_mode = hpf_mode = None
    route = {"l2h": "L2H", "para": "PARA"}.get(
        str(sound.filter_route or "").lower(), "H2L")
    return lpf_mode, hpf_mode, route


def _filtered(x: np.ndarray, route: str, lpf, hpf, jitter: np.ndarray
              ) -> np.ndarray:
    """Un canal à travers les filtres, dans l'ordre du routage
    (``FilterSet::renderLong``). ``lpf``/``hpf`` : configurations ou
    ``None``."""
    def low(signal):
        return signal if lpf is None else dsp.lpf_process(signal, lpf, jitter)

    def high(signal):
        return signal if hpf is None else dsp.hpf_process(signal, hpf)

    if route == "L2H":
        return high(low(x))
    if route == "PARA":
        if lpf is None or hpf is None:
            return high(low(x))
        return low(x) + high(x)
    return low(high(x))


@lru_cache(maxsize=128)
def _filter_configs(mode: str, cutoff: float, resonance: float, hpf: float):
    """Les configurations du firmware pour des réglages affichés."""
    freq = dsp.get_exp(NEUTRAL["lpfFrequency"],
                       laws.exp_octaves("lpfFrequency", cutoff))
    res = NEUTRAL["lpfResonance"] * (1.0 + float(laws.unit(resonance)))
    lpf = dsp.lpf_config(mode, [float(freq)], [res])
    hcfg = None
    if hpf >= 0:
        hfreq = dsp.get_exp(NEUTRAL["hpfFrequency"],
                            laws.exp_octaves("hpfFrequency", hpf))
        hcfg = dsp.hpf_config([float(hfreq)], [0.0])
    return lpf, hcfg


def filter_response(freqs, cutoff: float, resonance: float,
                    mode: str = "24dB", hpf: float | None = None
                    ) -> np.ndarray:
    """Réponse en décibels des filtres du firmware, pour l'affichage :
    l'échelle passe-bas (et le passe-haut en échelle si ``hpf`` est donné),
    linéarisée (:func:`.dsp.lpf_response`), avec la compensation de niveau
    que la voix applique. 0 dB : le niveau d'un filtre ouvert, sans
    résonance. Réglages en affichage 0..50."""
    lpf_mode = _LPF_MODES.get(str(mode or "24dB").lower(), "24dB")
    lpf, hcfg = _filter_configs(
        lpf_mode, round(float(cutoff), 2), round(float(resonance), 2),
        -1.0 if hpf is None else round(float(hpf), 2))
    freqs = np.asarray(freqs, dtype=np.float64)
    response = dsp.lpf_response(lpf, freqs) * float(lpf.gain[0])
    if hcfg is not None:
        response = response * dsp.hpf_response(hcfg, freqs) \
            * float(hcfg.gain[0])
    return 20.0 * np.log10(np.maximum(np.abs(response), 1e-6))


# --------------------------------------------------------------------------- #
# Échantillons
# --------------------------------------------------------------------------- #

_SAMPLE_CACHE: OrderedDict = OrderedDict()
_SAMPLE_CACHE_SIZE = 48
_SAMPLE_LOCK = threading.Lock()


def _load_sample(sd: SDCard | None, osc) -> tuple[np.ndarray, int] | None:
    """L'échantillon d'un oscillateur, lu une fois puis gardé : ``(données
    dans [−1, 1], fréquence)``, recadrées sur la zone jouée — ``(n,)`` pour
    un fichier mono, ``(n, 2)`` pour un stéréo : le Deluge le joue en stéréo
    (``Source::renderInStereo``). Mesuré sur la machine le 23 octobre 2026 :
    chaque canal sort au même gain, à l'échantillon près ; la moyenne des
    deux, rendue jusque-là, faisait perdre 5 dB à un piano dont les canaux
    s'opposent en partie."""
    if sd is None or not osc.file_name:
        return None
    from . import wav

    path = sd.resolve_sample(osc.file_name)
    if path is None:
        log.debug("échantillon introuvable pour le rendu : %s", osc.file_name)
        return None
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        stamp = 0
    key = (str(path), stamp)
    # Les voix d'une écoute se calculent dans plusieurs fils à la fois.
    with _SAMPLE_LOCK:
        cached = _SAMPLE_CACHE.get(key)
        if cached is None:
            try:
                data, file_sr = wav.read(path, max_frames=ENGINE_RATE * 20)
            except Exception as exc:  # noqa: BLE001
                log.debug("échantillon illisible %s : %s", path, exc)
                return None
            if data.size == 0 or not file_sr:
                return None
            if data.ndim == 2:
                data = data[:, 0] if data.shape[1] == 1 else data[:, :2]
            cached = (np.ascontiguousarray(data, dtype=np.float32),
                      int(file_sr))
            _SAMPLE_CACHE[key] = cached
            while len(_SAMPLE_CACHE) > _SAMPLE_CACHE_SIZE:
                _SAMPLE_CACHE.popitem(last=False)
        else:
            _SAMPLE_CACHE.move_to_end(key)
    data, file_sr = cached
    zone = getattr(osc, "zone", None)
    if zone is not None:
        scale = file_sr / 1000.0 if zone.unit == "ms" else 1.0
        start = max(0, int(zone.start * scale))
        end = int(zone.end * scale) if zone.end >= 0 else data.size
        end = min(data.size, end)
        if end > start + 1:
            data = data[start:end]
    if osc.reversed:
        data = data[::-1]
    return data, file_sr


def _sample_wave(data: np.ndarray, increments: np.ndarray, n: int,
                 loop: bool) -> np.ndarray:
    """Lecture à vitesse variable, un incrément par bloc
    (:func:`dsp.sample_increment` réglé comme une note), comme la machine
    (:func:`dsp.read_sample`) ; muette après la fin, ou bouclée. ``(n,)``
    d'un échantillon mono, ``(2, n)`` d'un stéréo.

    Mesuré sur la machine le 23 octobre 2026 (export de pistes) :
    l'interpolation linéaire d'avant laissait un écart de −19 dB sur un
    piano joué à l'octave et de −33 dB sur une caisse claire à 48 kHz ;
    celle-ci les ramène sous −68 dB."""
    return dsp.read_sample(data, increments, n, loop)


# --------------------------------------------------------------------------- #
# La voix
# --------------------------------------------------------------------------- #

def _graine(nom: str) -> int:
    """Graine stable du bruit, tirée du nom du son.

    C'était ``hash(nom)``. Or Python randomise le hachage des chaînes à
    chaque démarrage : le même preset rendait un bruit différent d'une
    session à l'autre, alors que le générateur promet qu'une graine donnée
    redonne le même son. Un test de rendu est tombé dessus — une basse
    « lo-fi » quasi muette, dans un processus sur plusieurs.

    ``crc32`` ne vaut rien en cryptographie, mais il est stable, rapide et
    c'est tout ce qu'on lui demande ici.
    """
    return zlib.crc32(str(nom or "").encode("utf-8")) & 0x7FFFFFFF


def _retrig(osc) -> int:
    """``retrigPhase`` sur 32 bits ; ``0xFFFFFFFF`` quand il est coupé."""
    value = int(getattr(osc, "retrig_phase", -1))
    return dsp.MASK32 if value == -1 else value & dsp.MASK32


def _start_phase(kind: str, retrig: int, rng: np.random.Generator) -> int:
    """La phase de départ d'une voix d'oscillateur : tirée au hasard
    (``randomizeOscPhases``), sauf redémarrage réglé — zéro de l'onde,
    plus ``retrigPhase``."""
    if retrig == dsp.MASK32:
        return int(rng.integers(0, 1 << 32))
    zero = (1 << 30) if kind == "triangle" else 0
    return (zero + retrig) & dsp.MASK32


_WAVE_KINDS = ("sine", "triangle", "square", "saw", "analogSaw",
               "analogSquare")


def _render_voice(sound: Sound, note: int, n: int, gate: float,
                  velocity: float, sd: SDCard | None, bpm: float,
                  glide_from: float, rng: np.random.Generator
                  ) -> np.ndarray:
    """Une note du son (``Voice::render``), ``(2, n)`` à l'échelle entière,
    avant les effets du son."""
    block = dsp.BLOCK
    nb = -(-n // block)
    osc1, osc2 = sound.osc1, sound.osc2
    if osc1 is None or osc2 is None:
        log.debug("son sans oscillateur : rendu silencieux")
        return np.zeros((2, n))

    # -- sources constantes de la note (``voice.cpp``) ------------------- #
    midi_velocity = max(1.0, min(127.0, float(velocity) * 127.0))
    constants = {
        "velocity": float(laws.velocity_source(midi_velocity)),
        "note": float(laws.note_source(note)),
        # *random* : une valeur tirée à chaque note, pas une dérive.
        "random": float(rng.uniform(-1.0, 1.0)),
        "aftertouch": 0.0,
    }
    static = _patch(sound, constants, only=set(constants))

    # Un échantillon en mode ONCE se joue jusqu'au bout : le Deluge ignore
    # alors la fin de la note.
    if osc1.is_sample and int(getattr(osc1, "loop_mode", 0)) == 1:
        gate = 1.0
    release_block = nb if gate >= 1.0 else int(round(gate * n / block))

    # -- enveloppes, un bloc à la fois ----------------------------------- #
    envelopes = {}
    end_block = nb
    attack1 = 0.0
    for index, env in ((1, sound.env1), (2, sound.env2)):
        attack, decay, sustain, release = _env_rates(sound, env, index, static)
        has_sustain = int(env.sustain) != INT32_MIN \
            or int(env.decay) > int(env.release)
        values, silent = dsp.envelope_blocks(attack, decay, sustain, release,
                                             nb, release_block, has_sustain)
        if index == 1:
            attack1 = attack
            end_block = silent
        envelopes[index] = values

    # -- LFO ------------------------------------------------------------- #
    def lfo_increment(lfo, key):
        if getattr(lfo, "sync_level", 0):
            hz = synced_hz(lfo.sync_level, bpm)
            return hz * dsp.Q32 / ENGINE_RATE
        return float(_final_exp(sound, key, static, 1)[0])

    lfo1 = dsp.lfo_blocks(sound.lfo1.type, np.full(nb, lfo_increment(
        sound.lfo1, "lfo1Rate")), dsp.lfo_start_phase(sound.lfo1.type, False),
        rng)
    lfo2 = dsp.lfo_blocks(sound.lfo2.type, np.full(nb, lfo_increment(
        sound.lfo2, "lfo2Rate")), dsp.lfo_start_phase(sound.lfo2.type, True),
        rng)

    sources = dict(constants)
    sources.update({
        "envelope1": envelopes[1] / dsp.Q31,
        "envelope2": envelopes[2] / dsp.Q31,
        "lfo1": lfo1 / dsp.Q31,
        "lfo2": lfo2 / dsp.Q31,
    })
    mod = _patch(sound, sources)

    # -- hauteur --------------------------------------------------------- #
    pitch_oct = 4.0 * _preset_u(sound, "pitch") + _blocks(mod.oct("pitch"), nb)
    porta = _display(sound, "portamento", 0.0)
    if glide_from and porta > 0 and sound.polyphonic != "legato":
        glide = laws.glide_seconds(porta)
        if glide > 0:
            t = np.arange(nb, dtype=np.float64) * block / ENGINE_RATE
            pitch_oct = pitch_oct + float(glide_from) / 12.0 * (
                1.0 - laws.attack_curve(t / glide))

    # -- amplitude et filtres ------------------------------------------- #
    instant = attack1 > 245632
    volume = _final_volume(sound, "volume", mod, nb)
    overall = np.minimum(volume * (envelopes[1] / 2.0 + float(1 << 30))
                         * 4.0 / dsp.Q32, dsp.Q31 - 1.0)
    overall_ramp = _ramp(overall, n, overall[0] if instant else 0.0)

    lpf_mode, hpf_mode, route = _filter_modes(sound)
    has_filters = lpf_mode is not None or hpf_mode is not None
    do_lpf = lpf_mode is not None and (
        lpf_mode == "24dBDrive" or _patched(sound, "lpfFrequency")
        or int(sound.param("lpfFrequency", 0x7FFFFFFF)) < 0x7FFFFFD2
        or int(sound.param("lpfMorph", INT32_MIN)) > INT32_MIN)
    do_hpf = hpf_mode is not None and (
        _patched(sound, "hpfFrequency")
        or int(sound.param("hpfFrequency", INT32_MIN)) != INT32_MIN
        or int(sound.param("hpfMorph", INT32_MIN)) > INT32_MIN)
    voices = max(1, min(8, int(sound.unison_num or 1)))
    neutral_unison = math.floor(134217728.0 / math.sqrt(voices))
    filter_gain = np.full(nb, 2.0 * neutral_unison)
    lpf = hpf = None
    if do_lpf:
        lpf = dsp.lpf_config(
            lpf_mode, _final_exp(sound, "lpfFrequency", mod, nb, 50.0),
            _final_linear(sound, "lpfResonance", mod, nb, 0.0),
            _final_linear(sound, "lpfMorph", mod, nb, 0.0))
        filter_gain = filter_gain * lpf.gain
    filter_gain = np.floor(filter_gain * 1720000000.0 / dsp.Q32) * 2.0
    if do_hpf:
        hpf = dsp.hpf_config(_final_exp(sound, "hpfFrequency", mod, nb, 0.0),
                             _final_linear(sound, "hpfResonance", mod, nb,
                                           0.0))
        filter_gain = filter_gain * hpf.gain
    jumps = np.concatenate(([False], filter_gain[1:] != filter_gain[:-1]))

    # -- oscillateurs ---------------------------------------------------- #
    stereo_unison = bool(sound.unison_spread) and voices > 1
    pans =dsp.unison_pans(int(sound.unison_spread or 0), voices)
    unison_l, unison_r = dsp.pan_amplitudes(pans)
    buf = np.zeros((2, n)) if stereo_unison else np.zeros((1, n))
    stereo_waves = []

    def add(wave, u):
        if wave.ndim == 2:
            # Un échantillon stéréo s'ajoute après les sources mono, que le
            # firmware recopie alors sur les deux canaux (``Voice::render``).
            stereo_waves.append((wave, u))
            return
        if stereo_unison:
            dsp.mix_into(buf[0], wave, unison_l[u])
            dsp.mix_into(buf[1], wave, unison_r[u])
        else:
            buf[0] += wave

    # La hauteur, en entiers comme la machine (``calculatePhaseIncrements``,
    # puis ``adjustPitch`` au rendu) : réglages fins de l'oscillateur et du
    # son, désaccord de l'unisson — chacun lu dans ``centAdjustTableSmall``
    # et tronqué —, puis hauteur d'ensemble et hauteur propre, par bloc.
    detuners = dsp.unison_detuners(int(sound.unison_detune or 0), voices)
    master = dsp.fine_tuner(0)
    overall_pitch = dsp.pitch_adjustment(pitch_oct)

    def tuned(base, cents_offset, extra_oct):
        fine = max(-50, min(50, int(cents_offset or 0))) * dsp.CENT_SCALE
        inc = dsp.fine_tune(dsp.fine_tune(base, dsp.fine_tuner(fine)), master)
        own = dsp.pitch_adjustment(np.broadcast_to(
            np.asarray(extra_oct, dtype=np.float64), (nb,)))
        out = []
        for u in range(voices):
            v = dsp.fine_tune(inc, detuners[u]) if voices > 1 else inc
            out.append(dsp.adjust_pitch(dsp.adjust_pitch(
                np.full(nb, v, dtype=np.int64), overall_pitch), own))
        return out

    def increments(transpose, cents_offset, extra_oct):
        return tuned(dsp.note_increment(note + int(sound.transpose)
                                        + int(transpose)),
                     cents_offset, extra_oct)

    def osc_kind(osc):
        kind = str(osc.type or "")
        if kind in _WAVE_KINDS:
            return kind
        if kind in ("inLeft", "inRight", "inStereo"):
            return None   # l'entrée audio : rien à entendre ici
        return "saw"      # échantillon absent, DX7 : une dent de scie

    letters = ("A", "B")
    pulse = {}
    osc_oct = {}
    for s, letter in enumerate(letters):
        pw = _final_hybrid(sound, "osc%sPulseWidth" % letter, mod, nb)
        pulse[s] = np.clip(np.round(pw * dsp.Q31), -dsp.Q31,
                           dsp.Q31 - 1.0).astype(np.int64)
        osc_oct[s] = 4.0 * _preset_u(sound, "osc%sPitch" % letter) \
            + _blocks(mod.oct("osc%sPitch" % letter), nb)

    if sound.mode == "fm":
        _fm_sources(sound, mod, nb, n, overall, instant, neutral_unison,
                    increments, osc_oct, pitch_oct, add, rng)
    else:
        # Bruit : une fois pour toute la voix (``voice.cpp``).
        noise = _final_volume(sound, "noiseVolume", mod, nb, 0.0)
        if np.any(noise > 0):
            level = noise / 2.0
            if has_filters:
                level = level * filter_gain / dsp.Q32 * 16.0
            level = np.minimum(level, 268435455.0) / 4.0
            amp = np.repeat(level, block)[:n]
            for c in range(buf.shape[0]):
                buf[c] += rng.integers(-(1 << 31), 1 << 31, n) * amp / dsp.Q32

        if sound.mode == "ringmod":
            ring = np.full(nb, float(1 << 27))
            if has_filters:
                ring = ring * filter_gain / dsp.Q32 * 16.0
            kinds = [osc_kind(osc1) or "saw", osc_kind(osc2) or "saw"]
            for kind in kinds:
                if kind in ("saw", "analogSaw"):
                    ring = ring * 2.0
            incs = [increments(osc.transpose, osc.cents, osc_oct[s])
                    for s, osc in enumerate((osc1, osc2))]
            ring_amp = np.repeat(ring, block)[:n]
            for u in range(voices):
                waves = []
                for s, osc in enumerate((osc1, osc2)):
                    retrig = _retrig(osc)
                    start = _start_phase(kinds[s], retrig, rng)
                    wave, _ = dsp.oscillator(kinds[s], incs[s][u], n, start,
                                             None, pulse[s], retrig)
                    waves.append(wave)
                add(waves[0] * waves[1] / dsp.Q32 * ring_amp / dsp.Q32, u)
        else:
            scratch = None
            for s, (osc, letter) in enumerate(zip((osc1, osc2), letters)):
                volume_s = _final_volume(sound, "osc%sVolume" % letter, mod,
                                         nb, 50.0 if s == 0 else 0.0)
                if not np.any(volume_s > 0):
                    continue
                if has_filters:
                    amp_blocks = np.round(volume_s * filter_gain / dsp.Q32)
                else:
                    amp_blocks = np.floor(volume_s / 16.0)
                amp = _ramp(amp_blocks, n, amp_blocks[0] if instant else 0.0,
                            jumps)
                sample = _load_sample(sd, osc) if osc.is_sample else None
                if sample is not None:
                    data, file_sr = sample
                    loop = int(getattr(osc, "loop_mode", 0)) == 2
                    base = dsp.sample_increment(
                        note + int(sound.transpose) + int(osc.transpose),
                        file_sr)
                    for u, incs in enumerate(tuned(base, osc.cents,
                                                   osc_oct[s])):
                        add(4.0 * amp * _sample_wave(data, incs, n, loop), u)
                    continue
                kind = osc_kind(osc)
                if kind is None:
                    continue
                incs = increments(osc.transpose, osc.cents, osc_oct[s])
                retrig = _retrig(osc)
                if scratch is None:
                    # Un seul tampon pour toutes les ondes de la note :
                    # chacune est ajoutée avant que la suivante ne l'écrase.
                    scratch = np.empty(n)
                for u in range(voices):
                    wave, _ = dsp.oscillator(
                        kind, incs[u], n, _start_phase(kind, retrig, rng), amp,
                        pulse[s], retrig, out=scratch)
                    add(wave, u)

    if stereo_waves:
        if buf.shape[0] == 1:
            buf = np.vstack((buf, buf))
        for wave, u in stereo_waves:
            if stereo_unison:
                buf[0] += wave[0] * unison_l[u]
                buf[1] += wave[1] * unison_r[u]
            else:
                buf += wave

    # -- filtres, volume, saturation, panoramique ----------------------- #
    out = np.zeros((2, n))
    lpf_cfg = lpf if do_lpf else None
    hpf_cfg = hpf if do_hpf else None
    clipping = int(sound.clipping_amount or 0)
    channels = []
    for c in range(buf.shape[0]):
        x = buf[c]
        if lpf_cfg is not None or hpf_cfg is not None:
            jitter = dsp.ladder_jitter(n, rng)[0] if lpf_cfg is not None \
                else np.ones(n)
            x = _filtered(x, route, lpf_cfg, hpf_cfg, jitter)
        if sound.mode != "fm":
            x = x * overall_ramp
            x /= dsp.Q31
        if clipping > 0:
            x, _ = dsp.saturate(x, clipping)
        channels.append(x)
    if len(channels) == 1:
        channels.append(channels[0])
    out[0], out[1] = channels
    if _patched(sound, "pan"):
        pan = _final_hybrid(sound, "pan", mod, nb) * float(1 << 30)
        left, right = dsp.pan_amplitudes(pan)
        out[0] *= np.repeat(left, block)[:n]
        out[1] *= np.repeat(right, block)[:n]
    if end_block < nb:
        out[:, end_block * block:] = 0.0
    return out


def _fm_sources(sound: Sound, mod: _Patch, nb: int, n: int,
                overall: np.ndarray, instant: bool, neutral_unison: float,
                increments, osc_oct: dict, pitch_oct: np.ndarray, add,
                rng: np.random.Generator) -> None:
    """Le moteur FM (``voice.cpp``) : le second modulateur, éventuellement
    passé dans le premier, puis les deux additionnés modulent la phase des
    deux porteuses. L'amplitude d'ensemble (volume, enveloppe 1) est déjà
    dans celle des porteuses."""
    block = dsp.BLOCK
    overall_fm = overall * neutral_unison / dsp.Q32 * 8.0
    carriers = []
    sources = zip((sound.osc1, sound.osc2), ("A", "B"))
    for s, (osc, letter) in enumerate(sources):
        volume_s = _final_volume(sound, "osc%sVolume" % letter, mod, nb,
                                 50.0 if s == 0 else 0.0)
        amp_blocks = np.minimum(volume_s * overall_fm / dsp.Q32, 134217727.0)
        amp = _ramp(amp_blocks, n, amp_blocks[0] if instant else 0.0)
        feedback = _final_linear(sound, "carrier%dFeedback" % (s + 1), mod,
                                 nb, 0.0)
        carriers.append((osc, amp, amp_blocks, feedback,
                         increments(osc.transpose, osc.cents, osc_oct[s])))
    modulators = []
    for m, modulator in enumerate((sound.modulator1, sound.modulator2)):
        amount = _final_volume(sound, "modulator%dAmount" % (m + 1), mod, nb,
                               0.0)
        feedback = _final_linear(sound, "modulator%dFeedback" % (m + 1), mod,
                                 nb, 0.0)
        extra = _blocks(mod.oct("modulator%dPitch" % (m + 1)), nb)
        modulators.append((modulator, amount, _ramp(amount, n, amount[0]),
                           feedback,
                           increments(modulator.transpose, modulator.cents,
                                      extra)))
    chain = bool(int(getattr(sound.modulator2, "to_modulator1", 0) or 0))
    active = [bool(np.any(m[1] > 0)) for m in modulators]

    def phase_of(thing):
        retrig = _retrig(thing)
        if retrig == dsp.MASK32:
            return int(rng.integers(0, 1 << 32))
        return retrig

    for u in range(len(carriers[0][4])):
        modulation = None
        if active[1] and not (chain and not active[0]):
            m1 = modulators[1]
            modulation, _, _ = dsp.fm_operator(m1[4][u], n, phase_of(m1[0]),
                                               m1[2], None, m1[3])
            m0 = modulators[0]
            if chain:
                modulation, _, _ = dsp.fm_operator(
                    m0[4][u], n, phase_of(m0[0]), m0[2], modulation, m0[3])
            elif active[0]:
                extra, _, _ = dsp.fm_operator(m0[4][u], n, phase_of(m0[0]),
                                              m0[2], None, m0[3])
                modulation = modulation + extra
        elif active[0] and not active[1]:
            m0 = modulators[0]
            modulation, _, _ = dsp.fm_operator(m0[4][u], n, phase_of(m0[0]),
                                               m0[2], None, m0[3])
        for osc, amp, amp_blocks, feedback, incs in carriers:
            if not np.any(amp_blocks > 0):
                continue
            wave, _, _ = dsp.fm_operator(incs[u], n, phase_of(osc), amp,
                                         modulation, feedback)
            add(wave, u)


# --------------------------------------------------------------------------- #
# Les effets du son
# --------------------------------------------------------------------------- #

def _raw(sound: Sound, key: str, default: int) -> float:
    """Valeur brute d'un réglage de fichier (``eq`` compris)."""
    try:
        return float(int(sound.param(key, default)))
    except (TypeError, ValueError):
        return float(default)


def _sound_chain(sound: Sound, stereo: np.ndarray, bpm: float,
                 limit_feedback: bool) -> tuple[np.ndarray, np.ndarray]:
    """Les effets du son entier, voix additionnées (``Sound::render``) :
    panoramique, réduction, mod FX, égaliseur, delay, puis l'envoi vers la
    réverbération et le volume post-effets. Les modulations s'y prennent au
    repos. Rend ``(sec, envoi)`` à l'échelle entière.

    :param limit_feedback: le Deluge borne la rétroaction du delay à 0,94
        hors lecture d'un clip — l'audition d'un preset.
    """
    rest = {"velocity": 0.0, "note": 0.0, "random": 0.0, "aftertouch": 0.0}
    mod = _patch(sound, rest, only=set(rest))
    out = np.array(stereo, dtype=np.float64)
    n = out.shape[1]

    if not _patched(sound, "pan"):
        left, right = dsp.pan_amplitudes(laws.raw_unit(
            sound.param("pan", 0)) * float(1 << 30))
        out[0] *= float(left)
        out[1] *= float(right)

    post_fx = float(_final_volume(sound, "volumePostFX", mod, 1, 40.0)[0])
    post_reverb = float(_final_volume(sound, "volumePostReverbSend", mod,
                                      1)[0])
    reverb_amount = float(_final_volume(sound, "reverbAmount", mod, 1, 0.0)[0])

    out, post_fx = dsp.bitcrush_srr(out, _raw(sound, "bitCrush", INT32_MIN),
                                    _raw(sound, "sampleRateReduction",
                                         INT32_MIN), post_fx)
    rate = float(_final_exp(sound, "modFXRate", mod, 1)[0])
    depth = float(_final_volume(sound, "modFXDepth", mod, 1)[0])
    out, post_fx = dsp.mod_fx(out, sound.mod_fx_type, rate, depth,
                              _raw(sound, "modFXOffset", 0),
                              _raw(sound, "modFXFeedback", 0), post_fx)
    eq = getattr(sound, "eq", {}) or {}
    out = dsp.equalizer(out, float(eq.get("bass", 0)),
                        float(eq.get("treble", 0)),
                        float(eq.get("bassFrequency", 0)),
                        float(eq.get("trebleFrequency", 0)))

    feedback = float(_final_linear(sound, "delayFeedback", mod, 1, 0.0)[0])
    if limit_feedback:
        feedback = min(feedback, float((1 << 30) - (1 << 26)))
    if feedback >= 256:
        delay_rate = float(_final_exp(sound, "delayRate", mod, 1)[0])
        level = int(getattr(sound, "delay_sync_level", 0) or 0)
        if level > 0:
            hz = synced_hz(level, bpm)
            seconds = 1.0 / hz if hz > 0 else 0.25
            length = min(max(seconds * ENGINE_RATE * float(1 << 24)
                             / max(delay_rate, 1.0), 1.0), 88200.0)
        else:
            length = float(dsp.delay_samples(delay_rate))
        out = dsp.delay(out, length, feedback,
                        bool(getattr(sound, "delay_ping_pong", 1)),
                        bool(getattr(sound, "delay_analog", 0)))

    # ``processReverbSendAndVolume`` : l'envoi suit le volume du morceau et
    # le volume post-effets du son.
    send_amount = SONG_REVERB_ADJUST * reverb_amount / float(1 << 27)
    send_and_post = post_fx * send_amount / float(1 << 27)
    send = (out[0] + out[1]) * send_and_post * 2.0 / dsp.Q32 \
        if reverb_amount > 0 else np.zeros(n)
    dry = out * (post_reverb * post_fx / float(1 << 54))
    return dry, send


# --------------------------------------------------------------------------- #
# Fréquence de sortie
# --------------------------------------------------------------------------- #

def _resampled(audio: np.ndarray, frames: int) -> np.ndarray:
    """``(n, 2)`` ramené à ``frames`` images par interpolation linéaire,
    après une moyenne glissante de la largeur du rapport quand on descend
    (contre le repliement). L'application rend à 44,1 kHz : seuls les tests
    descendent à 22,05 kHz."""
    audio = np.asarray(audio, dtype=np.float64)
    if audio.shape[0] == frames:
        return audio
    if audio.shape[0] == 0:
        return np.zeros((frames, 2))
    ratio = audio.shape[0] / float(max(frames, 1))
    width = int(round(ratio))
    if width > 1:
        kernel = np.ones(width) / width
        audio = np.stack([np.convolve(audio[:, c], kernel, mode="same")
                          for c in range(audio.shape[1])], axis=1)
    src = np.arange(audio.shape[0], dtype=np.float64)
    dst = np.linspace(0.0, audio.shape[0] - 1, frames)
    return np.stack([np.interp(dst, src, audio[:, c])
                     for c in range(audio.shape[1])], axis=1)


def _to_engine(audio: np.ndarray, sr: int) -> np.ndarray:
    """Un rendu ``(n, 2)`` à ``sr``, ramené à la fréquence du moteur."""
    if int(sr) == ENGINE_RATE:
        return np.asarray(audio, dtype=np.float64)
    frames = max(1, int(round(audio.shape[0] * ENGINE_RATE / float(sr))))
    return _resampled(audio, frames)


# --------------------------------------------------------------------------- #
# Rendu d'un son
# --------------------------------------------------------------------------- #

def sound_effects(sound: Sound, audio: np.ndarray, sr: int = 44100,
                  bpm: float = PREVIEW_BPM, limit_feedback: bool = True
                  ) -> np.ndarray:
    """Les effets d'un son — panoramique, réduction, mod FX, égaliseur,
    delay, réverbération — sur un rendu stéréo de ses voix déjà
    additionnées (:func:`render_sound` avec ``effects=False``), comme le
    Deluge les applique au son entier."""
    if audio.size == 0:
        return audio
    frames = audio.shape[0]
    engine = _to_engine(audio, sr).T / dsp.OUTPUT_GAIN
    dry, send = _sound_chain(sound, engine, bpm, limit_feedback)
    mixed = dsp.output_stage(dry + dsp.reverb(send, PREVIEW_REVERB))
    return _resampled(mixed.T, frames).astype(np.float32)


def render_sound(sound: Sound, note: int = 48, seconds: float = 2.5,
                 sr: int = 44100, gate: float = 0.7, velocity: float = 0.9,
                 sd: SDCard | None = None, bpm: float = PREVIEW_BPM,
                 glide_from: float = 0.0, effects: bool = True
                 ) -> np.ndarray:
    """Rend un son en float32, forme ``(frames, 2)``.

    :param note: note MIDI jouée.
    :param gate: fraction de la durée pendant laquelle la touche est tenue.
    :param velocity: vélocité de 0 à 1 (×127 pour la machine) ; elle
        n'agit que par les câbles qui partent de ``velocity``, comme sur le
        Deluge.
    :param sd: carte, nécessaire pour lire les oscillateurs de type
        ``sample``. Sans elle, ces oscillateurs sont remplacés par une onde.
    :param bpm: tempo, pour un LFO ou un delay calés sur le morceau.
    :param glide_from: écart en demi-tons de la note précédente : la note
        part de là et glisse, si le son a un glissé (``portamento``) et
        n'est pas en legato (``Voice::setupPorta``).
    :param effects: ``False`` rend la voix seule, avant panoramique, mod FX,
        delay, réverbération et volume — :func:`render_parts` les applique
        au son entier (:func:`sound_effects`).

    Le niveau est celui de la sortie du Deluge, au volume du morceau que
    l'atelier écrit ; une crête au-delà de 0,99 ramène le tout sous 0,99,
    là où la machine écrêterait. Ne lève jamais : un son impossible à
    rendre donne un tableau silencieux.
    """
    audio = _render_float(sound, note, seconds, sr, gate, velocity, sd, bpm,
                          glide_from, effects)
    if effects:
        peak = float(np.max(np.abs(audio)))
        if peak > 0.99:
            audio *= 0.99 / peak
    return audio


def _render_float(sound: Sound, note: int, seconds: float, sr: int,
                  gate: float, velocity: float, sd: SDCard | None,
                  bpm: float, glide_from: float = 0.0,
                  effects: bool = True) -> np.ndarray:
    """:func:`render_sound` sans le rattrapage de crête : les rendus qu'on
    additionne (rangées d'un kit, coups d'un motif) gardent ainsi leurs
    rapports, et seul le mélange est ramené."""
    frames = max(1, int(float(seconds) * int(sr)))
    try:
        n = max(1, int(round(float(seconds) * ENGINE_RATE)))
        rng = np.random.default_rng(_graine(sound.name))
        voice = _render_voice(sound, int(note), n, float(gate),
                              float(velocity), sd, float(bpm),
                              float(glide_from or 0.0), rng)
        if effects:
            dry, send = _sound_chain(sound, voice, float(bpm), True)
            voice = dsp.output_stage(dry + dsp.reverb(send, PREVIEW_REVERB))
        else:
            # La voix seule, au gain de sortie : :func:`sound_effects` la
            # reprend et passe l'étage de sortie une fois, à la fin.
            voice = voice * dsp.OUTPUT_GAIN
        audio = _resampled(voice.T, frames)
        # Un fondu de 5 ms en fin de rendu : la fenêtre se termine parfois
        # au milieu du son, et une coupure nette s'entend comme un clic.
        fade = min(frames, max(1, int(0.005 * int(sr))))
        audio[-fade:] *= np.linspace(1.0, 0.0, fade)[:, None]
        return audio.astype(np.float32)
    except Exception as exc:  # noqa: BLE001 - rempart : on rend du silence
        log.exception("rendu impossible : %s", exc)
        return np.zeros((frames, 2), dtype=np.float32)


def tail_seconds(sound: Sound) -> float:
    """Durée d'extinction d'une note : le release de l'enveloppe 1, selon
    le firmware, jusqu'à −40 dB — 80 % de l'étape, la courbe
    ``decayTableSmall8`` y valant 1/100 —, borné à :data:`MAX_TAIL_S`."""
    try:
        release = float(laws.release_seconds(
            laws.raw_unit(sound.env1.release)))
    except Exception:  # noqa: BLE001
        release = 0.8
    return max(0.2, min(MAX_TAIL_S, 0.8 * release))


# --------------------------------------------------------------------------- #
# Aperçus
# --------------------------------------------------------------------------- #

#: Phrases d'audition par catégorie : un lead se juge sur une mélodie, une
#: nappe sur un accord tenu, une basse sur une note grave répétée.
_PREVIEW_NOTES: dict[str, list[int]] = {
    "Bass": [36, 36, 43, 36],
    "Lead": [60, 63, 67, 70],
    "Pad": [48, 55, 60, 64],
    "Pluck": [60, 64, 67, 72],
    "Keys": [48, 52, 55, 60],
    "Drone": [36],
    "Arp": [60, 64, 67, 72],
    "FX": [48],
    "Autre": [48, 55],
}


def preview_notes(sound: Sound) -> list[int]:
    """La petite phrase d'audition d'un son, selon sa catégorie : celle que
    rend l'ordinateur, et que joue le Deluge branché."""
    try:
        category = sound.category_guess()
    except Exception:  # noqa: BLE001
        category = "Autre"
    return list(_PREVIEW_NOTES.get(category, _PREVIEW_NOTES["Autre"]))



def render_preview(preset: SynthPreset, notes: list[int] | None = None,
                   sr: int = 44100, sd: SDCard | None = None) -> np.ndarray:
    """Petite phrase d'audition, choisie selon la catégorie du preset.

    Les notes se succèdent avec un léger recouvrement, pour que les queues de
    réverbération ne soient pas coupées net ; les effets traitent la phrase
    entière, comme le son entier sur la machine.
    """
    sound = preset.sound
    if notes is None:
        notes = preview_notes(sound)
    notes = [int(n) for n in (notes or [48]) if 0 <= int(n) <= 127] or [48]

    step = 0.55
    tail = 1.1
    total_s = step * len(notes) + tail
    frames = int(total_s * sr)
    n = int(total_s * ENGINE_RATE)
    voices = np.zeros((2, n))
    try:
        rng = np.random.default_rng(_graine(sound.name))
        length = int((step + tail) * ENGINE_RATE)
        for index, note in enumerate(notes):
            start = int(index * step * ENGINE_RATE)
            count = min(length, n - start)
            if count <= 0:
                continue
            voice = _render_voice(sound, note, count, 0.6 * length / count,
                                  0.85, sd, PREVIEW_BPM, 0.0, rng)
            voices[:, start:start + count] += voice
        dry, send = _sound_chain(sound, voices, PREVIEW_BPM, True)
        mixed = dry + dsp.reverb(send, PREVIEW_REVERB)
    except Exception as exc:  # noqa: BLE001 - rempart : on rend du silence
        log.exception("aperçu impossible : %s", exc)
        return np.zeros((frames, 2), dtype=np.float32)
    out = _resampled(dsp.output_stage(mixed).T, frames)
    peak = float(np.max(np.abs(out)))
    if peak > 0.99:
        out *= 0.99 / peak
    return out.astype(np.float32)


#: Le nombre de fils qui calculent les voix d'une écoute. Mesuré sur la
#: machine de l'utilisateur (24 cœurs, 5 novembre 2026) : 3 ou 4 fils
#: rendent une section 1,7 fois plus vite qu'un seul, 6 ou 8 moins bien que
#: 4 — la part de Python de chaque voix ne se partage pas, et les fils s'y
#: attendent ; la mémoire fraîche des tableaux neufs non plus.
WORKERS = max(1, min(4, (os.cpu_count() or 1) - 1))


def _run_all(tasks: list, should_stop=None) -> list | None:
    """Les résultats de ``tasks`` (fonctions sans argument), dans l'ordre ;
    ``None`` si ``should_stop`` devient vrai en route.

    Quand les boucles du traitement du signal sont compilées, elles laissent
    les autres fils calculer pendant qu'elles tournent : les tâches se
    répartissent alors sur :data:`WORKERS` fils. Sans numba, elles se
    suivent dans ce fil-ci — en Python pur, des fils ne calculent pas plus
    vite qu'un seul. ``should_stop`` n'est consulté que d'ici."""
    if should_stop is not None and should_stop():
        return None
    workers = min(WORKERS, len(tasks)) if dsp.compiled() else 1
    if workers <= 1:
        results = []
        for task in tasks:
            if should_stop is not None and should_stop():
                return None
            results.append(task())
        return results
    pool = ThreadPoolExecutor(max_workers=workers,
                              thread_name_prefix="rendu")
    try:
        futures = [pool.submit(task) for task in tasks]
        pending = set(futures)
        while pending:
            _done, pending = wait(pending, timeout=0.05)
            if should_stop is not None and should_stop():
                return None
        return [future.result() for future in futures]
    finally:
        pool.shutdown(wait=True, cancel_futures=True)


def _voice_task(sound: Sound, key: tuple, note: int, count: int,
                gate: float, velocity: float, sd: SDCard | None,
                tempo: float, glide: float):
    """Le calcul d'une voix de :func:`render_parts`, pour :func:`_run_all`.

    Son hasard (phases de départ, gigue du filtre, *random*) lui est propre,
    tiré du son et de la note : il ne dépend plus des voix rendues avant
    elle, qui peuvent donc se calculer en même temps."""
    def task():
        rng = np.random.default_rng((_graine(sound.name), _graine(repr(key))))
        try:
            return _render_voice(sound, note, count, gate, velocity, sd,
                                 tempo, glide, rng)
        except Exception as exc:  # noqa: BLE001
            log.exception("note impossible à rendre : %s", exc)
            return np.zeros((2, count))
    return task


def render_parts(parts: dict, sounds: dict, bpm: float = 120.0,
                 sr: int = 44100, sd: SDCard | None = None,
                 tail: float = 0.8, should_stop=None,
                 normalize: bool = True) -> np.ndarray | None:
    """Rend des parties d'accompagnement, chacune avec son son.

    :param parts: ``{nom: [NoteEvent]}`` (cf. :mod:`delugeapp.core.accomp`),
        positions en pas de double-croche.
    :param sounds: ``{nom: Sound}`` ; une partie sans son est ignorée.
    :param tail: secondes laissées, au moins, à l'extinction de chaque
        note ; un son au release plus long garde le sien
        (:func:`tail_seconds`).
    :param should_stop: consulté pendant le calcul ; vrai, le rendu s'arrête
        et rend ``None``. Avec les vraies durées de release, un rendu peut
        dépasser deux secondes : à la fermeture, le fil doit pouvoir
        s'arrêter au lieu d'être tué en plein calcul.

    Comme sur la machine : un son **mono** ou **legato** coupe sa note
    précédente ; un son qui a un glissé part de la note précédente ; le
    tempo cale LFO et delay synchronisés ; les effets traitent chaque son
    entier, et **une seule réverbération** reçoit les envois de tous, comme
    celle du morceau.

    Une même note de même durée n'est rendue qu'une fois : une basse qui
    martèle la fondamentale coûte une note, pas trente-deux. Les voix
    distinctes se calculent en parallèle (:func:`_run_all`), puis les effets
    de chaque son ; le mélange se fait toujours dans le même ordre, si bien
    qu'un rendu redonne le même son à l'échantillon près.
    ``normalize=False`` laisse la crête telle quelle (:func:`mix` ramène
    le mélange avec la batterie).
    """
    from .accomp import total_steps

    tempo = float(bpm) if bpm and bpm > 0 else 120.0
    step_s = 60.0 / tempo / 4.0
    tails = {name: max(float(tail), tail_seconds(sound))
             for name, sound in (sounds or {}).items() if sound is not None}
    length_s = total_steps(parts) * step_s + max(tails.values(),
                                                  default=float(tail))
    frames = max(1, int(length_s * sr))
    rate = ENGINE_RATE
    n = max(1, int(length_s * rate))
    fade = max(1, int(0.008 * rate))

    # -- le plan : chaque note posée, et la voix distincte qu'elle joue -- #
    plans = []
    jobs: dict[tuple, int] = {}       # voix → nombre d'échantillons
    tasks = []
    for name, events in (parts or {}).items():
        sound = (sounds or {}).get(name)
        if sound is None:
            continue
        mono = sound.polyphonic in ("mono", "legato")
        glides = (sound.polyphonic != "legato"
                  and _display(sound, "portamento", 0.0) > 0)
        ordered = sorted(events, key=lambda e: float(e.start))
        placed = []
        previous = None
        for index, event in enumerate(ordered):
            held = max(0.02, float(event.length) * step_s)
            seconds = held + tails.get(name, float(tail))
            start = int(float(event.start) * step_s * rate)
            if mono and index + 1 < len(ordered):
                # La note suivante vole la voix : la rendre au-delà ne sert
                # à rien.
                following = float(ordered[index + 1].start) * step_s
                seconds = min(seconds, max(held, following
                                           - float(event.start) * step_s)
                              + 0.02)
            glide = 0.0
            if glides and previous is not None:
                glide = float(int(previous.note) - int(event.note))
            key = (int(event.note), round(held, 3), round(seconds, 2),
                   int(event.velocity) // 5, glide)
            voice_key = (name, key)
            count = jobs.get(voice_key)
            if count is None:
                count = jobs[voice_key] = max(1, int(round(seconds * rate)))
                tasks.append(_voice_task(
                    sound, key, int(event.note), count,
                    min(1.0, held / seconds),
                    # ``NoteEvent.velocity`` est un pourcentage : 100 % joue
                    # la vélocité 127.
                    max(1.0, min(100.0, float(event.velocity))) / 100.0,
                    sd, tempo, glide))
            previous = event
            if start >= n:
                continue
            length = count
            if mono and index + 1 < len(ordered):
                # La note suivante vole la voix : relâchement rapide.
                following = int(float(ordered[index + 1].start) * step_s
                                * rate)
                length = max(1, min(length, following - start + fade))
            placed.append((voice_key, start, min(n, start + length)))
        plans.append((name, sound, placed))

    # -- les voix, les plus longues d'abord : elles finissent ensemble -- #
    keys = list(jobs)
    order = sorted(range(len(keys)), key=lambda i: -jobs[keys[i]])
    rendered = _run_all([tasks[i] for i in order], should_stop)
    if rendered is None:
        return None
    voices = {keys[i]: voice for i, voice in zip(order, rendered)}

    # -- chaque son entier dans ses effets ------------------------------ #
    def chain(name, sound, placed):
        def task():
            mixed = np.zeros((2, n))
            for voice_key, start, end in placed:
                voice = voices[voice_key]
                chunk = voice[:, :end - start].copy()
                if end - start < voice.shape[1] and chunk.shape[1] > fade:
                    chunk[:, -fade:] *= np.linspace(1.0, 0.0, fade)[None, :]
                mixed[:, start:end] += chunk
            try:
                return _sound_chain(sound, mixed, tempo, False)
            except Exception as exc:  # noqa: BLE001
                log.exception("effets impossibles pour %s : %s", name, exc)
                return None
        return task

    chained = _run_all([chain(*plan) for plan in plans], should_stop)
    if chained is None:
        return None
    dry_total = np.zeros((2, n))
    send_total = np.zeros(n)
    for result in chained:
        if result is not None:
            dry_total += result[0]
            send_total += result[1]
    mixed = dry_total + dsp.reverb(send_total, PREVIEW_REVERB)
    out = _resampled(dsp.output_stage(mixed).T, frames).astype(np.float32)
    peak = float(np.max(np.abs(out))) if out.size else 0.0
    if normalize and peak > 0.98:
        out *= 0.98 / peak
    return out


def render_kit(kit: Kit, pattern=None, bpm: float = 128, sr: int = 44100,
               sd: SDCard | None = None) -> np.ndarray:
    """Rend un kit, soit rangée par rangée, soit en jouant un motif.

    Sans motif, chaque rangée est déclenchée à la suite, ce qui permet de
    vérifier un kit entier d'une écoute.
    """
    rows = list(kit.rows or [])
    if not rows:
        return np.zeros((int(0.5 * sr), 2), dtype=np.float32)

    if pattern is None:
        step = 0.35
        total = int((step * len(rows) + 1.2) * sr)
        out = np.zeros((total, 2), dtype=np.float32)
        for index, row in enumerate(rows):
            voice = _render_float(row.sound, 60, step + 1.0, sr, 0.5, 0.9,
                                  sd, PREVIEW_BPM)
            start = int(index * step * sr)
            end = min(total, start + voice.shape[0])
            out[start:end] += voice[:end - start]
    else:
        tempo = max(20.0, float(bpm))
        seconds_per_step = (60.0 / tempo) / 4.0     # pas de double-croche
        total = int((pattern.steps * seconds_per_step + 1.5) * sr)
        out = np.zeros((total, 2), dtype=np.float32)
        # Les rangées du kit sont associées aux pistes du motif par leur nom.
        by_name = {row.name.upper(): row for row in rows}
        cache: dict[tuple[str, int], np.ndarray] = {}
        for track, steps in pattern.tracks.items():
            row = by_name.get(track.upper())
            if row is None:
                continue
            for step_item in steps:
                key = (track.upper(), int(step_item.velocity // 16))
                voice = cache.get(key)
                if voice is None:
                    # La vélocité d'un pas est un pourcentage (1 à 100) :
                    # la diviser par 127 faisait sonner un coup plein à 79 %.
                    voice = _render_float(
                        row.sound, 60, 1.2, sr, 0.5,
                        max(0.2, min(1.0, step_item.velocity / 100.0)), sd,
                        tempo)
                    cache[key] = voice
                start = int(float(step_item.pos) * seconds_per_step * sr)
                end = min(total, start + voice.shape[0])
                if end > start:
                    out[start:end] += voice[:end - start]

    # Les rangées passent par l'étage du kit, à son volume.
    out *= kit_gain(kit)
    peak = float(np.max(np.abs(out)))
    if peak > 0.99:
        out *= 0.99 / peak
    return out


# --------------------------------------------------------------------------- #
# Batterie synthétisée
# --------------------------------------------------------------------------- #
#
# Pour écouter un rythme sans carte, ou une piste à laquelle la carte n'a pas
# d'échantillon à offrir : une boîte à rythmes analogique minimale, calculée.
# Chaque voix suit la recette classique des TR : sinus à hauteur tombante
# pour les fûts, bruit filtré pour les cymbales, partiels inharmoniques pour
# le métal. Le but reste de juger un rythme, pas d'imiter une machine.

#: Rôles que la batterie synthétisée sait jouer ; les autres prennent le rim.
SYNTH_DRUM_ROLES = (
    "Kick", "Snare", "Clap", "Rim", "HatC", "HatO", "Crash", "Ride", "China",
    "TomL", "TomM", "TomH", "ConL", "ConM", "ConH", "Cowbell", "Block",
    "Claves", "Shaker", "Tambourine", "Guiro", "Timpany",
)


def _drum_noise(n: int, role: str) -> np.ndarray:
    rng = np.random.default_rng(_graine("batterie " + role))
    return rng.standard_normal(n).astype(np.float32)


def _band(noise: np.ndarray, sr: int, low: float, high: float) -> np.ndarray:
    """Bruit limité à une bande de fréquences, crête ramenée à 1.

    Un masque doux dans le domaine fréquentiel : sur des sons de quelques
    dixièmes de seconde, c'est le filtre le plus simple qui reste juste.
    """
    spectrum = np.fft.rfft(noise)
    freqs = np.fft.rfftfreq(noise.shape[0], 1.0 / sr)
    mask = (1.0 / (1.0 + (low / np.maximum(freqs, 1.0)) ** 4)
            / (1.0 + (freqs / high) ** 4))
    out = np.fft.irfft(spectrum * mask, n=noise.shape[0])
    peak = float(np.max(np.abs(out))) or 1.0
    return (out / peak).astype(np.float32)


@lru_cache(maxsize=256)
def _synth_drum_mono(role: str, sr: int, level: int) -> np.ndarray:
    velocity = level / 20.0
    lengths = {"Kick": 0.5, "Snare": 0.3, "Clap": 0.35, "Rim": 0.08,
               "HatC": 0.09, "HatO": 0.45, "Crash": 1.6, "Ride": 1.2,
               "China": 1.4, "Shaker": 0.14, "Tambourine": 0.25,
               "Guiro": 0.3, "Cowbell": 0.3, "Block": 0.1, "Claves": 0.1,
               "Timpany": 0.9}
    seconds = lengths.get(role, 0.45)
    n = max(1, int(seconds * sr))
    t = np.arange(n, dtype=np.float32) / float(sr)

    def sweep(start_hz: float, end_hz: float, speed: float) -> np.ndarray:
        freq = end_hz + (start_hz - end_hz) * np.exp(-t * speed)
        return np.sin(2 * np.pi * np.cumsum(freq) / sr).astype(np.float32)

    def partials(freqs, decay: float) -> np.ndarray:
        tone = sum(np.sign(np.sin(2 * np.pi * f * t)) for f in freqs)
        return (tone / len(freqs) * np.exp(-t * decay)).astype(np.float32)

    noise = _drum_noise(n, role)

    def bright(low: float, high: float) -> np.ndarray:
        return _band(noise, sr, low, high)

    if role == "Kick":
        voice = sweep(160.0, 46.0, 28.0) * np.exp(-t * 6.5)
        # L'attaque : un clic bref, qui fait entendre la frappe.
        voice += 0.12 * bright(1500.0, 6000.0) * np.exp(-t * 300.0)
    elif role == "Snare":
        voice = (0.6 * bright(1200.0, 7000.0) * np.exp(-t * 16.0)
                 + 0.55 * sweep(220.0, 180.0, 40.0) * np.exp(-t * 24.0))
    elif role == "Clap":
        env = np.zeros(n, dtype=np.float32)
        for offset in (0.0, 0.011, 0.022):
            start = int(offset * sr)
            env[start:] += np.exp(-(t[: n - start]) * 70.0)
        env += 0.6 * np.exp(-np.maximum(t - 0.03, 0) * 12.0) * (t > 0.03)
        voice = bright(900.0, 3500.0) * env * 0.6
    elif role in ("HatC", "HatO", "Shaker"):
        decay = {"HatC": 55.0, "HatO": 8.0, "Shaker": 28.0}[role]
        attack = 1.0 - np.exp(-t * (400.0 if role != "Shaker" else 90.0))
        band = (7000.0, 14000.0) if role != "Shaker" else (4000.0, 11000.0)
        voice = bright(*band) * np.exp(-t * decay) * attack * 0.7
    elif role in ("Crash", "China", "Ride"):
        metal = partials((3150.0, 4540.0, 5950.0, 7340.0) if role != "Ride"
                         else (2900.0, 3720.0, 5110.0), 3.0)
        wash = bright(4000.0, 13000.0) * np.exp(-t * (2.5 if role != "Ride"
                                                       else 4.0))
        voice = 0.35 * metal + 0.55 * wash
    elif role == "Tambourine":
        voice = (0.5 * bright(5000.0, 12000.0) * np.exp(-t * 14.0)
                 + 0.3 * partials((6200.0, 7700.0), 18.0))
    elif role == "Guiro":
        scrape = (np.sin(2 * np.pi * 45.0 * t) > 0).astype(np.float32)
        voice = bright(2000.0, 6000.0) * scrape * np.exp(-t * 8.0) * 0.5
    elif role == "Cowbell":
        voice = partials((540.0, 800.0), 11.0) * 0.6
    elif role in ("Block", "Claves"):
        freq = 1000.0 if role == "Block" else 2500.0
        voice = np.sin(2 * np.pi * freq * t) * np.exp(-t * 55.0)
    elif role in ("TomL", "TomM", "TomH", "ConL", "ConM", "ConH",
                  "Timpany"):
        base = {"TomL": 95.0, "TomM": 135.0, "TomH": 185.0, "ConL": 210.0,
                "ConM": 290.0, "ConH": 370.0, "Timpany": 75.0}[role]
        decay = 7.0 if role.startswith("Tom") or role == "Timpany" else 15.0
        voice = sweep(base * 1.35, base, 18.0) * np.exp(-t * decay)
    else:                                                   # Rim
        voice = (np.sin(2 * np.pi * 1700.0 * t) * 0.6
                 + np.sin(2 * np.pi * 620.0 * t) * 0.5) * np.exp(-t * 110.0)
    voice = np.asarray(voice, dtype=np.float32)
    peak = float(np.max(np.abs(voice))) or 1.0
    voice = voice * (0.9 / peak) * (0.35 + 0.65 * velocity)
    fade = min(n, max(1, int(0.004 * sr)))
    voice[-fade:] *= np.linspace(1.0, 0.0, fade, dtype=np.float32)
    voice.flags.writeable = False
    return voice


def synth_drum(role: str, sr: int = 44100, velocity: float = 1.0
               ) -> np.ndarray:
    """Un coup de batterie synthétisé, en stéréo, prêt à mixer."""
    name = role if role in SYNTH_DRUM_ROLES else "Rim"
    level = int(round(max(0.0, min(1.0, float(velocity))) * 20))
    mono = _synth_drum_mono(name, int(sr), level)
    return np.repeat(mono[:, None], 2, axis=1)


def render_pattern(pattern, bpm: float = 120.0, sr: int = 44100,
                   kit: Kit | None = None, sd: SDCard | None = None,
                   bars: int | None = None, tail: float = 0.8,
                   normalize: bool = True) -> np.ndarray:
    """Rend un motif rythmique, bouclé sur ``bars`` mesures.

    Chaque piste est jouée par la rangée du kit qui porte son nom — un
    échantillon de la carte, au niveau de la machine, étage du kit compris —
    ou, à défaut, par la batterie synthétisée : une piste euclidienne ou un
    rôle sans échantillon sonne quand même. ``normalize=False`` laisse la
    crête telle quelle, pour un mélange ramené une seule fois (:func:`mix`).
    """
    steps_total = int(pattern.steps)
    loops = 1
    if bars:
        loops = max(1, int(np.ceil(bars * 16 / max(1, steps_total))))
        steps_total = int(bars * 16)
    tempo = max(20.0, float(bpm))
    step_s = 60.0 / tempo / 4.0
    n = max(1, int((steps_total * step_s + tail) * sr))
    out = np.zeros((n, 2), dtype=np.float32)
    rows = {row.name.upper(): row for row in (kit.rows if kit else [])}
    cache: dict[tuple[str, int], np.ndarray] = {}
    for track, steps in pattern.tracks.items():
        row = rows.get(track.upper())
        for step in steps:
            level = int(max(1, min(100, step.velocity)) // 5)
            key = (track, level)
            voice = cache.get(key)
            if voice is None:
                if row is not None:
                    voice = _render_float(row.sound, 60, 1.2, sr, 0.5,
                                          max(0.2, level / 20.0), sd,
                                          tempo) * kit_gain(kit)
                else:
                    voice = synth_drum(track, sr, level / 20.0)
                cache[key] = voice
            for loop in range(loops):
                position = float(step.pos) + loop * pattern.steps
                if position >= steps_total:
                    break
                start = int(position * step_s * sr)
                end = min(n, start + voice.shape[0])
                if end > start:
                    out[start:end] += voice[:end - start]
    peak = float(np.max(np.abs(out))) if out.size else 0.0
    if normalize and peak > 0.98:
        out *= 0.98 / peak
    return out


def mix(*tracks: np.ndarray, levels: tuple[float, ...] | None = None
        ) -> np.ndarray:
    """Additionne des rendus stéréo de longueurs différentes, sans saturer."""
    tracks = tuple(t for t in tracks if t is not None and t.size)
    if not tracks:
        return np.zeros((1, 2), dtype=np.float32)
    n = max(t.shape[0] for t in tracks)
    out = np.zeros((n, 2), dtype=np.float32)
    for index, track in enumerate(tracks):
        gain = levels[index] if levels and index < len(levels) else 1.0
        out[: track.shape[0]] += track * gain
    peak = float(np.max(np.abs(out)))
    if peak > 0.98:
        out *= 0.98 / peak
    return out


def spectrum(data: np.ndarray, sr: int,
             n: int = 4096) -> tuple[np.ndarray, np.ndarray]:
    """``(fréquences, amplitudes en dB)`` du signal, pour l'affichage.

    Moyenne des spectres de plusieurs fenêtres, ce qui donne une courbe
    lisible plutôt que l'instantané bruité d'une seule transformée.
    """
    arr = np.asarray(data, dtype=np.float32)
    if arr.ndim > 1:
        arr = arr.mean(axis=1)
    size = max(64, int(n))
    if arr.size < size:
        padded = np.zeros(size, dtype=np.float32)
        padded[:arr.size] = arr
        arr = padded

    window = np.hanning(size).astype(np.float32)
    hop = size // 2
    frames = []
    for start in range(0, arr.size - size + 1, hop):
        frames.append(np.abs(np.fft.rfft(arr[start:start + size] * window)))
        if len(frames) >= 64:
            break
    if not frames:
        frames = [np.abs(np.fft.rfft(arr[:size] * window))]

    magnitude = np.mean(np.asarray(frames), axis=0)
    freqs = np.fft.rfftfreq(size, 1.0 / max(1, int(sr)))
    reference = float(np.max(magnitude)) or 1.0
    db = 20.0 * np.log10(np.maximum(magnitude / reference, 1e-6))
    return freqs.astype(np.float32), db.astype(np.float32)
