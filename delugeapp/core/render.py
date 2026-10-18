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

Ne dépend que de numpy.
"""

from __future__ import annotations

import logging
import zlib
from functools import lru_cache

import numpy as np

from .fixedpoint import to_display
from .model import Kit, Sound, SynthPreset, param_of_destination
from .sdcard import SDCard

log = logging.getLogger(__name__)

#: Taille des tables d'onde.
TABLE_SIZE = 2048

#: Taille des blocs de filtrage, et recouvrement.
FILTER_BLOCK = 1024

#: Bornes du filtre, en hertz.
CUTOFF_MIN_HZ = 30.0
CUTOFF_MAX_HZ = 18000.0

#: Bornes des temps d'enveloppe, en secondes.
ATTACK_MIN, ATTACK_MAX = 0.001, 6.0
DECAY_MIN, DECAY_MAX = 0.005, 10.0
RELEASE_MIN, RELEASE_MAX = 0.005, 10.0

#: Bornes de vitesse des LFO, en hertz.
LFO_MIN_HZ, LFO_MAX_HZ = 0.05 , 30.0

#: Destinations de modulation reconnues. Les autres sont ignorées avec une
#: trace : le Deluge en accepte une cinquantaine, toutes n'ont pas d'effet
#: audible dans une approximation.
KNOWN_DESTINATIONS = (
    "lpfFrequency", "lpfResonance", "hpfFrequency", "pitch", "volume",
    "oscAVolume", "oscBVolume", "oscAPitch", "oscBPitch", "oscAPulseWidth",
    "oscBPulseWidth", "noiseVolume", "modFXDepth", "modFXRate",
    "reverbAmount", "delayFeedback", "pan",
    "modulator1Amount", "modulator2Amount",
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


def _exp_map(unit: float, low: float, high: float) -> float:
    """Interpolation exponentielle : l'oreille entend les rapports."""
    unit = max(0.0, min(1.0, float(unit)))
    return float(low * (high / low) ** unit)


def _cutoff_hz(unit: float) -> float:
    """Coupure du filtre en hertz, depuis une valeur 0..1."""
    return _exp_map(unit, CUTOFF_MIN_HZ, CUTOFF_MAX_HZ)


def _resonance_q(unit: float) -> float:
    """Facteur de qualité, de 0,7 (neutre) à 12 (auto-oscillation proche)."""
    return 0.707 + 11.3 * max(0.0, min(1.0, float(unit))) ** 2


def _env_times(env) -> tuple[float, float, float, float]:
    """``(attaque, decay, sustain, release)`` en secondes et en niveau."""
    attack = _exp_map(to_display(env.attack) / 50.0, ATTACK_MIN, ATTACK_MAX)
    decay = _exp_map(to_display(env.decay) / 50.0, DECAY_MIN, DECAY_MAX)
    sustain = max(0.0, min(1.0, to_display(env.sustain) / 50.0))
    release = _exp_map(to_display(env.release) / 50.0,
                       RELEASE_MIN, RELEASE_MAX)
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
    """Enveloppe ADSR échantillonnée.

    ``gate`` est la fraction de la durée pendant laquelle la touche est
    tenue ; le relâchement part du niveau atteint à cet instant, et non du
    sustain théorique, sinon une note relâchée pendant son attaque produit un
    saut de niveau.
    """
    out = np.zeros(n, dtype=np.float32)
    if n <= 0:
        return out
    gate_samples = max(1, min(n, int(n * max(0.01, min(1.0, gate)))))

    a = max(1, int(attack * sr))
    d = max(1, int(decay * sr))
    pos = 0
    if a < gate_samples:
        out[:a] = np.linspace(0.0, 1.0, a, dtype=np.float32)
        pos = a
    else:
        out[:gate_samples] = np.linspace(0.0, gate_samples / a, gate_samples,
                                         dtype=np.float32)
        pos = gate_samples

    if pos < gate_samples:
        remaining = gate_samples - pos
        # Décroissance exponentielle vers le sustain, comme sur la machine.
        curve = np.exp(-np.arange(remaining, dtype=np.float32) / max(1.0, d))
        out[pos:gate_samples] = sustain + (1.0 - sustain) * curve

    level = float(out[gate_samples - 1]) if gate_samples > 0 else 0.0
    tail = n - gate_samples
    if tail > 0:
        r = max(1.0, release * sr)
        out[gate_samples:] = level * np.exp(
            -np.arange(tail, dtype=np.float32) / r)
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

