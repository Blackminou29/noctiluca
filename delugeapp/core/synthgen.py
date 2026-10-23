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
from dataclasses import dataclass, field, replace

from ..i18n import N_, tr, untranslated
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
    #: Graine propre d'un aspect du son (:data:`FACETS`), à la place de
    #: ``seed`` : c'est ainsi qu'une variante tire un autre filtre en gardant
    #: le reste.
    facets: dict[str, int] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Outils de tirage
# --------------------------------------------------------------------------- #

#: Les aspects d'un son, dans l'ordre où le générateur les règle. Chacun a
#: ses propres tirages : changer un aspect — sa graine, ou le curseur qui le
#: règle — ne touche pas aux autres.
FACETS: dict[str, str] = {
    "moteur": N_("moteur de synthèse, jeu, glissé et volume"),
    "timbre": N_("formes d'onde, niveaux et accord des oscillateurs"),
    "filtre": N_("type de filtre, coupure, résonance et saturation"),
    "enveloppes": N_("enveloppes d'amplitude et de modulation"),
    "mouvement": N_("formes et vitesses des LFO"),
    "largeur": N_("unisson, désaccord et panoramique"),
    "espace": N_("réverbération, délai et effet de modulation"),
    "modulations": N_("câbles de modulation"),
    "arpège": N_("arpégiateur"),
}


class _Tirages:
    """Les tirages d'un aspect du son, nommés et indépendants.

    Chaque décision — « la coupure », « la saturation » — a son propre
    générateur, tiré de la graine de l'aspect et de son nom. Le nombre de
    tirages d'une décision ne décale donc jamais celui d'une autre.

    **Pourquoi.** Tous les tirages passaient par un seul générateur : un
    curseur qui ouvrait une branche (la réduction numérique au-delà de 0,5
    de saleté) consommait un nombre de plus, et décalait tout ce qui suivait.
    Mesuré à graine égale, 0,5 → 0,7 de saleté changeait 18 réglages en
    médiane et la structure du son (oscillateurs, câbles, mode de jeu) dans
    584 cas sur 660 : un autre son, pas le même en plus sale. La brillance,
    elle, ne changeait qu'un réglage.
    """

    __slots__ = ("_base", "_flux")

    def __init__(self, base: str) -> None:
        self._base = base
        self._flux: dict[str, random.Random] = {}

    def __call__(self, name: str) -> random.Random:
        flux = self._flux.get(name)
        if flux is None:
            flux = random.Random(f"{self._base}|{name}")
            self._flux[name] = flux
        return flux

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
    facets = dict(opts.facets or {})

    def tirages(facet: str) -> _Tirages:
        # Genre et rôle entrent dans la graine : sans cela, la graine 42
        # faisait les mêmes choix — mode de jeu, effet, saturation — dans
        # tous les genres, comme le générateur de kits avec ses grosses
        # caisses. L'aspect y entre aussi, et sa graine propre s'il en a une.
        return _Tirages(f"{facets.get(facet, seed)}|{opts.genre}|{role}"
                        f"|{facet}")

    profile = get_genre(opts.genre).for_role(role)

    preset = SynthPreset.new("GEN")
    sound = preset.sound
    sound.params = dict(DEFAULT_PARAMS)

    _apply_mode(sound, profile, opts, tirages("moteur"))
    _apply_oscillators(sound, profile, opts, tirages("timbre"))
    _apply_filter(sound, profile, opts, tirages("filtre"))
    _apply_envelopes(sound, profile, opts, tirages("enveloppes"))
    _apply_lfos(sound, profile, opts, tirages("mouvement"))
    _apply_unison(sound, profile, opts, tirages("largeur"))
    _apply_fx(sound, profile, opts, tirages("espace"))
    _apply_cables(sound, profile, opts, tirages("modulations"))
    _apply_arp(sound, profile, opts, tirages("arpège"), role)
    # Le volume général appartient au moteur : une variante qui tire un autre
    # espace ou un autre filtre ne doit pas jouer plus fort. Volume médian
    # des vrais presets : 38 à 40.
    sound.set_param("volume", _disp(_span(tirages("moteur")("volume"),
                                          (30, 44), 0.5)))

    _ensure_audible(sound)

    name = opts.name.strip() if opts.name else suggest_name(opts, seed)
    sound.name = safe_deluge_name(name)
    preset.name = sound.name
    log.debug("preset généré : %s (genre %s, rôle %s, graine %s)",
              sound.name, opts.genre, role, seed)
    return preset


