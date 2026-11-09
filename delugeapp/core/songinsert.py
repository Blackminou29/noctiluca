# -*- coding: utf-8 -*-
"""Ajouter des clips à un morceau du Deluge, sans rien en réécrire.

Le compositeur travaille sur la machine ; l'application lui propose des
clips — variations de ses clips, nouvelles pistes — qui doivent arriver
**dans son morceau**. Mais la règle de non-destruction tient : l'application
ne réécrit jamais un morceau (``core.model.Song`` est en lecture seule),
faute de pouvoir prouver qu'un aller-retour lecture/écriture est stable à
l'octet.

Ce module ne fait donc pas d'aller-retour. Il écrit un **nouveau fichier**,
numéroté comme le fait la machine (« Cool1 5 » après « Cool1 4 »), qui est
l'original **octet pour octet**, avec des ajouts :

* de nouvelles pistes, à la fin de ``<instruments>`` ;
* de nouveaux clips, à la fin de ``<sessionClips>`` — jamais au milieu :
  l'arrangement désigne les clips par leur rang (``clipInstances``), qui ne
  doit pas bouger ;
* des copies de clips du morceau dans de nouvelles sections, recopiées
  telles quelles, seul leur numéro de section changeant ;
* le nombre de répétitions des sections **neuves** (``numRepeats`` d'une
  section qu'aucun clip du morceau n'utilise).

Chaque écriture est **prouvée** : retirer les ajouts et défaire ces
remplacements redonne exactement les octets d'origine (:func:`verify`), et
le fichier obtenu se relit, chaque clip d'origine identique à lui-même.
L'original n'est jamais touché ; une écriture refusée par la preuve n'a pas
lieu.

Ce que le format impose, lu dans le code du firmware de la machine (1.3,
commit ``102cf9f``) :

* un morceau qui se déclare c1.3.0 ou plus récent ne lit ses notes que dans
  ``noteDataWithSplitProb`` (28 caractères par note) ; avant, dans
  ``noteDataWithLift`` (:func:`delugeapp.core.model.note_blob_tag`) ;
* en disposition « grille » (73 morceaux de l'utilisateur sur 136), une case
  piste × section ne montre **qu'un** clip : un nouveau clip d'une piste
  existante va donc dans une section où elle n'en a pas ;
* une mesure vaut ``96 << inputTickMagnitude`` ticks : 192 dans « Cool1 »,
  384 dans les morceaux écrits par l'application ;
* le firmware c1.2.1 connaît 12 sections, la 1.3 en connaît 24.
"""

from __future__ import annotations

import copy
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from ..i18n import tr
from . import dxml
from .model import Note, encode_notes, note_blob_tag, ticks_per_bar
from .sdcard import SDCard, check_name

log = logging.getLogger(__name__)

__all__ = ["SongTarget", "TargetTrack", "NewClip", "InsertPlan", "read_target",
           "plan_insert", "verify", "write_insert", "MIN_FIRMWARE"]

#: Plus ancien firmware dont on complète les morceaux : le communautaire
#: c1.2.0. Un morceau plus ancien se convertit en l'enregistrant une fois
#: sur la machine, qui l'écrit alors dans son format.
MIN_FIRMWARE = "c1.2.0"

#: Une balise et ses attributs entre guillemets — un ``>`` dans une valeur
#: ne la coupe pas.
_TAG = re.compile(rb'<(?P<close>/)?(?P<name>[A-Za-z_][\w.:-]*)'
                  rb'(?P<attrs>(?:\s+[^\s=/>]+\s*=\s*"[^"]*")*)\s*'
                  rb'(?P<self>/)?>')
_SKIP = re.compile(rb'<\?.*?\?>|<!--.*?-->', re.S)
_ATTR = re.compile(rb'\s([A-Za-z_][\w.:-]*)\s*=\s*"([^"]*)"')


# --------------------------------------------------------------------------- #
# Lire le morceau tel qu'il est écrit
# --------------------------------------------------------------------------- #

@dataclass
class _Span:
    """Un élément dans le fichier : ses octets, de ``start`` à ``end``."""

    name: str
    start: int
    end: int
    open_end: int
    attrs: dict[str, str]
    depth: int


