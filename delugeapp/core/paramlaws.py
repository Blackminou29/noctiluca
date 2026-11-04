# -*- coding: utf-8 -*-
"""Les lois des paramètres d'un son du Deluge, lues dans son firmware.

Le moteur d'écoute (:mod:`delugeapp.core.render`) traduisait les réglages en
sons par des courbes estimées « à l'oreille » : une coupure de 30 Hz à
18 kHz, des enveloppes de 1 ms à 10 s, des sources de modulation de 0 à 1.
L'utilisateur l'a entendu le 22 octobre 2026 : ses sons de l'atelier, écoutés
sur le PC, n'avaient « rien à voir » avec le Deluge. Mesuré sur ses trois
synthés, réglage par réglage : un decay de 13 durait 36 ms au lieu de
1,8 s, un vibrato de 5 balançait ±1,2 demi-ton au lieu de ±0,34, et
l'enveloppe d'une nappe, qui la referme sur la machine, la laissait ouverte.

Ce module donne les lois **du firmware de la machine** (1.3, commit
``102cf9f``) :

* ``functions.cpp`` — ``getParamRange``, ``getParamNeutralValue``,
  ``getExp`` (une octave par 2²⁶), ``lookupReleaseRate``, les lois de volume
  (quadratique) et linéaire ;
* ``patcher.cpp`` et ``patch_cable_set.cpp`` — comment un câble s'ajoute
  (en octaves pour un paramètre exponentiel, en facteur ``1 + v·a`` pour un
  paramètre linéaire), et la force **au carré** vers une hauteur ;
* ``patch_cable.h`` et ``patch_cable_set.cpp:834`` — un câble lu sans
  attribut ``polarity`` est **bipolaire** : une enveloppe y vaut −1 au repos
  et +1 à son sommet ;
* ``voice.cpp`` — vélocité et note ``(x − 64)/64``, *random* tiré une fois
  par note, l'enveloppe 1 appliquée au volume, le glissé ;
* ``envelope.cpp`` — chaque étape dure ``2²³ / vitesse`` échantillons, avec
  les courbes ``decayTableSmall4`` (attaque) et ``decayTableSmall8`` ;
* ``filter.h`` et ``lpladder.cpp`` — la coupure passe par ``tan`` sur
  ``1,44 rad`` à pleine échelle, soit 20 214 Hz au plus ;
* ``phase_increment_fine_tuner.cpp`` — l'unisson s'étale sur ±désaccord/2
  cents.

Les tables du firmware ont des formes exactes, recalculées ici :
``decayTableSmall4(x) = (2^(4(1−x)) − 1)/15``,
``decayTableSmall8(x) = (2^(8(1−x)) − 1)/255``, ``expTableSmall = 2^x``,
``tanTable = 2²⁸·tan(1,44·i/64)``. Seule ``releaseRateTable64`` n'a pas de
loi simple : ses 65 valeurs sont reprises telles quelles.

Tout est en flottants et accepte des tableaux numpy. Module arithmétique :
ni carte, ni audio, ni Qt.
"""

from __future__ import annotations

import math

import numpy as np

__all__ = [
    "SAMPLE_RATE", "unit", "raw_unit", "exp_range", "exp_octaves", "lpf_hz", "hpf_hz", "lfo_hz",
    "attack_rate", "decay_rate", "release_rate",
    "attack_seconds", "decay_seconds", "release_seconds", "glide_seconds",
    "volume_gain", "linear_level", "sustain_level", "ladder_resonance",
    "velocity_source", "note_source", "envelope_source", "to_polarity",
    "cable_strength", "cable_octaves", "cable_factor", "unison_cents",
    "attack_curve", "decay_curve", "PARAM_CLASS", "param_class",
]

#: Fréquence d'échantillonnage du Deluge.
SAMPLE_RATE = 44100

#: Pleine échelle d'une étape d'enveloppe (``envelope.cpp`` : 8388608).
_ENV_STEPS = float(1 << 23)

