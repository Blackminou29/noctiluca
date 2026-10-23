# -*- coding: utf-8 -*-
"""Moteur d'écoute hors-ligne : entendre un preset sans passer par le Deluge.

Le but est de **juger un son**, pas de simuler la machine. Un preset généré
doit pouvoir être écouté dans l'application avant d'être écrit sur la carte :
la question à laquelle ce module répond est « est-ce que cette basse est
grasse ? », pas « est-ce exactement ce que sortirait le Deluge ? ».

La SPEC §4.21 fixe la qualité attendue — « plausible, pas exact » — et un
budget de **400 ms pour 2,5 secondes**. Trois choix techniques en découlent :

* **tables d'onde à bandes limitées**, découpées par octave, lues par
  interpolation linéaire. Produire les formes d'onde par addition
  d'harmoniques serait plus juste mais coûterait dix fois plus cher pour
  12 voix d'unisson ;
* **filtre appliqué par blocs dans le domaine fréquentiel**, avec recouvrement
  de moitié. Une récursion échantillon par échantillon en Python coûterait à
  elle seule tout le budget ; ici un balayage de filtre complet prend 10 ms ;
* **réverbération par convolution FFT** d'une réponse impulsionnelle
  synthétique, soit 9 ms au lieu d'un réseau de retards bouclés.

**Les réglages suivent les lois du firmware** (:mod:`.paramlaws`) : durées
d'enveloppe et leurs courbes, coupures, vitesses des LFO, lois de volume,
désaccord d'unisson, glissé, et la manière dont un câble s'ajoute — sources
bipolaires, force au carré vers une hauteur, *random* tiré une fois par note.
Jusqu'au 22 octobre 2026, ces lois étaient estimées, et l'utilisateur
entendait ses sons de l'atelier « sans rapport » avec le Deluge : un decay de
13 durait 36 ms au lieu de 1,8 s, un vibrato léger balançait d'un
demi-ton. Ce qui reste approché, c'est le traitement du signal : formes
d'onde, filtre à résonance (le facteur de qualité d'un filtre à deux pôles
pour une échelle à transistors), effets.

Ne dépend que de numpy.
"""

from __future__ import annotations

import logging
import zlib
from functools import lru_cache

import numpy as np

from . import paramlaws as laws
from .fixedpoint import to_display
from .model import Kit, Sound, SynthPreset, param_of_destination
from .sdcard import SDCard

log = logging.getLogger(__name__)

#: Taille des tables d'onde.
TABLE_SIZE = 2048

#: Taille des blocs de filtrage, et recouvrement.
FILTER_BLOCK = 1024

#: Marge de sortie : la même pour tous les sons, pour que les lois de
#: volume gardent leurs rapports (un son au réglage 50 partout, joué
#: fort, frôle la pleine échelle).
OUTPUT_HEADROOM = 0.07

#: Durée maximale laissée à l'extinction d'une note : un release de 50 dure
#: 27 s sur la machine, l'écoute s'arrête avant.
MAX_TAIL_S = 4.0

#: Destinations de modulation entendues par le rendu. Les autres sont
#: ignorées avec une trace : le Deluge en accepte une cinquantaine.
KNOWN_DESTINATIONS = (
    "lpfFrequency", "lpfResonance", "hpfFrequency", "pitch", "volume",
    "oscAVolume", "oscBVolume", "oscAPitch", "oscBPitch", "oscAPulseWidth",
    "oscBPulseWidth", "noiseVolume", "modFXDepth", "modFXRate",
    "reverbAmount", "delayFeedback", "pan", "lfo1Rate", "lfo2Rate",
    "modulator1Amount", "modulator2Amount", "modulator1Pitch",
    "modulator2Pitch", "env1Attack", "env1Decay", "env1Sustain",
    "env1Release", "env2Attack", "env2Decay", "env2Sustain", "env2Release",
)

#: Tempo supposé pour l'aperçu d'un LFO synchronisé : un preset n'a pas de
#: tempo, c'est le morceau qui le donne.
PREVIEW_BPM = 120.0


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


def _q_of(resonance) -> np.ndarray:
    """Facteur de qualité d'un filtre à deux pôles, depuis la résonance
    traitée du firmware (0..1, :func:`.paramlaws.ladder_resonance`).

    **Approché** : l'échelle à transistors n'est pas un filtre à deux pôles.
    0,707 sans résonance, environ 2 au réglage 25, près de 5 en butée.
    """
    r = np.clip(np.asarray(resonance, dtype=np.float64), 0.0, 1.0)
    return 0.707 / (1.0 - 0.85 * r)


def _resonance_q(unit: float) -> float:
    """Facteur de qualité depuis le réglage de résonance ramené à 0..1."""
    return float(_q_of(laws.ladder_resonance(1.0 + laws.unit(
        float(unit) * 50.0))))


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


def _env_times(sound: Sound, env, index: int, static: _Patch
               ) -> tuple[float, float, float, float]:
    """``(attaque, decay, sustain, release)`` d'une enveloppe, en secondes
    et en niveau, selon le firmware ; ``static`` : les câbles des sources
    constantes de la note (vélocité, note, *random*)."""
    prefix = "env%d" % index
    attack = float(laws.attack_seconds(
        6.0 * laws.raw_unit(env.attack)
        + np.mean(static.oct(prefix + "Attack"))))
    decay = float(laws.decay_seconds(
        laws.raw_unit(env.decay) + np.mean(static.add(prefix + "Decay"))))
    sustain = float(laws.sustain_level(
        (1.0 + laws.raw_unit(env.sustain))
        * np.mean(static.factor(prefix + "Sustain"))))
    release = float(laws.release_seconds(
        laws.raw_unit(env.release) + np.mean(static.add(prefix + "Release"))))
    return attack, decay, sustain, release


