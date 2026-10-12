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
from .model import Kit, Sound, SynthPreset
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
)

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
    if kind == "sampleAndHold":
        steps = max(1, int(rate_hz * n / sr))
        values = rng.uniform(-1.0, 1.0, steps + 1).astype(np.float32)
        return values[np.minimum((phase % steps).astype(np.int64)
                                 if steps > 1 else np.zeros(n, dtype=np.int64),
                                 steps)]
    if kind == "randomWalk":
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
        if cable.destination not in KNOWN_DESTINATIONS:
            log.debug("destination de modulation ignorée : %s",
                      cable.destination)
            continue
        signal = sources.get(cable.source)
        if signal is None:
            log.debug("source de modulation ignorée : %s", cable.source)
            continue
        amount = cable.display() / 50.0        # −1 à +1
        contribution = (signal * amount * 50.0).astype(np.float32)
        if cable.destination in out:
            out[cable.destination] = out[cable.destination] + contribution
        else:
            out[cable.destination] = contribution
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
    base_ms = {"flanger": 2.0, "chorus": 14.0, "stereoChorus": 18.0,
               "phaser": 6.0, "warble": 24.0, "grain": 30.0}.get(kind, 14.0)
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
        a1, d1, s1, r1 = _env_times(sound.env1)
        a2, d2, s2, r2 = _env_times(sound.env2)
        env1 = _adsr(n, rate, a1, d1, s1, r1, gate)
        env2 = _adsr(n, rate, a2, d2, s2, r2, gate)
        lfo1 = _lfo(n, rate, sound.lfo1.type,
                    _exp_map(_unit(sound, "lfo1Rate"), LFO_MIN_HZ, LFO_MAX_HZ),
                    rng)
        lfo2 = _lfo(n, rate, sound.lfo2.type,
                    _exp_map(_unit(sound, "lfo2Rate"), LFO_MIN_HZ, LFO_MAX_HZ),
                    rng)

        sources = {
            "envelope1": env1,
            "envelope2": env2,
            "lfo1": lfo1,
            "lfo2": lfo2,
            "velocity": np.full(n, float(velocity), dtype=np.float32),
            "note": np.full(n, note / 127.0, dtype=np.float32),
            "aftertouch": np.full(n, 0.3, dtype=np.float32),
            "random": _lfo(n, rate, "randomWalk", 3.0, rng),
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
            # Deux opérateurs : l'oscillateur B module la phase de A.
            depth = _unit(sound, "modulator1Amount", 0.3) * 8.0
            modulator = _oscillator(sound, sound.osc2, "B", note, n, rate,
                                    pitch_mod, pw, sd, rng)
            semis = sound.osc1.transpose + sound.transpose
            carrier_hz = 440.0 * 2.0 ** ((note + semis - 69) / 12.0)
            phase = np.cumsum(
                np.full(n, carrier_hz / rate, dtype=np.float32))
            mixed = np.sin(2.0 * np.pi * (phase + modulator * depth),
                           dtype=np.float32)
            mixed = mixed * level_a
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
                    voice = render_sound(
                        row.sound, note=60, seconds=1.2, sr=sr, gate=0.5,
                        velocity=max(0.2, step_item.velocity / 127.0), sd=sd)
                    cache[key] = voice
                start = int(float(step_item.pos) * seconds_per_step * sr)
                end = min(total, start + voice.shape[0])
                if end > start:
                    out[start:end] += voice[:end - start]

    peak = float(np.max(np.abs(out)))
    if peak > 0.99:
        out *= 0.99 / peak
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
