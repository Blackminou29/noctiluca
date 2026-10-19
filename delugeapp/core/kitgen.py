# -*- coding: utf-8 -*-
"""Générateur de kits de batterie.

Assemble un kit en piochant un échantillon par rôle dans la bibliothèque
indexée. Deux façons de faire :

* :func:`build_kit` choisit lui-même les échantillons, par rôle et par genre ;
* :func:`kit_from_folder` prend tout un dossier tel quel, ce qui correspond à
  la façon dont les banques d'échantillons sont livrées.

**Un kit se construit autour d'une banque.** Une batterie sonne juste quand
ses éléments viennent de la même machine ou du même producteur : une grosse
caisse de 909 avec la caisse claire et les charleys de la même 909. La
première version tirait chaque rôle indépendamment, dans les douze premiers
candidats **par ordre alphabétique** : mesuré sur la carte, un kit de dix
rangées mêlait 9,9 dossiers différents, et 62 des 74 grosses caisses ne
sortaient jamais. Désormais :

1. chaque échantillon appartient à une **famille** (:func:`family_of`) — sa
   machine pour la bibliothèque d'usine (« 909 Kick dry » → *909*), son
   dossier pour une banque d'artiste ;
2. une famille principale est tirée parmi celles qui couvrent le mieux les
   rôles demandés, avec une préférence pour les machines du genre
   (:data:`GENRE_AFFINITY`) ;
3. les rôles qu'elle ne couvre pas sont complétés dans les familles voisines,
   jamais par ordre alphabétique.

Les rangées sont réglées **comme le Deluge les crée** (mesuré sur les 523
rangées des 43 kits de la carte) : enveloppe ouverte, ``velocity → volume``,
échantillon joué jusqu'au bout s'il dure moins de deux secondes. La première
version imposait un sustain nul et un decay par rôle, qui coupaient chaque
coup au bout de quelques dixièmes de seconde.
"""

from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass
from pathlib import Path

from ..i18n import N_, untranslated
from .db import Library
from .fixedpoint import from_display
from .genres import genre as get_genre
from .model import Kit, KitRow
from .sdcard import SDCard, norm_rel, safe_deluge_name

log = logging.getLogger(__name__)

#: Rangées d'un kit par défaut, dans l'ordre des pads du Deluge.
DEFAULT_SLOTS: tuple[str, ...] = (
    "Kick", "Snare", "HatC", "HatO", "Clap", "Rim",
    "TomL", "TomM", "TomH", "Crash", "Ride", "Shaker",
)

#: Rangées conseillées par genre, quand le genre a des habitudes marquées.
GENRE_SLOTS: dict[str, tuple[str, ...]] = {
    "acid": ("Kick", "Snare", "HatC", "HatO", "Clap", "Cowbell",
             "TomL", "TomM", "Rim", "Crash"),
    "techno": ("Kick", "Clap", "HatC", "HatO", "Snare", "Rim",
               "TomL", "Crash", "Shaker", "Ride"),
    "minimal": ("Kick", "HatC", "Clap", "Rim", "Shaker", "Block",
                "Claves", "HatO"),
    "house": ("Kick", "Clap", "HatC", "HatO", "Snare", "Shaker",
              "Cowbell", "TomM", "Rim", "Ride"),
    "deep_house": ("Kick", "Clap", "HatC", "HatO", "Shaker", "Rim",
                   "ConH", "ConL", "Snare", "Ride"),
    "dnb": ("Kick", "Snare", "HatC", "HatO", "Rim", "Clap",
            "TomL", "TomM", "Crash", "Ride"),
    "jungle": ("Kick", "Snare", "HatC", "HatO", "Rim", "ConH",
               "ConL", "Shaker", "Crash", "Timpany"),
    "dubstep": ("Kick", "Snare", "HatC", "HatO", "Clap", "Rim",
                "TomL", "Crash", "China", "Ride"),
    "electro": ("Kick", "Snare", "HatC", "HatO", "Clap", "Cowbell",
                "TomL", "TomM", "TomH", "Crash"),
    "industrial": ("Kick", "Snare", "HatC", "Rim", "Crash", "China",
                   "Block", "TomL", "TomM", "Clap"),
    "hardcore": ("Kick", "Snare", "HatC", "HatO", "Clap", "Crash",
                 "China", "TomL", "Rim", "Ride"),
    "lofi": ("Kick", "Snare", "HatC", "HatO", "Rim", "Shaker",
             "Tambourine", "Block", "ConM", "Clap"),
    "boards_of_canada": ("Kick", "Snare", "HatC", "Shaker", "Tambourine",
                         "Block", "ConM", "Rim", "HatO", "Ride"),
}

