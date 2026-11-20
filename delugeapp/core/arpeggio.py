# -*- coding: utf-8 -*-
"""L'arpégiateur d'un son, pour l'écoute sur l'ordinateur.

Jusqu'au 14 novembre 2026, l'écoute l'ignorait : un son arpégé y jouait ses
accords tenus. Ce module transforme les notes tenues d'une partie en notes
arpégées, avant le rendu (:func:`.render.render_parts`), d'après le code du
firmware 1.3 (``modulation/arpeggiator.cpp``, commit ``102cf9f``) :

* **les pas** tombent sur la grille du morceau, tous les ``2^(3 − niveau)``
  mesures (``doTickForward`` : ``clipCurrentPos % ticksPerPeriod``) — 7, une
  double-croche —, deux tiers ou une fois et demie de cela en ternaire et
  en pointé (``syncType``) ; une note enfoncée entre deux pas attend le
  suivant. **Sans synchronisation** (niveau 0), la première note part
  aussitôt et ``gatePos`` avance de ``arpRate >> 13`` par échantillon, par
  passes de 128 (``ArpeggiatorBase::render``) : un pas tous les 2²⁴ ;
* **l'ordre** (``setInitialNoteAndOctave``, ``calculateNextNoteAndOrOctave``)
  : notes montantes, descendantes, aller-retour, dans l'ordre joué, au
  hasard, en « marche », ou dans l'ordre « pattern » que la machine a tiré
  et écrit dans le fichier (``notePattern``, ``rearrangePatterntArpNotes``) ;
  octaves montantes, descendantes, aller-retour, alternées ou au hasard, sur
  ``numOctaves`` ; chaque pas répété ``stepRepeat`` fois ;
* **la durée** : ``gatePos`` atteint 2²⁴ au bout d'un pas, la note s'éteint
  à ``(arpeggiatorGate + 2³¹) >> 8`` — la moitié du pas au réglage neutre ;
  relâcher la note qui sonne l'éteint aussitôt (``noteOff``) ;
* **le rythme** (``arpRhythmPatterns``, 51 motifs de un à six pas) : un pas
  muet n'avance pas la suite ; **la longueur de séquence** : au bout, la
  suite repart de sa première note ;
* **les tirages**, à chaque pas que le rythme joue (``executeArpStep``,
  ``calculateRandomizerAmounts``) : la note (sinon un silence), la basse (la
  plus grave, sans octave), l'échange (une note et une octave au hasard), le
  glissé (la note tient jusqu'à la fin de la suivante), l'inversion
  (l'échantillon lu à rebours), l'accord (une à trois notes de plus, en
  tierces dans la gamme du morceau, s'il en a cinq au moins), les
  « ratchets » (le pas coupé en 2, 4 ou 8 notes, chacune de la même durée
  relative) ; les étalements de vélocité, de durée et d'octave ;
* **le verrou** (``randomizerLock``) : les seize tirages écrits dans le
  fichier rejoués en boucle — ceux de la machine, à l'identique, tant que le
  réglage n'a pas changé depuis qu'elle les a tirés (``lastLocked…``).

Restent approchés : les tirages sans verrou, qui viennent de ``CONG`` à
graine fixe (la machine part d'une graine que nul ne connaît) ; le verrou,
qui repart au début du morceau, là où la machine le relance à chaque tour de
clip ; un câble vers la vitesse libre ; la vélocité lue dans l'expression
MPE ; les arpèges de kit. Les niveaux de synchronisation sont lus comme ceux
d'un morceau à la résolution par défaut : les limites des « ratchets » (deux
notes au plus en 128ᵉ — quatre **au moins** en 64ᵉ, une faute du firmware
gardée telle quelle —, aucune en 256ᵉ) s'appliquent aux niveaux 8, 7 et 9.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import dsp
from .accomp import NoteEvent

__all__ = ["ArpNote", "ArpSettings", "apply", "expand", "settings_of"]

#: Les anciens modes (``mode`` des firmwares officiels) : ordre des notes
#: et des octaves (``oldModeToArpNoteMode``, ``oldModeToArpOctaveMode``).
_OLD_MODES = {"up": ("up", "up"), "down": ("down", "down"),
              "both": ("up", "alt"), "random": ("random", "random")}
_NOTE_MODES = ("up", "down", "upDown", "asPlayed", "random", "walk1",
               "walk2", "walk3", "pattern")
_OCTAVE_MODES = ("up", "down", "upDown", "alt", "random")
#: ``walk1`` à ``walk3`` : seuils du dé (sur 256) pour reculer d'un pas, et
#: pour rester sur place.
_WALKS = {"walk1": (77, 154), "walk2": (64, 128), "walk3": (51, 102)}

#: ``arpRhythmPatterns`` (``arpeggiator_rhythms.h``), sous les noms du
#: menu : « 0 » joue, « - » se tait. Le premier, « None », joue tout.
RHYTHMS = (
    "0", "0--", "00-", "0-0", "0-00", "00--", "000-", "0--0", "00-0",
    "0----", "0-000", "00---", "0000-", "0---0", "00-00", "0-0--", "000-0",
    "0--0-", "0--00", "000--", "00--0", "0-00-", "00-0-", "0-0-0",
    "0-----", "0-0000", "00----", "00000-", "0----0", "00-000", "0-0---",
    "0000-0", "0---0-", "000-00", "0--000", "000---", "0000--", "0---00",
    "00--00", "0-00--", "000--0", "0--00-", "0-0-00", "00-0--", "000-0-",
    "0--0-0", "0-000-", "00---0", "00--0-", "0-0--0", "00-0-0",
)

_GATE_FULL = 1 << 24
_LOCKED = 16                       # RANDOMIZER_LOCK_MAX_SAVED_VALUES
_TRIPLET, _DOTTED = 10, 19         # SYNC_TYPE_TRIPLET, SYNC_TYPE_DOTTED
_C_MAJOR = (0, (0, 2, 4, 5, 7, 9, 11))


@dataclass
class ArpNote(NoteEvent):
    """Une note arpégée : celles d'un tirage « inversion » font lire leur
    échantillon à rebours (``ArpReturnInstruction::invertReversed``)."""

    reversed: bool = False


@dataclass
class ArpSettings:
    """Ce que l'écoute retient de l'arpégiateur d'un son. Les réglages
    communautaires sont sur 32 bits non signés, comme dans
    ``ArpeggiatorSettings`` (la valeur du fichier plus 2³¹)."""

    note_mode: str = "up"
    octave_mode: str = "up"
    num_octaves: int = 2
    step_repeats: int = 1
    #: 0 : vitesse libre (``free_rate``).
    sync_level: int = 7
    #: Part du pas où la note sonne (``gateThreshold >> 8`` sur 2²⁴).
    gate: float = 0.5
    sync_type: int = 0
    #: La valeur finale d'``arpRate`` (2²⁴ au réglage neutre).
    free_rate: int = 1 << 24
    #: Motif de rythme et longueur de séquence, en crans du menu (0 à 50).
    rhythm: int = 0
    sequence_length: int = 0
    chord_polyphony: int = 0
    ratchet_amount: int = 0
    note_probability: int = 0xFFFFFFFF
    bass_probability: int = 0
    swap_probability: int = 0
    glide_probability: int = 0
    reverse_probability: int = 0
    chord_probability: int = 0
    ratchet_probability: int = 0
    spread_velocity: int = 0
    spread_gate: int = 0
    spread_octave: int = 0
    randomizer_lock: bool = False
    locked: dict = field(default_factory=dict)
    last_locked: dict = field(default_factory=dict)
    note_pattern: tuple | None = None

    @property
    def period(self) -> float:
        """La longueur d'un pas synchronisé, en double-croches."""
        period = 16.0 * 2.0 ** (3 - self.sync_level)
        if self.sync_type >= _DOTTED:
            return period * 3.0 / 2.0
        if self.sync_type >= _TRIPLET:
            return period * 2.0 / 3.0
        return period

    @property
    def gate_small(self) -> int:
        return int(round(self.gate * _GATE_FULL))


