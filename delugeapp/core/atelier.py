# -*- coding: utf-8 -*-
"""L'atelier du compositeur : un morceau, du choix des sons à l'arrangement.

Les outils de l'application savaient chacun une chose — un preset, un kit,
une progression, un rythme, une esquisse — et s'arrêtaient là. L'atelier les
tient ensemble autour d'**un morceau** et d'**un style** :

1. **le style** : genre, tempo, tonalité, ambiance des accords, et les six
   curseurs du générateur, communs à tous les sons — ce qui rend les sons
   d'un même morceau cohérents entre eux ;
2. **les pistes** : un kit, des synthés, des pistes MIDI (un appareil
   extérieur) ou CV (un modulaire), chacune avec sa partie — batterie,
   basse, accords, arpège, mélodie ;
3. **les clips** de chaque piste : un premier, puis ses variations
   (:mod:`delugeapp.core.variation`), toutes sur la même progression ;
4. **les sections** : quel clip chaque piste joue dans chacune, sur combien
   de mesures — le morceau, puis son arrangement.

Le projet devient un morceau du Deluge neuf (:func:`to_song_spec`,
:mod:`delugeapp.core.songwriter`) ou s'ajoute à un morceau existant, sans
rien en réécrire (:mod:`delugeapp.core.songinsert`). Il peut aussi **partir
d'un morceau de la carte** (:func:`from_song`) : ses pistes, ses clips, son
tempo et sa gamme deviennent ceux du projet, et sa progression est lue dans
ses notes (:func:`infer_progression`).

Module sans Qt ; la carte n'est lue que pour bâtir un kit ou retrouver un
preset.
"""

from __future__ import annotations

import copy
import logging
import random
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from ..i18n import N_, tr
from . import accomp, rhythm, sketch, synthgen, theory, variation
from .accomp import STEPS_PER_BAR, NoteEvent

log = logging.getLogger(__name__)

__all__ = [
    "KINDS", "PARTS", "PART_ROLES", "MACROS", "Style", "AtelierClip",
    "AtelierTrack", "AtelierSection", "Project", "new_project",
    "default_sections", "add_track", "remove_track", "generate_clip",
    "vary_clip", "remove_clip", "set_cell", "add_section", "remove_section",
    "move_section", "regenerate_sound", "sound_variations", "adopt_sound",
    "to_song_spec", "section_parts", "clip_parts", "infer_progression",
    "from_song", "track_label", "next_key", "parts_for_kind", "drum_rows",
    "live_notes", "listen_sounds", "insertion_plan", "clone_project",
    "edit_sound", "FEELS", "feels_for", "toggle_hit", "groove_clip",
    "add_euclid", "fullest_section", "arrangement_parts", "export_midi",
    "part_for", "use_preset", "use_kit",
]

#: Natures de piste, comme sur le Deluge.
KINDS: dict[str, str] = {
    "kit": N_("Kit"),
    "synth": N_("Synthé"),
    "midi": N_("MIDI"),
    "cv": N_("CV"),
}

#: Parties qu'une piste peut jouer (clés d'``accomp``).
PARTS: tuple[str, ...] = ("Batterie", "Basse", "Accords", "Arpège",
                          "Mélodie")

#: Rôle du son généré pour chaque partie.
PART_ROLES: dict[str, str] = {"Basse": "bass", "Accords": "pad",
                              "Arpège": "pluck", "Mélodie": "lead"}

#: Les six curseurs du générateur, partagés par tous les sons du projet.
MACROS = ("brightness", "movement", "space", "dirt", "width", "complexity")

#: Longueur d'un premier clip, en mesures.
DEFAULT_BARS = 4


def parts_for_kind(kind: str) -> tuple[str, ...]:
    """Parties possibles pour une nature de piste.

    Un kit ne joue que la batterie ; une piste CV, monophonique, ni accords
    ni batterie.
    """
    if kind == "kit":
        return ("Batterie",)
    if kind == "cv":
        return ("Basse", "Arpège", "Mélodie")
    return ("Basse", "Accords", "Arpège", "Mélodie")


# --------------------------------------------------------------------------- #
# Le projet
# --------------------------------------------------------------------------- #

@dataclass
class Style:
    """Ce qui rend les clips et les sons d'un morceau cohérents."""

    genre: str = "techno"
    #: 0 : le milieu de la plage du genre.
    bpm: float = 0.0
    root: int = 57
    scale: str = "mineur"
    #: Ambiance de la progression ; vide : celle du genre.
    ambiance: str = ""
    #: Couleur des accords ; vide : celle de l'ambiance.
    color: str = ""
    macros: dict[str, float] = field(default_factory=lambda: {
        m: 0.5 for m in MACROS})
    seed: int = 1

    def tempo(self) -> float:
        """Le tempo du morceau."""
        if self.bpm and self.bpm > 0:
            return float(self.bpm)
        from .genres import genre

        low, high = genre(self.genre).bpm
        return float(round((low + high) / 2.0))

    def mood(self) -> str:
        return self.ambiance or sketch.GENRE_AMBIANCE.get(self.genre, "pop")

    def options(self, role: str, seed: int) -> synthgen.GenOptions:
        """Les réglages du générateur pour un son de ce style."""
        opts = synthgen.GenOptions(genre=self.genre, role=role, seed=seed)
        for macro in MACROS:
            setattr(opts, macro, float(self.macros.get(macro, 0.5)))
        return opts


@dataclass
class AtelierClip:
    """Un clip d'une piste : des notes (en pas de double-croche) ou un
    motif de batterie."""

    key: str
    bars: int = DEFAULT_BARS
    events: list[NoteEvent] = field(default_factory=list)
    pattern: rhythm.Pattern | None = None
    #: Comment il est né : « généré », une variation (``fin``, ``cassure``…)
    #: ou « morceau » pour un clip lu sur la carte.
    origin: str = N_("généré")
    #: Clip d'où vient une variation.
    parent: str = ""
    seed: int = 0
    #: Index du clip dans les ``sessionClips`` du morceau importé : un clip
    #: qui est déjà sur le Deluge ne se réécrit pas.
    existing: int | None = None

    @property
    def steps(self) -> int:
        return int(self.bars) * STEPS_PER_BAR

    @property
    def note_count(self) -> int:
        if self.pattern is not None:
            return sum(len(s) for s in self.pattern.tracks.values())
        return len(self.events)


@dataclass
class AtelierTrack:
    """Une piste du projet."""

    uid: int
    kind: str
    part: str
    name: str = ""
    #: Canal d'une piste MIDI (1 à 16) ou CV (1 ou 2).
    channel: int = 1
    #: Réglages qui ont fait le son d'un synthé généré : c'est eux que les
    #: variantes de son poussent ou tirent à nouveau.
    options: synthgen.GenOptions | None = None
    preset: object | None = None
    kit: object | None = None
    clips: list[AtelierClip] = field(default_factory=list)
    #: Instrument du morceau importé (nature, nom, dossier, canal) : la
    #: piste existe déjà sur le Deluge.
    existing: dict | None = None
    #: Le son a été retouché à la main (:func:`edit_sound`) : ``preset`` n'est
    #: plus ce que donnent ``options``, et les variantes dans le style
    #: reportent ces retouches (:func:`sound_variations`).
    edited: bool = False
    #: Le jeu des clips neufs d'une piste d'accords ou de basse — « stabs »,
    #: « contretemps »… (:data:`FEELS`) ; vide : celui du genre.
    feel: str = ""

    def clip(self, key: str) -> AtelierClip | None:
        for clip in self.clips:
            if clip.key == key:
                return clip
        return None

    @property
    def is_drums(self) -> bool:
        return self.kind == "kit"

    @property
    def mono(self) -> bool:
        return self.kind == "cv"