#: Vitesse d'attaque au-delà de laquelle l'attaque est sautée
#: (``Envelope::noteOn`` : 245632).
_ATTACK_SKIP = 245632.0

#: ``releaseRateTable64`` (``lookuptables.cpp``), indexée de 0 à 64 ; le
#: réglage du milieu tombe sur l'indice 32.
RELEASE_RATE_TABLE = (
    1959518848, 240577040, 126456408, 84972672, 63518640, 50408868, 41567836,
    35202512, 30400724, 26649400, 23637820, 21166812, 19102814, 17352918,
    15850494, 14546511, 13404089, 12394955, 11497068, 10692993, 9968758,
    9313033, 8716538, 8171592, 7671792, 7211749, 6786901, 6393359, 6027784,
    5687299, 5369406, 5071928, 4792960, 4530827, 4284050, 4051316, 3831462,
    3623446, 3426337, 3239300, 3061582, 2892503, 2731448, 2577859, 2431229,
    2291096, 2157036, 2028664, 1905625, 1787593, 1674270, 1565377, 1460662,
    1359888, 1262836, 1169305, 1079105, 992062, 908014, 826807, 748301,
    672363, 598870, 527703, 458757,
)
_RELEASE = np.array(RELEASE_RATE_TABLE, dtype=np.float64)

#: La coupure à pleine échelle : ``atan(tanTable[64] / 2²⁸)`` = 1,44 rad.
_THETA_MAX = 1.44


# --------------------------------------------------------------------------- #
# Réglages et classes de paramètres
# --------------------------------------------------------------------------- #

def unit(display):
    """Valeur de réglage −1..+1 depuis l'affichage 0..50 (25 = 0).

    Le fichier porte un entier 32 bits signé, linéaire en affichage :
    ``0x80000000`` à 0, ``0`` à 25, ``0x7FFFFFFF`` à 50.
    """
    return np.clip(np.asarray(display, dtype=np.float64) / 25.0 - 1.0,
                   -1.0, 1.0)


#: Étendue d'un réglage exponentiel, en octaves par unité (``getParamRange``
#: divisé par 2²⁷) : 5,6 pour la coupure du filtre, 6 pour les attaques,
#: 4 pour les hauteurs et le temps du delay, 8 sinon.
_EXP_RANGE = {
    "lpfFrequency": 5.6,
    "env1Attack": 6.0, "env2Attack": 6.0, "env3Attack": 6.0,
    "env4Attack": 6.0,
    "pitch": 4.0, "oscAPitch": 4.0, "oscBPitch": 4.0,
    "modulator1Pitch": 4.0, "modulator2Pitch": 4.0, "delayRate": 4.0,
}

#: La classe de chaque paramètre patché (``param.h``) : ``volume`` (loi
#: quadratique), ``linear``, ``hybrid`` (additif) ou ``exp``.
PARAM_CLASS = {
    **{k: "volume" for k in (
        "oscAVolume", "oscBVolume", "volume", "noiseVolume",
        "modulator1Volume", "modulator2Volume", "modulator1Amount",
        "modulator2Amount", "waveFold", "volumePostFX",
        "volumePostReverbSend", "reverbAmount", "modFXDepth")},
    **{k: "linear" for k in (
        "modulator1Feedback", "modulator2Feedback", "carrier1Feedback",
        "carrier2Feedback", "lpfResonance", "hpfResonance", "env1Sustain",
        "env2Sustain", "env3Sustain", "env4Sustain", "lpfMorph", "hpfMorph",
        "delayFeedback")},
    **{k: "hybrid" for k in (
        "oscAPulseWidth", "oscBPulseWidth", "oscAPhaseWidth",
        "oscBPhaseWidth", "oscAWavetablePosition", "oscBWavetablePosition",
        "pan")},
    **{k: "exp" for k in (
        "lpfFrequency", "pitch", "oscAPitch", "oscBPitch", "modulator1Pitch",
        "modulator2Pitch", "hpfFrequency", "lfo1Rate", "lfo2Rate",
        "lfo3Rate", "lfo4Rate", "env1Attack", "env2Attack", "env3Attack",
        "env4Attack", "env1Decay", "env2Decay", "env3Decay", "env4Decay",
        "env1Release", "env2Release", "env3Release", "env4Release",
        "delayRate", "modFXRate", "arpRate", "arpeggiatorRate")},
}