# --------------------------------------------------------------------------- #
# Tables d'onde
# --------------------------------------------------------------------------- #

@lru_cache(maxsize=256)
def _wavetable(kind: str, band: int) -> np.ndarray:
    """Une période d'onde, limitée aux harmoniques audibles de cette octave.

    ``band`` est l'octave de la note jouée : plus elle est haute, moins
    d'harmoniques tiennent sous la fréquence de Nyquist. Construire une table
    par octave évite le repliement sans coûter un calcul par échantillon.
    """
    harmonics = max(1, min(512, int(2 ** (10 - band))))
    phase = np.linspace(0.0, 2.0 * np.pi, TABLE_SIZE, endpoint=False,
                        dtype=np.float64)
    out = np.zeros(TABLE_SIZE, dtype=np.float64)

    if kind in ("sine",):
        out = np.sin(phase)
    elif kind in ("saw", "analogSaw"):
        for h in range(1, harmonics + 1):
            out -= np.sin(h * phase) / h
        out *= 2.0 / np.pi
    elif kind in ("square", "analogSquare"):
        for h in range(1, harmonics + 1, 2):
            out += np.sin(h * phase) / h
        out *= 4.0 / np.pi
    elif kind == "triangle":
        for i, h in enumerate(range(1, harmonics + 1, 2)):
            out += ((-1) ** i) * np.sin(h * phase) / (h * h)
        out *= 8.0 / (np.pi ** 2)
    else:
        # Forme inconnue : une dent de scie reste le choix le moins surprenant.
        for h in range(1, harmonics + 1):
            out -= np.sin(h * phase) / h
        out *= 2.0 / np.pi

    peak = float(np.max(np.abs(out)))
    if peak > 0:
        out /= peak
    # Une valeur de bouclage en fin de table : l'interpolation ne doit pas
    # retomber à zéro entre le dernier point et le premier.
    return np.append(out, out[0]).astype(np.float32)


def _read_table(kind: str, phase_cycles: np.ndarray, freq_hz: float) -> np.ndarray:
    """Lit une table d'onde à la phase donnée, en cycles."""
    if kind == "sine":
        return np.sin(2.0 * np.pi * phase_cycles, dtype=np.float32)
    band = int(max(0, min(10, np.log2(max(freq_hz, 20.0) / 20.0))))
    table = _wavetable(kind, band)
    index = (phase_cycles % 1.0) * TABLE_SIZE
    return np.interp(index, _TABLE_INDEX, table).astype(np.float32)


#: Abscisses de l'interpolation, calculées une seule fois.
_TABLE_INDEX = np.arange(TABLE_SIZE + 1, dtype=np.float32)


# --------------------------------------------------------------------------- #
# Enveloppes et LFO
# --------------------------------------------------------------------------- #

def _adsr(n: int, sr: int, attack: float, decay: float, sustain: float,
          release: float, gate: float) -> np.ndarray:
    """Enveloppe échantillonnée, comme ``Envelope::render`` du firmware.

    Attaque en ``1 − decayTableSmall4`` (montée bombée) — sautée quand le
    firmware la juge instantanée ; decay en ``decayTableSmall8`` vers le
    palier ; release en ``decayTableSmall8`` depuis le niveau atteint au
    relâchement. ``attack``, ``decay`` et ``release`` sont les durées
    **complètes** des étapes (:mod:`.paramlaws`). Un palier nul éteint
    l'enveloppe à la fin du decay.

    ``gate`` est la fraction de la durée pendant laquelle la touche est
    tenue ; le relâchement part du niveau atteint à cet instant, et non du
    palier théorique, sinon une note relâchée pendant son attaque produit un
    saut de niveau.
    """
    out = np.zeros(n, dtype=np.float32)
    if n <= 0:
        return out
    gate_samples = max(1, min(n, int(n * max(0.01, min(1.0, gate)))))
    t = np.arange(gate_samples, dtype=np.float64) / float(sr)
    held = np.empty(gate_samples, dtype=np.float64)

    a = max(0.0, float(attack))
    d = max(1.0 / sr, float(decay))
    s = max(0.0, min(1.0, float(sustain)))
    in_attack = t < a if a > 0 else np.zeros(gate_samples, dtype=bool)
    if a > 0:
        held[in_attack] = laws.attack_curve(t[in_attack] / a)
    after = ~in_attack
    td = t[after] - a
    held[after] = np.where(td < d, s + (1.0 - s) * laws.decay_curve(td / d),
                           s)
    out[:gate_samples] = held

    level = float(out[gate_samples - 1])
    tail = n - gate_samples
    if tail > 0:
        r = max(1.0 / sr, float(release))
        tr = np.arange(tail, dtype=np.float64) / float(sr)
        out[gate_samples:] = level * np.where(tr < r,
                                              laws.decay_curve(tr / r), 0.0)
    return out


