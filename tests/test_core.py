# -*- coding: utf-8 -*-
"""Tests du noyau de Deluge Companion.

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

BAC_A_SABLE = Path(_tempfile.gettempdir()) / "deluge-companion-tests"
BAC_A_SABLE.mkdir(parents=True, exist_ok=True)
_os.environ["DELUGE_COMPANION_CONFIG"] = str(BAC_A_SABLE)


from delugeapp.core import (analysis, backup, db, deps, dxml, genres, health,
                            kitgen, midifile, organize, render, rhythm,
                            samplefix, scan, sdcard, similarity, slicer,
                            songpack, synthgen, theory, units, wav)
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
        """Le clip de 384 ticks fait 4 mesures."""
        stats = self._song().stats()
        self.assertEqual(stats["clips"], 1)
        self.assertEqual(stats["bars"], 4.0)
        self.assertEqual(stats["instruments"], 2)

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
        """Une cymbale doit durer plus longtemps qu'un charleston fermé."""
        from delugeapp.core.fixedpoint import to_display

        kit = kitgen.build_kit(self.sd, self.lib, "K",
                               slots=["Kick", "HatC", "Crash"], seed=1)
        par_role = {r.name: r.sound for r in kit.rows}
        self.assertLess(to_display(par_role["HATC"].env1.decay),
                        to_display(par_role["CRASH"].env1.decay))
        self.assertGreater(par_role["KICK"].display("volume"),
                           par_role["HATC"].display("volume"))
        self.assertEqual(par_role["HATC"].polyphonic, "choke")

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
        """Le Deluge exige exactement sept intervalles.

        Son écran réserve sept rangées de pads par octave : une gamme de
        cinq notes doit être complétée, une gamme de huit réduite.
        """
        for name in theory.SCALES:
            with self.subTest(gamme=name):
                modes = theory.deluge_mode_notes(name)
                self.assertEqual(len(modes), 7)
                self.assertEqual(modes, sorted(modes))
                self.assertEqual(len(set(modes)), 7)
                self.assertTrue(all(0 <= m < 12 for m in modes))
        self.assertEqual(theory.deluge_mode_notes("majeur"),
                         [0, 2, 4, 5, 7, 9, 11])

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
        fort = [n.pos for n in rhythm.apply_groove(base, "MPC 16B", 1.0)
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

    def test_conversion_de_resolution(self):
        """Les 24 ticks du Deluge deviennent 96 : un facteur exact de 4."""
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
        """SPEC §4.21 : 2,5 s rendues en moins de 400 ms."""
        import time

        preset = synthgen.generate(synthgen.GenOptions(genre="techno",
                                                       seed=1))
        # Premier appel écarté : il construit les tables d'onde.
        render.render_sound(preset.sound, seconds=0.2, sr=self.SR)

        durations = []
        for seed in range(5):
            other = synthgen.generate(synthgen.GenOptions(genre="ambient",
                                                          role="pad",
                                                          seed=seed,
                                                          width=1.0,
                                                          space=1.0))
            other.sound.unison_num = 8      # le cas le plus coûteux
            start = time.perf_counter()
            render.render_sound(other.sound, seconds=2.5, sr=self.SR)
            durations.append(time.perf_counter() - start)
        self.assertLess(max(durations), 0.4,
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
        """
        import statistics

        def centroid(role: str) -> float:
            values = []
            for key in genres.genre_keys():
                preset = synthgen.generate(synthgen.GenOptions(
                    genre=key, role=role, seed=1))
                mono = render.render_sound(preset.sound, seconds=1.0,
                                           sr=self.SR).mean(axis=1)
                values.append(analysis.spectral(mono, self.SR)["centroid"])
            return statistics.median(values)

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

    def test_tables_d_onde(self):
        """Les tables doivent être normalisées et bouclées."""
        for kind in ("sine", "saw", "square", "triangle", "inconnu"):
            with self.subTest(kind=kind):
                table = render._wavetable(kind, 2)
                self.assertEqual(table.size, render.TABLE_SIZE + 1)
                self.assertAlmostEqual(float(np.max(np.abs(table))), 1.0,
                                       delta=0.01)
                self.assertAlmostEqual(float(table[0]), float(table[-1]),
                                       places=5)


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
                self.assertEqual(row.sound.osc1.loop_mode, 0,
                                 "une tranche ne doit pas boucler")

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

        ports = midiport.outputs()
        if not ports:
            self.skipTest("aucun port de sortie MIDI")
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
    """``DELUGE_COMPANION_CONFIG`` déplace les réglages hors de chez l'utilisateur.

    Ce n'est pas un confort : mes propres scripts d'essai ont deux fois
    écrasé les réglages réels, et une fois en éteignant la confirmation
    d'écriture **et** la sauvegarde automatique — les deux filets qui
    protègent une carte contenant des mois de travail. La variable rend
    l'isolement possible en une ligne, au lieu de dépendre de ma vigilance.
    """

    def setUp(self):
        from delugeapp import config as config_mod

        self.config_mod = config_mod
        self._avant = os.environ.get(config_mod.CONFIG_ENV)

    def tearDown(self):
        if self._avant is None:
            os.environ.pop(self.config_mod.CONFIG_ENV, None)
        else:
            os.environ[self.config_mod.CONFIG_ENV] = self._avant

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

        reel = self.config_mod._base_dir() / self.config_mod.APP_ORG
        self.assertNotEqual(
            self.config_mod.CONFIG_DIR, reel,
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
