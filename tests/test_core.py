# -*- coding: utf-8 -*-
"""Tests du noyau de Noctiluca.

Ces tests s'exécutent **sans carte SD** : chacun fabrique au besoin une carte
factice dans un dossier temporaire (cf. SPEC §7). Ils n'importent jamais Qt,
ce qui permet de les lancer sur une machine sans affichage :

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

# --------------------------------------------------------------------------- #
# Bac à sable — avant tout import de ``delugeapp``
# --------------------------------------------------------------------------- #
# Rien ici ne doit toucher aux réglages réels de l'utilisateur. Ce n'est pas
# une précaution théorique : c'est arrivé trois fois, et la dernière a éteint
# ``confirm_writes`` et ``always_backup_before_write`` — les deux filets qui
# protègent une carte contenant des mois de travail.
#
# Ces quatre lignes doivent rester **au-dessus** de l'import de ``delugeapp``,
# qui calcule ses chemins au moment de l'import. Elles sont répétées dans
# chaque module de test, et non dans ``tests/__init__.py`` : ``unittest
# discover`` charge les modules à plat, sans importer le paquet.
#
# ``TestDossierDeConfiguration.test_la_suite_n_ecrit_pas_chez_l_utilisateur``
# échoue si on les retire.
import os as _os                                             # noqa: E402
import tempfile as _tempfile                                 # noqa: E402

BAC_A_SABLE = Path(_tempfile.gettempdir()) / "noctiluca-tests"
BAC_A_SABLE.mkdir(parents=True, exist_ok=True)
_os.environ["NOCTILUCA_CONFIG"] = str(BAC_A_SABLE)


from delugeapp.core import (accomp, analysis, backup, db, deps, dxml, genres,
                            health, kitgen, midifile, organize, render,
                            rhythm, samplefix, scan, sdcard, similarity,
                            sketch, slicer, songpack, synthgen, theory,
                            units, wav)
from delugeapp.core import fixedpoint
from delugeapp.core.fixedpoint import (
    INT32_MAX,
    INT32_MIN,
    format_fixed,
    from_display,
    from_unit,
    parse_fixed,
    to_display,
    to_unit,
)
from delugeapp.core.model import (
    Kit,
    Note,
    Song,
    Sound,
    SynthPreset,
    decode_notes,
    encode_notes,
    tempo_from_song_attrs,
)


# --------------------------------------------------------------------------- #
# Virgule fixe (SPEC §1.4)
# --------------------------------------------------------------------------- #

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
# Analyse acoustique
# --------------------------------------------------------------------------- #

class TestAnalysis(unittest.TestCase):
    """Mesures acoustiques, vérifiées sur des signaux de réponse connue."""

    SR = 44100
    MAJOR = [0, 2, 4, 5, 7, 9, 11]
    MINOR = [0, 2, 3, 5, 7, 8, 10]

    def _clicks(self, bpm: float, seconds: float = 8.0) -> np.ndarray:
        """Train de clics percussifs au tempo demandé."""
        n = int(self.SR * seconds)
        out = np.zeros(n, dtype=np.float32)
        decay = np.exp(-np.arange(400) / 60.0).astype(np.float32)
        click = (decay * np.sin(2 * np.pi * 120 * np.arange(400) / self.SR)
                 ).astype(np.float32)
        period = 60.0 / bpm
        for k in range(int(seconds / period)):
            i = int(k * period * self.SR)
            if i + 400 < n:
                out[i:i + 400] += click
        return out

    def _melody(self, root: int, scale: list[int],
                seconds: float = 6.0) -> np.ndarray:
        """Gamme jouée au-dessus d'une basse tenue sur la tonique."""
        n = int(self.SR * seconds)
        out = np.zeros(n, dtype=np.float32)
        seq = scale + [s + 12 for s in scale]
        step = n // len(seq)
        for i, s in enumerate(seq):
            freq = 440.0 * 2 ** ((root + s - 69) / 12)
            t = np.linspace(0, step / self.SR, step, endpoint=False,
                            dtype=np.float32)
            out[i * step:(i + 1) * step] += (
                np.exp(-t * 3) * np.sin(2 * np.pi * freq * t)).astype(np.float32)
        t = np.linspace(0, seconds, n, endpoint=False, dtype=np.float32)
        bass = 440.0 * 2 ** ((root - 12 - 69) / 12)
        out += (0.6 * np.sin(2 * np.pi * bass * t)).astype(np.float32)
        return (out / np.max(np.abs(out))).astype(np.float32)

    def test_tempo(self):
        """Le tempo doit être retrouvé à moins de 2,5 BPM près."""
        for bpm in (70, 90, 100, 120, 128, 140, 174):
            with self.subTest(bpm=bpm):
                got, confidence = analysis.detect_bpm(self._clicks(bpm), self.SR)
                self.assertAlmostEqual(got, bpm, delta=2.5)
                self.assertGreater(confidence, 0.3)

    def test_tempo_sans_ambiguite_d_octave(self):
        """128 BPM ne doit pas être rendu comme 64 BPM.

        L'autocorrélation d'une mesure à 128 BPM culmine aussi à 64 : retenir
        la première valeur de l'intervalle donnait la moitié du tempo.
        """
        got, _ = analysis.detect_bpm(self._clicks(128), self.SR)
        self.assertAlmostEqual(got, 128, delta=2.5)

    def test_tempo_signal_inexploitable(self):
        """Un signal trop court ou muet rend (0, 0) sans lever."""
        self.assertEqual(analysis.detect_bpm(np.zeros(100, dtype=np.float32),
                                             self.SR), (0.0, 0.0))
        self.assertEqual(analysis.detect_bpm(np.zeros(0, dtype=np.float32),
                                             self.SR), (0.0, 0.0))

    def test_chromagramme(self):
        """Une gamme majeure ne doit rien poser sur ses notes étrangères."""
        chroma = analysis.chromagram(self._melody(60, self.MAJOR), self.SR)
        self.assertAlmostEqual(float(chroma.sum()), 1.0, places=5)
        self.assertEqual(int(np.argmax(chroma)), 0)       # Do domine
        for foreign in (1, 3, 6, 8, 10):                  # Do# Ré# Fa# Sol# La#
            with self.subTest(classe=foreign):
                self.assertLess(chroma[foreign], 0.02)

    def test_tonalite_majeure_et_mineure(self):
        """La tonalité doit distinguer une majeure de sa relative mineure.

        C'est la difficulté propre à l'exercice : Do majeur et La mineur ont
        les mêmes notes. Seule une tonique nettement posée les sépare.
        """
        cas = [(60, self.MAJOR, "C"), (53, self.MAJOR, "F"),
               (55, self.MAJOR, "G"), (62, self.MAJOR, "D"),
               (57, self.MINOR, "Am"), (52, self.MINOR, "Em"),
               (50, self.MINOR, "Dm"), (60, self.MINOR, "Cm")]
        for root, scale, expected in cas:
            with self.subTest(attendu=expected):
                got, confidence = analysis.detect_key(
                    self._melody(root, scale), self.SR)
                self.assertEqual(got, expected)
                self.assertGreater(confidence, 0.2)

    def test_tonalite_signal_vide(self):
        self.assertEqual(analysis.detect_key(np.zeros(0, dtype=np.float32),
                                             self.SR), ("", 0.0))

    def test_fondamentale(self):
        """La fondamentale doit résister à une harmonique plus forte qu'elle."""
        for midi in (36, 48, 60, 69, 81):
            with self.subTest(midi=midi):
                freq = 440.0 * 2 ** ((midi - 69) / 12)
                t = np.linspace(0, 1.0, self.SR, endpoint=False,
                                dtype=np.float32)
                # Fondamentale faible, harmonique 2 dominante : le piège.
                signal = (0.3 * np.sin(2 * np.pi * freq * t)
                          + 1.0 * np.sin(2 * np.pi * 2 * freq * t)
                          + 0.5 * np.sin(2 * np.pi * 3 * freq * t)
                          ).astype(np.float32)
                self.assertEqual(analysis.estimate_root_note(signal, self.SR),
                                 midi)

    def test_fondamentale_sur_du_bruit(self):
        """Du bruit blanc n'a pas de fondamentale."""
        rng = np.random.default_rng(7)
        noise = rng.standard_normal(self.SR).astype(np.float32) * 0.2
        self.assertIsNone(analysis.estimate_root_note(noise, self.SR))

    def test_nom_de_note(self):
        """Convention de la SPEC : MIDI 60 = Do3 / C3."""
        self.assertEqual(analysis.note_name(60), "Do3")
        self.assertEqual(analysis.note_name(60, french=False), "C3")
        self.assertEqual(analysis.note_name(61), "Do#3")
        self.assertEqual(analysis.note_name(59), "Si2")
        self.assertEqual(analysis.note_name("x"), "")

    def test_niveaux(self):
        """Crête, RMS et facteur de crête sur une sinusoïde connue."""
        t = np.linspace(0, 1, self.SR, endpoint=False, dtype=np.float32)
        sine = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        out = analysis.loudness(sine)
        self.assertAlmostEqual(out["peak_db"], -6.02, delta=0.2)
        self.assertAlmostEqual(out["rms_db"], -9.03, delta=0.2)
        self.assertAlmostEqual(out["crest"], 1.414, delta=0.05)
        self.assertAlmostEqual(out["dc_offset"], 0.0, delta=1e-3)
        self.assertEqual(out["clipped"], 0.0)

    def test_niveaux_offset_et_ecretage(self):
        """Un offset continu et un écrêtage doivent être signalés."""
        t = np.linspace(0, 1, self.SR, endpoint=False, dtype=np.float32)
        decale = (0.2 * np.sin(2 * np.pi * 440 * t) + 0.3).astype(np.float32)
        self.assertAlmostEqual(analysis.loudness(decale)["dc_offset"], 0.3,
                               delta=0.01)
        ecrete = np.clip(2.0 * np.sin(2 * np.pi * 440 * t), -1.0, 1.0
                         ).astype(np.float32)
        self.assertGreater(analysis.loudness(ecrete)["clipped"], 0.3)

    def test_niveaux_signal_vide(self):
        out = analysis.loudness(np.zeros(0, dtype=np.float32))
        self.assertEqual(out["peak_db"], -120.0)

    def test_bornes_de_silence(self):
        """Le silence de tête et de queue doit être localisé."""
        signal = np.zeros(10000, dtype=np.float32)
        signal[3000:7000] = 0.5
        start, end = analysis.silence_bounds(signal)
        self.assertAlmostEqual(start, 3000, delta=50)
        self.assertAlmostEqual(end, 7000, delta=50)
        # Un fichier muet se reconnaît à (0, 0).
        self.assertEqual(analysis.silence_bounds(
            np.zeros(10000, dtype=np.float32)), (0, 0))

    def test_descripteurs_spectraux(self):
        """Un son grave et un son aigu doivent se distinguer nettement."""
        t = np.linspace(0, 1, self.SR, endpoint=False, dtype=np.float32)
        grave = (0.5 * np.sin(2 * np.pi * 80 * t)).astype(np.float32)
        aigu = (0.5 * np.sin(2 * np.pi * 8000 * t)).astype(np.float32)
        bas = analysis.spectral(grave, self.SR)
        haut = analysis.spectral(aigu, self.SR)
        self.assertLess(bas["centroid"], 1000)
        self.assertGreater(haut["centroid"], 5000)
        self.assertGreater(bas["low_ratio"], 0.5)
        self.assertGreater(haut["high_ratio"], 0.5)
        # Le bruit blanc est spectralement plus plat qu'une sinusoïde.
        rng = np.random.default_rng(3)
        bruit = rng.standard_normal(self.SR).astype(np.float32) * 0.3
        self.assertGreater(analysis.spectral(bruit, self.SR)["flatness"],
                           bas["flatness"])

    def test_attaques(self):
        """Les attaques d'un train de clics doivent être comptées."""
        hits = analysis.transients(self._clicks(120, seconds=4.0), self.SR)
        self.assertGreaterEqual(len(hits), 6)
        self.assertLessEqual(len(hits), 12)
        self.assertTrue(bool(np.all(np.diff(hits) > 0)))

    def test_classement_percussions(self):
        """Le nom du fichier doit primer, sans se laisser piéger.

        Trois pièges mesurés sur la vraie carte :
        le nom de machine (« 808 Clap » n'est pas une grosse caisse),
        le charleston ouvert (« 808 Open hihat »),
        et le chiffre du modèle (« DDD1 Tom low » est un tom grave).
        """
        neutre = {"duration": 0.3}
        spec = {"centroid": 1000.0, "low_ratio": 0.2, "high_ratio": 0.2,
                "flatness": 0.1}
        cas = [
            ("808 Clap.wav", "Clap"),
            ("808 Cowbell.wav", "Cowbell"),
            ("808 Conga low.wav", "ConL"),
            ("808 Conga high.wav", "ConH"),
            ("808 Open hihat.wav", "HatO"),
            ("909 Closed hihat.wav", "HatC"),
            ("DDD1 Tom low.wav", "TomL"),
            ("R100 Conga low.wav", "ConL"),
            ("Linndrum Conga extra high.wav", "ConH"),
            ("SDS5 Kick.wav", "Kick"),
            ("Acoustic Snare 3.wav", "Snare"),
            ("CR78 Cymbal.wav", "Crash"),
            ("Tom 1.wav", "TomH"),
        ]
        for name, expected in cas:
            with self.subTest(fichier=name):
                self.assertEqual(
                    analysis.classify_drum(name, neutre, spec), expected)

    def test_classement_sans_indice_de_nom(self):
        """Sans nom parlant, le spectre prend le relais."""
        kick = analysis.classify_drum(
            "01.wav", {"duration": 0.4},
            {"centroid": 150.0, "low_ratio": 0.8, "high_ratio": 0.01,
             "flatness": 0.05})
        self.assertEqual(kick, "Kick")
        hat = analysis.classify_drum(
            "02.wav", {"duration": 0.1},
            {"centroid": 9000.0, "low_ratio": 0.01, "high_ratio": 0.6,
             "flatness": 0.4})
        self.assertEqual(hat, "HatC")
        # Données absurdes : pas d'exception, catégorie de repli.
        self.assertEqual(analysis.classify_drum("x.wav", {}, {}), "Other")
        self.assertEqual(analysis.classify_drum(None, None, None), "Other")


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
# Profils de genre
# --------------------------------------------------------------------------- #

class TestGenres(unittest.TestCase):
    """Profils sonores par genre."""

    def test_genres_exiges(self):
        """La SPEC §4.15 en exige au moins 18, et nomme lesquels."""
        requis = ("acid", "techno", "detroit", "minimal", "house",
                  "deep_house", "trance", "psytrance", "dnb", "jungle",
                  "dubstep", "ambient", "berlin_school", "synthwave", "lofi",
                  "idm", "industrial", "electro", "hardcore", "downtempo",
                  "funk", "boards_of_canada")
        self.assertGreaterEqual(len(genres.GENRES), 18)
        for key in requis:
            with self.subTest(genre=key):
                self.assertIn(key, genres.GENRES)

    def test_profils_complets(self):
        """Chaque profil doit être exploitable par le générateur."""
        for key in genres.genre_keys():
            with self.subTest(genre=key):
                profile = genres.genre(key)
                self.assertTrue(profile.description)
                self.assertTrue(profile.label)
                self.assertRegex(profile.color, r"^#[0-9A-Fa-f]{6}$")
                self.assertLess(profile.bpm[0], profile.bpm[1])
                self.assertGreater(profile.bpm[0], 30)
                self.assertLess(profile.bpm[1], 300)
                self.assertTrue(profile.osc_types)
                self.assertTrue(profile.filter_mode)
                self.assertTrue(profile.cable_recipes)
                self.assertLessEqual(profile.cutoff[0], profile.cutoff[1])

    def test_genre_inconnu(self):
        """Une clé inconnue ne lève pas : elle retombe sur la techno."""
        self.assertEqual(genres.genre("pas un genre").key,
                         genres.FALLBACK_GENRE)
        self.assertEqual(genres.genre("").key, genres.FALLBACK_GENRE)
        self.assertEqual(genres.genre(None).key, genres.FALLBACK_GENRE)

    def test_surcharge_par_role(self):
        """Un rôle modifie le profil sans abîmer l'original."""
        base = genres.genre("acid")
        avant = base.cutoff
        basse = base.for_role("bass")
        nappe = base.for_role("pad")
        self.assertNotEqual(basse.cutoff, nappe.cutoff)
        self.assertEqual(base.cutoff, avant, "le profil d'origine a été modifié")
        # Une surcharge partielle garde les autres clés de l'enveloppe.
        self.assertEqual(set(nappe.env1), {"attack", "decay", "sustain",
                                           "release"})

    def test_role_inconnu(self):
        base = genres.genre("techno")
        self.assertIs(base.for_role("pas un role"), base)

    def test_genres_par_tempo(self):
        self.assertIn("techno", genres.genres_for_bpm(132))
        self.assertIn("ambient", genres.genres_for_bpm(70))
        self.assertEqual(genres.genres_for_bpm("x"), [])


# --------------------------------------------------------------------------- #
# Générateur de presets
# --------------------------------------------------------------------------- #

class TestSynthGen(unittest.TestCase):
    """Génération de presets : reproductibilité et audibilité."""

    def _audible(self, preset) -> tuple[bool, str]:
        """Vérifie qu'un preset produit réellement du son."""
        from delugeapp.core.fixedpoint import to_display

        sound = preset.sound
        if sound.display("volume") < 20:
            return False, "volume général trop bas"
        if not sound.osc1.is_audible:
            return False, f"osc1 muet (type {sound.osc1.type!r} sans fichier)"
        if sound.display("oscAVolume") < 10:
            return False, "oscillateur 1 inaudible"
        if (to_display(sound.env1.sustain) <= 0
                and to_display(sound.env1.decay) <= 0):
            return False, "enveloppe sans sustain ni decay"
        opens = any(c.destination in ("lpfFrequency", "lpfMorph")
                    and c.amount > 0 for c in sound.patch_cables)
        if sound.display("lpfFrequency") < 8 and not opens:
            return False, "filtre fermé sans modulation qui l'ouvre"
        return True, ""

    def test_reproductibilite(self):
        """Une même graine doit redonner exactement le même son."""
        opts = synthgen.GenOptions(genre="acid", role="bass", seed=42)
        a = synthgen.generate(opts)
        b = synthgen.generate(opts)
        self.assertEqual(a.sound, b.sound)
        autre = synthgen.generate(
            synthgen.GenOptions(genre="acid", role="bass", seed=43))
        self.assertNotEqual(a.sound, autre.sound)

    def test_n_utilise_pas_le_hasard_global(self):
        """``random.seed()`` ne doit pas influencer la génération.

        C'est l'exigence de la SPEC §4.16 : le tirage passe par une instance
        ``random.Random`` propre, sinon deux générations identiques en
        apparence divergent dès qu'un autre module touche au hasard global.
        """
        import random as _random

        opts = synthgen.GenOptions(genre="techno", role="lead", seed=11)
        _random.seed(1)
        first = synthgen.generate(opts)
        _random.seed(999)
        second = synthgen.generate(opts)
        self.assertEqual(first.sound, second.sound)

    def test_toujours_audible(self):
        """Tous les genres, tous les rôles : aucun preset muet."""
        for key in genres.genre_keys():
            for role in genres.ROLES:
                for seed in (0, 1, 2, 3):
                    with self.subTest(genre=key, role=role, seed=seed):
                        preset = synthgen.generate(synthgen.GenOptions(
                            genre=key, role=role, seed=seed))
                        ok, why = self._audible(preset)
                        self.assertTrue(ok, f"{key}/{role}/{seed} : {why}")

    def test_wavetable_sans_fichier_est_evitee(self):
        """``wavetable`` est un type lu depuis la carte : muet sans fichier.

        Trois genres le proposent ; le générateur doit l'écarter quand aucun
        échantillon n'est fourni.
        """
        for key in ("ambient", "idm", "boards_of_canada"):
            for seed in range(12):
                with self.subTest(genre=key, seed=seed):
                    preset = synthgen.generate(synthgen.GenOptions(
                        genre=key, role="pad", seed=seed))
                    self.assertTrue(preset.sound.osc1.is_audible)

    def test_curseurs(self):
        """Chaque curseur doit avoir un effet mesurable."""
        def gen(**kw):
            return synthgen.generate(synthgen.GenOptions(
                genre="techno", role="bass", seed=1, **kw)).sound

        sombre, clair = gen(brightness=0.0), gen(brightness=1.0)
        self.assertLess(sombre.display("lpfFrequency"),
                        clair.display("lpfFrequency"))
        sec, large = gen(space=0.0), gen(space=1.0)
        self.assertLessEqual(sec.display("reverbAmount"),
                             large.display("reverbAmount"))
        simple, complexe = gen(complexity=0.0), gen(complexity=1.0)
        self.assertLess(len(simple.patch_cables), len(complexe.patch_cables))
        etroit, ample = gen(width=0.0), gen(width=1.0)
        self.assertLessEqual(etroit.unison_detune, ample.unison_detune)

    def test_mode_impose(self):
        for mode in synthgen.MODES:
            with self.subTest(mode=mode):
                preset = synthgen.generate(synthgen.GenOptions(
                    genre="techno", seed=1, mode=mode))
                self.assertEqual(preset.sound.mode, mode)

    def test_echantillons_imposes(self):
        """Les échantillons fournis doivent être utilisés par les oscillateurs."""
        preset = synthgen.generate(synthgen.GenOptions(
            genre="lofi", role="keys", seed=2,
            use_samples=["SAMPLES/A.wav", "SAMPLES/B.wav"]))
        self.assertEqual(preset.sound.osc1.type, "sample")
        self.assertEqual(preset.sound.osc1.file_name, "SAMPLES/A.wav")
        self.assertIn("SAMPLES/A.wav", preset.sound.sample_paths())

    def test_aller_retour_xml(self):
        """Un preset généré doit se réécrire et se relire à l'identique."""
        with tempfile.TemporaryDirectory() as tmp:
            for key in ("acid", "ambient", "dnb", "idm"):
                for role in ("bass", "pad", "arp"):
                    with self.subTest(genre=key, role=role):
                        preset = synthgen.generate(synthgen.GenOptions(
                            genre=key, role=role, seed=5))
                        path = Path(tmp) / f"{key}_{role}.XML"
                        preset.save(path, backup=False)
                        again = SynthPreset.load(path)
                        self.assertEqual(again.sound.name, preset.sound.name)
                        self.assertEqual(again.sound.mode, preset.sound.mode)
                        self.assertEqual(again.sound.osc1.type,
                                         preset.sound.osc1.type)
                        self.assertEqual(again.sound.env1, preset.sound.env1)
                        self.assertEqual(len(again.sound.patch_cables),
                                         len(preset.sound.patch_cables))
                        for param in ("volume", "lpfFrequency", "lpfResonance",
                                      "oscAVolume"):
                            self.assertEqual(again.sound.param(param),
                                             preset.sound.param(param))

    def test_noms_varies_et_valides(self):
        """Les noms doivent varier et rester compatibles avec la carte."""
        noms = [synthgen.generate(synthgen.GenOptions(
            genre="techno", role="lead", seed=s)).sound.name
            for s in range(30)]
        self.assertGreater(len(set(noms)), 20)
        for nom in noms:
            with self.subTest(nom=nom):
                self.assertEqual(sdcard.check_name(nom), [])
        # Le genre doit influencer le nom, pas seulement la graine.
        par_genre = {synthgen.generate(synthgen.GenOptions(
            genre=g, role="bass", seed=7)).sound.name
            for g in genres.genre_keys()}
        self.assertGreater(len(par_genre), 10)

    def test_nom_impose(self):
        preset = synthgen.generate(synthgen.GenOptions(
            genre="techno", seed=1, name="MA BASSE"))
        self.assertEqual(preset.sound.name, "MA BASSE")

    def test_hasard_complet(self):
        for seed in range(12):
            with self.subTest(seed=seed):
                preset = synthgen.randomize(seed=seed)
                ok, why = self._audible(preset)
                self.assertTrue(ok, why)
        self.assertEqual(synthgen.randomize(seed=4).sound,
                         synthgen.randomize(seed=4).sound)

    def test_hasard_avec_role_impose(self):
        preset = synthgen.randomize(seed=1, role="pad")
        self.assertTrue(self._audible(preset)[0])

    def test_mutation(self):
        """Une mutation modifie le son sans le rendre muet."""
        base = synthgen.generate(synthgen.GenOptions(genre="house", seed=3))
        faible = synthgen.mutate(base, amount=0.1, seed=1)
        forte = synthgen.mutate(base, amount=0.9, seed=1)
        self.assertNotEqual(faible.sound, base.sound)
        self.assertTrue(self._audible(faible)[0])
        self.assertTrue(self._audible(forte)[0])
        # Reproductible, et sans toucher à l'original.
        self.assertEqual(synthgen.mutate(base, 0.5, seed=2).sound,
                         synthgen.mutate(base, 0.5, seed=2).sound)

    def test_mutation_nulle_reste_proche(self):
        base = synthgen.generate(synthgen.GenOptions(genre="house", seed=3))
        copie = synthgen.mutate(base, amount=0.0, seed=1)
        self.assertEqual(copie.sound.osc1.type, base.sound.osc1.type)
        self.assertEqual(copie.sound.mode, base.sound.mode)

    def test_morphing(self):
        """``t=0`` donne le premier son, ``t=1`` le second."""
        a = synthgen.generate(synthgen.GenOptions(genre="acid", role="bass",
                                                  seed=1))
        b = synthgen.generate(synthgen.GenOptions(genre="ambient", role="pad",
                                                 seed=2))
        debut = synthgen.morph(a, b, 0.0)
        fin = synthgen.morph(a, b, 1.0)
        milieu = synthgen.morph(a, b, 0.5)
        self.assertEqual(debut.sound.osc1.type, a.sound.osc1.type)
        self.assertEqual(fin.sound.osc1.type, b.sound.osc1.type)
        for preset in (debut, milieu, fin):
            self.assertTrue(self._audible(preset)[0])
        # Une valeur intermédiaire doit se situer entre les deux.
        entre = milieu.sound.param("lpfFrequency")
        bornes = sorted([a.sound.param("lpfFrequency"),
                         b.sound.param("lpfFrequency")])
        self.assertGreaterEqual(entre, bornes[0] - 1)
        self.assertLessEqual(entre, bornes[1] + 1)

    def test_morphing_bornes_hors_intervalle(self):
        a = synthgen.generate(synthgen.GenOptions(seed=1))
        b = synthgen.generate(synthgen.GenOptions(seed=2))
        self.assertTrue(self._audible(synthgen.morph(a, b, -5))[0])
        self.assertTrue(self._audible(synthgen.morph(a, b, 9))[0])

    def test_variations(self):
        base = synthgen.generate(synthgen.GenOptions(genre="trance", seed=1))
        lot = synthgen.variations(base, n=6, amount=0.3, seed=7)
        self.assertEqual(len(lot), 6)
        self.assertEqual(len({v.sound.name for v in lot}), 6)
        for variant in lot:
            with self.subTest(nom=variant.sound.name):
                self.assertTrue(self._audible(variant)[0])
                self.assertEqual(sdcard.check_name(variant.sound.name), [])
        self.assertEqual(synthgen.variations(base, n=0), [])

    def test_description(self):
        preset = synthgen.generate(synthgen.GenOptions(genre="acid",
                                                       role="bass", seed=1))
        texte = synthgen.describe(preset)
        self.assertIn("Synthèse", texte)
        self.assertTrue(texte.endswith("."))
        self.assertGreater(len(texte), 40)


# --------------------------------------------------------------------------- #
# Générateur de kits
# --------------------------------------------------------------------------- #

class TestKitGen(unittest.TestCase):
    """Assemblage de kits depuis la bibliothèque."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "carte"
        roles = ("Kick", "Snare", "HatC", "HatO", "Clap", "Rim", "Crash")
        for sub in ("SONGS", "SYNTHS", "KITS"):
            (self.root / sub).mkdir(parents=True)
        t = np.linspace(0, 0.3, 13230, endpoint=False, dtype=np.float32)
        rng = np.random.default_rng(1)
        for i, role in enumerate(roles):
            folder = self.root / "SAMPLES" / "DRUMS" / role
            folder.mkdir(parents=True)
            for n in range(3):
                signal = (0.5 * np.sin(2 * np.pi * (60 + 40 * i) * t)
                          * np.exp(-t * (6 + n))).astype(np.float32)
                wav.write(folder / f"{role} {n}.wav", signal, 44100)
        self.sd = sdcard.SDCard(self.root)
        self.lib = db.Library(Path(self._tmp.name) / "i.db")
        scan.scan_card(self.sd, self.lib, compute_hash=False)

    def tearDown(self):
        self.lib.close()
        self._tmp.cleanup()

    def test_construction(self):
        kit = kitgen.build_kit(self.sd, self.lib, "MON KIT", genre="techno",
                               seed=1)
        self.assertTrue(kit.rows)
        self.assertEqual(kit.name, "MON KIT")
        # Toutes les références doivent exister sur la carte.
        for rel in kit.sample_paths():
            with self.subTest(rel=rel):
                self.assertIsNotNone(self.sd.resolve_sample(rel))

    def test_reproductibilite(self):
        a = kitgen.build_kit(self.sd, self.lib, "A", genre="techno", seed=9)
        b = kitgen.build_kit(self.sd, self.lib, "A", genre="techno", seed=9)
        self.assertEqual(a.sample_paths(), b.sample_paths())

    def test_le_genre_change_le_choix(self):
        """Une même graine ne doit pas donner le même kit à tous les genres."""
        kicks = set()
        for key in ("techno", "acid", "dnb", "house", "lofi"):
            kit = kitgen.build_kit(self.sd, self.lib, "K", genre=key, seed=3)
            kick = next((r.file_name for r in kit.rows if r.name == "KICK"), "")
            kicks.add(kick)
        self.assertGreater(len(kicks), 1)

    def test_reglages_par_role(self):
        """Les rangées sont réglées comme celles des vrais kits de la carte.

        Mesuré sur les 523 rangées des 43 kits : enveloppe ouverte
        (attaque 0, sustain 50, release 0), ``velocity → volume`` à pleine
        échelle, échantillon joué jusqu'au bout (``loopMode`` 1). Ce test
        exigeait autrefois un decay plus court pour le charleston que pour la
        cymbale, avec un sustain nul : c'est ce qui coupait chaque coup au
        bout de quelques dixièmes de seconde.
        """
        from delugeapp.core.fixedpoint import to_display
        from delugeapp.core.model import REPEAT_ONCE

        kit = kitgen.build_kit(self.sd, self.lib, "K",
                               slots=["Kick", "HatC", "Crash"], seed=1)
        par_role = {r.name: r.sound for r in kit.rows}
        for nom, son in par_role.items():
            with self.subTest(rangee=nom):
                self.assertEqual(to_display(son.env1.sustain), 50)
                self.assertEqual(to_display(son.env1.release), 0)
                self.assertEqual(son.osc1.loop_mode, REPEAT_ONCE)
                self.assertIn(("velocity", "volume", 50),
                              [(c.source, c.destination, c.display())
                               for c in son.patch_cables])
                # La fin de zone est la longueur réelle du fichier.
                self.assertGreater(son.osc1.zone.end, 0)
        self.assertGreater(par_role["KICK"].display("volume"),
                           par_role["HATC"].display("volume"))
        self.assertEqual(par_role["HATC"].polyphonic, "choke")
        self.assertEqual(par_role["KICK"].polyphonic, "auto")

    def test_panoramique_comme_les_vrais_kits(self):
        """Médianes des 523 rangées réelles : toms en éventail, le grave à
        droite et l'aigu à gauche ; grosse caisse et charleys au centre.
        Le générateur mettait tout au centre."""
        t = np.linspace(0, 0.3, 13230, endpoint=False, dtype=np.float32)
        for role in ("TomL", "TomH"):
            dossier = self.root / "SAMPLES" / "DRUMS" / role
            dossier.mkdir(parents=True, exist_ok=True)
            wav.write(dossier / f"{role} 0.wav",
                      (0.4 * np.sin(2 * np.pi * 120 * t)).astype(np.float32),
                      44100)
        scan.scan_card(self.sd, self.lib, compute_hash=False, full=True)
        kit = kitgen.build_kit(self.sd, self.lib, "K", seed=1,
                               slots=["Kick", "HatC", "TomL", "TomH", "Crash"])
        pan = {r.name: r.sound.display("pan") for r in kit.rows}
        self.assertEqual(pan["KICK"], 0)
        self.assertEqual(pan["HATC"], 0)
        self.assertGreater(pan["TOML"], 0)
        self.assertLess(pan["TOMH"], 0)
        self.assertLess(pan["CRASH"], 0)

    def test_autre_son_pour_une_rangee(self):
        """Un seul son change ; il garde son rôle et ne revient pas."""
        kit = kitgen.build_kit(self.sd, self.lib, "K", seed=1,
                               slots=["Kick", "Snare", "HatC"])
        avant = [r.file_name for r in kit.rows]
        index = [r.name for r in kit.rows].index("SNARE")
        essayes = {avant[index]}
        vus = []
        for tour in range(2):
            slot = kitgen.reroll_row(kit, index, self.lib, "techno",
                                     seed=tour, avoid=essayes)
            with self.subTest(tour=tour):
                self.assertIsNotNone(slot)
                self.assertEqual(slot.role, "Snare")
                self.assertNotIn(slot.rel, essayes)
                self.assertEqual(kit.rows[index].name, "SNARE")
                self.assertEqual(kit.rows[index].file_name, slot.rel)
            essayes.add(slot.rel)
            vus.append(slot.rel)
        # Les autres rangées n'ont pas bougé.
        apres = [r.file_name for r in kit.rows]
        self.assertEqual([f for i, f in enumerate(apres) if i != index],
                         [f for i, f in enumerate(avant) if i != index])
        # Les trois caisses claires ont été essayées : plus de candidat, et
        # la rangée reste telle quelle.
        self.assertIsNone(kitgen.reroll_row(kit, index, self.lib, "techno",
                                            seed=9, avoid=essayes))
        self.assertEqual(kit.rows[index].file_name, vus[-1])

    def test_un_kit_se_construit_autour_d_une_machine(self):
        """Avant : dix rangées venues de dix dossiers différents."""
        t = np.linspace(0, 0.2, 8820, endpoint=False, dtype=np.float32)
        for role, mot in (("Kick", "Kick"), ("Snare", "Snare"),
                          ("HatC", "Closed hihat"), ("HatO", "Open hihat"),
                          ("Clap", "Clap")):
            for machine in ("909", "Linndrum"):
                wav.write(self.root / "SAMPLES" / "DRUMS" / role
                          / f"{machine} {mot}.wav",
                          (0.4 * np.sin(2 * np.pi * 200 * t)).astype(
                              np.float32), 44100)
        scan.scan_card(self.sd, self.lib, compute_hash=False, full=True)
        for seed in range(5):
            kit = kitgen.build_kit(self.sd, self.lib, "K", genre="techno",
                                   seed=seed,
                                   slots=["Kick", "Snare", "HatC", "HatO",
                                          "Clap"])
            familles = {kitgen.family_of(r.file_name) for r in kit.rows}
            with self.subTest(graine=seed):
                self.assertEqual(len(familles), 1, familles)
                self.assertEqual(len(kit.rows), 5)

    def test_famille_d_un_echantillon(self):
        self.assertEqual(kitgen.family_of("SAMPLES/DRUMS/Snare/909 Snare.wav"),
                         "909")
        self.assertEqual(kitgen.family_of(
            "SAMPLES/DRUMS/HatC/Sequential Circuits Drumtraks Closed hihat.wav"),
            "Sequential Circuits Drumtraks")
        self.assertEqual(kitgen.family_of("SAMPLES/DRUMS/Kick/07-KICK.wav"),
                         "Synthstrom n°")
        self.assertEqual(kitgen.family_of(
            "SAMPLES/Artists/Dean Daughters/Y2K/Y2K - CLAP - 01.wav"),
            "SAMPLES/Artists/Dean Daughters/Y2K")

    def test_un_long_echantillon_s_arrete_avec_la_note(self):
        """La règle du firmware : ONCE sous 2,002 s, CUT au-delà."""
        from delugeapp.core.model import (REPEAT_CUT, REPEAT_ONCE,
                                          repeat_mode_for)

        self.assertEqual(repeat_mode_for(0.4), REPEAT_ONCE)
        self.assertEqual(repeat_mode_for(2.001), REPEAT_ONCE)
        self.assertEqual(repeat_mode_for(2.5), REPEAT_CUT)
        self.assertEqual(repeat_mode_for(None), REPEAT_ONCE)

    def test_role_sans_candidat_est_omis(self):
        """Un rôle introuvable ne crée pas de rangée muette."""
        kit = kitgen.build_kit(self.sd, self.lib, "K",
                               slots=["Kick", "Guiro", "Timpany"], seed=1)
        self.assertTrue(all(r.file_name for r in kit.rows))
        self.assertLessEqual(len(kit.rows), 3)

    def test_aller_retour_xml(self):
        with tempfile.TemporaryDirectory() as tmp:
            kit = kitgen.build_kit(self.sd, self.lib, "K", genre="techno",
                                   seed=1)
            path = Path(tmp) / "KIT.XML"
            kit.save(path, backup=False)
            again = Kit.load(path)
            self.assertEqual(len(again.rows), len(kit.rows))
            self.assertEqual(again.sample_paths(), kit.sample_paths())
            self.assertEqual(again.rows[0].sound.display("volume"),
                             kit.rows[0].sound.display("volume"))

    def test_depuis_un_dossier(self):
        kit = kitgen.kit_from_folder(self.sd, "SAMPLES/DRUMS/Kick", "DOSSIER")
        self.assertEqual(len(kit.rows), 3)
        self.assertEqual(kit.name, "DOSSIER")
        for rel in kit.sample_paths():
            self.assertIsNotNone(self.sd.resolve_sample(rel))

    def test_dossier_absent(self):
        kit = kitgen.kit_from_folder(self.sd, "SAMPLES/NEANT", "VIDE")
        self.assertEqual(kit.rows, [])

    def test_rangees_conseillees(self):
        self.assertIn("Kick", kitgen.suggest_slots("techno"))
        self.assertEqual(kitgen.suggest_slots("genre inconnu"),
                         list(kitgen.DEFAULT_SLOTS))

    def test_bibliotheque_vide(self):
        """Sans échantillon indexé, le kit est vide mais valide."""
        with tempfile.TemporaryDirectory() as tmp:
            lib2 = db.Library(Path(tmp) / "vide.db")
            try:
                kit = kitgen.build_kit(self.sd, lib2, "VIDE", seed=1)
                self.assertEqual(kit.rows, [])
                self.assertEqual(kit.name, "VIDE")
            finally:
                lib2.close()


# --------------------------------------------------------------------------- #
# Théorie musicale
# --------------------------------------------------------------------------- #

class TestTheory(unittest.TestCase):
    """Gammes, accords, progressions, mixage harmonique."""

    def test_catalogue(self):
        """La SPEC §4.18 exige au moins 20 gammes et 20 accords."""
        self.assertGreaterEqual(len(theory.SCALES), 20)
        self.assertGreaterEqual(len(theory.CHORDS), 20)
        for name in ("majeur", "mineur", "dorien", "phrygien", "lydien",
                     "mixolydien", "locrien", "blues", "hijaz", "in sen"):
            with self.subTest(gamme=name):
                self.assertIn(name, theory.SCALES)
        for name in ("maj", "min", "dim", "aug", "7", "maj7", "m7", "m7b5",
                     "dim7", "sus2", "sus4", "9", "maj9", "m9", "add9"):
            with self.subTest(accord=name):
                self.assertIn(name, theory.CHORDS)

    def test_noms_de_notes(self):
        """Convention du projet : MIDI 60 = Do3 / C3."""
        self.assertEqual(theory.note_to_name(60), "Do3")
        self.assertEqual(theory.note_to_name(60, french=False), "C3")
        self.assertEqual(theory.note_to_name(69), "La3")
        self.assertEqual(theory.note_to_name(63), "Mib3")
        self.assertEqual(theory.note_to_name(60, with_octave=False), "Do")
        self.assertEqual(theory.note_to_name("x"), "")

    def test_aller_retour_des_noms(self):
        """Tout nom produit doit se relire sur toute l'étendue utile."""
        for midi in range(24, 108):
            for french in (True, False):
                with self.subTest(midi=midi, fr=french):
                    name = theory.note_to_name(midi, french=french)
                    self.assertEqual(theory.name_to_note(name), midi)

    def test_lecture_des_variantes(self):
        """Les deux langues et les deux altérations sont acceptées."""
        self.assertEqual(theory.name_to_note("Do3"), 60)
        self.assertEqual(theory.name_to_note("C3"), 60)
        self.assertEqual(theory.name_to_note("Mib2"),
                         theory.name_to_note("Eb2"))
        self.assertEqual(theory.name_to_note("Sib3"),
                         theory.name_to_note("A#3"))
        self.assertEqual(theory.name_to_note("n'importe quoi"), -1)
        self.assertEqual(theory.name_to_note(""), -1)

    def test_frequences(self):
        self.assertAlmostEqual(theory.frequency(69), 440.0, places=3)
        self.assertAlmostEqual(theory.frequency(60), 261.626, places=2)
        self.assertAlmostEqual(theory.frequency(81), 880.0, places=3)

    def test_gammes(self):
        """Do majeur doit donner la gamme de do, octave incluse."""
        notes = theory.scale_notes(60, "majeur")
        self.assertEqual(notes, [60, 62, 64, 65, 67, 69, 71, 72])
        self.assertEqual(theory.scale_notes(57, "mineur"),
                         [57, 59, 60, 62, 64, 65, 67, 69])
        deux = theory.scale_notes(60, "majeur", octaves=2)
        self.assertEqual(len(deux), 15)
        self.assertEqual(deux[-1], 84)
        # Une gamme inconnue ne lève pas.
        self.assertTrue(theory.scale_notes(60, "pas une gamme"))

    def test_mode_notes_du_deluge(self):
        """Firmware c1.x : la gamme telle quelle ; officiel : sept valeurs.

        Ce test exigeait sept intervalles pour toutes les gammes. C'était la
        règle du firmware officiel : le firmware communautaire de la machine
        (c1.2.1) propose des gammes de cinq et six notes, et un morceau de la
        carte (« Truc 1 ») est enregistré en pentatonique mineure à cinq
        notes.
        """
        self.assertEqual(theory.deluge_mode_notes("pentatonique mineure"),
                         [0, 3, 5, 7, 10])
        for name in theory.SCALES:
            with self.subTest(gamme=name):
                modes = theory.deluge_mode_notes(name, official=True)
                self.assertEqual(len(modes), 7)
                self.assertEqual(modes, sorted(modes))
                self.assertEqual(len(set(modes)), 7)
                self.assertTrue(all(0 <= m < 12 for m in modes))
        self.assertEqual(theory.deluge_mode_notes("majeur"),
                         [0, 2, 4, 5, 7, 9, 11])
        # Une gamme courte est complétée par son mode parent : jamais les
        # deux tierces à la fois, comme le faisait le complément par le
        # majeur.
        self.assertEqual(theory.deluge_mode_notes("pentatonique mineure",
                                                  official=True),
                         list(theory.SCALES["mineur"]))
        self.assertEqual(theory.deluge_mode_notes("in sen", official=True),
                         list(theory.SCALES["phrygien"]))

    def test_progression_nomme_juste(self):
        """Le VI de la mineur s'appelait « La » : c'est Fa."""
        chords = theory.progression(57, "mineur", "mélancolique", seed=3,
                                    bars=4)
        self.assertEqual([c["name"] for c in chords],
                         ["Lam", "Fa", "Do", "Sol"])
        self.assertEqual([c["bass"] % 12 for c in chords], [9, 5, 0, 7])
        self.assertTrue(all(36 <= c["bass"] <= 47 for c in chords))

    def test_orthographe_selon_la_tonalite(self):
        """Do mineur s'écrit avec Lab : la table fixe donnait « Sol# »."""
        def nommer(root, gamme):
            sp = theory.scale_spelling(root, gamme)
            return [theory.spell(n, sp, with_octave=False)
                    for n in theory.scale_notes(root, gamme)[:-1]]

        self.assertEqual(nommer(60, "mineur"),
                         ["Do", "Ré", "Mib", "Fa", "Sol", "Lab", "Sib"])
        self.assertEqual(nommer(62, "mineur harmonique"),
                         ["Ré", "Mi", "Fa", "Sol", "La", "Sib", "Do#"])
        # Réb majeur (cinq bémols) plutôt que Do# majeur (sept dièses).
        self.assertEqual(nommer(61, "majeur")[0], "Réb")
        # À égalité, la tonique garde le nom qu'on lui donne partout.
        self.assertEqual(nommer(63, "mineur")[0], "Mib")
        # Chaque lettre une fois dans une gamme de sept notes.
        for root in range(60, 72):
            for gamme in ("majeur", "mineur", "dorien", "lydien"):
                with self.subTest(root=root, gamme=gamme):
                    lettres = [n.rstrip("#b") for n in nommer(root, gamme)]
                    self.assertEqual(len(set(lettres)), 7)
        # L'octave suit la lettre : Mi#4 est le fa de MIDI 77.
        sp = theory.scale_spelling(66, "majeur")
        self.assertEqual(theory.spell(77, sp), "Mi#4")
        self.assertEqual(theory.progression(60, "mineur", "mélancolique",
                                            seed=3, bars=4)[1]["name"],
                         "Lab")

    def test_gammes_du_deluge(self):
        self.assertEqual(theory.deluge_scale_name("pentatonique mineure"),
                         "PENTATONIC MINOR")
        self.assertEqual(theory.deluge_scale_name("in sen"), "USER")
        self.assertIn("marva", theory.SCALES)
        self.assertEqual(theory.chord_quality([57, 60, 64]), "min")
        self.assertEqual(theory.chord_symbol(59, "m7b5"), "Siø7")

    def test_appartenance_et_recalage(self):
        self.assertTrue(theory.in_scale(64, 60, "majeur"))
        self.assertFalse(theory.in_scale(61, 60, "majeur"))
        self.assertEqual(theory.snap_to_scale(64, 60, "majeur"), 64)
        self.assertIn(theory.snap_to_scale(61, 60, "majeur"), (60, 62))

    def test_accords(self):
        self.assertEqual(theory.chord_notes(60, "maj"), [60, 64, 67])
        self.assertEqual(theory.chord_notes(60, "min"), [60, 63, 67])
        self.assertEqual(theory.chord_notes(60, "maj7"), [60, 64, 67, 71])
        self.assertEqual(theory.chord_notes(60, "m7"), [60, 63, 67, 70])
        self.assertTrue(theory.chord_notes(60, "accord inconnu"))

    def test_renversements(self):
        """Un renversement fait monter la basse à l'octave."""
        self.assertEqual(theory.chord_notes(60, "maj", inversion=1),
                         [64, 67, 72])
        self.assertEqual(theory.chord_notes(60, "maj", inversion=2),
                         [67, 72, 76])

    def test_dispositions(self):
        for voicing in ("close", "open", "spread", "drop2"):
            with self.subTest(voicing=voicing):
                notes = theory.chord_notes(60, "maj7", voicing=voicing)
                self.assertTrue(notes)
                self.assertEqual(notes, sorted(notes))
                self.assertTrue(all(0 <= n <= 127 for n in notes))

    def test_accords_diatoniques(self):
        """Do majeur : I ii iii IV V vi vii°, comme dans les manuels."""
        chords = theory.diatonic_chords(60, "majeur")
        self.assertEqual([s for s, _n in chords],
                         ["I", "ii", "iii", "IV", "V", "vi", "vii°"])
        self.assertEqual(chords[0][1], [60, 64, 67])
        # La mineur naturel : i ii° III iv v VI VII.
        mineur = [s for s, _n in theory.diatonic_chords(57, "mineur")]
        self.assertEqual(mineur, ["i", "ii°", "III", "iv", "v", "VI", "VII"])

    def test_accords_diatoniques_de_septieme(self):
        chords = theory.diatonic_chords(60, "majeur", sevenths=True)
        self.assertEqual(len(chords), 7)
        self.assertTrue(all(len(n) == 4 for _s, n in chords))

    def test_conduite_des_voix(self):
        """Le second accord doit bouger le moins possible depuis le premier."""
        do = theory.chord_notes(60, "maj")
        fa_brut = theory.chord_notes(65, "maj")
        fa_conduit = theory.voice_leading(do, fa_brut)
        ecart_brut = sum(min(abs(n - r) for r in do) for n in fa_brut)
        ecart_conduit = sum(min(abs(n - r) for r in do) for n in fa_conduit)
        self.assertLessEqual(ecart_conduit, ecart_brut)
        self.assertEqual(theory.voice_leading([], do), do)

    def test_progression(self):
        chords = theory.progression(57, "mineur", "mélancolique", seed=1,
                                    bars=4)
        self.assertEqual(len(chords), 4)
        for chord in chords:
            with self.subTest(degre=chord["degree"]):
                self.assertTrue(chord["notes"])
                self.assertTrue(chord["symbol"])
                self.assertEqual(chord["bars"], 1)
        # Reproductible.
        self.assertEqual(
            [c["notes"] for c in theory.progression(57, "mineur", "pop",
                                                    seed=3, bars=4)],
            [c["notes"] for c in theory.progression(57, "mineur", "pop",
                                                    seed=3, bars=4)])

    def test_progression_longueurs(self):
        for bars in (1, 2, 4, 8, 16):
            with self.subTest(bars=bars):
                self.assertEqual(
                    len(theory.progression(60, "majeur", "pop", seed=1,
                                           bars=bars)), bars)

    def test_progression_ambiance_inconnue(self):
        """Une ambiance inconnue en tire une au hasard, sans lever."""
        self.assertTrue(theory.progression(60, "majeur", "inconnue", seed=1))

    def test_camelot(self):
        """Codes vérifiés sur la vraie roue de Camelot."""
        self.assertEqual(theory.camelot("C"), "8B")
        self.assertEqual(theory.camelot("Am"), "8A")
        self.assertEqual(theory.camelot("G"), "9B")
        self.assertEqual(theory.camelot("Em"), "9A")
        self.assertEqual(theory.camelot("F#m"), "11A")
        self.assertEqual(theory.camelot(""), "")
        self.assertEqual(theory.camelot("pas une tonalité"), "")

    def test_camelot_aller_retour(self):
        for key in ("C", "Am", "G", "Em", "F", "Dm", "Bm", "F#m"):
            with self.subTest(key=key):
                self.assertEqual(theory.from_camelot(theory.camelot(key)),
                                 key)

    def test_tonalites_compatibles(self):
        """Mixage harmonique : soi-même, les voisins, et le relatif."""
        compatibles = theory.compatible_keys("Am")
        self.assertIn("Am", compatibles)
        self.assertIn("C", compatibles)       # relatif majeur
        self.assertIn("Em", compatibles)      # quinte
        self.assertIn("Dm", compatibles)      # quarte
        self.assertEqual(theory.compatible_keys("n'importe quoi"), [])

    def test_cycle_des_quintes(self):
        cycle = theory.circle_of_fifths()
        self.assertEqual(len(cycle), 12)
        self.assertEqual(cycle[0], ("C", "Am"))
        self.assertEqual(cycle[1], ("G", "Em"))

    def test_transposition(self):
        self.assertEqual(theory.transpose([60, 64, 67], 2), [62, 66, 69])
        self.assertEqual(theory.transpose([60, 64, 67], -12), [48, 52, 55])
        # Ce qui sort de l'étendue MIDI est écarté.
        self.assertEqual(theory.transpose([120, 60], 12), [72])


# --------------------------------------------------------------------------- #
# Rythmes
# --------------------------------------------------------------------------- #

class TestRhythm(unittest.TestCase):
    """Motifs euclidiens, grooves, swing, tables de temps."""

    @staticmethod
    def _show(cells) -> str:
        return "".join("x" if c else "." for c in cells)

    def test_euclidien(self):
        """``E(3,8)`` doit donner ``x..x..x.`` (exigence de la SPEC §7)."""
        self.assertEqual(self._show(rhythm.euclid(3, 8)), "x..x..x.")
        self.assertEqual(self._show(rhythm.euclid(5, 8)), "x.xx.xx.")
        self.assertEqual(self._show(rhythm.euclid(2, 5)), "x.x..")
        self.assertEqual(self._show(rhythm.euclid(4, 16)),
                         "x...x...x...x...")

    def test_euclidien_nombre_de_coups(self):
        """Le motif doit contenir exactement le nombre de coups demandé."""
        for steps in (4, 8, 12, 16, 32):
            for pulses in range(steps + 1):
                with self.subTest(pulses=pulses, steps=steps):
                    cells = rhythm.euclid(pulses, steps)
                    self.assertEqual(len(cells), steps)
                    self.assertEqual(sum(cells), pulses)

    def test_euclidien_rotation(self):
        base = rhythm.euclid(3, 8)
        tourne = rhythm.euclid(3, 8, rotate=1)
        self.assertEqual(sum(base), sum(tourne))
        self.assertNotEqual(base, tourne)
        self.assertEqual(rhythm.euclid(3, 8, rotate=8), base)

    def test_euclidien_cas_limites(self):
        self.assertEqual(rhythm.euclid(0, 8), [False] * 8)
        self.assertEqual(rhythm.euclid(8, 8), [True] * 8)
        self.assertEqual(rhythm.euclid(3, 0), [])
        self.assertEqual(sum(rhythm.euclid(99, 8)), 8)
        self.assertEqual(rhythm.euclid("x", "y"), [])

    def test_motif_euclidien_multipistes(self):
        pattern = rhythm.euclid_pattern({"Kick": (4, 16, 0),
                                         "HatC": (7, 16, 2)})
        self.assertEqual(pattern.steps, 16)
        self.assertEqual(len(pattern.tracks["Kick"]), 4)
        self.assertEqual(len(pattern.tracks["HatC"]), 7)
        # Une spécification invalide est ignorée sans lever.
        self.assertNotIn("Faux", rhythm.euclid_pattern(
            {"Faux": ("a", "b", "c")}).tracks)

    def test_rythmes_de_genre(self):
        for key in genres.genre_keys():
            with self.subTest(genre=key):
                pattern = rhythm.genre_beat(key, bars=1, seed=1)
                self.assertTrue(pattern.tracks)
                self.assertIn("Kick", pattern.tracks)
                for steps in pattern.tracks.values():
                    for step in steps:
                        self.assertTrue(0 <= step.pos < pattern.steps)
                        self.assertTrue(1 <= step.velocity <= 127)

    def test_rythme_sur_plusieurs_mesures(self):
        pattern = rhythm.genre_beat("techno", bars=4, seed=1, fills=False)
        self.assertEqual(pattern.steps, 64)
        self.assertEqual(pattern.bars, 4.0)
        self.assertEqual(len(pattern.tracks["Kick"]), 16)

    def test_rythme_reproductible(self):
        a = rhythm.genre_beat("house", bars=2, seed=5)
        b = rhythm.genre_beat("house", bars=2, seed=5)
        self.assertEqual({k: [(s.pos, s.velocity) for s in v]
                          for k, v in a.tracks.items()},
                         {k: [(s.pos, s.velocity) for s in v]
                          for k, v in b.tracks.items()})

    def test_conversion_en_notes(self):
        """Le motif doit devenir des notes de clip valides."""
        pattern = rhythm.genre_beat("techno", bars=2, seed=1)
        notes = pattern.to_notes({"Kick": 0, "Clap": 1, "HatC": 2, "Rim": 3})
        self.assertTrue(notes)
        for row, items in notes.items():
            for note in items:
                with self.subTest(row=row, pos=note.pos):
                    self.assertTrue(0 <= note.pos < pattern.length_ticks)
                    self.assertGreater(note.length, 0)
                    self.assertTrue(1 <= note.velocity <= 127)
                    self.assertTrue(0 <= note.condition <= 20)
        # Une piste sans rangée associée est ignorée.
        self.assertEqual(pattern.to_notes({}), {})

    def test_resolution(self):
        """16 pas par mesure donnent 6 ticks par pas, 96 par mesure."""
        pattern = rhythm.genre_beat("techno", bars=1, seed=1)
        self.assertEqual(pattern.ticks_per_step, 6)
        self.assertEqual(pattern.length_ticks, 96)
        self.assertEqual(rhythm.bars_to_ticks(16), 1536)
        self.assertEqual(rhythm.bars_to_ticks(1), 96)

    def test_swing(self):
        """Le swing retarde les pas impairs et laisse les pairs en place."""
        base = rhythm.euclid_pattern({"HatC": (16, 16, 0)})
        droit = base.to_notes({"HatC": 60})[60]
        swingue = rhythm.swing(base, 0.6).to_notes({"HatC": 60})[60]
        for i in range(0, 16, 2):
            self.assertEqual(droit[i].pos, swingue[i].pos)
        for i in range(1, 16, 2):
            self.assertGreater(swingue[i].pos, droit[i].pos)
        # Un swing nul ne change rien.
        self.assertEqual([n.pos for n in
                          rhythm.swing(base, 0.0).to_notes({"HatC": 60})[60]],
                         [n.pos for n in droit])

    def test_groove(self):
        """Un groove décale les pas, et la force dose l'effet."""
        base = rhythm.euclid_pattern({"HatC": (16, 16, 0)})
        droit = [n.pos for n in base.to_notes({"HatC": 60})[60]]
        # « MPC 16B » n'existe plus : les grooves portent les vrais
        # pourcentages de swing d'une MPC.
        fort = [n.pos for n in rhythm.apply_groove(base, "MPC 66 %", 1.0)
                .to_notes({"HatC": 60})[60]]
        self.assertNotEqual(droit, fort)
        nul = [n.pos for n in rhythm.apply_groove(base, "droit", 1.0)
               .to_notes({"HatC": 60})[60]]
        self.assertEqual(droit, nul)
        # Un groove inconnu laisse le motif tel quel.
        inconnu = rhythm.apply_groove(base, "pas un groove", 1.0)
        self.assertEqual([n.pos for n in inconnu.to_notes({"HatC": 60})[60]],
                         droit)

    def test_humanisation(self):
        pattern = rhythm.genre_beat("techno", bars=1, seed=1)
        humain = rhythm.humanize(pattern, timing=0.1, velocity=0.3, seed=2)
        self.assertEqual(set(humain.tracks), set(pattern.tracks))
        for steps in humain.tracks.values():
            for step in steps:
                self.assertTrue(1 <= step.velocity <= 127)
                self.assertGreaterEqual(step.pos, 0.0)
        # Reproductible, et l'original n'est pas touché.
        again = rhythm.humanize(pattern, timing=0.1, velocity=0.3, seed=2)
        self.assertEqual([s.pos for s in again.tracks["Kick"]],
                         [s.pos for s in humain.tracks["Kick"]])
        self.assertEqual([s.pos for s in pattern.tracks["Kick"]],
                         [float(s.pos) for s in
                          rhythm.genre_beat("techno", bars=1,
                                            seed=1).tracks["Kick"]])

    def test_affichage_ascii(self):
        pattern = rhythm.genre_beat("techno", bars=1, seed=1)
        texte = pattern.ascii()
        self.assertIn("Kick", texte)
        self.assertIn("x", texte)
        self.assertIn("|", texte)
        self.assertEqual(rhythm.Pattern().ascii(), "(motif vide)")

    def test_polyrythmie(self):
        cells = rhythm.polyrhythm(3, 4, 12)
        self.assertEqual(len(cells), 12)
        self.assertTrue(any(cells))
        self.assertEqual(rhythm.polyrhythm(0, 0, 8), [False] * 8)
        self.assertEqual(rhythm.polyrhythm("a", "b", 4), [])

    def test_table_des_temps(self):
        """Une noire à 120 BPM fait exactement 500 ms."""
        table = rhythm.delay_times(120)
        quarter = next(r for r in table if r["div"] == "1/4")
        self.assertAlmostEqual(quarter["ms"], 500.0, places=2)
        self.assertAlmostEqual(quarter["hz"], 2.0, places=3)
        self.assertAlmostEqual(quarter["dotted_ms"], 750.0, places=2)
        self.assertAlmostEqual(quarter["triplet_ms"], 333.33, places=1)
        eighth = next(r for r in table if r["div"] == "1/8")
        self.assertAlmostEqual(eighth["ms"], 250.0, places=2)
        # Un tempo absurde retombe sur 120 BPM.
        self.assertAlmostEqual(
            next(r for r in rhythm.delay_times(0) if r["div"] == "1/4")["ms"],
            500.0, places=2)
        self.assertTrue(rhythm.delay_times("x"))


# --------------------------------------------------------------------------- #
# Export MIDI
# --------------------------------------------------------------------------- #

class TestMidiFile(unittest.TestCase):
    """Écriture MIDI, relue par un analyseur indépendant du module."""

    @staticmethod
    def _parse(path: Path) -> dict:
        """Relit un fichier MIDI sans utiliser ``midifile``.

        Vérifie au passage l'intégrité du fichier : en-tête, blocs, longueurs,
        délais en longueur variable, notes toutes éteintes, aucun octet
        superflu.
        """
        import struct

        data = Path(path).read_bytes()
        if data[:4] != b"MThd":
            raise AssertionError("en-tête MThd absente")
        (header_len,) = struct.unpack(">I", data[4:8])
        fmt, ntracks, ppq = struct.unpack(">HHH", data[8:8 + header_len][:6])
        pos = 8 + header_len
        tempo_us = None
        tracks: list[dict] = []

        for _ in range(ntracks):
            if data[pos:pos + 4] != b"MTrk":
                raise AssertionError(f"bloc MTrk attendu à l'octet {pos}")
            (length,) = struct.unpack(">I", data[pos + 4:pos + 8])
            body = data[pos + 8:pos + 8 + length]
            pos += 8 + length

            i = 0
            now = 0
            name = None
            pending: dict[int, list[tuple[int, int]]] = {}
            notes: list[tuple[int, int, int, int]] = []
            ended = False
            while i < len(body):
                delta = 0
                while True:
                    byte = body[i]
                    i += 1
                    delta = (delta << 7) | (byte & 0x7F)
                    if not byte & 0x80:
                        break
                now += delta
                status = body[i]
                i += 1
                if status == 0xFF:
                    meta = body[i]
                    i += 1
                    size = 0
                    while True:
                        byte = body[i]
                        i += 1
                        size = (size << 7) | (byte & 0x7F)
                        if not byte & 0x80:
                            break
                    payload = body[i:i + size]
                    i += size
                    if meta == 0x03:
                        name = payload.decode("ascii", "replace")
                    elif meta == 0x51:
                        tempo_us = int.from_bytes(payload, "big")
                    elif meta == 0x2F:
                        ended = True
                elif status & 0xF0 in (0x80, 0x90):
                    note, velocity = body[i], body[i + 1]
                    i += 2
                    if status & 0xF0 == 0x90 and velocity > 0:
                        pending.setdefault(note, []).append((now, velocity))
                    elif pending.get(note):
                        start, level = pending[note].pop(0)
                        notes.append((start, note, level, now - start))
                else:
                    raise AssertionError(f"statut inattendu 0x{status:02X}")
            if not ended:
                raise AssertionError("fin de piste manquante")
            if any(pending.values()):
                raise AssertionError(f"notes non éteintes : {pending}")
            tracks.append({"name": name, "notes": sorted(notes)})

        if pos != len(data):
            raise AssertionError(f"{len(data) - pos} octets superflus")
        return {"format": fmt, "ppq": ppq, "tempo_us": tempo_us,
                "tracks": tracks}

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


# --------------------------------------------------------------------------- #
# Profondeur des câbles de modulation
# --------------------------------------------------------------------------- #

class TestPatchCableScale(unittest.TestCase):
    """Échelle des câbles de modulation, mesurée sur la carte réelle."""

    def test_echelle_pleine(self):
        """L'échelle pleine est ``0x40000000``, non ``0x7FFFFFFF``.

        Mesuré sur les 7 025 câbles de la carte : aucune valeur ne dépasse
        ``0x40000000``, et 1 925 s'y arrêtent exactement — c'est la
        signature du maximum de l'interface. Lire ces câbles sur l'échelle
        des paramètres ordinaires divisait toutes les profondeurs par deux.
        """
        from delugeapp.core.model import PATCH_CABLE_FULL, PatchCable

        self.assertEqual(PATCH_CABLE_FULL, 0x40000000)
        self.assertEqual(PatchCable(amount=PATCH_CABLE_FULL).display(), 50)
        self.assertEqual(PatchCable(amount=-PATCH_CABLE_FULL).display(), -50)
        self.assertEqual(PatchCable(amount=0).display(), 0)
        # La valeur la plus fréquente de la carte doit bien donner +50.
        self.assertEqual(PatchCable(amount=0x3FFFFFE8).display(), 50)

    def test_aller_retour(self):
        """Les 101 profondeurs affichables doivent se relire exactement."""
        from delugeapp.core.model import PatchCable

        for depth in range(-50, 51):
            with self.subTest(depth=depth):
                amount = PatchCable.amount_from_display(depth)
                self.assertEqual(PatchCable(amount=amount).display(), depth)

    def test_bornes(self):
        from delugeapp.core.model import PatchCable

        self.assertEqual(PatchCable.amount_from_display(999),
                         PatchCable.amount_from_display(50))
        self.assertEqual(PatchCable.amount_from_display("x"), 0)
        cable = PatchCable()
        cable.set_display(-30)
        self.assertEqual(cable.display(), -30)


# --------------------------------------------------------------------------- #
# Moteur d'écoute
# --------------------------------------------------------------------------- #

class TestRender(unittest.TestCase):
    """Rendu hors-ligne : budget de temps, audibilité, cohérence spectrale."""

    SR = 44100

    def test_forme_et_type(self):
        """Le rendu est un tableau stéréo float32 de la bonne longueur."""
        preset = synthgen.generate(synthgen.GenOptions(genre="techno",
                                                       seed=1))
        audio = render.render_sound(preset.sound, seconds=1.0, sr=self.SR)
        self.assertEqual(audio.dtype, np.float32)
        self.assertEqual(audio.ndim, 2)
        self.assertEqual(audio.shape, (self.SR, 2))

    def test_budget_de_temps(self):
        """SPEC §4.21 : 2,5 s rendues en moins de 600 ms, au pire cas — une
        nappe à huit voix d'unisson.

        Depuis le portage du traitement du signal du firmware (23 octobre
        2026), filtres et rétroactions se calculent échantillon par
        échantillon : au calme, ces cinq nappes prennent de 0,19 à 0,33 s
        (une nappe FM à rétroaction étalée en stéréo) ; l'ancien plafond de
        400 ms tenait à l'ancien moteur, approché. Après une dizaine de
        rendus d'affilée, le portable ralentit : le même son a pris 0,47 s,
        et un passage isolé sous la charge de toute la suite, 0,63 s. On
        garde donc le plus rapide de trois passages de chaque son.
        """
        import time

        preset = synthgen.generate(synthgen.GenOptions(genre="techno",
                                                       seed=1))
        # Premier appel écarté : il charge les tables du firmware.
        render.render_sound(preset.sound, seconds=0.2, sr=self.SR)

        durations = []
        for seed in range(5):
            other = synthgen.generate(synthgen.GenOptions(genre="ambient",
                                                          role="pad",
                                                          seed=seed,
                                                          width=1.0,
                                                          space=1.0))
            other.sound.unison_num = 8      # le cas le plus coûteux
            passages = []
            for _ in range(3):
                start = time.perf_counter()
                render.render_sound(other.sound, seconds=2.5, sr=self.SR)
                passages.append(time.perf_counter() - start)
            durations.append(min(passages))
        self.assertLess(max(durations), 0.6,
                        f"rendu trop lent : {max(durations) * 1000:.0f} ms")

    def test_aucun_rendu_muet_ni_sature(self):
        """Tous les genres et rôles doivent produire un signal propre."""
        for key in genres.genre_keys():
            for role in ("bass", "lead", "pad", "bell"):
                with self.subTest(genre=key, role=role):
                    preset = synthgen.generate(synthgen.GenOptions(
                        genre=key, role=role, seed=2))
                    audio = render.render_sound(preset.sound, seconds=0.8,
                                                sr=self.SR)
                    self.assertTrue(bool(np.all(np.isfinite(audio))),
                                    "valeurs non finies")
                    peak = float(np.max(np.abs(audio)))
                    self.assertGreater(peak, 0.005, "rendu muet")
                    self.assertLessEqual(peak, 1.0, "rendu saturé")

    def test_la_graine_du_bruit_est_stable(self):
        """Le même preset doit rendre le même son d'une session à l'autre.

        La graine du bruit et des phases de LFO venait de ``hash(nom)``, que
        Python randomise à chaque démarrage. Le générateur promet pourtant
        qu'une graine redonne le même son — et la promesse ne tenait pas
        au-delà de la session.

        Le défaut s'est manifesté en grand : la même basse « lo-fi », rendue
        dans deux processus, allait de 0,003 à 0,42 de crête, soit plus de
        40 dB d'écart. Un test de rendu muet est tombé dessus un jour sur
        plusieurs, ce qui en faisait une alerte qu'on finit par ignorer.
        """
        self.assertEqual(render._graine("AURORE GRAVE 3"), 1271953888)
        self.assertEqual(render._graine("Mon son"), 1509621092)
        self.assertEqual(render._graine(""), 0)
        self.assertEqual(render._graine(None), 0)

    def test_deux_rendus_du_meme_son_sont_identiques(self):
        """Au bit près : c'est la forme forte de la reproductibilité."""
        preset = synthgen.generate(synthgen.GenOptions(
            genre="lofi", role="bass", seed=2))
        premier = render.render_sound(preset.sound, seconds=0.5, sr=self.SR)
        second = render.render_sound(preset.sound, seconds=0.5, sr=self.SR)
        self.assertTrue(bool(np.array_equal(premier, second)),
                        "deux rendus du même son diffèrent")

    def test_un_son_renomme_change_de_bruit_mais_pas_de_niveau(self):
        """Le nom sert de graine : il ne doit pas décider du volume.

        Mesuré sur quarante graines : la crête allait de 0,007 à 0,42. Le
        bruit change, c'est voulu ; que le niveau varie de quarante fois
        l'est beaucoup moins, et ce contrôle garde la mesure sous les yeux.
        """
        import copy

        preset = synthgen.generate(synthgen.GenOptions(
            genre="lofi", role="bass", seed=2))
        cretes = []
        for nom in ("ESSAI A", "ESSAI B", "ESSAI C", "ESSAI D", "ESSAI E"):
            autre = copy.deepcopy(preset.sound)
            autre.name = nom
            audio = render.render_sound(autre, seconds=0.8, sr=self.SR)
            cretes.append(float(np.max(np.abs(audio))))
        for crete in cretes:
            self.assertGreater(crete, 0.005,
                               "un simple changement de nom rend le son muet")

    def test_hierarchie_spectrale(self):
        """Une basse doit sonner plus grave qu'un lead ou qu'une nappe.

        C'est le contrôle qui a révélé une erreur réelle : trois câbles de
        modulation empilés sur la coupure du filtre laissaient les basses
        grandes ouvertes, avec un centroïde de 13 kHz.

        La médiane de six graines, et non une seule : sur 22 tirages, la
        médiane d'une graine varie du simple au double (671 à 1 505 Hz pour
        les basses de l'ancien générateur, sur huit graines) ; le test
        passait par chance. Vu le 22 octobre 2026, quand chaque décision du
        générateur a reçu son propre tirage : la graine 1 seule mettait les
        basses à 2 315 Hz contre 2 237 pour les nappes, alors que sur huit
        graines rien n'avait bougé (basse 1 017 Hz contre 1 028 avant, nappe
        1 570 contre 1 648).
        """
        import statistics

        def centroid(role: str) -> float:
            medians = []
            for seed in range(1, 7):
                values = []
                for key in genres.genre_keys():
                    preset = synthgen.generate(synthgen.GenOptions(
                        genre=key, role=role, seed=seed))
                    mono = render.render_sound(preset.sound, seconds=0.5,
                                               sr=self.SR).mean(axis=1)
                    values.append(analysis.spectral(mono,
                                                    self.SR)["centroid"])
                medians.append(statistics.median(values))
            return statistics.median(medians)

        bass = centroid("bass")
        self.assertLess(bass, centroid("lead"))
        self.assertLess(bass, centroid("pad"))
        self.assertLess(bass, 2500, "les basses sont trop brillantes")

    def test_enveloppe_respectee(self):
        """Une attaque lente doit monter progressivement, pas d'un coup."""
        from delugeapp.core.fixedpoint import from_display

        preset = SynthPreset.new("ENV")
        sound = preset.sound
        sound.osc1.type = "saw"
        sound.set_param("oscAVolume", from_display(45, scale=50))
        sound.set_param("volume", from_display(45, scale=50))
        sound.set_param("lpfFrequency", from_display(45, scale=50))
        sound.env1.attack = from_display(35, scale=50)
        sound.env1.sustain = from_display(45, scale=50)

        mono = np.abs(render.render_sound(sound, seconds=2.0, sr=self.SR,
                                         gate=0.9).mean(axis=1))
        debut = float(np.max(mono[:self.SR // 20]))
        milieu = float(np.max(mono[self.SR // 2:self.SR]))
        self.assertLess(debut, milieu,
                        "l'attaque lente n'est pas respectée")

    def _measured(self, cutoff: int, note: int = 48) -> dict:
        """Mesures d'une dent de scie filtrée à la coupure donnée."""
        from delugeapp.core.fixedpoint import from_display

        preset = SynthPreset.new("F")
        sound = preset.sound
        sound.osc1.type = "saw"
        sound.unison_num = 1
        sound.patch_cables = []
        sound.set_param("oscAVolume", from_display(45, scale=50))
        sound.set_param("oscBVolume", from_display(0, scale=50))
        sound.set_param("volume", from_display(42, scale=50))
        sound.set_param("lpfFrequency", from_display(cutoff, scale=50))
        sound.set_param("lpfResonance", from_display(0, scale=50))
        sound.env1.sustain = from_display(45, scale=50)
        mono = render.render_sound(sound, note=note, seconds=1.0,
                                   sr=self.SR).mean(axis=1)
        out = analysis.spectral(mono, self.SR)
        out.update(analysis.loudness(mono))
        return out

    def test_filtre_eclaircit_en_s_ouvrant(self):
        """Ouvrir le filtre doit éclaircir le son.

        La comparaison n'a de sens qu'au-dessus de la fondamentale jouée. En
        dessous, le filtre coupe la fondamentale elle-même : le niveau
        s'écroule de près de 30 dB et le centroïde **remonte**, puisqu'il ne
        reste que du résidu. Mesuré sur un do 2 (130 Hz), le centroïde
        décroît jusqu'à une coupure de 20 puis croît — c'est une courbe en U,
        et comparer 10 à 30 traversait le creux.
        """
        centroids = [self._measured(c)["centroid"] for c in (20, 30, 40, 50)]
        self.assertEqual(centroids, sorted(centroids),
                         f"le centroïde devrait croître : {centroids}")
        self.assertLess(centroids[0] * 2, centroids[-1])

    def test_filtre_attenue_en_se_fermant(self):
        """Fermer le filtre doit faire baisser le niveau, sans exception."""
        levels = [self._measured(c)["rms_db"]
                  for c in (5, 10, 20, 30, 40, 50)]
        self.assertEqual(levels, sorted(levels),
                         f"le niveau devrait croître avec la coupure : {levels}")
        self.assertLess(levels[0], levels[-1] - 20)

    def test_note_change_la_hauteur(self):
        """Jouer une octave plus haut doit doubler la fondamentale."""
        from delugeapp.core.fixedpoint import from_display

        preset = SynthPreset.new("P")
        sound = preset.sound
        sound.osc1.type = "sine"
        sound.osc2.type = "sine"
        sound.set_param("oscAVolume", from_display(48, scale=50))
        sound.set_param("oscBVolume", from_display(0, scale=50))
        sound.set_param("volume", from_display(45, scale=50))
        sound.set_param("lpfFrequency", from_display(50, scale=50))
        sound.env1.sustain = from_display(48, scale=50)
        sound.unison_num = 1

        for note in (48, 60):
            with self.subTest(note=note):
                mono = render.render_sound(sound, note=note, seconds=1.0,
                                           sr=self.SR).mean(axis=1)
                detected = analysis.estimate_root_note(mono, self.SR)
                self.assertIsNotNone(detected)
                self.assertAlmostEqual(detected % 12, note % 12, delta=0)

    def test_modes_de_synthese(self):
        """Les trois modes doivent produire du son."""
        for mode in ("subtractive", "fm", "ringmod"):
            with self.subTest(mode=mode):
                preset = synthgen.generate(synthgen.GenOptions(
                    genre="techno", seed=1, mode=mode))
                audio = render.render_sound(preset.sound, seconds=0.8,
                                            sr=self.SR)
                self.assertGreater(float(np.max(np.abs(audio))), 0.005)

    def test_sans_carte(self):
        """Un oscillateur ``sample`` sans carte ne doit pas rendre le silence."""
        preset = synthgen.generate(synthgen.GenOptions(
            genre="lofi", seed=1, use_samples=["SAMPLES/absent.wav"]))
        audio = render.render_sound(preset.sound, seconds=0.8, sr=self.SR,
                                    sd=None)
        self.assertGreater(float(np.max(np.abs(audio))), 0.005)

    def test_avec_echantillon_reel(self):
        """Un oscillateur ``sample`` doit lire le fichier de la carte."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "carte"
            (root / "SAMPLES").mkdir(parents=True)
            for sub in ("SONGS", "SYNTHS", "KITS"):
                (root / sub).mkdir()
            t = np.linspace(0, 0.5, 22050, endpoint=False, dtype=np.float32)
            wav.write(root / "SAMPLES" / "s.wav",
                      (0.6 * np.sin(2 * np.pi * 220 * t)).astype(np.float32),
                      44100)
            sd = sdcard.SDCard(root)

            preset = SynthPreset.new("S")
            preset.sound.osc1.type = "sample"
            preset.sound.osc1.file_name = "SAMPLES/s.wav"
            from delugeapp.core.fixedpoint import from_display
            preset.sound.set_param("volume", from_display(45, scale=50))
            preset.sound.set_param("lpfFrequency", from_display(50, scale=50))
            preset.sound.env1.sustain = from_display(45, scale=50)

            audio = render.render_sound(preset.sound, note=60, seconds=1.0,
                                        sr=self.SR, sd=sd)
            self.assertGreater(float(np.max(np.abs(audio))), 0.005)

    def test_un_echantillon_stereo_reste_stereo(self):
        """Le Deluge joue un échantillon stéréo en stéréo, chaque canal au
        gain d'un mono (``Source::renderInStereo``). Mesuré sur la machine le
        23 octobre 2026 : un piano dont les canaux s'opposent en partie
        perdait 5 dB et toute sa largeur, ramené à la moyenne des deux. Ici
        les canaux s'opposent tout à fait : la moyenne serait muette."""
        from delugeapp.core.fixedpoint import from_display

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "carte"
            for sub in ("SAMPLES", "SONGS", "SYNTHS", "KITS"):
                (root / sub).mkdir(parents=True)
            t = np.arange(22050) / 44100.0
            onde = (0.5 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
            wav.write(root / "SAMPLES" / "st.wav",
                      np.stack([onde, -onde], axis=1), 44100)
            wav.write(root / "SAMPLES" / "mono.wav", onde, 44100)
            sd = sdcard.SDCard(root)

            def rendu(nom):
                preset = SynthPreset.new("S")
                preset.sound.osc1.type = "sample"
                preset.sound.osc1.file_name = "SAMPLES/" + nom
                preset.sound.set_param("volume", from_display(25, scale=50))
                return render.render_sound(preset.sound, note=60, seconds=0.4,
                                           sr=self.SR, sd=sd)

            stereo, mono = rendu("st.wav"), rendu("mono.wav")
            gauche = np.sqrt(np.mean(stereo[:, 0] ** 2))
            droite = np.sqrt(np.mean(stereo[:, 1] ** 2))
            self.assertGreater(gauche, 0.005)
            self.assertAlmostEqual(gauche / droite, 1.0, delta=0.01)
            self.assertLess(float(np.corrcoef(stereo[:, 0],
                                              stereo[:, 1])[0, 1]), -0.99)
            self.assertAlmostEqual(gauche / np.sqrt(np.mean(mono[:, 0] ** 2)),
                                   1.0, delta=0.01)

    def test_apercu(self):
        """L'aperçu enchaîne plusieurs notes et reste dans les bornes."""
        preset = synthgen.generate(synthgen.GenOptions(genre="house",
                                                       role="keys", seed=1))
        audio = render.render_preview(preset, sr=self.SR)
        self.assertEqual(audio.ndim, 2)
        self.assertGreater(audio.shape[0], self.SR)
        self.assertLessEqual(float(np.max(np.abs(audio))), 1.0)
        self.assertGreater(float(np.max(np.abs(audio))), 0.005)
        # Notes imposées.
        court = render.render_preview(preset, notes=[60], sr=self.SR)
        self.assertGreater(float(np.max(np.abs(court))), 0.005)

    def test_apercu_notes_invalides(self):
        preset = synthgen.generate(synthgen.GenOptions(seed=1))
        audio = render.render_preview(preset, notes=[999, -5], sr=self.SR)
        self.assertGreater(audio.shape[0], 0)

    def test_rendu_de_kit(self):
        """Un kit se rend rangée par rangée, ou en jouant un motif."""
        kit = Kit.new("K")
        for name in ("KICK", "SNARE", "HATC"):
            row = kit.add_row(name, "")
            row.sound.osc1.type = "square"
            from delugeapp.core.fixedpoint import from_display
            row.sound.set_param("volume", from_display(42, scale=50))
            row.sound.set_param("lpfFrequency", from_display(40, scale=50))
            row.sound.env1.decay = from_display(14, scale=50)

        audio = render.render_kit(kit, sr=self.SR)
        self.assertEqual(audio.ndim, 2)
        self.assertGreater(float(np.max(np.abs(audio))), 0.005)

        pattern = rhythm.genre_beat("techno", bars=1, seed=1)
        joue = render.render_kit(kit, pattern=pattern, bpm=128, sr=self.SR)
        self.assertGreater(joue.shape[0], 0)
        self.assertLessEqual(float(np.max(np.abs(joue))), 1.0)

    def test_rendu_de_kit_vide(self):
        audio = render.render_kit(Kit.new("VIDE"), sr=self.SR)
        self.assertEqual(audio.ndim, 2)
        self.assertGreater(audio.shape[0], 0)

    def test_spectre(self):
        """Le spectre doit situer correctement une sinusoïde connue."""
        t = np.linspace(0, 1, self.SR, endpoint=False, dtype=np.float32)
        sine = (0.5 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
        freqs, db = render.spectrum(sine, self.SR)
        self.assertEqual(freqs.shape, db.shape)
        self.assertAlmostEqual(float(freqs[int(np.argmax(db))]), 1000.0,
                               delta=30)
        self.assertAlmostEqual(float(np.max(db)), 0.0, delta=0.01)
        # Un signal stéréo et un signal trop court ne doivent pas lever.
        stereo = np.stack([sine, sine], axis=1)
        self.assertEqual(render.spectrum(stereo, self.SR)[0].shape,
                         freqs.shape)
        self.assertTrue(render.spectrum(np.zeros(10, dtype=np.float32),
                                        self.SR)[0].size)

    def test_son_impossible_rend_du_silence(self):
        """Un son absurde ne doit pas lever : il rend un tableau silencieux."""
        sound = Sound()
        sound.osc1 = None            # type: ignore[assignment]
        audio = render.render_sound(sound, seconds=0.5, sr=self.SR)
        self.assertEqual(audio.shape, (self.SR // 2, 2))
        self.assertEqual(float(np.max(np.abs(audio))), 0.0)

    def test_tables_du_firmware_livrees(self):
        """Les formes d'onde du firmware voyagent avec l'application
        (``delugeapp/data/deluge_tables.npz``) : sans elles, le moteur ne
        rend rien. Chaque table se termine par sa valeur de bouclage."""
        from delugeapp.core import dsp

        for name in dsp._SAW_TABLES[6:] + dsp._ANALOG_SAW_TABLES \
                + dsp._ANALOG_SQUARE_TABLES:
            with self.subTest(table=name):
                tab = dsp.table(name)
                self.assertEqual(tab.size, (1 << dsp._magnitude(tab)) + 1)
                self.assertLessEqual(float(np.max(np.abs(tab))), 32767.0)
                self.assertAlmostEqual(float(tab[0]), float(tab[-1]),
                                       delta=1.0)


class TestTraitementDuFirmware(unittest.TestCase):
    """:mod:`dsp`, le traitement du signal porté du firmware de la machine
    (1.3, ``102cf9f``), le 23 octobre 2026.

    Les références entières reprennent le code C ligne à ligne
    (``multiply_32x32_rshift32`` compris) ; le portage, en flottants, doit
    les suivre. Mesuré à l'écriture : l'échelle passe-bas à 6·10⁻⁵ près, le
    passe-haut à 2·10⁻⁵, les formes d'onde à 6·10⁻⁸.
    """

    def setUp(self):
        from delugeapp.core import dsp

        self.dsp = dsp

    # -- hauteurs -------------------------------------------------------- #

    def test_reglages_fins_en_entiers(self):
        """La hauteur se calcule en entiers, comme sur la machine : réglage
        fin lu dans ``centAdjustTableSmall`` (2³⁰ à zéro, deux bits faibles
        tronqués), désaccord d'unisson en pas égaux (la voix du milieu d'un
        nombre impair intacte), réglage de hauteur arrondi puis ``<< 8``.
        Vérifié sur la machine le 23 octobre 2026 : un unisson de 4 au
        désaccord 20 identique à −80 dB près pendant toute la note, quand
        ``2^(c/1200)`` exact dérivait jusqu'à −28 dB en une demi-seconde."""
        d = self.dsp
        self.assertEqual(d.fine_tuner(0), 1 << 30)
        self.assertEqual(d.fine_tune(1001, 1 << 30), 1000)
        for cents in (-50, -10, 3, 25, 50):
            with self.subTest(cents=cents):
                facteur = d.fine_tuner(cents * d.CENT_SCALE) / float(1 << 30)
                self.assertAlmostEqual(facteur, 2 ** (cents / 1200.0),
                                       delta=3e-5)
        quatre = d.unison_detuners(20, 4)
        self.assertTrue(quatre[0] < quatre[1] < (1 << 30) < quatre[2]
                        < quatre[3])
        self.assertEqual(d.unison_detuners(20, 3)[1], 1 << 30)
        self.assertEqual(d.unison_detuners(20, 1), [1 << 30])
        self.assertEqual(int(d.adjust_pitch(12345678, d.SAMPLE_UNITY)),
                         12345678)
        self.assertEqual(int(d.adjust_pitch(12345678, d.pitch_adjustment(1.0))),
                         ((12345678 * (1 << 25) + (1 << 31)) >> 32) << 8)
        self.assertEqual(int(d.adjust_pitch(1 << 30, d.pitch_adjustment(2.0))),
                         0)                            # trop aigu
        self.assertEqual(d.sample_increment(60, 44100), 1 << 24)
        self.assertEqual(d.sample_increment(72, 44100), 1 << 25)
        self.assertEqual(d.sample_increment(48, 44100), 1 << 23)
        self.assertAlmostEqual(d.sample_increment(60, 48000) / float(1 << 24),
                               48000 / 44100, delta=1e-6)

    # -- échantillons ---------------------------------------------------- #

    def test_noyau_de_lecture_selon_la_vitesse(self):
        """``getWhichKernel`` : le noyau 0 jusqu'à un demi-ton au-dessus de
        la hauteur d'origine, puis un noyau de plus par demi-octave montée,
        jusqu'au sixième."""
        k = self.dsp.sample_kernel
        self.assertEqual(k(1 << 23), 0)               # une octave en dessous
        self.assertEqual(k(1 << 24), 0)
        self.assertEqual(k(17268825), 0)
        self.assertEqual(k(17268826), 1)
        self.assertEqual(k(18260572), 1)              # 48 kHz à sa hauteur
        self.assertEqual(k(23051117), 2)
        self.assertEqual(k(1 << 25), 3)               # une octave au-dessus
        self.assertEqual(k(1 << 26), 5)
        self.assertEqual(k(1 << 28), 6)

    def test_lecture_d_echantillon_comme_la_machine(self):
        """``readSamplesResampled`` : à sa hauteur, l'échantillon sort tel
        quel ; transposé, un sinus cardinal fenêtré le relit sur 16 bits, et
        la sortie ``t`` lit la position ``(t + 1)·r − 1``. Vérifié sur la
        machine le 23 octobre 2026 : un piano joué à l'octave et une caisse
        claire à 48 kHz relus à −80 et −69 dB près, contre −19 et −33 dB par
        interpolation linéaire."""
        d = self.dsp
        t = np.arange(20000)
        x = 0.5 * np.sin(2 * np.pi * t / 97.3)
        brut = d.read_sample(x, [1 << 24] * 100, 12000)
        self.assertTrue(np.array_equal(brut, x[:12000]))
        stereo = d.read_sample(np.stack([x, -x], axis=1), [1 << 24] * 100,
                               12000)
        self.assertEqual(stereo.shape, (2, 12000))
        for vitesse in (0.5, 48000 / 44100, 1.5):
            inc = int(round(vitesse * (1 << 24)))
            n = 8000
            lu = d.read_sample(x, [inc] * 70, n)
            pos = ((np.arange(n) + 1) * inc - (1 << 24)) / float(1 << 24)
            attendu = 0.5 * np.sin(2 * np.pi * pos / 97.3)
            garde = slice(20, n - 20)
            ecart = np.sqrt(np.mean((lu[garde] - attendu[garde]) ** 2))
            with self.subTest(vitesse=vitesse):
                self.assertLess(ecart, 2e-4)
        # Après la fin, du silence.
        fin = d.read_sample(x[:100], [inc] * 2, 200)
        self.assertEqual(float(np.max(np.abs(fin[120:]))), 0.0)

    # -- oscillateurs ---------------------------------------------------- #

    def test_hauteur_et_choix_des_tables(self):
        """``noteFrequencyTable >> (20 − octave)`` : le la 3 à 440 Hz. Sous
        72 Hz, la dent de scie et le carré sont calculés « crus », sans
        table (``getTableNumber`` < 6)."""
        d = self.dsp
        self.assertAlmostEqual(d.note_increment(69) * 44100 / 2 ** 32, 440.0,
                               delta=0.01)
        self.assertEqual(int(d.table_numbers(d.note_increment(36))), 5)
        self.assertEqual(int(d.table_numbers(d.note_increment(48))), 7)
        self.assertEqual(d._reader("saw", d.note_increment(36), 0, False).mode,
                         "saw")
        self.assertEqual(d._reader("saw", d.note_increment(48), 0, False).name,
                         "sawWave153")
        # La dent de scie numérique : une série en 1/h exacte, fondamentale
        # à 32768/π.
        tab = d.table("sawWave215")
        fundamental = np.abs(np.fft.rfft(tab[:-1]))[1] / 1024.0
        self.assertAlmostEqual(fundamental, 32768.0 / np.pi, delta=2.0)

    def test_niveaux_des_formes_a_amplitude_egale(self):
        """À amplitude égale, le carré sort 5 dB au-dessus de la dent de
        scie et du triangle — l'ancien moteur les normalisait tous."""
        d = self.dsp
        n = 44100
        inc = np.full(-(-n // d.BLOCK), d.note_increment(48))
        amp = np.full(n, float(1 << 25))
        attendu = {"square": 0.508, "saw": 0.288, "sine": 0.354,
                   "triangle": 0.289, "analogSaw": 0.300,
                   "analogSquare": 0.493}
        for kind, rms in attendu.items():
            with self.subTest(kind=kind):
                wave, _ = d.oscillator(kind, inc, n, 0, amp=amp)
                self.assertAlmostEqual(
                    float(np.sqrt(np.mean(wave ** 2))) / (1 << 25), rms,
                    delta=0.01)

    def test_largeur_d_impulsion_du_carre(self):
        """``pulseWidth`` ajoute sa moitié de période à la partie haute du
        carré : +2³⁰ donne 75 % de temps haut."""
        d = self.dsp
        n = 44100
        nb = -(-n // d.BLOCK)
        wave, _ = d.oscillator("square", np.full(nb, d.note_increment(36)), n,
                               0, amp=np.full(n, float(1 << 25)),
                               pulse_blocks=np.full(nb, 1 << 30))
        self.assertAlmostEqual(float(np.mean(wave > 0)), 0.75, delta=0.01)

    def test_largeur_d_impulsion_des_autres_formes(self):
        """Pour les autres formes, la largeur passe par une synchronisation :
        l'onde court plus vite et repart à chaque période. Le son s'éclaire,
        sa hauteur reste. 400 sons de la carte s'en servent."""
        d = self.dsp
        n = 44100
        nb = -(-n // d.BLOCK)
        inc = np.full(nb, d.note_increment(48))
        amp = np.full(n, float(1 << 25))

        def centroid(x):
            s = np.abs(np.fft.rfft(x * np.hanning(x.size)))
            f = np.fft.rfftfreq(x.size, 1 / 44100)
            return float(np.sum(s * f) / np.sum(s))

        f0 = d.note_increment(48) * 44100 / 2 ** 32
        freqs = np.fft.rfftfreq(n, 1 / 44100)
        harmonic = np.abs(freqs / f0 - np.round(freqs / f0)) * f0 < 3.0
        for kind in ("saw", "triangle", "sine"):
            with self.subTest(kind=kind):
                plain, _ = d.oscillator(kind, inc, n, 0, amp=amp)
                synced, _ = d.oscillator(kind, inc, n, 0, amp=amp,
                                         pulse_blocks=np.full(nb, 1 << 30),
                                         retrig=0)
                self.assertGreater(centroid(synced), centroid(plain) * 1.2)
                # La hauteur reste : l'énergie tombe sur les harmoniques de
                # la note.
                power = np.abs(np.fft.rfft(synced * np.hanning(n))) ** 2
                self.assertGreater(float(np.sum(power[harmonic])
                                         / np.sum(power)), 0.9)

    # -- filtres --------------------------------------------------------- #

    @staticmethod
    def _echelle_entiere(freq, res, x):
        """``LpLadderFilter`` 24 dB, en entiers comme le firmware (sans
        gigue de coupure)."""
        from delugeapp.core import dsp

        def wrap(v):
            return ((v + (1 << 31)) & 0xFFFFFFFF) - (1 << 31)

        def m32r(a, b):
            return wrap((a * b + (1 << 31)) >> 32)

        def lsat(v, s):
            return max(-(1 << 31), min((1 << 31) - 1, v << s))

        tan = [int(v) for v in dsp.table("tanTable")]
        tanh = [int(v) for v in dsp.table("tanHSmall")]
        f = lsat(freq, 5)
        which, further = f >> 25, (f << 6) & 2147483647
        v1, v2 = tan[which], tan[min(which + 1, 64)]
        tanned = (wrap((v2 * further) >> 32)
                  + wrap((v1 * (2147483647 - further)) >> 32)) << 1
        div = int(288230376151711744.0 / float(134217728 + (tanned >> 1)))
        mv = max(m32r(tanned, div) << 4, 4317840)
        r = 2147483647 - (min(res, 510000000) << 2)
        r = m32r(r, r) << 1
        pr = m32r(2147483647 - r, 2147483647 - 33) << 1
        f3 = m32r(div, mv)
        f2 = m32r(f3, mv) << 1
        f1 = m32r(f2, mv) << 1
        total = int(72057594037927936.0 / float(
            67108864 + m32r(mv, m32r(mv, m32r(mv, m32r(mv, pr))))))
        pr = m32r(pr, 1150000000) << 1 if tanned <= 304587486 else pr >> 1
        mem = [0, 0, 0, 0]
        out = []
        for v in x:
            fbs = (m32r(mem[0], f1) + m32r(mem[1], f2) + m32r(mem[2], f3)
                   + m32r(mem[3], div)) << 2
            u = m32r(wrap(v - (m32r(fbs, pr) << 3)), total) << 2
            if pr > 510000000:
                w = (lsat(u, 2) + 2147483648) & 0xFFFFFFFF
                k = w >> 24
                s2 = (w >> 8) & 65535
                u = wrap(tanh[k] * (65536 - s2) + tanh[k + 1] * s2) >> 4
            for i in range(4):
                a = m32r(wrap(u - mem[i]), mv) << 1
                b = wrap(a + mem[i])
                mem[i] = wrap(b + a)
                u = b
            out.append(wrap(u << 1))
        return np.array(out, dtype=np.float64)

    def test_echelle_24db_contre_le_firmware_entier(self):
        """L'échelle 24 dB portée suit le calcul entier du firmware, avec et
        sans saturation de l'entrée (résonance au-delà de 13)."""
        d = self.dsp
        n = 1500
        t = np.arange(n)
        x = np.round(20000000 * np.sin(2 * np.pi * 220 * t / 44100)
                     + 6000000 * np.sin(2 * np.pi * 3170 * t / 44100))
        for freq, res in ((2000000, 0), (2000000, 268435456),
                          (9000000, 400000000), (40000000, 134217728)):
            with self.subTest(freq=freq, res=res):
                ref = self._echelle_entiere(freq, res, x.astype(np.int64).tolist())
                cfg = d.lpf_config("24dB", [freq] * 12, [res] * 12)
                got = d.lpf_process(x, cfg, np.ones(n))
                self.assertLess(float(np.max(np.abs(got - ref))),
                                1e-3 * float(np.max(np.abs(ref))))

    def test_compensation_de_niveau_des_filtres(self):
        """``filterGain`` : l'échelle froide divise par deux sans
        résonance, rend 1,25 au réglage 25 et 1,5 en butée ; le « drive »
        garde 0,8 ; le passe-haut retire jusqu'à 59 % en butée."""
        d = self.dsp
        cfg = d.lpf_config("24dB", [2000000] * 3, [0, 268435456, 536870911])
        np.testing.assert_allclose(cfg.gain, [0.5, 1.25, 1.5], atol=1e-3)
        cfg = d.lpf_config("24dBDrive", [2000000], [268435456])
        self.assertAlmostEqual(float(cfg.gain[0]), 0.8)
        cfg = d.hpf_config([2672947] * 2, [0, 536870911])
        self.assertAlmostEqual(float(cfg.gain[0]), 1.0, delta=1e-3)
        self.assertAlmostEqual(float(cfg.gain[1]), 1 - 19 / 32, delta=0.015)

    def test_reponse_lineaire_exacte(self):
        """La courbe de l'interface est la fonction de transfert exacte de
        l'échelle linéarisée : elle redonne la réponse impulsionnelle."""
        d = self.dsp
        size = 8192
        impulse = np.zeros(size)
        impulse[0] = float(1 << 18)
        freqs = np.array([100.0, 1000.0, 3000.0, 9000.0])
        grid = np.fft.rfftfreq(size, 1 / 44100)
        for mode, freq, res in (("24dB", 4e6, 1e8), ("12dB", 4e6, 2e8),
                                ("24dBDrive", 6e6, 2e8)):
            with self.subTest(mode=mode):
                cfg = d.lpf_config(mode, [freq] * 64, [res] * 64)
                y = d.lpf_process(impulse, cfg, np.ones(size))
                sim = np.interp(freqs, grid,
                                np.abs(np.fft.rfft(y)) / float(1 << 18))
                np.testing.assert_allclose(
                    np.abs(d.lpf_response(cfg, freqs)), sim, rtol=1e-3)
        cfg = d.hpf_config([3e6] * 64, [2.5e8] * 64)
        y = d.hpf_process(impulse, cfg)
        sim = np.interp(freqs, grid, np.abs(np.fft.rfft(y)) / float(1 << 18))
        np.testing.assert_allclose(np.abs(d.hpf_response(cfg, freqs)), sim,
                                   rtol=1e-3)

    # -- enveloppes, FM, panoramique ------------------------------------ #

    def test_enveloppe_par_blocs(self):
        """L'enveloppe avance par blocs de 128 échantillons : au réglage 25,
        l'attaque dure 2 048 échantillons (16 blocs), puis le decay mène au
        palier en ``2²³ / vitesse`` échantillons."""
        from delugeapp.core import paramlaws as laws

        d = self.dsp
        env = d.Envelope()
        attack = float(laws.attack_rate(0.0))
        decay = float(laws.decay_rate(-0.8))    # réglage 5 : 200 blocs
        env.note_on(attack, 1 << 30)
        values, states = [], []
        for _ in range(400):
            values.append(env.render(attack, decay, 1 << 30, 1000.0))
            states.append(env.state)
        top = int(np.argmax(values))
        self.assertIn(top, (15, 16))
        self.assertAlmostEqual(values[top] / d.Q31, 1.0, delta=0.01)
        palier = states.index(d.Envelope.SUSTAIN)
        blocks = float(1 << 23) / decay / d.BLOCK
        self.assertAlmostEqual(palier - top, blocks, delta=2)
        # Au palier, la moitié de l'échelle : 0 en valeur bipolaire.
        self.assertAlmostEqual(values[-1] / d.Q31, 0.0, delta=0.01)

    def test_indice_de_la_fm(self):
        """La phase de la porteuse est poussée de ``modulation << 8`` : une
        modulation de 2²⁴ fait un tour entier (le même sinus), 2²³ un
        demi-tour (le sinus inversé). Un modulateur au réglage 25 (2²⁵)
        sort ±2²⁴ : ±2π radians — l'ancien moteur en mettait 1,5."""
        d = self.dsp
        n = 2048
        nb = n // d.BLOCK
        inc = np.full(nb, d.note_increment(60))
        amp = np.full(n, float(1 << 26))
        plain, _, _ = d.fm_operator(inc, n, 0, amp)
        tour, _, _ = d.fm_operator(inc, n, 0, amp, np.full(n, float(1 << 24)))
        demi, _, _ = d.fm_operator(inc, n, 0, amp, np.full(n, float(1 << 23)))
        np.testing.assert_allclose(tour, plain, atol=2e-3 * (1 << 25))
        np.testing.assert_allclose(demi, -plain, atol=2e-3 * (1 << 25))
        modulator, _, _ = d.fm_operator(inc, n, 0, np.full(n, float(1 << 25)))
        self.assertAlmostEqual(float(np.max(np.abs(modulator))) / (1 << 24),
                               1.0, delta=0.01)

    def test_panoramique_lineaire(self):
        """``shouldDoPanning`` : au centre, plein niveau des deux côtés
        (l'ancien moteur perdait 3 dB) ; d'un côté, l'autre voie se tait."""
        d = self.dsp
        left, right = d.pan_amplitudes([0, 1 << 30, -(1 << 29)])
        np.testing.assert_allclose(left, [1.0, 0.0, 1.0])
        np.testing.assert_allclose(right, [1.0, 1.0, 0.5])

    # -- effets ---------------------------------------------------------- #

    def test_delay_temps_et_ping_pong(self):
        """Le tampon du delay vaut 16 384 échantillons au réglage neutre
        (0,37 s) ; la rétroaction vaut l'unité au réglage 25 ; en ping-pong,
        le premier écho part à droite, le second revient à gauche.

        Mesuré sur la machine (export de pistes, 23 octobre 2026) : le
        premier écho revient après la longueur entière du tampon, les
        suivants un échantillon plus tôt — 16 384, puis 16 383 à chaque
        tour. Avec 16 384 partout, les échos dérivaient d'un échantillon
        par répétition."""
        d = self.dsp
        self.assertEqual(float(d.delay_samples(1 << 24)), 16384.0)
        n = 60000
        x = np.zeros((2, n))
        x[:, 10] = float(1 << 26)
        out = d.delay(x, 16384.0, float(1 << 29), True, False)
        echo1 = out[:, 10 + 16384]
        echo2 = out[:, 10 + 16384 + 16383]
        self.assertAlmostEqual(echo1[1] / (1 << 26), 0.5, delta=0.01)
        self.assertAlmostEqual(echo1[0], 0.0, delta=1e3)
        self.assertAlmostEqual(echo2[0] / (1 << 26), 0.25, delta=0.01)
        self.assertAlmostEqual(echo2[1], 0.0, delta=1e3)
        echo3 = out[1, 10 + 16384 + 2 * 16383]
        self.assertAlmostEqual(echo3 / (1 << 26), 0.125, delta=0.01)
        # Pas d'écho ailleurs : ni à la longueur entière à chaque tour, ni un
        # échantillon trop tôt au premier (le filtre anti-continu laisse une
        # traîne d'un dix-millième de l'écho, pas davantage).
        self.assertAlmostEqual(out[0, 10 + 2 * 16384], 0.0, delta=1e5)
        self.assertAlmostEqual(out[1, 10 + 16383], 0.0, delta=1e5)
        both = d.delay(x, 16384.0, float(1 << 29), False, False)
        self.assertAlmostEqual(both[0, 10 + 16384] / (1 << 26), 0.5, delta=0.01)

    def test_reverberations(self):
        """« Mutable » (morceau neuf) et Freeverb (morceau sans modèle) :
        une queue stéréo qui s'éteint, finie."""
        d = self.dsp
        n = 3 * 44100
        send = np.zeros(n)
        send[100] = float(1 << 28)
        for model in (1, 0):
            with self.subTest(model=model):
                wet = d.reverb(send, d.ReverbSettings(model=model))
                self.assertTrue(bool(np.all(np.isfinite(wet))))
                early = float(np.sum(wet[:, :22050] ** 2))
                late = float(np.sum(wet[:, 88200:] ** 2))
                self.assertGreater(early, 0.0)
                self.assertLess(late, early / 10.0)
                self.assertGreater(float(np.max(np.abs(wet[0] - wet[1]))), 0.0)

    def test_sortie_au_niveau_du_deluge(self):
        """Un mélange de 2²⁴ sort à 0,29 de pleine échelle : le volume
        maître, les filtres du morceau ouverts (−20 %), le compresseur maître
        au repos — gain de base 0,85 pour un morceau, et non 1,35 —, puis
        ``<< 8`` vers le convertisseur. Sa saturation adoucie moyenne deux
        échantillons : −1,6 dB à 8 kHz, −7,6 dB à 16 kHz.

        Mesuré sur la machine (export avec Song FX, 4 novembre 2026) : avec
        1,35, l'écoute du PC sortait 4,4 dB trop fort et trop brillante."""
        d = self.dsp
        self.assertAlmostEqual(d.OUTPUT_GAIN * 2 ** 24, 0.2928, delta=0.001)
        t = np.arange(44100) / 44100.0
        for f, attendu in ((1000, 0.0), (8000, -1.6), (16000, -7.6)):
            x = float(1 << 20) * np.sin(2 * np.pi * f * t)
            y = d.output_stage(np.stack([x, x]))
            gain = np.sqrt(np.mean(y[0, 100:] ** 2) / np.mean(x[100:] ** 2))
            with self.subTest(f=f):
                self.assertAlmostEqual(20 * np.log10(gain / d.OUTPUT_GAIN),
                                       attendu, delta=0.1)


def _son_complet():
    """Un son qui passe par presque toutes les boucles du traitement du
    signal : dent de scie et carré à largeur d'impulsion modulée, unisson
    stéréo, échelle 24 dB saturée, passe-haut, écrêtage, phaser, delay et
    réverbération."""
    from delugeapp.core.model import PatchCable

    sound = SynthPreset.new("BOUCLES").sound
    sound.osc1.type = "saw"
    sound.osc2.type = "square"
    sound.unison_num = 3
    sound.unison_spread = 30
    sound.unison_detune = 12
    sound.lpf_mode = "24dB"
    sound.mod_fx_type = "phaser"
    sound.clipping_amount = 2
    for cle, valeur in (("oscAVolume", 40), ("oscBVolume", 35),
                        ("oscBPulseWidth", 20), ("lpfFrequency", 30),
                        ("lpfResonance", 45), ("hpfFrequency", 8),
                        ("modFXDepth", 30), ("delayFeedback", 20),
                        ("reverbAmount", 20), ("volume", 40)):
        sound.set_param(cle, from_display(valeur, scale=50))
    sound.patch_cables = [
        PatchCable("lfo1", "oscBPulseWidth",
                   PatchCable.amount_from_display(20)),
        PatchCable("envelope2", "lpfFrequency",
                   PatchCable.amount_from_display(15))]
    return sound


class TestEcouteCompilee(unittest.TestCase):
    """Les boucles du traitement du signal, compilées par numba, et les
    voix d'une écoute calculées en parallèle (5 novembre 2026).

    Écouter une section de huit mesures à l'atelier prenait 2,5 à 9 s en
    Python pur ; compilé et sur quatre fils, 0,3 à 1 s. Le calcul ne change
    pas : chaque boucle compilée rend les mêmes nombres que la même
    fonction en Python, et le nombre de fils ne change rien au son."""

    def setUp(self):
        from delugeapp.core import dsp

        self.dsp = dsp
        if not dsp.compiled():
            self.skipTest("numba n'est pas installé")
        self.addCleanup(setattr, dsp, "_compiled", True)

    def _deux_fois(self, calcul):
        """``calcul()`` compilé, puis en Python."""
        self.dsp._compiled = True
        compile_ = calcul()
        self.dsp._compiled = False
        try:
            python = calcul()
        finally:
            self.dsp._compiled = True
        return compile_, python

    def _memes(self, a, b, rtol=0.0, msg=None):
        a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
        self.assertEqual(a.shape, b.shape, msg)
        if rtol:
            crete = float(np.max(np.abs(b))) or 1.0
            self.assertLessEqual(float(np.max(np.abs(a - b))), rtol * crete,
                                 msg)
        else:
            self.assertTrue(np.array_equal(a, b), msg)

    def test_chaque_boucle_compilee_rend_les_nombres_du_python(self):
        """À l'échantillon près, sauf le lissage à un pôle, que le Python
        calcule d'un tableau entier par doublements : là, l'arrondi seul
        diffère (10⁻¹⁵ de la crête)."""
        d = self.dsp
        n = 6000
        nb = -(-n // d.BLOCK)
        t = np.arange(n)
        x = np.round(3e7 * np.sin(2 * np.pi * 110 * t / 44100)
                     + 9e6 * np.sin(2 * np.pi * 2170 * t / 44100))
        stereo = np.stack([x, np.roll(x, 37) * 0.7])
        jitter = 1.0 + np.random.default_rng(4).uniform(-0.005, 0.005, n)
        freq = np.linspace(1e6, 6e7, nb)
        for mode in ("12dB", "24dB", "24dBDrive"):
            for res, morph in ((0.0, 0.0), (5.3e8, 0.0), (4.5e8, 3e8)):
                cfg = d.lpf_config(mode, freq, np.full(nb, res),
                                   np.full(nb, morph))
                self._memes(*self._deux_fois(
                    lambda: d.lpf_process(x, cfg, jitter)),
                    msg="passe-bas %s %g" % (mode, res))
        resonance = np.full(nb, 5.36e8)
        resonance[:nb // 3] = 0.0
        resonance[nb // 3:2 * nb // 3] = 4.6e8
        hcfg = d.hpf_config(np.linspace(3e5, 3e7, nb), resonance)
        self._memes(*self._deux_fois(lambda: d.hpf_process(x, hcfg)),
                    msg="passe-haut")
        amp = np.full(n, float(1 << 26))
        pw = np.linspace(0, 1.5e9, nb).astype(np.int64)
        sale = np.full(n, 7.0)
        for kind in ("sine", "triangle", "square", "saw", "analogSaw",
                     "analogSquare"):
            for note in (20, 57, 110):
                incs = np.linspace(d.note_increment(note),
                                   d.note_increment(note + 7),
                                   nb).astype(np.int64)
                for pulse in (None, pw):
                    for a in (amp, None):
                        compile_, python = self._deux_fois(
                            lambda: d.oscillator(kind, incs, n, 987654321,
                                                 a, pulse, 0)[0])
                        self._memes(compile_, python, msg="%s %d" % (kind,
                                                                     note))
                        # Un tampon déjà sali rend la même onde.
                        self._memes(d.oscillator(kind, incs, n, 987654321, a,
                                                 pulse, 0, out=sale)[0],
                                    python, msg="tampon réutilisé")
        inc = np.full(nb, d.note_increment(57))
        self._memes(*self._deux_fois(lambda: d.fm_operator(
            inc, n, 12345, amp, np.full(n, 3e6), np.full(nb, 1.9e9))[0]),
            msg="FM rétroaction")
        for args in ((300000.0, 5000.0, 9e8, 800.0, 30, True),
                     (40.0, 300.0, 0.0, 20.0, 20, False),
                     (2000.0, 300.0, -2147483648.0, 90000.0, 10, True)):
            compile_, python = self._deux_fois(
                lambda: d.envelope_blocks(*args[:4], nb, *args[4:]))
            self._memes(compile_[0], python[0], msg="enveloppe %r" % (args,))
            self.assertEqual(compile_[1], python[1])
        self._memes(*self._deux_fois(lambda: d.ladder_jitter(
            n, np.random.default_rng(9))[0]), rtol=1e-12, msg="gigue")
        self._memes(*self._deux_fois(lambda: d.tanh_antialiased(x * 9, 5)[0]),
                    msg="saturation")
        self._memes(*self._deux_fois(lambda: d.bitcrush_srr(
            stereo, 5e8, 3e8, 1e9)[0]), msg="réduction")
        for kind in ("phaser", "flanger", "chorus"):
            self._memes(*self._deux_fois(lambda: d.mod_fx(
                stereo, kind, 30000.0, 6e8, 0.0, 9e8, 1e9)[0]), msg=kind)
        for model in (0, 1):
            self._memes(*self._deux_fois(lambda: d.reverb(
                x, d.ReverbSettings(model=model))), rtol=1e-12,
                msg="réverbération %d" % model)
        self._memes(*self._deux_fois(lambda: d.one_pole(x, 1 / 128, 3e6)[0]),
                    rtol=1e-12, msg="un pôle")
        # Aucune boucle n'est retombée sur Python en route.
        self.assertTrue(d.compiled())

    def test_le_nombre_de_fils_ne_change_rien_au_son(self):
        """Une section de l'atelier, sur un fil puis sur quatre : les voix
        finissent dans un autre ordre, le mélange reste le même à
        l'échantillon près — chaque voix tire son hasard de sa note."""
        from unittest import mock

        from delugeapp.core import atelier

        projet = atelier.new_project(atelier.Style(genre="trance", seed=3))
        parts, _drums, _bars = atelier.section_parts(
            projet, atelier.fullest_section(projet))
        sons = atelier.listen_sounds(projet)
        sons = {k: v for k, v in sons.items() if k in parts}
        rendus = []
        for fils in (1, 4, 4):
            with mock.patch.object(render, "WORKERS", fils):
                rendus.append(render.render_parts(
                    parts, sons, bpm=projet.style.tempo(), normalize=False))
        self.assertGreater(float(np.max(np.abs(rendus[0]))), 0.01)
        for rendu in rendus[1:]:
            self.assertTrue(np.array_equal(rendus[0], rendu))

    def test_l_arret_interrompt_le_calcul_en_parallele(self):
        """Demandé pendant le calcul des voix, l'arrêt rend ``None`` sans
        attendre la fin de toutes."""
        from unittest import mock

        from delugeapp.core.accomp import NoteEvent

        son = _son_complet()
        partie = [NoteEvent(i * 4, 4, 45 + i, 100) for i in range(16)]
        appels = []

        def arret():
            appels.append(1)
            return len(appels) > 1

        with mock.patch.object(render, "WORKERS", 4):
            self.assertIsNone(render.render_parts({"A": partie}, {"A": son},
                                                  should_stop=arret))

    def test_sans_numba_l_ecoute_rend_le_meme_son(self):
        """numba absent — paquet non installé, ou version de Python qu'il
        ne connaît pas encore —, l'écoute tourne en Python et rend le même
        son, à l'arrondi du lissage près."""
        import subprocess
        import sys
        import textwrap

        with tempfile.TemporaryDirectory() as tmp:
            chemin = Path(tmp) / "BOUCLES.XML"
            preset = SynthPreset.new("BOUCLES")
            preset.sound = _son_complet()
            preset.save(chemin, backup=False)
            son = SynthPreset.load(chemin).sound
            attendu = render.render_sound(son, note=45, seconds=0.5,
                                          sr=22050)
            sortie = Path(tmp) / "rendu.npy"
            code = textwrap.dedent("""
                import os, sys
                sys.modules["numba"] = None
                os.environ["NOCTILUCA_CONFIG"] = sys.argv[3]
                sys.path.insert(0, sys.argv[4])
                import numpy as np
                from delugeapp.core import dsp, render
                from delugeapp.core.model import SynthPreset
                assert not dsp.compiled()
                son = SynthPreset.load(sys.argv[1]).sound
                np.save(sys.argv[2], render.render_sound(
                    son, note=45, seconds=0.5, sr=22050))
            """)
            depot = str(Path(__file__).resolve().parent.parent)
            fait = subprocess.run(
                [sys.executable, "-c", code, str(chemin), str(sortie),
                 str(BAC_A_SABLE), depot],
                capture_output=True, text=True, timeout=300)
            self.assertEqual(fait.returncode, 0, fait.stderr[-2000:])
            obtenu = np.load(sortie)
        self.assertGreater(float(np.max(np.abs(attendu))), 0.01)
        self._memes(obtenu, attendu, rtol=1e-9)

    def test_numba_ne_s_importe_qu_au_premier_calcul(self):
        """Tracer une courbe de filtre — dans le fil de l'interface — ne
        charge pas numba, une demi-seconde d'import ; la première écoute,
        dans son fil, le charge."""
        import subprocess
        import sys
        import textwrap

        code = textwrap.dedent("""
            import os, sys
            os.environ["NOCTILUCA_CONFIG"] = sys.argv[1]
            sys.path.insert(0, sys.argv[2])
            import numpy as np
            from delugeapp.core import render
            from delugeapp.core.model import SynthPreset
            render.filter_response(np.geomspace(20, 20000, 64), 30.0, 20.0)
            avant = "numba" in sys.modules
            render.render_sound(SynthPreset.new("A").sound, seconds=0.1)
            print(avant, "numba" in sys.modules)
        """)
        depot = str(Path(__file__).resolve().parent.parent)
        fait = subprocess.run([sys.executable, "-c", code, str(BAC_A_SABLE),
                               depot], capture_output=True, text=True,
                              timeout=120)
        self.assertEqual(fait.returncode, 0, fait.stderr[-2000:])
        self.assertEqual(fait.stdout.split(), ["False", "True"])

    def test_une_compilation_refusee_retombe_sur_python(self):
        """Une boucle que numba refuse tourne en Python, avec une trace ; les
        suivantes aussi, et leurs tableaux leur arrivent alors en listes."""
        d = self.dsp

        def refusee(values):
            # Un objet Python quelconque : numba ne sait pas le typer.
            return len([object()]) + values[0]

        boucle = d._Boucle(refusee)
        with self.assertLogs("delugeapp.core.dsp", "WARNING"):
            self.assertEqual(boucle(np.array([3.0])), 4.0)
        self.assertFalse(d.compiled())
        self.assertIsInstance(d._seq(np.array([1.0])), list)


class TestLoisDuFirmware(unittest.TestCase):
    """:mod:`paramlaws` face au firmware de la machine (1.3, ``102cf9f``).

    Les valeurs attendues viennent d'un portage **entier** du code du
    firmware (``getExp``, ``lookupReleaseRate``, ``instantTan``,
    ``Envelope::render``), fait le 22 octobre 2026 : les lois en flottants
    doivent les redonner. Jusque-là, le moteur d'écoute estimait ces lois, et
    un decay de 13 y durait 36 ms au lieu de 1,8 s.
    """

    def setUp(self):
        from delugeapp.core import paramlaws

        self.laws = paramlaws

    def test_durees_d_enveloppe(self):
        L = self.laws
        for reglage, attaque, decay, release in (
                (3, 0.0012, 0.3409, 0.1703), (13, 0.0063, 1.7945, 0.8973),
                (21, 0.0239, 3.5890, 1.7777), (25, 0.0464, 4.8774, 2.4078),
                (50, 2.9722, 63.4060, 27.1740)):
            with self.subTest(reglage=reglage):
                u = float(L.unit(reglage))
                self.assertAlmostEqual(float(L.attack_seconds(6 * u)), attaque,
                                       delta=attaque * 0.02)
                self.assertAlmostEqual(float(L.decay_seconds(u)), decay,
                                       delta=decay * 0.001)
                self.assertAlmostEqual(float(L.release_seconds(u)), release,
                                       delta=release * 0.001)
        # Réglage 0 : le firmware saute l'attaque.
        self.assertEqual(float(L.attack_seconds(6 * float(L.unit(0)))), 0.0)

    def test_coupures_et_vitesses(self):
        L = self.laws
        for reglage, lpf, lfo in ((0, 12.4, 0.004877), (19, 237.3, 0.3303),
                                  (25, 602.4, 1.25), (40, 6185.3, 34.82),
                                  (50, 20214.0, 319.99)):
            with self.subTest(reglage=reglage):
                self.assertAlmostEqual(
                    float(L.lpf_hz(L.exp_octaves("lpfFrequency", reglage))),
                    lpf, delta=lpf * 0.002)
                self.assertAlmostEqual(
                    float(L.lfo_hz(L.exp_octaves("lfo1Rate", reglage))),
                    lfo, delta=lfo * 0.002)

    def test_volume_quadratique_et_unisson(self):
        L = self.laws
        # Le réglage 25 sonne 12 dB sous le réglage 50.
        self.assertAlmostEqual(float(L.volume_gain(1 + L.unit(25))
                                     / L.volume_gain(1 + L.unit(50))), 0.25,
                               places=3)
        self.assertEqual(L.unison_cents(8, 2), [-4.0, 4.0])
        self.assertEqual(L.unison_cents(7, 3), [-3.5, 0.0, 3.5])
        self.assertAlmostEqual(L.glide_seconds(7), 0.0581, delta=0.001)
        self.assertEqual(L.glide_seconds(0), 0.0)

    def test_sources_et_cables(self):
        L = self.laws
        self.assertEqual(float(L.velocity_source(64)), 0.0)
        self.assertEqual(float(L.note_source(64)), 0.0)
        self.assertEqual(float(L.envelope_source(0.0)), -1.0)
        # Un câble lu sans polarité est bipolaire ; « unipolar » ramène la
        # source dans 0..1, l'aftertouch reste unipolaire.
        self.assertEqual(L.to_polarity(-1.0, "envelope2"), -1.0)
        self.assertEqual(float(L.to_polarity(-1.0, "envelope2", "unipolar")),
                         0.0)
        self.assertEqual(L.to_polarity(0.3, "aftertouch"), 0.3)
        # Vers une hauteur, la force est élevée au carré ; vers la hauteur
        # générale, multipliée par 1/√2 : un vibrato de 5 vaut ±0,34
        # demi-ton, pas ±1,2.
        a = L.cable_strength(0x6666666)    # HARD CLOUD : lfo1 → pitch, 5
        vibrato = float(L.cable_octaves(1.0, a, "pitch", "lfo1")) * 12
        self.assertAlmostEqual(vibrato, 0.34, delta=0.01)
        self.assertAlmostEqual(float(L.cable_octaves(1.0, 0.5,
                                                     "lpfFrequency")), 4.0)
        self.assertAlmostEqual(float(L.cable_factor(1.0, 0.5)), 1.5)

    def test_courbes_exactes_des_tables(self):
        """``decayTableSmall4`` et ``decayTableSmall8`` ont une forme
        exacte : quelques valeurs du firmware (sur 65535)."""
        L = self.laws
        for x, attendu in ((0.125, 45061), (0.25, 30583), (0.5, 13107),
                           (0.75, 4369)):
            self.assertAlmostEqual(float(1 - L.attack_curve(x)) * 65535,
                                   attendu, delta=1.5)
        for x, attendu in ((0.125, 32639), (0.25, 16191), (0.5, 3855),
                           (0.75, 771)):
            self.assertAlmostEqual(float(L.decay_curve(x)) * 65535, attendu,
                                   delta=1.5)


class TestEcouteFidele(unittest.TestCase):
    """Le moteur d'écoute applique les lois du firmware, et ce qu'elles
    changent s'entend."""

    SR = 22050

    def _son(self, cables=(), **reglages):
        from delugeapp.core.fixedpoint import from_display
        from delugeapp.core.model import PatchCable

        sound = SynthPreset.new("FIDELE").sound
        sound.osc1.type = "saw"
        sound.osc2.type = "saw"
        sound.unison_num = 1
        defaut = {"oscAVolume": 45, "oscBVolume": 0, "volume": 40,
                  "lpfFrequency": 50, "lpfResonance": 0}
        defaut.update(reglages)
        for cle, valeur in defaut.items():
            sound.set_param(cle, from_display(valeur, scale=50))
        sound.patch_cables = [
            PatchCable(src, dst, PatchCable.amount_from_display(force),
                       polarity=pol)
            for src, dst, force, pol in cables]
        return sound

    def _hauteur(self, mono, t0, t1, attendu):
        seg = mono[int(t0 * self.SR):int(t1 * self.SR)]
        ac = np.correlate(seg, seg, "full")[seg.size - 1:]
        lo = int(self.SR / (attendu * 1.3))
        hi = int(self.SR / (attendu / 1.3))
        return self.SR / (lo + int(np.argmax(ac[lo:hi])))

    def test_random_vers_la_hauteur_ne_tangue_pas(self):
        """*random* est tiré une fois par note : la hauteur ne bouge pas
        pendant la note. L'ancien rendu la faisait dériver à 3 Hz."""
        son = self._son([("random", "oscAPitch", 8, "")])
        mono = render.render_sound(son, note=57, seconds=1.2,
                                   sr=self.SR).mean(axis=1)
        debut = self._hauteur(mono, 0.1, 0.3, 220.0)
        fin = self._hauteur(mono, 0.8, 1.0, 220.0)
        self.assertAlmostEqual(debut, fin, delta=debut * 0.004)

    def test_une_enveloppe_bipolaire_referme_le_filtre(self):
        """Câble sans polarité : l'enveloppe 2 vaut −1 à son palier nul, et
        tire la coupure **sous** son réglage. Unipolaire, elle n'ajoute
        rien au palier."""
        from delugeapp.core.fixedpoint import from_display

        def niveau_tenu(polarite):
            son = self._son([("envelope2", "lpfFrequency", 25, polarite)],
                            lpfFrequency=30)
            son.env2.attack = from_display(0, scale=50)
            son.env2.decay = from_display(5, scale=50)
            son.env2.sustain = from_display(0, scale=50)
            mono = render.render_sound(son, note=57, seconds=1.2,
                                       sr=self.SR, gate=0.9).mean(axis=1)
            seg = mono[int(0.7 * self.SR):int(1.0 * self.SR)]
            return 20 * np.log10(np.sqrt(np.mean(seg ** 2)) + 1e-12)

        self.assertLess(niveau_tenu(""), niveau_tenu("unipolar") - 10)

    def test_le_panoramique_est_centre_au_reglage_25(self):
        son = self._son(pan=25)
        audio = render.render_sound(son, note=57, seconds=0.5, sr=self.SR)
        gauche = float(np.sqrt(np.mean(audio[:, 0] ** 2)))
        droite = float(np.sqrt(np.mean(audio[:, 1] ** 2)))
        self.assertAlmostEqual(gauche, droite, delta=gauche * 0.01)

    def test_la_velocite_n_agit_que_par_son_cable(self):
        sans = self._son()
        avec = self._son([("velocity", "volume", 50, "")])
        def crete(son, v):
            return float(np.max(np.abs(render.render_sound(
                son, note=57, seconds=0.4, sr=self.SR, velocity=v))))
        self.assertAlmostEqual(crete(sans, 0.3), crete(sans, 1.0),
                               delta=crete(sans, 1.0) * 0.02)
        self.assertLess(crete(avec, 0.3), crete(avec, 1.0) * 0.5)

    def test_une_basse_mono_glisse_et_coupe_sa_note(self):
        """Mono, glissé 20 : la seconde note part de la première et la
        coupe ; sans glissé, elle part juste."""
        from delugeapp.core.accomp import NoteEvent
        from delugeapp.core.fixedpoint import from_display

        son = self._son()
        son.polyphonic = "mono"
        son.set_param("portamento", from_display(20, scale=50))
        partie = [NoteEvent(0, 4, 45, 100), NoteEvent(4, 4, 57, 100)]
        audio = render.render_parts({"Basse": partie}, {"Basse": son},
                                    bpm=120, sr=self.SR).mean(axis=1)
        depart = 0.5   # la seconde note, à la double-croche 4
        tot = self._hauteur(audio, depart + 0.005, depart + 0.04, 165.0)
        tard = self._hauteur(audio, depart + 0.35, depart + 0.45, 220.0)
        self.assertLess(tot, 200.0, "la note ne glisse pas")
        self.assertAlmostEqual(tard, 220.0, delta=3.0)

    def test_la_polarite_d_un_cable_se_lit_et_s_ecrit(self):
        import xml.etree.ElementTree as ET

        from delugeapp.core.model import PatchCable

        el = ET.fromstring('<patchCable source="envelope2" '
                           'destination="lpfFrequency" amount="0x20000000" '
                           'polarity="unipolar" />')
        cable = PatchCable.from_xml(el)
        self.assertEqual(cable.polarity, "unipolar")
        sortie = ET.Element("patchCable")
        cable.to_xml(sortie)
        self.assertEqual(sortie.get("polarity"), "unipolar")
        sans = ET.Element("patchCable")
        PatchCable("lfo1", "pitch", 1).to_xml(sans)
        self.assertIsNone(sans.get("polarity"))

    @staticmethod
    def _rms(audio):
        return float(np.sqrt(np.mean(np.asarray(audio, dtype=np.float64) ** 2)))

    def test_le_volume_du_preset_agit_apres_la_saturation(self):
        """Le ``volume`` d'un preset règle le volume **post-effets** du son
        (``Sound::readParamTagFromFile``) : il ne pousse pas la saturation.
        De 15 à 30, le niveau monte exactement de 12 dB, saturation
        comprise — l'ancien moteur le traitait comme le volume de la voix."""
        bas = self._son(volume=15)
        haut = self._son(volume=30)
        bas.clipping_amount = haut.clipping_amount = 5
        a = render.render_sound(bas, note=45, seconds=0.6, sr=self.SR)
        b = render.render_sound(haut, note=45, seconds=0.6, sr=self.SR)
        self.assertAlmostEqual(self._rms(b) / self._rms(a), 4.0, delta=0.02)

    def test_l_unisson_est_compense_avant_le_filtre(self):
        """Chaque voix d'unisson est réduite de ``1/√n`` : quatre voix
        désaccordées sonnent aussi fort qu'une. L'ancien moteur divisait par
        ``n`` et perdait 6 dB."""
        une = self._son()
        quatre = self._son()
        quatre.unison_num = 4
        quatre.unison_detune = 10
        for note in (45, 57):
            with self.subTest(note=note):
                a = render.render_sound(une, note=note, seconds=1.0,
                                        sr=self.SR)
                b = render.render_sound(quatre, note=note, seconds=1.0,
                                        sr=self.SR)
                self.assertAlmostEqual(self._rms(b) / self._rms(a), 1.0,
                                       delta=0.2)

    def test_le_bruit_vaut_deux_dents_de_scie(self):
        """Au même réglage, le bruit blanc uniforme du firmware sort deux
        fois plus fort qu'une dent de scie (``noiseVolume >> 1``, puis le
        gain des filtres ``<< 4``, puis ``>> 2``) ; l'ancien bruit, gaussien,
        était 7 dB trop bas.

        Mesuré dans la voix : à la sortie, la saturation adoucie du
        compresseur maître moyenne deux échantillons (vérifié sur la machine
        le 4 novembre 2026), ce qui ôte la moitié de la puissance d'un bruit
        blanc et presque rien d'une dent de scie grave — 2 × √½."""
        bruit = self._son(oscAVolume=0, noiseVolume=40)
        scie = self._son(oscAVolume=40)
        voix = [render.render_sound(s, note=48, seconds=0.6, sr=44100,
                                    effects=False) for s in (bruit, scie)]
        self.assertAlmostEqual(self._rms(voix[0]) / self._rms(voix[1]), 2.0,
                               delta=0.06)
        sortie = [render.render_sound(s, note=48, seconds=0.6, sr=44100)
                  for s in (bruit, scie)]
        self.assertAlmostEqual(self._rms(sortie[0]) / self._rms(sortie[1]),
                               2.0 * 0.5 ** 0.5, delta=0.06)

    def test_un_vieux_preset_fm_n_a_pas_de_filtre(self):
        """Un son FM venu d'un firmware antérieur au communautaire 1.2.0
        garde son mode de filtre dans le fichier, mais la machine l'éteint
        (``Sound::readFromFile``) ; un son FM récent, lui, est filtré."""
        from delugeapp.core.fixedpoint import from_display

        def niveau(firmware, filtre):
            son = self._son(lpfFrequency=10)
            son.mode = "fm"
            son.firmware = firmware
            son.set_param("modulator1Amount", from_display(30, scale=50))
            if not filtre:
                son.lpf_mode = son.hpf_mode = "off"
            return self._rms(render.render_sound(son, note=57, seconds=0.5,
                                                 sr=self.SR))

        self.assertAlmostEqual(niveau("3.0.4", True) / niveau("3.0.4", False),
                               1.0, places=3)
        self.assertLess(niveau("c1.3.0", True) / niveau("c1.3.0", False), 0.6)

    def test_les_effets_appliques_a_part_redonnent_le_meme_son(self):
        """``sound_effects`` sur la voix seule (``effects=False``) redonne
        le rendu complet : c'est le chemin des sons entiers, voix
        additionnées. Seuls diffèrent les 5 ms du fondu final."""
        from delugeapp.core.fixedpoint import from_display

        son = self._son(reverbAmount=30, delayFeedback=20)
        son.mod_fx_type = "chorus"
        son.set_param("modFXDepth", from_display(30, scale=50))
        # À la fréquence de l'application : à 22 kHz, l'aller-retour du
        # rééchantillonnage coûterait 1,4 % de niveau.
        sr = 44100
        entier = render.render_sound(son, note=57, seconds=1.5, sr=sr)
        voix = render.render_sound(son, note=57, seconds=1.5, sr=sr,
                                   effects=False)
        apart = render.sound_effects(son, voix, sr=sr)
        utile = slice(0, entier.shape[0] - int(0.02 * sr))
        a = entier[utile].ravel()
        b = apart[utile].ravel()
        self.assertAlmostEqual(self._rms(b) / self._rms(a), 1.0, delta=0.001)
        self.assertGreater(float(np.corrcoef(a, b)[0, 1]), 0.9999)

    def test_la_reverberation_d_un_morceau_neuf(self):
        """L'écoute envoie le son vers la réverbération d'un morceau neuf
        du firmware 1.3 (« Mutable ») : une queue après la note, que le même
        son sans envoi n'a pas."""
        avec = self._son(reverbAmount=30)
        sans = self._son()
        queue = slice(int(1.5 * self.SR), int(1.9 * self.SR))
        a = render.render_sound(avec, note=57, seconds=2.0, sr=self.SR,
                                gate=0.3)
        b = render.render_sound(sans, note=57, seconds=2.0, sr=self.SR,
                                gate=0.3)
        self.assertGreater(self._rms(a[queue]), 1e-3)
        self.assertLess(self._rms(b[queue]), 1e-6)


class TestSampleFix(unittest.TestCase):
    """Correction des défauts audio : mono, continu, écrêtage, fréquence.

    Tous les tests travaillent sur une carte jetable, et plusieurs comparent
    les fichiers **à l'octet** avant et après : c'est la seule façon de
    prouver qu'une simulation ne touche à rien et qu'une restauration rend
    bien l'original.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.root = base / "carte"
        for sub in ("SONGS", "SYNTHS", "KITS", "SAMPLES/DRUMS/Kick",
                    "SAMPLES/DRUMS/Snare", "SAMPLES/MULTISAMPLES"):
            (self.root / sub).mkdir(parents=True)

        t = np.linspace(0, 0.4, 17640, endpoint=False, dtype=np.float32)

        # Une percussion stéréo : deux canaux légèrement désaccordés.
        stereo = np.stack(
            [0.6 * np.sin(2 * np.pi * 70 * t) * np.exp(-t * 9),
             0.6 * np.sin(2 * np.pi * 71 * t) * np.exp(-t * 9)], axis=1)
        wav.write(self.root / "SAMPLES/DRUMS/Kick/stereo.wav",
                  stereo.astype(np.float32), 44100)

        # Un fichier à 32 kHz, hors des fréquences lues directement.
        wav.write(self.root / "SAMPLES/DRUMS/Snare/32k.wav",
                  (0.4 * np.random.default_rng(3).standard_normal(12800)
                   ).astype(np.float32), 32000)

        # Une composante continue franche.
        wav.write(self.root / "SAMPLES/DRUMS/Kick/continu.wav",
                  (0.3 * np.sin(2 * np.pi * 90 * t) + 0.08
                   ).astype(np.float32), 44100)

        # Un fichier déjà à pleine échelle **et** décalé : recentrer un tel
        # signal l'écrête, c'est le cas qui a motivé le garde-fou.
        chaud = 0.92 * np.sin(2 * np.pi * 110 * t) + 0.079
        wav.write(self.root / "SAMPLES/DRUMS/Kick/chaud.wav",
                  np.clip(chaud, -1.0, 1.0).astype(np.float32), 44100)

        # Un fichier mono ordinaire, qui ne doit jamais être touché.
        wav.write(self.root / "SAMPLES/MULTISAMPLES/mono.wav",
                  (0.5 * np.sin(2 * np.pi * 220 * t)).astype(np.float32),
                  44100)

        self.sd = sdcard.SDCard(self.root)
        self.lib = db.Library(base / "index.db")
        scan.scan_card(self.sd, self.lib, compute_hash=True, analyze=True)

    def tearDown(self):
        self.lib.close()
        self._tmp.cleanup()

    # -- utilitaires -------------------------------------------------------- #

    def _sha(self, rel: str) -> str:
        return hashlib.sha256((self.root / rel).read_bytes()).hexdigest()

    def _empreintes(self) -> dict:
        return {self.sd.rel(p): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.root.rglob("*")
                if p.is_file() and p.suffix.lower() == ".wav"}

    def _preset_borne(self, nom: str, rel: str, frames: int,
                      unit: str = "samples"):
        """Un preset qui borne ``rel`` en trames (ou en millisecondes)."""
        from delugeapp.core.model import Zone

        preset = SynthPreset.new(nom)
        preset.sound.osc1.type = "sample"
        preset.sound.osc1.file_name = rel
        preset.sound.osc1.zone = Zone(start=100, end=frames, unit=unit,
                                      start_loop=200, end_loop=frames - 50)
        preset.save(self.root / "SYNTHS" / f"{nom}.XML", backup=False)
        return self.root / "SYNTHS" / f"{nom}.XML"

    def _song(self, nom: str, rel: str) -> None:
        """Un morceau qui cite un échantillon, bornes en trames."""
        (self.root / "SONGS" / nom).write_bytes(
            b'<song firmwareVersion="3.0.4" timePerTimerTick="459"'
            b' timerTickFraction="1610612736" inputTickMagnitude="1">'
            b'<instruments><sound presetName="X"><osc1 type="sample"'
            b' fileName="' + rel.encode("utf-8") +
            b'"><zone startSamplePos="0" endSamplePos="1000"/>'
            b'</osc1></sound></instruments></song>')

    # -- sélection ---------------------------------------------------------- #

    def test_plan_mono_ne_vise_que_les_percussions_stereo(self):
        plan = samplefix.plan_mono(self.sd, self.lib)
        rels = [e.rel for e in plan.edits]
        self.assertEqual(len(rels), 1)
        self.assertTrue(rels[0].endswith("stereo.wav"))

    def test_plan_mono_ignore_la_stereo_hors_de_drums(self):
        """Le critère est celui du diagnostic : sous ``SAMPLES/DRUMS/`` seul."""
        t = np.linspace(0, 0.2, 8820, endpoint=False, dtype=np.float32)
        ailleurs = np.stack([0.4 * np.sin(2 * np.pi * 200 * t)] * 2, axis=1)
        wav.write(self.root / "SAMPLES/MULTISAMPLES/st.wav",
                  ailleurs.astype(np.float32), 44100)
        scan.scan_card(self.sd, self.lib, compute_hash=True)

        plan = samplefix.plan_mono(self.sd, self.lib)
        self.assertNotIn("SAMPLES/MULTISAMPLES/st.wav",
                         [e.rel for e in plan.edits])
        # Explicitement demandé, en revanche, il est traité.
        force = samplefix.plan_mono(
            self.sd, self.lib, rels=["SAMPLES/MULTISAMPLES/st.wav"])
        self.assertEqual(len(force.edits), 1)

    def test_les_seuils_viennent_de_health(self):
        """Dupliquer les seuils ferait diverger plan et diagnostic."""
        self.assertEqual(samplefix.DC_THRESHOLD, health.DC_OFFSET_LIMIT)
        self.assertEqual(samplefix.CLIP_THRESHOLD, health.CLIPPED_RATIO)
        self.assertEqual(samplefix.STANDARD_RATES, health.GOOD_SAMPLE_RATES)

    def test_le_plan_correspond_au_diagnostic(self):
        """Autant de fichiers dans le plan que la page Santé en signale."""
        report = health.check_card(self.sd, self.lib)
        compte = {i.code: i.count for i in report.issues}
        for code, builder in (
                ("STEREO_DRUM", samplefix.plan_mono),
                ("ODD_SAMPLE_RATE", samplefix.plan_standard_rate),
                ("DC_OFFSET", samplefix.plan_remove_dc),
                ("CLIPPED_SAMPLE", samplefix.plan_headroom)):
            with self.subTest(code=code):
                plan = builder(self.sd, self.lib)
                self.assertEqual(len(plan.edits) + len(plan.skipped),
                                 compte.get(code, 0))

    # -- simulation contre application -------------------------------------- #

    def test_simulate_ne_touche_a_rien(self):
        avant = self._empreintes()
        plan = samplefix.plan_from_health(
            self.sd, self.lib, list(samplefix.HEALTH_CODES))
        result = plan.simulate(self.sd, self.lib)
        self.assertFalse(result.applied)
        self.assertTrue(result.done)
        self.assertEqual(self._empreintes(), avant)
        self.assertFalse((self.root / samplefix.BACKUP_ROOT).exists())

    def test_apply_ecrit_vraiment(self):
        """``apply()`` applique : c'est la différence avec ``simulate()``."""
        avant = self._sha("SAMPLES/DRUMS/Kick/stereo.wav")
        plan = samplefix.plan_mono(self.sd, self.lib)
        result = plan.apply(self.sd, self.lib)
        self.assertTrue(result.applied)
        self.assertNotEqual(self._sha("SAMPLES/DRUMS/Kick/stereo.wav"), avant)

    # -- mono --------------------------------------------------------------- #

    def test_mono_conserve_la_longueur_et_divise_la_taille(self):
        rel = "SAMPLES/DRUMS/Kick/stereo.wav"
        avant = wav.probe(self.root / rel)
        taille = (self.root / rel).stat().st_size

        result = samplefix.plan_mono(self.sd, self.lib).apply(self.sd, self.lib)
        apres = wav.probe(self.root / rel)

        self.assertEqual(apres.channels, 1)
        self.assertEqual(apres.frames, avant.frames,
                         "le nombre de trames ne doit pas changer")
        self.assertLess((self.root / rel).stat().st_size, taille * 0.6)
        self.assertEqual(result.zones_moved, 0)
        self.assertGreater(result.bytes_saved, 0)

    def test_mono_met_l_index_a_jour(self):
        samplefix.plan_mono(self.sd, self.lib).apply(self.sd, self.lib)
        row = self.lib.get("sample", "SAMPLES/DRUMS/Kick/stereo.wav")
        self.assertIsNotNone(row)
        self.assertEqual(row["channels"], 1)
        report = health.check_card(self.sd, self.lib)
        self.assertNotIn("STEREO_DRUM", {i.code for i in report.issues})

    # -- sauvegarde et restauration ----------------------------------------- #

    def test_la_sauvegarde_suit_l_arborescence_de_la_carte(self):
        """Pas de chemin absolu enterré sous ``_BACKUP/``."""
        empreintes = self._empreintes()
        result = samplefix.plan_mono(self.sd, self.lib).apply(self.sd, self.lib)
        base = self.sd.abs(result.backup_dir)

        for rel in result.done:
            with self.subTest(fichier=rel):
                copie = base / rel
                self.assertTrue(copie.is_file(),
                                f"original attendu en {copie}")
                self.assertEqual(
                    hashlib.sha256(copie.read_bytes()).hexdigest(),
                    empreintes[rel])

        dehors = [p for p in base.rglob("*") if p.is_file()
                  and not str(p.relative_to(base)).replace("\\", "/")
                  .upper().startswith("SAMPLES/")]
        self.assertEqual(dehors, [])

    def test_restore_rend_l_original_a_l_octet(self):
        empreintes = self._empreintes()
        result = samplefix.plan_mono(self.sd, self.lib).apply(self.sd, self.lib)
        modifies = [rel for rel in result.done
                    if self._sha(rel) != empreintes[rel]]
        self.assertTrue(modifies)

        nb, erreurs = samplefix.restore(self.sd, result.backup_dir,
                                        self.lib, apply=False)
        self.assertEqual(nb, len(result.done))
        self.assertEqual(
            [rel for rel in modifies if self._sha(rel) != empreintes[rel]],
            modifies, "la simulation de restauration a écrit")

        nb, erreurs = samplefix.restore(self.sd, result.backup_dir,
                                        self.lib, apply=True)
        self.assertEqual(erreurs, [])
        for rel in modifies:
            with self.subTest(fichier=rel):
                self.assertEqual(self._sha(rel), empreintes[rel])

        # Rien ne doit avoir été créé hors des dossiers de la carte.
        racines = {p.relative_to(self.root).parts[0].upper()
                   for p in self.root.rglob("*") if p.is_file()}
        self.assertTrue(racines <= {"SAMPLES", "SYNTHS", "KITS", "SONGS",
                                    samplefix.BACKUP_ROOT}, racines)

    def test_deux_executions_ont_deux_sauvegardes(self):
        r1 = samplefix.plan_mono(self.sd, self.lib).apply(self.sd, self.lib)
        r2 = samplefix.plan_remove_dc(self.sd, self.lib).apply(self.sd,
                                                               self.lib)
        self.assertTrue(r1.backup_dir)
        self.assertNotEqual(r1.backup_dir, r2.backup_dir)

    def test_restore_d_une_sauvegarde_absente(self):
        nb, erreurs = samplefix.restore(self.sd, "_BACKUP/inexistant",
                                        self.lib, apply=True)
        self.assertEqual(nb, 0)
        self.assertTrue(erreurs)

    # -- composante continue ------------------------------------------------ #

    def test_retrait_du_continu(self):
        rel = "SAMPLES/DRUMS/Kick/continu.wav"
        plan = samplefix.plan_remove_dc(self.sd, self.lib)
        self.assertIn(rel, [e.rel for e in plan.edits])
        plan.apply(self.sd, self.lib)

        data, _ = wav.read(self.root / rel)
        self.assertLess(abs(analysis.loudness(data)["dc_offset"]),
                        samplefix.DC_THRESHOLD)

    def test_le_retrait_du_continu_ne_cree_pas_d_ecretage(self):
        """Recentrer un signal déjà à pleine échelle doit l'atténuer.

        Sans garde-fou, ``wav.convert`` rabotait les sommets : le fichier
        sortait recentré **et** écrêté, et le diagnostic empirait.
        """
        rel = "SAMPLES/DRUMS/Kick/chaud.wav"
        plan = samplefix.plan_remove_dc(self.sd, self.lib, rels=[rel])
        edit = plan.edits[0]
        self.assertIn("normalize", edit.actions,
                      "une baisse de niveau devait accompagner le retrait")
        plan.apply(self.sd, self.lib)

        data, _ = wav.read(self.root / rel)
        niveaux = analysis.loudness(data)
        self.assertLess(abs(niveaux["dc_offset"]), samplefix.DC_THRESHOLD)
        self.assertLessEqual(niveaux["clipped"], samplefix.CLIP_THRESHOLD)

    def test_marge_rendue_aux_fichiers_ecretes(self):
        rel = "SAMPLES/DRUMS/Kick/chaud.wav"
        samplefix.plan_headroom(self.sd, self.lib, rels=[rel],
                                target_db=-3.0).apply(self.sd, self.lib)
        data, _ = wav.read(self.root / rel)
        crete = 20.0 * np.log10(max(float(np.max(np.abs(data))), 1e-9))
        self.assertAlmostEqual(crete, -3.0, delta=0.2)

    # -- rééchantillonnage et bornes ---------------------------------------- #

    def test_reechantillonnage_recale_les_bornes_en_trames(self):
        rel = "SAMPLES/DRUMS/Snare/32k.wav"
        frames = wav.probe(self.root / rel).frames
        chemin = self._preset_borne("BORNES", rel, frames)

        result = samplefix.plan_standard_rate(
            self.sd, self.lib, rels=[rel]).apply(self.sd, self.lib)
        ratio = 44100 / 32000.0

        apres = wav.probe(self.root / rel)
        self.assertEqual(apres.sample_rate, 44100)
        self.assertAlmostEqual(apres.frames / frames, ratio, delta=0.01)

        zone = SynthPreset.load(chemin).sound.osc1.zone
        self.assertEqual(zone.start, round(100 * ratio))
        self.assertEqual(zone.end, round(frames * ratio))
        self.assertEqual(zone.start_loop, round(200 * ratio))
        self.assertEqual(zone.end_loop, round((frames - 50) * ratio))
        self.assertIn("SYNTHS/BORNES.XML", result.retargeted)
        self.assertGreaterEqual(result.zones_moved, 4)

    def test_les_bornes_en_millisecondes_ne_bougent_pas(self):
        """Une durée en millisecondes survit à un rééchantillonnage."""
        rel = "SAMPLES/DRUMS/Snare/32k.wav"
        frames = wav.probe(self.root / rel).frames
        chemin = self._preset_borne("MS", rel, frames, unit="ms")

        samplefix.plan_standard_rate(
            self.sd, self.lib, rels=[rel]).apply(self.sd, self.lib)

        zone = SynthPreset.load(chemin).sound.osc1.zone
        self.assertEqual(zone.unit, "ms")
        self.assertEqual(zone.start, 100)
        self.assertEqual(zone.end, frames)

    def test_les_kits_sont_recales_aussi(self):
        rel = "SAMPLES/DRUMS/Snare/32k.wav"
        frames = wav.probe(self.root / rel).frames
        from delugeapp.core.model import Zone

        kit = Kit.new("KR")
        kit.add_row("SNARE", rel)
        kit.rows[0].sound.osc1.zone = Zone(start=0, end=frames,
                                           unit="samples")
        kit.save(self.root / "KITS" / "KR.XML", backup=False)

        result = samplefix.plan_standard_rate(
            self.sd, self.lib, rels=[rel]).apply(self.sd, self.lib)
        self.assertIn("KITS/KR.XML", result.retargeted)

        relu = Kit.load(self.root / "KITS" / "KR.XML")
        self.assertEqual(relu.rows[0].sound.osc1.zone.end,
                         round(frames * 44100 / 32000.0))

    def test_le_recalage_laisse_un_bak(self):
        rel = "SAMPLES/DRUMS/Snare/32k.wav"
        frames = wav.probe(self.root / rel).frames
        self._preset_borne("BAK", rel, frames)
        samplefix.plan_standard_rate(
            self.sd, self.lib, rels=[rel]).apply(self.sd, self.lib)
        self.assertTrue(list((self.root / "SYNTHS").glob("BAK*.bak")),
                        "aucune sauvegarde du preset recalé")

    def test_retarget_zones_sans_ratio_ne_fait_rien(self):
        moved, files = samplefix.retarget_zones(self.sd, {}, apply=True)
        self.assertEqual((moved, files), (0, []))

    def test_retarget_zones_en_simulation_n_ecrit_pas(self):
        rel = "SAMPLES/DRUMS/Snare/32k.wav"
        frames = wav.probe(self.root / rel).frames
        chemin = self._preset_borne("SIM", rel, frames)
        avant = chemin.read_bytes()

        moved, files = samplefix.retarget_zones(
            self.sd, {sdcard.norm_rel(rel): 0.5}, apply=False)
        self.assertGreater(moved, 0)
        self.assertEqual(chemin.read_bytes(), avant)

    # -- protection des morceaux -------------------------------------------- #

    def test_un_echantillon_cite_par_un_morceau_est_ecarte(self):
        """Un morceau borne en trames et n'est jamais réécrit (SPEC §0)."""
        rel = "SAMPLES/DRUMS/Snare/32k.wav"
        self._song("M.XML", rel)

        verrous = samplefix.song_locked_samples(self.sd)
        self.assertIn(sdcard.norm_rel(rel), verrous)

        plan = samplefix.plan_standard_rate(self.sd, self.lib, rels=[rel])
        self.assertEqual(plan.edits, [])
        self.assertEqual(len(plan.skipped), 1)
        self.assertIn("morceau", plan.skipped[0].skipped)

    def test_le_mono_reste_permis_sur_un_echantillon_de_morceau(self):
        """Le mono garde la longueur : aucune borne ne se décale."""
        rel = "SAMPLES/DRUMS/Kick/stereo.wav"
        self._song("M.XML", rel)
        plan = samplefix.plan_custom(self.sd, self.lib, [rel], mono=True)
        self.assertEqual(len(plan.edits), 1)
        self.assertEqual(plan.skipped, [])

    # -- plans composés ----------------------------------------------------- #

    def test_plan_from_health_fusionne_deux_defauts_d_un_fichier(self):
        """Un fichier à la fois écrêté et décalé n'est réécrit qu'une fois."""
        plan = samplefix.plan_from_health(
            self.sd, self.lib, ["DC_OFFSET", "CLIPPED_SAMPLE"])
        rels = [e.rel for e in plan.edits]
        self.assertEqual(len(rels), len(set(rels)), "doublon dans le plan")
        chaud = next((e for e in plan.edits
                      if e.rel.endswith("chaud.wav")), None)
        self.assertIsNotNone(chaud)
        self.assertIn("dc", chaud.actions)
        self.assertIn("normalize", chaud.actions)

    def test_plan_from_health_ignore_les_codes_inconnus(self):
        plan = samplefix.plan_from_health(self.sd, self.lib,
                                          ["PAS_UN_CODE", "MAC_JUNK"])
        self.assertEqual(len(plan.edits), 0)

    def test_plan_custom_ecarte_ce_qui_est_deja_mono(self):
        rel = "SAMPLES/MULTISAMPLES/mono.wav"
        plan = samplefix.plan_custom(self.sd, self.lib, [rel], mono=True)
        self.assertEqual(plan.edits, [])
        self.assertEqual(plan.skipped[0].skipped, "déjà en mono")

    def test_plan_custom_sans_traitement_est_vide(self):
        plan = samplefix.plan_custom(self.sd, self.lib,
                                     ["SAMPLES/MULTISAMPLES/mono.wav"])
        self.assertFalse(plan)
        self.assertEqual(plan.summary(), "Rien à corriger.")

    def test_plan_custom_fondus(self):
        rel = "SAMPLES/MULTISAMPLES/mono.wav"
        frames = wav.probe(self.root / rel).frames
        samplefix.plan_custom(self.sd, self.lib, [rel],
                              fade_ms=10.0).apply(self.sd, self.lib)
        data, _ = wav.read(self.root / rel)
        self.assertEqual(data.shape[0], frames, "le fondu change la longueur")
        self.assertLess(abs(float(data.flat[0])), 0.01)
        self.assertLess(abs(float(data.flat[-1])), 0.01)

    def test_coupe_du_silence_change_la_longueur(self):
        rel = "SAMPLES/MULTISAMPLES/silence.wav"
        t = np.linspace(0, 0.2, 8820, endpoint=False, dtype=np.float32)
        signal = np.concatenate([
            np.zeros(4410, dtype=np.float32),
            (0.5 * np.sin(2 * np.pi * 220 * t)).astype(np.float32),
            np.zeros(4410, dtype=np.float32)])
        wav.write(self.root / rel, signal, 44100)
        scan.scan_card(self.sd, self.lib, compute_hash=True)

        plan = samplefix.plan_custom(self.sd, self.lib, [rel], trim_db=-60.0)
        self.assertTrue(plan.changes_length)
        plan.apply(self.sd, self.lib)
        self.assertLess(wav.probe(self.root / rel).frames, signal.size)

    # -- rapports ----------------------------------------------------------- #

    def test_le_detail_cite_chaque_fichier(self):
        plan = samplefix.plan_from_health(
            self.sd, self.lib, list(samplefix.HEALTH_CODES))
        texte = plan.to_text()
        for edit in plan.edits:
            self.assertIn(edit.rel, texte)
        self.assertIn("fichier(s)", plan.summary())

    def test_le_libelle_dit_ce_qui_change(self):
        plan = samplefix.plan_mono(self.sd, self.lib)
        self.assertIn("mono", plan.edits[0].label)
        plan = samplefix.plan_standard_rate(self.sd, self.lib)
        self.assertIn("Hz", plan.edits[0].label)

    def test_plan_vide(self):
        plan = samplefix.FixPlan()
        self.assertFalse(plan)
        self.assertEqual(len(plan), 0)
        result = plan.apply(self.sd, self.lib)
        self.assertEqual(result.done, [])

    def test_fichier_disparu_pendant_l_application(self):
        """Une correction qui échoue n'interrompt pas les autres."""
        plan = samplefix.plan_from_health(
            self.sd, self.lib, list(samplefix.HEALTH_CODES))
        self.assertGreater(len(plan.edits), 1)
        plan.edits.insert(0, samplefix.Edit(rel="SAMPLES/DRUMS/Kick/parti.wav",
                                            actions={"mono": True}))
        result = plan.apply(self.sd, self.lib)
        self.assertEqual(len(result.failed), 1)
        self.assertIn("introuvable", result.failed[0][1])
        self.assertTrue(result.done, "le reste du plan devait s'appliquer")

    def test_interruption(self):
        """``should_stop`` arrête le plan sans abîmer ce qui reste."""
        plan = samplefix.plan_from_health(
            self.sd, self.lib, list(samplefix.HEALTH_CODES))
        result = plan.apply(self.sd, self.lib, should_stop=lambda: True)
        self.assertEqual(result.done, [])

    def test_progression(self):
        vus: list = []
        samplefix.plan_mono(self.sd, self.lib).apply(
            self.sd, self.lib, progress=vus.append)
        self.assertTrue(vus)
        self.assertEqual(len(vus[0]), 3)


class TestWavRemoveDC(unittest.TestCase):
    """Le retrait de composante continue, ajouté à ``wav.convert``."""

    def test_remove_dc_recentre(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            base = Path(tmp.name)
            t = np.linspace(0, 0.2, 8820, endpoint=False, dtype=np.float32)
            signal = (0.4 * np.sin(2 * np.pi * 150 * t) + 0.12
                      ).astype(np.float32)
            wav.write(base / "a.wav", signal, 44100)

            info = wav.convert(base / "a.wav", base / "b.wav",
                               remove_dc=True)
            self.assertTrue(info.ok)
            data, _ = wav.read(base / "b.wav")
            self.assertLess(abs(float(np.mean(data))), 1e-3)
            self.assertEqual(data.shape[0], signal.size)
        finally:
            tmp.cleanup()

    def test_remove_dc_par_canal(self):
        """Chaque canal est recentré séparément."""
        a = np.stack([np.full(1000, 0.2, dtype=np.float32),
                      np.full(1000, -0.3, dtype=np.float32)], axis=1)
        out = wav._remove_dc(a)
        self.assertAlmostEqual(float(out[:, 0].mean()), 0.0, places=5)
        self.assertAlmostEqual(float(out[:, 1].mean()), 0.0, places=5)

    def test_remove_dc_sur_un_tableau_vide(self):
        vide = np.zeros((0, 1), dtype=np.float32)
        self.assertEqual(wav._remove_dc(vide).shape, vide.shape)


class TestSlicer(unittest.TestCase):
    """Découpage d'une boucle en kit.

    Le point à ne jamais casser : **toutes les rangées pointent le même
    fichier**, avec leurs propres bornes en trames. C'est ce qui évite de
    dupliquer l'audio, et c'est un idiome vérifié sur la carte réelle.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.root = base / "carte"
        for sub in ("SONGS", "SYNTHS", "KITS", "SAMPLES/LOOPS"):
            (self.root / sub).mkdir(parents=True)

        # Une boucle de 2 s à 120 BPM : quatre temps, une attaque par temps,
        # plus deux contretemps. 88 200 trames = 16 doubles-croches.
        self.sr = 44100
        self.frames = 88200
        signal = np.zeros(self.frames, dtype=np.float32)
        pas = self.sr // 8                     # une croche à 120 BPM
        for index in range(8):
            debut = index * pas
            duree = min(pas // 2, self.frames - debut)
            t = np.arange(duree, dtype=np.float32) / self.sr
            amplitude = 0.9 if index % 2 == 0 else 0.4
            signal[debut:debut + duree] = (
                amplitude * np.sin(2 * np.pi * 180 * t)
                * np.exp(-t * 40)).astype(np.float32)
        self.rel = "SAMPLES/LOOPS/boucle.wav"
        wav.write(self.root / self.rel, signal, self.sr)

        self.sd = sdcard.SDCard(self.root)
        self.lib = db.Library(base / "index.db")
        scan.scan_card(self.sd, self.lib, compute_hash=True, analyze=True)

    def tearDown(self):
        self.lib.close()
        self._tmp.cleanup()

    # -- placement des coupes ---------------------------------------------- #

    def test_la_premiere_tranche_part_de_zero(self):
        jeu = slicer.slice_sample(self.sd, self.rel, mode="transients")
        self.assertTrue(jeu)
        self.assertEqual(jeu.slices[0].start, 0)

    def test_les_tranches_couvrent_tout_le_fichier_sans_trou(self):
        for mode in ("transients", "grid"):
            with self.subTest(mode=mode):
                jeu = slicer.slice_sample(self.sd, self.rel, mode=mode)
                self.assertEqual(jeu.slices[-1].end, jeu.frames)
                self.assertEqual(jeu.covered, jeu.frames)
                for index in range(len(jeu) - 1):
                    self.assertEqual(jeu.slices[index].end,
                                     jeu.slices[index + 1].start)

    def test_les_bornes_sont_exclusives(self):
        """Mesuré sur la carte : ``endSamplePos`` vaut le nombre de trames."""
        jeu = slicer.slice_sample(self.sd, self.rel, mode="grid", count=4)
        self.assertEqual(jeu.slices[-1].end, self.frames)
        self.assertEqual(sum(s.frames for s in jeu.slices), self.frames)

    def test_divisions_egales(self):
        jeu = slicer.slice_sample(self.sd, self.rel, mode="grid", count=8)
        self.assertEqual(len(jeu), 8)
        longueurs = {s.frames for s in jeu.slices}
        # Au plus deux longueurs : la division exacte, et le reste final.
        self.assertLessEqual(len(longueurs), 2)
        self.assertAlmostEqual(min(longueurs), self.frames // 8, delta=2)

    def test_la_grille_ignore_le_tempo(self):
        """Aligner une division déjà exacte sur un tempo *détecté* la fausse.

        Sur ``Bricky-NoKS-120.wav`` (4,0 s), l'alignement sur 120,2 BPM
        faisait sortir une tranche à 256 ms au lieu de 250.
        """
        sans = slicer.grid_slices(self.frames, self.sr, 16)
        self.assertEqual(len(sans), 16)
        self.assertEqual(sans[1] - sans[0], self.frames // 16)

    def test_le_nombre_de_tranches_est_plafonne(self):
        jeu = slicer.slice_sample(self.sd, self.rel, mode="grid", count=999)
        self.assertLessEqual(len(jeu), slicer.MAX_SLICES)

    def test_les_tranches_trop_courtes_sont_fondues(self):
        """Une tranche de 2 ms ne produit qu'un clic : elle est absorbée."""
        positions = [0, 10, 20, 30, 44100]
        jeu = slicer.slice_sample(self.sd, self.rel, mode="manual",
                                  positions=positions)
        mini = slicer.MIN_SLICE_MS * self.sr / 1000.0
        for tranche in jeu.slices:
            self.assertGreaterEqual(tranche.frames, mini * 0.999)
        self.assertLess(len(jeu), len(positions))

    def test_positions_manuelles_desordonnees(self):
        jeu = slicer.slice_sample(
            self.sd, self.rel, mode="manual",
            positions=[30000, 0, 10000, 10000, -50, 10 ** 9])
        starts = [s.start for s in jeu.slices]
        self.assertEqual(starts, sorted(starts))
        self.assertEqual(len(starts), len(set(starts)))
        self.assertEqual(starts[0], 0)
        self.assertLessEqual(max(s.end for s in jeu.slices), self.frames)

    def test_quantize_aligne_sur_la_grille(self):
        jeu = slicer.slice_sample(self.sd, self.rel, mode="manual",
                                  positions=[0, 11000, 22300, 33100])
        aligne = jeu.quantize(120.0)
        pas = self.sr * 60.0 / (120.0 * 4.0)      # une double-croche
        for tranche in aligne.slices:
            reste = tranche.start % pas
            self.assertLess(min(reste, pas - reste), 1.0)

    def test_quantize_sans_tempo_ne_change_rien(self):
        jeu = slicer.slice_sample(self.sd, self.rel, mode="grid", count=8)
        self.assertIs(jeu.quantize(0.0), jeu)

    def test_le_tempo_vient_de_l_index(self):
        """Pas besoin de ressaisir le tempo d'une boucle déjà analysée."""
        row = self.lib.get("sample", self.rel)
        attendu = float(row["bpm"] or 0.0)
        jeu = slicer.slice_sample(self.sd, self.rel, lib=self.lib)
        self.assertAlmostEqual(jeu.bpm, attendu, places=3)

    # -- du découpage au kit ----------------------------------------------- #

    def test_le_kit_ne_cite_qu_un_fichier(self):
        jeu = slicer.slice_sample(self.sd, self.rel, mode="grid", count=8)
        kit = slicer.slices_to_kit(jeu, "ESSAI")
        self.assertEqual(len(kit.rows), 8)
        self.assertEqual(len({r.file_name for r in kit.rows}), 1,
                         "un découpage ne doit dupliquer aucun fichier")

    def test_chaque_rangee_porte_ses_bornes(self):
        jeu = slicer.slice_sample(self.sd, self.rel, mode="grid", count=8)
        kit = slicer.slices_to_kit(jeu, "ESSAI")
        for index, (row, tranche) in enumerate(zip(kit.rows, jeu.slices), 1):
            with self.subTest(rangee=index):
                zone = row.sound.osc1.zone
                self.assertIsNotNone(zone)
                self.assertEqual(zone.unit, "samples")
                self.assertEqual(zone.start, tranche.start)
                self.assertEqual(zone.end, tranche.end)
                # Ce test exigeait ``loopMode`` 0 en le prenant pour « ne
                # boucle pas ». C'est CUT : la tranche s'arrêtait avec la
                # note. ONCE (1) ne boucle pas non plus, et joue la tranche
                # jusqu'au bout, comme le découpeur du Deluge.
                from delugeapp.core.model import REPEAT_LOOP, REPEAT_ONCE

                self.assertEqual(row.sound.osc1.loop_mode, REPEAT_ONCE)
                self.assertNotEqual(row.sound.osc1.loop_mode, REPEAT_LOOP)

    def test_les_bornes_survivent_a_l_aller_retour_xml(self):
        """Le test qui compte : un kit relu doit rejouer les mêmes tranches."""
        jeu = slicer.slice_sample(self.sd, self.rel, mode="grid", count=12)
        rel, _message = slicer.save_sliced_kit(self.sd, jeu, "AR", apply=True)
        self.assertTrue(rel)

        relu = Kit.load(self.root / rel)
        self.assertEqual(len(relu.rows), len(jeu))
        for index, (row, tranche) in enumerate(zip(relu.rows, jeu.slices), 1):
            with self.subTest(rangee=index):
                zone = row.sound.osc1.zone
                self.assertIsNotNone(zone, "bornes perdues à l'écriture")
                self.assertEqual((zone.start, zone.end),
                                 (tranche.start, tranche.end))

    def test_la_simulation_n_ecrit_rien(self):
        avant = {p.relative_to(self.root).as_posix()
                 for p in self.root.rglob("*") if p.is_file()}
        jeu = slicer.slice_sample(self.sd, self.rel, mode="grid", count=8)
        rel, message = slicer.save_sliced_kit(self.sd, jeu, "SIM",
                                              apply=False)
        self.assertTrue(rel)
        self.assertIn("seraient", message)
        apres = {p.relative_to(self.root).as_posix()
                 for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(avant, apres)

    def test_un_kit_existant_n_est_jamais_ecrase(self):
        jeu = slicer.slice_sample(self.sd, self.rel, mode="grid", count=4)
        premier, _ = slicer.save_sliced_kit(self.sd, jeu, "DOUBLE",
                                            apply=True)
        second, _ = slicer.save_sliced_kit(self.sd, jeu, "DOUBLE", apply=True)
        self.assertNotEqual(premier, second)
        self.assertTrue((self.root / premier).is_file())
        self.assertTrue((self.root / second).is_file())

    def test_le_nom_du_kit_est_assaini(self):
        jeu = slicer.slice_sample(self.sd, self.rel, mode="grid", count=4)
        rel, _ = slicer.save_sliced_kit(self.sd, jeu, "nom/avec:interdits?",
                                        apply=True)
        self.assertTrue(rel)
        self.assertTrue((self.root / rel).is_file())
        nom = Path(rel).stem
        for interdit in '/\\:?*"<>|':
            self.assertNotIn(interdit, nom)

    def test_un_decoupage_vide_n_ecrit_pas(self):
        vide = slicer.SliceSet(rel=self.rel, sr=self.sr, frames=self.frames)
        rel, message = slicer.save_sliced_kit(self.sd, vide, apply=True)
        self.assertEqual(rel, "")
        self.assertIn("Aucune", message)

    # -- écoute et export --------------------------------------------------- #

    def test_render_slice_rend_la_bonne_longueur(self):
        jeu = slicer.slice_sample(self.sd, self.rel, mode="grid", count=8)
        for index in (0, 3, len(jeu) - 1):
            with self.subTest(tranche=index):
                bloc = slicer.render_slice(self.sd, jeu, index)
                self.assertEqual(bloc.shape[0], jeu.slices[index].frames)

    def test_render_slice_hors_bornes(self):
        jeu = slicer.slice_sample(self.sd, self.rel, mode="grid", count=4)
        self.assertEqual(slicer.render_slice(self.sd, jeu, -1).size, 0)
        self.assertEqual(slicer.render_slice(self.sd, jeu, 99).size, 0)

    def test_export_en_fichiers_separes(self):
        jeu = slicer.slice_sample(self.sd, self.rel, mode="grid", count=8)

        prevus, erreurs = slicer.export_slices(self.sd, jeu,
                                               "SAMPLES/TRANCHES")
        self.assertEqual(len(prevus), 8)
        self.assertEqual(erreurs, [])
        self.assertFalse((self.root / "SAMPLES/TRANCHES").exists(),
                         "la simulation a créé le dossier")

        ecrits, erreurs = slicer.export_slices(self.sd, jeu,
                                               "SAMPLES/TRANCHES",
                                               apply=True)
        self.assertEqual(erreurs, [])
        self.assertEqual(len(ecrits), 8)
        total = 0
        for rel, tranche in zip(ecrits, jeu.slices):
            info = wav.probe(self.root / rel)
            self.assertTrue(info.ok)
            self.assertEqual(info.frames, tranche.frames)
            total += info.frames
        self.assertEqual(total, self.frames,
                         "les tranches exportées doivent reconstituer le tout")

    def test_export_sans_dossier(self):
        jeu = slicer.slice_sample(self.sd, self.rel, mode="grid", count=4)
        fichiers, erreurs = slicer.export_slices(self.sd, jeu, "")
        self.assertEqual(fichiers, [])
        self.assertTrue(erreurs)

    # -- cas limites -------------------------------------------------------- #

    def test_fichier_absent(self):
        jeu = slicer.slice_sample(self.sd, "SAMPLES/pas-la.wav")
        self.assertEqual(len(jeu), 0)
        self.assertFalse(jeu)
        self.assertEqual(jeu.summary(), "Aucune tranche.")

    def test_fichier_trop_court_pour_etre_decoupe(self):
        rel = "SAMPLES/LOOPS/court.wav"
        wav.write(self.root / rel, np.zeros(64, dtype=np.float32), 44100)
        jeu = slicer.slice_sample(self.sd, rel, mode="grid", count=16)
        self.assertEqual(len(jeu), 1)
        self.assertEqual(jeu.slices[0].start, 0)
        self.assertEqual(jeu.slices[0].end, 64)

    def test_detect_slices_sur_du_silence(self):
        """Sans attaque, une seule tranche : le fichier entier."""
        silence = np.zeros(44100, dtype=np.float32)
        starts = slicer.detect_slices(silence, 44100)
        self.assertEqual(starts, [0])

    def test_grid_slices_sur_un_fichier_vide(self):
        self.assertEqual(slicer.grid_slices(0, 44100, 16), [0])

    def test_le_resume_annonce_les_extremes(self):
        jeu = slicer.slice_sample(self.sd, self.rel, mode="transients")
        texte = jeu.summary()
        self.assertIn("tranches", texte)
        self.assertIn("ms", texte)
        detail = jeu.to_text()
        self.assertIn(self.rel, detail)
        self.assertEqual(len(detail.splitlines()), len(jeu) + 2)

    def test_les_etiquettes_sont_numerotees_et_courtes(self):
        jeu = slicer.slice_sample(self.sd, self.rel, mode="grid", count=12)
        for index, tranche in enumerate(jeu.slices, 1):
            self.assertTrue(tranche.label.endswith("%02d" % index),
                            tranche.label)
            self.assertLessEqual(len(tranche.label), slicer.MAX_ROW_NAME + 3)


class TestSimilarity(unittest.TestCase):
    """Recherche d'échantillons par ressemblance sonore.

    La carte d'essai contient trois familles franchement distinctes — des
    graves courts, des bruits aigus, des bourdons tenus — et les tests
    vérifient que les voisins d'un son appartiennent à sa famille. Comparer
    des familles si éloignées serait trop facile si les descripteurs étaient
    mal normalisés : c'est précisément ce que ces tests attrapent.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.root = base / "carte"
        for sub in ("SONGS", "SYNTHS", "KITS",
                    "SAMPLES/DRUMS/Kick", "SAMPLES/DRUMS/HatC",
                    "SAMPLES/PADS"):
            (self.root / sub).mkdir(parents=True)

        rng = np.random.default_rng(11)
        sr = 44100

        # Six graves courts : attaque immédiate, énergie sous 200 Hz.
        for index in range(6):
            t = np.linspace(0, 0.25, int(0.25 * sr), endpoint=False,
                            dtype=np.float32)
            freq = 55.0 + index * 4.0
            wav.write(self.root / ("SAMPLES/DRUMS/Kick/k%d.wav" % index),
                      (0.8 * np.sin(2 * np.pi * freq * t)
                       * np.exp(-t * (18 + index))).astype(np.float32), sr)

        # Six bruits aigus, filtrés en haut : des charlestons.
        for index in range(6):
            n = int(0.12 * sr)
            t = np.linspace(0, 0.12, n, endpoint=False, dtype=np.float32)
            bruit = rng.standard_normal(n).astype(np.float32)
            # Différenciation = passe-haut du pauvre.
            aigu = np.diff(bruit, prepend=np.float32(0.0))
            wav.write(self.root / ("SAMPLES/DRUMS/HatC/h%d.wav" % index),
                      (0.5 * aigu * np.exp(-t * (40 + index * 5))
                       ).astype(np.float32), sr)

        # Six bourdons tenus : attaque lente, spectre médium, pas de crête.
        for index in range(6):
            n = int(1.6 * sr)
            t = np.linspace(0, 1.6, n, endpoint=False, dtype=np.float32)
            enveloppe = np.clip(t / 0.6, 0.0, 1.0)
            son = sum(0.25 / (h + 1) * np.sin(2 * np.pi * (220 + index * 10)
                                              * (h + 1) * t)
                      for h in range(4))
            wav.write(self.root / ("SAMPLES/PADS/p%d.wav" % index),
                      (son * enveloppe).astype(np.float32), sr)

        self.sd = sdcard.SDCard(self.root)
        self.lib = db.Library(base / "index.db")
        scan.scan_card(self.sd, self.lib, compute_hash=True, analyze=True)

    def tearDown(self):
        self.lib.close()
        self._tmp.cleanup()

    def _famille(self, rel: str) -> str:
        parts = sdcard.norm_rel(rel).split("/")
        return parts[-2] if len(parts) >= 2 else ""

    # -- l'index porte bien les descripteurs -------------------------------- #

    def test_le_scan_enregistre_les_descripteurs(self):
        """Ils étaient calculables mais jamais conservés avant le schéma 4."""
        for row in self.lib.search_samples(limit=100):
            with self.subTest(fichier=row["rel"]):
                for champ in similarity.FEATURES:
                    self.assertIsNotNone(row[champ],
                                         "%s manquant" % champ)

    def test_le_schema_est_en_version_4(self):
        self.assertEqual(self.lib.get_meta("schema_version"), "4")

    def test_une_base_mise_a_niveau_reclame_une_reanalyse(self):
        """Les colonnes neuves sont vides : il faut y revenir."""
        import sqlite3

        chemin = Path(self._tmp.name) / "ancienne.db"
        lib = db.Library(chemin)
        lib.upsert_sample({"rel": "SAMPLES/x.wav", "size": 1})
        lib.add_tag("sample", "SAMPLES/x.wav", "garde-moi")
        lib.commit()
        lib.close()

        con = sqlite3.connect(chemin)
        for champ in similarity.FEATURES:
            con.execute("ALTER TABLE samples DROP COLUMN %s" % champ)
        con.execute("UPDATE meta SET value = '3' WHERE key = 'schema_version'")
        con.commit()
        con.close()

        lib = db.Library(chemin)
        try:
            cols = {r["name"] for r in
                    lib.con.execute("PRAGMA table_info(samples)")}
            self.assertTrue(set(similarity.FEATURES) <= cols,
                            "les colonnes n'ont pas été ajoutées")
            self.assertTrue(lib.needs_rescan,
                            "la réanalyse doit être réclamée")
            self.assertEqual(lib.tags_of("sample", "SAMPLES/x.wav"),
                             ["garde-moi"],
                             "les étiquettes de l'utilisateur sont perdues")
        finally:
            lib.close()

    def test_une_analyse_incrementale_est_forcee_apres_mise_a_niveau(self):
        """Sans cela, les fichiers inchangés seraient sautés et les colonnes
        resteraient vides — le drapeau ne servait à rien."""
        self.lib.set_meta("needs_rescan", "1")
        self.lib.con.execute("UPDATE samples SET centroid = NULL")
        self.lib.commit()

        scan.scan_card(self.sd, self.lib, compute_hash=False, analyze=True,
                       full=False)
        vides = self.lib.con.execute(
            "SELECT COUNT(*) FROM samples WHERE centroid IS NULL").fetchone()[0]
        self.assertEqual(vides, 0, "les descripteurs n'ont pas été refaits")
        self.assertFalse(self.lib.needs_rescan,
                         "le drapeau doit être levé après l'analyse")

    def test_le_drapeau_reste_pose_sans_analyse_acoustique(self):
        self.lib.set_meta("needs_rescan", "1")
        scan.scan_card(self.sd, self.lib, compute_hash=False, analyze=False)
        self.assertTrue(self.lib.needs_rescan,
                        "sans analyse acoustique, les colonnes restent vides")

    # -- l'espace de comparaison -------------------------------------------- #

    def test_l_espace_contient_tous_les_echantillons_analyses(self):
        espace = similarity.build_space(self.lib)
        self.assertEqual(len(espace), self.lib.stats()["samples"])
        self.assertEqual(espace.vectors.shape,
                         (len(espace), len(similarity.FEATURES)))

    def test_un_echantillon_sans_descripteur_est_ecarte(self):
        """Un vecteur incomplet donnerait des voisins faux sans le dire."""
        self.lib.con.execute(
            "UPDATE samples SET attack = NULL WHERE rel LIKE '%k0.wav'")
        self.lib.commit()
        espace = similarity.build_space(self.lib)
        self.assertFalse(espace.has("SAMPLES/DRUMS/Kick/k0.wav"))
        self.assertEqual(len(espace), self.lib.stats()["samples"] - 1)

    def test_un_espace_vide_ne_casse_rien(self):
        self.lib.clear()
        self.lib.commit()
        espace = similarity.build_space(self.lib)
        self.assertFalse(espace)
        self.assertEqual(len(espace), 0)
        self.assertEqual(similarity.similar(self.lib, "SAMPLES/x.wav"), [])

    def test_l_espace_se_restreint_a_une_categorie(self):
        espace = similarity.build_space(self.lib, category="Kick")
        self.assertTrue(espace)
        for rel in espace.rels:
            self.assertEqual(self._famille(rel), "kick")

    # -- la ressemblance ---------------------------------------------------- #

    def test_les_voisins_sont_de_la_meme_famille(self):
        espace = similarity.build_space(self.lib)
        for rel in espace.rels:
            famille = self._famille(rel)
            voisins = similarity.similar(self.lib, rel, limit=3,
                                         space=espace)
            with self.subTest(fichier=Path(rel).name):
                self.assertTrue(voisins)
                memes = sum(1 for v in voisins
                            if self._famille(v.rel) == famille)
                self.assertGreaterEqual(
                    memes, 2,
                    "%s : %d / %d voisins de la même famille (%s)"
                    % (Path(rel).name, memes, len(voisins),
                       [Path(v.rel).name for v in voisins]))

    def test_un_son_ne_se_retourne_jamais_lui_meme(self):
        espace = similarity.build_space(self.lib)
        for rel in espace.rels:
            voisins = similarity.similar(self.lib, rel, limit=50,
                                         space=espace)
            self.assertNotIn(sdcard.norm_rel(rel),
                             [sdcard.norm_rel(v.rel) for v in voisins])

    def test_les_voisins_sont_tries_du_plus_proche(self):
        espace = similarity.build_space(self.lib)
        voisins = similarity.similar(self.lib, espace.rels[0], limit=10,
                                     space=espace)
        distances = [v.distance for v in voisins]
        self.assertEqual(distances, sorted(distances))
        self.assertGreaterEqual(distances[0], 0.0)

    def test_la_limite_est_respectee(self):
        espace = similarity.build_space(self.lib)
        for limite in (1, 3, 5):
            voisins = similarity.similar(self.lib, espace.rels[0],
                                         limit=limite, space=espace)
            self.assertEqual(len(voisins), limite)

    def test_la_distance_maximale_coupe_la_liste(self):
        espace = similarity.build_space(self.lib)
        tous = similarity.similar(self.lib, espace.rels[0], limit=50,
                                  space=espace)
        seuil = tous[2].distance
        courts = similarity.similar(self.lib, espace.rels[0], limit=50,
                                    space=espace, max_distance=seuil)
        self.assertLessEqual(len(courts), len(tous))
        for match in courts:
            self.assertLessEqual(match.distance, seuil)

    def test_un_echantillon_inconnu(self):
        self.assertEqual(similarity.similar(self.lib, "SAMPLES/pas-la.wav"),
                         [])

    def test_la_proximite_s_affiche_en_pourcentage(self):
        proche = similarity.Match(rel="a", distance=0.0)
        loin = similarity.Match(rel="b", distance=4.0)
        self.assertEqual(proche.closeness, 100)
        self.assertLess(loin.closeness, 10)
        self.assertGreaterEqual(loin.closeness, 0)

    def test_same_category_restreint_la_recherche(self):
        voisins = similarity.similar(self.lib, "SAMPLES/DRUMS/Kick/k0.wav",
                                     limit=10, same_category=True)
        self.assertTrue(voisins)
        for match in voisins:
            self.assertEqual(self._famille(match.rel), "kick")

    # -- pas de detection de quasi-doublons : voir similarity.py ----------- #

    def test_il_n_y_a_pas_de_detection_de_quasi_doublons(self):
        """Mesure faite, fonction retirée : voir l'explication du module.

        Le descripteur est aveugle à la hauteur. Serré à 0,12 avec une durée
        à 2 % près, il ne trouvait que des notes voisines du même instrument
        (``Cello B3`` avec ``Cello C4``) ; desserré à 0,45, il regroupait
        59 % de la bibliothèque. La question du doublon a déjà une réponse
        juste : ``Library.duplicates()``, octet pour octet.
        """
        self.assertFalse(hasattr(similarity, "near_duplicates"))
        self.assertNotIn("near_duplicates", similarity.__all__)
        self.assertFalse(hasattr(similarity, "NEAR_DUPLICATE_DISTANCE"))

    # -- explication -------------------------------------------------------- #

    def test_describe_resume_les_descripteurs(self):
        row = self.lib.get("sample", "SAMPLES/DRUMS/Kick/k0.wav")
        texte = similarity.describe(row)
        for mot in ("brillance", "grave", "attaque"):
            self.assertIn(mot, texte)

    def test_describe_sur_une_ligne_sans_analyse(self):
        self.assertIn("Aucun", similarity.describe(None))

    def test_les_poids_couvrent_tous_les_descripteurs(self):
        self.assertEqual(set(similarity.WEIGHTS), set(similarity.FEATURES))
        self.assertTrue(similarity.LOG_FEATURES <= set(similarity.FEATURES))


class TestAttackTime(unittest.TestCase):
    """``analysis.attack_time`` : la seule mesure temporelle du descripteur."""

    def test_une_percussion_attaque_tout_de_suite(self):
        sr = 44100
        t = np.linspace(0, 0.3, int(0.3 * sr), endpoint=False,
                        dtype=np.float32)
        kick = (np.sin(2 * np.pi * 60 * t) * np.exp(-t * 20)
                ).astype(np.float32)
        self.assertLess(analysis.attack_time(kick, sr), 0.02)

    def test_une_nappe_met_du_temps(self):
        sr = 44100
        n = int(1.5 * sr)
        t = np.linspace(0, 1.5, n, endpoint=False, dtype=np.float32)
        nappe = (np.sin(2 * np.pi * 220 * t)
                 * np.clip(t / 0.8, 0.0, 1.0)).astype(np.float32)
        attaque = analysis.attack_time(nappe, sr)
        self.assertGreater(attaque, 0.3)
        self.assertLess(attaque, 1.5)

    def test_sur_du_silence(self):
        self.assertEqual(analysis.attack_time(np.zeros(1000,
                                                       dtype=np.float32),
                                              44100), 0.0)

    def test_sur_un_tableau_minuscule(self):
        self.assertEqual(analysis.attack_time(np.zeros(3, dtype=np.float32),
                                              44100), 0.0)

    def test_sans_frequence(self):
        self.assertEqual(analysis.attack_time(np.ones(100,
                                                      dtype=np.float32), 0),
                         0.0)


class TestSongPack(unittest.TestCase):
    """Rassembler un morceau et ses dépendances.

    Le point à ne jamais casser : **la carte n'est pas touchée.** Tout est
    copié, rien n'est déplacé, et un morceau reste lisible par le Deluge
    après l'opération.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.root = base / "carte"
        for sub in ("SONGS", "SYNTHS", "SYNTHS/acid", "KITS",
                    "SAMPLES/DRUMS/Kick", "SAMPLES/DRUMS/Snare"):
            (self.root / sub).mkdir(parents=True)

        t = np.linspace(0, 0.3, 13230, endpoint=False, dtype=np.float32)
        wav.write(self.root / "SAMPLES/DRUMS/Kick/k.wav",
                  (0.7 * np.sin(2 * np.pi * 60 * t) * np.exp(-t * 14)
                   ).astype(np.float32), 44100)
        wav.write(self.root / "SAMPLES/DRUMS/Snare/s.wav",
                  (0.4 * np.random.default_rng(2).standard_normal(8820)
                   ).astype(np.float32), 44100)
        wav.write(self.root / "SAMPLES/DRUMS/Kick/ailleurs.wav",
                  (0.3 * np.sin(2 * np.pi * 90 * t)).astype(np.float32),
                  44100)

        preset = SynthPreset.new("BASSE")
        preset.sound.osc1.type = "sample"
        preset.sound.osc1.file_name = "SAMPLES/DRUMS/Kick/k.wav"
        preset.save(self.root / "SYNTHS" / "BASSE.XML", backup=False)

        # Un preset rangé dans un sous-dossier, comme sur une vraie carte.
        acide = SynthPreset.new("TB01")
        acide.sound.osc1.type = "saw"
        acide.save(self.root / "SYNTHS/acid" / "TB01.XML", backup=False)

        kit = Kit.new("KIT")
        kit.add_row("KICK", "SAMPLES/DRUMS/Kick/k.wav")
        kit.add_row("SNARE", "SAMPLES/DRUMS/Snare/s.wav")
        kit.save(self.root / "KITS" / "KIT.XML", backup=False)

        self.sd = sdcard.SDCard(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    # -- fabrique de morceaux ---------------------------------------------- #

    def _song(self, nom: str = "MORCEAU.XML", instruments: str = "",
              clips: str = "") -> str:
        """Écrit un morceau et retourne son chemin relatif."""
        defaut_inst = ('<sound presetName="BASSE" presetFolder="SYNTHS" />'
                       '<kit presetName="KIT" presetFolder="KITS" />')
        defaut_clips = (
            '<instrumentClip length="384" section="0" clipName="Basse"'
            ' instrumentPresetName="BASSE" instrumentPresetFolder="SYNTHS">'
            '<noteRows><noteRow y="36" noteDataWithLift="0x'
            '0000000000000018401400000060000000184014"/></noteRows>'
            '</instrumentClip>')
        texte = (
            '<song firmwareVersion="3.0.4" timePerTimerTick="459"'
            ' timerTickFraction="1610612736" inputTickMagnitude="1"'
            ' rootNote="60">'
            '<modeNotes><modeNote>0</modeNote><modeNote>2</modeNote>'
            '<modeNote>4</modeNote><modeNote>5</modeNote>'
            '<modeNote>7</modeNote><modeNote>9</modeNote>'
            '<modeNote>11</modeNote></modeNotes>'
            '<instruments>%s</instruments>'
            '<sessionClips>%s</sessionClips></song>'
            % (instruments or defaut_inst, clips or defaut_clips))
        (self.root / "SONGS" / nom).write_text(texte, encoding="utf-8")
        return "SONGS/%s" % nom

    def _empreintes(self) -> dict:
        return {p.relative_to(self.root).as_posix():
                hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.root.rglob("*") if p.is_file()}

    # -- inventaire -------------------------------------------------------- #

    def test_inventaire_complet(self):
        pack = songpack.collect(self.sd, self._song())
        self.assertTrue(pack)
        self.assertTrue(pack.complete, (pack.missing_presets,
                                        pack.missing_samples))
        self.assertEqual(sorted(pack.presets),
                         ["KITS/KIT.XML", "SYNTHS/BASSE.XML"])
        self.assertIn("SAMPLES/DRUMS/Kick/k.wav", pack.samples)
        self.assertIn("SAMPLES/DRUMS/Snare/s.wav", pack.samples)
        self.assertEqual(len(pack), 5, pack.files())

    def test_un_echantillon_etranger_n_est_pas_embarque(self):
        pack = songpack.collect(self.sd, self._song())
        self.assertNotIn("SAMPLES/DRUMS/Kick/ailleurs.wav", pack.samples)

    def test_un_preset_dans_un_sous_dossier_est_retrouve(self):
        """Un morceau nomme ses presets, il ne donne pas leur chemin."""
        pack = songpack.collect(self.sd, self._song(
            instruments='<sound presetName="TB01" presetFolder="SYNTHS/acid" />',
            clips='<instrumentClip length="384" section="0"'
                  ' instrumentPresetName="TB01"'
                  ' instrumentPresetFolder="SYNTHS/acid" />'))
        self.assertIn("SYNTHS/acid/TB01.XML", pack.presets)
        self.assertTrue(pack.complete, pack.missing_presets)

    def test_un_preset_au_dossier_sans_racine(self):
        """``acid`` plutôt que ``SYNTHS/acid`` : le cas existe sur la carte."""
        pack = songpack.collect(self.sd, self._song(
            instruments='<sound presetName="TB01" presetFolder="acid" />',
            clips='<instrumentClip length="384" instrumentPresetName="TB01"'
                  ' instrumentPresetFolder="acid" />'))
        self.assertIn("SYNTHS/acid/TB01.XML", pack.presets)

    def test_un_preset_absent_est_signale_sans_bloquer(self):
        pack = songpack.collect(self.sd, self._song(
            instruments='<sound presetName="DISPARU" presetFolder="SYNTHS" />',
            clips='<instrumentClip length="384"'
                  ' instrumentPresetName="DISPARU"'
                  ' instrumentPresetFolder="SYNTHS" />'))
        self.assertFalse(pack.complete)
        self.assertTrue(pack.missing_presets)
        self.assertIn("DISPARU", pack.missing_presets[0])
        # Le morceau lui-même reste dans la liste à copier.
        self.assertIn(pack.song_rel, pack.files())

    def test_un_echantillon_absent_est_signale(self):
        casse = SynthPreset.new("CASSE")
        casse.sound.osc1.type = "sample"
        casse.sound.osc1.file_name = "SAMPLES/PARTI/x.wav"
        casse.save(self.root / "SYNTHS" / "CASSE.XML", backup=False)

        pack = songpack.collect(self.sd, self._song(
            instruments='<sound presetName="CASSE" presetFolder="SYNTHS" />',
            clips='<instrumentClip length="384" instrumentPresetName="CASSE"'
                  ' instrumentPresetFolder="SYNTHS" />'))
        self.assertFalse(pack.complete)
        self.assertEqual(pack.missing_samples, ["SAMPLES/PARTI/x.wav"])

    def test_un_morceau_introuvable(self):
        pack = songpack.collect(self.sd, "SONGS/pas-la.XML")
        self.assertFalse(pack)
        self.assertEqual(len(pack), 0)
        self.assertIn("introuvable", pack.summary())

    def test_le_detail_cite_tout(self):
        pack = songpack.collect(self.sd, self._song())
        texte = pack.to_text()
        for rel in pack.files():
            self.assertIn(rel, texte)
        self.assertIn("fichier(s)", pack.summary())

    # -- copie -------------------------------------------------------------- #

    def test_la_simulation_n_ecrit_rien(self):
        pack = songpack.collect(self.sd, self._song())
        dest = Path(self._tmp.name) / "ailleurs"
        prevus, erreurs = songpack.write_pack(self.sd, pack, dest)
        self.assertEqual(len(prevus), len(pack))
        self.assertEqual(erreurs, [])
        self.assertFalse(dest.exists(), "la simulation a créé le dossier")

    def test_le_dossier_produit_est_une_mini_carte(self):
        pack = songpack.collect(self.sd, self._song())
        dest = Path(self._tmp.name) / "ailleurs"
        copies, erreurs = songpack.write_pack(self.sd, pack, dest,
                                              apply=True)
        self.assertEqual(erreurs, [])
        self.assertEqual(len(copies), len(pack))

        racines = {p.relative_to(dest).parts[0]
                   for p in dest.rglob("*") if p.is_file()}
        self.assertEqual(racines, {"SONGS", "SYNTHS", "KITS", "SAMPLES"})

        # Le morceau copié se relit, et tout ce qu'il cite est là.
        copie = dest / pack.song_rel
        self.assertTrue(copie.is_file())
        relu = Song.load(copie)
        copie_sd = sdcard.SDCard(dest)
        absents = [r for r in relu.sample_paths()
                   if copie_sd.resolve_sample(r) is None]
        self.assertEqual(absents, [])

    def test_les_copies_sont_identiques_a_l_octet(self):
        pack = songpack.collect(self.sd, self._song())
        dest = Path(self._tmp.name) / "ailleurs"
        songpack.write_pack(self.sd, pack, dest, apply=True)
        for rel in pack.files():
            with self.subTest(fichier=rel):
                source = self.sd.abs(rel)
                self.assertEqual(
                    hashlib.sha256((dest / rel).read_bytes()).hexdigest(),
                    hashlib.sha256(source.read_bytes()).hexdigest())

    def test_la_carte_n_est_jamais_touchee(self):
        """Tout est copié : rien ne bouge ni ne change sur la carte."""
        rel = self._song()          # le morceau d'abord...
        avant = self._empreintes()  # ...puis l'empreinte de la carte
        pack = songpack.collect(self.sd, rel)
        dest = Path(self._tmp.name) / "ailleurs"
        songpack.write_pack(self.sd, pack, dest, apply=True)
        self.assertEqual(self._empreintes(), avant)

    def test_la_copie_s_interrompt_proprement(self):
        pack = songpack.collect(self.sd, self._song())
        dest = Path(self._tmp.name) / "ailleurs"
        copies, erreurs = songpack.write_pack(
            self.sd, pack, dest, apply=True, should_stop=lambda: True)
        self.assertEqual(copies, [])
        self.assertEqual(erreurs, [])

    def test_la_progression_est_rapportee(self):
        pack = songpack.collect(self.sd, self._song())
        vus: list = []
        songpack.write_pack(self.sd, pack,
                            Path(self._tmp.name) / "p", apply=True,
                            progress=vus.append)
        self.assertEqual(len(vus), len(pack))
        self.assertEqual(len(vus[0]), 3)

    def test_un_pack_vide_ne_copie_rien(self):
        vide = songpack.SongPack()
        copies, erreurs = songpack.write_pack(
            self.sd, vide, Path(self._tmp.name) / "x", apply=True)
        self.assertEqual(copies, [])
        self.assertTrue(erreurs)

    def test_le_nom_de_dossier_est_assaini(self):
        # Convention déjà en place dans ``sdcard.safe_deluge_name``.
        self.assertEqual(songpack.safe_folder_name(""), "SANS NOM")
        propre = songpack.safe_folder_name("Mon/Morceau: été ?")
        for interdit in '/\\:?*"<>|':
            self.assertNotIn(interdit, propre)
        self.assertLessEqual(len(propre), 40)


class TestSongToMidi(unittest.TestCase):
    """``midifile.song_to_midi`` : une piste par clip."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _song(self, clips: int = 3, notes: int = 4) -> Song:
        from delugeapp.core.model import Clip, Note, NoteRow

        song = Song(tempo_bpm=124.0)
        for index in range(clips):
            clip = Clip(name="Clip %d" % (index + 1), length=384,
                        is_kit=(index == 0))
            row = NoteRow(y=36 + index)
            row.notes = [Note(pos=n * 24, length=12, velocity=100)
                         for n in range(notes)]
            clip.note_rows = [row]
            song.clips.append(clip)
        return song

    def test_une_piste_par_clip(self):
        chemin = self.base / "a.mid"
        self.assertEqual(midifile.song_to_midi(chemin, self._song(3)), 3)
        donnees = chemin.read_bytes()
        self.assertEqual(donnees[:4], b"MThd")
        # Format 1 : les pistes annoncées comprennent celle du tempo.
        self.assertEqual(int.from_bytes(donnees[10:12], "big"), 4)

    def test_un_clip_sans_note_est_ignore(self):
        from delugeapp.core.model import Clip

        song = self._song(2)
        song.clips.append(Clip(name="Muet", length=384))
        self.assertEqual(midifile.song_to_midi(self.base / "b.mid", song), 2)

    def test_un_morceau_sans_note_n_ecrit_rien(self):
        chemin = self.base / "c.mid"
        self.assertEqual(midifile.song_to_midi(chemin, Song()), 0)
        self.assertFalse(chemin.exists())

    def test_le_nombre_de_pistes_est_plafonne(self):
        song = self._song(10)
        self.assertEqual(
            midifile.song_to_midi(self.base / "d.mid", song, max_clips=4), 4)

    def test_le_tempo_du_morceau_est_repris(self):
        chemin = self.base / "e.mid"
        midifile.song_to_midi(chemin, self._song(1))
        # 124 BPM -> 60 000 000 / 124 microsecondes par noire.
        attendu = int(round(60_000_000 / 124.0))
        self.assertIn(attendu.to_bytes(3, "big"), chemin.read_bytes())

    def test_un_clip_de_kit_part_sur_le_canal_des_percussions(self):
        chemin = self.base / "f.mid"
        midifile.song_to_midi(chemin, self._song(2))
        donnees = chemin.read_bytes()
        # Canal 10 (indice 9) : statut 0x99 pour un note-on.
        self.assertIn(b"\x99", donnees)
        self.assertIn(b"\x90", donnees)


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


class _SortieFactice:
    """Une sortie MIDI qui note ce qu'on lui envoie, avec l'instant.

    Elle permet de vérifier le séquenceur **sans aucun matériel** : c'est
    précisément là que je me suis trompé — une piste de motif n'est pas une
    suite de 0 et de 1 mais une liste éparse de ``Step``, et le motif sortait
    deux fois trop vite, les coups dans l'ordre de la liste au lieu de leur
    position.
    """

    def __init__(self):
        self.is_open = True
        self.events = []          # (instant, type, note, vélocité)
        self.t0 = time.monotonic()

    def _note(self, genre, note, velocity=0):
        self.events.append((time.monotonic() - self.t0, genre, int(note),
                            int(velocity)))

    def note_on(self, note, velocity=100, channel=1):
        self._note("on", note, velocity)
        return True

    def note_off(self, note, channel=1):
        self._note("off", note)
        return True

    def control_change(self, cc, value, channel=1):
        self.events.append((time.monotonic() - self.t0, "cc", int(cc),
                            int(value)))
        return True

    def realtime(self, status):
        self.events.append((time.monotonic() - self.t0, "rt", int(status), 0))
        return True

    def all_notes_off(self, channel=None):
        self.events.append((time.monotonic() - self.t0, "panic", 0, 0))

    def close(self):
        self.is_open = False

    def temps_des(self, genre, note=None):
        return [e[0] for e in self.events
                if e[1] == genre and (note is None or e[2] == note)]


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
        self.assertTrue(out.open(ports[0]))
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


# --------------------------------------------------------------------------- #
# Générateurs et aides à la composition (13 octobre 2026)
# --------------------------------------------------------------------------- #

class TestGenerateurRecale(unittest.TestCase):
    """Le générateur de presets, recalé sur la carte et sur le firmware."""

    @staticmethod
    def _gen(genre, role, seed, **kw):
        return synthgen.generate(synthgen.GenOptions(genre=genre, role=role,
                                                     seed=seed, **kw))

    def test_l_arpegiateur_s_ecrit_pour_c1(self):
        """c1.2.1 ignore ``mode`` dans un fichier c1.2.x : il lit arpMode."""
        with tempfile.TemporaryDirectory() as tmp:
            preset = self._gen("trance", "arp", 3)
            self.assertTrue(preset.sound.arp.is_on)
            racine = dxml.load(preset.save(Path(tmp) / "A.XML",
                                           backup=False)).root
        arp = racine.find("arpeggiator")
        self.assertEqual(arp.get("arpMode"), "arp")
        self.assertIn(arp.get("noteMode"),
                      ("up", "down", "upDown", "random", "asPlayed"))
        self.assertIn(arp.get("octaveMode"),
                      ("up", "down", "upDown", "alt", "random"))
        # Double-croche ou croche, jamais la quadruple-croche d'avant (9).
        self.assertIn(arp.get("syncLevel"), ("6", "7", "8"))

    def test_toujours_sensible_a_la_velocite(self):
        """778 presets réels sur 911 ; le générateur l'oubliait."""
        for genre in genres.genre_keys():
            for role in genres.ROLES:
                son = self._gen(genre, role, 4).sound
                with self.subTest(genre=genre, role=role):
                    vel = [c.display() for c in son.patch_cables
                           if (c.source, c.destination)
                           == ("velocity", "volume")]
                    self.assertTrue(vel)
                    self.assertGreaterEqual(vel[0], 25)

    def test_la_cloche_est_fm_et_accordee(self):
        from collections import Counter

        modes = Counter(self._gen("ambient", "bell", s).sound.mode
                        for s in range(30))
        self.assertGreater(modes["fm"], 15)
        fm = next(self._gen("ambient", "bell", s) for s in range(30)
                  if self._gen("ambient", "bell", s).sound.mode == "fm")
        self.assertNotEqual(fm.sound.modulator1.transpose, 0,
                            "une cloche à l'unisson n'a rien de métallique")
        with tempfile.TemporaryDirectory() as tmp:
            racine = dxml.load(fm.save(Path(tmp) / "B.XML",
                                       backup=False)).root
        self.assertEqual(racine.find("modulator1").get("transpose"),
                         str(fm.sound.modulator1.transpose))
        self.assertIsNotNone(racine.find("modulator2").get("toModulator1"))

    def test_un_preset_soustractif_n_ecrit_pas_de_modulateur(self):
        with tempfile.TemporaryDirectory() as tmp:
            preset = self._gen("house", "pad", 1, mode="subtractive")
            racine = dxml.load(preset.save(Path(tmp) / "P.XML",
                                           backup=False)).root
        self.assertIsNone(racine.find("modulator1"))

    def test_le_wobble_de_la_dubstep_est_synchronise(self):
        synchro = [self._gen("dubstep", "bass", s).sound.lfo1.sync_level
                   for s in range(30)]
        self.assertGreater(sum(1 for v in synchro if v), 15)
        self.assertTrue(all(v in (0, 5, 6, 7) for v in synchro))

    def test_les_basses_tiennent_sauf_en_acid(self):
        """Sustain médian réel : 35 ; l'acid garde sa basse qui claque."""
        from delugeapp.core.fixedpoint import to_display
        from statistics import median

        def sustain(genre):
            return median(to_display(self._gen(genre, "bass", s).sound
                                     .env1.sustain) for s in range(20))

        self.assertGreater(sustain("deep_house"), 15)
        self.assertLess(sustain("acid"), 10)

    def test_les_signatures_de_genre_tiennent(self):
        from statistics import median

        def med(genre, role, fn):
            return median(fn(self._gen(genre, role, s).sound)
                          for s in range(24))

        self.assertGreater(med("trance", "pad", lambda s: s.unison_num),
                           med("deep_house", "pad", lambda s: s.unison_num))
        self.assertGreater(
            med("acid", "bass", lambda s: s.display("lpfResonance")),
            med("house", "bass", lambda s: s.display("lpfResonance")))
        self.assertLess(med("house", "bass",
                            lambda s: s.display("reverbAmount")), 8)

    def test_le_rendu_entend_l_accord_des_modulateurs(self):
        import copy

        base = self._gen("ambient", "bell", 1, mode="fm")
        unisson = copy.deepcopy(base)
        unisson.sound.modulator1.transpose = 0
        unisson.sound.modulator1.cents = 0
        a = render.render_sound(base.sound, note=60, seconds=0.8)
        b = render.render_sound(unisson.sound, note=60, seconds=0.8)
        self.assertGreater(float(np.max(np.abs(a - b))), 0.05)

    def test_l_ecoute_d_une_rangee_once_ignore_la_fin_de_note(self):
        """Sur la machine, ONCE joue l'échantillon jusqu'au bout."""
        from delugeapp.core.model import REPEAT_CUT, REPEAT_ONCE

        with tempfile.TemporaryDirectory() as tmp:
            racine = Path(tmp) / "carte"
            (racine / "SAMPLES").mkdir(parents=True)
            t = np.linspace(0, 1.0, 44100, endpoint=False, dtype=np.float32)
            wav.write(racine / "SAMPLES" / "long.wav",
                      (0.5 * np.sin(2 * np.pi * 220 * t)).astype(np.float32),
                      44100)
            sd = sdcard.SDCard(racine)
            kit = Kit.new("K")
            row = kit.add_row("LONG", "SAMPLES/long.wav", seconds=1.0,
                              frames=44100)
            self.assertEqual(row.sound.osc1.loop_mode, REPEAT_ONCE)
            once = render.render_sound(row.sound, note=60, seconds=1.0,
                                       gate=0.3, sd=sd)
            row.sound.osc1.loop_mode = REPEAT_CUT
            cut = render.render_sound(row.sound, note=60, seconds=1.0,
                                      gate=0.3, sd=sd)
        fenetre = slice(int(0.6 * 44100), int(0.7 * 44100))
        self.assertGreater(float(np.max(np.abs(once[fenetre]))), 0.05)
        self.assertLess(float(np.max(np.abs(cut[fenetre]))), 0.01)

    def test_lfo_synchronise_a_120_bpm(self):
        self.assertAlmostEqual(render.synced_hz(7), 8.0)
        self.assertAlmostEqual(render.synced_hz(5), 2.0)
        self.assertAlmostEqual(render.synced_hz(3), 0.5)
        self.assertEqual(render.synced_hz(0), 0.0)


class TestAccompagnement(unittest.TestCase):
    """Basse, accords et arpège tirés d'une progression."""

    def setUp(self):
        from delugeapp.core import accomp

        self.accomp = accomp
        self.prog = theory.progression(57, "mineur", "mélancolique", seed=3,
                                       bars=4)

    def test_chaque_genre_a_ses_styles(self):
        for genre in genres.genre_keys():
            chords, bass, _arp = self.accomp.genre_styles(genre)
            with self.subTest(genre=genre):
                self.assertIn(chords, self.accomp.CHORD_STYLES)
                self.assertIn(bass, self.accomp.BASS_STYLES)

    def test_la_basse_tombe_sur_la_fondamentale(self):
        for style in self.accomp.BASS_STYLES:
            notes = self.accomp.bass_part(self.prog, style)
            with self.subTest(style=style):
                self.assertTrue(notes)
                for bar, chord in enumerate(self.prog):
                    premiere = min((e for e in notes
                                    if bar * 16 <= e.start < (bar + 1) * 16),
                                   key=lambda e: e.start)
                    self.assertEqual(premiere.note % 12,
                                     chord["root"] % 12)

    def test_la_basse_contretemps_evite_les_temps(self):
        for style in ("contretemps", "roulante"):
            with self.subTest(style=style):
                debuts = {e.start % 4 for e in self.accomp.bass_part(
                    self.prog, style)}
                self.assertNotIn(0, debuts)

    def test_la_marche_approche_l_accord_suivant(self):
        notes = self.accomp.bass_part(self.prog, "marche")
        for bar in range(len(self.prog) - 1):
            derniere = max((e for e in notes
                            if bar * 16 <= e.start < (bar + 1) * 16),
                           key=lambda e: e.start)
            suivante = self.prog[bar + 1]["bass"]
            self.assertEqual(abs(derniere.note - suivante), 1)

    def test_les_accords_couvrent_chaque_mesure(self):
        notes = self.accomp.chord_part(self.prog, "tenu")
        for bar, chord in enumerate(self.prog):
            dans = sorted(e.note for e in notes if e.start == bar * 16)
            self.assertEqual(dans, sorted(chord["notes"]))

    def test_l_arpege_monte_au_dessus_des_accords(self):
        arp = self.accomp.arp_part(self.prog, "montant", rate=1)
        self.assertEqual(len(arp), 16 * len(self.prog))
        haut_accords = max(n for c in self.prog for n in c["notes"])
        self.assertGreater(min(e.note for e in arp), haut_accords - 12)

    def test_export_midi_multipiste(self):
        parts = self.accomp.accompany(self.prog, genre="synthwave",
                                      arp=True)
        with tempfile.TemporaryDirectory() as tmp:
            chemin = Path(tmp) / "accomp.mid"
            pistes = midifile.parts_to_midi(chemin, parts, 110)
            lu = TestMidiFile._parse(chemin)
        self.assertEqual(pistes, 3)
        noms = [t["name"] for t in lu["tracks"]]
        for nom in ("Accords", "Basse", "Arpège"):
            self.assertIn(nom.replace("è", "e"),
                          [n.replace("è", "e").replace("?", "e")
                           for n in noms if n])
        # Toutes les notes y sont, toutes éteintes (vérifié par l'analyseur).
        total = sum(len(t["notes"]) for t in lu["tracks"])
        self.assertEqual(total, sum(len(v) for v in parts.values()))

    def test_ecoute_de_l_accompagnement(self):
        parts = self.accomp.accompany(self.prog, genre="house")
        sons = {"Accords": synthgen.generate(synthgen.GenOptions(
                    genre="house", role="stab", seed=1)).sound,
                "Basse": synthgen.generate(synthgen.GenOptions(
                    genre="house", role="bass", seed=1)).sound}
        audio = render.render_parts(parts, sons, bpm=120, sr=22050)
        attendu = 4 * 2.0 * 22050                 # quatre mesures à 120
        self.assertGreaterEqual(audio.shape[0], attendu)
        self.assertGreater(float(np.max(np.abs(audio))), 0.05)
        self.assertLessEqual(float(np.max(np.abs(audio))), 0.98 + 1e-6)


class TestRythmesJustes(unittest.TestCase):
    """Motifs, grooves et polyrythmes vérifiés contre leur définition."""

    def test_les_accents_ne_sont_plus_ecretes(self):
        for genre in genres.genre_keys():
            motif = rhythm.genre_beat(genre, bars=1, seed=1)
            with self.subTest(genre=genre):
                vel = [s.velocity for st in motif.tracks.values()
                       for s in st]
                self.assertTrue(all(1 <= v <= 100 for v in vel))
                # Les coups forts restent distincts des faibles.
                self.assertGreater(max(vel), min(vel))

    def test_le_break_amen(self):
        motif = rhythm.genre_beat("jungle", bars=1, seed=1, fills=False)
        self.assertEqual([s.pos for s in motif.tracks["Kick"]],
                         [0, 2, 10, 11])
        self.assertEqual([s.pos for s in motif.tracks["Snare"]],
                         [4, 7, 9, 12, 15])

    def test_le_two_step_de_la_drum_and_bass(self):
        motif = rhythm.genre_beat("dnb", bars=1, seed=1, fills=False)
        self.assertEqual([s.pos for s in motif.tracks["Kick"]], [0, 10])
        self.assertEqual([s.pos for s in motif.tracks["Snare"]], [4, 12])

    def test_polyrythme_exact(self):
        cells = rhythm.polyrhythm(3, 4, 16)
        trois = [round(i * 16 / 3) for i in range(3)]
        quatre = [0, 4, 8, 12]
        self.assertEqual({i for i, c in enumerate(cells) if c},
                         set(trois) | set(quatre))

    def test_swing_mpc(self):
        """58 % : la seconde double-croche tombe à 58 % de la croche."""
        decalage = rhythm.GROOVES["MPC 58 %"][1]
        self.assertAlmostEqual(6 + decalage, 0.58 * 12, places=3)
        self.assertEqual(rhythm.GROOVES["MPC 58 %"][0], 0)
        self.assertEqual(rhythm.deluge_swing("MPC 58 %"), 58)
        self.assertEqual(rhythm.deluge_swing("droit"), 50)
        self.assertIsNone(rhythm.deluge_swing("laid-back"))

    def test_groove_applique_deux_fois_sans_planter(self):
        motif = rhythm.genre_beat("house", bars=1, seed=1)
        une = rhythm.apply_groove(motif, "MPC 62 %")
        deux = rhythm.apply_groove(une, "MPC 62 %")
        self.assertEqual(len(deux.tracks["Kick"]), len(motif.tracks["Kick"]))
        # Depuis le motif droit, le résultat ne cumule pas.
        refait = rhythm.apply_groove(rhythm.straighten(une), "MPC 62 %")
        self.assertEqual([s.pos for s in refait.tracks["Shaker"]],
                         [s.pos for s in une.tracks["Shaker"]])


class TestHabitudesDesPresets(unittest.TestCase):
    """Les traits que le générateur ignorait, recalés sur les 911 presets.

    Mesuré sur la carte (14 octobre 2026) : 33 % des basses ont un
    portamento, 27 à 56 % des presets une saturation, le délai se cale
    surtout à la croche, l'effet de modulation va de 11 % (sons pincés) à
    38 % (arpèges). Le générateur ne posait jamais ni portamento ni
    saturation, calait tout à la double-croche et mettait un effet de
    modulation sur un preset sur trois.
    """

    @staticmethod
    def _sons(genre, role, n=60, **curseurs):
        return [synthgen.generate(synthgen.GenOptions(
            genre=genre, role=role, seed=k, **curseurs)).sound
            for k in range(n)]

    @staticmethod
    def _part(sons, test):
        return sum(1 for s in sons if test(s)) / len(sons)

    def test_portamento_selon_le_role_et_le_genre(self):
        def glisse(son):
            return son.display("portamento") > 0

        acid = self._part(self._sons("acid", "bass"), glisse)
        house = self._part(self._sons("house", "bass"), glisse)
        claviers = self._part(self._sons("techno", "keys"), glisse)
        self.assertGreater(acid, 0.5)
        self.assertGreater(acid, house)
        self.assertGreater(self._part(self._sons("techno", "bass"), glisse),
                           claviers)

    def test_saturation_suit_le_curseur_de_salete(self):
        def sature(son):
            return son.clipping_amount > 0

        propre = self._part(self._sons("techno", "drone", dirt=0.0), sature)
        moyen = self._part(self._sons("techno", "drone"), sature)
        sale = self._part(self._sons("techno", "drone", dirt=1.0), sature)
        self.assertGreater(moyen, 0.25)
        self.assertLess(propre, moyen)
        self.assertLess(moyen, sale)

    def test_delai_a_la_croche_pour_un_lead_a_la_double_pour_une_nappe(self):
        from collections import Counter

        leads = Counter(s.delay_sync_level
                        for s in self._sons("trance", "lead"))
        nappes = Counter(s.delay_sync_level
                         for s in self._sons("trance", "pad"))
        self.assertEqual(leads.most_common(1)[0][0], 6)
        self.assertEqual(nappes.most_common(1)[0][0], 7)

    def test_effet_de_modulation_plus_rare_sur_une_basse(self):
        def module(son):
            return son.mod_fx_type != "none"

        self.assertLess(self._part(self._sons("techno", "bass", n=80), module),
                        self._part(self._sons("techno", "pad", n=80), module))

    def test_la_graine_ne_fait_pas_les_memes_choix_dans_tous_les_genres(self):
        """Avant, la graine 42 tirait le même mode de jeu en techno et en
        house : le genre n'entrait pas dans le tirage."""
        pareils = sum(
            1 for k in range(60)
            if synthgen.generate(synthgen.GenOptions(
                genre="techno", role="bass", seed=k)).sound.polyphonic
            == synthgen.generate(synthgen.GenOptions(
                genre="house", role="bass", seed=k)).sound.polyphonic)
        self.assertLess(pareils, 45)


class TestCouleursDAccords(unittest.TestCase):
    """Septièmes, neuvièmes et suspendus dans les progressions."""

    def test_le_jazz_prend_des_septiemes_sauf_demande_contraire(self):
        prog = theory.progression(57, "mineur", "jazz", seed=2, bars=4)
        self.assertTrue(all(len(c["notes"]) == 4 for c in prog))
        self.assertTrue(all(c["quality"] in ("m7", "maj7", "7", "m7b5")
                            for c in prog))
        triades = theory.progression(57, "mineur", "jazz", seed=2, bars=4,
                                     color="triades")
        self.assertTrue(all(len(c["notes"]) == 3 for c in triades))

    def test_neuvieme_jouee_sans_fondamentale_et_nommee_juste(self):
        full, joue, suffixe = theory.colored_chord(60, "majeur", 0,
                                                   "neuvièmes")
        self.assertEqual(suffixe, "9")
        self.assertEqual(theory.chord_quality(full), "maj9")
        # Mi, sol, si, ré : la fondamentale est laissée à la basse.
        self.assertEqual(sorted(n % 12 for n in joue), [2, 4, 7, 11])
        prog = theory.progression(60, "majeur", "pop", seed=1, bars=4,
                                  color="neuvièmes")
        for accord in prog:
            with self.subTest(accord=accord["name"]):
                self.assertEqual(accord["bass"] % 12, accord["root"] % 12)

    def test_pas_de_neuvieme_mineure(self):
        """Le ii de la mineur (si-ré-fa-la) n'a pas de neuvième : do serait
        à un demi-ton de si. Il reste demi-diminué."""
        full, _joue, suffixe = theory.colored_chord(57, "mineur", 1,
                                                    "neuvièmes")
        self.assertEqual(suffixe, "7")
        self.assertEqual(theory.chord_quality(full), "m7b5")

    def test_pas_de_quarte_augmentee_deguisee_en_sus4(self):
        """Le IV de do (fa) a un si, quarte augmentée : il prend sus2."""
        _full, joue, suffixe = theory.colored_chord(60, "majeur", 3,
                                                    "suspendus")
        self.assertEqual(suffixe, "sus2")
        self.assertEqual(theory.chord_quality(joue), "sus2")

    def test_toutes_les_couleurs_restent_dans_la_gamme(self):
        for color in theory.CHORD_COLORS:
            for scale in ("majeur", "mineur", "dorien"):
                classes = {(62 + i) % 12 for i in theory.SCALES[scale]}
                for amb in theory.progression_names():
                    prog = theory.progression(62, scale, amb, seed=5, bars=8,
                                              color=color)
                    with self.subTest(color=color, scale=scale, amb=amb):
                        self.assertTrue(all(n % 12 in classes
                                            for c in prog for n in c["notes"]))

    def test_une_neuvieme_ne_s_ecrase_pas_en_grappe(self):
        """Jouée avec sa fondamentale, une neuvième met la fondamentale à un
        ton de la neuvième, et la conduite des voix en faisait une grappe de
        secondes (Sol9 joué fa-sol-la-si). Sans fondamentale — la basse la
        tient —, il reste au plus une seconde par accord."""
        for seed in range(12):
            prog = theory.progression(60, "majeur", "pop", seed=seed, bars=8,
                                      color="neuvièmes")
            for c in prog:
                notes = sorted(c["notes"])
                secondes = sum(1 for a, b in zip(notes, notes[1:])
                               if b - a <= 2)
                with self.subTest(graine=seed, accord=c["name"]):
                    self.assertLessEqual(secondes, 1, notes)


class TestMelodie(unittest.TestCase):
    """La mélodie posée sur une progression."""

    def _melodie(self, genre="trance", seed=3, bars=4, scale="mineur",
                 ambiance="pop"):
        prog = theory.progression(57, scale, ambiance, seed=seed, bars=bars)
        return prog, accomp.melody_part(prog, root=57, scale=scale,
                                        genre=genre, seed=seed)

    def test_dans_la_gamme_et_l_accord_sur_les_temps_forts(self):
        classes = {(57 + i) % 12 for i in theory.SCALES["mineur"]}
        for genre in ("ambient", "trance", "house", "lofi"):
            for seed in range(8):
                prog, mel = self._melodie(genre, seed, bars=8)
                for e in mel:
                    accord = prog[int(e.start // 16)]
                    with self.subTest(genre=genre, graine=seed, debut=e.start):
                        self.assertIn(e.note % 12, classes)
                        if e.start % 8 == 0:
                            self.assertIn(e.note % 12,
                                          {n % 12 for n in accord["notes"]}
                                          | {accord["root"] % 12})

    def test_un_motif_repris_et_une_fin_sur_la_fondamentale(self):
        prog, mel = self._melodie("synthwave", seed=5)

        def rythme(mesure):
            return [e.start - 16 * mesure for e in mel
                    if 16 * mesure <= e.start < 16 * (mesure + 1)]

        self.assertEqual(rythme(0), rythme(1))
        self.assertEqual(mel[-1].note % 12, prog[-1]["root"] % 12)
        self.assertGreaterEqual(mel[-1].length, 4)

    def test_un_mouvement_surtout_conjoint(self):
        from statistics import median

        ecarts = []
        for seed in range(20):
            _prog, mel = self._melodie("trance", seed, bars=8)
            ecarts += [abs(b.note - a.note) for a, b in zip(mel, mel[1:])]
        self.assertLessEqual(median(ecarts), 2)
        self.assertLessEqual(max(ecarts), 12)

    def test_l_allure_suit_le_genre(self):
        _p, ambient = self._melodie("ambient", seed=2)
        _p, house = self._melodie("house", seed=2)
        self.assertLess(len(ambient), len(house))

    def test_reproductible_et_renouvelable(self):
        _p, a = self._melodie(seed=4)
        _p, b = self._melodie(seed=4)
        self.assertEqual(a, b)
        prog = theory.progression(57, "mineur", "pop", seed=4, bars=4)
        autres = {tuple(e.note for e in accomp.melody_part(
            prog, root=57, scale="mineur", genre="trance", seed=k))
            for k in range(6)}
        self.assertGreater(len(autres), 1)

    def test_une_piste_de_plus_en_midi(self):
        prog = theory.progression(57, "mineur", "pop", seed=1, bars=4)
        parts = accomp.accompany(prog, genre="trance", melody=True, root=57,
                                 scale="mineur", seed=1)
        self.assertIn("Mélodie", parts)
        with tempfile.TemporaryDirectory() as tmp:
            pistes = midifile.parts_to_midi(Path(tmp) / "m.mid", parts, 138)
        self.assertEqual(pistes, len(parts))
        self.assertEqual(midifile.PART_CHANNELS["Mélodie"], 3)


class TestBatterieSynthetisee(unittest.TestCase):
    """Écouter un rythme sans carte : une boîte à rythmes calculée."""

    @staticmethod
    def _centroide(son):
        spectre = np.abs(np.fft.rfft(son[:, 0], 32768))
        freqs = np.fft.rfftfreq(32768, 1 / 44100)
        return float((spectre * freqs).sum() / spectre.sum())

    def test_chaque_voix_sonne_sans_saturer(self):
        for role in render.SYNTH_DRUM_ROLES:
            son = render.synth_drum(role)
            with self.subTest(role=role):
                self.assertEqual(son.shape[1], 2)
                self.assertGreater(float(np.sqrt((son ** 2).mean())), 0.02)
                self.assertLessEqual(float(np.abs(son).max()), 1.0)
                self.assertTrue(np.all(np.isfinite(son)))

    def test_la_grosse_caisse_est_grave_et_les_charleys_aigus(self):
        kick = self._centroide(render.synth_drum("Kick"))
        caisse = self._centroide(render.synth_drum("Snare"))
        charley = self._centroide(render.synth_drum("HatC"))
        self.assertLess(kick, 500)
        self.assertLess(kick, caisse)
        self.assertLess(caisse, charley)
        toms = [self._centroide(render.synth_drum(t))
                for t in ("TomL", "TomM", "TomH")]
        self.assertEqual(toms, sorted(toms))

    def test_un_motif_boucle_sur_la_duree_demandee(self):
        motif = rhythm.genre_beat("techno", bars=1, seed=1)
        audio = render.render_pattern(motif, bpm=120, bars=4, tail=0.0)
        self.assertAlmostEqual(audio.shape[0] / 44100, 8.0, places=2)
        # La quatrième mesure joue encore : la boucle n'est pas tombée.
        fin = audio[int(6.5 * 44100):int(7.5 * 44100)]
        self.assertGreater(float(np.abs(fin).max()), 0.05)

    def test_une_piste_inconnue_sonne_quand_meme(self):
        motif = rhythm.Pattern(name="E", steps=16)
        for pos in (0, 3, 6, 9, 12):
            motif.add("E(5,16)", rhythm.Step(pos=pos, velocity=90))
        self.assertGreater(float(np.abs(render.render_pattern(motif)).max()),
                           0.05)


class TestVariationsRythmiques(unittest.TestCase):
    """« Motif du genre » donnait toujours le même motif."""

    def test_l_ossature_ne_bouge_jamais(self):
        for genre in genres.genre_keys():
            base = rhythm.genre_beat(genre, bars=2, seed=1)
            for seed in range(6):
                variante = rhythm.variation(base, genre, seed=seed)
                for piste in rhythm.BACKBONE:
                    with self.subTest(genre=genre, graine=seed, piste=piste):
                        self.assertLessEqual(
                            {st.pos for st in base.tracks.get(piste, [])},
                            {st.pos for st in variante.tracks.get(piste, [])})

    def test_une_variation_change_quelque_chose_et_se_rejoue(self):
        base = rhythm.genre_beat("house", bars=1, seed=1)

        def cases(motif):
            return {(t, st.pos) for t, sts in motif.tracks.items()
                    for st in sts}

        a = rhythm.variation(base, "house", seed=4)
        self.assertNotEqual(cases(a), cases(base))
        self.assertEqual(cases(a), cases(rhythm.variation(base, "house",
                                                          seed=4)))
        self.assertTrue(all(0 <= st.pos < a.steps
                            for sts in a.tracks.values() for st in sts))

    def test_pas_de_charleys_serres_sur_un_rythme_clairseme(self):
        """Mesuré : la densité d'un motif dub était multipliée par 4,6."""
        base = rhythm.genre_beat("ambient", bars=1, seed=1)
        for seed in range(12):
            variante = rhythm.variation(base, "ambient", seed=seed,
                                        amount=1.0)
            self.assertNotIn("charleys", variante.name)

    def test_boucler_un_motif(self):
        motif = rhythm.genre_beat("techno", bars=1, seed=1)
        long = rhythm.loop(motif, 3)
        self.assertEqual(long.steps, 48)
        self.assertEqual(len(long.tracks["Kick"]),
                         3 * len(motif.tracks["Kick"]))


class TestBasseAcide(unittest.TestCase):
    """La ligne de 303 : silences, accents, octaves, glissés."""

    def test_notes_de_l_accord_accents_et_glisses(self):
        prog = theory.progression(57, "mineur", "techno", seed=1, bars=4)
        basse = accomp.bass_part(prog, "acide")
        for e in basse:
            accord = prog[int(e.start // 16)]
            permises = {(accord["bass"] + d) % 12 for d in (0, 7)} | {
                n % 12 for n in accord["notes"]}
            with self.subTest(debut=e.start):
                self.assertIn(e.note % 12, permises)
        self.assertTrue(any(e.velocity >= 90 for e in basse))
        self.assertTrue(any(e.velocity < 80 for e in basse))
        glisses = [(a, b) for a, b in zip(basse, basse[1:])
                   if a.start + a.length > b.start]
        self.assertTrue(glisses)
        # Deux notes identiques qui se chevauchent se couperaient en MIDI.
        self.assertTrue(all(a.note != b.note for a, b in glisses))

    def test_l_acid_la_prend_par_defaut(self):
        self.assertEqual(accomp.genre_styles("acid")[1], "acide")


class TestBatterieDansLAccompagnement(unittest.TestCase):

    def test_la_batterie_suit_la_progression_et_part_en_piste_10(self):
        prog = theory.progression(57, "mineur", "pop", seed=1, bars=4)
        parts = accomp.accompany(prog, "house",
                                 drums=rhythm.genre_beat("house", 1, seed=1))
        batterie = parts["Batterie"]
        self.assertGreaterEqual(max(e.start for e in batterie), 48)
        self.assertIn(midifile.GM_DRUMS["Kick"], {e.note for e in batterie})
        with tempfile.TemporaryDirectory() as tmp:
            chemin = Path(tmp) / "b.mid"
            midifile.parts_to_midi(chemin, parts, 124)
            self.assertIn(0x99, chemin.read_bytes())    # note on, canal 10


class TestRemplacementDAccord(unittest.TestCase):

    def test_meme_fonction_dans_la_gamme_et_l_original_intact(self):
        for scale in ("majeur", "mineur"):
            for seed in range(6):
                prog = theory.progression(60, scale, "pop", seed=seed, bars=4)
                copie = [dict(c) for c in prog]
                classes = {(60 + i) % 12 for i in theory.SCALES[scale]}
                for position in range(4):
                    neuve = theory.substitute(prog, position, 60, scale,
                                              seed=position)
                    with self.subTest(scale=scale, graine=seed,
                                      position=position):
                        self.assertEqual(prog, copie)
                        self.assertNotEqual(neuve[position]["degree"],
                                            prog[position]["degree"])
                        self.assertEqual(neuve[position]["function"],
                                         prog[position]["function"])
                        self.assertTrue(all(n % 12 in classes
                                            for n in neuve[position]["notes"]))
                        for autre in range(4):
                            if autre != position:
                                self.assertEqual(neuve[autre]["name"],
                                                 prog[autre]["name"])

    def test_la_fonction_figure_dans_chaque_accord(self):
        prog = theory.progression(60, "majeur", "pop", seed=1, bars=4)
        self.assertTrue(all(c["function"] in ("tonique", "sous-dominante",
                                               "dominante") for c in prog))


class TestEsquisse(unittest.TestCase):
    """Le modèle d'arrangement devient un morceau entier."""

    def _esquisse(self, genre, seed=2):
        prog = sketch.default_progression(genre, seed=seed)
        return sketch.sketch(prog, genre, root=57, scale="mineur", seed=seed)

    def test_chaque_partie_ne_joue_que_dans_ses_sections(self):
        for genre in genres.genre_keys():
            esquisse = self._esquisse(genre)
            self.assertEqual(esquisse.bars, sum(
                b for _n, b in sketch.ARRANGEMENTS[genre]))
            for nom, evenements in esquisse.parts.items():
                for e in evenements:
                    section = next(
                        s for s in esquisse.sections
                        if s.start * 16 <= e.start < (s.start + s.bars) * 16)
                    with self.subTest(genre=genre, partie=nom,
                                      section=section.name):
                        if nom == "Batterie":
                            self.assertTrue({"Batterie", "Batterie légère"}
                                            & set(section.parts))
                        else:
                            self.assertIn(nom, section.parts)

    def test_intro_sans_caisse_claire_cassure_sans_batterie(self):
        esquisse = self._esquisse("techno")
        for section in esquisse.sections:
            debut, fin = section.start * 16, (section.start + section.bars) * 16
            pistes = {t for t, sts in esquisse.drums.tracks.items()
                      if any(debut <= st.pos < fin for st in sts)}
            with self.subTest(section=section.name):
                if section.kind in ("intro", "fin"):
                    self.assertFalse(pistes & {"Snare", "Clap", "Crash"})
                if section.kind == "cassure":
                    self.assertFalse(pistes)
                if section.kind == "pic":
                    self.assertIn(float(debut), {st.pos for st in
                                                 esquisse.drums.tracks["Crash"]})

    def test_un_refrain_final_reste_un_refrain(self):
        self.assertEqual(sketch.section_kind("Refrain final"), "pic")
        self.assertEqual(sketch.section_kind("Final"), "fin")
        self.assertEqual(sketch.section_kind("Pont"), "cassure")

    def test_un_fichier_midi_avec_les_sections_en_reperes(self):
        esquisse = self._esquisse("house")
        with tempfile.TemporaryDirectory() as tmp:
            chemin = Path(tmp) / "e.mid"
            pistes = midifile.parts_to_midi(chemin, esquisse.parts, 124,
                                            markers=esquisse.markers())
            donnees = chemin.read_bytes()
        self.assertEqual(pistes, len(esquisse.parts))
        self.assertIn(b"\xff\x06\x05Intro", donnees)
        self.assertIn(b"Refrain 2", donnees)

    def test_un_extrait_part_de_zero_et_dure_huit_mesures_au_plus(self):
        esquisse = self._esquisse("trance")
        index = next(i for i, s in enumerate(esquisse.sections)
                     if s.kind == "pic")
        parts, batterie, mesures = sketch.excerpt(esquisse, index)
        self.assertEqual(mesures, 8)
        debuts = [e.start for evs in parts.values() for e in evs]
        self.assertGreaterEqual(min(debuts), 0)
        self.assertLess(max(debuts), 8 * 16)
        self.assertLess(max(st.pos for sts in batterie.tracks.values()
                            for st in sts), 8 * 16)


def model_osc(file_name: str, end: int = -1):
    """Oscillateur jouant un fichier, zone en échantillons."""
    from delugeapp.core.model import Osc, Zone

    return Osc(type="sample", file_name=file_name,
               zone=Zone(start=0, end=end, unit="samples"))


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestSongWriter(unittest.TestCase):
    """Morceaux du Deluge écrits depuis les outils de création.

    Le format attendu est celui de la machine (c1.2.1, ``DEFAULT.XML`` et
    ``SONG1.XML`` de la carte) ; les conversions d'époque reproduisent ce
    que le firmware fait en chargeant un preset ancien, vérifié sur les
    instruments des six morceaux c1.2.1 de la carte.
    """

    ROLES = ("Kick", "Snare", "HatC", "HatO", "Clap", "Rim", "Crash",
             "Shaker")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "carte"
        for sub in ("SONGS", "SYNTHS", "KITS"):
            (self.root / sub).mkdir(parents=True)
        t = np.linspace(0, 0.3, 13230, endpoint=False, dtype=np.float32)
        for i, role in enumerate(self.ROLES):
            folder = self.root / "SAMPLES" / "DRUMS" / role
            folder.mkdir(parents=True)
            signal = (0.5 * np.sin(2 * np.pi * (60 + 40 * i) * t)
                      * np.exp(-t * 6)).astype(np.float32)
            wav.write(folder / f"{role} 0.wav", signal, 44100)
        # Comme « 808 Kick.wav » : 22 051 trames, que le TR-808 sans version
        # borne à 501 ms.
        wav.write(self.root / "SAMPLES" / "DRUMS" / "Kick" / "808.wav",
                  np.zeros(22051, dtype=np.float32), 44100)
        self.sd = sdcard.SDCard(self.root)
        self.lib = db.Library(Path(self._tmp.name) / "i.db")
        scan.scan_card(self.sd, self.lib, compute_hash=False)

    def tearDown(self):
        self.lib.close()
        self._tmp.cleanup()

    # -- utilitaires ----------------------------------------------------- #

    @staticmethod
    def _note(pos, length, note=60, velocity=100):
        return accomp.NoteEvent(pos, length, note, velocity)

    def _spec(self, **kwargs):
        from delugeapp.core import songwriter

        preset = SynthPreset.new("BASSE")
        track = songwriter.synth_track(preset)
        clip = songwriter.ClipSpec(track=0, length=songwriter.BAR, rows={
            60: [Note(pos=0, length=96, velocity=100)]}, name="Basse")
        values = dict(name="Essai", bpm=120.0, tracks=[track], clips=[clip])
        values.update(kwargs)
        return songwriter.SongSpec(**values)

    # -- temps ----------------------------------------------------------- #

    def test_le_tempo_s_ecrit_comme_la_machine(self):
        """120 BPM donnent les deux nombres de ``DEFAULT.XML``."""
        from delugeapp.core import songwriter
        from delugeapp.core.model import tempo_from_song_attrs

        self.assertEqual(songwriter.tempo_attrs(120), (229, -1342177280))
        for bpm in (70.5, 124, 128, 174):
            tick, fraction = songwriter.tempo_attrs(bpm)
            with self.subTest(bpm=bpm):
                self.assertAlmostEqual(
                    tempo_from_song_attrs(tick, fraction, 2), bpm, places=2)

    def test_une_double_croche_vaut_24_ticks(self):
        from delugeapp.core import songwriter

        self.assertEqual((songwriter.BAR, songwriter.STEP), (384, 24))
        rows = songwriter.events_to_rows([self._note(4, 2)], 384)
        note = rows[60][0]
        self.assertEqual((note.pos, note.length, note.velocity, note.condition),
                         (96, 48, 127, 20))

    def test_une_note_qui_en_chevauche_une_autre_est_raccourcie(self):
        """Le firmware **ignore** une note qui commence avant la fin de la
        précédente : on raccourcit la première au lieu de perdre la seconde."""
        from delugeapp.core import songwriter

        rows = songwriter.events_to_rows(
            [self._note(0, 4), self._note(2, 4), self._note(2, 1),
             self._note(15, 8)], 384)
        notes = [(n.pos, n.length) for n in rows[60]]
        self.assertEqual(notes, [(0, 48), (48, 96), (360, 24)])

    def test_un_motif_de_douze_pas_tient_dans_une_mesure(self):
        from delugeapp.core import songwriter

        motif = rhythm.Pattern(name="E", steps=12)
        motif.tracks["E(5,12)"] = [rhythm.Step(pos=i) for i in (0, 3, 6)]
        rows, length = songwriter.pattern_rows(motif, {"E(5,12)": 2})
        self.assertEqual(length, 384)
        self.assertEqual([n.pos for n in rows[2]], [0, 96, 192])

    def test_une_partie_qui_se_repete_tient_dans_une_boucle_courte(self):
        from delugeapp.core import songwriter

        quatre = {36: [Note(pos=b * 384, length=96) for b in range(4)]}
        rows, length = songwriter.fold(quatre, 4 * 384)
        self.assertEqual((length, [n.pos for n in rows[36]]), (384, [0]))

        # Une mesure différente des autres : la boucle reste entière.
        inegal = {36: [Note(pos=b * 384, length=96) for b in range(4)]
                  + [Note(pos=3 * 384 + 192, length=24)]}
        self.assertEqual(songwriter.fold(inegal, 4 * 384)[1], 4 * 384)

        # Une note qui déborde de sa mesure ne se replie pas.
        long = {36: [Note(pos=b * 384 + 300, length=200) for b in range(4)]}
        self.assertEqual(songwriter.fold(long, 4 * 384)[1], 4 * 384)

    # -- assemblage ------------------------------------------------------ #

    def _sections_spec(self):
        from delugeapp.core import songwriter

        spec = self._spec()
        spec.tracks.append(songwriter.synth_track(SynthPreset.new("NAPPE")))
        bar = songwriter.BAR
        note = [Note(pos=0, length=96)]
        spec.clips = [
            songwriter.ClipSpec(0, bar, {60: list(note)}, section=0,
                                name="Intro"),
            songwriter.ClipSpec(0, 2 * bar, {60: list(note)}, section=1,
                                playing=False, name="Theme"),
            songwriter.ClipSpec(1, 4 * bar, {64: list(note)}, section=1,
                                playing=False, name="Theme nappe"),
            songwriter.ClipSpec(1, bar, {64: list(note)}, section=2,
                                playing=False, name="Fin"),
        ]
        spec.sections = [songwriter.SectionSpec("Intro", 8 * bar),
                         songwriter.SectionSpec("Thème", 16 * bar),
                         songwriter.SectionSpec("Fin", 4 * bar)]
        return spec

    def test_la_premiere_section_est_en_haut_et_enchaine(self):
        """En disposition « rangées », la machine passe à la section du clip
        d'en dessous : la première section a les index les plus élevés, et
        chaque section se répète sur son plus long clip."""
        from delugeapp.core import songwriter

        root = songwriter.build(self._sections_spec()).root
        clips = list(root.find("sessionClips"))
        self.assertEqual([c.get("clipName") for c in clips],
                         ["Fin", "Theme nappe", "Theme", "Intro"])
        self.assertEqual([c.get("isPlaying") for c in clips],
                         ["0", "0", "0", "1"])
        repeats = {s.get("id"): s.get("numRepeats")
                   for s in root.find("sections")}
        self.assertEqual(len(repeats), 12)
        self.assertEqual([repeats[k] for k in "0123"], ["8", "4", "4", "0"])
        self.assertEqual(root.get("inputTickMagnitude"), "2")
        self.assertEqual(root.get("yScrollSongView"), str(4 - 8))

    def test_l_arrangement_place_les_clips_de_session(self):
        """``clipInstances`` : position, longueur, index du clip de session ;
        une instance plus longue que son clip le fait boucler."""
        from delugeapp.core import songwriter

        root = songwriter.build(self._sections_spec()).root
        bar = songwriter.BAR
        par_nom = {}
        for inst in root.find("instruments"):
            blob = inst.get("clipInstances")[2:]
            par_nom[inst.get("presetName")] = [
                (int(blob[i:i + 8], 16) // bar, int(blob[i + 8:i + 16], 16)
                 // bar, int(blob[i + 16:i + 24], 16))
                for i in range(0, len(blob), 24)]
        self.assertEqual(par_nom["BASSE"], [(0, 8, 3), (8, 16, 2)])
        self.assertEqual(par_nom["NAPPE"], [(8, 16, 1), (24, 4, 0)])
        clips = list(root.find("sessionClips"))
        for nom, instances in par_nom.items():
            for _pos, _len, index in instances:
                self.assertEqual(clips[index].get("instrumentPresetName"),
                                 nom)

    def test_deux_synthes_homonymes_restent_distincts(self):
        """La machine retrouve l'instrument d'un clip par son nom, sans
        tenir compte de la casse : deux homonymes, et le second se tairait."""
        from delugeapp.core import songwriter

        spec = self._spec()
        spec.tracks.append(songwriter.synth_track(SynthPreset.new("basse")))
        spec.clips.append(songwriter.ClipSpec(1, 384, {
            48: [Note(pos=0, length=96)]}, name="Autre"))
        root = songwriter.build(spec).root
        noms = [i.get("presetName") for i in root.find("instruments")]
        self.assertEqual(noms, ["BASSE", "basse 2"])
        self.assertEqual(sorted(c.get("instrumentPresetName")
                                for c in root.find("sessionClips")),
                         ["BASSE", "basse 2"])

    def test_un_instrument_integre_laisse_ses_parametres_au_clip(self):
        """Comme ``DEFAULT.XML`` : ni ``<defaultParams>`` ni ``<arpeggiator>``
        dans l'instrument ; ``<soundParams>`` et l'arpège dans le clip."""
        from delugeapp.core import songwriter

        root = songwriter.build(self._spec()).root
        sound = root.find("instruments/sound")
        self.assertIsNone(sound.find("defaultParams"))
        self.assertIsNone(sound.find("arpeggiator"))
        self.assertIsNone(sound.get("firmwareVersion"))
        self.assertEqual(list(sound.attrib)[:3],
                         ["presetName", "presetFolder", "defaultVelocity"])
        clip = root.find("sessionClips/instrumentClip")
        self.assertIsNotNone(clip.find("soundParams"))
        self.assertEqual(clip.find("arpeggiator").get("arpMode"), "off")
        row = clip.find("noteRows/noteRow")
        # pos 0, longueur 96, vélocité 100 (0x64), lift 64, condition 20.
        self.assertEqual(row.get("noteDataWithLift"),
                         "0x0000000000000060644014")

    def test_le_kit_d_un_morceau_a_une_rangee_par_son(self):
        """Chaque son du kit a sa rangée dans le clip, avec ses réglages en
        ``<soundParams>`` ; les réglages du kit vont dans ``<kitParams>``."""
        from delugeapp.core import songwriter

        kit = Kit.new("KIT")
        kit.add_row("KICK", "SAMPLES/DRUMS/Kick/Kick 0.wav")
        kit.add_row("SNARE", "SAMPLES/DRUMS/Snare/Snare 0.wav")
        track = songwriter.kit_track(kit)
        spec = songwriter.SongSpec(name="K", tracks=[track], clips=[
            songwriter.ClipSpec(0, 384, {1: [Note(pos=96, length=24)]})])
        root = songwriter.build(spec).root
        body = root.find("instruments/kit")
        self.assertIsNone(body.find("defaultParams"))
        drums = list(body.find("soundSources"))
        self.assertEqual([d.get("name") for d in drums], ["KICK", "SNARE"])
        self.assertTrue(all(d.find("defaultParams") is None for d in drums))
        clip = root.find("sessionClips/instrumentClip")
        self.assertIsNotNone(clip.find("kitParams"))
        rows = list(clip.find("noteRows"))
        self.assertEqual([r.get("drumIndex") for r in rows], ["0", "1"])
        self.assertIsNone(rows[0].get("noteDataWithLift"))
        self.assertTrue(rows[1].get("noteDataWithLift"))
        self.assertTrue(all(r.find("soundParams") is not None for r in rows))

    def test_une_note_hors_gamme_coupe_le_mode_gamme(self):
        """Un clip « dans la gamme » ne montre que les notes de la gamme :
        une note étrangère y serait invisible."""
        from delugeapp.core import songwriter

        dans = self._spec(root=0, mode_notes=(0, 2, 4, 5, 7, 9, 11))
        hors = self._spec(root=0, mode_notes=(0, 2, 4, 5, 7, 9, 11))
        hors.clips[0].rows[61] = [Note(pos=192, length=24)]
        self.assertEqual(songwriter.build(dans).root.find(
            "sessionClips/instrumentClip").get("inKeyMode"), "1")
        self.assertEqual(songwriter.build(hors).root.find(
            "sessionClips/instrumentClip").get("inKeyMode"), "0")

    # -- conversions d'époque ------------------------------------------- #

    def _ancien_son(self, version="3.1.5", mode="subtractive"):
        import xml.etree.ElementTree as ET

        el = ET.fromstring(
            '<sound firmwareVersion="%s" earliestCompatibleFirmware="3.1.0"'
            ' polyphonic="poly" mode="%s" lpfMode="24dB">'
            '<osc1 type="saw" /><osc2 type="square" />'
            '<arpeggiator mode="both" numOctaves="2" syncLevel="7" />'
            '<compressor syncLevel="6" attack="327244" release="936" />'
            '<defaultParams volume="0x50000000" lpfFrequency="0x10000000"'
            ' lpfResonance="0x40000000">'
            '<patchCables><patchCable source="velocity"'
            ' destination="lpfFrequency" amount="0x11800000" />'
            '<patchCable source="lfo1" destination="pitch"'
            ' amount="0x03D70A3C" /></patchCables>'
            '</defaultParams></sound>' % (version, mode))
        return el

    def test_un_preset_ancien_est_mis_a_niveau(self):
        """3.1.5 dans un morceau c1.2.1 : ancien mode d'arpège éclaté,
        câbles d'expression ajoutés (comme TB01 dans ``DEFAULT.XML``),
        version retirée, ancien compresseur renommé."""
        from delugeapp.core import songwriter

        track = songwriter.synth_track(self._ancien_son(), version="3.1.5")
        self.assertEqual((track.arp["arpMode"], track.arp["noteMode"],
                          track.arp["octaveMode"]), ("arp", "up", "alt"))
        self.assertIsNone(track.body.get("firmwareVersion"))
        self.assertIsNotNone(track.body.find("sidechain"))
        self.assertIsNone(track.body.find("compressor"))
        cables = [(c.get("source"), c.get("destination"), c.get("amount"))
                  for c in track.params.find("patchCables")]
        # Rangés comme la machine les réécrit : groupés par destination.
        self.assertEqual(cables, [
            ("velocity", "lpfFrequency", "0x11800000"),
            ("y", "lpfFrequency", "0x19999990"),
            ("lfo1", "pitch", "0x03D70A3C"),
            ("aftertouch", "volume", "0x2A3D7094")])

    def test_un_preset_recent_n_est_pas_converti(self):
        from delugeapp.core import songwriter

        track = songwriter.synth_track(self._ancien_son("c1.2.1"),
                                       version="c1.2.1")
        # L'ancien ``mode`` n'est plus lu par c1.2 : l'arpège reste éteint.
        self.assertEqual(track.arp["arpMode"], "off")
        sources = [c.get("source") for c in track.params.find("patchCables")]
        self.assertEqual(sources, ["velocity", "lfo1"])

    def test_un_son_fm_ancien_perd_ses_filtres(self):
        """Avant c1.2.0, un son FM gardait un mode de filtre qu'il ne jouait
        pas : la machine le coupe en le chargeant."""
        from delugeapp.core import songwriter

        track = songwriter.synth_track(self._ancien_son("c1.1.0", "fm"),
                                       version="c1.1.0")
        self.assertEqual((track.body.get("lpfMode"),
                          track.body.get("hpfMode")), ("off", "off"))
        cables = {(c.get("source"), c.get("destination"))
                  for c in track.params.find("patchCables")}
        self.assertNotIn(("y", "modulator1Volume"), cables)

    def test_la_synchro_de_l_arpege_passe_en_valeur_interne(self):
        """Le clip garde la valeur interne : TB01 écrit 7, ``DEFAULT.XML``
        porte 6 dans son clip."""
        from delugeapp.core import songwriter

        self.assertEqual(songwriter.synth_track(
            self._ancien_son(), version="3.1.5").arp["syncLevel"], "6")
        son = self._ancien_son()
        son.find("arpeggiator").set("syncLevel", "0")
        self.assertEqual(songwriter.synth_track(
            son, version="3.1.5").arp["syncLevel"], "0")

    def test_une_version_cachee_dans_un_son_est_retiree(self):
        """Laissée dans le morceau, elle changerait la version de lecture de
        tout ce qui suit."""
        import xml.etree.ElementTree as ET

        from delugeapp.core import songwriter

        kit = ET.fromstring(
            '<kit firmwareVersion="2.0.0"><firmwareVersion>2.0.0'
            '</firmwareVersion><earliestCompatibleFirmware>2.0.0'
            '</earliestCompatibleFirmware><soundSources>'
            '<sound firmwareVersion="2.0.0"><name>A</name>'
            '<firmwareVersion>2.0.0</firmwareVersion><osc1><type>square'
            '</type></osc1></sound></soundSources></kit>')
        track = songwriter.kit_track(kit, version="3.0.0")
        texte = ET.tostring(track.body, encoding="unicode")
        self.assertNotIn("firmwareVersion", texte)
        songwriter.upgrade_kit(kit, "3.0.0")
        texte = ET.tostring(kit, encoding="unicode")
        self.assertNotIn("firmwareVersion", texte)
        self.assertNotIn("earliestCompatibleFirmware", texte)

    def _kit_sans_version(self):
        """Un kit au format 2.x, sans version, comme ``000 TR-808.XML``."""
        import xml.etree.ElementTree as ET

        return ET.fromstring(
            '<kit><lpfMode>24dB</lpfMode><modFXType>flanger</modFXType>'
            '<defaultParams><volume>0x3504F334</volume>'
            '<lpf><frequency>0x7FFFFFFF</frequency>'
            '<resonance>0x00000000</resonance></lpf>'
            '<hpf><frequency>0x80000000</frequency>'
            '<resonance>0xC0000000</resonance></hpf></defaultParams>'
            '<soundSources><sound><name>KICK</name>'
            '<osc1><type>sample</type><reversed>0</reversed>'
            '<fileName>SAMPLES/DRUMS/Kick/808.wav</fileName>'
            '<zone><startMilliseconds>10</startMilliseconds>'
            '<endMilliseconds>501</endMilliseconds></zone></osc1>'
            '<osc2><type>sample</type><fileName></fileName>'
            '<zone><startMilliseconds>0</startMilliseconds>'
            '<endMilliseconds>9999999</endMilliseconds></zone></osc2>'
            '<polyphonic>2</polyphonic><mode>subtractive</mode>'
            '<defaultParams><volume>0x3851EB64</volume>'
            '<lpfFrequency>0x7FFFFFFF</lpfFrequency>'
            '<lpfResonance>0x00000000</lpfResonance>'
            '<patchCables><patchCable><source>velocity</source>'
            '<destination>volume</destination><amount>0x3FFFFFE8</amount>'
            '</patchCable></patchCables></defaultParams>'
            '<arpeggiator><mode>off</mode><numOctaves>2</numOctaves>'
            '<syncLevel>7</syncLevel></arpeggiator>'
            '</sound></soundSources></kit>')

    def test_un_kit_sans_version_recoit_les_conversions_de_la_machine(self):
        """Mesuré sur ``SONG1.XML``, qui intègre le TR-808 sans version :
        bornes converties en trames (501 ms -> les 22 051 trames du fichier,
        à 45 trames près), résonance à mi-course ramenée à zéro quand le
        filtre est ouvert, câbles d'expression, polyphonie en clair."""
        from delugeapp.core import songwriter

        track = songwriter.kit_track(self._kit_sans_version(), version="",
                                     sd=self.sd)
        drum = track.body.find("soundSources/sound")
        zone = drum.find("osc1/zone")
        self.assertEqual((zone.get("startSamplePos"),
                          zone.get("endSamplePos")), ("441", "22051"))
        self.assertIsNone(zone.find("startMilliseconds"))
        vide = drum.find("osc2/zone")
        self.assertEqual((vide.get("startSamplePos"),
                          vide.get("endSamplePos")), ("0", "0"))
        self.assertEqual(drum.find("polyphonic").text, "choke")
        self.assertEqual(drum.find("arpeggiator").get("arpMode"), "off")
        params = track.drum_params[0]
        self.assertEqual(params.find("lpfResonance").text, "0x80000000")
        self.assertEqual(params.find("volume").text, "0x3851EB64")
        sources = [c.get("source") or c.find("source").text
                   for c in params.find("patchCables")]
        self.assertEqual(sources, ["velocity", "aftertouch", "y"])
        # Le kit : passe-bas ouvert, résonance à mi-course -> zéro ; le
        # passe-haut garde la sienne (le firmware teste le passe-bas).
        self.assertEqual(track.params.find("lpf/resonance").text,
                         "0x80000000")
        self.assertEqual(track.params.find("hpf/resonance").text,
                         "0xC0000000")
        self.assertEqual(track.unconverted, [])

    def test_un_kit_ancien_de_la_carte_est_converti_avant_d_etre_complete(self):
        """L'atelier complète un kit de la carte de rangées neuves : converti
        après, le kit complété aurait vu ces rangées « converties » comme si
        elles venaient d'un firmware 2.x. ``current_kit`` convertit d'abord,
        et rend un kit au niveau c1.2.1 ; l'original ne bouge pas."""
        import xml.etree.ElementTree as ET

        from delugeapp.core import songwriter
        from delugeapp.core.model import Kit

        chemin = self.root / "KITS" / "VIEUX.XML"
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text('<?xml version="1.0" encoding="UTF-8"?>'
                          + ET.tostring(self._kit_sans_version(),
                                        encoding="unicode"), encoding="utf-8")
        ancien = Kit.load(chemin)
        avant = ET.tostring(ancien.doc.root, encoding="unicode")
        neuf = songwriter.current_kit(ancien, self.sd)
        self.assertIsNot(neuf, ancien)
        self.assertEqual(ET.tostring(ancien.doc.root, encoding="unicode"),
                         avant, "le kit d'origine a changé")
        self.assertEqual(neuf.doc.firmware, songwriter.FIRMWARE)
        # Déjà au niveau : rendu tel quel, et complété sans autre conversion.
        self.assertIs(songwriter.current_kit(neuf, self.sd), neuf)
        neuf.add_row("SNARE", "SAMPLES/DRUMS/Kick/808.wav", frames=22051)
        track = songwriter.kit_track(neuf, sd=self.sd)
        kick, caisse = track.body.find("soundSources")
        zone = kick.find("osc1/zone")
        self.assertEqual((zone.get("startSamplePos"),
                          zone.get("endSamplePos")), ("441", "22051"))
        self.assertIsNone(zone.find("startMilliseconds"))
        # La machine lit indifféremment l'attribut ou le sous-élément.
        self.assertEqual(kick.get("polyphonic")
                         or kick.findtext("polyphonic"), "choke")
        self.assertEqual(caisse.find("osc1/zone").get("endSamplePos"),
                         "22051")
        # Un kit généré, sans fichier d'origine, passe tel quel.
        genere = Kit.new("GENERE")
        self.assertIs(songwriter.current_kit(genere, self.sd), genere)

    def test_la_compensation_de_resonance_suit_le_firmware(self):
        """``oldResonanceCompensation`` : 8 dB à résonance nulle, 2,7 dB au
        quart, plus rien dès la mi-course ; ``shiftVolumeByDB`` repart du bas
        de l'intervalle, défaut du firmware compris."""
        from delugeapp.core import songwriter

        db = songwriter._resonance_compensation_db
        self.assertAlmostEqual(db(-(1 << 31)), 8.0, places=4)
        self.assertAlmostEqual(db(-(1 << 30)), 2764 / 1024.0, places=4)
        self.assertEqual(db(0), 0.0)
        # Volume dans l'intervalle 11 (1,5 dB) : +1 dB y reste, aux deux
        # tiers ; +2 dB passe dans l'intervalle 12 (1,4 dB), à 0,5/1,4.
        shift = songwriter._shift_volume_db
        self.assertEqual(shift(0x3851EB64, 1.0) + (1 << 31),
                         (11 << 28) + 178956976)
        self.assertEqual(shift(0x3851EB64, 2.0) + (1 << 31),
                         (12 << 28) + 95869808)
        self.assertEqual(shift(-(1 << 31), 3.0), -(1 << 31))

    def test_les_versions_se_rangent_comme_dans_le_firmware(self):
        from delugeapp.core import songwriter

        older = songwriter._older
        self.assertTrue(older("", "1.2.0"))
        self.assertTrue(older("3.1.5", "4.0.0-beta"))
        self.assertTrue(older("4.0.0-beta", "4.0.0"))
        self.assertTrue(older("4.1.0", "c1.0.0"))
        self.assertFalse(older("c1.2.1", "c1.2.0"))
        self.assertTrue(older("c1.1.0", "c1.2.0"))

    # -- écriture -------------------------------------------------------- #

    def test_simuler_n_ecrit_rien(self):
        from delugeapp.core import songwriter

        avant = sorted(p.name for p in (self.root / "SONGS").iterdir())
        plan = songwriter.write_song(self.sd, self._spec())
        self.assertTrue(plan.ok)
        self.assertFalse(plan.applied)
        self.assertEqual(plan.rel, "SONGS/Essai.XML")
        self.assertIn("Nouveau fichier : SONGS/Essai.XML", plan.text())
        self.assertEqual(sorted(p.name for p in
                                (self.root / "SONGS").iterdir()), avant)

    def test_un_nom_pris_est_numerote_et_rien_n_est_remplace(self):
        from delugeapp.core import songwriter

        ancien = self.root / "SONGS" / "ESSAI.XML"
        ancien.write_bytes(b"<song />")
        fait = songwriter.write_song(self.sd, self._spec(), apply=True)
        self.assertEqual(fait.rel, "SONGS/Essai 2.XML")
        self.assertTrue(fait.applied)
        self.assertEqual(ancien.read_bytes(), b"<song />")
        # DEFAULT.XML est le morceau de départ de la machine : jamais ce nom.
        self.assertEqual(songwriter.free_song_name(self.sd, "default"),
                         "SONGS/default 2.XML")
        # Un nom déjà numéroté continue sa suite : « Essai 3 », pas
        # « Essai 2 2 » (vu dans le journal de l'utilisateur).
        self.assertEqual(songwriter.free_song_name(self.sd, "Essai 2"),
                         "SONGS/Essai 3.XML")
        self.assertEqual(songwriter.free_song_name(self.sd, "SONG1"),
                         "SONGS/SONG1.XML")

    def test_le_morceau_ecrit_se_relit(self):
        from delugeapp.core import songwriter

        fait = songwriter.write_song(self.sd, self._spec(bpm=124),
                                     apply=True)
        song = Song.load(self.sd.abs(fait.rel))
        self.assertEqual((song.firmware, song.input_tick_magnitude),
                         ("c1.2.1", 2))
        self.assertAlmostEqual(song.tempo_bpm, 124.0, places=2)
        self.assertEqual(song.stats()["clips"], 1)
        self.assertEqual(song.clips[0].bars, 1.0)
        self.assertEqual(song.clips[0].note_rows[0].notes[0].length, 96)
        self.assertEqual(len(song.preview), 144 * 6)

    def test_un_echantillon_absent_est_annonce(self):
        from delugeapp.core import songwriter

        kit = Kit.new("KIT")
        kit.add_row("KICK", "SAMPLES/DRUMS/Kick/Kick 0.wav")
        kit.add_row("FANTOME", "SAMPLES/ABSENT/x.wav")
        spec = songwriter.SongSpec(
            name="K", tracks=[songwriter.kit_track(kit)],
            clips=[songwriter.ClipSpec(0, 384, {0: [Note(pos=0)]})])
        plan = songwriter.write_song(self.sd, spec)
        self.assertEqual(plan.missing, ["SAMPLES/ABSENT/x.wav"])
        self.assertIn("1 échantillon(s) absent(s)", plan.text())

    # -- recettes -------------------------------------------------------- #

    def test_les_sons_des_parties_ont_l_arpegiateur_eteint(self):
        """L'arpège est écrit note par note : celui de la machine, qui lit
        ``arpMode``, doit rester éteint."""
        from delugeapp.core import songwriter

        parts = {"Arpège": [self._note(0, 1)], "Accords": [self._note(0, 16)]}
        for genre in ("trance", "psytrance", "berlin_school"):
            for name, preset in songwriter.part_presets(parts, genre).items():
                with self.subTest(genre=genre, partie=name):
                    self.assertFalse(preset.sound.arp.is_on)

    def test_une_progression_devient_un_morceau(self):
        from delugeapp.core import songwriter

        prog = theory.progression(57, "mineur", "techno", bars=4, seed=1)
        beat = rhythm.genre_beat("techno", bars=1, seed=1, fills=False)
        parts = accomp.accompany(prog, genre="techno", root=57,
                                 scale="mineur", seed=1)
        drums = rhythm.loop(beat, 4)
        kit, rows, perdus = songwriter.drum_kit_for(self.sd, self.lib,
                                                    "techno", drums.tracks)
        self.assertEqual(perdus, [])
        spec = songwriter.progression_song(
            parts, name="P", bpm=124, genre="techno", root=57,
            scale="mineur", drums=drums, kit=kit, row_map=rows)
        noms = [c.name for c in spec.clips]
        self.assertEqual(noms, ["Accords", "Basse", "Batterie"])
        self.assertEqual(spec.clips[-1].length, 384,
                         "la batterie d'une mesure doit boucler")
        self.assertEqual((spec.root, spec.mode_notes),
                         (9, (0, 2, 3, 5, 7, 8, 10)))
        self.assertTrue(all(c.playing for c in spec.clips))

    def test_une_piste_euclidienne_recoit_une_percussion(self):
        from delugeapp.core import songwriter

        motif = rhythm.Pattern(name="M", steps=16)
        motif.tracks["Kick"] = [rhythm.Step(pos=0), rhythm.Step(pos=8)]
        motif.tracks["E(5,16)"] = [rhythm.Step(pos=i) for i in (0, 3, 6)]
        kit, rows, perdus = songwriter.drum_kit_for(self.sd, self.lib,
                                                    "techno", motif.tracks)
        self.assertEqual(perdus, [])
        self.assertEqual(set(rows), {"Kick", "E(5,16)"})
        self.assertNotEqual(rows["Kick"], rows["E(5,16)"])
        spec = songwriter.pattern_song(motif, kit, rows, name="M", bpm=120)
        self.assertEqual(sum(len(n) for n in spec.clips[0].rows.values()), 5)

    def test_le_kit_de_l_ecoute_n_est_pas_modifie(self):
        from delugeapp.core import songwriter

        base = kitgen.build_kit(self.sd, self.lib, "ECOUTE", genre="techno",
                                seed=1, slots=["Kick"])
        avant = len(base.rows)
        kit, rows, _perdus = songwriter.drum_kit_for(
            self.sd, self.lib, "techno", ["Kick", "Rim"], base=base)
        self.assertEqual(len(base.rows), avant)
        self.assertEqual(len(kit.rows), avant + 1)

    def test_une_esquisse_devient_un_morceau_a_sections(self):
        from delugeapp.core import songwriter

        prog = sketch.default_progression("techno", seed=1)
        result = sketch.sketch(prog, genre="techno", root=57, scale="mineur",
                               seed=1)
        kit, rows, _p = songwriter.drum_kit_for(self.sd, self.lib, "techno",
                                                result.drums.tracks)
        spec = songwriter.sketch_song(result, name="S", bpm=128,
                                      genre="techno", root=57,
                                      scale="mineur", kit=kit, row_map=rows)
        self.assertEqual([s.name for s in spec.sections],
                         [s.name for s in result.sections])
        self.assertEqual(sum(s.length for s in spec.sections),
                         result.bars * songwriter.BAR)
        joues = {c.section for c in spec.clips if c.playing}
        self.assertEqual(joues, {0})
        # L'intro tient en boucles courtes : accords et batterie légère.
        intro = [c for c in spec.clips if c.section == 0]
        self.assertTrue(all(c.length <= 4 * songwriter.BAR for c in intro))
        doc = songwriter.build(spec)
        repeats = [int(s.get("numRepeats")) for s in doc.root.find("sections")]
        self.assertEqual(repeats[0], 16 // 4)

    def test_un_preset_garde_son_arpegiateur(self):
        """S'il est allumé, la phrase devient des accords tenus, que la
        machine arpège elle-même."""
        from delugeapp.core import songwriter

        preset = SynthPreset.new("ARP")
        preset.sound.arp.arp_mode = "arp"
        preset.sound.arp.mode = "up"
        spec = songwriter.preset_song(preset, name="A", bpm=120,
                                      genre="trance", role="pluck")
        self.assertEqual(spec.clips[0].name, "Accords")
        self.assertEqual(spec.tracks[0].arp["arpMode"], "arp")
        basse = songwriter.preset_song(SynthPreset.new("B"), name="B",
                                       bpm=120, genre="techno", role="bass")
        self.assertEqual(basse.clips[0].name, "Basse")
        self.assertEqual(basse.tracks[0].arp["arpMode"], "off")

    def test_une_boucle_decoupee_se_rejoue_a_sa_place(self):
        from delugeapp.core import slicer, songwriter

        tranches = slicer.SliceSet(
            rel="SAMPLES/DRUMS/Kick/808.wav", sr=44100, frames=88200,
            slices=[slicer.Slice(i * 22050, (i + 1) * 22050)
                    for i in range(4)], bpm=120.0)
        spec = songwriter.slices_song(tranches, name="B")
        self.assertEqual(spec.clips[0].length, 384)
        self.assertEqual([spec.clips[0].rows[i][0].pos for i in range(4)],
                         [0, 96, 192, 288])
        self.assertEqual(len(spec.tracks[0].drum_params), 4)
        # Tempo inconnu : celui qui fait tenir la boucle en mesures entières.
        self.assertEqual(songwriter.loop_tempo(2.0), 120.0)
        self.assertEqual(songwriter.loop_tempo(1.6), 150.0)
        self.assertEqual(songwriter.loop_tempo(0), 120.0)


class TestVoixMaximales(unittest.TestCase):
    """``maxVoices`` : la machine écrit 8 pour tous ses sons."""

    def test_un_son_genere_garde_huit_voix_meme_en_legato(self):
        """Mesuré : les 94 ``maxVoices`` des morceaux de la carte valent 8,
        legato et auto compris ; 0 serait un plafond de zéro voix."""
        vus = set()
        for seed in range(40):
            preset = synthgen.generate(synthgen.GenOptions(
                genre="acid", role="bass", seed=seed))
            vus.add(preset.sound.polyphonic)
            self.assertEqual(preset.sound.max_voices, 8)
        self.assertGreater(len(vus), 1, "aucun son non polyphonique tiré")

    def test_un_ancien_zero_redevient_huit_dans_un_morceau(self):
        import xml.etree.ElementTree as ET

        from delugeapp.core import songwriter

        son = ET.fromstring('<sound polyphonic="legato" maxVoices="0">'
                            '<osc1 type="saw" /></sound>')
        track = songwriter.synth_track(son, version="c1.2.1")
        self.assertEqual(track.body.get("maxVoices"), "8")


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


def _son(chemin, frequence=220.0, duree=0.05, profondeur=16, canaux=1,
         taux=44100):
    """Un son court, écrit par l'écrivain de l'application."""
    t = np.linspace(0, duree, int(taux * duree), endpoint=False)
    signal = (0.5 * np.sin(2 * np.pi * frequence * t)).astype(np.float32)
    if canaux > 1:
        signal = np.stack([signal] * canaux, axis=1)
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    wav.write(chemin, signal, taux, profondeur)
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


class TestPontDaw(unittest.TestCase):
    """Le pont entre le Deluge et les DAW : ``daw`` (vers le DAW) et
    ``dawimport`` (depuis le DAW), sur une carte factice."""

    ROLES = ("Kick", "Snare", "HatC", "HatO", "Clap")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.root = self.base / "carte"
        for sub in ("SONGS", "SYNTHS", "KITS"):
            (self.root / sub).mkdir(parents=True)
        t = np.linspace(0, 0.2, 8820, endpoint=False, dtype=np.float32)
        for i, role in enumerate(self.ROLES):
            folder = self.root / "SAMPLES" / "DRUMS" / role
            folder.mkdir(parents=True)
            signal = (0.5 * np.sin(2 * np.pi * (60 + 40 * i) * t)
                      * np.exp(-t * 8)).astype(np.float32)
            wav.write(folder / f"{role} 0.wav", signal, 44100)
        self.sd = sdcard.SDCard(self.root)
        self.lib = db.Library(self.base / "i.db")
        scan.scan_card(self.sd, self.lib, compute_hash=False)

    def tearDown(self):
        self.lib.close()
        self._tmp.cleanup()

    # -- utilitaires ----------------------------------------------------- #

    def _morceau(self) -> Path:
        """Un morceau du Deluge : une basse et une batterie, deux sections."""
        from delugeapp.core import songwriter as sw

        kit = kitgen.build_kit(self.sd, self.lib, "KIT", seed=1,
                               slots=["Kick", "Snare", "HatC"])
        basse = sw.synth_track(SynthPreset.new("BASSE"))
        batterie = sw.kit_track(kit)
        clips = [
            sw.ClipSpec(track=0, length=sw.BAR, section=0, rows={
                40: [Note(pos=0, length=96, velocity=100),
                     Note(pos=192, length=48, velocity=90)]}),
            sw.ClipSpec(track=0, length=2 * sw.BAR, section=1, rows={
                43: [Note(pos=0, length=384, velocity=110)]}),
            sw.ClipSpec(track=1, length=sw.BAR, section=0, rows={
                0: [Note(pos=p, length=24, velocity=100)
                    for p in (0, 192)],
                2: [Note(pos=p, length=12, velocity=80)
                    for p in range(0, 384, 48)]}),
            sw.ClipSpec(track=1, length=sw.BAR, section=1, rows={
                1: [Note(pos=96, length=24, velocity=100)]}),
        ]
        spec = sw.SongSpec(name="Pont", bpm=126.0, tracks=[basse, batterie],
                           clips=clips, sections=[
                               sw.SectionSpec("A", 2 * sw.BAR),
                               sw.SectionSpec("B", 2 * sw.BAR)])
        fait = sw.write_song(self.sd, spec, apply=True)
        self.assertTrue(fait.applied, fait.error)
        return self.root / fait.rel

    @staticmethod
    def _deroule(track):
        from delugeapp.core.daw import _expanded

        return sorted((round(d, 4), n.pitch, round(n.length, 4), n.velocity)
                      for d, n in _expanded(track))

    def _set_ableton(self, live8: bool = False) -> Path:
        """Un set Live réduit à ce que l'import lit, comme Live l'écrit."""
        import gzip

        maitre = "MasterTrack" if live8 else "MainTrack"
        maitre = ("<%s><DeviceChain><Mixer><Tempo><Manual Value=\"97\" />"
                  "</Tempo></Mixer></DeviceChain></%s>" % (maitre, maitre))
        if live8:
            scenes = ('<SceneNames><Scene Id="0" Value=" Couplet" />'
                      '<Scene Id="1" Value="" />'
                      '<Scene Id="2" Value="Refrain" /></SceneNames>')
        else:
            scenes = ('<Scenes><Scene Id="0"><Name Value="Couplet" /></Scene>'
                      '<Scene Id="1"><Name Value="" /></Scene>'
                      '<Scene Id="2"><Name Value="Refrain" /></Scene>'
                      "</Scenes>")

        def clip(debut, fin, notes, nom=""):
            pistes = "".join(
                '<KeyTrack Id="%d"><Notes>%s</Notes><MidiKey Value="%d" />'
                "</KeyTrack>" % (i, "".join(
                    '<MidiNoteEvent Time="%s" Duration="%s" Velocity="%s" '
                    'IsEnabled="true" />' % (t, d, v) for t, d, v in evs), p)
                for i, (p, evs) in enumerate(notes.items()))
            return ('<MidiClip Id="0" Time="%s"><CurrentStart Value="%s" />'
                    '<CurrentEnd Value="%s" /><Loop><LoopStart Value="0" />'
                    '<LoopEnd Value="4" /><StartRelative Value="0" />'
                    '<LoopOn Value="true" /></Loop><Name Value="%s" />'
                    "<Notes><KeyTracks>%s</KeyTracks></Notes></MidiClip>"
                    % (debut, debut, fin, nom, pistes))

        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Ableton MajorVersion="5" MinorVersion="12.0_12043">'
            "<LiveSet><Tracks>"
            '<MidiTrack Id="8"><Name><EffectiveName Value="1-MIDI" />'
            '<UserName Value="Basse" /></Name><DeviceChain><MainSequencer>'
            "<ClipSlotList>"
            '<ClipSlot Id="0"><ClipSlot><Value>'
            + clip(0, 4, {40: [(0, 1, 100)]}, "Intro") +
            "</Value></ClipSlot></ClipSlot>"
            '<ClipSlot Id="1"><ClipSlot><Value /></ClipSlot></ClipSlot>'
            '<ClipSlot Id="2"><ClipSlot><Value>'
            + clip(0, 4, {45: [(0, 2, 90), (2, 2, 90)]}) +
            "</Value></ClipSlot></ClipSlot>"
            "</ClipSlotList><ClipTimeable><ArrangerAutomation><Events>"
            # Huit noires d'une boucle de quatre ; la note à 5 est hors de la
            # boucle : Live ne la joue pas.
            + clip(8, 16, {43: [(0, 1, 100), (5, 1, 100)]}) +
            "</Events></ArrangerAutomation></ClipTimeable>"
            "</MainSequencer></DeviceChain></MidiTrack>"
            '<AudioTrack Id="9" />'
            "</Tracks>" + maitre + scenes +
            '<Locators><Locators><Locator Id="0"><Time Value="8" />'
            '<Name Value="Pont" /></Locator></Locators></Locators>'
            "</LiveSet></Ableton>")
        chemin = self.base / ("live8.als" if live8 else "set.als")
        with gzip.open(chemin, "wb") as f:
            f.write(xml.encode("utf-8"))
        return chemin

    # -- vers le DAW ----------------------------------------------------- #

    def test_un_morceau_du_deluge_devient_un_modele_commun(self):
        from delugeapp.core import daw

        song = daw.from_deluge(self._morceau())
        self.assertEqual(song.bpm, 126.0)
        self.assertEqual([t.kind for t in song.tracks], ["synth", "kit"])
        self.assertEqual(len(song.scenes), 2)
        kit = song.tracks[1]
        self.assertEqual(kit.channel, 9)
        # La grosse caisse sur 36, la caisse claire sur 38 : General MIDI.
        self.assertLessEqual({36, 38}, set(kit.drums))
        # Deux sections de deux mesures : seize noires.
        self.assertEqual(song.length, 16.0)

    def test_l_ordre_des_clips_suit_la_page_morceaux(self):
        """La page Morceaux liste ``Song.clips + Song.arrangement_clips`` ;
        chaque ligne doit retrouver son clip pour l'écouter."""
        from delugeapp.core import daw

        chemin = self._morceau()
        song = daw.from_deluge(chemin)
        modele = Song.load(chemin)
        lignes = modele.clips + modele.arrangement_clips
        self.assertEqual(len(song.clip_order), len(lignes))
        for clip, (piste, indice) in zip(lignes, song.clip_order):
            self.assertEqual(len(song.tracks[piste].clips[indice].notes),
                             clip.note_count)

    def test_un_clip_s_ecoute_sur_toute_sa_boucle(self):
        from delugeapp.core import daw

        song = daw.from_deluge(self._morceau())
        piste, indice = song.clip_order[1]          # la basse, deux mesures
        audio = daw.render_clip(song, piste, indice, self.sd)
        self.assertEqual(audio.shape[0], round(song.seconds(8.0) * 44100))
        self.assertGreater(float(np.max(np.abs(audio))), 0.01)
        self.assertIsNotNone(daw.render_clip(song, *song.clip_order[2],
                                             self.sd))
        song.tracks[0].kind = "midi"                # le Deluge seul la joue
        self.assertIsNone(daw.render_clip(song, piste, indice, self.sd))

    def test_le_morceau_entier_est_la_somme_de_ses_pistes(self):
        from delugeapp.core import daw

        chemin = self._morceau()
        song = daw.from_deluge(chemin)
        mix = daw.render_mix(song, self.sd)
        self.assertGreaterEqual(mix.shape[0],
                                round(song.seconds(song.length) * 44100))
        dossier = self.base / "pistes"
        pistes = daw.render_stems(daw.from_deluge(chemin), self.sd, dossier)
        self.assertEqual(len(pistes), 2)
        somme = np.zeros((0, 2))
        for fichier in pistes:
            donnees, _taux = wav.read(fichier)
            # Chaque piste seule reste sous 0 dBFS : elle n'a pas été réduite.
            self.assertLess(float(np.max(np.abs(donnees))), 0.999)
            n = max(somme.shape[0], donnees.shape[0])
            somme = (np.pad(somme, ((0, n - somme.shape[0]), (0, 0)))
                     + np.pad(donnees, ((0, n - donnees.shape[0]), (0, 0))))
        # Le mélange, lui, est ramené sous 0 dBFS s'il les dépasse.
        crete = float(np.max(np.abs(somme)))
        attendu = somme * min(1.0, 0.999 / crete)
        n = min(attendu.shape[0], mix.shape[0])
        self.assertLess(float(np.max(np.abs(attendu[:n] - mix[:n]))), 1e-3)
        self.assertLessEqual(float(np.max(np.abs(mix))), 0.999 + 1e-6)
        self.assertIsNone(daw.render_mix(song, self.sd,
                                         should_stop=lambda: True))

    def test_aller_retour_par_les_trois_formats(self):
        from delugeapp.core import daw, dawimport

        song = daw.from_deluge(self._morceau())
        attendu = [self._deroule(t) for t in song.tracks]
        for ext, ecrire in ((".mid", daw.write_midi),
                            (".dawproject", daw.write_dawproject),
                            (".rpp", daw.write_rpp)):
            with self.subTest(format=ext):
                chemin = self.base / ("pont" + ext)
                ecrire(song, chemin)
                relu = dawimport.read_project(chemin)
                self.assertEqual([self._deroule(t) for t in relu.tracks],
                                 attendu)
                self.assertAlmostEqual(relu.bpm, 126.0, places=3)
                # La batterie revient batterie : canal 10 dans les trois.
                self.assertEqual([c.kind for c in
                                  dawimport.default_choices(relu)],
                                 ["synth", "kit"])

    def test_le_dossier_pour_le_daw_ne_remplace_rien(self):
        from delugeapp.core import daw

        song = daw.from_deluge(self._morceau())
        dest = self.base / "export"
        fait = daw.write_folder(song, dest, formats=("midi", "dawproject",
                                                     "rpp", "als"),
                                als_template=self._faux_live())
        for rel in fait["files"]:
            self.assertTrue((fait["folder"] / rel).exists(), rel)
        for suffixe in (".mid", ".dawproject", ".rpp", ".als"):
            self.assertTrue(any(f.endswith(suffixe) for f in fait["files"]),
                            suffixe)
        encore = daw.write_folder(song, dest, formats=("midi",))
        self.assertNotEqual(encore["folder"], fait["folder"])
        self.assertTrue(encore["folder"].name.endswith(" 2"))

    # -- depuis le DAW --------------------------------------------------- #

    def test_un_set_ableton_live_12(self):
        from delugeapp.core import dawimport

        song = dawimport.read_project(self._set_ableton())
        self.assertEqual(song.bpm, 97.0)
        self.assertEqual(len(song.tracks), 1)            # la piste audio, non
        basse = song.tracks[0]
        self.assertEqual(basse.name, "Basse")
        # La scène vide est retirée : « Refrain » devient la deuxième.
        self.assertEqual([s.name for s in song.scenes],
                         ["Couplet", "Refrain"])
        self.assertEqual(sorted(basse.scenes), [0, 1])
        self.assertEqual(song.markers, [(8.0, "Pont")])
        self.assertTrue(song.arranged)
        # La boucle de 4 noires jouée sur 8 : deux fois la note, jamais celle
        # qui est hors de la boucle.
        self.assertEqual(self._deroule(basse),
                         [(8.0, 43, 1.0, 100), (12.0, 43, 1.0, 100)])

    def test_un_set_ableton_live_8(self):
        from delugeapp.core import dawimport

        song = dawimport.read_project(self._set_ableton(live8=True))
        self.assertEqual(song.bpm, 97.0)
        self.assertEqual([s.name for s in song.scenes],
                         ["Couplet", "Refrain"])

    def test_reaper_recale_les_secondes_sur_la_grille(self):
        """À 129 BPM, 32 noires s'écrivent 14,883721 s et se relisent
        32,00000015 : sans recalage, un tour de boucle de plus, de durée
        nulle (relevé sur « Calm Down »)."""
        from delugeapp.core import daw, dawimport
        from delugeapp.core.daw import (DawClip, DawNote, DawSong, DawTrack,
                                        Placement)

        piste = DawTrack(name="Arp", clips=[DawClip("a", 4.0, [
            DawNote(60, 0.0, 0.5), DawNote(64, 3.75, 0.25)])],
            placements=[Placement(0, 0.0, 32.0), Placement(0, 64.0, 64.0)])
        song = DawSong(name="Grille", bpm=129.0, tracks=[piste])
        chemin = self.base / "grille.rpp"
        daw.write_rpp(song, chemin)
        relu = dawimport.read_project(chemin)
        self.assertEqual(self._deroule(relu.tracks[0]), self._deroule(piste))
        self.assertEqual(len(self._deroule(relu.tracks[0])), 48)

    def test_les_sections_suivent_les_reperes_puis_la_mesure(self):
        from delugeapp.core import dawimport
        from delugeapp.core.daw import (DawClip, DawNote, DawSong, DawTrack,
                                        Placement)

        def morceau(noires, reperes=()):
            piste = DawTrack(name="x", clips=[DawClip("c", 4.0, [
                DawNote(60, 0.0, 1.0)])], placements=[
                Placement(0, 0.0, float(noires))])
            return DawSong(name="s", tracks=[piste], markers=list(reperes))

        # Sans repère : des tranches de 8 mesures.
        self.assertEqual(dawimport.sections_of(morceau(64)),
                         [(0.0, 32.0, "Section 1"), (32.0, 64.0, "Section 2")])
        # 200 mesures : 25 tranches, doublées deux fois pour tenir en 12.
        self.assertEqual(len(dawimport.sections_of(morceau(800))), 7)
        # Les repères coupent, et nomment.
        self.assertEqual(
            dawimport.sections_of(morceau(64, [(16.0, "B"), (48.0, "C")])),
            [(0.0, 16.0, "Début"), (16.0, 48.0, "B"), (48.0, 64.0, "C")])
        # Une longue section se découpe à la mesure, sous son nom.
        self.assertEqual(
            [s[2] for s in dawimport.sections_of(morceau(96, [(32.0, "B")]))],
            ["Début", "B", "B 2"])
        # Quatorze repères : les plus courtes fusionnent, douze au plus.
        reperes = [(4.0 * i, "R%d" % i) for i in range(1, 15)]
        self.assertEqual(len(dawimport.sections_of(morceau(120, reperes))),
                         12)

    def test_import_vers_un_nouveau_morceau_relu_comme_la_machine(self):
        from delugeapp.core import daw, dawimport
        from delugeapp.core import songwriter as sw
        from delugeapp.core.daw import (DawClip, DawNote, DawSong, DawTrack,
                                        Placement)

        melodie = DawTrack(name="Lead", clips=[DawClip("m", 8.0, [
            DawNote(72, 0.0, 1.0, 100), DawNote(76, 1.5, 0.5, 80),
            DawNote(79, 4.0, 2.0, 110)])],
            placements=[Placement(0, 0.0, 32.0)])
        batterie = DawTrack(name="Drums", channel=9, clips=[DawClip("d", 4.0, [
            DawNote(36, 0.0, 0.25), DawNote(38, 1.0, 0.25),
            DawNote(42, 0.5, 0.125), DawNote(36, 2.0, 0.25),
            DawNote(38, 3.0, 0.25)])], placements=[Placement(0, 0.0, 32.0)])
        song = DawSong(name="Import", bpm=110.0, tracks=[melodie, batterie])
        choix = dawimport.default_choices(song)
        self.assertEqual([c.kind for c in choix], ["synth", "kit"])
        spec = dawimport.build_song(song, choix, name="Import", sd=self.sd,
                                    lib=self.lib)
        # 32 noires = 8 mesures : une section, des clips repliés.
        self.assertEqual(len(spec.sections), 1)
        self.assertEqual(sorted(c.length for c in spec.clips),
                         [sw.BAR, 2 * sw.BAR])
        avant = sorted(p.name for p in (self.root / "SONGS").iterdir())
        fait = sw.write_song(self.sd, spec, apply=True)
        self.assertTrue(fait.applied, fait.error)
        self.assertEqual(len(list((self.root / "SONGS").iterdir())),
                         len(avant) + 1)
        relu = daw.from_deluge(self.root / fait.rel)
        self.assertEqual(relu.bpm, 110.0)
        self.assertEqual(self._deroule(relu.tracks[0]),
                         self._deroule(melodie))
        # Chaque coup de la batterie a sa rangée.
        self.assertEqual(len(self._deroule(relu.tracks[1])),
                         len(self._deroule(batterie)))

    def test_les_chevauchements_sont_raccourcis_pas_perdus(self):
        from delugeapp.core import dawimport
        from delugeapp.core.daw import (DawClip, DawNote, DawSong, DawTrack,
                                        Placement)

        piste = DawTrack(name="Pad", clips=[DawClip("p", 4.0, [
            DawNote(60, 0.0, 2.0), DawNote(60, 1.0, 1.0)])],
            placements=[Placement(0, 0.0, 4.0)])
        spec = dawimport.build_song(DawSong(name="c", tracks=[piste]),
                                    [dawimport.ImportChoice("synth", "pad")],
                                    name="c")
        notes = spec.clips[0].rows[60]
        self.assertEqual([(n.pos, n.length) for n in notes],
                         [(0, 96), (96, 96)])

    def test_scenes_ou_arrangement_au_choix(self):
        from delugeapp.core import dawimport

        song = dawimport.read_project(self._set_ableton())
        choix = dawimport.default_choices(song)
        par_scenes = dawimport.build_song(song, choix, name="s",
                                          source="scenes")
        self.assertEqual([s.name for s in par_scenes.sections],
                         ["Couplet", "Refrain"])
        par_arrangement = dawimport.build_song(song, choix, name="a")
        self.assertEqual(par_arrangement.sections[0].name, "Début")

    def test_deviner_le_role_d_une_piste(self):
        from delugeapp.core import dawimport
        from delugeapp.core.daw import DawClip, DawNote, DawTrack

        def piste(nom, notes):
            return DawTrack(name=nom, clips=[DawClip("c", 4.0, notes)])

        self.assertEqual(dawimport.guess_role(piste("Sub Bass", [])), "bass")
        grave = [DawNote(36 + i % 3, i * 0.5, 0.5) for i in range(8)]
        self.assertEqual(dawimport.guess_role(piste("Piste 3", grave)),
                         "bass")
        accords = [DawNote(p, 0.0, 4.0) for p in (60, 64, 67)]
        self.assertEqual(dawimport.guess_role(piste("x", accords)), "pad")
        frappes = [DawNote(p, t, 0.5) for t in (0, 1) for p in (60, 64, 67)]
        self.assertEqual(dawimport.guess_role(piste("x", frappes)), "keys")
        rythme = [DawNote(p, t * 0.5, 0.1) for t, p in enumerate(
            (36, 42, 38, 42, 36, 42, 38, 46))]
        self.assertTrue(dawimport.looks_like_drums(piste("x", rythme)))
        ligne = [DawNote(p, t * 0.5, 0.1) for t, p in enumerate(
            (36, 42, 38, 72, 76, 79, 84, 86))]
        self.assertFalse(dawimport.looks_like_drums(piste("x", ligne)))

    def test_un_fichier_abime_ou_inconnu_est_refuse_clairement(self):
        from delugeapp.core import dawimport

        for nom, contenu in (("a.als", b"JUNK"), ("b.dawproject", b"PK??"),
                             ("c.mid", b"RIFF"), ("d.als", b"")):
            (self.base / nom).write_bytes(contenu)
            with self.subTest(nom=nom), self.assertRaises(ValueError):
                dawimport.read_project(self.base / nom)
        with self.assertRaises(ValueError):
            dawimport.read_project(self.base / "e.flp")

    # -- Ableton Live ---------------------------------------------------- #

    _CLIP = (
        '<MidiClip Id="0" Time="0"><LomId Value="0" />'
        '<CurrentStart Value="0" /><CurrentEnd Value="4" /><Loop>'
        '<LoopStart Value="0" /><LoopEnd Value="4" />'
        '<StartRelative Value="0" /><LoopOn Value="true" />'
        '<OutMarker Value="4" /><HiddenLoopStart Value="0" />'
        '<HiddenLoopEnd Value="4" /></Loop><Name Value="x" />'
        '<Color Value="0" /><Envelopes><Envelopes><ClipEnvelope Id="0" />'
        '</Envelopes></Envelopes><ScrollerTimePreserver>'
        '<LeftTime Value="0" /><RightTime Value="4" /></ScrollerTimePreserver>'
        '<TimeSelection><AnchorTime Value="1" /><OtherTime Value="2" />'
        '</TimeSelection><Notes><KeyTracks><KeyTrack Id="0"><Notes>'
        '<MidiNoteEvent Time="0" Duration="1" Velocity="100" '
        'OffVelocity="64" NoteId="1" /></Notes><MidiKey Value="1" />'
        '</KeyTrack></KeyTracks><PerNoteEventStore><EventLists />'
        '</PerNoteEventStore><NoteIdGenerator><NextId Value="2" />'
        '</NoteIdGenerator></Notes></MidiClip>')

    def _faux_live(self, edition: str = "Lite") -> Path:
        """Une installation de Live réduite à ce que ``dawals`` y lit, au
        format d'un Live imaginaire : les fichiers d'Ableton n'entrent pas
        dans le dépôt. ``edition`` nomme l'exécutable, comme Live le fait."""
        import gzip

        racine = self.base / ("Ableton " + edition)
        res = racine / "Resources"
        version = 'MinorVersion="12.0_99999"'

        def ecrire(rel, corps):
            chemin = res / rel
            chemin.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(chemin, "wb") as f:
                f.write(('<?xml version="1.0" encoding="UTF-8"?><Ableton %s>'
                         '%s</Ableton>' % (version, corps)).encode("utf-8"))

        cases = ('<ClipSlotList><ClipSlot Id="0"><LomId Value="0" />'
                 '<ClipSlot><Value /></ClipSlot><HasStop Value="true" />'
                 '</ClipSlot></ClipSlotList>')

        def piste(balise, sequence):
            return (
                '<%s Id="0"><Name><EffectiveName Value="1" />'
                '<UserName Value="" /></Name><Color Value="0" />'
                '<AutomationEnvelopes><Envelopes><AutomationEnvelope Id="0">'
                '<EnvelopeTarget><PointeeId Value="10" /></EnvelopeTarget>'
                '<Automation><Events><FloatEvent Id="0" Time="-63072000" '
                'Value="1" /></Events></Automation></AutomationEnvelope>'
                '</Envelopes></AutomationEnvelopes><DeviceChain>'
                '<MidiOutputRouting><Target Value="MidiOut/None" />'
                '<UpperDisplayString Value="None" />'
                '<LowerDisplayString Value="" /></MidiOutputRouting><Mixer>'
                '<Volume><Manual Value="1" /><AutomationTarget Id="10" />'
                '</Volume><Pan><ModulationTarget Id="11" /></Pan></Mixer>'
                '<MainSequencer>%s%s</MainSequencer><FreezeSequencer>%s'
                '</FreezeSequencer></DeviceChain></%s>'
                % (balise, cases, sequence, cases, balise))

        base = (
            '<LiveSet><NextPointeeId Value="100" /><Tracks>%s</Tracks>'
            '<MainTrack><AutomationEnvelopes><Envelopes>'
            '<AutomationEnvelope Id="0"><EnvelopeTarget><PointeeId Value="8"'
            ' /></EnvelopeTarget><Automation><Events><FloatEvent Id="0" '
            'Time="-63072000" Value="120" /></Events></Automation>'
            '</AutomationEnvelope></Envelopes></AutomationEnvelopes>'
            '<DeviceChain><Mixer><Tempo><Manual Value="120" />'
            '<AutomationTarget Id="8" /></Tempo></Mixer></DeviceChain>'
            '</MainTrack><Scenes><Scene Id="0"><Name Value="" />'
            '<Tempo Value="120" /></Scene></Scenes><Locators><Locators />'
            '</Locators></LiveSet>')
        midi = piste("MidiTrack", '<ClipTimeable><ArrangerAutomation>'
                     '<Events /></ArrangerAutomation></ClipTimeable>')
        audio = piste("AudioTrack", '<Sample><ArrangerAutomation><Events />'
                      '</ArrangerAutomation></Sample>')
        ecrire("Core Library/Defaults/Creating Tracks/MIDI Track/"
               "Default MIDI Track.als", base % midi)
        ecrire("Core Library/Defaults/Creating Tracks/Audio Track/"
               "Default Audio Track.als", base % audio)
        ecrire("Core Library/MIDI Clips/Drums/x.alc",
               "<LiveSet><Tracks><MidiTrack>%s</MidiTrack></Tracks>"
               "</LiveSet>" % self._CLIP)
        clip_audio = (
            '<AudioClip Id="0" Time="0"><CurrentStart Value="0" />'
            '<CurrentEnd Value="1" /><Loop><LoopStart Value="0" />'
            '<LoopEnd Value="1" /><StartRelative Value="0" />'
            '<LoopOn Value="true" /><OutMarker Value="1" />'
            '<HiddenLoopStart Value="0" /><HiddenLoopEnd Value="1" /></Loop>'
            '<Name Value="a" /><Color Value="0" /><Envelopes><Envelopes />'
            '</Envelopes><ScrollerTimePreserver><LeftTime Value="0" />'
            '<RightTime Value="1" /></ScrollerTimePreserver><SampleRef>'
            '<FileRef><RelativePathType Value="5" /><RelativePath Value="x" />'
            '<Path Value="/x" /><Type Value="2" /><LivePackName Value="P" />'
            '<LivePackId Value="p" /><OriginalFileSize Value="1" />'
            '<OriginalCrc Value="1" /><SourceHint Value="" /></FileRef>'
            '<LastModDate Value="0" /><DefaultDuration Value="1" />'
            '<DefaultSampleRate Value="48000" /></SampleRef>'
            '<WarpMode Value="4" /><IsWarped Value="true" /><WarpMarkers>'
            '<WarpMarker Id="9" SecTime="0" BeatTime="0" /></WarpMarkers>'
            '<SavedWarpMarkersForStretched /></AudioClip>')
        ecrire("Core Library/Lessons/demo.als",
               "<LiveSet><Tracks><AudioTrack>%s</AudioTrack></Tracks>"
               "</LiveSet>" % clip_audio)
        (racine / "Program").mkdir(parents=True, exist_ok=True)
        (racine / "Program" / ("Ableton Live 12 %s.exe" % edition)
         ).write_bytes(b"")
        return res

    @staticmethod
    def _pointees(chemin):
        import gzip
        import xml.etree.ElementTree as ET

        from delugeapp.core import dawals

        racine = ET.fromstring(gzip.open(chemin).read())
        suivant = int(racine.find("LiveSet/NextPointeeId").get("Value"))
        ids = [int(e.get("Id")) for e in racine.iter()
               if e.get("Id") is not None and dawals._is_pointee(e.tag)]
        refs = {int(e.get("Value")) for e in racine.iter("PointeeId")}
        return racine, suivant, ids, refs

    def test_un_set_ableton_aller_retour(self):
        from delugeapp.core import daw, dawals, dawimport

        res = self._faux_live()
        song = daw.from_deluge(self._morceau())
        chemin = dawals.write_als(song, self.base / "pont.als", template=res)
        relu = dawimport.read_project(chemin)
        self.assertEqual([self._deroule(t) for t in relu.tracks],
                         [self._deroule(t) for t in song.tracks])
        self.assertEqual(relu.bpm, 126.0)
        self.assertEqual(len(relu.scenes), len(song.scenes))
        racine, suivant, ids, refs = self._pointees(chemin)
        # Chaque piste clonée a ses numéros propres, sous NextPointeeId, et
        # ses enveloppes désignent les siens.
        self.assertEqual(len(ids), len(set(ids)))
        self.assertLess(max(ids), suivant)
        self.assertLessEqual(refs, set(ids))
        # Le tempo vit deux fois : la valeur et son enveloppe.
        tempo = racine.find("LiveSet/MainTrack/DeviceChain/Mixer/Tempo")
        self.assertEqual(tempo.find("Manual").get("Value"), "126")
        self.assertEqual(next(racine.find("LiveSet/MainTrack").iter(
            "FloatEvent")).get("Value"), "126")
        # Une case par scène, dans les deux listes de chaque piste.
        for piste in racine.find("LiveSet/Tracks"):
            for liste in ("DeviceChain/MainSequencer/ClipSlotList",
                          "DeviceChain/FreezeSequencer/ClipSlotList"):
                self.assertEqual(len(piste.find(liste)),
                                 len(song.scenes))

    def test_le_set_suit_l_edition_de_live(self):
        """Le tableau d'Ableton : Lite 8 pistes et 16 scènes, Intro 16 et 16,
        Standard et Suite sans limite. Mesuré sur Live 12 Lite : « 9 pistes ;
        (limité à 8) » à l'ouverture, douze scènes sans avertissement."""
        from delugeapp.core import dawals
        from delugeapp.core.daw import (DawClip, DawNote, DawScene, DawSong,
                                        DawTrack, Placement)

        pistes = [DawTrack(name="P%d" % i, clips=[DawClip("c", 4.0, [
            DawNote(60, 0.0, 1.0)])], placements=[Placement(0, 0.0, 4.0)],
            scenes={s: 0 for s in range(20)}) for i in range(18)]
        song = DawSong(name="Gros", tracks=pistes,
                       scenes=[DawScene("S%d" % s, 4.0) for s in range(20)])
        for edition, attendu in (("Lite", (8, 16, 2)), ("Intro", (16, 16, 2)),
                                 ("Suite", (18, 20, 0)),
                                 ("Standard", (18, 20, 0))):
            with self.subTest(edition=edition):
                res = self._faux_live(edition)
                self.assertEqual(dawals.find_live(res).edition, edition)
                notes: list = []
                chemin = dawals.write_als(song, self.base / (edition + ".als"),
                                          template=res, notes=notes)
                racine, *_ = self._pointees(chemin)
                self.assertEqual((len(racine.find("LiveSet/Tracks")),
                                  len(racine.find("LiveSet/Scenes")),
                                  len(notes)), attendu)
        res = self._faux_live("Lite")
        # Les pistes de notes d'abord : l'audio prend les places libres.
        notes.clear()
        dossier = self.base / "lite"
        (dossier / "Pistes audio").mkdir(parents=True)
        audio = {}
        for i in range(3):
            rel = "Pistes audio/%02d.wav" % i
            wav.write(dossier / rel, np.zeros(4410, np.float32), 44100)
            audio[i] = rel
        song.tracks = pistes[:6]
        song.scenes = song.scenes[:10]
        chemin = dawals.write_als(song, dossier / "lite.als", audio=audio,
                                  template=res, notes=notes)
        racine, *_ = self._pointees(chemin)
        self.assertEqual([p.tag for p in racine.find("LiveSet/Tracks")],
                         ["MidiTrack"] * 6 + ["AudioTrack"] * 2)
        self.assertEqual(len(notes), 1)

    def test_les_pistes_audio_sont_posees_au_debut(self):
        from delugeapp.core import daw, dawals

        res = self._faux_live()
        song = daw.from_deluge(self._morceau())
        dossier = self.base / "dossier"
        (dossier / "Pistes audio").mkdir(parents=True)
        wav.write(dossier / "Pistes audio" / "01 Basse.wav",
                  np.zeros(44100 * 2, np.float32), 44100)
        chemin = dawals.write_als(song, dossier / "pont.als",
                                  audio={0: "Pistes audio/01 Basse.wav"},
                                  template=res)
        racine, *_ = self._pointees(chemin)
        clip = next(racine.iter("AudioClip"))
        ref = clip.find("SampleRef/FileRef")
        self.assertEqual(ref.find("RelativePathType").get("Value"), "1")
        self.assertEqual(ref.find("RelativePath").get("Value"),
                         "Pistes audio/01 Basse.wav")
        # Deux secondes à 126 BPM : 4,2 noires, calées par deux repères.
        reperes = clip.findall("WarpMarkers/WarpMarker")
        self.assertEqual([r.get("SecTime") for r in reperes], ["0", "2"])
        self.assertEqual(reperes[1].get("BeatTime"), "4.2")

    def test_sans_live_le_set_est_annonce_comme_laisse(self):
        from unittest import mock

        from delugeapp.core import daw, dawals

        song = daw.from_deluge(self._morceau())
        with mock.patch.object(dawals, "find_live", return_value=None):
            fait = daw.write_folder(song, self.base / "x", formats=("als",))
        self.assertFalse(any(f.endswith(".als") for f in fait["files"]))
        self.assertTrue(any("Ableton" in r for r in fait["skipped"]))

    def test_avec_le_live_installe(self):
        """Sur un PC où Live est installé, ses vrais fichiers servent de
        modèles — lus, jamais écrits."""
        from delugeapp.core import daw, dawals, dawimport

        live = dawals.find_live()
        if live is None:
            self.skipTest("Live n'est pas installé sur ce PC")
        song = daw.from_deluge(self._morceau())
        chemin = dawals.write_als(song, self.base / "vrai.als")
        relu = dawimport.read_project(chemin)
        self.assertEqual([self._deroule(t) for t in relu.tracks],
                         [self._deroule(t) for t in song.tracks])

    # -- jouer ensemble -------------------------------------------------- #

    def test_chaque_piste_ecoute_son_canal_dans_une_copie(self):
        from delugeapp.core import dawlive

        chemin = self._morceau()
        rel = "SONGS/" + chemin.name
        original = chemin.read_bytes()
        routes = dawlive.read_routes(self.sd, rel)
        self.assertEqual([r.kind for r in routes], ["synth", "kit"])
        self.assertEqual([r.existing for r in routes], [None, None])
        # Les sons du kit prennent les notes de l'export vers le DAW.
        self.assertLessEqual({36, 38}, {n for _s, n, _c in routes[1].drums})
        dawlive.propose_channels(routes, avoid={0})
        # Le canal 1 est celui de MIDI Follow : le synthé prend le 2, le kit
        # le 10 des batteries.
        self.assertEqual([r.channel for r in routes], [1, 9])
        plan = dawlive.plan_live(self.sd, rel, routes, follow={0})
        self.assertTrue(plan.ok, plan.error)
        self.assertEqual(plan.rel, "SONGS/Pont DAW.XML")
        fait = dawlive.write_live(self.sd, plan)
        self.assertFalse(fait.applied)                  # simulé d'abord
        self.assertFalse((self.root / plan.rel).exists())
        fait = dawlive.write_live(self.sd, plan, apply=True)
        self.assertTrue(fait.applied, fait.error)
        self.assertEqual(chemin.read_bytes(), original)
        relu = dawlive.read_routes(self.sd, plan.rel)
        self.assertEqual([r.existing for r in relu], [1, 9])
        self.assertTrue(all(c == 9 for _s, _n, c in relu[1].drums))
        # La copie relue ne demande plus rien.
        dawlive.propose_channels(relu)
        encore = dawlive.plan_live(self.sd, plan.rel, relu)
        self.assertFalse(encore.ok)
        self.assertEqual(encore.edits, [])

    def test_un_kit_deja_regle_change_de_canal_en_entier(self):
        """Sur une copie « DAW », les sons du kit écoutent déjà : choisir un
        autre canal pour le kit doit les y mener tous — le plan l'annonçait,
        et rien ne changeait."""
        from delugeapp.core import dawlive

        rel = "SONGS/" + self._morceau().name
        routes = dawlive.propose_channels(dawlive.read_routes(self.sd, rel),
                                          avoid={0})
        copie = dawlive.plan_live(self.sd, rel, routes)
        self.assertTrue(dawlive.write_live(self.sd, copie, apply=True).applied)
        relu = dawlive.read_routes(self.sd, copie.rel)
        self.assertEqual(relu[1].existing, 9)
        relu[1].channel = 4                     # choisi dans le tableau
        plan = dawlive.plan_live(self.sd, copie.rel, relu)
        self.assertTrue(plan.ok, plan.error)
        self.assertEqual({(e[1], e[2]) for e in plan.edits}, {(b"9", b"4")})
        self.assertEqual(len(plan.edits), len(relu[1].drums))
        self.assertTrue(any("canal 5 (" in ligne for ligne in plan.lines))
        fait = dawlive.write_live(self.sd, plan, apply=True)
        self.assertTrue(fait.applied, fait.error)
        apres = dawlive.read_routes(self.sd, plan.rel)
        self.assertEqual(apres[1].existing, 4)
        self.assertTrue(all(c == 4 for _s, _n, c in apres[1].drums))
        # Les notes apprises restent les leurs.
        self.assertEqual([n for _s, n, _c in apres[1].drums],
                         [n for _s, n, _c in relu[1].drums])
        # La preuve refuse un son resté sur l'ancien canal.
        plan.data = plan.data.replace(b'channel="4"', b'channel="9"', 1)
        self.assertNotEqual(dawlive.verify_live(
            (self.root / copie.rel).read_bytes(), plan), "")

    def test_une_ecoute_existante_est_gardee_et_signalee(self):
        from delugeapp.core import dawlive

        chemin = self._morceau()
        texte = chemin.read_bytes().replace(
            b'activeModFunction="0"', b'activeModFunction="0"\n'
            b'\t\t\tinputMidiChannel="0"', 1)
        chemin.write_bytes(texte)
        rel = "SONGS/" + chemin.name
        routes = dawlive.propose_channels(dawlive.read_routes(self.sd, rel),
                                          avoid={0})
        self.assertEqual(routes[0].existing, 0)
        self.assertIsNone(routes[0].channel)            # gardé
        plan = dawlive.plan_live(self.sd, rel, routes, follow={0})
        self.assertTrue(plan.ok, plan.error)
        self.assertTrue(any("MIDI Follow" in l for l in plan.lines))
        # Sur demande, l'écoute existante change de canal : la valeur seule
        # est remplacée.
        routes = dawlive.propose_channels(dawlive.read_routes(self.sd, rel),
                                          avoid={0}, keep_existing=False)
        self.assertEqual(routes[0].channel, 1)
        plan = dawlive.plan_live(self.sd, rel, routes)
        self.assertIn((b"0", b"1"), [(e[1], e[2]) for e in plan.edits])
        self.assertTrue(plan.ok, plan.error)

    def test_la_preuve_refuse_une_copie_alteree(self):
        from delugeapp.core import dawlive

        chemin = self._morceau()
        rel = "SONGS/" + chemin.name
        routes = dawlive.propose_channels(dawlive.read_routes(self.sd, rel))
        plan = dawlive.plan_live(self.sd, rel, routes)
        self.assertEqual(dawlive.verify_live(chemin.read_bytes(), plan), "")
        plan.data = plan.data.replace(b'tempo', b'tempi', 1)
        self.assertNotEqual(dawlive.verify_live(chemin.read_bytes(), plan),
                            "")
        # Un canal qui n'est pas celui prévu est refusé aussi.
        plan = dawlive.plan_live(self.sd, rel, routes)
        routes[0].channel = 5
        self.assertNotEqual(dawlive.verify_live(chemin.read_bytes(), plan),
                            "")

    def test_le_mode_d_emploi_dit_l_horloge_et_les_canaux(self):
        from delugeapp.core import dawlive

        etapes = dawlive.setup_steps("ableton")
        self.assertTrue(any("Clock" in e for e in etapes))
        self.assertTrue(any("MIDI To" in e for e in etapes))
        self.assertNotEqual(dawlive.setup_steps("autre"), etapes)

    def test_sous_windows_le_deluge_mene_l_horloge(self):
        """Mesuré le 9 novembre 2026 : sous Windows 11, le Deluge joue les
        notes de Live mais ignore son horloge (pilote USB MIDI 2 de Windows,
        code USB 0x5 au lieu de 0xF). Le mode d'emploi le dit là, et
        seulement là, pour tous les DAW."""
        from delugeapp.core import dawlive

        for daw in ("ableton", "autre"):
            with self.subTest(daw=daw):
                windows = dawlive.setup_steps(daw, platform="win32")
                ailleurs = dawlive.setup_steps(daw, platform="darwin")
                self.assertEqual(windows[:-1], ailleurs)
                self.assertIn("Windows", windows[-1])
                self.assertIn("Clock ▸ Output", windows[-1])
                self.assertFalse(any("Windows" in e for e in ailleurs))
        # Live suit le Deluge par son bouton EXT.
        self.assertTrue(any("EXT" in e for e in dawlive.setup_steps(
            "ableton", platform="linux")))

    def test_le_set_d_une_copie_daw_sort_vers_le_deluge(self):
        """L'export de la copie « DAW » sort sur les canaux qu'écoute la
        machine, et son set Live est déjà routé (« MIDI To ») comme celui que
        Live a enregistré le 9 novembre 2026 : vérifié sur la machine, les
        trois pistes de « Cool1 DAW » jouaient sans réglage. L'original,
        dont les pistes n'écoutent rien, reste comme avant."""
        import gzip
        import xml.etree.ElementTree as ET

        from delugeapp.core import daw, dawals, dawlive

        res = self._faux_live()
        chemin = self._morceau()
        rel = "SONGS/" + chemin.name
        routes = dawlive.propose_channels(dawlive.read_routes(self.sd, rel),
                                          avoid={0})
        plan = dawlive.plan_live(self.sd, rel, routes, follow={0})
        self.assertTrue(dawlive.write_live(self.sd, plan, apply=True).applied)

        def sorties(fichier):
            racine = ET.fromstring(gzip.open(fichier).read())
            return [tuple(p.find("DeviceChain/MidiOutputRouting/" + nom)
                          .get("Value") for nom in
                          ("Target", "UpperDisplayString",
                           "LowerDisplayString"))
                    for p in racine.find("LiveSet/Tracks")]

        copie = daw.from_deluge(self.root / plan.rel)
        self.assertEqual([t.listens for t in copie.tracks], [1, 9])
        self.assertEqual([t.channel for t in copie.tracks], [1, 9])
        als = dawals.write_als(copie, self.base / "copie.als", template=res)
        self.assertEqual(sorties(als), [
            ("MidiOut/External.Dev:Deluge{16D0-0CE2-0-out-0}/1", "Deluge",
             "Ch. 2"),
            ("MidiOut/External.Dev:Deluge{16D0-0CE2-0-out-0}/9", "Deluge",
             "Ch. 10")])
        # Les notes du kit restent celles que la copie fait écouter.
        self.assertEqual(set(copie.tracks[1].drums),
                         {n for _s, n, _c in routes[1].drums})

        original = daw.from_deluge(chemin)
        self.assertEqual([t.listens for t in original.tracks], [None, None])
        self.assertEqual([t.channel for t in original.tracks], [0, 9])
        als = dawals.write_als(original, self.base / "original.als",
                               template=res)
        self.assertEqual(sorties(als), [("MidiOut/None", "None", "")] * 2)

        # Le lisez-moi le dit quand le set est routé, et seulement alors.
        for song, fichiers, attendu in ((copie, ["x.als"], True),
                                        (copie, ["x.mid"], False),
                                        (original, ["x.als"], False)):
            texte = daw.write_readme(song, self.base / "LISEZMOI.txt",
                                     fichiers).read_text("utf-8")
            self.assertEqual("MIDI To" in texte, attendu)

    def test_un_kit_appris_garde_ses_notes_a_l_export(self):
        """Un son de kit appris sur la machine sur une autre note que celle
        de General MIDI : l'export le joue sur sa note, les autres sons
        l'évitent. Un kit qui écoute en entier (``MIDIInput``) passe avant
        ses sons sur la machine : ses notes General MIDI ne le jouent pas,
        il n'est pas routé."""
        from delugeapp.core import daw, dawlive

        rel = "SONGS/" + self._morceau().name
        routes = dawlive.propose_channels(dawlive.read_routes(self.sd, rel),
                                          avoid={0})
        plan = dawlive.plan_live(self.sd, rel, routes)
        self.assertTrue(dawlive.write_live(self.sd, plan, apply=True).applied)
        copie = self.root / plan.rel
        texte = copie.read_bytes()
        avant = daw.from_deluge(copie).tracks[1]
        kick = next(p for p, (i, _n) in avant.drums.items() if i == 0)
        self.assertEqual(kick, 36)
        # Le kick appris sur le do 3 (60) au lieu du 36.
        copie.write_bytes(texte.replace(b'note="36"', b'note="60"', 1))
        kit = daw.from_deluge(copie).tracks[1]
        self.assertEqual(kit.listens, 9)
        self.assertEqual(kit.drums[60][0], 0)
        self.assertNotIn(36, kit.drums)
        self.assertEqual(len(kit.drums), len(avant.drums))
        notes = {n.pitch for _d, n in daw._expanded(kit)}
        self.assertIn(60, notes)
        self.assertNotIn(36, notes)
        # Le kit entier à l'écoute : plus de routage, le canal 10 d'usage.
        fin = texte.index(b"</kit>")
        copie.write_bytes(texte[:fin] + b'<MIDIInput channel="4" note="36" />'
                          + texte[fin:])
        kit = daw.from_deluge(copie).tracks[1]
        self.assertIsNone(kit.listens)
        self.assertEqual(kit.channel, 9)


# --------------------------------------------------------------------------- #
# Un instrument multi-échantillon (7 novembre 2026)
# --------------------------------------------------------------------------- #

def _note_sinus(midi: int, seconds: float = 0.6, sr: int = 44100):
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False,
                    dtype=np.float32)
    freq = 440.0 * 2 ** ((midi - 69) / 12.0)
    return (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


class TestInstrumentMultiEchantillon(unittest.TestCase):
    """Les noms des vrais dossiers de la carte, puis un dossier jetable."""

    def test_les_noms_de_la_carte(self):
        from delugeapp.core import multisample as ms

        # Steinway (C4 = 60, couche de vélocité), guitare REPHAZER (numéro
        # MIDI en C3 = 60), puis des noms sans note.
        self.assertEqual(ms.note_from_name("A1-1-48"), (33, None, (1, 48)))
        self.assertEqual(ms.note_from_name("C2-1-48"), (36, None, (1, 48)),
                         "le 48 de la vélocité n'est pas un numéro MIDI")
        self.assertEqual(ms.note_from_name("Db6-97-127"),
                         (85, None, (97, 127)))
        self.assertEqual(ms.note_from_name("Guitar 3 oct3_11(C#3)_61"),
                         (49, 61, None))
        self.assertEqual(ms.note_from_name("Guitar 3 oct3_2 (E1)_40"),
                         (28, 40, None))
        for sans in ("1", "Kick 808", "Pad A minor", "oct3"):
            with self.subTest(nom=sans):
                self.assertEqual(ms.note_from_name(sans)[0], None)
        self.assertEqual(ms.note_label(60), "C3")
        self.assertEqual(ms.default_name("SAMPLES/MULTISAMPLES/STEINWAY/LOW"),
                         "STEINWAY LOW")
        self.assertEqual(ms.default_name("SAMPLES/MULTISAMPLES/Strings"),
                         "Strings")

    def _carte(self, fichiers: dict[str, int]):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        racine = Path(tmp.name) / "carte"
        for sous in ("SONGS", "SYNTHS", "KITS", "SAMPLES/MULTISAMPLES/Orgue"):
            (racine / sous).mkdir(parents=True, exist_ok=True)
        for nom, midi in fichiers.items():
            wav.write(racine / "SAMPLES/MULTISAMPLES/Orgue" / nom,
                      _note_sinus(midi), 44100)
        return sdcard.SDCard(racine)

    def test_des_tranches_comme_celles_du_firmware(self):
        from delugeapp.core import multisample as ms
        from delugeapp.core.model import SynthPreset

        sd = self._carte({"Orgue C4.wav": 60, "Orgue E4.wav": 64,
                          "Orgue G4.wav": 67, "Orgue G4 bis.wav": 67})
        plan = ms.plan_instrument(sd, "SAMPLES/MULTISAMPLES/Orgue")
        self.assertIn("C4 = 60", plan.convention)
        layer = plan.layers[0]
        self.assertEqual([(s.note, top) for s, top in layer.ranges],
                         [(60, 62), (64, 65), (67, 127)])
        self.assertEqual(len(plan.skipped), 1)       # le second G4
        ecrit = ms.write_instruments(sd, plan, apply=True)
        self.assertTrue(ecrit.applied, ecrit.error)
        self.assertEqual(ecrit.rels, ["SYNTHS/Multi/Orgue.XML"])
        relu = SynthPreset.load(sd.abs(ecrit.rels[0]))
        self.assertEqual([(r.top_note, r.transpose, r.zone.end)
                          for r in relu.sound.osc1.ranges],
                         [(62, 0, 26460), (65, -4, 26460),
                          (127, -7, 26460)])
        self.assertEqual(relu.sound.osc1.loop_mode, 1)   # ONCE, < 2,002 s
        # Une seconde fois : un nom neuf, rien de remplacé.
        encore = ms.write_instruments(sd, plan, apply=True)
        self.assertEqual(encore.rels, ["SYNTHS/Multi/Orgue 2.XML"])

    def test_chaque_note_joue_sa_tranche_sur_l_ordinateur(self):
        """Un multi-échantillon s'entendait en dent de scie : sans
        ``fileName`` propre, l'écoute ne trouvait aucun fichier."""
        from delugeapp.core import multisample as ms

        sd = self._carte({"Orgue C3.wav": 48, "Orgue C5.wav": 72})
        doux = sd.abs("SAMPLES/MULTISAMPLES/Orgue/Orgue C3.wav")
        wav.write(doux, 0.05 * _note_sinus(48) / 0.5, 44100)
        plan = ms.plan_instrument(sd, "SAMPLES/MULTISAMPLES/Orgue",
                                  detect=False)
        sound = ms.build_presets(plan)[0].sound
        niveaux = {}
        for note in (40, 84):
            audio = render.render_sound(sound, note=note, seconds=0.4, sd=sd)
            niveaux[note] = float(np.sqrt(np.mean(audio ** 2)))
        # La note grave joue le son doux, l'aiguë le fort : dix fois plus.
        self.assertGreater(niveaux[84], 5 * niveaux[40])
        self.assertGreater(niveaux[40], 0.0)

    def test_une_note_relachee_s_eteint_sans_coupure(self):
        """Entendu sur la machine (9 novembre 2026) : avec la relâche du son
        neuf du firmware, 6 ms, le piano se coupait net. Celle du piano que
        REPHAZER a bâti sur la machine : le réglage 8, une demi-seconde."""
        from delugeapp.core import multisample as ms
        from delugeapp.core import paramlaws

        sd = self._carte({"Orgue C3.wav": 48, "Orgue C5.wav": 72})
        plan = ms.plan_instrument(sd, "SAMPLES/MULTISAMPLES/Orgue",
                                  detect=False)
        son = ms.build_presets(plan)[0].sound
        self.assertEqual(son.env1.release, -1460288888)
        unites = (son.env1.release + 2 ** 31) / 2 ** 32 * 2 - 1
        self.assertAlmostEqual(float(paramlaws.release_seconds(unites)), 0.495,
                               places=2)

    def test_des_couches_de_velocite_font_deux_presets(self):
        from delugeapp.core import multisample as ms

        sd = self._carte({"C4-1-64.wav": 60, "E4-1-64.wav": 64,
                          "C4-65-127.wav": 60, "E4-65-127.wav": 64})
        plan = ms.plan_instrument(sd, "SAMPLES/MULTISAMPLES/Orgue")
        self.assertEqual([layer.name for layer in plan.layers],
                         ["Orgue 1-64", "Orgue 65-127"])
        self.assertEqual(len(ms.build_presets(plan)), 2)

    def test_la_meme_note_partout_dans_le_fichier_est_ignoree(self):
        """``loadAllSamplesInFolder`` : tous la même note, on s'en méfie."""
        from unittest import mock

        from delugeapp.core import multisample as ms

        sd = self._carte({"1.wav": 60, "2.wav": 67})
        vrai_probe = wav.probe

        def probe_a_60(path):
            info = vrai_probe(path)
            info.root_note = 60
            return info

        with mock.patch.object(ms.wav, "probe", probe_a_60):
            plan = ms.plan_instrument(sd, "SAMPLES/MULTISAMPLES/Orgue")
        self.assertEqual(sorted((s.note, s.source)
                                for s, _t in plan.layers[0].ranges),
                         [(60, "écoute"), (67, "écoute")])


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


class TestTablesDOnde(unittest.TestCase):
    """Une table d'onde au format du firmware 1.3.0, et ce qui s'en sert."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "carte"
        for sous in ("SONGS", "SYNTHS", "KITS", "SAMPLES/Nappes"):
            (self.root / sous).mkdir(parents=True)
        sr = 44100
        temps = np.linspace(0, 2.0, 2 * sr, endpoint=False)
        # Une nappe en la 3 (220 Hz) qui s'éclaircit : la table doit
        # évoluer d'un cycle à l'autre.
        brillance = np.linspace(0.0, 0.6, temps.size)
        nappe = (np.sin(2 * np.pi * 220 * temps)
                 + brillance * np.sin(2 * np.pi * 660 * temps)) * 0.4
        wav.write(self.root / "SAMPLES/Nappes/nappe.wav",
                  nappe.astype(np.float32), sr)
        bruit = np.random.default_rng(3).standard_normal(sr) * 0.3
        wav.write(self.root / "SAMPLES/Nappes/bruit.wav",
                  bruit.astype(np.float32), sr)
        self.sd = sdcard.SDCard(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_une_table_au_format_du_firmware(self):
        from delugeapp.core import wavetable as wt

        rel, erreur = wt.write_wavetable(self.sd, "SAMPLES/Nappes/nappe.wav",
                                         "NAPPE", apply=True)
        self.assertEqual((rel, erreur), ("SAMPLES/WAVETABLES/NAPPE.wav", ""))
        chemin = self.sd.abs(rel)
        octets = chemin.read_bytes()
        # Le bloc Serum que lit ``audio_file.cpp`` : « clm », puis « <!> »
        # et quatre chiffres.
        i = octets.find(b"clm ")
        self.assertGreater(i, 0)
        self.assertEqual(octets[i + 8:i + 15], b"<!>2048")
        self.assertEqual(wt.cycle_size_of(chemin), 2048)
        data, sr = wav.read(chemin)
        self.assertEqual((data.shape[0], sr), (64 * 2048, 44100))
        premier, dernier = data[:2048], data[-2048:]
        self.assertGreater(float(np.max(np.abs(premier - dernier))), 0.05,
                           "la table n'évolue pas")
        # Une seconde table du même nom est numérotée.
        self.assertEqual(wt.write_wavetable(self.sd, "SAMPLES/Nappes/nappe.wav",
                                            "NAPPE")[0],
                         "SAMPLES/WAVETABLES/NAPPE 2.wav")

    def test_un_bruit_ne_donne_pas_de_table(self):
        from delugeapp.core import wavetable as wt

        rel, erreur = wt.write_wavetable(self.sd, "SAMPLES/Nappes/bruit.wav",
                                         apply=True)
        self.assertEqual(rel, "")
        self.assertIn("hauteur", erreur)
        self.assertFalse((self.root / "SAMPLES/WAVETABLES").exists())

    def test_l_ecoute_joue_la_table_a_la_bonne_hauteur(self):
        """La dent de scie d'avant ne tenait aucun compte de la table."""
        from delugeapp.core import wavetable as wt
        from delugeapp.core.fixedpoint import from_display

        rel, _e = wt.write_wavetable(self.sd, "SAMPLES/Nappes/nappe.wav",
                                     "NAPPE", apply=True)
        preset = SynthPreset.new("TABLE")
        sound = preset.sound
        sound.osc1.type = "wavetable"
        sound.osc1.file_name = rel
        sound.set_param("oscBVolume", from_display(0, scale=50))
        sound.set_param("lpfFrequency", from_display(50, scale=50))
        sound.env1.sustain = from_display(48, scale=50)
        for note in (48, 60):
            with self.subTest(note=note):
                mono = render.render_sound(sound, note=note, seconds=0.8,
                                           sd=self.sd).mean(axis=1)
                self.assertEqual(analysis.estimate_root_note(mono, 44100),
                                 note)

    def test_le_generateur_prend_une_table_de_la_carte(self):
        tables = ["SAMPLES/WAVETABLES/NAPPE.wav"]
        vus = set()
        for genre in genres.genre_keys():
            for graine in range(12):
                preset = synthgen.generate(synthgen.GenOptions(
                    genre=genre, role="pad", seed=graine,
                    wavetables=tables))
                for osc in (preset.sound.osc1, preset.sound.osc2):
                    if osc.type == "wavetable":
                        self.assertIn(osc.file_name, tables)
                        vus.add(genre)
        self.assertTrue(vus, "aucun genre n'a pris la table")
        # Sans table, le tirage est celui d'avant, à l'identique.
        sans = synthgen.generate(synthgen.GenOptions(genre="trance",
                                                     role="pad", seed=3))
        self.assertNotIn("wavetable", (sans.sound.osc1.type,
                                       sans.sound.osc2.type))


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



# --------------------------------------------------------------------------- #
# Noms courts de FAT (8.3)
# --------------------------------------------------------------------------- #

class TestSidechain(unittest.TestCase):
    """Le sidechain porté du firmware 1.3.0 (``sidechain.cpp``,
    ``Sound::render``, ``renderReverb``) : la grosse caisse fait pomper les
    sons câblés depuis la source *sidechain*, et la réverbération."""

    def test_combiner_deux_coups(self):
        from delugeapp.core import dsp

        self.assertEqual(dsp.combine_hit_strengths(0, 1000), 1000)
        # À mi-chemin du plus fort et de la somme, plafonnée.
        self.assertEqual(dsp.combine_hit_strengths(1000, 1000), 1500)
        self.assertEqual(dsp.combine_hit_strengths(dsp.ONE_Q31, dsp.ONE_Q31),
                         dsp.ONE_Q31 - 1)

    def test_la_vitesse_suit_le_tempo(self):
        from delugeapp.core import dsp

        self.assertEqual(dsp.sidechain_rate(936, 0, 120.0), 936)
        a120 = dsp.sidechain_rate(936, 6, 120.0)
        self.assertEqual(a120, int(936 * 120 * 2 ** 10 / 165375))
        # Deux fois plus vite au double du tempo, ou un niveau plus haut.
        self.assertAlmostEqual(dsp.sidechain_rate(936, 6, 240.0) / a120, 2.0,
                               places=2)
        self.assertAlmostEqual(dsp.sidechain_rate(936, 7, 120.0) / a120, 2.0,
                               places=2)

    def test_l_enveloppe_creuse_puis_remonte(self):
        from delugeapp.core import dsp

        hits = [0] * 400
        hits[10] = dsp.ONE_Q31
        attaque = dsp.sidechain_rate(327244, 6, 120.0)
        relache = dsp.sidechain_rate(936, 6, 120.0)
        v = dsp.sidechain_blocks(hits, attaque, relache, -601295438)
        self.assertTrue(np.all(v[:10] == 0))
        self.assertTrue(np.all(v <= 0))
        creux = int(np.argmin(v))
        self.assertLess(creux, 13)                   # l'attaque est brève
        self.assertLess(v[creux], -0.9 * dsp.ONE_Q31)
        # Puis elle remonte sans jamais redescendre, jusqu'au repos.
        remontee = v[creux:]
        self.assertTrue(np.all(np.diff(remontee) >= 0))
        self.assertEqual(v[-1], 0)
        # Un coup plus faible pendant la remontée ne la relance pas.
        hits2 = list(hits)
        hits2[60] = 1000
        self.assertTrue(np.array_equal(
            dsp.sidechain_blocks(hits2, attaque, relache, -601295438), v))

    def test_une_attaque_tout_en_bas_saute_au_creux(self):
        from delugeapp.core import dsp

        hits = [0] * 50
        hits[5] = dsp.ONE_Q31
        v = dsp.sidechain_blocks(hits, 1 << 22, dsp.sidechain_rate(936, 6, 120.0),
                                 -601295438, instant=True)
        self.assertLess(v[5], -0.9 * dsp.ONE_Q31)

    @staticmethod
    def _sons(cable=0x40000000, envoi=2147483647):
        """Une grosse caisse **muette** qui envoie ses coups — le rendu ne
        contient que la nappe —, et une nappe câblée depuis le sidechain."""
        from delugeapp.core.model import PatchCable

        kick = SynthPreset.new("KICK").sound
        kick.set_param("volume", INT32_MIN)
        kick.side_chain_send = envoi
        nappe = SynthPreset.new("NAPPE").sound
        if cable:
            nappe.patch_cables.append(PatchCable(
                source="compressor", destination="volumePostReverbSend",
                amount=cable))
        return kick, nappe

    @staticmethod
    def _rendu(kick, nappe, hits=None):
        from delugeapp.core import render
        from delugeapp.core.accomp import NoteEvent

        # Pas de double-croche à 120 BPM : 0,125 s. Coups à 1, 2 et 3 s.
        parts = {"nappe": [NoteEvent(0.0, 32.0, 60, 100)],
                 "kick": [NoteEvent(float(p), 1.0, 36, 100)
                          for p in (8, 16, 24)]}
        return render.render_parts(parts, {"nappe": nappe, "kick": kick},
                                   bpm=120.0, sr=44100, normalize=False,
                                   tail=0.2, sidechain_hits=hits)

    @staticmethod
    def _niveau(audio, debut, fin):
        a, b = int(debut * 44100), int(fin * 44100)
        return float(np.sqrt(np.mean(np.asarray(audio)[a:b] ** 2)))

    def test_la_nappe_pompe_sous_la_grosse_caisse(self):
        """Câble coupé, la nappe garde son niveau ; câblée, elle se creuse
        juste après chaque coup, et l'a retrouvé avant le suivant."""
        temoin = self._rendu(*self._sons(cable=0))
        pompee = self._rendu(*self._sons())
        self.assertGreater(self._niveau(temoin, 1.02, 1.10), 0.01)
        self.assertLess(self._niveau(pompee, 1.02, 1.10),
                        0.6 * self._niveau(temoin, 1.02, 1.10))
        # Avant le premier coup, rien ne change.
        self.assertAlmostEqual(self._niveau(pompee, 0.5, 0.9),
                               self._niveau(temoin, 0.5, 0.9), places=4)
        self.assertGreater(self._niveau(pompee, 1.85, 1.98),
                           0.9 * self._niveau(temoin, 1.85, 1.98))

    def test_sans_envoi_rien_ne_pompe(self):
        temoin = self._rendu(*self._sons(cable=0))
        sans = self._rendu(*self._sons(envoi=0))
        self.assertTrue(np.allclose(temoin, sans, atol=1e-6))

    def test_les_coups_d_une_autre_piste_font_pomper(self):
        """Une piste rendue seule reçoit les coups du morceau entier."""
        kick, nappe = self._sons(envoi=0)
        temoin = self._rendu(kick, nappe)
        pompee = self._rendu(kick, nappe,
                             hits=[(1.0, 2147483647), (2.0, 2147483647)])
        self.assertLess(self._niveau(pompee, 1.02, 1.10),
                        0.6 * self._niveau(temoin, 1.02, 1.10))

    def test_la_reverberation_suit_le_son_le_plus_reverbere(self):
        from delugeapp.core import dsp, render

        _kick, nappe = self._sons(cable=0x20000000)          # mi-force
        sec = SynthPreset.new("SEC").sound
        nappe.set_param("reverbAmount", 0)
        sec.set_param("reverbAmount", INT32_MIN + 1000)
        hits = [0] * 200
        hits[20] = dsp.ONE_Q31
        n = 200 * dsp.BLOCK
        gain = render._reverb_ducking([("sec", sec, [1]),
                                       ("nappe", nappe, [1])], hits, 120.0, n)
        self.assertEqual(gain.shape, (n,))
        self.assertAlmostEqual(float(gain[0]), 1.0, places=3)
        # Mi-force au plus creux : ``p = 2²⁹ − 2²⁸``, (1 − 0,5)² = 0,25.
        self.assertAlmostEqual(float(gain.min()), 0.25, places=2)
        # Le plus réverbéré n'a pas de câble : la réverbération ne pompe pas.
        nappe.set_param("reverbAmount", INT32_MIN + 10)
        self.assertIsNone(render._reverb_ducking(
            [("sec", sec, [1]), ("nappe", nappe, [1])], hits, 120.0, n))

    def test_le_fichier_garde_l_envoi(self):
        import xml.etree.ElementTree as ET

        son = SynthPreset.new("KICK").sound
        son.side_chain_send = 2147483647
        el = ET.Element("sound")
        son.to_xml(el)
        self.assertEqual(el.get("sideChainSend"), "2147483647")
        self.assertEqual(Sound.from_xml(el).side_chain_send, 2147483647)
        muet = ET.Element("sound")
        SynthPreset.new("X").sound.to_xml(muet)
        self.assertIsNone(muet.get("sideChainSend"))


class TestLfo1Global(unittest.TestCase):
    """Le LFO 1 du Deluge est global : il court d'une note à l'autre.
    L'écoute le faisait repartir à chaque note."""

    @staticmethod
    def _son():
        from delugeapp.core.model import PatchCable

        son = SynthPreset.new("BALAYAGE").sound
        son.lfo1.type = "sine"
        son.lfo1.sync_level = 0
        son.set_param("lfo1Rate", 0)
        # Rien d'autre ne court dans le temps : mod FX, delay, réverbération.
        son.mod_fx_type = "none"
        son.set_param("delayFeedback", INT32_MIN)
        son.set_param("reverbAmount", INT32_MIN)
        son.patch_cables.append(PatchCable(source="lfo1",
                                           destination="lpfFrequency",
                                           amount=0x30000000))
        return son

    def test_la_phase_avance_avec_le_morceau(self):
        from delugeapp.core import render

        son = self._son()
        depart = render._lfo1_phase(son, 0, 120.0)
        plus_tard = render._lfo1_phase(son, 44100, 120.0)
        self.assertIsNotNone(depart)
        self.assertNotEqual(depart, plus_tard)
        # Sans câble depuis le LFO 1, rien à reprendre.
        son.patch_cables.clear()
        self.assertIsNone(render._lfo1_phase(son, 44100, 120.0))

    def test_deux_notes_egales_sonnent_selon_le_lfo(self):
        from delugeapp.core import render
        from delugeapp.core.accomp import NoteEvent

        son = self._son()

        def seule(pas):
            """Une note rendue seule : ni traîne ni réverbération d'une
            autre note ne s'y mêle."""
            return render.render_parts(
                {"a": [NoteEvent(pas, 2.0, 48, 100)]}, {"a": son}, bpm=120.0,
                sr=44100, normalize=False, tail=0.1)

        # La même note, au début et 16 pas plus loin (2 s à 120 BPM).
        # En entiers : ``int(2,05 × 44 100)`` tombe un échantillon trop tôt.
        n, debut = int(0.15 * 44100), int(0.05 * 44100)
        premiere = seule(0.0)[debut:][:n]
        seconde = seule(16.0)[2 * 44100 + debut:][:n]
        self.assertGreater(float(np.max(np.abs(premiere - seconde))), 1e-3)


class TestGlisseEnFrequence(unittest.TestCase):
    """Le glissé du firmware (``Voice::render``) interpole le pas de phase,
    donc la fréquence ; l'écoute interpolait les demi-tons."""

    def test_le_milieu_d_un_glisse_d_octave(self):
        from delugeapp.core import render

        t = np.array([0.0, 0.05, 0.1])
        octaves = render._glide_octaves(12.0, t, 0.1)
        self.assertAlmostEqual(float(octaves[0]), 1.0, places=3)
        # À mi-course, getDecay4 vaut 0,2 : la fréquence a fait 20 % du
        # chemin (×1,2, soit 0,263 octave) — en demi-tons, on aurait 0,2.
        self.assertAlmostEqual(float(octaves[1]), float(np.log2(1.2)),
                               places=3)
        self.assertAlmostEqual(float(octaves[2]), 0.0, places=6)
        # Vers le bas, le même chemin en fréquence.
        bas = render._glide_octaves(-12.0, t, 0.1)
        self.assertAlmostEqual(float(bas[1]), float(np.log2(0.9)), places=3)


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
