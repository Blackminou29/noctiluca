# -*- coding: utf-8 -*-
"""Lecture et écriture tolérantes des fichiers XML du Synthstrom Deluge.

Les cartes réelles contiennent des fichiers écrits par plusieurs générations de
firmware, plus des fichiers produits par des outils tiers. Ce module absorbe les
anomalies constatées :

* **document multi-racines** (firmware 2.x) : ``<firmwareVersion>`` et
  ``<earliestCompatibleFirmware>`` sont des frères de ``<sound>`` ; on enveloppe
  le tout dans une racine de synthèse ``<delugeFile>`` puis on isole la vraie racine ;
* **``&`` non échappé** dans un attribut (``fileName="… Tenor & Alto Sax.wav"``) ;
* **octets non UTF-8** et caractères interdits par XML 1.0 (``name="\\xff\\xff…"``) ;
* **attributs dupliqués** dans une même balise (clips de morceaux) ;
* **balises mal fermées** : repli sur un analyseur tolérant qui referme la pile.

Deux dialectes coexistent et sont traités de façon transparente :

* ``'elem'`` (firmware 2.x) : ``<osc1><type>saw</type></osc1>`` ;
* ``'attr'`` (firmware 3.0+) : ``<osc1 type="saw" />``.

Le module n'importe ni Qt ni numpy.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator

log = logging.getLogger(__name__)

__all__ = [
    "DelugeXMLError",
    "DelugeDoc",
    "ROOT_TAGS",
    "WRAPPER_TAG",
    "repair_text",
    "load",
    "loads",
    "detect_dialect",
    "dump",
    "save",
    "get",
    "set_",
    "get_child",
    "ensure_child",
    "iter_children",
    "remove_child",
]


class DelugeXMLError(Exception):
    """Fichier XML Deluge illisible même après réparation."""


#: Balises racines connues du format Deluge.
ROOT_TAGS = frozenset(
    {
        "sound",
        "kit",
        "song",
        "instrument",
        "audioClip",
        "clip",
        "runtimeFeatureSettings",
        "defaults",
        "settings",
        "midiFollow",
        "midiDevices",
        "delugeFile",
    }
)

#: Racine de synthèse utilisée pour envelopper les documents multi-racines.
WRAPPER_TAG = "delugeFile"

_XML_DECL_RE = re.compile(r"^\s*<\?xml[^>]*\?>\s*", re.I)
# Caractères interdits par XML 1.0 (on conserve \t \n \r et U+FFFD qui est licite).
_INVALID_XML_RE = re.compile(
    r"[^\u0009\u000A\u000D\u0020-\uD7FF\uE000-\uFFFD\U00010000-\U0010FFFF]"
)
# '&' qui n'introduit pas une entité valide.
_BARE_AMP_RE = re.compile(r"&(?!(?:#[0-9]+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9._-]*);)")
_ATTR_RE = re.compile(r"([A-Za-z_:][-\w.:]*)\s*=\s*(\"[^\"]*\"|'[^']*')")
_START_TAG_RE = re.compile(
    r"<(?P<name>[A-Za-z_:][-\w.:]*)(?P<attrs>(?:[^<>\"']|\"[^\"]*\"|'[^']*')*)>", re.S
)
_CLOSE_TAG_RE = re.compile(r"</\s*(?P<name>[A-Za-z_:][-\w.:]*)\s*>")
_ENTITY_RE = re.compile(r"&(#[0-9]+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9._-]*);")

_NAMED_ENTITIES = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'"}


@dataclass
class DelugeDoc:
    """Document XML Deluge chargé en mémoire.

    :param path: chemin du fichier d'origine (``None`` si créé en mémoire) ;
    :param root: élément racine RÉEL (``<sound>``, ``<kit>``, ``<song>``…) ;
    :param preamble: éléments frères hors racine (firmware 2.x), dans l'ordre ;
    :param dialect: ``'attr'`` ou ``'elem'`` ;
    :param firmware: version détectée (``''`` si inconnue) ;
    :param repaired: anomalies corrigées à la lecture (rapport de santé).
    """

    path: Path | None
    root: ET.Element
    preamble: dict[str, str] = field(default_factory=dict)
    dialect: str = "attr"
    firmware: str = ""
    repaired: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Réparation du texte brut
# ---------------------------------------------------------------------------


def repair_text(raw: bytes) -> tuple[str, list[str]]:
    """Décode et répare des octets bruts de fichier Deluge.

    Corrige : BOM, octets non UTF-8, caractères interdits par XML 1.0,
    ``&`` non échappé. Retourne ``(texte, anomalies)``.
    """
    fixes: list[str] = []
    if isinstance(raw, str):
        text = raw
    else:
        data = bytes(raw)
        if data.startswith(b"\xef\xbb\xbf"):
            data = data[3:]
            fixes.append("BOM UTF-8 retiré")
            text = _decode_utf8(data, fixes)
        elif data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
            enc = "utf-16-le" if data.startswith(b"\xff\xfe") else "utf-16-be"
            text = data[2:].decode(enc, errors="replace")
            fixes.append("fichier UTF-16 converti en UTF-8")
        else:
            text = _decode_utf8(data, fixes)

    if _INVALID_XML_RE.search(text):
        text = _INVALID_XML_RE.sub("", text)
        fixes.append("caractères interdits par XML 1.0 supprimés")

    if "&" in text:
        text, n = _BARE_AMP_RE.subn("&amp;", text)
        if n:
            fixes.append("%d '&' non échappé(s) corrigé(s)" % n)

    return text, fixes


def _decode_utf8(data: bytes, fixes: list[str]) -> str:
    """Décode en UTF-8, avec remplacement des octets invalides."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        fixes.append("octets non UTF-8 remplacés")
        return data.decode("utf-8", errors="replace")


