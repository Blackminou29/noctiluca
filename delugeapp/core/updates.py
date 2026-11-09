# -*- coding: utf-8 -*-
"""Savoir s'il existe une version plus récente de l'application.

Le manuel promet « ni Internet, ni compte » : rien ne part sur le réseau
sans que l'utilisateur l'ait demandé — le menu Aide ▸ Rechercher une
nouvelle version, ou la case des réglages, **décochée par défaut**, qui le
fait au plus une fois par jour au démarrage. La seule requête est une
lecture de la page publique des versions sur GitHub ; elle n'envoie rien
d'autre que l'en-tête ``User-Agent`` de l'application.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta

from .. import __repo__, __version__

log = logging.getLogger(__name__)

__all__ = ["Release", "API_URL", "latest_release", "is_newer", "due"]

#: La dernière version publiée, lue sur l'API publique de GitHub.
API_URL = __repo__.replace("https://github.com/",
                           "https://api.github.com/repos/") \
    + "/releases/latest"

#: Délai entre deux vérifications automatiques.
INTERVAL = timedelta(days=1)


@dataclass(frozen=True)
class Release:
    """Une version publiée : son numéro et sa page."""

    version: str
    url: str


def _key(version: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", str(version))[:4])


def is_newer(version: str, current: str = __version__) -> bool:
    """Vrai si ``version`` (``v1.2.0``, ``1.2``…) dépasse ``current``."""
    a, b = _key(version), _key(current)
    if not a:
        return False
    longueur = max(len(a), len(b))
    return a + (0,) * (longueur - len(a)) > b + (0,) * (longueur - len(b))


def latest_release(timeout: float = 6.0, opener=None) -> Release | None:
    """La dernière version publiée, ou ``None`` (pas de réseau, réponse
    étrange). Ne lève jamais."""
    requete = urllib.request.Request(
        API_URL, headers={"User-Agent": "Noctiluca/%s" % __version__,
                          "Accept": "application/vnd.github+json"})
    try:
        ouvrir = opener or urllib.request.urlopen
        with ouvrir(requete, timeout=timeout) as reponse:
            donnees = json.loads(reponse.read(512 * 1024).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - pas de réseau : rien à dire
        log.info("vérification de version impossible : %s", exc)
        return None
    if not isinstance(donnees, dict) or donnees.get("draft") \
            or donnees.get("prerelease"):
        return None
    tag = str(donnees.get("tag_name") or "").strip()
    url = str(donnees.get("html_url") or __repo__ + "/releases")
    if not _key(tag) or not url.startswith("https://github.com/"):
        return None
    return Release(version=tag.lstrip("vV"), url=url)


def due(last_check: str, now: datetime | None = None) -> bool:
    """Vrai si la dernière vérification date de plus d'un jour."""
    try:
        derniere = datetime.fromisoformat(str(last_check))
    except (TypeError, ValueError):
        return True
    return (now or datetime.now()) - derniere >= INTERVAL