def _apply_mode(sound: Sound, profile: GenreProfile, opts: GenOptions,
                tirage: _Tirages) -> None:
    """Choisit le mode de synthèse et la polyphonie."""
    if opts.mode in MODES:
        sound.mode = opts.mode
    else:
        # Le rôle et le genre choisissent le moteur : une cloche est FM, un
        # effet sur deux est en ring mod sur la carte. À défaut, la FM reste
        # minoritaire — elle demande un accord des modulateurs pour sonner.
        sound.mode = _pick(tirage("moteur"), profile.modes or DEFAULT_MODES,
                           "subtractive")
    role = opts.role
    if role in ("bass", "lead"):
        sound.polyphonic = _pick(tirage("jeu"), _MONO_ROLES_POLY, "poly")
    elif role == "drone":
        sound.polyphonic = "poly"
    else:
        # « auto » : 1 à 2 % des vrais presets de ces rôles, contre 16 % des
        # presets générés jusqu'ici.
        sound.polyphonic = _pick(tirage("jeu"), [("poly", 40.0), ("auto", 1.0)],
                                 "poly")
    # Huit voix, quelle que soit la polyphonie : c'est ce qu'écrit la machine
    # pour chacun des 94 sons des morceaux de la carte, legato et auto
    # compris. Le 0 qu'on écrivait pour les sons non polyphoniques est une
    # valeur qu'elle ne produit jamais (son menu remplace 0 par 127) et
    # qu'elle lit comme un plafond de zéro voix (``AudioEngine::solicitVoice``).
    sound.max_voices = 8
    _apply_glide(sound, profile, role, tirage)


def _apply_glide(sound: Sound, profile: GenreProfile, role: str,
                 tirage: _Tirages) -> None:
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
    r = tirage("glissé")
    if r.random() < chance:
        sound.set_param("portamento", _disp(_span(r, bounds)))


