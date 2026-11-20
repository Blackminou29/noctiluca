# -*- coding: utf-8 -*-
"""Tests du noyau de Noctiluca : le format du Deluge et la bibliothèque.

La virgule fixe, la réparation des XML, les notes, le tempo, les
presets, les morceaux, la carte, les WAV, l'index et l'analyse, les
dépendances, le rangement, la santé, les sauvegardes, les unités, le
dossier de configuration, l'ancien nom, l'export MIDI et les audits.
Les autres thèmes du noyau ont leur fichier : ``test_generateurs``,
``test_ecoute``, ``test_outils_audio``, ``test_deluge``, ``test_daw``.

Ces tests s'exécutent **sans carte SD** : chacun fabrique au besoin une carte
factice dans un dossier temporaire (cf. SPEC §7). Ils n'importent jamais Qt,
ce qui permet de les lancer sur une machine sans affichage :

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
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

from delugeapp.core import (analysis, backup, db, deps, dxml, genres, health,
                            midifile, organize, render, rhythm, samplefix,
                            scan, sdcard, songpack, synthgen, theory, units,
                            wav, fixedpoint)
from delugeapp.core.fixedpoint import (INT32_MAX, INT32_MIN, format_fixed,
                                       from_display, from_unit, parse_fixed,
                                       to_display, to_unit)
from delugeapp.core.model import (Kit, Note, Song, Sound, SynthPreset,
                                  decode_notes, encode_notes,
                                  tempo_from_song_attrs)

import sys as _sys                                           # noqa: E402

# Les aides partagées (``tests/aides_coeur.py``), par leur nom : ``unittest
# discover -s tests`` charge les modules à plat, pytest en paquet.
_DOSSIER = str(Path(__file__).resolve().parent)
if _DOSSIER not in _sys.path:
    _sys.path.insert(0, _DOSSIER)
from aides_coeur import _SortieFactice, _son, lire_midi  # noqa: E402
class TestFixedPoint(unittest.TestCase):
    """Conversions des paramètres en virgule fixe."""

    def test_bornes_connues(self):
        """Les trois bornes documentées doivent se lire exactement."""
        self.assertEqual(parse_fixed("0x80000000"), INT32_MIN)
        self.assertEqual(parse_fixed("0x00000000"), 0)
        self.assertEqual(parse_fixed("0x7FFFFFFF"), INT32_MAX)

    def test_affichage_unipolaire(self):
        """L'écran du Deluge affiche 0 à 50 (SPEC §1.4)."""
        self.assertEqual(to_display(INT32_MIN), 0)
        self.assertEqual(to_display(INT32_MAX), 50)
        self.assertEqual(to_display(0), 25)

    def test_aller_retour_hexadecimal(self):
        """``format_fixed`` puis ``parse_fixed`` doit rendre la valeur d'origine."""
        for value in (INT32_MIN, -1234567, 0, 1, 987654321, INT32_MAX):
            with self.subTest(value=value):
                self.assertEqual(parse_fixed(format_fixed(value)), value)

    def test_aller_retour_unitaire(self):
        """La conversion en flottant [0,1] doit être stable au bit près."""
        for value in (INT32_MIN, -5, 0, 5, INT32_MAX):
            with self.subTest(value=value):
                self.assertAlmostEqual(from_unit(to_unit(value)), value, delta=2)

    def test_aller_retour_affichage(self):
        """Chaque cran 0..50 doit se retrouver après conversion."""
        for disp in range(51):
            with self.subTest(disp=disp):
                self.assertEqual(to_display(from_display(disp)), disp)

    def test_valeur_illisible(self):
        """Une valeur invalide ne lève pas : elle retombe sur le défaut."""
        self.assertEqual(parse_fixed("pas un nombre", default=42), 42)
        self.assertEqual(parse_fixed(None, default=7), 7)


# --------------------------------------------------------------------------- #
# Réparation XML (SPEC §1.3)
# --------------------------------------------------------------------------- #

class TestXMLRepair(unittest.TestCase):
    """Les trois anomalies réellement présentes sur la carte."""

    def test_document_multi_racines(self):
        """Firmware 2.x : ``<firmwareVersion>`` est frère de ``<sound>``."""
        raw = (b'<?xml version="1.0" encoding="UTF-8"?>\n'
               b'<firmwareVersion>2.0.0-beta</firmwareVersion>\n'
               b'<earliestCompatibleFirmware>2.0.0</earliestCompatibleFirmware>\n'
               b'<sound><osc1><type>saw</type></osc1></sound>\n')
        doc = dxml.loads(raw)
        self.assertEqual(doc.root.tag, "sound")
        self.assertEqual(doc.preamble.get("firmwareVersion"), "2.0.0-beta")
        self.assertEqual(doc.firmware, "2.0.0-beta")
        osc1 = dxml.get_child(doc.root, "osc1")
        self.assertIsNotNone(osc1)
        self.assertEqual(dxml.get(osc1, "type"), "saw")

    def test_esperluette_non_echappee(self):
        """``&`` nu dans un attribut : cas réel des saxophones de la carte."""
        raw = (b'<sound><osc1 fileName="SAMPLES/Tenor & Alto Sax G2.wav" />'
               b'</sound>')
        doc = dxml.loads(raw)
        osc1 = dxml.get_child(doc.root, "osc1")
        self.assertIsNotNone(osc1)
        self.assertEqual(dxml.get(osc1, "fileName"),
                         "SAMPLES/Tenor & Alto Sax G2.wav")

    def test_octets_non_utf8(self):
        """Nom de périphérique MIDI avec des octets illégaux."""
        raw = b'<song><device name="\xff\xfe bidule" /></song>'
        doc = dxml.loads(raw)
        self.assertEqual(doc.root.tag, "song")
        device = dxml.get_child(doc.root, "device")
        self.assertIsNotNone(device)
        self.assertIn("bidule", dxml.get(device, "name") or "")

    def test_nom_d_appareil_en_octets_ff_est_une_forme_du_firmware(self):
        """Le nom d'un contrôleur MIDI appris, tel que la 1.3.0 l'enregistre.

        Forme relevée dans ``SONGS/ATELIER AMBIENT.XML`` (7 novembre 2026) :
        ce n'est pas un fichier abîmé, et il ne doit plus passer pour tel.
        """
        raw = (b'<song><midiKnobs><midiKnob channel="11" ccNumber="13"\n'
               b'\t\trelative="0"\n\t\tcontrolsParam="hpfFrequency">\n'
               b'\t\t<device\n\t\t\tname="' + b"\xff" * 32 + b'"\n'
               b'\t\t\tvendorId="0x1235"\n\t\t\tproductId="0x0061" />\n'
               b'</midiKnob></midiKnobs></song>')
        doc = dxml.loads(raw)
        self.assertEqual(doc.repaired, [dxml.FIRMWARE_QUIRKS[0]])
        device = doc.root.find(".//device")
        self.assertEqual(device.get("name"), "")
        self.assertEqual(device.get("vendorId"), "0x1235")

    def test_balises_numeriques_de_la_beta_1_3(self):
        """Le ``<performanceView>`` de la bêta : ``<8>128</8>``, illégal en XML.

        Lu jusqu'ici par l'analyseur de dernier recours, qui le déclarait
        « reconstruit » : cinq morceaux de l'utilisateur, tous écrits par la
        machine.
        """
        raw = (b'<song><performanceView><defaultFXValues><FX1>'
               b'<param>none</param><row>\n\t<8>128</8>\n\t<7>110</7>\n'
               b'\t<1>0</1>\n</row><hold><status>Off</status><row>255</row>'
               b'</hold></FX1></defaultFXValues></performanceView>'
               b'<instruments /></song>')
        doc = dxml.loads(raw)
        self.assertEqual(doc.repaired, [dxml.FIRMWARE_QUIRKS[1]])
        row = doc.root.find(".//FX1/row")
        self.assertEqual([(c.tag, c.text) for c in row],
                         [("n8", "128"), ("n7", "110"), ("n1", "0")])
        self.assertEqual(doc.root.find(".//hold/row").text, "255")

    def test_les_trois_anomalies_ensemble(self):
        """Un fichier cumulant les trois défauts doit rester lisible."""
        raw = (b'<?xml version="1.0" encoding="UTF-8"?>\n'
               b'<firmwareVersion>2.1.0</firmwareVersion>\n'
               b'<sound name="Sax \xff">'
               b'<osc1 fileName="SAMPLES/A & B.wav"><type>sample</type></osc1>'
               b'</sound>')
        doc = dxml.loads(raw)
        self.assertEqual(doc.root.tag, "sound")
        self.assertEqual(doc.firmware, "2.1.0")
        self.assertTrue(doc.repaired, "les réparations doivent être signalées")
        osc1 = dxml.get_child(doc.root, "osc1")
        self.assertEqual(dxml.get(osc1, "fileName"), "SAMPLES/A & B.wav")

    def test_dialectes_detectes(self):
        """Le dialecte d'origine doit être reconnu dans les deux sens."""
        attr = dxml.loads(b'<sound><osc1 type="saw" transpose="0" /></sound>')
        elem = dxml.loads(b'<sound><osc1><type>saw</type></osc1></sound>')
        self.assertEqual(attr.dialect, "attr")
        self.assertEqual(elem.dialect, "elem")
        # L'accès est indifférent au dialecte.
        for doc in (attr, elem):
            self.assertEqual(dxml.get(dxml.get_child(doc.root, "osc1"), "type"),
                             "saw")


# --------------------------------------------------------------------------- #
# Notes (SPEC §1.6)
# --------------------------------------------------------------------------- #

class TestNotes(unittest.TestCase):
    """Décodage et encodage des blobs de notes."""

    def test_blob_20_caracteres(self):
        """``noteData`` : pos(8) longueur(8) vélocité(2) condition(2)."""
        blob = "0x" + "00000000" + "00000018" + "40" + "14"
        notes = decode_notes(blob, with_lift=False)
        self.assertEqual(len(notes), 1)
        n = notes[0]
        self.assertEqual((n.pos, n.length, n.velocity, n.condition),
                         (0, 24, 0x40, 20))
        self.assertEqual(n.probability, 1.0)

    def test_blob_22_caracteres(self):
        """``noteDataWithLift`` insère le lift AVANT la condition.

        Mesuré sur les 403 notes de la carte munies d'un lift : l'octet en
        position 18-20 vaut 0x40 pour 100 % d'entre elles (c'est le lift, dont
        la valeur par défaut est 64), tandis que celui en position 20-22 vaut
        0x14 pour 92,8 % (c'est la condition « toujours »), le reste étant des
        probabilités et une itération. La disposition réelle est donc
        ``pos(8) length(8) velocity(2) lift(2) condition(2)``.
        """
        blob = "0x" + "00000060" + "0000000C" + "7F" + "40" + "14"
        notes = decode_notes(blob, with_lift=True)
        self.assertEqual(len(notes), 1)
        n = notes[0]
        self.assertEqual((n.pos, n.length, n.velocity, n.lift, n.condition),
                         (96, 12, 127, 0x40, 20))

    def test_plusieurs_notes(self):
        """Un blob contient autant de notes que de groupes de 22 caractères."""
        one = "000000600000000C7F4014"
        notes = decode_notes("0x" + one * 4, with_lift=True)
        self.assertEqual(len(notes), 4)

    def test_aller_retour(self):
        """``encode_notes`` puis ``decode_notes`` doit rendre les mêmes notes."""
        original = [
            Note(pos=0, length=24, velocity=64, condition=20, lift=64),
            Note(pos=96, length=48, velocity=127, condition=10, lift=32),
            Note(pos=288, length=12, velocity=1, condition=0x86, lift=127),
        ]
        for with_lift in (True, False):
            with self.subTest(with_lift=with_lift):
                again = decode_notes(encode_notes(original, with_lift),
                                     with_lift)
                self.assertEqual(len(again), len(original))
                for a, b in zip(original, again):
                    self.assertEqual((a.pos, a.length, a.velocity, a.condition),
                                     (b.pos, b.length, b.velocity, b.condition))
                    if with_lift:
                        self.assertEqual(a.lift, b.lift)

    def test_probabilite(self):
        """Condition < 20 = probabilité par pas de 5 %."""
        self.assertEqual(Note(condition=20).probability, 1.0)
        self.assertAlmostEqual(Note(condition=10).probability, 0.5)
        self.assertTrue(Note(condition=0x86).is_iteration)

    def test_blob_invalide(self):
        """Un blob tronqué ou absurde ne lève pas."""
        for blob in (None, "", "0x", "0xZZZZ", "0x1234"):
            with self.subTest(blob=blob):
                self.assertIsInstance(decode_notes(blob, True), list)


# --------------------------------------------------------------------------- #
# Tempo (SPEC §4.5)
# --------------------------------------------------------------------------- #

class TestTempo(unittest.TestCase):
    """Calcul du tempo à partir des attributs d'horloge."""

    def test_defaut_usine(self):
        """``DEFAULT.XML`` de la carte réelle vaut 120 BPM."""
        self.assertAlmostEqual(
            tempo_from_song_attrs(229, -1342177280, 2), 120.0, places=2)

    def test_fraction_non_signee(self):
        """La fraction est non signée ; la lire signée fausse le résultat.

        Valeurs relevées sur ``Nimp1.XML`` (122 BPM sur la machine). Lue en
        signé, la même entrée donnerait 122,08 BPM.
        """
        self.assertAlmostEqual(
            tempo_from_song_attrs(225, -334444175, 2), 122.0, places=3)

    def test_valeurs_reelles_de_la_carte(self):
        """Triplets relevés sur la carte, et leur tempo affiché par le Deluge.

        Les 46 morceaux de la carte donnent tous un BPM entier avec cette
        formule, ce qui ne serait pas le cas avec 48 ticks par noire.
        """
        cas = [
            ((510, 1789569707, 1), 108.0),
            ((459, 1610612736, 1), 120.0),
            ((765, -1610612736, 1), 72.0),
            ((492, 805306368, 1), 112.0),
            ((222, 1194970740, 2), 124.0),
            ((798, -373475417, 1), 69.0),
        ]
        for args, attendu in cas:
            with self.subTest(args=args):
                self.assertAlmostEqual(tempo_from_song_attrs(*args),
                                       attendu, places=3)

    def test_repli_hors_bornes(self):
        """Un calcul absurde retombe sur 120 BPM plutôt que de propager."""
        self.assertEqual(tempo_from_song_attrs(0, 0, 0), 120.0)
        self.assertEqual(tempo_from_song_attrs(1, 0, 0), 120.0)
        self.assertEqual(tempo_from_song_attrs("x", None, 2), 120.0)


# --------------------------------------------------------------------------- #
# Presets et kits
# --------------------------------------------------------------------------- #

class TestPresets(unittest.TestCase):
    """Lecture et écriture des presets : le fichier réécrit doit se relire."""

    def test_preset_neuf_est_jouable(self):
        """``SynthPreset.new`` doit produire un son audible et cohérent."""
        preset = SynthPreset.new("TEST")
        self.assertEqual(preset.sound.name, "TEST")
        self.assertTrue(preset.sound.osc1.is_audible)
        self.assertIn(preset.sound.mode, ("subtractive", "fm", "ringmod"))

    def test_aller_retour_preset(self):
        """Écrire puis relire un preset doit conserver tous les champs clés."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "TEST.XML"
            preset = SynthPreset.new("MON SON")
            preset.sound.osc1.type = "saw"
            preset.sound.osc2.type = "square"
            preset.sound.osc2.transpose = -12
            preset.sound.lpf_mode = "24dB"
            preset.sound.set_param("lpfFrequency", 123456789)
            preset.sound.env1.attack = -1000000
            preset.save(path, backup=False)

            again = SynthPreset.load(path)
            self.assertEqual(again.sound.osc1.type, "saw")
            self.assertEqual(again.sound.osc2.type, "square")
            self.assertEqual(again.sound.osc2.transpose, -12)
            self.assertEqual(again.sound.lpf_mode, "24dB")
            self.assertEqual(again.sound.param("lpfFrequency"), 123456789)
            self.assertEqual(again.sound.env1.attack, -1000000)

    def test_double_aller_retour_est_stable(self):
        """Deux écritures successives doivent donner un fichier identique."""
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "A.XML"
            second = Path(tmp) / "B.XML"
            SynthPreset.new("STABLE").save(first, backup=False)
            SynthPreset.load(first).save(second, backup=False)
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_sauvegarde_bak(self):
        """Une écriture avec ``backup=True`` conserve l'ancienne version."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "TEST.XML"
            SynthPreset.new("UN").save(path, backup=False)
            preset = SynthPreset.load(path)
            preset.sound.name = "DEUX"
            preset.save(path, backup=True)
            baks = list(Path(tmp).glob("*.bak"))
            self.assertEqual(len(baks), 1, "une sauvegarde .bak est attendue")

    def test_kit_neuf(self):
        """Un kit créé puis relu conserve ses rangées."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "KIT.XML"
            kit = Kit.new("MON KIT")
            kit.add_row("KICK", "SAMPLES/DRUMS/Kick/k.wav")
            kit.add_row("SNARE", "SAMPLES/DRUMS/Snare/s.wav")
            kit.save(path, backup=False)

            again = Kit.load(path)
            self.assertEqual(len(again.rows), 2)
            self.assertIn("SAMPLES/DRUMS/Kick/k.wav", again.sample_paths())


# --------------------------------------------------------------------------- #
# Morceaux
# --------------------------------------------------------------------------- #

class TestSong(unittest.TestCase):
    """Lecture d'un morceau de synthèse."""

    SONG = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<song firmwareVersion="3.0.4" timePerTimerTick="459"'
        ' timerTickFraction="1610612736" inputTickMagnitude="1" rootNote="69"'
        ' swingAmount="12" swingInterval="7" previewNumPads="144">'
        '<modeNotes><modeNote>0</modeNote><modeNote>2</modeNote>'
        '<modeNote>3</modeNote><modeNote>5</modeNote><modeNote>7</modeNote>'
        '<modeNote>8</modeNote><modeNote>10</modeNote></modeNotes>'
        '<instruments>'
        '<sound presetName="BASSE" presetFolder="SYNTHS/Basses" />'
        '<kit presetName="BATTERIE" presetFolder="KITS" />'
        '</instruments>'
        '<sessionClips>'
        '<instrumentClip length="384" section="0" instrumentPresetName="BASSE"'
        ' instrumentPresetFolder="SYNTHS/Basses">'
        '<noteRows>'
        '<noteRow y="60" noteDataWithLift="0x'
        '0000000000000018401400000000600000001840140" />'
        '</noteRows></instrumentClip>'
        '</sessionClips></song>'
    ).encode("utf-8")

    def _song(self) -> Song:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "MORCEAU.XML"
            path.write_bytes(self.SONG)
            return Song.load(path)

    def test_lecture(self):
        """Les champs principaux doivent être lus correctement."""
        song = self._song()
        self.assertEqual(song.name, "MORCEAU")
        self.assertAlmostEqual(song.tempo_bpm, 120.0, places=1)
        self.assertEqual(song.root_note, 69)
        self.assertEqual(song.swing_amount, 12)
        self.assertEqual(len(song.instruments), 2)
        self.assertEqual(len(song.clips), 1)

    def test_nom_de_gamme(self):
        """rootNote 69 (La) + intervalles mineurs = « La mineur »."""
        self.assertEqual(self._song().scale_name(), "La mineur")

    def test_statistiques(self):
        """Le clip de 384 ticks fait **2** mesures à magnitude 1.

        Ce test affirmait 4, d'après la SPEC qui comptait 96 ticks par
        mesure. Le firmware en compte ``96 << inputTickMagnitude``
        (``Song::getBarLength``) : 192 ici. Mesuré sur les 40 morceaux 3.0.4
        de la carte, dont la double croche vaut 12 ticks.
        """
        stats = self._song().stats()
        self.assertEqual(stats["clips"], 1)
        self.assertEqual(stats["bars"], 2.0)
        self.assertEqual(stats["instruments"], 2)

    def test_la_resolution_suit_la_magnitude(self):
        """Une mesure vaut 96 << inputTickMagnitude ticks."""
        from delugeapp.core.model import ticks_per_bar

        self.assertEqual([ticks_per_bar(m) for m in (0, 1, 2, 3)],
                         [96, 192, 384, 768])
        song = self._song()
        self.assertEqual(song.input_tick_magnitude, 1)
        self.assertEqual(song.clips[0].ticks_per_bar, 192)

    def test_un_morceau_c1_2_1_compte_384_ticks_par_mesure(self):
        """Le format de la machine : magnitude 2, 1 536 ticks = 4 mesures."""
        texte = self.SONG.decode("utf-8").replace(
            'inputTickMagnitude="1"', 'inputTickMagnitude="2"').replace(
            'timePerTimerTick="459"', 'timePerTimerTick="229"').replace(
            'timerTickFraction="1610612736"',
            'timerTickFraction="-1342177280"').replace(
            'length="384"', 'length="1536"')
        with tempfile.TemporaryDirectory() as tmp:
            chemin = Path(tmp) / "C121.XML"
            chemin.write_text(texte, encoding="utf-8")
            song = Song.load(chemin)
        self.assertAlmostEqual(song.tempo_bpm, 120.0, places=1)
        self.assertEqual(song.clips[0].bars, 4.0)
        self.assertEqual(song.stats()["bars"], 4.0)

    def test_presets_references(self):
        """Les presets utilisés doivent être retrouvés sans doublon."""
        refs = self._song().preset_refs()
        noms = {nom for _k, nom, _f in refs}
        self.assertIn("BASSE", noms)
        self.assertIn("BATTERIE", noms)

    def test_vignette(self):
        """La vignette est toujours une matrice 8x18, même sans données."""
        grid = self._song().preview_colors()
        self.assertEqual(len(grid), 8)
        self.assertTrue(all(len(row) == 18 for row in grid))

    def test_la_vignette_commence_par_la_rangee_du_bas(self):
        """Le firmware écrit d'abord la rangée du bas : allumée seule, elle
        doit finir en dernière ligne de la matrice, qui se dessine de haut
        en bas."""
        song = self._song()
        song.preview = "FF0000" * 18 + "000000" * 18 * 7
        grid = song.preview_colors()
        self.assertEqual(set(grid[7]), {"#FF0000"})
        self.assertEqual(set(grid[0]), {"#000000"})