def _strip_decl(text: str) -> str:
    """Retire la déclaration ``<?xml …?>`` de tête."""
    return _XML_DECL_RE.sub("", text, count=1)


# ---------------------------------------------------------------------------
# Analyse
# ---------------------------------------------------------------------------


def _dedupe_attributes(text: str) -> tuple[str, int]:
    """Supprime les attributs dupliqués d'une même balise (première occurrence gardée)."""
    removed = 0

    def _fix(match: "re.Match[str]") -> str:
        nonlocal removed
        attrs = match.group("attrs")
        if "=" not in attrs:
            return match.group(0)
        seen: set[str] = set()
        pieces: list[tuple[str, str]] = []
        dup = 0
        pos = 0
        for m in _ATTR_RE.finditer(attrs):
            name = m.group(1)
            if name in seen:
                dup += 1
                continue
            seen.add(name)
            pieces.append((name, m.group(2)))
            pos = m.end()
        if not dup:
            return match.group(0)
        removed += dup
        tail = attrs[pos:]
        self_closing = tail.rstrip().endswith("/")
        body = "".join("\n\t%s=%s" % (name, value) for name, value in pieces)
        return "<%s%s%s>" % (match.group("name"), body, " /" if self_closing else "")

    out = _START_TAG_RE.sub(_fix, text)
    return out, removed


def _split_roots(
    elements: list[ET.Element],
) -> tuple[ET.Element | None, dict[str, str], list[ET.Element]]:
    """Sépare la vraie racine, le préambule (frères feuilles) et les éléments surnuméraires."""
    root: ET.Element | None = None
    for el in elements:
        if el.tag in ROOT_TAGS:
            root = el
            break
    if root is None:
        for el in elements:
            if len(el) or el.attrib:
                root = el
                break
    if root is None and elements:
        root = elements[-1]

    preamble: dict[str, str] = {}
    extras: list[ET.Element] = []
    for el in elements:
        if el is root:
            continue
        if len(el) == 0 and not el.attrib:
            preamble[el.tag] = (el.text or "").strip()
        else:
            extras.append(el)
    return root, preamble, extras


