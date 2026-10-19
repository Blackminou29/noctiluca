# -*- coding: utf-8 -*-
"""Découpage d'une boucle en kit jouable.

Prendre un break, une boucle de batterie ou une phrase, et en faire un kit
dont chaque pad joue une tranche : c'est l'un des gestes les plus courants
sur une boîte à rythmes.

**Le découpage ne duplique aucun fichier.** Chaque rangée du kit pointe le
même échantillon avec ses propres bornes (``startSamplePos`` /
``endSamplePos``). Ce n'est pas une idée : c'est l'idiome déjà présent sur la
carte de référence, où 19 zones ne jouent qu'une portion de leur fichier —
``021 hodeur 1.XML`` joue les 10 à 55 % de six enregistrements, et
``015 Andrew Stirton Frugal.XML`` démarre ``frugalriser.wav`` à la trame
113 403. Un kit y référence même **deux fois le même fichier avec des bornes
différentes** (``snare smack.wav``), ce qui est exactement un découpage à deux
tranches.

Les bornes sont **exclusives** : sur la carte, une zone qui couvre tout le
fichier porte ``endSamplePos`` égal au nombre de trames, pas au dernier
indice (``clap1.wav`` : 384 → 12259 pour 12259 trames).

Trois façons de placer les coupes :

* ``transients`` — sur les attaques détectées, ce qui suit le jeu réel ;
* ``grid`` — en divisions égales du fichier : sur une boucle correctement
  coupée, c'est déjà la grille musicale, et c'est le mode qui garde un break
  en place quand on le rejoue ;
* ``manual`` — des positions fournies, pour l'édition à la souris.

L'export en fichiers séparés existe aussi (:func:`export_slices`), pour les
cas où l'on veut des échantillons autonomes, mais ce n'est pas le mode par
défaut : il multiplie l'occupation disque sans rien apporter au Deluge.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..i18n import tr
from . import analysis, wav
from .db import Library
from .dxml import DelugeXMLError
from .model import Kit, Zone
from .sdcard import SDCard, safe_deluge_name

log = logging.getLogger(__name__)

__all__ = [
    "Slice", "SliceSet",
    "MODES", "DEFAULT_SLICES", "MAX_SLICES", "MIN_SLICE_MS",
    "detect_slices", "grid_slices", "slice_sample",
    "slices_to_kit", "save_sliced_kit", "export_slices", "render_slice",
]

#: Modes de placement des coupes.
MODES = ("transients", "grid", "manual")

#: Nombre de tranches visé par défaut : une mesure en doubles-croches.
DEFAULT_SLICES = 16

#: Plafond retenu. Rien dans le format ne l'impose — le plus gros kit de la
#: carte de référence compte 19 rangées — mais au-delà, un pad par tranche
#: devient impraticable à jouer.
MAX_SLICES = 32

#: Durée minimale d'une tranche : en dessous, on entend un clic, pas un son.
MIN_SLICE_MS = 20.0

#: Longueur maximale d'un nom de rangée, pour rester lisible sur l'écran.
MAX_ROW_NAME = 12


# --------------------------------------------------------------------------- #
# Une tranche
# --------------------------------------------------------------------------- #

@dataclass
class Slice:
    """Une tranche : bornes en trames, ``end`` exclusif."""

    start: int
    end: int
    label: str = ""

    @property
    def frames(self) -> int:
        """Longueur en trames."""
        return max(0, int(self.end) - int(self.start))

    def seconds(self, sr: int) -> float:
        """Durée en secondes pour la fréquence donnée."""
        return self.frames / float(sr) if sr > 0 else 0.0

    def zone(self) -> Zone:
        """La zone Deluge correspondante."""
        return Zone(start=int(self.start), end=int(self.end),
                    unit="samples")


@dataclass
class SliceSet:
    """Le découpage d'un échantillon."""

    rel: str
    sr: int
    frames: int
    slices: list[Slice] = field(default_factory=list)
    bpm: float = 0.0
    mode: str = "transients"

    def __len__(self) -> int:
        return len(self.slices)

    def __bool__(self) -> bool:
        return bool(self.slices)

    def __iter__(self):
        return iter(self.slices)

    @property
    def duration(self) -> float:
        """Durée totale du fichier, en secondes."""
        return self.frames / float(self.sr) if self.sr > 0 else 0.0

    @property
    def covered(self) -> int:
        """Trames effectivement couvertes par les tranches."""
        return sum(s.frames for s in self.slices)

    def summary(self) -> str:
        """Résumé en une ligne."""
        if not self.slices:
            return tr("Aucune tranche.")
        court = min(s.frames for s in self.slices) / float(self.sr or 1)
        long = max(s.frames for s in self.slices) / float(self.sr or 1)
        texte = (tr("%d tranches, de %.0f à %.0f ms")
                 % (len(self.slices), court * 1000.0, long * 1000.0))
        if self.bpm:
            texte += " — %.1f BPM" % self.bpm
        return texte + "."

    def to_text(self) -> str:
        """Détail tranche par tranche."""
        lignes = ["%s  (%s)" % (self.rel, self.summary()), ""]
        for index, tranche in enumerate(self.slices, 1):
            lignes.append(
                "  %2d  %-12s %9d → %-9d  %7.1f ms"
                % (index, tranche.label, tranche.start, tranche.end,
                   tranche.seconds(self.sr) * 1000.0))
        return "\n".join(lignes)

    def quantize(self, bpm: float, division: int = 16) -> "SliceSet":
        """Aligne les coupes sur une grille musicale.

        Un transitoire détecté tombe presque toujours quelques
        millisecondes à côté du temps : rejouer les tranches dans l'ordre
        fait alors entendre un flottement. Aligner les débuts sur la grille
        remet le motif en place.
        """
        if bpm <= 0 or division <= 0 or self.sr <= 0:
            return self
        pas = self.sr * 60.0 / (bpm * (division / 4.0))
        if pas <= 1:
            return self

        bornes = sorted({_clamp(int(round(s.start / pas) * pas), 0,
                                self.frames) for s in self.slices})
        return _from_starts(self, bornes, mode=self.mode)


