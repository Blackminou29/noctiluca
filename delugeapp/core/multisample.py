# -*- coding: utf-8 -*-
"""Un instrument multi-échantillon, bâti depuis un dossier de sons.

Le 7 novembre 2026, **164 fichiers de ``SAMPLES/MULTISAMPLES`` (294 Mio)**
ne servaient à aucun preset de la carte de l'utilisateur : un piano Steinway
en deux couches de vélocité (``STEINWAY_IOWA/LOW/A1-1-48.WAV``,
``HIGH/A1-97-127.wav``) et une guitare (``Guitar 3 oct3_11(C#3)_61.wav``).
Ce module en fait des presets jouables.

Ce que fait le firmware, et que ce module refait à l'identique (1.3.0,
``sample_browser.cpp`` et ``sample_holder_for_voice.cpp``) :

* les échantillons sont rangés par hauteur, et chaque tranche s'arrête **à
  mi-chemin** de la suivante : ``rangeTopNote = (note + suivante) // 2`` ;
  la dernière n'a pas de note haute ;
* deux échantillons sur la même note : le second est écarté ;
* ``transpose = 60 − note`` (60 : le do que le Deluge affiche « C3 ») ;
* les points de boucle du fichier (bloc ``smpl``) : la fin de boucle devient
  la fin de la zone si la boucle est plus longue que ce qui la suit, sinon la
  fin de boucle ; le début de boucle est repris s'il précède la fin ;
* le mode de lecture : la moitié des sons ou plus ont une boucle, et la
  moitié une fin de boucle avant la fin, sur moins de 2,002 s en moyenne —
  jusqu'au bout ; une boucle seulement — en boucle ; sinon jusqu'au bout
  sous 2,002 s, et s'arrêter avec la note au-delà.

Ce qu'il **ne fait pas**, et que ce module ajoute :

* la hauteur **lue dans le nom** — « A1 », « Db4 », « (C#3)_61 ». La
  machine ne connaît que le bloc ``smpl`` du fichier et sa propre détection.
  La convention d'octave n'est pas la même partout : le Deluge appelle
  « C3 » le do 60, la plupart des banques « C4 ». Un numéro MIDI écrit à côté
  du nom tranche ; sinon l'écoute de quelques fichiers, et à défaut « C4 » ;
* les **couches de vélocité** (« A1-1-48 », « A1-97-127 ») : une tranche du
  Deluge n'a qu'une note haute, pas de vélocité. Une couche devient donc un
  preset — « STEINWAY LOW 1-48 », « … 97-127 ».

Rien n'est écrit sans :func:`write_instruments` avec ``apply`` ; aucun
fichier existant n'est remplacé, et les échantillons ne sont pas touchés.
"""

from __future__ import annotations

import logging
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from ..i18n import N_, tr
from . import wav
from .fixedpoint import INT32_MIN
from .model import SampleRange, SynthPreset, Zone, repeat_mode_for
from .sdcard import SDCard, norm_rel, safe_deluge_name

log = logging.getLogger(__name__)

__all__ = [
    "SampleNote", "Layer", "InstrumentPlan", "note_from_name",
    "plan_instrument", "build_presets", "write_instruments", "default_name",
    "note_label",
    "DEFAULT_FOLDER",
]

#: Sous-dossier de ``SYNTHS`` où partent les instruments bâtis.
DEFAULT_FOLDER = "Multi"

#: La relâche de l'enveloppe 1 : le réglage 8 (0,5 s), celui du piano
#: multi-échantillon que REPHAZER a bâti sur la machine
#: (``8 × 85 899 345 − 2³¹``, ``getParamFromUserValue``).
RELEASE = 8 * 85899345 - 2147483648

#: Fichiers écoutés au plus pour décider de la convention d'octave.
CONVENTION_PROBES = 8

#: Extensions lues par le Deluge.
_AUDIO = (".wav", ".aif", ".aiff")

_PITCH_CLASS = {"c": 0, "d": 2, "e": 4, "f": 5, "g": 7, "a": 9, "b": 11}
# Une lettre de note que ne précède aucune lettre, une altération, un octave.
_NOTE_RE = re.compile(r"(?<![A-Za-z])([A-Ga-g])(#|b|♯|♭)?(-?\d)(?!\d)")
_INT_RE = re.compile(r"(?<!\d)(\d{1,3})(?!\d)")
_VELOCITY_RE = re.compile(r"(?<!\d)(\d{1,3})\s*-\s*(\d{1,3})(?!\d)")


