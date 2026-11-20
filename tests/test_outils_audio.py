# -*- coding: utf-8 -*-
"""Tests des outils sur les sons : correction, découpage, ressemblance,
attaques, sortie d'un morceau en pack et en MIDI.

Sans carte réelle ni Qt : chaque test fabrique sa carte jetable. Découpés
de ``test_core.py`` le 20 novembre 2026.

    python -m unittest tests.test_outils_audio -v
"""

from __future__ import annotations

import hashlib
import tempfile
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

from delugeapp.core import (analysis, db, health, midifile, samplefix, scan,
                            sdcard, similarity, slicer, songpack, wav)
from delugeapp.core.model import Kit, Note, Song, SynthPreset


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
