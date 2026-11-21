# -*- coding: utf-8 -*-
"""Tests du dialogue avec le Deluge : MIDI, MIDI Follow, lien USB et
SysEx, synchronisation de la carte, envoi au Deluge, favoris,
firmware.

Sans carte réelle ni Qt : chaque test fabrique sa carte jetable. Découpés
de ``test_core.py`` le 20 novembre 2026.

    python -m unittest tests.test_deluge -v
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

# --------------------------------------------------------------------------- #
# Bac à sable — avant tout import de ``delugeapp``
# --------------------------------------------------------------------------- #
# Rien ici ne doit toucher aux réglages réels de l'utilisateur : voir
# ``test_core.py``, où ces lignes sont expliquées.
import os as _os                                             # noqa: E402
import tempfile as _tempfile                                 # noqa: E402

BAC_A_SABLE = Path(_tempfile.gettempdir()) / "noctiluca-tests"
BAC_A_SABLE.mkdir(parents=True, exist_ok=True)
_os.environ["NOCTILUCA_CONFIG"] = str(BAC_A_SABLE)

from delugeapp.core import (backup, db, deps, organize, rhythm, samplefix,
                            scan, sdcard, wav)
from delugeapp.core.fixedpoint import INT32_MAX, INT32_MIN
from delugeapp.core.model import Note, Sound, SynthPreset

import sys as _sys                                           # noqa: E402

# Les aides partagées (``tests/aides_coeur.py``), par leur nom : ``unittest
# discover -s tests`` charge les modules à plat, pytest en paquet.
_DOSSIER = str(Path(__file__).resolve().parent)
if _DOSSIER not in _sys.path:
    _sys.path.insert(0, _DOSSIER)
from aides_coeur import _SortieFactice, _son  # noqa: E402


class TestMidiPort(unittest.TestCase):
    """La couche MIDI, en ctypes sur ``winmm`` : aucune dépendance.

    Ni ``mido`` ni ``python-rtmidi`` ne sont installés sur la machine de
    l'utilisateur, et le projet n'exige rien de plus que ``numpy`` et PyQt6.
    """

    def test_encodage_d_un_message(self):
        from delugeapp.core import midiport

        self.assertEqual(midiport.short_message(0x90, 60, 100), 0x00643C90)
        self.assertEqual(midiport.short_message(0xB0, 74, 0), 0x00004AB0)

    def test_les_octets_de_donnees_sont_bornes(self):
        """Un octet MIDI ne dépasse pas 127 : un message illégal bloque le
        flux de certains appareils."""
        from delugeapp.core import midiport

        self.assertEqual(midiport.short_message(0x90, 999, -5), 0x00007F90)
        self.assertEqual(midiport.short_message(0x90, -1, 300), 0x007F0090)

    def test_les_canaux_vont_de_1_a_16(self):
        from delugeapp.core.midiport import _channel

        self.assertEqual([_channel(v) for v in (1, 16, 0, 99, "x", None)],
                         [0, 15, 0, 15, 0, 0])

    def test_reconnaitre_un_deluge_a_son_nom(self):
        from delugeapp.core.midiport import MidiDevice

        for nom in ("Deluge", "2- Deluge", "Synthstrom Deluge",
                    "DELUGE MIDI 1"):
            self.assertTrue(MidiDevice(0, nom, "out").is_deluge, nom)
        for nom in ("Microsoft GS Wavetable Synth", "loopMIDI Port", ""):
            self.assertFalse(MidiDevice(0, nom, "out").is_deluge, nom)

    def test_enumeration(self):
        from delugeapp.core import midiport

        if not midiport.available():
            self.skipTest("pas de MIDI sur cette machine")
        for appareil in midiport.outputs():
            self.assertIsInstance(appareil.name, str)
            self.assertEqual(appareil.kind, "out")

    def test_un_port_ferme_refuse_tout_sans_lever(self):
        """Rien ne doit lever parce qu'aucun appareil n'est branché."""
        from delugeapp.core import midiport

        out = midiport.MidiOut()
        self.assertFalse(out.is_open)
        self.assertFalse(out.note_on(60))
        self.assertFalse(out.note_off(60))
        self.assertFalse(out.control_change(74, 64))
        self.assertFalse(out.program_change(3))
        self.assertFalse(out.pitch_bend(0))
        self.assertFalse(out.realtime(midiport.CLOCK))
        self.assertFalse(out.open(None))
        out.all_notes_off()               # ne doit pas lever
        out.close()                       # ni fermer deux fois
        out.close()

    def test_ouvrir_et_fermer_un_vrai_port(self):
        from delugeapp.core import midiport

        # Jamais le Deluge : la note et le CC 74 — la coupure du filtre en
        # MIDI Follow — iraient modifier le son en cours sur la machine.
        ports = [p for p in midiport.outputs() if not p.is_deluge]
        if not ports:
            self.skipTest("aucun port de sortie MIDI autre que le Deluge")
        out = midiport.MidiOut()
        ouvert = out.open(ports[0])
        if not ouvert and os.environ.get("GITHUB_ACTIONS"):
            # Les machines Windows Server de GitHub déclarent le synthé GS de
            # Microsoft mais refusent de l'ouvrir, faute de service audio
            # (9 novembre 2026). Ailleurs, un refus reste une erreur.
            self.skipTest("port %s refusé par la machine de GitHub : %s"
                          % (ports[0].name, out.last_error))
        self.assertTrue(ouvert, out.last_error)
        try:
            self.assertTrue(out.is_open)
            self.assertEqual(out.device.name, ports[0].name)
            # Vélocité 1 : la chaîne est prouvée sans faire de bruit.
            self.assertTrue(out.note_on(60, 1))
            self.assertTrue(out.note_off(60))
            self.assertTrue(out.control_change(74, 64))
        finally:
            out.close()
        self.assertFalse(out.is_open)


class TestMidiFollow(unittest.TestCase):
    """La carte « paramètre -> contrôleur » du firmware communautaire.

    Relevée sur la carte de l'utilisateur : 56 entrées, dont une sans
    contrôleur (``stutterRate`` vaut 255, hors de 0..127) et trois sans
    équivalent dans le modèle. Restent 52 paramètres pilotables.
    """

    def test_les_defauts_donnent_52_parametres(self):
        from delugeapp.core import midifollow

        carte = midifollow.load_map()
        self.assertEqual(len(carte), 52)

    def test_un_controleur_hors_plage_est_ecarte(self):
        """255 veut dire « non assigné », pas « contrôleur 255 »."""
        from delugeapp.core import midifollow

        self.assertEqual(midifollow.DEFAULT_CC["stutterRate"], 255)
        self.assertNotIn("stutterRate", midifollow.load_map())

    def test_les_noms_du_firmware_sont_traduits(self):
        from delugeapp.core import midifollow

        carte = midifollow.load_map()
        attendu = {"volume": 7, "pitchAdjust": 3, "oscAPitchAdjust": 12,
                   "oscAPulseWidth": 23, "bitCrush": 62,
                   "arpeggiatorGate": 50, "bassFrequency": 84,
                   "modulator1Amount": 54, "env1.attack": 73,
                   "env2.release": 80, "lpfFrequency": 74}
        for cle, cc in attendu.items():
            self.assertEqual(carte.get(cle), cc, cle)

    def test_les_parametres_sans_equivalent_sont_ecartes(self):
        from delugeapp.core import midifollow

        carte = midifollow.load_map()
        for nom in midifollow.SANS_EQUIVALENT:
            self.assertNotIn(nom, carte)

    def test_conversion_en_valeur_de_controleur(self):
        from delugeapp.core import midifollow

        self.assertEqual(midifollow.cc_value(INT32_MIN), 0)
        self.assertEqual(midifollow.cc_value(INT32_MAX), 127)
        self.assertEqual(midifollow.cc_value(0), 64)
        # Et rien ne sort de 0..127, même avec une valeur aberrante.
        for brut in (-(1 << 40), 1 << 40):
            self.assertIn(midifollow.cc_value(brut), (0, 127))

    def test_lire_le_fichier_de_la_carte(self):
        """Le fichier de l'utilisateur l'emporte sur les valeurs par défaut."""
        from delugeapp.core import midifollow

        with tempfile.TemporaryDirectory() as tmp:
            chemin = Path(tmp) / "MIDIFollow.XML"
            chemin.write_text(
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<defaults><defaultCCMappings>"
                "<lpfFrequency>99</lpfFrequency>"
                "<volumePostFX>8</volumePostFX>"
                "<stutterRate>255</stutterRate>"
                "</defaultCCMappings></defaults>", encoding="utf-8")
            carte = midifollow.load_map(path=chemin)
            self.assertEqual(carte.get("lpfFrequency"), 99)
            self.assertEqual(carte.get("volume"), 8)
            self.assertNotIn("stutterRate", carte)

    def test_la_table_dit_d_ou_elle_vient(self):
        """Sans fichier lu, ce sont les valeurs d'usine : l'interface ne
        doit pas prétendre les avoir lues sur la carte."""
        from delugeapp.core import midifollow

        carte, source = midifollow.load_map_with_source()
        self.assertEqual((len(carte), source), (52, ""))
        with tempfile.TemporaryDirectory() as tmp:
            chemin = Path(tmp) / "MIDIFollow.XML"
            chemin.write_bytes(b"\x00\x01 pas du XML")
            self.assertEqual(midifollow.load_map_with_source(path=chemin)[1],
                             "")
            chemin.write_text(
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<defaults><defaultCCMappings>"
                "<lpfFrequency>99</lpfFrequency>"
                "</defaultCCMappings></defaults>", encoding="utf-8")
            carte, source = midifollow.load_map_with_source(path=chemin)
            self.assertEqual((carte, source),
                             ({"lpfFrequency": 99}, "MIDIFollow.XML"))

            from delugeapp.core.delugelink import DelugeLink

            class Carte:
                root = Path(tmp)

            lien = DelugeLink()
            lien.load_follow_map(Carte())
            self.assertEqual(lien.state().follow_source, "MIDIFollow.XML")
            lien.load_follow_map(None)
            self.assertEqual(lien.state().follow_source, "")

    #: La forme du fichier en firmware 1.3, relevée sur la carte de
    #: l'utilisateur (``SETTINGS/MIDIFollow.XML``), abrégée.
    FOLLOW_13 = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<defaults>\n'
        "\t<cc_mappings>\n\t\t<pitch>3</pitch>\n\t\t<volumePostFX>7</volumePostFX>"
        "\n\t\t<lpfFrequency>74</lpfFrequency>\n\t\t<env3Attack>40</env3Attack>"
        "\n\t</cc_mappings>\n\t<settings>\n\t\t<channels>\n"
        "\t\t\t<a>\n\t\t\t\t<channel>1</channel>\n\t\t\t</a>\n"
        "\t\t\t<b>\n\t\t\t\t<channel>256</channel>\n\t\t\t</b>\n"
        "\t\t\t<track_1>\n\t\t\t\t<channel>256</channel>\n\t\t\t</track_1>\n"
        "\t\t</channels>\n\t\t<kit_root_note>\n\t\t\t<note>36</note>\n"
        "\t\t</kit_root_note>\n\t\t<feedback>\n\t\t\t<channel>a</channel>\n"
        "\t\t\t<automation>disabled</automation>\n\t\t</feedback>\n"
        "\t</settings>\n</defaults>\n")

    def test_le_fichier_de_la_1_3_n_assigne_que_ses_controleurs(self):
        """Mesuré : faute de reconnaître ``cc_mappings``, canaux et note de
        base passaient pour des contrôleurs (80 au lieu de 79)."""
        from delugeapp.core import midifollow

        with tempfile.TemporaryDirectory() as tmp:
            chemin = Path(tmp) / "MIDIFollow.XML"
            chemin.write_text(self.FOLLOW_13, encoding="utf-8")
            carte = midifollow.load_map(path=chemin)
        self.assertEqual(carte.get("lpfFrequency"), 74)
        self.assertEqual(carte.get("volume"), 7)
        self.assertNotIn(1, [v for k, v in carte.items() if k != "pitchAdjust"])
        self.assertEqual(set(carte.values()), {3, 7, 74, 40})

    def test_les_reglages_de_la_machine_se_lisent(self):
        """Le canal s'écrit + 1 ; 256 veut dire « aucun »."""
        from delugeapp.core import midifollow

        with tempfile.TemporaryDirectory() as tmp:
            chemin = Path(tmp) / "MIDIFollow.XML"
            chemin.write_text(self.FOLLOW_13, encoding="utf-8")
            reglages = midifollow.read_settings(path=chemin)
            self.assertEqual(reglages, midifollow.FollowSettings(
                channel_a=1, channel_b=None, channel_c=None, kit_root_note=36,
                feedback="a"))
            ancien = Path(tmp) / "ancien.XML"
            ancien.write_text('<?xml version="1.0"?><defaults>'
                              "<defaultCCMappings><pitch>3</pitch>"
                              "</defaultCCMappings></defaults>",
                              encoding="utf-8")
            self.assertIsNone(midifollow.read_settings(path=ancien))

    def test_la_1_3_range_le_fichier_dans_settings(self):
        from delugeapp.core import midifollow

        class Carte:
            pass

        with tempfile.TemporaryDirectory() as tmp:
            Carte.root = Path(tmp)
            (Path(tmp) / "SETTINGS").mkdir()
            (Path(tmp) / "SETTINGS" / "MIDIFollow.XML").write_text(
                self.FOLLOW_13, encoding="utf-8")
            carte, source = midifollow.load_map_with_source(Carte())
            self.assertEqual(source, "MIDIFollow.XML")
            self.assertEqual(carte.get("lpfFrequency"), 74)
            self.assertEqual(midifollow.read_settings(Carte()).channel_a, 1)

    def test_un_fichier_abime_retombe_sur_les_defauts(self):
        from delugeapp.core import midifollow

        with tempfile.TemporaryDirectory() as tmp:
            chemin = Path(tmp) / "MIDIFollow.XML"
            chemin.write_bytes(b"\x00\x01 pas du XML")
            self.assertEqual(len(midifollow.load_map(path=chemin)), 52)

    def test_un_son_devient_une_liste_de_controleurs(self):
        from delugeapp.core import midifollow

        son = Sound()
        son.set_param("lpfFrequency", INT32_MAX)
        son.set_param("pan", 0)
        messages = midifollow.sound_messages(son)
        self.assertIn((74, 127), messages)
        self.assertIn((10, 64), messages)
        # Un paramètre absent du son n'est pas envoyé : l'écrire écraserait
        # sur la machine un réglage que l'application ne connaît pas.
        envoyes = {cc for cc, _v in messages}
        self.assertNotIn(91, envoyes)        # reverbAmount, jamais réglé

    def test_un_seul_parametre_a_la_fois(self):
        from delugeapp.core import midifollow

        son = Sound()
        son.set_param("lpfFrequency", INT32_MIN)
        son.set_param("lpfResonance", INT32_MAX)
        self.assertEqual(
            midifollow.sound_messages(son, keys=["lpfResonance"]),
            [(71, 127)])


class TestDelugeLink(unittest.TestCase):
    """Le lien complet : état, envoi, séquenceur."""

    def test_sans_rien_de_branche_tout_repond_sans_lever(self):
        from delugeapp.core.delugelink import DelugeLink

        lien = DelugeLink()
        self.assertFalse(lien.is_connected)
        self.assertEqual(lien.send_sound(Sound()), 0)
        self.assertFalse(lien.send_param("lpfFrequency", 0))
        self.assertFalse(lien.note_on(60))
        self.assertFalse(lien.play_notes(60))
        lien.panic()
        lien.disconnect()

    def test_le_canal_reste_entre_1_et_16(self):
        from delugeapp.core.delugelink import DelugeLink

        lien = DelugeLink()
        for donne, attendu in ((1, 1), (16, 16), (0, 1), (99, 16),
                               ("x", 1), (None, 1)):
            lien.set_channel(donne)
            self.assertEqual(lien.channel, attendu, donne)

    def test_l_etat_se_raconte_en_francais(self):
        from delugeapp.core.delugelink import LinkState

        self.assertIn("indisponible", LinkState().summary())
        self.assertIn("Branchez", LinkState(supported=True).summary())
        self.assertIn("pas encore connect\u00e9",
                      LinkState(supported=True,
                                ports_out=["Deluge"]).summary())
        self.assertIn("deux sens",
                      LinkState(supported=True, out_name="Deluge",
                                in_name="Deluge", deluge_out=True).summary())
        self.assertIn("envoi seulement",
                      LinkState(supported=True, out_name="Deluge",
                                deluge_out=True).summary())

    def test_notes_accords_et_suites(self):
        from delugeapp.core.delugelink import _as_steps

        self.assertEqual(_as_steps(60), [[60]])
        self.assertEqual(_as_steps([60, 64]), [[60], [64]])
        self.assertEqual(_as_steps([[60, 64, 67]]), [[60, 64, 67]])
        self.assertEqual(_as_steps(None), [])
        self.assertEqual(_as_steps([]), [])

    def test_le_sequenceur_pose_les_coups_au_bon_moment(self):
        """Le test qui aurait attrapé mon erreur de lecture du motif.

        Un motif techno d'une mesure : la grosse caisse tombe sur les pas
        0, 4, 8 et 12. À 240 BPM, un pas dure 62,5 ms, donc les quatre coups
        doivent arriver à 0, 250, 500 et 750 ms.
        """
        from delugeapp.core import rhythm
        from delugeapp.core.delugelink import DelugeLink

        motif = rhythm.genre_beat("techno", bars=1, seed=1, fills=False)
        positions = [st.pos for st in motif.tracks["Kick"]]
        self.assertEqual(positions, [0, 4, 8, 12], "le motif a changé")

        lien = DelugeLink()
        fausse = _SortieFactice()
        lien._out = fausse
        duree_pas = 60.0 / 240 * motif.ticks_per_step / motif.ppq

        self.assertTrue(lien.play_pattern(motif, bpm=240,
                                          row_notes={"Kick": 36}))
        for _ in range(400):
            if not lien.is_playing:
                break
            time.sleep(0.01)
        self.assertFalse(lien.is_playing, "le motif ne s'arrête pas")

        frappes = fausse.temps_des("on", 36)
        self.assertEqual(len(frappes), 4, "quatre coups de grosse caisse")
        for index, (vu, pas) in enumerate(zip(frappes, positions)):
            attendu = pas * duree_pas
            self.assertAlmostEqual(
                vu, attendu, delta=0.05,
                msg="coup %d : %.3f s au lieu de %.3f s"
                    % (index, vu, attendu))

    def test_chaque_note_allumee_est_eteinte(self):
        """Une note qui reste coincée se remarque très vite à l'oreille."""
        from delugeapp.core import rhythm
        from delugeapp.core.delugelink import DelugeLink

        motif = rhythm.genre_beat("house", bars=1, seed=3, fills=True)
        lien = DelugeLink()
        fausse = _SortieFactice()
        lien._out = fausse
        lien.play_pattern(motif, bpm=480)
        for _ in range(400):
            if not lien.is_playing:
                break
            time.sleep(0.01)

        allumees = [e[2] for e in fausse.events if e[1] == "on"]
        eteintes = [e[2] for e in fausse.events if e[1] == "off"]
        for note in set(allumees):
            self.assertGreaterEqual(
                eteintes.count(note), allumees.count(note),
                "la note %d reste allumée" % note)

    def test_l_horloge_bat_24_fois_par_noire(self):
        from delugeapp.core import rhythm
        from delugeapp.core.delugelink import DelugeLink
        from delugeapp.core import midiport

        motif = rhythm.genre_beat("techno", bars=1, seed=1, fills=False)
        lien = DelugeLink()
        fausse = _SortieFactice()
        lien._out = fausse
        lien.play_pattern(motif, bpm=480, clock=True)
        for _ in range(400):
            if not lien.is_playing:
                break
            time.sleep(0.01)

        horloges = [e for e in fausse.events
                    if e[1] == "rt" and e[2] == midiport.CLOCK]
        noires = motif.length_ticks / motif.ppq
        self.assertEqual(len(horloges), int(round(24 * noires)))
        departs = [e for e in fausse.events
                   if e[1] == "rt" and e[2] == midiport.START]
        arrets = [e for e in fausse.events
                  if e[1] == "rt" and e[2] == midiport.STOP]
        self.assertEqual((len(departs), len(arrets)), (1, 1))

    def test_arreter_coupe_tout_de_suite(self):
        from delugeapp.core import rhythm
        from delugeapp.core.delugelink import DelugeLink

        motif = rhythm.genre_beat("techno", bars=4, seed=1, fills=True)
        lien = DelugeLink()
        lien._out = _SortieFactice()
        lien.play_pattern(motif, bpm=30)         # plusieurs secondes
        time.sleep(0.1)
        debut = time.monotonic()
        lien.stop_playing()
        self.assertLess(time.monotonic() - debut, 0.5, "l'arrêt traîne")
        self.assertFalse(lien.is_playing)

    def test_envoyer_un_son_compte_les_controleurs(self):
        from delugeapp.core.delugelink import DelugeLink

        son = Sound()
        son.set_param("lpfFrequency", INT32_MAX)
        son.set_param("reverbAmount", 0)
        lien = DelugeLink()
        lien._out = _SortieFactice()
        lien.load_follow_map()
        # Deux paramètres posés, **plus les huit segments des deux
        # enveloppes** : celles-ci existent toujours sur un ``Sound``, avec
        # leurs valeurs par défaut. J'attendais 2 ; le code avait raison.
        self.assertEqual(lien.send_sound(son), 10)
        self.assertEqual(lien.send_sound(son, keys=["lpfFrequency"]), 1)
        self.assertEqual(
            lien.send_sound(son, keys=["reverbAmount", "env1.attack"]), 2)