#: Volume affiché par rôle (0 à 50) : la médiane des vraies rangées de la
#: carte (523 rangées, 43 kits ; 41 kits sur 43 règlent leurs rangées une à
#: une). La grosse caisse n'y passe pas devant — ses échantillons sont déjà
#: les plus forts — et les cymbales restent derrière. Les rôles vus moins de
#: six fois gardent une valeur prudente.
ROLE_VOLUME: dict[str, int] = {
    "Kick": 38, "Snare": 39, "Clap": 38, "Rim": 38, "HatC": 36, "HatO": 32,
    "Crash": 34, "Ride": 30, "China": 32, "TomL": 38, "TomM": 36, "TomH": 39,
    "ConL": 36, "ConM": 36, "ConH": 38, "Cowbell": 38, "Block": 34,
    "Claves": 30, "Shaker": 34, "Tambourine": 36, "Guiro": 32,
    "Timpany": 38, "Other": 38,
}

#: Panoramique affiché par rôle (−25 gauche à +25 droite), médiane des vraies
#: rangées. Grosse caisse, caisse claire, clap et charleys au centre ; les
#: toms en éventail, du grave à droite à l'aigu à gauche ; la ride à droite,
#: la crash et le shaker un peu à gauche.
ROLE_PAN: dict[str, int] = {
    "TomL": 9, "TomM": -2, "TomH": -12, "Ride": 5, "Crash": -3, "China": 4,
    "Shaker": -6, "Tambourine": -3, "Cowbell": -2, "Claves": 9,
    "ConH": -8, "ConM": -4, "Guiro": 5, "Timpany": -6,
}

#: Rôles en polyphonie « choke » : un nouveau coup coupe le précédent, comme
#: un charleston qu'on referme (87 rangées de la carte sur 523 ; les autres
#: sont en « auto »).
CHOKE_ROLES = ("HatC", "HatO")

#: Durée maximale d'un échantillon retenu comme percussion, en secondes. Les
#: cymbales ont droit à plus : leur queue fait leur son.
MAX_SLOT_SECONDS = 4.0
_LONG_ROLES_SECONDS = {"Crash": 8.0, "Ride": 8.0, "China": 8.0,
                       "Timpany": 6.0}

#: Machines et banques qu'un genre appelle, cherchées dans le nom de la
#: famille. Préférence de style, pas une règle : une famille sans affinité
#: reste tirable, simplement moins souvent.
GENRE_AFFINITY: dict[str, tuple[str, ...]] = untranslated({
    "acid": ("909", "808", "r-50"),
    "techno": ("909", "distorted", "ddd1", "deep sky", "r-50"),
    "detroit": ("909", "808", "r100", "drumtraks"),
    "minimal": ("808", "909", "cr78", "kr55", "r-50", "mic kit"),
    "house": ("909", "808", "r100", "linndrum", "y2k"),
    "deep_house": ("909", "808", "linndrum", "hr16"),
    "trance": ("909", "xv5080", "deep sky"),
    "psytrance": ("psy", "909", "xv5080", "deep sky"),
    "dnb": ("xv5080", "linndrum", "sds5", "break"),
    "jungle": ("linndrum", "drumtraks", "break", "xv5080"),
    "dubstep": ("bass music", "xv5080", "deep sky", "808"),
    "ambient": ("mic kit", "cr78", "kr55", "hammond"),
    "berlin_school": ("cr78", "kr55", "rhythmace", "hammond", "sds5"),
    "synthwave": ("linndrum", "sds5", "drumtraks", "ddd1", "rx-5"),
    "lofi": ("cr78", "kr55", "rhythmace", "hammond", "mic kit"),
    "idm": ("sds5", "kr55", "ddd1", "distorted", "clipping"),
    "industrial": ("distorted", "ddd1", "sds5", "xv5080", "totems"),
    "electro": ("808", "ddd1", "r100", "drumtraks"),
    "hardcore": ("distorted", "909"),
    "downtempo": ("hr16", "linndrum", "cr78", "mic kit"),
    "funk": ("linndrum", "drumtraks", "cr78", "hr16"),
    "boards_of_canada": ("cr78", "kr55", "rhythmace", "hammond", "mic kit"),
})