def _elements(data: bytes) -> list[_Span]:
    """Tous les éléments du fichier, avec leur place exacte en octets."""
    skipped = [(m.start(), m.end()) for m in _SKIP.finditer(data)]

    def hidden(pos: int) -> bool:
        return any(a <= pos < b for a, b in skipped)

    out: list[_Span] = []
    stack: list[_Span] = []
    for match in _TAG.finditer(data):
        if hidden(match.start()):
            continue
        name = match.group("name").decode("latin-1")
        if match.group("close"):
            while stack:
                top = stack.pop()
                if top.name == name:
                    top.end = match.end()
                    break
            continue
        attrs = {k.decode("latin-1"): v.decode("utf-8", "replace")
                 for k, v in _ATTR.findall(match.group("attrs") or b"")}
        span = _Span(name, match.start(), match.end(), match.end(), attrs,
                     len(stack))
        out.append(span)
        if not match.group("self"):
            stack.append(span)
    return out


def _children(spans: list[_Span], parent: _Span) -> list[_Span]:
    return [s for s in spans if s.depth == parent.depth + 1
            and parent.start < s.start and s.end <= parent.end]


def _line_start(data: bytes, pos: int) -> int:
    return data.rfind(b"\n", 0, pos) + 1


def _indent_of(data: bytes, pos: int) -> int:
    start = _line_start(data, pos)
    count = 0
    while start + count < pos and data[start + count:start + count + 1] \
            == b"\t":
        count += 1
    return count


@dataclass
class TargetTrack:
    """Une piste du morceau : son instrument et ses clips."""

    index: int
    kind: str                    # sound | kit | midi | cv | audio
    name: str = ""
    folder: str = ""
    channel: int = -1
    suffix: int = -1
    clips: list[int] = field(default_factory=list)   # rangs de session
    #: Sections où la piste a déjà un clip.
    sections: set[int] = field(default_factory=set)
    #: Noms des sons d'un kit, dans l'ordre des rangées.
    drums: list[str] = field(default_factory=list)


@dataclass
class SongTarget:
    """Ce qu'il faut savoir d'un morceau pour le compléter."""

    rel: str
    data: bytes
    firmware: str
    magnitude: int
    layout: str
    tracks: list[TargetTrack]
    #: Section de chaque clip de session, dans l'ordre du fichier.
    clip_sections: list[int]
    #: Clé d'une piste pour chaque clip de session (rang dans ``tracks``).
    clip_tracks: list[int]
    max_sections: int
    root: int = 0
    mode_notes: tuple[int, ...] = ()
    reason: str = ""             # pourquoi on ne peut pas le compléter

    @property
    def ok(self) -> bool:
        return not self.reason

    @property
    def bar(self) -> int:
        return ticks_per_bar(self.magnitude)

    @property
    def used_sections(self) -> set[int]:
        return set(self.clip_sections)

    def free_sections(self) -> list[int]:
        used = self.used_sections
        return [s for s in range(self.max_sections) if s not in used]


def _kind_of_clip(span: _Span) -> tuple[str, tuple]:
    if span.name == "audioClip":
        return "audio", ("audio", span.attrs.get("trackName", ""))
    if "midiChannel" in span.attrs:
        return "midi", ("midi", int(span.attrs.get("midiChannel", 0)),
                        int(span.attrs.get("midiChannelSuffix", -1)))
    if "cvChannel" in span.attrs:
        return "cv", ("cv", int(span.attrs.get("cvChannel", 0)))
    name = span.attrs.get("instrumentPresetName", "").casefold()
    folder = span.attrs.get("instrumentPresetFolder", "").casefold()
    return "?", ("preset", name, folder)