@dataclass
class AtelierSection:
    """Une section : son nom, sa durée, et le clip de chaque piste."""

    name: str
    kind: str = "montée"
    bars: int = 16
    #: Piste (``uid``) -> clé du clip joué ; une piste absente se tait.
    cells: dict[int, str] = field(default_factory=dict)
    #: Numéro de la section dans le morceau importé.
    existing: int | None = None


@dataclass
class Project:
    """Le morceau en cours."""

    style: Style = field(default_factory=Style)
    progression: list[dict] = field(default_factory=list)
    tracks: list[AtelierTrack] = field(default_factory=list)
    sections: list[AtelierSection] = field(default_factory=list)
    #: Morceau de la carte d'où part le projet, s'il y en a un.
    song_rel: str = ""
    song_name: str = ""
    #: Disposition et version du morceau importé (``songinsert``).
    song_firmware: str = ""
    _next_uid: int = 1

    def track(self, uid: int) -> AtelierTrack | None:
        for track in self.tracks:
            if track.uid == uid:
                return track
        return None

    def index_of(self, uid: int) -> int:
        for index, track in enumerate(self.tracks):
            if track.uid == uid:
                return index
        return -1

    def new_uid(self) -> int:
        uid = self._next_uid
        self._next_uid += 1
        return uid

    @property
    def bars(self) -> int:
        return sum(int(s.bars) for s in self.sections)


def track_label(track: AtelierTrack) -> str:
    """Nom d'une piste pour l'écran : sa partie et sa nature."""
    if track.name:
        return track.name
    label = tr(track.part)
    if track.kind == "midi":
        return tr("%s (MIDI %d)") % (label, track.channel)
    if track.kind == "cv":
        return tr("%s (CV %d)") % (label, track.channel)
    return label


def next_key(track: AtelierTrack) -> str:
    """Prochaine lettre libre : A, B, C… puis A2, B2…"""
    taken = {c.key for c in track.clips}
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    for round_ in range(1, 100):
        for letter in letters:
            key = letter if round_ == 1 else "%s%d" % (letter, round_)
            if key not in taken:
                return key
    return "Z%d" % (len(taken) + 1)


# --------------------------------------------------------------------------- #
# Fabriquer
# --------------------------------------------------------------------------- #

def _progression(style: Style, seed: int | None = None) -> list[dict]:
    color = style.color or theory.AMBIANCE_COLORS.get(style.mood(), "")
    return theory.progression(int(style.root), style.scale, style.mood(),
                              seed=style.seed if seed is None else seed,
                              bars=4, color=color)


def _sound_for(style: Style, part: str, seed: int):
    """Un son du style pour une partie : ses réglages et le preset."""
    role = PART_ROLES.get(part, "lead")
    if part == "Accords":
        held = accomp.genre_styles(style.genre)[0] in ("tenu", "blanches")
        role = "pad" if held else "stab"
    opts = style.options(role, seed)
    preset = _generate(opts)
    opts.name = preset.sound.name
    return opts, preset


def _generate(opts: synthgen.GenOptions):
    """Le preset que donnent ``opts``, arpégiateur éteint : l'arpège est
    écrit note par note, l'arpégiateur du son jouerait par dessus
    (``songwriter.part_presets``)."""
    preset = synthgen.generate(opts)
    _arp_off(preset.sound)
    return preset


def _arp_off(sound) -> None:
    sound.arp.mode = "off"
    sound.arp.arp_mode = "off"


def add_track(project: Project, kind: str, part: str = "", *,
              channel: int = 1, sd=None, lib=None,
              seed: int | None = None, clip: bool = True) -> AtelierTrack:
    """Ajoute une piste et, d'office, son premier clip.

    Un synthé reçoit un son généré dans le style du projet ; un kit, un kit
    bâti dans la bibliothèque de la carte si elle est là (sinon la batterie
    s'écoute avec la batterie synthétisée, et un kit se choisit avant
    d'écrire).
    """
    if kind not in KINDS:
        raise ValueError(tr("nature de piste inconnue : %s") % kind)
    allowed = parts_for_kind(kind)
    part = part if part in allowed else allowed[0]
    style = project.style
    base_seed = style.seed if seed is None else int(seed)
    track = AtelierTrack(uid=project.new_uid(), kind=kind, part=part,
                         channel=max(1, min(16 if kind == "midi" else 2,
                                            int(channel))))
    sound_seed = int(random.Random(f"{base_seed}|{part}|{track.uid}")
                     .randrange(1 << 30))
    if kind == "synth":
        track.options, track.preset = _sound_for(style, part, sound_seed)
    elif kind == "kit" and sd is not None and lib is not None:
        track.kit = _build_kit(sd, lib, style, sound_seed)
    project.tracks.append(track)
    if clip:
        generate_clip(project, track.uid, seed=sound_seed)
    return track


def _build_kit(sd, lib, style: Style, seed: int):
    from . import kitgen

    try:
        kit = kitgen.build_kit(sd, lib, tr("ATELIER"), genre=style.genre,
                               seed=seed)
    except Exception as exc:          # noqa: BLE001 - la batterie s'écoute sans
        log.debug("kit de l'atelier impossible : %s", exc)
        return None
    return kit if getattr(kit, "rows", None) else None


def remove_track(project: Project, uid: int) -> None:
    """Retire une piste et ses cases dans toutes les sections."""
    project.tracks = [t for t in project.tracks if t.uid != uid]
    for section in project.sections:
        section.cells.pop(uid, None)


#: Les jeux qu'une piste d'accords ou de basse peut prendre — ceux de la
#: Boîte à outils d'autrefois, rangés par partie.
FEELS: dict[str, tuple[str, ...]] = {
    "Accords": tuple(accomp.CHORD_STYLES),
    "Basse": tuple(accomp.BASS_STYLES),
}


def feels_for(part: str) -> tuple[str, ...]:
    """Les jeux possibles d'une partie ; aucun pour l'arpège ou la mélodie,
    dont l'allure suit le genre."""
    return FEELS.get(str(part or ""), ())


def _make_events(project: Project, track: AtelierTrack, bars: int,
                 seed: int) -> list[NoteEvent]:
    style = project.style
    chords = [variation.chord_at(project.progression, b) for b in range(bars)]
    styles = accomp.genre_styles(style.genre)
    part = track.part
    feel = track.feel if track.feel in feels_for(part) else ""
    if part == "Basse":
        events = accomp.bass_part(chords, feel or styles[1])
    elif part == "Accords":
        events = accomp.chord_part(chords, feel or styles[0])
    elif part == "Arpège":
        events = accomp.arp_part(chords, rate=1 if track.mono else 2,
                                 octaves=2, seed=seed)
    else:
        events = accomp.melody_part(chords, root=style.root,
                                    scale=style.scale, genre=style.genre,
                                    seed=seed)
    return variation.clean_part(events, bars * STEPS_PER_BAR,
                                mono=track.mono)


def generate_clip(project: Project, uid: int, bars: int | None = None,
                  seed: int | None = None) -> AtelierClip:
    """Un clip neuf pour la piste, sur la progression du projet."""
    track = project.track(uid)
    if track is None:
        raise ValueError(tr("piste inconnue"))
    if not project.progression:
        project.progression = _progression(project.style)
    bars = max(1, int(bars or DEFAULT_BARS))
    seed = int(seed if seed is not None
               else random.Random(f"{project.style.seed}|{uid}|"
                                  f"{len(track.clips)}").randrange(1 << 30))
    clip = AtelierClip(key=next_key(track), bars=bars, seed=seed)
    if track.is_drums:
        clip.pattern = rhythm.genre_beat(project.style.genre, bars=bars,
                                         seed=seed)
    else:
        clip.events = _make_events(project, track, bars, seed)
    track.clips.append(clip)
    return clip