#: Poids d'un rôle dans le choix de la famille principale : mieux vaut une
#: banque qui a la grosse caisse et la caisse claire qu'une qui a trois
#: percussions secondaires.
_ROLE_WEIGHT = {"Kick": 3.0, "Snare": 2.0, "Clap": 1.5, "HatC": 2.0,
                "HatO": 1.0}

#: Mots qui désignent l'instrument dans un nom de fichier d'usine. Ce qui
#: les précède est le nom de la machine : « Sequential Circuits Drumtraks
#: Snare » → *Sequential Circuits Drumtraks*.
_INSTRUMENT_WORDS = (
    "kick", "snare", "closed", "open", "pedal", "hihat", "hi-hat", "hat",
    "clap", "rim", "cymbal", "crash", "ride", "china", "splash", "tom",
    "cowbell", "maraca", "cabasa", "shaker", "percussion", "conga", "bongo",
    "clave", "claves", "block", "agogo", "tambourine", "guiro", "timpani",
    "timpany", "bell", "cuica", "whistle", "triangle", "perc",
)

#: Fichiers numérotés d'usine : ``07-KICK``. Deux chiffres et un tiret, pas
#: davantage — un motif plus large prenait « 909 Snare » pour un numéro.
_NUMBERED_RE = re.compile(r"^\d{2}-[a-z]+$")


@dataclass
class KitSlot:
    """Un emplacement de kit et l'échantillon qui l'occupe."""

    role: str
    rel: str = ""
    name: str = ""
    family: str = ""

    @property
    def filled(self) -> bool:
        """Vrai si un échantillon a été trouvé pour ce rôle."""
        return bool(self.rel)


def suggest_slots(genre: str) -> list[str]:
    """Rangées conseillées pour un genre."""
    key = str(genre or "").strip().lower()
    return list(GENRE_SLOTS.get(key, DEFAULT_SLOTS))


# --------------------------------------------------------------------------- #
# Familles et rôles
# --------------------------------------------------------------------------- #

def _machine_prefix(stem: str) -> str:
    """Nom de machine en tête d'un nom de fichier d'usine, ou ``""``."""
    words = stem.replace("_", " ").split()
    out: list[str] = []
    for word in words:
        if word.lower().strip("-") in _INSTRUMENT_WORDS:
            break
        out.append(word)
    return " ".join(out) if len(out) < len(words) else ""


def family_of(rel: str) -> str:
    """Famille d'un échantillon : la banque, ou la machine, d'où il vient.

    * dans ``SAMPLES/DRUMS/<catégorie>/``, bibliothèque d'usine rangée par
      instrument, la famille est la **machine** nommée en tête du fichier
      (« 909 Kick dry » → ``909``) ; les fichiers numérotés d'usine
      (``07-KICK``) forment la famille ``Synthstrom n°`` ;
    * ailleurs, c'est le **dossier** : une banque d'artiste est un kit.
    """
    path = Path(str(rel or "").replace("\\", "/"))
    parts = [p.lower() for p in path.parts]
    if len(parts) >= 4 and parts[0] == "samples" and parts[1] == "drums":
        stem = path.stem
        if _NUMBERED_RE.match(stem.lower()):
            return N_("Synthstrom n°")
        machine = _machine_prefix(stem)
        if machine:
            return machine
        return "/".join(path.parts[:3])
    return path.parent.as_posix()


def _role_of(row) -> str:
    """Rôle d'un échantillon indexé : sa catégorie de rangement, ou son nom."""
    from .analysis import DRUM_CATEGORIES, classify_drum

    rel = row["rel"]
    parts = norm_rel(rel).split("/")
    if len(parts) >= 4 and parts[0] == "samples" and parts[1] == "drums":
        for category in DRUM_CATEGORIES:
            if category.lower() == parts[2]:
                return category
    try:
        duration = float(row["duration"] or 0.0)
    except (KeyError, IndexError, TypeError, ValueError):
        duration = 0.0
    return classify_drum(Path(rel).name, {"duration": duration}, {})


def _max_seconds(role: str) -> float:
    return _LONG_ROLES_SECONDS.get(role, MAX_SLOT_SECONDS)


