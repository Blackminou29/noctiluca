# -*- coding: utf-8 -*-
"""Le traitement du signal du Deluge, porté de son firmware.

Le moteur d'écoute (:mod:`delugeapp.core.render`) approchait chaque étage :
tables d'onde normalisées, filtre à deux pôles appliqué par blocs FFT,
réverbération par une réponse impulsionnelle inventée. L'utilisateur l'a
entendu le 23 octobre 2026 : ses sons, écoutés sur le PC, gardaient un air
de famille avec le Deluge, sans en avoir le grain. Ce module reprend, étage
par étage, ce que calcule **le firmware de sa machine** (communautaire 1.3,
commit ``102cf9f``) :

* ``dsp/oscillators/`` — les tables de formes d'onde, leur choix selon la
  hauteur (``getTableNumber``), les ondes « crues » des notes graves, la
  largeur d'impulsion (produit de deux carrés, ou synchronisation interne
  pour les autres formes), le sinus de la FM et sa rétroaction ;
* ``dsp/filter/`` — l'échelle à transistors 12 et 24 dB, la version
  « drive », le passe-haut en échelle : les mêmes équations, échantillon par
  échantillon, avec la gigue de coupure et les compensations de niveau ;
* ``util/functions.h`` — les saturations ``getTanHUnknown`` et
  ``getTanHAntialiased``, le panoramique linéaire ;
* ``model/sample/`` et ``dsp/interpolate/`` — la lecture des échantillons :
  telle quelle à leur hauteur, sinon par sinus cardinal fenêtré à 16 points,
  le noyau choisi selon la transposition ;
* ``modulation/envelope.cpp`` et ``lfo.h`` — enveloppes et LFO calculés
  une fois par bloc de 128 échantillons, comme sur la machine ;
* ``model/mod_controllable/`` — réduction d'échantillonnage et de
  résolution, chorus, flanger, phaser, égaliseur ;
* ``dsp/delay/`` — le delay, numérique ou analogique, en ping-pong ;
* ``dsp/reverb/`` — les réverbérations « Mutable » (celle d'un morceau
  neuf) et Freeverb (celle des morceaux enregistrés sans modèle).

**Convention numérique.** Les signaux sont des tableaux ``float64`` à
**l'échelle des entiers du firmware** : la pleine échelle vaut ±2³¹. Les
formules se lisent donc à côté du code C : ``multiply_32x32_rshift32(a, b)``
s'écrit ``a * b / 2³²``. Les arrondis entiers ne sont pas reproduits — ils
ne s'entendent pas —, mais les seuils, les saturations et les rapports de
niveau le sont, parce qu'eux s'entendent. Sauf pour la hauteur, calculée en
entiers comme sur la machine : une erreur d'un dixième de cent s'y accumule
note après note en dérive de phase.

**Vérifié sur la machine** (23 octobre 2026, export de pistes d'un morceau
d'essai de douze sons) : niveaux à 0,1 dB près ; sinus, impulsion, FM,
unisson, kit et échantillons identiques à l'échantillon près (−69 à
−81 dB d'écart pendant la note) ; filtres et saturation au spectre près (±0,5 dB par
harmonique), leur forme d'onde différant autant que deux rendus de la
machine entre eux — la gigue de coupure est tirée au hasard. Le 4 novembre,
avec Song FX : réverbération à 0,2 dB près, sortie à 0,01 dB
(:func:`output_stage`). L'export rend
par fenêtres de 32 échantillons, le jeu direct par fenêtres de 128 au plus :
ce module en prend 128 (:data:`BLOCK`).

**Tables.** Les formes d'onde « analogiques » ont été relevées par
Synthstrom sur deux synthétiseurs ; elles ne se recalculent pas. Elles sont
copiées du firmware (``util/lookuptables/``, et les noyaux de
``dsp/interpolate/interpolate.cpp``) dans
``delugeapp/data/deluge_tables.npz`` (85 tables, 271 Ko). Le firmware est
publié sous licence GPL 3 : distribuer l'application avec ces tables
obligerait à la publier sous la même licence.

**Vitesse.** Les récurrences — échelles, phaser, flanger, rétroaction de la
FM, réverbérations — se calculent échantillon par échantillon : rien ne s'y
vectorise sans changer le calcul. En Python pur, écouter une section de huit
mesures à l'atelier demandait 2,5 à 9 s (4 novembre 2026). Chacune de ces
boucles est donc écrite une fois, dans un Python que **numba** sait compiler
(:class:`_Boucle`) : avec lui, elle tourne en code machine et laisse les
autres fils calculer pendant ce temps ; sans lui, la même fonction tourne en
Python, comme avant.

Dépend de numpy, et de numba s'il est installé. Module de calcul : ni carte,
ni audio, ni Qt.
"""

from __future__ import annotations

import array
import logging
import math
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

#: Fréquence d'échantillonnage du Deluge.
SR = 44100

#: Taille d'un bloc de rendu (``SSI_TX_BUFFER_NUM_SAMPLES``) : paramètres,
#: enveloppes et LFO sont recalculés une fois par bloc.
BLOCK = 128

#: Pleine échelle d'un entier signé 32 bits, et 2³².
Q31 = float(1 << 31)
Q32 = float(1 << 32)
MASK32 = (1 << 32) - 1

#: Ajouté à l'entrée des boucles échantillon par échantillon : dans le
#: silence, les mémoires d'un filtre décroissent jusqu'aux nombres
#: sous-normaux, que le processeur calcule cent fois plus lentement — un
#: passe-bas qui s'éteint coûtait le double. Mille fois sous le bit de poids
#: faible du firmware, qui travaille en entiers et ne connaît pas ce défaut.
DENORMAL_GUARD = 1e-3

_DATA = Path(__file__).resolve().parent.parent / "data" / "deluge_tables.npz"


@lru_cache(maxsize=1)
def _tables() -> dict[str, np.ndarray]:
    with np.load(_DATA) as data:
        return {name: data[name].astype(np.float64) for name in data.files}


def table(name: str) -> np.ndarray:
    """Une table du firmware, en flottants (``tanHSmall``, ``sawWave215``…)."""
    return _tables()[name]


def _buffer(n: int) -> array.array:
    """Un tampon de ``n`` flottants pour les boucles échantillon par
    échantillon : numpy le relit sans copie (:func:`_as_array`), là où une
    liste coûte une conversion de plus."""
    return array.array("d", bytes(8 * int(n)))


def _as_array(buf: array.array) -> np.ndarray:
    return np.frombuffer(buf, dtype=np.float64)


# --------------------------------------------------------------------------- #
# Boucles compilées
# --------------------------------------------------------------------------- #

#: ``None`` tant que la question ne s'est pas posée (:func:`compiled`) ;
#: puis vrai tant que les boucles passent par numba — faux s'il n'est pas
#: installé, ou dès qu'une compilation a échoué.
_compiled: bool | None = None
_numba = None
_JIT_LOCK = threading.Lock()


def compiled() -> bool:
    """Les boucles échantillon par échantillon tournent-elles compilées ?

    numba ne s'importe qu'à la première question, donc au premier calcul :
    une demi-seconde, que le tracé d'un filtre, dans le fil de
    l'interface, n'a pas à payer."""
    global _compiled, _numba
    if _compiled is None:
        with _JIT_LOCK:
            if _compiled is None:
                try:
                    import numba
                except Exception:  # noqa: BLE001 - absent, ou incompatible
                    numba = None
                _numba = numba
                _compiled = numba is not None
    return _compiled


def _jit(fn):
    """La version compilée de ``fn``, gardée sur disque à côté du module :
    numba ne la recompile qu'après une modification du fichier."""
    try:
        return _numba.njit(cache=True, nogil=True)(fn)
    except RuntimeError:  # aucun dossier où garder le code compilé
        return _numba.njit(nogil=True)(fn)


class _Boucle:
    """Une boucle échantillon par échantillon.

    Avec numba, elle est compilée au premier appel et rend la main aux
    autres fils pendant qu'elle tourne (``nogil``) : les voix d'une écoute
    se calculent alors en parallèle (:func:`.render.render_parts`). Sans
    numba, ou si la compilation échoue, ``py_func`` — la même fonction —
    tourne en Python ; ses tableaux lui arrivent en listes (:func:`_seq`),
    trois fois plus rapides à indexer qu'un tableau numpy.

    **En code compilé, un index hors du tableau ne lève rien : il lit
    n'importe où.** Chaque index tiré d'un signal y est donc borné, NaN
    compris (``not v <= borne``)."""

    def __init__(self, fn) -> None:
        self.py_func = fn
        self.__name__ = fn.__name__
        self.__doc__ = fn.__doc__
        self._compiled_fn = None

    def __call__(self, *args):
        global _compiled
        if compiled():
            fn = self._compiled_fn
            if fn is None:
                with _JIT_LOCK:
                    if self._compiled_fn is None:
                        self._compiled_fn = _jit(self.py_func)
                    fn = self._compiled_fn
            try:
                return fn(*args)
            except _numba.core.errors.NumbaError as exc:
                log.warning("boucle %s non compilée, calcul en Python : %s",
                            self.__name__, exc)
                _compiled = False
        return self.py_func(*args)


def _seq(values):
    """Les valeurs d'un signal pour une :class:`_Boucle` : un tableau
    contigu pour numba, une liste pour Python."""
    values = np.asarray(values, dtype=np.float64)
    return np.ascontiguousarray(values) if compiled() else values.tolist()


def _flags(values):
    """:func:`_seq` pour des booléens (un par bloc)."""
    values = np.asarray(values, dtype=np.bool_)
    return np.ascontiguousarray(values) if compiled() else values.tolist()


def _out(n: int):
    """Le tampon de sortie d'une :class:`_Boucle`."""
    return np.zeros(int(n)) if compiled() else _buffer(n)


def _zeros(n: int):
    """Un tampon de travail d'une :class:`_Boucle`, relu autant qu'écrit."""
    return np.zeros(int(n)) if compiled() else [0.0] * int(n)


def prepare(should_stop=None) -> bool:
    """Charge le code compilé de chaque boucle — ou le compile, après une
    modification de ce fichier —, en la faisant tourner sur deux blocs de
    silence, avec les types de l'écoute : rien de neuf ne se compile
    ensuite. À lancer dans un fil à part : la première écoute d'une session
    attendait ainsi une seconde de plus (import de numba compris), quatre
    après une modification. ``should_stop`` est consulté entre deux
    boucles. Rend faux sans numba, ou si l'arrêt a été demandé."""
    if not compiled():
        return False
    n, nb = 2 * BLOCK, 2
    silence = np.zeros(n)
    stereo = np.zeros((2, n))
    amp = np.ones(n)
    inc = np.full(nb, note_increment(57), dtype=np.int64)
    pulse = np.full(nb, 1 << 29, dtype=np.int64)
    rng = np.random.default_rng(0)
    steps = (
        lambda: lpf_process(silence, lpf_config("24dB", [2e6] * nb,
                                                [0.0] * nb),
                            ladder_jitter(n, rng)[0]),
        lambda: hpf_process(silence, hpf_config([2e6] * nb, [0.0] * nb)),
        lambda: oscillator("saw", inc, n, 0, amp, None, MASK32,
                           out=np.empty(n)),
        lambda: oscillator("square", inc, n, 0, amp, pulse),
        lambda: oscillator("sine", inc, n, 0, amp, pulse, 0),
        lambda: fm_operator(inc, n, 0, amp, None, np.full(nb, 1e8)),
        lambda: envelope_blocks(1000.0, 1000.0, 0.0, 1000.0, nb, 1, True),
        lambda: tanh_antialiased(silence, 5),
        lambda: mix_into(np.zeros(n), silence, 1.0),
        lambda: bitcrush_srr(stereo, -Q31, 0.0, 1.0),
        lambda: mod_fx(stereo, "phaser", 1.0, 1.0, 0.0, 0.0, 1.0),
        lambda: mod_fx(stereo, "flanger", 1.0, 1.0, 0.0, 0.0, 1.0),
        lambda: mod_fx(stereo, "chorus", 1.0, 1.0, 0.0, 0.0, 1.0),
        lambda: reverb(silence + 1.0, ReverbSettings()),
        lambda: one_pole(silence, 0.5),
    )
    for step in steps:
        if should_stop is not None and should_stop():
            return False
        step()
    return compiled()


def _result(buf) -> np.ndarray:
    """Un tampon de :func:`_out`, en tableau qui lui appartient."""
    if isinstance(buf, np.ndarray):
        return buf
    return _as_array(buf).copy()


# --------------------------------------------------------------------------- #
# Petites fonctions du firmware
# --------------------------------------------------------------------------- #

_TANH_X = np.linspace(-1.0, 1.0, 257)


def tanh_unknown(x, saturation: int):
    """``getTanHUnknown`` : la table ``tanHSmall`` (≈ tanh(4v)), lue en
    ``v = x·2^s / 2³¹`` borné à ±1, rendue sur ``2^(29−s)`` — gain unité
    pour un petit signal, plafond à ``2^(29−s)``."""
    s = int(saturation)
    v = np.clip(np.asarray(x, dtype=np.float64) * (2.0 ** s / Q31), -1.0, 1.0)
    scale = 65536.0 / 2.0 ** (s + 2)
    return np.interp(v, _TANH_X, table("tanHSmall")) * scale


def _tanh_list():
    """``tanHSmall`` ramenée à ±1, pour les boucles échantillon par
    échantillon, qui la lisent en ligne : ``p = (v + 1)·128``, puis
    interpolation entre ``tab[k]`` et ``tab[k + 1]``. ``math.tanh`` s'en
    écarte de 0,07 % ; près de l'auto-oscillation, l'écart grandissait
    jusqu'à 5 % de la crête. Un appel de fonction par échantillon, lui,
    coûtait autant que le filtre. Un tableau pour numba, une liste sinon."""
    return _tanh_table(compiled())


@lru_cache(maxsize=2)
def _tanh_table(as_array: bool):
    values = table("tanHSmall") / 32768.0
    return np.ascontiguousarray(values) if as_array else values.tolist()


def tanh_antialiased(x: np.ndarray, saturation: int,
                     last: float = Q31) -> tuple[np.ndarray, float]:
    """``getTanHAntialiased`` : la table ``tanH2d`` lue entre la valeur de
    travail de l'échantillon précédent et la courante — une tangente
    hyperbolique adoucie contre le repliement. Rend la sortie et la
    dernière valeur de travail (``2³¹`` = silence)."""
    s = int(saturation)
    x = np.asarray(x, dtype=np.float64)
    if x.size == 0:
        return x.copy(), last
    if compiled() and x.ndim == 1:
        out = np.empty(x.size)
        last = _tanh2d_loop(np.ascontiguousarray(x), 2.0 ** s, float(last),
                            _tanh_grid(), 32768.0 / 2.0 ** (s + 1), out)
        return out, last
    work = np.clip(x * 2.0 ** s, -Q31, Q31 - 1.0) + Q31
    prev = np.empty_like(work)
    prev[0] = last
    prev[1:] = work[:-1]
    grid = table("tanH2d")
    cx = work / float(1 << 25)
    ix = np.minimum(cx.astype(np.int64), 127)
    fx = cx - ix
    cy = prev / float(1 << 26)
    iy = np.minimum(cy.astype(np.int64), 63)
    fy = cy - iy
    v1 = grid[iy, ix] * (1.0 - fx) + grid[iy, ix + 1] * fx
    v2 = grid[iy + 1, ix] * (1.0 - fx) + grid[iy + 1, ix + 1] * fx
    out = (v1 * (1.0 - fy) + v2 * fy) * (32768.0 / 2.0 ** (s + 1))
    return out, float(work[-1])


@_Boucle
def _tanh2d_loop(x, gain, last, grid, scale, out):
    """:func:`tanh_antialiased` en une passe, sans ses neuf tableaux
    intermédiaires ; rend la dernière valeur de travail."""
    top, bottom = Q31 - 1.0, -Q31
    if not (last >= 0.0 and last <= Q32):
        last = Q31
    for i in range(len(x)):
        work = x[i] * gain
        work = top if not work <= top else (bottom if work < bottom else work)
        work += Q31
        cx = work / 33554432.0
        ix = int(cx)
        if ix > 127:
            ix = 127
        fx = cx - ix
        cy = last / 67108864.0
        iy = int(cy)
        if iy > 63:
            iy = 63
        fy = cy - iy
        v1 = grid[iy, ix] * (1.0 - fx) + grid[iy, ix + 1] * fx
        v2 = grid[iy + 1, ix] * (1.0 - fx) + grid[iy + 1, ix + 1] * fx
        out[i] = (v1 * (1.0 - fy) + v2 * fy) * scale
        last = work
    return last