def read_target(sd: SDCard, rel: str) -> SongTarget:
    """Lit un morceau de la carte pour le compléter ; ``reason`` dit pourquoi
    ce n'est pas possible, le cas échéant."""
    path = sd.abs(rel)
    data = path.read_bytes()
    doc = dxml.loads(data, path)
    firmware = doc.firmware or ""
    root = doc.root
    target = SongTarget(rel=rel, data=data, firmware=firmware,
                        magnitude=int(root.get("inputTickMagnitude") or 1),
                        layout=root.get("sessionLayout") or "",
                        tracks=[], clip_sections=[], clip_tracks=[],
                        max_sections=24 if not dxml.version_older(
                            firmware, "c1.3.0") else 12)
    try:
        target.root = int(root.get("rootNote") or 0) % 12
    except ValueError:
        target.root = 0
    modes = root.find("modeNotes")
    if modes is not None:
        target.mode_notes = tuple(int((m.text or "0").strip() or 0)
                                  for m in modes.findall("modeNote"))
    if root.tag != "song":
        target.reason = tr("ce fichier n'est pas un morceau")
        return target
    if doc.dialect != "attr" or doc.preamble:
        target.reason = tr("morceau d'un ancien firmware (format 2.x)")
        return target
    if dxml.version_older(firmware, MIN_FIRMWARE):
        target.reason = tr("morceau du firmware %s : enregistrez-le une fois "
                           "sur le Deluge, qui le convertit, puis "
                           "recommencez") % (firmware or "?")
        return target

    spans = _elements(data)
    song = next((s for s in spans if s.name == "song" and s.depth == 0), None)
    if song is None:
        target.reason = tr("structure du morceau illisible")
        return target
    top = {s.name: s for s in _children(spans, song)}
    if "instruments" not in top or "sessionClips" not in top:
        target.reason = tr("morceau sans instruments ni clips")
        return target
    if top["sessionClips"].end == top["sessionClips"].open_end \
            or top["instruments"].end == top["instruments"].open_end:
        target.reason = tr("morceau sans clip")
        return target

    keys: dict[tuple, int] = {}
    for index, inst in enumerate(_children(spans, top["instruments"])):
        kind = {"sound": "sound", "kit": "kit", "midi": "midi",
                "midiChannel": "midi", "mpeZone": "midi",
                "cvChannel": "cv", "audioTrack": "audio"}.get(inst.name)
        if kind is None:
            continue
        track = TargetTrack(index=index, kind=kind,
                            name=inst.attrs.get("presetName", "")
                            or inst.attrs.get("name", ""),
                            folder=inst.attrs.get("presetFolder", ""))
        if kind == "midi":
            track.channel = int(inst.attrs.get("channel", 0))
            track.suffix = int(inst.attrs.get("suffix", -1))
            key = ("midi", track.channel, track.suffix)
        elif kind == "cv":
            track.channel = int(inst.attrs.get("channel", 0))
            key = ("cv", track.channel)
        elif kind == "audio":
            key = ("audio", track.name)
        else:
            key = ("preset", track.name.casefold(), track.folder.casefold())
            if kind == "kit":
                track.drums = _drum_names(doc.root, track.name)
        keys.setdefault(key, len(target.tracks))
        target.tracks.append(track)

    for rank, clip in enumerate(_children(spans, top["sessionClips"])):
        _kind, key = _kind_of_clip(clip)
        owner = keys.get(key, -1)
        if owner < 0 and key[0] == "preset":
            # Le dossier d'un clip peut omettre la racine (« acid » pour
            # « SYNTHS/acid ») : le nom seul départage.
            owner = next((i for k, i in keys.items() if k[0] == "preset"
                          and k[1] == key[1]), -1)
        section = int(clip.attrs.get("section", 0) or 0)
        target.clip_sections.append(section)
        target.clip_tracks.append(owner)
        if owner >= 0:
            target.tracks[owner].clips.append(rank)
            target.tracks[owner].sections.add(section)
    return target


def _drum_names(song_root: ET.Element, name: str) -> list[str]:
    instruments = song_root.find("instruments")
    for el in (instruments if instruments is not None else []):
        if el.tag == "kit" and (el.get("presetName") or "").casefold() \
                == (name or "").casefold():
            sources = el.find("soundSources")
            out = []
            for sound in (sources if sources is not None else []):
                label = sound.get("name")
                if label is None and sound.find("name") is not None:
                    label = sound.find("name").text
                out.append((label or "").strip())
            return out
    return []


# --------------------------------------------------------------------------- #
# Ce qu'on ajoute
# --------------------------------------------------------------------------- #