@dataclass
class SampleNote:
    """Un fichier du dossier, et la hauteur qu'on lui trouve."""

    rel: str
    note: int | None = None
    #: D'où vient la hauteur : « nom », « numéro », « fichier », « écoute ».
    source: str = ""
    frames: int = 0
    seconds: float = 0.0
    velocity: tuple[int, int] | None = None
    #: La hauteur lue dans le nom, en convention « C4 = 60 », avant que la
    #: convention du dossier soit décidée.
    named: int | None = None
    #: Points de boucle du bloc ``smpl``, en trames.
    loop_start: int | None = None
    loop_end: int | None = None

    def zone(self) -> Zone:
        """La zone que le firmware poserait (``sampleBeenSet``, choix
        manuel d'un fichier)."""
        zone = Zone(start=0, end=self.frames)
        fin = self.loop_end
        if fin and fin <= self.frames:
            debut = self.loop_start or 0
            if fin - debut >= self.frames - fin:
                zone.end = fin
            else:
                zone.end_loop = fin
            if 0 < debut < fin:
                zone.start_loop = debut
        return zone


@dataclass
class Layer:
    """Une couche de vélocité : un preset."""

    velocity: tuple[int, int] | None
    ranges: list[tuple[SampleNote, int]] = field(default_factory=list)
    name: str = ""

    @property
    def low(self) -> int:
        return min(s.note for s, _top in self.ranges)

    @property
    def high(self) -> int:
        return max(s.note for s, _top in self.ranges)


@dataclass
class InstrumentPlan:
    """Ce que :func:`build_presets` fera du dossier."""

    folder: str
    name: str
    layers: list[Layer] = field(default_factory=list)
    #: ``(chemin, raison)`` des fichiers laissés de côté.
    skipped: list[tuple[str, str]] = field(default_factory=list)
    #: Convention d'octave retenue pour les noms, et pourquoi.
    convention: str = ""

    def __bool__(self) -> bool:
        return any(layer.ranges for layer in self.layers)

    def lines(self) -> list[str]:
        """Le plan en clair."""
        out = []
        for layer in self.layers:
            if layer.ranges:
                out.append(tr("%s : %d tranche(s), de %s à %s") % (
                    layer.name, len(layer.ranges), note_label(layer.low),
                    note_label(layer.high)))
        if self.convention:
            out.append(self.convention)
        for rel, why in self.skipped[:8]:
            out.append(tr("Écarté : %s — %s") % (Path(rel).name, why))
        if len(self.skipped) > 8:
            out.append(tr("… et %d autre(s) fichier(s) écarté(s)")
                       % (len(self.skipped) - 8))
        return out