# --------------------------------------------------------------------------- #
# Placement des coupes
# --------------------------------------------------------------------------- #

def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(int(value), high))


def _label(index: int, stem: str = "") -> str:
    """Nom court d'une rangée : le numéro suffit sur l'écran du Deluge."""
    if not stem:
        return "%02d" % index
    place = max(1, MAX_ROW_NAME - 3)
    return safe_deluge_name("%s %02d" % (stem[:place], index))


def _from_starts(base: SliceSet, starts: list[int],
                 mode: str = "manual", stem: str = "") -> SliceSet:
    """Construit un découpage à partir de positions de début."""
    propres = sorted({_clamp(s, 0, base.frames) for s in starts})
    if not propres or propres[0] != 0:
        propres = [0] + [s for s in propres if s > 0]

    # On filtre les BORNES, on ne fusionne pas les tranches après coup : une
    # première tranche trop courte n'a pas de précédente où se fondre, et
    # restait à 30 trames — soit le clic qu'on voulait éviter.
    mini = int(MIN_SLICE_MS * base.sr / 1000.0)
    gardees: list[int] = []
    for start in propres:
        if not gardees or start - gardees[-1] >= mini:
            gardees.append(start)
    if not gardees:
        gardees = [0]

    # Une queue plus courte que le minimum rejoint la tranche précédente.
    while len(gardees) > 1 and base.frames - gardees[-1] < mini:
        gardees.pop()

    tranches = [
        Slice(start=start,
              end=gardees[index + 1] if index + 1 < len(gardees)
              else base.frames,
              label=_label(index + 1, stem))
        for index, start in enumerate(gardees)
    ]

    return SliceSet(rel=base.rel, sr=base.sr, frames=base.frames,
                    slices=tranches, bpm=base.bpm, mode=mode)


def detect_slices(data: np.ndarray, sr: int, sensitivity: float = 1.0,
                  max_slices: int = DEFAULT_SLICES) -> list[int]:
    """Positions de début des tranches, sur les attaques détectées.

    Retourne des numéros de trame. La première vaut toujours 0 : une boucle
    commence rarement par du silence, et quand c'est le cas la coupe du
    silence est un autre outil.
    """
    limite = _clamp(max_slices, 1, MAX_SLICES)
    try:
        attaques = analysis.transients(data, sr, sensitivity=sensitivity)
    except Exception as exc:                        # noqa: BLE001
        log.debug("détection des attaques impossible : %s", exc)
        attaques = np.zeros(0, dtype=np.int64)

    positions = [0] + [int(p) for p in attaques if p > 0]
    if len(positions) <= limite:
        return sorted(set(positions))

    # Trop d'attaques : on garde les plus franches, en conservant l'ordre.
    try:
        arr = analysis._mono(data)
        force = []
        fenetre = max(1, int(0.01 * sr))
        for p in positions[1:]:
            fin = min(arr.size, p + fenetre)
            force.append((float(np.max(np.abs(arr[p:fin]))) if fin > p else 0.0,
                          p))
        force.sort(reverse=True)
        gardees = [p for _f, p in force[:limite - 1]]
    except Exception as exc:                        # noqa: BLE001
        log.debug("tri des attaques impossible : %s", exc)
        gardees = positions[1:limite]
    return sorted({0, *gardees})


