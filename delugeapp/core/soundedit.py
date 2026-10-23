# -*- coding: utf-8 -*-
"""Modifier un son à la main, réglage par réglage.

Le générateur et l'atelier proposent des sons ; le compositeur veut pouvoir
les reprendre avant d'en faire un morceau : ouvrir le filtre, allonger un
release, retirer un vibrato. Ce module décrit **chaque réglage modifiable**
d'un son du Deluge — sa place dans les menus de la machine, ses bornes, son
cran — et sait le lire et l'écrire dans un :class:`~delugeapp.core.model.Sound`.

Chaque valeur est donnée **au cran de la machine** (0 à 50, ou −25 à +25)
et dans sa **grandeur réelle**, calculée par les lois du firmware
(:mod:`.paramlaws`) : « decay 13 » se lit « 1,8 s », « coupure 19 » se lit
« 237 Hz » — ce que le Deluge en fera.

Les bornes sont celles des menus du firmware (1.3, ``gui/menu_item``) :
saturation 0 à 15, unisson 1 à 8 voix, désaccord et étalement 0 à 50.
Passer en FM éteint les filtres, comme le fait la machine
(``Sound::setSynthMode``) ; en revenir les rallume.

Module sans Qt.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass

from ..i18n import N_, decimal, tr, untranslated
from . import paramlaws as laws
from .fixedpoint import from_display, to_display
from .model import PARAM_BIPOLAR, PatchCable, Sound, param_of_destination

__all__ = ["Control", "SECTIONS", "CONTROLS", "control", "controls_of",
           "value", "set_value", "describe", "visible", "CABLE_SOURCES",
           "CABLE_DESTINATIONS", "describe_cable", "add_cable",
           "set_cable", "remove_cable", "copy_sound", "differences",
           "carry_edits"]


@dataclass(frozen=True)
class Control:
    """Un réglage modifiable."""

    key: str
    label: str
    section: str
    kind: str = "knob"              # « knob » ou « choice »
    minimum: int = 0
    maximum: int = 50
    bipolar: bool = False
    choices: tuple = ()             # ((valeur, libellé N_), …)
    tip: str = ""


#: Les onglets de l'éditeur, dans l'ordre des menus de la machine.
SECTIONS = (N_("Voix"), N_("Oscillateurs"), N_("Filtres"), N_("Enveloppes"),
            N_("LFO"), N_("Effets"))

_WAVES = (("saw", N_("Dent de scie")), ("square", N_("Carré")),
          ("sine", N_("Sinus")), ("triangle", N_("Triangle")),
          ("analogSaw", N_("Dent de scie analogique")),
          ("analogSquare", N_("Carré analogique")))
_LFO_WAVES = (("sine", N_("Sinus")), ("triangle", N_("Triangle")),
              ("square", N_("Carré")), ("saw", N_("Dent de scie")),
              ("sah", N_("Échantillonné-bloqué")),
              ("rwalk", N_("Marche aléatoire")), ("warbler", "Warbler"))
#: Calage sur le tempo : 0 libre, puis ``2^(3 − niveau)`` mesures.
_SYNC = ((0, N_("Libre")), (1, N_("4 mesures")), (2, N_("2 mesures")),
         (3, N_("1 mesure")), (4, "1/2"), (5, "1/4"), (6, "1/8"),
         (7, "1/16"), (8, "1/32"), (9, "1/64"))

V, O, F, E, L, X = SECTIONS

CONTROLS: tuple[Control, ...] = (
    # -- voix --------------------------------------------------------------- #
    Control("mode", N_("Moteur"), V, "choice", choices=(
        ("subtractive", N_("Soustractive")), ("fm", "FM"),
        ("ringmod", N_("Ring mod"))),
        tip=N_("Le moteur de synthèse. Passer en FM éteint les filtres, "
               "comme sur la machine.")),
    Control("polyphonic", N_("Jeu"), V, "choice", choices=(
        ("poly", N_("Polyphonique")), ("mono", "Mono"),
        ("legato", "Legato"), ("auto", "Auto"), ("choke", N_("Étouffé"))),
        tip=N_("Mono : une note à la fois. Legato : une note à la fois, sans "
               "relancer les enveloppes ni glisser.")),
    Control("transpose", N_("Transposition"), V, minimum=-24, maximum=24,
            bipolar=True, tip=N_("Tout le son, en demi-tons.")),
    Control("portamento", N_("Glissé"), V,
            tip=N_("Le temps que met la hauteur pour aller d'une note à la "
                   "suivante ; 0 le coupe. Sans effet en legato.")),
    Control("volume", N_("Volume"), V,
            tip=N_("Le niveau du son. Loi quadratique : 25 sonne 12 dB sous "
                   "50.")),
    Control("pan", N_("Panoramique"), V, minimum=-25, maximum=25,
            bipolar=True, tip=N_("Gauche ou droite ; 0 au centre.")),
    Control("unison.num", N_("Unisson"), V, minimum=1, maximum=8,
            tip=N_("Le nombre de voix jouées ensemble à chaque note.")),
    Control("unison.detune", N_("Désaccord"), V,
            tip=N_("L'écart entre les voix d'unisson, réparti de −réglage/2 "
                   "à +réglage/2 cents.")),
    Control("unison.spread", N_("Étalement"), V,
            tip=N_("Les voix d'unisson réparties dans l'espace stéréo.")),
    # -- oscillateurs ----------------------------------------------------- #
    Control("osc1.type", N_("Forme A"), O, "choice", choices=_WAVES,
            tip=N_("La forme d'onde de l'oscillateur A.")),
    Control("osc1.transpose", N_("Transposition A"), O, minimum=-36,
            maximum=36, bipolar=True, tip=N_("En demi-tons.")),
    Control("osc1.cents", N_("Accord fin A"), O, minimum=-50, maximum=50,
            bipolar=True, tip=N_("En cents (centièmes de demi-ton).")),
    Control("oscAVolume", N_("Niveau A"), O,
            tip=N_("Le niveau de l'oscillateur A, loi quadratique.")),
    Control("oscAPulseWidth", N_("Largeur A"), O,
            tip=N_("La largeur d'impulsion, pour les formes carrées : 25 "
                   "donne un carré, les extrêmes une impulsion fine.")),
    Control("osc2.type", N_("Forme B"), O, "choice", choices=_WAVES,
            tip=N_("La forme d'onde de l'oscillateur B.")),
    Control("osc2.transpose", N_("Transposition B"), O, minimum=-36,
            maximum=36, bipolar=True, tip=N_("En demi-tons.")),
    Control("osc2.cents", N_("Accord fin B"), O, minimum=-50, maximum=50,
            bipolar=True, tip=N_("En cents (centièmes de demi-ton).")),
    Control("oscBVolume", N_("Niveau B"), O,
            tip=N_("Le niveau de l'oscillateur B, loi quadratique.")),
    Control("oscBPulseWidth", N_("Largeur B"), O,
            tip=N_("La largeur d'impulsion de l'oscillateur B.")),
    Control("noiseVolume", N_("Bruit"), O,
            tip=N_("Le niveau du bruit blanc mêlé aux oscillateurs.")),
    Control("modulator1Amount", N_("Modulateur 1"), O,
            tip=N_("FM : la profondeur du premier modulateur.")),
    Control("modulator1.transpose", N_("Accord modulateur 1"), O,
            minimum=-36, maximum=36, bipolar=True,
            tip=N_("FM : l'accord du premier modulateur, en demi-tons — "
                   "c'est lui qui fait le timbre.")),
    Control("modulator2Amount", N_("Modulateur 2"), O,
            tip=N_("FM : la profondeur du second modulateur.")),
    Control("modulator2.transpose", N_("Accord modulateur 2"), O,
            minimum=-36, maximum=36, bipolar=True,
            tip=N_("FM : l'accord du second modulateur, en demi-tons.")),
    # -- filtres ------------------------------------------------------------ #
    Control("lpf_mode", N_("Passe-bas"), F, "choice", choices=(
        ("24dB", "24 dB"), ("12dB", "12 dB"),
        ("24dBDrive", N_("24 dB saturé")), ("SVF_Band", N_("SVF passe-bande")),
        ("SVF_Notch", N_("SVF coupe-bande")), ("Off", N_("Éteint"))),
        tip=N_("Le type de filtre passe-bas.")),
    Control("lpfFrequency", N_("Coupure"), F,
            tip=N_("La fréquence de coupure du passe-bas.")),
    Control("lpfResonance", N_("Résonance"), F,
            tip=N_("L'accentuation autour de la coupure.")),
    Control("hpf_mode", N_("Passe-haut"), F, "choice", choices=(
        ("HPLadder", N_("Échelle")), ("SVF_Band", N_("SVF passe-bande")),
        ("SVF_Notch", N_("SVF coupe-bande")), ("Off", N_("Éteint"))),
        tip=N_("Le type de filtre passe-haut.")),
    Control("hpfFrequency", N_("Coupure passe-haut"), F,
            tip=N_("La fréquence de coupure du passe-haut ; 0 le laisse "
                   "tout passer.")),
    Control("hpfResonance", N_("Résonance passe-haut"), F,
            tip=N_("L'accentuation autour de la coupure du passe-haut.")),
    # -- enveloppes ------------------------------------------------------- #
    *(Control("env%d.%s" % (i, seg), label, E, tip=tip)
      for i in (1, 2)
      for seg, label, tip in (
          ("attack", N_("Attaque %d"), N_("Le temps de montée.")),
          ("decay", N_("Decay %d"), N_("Le temps de descente vers le "
                                       "palier.")),
          ("sustain", N_("Palier %d"), N_("Le niveau tenu tant que la "
                                          "touche l'est.")),
          ("release", N_("Release %d"), N_("Le temps d'extinction, une fois "
                                           "la touche relâchée.")))),
    # -- LFO ---------------------------------------------------------------- #
    Control("lfo1.type", N_("Forme LFO 1"), L, "choice", choices=_LFO_WAVES,
            tip=N_("La forme du LFO 1, commun à toutes les notes.")),
    Control("lfo1.sync", N_("Calage LFO 1"), L, "choice", choices=_SYNC,
            tip=N_("Libre, ou calé sur le tempo du morceau.")),
    Control("lfo1Rate", N_("Vitesse LFO 1"), L,
            tip=N_("La vitesse du LFO 1 quand il est libre.")),
    Control("lfo2.type", N_("Forme LFO 2"), L, "choice", choices=_LFO_WAVES,
            tip=N_("La forme du LFO 2, relancé à chaque note.")),
    Control("lfo2.sync", N_("Calage LFO 2"), L, "choice", choices=_SYNC,
            tip=N_("Libre, ou calé sur le tempo du morceau.")),
    Control("lfo2Rate", N_("Vitesse LFO 2"), L,
            tip=N_("La vitesse du LFO 2 quand il est libre.")),
    # -- effets ------------------------------------------------------------- #
    Control("reverbAmount", N_("Réverbération"), X,
            tip=N_("L'envoi vers la réverbération du morceau.")),
    Control("delayFeedback", N_("Délai"), X,
            tip=N_("Le retour du délai : combien de répétitions. 50 ne "
                   "s'arrête plus.")),
    Control("delay.sync", N_("Calage du délai"), X, "choice", choices=_SYNC,
            tip=N_("Le temps du délai, calé sur le tempo ou libre.")),
    Control("delayRate", N_("Temps du délai"), X,
            tip=N_("Le temps du délai quand il est libre.")),
    Control("mod_fx_type", N_("Mod FX"), X, "choice", choices=(
        ("none", N_("Aucun")), ("chorus", "Chorus"), ("flanger", "Flanger"),
        ("phaser", "Phaser"), ("StereoChorus", N_("Chorus stéréo")),
        ("TapeWarble", untranslated("Tape warble")), ("dimension", "Dimension"),
        ("grainFX", "Grain")),
        tip=N_("L'effet de modulation : chorus, flanger, phaser…")),
    Control("modFXDepth", N_("Profondeur mod FX"), X,
            tip=N_("La profondeur de l'effet de modulation.")),
    Control("modFXRate", N_("Vitesse mod FX"), X,
            tip=N_("La vitesse de l'effet de modulation.")),
    Control("clipping", N_("Saturation"), X, minimum=0, maximum=15,
            tip=N_("La saturation du son, de 0 à 15 comme sur la machine.")),
    Control("bitCrush", N_("Réduction de bits"), X,
            tip=N_("Moins de bits : un grain numérique.")),
    Control("sampleRateReduction", N_("Réduction de fréquence"), X,
            tip=N_("Une fréquence d'échantillonnage abaissée : un son "
                   "métallique.")),
    Control("bass", N_("Graves"), X, minimum=-25, maximum=25, bipolar=True,
            tip=N_("L'égaliseur, dans les graves.")),
    Control("treble", N_("Aigus"), X, minimum=-25, maximum=25, bipolar=True,
            tip=N_("L'égaliseur, dans les aigus.")),
)

_BY_KEY = {c.key: c for c in CONTROLS}


def control(key: str) -> Control:
    """Le réglage ``key``."""
    return _BY_KEY[key]


def controls_of(section: str) -> list[Control]:
    """Les réglages d'un onglet, dans l'ordre."""
    return [c for c in CONTROLS if c.section == section]


def copy_sound(sound: Sound) -> Sound:
    """Une copie indépendante, à modifier sans toucher l'original."""
    return copy.deepcopy(sound)