def one_pole(x, k: float, y0: float = 0.0) -> tuple[np.ndarray, float]:
    """Filtre à un pôle ``y += k·(x − y)``, échantillon par échantillon,
    calculé d'un bloc : la récurrence est linéaire, une somme préfixe par
    doublements la résout en log₂(n) passes. Rend le signal et son dernier
    état. Agit sur le dernier axe."""
    x = np.asarray(x, dtype=np.float64)
    n = x.shape[-1]
    if n == 0:
        return x.copy(), float(y0)
    k = float(k)
    if compiled() and x.ndim == 1:
        # Compilée, la récurrence se calcule en une passe, sans les log₂(n)
        # passes d'un tableau entier : 2,2 s sur les 22 de quatre écoutes de
        # section, surtout dans la gigue des échelles.
        y = np.empty(n)
        return y, _one_pole_loop(np.ascontiguousarray(x), k, float(y0), y)
    a = 1.0 - k
    y = x * k
    shift, power = 1, a
    while shift < n and power != 0.0:
        y[..., shift:] += power * y[..., :-shift]
        power *= power
        shift *= 2
    if y0:
        y += y0 * a ** np.arange(1, n + 1, dtype=np.float64)
    return y, float(y[..., -1].ravel()[0]) if y.ndim == 1 else y[..., -1]


@_Boucle
def _one_pole_loop(x, k, y, out):
    """:func:`one_pole` échantillon par échantillon ; rend le dernier état."""
    for i in range(len(x)):
        y += k * (x[i] - y)
        out[i] = y
    return y


@lru_cache(maxsize=8)
def _one_pole_matrix(k: float, size: int = BLOCK
                     ) -> tuple[np.ndarray, np.ndarray]:
    """La matrice d'un filtre à un pôle sur ``size`` échantillons, et les
    puissances qui propagent l'état de départ."""
    a = 1.0 - k
    i = np.arange(size)
    diff = i[:, None] - i[None, :]
    matrix = np.where(diff >= 0, k * a ** np.maximum(diff, 0), 0.0)
    return matrix, a ** (i + 1.0)


def one_pole_short(x: np.ndarray, k: float, y0: np.ndarray
                   ) -> tuple[np.ndarray, np.ndarray]:
    """:func:`one_pole` pour quelques canaux et au plus 128 échantillons :
    un produit matriciel, bien plus rapide qu'une somme préfixe quand
    l'appel se répète bloc après bloc (le continu du delay)."""
    matrix, powers = _one_pole_matrix(float(k))
    c = x.shape[-1]
    y = x @ matrix[:c, :c].T + y0[:, None] * powers[None, :c]
    return y, y[:, -1].copy()


def mix_into(dest: np.ndarray, wave: np.ndarray, gain: float) -> None:
    """``dest += wave · gain``, sur place ; compilé, sans le tableau
    intermédiaire du produit."""
    if compiled() and dest.ndim == 1 and dest.flags.c_contiguous:
        _mix_loop(dest, np.ascontiguousarray(wave, dtype=np.float64),
                  float(gain))
    else:
        dest += wave * gain


@_Boucle
def _mix_loop(dest, wave, gain):
    for i in range(len(dest)):
        dest[i] += wave[i] * gain


def pan_amplitudes(pan) -> tuple[np.ndarray, np.ndarray]:
    """``shouldDoPanning`` : loi **linéaire**, ±2³⁰ pour un côté entier. Au
    centre, les deux voies gardent tout leur niveau ; d'un côté, l'autre
    voie descend seule. Rend les gains gauche et droit (1 = unité)."""
    p = np.clip(np.asarray(pan, dtype=np.float64) / float(1 << 30), -1.0, 1.0)
    right = np.where(p >= 0.0, 1.0, 1.0 + p)
    left = np.where(p <= 0.0, 1.0, 1.0 - p)
    return left, right


def get_exp(value, octaves):
    """``getExp`` : une octave par 2²⁶, saturé à 2³¹."""
    out = np.asarray(value, dtype=np.float64) \
        * np.power(2.0, np.asarray(octaves, dtype=np.float64))
    return np.minimum(out, Q31 - 1.0)


# --------------------------------------------------------------------------- #
# Hauteurs
# --------------------------------------------------------------------------- #

def note_increment(note_code: int) -> int:
    """Incrément de phase d'une note (``Voice::calculatePhaseIncrements``,
    oscillateur d'onde) : ``noteFrequencyTable >> (20 − octave)``, une
    phase de 2³² par période. 0 au-delà de 22 kHz."""
    n = int(note_code)
    within = (n + 236) % 12
    octave = (n + 116) // 12
    shift = 20 - octave
    if shift < 0:
        return 0
    if shift > 40:
        return 0
    return int(table("noteFrequencyTable")[within]) >> shift


def cents_factor(cents) -> float:
    """±50 cents, en facteur exact (le firmware passe par
    :func:`fine_tuner`)."""
    return float(2.0 ** (float(cents) / 1200.0))


#: Un cent de réglage fin, à l'échelle de ``PhaseIncrementFineTuner``.
CENT_SCALE = 42949672


def fine_tuner(scaled: int) -> int:
    """``PhaseIncrementFineTuner::setup`` : le multiplicateur d'un réglage
    fin (cents × :data:`CENT_SCALE`), lu dans ``centAdjustTableSmall`` —
    ±50 cents sur 257 points de 16 bits, interpolés en entiers. 2³⁰ à zéro.

    Mesuré sur la machine le 23 octobre 2026 : avec ``2^(c/1200)`` exact,
    les voix d'un unisson dérivaient lentement des siennes (−60 dB d'écart
    au départ d'une note, −28 dB une demi-seconde plus tard)."""
    tab = table("centAdjustTableSmall")
    x = (int(scaled) + (1 << 31)) & MASK32
    index = x >> 24
    strength = (x >> 9) & 32767
    return int(tab[index]) * (32768 - strength) \
        + int(tab[index + 1]) * strength


def fine_tune(increment: int, multiplier: int) -> int:
    """``PhaseIncrementFineTuner::detune`` : ``(incrément × multiplicateur)
    >> 32``, puis ``<< 2`` — même au réglage nul, les deux bits faibles
    tombent."""
    return ((int(increment) * int(multiplier)) >> 32) << 2


def unison_detuners(detune: int, voices: int) -> list[int]:
    """``Sound::setupUnisonDetuners`` : le multiplicateur de chaque voix
    d'unisson, de −désaccord/2 à +désaccord/2 en pas égaux ; la voix du
    milieu d'un nombre impair n'est pas désaccordée."""
    n = int(voices)
    if n < 2:
        return [1 << 30]
    scaled = int(detune) * CENT_SCALE
    lowest = -(scaled >> 1)
    spacing = scaled // (n - 1)
    return [(1 << 30) if (n & 1) and u == (n - 1) >> 1
            else fine_tuner(lowest + spacing * u) for u in range(n)]


def adjust_pitch(increment, adjustment) -> np.ndarray:
    """``Voice::adjustPitch`` : un incrément multiplié par un réglage de
    hauteur (2²⁴ = neutre, laissé tel quel), ``(a × b) >> 32`` arrondi puis
    ``<< 8``. Trop haut pour être rendu : 0."""
    inc = np.asarray(increment, dtype=np.int64)
    adj = np.broadcast_to(np.asarray(adjustment, dtype=np.int64), inc.shape)
    out = (inc * adj + (1 << 31)) >> 32
    return np.where(adj == SAMPLE_UNITY, inc,
                    np.where(out >= (1 << 23), 0, out << 8))


def pitch_adjustment(octaves) -> np.ndarray:
    """Un réglage de hauteur en octaves, à l'échelle de
    :func:`adjust_pitch` : 2²⁴ par octave nulle, doublé par octave."""
    octaves = np.asarray(octaves, dtype=np.float64)
    adj = np.round(float(SAMPLE_UNITY) * np.power(2.0, octaves))
    return np.where(octaves == 0.0, SAMPLE_UNITY,
                    np.clip(adj, 1.0, Q31 - 1.0)).astype(np.int64)


def sample_increment(note_code: int, sample_rate: int) -> int:
    """Incrément d'un échantillon pour une note (``calculatePhaseIncrements``,
    oscillateur ``sample``) : l'intervalle depuis le do 3 (60) dans
    ``noteIntervalTable``, sur l'incrément neutre du fichier
    (``(fréquence << 24) / 44 100``). 0 quand ce serait trop aigu."""
    n = int(note_code)
    within = (n + 240) % 12
    octave = (n + 120) // 12
    neutral = (int(sample_rate) << 24) // SR
    inc = (int(table("noteIntervalTable")[within]) * neutral) >> 32
    shift = 13 - octave
    if shift >= 0:
        return inc >> shift
    if inc >= (2026954652 >> -shift):
        return 0
    return inc << -shift


def unison_pans(spread: int, voices: int) -> list[int]:
    """``Sound::setupUnisonStereoSpread`` : les voix d'unisson réparties de
    −spread/2 à +spread/2, une sur deux retournée (−2 +1 0 −1 +2) ; ±2³⁰
    pour un côté entier."""
    n = int(voices)
    if n < 2:
        return [0]
    scaled = int(spread) * 42949672
    lowest = -(scaled >> 1)
    spacing = scaled // (n - 1)
    pans = []
    for u in range(n):
        sign = -1 if (min(u, n - 1 - u) & 1) else 1
        pans.append(sign * (lowest + spacing * u))
    return pans


# --------------------------------------------------------------------------- #
# Oscillateurs
# --------------------------------------------------------------------------- #

#: ``getTableNumber`` (``basic_waves.cpp``) : la table d'une hauteur est
#: celle dont la borne d'incrément est la première à ne pas être dépassée.
_TABLE_LIMITS = np.array([
    1247086, 1764571, 2494173, 3526245, 4982560, 7040929, 9988296, 14035840,
    19701684, 28256363, 40518559, 55063683, 79536431, 113025455, 165191049,
    238609294, 306783378, 429496729, 715827882], dtype=np.int64)

_HARMONICS = (215, 153, 109, 76, 53, 39, 27, 19, 13, 9, 7, 5, 3, 1)
_SAW_TABLES = (None,) * 6 + tuple("sawWave%d" % h for h in _HARMONICS)
_SQUARE_TABLES = (None,) * 6 + tuple("squareWave%d" % h for h in _HARMONICS)
_ANALOG_SQUARE_TABLES = tuple("analogSquare_%d" % h for h in (
    1722, 1217, 861, 609, 431, 305) + _HARMONICS)
#: Les huit premières tables viennent d'un premier synthétiseur, les
#: suivantes d'un second (``analogSawTables``).
_ANALOG_SAW_TABLES = tuple("mysterySynthASaw_%d" % h for h in (
    1722, 1217, 861, 609, 431, 305, 215, 153)) + tuple(
    "mysterySynthBSaw_%d" % h for h in _HARMONICS[2:])

#: Sous cet incrément, le triangle est calculé « cru », sans table.
_TRIANGLE_CRUDE = 69273666


def table_numbers(increments) -> np.ndarray:
    """``getTableNumber`` pour un tableau d'incréments."""
    increments = np.asarray(increments, dtype=np.int64)
    return np.searchsorted(_TABLE_LIMITS, increments, side="left")


def _triangle_table(inc: int) -> str:
    """La table anti-repliement d'un triangle aigu."""
    if inc <= 102261126:
        return "triangleWaveAntiAliasing21"
    if inc <= 143165576:
        return "triangleWaveAntiAliasing15"
    if inc <= 238609294:
        return "triangleWaveAntiAliasing9"
    if inc <= 429496729:
        return "triangleWaveAntiAliasing5"
    if inc <= 715827882:
        return "triangleWaveAntiAliasing3"
    return "triangleWaveAntiAliasing1"


def _magnitude(tab: np.ndarray) -> int:
    return int(round(math.log2(tab.size - 1)))


def _read_table(tab: np.ndarray, phase: np.ndarray) -> np.ndarray:
    """``waveRenderingFunctionGeneral`` : lecture interpolée (fraction sur
    15 bits), rendue sur ``valeur × 65536``."""
    mag = _magnitude(tab)
    if compiled() and phase.ndim == 1:
        out = np.empty(phase.size)
        _table_read(tab, np.ascontiguousarray(phase, dtype=np.int64),
                    32 - mag, 16 - mag, out)
        return out
    index = phase >> (32 - mag)
    frac = ((phase >> (16 - mag)) & 0xFFFF) >> 1
    v1 = tab[index]
    return v1 * 65536.0 + 2.0 * (tab[index + 1] - v1) * frac


@_Boucle
def _table_read(tab, phase, shift_index, shift_frac, out):
    """:func:`_read_table` d'une passe."""
    top = len(tab) - 2
    for i in range(len(phase)):
        p = phase[i]
        index = p >> shift_index
        if index < 0:
            index = 0
        elif index > top:
            index = top
        frac = ((p >> shift_frac) & 0xFFFF) >> 1
        v1 = tab[index]
        out[i] = v1 * 65536.0 + 2.0 * (tab[index + 1] - v1) * frac


def _read_pulse(tab: np.ndarray, half_phase: np.ndarray,
                to_add: int) -> np.ndarray:
    """``waveRenderingFunctionPulse`` : le produit de deux carrés lus à
    demi-vitesse, décalés de la largeur d'impulsion. Comme le firmware, la
    fraction d'interpolation ne garde que ses 15 bits bas."""
    mag = _magnitude(tab)
    shift = 16 - mag
    index_a = half_phase >> (32 - mag)
    frac_a = (half_phase >> shift) & 0x7FFF
    out_a = -2.0 * (frac_a * tab[index_a + 1]
                    + (32768 - frac_a) * tab[index_a])
    later = (half_phase + to_add) & MASK32
    index_b = later >> (32 - mag)
    frac_b = (later >> shift) & 0x7FFF
    out_b = 2.0 * (frac_b * tab[index_b + 1]
                   + (32767 - frac_b) * tab[index_b])
    return np.round(2.0 * out_a * out_b / Q32) * 2.0


def _signed(phase: np.ndarray) -> np.ndarray:
    """Une phase lue en entier signé 32 bits."""
    signed = np.where(phase >= (1 << 31), phase - (1 << 32), phase)
    return signed.astype(np.float64)


def _crude_triangle(phase: np.ndarray) -> np.ndarray:
    """``getTriangleSmall`` : de −2³⁰ à +2³⁰ et retour."""
    folded = np.where(phase >= (1 << 31), (1 << 32) - phase, phase)
    return (folded - (1 << 30)).astype(np.float64)


@dataclass
class _Reader:
    """Comment un bloc lit sa forme d'onde : ``mode`` (``saw``, ``square``,
    ``triangle`` pour les ondes crues, ``table``, ``pulse``), la table, et
    les deux échelles du firmware — ``gain`` avec amplitude, ``raw`` sans
    (modulation en anneau)."""

    mode: str
    name: str | None
    gain: float
    raw: float


_CRUDE_SAW = _Reader("saw", None, 1.0 / Q32, 0.5)
_CRUDE_SQUARE = _Reader("square", None, 1.0 / Q32, 0.5)
_CRUDE_TRIANGLE = _Reader("triangle", None, 2.0 / Q32, 2.0)