def vary_clip(project: Project, uid: int, key: str, how: str,
              seed: int | None = None) -> AtelierClip:
    """Une variation du clip ``key`` de la piste, ajoutée à ses clips."""
    track = project.track(uid)
    source = track.clip(key) if track is not None else None
    if source is None:
        raise ValueError(tr("clip inconnu"))
    seed = int(seed if seed is not None
               else random.Random(f"{project.style.seed}|{uid}|{key}|{how}|"
                                  f"{len(track.clips)}").randrange(1 << 30))
    clip = AtelierClip(key=next_key(track), bars=source.bars, origin=how,
                       parent=source.key, seed=seed)
    if track.is_drums:
        if source.pattern is None:
            raise ValueError(tr("clip sans motif"))
        clip.pattern = variation.vary_drums(source.pattern, how,
                                            genre=project.style.genre,
                                            seed=seed)
    else:
        clip.events = variation.vary_part(
            source.events, how, part=track.part, bars=source.bars,
            chords=project.progression, root=project.style.root,
            scale=project.style.scale, seed=seed, genre=project.style.genre,
            mono=track.mono)
    track.clips.append(clip)
    return clip


def remove_clip(project: Project, uid: int, key: str) -> None:
    """Retire un clip ; les sections qui le jouaient se taisent pour cette
    piste."""
    track = project.track(uid)
    if track is None:
        return
    track.clips = [c for c in track.clips if c.key != key]
    for section in project.sections:
        if section.cells.get(uid) == key:
            del section.cells[uid]


def set_cell(project: Project, section_index: int, uid: int,
             key: str | None) -> None:
    """Le clip que la piste joue dans la section ; ``None`` : silence."""
    section = project.sections[int(section_index)]
    if key is None:
        section.cells.pop(uid, None)
        return
    track = project.track(uid)
    if track is None or track.clip(key) is None:
        raise ValueError(tr("clip inconnu"))
    section.cells[uid] = key


def add_section(project: Project, name: str, bars: int = 16,
                index: int | None = None) -> AtelierSection:
    """Une section neuve ; elle reprend les clips de la précédente."""
    section = AtelierSection(name=name or tr("Section"),
                             kind=sketch.section_kind(name), bars=max(1, int(bars)))
    position = len(project.sections) if index is None else max(
        0, min(len(project.sections), int(index)))
    if position:
        section.cells = dict(project.sections[position - 1].cells)
    project.sections.insert(position, section)
    return section


def remove_section(project: Project, index: int) -> None:
    if 0 <= int(index) < len(project.sections):
        del project.sections[int(index)]


def move_section(project: Project, index: int, offset: int) -> int:
    """Déplace une section ; rend sa nouvelle place."""
    index = int(index)
    target = max(0, min(len(project.sections) - 1, index + int(offset)))
    if 0 <= index < len(project.sections) and target != index:
        section = project.sections.pop(index)
        project.sections.insert(target, section)
    return target


# --------------------------------------------------------------------------- #
# La batterie, à la main
# --------------------------------------------------------------------------- #

def _drum_clip(project: Project, uid: int, key: str) -> AtelierClip:
    track = project.track(uid)
    clip = track.clip(key) if track is not None else None
    if clip is None or not track.is_drums:
        raise ValueError(tr("clip inconnu"))
    if clip.pattern is None:
        clip.pattern = rhythm.Pattern(name="", steps=clip.steps)
    return clip


def toggle_hit(project: Project, uid: int, key: str, row: str, step: int,
               velocity: int = 100) -> bool:
    """Ajoute ou retire un coup dans un clip de batterie, à la case ``step``
    de la rangée ``row``. Rend vrai si le coup y est désormais.

    Un coup décalé par un groove compte pour la case d'où il vient : le
    retirer se fait en cliquant là où la grille le montre.
    """
    clip = _drum_clip(project, uid, key)
    step = int(step)
    if not 0 <= step < clip.steps:
        raise ValueError(tr("case hors du clip"))
    hits = clip.pattern.tracks.setdefault(str(row), [])
    present = [s for s in hits if rhythm.cell(s) == step]
    for hit in present:
        hits.remove(hit)
    if not present:
        hits.append(rhythm.Step(pos=step, velocity=max(1, min(100,
                                                              int(velocity)))))
        hits.sort(key=lambda s: float(s.pos))
    return not present


def groove_clip(project: Project, uid: int, key: str, groove: str,
                swing: float = 0.0) -> AtelierClip:
    """Pose un groove — et un swing de 0 à 1 — sur un clip de batterie.

    Toujours depuis le motif droit : un second groove remplace le premier
    au lieu de s'y ajouter. Les coups ajoutés à la main restent.
    """
    clip = _drum_clip(project, uid, key)
    pattern = rhythm.apply_groove(rhythm.straighten(clip.pattern),
                                  groove or "droit", 1.0)
    if swing and float(swing) > 0:
        pattern = rhythm.swing(pattern, float(swing))
    pattern.name = clip.pattern.name
    clip.pattern = pattern
    return clip


def add_euclid(project: Project, uid: int, key: str, pulses: int,
               steps: int = 16, rotation: int = 0, row: str = "") -> str:
    """Ajoute à un clip de batterie une rangée euclidienne : ``pulses`` coups
    répartis au mieux sur ``steps`` pas, répétés sur toute la longueur du
    clip. Rend le nom de la rangée — « E(5,16) » à défaut d'un autre.

    Sur la carte, une rangée que le kit n'a pas reçoit une percussion de la
    bibliothèque (:func:`songwriter.drum_kit_for`).
    """
    clip = _drum_clip(project, uid, key)
    steps = max(1, int(steps))
    cells = rhythm.euclid(max(0, int(pulses)), steps, int(rotation) % steps)
    name = row or ("E(%d,%d)" % (int(pulses), steps)
                   + ("+%d" % (int(rotation) % steps) if int(rotation) % steps
                      else ""))
    hits = []
    for offset in range(0, clip.steps, steps):
        for index, on in enumerate(cells):
            if on and offset + index < clip.steps:
                hits.append(rhythm.Step(pos=offset + index, velocity=100))
    clip.pattern.tracks[name] = hits
    return name


# --------------------------------------------------------------------------- #
# La structure : du clip au morceau
# --------------------------------------------------------------------------- #

#: Variation de la batterie selon le rôle de la section.
_DRUM_FOR_KIND = {"intro": "légère", "fin": "légère", "cassure": "cassure",
                  "pic": "ornements"}


def default_sections(project: Project) -> list[AtelierSection]:
    """La structure du genre (:data:`sketch.ARRANGEMENTS`), remplie.

    Chaque section reçoit les parties que son rôle appelle — l'intro sans
    basse, la cassure sans grosse caisse, le sommet avec tout — et la
    batterie y joue la variation qui convient (légère, cassure, ornée). Un
    second sommet fait répondre la mélodie et relance la basse : le morceau
    se développe au lieu de se répéter.
    """
    plan = sketch.plan(project.style.genre, melody=True)
    created: dict[tuple[int, str], str] = {}

    def variant(track: AtelierTrack, how: str) -> str:
        cle = (track.uid, how)
        if cle not in created:
            base = track.clips[0].key
            clip = vary_clip(project, track.uid, base, how,
                             seed=random.Random(f"{project.style.seed}|"
                                                f"{track.uid}|{how}")
                             .randrange(1 << 30))
            created[cle] = clip.key
        return created[cle]

    peaks = 0
    sections: list[AtelierSection] = []
    for planned in plan:
        section = AtelierSection(name=planned.name, kind=planned.kind,
                                 bars=int(planned.bars))
        if planned.kind == "pic":
            peaks += 1
        for track in project.tracks:
            if not track.clips:
                continue
            first = track.clips[0].key
            if track.is_drums:
                if "Batterie" in planned.parts or \
                        "Batterie légère" in planned.parts \
                        or planned.kind == "cassure":
                    how = _DRUM_FOR_KIND.get(planned.kind)
                    section.cells[track.uid] = variant(track, how) if how \
                        else first
                continue
            if track.part not in planned.parts:
                continue
            key = first
            if planned.kind == "pic" and peaks >= 2:
                if track.part == "Mélodie":
                    key = variant(track, "réponse")
                elif track.part == "Basse":
                    key = variant(track, "plus")
            section.cells[track.uid] = key
        sections.append(section)
    return sections


