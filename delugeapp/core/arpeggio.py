# -*- coding: utf-8 -*-
"""L'arpégiateur d'un son, pour l'écoute sur l'ordinateur.

Jusqu'au 14 novembre 2026, l'écoute l'ignorait : un son arpégé y jouait ses
accords tenus. Ce module transforme les notes tenues d'une partie en notes
arpégées, avant le rendu (:func:`.render.render_parts`), d'après le code du
firmware 1.3 (``modulation/arpeggiator.cpp``, commit ``102cf9f``) :

* **les pas** tombent sur la grille du morceau, tous les ``2^(3 − niveau)``
  mesures (``doTickForward`` : ``clipCurrentPos % ticksPerPeriod``) — 7, une
  double-croche ; une note enfoncée entre deux pas attend le suivant ;
* **l'ordre** (``setInitialNoteAndOctave``, ``calculateNextNoteAndOrOctave``)
  : notes montantes, descendantes, aller-retour, dans l'ordre joué, au
  hasard, ou en « marche » ; octaves montantes, descendantes, aller-retour,
  alternées ou au hasard, sur ``numOctaves`` ; chaque pas répété
  ``stepRepeat`` fois ;
* **la durée** : ``gatePos`` atteint 2²⁴ au bout d'un pas, la note s'éteint
  à ``(arpeggiatorGate + 2³¹) >> 8`` — la moitié du pas au réglage neutre ;
  relâcher la note qui sonne l'éteint aussitôt (``noteOff``) ;
* une note ajoutée ou retirée pendant l'arpège décale la position comme
  sur la machine.

Restent au neutre les fonctions de la version communautaire qui tirent au
sort ou découpent le pas — rythme, longueur de séquence, « ratchets »,
probabilités de note, de basse, d'échange, d'inversion, d'accord, étalement
de vélocité, de durée et d'octave —, comme dans un son neuf ; le mode
« pattern » (un ordre tiré au sort par la machine) joue dans l'ordre
montant. Un arpège sans synchronisation (niveau 0, vitesse libre) n'est pas
porté : ses notes restent tenues. Les tirages au sort viennent d'un
générateur à graine fixe : la machine, elle, tire les siens au hasard.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

__all__ = ["ArpSettings", "apply", "expand", "settings_of"]

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


@dataclass
class ArpSettings:
    """Ce que l'écoute retient de l'arpégiateur d'un son."""

    note_mode: str = "up"
    octave_mode: str = "up"
    num_octaves: int = 2
    step_repeats: int = 1
    sync_level: int = 7
    #: Part du pas où la note sonne (``gateThreshold``, de 0 à 1).
    gate: float = 0.5

    @property
    def period(self) -> float:
        """La longueur d'un pas, en double-croches."""
        return 16.0 * 2.0 ** (3 - self.sync_level)


def settings_of(sound) -> ArpSettings | None:
    """Les réglages de l'arpégiateur d'un son, ou ``None`` s'il est éteint
    — ou sans synchronisation, que l'écoute ne porte pas."""
    arp = getattr(sound, "arp", None)
    if arp is None or not arp.is_on:
        return None
    if arp.arp_mode:
        note = arp.note_mode if arp.note_mode in _NOTE_MODES else "up"
        octave = arp.octave_mode if arp.octave_mode in _OCTAVE_MODES else "up"
    else:
        note, octave = _OLD_MODES.get(str(arp.mode), ("up", "up"))
    level = int(arp.sync_level or 0)
    if level <= 0:
        return None
    gate = (int(sound.param("arpeggiatorGate", 0)) + (1 << 31)) >> 8
    return ArpSettings(note, octave, max(1, int(arp.num_octaves or 1)),
                       max(1, int(getattr(arp, "step_repeat", 1) or 1)),
                       level, min(max(gate / float(1 << 24), 0.0), 1.0))