def _modulations(sound: Sound, n: int, sr: int, sources: dict,
                 ) -> dict[str, np.ndarray]:
    """Somme, par destination, des modulations issues des patch cables.

    Les valeurs sont en unités d'affichage signées (−50 à +50), ce qui permet
    de les ajouter directement au paramètre de base.
    """
    out: dict[str, np.ndarray] = {}
    for cable in sound.patch_cables:
        # Le câble vise ``oscAPhaseWidth`` quand le paramètre s'appelle
        # ``oscAPulseWidth`` : sans cette traduction, les 295 câbles de
        # largeur d'impulsion de la carte restaient muets à l'écoute.
        destination = param_of_destination(cable.destination)
        if destination not in KNOWN_DESTINATIONS:
            log.debug("destination de modulation ignorée : %s",
                      cable.destination)
            continue
        signal = sources.get(cable.source)
        if signal is None:
            log.debug("source de modulation ignorée : %s", cable.source)
            continue
        amount = cable.display() / 50.0        # −1 à +1
        contribution = (signal * amount * 50.0).astype(np.float32)
        if destination in out:
            out[destination] = out[destination] + contribution
        else:
            out[destination] = contribution
    return out


def _modulated(base_display: float, mod: np.ndarray | None, n: int,
               ) -> np.ndarray:
    """Paramètre de base plus sa modulation, borné à 0..50, puis ramené 0..1."""
    if mod is None:
        return np.full(n, max(0.0, min(1.0, base_display / 50.0)),
                       dtype=np.float32)
    total = np.clip(base_display + mod, 0.0, 50.0)
    return (total / 50.0).astype(np.float32)


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