def param_class(name: str) -> str:
    """``volume``, ``linear``, ``hybrid``, ``exp`` — ``""`` si inconnu."""
    return PARAM_CLASS.get(str(name or ""), "")


def exp_range(name: str) -> float:
    """Octaves par unité de réglage d'un paramètre exponentiel."""
    return _EXP_RANGE.get(str(name or ""), 8.0)


def raw_unit(value) -> float:
    """Valeur −1..+1 d'un entier de fichier : ``0x80000000`` = −1, 0 = 0.

    Plus juste que l'affichage arrondi au cran, et sans ambiguïté pour les
    réglages que l'interface montre en bipolaire (le panoramique s'affiche
    0 au centre)."""
    try:
        return max(-1.0, min(1.0, float(int(value)) / 2147483648.0))
    except (TypeError, ValueError):
        return 0.0


def exp_octaves(name: str, display) -> np.ndarray:
    """Décalage en octaves d'un réglage exponentiel par rapport à son neutre
    (le réglage 25)."""
    return unit(display) * _EXP_RANGE.get(name, 8.0)


# --------------------------------------------------------------------------- #
# Fréquences
# --------------------------------------------------------------------------- #

def _tan_hz(neutral: float, octaves) -> np.ndarray:
    """Une fréquence de filtre : la valeur finale décalée de 5 bits, plafonnée
    à 2³¹ (``lshiftAndSaturate<5>``), puis ``θ = x / 2³¹ · 1,44`` rad,
    soit ``θ · fs / π`` Hz."""
    final = neutral * np.power(2.0, np.asarray(octaves, dtype=np.float64))
    x = np.minimum(final * 32.0, float(1 << 31))
    return x / float(1 << 31) * _THETA_MAX * SAMPLE_RATE / math.pi


def lpf_hz(octaves) -> np.ndarray:
    """Coupure du filtre passe-bas : 602 Hz au réglage 25, 20 214 Hz au
    plus, 12 Hz au réglage 0. ``octaves`` : réglage et câbles additionnés."""
    return _tan_hz(2000000.0, octaves)


def hpf_hz(octaves) -> np.ndarray:
    """Coupure du filtre passe-haut : 805 Hz au réglage 25."""
    return _tan_hz(2672947.0, octaves)


def lfo_hz(octaves) -> np.ndarray:
    """Vitesse d'un LFO libre (et du mod FX) : 1,25 Hz au réglage 25, de
    0,005 à 320 Hz. L'incrément de phase vaut la valeur finale, sur 2³²."""
    final = 121739.0 * np.power(2.0, np.asarray(octaves, dtype=np.float64))
    return final * SAMPLE_RATE / float(1 << 32)


# --------------------------------------------------------------------------- #
# Enveloppes et glissé
# --------------------------------------------------------------------------- #

def attack_rate(octaves) -> np.ndarray:
    """Vitesse d'attaque du firmware (pas d'enveloppe par échantillon) :
    ``getExp(4096, −octaves)``. Au-delà de 245 632, l'attaque est sautée."""
    return 4096.0 * np.power(2.0, -np.asarray(octaves, dtype=np.float64))


def attack_seconds(octaves) -> np.ndarray:
    """Durée de l'attaque ; 0 quand le firmware la saute.

    ``octaves`` : réglage (×6) et câbles additionnés, **avant** la négation
    que le firmware applique aux attaques.
    """
    rate = attack_rate(octaves)
    seconds = _ENV_STEPS / np.maximum(rate, 1e-9) / SAMPLE_RATE
    return np.where(rate > _ATTACK_SKIP, 0.0, seconds)


