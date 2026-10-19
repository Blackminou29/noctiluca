# -*- coding: utf-8 -*-
"""Dépendances entre fichiers de la carte.

Un preset, un kit ou un morceau référence des échantillons par leur chemin.
Déplacer ou renommer un échantillon casse donc silencieusement tout ce qui
l'utilisait — le Deluge se contente de ne plus rien jouer. Ce module sait :

* qui utilise quoi (:func:`build_graph`) ;
* réécrire une référence dans **tous** les XML concernés (:func:`relink`) ;
* proposer un remplaçant pour une référence cassée
  (:func:`find_replacement`).

Toutes les comparaisons de chemins passent par
:func:`~delugeapp.core.sdcard.norm_rel`, la casse des ``fileName`` n'étant pas
fiable (cf. SPEC §1.7).

**Rien n'est écrit sans ``apply=True``** : par défaut, les fonctions de
modification retournent la liste de ce qu'elles feraient (cf. SPEC §0.2).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable

from ..i18n import tr
from . import dxml
from .db import Library
from .model import Song
from .sdcard import SDCard, norm_rel

log = logging.getLogger(__name__)

#: Attribut (ou élément) portant un chemin d'échantillon dans les XML Deluge.
FILENAME_KEY = "fileName"

#: Écart de durée toléré pour proposer un remplaçant, en secondes.
DURATION_TOLERANCE = 0.25

#: Similarité de nom minimale pour proposer un remplaçant.
NAME_SIMILARITY = 0.6


@dataclass
class DepGraph:
    """Qui utilise quoi, sur toute la carte.

    :param used_by: ``norm_rel(échantillon)`` -> ``[(nature, chemin source)]`` ;
    :param missing: ``[(nature, source, échantillon)]`` pour les références
        introuvables ;
    :param unused: chemins des échantillons qu'aucun fichier n'utilise.
    """

    used_by: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    missing: list[tuple[str, str, str]] = field(default_factory=list)
    unused: list[str] = field(default_factory=list)

    def usage_count(self, rel: str) -> int:
        """Nombre de fichiers qui utilisent cet échantillon."""
        return len(self.used_by.get(norm_rel(rel), ()))

    def users_of(self, rel: str) -> list[tuple[str, str]]:
        """``[(nature, chemin)]`` des fichiers qui utilisent cet échantillon."""
        return list(self.used_by.get(norm_rel(rel), ()))

    def missing_by_sample(self) -> dict[str, list[tuple[str, str]]]:
        """Références cassées regroupées par échantillon attendu."""
        out: dict[str, list[tuple[str, str]]] = {}
        for kind, source, sample in self.missing:
            out.setdefault(sample, []).append((kind, source))
        return out

    def summary(self) -> str:
        """Phrase de bilan, pour la barre d'état."""
        return (tr("%d échantillons utilisés, %d inutilisés, %d références "
                   "cassées")
                % (len(self.used_by), len(self.unused), len(self.missing)))


def build_graph(sd: SDCard, lib: Library) -> DepGraph:
    """Construit le graphe des dépendances depuis l'index.

    Lit la table ``links`` remplie par l'analyse plutôt que de relire la carte :
    c'est immédiat, et l'index est déjà à jour après un ``scan_card``.
    """
    graph = DepGraph()
    try:
        rows = lib.con.execute(
            "SELECT src_kind, src_rel, dst_rel, dst_norm, missing FROM links"
        ).fetchall()
    except Exception as exc:  # noqa: BLE001 - base illisible : graphe vide
        log.error("lecture des dépendances impossible : %s", exc)
        return graph

    for row in rows:
        key = row["dst_norm"] or norm_rel(row["dst_rel"])
        entry = (row["src_kind"], row["src_rel"])
        if row["missing"]:
            graph.missing.append(
                (row["src_kind"], row["src_rel"], row["dst_rel"]))
        else:
            graph.used_by.setdefault(key, []).append(entry)

    try:
        graph.unused = [r["rel"] for r in lib.unused_samples()]
    except Exception as exc:  # noqa: BLE001
        log.debug("liste des échantillons inutilisés indisponible : %s", exc)
    return graph


# --------------------------------------------------------------------------- #
# Lecture des dépendances d'un morceau
# --------------------------------------------------------------------------- #

def samples_of_song(song: Song) -> list[str]:
    """Échantillons référencés par un morceau, sans doublon."""
    return song.sample_paths()


