# -*- coding: utf-8 -*-
"""Les brouillons de l'atelier : ses morceaux, gardés sur l'ordinateur.

L'atelier ne tenait qu'un morceau. Recomposer, ou ouvrir un morceau de la
carte, remplaçait celui en cours — ses sons retouchés, ses clips dessinés,
sa structure — et seul [Défaire] le rendait, le temps de la séance. Écrit
sur la carte puis rouvert, il revenait figé : ses pistes appartenaient au
morceau, plus à l'atelier.

Chaque morceau remplacé ou écrit est désormais **rangé** ici, et se rouvre
tel qu'il était. Un brouillon, ce sont deux fichiers du dossier que
l'appelant désigne (``atelier/brouillons``, dans le dossier de configuration
de l'application) :

* ``<ident>.pickle`` — le projet entier (:func:`atelier.dump_draft`) ;
* ``<ident>.json`` — sa fiche : nom, genre, tonalité, durée, date. La liste
  des brouillons se lit dans les fiches, sans rouvrir un seul projet.

``ident`` est celui du projet (:attr:`atelier.Project.ident`) : ranger deux
fois le même morceau remplace son brouillon au lieu d'en faire un second.

Comme le brouillon de la séance, ces fichiers ne se lisent que depuis le
dossier de configuration, qui les a écrits : ``pickle`` exécute ce qu'on lui
donne, et rien ici ne vient d'ailleurs.

Module sans Qt.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..i18n import tr
from . import atelier

log = logging.getLogger(__name__)

__all__ = ["KEEP", "Entry", "shelve", "entries", "load", "remove", "prune"]

#: Brouillons gardés au plus. Au-delà, les plus anciens partent — d'abord
#: ceux qui n'ont été ni retouchés ni écrits sur la carte.
KEEP = 40

_IDENT = re.compile(r"^[0-9a-f]{8,64}$")


@dataclass
class Entry:
    """Un brouillon rangé, tel que sa fiche le décrit."""

    ident: str
    name: str = ""
    #: Instant du rangement (``time.time()``).
    saved: float = 0.0
    #: La fiche entière : genre, tonique, gamme, mesures, tempo, étape…
    meta: dict = field(default_factory=dict)

    @property
    def worked(self) -> bool:
        """Retouché depuis sa composition, ou écrit sur la carte."""
        return bool(self.meta.get("written")) \
            or int(self.meta.get("edits") or 0) > 0


def _paths(base: Path, ident: str) -> tuple[Path, Path]:
    if not _IDENT.match(str(ident or "")):
        raise ValueError(tr("brouillon inconnu"))
    base = Path(base)
    return base / ("%s.pickle" % ident), base / ("%s.json" % ident)


def _write(path: Path, data: bytes) -> None:
    """Écrit d'un seul geste : un fichier à moitié écrit ne remplace
    jamais le précédent."""
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def shelve(base: Path, project: atelier.Project, meta: dict | None = None,
           keep: int = KEEP) -> Entry:
    """Range ``project`` parmi les brouillons, sous son identifiant, et rend
    sa fiche. Un brouillon du même morceau est remplacé ; au-delà de
    ``keep`` brouillons, les plus anciens partent (:func:`prune`)."""
    card = dict(meta or {})
    card["ident"] = project.ident
    card.setdefault("name", project.song_name or "")
    card["written"] = bool(project.written)
    card["edits"] = int(getattr(project, "edits", 0) or 0)
    card["saved"] = time.time()
    data, sheet = _paths(base, project.ident)
    Path(base).mkdir(parents=True, exist_ok=True)
    _write(data, atelier.dump_draft(project, card))
    _write(sheet, json.dumps(card, ensure_ascii=False,
                             indent=1).encode("utf-8"))
    prune(base, keep)
    return Entry(ident=project.ident, name=str(card.get("name") or ""),
                 saved=float(card["saved"]), meta=card)


def entries(base: Path) -> list[Entry]:
    """Les brouillons rangés, le plus récent d'abord. Une fiche illisible,
    ou sans son projet, est passée."""
    base = Path(base)
    out: list[Entry] = []
    if not base.is_dir():
        return out
    for sheet in base.glob("*.json"):
        ident = sheet.stem
        if not _IDENT.match(ident) \
                or not sheet.with_suffix(".pickle").is_file():
            continue
        try:
            card = json.loads(sheet.read_text(encoding="utf-8"))
            if not isinstance(card, dict):
                continue
            out.append(Entry(ident=ident, name=str(card.get("name") or ""),
                             saved=float(card.get("saved") or 0.0),
                             meta=card))
        except (OSError, ValueError, TypeError) as exc:
            log.debug("fiche de brouillon illisible (%s) : %s", sheet.name,
                      exc)
    out.sort(key=lambda e: (-e.saved, e.ident))
    return out


def load(base: Path, ident: str) -> tuple[atelier.Project, dict]:
    """Le projet d'un brouillon et sa fiche. ``ValueError`` s'il est
    illisible ou d'une autre version, ``OSError`` s'il a disparu."""
    data, _sheet = _paths(base, ident)
    return atelier.load_draft(data.read_bytes())


def remove(base: Path, ident: str) -> bool:
    """Retire un brouillon. Rend vrai s'il existait."""
    found = False
    for path in _paths(base, ident):
        try:
            path.unlink()
            found = True
        except FileNotFoundError:
            pass
    return found


def prune(base: Path, keep: int = KEEP) -> int:
    """Ne garde que ``keep`` brouillons. Partent d'abord les plus anciens
    de ceux qu'on n'a ni retouchés ni écrits sur la carte, puis les plus
    anciens tout court. Rend le nombre de brouillons retirés."""
    kept = entries(base)
    extra = len(kept) - max(0, int(keep))
    if extra <= 0:
        return 0
    oldest_first = sorted(kept, key=lambda e: (e.worked, e.saved))
    removed = 0
    for entry in oldest_first[:extra]:
        try:
            removed += bool(remove(base, entry.ident))
        except OSError as exc:
            log.debug("brouillon non retiré (%s) : %s", entry.ident, exc)
    return removed