# --------------------------------------------------------------------------- #
# Carte SD
# --------------------------------------------------------------------------- #

class TestSDCard(unittest.TestCase):
    """Parcours de la carte et résolution des chemins."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        # Carte factice, avec la casse « fautive » des vrais XML.
        (self.root / "SONGS").mkdir()
        (self.root / "SYNTHS" / "Basses").mkdir(parents=True)
        (self.root / "KITS").mkdir()
        (self.root / "SAMPLES" / "MULTISAMPLES" / "Sax").mkdir(parents=True)
        (self.root / "SONGS" / "A.XML").write_bytes(b"<song />")
        (self.root / "SYNTHS" / "Basses" / "B.XML").write_bytes(b"<sound />")
        (self.root / "KITS" / "K.XML").write_bytes(b"<kit />")
        (self.root / "SAMPLES" / "MULTISAMPLES" / "Sax" / "s.wav").write_bytes(b"RIFF")
        (self.root / "deluge-c1_2_1.bin").write_bytes(b"\x00")
        # Parasites qui ne doivent jamais apparaître dans les inventaires.
        (self.root / "SONGS" / "._A.XML").write_bytes(b"junk")
        (self.root / ".Trashes").mkdir()
        (self.root / ".Trashes" / "vieux.XML").write_bytes(b"<song />")
        (self.root / "SAMPLES" / ".DS_Store").write_bytes(b"junk")
        self.sd = sdcard.SDCard(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_carte_valide(self):
        self.assertTrue(self.sd.is_valid())
        self.assertEqual(self.sd.missing_dirs(), [])

    def test_inventaires_sans_parasites(self):
        """AppleDouble, corbeilles et .DS_Store sont écartés."""
        self.assertEqual([p.name for p in self.sd.songs()], ["A.XML"])
        self.assertEqual([p.name for p in self.sd.synths()], ["B.XML"])
        self.assertEqual([p.name for p in self.sd.kits()], ["K.XML"])
        self.assertEqual([p.name for p in self.sd.samples()], ["s.wav"])
        self.assertEqual([p.name for p in self.sd.firmware_files()],
                         ["deluge-c1_2_1.bin"])

    def test_resolution_insensible_a_la_casse(self):
        """Le cas réel de la carte : ``Multisamples`` contre ``MULTISAMPLES``."""
        for ref in ("SAMPLES/MULTISAMPLES/Sax/s.wav",
                    "SAMPLES/Multisamples/Sax/s.wav",
                    "samples/multisamples/sax/S.WAV"):
            with self.subTest(ref=ref):
                self.assertIsNotNone(self.sd.resolve_sample(ref),
                                     f"{ref} devrait se résoudre")

    def test_echantillon_absent(self):
        self.assertIsNone(self.sd.resolve_sample("SAMPLES/NEANT/x.wav"))
        self.assertIsNone(self.sd.resolve_sample(""))

    def test_chemins_relatifs(self):
        p = self.root / "SAMPLES" / "MULTISAMPLES" / "Sax" / "s.wav"
        self.assertEqual(self.sd.rel(p), "SAMPLES/MULTISAMPLES/Sax/s.wav")
        self.assertEqual(self.sd.abs("SAMPLES/MULTISAMPLES/Sax/s.wav"), p)

    def test_norm_rel(self):
        self.assertEqual(sdcard.norm_rel("SAMPLES\\Multisamples//Sax/"),
                         "samples/multisamples/sax")
        self.assertEqual(sdcard.norm_rel(""), "")

    def test_noms_compatibles_fat32(self):
        self.assertEqual(sdcard.safe_deluge_name("Épée: trop/long?"),
                         "Epee trop long")
        self.assertEqual(sdcard.safe_deluge_name(""), "SANS NOM")
        self.assertTrue(sdcard.check_name("Bad<name>"))
        self.assertEqual(sdcard.check_name("BONNE BASSE 01"), [])
        self.assertTrue(sdcard.check_name("x" * 80))

    def test_carte_invalide(self):
        """Un dossier quelconque n'est pas une carte Deluge."""
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(sdcard.SDCard(Path(tmp)).is_valid())
            self.assertFalse(sdcard.is_deluge_root(Path(tmp) / "absent"))


# --------------------------------------------------------------------------- #
# Audio
# --------------------------------------------------------------------------- #

class TestWav(unittest.TestCase):
    """Lecture et écriture WAV sans dépendance externe."""

    def _signal(self, frames: int = 2048, channels: int = 1) -> np.ndarray:
        t = np.linspace(0, 1, frames, endpoint=False, dtype=np.float32)
        mono = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        if channels == 1:
            return mono
        return np.stack([mono] * channels, axis=1)

    def test_aller_retour_par_profondeur(self):
        """16, 24 et 32 bits doivent se relire à la précision attendue."""
        tolerances = {16: 2e-4, 24: 2e-6, 32: 1e-6}
        with tempfile.TemporaryDirectory() as tmp:
            for bits, tol in tolerances.items():
                with self.subTest(bits=bits):
                    path = Path(tmp) / f"t{bits}.wav"
                    data = self._signal()
                    wav.write(path, data, 44100, bit_depth=bits)

                    info = wav.probe(path)
                    self.assertTrue(info.ok, info.error)
                    self.assertEqual(info.sample_rate, 44100)
                    self.assertEqual(info.channels, 1)
                    self.assertEqual(info.bit_depth, bits)
                    self.assertEqual(info.frames, len(data))

                    back, sr = wav.read(path, mono=True)
                    self.assertEqual(sr, 44100)
                    self.assertEqual(len(back), len(data))
                    self.assertLess(float(np.max(np.abs(back - data))), tol)

    def test_stereo(self):
        """Un fichier stéréo conserve ses deux canaux."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "st.wav"
            data = self._signal(channels=2)
            wav.write(path, data, 48000, bit_depth=24)
            info = wav.probe(path)
            self.assertEqual((info.channels, info.sample_rate), (2, 48000))
            back, _sr = wav.read(path)
            self.assertEqual(back.shape, data.shape)

    def test_duree(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "d.wav"
            wav.write(path, self._signal(44100), 44100, bit_depth=16)
            self.assertAlmostEqual(wav.probe(path).duration, 1.0, places=3)

    def test_enveloppe(self):
        """``peaks`` rend bien (buckets, 2) et reste dans [-1, 1]."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.wav"
            wav.write(path, self._signal(44100), 44100, bit_depth=16)
            env = wav.peaks(path, buckets=200)
            self.assertEqual(env.shape, (200, 2))
            self.assertLessEqual(float(np.max(env)), 1.0)
            self.assertGreaterEqual(float(np.min(env)), -1.0)
            # min <= max pour chaque tranche
            self.assertTrue(bool(np.all(env[:, 0] <= env[:, 1])))

    def test_fichier_invalide_ne_leve_pas(self):
        """SPEC §4.6 : ``probe`` ne lève jamais, il rend ``ok=False``."""
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "pasaudio.wav"
            bad.write_bytes(b"ceci n'est pas un wav")
            info = wav.probe(bad)
            self.assertFalse(info.ok)
            self.assertTrue(info.error)
            absent = wav.probe(Path(tmp) / "absent.wav")
            self.assertFalse(absent.ok)

    def test_conversion(self):
        """``convert`` réechantillonne et change la profondeur."""
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src.wav"
            dst = Path(tmp) / "dst.wav"
            wav.write(src, self._signal(44100, channels=2), 44100, bit_depth=24)
            info = wav.convert(src, dst, sample_rate=22050, bit_depth=16,
                               mono=True, normalize_db=-3.0)
            self.assertTrue(info.ok, info.error)
            self.assertEqual(info.sample_rate, 22050)
            self.assertEqual(info.channels, 1)
            self.assertEqual(info.bit_depth, 16)


# --------------------------------------------------------------------------- #
# Index et analyse
# --------------------------------------------------------------------------- #

class TestLibraryAndScan(unittest.TestCase):
    """Index SQLite et analyse d'une carte factice."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "carte"
        for sub in ("SONGS", "SYNTHS", "KITS", "SAMPLES/DRUMS/Kick"):
            (self.root / sub).mkdir(parents=True)

        # Deux échantillons réels, de contenus différents.
        t = np.linspace(0, 0.2, 8820, endpoint=False, dtype=np.float32)
        wav.write(self.root / "SAMPLES/DRUMS/Kick/k1.wav",
                  (0.6 * np.sin(2 * np.pi * 60 * t)).astype(np.float32), 44100)
        wav.write(self.root / "SAMPLES/DRUMS/Kick/k2.wav",
                  (0.3 * np.sin(2 * np.pi * 90 * t)).astype(np.float32), 44100)

        # Un preset qui référence k1 (présent) et un fichier absent.
        preset = SynthPreset.new("BASSE")
        preset.sound.osc1.type = "sample"
        preset.sound.osc1.file_name = "SAMPLES/DRUMS/Kick/k1.wav"
        preset.sound.osc2.type = "sample"
        preset.sound.osc2.file_name = "SAMPLES/NEANT/absent.wav"
        preset.save(self.root / "SYNTHS" / "BASSE.XML", backup=False)

        kit = Kit.new("KIT")
        kit.add_row("KICK", "SAMPLES/DRUMS/Kick/k1.wav")
        kit.save(self.root / "KITS" / "KIT.XML", backup=False)

        (self.root / "SONGS" / "M.XML").write_bytes(TestSong.SONG)

        self.sd = sdcard.SDCard(self.root)
        self.lib = db.Library(Path(self._tmp.name) / "index.db")

    def tearDown(self):
        self.lib.close()
        self._tmp.cleanup()

    def _scan(self, **kw):
        return scan.scan_card(self.sd, self.lib, **kw)

    def test_analyse_complete(self):
        """L'analyse doit tout indexer sans erreur."""
        res = self._scan()
        self.assertEqual(res.errors, [])
        self.assertEqual((res.samples, res.presets, res.kits, res.songs),
                         (2, 1, 1, 1))
        stats = self.lib.stats()
        self.assertEqual(stats["samples"], 2)
        self.assertEqual(stats["synths"], 1)
        self.assertEqual(stats["kits"], 1)
        self.assertEqual(stats["songs"], 1)

    def test_dependances_et_manquants(self):
        """Le fichier absent doit être signalé, le présent rattaché."""
        self._scan()
        missing = self.lib.missing_links()
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]["dst_rel"], "SAMPLES/NEANT/absent.wav")
        # k1 est utilisé par le preset ET par le kit ; k2 par personne.
        k1 = self.lib.get("sample", "SAMPLES/DRUMS/Kick/k1.wav")
        k2 = self.lib.get("sample", "SAMPLES/DRUMS/Kick/k2.wav")
        self.assertEqual(k1["used_count"], 2)
        self.assertEqual(k2["used_count"], 0)
        self.assertEqual([r["rel"] for r in self.lib.unused_samples()],
                         ["SAMPLES/DRUMS/Kick/k2.wav"])

    def test_categorie_deduite(self):
        """``SAMPLES/DRUMS/Kick/…`` doit donner la catégorie ``Kick``."""
        self._scan()
        row = self.lib.get("sample", "SAMPLES/DRUMS/Kick/k1.wav")
        self.assertEqual(row["category"], "Kick")

    def test_analyse_incrementale(self):
        """Sans modification, tout doit être sauté."""
        self._scan()
        again = self._scan(full=False)
        # 2 échantillons + 1 preset + 1 kit + 1 morceau.
        self.assertEqual(again.skipped, 5)
        self.assertEqual(again.errors, [])

    def test_l_analyse_acoustique_cochee_apres_coup_mesure_les_inchanges(self):
        """Cocher l'analyse acoustique après une première lecture.

        L'analyse incrémentale sautait les fichiers inchangés, restés donc
        sans mesures : il fallait « Tout réanalyser ». Elle les mesure.
        """
        self._scan(analyze=False)
        rel = "SAMPLES/DRUMS/Kick/k1.wav"
        self.assertIsNone(self.lib.get("sample", rel)["peak"])
        again = self._scan(analyze=True, full=False)
        self.assertIsNotNone(self.lib.get("sample", rel)["peak"])
        self.assertEqual(again.skipped, 3)       # preset, kit, morceau
        # Mesurés une fois, ils sont ensuite sautés comme les autres.
        self.assertEqual(self._scan(analyze=True, full=False).skipped, 5)

    def test_les_morceaux_sont_relus_une_fois_apres_correction(self):
        """Un index écrit par l'ancienne lecture garde des mesures fausses.

        L'analyse incrémentale ne relit pas un fichier inchangé : sans
        version de lecture, le nombre de mesures d'un morceau resterait
        celui de l'ancienne résolution jusqu'à une analyse complète.
        """
        self._scan()
        rel = "SONGS/M.XML"
        # On simule l'index d'avant la correction.
        self.lib.con.execute("UPDATE songs SET bars = 4.0 WHERE rel = ?",
                             (rel,))
        self.lib.con.commit()
        self.lib.set_meta("song_reader", "1")
        again = self._scan(full=False)
        self.assertEqual(again.skipped, 4, "le morceau aurait dû être relu")
        self.assertEqual(self.lib.get("song", rel)["bars"], 2.0)
        self.assertEqual(self.lib.get_meta("song_reader"), scan.SONG_READER)
        # Une seule fois : l'analyse suivante le saute de nouveau.
        self.assertEqual(self._scan(full=False).skipped, 5)

    def test_analyse_interruptible(self):
        """``should_stop`` doit arrêter l'analyse proprement."""
        res = self._scan(should_stop=lambda: True)
        self.assertTrue(res.stopped)
        self.assertEqual(res.errors, [])

    def test_carte_invalide_ne_leve_pas(self):
        """Une carte absente produit une erreur, pas une exception."""
        with tempfile.TemporaryDirectory() as tmp:
            res = scan.scan_card(sdcard.SDCard(Path(tmp)), self.lib)
            self.assertTrue(res.errors)
            self.assertEqual(res.samples, 0)

    def test_xml_illisible_est_signale(self):
        """Un XML irrécupérable donne ``ok=0``, sans interrompre l'analyse."""
        (self.root / "SYNTHS" / "CASSE.XML").write_bytes(b"\x00\x01 pas du xml")
        res = self._scan()
        row = self.lib.get("synth", "SYNTHS/CASSE.XML")
        self.assertIsNotNone(row)
        self.assertEqual(row["ok"], 0)
        self.assertTrue(row["error"])
        # Les autres fichiers ont tout de même été indexés.
        self.assertEqual(res.presets, 2)

    def test_recherche(self):
        """Les filtres de recherche doivent se combiner."""
        self._scan()
        self.assertEqual(len(self.lib.search_samples()), 2)
        self.assertEqual(len(self.lib.search_samples(text="k1")), 1)
        self.assertEqual(len(self.lib.search_samples(category="Kick")), 2)
        self.assertEqual(len(self.lib.search_samples(only_unused=True)), 1)
        self.assertEqual(len(self.lib.search_samples(folder="SAMPLES/DRUMS")), 2)
        self.assertEqual(len(self.lib.search_presets(kind="synth")), 1)
        self.assertEqual(len(self.lib.search_presets(kind="kit")), 1)
        self.assertEqual(len(self.lib.search_songs()), 1)

    def test_recherche_caracteres_speciaux(self):
        """Un ``%`` saisi par l'utilisateur ne doit pas devenir un joker."""
        self._scan()
        self.assertEqual(len(self.lib.search_samples(text="%")), 0)
        self.assertEqual(len(self.lib.search_samples(text="_")), 0)

    def test_tags_et_favoris(self):
        """Tags, notes et favoris doivent survivre à une nouvelle analyse."""
        self._scan()
        rel = "SAMPLES/DRUMS/Kick/k1.wav"
        self.lib.add_tag("sample", rel, "gros son", "#F2453D")
        self.lib.set_rating("sample", rel, stars=4, favorite=True,
                            notes="à garder")
        self.assertEqual(self.lib.tags_of("sample", rel), ["gros son"])

        self.lib.clear()
        self._scan()
        self.assertEqual(self.lib.tags_of("sample", rel), ["gros son"])
        rating = self.lib.get_rating("sample", rel)
        self.assertEqual((rating["stars"], rating["favorite"], rating["notes"]),
                         (4, 1, "à garder"))
        self.assertEqual(len(self.lib.search_samples(favorite=True)), 1)
        self.assertEqual(len(self.lib.search_samples(tag="gros son")), 1)

        self.lib.remove_tag("sample", rel, "gros son")
        self.assertEqual(self.lib.tags_of("sample", rel), [])

    def test_empreinte_rapide_ne_suffit_pas(self):
        """Deux fichiers aux extrémités identiques ne sont PAS des doublons.

        C'est le cas réel des multi-échantillons ``MoDrama`` de la carte :
        même taille, mêmes 64 Kio de tête et de queue (du silence), contenus
        différents. ``duplicates()`` ne doit rien affirmer sans comparaison
        complète, sous peine de faire supprimer de vrais échantillons.
        """
        head = np.zeros(70000, dtype=np.float32)
        tail = np.zeros(70000, dtype=np.float32)
        mid_a = np.full(70000, 0.5, dtype=np.float32)
        mid_b = np.full(70000, -0.5, dtype=np.float32)
        a = self.root / "SAMPLES" / "a.wav"
        b = self.root / "SAMPLES" / "b.wav"
        wav.write(a, np.concatenate([head, mid_a, tail]), 44100)
        wav.write(b, np.concatenate([head, mid_b, tail]), 44100)
        self.assertEqual(a.stat().st_size, b.stat().st_size)

        self._scan()
        for group in self.lib.duplicates():
            rels = {r["rel"] for r in group}
            self.assertNotEqual(rels, {"SAMPLES/a.wav", "SAMPLES/b.wav"},
                                "deux fichiers différents ont été déclarés "
                                "identiques")

    def test_doublon_reel_est_confirme(self):
        """Deux fichiers réellement identiques doivent être détectés."""
        import shutil

        shutil.copyfile(self.root / "SAMPLES/DRUMS/Kick/k1.wav",
                        self.root / "SAMPLES/DRUMS/Kick/copie.wav")
        self._scan()
        groups = self.lib.duplicates()
        self.assertEqual(len(groups), 1)
        self.assertEqual({r["rel"] for r in groups[0]},
                         {"SAMPLES/DRUMS/Kick/k1.wav",
                          "SAMPLES/DRUMS/Kick/copie.wav"})

    def test_empreinte_complete_vs_rapide(self):
        """``file_hash`` doit distinguer les deux modes."""
        p = self.root / "SAMPLES/DRUMS/Kick/k1.wav"
        self.assertTrue(scan.file_hash(p, quick=True))
        self.assertTrue(scan.file_hash(p, quick=False))
        # Un fichier absent ne lève pas.
        self.assertEqual(scan.file_hash(self.root / "absent.wav"), "")


