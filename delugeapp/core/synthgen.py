# -*- coding: utf-8 -*-
"""Générateur de presets de synthé.

Fabrique des presets jouables à partir d'un genre musical et d'un rôle, ou
complètement au hasard. Les profils de :mod:`delugeapp.core.genres` donnent les
intervalles ; ce module y tire au sort et traduit le résultat en paramètres
Deluge.

Deux garanties, qui sont la raison d'être du module :

* **le preset produit est toujours audible.** Un générateur qui sort un son
  muet une fois sur dix est inutilisable. Une passe de sûreté
  (:func:`_ensure_audible`) vérifie le volume général, la présence d'un
  oscillateur audible, l'enveloppe d'amplitude et l'ouverture du filtre avant
  de rendre le preset.
* **tout est reproductible.** Le tirage passe par une instance
  :class:`random.Random` propre à l'appel, jamais par le ``random`` global :
  une même graine redonne exactement le même son, quoi qu'il se passe
  ailleurs dans l'application. À version égale du générateur seulement :
  chaque recalage sur la carte change le son qu'une graine donne.

Les huit curseurs de :class:`GenOptions` (``brightness``, ``movement``,
``space``, ``dirt``, ``width``, ``complexity``) déplacent les intervalles du
genre sans en sortir brutalement : à 0,5 on obtient le centre du profil.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field

from .fixedpoint import INT32_MAX, INT32_MIN, from_display
from .genres import ROLES, GenreProfile, genre as get_genre
from .model import (
    DEFAULT_PARAMS,
    Envelope,
    LFO,
    Modulator,
    Osc,
    PatchCable,
    Sound,
    SynthPreset,
)
from .sdcard import safe_deluge_name

log = logging.getLogger(__name__)

#: Modes de synthèse du Deluge.
MODES = ("subtractive", "fm", "ringmod")

#: Moteurs par défaut et leur poids, quand ni le rôle ni le genre n'en
#: imposent.
DEFAULT_MODES: list[tuple[str, float]] = [("subtractive", 8.0), ("fm", 1.2),
                                         ("ringmod", 0.6)]

#: Accord du premier modulateur FM (demi-tons) et poids : la distribution
#: relevée sur les 145 presets FM de la carte (unisson 54, ±12 : 26, -24 : 9,
#: +28 : 7, +24 : 5, +7 : 6…).
FM_MOD1_TRANSPOSE: list[tuple[int, float]] = [
    (0, 5.0), (12, 2.0), (-12, 1.2), (-24, 1.0), (24, 0.8), (28, 0.8),
    (7, 0.7), (19, 0.6)]

#: Accord du second modulateur : -12 dans 61 presets sur 145.
FM_MOD2_TRANSPOSE: list[tuple[int, float]] = [
    (-12, 4.0), (0, 1.5), (12, 1.0), (7, 0.6), (-24, 0.4)]

#: Cloches : rapports franchement inharmoniques, ce qui fait le métal.
FM_BELL_TRANSPOSE: list[tuple[int, float]] = [
    (28, 3.0), (24, 2.0), (19, 2.0), (31, 1.0), (33, 0.8)]

#: Rôles qui gagnent à un léger vibrato (``lfo1 → pitch`` : 579 presets sur
#: 911 de la carte en portent un, médiane +4).
_VIBRATO_ROLES = ("lead", "pad", "keys", "bell", "drone")

#: Rôles qui gagnent au suivi de clavier (``note → lpfFrequency`` : 191
#: presets, médiane +15) : le timbre s'éclaircit en montant.
_KEYTRACK_ROLES = ("bass", "lead", "keys", "pluck")

#: Niveaux de synchro d'un arpège, en valeur de fichier : 7 = double-croche
#: (les 23 arpèges synchronisés de la carte), 6 = croche, 8 = triple-croche.
_ARP_SYNC: list[tuple[int, float]] = [(7, 6.0), (6, 2.0), (8, 1.0)]

#: Habitudes par rôle relevées sur les 911 presets de la carte (14 octobre
#: 2026), que le générateur ignorait : il ne posait jamais de portamento ni de
#: saturation, synchronisait tous ses délais à la double-croche et mettait un
#: effet de modulation sur un preset sur trois, quel que soit le rôle.
#: Les rôles absents (``stab``, ``bell``) reprennent ceux de ``pluck`` et
#: ``keys``, dont ils sont les cousins.
_ROLE_KIN = {"stab": "pluck", "bell": "keys"}

#: Portamento : part des presets qui en portent, et plage de réglage autour
#: de la médiane réelle (basse 10, lead 6, nappe 7…).
_GLIDE: dict[str, tuple[float, tuple[int, int]]] = {
    "bass": (0.33, (6, 14)), "lead": (0.25, (3, 10)),
    "pad": (0.16, (4, 10)), "drone": (0.21, (2, 8)), "fx": (0.24, (5, 14)),
    "keys": (0.11, (3, 9)), "pluck": (0.12, (1, 4)), "arp": (0.14, (1, 4)),
}

#: Saturation (``clippingAmount``) : part des presets qui en portent. Les
#: valeurs réelles vont surtout de 2 à 5.
_SATURATION: dict[str, float] = {
    "bass": 0.40, "lead": 0.34, "pad": 0.31, "drone": 0.56, "fx": 0.53,
    "keys": 0.27, "pluck": 0.40, "arp": 0.46,
}
_SATURATION_LEVELS: list[tuple[int, float]] = [(2, 1.0), (3, 2.5), (4, 2.5),
                                               (5, 1.2)]

#: Synchro du délai (``syncLevel`` : 5 = noire, 6 = croche, 7 =
#: double-croche, 8 = triple-croche) parmi les presets dont le délai sonne.
#: La croche domine pour les sons joués, la double-croche pour les nappes.
_DELAY_SYNC: dict[str, list[tuple[int, float]]] = {
    "bass": [(6, 45.0), (7, 36.0), (5, 10.0), (8, 5.0)],
    "lead": [(6, 67.0), (7, 27.0), (5, 5.0)],
    "pad": [(7, 49.0), (6, 29.0), (5, 8.0)],
    "drone": [(7, 42.0), (6, 32.0), (5, 24.0)],
    "fx": [(7, 50.0), (6, 30.0), (5, 13.0)],
    "keys": [(6, 52.0), (7, 24.0), (5, 16.0), (8, 3.0)],
    "pluck": [(6, 72.0), (5, 14.0), (7, 6.0), (8, 4.0)],
    "arp": [(6, 48.0), (7, 29.0), (5, 12.0)],
}

#: Passe-haut : part des presets qui en portent, et plage autour du réglage
#: réel (médiane 16 à 22). Sur une basse, plus rare et plus bas : il ne doit
#: nettoyer que l'infra-grave.
_HPF: dict[str, tuple[float, tuple[int, int]]] = {
    "bass": (0.20, (2, 10)), "lead": (0.38, (12, 24)),
    "pad": (0.44, (14, 26)), "drone": (0.45, (10, 24)),
    "fx": (0.70, (14, 30)), "keys": (0.34, (10, 22)),
    "pluck": (0.40, (10, 22)), "arp": (0.33, (14, 24)),
}

#: Effet de modulation : part des presets qui en portent (de 11 % pour les
#: sons pincés à 38 % pour les arpèges), et les types qu'ils choisissent —
#: chorus pour basses et claviers, phaser pour leads et nappes.
_MOD_FX: dict[str, tuple[float, list[tuple[str, float]]]] = {
    "bass": (0.15, [("chorus", 5.0), ("StereoChorus", 2.0), ("phaser", 1.0),
                    ("flanger", 0.5)]),
    "lead": (0.21, [("phaser", 5.0), ("chorus", 2.5), ("flanger", 1.0)]),
    "pad": (0.36, [("phaser", 5.0), ("chorus", 2.5), ("StereoChorus", 1.5),
                   ("flanger", 1.0)]),
    "drone": (0.18, [("phaser", 5.0), ("chorus", 2.5)]),
    "fx": (0.13, [("phaser", 3.0), ("chorus", 1.0), ("flanger", 1.0)]),
    "keys": (0.16, [("chorus", 5.0), ("StereoChorus", 2.0), ("phaser", 1.5)]),
    "pluck": (0.11, [("chorus", 3.0), ("flanger", 1.5)]),
    "arp": (0.38, [("phaser", 4.5), ("flanger", 2.5), ("chorus", 2.5)]),
}

#: Mode de jeu d'une basse ou d'un lead : sur la carte, un tiers en poly, un
#: tiers en legato, un quart en mono — le générateur en mettait la moitié en
#: mono.
_MONO_ROLES_POLY: list[tuple[str, float]] = [("poly", 1.0), ("legato", 1.0),
                                             ("mono", 0.7)]

#: Variante « analogique » d'une forme d'onde : 11 à 23 % des premiers
#: oscillateurs réels, selon le rôle.
_ANALOG_VARIANT = {"saw": "analogSaw", "square": "analogSquare"}
_ANALOG_CHANCE = 0.2


def _kin(role: str) -> str:
    """Rôle mesuré le plus proche d'un rôle sans mesure propre."""
    return _ROLE_KIN.get(role, role)