def library_families(lib: Library) -> dict[str, dict[str, list]]:
    """``{famille: {rôle: [lignes d'index]}}`` pour toute la bibliothèque.

    Seuls les échantillons courts qu'on sait rattacher à un rôle de
    percussion y figurent.
    """
    families: dict[str, dict[str, list]] = {}
    try:
        rows = lib.search_samples(limit=100000)
    except Exception as exc:  # noqa: BLE001 - index indisponible
        log.debug("bibliothèque illisible pour les kits : %s", exc)
        return families
    for row in rows:
        try:
            duration = float(row["duration"] or 0.0)
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        if duration <= 0:
            continue
        role = _role_of(row)
        if not role or role == "Other" or duration > _max_seconds(role):
            continue
        families.setdefault(family_of(row["rel"]), {}).setdefault(
            role, []).append(row)
    # Ordre stable, indépendant de l'ordre de l'index : la graine seule
    # décide.
    for roles in families.values():
        for rows_of_role in roles.values():
            rows_of_role.sort(key=lambda r: norm_rel(r["rel"]))
    return families


def _affinity(genre: str, family: str) -> float:
    """1 si la famille évoque une machine du genre, 0 sinon."""
    text = family.lower()
    return 1.0 if any(token in text
                      for token in GENRE_AFFINITY.get(genre, ())) else 0.0


def _coverage(roles: dict, wanted: list[str]) -> float:
    """Part pondérée des rôles demandés que la famille sait remplir, 0 à 1."""
    total = sum(_ROLE_WEIGHT.get(role, 1.0) for role in wanted)
    if total <= 0:
        return 0.0
    return sum(_ROLE_WEIGHT.get(role, 1.0) for role in wanted
               if role in roles) / total


def _score(family: str, roles: dict, wanted: list[str], genre: str) -> float:
    """Couverture des rôles, doublée pour une machine du genre.

    Un bonus additif ne suffisait pas : noyé dans la couverture des rôles
    secondaires, il laissait la techno sans 909 et le lo-fi sans CR78.
    """
    coverage = _coverage(roles, wanted)
    if coverage <= 0:
        return 0.0
    return coverage * (2.0 if _affinity(genre, family) else 1.0)


def _draw_family(rng: random.Random, families: dict, wanted: list[str],
                 genre: str, top: int = 6) -> str:
    """Tire une famille parmi les mieux placées, au prorata du carré du score.

    Une famille qui couvre moins de la moitié des rôles demandés n'est
    retenue que faute de mieux : elle ferait un kit maigre.
    """
    scored = sorted(((_score(name, roles, wanted, genre), name,
                      _coverage(roles, wanted))
                     for name, roles in families.items()),
                    key=lambda item: (-item[0], item[1]))
    solid = [(score, name) for score, name, cov in scored
             if score > 0 and cov >= 0.5]
    scored = (solid or [(score, name) for score, name, _c in scored
                        if score > 0])[:top]
    if not scored:
        return ""
    total = sum(score * score for score, _name in scored)
    draw = rng.uniform(0.0, total)
    upto = 0.0
    for score, name in scored:
        upto += score * score
        if draw <= upto:
            return name
    return scored[-1][1]


# --------------------------------------------------------------------------- #
# Construction
# --------------------------------------------------------------------------- #

def build_kit(sd: SDCard, lib: Library, name: str, genre: str = "techno",
              seed: int | None = None, slots: list[str] | None = None,
              prefer_folder: str = "") -> Kit:
    """Assemble un kit cohérent en choisissant un échantillon par rôle.

    :param slots: rôles à remplir ; par défaut ceux conseillés pour le genre.
    :param prefer_folder: dossier à privilégier : la famille principale est
        alors prise dans ce dossier, pour bâtir un kit d'une seule banque.
    :param seed: rend le choix reproductible.

    Les rôles sans candidat sont **omis** plutôt que laissés vides : un kit
    avec des rangées muettes est plus déroutant qu'un kit plus court.
    """
    # Le genre entre dans la graine : sans cela, une même graine donnait la
    # même grosse caisse à tous les genres.
    base = seed if seed is not None else random.randrange(1 << 30)
    rng = random.Random(f"{base}|{genre}")
    wanted = list(slots) if slots else suggest_slots(genre)
    profile = get_genre(genre)

    kit = Kit.new(safe_deluge_name(name or f"KIT {profile.label}"))
    kit.rows = []
    chosen = _choose(lib, wanted, genre, rng, prefer_folder)

    for slot in chosen:
        if not slot.filled:
            log.debug("aucun échantillon pour le rôle %s", slot.role)
            continue
        info = slot.info or {}
        kit_row = kit.add_row(safe_deluge_name(slot.role.upper()), slot.rel,
                              seconds=info.get("duration"),
                              frames=info.get("frames"))
        _tune_row(kit_row, slot.role)

    filled = [s for s in chosen if s.filled]
    log.info("kit « %s » : %d rangée(s) sur %d rôle(s), %d famille(s)",
             kit.name, len(filled), len(wanted),
             len({s.family for s in filled}))
    kit.slots = chosen                       # pour l'affichage
    return kit