# --------------------------------------------------------------------------- #
# Dépendances
# --------------------------------------------------------------------------- #

class TestDeps(unittest.TestCase):
    """Graphe des dépendances, réaffectation et recherche de remplaçants."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "carte"
        for sub in ("SONGS", "SYNTHS", "KITS",
                    "SAMPLES/MULTISAMPLES/Piano", "SAMPLES/DRUMS/Kick"):
            (self.root / sub).mkdir(parents=True)

        t = np.linspace(0, 0.2, 8820, endpoint=False, dtype=np.float32)
        tone = (0.5 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
        wav.write(self.root / "SAMPLES/MULTISAMPLES/Piano/C3.wav", tone, 44100)
        wav.write(self.root / "SAMPLES/DRUMS/Kick/k.wav", tone, 44100)
        wav.write(self.root / "SAMPLES/DRUMS/Kick/inutilise.wav", tone, 44100)

        # Deux presets : l'un correct, l'autre pointant vers un dossier déplacé
        # — exactement la situation des presets « rephazer » de la carte.
        good = SynthPreset.new("BON")
        good.sound.osc1.type = "sample"
        good.sound.osc1.file_name = "SAMPLES/DRUMS/Kick/k.wav"
        good.save(self.root / "SYNTHS" / "BON.XML", backup=False)

        broken = SynthPreset.new("CASSE")
        broken.sound.osc1.type = "sample"
        broken.sound.osc1.file_name = "SAMPLES/ANCIEN/Piano/C3.wav"
        broken.save(self.root / "SYNTHS" / "CASSE.XML", backup=False)

        kit = Kit.new("KIT")
        kit.add_row("KICK", "SAMPLES/DRUMS/Kick/k.wav")
        kit.save(self.root / "KITS" / "KIT.XML", backup=False)

        self.sd = sdcard.SDCard(self.root)
        self.lib = db.Library(Path(self._tmp.name) / "index.db")
        scan.scan_card(self.sd, self.lib, compute_hash=False)

    def tearDown(self):
        self.lib.close()
        self._tmp.cleanup()

    def test_graphe(self):
        """Usages, inutilisés et références cassées doivent être séparés."""
        graph = deps.build_graph(self.sd, self.lib)
        # k.wav est utilisé par le preset et par le kit.
        self.assertEqual(graph.usage_count("SAMPLES/DRUMS/Kick/k.wav"), 2)
        # La casse ne doit pas changer le résultat.
        self.assertEqual(graph.usage_count("samples/drums/kick/K.WAV"), 2)
        self.assertIn("SAMPLES/DRUMS/Kick/inutilise.wav", graph.unused)
        self.assertEqual(len(graph.missing), 1)
        self.assertEqual(graph.missing[0][2], "SAMPLES/ANCIEN/Piano/C3.wav")

    def test_utilisateurs(self):
        users = deps.build_graph(self.sd, self.lib).users_of(
            "SAMPLES/DRUMS/Kick/k.wav")
        self.assertEqual({kind for kind, _rel in users}, {"synth", "kit"})

    def test_remplacant_trouve(self):
        """Un dossier déplacé doit être retrouvé par le nom du fichier."""
        candidates = deps.find_replacement(
            self.sd, "SAMPLES/ANCIEN/Piano/C3.wav", self.lib)
        self.assertTrue(candidates)
        self.assertEqual(candidates[0], "SAMPLES/MULTISAMPLES/Piano/C3.wav")

    def test_remplacant_introuvable(self):
        self.assertEqual(
            deps.find_replacement(self.sd, "SAMPLES/X/zzzzzz.wav", self.lib), [])
        self.assertEqual(deps.find_replacement(self.sd, "", self.lib), [])

    def test_relink_simulation_ne_touche_a_rien(self):
        """``apply=False`` doit laisser la carte intacte (SPEC §0.2)."""
        target = self.root / "SYNTHS" / "CASSE.XML"
        before = target.read_bytes()
        changes = deps.relink(self.sd, "SAMPLES/ANCIEN/Piano/C3.wav",
                              "SAMPLES/MULTISAMPLES/Piano/C3.wav", apply=False)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0][1], 1)
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(list(self.root.rglob("*.bak")), [])

    def test_relink_applique(self):
        """``apply=True`` doit réparer la référence et sauvegarder l'ancien."""
        deps.relink(self.sd, "SAMPLES/ANCIEN/Piano/C3.wav",
                    "SAMPLES/MULTISAMPLES/Piano/C3.wav", apply=True)
        preset = SynthPreset.load(self.root / "SYNTHS" / "CASSE.XML")
        self.assertEqual(preset.sample_paths(),
                         ["SAMPLES/MULTISAMPLES/Piano/C3.wav"])
        self.assertEqual(len(list(self.root.rglob("*.bak"))), 1)
        # Plus aucune référence cassée après réanalyse.
        scan.scan_card(self.sd, self.lib, compute_hash=False, full=True)
        self.assertEqual(self.lib.missing_links(), [])

    def test_relink_many_une_seule_sauvegarde_par_fichier(self):
        """Réparer plusieurs références ne doit pas multiplier les ``.bak``.

        Appeler ``relink`` en boucle créait 125 sauvegardes pour 10 presets
        sur la vraie carte ; ``relink_many`` n'en crée qu'une par fichier.
        """
        preset = SynthPreset.new("MULTI")
        preset.sound.osc1.type = "sample"
        preset.sound.osc1.file_name = "SAMPLES/ANCIEN/Piano/C3.wav"
        preset.sound.osc2.type = "sample"
        preset.sound.osc2.file_name = "SAMPLES/ANCIEN/Piano/autre.wav"
        preset.save(self.root / "SYNTHS" / "MULTI.XML", backup=False)
        wav.write(self.root / "SAMPLES/MULTISAMPLES/Piano/autre.wav",
                  np.zeros(1000, dtype=np.float32), 44100)

        mapping = {
            "SAMPLES/ANCIEN/Piano/C3.wav": "SAMPLES/MULTISAMPLES/Piano/C3.wav",
            "SAMPLES/ANCIEN/Piano/autre.wav":
                "SAMPLES/MULTISAMPLES/Piano/autre.wav",
        }
        changes = deps.relink_many(self.sd, mapping, apply=True)
        touched = {p.name for p, _n in changes}
        self.assertIn("MULTI.XML", touched)
        self.assertEqual(sum(n for _p, n in changes), 3)   # 2 dans MULTI, 1 dans CASSE
        baks = list((self.root / "SYNTHS").glob("*.bak"))
        self.assertEqual(len(baks), len(touched))

    def test_relink_many_simulation(self):
        mapping = {"SAMPLES/ANCIEN/Piano/C3.wav":
                   "SAMPLES/MULTISAMPLES/Piano/C3.wav"}
        before = (self.root / "SYNTHS" / "CASSE.XML").read_bytes()
        changes = deps.relink_many(self.sd, mapping, apply=False)
        self.assertEqual(sum(n for _p, n in changes), 1)
        self.assertEqual((self.root / "SYNTHS" / "CASSE.XML").read_bytes(),
                         before)

    def test_relink_entrees_vides(self):
        """Des chemins vides ne doivent rien faire, sans lever."""
        self.assertEqual(deps.relink(self.sd, "", "x", apply=True), [])
        self.assertEqual(deps.relink_many(self.sd, {}, apply=True), [])

    def test_dependances_d_un_morceau(self):
        """Les presets d'un morceau doivent être listés sans doublon."""
        path = self.root / "SONGS" / "M.XML"
        path.write_bytes(TestSong.SONG)
        song = Song.load(path)
        presets = deps.presets_of_song(song)
        self.assertIn(("SYNTHS/Basses", "BASSE"), presets)
        self.assertEqual(len(presets), len(set(presets)))
        self.assertIsInstance(deps.samples_of_song(song), list)


# --------------------------------------------------------------------------- #
# Réorganisation
# --------------------------------------------------------------------------- #

class TestOrganize(unittest.TestCase):
    """Plans de réorganisation : simulation, application, non-régression."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "carte"
        for sub in ("SONGS", "SYNTHS", "KITS", "SAMPLES/EN VRAC",
                    "SAMPLES/EN VRAC/PROFOND"):
            (self.root / sub).mkdir(parents=True)

        t = np.linspace(0, 0.25, 11025, endpoint=False, dtype=np.float32)
        kick = (0.8 * np.sin(2 * np.pi * 60 * t) * np.exp(-t * 20)
                ).astype(np.float32)
        rng = np.random.default_rng(1)
        hat = (0.3 * rng.standard_normal(4410)).astype(np.float32)
        tone = (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        wav.write(self.root / "SAMPLES/EN VRAC/808 Kick.wav", kick, 44100)
        wav.write(self.root / "SAMPLES/EN VRAC/Closed hihat.wav", hat, 44100)
        wav.write(self.root / "SAMPLES/EN VRAC/inutilise.wav", tone, 44100)
        # Contenu différent : sans quoi ce fichier formerait un second groupe
        # de doublons et brouillerait les tests de déduplication.
        wav.write(self.root / "SAMPLES/EN VRAC/PROFOND/enfoui.wav",
                  (0.2 * np.sin(2 * np.pi * 330 * t)).astype(np.float32), 44100)

        # Parasites à nettoyer.
        (self.root / "SAMPLES/EN VRAC/._808 Kick.wav").write_bytes(b"junk")
        (self.root / "SAMPLES/.DS_Store").write_bytes(b"junk")

        preset = SynthPreset.new("BASSE")
        preset.sound.osc1.type = "sample"
        preset.sound.osc1.file_name = "SAMPLES/EN VRAC/808 Kick.wav"
        preset.save(self.root / "SYNTHS" / "BASSE.XML", backup=False)

        kit = Kit.new("KIT")
        kit.add_row("KICK", "SAMPLES/EN VRAC/808 Kick.wav")
        kit.add_row("HAT", "SAMPLES/EN VRAC/Closed hihat.wav")
        kit.save(self.root / "KITS" / "KIT.XML", backup=False)

        self.sd = sdcard.SDCard(self.root)
        self.lib = db.Library(Path(self._tmp.name) / "index.db")
        scan.scan_card(self.sd, self.lib, compute_hash=True)

    def tearDown(self):
        self.lib.close()
        self._tmp.cleanup()

    def _snapshot(self) -> set[str]:
        """Tous les chemins relatifs de la carte, pour comparer avant/après."""
        return {p.relative_to(self.root).as_posix()
                for p in self.root.rglob("*") if p.is_file()}

    # -- la règle d'or ----------------------------------------------------- #

    def test_un_plan_ne_touche_a_rien_tant_qu_il_n_est_pas_applique(self):
        """Construire un plan ne doit modifier aucun fichier (SPEC §0.2)."""
        before = self._snapshot()
        organize.plan_auto_classify_drums(self.sd, self.lib)
        organize.plan_purge_junk(self.sd)
        organize.plan_archive_unused(self.sd, self.lib)
        organize.plan_fix_names(self.sd, self.lib)
        organize.plan_dedupe(self.sd, self.lib)
        organize.plan_group_by(self.sd, self.lib, "category")
        organize.plan_flatten(self.sd, "SAMPLES/EN VRAC")
        organize.plan_rename(self.sd, ["SAMPLES/EN VRAC/inutilise.wav"],
                             "{name} {n}", lib=self.lib)
        self.assertEqual(self._snapshot(), before)

    def test_deplacer_un_echantillon_ne_casse_aucun_preset(self):
        """Le point critique : les XML doivent suivre les fichiers déplacés."""
        plan = organize.plan_auto_classify_drums(self.sd, self.lib)
        self.assertTrue(plan, "le kick et le charleston devraient être rangés")
        done, errors = plan.apply(self.sd, self.lib)
        self.assertEqual(errors, [])
        self.assertGreater(done, 0)

        # Le kick a changé de dossier…
        self.assertTrue((self.root / "SAMPLES/DRUMS/Kick/808 Kick.wav").exists())
        # …et le preset comme le kit pointent vers le nouvel emplacement.
        preset = SynthPreset.load(self.root / "SYNTHS" / "BASSE.XML")
        kit = Kit.load(self.root / "KITS" / "KIT.XML")
        self.assertEqual(preset.sample_paths(),
                         ["SAMPLES/DRUMS/Kick/808 Kick.wav"])
        self.assertIn("SAMPLES/DRUMS/Kick/808 Kick.wav", kit.sample_paths())
        for ref in preset.sample_paths() + kit.sample_paths():
            with self.subTest(ref=ref):
                self.assertIsNotNone(self.sd.resolve_sample(ref))
        # Et l'index ne voit plus aucune référence cassée.
        scan.scan_card(self.sd, self.lib, compute_hash=True, full=True)
        self.assertEqual(self.lib.missing_links(), [])

    def test_jamais_d_ecrasement(self):
        """Une destination occupée doit faire échouer l'opération, pas écraser."""
        (self.root / "SAMPLES/DRUMS/Kick").mkdir(parents=True)
        victime = self.root / "SAMPLES/DRUMS/Kick/808 Kick.wav"
        victime.write_bytes(b"CONTENU A NE PAS PERDRE")
        plan = organize.plan_auto_classify_drums(self.sd, self.lib)
        done, errors = plan.apply(self.sd, self.lib)
        self.assertTrue(errors, "un conflit devait être signalé")
        self.assertEqual(victime.read_bytes(), b"CONTENU A NE PAS PERDRE")

    # -- plans individuels -------------------------------------------------- #

    def test_parasites_hors_des_dossiers_ignores_et_taille_comptee(self):
        """Le parcours élague les corbeilles et compte les octets lui-même.

        Il parcourait tout, corbeilles comprises, et interrogeait le disque
        pour chaque fichier : 0,82 s sur la carte de l'utilisateur, 90 % du
        diagnostic de santé.
        """
        corbeille = self.root / ".Trashes" / "501"
        corbeille.mkdir(parents=True)
        (corbeille / "._jete.wav").write_bytes(b"x" * 10)
        (self.root / "SAMPLES" / "Thumbs.db").write_bytes(b"y" * 7)
        plan = organize.plan_purge_junk(self.sd)
        chemins = {self.sd.rel(op.src) for op in plan.ops}
        self.assertIn("SAMPLES/Thumbs.db", chemins)
        self.assertFalse(any(".Trashes" in c for c in chemins))
        self.assertEqual(plan.size, sum(op.src.stat().st_size
                                        for op in plan.ops))
        self.assertEqual([op.src for op in plan.ops],
                         sorted(op.src for op in plan.ops))

    def test_nettoyage_des_parasites(self):
        """Seuls les parasites doivent être visés."""
        plan = organize.plan_purge_junk(self.sd)
        names = {op.src.name for op in plan.ops}
        self.assertIn("._808 Kick.wav", names)
        self.assertIn(".DS_Store", names)
        self.assertNotIn("808 Kick.wav", names)
        self.assertTrue(all(op.kind == "delete" for op in plan.ops))

        plan.apply(self.sd, self.lib)
        self.assertFalse((self.root / "SAMPLES/EN VRAC/._808 Kick.wav").exists())
        self.assertTrue((self.root / "SAMPLES/EN VRAC/808 Kick.wav").exists())

    def test_archivage_des_inutilises(self):
        """Les inutilisés sont déplacés, pas supprimés."""
        plan = organize.plan_archive_unused(self.sd, self.lib)
        rels = {self.sd.rel(op.src) for op in plan.ops}
        self.assertIn("SAMPLES/EN VRAC/inutilise.wav", rels)
        self.assertNotIn("SAMPLES/EN VRAC/808 Kick.wav", rels)
        self.assertTrue(all(op.kind == "move" for op in plan.ops))
        plan.apply(self.sd, self.lib)
        self.assertTrue(list(self.root.glob("_UNUSED/**/inutilise.wav")))

    def test_les_prises_du_deluge_ne_sont_pas_archivees(self):
        """RECORD, RESAMPLE, CLIPS, EXPORTS : aucun preset ne les cite.

        L'archivage les emportait avec le reste ; ce sont des prises de
        l'utilisateur (``audioRecordingFolderNames`` du firmware 1.3.0).
        """
        t = np.linspace(0, 0.1, 4410, endpoint=False, dtype=np.float32)
        for i, folder in enumerate(organize.RECORDING_DIRS):
            (self.root / folder).mkdir(parents=True)
            wav.write(self.root / folder / "REC00000.WAV",
                      (0.1 * (i + 1) * np.sin(2 * np.pi * 200 * t)
                       ).astype(np.float32), 44100)
        scan.scan_card(self.sd, self.lib, compute_hash=True)
        rels = {self.sd.rel(op.src)
                for op in organize.plan_archive_unused(self.sd, self.lib).ops}
        self.assertIn("SAMPLES/EN VRAC/inutilise.wav", rels)
        self.assertFalse([r for r in rels if organize.is_recording(r)])
        issue = next(i for i in health.check_card(self.sd, self.lib).issues
                     if i.code == "ORPHAN_SAMPLE")
        self.assertFalse([r for r in issue.items if organize.is_recording(r)])
        self.assertTrue(organize.is_recording("samples/record/x.wav"))
        self.assertFalse(organize.is_recording("SAMPLES/RECORDINGS/x.wav"))

    def test_doublons_confirmes_seulement(self):
        """Un doublon réel est proposé, et la référence est redirigée."""
        import shutil as _sh

        _sh.copyfile(self.root / "SAMPLES/EN VRAC/808 Kick.wav",
                     self.root / "SAMPLES/EN VRAC/copie.wav")
        scan.scan_card(self.sd, self.lib, compute_hash=True, full=True)
        plan = organize.plan_dedupe(self.sd, self.lib)
        self.assertEqual(len(plan.ops), 1)
        op = plan.ops[0]
        self.assertEqual(op.kind, "delete")
        # dst porte le fichier conservé : les références y seront redirigées.
        self.assertIsNotNone(op.dst)
        self.assertEqual(op.dst.name, "copie.wav")   # chemin le plus court

        plan.apply(self.sd, self.lib)
        scan.scan_card(self.sd, self.lib, compute_hash=True, full=True)
        self.assertEqual(self.lib.missing_links(), [],
                         "la suppression d'un doublon ne doit casser aucune "
                         "référence")

    def test_mise_a_plat(self):
        plan = organize.plan_flatten(self.sd, "SAMPLES/EN VRAC")
        self.assertTrue(any(op.src.name == "enfoui.wav" for op in plan.ops))
        plan.apply(self.sd, self.lib)
        self.assertTrue((self.root / "SAMPLES/EN VRAC/enfoui.wav").exists())

    def test_correction_des_noms(self):
        """Un nom finissant par un point doit être corrigé."""
        mauvais = self.root / "SAMPLES/EN VRAC/Nom fautif..wav"
        mauvais.write_bytes((self.root / "SAMPLES/EN VRAC/inutilise.wav"
                             ).read_bytes())
        scan.scan_card(self.sd, self.lib, compute_hash=False, full=True)
        plan = organize.plan_fix_names(self.sd, self.lib)
        self.assertTrue(any(op.src.name == "Nom fautif..wav"
                            for op in plan.ops))

    def test_renommage_par_motif(self):
        """Les jetons du motif doivent être remplacés."""
        plan = organize.plan_rename(
            self.sd, ["SAMPLES/EN VRAC/808 Kick.wav"],
            "{cat} {n:02} - {name}", lib=self.lib)
        self.assertEqual(len(plan.ops), 1)
        self.assertIn("01", plan.ops[0].dst.name)
        self.assertTrue(plan.ops[0].dst.name.endswith(".wav"))

    def test_renommage_motif_invalide(self):
        """Un jeton inconnu ne doit pas faire échouer le renommage."""
        plan = organize.plan_rename(
            self.sd, ["SAMPLES/EN VRAC/808 Kick.wav"],
            "{inconnu} {name}", lib=self.lib)
        self.assertIsInstance(plan.ops, list)

    def test_regroupement(self):
        for key in ("category", "duration", "bpm", "key", "artist"):
            with self.subTest(key=key):
                plan = organize.plan_group_by(self.sd, self.lib, key)
                self.assertTrue(all(op.kind == "move" for op in plan.ops))

    def test_creation_arborescence_percussions(self):
        plan = organize.plan_create_drum_folders(self.sd)
        self.assertTrue(plan)
        plan.apply(self.sd, self.lib)
        self.assertTrue((self.root / "SAMPLES/DRUMS/Kick").is_dir())
        self.assertTrue((self.root / "SAMPLES/DRUMS/Snare").is_dir())
        # Rejouer le plan ne propose plus rien.
        self.assertFalse(organize.plan_create_drum_folders(self.sd))

    def test_resume_de_plan(self):
        vide = organize.Plan()
        self.assertEqual(vide.summary(), "Aucune modification à faire.")
        self.assertFalse(vide)
        plan = organize.Plan([organize.Op("move", Path("a"), Path("b"))],
                             title="Essai")
        self.assertIn("Essai", plan.summary())
        self.assertIn("a", plan.to_text())

    def test_dossier_conseille(self):
        self.assertEqual(organize.suggest_folder("808 Kick", "Kick"),
                         "SAMPLES/DRUMS/Kick")
        self.assertEqual(organize.suggest_folder("ma boucle loop", ""),
                         "SAMPLES/CLIPS")
        self.assertTrue(organize.suggest_folder("truc", "").startswith("SAMPLES/"))

    def test_fichier_disparu_pendant_l_application(self):
        """Un fichier supprimé entre le plan et son application est signalé."""
        plan = organize.plan_auto_classify_drums(self.sd, self.lib)
        for op in plan.ops:
            if op.src.name == "808 Kick.wav":
                op.src.unlink()
        done, errors = plan.apply(self.sd, self.lib)
        self.assertTrue(errors)