#: Modes de filtre passe-bas acceptés par le firmware.
LPF_MODES = ("24dB", "12dB", "24dBDrive", "SVF_Band", "SVF_Notch")

#: Coupure minimale tolérée, en unités d'affichage, quand rien ne vient
#: ouvrir le filtre. En dessous, le son est inaudible.
MIN_SAFE_CUTOFF = 10

#: Volume général minimal, en unités d'affichage.
MIN_VOLUME = 28

#: Oscillateurs qui ne produisent rien sans échantillon ni entrée externe.
#:
#: ``wavetable`` en fait partie : le modèle le traite comme un type lu depuis
#: la carte (``Osc.is_sample``), et un oscillateur wavetable sans fichier est
#: muet. Trois genres proposent cette forme dans leur profil ; sans cette
#: précaution, 12 des 1 320 combinaisons genre × rôle × graine sortaient un
#: oscillateur silencieux.
_SILENT_OSC_TYPES = ("sample", "wavetable", "inLeft", "inRight", "dx7")

#: Formes d'onde de repli, toutes audibles sans fichier.
_SAFE_OSC_TYPES = ("saw", "square", "triangle", "sine", "analogSaw",
                   "analogSquare")


@dataclass
class GenOptions:
    """Réglages d'une génération.

    Les six curseurs vont de 0 à 1 ; 0,5 est le centre du profil de genre.
    """

    genre: str = "techno"
    role: str = "bass"
    seed: int | None = None
    brightness: float = 0.5
    movement: float = 0.5
    space: float = 0.5
    dirt: float = 0.5
    width: float = 0.5
    complexity: float = 0.5
    mode: str = ""
    use_samples: list[str] = field(default_factory=list)
    name: str = ""


# --------------------------------------------------------------------------- #
# Outils de tirage
# --------------------------------------------------------------------------- #

def _clamp01(value: float) -> float:
    """Ramène un curseur dans [0, 1]."""
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.5


def _pick(rng: random.Random, weighted: list[tuple[str, float]],
          default: str) -> str:
    """Tire une valeur dans une liste pondérée."""
    choices = [(name, weight) for name, weight in (weighted or [])
               if weight > 0]
    if not choices:
        return default
    total = sum(w for _n, w in choices)
    draw = rng.uniform(0.0, total)
    upto = 0.0
    for name, weight in choices:
        upto += weight
        if draw <= upto:
            return name
    return choices[-1][0]