@dataclass
class _Chosen(KitSlot):
    """Un emplacement retenu, avec ce que l'index sait de l'échantillon."""

    info: dict | None = None


def _choose(lib: Library, wanted: list[str], genre: str,
            rng: random.Random, prefer_folder: str = "") -> list[_Chosen]:
    """Choisit un échantillon par rôle, banque principale d'abord."""
    families = library_families(lib)
    if prefer_folder:
        prefix = norm_rel(prefer_folder).rstrip("/") + "/"
        preferred = {
            name: {role: [r for r in rows
                          if (norm_rel(r["rel"]) + "/").startswith(prefix)]
                   for role, rows in roles.items()}
            for name, roles in families.items()}
        preferred = {name: {r: rows for r, rows in roles.items() if rows}
                     for name, roles in preferred.items()}
        preferred = {name: roles for name, roles in preferred.items() if roles}
    else:
        preferred = {}

    out: list[_Chosen] = [_Chosen(role=role) for role in wanted]
    missing = set(wanted)
    used: set[str] = set()

    def _fill_from(family: str, pool: dict) -> None:
        roles = pool.get(family, {})
        for slot in out:
            if slot.role not in missing or slot.role not in roles:
                continue
            rows = [r for r in roles[slot.role] if r["rel"] not in used]
            if not rows:
                continue
            row = rng.choice(rows)
            used.add(row["rel"])
            slot.rel = row["rel"]
            slot.name = Path(row["rel"]).stem
            slot.family = family
            slot.info = {"duration": _float(row, "duration"),
                         "frames": _int(row, "frames")}
            missing.discard(slot.role)

    # 1. La famille principale : celle du dossier imposé, sinon la mieux
    #    placée pour le genre (tirée, pour que deux kits diffèrent).
    first_pool = preferred or families
    main = _draw_family(rng, first_pool, wanted, genre)
    if main:
        _fill_from(main, first_pool)

    # 2. Les rôles manquants, famille par famille, au mieux pour ce qui
    #    reste à remplir.
    tried = {main}
    while missing:
        rest = {name: roles for name, roles in families.items()
                if name not in tried
                and any(role in roles for role in missing)}
        if not rest:
            break
        nxt = _draw_family(rng, rest, sorted(missing), genre)
        if not nxt:
            break
        tried.add(nxt)
        _fill_from(nxt, families)
    return out


def _float(row, key: str) -> float | None:
    try:
        value = row[key]
    except (KeyError, IndexError):
        return None
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _int(row, key: str) -> int | None:
    value = _float(row, key)
    return int(value) if value is not None else None


def _tune_row(row: KitRow, role: str) -> None:
    """Règle volume, panoramique et polyphonie d'une rangée selon son rôle.

    L'enveloppe reste celle que pose :meth:`Kit.add_row`, ouverte comme sur
    les vraies rangées : c'est l'échantillon qui porte sa propre extinction.
    """
    sound = row.sound
    sound.set_param("volume", from_display(
        ROLE_VOLUME.get(role, ROLE_VOLUME["Other"]), scale=50))
    sound.set_param("pan", from_display(ROLE_PAN.get(role, 0), bipolar=True,
                                        scale=50))
    sound.polyphonic = "choke" if role in CHOKE_ROLES else "auto"


def row_role(row: KitRow) -> str:
    """Rôle d'une rangée : son nom s'il en est un (``HATC``), sinon son fichier."""
    name = str(row.name or "").strip().lower()
    for role in ROLE_VOLUME:
        if role.lower() == name:
            return role
    rel = row.file_name
    return _role_of({"rel": rel, "duration": None}) if rel else "Other"