#: Les réglages communautaires de ``<defaultParams>`` (sous le nom de leur
#: champ), avec leur valeur par défaut dans le fichier.
_PARAMS = (
    ("note_probability", "noteProbability", 0x7FFFFFFF),
    ("bass_probability", "bassProbability", -(1 << 31)),
    ("swap_probability", "swapProbability", -(1 << 31)),
    ("glide_probability", "glideProbability", -(1 << 31)),
    ("reverse_probability", "reverseProbability", -(1 << 31)),
    ("chord_probability", "chordProbability", -(1 << 31)),
    ("ratchet_probability", "ratchetProbability", -(1 << 31)),
    ("ratchet_amount", "ratchetAmount", -(1 << 31)),
    ("chord_polyphony", "chordPolyphony", -(1 << 31)),
    ("spread_velocity", "spreadVelocity", -(1 << 31)),
    ("spread_gate", "spreadGate", -(1 << 31)),
    ("spread_octave", "spreadOctave", -(1 << 31)),
)


def _menu(value: int) -> int:
    """``computeCurrentValueForUnsignedMenuItem`` : 0 à 50."""
    return (int(value) * 50 + (1 << 31)) >> 32


def settings_of(sound) -> ArpSettings | None:
    """Les réglages de l'arpégiateur d'un son, ou ``None`` s'il est
    éteint."""
    arp = getattr(sound, "arp", None)
    if arp is None or not arp.is_on:
        return None
    if arp.arp_mode:
        note = arp.note_mode if arp.note_mode in _NOTE_MODES else "up"
        octave = arp.octave_mode if arp.octave_mode in _OCTAVE_MODES else "up"
    else:
        note, octave = _OLD_MODES.get(str(arp.mode), ("up", "up"))

    def unsigned(name: str, default: int) -> int:
        return (int(sound.param(name, default)) + (1 << 31)) & 0xFFFFFFFF

    gate = unsigned("arpeggiatorGate", 0) >> 8
    level = max(0, int(arp.sync_level or 0))
    rate = 1 << 24
    if level == 0:
        from . import paramlaws

        u = paramlaws.raw_unit(sound.param("arpeggiatorRate", 0))
        rate = int(float(dsp.get_exp(float(1 << 24), 8.0 * u)))
    out = ArpSettings(
        note, octave, max(1, int(arp.num_octaves or 1)),
        max(1, int(getattr(arp, "step_repeat", 1) or 1)), level,
        min(max(gate, 0), _GATE_FULL - 1) / float(_GATE_FULL),
        sync_type=int(getattr(arp, "sync_type", 0) or 0), free_rate=rate,
        rhythm=_menu(unsigned("rhythm", -(1 << 31))),
        sequence_length=_menu(unsigned("sequenceLength", -(1 << 31))),
        randomizer_lock=bool(getattr(arp, "randomizer_lock", False)),
        locked=dict(getattr(arp, "locked", None) or {}),
        last_locked=dict(getattr(arp, "last_locked", None) or {}),
        note_pattern=getattr(arp, "note_pattern", None))
    for attr, name, default in _PARAMS:
        setattr(out, attr, unsigned(name, default))
    return out