def note_label(note: int) -> str:
    """Le nom d'une note **comme l'écrit le Deluge** : 60 = « C3 »."""
    names = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
    return "%s%d" % (names[int(note) % 12], int(note) // 12 - 2)


def note_from_name(stem: str) -> tuple[int | None, int | None,
                                        tuple[int, int] | None]:
    """Ce que dit le nom d'un fichier : ``(note C4 = 60, note certaine,
    vélocités)``.

    * la note lue (« A1 », « Db4 », « C#3 »), en convention « C4 = 60 » ;
    * la note **certaine** si un numéro MIDI l'accompagne (« (C#3)_61 ») :
      il dit aussi la convention ;
    * une plage de vélocités écrite après la note (« A1-97-127 »).
    """
    matches = list(_NOTE_RE.finditer(stem))
    if not matches:
        return None, None, None
    m = matches[-1]
    letter, accident, octave = m.group(1).lower(), m.group(2) or "", m.group(3)
    pitch = _PITCH_CLASS[letter] + {"#": 1, "♯": 1, "b": -1, "♭": -1}.get(
        accident, 0)
    c4 = 12 * (int(octave) + 1) + pitch
    if not 0 <= c4 <= 127:
        return None, None, None
    reste = stem[m.end():]
    # La plage de vélocités d'abord, puis on l'efface : « C2-1-48 » portait
    # un 48 que l'on prenait pour le numéro MIDI du do 2 (36 + 12) — mesuré
    # sur les Steinway de la carte.
    velocity = None
    v = _VELOCITY_RE.search(reste)
    if v is not None:
        low, high = int(v.group(1)), int(v.group(2))
        if 0 <= low < high <= 127:
            velocity = (low, high)
            reste = reste[:v.start()] + " " + reste[v.end():]
    numbers = [int(n) for n in _INT_RE.findall(reste)]
    certain = next((n for n in numbers if n in (c4, c4 + 12) and n <= 127),
                   None)
    return c4, certain, velocity


def default_name(folder: str) -> str:
    """Le nom proposé pour l'instrument d'un dossier : le sien, précédé de
    celui du dossier parent quand il ne dit presque rien — « LOW », « 3 »
    deviennent « STEINWAY_IOWA LOW », « REPHAZER X-SELECTED 3 »."""
    parts = [p for p in str(folder).replace("\\", "/").split("/") if p]
    if not parts:
        return "MULTI"
    nom = parts[-1]
    if (len(nom) <= 4 or nom.isdigit()) and len(parts) >= 2 \
            and parts[-2].upper() not in ("SAMPLES", "MULTISAMPLES"):
        nom = "%s %s" % (parts[-2], nom)
    return nom


def _audio_files(sd: SDCard, folder: str) -> list[Path]:
    base = sd.abs(folder)
    try:
        files = sorted((p for p in base.iterdir() if p.is_file()
                        and p.suffix.lower() in _AUDIO
                        and not p.name.startswith(("._", "."))),
                       key=lambda p: p.name.lower())
    except OSError:
        return []
    return files


def _detect(path: Path) -> int | None:
    from . import analysis

    try:
        data, sr = wav.read(path, max_frames=6 * 48000, mono=True)
    except Exception:  # noqa: BLE001 - un fichier illisible ne bloque rien
        return None
    return analysis.estimate_root_note(data, sr)


def _convention(samples: list[SampleNote], paths: dict[str, Path],
                detect: bool) -> tuple[int, str]:
    """Le décalage à ajouter aux notes lues (« C4 = 60 »), et pourquoi."""
    named = [s for s in samples if s.named is not None]
    if not named:
        return 0, ""
    if detect:
        pas = max(1, len(named) // CONVENTION_PROBES)
        ecarts = []
        for s in named[::pas][:CONVENTION_PROBES]:
            heard = _detect(paths[s.rel])
            if heard is not None:
                ecarts.append(heard - s.named)
        if ecarts:
            octave = int(round(statistics.median(ecarts) / 12.0)) * 12
            if octave in (0, 12):
                return octave, (
                    tr("Noms lus avec « C4 = 60 », confirmé à l'écoute de %d "
                       "fichier(s)") if octave == 0 else
                    tr("Noms lus avec « C3 = 60 », la convention du Deluge, "
                       "confirmée à l'écoute de %d fichier(s)")) % len(ecarts)
    return 0, tr("Noms lus avec « C4 = 60 », la convention de la plupart des "
                 "banques : l'écoute n'a pas pu trancher")


def plan_instrument(sd: SDCard, folder: str, name: str = "",
                    detect: bool = True) -> InstrumentPlan:
    """Lit le dossier et décide des tranches, sans rien écrire."""
    folder = str(folder).replace("\\", "/").strip("/")
    plan = InstrumentPlan(folder=folder,
                          name=safe_deluge_name(name or default_name(folder)))
    paths: dict[str, Path] = {}
    samples: list[SampleNote] = []
    for path in _audio_files(sd, folder):
        rel = sd.rel(path)
        info = wav.probe(path)
        if not info.ok or info.frames <= 0:
            plan.skipped.append((rel, tr("illisible")))
            continue
        paths[rel] = path
        named, certain, velocity = note_from_name(path.stem)
        sample = SampleNote(rel=rel, frames=int(info.frames),
                            seconds=float(info.duration), velocity=velocity,
                            named=named if certain is None else None,
                            loop_start=getattr(info, "loop_start", None),
                            loop_end=getattr(info, "loop_end", None))
        if certain is not None:
            sample.note, sample.source = certain, N_("numéro")
        elif named is None and getattr(info, "root_note", None) is not None:
            sample.note, sample.source = int(info.root_note), N_("fichier")
        samples.append(sample)

    # « Si tous les échantillons portent la même note, on se méfie et on
    # l'oublie » (``loadAllSamplesInFolder``) : les seize sons de
    # ``REPHAZER X-SELECTED/1`` disent tous 60 dans leur bloc ``smpl``.
    du_fichier = [s for s in samples if s.source == "fichier"]
    if len(du_fichier) > 1 and len({s.note for s in du_fichier}) == 1:
        for sample in du_fichier:
            sample.note, sample.source = None, ""

    offset, plan.convention = _convention(samples, paths, detect)
    for sample in samples:
        if sample.note is None and sample.named is not None:
            sample.note, sample.source = sample.named + offset, N_("nom")
        elif sample.note is None and detect:
            heard = _detect(paths[sample.rel])
            if heard is not None:
                sample.note, sample.source = heard, N_("écoute")
        if sample.note is None or not 0 <= sample.note <= 127:
            plan.skipped.append((sample.rel, tr("hauteur introuvable")))

    groups: dict[tuple[int, int] | None, list[SampleNote]] = {}
    for sample in samples:
        if sample.note is not None and 0 <= sample.note <= 127:
            groups.setdefault(sample.velocity, []).append(sample)
    for velocity in sorted(groups, key=lambda v: (v is not None, v or (0, 0))):
        layer = Layer(velocity=velocity)
        par_note = sorted(groups[velocity], key=lambda s: (s.note, s.rel))
        kept: list[SampleNote] = []
        for sample in par_note:
            if kept and sample.note == kept[-1].note:
                plan.skipped.append((sample.rel,
                                     tr("même note que %s")
                                     % Path(kept[-1].rel).name))
                continue
            kept.append(sample)
        for index, sample in enumerate(kept):
            top = 127 if index == len(kept) - 1 else \
                (sample.note + kept[index + 1].note) // 2
            layer.ranges.append((sample, top))
        suffix = " %d-%d" % velocity if velocity is not None and \
            len(groups) > 1 else ""
        layer.name = safe_deluge_name(plan.name + suffix)
        plan.layers.append(layer)
    return plan


def build_presets(plan: InstrumentPlan) -> list[SynthPreset]:
    """Un preset par couche, comme le Deluge le bâtirait du même dossier."""
    presets = []
    for layer in plan.layers:
        if not layer.ranges:
            continue
        preset = SynthPreset.new(layer.name)
        sound = preset.sound
        osc = sound.osc1
        osc.type = "sample"
        osc.file_name = ""
        osc.ranges = [SampleRange(top_note=top, file_name=s.rel,
                                  transpose=60 - int(s.note), cents=0,
                                  zone=s.zone())
                      for s, top in layer.ranges]
        osc.loop_mode = _repeat_mode(layer)
        # Le second oscillateur se tait : l'instrument est son échantillon.
        sound.set_param("oscBVolume", INT32_MIN)
        # Relâchée, la note s'éteint en une demi-seconde, comme sous
        # l'étouffoir : le son neuf du firmware la coupe en 6 ms — entendu
        # sur la machine le 9 novembre 2026, « elle s'éteint sèchement ».
        sound.env1.release = RELEASE
        presets.append(preset)
    return presets


def _repeat_mode(layer: Layer) -> int:
    """Le mode de lecture que choisirait le firmware pour ces tranches
    (``loadAllSamplesInFolder``)."""
    from .model import REPEAT_LOOP, REPEAT_ONCE

    n = len(layer.ranges)
    moyenne = sum(s.seconds for s, _t in layer.ranges) / n
    bouclees = sum(1 for s, _t in layer.ranges if s.loop_end)
    fins = sum(1 for s, _t in layer.ranges if s.zone().end_loop >= 0)
    if bouclees * 2 >= n:
        return REPEAT_ONCE if fins * 2 >= n and moyenne < 2.002 \
            else REPEAT_LOOP
    return repeat_mode_for(moyenne)


@dataclass
class InstrumentWrite:
    """Ce que :func:`write_instruments` a écrit, ou écrirait."""

    rels: list[str] = field(default_factory=list)
    error: str = ""
    applied: bool = False


def _free_rel(sd: SDCard, folder: str, name: str, taken: set[str]) -> str:
    base = "SYNTHS/%s" % folder.strip("/") if folder.strip("/") else "SYNTHS"
    stem = safe_deluge_name(name or "MULTI")
    rel, index = "%s/%s.XML" % (base, stem), 2
    while sd.abs(rel).exists() or norm_rel(rel) in taken:
        rel = "%s/%s %d.XML" % (base, stem, index)
        index += 1
    return rel


def write_instruments(sd: SDCard, plan: InstrumentPlan,
                      folder: str = DEFAULT_FOLDER,
                      apply: bool = False) -> InstrumentWrite:
    """Écrit les presets du plan dans ``SYNTHS/<folder>`` — **simule** sans
    ``apply``. Un nom pris est numéroté : rien n'est remplacé."""
    result = InstrumentWrite()
    presets = build_presets(plan)
    if not presets:
        result.error = tr("aucun échantillon dont la hauteur soit connue")
        return result
    taken: set[str] = set()
    targets = []
    for preset in presets:
        rel = _free_rel(sd, folder, preset.name, taken)
        taken.add(norm_rel(rel))
        targets.append((preset, rel))
    result.rels = [rel for _p, rel in targets]
    if not apply:
        return result
    sd.require_writable()
    for preset, rel in targets:
        target = sd.abs(rel)
        if target.exists():
            result.error = tr("%s existe déjà : rien n'a été écrit") % rel
            return result
        target.parent.mkdir(parents=True, exist_ok=True)
        preset.save(target, backup=False)
        log.info("instrument écrit : %s (%d tranche(s))", rel,
                 len(preset.sound.osc1.ranges))
    sd.invalidate_cache()
    result.applied = True
    return result
