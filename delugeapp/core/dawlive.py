# -*- coding: utf-8 -*-
"""Jouer ensemble : le DAW joue les sons du Deluge, en direct.

Chaque piste du Deluge peut **écouter** un canal MIDI : ce que le DAW y
envoie, elle le joue avec son propre son, comme si l'on jouait ses pads. Ce
module prépare une **copie** d'un morceau où chaque synthé écoute son canal
et chaque kit le sien, chaque son du kit sur sa note General MIDI — celles
de l'export vers le DAW (:func:`delugeapp.core.daw.drum_pitch`) : un clip
parti du Deluge vers le DAW y rejoue les bons sons.

Lu dans le code du firmware 1.3 (commit ``102cf9f``) :

* un synthé porte l'attribut ``inputMidiChannel``, canal compté depuis 0
  (``MelodicInstrument::writeMelodicInstrumentAttributesToFile``, écrit
  après ``activeModFunction``) ; sans ``inputMidiDevice``, n'importe quel
  appareil le fait jouer (``LearnedMIDI::equalsCable``) ;
* chaque son d'un kit peut porter ``<midiInput channel note />``, écrit à
  la fin du son (``SoundDrum::writeToFile``) : cette note le fait jouer ;
* un kit entier peut aussi écouter un canal (``<MIDIInput channel note />``,
  la note étant celle de la rangée du bas) : il passe alors avant ses sons
  (``Kit::offerReceivedNote``) ;
* l'horloge se règle dans SETTINGS ▸ MIDI ▸ Clock ▸ Input et Output.

Mesuré sur la carte de l'utilisateur : 42 synthés de ses morceaux écoutent
déjà le canal 1, que son MIDI Follow (canal A) utilise aussi. Une écoute
existante est gardée telle quelle, sauf demande ; le plan dit quand deux
pistes partagent un canal, et quand MIDI Follow l'utilise.

La copie est prouvée comme celles de :mod:`.songinsert` : défaire les ajouts
redonne l'original octet pour octet, et chaque instrument relu, ajouts
retirés, est identique à l'original. L'original n'est jamais touché.
"""

from __future__ import annotations

import copy
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from ..i18n import N_, tr
from . import dxml
from .sdcard import SDCard

log = logging.getLogger(__name__)

__all__ = ["LiveRoute", "LivePlan", "read_routes", "propose_channels",
           "plan_live", "write_live", "verify_live", "setup_steps",
           "DRUM_CHANNEL"]

#: Le canal des batteries en General MIDI (le 10, compté depuis 0).
DRUM_CHANNEL = 9

_KINDS = {"sound": "synth", "kit": "kit", "midi": "midi",
          "midiChannel": "midi", "mpeZone": "midi", "cvChannel": "cv",
          "audioOutput": "audio"}


@dataclass
class LiveRoute:
    """Ce qu'une piste du morceau écoute.

    :param index: rang de l'instrument dans ``<instruments>``.
    :param existing: canal déjà réglé dans le morceau (0–15), ou ``None``.
    :param channel: canal voulu (0–15) ; ``None`` : la piste n'écoute pas,
        ou garde ce qu'elle a.
    :param drums: pour un kit, chaque son : ``(nom, note, canal déjà
        réglé)``.
    :param whole_kit: le kit entier écoute déjà un canal (``MIDIInput``).
    """

    index: int
    name: str
    kind: str
    existing: int | None = None
    channel: int | None = None
    drums: list[tuple[str, int, int | None]] = field(default_factory=list)
    whole_kit: bool = False

    @property
    def can_listen(self) -> bool:
        """Seuls les synthés et les kits jouent ce qu'ils reçoivent ; une
        piste MIDI ou CV le renvoie, une piste audio n'en fait rien."""
        return self.kind in ("synth", "kit")

    @property
    def listens(self) -> int | None:
        """Le canal que la piste écoutera dans la copie."""
        return self.channel if self.channel is not None else self.existing


def _int(text, default: int | None = None) -> int | None:
    try:
        return int(str(text).strip())
    except (TypeError, ValueError):
        return default