def _parse_wrapped(body: str) -> list[ET.Element] | None:
    """Analyse un corps enveloppé dans ``<delugeFile>`` ; ``None`` si toujours invalide."""
    try:
        wrapper = ET.fromstring("<%s>%s</%s>" % (WRAPPER_TAG, body, WRAPPER_TAG))
    except ET.ParseError:
        return None
    return list(wrapper)


def _parse_document(text: str) -> tuple[ET.Element, dict[str, str], list[ET.Element], list[str]]:
    """Analyse tolérante : retourne ``(racine, préambule, extras, anomalies)``."""
    fixes: list[str] = []

    # 1. Le cas normal : un document bien formé à racine unique.
    try:
        return ET.fromstring(text), {}, [], fixes
    except ET.ParseError as first_error:
        first = first_error

    # 2. Document multi-racines (firmware 2.x) : on enveloppe.
    body = _strip_decl(text)
    children = _parse_wrapped(body)
    if children is not None:
        root, preamble, extras = _split_roots(children)
        if root is not None:
            fixes.append("document multi-racines enveloppé dans <%s>" % WRAPPER_TAG)
            return root, preamble, extras, fixes

    # 3. Attributs dupliqués dans une même balise.
    fixed_text, removed = _dedupe_attributes(text)
    if removed:
        fixes.append("%d attribut(s) dupliqué(s) supprimé(s)" % removed)
        try:
            return ET.fromstring(fixed_text), {}, [], fixes
        except ET.ParseError:
            pass
        children = _parse_wrapped(_strip_decl(fixed_text))
        if children is not None:
            root, preamble, extras = _split_roots(children)
            if root is not None:
                fixes.append("document multi-racines enveloppé dans <%s>" % WRAPPER_TAG)
                return root, preamble, extras, fixes
        text = fixed_text

    # 4. Dernier recours : analyseur tolérant (balises mal fermées, texte parasite).
    elements, tolerant_fixes = _tolerant_parse(text)
    if not elements:
        raise DelugeXMLError("XML illisible : %s" % first)
    fixes.append("structure XML reconstruite par l'analyseur tolérant")
    fixes.extend(tolerant_fixes)
    if len(elements) == 1:
        return elements[0], {}, [], fixes
    root, preamble, extras = _split_roots(elements)
    if root is None:  # pragma: no cover - impossible, elements n'est pas vide
        raise DelugeXMLError("XML illisible : aucune racine exploitable")
    return root, preamble, extras, fixes


def _unescape(text: str) -> str:
    """Décode les entités XML connues ; laisse les inconnues telles quelles."""
    if "&" not in text:
        return text

    def _sub(m: "re.Match[str]") -> str:
        body = m.group(1)
        if body.startswith("#"):
            try:
                code = int(body[2:], 16) if body[1] in "xX" else int(body[1:], 10)
            except ValueError:
                return m.group(0)
            if 0 < code <= 0x10FFFF:
                try:
                    return chr(code)
                except ValueError:  # pragma: no cover
                    return m.group(0)
            return m.group(0)
        return _NAMED_ENTITIES.get(body, m.group(0))

    return _ENTITY_RE.sub(_sub, text)


def _parse_attrs(blob: str) -> tuple[dict[str, str], bool, int]:
    """Analyse les attributs d'une balise ouvrante ; retourne (attributs, auto-fermante, doublons)."""
    attrs: dict[str, str] = {}
    dup = 0
    for m in _ATTR_RE.finditer(blob):
        name = m.group(1)
        raw = m.group(2)[1:-1]
        if name in attrs:
            dup += 1
            continue
        attrs[name] = _unescape(raw)
    self_closing = blob.rstrip().endswith("/")
    return attrs, self_closing, dup