def _apply_oscillators(sound: Sound, profile: GenreProfile, opts: GenOptions,
                       tirage: _Tirages) -> None:
    """Règle les deux oscillateurs, et les échantillons si on en donne."""
    samples = [s for s in (opts.use_samples or []) if s]
    if samples:
        sound.osc1 = Osc(type="sample", file_name=samples[0])
        if len(samples) > 1:
            sound.osc2 = Osc(type="sample", file_name=samples[1])
        else:
            sound.osc2 = Osc(type=_pick(tirage("osc 2"), profile.osc_types,
                                        "square"))
            sound.set_param("oscBVolume", _disp(_span(tirage("niveau B"),
                                                      (0, 18))))
    else:
        # Sans échantillon fourni, écarter d'emblée les formes qui en
        # réclament un : les tirer puis les corriger ensuite donnerait un son
        # qui ne ressemble plus au profil du genre.
        playable = [(name, weight) for name, weight in profile.osc_types
                    if name not in _SILENT_OSC_TYPES]
        first = _pick(tirage("osc 1"), playable, "saw")
        if first in _ANALOG_VARIANT and tirage("analogique").random() \
                < _ANALOG_CHANCE:
            first = _ANALOG_VARIANT[first]
        sound.osc1 = Osc(type=first)
        # Le second oscillateur reprend souvent la même forme, décalée.
        r = tirage("osc 2")
        second = first if r.random() < 0.45 else _pick(r, playable, "square")
        sound.osc2 = Osc(type=second)

    sound.set_param("oscAVolume", _disp(_span(tirage("niveau A"), (40, 50), 0.8)))

    if sound.osc2.type not in _SILENT_OSC_TYPES or sound.osc2.file_name:
        # Un deuxième oscillateur plus discret que le premier : c'est ce qui
        # épaissit un son sans le rendre confus.
        level = _span(tirage("niveau B"), (0, 42), 0.35 + 0.4 * _clamp01(opts.width))
        sound.set_param("oscBVolume", _disp(level))
        # Désaccord ou transposition à l'octave / à la quinte.
        choice = tirage("accord B").random()
        if choice < 0.35:
            sound.osc2.transpose = -12
        elif choice < 0.5:
            sound.osc2.transpose = 12
        elif choice < 0.6:
            sound.osc2.transpose = 7
        sound.osc2.cents = int(round(
            tirage("cents B").uniform(-1, 1) * 25 * _clamp01(opts.width)))

    if opts.role == "bass":
        # Une basse se joue bas : sans cela le générateur produit des sons
        # justes mais inutilisables comme basse.
        sound.transpose = tirage("octave").choice([-24, -12, -12, 0])

    # Largeur d'impulsion, utile aux formes carrées.
    if "square" in (sound.osc1.type or ""):
        sound.set_param("oscAPulseWidth", _disp(_span(tirage("impulsion"),
                                                      (10, 40))))

    if sound.mode == "fm":
        _apply_fm(sound, opts, tirage)

    r = tirage("bruit")
    if r.random() < 0.18 + 0.3 * _clamp01(opts.dirt):
        sound.set_param("noiseVolume", _disp(_span(r, (2, 20))))


def _apply_fm(sound: Sound, opts: GenOptions, tirage: _Tirages) -> None:
    """Accorde les deux modulateurs FM et règle leur profondeur.

    En FM, ce sont les modulateurs qui font le timbre ; les laisser à
    l'unisson, comme avant, donnait la même couleur à tous les presets FM.
    """
    bell = opts.role == "bell"
    table = FM_BELL_TRANSPOSE if bell else FM_MOD1_TRANSPOSE
    cents = tirage("cents FM")
    sound.modulator1 = Modulator(
        transpose=int(_pick(tirage("accord FM 1"), [(str(v), w) for v, w in table],
                            "0")),
        # Un léger écart de cents rend un timbre FM vivant ; les cloches
        # en prennent davantage, ce qui accentue l'inharmonicité.
        cents=int(round(cents.uniform(0, 12 if bell else 4)))
        if cents.random() < (0.6 if bell else 0.25) else 0)
    sound.modulator2 = Modulator(
        transpose=int(_pick(tirage("accord FM 2"),
                            [(str(v), w) for v, w in FM_MOD2_TRANSPOSE],
                            "-12")),
        to_modulator1=1 if tirage("FM 2 vers 1").random() < 0.4 else 0)
    depth = (18, 40) if bell else (10, 34)
    sound.set_param("modulator1Amount",
                    _disp(_span(tirage("profondeur FM"), depth,
                                0.4 + 0.3 * _clamp01(opts.dirt))))
    sound.set_param("modulator1Feedback", _disp(_span(tirage("rétroaction FM"),
                                                      (0, 14))))
    r = tirage("niveau FM 2")
    if r.random() < 0.5:
        sound.set_param("modulator2Amount", _disp(_span(r, (0, 24))))