def read_routes(sd: SDCard, rel: str) -> list[LiveRoute]:
    """Les pistes du morceau et ce qu'elles écoutent déjà."""
    from .daw import _drum_map, _track_name

    root = dxml.load(sd.abs(rel)).root
    if root is None or root.tag != "song":
        raise ValueError(tr("ce fichier n'est pas un morceau du Deluge"))
    instruments = dxml.get_child(root, "instruments")
    routes: list[LiveRoute] = []
    for index, el in enumerate(list(instruments) if instruments is not None
                               else []):
        kind = _KINDS.get(el.tag, "")
        if not kind:
            continue
        route = LiveRoute(index=index, name=_track_name(el, kind), kind=kind)
        if kind == "kit":
            entier = dxml.get_child(el, "MIDIInput")
            if entier is not None:
                route.whole_kit = True
                route.existing = _int(dxml.get(entier, "channel"))
            notes = _drum_map(el)
            sources = dxml.get_child(el, "soundSources")
            sons = [s for s in (list(sources) if sources is not None else [])
                    if s.tag == "sound"]
            for i, son in enumerate(sons):
                appris = dxml.get_child(son, "midiInput")
                note = notes.get(i, (36 + i, i, ""))
                route.drums.append((note[2], note[0], _int(
                    dxml.get(appris, "channel")) if appris is not None
                    else None))
            canaux = {c for _n, _p, c in route.drums if c is not None}
            if route.existing is None and len(canaux) == 1:
                route.existing = canaux.pop()
        else:
            route.existing = _int(dxml.get(el, "inputMidiChannel"))
        routes.append(route)
    return routes


def propose_channels(routes: list[LiveRoute], avoid: set[int] | None = None,
                     keep_existing: bool = True) -> list[LiveRoute]:
    """Donne un canal libre à chaque synthé et chaque kit qui n'en a pas.

    Les kits prennent d'abord le canal 10, celui des batteries ; les synthés
    les canaux 1 à 16 dans l'ordre. ``avoid`` (les canaux de MIDI Follow,
    comptés depuis 0) n'est pris qu'en dernier recours ; une écoute déjà
    réglée est gardée si ``keep_existing``. Au-delà de seize pistes, les
    suivantes n'écoutent rien.
    """
    avoid = set(avoid or ())
    pris = {r.existing for r in routes
            if keep_existing and r.can_listen and r.existing is not None}
    libres = [c for c in range(16) if c not in pris and c not in avoid
              and c != DRUM_CHANNEL]
    secours = [c for c in sorted(avoid) if c not in pris
               and c != DRUM_CHANNEL]
    batterie_libre = DRUM_CHANNEL not in pris and DRUM_CHANNEL not in avoid
    for route in routes:
        route.channel = None
        if not route.can_listen:
            continue
        if keep_existing and route.existing is not None:
            # Un kit dont une partie des sons écoute déjà : les autres
            # rejoignent leur canal.
            if route.kind == "kit" and not route.whole_kit \
                    and any(d[2] is None for d in route.drums):
                route.channel = route.existing
            continue
        if route.kind == "kit" and batterie_libre:
            route.channel = DRUM_CHANNEL
            batterie_libre = False
        elif libres:
            route.channel = libres.pop(0)
        elif batterie_libre:
            route.channel = DRUM_CHANNEL
            batterie_libre = False
        elif secours:
            route.channel = secours.pop(0)
    return routes


# --------------------------------------------------------------------------- #
# La copie
# --------------------------------------------------------------------------- #

@dataclass
class LivePlan:
    """La copie préparée : ses octets, et ce qu'elle change."""

    source: str = ""
    rel: str = ""
    data: bytes = b""
    edits: list[tuple[int, bytes, bytes]] = field(default_factory=list)
    routes: list[LiveRoute] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.rel) and not self.error

    def text(self) -> str:
        return "\n".join(self.lines)


_ACTIVE_MOD = re.compile(rb'\sactiveModFunction\s*=\s*"[^"]*"')
_INPUT_CHANNEL = re.compile(rb'\sinputMidiChannel\s*=\s*"(?P<v>[^"]*)"')


def _tabs(n: int) -> bytes:
    return b"\t" * max(0, n)


