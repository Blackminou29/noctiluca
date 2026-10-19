# -*- coding: utf-8 -*-
"""Recherche d'échantillons par ressemblance sonore.

Sur une bibliothèque de 1 700 fichiers, le nom et le dossier ne suffisent
plus : on cherche « un kick comme celui-là », pas un kick au hasard. Ce
module compare les descripteurs acoustiques que l'analyse a déjà mesurés et
que l'index conserve depuis le schéma 4.

**Tout se fait sur l'index, sans relire la carte.** Les huit descripteurs
tiennent en huit nombres par échantillon : comparer 1 741 fichiers coûte une
soustraction de matrices, là où une relecture de la carte coûterait des
minutes.

Le descripteur, et pourquoi chacun :

===============  ========================================================
``centroid``     centre de gravité du spectre : la brillance
``rolloff``      fréquence sous laquelle tient 85 % de l'énergie
``flatness``     0 pour un son tonal, 1 pour du bruit
``bandwidth``    étalement du spectre autour du centroïde
``low_ratio``    part d'énergie sous 200 Hz : un kick contre un charleston
``high_ratio``   part d'énergie au-dessus de 5 kHz
``crest``        rapport crête/RMS : percussif contre compressé ou tenu
``attack``       temps jusqu'à la crête : la seule mesure temporelle, et
                 celle qui sépare le mieux une percussion d'une nappe
===============  ========================================================

Les grandeurs en hertz et en secondes passent par un logarithme : l'oreille
entend des rapports, pas des différences. Un centroïde de 200 Hz est aussi
loin de 400 Hz que 2 kHz de 4 kHz, ce qu'une distance linéaire ignorerait
complètement.

Chaque dimension est ensuite ramenée à l'écart-type de la bibliothèque, pour
qu'aucune ne pèse plus qu'une autre du seul fait de son unité.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import numpy as np

from ..i18n import tr
from .db import Library
from .sdcard import norm_rel

log = logging.getLogger(__name__)

__all__ = [
    "Match", "Space",
    "FEATURES", "LOG_FEATURES", "WEIGHTS",
    "build_space", "similar", "describe",
]

#: Les descripteurs comparés, dans l'ordre du vecteur.
FEATURES = ("centroid", "rolloff", "flatness", "bandwidth",
            "low_ratio", "high_ratio", "crest", "attack")

#: Ceux qui s'entendent en rapports, et passent donc au logarithme.
LOG_FEATURES = frozenset({"centroid", "rolloff", "bandwidth", "crest",
                          "attack"})

#: Poids par descripteur. Le contenu grave et le temps d'attaque décident
#: plus que le reste de « ça sonne pareil » : un kick et un tom partagent
#: leur platitude spectrale, pas leur grave ni leur attaque.
WEIGHTS = {
    "centroid": 1.3,
    "rolloff": 1.0,
    "flatness": 0.8,
    "bandwidth": 0.7,
    "low_ratio": 1.4,
    "high_ratio": 1.1,
    "crest": 0.9,
    "attack": 1.3,
}

#: Valeur plancher avant le logarithme, pour ne jamais prendre log(0).
_FLOOR = 1e-4


@dataclass
class Match:
    """Un voisin trouvé."""

    rel: str
    distance: float
    row: object = None

    @property
    def closeness(self) -> int:
        """Ressemblance en pourcentage, pour l'affichage.

        Purement indicative : c'est une distance repliée sur 0–100, pas une
        probabilité.
        """
        return int(round(100.0 * math.exp(-max(0.0, self.distance))))


@dataclass
class Space:
    """La bibliothèque réduite à ses descripteurs, prête à être comparée."""

    rels: list[str] = field(default_factory=list)
    vectors: np.ndarray = field(
        default_factory=lambda: np.zeros((0, len(FEATURES)), dtype=np.float32))
    rows: dict[str, object] = field(default_factory=dict)
    index: dict[str, int] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.rels)

    def __bool__(self) -> bool:
        return bool(self.rels)

    def has(self, rel: str) -> bool:
        """Vrai si cet échantillon a des descripteurs utilisables."""
        return norm_rel(rel) in self.index


def _value(row, key: str) -> float | None:
    """Lit un descripteur d'une ligne d'index, ou ``None`` s'il manque."""
    try:
        raw = row[key]
    except (KeyError, IndexError, TypeError):
        return None
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return None if not math.isfinite(value) else value


def _raw_vector(row) -> np.ndarray | None:
    """Le vecteur brut d'une ligne, ou ``None`` si l'analyse manque.

    Un seul descripteur absent suffit à écarter la ligne : comparer un
    vecteur incomplet à des vecteurs complets donnerait des voisins faux
    sans que rien ne le signale.
    """
    out = np.empty(len(FEATURES), dtype=np.float64)
    for position, name in enumerate(FEATURES):
        value = _value(row, name)
        if value is None:
            return None
        if name in LOG_FEATURES:
            value = math.log10(max(value, _FLOOR))
        out[position] = value
    return out