def _apply_filter(sound: Sound, profile: GenreProfile, opts: GenOptions,
                  tirage: _Tirages) -> None:
    """Règle le filtre : mode, coupure, résonance."""
    sound.lpf_mode = _pick(tirage("type"), profile.filter_mode, "24dB")
    if sound.lpf_mode not in LPF_MODES:
        sound.lpf_mode = "24dB"

    cutoff = _span(tirage("coupure"), profile.cutoff, _clamp01(opts.brightness))
    sound.set_param("lpfFrequency", _disp(cutoff))
    resonance = _span(tirage("résonance"), profile.resonance, _clamp01(opts.dirt))
    sound.set_param("lpfResonance", _disp(resonance))

    # Un passe-haut dégage le grave inutile, à la fréquence et au réglage
    # des vrais presets du rôle ; sur une basse, rare et bas.
    chance, bounds = _HPF.get(_kin(opts.role), (0.3, (8, 20)))
    r = tirage("passe-haut")
    if r.random() < chance:
        sound.hpf_mode = "HPLadder"
        sound.set_param("hpfFrequency", _disp(_span(r, bounds)))

    # Saturation : 27 à 56 % des vrais presets selon le rôle, réglée entre 2
    # et 5. Le curseur de saleté en change la fréquence et la force.
    dirt = _clamp01(opts.dirt)
    r = tirage("saturation")
    if r.random() < _SATURATION.get(_kin(opts.role), 0.35) * (0.3 + 1.4 * dirt):
        level = int(_pick(r, [(str(v), w) for v, w in _SATURATION_LEVELS],
                          "3"))
        sound.clipping_amount = level + int(round(max(0.0, dirt - 0.5) * 6))

    # Le tirage a lieu quel que soit le curseur : c'est lui qui, autrefois
    # sauté sous 0,5 de saleté, décalait tout le reste du son.
    if tirage("réduction").random() < dirt and dirt > 0.5:
        if "sampleRateReduction" in profile.fx:
            sound.set_param("sampleRateReduction",
                            _disp(_span(tirage("fréquence réduite"),
                                        profile.fx["sampleRateReduction"],
                                        dirt)))
        if "bitCrush" in profile.fx:
            sound.set_param("bitCrush",
                            _disp(_span(tirage("bitcrush"), profile.fx["bitCrush"],
                                        dirt)))


def _apply_envelopes(sound: Sound, profile: GenreProfile, opts: GenOptions,
                     tirage: _Tirages) -> None:
    """Règle l'enveloppe d'amplitude et celle de modulation."""
    def _env(name: str, ranges: dict, bias: float) -> Envelope:
        return Envelope(
            attack=_disp(_span(tirage(name + " attaque"),
                               ranges.get("attack", (0, 6)), bias)),
            decay=_disp(_span(tirage(name + " decay"),
                              ranges.get("decay", (14, 30)), bias)),
            sustain=_disp(_span(tirage(name + " sustain"),
                                ranges.get("sustain", (20, 40)), bias)),
            release=_disp(_span(tirage(name + " release"),
                                ranges.get("release", (10, 24)), bias)),
        )

    sound.env1 = _env(untranslated("env 1"), profile.env1, 0.5)
    sound.env2 = _env(untranslated("env 2"), profile.env2 or profile.env1,
                      _clamp01(opts.movement))


def _apply_lfos(sound: Sound, profile: GenreProfile, opts: GenOptions,
                tirage: _Tirages) -> None:
    """Choisit les formes et les vitesses des deux LFO."""
    types = profile.lfo_types or ["triangle"]
    sound.lfo1 = LFO(type=tirage("forme 1").choice(types))
    sound.lfo2 = LFO(type=tirage("forme 2").choice(types))
    movement = _clamp01(opts.movement)
    sound.set_param("lfo1Rate", _disp(_span(tirage("vitesse 1"), profile.lfo_rate,
                                            movement)))
    sound.set_param("lfo2Rate", _disp(_span(tirage("vitesse 2"), profile.lfo_rate,
                                            movement * 0.7)))
    # Le LFO 1 se cale sur le tempo selon le genre : c'est le « wobble » de
    # la dubstep, la pulsation de la trance. Valeurs de fichier : 5 = noire,
    # 6 = croche, 7 = double-croche.
    chance, levels = profile.lfo_sync
    r = tirage("synchro 1")
    if levels and r.random() < max(0.0, min(1.0, chance)):
        sound.lfo1.sync_level = int(r.choice(list(levels)))
    # Le LFO 2 aussi, plus rarement, pour un mouvement rythmique secondaire.
    r = tirage("synchro 2")
    if r.random() < 0.35 * movement + 0.1:
        sound.lfo2.sync_level = r.choice([5, 6, 7, 7, 8])