def _tolerant_parse(text: str) -> tuple[list[ET.Element], list[str]]:
    """Analyseur de dernier recours : reconstruit l'arbre en refermant les balises orphelines."""
    fixes: list[str] = []
    roots: list[ET.Element] = []
    stack: list[ET.Element] = []
    pending: list[str] = []
    n = len(text)
    i = 0
    mismatched = 0
    orphan = 0
    dup_total = 0

    def _flush_text() -> None:
        if not pending:
            return
        chunk = "".join(pending)
        pending.clear()
        if not chunk.strip():
            return
        value = _unescape(chunk)
        if stack:
            parent = stack[-1]
            if len(parent):
                last = parent[-1]
                last.tail = (last.tail or "") + value
            else:
                parent.text = (parent.text or "") + value

    while i < n:
        lt = text.find("<", i)
        if lt < 0:
            pending.append(text[i:])
            break
        if lt > i:
            pending.append(text[i:lt])
        if text.startswith("<!--", lt):
            end = text.find("-->", lt + 4)
            i = n if end < 0 else end + 3
            continue
        if text.startswith("<![CDATA[", lt):
            end = text.find("]]>", lt + 9)
            if end < 0:
                pending.append(text[lt + 9 :])
                break
            pending.append(text[lt + 9 : end])
            i = end + 3
            continue
        if text.startswith("<?", lt):
            end = text.find("?>", lt + 2)
            i = n if end < 0 else end + 2
            continue
        if text.startswith("<!", lt):
            end = text.find(">", lt + 2)
            i = n if end < 0 else end + 1
            continue
        if text.startswith("</", lt):
            m = _CLOSE_TAG_RE.match(text, lt)
            if not m:
                pending.append("<")
                i = lt + 1
                continue
            _flush_text()
            name = m.group("name")
            depth = None
            for k in range(len(stack) - 1, -1, -1):
                if stack[k].tag == name:
                    depth = k
                    break
            if depth is None:
                orphan += 1
            else:
                if depth != len(stack) - 1:
                    mismatched += 1
                del stack[depth:]
            i = m.end()
            continue

        m = _START_TAG_RE.match(text, lt)
        if not m:
            pending.append("<")
            i = lt + 1
            continue
        _flush_text()
        attrs, self_closing, dup = _parse_attrs(m.group("attrs"))
        dup_total += dup
        el = ET.Element(m.group("name"), attrs)
        if stack:
            stack[-1].append(el)
        else:
            roots.append(el)
        if not self_closing:
            stack.append(el)
        i = m.end()

    _flush_text()
    if stack:
        fixes.append("%d balise(s) non fermée(s) refermée(s)" % len(stack))
    if mismatched:
        fixes.append("%d balise(s) fermée(s) dans le désordre" % mismatched)
    if orphan:
        fixes.append("%d balise(s) fermante(s) orpheline(s) ignorée(s)" % orphan)
    if dup_total:
        fixes.append("%d attribut(s) dupliqué(s) supprimé(s)" % dup_total)
    return roots, fixes


def detect_dialect(root: ET.Element) -> str:
    """Détermine le dialecte du document : ``'attr'`` (fw 3.0+) ou ``'elem'`` (fw 2.x)."""
    if root is None:
        return "attr"
    attrs = 0
    leaves = 0
    for el in root.iter():
        attrs += len(el.attrib)
        if len(el) == 0 and el.text is not None and el.text.strip():
            leaves += 1
    if attrs == 0 and leaves == 0:
        return "attr"
    return "attr" if attrs >= leaves else "elem"


def _detect_firmware(root: ET.Element, preamble: dict[str, str]) -> str:
    """Extrait la version de firmware du document (``''`` si inconnue)."""
    value = root.get("firmwareVersion") if root is not None else None
    if not value:
        value = preamble.get("firmwareVersion", "")
    if not value and root is not None:
        child = root.find("firmwareVersion")
        if child is not None and child.text:
            value = child.text
    return (value or "").strip()