def _span(rng: random.Random, bounds: tuple[int, int],
          bias: float = 0.5) -> int:
    """Tire un entier dans ``bounds``, déplacé par ``bias``.

    ``bias`` à 0,5 tire autour du centre de l'intervalle ; à 0 on se serre
    contre le minimum, à 1 contre le maximum. Le tirage reste **dans**
    l'intervalle du genre : un curseur pousse une tendance, il ne dénature pas
    le profil.
    """
    try:
        low, high = int(bounds[0]), int(bounds[1])
    except (TypeError, ValueError, IndexError):
        return 25
    if high < low:
        low, high = high, low
    if low == high:
        return low
    bias = _clamp01(bias)
    centre = low + (high - low) * bias
    # Écart-type d'un quart de l'intervalle : assez pour varier, pas assez
    # pour ignorer le curseur.
    spread = (high - low) / 4.0
    value = rng.gauss(centre, spread)
    return int(round(max(low, min(high, value))))


def _disp(value: int, bipolar: bool = False) -> int:
    """Convertit une valeur d'affichage 0..50 en virgule fixe Deluge."""
    return from_display(int(value), bipolar=bipolar, scale=50)


# --------------------------------------------------------------------------- #
# Génération
# --------------------------------------------------------------------------- #

def generate(opts: GenOptions) -> SynthPreset:
    """Fabrique un preset d'après ``opts``.

    Le résultat est toujours jouable, et identique pour une même graine.
    """
    seed = opts.seed if opts.seed is not None else random.randrange(1 << 30)
    role = opts.role if opts.role in ROLES else "bass"
    # Genre et rôle entrent dans la graine : sans cela, la graine 42 faisait
    # les mêmes choix — mode de jeu, effet, saturation — dans tous les genres,
    # comme le faisait le générateur de kits avec ses grosses caisses.
    rng = random.Random(f"{seed}|{opts.genre}|{role}")

    profile = get_genre(opts.genre).for_role(role)

    preset = SynthPreset.new("GEN")
    sound = preset.sound
    sound.params = dict(DEFAULT_PARAMS)

    _apply_mode(sound, profile, opts, rng)
    _apply_oscillators(sound, profile, opts, rng)
    _apply_filter(sound, profile, opts, rng)
    _apply_envelopes(sound, profile, opts, rng)
    _apply_lfos(sound, profile, opts, rng)
    _apply_unison(sound, profile, opts, rng)
    _apply_fx(sound, profile, opts, rng)
    _apply_cables(sound, profile, opts, rng)
    _apply_arp(sound, profile, opts, rng, role)

    _ensure_audible(sound)

    name = opts.name.strip() if opts.name else suggest_name(opts, seed)
    sound.name = safe_deluge_name(name)
    preset.name = sound.name
    log.debug("preset généré : %s (genre %s, rôle %s, graine %s)",
              sound.name, opts.genre, role, seed)
    return preset


def _apply_mode(sound: Sound, profile: GenreProfile, opts: GenOptions,
                rng: random.Random) -> None:
    """Choisit le mode de synthèse et la polyphonie."""
    if opts.mode in MODES:
        sound.mode = opts.mode
    else:
        # Le rôle et le genre choisissent le moteur : une cloche est FM, un
        # effet sur deux est en ring mod sur la carte. À défaut, la FM reste
        # minoritaire — elle demande un accord des modulateurs pour sonner.
        sound.mode = _pick(rng, profile.modes or DEFAULT_MODES, "subtractive")
    role = opts.role
    if role in ("bass", "lead"):
        sound.polyphonic = _pick(rng, _MONO_ROLES_POLY, "poly")
    elif role == "drone":
        sound.polyphonic = "poly"
    else:
        # « auto » : 1 à 2 % des vrais presets de ces rôles, contre 16 % des
        # presets générés jusqu'ici.
        sound.polyphonic = _pick(rng, [("poly", 40.0), ("auto", 1.0)], "poly")
    # Huit voix, quelle que soit la polyphonie : c'est ce qu'écrit la machine
    # pour chacun des 94 sons des morceaux de la carte, legato et auto
    # compris. Le 0 qu'on écrivait pour les sons non polyphoniques est une
    # valeur qu'elle ne produit jamais (son menu remplace 0 par 127) et
    # qu'elle lit comme un plafond de zéro voix (``AudioEngine::solicitVoice``).
    sound.max_voices = 8
    _apply_glide(sound, profile, role, rng)


def _apply_glide(sound: Sound, profile: GenreProfile, role: str,
                 rng: random.Random) -> None:
    """Pose un portamento, à la fréquence des vrais presets du rôle.

    Sur une basse ou un lead, le glissé va avec le jeu monophonique : 86 %
    des basses à portamento de la carte sont en legato ou en mono. Le genre
    module la chance (``GenreProfile.glide``) : la 303 glisse, la house
    beaucoup moins.
    """
    chance, bounds = _GLIDE.get(_kin(role), (0.1, (2, 8)))
    if role in ("bass", "lead"):
        chance *= 1.35 if sound.polyphonic in ("mono", "legato") else 0.4
    chance = min(0.9, chance * max(0.0, float(getattr(profile, "glide", 1.0))))
    if rng.random() < chance:
        sound.set_param("portamento", _disp(_span(rng, bounds)))