def _apply_unison(sound: Sound, profile: GenreProfile, opts: GenOptions,
                  tirage: _Tirages) -> None:
    """Règle l'unisson et le désaccord, qui font la largeur du son."""
    width = _clamp01(opts.width)
    sound.unison_num = _span(tirage("unisson"), profile.unison, width)
    sound.unison_detune = _span(tirage("désaccord"), profile.detune, width)
    sound.unison_spread = int(round(width * tirage("étalement").uniform(0, 40)))
    # Le panoramique reste modéré : un son trop latéralisé gêne au mixage.
    r = tirage("panoramique")
    if r.random() < 0.25:
        sound.set_param("pan", _disp(int(r.uniform(-8, 8)), bipolar=True))


def _apply_fx(sound: Sound, profile: GenreProfile, opts: GenOptions,
              tirage: _Tirages) -> None:
    """Règle réverbération, délai et effets de modulation."""
    space = _clamp01(opts.space)
    for key, bounds in (profile.fx or {}).items():
        if key in ("sampleRateReduction", "bitCrush"):
            continue        # déjà traités avec la saleté
        bias = space if key in ("reverbAmount", "delayFeedback",
                                "delayRate") else _clamp01(opts.movement)
        sound.set_param(key, _disp(_span(tirage(key), bounds, bias)))

    # Effet de modulation à la fréquence des vrais presets du rôle au centre
    # du curseur de largeur, qui la divise ou la multiplie par 2,5 à ses
    # extrémités.
    chance, kinds = _MOD_FX.get(_kin(opts.role), (0.22, [("chorus", 1.0)]))
    r = tirage("effet de modulation")
    if r.random() < chance * (0.4 + 1.2 * _clamp01(opts.width)):
        sound.mod_fx_type = _pick(r, kinds, "chorus")
        if "modFXDepth" not in (profile.fx or {}):
            sound.set_param("modFXDepth", _disp(_span(tirage("profondeur"),
                                                      (8, 30))))
    sound.delay_sync_level = int(_pick(
        tirage("synchro du délai"),
        [(str(v), w) for v, w in _DELAY_SYNC.get(_kin(opts.role),
                                                 [(6, 1.0)])], "6"))


def _apply_cables(sound: Sound, profile: GenreProfile, opts: GenOptions,
                  tirage: _Tirages) -> None:
    """Pose les modulations (patch cables) d'après les recettes du genre."""
    recipes = profile.cable_recipes or [[("envelope2", "lpfFrequency",
                                          (12, 34))]]
    recipe = list(tirage("recette").choice(recipes))
    complexity = _clamp01(opts.complexity)

    cables: list[PatchCable] = []
    for index, (source, destination, bounds) in enumerate(recipe):
        amount = _span(tirage("recette %d" % index), bounds,
                       0.4 + 0.5 * complexity)
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
    tirage("appoint").shuffle(extras)
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
                _span(tirage("appoint " + destination), bounds, complexity))))
        busy.add(destination)
        taken += 1

    _add_playing_cables(sound, opts, tirage, cables)
    sound.patch_cables = cables