# --------------------------------------------------------------------------- #
# Lire et écrire
# --------------------------------------------------------------------------- #

def _field(sound: Sound, key: str):
    """``(objet, attribut)`` pour un réglage porté par un champ du modèle."""
    head, _, tail = key.partition(".")
    if head in ("osc1", "osc2", "lfo1", "lfo2", "env1", "env2",
                "modulator1", "modulator2"):
        attr = {"sync": "sync_level"}.get(tail, tail)
        return getattr(sound, head), attr
    if head == "unison":
        return sound, "unison_" + tail
    if head == "delay":
        return sound, "delay_sync_level"
    if key == "clipping":
        return sound, "clipping_amount"
    if key in ("mode", "polyphonic", "transpose", "lpf_mode", "hpf_mode",
               "mod_fx_type"):
        return sound, key
    return None, ""


def value(sound: Sound, key: str):
    """La valeur d'un réglage : un cran (entier) ou un choix (texte)."""
    obj, attr = _field(sound, key)
    if obj is not None:
        raw = getattr(obj, attr)
        if key.startswith("env"):
            return to_display(raw)
        if key == "hpf_mode" and not raw:
            return "HPLadder"           # le défaut du firmware
        return raw
    return sound.display(key)


def set_value(sound: Sound, key: str, new) -> None:
    """Écrit un réglage dans ``sound``. Passer en FM éteint les filtres,
    en revenir les rallume (``Sound::setSynthMode``)."""
    c = _BY_KEY.get(key)
    if c is not None and c.kind == "knob":
        new = max(c.minimum, min(c.maximum, int(round(float(new)))))
    obj, attr = _field(sound, key)
    if obj is not None:
        if key.startswith("env"):
            setattr(obj, attr, from_display(int(new)))
            return
        if key == "mode":
            old = sound.mode
            sound.mode = str(new)
            if new == "fm" and old != "fm":
                sound.lpf_mode, sound.hpf_mode = "Off", "Off"
            elif old == "fm" and new != "fm":
                if sound.lpf_mode == "Off":
                    sound.lpf_mode = "24dB"
                if sound.hpf_mode == "Off":
                    sound.hpf_mode = "HPLadder"
            return
        setattr(obj, attr, new)
        return
    sound.set_param(key, from_display(int(new), bipolar=key in PARAM_BIPOLAR))