def _lfo(n: int, sr: int, kind: str, rate_hz: float,
         rng: np.random.Generator) -> np.ndarray:
    """LFO bipolaire dans [-1, 1]."""
    if n <= 0:
        return np.zeros(0, dtype=np.float32)
    t = np.arange(n, dtype=np.float32) / sr
    phase = rate_hz * t

    if kind == "sine":
        return np.sin(2.0 * np.pi * phase, dtype=np.float32)
    if kind == "triangle":
        return (2.0 * np.abs(2.0 * (phase % 1.0) - 1.0) - 1.0).astype(np.float32)
    if kind == "square":
        return np.where((phase % 1.0) < 0.5, 1.0, -1.0).astype(np.float32)
    if kind == "saw":
        return (2.0 * (phase % 1.0) - 1.0).astype(np.float32)
    if kind == "sah":
        steps = max(1, int(rate_hz * n / sr))
        values = rng.uniform(-1.0, 1.0, steps + 1).astype(np.float32)
        return values[np.minimum((phase % steps).astype(np.int64)
                                 if steps > 1 else np.zeros(n, dtype=np.int64),
                                 steps)]
    if kind == "rwalk":
        steps = max(2, int(rate_hz * n / sr) + 1)
        knots = np.cumsum(rng.uniform(-0.4, 0.4, steps)).astype(np.float32)
        peak = float(np.max(np.abs(knots))) or 1.0
        knots /= peak
        return np.interp(np.linspace(0, steps - 1, n),
                         np.arange(steps), knots).astype(np.float32)
    return np.zeros(n, dtype=np.float32)


# --------------------------------------------------------------------------- #
# Modulations
# --------------------------------------------------------------------------- #

def _series(value, n: int) -> np.ndarray:
    """Un scalaire ou un tableau, étendu à ``n`` échantillons (float32)."""
    arr = np.asarray(value, dtype=np.float32)
    if arr.ndim == 0:
        return np.full(n, float(arr), dtype=np.float32)
    return arr[:n].astype(np.float32)


def _volume(sound: Sound, name: str, patch: _Patch, n: int,
            default: float = 25.0) -> np.ndarray:
    """Gain d'un paramètre de volume, relatif au réglage 25 (loi du
    firmware : ``(1 + u)·Π(1 + v·a)`` élevé au carré)."""
    factor = (1.0 + _u(sound, name, default)) \
        * np.asarray(patch.factor(name), dtype=np.float64)
    return _series(laws.volume_gain(factor), n)


def _linear(sound: Sound, name: str, patch: _Patch, n: int,
            default: float = 25.0) -> np.ndarray:
    """Facteur d'un paramètre linéaire, relatif au réglage 25 (0 à 2)."""
    factor = (1.0 + _u(sound, name, default)) \
        * np.asarray(patch.factor(name), dtype=np.float64)
    return _series(laws.linear_level(factor), n)


def _octaves(sound: Sound, name: str, patch: _Patch, n: int,
             default: float = 25.0) -> np.ndarray:
    """Décalage en octaves d'un paramètre exponentiel : réglage et câbles."""
    return _series(laws.exp_range(name) * _u(sound, name, default)
                   + np.asarray(patch.oct(name), dtype=np.float64), n)


def _hybrid(sound: Sound, name: str, patch: _Patch, n: int,
            default: float = 25.0) -> np.ndarray:
    """Valeur −1..+1 d'un paramètre hybride (largeur, panoramique)."""
    return _series(np.clip(_u(sound, name, default)
                           + np.asarray(patch.add(name), dtype=np.float64),
                           -1.0, 1.0), n)


# --------------------------------------------------------------------------- #
# Filtres
# --------------------------------------------------------------------------- #

def _response(freqs: np.ndarray, cutoff_hz: float, q: float, poles: int,
              high_pass: bool = False) -> np.ndarray:
    """Réponse en fréquence d'un filtre résonant à 2 ou 4 pôles."""
    w = freqs / max(cutoff_hz, 10.0)
    denominator = (1.0 - w * w) + 1j * w / max(q, 0.05)
    # Éviter la division par zéro exactement à la résonance.
    denominator[np.abs(denominator) < 1e-9] = 1e-9
    response = (-(w * w) if high_pass else 1.0) / denominator
    if poles >= 4:
        response = response * response
    return response


def _filter_sweep(signal: np.ndarray, sr: int, cutoff_hz: np.ndarray,
                  q: np.ndarray, poles: int,
                  high_pass: bool = False) -> np.ndarray:
    """Filtre à coupure variable, par blocs dans le domaine fréquentiel.

    Chaque bloc est fenêtré en Hann avec recouvrement de moitié, filtré avec
    la coupure moyenne du bloc, puis réaccumulé. C'est ce qui permet de tenir
    le budget de temps : une récursion par échantillon en Python coûterait à
    elle seule plus que les 400 ms allouées à tout le rendu.
    """
    n = signal.size
    if n == 0:
        return signal
    block = min(FILTER_BLOCK, max(64, 1 << int(np.log2(max(n, 64)))))
    hop = block // 2
    window = np.hanning(block).astype(np.float32)
    freqs = np.fft.rfftfreq(block, 1.0 / sr)

    padded = np.zeros(n + 2 * block, dtype=np.float32)
    padded[block:block + n] = signal
    out = np.zeros_like(padded)

    for start in range(0, n + block, hop):
        chunk = padded[start:start + block]
        if chunk.size < block:
            break
        centre = min(n - 1, max(0, start - block + hop))
        response = _response(freqs, float(cutoff_hz[centre]),
                             float(q[centre]), poles, high_pass)
        filtered = np.fft.irfft(np.fft.rfft(chunk * window) * response, block)
        out[start:start + block] += filtered.astype(np.float32)

    # La fenêtre de Hann à recouvrement de moitié somme à 1.
    return out[block:block + n]


# --------------------------------------------------------------------------- #
# Effets
# --------------------------------------------------------------------------- #

def _saturate(signal: np.ndarray, amount: float) -> np.ndarray:
    """Distorsion douce par tangente hyperbolique."""
    if amount <= 0:
        return signal
    drive = 1.0 + amount * 12.0
    return (np.tanh(signal * drive) / np.tanh(drive)).astype(np.float32)