@dataclass
class NewClip:
    """Un clip à ajouter.

    ``track`` est le rang d'une piste du morceau (:class:`TargetTrack`), ou
    ``-1`` pour une piste neuve, désignée alors par ``new_track`` (rang dans
    les pistes neuves). ``rows`` et ``length`` sont en ticks **du
    morceau** ; ``copy_of`` désigne un clip du morceau à recopier tel quel
    dans la section ``section``.
    """

    track: int
    section: int
    rows: dict[int, list[Note]] = field(default_factory=dict)
    length: int = 0
    name: str = ""
    new_track: int = -1
    copy_of: int | None = None


@dataclass
class InsertPlan:
    """Le plan d'un morceau complété : ce qui change, et les octets."""

    source: str = ""
    rel: str = ""
    lines: list[str] = field(default_factory=list)
    data: bytes = b""
    #: ``(position dans l'original, octets d'origine, octets écrits)`` :
    #: un ajout a des octets d'origine vides.
    edits: list[tuple[int, bytes, bytes]] = field(default_factory=list)
    error: str = ""
    added_tracks: int = 0
    added_clips: int = 0

    @property
    def ok(self) -> bool:
        return bool(self.rel) and not self.error

    def text(self) -> str:
        return "\n".join(self.lines)


def _strip_automation(el: ET.Element) -> None:
    """Un paramètre automatisé (``0x`` + valeur + couples position/valeur)
    garde sa seule valeur de départ : un clip neuf n'hérite pas des
    mouvements de bouton enregistrés dans le clip qui lui sert de modèle."""
    for node in el.iter():
        for key, value in list(node.attrib.items()):
            text = str(value)
            if text[:2].lower() == "0x" and len(text) > 10 \
                    and all(c in "0123456789abcdefABCDEF" for c in text[2:]):
                node.set(key, text[:10])


def _reference_clip(data: bytes, spans_clips: list[_Span], rank: int
                    ) -> ET.Element | None:
    span = spans_clips[rank]
    try:
        return ET.fromstring(data[span.start:span.end].decode("utf-8",
                                                               "replace"))
    except ET.ParseError:
        doc = dxml.loads(data[span.start:span.end])
        return doc.root


def _clip_from_reference(ref: ET.Element, clip: NewClip, tag: str,
                         width: int, track: TargetTrack) -> ET.Element:
    """Un clip neuf pour une piste du morceau, réglé comme un de ses clips."""
    el = ET.Element(ref.tag)
    for key, value in ref.attrib.items():
        el.set(key, value)
    el.set("clipName", _ascii(clip.name))
    el.set("isPlaying", "0")
    el.set("isSoloing", "0")
    el.set("length", str(int(clip.length)))
    el.set("section", str(int(clip.section)))
    for key in ("onKeyboardScreen", "onAutomationInstrumentClipView",
                "lastSelectedParamID", "lastSelectedParamKind",
                "lastSelectedParamShortcutX", "lastSelectedParamShortcutY",
                "lastSelectedInstrumentType", "lastSelectedPatchSource",
                "crossScreenEditLevel"):
        el.attrib.pop(key, None)
    ref_rows = ref.find("noteRows")
    for child in ref:
        if child.tag in ("noteRows", "expressionData", "midiParams"):
            continue
        kept = copy.deepcopy(child)
        _strip_automation(kept)
        el.append(kept)
    holder = ET.SubElement(el, "noteRows")
    if track.kind == "kit":
        # Les rangées dans l'ordre du clip modèle — l'utilisateur a pu les
        # déplacer sur la machine —, chacune jouant **son** son
        # (``drumIndex``) : ``clip.rows`` est indexé par son, pas par place.
        for position, model in enumerate(list(ref_rows) if ref_rows
                                         is not None else []):
            row = ET.SubElement(holder, "noteRow")
            row.set("colourOffset", model.get("colourOffset", "0"))
            try:
                drum = int(model.get("drumIndex", position))
            except ValueError:
                drum = position
            notes = clip.rows.get(drum)
            if notes:
                row.set(tag, encode_notes(notes, width=width))
            row.set("drumIndex", str(drum))
            params = model.find("soundParams")
            if params is not None:
                kept = copy.deepcopy(params)
                _strip_automation(kept)
                row.append(kept)
    else:
        for y in sorted(clip.rows):
            row = ET.SubElement(holder, "noteRow")
            row.set("y", str(int(y)))
            row.set(tag, encode_notes(clip.rows[y], width=width))
    if len(holder) == 0:
        el.remove(holder)
    return el