def _release_rate(index) -> np.ndarray:
    """``lookupReleaseRate`` : interpolation dans la table, bornée."""
    i = np.clip(np.asarray(index, dtype=np.float64), 0.0, 64.0)
    return np.interp(i, np.arange(65, dtype=np.float64), _RELEASE)


def _rate_index(units) -> np.ndarray:
    """Indice dans la table des vitesses : 32 + 32 × (réglage et câbles, en
    unités de réglage)."""
    return 32.0 + 32.0 * np.asarray(units, dtype=np.float64)


def decay_rate(units) -> np.ndarray:
    """Vitesse du decay (``70 << 9`` × ``lookupReleaseRate``) ; ``units`` :
    réglage −1..+1 plus les câbles, en unités de réglage."""
    # ``multiply_32x32_rshift32`` tronque : au réglage 50, 3,83 devient 3.
    return np.floor((70 << 9) * _release_rate(_rate_index(units))
                    / float(1 << 32))


def release_rate(units) -> np.ndarray:
    """Vitesse du release (``140 << 9`` × ``lookupReleaseRate``)."""
    return np.floor((140 << 9) * _release_rate(_rate_index(units))
                    / float(1 << 32))


def decay_seconds(units) -> np.ndarray:
    """Durée complète du decay (``70 << 9`` × table) ; ``units`` : réglage
    −1..+1 plus les câbles, en unités de réglage."""
    return _ENV_STEPS / np.maximum(decay_rate(units), 1e-9) / SAMPLE_RATE


def release_seconds(units) -> np.ndarray:
    """Durée complète du release (``140 << 9`` × table)."""
    return _ENV_STEPS / np.maximum(release_rate(units), 1e-9) / SAMPLE_RATE


def glide_seconds(display) -> float:
    """Durée du glissé (``Voice::setupPorta`` : la table des vitesses, sur
    ``>> 13``) ; 0 quand il est coupé (réglage 0)."""
    if float(display) <= 0.0:
        return 0.0
    speed = float(_release_rate(_rate_index(unit(display)))) / 8192.0
    return _ENV_STEPS / max(speed, 1e-9) / SAMPLE_RATE


def attack_curve(x) -> np.ndarray:
    """Montée de l'attaque, ``x`` de 0 à 1 : ``1 − decayTableSmall4``."""
    x = np.clip(np.asarray(x, dtype=np.float64), 0.0, 1.0)
    return 1.0 - (np.power(2.0, 4.0 * (1.0 - x)) - 1.0) / 15.0


def decay_curve(x) -> np.ndarray:
    """Descente du decay et du release : ``decayTableSmall8``."""
    x = np.clip(np.asarray(x, dtype=np.float64), 0.0, 1.0)
    return (np.power(2.0, 8.0 * (1.0 - x)) - 1.0) / 255.0


# --------------------------------------------------------------------------- #
# Niveaux
# --------------------------------------------------------------------------- #

def volume_gain(factor) -> np.ndarray:
    """Gain d'un paramètre de volume, relatif au réglage 25 :
    ``getFinalParameterValueVolume`` élève au carré. ``factor`` : produit
    du réglage ``1 + u`` et des câbles ``1 + v·a`` (0 à 4)."""
    f = np.clip(np.asarray(factor, dtype=np.float64), 0.0, 4.0)
    return f * f


def linear_level(factor) -> np.ndarray:
    """Valeur d'un paramètre linéaire, relative au réglage 25."""
    return np.clip(np.asarray(factor, dtype=np.float64), 0.0, 4.0)


def sustain_level(factor) -> np.ndarray:
    """Palier d'une enveloppe, 0 à 1 : linéaire, la moitié au réglage 25."""
    return np.clip(np.asarray(factor, dtype=np.float64) * 0.5, 0.0, 1.0)