def _bitcrush(signal: np.ndarray, amount: float) -> np.ndarray:
    """Réduction de résolution : de 16 bits à 2 bits."""
    if amount <= 0.01:
        return signal
    bits = max(2.0, 16.0 - amount * 14.0)
    levels = 2.0 ** bits
    return (np.round(signal * levels) / levels).astype(np.float32)


def _decimate(signal: np.ndarray, amount: float) -> np.ndarray:
    """Réduction de fréquence d'échantillonnage par maintien de valeur."""
    if amount <= 0.01:
        return signal
    factor = max(1, int(1 + amount * 31))
    if factor <= 1:
        return signal
    held = signal[::factor]
    return np.repeat(held, factor)[:signal.size].astype(np.float32)


def _delay(signal: np.ndarray, sr: int, time_s: float, feedback: float,
           mix: float) -> np.ndarray:
    """Délai à répétitions, par sommation de copies décalées.

    Additionner quelques copies atténuées coûte beaucoup moins qu'une boucle
    de rétroaction échantillon par échantillon, pour un résultat
    indiscernable à l'écoute.
    """
    if mix <= 0.01 or time_s <= 0:
        return signal
    offset = max(1, int(time_s * sr))
    out = signal.copy()
    level = mix
    position = offset
    repeats = 0
    while level > 0.01 and position < signal.size and repeats < 12:
        out[position:] += signal[:signal.size - position] * level
        level *= max(0.0, min(0.95, feedback))
        position += offset
        repeats += 1
    return out.astype(np.float32)


@lru_cache(maxsize=16)
def _reverb_ir(sr: int, seconds: float, bright: float) -> np.ndarray:
    """Réponse impulsionnelle synthétique : bruit décroissant filtré."""
    length = max(16, int(seconds * sr))
    rng = np.random.default_rng(12345)
    noise = rng.standard_normal(length).astype(np.float32)
    decay = np.exp(-np.linspace(0.0, 7.0, length, dtype=np.float32))
    ir = noise * decay
    # Un lissage simple assombrit la queue, comme une vraie pièce.
    taps = max(2, int((1.0 - bright) * 48) + 2)
    kernel = np.ones(taps, dtype=np.float32) / taps
    ir = np.convolve(ir, kernel, mode="same")
    peak = float(np.max(np.abs(ir))) or 1.0
    return (ir / peak).astype(np.float32)


def _reverb(signal: np.ndarray, sr: int, amount: float,
            size: float = 0.6) -> np.ndarray:
    """Réverbération par convolution FFT."""
    if amount <= 0.01:
        return signal
    ir = _reverb_ir(sr, 0.4 + size * 2.0, 0.5)
    length = 1 << int(np.ceil(np.log2(signal.size + ir.size)))
    wet = np.fft.irfft(np.fft.rfft(signal, length)
                       * np.fft.rfft(ir, length), length)[:signal.size]
    peak = float(np.max(np.abs(wet))) or 1.0
    wet = (wet / peak * float(np.max(np.abs(signal)) or 1.0)).astype(np.float32)
    return ((1.0 - amount * 0.5) * signal + amount * 0.7 * wet).astype(np.float32)


def _mod_fx(signal: np.ndarray, sr: int, kind: str, depth: float,
            rate_hz: float) -> np.ndarray:
    """Chorus, flanger ou phaser : un délai court modulé."""
    if kind in ("", "none") or depth <= 0.01:
        return signal
    base_ms = {"flanger": 2.0, "chorus": 14.0, "StereoChorus": 18.0,
               "phaser": 6.0, "TapeWarble": 24.0, "grainFX": 30.0, "dimension": 10.0}.get(kind, 14.0)
    sweep_ms = base_ms * depth * 0.8
    n = signal.size
    t = np.arange(n, dtype=np.float32) / sr
    offset = (base_ms + sweep_ms * np.sin(2.0 * np.pi * rate_hz * t)) * sr / 1000.0
    index = np.arange(n, dtype=np.float32) - offset
    np.clip(index, 0, n - 1, out=index)
    delayed = np.interp(index, np.arange(n, dtype=np.float32),
                        signal).astype(np.float32)
    sign = -1.0 if kind == "phaser" else 1.0
    return (0.65 * signal + sign * 0.55 * depth * delayed).astype(np.float32)


# --------------------------------------------------------------------------- #
# Rendu d'un son
# --------------------------------------------------------------------------- #

def _sample_voice(sound: Sound, osc, note: int, n: int, sr: int,
                  sd: SDCard | None) -> np.ndarray | None:
    """Lit un échantillon de la carte et le transpose à la note demandée."""
    if sd is None or not osc.file_name:
        return None
    from . import wav

    path = sd.resolve_sample(osc.file_name)
    if path is None:
        log.debug("échantillon introuvable pour le rendu : %s", osc.file_name)
        return None
    try:
        data, file_sr = wav.read(path, mono=True, max_frames=sr * 12)
    except Exception as exc:  # noqa: BLE001
        log.debug("échantillon illisible %s : %s", path, exc)
        return None
    if data.size == 0:
        return None

    # Transposition : l'échantillon est supposé enregistré en do médian, à
    # défaut d'information de note de référence.
    semis = (note - 60) + osc.transpose + osc.cents / 100.0
    ratio = (2.0 ** (semis / 12.0)) * (file_sr / float(sr))
    length = int(data.size / max(ratio, 1e-6))
    if length <= 1:
        return None
    index = np.arange(min(length, n), dtype=np.float32) * ratio
    np.clip(index, 0, data.size - 1, out=index)
    voice = np.interp(index, np.arange(data.size, dtype=np.float32),
                      data).astype(np.float32)
    out = np.zeros(n, dtype=np.float32)
    out[:voice.size] = voice
    if osc.reversed:
        out = out[::-1].copy()
    return out