class _Arp:
    """L'état de ``ArpeggiatorBase`` : la note et l'octave en cours, leurs
    directions, ce qui a été joué dans l'octave."""

    def __init__(self, s: ArpSettings, rng: random.Random):
        self.s = s
        self.rng = rng
        self.which = 0
        self.direction = 1
        self.octave = 0
        self.octave_direction = 1
        self.random_from_octave = 0
        self.repeat_index = 0
        self.first = True

    def _dice(self) -> int:
        return self.rng.randrange(256)

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

    def step(self, count: int) -> None:
        """``executeArpStep`` d'un pas joué, au neutre."""
        if self.first:
            self.random_from_octave = 0
            self.repeat_index = 0
            self.which = 0
            self.initial(count)
        else:
            self.next(count)
        self.random_from_octave += 1
        self.repeat_index += 1
        if self.repeat_index >= self.s.step_repeats:
            self.repeat_index = 0
        self.first = False


def expand(events, s: ArpSettings, seed: int = 0) -> list:
    """Les notes ``events`` (:class:`.accomp.NoteEvent`, tenues) arpégées
    selon ``s`` : des notes neuves, en double-croches elles aussi."""
    from .accomp import NoteEvent

    events = sorted(events, key=lambda e: (float(e.start), int(e.note)))
    if not events:
        return []
    period = s.period
    # Les changements, dans l'ordre : à un même instant, les relâchés
    # d'abord, puis les enfoncés, puis le pas.
    changes = []
    for i, e in enumerate(events):
        changes.append((float(e.start) + float(e.length), 0, i))
        changes.append((float(e.start), 1, i))
    changes.sort()
    end = max(t for t, _k, _i in changes)
    held: list[tuple[int, int]] = []        # (hauteur, index), triées
    as_played: list[int] = []
    arp = _Arp(s, random.Random(seed))
    out: list = []
    sounding = None                          # (index dans out, hauteur source)
    c = 0
    tick = 0
    while True:
        t_tick = tick * period
        while c < len(changes) and changes[c][0] <= t_tick + 1e-9:
            t, kind, i = changes[c]
            c += 1
            pitch = int(events[i].note)
            if kind == 1:
                if any(p == pitch for p, _j in held):
                    continue
                key = sum(1 for p, _j in held if p < pitch)
                held.insert(key, (pitch, i))
                as_played.append(pitch)
                if len(held) == 1:
                    arp.first = True
                elif arp.which >= key:
                    arp.which += 1
                continue
            key = next((k for k, (p, j) in enumerate(held) if j == i), None)
            if key is None:
                continue
            if sounding is not None and sounding[1] == pitch:
                _cut(out, sounding[0], t)
                sounding = None
            del held[key]
            as_played.remove(pitch)
            if not held and sounding is not None:
                _cut(out, sounding[0], t)
                sounding = None
            if arp.which >= key:
                arp.which = max(0, arp.which - 1)
        if t_tick > end + 1e-9:
            break
        if held:
            count = len(held)
            arp.step(count)
            arp.which = min(max(arp.which, 0), count - 1)
            if s.note_mode == "asPlayed":
                wanted = as_played[arp.which]
                source = next((k for k, (p, _j) in enumerate(held)
                               if p >= wanted), 0)
            else:
                source = arp.which
            pitch, j = held[source]
            note = min(max(pitch + arp.octave * 12, 0), 127)
            out.append(NoteEvent(t_tick, s.gate * period, note,
                                 int(events[j].velocity)))
            sounding = (len(out) - 1, pitch)
        tick += 1
    return [e for e in out if e.length > 0]


def _cut(out: list, index: int, t: float) -> None:
    """La note arpégée ``out[index]`` s'éteint à ``t`` si elle sonne
    encore."""
    e = out[index]
    if e.start + e.length > t:
        e.length = max(0.0, t - e.start)


def apply(parts: dict, sounds: dict) -> dict:
    """Les parties dont le son arpège, arpégées ; les autres telles
    quelles."""
    out = {}
    for name, events in (parts or {}).items():
        s = settings_of((sounds or {}).get(name))
        out[name] = expand(events, s) if s is not None else events
    return out