def ladder_resonance(factor) -> np.ndarray:
    """Résonance « traitée » du filtre en échelle, 0 à 1
    (``LpLadderFilter::setConfig``, échelle froide 12/24 dB).

    La valeur finale vaut ``factor × 25 × 10737418`` ; elle est plafonnée à
    510 000 000, puis ``r = 1 − 4x/2³¹`` est élevée au carré.
    """
    final = np.clip(np.asarray(factor, dtype=np.float64), 0.0, 4.0) \
        * 25.0 * 10737418.0
    r = 1.0 - np.minimum(final, 510000000.0) * 4.0 / float(1 << 31)
    return np.clip(1.0 - r * r, 0.0, 1.0)


# --------------------------------------------------------------------------- #
# Sources et câbles
# --------------------------------------------------------------------------- #

def velocity_source(velocity) -> np.ndarray:
    """Source *velocity*, −1..+1 : ``(vélocité − 64) / 64`` (128 = +1)."""
    v = np.asarray(velocity, dtype=np.float64)
    return np.clip((v - 64.0) / 64.0, -1.0, 1.0)


def note_source(note) -> np.ndarray:
    """Source *note*, −1..+1 : ``(note − 64) / 64``."""
    return np.clip((np.asarray(note, dtype=np.float64) - 64.0) / 64.0,
                   -1.0, 1.0)


def envelope_source(level) -> np.ndarray:
    """Source *envelope*, −1..+1, depuis le niveau 0..1 de l'enveloppe :
    ``Envelope::render`` centre sa sortie autour de 0."""
    return np.asarray(level, dtype=np.float64) * 2.0 - 1.0


def to_polarity(value, source: str, polarity: str = ""):
    """``PatchCable::toPolarity`` : un câble unipolaire ramène sa source
    bipolaire dans 0..1. L'aftertouch, lui, est stocké unipolaire."""
    pol = str(polarity or "").lower()
    if source == "aftertouch":
        return value if pol != "bipolar" else (np.asarray(value) * 2.0 - 1.0)
    if pol == "unipolar":
        return np.asarray(value) * 0.5 + 0.5
    return value


def cable_strength(amount: int) -> float:
    """Force d'un câble, −1..+1 : pleine échelle ``0x40000000``."""
    return max(-1.0, min(1.0, float(amount) / float(1 << 30)))


def cable_octaves(value, strength: float, destination: str,
                  source: str = "") -> np.ndarray:
    """Ce qu'un câble ajoute à un paramètre exponentiel, en octaves.

    ``v · a · 8`` en général ; vers une hauteur ou le temps du delay, la
    force est élevée au carré (``getModifiedPatchCableAmount``), soit
    ``v · a·|a| · 4`` — et vers la hauteur générale, multipliée par
    ``1/√2`` (« 3 octaves plutôt que 4 »), ou par ``2/3`` depuis la
    vélocité.
    """
    v = np.asarray(value, dtype=np.float64)
    a = float(strength)
    if destination in ("pitch", "oscAPitch", "oscBPitch", "modulator1Pitch",
                       "modulator2Pitch", "delayRate"):
        out = v * a * abs(a) * 4.0
        if destination == "pitch":
            out = out * ((2.0 / 3.0) if source == "velocity"
                         else 1518500250.0 / float(1 << 31))
        return out
    return v * a * 8.0


def cable_factor(value, strength: float) -> np.ndarray:
    """Facteur qu'un câble applique à un paramètre linéaire ou de volume :
    ``1 + v · a`` (``cableToLinearParam``)."""
    return np.clip(1.0 + np.asarray(value, dtype=np.float64) * float(strength),
                   0.0, 2.0)


def unison_cents(detune: int, voices: int) -> list[float]:
    """Désaccord de chaque voix d'unisson, en cents : réparti également de
    −désaccord/2 à +désaccord/2 (``Sound::setupUnisonDetuners``)."""
    n = max(1, int(voices))
    if n < 2:
        return [0.0]
    d = float(max(0, int(detune)))
    return [-d / 2.0 + d * u / (n - 1.0) for u in range(n)]