def grid_slices(frames: int, sr: int, count: int = DEFAULT_SLICES
                ) -> list[int]:
    """Positions de début en divisions égales du fichier.

    **Pas d'alignement sur un tempo ici, et c'est volontaire.** Une boucle
    correctement coupée est déjà un multiple exact de la division : les
    4,0 s de ``Bricky-NoKS-120.wav`` donnent 16 tranches de 250 ms, soit la
    croche à 120 BPM, au cent près. Ramener ces bornes sur un tempo
    *détecté* — 120,2 BPM au lieu de 120 — déplaçait les coupes et faisait
    sortir une tranche à 256 ms : l'alignement dégradait un découpage déjà
    juste.

    L'alignement sert pour les coupes issues des attaques, qui tombent
    réellement à côté de la grille ; il est là, et là seulement
    (:meth:`SliceSet.quantize`).
    """
    nombre = _clamp(count, 1, MAX_SLICES)
    if frames <= 0:
        return [0]
    pas = frames / float(nombre)
    return sorted({_clamp(int(round(i * pas)), 0, frames)
                   for i in range(nombre)})


def slice_sample(sd: SDCard, rel: str, mode: str = "transients",
                 count: int = DEFAULT_SLICES, sensitivity: float = 1.0,
                 bpm: float = 0.0, positions: list[int] | None = None,
                 lib: Library | None = None,
                 quantize: bool = False) -> SliceSet:
    """Découpe un échantillon de la carte. Ne modifie rien sur le disque.

    ``bpm`` vaut par défaut celui que l'analyse a enregistré dans l'index,
    ce qui évite de le ressaisir pour une boucle déjà analysée.
    """
    path = sd.resolve_sample(rel)
    if path is None or not path.is_file():
        log.info("échantillon introuvable : %s", rel)
        return SliceSet(rel=rel, sr=0, frames=0, mode=mode)

    info = wav.probe(path)
    if not info.ok or info.frames <= 0:
        log.info("échantillon illisible (%s) : %s", rel, info.error)
        return SliceSet(rel=rel, sr=0, frames=0, mode=mode)

    tempo = float(bpm or 0.0)
    if tempo <= 0 and lib is not None:
        row = lib.get("sample", rel)
        if row is not None:
            try:
                tempo = float(row["bpm"] or 0.0)
            except (KeyError, IndexError, TypeError):
                tempo = 0.0

    base = SliceSet(rel=rel, sr=info.sample_rate, frames=info.frames,
                    bpm=tempo, mode=mode)
    stem = Path(rel).stem

    if mode == "manual":
        starts = list(positions or [0])
    elif mode == "grid":
        starts = grid_slices(info.frames, info.sample_rate, count)
    else:
        data, sr = wav.read(path)
        starts = detect_slices(data, sr or info.sample_rate,
                               sensitivity=sensitivity, max_slices=count)

    decoupage = _from_starts(base, starts, mode=mode, stem=stem)
    if quantize and tempo > 0:
        decoupage = decoupage.quantize(tempo)
        for index, tranche in enumerate(decoupage.slices, 1):
            tranche.label = _label(index, stem)
    return decoupage


# --------------------------------------------------------------------------- #
# Du découpage au kit
# --------------------------------------------------------------------------- #

def slices_to_kit(sliceset: SliceSet, name: str = "") -> Kit:
    """Construit un kit dont chaque rangée joue une tranche.

    Toutes les rangées pointent **le même fichier** : aucune copie n'est
    créée. L'ordre des rangées est l'ordre des tranches, de façon que les
    pads rejouent la boucle de gauche à droite.
    """
    titre = safe_deluge_name(name or Path(sliceset.rel).stem)[:20] or "SLICES"
    kit = Kit.new(titre)
    for tranche in sliceset.slices:
        # Une tranche courte se joue jusqu'au bout quelle que soit la note,
        # comme le fait le découpeur du Deluge (``slicer.cpp`` : ONCE sous
        # 2,002 s). L'ancien ``loopMode`` 0 était CUT : la tranche s'arrêtait
        # avec la note, contrairement à ce qu'annonçait le commentaire.
        row = kit.add_row(tranche.label or "SLICE", sliceset.rel,
                          seconds=tranche.seconds(sliceset.sr))
        row.sound.osc1.zone = tranche.zone()
    return kit