def new_project(style: Style, kinds: dict[str, str] | None = None, *,
                sd=None, lib=None, structure: bool = True) -> Project:
    """Un projet prêt à écouter : une progression, une piste par partie,
    un premier clip chacune, et la structure du genre.

    :param kinds: partie -> nature de piste (``{"Basse": "midi"}`` pour
        jouer la basse sur un synthé extérieur) ; par défaut, un kit et des
        synthés — batterie, basse, accords, mélodie, et l'arpège si le genre
        en a l'habitude.
    """
    project = Project(style=style)
    project.progression = _progression(style)
    wanted = ["Batterie", "Basse", "Accords", "Mélodie"]
    if accomp.genre_styles(style.genre)[2]:
        wanted.insert(3, "Arpège")
    channel = {"midi": 1, "cv": 1}
    for part in wanted:
        kind = (kinds or {}).get(part, "kit" if part == "Batterie"
                                 else "synth")
        if part not in parts_for_kind(kind):
            continue
        number = channel.get(kind, 1)
        if kind in channel:
            channel[kind] = number + 1
        add_track(project, kind, part, channel=number, sd=sd, lib=lib)
    if structure:
        project.sections = default_sections(project)
    return project


# --------------------------------------------------------------------------- #
# Les sons
# --------------------------------------------------------------------------- #

def regenerate_sound(project: Project, uid: int,
                     seed: int | None = None) -> None:
    """Un autre son du même style pour un synthé."""
    track = project.track(uid)
    if track is None or track.kind != "synth":
        return
    new_seed = int(seed if seed is not None
                   else random.randrange(1 << 30))
    track.options, track.preset = _sound_for(project.style, track.part,
                                             new_seed)
    track.edited = False


def sound_variations(project: Project, uid: int, n: int = 8,
                     seed: int | None = None) -> list[synthgen.Variant]:
    """Variantes du son d'un synthé, **dans le style** : un aspect tiré à
    nouveau ou un curseur poussé (:func:`synthgen.style_variations`).

    Un son retouché à la main garde ses retouches dans chaque variante
    (:func:`.soundedit.carry_edits`) : la variante lui change ce qu'elle
    change au son généré, et rien d'autre. Celle que les retouches rendent
    identique au son — la coupure déjà au maximum pour « Plus brillant » —
    est écartée, et la suivante prend sa place."""
    track = project.track(uid)
    if track is None or track.options is None:
        return []
    if not track.edited or track.preset is None:
        out = synthgen.style_variations(track.options, n, seed=seed)
        for variant in out:
            _arp_off(variant.preset.sound)
        return out
    from .sdcard import safe_deluge_name
    from .soundedit import carry_edits

    start = _generate(track.options).sound
    edited = track.preset.sound
    # Le nom donné à la main, sans le numéro d'une variante adoptée.
    base = re.sub(r"\s+\d{1,2}$", "", edited.name or "").strip() \
        or track.options.name
    spare = len(synthgen.VARIABLE_FACETS) + len(synthgen.NUDGES) // 2
    out: list[synthgen.Variant] = []
    for variant in synthgen.style_variations(track.options, max(n, spare),
                                             seed=seed):
        if len(out) >= n:
            break
        sound = carry_edits(start, edited, variant.preset.sound)
        _arp_off(sound)
        probe = copy.copy(sound)
        probe.name = edited.name
        if probe == edited:
            continue
        sound.name = safe_deluge_name("%s %d" % (base[:56], len(out) + 2))
        variant.preset.sound = sound
        variant.preset.name = sound.name
        variant.retouched = True
        out.append(variant)
    return out


def adopt_sound(project: Project, uid: int,
                choice: synthgen.Variant) -> None:
    """La piste prend le son d'une variante — et les retouches qu'elle
    porte."""
    track = project.track(uid)
    if track is None:
        return
    track.options = choice.options
    track.preset = choice.preset
    track.edited = choice.retouched


def edit_sound(project: Project, uid: int, sound) -> bool:
    """La piste prend le son ``sound``, retouché à la main
    (:mod:`.soundedit`). Seule une piste neuve de synthé se retouche : le
    son d'une piste du morceau d'origine lui appartient, et compléter le
    morceau ne réécrit rien de ce qu'il contient."""
    track = project.track(uid)
    if (track is None or track.kind != "synth" or track.preset is None
            or track.existing is not None):
        return False
    preset = copy.deepcopy(track.preset)
    preset.sound = copy.deepcopy(sound)
    if sound.name:
        preset.name = sound.name
    track.preset = preset
    track.edited = True
    return True


# --------------------------------------------------------------------------- #
# Écouter
# --------------------------------------------------------------------------- #

def clip_parts(project: Project, uid: int, key: str
               ) -> tuple[dict, rhythm.Pattern | None, int]:
    """Ce qu'il faut pour écouter un clip seul : ``(parties, batterie,
    mesures)``."""
    track = project.track(uid)
    clip = track.clip(key) if track is not None else None
    if clip is None:
        return {}, None, 0
    if track.is_drums:
        return {}, clip.pattern, clip.bars
    return {_part_key(track): list(clip.events)}, None, clip.bars


def _part_key(track: AtelierTrack) -> str:
    # Deux pistes peuvent jouer la même partie : la clé d'écoute est unique.
    return "%s#%d" % (track.part, track.uid)


def section_parts(project: Project, index: int, max_bars: int = 8
                  ) -> tuple[dict, rhythm.Pattern | None, int]:
    """Le début d'une section, toutes pistes ensemble : ``(parties, batterie,
    mesures)``. Chaque clip boucle sur la durée écoutée."""
    if not 0 <= int(index) < len(project.sections):
        return {}, None, 0
    section = project.sections[int(index)]
    bars = max(1, min(int(max_bars), int(section.bars)))
    steps = bars * STEPS_PER_BAR
    parts: dict[str, list[NoteEvent]] = {}
    drums: rhythm.Pattern | None = None
    for track in project.tracks:
        key = section.cells.get(track.uid)
        clip = track.clip(key) if key else None
        if clip is None:
            continue
        if track.is_drums and clip.pattern is not None:
            looped = rhythm.loop(clip.pattern, bars)
            if drums is None:
                drums = looped
            else:
                for name, hits in looped.tracks.items():
                    drums.tracks.setdefault(name, []).extend(hits)
            continue
        events: list[NoteEvent] = []
        for offset in range(0, steps, clip.steps):
            for event in clip.events:
                start = event.start + offset
                if start < steps:
                    events.append(NoteEvent(start, event.length, event.note,
                                            event.velocity))
        parts[_part_key(track)] = events
    return parts, drums, bars


def fullest_section(project: Project) -> int:
    """La section où jouent le plus de pistes — la plus longue à égalité :
    celle qui donne le mieux l'idée du morceau. -1 sans section."""
    best, best_key = -1, None
    for index, section in enumerate(project.sections):
        playing = sum(1 for track in project.tracks
                      if section.cells.get(track.uid)
                      and track.clip(section.cells[track.uid]) is not None)
        key = (playing, int(section.bars), -index)
        if playing and (best_key is None or key > best_key):
            best, best_key = index, key
    return best


