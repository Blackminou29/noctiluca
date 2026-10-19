# -*- coding: utf-8 -*-
"""Anglais de ``delugeapp/core/wav.py`` : lecture et contrôle des fichiers
audio."""

TEXTS = {
    "fichier trop court": "file too short",
    "conteneur RIFF sans forme WAVE": "RIFF container without a WAVE form",
    "chunk fmt incomplet": "incomplete fmt chunk",
    "nombre de bits invalide": "invalid bit count",
    "format WAV non géré (code 0x%04X)": "unsupported WAV format (code 0x%04X)",
    "chunk fmt absent": "fmt chunk missing",
    "chunk data absent": "data chunk missing",
    "taux d'échantillonnage invalide": "invalid sample rate",
    "conteneur FORM inconnu": "unknown FORM container",
    "chunk COMM incomplet": "incomplete COMM chunk",
    "compression AIFC non gérée (%s)": "unsupported AIFC compression (%s)",
    "chunk COMM absent": "COMM chunk missing",
    "chunk SSND absent": "SSND chunk missing",
    "fichier vide ou trop court": "empty or too short file",
    "format de fichier inconnu (%s)": "unknown file format (%s)",
    "en-tête incohérent": "inconsistent header",
    "nombre de canaux aberrant (%d)": "absurd channel count (%d)",
    "largeur d'échantillon non gérée (%d octets)":
        "unsupported sample width (%d bytes)",
    "erreur inattendue: %s": "unexpected error: %s",
    "nom commençant par un point : le Deluge ne le montre pas":
        "name starting with a dot: the Deluge does not show it",
    "extension %s : le Deluge ne lit que le WAV et l'AIFF":
        "%s extension: the Deluge only reads WAV and AIFF",
    "absente": "missing",
    "illisible : %s": "unreadable: %s",
    "extension .aifc": ".aifc extension",
    "%s, et illisible ici : %s": "%s, and unreadable here: %s",
    "fichier vide ou tronqué": "empty or truncated file",
    "en-tête « fmt » incomplet": "incomplete “fmt” header",
    "en-tête étendu (WAVE_FORMAT_EXTENSIBLE)":
        "extended header (WAVE_FORMAT_EXTENSIBLE)",
    "PCM %d bits": "%d-bit PCM",
    "flottant %d bits": "%d-bit float",
    "format compressé (code 0x%04X) que ni le Deluge ni l'application ne "
    "savent lire":
        "compressed format (code 0x%04X) that neither the Deluge nor the "
        "application can read",
    "%d canaux : le Deluge ne lit que le mono et la stéréo":
        "%d channels: the Deluge only reads mono and stereo",
    "%d Hz, hors des 5 000 à 96 000 Hz qu'il lit":
        "%d Hz, outside the 5,000 to 96,000 Hz it reads",
    "en-tête « COMM » incomplet": "incomplete “COMM” header",
    "en-tête « COMM » de %d octets": "%d-byte “COMM” header",
    "compression AIFC « %s » que ni le Deluge ni l'application ne savent "
    "lire":
        "AIFC compression “%s” that neither the Deluge nor the application "
        "can read",
    "fichier abîmé : en-tête ou données absents":
        "damaged file: header or data missing",
    "profondeur de bits inconnue : %r": "unknown bit depth: %r",
    "profondeur de bits non gérée : %r": "unsupported bit depth: %r",
    "forme de tableau non gérée : %r": "unsupported array shape: %r",
    "profondeur de bits non gérée : %d": "unsupported bit depth: %d",
    "taux d'échantillonnage invalide : %r": "invalid sample rate: %r",
    "aucun canal à écrire": "no channel to write",
    "source illisible : %s": "unreadable source: %s",
    "source illisible": "unreadable source",
    "écriture invalide : %s": "invalid write: %s",
}