def presets_of_song(song: Song) -> list[tuple[str, str]]:
    """``[(dossier, nom)]`` des presets utilisés par un morceau."""
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for _kind, name, folder in song.preset_refs():
        key = (folder, name)
        if name and key not in seen:
            seen.add(key)
            out.append(key)
    return out


# --------------------------------------------------------------------------- #
# Réécriture des références
# --------------------------------------------------------------------------- #

def _xml_files(sd: SDCard) -> list[Path]:
    """Tous les XML susceptibles de référencer un échantillon."""
    return sd.synths() + sd.kits() + sd.songs()


def _retarget_element(el, old_norm: str, new_rel: str) -> int:
    """Remplace ``fileName`` dans un élément et ses descendants.

    Retourne le nombre de remplacements effectués.
    """
    count = 0
    for node in el.iter():
        value = dxml.get(node, FILENAME_KEY)
        if value and norm_rel(value) == old_norm:
            # Le dialecte est préservé : ``set_`` écrit là où la valeur était.
            dialect = "elem" if dxml.get_child(node, FILENAME_KEY) is not None else "attr"
            dxml.set_(node, FILENAME_KEY, new_rel, dialect)
            count += 1
    return count


def _xml_escaped(text: str) -> str:
    """Forme échappée d'un nom, telle qu'un attribut XML peut la contenir."""
    return (text.replace("&", "&amp;").replace("'", "&apos;")
            .replace('"', "&quot;"))


def relink(sd: SDCard, old_rel: str, new_rel: str, apply: bool = False,
           progress: Callable[[str], None] | None = None,
           ) -> list[tuple[Path, int]]:
    """Fait pointer vers ``new_rel`` tout ce qui référençait ``old_rel``.

    :param apply: ``False`` (défaut) ne touche à rien et retourne seulement ce
        qui serait modifié — c'est la règle du §0.2 de la SPEC.
    :returns: ``[(fichier, nombre de remplacements)]``, fichiers inchangés
        exclus.

    L'écriture passe par ``dxml.save``, donc avec sauvegarde ``.bak`` et
    écriture atomique, et **conserve le dialecte XML d'origine**.
    """
    if apply:
        sd.require_writable()
    old_norm = norm_rel(old_rel)
    new_clean = str(new_rel or "").replace("\\", "/").strip("/")
    changes: list[tuple[Path, int]] = []
    if not old_norm or not new_clean:
        log.warning("relink appelé avec un chemin vide (%r -> %r)",
                    old_rel, new_rel)
        return changes

    for path in _xml_files(sd):
        if progress is not None:
            try:
                progress(path.name)
            except Exception:  # noqa: BLE001 - l'affichage ne bloque rien
                pass
        try:
            raw = path.read_bytes()
        except OSError as exc:
            log.debug("fichier illisible %s : %s", path, exc)
            continue
        # Filtre rapide : inutile de parser un XML qui ne cite pas le nom.
        name = Path(old_norm).name
        low = raw.lower()
        if name and not any(
                form.encode("utf-8", "replace").lower() in low
                for form in (name, _xml_escaped(name))):
            continue

        try:
            doc = dxml.loads(raw, path)
        except Exception as exc:  # noqa: BLE001 - XML abîmé : on passe
            log.debug("XML illisible %s : %s", path, exc)
            continue

        count = _retarget_element(doc.root, old_norm, new_clean)
        if not count:
            continue
        changes.append((path, count))
        if apply:
            try:
                dxml.save(doc, path, backup=True)
            except Exception as exc:  # noqa: BLE001
                log.error("écriture impossible dans %s : %s", path, exc)
                changes[-1] = (path, 0)

    if apply:
        sd.invalidate_cache()
    log.info("relink %s -> %s : %d fichier(s)%s", old_rel, new_rel,
             len(changes), "" if apply else " (simulation)")
    return changes


# --------------------------------------------------------------------------- #
# Recherche d'un remplaçant
# --------------------------------------------------------------------------- #

def _similarity(a: str, b: str) -> float:
    """Similarité de deux noms, entre 0 et 1."""
    return SequenceMatcher(None, a, b).ratio()


def _strip_noise(stem: str) -> str:
    """Retire d'un nom les numéros et mentions qui ne l'identifient pas."""
    text = stem.lower()
    text = re.sub(r"\b(\d{1,3})\b", " ", text)
    text = re.sub(r"[^a-z]+", " ", text)
    return " ".join(text.split())