def _oscillator(sound: Sound, osc, which: str, note: int, n: int, sr: int,
                pitch_mod: np.ndarray, pw_unit: np.ndarray,
                sd: SDCard | None, rng: np.random.Generator) -> np.ndarray:
    """Un oscillateur, unisson compris."""
    if osc.type in ("sample", "wavetable"):
        voice = _sample_voice(sound, osc, note, n, sr, sd)
        if voice is not None:
            return voice
        # Sans fichier, on retombe sur une onde : mieux vaut un son approché
        # que le silence, puisque le but est de juger le preset.
        kind = "saw"
    elif osc.type in ("inLeft", "inRight", "dx7"):
        kind = "sine"
    else:
        kind = osc.type

    semis = osc.transpose + osc.cents / 100.0 + sound.transpose
    base_hz = 440.0 * 2.0 ** ((note + semis - 69) / 12.0)
    base_hz = float(np.clip(base_hz, 8.0, sr * 0.45))

    voices = max(1, min(8, sound.unison_num))
    # ±désaccord/2 cents, réparti également (le firmware) ; c'était
    # ±désaccord × 2 : quatre fois trop large.
    cents = laws.unison_cents(sound.unison_detune, voices)
    out = np.zeros(n, dtype=np.float32)

    for v in range(voices):
        freq = base_hz * 2.0 ** (cents[v] / 1200.0)
        instant = freq * (2.0 ** (pitch_mod / 12.0))
        phase = np.cumsum(instant / sr, dtype=np.float32)
        # Phase de départ décalée : sans cela, les voix d'unisson s'ajoutent
        # en phase et produisent un transitoire de niveau anormal.
        phase += rng.uniform(0.0, 1.0)
        wave = _read_table(kind, phase, freq)

        if kind in ("square", "analogSquare"):
            # Largeur d'impulsion : on soustrait une copie décalée.
            width = np.clip(pw_unit, 0.02, 0.98)
            shifted = _read_table(kind, phase + width, freq)
            wave = (wave - shifted) * 0.5
        out += wave

    out /= float(voices)
    return out

def _fm_voice(sound: Sound, note: int, n: int, rate: int,
              pitch_mod: np.ndarray, mod: _Patch, level_a: np.ndarray,
              level_b: np.ndarray) -> np.ndarray:
    """Le moteur FM du Deluge : deux porteuses, deux modulateurs.

    Les porteuses sont des sinusoïdes accordées comme les oscillateurs A et
    B ; chaque modulateur, accordé à part (``<modulator1>``,
    ``<modulator2>``), module la phase de sa porteuse — ou, si
    ``toModulator1`` est posé, celle du premier modulateur. C'est l'accord
    des modulateurs qui fait le timbre : l'ancien rendu modulait avec
    l'oscillateur B et rendait tous les presets FM semblables.
    """
    vib = (2.0 ** (pitch_mod / 12.0)).astype(np.float32)

    def _phase(semis: float) -> np.ndarray:
        hz = 440.0 * 2.0 ** ((note + sound.transpose + semis - 69) / 12.0)
        hz = float(np.clip(hz, 1.0, rate * 0.45))
        return np.cumsum(hz * vib / rate, dtype=np.float64)

    two_pi = 2.0 * np.pi
    m1 = getattr(sound, "modulator1", None)
    m2 = getattr(sound, "modulator2", None)
    m1_semis = (m1.transpose + m1.cents / 100.0) if m1 else 0.0
    m2_semis = (m2.transpose + m2.cents / 100.0) if m2 else -12.0
    to_m1 = bool(m2 and m2.to_modulator1)

    # Indice de modulation : jusqu'à ~6 radians à fond, ce qui va du timbre
    # doux au métal sans tomber dans le bruit. Le niveau d'un modulateur
    # suit la loi de volume du firmware (quadratique) : 1,5 rad au réglage
    # 25, 6 en butée.
    depth1 = _volume(sound, "modulator1Amount", mod, n, 0.0) * 1.5
    depth2 = _volume(sound, "modulator2Amount", mod, n, 0.0) * 1.5

    m2_out = np.sin(two_pi * _phase(m2_semis)).astype(np.float32)
    m1_out = np.sin(two_pi * _phase(m1_semis)
                    + (m2_out * depth2 if to_m1 else 0.0)).astype(np.float32)
    c1 = np.sin(two_pi * _phase(sound.osc1.transpose
                                + sound.osc1.cents / 100.0)
                + m1_out * depth1).astype(np.float32)
    c2 = np.sin(two_pi * _phase(sound.osc2.transpose
                                + sound.osc2.cents / 100.0)
                + (0.0 if to_m1 else m2_out * depth2)).astype(np.float32)
    return (c1 * level_a + c2 * level_b).astype(np.float32)


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