def visible(sound: Sound, key: str) -> bool:
    """Un réglage a-t-il un sens pour ce son ? (Les modulateurs n'existent
    qu'en FM ; les formes d'onde n'y servent plus.)"""
    fm = sound.mode == "fm"
    if key.startswith("modulator"):
        return fm
    if key in ("osc1.type", "osc2.type", "oscAPulseWidth", "oscBPulseWidth",
               "noiseVolume"):
        return not fm
    return True


# --------------------------------------------------------------------------- #
# Ce que vaut un réglage
# --------------------------------------------------------------------------- #

def _u(sound: Sound, key: str, default: float = 25.0) -> float:
    if key in sound.params:
        return laws.raw_unit(sound.params[key])
    if key in sound.eq:
        return laws.raw_unit(sound.eq[key])
    return float(laws.unit(default))


def _seconds(s: float) -> str:
    if s <= 0:
        return tr("instantané")
    if s < 1.0:
        return tr("%d ms") % int(round(s * 1000))
    return tr("%s s") % decimal(s, 1)


def _hz(hz: float) -> str:
    if hz >= 1000:
        return tr("%s kHz") % decimal(hz / 1000.0, 1)
    if hz >= 10:
        return tr("%d Hz") % int(round(hz))
    return tr("%s Hz") % decimal(hz, 2)