def loads(data: bytes, path: Path | None = None) -> DelugeDoc:
    """Analyse des octets (ou une chaîne) de fichier Deluge et retourne un :class:`DelugeDoc`."""
    text, fixes = repair_text(data)
    if not text.strip():
        raise DelugeXMLError("fichier vide")
    root, preamble, extras, more = _parse_document(text)
    fixes = fixes + more
    if extras:
        fixes.append(
            "%d élément(s) de premier niveau ignoré(s) : %s"
            % (len(extras), ", ".join(sorted({e.tag for e in extras})))
        )
    dialect = detect_dialect(root)
    firmware = _detect_firmware(root, preamble)
    return DelugeDoc(
        path=Path(path) if path is not None else None,
        root=root,
        preamble=preamble,
        dialect=dialect,
        firmware=firmware,
        repaired=fixes,
    )


def load(path: Path) -> DelugeDoc:
    """Charge un fichier XML Deluge. Lève :class:`DelugeXMLError` si irrécupérable."""
    p = Path(path)
    try:
        raw = p.read_bytes()
    except OSError as exc:
        raise DelugeXMLError("lecture impossible de %s : %s" % (p, exc)) from exc
    try:
        doc = loads(raw, p)
    except DelugeXMLError as exc:
        raise DelugeXMLError("%s : %s" % (p.name, exc)) from exc
    if doc.repaired:
        log.debug("XML réparé %s : %s", p.name, "; ".join(doc.repaired))
    return doc


# ---------------------------------------------------------------------------
# Sérialisation au style Deluge
# ---------------------------------------------------------------------------