def _reader(kind: str, inc: int, pulse: int, pw_sync: bool) -> _Reader:
    """La forme lue par un bloc (``Oscillator::renderOsc``)."""
    if kind == "sine":
        return _Reader("table", "sineWaveSmall", 1.0 / Q32, 1.0)
    if kind == "triangle":
        if inc < _TRIANGLE_CRUDE:
            return _CRUDE_TRIANGLE
        return _Reader("table", _triangle_table(inc), 1.0 / Q32, 1.0)
    if kind == "square":
        do_pulse = pulse != 0
        number = int(table_numbers(int(inc * 0.6) if do_pulse else inc))
        if number < 6:
            return _CRUDE_SQUARE
        if do_pulse:
            return _Reader("pulse", _SQUARE_TABLES[number], 2.0 / Q32, 1.0)
        return _Reader("table", _SQUARE_TABLES[number], 2.0 / Q32, 1.0)
    number = int(table_numbers(inc))
    if kind == "analogSaw":
        return _Reader("table", _ANALOG_SAW_TABLES[number], 2.0 / Q32, 1.0)
    if kind == "analogSquare":
        return _Reader("table", _ANALOG_SQUARE_TABLES[number], 2.0 / Q32, 1.0)
    # Dent de scie (et forme inconnue).
    if number < 6:
        return _CRUDE_SAW
    return _Reader("table", _SAW_TABLES[number], 2.0 / Q32, 1.0)


def _wave(reader: _Reader, phase: np.ndarray, pulse_width=0) -> np.ndarray:
    """Les valeurs d'onde d'un lecteur, avant amplitude ; ``pulse_width`` :
    un entier, ou un par échantillon."""
    if reader.mode == "saw":
        return _signed(phase)
    if reader.mode == "square":
        width = (np.asarray(pulse_width, dtype=np.int64) + (1 << 31)) & MASK32
        return np.where(phase < width, Q31 - 1.0, -Q31)
    if reader.mode == "triangle":
        return _crude_triangle(phase)
    tab = table(reader.name)
    if reader.mode == "pulse":
        width = (np.asarray(pulse_width, dtype=np.int64) + (1 << 31)) & MASK32
        return _read_pulse(tab, phase >> 1, (-(width >> 1)) & MASK32)
    return _read_table(tab, phase)


def oscillator(kind: str, inc_blocks, n: int, phase0: int,
               amp: np.ndarray | None = None, pulse_blocks=None,
               retrig: int = MASK32, out: np.ndarray | None = None
               ) -> tuple[np.ndarray, int]:
    """Une voix d'oscillateur (``Oscillator::renderOsc``), bloc par bloc.

    :param kind: ``sine``, ``triangle``, ``square``, ``saw``,
        ``analogSaw`` ou ``analogSquare``.
    :param inc_blocks: incrément de phase de chaque bloc (0 : bloc muet,
        trop aigu pour être rendu).
    :param phase0: phase de départ, sur 2³².
    :param amp: amplitude de chaque échantillon (rampe du firmware) ;
        ``None`` rend l'onde brute, comme pour la modulation en anneau.
    :param pulse_blocks: largeur d'impulsion de chaque bloc (``int32``,
        ``lshiftAndSaturate<1>`` déjà appliqué).
    :param retrig: phase de redémarrage (``retrigPhase``), utile à la
        synchronisation interne ; ``0xFFFFFFFF`` quand elle est coupée.
    :param out: ``n`` flottants à remplir au lieu d'un tableau neuf : passé
        d'une voix d'unisson à la suivante, il épargne à chacune la
        mémoire fraîche d'un tableau de la longueur de la note.

    La largeur d'impulsion d'un carré multiplie deux carrés décalés ; celle
    des autres formes passe par une **synchronisation** : l'onde court
    ``1 + largeur`` fois plus vite (moins vite pour le carré analogique) et
    repart à chaque période, l'échantillon du saut fondu en sinus
    (``renderOscSync``). Rend le signal et la phase finale.
    """
    inc_blocks = np.asarray(inc_blocks, dtype=np.int64)
    nb = inc_blocks.size
    if pulse_blocks is None:
        pulse_blocks = np.zeros(nb, dtype=np.int64)
    pulse_blocks = np.asarray(pulse_blocks, dtype=np.int64)
    if compiled():
        # Les boucles des tables calculent leurs phases, d'après celle du
        # début de chaque bloc. Les autres formes demanderont les tableaux
        # entiers de phases et d'incréments : chaque tableau neuf de la
        # longueur d'une note coûte, sous Windows, de la mémoire fraîche, que
        # les fils de l'écoute se disputent.
        inc = phase = None
        starts = np.empty(inc_blocks.size, dtype=np.int64)
        _block_starts(inc_blocks, int(phase0) & MASK32, starts)
    else:
        inc = np.repeat(inc_blocks, BLOCK)[:n]
        phase = (int(phase0) + np.cumsum(inc)) & MASK32
    if out is None:
        out = np.zeros(n, dtype=np.float64)
    else:
        out.fill(0.0)
    end_phase = int((int(phase0) + int(inc_blocks.sum()) * BLOCK) & MASK32)
    if n == 0:
        return out, end_phase

    sync_kind = kind not in ("square",)
    groups: dict[tuple, tuple[_Reader, list[np.ndarray]]] = {}
    for blocks, step, pulse in _block_signatures(kind, inc_blocks,
                                                 pulse_blocks):
        pw_sync = sync_kind and pulse != 0
        if pw_sync and kind == "triangle":
            # Le triangle choisit sa table d'après l'incrément accéléré.
            p = abs(pulse) / Q31
            reader = _reader(kind, int(step * (1.0 + p)), pulse, True)
        else:
            reader = _reader(kind, step, pulse, pw_sync)
        key = (reader.mode, reader.name, pw_sync)
        groups.setdefault(key, (reader, []))[1].append(blocks)

    within = np.arange(BLOCK, dtype=np.int64)
    for (_mode, _name, pw_sync), (reader, parts) in groups.items():
        blocks = parts[0] if len(parts) == 1 \
            else np.sort(np.concatenate(parts))
        if compiled() and not pw_sync and reader.mode in ("table", "pulse"):
            # Les cas courants, d'une seule passe : lecture, amplitude,
            # écriture.
            tab = table(reader.name)
            mag = _magnitude(tab)
            amp_or_none = _NO_AMP if amp is None else amp
            scale = reader.raw if amp is None else reader.gain
            if reader.mode == "table":
                _table_osc(tab, starts, inc_blocks, blocks, amp_or_none,
                           scale, 32 - mag, 16 - mag, out)
            else:
                _pulse_osc(tab, starts, inc_blocks, blocks, pulse_blocks,
                           amp_or_none, scale, mag, out)
            continue
        if phase is None:
            phase = np.zeros(n, dtype=np.int64)
            _phase_loop(inc_blocks, int(phase0) & MASK32, phase)
        # Les échantillons du groupe, bloc par bloc : un masque de toute la
        # longueur par groupe coûtait n × blocs quand la largeur bouge.
        idx = (np.asarray(blocks, dtype=np.int64)[:, None] * BLOCK
               + within[None, :]).ravel()
        idx = idx[idx < n]
        if idx.size == 0:
            continue
        if not pw_sync:
            widths = np.repeat(pulse_blocks[blocks], BLOCK)[:idx.size] \
                if reader.mode in ("square", "pulse") else 0
            values = _wave(reader, phase[idx], widths)
        else:
            if inc is None:
                inc = np.repeat(inc_blocks, BLOCK)[:n]
            values = _synced_wave(kind, reader, phase, inc, idx,
                                  pulse_blocks, int(retrig))
        scale = reader.raw if amp is None else reader.gain
        if amp is None:
            out[idx] = values * scale
        else:
            out[idx] = values * amp[idx] * scale
    return out, end_phase


_NO_AMP = np.zeros(0)


@_Boucle
def _phase_loop(inc_blocks, phase, out):
    """La phase de chaque échantillon d'un oscillateur, sur 2³², après celle
    de départ."""
    n = len(out)
    for b in range(len(inc_blocks)):
        step = inc_blocks[b]
        for i in range(b * BLOCK, min(n, (b + 1) * BLOCK)):
            phase = (phase + step) & MASK32
            out[i] = phase


@_Boucle
def _block_starts(inc_blocks, phase, out):
    """La phase d'un oscillateur au début de chaque bloc, sur 2³²."""
    for b in range(len(inc_blocks)):
        out[b] = phase
        phase = (phase + inc_blocks[b] * BLOCK) & MASK32


@_Boucle
def _table_osc(tab, starts, inc_blocks, blocks, amp, scale, shift_index,
               shift_frac, out):
    """:func:`_read_table` sur les blocs ``blocks`` d'un oscillateur,
    multipliée par l'amplitude (aucune si ``amp`` est vide) et l'échelle,
    écrite dans ``out``. Chaque échantillon avance la phase avant d'être
    lu, comme la somme cumulée du calcul en Python."""
    n = len(out)
    top = len(tab) - 2
    with_amp = len(amp) > 0
    for j in range(len(blocks)):
        b = blocks[j]
        p = starts[b]
        step = inc_blocks[b]
        for i in range(b * BLOCK, min(n, (b + 1) * BLOCK)):
            p = (p + step) & MASK32
            index = p >> shift_index
            if index < 0:
                index = 0
            elif index > top:
                index = top
            frac = ((p >> shift_frac) & 0xFFFF) >> 1
            v1 = tab[index]
            v = v1 * 65536.0 + 2.0 * (tab[index + 1] - v1) * frac
            if with_amp:
                out[i] = v * amp[i] * scale
            else:
                out[i] = v * scale


@_Boucle
def _pulse_osc(tab, starts, inc_blocks, blocks, pulse_blocks, amp, scale,
               mag, out):
    """:func:`_read_pulse` sur les blocs ``blocks`` d'un carré à largeur
    d'impulsion, multipliée par l'amplitude (aucune si ``amp`` est vide) et
    l'échelle, écrite dans ``out``."""
    n = len(out)
    top = len(tab) - 2
    with_amp = len(amp) > 0
    shift = 16 - mag
    shift_index = 32 - mag
    for j in range(len(blocks)):
        b = blocks[j]
        p = starts[b]
        step = inc_blocks[b]
        width = (pulse_blocks[b] + (1 << 31)) & MASK32
        to_add = (-(width >> 1)) & MASK32
        for i in range(b * BLOCK, min(n, (b + 1) * BLOCK)):
            p = (p + step) & MASK32
            half = p >> 1
            index = half >> shift_index
            if index < 0:
                index = 0
            elif index > top:
                index = top
            frac = (half >> shift) & 0x7FFF
            out_a = -2.0 * (frac * tab[index + 1] + (32768 - frac) * tab[index])
            later = (half + to_add) & MASK32
            index = later >> shift_index
            if index < 0:
                index = 0
            elif index > top:
                index = top
            frac = (later >> shift) & 0x7FFF
            out_b = 2.0 * (frac * tab[index + 1] + (32767 - frac) * tab[index])
            v = np.rint(2.0 * out_a * out_b / Q32) * 2.0
            if with_amp:
                out[i] = v * amp[i] * scale
            else:
                out[i] = v * scale


#: Les seuils de :func:`_triangle_table`.
_TRIANGLE_LIMITS = np.array([102261126, 143165576, 238609294, 429496729,
                             715827882], dtype=np.int64)


def _block_signatures(kind: str, inc_blocks: np.ndarray,
                      pulse_blocks: np.ndarray) -> list:
    """Les blocs sonores d'un oscillateur, rangés par forme lue.

    La forme d'un bloc (:func:`_reader`) ne dépend de son incrément que par
    la table qu'il choisit, et de sa largeur d'impulsion que par sa
    présence : un numéro par bloc, calculé d'un coup. Rend, par numéro, les
    blocs, l'incrément et la largeur du premier — de quoi appeler
    :func:`_reader` une fois par numéro et non par bloc, car avec un
    vibrato ou une largeur modulée, chaque bloc a son incrément."""
    pw = pulse_blocks != 0
    if kind == "triangle":
        eff = np.where(pw, (inc_blocks * (1.0 + np.abs(pulse_blocks) / Q31))
                       .astype(np.int64), inc_blocks)
        number = np.where(eff < _TRIANGLE_CRUDE, 0, 1 + np.searchsorted(
            _TRIANGLE_LIMITS, eff, side="left"))
    elif kind == "square":
        number = table_numbers(np.where(
            pw, (inc_blocks * 0.6).astype(np.int64), inc_blocks))
    elif kind == "sine":
        number = np.zeros(inc_blocks.size, dtype=np.int64)
    else:
        number = table_numbers(inc_blocks)
    signature = np.where(inc_blocks > 0, number * 2 + pw, -1)
    values, first, inverse = np.unique(signature, return_index=True,
                                       return_inverse=True)
    out = []
    for u, (value, b) in enumerate(zip(values.tolist(), first.tolist())):
        if value >= 0:
            out.append((np.nonzero(inverse.ravel() == u)[0],
                        int(inc_blocks[b]), int(pulse_blocks[b])))
    return out


def _synced_wave(kind: str, reader: _Reader, phase: np.ndarray,
                 inc: np.ndarray, idx: np.ndarray, pulse_blocks: np.ndarray,
                 retrig: int) -> np.ndarray:
    """La largeur d'impulsion des formes autres que le carré : une
    synchronisation sur la phase de l'oscillateur (``renderOsc``, branche
    ``doPulseWave``)."""
    pulse = np.repeat(pulse_blocks, BLOCK)[:phase.size][idx]
    p = np.minimum(np.abs(pulse).astype(np.float64), Q31) / Q31
    offset = {"saw": 1 << 31, "sine": -(3 << 30)}.get(kind, 0)
    extra = {"saw": 1 << 31, "sine": 3 << 30}.get(kind, 0)
    start = (retrig + extra) & MASK32
    resetter = (phase[idx] + offset) & MASK32
    step = inc[idx]
    if kind == "analogSquare":
        ratio = 1.0 / (1.0 + p)
    else:
        ratio = 1.0 + p
    synced = (start + np.floor(resetter * ratio).astype(np.int64)) & MASK32
    values = _wave(reader, synced)
    if reader.mode != "table":
        # Les ondes crues repartent sèchement.
        return values

    # Le saut : l'échantillon le plus proche est fondu entre l'ancienne et
    # la nouvelle période, selon où tombe le saut (``renderOscSync``).
    wrapped = np.nonzero(resetter < step)[0]
    if wrapped.size == 0:
        return values
    frac = resetter[wrapped] / np.maximum(step[wrapped], 1)
    cycle = np.floor(Q32 * ratio[wrapped]).astype(np.int64)
    sync_step = np.floor(step[wrapped] * ratio[wrapped]).astype(np.int64)
    late = frac < 0.5
    # Saut juste avant l'échantillon : on fond celui-ci.
    w = wrapped[late]
    if w.size:
        old = _wave(reader, (synced[w] + cycle[late]) & MASK32)
        values[w] = _blend(old, values[w], frac[late])
    # Saut juste après l'échantillon précédent : on fond celui-là.
    early = ~late
    w = wrapped[early] - 1
    keep = w >= 0
    if np.any(keep):
        w = w[keep]
        new = _wave(reader, (synced[wrapped[early][keep]]
                             - sync_step[early][keep]) & MASK32)
        values[w] = _blend(values[w], new, frac[early][keep] - 1.0)
    return values


def _blend(old: np.ndarray, new: np.ndarray, fade: np.ndarray) -> np.ndarray:
    """Le fondu du saut : moitié-moitié au saut même, tout l'un ou tout
    l'autre à un demi-échantillon (``getSine(fade >> 1)``)."""
    weight = np.sin(np.pi * np.clip(fade, -0.5, 0.5))
    return 0.5 * (old + new) + 0.5 * (new - old) * weight


# --------------------------------------------------------------------------- #
# FM
# --------------------------------------------------------------------------- #

def _sine(phase: np.ndarray) -> np.ndarray:
    """``SineOsc`` : le sinus de 256 points et sa différence, sur 2³¹."""
    tab = table("sineWaveSmall")
    index = phase >> 24
    frac = (phase >> 8) & 0xFFFF
    v1 = tab[index]
    return v1 * 65536.0 + (tab[index + 1] - v1) * frac


