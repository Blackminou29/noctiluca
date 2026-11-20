# -*- coding: utf-8 -*-
"""L'étirement d'un échantillon, pour l'écoute sur l'ordinateur.

Jusqu'au 20 novembre 2026, l'écoute l'ignorait : un échantillon joué plus
haut y était toujours lu plus vite. Ce module transcrit l'étireur du
firmware 1.3 (commit ``102cf9f``) :

* **la vitesse** (``VoiceUnisonPartSource::getSpeedParamForNoSyncing``) :
  avec ``timeStretchEnable``, la hauteur et la vitesse sont indépendantes —
  le rapport d'étirement compense la transposition, l'échantillon garde sa
  durée ; ``timeStretchAmount`` (−48 à +48 demi-tons,
  ``timeStretchAdjustTable``) l'accélère ou le ralentit ;
* **la percussivité** (``Sample::fillPercCache``) : la pente du signal,
  lissée sur deux pôles, et sa variation au milieu de chaque « pixel » de
  128 échantillons, saturée sur un octet ; elle se calcule au fil de la
  lecture, à raison de six échantillons au plus par échantillon rendu ;
* **l'étireur** (``TimeStretcher::hopEnd``) : deux têtes de lecture, l'une
  fondue dans l'autre. À chaque fin de saut, la longueur du suivant se tire
  entre deux bornes qui dépendent de la vitesse (tables ``minHopSize``…),
  vers la zone la plus percussive ; la nouvelle tête se cale ensuite, à
  l'échantillon près et entre deux, là où trois moyennes glissantes
  ressemblent le plus à celles de l'ancienne ; le fondu, linéaire, dure une
  part du saut plus une longueur fixe.

Chaque tête lit comme une lecture ordinaire (:func:`.dsp.read_positions`,
le noyau sinc du firmware). La voix s'arrête quand la position étirée
atteint la fin du fichier, ou quand les deux têtes l'ont dépassée ; en
boucle, la position repart du début et un saut se force si la tête neuve
s'était éteinte (``reInit``). Un échantillon à rebours s'étire retourné
(la machine tient pour lui un cache à rebours, aux pixels décalés d'un
échantillon). Restent hors du portage : l'étirement des clips audio calés
sur le tempo
(``sequenceSyncLengthTicks``), le saut dans la pré-marge d'une boucle
(``TIMESTRETCHER_LEVEL_IF_ACTIVE``), les sauts différés quand trois voix en
font un dans la même passe, le cache de percussivité gardé d'une note à
l'autre et les tampons du firmware (``TIME_STRETCH_ENABLE_BUFFER``, éteint
en 1.3). Les tirages au sort viennent de ``CONG`` à graine fixe : la
machine, elle, tire les siens au hasard.
"""

from __future__ import annotations

import numpy as np

from . import dsp

__all__ = ["UNITY", "percussiveness", "speed_ratio", "stretch"]

UNITY = dsp.SAMPLE_UNITY
_PERC_MAG = 7                      # kPercBufferReductionMagnitude
_PERC_SIZE = 1 << _PERC_MAG
_FIRST_HOP = 200                   # TimeStretch::kDefaultFirstHopLength
_N_AVG = 3                         # Crossfade::kNumMovingAverages
_AVG_LEN = 35                      # Crossfade::kMovingAverageLength
_PERC_PER_SAMPLE = 6               # maxNumSamplesToProcess, sans cache
_ZONE_GAP = 2048                   # au-delà, fillPercCache ouvre une zone

# Les tables de ``time_stretcher.cpp`` : « fine » sur ±1 octave de vitesse,
# par demi-ton ; « coarse » de −2 à +2 octaves.
_MIN_HOP_COARSE = (2500, 3000, 3000, 600, 300)
_MIN_HOP_FINE = (3000, 3000, 3000, 3000, 3000, 3000, 3000, 3000,
                 3000, 2500, 2000, 1500, 1000, 900, 800, 700, 600)