def _apply_oscillators(sound: Sound, profile: GenreProfile, opts: GenOptions,
                       rng: random.Random) -> None:
    """Règle les deux oscillateurs, et les échantillons si on en donne."""
    samples = [s for s in (opts.use_samples or []) if s]
    if samples:
        sound.osc1 = Osc(type="sample", file_name=samples[0])
        if len(samples) > 1:
            sound.osc2 = Osc(type="sample", file_name=samples[1])
        else:
            sound.osc2 = Osc(type=_pick(rng, profile.osc_types, "square"))
            sound.set_param("oscBVolume", _disp(_span(rng, (0, 18))))
    else:
        # Sans échantillon fourni, écarter d'emblée les formes qui en
        # réclament un : les tirer puis les corriger ensuite donnerait un son
        # qui ne ressemble plus au profil du genre.
        playable = [(name, weight) for name, weight in profile.osc_types
                    if name not in _SILENT_OSC_TYPES]
        first = _pick(rng, playable, "saw")
        if first in _ANALOG_VARIANT and rng.random() < _ANALOG_CHANCE:
            first = _ANALOG_VARIANT[first]
        sound.osc1 = Osc(type=first)
        # Le second oscillateur reprend souvent la même forme, décalée.
        second = (first if rng.random() < 0.45
                  else _pick(rng, playable, "square"))
        sound.osc2 = Osc(type=second)

    sound.set_param("oscAVolume", _disp(_span(rng, (40, 50), 0.8)))

    if sound.osc2.type not in _SILENT_OSC_TYPES or sound.osc2.file_name:
        # Un deuxième oscillateur plus discret que le premier : c'est ce qui
        # épaissit un son sans le rendre confus.
        level = _span(rng, (0, 42), 0.35 + 0.4 * _clamp01(opts.width))
        sound.set_param("oscBVolume", _disp(level))
        # Désaccord ou transposition à l'octave / à la quinte.
        choice = rng.random()
        if choice < 0.35:
            sound.osc2.transpose = -12
        elif choice < 0.5:
            sound.osc2.transpose = 12
        elif choice < 0.6:
            sound.osc2.transpose = 7
        sound.osc2.cents = int(round(
            rng.uniform(-1, 1) * 25 * _clamp01(opts.width)))

    if opts.role == "bass":
        # Une basse se joue bas : sans cela le générateur produit des sons
        # justes mais inutilisables comme basse.
        sound.transpose = rng.choice([-24, -12, -12, 0])

    # Largeur d'impulsion, utile aux formes carrées.
    if "square" in (sound.osc1.type or ""):
        sound.set_param("oscAPulseWidth", _disp(_span(rng, (10, 40))))

    if sound.mode == "fm":
        _apply_fm(sound, opts, rng)

    if rng.random() < 0.18 + 0.3 * _clamp01(opts.dirt):
        sound.set_param("noiseVolume", _disp(_span(rng, (2, 20))))


def _apply_fm(sound: Sound, opts: GenOptions, rng: random.Random) -> None:
    """Accorde les deux modulateurs FM et règle leur profondeur.

    En FM, ce sont les modulateurs qui font le timbre ; les laisser à
    l'unisson, comme avant, donnait la même couleur à tous les presets FM.
    """
    bell = opts.role == "bell"
    table = FM_BELL_TRANSPOSE if bell else FM_MOD1_TRANSPOSE
    sound.modulator1 = Modulator(
        transpose=int(_pick(rng, [(str(t), w) for t, w in table], "0")),
        # Un léger écart de cents rend un timbre FM vivant ; les cloches
        # en prennent davantage, ce qui accentue l'inharmonicité.
        cents=int(round(rng.uniform(0, 12 if bell else 4)))
        if rng.random() < (0.6 if bell else 0.25) else 0)
    sound.modulator2 = Modulator(
        transpose=int(_pick(rng, [(str(t), w) for t, w in FM_MOD2_TRANSPOSE],
                            "-12")),
        to_modulator1=1 if rng.random() < 0.4 else 0)
    depth = (18, 40) if bell else (10, 34)
    sound.set_param("modulator1Amount",
                    _disp(_span(rng, depth, 0.4 + 0.3 * _clamp01(opts.dirt))))
    sound.set_param("modulator1Feedback", _disp(_span(rng, (0, 14))))
    if rng.random() < 0.5:
        sound.set_param("modulator2Amount", _disp(_span(rng, (0, 24))))


def _apply_filter(sound: Sound, profile: GenreProfile, opts: GenOptions,
                  rng: random.Random) -> None:
    """Règle le filtre : mode, coupure, résonance."""
    sound.lpf_mode = _pick(rng, profile.filter_mode, "24dB")
    if sound.lpf_mode not in LPF_MODES:
        sound.lpf_mode = "24dB"

    cutoff = _span(rng, profile.cutoff, _clamp01(opts.brightness))
    sound.set_param("lpfFrequency", _disp(cutoff))
    resonance = _span(rng, profile.resonance, _clamp01(opts.dirt))
    sound.set_param("lpfResonance", _disp(resonance))

    # Un passe-haut dégage le grave inutile, à la fréquence et au réglage
    # des vrais presets du rôle ; sur une basse, rare et bas.
    chance, bounds = _HPF.get(_kin(opts.role), (0.3, (8, 20)))
    if rng.random() < chance:
        sound.hpf_mode = "HPLadder"
        sound.set_param("hpfFrequency", _disp(_span(rng, bounds)))

    # Saturation : 27 à 56 % des vrais presets selon le rôle, réglée entre 2
    # et 5. Le curseur de saleté en change la fréquence et la force.
    dirt = _clamp01(opts.dirt)
    if rng.random() < _SATURATION.get(_kin(opts.role), 0.35) * (0.3 + 1.4 * dirt):
        level = int(_pick(rng, [(str(v), w) for v, w in _SATURATION_LEVELS],
                          "3"))
        sound.clipping_amount = level + int(round(max(0.0, dirt - 0.5) * 6))

    if dirt > 0.5 and rng.random() < dirt:
        if "sampleRateReduction" in profile.fx:
            sound.set_param("sampleRateReduction",
                            _disp(_span(rng, profile.fx["sampleRateReduction"],
                                        dirt)))
        if "bitCrush" in profile.fx:
            sound.set_param("bitCrush",
                            _disp(_span(rng, profile.fx["bitCrush"], dirt)))


def _apply_envelopes(sound: Sound, profile: GenreProfile, opts: GenOptions,
                     rng: random.Random) -> None:
    """Règle l'enveloppe d'amplitude et celle de modulation."""
    def _env(ranges: dict, bias: float) -> Envelope:
        return Envelope(
            attack=_disp(_span(rng, ranges.get("attack", (0, 6)), bias)),
            decay=_disp(_span(rng, ranges.get("decay", (14, 30)), bias)),
            sustain=_disp(_span(rng, ranges.get("sustain", (20, 40)), bias)),
            release=_disp(_span(rng, ranges.get("release", (10, 24)), bias)),
        )

    sound.env1 = _env(profile.env1, 0.5)
    sound.env2 = _env(profile.env2 or profile.env1, _clamp01(opts.movement))