def _add_playing_cables(sound: Sound, opts: GenOptions, tirage: _Tirages,
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
            PatchCable.amount_from_display(_span(tirage("vélocité"), (30, 50),
                                                 0.8))))

    lfo1_free = (sound.lfo1.sync_level == 0
                 and not any(c.source == "lfo1" for c in cables))
    r = tirage("vibrato")
    if (opts.role in _VIBRATO_ROLES and lfo1_free and "pitch" not in targets
            and r.random() < 0.55):
        cables.append(PatchCable(
            "lfo1", "pitch", PatchCable.amount_from_display(
                _span(r, (2, 6)))))

    r = tirage("suivi de clavier")
    if (opts.role in _KEYTRACK_ROLES and ("note", "lpfFrequency") not in busy
            and r.random() < 0.3):
        cables.append(PatchCable(
            "note", "lpfFrequency", PatchCable.amount_from_display(
                _span(r, (8, 20)))))

    # Les sons tenus bougent dans l'espace stéréo (``random → pan`` :
    # 126 presets de la carte, ``lfo2 → pan`` : 56).
    r = tirage("panoramique modulé")
    if (opts.role in ("pad", "drone") and "pan" not in targets
            and r.random() < 0.6):
        cables.append(PatchCable(
            r.choice(["lfo2", "random"]), "pan",
            PatchCable.amount_from_display(_span(r, (8, 22)))))

    # En FM, une enveloppe qui referme le modulateur donne l'attaque
    # brillante qui s'adoucit — celle des pianos électriques et des cloches
    # (``envelope2 → modulator1Volume`` : 52 presets FM de la carte).
    if (sound.mode == "fm" and opts.role in ("bell", "keys", "pluck")
            and "modulator1Amount" not in targets):
        cables.append(PatchCable(
            "envelope2", "modulator1Amount", PatchCable.amount_from_display(
                _span(tirage("enveloppe FM"), (14, 34)))))