def reroll_row(kit: Kit, index: int, lib: Library, genre: str = "techno",
               seed=None, avoid=()) -> KitSlot | None:
    """Remplace l'échantillon d'une rangée par un autre du même rôle.

    Le remplaçant vient de la **même famille** quand elle en a un autre —
    le kit garde sa couleur —, sinon des familles qui conviennent au genre.
    Jamais un échantillon déjà présent dans le kit, ni un de ``avoid`` —
    ceux déjà essayés pour cette rangée : sans eux, une famille de deux
    caisses claires faisait la navette entre les deux à chaque clic. Nom,
    volume, panoramique et polyphonie suivent le rôle, comme à la
    construction.

    :returns: le nouvel emplacement, ou ``None`` si la bibliothèque n'a pas
        d'autre candidat (la rangée est alors laissée telle quelle).
    """
    if not 0 <= int(index) < len(kit.rows):
        return None
    old = kit.rows[index]
    role = row_role(old)
    rng = random.Random(seed if seed is not None
                        else random.randrange(1 << 30))
    families = library_families(lib)
    used = {norm_rel(r.file_name) for r in kit.rows if r.file_name}
    used |= {norm_rel(rel) for rel in avoid if rel}

    def _free(family: str) -> list:
        return [r for r in families.get(family, {}).get(role, [])
                if norm_rel(r["rel"]) not in used]

    family = family_of(old.file_name) if old.file_name else ""
    candidates = _free(family) if family else []
    if not candidates:
        rest = {name: roles for name, roles in families.items()
                if name != family and _free(name)}
        family = _draw_family(rng, rest, [role], genre)
        candidates = _free(family) if family else []
    if not candidates:
        return None

    chosen = rng.choice(candidates)
    tmp = Kit.new("TMP")
    tmp.rows = []
    new_row = tmp.add_row(old.name or safe_deluge_name(role.upper()),
                          chosen["rel"], seconds=_float(chosen, "duration"),
                          frames=_int(chosen, "frames"))
    _tune_row(new_row, role)
    kit.rows[index] = new_row
    slot = KitSlot(role=role, rel=chosen["rel"], name=Path(chosen["rel"]).stem,
                   family=family)
    for k, existing in enumerate(getattr(kit, "slots", None) or []):
        if norm_rel(existing.rel or "") == norm_rel(old.file_name or "")                 and existing.rel:
            kit.slots[k] = _Chosen(role=role, rel=slot.rel, name=slot.name,
                                   family=family,
                                   info={"duration": _float(chosen, "duration"),
                                         "frames": _int(chosen, "frames")})
            break
    return slot


def kit_from_folder(sd: SDCard, folder: str, name: str = "") -> Kit:
    """Crée un kit depuis tous les échantillons d'un dossier.

    Les fichiers sont pris dans l'ordre alphabétique, ce qui respecte la
    numérotation des banques (``01 Kick``, ``02 Snare``…). Le rôle de chaque
    rangée est déduit du nom du fichier, et sa durée lue dans le fichier.
    """
    from .analysis import classify_drum
    from . import wav

    base = sd.resolve_sample(folder)
    kit = Kit.new(safe_deluge_name(name or (base.name if base else "KIT")))
    kit.rows = []
    if base is None or not base.is_dir():
        log.warning("dossier introuvable pour le kit : %r", folder)
        return kit

    from .sdcard import AUDIO_EXT, _is_ignored_file

    files = sorted(
        (p for p in base.iterdir()
         if p.is_file() and not _is_ignored_file(p.name)
         and p.suffix.lower() in AUDIO_EXT),
        key=lambda p: p.name.lower())

    for path in files[:64]:        # le Deluge n'affiche pas plus de pads
        rel = sd.rel(path)
        info = wav.probe(path)
        seconds = info.duration if info.ok else None
        role = classify_drum(path.name, {"duration": seconds or 0.5}, {})
        row = kit.add_row(safe_deluge_name(path.stem.upper())[:32], rel,
                          seconds=seconds,
                          frames=info.frames if info.ok else None)
        _tune_row(row, role)

    log.info("kit « %s » : %d rangée(s) depuis %s", kit.name, len(kit.rows),
             folder)
    return kit