def _apply_lfos(sound: Sound, profile: GenreProfile, opts: GenOptions,
                rng: random.Random) -> None:
    """Choisit les formes et les vitesses des deux LFO."""
    types = profile.lfo_types or ["triangle"]
    sound.lfo1 = LFO(type=rng.choice(types))
    sound.lfo2 = LFO(type=rng.choice(types))
    movement = _clamp01(opts.movement)
    sound.set_param("lfo1Rate", _disp(_span(rng, profile.lfo_rate, movement)))
    sound.set_param("lfo2Rate", _disp(_span(rng, profile.lfo_rate,
                                            movement * 0.7)))
    # Le LFO 1 se cale sur le tempo selon le genre : c'est le « wobble » de
    # la dubstep, la pulsation de la trance. Valeurs de fichier : 5 = noire,
    # 6 = croche, 7 = double-croche.
    chance, levels = profile.lfo_sync
    if levels and rng.random() < max(0.0, min(1.0, chance)):
        sound.lfo1.sync_level = int(rng.choice(list(levels)))
    # Le LFO 2 aussi, plus rarement, pour un mouvement rythmique secondaire.
    if rng.random() < 0.35 * movement + 0.1:
        sound.lfo2.sync_level = rng.choice([5, 6, 7, 7, 8])


def _apply_unison(sound: Sound, profile: GenreProfile, opts: GenOptions,
                  rng: random.Random) -> None:
    """Règle l'unisson et le désaccord, qui font la largeur du son."""
    width = _clamp01(opts.width)
    sound.unison_num = _span(rng, profile.unison, width)
    sound.unison_detune = _span(rng, profile.detune, width)
    sound.unison_spread = int(round(width * rng.uniform(0, 40)))
    # Le panoramique reste modéré : un son trop latéralisé gêne au mixage.
    if rng.random() < 0.25:
        sound.set_param("pan", _disp(int(rng.uniform(-8, 8)), bipolar=True))


def _apply_fx(sound: Sound, profile: GenreProfile, opts: GenOptions,
              rng: random.Random) -> None:
    """Règle réverbération, délai et effets de modulation."""
    space = _clamp01(opts.space)
    for key, bounds in (profile.fx or {}).items():
        if key in ("sampleRateReduction", "bitCrush"):
            continue        # déjà traités avec la saleté
        bias = space if key in ("reverbAmount", "delayFeedback",
                                "delayRate") else _clamp01(opts.movement)
        sound.set_param(key, _disp(_span(rng, bounds, bias)))

    # Effet de modulation à la fréquence des vrais presets du rôle au centre
    # du curseur de largeur, qui la divise ou la multiplie par 2,5 à ses
    # extrémités.
    chance, kinds = _MOD_FX.get(_kin(opts.role), (0.22, [("chorus", 1.0)]))
    if rng.random() < chance * (0.4 + 1.2 * _clamp01(opts.width)):
        sound.mod_fx_type = _pick(rng, kinds, "chorus")
        if "modFXDepth" not in (profile.fx or {}):
            sound.set_param("modFXDepth", _disp(_span(rng, (8, 30))))
    sound.delay_sync_level = int(_pick(
        rng, [(str(v), w) for v, w in _DELAY_SYNC.get(_kin(opts.role),
                                                       [(6, 1.0)])], "6"))
    # Volume médian des vrais presets : 38 à 40.
    sound.set_param("volume", _disp(_span(rng, (30, 44), 0.5)))


def _apply_cables(sound: Sound, profile: GenreProfile, opts: GenOptions,
                  rng: random.Random) -> None:
    """Pose les modulations (patch cables) d'après les recettes du genre."""
    recipes = profile.cable_recipes or [[("envelope2", "lpfFrequency",
                                          (12, 34))]]
    recipe = list(rng.choice(recipes))
    complexity = _clamp01(opts.complexity)

    cables: list[PatchCable] = []
    for source, destination, bounds in recipe:
        amount = _span(rng, bounds, 0.4 + 0.5 * complexity)
        cables.append(PatchCable(
            source=source, destination=destination,
            amount=PatchCable.amount_from_display(amount)))

    # La complexité ajoute des modulations secondaires, prises dans un
    # répertoire sûr : aucune ne peut rendre le son muet.
    # (``velocity → volume`` n'y figure plus : il est toujours posé, voir
    # :func:`_add_playing_cables`.)
    extras = [
        ("velocity", "lpfFrequency", (6, 22)),
        ("lfo2", "oscAPulseWidth", (6, 20)),
        ("lfo2", "modFXDepth", (6, 20)),
        ("envelope2", "oscBVolume", (6, 20)),
        ("note", "lpfFrequency", (4, 16)),
        ("aftertouch", "lpfFrequency", (6, 20)),
        ("random", "oscAPitch", (2, 8)),
    ]
    rng.shuffle(extras)
    wanted = int(round(complexity * 3))
    taken = 0
    # On écarte les destinations **déjà modulées par la recette**, et pas
    # seulement les paires source/destination identiques. Trois câbles
    # distincts pointant sur `lpfFrequency` (+50, +26, +20) additionnaient
    # leurs effets et laissaient le filtre grand ouvert en permanence :
    # une basse d'acid ressortait avec un centroïde de 13 kHz, soit
    # exactement l'inverse de ce que le genre demande.
    busy = {c.destination for c in cables}
    for source, destination, bounds in extras:
        if taken >= wanted:
            break
        if destination in busy:
            continue
        cables.append(PatchCable(
            source=source, destination=destination,
            amount=PatchCable.amount_from_display(
                _span(rng, bounds, complexity))))
        busy.add(destination)
        taken += 1

    _add_playing_cables(sound, opts, rng, cables)
    sound.patch_cables = cables