def save_sliced_kit(sd: SDCard, sliceset: SliceSet, name: str = "",
                    folder: str = "KITS",
                    apply: bool = False) -> tuple[str, str]:
    """Écrit le kit sur la carte. Retourne ``(chemin relatif, message)``.

    ``apply=False`` (défaut) ne crée rien : le chemin retourné est celui qui
    *serait* écrit, pour pouvoir l'annoncer avant confirmation (SPEC §0.2).
    """
    if not sliceset:
        return "", tr("Aucune tranche à écrire.")

    titre = safe_deluge_name(name or Path(sliceset.rel).stem)[:20] or "SLICES"
    base = str(folder or "KITS").strip("/") or "KITS"
    rel = "%s/%s.XML" % (base, titre)

    # Un nom déjà pris n'est jamais écrasé : on numérote.
    index = 2
    while sd.abs(rel).exists():
        rel = "%s/%s %d.XML" % (base, titre, index)
        index += 1
        if index > 99:
            return "", tr("Trop de kits portent déjà ce nom.")

    if not apply:
        return rel, (tr("%d tranches seraient écrites dans %s.")
                     % (len(sliceset), rel))
    sd.require_writable()

    kit = slices_to_kit(sliceset, titre)
    path = sd.abs(rel)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        kit.save(path, backup=False)
    except (OSError, DelugeXMLError) as exc:
        # ``dxml.save`` traduit toute erreur d'écriture en DelugeXMLError.
        log.exception("écriture du kit impossible : %s", rel)
        return "", tr("Écriture impossible : %s") % exc
    return rel, tr("%d tranches écrites dans %s.") % (len(sliceset), rel)


# --------------------------------------------------------------------------- #
# Écoute et export
# --------------------------------------------------------------------------- #

def render_slice(sd: SDCard, sliceset: SliceSet, index: int) -> np.ndarray:
    """Le signal d'une tranche, pour l'écouter avant d'écrire le kit."""
    if not 0 <= index < len(sliceset.slices):
        return np.zeros(0, dtype=np.float32)
    path = sd.resolve_sample(sliceset.rel)
    if path is None:
        return np.zeros(0, dtype=np.float32)
    tranche = sliceset.slices[index]
    try:
        data, _sr = wav.read(path)
    except Exception as exc:                        # noqa: BLE001
        log.debug("lecture impossible pour l'écoute : %s", exc)
        return np.zeros(0, dtype=np.float32)
    if data.ndim == 1:
        data = data.reshape(-1, 1)
    return np.ascontiguousarray(
        data[_clamp(tranche.start, 0, data.shape[0]):
             _clamp(tranche.end, 0, data.shape[0])])


def export_slices(sd: SDCard, sliceset: SliceSet, folder: str,
                  apply: bool = False,
                  bit_depth: int | None = None) -> tuple[list[str], list[str]]:
    """Écrit chaque tranche dans son propre fichier.

    Ce n'est **pas** nécessaire pour jouer un découpage sur le Deluge : un kit
    à zones suffit et n'occupe rien de plus. Cette fonction existe pour
    sortir des échantillons autonomes, réutilisables ailleurs.

    Retourne ``(fichiers, erreurs)``. Avec ``apply=False``, seuls les chemins
    prevus sont retournés.
    """
    if not sliceset:
        return [], [tr("Aucune tranche à exporter.")]

    base = str(folder or "").strip("/")
    if not base:
        return [], [tr("Aucun dossier de destination.")]

    stem = safe_deluge_name(Path(sliceset.rel).stem)[:16] or "SLICE"
    prevus = ["%s/%s %02d.wav" % (base, stem, i + 1)
              for i in range(len(sliceset))]
    if not apply:
        return prevus, []
    sd.require_writable()

    path = sd.resolve_sample(sliceset.rel)
    if path is None:
        return [], [tr("Échantillon introuvable : %s") % sliceset.rel]
    try:
        data, sr = wav.read(path)
    except Exception as exc:                        # noqa: BLE001
        return [], [tr("Lecture de l'échantillon impossible : %s") % exc]
    if data.ndim == 1:
        data = data.reshape(-1, 1)

    info = wav.probe(path)
    profondeur = bit_depth or (info.bit_depth if info.ok else 16)
    ecrits: list[str] = []
    erreurs: list[str] = []
    for rel, tranche in zip(prevus, sliceset.slices):
        bloc = data[_clamp(tranche.start, 0, data.shape[0]):
                    _clamp(tranche.end, 0, data.shape[0])]
        if bloc.shape[0] == 0:
            erreurs.append(tr("%s : tranche vide") % rel)
            continue
        cible = sd.abs(rel)
        try:
            cible.parent.mkdir(parents=True, exist_ok=True)
            wav.write(cible, bloc, sr or info.sample_rate, profondeur)
            ecrits.append(rel)
        except OSError as exc:
            erreurs.append(tr("%s : %s") % (rel, exc))
    return ecrits, erreurs