def _ascii(text: str) -> str:
    from .songwriter import ascii_label

    return ascii_label(text)


def _with_attrs(block: bytes, changes: dict[str, str]) -> bytes:
    """Les octets d'une balise ouvrante, quelques attributs changés."""
    out = block
    for key, value in changes.items():
        pattern = re.compile(rb'(\s' + re.escape(key.encode()) +
                             rb'\s*=\s*")[^"]*(")')
        if pattern.search(out):
            out = pattern.sub(lambda m: m.group(1) + value.encode() +
                              m.group(2), out, count=1)
    return out


_VERSION = re.compile(r"^(?P<base>.*\S)\s+(?P<n>\d{1,3})$")


def next_version(sd: SDCard, stem: str) -> str:
    """La version suivante d'un morceau, numérotée comme le fait la
    machine : « Cool1 5 » après « Cool1 4 » (la carte de l'utilisateur
    porte « Cool1 », « Cool1 2 »… « Cool1 4 »), « Calm Down 2 » après
    « Calm Down ». Jamais un nom pris.

    Le nom passe en ASCII (« dièse » → « diese ») : le câble perd le bit 7
    des noms (mesuré), et six morceaux de l'utilisateur portent un accent.
    """
    from .cardimport import card_name
    from .songwriter import free_song_name

    stem = card_name(stem or "")
    match = _VERSION.match(stem)
    if not match:
        return free_song_name(sd, stem)
    base, number = match.group("base"), int(match.group("n"))
    for candidate in range(number + 1, 1000):
        rel = "SONGS/%s %d.XML" % (base, candidate)
        if not sd.exists(rel):
            return rel
    raise ValueError(tr("trop de morceaux portent déjà ce nom"))


def _unique_name(name: str, folder: str, kind: str,
                 taken: set[tuple[str, str, str]]) -> str:
    base = name or ("KIT" if kind == "kit" else "SYNTH")
    candidate, index = base, 2
    while (kind, folder.upper(), candidate.upper()) in taken:
        candidate = "%s %d" % (base, index)
        index += 1
    taken.add((kind, folder.upper(), candidate.upper()))
    return candidate