def _db(gain: float) -> str:
    if gain <= 1e-6:
        return tr("silence")
    db = 20.0 * math.log10(gain)
    return tr("%s dB") % (("+" if db > 0.05 else "") + decimal(db, 1))


def _sync(level: int) -> str:
    return tr(dict(_SYNC).get(int(level), str(level)))


def describe(sound: Sound, key: str) -> str:
    """Ce que le réglage vaut sur la machine : « 1,8 s », « 237 Hz »…"""
    try:
        return _describe(sound, key)
    except Exception:  # noqa: BLE001 - une description manque, rien ne casse
        return ""


def _describe(sound: Sound, key: str) -> str:
    if key.startswith("env"):
        env = getattr(sound, key[:4])
        seg = key[5:]
        u = laws.raw_unit(getattr(env, seg))
        if seg == "attack":
            return _seconds(float(laws.attack_seconds(6.0 * u)))
        if seg == "decay":
            return _seconds(float(laws.decay_seconds(u)))
        if seg == "release":
            return _seconds(float(laws.release_seconds(u)))
        return tr("%d %%") % int(round(float(laws.sustain_level(1.0 + u))
                                       * 100))
    if key == "lpfFrequency":
        return _hz(float(laws.lpf_hz(5.6 * _u(sound, key, 50))))
    if key == "hpfFrequency":
        hz = float(laws.hpf_hz(8.0 * _u(sound, key, 0)))
        return _hz(hz) if hz >= 20.0 else tr("tout passe")
    if key in ("lpfResonance", "hpfResonance"):
        return tr("%d %%") % int(round(float(laws.ladder_resonance(
            1.0 + _u(sound, key, 0))) * 100))
    if key in ("lfo1Rate", "lfo2Rate", "modFXRate"):
        lfo = {"lfo1Rate": sound.lfo1, "lfo2Rate": sound.lfo2}.get(key)
        if lfo is not None and lfo.sync_level:
            return tr("calé : %s") % _sync(lfo.sync_level)
        return _hz(float(laws.lfo_hz(8.0 * _u(sound, key))))
    if key in ("lfo1.sync", "lfo2.sync", "delay.sync"):
        return ""
    if key == "delayRate":
        if sound.delay_sync_level:
            return tr("calé : %s") % _sync(sound.delay_sync_level)
        return tr("≈ %s") % _seconds(0.134 * 2.0 ** -(4.0 * _u(sound, key)))
    if key == "delayFeedback":
        return tr("%d %%") % int(round(min(1.0, (1.0 + _u(sound, key, 0))
                                           * 0.5) * 100))
    if key == "portamento":
        glide = laws.glide_seconds((_u(sound, key, 0) + 1.0) * 25.0)
        return _seconds(glide) if glide > 0 else tr("coupé")
    if key in ("volume", "oscAVolume", "oscBVolume", "noiseVolume",
               "reverbAmount", "modFXDepth", "modulator1Amount",
               "modulator2Amount"):
        # Relatif au réglage 50, en décibels.
        gain = float(laws.volume_gain(1.0 + _u(sound, key, 0))) / 4.0
        return _db(gain)
    if key == "pan":
        u = _u(sound, key)
        if abs(u) < 0.02:
            return tr("centre")
        side = tr("gauche") if u < 0 else tr("droite")
        return tr("%s %d %%") % (side, int(round(abs(u) * 100)))
    if key in ("oscAPulseWidth", "oscBPulseWidth"):
        return tr("%d %%") % int(round((0.5 + 0.45 * _u(sound, key)) * 100))
    if key == "unison.detune":
        if sound.unison_num < 2:
            return tr("une seule voix")
        return tr("±%s cents") % decimal(sound.unison_detune / 2.0, 1)
    if key == "unison.num":
        return tr("%d voix") % sound.unison_num
    if key in ("transpose", "osc1.transpose", "osc2.transpose",
               "modulator1.transpose", "modulator2.transpose"):
        n = int(value(sound, key))
        return tr("%+d demi-tons") % n if n else tr("à l'unisson")
    if key in ("osc1.cents", "osc2.cents"):
        n = int(value(sound, key))
        return tr("%+d cents") % n if n else ""
    return ""


