# -*- coding: utf-8 -*-
"""Anglais de ``delugeapp/core/dxml.py`` : la lecture des XML du Deluge.

Les anomalies réparées se gardent en français dans l'index ; elles se
traduisent à l'affichage, par ``tr_stored``."""

TEXTS = {
    "BOM UTF-8 retiré": "UTF-8 BOM removed",
    "fichier UTF-16 converti en UTF-8": "UTF-16 file converted to UTF-8",
    "caractères interdits par XML 1.0 supprimés":
        "characters forbidden by XML 1.0 removed",
    "%d '&' non échappé(s) corrigé(s)": "%d unescaped '&' fixed",
    "octets non UTF-8 remplacés": "non-UTF-8 bytes replaced",
    "nom d'appareil MIDI en octets 0xFF, écrit par le firmware":
        "MIDI device name in 0xFF bytes, written by the firmware",
    "balises numériques de la bêta 1.3 (performanceView) renommées":
        "numeric tags of the 1.3 beta (performanceView) renamed",
    "document multi-racines enveloppé dans <%s>":
        "multi-root document wrapped in <%s>",
    "%d attribut(s) dupliqué(s) supprimé(s)":
        "%d duplicate attribute(s) removed",
    "XML illisible : %s": "unreadable XML: %s",
    "structure XML reconstruite par l'analyseur tolérant":
        "XML structure rebuilt by the tolerant parser",
    "XML illisible : aucune racine exploitable":
        "unreadable XML: no usable root",
    "%d balise(s) non fermée(s) refermée(s)": "%d unclosed tag(s) closed",
    "%d balise(s) fermée(s) dans le désordre":
        "%d tag(s) closed out of order",
    "%d balise(s) fermante(s) orpheline(s) ignorée(s)":
        "%d orphan closing tag(s) ignored",
    "fichier vide": "empty file",
    "%d élément(s) de premier niveau ignoré(s) : %s":
        "%d top-level element(s) ignored: %s",
    "lecture impossible de %s : %s": "could not read %s: %s",
    "%s : %s": "%s: %s",
    "document vide : rien à sérialiser": "empty document: nothing to write",
    "aucun chemin de destination pour l'enregistrement":
        "no destination path to save to",
    "dossier inaccessible %s : %s": "folder not accessible %s: %s",
    "sauvegarde .bak impossible : %s laissé intact":
        "could not make the .bak copy: %s left untouched",
    "écriture impossible de %s : %s": "could not write %s: %s",
}