_MAX_HOP_COARSE = (5000, 6500, 11000, 4000, 2500)
_MAX_HOP_FINE = (6500, 7000, 8000, 9000, 9500, 9750, 10000, 11000,
                 11000, 7500, 8000, 6500, 5000, 4750, 4500, 4250, 4000)
_XF_PROP_COARSE = (200, 160, 0, 9, 9)
_XF_PROP_FINE = (160, 140, 125, 110, 90, 70, 50, 20,
                 0, 20, 20, 20, 20, 17, 14, 11, 9)
_XF_ABS_COARSE = (10, 10, 60, 40, 20)
_XF_ABS_FINE = (10, 10, 10, 10, 10, 10, 10, 170,
                60, 90, 20, 30, 40, 40, 40, 40, 40)
_RANDOM_COARSE = (85, 120, 0, 0, 0)
_RANDOM_FINE = (120, 95, 70, 45, 20, 15, 10, 10,
                0, 0, 0, 0, 0, 0, 0, 0, 0)

#: ``timeStretchAdjustTable`` (``lookuptables.cpp``) : 2^((i − 48)/12) sur
#: 2²⁴, de −48 à +48 demi-tons.
_ADJUST = (
    1048576, 1110928, 1176987, 1246974, 1321123, 1399681, 1482910, 1571089,
    1664511, 1763488, 1868350, 1979448, 2097152, 2221855, 2353974, 2493948,
    2642246, 2799362, 2965821, 3142178, 3329021, 3526975, 3736700, 3958896,
    4194304, 4443710, 4707947, 4987896, 5284492, 5598724, 5931642, 6284355,
    6658043, 7053950, 7473400, 7917792, 8388608, 8887421, 9415894, 9975792,
    10568984, 11197448, 11863283, 12568711, 13316085, 14107901, 14946800,
    15835583, 16777216, 17774841, 18831788, 19951585, 21137968, 22394897,
    23726566, 25137421, 26632170, 28215802, 29893600, 31671166, 33554432,
    35549682, 37663576, 39903169, 42275935, 44789793, 47453133, 50274843,
    53264341, 56431603, 59787201, 63342333, 67108864, 71099365, 75327153,
    79806339, 84551870, 89579586, 94906266, 100549686, 106528681,
    112863206, 119574402, 126684666, 134217728, 142198729, 150654306,
    159612677, 169103741, 179159172, 189812531, 201099372, 213057363,
    225726413, 239148804, 253369332, 268435456)


def speed_ratio(phase_increment: int, neutral: int, independent: bool,
                amount: int) -> int:
    """``getSpeedParamForNoSyncing`` : le rapport d'étirement, sur 2²⁴.

    :param phase_increment: l'incrément de lecture de la note (hauteur).
    :param neutral: celui qui lirait le fichier à sa hauteur
        (``(fréquence << 24) / 44 100``).
    :param independent: ``timeStretchEnable`` — la hauteur et la vitesse
        indépendantes.
    :param amount: ``timeStretchAmount``, en demi-tons."""
    ratio = UNITY
    inc = int(phase_increment)
    if independent and inc > 0 and inc != int(neutral):
        ratio = (int(neutral) << 24) // inc
    amount = int(amount)
    if amount:
        ratio = (ratio * _ADJUST[max(-48, min(48, amount)) + 48]) >> 24
    # Sur 32 bits signés là-bas : au-delà de 128 fois plus vite, la machine
    # déborde ; l'écoute s'en tient au plafond.
    return min(ratio, (1 << 31) - 1)


def _wrap32(v: int) -> int:
    return ((int(v) + (1 << 31)) & 0xFFFFFFFF) - (1 << 31)


def _mul(a: int, b: int) -> int:
    """``multiply_32x32_rshift32``."""
    return _wrap32((int(a) * int(b)) >> 32)


def _mulr(a: int, b: int) -> int:
    """``multiply_32x32_rshift32_rounded``."""
    return _wrap32((int(a) * int(b) + (1 << 31)) >> 32)


def _interpolate(position: int, bits: int, values, size_bits: int) -> int:
    """``interpolateTableSigned`` : ``valeur × 65536``."""
    which = position >> (bits - size_bits)
    strength = (position >> (bits - 16 - size_bits)) & 65535
    return values[which] * (65536 - strength) + values[which + 1] * strength