class TestSysexDuDeluge(unittest.TestCase):
    """Le SysEx du firmware c1.2.1, lu dans son code.

    Les vecteurs de compression sont calculés **à la main** d'après
    ``util/pack.c`` : un portage fautif et un test recopié du portage
    seraient d'accord entre eux.
    """

    def test_les_demandes_s_ecrivent_comme_le_firmware_les_attend(self):
        from delugeapp.core import delugesysex as sx

        self.assertEqual(sx.identity_request().hex(" "), "f0 7e 7f 06 01 f7")
        self.assertEqual(sx.ping(42).hex(" "), "f0 00 21 7b 01 00 2a f7")
        self.assertEqual(sx.popup().hex(" "), "f0 00 21 7b 01 01 f7")
        self.assertEqual(sx.display_request().hex(" "),
                         "f0 00 21 7b 01 02 00 03 f7")

    def test_la_demande_qui_change_l_ecran_de_la_machine_est_refusee(self):
        """Le mode 4 appelle ``swapDisplayType`` : il bascule l'écran de la
        machine entre OLED et sept segments."""
        from delugeapp.core import delugesysex as sx

        with self.assertRaises(ValueError):
            sx.display_request(4)

    def test_compression_vecteurs_calcules_a_la_main(self):
        from delugeapp.core import delugesysex as sx

        cas = {
            bytes(10): [84, 0],                 # 64 + 2×10, puis l'octet
            bytes([0x80] * 3): [71, 0],         # 64 + 1 (bit fort) + 2×3
            bytes([1, 2]): [0, 1, 2],           # dense de 2 : décalage 0
            bytes([0xFF]): [67, 0x7F],          # dense de 1 : 64 + 2 + 1
            bytes(40): [126, 9, 0],             # 31 + 9 répétitions
            bytes([1, 2, 3]): [4, 1, 2, 3],     # dense de 3 : décalage 4
        }
        for source, attendu in cas.items():
            with self.subTest(source=source.hex()):
                self.assertEqual(list(sx.pack_8to7_rle(source)), attendu)
                self.assertEqual(sx.unpack_7to8_rle(bytes(attendu)), source)

    def test_codage_7_bits_de_sequential(self):
        from delugeapp.core import delugesysex as sx

        source = bytes([0x81, 2, 3, 4, 5, 6, 0x87])
        self.assertEqual(list(sx.pack_8bit_to_7bit(source)),
                         [0x41, 1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(sx.unpack_7bit_to_8bit(
            sx.pack_8bit_to_7bit(source)), source)

    def test_allers_retours_sur_des_ecrans_varies(self):
        import random

        from delugeapp.core import delugesysex as sx

        rng = random.Random(3)
        for essai in range(60):
            source = bytes(rng.choice((0, 0, 0, 0xFF, rng.randrange(256)))
                           for _ in range(sx.OLED_BYTES))
            with self.subTest(essai=essai):
                code = sx.pack_8to7_rle(source)
                self.assertTrue(all(octet < 128 for octet in code))
                self.assertEqual(sx.unpack_7to8_rle(code, sx.OLED_BYTES),
                                 source)

    def test_un_flux_abime_ne_leve_pas(self):
        from delugeapp.core import delugesysex as sx

        self.assertIsNone(sx.unpack_7to8_rle(bytes([62, 0, 0])))
        self.assertIsNone(sx.parse(b"\xf0\x00\x21\x7b\x01\x02\x40\x01\x00"
                                   b"\x3e\x00\xf7"))
        self.assertIsNone(sx.parse(b"\x90\x40\x40"))
        self.assertIsNone(sx.parse(b""))

    def test_lire_l_identite(self):
        from delugeapp.core import delugesysex as sx

        reponse = bytes((0xF0, 0x7E, 0x7F, 0x06, 0x02, 0x00, 0x21, 0x7B,
                         0x01, 0, 0, 0, 1, 2, 1, 0, 0xF7))
        identite = sx.parse(reponse)
        self.assertEqual(identite.version, "c1.2.1")
        self.assertTrue(identite.community)
        officiel = sx.Identity(4, 1, 4)
        self.assertEqual((officiel.version, officiel.community),
                         ("4.1.4", False))
        autre = bytearray(reponse)
        autre[6] = 0x22                     # un autre fabricant
        self.assertIsNone(sx.parse(bytes(autre)))

    def test_l_ecran_se_reconstruit_image_puis_differences(self):
        """Bit 0 d'un octet = pixel du **haut** de sa colonne."""
        from delugeapp.core import delugesysex as sx

        image = bytearray(sx.OLED_BYTES)
        image[0] = 0x01                     # (0, 0)
        image[128 + 5] = 0x80               # (5, 15)
        trame = (b"\xf0\x00\x21\x7b\x01\x02\x40\x01\x00"
                 + sx.pack_8to7_rle(bytes(image)) + b"\xf7")
        ecran = sx.OledScreen()
        self.assertTrue(ecran.apply(sx.parse(trame)))
        self.assertTrue(ecran.pixel(0, 0))
        self.assertTrue(ecran.pixel(5, 15))
        self.assertFalse(ecran.pixel(0, 1))
        self.assertEqual(ecran.lit_count(), 2)
        difference = (b"\xf0\x00\x21\x7b\x01\x02\x40\x02\x02\x01"
                      + sx.pack_8to7_rle(bytes([0xFF] * 8)) + b"\xf7")
        delta = sx.parse(difference)
        self.assertEqual((delta.start, len(delta.data)), (2, 8))
        ecran.apply(delta)
        self.assertEqual(ecran.lit_count(), 2 + 64)
        self.assertTrue(all(ecran.pixel(x, y) for x in range(16, 24)
                            for y in range(8)))

    def test_une_difference_pleine_page_vaut_une_image(self):
        """Mesuré sur la machine : l'abonnement forcé (mode 3) répond par
        une différence qui couvre tout l'écran, jamais par une image."""
        from delugeapp.core import delugesysex as sx

        ecran = sx.OledScreen()
        partielle = (b"\xf0\x00\x21\x7b\x01\x02\x40\x02\x00\x01"
                     + sx.pack_8to7_rle(bytes([0xFF] * 8)) + b"\xf7")
        self.assertTrue(ecran.apply(sx.parse(partielle)))
        self.assertFalse(ecran.complete)
        pleine = (b"\xf0\x00\x21\x7b\x01\x02\x40\x02\x00\x60"
                  + sx.pack_8to7_rle(bytes(sx.OLED_BYTES)) + b"\xf7")
        delta = sx.parse(pleine)
        self.assertEqual((delta.start, len(delta.data)), (0, sx.OLED_BYTES))
        self.assertTrue(ecran.apply(delta))
        self.assertTrue(ecran.complete)
        self.assertEqual(ecran.lit_count(), 0)

    #: Réponse du Deluge branché (firmware c1.2.1) à la demande d'image
    #: compressée (mode 1), telle qu'elle est arrivée : l'écran montrait
    #: « SYNTH » au-dessus de « TB01 ».
    TRAME_MESUREE = (
        "f000217b01024001007e7f006600424c47122c6400060870240806007e081010"
        "207e004402437e440202007e4610437e7e4400514044004b4043004400430049"
        "4043004400450045407e4600447f4a00447f4466007f3d4400003f7f4460007f"
        "3f44004401447f7e7f007e7400f7")

    def test_une_vraie_trame_de_la_machine(self):
        """Des octets venus de la machine, pas de notre codeur : un portage
        fautif et un vecteur qu'il aurait produit seraient d'accord."""
        from delugeapp.core import delugesysex as sx

        brut = bytes.fromhex(self.TRAME_MESUREE)
        self.assertEqual(len(brut), 110)
        trame = sx.parse(brut)
        self.assertIsInstance(trame, sx.OledFrame)
        ecran = sx.OledScreen()
        self.assertTrue(ecran.apply(trame))
        self.assertEqual(ecran.lit_count(), 207)
        allumes = [(x, y) for y in range(sx.OLED_HEIGHT)
                   for x in range(sx.OLED_WIDTH) if ecran.pixel(x, y)]
        self.assertEqual((min(x for x, _ in allumes), max(x for x, _ in allumes),
                          min(y for _, y in allumes), max(y for _, y in allumes)),
                         (49, 78, 9, 30))
        # Le haut du S de SYNTH, la barre du T de TB01.
        self.assertTrue(ecran.pixel(50, 9))
        self.assertFalse(ecran.pixel(49, 9))
        self.assertTrue(all(ecran.pixel(x, 22) for x in range(49, 57)))
        # Et notre codeur redonne exactement ce que la machine a envoyé.
        self.assertEqual(sx.pack_8to7_rle(trame.data), brut[9:-1])

    def test_la_vraie_reponse_d_identite(self):
        from delugeapp.core import delugesysex as sx

        reponse = bytes.fromhex("f07e7f0602 00217b01 000000 010201 00f7"
                                .replace(" ", ""))
        identite = sx.parse(reponse)
        self.assertEqual((identite.major, identite.minor, identite.patch),
                         (1, 2, 1))
        self.assertTrue(identite.community)
        self.assertEqual(identite.version, "c1.2.1")

    def test_une_difference_hors_ecran_est_refusee(self):
        from delugeapp.core import delugesysex as sx

        trop_loin = (b"\xf0\x00\x21\x7b\x01\x02\x40\x02\x60\x01"
                     + sx.pack_8to7_rle(bytes(8)) + b"\xf7")
        self.assertIsNone(sx.parse(trop_loin))


class TestControleursExacts(unittest.TestCase):
    """Contrôleur <-> paramètre, au cran près du firmware.

    ``ParamCollection::paramValueToKnobPos`` : ``(v + 2^24) >> 25`` ;
    ``MidiTakeover::calculateKnobPos`` : ``cc − 64``, et 127 vaut +64.
    """

    def test_envoyer_tombe_sur_le_cran_du_firmware(self):
        from delugeapp.core import midifollow

        # 0x3851EB64 : position 28 pour le firmware, donc 92. L'ancienne
        # règle de trois disait 91, un cran trop bas.
        self.assertEqual(midifollow.cc_value(0x3851EB64), 92)
        self.assertEqual(midifollow.cc_value(0), 64)
        self.assertEqual(midifollow.cc_value(INT32_MIN), 0)
        self.assertEqual(midifollow.cc_value(INT32_MAX), 127)
        self.assertEqual(midifollow.cc_value(0x7F000000), 127)

    def test_la_largeur_d_impulsion_est_a_demi_echelle(self):
        """``PatchedParamSet`` : ``(v >> 24) − 64`` pour la largeur
        d'impulsion des oscillateurs."""
        from delugeapp.core import midifollow

        self.assertEqual(midifollow.cc_value(0x40000000, "oscAPulseWidth"), 64)
        self.assertEqual(midifollow.raw_from_cc(64, "oscBPulseWidth"),
                         0x40000000)

    def test_lire_le_retour_de_la_machine(self):
        from delugeapp.core import midifollow

        self.assertEqual(midifollow.raw_from_cc(92), 28 << 25)
        self.assertEqual(midifollow.raw_from_cc(64), 0)
        self.assertEqual(midifollow.raw_from_cc(0), INT32_MIN)
        # La machine envoie position + 64 : 128 pour le maximum.
        self.assertEqual(midifollow.raw_from_cc(128), INT32_MAX)

    def test_un_aller_retour_ne_bouge_pas_d_un_cran(self):
        from delugeapp.core import midifollow

        for cc in range(0, 127):
            with self.subTest(cc=cc):
                self.assertEqual(
                    midifollow.cc_value(midifollow.raw_from_cc(cc)), cc)

    def test_la_carte_inverse(self):
        from delugeapp.core import midifollow

        inverse = midifollow.reverse_map({"lpfFrequency": 74, "pan": 10})
        self.assertEqual(inverse, {74: "lpfFrequency", 10: "pan"})


class _FauxWinmm:
    """Les fonctions d'entrée de ``winmm``, jouées par Python.

    Les en-têtes ``MIDIHDR`` sont les vrais objets ctypes du module : le
    faux pilote y écrit comme le vrai, puis appelle le vrai rappel.
    """

    def __init__(self):
        import ctypes
        import threading

        self.ctypes = ctypes
        self.verrou = threading.Lock()
        self.proc = None
        self.file: list = []
        self.appels: list[str] = []
        self.prepares: set[int] = set()
        self.ajouts_apres_reset = 0
        self.remis = False

    def midiInOpen(self, poignee, index, proc, inst, drapeaux):
        poignee._obj.value = 4242
        self.proc = proc
        self.appels.append("open")
        return 0

    def midiInPrepareHeader(self, _h, entete, taille):
        self.prepares.add(self.ctypes.addressof(entete._obj))
        return 0

    def midiInAddBuffer(self, _h, entete, taille):
        with self.verrou:
            if self.remis:
                self.ajouts_apres_reset += 1
            self.file.append(entete._obj)
            self.appels.append("add")
        return 0

    def midiInStart(self, _h):
        self.appels.append("start")
        return 0

    def midiInStop(self, _h):
        self.appels.append("stop")
        return 0

    def midiInReset(self, _h):
        self.appels.append("reset")
        with self.verrou:
            self.remis = True
            rendus, self.file = self.file, []
        for entete in rendus:
            entete.dwBytesRecorded = 0
            entete.dwFlags |= 1
            self.proc(4242, 0x3C4, None, self.ctypes.addressof(entete), 0)
        return 0

    def midiInUnprepareHeader(self, _h, entete, taille):
        with self.verrou:
            if any(e is entete._obj for e in self.file):
                return 65
        self.appels.append("unprepare")
        return 0

    def midiInClose(self, _h):
        self.appels.append("close")
        return 0

    # -- côté appareil ---------------------------------------------------- #

    def sysex(self, donnees: bytes, stamp: int = 0) -> None:
        reste = bytes(donnees)
        while reste:
            with self.verrou:
                entete = self.file.pop(0)
            morceau, reste = (reste[:entete.dwBufferLength],
                              reste[entete.dwBufferLength:])
            self.ctypes.memmove(entete.lpData, morceau, len(morceau))
            entete.dwBytesRecorded = len(morceau)
            entete.dwFlags |= 1
            self.proc(4242, 0x3C4, None, self.ctypes.addressof(entete), stamp)

    def court(self, status: int, d1: int, d2: int, stamp: int) -> None:
        self.proc(4242, 0x3C3, None, status | (d1 << 8) | (d2 << 16), stamp)


class _FauxSortie:
    """Les fonctions de sortie de ``winmm``, qui notent ce qui part."""

    def __init__(self):
        self.appels: list = []

    def midiOutOpen(self, poignee, index, rappel, instance, drapeaux):
        poignee._obj.value = 77
        self.appels.append("open")
        return 0

    def midiOutShortMsg(self, _h, message):
        self.appels.append((message & 0xFF, (message >> 8) & 0xFF,
                            (message >> 16) & 0xFF))
        return 0

    def midiOutReset(self, _h):
        self.appels.append("reset")
        return 0

    def midiOutClose(self, _h):
        self.appels.append("close")
        return 0


class TestFermetureDeSortie(unittest.TestCase):
    """Fermer un port n'envoie rien à la machine s'il n'a rien joué.

    Lu en relisant le code, le Deluge branché : chaque fermeture envoyait
    seize « All Notes Off » et un ``midiOutReset``, y compris sur le port des
    SysEx et pendant des essais censés ne rien envoyer.
    """

    def setUp(self):
        from delugeapp.core import midiport

        if midiport.ctypes is None:
            self.skipTest("ctypes de Windows absent")
        self.midiport = midiport
        self.faux = _FauxSortie()
        self._vrai = midiport._winmm
        midiport._winmm = self.faux
        self.port = midiport.MidiOut()
        self.assertTrue(self.port.open(
            midiport.MidiDevice(0, "MIDIOUT3 (Deluge)", "out")))

    def tearDown(self):
        self.midiport._winmm = self._vrai

    def test_un_port_qui_n_a_rien_joue_se_ferme_sans_rien_envoyer(self):
        self.port.realtime(self.midiport.CLOCK)   # message système : neutre
        self.port.close()
        self.assertEqual(self.faux.appels, ["open", (0xF8, 0, 0), "close"])

    def test_un_port_qui_a_joue_eteint_tout_en_partant(self):
        self.port.note_on(60, 100, channel=2)
        self.port.close()
        appels = self.faux.appels
        self.assertIn((0x81, 60, 0), appels)             # la note relâchée
        self.assertEqual(sum(1 for a in appels if isinstance(a, tuple)
                             and a[0] & 0xF0 == 0xB0 and a[1] == 123), 16)
        self.assertEqual(appels[-2:], ["reset", "close"])

    def test_rouvrir_remet_le_compte_a_zero(self):
        self.port.note_on(60)
        self.port.close()
        self.faux.appels.clear()
        self.assertTrue(self.port.open(
            self.midiport.MidiDevice(0, "Deluge", "out")))
        self.port.close()
        self.assertEqual(self.faux.appels, ["open", "close"])


class TestEntreeSysex(unittest.TestCase):
    """La réception des SysEx, sur un faux pilote mais avec les vrais
    tampons, le vrai rappel et le vrai fil de recyclage."""

    def setUp(self):
        from delugeapp.core import midiport

        if midiport.ctypes is None:
            self.skipTest("ctypes de Windows absent")
        self.midiport = midiport
        self.faux = _FauxWinmm()
        self._vrai = midiport._winmm
        midiport._winmm = self.faux

    def tearDown(self):
        self.midiport._winmm = self._vrai

    def _ouvrir(self):
        entree = self.midiport.MidiIn()
        self.assertTrue(entree.open(self.midiport.MidiDevice(0, "Deluge",
                                                             "in")))
        self.assertEqual(len(self.faux.file),
                         self.midiport.SYSEX_BUFFERS)
        return entree

    def _attendre_tampons(self, nombre):
        for _ in range(200):
            with self.faux.verrou:
                if len(self.faux.file) >= nombre:
                    return True
            time.sleep(0.005)
        return False

    def test_un_sysex_sur_deux_tampons_est_recolle(self):
        entree = self._ouvrir()
        try:
            long = bytes([0xF0]) + bytes(range(1, 128)) * 40 + b"\xf7"
            self.assertGreater(len(long), self.midiport.SYSEX_BUFFER_SIZE)
            self.faux.sysex(long, stamp=77)
            recus = entree.poll()
            self.assertEqual(len(recus), 1)
            self.assertTrue(recus[0].is_sysex)
            self.assertEqual(recus[0].data, long)
            self.assertEqual(recus[0].stamp, 77)
            # Les deux tampons sont revenus au pilote, par le fil de
            # recyclage et non par le rappel.
            self.assertTrue(self._attendre_tampons(
                self.midiport.SYSEX_BUFFERS))
        finally:
            entree.close()

    def test_les_messages_courts_gardent_l_horodatage_du_pilote(self):
        entree = self._ouvrir()
        try:
            self.faux.court(0xF8, 0, 0, stamp=1234)
            self.faux.court(0xB0, 74, 128, stamp=1240)
            recus = entree.poll()
            self.assertEqual([(m.status, m.stamp) for m in recus],
                             [(0xF8, 1234), (0xB0, 1240)])
            # 128 n'est pas un octet MIDI, mais c'est ce que la machine
            # envoie pour un bouton au maximum : on le garde.
            self.assertEqual(recus[1].data2, 128)
        finally:
            entree.close()

    def test_fermer_rend_tout_dans_l_ordre(self):
        """Arrêt, reset (le pilote rend les tampons), **aucun** tampon
        rendu au pilote après le reset, libération, fermeture."""
        entree = self._ouvrir()
        entree.close()
        appels = [a for a in self.faux.appels if a != "add"]
        self.assertEqual(appels[:4], ["open", "start", "stop", "reset"])
        self.assertEqual(appels[-1], "close")
        self.assertEqual(appels.count("unprepare"),
                         self.midiport.SYSEX_BUFFERS)
        self.assertEqual(self.faux.ajouts_apres_reset, 0)
        self.assertFalse(entree.is_open)

    def test_rouvrir_ne_bloque_pas(self):
        """``open`` ferme d'abord, **hors** du verrou que le fil de
        recyclage attend : rouvrir prenait deux secondes d'attente."""
        entree = self._ouvrir()
        try:
            self.faux.sysex(b"\xf0\x01\xf7")
            debut = time.monotonic()
            self.faux.file.clear()
            self.assertTrue(entree.open(self.midiport.MidiDevice(
                0, "Deluge", "in")))
            self.assertLess(time.monotonic() - debut, 1.0)
        finally:
            entree.close()


def _deluge_simule():
    """Le module ``tests/deluge_simule.py``, quelle que soit la façon dont la
    suite est lancée (``discover -s tests`` ou ``tests.test_core``)."""
    import sys

    dossier = str(Path(__file__).resolve().parent)
    if dossier not in sys.path:
        sys.path.insert(0, dossier)
    import deluge_simule

    return deluge_simule


class TestLiaisonVivante(unittest.TestCase):
    """La liaison complète, face au Deluge simulé (``tests/deluge_simule.py``)."""

    def setUp(self):
        from delugeapp.core import midiport
        from delugeapp.core.delugelink import DelugeLink

        DelugeSimule = _deluge_simule().DelugeSimule

        self.midiport = midiport
        self.machine = DelugeSimule()
        self._sauves = (midiport.outputs, midiport.inputs,
                        midiport.available)
        midiport.outputs = lambda: self.machine.devices("out")
        midiport.inputs = lambda: self.machine.devices("in")
        midiport.available = lambda: True
        self.lien = DelugeLink()
        self.machine.brancher(self.lien)

    def tearDown(self):
        (self.midiport.outputs, self.midiport.inputs,
         self.midiport.available) = self._sauves

    def test_les_notes_passent_par_le_premier_port_et_les_sysex_par_le_troisieme(self):
        self.assertTrue(self.lien.connect())
        etat = self.lien.state()
        self.assertEqual(etat.out_name, "Deluge")
        self.assertEqual(etat.in_name, "Deluge")
        self.assertEqual(etat.sysex_name, "MIDIOUT3 (Deluge)")
        self.lien.wait_files(3.0)
        # Rien que des demandes de lecture : identité, ping, et la sonde des
        # fichiers par USB (que la 1.2.1 ignore).
        from delugeapp.core import delugesysex as sx

        sonde = bytes((0xF0,)) + sx.DELUGE_ID + bytes((0x04,))
        envoyes = [e[1] for e in self.machine.sorties[3].envoyes]
        self.assertEqual(envoyes[0], sx.identity_request())
        self.assertEqual(envoyes[1][:6], bytes((0xF0,)) + sx.DELUGE_ID
                         + bytes((sx.CMD_PING,)))
        self.assertEqual([e[:6] for e in envoyes[2:]], [sonde])
        self.assertIn(b'{"ping":{}}', envoyes[2])
        self.assertEqual(self.machine.sorties[1].envoyes, [])

    def test_la_machine_dit_sa_version_et_l_aller_retour_se_mesure(self):
        self.assertTrue(self.lien.connect())
        evenements = self.lien.service()
        self.assertIn("identity", evenements)
        self.assertIn("ping", evenements)
        etat = self.lien.state()
        self.assertEqual(etat.firmware, "c1.2.1")
        self.assertTrue(etat.verified)
        self.assertIsNotNone(etat.latency_ms)
        self.assertIn("Deluge c1.2.1", etat.summary())

    def test_l_aller_retour_se_compte_a_l_arrivee_pas_au_service(self):
        """La machine répond en 2 à 3 ms, le service ne passe que toutes les
        40 ms : compté au service, l'aller-retour affichait 41 ms
        (mesuré sur la machine)."""
        self.assertTrue(self.lien.connect())
        self.lien.service()
        self.assertTrue(self.lien.ping())
        time.sleep(0.08)
        self.assertIn("ping", self.lien.service())
        self.assertLess(self.lien.latency_ms, 40.0)

    def test_un_aller_retour_sous_la_milliseconde_ne_s_affiche_pas_zero(self):
        """Mesuré : 0,3 ms en USB. Arrondi à l'unité, c'était « 0 ms »."""
        from delugeapp.core.delugelink import latency_text

        self.assertEqual(latency_text(0.33), "0,3 ms")
        self.assertEqual(latency_text(2.54), "2,5 ms")
        self.assertEqual(latency_text(41.2), "41 ms")
        self.assertEqual(latency_text(-1), "0,0 ms")
        # Vu face à la machine, interface en anglais : « 1,7 ms ».
        from delugeapp import i18n

        i18n.set_language("en")
        self.addCleanup(i18n.set_language, "fr")
        self.assertEqual(latency_text(1.74), "1.7 ms")

    def test_sans_troisieme_port_les_sysex_passent_par_le_premier(self):
        self.machine = _deluge_simule().DelugeSimule(cables=1)
        self.machine.brancher(self.lien)
        self.assertTrue(self.lien.connect())
        self.assertEqual(self.lien.state().sysex_name, "Deluge")
        self.lien.service()
        self.assertEqual(self.lien.state().firmware, "c1.2.1")

    def test_une_machine_muette_est_redemandee_trois_fois(self):
        self.machine.muette = True
        self.assertTrue(self.lien.connect())
        for _ in range(4):
            self.lien._ident_sent -= 3.0
            self.lien.service()
        identites = [d for d in self.machine.demandes
                     if d == bytes((0xF0, 0x7E, 0x7F, 0x06, 0x01, 0xF7))]
        self.assertEqual(len(identites), 3)
        self.assertEqual(self.lien.state().firmware, "")

    def test_l_ecran_se_recopie_et_s_entretient(self):
        from delugeapp.core import delugesysex as sx

        self.assertTrue(self.lien.connect())
        self.lien.service()
        self.machine.ecran[0] = 0xFF
        self.assertTrue(self.lien.set_screen(True))
        # Comme la vraie machine : une différence pleine page, pas d'image.
        reponse = sx.parse(self.machine.entrees[3].recus[-1].data)
        self.assertIsInstance(reponse, sx.OledDelta)
        self.assertEqual((reponse.start, len(reponse.data)),
                         (0, sx.OLED_BYTES))
        self.assertIn("screen", self.lien.service())
        self.assertTrue(self.lien.screen.complete)
        self.assertEqual(self.lien.screen.lit_count(), 8)
        self.machine.dessine(3, bytes([0x0F] * 8))
        self.assertIn("screen", self.lien.service())
        self.assertEqual(self.lien.screen.lit_count(), 8 + 32)
        # L'abonnement dure deux secondes : il est renouvelé avant.
        avant = len(self.machine.demandes)
        self.lien._screen_sent -= 1.5
        self.lien.service()
        self.assertEqual(len(self.machine.demandes), avant + 1)
        self.assertEqual(self.machine.demandes[-1][-2], 2)
        self.lien.set_screen(False)
        self.lien._screen_sent -= 5
        self.lien.service()
        self.assertEqual(len(self.machine.demandes), avant + 1)

    def test_le_tempo_et_la_lecture_de_la_machine(self):
        self.assertTrue(self.lien.connect())
        self.machine.court(self.midiport.START)
        self.machine.horloge(124.0)
        evenements = self.lien.service()
        self.assertIn("transport", evenements)
        self.assertIn("tempo", evenements)
        self.assertTrue(self.lien.running)
        self.assertAlmostEqual(self.lien.tempo, 124.0, delta=0.3)
        self.machine.court(self.midiport.STOP)
        self.lien.service()
        self.assertFalse(self.lien.running)

    def test_une_horloge_qui_se_tait_arrete_la_lecture(self):
        self.assertTrue(self.lien.connect())
        self.machine.court(self.midiport.START)
        self.machine.horloge(120.0)
        self.lien.service()
        self.lien._tick_seen -= 5.0
        self.assertIn("transport", self.lien.service())
        self.assertFalse(self.lien.running)
        self.assertAlmostEqual(self.lien.tempo, 120.0, delta=0.3)

    def test_le_retour_midi_follow_donne_le_son_selectionne(self):
        self.assertTrue(self.lien.connect())
        self.lien.set_channel(1)
        cc = self.lien.follow_map["lpfFrequency"]
        self.machine.court(0xB0, cc, 92)
        self.machine.court(0xB1, cc, 10)       # un autre canal : ignoré
        self.assertIn("params", self.lien.service())
        self.assertEqual(self.lien.machine["lpfFrequency"], 28 << 25)
        self.assertEqual(self.lien.state().feedback, 1)

    # -- l'écoute d'un son, selon le réglage Takeover de la machine ---------- #

    #: Mesuré le 22 octobre 2026 sur la piste « Accords » d'ESSAI ACCORDS
    #: (retour MIDI Follow), puis ce qu'« Écouter » y envoyait pour Echo
    #: Chord. La machine, en Pickup, n'en a appliqué aucun.
    DEPART = {"volume": 84, "pan": 64, "lpfFrequency": 92,
              "lpfResonance": 84}
    VOULU = {"volume": 122, "pan": 100, "lpfFrequency": 53,
             "lpfResonance": 22}

    def _ecoute(self, mode, retour=False, joue=False, salve=None):
        """Envoie le son voulu à une machine réglée en ``mode`` ; rend les
        positions obtenues et, par réglage, les valeurs parties."""
        from delugeapp.core import midifollow
        from delugeapp.core.model import Sound

        self.machine.salve = salve
        self.assertTrue(self.lien.connect())
        self.lien.set_channel(1)
        carte = self.lien.follow_map
        son = Sound()
        for cle, cc in self.VOULU.items():
            son.set_param(cle, midifollow.raw_from_cc(cc, cle))
        boutons = self.machine.boutons
        boutons.mode = mode
        boutons.position = {carte[c]: v - 64 for c, v in self.DEPART.items()}
        if retour:
            self.machine.retour_midi_follow()
        if joue:
            self.machine.court(self.midiport.START)
        self.lien.service()
        sortie = self.machine.sorties[1]
        sortie.envoyes.clear()
        self.assertEqual(self.lien.send_sound(son, keys=list(self.VOULU)),
                         len(self.VOULU))
        obtenu = {c: boutons.valeur(carte[c]) for c in self.VOULU}
        envois = {c: [e[2] for e in sortie.envoyes
                      if e[0] == "cc" and e[1] == carte[c]]
                  for c in self.VOULU}
        return obtenu, envois

    def test_en_pickup_un_saut_d_un_coup_est_ignore(self):
        """Ce que la machine a fait le 22 octobre, et que le Deluge simulé
        doit refaire : la règle du firmware, pas celle de l'application."""
        boutons = _deluge_simule().Boutons("pickup")
        boutons.position = {7: 84 - 64}
        boutons.recoit(7, 122)
        self.assertEqual(boutons.valeur(7), 84)
        boutons.recoit(7, 122)
        self.assertEqual(boutons.valeur(7), 84, "toujours pas rattrapé")

    def test_l_ecoute_s_applique_dans_les_trois_modes(self):
        from delugeapp.core.delugelink import DelugeLink

        for mode in ("jump", "pickup", "scale"):
            for retour in (False, True):
                with self.subTest(mode=mode, retour=retour):
                    # Une machine et un lien neufs ; les ports simulés du
                    # ``setUp`` les trouvent par ``self.machine``.
                    self.machine = _deluge_simule().DelugeSimule()
                    self.lien = DelugeLink()
                    self.machine.brancher(self.lien)
                    obtenu, _envois = self._ecoute(mode, retour=retour)
                    self.assertEqual(obtenu, self.VOULU)
                    self.lien.disconnect()

    def test_sans_retour_le_bouton_est_franchi_aux_deux_extremes(self):
        _obtenu, envois = self._ecoute("pickup")
        for cle, cc in self.VOULU.items():
            self.assertEqual(envois[cle], [0, 127, cc])

    def test_avec_le_retour_la_position_actuelle_part_d_abord(self):
        """Le retour MIDI Follow dit où est chaque bouton : on part de là,
        sans passer par les extrêmes, et on retient la nouvelle valeur — la
        machine ne renvoie pas ce qu'elle reçoit."""
        from delugeapp.core import midifollow

        _obtenu, envois = self._ecoute("pickup", retour=True)
        for cle, cc in self.VOULU.items():
            self.assertEqual(envois[cle], [self.DEPART[cle], cc])
            self.assertEqual(
                midifollow.cc_value(self.lien.machine[cle], cle), cc)

    def test_une_salve_trop_rapide_est_perdue(self):
        """Mesuré le 22 octobre 2026, écran recopié et « Display Param »
        allumé : d'une salve de 135 contrôleurs en 0,2 s, la machine n'a
        appliqué que les trois premiers. Le Deluge simulé fait de même."""
        self.machine.salve = 3
        self.assertTrue(self.lien.connect())
        self.lien.service()
        cc = self.lien.follow_map["volume"]
        self.machine.boutons.position = {cc: 0}
        self.machine.en_attente = 0
        for valeur in (10, 20, 30, 40, 50):
            self.lien._out.control_change(cc, valeur, 1)
        self.assertEqual(self.machine.boutons.valeur(cc), 30)
        self.assertEqual(self.machine.cc_perdus, 2)

    def test_l_ecoute_attend_la_machine_entre_deux_reglages(self):
        """Un ping entre deux réglages, et le suivant ne part qu'à son
        retour : sur la machine, les 45 réglages d'Echo Chord sont alors
        tous passés (0,8 s), au lieu d'un seul."""
        from delugeapp.core import delugesysex as sx

        obtenu, _envois = self._ecoute("pickup", salve=3)
        self.assertEqual(obtenu, self.VOULU)
        self.assertEqual(self.machine.cc_perdus, 0)
        # Par le port des contrôleurs, pas par celui des SysEx : deux ports
        # sont deux files, et un pong venu par l'autre les a doublés.
        pings = [e[1] for e in self.machine.sorties[1].envoyes
                 if e[0] == "sysex" and e[1][5] == sx.CMD_PING
                 and e[1][6] >= 0x40]
        # Un entre deux réglages, et un avant la note.
        self.assertEqual(len(pings), len(self.VOULU))
        self.assertFalse([e for e in self.machine.sorties[3].envoyes
                          if e[0] == "sysex" and e[1][5] == sx.CMD_PING
                          and e[1][6] >= 0x40])

    def test_la_recopie_de_l_ecran_se_tait_pendant_l_envoi(self):
        """Mesuré : la machine perd des contrôleurs pendant qu'elle envoie
        son écran. L'envoi attend que l'abonnement expire chez elle, et ne
        le renouvelle pas avant d'avoir fini."""
        from unittest import mock

        from delugeapp.core import delugesysex as sx
        from delugeapp.core import midifollow
        from delugeapp.core.model import Sound

        self.assertTrue(self.lien.connect())
        self.lien.service()
        self.assertTrue(self.lien.set_screen(True))
        son = Sound()
        son.set_param("volume", midifollow.raw_from_cc(100, "volume"))
        with mock.patch.object(sx, "STREAM_SECONDS", 0.3):
            fin_abonnement = self.lien._screen_sent + 0.3
            self.assertEqual(self.lien.send_sound(son, keys=["volume"]), 1)
            self.assertGreaterEqual(time.monotonic(), fin_abonnement)
        # Retenue, la recopie ne se renouvelle pas ; relâchée, elle reprend.
        demandes = len(self.machine.demandes)
        self.lien._screen_hold += 1          # un envoi en cours
        self.lien._screen_sent -= 5
        self.lien.service()
        self.assertEqual(len(self.machine.demandes), demandes)
        self.lien._release_screen()
        self.lien.service()
        self.assertEqual(len(self.machine.demandes), demandes + 1)

    def test_sans_cadence_la_salve_se_perd(self):
        """Le même envoi, pong jamais attendu : la machine en perd."""
        from unittest import mock

        with mock.patch.object(type(self.lien), "_sync_point",
                               lambda self, timeout=0: True):
            obtenu, _envois = self._ecoute("pickup", salve=3)
        self.assertNotEqual(obtenu, self.VOULU)
        self.assertGreater(self.machine.cc_perdus, 0)

    def test_machine_qui_joue_sans_retour_la_valeur_part_seule(self):
        """Les extrêmes s'entendraient : la valeur part seule. En Pickup, la
        machine l'ignore alors — limite dite dans le manuel."""
        obtenu, envois = self._ecoute("pickup", joue=True)
        self.assertTrue(self.lien.running)
        for cle, cc in self.VOULU.items():
            self.assertEqual(envois[cle], [cc])
        self.assertEqual(obtenu, self.DEPART)
        self.assertNotIn("volume", self.lien.machine)

    def test_les_notes_tenues_sur_la_machine(self):
        self.assertTrue(self.lien.connect())
        for note in (60, 64, 67):
            self.machine.court(0x90, note, 100)
        self.machine.court(0x80, 64, 0)
        self.assertIn("notes", self.lien.service())
        self.assertEqual(self.lien.held, {60, 67})

    def test_un_port_occupe_se_dit_en_clair(self):
        self.machine.refuse_cable = 1
        self.assertFalse(self.lien.connect())
        resume = self.lien.state().summary()
        self.assertIn("déjà utilisé par une autre application", resume)

    def test_deconnecter_oublie_ce_que_la_machine_a_dit(self):
        self.assertTrue(self.lien.connect())
        self.lien.service()
        self.lien.disconnect()
        etat = self.lien.state()
        self.assertEqual((etat.firmware, etat.latency_ms, etat.out_name),
                         ("", None, ""))

    def test_le_tempo_d_une_horloge(self):
        from delugeapp.core.delugelink import tempo_from_ticks

        ecart = 60000.0 / (120 * 24)
        self.assertAlmostEqual(tempo_from_ticks(
            [i * ecart for i in range(25)]), 120.0, places=6)
        self.assertIsNone(tempo_from_ticks([0, 10]))
        self.assertIsNone(tempo_from_ticks([5, 5, 5]))


# --------------------------------------------------------------------------- #
# La carte restée dans le Deluge : copie de travail et synchronisation
# --------------------------------------------------------------------------- #

def _empreinte_dossier(racine: Path) -> str:
    """Empreinte d'un dossier entier : noms, tailles, dates et contenus."""
    h = hashlib.sha256()
    for p in sorted(Path(racine).rglob("*")):
        if p.is_file():
            st = p.stat()
            h.update(p.relative_to(racine).as_posix().encode())
            h.update(str((st.st_size, st.st_mtime_ns)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


class TestSynchroCarte(unittest.TestCase):
    """``core/cardsync.py`` face à une carte simulée par un dossier.

    La sauvegarde de l'utilisateur sert de point de départ et n'est jamais
    modifiée ; la carte fait foi la première fois ; ce qui change des deux
    côtés garde ses deux versions ; une suppression ne passe pas sans accord.
    """

    def setUp(self):
        from delugeapp.core import cardsync

        self.cs = cardsync
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.carte = base / "carte"
        self.sauvegarde = base / "sauvegarde"
        self.travail = base / "travail"
        self.travail.mkdir()
        # La carte, dans le Deluge.
        self._ecrit(self.carte, "SONGS/A.XML", b"<song a/>", 1_700_000_000)
        self._ecrit(self.carte, "SONGS/B.XML", b"<song b/>", 1_700_000_100)
        self._ecrit(self.carte, "SYNTHS/P.XML", b"<sound p/>", 1_700_000_200)
        self._ecrit(self.carte, "SAMPLES/K.WAV", bytes(range(256)) * 4,
                    1_700_000_300)
        # Enregistré par le Deluge : date nulle.
        self._ecrit(self.carte, "SONGS/NEUF.XML", b"<song neuf/>", None)
        # La sauvegarde : une copie faite sur un Mac — deux heures d'écart
        # partout —, une version ancienne de B, et une corbeille.
        for rel in ("SONGS/A.XML", "SYNTHS/P.XML", "SAMPLES/K.WAV"):
            self._copie_decalee(rel, -7200)
        self._ecrit(self.sauvegarde, "SONGS/B.XML", b"<song b ancien/>",
                    1_600_000_000)
        self._ecrit(self.sauvegarde, ".Trashes/501/X.WAV", b"poubelle", 1)
        self._ecrit(self.sauvegarde, "SONGS/._A.XML", b"mac", 1)

    def tearDown(self):
        self._tmp.cleanup()

    @staticmethod
    def _ecrit(racine, rel, donnees, mtime):
        p = Path(racine) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(donnees)
        if mtime is None:
            # La date nulle de FAT : 1er janvier 1980, heure locale.
            from delugeapp.core.delugefiles import from_fat
            mtime = from_fat(0x21, 0)
        os.utime(p, (mtime, mtime))

    def _copie_decalee(self, rel, decalage):
        source = self.carte / rel
        st = source.stat()
        self._ecrit(self.sauvegarde, rel, source.read_bytes(),
                    st.st_mtime + decalage)

    def _synchronise(self, **options):
        transport = self.cs.FolderCard(self.carte)
        manifeste = self.cs.load_manifest(self.travail)
        plan = self.cs.plan_sync(transport.walk(),
                                 self.cs.scan_local(self.travail), manifeste,
                                 backup=options.pop("backup", None))
        resultat = self.cs.apply_plan(plan, transport, self.travail,
                                      manifeste, **options)
        return plan, resultat

    def _fichiers(self, racine):
        return {p.relative_to(racine).as_posix(): p.read_bytes()
                for p in Path(racine).rglob("*") if p.is_file()
                and self.cs.META_DIR not in p.parts}

    # -- ce qui ne voyage pas ----------------------------------------------- #

    def test_corbeilles_index_et_parasites_ne_voyagent_pas(self):
        for rel in (".Trashes/501/X.WAV", ".Trash-59016/files/A.XML",
                    ".Spotlight-V100/Store-V2/x", "System Volume Information/y",
                    "SONGS/._A.XML", "SYNTHS/.DS_Store", "SONGS/~DC1A2B.TMP",
                    ".noctiluca/synchro.json",
                    ".deluge-companion/synchro.json",
                    "SYNTHS/P.XML.2026-10-18_12h00.bak",
                    "_BACKUP/SAMPLES/x.wav"):
            self.assertTrue(self.cs.is_junk(rel), rel)
        for rel in ("SONGS/A.XML", "SAMPLES/DRUMS/Kick/k.wav",
                    "SETTINGS/MIDIFollow.XML", "SONGS/~ma chanson.XML"):
            self.assertFalse(self.cs.is_junk(rel), rel)

    # -- la première fois ---------------------------------------------------- #

    def test_la_premiere_fois_part_de_la_sauvegarde_sans_la_toucher(self):
        avant = _empreinte_dossier(self.sauvegarde)
        plan, resultat = self._synchronise(backup=self.sauvegarde)
        c = plan.counts()
        # A, P et K : même taille, deux heures d'écart -> repris localement.
        self.assertEqual(c["copy_backup"], 3, plan.actions)
        # B diffère, NEUF est absent de la sauvegarde -> par le câble.
        self.assertEqual(sorted(a.rel for a in plan.of("pull")),
                         ["SONGS/B.XML", "SONGS/NEUF.XML"])
        self.assertTrue(resultat.ok, resultat.errors)
        self.assertEqual(self._fichiers(self.travail),
                         self._fichiers(self.carte))
        self.assertEqual(_empreinte_dossier(self.sauvegarde), avant)

    def test_un_fichier_du_deluge_recoit_une_date_pour_la_suite(self):
        self._synchronise(backup=self.sauvegarde)
        transport = self.cs.FolderCard(self.carte)
        neuf = transport.walk()["SONGS/NEUF.XML"]
        self.assertNotEqual(neuf.date, 0)
        # Rien n'a changé depuis : plus rien à faire.
        plan, _ = self._synchronise()
        self.assertTrue(plan.empty, plan.summary())

    # -- ensuite ------------------------------------------------------------- #

    def test_ce_que_le_deluge_reecrit_descend(self):
        self._synchronise(backup=self.sauvegarde)
        # Le Deluge réenregistre A : même taille, date nulle.
        self._ecrit(self.carte, "SONGS/A.XML", b"<song A/>", None)
        plan, resultat = self._synchronise()
        self.assertEqual([a.rel for a in plan.of("pull")], ["SONGS/A.XML"])
        self.assertTrue(resultat.ok)
        self.assertEqual((self.travail / "SONGS/A.XML").read_bytes(),
                         b"<song A/>")
        self.assertTrue(self._synchronise()[0].empty)

    def test_ce_que_l_application_cree_ou_modifie_monte(self):
        self._synchronise(backup=self.sauvegarde)
        self._ecrit(self.travail, "SONGS/CREE.XML", b"<song cree/>",
                    time.time())
        self._ecrit(self.travail, "SYNTHS/P.XML", b"<sound p modifie/>",
                    time.time() + 10)
        plan, resultat = self._synchronise()
        self.assertEqual(sorted(a.rel for a in plan.of("push")),
                         ["SONGS/CREE.XML", "SYNTHS/P.XML"])
        self.assertTrue(resultat.ok, resultat.errors)
        self.assertEqual((self.carte / "SONGS/CREE.XML").read_bytes(),
                         b"<song cree/>")
        self.assertEqual((self.carte / "SYNTHS/P.XML").read_bytes(),
                         b"<sound p modifie/>")
        self.assertTrue(self._synchronise()[0].empty)

    def test_change_des_deux_cotes_les_deux_versions_restent(self):
        self._synchronise(backup=self.sauvegarde)
        self._ecrit(self.carte, "SONGS/B.XML", b"<song b deluge/>", None)
        self._ecrit(self.travail, "SONGS/B.XML", b"<song b pc/>",
                    time.time() + 20)
        plan, resultat = self._synchronise()
        self.assertEqual([a.rel for a in plan.of("conflict")], ["SONGS/B.XML"])
        self.assertTrue(resultat.ok, resultat.errors)
        self.assertEqual(resultat.renamed, [("SONGS/B.XML",
                                             "SONGS/B (PC).XML")])
        for racine in (self.carte, self.travail):
            self.assertEqual((racine / "SONGS/B.XML").read_bytes(),
                             b"<song b deluge/>")
            self.assertEqual((racine / "SONGS/B (PC).XML").read_bytes(),
                             b"<song b pc/>")
        self.assertTrue(self._synchronise()[0].empty)

    def test_supprime_sur_le_pc_rien_ne_part_sans_accord(self):
        self._synchronise(backup=self.sauvegarde)
        (self.travail / "SONGS/A.XML").unlink()
        plan, resultat = self._synchronise()
        self.assertEqual([a.rel for a in plan.needs_consent], ["SONGS/A.XML"])
        self.assertTrue((self.carte / "SONGS/A.XML").exists())
        self.assertEqual(resultat.done["delete_card"], 0)
        plan, resultat = self._synchronise(allow_card_deletes=True)
        self.assertFalse((self.carte / "SONGS/A.XML").exists())
        self.assertEqual(resultat.done["delete_card"], 1)

    def test_supprime_sur_le_deluge_va_dans_l_historique(self):
        self._synchronise(backup=self.sauvegarde)
        (self.carte / "SONGS/A.XML").unlink()
        plan, resultat = self._synchronise()
        self.assertEqual([a.rel for a in plan.of("delete_local")],
                         ["SONGS/A.XML"])
        self.assertFalse((self.travail / "SONGS/A.XML").exists())
        historique = list((self.travail / self.cs.HISTORY)
                          .rglob("A.XML"))
        self.assertEqual([p.read_bytes() for p in historique], [b"<song a/>"])

    def test_la_sauvegarde_seule_est_proposee_jamais_reprise_d_office(self):
        self._ecrit(self.sauvegarde, "KITS/COMPAGNON 1.XML", b"<kit/>", 1)
        self._ecrit(self.sauvegarde, "README.txt", b"ancien", 1)
        plan, _ = self._synchronise(backup=self.sauvegarde)
        self.assertEqual([r for r, _ in plan.backup_only],
                         ["KITS/COMPAGNON 1.XML", "README.txt"])
        self.assertEqual([r for r, _ in plan.backup_music()],
                         ["KITS/COMPAGNON 1.XML"])
        self.assertFalse((self.travail / "KITS/COMPAGNON 1.XML").exists())
        # Repris sur demande : il part au Deluge à la synchronisation.
        self.assertEqual(self.cs.take_from_backup(
            self.sauvegarde, self.travail, ["KITS/COMPAGNON 1.XML"]), 1)
        plan, resultat = self._synchronise()
        self.assertEqual([a.rel for a in plan.of("push")],
                         ["KITS/COMPAGNON 1.XML"])
        self.assertEqual((self.carte / "KITS/COMPAGNON 1.XML").read_bytes(),
                         b"<kit/>")

    def test_une_carte_simulee_n_ecrase_jamais_un_fichier_neuf(self):
        from delugeapp.core.delugefiles import FileError

        transport = self.cs.FolderCard(self.carte)
        with self.assertRaises(FileError):
            transport.write_new("SONGS/A.XML", b"x", time.time())
        self.assertEqual((self.carte / "SONGS/A.XML").read_bytes(),
                         b"<song a/>")

    def test_disparu_des_deux_cotes_le_manifeste_l_oublie(self):
        self._synchronise(backup=self.sauvegarde)
        (self.carte / "SONGS/A.XML").unlink()
        (self.travail / "SONGS/A.XML").unlink()
        plan, _ = self._synchronise()
        self.assertEqual(plan.forget, ["SONGS/A.XML"])
        self.assertNotIn("SONGS/A.XML", self.cs.load_manifest(self.travail))


class TestFichiersParUsb(unittest.TestCase):
    """Les fichiers de la carte par le câble USB (firmware 1.3), à travers le
    vrai lien MIDI et le Deluge simulé, qui sert ses fichiers comme
    ``storage/smsysex.cpp`` — dangers compris."""

    def setUp(self):
        from delugeapp.core import midiport

        self.midiport = midiport
        self._tmp = tempfile.TemporaryDirectory()
        self.racine = Path(self._tmp.name) / "carte"
        (self.racine / "SONGS").mkdir(parents=True)
        (self.racine / "SONGS" / "A.XML").write_bytes(b"<song a/>")
        self._sauves = (midiport.outputs, midiport.inputs,
                        midiport.available)
        self.machine = None
        self.lien = None

    def tearDown(self):
        if self.lien is not None:
            self.lien.disconnect()
        (self.midiport.outputs, self.midiport.inputs,
         self.midiport.available) = self._sauves
        self._tmp.cleanup()

    def _branche(self, version=(1, 3, 0)):
        from delugeapp.core.delugelink import DelugeLink

        self.machine = _deluge_simule().DelugeSimule(version=version,
                                                     carte=self.racine)
        self.midiport.outputs = lambda: self.machine.devices("out")
        self.midiport.inputs = lambda: self.machine.devices("in")
        self.midiport.available = lambda: True
        self.lien = DelugeLink()
        self.machine.brancher(self.lien)
        self.assertTrue(self.lien.connect())
        self.lien.wait_files(5.0)
        return self.lien.files

    def _commandes(self, nom=None):
        return [c for c in self.machine.carte_usb.commandes
                if nom is None or c[0] == nom]

    # -- savoir si la machine le fait ----------------------------------------- #

    def test_la_1_2_1_ne_donne_pas_ses_fichiers_et_rien_ne_part(self):
        files = self._branche(version=(1, 2, 1))
        self.assertFalse(files.supported)
        self.assertFalse(self.lien.state().files)
        self.assertEqual(self._commandes(), [])

    def test_la_1_3_les_donne_et_reserve_ses_numeros(self):
        files = self._branche()
        self.assertTrue(files.supported)
        self.assertTrue(self.lien.state().files)
        self.assertIn("files", self.lien.service())
        self.assertEqual(files._ids, list(range(9, 16)))

    # -- lire ---------------------------------------------------------------- #

    def test_un_dossier_de_plus_de_vingt_cinq_entrees(self):
        for i in range(60):
            (self.racine / "SONGS" / ("S%02d.XML" % i)).write_bytes(b"x" * i)
        files = self._branche()
        noms = {e.name for e in files.listdir("/SONGS")}
        self.assertEqual(len(noms), 61)
        self.assertGreaterEqual(len(self._commandes("dir")), 3)

    def test_lire_toutes_les_tailles_a_l_octet_pres(self):
        import random

        hasard = random.Random(7)
        tailles = (0, 1, 7, 1023, 1024, 1025, 5000)
        for n in tailles:
            (self.racine / ("F%d.BIN" % n)).write_bytes(
                bytes(hasard.randrange(256) for _ in range(n)))
        files = self._branche()
        for n in tailles:
            self.assertEqual(files.read("/F%d.BIN" % n),
                             (self.racine / ("F%d.BIN" % n)).read_bytes(), n)

    # -- écrire sans jamais écraser -------------------------------------------- #

    def test_un_fichier_neuf_passe_par_un_nom_temporaire(self):
        files = self._branche()
        donnees = bytes(range(256)) * 9
        files.write_new("/SONGS/NOUVEAU.XML", donnees, mtime=1_700_000_000)
        self.assertEqual((self.racine / "SONGS/NOUVEAU.XML").read_bytes(),
                         donnees)
        ouvertures = [a for n, a in self._commandes("open") if a.get("write")]
        self.assertTrue(ouvertures)
        self.assertTrue(all("/~DC" in a["path"] for a in ouvertures),
                        ouvertures)
        self.assertEqual(sorted(p.name for p in (self.racine / "SONGS")
                                .iterdir()), ["A.XML", "NOUVEAU.XML"])

    def test_aucun_message_ne_depasse_ce_que_la_machine_recoit(self):
        """Mesuré : un bloc de 1 024 octets codé en faisait 1 230, et la
        machine l'abandonnait sans répondre (``incomingSysexBuffer[1024]``)."""
        files = self._branche()
        files.write_new("/GROS.BIN", bytes(range(256)) * 40)      # 10 Ko
        self.assertEqual(self.machine.trop_longs, [])
        self.assertEqual((self.racine / "GROS.BIN").read_bytes(),
                         bytes(range(256)) * 40)
        self.assertTrue(all(len(e[1]) <= 1024
                            for e in self.machine.sorties[3].envoyes))

    def test_un_nom_pris_est_refuse_et_l_existant_reste_intact(self):
        from delugeapp.core.delugefiles import FileError

        files = self._branche()
        with self.assertRaises(FileError) as erreur:
            files.write_new("/songs/a.xml", b"ecrase ?")
        self.assertEqual(erreur.exception.code, 8)
        self.assertEqual((self.racine / "SONGS/A.XML").read_bytes(),
                         b"<song a/>")
        self.assertEqual([p.name for p in (self.racine / "SONGS").iterdir()],
                         ["A.XML"])

    def test_move_et_copy_qui_ecrasent_ne_partent_jamais(self):
        files = self._branche()
        files.write_new("/SONGS/B.XML", b"b")
        files.replace("/SONGS/A.XML", b"<song a v2/>")
        self.assertEqual(self._commandes("move") + self._commandes("copy"), [])

    def test_remplacer_sans_laisser_de_trace(self):
        files = self._branche()
        files.replace("/SONGS/A.XML", b"<song a v2/>", mtime=1_700_000_000)
        self.assertEqual((self.racine / "SONGS/A.XML").read_bytes(),
                         b"<song a v2/>")
        self.assertEqual([p.name for p in (self.racine / "SONGS").iterdir()],
                         ["A.XML"])
        entree = files.exists("/SONGS/A.XML")
        from delugeapp.core.delugefiles import fat_stamp

        self.assertEqual((entree.date, entree.time), fat_stamp(1_700_000_000))

    def test_un_dossier_absent_est_cree(self):
        files = self._branche()
        files.write_new("/SONGS/NEUF/X.XML", b"x")
        self.assertEqual((self.racine / "SONGS/NEUF/X.XML").read_bytes(), b"x")

    # -- les noms ------------------------------------------------------------- #

    def test_un_nom_accentue_n_est_pas_envoye(self):
        from delugeapp.core.delugefiles import FileError

        files = self._branche()
        avant = len(self._commandes())
        with self.assertRaises(FileError):
            files.write_new("/SONGS/dièse.XML", b"x")
        self.assertEqual(len(self._commandes()), avant)

    def test_un_nom_abime_au_retour_est_mis_a_part(self):
        """Mesuré : le bit 7 se perd, « è » revient en saut de ligne."""
        (self.racine / "SONGS" / "Le Mans - D dièse.XML").write_bytes(b"d")
        files = self._branche()
        arbre = files.walk("/")
        self.assertIn("SONGS/A.XML", arbre)
        self.assertEqual(files.unreachable, ["SONGS/Le Mans - D di\nse.XML"])

    # -- toute une synchronisation par le câble -------------------------------- #

    def test_synchroniser_par_usb(self):
        from delugeapp.core import cardsync

        from delugeapp.core.delugefiles import from_fat

        enregistre = self.racine / "SONGS" / "DELUGE.XML"
        enregistre.write_bytes(b"<song du deluge/>")
        nul = from_fat(0x21, 0)
        os.utime(enregistre, (nul, nul))          # date nulle : le Deluge
        files = self._branche()
        carte = cardsync.UsbCard(files)
        travail = Path(self._tmp.name) / "travail"
        travail.mkdir()
        manifeste = {}
        plan = cardsync.plan_sync(carte.walk(), cardsync.scan_local(travail),
                                  manifeste)
        resultat = cardsync.apply_plan(plan, carte, travail, manifeste)
        self.assertTrue(resultat.ok, resultat.errors)
        self.assertEqual((travail / "SONGS/DELUGE.XML").read_bytes(),
                         b"<song du deluge/>")
        self.assertNotEqual(files.exists("/SONGS/DELUGE.XML").date, 0)
        # Une création de l'application monte, et la suite est à jour.
        (travail / "SONGS" / "PC.XML").write_bytes(b"<song pc/>")
        plan = cardsync.plan_sync(carte.walk(), cardsync.scan_local(travail),
                                  manifeste)
        self.assertEqual([a.rel for a in plan.of("push")], ["SONGS/PC.XML"])
        self.assertTrue(cardsync.apply_plan(plan, carte, travail,
                                            manifeste).ok)
        self.assertEqual((self.racine / "SONGS/PC.XML").read_bytes(),
                         b"<song pc/>")
        plan = cardsync.plan_sync(carte.walk(), cardsync.scan_local(travail),
                                  manifeste)
        self.assertTrue(plan.empty, plan.summary())


class TestSauvegardeEnLectureSeule(unittest.TestCase):
    """La sauvegarde de la carte se lit, elle ne s'écrit jamais.

    L'utilisateur, le 18 octobre 2026 : « SDCARD Deluge est un emplacement
    de sauvegarde de ma carte SD qui n'est pas destiné à être le répertoire
    de travail ». L'application y avait pourtant réparé dix presets le
    11 octobre — que la carte, elle, n'a jamais reçus (mesuré par USB).
    """

    def setUp(self):
        from delugeapp.core.sdcard import SDCard

        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.racine = base / "SDCARD Deluge"
        for sous in ("SONGS", "SYNTHS", "KITS", "SAMPLES"):
            (self.racine / sous).mkdir(parents=True)
        preset = SynthPreset.new("P")
        preset.sound.osc1.type = "sample"
        preset.sound.osc1.file_name = "SAMPLES/A.wav"
        preset.save(self.racine / "SYNTHS" / "P.XML", backup=False)
        self.sd = SDCard(self.racine, read_only=True,
                         read_only_reason="sauvegarde")
        self.avant = _empreinte_dossier(self.racine)

    def tearDown(self):
        self.assertEqual(_empreinte_dossier(self.racine), self.avant,
                         "la sauvegarde a changé")
        self._tmp.cleanup()

    def test_ecrire_un_morceau_est_refuse(self):
        from delugeapp.core import songwriter

        track = songwriter.synth_track(SynthPreset.new("BASSE"))
        clip = songwriter.ClipSpec(track=0, length=songwriter.BAR, rows={
            60: [Note(pos=0, length=96, velocity=100)]})
        spec = songwriter.SongSpec(name="Essai", bpm=120.0, tracks=[track],
                                   clips=[clip])
        self.assertTrue(songwriter.write_song(self.sd, spec).rel)  # simuler
        with self.assertRaises(PermissionError):
            songwriter.write_song(self.sd, spec, apply=True)

    def test_relier_les_references_est_refuse(self):
        from delugeapp.core import deps

        self.assertTrue(deps.relink(self.sd, "SAMPLES/A.wav", "SAMPLES/B.wav"))
        with self.assertRaises(PermissionError):
            deps.relink(self.sd, "SAMPLES/A.wav", "SAMPLES/B.wav", apply=True)
        with self.assertRaises(PermissionError):
            deps.relink_many(self.sd, {"SAMPLES/A.wav": "SAMPLES/B.wav"},
                             apply=True)

    def test_un_plan_de_rangement_ou_de_correction_est_refuse(self):
        from delugeapp.core import organize, samplefix

        with self.assertRaises(PermissionError):
            organize.Plan().apply(self.sd, None)
        with self.assertRaises(PermissionError):
            samplefix.FixPlan().apply(self.sd, None)

    def test_restaurer_dessus_est_refuse(self):
        from delugeapp.core import backup

        from datetime import datetime

        with self.assertRaises(PermissionError):
            backup.restore_backup(backup.BackupInfo(
                Path(self._tmp.name) / "x", datetime.now()), self.sd,
                apply=True)

    def test_le_contexte_refuse_d_ecrire_sans_lever(self):
        from delugeapp.config import AppContext, Settings

        ctx = AppContext(settings=Settings(), sd=self.sd, lib=None,
                         player=None)
        self.assertIs(ctx.sd_or_warn(None), self.sd)            # lire : oui
        self.assertIsNone(ctx.sd_or_warn(None, write=True))      # écrire : non


class TestRolesDeLaCarte(unittest.TestCase):
    """Copie de travail, sauvegarde, carte dans un lecteur : chacun son rôle."""

    def setUp(self):
        from delugeapp.config import Settings

        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.reglages = Settings()
        self.reglages.work_dir = str(self.base / "travail")

    def tearDown(self):
        self._tmp.cleanup()

    def test_l_ancien_dossier_de_travail_devient_la_sauvegarde(self):
        sauvegarde = self.base / "SDCARD Deluge"
        self.reglages.sd_path = str(sauvegarde)
        self.assertTrue(self.reglages.adopt_card_roles())
        self.assertEqual(self.reglages.card_backup, str(sauvegarde))
        self.assertFalse(self.reglages.adopt_card_roles())     # une fois
        self.assertEqual(self.reglages.card_role(sauvegarde), "sauvegarde")
        carte = self.reglages.open_card(sauvegarde)
        self.assertTrue(carte.read_only)
        self.assertIn("sauvegarde", carte.read_only_reason)

    def test_une_carte_dans_un_lecteur_ou_la_copie_de_travail_restent(self):
        from delugeapp.core.sdcard import is_drive_root

        self.assertTrue(is_drive_root(Path(Path.cwd().anchor)))
        self.assertFalse(is_drive_root(self.base))
        self.reglages.sd_path = Path.cwd().anchor
        self.assertFalse(self.reglages.adopt_card_roles())
        self.reglages.sd_path = self.reglages.work_dir
        self.assertFalse(self.reglages.adopt_card_roles())
        self.assertEqual(self.reglages.card_role(self.reglages.work_dir),
                         "travail")
        self.assertFalse(self.reglages.open_card(self.reglages.work_dir)
                         .read_only)

    def test_les_reglages_se_relisent(self):
        from delugeapp.config import Settings

        self.reglages.card_backup = "D:/sauvegarde"
        self.reglages.auto_sync = False
        relu = Settings.from_dict(self.reglages.to_dict())
        self.assertEqual((relu.work_dir, relu.card_backup, relu.auto_sync),
                         (self.reglages.work_dir, "D:/sauvegarde", False))


# --------------------------------------------------------------------------- #
# Le PC et le Deluge, dans les deux sens (18 octobre 2026)
# --------------------------------------------------------------------------- #

def _wav_a_la_main(chemin, tag=1, canaux=1, frequence=44100, bits=16,
                   trames=64, magic=b"RIFF", sous_format=None,
                   avec_donnees=True, donnees=None):
    """Un WAV écrit octet par octet : ce qu'aucun écrivain soigneux ne
    produit, mais que des logiciels de MAO écrivent — l'en-tête étendu,
    l'A-law, le RIFX."""
    import struct

    e = ">" if magic == b"RIFX" else "<"
    octets = max(1, (bits + 7) // 8)
    bloc = canaux * octets
    fmt = struct.pack(e + "HHIIHH", 0xFFFE if sous_format is not None else tag,
                      canaux, frequence, frequence * bloc, bloc, bits)
    if sous_format is not None:
        fmt += struct.pack(e + "HHI", 22, bits, 0)
        fmt += struct.pack(e + "H", sous_format) + bytes(14)
    corps = b"WAVE" + b"fmt " + struct.pack(e + "I", len(fmt)) + fmt
    if avec_donnees:
        if donnees is None:
            donnees = bytes((i * 37) % 256 for i in range(trames * bloc))
        corps += b"data" + struct.pack(e + "I", len(donnees)) + donnees
        if len(donnees) & 1:
            corps += b"\x00"
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_bytes(magic + struct.pack(e + "I", len(corps)) + corps)
    return chemin


def _preset(chemin, *echantillons):
    """Un preset de synthé, citant au plus deux échantillons."""
    preset = SynthPreset.new(Path(chemin).stem)
    for osc, rel in zip((preset.sound.osc1, preset.sound.osc2), echantillons):
        osc.type = "sample"
        osc.file_name = rel
    Path(chemin).parent.mkdir(parents=True, exist_ok=True)
    preset.save(Path(chemin), backup=False)
    return Path(chemin)


class TestCeQueLeDelugeLit(unittest.TestCase):
    """``wav.deluge_problem`` : les règles de lecture du firmware de la
    machine (1.3 bêta ``102cf9f``, ``AudioFile::loadFile``), fichier par
    fichier. Mesuré : la carte et le PC de l'utilisateur les respectent
    déjà partout — ces cas sont ceux qui arriveront d'ailleurs."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dossier = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_ce_que_l_application_ecrit_le_deluge_le_lit(self):
        for nom, profondeur in (("p8.wav", 8), ("p16.wav", 16),
                                ("p24.wav", 24), ("p32.wav", 32),
                                ("f32.wav", "float32"), ("a16.aif", 16),
                                ("a24.aiff", 24)):
            chemin = _son(self.dossier / nom, profondeur=profondeur)
            self.assertEqual(wav.deluge_problem(chemin), ("", False), nom)
        for taux in (5000, 44100, 48000, 96000):
            chemin = _son(self.dossier / ("t%d.wav" % taux), taux=taux)
            self.assertEqual(wav.deluge_problem(chemin), ("", False), taux)
        self.assertEqual(wav.deluge_problem(
            _son(self.dossier / "st.wav", canaux=2)), ("", False))

    def test_ce_que_la_conversion_repare(self):
        cas = {
            "etendu": _wav_a_la_main(self.dossier / "etendu.wav", bits=24,
                                     sous_format=1),
            "alaw": _wav_a_la_main(self.dossier / "alaw.wav", tag=6, bits=8),
            "rifx": _wav_a_la_main(self.dossier / "rifx.wav", magic=b"RIFX"),
            "flottant 64": _son(self.dossier / "f64.wav",
                                profondeur="float64"),
            "192 kHz": _son(self.dossier / "192k.wav", taux=192000),
            "AIFF flottant": _son(self.dossier / "f.aif",
                                  profondeur="float32"),
        }
        for nom, chemin in cas.items():
            raison, reparable = wav.deluge_problem(chemin)
            self.assertTrue(raison, nom)
            self.assertTrue(reparable, "%s : %s" % (nom, raison))
        self.assertIn("WAVE_FORMAT_EXTENSIBLE",
                      wav.deluge_problem(cas["etendu"])[0])
        self.assertIn("A-law", wav.deluge_problem(cas["alaw"])[0])

    def test_ce_qui_ne_se_repare_pas(self):
        quatre = _son(self.dossier / "quatre.wav", canaux=4)
        adpcm = _wav_a_la_main(self.dossier / "adpcm.wav", tag=2, bits=4)
        tronque = _wav_a_la_main(self.dossier / "tronque.wav",
                                 avec_donnees=False)
        mp3 = self.dossier / "chanson.mp3"
        mp3.write_bytes(b"ID3" + bytes(100))
        cache = self.dossier / "._kick.wav"
        cache.write_bytes(b"\x00\x05\x16\x07" + bytes(80))
        faux = self.dossier / "faux.wav"
        faux.write_bytes(b"ceci n'est pas un son")
        for chemin, mot in ((quatre, "canaux"), (adpcm, "compressé"),
                            (tronque, "abîmé"), (mp3, ".mp3"),
                            (cache, "point"), (faux, "ni WAV ni AIFF")):
            raison, reparable = wav.deluge_problem(chemin)
            self.assertIn(mot, raison, chemin.name)
            self.assertFalse(reparable, chemin.name)


class TestEnvoyerAuDeluge(unittest.TestCase):
    """``core/cardimport.py`` : du PC vers la carte, sur des dossiers bâtis à
    l'image des deux packs mesurés chez l'utilisateur — l'un à la forme de
    la carte, l'autre non, avec ses parasites de macOS."""

    def setUp(self):
        from delugeapp.core import cardimport
        from delugeapp.core.sdcard import SDCard

        self.ci = cardimport
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.carte = base / "carte"
        for sous in ("SONGS", "SYNTHS", "KITS", "SAMPLES/DRUMS/Kick"):
            (self.carte / sous).mkdir(parents=True)
        _son(self.carte / "SAMPLES/DRUMS/Kick/K1.wav", 60)
        self.sd = SDCard(self.carte)
        self.pc = base / "pc"
        self.pc.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _plan(self, *sources, dest="SAMPLES"):
        scan = self.ci.scan_sources([self.pc / s for s in sources])
        return self.ci.plan_import(scan, self.carte, dest)

    @staticmethod
    def _rels(plan, *actions):
        return sorted(i.rel for i in plan.of(*actions))

    # -- les noms ----------------------------------------------------------- #

    def test_un_nom_qui_passe_par_le_cable(self):
        for brut, propre in (("Épée", "Epee"), ("a:b?c", "a_b_c"),
                             ("fin. ", "fin"), ("CON", "_CON"),
                             ("Straße", "Strasse"), ("Kick “dur”", "Kick 'dur'"),
                             ("kick dist 10 [2022-07-05 164600].wav",
                              "kick dist 10 [2022-07-05 164600].wav")):
            self.assertEqual(self.ci.card_name(brut), propre, brut)
            self.assertTrue(all(32 <= ord(c) < 127
                                for c in self.ci.card_name(brut)))

    # -- les packs ----------------------------------------------------------- #

    def test_un_pack_a_la_forme_de_la_carte_garde_ses_chemins(self):
        racine = self.pc / "postsolarpunk Multisamples"
        for nom in ("kick 1 [2022-07-05].wav", "kick 2 [2022-07-05].wav"):
            _son(racine / "SAMPLES/MULTISAMPLES/p23 kick map" / nom)
        _preset(racine / "SYNTHS/Artists/postsolarpunk/P23Kick.XML",
                "SAMPLES/MULTISAMPLES/p23 kick map/kick 1 [2022-07-05].wav",
                "SAMPLES/Multisamples/P23 KICK MAP/kick 2 [2022-07-05].wav")
        (racine / "README.txt").write_text("merci")
        plan = self._plan("postsolarpunk Multisamples")
        self.assertEqual(self._rels(plan, "copy"), [
            "SAMPLES/MULTISAMPLES/p23 kick map/kick 1 [2022-07-05].wav",
            "SAMPLES/MULTISAMPLES/p23 kick map/kick 2 [2022-07-05].wav",
            "SYNTHS/Artists/postsolarpunk/P23Kick.XML"])
        # La casse des références n'est pas fiable (SPEC §1.7) : FAT l'ignore.
        self.assertEqual(plan.missing, {})
        self.assertEqual([r for _c, r in plan.ignored if "documentation" in r],
                         ["documentation : reste sur le PC"])

    def test_un_pack_sans_la_forme_de_la_carte(self):
        """« TJontheRoad Delugetions » : ``TJ SYNTHS/SYNTHS/*.XML`` va dans
        un dossier au nom du pack sous SYNTHS — envoyés sur la machine le
        9 novembre 2026, ses 36 presets s'étaient vidés à la racine, au
        milieu des dossiers rangés ; ``TJ SAMPLES`` garde son nom sous la
        destination."""
        racine = self.pc / "TJ Pack"
        _son(racine / "TJ SAMPLES/TJ Kick/00-KICK.wav")
        _preset(racine / "TJ SYNTHS/SYNTHS/Amb Air.XML")
        for parasite in ("__MACOSX/TJ SAMPLES/._00-KICK.wav",
                         "TJ SAMPLES/.DS_Store", "TJ SAMPLES/TJ Kick/._00-KICK.wav",
                         "TJ SAMPLES/TJ Kick/00-KICK.wav.reapeaks"):
            p = racine / parasite
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"\x00\x05\x16\x07")
        plan = self._plan("TJ Pack")
        self.assertEqual(self._rels(plan, "copy"), [
            "SAMPLES/TJ Pack/TJ SAMPLES/TJ Kick/00-KICK.wav",
            "SYNTHS/TJ Pack/Amb Air.XML"])
        self.assertGreaterEqual(plan.junk, 4)
        self.assertEqual(plan.ignored, [])

    def test_rien_ne_se_pose_a_la_racine_et_les_presets_suivent(self):
        """Un pack à la forme de la carte dont un son et un preset tombent à
        la racine : tous deux vont dans le dossier du pack, et le preset,
        réécrit, cite le son à sa nouvelle place."""
        racine = self.pc / "Mon Pack"
        _son(racine / "SAMPLES/grosse.wav", 70)
        _preset(racine / "SYNTHS/Basse.XML", "SAMPLES/grosse.wav")
        _preset(racine / "SYNTHS/Ranges/Nappe.XML")
        plan = self._plan("Mon Pack")
        self.assertEqual(self._rels(plan, "copy"), [
            "SAMPLES/Mon Pack/grosse.wav", "SYNTHS/Mon Pack/Basse.XML",
            "SYNTHS/Ranges/Nappe.XML"])
        self.assertEqual(plan.retarget, {"SYNTHS/Mon Pack/Basse.XML": {
            "SAMPLES/grosse.wav": "SAMPLES/Mon Pack/grosse.wav"}})
        self.assertEqual(plan.missing, {})
        self.ci.apply_import(plan, self.sd)
        relu = SynthPreset.load(self.carte / "SYNTHS/Mon Pack/Basse.XML")
        self.assertEqual(relu.sound.osc1.file_name,
                         "SAMPLES/Mon Pack/grosse.wav")

    def test_un_fichier_deja_range_ailleurs_n_est_pas_recopie(self):
        """Le pack « TJontheRoad » était déjà sur la carte, dans SYNTHS/tj :
        envoyé de nouveau, il s'y serait mis en double. Un son identique
        rangé ailleurs n'est pas recopié non plus, et le preset du pack qui
        le cite est réécrit vers lui."""
        racine = self.pc / "TJ Pack"
        _preset(racine / "TJ SYNTHS/SYNTHS/Amb Air.XML")
        (self.carte / "SYNTHS/tj").mkdir()
        (self.carte / "SYNTHS/tj/Amb Air.XML").write_bytes(
            (racine / "TJ SYNTHS/SYNTHS/Amb Air.XML").read_bytes())
        _son(racine / "SAMPLES/K1 copie.wav", 60)
        (racine / "SAMPLES/K1 copie.wav").write_bytes(
            (self.carte / "SAMPLES/DRUMS/Kick/K1.wav").read_bytes())
        _preset(racine / "SYNTHS/Frappe.XML", "SAMPLES/K1 copie.wav")
        plan = self._plan("TJ Pack")
        memes = {i.rel: i.reason for i in plan.of("same")}
        self.assertEqual(sorted(memes), ["SAMPLES/DRUMS/Kick/K1.wav",
                                         "SYNTHS/tj/Amb Air.XML"])
        self.assertIn("SYNTHS/tj/Amb Air.XML", memes["SYNTHS/tj/Amb Air.XML"])
        self.assertEqual(self._rels(plan, "copy"),
                         ["SYNTHS/TJ Pack/Frappe.XML"])
        self.assertEqual(plan.retarget["SYNTHS/TJ Pack/Frappe.XML"],
                         {"SAMPLES/K1 copie.wav": "SAMPLES/DRUMS/Kick/K1.wav"})

    def test_en_vrac_dans_la_destination_choisie(self):
        _son(self.pc / "kick.wav")
        _preset(self.pc / "Bass.XML")
        plan = self._plan("kick.wav", "Bass.XML", dest="SAMPLES/DRUMS/Kick")
        self.assertEqual(self._rels(plan, "copy"),
                         ["SAMPLES/DRUMS/Kick/kick.wav", "SYNTHS/Bass.XML"])
        # Une destination hors de SAMPLES n'en est pas une.
        plan = self._plan("kick.wav", dest="SONGS/ailleurs")
        self.assertEqual(self._rels(plan, "copy"), ["SAMPLES/kick.wav"])

    # -- rien d'existant n'est remplacé ---------------------------------------- #

    def test_identique_deja_la_numerote_ou_garde(self):
        k1 = self.carte / "SAMPLES/DRUMS/Kick/K1.wav"
        (self.pc / "same").mkdir()
        (self.pc / "same" / "K1.wav").write_bytes(k1.read_bytes())
        _son(self.pc / "autre" / "K1.wav", 90)
        _son(self.pc / "pack/SAMPLES/DRUMS/Kick/K1.wav", 120)
        plan = self.ci.plan_import(self.ci.scan_sources(
            [self.pc / "same" / "K1.wav", self.pc / "autre" / "K1.wav"]),
            self.carte, "SAMPLES/DRUMS/Kick")
        self.assertEqual(self._rels(plan, "same"),
                         ["SAMPLES/DRUMS/Kick/K1.wav"])
        self.assertEqual(self._rels(plan, "copy"),
                         ["SAMPLES/DRUMS/Kick/K1 2.wav"])
        plan = self._plan("pack")
        self.assertEqual(self._rels(plan, "kept"),
                         ["SAMPLES/DRUMS/Kick/K1.wav"])
        self.assertIn("presets du pack", plan.of("kept")[0].reason)
        avant = k1.read_bytes()
        self.ci.apply_import(plan, self.sd)
        self.assertEqual(k1.read_bytes(), avant)

    def test_apparu_entre_le_plan_et_la_copie_n_est_pas_ecrase(self):
        _son(self.pc / "snare.wav", 200)
        plan = self._plan("snare.wav")
        intrus = self.carte / "SAMPLES" / "snare.wav"
        intrus.write_bytes(b"ecrit entre-temps")
        resultat = self.ci.apply_import(plan, self.sd)
        self.assertEqual(resultat.written, [])
        self.assertEqual(len(resultat.errors), 1)
        self.assertEqual(intrus.read_bytes(), b"ecrit entre-temps")

    def test_la_sauvegarde_refuse_l_envoi(self):
        from delugeapp.core.sdcard import SDCard

        _son(self.pc / "snare.wav")
        plan = self._plan("snare.wav")
        avant = _empreinte_dossier(self.carte)
        with self.assertRaises(PermissionError):
            self.ci.apply_import(plan, SDCard(self.carte, read_only=True))
        self.assertEqual(_empreinte_dossier(self.carte), avant)

    # -- noms nettoyés : le pack suit ------------------------------------------ #

    def test_un_nom_accentue_est_nettoye_et_le_preset_suit(self):
        racine = self.pc / "pack"
        _son(racine / "SAMPLES/Été/Clé.wav")
        _preset(racine / "SYNTHS/Ré.XML", "SAMPLES/Été/Clé.wav")
        plan = self._plan("pack")
        self.assertEqual(self._rels(plan, "copy"),
                         ["SAMPLES/Ete/Cle.wav", "SYNTHS/pack/Re.XML"])
        self.assertEqual(plan.retarget, {"SYNTHS/pack/Re.XML": {
            "SAMPLES/Été/Clé.wav": "SAMPLES/Ete/Cle.wav"}})
        self.assertEqual(plan.missing, {})
        resultat = self.ci.apply_import(plan, self.sd)
        self.assertEqual(resultat.errors, [])
        relu = SynthPreset.load(self.carte / "SYNTHS/pack/Re.XML")
        self.assertEqual(relu.sound.osc1.file_name, "SAMPLES/Ete/Cle.wav")
        for p in self.carte.rglob("*"):
            self.assertTrue(all(ord(c) < 128 for c in p.name), p.name)

    def test_un_echantillon_introuvable_est_signale(self):
        _preset(self.pc / "pack/SYNTHS/Seul.XML", "SAMPLES/ABSENT/x.wav")
        plan = self._plan("pack")
        self.assertEqual(plan.missing,
                         {"SYNTHS/pack/Seul.XML": ["SAMPLES/ABSENT/x.wav"]})
        self.assertIn("introuvables", plan.to_text())

    # -- ce que le Deluge ne lit pas --------------------------------------------- #

    def test_ce_que_le_deluge_ne_lit_pas_reste_sur_le_pc(self):
        for nom, contenu in (("chanson.mp3", b"ID3"), ("motif.mid", b"MThd"),
                             ("lisez-moi.txt", b"merci"),
                             ("deluge-c1_2_1.bin", b"\x00"),
                             ("reglages.XML", b"<midiFollow/>"),
                             ("bizarre.foo", b"?")):
            (self.pc / nom).write_bytes(contenu)
        plan = self._plan("chanson.mp3", "motif.mid", "lisez-moi.txt",
                          "deluge-c1_2_1.bin", "reglages.XML", "bizarre.foo")
        self.assertEqual(plan.items, [])
        raisons = " | ".join(r for _c, r in plan.ignored)
        for mot in ("WAV", "MIDI", "documentation", "firmware", "réglage",
                    "pas un fichier du Deluge"):
            self.assertIn(mot, raisons)

    def test_un_en_tete_etendu_est_converti_sans_perte(self):
        source = _son(self.pc / "pc24.wav", profondeur=24)
        brut = source.read_bytes()
        debut = brut.find(b"data")
        taille = int.from_bytes(brut[debut + 4:debut + 8], "little")
        # Le même son, avec l'en-tête étendu qu'écrivent des logiciels de MAO.
        _wav_a_la_main(self.pc / "etendu.wav", bits=24, sous_format=1,
                       donnees=brut[debut + 8:debut + 8 + taille])
        plan = self._plan("etendu.wav")
        self.assertEqual(self._rels(plan, "convert"), ["SAMPLES/etendu.wav"])
        resultat = self.ci.apply_import(plan, self.sd)
        self.assertEqual(resultat.converted, ["SAMPLES/etendu.wav"])
        sur_la_carte = self.carte / "SAMPLES/etendu.wav"
        self.assertEqual(wav.deluge_problem(sur_la_carte), ("", False))
        avant, _ = wav.read(source)
        apres, _ = wav.read(sur_la_carte)
        self.assertEqual(wav.probe(sur_la_carte).bit_depth, 24)
        self.assertTrue(np.array_equal(avant, apres))

    # -- les sons compressés : décodés en WAV ------------------------------- #

    def _compresse(self, nom):
        """Un son de ``tests/donnees``, copié sur le PC : la sinusoïde de
        :func:`_son` sur un dixième de seconde, compressée par ffmpeg 8.1
        (FLAC 16 et 24 bits ; MP3 mono à 22 kHz, 64 kb/s ; Vorbis ; et un
        Opus dans un ``.ogg``, que le décodeur ne lit pas)."""
        import shutil

        from delugeapp.core import compressed

        if not compressed.available():
            self.skipTest("miniaudio absent")
        cible = self.pc / nom
        shutil.copyfile(Path(__file__).parent / "donnees" / nom, cible)
        return cible

    def test_un_flac_arrive_en_wav_a_l_echantillon_pres(self):
        for nom, profondeur in (("sinus16.flac", 16), ("sinus24.flac", 24)):
            with self.subTest(nom):
                self._compresse(nom)
                plan = self._plan(nom)
                rel = "SAMPLES/" + nom.replace(".flac", ".wav")
                self.assertEqual(self._rels(plan, "convert"), [rel])
                item = plan.of("convert")[0]
                self.assertIn("FLAC", item.reason)
                resultat = self.ci.apply_import(plan, self.sd)
                self.assertEqual(resultat.converted, [rel])
                sur_la_carte = self.carte / rel
                # Le câble transporte le WAV, pas le FLAC : le plan le savait.
                self.assertEqual(item.size, sur_la_carte.stat().st_size)
                self.assertEqual(wav.deluge_problem(sur_la_carte), ("", False))
                info = wav.probe(sur_la_carte)
                self.assertEqual((info.bit_depth, info.channels,
                                  info.sample_rate, info.frames),
                                 (profondeur, 2, 44100, 4410))
                attendu, _ = wav.read(_son(self.pc / "ref.wav", duree=0.1,
                                           profondeur=profondeur, canaux=2))
                relu, _ = wav.read(sur_la_carte)
                # Au plus un pas de quantification : la sinusoïde de
                # référence est recalculée ici, sur un autre processeur
                # peut-être.
                self.assertLessEqual(float(np.max(np.abs(relu - attendu))),
                                     1.0 / 2 ** (profondeur - 1) + 1e-9)

    def test_un_mp3_garde_sa_frequence_et_ses_canaux(self):
        """``miniaudio`` rend tout en stéréo à 44,1 kHz si on le laisse
        faire : un MP3 mono à 22 kHz doit arriver tel qu'il est."""
        self._compresse("sinus22k.mp3")
        plan = self._plan("sinus22k.mp3", dest="SAMPLES/DRUMS/Kick")
        rel = "SAMPLES/DRUMS/Kick/sinus22k.wav"
        self.assertEqual(self._rels(plan, "convert"), [rel])
        self.assertEqual(self.ci.apply_import(plan, self.sd).errors, [])
        info = wav.probe(self.carte / rel)
        self.assertEqual((info.channels, info.sample_rate, info.bit_depth,
                          info.frames), (1, 22050, 16, 2205))
        attendu, _ = wav.read(_son(self.pc / "ref.wav", duree=0.1,
                                   taux=22050))
        relu, _ = wav.read(self.carte / rel)
        # Calé sur l'original : le décodeur retire le délai de l'encodeur.
        correlation = np.corrcoef(attendu.ravel(), relu.ravel())[0, 1]
        self.assertGreater(correlation, 0.99)

    def test_un_ogg_deja_la_en_wav_est_numerote(self):
        self._compresse("sinus.ogg")
        deja = _son(self.carte / "SAMPLES/sinus.wav", 90)
        avant = deja.read_bytes()
        plan = self._plan("sinus.ogg")
        self.assertEqual(self._rels(plan, "convert"), ["SAMPLES/sinus 2.wav"])
        self.assertEqual(self.ci.apply_import(plan, self.sd).errors, [])
        self.assertEqual(deja.read_bytes(), avant)
        self.assertEqual(wav.probe(self.carte / "SAMPLES/sinus 2.wav")
                         .channels, 2)

    def test_ce_que_le_decodeur_ne_lit_pas_reste_sur_le_pc(self):
        self._compresse("opus.ogg")
        (self.pc / "abime.mp3").write_bytes(b"ID3" + bytes(40))
        (self.pc / "chanson.m4a").write_bytes(b"\x00" * 8)
        plan = self._plan("opus.ogg", "abime.mp3", "chanson.m4a")
        self.assertEqual(plan.items, [])
        self.assertEqual(len(plan.ignored), 3)
        for chemin, raison in plan.ignored:
            self.assertIn("exportez-le en WAV", raison, chemin)
        self.assertIn("Opus", dict(plan.ignored)[str(self.pc / "opus.ogg")])

    def test_sans_decodeur_les_sons_compresses_restent_sur_le_pc(self):
        import shutil
        from unittest import mock

        from delugeapp.core import compressed

        shutil.copyfile(Path(__file__).parent / "donnees" / "sinus16.flac",
                        self.pc / "sinus16.flac")
        with mock.patch.object(compressed, "_ma", None):
            plan = self._plan("sinus16.flac")
        self.assertEqual(plan.items, [])
        self.assertIn("exportez-le en WAV", plan.ignored[0][1])

    def test_quatre_canaux_sont_refuses(self):
        _son(self.pc / "quad.wav", canaux=4)
        plan = self._plan("quad.wav")
        self.assertEqual(self._rels(plan, "refused"), ["SAMPLES/quad.wav"])
        self.assertTrue(plan.empty)
        self.ci.apply_import(plan, self.sd)
        self.assertFalse((self.carte / "SAMPLES/quad.wav").exists())

    # -- le temps du câble -------------------------------------------------------- #

    def test_le_plan_dit_le_temps_du_cable(self):
        from delugeapp.core.delugefiles import cable_time

        # Les deux packs de l'utilisateur, à 60 Ko/s — deux blocs en vol,
        # mesuré le 22 octobre 2026 (7 min et 1 h 43 à 45 Ko/s, avant).
        self.assertEqual(cable_time(write_bytes=int(18.3 * 1024 * 1024)),
                         "environ 5 min")
        self.assertEqual(cable_time(write_bytes=int(271.2 * 1024 * 1024)),
                         "environ 1 h 17")
        self.assertEqual(cable_time(write_bytes=100_000), "quelques secondes")
        self.assertEqual(cable_time(read_bytes=4_000_000), "environ 30 s")

    def test_les_dossiers_proposes(self):
        self.assertEqual(self.ci.sample_folders(self.carte),
                         ["SAMPLES", "SAMPLES/DRUMS", "SAMPLES/DRUMS/Kick"])


class TestCableEnFile(unittest.TestCase):
    """Le câble USB face au Deluge simulé : deux lectures d'avance, un
    transfert qui s'arrête entre deux blocs, un câble débranché."""

    def setUp(self):
        from delugeapp.core import midiport
        from delugeapp.core.delugelink import DelugeLink

        self.midiport = midiport
        self._tmp = tempfile.TemporaryDirectory()
        self.racine = Path(self._tmp.name) / "carte"
        (self.racine / "SONGS").mkdir(parents=True)
        (self.racine / "SONGS" / "A.XML").write_bytes(b"<song a/>")
        self._sauves = (midiport.outputs, midiport.inputs,
                        midiport.available)
        self.machine = _deluge_simule().DelugeSimule(version=(1, 3, 0),
                                                     carte=self.racine)
        midiport.outputs = lambda: self.machine.devices("out")
        midiport.inputs = lambda: self.machine.devices("in")
        midiport.available = lambda: True
        self.lien = DelugeLink()
        self.machine.brancher(self.lien)
        self.assertTrue(self.lien.connect())
        self.lien.wait_files(5.0)
        self.files = self.lien.files

    def tearDown(self):
        self.lien.disconnect()
        (self.midiport.outputs, self.midiport.inputs,
         self.midiport.available) = self._sauves
        self._tmp.cleanup()

    def _lectures(self):
        return sum(1 for n, _ in self.machine.carte_usb.commandes
                   if n == "read")

    def test_deux_lectures_en_vol(self):
        import queue

        donnees = bytes((i * 7) % 256 for i in range(10_000))
        (self.racine / "GROS.BIN").write_bytes(donnees)
        vus: list[int] = []
        compter = self._lectures

        class FileComptee(queue.Queue):
            def get(self, *args, **kwargs):
                vus.append(compter())
                return super().get(*args, **kwargs)

        self.files._replies = FileComptee()
        self.assertEqual(self.files.read("/GROS.BIN"), donnees)
        # À la première attente d'un bloc, deux demandes sont déjà parties.
        premier = next(i for i, n in enumerate(vus) if n)
        self.assertEqual(vus[premier], 2)
        self.assertEqual(self._lectures(), 10)

    def test_deux_ecritures_en_vol(self):
        """Mesuré le 22 octobre 2026 : 61 à 63 Ko/s avec deux blocs en vol,
        48 à 50 un à la fois, rien de plus avec trois."""
        import queue

        donnees = bytes((i * 11) % 256 for i in range(5_000))
        vus: list[int] = []
        machine = self.machine

        def ecritures():
            return sum(1 for n, _ in machine.carte_usb.commandes
                       if n == "write")

        class FileComptee(queue.Queue):
            def get(self, *args, **kwargs):
                vus.append(ecritures())
                return super().get(*args, **kwargs)

        self.files._replies = FileComptee()
        self.files.write_new("/SONGS/GROS.BIN", donnees, mtime=None)
        self.assertEqual((self.racine / "SONGS" / "GROS.BIN").read_bytes(),
                         donnees)
        # À la première attente d'une réponse, deux blocs sont déjà partis.
        premier = next(i for i, n in enumerate(vus) if n)
        self.assertEqual(vus[premier], 2)

    def test_un_transfert_s_arrete_entre_deux_blocs(self):
        from delugeapp.core.delugefiles import STOPPED, FileError

        blocs = []
        self.files.stop_check = lambda: len(blocs) >= 3
        with self.assertRaises(FileError) as arret:
            self.files.write_new("/SONGS/GROS.XML", bytes(10_000), mtime=None,
                                 progress=lambda n, t: blocs.append(n))
        self.assertEqual(arret.exception.code, STOPPED)
        self.assertEqual(len(blocs), 3)
        # Ni le fichier, ni son temporaire : la carte est comme avant.
        self.assertEqual(sorted(p.name for p in (self.racine / "SONGS")
                                .iterdir()), ["A.XML"])
        self.files.stop_check = lambda: True
        with self.assertRaises(FileError) as arret:
            self.files.read("/SONGS/A.XML")
        self.assertEqual(arret.exception.code, STOPPED)

    # -- après une écriture : seuls les dossiers touchés ----------------------- #

    def _travail(self):
        """Une copie de travail à l'image de la carte simulée."""
        from delugeapp.ui import cardwork

        for rel, donnees in (("SYNTHS/P.XML", b"<sound p/>"),
                             ("SAMPLES/DRUMS/k.wav", b"RIFF-k"),
                             ("SAMPLES/DRUMS/s.wav", b"RIFF-s")):
            (self.racine / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.racine / rel).write_bytes(donnees)
        travail = Path(self._tmp.name) / "travail"
        plan, effet, *_ = cardwork._synchronise(self.files, travail, None,
                                                 False)
        self.assertEqual(effet.done["pull"], 4, plan.actions)
        return cardwork, travail

    def _dossiers_listes(self, depuis):
        return [a["path"] for n, a in self.machine.carte_usb.commandes[depuis:]
                if n == "dir"]

    def test_apres_une_ecriture_seul_son_dossier_est_liste(self):
        cardwork, travail = self._travail()
        (travail / "SONGS" / "NEUF.XML").write_bytes(b"<song neuf/>")
        avant = len(self.machine.carte_usb.commandes)
        plan, effet, *_ = cardwork._synchronise(
            self.files, travail, None, False, raison=cardwork.ECRITURE,
            quick=True)
        self.assertEqual(plan.scope, ["SONGS"])
        self.assertEqual([(a.kind, a.rel) for a in plan.actions],
                         [("push", "SONGS/NEUF.XML")])
        self.assertEqual(effet.done["push"], 1)
        self.assertEqual((self.racine / "SONGS" / "NEUF.XML").read_bytes(),
                         b"<song neuf/>")
        # Une page pour SONGS — et pas les cinq dossiers de la carte.
        listes = self._dossiers_listes(avant)
        self.assertEqual(set(listes), {"/SONGS"})

    def test_ce_que_le_deluge_a_enregistre_attend_le_parcours_complet(self):
        cardwork, travail = self._travail()
        (self.racine / "SYNTHS" / "MACHINE.XML").write_bytes(b"<sound m/>")
        (travail / "SONGS" / "NEUF.XML").write_bytes(b"<song neuf/>")
        plan, *_ = cardwork._synchronise(self.files, travail, None, False,
                                         quick=True)
        self.assertNotIn("SYNTHS/MACHINE.XML", [a.rel for a in plan.actions])
        self.assertFalse((travail / "SYNTHS" / "MACHINE.XML").exists())
        plan, *_ = cardwork._synchronise(self.files, travail, None, False)
        self.assertEqual([(a.kind, a.rel) for a in plan.actions],
                         [("pull", "SYNTHS/MACHINE.XML")])

    def test_une_suppression_locale_attend_toujours_l_accord(self):
        cardwork, travail = self._travail()
        (travail / "SAMPLES" / "DRUMS" / "k.wav").unlink()
        plan, effet, *_ = cardwork._synchronise(self.files, travail, None,
                                                 False, quick=True)
        self.assertEqual(plan.scope, ["SAMPLES/DRUMS"])
        self.assertEqual([a.rel for a in plan.needs_consent],
                         ["SAMPLES/DRUMS/k.wav"])
        self.assertTrue((self.racine / "SAMPLES" / "DRUMS" / "k.wav").exists())
        self.assertEqual(sum(effet.done.values()), 0)

    def test_un_dossier_neuf_part_tel_quel(self):
        """Un dossier que la carte n'a pas encore : listé vide, puis créé
        par la machine elle-même à l'écriture (``createPathDirectories``)."""
        cardwork, travail = self._travail()
        neuf = travail / "SAMPLES" / "ESSAI" / "a.wav"
        neuf.parent.mkdir(parents=True)
        neuf.write_bytes(b"RIFF-a")
        plan, effet, *_ = cardwork._synchronise(self.files, travail, None,
                                                 False, quick=True)
        self.assertEqual(plan.scope, ["SAMPLES/ESSAI"])
        self.assertEqual(effet.done["push"], 1)

    def test_une_synchronisation_complete_en_attente_n_est_pas_perdue(self):
        """La machine joue ; la connexion attend, puis on écrit : à l'arrêt,
        c'est la synchronisation complète qui part, pas la restreinte."""
        from delugeapp.ui.cardwork import ECRITURE, _plus_large

        self.assertEqual(_plus_large(None, ECRITURE), ECRITURE)
        self.assertEqual(_plus_large("connexion", ECRITURE), "connexion")
        self.assertEqual(_plus_large(ECRITURE, "retour"), "retour")
        self.assertEqual(_plus_large(ECRITURE, ECRITURE), ECRITURE)

    def test_rien_de_change_rien_n_est_liste(self):
        cardwork, travail = self._travail()
        avant = len(self.machine.carte_usb.commandes)
        plan, effet, _s, attente, _r = cardwork._synchronise(
            self.files, travail, None, False, quick=True)
        self.assertEqual((plan.scope, attente), ([], []))
        self.assertEqual(self._dossiers_listes(avant), [])

    def test_un_cable_debranche_le_dit_tout_de_suite(self):
        from delugeapp.core.delugefiles import NOT_CONNECTED, FileError

        # Débranché : plus aucun port — le lien retomberait sinon sur le
        # premier câble.
        for port in self.machine.sorties.values():
            port.close()
        debut = time.monotonic()
        with self.assertRaises(FileError) as erreur:
            self.files.listdir("/")
        self.assertEqual(erreur.exception.code, NOT_CONNECTED)
        self.assertLess(time.monotonic() - debut, 1.0)


class TestEchangesAvecLeDeluge(unittest.TestCase):
    """Ce qui attend, ce qui a voyagé, et une synchronisation qui s'arrête
    proprement (``core/cardsync.py``)."""

    def setUp(self):
        from delugeapp.core import cardsync

        self.cs = cardsync
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.carte = base / "carte"
        self.travail = base / "travail"
        self.sauvegarde = base / "sauvegarde"
        self.travail.mkdir()
        TestSynchroCarte._ecrit(self.carte, "SONGS/A.XML", b"<song a/>",
                                1_700_000_000)
        TestSynchroCarte._ecrit(self.carte, "SYNTHS/P.XML", b"<sound p/>",
                                1_700_000_100)

    def tearDown(self):
        self._tmp.cleanup()

    def _synchronise(self, transport=None, **options):
        transport = transport or self.cs.FolderCard(self.carte)
        manifeste = self.cs.load_manifest(self.travail)
        plan = self.cs.plan_sync(transport.walk(),
                                 self.cs.scan_local(self.travail), manifeste)
        return plan, self.cs.apply_plan(plan, transport, self.travail,
                                        manifeste, **options)

    def _carte_qui_cede(self, code, apres=0):
        from delugeapp.core.delugefiles import FileError

        cs = self.cs

        class CarteQuiCede(cs.FolderCard):
            envois = 0

            def write_new(self, rel, data, mtime, progress=None):
                type(self).envois += 1
                if type(self).envois > apres:
                    raise FileError("essai", code=code)
                super().write_new(rel, data, mtime, progress)

        return CarteQuiCede(self.carte)

    def _trois_creations(self):
        self._synchronise()
        for nom in ("C1", "C2", "C3"):
            TestSynchroCarte._ecrit(self.travail, "SONGS/%s.XML" % nom,
                                    b"<song %s/>" % nom.encode(),
                                    time.time())

    def test_le_plan_restreint_est_le_plan_complet_sur_ses_dossiers(self):
        """Sur les dossiers qu'il couvre, le plan restreint décide comme le
        plan complet — fichier par fichier ; ailleurs, il ne dit rien."""
        ecrit = TestSynchroCarte._ecrit
        ecrit(self.carte, "SAMPLES/K/k.wav", b"k", 1_700_000_200)
        ecrit(self.carte, "SAMPLES/K/s.wav", b"s", 1_700_000_300)
        self._synchronise()
        # De tout : reçu, envoyé, supprimé d'un côté puis de l'autre, changé
        # des deux côtés, dans deux dossiers sur trois.
        ecrit(self.carte, "SONGS/DELUGE.XML", b"<song d/>", 1_700_100_000)
        ecrit(self.travail, "SONGS/PC.XML", b"<song pc/>", time.time())
        ecrit(self.carte, "SONGS/A.XML", b"<song a2/>", 1_700_100_000)
        ecrit(self.travail, "SONGS/A.XML", b"<song a3/>", time.time())
        (self.carte / "SAMPLES" / "K" / "k.wav").unlink()
        (self.travail / "SAMPLES" / "K" / "s.wav").unlink()
        ecrit(self.carte, "SYNTHS/Q.XML", b"<sound q/>", 1_700_100_000)
        carte = self.cs.FolderCard(self.carte)
        local = self.cs.scan_local(self.travail)
        manifeste = self.cs.load_manifest(self.travail)
        complet = self.cs.plan_sync(carte.walk(), local, manifeste)
        dossiers = ["SONGS", "SAMPLES/K"]
        restreint = self.cs.plan_folders(carte.walk_folders(dossiers), local,
                                         manifeste, dossiers)

        def dans(plan):
            return sorted((a.kind, a.rel) for a in plan.actions
                          if self.cs.parent_folder(a.rel) in dossiers)

        self.assertEqual(dans(restreint), dans(complet))
        self.assertEqual(len(dans(restreint)), len(restreint.actions))
        self.assertEqual({a.kind for a in restreint.actions},
                         {"pull", "push", "conflict", "delete_local",
                          "delete_card"})
        self.assertIn(("pull", "SYNTHS/Q.XML"),
                      [(a.kind, a.rel) for a in complet.actions])

    def test_les_dossiers_changes_comptent_les_suppressions(self):
        TestSynchroCarte._ecrit(self.carte, "SAMPLES/K/k.wav", b"k",
                                1_700_000_200)
        self._synchronise()
        self.assertEqual(self.cs.changed_folders(self.travail), [])
        TestSynchroCarte._ecrit(self.travail, "SONGS/B.XML", b"<song b/>",
                                time.time())
        (self.travail / "SAMPLES" / "K" / "k.wav").unlink()
        self.assertEqual(self.cs.changed_folders(self.travail),
                         ["SAMPLES/K", "SONGS"])

    def test_un_plan_restreint_garde_les_suppressions_d_ailleurs(self):
        """Sans quoi « Suppressions à confirmer » se viderait après chaque
        envoi d'un morceau."""
        cs = self.cs
        ancien = cs.SyncPlan(actions=[
            cs.Action("delete_card", "SAMPLES/K/k.wav", 10),
            cs.Action("delete_card", "SONGS/VIEUX.XML", 5)],
            unreachable=["SAMPLES/Été/x.wav"])
        neuf = cs.SyncPlan(actions=[cs.Action("push", "SONGS/NEUF.XML", 3)],
                           scope=["SONGS"])
        fusion = cs.merge_plans(neuf, ancien)
        self.assertEqual([a.rel for a in fusion.needs_consent],
                         ["SAMPLES/K/k.wav"])
        self.assertEqual(fusion.unreachable, ["SAMPLES/Été/x.wav"])
        # Un plan complet remplace tout.
        complet = cs.SyncPlan()
        self.assertEqual(cs.merge_plans(complet, ancien).needs_consent, [])

    def test_les_temporaires_ne_voyagent_jamais(self):
        for rel in ("SAMPLES/a.wav.noct-tmp", "SAMPLES/a.wav.dc-tmp",
                    "SAMPLES/b.wav.tmp~", "SYNTHS/P.ab12cd_9.tmp"):
            self.assertTrue(self.cs.is_junk(rel), rel)
        for rel in ("SONGS/tmp.XML", "SAMPLES/temp.wav"):
            self.assertFalse(self.cs.is_junk(rel), rel)

    def test_un_arret_garde_ce_qui_est_fait(self):
        from delugeapp.core.delugefiles import STOPPED

        self._trois_creations()
        _plan, resultat = self._synchronise(self._carte_qui_cede(STOPPED, 1))
        self.assertTrue(resultat.stopped)
        self.assertFalse(resultat.lost)
        self.assertEqual(resultat.errors, [])
        self.assertEqual(resultat.done["push"], 1)
        # La suite part à la synchronisation suivante, et rien ne repart deux
        # fois.
        plan, resultat = self._synchronise()
        self.assertEqual(len(plan.of("push")), 2)
        self.assertTrue(resultat.ok)
        self.assertTrue(self._synchronise()[0].empty)

    def test_un_cable_debranche_arrete_tout_de_suite(self):
        from delugeapp.core.delugefiles import NOT_CONNECTED

        self._trois_creations()
        carte = self._carte_qui_cede(NOT_CONNECTED)
        _plan, resultat = self._synchronise(carte)
        self.assertTrue(resultat.lost)
        self.assertEqual(resultat.errors, ["le Deluge a été débranché"])
        self.assertEqual(type(carte).envois, 1)

    def test_deux_silences_arretent(self):
        self._trois_creations()
        carte = self._carte_qui_cede(15)
        _plan, resultat = self._synchronise(carte)
        self.assertTrue(resultat.lost)
        self.assertIn("le Deluge ne répond plus", resultat.errors)
        self.assertEqual(type(carte).envois, 2)

    def test_l_historique_raconte_chaque_echange(self):
        _plan, resultat = self._synchronise()
        echange = self.cs.exchange_of(resultat, "connexion", 1.5)
        self.assertEqual(sorted(echange.received),
                         ["SONGS/A.XML", "SYNTHS/P.XML"])
        self.assertTrue(self.cs.record_exchange(self.travail, echange))
        TestSynchroCarte._ecrit(self.travail, "SONGS/CREE.XML", b"<song/>",
                                time.time())
        _plan, resultat = self._synchronise()
        self.cs.record_exchange(self.travail,
                                self.cs.exchange_of(resultat, "écriture"))
        # Une synchronisation qui n'a rien fait ne s'écrit pas.
        _plan, resultat = self._synchronise()
        self.assertFalse(self.cs.record_exchange(
            self.travail, self.cs.exchange_of(resultat, "retour")))
        gardes = self.cs.load_exchanges(self.travail)
        self.assertEqual([e.reason for e in gardes], ["écriture", "connexion"])
        self.assertEqual(gardes[0].sent, ["SONGS/CREE.XML"])
        self.assertEqual(gardes[0].summary(), "1 envoyé(s)")
        self.assertEqual(gardes[1].summary(), "2 reçu(s)")
        # Pas plus de deux cents.
        for i in range(self.cs.MAX_EXCHANGES + 5):
            self.cs.record_exchange(self.travail, self.cs.Exchange(
                when=time.time() + i, reason="x", counts={"push": 1}))
        self.assertEqual(len(self.cs.load_exchanges(self.travail)),
                         self.cs.MAX_EXCHANGES)

    def test_les_arrivees_recentes(self):
        TestSynchroCarte._ecrit(self.carte, "SAMPLES/RECORD/REC00001.WAV",
                                b"RIFF", None)
        TestSynchroCarte._ecrit(self.carte, "SETTINGS/MIDIFollow.XML",
                                b"<x/>", None)
        _plan, resultat = self._synchronise()
        self.cs.record_exchange(self.travail,
                                self.cs.exchange_of(resultat, "connexion"))
        arrivees = [rel for _quand, rel in
                    self.cs.recent_arrivals(self.travail)]
        self.assertEqual(sorted(arrivees), ["SAMPLES/RECORD/REC00001.WAV",
                                            "SONGS/A.XML", "SYNTHS/P.XML"])
        (self.travail / "SONGS/A.XML").unlink()
        self.assertNotIn("SONGS/A.XML",
                         [r for _q, r in self.cs.recent_arrivals(self.travail)])

    def test_ce_qui_attend_d_etre_envoye(self):
        self.assertEqual(self.cs.pending_changes(self.travail), [])
        self._synchronise()
        self.assertEqual(self.cs.pending_changes(self.travail), [])
        TestSynchroCarte._ecrit(self.travail, "SONGS/CREE.XML", b"<song/>",
                                time.time())
        TestSynchroCarte._ecrit(self.travail, "SYNTHS/P.XML", b"<sound P2/>",
                                time.time() + 5)
        self.assertEqual(self.cs.pending_changes(self.travail),
                         [("SONGS/CREE.XML", 7), ("SYNTHS/P.XML", 11)])

    def test_la_sauvegarde_ne_relit_que_ce_qui_a_bouge(self):
        from unittest import mock

        self._synchronise()
        for rel in ("SONGS/A.XML", "SYNTHS/P.XML"):
            TestSynchroCarte._ecrit(self.sauvegarde, rel,
                                    (self.travail / rel).read_bytes(),
                                    1_600_000_000)
        appels = []
        vrai = self.cs._same_content

        def compte(a, b):
            appels.append(Path(a).name)
            return vrai(a, b)

        with mock.patch.object(self.cs, "_same_content", compte):
            plan = self.cs.update_backup(self.travail, self.sauvegarde)
            self.assertEqual(plan.summary(), "déjà à jour")
            self.assertEqual(len(appels), 2)
            appels.clear()
            self.cs.update_backup(self.travail, self.sauvegarde)
            self.assertEqual(appels, [])
            TestSynchroCarte._ecrit(self.travail, "SONGS/A.XML", b"<song A/>",
                                    time.time())
            plan = self.cs.update_backup(self.travail, self.sauvegarde)
            self.assertEqual(appels, ["A.XML"])
            self.assertEqual(plan.replaced, ["SONGS/A.XML"])
        self.assertEqual(self.cs.backup_state(self.travail,
                                              self.sauvegarde)["updated"], 0)
        self.cs.update_backup(self.travail, self.sauvegarde, apply=True)
        self.assertGreater(self.cs.backup_state(self.travail,
                                                self.sauvegarde)["updated"], 0)
        self.assertEqual((self.sauvegarde / "SONGS/A.XML").read_bytes(),
                         b"<song A/>")
        # Une autre sauvegarde ne profite pas de ce que l'on sait de celle-ci.
        self.assertEqual(self.cs.backup_state(self.travail,
                                              self.carte), {})


class TestFavorisDuDeluge(unittest.TestCase):
    """``SETTINGS/FAVOURITES``, au format du firmware 1.3.0."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "carte"
        for sous in ("SONGS", "SYNTHS", "KITS", "SAMPLES/DRUMS/Kick",
                     "SETTINGS/FAVOURITES"):
            (self.root / sous).mkdir(parents=True)
        t = np.linspace(0, 0.2, 8820, endpoint=False, dtype=np.float32)
        for i, nom in enumerate(("a.wav", "b.wav")):
            wav.write(self.root / "SAMPLES/DRUMS/Kick" / nom,
                      (0.3 * (i + 1) * np.sin(2 * np.pi * 60 * t)
                       ).astype(np.float32), 44100)
        # La banque vide que la machine crée au premier passage.
        (self.root / "SETTINGS/FAVOURITES/SAMPLES_Bank0.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n<favourites>\n'
            '</favourites>\n', encoding="utf-8")
        self.sd = sdcard.SDCard(self.root)
        self.lib = db.Library(Path(self._tmp.name) / "i.db")

    def tearDown(self):
        self.lib.close()
        self._tmp.cleanup()

    def test_un_son_va_sur_le_premier_pad_libre_puis_le_quitte(self):
        from delugeapp.core import favourites as fv

        rel = "SAMPLES/DRUMS/Kick/a.wav"
        self.assertEqual(fv.read(self.sd, "SAMPLES"), [])
        fav = fv.plan_add(self.sd, "SAMPLES", rel)
        self.assertEqual((fav.bank, fav.position, fav.colour), (0, 0, 4))
        banque = fv.write(self.sd, "SAMPLES", add=fav, apply=True)
        self.assertEqual(banque, "SETTINGS/FAVOURITES/SAMPLES_Bank0.xml")
        texte = (self.root / banque).read_text(encoding="utf-8")
        self.assertIn('\t<favourite\n\t\tposition="0"\n\t\tcolour="4"\n'
                      '\t\tinstrumentPresetFolder="SAMPLES/DRUMS/Kick/a.wav" />',
                      texte)
        self.assertEqual(fv.read(self.sd, "SAMPLES"),
                         [fv.Favourite(0, 0, 4, rel)])
        # L'ancienne banque est gardée ; le second son prend le pad suivant.
        self.assertTrue(list(self.root.glob(
            "_BACKUP/favoris-*/SETTINGS/FAVOURITES/SAMPLES_Bank0.xml")))
        second = fv.plan_add(self.sd, "SAMPLES", "SAMPLES/DRUMS/Kick/b.wav")
        self.assertEqual((second.bank, second.position), (0, 1))
        fv.write(self.sd, "SAMPLES", remove=fv.plan_remove(
            self.sd, "SAMPLES", rel), apply=True)
        self.assertEqual(fv.read(self.sd, "SAMPLES"), [])

    def test_une_banque_pleine_passe_a_la_suivante(self):
        from delugeapp.core import favourites as fv

        lignes = "".join(
            '<favourite position="%d" colour="2" '
            'instrumentPresetFolder="SAMPLES/x%d.wav" />' % (i, i)
            for i in range(16))
        (self.root / "SETTINGS/FAVOURITES/SAMPLES_Bank0.xml").write_text(
            "<favourites>%s</favourites>" % lignes, encoding="utf-8")
        fav = fv.plan_add(self.sd, "SAMPLES", "SAMPLES/DRUMS/Kick/a.wav")
        self.assertEqual((fav.bank, fav.position), (1, 0))

    def test_les_favoris_de_la_machine_deviennent_ceux_de_l_application(self):
        (self.root / "SETTINGS/FAVOURITES/SAMPLES_Bank3.xml").write_text(
            '<favourites><favourite position="5" colour="4" '
            'instrumentPresetFolder="SAMPLES/DRUMS/Kick/b.wav" />'
            '</favourites>', encoding="utf-8")
        scan.scan_card(self.sd, self.lib, compute_hash=False)
        self.assertTrue(self.lib.get_rating(
            "sample", "SAMPLES/DRUMS/Kick/b.wav")["favorite"])
        self.assertFalse(self.lib.get_rating(
            "sample", "SAMPLES/DRUMS/Kick/a.wav")["favorite"])


class TestNouvelleVersion(unittest.TestCase):
    """La page des versions de GitHub, lue seulement sur demande."""

    def test_comparer_les_versions(self):
        from delugeapp.core import updates

        self.assertTrue(updates.is_newer("v1.0.1", "1.0.0"))
        self.assertTrue(updates.is_newer("1.1", "1.0.9"))
        self.assertFalse(updates.is_newer("v1.0.0", "1.0.0"))
        self.assertFalse(updates.is_newer("1.0", "1.0.0"))
        self.assertFalse(updates.is_newer("brouillon", "1.0.0"))

    def test_une_fois_par_jour(self):
        from datetime import datetime

        from delugeapp.core import updates

        maintenant = datetime(2026, 11, 7, 12, 0)
        self.assertTrue(updates.due("", maintenant))
        self.assertTrue(updates.due("2026-11-06T11:00:00", maintenant))
        self.assertFalse(updates.due("2026-11-07T08:00:00", maintenant))

    def test_la_reponse_de_github(self):
        import io
        import json

        from delugeapp.core import updates

        class Reponse(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

        def ouvrir(donnees):
            def opener(requete, timeout):
                self.assertTrue(requete.full_url.endswith(
                    "/repos/Blackminou29/noctiluca/releases/latest"))
                self.assertIn("Noctiluca/", requete.get_header("User-agent"))
                return Reponse(json.dumps(donnees).encode("utf-8"))
            return opener

        sortie = updates.latest_release(opener=ouvrir({
            "tag_name": "v1.2.0", "html_url":
            "https://github.com/Blackminou29/noctiluca/releases/tag/v1.2.0"}))
        self.assertEqual(sortie.version, "1.2.0")
        self.assertIsNone(updates.latest_release(opener=ouvrir(
            {"tag_name": "v9.0.0", "draft": True})))
        self.assertIsNone(updates.latest_release(opener=ouvrir(
            {"tag_name": "v9", "html_url": "https://ailleurs.example/x"})))

        def sans_reseau(requete, timeout):
            raise OSError("pas de réseau")

        self.assertIsNone(updates.latest_release(opener=sans_reseau))

    def test_le_reglage_est_decoche_par_defaut(self):
        from delugeapp.config import Settings

        s = Settings()
        self.assertFalse(s.check_updates)
        relu = Settings.from_dict(dict(s.to_dict(), check_updates=True,
                                       last_update_check="2026-11-07T08:00"))
        self.assertTrue(relu.check_updates)
        self.assertEqual(relu.last_update_check, "2026-11-07T08:00")


class _Reponse:
    """Une réponse de ``urlopen`` : des octets lus par blocs."""

    def __init__(self, data: bytes, url: str = "https://objects.example/x"):
        import io

        self._f = io.BytesIO(data)
        self._url = url

    def read(self, n=-1):
        return self._f.read(n)

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


class TestMiseAJourAutomatique(unittest.TestCase):
    """Télécharger, vérifier et installer une nouvelle version (1.1.0), sur
    la forme des fichiers de la 1.0.3 relevée le 21 novembre 2026 sur l'API
    de GitHub : chacun porte son empreinte SHA-256 (``digest``)."""

    DONNEES = b"Noctiluca 9.9.9 " * 70000           # plus d'un mégaoctet

    def setUp(self):
        import hashlib

        from delugeapp.core import updates

        self.updates = updates
        self.tmp = Path(tempfile.mkdtemp(prefix="noctiluca-maj-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.sha = hashlib.sha256(self.DONNEES).hexdigest()

    def _fichier(self, nom, data=None, sha=None):
        data = self.DONNEES if data is None else data
        return self.updates.Asset(
            nom, self.updates.DOWNLOADS + "v9.9.9/" + nom, len(data),
            sha or self.sha)

    def _ouvrir(self, data=None, url="https://objects.example/x"):
        appels = []

        def opener(requete, timeout):
            appels.append(requete.full_url)
            return _Reponse(self.DONNEES if data is None else data, url)
        opener.appels = appels
        return opener

    def test_les_fichiers_d_une_version(self):
        import json

        base = "https://github.com/Blackminou29/noctiluca/releases/download/"
        bon = "sha256:" + "ab" * 32
        donnees = {"tag_name": "v1.0.3", "html_url": base, "assets": [
            {"name": "Noctiluca-1.0.3-linux-x86_64.AppImage", "size": 151259640,
             "digest": bon, "browser_download_url":
             base + "v1.0.3/Noctiluca-1.0.3-linux-x86_64.AppImage"},
            {"name": "Noctiluca-1.0.3-macos-arm64.dmg", "size": 90841221,
             "digest": bon, "browser_download_url":
             base + "v1.0.3/Noctiluca-1.0.3-macos-arm64.dmg"},
            {"name": "Noctiluca-1.0.3-windows-x64-setup.exe",
             "size": 70858853, "digest": bon.upper().replace("SHA", "sha"),
             "browser_download_url":
             base + "v1.0.3/Noctiluca-1.0.3-windows-x64-setup.exe"},
            # Refusés : sans empreinte, ailleurs, vide, nom piégé.
            {"name": "sans.exe", "size": 9, "browser_download_url":
             base + "v1.0.3/sans.exe"},
            {"name": "ailleurs.exe", "size": 9, "digest": bon,
             "browser_download_url": "https://ailleurs.example/a.exe"},
            {"name": "vide.exe", "size": 0, "digest": bon,
             "browser_download_url": base + "v1.0.3/vide.exe"},
            {"name": "../x.exe", "size": 9, "digest": bon,
             "browser_download_url": base + "v1.0.3/x.exe"},
            {"name": "court.exe", "size": 9, "digest": "sha256:ab",
             "browser_download_url": base + "v1.0.3/court.exe"}]}
        version = self.updates.latest_release(
            opener=lambda r, timeout: _Reponse(
                json.dumps(donnees).encode("utf-8")))
        self.assertEqual(len(version.assets), 3)
        self.assertEqual({a.sha256 for a in version.assets}, {"ab" * 32})
        for genre, suffixe in (("windows", "setup.exe"), ("macos", ".dmg"),
                               ("appimage", ".AppImage")):
            self.assertTrue(self.updates.asset_for(version, genre)
                            .name.endswith(suffixe), genre)
        self.assertIsNone(self.updates.asset_for(version, None))

    def test_ou_l_installation_est_possible(self):
        kind = self.updates.install_kind
        self.assertIsNone(kind("win32", frozen=False), "depuis les sources")
        self.assertEqual(kind("win32", frozen=True), "windows")
        paquet = self.tmp / "Applications" / "Noctiluca.app"
        executable = paquet / "Contents" / "MacOS" / "Noctiluca"
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"")
        self.assertEqual(kind("darwin", True, {}, str(executable)), "macos")
        self.assertEqual(self.updates.app_bundle(executable), paquet.resolve())
        deplace = self.tmp / "AppTranslocation" / "X" / "Noctiluca.app"
        (deplace / "Contents" / "MacOS").mkdir(parents=True)
        self.assertIsNone(kind("darwin", True, {}, str(
            deplace / "Contents" / "MacOS" / "Noctiluca")))
        self.assertIsNone(kind("darwin", True, {}, str(self.tmp / "noct")))
        image = self.tmp / "Noctiluca.AppImage"
        image.write_bytes(b"")
        self.assertEqual(kind("linux", True, {"APPIMAGE": str(image)}),
                         "appimage")
        self.assertIsNone(kind("linux", True, {}), "l'archive Linux")

    def test_le_telechargement_est_verifie(self):
        updates = self.updates
        fichier = self._fichier("Noctiluca-9.9.9-windows-x64-setup.exe")
        cible = self.tmp / fichier.name
        avance = []
        updates.download(fichier, cible, avance.append, opener=self._ouvrir())
        self.assertEqual(cible.read_bytes(), self.DONNEES)
        self.assertTrue(avance and avance[-1].total >= 1)
        self.assertEqual(avance[-1].current, avance[-1].total)
        # Déjà là et juste : pas une seconde fois.
        refuse = self._ouvrir()
        updates.download(fichier, cible, opener=refuse)
        self.assertEqual(refuse.appels, [])
        # Une empreinte fausse, un fichier trop long ou trop court, un
        # arrêt, une adresse en clair : rien ne reste.
        for nom, f, ouvrir, arret in (
                ("empreinte", self._fichier("a.exe", sha="0" * 64),
                 self._ouvrir(), None),
                ("trop long", self._fichier("b.exe", data=b"x" * 10),
                 self._ouvrir(), None),
                ("trop court", self._fichier("c.exe", data=self.DONNEES + b"!"),
                 self._ouvrir(), None),
                ("arrêt", self._fichier("d.exe"), self._ouvrir(),
                 lambda: True),
                ("en clair", self._fichier("e.exe"),
                 self._ouvrir(url="http://objects.example/x"), None)):
            with self.subTest(nom):
                with self.assertRaises(updates.UpdateError):
                    updates.download(f, self.tmp / f.name, should_stop=arret,
                                     opener=ouvrir)
                self.assertEqual(sorted(p.name for p in self.tmp.iterdir()),
                                 [cible.name])
        ailleurs = updates.Asset("x.exe", "https://ailleurs.example/x.exe",
                                 10, self.sha)
        with self.assertRaises(updates.UpdateError):
            updates.download(ailleurs, self.tmp / "x.exe", opener=self._ouvrir())

    def test_preparer_pour_chaque_systeme(self):
        import os
        from unittest import mock

        updates = self.updates
        version = updates.Release("9.9.9", "https://github.com/x")
        with mock.patch.object(updates, "download_folder",
                               return_value=self.tmp / "telecharges"):
            pret = updates.prepare(
                version, self._fichier("Noctiluca-9.9.9-windows-x64-setup.exe"),
                "windows", opener=self._ouvrir())
        self.assertEqual((pret.kind, pret.version, pret.target),
                         ("windows", "9.9.9", None))
        self.assertEqual(pret.file.read_bytes(), self.DONNEES)

        image = self.tmp / "Noctiluca-1.1.0-linux-x86_64.AppImage"
        image.write_bytes(b"ancienne")
        pret = updates.prepare(
            version, self._fichier("Noctiluca-9.9.9-linux-x86_64.AppImage"),
            "appimage", opener=self._ouvrir(), environ={"APPIMAGE": str(image)})
        self.assertEqual(pret.target, image)
        self.assertEqual(pret.file.parent, image.parent, "même disque")
        self.assertTrue(pret.file.name.startswith("."))
        self.assertEqual(image.read_bytes(), b"ancienne", "rien de remplacé")
        if os.name == "posix":
            self.assertTrue(os.access(pret.file, os.X_OK))

        paquet = self.tmp / "Apps" / "Noctiluca.app"
        (paquet / "Contents" / "MacOS").mkdir(parents=True)
        commandes = []

        def run(cmd, check=False, timeout=None):
            commandes.append(cmd[0] + " " + cmd[1])
            if cmd[:2] == ["hdiutil", "attach"]:
                monte = Path(cmd[cmd.index("-mountpoint") + 1])
                (monte / "Noctiluca.app" / "Contents").mkdir(parents=True)
                (monte / "Noctiluca.app" / "Contents" / "neuf").write_text("9")
            elif cmd[0] == "ditto":
                shutil.copytree(cmd[1], cmd[2])
            return None

        with mock.patch.object(updates, "download_folder",
                               return_value=self.tmp / "telecharges"):
            pret = updates.prepare(
                version, self._fichier("Noctiluca-9.9.9-macos-arm64.dmg"),
                "macos", opener=self._ouvrir(),
                executable=str(paquet / "Contents" / "MacOS" / "Noctiluca"),
                run=run)
        self.assertEqual(commandes, ["hdiutil attach", "ditto " + str(
            Path(commandes[1].split(" ", 1)[1])), "hdiutil detach"])
        self.assertEqual(pret.target, paquet.resolve())
        self.assertEqual((pret.file / "Contents" / "neuf").read_text(), "9")
        self.assertTrue(pret.file.name.startswith(".Noctiluca-9.9.9"))

        def sans_application(cmd, check=False, timeout=None):
            return None

        with mock.patch.object(updates, "download_folder",
                               return_value=self.tmp / "telecharges"), \
                self.assertRaises(updates.UpdateError):
            updates.prepare(
                version, self._fichier("Noctiluca-9.9.9-macos-arm64.dmg"),
                "macos", opener=self._ouvrir(),
                executable=str(paquet / "Contents" / "MacOS" / "Noctiluca"),
                run=sans_application)

    def test_lancer_l_installation(self):
        updates = self.updates
        ouverts, lances = [], []
        installateur = self.tmp / "setup.exe"
        updates.launch(updates.Pending("windows", installateur, None, "9.9.9"),
                       pid=42, startfile=lambda p, arguments: ouverts.append(
                           (p, arguments)))
        self.assertEqual(ouverts, [(str(installateur), "/S /RELANCER")])
        for genre in ("appimage", "macos"):
            updates.launch(updates.Pending(genre, self.tmp / "neuve",
                                           self.tmp / "actuelle", "9.9.9"),
                           pid=42, popen=lambda cmd, **k: lances.append(
                               (cmd, k)))
            cmd, options = lances[-1]
            self.assertEqual(cmd[:3], ["/bin/sh", "-c",
                                       updates.SCRIPTS[genre]])
            self.assertEqual(cmd[4:], ["42", str(self.tmp / "neuve"),
                                       str(self.tmp / "actuelle")])
            self.assertTrue(options["start_new_session"])
        with self.assertRaises(updates.UpdateError):
            updates.launch(updates.Pending("ailleurs", self.tmp / "x", None,
                                           "9"), pid=42)

    @unittest.skipUnless(sys.platform != "win32" and Path("/bin/sh").exists(),
                         "les scripts de macOS et de Linux")
    def test_les_scripts_remplacent_puis_relancent(self):
        """Pour de vrai : chaque script attend la fin du processus, échange
        les fichiers, puis relance — ici, un témoin à la place de la
        relance ; et l'ancienne application revient si l'échange échoue."""
        import subprocess
        import time

        updates = self.updates
        temoin = self.tmp / "relancee"
        neuve = self.tmp / ".neuve.AppImage"
        neuve.write_text("#!/bin/sh\necho neuve > '%s'\n" % temoin)
        neuve.chmod(0o755)
        actuelle = self.tmp / "Noctiluca.AppImage"
        actuelle.write_text("ancienne")
        attente = subprocess.Popen(["sleep", "0.5"])
        updates.launch(updates.Pending("appimage", neuve, actuelle, "9"),
                       pid=attente.pid)
        self.assertEqual(actuelle.read_text(), "ancienne",
                         "rien avant la fin du processus")
        attente.wait()
        for _ in range(100):
            if temoin.exists():
                break
            time.sleep(0.05)
        self.assertEqual(temoin.read_text().strip(), "neuve")
        self.assertFalse(neuve.exists())
        self.assertIn("echo neuve", actuelle.read_text())

        script = updates.SCRIPTS["macos"].replace(
            'open "$3"', 'touch "$3/relancee"')
        paquet = self.tmp / "Noctiluca.app"
        (paquet / "Contents").mkdir(parents=True)
        (paquet / "Contents" / "v").write_text("1.1.0")
        nouveau = self.tmp / ".Noctiluca-9.app"
        (nouveau / "Contents").mkdir(parents=True)
        (nouveau / "Contents" / "v").write_text("9")
        fini = subprocess.Popen(["true"])
        fini.wait()
        subprocess.run(["/bin/sh", "-c", script, "x", str(fini.pid),
                        str(nouveau), str(paquet)], check=True, timeout=20)
        self.assertEqual((paquet / "Contents" / "v").read_text(), "9")
        self.assertTrue((paquet / "relancee").exists())
        self.assertFalse(nouveau.exists())
        self.assertFalse(Path(str(paquet) + ".ancien").exists())
        # La nouvelle absente : l'ancienne reste, et se rouvre.
        subprocess.run(["/bin/sh", "-c", script, "x", str(fini.pid),
                        str(self.tmp / "absente.app"), str(paquet)],
                       check=True, timeout=20)
        self.assertEqual((paquet / "Contents" / "v").read_text(), "9")


class TestFirmwareDuDeluge(unittest.TestCase):
    """Préparer la carte pour une mise à jour du firmware, sur la forme des
    versions publiées relevée le 8 novembre 2026 (API GitHub)."""

    BIN = bytes(range(256)) * 1400            # 350 Ko, dans les tailles sûres

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "carte"
        for sub in ("SONGS", "SYNTHS", "KITS", "SAMPLES"):
            (self.root / sub).mkdir(parents=True)
        (self.root / "deluge-c1_2_1.bin").write_bytes(b"ancien" * 60000)
        self.sd = sdcard.SDCard(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def _archive(self, *noms) -> bytes:
        """Comme ``v1.3.0.zip`` : le .bin, un README, et les parasites que
        macOS y laisse — dont un ``._deluge-c1_3_0.bin``."""
        import io
        import zipfile

        tampon = io.BytesIO()
        with zipfile.ZipFile(tampon, "w") as z:
            z.writestr("v1.3.0/", b"")
            z.writestr("v1.3.0/.DS_Store", b"x" * 64)
            z.writestr("v1.3.0/README.txt", b"Deluge Community Firmware")
            z.writestr("__MACOSX/v1.3.0/._deluge-c1_3_0.bin", b"y" * 213)
            for nom in noms or ("v1.3.0/deluge-c1_3_0.bin",):
                z.writestr(nom, self.BIN)
        return tampon.getvalue()

    def test_les_versions(self):
        from delugeapp.core import firmware

        for texte, version in (("deluge-c1_3_0.bin", "1.3.0"),
                               ("c1.3.0", "1.3.0"), ("v1.3.0", "1.3.0"),
                               ("release_1_2_1", "1.2.1"),
                               ("release_1_0", "1.0.0"),
                               ("deluge-v1_3_0-beta+2026_10_18-102cf9f.bin",
                                "1.3.0"), ("nightly", "")):
            self.assertEqual(firmware.version_of(texte), version, texte)
        self.assertTrue(firmware.is_newer("v1.3.0", "c1.2.1"))
        self.assertFalse(firmware.is_newer("v1.3.0", "c1.3.0"))
        self.assertFalse(firmware.is_newer("nightly", "c1.2.1"))
        self.assertTrue(firmware.is_newer("v1.3.0", ""))
        self.assertEqual(firmware.card_version(self.sd), "1.2.1")

    def test_seule_la_derniere_version_stable_est_proposee(self):
        import json

        from delugeapp.core import firmware

        def actif(nom, taille=1000):
            return {"name": nom, "size": taille, "browser_download_url":
                    "https://github.com/SynthstromAudible/DelugeFirmware/"
                    "releases/download/x/" + nom}

        publiees = [
            {"tag_name": "nightly", "prerelease": True, "draft": False,
             "html_url": "https://github.com/x/nightly",
             "assets": [actif("nightly.zip")]},
            {"tag_name": "v1.3.0", "prerelease": False, "draft": False,
             "html_url": "https://github.com/x/v1.3.0",
             "assets": [actif("deluge-c1_3_0_here_for_debugging_only.elf"),
                        actif("v1.3.0.zip", 1174373)]},
            {"tag_name": "v1.3.0-rc2", "prerelease": True, "draft": False,
             "html_url": "https://github.com/x/rc2",
             "assets": [actif("deluge-v1_3_0-rc+2026_10_19-465a309.bin")]},
            {"tag_name": "release_1_2_1", "prerelease": False, "draft": False,
             "html_url": "https://github.com/x/121",
             "assets": [actif("deluge-community-release-1_2_1.zip")]},
            {"tag_name": "release_1_0", "prerelease": False, "draft": False,
             "html_url": "https://github.com/x/100",
             "assets": [actif("deluge-c1_0_0.bin")]},
        ]

        class Reponse:
            def __init__(self, corps):
                self.corps = corps

            def read(self, _n=-1):
                return self.corps

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

        def ouvrir(requete, timeout):
            self.assertIn("SynthstromAudible/DelugeFirmware",
                          requete.full_url)
            return Reponse(json.dumps(publiees).encode("utf-8"))

        sortie = firmware.latest_release(opener=ouvrir)
        self.assertEqual((sortie.version, sortie.asset, sortie.size),
                         ("1.3.0", "v1.3.0.zip", 1174373))

        def sans_reseau(requete, timeout):
            raise OSError("pas de réseau")

        self.assertIsNone(firmware.latest_release(opener=sans_reseau))

    def test_le_bin_sort_de_l_archive_sans_ses_parasites(self):
        from delugeapp.core import firmware

        nom, contenu = firmware.firmware_from(self._archive(), "v1.3.0.zip")
        self.assertEqual((nom, contenu), ("deluge-c1_3_0.bin", self.BIN))
        with self.assertRaises(ValueError):          # deux firmwares
            firmware.firmware_from(self._archive(
                "v1.3.0/deluge-c1_3_0.bin", "autre/deluge-c1_2_1.bin"), "x.zip")
        with self.assertRaises(ValueError):          # aucun
            firmware.firmware_from(self._archive("v1.3.0/notes.txt"), "x.zip")
        with self.assertRaises(ValueError):          # vide : 7 segments en danger
            firmware.firmware_from(b"", "deluge-c1_0_0.bin")
        with self.assertRaises(ValueError):          # 3,5 Mo
            firmware.firmware_from(b"\0" * (3_500_000), "deluge-c9.bin")
        self.assertEqual(firmware.firmware_from(self.BIN, "deluge-c1_0_0.bin"),
                         ("deluge-c1_0_0.bin", self.BIN))

    def test_la_pose_range_l_ancien_et_ne_laisse_qu_un_bin(self):
        from delugeapp.core import firmware

        ancien = (self.root / "deluge-c1_2_1.bin").read_bytes()
        plan = firmware.plan_install(self.sd, "deluge-c1_3_0.bin", self.BIN)
        self.assertEqual(plan.retired, ["deluge-c1_2_1.bin"])
        self.assertTrue(plan.backup.startswith("_BACKUP/firmware-"))
        # Le plan n'écrit rien.
        self.assertEqual([p.name for p in self.sd.firmware_files()],
                         ["deluge-c1_2_1.bin"])
        firmware.install(self.sd, plan)
        self.assertEqual([p.name for p in self.sd.firmware_files()],
                         ["deluge-c1_3_0.bin"])
        self.assertEqual((self.root / "deluge-c1_3_0.bin").read_bytes(),
                         self.BIN)
        self.assertEqual((self.root / plan.backup / "deluge-c1_2_1.bin")
                         .read_bytes(), ancien)
        self.assertEqual(list(self.root.glob("*.noct-tmp")), [])
        # La sauvegarde ne voyage pas vers la carte.
        from delugeapp.core import cardsync
        self.assertTrue(cardsync.is_junk(plan.backup + "/deluge-c1_2_1.bin"))

    def test_un_telechargement_incomplet_est_refuse(self):
        from delugeapp.core import firmware

        class Reponse:
            def read(self, _n=-1):
                return b"tronque"

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

        version = firmware.FirmwareRelease("1.3.0", "v1.3.0", "v1.3.0.zip",
                                           "https://github.com/x", "", 999)
        with self.assertRaises(OSError):
            firmware.download(version, opener=lambda r, timeout: Reponse())
