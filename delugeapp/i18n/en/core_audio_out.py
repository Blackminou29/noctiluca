# -*- coding: utf-8 -*-
"""Anglais de ``delugeapp/core/audio_out.py`` : pourquoi rien ne s'entend."""

TEXTS = {
    "le paquet Python sounddevice n'est pas installé "
    "(pip install sounddevice)":
        "the Python package sounddevice is not installed "
        "(pip install sounddevice)",
    "la bibliothèque PortAudio manque : installez le paquet libportaudio2 "
    "(sudo apt install libportaudio2), puis relancez l'application":
        "the PortAudio library is missing: install the libportaudio2 package "
        "(sudo apt install libportaudio2), then restart the application",
    "la bibliothèque PortAudio n'a pas pu être chargée (%s)":
        "the PortAudio library could not be loaded (%s)",
    "aucune sortie audio n'a été trouvée sur cet ordinateur":
        "no audio output was found on this computer",
}