def _quick_log(x: int) -> int:
    """``quickLog`` : ``(magnitude + 1 + mantisse) << 25``, en entiers."""
    x = int(x) & 0xFFFFFFFF
    magnitude = x.bit_length()
    shift = 26 - magnitude
    lsbs = _wrap32(x << shift) if shift >= 0 else _wrap32(x) >> -shift
    return _wrap32((magnitude << 25) + (lsbs & ~(1 << 26)))


# --------------------------------------------------------------------------- #
# La percussivité
# --------------------------------------------------------------------------- #

def percussiveness(samples: np.ndarray) -> np.ndarray:
    """``Sample::fillPercCache`` sur tout le fichier, du début : un octet
    par pixel de 128 échantillons, de 0 (rien ne bouge) à 63 (une
    attaque)."""
    samples = np.asarray(samples, dtype=np.float64)
    if samples.ndim == 1:
        samples = samples[:, None]
    # Chaque canal lu sur 32 bits puis ``>> 2``, additionnés.
    lu = np.floor(np.clip(samples, -1.0, 1.0 - 2.0 ** -31) * 2.0 ** 31)
    x = np.floor(lu / 4.0).sum(axis=1)
    pixels = max(1, ((x.size - 1) >> _PERC_MAG) + 1)
    out = dsp._zeros(pixels)
    _perc_loop(dsp._seq(x), out, dsp._tanh_list())
    return np.asarray(out, dtype=np.int64)