def _effects(sound: Sound, mixed: np.ndarray, rate: int, mod: _Patch,
             bpm: float) -> np.ndarray:
    """Mod FX, delay et réverbération d'un son, sur un signal mono."""
    n = mixed.size
    mod_rate = float(laws.lfo_hz(np.mean(
        _octaves(sound, "modFXRate", mod, n))))
    mod_depth = float(np.mean(_volume(sound, "modFXDepth", mod, n,
                                      0.0))) / 4.0
    mixed = _mod_fx(mixed, rate, sound.mod_fx_type, mod_depth, mod_rate)

    delay_fb = float(np.mean(_linear(sound, "delayFeedback", mod, n,
                                     0.0))) * 0.5
    if delay_fb > 0.02:
        level = int(getattr(sound, "delay_sync_level", 0) or 0)
        if level > 0:
            hz = synced_hz(level, bpm)
            delay_time = 1.0 / hz if hz > 0 else 0.25
        else:
            # Approché : le temps du delay libre n'est pas relevé dans le
            # firmware ; 134 ms au réglage 25, une octave par cran.
            delay_time = 0.134 * 2.0 ** -float(np.mean(
                _octaves(sound, "delayRate", mod, n)))
        mixed = _delay(mixed, rate, min(2.0, delay_time),
                       min(0.95, delay_fb), delay_fb * 0.8)

    send = float(np.mean(_volume(sound, "reverbAmount", mod, n, 0.0)))
    reverb_amount = min(1.0, 0.45 * send)
    if reverb_amount > 0.02:
        mixed = _reverb(mixed, rate, reverb_amount)
    return mixed