def _mul(a: int, b: int) -> int:
    """``multiply_32x32_rshift32``."""
    return (int(a) * int(b)) >> 32


class _Held:
    """Une note tenue (``ArpNote`` du firmware) : sa hauteur, sa vélocité,
    et ce qu'elle a joué en dernier (``noteCodeOnPostArp``)."""

    __slots__ = ("pitch", "velocity", "post")

    def __init__(self, pitch: int, velocity) -> None:
        self.pitch = int(pitch)
        self.velocity = velocity
        self.post: list[int] = []


#: Ce que tire ``calculateRandomizerAmounts``, dans son ordre : le nom du
#: tirage gardé, le réglage et la façon de tirer.
_DRAWS = (
    ("note", "note_probability", "chance"),
    ("bass", "bass_probability", "chance"),
    ("swap", "swap_probability", "chance"),
    ("glide", "glide_probability", "chance"),
    ("reverse", "reverse_probability", "chance"),
    ("chord", "chord_probability", "chance"),
    ("ratchet", "ratchet_probability", "chance"),
    ("spread_velocity", "spread_velocity", "bipolar"),
    ("spread_gate", "spread_gate", "bipolar"),
    ("spread_octave", "spread_octave", "two_bits"),
)


class _Arp:
    """L'état d'``ArpeggiatorBase`` et d'``Arpeggiator`` pour une partie, et
    les notes qu'il a jouées."""

    def __init__(self, s: ArpSettings, rng: dsp.Cong, key) -> None:
        self.s = s
        self.rng = rng
        root, modes = key if key is not None else _C_MAJOR
        self.root = int(root) % 12
        self.modes = sorted({int(m) % 12 for m in modes})
        pattern = s.note_pattern
        if pattern is None:
            # ``generateNewNotePattern`` : à la création des réglages.
            pattern = tuple(rng.random255() % (i + 1) for i in range(16))
        self.pattern = tuple(pattern) + (0,) * max(0, 16 - len(pattern))
        self.locked = {k: list(s.locked.get(k, ())) + [0] * _LOCKED
                       for k, _a, _w in _DRAWS}
        self.last_locked = {k: int(s.last_locked.get(k, 0))
                            for k, _a, _w in _DRAWS}
        self.notes: list[_Held] = []       # par hauteur
        self.as_played: list[int] = []
        self.by_pattern: list[int] = []
        self.out: list[ArpNote] = []
        self.open: list[int] = []          # notes de ``out`` qui sonnent
        self.active: list[int] = []        # active_note
        self.glide: list[int] = []         # glideNoteCodeCurrentlyOnPostArp
        self.now = 0.0
        self.gate_active = False
        self.gate_pos = 0
        self.gate_t0: float | None = None
        self.played_first = False
        self.seq_count = 0
        self.random_from_octave = 0
        self.which = 0
        self.octave = 0
        self.direction = 1
        self.octave_direction = 1
        self.rhythm_count = 0
        self.last_rhythm = 0
        self.locked_index = 0
        self.last = {"note": True, "bass": False, "swap": False,
                     "reverse": False, "chord": False}
        self.repeat_index = 0
        self.reset_ratchet()
        self.glide_next_off = False
        self.draw = {k: (k == "note") for k, _a, w in _DRAWS
                     if w == "chance"}
        self.spread = {"spread_velocity": 0, "spread_gate": 0,
                       "spread_octave": 0}
        self.reset_locked_next = False

    # -- les tirages ---------------------------------------------------- #

    def _dice(self) -> int:
        return self.rng.random255()

    def _chance(self, value: int) -> bool:
        """``getRandomProbabilityResult``."""
        if value == 0:
            return False
        if value == 0xFFFFFFFF:
            return True
        return (value >> 16) >= self.rng.random(65535)

    def _scaled(self, value: int, factor: int) -> int:
        q31 = _mul(self.rng.triangle(), value >> 1) * 2      # q31_mult
        return _mul(q31, factor)

    def _bipolar(self, value: int) -> int:
        """``getRandomBipolarProbabilityAmount`` : −127 à 127."""
        if value == 0:
            return 0
        return max(-127, min(127, self._scaled(value, 255)))

    def _two_bits(self, value: int) -> int:
        """``getRandomWeighted2BitsAmount`` : 0 à 3. Le « triangle » du
        firmware est saturé : au plus fort, 0, 1, 2 et 3 sortent à 18, 32,
        32 et 18 %."""
        if value == 0:
            return 0
        return abs(self._scaled(value, 5))

    def _draw_one(self, how: str, value: int):
        if how == "chance":
            return self._chance(value)
        if how == "bipolar":
            return self._bipolar(value)
        return self._two_bits(value)

    def calculate_randomizer(self) -> None:
        """``calculateRandomizerAmounts``."""
        s = self.s
        if s.randomizer_lock:
            for key, attr, how in _DRAWS:
                value = getattr(s, attr)
                if self.reset_locked_next or self.last_locked[key] != value:
                    self.locked[key] = [int(self._draw_one(how, value))
                                        for _i in range(_LOCKED)]
                    self.last_locked[key] = value
            self.reset_locked_next = False
            at = self.locked_index % _LOCKED
            for key, _attr, how in _DRAWS:
                v = self.locked[key][at]
                if how == "chance":
                    self.draw[key] = v != 0
                else:
                    self.spread[key] = v
            return
        for key, attr, how in _DRAWS:
            v = self._draw_one(how, getattr(s, attr))
            if how == "chance":
                self.draw[key] = v
            else:
                self.spread[key] = v
        self.reset_locked_next = True

    # -- le pas ---------------------------------------------------------- #

    def reset_ratchet(self) -> None:
        self.ratcheting = False
        self.ratchet_mult = 0
        self.ratchet_count = 0
        self.ratchet_index = 0

    def reset_base(self) -> None:
        self.reset_ratchet()
        self.rhythm_count = 0
        self.last_rhythm = 0
        self.repeat_index = 0
        self.glide_next_off = False
        self.active = []

    def maybe_setup_ratchet(self) -> None:
        """``maybeSetupNewRatchet``."""
        s = self.s
        even = s.sync_type < _TRIPLET
        self.ratcheting = (self.draw["ratchet"] and s.ratchet_amount > 0
                           and not (even and s.sync_level == 9))
        if self.ratcheting:
            self.ratchet_mult = self._two_bits(s.ratchet_amount)
            self.ratchet_count = 1 << self.ratchet_mult
            if s.sync_level == 8:
                self.ratchet_mult, self.ratchet_count = 1, 2
            elif s.sync_level == 7:
                self.ratchet_mult = max(2, self.ratchet_mult)
                self.ratchet_count = max(4, self.ratchet_count)
            if self.ratchet_mult == 0:
                self.ratcheting = False
                self.ratchet_count = 0
        else:
            self.ratchet_mult = 0
            self.ratchet_count = 0
        self.ratchet_index = 0

    def execute_step(self, count: int, is_ratchet: bool) -> dict:
        """``executeArpStep`` : rend les décisions du pas."""
        s = self.s
        if not is_ratchet and (not self.played_first
                               or (s.sequence_length > 0
                                   and self.seq_count >= s.sequence_length)):
            self.played_first = False
            self.seq_count = 0
            self.rhythm_count = 0
            self.last_rhythm = 0
            self.locked_index = 0
            self.random_from_octave = 0
            self.repeat_index = 0
            self.which = 0
            self.glide_next_off = False
        steps = RHYTHMS[min(max(s.rhythm, 0), len(RHYTHMS) - 1)]
        index = self.last_rhythm if is_ratchet else self.rhythm_count
        carry = steps[index % len(steps)] == "0"
        if carry and not is_ratchet:
            self.calculate_randomizer()
        if is_ratchet:
            decided = dict(self.last)
        else:
            decided = {k: self.draw[k] for k in self.last}
        decided["carry"] = carry
        if is_ratchet:
            self.ratchet_index += 1
            return decided
        if carry:
            self.maybe_setup_ratchet()
            if not self.played_first:
                self.initial(count)
            else:
                self.next(count)
            self.random_from_octave += 1
            self.locked_index = (self.locked_index + 1) % _LOCKED
            self.repeat_index += 1
            if self.repeat_index >= s.step_repeats:
                self.repeat_index = 0
            self.played_first = True
            self.last_rhythm = self.rhythm_count
            self.last = {k: decided[k] for k in self.last}
        if s.sequence_length > 0:
            self.seq_count += 1
        self.rhythm_count = (self.rhythm_count + 1) % len(steps)
        return decided

    def initial(self, count: int) -> None:
        """``setInitialNoteAndOctave``."""
        s = self.s
        if s.note_mode == "random":
            self.which, self.direction = self._dice() % count, 1
        elif s.note_mode == "down":
            self.which, self.direction = count - 1, -1
        else:
            self.which, self.direction = 0, 1
        if s.octave_mode == "random":
            self.octave, self.octave_direction = \
                self._dice() % s.num_octaves, 1
        elif s.octave_mode == "down" or (s.octave_mode == "alt"
                                         and s.note_mode == "down"):
            self.octave, self.octave_direction = s.num_octaves - 1, -1
        else:
            self.octave, self.octave_direction = 0, 1

    def next(self, count: int) -> None:
        """``calculateNextNoteAndOrOctave``."""
        s = self.s
        if self.repeat_index > 0:
            return
        if s.note_mode == "random" and s.octave_mode == "random":
            self.which = self._dice() % count
            self.octave = self._dice() % s.num_octaves
            self.octave_direction = self.direction = 1
            self.random_from_octave = 0
            return
        octaves = s.num_octaves
        octave_mode, note_mode = s.octave_mode, s.note_mode
        reverse_once = change_octave = changing_direction = False
        if note_mode == "random":
            self.which = self._dice() % count
            if self.random_from_octave >= count:
                change_octave = True
        else:
            if note_mode in _WALKS:
                back, stay = _WALKS[note_mode]
                dice = self._dice()
                if dice < back:
                    reverse_once = True
                    note_mode = "down"
                    octave_mode = {"up": "down", "down": "up"}.get(
                        octave_mode, octave_mode)
                    self.direction = -self.direction
                    self.octave_direction = -self.octave_direction
                elif dice < stay:
                    return
            self.which += self.direction
            if self.which >= count:
                changing_direction = (self.octave >= octaves - 1
                                      and note_mode not in ("upDown",
                                                            "random")
                                      and octave_mode == "alt")
                if changing_direction:
                    self.direction = -1
                    self.which = count - 2
                elif note_mode == "upDown":
                    self.direction = -1
                    self.which = count - 1
                else:
                    self.which = 0
                    change_octave = True
            elif self.which < 0:
                changing_direction = (self.octave <= 0
                                      and note_mode not in ("upDown",
                                                            "random")
                                      and octave_mode == "alt")
                if changing_direction:
                    self.direction = 1
                    self.which = 1
                elif note_mode == "upDown":
                    self.which = 0
                    self.direction = 1
                    change_octave = True
                else:
                    self.which = count - 1
                    change_octave = True
        if changing_direction:
            self.octave_direction = 1 if self.octave_direction == -1 else -1
        if change_octave:
            self.random_from_octave = 0
            if octaves == 1:
                self.octave, self.octave_direction = 0, 1
            elif octave_mode == "random":
                self.octave = self._dice() % octaves
                self.octave_direction = 1
            elif octave_mode in ("upDown", "alt"):
                self.octave += self.octave_direction
                if self.octave > octaves - 1:
                    self.octave_direction = -1
                    self.octave = octaves - 2 if octave_mode == "alt" \
                        else octaves - 1
                elif self.octave < 0:
                    self.octave_direction = 1
                    self.octave = 1 if octave_mode == "alt" else 0
            else:
                self.octave_direction = -1 if octave_mode == "down" else 1
                self.octave += self.octave_direction
                if self.octave >= octaves:
                    self.octave = 0
                elif self.octave < 0:
                    self.octave = octaves - 1
        if reverse_once:
            self.direction = -self.direction
            self.octave_direction = -self.octave_direction

    # -- les notes jouées ------------------------------------------------ #

    def _search(self, pitch: int) -> int:
        """``notes.search(…, GREATER_OR_EQUAL)``, ramené à 0 au-delà."""
        for k, held in enumerate(self.notes):
            if held.pitch >= pitch:
                return k
        return 0

    def _velocity(self, velocity, spread: int):
        """``calculateSpreadVelocity``, sur la vélocité de la machine (1 à
        127) ; ``velocity`` en pour cent, comme les notes de l'écoute."""
        if spread == 0:
            return velocity
        v = max(1, min(127, int(round(float(velocity) * 1.27))))
        if spread < 0:
            v -= _mul((-spread) << 24, v - 1) << 1
        else:
            v += _mul(spread << 24, 127 - v) << 1
        return max(1, min(127, v)) / 1.27

    def _chord(self, note: int) -> list[int]:
        """Les notes que l'accord ajoute à ``note`` (``switchNoteOn``)."""
        modes = self.modes
        interval = (note - self.root) % 12
        if len(modes) < 5 or interval not in modes:
            return []
        degree = modes.index(interval)
        extra = min(3, self._two_bits(self.s.chord_polyphony))
        offsets = {1: (4,), 2: (2, 4), 3: (2, 4, 6)}.get(extra, ())
        base = modes[degree % len(modes)]
        out = []
        for off in offsets:
            target = modes[(degree + off) % len(modes)]
            if target <= base:
                target += 12
            out.append(min(127, note + target - base))
        return out

    def _end(self, indices, t: float) -> None:
        for i in indices:
            if i in self.open:
                self.open.remove(i)
                e = self.out[i]
                e.length = max(0.0, t - e.start)

    def switch_note_on(self, t: float, is_ratchet: bool) -> None:
        """``Arpeggiator::switchNoteOn``."""
        s = self.s
        count = len(self.notes)
        d = self.execute_step(count, is_ratchet)
        self.which = min(max(self.which, 0), count - 1)
        if d["bass"]:
            source = 0
        elif d["swap"]:
            source = self._dice() % count
        elif s.note_mode == "asPlayed":
            source = self._search(self.as_played[self.which])
        elif s.note_mode == "pattern":
            source = self._search(self.by_pattern[self.which])
        else:
            source = self.which
        held = self.notes[source]
        if not (d["carry"] and d["note"]):
            return
        self.gate_active = True
        if not is_ratchet:
            self.gate_pos = 0
            self.gate_t0 = t
        velocity = self._velocity(held.velocity,
                                  self.spread["spread_velocity"])
        if d["bass"]:
            note = held.pitch
        elif d["swap"]:
            note = held.pitch + (self._dice() % s.num_octaves) * 12
        else:
            note = held.pitch + (self.octave
                                 + self.spread["spread_octave"]) * 12
        note = min(max(note, 0), 127)
        codes = [note]
        if d["chord"]:
            codes += self._chord(note)
        held.post = list(codes)
        self.active = []
        for code in codes:
            self.out.append(ArpNote(t, 0.0, code, velocity,
                                    reversed=bool(d["reverse"])))
            self.active.append(len(self.out) - 1)
            self.open.append(len(self.out) - 1)
        if self.draw["glide"] and not self.ratcheting:
            self.glide_next_off = True

    def switch_any_note_off(self, t: float) -> None:
        """``switchAnyNoteOff`` : une note glissée tient jusqu'à la fin de
        la suivante."""
        if not self.gate_active:
            return
        self._end(self.glide, t)
        self.glide = []
        if self.glide_next_off:
            self.glide = self.active
            self.glide_next_off = False
        else:
            self._end(self.active, t)
        self.active = []
        self.gate_active = False

    def note_on(self, pitch: int, velocity, t: float, free: bool) -> None:
        """``Arpeggiator::noteOn``, l'arpège allumé."""
        if any(h.pitch == pitch for h in self.notes):
            return
        key = sum(1 for h in self.notes if h.pitch < pitch)
        self.notes.insert(key, _Held(pitch, velocity))
        self.as_played.append(int(pitch))
        self.rearrange()
        if len(self.notes) == 1:
            self.played_first = False
            self.gate_active = False
            if free:
                self.switch_note_on(t, False)
        elif self.which >= key:
            self.which += 1

    def note_off(self, pitch: int, t: float) -> None:
        """``Arpeggiator::noteOff`` : la note qui sonne s'éteint si c'est
        elle qu'on relâche (``whichNoteCurrentlyOnPostArp``)."""
        key = next((k for k, h in enumerate(self.notes) if h.pitch == pitch),
                   None)
        if key is None:
            return
        held = self.notes[key]
        if self.which == key:
            self._end(self.glide, t)
            self.glide = []
            self._end([i for i in self.open
                       if self.out[i].note in held.post], t)
            held.post = []
        del self.notes[key]
        self.as_played.remove(int(pitch))
        self.rearrange()
        if self.which >= key:
            self.which = max(0, self.which - 1)
        if self.ratcheting and self.ratchet_index >= self.ratchet_count:
            self.reset_ratchet()
        if not self.notes:
            self.reset_base()
            self.played_first = False
            # Plus rien de tenu : rien ne sonne plus (la machine ne rend plus
            # l'arpège, sa note ne s'éteindrait jamais).
            self._end(list(self.open), t)
            self.glide = []

    def rearrange(self) -> None:
        """``rearrangePatterntArpNotes`` : chaque note, de la plus grave à
        la plus aiguë, insérée à la place que le motif lui donne."""
        order: list[int] = []
        for i, held in enumerate(self.notes):
            place = self.pattern[min(i, 15)]
            order.insert(i if place < 0 else min(place, i), held.pitch)
        self.by_pattern = order

    # -- le temps -------------------------------------------------------- #

    def _gate_small(self) -> int:
        """Le seuil de durée du pas en cours : étalé, puis divisé par le
        nombre de « ratchets » (``ArpeggiatorBase::render``)."""
        gate = self.s.gate_small
        spread = self.spread["spread_gate"]
        if spread < 0:
            gate -= _mul((-spread) << 24, gate) << 1
        elif spread > 0:
            gate += _mul(spread << 24, _GATE_FULL - gate) << 1
        gate = min(max(gate, 0), _GATE_FULL - 1)
        if self.ratcheting:
            gate >>= self.ratchet_mult
        return gate

    def render_window(self, t: float) -> None:
        """Un passage de ``render`` sans synchronisation, au début d'une
        passe de 128 échantillons."""
        gate = self._gate_small()
        part = _GATE_FULL >> self.ratchet_mult
        if self.gate_pos >= self.ratchet_index * part + gate:
            self.switch_any_note_off(t)
            if self.ratcheting and \
                    self.ratchet_index < self.ratchet_count - 1 and \
                    self.gate_pos >= (self.ratchet_index + 1) * part:
                self.switch_note_on(t, True)
            elif self.gate_pos >= _GATE_FULL:
                self.switch_note_on(t, False)

    def next_event(self, period: float) -> tuple[float, str]:
        """Synchronisé : le prochain instant où ``render`` éteint la note ou
        lance le « ratchet » suivant, ``gatePos`` montant de 2²⁴ par pas."""
        if not self.notes or self.gate_t0 is None:
            return float("inf"), ""
        gate = self._gate_small()
        part = _GATE_FULL >> self.ratchet_mult
        off = self.ratchet_index * part + gate
        best = (float("inf"), "")
        if self.gate_active:
            best = (self.gate_t0 + period * off / _GATE_FULL, "off")
        if self.ratcheting and self.ratchet_index < self.ratchet_count - 1:
            on = max(off, (self.ratchet_index + 1) * part)
            t_on = self.gate_t0 + period * on / _GATE_FULL
            if t_on < best[0]:
                best = (t_on, "ratchet")
        return max(best[0], self.now), best[1]