def fm_operator(inc_blocks, n: int, phase0: int, amp: np.ndarray,
                modulation: np.ndarray | None = None,
                feedback_blocks=None, last: float = 0.0
                ) -> tuple[np.ndarray, int, float]:
    """Un opérateur FM (``renderSineWaveWithFeedback``,
    ``renderFMWithFeedback[Add]``) : un sinus dont la phase est poussée de
    ``modulation << 8`` (l'indice vaut ±amplitude/2²⁵ périodes) et, si la
    rétroaction est réglée, de sa propre sortie précédente, écrêtée à
    ±2²¹ — un huitième de période.

    Rend le signal (sinus × amplitude / 2³²), la phase finale et la
    dernière valeur de rétroaction."""
    inc_blocks = np.asarray(inc_blocks, dtype=np.int64)
    if compiled():
        phase = np.zeros(n, dtype=np.int64)
        _phase_loop(inc_blocks, int(phase0) & MASK32, phase)
    else:
        inc = np.repeat(inc_blocks, BLOCK)[:n]
        phase = (int(phase0) + np.cumsum(inc)) & MASK32
    end_phase = int((int(phase0) + int(inc_blocks.sum()) * BLOCK) & MASK32)
    if feedback_blocks is None or not np.any(np.asarray(feedback_blocks)):
        if modulation is not None:
            shift = (np.round(modulation).astype(np.int64) << 8) & MASK32
            phase = (phase + shift) & MASK32
        return _sine(phase) * amp / Q32, end_phase, float(last)

    # Rétroaction : une récurrence d'un échantillon, calculée en Python ;
    # tout ce qui n'en dépend pas est préparé d'un bloc. Les positions se
    # comptent en pas de table (256 par période), décalées d'une période
    # pour rester positives : la table dépliée sur trois périodes évite
    # tout masque dans la boucle. Les arrondis entiers du firmware n'y
    # sont pas, soit 0,2 % de la crête au plus.
    values, step = _sine_lists()
    small = phase >> 8
    if modulation is not None:
        small = small + np.round(modulation).astype(np.int64)
    position = _seq((small & 0xFFFFFF) / 65536.0 + 256.0)
    fb = _seq(np.asarray(feedback_blocks, dtype=np.float64) / Q32 / 65536.0)
    out = _out(n)
    value = _fm_feedback_loop(position, fb, values, step, float(last), out)
    return _result(out) * amp / Q32, end_phase, value


@_Boucle
def _fm_feedback_loop(position, fb, values, step, value, out):
    """La récurrence de :func:`fm_operator` ; rend la dernière valeur."""
    hi = (float(1 << 21) - 1.0) / 65536.0
    lo = -float(1 << 21) / 65536.0
    n = len(position)
    for b in range(len(fb)):
        k = fb[b]
        for i in range(b * BLOCK, min(n, (b + 1) * BLOCK)):
            feedback = value * k
            if not feedback <= hi:
                feedback = hi
            elif feedback < lo:
                feedback = lo
            x = position[i] + feedback
            j = int(x)
            value = values[j] + step[j] * (x - j)
            out[i] = value
    return value


def _sine_lists():
    """Le sinus de ``SineOsc`` pour la boucle de rétroaction, déplié sur
    trois périodes : valeurs sur 2³¹ et pentes par pas de table."""
    return _sine_tables(compiled())


@lru_cache(maxsize=2)
def _sine_tables(as_array: bool):
    tab = table("sineWaveSmall")
    values = np.tile(tab[:-1] * 65536.0, 3)
    step = np.tile((tab[1:] - tab[:-1]) * 65536.0, 3)
    if as_array:
        return np.ascontiguousarray(values), np.ascontiguousarray(step)
    return values.tolist(), step.tolist()


# --------------------------------------------------------------------------- #
# Échantillons
# --------------------------------------------------------------------------- #

#: Incrément de phase d'un échantillon lu à sa hauteur (``kMaxSampleValue``)
#: : un pas du fichier par échantillon de sortie, lu sans interpolation.
SAMPLE_UNITY = 1 << 24

#: Les échantillons de sortie calculés d'un coup par :func:`read_sample`.
_READ_CHUNK = 16384


def sample_kernel(increment: int) -> int:
    """``getWhichKernel`` (``functions.cpp``) : le noyau d'interpolation
    d'un échantillon selon son incrément de phase. Le noyau 0 sert jusqu'à
    un demi-ton au-dessus de la hauteur d'origine ; au-delà, un noyau plus
    étroit par demi-octave montée, pour ne pas replier les aigus."""
    inc = int(increment)
    if inc < 17268826:
        return 0
    kernel = 1
    while inc >= 32599202:                    # 11,5 demi-tons au-dessus
        inc >>= 1
        kernel += 2
        if kernel == 5:
            break
    if inc >= 23051117:                       # 5,5 demi-tons au-dessus
        kernel += 1
    return kernel


def read_sample(data: np.ndarray, inc_blocks, n: int,
                loop: bool = False) -> np.ndarray:
    """Lecture d'un échantillon (``SampleLowLevelReader``) : ``(n,)`` d'un
    fichier mono, ``(canaux, n)`` d'un stéréo, dans l'unité de ``data``.

    À sa hauteur (incrément 2²⁴ partout), l'échantillon est lu tel quel.
    Sinon, sinus cardinal fenêtré à 16 points (``Interpolator::interpolate``,
    la lecture « smooth », réglage par défaut) : l'échantillon y entre sur
    16 bits, le noyau se choisit par bloc selon la vitesse
    (:func:`sample_kernel`) et ses 17 phases s'interpolent linéairement. La
    sortie ``t`` lit la position ``(t + 1)·r − 1`` (``r`` : la vitesse) : le
    tampon se remplit à moitié en arrière du départ, et chaque échantillon de
    sortie avance la tête avant d'être lu (``considerUpcomingWindow``).

    :param inc_blocks: incrément de phase par bloc de 128, sur 2²⁴.
    :param loop: rebouclage sur l'échantillon entier.
    """
    data = np.asarray(data)
    mono = data.ndim == 1
    samples = data[:, None] if mono else data
    frames, channels = samples.shape
    inc_blocks = np.asarray(inc_blocks, dtype=np.int64)
    inc = np.repeat(inc_blocks, BLOCK)[:n]
    out = np.zeros((channels, n))
    if frames == 0 or inc.size < n:
        return out[0] if mono else out
    if np.all(inc == SAMPLE_UNITY):
        t = np.arange(n)
        if loop:
            t = np.mod(t, frames)
        out = samples[np.minimum(t, frames - 1)].T * (t < frames)
        return out[0] if mono else out
    whole = np.clip(np.floor(samples.astype(np.float64) * 32768.0),
                    -32768.0, 32767.0)
    kernels = table("windowedSincKernel")
    which = np.repeat([sample_kernel(v) for v in inc_blocks], BLOCK)[:n]
    position = np.cumsum(inc) - SAMPLE_UNITY
    taps = np.arange(8, -8, -1)
    for a in range(0, n, _READ_CHUNK):
        b = min(n, a + _READ_CHUNK)
        pos = position[a:b]
        frac = pos & 0xFFFFFF
        phase = frac >> 20
        strength = ((frac >> 5) & 0x7FFF) / 32768.0
        w = which[a:b]
        k0 = kernels[w, phase]
        k = k0 + (kernels[w, phase + 1] - k0) * strength[:, None]
        index = (pos >> 24)[:, None] + taps[None, :]
        if loop:
            index = np.mod(index, frames)
            valid = None
        else:
            valid = (index >= 0) & (index < frames)
            index = np.clip(index, 0, frames - 1)
        for c in range(channels):
            values = whole[index, c]
            if valid is not None:
                values = values * valid
            out[c, a:b] = np.einsum("ij,ij->i", k, values)
    out /= float(1 << 30)
    return out[0] if mono else out


# --------------------------------------------------------------------------- #
# Filtres en échelle
# --------------------------------------------------------------------------- #

#: ``resonanceThresholdsForOversampling`` et ``resonanceLimitTable``
#: (``lpladder.cpp``) : au-delà de ces résonances, l'échelle « drive »
#: double sa fréquence de calcul.
_OVERSAMPLE_THRESHOLDS = (16384,) * 52 + (15500, 20735, 17000, 9000, 9000) \
    + (9000,) * 8
_OVERSAMPLE_LIMITS = (32767,) * 52 + (28415, 20000, 17000, 17000, 17000) \
    + (17000,) * 8


def _quick_log(x: np.ndarray) -> np.ndarray:
    """``quickLog`` : log₂ approché, ``(magnitude + 1 + mantisse) << 25``."""
    x = np.maximum(np.asarray(x, dtype=np.float64), 1.0)
    magnitude = np.floor(np.log2(x)) + 1.0
    mantissa = x / np.power(2.0, magnitude - 1.0)  # 1..2
    return (magnitude + mantissa) * float(1 << 25)


def _table_signed(values, position: np.ndarray) -> np.ndarray:
    """``interpolateTableSigned(position, 30, table, 6)`` sur une table de
    65 valeurs ; rend ``valeur × 65536``."""
    index = np.clip(position / float(1 << 24), 0.0, 64.0)
    return np.interp(index, np.arange(65, dtype=np.float64),
                     np.asarray(values, dtype=np.float64)) * 65536.0


def curve_frequency(freq) -> tuple[np.ndarray, np.ndarray]:
    """``Filter::curveFrequency`` : ``tan`` par la table du firmware
    (``instantTan`` sur 1,44 rad à pleine échelle). Rend ``t = tan θ`` et
    ``G = t/(1+t)``, le coefficient d'un étage."""
    x = np.minimum(np.asarray(freq, dtype=np.float64) * 32.0, Q31 - 1.0)
    x = np.maximum(x, 0.0)
    tanned = np.interp(x / float(1 << 25), np.arange(65, dtype=np.float64),
                       table("tanTable"))
    t = tanned / float(1 << 28)
    return t, t / (1.0 + t)


@dataclass
class LadderConfig:
    """Les coefficients d'une échelle passe-bas, un par bloc (tableaux)."""

    mode: str
    m: np.ndarray        # coefficient d'un étage, avant gigue
    c1: np.ndarray       # prises de rétroaction des étages
    c2: np.ndarray
    c3: np.ndarray
    c4: np.ndarray
    k_in: np.ndarray     # 1 / (1 + rétroaction instantanée)
    k_fb: np.ndarray     # force de la rétroaction
    saturate: np.ndarray  # saturation de l'entrée (résonance haute)
    k_morph: np.ndarray
    oversample: np.ndarray
    gain: np.ndarray     # facteur appliqué au gain des oscillateurs


def lpf_config(mode: str, freq, res, morph=None) -> LadderConfig:
    """``LpLadderFilter::setConfig`` pour chaque bloc.

    :param mode: ``12dB``, ``24dB`` ou ``24dBDrive``.
    :param freq: valeur finale de ``lpfFrequency`` (neutre 2 000 000).
    :param res: valeur finale de ``lpfResonance`` (neutre ≈ 2²⁸).
    :param morph: valeur finale de ``lpfMorph`` (``None`` : 0).
    """
    if morph is None:
        morph = 0.0
    arrays = np.broadcast_arrays(
        np.atleast_1d(np.asarray(freq, dtype=np.float64)),
        np.atleast_1d(np.asarray(res, dtype=np.float64)),
        np.atleast_1d(np.asarray(morph, dtype=np.float64)))
    freq, res, morph = (np.array(a, dtype=np.float64) for a in arrays)
    morph_q31 = np.clip(morph * 4.0, 0.0, Q31 - 1.0)
    oversample = np.zeros(freq.shape, dtype=bool)

    if mode == "24dBDrive":
        p_r = np.clip(4.0 * res, 0.0, Q31 - 1.0)
        log_freq = np.minimum(_quick_log(freq), float(63 << 24))
        threshold = _table_signed(_OVERSAMPLE_THRESHOLDS, log_freq)
        oversample = (np.floor(log_freq / float(1 << 24)) > 51) \
            & (p_r > threshold)
        if np.any(oversample):
            half = np.floor(freq / 2.0)
            log2 = log_freq - float(1 << 25)
            half = half - np.floor(np.round(log2 * half / Q32) / 256.0) * 34.0
            half = np.minimum(39056384.0, half)
            limit = _table_signed(_OVERSAMPLE_LIMITS, log2)
            freq = np.where(oversample, half, freq)
            p_r = np.where(oversample, np.minimum(p_r, limit), p_r)
    else:
        resonance = (Q31 - 1.0 - np.minimum(res, 510000000.0) * 4.0) / Q31
        p_r = (1.0 - resonance * resonance) * Q31
        p_r = p_r * ((Q31 - 1.0 - 33.0) / Q31)

    t, g = curve_frequency(freq)
    m = np.maximum(g, 4317840.0 / Q31)
    rho = p_r / Q31
    one_plus_t = 1.0 + t
    if mode == "12dB":
        c2 = (2.0 * m - 1.0) / one_plus_t
        c1 = c2 * m
        c3 = 2.0 / one_plus_t
        c4 = np.zeros_like(m)
        k_in = 1.0 / (1.0 + 2.0 * rho * (2.0 * m - 1.0) * m * m)
    else:
        c1 = m ** 3 / one_plus_t
        c2 = m ** 2 / one_plus_t
        c3 = m / one_plus_t
        c4 = 2.0 / one_plus_t
        k_in = 1.0 / (1.0 + 2.0 * rho * m ** 4)

    if mode != "24dBDrive":
        tanned = t * float(1 << 28)
        p_fb = np.where(tanned <= 304587486.0,
                        p_r * (1150000000.0 * 2.0 / Q32), p_r * 0.5)
        a = 536870912.0 - np.minimum(res, 536870911.0)
        a = np.floor(a * a / Q32) * 8.0
        gain = (268435456.0 + 536870912.0 - a) * 8.0 / Q32
    else:
        p_fb = p_r
        gain = np.full(freq.shape, 0.8)
    saturate = (morph_q31 > 0.0) | (p_fb > 510000000.0)
    return LadderConfig(mode, m, c1, c2, c3, c4, k_in, p_fb / float(1 << 29),
                        saturate, morph_q31 / Q31, oversample, gain)