# --------------------------------------------------------------------------- #
# Modulations
# --------------------------------------------------------------------------- #

CABLE_SOURCES = (
    ("velocity", N_("Vélocité")), ("envelope1", N_("Enveloppe 1")),
    ("envelope2", N_("Enveloppe 2")), ("lfo1", N_("LFO 1")),
    ("lfo2", N_("LFO 2")), ("note", N_("Note jouée")),
    ("random", N_("Aléatoire")),
    ("aftertouch", "Aftertouch"),
)

#: Destinations proposées, sous le nom du **paramètre** (le câble porte le
#: nom du firmware, :func:`~delugeapp.core.model.cable_destination`).
CABLE_DESTINATIONS = (
    ("volume", N_("Volume")), ("pitch", N_("Hauteur")),
    ("lpfFrequency", N_("Coupure")), ("lpfResonance", N_("Résonance")),
    ("hpfFrequency", N_("Coupure passe-haut")),
    ("oscAVolume", N_("Niveau A")), ("oscBVolume", N_("Niveau B")),
    ("oscAPitch", N_("Hauteur A")), ("oscBPitch", N_("Hauteur B")),
    ("oscAPulseWidth", N_("Largeur A")), ("oscBPulseWidth", N_("Largeur B")),
    ("noiseVolume", N_("Bruit")), ("pan", N_("Panoramique")),
    ("lfo1Rate", N_("Vitesse LFO 1")), ("lfo2Rate", N_("Vitesse LFO 2")),
    ("env1Attack", N_("Attaque 1")), ("env1Release", N_("Release 1")),
    ("env2Decay", N_("Decay 2")), ("modFXDepth", N_("Profondeur mod FX")),
    ("reverbAmount", N_("Réverbération")), ("delayFeedback", N_("Délai")),
    ("modulator1Amount", N_("Modulateur 1")),
    ("modulator2Amount", N_("Modulateur 2")),
)