def _synth_edit(data: bytes, span, channel: int, existing: int | None
                ) -> tuple[int, bytes, bytes] | None:
    from .songinsert import _indent_of

    ouvrante = data[span.start:span.open_end]
    if existing is not None:
        m = _INPUT_CHANNEL.search(ouvrante)
        if m is None or existing == channel:
            return None
        return (span.start + m.start("v"), m.group("v"),
                str(channel).encode())
    attribut = b'inputMidiChannel="%d"' % channel
    m = _ACTIVE_MOD.search(ouvrante)
    if m is not None:
        # Là où la machine l'écrit, sur sa ligne s'il y en a une par
        # attribut.
        if b"\n" in ouvrante[:m.end()]:
            debut_ligne = ouvrante.rfind(b"\n", 0, m.start() + 1) + 1
            retrait = ouvrante[debut_ligne:m.start() + 1].strip(b" ")
            insere = b"\n" + _tabs(retrait.count(b"\t")) + attribut
        else:
            insere = b" " + attribut
        return (span.start + m.end(), b"", insere)
    fin = len(ouvrante) - (2 if ouvrante.endswith(b"/>") else 1)
    retrait = _indent_of(data, span.start) + 1
    insere = (b"\n" + _tabs(retrait) if b"\n" in ouvrante else b" ") + attribut
    return (span.start + fin, b"", insere)


def _drum_edit(data: bytes, span, channel: int, note: int
               ) -> tuple[int, bytes, bytes] | None:
    from .songinsert import _indent_of, _line_start

    fermante = b"</sound>"
    if data[span.end - len(fermante):span.end] != fermante:
        return None                     # un son sans contenu : rien à faire
    position = span.end - len(fermante)
    retrait = _indent_of(data, span.start) + 1
    bloc = (_tabs(retrait) + b"<midiInput\n" + _tabs(retrait + 1)
            + b'channel="%d"\n' % channel + _tabs(retrait + 1)
            + b'note="%d" />\n' % note)
    debut = _line_start(data, position)
    if data[debut:position].strip(b" \t") == b"":
        return (debut, b"", bloc)
    return (position, b"", b"\n" + bloc + _tabs(retrait - 1))


def plan_live(sd: SDCard, rel: str, routes: list[LiveRoute], name: str = "",
              follow: set[int] | None = None) -> LivePlan:
    """La copie du morceau où chaque piste écoute son canal (``routes``,
    tel que :func:`propose_channels` les règle). Rien n'est écrit."""
    from .songinsert import _children, _elements
    from .songwriter import free_song_name

    plan = LivePlan(source=rel, routes=routes)
    try:
        data = sd.abs(rel).read_bytes()
    except OSError as exc:
        plan.error = tr("lecture impossible : %s") % exc
        return plan
    spans = _elements(data)
    racine = next((s for s in spans if s.depth == 0), None)
    if racine is None or racine.name != "song":
        plan.error = tr("ce fichier n'est pas un morceau du Deluge")
        return plan
    conteneur = next((s for s in _children(spans, racine)
                      if s.name == "instruments"), None)
    pistes = _children(spans, conteneur) if conteneur is not None else []
    edits: list[tuple[int, bytes, bytes]] = []
    for route in routes:
        if route.channel is None or not route.can_listen:
            continue
        if route.index >= len(pistes) \
                or _KINDS.get(pistes[route.index].name) != route.kind:
            plan.error = tr("le morceau a changé depuis sa lecture : rien "
                            "n'est écrit")
            return plan
        span = pistes[route.index]
        if route.kind == "synth":
            edit = _synth_edit(data, span, route.channel, route.existing)
            if edit is not None:
                edits.append(edit)
            continue
        if route.whole_kit:
            continue
        sources = next((s for s in _children(spans, span)
                        if s.name == "soundSources"), None)
        sons = [s for s in _children(spans, sources) if s.name == "sound"] \
            if sources is not None else []
        for son, (_nom, note, deja) in zip(sons, route.drums):
            if deja is not None:
                continue
            edit = _drum_edit(data, son, route.channel, note)
            if edit is not None:
                edits.append(edit)
    edits.sort(key=lambda e: e[0])
    morceaux, curseur = [], 0
    for position, ancien, neuf in edits:
        morceaux.append(data[curseur:position])
        morceaux.append(neuf)
        curseur = position + len(ancien)
    morceaux.append(data[curseur:])
    plan.data = b"".join(morceaux)
    plan.edits = edits
    if not edits:
        plan.error = tr("chaque piste écoute déjà son canal : il n'y a rien "
                        "à changer")
        plan.lines = _plan_lines(plan, follow or set())
        return plan
    try:
        plan.rel = free_song_name(sd, name or tr("%s DAW") % Path(rel).stem)
    except ValueError as exc:
        plan.error = str(exc)
        return plan
    plan.lines = _plan_lines(plan, follow or set())
    probleme = verify_live(data, plan)
    if probleme:
        plan.error = probleme
    return plan