def sound_effects(sound: Sound, audio: np.ndarray, sr: int = 44100,
                  bpm: float = PREVIEW_BPM) -> np.ndarray:
    """Les effets d'un son — mod FX, delay, réverbération — sur un rendu
    stéréo de ses voix déjà additionnées, comme le Deluge les applique au
    son entier. Les modulations des effets s'y prennent au repos."""
    if audio.size == 0:
        return audio
    rest = {"velocity": 0.0, "note": 0.0, "random": 0.0, "aftertouch": 0.0}
    mod = _patch(sound, rest, only=set(rest))
    out = np.empty_like(audio)
    for channel in range(audio.shape[1]):
        out[:, channel] = _effects(sound, audio[:, channel].copy(), int(sr),
                                   mod, bpm)
    return out


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
    :param effects: ``False`` rend la voix seule, sans mod FX, delay ni
        réverbération — :func:`render_parts` les applique au son entier
        (:func:`sound_effects`).

    Les niveaux suivent les lois de volume du firmware : deux sons, ou deux
    vélocités, gardent leur rapport. Ne lève jamais : un son impossible à
    rendre donne un tableau silencieux.
    """
    try:
        n = max(1, int(float(seconds) * int(sr)))
        rate = int(sr)
        rng = np.random.default_rng(_graine(sound.name))

        # -- sources constantes de la note (``voice.cpp``) ---------------- #
        midi_velocity = max(1.0, min(127.0, float(velocity) * 127.0))
        constants = {
            "velocity": float(laws.velocity_source(midi_velocity)),
            "note": float(laws.note_source(note)),
            # *random* : une valeur tirée à chaque note, pas une dérive.
            # La dérive (« rwalk » à 3 Hz) faisait tanguer d'un demi-ton
            # les sons qui en portaient un câble vers la hauteur.
            "random": float(rng.uniform(-1.0, 1.0)),
            "aftertouch": 0.0,
        }
        static = _patch(sound, constants, only=set(constants))

        # -- enveloppes et LFO ------------------------------------------- #
        # Un échantillon en mode ONCE se joue jusqu'au bout : le Deluge
        # ignore alors la fin de la note. Relâcher l'enveloppe à la fin de
        # la note (release 0 sur une rangée de kit) coupait le son net.
        osc1 = sound.osc1
        if (osc1 is not None and osc1.is_sample
                and int(getattr(osc1, "loop_mode", 0)) == 1):
            gate = 1.0
        a1, d1, s1, r1 = _env_times(sound, sound.env1, 1, static)
        a2, d2, s2, r2 = _env_times(sound, sound.env2, 2, static)
        env1 = _adsr(n, rate, a1, d1, s1, r1, gate)
        env2 = _adsr(n, rate, a2, d2, s2, r2, gate)

        def _lfo_hz(lfo, key):
            # Un LFO synchronisé bat au tempo : sa vitesse libre est ignorée.
            if getattr(lfo, "sync_level", 0):
                return synced_hz(lfo.sync_level, bpm)
            return float(laws.lfo_hz(
                laws.exp_range(key) * _u(sound, key)
                + np.mean(static.oct(key))))

        lfo1 = _lfo(n, rate, sound.lfo1.type,
                    _lfo_hz(sound.lfo1, "lfo1Rate"), rng)
        lfo2 = _lfo(n, rate, sound.lfo2.type,
                    _lfo_hz(sound.lfo2, "lfo2Rate"), rng)

        # Sources bipolaires, comme les lit un câble sans polarité : une
        # enveloppe vaut −1 au repos et +1 à son sommet.
        sources = dict(constants)
        sources.update({
            "envelope1": laws.envelope_source(env1).astype(np.float32),
            "envelope2": laws.envelope_source(env2).astype(np.float32),
            "lfo1": lfo1,
            "lfo2": lfo2,
        })
        mod = _patch(sound, sources)

        # -- hauteur ------------------------------------------------------ #
        master = _octaves(sound, "pitch", mod, n) * 12.0
        porta = _display(sound, "portamento", 0.0)
        if glide_from and porta > 0 and sound.polyphonic != "legato":
            glide = laws.glide_seconds(porta)
            if glide > 0:
                t = np.arange(n, dtype=np.float64) / rate
                # La hauteur part de la note précédente et la quitte en
                # ``decayTableSmall4``, comme l'enveloppe du glissé.
                master = master + (float(glide_from) * (
                    1.0 - laws.attack_curve(t / glide))).astype(np.float32)
        pitch_a = master + _series(mod.oct("oscAPitch"), n) * 12.0
        pitch_b = master + _series(mod.oct("oscBPitch"), n) * 12.0
        pw_a = 0.5 + 0.45 * _hybrid(sound, "oscAPulseWidth", mod, n)
        pw_b = 0.5 + 0.45 * _hybrid(sound, "oscBPulseWidth", mod, n)

        # -- oscillateurs ------------------------------------------------- #
        osc_a = _oscillator(sound, sound.osc1, "A", note, n, rate, pitch_a,
                            pw_a, sd, rng)
        level_a = _volume(sound, "oscAVolume", mod, n, 50.0)
        level_b = _volume(sound, "oscBVolume", mod, n, 0.0)

        if sound.mode == "fm":
            mixed = _fm_voice(sound, note, n, rate, pitch_a, mod,
                              level_a, level_b)
        elif sound.mode == "ringmod":
            osc_b = _oscillator(sound, sound.osc2, "B", note, n, rate,
                                pitch_b, pw_b, sd, rng)
            mixed = (osc_a * osc_b * level_a).astype(np.float32)
        else:
            osc_b = _oscillator(sound, sound.osc2, "B", note, n, rate,
                                pitch_b, pw_b, sd, rng)
            mixed = (osc_a * level_a + osc_b * level_b).astype(np.float32)

        noise_level = _volume(sound, "noiseVolume", mod, n, 0.0)
        if float(np.max(noise_level)) > 1e-3:
            mixed = mixed + (rng.standard_normal(n).astype(np.float32) * 0.5
                             * noise_level)

        # -- filtres ------------------------------------------------------ #
        if str(sound.lpf_mode or "").lower() != "off":
            poles = 2 if sound.lpf_mode in ("12dB",) else 4
            cutoff = laws.lpf_hz(_octaves(sound, "lpfFrequency", mod, n, 50.0))
            q = _q_of(laws.ladder_resonance(
                _linear(sound, "lpfResonance", mod, n, 0.0)))
            mixed = _filter_sweep(mixed, rate, cutoff.astype(np.float32),
                                  q.astype(np.float32), poles)

        if sound.hpf_mode and str(sound.hpf_mode).lower() != "off":
            hp_cut = laws.hpf_hz(_octaves(sound, "hpfFrequency", mod, n, 0.0))
            if float(np.max(hp_cut)) > 20.0:
                hp_q = _q_of(laws.ladder_resonance(
                    _linear(sound, "hpfResonance", mod, n, 0.0)))
                mixed = _filter_sweep(mixed, rate, hp_cut.astype(np.float32),
                                      hp_q.astype(np.float32), 2,
                                      high_pass=True)

        # -- enveloppe d'amplitude --------------------------------------- #
        # ``voice.cpp`` : le volume du son, enveloppe 1 comprise
        # (linéaire en niveau d'enveloppe).
        mixed = mixed * env1 * _volume(sound, "volume", mod, n, 50.0)

        # -- saleté ------------------------------------------------------- #
        if sound.clipping_amount:
            mixed = _saturate(mixed, min(1.0, sound.clipping_amount / 10.0))
        mixed = _decimate(mixed, _unit(sound, "sampleRateReduction", 0.0))
        mixed = _bitcrush(mixed, _unit(sound, "bitCrush", 0.0))

        # -- effets ------------------------------------------------------- #
        # Sur le Deluge, ils traitent le son entier, voix additionnées :
        # :func:`render_parts` les applique une fois, à la partie.
        if effects:
            mixed = _effects(sound, mixed, rate, mod, bpm)

        # -- niveau et stéréo -------------------------------------------- #
        # Une marge fixe, la même pour tous les sons : les lois de volume
        # gardent leurs rapports, d'un son à l'autre et d'une vélocité à
        # l'autre. Seul un son qui écrêterait est ramené.
        mixed = mixed * OUTPUT_HEADROOM
        peak = float(np.max(np.abs(mixed)))
        if peak > 0.99:
            mixed = mixed * (0.99 / peak)

        # Panoramique : centré au réglage 25 (l'ancien calcul, 25/50,
        # penchait chaque son à droite).
        pan = float(np.clip(np.mean(_hybrid(sound, "pan", mod, n)),
                            -1.0, 1.0))
        left = mixed * float(np.sqrt((1.0 - pan) * 0.5))
        right = mixed * float(np.sqrt((1.0 + pan) * 0.5))

        if sound.unison_spread and sound.unison_num > 1:
            # Élargissement : un très court décalage entre les canaux.
            shift = max(1, int(sound.unison_spread / 50.0 * 0.004 * rate))
            right = np.concatenate([np.zeros(shift, dtype=np.float32),
                                    right[:-shift]])

        # Un fondu de 5 ms en fin de rendu : la fenêtre se termine parfois
        # au milieu du son, et une coupure nette s'entend comme un clic.
        fade = min(n, max(1, int(0.005 * rate)))
        ramp = np.linspace(1.0, 0.0, fade, dtype=np.float32)
        left[-fade:] *= ramp
        right[-fade:] *= ramp
        return np.stack([left, right], axis=1).astype(np.float32)
    except Exception as exc:  # noqa: BLE001 - rempart : on rend du silence
        log.exception("rendu impossible : %s", exc)
        return np.zeros((max(1, int(float(seconds) * int(sr))), 2),
                        dtype=np.float32)


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
    réverbération ne soient pas coupées net.
    """
    sound = preset.sound
    if notes is None:
        notes = preview_notes(sound)
    notes = [int(n) for n in (notes or [48]) if 0 <= int(n) <= 127] or [48]

    step = 0.55
    tail = 1.1
    total = int((step * len(notes) + tail) * sr)
    out = np.zeros((total, 2), dtype=np.float32)

    for index, note in enumerate(notes):
        voice = render_sound(sound, note=note, seconds=step + tail, sr=sr,
                             gate=0.6, velocity=0.85, sd=sd, effects=False)
        start = int(index * step * sr)
        end = min(total, start + voice.shape[0])
        out[start:end] += voice[:end - start]
    # Les effets traitent la phrase entière, comme le son entier sur la
    # machine.
    out = sound_effects(sound, out, sr=sr)

    peak = float(np.max(np.abs(out)))
    if peak > 0.99:
        out *= 0.99 / peak
    return out