def _filter_sweep(signal: np.ndarray, sr: int, cutoff_unit: np.ndarray,
                  q_unit: np.ndarray, poles: int,
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
        cutoff = _cutoff_hz(float(cutoff_unit[centre]))
        q = _resonance_q(float(q_unit[centre]))
        response = _response(freqs, cutoff, q, poles, high_pass)
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
    detune_cents = max(0, sound.unison_detune) * 2.0
    out = np.zeros(n, dtype=np.float32)

    for v in range(voices):
        if voices > 1:
            spread = (v / (voices - 1.0)) * 2.0 - 1.0
        else:
            spread = 0.0
        freq = base_hz * 2.0 ** (spread * detune_cents / 1200.0)
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
              pitch_mod: np.ndarray, mod: dict, level_a: np.ndarray,
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
    # doux au métal sans tomber dans le bruit.
    depth1 = _modulated(sound.display("modulator1Amount"),
                        mod.get("modulator1Amount"), n) * 6.0
    depth2 = _modulated(sound.display("modulator2Amount"),
                        mod.get("modulator2Amount"), n) * 6.0

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




def render_sound(sound: Sound, note: int = 48, seconds: float = 2.5,
                 sr: int = 44100, gate: float = 0.7, velocity: float = 0.9,
                 sd: SDCard | None = None) -> np.ndarray:
    """Rend un son en float32, forme ``(frames, 2)``.

    :param note: note MIDI jouée.
    :param gate: fraction de la durée pendant laquelle la touche est tenue.
    :param velocity: vélocité de 0 à 1, qui alimente la source ``velocity``
        des modulations.
    :param sd: carte, nécessaire pour lire les oscillateurs de type
        ``sample``. Sans elle, ces oscillateurs sont remplacés par une onde.

    Ne lève jamais : un son impossible à rendre donne un tableau silencieux.
    """
    try:
        n = max(1, int(float(seconds) * int(sr)))
        rate = int(sr)
        rng = np.random.default_rng(_graine(sound.name))

        # -- enveloppes et LFO ------------------------------------------- #
        # Un échantillon en mode ONCE se joue jusqu'au bout : le Deluge
        # ignore alors la fin de la note. Relâcher l'enveloppe à la fin de
        # la note (release 0 sur une rangée de kit) coupait le son net.
        osc1 = sound.osc1
        if (osc1 is not None and osc1.is_sample
                and int(getattr(osc1, "loop_mode", 0)) == 1):
            gate = 1.0
        a1, d1, s1, r1 = _env_times(sound.env1)
        a2, d2, s2, r2 = _env_times(sound.env2)
        env1 = _adsr(n, rate, a1, d1, s1, r1, gate)
        env2 = _adsr(n, rate, a2, d2, s2, r2, gate)
        def _lfo_hz(lfo, key):
            # Un LFO synchronisé bat au tempo : sa vitesse libre est ignorée.
            if getattr(lfo, "sync_level", 0):
                return synced_hz(lfo.sync_level)
            return _exp_map(_unit(sound, key), LFO_MIN_HZ, LFO_MAX_HZ)

        lfo1 = _lfo(n, rate, sound.lfo1.type,
                    _lfo_hz(sound.lfo1, "lfo1Rate"), rng)
        lfo2 = _lfo(n, rate, sound.lfo2.type,
                    _lfo_hz(sound.lfo2, "lfo2Rate"), rng)

        sources = {
            "envelope1": env1,
            "envelope2": env2,
            "lfo1": lfo1,
            "lfo2": lfo2,
            "velocity": np.full(n, float(velocity), dtype=np.float32),
            "note": np.full(n, note / 127.0, dtype=np.float32),
            "aftertouch": np.full(n, 0.3, dtype=np.float32),
            "random": _lfo(n, rate, "rwalk", 3.0, rng),
        }
        mod = _modulations(sound, n, rate, sources)

        # -- oscillateurs ------------------------------------------------- #
        pitch_mod = np.zeros(n, dtype=np.float32)
        for key, scale in (("pitch", 12.0), ("oscAPitch", 12.0)):
            if key in mod:
                pitch_mod = pitch_mod + mod[key] / 50.0 * scale
        pw = _modulated(sound.display("oscAPulseWidth"),
                        mod.get("oscAPulseWidth"), n) * 0.5 + 0.25

        osc_a = _oscillator(sound, sound.osc1, "A", note, n, rate, pitch_mod,
                            pw, sd, rng)
        level_a = _modulated(sound.display("oscAVolume"),
                             mod.get("oscAVolume"), n)
        level_b = _modulated(sound.display("oscBVolume"),
                             mod.get("oscBVolume"), n)

        if sound.mode == "fm":
            mixed = _fm_voice(sound, note, n, rate, pitch_mod, mod,
                              level_a, level_b)
        elif sound.mode == "ringmod":
            osc_b = _oscillator(sound, sound.osc2, "B", note, n, rate,
                                pitch_mod, pw, sd, rng)
            mixed = (osc_a * osc_b * level_a).astype(np.float32)
        else:
            osc_b = _oscillator(sound, sound.osc2, "B", note, n, rate,
                                pitch_mod, pw, sd, rng)
            mixed = (osc_a * level_a + osc_b * level_b).astype(np.float32)

        noise_level = _modulated(sound.display("noiseVolume"),
                                 mod.get("noiseVolume"), n)
        if float(np.max(noise_level)) > 0.01:
            mixed = mixed + (rng.standard_normal(n).astype(np.float32) * 0.3
                             * noise_level)

        # -- filtres ------------------------------------------------------ #
        poles = 2 if sound.lpf_mode in ("12dB",) else 4
        cutoff = _modulated(sound.display("lpfFrequency"),
                            mod.get("lpfFrequency"), n)
        reso = _modulated(sound.display("lpfResonance"),
                          mod.get("lpfResonance"), n)
        mixed = _filter_sweep(mixed, rate, cutoff, reso, poles)

        if sound.hpf_mode and sound.display("hpfFrequency") > 1:
            hp_cut = _modulated(sound.display("hpfFrequency"),
                                mod.get("hpfFrequency"), n)
            hp_q = _modulated(sound.display("hpfResonance"), None, n)
            mixed = _filter_sweep(mixed, rate, hp_cut, hp_q, 2,
                                  high_pass=True)

        # -- enveloppe d'amplitude --------------------------------------- #
        mixed = mixed * env1
        if "volume" in mod:
            mixed = mixed * np.clip(1.0 + mod["volume"] / 50.0, 0.0, 2.0)

        # -- saleté ------------------------------------------------------- #
        if sound.clipping_amount:
            mixed = _saturate(mixed, min(1.0, sound.clipping_amount / 10.0))
        mixed = _decimate(mixed, _unit(sound, "sampleRateReduction", 0.0))
        mixed = _bitcrush(mixed, _unit(sound, "bitCrush", 0.0))

        # -- effets ------------------------------------------------------- #
        mod_rate = _exp_map(_unit(sound, "modFXRate", 0.3), 0.05, 8.0)
        mod_depth = _modulated(sound.display("modFXDepth"),
                               mod.get("modFXDepth"), n)
        mixed = _mod_fx(mixed, rate, sound.mod_fx_type,
                        float(np.mean(mod_depth)), mod_rate)

        delay_time = _exp_map(_unit(sound, "delayRate", 0.4), 0.02, 0.9)
        delay_fb = _unit(sound, "delayFeedback", 0.0)
        if delay_fb > 0.02:
            mixed = _delay(mixed, rate, delay_time, delay_fb, delay_fb * 0.6)

        reverb_amount = _unit(sound, "reverbAmount", 0.0)
        if reverb_amount > 0.02:
            mixed = _reverb(mixed, rate, reverb_amount)

        # -- niveau et stéréo -------------------------------------------- #
        mixed = mixed * (0.3 + 0.7 * _unit(sound, "volume", 0.8)) * velocity
        peak = float(np.max(np.abs(mixed)))
        if peak > 0.99:
            mixed = mixed * (0.99 / peak)

        pan = (sound.display("pan") / 50.0) if "pan" in sound.params else 0.0
        pan = float(np.clip(pan, -1.0, 1.0))
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


def render_preview(preset: SynthPreset, notes: list[int] | None = None,
                   sr: int = 44100, sd: SDCard | None = None) -> np.ndarray:
    """Petite phrase d'audition, choisie selon la catégorie du preset.

    Les notes se succèdent avec un léger recouvrement, pour que les queues de
    réverbération ne soient pas coupées net.
    """
    sound = preset.sound
    if notes is None:
        try:
            category = sound.category_guess()
        except Exception:  # noqa: BLE001
            category = "Autre"
        notes = _PREVIEW_NOTES.get(category, _PREVIEW_NOTES["Autre"])
    notes = [int(n) for n in (notes or [48]) if 0 <= int(n) <= 127] or [48]

    step = 0.55
    tail = 1.1
    total = int((step * len(notes) + tail) * sr)
    out = np.zeros((total, 2), dtype=np.float32)

    for index, note in enumerate(notes):
        voice = render_sound(sound, note=note, seconds=step + tail, sr=sr,
                             gate=0.6, velocity=0.85, sd=sd)
        start = int(index * step * sr)
        end = min(total, start + voice.shape[0])
        out[start:end] += voice[:end - start]

    peak = float(np.max(np.abs(out)))
    if peak > 0.99:
        out *= 0.99 / peak
    return out


def render_parts(parts: dict, sounds: dict, bpm: float = 120.0,
                 sr: int = 44100, sd: SDCard | None = None,
                 tail: float = 0.8) -> np.ndarray:
    """Rend des parties d'accompagnement, chacune avec son son.

    :param parts: ``{nom: [NoteEvent]}`` (cf. :mod:`delugeapp.core.accomp`),
        positions en pas de double-croche.
    :param sounds: ``{nom: Sound}`` ; une partie sans son est ignorée.
    :param tail: secondes laissées à l'extinction de chaque note.

    Une même note de même durée n'est rendue qu'une fois : une basse qui
    martèle la fondamentale coûte une note, pas trente-deux.
    """
    from .accomp import total_steps

    tempo = float(bpm) if bpm and bpm > 0 else 120.0
    step_s = 60.0 / tempo / 4.0
    length_s = total_steps(parts) * step_s + tail
    n = max(1, int(length_s * sr))
    out = np.zeros((n, 2), dtype=np.float32)
    cache: dict[tuple, np.ndarray] = {}
    for name, events in (parts or {}).items():
        sound = (sounds or {}).get(name)
        if sound is None:
            continue
        for event in events:
            held = max(0.02, float(event.length) * step_s)
            key = (name, int(event.note), round(held, 3),
                   int(event.velocity) // 5)
            voice = cache.get(key)
            if voice is None:
                seconds = held + tail
                voice = render_sound(sound, note=int(event.note),
                                     seconds=seconds, sr=sr,
                                     gate=held / seconds,
                                     velocity=max(0.05, event.velocity / 100.0),
                                     sd=sd)
                cache[key] = voice
            start = int(float(event.start) * step_s * sr)
            if start >= n:
                continue
            end = min(n, start + voice.shape[0])
            out[start:end] += voice[:end - start]
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