def _changes(events) -> list[tuple[float, int, int]]:
    """Les changements, dans l'ordre : à un même instant, les relâchés
    d'abord, puis les enfoncés."""
    changes = []
    for i, e in enumerate(events):
        changes.append((float(e.start) + float(e.length), 0, i))
        changes.append((float(e.start), 1, i))
    changes.sort()
    return changes


def expand(events, s: ArpSettings, seed: int = 0, key=None,
           bpm: float = 120.0) -> list:
    """Les notes ``events`` (:class:`.accomp.NoteEvent`, tenues) arpégées
    selon ``s`` : des :class:`ArpNote`, en double-croches elles aussi.

    :param key: ``(tonique, notes de la gamme)`` du morceau, pour les
        accords — do majeur, celle d'un morceau neuf, sans elle.
    :param bpm: le tempo, pour la vitesse libre."""
    events = sorted(events, key=lambda e: (float(e.start), int(e.note)))
    if not events:
        return []
    arp = _Arp(s, dsp.Cong((dsp.CONG_SEED + int(seed)) & 0xFFFFFFFF), key)
    changes = _changes(events)
    if s.sync_level > 0:
        _run_synced(arp, events, changes)
    else:
        _run_free(arp, events, changes, bpm)
    end = max(t for t, _k, _i in changes)
    arp._end(list(arp.open), end)
    return [e for e in arp.out if e.length > 0]