# --------------------------------------------------------------------------- #
# Diagnostic de santé
# --------------------------------------------------------------------------- #

class TestHealth(unittest.TestCase):
    """Rapport de santé et réparation automatique."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "carte"
        for sub in ("SONGS", "SYNTHS", "KITS", "SAMPLES/MULTISAMPLES/Piano"):
            (self.root / sub).mkdir(parents=True)

        t = np.linspace(0, 0.25, 11025, endpoint=False, dtype=np.float32)
        tone = (0.5 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
        wav.write(self.root / "SAMPLES/MULTISAMPLES/Piano/C3.wav", tone, 44100)
        wav.write(self.root / "SAMPLES/MULTISAMPLES/Piano/orphelin.wav",
                  (0.4 * np.sin(2 * np.pi * 330 * t)).astype(np.float32), 44100)

        # Un preset dont la référence est cassée, mais réparable : le fichier
        # existe ailleurs sous le même nom.
        preset = SynthPreset.new("CASSE")
        preset.sound.osc1.type = "sample"
        preset.sound.osc1.file_name = "SAMPLES/ANCIEN/Piano/C3.wav"
        preset.save(self.root / "SYNTHS" / "CASSE.XML", backup=False)

        (self.root / "SAMPLES/._parasite.wav").write_bytes(b"junk")
        (self.root / "SAMPLES/.DS_Store").write_bytes(b"junk")

        self.sd = sdcard.SDCard(self.root)
        self.lib = db.Library(Path(self._tmp.name) / "index.db")
        scan.scan_card(self.sd, self.lib, compute_hash=True)

    def tearDown(self):
        self.lib.close()
        self._tmp.cleanup()

    def _codes(self, report) -> set[str]:
        return {i.code for i in report.issues}

    def test_rapport(self):
        """Les anomalies présentes doivent être détectées."""
        report = health.check_card(self.sd, self.lib)
        codes = self._codes(report)
        self.assertIn("MISSING_SAMPLE", codes)
        self.assertIn("ORPHAN_SAMPLE", codes)
        self.assertIn("MAC_JUNK", codes)
        self.assertLessEqual(report.score, 100)
        self.assertGreaterEqual(report.score, 0)

    def test_bareme(self):
        """100 − (5 × erreurs + 2 × avertissements), borné à [0, 100]."""
        issues = [health.Issue("A", "error", "", "", ["x"]),
                  health.Issue("B", "warn", "", "", ["x"]),
                  health.Issue("C", "info", "", "", ["x"])]
        self.assertEqual(health.compute_score(issues), 93)
        self.assertEqual(health.compute_score([]), 100)
        beaucoup = [health.Issue(str(i), "error", "", "", ["x"])
                    for i in range(50)]
        self.assertEqual(health.compute_score(beaucoup), 0)

    def test_aucune_anomalie_sur_une_carte_saine(self):
        """Une carte propre ne doit rien déclencher d'anormal."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "propre"
            for sub in ("SONGS", "SYNTHS", "KITS", "SAMPLES/DRUMS/Kick"):
                (root / sub).mkdir(parents=True)
            t = np.linspace(0, 0.2, 8820, endpoint=False, dtype=np.float32)
            wav.write(root / "SAMPLES/DRUMS/Kick/k.wav",
                      (0.5 * np.sin(2 * np.pi * 60 * t)).astype(np.float32),
                      44100)
            preset = SynthPreset.new("BON")
            preset.sound.osc1.type = "sample"
            preset.sound.osc1.file_name = "SAMPLES/DRUMS/Kick/k.wav"
            preset.save(root / "SYNTHS" / "BON.XML", backup=False)
            sd2 = sdcard.SDCard(root)
            lib2 = db.Library(Path(tmp) / "i.db")
            try:
                scan.scan_card(sd2, lib2, compute_hash=True)
                report = health.check_card(sd2, lib2)
                codes = self._codes(report)
                self.assertNotIn("MISSING_SAMPLE", codes)
                self.assertNotIn("MAC_JUNK", codes)
                self.assertNotIn("ORPHAN_SAMPLE", codes)
                self.assertGreaterEqual(report.score, 95)
            finally:
                lib2.close()

    def test_xml_multiracine_n_est_pas_une_anomalie(self):
        """Un document multi-racines est la forme normale du firmware 2.x.

        Sur la carte réelle, 134 des 140 fichiers réparés sont dans ce cas :
        les signaler ferait passer une carte saine pour une carte abîmée.
        """
        (self.root / "SYNTHS" / "FW2.XML").write_bytes(
            b'<firmwareVersion>2.1.0</firmwareVersion>\n'
            b'<sound><osc1><type>saw</type></osc1></sound>')
        scan.scan_card(self.sd, self.lib, compute_hash=False, full=True)
        row = self.lib.get("synth", "SYNTHS/FW2.XML")
        self.assertIn("multi-racines", row["repaired"])
        # … et pourtant aucune anomalie REPAIRED_XML n'est levée.
        self.assertNotIn("REPAIRED_XML",
                         self._codes(health.check_card(self.sd, self.lib)))

    def test_xml_vraiment_abime_est_signale(self):
        """Un « & » non échappé, lui, doit être rapporté."""
        (self.root / "SYNTHS" / "AMP.XML").write_bytes(
            b'<sound><osc1 fileName="SAMPLES/A & B.wav" /></sound>')
        scan.scan_card(self.sd, self.lib, compute_hash=False, full=True)
        self.assertIn("REPAIRED_XML",
                      self._codes(health.check_card(self.sd, self.lib)))

    def test_ce_que_le_firmware_ecrit_n_est_pas_une_anomalie(self):
        """Un nom d'appareil en 0xFF, des balises numériques de la bêta 1.3.

        Les deux bloquaient la note de l'utilisateur à 92/100, avec un
        conseil impossible pour un morceau (« réenregistrer depuis
        l'application »). Un vrai défaut, à côté, reste signalé — seul.
        """
        ff = b'<device name="' + b"\xff" * 32 + b'" vendorId="0x1235" />'
        (self.root / "SONGS" / "MACHINE.XML").write_bytes(
            b'<song><performanceView><row><8>128</8><1>0</1></row>'
            b'</performanceView><midiKnobs><midiKnob>' + ff
            + b'</midiKnob></midiKnobs></song>')
        (self.root / "SYNTHS" / "APPRIS.XML").write_bytes(
            b'<sound><midiKnobs><midiKnob>' + ff
            + b'</midiKnob></midiKnobs></sound>')
        scan.scan_card(self.sd, self.lib, compute_hash=False, full=True)
        self.assertNotIn("REPAIRED_XML",
                         self._codes(health.check_card(self.sd, self.lib)))

        (self.root / "SYNTHS" / "APPRIS.XML").write_bytes(
            b'<sound><osc1 fileName="SAMPLES/A & B.wav" /><midiKnobs>'
            b'<midiKnob>' + ff + b'</midiKnob></midiKnobs></sound>')
        scan.scan_card(self.sd, self.lib, compute_hash=False, full=True)
        issue = next(i for i in health.check_card(self.sd, self.lib).issues
                     if i.code == "REPAIRED_XML")
        self.assertEqual(len(issue.items), 1)
        self.assertIn("'&'", issue.items[0])
        self.assertNotIn("0xFF", issue.items[0])

    def test_une_note_d_avant_se_relit_sans_tout_reanalyser(self):
        """L'index de l'utilisateur gardait l'ancienne note de ces fichiers.

        Inchangés, ils n'étaient pas relus : la version de lecture des presets
        et des morceaux les fait relire une fois.
        """
        ff = b'<device name="' + b"\xff" * 32 + b'" />'
        (self.root / "SYNTHS" / "APPRIS.XML").write_bytes(
            b'<sound><midiKnobs><midiKnob>' + ff
            + b'</midiKnob></midiKnobs></sound>')
        scan.scan_card(self.sd, self.lib, compute_hash=False, full=True)
        # L'index tel que l'ancienne lecture l'avait rempli.
        self.lib.con.execute("UPDATE presets SET repaired = ? WHERE rel = ?",
                             ("octets non UTF-8 remplacés",
                              "SYNTHS/APPRIS.XML"))
        self.lib.con.commit()
        self.lib.set_meta("synth_reader", "1")
        scan.scan_card(self.sd, self.lib, compute_hash=False, full=False)
        self.assertEqual(self.lib.get("synth", "SYNTHS/APPRIS.XML")["repaired"],
                         dxml.FIRMWARE_QUIRKS[0])
        self.assertEqual(self.lib.get_meta("synth_reader"),
                         scan.PRESET_READER)

    def test_rendus_texte_et_html(self):
        report = health.check_card(self.sd, self.lib)
        texte = report.to_text()
        self.assertIn("Santé de la carte", texte)
        html = report.to_html()
        self.assertTrue(html.startswith("<html>"))
        self.assertIn("</html>", html)
        # Le HTML doit échapper ce qu'il insère.
        hostile = health.HealthReport(
            [health.Issue("X", "warn", "<script>", "a & b", ["<b>"])])
        self.assertNotIn("<script>", hostile.to_html())
        self.assertIn("&amp;", hostile.to_html())

    def test_reparation_automatique_repare_vraiment(self):
        """La réparation doit faire remonter la note et tenir ses promesses."""
        before = health.check_card(self.sd, self.lib)
        codes = [i.code for i in before.auto_fixable()]
        self.assertIn("MISSING_SAMPLE", codes)

        plan = health.autofix(self.sd, self.lib, codes, apply=False)
        self.assertTrue(plan)
        done, errors = plan.apply(self.sd, self.lib)
        self.assertEqual(errors, [])

        scan.scan_card(self.sd, self.lib, compute_hash=True, full=True)
        after = health.check_card(self.sd, self.lib)
        self.assertEqual(self.lib.missing_links(), [])
        self.assertGreater(after.score, before.score)

    def test_archivage_n_emporte_pas_la_cible_d_une_reparation(self):
        """Un échantillon paraît inutilisé parce que sa référence est cassée.

        Réparer les références doit donc passer **avant** l'archivage : sinon
        l'archivage déplace la cible et la réparation échoue. C'est le cas des
        130 échantillons « rephazer » de la carte réelle.
        """
        plan = health.autofix(self.sd, self.lib,
                              ["MISSING_SAMPLE", "ORPHAN_SAMPLE"], apply=False)
        archived = {op.src.name for op in plan.ops if op.kind == "move"}
        self.assertNotIn("C3.wav", archived,
                         "C3.wav sert de cible à une réparation : il ne doit "
                         "pas être archivé")
        plan.apply(self.sd, self.lib)
        scan.scan_card(self.sd, self.lib, compute_hash=True, full=True)
        self.assertEqual(self.lib.missing_links(), [])

    def test_reparation_en_simulation(self):
        """``apply=False`` ne doit toucher à rien."""
        before = {p.relative_to(self.root).as_posix()
                  for p in self.root.rglob("*") if p.is_file()}
        health.autofix(self.sd, self.lib, list(health.AUTOFIX_CODES),
                       apply=False)
        after = {p.relative_to(self.root).as_posix()
                 for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_code_inconnu_ignore(self):
        plan = health.autofix(self.sd, self.lib, ["PAS_UN_CODE"], apply=False)
        self.assertEqual(plan.ops, [])

    def test_firmware_multiple(self):
        (self.root / "deluge-c1_2_1.bin").write_bytes(b"\x00")
        (self.root / "deluge-c1_3_0.bin").write_bytes(b"\x00")
        codes = self._codes(health.check_card(self.sd, self.lib))
        self.assertIn("MULTI_FIRMWARE", codes)

    def test_dossier_standard_absent(self):
        import shutil as _sh

        _sh.rmtree(self.root / "KITS")
        report = health.check_card(self.sd, self.lib)
        issue = next((i for i in report.issues
                      if i.code == "MISSING_STD_DIR"), None)
        self.assertIsNotNone(issue)
        self.assertIn("KITS", issue.items)
        # Et la réparation recrée le dossier.
        health.autofix(self.sd, self.lib, ["MISSING_STD_DIR"],
                       apply=True)
        self.assertTrue((self.root / "KITS").is_dir())

    def test_sans_sauvegarde(self):
        """Le contrôle de sauvegarde ne s'applique que si on donne un dossier."""
        self.assertNotIn("NO_BACKUP",
                         self._codes(health.check_card(self.sd, self.lib)))
        vide = Path(self._tmp.name) / "sauvegardes"
        codes = self._codes(health.check_card(self.sd, self.lib,
                                              backup_dir=vide))
        self.assertIn("NO_BACKUP", codes)


# --------------------------------------------------------------------------- #
# Sauvegardes
# --------------------------------------------------------------------------- #

class TestIndexEntreFils(unittest.TestCase):
    """Une seule connexion SQLite, plusieurs fils : il faut un verrou.

    ``check_same_thread=False`` ne rend pas une connexion sûre, il désactive
    seulement la vérification de Python. Sans verrou, quatre fils qui
    interrogent l'index en même temps donnent « bad parameter or other API
    misuse » et des lignes tronquées — et le diagnostic de santé, dont
    chaque contrôle avale ses erreurs, rend alors un **rapport amputé sans
    rien signaler**. C'est ce que faisait l'application dès que le
    diagnostic partait dans un fil pendant que le tableau de bord lisait.
    """

    def _carte(self, racine: Path):
        for nom in ("SONGS", "SYNTHS", "KITS", "SAMPLES"):
            (racine / nom).mkdir(parents=True, exist_ok=True)
        return sdcard.SDCard(racine)

    def test_lectures_concurrentes_justes_et_silencieuses(self):
        import threading

        with tempfile.TemporaryDirectory() as tmp:
            racine = Path(tmp) / "carte"
            carte = self._carte(racine)
            lib = db.Library(Path(tmp) / "index.sqlite3")
            try:
                for index in range(60):
                    lib.upsert_sample({
                        "rel": "SAMPLES/son%02d.wav" % index,
                        "name": "son%02d" % index, "size": 1000 + index})
                lib.commit()

                erreurs: list = []
                resultats: list = []

                def travail():
                    try:
                        for _ in range(12):
                            lignes = lib.search_samples(limit=100)
                            resultats.append(len(lignes))
                            for ligne in lignes:
                                # Une ligne tronquée lève ici.
                                _ = ligne["rel"]
                    except Exception as exc:        # noqa: BLE001
                        erreurs.append("%s: %s" % (type(exc).__name__, exc))

                fils = [threading.Thread(target=travail) for _ in range(5)]
                for f in fils:
                    f.start()
                for f in fils:
                    f.join(30)

                self.assertEqual(erreurs, [], "lecture concurrente en échec")
                self.assertEqual(set(resultats), {60},
                                 "résultats incomplets : %s"
                                 % sorted(set(resultats)))
            finally:
                lib.close()

    def test_ecriture_pendant_lecture(self):
        """Le cas réel : l'analyse écrit pendant que l'interface lit."""
        import threading

        with tempfile.TemporaryDirectory() as tmp:
            lib = db.Library(Path(tmp) / "index.sqlite3")
            try:
                erreurs: list = []
                fini = threading.Event()

                def ecrire():
                    try:
                        for index in range(200):
                            lib.upsert_sample({
                                "rel": "SAMPLES/a%03d.wav" % index,
                                "name": "a%03d" % index, "size": index})
                        lib.commit()
                    except Exception as exc:        # noqa: BLE001
                        erreurs.append("écriture : %s" % exc)
                    finally:
                        fini.set()

                def lire():
                    try:
                        while not fini.is_set():
                            lib.stats()
                            lib.search_samples(limit=50)
                    except Exception as exc:        # noqa: BLE001
                        erreurs.append("lecture : %s" % exc)

                fils = [threading.Thread(target=ecrire),
                        threading.Thread(target=lire)]
                for f in fils:
                    f.start()
                for f in fils:
                    f.join(30)
                self.assertEqual(erreurs, [])
                self.assertEqual(lib.stats().get("samples"), 200)
            finally:
                lib.close()

    def test_jamais_deux_requetes_en_meme_temps(self):
        """La propriété elle-même, plutôt que l'espoir d'un symptôme.

        Un premier test guettait le dégât — lignes tronquées, notes
        divergentes — et passait **aussi bien sans le verrou** : sur une
        carte factice, la fenêtre de course est trop étroite. Il ne prouvait
        donc rien.

        Celui-ci espionne la vraie connexion et compte combien de requêtes
        s'y trouvent **en même temps**. Avec le verrou : une, toujours. Sans
        lui : plusieurs, et c'est exactement ce qui a rendu « bad parameter
        or other API misuse » et deux notes de santé différentes pour la
        même carte.
        """
        import threading

        with tempfile.TemporaryDirectory() as tmp:
            lib = db.Library(Path(tmp) / "index.sqlite3")
            try:
                for index in range(40):
                    lib.upsert_sample({"rel": "SAMPLES/s%02d.wav" % index,
                                       "name": "s%02d" % index})
                lib.commit()

                vraie = lib.con.raw
                compte = {"actives": 0, "maximum": 0}
                garde = threading.Lock()

                class _Espion:
                    """Compte les requêtes simultanées sur la connexion."""

                    def __getattr__(self, nom):
                        return getattr(vraie, nom)

                    def execute(self, sql, parameters=()):
                        with garde:
                            compte["actives"] += 1
                            compte["maximum"] = max(compte["maximum"],
                                                    compte["actives"])
                        try:
                            # La pause élargit la fenêtre : sous verrou, elle
                            # ne laisse entrer personne ; sans verrou, si.
                            time.sleep(0.002)
                            return vraie.execute(sql, parameters)
                        finally:
                            with garde:
                                compte["actives"] -= 1

                lib.con._con = _Espion()

                def travail():
                    for _ in range(10):
                        lib.search_samples(limit=100)
                        lib.stats()

                fils = [threading.Thread(target=travail) for _ in range(4)]
                for f in fils:
                    f.start()
                for f in fils:
                    f.join(60)

                self.assertGreater(compte["maximum"], 0, "rien n'a été exécuté")
                self.assertEqual(
                    compte["maximum"], 1,
                    "%d requêtes en même temps sur une seule connexion"
                    % compte["maximum"])
            finally:
                # ``close`` passe par l'espion, qui délègue à la vraie
                # connexion : rien à remettre en place.
                lib.close()

    def test_un_resultat_est_deja_lu(self):
        """Le proxy matérialise : plus de curseur paresseux à travers les fils.

        C'est la seconde moitié de la correction. Un curseur lu plus tard,
        pendant qu'un autre fil interroge la même connexion, entrelace les
        appels à SQLite — d'où les lignes tronquées.
        """
        with tempfile.TemporaryDirectory() as tmp:
            lib = db.Library(Path(tmp) / "index.sqlite3")
            try:
                lib.upsert_sample({"rel": "SAMPLES/a.wav", "name": "a"})
                lib.commit()
                resultat = lib.con.execute("SELECT rel FROM samples")
                self.assertIsInstance(resultat, db._Resultat)
                # Lisible deux fois : la preuve qu'il ne reste rien à tirer
                # de la base.
                self.assertEqual(len(resultat.fetchall()), 1)
                self.assertEqual(len(resultat.fetchall()), 1)
            finally:
                lib.close()

    def test_le_verrou_est_reentrant(self):
        """Une requête qui en contient une autre ne doit pas se bloquer."""
        with tempfile.TemporaryDirectory() as tmp:
            lib = db.Library(Path(tmp) / "index.sqlite3")
            try:
                with lib.lock:
                    with lib.lock:
                        self.assertEqual(
                            lib.con.execute("SELECT 1").fetchone()[0], 1)
            finally:
                lib.close()


class TestCodesDAnomalie(unittest.TestCase):
    """``health.ISSUE_CODES`` est le vocabulaire stable des anomalies.

    L'interface s'en sert pour mener chaque anomalie vers l'onglet qui la
    répare. Si un code disparaît du module sans disparaître de la table des
    destinations, le raccourci vise un code mort — et personne ne s'en
    aperçoit, puisque rien ne lève.
    """

    def test_les_codes_emis_sont_tous_declares(self):
        """Ce que ``check_card`` produit vraiment, sur une carte factice."""
        with tempfile.TemporaryDirectory() as tmp:
            racine = Path(tmp) / "carte"
            for nom in ("SONGS", "SYNTHS", "KITS", "SAMPLES"):
                (racine / nom).mkdir(parents=True)
            (racine / "SAMPLES" / "._parasite.wav").write_bytes(b"x")
            (racine / "SAMPLES" / "notes.txt").write_text("bonjour")
            carte = sdcard.SDCard(racine)
            lib = db.Library(Path(tmp) / "index.sqlite3")
            try:
                rapport = health.check_card(carte, lib)
            finally:
                lib.close()
            emis = {i.code for i in rapport.issues}
            self.assertTrue(emis, "aucune anomalie : le test ne prouve rien")
            self.assertTrue(
                emis <= health.ISSUE_CODES,
                "codes émis mais non déclarés : %s"
                % sorted(emis - health.ISSUE_CODES))

    def test_aucun_code_declare_n_est_invente(self):
        """Dans l'autre sens : chaque code déclaré existe dans le module."""
        source = Path("delugeapp/core/health.py").read_text(encoding="utf-8")
        for code in sorted(health.ISSUE_CODES):
            self.assertIn('"%s"' % code, source, code)


class TestBackup(unittest.TestCase):
    """Sauvegarde, comparaison et restauration."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.root = self.base / "carte"
        for sub in ("SONGS", "SYNTHS", "KITS", "SAMPLES/DRUMS/Kick"):
            (self.root / sub).mkdir(parents=True)
        t = np.linspace(0, 0.2, 8820, endpoint=False, dtype=np.float32)
        wav.write(self.root / "SAMPLES/DRUMS/Kick/k.wav",
                  (0.5 * np.sin(2 * np.pi * 60 * t)).astype(np.float32), 44100)
        SynthPreset.new("UN").save(self.root / "SYNTHS" / "UN.XML",
                                   backup=False)
        SynthPreset.new("DEUX").save(self.root / "SYNTHS" / "DEUX.XML",
                                     backup=False)
        Kit.new("KIT").save(self.root / "KITS" / "KIT.XML", backup=False)
        (self.root / "CommunityFeatures.XML").write_bytes(b"<settings />")
        (self.root / "SAMPLES/._junk.wav").write_bytes(b"junk")

        self.sd = sdcard.SDCard(self.root)
        self.bdir = self.base / "sauvegardes"

    def tearDown(self):
        self._tmp.cleanup()

    def test_sauvegarde_sans_echantillons(self):
        """Le défaut : les XML seuls, ce qui est petit et rapide."""
        info = backup.create_backup(self.sd, self.bdir, label="essai")
        self.assertTrue(info.path.is_dir())
        self.assertFalse(info.include_samples)
        self.assertEqual(info.files, 4)        # 3 XML + CommunityFeatures
        self.assertFalse((info.path / "SAMPLES").exists())
        # Les parasites ne sont pas sauvegardés.
        self.assertEqual(list(info.path.rglob("._*")), [])
        self.assertIn("essai", info.name)

    def test_les_reglages_du_firmware_1_3_sont_sauvegardes(self):
        """Le firmware 1.3 range ses réglages et les favoris dans
        ``SETTINGS/`` — mesuré sur la machine de l'utilisateur, le 21 octobre
        2026. La sauvegarde ne regardait qu'à la racine, et les perdait."""
        reglages = self.root / "SETTINGS"
        (reglages / "FAVOURITES").mkdir(parents=True)
        (reglages / "MIDIFollow.XML").write_bytes(b"<defaults />")
        (reglages / "FAVOURITES" / "SONG_Bank0.xml").write_bytes(b"<x />")
        info = backup.create_backup(self.sd, self.bdir)
        self.assertTrue((info.path / "SETTINGS/MIDIFollow.XML").is_file())
        self.assertTrue(
            (info.path / "SETTINGS/FAVOURITES/SONG_Bank0.xml").is_file())
        # La racine, celle des firmwares plus anciens, reste sauvegardée.
        self.assertTrue((info.path / "CommunityFeatures.XML").is_file())
        diff = backup.diff_backup(info, self.sd)
        self.assertEqual((diff["added"], diff["changed"]), ([], []))

    def test_sauvegarde_avec_echantillons(self):
        info = backup.create_backup(self.sd, self.bdir, include_samples=True)
        self.assertTrue(info.include_samples)
        self.assertTrue((info.path / "SAMPLES/DRUMS/Kick/k.wav").is_file())
        self.assertEqual(list(info.path.rglob("._*")), [])

    def test_liste_et_manifeste(self):
        backup.create_backup(self.sd, self.bdir, label="premiere")
        backup.create_backup(self.sd, self.bdir, label="seconde")
        backups = backup.list_backups(self.bdir)
        self.assertEqual(len(backups), 2)
        # La plus récente d'abord.
        self.assertGreaterEqual(backups[0].when, backups[1].when)
        self.assertTrue(all(b.files > 0 for b in backups))
        self.assertIn("fichiers", backups[0].summary())

    def test_liste_dossier_absent(self):
        self.assertEqual(backup.list_backups(self.base / "nulle part"), [])

    def test_comparaison(self):
        """La comparaison doit voir modifications, ajouts et retraits."""
        info = backup.create_backup(self.sd, self.bdir)
        self.assertEqual(backup.diff_backup(info, self.sd)["changed"], [])

        (self.root / "SYNTHS" / "UN.XML").write_bytes(b"<sound name='X' />")
        (self.root / "SYNTHS" / "TROIS.XML").write_bytes(b"<sound />")
        (self.root / "SYNTHS" / "DEUX.XML").unlink()
        diff = backup.diff_backup(info, self.sd)
        self.assertEqual(diff["changed"], ["SYNTHS/UN.XML"])
        self.assertEqual(diff["added"], ["SYNTHS/TROIS.XML"])
        self.assertEqual(diff["removed"], ["SYNTHS/DEUX.XML"])

    def test_restauration(self):
        """Une restauration remet les fichiers modifiés et supprimés."""
        info = backup.create_backup(self.sd, self.bdir)
        original = (self.root / "SYNTHS" / "UN.XML").read_bytes()
        (self.root / "SYNTHS" / "UN.XML").write_bytes(b"<sound name='X' />")
        (self.root / "SYNTHS" / "DEUX.XML").unlink()

        restored, errors = backup.restore_backup(info, self.sd)
        self.assertEqual(errors, [])
        self.assertEqual(restored, 2)
        self.assertEqual((self.root / "SYNTHS" / "UN.XML").read_bytes(),
                         original)
        self.assertTrue((self.root / "SYNTHS" / "DEUX.XML").is_file())

    def test_restauration_en_simulation(self):
        info = backup.create_backup(self.sd, self.bdir)
        (self.root / "SYNTHS" / "UN.XML").write_bytes(b"<sound name='X' />")
        restored, errors = backup.restore_backup(info, self.sd, apply=False)
        self.assertEqual(restored, 1)
        self.assertEqual(errors, [])
        # Le fichier n'a pas été remis en place.
        self.assertEqual((self.root / "SYNTHS" / "UN.XML").read_bytes(),
                         b"<sound name='X' />")

    def test_restauration_ignore_l_identique(self):
        """Rien à restaurer si la carte est déjà conforme."""
        info = backup.create_backup(self.sd, self.bdir)
        self.assertEqual(backup.restore_backup(info, self.sd), (0, []))

    def test_archive_zip(self):
        info = backup.create_backup(self.sd, self.bdir, label="archive",
                                    zip_it=True)
        self.assertTrue(info.zipped)
        self.assertEqual(info.path.suffix, ".zip")
        self.assertFalse(info.path.with_suffix("").exists())
        # Elle doit se comparer et se restaurer comme un dossier.
        self.assertEqual(backup.diff_backup(info, self.sd)["changed"], [])
        (self.root / "SYNTHS" / "UN.XML").write_bytes(b"<sound name='X' />")
        restored, errors = backup.restore_backup(info, self.sd)
        self.assertEqual((restored, errors), (1, []))

    def test_archive_date_avant_1980(self):
        """Le format ZIP refuse les dates antérieures à 1980.

        Deux presets de la carte réelle sont datés du 31/12/1979 : sans
        tolérance, toute la compression échouait à cause de ces deux fichiers.
        """
        vieux = self.root / "SYNTHS" / "UN.XML"
        os.utime(vieux, (0, 0))   # 01/01/1970
        info = backup.create_backup(self.sd, self.bdir, zip_it=True)
        self.assertTrue(info.zipped)
        self.assertGreater(info.files, 0)

    def test_interruption_supprime_la_sauvegarde_partielle(self):
        """Une sauvegarde interrompue ne doit pas passer pour complète."""
        info = backup.create_backup(self.sd, self.bdir, label="interrompue",
                                    should_stop=lambda: True)
        self.assertFalse(info.path.exists())
        self.assertEqual(info.files, 0)
        self.assertEqual(backup.list_backups(self.bdir), [])

    def test_suppression(self):
        info = backup.create_backup(self.sd, self.bdir)
        self.assertTrue(backup.delete_backup(info))
        self.assertEqual(backup.list_backups(self.bdir), [])

    def test_copie_ponctuelle(self):
        """``snapshot_xml`` copie un fichier à côté de lui, sans l'écraser."""
        target = self.root / "SYNTHS" / "UN.XML"
        first = backup.snapshot_xml(target)
        self.assertTrue(first.is_file())
        self.assertEqual(first.read_bytes(), target.read_bytes())
        second = backup.snapshot_xml(target)
        self.assertNotEqual(first, second)
        self.assertTrue(second.is_file())

    def test_copie_ponctuelle_fichier_absent(self):
        with self.assertRaises(OSError):
            backup.snapshot_xml(self.root / "absent.XML")


# --------------------------------------------------------------------------- #
# Export MIDI
# --------------------------------------------------------------------------- #

class TestMidiFile(unittest.TestCase):
    """Écriture MIDI, relue par un analyseur indépendant du module."""

    #: Le lecteur indépendant (``aides_coeur.lire_midi``), partagé avec
    #: les tests de l'accompagnement.
    _parse = staticmethod(lire_midi)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_fichier_valide(self):
        """Le fichier produit doit être un SMF de type 1 relisible."""
        track = midifile.MidiTrack(name="Essai", channel=0)
        for i, note in enumerate((60, 64, 67, 72)):
            track.add(i * 96, note, 100, 90)
        path = self.dir / "a.mid"
        midifile.write_midi(path, [track], bpm=128)

        parsed = self._parse(path)
        self.assertEqual(parsed["format"], 1)
        self.assertEqual(parsed["ppq"], 96)
        self.assertAlmostEqual(60_000_000 / parsed["tempo_us"], 128.0,
                               places=1)
        # Piste 0 = tempo, piste 1 = la nôtre.
        self.assertEqual(len(parsed["tracks"]), 2)
        self.assertEqual(parsed["tracks"][1]["name"], "Essai")
        self.assertEqual(parsed["tracks"][1]["notes"],
                         [(0, 60, 100, 90), (96, 64, 100, 90),
                          (192, 67, 100, 90), (288, 72, 100, 90)])

    def test_tempo(self):
        for bpm in (60, 90, 120, 128, 174):
            with self.subTest(bpm=bpm):
                path = self.dir / f"{bpm}.mid"
                midifile.write_midi(path, [], bpm=bpm)
                parsed = self._parse(path)
                self.assertAlmostEqual(60_000_000 / parsed["tempo_us"],
                                       float(bpm), places=1)

    def test_longueur_variable(self):
        """Les délais longs doivent être codés sur plusieurs octets."""
        track = midifile.MidiTrack(name="Long", channel=0)
        track.add(0, 60, 100, 24)
        track.add(100000, 62, 100, 24)        # au-delà de 2^14
        path = self.dir / "long.mid"
        midifile.write_midi(path, [track])
        notes = self._parse(path)["tracks"][1]["notes"]
        self.assertEqual([n[0] for n in notes], [0, 100000])

    def test_notes_simultanees(self):
        """Un accord, puis la même note répétée : rien ne doit rester allumé."""
        track = midifile.MidiTrack(name="Accord", channel=0)
        for note in (60, 64, 67):
            track.add(0, note, 100, 96)
        track.add(96, 60, 100, 96)
        track.add(192, 60, 100, 96)
        path = self.dir / "accord.mid"
        midifile.write_midi(path, [track])
        notes = self._parse(path)["tracks"][1]["notes"]
        self.assertEqual(len(notes), 5)

    def test_export_d_un_motif(self):
        """Toutes les frappes d'un motif doivent sortir, sur le canal 10."""
        pattern = rhythm.genre_beat("techno", bars=2, seed=1)
        path = self.dir / "rythme.mid"
        midifile.pattern_to_midi(path, pattern, None, 130)
        parsed = self._parse(path)
        attendu = sum(len(s) for s in pattern.tracks.values())
        self.assertEqual(len(parsed["tracks"][1]["notes"]), attendu)
        # Les notes doivent être celles de la table General MIDI.
        utilisees = {n[1] for n in parsed["tracks"][1]["notes"]}
        self.assertIn(midifile.GM_DRUMS["Kick"], utilisees)
        self.assertTrue(utilisees <= set(midifile.GM_DRUMS.values()))

    def test_export_motif_avec_correspondance(self):
        pattern = rhythm.euclid_pattern({"Kick": (4, 16, 0)})
        path = self.dir / "map.mid"
        midifile.pattern_to_midi(path, pattern, {"Kick": 99}, 120)
        notes = self._parse(path)["tracks"][1]["notes"]
        self.assertEqual({n[1] for n in notes}, {99})

    def test_export_d_une_progression(self):
        """Un accord par mesure : 4 temps × ppq entre chaque."""
        chords = theory.progression(57, "mineur", "pop", seed=1, bars=4)
        path = self.dir / "accords.mid"
        midifile.progression_to_midi(path, chords, 90)
        parsed = self._parse(path)
        attendu = sum(len(c["notes"]) for c in chords)
        self.assertEqual(len(parsed["tracks"][1]["notes"]), attendu)
        debuts = sorted({n[0] for n in parsed["tracks"][1]["notes"]})
        pas = 4 * parsed["ppq"]
        self.assertEqual(debuts, [i * pas for i in range(len(chords))])

    def test_export_d_un_clip(self):
        """Un clip du Deluge doit sortir avec toutes ses notes."""
        with tempfile.TemporaryDirectory() as tmp:
            song_path = Path(tmp) / "M.XML"
            song_path.write_bytes(TestSong.SONG)
            song = Song.load(song_path)
            clip = song.clips[0]
            path = self.dir / "clip.mid"
            midifile.clip_to_midi(path, clip, song.tempo_bpm)
            parsed = self._parse(path)
            total = sum(len(t["notes"]) for t in parsed["tracks"][1:])
            self.assertEqual(total, clip.note_count)
            self.assertAlmostEqual(60_000_000 / parsed["tempo_us"],
                                   song.tempo_bpm, places=1)

    def test_un_clip_c1_2_1_sort_a_la_bonne_vitesse(self):
        """Une noire vaut 96 ticks à magnitude 2 : elle reste une noire.

        Le facteur de conversion valait toujours 4 : un clip d'un morceau
        c1.2.1 sortait quatre fois trop lent, un clip 3.x deux fois.
        """
        from delugeapp.core.model import Clip, Note, NoteRow

        for magnitude in (2, 1):
            clip = Clip(name="T", ticks_per_bar=96 << magnitude)
            # Une noire de durée, au deuxième temps.
            noire = 24 << magnitude
            clip.note_rows = [NoteRow(y=60, notes=[Note(pos=noire,
                                                        length=noire // 2)])]
            chemin = self.dir / ("vitesse%d.mid" % magnitude)
            midifile.clip_to_midi(chemin, clip, 120)
            notes = self._parse(chemin)["tracks"][1]["notes"]
            ppq = self._parse(chemin)["ppq"]
            with self.subTest(magnitude=magnitude):
                self.assertEqual((notes[0][0], notes[0][3]), (ppq, ppq // 2))
                self.assertEqual(ppq, 96)

    def test_conversion_de_resolution(self):
        """Sans résolution connue, l'ancienne hypothèse (24 par noire)
        s'applique : un facteur exact de 4."""
        from delugeapp.core.model import Note, NoteRow

        clip = type("C", (), {})()
        clip.note_rows = [NoteRow(y=60, notes=[Note(pos=0, length=24),
                                               Note(pos=96, length=48)])]
        clip.is_kit = False
        clip.name = "T"
        path = self.dir / "res.mid"
        midifile.clip_to_midi(path, clip, 120)
        notes = self._parse(path)["tracks"][1]["notes"]
        self.assertEqual([(n[0], n[3]) for n in notes],
                         [(0, 96), (384, 192)])

    def test_cas_limites(self):
        """Aucun cas vide ne doit produire un fichier invalide."""
        midifile.write_midi(self.dir / "vide.mid", [])
        self.assertEqual(len(self._parse(self.dir / "vide.mid")["tracks"]), 1)

        midifile.write_midi(self.dir / "sansnote.mid",
                            [midifile.MidiTrack(name="Rien")])
        self.assertEqual(
            self._parse(self.dir / "sansnote.mid")["tracks"][1]["notes"], [])

        midifile.progression_to_midi(self.dir / "p.mid", [], 120)
        self._parse(self.dir / "p.mid")

    def test_nom_non_ascii(self):
        """Un nom accentué est translittéré, pas livré en octets douteux."""
        track = midifile.MidiTrack(name="Accentué élan", channel=0,
                                   events=[(0, 60, 100, 24)])
        path = self.dir / "nom.mid"
        midifile.write_midi(path, [track])
        self.assertEqual(self._parse(path)["tracks"][1]["name"],
                         "Accentue elan")

    def test_valeurs_hors_bornes(self):
        """Notes, vélocités et canaux aberrants sont ramenés dans les bornes."""
        track = midifile.MidiTrack(name="Bornes", channel=99,
                                   events=[(-5, 999, 999, 0),
                                           (0, -10, -10, -10)])
        path = self.dir / "bornes.mid"
        midifile.write_midi(path, [track])
        notes = self._parse(path)["tracks"][1]["notes"]
        for _pos, note, velocity, duration in notes:
            self.assertTrue(0 <= note <= 127)
            self.assertTrue(1 <= velocity <= 127)
            self.assertGreater(duration, 0)

    def test_ecriture_atomique(self):
        """Aucun fichier temporaire ne doit subsister après l'écriture."""
        path = self.dir / "atomique.mid"
        midifile.write_midi(path, [midifile.MidiTrack(name="X")])
        self.assertTrue(path.is_file())
        self.assertEqual(list(self.dir.glob("*.part")), [])


class TestUnits(unittest.TestCase):
    """``core/units.py`` : une seule mise en forme pour tout le logiciel.

    Il y en a eu trois — une dans l'interface, deux recopiées dans le noyau —
    et les copies du noyau écrivaient le séparateur décimal à l'anglaise.
    Les messages de correction d'échantillons annonçaient « 9.9 Mio » au
    milieu d'une application en français.
    """

    def test_octets(self):
        cas = {
            0: "0 o",
            1: "1 o",
            512: "512 o",
            1023: "1023 o",
            1024: "1,0 Kio",
            1536: "1,5 Kio",
            1024 ** 2: "1,0 Mio",
            5 * 1024 ** 2 + 512 * 1024: "5,5 Mio",
            1024 ** 3: "1,0 Gio",
        }
        for octets, attendu in cas.items():
            with self.subTest(octets=octets):
                self.assertEqual(units.human_size(octets), attendu)

    def test_le_separateur_decimal_est_la_virgule(self):
        """Toute l'application est en français : jamais de point décimal."""
        for octets in (1024, 1536, 10 ** 6, 10 ** 9, 10 ** 12):
            with self.subTest(octets=octets):
                texte = units.human_size(octets)
                self.assertNotIn(".", texte, texte)
                if "o" != texte.split()[-1]:
                    self.assertIn(",", texte, texte)

    def test_une_taille_inconnue_n_est_pas_une_taille_nulle(self):
        self.assertEqual(units.human_size(None), "—")
        self.assertEqual(units.human_size("pas un nombre"), "—")

    def test_au_dela_du_gibioctet(self):
        """Pas d'unité au-delà : on reste en Gio plutôt qu'inventer."""
        self.assertTrue(units.human_size(5000 * 1024 ** 3).endswith("Gio"))

    def test_durees(self):
        cas = {
            1.25: "1,25 s",
            59.99: "59,99 s",
            60: "1 min 00 s",
            187: "3 min 07 s",
            3599: "59 min 59 s",
        }
        for secondes, attendu in cas.items():
            with self.subTest(secondes=secondes):
                self.assertEqual(units.human_duration(secondes), attendu)

    def test_une_duree_nulle_ou_absente(self):
        for valeur in (0, None, -1, "x"):
            with self.subTest(valeur=valeur):
                self.assertEqual(units.human_duration(valeur), "—")

    def test_pas_de_soixante_secondes(self):
        """L'arrondi porte sur le total : « 2 min 60 s » n'existe pas."""
        for secondes in (119.6, 119.9, 179.7, 239.95):
            with self.subTest(secondes=secondes):
                self.assertNotIn("60 s", units.human_duration(secondes))

    def test_taille_de_fichier(self):
        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier) / "x.bin"
            chemin.write_bytes(b"0" * 1234)
            self.assertEqual(units.file_size(chemin), 1234)
            self.assertEqual(units.file_size(Path(dossier) / "absent"), 0)
            self.assertEqual(units.file_size(dossier), 0)

    def test_l_interface_et_le_noyau_partagent_l_implementation(self):
        """Une seule source : sinon les deux divergent à la retouche."""
        try:
            from delugeapp.ui.widgets import common
        except ImportError:
            self.skipTest("PyQt6 absent")
        self.assertIs(common.human_size, units.human_size)
        self.assertIs(common.human_duration, units.human_duration)

    def test_les_modules_du_noyau_n_ont_plus_de_copie(self):
        """Garde-fou : le doublon ne doit pas revenir."""
        from delugeapp.core import samplefix, songpack

        for module in (samplefix, songpack):
            with self.subTest(module=module.__name__):
                self.assertFalse(hasattr(module, "_human"))
                self.assertFalse(hasattr(module, "_size"))

    def test_dates(self):
        """Une date se lit, elle ne se déchiffre pas.

        La base garde l'ISO, qui se trie bien ; la page Réglages l'affichait
        tel quel — « 2026-10-10T23:57:06 » au milieu d'une phrase française.
        """
        self.assertEqual(units.human_datetime("2026-10-10T23:57:06"),
                         "10/10/2026 à 23h57")
        self.assertEqual(units.human_datetime("2026-01-02T05:04"),
                         "02/01/2026 à 05h04")
        self.assertEqual(units.human_datetime(""), "—")
        self.assertEqual(units.human_datetime(None), "—")
        self.assertEqual(units.human_datetime(None, absent="jamais"),
                         "jamais")
        # Une chaîne illisible vaut mieux qu'un tiret : on cherche
        # justement à savoir quand.
        self.assertEqual(units.human_datetime("hier soir"), "hier soir")

    def test_les_messages_du_noyau_portent_la_virgule(self):
        """Le défaut constaté : « libérés 9.9 Mio » dans la barre d'état."""
        from delugeapp.core import samplefix

        res = samplefix.FixResult(applied=True, done=["a", "b"],
                                  bytes_before=10_400_000,
                                  bytes_after=5_200_000)
        texte = res.summary()
        self.assertIn("5,0 Mio", texte)
        self.assertNotIn("5.0", texte)


class TestDossierDeConfiguration(unittest.TestCase):
    """``NOCTILUCA_CONFIG`` déplace les réglages hors de chez l'utilisateur.

    Ce n'est pas un confort : mes propres scripts d'essai ont deux fois
    écrasé les réglages réels, et une fois en éteignant la confirmation
    d'écriture **et** la sauvegarde automatique — les deux filets qui
    protègent une carte contenant des mois de travail. La variable rend
    l'isolement possible en une ligne, au lieu de dépendre de ma vigilance.
    """

    def setUp(self):
        from delugeapp import config as config_mod

        self.config_mod = config_mod
        self._avant = {nom: os.environ.get(nom)
                       for nom in (config_mod.CONFIG_ENV,
                                   config_mod.LEGACY_CONFIG_ENV)}

    def tearDown(self):
        for nom, valeur in self._avant.items():
            if valeur is None:
                os.environ.pop(nom, None)
            else:
                os.environ[nom] = valeur

    def _dossier(self, valeur):
        """Dossier de configuration que donnerait un démarrage avec ``valeur``."""
        if valeur is None:
            os.environ.pop(self.config_mod.CONFIG_ENV, None)
        else:
            os.environ[self.config_mod.CONFIG_ENV] = valeur
        return self.config_mod._config_dir()

    def test_la_variable_impose_le_dossier(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self._dossier(tmp), Path(tmp))

    def test_l_ancienne_variable_vaut_toujours(self):
        """Un script d'essai écrit sous l'ancien nom reste isolé : s'il
        retombait sur les réglages réels, c'est la carte qui paierait."""
        with tempfile.TemporaryDirectory() as tmp:
            os.environ[self.config_mod.LEGACY_CONFIG_ENV] = tmp
            self.assertEqual(self._dossier(None), Path(tmp))
            with tempfile.TemporaryDirectory() as neuf:
                self.assertEqual(self._dossier(neuf), Path(neuf),
                                 "la nouvelle variable passe avant l'ancienne")

    def test_sans_la_variable_on_reste_chez_l_utilisateur(self):
        self.assertEqual(self._dossier(None).name, self.config_mod.APP_ORG)

    def test_une_valeur_vide_ne_deplace_rien(self):
        """Une variable posée à vide n'envoie pas les réglages à la racine."""
        self.assertEqual(self._dossier("   ").name, self.config_mod.APP_ORG)

    def test_le_tilde_est_developpe(self):
        self.assertFalse(str(self._dossier("~/essai-deluge")).startswith("~"))

    def test_les_reglages_vont_dans_le_dossier_courant_du_module(self):
        """Déplacer les chemins du module suffit à isoler une écriture.

        C'est le geste que doit faire tout script : sans lui, ``save_settings``
        écrit chez l'utilisateur.
        """
        config_mod = self.config_mod
        with tempfile.TemporaryDirectory() as tmp:
            anciens = (config_mod.CONFIG_DIR, config_mod.SETTINGS_PATH)
            try:
                config_mod.CONFIG_DIR = Path(tmp)
                config_mod.SETTINGS_PATH = Path(tmp) / "settings.json"
                reglages = config_mod.Settings()
                reglages.confirm_writes = False
                config_mod.save_settings(reglages)

                ecrit = Path(tmp) / "settings.json"
                self.assertTrue(ecrit.exists(),
                                "rien n'a été écrit dans le dossier isolé")
                self.assertIn('"confirm_writes": false',
                              ecrit.read_text(encoding="utf-8"))
            finally:
                config_mod.CONFIG_DIR, config_mod.SETTINGS_PATH = anciens

    def test_la_suite_n_ecrit_pas_chez_l_utilisateur(self):
        """L'invariant qui remplace ma vigilance.

        ``tests/__init__.py`` déplace la configuration dans un bac à sable
        avant tout import de ``delugeapp``. Si ces lignes disparaissent, ce
        test tombe — au lieu d'un fichier de réglages écrasé chez
        l'utilisateur, découvert deux heures plus tard.
        """
        import tests

        for nom in (self.config_mod.APP_ORG, self.config_mod.LEGACY_APP_ORG):
            self.assertNotEqual(
                self.config_mod.CONFIG_DIR, self.config_mod._base_dir() / nom,
                "la suite écrirait dans les réglages réels de l'utilisateur")
        self.assertEqual(self.config_mod.CONFIG_DIR, tests.BAC_A_SABLE)
        for chemin in (self.config_mod.SETTINGS_PATH,
                       self.config_mod.LOG_PATH,
                       self.config_mod.DB_PATH,
                       self.config_mod.DEFAULT_BACKUP_DIR):
            self.assertTrue(
                str(chemin).startswith(str(tests.BAC_A_SABLE)),
                "%s sort du bac à sable" % chemin)

    def test_les_defauts_protegent_la_carte(self):
        """Les deux filets sont actifs par défaut (SPEC §0.2).

        Ils ne doivent jamais passer à ``False`` par inadvertance dans la
        classe : c'est la valeur que reçoit un utilisateur qui n'a pas encore
        de fichier de réglages.
        """
        neuf = self.config_mod.Settings()
        self.assertTrue(neuf.confirm_writes)
        self.assertTrue(neuf.always_backup_before_write)


class TestAncienNom(unittest.TestCase):
    """« Deluge Companion » devient « Noctiluca » sans rien perdre.

    Chez l'utilisateur : 1,1 Go dans ``%APPDATA%/DelugeCompanion``
    (réglages, index, sauvegardes), 1,4 Go de copie de travail dans
    ``%LOCALAPPDATA%/DelugeCompanion/Carte``, et ce chemin-là écrit dans ses
    réglages et dans l'index. Un simple changement de nom aurait ouvert
    l'application sur des réglages neufs, une copie de travail vide à
    recréer par le câble — des heures — et un index vidé.
    """

    def setUp(self):
        from unittest import mock

        from delugeapp import config as config_mod

        self.config_mod = config_mod
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.ancien = self.base / config_mod.LEGACY_APP_ORG
        self.nouveau = self.base / config_mod.APP_ORG
        for nom in ("REPRISES", "_RENOMMES"):
            patch = mock.patch.object(config_mod, nom, [])
            patch.start()
            self.addCleanup(patch.stop)

    def test_le_dossier_seul_est_renomme(self):
        (self.ancien / "backups").mkdir(parents=True)
        (self.ancien / "settings.json").write_text("{}", encoding="utf-8")
        self.assertEqual(self.config_mod._reprendre(self.ancien, self.nouveau),
                         self.nouveau)
        self.assertFalse(self.ancien.exists())
        self.assertEqual((self.nouveau / "settings.json").read_text(
            encoding="utf-8"), "{}")
        self.assertTrue((self.nouveau / "backups").is_dir())
        self.assertEqual(self.config_mod.REPRISES,
                         [(self.ancien, self.nouveau, True)])
        self.assertEqual(self.config_mod._RENOMMES,
                         [(self.ancien, self.nouveau)])

    def test_un_dossier_neuf_existant_n_est_pas_ecrase(self):
        """Les deux à la fois : on garde le neuf, l'ancien reste intact et
        ses chemins ne sont pas traduits — il mène encore quelque part."""
        self.ancien.mkdir()
        (self.ancien / "settings.json").write_text("ancien", encoding="utf-8")
        self.nouveau.mkdir()
        self.assertEqual(self.config_mod._reprendre(self.ancien, self.nouveau),
                         self.nouveau)
        self.assertEqual((self.ancien / "settings.json").read_text(
            encoding="utf-8"), "ancien")
        self.assertEqual(self.config_mod.REPRISES, [])
        self.assertEqual(self.config_mod._RENOMMES, [])

    def test_sans_ancien_dossier_rien_n_est_cree(self):
        self.assertEqual(self.config_mod._reprendre(self.ancien, self.nouveau),
                         self.nouveau)
        self.assertFalse(self.nouveau.exists())
        self.assertEqual(self.config_mod.REPRISES, [])

    def test_un_renommage_impossible_garde_l_ancien_dossier(self):
        """Une fenêtre de l'ancienne version tient ``library.db`` ouvert :
        l'ancien dossier sert tel quel, rien n'est perdu ni dédoublé."""
        from unittest import mock

        self.ancien.mkdir()
        with mock.patch.object(Path, "rename",
                               side_effect=PermissionError("tenu ouvert")):
            obtenu = self.config_mod._reprendre(self.ancien, self.nouveau)
        self.assertEqual(obtenu, self.ancien)
        self.assertTrue(self.ancien.is_dir())
        self.assertFalse(self.nouveau.exists())
        self.assertEqual(self.config_mod.REPRISES,
                         [(self.ancien, self.nouveau, False)])
        self.assertEqual(self.config_mod._RENOMMES, [])

    def test_un_chemin_enregistre_suit_le_dossier(self):
        self.config_mod._RENOMMES.append((self.ancien, self.nouveau))
        actuel = self.config_mod.chemin_actuel
        self.assertEqual(actuel(str(self.ancien / "Carte")),
                         str(self.nouveau / "Carte"))
        self.assertEqual(actuel(str(self.ancien)), str(self.nouveau))
        if os.name == "nt":
            self.assertEqual(actuel(str(self.ancien / "Carte").upper()),
                             str(self.nouveau) + "\\CARTE")
        for tel_quel in (str(self.base / "DelugeCompanionBis" / "Carte"),
                         str(self.base / "Ailleurs"), "", "   "):
            self.assertEqual(actuel(tel_quel), tel_quel)

    def test_les_reglages_suivent_la_copie_de_travail(self):
        self.config_mod._RENOMMES.append((self.ancien, self.nouveau))
        carte = str(self.ancien / "Carte")
        s = self.config_mod.Settings(
            sd_path=carte, recent_paths=[carte, str(self.nouveau / "Carte"),
                                         str(self.base / "Ailleurs")],
            card_backup=str(self.base / "Sauvegarde"))
        self.assertTrue(s.relocate())
        self.assertEqual(s.sd_path, str(self.nouveau / "Carte"))
        self.assertEqual(s.recent_paths, [str(self.nouveau / "Carte"),
                                          str(self.base / "Ailleurs")])
        self.assertEqual(s.card_backup, str(self.base / "Sauvegarde"))
        self.assertFalse(s.relocate(), "une seconde fois, rien ne change")

    def test_l_index_reconnait_la_carte_renommee(self):
        """Sans la traduction, l'index se vidait au premier démarrage : la
        racine retenue n'était plus celle de la carte ouverte."""
        nouvelle = self.nouveau / "Carte"
        for sous in ("SONGS", "SYNTHS", "KITS", "SAMPLES"):
            (nouvelle / sous).mkdir(parents=True)
        lib = db.Library(self.base / "index.db")
        self.addCleanup(lib.close)
        lib.set_meta("last_scan_root", str(self.ancien / "Carte"))
        sd = sdcard.SDCard(nouvelle)
        self.config_mod._RENOMMES.append((self.ancien, self.nouveau))
        self.assertFalse(scan.forget_other_card(sd, lib))
        self.assertEqual(lib.get_meta("last_scan_root"),
                         str(self.ancien / "Carte"))
        self.config_mod._RENOMMES.clear()
        self.assertTrue(scan.forget_other_card(sd, lib),
                        "le témoin : sans traduction, l'index est vidé")

    def test_le_dossier_de_synchronisation_change_de_nom(self):
        from delugeapp.core import cardsync

        travail = self.base / "Carte"
        (travail / cardsync.LEGACY_META_DIR / "historique").mkdir(parents=True)
        (travail / cardsync.LEGACY_META_DIR / "synchro.json").write_bytes(b"{}")
        self.assertTrue(cardsync.adopt_legacy_meta(travail))
        self.assertEqual((travail / cardsync.MANIFEST).read_bytes(), b"{}")
        self.assertTrue((travail / cardsync.HISTORY).is_dir())
        self.assertFalse((travail / cardsync.LEGACY_META_DIR).exists())
        self.assertFalse(cardsync.adopt_legacy_meta(travail))

    def test_un_dossier_de_synchronisation_neuf_n_est_pas_ecrase(self):
        from delugeapp.core import cardsync

        travail = self.base / "Carte"
        (travail / cardsync.LEGACY_META_DIR).mkdir(parents=True)
        (travail / cardsync.LEGACY_META_DIR / "synchro.json").write_bytes(b"A")
        (travail / cardsync.META_DIR).mkdir()
        (travail / cardsync.MANIFEST).write_bytes(b"B")
        self.assertFalse(cardsync.adopt_legacy_meta(travail))
        self.assertEqual((travail / cardsync.LEGACY_META_DIR / "synchro.json")
                         .read_bytes(), b"A")
        self.assertEqual((travail / cardsync.MANIFEST).read_bytes(), b"B")
        self.assertTrue(cardsync.is_junk(cardsync.LEGACY_META_DIR
                                         + "/synchro.json"),
                        "l'ancien dossier ne part jamais sur la carte")

    def test_la_sauvegarde_n_est_reprise_qu_a_sa_mise_a_jour(self):
        """La sauvegarde n'est écrite que par « Mettre à jour la
        sauvegarde » : son dossier de l'ancien nom attend ce moment."""
        from delugeapp.core import cardsync

        travail, sauvegarde = self.base / "Carte", self.base / "Sauvegarde"
        (travail / "SONGS").mkdir(parents=True)
        (travail / "SONGS" / "A.XML").write_bytes(b"<song/>")
        remplace = sauvegarde / cardsync.LEGACY_META_DIR / "remplaces" / "x"
        remplace.mkdir(parents=True)
        cardsync.update_backup(travail, sauvegarde)
        self.assertTrue(remplace.is_dir(), "un plan seul n'écrit rien")
        cardsync.update_backup(travail, sauvegarde, apply=True)
        self.assertFalse((sauvegarde / cardsync.LEGACY_META_DIR).exists())
        self.assertTrue((sauvegarde / cardsync.META_DIR / "remplaces" / "x")
                        .is_dir())
        self.assertEqual((sauvegarde / "SONGS" / "A.XML").read_bytes(),
                         b"<song/>")

    def test_premier_lancement_sous_le_nouveau_nom(self):
        """Le vrai démarrage, dans un profil fabriqué : les deux dossiers
        sont renommés — pas copiés —, la carte enregistrée reste la copie de
        travail, et le lancement suivant ne refait rien."""
        import json
        import subprocess
        import sys
        import textwrap

        itinerant, local = self.base / "Roaming", self.base / "Local"
        conf = itinerant / self.config_mod.LEGACY_APP_ORG
        copie = local / self.config_mod.LEGACY_APP_ORG / "Carte"
        (copie / ".deluge-companion").mkdir(parents=True)
        (copie / ".deluge-companion" / "synchro.json").write_bytes(b"{}")
        conf.mkdir(parents=True)
        (conf / "settings.json").write_text(json.dumps({
            "sd_path": str(copie),
            "recent_paths": [str(copie), str(self.base / "Ailleurs")]}),
            encoding="utf-8")
        fiche = (conf / "settings.json").stat().st_ino

        env = {k: v for k, v in os.environ.items()
               if k not in (self.config_mod.CONFIG_ENV,
                            self.config_mod.LEGACY_CONFIG_ENV)}
        env.update(APPDATA=str(itinerant), LOCALAPPDATA=str(local),
                   XDG_CONFIG_HOME=str(itinerant))
        code = textwrap.dedent("""
            import json, sys
            sys.path.insert(0, sys.argv[1])
            from delugeapp import config
            from delugeapp.core import cardsync
            s = config.load_settings()
            print(json.dumps({
                "config": str(config.CONFIG_DIR),
                "travail": str(config.DEFAULT_WORK_DIR),
                "carte": s.sd_path, "recents": s.recent_paths,
                "role": s.card_role(s.sd_path),
                "synchro": cardsync.adopt_legacy_meta(s.work_path()),
                "reprises": [f for _, _, f in config.REPRISES]}))
        """)
        depot = str(Path(__file__).resolve().parent.parent)

        def lance():
            fait = subprocess.run([sys.executable, "-c", code, depot],
                                  env=env, capture_output=True, text=True,
                                  timeout=120)
            self.assertEqual(fait.returncode, 0, fait.stderr[-2000:])
            return json.loads(fait.stdout.strip().splitlines()[-1])

        neuve = str(local / self.config_mod.APP_ORG / "Carte")
        premier = lance()
        self.assertEqual(premier["config"],
                         str(itinerant / self.config_mod.APP_ORG))
        self.assertEqual(premier["travail"], neuve)
        self.assertEqual(premier["carte"], neuve)
        self.assertEqual(premier["recents"],
                         [neuve, str(self.base / "Ailleurs")])
        self.assertEqual(premier["role"], "travail")
        self.assertTrue(premier["synchro"])
        self.assertEqual(premier["reprises"], [True, True])
        self.assertFalse(conf.exists())
        self.assertFalse(copie.exists())
        self.assertEqual((Path(neuve) / ".noctiluca" / "synchro.json")
                         .read_bytes(), b"{}")
        if fiche:
            self.assertEqual((itinerant / self.config_mod.APP_ORG
                              / "settings.json").stat().st_ino, fiche,
                             "le fichier a été copié, pas renommé")

        second = lance()
        self.assertEqual(second["reprises"], [])
        self.assertFalse(second["synchro"])
        self.assertEqual((second["carte"], second["role"]),
                         (neuve, "travail"))


class TestApiPubliqueNonAppelee(unittest.TestCase):
    """Quatre fonctions publiques que rien n'appelait.

    Elles font partie de la surface documentée des modules — parallèles à
    ``genre_keys()`` ou ``scale_names()`` — mais aucun appelant ne les
    exerçait. Mortes **et** non testées, elles auraient cédé au premier
    usage. Les voici couvertes ; elles restent en place.
    """

    def test_to_bipolar_et_from_bipolar_font_un_aller_retour(self):
        for valeur in (INT32_MIN, -INT32_MAX // 2, 0, INT32_MAX // 2,
                       INT32_MAX):
            with self.subTest(valeur=valeur):
                flottant = fixedpoint.to_bipolar(valeur)
                self.assertGreaterEqual(flottant, -1.0)
                self.assertLessEqual(flottant, 1.0)
                retour = fixedpoint.from_bipolar(flottant)
                self.assertAlmostEqual(retour / INT32_MAX,
                                       valeur / INT32_MAX, places=6)

    def test_to_bipolar_garde_le_zero(self):
        self.assertEqual(fixedpoint.to_bipolar(0), 0.0)
        self.assertEqual(fixedpoint.from_bipolar(0.0), 0)

    def test_from_bipolar_sature_au_lieu_de_deborder(self):
        self.assertEqual(fixedpoint.from_bipolar(5.0), INT32_MAX)
        self.assertEqual(fixedpoint.from_bipolar(-5.0), -INT32_MAX)

    def test_from_bipolar_absorbe_les_valeurs_absurdes(self):
        for absurde in (float("nan"), None, "x"):
            with self.subTest(valeur=absurde):
                self.assertEqual(fixedpoint.from_bipolar(absurde), 0)

    def test_beat_names_liste_les_motifs_utilisables(self):
        noms = rhythm.beat_names()
        self.assertTrue(noms)
        self.assertEqual(len(noms), len(set(noms)))
        # Chaque nom doit effectivement produire un motif.
        for nom in noms:
            with self.subTest(motif=nom):
                self.assertIn(nom, rhythm._BEATS)
        self.assertIn("four_on_floor", noms)
        # La liste est une copie : la modifier ne doit rien casser.
        noms.append("intrus")
        self.assertNotIn("intrus", rhythm.beat_names())

    def test_chord_names_liste_les_accords_utilisables(self):
        noms = theory.chord_names()
        self.assertTrue(noms)
        self.assertEqual(len(noms), len(set(noms)))
        for nom in noms:
            with self.subTest(accord=nom):
                notes = theory.chord_notes(60, nom)
                self.assertTrue(notes, nom)
                self.assertTrue(all(0 <= n <= 127 for n in notes), nom)
        noms.append("intrus")
        self.assertNotIn("intrus", theory.chord_names())


# --------------------------------------------------------------------------- #
# Défauts trouvés lors de l'audit du 12 octobre 2026
# --------------------------------------------------------------------------- #

#: Preset réduit à ce qui faisait défaut : des parties que le modèle ne
#: connaît pas (modulateurs FM, affectations MIDI, synchro d'oscillateur),
#: un câble dont la profondeur dépend de **deux** sources, un attribut
#: inconnu sur un câble, une polyphonie à l'ancienne et une dernière tranche
#: sans note haute.
_PRESET_COMPLET = """<?xml version="1.0" encoding="UTF-8"?>
<sound
\tname="TEST"
\tpolyphonic="1"
\tmode="fm">
\t<osc1 type="sample" transpose="0" cents="0" retrigPhase="-1">
\t\t<sampleRanges>
\t\t\t<sampleRange rangeTopNote="60" fileName="SAMPLES/a.wav">
\t\t\t\t<zone startSamplePos="0" endSamplePos="100" />
\t\t\t</sampleRange>
\t\t\t<sampleRange fileName="SAMPLES/b.wav">
\t\t\t\t<zone startSamplePos="0" endSamplePos="200" />
\t\t\t</sampleRange>
\t\t</sampleRanges>
\t</osc1>
\t<osc2 type="square" oscillatorSync="1" />
\t<modulator1 transpose="7" cents="3" />
\t<modulator2 transpose="-5" cents="0" toModulator1="1" />
\t<midiKnobs>
\t\t<midiKnob channel="3" ccNumber="74" controlsParam="lpfFrequency" />
\t</midiKnobs>
\t<defaultParams volume="0x7FFFFFFF">
\t\t<patchCables>
\t\t\t<patchCable source="velocity" destination="volume"
\t\t\t\tamount="0x20000000" rangeAdjustable="1" />
\t\t\t<patchCable source="lfo1" destination="pitch" amount="0x03D70A3C">
\t\t\t\t<depthControlledBy>
\t\t\t\t\t<patchCable source="lfo2" amount="0x31EB850C" />
\t\t\t\t\t<patchCable source="random" amount="0x2F5C28E4" />
\t\t\t\t</depthControlledBy>
\t\t\t</patchCable>
\t\t</patchCables>
\t</defaultParams>
</sound>
"""


class TestAuditOctobre(unittest.TestCase):
    """Chaque test échoue sur le code d'avant la correction qu'il décrit."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.root = self.base / "carte"
        for sub in ("SONGS", "SYNTHS", "KITS", "SAMPLES"):
            (self.root / sub).mkdir(parents=True)
        self.sd = sdcard.SDCard(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def _preset(self) -> Path:
        path = self.root / "SYNTHS" / "TEST.XML"
        path.write_text(_PRESET_COMPLET, encoding="utf-8")
        return path

    # -- modèle : rien ne se perd à l'enregistrement ------------------------ #

    def test_dupliquer_un_preset_garde_ce_que_le_modele_ignore(self):
        """516 presets sur 911 sortaient abîmés de « Dupliquer »."""
        copie = SynthPreset.load(self._preset()).copy("TEST copie")
        doc = dxml.load(copie.save(self.root / "SYNTHS" / "C.XML",
                                   backup=False))
        self.assertEqual(doc.root.find("modulator1").get("transpose"), "7")
        self.assertEqual(doc.root.find("modulator2").get("toModulator1"), "1")
        self.assertEqual(doc.root.find("osc2").get("oscillatorSync"), "1")
        self.assertIsNotNone(doc.root.find("midiKnobs/midiKnob"))

    def test_deux_sources_de_profondeur_survivent(self):
        """La source intérieure était remplacée par la source extérieure."""
        preset = SynthPreset.load(self._preset())
        preset.save(backup=False)
        cable = [c for c in SynthPreset.load(preset.path).sound.patch_cables
                 if c.source == "lfo1"][0]
        self.assertEqual([s for s, _a in cable.depth_cables],
                         ["lfo2", "random"])
        self.assertEqual(cable.depth_cables[1][1], parse_fixed("0x2F5C28E4"))

    def test_attribut_inconnu_d_un_cable_survit(self):
        path = self._preset()
        SynthPreset.load(path).save(backup=False)
        cable = dxml.load(path).root.find(
            "defaultParams/patchCables/patchCable")
        self.assertEqual(cable.get("rangeAdjustable"), "1")

    def test_polyphonie_ancienne_non_traduite_si_inchangee(self):
        path = self._preset()
        preset = SynthPreset.load(path)
        self.assertEqual(preset.sound.polyphonic, "poly")
        preset.save(backup=False)
        self.assertEqual(dxml.load(path).root.get("polyphonic"), "1")
        preset.sound.polyphonic = "mono"
        preset.save(backup=False)
        self.assertEqual(dxml.load(path).root.get("polyphonic"), "mono")

    def test_derniere_tranche_sans_note_haute(self):
        path = self._preset()
        SynthPreset.load(path).save(backup=False)
        tranches = dxml.load(path).root.findall(
            "osc1/sampleRanges/sampleRange")
        self.assertEqual(tranches[0].get("rangeTopNote"), "60")
        self.assertIsNone(tranches[1].get("rangeTopNote"))

    def test_gammes_et_noms_de_notes_uniques(self):
        """Deux tables divergentes : « Ré# » ici, « Mib » ailleurs."""
        song = Song(root_note=3, mode_notes=[0, 2, 3, 6, 7, 8, 11])
        self.assertEqual(song.scale_name(), "Mib hongroise mineure")
        song = Song(root_note=10, mode_notes=[0, 1, 5, 7, 10])
        self.assertEqual(song.scale_name(), "Sib in sen")
        self.assertEqual(analysis.note_name(63), "Mib3")

    # -- écriture : la copie de sécurité d'abord ---------------------------- #

    def test_pas_d_ecrasement_sans_copie_de_securite(self):
        from unittest import mock

        path = self._preset()
        avant = path.read_bytes()
        doc = dxml.load(path)
        doc.root.set("name", "CHANGE")
        with mock.patch.object(dxml, "_make_backup", return_value=None):
            with self.assertRaises(dxml.DelugeXMLError):
                dxml.save(doc, path, backup=True)
        self.assertEqual(path.read_bytes(), avant)

    # -- chemins ------------------------------------------------------------ #

    def test_rel_exige_une_frontiere_de_dossier(self):
        voisin = self.base / "carte 2" / "x.wav"
        voisin.parent.mkdir()
        voisin.write_bytes(b"x")
        self.assertEqual(self.sd.rel(voisin), "x.wav")
        self.assertEqual(self.sd.rel(self.root / "SONGS" / "a.XML"),
                         "SONGS/a.XML")

    def test_un_filename_ne_sort_pas_de_la_carte(self):
        (self.base / "dehors.wav").write_bytes(b"x")
        self.assertIsNone(self.sd.resolve_sample("../dehors.wav"))
        self.assertIsNone(self.sd.resolve_sample("SAMPLES/../../dehors.wav"))

    # -- références ---------------------------------------------------------- #

    def test_relink_trouve_un_nom_echappe(self):
        """``&`` écrit ``&amp;`` dans le XML : le pré-filtre le manquait."""
        wav.write(self.root / "SAMPLES" / "Tenor & Alto.wav",
                  np.zeros(100, dtype=np.float32), 44100)
        preset = SynthPreset.new("SAX")
        preset.sound.osc1 = model_osc("SAMPLES/Tenor & Alto.wav")
        preset.save(self.root / "SYNTHS" / "SAX.XML", backup=False)
        self.assertIn(b"&amp;", (self.root / "SYNTHS" / "SAX.XML").read_bytes())
        changes = deps.relink_many(
            self.sd, {"SAMPLES/Tenor & Alto.wav": "SAMPLES/Sax.wav"},
            apply=True)
        self.assertEqual(len(changes), 1)
        self.assertEqual(
            SynthPreset.load(self.root / "SYNTHS" / "SAX.XML").sample_paths(),
            ["SAMPLES/Sax.wav"])

    def test_doublon_garde_si_ses_references_n_ont_pas_suivi(self):
        """Supprimer après une réécriture ratée cassait les presets."""
        from unittest import mock

        t = np.linspace(0, 0.1, 4410, dtype=np.float32)
        son = (0.5 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
        (self.root / "SAMPLES" / "LONG DOSSIER").mkdir()
        original = self.root / "SAMPLES" / "LONG DOSSIER" / "son.wav"
        wav.write(original, son, 44100)
        wav.write(self.root / "SAMPLES" / "son.wav", son, 44100)
        preset = SynthPreset.new("P")
        preset.sound.osc1 = model_osc("SAMPLES/LONG DOSSIER/son.wav")
        preset.save(self.root / "SYNTHS" / "P.XML", backup=False)

        lib = db.Library(self.base / "index.db")
        try:
            scan.scan_card(self.sd, lib, compute_hash=True, full=True)
            plan = organize.plan_dedupe(self.sd, lib)
            self.assertEqual([op.src for op in plan.ops], [original])
            with mock.patch.object(dxml, "save",
                                   side_effect=dxml.DelugeXMLError("plein")):
                _done, erreurs = plan.apply(self.sd, lib)
            self.assertTrue(original.exists(), "le doublon cité a disparu")
            self.assertTrue(any("conservé" in e for e in erreurs), erreurs)
        finally:
            lib.close()

    def test_l_index_suit_un_fichier_deplace(self):
        wav.write(self.root / "SAMPLES" / "seul.wav",
                  np.zeros(100, dtype=np.float32), 44100)
        lib = db.Library(self.base / "index.db")
        try:
            scan.scan_card(self.sd, lib, compute_hash=False, full=True)
            lib.set_rating("sample", "SAMPLES/seul.wav", favorite=True)
            plan = organize.plan_archive_unused(self.sd, lib)
            plan.apply(self.sd, lib)
            self.assertIsNone(lib.get("sample", "SAMPLES/seul.wav"))
            self.assertIsNotNone(lib.get("sample", "_UNUSED/seul.wav"))
            self.assertTrue(
                lib.get_rating("sample", "_UNUSED/seul.wav")["favorite"])
        finally:
            lib.close()

    def test_un_preset_ecrit_apparait_dans_l_index(self):
        lib = db.Library(self.base / "index.db")
        try:
            path = SynthPreset.new("NEUF").save(
                self.root / "SYNTHS" / "NEUF.XML", backup=False)
            self.assertIsNone(lib.get("synth", "SYNTHS/NEUF.XML"))
            scan.index_presets(self.sd, lib, [path])
            self.assertIsNotNone(lib.get("synth", "SYNTHS/NEUF.XML"))
        finally:
            lib.close()

    # -- audio ---------------------------------------------------------------- #

    def test_conversion_garde_note_et_boucle(self):
        """Le bloc ``smpl`` disparaissait : 184 fichiers bouclés sur la carte."""
        import struct

        smpl = struct.pack("<9I", 0, 0, 31250, 48, 0, 0, 0, 1, 0)
        smpl += struct.pack("<6I", 0, 0, 1000, 3000, 0, 0)
        src = self.root / "SAMPLES" / "boucle.wav"
        data = (0.5 * np.sin(np.linspace(0, 400, 8000))).astype(np.float32)
        wav.write(src, data, 32000, extra_chunks=[(b"smpl", smpl)])
        self.assertEqual(wav.probe(src).loop_start, 1000)

        mono = wav.convert(src, self.base / "dc.wav", remove_dc=True)
        self.assertEqual((mono.root_note, mono.loop_start, mono.loop_end),
                         (48, 1000, 3000))
        plus = wav.convert(src, self.base / "48k.wav", sample_rate=48000)
        self.assertEqual((plus.root_note, plus.loop_start, plus.loop_end),
                         (48, 1500, 4500))

    def test_recentrer_n_ecrete_pas(self):
        # Asymétrique, comme un kick saturé : surtout positif, avec de brèves
        # pointes à -0,99. Recentré, il descend sous -1. (Un signal
        # symétrique décalé ne prouve rien : le recentrer le ramène dans
        # ses bornes.)
        src = self.root / "SAMPLES" / "chaud.wav"
        signal = np.full(8820, 0.4, dtype=np.float32)
        signal[::100] = -0.99
        wav.write(src, signal, 44100)
        wav.convert(src, self.base / "x.wav", remove_dc=True)
        sortie, _sr = wav.read(self.base / "x.wav")
        self.assertLess(float(np.max(np.abs(sortie))), 0.9995)

    def test_rogner_epargne_un_fichier_cite_par_un_preset(self):
        t = np.zeros(4410, dtype=np.float32)
        t[2000:] = 0.5
        wav.write(self.root / "SAMPLES" / "tranche.wav", t, 44100)
        preset = SynthPreset.new("P")
        preset.sound.osc1 = model_osc("SAMPLES/tranche.wav")
        preset.save(self.root / "SYNTHS" / "P.XML", backup=False)
        lib = db.Library(self.base / "index.db")
        try:
            scan.scan_card(self.sd, lib, compute_hash=False, full=True)
            plan = samplefix.plan_custom(self.sd, lib,
                                         ["SAMPLES/tranche.wav"], trim_db=-60)
            self.assertEqual(plan.edits, [])
            self.assertIn("rognage", plan.skipped[0].skipped)
        finally:
            lib.close()

    def test_restaurer_remet_les_bornes_a_l_echelle_d_origine(self):
        wav.write(self.root / "SAMPLES" / "lent.wav",
                  (0.3 * np.sin(np.linspace(0, 300, 16000))).astype(
                      np.float32), 32000)
        preset = SynthPreset.new("P")
        preset.sound.osc1 = model_osc("SAMPLES/lent.wav", end=12000)
        path = preset.save(self.root / "SYNTHS" / "P.XML", backup=False)
        lib = db.Library(self.base / "index.db")
        try:
            scan.scan_card(self.sd, lib, compute_hash=False, full=True)
            result = samplefix.plan_standard_rate(self.sd, lib).apply(
                self.sd, lib)
            self.assertEqual(SynthPreset.load(path).sound.osc1.zone.end, 16538)
            samplefix.restore(self.sd, result.backup_dir, lib, apply=True)
            self.assertAlmostEqual(SynthPreset.load(path).sound.osc1.zone.end,
                                   12000, delta=1)
        finally:
            lib.close()

    # -- sauvegardes et export ------------------------------------------------ #

    def test_une_archive_lit_son_manifeste(self):
        wav.write(self.root / "SAMPLES" / "a.wav",
                  np.zeros(10, dtype=np.float32), 44100)
        dossier = self.base / "sauvegardes"
        backup.create_backup(self.sd, dossier, label="AVANT", zip_it=True,
                             include_samples=True)
        info = backup.list_backups(dossier)[0]
        self.assertTrue(info.zipped)
        self.assertEqual(info.label, "AVANT")
        self.assertTrue(info.include_samples)
        self.assertEqual(backup.diff_backup(info, self.sd)["removed"], [])

    def test_une_piste_audio_n_est_pas_un_preset_manquant(self):
        (self.root / "SONGS" / "S.XML").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n<song>\n'
            '<instruments>\n<audioOutput name="AUDIO 1" />\n</instruments>\n'
            '</song>\n', encoding="utf-8")
        pack = songpack.collect(self.sd, "SONGS/S.XML")
        self.assertEqual(pack.missing_presets, [])


class TestAuditOctobreSuite(unittest.TestCase):
    """Seconde passe de l'audit : index, doublons, vocabulaire du firmware."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.root = self._carte("carte")
        self.sd = sdcard.SDCard(self.root)
        self.lib = db.Library(self.base / "index.db")
        self.son = (0.5 * np.sin(np.linspace(0, 500, 20000))).astype(
            np.float32)

    def tearDown(self):
        self.lib.close()
        self._tmp.cleanup()

    def _carte(self, nom: str) -> Path:
        root = self.base / nom
        for sub in ("SONGS", "SYNTHS", "KITS", "SAMPLES"):
            (root / sub).mkdir(parents=True)
        return root

    # -- index -------------------------------------------------------------- #

    def test_un_fichier_modifie_n_est_plus_un_doublon(self):
        """L'empreinte complète gardée proposait de supprimer un fichier
        devenu différent."""
        import shutil as _sh

        wav.write(self.root / "SAMPLES" / "a.wav", self.son, 44100)
        _sh.copy(self.root / "SAMPLES" / "a.wav", self.root / "SAMPLES" / "b.wav")
        scan.scan_card(self.sd, self.lib, full=False)
        self.assertEqual(len(self.lib.duplicates()), 1)

        time.sleep(1.1)              # une date de modification différente
        autre = self.son.copy()
        autre[5000:6000] = 0
        wav.write(self.root / "SAMPLES" / "b.wav", autre, 44100)
        scan.scan_card(self.sd, self.lib, full=False)
        self.assertEqual(self.lib.duplicates(), [])
        self.assertEqual(organize.plan_dedupe(self.sd, self.lib).ops, [])

    def test_un_fichier_disparu_quitte_l_index(self):
        import shutil as _sh

        wav.write(self.root / "SAMPLES" / "x.wav", self.son[:100], 44100)
        preset = SynthPreset.new("P")
        preset.sound.osc1 = model_osc("SAMPLES/x.wav")
        preset.save(self.root / "SYNTHS" / "P.XML", backup=False)
        scan.scan_card(self.sd, self.lib, full=False)

        _sh.move(self.root / "SAMPLES" / "x.wav", self.base / "x.wav")
        scan.scan_card(self.sd, self.lib, full=False)
        self.assertIsNone(self.lib.get("sample", "SAMPLES/x.wav"))
        self.assertEqual([r["dst_rel"] for r in self.lib.missing_links()],
                         ["SAMPLES/x.wav"])

        _sh.move(self.base / "x.wav", self.root / "SAMPLES" / "x.wav")
        scan.scan_card(self.sd, self.lib, full=False)
        self.assertEqual(self.lib.missing_links(), [],
                         "la référence d'un échantillon revenu reste cassée")

    def test_l_index_d_une_autre_carte_est_ecarte(self):
        """Les empreintes d'une carte s'appliquaient aux fichiers de même
        chemin d'une autre."""
        import shutil as _sh

        wav.write(self.root / "SAMPLES" / "a.wav", self.son, 44100)
        _sh.copy2(self.root / "SAMPLES" / "a.wav", self.root / "SAMPLES" / "b.wav")
        scan.scan_card(self.sd, self.lib)

        autre_racine = self._carte("autre")
        wav.write(autre_racine / "SAMPLES" / "a.wav", self.son, 44100)
        different = self.son.copy()
        different[:10] = 0
        wav.write(autre_racine / "SAMPLES" / "b.wav", different, 44100)
        autre = sdcard.SDCard(autre_racine)
        self.assertTrue(scan.forget_other_card(autre, self.lib))
        self.assertEqual(organize.plan_dedupe(autre, self.lib).ops, [])
        self.assertFalse(scan.forget_other_card(self.sd, self.lib),
                         "un index vidé ne décrit plus aucune carte")

    def test_un_doublon_qui_ne_l_est_plus_n_est_pas_supprime(self):
        """Dernier filet, indépendant de l'index : l'octet près."""
        import shutil as _sh

        wav.write(self.root / "SAMPLES" / "a.wav", self.son, 44100)
        (self.root / "SAMPLES" / "LONG").mkdir()
        cible = self.root / "SAMPLES" / "LONG" / "a.wav"
        _sh.copy(self.root / "SAMPLES" / "a.wav", cible)
        scan.scan_card(self.sd, self.lib)
        plan = organize.plan_dedupe(self.sd, self.lib)
        self.assertEqual([op.src for op in plan.ops], [cible])
        # Le fichier change entre l'analyse et l'application du plan.
        donnees = bytearray(cible.read_bytes())
        donnees[-1] ^= 0xFF
        cible.write_bytes(bytes(donnees))
        _done, erreurs = plan.apply(self.sd, self.lib)
        self.assertTrue(cible.exists())
        self.assertTrue(any("octet pour octet" in e for e in erreurs))

    # -- vocabulaire du firmware --------------------------------------------- #

    def test_un_cable_vise_le_nom_de_destination_du_firmware(self):
        from delugeapp.core.model import PatchCable

        preset = SynthPreset.new("PW")
        preset.sound.patch_cables = [
            PatchCable("lfo1", "oscAPulseWidth", 0x10000000),
            PatchCable("lfo2", "bitCrush", 0x10000000),
            PatchCable("envelope2", "lpfFrequency", 0x10000000)]
        path = preset.save(self.root / "SYNTHS" / "PW.XML", backup=False)
        cibles = [c.get("destination") for c in
                  dxml.load(path).root.iter("patchCable")]
        self.assertEqual(cibles,
                         ["oscAPhaseWidth", "bitcrushAmount", "lpfFrequency"])

    def test_l_ecoute_entend_un_cable_de_largeur_d_impulsion(self):
        from delugeapp.core.model import PatchCable

        son = SynthPreset.new("PW").sound
        son.patch_cables = [PatchCable("lfo1", "oscAPhaseWidth", 0x20000000)]
        mods = render._modulations(son, 100, 44100,
                                   {"lfo1": np.ones(100, dtype=np.float32)})
        self.assertIn("oscAPulseWidth", mods)

    def test_le_generateur_n_ecrit_que_des_noms_connus_du_firmware(self):
        """Noms relevés dans le code du firmware communautaire."""
        filtres = {"24dB", "12dB", "24dBDrive", "SVF_Band", "SVF_Notch",
                   "HPLadder", "Off"}
        effets = {"none", "flanger", "chorus", "phaser", "StereoChorus",
                  "TapeWarble", "dimension", "grainFX"}
        lfos = {"sine", "triangle", "square", "saw", "sah", "rwalk",
                "warbler"}
        vus = set()
        for genre in genres.genre_keys():
            for role in synthgen.ROLES:
                for graine in range(4):
                    son = synthgen.generate(synthgen.GenOptions(
                        genre=genre, role=role, seed=graine)).sound
                    vus |= {("filtre", son.lpf_mode), ("effet", son.mod_fx_type),
                            ("lfo", son.lfo1.type), ("lfo", son.lfo2.type)}
        inconnus = sorted(
            (k, v) for k, v in vus
            if v not in {"filtre": filtres, "effet": effets, "lfo": lfos}[k])
        self.assertEqual(inconnus, [])

    def test_ancienne_polyphonie_numerique(self):
        """Firmware : 0 = auto, 2 = choke, tout autre nombre = poly."""
        attendu = {"0": "auto", "1": "poly", "2": "choke", "3": "poly",
                   "4": "poly"}
        for brut, mode in attendu.items():
            with self.subTest(valeur=brut):
                el = dxml.loads(('<sound polyphonic="%s" />' % brut).encode()).root
                self.assertEqual(Sound.from_xml(el).polyphonic, mode)

    # -- divers --------------------------------------------------------------- #

    def test_un_preset_cite_par_un_morceau_n_est_pas_renomme(self):
        for nom in ("Cite.", "Libre."):
            SynthPreset.new(nom).save(self.root / "SYNTHS" / f"{nom}.XML",
                                      backup=False)
        (self.root / "SONGS" / "S.XML").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n<song>\n<instruments>\n'
            '<sound presetName="Cite." presetFolder="SYNTHS" />\n'
            '</instruments>\n</song>\n', encoding="utf-8")
        scan.scan_card(self.sd, self.lib)
        cibles = [op.src.name for op in
                  organize.plan_fix_names(self.sd, self.lib).ops]
        self.assertIn("Libre..XML", cibles)
        self.assertNotIn("Cite..XML", cibles)

    def test_midi_follow_ne_lit_que_les_assignations(self):
        from delugeapp.core import midifollow

        fichier = self.base / "MIDIFollow.XML"
        fichier.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n<defaults>\n'
            '<defaultCCMappings><lpfFrequency>74</lpfFrequency>'
            '</defaultCCMappings>\n<pan>3</pan>\n</defaults>\n',
            encoding="utf-8")
        self.assertEqual(midifollow.load_map(path=fichier),
                         {"lpfFrequency": 74})

    def test_restaurer_garde_une_copie_de_ce_qu_on_ecrase(self):
        """La restauration écrasait le travail récent sans recours."""
        preset = self.root / "SYNTHS" / "P.XML"
        preset.write_text("<sound name='ANCIEN' />", encoding="utf-8")
        dossier = self.base / "sauvegardes"
        backup.create_backup(self.sd, dossier, label="vieille")
        preset.write_text("<sound name='RECENT' />", encoding="utf-8")

        vieille = backup.list_backups(dossier)[0]
        restaures, erreurs = backup.restore_backup(vieille, self.sd,
                                                   safety_dir=dossier)
        self.assertEqual((restaures, erreurs), (1, []))
        self.assertIn("ANCIEN", preset.read_text(encoding="utf-8"))
        abri = [b for b in backup.list_backups(dossier)
                if b.label == "avant restauration"]
        self.assertEqual(len(abri), 1)
        self.assertIn("RECENT", (abri[0].path / "SYNTHS" / "P.XML").read_text(
            encoding="utf-8"))

    def test_pas_de_sauvegarde_dans_les_dossiers_de_la_carte(self):
        with self.assertRaises(OSError):
            backup.create_backup(self.sd, self.root / "SAMPLES" / "copie")
        self.assertFalse((self.root / "SAMPLES" / "copie").exists())

    def test_le_swing_survit_au_jeu_sur_la_machine(self):
        """Un pas à 2,5 partait au pas 2 : le swing disparaissait."""
        from delugeapp.core.delugelink import DelugeLink

        motif = rhythm.Pattern(steps=4)
        motif.add("Kick", rhythm.Step(pos=0))
        motif.add("Kick", rhythm.Step(pos=2.5))
        lien = DelugeLink()
        fausse = _SortieFactice()
        lien._out = fausse
        self.assertTrue(lien.play_pattern(motif, bpm=240,
                                          row_notes={"Kick": 36}))
        for _ in range(300):
            if not lien.is_playing:
                break
            time.sleep(0.01)
        frappes = fausse.temps_des("on", 36)
        duree_pas = 60.0 / 240 * motif.ticks_per_step / motif.ppq
        self.assertEqual(len(frappes), 2)
        self.assertAlmostEqual(frappes[1] - frappes[0], 2.5 * duree_pas,
                               delta=0.02)


def model_osc(file_name: str, end: int = -1):
    """Oscillateur jouant un fichier, zone en échantillons."""
    from delugeapp.core.model import Osc, Zone

    return Osc(type="sample", file_name=file_name,
               zone=Zone(start=0, end=end, unit="samples"))


class TestNomsCourtsDeFAT(unittest.TestCase):
    """Un kit d'usine (« 030 Chaz Bundick ») cite deux échantillons par leur
    nom court de FAT, « CB1-BD~1.WAV » pour « CB1-bdrum1.wav ». Le Deluge
    les trouve (``ff.c``, « SFN matched? ») ; l'application ne les trouvait
    que par les noms courts que Windows fabrique, et l'index les tenait pour
    inutilisés — l'archivage proposait de les déplacer."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "carte"
        for sub in ("SONGS", "SYNTHS", "KITS"):
            (self.root / sub).mkdir(parents=True)
        self.dossier = self.root / "SAMPLES/Artists/Chaz"
        _son(self.dossier / "CB1-bdrum1.wav", 60.0)
        _son(self.dossier / "CB3-bell.wav", 880.0)
        kit = Kit.new("030 Chaz Bundick")
        kit.add_row("KICK", "SAMPLES/ARTISTS/CHAZ/CB1-BD~1.WAV")
        kit.add_row("BELL", "SAMPLES/ARTISTS/CHAZ/CB3-BELL.WAV")
        self.kit = self.root / "KITS" / "030 Chaz Bundick.XML"
        kit.save(self.kit, backup=False)
        self.sd = sdcard.SDCard(self.root)
        self.lib = db.Library(Path(self._tmp.name) / "index.db")

    def tearDown(self):
        self.lib.close()
        self._tmp.cleanup()

    def test_les_regles_de_fatfs(self):
        corr = sdcard.short_name_matches
        self.assertTrue(corr("CB1-BD~1.WAV", "CB1-bdrum1.wav"))
        self.assertTrue(corr("cb1-bd~1.wav", "CB1-bdrum1.wav"))
        self.assertTrue(corr("MYKICK~1.WAV", "My Kick.wav"))      # espace ôté
        self.assertTrue(corr("KICK~1.AIF", "kick.aiff"))           # extension
        self.assertTrue(corr("A_B~1.WAV", "a+b.wav"))              # « + » → « _ »
        self.assertTrue(corr("BASSLI~2.WAV", "Bass line 2.wav"))
        # Un nom qui tient en 8.3 n'est jamais numéroté.
        self.assertFalse(corr("CB1-BD~1.WAV", "CB1-bd.wav"))
        self.assertFalse(corr("CB1-BD~1.WAV", "CB1-bdrum1.aif"))
        self.assertFalse(corr("CB1-BD~1.WAV", "CB2-bdrum2.wav"))
        self.assertFalse(corr("CB1-bdrum1.wav", "CB1-bdrum1.wav"))
        self.assertEqual(sdcard.short_name_basis("CB1-bdrum1.wav"),
                         ("CB1-BDRU", "WAV", True))

    def test_le_nom_court_mene_au_nom_long(self):
        trouve = self.sd.resolve_sample("SAMPLES/ARTISTS/CHAZ/CB1-BD~1.WAV")
        self.assertIsNotNone(trouve)
        # Le nom long, pas un nom court que Windows aurait fabriqué.
        self.assertEqual(trouve.name, "CB1-bdrum1.wav")

    def test_deux_candidats_ne_se_departagent_pas(self):
        _son(self.dossier / "CB1-bdrum2.wav", 70.0)
        self.sd.invalidate_cache()
        self.assertIsNone(
            self.sd.resolve_sample("SAMPLES/ARTISTS/CHAZ/CB1-BD~1.WAV"))

    def test_l_index_compte_l_echantillon_comme_utilise(self):
        scan.scan_card(self.sd, self.lib, compute_hash=False)
        self.assertEqual(self.lib.missing_links(), [])
        inutiles = [r["rel"] for r in self.lib.unused_samples()]
        self.assertNotIn("SAMPLES/Artists/Chaz/CB1-bdrum1.wav", inutiles)
        plan = organize.plan_archive_unused(self.sd, self.lib)
        self.assertEqual([op.src.name for op in plan.ops], [])
        rapport = health.check_card(self.sd, self.lib)
        self.assertNotIn("MISSING_SAMPLE", [i.code for i in rapport.issues])
        self.assertNotIn("ORPHAN_SAMPLE", [i.code for i in rapport.issues])

    def test_un_rangement_reecrit_aussi_le_nom_court(self):
        scan.scan_card(self.sd, self.lib, compute_hash=False)
        cible = self.root / "SAMPLES/DRUMS/Kick/CB1-bdrum1.wav"
        plan = organize.Plan(ops=[organize.Op(
            "move", self.dossier / "CB1-bdrum1.wav", cible)])
        _faits, erreurs = plan.apply(self.sd, self.lib)
        self.assertEqual(erreurs, [])
        relu = Kit.load(self.kit)
        noms = [r.file_name for r in relu.rows]
        self.assertIn("SAMPLES/DRUMS/Kick/CB1-bdrum1.wav", noms)
        # La cloche, citée par son nom long, n'a pas bougé.
        self.assertIn("SAMPLES/ARTISTS/CHAZ/CB3-BELL.WAV", noms)
        self.assertIsNotNone(self.sd.resolve_sample(noms[0]))

    def test_un_nom_court_n_est_pas_redirige_s_il_peut_en_designer_un_autre(self):
        _son(self.dossier / "CB1-bdrum2.wav", 70.0)
        self.sd.invalidate_cache()
        avant = self.kit.read_bytes()
        plan = organize.Plan(ops=[organize.Op(
            "move", self.dossier / "CB1-bdrum1.wav",
            self.root / "SAMPLES/DRUMS/Kick/CB1-bdrum1.wav")])
        plan.apply(self.sd, self.lib)
        self.assertEqual(self.kit.read_bytes(), avant)

    def test_un_morceau_qui_cite_le_nom_court_protege_le_fichier(self):
        (self.root / "SONGS" / "M.XML").write_bytes(
            b'<song firmwareVersion="3.0.4" timePerTimerTick="459"'
            b' timerTickFraction="1610612736" inputTickMagnitude="1">'
            b'<instruments><sound presetName="X"><osc1 type="sample"'
            b' fileName="SAMPLES/ARTISTS/CHAZ/CB1-BD~1.WAV">'
            b'<zone startSamplePos="0" endSamplePos="1000"/>'
            b'</osc1></sound></instruments></song>')
        verrous = samplefix.song_locked_samples(self.sd)
        self.assertIn("samples/artists/chaz/cb1-bdrum1.wav", verrous)

    def test_le_recalage_des_bornes_suit_le_nom_court(self):
        kit = Kit.load(self.kit)
        zone = kit.rows[0].sound.osc1.zone
        zone.unit, zone.start, zone.end = "samples", 0, 1000
        kit.save(self.kit, backup=False)
        moved, fichiers = samplefix.retarget_zones(
            self.sd, {"samples/artists/chaz/cb1-bdrum1.wav": 0.5}, apply=True)
        self.assertGreater(moved, 0)
        self.assertEqual(Kit.load(self.kit).rows[0].sound.osc1.zone.end, 500)