class SampleIndex:
    """Index des échantillons, préparé une fois pour plusieurs recherches.

    Chercher un remplaçant sans index coûte une comparaison de similarité par
    échantillon : pour les 125 références cassées de cette carte et ses
    1 741 échantillons, cela faisait **217 000 comparaisons** et près de dix
    secondes. L'index ramène le cas courant — un fichier retrouvé sous le
    même nom ailleurs — à une simple consultation de dictionnaire.
    """

    def __init__(self, rows) -> None:
        #: nom de fichier en minuscules -> chemins
        self.by_name: dict[str, list[str]] = {}
        #: nom réduit (sans chiffres ni ponctuation) -> chemins
        self.by_core: dict[str, list[str]] = {}
        #: (chemin, radical en minuscules, dossier normalisé)
        self.entries: list[tuple[str, str, str]] = []

        for row in rows or ():
            try:
                rel = row["rel"]
            except (TypeError, KeyError, IndexError):
                continue
            if not rel:
                continue
            path = Path(rel)
            name = path.name.lower()
            stem = path.stem.lower()
            folder = norm_rel(str(path.parent))
            self.by_name.setdefault(name, []).append(rel)
            core = _strip_noise(path.stem)
            if core:
                self.by_core.setdefault(core, []).append(rel)
            self.entries.append((rel, stem, folder))

    def __len__(self) -> int:
        return len(self.entries)


def find_replacement(sd: SDCard, missing_rel: str, lib: Library,
                     rows: list | None = None,
                     index: "SampleIndex | None" = None) -> list[str]:
    """Remplaçants possibles pour une référence cassée, du meilleur au moins bon.

    Trois pistes, par ordre de confiance :

    1. **même nom de fichier ailleurs sur la carte** — c'est le cas d'un
       dossier simplement déplacé, et de loin le plus fréquent ;
    2. **même dossier d'origine, nom proche** — un fichier renommé ;
    3. **nom proche n'importe où**, une fois le bruit retiré (numéros, tirets).

    Ne propose jamais un fichier qui n'existe pas réellement.

    :param rows: échantillons déjà lus dans l'index de la carte.
    :param index: :class:`SampleIndex` déjà construit. Le fournir est ce qui
        rend la recherche en lot rapide : la première piste devient une
        consultation de dictionnaire au lieu d'un parcours complet.
    """
    target = str(missing_rel or "").replace("\\", "/").strip("/")
    if not target:
        return []
    path = Path(target)
    wanted_name = path.name.lower()
    wanted_stem = path.stem.lower()
    wanted_folder = norm_rel(str(path.parent))
    wanted_core = _strip_noise(path.stem)

    if index is None:
        if rows is None:
            try:
                rows = lib.search_samples(limit=100000)
            except Exception as exc:  # noqa: BLE001
                log.debug("index indisponible pour la recherche de "
                          "remplaçant : %s", exc)
                rows = []
        index = SampleIndex(rows)

    # 1. Même nom de fichier : le cas du dossier déplacé.
    exact = [rel for rel in index.by_name.get(wanted_name, ())
             if norm_rel(rel) != norm_rel(target)]
    if exact:
        # Le dossier le plus ressemblant d'abord, puis le chemin le plus court.
        exact.sort(key=lambda r: (-_similarity(norm_rel(str(Path(r).parent)),
                                               wanted_folder), len(r)))
        return exact[:20]

    # 2. Même nom réduit : « 01 Kick.wav » contre « Kick 1.wav ».
    core_hits = [rel for rel in index.by_core.get(wanted_core, ())
                 if norm_rel(rel) != norm_rel(target)] if wanted_core else []

    # 3. Nom approchant. C'est la seule piste coûteuse, donc la dernière.
    same_folder: list[tuple[float, str]] = []
    similar: list[tuple[float, str]] = []
    for rel, stem, folder in index.entries:
        if norm_rel(rel) == norm_rel(target):
            continue
        score = _similarity(stem, wanted_stem)
        if score < NAME_SIMILARITY:
            continue
        if folder == wanted_folder:
            same_folder.append((score, rel))
        else:
            similar.append((score, rel))
    same_folder.sort(reverse=True)
    similar.sort(reverse=True)

    out: list[str] = []
    for rel in (core_hits + [r for _s, r in same_folder]
                + [r for _s, r in similar]):
        if rel not in out:
            out.append(rel)
    return out[:20]