def _add_playing_cables(sound: Sound, opts: GenOptions, rng: random.Random,
                        cables: list[PatchCable]) -> None:
    """Pose les modulations qui rendent un preset jouable au clavier.

    Mesuré sur la carte : ``velocity → volume`` à pleine échelle figure dans
    778 presets sur 911. Sans lui, frapper fort ou doucement donne le même
    son — un preset généré se jouait comme un orgue. Viennent ensuite un
    léger vibrato (579 presets) et le suivi de clavier sur le filtre
    (191 presets), selon le rôle.
    """
    busy = {(c.source, c.destination) for c in cables}
    targets = {c.destination for c in cables}

    if "volume" not in targets:
        cables.append(PatchCable(
            "velocity", "volume",
            PatchCable.amount_from_display(_span(rng, (30, 50), 0.8))))

    lfo1_free = (sound.lfo1.sync_level == 0
                 and not any(c.source == "lfo1" for c in cables))
    if (opts.role in _VIBRATO_ROLES and lfo1_free and "pitch" not in targets
            and rng.random() < 0.55):
        cables.append(PatchCable(
            "lfo1", "pitch", PatchCable.amount_from_display(
                _span(rng, (2, 6)))))

    if (opts.role in _KEYTRACK_ROLES and ("note", "lpfFrequency") not in busy
            and rng.random() < 0.3):
        cables.append(PatchCable(
            "note", "lpfFrequency", PatchCable.amount_from_display(
                _span(rng, (8, 20)))))

    # Les sons tenus bougent dans l'espace stéréo (``random → pan`` :
    # 126 presets de la carte, ``lfo2 → pan`` : 56).
    if (opts.role in ("pad", "drone") and "pan" not in targets
            and rng.random() < 0.6):
        cables.append(PatchCable(
            rng.choice(["lfo2", "random"]), "pan",
            PatchCable.amount_from_display(_span(rng, (8, 22)))))

    # En FM, une enveloppe qui referme le modulateur donne l'attaque
    # brillante qui s'adoucit — celle des pianos électriques et des cloches
    # (``envelope2 → modulator1Volume`` : 52 presets FM de la carte).
    if (sound.mode == "fm" and opts.role in ("bell", "keys", "pluck")
            and "modulator1Amount" not in targets):
        cables.append(PatchCable(
            "envelope2", "modulator1Amount", PatchCable.amount_from_display(
                _span(rng, (14, 34)))))


def _apply_arp(sound: Sound, profile: GenreProfile, opts: GenOptions,
               rng: random.Random, role: str) -> None:
    """Active l'arpégiateur selon la probabilité du genre et du rôle."""
    if rng.random() >= max(0.0, min(1.0, profile.arp_probability)):
        sound.arp.mode = "off"
        sound.arp.arp_mode = "off"
        return
    old = _pick(rng, [("up", 3.0), ("down", 1.5), ("both", 1.5),
                      ("random", 1.0)], "up")
    # Le firmware c1.x **ignore** l'ancien attribut ``mode`` dès que le
    # fichier se déclare c1.2.0 ou plus récent (``sound.cpp``) : il lit
    # ``arpMode``, ``noteMode`` et ``octaveMode``. Les presets générés sont
    # estampillés c1.2.1 ; sans ces trois attributs, leur arpégiateur restait
    # éteint sur la machine. ``mode`` est gardé pour les firmwares anciens.
    sound.arp.mode = old
    sound.arp.arp_mode = "arp"
    sound.arp.note_mode = {"up": "up", "down": "down", "both": "upDown",
                           "random": "random"}[old]
    sound.arp.octave_mode = _pick(rng, [("up", 5.0), ("upDown", 1.5),
                                        ("alt", 0.8)], "up")
    # Octaves relevées sur les 80 arpèges de la carte : 2 (47), 1 (25), 3 (6).
    sound.arp.num_octaves = int(_pick(rng, [("2", 5.0), ("1", 3.0),
                                            ("3", 1.0)], "2"))
    sound.arp.sync_level = int(_pick(rng, [(str(v), w) for v, w in _ARP_SYNC],
                                     "7"))
    # Vitesse au neutre (72 arpèges sur 80) : la division vient de la
    # synchro, la vitesse ne fait que la décaler.
    sound.set_param("arpeggiatorRate", _disp(25))
    sound.set_param("arpeggiatorGate", _disp(_span(rng, (18, 32))))


# --------------------------------------------------------------------------- #
# Sûreté : le preset doit sonner
# --------------------------------------------------------------------------- #

def _ensure_audible(sound: Sound) -> None:
    """Corrige un preset qui ne produirait aucun son.

    Quatre vérifications, chacune correspondant à une façon réelle d'obtenir
    le silence :

    1. volume général trop bas ;
    2. aucun oscillateur audible (type ``sample`` sans fichier, par exemple) ;
    3. enveloppe d'amplitude sans sustain **ni** decay — la note s'ouvre et ne
       laisse rien passer ;
    4. filtre fermé sans aucune modulation qui vienne l'ouvrir.
    """
    # 1. Volume général.
    if sound.display("volume") < MIN_VOLUME:
        sound.set_param("volume", _disp(MIN_VOLUME + 6))

    # 2. Au moins un oscillateur qui produit quelque chose.
    def _usable(osc: Osc) -> bool:
        if osc.type in _SILENT_OSC_TYPES:
            return bool(osc.file_name)
        return True

    if not _usable(sound.osc1):
        if _usable(sound.osc2):
            sound.osc1, sound.osc2 = sound.osc2, sound.osc1
            sound.set_param("oscAVolume", _disp(44))
        else:
            sound.osc1 = Osc(type="saw")
    if sound.display("oscAVolume") < 12:
        sound.set_param("oscAVolume", _disp(42))

    # 3. Enveloppe d'amplitude : il faut du sustain ou du decay.
    if (sound.env1.sustain <= INT32_MIN + 1
            and sound.env1.decay <= INT32_MIN + 1):
        sound.env1.decay = _disp(20)
        sound.env1.sustain = _disp(30)
    # Une attaque maximale avec un decay nul rend la note inaudible en jeu.
    if sound.env1.attack >= INT32_MAX - 1:
        sound.env1.attack = _disp(30)

    # 4. Filtre : s'il est presque fermé, il faut quelque chose qui l'ouvre.
    opens_filter = any(
        c.destination in ("lpfFrequency", "lpfMorph") and c.amount > 0
        for c in sound.patch_cables)
    if sound.display("lpfFrequency") < MIN_SAFE_CUTOFF and not opens_filter:
        sound.set_param("lpfFrequency", _disp(MIN_SAFE_CUTOFF + 8))

    # Une résonance extrême sur un filtre très ouvert sature inutilement.
    if (sound.display("lpfResonance") > 46
            and sound.display("lpfFrequency") > 44):
        sound.set_param("lpfResonance", _disp(34))