def plan_insert(sd: SDCard, target: SongTarget, new_tracks: list,
                clips: list[NewClip], repeats: dict[int, int] | None = None,
                name: str = "") -> InsertPlan:
    """Le plan du morceau complété — **rien n'est écrit**.

    :param new_tracks: pistes neuves (:class:`songwriter.Track`).
    :param clips: clips à ajouter (:class:`NewClip`), dans l'ordre où les
        sections se suivent : ils s'écrivent à la fin des clips du morceau,
        le dernier en premier, pour qu'en disposition « rangées » la
        première section ajoutée soit en haut et enchaîne vers le bas.
    :param repeats: répétitions de chaque section **neuve**.
    """
    from . import songwriter

    plan = InsertPlan(source=target.rel)
    if not target.ok:
        plan.error = target.reason
        return plan
    data = target.data
    stem = name or Path(target.rel).stem
    try:
        plan.rel = next_version(sd, stem) if not name \
            else songwriter.free_song_name(sd, stem)
    except ValueError as exc:
        plan.error = str(exc)
        return plan
    problems = check_name(Path(plan.rel).stem)
    if problems:
        plan.error = " ".join(problems)
        return plan
    tag, width = note_blob_tag(target.firmware)
    spans = _elements(data)
    song = next(s for s in spans if s.name == "song" and s.depth == 0)
    top = {s.name: s for s in _children(spans, song)}
    session = _children(spans, top["sessionClips"])
    used = target.used_sections

    for clip in clips:
        if not 0 <= int(clip.section) < target.max_sections:
            plan.error = tr("le Deluge connaît %d sections au plus") \
                % target.max_sections
            return plan
        if clip.track >= 0 and target.layout == "1" \
                and clip.copy_of is None \
                and clip.section in target.tracks[clip.track].sections:
            plan.error = tr("la piste %s a déjà un clip dans la section %d : "
                            "en disposition grille, le nouveau y serait "
                            "caché") % (target.tracks[clip.track].name
                                        or target.tracks[clip.track].kind,
                                        clip.section + 1)
            return plan

    # -- pistes neuves -------------------------------------------------------- #
    taken = {(t.kind, t.folder.upper(), t.name.upper())
             for t in target.tracks}
    inst_depth = _indent_of(data, top["instruments"].start) + 1
    blocks: list[bytes] = []
    names: list[str] = []
    for track in new_tracks:
        if track.is_external:
            names.append(track.name)
            if track.kind == "midi":
                used_suffixes = [t.suffix for t in target.tracks
                                 if t.kind == "midi"
                                 and t.channel == track.channel]
                if used_suffixes:
                    track.suffix = max(used_suffixes) + 1
        else:
            names.append(_unique_name(track.name, track.folder, track.kind,
                                      taken))
        element = songwriter._instrument_element(track, names[-1], None)
        blocks.append(dxml.dump_element(element, inst_depth).encode("utf-8"))
    if blocks:
        at = _line_start(data, top["instruments"].end
                         - len(b"</instruments>"))
        plan.edits.append((at, b"", b"".join(blocks)))
        plan.added_tracks = len(blocks)

    # -- clips ------------------------------------------------------------------ #
    clip_depth = _indent_of(data, top["sessionClips"].start) + 1
    spec = songwriter.SongSpec(name=stem, root=target.root,
                               mode_notes=target.mode_notes or
                               (0, 2, 4, 5, 7, 9, 11),
                               tracks=list(new_tracks))
    out_blocks: list[bytes] = []
    for clip in reversed(clips):
        if clip.copy_of is not None:
            span = session[clip.copy_of]
            raw = data[span.start:span.end]
            head = _with_attrs(raw[:span.open_end - span.start],
                               {"section": str(int(clip.section)),
                                "isPlaying": "0"})
            block = head + raw[span.open_end - span.start:]
            indent = _indent_of(data, span.start)
            out_blocks.append(b"\t" * indent + block + b"\n")
        elif clip.track >= 0:
            track = target.tracks[clip.track]
            if not track.clips:
                plan.error = tr("la piste %s n'a aucun clip qui serve de "
                                "modèle") % (track.name or track.kind)
                return plan
            ref = _reference_clip(data, session, track.clips[0])
            element = _clip_from_reference(ref, clip, tag, width, track)
            out_blocks.append(dxml.dump_element(element, clip_depth)
                              .encode("utf-8"))
        else:
            spec_clip = songwriter.ClipSpec(
                track=clip.new_track, length=int(clip.length),
                rows=clip.rows, section=int(clip.section), name=clip.name,
                playing=False)
            colour = (clip.new_track * 13) % 72 - 60
            element = songwriter._clip_element(
                spec, spec_clip, names[clip.new_track], colour,
                blob=(tag, width), magnitude=target.magnitude)
            out_blocks.append(dxml.dump_element(element, clip_depth)
                              .encode("utf-8"))
    if out_blocks:
        at = _line_start(data, top["sessionClips"].end
                         - len(b"</sessionClips>"))
        plan.edits.append((at, b"", b"".join(out_blocks)))
        plan.added_clips = len(out_blocks)

    # -- répétitions des sections neuves ------------------------------------- #
    sections = top.get("sections")
    for number, count in sorted((repeats or {}).items()):
        if number in used:
            plan.error = tr("la section %d appartient déjà au morceau : sa "
                            "durée ne change pas") % (number + 1)
            return plan
        if sections is None:
            break
        entry = next((s for s in _children(spans, sections)
                      if s.name == "section"
                      and s.attrs.get("id") == str(number)), None)
        if entry is None:
            continue
        old = data[entry.start:entry.open_end]
        new = _with_attrs(old, {"numRepeats": str(max(0, int(count)))})
        if new != old:
            plan.edits.append((entry.start, old, new))

    plan.edits.sort(key=lambda e: e[0])
    pieces, cursor = [], 0
    for position, old, new in plan.edits:
        pieces.append(data[cursor:position])
        pieces.append(new)
        cursor = position + len(old)
    pieces.append(data[cursor:])
    plan.data = b"".join(pieces)
    plan.lines = _plan_lines(target, plan, new_tracks, clips, repeats or {})
    problem = verify(data, plan)
    if problem:
        plan.error = problem
    return plan