def _apply_change(arp: _Arp, events, change, free: bool) -> None:
    t, kind, i = change
    arp.now = max(arp.now, t)
    if kind == 1:
        arp.note_on(int(events[i].note), events[i].velocity, t, free)
    else:
        arp.note_off(int(events[i].note), t)


def _run_synced(arp: _Arp, events, changes) -> None:
    """Les pas sur la grille, et entre eux ce que ``render`` éteint ou
    relance."""
    period = arp.s.period
    end = max(t for t, _k, _i in changes)
    c = 0
    tick = 0
    while True:
        t_tick = tick * period
        while True:
            t_in = changes[c][0] if c < len(changes) else float("inf")
            t_ev, what = arp.next_event(period)
            if t_in <= t_tick + 1e-9 and t_in <= t_ev + 1e-9:
                _apply_change(arp, events, changes[c], False)
                c += 1
                continue
            if t_ev < t_tick - 1e-9:
                arp.now = t_ev
                arp.switch_any_note_off(t_ev)
                if what == "ratchet":
                    arp.switch_note_on(t_ev, True)
                continue
            break
        if t_tick > end + 1e-9:
            break
        arp.now = t_tick
        if tick == 0:
            arp.locked_index = 0           # clipCurrentPos == 0
        if arp.notes:
            arp.switch_any_note_off(t_tick)
            arp.switch_note_on(t_tick, False)
        tick += 1