# --------------------------------------------------------------------------- #
# Variantes
# --------------------------------------------------------------------------- #

def randomize(seed: int | None = None, role: str = "") -> SynthPreset:
    """Preset entièrement au hasard : genre, rôle et curseurs tirés au sort."""
    value = seed if seed is not None else random.randrange(1 << 30)
    rng = random.Random(value)
    from .genres import genre_keys

    opts = GenOptions(
        genre=rng.choice(genre_keys()),
        role=role if role in ROLES else rng.choice(ROLES),
        seed=value,
        brightness=rng.random(),
        movement=rng.random(),
        space=rng.random(),
        dirt=rng.random(),
        width=rng.random(),
        complexity=rng.random(),
    )
    return generate(opts)


def mutate(preset: SynthPreset, amount: float = 0.25,
           seed: int | None = None) -> SynthPreset:
    """Variante légère d'un preset existant.

    ``amount`` va de 0 (copie conforme) à 1 (presque un autre son). Seuls les
    paramètres continus sont déplacés ; les choix structurels (formes d'onde,
    mode) ne changent qu'au-delà d'une mutation forte, pour que la variante
    reste reconnaissable.
    """
    rng = random.Random(seed if seed is not None
                        else random.randrange(1 << 30))
    strength = _clamp01(amount)
    clone = preset.copy(preset.sound.name)
    sound = clone.sound

    for key in list(sound.params):
        if rng.random() > 0.3 + 0.6 * strength:
            continue
        current = sound.display(key)
        shift = rng.gauss(0.0, 10.0 * strength)
        bipolar = key in ("pan", "pitchAdjust", "oscAPitchAdjust",
                          "oscBPitchAdjust")
        if bipolar:
            sound.set_param(key, _disp(int(round(max(-50, min(50,
                                                              current + shift)))),
                                       bipolar=True))
        else:
            sound.set_param(key, _disp(int(round(max(0, min(50,
                                                            current + shift))))))

    for env in (sound.env1, sound.env2):
        for field_name in ("attack", "decay", "sustain", "release"):
            if rng.random() > 0.3 + 0.6 * strength:
                continue
            from .fixedpoint import to_display

            current = to_display(getattr(env, field_name))
            shift = rng.gauss(0.0, 10.0 * strength)
            setattr(env, field_name,
                    _disp(int(round(max(0, min(50, current + shift))))))

    for cable in sound.patch_cables:
        if rng.random() > 0.3 + 0.6 * strength:
            continue
        cable.set_display(int(round(
            cable.display() + rng.gauss(0.0, 10.0 * strength))))

    if strength > 0.5:
        if rng.random() < strength - 0.4:
            sound.unison_num = max(1, min(8, sound.unison_num
                                          + rng.choice([-1, 1])))
        if rng.random() < strength - 0.45:
            sound.lfo1.type = rng.choice(["sine", "triangle", "square", "saw",
                                          "sah", "rwalk"])

    _ensure_audible(sound)
    clone.name = sound.name
    return clone


def morph(a: SynthPreset, b: SynthPreset, t: float) -> SynthPreset:
    """Interpole deux presets : ``t=0`` donne ``a``, ``t=1`` donne ``b``.

    Les paramètres continus sont mélangés ; les choix discrets (formes d'onde,
    mode, type de filtre) basculent à mi-chemin, parce qu'il n'existe pas
    d'intermédiaire entre une dent de scie et un carré.
    """
    ratio = _clamp01(t)
    clone = a.copy(a.sound.name)
    sound, other = clone.sound, b.sound

    for key in set(sound.params) | set(other.params):
        start = sound.param(key, INT32_MIN)
        end = other.param(key, INT32_MIN)
        sound.set_param(key, int(round(start + (end - start) * ratio)))

    for name in ("env1", "env2"):
        src, dst = getattr(sound, name), getattr(other, name)
        for field_name in ("attack", "decay", "sustain", "release"):
            start = getattr(src, field_name)
            end = getattr(dst, field_name)
            setattr(src, field_name,
                    int(round(start + (end - start) * ratio)))

    sound.unison_num = int(round(sound.unison_num
                                 + (other.unison_num - sound.unison_num) * ratio))
    sound.unison_detune = int(round(
        sound.unison_detune + (other.unison_detune - sound.unison_detune) * ratio))

    if ratio >= 0.5:
        sound.osc1 = Osc(**vars(other.osc1))
        sound.osc2 = Osc(**vars(other.osc2))
        sound.mode = other.mode
        sound.lpf_mode = other.lpf_mode
        sound.mod_fx_type = other.mod_fx_type
        sound.lfo1 = LFO(**vars(other.lfo1))
        sound.lfo2 = LFO(**vars(other.lfo2))
        sound.patch_cables = [PatchCable(**vars(c)) for c in other.patch_cables]

    _ensure_audible(sound)
    name = f"{a.sound.name[:12]}-{b.sound.name[:12]}"
    sound.name = safe_deluge_name(name)
    clone.name = sound.name
    return clone


def variations(preset: SynthPreset, n: int = 8, amount: float = 0.3,
               seed: int | None = None) -> list[SynthPreset]:
    """``n`` variantes d'un preset, numérotées et reproductibles."""
    base = seed if seed is not None else random.randrange(1 << 30)
    out: list[SynthPreset] = []
    for i in range(max(0, int(n))):
        variant = mutate(preset, amount, seed=base + i)
        variant.sound.name = safe_deluge_name(
            f"{preset.sound.name[:56]} {i + 1}")
        variant.name = variant.sound.name
        out.append(variant)
    return out


