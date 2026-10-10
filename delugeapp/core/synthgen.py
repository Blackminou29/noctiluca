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
  une même graine redonne exactement le même son, aujourd'hui comme dans six
  mois, quoi qu'il se passe ailleurs dans l'application.

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
    Osc,
    PatchCable,
    Sound,
    SynthPreset,
)
from .sdcard import safe_deluge_name

log = logging.getLogger(__name__)

#: Modes de synthèse du Deluge.
MODES = ("subtractive", "fm", "ringmod")

#: Modes de filtre passe-bas acceptés par le firmware.
LPF_MODES = ("24dB", "12dB", "24dBDrive", "SVF_Bandpass", "SVF_Notch")

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
    rng = random.Random(seed)

    role = opts.role if opts.role in ROLES else "bass"
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
        # La FM reste minoritaire : elle demande un réglage fin pour sonner,
        # et un tirage au sort y produit souvent du bruit.
        sound.mode = _pick(rng, [("subtractive", 8.0), ("fm", 1.2),
                                 ("ringmod", 0.6)], "subtractive")
    role = opts.role
    if role in ("bass", "lead"):
        sound.polyphonic = _pick(rng, [("mono", 3.0), ("legato", 1.0),
                                       ("poly", 0.6)], "mono")
    elif role == "drone":
        sound.polyphonic = "poly"
    else:
        sound.polyphonic = _pick(rng, [("poly", 6.0), ("auto", 1.0)], "poly")
    sound.max_voices = 8 if sound.polyphonic == "poly" else 0


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
        sound.set_param("modulator1Amount", _disp(_span(rng, (10, 40))))
        sound.set_param("modulator1Feedback", _disp(_span(rng, (0, 16))))

    if rng.random() < 0.18 + 0.3 * _clamp01(opts.dirt):
        sound.set_param("noiseVolume", _disp(_span(rng, (2, 20))))


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

    # Un passe-haut léger dégage le grave des sons aigus ; sur une basse il
    # serait contre-productif.
    if opts.role not in ("bass", "drone") and rng.random() < 0.3:
        sound.hpf_mode = "HPLadder"
        sound.set_param("hpfFrequency", _disp(_span(rng, (0, 14))))

    dirt = _clamp01(opts.dirt)
    if dirt > 0.5 and rng.random() < dirt:
        sound.clipping_amount = int(round((dirt - 0.5) * 2 * rng.uniform(1, 8)))
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
    # Le LFO 2 du Deluge est synchronisé au tempo quand sync_level > 0 : utile
    # pour les mouvements rythmiques.
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

    if rng.random() < 0.3 + 0.5 * _clamp01(opts.width):
        sound.mod_fx_type = _pick(rng, [("chorus", 3.0), ("stereoChorus", 2.0),
                                        ("flanger", 1.0), ("phaser", 1.0)],
                                  "chorus")
        if "modFXDepth" not in (profile.fx or {}):
            sound.set_param("modFXDepth", _disp(_span(rng, (8, 30))))
    sound.set_param("volume", _disp(_span(rng, (34, 46), 0.6)))


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
    extras = [
        ("velocity", "volume", (8, 24)),
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

    sound.patch_cables = cables


def _apply_arp(sound: Sound, profile: GenreProfile, opts: GenOptions,
               rng: random.Random, role: str) -> None:
    """Active l'arpégiateur selon la probabilité du genre et du rôle."""
    if rng.random() >= max(0.0, min(1.0, profile.arp_probability)):
        sound.arp.mode = "off"
        return
    sound.arp.mode = _pick(rng, [("up", 3.0), ("down", 1.5), ("both", 1.5),
                                 ("random", 1.0)], "up")
    sound.arp.num_octaves = rng.choice([1, 2, 2, 3])
    sound.arp.sync_level = rng.choice([7, 7, 8, 9])
    sound.set_param("arpeggiatorRate", _disp(_span(rng, (16, 38))))
    sound.set_param("arpeggiatorGate", _disp(_span(rng, (16, 34))))


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
                                          "sampleAndHold", "randomWalk"])

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

    fx = sound.fx_list()
    if fx:
        parts.append("effets : " + ", ".join(fx).lower())

    if sound.arp.is_on:
        parts.append(f"arpégiateur {sound.arp.mode}")

    if sound.patch_cables:
        parts.append(f"{len(sound.patch_cables)} modulation(s)")

    return ". ".join(parts) + "."