def _without_inputs(el: ET.Element) -> ET.Element:
    """L'instrument sans ce que la copie peut ajouter : son canal d'écoute,
    et l'écoute de ses sons."""
    el = copy.deepcopy(el)
    el.attrib.pop("inputMidiChannel", None)
    sources = el.find("soundSources")
    for son in (list(sources) if sources is not None else []):
        for appris in son.findall("midiInput"):
            son.remove(appris)
    return el


def verify_live(original: bytes, plan: LivePlan) -> str:
    """``""`` si la copie est l'original plus ses ajouts, et si chaque piste
    y écoute le canal prévu."""
    from .songinsert import _same_tree

    reconstruit, curseur, decalage = bytearray(), 0, 0
    for position, ancien, neuf in plan.edits:
        debut = position + decalage
        reconstruit += plan.data[curseur:debut]
        reconstruit += ancien
        curseur = debut + len(neuf)
        decalage += len(neuf) - len(ancien)
    reconstruit += plan.data[curseur:]
    if bytes(reconstruit) != original:
        return tr("le fichier ne redonne pas l'original : rien n'est écrit")
    try:
        avant = dxml.loads(original).root
        apres = dxml.loads(plan.data).root
    except dxml.DelugeXMLError as exc:
        return tr("le fichier ne se relit pas : %s") % exc
    a, b = avant.find("instruments"), apres.find("instruments")
    anciens = list(a) if a is not None else []
    nouveaux = list(b) if b is not None else []
    if len(anciens) != len(nouveaux):
        return tr("des éléments du morceau ont disparu")
    for x, y in zip(anciens, nouveaux):
        if not _same_tree(_without_inputs(x), _without_inputs(y)):
            return tr("un élément du morceau a changé : rien n'est écrit")
    for route in plan.routes:
        if route.channel is None or not route.can_listen or route.whole_kit:
            continue
        el = nouveaux[route.index]
        if route.kind == "synth":
            if _int(dxml.get(el, "inputMidiChannel")) != route.channel:
                return tr("%s n'écoute pas le canal prévu : rien n'est "
                          "écrit") % route.name
            continue
        sources = el.find("soundSources")
        sons = [s for s in (list(sources) if sources is not None else [])
                if s.tag == "sound"]
        for son, (_nom, note, deja) in zip(sons, route.drums):
            appris = son.find("midiInput")
            if deja is None and (appris is None or _int(appris.get(
                    "channel")) != route.channel
                    or _int(appris.get("note")) != note):
                return tr("%s n'écoute pas le canal prévu : rien n'est "
                          "écrit") % route.name
    return ""