def relink_many(sd: SDCard, mapping: dict[str, str], apply: bool = False,
                progress: Callable[[str], None] | None = None,
                failures: list[str] | None = None,
                ) -> list[tuple[Path, int]]:
    """Applique plusieurs réaffectations en **un seul passage par fichier**.

    C'est la version à utiliser pour réparer une carte : appeler
    :func:`relink` en boucle rouvre et ré-enregistre le même XML à chaque
    référence, ce qui crée autant de sauvegardes ``.bak`` qu'il y a de
    références — 125 fichiers ``.bak`` pour 10 presets sur cette carte. Ici,
    chaque fichier est lu, modifié et écrit une fois, donc une seule
    sauvegarde par fichier réellement touché.

    :param mapping: ``{ancien chemin: nouveau chemin}``.
    :param apply: ``False`` (défaut) simule sans rien écrire.
    :param failures: reçoit, en français, chaque XML qui cite peut-être un
        des fichiers mais n'a pas pu être lu ou réécrit. L'appelant qui
        s'apprête à supprimer les anciens fichiers **doit** le consulter :
        une référence non redirigée devient une référence cassée.
    :returns: ``[(fichier, nombre total de remplacements)]``.
    """
    if apply:
        sd.require_writable()
    table = {norm_rel(old): str(new or "").replace("\\", "/").strip("/")
             for old, new in (mapping or {}).items()
             if old and new}
    changes: list[tuple[Path, int]] = []
    if not table:
        return changes

    # Noms de fichiers recherchés, pour écarter vite les XML non concernés.
    # Le nom figure parfois échappé dans le XML (``&amp;``) : on cherche les
    # deux formes, sinon ces fichiers n'étaient jamais réécrits.
    needles: set[bytes] = set()
    for key in table:
        name = Path(key).name
        if name:
            for form in (name, _xml_escaped(name)):
                needles.add(form.encode("utf-8", "replace").lower())

    def _fail(text: str) -> None:
        if failures is not None:
            failures.append(text)

    for path in _xml_files(sd):
        if progress is not None:
            try:
                progress(path.name)
            except Exception:  # noqa: BLE001
                pass
        try:
            raw = path.read_bytes()
        except OSError as exc:
            log.warning("fichier illisible %s : %s", path, exc)
            _fail(tr("%s : illisible (%s)") % (sd.rel(path), exc))
            continue
        low = raw.lower()
        if not any(n in low for n in needles):
            continue
        try:
            doc = dxml.loads(raw, path)
        except Exception as exc:  # noqa: BLE001
            log.warning("XML illisible %s : %s", path, exc)
            _fail(tr("%s : XML illisible (%s)") % (sd.rel(path), exc))
            continue

        count = 0
        for node in doc.root.iter():
            value = dxml.get(node, FILENAME_KEY)
            if not value:
                continue
            new_rel = table.get(norm_rel(value))
            if not new_rel:
                continue
            dialect = ("elem" if dxml.get_child(node, FILENAME_KEY) is not None
                       else "attr")
            dxml.set_(node, FILENAME_KEY, new_rel, dialect)
            count += 1

        if not count:
            continue
        if apply:
            try:
                dxml.save(doc, path, backup=True)
            except Exception as exc:  # noqa: BLE001
                log.error("écriture impossible dans %s : %s", path, exc)
                _fail(tr("%s : écriture impossible (%s)")
                      % (sd.rel(path), exc))
                continue
        changes.append((path, count))

    if apply:
        sd.invalidate_cache()
    log.info("relink_many : %d référence(s) dans %d fichier(s)%s",
             sum(n for _p, n in changes), len(changes),
             "" if apply else " (simulation)")
    return changes


def find_replacements_bulk(sd: SDCard, lib: Library,
                           progress: Callable[[str], None] | None = None,
                           ) -> dict[str, list[str]]:
    """Remplaçants pour toutes les références cassées de la carte.

    L'index des échantillons est bâti **une seule fois** puis réutilisé : sans
    cela, la recherche en lot refait un parcours complet par référence
    cassée, ce qui prenait près de dix secondes sur cette carte.
    """
    graph = build_graph(sd, lib)
    try:
        rows = lib.search_samples(limit=100000)
    except Exception as exc:  # noqa: BLE001
        log.debug("index indisponible : %s", exc)
        rows = []
    index = SampleIndex(rows)

    out: dict[str, list[str]] = {}
    for sample in graph.missing_by_sample():
        if progress is not None:
            try:
                progress(sample)
            except Exception:  # noqa: BLE001
                pass
        out[sample] = find_replacement(sd, sample, lib, index=index)
    return out