def verify(original: bytes, plan: InsertPlan) -> str:
    """Rend ``""`` si le fichier du plan est l'original plus ses ajouts.

    Deux preuves : défaire les ajouts et remplacements redonne **exactement**
    les octets d'origine ; et le fichier se relit, avec les clips et les
    instruments d'origine identiques à eux-mêmes, dans le même ordre.
    """
    rebuilt, cursor, shift = bytearray(), 0, 0
    data = plan.data
    for position, old, new in plan.edits:
        start = position + shift
        rebuilt += data[cursor:start]
        rebuilt += old
        cursor = start + len(new)
        shift += len(new) - len(old)
    rebuilt += data[cursor:]
    if bytes(rebuilt) != original:
        return tr("le fichier ne redonne pas l'original : rien n'est écrit")
    try:
        before = dxml.loads(original).root
        after = dxml.loads(data).root
    except dxml.DelugeXMLError as exc:
        return tr("le fichier ne se relit pas : %s") % exc
    for holder in ("instruments", "sessionClips"):
        old_items = list(before.find(holder) if before.find(holder)
                         is not None else [])
        new_items = list(after.find(holder) if after.find(holder)
                         is not None else [])
        if len(new_items) < len(old_items):
            return tr("des éléments du morceau ont disparu")
        for a, b in zip(old_items, new_items):
            if not _same_tree(a, b):
                return tr("un élément du morceau a changé : rien n'est écrit")
    return ""


def _same_tree(a: ET.Element, b: ET.Element) -> bool:
    if a.tag != b.tag or a.attrib != b.attrib:
        return False
    if (a.text or "").strip() != (b.text or "").strip():
        return False
    if len(a) != len(b):
        return False
    return all(_same_tree(x, y) for x, y in zip(a, b))


def _plan_lines(target: SongTarget, plan: InsertPlan, new_tracks, clips,
                repeats: dict[int, int]) -> list[str]:
    lines = [tr("Nouveau fichier : %s") % plan.rel,
             tr("Le morceau %s reste tel quel ; le nouveau le contient octet "
                "pour octet, plus ce qui suit.") % Path(target.rel).stem]
    for track in new_tracks:
        lines.append(tr("Piste ajoutée : %s") % (track.name or track.kind))
    by_section: dict[int, list[NewClip]] = {}
    for clip in clips:
        by_section.setdefault(int(clip.section), []).append(clip)
    for section in sorted(by_section):
        copies = sum(1 for c in by_section[section] if c.copy_of is not None)
        fresh = len(by_section[section]) - copies
        text = tr("Section %d : %d clip(s) neuf(s), %d repris du morceau") % (
            section + 1, fresh, copies)
        if section in repeats:
            # 0 : « Repeats: infinite » sur la machine (``session_view.cpp``).
            text += (tr(", répétée sans fin") if not repeats[section]
                     else tr(", %d répétition(s)") % repeats[section])
        lines.append(text)
    tag, _width = note_blob_tag(target.firmware)
    lines.append(tr("Notes au format %s (firmware %s).") % (
        tag, target.firmware or "?"))
    return lines


def write_insert(sd: SDCard, plan: InsertPlan, apply: bool = False):
    """Écrit le morceau complété — **simule** sans ``apply``.

    Rend un :class:`songwriter.SongWrite`. Le fichier est toujours nouveau :
    s'il est apparu entre le plan et l'écriture, rien n'est écrit.
    """
    from .songwriter import SongWrite

    result = SongWrite(rel=plan.rel, lines=list(plan.lines),
                       error=plan.error)
    if plan.error or not plan.rel or not apply:
        return result
    sd.require_writable()
    target = sd.abs(plan.rel)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        # « x » : création exclusive — un fichier apparu entre-temps n'est
        # pas remplacé.
        with open(target, "xb") as handle:
            handle.write(plan.data)
    except FileExistsError:
        result.error = tr("%s existe déjà : rien n'a été écrit") % plan.rel
        return result
    except OSError as exc:
        log.exception("écriture du morceau complété impossible : %s",
                      plan.rel)
        result.error = tr("écriture impossible : %s") % exc
        return result
    sd.invalidate_cache()
    result.applied = True
    log.info("morceau complété : %s depuis %s (%d piste(s), %d clip(s) "
             "ajoutés)", plan.rel, plan.source, plan.added_tracks,
             plan.added_clips)
    return result