@dsp._Boucle
def _perc_loop(x, out, tab):
    """Les échantillons de :func:`percussiveness`, en entiers portés par
    des flottants."""
    pole0 = 0.0
    pole1 = 0.0
    last_read = 0.0
    last_angle = 0.0
    for i in range(len(x)):
        angle = x[i] - last_read
        last_read = x[i]
        if angle < 0.0:
            angle = -angle
        pole0 += np.floor((angle - pole0) / 512.0)
        pole1 += np.floor((pole0 - pole1) / 512.0)
        angle = pole1
        if ((i + 1) & 127) == 64:
            difference = angle - last_angle
            if difference < 0.0:
                difference = -difference
            if angle > 0.0:
                perc = np.floor(np.floor(difference * 262144.0 / angle) / 2.0)
                # Le quotient, sur 64 bits, est rangé dans 32.
                perc -= np.floor((perc + 2147483648.0) / 4294967296.0) \
                    * 4294967296.0
            elif difference > 0.0:
                # La division par zéro de la libgcc rend 2⁶⁴ − 1 : −1 une
                # fois rangé.
                perc = -1.0
            else:
                perc = 0.0
            # ``getTanH<23>`` : décalé de 23 bits et saturé, la table
            # ``tanHSmall`` lue sur 32 bits, rendue ``>> 25``.
            work = perc * 8388608.0
            if work > 2147483647.0:
                work = 2147483647.0
            elif work < -2147483648.0:
                work = -2147483648.0
            work += 2147483648.0
            which = int(work // 16777216.0)
            strength = np.floor(work / 256.0) % 65536.0
            value = tab[which] * (65536.0 - strength) \
                + tab[which + 1] * strength
            # ``tab`` est ramenée à ±1 (la table du firmware sur 32 768) ;
            # le résultat est rangé dans un octet non signé.
            byte = np.floor(value * 32768.0 / 33554432.0) % 256.0
            index = (i + 1) >> 7
            if index < len(out):
                out[index] = byte
        last_angle = angle


# --------------------------------------------------------------------------- #
# Le calage de la tête neuve
# --------------------------------------------------------------------------- #

def _averages(mix: np.ndarray, start: int, crossfade: int,
              length: int) -> list[float] | None:
    """``Sample::getAveragesForCrossfade`` : trois sommes consécutives de
    ``length`` échantillons, centrées au milieu du fondu ; ``None`` trop
    près d'un bord."""
    frames = mix.size
    half = crossfade >> 1
    read = start + half - ((length * _N_AVG) >> 1)
    if read < half or read >= frames - half:
        return None
    if read + length * _N_AVG > frames:
        return None
    return [float(mix[read + i * length:read + (i + 1) * length].sum())
            for i in range(_N_AVG)]


@dsp._Boucle
def _align_loop(mix, old, new, first_read, length, max_search, pitched):
    """La recherche de ``hopEnd`` : fait glisser les trois moyennes de la
    tête neuve, un échantillon à la fois, d'abord en avant puis en arrière
    (ou l'inverse si le premier pas en avant éloigne), et garde le décalage
    où elles ressemblent le plus à celles de l'ancienne. Quatre changements
    de signe de l'écart total, toutes directions confondues, arrêtent tout ;
    à un changement de signe près du meilleur, la position se cale entre
    deux échantillons. Rend ``(décalage, fraction sur 2²⁴)``."""
    frames = len(mix)
    old_sum = old[0] + old[1] + old[2]
    best_diff = abs(new[0] - old[0]) + abs(new[1] - old[1]) \
        + abs(new[2] - old[2])
    initial_change = new[0] + new[1] + new[2] - old_sum
    best_offset = 0
    additional = 0.0
    direction = 1
    done = 0
    flips = 0
    while True:
        restart = False
        stop = False
        last_change = initial_change
        b0 = first_read - 1 if direction == -1 else first_read
        b1 = b0 + length
        b2 = b1 + length
        b3 = b2 + length
        t0 = new[0]
        t1 = new[1]
        t2 = new[2]
        offset = 0
        for _step in range(max_search):
            if b0 < 0 or b3 >= frames:
                break
            v0 = mix[b0] * direction
            v1 = mix[b1] * direction
            v2 = mix[b2] * direction
            v3 = mix[b3] * direction
            t0 = t0 - v0 + v1
            t1 = t1 - v1 + v2
            t2 = t2 - v2 + v3
            b0 += direction
            b1 += direction
            b2 += direction
            b3 += direction
            diff = abs(t0 - old[0]) + abs(t1 - old[1]) + abs(t2 - old[2])
            if offset == 0 and direction == 1 and done == 0 \
                    and diff > best_diff:
                restart = True
                break
            offset += direction
            here = diff < best_diff
            if here:
                best_diff = diff
                best_offset = offset
            change = t0 + t1 + t2 - old_sum
            if (change < 0.0) != (last_change < 0.0):
                if pitched and (here or best_offset == offset - direction):
                    a = abs(change)
                    b = abs(last_change)
                    additional = np.floor(b * 16777216.0 / (a + b))
                    if direction == -1:
                        additional = 16777216.0 - additional
                    if here != (direction == -1):
                        best_offset -= 1
                flips += 1
                if flips >= 4:
                    stop = True
                    break
            last_change = change
        if stop:
            break
        if restart:
            direction = -direction
            continue
        done += 1
        if done >= 2:
            break
        direction = -direction
    return best_offset, additional


# --------------------------------------------------------------------------- #
# L'étireur
# --------------------------------------------------------------------------- #

def _hop_parameters(ratio: int, rng: dsp.Cong) -> tuple[int, int, int, int]:
    """Les bornes du saut (avant la hauteur), sa part de fondu et la
    longueur fixe de celui-ci, selon la vitesse (``speedLog`` : 832 << 20 au
    neutre, 32 << 20 par octave)."""
    speed_log = _quick_log(ratio)
    if (800 << 20) <= speed_log < (864 << 20):
        position = speed_log - (800 << 20)
        tables = (_MIN_HOP_FINE, _MAX_HOP_FINE, _XF_PROP_FINE, _XF_ABS_FINE,
                  _RANDOM_FINE)
        bits, size = 26, 4
    else:
        speed_log = min(max(speed_log, 768 << 20), 896 << 20)
        position = min(speed_log - (768 << 20), (128 << 20) - 1)
        tables = (_MIN_HOP_COARSE, _MAX_HOP_COARSE, _XF_PROP_COARSE,
                  _XF_ABS_COARSE, _RANDOM_COARSE)
        bits, size = 27, 2
    lo, hi, prop, absolu, alea = (_interpolate(position, bits, t, size)
                                  for t in tables)
    min_beam = lo >> 16
    # ``<< 8`` sur 32 bits : il déborde quand la vitesse baisse de plus de
    # dix demi-tons, et le fondu prend alors la moitié du saut — comme sur
    # la machine.
    xf_prop = _wrap32(prop << 8)
    min_beam += _wrap32(_mul(min_beam, _mul(rng.noise(), alea << 8)) << 2)
    return min_beam, hi >> 16, xf_prop, absolu >> 16


class _Head:
    """Une tête de lecture : sa base sur 2²⁴ (l'échantillon de sortie ``k``
    du segment suivant lit ``base + k·incrément − 2²⁴``) et si elle sonne."""

    __slots__ = ("pos", "active")

    def __init__(self) -> None:
        self.pos = 0
        self.active = True


class _Stretcher:
    """Le ``TimeStretcher`` d'une voix : où lit chaque tête, échantillon par
    échantillon, et le poids de la neuve dans le fondu."""

    def __init__(self, data: np.ndarray, n: int, sample_rate: int,
                 loop: bool, seed: int) -> None:
        self.frames = data.shape[0]
        self.loop = loop
        self.sample_rate = int(sample_rate)
        self.mix = np.clip(np.floor(data.astype(np.float64) * 32768.0),
                           -32768.0, 32767.0).sum(axis=1).astype(np.int64)
        self.mix_seq = None
        self.perc = percussiveness(data)
        self.rng = dsp.Cong(seed)
        self.newer, self.older = _Head(), _Head()
        self.progress, self.xf_inc = UNITY, 0
        first = self.rng.random255()
        self.til_hop = _FIRST_HOP + ((first - 256 if first >= 128 else first)
                                     >> 2)
        self.big = 0                       # samplePosBig
        self.zone_start = self.cache_end = 0
        self.pos_new = np.zeros(n, dtype=np.int64)
        self.pos_old = np.zeros(n, dtype=np.int64)
        self.weight = np.ones(n)
        self.on_new = np.zeros(n, dtype=bool)
        self.on_old = np.zeros(n, dtype=bool)

    def fill_perc_cache(self, inc: int, window: int) -> None:
        """``fillPercCache`` au début d'une passe : la zone calculée
        s'étend vers ``position + incrément / 1024``, d'au plus six
        échantillons par échantillon de la passe."""
        play = self.big >> 24
        if play >= self.frames:
            return
        if play < self.zone_start or self.cache_end < play - _ZONE_GAP:
            self.zone_start = self.cache_end = play
        target = min(self.frames, play + (inc >> 10))
        self.cache_end = max(self.cache_end,
                             min(target, self.cache_end
                                 + _PERC_PER_SAMPLE * window))

    def hop_end(self, inc: int, ratio: int) -> None:
        """``hopEnd`` : la tête neuve devient l'ancienne, une autre part."""
        newer, older = self.newer, self.older
        older.pos, older.active = newer.pos, newer.active
        newer.active = True
        sample_pos = self.big >> 24
        min_beam, max_beam, xf_prop, xf_abs = _hop_parameters(ratio, self.rng)
        min_beam = ((min_beam & 0xFFFFFFFF) * inc) >> 24
        max_beam = ((max_beam & 0xFFFFFFFF) * inc) >> 24
        best = (min_beam + max_beam) >> 1
        best = self._beam_search(sample_pos, min_beam, max_beam, ratio, best)
        back_edge = max(0, sample_pos + ((best * (ratio - UNITY)) >> 25))
        til_hop = max(1, (best << 24) // inc)
        crossfade = (_mulr(til_hop, xf_prop) + xf_abs * 4) & 0xFFFFFFFF
        if crossfade >= (til_hop >> 1):
            crossfade = til_hop >> 1
        til_hop -= crossfade
        crossfade = min(til_hop, crossfade)
        self.til_hop = til_hop
        # Une division par zéro rend zéro : l'ancienne tête sonne alors
        # seule jusqu'au saut suivant.
        self.xf_inc = UNITY // crossfade if crossfade else 0
        self.progress = 0
        if back_edge >= self.frames:
            newer.active = False
            return
        offset, extra = 0, 0
        if older.active:
            offset, extra = self._align(back_edge, crossfade, inc)
        newer.pos = (max(0, back_edge + offset) << 24) + extra

    def _beam_search(self, sample_pos: int, min_beam: int, max_beam: int,
                     ratio: int, best: int) -> int:
        """La longueur de saut dont la fenêtre parcourue est en moyenne la
        plus percussive, par pas de 128."""
        top = sample_pos >> _PERC_MAG
        real = (top << _PERC_MAG) + (_PERC_SIZE >> 1)
        if not self.zone_start <= real < self.cache_end:
            return best
        earliest = (self.zone_start + (_PERC_SIZE >> 1)) >> _PERC_MAG
        latest = (self.cache_end - (_PERC_SIZE >> 1)) >> _PERC_MAG
        perc = self.perc
        back_seen = front_seen = top
        total = best_total = 0
        best_width = 1
        shift = 25 + _PERC_MAG
        for width in range(min_beam, max_beam, _PERC_SIZE):
            back = top + ((width * (ratio - UNITY)) >> shift)
            front = top + ((width * (ratio + UNITY)) >> shift)
            pixels = front - back
            if not pixels:
                continue
            if front > latest or back < earliest:
                break
            while front > front_seen:
                total += int(perc[front_seen])
                front_seen += 1
            while back > back_seen:
                total -= int(perc[back_seen])
                back_seen += 1
            while back < back_seen:
                back_seen -= 1
                total += int(perc[back_seen])
            if total * best_width >= best_total * pixels:
                best_total, best, best_width = total, width, pixels
        return best

    def _align(self, back_edge: int, crossfade: int,
               inc: int) -> tuple[int, int]:
        """Le décalage de la tête neuve et sa fraction (``additionalOscPos``,
        la fraction de l'ancienne tête comprise)."""
        older = self.older
        length = min(max((inc * _AVG_LEN) >> 24, 1), _AVG_LEN * 2)
        crossfade_src = (crossfade * inc) >> 24
        old_pos = older.pos >> 24
        if self.loop:
            old_pos %= self.frames
        old = _averages(self.mix, old_pos, crossfade_src, length)
        new = _averages(self.mix, back_edge, crossfade_src, length) \
            if old is not None else None
        if new is None:
            return 0, 0
        max_search = (((self.til_hop * 40) >> 8) * inc) >> 24
        max_search = min(max_search, (self.sample_rate // 45) >> 1)
        first_read = back_edge + (crossfade_src >> 1) \
            - ((length * _N_AVG) >> 1)
        if self.mix_seq is None:
            self.mix_seq = dsp._seq(self.mix)
        pitched = inc != UNITY
        offset, extra = _align_loop(self.mix_seq, dsp._seq(old),
                                    dsp._seq(new), first_read, length,
                                    max(0, max_search), pitched)
        offset, extra = int(offset), int(extra)
        if pitched:
            extra += older.pos & (UNITY - 1)
            if extra >= UNITY:
                extra -= UNITY
                offset += 1
        return offset, extra

    def run(self, inc_blocks: np.ndarray, ratio_blocks: np.ndarray,
            n: int) -> None:
        """Les passes de 128, coupées aux fins de saut et au bout du
        fichier."""
        newer, older = self.newer, self.older
        frames = self.frames
        last = inc_blocks.size - 1
        t = 0
        while t < n:
            block = min(t // dsp.BLOCK, last)
            block_end = min(n, (block + 1) * dsp.BLOCK)
            inc = int(inc_blocks[block])
            ratio = int(ratio_blocks[block])
            if inc <= 0:
                t = block_end
                continue
            combined = (inc * ratio) >> 24
            if t == block * dsp.BLOCK and ratio != UNITY:
                self.fill_perc_cache(inc, block_end - t)
            limit = block_end - t
            left = (frames << 24) - self.big
            if combined > 0 and left < combined:
                if not self.loop:
                    break                  # la voix s'arrête
                # ``reInit`` : la position repart du début ; un saut se
                # force si la tête neuve s'était éteinte.
                self.big = -left
                if not newer.active:
                    self.hop_end(inc, ratio)
            elif combined > 0:
                limit = min(limit, left // combined)
            if newer.active and self.til_hop <= 0:
                self.hop_end(inc, ratio)
            end = t + limit
            if newer.active:
                end = min(end, t + self.til_hop)
            seg = end - t
            k = np.arange(1, seg + 1, dtype=np.int64)
            if newer.active:
                self.pos_new[t:end] = newer.pos + inc * k - UNITY
                self.on_new[t:end] = True
            if older.active and self.progress < UNITY:
                self.pos_old[t:end] = older.pos + inc * k - UNITY
                self.on_old[t:end] = True
                now = self.progress
                after = min(UNITY, now + self.xf_inc * seg)
                self.weight[t:end] = (now + (after - now) * k / seg) / UNITY
                self.progress += self.xf_inc * seg
                if self.progress >= UNITY:
                    older.active = False
            newer.pos += inc * seg
            older.pos += inc * seg
            self.big += combined * seg
            self.til_hop -= seg
            if not self.loop:
                if newer.active and (newer.pos - UNITY) >> 24 >= frames:
                    newer.active = False
                if older.active and (older.pos - UNITY) >> 24 >= frames:
                    older.active = False
                if not newer.active and not older.active:
                    break
            t = end


def warm_up() -> None:
    """Fait tourner les deux boucles du module sur du silence, avec les
    types de l'écoute (:func:`.dsp.prepare`)."""
    silence = np.zeros(4 * _PERC_SIZE)
    _perc_loop(dsp._seq(silence), dsp._zeros(4), dsp._tanh_list())
    zeros = dsp._seq([0.0] * _N_AVG)
    _align_loop(dsp._seq(silence), zeros, zeros, 0, _AVG_LEN, 4, True)


def stretch(samples: np.ndarray, inc_blocks, ratio_blocks, n: int,
            sample_rate: int, loop: bool = False,
            seed: int = dsp.CONG_SEED) -> np.ndarray:
    """Un échantillon lu ``n`` échantillons durant, à la hauteur
    ``inc_blocks`` et à la vitesse ``ratio_blocks`` (un de chaque par bloc
    de 128, sur 2²⁴) : ``(n,)`` d'un mono, ``(canaux, n)`` d'un stéréo,
    dans l'unité de ``samples``."""
    samples = np.asarray(samples)
    mono = samples.ndim == 1
    data = samples[:, None] if mono else samples
    frames, channels = data.shape
    inc_blocks = np.asarray(inc_blocks, dtype=np.int64)
    ratio_blocks = np.asarray(ratio_blocks, dtype=np.int64)
    out = np.zeros((channels, n))
    if frames == 0 or n == 0 or inc_blocks.size == 0:
        return out[0] if mono else out
    st = _Stretcher(data, n, sample_rate, loop, seed)
    st.run(inc_blocks, ratio_blocks, n)
    which = np.repeat([dsp.sample_kernel(int(v)) for v in inc_blocks],
                      dsp.BLOCK)[:n]
    if which.size < n:
        which = np.pad(which, (0, n - which.size), mode="edge")
    native = bool(np.all(inc_blocks == UNITY))
    for pos, on, gain in ((st.pos_new, st.on_new, st.weight),
                          (st.pos_old, st.on_old, 1.0 - st.weight)):
        if not np.any(on):
            continue
        pos = pos[on]
        if native:
            # À sa hauteur, la machine lit les échantillons tels quels.
            index = pos >> 24
            if loop:
                index %= frames
            valid = (index >= 0) & (index < frames)
            lu = np.zeros((channels, pos.size))
            lu[:, valid] = data[index[valid]].T
        else:
            lu = dsp.read_positions(data, pos, which[on], loop)
        out[:, on] += lu * gain[on]
    return out[0] if mono else out
