# -*- coding: utf-8 -*-
"""Anglais de ``delugeapp/core/soundedit.py`` : les réglages de l'éditeur
de son et ce qu'ils valent."""

TEXTS = {
    "Voix": "Voice",
    "Oscillateurs": "Oscillators",
    "Filtres": "Filters",
    "Enveloppes": "Envelopes",
    "LFO": "LFO",
    "Effets": "Effects",
    "Dent de scie": "Saw",
    "Carré": "Square",
    "Sinus": "Sine",
    "Triangle": "Triangle",
    "Dent de scie analogique": "Analog saw",
    "Carré analogique": "Analog square",
    "Échantillonné-bloqué": "Sample and hold",
    "Marche aléatoire": "Random walk",
    "Libre": "Free",
    "4 mesures": "4 bars",
    "2 mesures": "2 bars",
    "1 mesure": "1 bar",
    "Moteur": "Engine",
    "Soustractive": "Subtractive",
    "Ring mod": "Ring mod",
    "Le moteur de synthèse. Passer en FM éteint les filtres, comme sur la "
    "machine.":
        "The synthesis engine. Switching to FM turns the filters off, as on "
        "the machine.",
    "Jeu": "Play mode",
    "Polyphonique": "Polyphonic",
    "Étouffé": "Choke",
    "Mono : une note à la fois. Legato : une note à la fois, sans relancer "
    "les enveloppes ni glisser.":
        "Mono: one note at a time. Legato: one note at a time, without "
        "retriggering the envelopes or gliding.",
    "Transposition": "Transpose",
    "Tout le son, en demi-tons.": "The whole sound, in semitones.",
    "Glissé": "Glide",
    "Le temps que met la hauteur pour aller d'une note à la suivante ; 0 le "
    "coupe. Sans effet en legato.":
        "The time the pitch takes to go from one note to the next; 0 turns it "
        "off. No effect in legato.",
    "Volume": "Volume",
    "Le niveau du son. Loi quadratique : 25 sonne 12 dB sous 50.":
        "The level of the sound. Quadratic law: 25 sounds 12 dB below 50.",
    "Panoramique": "Pan",
    "Gauche ou droite ; 0 au centre.": "Left or right; 0 in the centre.",
    "Unisson": "Unison",
    "Le nombre de voix jouées ensemble à chaque note.":
        "The number of voices played together on each note.",
    "Désaccord": "Detune",
    "L'écart entre les voix d'unisson, réparti de −réglage/2 à +réglage/2 "
    "cents.":
        "The spread between the unison voices, from −setting/2 to +setting/2 "
        "cents.",
    "Étalement": "Spread",
    "Les voix d'unisson réparties dans l'espace stéréo.":
        "The unison voices spread across the stereo field.",
    "Forme A": "Shape A",
    "La forme d'onde de l'oscillateur A.": "The waveform of oscillator A.",
    "Transposition A": "Transpose A",
    "En demi-tons.": "In semitones.",
    "Accord fin A": "Fine tune A",
    "En cents (centièmes de demi-ton).":
        "In cents (hundredths of a semitone).",
    "Niveau A": "Level A",
    "Le niveau de l'oscillateur A, loi quadratique.":
        "The level of oscillator A, quadratic law.",
    "Largeur A": "Width A",
    "La largeur d'impulsion, pour les formes carrées : 25 donne un carré, les "
    "extrêmes une impulsion fine.":
        "The pulse width, for square shapes: 25 gives a square, the extremes "
        "a thin pulse.",
    "Forme B": "Shape B",
    "La forme d'onde de l'oscillateur B.": "The waveform of oscillator B.",
    "Transposition B": "Transpose B",
    "Accord fin B": "Fine tune B",
    "Niveau B": "Level B",
    "Le niveau de l'oscillateur B, loi quadratique.":
        "The level of oscillator B, quadratic law.",
    "Largeur B": "Width B",
    "La largeur d'impulsion de l'oscillateur B.":
        "The pulse width of oscillator B.",
    "Bruit": "Noise",
    "Le niveau du bruit blanc mêlé aux oscillateurs.":
        "The level of the white noise mixed with the oscillators.",
    "Modulateur 1": "Modulator 1",
    "FM : la profondeur du premier modulateur.":
        "FM: the depth of the first modulator.",
    "Accord modulateur 1": "Modulator 1 tuning",
    "FM : l'accord du premier modulateur, en demi-tons — c'est lui qui fait "
    "le timbre.":
        "FM: the tuning of the first modulator, in semitones — it is what "
        "makes the timbre.",
    "Modulateur 2": "Modulator 2",
    "FM : la profondeur du second modulateur.":
        "FM: the depth of the second modulator.",
    "Accord modulateur 2": "Modulator 2 tuning",
    "FM : l'accord du second modulateur, en demi-tons.":
        "FM: the tuning of the second modulator, in semitones.",
    "Passe-bas": "Low-pass",
    "24 dB saturé": "24 dB drive",
    "SVF passe-bande": "SVF band-pass",
    "SVF coupe-bande": "SVF notch",
    "Éteint": "Off",
    "Le type de filtre passe-bas.": "The type of low-pass filter.",
    "Coupure": "Cutoff",
    "La fréquence de coupure du passe-bas.":
        "The cutoff frequency of the low-pass.",
    "Résonance": "Resonance",
    "L'accentuation autour de la coupure.": "The emphasis around the cutoff.",
    "Passe-haut": "High-pass",
    "Échelle": "Ladder",
    "Le type de filtre passe-haut.": "The type of high-pass filter.",
    "Coupure passe-haut": "High-pass cutoff",
    "La fréquence de coupure du passe-haut ; 0 le laisse tout passer.":
        "The cutoff frequency of the high-pass; 0 lets everything through.",
    "Résonance passe-haut": "High-pass resonance",
    "L'accentuation autour de la coupure du passe-haut.":
        "The emphasis around the high-pass cutoff.",
    "Attaque %d": "Attack %d",
    "Le temps de montée.": "The rise time.",
    "Decay %d": "Decay %d",
    "Le temps de descente vers le palier.":
        "The fall time towards the sustain.",
    "Palier %d": "Sustain %d",
    "Le niveau tenu tant que la touche l'est.":
        "The level held as long as the key is.",
    "Release %d": "Release %d",
    "Le temps d'extinction, une fois la touche relâchée.":
        "The fade-out time, once the key is released.",
    "Forme LFO 1": "LFO 1 shape",
    "La forme du LFO 1, commun à toutes les notes.":
        "The shape of LFO 1, shared by all notes.",
    "Calage LFO 1": "LFO 1 sync",
    "Libre, ou calé sur le tempo du morceau.":
        "Free, or locked to the song's tempo.",
    "Vitesse LFO 1": "LFO 1 rate",
    "La vitesse du LFO 1 quand il est libre.":
        "The rate of LFO 1 when it is free.",
    "Forme LFO 2": "LFO 2 shape",
    "La forme du LFO 2, relancé à chaque note.":
        "The shape of LFO 2, restarted on each note.",
    "Calage LFO 2": "LFO 2 sync",
    "Vitesse LFO 2": "LFO 2 rate",
    "La vitesse du LFO 2 quand il est libre.":
        "The rate of LFO 2 when it is free.",
    "Réverbération": "Reverb",
    "L'envoi vers la réverbération du morceau.":
        "The send to the song's reverb.",
    "Délai": "Delay",
    "Le retour du délai : combien de répétitions. 50 ne s'arrête plus.":
        "The delay feedback: how many repeats. 50 never stops.",
    "Calage du délai": "Delay sync",
    "Le temps du délai, calé sur le tempo ou libre.":
        "The delay time, locked to the tempo or free.",
    "Temps du délai": "Delay time",
    "Le temps du délai quand il est libre.": "The delay time when it is free.",
    "Mod FX": "Mod FX",
    "Aucun": "None",
    "Chorus stéréo": "Stereo chorus",
    "L'effet de modulation : chorus, flanger, phaser…":
        "The modulation effect: chorus, flanger, phaser…",
    "Profondeur mod FX": "Mod FX depth",
    "La profondeur de l'effet de modulation.":
        "The depth of the modulation effect.",
    "Vitesse mod FX": "Mod FX rate",
    "La vitesse de l'effet de modulation.":
        "The rate of the modulation effect.",
    "Saturation": "Saturation",
    "La saturation du son, de 0 à 15 comme sur la machine.":
        "The saturation of the sound, from 0 to 15 as on the machine.",
    "Réduction de bits": "Bit reduction",
    "Moins de bits : un grain numérique.": "Fewer bits: a digital grain.",
    "Réduction de fréquence": "Rate reduction",
    "Une fréquence d'échantillonnage abaissée : un son métallique.":
        "A lowered sample rate: a metallic sound.",
    "Graves": "Bass",
    "L'égaliseur, dans les graves.": "The equaliser, in the bass.",
    "Aigus": "Treble",
    "L'égaliseur, dans les aigus.": "The equaliser, in the treble.",
    "instantané": "instant",
    "%d ms": "%d ms",
    "%s s": "%s s",
    "%s kHz": "%s kHz",
    "%d Hz": "%d Hz",
    "%s Hz": "%s Hz",
    "silence": "silence",
    "%s dB": "%s dB",
    "%d %%": "%d%%",
    "tout passe": "everything passes",
    "calé : %s": "synced: %s",
    "≈ %s": "≈ %s",
    "coupé": "off",
    "centre": "centre",
    "gauche": "left",
    "droite": "right",
    "%s %d %%": "%s %d%%",
    "une seule voix": "a single voice",
    "±%s cents": "±%s cents",
    "%d voix": "%d voices",
    "%+d demi-tons": "%+d semitones",
    "à l'unisson": "in unison",
    "%+d cents": "%+d cents",
    "Vélocité": "Velocity",
    "Enveloppe 1": "Envelope 1",
    "Enveloppe 2": "Envelope 2",
    "LFO 1": "LFO 1",
    "LFO 2": "LFO 2",
    "Note jouée": "Note played",
    "Aléatoire": "Random",
    "Hauteur": "Pitch",
    "Hauteur A": "Pitch A",
    "Hauteur B": "Pitch B",
    "Attaque 1": "Attack 1",
    "Release 1": "Release 1",
    "Decay 2": "Decay 2",
    "%s demi-ton": "%s semitone",
    "%s octave(s)": "%s octave(s)",
    "×%s à ×%s": "×%s to ×%s",
    "%+d %%": "%+d%%",
    "%s : %s → %s": "%s: %s → %s",
    "Modulations modifiées": "Modulation changed",
}