def render_parts(parts: dict, sounds: dict, bpm: float = 120.0,
                 sr: int = 44100, sd: SDCard | None = None,
                 tail: float = 0.8, should_stop=None) -> np.ndarray | None:
    """Rend des parties d'accompagnement, chacune avec son son.

    :param parts: ``{nom: [NoteEvent]}`` (cf. :mod:`delugeapp.core.accomp`),
        positions en pas de double-croche.
    :param sounds: ``{nom: Sound}`` ; une partie sans son est ignorée.
    :param tail: secondes laissées, au moins, à l'extinction de chaque
        note ; un son au release plus long garde le sien
        (:func:`tail_seconds`).
    :param should_stop: consulté entre deux notes ; vrai, le rendu s'arrête
        et rend ``None``. Avec les vraies durées de release, un rendu peut
        dépasser deux secondes : à la fermeture, le fil doit pouvoir
        s'arrêter au lieu d'être tué en plein calcul.

    Comme sur la machine : un son **mono** ou **legato** coupe sa note
    précédente ; un son qui a un glissé part de la note précédente ; le
    tempo cale LFO et delay synchronisés.

    Une même note de même durée n'est rendue qu'une fois : une basse qui
    martèle la fondamentale coûte une note, pas trente-deux.
    """
    from .accomp import total_steps

    tempo = float(bpm) if bpm and bpm > 0 else 120.0
    step_s = 60.0 / tempo / 4.0
    tails = {name: max(float(tail), tail_seconds(sound))
             for name, sound in (sounds or {}).items() if sound is not None}
    length_s = total_steps(parts) * step_s + max(tails.values(),
                                                  default=float(tail))
    n = max(1, int(length_s * sr))
    out = np.zeros((n, 2), dtype=np.float32)
    cache: dict[tuple, np.ndarray] = {}
    fade = max(1, int(0.008 * sr))
    for name, events in (parts or {}).items():
        sound = (sounds or {}).get(name)
        if sound is None:
            continue
        mono = sound.polyphonic in ("mono", "legato")
        glides = (sound.polyphonic != "legato"
                  and _display(sound, "portamento", 0.0) > 0)
        ordered = sorted(events, key=lambda e: float(e.start))
        voices = np.zeros((n, 2), dtype=np.float32)
        previous = None
        for index, event in enumerate(ordered):
            if should_stop is not None and should_stop():
                return None
            held = max(0.02, float(event.length) * step_s)
            seconds = held + tails.get(name, float(tail))
            start = int(float(event.start) * step_s * sr)
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
            key = (name, int(event.note), round(held, 3), round(seconds, 2),
                   int(event.velocity) // 5, glide)
            voice = cache.get(key)
            if voice is None:
                voice = render_sound(
                    sound, note=int(event.note), seconds=seconds, sr=sr,
                    gate=min(1.0, held / seconds),
                    # ``NoteEvent.velocity`` est un pourcentage : 100 %
                    # joue la vélocité 127.
                    velocity=max(1.0, min(100.0, float(event.velocity)))
                    / 100.0,
                    sd=sd, bpm=tempo, glide_from=glide, effects=False)
                cache[key] = voice
            previous = event
            if start >= n:
                continue
            length = voice.shape[0]
            if mono and index + 1 < len(ordered):
                # La note suivante vole la voix : relâchement rapide.
                following = int(float(ordered[index + 1].start) * step_s * sr)
                length = max(1, min(length, following - start + fade))
            end = min(n, start + length)
            chunk = voice[:end - start].copy()
            if end - start < voice.shape[0] and chunk.shape[0] > fade:
                chunk[-fade:] *= np.linspace(1.0, 0.0, fade,
                                             dtype=np.float32)[:, None]
            voices[start:end] += chunk
        # Les effets traitent le son entier, comme sur la machine : une
        # réverbération par partie, et non une par note.
        out += sound_effects(sound, voices, sr=sr, bpm=tempo)
    peak = float(np.max(np.abs(out))) if out.size else 0.0
    if peak > 0.98:
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
            voice = render_sound(row.sound, note=60, seconds=step + 1.0,
                                 sr=sr, gate=0.5, velocity=0.9, sd=sd)
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
                    voice = render_sound(
                        row.sound, note=60, seconds=1.2, sr=sr, gate=0.5,
                        velocity=max(0.2, min(1.0, step_item.velocity
                                              / 100.0)), sd=sd)
                    cache[key] = voice
                start = int(float(step_item.pos) * seconds_per_step * sr)
                end = min(total, start + voice.shape[0])
                if end > start:
                    out[start:end] += voice[:end - start]

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
                   bars: int | None = None, tail: float = 0.8) -> np.ndarray:
    """Rend un motif rythmique, bouclé sur ``bars`` mesures.

    Chaque piste est jouée par la rangée du kit qui porte son nom — un
    échantillon de la carte — ou, à défaut, par la batterie synthétisée :
    une piste euclidienne ou un rôle sans échantillon sonne quand même.
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
                    voice = render_sound(row.sound, note=60, seconds=1.2,
                                         sr=sr, gate=0.5,
                                         velocity=max(0.2, level / 20.0),
                                         sd=sd)
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
    if peak > 0.98:
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