def _escape_attr(value: str) -> str:
    """Échappe une valeur d'attribut."""
    out = (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    return out.replace("\r", "&#13;").replace("\n", "&#10;").replace("\t", "&#9;")


def _escape_text(value: str) -> str:
    """Échappe un contenu textuel."""
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _write_element(out: list[str], el: ET.Element, depth: int, dialect: str) -> None:
    """Écrit un élément et sa descendance au style Deluge (indentation par tabulations)."""
    ind = "\t" * depth
    tag = el.tag
    if not isinstance(tag, str):  # commentaires / instructions de traitement
        return
    attrs = [(k, "" if v is None else str(v)) for k, v in el.attrib.items()]
    children = [c for c in el if isinstance(c.tag, str)]
    text = el.text or ""
    has_text = text.strip() != ""

    if len(attrs) > 2:
        head = (
            ind
            + "<"
            + tag
            + "\n"
            + "\n".join(ind + "\t" + '%s="%s"' % (k, _escape_attr(v)) for k, v in attrs)
        )
    else:
        head = ind + "<" + tag + "".join(' %s="%s"' % (k, _escape_attr(v)) for k, v in attrs)

    if not children and not has_text:
        if not attrs and dialect == "elem":
            # Le firmware 2.x écrit <fileName></fileName> et jamais <fileName />.
            out.append("%s<%s></%s>\n" % (ind, tag, tag))
        else:
            out.append(head + " />\n")
        return

    if not children:
        out.append(head + ">" + _escape_text(text) + "</" + tag + ">\n")
        return

    out.append(head + ">\n")
    if has_text:
        out.append(ind + "\t" + _escape_text(text.strip()) + "\n")
    for child in children:
        _write_element(out, child, depth + 1, dialect)
    out.append(ind + "</" + tag + ">\n")


def dump(doc: DelugeDoc) -> str:
    """Sérialise un document au format Deluge (§4.3.1 de la spécification)."""
    if doc is None or doc.root is None:
        raise DelugeXMLError("document vide : rien à sérialiser")
    dialect = doc.dialect if doc.dialect in ("attr", "elem") else "attr"
    out: list[str] = ['<?xml version="1.0" encoding="UTF-8"?>\n']
    for name, value in (doc.preamble or {}).items():
        out.append("<%s>%s</%s>\n" % (name, _escape_text(value), name))
    _write_element(out, doc.root, 0, dialect)
    return "".join(out)


def _make_backup(target: Path) -> Path | None:
    """Copie horodatée ``<nom>.<AAAAMMJJ-HHMMSS>.bak`` du fichier existant."""
    try:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = target.with_name("%s.%s.bak" % (target.name, stamp))
        n = 1
        while backup.exists():
            backup = target.with_name("%s.%s-%d.bak" % (target.name, stamp, n))
            n += 1
        backup.write_bytes(target.read_bytes())
        return backup
    except OSError as exc:
        log.warning("sauvegarde impossible de %s : %s", target, exc)
        return None


def save(doc: DelugeDoc, path: Path | None = None, backup: bool = True) -> Path:
    """Écrit le document de façon atomique (fichier temporaire + ``os.replace``).

    ``backup=True`` conserve une copie ``.bak`` horodatée de l'ancien fichier.
    Retourne le chemin écrit.
    """
    target = Path(path) if path is not None else doc.path
    if target is None:
        raise DelugeXMLError("aucun chemin de destination pour l'enregistrement")
    target = Path(target)
    data = dump(doc).encode("utf-8")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DelugeXMLError("dossier inaccessible %s : %s" % (target.parent, exc)) from exc

    if backup and target.exists():
        _make_backup(target)

    tmp_path: Path | None = None
    try:
        fd, tmp_name = tempfile.mkstemp(
            dir=str(target.parent), prefix=target.stem + ".", suffix=".tmp"
        )
        tmp_path = Path(tmp_name)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(str(tmp_path), str(target))
        tmp_path = None
    except OSError as exc:
        raise DelugeXMLError("écriture impossible de %s : %s" % (target, exc)) from exc
    finally:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:  # pragma: no cover
                pass

    doc.path = target
    log.info("XML enregistré : %s (%d octets)", target, len(data))
    return target


# ---------------------------------------------------------------------------
# Accès indifférent au dialecte
# ---------------------------------------------------------------------------


def get(el: ET.Element, name: str, default: str | None = None) -> str | None:
    """Lit un attribut OU un sous-élément texte de même nom."""
    if el is None:
        return default
    value = el.get(name)
    if value is not None:
        return value
    child = el.find(name)
    if child is not None:
        if len(child) == 0:
            return child.text if child.text is not None else ""
        if child.text is not None and child.text.strip():
            return child.text.strip()
    return default


def set_(el: ET.Element, name: str, value: str, dialect: str = "attr") -> None:
    """Écrit un attribut (dialecte ``'attr'``) ou un sous-élément texte (dialecte ``'elem'``)."""
    if el is None:
        return
    text = "" if value is None else str(value)
    if dialect == "elem":
        el.attrib.pop(name, None)
        child = el.find(name)
        if child is None:
            child = ET.SubElement(el, name)
        child.text = text
    else:
        child = el.find(name)
        if child is not None and len(child) == 0:
            el.remove(child)
        el.set(name, text)


def get_child(el: ET.Element, name: str) -> ET.Element | None:
    """Retourne le premier sous-élément ``name``, ou ``None``."""
    if el is None:
        return None
    return el.find(name)


def ensure_child(el: ET.Element, name: str) -> ET.Element:
    """Retourne le sous-élément ``name``, en le créant s'il manque."""
    child = el.find(name)
    if child is None:
        child = ET.SubElement(el, name)
    return child


def iter_children(el: ET.Element, name: str) -> Iterator[ET.Element]:
    """Itère sur tous les sous-éléments directs nommés ``name``."""
    if el is None:
        return iter(())
    return el.iterfind(name)


def remove_child(el: ET.Element, name: str) -> None:
    """Supprime tous les sous-éléments directs nommés ``name`` (et l'attribut homonyme)."""
    if el is None:
        return
    for child in list(el.findall(name)):
        el.remove(child)
    el.attrib.pop(name, None)