def describe_cable(cable: PatchCable) -> str:
    """Ce qu'un câble fait sur la machine, à pleine course de sa source :
    « ±4 octaves », « ±0,34 demi-ton », « ×0,5 à ×1,5 »."""
    try:
        dest = param_of_destination(cable.destination)
        a = laws.cable_strength(cable.amount)
        kind = laws.param_class(dest)
        bipolar = (getattr(cable, "polarity", "") or "") != "unipolar" \
            and cable.source != "aftertouch"
        lo = -1.0 if bipolar else 0.0
        if kind == "exp":
            octaves = float(laws.cable_octaves(1.0, a, dest, cable.source))
            if dest in ("pitch", "oscAPitch", "oscBPitch"):
                semis = abs(octaves) * 12.0
                text = tr("%s demi-ton") % decimal(semis, 2)
            else:
                text = tr("%s octave(s)") % decimal(abs(octaves), 1)
            return ("±" if bipolar else "+") + text
        if kind in ("linear", "volume"):
            low = float(laws.cable_factor(lo, a))
            high = float(laws.cable_factor(1.0, a))
            if kind == "volume":
                low, high = low * low, high * high
            return tr("×%s à ×%s") % (decimal(min(low, high), 2),
                                      decimal(max(low, high), 2))
        return (tr("%+d %%") % int(round(a * 100)))
    except Exception:  # noqa: BLE001
        return ""


def add_cable(sound: Sound, source: str = "lfo1",
              destination: str = "lpfFrequency", depth: int = 10
              ) -> PatchCable:
    """Ajoute un câble ``source → destination`` de profondeur ``depth``
    (−50..+50, l'échelle de la machine)."""
    from .model import cable_destination

    cable = PatchCable(source, cable_destination(destination),
                       PatchCable.amount_from_display(depth))
    sound.patch_cables.append(cable)
    return cable


