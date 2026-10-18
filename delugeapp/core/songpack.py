# -*- coding: utf-8 -*-
"""Rassembler tout ce dont un morceau a besoin, dans un dossier à part.

Le Deluge garde ses morceaux, ses presets et ses échantillons dans trois
arborescences séparées. Pour archiver un morceau, le donner à quelqu'un ou le
porter sur une autre carte, il faut donc réunir des fichiers éparpillés — et
en oublier un suffit à ce que le morceau s'ouvre muet à l'arrivée.

Ce module construit cet ensemble : le morceau, les presets qu'il nomme, les
échantillons que ces presets lisent, **avec l'arborescence d'origine**, de
sorte que le dossier produit est une mini-carte qu'il suffit de recopier.

Deux règles qui ne changent pas :

* rien n'est écrit sans ``apply=True`` (SPEC §0.2) : le plan se chiffre et
  s'affiche d'abord ;
* **rien n'est déplacé ni modifié sur la carte.** Tout est copié. Un morceau
  reste lisible par le Deluge après l'opération, puisque la carte n'a pas
  bougé d'un octet.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import units
from .model import Kit, Song, SynthPreset
from .sdcard import SDCard, norm_rel

log = logging.getLogger(__name__)

__all__ = ["SongPack", "collect", "write_pack", "safe_folder_name"]

#: Dossiers d'une carte, dans l'ordre où on les recopie.
STD_DIRS = ("SONGS", "SYNTHS", "KITS", "SAMPLES")


@dataclass
class SongPack:
    """Inventaire de ce qu'un morceau réclame."""

    song_rel: str = ""
    name: str = ""
    presets: list[str] = field(default_factory=list)
    samples: list[str] = field(default_factory=list)
    missing_presets: list[str] = field(default_factory=list)
    missing_samples: list[str] = field(default_factory=list)
    bytes_total: int = 0

    def __len__(self) -> int:
        return len(self.files())

    def __bool__(self) -> bool:
        return bool(self.song_rel)

    def files(self) -> list[str]:
        """Tous les fichiers à copier, morceau compris."""
        out = [self.song_rel] if self.song_rel else []
        return out + list(self.presets) + list(self.samples)

    @property
    def complete(self) -> bool:
        """Vrai si rien ne manque."""
        return not self.missing_presets and not self.missing_samples

    def summary(self) -> str:
        """Résumé en une ligne."""
        if not self.song_rel:
            return "Morceau introuvable."
        texte = ("%d fichier(s) — %d preset(s), %d échantillon(s), %s"
                 % (len(self), len(self.presets), len(self.samples),
                    units.human_size(self.bytes_total)))
        manque = len(self.missing_presets) + len(self.missing_samples)
        if manque:
            texte += " ; %d introuvable(s)" % manque
        return texte + "."

    def to_text(self) -> str:
        """Détail, fichier par fichier."""
        lignes = ["Morceau : %s" % self.song_rel, "", self.summary(), ""]
        if self.presets:
            lignes.append("Presets (%d) :" % len(self.presets))
            lignes += ["  %s" % p for p in self.presets]
            lignes.append("")
        if self.samples:
            lignes.append("Échantillons (%d) :" % len(self.samples))
            lignes += ["  %s" % s for s in self.samples]
            lignes.append("")
        if self.missing_presets:
            lignes.append("Presets introuvables (%d) :"
                          % len(self.missing_presets))
            lignes += ["  %s" % p for p in self.missing_presets]
            lignes.append("")
        if self.missing_samples:
            lignes.append("Échantillons introuvables (%d) :"
                          % len(self.missing_samples))
            lignes += ["  %s" % s for s in self.missing_samples]
        return "\n".join(lignes).rstrip()


def safe_folder_name(name: str) -> str:
    """Nom de dossier utilisable partout, tiré du nom du morceau.

    On réutilise l'assainissement de la carte : le dossier produit est destiné
    à être recopié sur une carte, autant qu'il en respecte déjà les règles.
    """
    from .sdcard import safe_deluge_name

    # ``safe_deluge_name`` rend déjà « SANS NOM » pour une entrée vide : un
    # second repli ici ne servirait qu'à inventer une deuxième convention.
    return safe_deluge_name(name or "").strip()[:40]


def _find_preset(sd: SDCard, kind: str, name: str, folder: str) -> str:
    """Chemin relatif d'un preset nommé par un morceau, ou ``""``.

    Un morceau désigne ses presets par leur **nom et leur dossier**, pas par
    un chemin. La casse n'est pas fiable (FAT32), et le dossier annoncé peut
    être vide : on cherche alors dans toute l'arborescence correspondante.
    """
    racine = "KITS" if kind == "kit" else "SYNTHS"
    candidats = sd.kits() if kind == "kit" else sd.synths()

    cible = norm_rel(name)
    dossier = norm_rel(folder or "")

    # 1. Le dossier annoncé, s'il est renseigné.
    if dossier:
        attendu = norm_rel("%s/%s.XML" % (folder.strip("/"), name))
        for chemin in candidats:
            if norm_rel(sd.rel(chemin)) == attendu:
                return sd.rel(chemin)
        # Le dossier du morceau peut omettre la racine (« acid » plutôt que
        # « SYNTHS/acid ») : on réessaie en la préfixant.
        attendu = norm_rel("%s/%s/%s.XML" % (racine, folder.strip("/"), name))
        for chemin in candidats:
            if norm_rel(sd.rel(chemin)) == attendu:
                return sd.rel(chemin)

    # 2. À défaut, le premier preset de ce nom, où qu'il soit.
    for chemin in candidats:
        if norm_rel(chemin.stem) == cible:
            return sd.rel(chemin)
    return ""