# --------------------------------------------------------------------------- #
# Nommage et description
# --------------------------------------------------------------------------- #

#: Qualificatifs, choisis pour sonner juste sur l'écran du Deluge (ASCII,
#: courts, évocateurs). Mélange volontaire de français et d'anglais, comme le
#: vocabulaire des producteurs.
_ADJECTIVES = (
    "ACID", "DARK", "NEON", "WARM", "COLD", "DEEP", "HARD", "SOFT", "RAW",
    "GLASS", "VELVET", "RUST", "CHROME", "AMBRE", "NUIT", "BRUME", "ORAGE",
    "VELOURS", "CRISTAL", "LUNAIRE", "SOLAIRE", "FERRIQUE", "ECHO", "VAPEUR",
    "SABLE", "MARBRE", "OMBRE", "AURORE", "PRISME", "TITANE",
)

#: Substantifs par rôle : un nom de basse ne ressemble pas à un nom de nappe.
_NOUNS = {
    "bass": ("GROWL", "SUB", "WOBBLE", "GRAVE", "RUMBLE", "BASSE", "PUNCH"),
    "lead": ("LEAD", "CRY", "BLADE", "SOLO", "VOIX", "SIREN", "FLECHE"),
    "pad": ("PAD", "NAPPE", "DRIFT", "CLOUD", "VOILE", "HALO", "BRUME"),
    "pluck": ("PLUCK", "PINCE", "DROP", "GOUTTE", "SPARK", "CORDE"),
    "keys": ("KEYS", "CLAVIER", "PIANO", "RHODES", "TOUCHE", "ORGUE"),
    "stab": ("STAB", "ACCORD", "HIT", "CHOC", "BRIQUE"),
    "fx": ("FX", "SWEEP", "NOISE", "RISER", "SOUFFLE", "VERTIGE"),
    "drone": ("DRONE", "BOURDON", "DRIFT", "MASSE", "TUNNEL"),
    "arp": ("ARP", "ARPEGE", "SEQ", "MOTIF", "SPIRALE", "HORLOGE"),
    "bell": ("BELL", "CLOCHE", "CHIME", "GLASS", "TINTEMENT"),
}


def suggest_name(opts: GenOptions, seed: int) -> str:
    """Nom évocateur et reproductible : ``ACID GROWL 3``, ``NEON PAD``…

    Le tirage mêle le genre et le rôle à la graine : sinon une même graine
    donnait le même qualificatif à tous les genres, et une série de presets
    s'appelait « VELVET » du premier au dernier.
    """
    role = opts.role if opts.role in _NOUNS else "bass"
    rng = random.Random(f"{seed}|{opts.genre}|{role}")
    adjective = rng.choice(_ADJECTIVES)
    noun = rng.choice(_NOUNS[role])
    name = f"{adjective} {noun}"
    if rng.random() < 0.45:
        name += f" {rng.randint(2, 99)}"
    return safe_deluge_name(name)


def describe(preset: SynthPreset) -> str:
    """Description française du son, telle qu'on la lirait dans un magazine."""
    sound = preset.sound
    parts: list[str] = []

    labels = {"subtractive": "soustractive", "fm": "FM", "ringmod": "ring mod"}
    parts.append(f"Synthèse {labels.get(sound.mode, sound.mode)}")

    oscs = sound.osc_label(sound.osc1)
    if sound.display("oscBVolume") > 6:
        oscs += f" + {sound.osc_label(sound.osc2)}"
    parts.append(f"oscillateurs {oscs}")

    cutoff = sound.display("lpfFrequency")
    resonance = sound.display("lpfResonance")
    if cutoff < 16:
        colour = "très sombre"
    elif cutoff < 28:
        colour = "sombre"
    elif cutoff < 40:
        colour = "équilibré"
    else:
        colour = "brillant"
    filtre = f"filtre {sound.lpf_mode} {colour}"
    if resonance > 32:
        filtre += ", très résonant"
    elif resonance > 18:
        filtre += ", résonant"
    parts.append(filtre)

    from .fixedpoint import to_display

    a = to_display(sound.env1.attack)
    r = to_display(sound.env1.release)
    s = to_display(sound.env1.sustain)
    if a < 6:
        shape = "attaque immédiate"
    elif a < 18:
        shape = "attaque douce"
    else:
        shape = "attaque lente"
    if s < 8:
        shape += ", son percussif"
    elif r > 30:
        shape += ", longue extinction"
    parts.append(shape)

    if sound.unison_num > 2:
        parts.append(f"{sound.unison_num} voix désaccordées")

    jeu = {"mono": "jeu monophonique", "legato": "jeu legato"}.get(
        sound.polyphonic, "")
    if sound.display("portamento") > 0:
        jeu = (jeu + ", glissé d'une note à l'autre") if jeu else             "glissé d'une note à l'autre"
    if jeu:
        parts.append(jeu)

    divisions = {5: "noires", 6: "croches", 7: "doubles-croches",
                 8: "triples-croches"}
    fx = [f"delay en {divisions[sound.delay_sync_level]}"
          if f == "delay" and sound.delay_sync_level in divisions else f
          for f in sound.fx_list()]
    if fx:
        parts.append("effets : " + ", ".join(fx).lower())

    if sound.mode == "fm":
        ecart = sound.modulator1.transpose
        if ecart:
            parts.append(f"modulateur à {ecart:+d} demi-tons")
        else:
            parts.append("modulateur à l'unisson")

    if sound.arp.is_on:
        sens = {"up": "montant", "down": "descendant", "upDown": "aller-retour",
                "random": "aléatoire", "asPlayed": "dans l'ordre joué"}
        division = divisions.get(sound.arp.sync_level, "")
        texte = "arpégiateur " + sens.get(sound.arp.note_mode or "up",
                                          sound.arp.note_mode or "")
        if division:
            texte += f" en {division}"
        parts.append(texte)

    if sound.patch_cables:
        parts.append(f"{len(sound.patch_cables)} modulation(s)")

    return ". ".join(parts) + "."
