# -*- coding: utf-8 -*-
"""Profils sonores par genre musical.

Chaque genre décrit **des intervalles**, pas des valeurs : c'est
:mod:`delugeapp.core.synthgen` qui tire au sort dedans. Un profil répond à la
question « à quoi ressemble une basse de techno, par opposition à une basse de
drum and bass », en termes de formes d'onde, de filtre, d'enveloppes et
d'effets.

Les valeurs d'enveloppe, de coupure et d'effets sont exprimées dans
**l'échelle de l'écran du Deluge, de 0 à 50** (cf. SPEC §1.4), parce que c'est
celle que l'utilisateur lit sur la machine. La conversion en virgule fixe est
faite au dernier moment par ``synthgen``.

Un profil peut surcharger ses réglages par **rôle** (basse, lead, nappe…) :
une nappe d'ambient et une basse d'ambient ne partagent que l'esthétique
générale, pas les enveloppes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..i18n import N_, tr

log = logging.getLogger(__name__)

#: Rôles qu'un preset peut tenir dans un morceau.
ROLES: tuple[str, ...] = ("bass", "lead", "pad", "pluck", "keys", "stab",
                          "fx", "drone", "arp", "bell")

#: Libellés des rôles, pour l'interface — traduits par :func:`role_label`.
ROLE_LABELS = {
    "bass": N_("Basse"), "lead": N_("Lead"), "pad": N_("Nappe"),
    "pluck": N_("Pincé"), "keys": N_("Clavier"), "stab": N_("Accord bref"),
    "fx": N_("Effet"), "drone": N_("Bourdon"), "arp": N_("Arpège"),
    "bell": N_("Cloche"),
}

#: Couleurs reprises de ``PAD_CYCLE`` (cf. SPEC §2), citées en clair pour que
#: le noyau n'importe pas l'interface.
_RED, _ORANGE, _AMBER, _YELLOW = "#F2453D", "#FF8C1A", "#FFC400", "#F5E13C"
_GREEN, _MINT, _CYAN, _BLUE = "#3DD160", "#2FD3A6", "#28C4E0", "#3E86F5"
_INDIGO, _PURPLE, _MAGENTA, _PINK = "#6B5CE7", "#A85BE0", "#F04FA8", "#FF7BB0"


@dataclass
class GenreProfile:
    """Esthétique sonore d'un genre, décrite en intervalles.

    Les champs ``env1``/``env2`` et ``fx`` sont des dictionnaires
    ``{nom: (minimum, maximum)}`` en unités d'affichage 0 à 50.
    """

    key: str
    label: str
    color: str
    bpm: tuple[int, int]
    description: str
    osc_types: list[tuple[str, float]] = field(default_factory=list)
    filter_mode: list[tuple[str, float]] = field(default_factory=list)
    cutoff: tuple[int, int] = (20, 45)
    resonance: tuple[int, int] = (0, 20)
    env1: dict[str, tuple[int, int]] = field(default_factory=dict)
    env2: dict[str, tuple[int, int]] = field(default_factory=dict)
    unison: tuple[int, int] = (1, 2)
    detune: tuple[int, int] = (0, 12)
    lfo_rate: tuple[int, int] = (10, 30)
    lfo_types: list[str] = field(default_factory=lambda: ["triangle"])
    fx: dict[str, tuple[int, int]] = field(default_factory=dict)
    cable_recipes: list[list[tuple[str, str, tuple[int, int]]]] = field(
        default_factory=list)
    arp_probability: float = 0.1
    #: Moteurs de synthèse et leur poids ; vide = le choix par défaut du rôle.
    modes: list[tuple[str, float]] = field(default_factory=list)
    #: Probabilité de synchroniser le LFO 1 au tempo, et niveaux possibles
    #: (``syncLevel`` du fichier : 5 = noire, 6 = croche, 7 = double-croche).
    #: C'est ce qui fait un « wobble » de dubstep : un LFO libre balaye le
    #: filtre sans jamais tomber en mesure.
    lfo_sync: tuple[float, tuple[int, ...]] = (0.12, (5, 6, 7))
    #: Multiplie la chance d'un portamento : la 303 de l'acid glisse d'une
    #: note à l'autre, une basse house ou psytrance presque jamais.
    glide: float = 1.0
    roles: dict[str, dict] = field(default_factory=dict)

    def for_role(self, role: str) -> "GenreProfile":
        """Profil ajusté pour un rôle donné.

        Retourne une copie dont les champs surchargés par ``roles[role]``
        remplacent ceux du genre. Un rôle inconnu rend le profil inchangé.
        """
        import copy

        overrides = self.roles.get(role)
        if not overrides:
            return self
        clone = copy.deepcopy(self)
        for name, value in overrides.items():
            if not hasattr(clone, name):
                log.debug("surcharge de rôle inconnue : %s.%s", self.key, name)
                continue
            current = getattr(clone, name)
            # Les dictionnaires sont fusionnés clé par clé, pas remplacés :
            # un rôle peut ne redéfinir que l'attaque sans perdre le reste.
            if isinstance(current, dict) and isinstance(value, dict):
                merged = dict(current)
                merged.update(value)
                setattr(clone, name, merged)
            else:
                setattr(clone, name, value)
        return clone


# --------------------------------------------------------------------------- #
# Briques communes
# --------------------------------------------------------------------------- #

#: Enveloppe percussive : attaque immédiate, extinction rapide.
_ENV_PERC = {"attack": (0, 2), "decay": (8, 20), "sustain": (0, 6),
             "release": (4, 14)}
#: Enveloppe tenue : le son reste tant que la touche est enfoncée.
_ENV_SUSTAIN = {"attack": (0, 6), "decay": (20, 35), "sustain": (35, 50),
                "release": (14, 28)}
#: Enveloppe lente : nappes et bourdons.
_ENV_SLOW = {"attack": (18, 36), "decay": (25, 40), "sustain": (38, 50),
             "release": (30, 48)}
#: Enveloppe de modulation discrète, pour ouvrir le filtre à l'attaque.
_ENV_MOD_SNAP = {"attack": (0, 3), "decay": (6, 18), "sustain": (0, 8),
                 "release": (6, 16)}

#: Jeu de modulations classique : enveloppe 2 vers la coupure du filtre.
_CABLE_ENV_TO_LPF = [("envelope2", "lpfFrequency", (12, 34))]
#: Vibrato léger.
_CABLE_LFO_TO_PITCH = [("lfo1", "pitch", (4, 12))]
#: Balayage de filtre par LFO.
_CABLE_LFO_TO_LPF = [("lfo1", "lpfFrequency", (10, 28))]
#: Sensibilité à la vélocité, qui rend un preset jouable au clavier : à
#: pleine échelle ou presque, comme dans 778 presets de la carte sur 911.
_CABLE_VELOCITY = [("velocity", "volume", (30, 50))]


def _role(**kwargs) -> dict:
    """Raccourci de lisibilité pour les surcharges de rôle."""
    return dict(kwargs)


#: Surcharges de rôle communes à la plupart des genres.
#:
#: **Recalées sur les 911 presets de la carte**, classés par catégorie : les
#: plages visent l'écart interquartile des vrais presets de chaque rôle. Avant
#: ce recalage, 56 % seulement des paramètres générés tombaient dans cette
#: zone ; les écarts étaient tous dans le même sens — trop de résonance, trop
#: d'unisson, du délai partout et de la réverbération sur les basses, des
#: basses sans tenue. Les genres gardent leurs signatures par leurs propres
#: surcharges (résonance de l'acid, largeur de la trance, espace de
#: l'ambient…).
_COMMON_ROLES: dict[str, dict] = {
    # Réel : sustain médian 35, réverbération médiane 0, délai 5.
    "bass": _role(env1={"attack": (0, 3), "decay": (8, 22),
                        "sustain": (12, 42), "release": (3, 16)},
                  cutoff=(12, 30), unison=(1, 2), detune=(2, 8),
                  fx={"reverbAmount": (0, 6), "delayFeedback": (0, 8)},
                  arp_probability=0.03),
    # Réel : release médiane 32, sustain 50.
    "lead": _role(env1={"attack": (0, 8), "decay": (12, 28),
                        "sustain": (28, 50), "release": (18, 38)},
                  cutoff=(28, 48), unison=(1, 3), detune=(3, 10)),
    "pad": _role(env1={"attack": (12, 36), "decay": (18, 22),
                       "sustain": (36, 50), "release": (22, 42)},
                 cutoff=(22, 42), resonance=(0, 8), unison=(1, 4),
                 detune=(4, 10), arp_probability=0.0),
    # Réel : release médiane 14 — un pincé laisse traîner sa queue.
    "pluck": _role(env1={"attack": (0, 1), "decay": (5, 16),
                         "sustain": (0, 10), "release": (8, 20)},
                   cutoff=(26, 46), unison=(1, 2), detune=(3, 9),
                   modes=[("subtractive", 6.0), ("fm", 2.0)]),
    "keys": _role(env1={"attack": (0, 4), "decay": (10, 26),
                        "sustain": (12, 44), "release": (6, 22)},
                  cutoff=(26, 44), resonance=(0, 10), unison=(1, 2),
                  detune=(3, 9),
                  modes=[("subtractive", 6.0), ("fm", 2.5),
                         ("ringmod", 0.6)]),
    "stab": _role(env1={"attack": (0, 2), "decay": (4, 12),
                        "sustain": (0, 6), "release": (4, 14)},
                  cutoff=(24, 44), unison=(1, 3), detune=(4, 12)),
    # Réel : un bourdon tient tout (sustain 50) sur une seule voix.
    "drone": _role(env1={"attack": (22, 40), "decay": (18, 24),
                         "sustain": (50, 50), "release": (32, 46)},
                   cutoff=(16, 36), resonance=(0, 8), unison=(1, 1),
                   detune=(4, 10), fx={"delayFeedback": (10, 22)},
                   arp_probability=0.0),
    "arp": _role(env1={"attack": (0, 4), "decay": (6, 18),
                       "sustain": (6, 30), "release": (6, 18)},
                 unison=(1, 2), detune=(3, 8), arp_probability=0.95),
    # Une cloche est FM par nature : un rapport inharmonique entre porteuse
    # et modulateur fait le timbre métallique.
    "bell": _role(env1={"attack": (0, 1), "decay": (20, 38),
                        "sustain": (0, 6), "release": (24, 44)},
                  cutoff=(34, 50), resonance=(0, 6), unison=(1, 1),
                  detune=(0, 4),
                  modes=[("fm", 6.0), ("subtractive", 2.0),
                         ("ringmod", 1.0)]),
    # Réel : la moitié des effets de la carte sont en ring mod, filtre
    # ouvert et peu résonant.
    "fx": _role(env1={"attack": (0, 24), "decay": (12, 24),
                      "sustain": (10, 50), "release": (16, 40)},
                cutoff=(22, 46), resonance=(0, 16), unison=(1, 2),
                detune=(2, 10), arp_probability=0.0,
                modes=[("subtractive", 3.0), ("ringmod", 3.0),
                       ("fm", 1.5)]),
}

#: Basse percussive : la note claque puis s'efface. C'est la signature des
#: genres de séquenceur (acid, techno, electro), pas celle de toutes les
#: basses — la plupart des vraies basses de la carte tiennent la note.
_BASS_PERC = {"attack": (0, 2), "decay": (8, 20), "sustain": (0, 8),
              "release": (4, 14)}


def _with_common_roles(extra: dict[str, dict] | None = None) -> dict[str, dict]:
    """Fusionne les surcharges communes avec celles propres au genre."""
    import copy

    out = copy.deepcopy(_COMMON_ROLES)
    for role, override in (extra or {}).items():
        base = out.setdefault(role, {})
        for name, value in override.items():
            if isinstance(value, dict) and isinstance(base.get(name), dict):
                merged = dict(base[name])
                merged.update(value)
                base[name] = merged
            else:
                base[name] = value
    return out


# --------------------------------------------------------------------------- #
# Les genres
# --------------------------------------------------------------------------- #

GENRES: dict[str, GenreProfile] = {}


def _add(profile: GenreProfile) -> None:
    GENRES[profile.key] = profile


_add(GenreProfile(
    key="acid", label="Acid", color=_YELLOW, bpm=(125, 140),
    description=N_("La 303 et rien d'autre : une dent de scie, un filtre très "
                   "résonant et une enveloppe qui claque."),
    osc_types=[("saw", 3.0), ("square", 2.0), ("analogSaw", 1.5)],
    filter_mode=[("24dB", 3.0), ("24dBDrive", 2.0)],
    cutoff=(10, 32), resonance=(24, 44),
    env1=_ENV_PERC, env2=_ENV_MOD_SNAP,
    unison=(1, 1), detune=(0, 4),
    lfo_rate=(14, 34), lfo_types=["triangle", "square"],
    fx={"reverbAmount": (0, 10), "delayFeedback": (6, 18),
        "delayRate": (18, 34), "modFXDepth": (0, 8),
        "sampleRateReduction": (0, 6), "bitCrush": (0, 4)},
    cable_recipes=[
        [("envelope2", "lpfFrequency", (26, 44))],
        [("envelope2", "lpfFrequency", (20, 38)),
         ("velocity", "lpfFrequency", (8, 20))],
        [("envelope2", "lpfFrequency", (24, 40)),
         ("lfo1", "lpfFrequency", (6, 16))],
    ],
    arp_probability=0.12,
    glide=2.5,
    roles=_with_common_roles({
        "bass": _role(cutoff=(8, 26), resonance=(32, 50), env1=_BASS_PERC),
        "lead": _role(cutoff=(20, 40), resonance=(28, 46)),
        "arp": _role(resonance=(20, 40)),
    }),
))

_add(GenreProfile(
    key="techno", label="Techno", color=_CYAN, bpm=(128, 145),
    description=N_("Sons secs et métalliques, peu de réverbération, tout dans "
                   "l'attaque et la pression."),
    osc_types=[("saw", 3.0), ("square", 2.5), ("analogSquare", 1.5),
               ("sine", 0.8)],
    filter_mode=[("24dB", 3.0), ("12dB", 1.5), ("24dBDrive", 1.5)],
    cutoff=(16, 38), resonance=(2, 18),
    env1=_ENV_PERC, env2=_ENV_MOD_SNAP,
    unison=(1, 3), detune=(0, 10),
    lfo_rate=(8, 28), lfo_types=["triangle", "square", "sah"],
    fx={"reverbAmount": (2, 12), "delayFeedback": (4, 14),
        "delayRate": (14, 30), "modFXDepth": (0, 12),
        "sampleRateReduction": (0, 10), "bitCrush": (0, 8)},
    cable_recipes=[
        _CABLE_ENV_TO_LPF,
        [("envelope2", "lpfFrequency", (14, 30)), *_CABLE_VELOCITY],
        [("lfo1", "lpfFrequency", (8, 22))],
    ],
    arp_probability=0.08,
    lfo_sync=(0.3, (5, 6, 7)),
    roles=_with_common_roles({"bass": _role(cutoff=(10, 26),
                                            env1=_BASS_PERC)}),
))

_add(GenreProfile(
    key="detroit", label="Detroit", color=_INDIGO, bpm=(120, 132),
    description=N_("L'école de Detroit : accords chauds, cordes synthétiques et "
                   "une mélancolie tenue."),
    osc_types=[("saw", 3.0), ("square", 1.5), ("triangle", 1.2)],
    filter_mode=[("24dB", 2.0), ("12dB", 2.5)],
    cutoff=(24, 44), resonance=(0, 12),
    env1=_ENV_SUSTAIN, env2=_ENV_MOD_SNAP,
    unison=(2, 4), detune=(8, 22),
    lfo_rate=(6, 20), lfo_types=["triangle", "sine"],
    fx={"reverbAmount": (10, 24), "delayFeedback": (6, 18),
        "delayRate": (16, 32), "modFXDepth": (8, 24)},
    cable_recipes=[_CABLE_ENV_TO_LPF, _CABLE_LFO_TO_LPF, _CABLE_VELOCITY],
    arp_probability=0.1,
    roles=_with_common_roles({"pad": _role(unison=(2, 4),
                                           detune=(10, 22))}),
))

_add(GenreProfile(
    key="minimal", label="Minimal", color=_GREEN, bpm=(122, 132),
    description=N_("Peu de matière, beaucoup d'espace : des sons courts, "
                   "discrets, qui laissent respirer le rythme."),
    osc_types=[("sine", 2.5), ("triangle", 2.0), ("square", 1.5),
               ("saw", 1.0)],
    filter_mode=[("12dB", 3.0), ("24dB", 1.5)],
    cutoff=(20, 40), resonance=(0, 10),
    env1=_ENV_PERC, env2=_ENV_MOD_SNAP,
    unison=(1, 2), detune=(0, 8),
    lfo_rate=(6, 18), lfo_types=["triangle", "sine"],
    fx={"reverbAmount": (6, 18), "delayFeedback": (4, 16),
        "delayRate": (14, 30), "modFXDepth": (0, 10)},
    cable_recipes=[_CABLE_ENV_TO_LPF, _CABLE_VELOCITY],
    arp_probability=0.06,
    glide=0.6,
    roles=_with_common_roles({"bass": _role(env1=_BASS_PERC)}),
))

_add(GenreProfile(
    key="house", label="House", color=_ORANGE, bpm=(118, 128),
    description=N_("Rond et dansant : des accords pleins, un filtre souple et "
                   "un grain chaleureux."),
    osc_types=[("saw", 3.0), ("square", 2.0), ("triangle", 1.0)],
    filter_mode=[("12dB", 3.0), ("24dB", 2.0)],
    cutoff=(24, 44), resonance=(0, 12),
    env1=_ENV_SUSTAIN, env2=_ENV_MOD_SNAP,
    unison=(2, 4), detune=(6, 18),
    lfo_rate=(8, 22), lfo_types=["triangle", "sine"],
    fx={"reverbAmount": (8, 20), "delayFeedback": (6, 16),
        "delayRate": (16, 32), "modFXDepth": (6, 20)},
    cable_recipes=[_CABLE_ENV_TO_LPF, _CABLE_VELOCITY, _CABLE_LFO_TO_LPF],
    arp_probability=0.08,
    glide=0.6,
    roles=_with_common_roles({
        "stab": _role(env1={"attack": (0, 1), "decay": (5, 12),
                            "sustain": (0, 2), "release": (4, 10)}),
    }),
))

_add(GenreProfile(
    key="deep_house", label="Deep house", color=_MINT, bpm=(118, 126),
    description=N_("Feutré et profond : des accords doux, un filtre bas et "
                   "beaucoup de réverbération."),
    osc_types=[("saw", 2.5), ("triangle", 2.0), ("sine", 1.5)],
    filter_mode=[("12dB", 3.0), ("24dB", 1.5)],
    cutoff=(18, 36), resonance=(0, 8),
    env1=_ENV_SUSTAIN, env2=_ENV_MOD_SNAP,
    unison=(2, 5), detune=(10, 24),
    lfo_rate=(4, 16), lfo_types=["sine", "triangle"],
    fx={"reverbAmount": (14, 28), "delayFeedback": (8, 18),
        "delayRate": (18, 34), "modFXDepth": (10, 26)},
    cable_recipes=[_CABLE_ENV_TO_LPF, _CABLE_LFO_TO_LPF, _CABLE_VELOCITY],
    arp_probability=0.05,
    glide=0.6,
    roles=_with_common_roles(),
))

_add(GenreProfile(
    key="trance", label="Trance", color=_BLUE, bpm=(132, 142),
    description=N_("Large et montant : des nappes désaccordées, des arpèges "
                   "rapides et beaucoup d'espace."),
    osc_types=[("saw", 3.5), ("square", 1.5)],
    filter_mode=[("24dB", 3.0), ("12dB", 1.5)],
    cutoff=(26, 48), resonance=(0, 14),
    env1=_ENV_SUSTAIN, env2={"attack": (6, 24), "decay": (18, 36),
                             "sustain": (10, 30), "release": (18, 36)},
    unison=(3, 6), detune=(16, 34),
    lfo_rate=(10, 28), lfo_types=["triangle", "sine", "saw"],
    fx={"reverbAmount": (16, 32), "delayFeedback": (8, 20),
        "delayRate": (18, 34), "modFXDepth": (14, 32)},
    cable_recipes=[
        [("envelope2", "lpfFrequency", (18, 36))],
        [("envelope2", "lpfFrequency", (16, 32)), ("lfo1", "lpfFrequency", (8, 20))],
        [("lfo1", "lpfFrequency", (12, 28)), *_CABLE_VELOCITY],
    ],
    arp_probability=0.3,
    lfo_sync=(0.35, (6, 7)),
    roles=_with_common_roles({
        "arp": _role(arp_probability=1.0),
        # La nappe et le lead « supersaw » font la trance : beaucoup de
        # voix, franchement désaccordées.
        "pad": _role(unison=(3, 6), detune=(12, 26)),
        "lead": _role(unison=(3, 5), detune=(10, 22)),
    }),
))

_add(GenreProfile(
    key="psytrance", label="Psytrance", color=_PURPLE, bpm=(138, 150),
    description=N_("Basses roulantes et leads tordus, modulations rapides et "
                   "filtre très résonant."),
    osc_types=[("saw", 3.0), ("square", 2.5), ("analogSaw", 1.5)],
    filter_mode=[("24dB", 3.0), ("24dBDrive", 2.0), ("SVF_Band", 1.0)],
    cutoff=(14, 38), resonance=(12, 34),
    env1=_ENV_PERC, env2=_ENV_MOD_SNAP,
    unison=(1, 3), detune=(4, 16),
    lfo_rate=(20, 44), lfo_types=["square", "sah", "rwalk"],
    fx={"reverbAmount": (6, 18), "delayFeedback": (8, 20),
        "delayRate": (20, 38), "modFXDepth": (10, 30),
        "sampleRateReduction": (0, 12), "bitCrush": (0, 10)},
    cable_recipes=[
        [("envelope2", "lpfFrequency", (22, 42)), ("lfo1", "lpfFrequency", (10, 26))],
        [("lfo1", "lpfFrequency", (16, 34)), ("lfo2", "oscAPitch", (4, 12))],
        [("envelope2", "lpfFrequency", (20, 38)), ("lfo1", "oscAPulseWidth", (10, 26))],
    ],
    arp_probability=0.2,
    lfo_sync=(0.5, (7,)),
    glide=0.5,
    roles=_with_common_roles({"bass": _role(cutoff=(8, 24), resonance=(18, 36),
                                            env1=_BASS_PERC)}),
))

_add(GenreProfile(
    key="dnb", label="Drum and bass", color=_RED, bpm=(170, 178),
    description=N_("Basses lourdes et agressives, attaque immédiate, filtre qui "
                   "balaye."),
    osc_types=[("saw", 3.0), ("square", 2.0), ("sine", 1.5),
               ("analogSaw", 1.0)],
    filter_mode=[("24dB", 3.0), ("24dBDrive", 2.5)],
    cutoff=(10, 34), resonance=(6, 26),
    env1=_ENV_PERC, env2=_ENV_MOD_SNAP,
    unison=(1, 3), detune=(2, 14),
    lfo_rate=(12, 34), lfo_types=["triangle", "square", "sah"],
    fx={"reverbAmount": (4, 14), "delayFeedback": (4, 14),
        "delayRate": (16, 32), "modFXDepth": (4, 20),
        "sampleRateReduction": (0, 14), "bitCrush": (0, 12)},
    cable_recipes=[
        [("envelope2", "lpfFrequency", (24, 44))],
        [("lfo1", "lpfFrequency", (14, 32)), *_CABLE_VELOCITY],
        [("envelope2", "lpfFrequency", (20, 38)), ("lfo2", "lpfResonance", (8, 20))],
    ],
    arp_probability=0.05,
    roles=_with_common_roles({"bass": _role(cutoff=(6, 22), resonance=(16, 40))}),
))

_add(GenreProfile(
    key="jungle", label="Jungle", color=_GREEN, bpm=(160, 172),
    description=N_("Basses rondes à la jamaïcaine et nappes lointaines, sur un "
                   "grain d'échantillonneur."),
    osc_types=[("sine", 2.5), ("triangle", 2.0), ("saw", 2.0)],
    filter_mode=[("24dB", 2.5), ("12dB", 2.0)],
    cutoff=(10, 30), resonance=(0, 12),
    env1=_ENV_SUSTAIN, env2=_ENV_MOD_SNAP,
    unison=(1, 3), detune=(2, 12),
    lfo_rate=(6, 20), lfo_types=["sine", "triangle"],
    fx={"reverbAmount": (8, 22), "delayFeedback": (6, 18),
        "delayRate": (18, 34), "modFXDepth": (4, 18),
        "sampleRateReduction": (2, 16), "bitCrush": (2, 14)},
    cable_recipes=[_CABLE_ENV_TO_LPF, _CABLE_VELOCITY],
    arp_probability=0.04,
    roles=_with_common_roles({"bass": _role(cutoff=(6, 20))}),
))

_add(GenreProfile(
    key="dubstep", label="Dubstep", color=_MAGENTA, bpm=(138, 145),
    description=N_("Basses déformées et parlantes : beaucoup de modulation, de "
                   "résonance et de saleté."),
    osc_types=[("saw", 3.0), ("square", 2.5), ("analogSquare", 2.0)],
    filter_mode=[("24dBDrive", 3.0), ("24dB", 2.0), ("SVF_Band", 1.5)],
    cutoff=(8, 34), resonance=(14, 38),
    env1={"attack": (0, 4), "decay": (14, 30), "sustain": (20, 42),
          "release": (8, 22)},
    env2=_ENV_MOD_SNAP,
    unison=(1, 3), detune=(4, 18),
    lfo_rate=(16, 44), lfo_types=["square", "sah", "triangle"],
    fx={"reverbAmount": (4, 16), "delayFeedback": (4, 16),
        "delayRate": (18, 34), "modFXDepth": (16, 38),
        "sampleRateReduction": (4, 22), "bitCrush": (4, 20)},
    cable_recipes=[
        [("lfo1", "lpfFrequency", (22, 44)), ("envelope2", "lpfFrequency", (14, 30))],
        [("lfo1", "lpfFrequency", (18, 38)), ("lfo2", "lpfResonance", (10, 26))],
        [("lfo1", "oscAPulseWidth", (16, 34)), ("envelope2", "lpfFrequency", (18, 34))],
    ],
    arp_probability=0.04,
    # Le « wobble » : un LFO synchronisé au tempo qui balaye le filtre.
    lfo_sync=(0.8, (5, 6, 6, 7)),
    glide=1.4,
    roles=_with_common_roles({"bass": _role(resonance=(20, 42))}),
))

_add(GenreProfile(
    key="ambient", label="Ambient", color=_MINT, bpm=(60, 90),
    description=N_("Sans rythme et sans bords : attaques lentes, réverbération "
                   "immense, mouvement imperceptible."),
    osc_types=[("sine", 3.0), ("triangle", 2.5), ("saw", 1.2),
               ("wavetable", 1.0)],
    filter_mode=[("12dB", 3.0), ("24dB", 1.5)],
    cutoff=(18, 40), resonance=(0, 6),
    env1=_ENV_SLOW, env2={"attack": (20, 44), "decay": (28, 46),
                          "sustain": (30, 50), "release": (32, 50)},
    unison=(3, 6), detune=(14, 32),
    lfo_rate=(1, 10), lfo_types=["sine", "triangle", "rwalk"],
    fx={"reverbAmount": (22, 40), "delayFeedback": (12, 26),
        "delayRate": (20, 38), "modFXDepth": (14, 34)},
    cable_recipes=[
        _CABLE_LFO_TO_LPF,
        [("lfo1", "lpfFrequency", (8, 22)), ("lfo2", "pitch", (2, 8))],
        [("envelope2", "lpfFrequency", (10, 26)), ("lfo1", "oscAVolume", (6, 18))],
    ],
    arp_probability=0.02,
    roles=_with_common_roles({
        "pad": _role(detune=(10, 24), unison=(2, 5),
                     fx={"reverbAmount": (28, 46)}),
        "drone": _role(fx={"reverbAmount": (26, 44)}),
    }),
))

_add(GenreProfile(
    key="berlin_school", label="Berlin school", color=_AMBER, bpm=(90, 120),
    description=N_("Séquences hypnotiques à la Tangerine Dream : arpèges "
                   "synchronisés et filtre qui respire."),
    osc_types=[("saw", 3.0), ("square", 2.0), ("triangle", 1.5)],
    filter_mode=[("24dB", 3.0), ("12dB", 2.0)],
    cutoff=(18, 42), resonance=(6, 22),
    env1={"attack": (0, 6), "decay": (12, 28), "sustain": (6, 24),
          "release": (10, 26)},
    env2=_ENV_MOD_SNAP,
    unison=(1, 3), detune=(4, 16),
    lfo_rate=(4, 18), lfo_types=["triangle", "sine", "saw"],
    fx={"reverbAmount": (12, 28), "delayFeedback": (10, 24),
        "delayRate": (18, 34), "modFXDepth": (8, 24)},
    cable_recipes=[
        [("envelope2", "lpfFrequency", (16, 34))],
        [("lfo1", "lpfFrequency", (12, 28))],
        [("envelope2", "lpfFrequency", (14, 30)), ("lfo1", "pitch", (2, 8))],
    ],
    arp_probability=0.6,
    lfo_sync=(0.4, (6, 7)),
    roles=_with_common_roles({"arp": _role(arp_probability=1.0)}),
))

_add(GenreProfile(
    key="synthwave", label="Synthwave", color=_PINK, bpm=(100, 118),
    description=N_("Nostalgie des années 80 : nappes larges, basses rondes et "
                   "beaucoup de chorus."),
    osc_types=[("saw", 3.0), ("square", 2.0), ("triangle", 1.5)],
    filter_mode=[("12dB", 3.0), ("24dB", 2.0)],
    cutoff=(24, 46), resonance=(0, 12),
    env1=_ENV_SUSTAIN, env2=_ENV_MOD_SNAP,
    unison=(2, 5), detune=(14, 30),
    lfo_rate=(4, 16), lfo_types=["sine", "triangle"],
    fx={"reverbAmount": (16, 30), "delayFeedback": (8, 20),
        "delayRate": (18, 34), "modFXDepth": (20, 40)},
    cable_recipes=[_CABLE_ENV_TO_LPF, _CABLE_VELOCITY, _CABLE_LFO_TO_PITCH],
    arp_probability=0.15,
    glide=1.3,
    roles=_with_common_roles({
        "bass": _role(detune=(6, 16)),
        "pad": _role(unison=(2, 5), detune=(10, 24)),
        "lead": _role(unison=(2, 4), detune=(6, 18)),
    }),
))

_add(GenreProfile(
    key="lofi", label="Lo-fi", color=_ORANGE, bpm=(70, 95),
    description=N_("Doux et usé : bande passante réduite, grain numérique, "
                   "légers désaccords."),
    osc_types=[("triangle", 2.5), ("sine", 2.0), ("saw", 2.0),
               ("square", 1.0)],
    filter_mode=[("12dB", 3.0), ("24dB", 1.5)],
    cutoff=(14, 32), resonance=(0, 8),
    env1={"attack": (0, 8), "decay": (14, 30), "sustain": (14, 36),
          "release": (12, 28)},
    env2=_ENV_MOD_SNAP,
    unison=(1, 3), detune=(8, 24),
    lfo_rate=(3, 14), lfo_types=["sine", "triangle", "rwalk"],
    fx={"reverbAmount": (12, 26), "delayFeedback": (6, 18),
        "delayRate": (16, 32), "modFXDepth": (10, 28),
        "sampleRateReduction": (8, 26), "bitCrush": (6, 22)},
    cable_recipes=[_CABLE_ENV_TO_LPF, _CABLE_LFO_TO_PITCH, _CABLE_VELOCITY],
    arp_probability=0.06,
    roles=_with_common_roles(),
))

_add(GenreProfile(
    key="idm", label="IDM", color=_CYAN, bpm=(90, 160),
    description=N_("Timbres instables et imprévisibles : modulations croisées, "
                   "formes d'onde inhabituelles."),
    osc_types=[("wavetable", 2.5), ("square", 2.0), ("saw", 2.0),
               ("triangle", 1.5), ("sine", 1.0)],
    filter_mode=[("SVF_Band", 2.0), ("24dB", 2.0), ("12dB", 2.0),
                 ("SVF_Notch", 1.0)],
    cutoff=(12, 46), resonance=(4, 26),
    env1={"attack": (0, 12), "decay": (8, 30), "sustain": (0, 30),
          "release": (6, 30)},
    env2={"attack": (0, 16), "decay": (6, 28), "sustain": (0, 24),
          "release": (6, 26)},
    unison=(1, 4), detune=(4, 26),
    lfo_rate=(10, 46), lfo_types=["sah", "rwalk", "square",
                                  "triangle"],
    fx={"reverbAmount": (8, 24), "delayFeedback": (8, 22),
        "delayRate": (14, 36), "modFXDepth": (12, 34),
        "sampleRateReduction": (4, 24), "bitCrush": (4, 22)},
    cable_recipes=[
        [("lfo1", "lpfFrequency", (14, 34)), ("lfo2", "oscAPitch", (4, 14))],
        [("envelope2", "oscAWavetablePosition", (16, 38)),
         ("lfo1", "lpfFrequency", (10, 26))],
        [("random", "lpfFrequency", (10, 28)), ("lfo1", "oscAVolume", (8, 22))],
    ],
    modes=[("subtractive", 4.0), ("fm", 2.5), ("ringmod", 1.5)],
    arp_probability=0.18,
    roles=_with_common_roles(),
))

_add(GenreProfile(
    key="industrial", label="Industrial", color=_RED, bpm=(120, 150),
    description=N_("Métallique et abrasif : bruit, distorsion et résonances "
                   "dures."),
    osc_types=[("square", 3.0), ("saw", 2.5), ("analogSquare", 2.0)],
    filter_mode=[("24dBDrive", 3.0), ("24dB", 2.0), ("SVF_Band", 1.5)],
    cutoff=(12, 38), resonance=(12, 36),
    env1=_ENV_PERC, env2=_ENV_MOD_SNAP,
    unison=(1, 3), detune=(2, 14),
    lfo_rate=(14, 42), lfo_types=["square", "sah"],
    fx={"reverbAmount": (8, 22), "delayFeedback": (6, 20),
        "delayRate": (14, 30), "modFXDepth": (10, 30),
        "sampleRateReduction": (10, 30), "bitCrush": (10, 28)},
    cable_recipes=[
        [("envelope2", "lpfFrequency", (20, 40)), ("lfo1", "lpfResonance", (10, 26))],
        [("lfo1", "lpfFrequency", (18, 38))],
        [("envelope2", "lpfFrequency", (18, 34)), ("lfo2", "bitCrush", (8, 24))],
    ],
    modes=[("subtractive", 5.0), ("ringmod", 2.0), ("fm", 1.5)],
    arp_probability=0.06,
    roles=_with_common_roles(),
))

_add(GenreProfile(
    key="electro", label="Electro", color=_BLUE, bpm=(124, 136),
    description=N_("Basses carrées et leads tranchants, dans l'esprit des "
                   "boîtes à rythmes de Miami."),
    osc_types=[("square", 3.0), ("saw", 2.5), ("analogSquare", 1.5)],
    filter_mode=[("24dB", 3.0), ("12dB", 2.0)],
    cutoff=(18, 40), resonance=(6, 22),
    env1=_ENV_PERC, env2=_ENV_MOD_SNAP,
    unison=(1, 3), detune=(2, 14),
    lfo_rate=(10, 30), lfo_types=["triangle", "square"],
    fx={"reverbAmount": (4, 16), "delayFeedback": (6, 18),
        "delayRate": (16, 32), "modFXDepth": (6, 22),
        "bitCrush": (2, 14)},
    cable_recipes=[_CABLE_ENV_TO_LPF, _CABLE_VELOCITY, _CABLE_LFO_TO_LPF],
    arp_probability=0.12,
    roles=_with_common_roles({"bass": _role(env1=_BASS_PERC)}),
))

_add(GenreProfile(
    key="hardcore", label="Hardcore", color=_MAGENTA, bpm=(160, 200),
    description=N_("Rapide et saturé : attaque brutale, distorsion franche, "
                   "aucune subtilité."),
    osc_types=[("saw", 3.0), ("square", 3.0), ("analogSaw", 2.0)],
    filter_mode=[("24dBDrive", 3.0), ("24dB", 2.0)],
    cutoff=(20, 46), resonance=(8, 28),
    env1={"attack": (0, 1), "decay": (6, 18), "sustain": (10, 32),
          "release": (4, 14)},
    env2=_ENV_MOD_SNAP,
    unison=(2, 4), detune=(8, 24),
    lfo_rate=(16, 44), lfo_types=["square", "saw", "sah"],
    fx={"reverbAmount": (4, 16), "delayFeedback": (4, 14),
        "delayRate": (14, 30), "modFXDepth": (8, 26),
        "sampleRateReduction": (6, 24), "bitCrush": (8, 26)},
    cable_recipes=[
        [("envelope2", "lpfFrequency", (18, 36))],
        [("lfo1", "lpfFrequency", (16, 34)), *_CABLE_VELOCITY],
    ],
    arp_probability=0.08,
    roles=_with_common_roles(),
))

_add(GenreProfile(
    key="downtempo", label="Downtempo", color=_AMBER, bpm=(80, 110),
    description=N_("Posé et chaleureux : enveloppes souples, grain analogique, "
                   "beaucoup d'espace."),
    osc_types=[("triangle", 2.5), ("saw", 2.5), ("sine", 2.0)],
    filter_mode=[("12dB", 3.0), ("24dB", 1.5)],
    cutoff=(18, 38), resonance=(0, 10),
    env1=_ENV_SUSTAIN, env2=_ENV_MOD_SNAP,
    unison=(2, 4), detune=(8, 22),
    lfo_rate=(3, 14), lfo_types=["sine", "triangle"],
    fx={"reverbAmount": (14, 28), "delayFeedback": (8, 20),
        "delayRate": (18, 34), "modFXDepth": (10, 28)},
    cable_recipes=[_CABLE_ENV_TO_LPF, _CABLE_LFO_TO_LPF, _CABLE_VELOCITY],
    arp_probability=0.06,
    roles=_with_common_roles(),
))

_add(GenreProfile(
    key="funk", label="Funk", color=_YELLOW, bpm=(100, 120),
    description=N_("Nerveux et rebondissant : basses pincées, filtre sensible à "
                   "la vélocité, enveloppes courtes."),
    osc_types=[("saw", 3.0), ("square", 2.5), ("triangle", 1.0)],
    filter_mode=[("24dB", 2.5), ("12dB", 2.5)],
    cutoff=(20, 44), resonance=(6, 22),
    env1={"attack": (0, 2), "decay": (8, 20), "sustain": (4, 20),
          "release": (6, 16)},
    env2=_ENV_MOD_SNAP,
    unison=(1, 3), detune=(2, 12),
    lfo_rate=(8, 26), lfo_types=["triangle", "sine"],
    fx={"reverbAmount": (6, 18), "delayFeedback": (4, 14),
        "delayRate": (14, 30), "modFXDepth": (10, 28)},
    cable_recipes=[
        [("envelope2", "lpfFrequency", (18, 36)), ("velocity", "lpfFrequency", (14, 30))],
        [("velocity", "lpfFrequency", (16, 34)), *_CABLE_VELOCITY],
    ],
    arp_probability=0.08,
    glide=1.3,
    roles=_with_common_roles({"bass": _role(env1=_BASS_PERC)}),
))

_add(GenreProfile(
    key="boards_of_canada", label="Boards of Canada", color=_PURPLE,
    bpm=(70, 100),
    description=N_("Mélancolie de bande magnétique : désaccords doux, filtre "
                   "feutré, mouvement lent et irrégulier."),
    osc_types=[("triangle", 2.5), ("sine", 2.0), ("saw", 2.0),
               ("wavetable", 1.0)],
    filter_mode=[("12dB", 3.0), ("24dB", 1.5)],
    cutoff=(14, 34), resonance=(0, 8),
    env1={"attack": (2, 14), "decay": (16, 34), "sustain": (18, 40),
          "release": (16, 36)},
    env2={"attack": (8, 28), "decay": (18, 36), "sustain": (10, 34),
          "release": (18, 38)},
    unison=(2, 5), detune=(16, 34),
    lfo_rate=(1, 10), lfo_types=["sine", "triangle", "rwalk"],
    fx={"reverbAmount": (16, 32), "delayFeedback": (8, 22),
        "delayRate": (18, 36), "modFXDepth": (16, 34),
        "sampleRateReduction": (4, 18), "bitCrush": (2, 14)},
    cable_recipes=[
        [("lfo1", "pitch", (4, 12)), ("envelope2", "lpfFrequency", (10, 26))],
        [("lfo1", "lpfFrequency", (8, 22)), ("lfo2", "pitch", (2, 10))],
        [("envelope2", "lpfFrequency", (12, 28)), ("lfo1", "oscAVolume", (6, 16))],
    ],
    arp_probability=0.05,
    roles=_with_common_roles({"pad": _role(unison=(2, 4),
                                           detune=(12, 26))}),
))


# --------------------------------------------------------------------------- #
# Accès
# --------------------------------------------------------------------------- #

#: Genre utilisé lorsqu'une clé inconnue est demandée.
FALLBACK_GENRE = "techno"


def genre_keys() -> list[str]:
    """Clés de tous les genres, dans l'ordre alphabétique de leur libellé."""
    return sorted(GENRES, key=lambda k: GENRES[k].label.lower())


def genre(key: str) -> GenreProfile:
    """Profil d'un genre. Une clé inconnue retombe sur la techno."""
    profile = GENRES.get(str(key or "").strip().lower())
    if profile is None:
        log.debug("genre inconnu : %r, repli sur %s", key, FALLBACK_GENRE)
        return GENRES[FALLBACK_GENRE]
    return profile


def genres_for_bpm(bpm: float) -> list[str]:
    """Genres dont la plage de tempo contient ``bpm``.

    Sert à proposer un genre cohérent avec le morceau en cours d'écriture.
    """
    try:
        value = float(bpm)
    except (TypeError, ValueError):
        return []
    return [k for k, p in GENRES.items() if p.bpm[0] <= value <= p.bpm[1]]


def role_label(role: str) -> str:
    """Libellé d'un rôle, dans la langue de l'interface."""
    return tr(ROLE_LABELS.get(role, role))