def _plan_lines(plan: LivePlan, follow: set[int]) -> list[str]:
    lignes = []
    if plan.rel:
        lignes += [tr("Nouveau fichier : %s") % plan.rel,
                   tr("Le morceau %s reste tel quel ; la copie le contient "
                      "octet pour octet, plus ce qui suit.")
                   % Path(plan.source).stem]
    par_canal: dict[int, list[str]] = {}
    for route in plan.routes:
        if not route.can_listen:
            lignes.append(tr("%s : n'écoute pas (une piste %s renvoie ce "
                             "qu'elle reçoit)") % (route.name, route.kind.upper())
                          if route.kind in ("midi", "cv") else
                          tr("%s : piste audio, n'écoute pas") % route.name)
            continue
        canal = route.listens
        if canal is None:
            lignes.append(tr("%s : aucun canal libre, n'écoute pas")
                          % route.name)
            continue
        par_canal.setdefault(canal, []).append(route.name)
        if route.channel is None or route.channel == route.existing:
            detail = tr("déjà réglé")
        elif route.existing is not None:
            detail = tr("au lieu du canal %d") % (route.existing + 1)
        else:
            detail = tr("nouveau")
        if route.kind == "kit" and not route.whole_kit:
            lignes.append(tr("%s : canal %d (%s), %d sons sur leurs notes "
                             "General MIDI") % (route.name, canal + 1, detail,
                                                len(route.drums)))
        else:
            lignes.append(tr("%s : canal %d (%s)") % (route.name, canal + 1,
                                                     detail))
    for canal, noms in sorted(par_canal.items()):
        if len(noms) > 1:
            lignes.append(tr("Attention : %s écoutent ensemble le canal %d")
                          % (", ".join(noms), canal + 1))
        if canal in follow:
            lignes.append(tr("Attention : le canal %d est aussi celui de MIDI "
                             "Follow ; ce que le DAW y envoie joue aussi la "
                             "piste choisie sur la machine") % (canal + 1))
    return lignes


def write_live(sd: SDCard, plan: LivePlan, apply: bool = False):
    """Écrit la copie — **simule** sans ``apply``. Rend un
    :class:`~delugeapp.core.songwriter.SongWrite`. Le fichier est toujours
    nouveau : s'il est apparu entre le plan et l'écriture, rien n'est écrit.
    """
    from .songwriter import SongWrite

    result = SongWrite(rel=plan.rel, lines=list(plan.lines),
                       error=plan.error)
    if plan.error or not plan.rel or not apply:
        return result
    sd.require_writable()
    cible = sd.abs(plan.rel)
    try:
        cible.parent.mkdir(parents=True, exist_ok=True)
        with open(cible, "xb") as handle:
            handle.write(plan.data)
    except FileExistsError:
        result.error = tr("%s existe déjà : rien n'a été écrit") % plan.rel
        return result
    except OSError as exc:
        log.exception("écriture de la copie impossible : %s", plan.rel)
        result.error = tr("écriture impossible : %s") % exc
        return result
    sd.invalidate_cache()
    result.applied = True
    log.info("copie pour le DAW : %s depuis %s (%d ajout(s))", plan.rel,
             plan.source, len(plan.edits))
    return result


# --------------------------------------------------------------------------- #
# Le mode d'emploi
# --------------------------------------------------------------------------- #

#: Les réglages du DAW, DAW par DAW : la copie ne peut pas les faire.
_DAW_STEPS = {
    "ableton": (
        N_("Live ▸ Préférences ▸ Link, Tempo & MIDI : sur le port du Deluge, "
           "cochez Piste en entrée et en sortie."),
        N_("Pour que le Deluge suive le tempo de Live : cochez aussi Sync en "
           "sortie ; pour que Live suive le Deluge : Sync en entrée, et "
           "réglez Live sur l'horloge externe (bouton EXT)."),
        N_("Pour chaque piste du tableau : une piste MIDI dans Live, « MIDI "
           "To » sur le Deluge, et le canal indiqué."),
    ),
    "autre": (
        N_("Dans les réglages MIDI du DAW, activez le port du Deluge en "
           "entrée et en sortie."),
        N_("Choisissez qui mène le tempo : le DAW envoie son horloge au "
           "Deluge, ou suit la sienne."),
        N_("Pour chaque piste du tableau : une piste MIDI du DAW qui sort "
           "vers le Deluge, sur le canal indiqué."),
    ),
}

_DELUGE_STEPS = (
    N_("Chargez la copie sur le Deluge."),
    N_("Pour suivre le tempo du DAW : SETTINGS ▸ MIDI ▸ Clock ▸ Input sur ON. "
       "Pour le mener : Clock ▸ Output sur ON."),
)


def setup_steps(daw: str = "ableton") -> list[str]:
    """Ce qu'il reste à régler, sur le Deluge puis dans le DAW."""
    return [tr(s) for s in _DELUGE_STEPS] + [
        tr(s) for s in _DAW_STEPS.get(daw, _DAW_STEPS["autre"])]