def _run_free(arp: _Arp, events, changes, bpm: float) -> None:
    """Sans synchronisation : ``render`` à chaque passe de 128
    échantillons, ``gatePos`` remis à 2²⁴ près."""
    tempo = float(bpm) if bpm and bpm > 0 else 120.0
    per_step = dsp.SR * 60.0 / tempo / 4.0
    window = dsp.BLOCK
    increment = ((int(arp.s.free_rate) >> 5) >> 8) * window
    c = 0
    sample = 0
    while True:
        t = sample / per_step
        while c < len(changes) and changes[c][0] <= t + 1e-9:
            _apply_change(arp, events, changes[c], True)
            c += 1
        if c >= len(changes) and not arp.notes:
            break
        arp.now = max(arp.now, t)
        if arp.notes:
            arp.render_window(t)
            arp.gate_pos &= _GATE_FULL - 1
            arp.gate_pos += increment
        sample += window


def apply(parts: dict, sounds: dict, bpm: float = 120.0, key=None) -> dict:
    """Les parties dont le son arpège, arpégées ; les autres telles
    quelles. ``key`` : la gamme du morceau (:func:`expand`)."""
    out = {}
    for name, events in (parts or {}).items():
        s = settings_of((sounds or {}).get(name))
        out[name] = expand(events, s, key=key, bpm=bpm) \
            if s is not None else events
    return out