def set_cable(sound: Sound, index: int, *, source: str | None = None,
              destination: str | None = None, depth: int | None = None,
              polarity: str | None = None) -> None:
    """Modifie le câble ``index``."""
    from .model import cable_destination

    cable = sound.patch_cables[index]
    if source is not None:
        cable.source = source
    if destination is not None:
        cable.destination = cable_destination(destination)
    if depth is not None:
        cable.amount = PatchCable.amount_from_display(depth)
    if polarity is not None:
        cable.polarity = polarity


def remove_cable(sound: Sound, index: int) -> None:
    """Retire le câble ``index``."""
    del sound.patch_cables[index]


def differences(before: Sound, after: Sound) -> list[str]:
    """Les réglages qui ont changé, en clair : ``« Coupure : 19 → 30 »``."""
    out = []
    for c in CONTROLS:
        try:
            a, b = value(before, c.key), value(after, c.key)
        except Exception:  # noqa: BLE001
            continue
        if a != b:
            if c.kind == "choice":
                names = dict(c.choices)
                a, b = tr(names.get(a, str(a))), tr(names.get(b, str(b)))
            label = tr(c.label)
            if "%d" in label:
                label = label % int(c.key[3])
            out.append(tr("%s : %s → %s") % (label, a, b))
    if len(before.patch_cables) != len(after.patch_cables) or any(
            (x.source, x.destination, x.amount, x.polarity)
            != (y.source, y.destination, y.amount, y.polarity)
            for x, y in zip(before.patch_cables, after.patch_cables)):
        out.append(tr("Modulations modifiées"))
    return out


# --------------------------------------------------------------------------- #
# Reporter des retouches sur une variante
# --------------------------------------------------------------------------- #

def carry_edits(start: Sound, edited: Sound, onto: Sound) -> Sound:
    """Les retouches qui ont fait ``edited`` à partir de ``start``,
    reportées sur ``onto`` — une variante de ``start`` : on obtient la
    variante du son retouché.

    Un réglage tourné l'est d'autant (coupure 30 → 44 : quatorze crans de
    plus sur la coupure de la variante, dans les bornes de la machine). Un
    choix — forme d'onde, type de filtre, polarité — reste celui qu'on a
    fait, sauf si la variante change ce choix-là : c'est alors ce qu'on lui
    demande (« Autre filtre »). Une modulation ajoutée reste, une modulation
    retirée le reste, une profondeur retouchée l'est d'autant ; une
    modulation que la variante retire disparaît. ``onto`` n'est pas modifié,
    et garde son nom.
    """
    out = copy_sound(onto)
    for c in CONTROLS:
        before, after = value(start, c.key), value(edited, c.key)
        if before == after:
            continue
        theirs = value(onto, c.key)
        if c.kind == "knob":
            set_value(out, c.key, theirs + after - before)
        elif theirs == before:
            set_value(out, c.key, after)
    out.patch_cables = _carry_cables(start.patch_cables,
                                     edited.patch_cables, onto.patch_cables)
    return out


def _keyed(cables) -> dict:
    """Les câbles par ``(source, destination, rang)`` : deux câbles pareils
    restent distincts."""
    out: dict = {}
    for cable in cables:
        key = (cable.source, param_of_destination(cable.destination))
        rank = sum(1 for k in out if k[:2] == key)
        out[key + (rank,)] = cable
    return out


def _polarity(cable: PatchCable) -> str:
    return cable.polarity or "bipolar"      # vide : bipolaire, en 1.3


def _carry_cables(start, edited, onto) -> list[PatchCable]:
    before, after, theirs = _keyed(start), _keyed(edited), _keyed(onto)
    out = []
    for key, cable in theirs.items():
        old, new = before.get(key), after.get(key)
        if old is not None and new is None:
            continue                        # retirée à la main
        if old is None and new is not None:
            out.append(copy.deepcopy(new))  # ajoutée des deux côtés : la vôtre
            continue
        cable = copy.deepcopy(cable)
        if old is not None:
            if new.amount != old.amount:
                cable.set_display(cable.display() + new.display()
                                  - old.display())
            if (_polarity(new) != _polarity(old)
                    and _polarity(cable) == _polarity(old)):
                cable.polarity = new.polarity
        out.append(cable)
    out.extend(copy.deepcopy(cable) for key, cable in after.items()
               if key not in before and key not in theirs)
    return out