#: Ordre des rangées d'un kit quand rien d'autre ne le dit : celui des
#: rôles de la machine, de la grosse caisse aux percussions.
_DRUM_ORDER = ("Kick", "Snare", "Clap", "HatC", "HatO", "Rim", "TomL",
               "TomM", "TomH", "Crash", "Ride", "Shaker", "Cowbell", "Block",
               "Claves", "Tambourine", "ConL", "ConM", "ConH", "Guiro",
               "China", "Timpany")


def drum_rows(track: AtelierTrack) -> list[str]:
    """Pistes du motif dans l'ordre des rangées que la machine leur donne.

    MIDI Follow joue la rangée *n* d'un clip de kit avec la note
    « Kit Root Note » + *n* (36 d'usine) — la rangée 0 en bas. Pour une piste
    du morceau, c'est l'ordre de son premier clip ; pour un kit bâti ici,
    celui de ses rangées ; à défaut, l'ordre des rôles de la machine.
    """
    if track.existing and track.existing.get("rows"):
        return list(track.existing["rows"])
    names = sorted({n for c in track.clips if c.pattern is not None
                    for n in c.pattern.tracks},
                   key=lambda n: (_DRUM_ORDER.index(n)
                                  if n in _DRUM_ORDER else 99, n))
    kit = track.kit
    if kit is not None and getattr(kit, "rows", None):
        from .songwriter import drum_rows as kit_rows

        mapping = kit_rows(names, kit)
        ordered = [""] * len(kit.rows)
        for name, index in mapping.items():
            if 0 <= index < len(ordered) and not ordered[index]:
                ordered[index] = name
        return ordered + [n for n in names if n not in ordered]
    return names