#: Nom public : la page Morceaux doit chercher les presets exactement comme
#: l'export, sinon elle déclare « absent » ce que l'export copie.
find_preset = _find_preset


def _samples_of_preset(sd: SDCard, rel: str) -> list[str]:
    """Échantillons lus par un preset ou un kit."""
    chemin = sd.abs(rel)
    classe = Kit if norm_rel(rel).startswith("kits/") else SynthPreset
    try:
        objet = classe.load(chemin)
    except Exception as exc:                        # noqa: BLE001
        log.debug("preset illisible (%s) : %s", rel, exc)
        return []
    try:
        return [p for p in objet.sample_paths() if p]
    except Exception as exc:                        # noqa: BLE001
        log.debug("échantillons de %s illisibles : %s", rel, exc)
        return []


def collect(sd: SDCard, song_rel: str) -> SongPack:
    """Inventorie tout ce dont un morceau a besoin. N'écrit rien.

    Les échantillons viennent de deux sources : ceux que le morceau cite
    lui-même (il embarque une copie des définitions d'instruments) et ceux
    que lisent les presets qu'il nomme. Les deux sont nécessaires : un
    morceau peut citer un échantillon qu'aucun preset de la carte ne lit.
    """
    pack = SongPack(song_rel=song_rel)
    chemin = sd.abs(song_rel)
    if not chemin.is_file():
        log.info("morceau introuvable : %s", song_rel)
        return SongPack()

    try:
        song = Song.load(chemin)
    except Exception as exc:                        # noqa: BLE001
        log.exception("morceau illisible : %s", song_rel)
        pack.name = Path(song_rel).stem
        pack.missing_presets.append("morceau illisible : %s" % exc)
        return pack

    pack.name = song.name or Path(song_rel).stem
    pack.bytes_total = units.file_size(chemin)

    # -- les presets -------------------------------------------------------- #
    vus_presets: set[str] = set()
    for kind, name, folder in song.preset_refs():
        # Une piste audio, MIDI ou CV porte parfois un nom, mais aucun preset
        # à copier : la chercher dans SYNTHS la déclarait « introuvable ».
        if not name or kind not in ("sound", "kit"):
            continue
        trouve = _find_preset(sd, kind, name, folder)
        if not trouve:
            etiquette = "%s/%s" % (folder or ("KITS" if kind == "kit"
                                              else "SYNTHS"), name)
            if etiquette not in pack.missing_presets:
                pack.missing_presets.append(etiquette)
            continue
        cle = norm_rel(trouve)
        if cle in vus_presets:
            continue
        vus_presets.add(cle)
        pack.presets.append(trouve)
        pack.bytes_total += units.file_size(sd.abs(trouve))

    # -- les échantillons --------------------------------------------------- #
    attendus: list[str] = list(song.sample_paths())
    for preset in pack.presets:
        attendus += _samples_of_preset(sd, preset)

    vus_samples: set[str] = set()
    for ref in attendus:
        if not ref:
            continue
        cle = norm_rel(ref)
        if cle in vus_samples:
            continue
        vus_samples.add(cle)
        reel = sd.resolve_sample(ref)
        if reel is None:
            pack.missing_samples.append(ref)
            continue
        rel = sd.rel(reel)
        pack.samples.append(rel)
        pack.bytes_total += units.file_size(reel)

    pack.presets.sort()
    pack.samples.sort()
    return pack


def write_pack(sd: SDCard, pack: SongPack, dest: Path,
               apply: bool = False, progress=None,
               should_stop=None) -> tuple[list[str], list[str]]:
    """Copie l'ensemble dans ``dest``, arborescence conservée.

    Retourne ``(fichiers copiés, erreurs)``. Avec ``apply=False``, rien n'est
    écrit : seule la liste prévue est retournée.

    Le dossier produit a la forme d'une carte (``SONGS/``, ``SYNTHS/``,
    ``KITS/``, ``SAMPLES/``) : le recopier à la racine d'une autre carte
    suffit à y jouer le morceau.
    """
    if not pack or not pack.files():
        return [], ["Rien à copier."]

    cible = Path(dest)
    prevus = pack.files()
    if not apply:
        return prevus, []

    copies: list[str] = []
    erreurs: list[str] = []
    total = len(prevus)
    for index, rel in enumerate(prevus, 1):
        if should_stop is not None and should_stop():
            log.info("copie interrompue après %d fichier(s)", index - 1)
            break
        if progress is not None:
            progress((index, total, Path(rel).name))

        source = sd.abs(rel)
        if not source.is_file():
            # Un échantillon peut n'être trouvable qu'à la casse près.
            trouve = sd.resolve_sample(rel)
            if trouve is None:
                erreurs.append("%s : introuvable" % rel)
                continue
            source = trouve

        destination = cible / rel
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            copies.append(rel)
        except OSError as exc:
            erreurs.append("%s : %s" % (rel, exc))

    return copies, erreurs