def _apply_arp(sound: Sound, profile: GenreProfile, opts: GenOptions,
               tirage: _Tirages, role: str) -> None:
    """Active l'arpégiateur selon la probabilité du genre et du rôle."""
    if tirage("arpège").random() >= max(0.0, min(1.0, profile.arp_probability)):
        sound.arp.mode = "off"
        sound.arp.arp_mode = "off"
        return
    old = _pick(tirage("sens"), [("up", 3.0), ("down", 1.5), ("both", 1.5),
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
    sound.arp.octave_mode = _pick(tirage("octaves"), [("up", 5.0), ("upDown", 1.5),
                                                 ("alt", 0.8)], "up")
    # Octaves relevées sur les 80 arpèges de la carte : 2 (47), 1 (25), 3 (6).
    sound.arp.num_octaves = int(_pick(tirage("étendue"), [("2", 5.0), ("1", 3.0),
                                                     ("3", 1.0)], "2"))
    sound.arp.sync_level = int(_pick(tirage("division"),
                                     [(str(v), w) for v, w in _ARP_SYNC],
                                     "7"))
    # Vitesse au neutre (72 arpèges sur 80) : la division vient de la
    # synchro, la vitesse ne fait que la décaler.
    sound.set_param("arpeggiatorRate", _disp(25))
    sound.set_param("arpeggiatorGate", _disp(_span(tirage("durée"), (18, 32))))


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
# Variantes dans le style
# --------------------------------------------------------------------------- #

#: Variantes « dans une direction » : le même son, un curseur poussé. La
#: graine ne change pas, et chaque décision a son propre tirage
#: (:class:`_Tirages`) : seuls bougent les réglages que ce curseur règle.
NUDGES: dict[str, tuple[str, float]] = {
    N_("Plus brillant"): ("brightness", 0.2),
    N_("Plus sombre"): ("brightness", -0.2),
    N_("Plus sale"): ("dirt", 0.2),
    N_("Plus propre"): ("dirt", -0.2),
    N_("Plus large"): ("width", 0.2),
    N_("Plus étroit"): ("width", -0.2),
    N_("Plus d'espace"): ("space", 0.2),
    N_("Plus sec"): ("space", -0.2),
    N_("Plus de mouvement"): ("movement", 0.2),
    N_("Plus statique"): ("movement", -0.2),
}

#: Aspects qu'une variante tire à nouveau. Le moteur et l'arpège n'y sont
#: pas : changer de moteur fait un autre instrument, et l'arpégiateur est
#: éteint sur la plupart des sons.
VARIABLE_FACETS = ("timbre", "filtre", "enveloppes", "mouvement", "espace",
                   "modulations", "largeur")

#: Libellé d'une variante qui tire un aspect à nouveau.
FACET_LABELS: dict[str, str] = {
    "timbre": N_("Autre timbre"), "filtre": N_("Autre filtre"),
    "enveloppes": N_("Autres enveloppes"), "mouvement": N_("Autre mouvement"),
    "espace": N_("Autre espace"), "modulations": N_("Autres modulations"),
    "largeur": N_("Autre largeur"),
}


def _copy_options(opts: GenOptions) -> GenOptions:
    return replace(opts, use_samples=list(opts.use_samples or []),
                   facets=dict(opts.facets or {}))


def nudged(opts: GenOptions, label: str) -> GenOptions | None:
    """Les réglages de ``opts``, un curseur poussé (:data:`NUDGES`).

    Rend ``None`` si le curseur est déjà en butée : la variante serait le
    même son.
    """
    if label not in NUDGES:
        raise ValueError(tr("variante inconnue : %s") % label)
    macro, delta = NUDGES[label]
    current = _clamp01(getattr(opts, macro, 0.5))
    target = _clamp01(current + delta)
    if abs(target - current) < 1e-6:
        return None
    out = _copy_options(opts)
    setattr(out, macro, round(target, 3))
    return out


def rerolled(opts: GenOptions, facet: str, seed: int) -> GenOptions:
    """Les réglages de ``opts``, un seul aspect tiré à nouveau."""
    if facet not in FACETS:
        raise ValueError(tr("aspect inconnu : %s") % facet)
    out = _copy_options(opts)
    out.facets[facet] = int(seed)
    return out


@dataclass
class Variant:
    """Une variante d'un preset généré : son libellé (clé française,
    traduite à l'affichage), ses réglages, et le preset obtenu."""

    label: str
    options: GenOptions
    preset: SynthPreset
    #: L'aspect tiré à nouveau, ou le curseur poussé.
    changed: str = ""
    #: Le preset porte des retouches faites à la main
    #: (:func:`.soundedit.carry_edits`) : ``generate(options)`` ne le refait
    #: plus.
    retouched: bool = False


def style_variations(opts: GenOptions, n: int = 8,
                     seed: int | None = None) -> list[Variant]:
    """``n`` variantes **dans le style** du son que donnent ``opts``.

    Une variante ne sort jamais du profil du genre et du rôle : elle tire à
    nouveau un seul aspect (un autre filtre, d'autres enveloppes…) ou pousse
    un seul curseur (plus brillant, plus sale…), le reste du son restant
    identique. ``mutate`` déplace au contraire chaque réglage au hasard, sans
    connaître le profil.

    Les aspects d'abord, puis les directions, du côté où le curseur a le
    plus de marge. Reproductible pour une même ``seed``.
    """
    base_seed = seed if seed is not None else random.randrange(1 << 30)
    rng = random.Random(f"variantes|{base_seed}")
    # Les aspects dans un ordre propre à la graine : deux séries de variantes
    # ne commencent pas toutes par le timbre.
    facets = [("facet", f) for f in VARIABLE_FACETS]
    rng.shuffle(facets)
    nudges = []
    for up, down in ((N_("Plus brillant"), N_("Plus sombre")),
                     (N_("Plus sale"), N_("Plus propre")),
                     (N_("Plus d'espace"), N_("Plus sec")),
                     (N_("Plus large"), N_("Plus étroit")),
                     (N_("Plus de mouvement"), N_("Plus statique"))):
        current = _clamp01(getattr(opts, NUDGES[up][0], 0.5))
        nudges.append(("nudge", up if current <= 0.5 else down))
    # Aspect et direction en alternance : les premières variantes couvrent
    # déjà les deux façons de varier.
    order: list[tuple[str, str]] = []
    while facets or nudges:
        if facets:
            order.append(facets.pop(0))
        if nudges:
            order.append(nudges.pop(0))
    out: list[Variant] = []
    base_name = (opts.name or "").strip()
    for index, (kind, key) in enumerate(order[:max(0, int(n))]):
        if kind == "facet":
            options = rerolled(opts, key, rng.randrange(1 << 30))
            label = FACET_LABELS[key]
        else:
            options = nudged(opts, key)
            if options is None:
                continue
            label = key
        preset = generate(options)
        if base_name:
            preset.sound.name = safe_deluge_name(f"{base_name[:56]} {index + 2}")
            preset.name = preset.sound.name
        out.append(Variant(label=label, options=options, preset=preset,
                           changed=key))
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
    """Description du son, telle qu'on la lirait dans un magazine, dans la
    langue de l'interface."""
    sound = preset.sound
    parts: list[str] = []

    labels = {"subtractive": N_("soustractive"), "fm": "FM",
              "ringmod": N_("ring mod")}
    parts.append(tr("Synthèse %s") % tr(labels.get(sound.mode, sound.mode)))

    oscs = sound.osc_label(sound.osc1)
    if sound.display("oscBVolume") > 6:
        oscs += f" + {sound.osc_label(sound.osc2)}"
    parts.append(tr("oscillateurs %s") % oscs)

    cutoff = sound.display("lpfFrequency")
    resonance = sound.display("lpfResonance")
    if cutoff < 16:
        colour = tr("très sombre")
    elif cutoff < 28:
        colour = tr("sombre")
    elif cutoff < 40:
        colour = tr("équilibré")
    else:
        colour = tr("brillant")
    filtre = tr("filtre %s %s") % (sound.lpf_mode, colour)
    if resonance > 32:
        filtre += tr(", très résonant")
    elif resonance > 18:
        filtre += tr(", résonant")
    parts.append(filtre)

    from .fixedpoint import to_display

    a = to_display(sound.env1.attack)
    r = to_display(sound.env1.release)
    s = to_display(sound.env1.sustain)
    if a < 6:
        shape = tr("attaque immédiate")
    elif a < 18:
        shape = tr("attaque douce")
    else:
        shape = tr("attaque lente")
    if s < 8:
        shape += tr(", son percussif")
    elif r > 30:
        shape += tr(", longue extinction")
    parts.append(shape)

    if sound.unison_num > 2:
        parts.append(tr("%d voix désaccordées") % sound.unison_num)

    jeu = {"mono": tr("jeu monophonique"), "legato": tr("jeu legato")}.get(
        sound.polyphonic, "")
    if sound.display("portamento") > 0:
        glisse = tr("glissé d'une note à l'autre")
        jeu = "%s, %s" % (jeu, glisse) if jeu else glisse
    if jeu:
        parts.append(jeu)

    divisions = {5: N_("noires"), 6: N_("croches"), 7: N_("doubles-croches"),
                 8: N_("triples-croches")}
    fx = [tr("delay en %s") % tr(divisions[sound.delay_sync_level])
          if f == "delay" and sound.delay_sync_level in divisions else f
          for f in sound.fx_list()]
    if fx:
        parts.append(tr("effets : %s") % ", ".join(fx).lower())

    if sound.mode == "fm":
        ecart = sound.modulator1.transpose
        if ecart:
            parts.append(tr("modulateur à %+d demi-tons") % ecart)
        else:
            parts.append(tr("modulateur à l'unisson"))

    if sound.arp.is_on:
        sens = {"up": N_("montant"), "down": N_("descendant"),
                "upDown": N_("aller-retour"), "random": N_("aléatoire"),
                "asPlayed": N_("dans l'ordre joué")}
        mode = sound.arp.note_mode or "up"
        texte = tr("arpégiateur %s") % tr(sens.get(mode, mode))
        division = divisions.get(sound.arp.sync_level, "")
        if division:
            texte += tr(" en %s") % tr(division)
        parts.append(texte)

    if sound.patch_cables:
        parts.append(tr("%d modulation(s)") % len(sound.patch_cables))

    return ". ".join(parts) + "."