def live_notes(project: Project, uid: int, key: str, kit_root: int = 36
               ) -> tuple[list[tuple[float, float, int, int]], int]:
    """Un clip en notes à jouer sur la machine : ``(notes, pas)``.

    Les notes sont ``(début, durée, note, vélocité 1-127)`` ; une batterie
    joue chaque rangée par sa note MIDI Follow (:func:`drum_rows`).
    """
    track = project.track(uid)
    clip = track.clip(key) if track is not None else None
    if clip is None:
        return [], 0
    notes: list[tuple[float, float, int, int]] = []
    if track.is_drums:
        order = drum_rows(track)
        for name, steps in (clip.pattern.tracks
                            if clip.pattern is not None else {}).items():
            if name not in order:
                continue
            note = int(kit_root) + order.index(name)
            for step in steps:
                notes.append((float(step.pos), max(0.5, float(step.length)),
                              note, max(1, min(127, int(step.velocity)
                                                * 127 // 100))))
    else:
        for event in clip.events:
            notes.append((float(event.start), float(event.length),
                          int(event.note),
                          max(1, min(127, int(event.velocity) * 127 // 100))))
    return notes, clip.steps


def listen_sounds(project: Project) -> dict:
    """Le son de chaque partie, pour :func:`render.render_parts` : celui de
    la piste, ou un son généré du style (piste MIDI ou CV, dont le vrai son
    est hors du Deluge)."""
    out = {}
    for track in project.tracks:
        if track.is_drums:
            continue
        preset = track.preset
        if preset is None:
            _opts, preset = _sound_for(project.style, track.part,
                                       int(project.style.seed) + track.uid)
        out[_part_key(track)] = preset.sound
    return out


# --------------------------------------------------------------------------- #
# Écrire un morceau neuf
# --------------------------------------------------------------------------- #

def to_song_spec(project: Project, name: str, sd=None, lib=None):
    """Le projet en morceau du Deluge (:class:`songwriter.SongSpec`).

    Une section du Deluge par section du projet ; dans chacune, le clip que
    chaque piste y joue, ramené à sa plus courte boucle exacte, et un nombre
    de répétitions qui couvre la durée de la section. L'arrangement place
    les mêmes clips sur toute la durée du morceau. Une piste qui ne joue
    dans aucune section n'est pas écrite.

    Lève ``ValueError`` (message pour l'utilisateur) si le projet ne
    s'écrit pas : aucune section, aucun clip, une batterie sans kit.
    """
    from . import songwriter

    if not project.sections:
        raise ValueError(tr("ajoutez au moins une section"))
    if len(project.sections) > songwriter.MAX_SECTIONS:
        raise ValueError(tr("le Deluge connaît %d sections au plus")
                         % songwriter.MAX_SECTIONS)
    used = [t for t in project.tracks
            if any(s.cells.get(t.uid) for s in project.sections)]
    if not used:
        raise ValueError(tr("aucune section ne joue de clip"))
    tracks: list = []
    index: dict[int, int] = {}
    row_maps: dict[int, dict] = {}
    for track in used:
        if track.kind == "synth":
            preset = track.preset
            if preset is None:
                _opts, preset = _sound_for(project.style, track.part,
                                           track.uid)
            built = songwriter.synth_track(preset, arp=False)
        elif track.kind == "kit":
            names = sorted({n for c in track.clips if c.pattern is not None
                            for n in c.pattern.tracks})
            kit, mapping, lost = (None, {}, names)
            if sd is not None:
                # Un kit ancien de la carte est converti avant d'être
                # complété : ses bornes en millisecondes deviennent des
                # trames, que la machine lit dans un morceau c1.2.1.
                kit, mapping, lost = songwriter.drum_kit_for(
                    sd, lib, project.style.genre, names,
                    base=songwriter.current_kit(track.kit, sd))
            if kit is None:
                raise ValueError(tr("la batterie n'a pas de kit : branchez "
                                    "la carte, ou choisissez un kit"))
            if lost:
                log.info("pistes de batterie sans son : %s", ", ".join(lost))
            built = songwriter.kit_track(kit, sd=sd)
            row_maps[track.uid] = mapping
        elif track.kind == "midi":
            built = songwriter.midi_track(track.channel)
        else:
            built = songwriter.cv_track(track.channel)
        index[track.uid] = len(tracks)
        tracks.append(built)

    clips = []
    for number, section in enumerate(project.sections):
        span = int(section.bars) * songwriter.BAR
        for track in used:
            key = section.cells.get(track.uid)
            clip = track.clip(key) if key else None
            if clip is None:
                continue
            length = clip.bars * songwriter.BAR
            if track.is_drums:
                rows, length = songwriter.pattern_rows(
                    clip.pattern, row_maps.get(track.uid, {}), length=length)
            else:
                rows = songwriter.events_to_rows(clip.events, length)
            if not rows:
                continue
            rows, length = songwriter.fold(rows, length)
            if length > span:
                length = span
            clips.append(songwriter.ClipSpec(
                track=index[track.uid], length=length, rows=rows,
                section=number, playing=number == 0,
                name="%s %s" % (tr(section.name),
                                songwriter.part_label(track.part))))
    if not clips:
        raise ValueError(tr("aucune section ne joue de clip"))
    key_root, mode = songwriter.key_of(project.style.root,
                                       project.style.scale)
    summary = [tr("Style : %s, %s") % (project.style.genre,
                                       theory.note_to_name(
                                           project.style.root,
                                           with_octave=False)
                                       + " " + tr(project.style.scale))]
    for track in used:
        summary.append(tr("%s : %d clip(s)") % (
            track_label(track),
            len({s.cells.get(track.uid) for s in project.sections
                 if s.cells.get(track.uid)})))
    return songwriter.SongSpec(
        name=name, bpm=project.style.tempo(), root=key_root, mode_notes=mode,
        tracks=tracks, clips=clips, summary=summary,
        sections=[songwriter.SectionSpec(s.name, int(s.bars) * songwriter.BAR)
                  for s in project.sections])


# --------------------------------------------------------------------------- #
# Exporter en MIDI
# --------------------------------------------------------------------------- #

def arrangement_parts(project: Project) -> tuple[dict, list[tuple[float, str]]]:
    """Le morceau entier, piste par piste, en notes — de quoi écrire un
    fichier MIDI : ``({partie: [NoteEvent]}, [(pas, section)])``.

    Chaque section, dans l'ordre, fait boucler le clip de chaque piste sur
    toute sa durée ; la batterie passe en notes General MIDI, sur le canal
    des percussions. Deux pistes de même partie prennent deux noms.
    """
    names: dict[int, str] = {}
    for track in project.tracks:
        name, number = track.part, 2
        while name in names.values():
            name = "%s %d" % (track.part, number)
            number += 1
        names[track.uid] = name
    parts: dict[str, list[NoteEvent]] = {}
    markers: list[tuple[float, str]] = []
    offset = 0
    for section in project.sections:
        steps = int(section.bars) * STEPS_PER_BAR
        markers.append((float(offset), tr(section.name)))
        for track in project.tracks:
            key = section.cells.get(track.uid)
            clip = track.clip(key) if key else None
            if clip is None:
                continue
            events = parts.setdefault(names[track.uid], [])
            if track.is_drums:
                if clip.pattern is None:
                    continue
                for event in accomp.drum_part(clip.pattern, int(section.bars)):
                    if event.start < steps:
                        events.append(NoteEvent(offset + event.start,
                                                event.length, event.note,
                                                event.velocity))
                continue
            for start in range(0, steps, max(1, clip.steps)):
                for event in clip.events:
                    if start + event.start < steps:
                        events.append(NoteEvent(offset + start + event.start,
                                                event.length, event.note,
                                                event.velocity))
        offset += steps
    return {k: sorted(v, key=lambda e: (e.start, e.note))
            for k, v in parts.items() if v}, markers


def export_midi(project: Project, path) -> int:
    """Écrit le morceau entier dans un fichier MIDI : une piste par piste du
    projet, le nom des sections en repères. Rend le nombre de pistes."""
    from pathlib import Path

    from . import midifile

    parts, markers = arrangement_parts(project)
    if not parts:
        raise ValueError(tr("aucune section ne joue de clip"))
    return midifile.parts_to_midi(Path(path), parts, project.style.tempo(),
                                  markers=markers)


# --------------------------------------------------------------------------- #
# Les sons de la bibliothèque et du générateur
# --------------------------------------------------------------------------- #

#: La partie que joue un son, d'après son rôle dans le générateur ou sa
#: catégorie dans la bibliothèque.
_ROLE_PARTS = {"bass": "Basse", "sub": "Basse", "lead": "Mélodie",
               "pad": "Accords", "keys": "Accords", "stab": "Accords",
               "drone": "Accords", "pluck": "Arpège", "arp": "Arpège",
               "fx": "Mélodie", "bell": "Mélodie"}


def part_for(role: str) -> str:
    """« Basse » pour une basse, « Accords » pour une nappe… ; « Mélodie »
    pour ce qui n'est pas reconnu."""
    return _ROLE_PARTS.get(str(role or "").strip().casefold(), "Mélodie")


def use_preset(project: Project, preset, part: str = "",
               uid: int | None = None, options=None,
               edited: bool = False) -> AtelierTrack:
    """Un son venu d'ailleurs — un preset de la carte, un son du générateur —
    prend place dans le projet.

    Il va à la piste ``uid`` si c'est un synthé neuf ; à défaut, au premier
    synthé neuf qui joue ``part`` ; à défaut, à une piste neuve, avec son
    premier clip. ``options`` — les réglages du générateur qui l'ont fait —
    permettent ensuite d'en tirer des variantes dans le style.
    """
    part = part if part in parts_for_kind("synth") else "Mélodie"
    track = project.track(uid) if uid is not None else None
    if track is None or track.kind != "synth" or track.existing is not None:
        track = next((t for t in project.tracks
                      if t.kind == "synth" and t.part == part
                      and t.existing is None), None)
    if track is None:
        track = add_track(project, "synth", part)
    preset = copy.deepcopy(preset)
    if options is not None:
        # L'arpège s'écrit note par note : l'arpégiateur d'un son du
        # générateur jouerait par-dessus (cf. :func:`_generate`).
        _arp_off(preset.sound)
    track.preset = preset
    track.options = copy.deepcopy(options) if options is not None else None
    track.edited = bool(edited)
    return track


def use_kit(project: Project, kit, uid: int | None = None) -> AtelierTrack:
    """Un kit — de la carte ou du générateur — devient la batterie : celle de
    la piste ``uid``, à défaut la première batterie neuve, à défaut une
    piste neuve avec son premier clip."""
    track = project.track(uid) if uid is not None else None
    if track is None or not track.is_drums or track.existing is not None:
        track = next((t for t in project.tracks
                      if t.is_drums and t.existing is None), None)
    if track is None:
        track = add_track(project, "kit", "Batterie")
    track.kit = copy.deepcopy(kit)
    return track


# --------------------------------------------------------------------------- #
# Partir d'un morceau de la carte
# --------------------------------------------------------------------------- #

def infer_progression(events, root: int, scale: str, bars: int
                      ) -> list[dict]:
    """La progression d'une partie, mesure par mesure.

    Pour chaque mesure, l'accord diatonique de la gamme qui couvre le mieux
    les notes qui y sonnent — pondérées par leur durée, la note la plus grave
    comptant double (c'est souvent la fondamentale). Rend des accords au
    format de :func:`theory.progression`, prêts pour l'accompagnement et
    les variations.
    """
    triads = theory.diatonic_chords(int(root), scale)
    sevenths = theory.diatonic_chords(int(root), scale, sevenths=True)
    if not triads:
        return []
    # Triades et septièmes : sans les secondes, un Fa maj7 (fa la do mi) se
    # lisait La mineur, qui en couvre trois notes sur quatre.
    candidates = [(i, "triades", {int(n) % 12 for n in notes})
                  for i, (_s, notes) in enumerate(triads)]
    candidates += [(i, "septièmes", {int(n) % 12 for n in notes})
                   for i, (_s, notes) in enumerate(sevenths)
                   if i < len(triads)]
    out: list[dict] = []
    for bar in range(max(1, int(bars))):
        first, last = bar * STEPS_PER_BAR, (bar + 1) * STEPS_PER_BAR
        weights = [0.0] * 12
        inside = [e for e in events or () if first <= e.start < last]
        for event in inside:
            weights[int(event.note) % 12] += max(0.25, float(event.length))
        if inside:
            lowest = min(inside, key=lambda e: e.note)
            weights[int(lowest.note) % 12] += max(0.25, float(lowest.length))
        if not inside and out:
            out.append(dict(out[-1]))
            continue
        best = None
        for index, colour, classes in candidates:
            score = sum(weights[c] for c in classes) \
                - 0.5 * sum(w for c, w in enumerate(weights)
                            if c not in classes)
            # À score égal, l'accord le plus simple : une triade jouée n'est
            # pas une septième dont on aurait oublié la septième.
            silent = sum(1 for c in classes if weights[c] <= 0)
            key = (score - 0.01 * silent, -len(classes))
            if best is None or key > best[0]:
                best = (key, index, colour)
        _key, index, colour = best
        # L'accord tel que le décrit une progression de la Boîte à outils :
        # nom, basse, fonction, voix conduites depuis le précédent.
        previous = out[-1]["notes"] if out else []
        out.append(theory._chord_entry(int(root), scale, index, colour,
                                       previous))
    return out


def _scale_of(song) -> str:
    """Nom de gamme de l'application pour les ``modeNotes`` d'un morceau."""
    from .model import SCALE_MODES

    intervals = tuple(sorted({int(n) % 12 for n in song.mode_notes or ()}))
    # Une gamme libre (« USER ») que l'application ne nomme pas : majeur,
    # le défaut de la machine.
    return SCALE_MODES.get(intervals) or (
        "chromatique" if len(intervals) == 12 else "majeur")


def _guess_part(clips) -> str:
    """Partie que joue une piste mélodique, d'après les notes de ses clips.

    Les attaques se comptent **clip par clip** : trois clips de mélodie aux
    mêmes temps, mis ensemble, passaient pour des accords de trois notes.
    """
    events = [e for clip in clips for e in clip.events]
    if not events:
        return "Mélodie"
    pitches = sorted(e.note for e in events)
    median = pitches[len(pitches) // 2]
    onsets = chords = 0
    for clip in clips:
        groups: dict[float, int] = {}
        for event in clip.events:
            groups[round(event.start, 2)] = groups.get(
                round(event.start, 2), 0) + 1
        onsets += len(groups)
        chords += sum(1 for size in groups.values() if size >= 3)
    if chords >= max(1, onsets // 3):
        return "Accords"
    if median < 52:
        return "Basse"
    short = sum(1 for e in events if e.length <= 1.0)
    if len(events) >= 24 and short >= len(events) * 0.7:
        return "Arpège"
    return "Mélodie"


def _kit_row_names(song_root: ET.Element, name: str, folder: str
                   ) -> list[str]:
    """Noms des rangées du kit ``name`` dans le morceau, dans l'ordre."""
    instruments = song_root.find("instruments")
    for el in (instruments if instruments is not None else []):
        if el.tag != "kit":
            continue
        if (el.get("presetName") or "").casefold() != (name or "").casefold():
            continue
        sources = el.find("soundSources")
        out = []
        for sound in (sources if sources is not None else []):
            label = sound.get("name")
            if label is None:
                child = sound.find("name")
                label = child.text if child is not None else ""
            out.append((label or "").strip() or "?")
        return out
    return []


def _unique(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for raw in names:
        base = raw or "?"
        count = seen.get(base, 0)
        seen[base] = count + 1
        out.append(base if not count else "%s %d" % (base, count + 1))
    return out


def from_song(song, sd=None) -> Project:
    """Un projet qui part d'un morceau de la carte.

    Les pistes du morceau (synthés, kits, MIDI, CV — les pistes audio n'ont
    rien à varier) deviennent celles du projet, chacune avec ses clips ; les
    sections du morceau deviennent celles du projet. Tempo et gamme sont
    ceux du morceau ; la progression est lue dans ses notes. Le genre, que
    le fichier ne dit pas, reste celui qu'on choisira.
    """
    from .model import Song

    if not isinstance(song, Song):
        raise ValueError(tr("morceau illisible"))
    scale = _scale_of(song)
    root = 48 + int(song.root_note) % 12
    project = Project(style=Style(bpm=float(song.tempo_bpm or 120.0),
                                  root=root, scale=scale),
                      song_rel="", song_name=song.name or "",
                      song_firmware=song.firmware or "")
    if song.path is not None and sd is not None:
        try:
            project.song_rel = sd.rel(song.path)
        except Exception:            # noqa: BLE001 - un nom suffit
            project.song_rel = ""
    ticks = float(max(1, song.ticks_per_bar))
    per_step = ticks / STEPS_PER_BAR
    doc_root = song.doc.root if song.doc is not None else None

    groups: dict[tuple, list[tuple[int, object]]] = {}
    order: list[tuple] = []
    for index, clip in enumerate(song.clips):
        if clip.kind == "audio":
            continue
        if clip.kind in ("midi", "cv"):
            key = (clip.kind, "", "", clip.channel, clip.suffix)
        else:
            key = (clip.kind, (clip.preset_name or "").casefold(),
                   (clip.preset_folder or "").casefold(), -1, -1)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append((index, clip))

    section_keys: dict[int, AtelierSection] = {}
    for key in order:
        kind, _name, _folder, channel, _suffix = key
        members = groups[key]
        first = members[0][1]
        atelier_kind = {"sound": "synth", "kit": "kit", "midi": "midi",
                        "cv": "cv"}.get(kind, "synth")
        track = AtelierTrack(uid=project.new_uid(), kind=atelier_kind,
                             part="Batterie" if kind == "kit" else "Mélodie",
                             channel=(channel + 1) if channel >= 0 else 1,
                             existing={"kind": kind,
                                       "name": first.preset_name,
                                       "folder": first.preset_folder,
                                       "channel": channel,
                                       "suffix": _suffix})
        if kind == "kit" and doc_root is not None:
            rows = _unique(_kit_row_names(doc_root, first.preset_name,
                                          first.preset_folder))
        else:
            rows = []
        for clip_index, clip in members:
            bars = max(1, int(round(clip.length / ticks))) or 1
            atelier = AtelierClip(key=next_key(track), bars=bars,
                                  origin=N_("morceau"), existing=clip_index)
            if kind == "kit":
                pattern = rhythm.Pattern(name=first.preset_name or "",
                                         steps=bars * STEPS_PER_BAR)
                if "rows" not in track.existing:
                    # L'ordre des rangées du premier clip : c'est par lui
                    # que MIDI Follow désigne un son (note 36 = la rangée
                    # du bas), pas par l'ordre des sons du kit.
                    track.existing["rows"] = [
                        rows[r.drum_index] if r.drum_index is not None
                        and 0 <= r.drum_index < len(rows) else ""
                        for r in clip.note_rows]
                for row_index, row in enumerate(clip.note_rows):
                    # Une rangée joue le son ``drumIndex`` du kit, quelle
                    # que soit sa place : l'utilisateur a pu les déplacer.
                    drum = row.drum_index if row.drum_index is not None \
                        else row_index
                    label = rows[drum] if 0 <= drum < len(rows) \
                        else tr("Rangée %d") % (drum + 1)
                    for note in row.notes:
                        pattern.add(label, rhythm.Step(
                            pos=float(note.pos) / per_step,
                            velocity=max(1, min(100, int(note.velocity)
                                                * 100 // 127)),
                            length=max(1, int(round(note.length
                                                    / per_step)))))
                atelier.pattern = pattern
            else:
                for row in clip.note_rows:
                    for note in row.notes:
                        atelier.events.append(NoteEvent(
                            float(note.pos) / per_step,
                            max(0.25, float(note.length) / per_step),
                            int(row.y),
                            max(1, min(100, int(note.velocity) * 100 // 127))))
                atelier.events.sort(key=lambda e: (e.start, e.note))
            track.clips.append(atelier)
            section = section_keys.get(clip.section)
            if section is None:
                section = AtelierSection(
                    name=tr("Section %d") % (int(clip.section) + 1),
                    kind="montée", bars=bars, existing=int(clip.section))
                section_keys[clip.section] = section
            section.bars = max(section.bars, bars)
            section.cells.setdefault(track.uid, atelier.key)
        if kind != "kit":
            track.part = _guess_part(track.clips)
            if kind == "cv" and track.part == "Accords":
                track.part = "Mélodie"
        if kind == "sound" and sd is not None:
            track.preset = _card_preset(sd, first.preset_name,
                                        first.preset_folder)
        elif kind == "kit" and sd is not None:
            track.kit = _card_kit(sd, first.preset_name, first.preset_folder)
        track.name = first.preset_name or ""
        project.tracks.append(track)
    project.sections = [section_keys[k] for k in sorted(section_keys)]
    # La progression : la partie la plus harmonique d'abord.
    for wanted in ("Accords", "Basse", "Arpège", "Mélodie"):
        candidates = [t for t in project.tracks if t.part == wanted
                      and t.clips and t.clips[0].events]
        if candidates:
            clip = max(candidates[0].clips, key=lambda c: c.note_count)
            project.progression = infer_progression(
                clip.events, project.style.root, scale, clip.bars)
            break
    if not project.progression:
        project.progression = _progression(project.style)
    return project


def _card_preset(sd, name: str, folder: str):
    from .model import SynthPreset
    from .songpack import find_preset

    try:
        rel = find_preset(sd, "sound", name, folder)
        return SynthPreset.load(sd.abs(rel)) if rel else None
    except Exception as exc:          # noqa: BLE001 - l'écoute s'en passe
        log.debug("preset %s introuvable : %s", name, exc)
        return None


def _card_kit(sd, name: str, folder: str):
    from .model import Kit
    from .songpack import find_preset

    try:
        rel = find_preset(sd, "kit", name, folder)
        return Kit.load(sd.abs(rel)) if rel else None
    except Exception as exc:          # noqa: BLE001
        log.debug("kit %s introuvable : %s", name, exc)
        return None


# --------------------------------------------------------------------------- #
# Compléter le morceau d'origine
# --------------------------------------------------------------------------- #

def _target_track(target, track: AtelierTrack) -> int:
    """Rang de la piste du morceau d'origine que ``track`` désigne."""
    info = track.existing or {}
    kind = info.get("kind")
    for index, candidate in enumerate(target.tracks):
        if candidate.kind != kind:
            continue
        if kind in ("midi", "cv"):
            if candidate.channel == info.get("channel") and (
                    kind == "cv" or candidate.suffix == info.get("suffix")):
                return index
        elif candidate.name.casefold() == (info.get("name") or "").casefold():
            return index
    return -1


def _rows_for(target_bar: int, rows: dict, length: int) -> tuple[dict, int]:
    """Rangées en ticks d'un morceau à 384 par mesure -> ticks du morceau
    d'origine (192 par mesure dans un morceau 3.x ou « Cool1 »)."""
    from . import songwriter
    from .model import Note

    if target_bar == songwriter.BAR:
        return rows, length
    ratio = target_bar / float(songwriter.BAR)
    out = {}
    new_length = max(1, int(round(length * ratio)))
    for y, notes in rows.items():
        scaled = [Note(pos=int(round(n.pos * ratio)),
                       length=max(1, int(round(n.length * ratio))),
                       velocity=n.velocity, condition=n.condition,
                       lift=n.lift) for n in notes]
        out[y] = songwriter._clean_notes(scaled, new_length)
    return {y: n for y, n in out.items() if n}, new_length


def insertion_plan(project: Project, sd, lib=None, name: str = ""):
    """Le plan du morceau d'origine complété par le projet
    (:mod:`songinsert`) — rien n'est écrit.

    Les sections du morceau restent telles quelles ; ce qui s'y ajoute, ce
    sont les clips des **nouvelles pistes**. Les sections neuves du projet
    prennent des numéros libres, et y vont les clips neufs comme les clips
    du morceau qu'elles reprennent (recopiés à l'identique). Un clip neuf
    d'une piste du morceau ne remplace jamais celui qu'elle a déjà dans une
    section : il faudrait réécrire le morceau.

    Rend ``(plan, remarques)``.
    """
    from . import songinsert, songwriter

    if not project.song_rel:
        raise ValueError(tr("ce projet ne part pas d'un morceau de la carte"))
    target = songinsert.read_target(sd, project.song_rel)
    if not target.ok:
        raise ValueError(target.reason)
    notes: list[str] = []
    free = target.free_sections()
    numbers: list[int] = []
    for section in project.sections:
        if section.existing is not None:
            numbers.append(int(section.existing))
        elif free:
            numbers.append(free.pop(0))
        else:
            raise ValueError(tr("le morceau n'a plus de section libre "
                                "(%d au plus)") % target.max_sections)

    new_tracks: list = []
    new_index: dict[int, int] = {}
    row_maps: dict[int, dict] = {}
    for track in project.tracks:
        if track.existing is not None:
            continue
        if not any(s.cells.get(track.uid) for s in project.sections):
            continue
        if track.kind == "synth":
            preset = track.preset
            if preset is None:
                _opts, preset = _sound_for(project.style, track.part,
                                           track.uid)
            built = songwriter.synth_track(preset, arp=False)
        elif track.kind == "kit":
            names = sorted({n for c in track.clips if c.pattern is not None
                            for n in c.pattern.tracks})
            kit, mapping, _lost = songwriter.drum_kit_for(
                sd, lib, project.style.genre, names,
                base=songwriter.current_kit(track.kit, sd))
            if kit is None:
                raise ValueError(tr("la batterie ajoutée n'a pas de kit"))
            built = songwriter.kit_track(kit, sd=sd)
            row_maps[track.uid] = mapping
        elif track.kind == "midi":
            built = songwriter.midi_track(track.channel)
        else:
            built = songwriter.cv_track(track.channel)
        new_index[track.uid] = len(new_tracks)
        new_tracks.append(built)

    clips: list = []
    repeats: dict[int, int] = {}
    for section, number in zip(project.sections, numbers):
        longest = 0
        for track in project.tracks:
            key = section.cells.get(track.uid)
            clip = track.clip(key) if key else None
            if clip is None:
                continue
            target_index = _target_track(target, track) \
                if track.existing is not None else -1
            if track.existing is not None and target_index < 0:
                notes.append(tr("%s : piste introuvable dans le morceau")
                             % track_label(track))
                continue
            label = "%s %s" % (tr(section.name),
                               songwriter.part_label(track.part))
            if track.existing is not None and clip.existing is not None:
                if target.clip_sections[clip.existing] == number:
                    longest = max(longest, clip.bars * target.bar)
                    continue                  # déjà là
                if section.existing is not None:
                    notes.append(tr("%s, %s : la piste y a déjà son clip ; "
                                    "il reste") % (tr(section.name),
                                                   track_label(track)))
                    continue
                clips.append(songinsert.NewClip(track=target_index,
                                                section=number,
                                                copy_of=clip.existing,
                                                name=label))
                longest = max(longest, clip.bars * target.bar)
                continue
            if track.existing is not None and section.existing is not None \
                    and number in target.tracks[target_index].sections:
                notes.append(tr("%s, %s : la piste y a déjà un clip ; le "
                                "nouveau irait dans une section neuve")
                             % (tr(section.name), track_label(track)))
                continue
            length = clip.bars * songwriter.BAR
            if track.is_drums:
                if track.existing is not None:
                    drums = _unique(target.tracks[target_index].drums)
                    mapping = {n: i for i, n in enumerate(drums)}
                else:
                    mapping = row_maps.get(track.uid, {})
                rows, length = songwriter.pattern_rows(clip.pattern, mapping,
                                                       length=length)
            else:
                rows = songwriter.events_to_rows(clip.events, length)
            if not rows:
                continue
            rows, length = songwriter.fold(rows, length)
            rows, length = _rows_for(target.bar, rows, length)
            clips.append(songinsert.NewClip(
                track=target_index, section=number, rows=rows,
                length=length, name=label,
                new_track=new_index.get(track.uid, -1)))
            longest = max(longest, length)
        if section.existing is None and longest:
            repeats[number] = max(1, int(round(
                int(section.bars) * target.bar / float(longest))))
    # La dernière section neuve tourne en boucle : la suite, en disposition
    # « rangées », serait la première section du morceau.
    fresh = [n for s, n in zip(project.sections, numbers)
             if s.existing is None and n in repeats]
    if fresh:
        repeats[fresh[-1]] = 0
    if not clips and not new_tracks:
        raise ValueError(tr("rien à ajouter : le projet ne contient que ce "
                            "que le morceau a déjà"))
    plan = songinsert.plan_insert(sd, target, new_tracks, clips, repeats,
                                  name=name)
    plan.lines.extend(notes)
    return plan, notes


def clone_project(project: Project) -> Project:
    """Copie indépendante (pour annuler, ou pour essayer)."""
    return copy.deepcopy(project)