def _stage(g: float, z: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Un étage ``BasicFilterComponent`` en z : la sortie ``G(z+1)/(z−p)``
    et la mémoire ``2G/(z−p)``, ``p = 1 − 2G``."""
    p = 1.0 - 2.0 * g
    return g * (z + 1.0) / (z - p), 2.0 * g / (z - p)


def lpf_response(cfg: LadderConfig, freqs, block: int = 0) -> np.ndarray:
    """Réponse complexe de l'échelle passe-bas d'un bloc, linéarisée
    (saturations au gain unité, sans gigue) : l'entrée diminuée de la
    rétroaction des mémoires, puis les étages. Calculée en z, elle garde un
    sens au-delà de l'auto-oscillation : une pointe étroite à la coupure."""
    z = np.exp(2j * np.pi * np.asarray(freqs, dtype=np.float64) / SR)
    h, q = _stage(float(cfg.m[block]), z)
    k_in, k_fb = float(cfg.k_in[block]), float(cfg.k_fb[block])
    c1, c2, c3, c4 = (float(c[block]) for c in (cfg.c1, cfg.c2, cfg.c3,
                                                 cfg.c4))
    if cfg.mode == "12dB":
        taps = c1 + c2 * h + c3 * h * h
        out = 2.0 * (2.0 * h - 1.0) * h * h
    else:
        taps = c1 + c2 * h + c3 * h ** 2 + c4 * h ** 3
        out = 2.0 * h ** 4
    return out * k_in / (1.0 + k_in * k_fb * q * taps)


def hpf_response(cfg: HpfConfig, freqs, block: int = 0) -> np.ndarray:
    """Réponse complexe du passe-haut en échelle d'un bloc, linéarisée."""
    z = np.exp(2j * np.pi * np.asarray(freqs, dtype=np.float64) / SR)
    h, q = _stage(float(cfg.g[block]), z)
    c_a, c3, cl = (float(c[block]) for c in (cfg.c_a, cfg.c3, cfg.cl))
    high = 1.0 - h
    return float(cfg.c_out[block]) * c_a * high / (
        1.0 - c_a * q * (c3 + cl * high))


def ladder_jitter(n: int, rng: np.random.Generator,
                  state: float = 0.0) -> tuple[np.ndarray, float]:
    """La gigue de coupure de l'échelle : du bruit uniforme (``>> 2``)
    lissé à 1/128 par échantillon, soit ±0,5 % environ. Rend le facteur
    appliqué au coefficient et l'état final."""
    noise = rng.integers(-(1 << 29), 1 << 29, n)
    if compiled():
        # D'une passe : chaque tableau neuf d'une voix coûte, sous Windows,
        # de la mémoire fraîche, que les fils de l'écoute se disputent.
        out = np.empty(n)
        return out, _jitter_loop(noise, 1.0 / 128.0, float(state), out)
    smooth, last = one_pole(noise.astype(np.float64), 1.0 / 128.0, state)
    return 1.0 + smooth / Q32, last


@_Boucle
def _jitter_loop(noise, k, y, out):
    """:func:`ladder_jitter` : le bruit lissé (:func:`one_pole`), puis le
    facteur ; rend le dernier état du lissage."""
    for i in range(len(noise)):
        y += k * (float(noise[i]) - y)
        out[i] = 1.0 + y / Q32
    return y


def lpf_process(x: np.ndarray, cfg: LadderConfig, jitter: np.ndarray,
                state: list[float] | None = None) -> np.ndarray:
    """L'échelle passe-bas, échantillon par échantillon
    (``do12dBLPFOnSample``, ``do24dBLPFOnSample``, ``doDriveLPFOnSample``).

    ``state`` : les mémoires des quatre étages, mises à jour sur place.
    """
    n = x.size
    if state is None:
        state = [0.0, 0.0, 0.0, 0.0]
    out = _out(n)
    state[:] = _lpf_loop(
        _seq(x), _seq(cfg.m), _seq(np.broadcast_to(jitter, (n,))),
        _seq(cfg.c1), _seq(cfg.c2), _seq(cfg.c3), _seq(cfg.c4),
        _seq(cfg.k_in), _seq(cfg.k_fb), _flags(cfg.saturate),
        _seq(cfg.k_morph), _flags(cfg.oversample),
        _LPF_CODES.get(cfg.mode, 2), out, _tanh_list(),
        *(float(s) for s in state))
    return _result(out)


#: Le numéro de chaque échelle pour :func:`_lpf_loop`.
_LPF_CODES = {"12dB": 0, "24dB": 1, "24dBDrive": 2}

#: ``getTanHUnknown(x, 2)``, ``(x, 4)``, ``(x, 7)`` : entrées et plafonds.
_IN2, _TOP2 = 4.0 / Q31, float(1 << 27)
_IN4, _TOP4 = 16.0 / Q31, float(1 << 25)
_IN7, _TOP7 = 128.0 / Q31, float(1 << 22)


@_Boucle
def _lpf_loop(x, ms, jitter, c1s, c2s, c3s, c4s, k_ins, k_fbs, sats,
              k_morphs, overs, mode, out, tab, s1, s2, s3, s4):
    """Les échantillons de :func:`lpf_process`, bloc par bloc ; ``mode`` :
    0 pour 12 dB, 1 pour 24 dB, 2 pour « drive ». Rend les quatre mémoires.

    Le coefficient d'un étage est ``ms[b]`` (un par bloc) multiplié par la
    gigue de l'échantillon. Chaque cas a sa boucle : un test par
    échantillon coûte, en Python, autant qu'une multiplication du filtre."""
    n = len(x)
    in2, top2 = _IN2, _TOP2
    in4, top4 = _IN4, _TOP4
    in7, top7 = _IN7, _TOP7
    y4 = 0.0
    for b in range(len(c1s)):
        m = ms[b]
        c1 = c1s[b]
        c2 = c2s[b]
        c3 = c3s[b]
        c4 = c4s[b]
        k_in = k_ins[b]
        k_fb = k_fbs[b]
        sat = sats[b]
        k_morph = k_morphs[b]
        start = b * BLOCK
        stop = min(n, start + BLOCK)
        if mode == 0 and not sat:
            for i in range(start, stop):
                mm = m * jitter[i]
                u = ((x[i] + DENORMAL_GUARD)
                     - k_fb * (s1 * c1 + s2 * c2 + s3 * c3)) * k_in
                a = (u - s1) * mm
                y1 = a + s1
                s1 = y1 + a
                a = (y1 - s2) * mm
                y2 = a + s2
                s2 = y2 + a
                a = (y2 - s3) * mm
                y3 = a + s3
                s3 = y3 + a
                out[i] = 2.0 * (2.0 * y3 - y2)
        elif mode == 0:
            for i in range(start, stop):
                v = x[i] + DENORMAL_GUARD
                mm = m * jitter[i]
                u = (v - k_fb * (s1 * c1 + s2 * c2 + s3 * c3)) * k_in
                w = (u + v * k_morph) * in2
                w = 1.0 if not w <= 1.0 else (-1.0 if w < -1.0 else w)
                p = (w + 1.0) * 128.0
                k = int(p)
                if k > 255:
                    k = 255
                u = top2 * (tab[k] + (tab[k + 1] - tab[k]) * (p - k))
                a = (u - s1) * mm
                y1 = a + s1
                s1 = y1 + a
                a = (y1 - s2) * mm
                y2 = a + s2
                s2 = y2 + a
                a = (y2 - s3) * mm
                y3 = a + s3
                s3 = y3 + a
                out[i] = 2.0 * (2.0 * y3 - y2)
        elif mode == 1 and not sat:
            for i in range(start, stop):
                mm = m * jitter[i]
                fb = s1 * c1 + s2 * c2 + s3 * c3 + s4 * c4
                u = ((x[i] + DENORMAL_GUARD) - k_fb * fb) * k_in
                a = (u - s1) * mm
                y1 = a + s1
                s1 = y1 + a
                a = (y1 - s2) * mm
                y2 = a + s2
                s2 = y2 + a
                a = (y2 - s3) * mm
                y3 = a + s3
                s3 = y3 + a
                a = (y3 - s4) * mm
                y4 = a + s4
                s4 = y4 + a
                out[i] = 2.0 * y4
        elif mode == 1:
            for i in range(start, stop):
                v = x[i] + DENORMAL_GUARD
                mm = m * jitter[i]
                u = (v - k_fb * (s1 * c1 + s2 * c2 + s3 * c3 + s4 * c4)) * k_in
                w = (u + v * k_morph) * in2
                w = 1.0 if not w <= 1.0 else (-1.0 if w < -1.0 else w)
                p = (w + 1.0) * 128.0
                k = int(p)
                if k > 255:
                    k = 255
                u = top2 * (tab[k] + (tab[k + 1] - tab[k]) * (p - k))
                a = (u - s1) * mm
                y1 = a + s1
                s1 = y1 + a
                a = (y1 - s2) * mm
                y2 = a + s2
                s2 = y2 + a
                a = (y2 - s3) * mm
                y3 = a + s3
                s3 = y3 + a
                a = (y3 - s4) * mm
                y4 = a + s4
                s4 = y4 + a
                out[i] = 2.0 * y4
        else:
            # Échelle « drive » : rétroaction et sortie saturées, calcul
            # doublé aux hautes résonances aiguës.
            steps = 2 if overs[b] else 1
            for i in range(start, stop):
                v = x[i] + DENORMAL_GUARD
                mm = m * jitter[i]
                for _ in range(steps):
                    w = (s1 * c1 + s2 * c2 + s3 * c3 + s4 * c4) * in7
                    w = 1.0 if not w <= 1.0 else (-1.0 if w < -1.0 else w)
                    p = (w + 1.0) * 128.0
                    k = int(p)
                    if k > 255:
                        k = 255
                    fb = top7 * (tab[k] + (tab[k + 1] - tab[k]) * (p - k))
                    u = (v - k_fb * fb) * k_in
                    if sat:
                        w = (u + v * k_morph) * in2
                        w = 1.0 if not w <= 1.0 else (-1.0 if w < -1.0 else w)
                        p = (w + 1.0) * 128.0
                        k = int(p)
                        if k > 255:
                            k = 255
                        u = top2 * (tab[k] + (tab[k + 1] - tab[k]) * (p - k))
                    a = (u - s1) * mm
                    y1 = a + s1
                    s1 = y1 + a
                    a = (y1 - s2) * mm
                    y2 = a + s2
                    s2 = y2 + a
                    a = (y2 - s3) * mm
                    y3 = a + s3
                    s3 = y3 + a
                    a = (y3 - s4) * mm
                    y4 = a + s4
                    s4 = y4 + a
                w = 2.0 * y4 * in4
                w = 1.0 if not w <= 1.0 else (-1.0 if w < -1.0 else w)
                p = (w + 1.0) * 128.0
                k = int(p)
                if k > 255:
                    k = 255
                out[i] = top4 * (tab[k] + (tab[k + 1] - tab[k]) * (p - k))
    return s1, s2, s3, s4


@dataclass
class HpfConfig:
    """Les coefficients du passe-haut en échelle, un par bloc."""

    g: np.ndarray        # coefficient d'un étage (fc)
    c3: np.ndarray       # prise de rétroaction du passe-haut interne
    cl: np.ndarray       # prise de rétroaction du passe-bas interne
    c_a: np.ndarray      # mise à l'échelle avant saturation
    c_out: np.ndarray    # normalisation de sortie
    resonance: np.ndarray  # hpfProcessedResonance (seuils de saturation)
    gain: np.ndarray


def hpf_config(freq, res) -> HpfConfig:
    """``HpLadderFilter::setConfig`` pour chaque bloc ; ``res`` est
    quantifiée comme dans ``FilterSet::setConfig`` (``>> 21 << 21``)."""
    freq = np.atleast_1d(np.asarray(freq, dtype=np.float64))
    res = np.broadcast_to(np.atleast_1d(np.asarray(res, dtype=np.float64)),
                          freq.shape)
    res = np.floor(res / float(1 << 21)) * float(1 << 21)
    t, g = curve_frequency(freq)
    resonance = (Q31 - 1.0 - np.minimum(res, 536870911.0) * 4.0) / Q31
    p_r = np.maximum((1.0 - resonance * resonance) * Q31, 134217728.0)
    p_unaltered = p_r
    p_r = np.floor(p_r * 1200000000.0 / Q32) * 2.0
    divide = Q31 / np.maximum(np.floor(p_r / float(1 << 23)), 1.0)
    fc = g * Q31
    m_res = p_unaltered * fc / Q32
    m2_res = m_res * fc / Q32
    one_plus_t = 1.0 + t
    c3 = -g / one_plus_t
    cl = 1.0 / one_plus_t
    to_divide = 268435456.0 - m_res / 2.0 + m2_res
    total = p_r * 67108864.0 / to_divide
    raw = np.minimum(res, 536870911.0) * 4.0
    squared = raw * raw / Q31
    squared = np.floor(squared * squared / Q32 / 16.0) * 19.0
    gain = (Q31 - 1.0 - squared) * 2.0 / Q32
    return HpfConfig(g, c3, cl, total * 32.0 / Q32, divide * 128.0 / Q32,
                     p_r, gain)


def hpf_process(x: np.ndarray, cfg: HpfConfig,
                state: list[float] | None = None) -> np.ndarray:
    """Le passe-haut en échelle (``HpLadderFilter::doHPF``). ``state`` :
    les trois mémoires et la dernière valeur de travail de la saturation."""
    n = x.size
    if state is None:
        state = [0.0, 0.0, 0.0, Q31]
    out = _out(n)
    state[:] = _hpf_loop(
        _seq(x), _seq(cfg.g), _seq(cfg.c3), _seq(cfg.cl), _seq(cfg.c_a),
        _seq(cfg.c_out), _seq(cfg.resonance), out, _tanh_list(),
        _tanh_grid(), *(float(s) for s in state))
    return _result(out)


def _tanh_grid():
    """``tanH2d``, pour une lecture échantillon par échantillon : un
    tableau pour numba, des listes sinon."""
    return _tanh_grid_table(compiled())


@lru_cache(maxsize=2)
def _tanh_grid_table(as_array: bool):
    grid = table("tanH2d")
    return np.ascontiguousarray(grid) if as_array else grid.tolist()


@_Boucle
def _hpf_loop(x, gs, c3s, cls, c_as, c_outs, p_rs, out, tab, grid,
              h1, l1, h3, last):
    """Les échantillons de :func:`hpf_process`, bloc par bloc. Rend les
    trois mémoires et la dernière valeur de travail de la saturation."""
    n = len(x)
    in2, top2 = _IN2, _TOP2
    top, bottom = Q31 - 1.0, -Q31
    scale = 32768.0 / 4.0   # >> (1 + 1)
    if not (last >= 0.0 and last <= Q32):
        last = Q31
    for b in range(len(gs)):
        g = gs[b]
        c3 = c3s[b]
        cl = cls[b]
        c_a = c_as[b]
        c_out = c_outs[b]
        p_r = p_rs[b]
        start = b * BLOCK
        stop = min(n, start + BLOCK)
        if p_r > 900000000.0:
            # Forte résonance : la saturation adoucie
            # ``getTanHAntialiased(a, 1)`` dépend de l'échantillon précédent,
            # la table à deux entrées se lit en ligne (numpy à chaque
            # échantillon coûtait 20 µs, soit 1,4 s pour 1,5 s de son).
            for i in range(start, stop):
                v = x[i] + DENORMAL_GUARD
                a = (v - h1) * g
                lp = a + h1
                h1 = lp + a
                first = v - lp
                a = c_a * (first + h3 * c3 + l1 * cl)
                work = a * 2.0
                work = top if not work <= top else (
                    bottom if work < bottom else work)
                work += Q31
                cx = work / 33554432.0
                ix = int(cx)
                if ix > 127:
                    ix = 127
                fx = cx - ix
                cy = last / 67108864.0
                iy = int(cy)
                if iy > 63:
                    iy = 63
                fy = cy - iy
                row = grid[iy]
                v1 = row[ix] + (row[ix + 1] - row[ix]) * fx
                row = grid[iy + 1]
                v2 = row[ix] + (row[ix + 1] - row[ix]) * fx
                a = (v1 + (v2 - v1) * fy) * scale
                last = work
                d = (a - h3) * g
                hp = d + h3
                h3 = hp + d
                d = ((a - hp) - l1) * g
                lo = d + l1
                l1 = lo + d
                out[i] = a * c_out
            continue
        a = 0.0
        if p_r > 750000000.0:
            for i in range(start, stop):
                v = x[i] + DENORMAL_GUARD
                d = (v - h1) * g
                lp = d + h1
                h1 = lp + d
                a = c_a * (v - lp + h3 * c3 + l1 * cl)
                w = a * in2
                w = 1.0 if not w <= 1.0 else (-1.0 if w < -1.0 else w)
                p = (w + 1.0) * 128.0
                k = int(p)
                if k > 255:
                    k = 255
                y = top2 * (tab[k] + (tab[k + 1] - tab[k]) * (p - k))
                d = (y - h3) * g
                hp = d + h3
                h3 = hp + d
                d = ((y - hp) - l1) * g
                lo = d + l1
                l1 = lo + d
                out[i] = y * c_out
        else:
            for i in range(start, stop):
                v = x[i] + DENORMAL_GUARD
                d = (v - h1) * g
                lp = d + h1
                h1 = lp + d
                a = c_a * (v - lp + h3 * c3 + l1 * cl)
                d = (a - h3) * g
                hp = d + h3
                h3 = hp + d
                d = ((a - hp) - l1) * g
                lo = d + l1
                l1 = lo + d
                out[i] = a * c_out
        # La valeur de travail de la saturation adoucie, pour un bloc
        # suivant plus résonant : celle du dernier échantillon suffit.
        work = a * 4.0
        work = top if not work <= top else (bottom if work < bottom else work)
        last = work + Q31
    return h1, l1, h3, last


# --------------------------------------------------------------------------- #
# Saturation de la voix
# --------------------------------------------------------------------------- #

def saturate(x: np.ndarray, clipping: int,
             last: float = Q31) -> tuple[np.ndarray, float]:
    """``Sound::saturate`` : ``getTanHAntialiased(x, 5 + écrêtage)``, puis
    un gain de ``2^(écrêtage − 2)`` au-delà de 2. Le seuil d'entrée tombe
    de moitié à chaque cran, la sortie plafonne vers 2²²."""
    c = int(clipping)
    y, last = tanh_antialiased(x, 5 + c, last)
    if c > 2:
        y = y * float(1 << (c - 2))
    return y, last


# --------------------------------------------------------------------------- #
# Enveloppes et LFO
# --------------------------------------------------------------------------- #

def decay4(pos: float) -> float:
    """``getDecay4(pos, 23)``, sur 2³¹ : 2³¹ à 0, 0 à 2²³."""
    if pos >= 8388608:
        return 0.0
    return _decay_table("decayTableSmall4", pos)


def _decay_table(name: str, pos: float) -> float:
    """``getDecay4``/``getDecay8`` : la table lue en ``pos`` (23 bits),
    rendue sur 2³¹."""
    tab = table(name)
    index = int(pos) >> 15
    if index >= 256:
        return float(tab[256]) * 32768.0
    frac = int(pos) & 32767
    return (tab[index] * (32768 - frac) + tab[index + 1] * frac)


# --------------------------------------------------------------------------- #
# Sidechain
# --------------------------------------------------------------------------- #

#: ``ONE_Q31`` du firmware.
ONE_Q31 = 2147483647

#: ``attackRateTable[0] << 2`` : une attaque « tout en bas » saute droit au
#: relâchement (``SideChain::render``).
SIDECHAIN_INSTANT_ATTACK = 262144 << 2


def combine_hit_strengths(a: int, b: int) -> int:
    """``combineHitStrengths`` : à mi-chemin du plus fort et de la somme
    (« plutôt que Pythagore, pour gagner du calcul »)."""
    total = min((int(a) & 0xFFFFFFFF) + (int(b) & 0xFFFFFFFF), ONE_Q31)
    return (max(int(a), int(b)) >> 1) + (total >> 1)


def sidechain_rate(raw: int, sync_level: int, bpm: float) -> int:
    """La vitesse d'attaque ou de relâchement du sidechain, par échantillon
    (``getActualAttackRate``/``getActualReleaseRate``). Synchronisée, elle
    suit le tempo : ``réglage · BPM · 2^(4 + niveau) / 165 375``, ``niveau``
    tel que le fichier l'écrit — la grandeur des tics du morceau, qui entre
    dans l'inverse du temps par tic et dans la conversion du niveau,
    s'annule."""
    level = int(sync_level or 0)
    if level <= 0 or bpm <= 0:
        return int(raw)
    return int(float(raw) * float(bpm) * 2.0 ** (4 + level) / 165375.0)


def _mul32(a: int, b: int) -> int:
    """``multiply_32x32_rshift32``."""
    return (int(a) * int(b)) >> 32


def sidechain_blocks(hits, attack: int, release: int, shape: int,
                     instant: bool = False) -> np.ndarray:
    """``SideChain::render``, bloc par bloc : la valeur de la source
    *sidechain* (−2³¹ au plus creux, 0 au repos).

    :param hits: force du coup reçu au début de chaque bloc (0 : aucun),
        coups d'un même bloc déjà combinés (:func:`combine_hit_strengths`).
    :param attack: vitesse d'attaque par échantillon (:func:`sidechain_rate`).
    :param release: vitesse de relâchement par échantillon.
    :param shape: le réglage ``compressorShape`` du son, brut.
    :param instant: l'attaque est « tout en bas » (réglage brut égal à
        :data:`SIDECHAIN_INSTANT_ATTACK`).

    Recopié ligne à ligne, ``goto`` compris : une boucle Python d'environ
    70 000 blocs pour trois minutes, quelques dizaines de millisecondes.
    """
    decay4 = table("decayTableSmall4")
    decay8 = table("decayTableSmall8")

    def get_decay(tab, pos: int) -> int:
        index = pos >> 15
        if index >= 256:
            return int(tab[256]) * 32768
        frac = pos & 32767
        return int(tab[index]) * (32768 - frac) + int(tab[index + 1]) * frac

    off, attacking, releasing = 0, 1, 2
    status, pos, last = off, 0, ONE_Q31
    offset = height = 0
    positive_shape = (int(shape) + 2147483648) & 0xFFFFFFFF
    n = BLOCK
    out = np.empty(len(hits))
    for b, hit in enumerate(hits):
        to_release = False
        if hit:
            new_offset = ONE_Q31 - int(hit)
            # Seul un coup qui creuse davantage compte.
            if new_offset < last:
                offset = new_offset
                if instant:
                    to_release = True
                else:
                    status = attacking
                    height = last - offset
                    pos = 0
        if status == attacking and not to_release:
            pos += n * attack
            if pos >= 8388608:
                to_release = True
            else:
                last = (_mul32(height, ONE_Q31 - get_decay(decay4,
                                                           8388608 - pos))
                        << 1) + offset
        if to_release:
            pos = 0
            status = releasing
            height = ONE_Q31 - offset
        if status == releasing:
            pos += n * release
            if pos >= 8388608:
                status = off
                last = ONE_Q31
            else:
                curvedness = (positive_shape >> 15) - (pos >> 7)
                if curvedness < 0:
                    pre = pos << 8
                else:
                    curvedness = min(curvedness, 65536)
                    pre = (65536 - curvedness) * (pos >> 8) \
                        + (get_decay(decay8, 8388608 - pos) >> 16) * curvedness
                last = ONE_Q31 - height + (_mul32(pre, height) << 1)
        elif status == off:
            last = ONE_Q31
        out[b] = last - ONE_Q31
    return out


class Envelope:
    """Une enveloppe du firmware (``envelope.cpp``), rendue par bloc."""

    ATTACK, DECAY, SUSTAIN, RELEASE, OFF = range(5)

    def __init__(self) -> None:
        self.state = Envelope.OFF
        self.pos = 0.0
        self.last = 0.0
        self.pre = 0.0
        self.smoothed = 0.0
        self.ignored_note_off = False

    def note_on(self, attack_rate: float, sustain: float) -> None:
        """``Envelope::noteOn`` : une attaque plus rapide que 245 632 est
        sautée, l'enveloppe part du sommet."""
        self.smoothed = float(sustain)
        self.ignored_note_off = False
        self.pos = 0.0
        if attack_rate > 245632:
            self.state = Envelope.DECAY
            self.last = Q31 - 1.0
        else:
            self.state = Envelope.ATTACK
            self.last = 0.0

    def note_off(self, has_sustain: bool) -> None:
        """``Envelope::noteOff`` : sans palier, la note continue son decay."""
        if not has_sustain:
            self.ignored_note_off = True
        elif self.state < Envelope.RELEASE:
            self.release()

    def release(self) -> None:
        if self.state != Envelope.RELEASE:
            self.state = Envelope.RELEASE
            self.pos = 0.0
            self.pre = self.last

    def render(self, attack: float, decay: float, sustain: float,
               release: float, n: int = BLOCK) -> float:
        """Un bloc : la valeur bipolaire de l'enveloppe (−2³¹ éteinte)."""
        while True:
            if self.state == Envelope.ATTACK:
                self.pos += attack * n
                if self.pos >= 8388608:
                    self.pos = 0.0
                    self.state = Envelope.DECAY
                    continue
                self.last = max(Q31 - 1.0 - _decay_table(
                    "decayTableSmall4", self.pos), 1.0)
                break
            if self.state == Envelope.DECAY:
                toward = math.floor((sustain - self.smoothed) / 512.0)
                self.smoothed += n * toward
                self.smoothed = min(max(self.smoothed, -Q31), Q31 - 1.0)
                self.last = self.smoothed + _decay_table(
                    "decayTableSmall8", self.pos) * (
                    Q31 - 1.0 - self.smoothed) / Q32 * 2.0
                self.pos += decay * n
                if self.pos >= 8388608:
                    self.state = Envelope.SUSTAIN
                break
            if self.state == Envelope.SUSTAIN:
                toward = math.floor((sustain - self.smoothed) / 512.0)
                self.smoothed += n * toward
                self.last = self.smoothed
                if sustain <= 0:
                    self.state = Envelope.OFF
                elif self.ignored_note_off:
                    self.release()
                break
            if self.state == Envelope.RELEASE:
                self.pos += release * n
                if self.pos >= 8388608:
                    self.state = Envelope.OFF
                    self.last = 0.0
                    return -Q31
                self.last = _decay_table("decayTableSmall8", self.pos) \
                    * self.pre / Q32 * 2.0
                break
            return -Q31
        return (self.last - float(1 << 30)) * 2.0


def envelope_blocks(attack: float, decay: float, sustain: float,
                    release: float, nb: int, release_block: int,
                    has_sustain: bool) -> tuple[np.ndarray, int]:
    """Une :class:`Envelope` sur ``nb`` blocs, la touche relâchée au bloc
    ``release_block`` : ses valeurs, et le nombre de blocs après lequel
    elle s'est tue (``nb`` si jamais)."""
    if compiled():
        out = np.empty(int(nb))
        end = _envelope_loop(float(attack), float(decay), float(sustain),
                             float(release), int(release_block),
                             bool(has_sustain), table("decayTableSmall4"),
                             table("decayTableSmall8"), out)
        return out, end
    machine = Envelope()
    machine.note_on(attack, sustain)
    values = np.empty(int(nb))
    end = int(nb)
    for b in range(int(nb)):
        if b == release_block:
            machine.note_off(has_sustain)
        values[b] = machine.render(attack, decay, sustain, release)
        if end == nb and (machine.state == Envelope.OFF
                          or (machine.state > Envelope.DECAY
                              and values[b] <= -Q31)):
            end = b + 1
    return values, end


@_Boucle
def _envelope_loop(attack, decay, sustain, release, release_block,
                   has_sustain, decay4, decay8, out):
    """:func:`envelope_blocks` d'une passe : la machine à états de
    :class:`Envelope`, recopiée ligne à ligne (états 0 attaque, 1 decay,
    2 palier, 3 release, 4 éteinte), ``_decay_table`` en ligne."""
    nb = len(out)
    n = float(BLOCK)
    end = nb
    smoothed = sustain
    ignored = False
    pos = 0.0
    pre = 0.0
    if attack > 245632:
        state = 1
        last = Q31 - 1.0
    else:
        state = 0
        last = 0.0
    for b in range(nb):
        if b == release_block:
            if not has_sustain:
                ignored = True
            elif state < 3:
                state = 3
                pos = 0.0
                pre = last
        value = -Q31
        while True:
            if state == 0:
                pos += attack * n
                if pos >= 8388608:
                    pos = 0.0
                    state = 1
                    continue
                index = int(pos) >> 15
                if index >= 256:
                    level = decay4[256] * 32768.0
                else:
                    frac = int(pos) & 32767
                    level = decay4[index] * (32768 - frac) \
                        + decay4[index + 1] * frac
                last = max(Q31 - 1.0 - level, 1.0)
            elif state == 1:
                toward = math.floor((sustain - smoothed) / 512.0)
                smoothed += n * toward
                smoothed = min(max(smoothed, -Q31), Q31 - 1.0)
                index = int(pos) >> 15
                if index >= 256:
                    level = decay8[256] * 32768.0
                else:
                    frac = int(pos) & 32767
                    level = decay8[index] * (32768 - frac) \
                        + decay8[index + 1] * frac
                last = smoothed + level * (Q31 - 1.0 - smoothed) / Q32 * 2.0
                pos += decay * n
                if pos >= 8388608:
                    state = 2
            elif state == 2:
                toward = math.floor((sustain - smoothed) / 512.0)
                smoothed += n * toward
                last = smoothed
                if sustain <= 0:
                    state = 4
                elif ignored:
                    state = 3
                    pos = 0.0
                    pre = last
            elif state == 3:
                pos += release * n
                if pos >= 8388608:
                    state = 4
                    last = 0.0
                    break
                index = int(pos) >> 15
                if index >= 256:
                    level = decay8[256] * 32768.0
                else:
                    frac = int(pos) & 32767
                    level = decay8[index] * (32768 - frac) \
                        + decay8[index + 1] * frac
                last = level * pre / Q32 * 2.0
            else:
                break
            value = (last - float(1 << 30)) * 2.0
            break
        out[b] = value
        if end == nb and (state == 4 or (state > 1 and value <= -Q31)):
            end = b + 1
    return end


#: Phases de départ d'un LFO (``getLFOInitialPhaseForZero``,
#: ``getLFOInitialPhaseForNegativeExtreme``).
def lfo_start_phase(kind: str, local: bool) -> int:
    """Le LFO 2 (par note) part de son extrême négatif ; le LFO 1 (global)
    de zéro pour le sinus et le triangle."""
    if not local and kind in ("sine", "triangle"):
        return (1 << 30) if kind == "triangle" else 0
    return {"saw": 1 << 31, "sine": 3 << 30}.get(kind, 0)


def lfo_value(kind: str, phase: np.ndarray) -> np.ndarray:
    """La valeur bipolaire (±2³¹) d'un LFO périodique à sa phase."""
    phase = np.asarray(phase, dtype=np.int64)
    if kind == "saw":
        return _signed(phase)
    if kind == "square":
        return np.where(phase < (1 << 31), Q31 - 1.0, -Q31)
    if kind == "sine":
        return _read_table(table("sineWaveSmall"), phase)
    # triangle
    return np.where(phase < (1 << 31), 2.0 * phase - Q31,
                    Q31 - 1.0 - 2.0 * (phase - float(1 << 31)))


def lfo_blocks(kind: str, inc_blocks, phase0: int,
               rng: np.random.Generator) -> np.ndarray:
    """``LFO::render`` bloc par bloc : la valeur au début de chaque bloc,
    puis la phase avance de ``incrément × 128``. Hasard (``sah``) et
    marche aléatoire (``rwalk``) tirent une valeur à chaque période."""
    inc = np.asarray(inc_blocks, dtype=np.int64)
    nb = inc.size
    steps = inc * BLOCK
    starts = (int(phase0) + np.concatenate(([0], np.cumsum(steps)[:-1]))) \
        & MASK32 if nb else np.zeros(0, dtype=np.int64)
    if kind in ("saw", "square", "sine", "triangle"):
        return lfo_value(kind, starts)
    out = np.zeros(nb, dtype=np.float64)
    hold = 0.0
    wraps = (starts + steps) > MASK32
    if kind == "sah":
        for b in range(nb):
            if starts[b] == 0 or wraps[b]:
                hold = float(rng.integers(-(1 << 31), 1 << 31))
            out[b] = hold
        return out
    if kind == "rwalk":
        span = float(4294967295 // 20)
        for b in range(nb):
            if starts[b] == 0:
                hold = span / 2.0 - float(rng.integers(0, int(span)))
            elif wraps[b]:
                # Un pas au hasard, rappelé vers zéro (``holdValue / −16``).
                draw = float(rng.integers(0, int(span)))
                hold = hold + hold / -16.0 + span / 2.0 - draw
                hold = min(max(hold, -Q31), Q31 - 1.0)
            out[b] = hold
        return out
    if kind == "warbler":
        target, speed = 0.0, 0.0
        for b in range(nb):
            step = int(inc[b]) * 2
            if (int(starts[b]) + step * BLOCK) > MASK32:
                target = float(rng.integers(-(1 << 31), 1 << 31))
                speed = 0.0
            speed += BLOCK * ((target - hold) * (step >> 8) / Q32)
            hold = min(max(hold + speed, -Q31), Q31 - 1.0)
            out[b] = hold
        return out
    return lfo_value("triangle", starts)


# --------------------------------------------------------------------------- #
# Effets du son
# --------------------------------------------------------------------------- #

def bitcrush_srr(stereo: np.ndarray, bitcrush: float, srr: float,
                 post_fx: float) -> tuple[np.ndarray, float]:
    """``processSRRAndBitcrushing`` : masque des bits bas, réduction de la
    fréquence d'échantillonnage par interpolation linéaire aller-retour.

    :param bitcrush: valeur brute de ``bitcrushAmount`` (actif au-dessus de
        −2 113 929 216).
    :param srr: valeur brute de ``sampleRateReduction`` (actif si ≠ −2³¹).
    :param post_fx: volume post-effets, réduit au-delà de 4 crans de
        résolution.
    """
    out = np.array(stereo, dtype=np.float64)
    srr_on = srr != -Q31
    mask_srr = None
    if bitcrush >= -2113929216:
        preset = int(bitcrush + Q31) >> 29
        if preset > 4:
            post_fx = post_fx / float(1 << (preset - 4))
        if not srr_on:
            shift = 19 + preset
            out = np.floor(out / float(1 << shift)) * float(1 << shift)
        else:
            # Le firmware masque des échantillons à mi-niveau sur 18 + n
            # bits ; ici ils restent à plein niveau, d'où un bit de plus.
            mask_srr = 19 + preset
    if not srr_on:
        return out, post_fx

    low_inc = float(get_exp(4194304.0, (srr + Q31) / 8.0 / float(1 << 26)))
    high_inc = math.floor(4294967295.0 / math.floor(low_inc / 64.0)) * 64.0
    left = _seq(out[0])
    right = _seq(out[1])
    quantum = float(1 << mask_srr) if mask_srr is not None else 0.0
    _srr_loop(left, right, low_inc, float(high_inc), quantum)
    return np.array([left, right]), post_fx


@_Boucle
def _srr_loop(left, right, low_inc, high_inc, quantum):
    """La réduction d'échantillonnage de :func:`bitcrush_srr`, sur place."""
    last_l = last_r = grab_l = grab_r = old_l = old_r = 0.0
    low_pos = 0.0
    high_pos = 0.0
    step = 1.0 / 4194304.0
    for i in range(len(left)):
        if low_pos < 4194304.0:
            s2 = low_pos * step
            s1 = 1.0 - s2
            old_l, old_r = grab_l, grab_r
            grab_l = last_l * s1 + left[i] * s2
            grab_r = last_r * s1 + right[i] * s2
            if quantum != 0.0:
                grab_l = math.floor(grab_l / quantum) * quantum
                grab_r = math.floor(grab_r / quantum) * quantum
            low_pos += low_inc
            high_pos = (low_pos % 4194304.0) * high_inc / 4194304.0
        low_pos -= 4194304.0
        last_l, last_r = left[i], right[i]
        s2 = min(high_pos, 4194303.0) * step
        s1 = 1.0 - s2
        left[i] = old_l * s1 + grab_l * s2
        right[i] = old_r * s1 + grab_r * s2
        high_pos += high_inc


#: ``kModFXBufferSize`` et les temps du flanger, en échantillons.
_MOD_FX_SIZE = 512
_MOD_FX_MAX = float((_MOD_FX_SIZE - 1) << 16)
_FLANGER_MIN = float(3 << 16)
_FLANGER_AMPLITUDE = _MOD_FX_MAX - _FLANGER_MIN
_FLANGER_OFFSET = (_MOD_FX_MAX + _FLANGER_MIN) / 2.0


def _mod_fx_feedback(feedback_param: float) -> float:
    """``setupModFXWFeedback`` : la rétroaction du flanger et du phaser,
    depuis ``modFXFeedback`` (0 au réglage neutre donne 0,76)."""
    a = math.floor(feedback_param / 2.0)
    b = 2147483647.0 - math.floor((a + 1073741824.0) / 4.0) * 3.0
    c = math.floor(b * b / Q32)
    d = math.floor(b * c / Q32)
    return Q31 - d * 4.0


def _mod_fx_volume_cut(feedback: float) -> float:
    """La baisse de volume qui accompagne la rétroaction."""
    sq = feedback * feedback / Q32 * 2.0
    sq2 = sq * sq / Q32 * 2.0
    sq2 = sq2 * sq / Q32 * 2.0
    sq2 = math.floor(sq2 * sq2 / Q32 / 16.0) * 23.0
    return (Q31 - 1.0 - sq2) / Q32


def mod_fx(stereo: np.ndarray, kind: str, rate_inc: float, depth: float,
           offset_param: float, feedback_param: float,
           post_fx: float) -> tuple[np.ndarray, float]:
    """``ModFXProcessor::processModFX`` : chorus, flanger, phaser.

    :param rate_inc: incrément de phase du LFO (``modFXRate`` final).
    :param depth: ``modFXDepth`` final (neutre 526 133 494).
    :param offset_param: ``modFXOffset`` brut ; ``feedback_param`` :
        ``modFXFeedback`` brut.
    Rend le signal et le volume post-effets corrigé.
    """
    kind = str(kind or "")
    if kind in ("", "none", "grainFX"):
        return stereo, post_fx
    n = stereo.shape[1]
    phase = (np.arange(n, dtype=np.int64) * int(rate_inc)) & MASK32
    if kind == "phaser":
        feedback = _mod_fx_feedback(feedback_param)
        post_fx = post_fx * _mod_fx_volume_cut(feedback)
        lfo = lfo_value("sine", phase)
        return _phaser(stereo, lfo, depth, feedback), post_fx
    if kind == "flanger":
        feedback = _mod_fx_feedback(feedback_param)
        post_fx = post_fx * _mod_fx_volume_cut(feedback) * 2.0
        lfo = lfo_value("triangle", phase)
        times = lfo * _FLANGER_AMPLITUDE / Q32 + _FLANGER_OFFSET
        return _flanger(stereo, times, -times + 2.0 * _FLANGER_OFFSET,
                        feedback / Q31), post_fx
    # Chorus, chorus stéréo, dimension — et le « tape warble », approché
    # par un chorus.
    centre = math.floor(offset_param / 2.0) + 1073741824.0
    offset = _MOD_FX_MAX * centre / Q32
    amount = offset * depth / Q32 * 4.0
    post_fx = post_fx * 1518500250.0 / Q32 * 2.0
    lfo = lfo_value("triangle" if kind == "dimension" else "sine", phase)
    left_time = lfo * amount / Q32 + offset
    right_time = -lfo * amount / Q32 + offset
    left = _read_mod_fx(stereo[0], left_time)
    right = _read_mod_fx(stereo[1], right_time)
    if kind == "dimension":
        return np.array([left * 4.0, right * 4.0]), post_fx
    return np.array([stereo[0] + left * 2.0, stereo[1] + right * 2.0]), post_fx


def _read_mod_fx(dry: np.ndarray, times: np.ndarray) -> np.ndarray:
    """La lecture du tampon de 512 échantillons d'un chorus (sans
    rétroaction : le tampon garde le signal sec), à mi-niveau comme le
    firmware (``strength1 = 65535 << 15``)."""
    n = dry.size
    if compiled():
        out = np.empty(n)
        _mod_fx_loop(np.ascontiguousarray(dry, dtype=np.float64),
                     np.ascontiguousarray(times, dtype=np.float64), out)
        return out
    steps = np.floor(times / 65536.0).astype(np.int64)
    frac = (times - steps * 65536.0) / 65536.0
    # Un retard nul relit l'échantillon écrit 512 pas plus tôt.
    delay1 = np.where(steps == 0, _MOD_FX_SIZE, steps)
    delay2 = steps + 1
    padded = np.concatenate([np.zeros(_MOD_FX_SIZE + 1), dry])
    pos = np.arange(n) + _MOD_FX_SIZE + 1
    a = padded[pos - delay1]
    b = padded[pos - delay2]
    return (a * (1.0 - frac) + b * frac) * 0.5


@_Boucle
def _mod_fx_loop(dry, times, out):
    """:func:`_read_mod_fx` d'une passe : avant le début, le tampon est
    muet."""
    n = len(dry)
    for i in range(n):
        t = times[i]
        step = math.floor(t / 65536.0)
        frac = (t - step * 65536.0) / 65536.0
        back = _MOD_FX_SIZE if step == 0 else step
        j = i - back
        a = dry[j] if 0 <= j < n else 0.0
        j = i - step - 1
        b = dry[j] if 0 <= j < n else 0.0
        out[i] = (a * (1.0 - frac) + b * frac) * 0.5


def _flanger(stereo: np.ndarray, left_time: np.ndarray,
             right_time: np.ndarray, feedback: float) -> np.ndarray:
    """Le flanger : la sortie retardée, pondérée par la rétroaction,
    réinjectée dans le tampon et ajoutée au signal."""
    out = np.array(stereo, dtype=np.float64)
    for channel, times in ((0, left_time), (1, right_time)):
        res = _out(out.shape[1])
        _flanger_loop(_seq(stereo[channel] + DENORMAL_GUARD), _seq(times),
                      float(feedback), _zeros(_MOD_FX_SIZE), res)
        out[channel] = _result(res)
    return out


@_Boucle
def _flanger_loop(dry, times, feedback, buf, out):
    """Un canal de :func:`_flanger` ; ``buf`` : le tampon de 512 cases."""
    size = len(buf)
    write = 0
    for i in range(len(dry)):
        v = dry[i]
        t = times[i]
        step = int(t // 65536.0)
        frac = (t - step * 65536.0) / 65536.0
        # Le masque garde l'index dans le tampon, quel que soit le temps.
        p1 = (write - step) & (size - 1)
        p2 = (p1 - 1) & (size - 1)
        delayed = (buf[p1] * (1.0 - frac) + buf[p2] * frac) * 0.5
        wet = delayed * feedback * 2.0
        buf[write] = wet + v
        out[i] = v + wet
        write = (write + 1) & (size - 1)


def _phaser(stereo: np.ndarray, lfo: np.ndarray, depth: float,
            feedback: float) -> np.ndarray:
    """Le phaser : six passe-tout du premier ordre balayés par le LFO, avec
    rétroaction (``processOnePhaserSample``)."""
    a1 = (float(1 << 30) - ((lfo + Q31) / 2.0) * depth / Q32) / float(1 << 30)
    fb = float(feedback / Q31)
    out = np.array(stereo, dtype=np.float64)
    coef = _seq(a1)
    for channel in (0, 1):
        res = _out(out.shape[1])
        _phaser_loop(_seq(stereo[channel] + DENORMAL_GUARD), coef, fb, res)
        out[channel] = _result(res)
    return out


@_Boucle
def _phaser_loop(dry, coef, fb, out):
    """Un canal de :func:`_phaser`."""
    mem = p1 = p2 = p3 = p4 = p5 = p6 = 0.0
    for i in range(len(dry)):
        v = dry[i]
        a = coef[i]
        mem = v + mem * fb
        # Les six passe-tout, déroulés.
        was = mem
        mem = p1 - mem * a
        p1 = mem * a + was
        was = mem
        mem = p2 - mem * a
        p2 = mem * a + was
        was = mem
        mem = p3 - mem * a
        p3 = mem * a + was
        was = mem
        mem = p4 - mem * a
        p4 = mem * a + was
        was = mem
        mem = p5 - mem * a
        p5 = mem * a + was
        was = mem
        mem = p6 - mem * a
        p6 = mem * a + was
        out[i] = v + mem


def equalizer(stereo: np.ndarray, bass: float, treble: float,
              bass_freq: float, treble_freq: float) -> np.ndarray:
    """``ModControllableAudio::doEQ`` : un passe-bas sépare l'aigu
    (≈ 2,8 kHz au neutre), un second isole le grave (≈ 200 Hz) ; chacun est
    rajouté avec son gain. Valeurs brutes des quatre réglages."""
    do_bass = bass != 0
    do_treble = treble != 0
    if not (do_bass or do_treble):
        return stereo
    out = np.array(stereo, dtype=np.float64)
    positive = math.floor(bass / 2.0) + 1073741824.0
    bass_amount = (positive * positive / Q32 * 2.0 - 536870912.0) \
        / float(1 << 29)
    positive = math.floor(treble / 2.0) + 1073741824.0
    treble_amount = positive * positive / Q32 * 2.0 / float(1 << 29)
    for channel in (0, 1):
        x = out[channel]
        if do_treble:
            k_t = float(get_exp(700000000.0, math.floor(treble_freq / 32.0)
                                * 6.0 / float(1 << 26))) * 2.0 / Q32
            smooth, _ = one_pole(x, min(k_t, 1.0))
            treble_only = x - smooth
            x = smooth
        if do_bass:
            k_b = float(get_exp(120000000.0, math.floor(bass_freq / 32.0)
                                * 6.0 / float(1 << 26))) / Q32
            bass_only, _ = one_pole(x, min(k_b, 1.0))
        y = x.copy()
        if do_treble:
            y = y + treble_only * treble_amount
        if do_bass:
            y = y + bass_only * bass_amount
        out[channel] = y
    return out


#: Réponse impulsionnelle du delay analogique (``ImpulseResponseProcessor``).
_ANALOG_IR = np.array([
    -3203916, 8857848, 24813136, 41537808, 35217472, 15195632, -27538592,
    -61984128, 1944654848, 1813580928, 438462784, 101125088, 6042048,
    -22429488, -46218864, -56638560, -64785312, -52108528, -37256992,
    -11863856, 1390352, 14663296, 12784464, 14254800, 5690912, 4490736],
    dtype=np.float64) / Q32


def delay_samples(rate) -> np.ndarray:
    """La longueur du tampon du delay (``getIdealBufferSizeFromRate``) :
    16 384 échantillons au réglage neutre (0,37 s), de 1 à 88 200."""
    rate = np.maximum(np.asarray(rate, dtype=np.float64), 1.0)
    return np.clip(np.floor(16384.0 * float(1 << 24) / rate), 1.0, 88200.0)


def delay(stereo: np.ndarray, length, feedback, ping_pong: bool,
          analog: bool) -> np.ndarray:
    """``Delay::process`` : ce qui revient du tampon est multiplié par la
    rétroaction (``feedback / 2³⁰`` : l'unité au réglage 25) — saturé
    doucement en mode analogique après un filtre de 26 coefficients,
    écrêté sinon —, débarrassé de son continu, renvoyé croisé en
    ping-pong, et ajouté au signal.

    :param length: longueur du tampon par bloc (échantillons).
    :param feedback: ``delayFeedback`` final par bloc.

    L'écho revient **un échantillon avant** la longueur du tampon : celui-ci
    a 20 cases de plus (``delaySpaceBetweenReadAndWrite``), l'écriture se
    fait 20 cases derrière la lecture, et la lecture avance avant de lire.
    Sauf au premier tour : le delay qui démarre écrit d'abord dans un
    tampon secondaire, une case plus loin (``writeNative`` après
    ``clearAndMoveOn``), recopié dans le principal au bout d'une longueur
    (``getAmountToWriteBeforeReadingBegins``) — le premier écho revient à
    la longueur entière. Mesuré sur la machine le 23 octobre 2026 : sans
    cela, les échos dérivaient d'un échantillon par répétition.
    """
    stereo = np.asarray(stereo, dtype=np.float64)
    n = stereo.shape[1]
    nb = -(-n // BLOCK)
    length = np.broadcast_to(
        np.atleast_1d(np.asarray(length, dtype=np.float64)), (nb,))
    feedback = np.broadcast_to(
        np.atleast_1d(np.asarray(feedback, dtype=np.float64)), (nb,))
    out = stereo.copy()
    longest = int(np.max(length)) + 2
    history = np.zeros((2, longest + n + 2), dtype=np.float64)
    base = longest + 1
    fir_state = np.zeros((2, _ANALOG_IR.size - 1))
    dc = np.zeros(2)
    # Les blocs où longueur et retour ne bougent pas s'enchaînent : on
    # avance alors d'une longueur de tampon à la fois, et non d'un bloc.
    changes = np.nonzero((length[1:] != length[:-1])
                         | (feedback[1:] != feedback[:-1]))[0] + 1
    run_end = np.append(changes * BLOCK, n)
    first_pass = int(length[0]) if nb else 0
    pos = 0
    while pos < n:
        b = pos // BLOCK
        d = max(1, int(length[b]) - 1)
        limit = int(run_end[np.searchsorted(run_end, pos, side="right")])
        chunk = min(limit - pos, d, n - pos)
        shift = 1 if pos < first_pass else 0
        if shift:
            chunk = min(chunk, first_pass - pos)
        fb = float(feedback[b])
        sl = slice(pos, pos + chunk)
        read = history[:, base + pos - d:base + pos - d + chunk].copy()
        if analog:
            joined = np.concatenate([fir_state, read], axis=1)
            fir_state = joined[:, -(_ANALOG_IR.size - 1):]
            filtered = np.stack([np.convolve(joined[c], _ANALOG_IR,
                                             mode="valid") for c in (0, 1)])
            work = tanh_unknown(filtered * fb / Q32, 8) * 4.0
        else:
            work = np.clip(read * fb / Q32, -float(1 << 29),
                           float(1 << 29) - 1.0) * 4.0
        if chunk <= BLOCK:
            smooth, dc = one_pole_short(work, 1.0 / 2048.0, dc)
        else:
            smooth = np.empty_like(work)
            for c in (0, 1):
                smooth[c], dc[c] = one_pole(work[c], 1.0 / 2048.0, dc[c])
        work = work - smooth
        dry = stereo[:, sl]
        if ping_pong:
            back = np.stack([work[1], (dry[0] + dry[1]) / 2.0 + work[0]])
        else:
            back = work + dry
        history[:, base + pos + shift:base + pos + chunk + shift] = back
        out[:, sl] = dry + work
        pos += chunk
    return out


# --------------------------------------------------------------------------- #
# Réverbérations
# --------------------------------------------------------------------------- #

@dataclass
class ReverbSettings:
    """La réverbération d'un morceau (``<reverb>``), en valeurs 0..1."""

    model: int = 1          # 0 Freeverb, 1 Mutable, 2 Digital
    room_size: float = 0.6
    damping: float = 0.72
    width: float = 1.0
    hpf: float = 0.0
    lpf: float = 1.0
    pan: int = 0


def _reverb_cutoff(f: float, high_pass: bool) -> float:
    """``calcFilterCutoff`` (``reverb/base.hpp``)."""
    lo, hi = (20.0, 150.0) if high_pass else (0.0, 5083.74)
    hz = lo + (math.exp(1.5 * f) - 1.0) * hi
    fc = hz / SR
    return fc / (1.0 + fc)


def reverb(send: np.ndarray, settings: ReverbSettings) -> np.ndarray:
    """La réverbération du morceau, sur la somme des envois (mono, échelle
    entière) ; rend la stéréo à ajouter au mélange. Le modèle « Digital »
    retombe sur « Mutable »."""
    send = np.asarray(send, dtype=np.float64)
    if send.size == 0 or not np.any(send):
        return np.zeros((2, send.size))
    left_amp, right_amp = pan_amplitudes(settings.pan)
    volume = float(1 << 29)
    gains = (float(left_amp) * volume, float(right_amp) * volume)
    if int(settings.model) == 0:
        return _freeverb(send, settings, gains)
    return _mutable(send, settings, gains)


def _delay_line_read(history: np.ndarray, now: int, offsets: np.ndarray
                     ) -> np.ndarray:
    """La valeur écrite ``offsets`` échantillons plus tôt (``at(i)``)."""
    return history[now - offsets]


def _mutable(send: np.ndarray, settings: ReverbSettings,
             gains: tuple[float, float]) -> np.ndarray:
    """La réverbération « Mutable » (``reverb/mutable.hpp``) : quatre
    passe-tout de diffusion, puis une boucle de deux branches — lecture
    modulée, passe-bas, deux passe-tout, retard — dont chacune donne une
    voie. Calculée par blocs plus courts que le plus court de ses retards
    bouclés, donc exactement."""
    n = send.size
    room = 0.01 + float(settings.room_size) * 0.97
    damping = min(max(math.log2(float(settings.damping) * 50.0 + 1.0) / 5.7,
                      0.0), 1.0)
    klp = 0.01 + (1.0 - damping) * 0.99
    kap = 0.1 + float(settings.width) * 0.8
    hp_cut = _reverb_cutoff(float(settings.hpf), True)
    lp_cut = _reverb_cutoff(float(settings.lpf), False)

    x = send / 2147483647.0
    # Diffusion d'entrée : chaque passe-tout boucle sur L−1 échantillons.
    for length in (150, 214, 319, 527):
        x = _allpass_stream(x, length - 1, kap)
    apout = x

    lfo1, lfo2 = _reverb_lfos(n)
    if compiled():
        out_l = np.empty(n)
        out_r = np.empty(n)
        _mutable_loop(np.ascontiguousarray(apout), np.ascontiguousarray(lfo1),
                      np.ascontiguousarray(lfo2), room, klp, kap, out_l,
                      out_r)
        return _mutable_output(out_l, out_r, hp_cut, lp_cut, gains)
    tail = 6400
    total = n + tail
    hist1 = np.zeros(total + 1)   # del1, indexé par échantillon (+tail)
    hist2 = np.zeros(total + 1)
    ap = {length: np.zeros(total + 1) for length in (2182, 2690, 2525, 2197)}
    out_l = np.zeros(n)
    out_r = np.zeros(n)
    lp1 = lp2 = 0.0
    block = 2048
    for start in range(0, n, block):
        stop = min(n, start + block)
        idx = np.arange(start, stop) + tail
        a_in = apout[start:stop]
        # Branche « droite » : lit del2, écrit del1.
        offset = 6261.0 + 50.0 * lfo2[start:stop]
        whole = offset.astype(np.int64)
        frac = offset - whole
        r = hist2[idx - whole] * (1.0 - frac) + hist2[idx - whole - 1] * frac
        c = a_in + r * room
        c, lp1 = one_pole(c, klp, lp1)
        c = _allpass_block(c, ap[2182], idx, 2181, -kap)
        c = _allpass_block(c, ap[2690], idx, 2689, kap)
        hist1[idx] = c
        out_r[start:stop] = c * 2.0
        # Branche « gauche » : lit del1, écrit del2.
        offset = 4460.0 + 40.0 * lfo1[start:stop]
        whole = offset.astype(np.int64)
        frac = offset - whole
        r = hist1[idx - whole] * (1.0 - frac) + hist1[idx - whole - 1] * frac
        c = a_in + r * room
        c, lp2 = one_pole(c, klp, lp2)
        c = _allpass_block(c, ap[2525], idx, 2524, -kap)
        c = _allpass_block(c, ap[2197], idx, 2196, kap)
        hist2[idx] = c
        out_l[start:stop] = c * 2.0
    return _mutable_output(out_l, out_r, hp_cut, lp_cut, gains)


def _mutable_output(out_l: np.ndarray, out_r: np.ndarray, hp_cut: float,
                    lp_cut: float, gains: tuple[float, float]) -> np.ndarray:
    """Les filtres de sortie de :func:`_mutable`, l'écrêtage et le gain."""
    out = np.zeros((2, out_l.size))
    for channel, wet, gain in ((0, out_l, gains[0]), (1, out_r, gains[1])):
        low, _ = one_pole(wet, hp_cut)
        wet = wet - low
        wet, _ = one_pole(wet, lp_cut)
        wet = np.clip(wet * 15.0 * Q32, -Q31, 2147483520.0)
        out[channel] = wet * gain / Q32
    return out


#: Les tampons de :func:`_mutable_loop` : une puissance de deux au-delà du
#: plus long retard lu (6 261 + 50 + 1 échantillons).
_MUTABLE_SIZE = 8192


@_Boucle
def _mutable_loop(apout, lfo1, lfo2, room, klp, kap, out_l, out_r):
    """La boucle de :func:`_mutable`, échantillon par échantillon, sur des
    tampons circulaires. Chaque lecture remonte plus loin qu'un bloc de la
    version Python : les deux calculs sont les mêmes."""
    mask = _MUTABLE_SIZE - 1
    hist1 = np.zeros(_MUTABLE_SIZE)
    hist2 = np.zeros(_MUTABLE_SIZE)
    ap1 = np.zeros(_MUTABLE_SIZE)
    ap2 = np.zeros(_MUTABLE_SIZE)
    ap3 = np.zeros(_MUTABLE_SIZE)
    ap4 = np.zeros(_MUTABLE_SIZE)
    lp1 = 0.0
    lp2 = 0.0
    for i in range(len(apout)):
        a_in = apout[i]
        now = i & mask
        # Branche « droite » : lit del2, écrit del1.
        offset = 6261.0 + 50.0 * lfo2[i]
        whole = int(offset)
        frac = offset - whole
        r = hist2[(i - whole) & mask] * (1.0 - frac) \
            + hist2[(i - whole - 1) & mask] * frac
        lp1 += klp * (a_in + r * room - lp1)
        tail = ap1[(i - 2181) & mask]
        fed = lp1 + tail * -kap
        ap1[now] = fed
        c = fed * kap + tail
        tail = ap2[(i - 2689) & mask]
        fed = c + tail * kap
        ap2[now] = fed
        c = fed * -kap + tail
        hist1[now] = c
        out_r[i] = c * 2.0
        # Branche « gauche » : lit del1, écrit del2.
        offset = 4460.0 + 40.0 * lfo1[i]
        whole = int(offset)
        frac = offset - whole
        r = hist1[(i - whole) & mask] * (1.0 - frac) \
            + hist1[(i - whole - 1) & mask] * frac
        lp2 += klp * (a_in + r * room - lp2)
        tail = ap3[(i - 2524) & mask]
        fed = lp2 + tail * -kap
        ap3[now] = fed
        c = fed * kap + tail
        tail = ap4[(i - 2196) & mask]
        fed = c + tail * kap
        ap4[now] = fed
        c = fed * -kap + tail
        hist2[now] = c
        out_l[i] = c * 2.0


def _allpass_stream(x: np.ndarray, delay_len: int, k: float) -> np.ndarray:
    """Un passe-tout de Schroeder sur tout un signal, par tranches de son
    retard : ``w = x + k·w[−L]``, ``y = −k·w + w[−L]``."""
    n = x.size
    if compiled():
        y = np.empty(n)
        _allpass_loop(np.ascontiguousarray(x, dtype=np.float64), float(k),
                      np.zeros(int(delay_len)), y)
        return y
    # ``w[i + L]`` garde ce qui a été écrit à l'échantillon i.
    w = np.zeros(n + delay_len)
    y = np.zeros(n)
    for start in range(0, n, delay_len):
        stop = min(n, start + delay_len)
        tail = w[start:stop]
        cur = x[start:stop] + k * tail
        w[start + delay_len:stop + delay_len] = cur
        y[start:stop] = -k * cur + tail
    return y


@_Boucle
def _allpass_loop(x, k, history, out):
    """:func:`_allpass_stream` échantillon par échantillon ; ``history`` :
    un tour de retard, en tampon circulaire."""
    size = len(history)
    pos = 0
    for i in range(len(x)):
        tail = history[pos]
        cur = x[i] + k * tail
        history[pos] = cur
        out[i] = -k * cur + tail
        pos += 1
        if pos == size:
            pos = 0


def _allpass_block(c: np.ndarray, history: np.ndarray, idx: np.ndarray,
                   delay_len: int, k: float) -> np.ndarray:
    """Un passe-tout de la boucle, sur un bloc plus court que son retard ;
    ``history`` garde ce qu'il a écrit, indexé par échantillon."""
    tail = history[idx - delay_len]
    fed = c + tail * k
    history[idx] = fed
    return fed * -k + tail


def _reverb_lfos(n: int) -> tuple[np.ndarray, np.ndarray]:
    """Les deux LFO de la réverbération (cosinus approché de Mutable, 0,5 et
    0,3 Hz), qui avancent d'un pas toutes les 32 échantillons ; valeurs de
    0 à 1."""
    out = []
    for hz in (0.5, 0.3):
        f = hz / SR * 32.0
        sign = 16.0
        f = f - 0.25
        if f < 0.0:
            f = -f
        elif f > 0.5:
            f = f - 0.5
        else:
            sign = -16.0
        coef = sign * f * (1.0 - 2.0 * f)
        y0, y1 = coef * 0.25, 0.5
        steps = n // 32 + 2
        values = np.empty(steps)
        values[0] = y0 + 0.5
        for s in range(1, steps):
            temp = y1
            y1 = coef * y1 - y0
            y0 = temp
            values[s] = y0 + 0.5
        # Le pas tombe à l'échantillon 31, 63… (``write_ptr & 31``).
        which = (np.arange(n) + 1) // 32
        out.append(values[which])
    return out[0], out[1]


_COMBS = (1116, 1188, 1277, 1356, 1422, 1491, 1557, 1617)
_ALLPASSES = (556, 441, 341, 225)


def _freeverb(send: np.ndarray, settings: ReverbSettings,
              gains: tuple[float, float]) -> np.ndarray:
    """Freeverb (``reverb/freeverb/``), la réverbération des morceaux
    enregistrés sans modèle : huit filtres en peigne amortis par voie, puis
    quatre passe-tout ; écart stéréo de 23 échantillons."""
    n = send.size
    roomsize = float(settings.room_size) * 0.28 + 0.7
    damp = float(settings.damping) * 0.4
    width = float(settings.width)
    wet2 = ((1.0 - width) / 2.0) / (width / 2.0 + 0.5)
    low, _ = one_pole(send, 1.0 / 2048.0)
    x = send - low
    outs = []
    for spread in (0, 23):
        acc = np.zeros(n)
        for length in _COMBS:
            acc += _comb(x, length + spread, roomsize, damp)
        for length in _ALLPASSES:
            acc = _freeverb_allpass(acc, length + spread)
        outs.append(acc)
    # ``multiply_32x32_rshift32_rounded(x, wet2)`` : wet2 sur 2³¹, d'où /2.
    left = (outs[0] + outs[1] * wet2 / 2.0) * 2.0
    right = (outs[1] + left * wet2 / 2.0) * 2.0
    return np.array([left * gains[0] / Q32, right * gains[1] / Q32])


def _comb(x: np.ndarray, length: int, room: float, damp: float) -> np.ndarray:
    """Un peigne de Freeverb : la sortie est ce qui a été écrit ``length``
    échantillons plus tôt ; on réécrit l'entrée plus la sortie amortie."""
    n = x.size
    written = np.zeros(n + length)
    out = np.zeros(n)
    store = 0.0
    for start in range(0, n, length):
        stop = min(n, start + length)
        read = written[start:stop]
        smoothed, store = one_pole(read, 1.0 - damp, store)
        written[start + length:stop + length] = x[start:stop] + smoothed * room
        out[start:stop] = read
    return out


def _freeverb_allpass(x: np.ndarray, length: int) -> np.ndarray:
    """Le passe-tout de Freeverb : sortie ``−x + tampon``, écriture
    ``x + tampon/2``."""
    n = x.size
    written = np.zeros(n + length)
    out = np.zeros(n)
    for start in range(0, n, length):
        stop = min(n, start + length)
        buf = written[start:stop]
        out[start:stop] = -x[start:stop] + buf
        written[start + length:stop + length] = x[start:stop] + buf / 2.0
    return out


# --------------------------------------------------------------------------- #
# Sortie
# --------------------------------------------------------------------------- #

#: Le gain de base du compresseur maître d'un morceau : 0,85 népers
#: (``Song::Song``, ``setBaseGain(0.85)``, « pour retrouver 1,0 ») — et non
#: 1,35, la valeur par défaut de la classe, qu'avait d'abord prise ce
#: portage. Mesuré sur la machine (export avec Song FX, 4 novembre 2026) :
#: avec 1,35, l'écoute du PC sortait 4,4 dB trop fort.
SONG_COMPRESSOR_GAIN = 0.85

#: Du mélange (échelle entière) au tampon de sortie (``renderSongFX``) : le
#: volume maître de 167 763 968 passe par les filtres du morceau, qui lui
#: retirent 20 % même ouverts (``1720000000 << 1`` dans
#: ``FilterSet::setConfig``) ; le compresseur maître au repos le multiplie
#: par ``exp(0,85)``.
_MASTER_VOLUME = math.floor(167763968 * 1720000000 / Q32) * 2.0
_COMPRESSOR_SCALE = math.exp(SONG_COMPRESSOR_GAIN) \
    * math.floor(_MASTER_VOLUME / 2.0) / 2.0 * 16.0 / Q32

#: Du mélange à la sortie audio, au gain près : puis ``<< 8`` vers le
#: convertisseur (``doSomeOutputting``), qui écrête à ±2³¹ — un mélange de
#: 2²⁴ sort à 0,29 de pleine échelle.
OUTPUT_GAIN = _COMPRESSOR_SCALE * 128.0 / Q31


def output_stage(stereo: np.ndarray) -> np.ndarray:
    """Du mélange (``(2, n)``, échelle entière) à la sortie audio, pleine
    échelle 1 : gain du morceau et du compresseur maître, puis la saturation
    adoucie de ce dernier (``getTanHAntialiased``, saturation 3), qui, aux
    niveaux d'écoute, moyenne deux échantillons successifs — −1,6 dB à
    8 kHz, −7,6 dB à 16 kHz, mesurés sur la machine. :data:`OUTPUT_GAIN`
    en est la part linéaire."""
    x = np.asarray(stereo, dtype=np.float64) * _COMPRESSOR_SCALE
    out = np.empty_like(x)
    for c in range(x.shape[0]):
        out[c], _ = tanh_antialiased(x[c], 3)
    return out * (128.0 / Q31)