def build_space(lib: Library, rows: list | None = None,
                folder: str = "", category: str = "") -> Space:
    """Construit l'espace de comparaison depuis l'index.

    ``folder`` et ``category`` restreignent la population — utile pour
    chercher « parmi les kicks » plutôt que dans toute la carte. La
    normalisation se fait alors sur cette population, ce qui est voulu : les
    écarts significatifs entre deux kicks ne sont pas ceux qui séparent un
    kick d'une nappe.
    """
    lignes = rows if rows is not None else lib.search_samples(
        folder=folder, category=category, limit=100000)

    rels: list[str] = []
    bruts: list[np.ndarray] = []
    gardees: dict[str, object] = {}
    for row in lignes:
        vecteur = _raw_vector(row)
        if vecteur is None:
            continue
        try:
            rel = str(row["rel"])
        except (KeyError, IndexError, TypeError):
            continue
        cle = norm_rel(rel)
        if cle in gardees:
            continue
        rels.append(rel)
        bruts.append(vecteur)
        gardees[cle] = row

    if not bruts:
        return Space()

    brut = np.vstack(bruts)
    # Normalisation par l'écart-type de la population. Un descripteur
    # constant (écart-type nul) serait divisé par zéro : il ne distingue
    # rien, on le neutralise.
    moyenne = brut.mean(axis=0)
    ecart = brut.std(axis=0)
    ecart[ecart < 1e-9] = 1.0
    poids = np.array([WEIGHTS.get(name, 1.0) for name in FEATURES],
                     dtype=np.float64)
    vectors = ((brut - moyenne) / ecart * poids).astype(np.float32)

    return Space(rels=rels, vectors=vectors, rows=gardees,
                 index={norm_rel(r): i for i, r in enumerate(rels)})


def similar(lib: Library, rel: str, limit: int = 20,
            space: Space | None = None, same_category: bool = False,
            max_distance: float = 0.0) -> list[Match]:
    """Les échantillons qui ressemblent le plus à ``rel``.

    Retourne au plus ``limit`` voisins, du plus proche au plus lointain,
    sans l'échantillon de départ. Liste vide si celui-ci n'a pas encore été
    analysé — c'est le cas tant que ``scan_card(analyze=True)`` n'a pas
    tourné.
    """
    categorie = ""
    if same_category:
        row = lib.get("sample", rel)
        if row is not None:
            try:
                categorie = str(row["category"] or "")
            except (KeyError, IndexError, TypeError):
                categorie = ""

    univers = space if space is not None else build_space(
        lib, category=categorie)
    if not univers or not univers.has(rel):
        if space is not None and not univers.has(rel):
            log.debug("échantillon absent de l'espace fourni : %s", rel)
        return []

    position = univers.index[norm_rel(rel)]
    ecarts = np.linalg.norm(univers.vectors - univers.vectors[position],
                            axis=1)
    ecarts[position] = np.inf           # jamais se retourner soi-même

    nombre = max(1, min(int(limit), len(univers) - 1)) if len(univers) > 1 else 0
    if nombre <= 0:
        return []
    proches = np.argsort(ecarts, kind="stable")[:nombre]

    sortie: list[Match] = []
    for indice in proches:
        distance = float(ecarts[int(indice)])
        if not math.isfinite(distance):
            continue
        if max_distance and distance > float(max_distance):
            break
        voisin = univers.rels[int(indice)]
        sortie.append(Match(rel=voisin, distance=round(distance, 4),
                            row=univers.rows.get(norm_rel(voisin))))
    return sortie


# --------------------------------------------------------------------------- #
# Pourquoi il n'y a PAS de détection de quasi-doublons ici
# --------------------------------------------------------------------------- #
#
# Une fonction regroupant les échantillons « qui sonnent presque pareil » a
# existé dans ce module. Elle a été retirée après mesure : **ce descripteur
# ne peut pas distinguer deux exemplaires d'un même son d'une autre note du
# même instrument.**
#
# Les chiffres, sur la carte de référence (1 741 échantillons) :
#
# * à une distance de 0,45, le regroupement avale **59 % de la bibliothèque**
#   en 200 groupes, et met « 8 Choir G#2 » avec « Orchestra B3 » et un
#   saxophone : ce sont des familles de timbre, pas des doublons ;
# * en serrant à 0,12 **et** en exigeant une durée à 2 % près — critère qui
#   devrait isoler le même son réencodé — les 15 paires trouvées sont
#   **toutes** deux notes voisines du même instrument multi-échantillon :
#   ``Cello B3`` avec ``Cello C4``, ``MK2 Brass F#3`` avec ``MK2 Brass G3``,
#   ``8 Choir A#3`` avec ``8 Choir E5``. Même durée, même fréquence, même
#   dossier — et aucun doublon.
#
# La cause est structurelle : le descripteur est aveugle à la hauteur, et une
# bibliothèque multi-échantillon est précisément faite de fichiers de même
# timbre et de même longueur à des hauteurs différentes.
#
# La question « ai-je ce son en double ? » a déjà une réponse juste et
# conservatrice : :meth:`db.Library.duplicates`, qui compare les fichiers
# octet pour octet. Ne pas remplacer une certitude par une ressemblance.


def describe(row) -> str:
    """Résumé lisible des descripteurs d'un échantillon.

    Sert à expliquer pourquoi deux sons se ressemblent, plutôt que de laisser
    l'utilisateur deviner.
    """
    if row is None:
        return tr("Aucun descripteur.")
    morceaux: list[str] = []
    centroid = _value(row, "centroid")
    if centroid:
        morceaux.append(tr("brillance %.0f Hz") % centroid)
    low = _value(row, "low_ratio")
    if low is not None:
        morceaux.append(tr("grave %.0f %%") % (low * 100.0))
    high = _value(row, "high_ratio")
    if high is not None:
        morceaux.append(tr("aigu %.0f %%") % (high * 100.0))
    flatness = _value(row, "flatness")
    if flatness is not None:
        morceaux.append(tr("bruité %.0f %%") % (flatness * 100.0))
    attack = _value(row, "attack")
    if attack is not None:
        morceaux.append(tr("attaque %.0f ms") % (attack * 1000.0))
    crest = _value(row, "crest")
    if crest:
        morceaux.append(tr("crête/RMS %.1f") % crest)
    return ", ".join(morceaux) if morceaux else tr("Pas encore analysé.")
