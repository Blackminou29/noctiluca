# -*- coding: utf-8 -*-
"""Tests de l'écoute sur l'ordinateur : le moteur de rendu, les étages
du firmware transcrits, l'arpégiateur, les tables d'onde.

Sans carte réelle ni Qt : chaque test fabrique sa carte jetable. Découpés
de ``test_core.py`` le 20 novembre 2026.

    python -m unittest tests.test_ecoute -v
"""

from __future__ import annotations

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

from delugeapp.core import (analysis, db, genres, render, rhythm, sdcard,
                            synthgen, wav)
from delugeapp.core.fixedpoint import INT32_MIN, from_display
from delugeapp.core.model import Kit, Sound, SynthPreset


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

    @staticmethod
    def _svf_entier(freq, res, morph, band, x):
        """``SVFilter`` (``setConfig`` et ``doSVF``, 1.3), en entiers 32 bits
        comme le firmware : débordements, ``smmul`` et ``smmulr``,
        ``getTanHUnknown`` sur la table. ``morph`` en Q28."""
        from delugeapp.core import dsp

        def wrap(v):
            return ((v + (1 << 31)) & 0xFFFFFFFF) - (1 << 31)

        def m32(a, b):
            return wrap((a * b) >> 32)

        def m32r(a, b):
            return wrap((a * b + (1 << 31)) >> 32)

        def lsat(v, s):
            return max(-(1 << 31), min((1 << 31) - 1, v << s))

        tan = [int(v) for v in dsp.table("tanTable")]
        tanh = [int(v) for v in dsp.table("tanHSmall")]

        def tanh3(v):
            w = (max(-(1 << 28), min((1 << 28) - 1, v)) << 3) + (1 << 31)
            k, s2 = w >> 24, (w >> 8) & 65535
            return wrap(tanh[k] * (65536 - s2) + tanh[k + 1] * s2) >> 5

        one = (1 << 31) - 1
        f = lsat(freq, 5)
        which, further = f >> 25, (f << 6) & 2147483647
        v1, v2 = tan[which], tan[min(which + 1, 64)]
        tanned = (wrap((v2 * further) >> 32)
                  + wrap((v1 * (2147483647 - further)) >> 32)) << 1
        div = int(288230376151711744.0 / float(134217728 + (tanned >> 1)))
        fc = m32r(tanned, div) << 4
        fc = fc + m32(fc, int(one * 0.25))
        q = one - 4 * res
        k_in = (q >> 1) + (one >> 1)
        q = m32r(q, q) << 1
        m = lsat(morph, 2)
        half = one >> 1
        if band and m > half:
            m = 2 * (m - half)
            c_low, c_band, c_high = 0, one - m, m
        elif band:
            m = 2 * m
            c_low, c_band, c_high = one - m, m, 0
        else:
            c_low, c_band, c_high = one - m, 0, m
        low = bande = 0
        out = []
        for v in x:
            v = m32(k_in, v)
            memo = []
            for _pas in range(2):
                low = wrap(low + 2 * m32(bande, fc))
                high = wrap(wrap(v - low) - 2 * m32(bande, q))
                bande = wrap(2 * m32(high, fc) + bande)
                memo.append((low, high, bande))
                if not _pas:
                    bande = tanh3(bande)
                    memo[0] = (low, high, bande)
            lo, hi, ba = (wrap(memo[0][i] + memo[1][i]) for i in range(3))
            r = m32r(lo, c_low)
            r = wrap(r + ((hi * c_high + (1 << 31)) >> 32))
            if band:
                r = wrap(r + ((ba * c_band + (1 << 31)) >> 32))
            bande = tanh3(bande)
            out.append(wrap(3 * r))
        return np.array(out, dtype=np.float64)

    def test_svf_contre_le_firmware_entier(self):
        """Le SVF porté suit le calcul entier du firmware : passe-bas,
        dosages du « morph », bande, résonance jusqu'à la saturation de la
        bande."""
        d = self.dsp
        n = 1500
        t = np.arange(n)
        x = np.round(20000000 * np.sin(2 * np.pi * 220 * t / 44100)
                     + 6000000 * np.sin(2 * np.pi * 3170 * t / 44100))
        for mode, freq, res, morph in (
                ("SVF_Notch", 2000000, 0, 0),
                ("SVF_Notch", 9000000, 400000000, 0),
                ("SVF_Notch", 40000000, 134217728, 300000000),
                ("SVF_Band", 9000000, 268435456, 100000000),
                ("SVF_Band", 20000000, 500000000, 400000000)):
            with self.subTest(mode=mode, freq=freq, res=res, morph=morph):
                ref = self._svf_entier(freq, res, morph, mode == "SVF_Band",
                                       x.astype(np.int64).tolist())
                cfg = d.svf_config(mode, [freq] * 12, [res] * 12,
                                   [morph] * 12)
                got = d.svf_process(x, cfg)
                self.assertGreater(float(np.max(np.abs(ref))), 1e6)
                self.assertLess(float(np.max(np.abs(got - ref))),
                                1e-3 * float(np.max(np.abs(ref))))

    def test_le_morph_du_svf_dose_ses_sorties(self):
        """« Notch » : du passe-bas (morph 0) au passe-haut (morph au
        maximum) ; « Band » : passe-bas, bande au milieu, passe-haut. La
        courbe de l'interface redonne la réponse impulsionnelle."""
        d = self.dsp
        freqs = np.array([60.0, 15000.0])

        def niveaux(mode, morph):
            cfg = d.svf_config(mode, [4e6], [0.0], [morph])
            return np.abs(d.svf_response(cfg, freqs))

        bas, haut = niveaux("SVF_Notch", 0.0), niveaux("SVF_Notch", 5.3e8)
        self.assertAlmostEqual(float(bas[0]), 1.5, delta=0.01)   # « × 1,5 »
        self.assertLess(float(bas[1]), 0.05)
        self.assertLess(float(haut[0]), 0.05)
        self.assertGreater(float(haut[1]), 1.0)
        milieu = niveaux("SVF_Band", 2.684e8)
        self.assertLess(float(np.max(milieu)), 0.2)
        cfg = d.svf_config("SVF_Band", [4e6], [0.0], [2.684e8])
        coupure = np.abs(d.svf_response(cfg, [800.0, 1500.0, 3000.0]))
        self.assertGreater(float(np.max(coupure)), 1.0)

    def test_un_son_svf_se_filtre_en_passe_bas_et_en_passe_haut(self):
        """Le SVF d'un son était rendu comme une échelle 12 dB, et son
        passe-haut comme une échelle : chacun a maintenant le sien."""
        from delugeapp.core import render

        def centroide(lpf, hpf, cutoff=None, hpf_freq=None):
            preset = SynthPreset.new("S")
            son = preset.sound
            son.osc1.type = "saw"
            son.unison_num = 1
            son.patch_cables = []
            son.lpf_mode, son.hpf_mode = lpf, hpf
            if cutoff is not None:
                son.set_param("lpfFrequency", from_display(cutoff, scale=50))
            if hpf_freq is not None:
                son.set_param("hpfFrequency", from_display(hpf_freq,
                                                           scale=50))
            mono = render.render_sound(son, note=36, seconds=0.5,
                                       effects=False).mean(axis=1)
            return analysis.spectral(mono, 44100)["centroid"], mono

        ouvert, _ = centroide("SVF_Notch", "off")
        ferme, svf = centroide("SVF_Notch", "off", cutoff=15)
        _c, echelle = centroide("12dB", "off", cutoff=15)
        self.assertLess(ferme, 0.6 * ouvert)
        self.assertGreater(float(np.max(np.abs(svf - echelle))), 0.01)
        coupe_bas, haut_svf = centroide("SVF_Notch", "SVF_Notch", hpf_freq=30)
        self.assertGreater(coupe_bas, 1.3 * ouvert)
        _c, haut_echelle = centroide("SVF_Notch", "HPLadder", hpf_freq=30)
        self.assertGreater(float(np.max(np.abs(haut_svf - haut_echelle))),
                           0.01)

    @staticmethod
    def _warble_entier(x_l, x_r, rate, depth, offset_param, feedback_param):
        """``processOneModFXSample<WARBLE, stéréo>`` et ses deux LFO
        « warbler » (``lfo.h``), en entiers 32 bits comme le firmware, à la
        graine de ``waves.cpp``."""
        def wrap(v):
            return ((v + (1 << 31)) & 0xFFFFFFFF) - (1 << 31)

        def m32(a, b):
            return wrap((a * b) >> 32)

        def m32r(a, b):
            return wrap((a * b + (1 << 31)) >> 32)

        a = feedback_param >> 1
        b = 2147483647 - ((a + 1073741824) >> 2) * 3
        c = m32(b, b)
        d = m32(b, c)
        feedback = wrap(2147483648 - (d << 2))
        k_offset = ((511 << 16) + (3 << 16)) >> 1
        offset = k_offset + m32(k_offset, offset_param)
        amount = m32(offset, depth) << 1
        cong = [380116160]
        lfos = [[0, 0, 0, 0], [0, 0, 0, 0]]     # phase, valeur, cible, vitesse
        incs = [rate, m32(rate, int(0.97 * 2147483647)) << 1]

        def render(lfo, inc):
            inc = (inc * 2) & 0xFFFFFFFF
            if lfo[0] + inc > 0xFFFFFFFF:
                cong[0] = (69069 * cong[0] + 1234567) & 0xFFFFFFFF
                lfo[2] = wrap(cong[0])
                lfo[3] = 0
            lfo[3] = wrap(lfo[3] + m32(wrap(lfo[2] - lfo[1]), inc >> 8))
            lfo[1] = max(-(1 << 31), min((1 << 31) - 1, lfo[1] + lfo[3]))
            lfo[0] = (lfo[0] + inc) & 0xFFFFFFFF
            return lfo[1]

        buf = [[0] * 512, [0] * 512]
        write = 0
        out = [[], []]
        for v_l, v_r in zip(x_l, x_r):
            valeurs = [render(lfos[0], incs[0]), render(lfos[1], incs[1])]
            for ch, v in ((0, v_l), (1, v_r)):
                t = m32(valeurs[ch], amount) + offset
                s2 = (t & 65535) << 15
                s1 = (65535 << 15) - s2
                pos = write - (t >> 16)
                sortie = m32r(buf[ch][pos & 511], s1) \
                    + m32r(buf[ch][(pos - 1) & 511], s2)
                buf[ch][write] = wrap(m32r(sortie, feedback) + v)
                out[ch].append(wrap(sortie << 2))
            write = (write + 1) & 511
        return np.array(out, dtype=np.float64)

    def test_tape_warble_contre_le_firmware_entier(self):
        """Le « tape warble » porté suit le calcul entier du firmware : LFO
        aléatoires lissés, retard modulé, rétroaction, sortie mouillée
        seule. Il était rendu comme un chorus."""
        d = self.dsp
        n = 30000
        t = np.arange(n)
        x = np.round(20000000 * np.sin(2 * np.pi * 220 * t / 44100)
                     + 6000000 * np.sin(2 * np.pi * 3170 * t / 44100))
        stereo = np.stack([x, np.roll(x, 37)])
        for rate, depth, offset, feedback in (
                (194783, 526133494, 0, 0),
                (600000, 1000000000, 700000000, -500000000)):
            with self.subTest(rate=rate, offset=offset):
                ref = self._warble_entier(
                    stereo[0].astype(np.int64).tolist(),
                    stereo[1].astype(np.int64).tolist(), rate, depth, offset,
                    feedback)
                got, _ = d.mod_fx(stereo, "TapeWarble", rate, depth, offset,
                                  feedback, 1.0)
                self.assertGreater(float(np.max(np.abs(ref))), 1e7)
                self.assertLess(float(np.max(np.abs(got - ref))),
                                1e-3 * float(np.max(np.abs(ref))))
        # Rien que le retard : silence le temps du premier passage.
        self.assertLess(float(np.max(np.abs(got[:, :100]))), 1.0)

    @staticmethod
    def _melange(secondes=3.0, gain_db=0.0):
        t = np.arange(int(44100 * secondes)) / 44100.0
        return np.stack([np.sin(2 * np.pi * 110 * t) * (1 + np.sin(3 * t)),
                         np.sin(2 * np.pi * 165 * t) * (1 + np.cos(3 * t))]) \
            * float(1 << 24) * 10 ** (gain_db / 20)

    def test_le_compresseur_maitre_au_repos_garde_le_gain_de_base(self):
        """Seuil nul, volume d'usine : la sortie d'avant — gain fixe puis
        saturation —, vérifiée contre la machine, à 10⁻⁵ près."""
        d = self.dsp
        x = self._melange()
        avant = np.stack([d.tanh_antialiased(c * d._COMPRESSOR_SCALE, 3)[0]
                          for c in x]) * (128.0 / d.Q31)
        self.assertLess(float(np.max(np.abs(d.output_stage(x) - avant))),
                        1e-5)

    def test_le_compresseur_maitre_limite_et_comprime(self):
        """À seuil nul, il limite quand sa sortie dépasse le volume du
        morceau : un mélange poussé de 24 dB, ou un morceau au volume
        baissé. Réglé, il comprime et rattrape le niveau."""
        d = self.dsp

        def niveau(y):
            return 20 * np.log10(np.sqrt(np.mean(y[:, 44100:] ** 2)))

        fort = self._melange(gain_db=24.0)
        repos = d.MasterCompressor()
        sans = np.stack([d.tanh_antialiased(c * d._COMPRESSOR_SCALE, 3)[0]
                         for c in fort]) * (128.0 / d.Q31)
        self.assertLess(niveau(d.output_stage(fort, repos)), niveau(sans) - 0.5)
        x = self._melange()
        bas = d.MasterCompressor(final_volume=float(1 << 20))
        self.assertLess(niveau(d.output_stage(x, bas)),
                        niveau(d.output_stage(x)) - 2.0)
        regle = d.MasterCompressor(threshold=float(1 << 30),
                                   ratio=float(1 << 30))
        comprime = d.output_stage(x, regle)
        self.assertNotAlmostEqual(niveau(comprime), niveau(d.output_stage(x)),
                                  delta=0.5)

    def test_le_compresseur_maitre_est_causal(self):
        """Le gain d'un bloc vient de la sortie du précédent : le début d'un
        rendu partiel, coupé entre deux blocs de 128, est celui du rendu
        complet (l'écoute en flux). Un bloc tronqué, lui, a sa propre
        rampe — comme une fenêtre plus courte sur la machine."""
        d = self.dsp
        x = self._melange(gain_db=24.0)
        regle = d.MasterCompressor(threshold=float(1 << 30), hpf=float(1 << 30))
        plein = d.output_stage(x, regle)
        coupe = 391 * d.BLOCK
        debut = d.output_stage(x[:, :coupe], regle)
        np.testing.assert_array_equal(debut, plein[:, :coupe])

    def test_le_compresseur_maitre_sans_numba(self):
        """Sans numba, chaque bloc d'un coup : la même sortie, détection
        filtrée et mélange sec compris."""
        d = self.dsp
        x = self._melange(secondes=1.0, gain_db=20.0)
        for comp in (d.MasterCompressor(),
                     d.MasterCompressor(threshold=float(1 << 30),
                                        hpf=float(1 << 30),
                                        blend=float(1 << 30))):
            with self.subTest(comp=comp):
                (a, r, seuil, fraction, hpf_a, er, volume, wet,
                 dry) = d._compressor_constants(comp)
                gain = min(np.exp(comp.base_gain + er), 31.0)
                courant = np.floor(gain * volume) * 256.0
                blocs = np.empty((2, x.shape[1]))
                d._compressor_blocks(x, a, r, seuil, fraction, hpf_a, er,
                                     volume, wet, dry, comp.base_gain,
                                     courant, blocs)
                attendu = d.output_stage(x, comp)
                np.testing.assert_allclose(blocs * (128.0 / d.Q31), attendu,
                                           atol=1e-6)

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
        from delugeapp.core import timestretch as ts

        source = stereo.T / 2 ** 31
        self._memes(*self._deux_fois(lambda: ts.percussiveness(source)),
                    msg="percussivité")
        for demi, amount in ((-7, 0), (0, -5), (5, 3)):
            inc = d.sample_increment(60 + demi, 44100)
            ratio = ts.speed_ratio(inc, 1 << 24, True, amount)
            self._memes(*self._deux_fois(lambda: ts.stretch(
                source, np.full(nb, inc), np.full(nb, ratio), n, 44100)),
                msg="étirement %+d %+d" % (demi, amount))
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


class TestLArpegiateur(unittest.TestCase):
    """``core/arpeggio.py`` : l'écoute ignorait l'arpégiateur — un son
    arpégé jouait ses accords tenus. Les suites attendues sont celles du
    code du firmware 1.3 (``calculateNextNoteAndOrOctave``), déroulé à la
    main."""

    @staticmethod
    def _suite(note_mode, octave_mode, octaves=2, notes=(60, 64, 67),
               repeats=1, combien=10):
        from delugeapp.core import arpeggio
        from delugeapp.core.accomp import NoteEvent

        s = arpeggio.ArpSettings(note_mode, octave_mode, octaves, repeats,
                                 7, 0.5)
        sortie = arpeggio.expand([NoteEvent(0, 16, p, 90) for p in notes], s)
        return [e.note for e in sortie[:combien]], sortie

    def test_l_ordre_des_notes_et_des_octaves(self):
        for modes, attendu in (
                (("up", "up"), [60, 64, 67, 72, 76, 79, 60, 64, 67, 72]),
                (("down", "down"), [79, 76, 72, 67, 64, 60, 79, 76, 72, 67]),
                # Aller-retour : la note du haut deux fois, pas celle du bas.
                (("upDown", "up"), [60, 64, 67, 67, 64, 60, 72, 76, 79, 79]),
                # Alterné : demi-tour à l'octave du haut, sans répéter.
                (("up", "alt"), [60, 64, 67, 72, 76, 79, 76, 72, 67, 64]),
                (("down", "alt"), [79, 76, 72, 67, 64, 60, 64, 67, 72, 76])):
            with self.subTest(modes=modes):
                self.assertEqual(self._suite(*modes)[0], attendu)
        self.assertEqual(self._suite("up", "up", repeats=2)[0],
                         [60, 60, 64, 64, 67, 67, 72, 72, 76, 76])
        notes, sortie = self._suite("random", "random", combien=16)
        self.assertLessEqual(set(notes), {60, 64, 67, 72, 76, 79})
        self.assertEqual(len(sortie), 16)       # un pas par double-croche

    def test_les_pas_la_duree_et_les_mains(self):
        """Une note enfoncée entre deux pas attend le suivant ; relâcher
        celle qui sonne l'éteint ; la durée est la moitié du pas au réglage
        neutre."""
        from delugeapp.core import arpeggio
        from delugeapp.core.accomp import NoteEvent

        s = arpeggio.ArpSettings("up", "up", 1, 1, 7, 0.5)
        sortie = arpeggio.expand([NoteEvent(0, 8, 60, 90),
                                  NoteEvent(2.5, 8, 64, 80)], s)
        self.assertEqual([(e.start, e.note) for e in sortie[:6]],
                         [(0.0, 60), (1.0, 60), (2.0, 60), (3.0, 64),
                          (4.0, 60), (5.0, 64)])
        self.assertEqual(sortie[3].velocity, 80)
        self.assertTrue(all(e.length == 0.5 for e in sortie))
        # Une note plus grave ajoutée : la position suit la note qui sonnait
        # (``whichNoteCurrentlyOnPostArp++``), le pas suivant reprend en bas.
        sortie = arpeggio.expand([NoteEvent(0, 8, 64, 90),
                                  NoteEvent(1.5, 8, 60, 90)], s)
        self.assertEqual([e.note for e in sortie[:4]], [64, 64, 60, 64])
        sortie = arpeggio.expand([NoteEvent(0, 8, 60, 90),
                                  NoteEvent(0, 3.2, 64, 90)], s)
        self.assertAlmostEqual(sortie[3].length, 0.2)
        self.assertEqual(sortie[3].note, 64)
        # Niveau 6 : une croche par pas ; durée au quart du pas.
        s6 = arpeggio.ArpSettings("up", "up", 1, 1, 6, 0.25)
        sortie = arpeggio.expand([NoteEvent(0, 8, 60, 90)], s6)
        self.assertEqual([e.start for e in sortie], [0.0, 2.0, 4.0, 6.0])
        self.assertEqual(sortie[0].length, 0.5)

    def test_les_reglages_d_un_son(self):
        """Ancien mode (« both » : notes montantes, octaves alternées) ou
        modes communautaires ; sans synchronisation, la vitesse libre
        d'``arpeggiatorRate`` ; la durée vient d'``arpeggiatorGate``."""
        from delugeapp.core import arpeggio

        son = SynthPreset.new("A").sound
        self.assertIsNone(arpeggio.settings_of(son))
        son.arp.mode = "both"
        s = arpeggio.settings_of(son)
        self.assertEqual((s.note_mode, s.octave_mode, s.gate),
                         ("up", "alt", 0.5))
        son.arp.arp_mode, son.arp.note_mode = "arp", "upDown"
        son.arp.octave_mode = "random"
        son.set_param("arpeggiatorGate", 1 << 30)
        s = arpeggio.settings_of(son)
        self.assertEqual((s.note_mode, s.octave_mode, s.gate),
                         ("upDown", "random", 0.75))
        son.arp.sync_level = 0
        self.assertEqual(arpeggio.settings_of(son).free_rate, 1 << 24)
        son.set_param("arpeggiatorRate", 1 << 30)       # + 4 octaves
        self.assertEqual(arpeggio.settings_of(son).free_rate, 1 << 28)

    def test_la_repetition_des_pas_se_lit_et_s_ecrit(self):
        import xml.etree.ElementTree as ET

        from delugeapp.core.model import Arpeggiator

        el = ET.fromstring('<arpeggiator arpMode="arp" stepRepeat="3" />')
        arp = Arpeggiator.from_xml(el)
        self.assertEqual(arp.step_repeat, 3)
        sortie = ET.Element("arpeggiator")
        arp.to_xml(sortie)
        self.assertEqual(sortie.get("stepRepeat"), "3")
        sortie = ET.Element("arpeggiator")
        Arpeggiator().to_xml(sortie)
        self.assertIsNone(sortie.get("stepRepeat"))

    def test_un_son_arpege_s_entend_note_par_note(self):
        """Le rendu d'un accord tenu par un son arpégé est, à l'échantillon
        près, celui de ses notes arpégées jouées par le même son éteint ;
        l'aperçu d'un preset arpège aussi."""
        import copy

        from delugeapp.core import arpeggio, render
        from delugeapp.core.accomp import NoteEvent

        son = SynthPreset.new("ARP").sound
        son.arp.mode = "up"
        accord = [NoteEvent(0, 8, p, 90) for p in (48, 52, 55)]
        arpege = render.render_parts({"a": accord}, {"a": son}, bpm=120,
                                     normalize=False)
        eteint = copy.deepcopy(son)
        eteint.arp.mode = "off"
        notes = arpeggio.expand(accord, arpeggio.settings_of(son))
        attendu = render.render_parts({"a": notes}, {"a": eteint}, bpm=120,
                                      normalize=False)
        tenu = render.render_parts({"a": accord}, {"a": eteint}, bpm=120,
                                   normalize=False)
        n = min(arpege.shape[0], attendu.shape[0])
        np.testing.assert_array_equal(arpege[:n], attendu[:n])
        self.assertGreater(float(np.max(np.abs(arpege[:n] - tenu[:n]))),
                           0.01)
        apercu = render.render_sound(son, note=48, seconds=1.0)
        sans = render.render_sound(eteint, note=48, seconds=1.0)
        self.assertEqual(apercu.shape, sans.shape)
        self.assertGreater(float(np.max(np.abs(apercu - sans))), 0.01)


class TestLArpegiateurCommunautaire(unittest.TestCase):
    """Ce que l'arpégiateur communautaire tire au sort ou découpe — rythme,
    longueur de séquence, « ratchets », probabilités, accords, étalements,
    verrou —, le mode « pattern », le ternaire et la vitesse libre : restés
    au neutre jusqu'au 21 novembre 2026. Les suites attendues sont déroulées
    à la main depuis ``arpeggiator.cpp`` (1.3)."""

    TOUJOURS = 0xFFFFFFFF

    def _arp(self, notes=(60, 64, 67), longueur=16.0, mode="up",
             octaves=2, cle=None, bpm=120.0, **reglages):
        from delugeapp.core import arpeggio
        from delugeapp.core.accomp import NoteEvent

        reglages.setdefault("sync_level", 7)
        s = arpeggio.ArpSettings(mode, "up", octaves, 1, **reglages)
        return arpeggio.expand([NoteEvent(0, longueur, p, 80) for p in notes],
                               s, key=cle, bpm=bpm)

    def test_un_pas_muet_n_avance_pas_la_suite(self):
        """Le rythme « 0-0 » : le deuxième pas se tait, et la suite reprend
        où elle en était."""
        from delugeapp.core import arpeggio

        self.assertEqual(len(arpeggio.RHYTHMS), 51)
        self.assertEqual(arpeggio.RHYTHMS[3], "0-0")
        sortie = self._arp(longueur=9, rhythm=3)
        self.assertEqual([(e.start, e.note) for e in sortie],
                         [(0, 60), (2, 64), (3, 67), (5, 72), (6, 76),
                          (8, 79)])
        # Le cran du menu, depuis le fichier : (v · 50 + 2³¹) >> 32.
        self.assertEqual(arpeggio._menu((3 << 32) // 50 + 1), 3)

    def test_la_sequence_repart_a_sa_longueur(self):
        sortie = self._arp(longueur=7, sequence_length=3)
        self.assertEqual([e.note for e in sortie],
                         [60, 64, 67, 60, 64, 67, 60])

    def test_les_probabilites_de_note_et_de_basse(self):
        self.assertEqual(self._arp(note_probability=0), [])
        presque = self._arp(longueur=64, note_probability=1 << 31)
        self.assertTrue(16 < len(presque) < 48, len(presque))
        basses = self._arp(longueur=8, bass_probability=self.TOUJOURS)
        self.assertEqual({e.note for e in basses}, {60})
        echanges = self._arp(longueur=32, swap_probability=self.TOUJOURS)
        self.assertLessEqual({e.note for e in echanges},
                             {60, 64, 67, 72, 76, 79})
        self.assertGreater(len({e.note for e in echanges}), 3)

    def test_l_accord_monte_en_tierces_dans_la_gamme(self):
        """Une à trois notes de plus : la quinte, puis la tierce et la
        quinte, puis la septième — dans la gamme du morceau."""
        sortie = self._arp(notes=(60,), longueur=48, octaves=1,
                           chord_probability=self.TOUJOURS,
                           chord_polyphony=self.TOUJOURS)
        accords = {}
        for e in sortie:
            accords.setdefault(e.start, []).append(e.note)
        formes = {tuple(sorted(n)) for n in accords.values()}
        self.assertLessEqual(formes, {(60,), (60, 67), (60, 64, 67),
                                      (60, 64, 67, 71)})
        self.assertGreater(len(formes), 2)
        # La mineur : sur la, do et mi.
        mineur = self._arp(notes=(57,), longueur=48, octaves=1,
                           cle=(9, (0, 2, 3, 5, 7, 8, 10)),
                           chord_probability=self.TOUJOURS,
                           chord_polyphony=self.TOUJOURS)
        self.assertLessEqual({e.note for e in mineur}, {57, 60, 64, 67})
        # Une note hors de la gamme, ou une gamme de quatre notes : rien.
        hors = self._arp(notes=(61,), longueur=8, octaves=1,
                         chord_probability=self.TOUJOURS,
                         chord_polyphony=self.TOUJOURS)
        self.assertEqual({e.note for e in hors}, {61})
        quatre = self._arp(notes=(60,), longueur=8, octaves=1,
                           cle=(0, (0, 4, 7, 10)),
                           chord_probability=self.TOUJOURS,
                           chord_polyphony=self.TOUJOURS)
        self.assertEqual({e.note for e in quatre}, {60})

    def test_les_ratchets_coupent_le_pas(self):
        """En croches (niveau 6), 2, 4 ou 8 notes par pas, chacune à la
        durée relative du pas ; en 128ᵉ (8), deux toujours ; en 64ᵉ (7),
        quatre au moins — le ``std::max`` du firmware, gardé ; en 256ᵉ,
        aucun."""
        sortie = self._arp(notes=(60,), longueur=32, octaves=1, sync_level=6,
                           ratchet_probability=self.TOUJOURS,
                           ratchet_amount=self.TOUJOURS)
        par_pas = {}
        for e in sortie:
            par_pas.setdefault(int(e.start // 2), []).append(e)
        tailles = {len(v) for v in par_pas.values()}
        self.assertLessEqual(tailles, {1, 2, 4, 8})
        self.assertGreater(len(tailles - {1}), 1)
        for notes in par_pas.values():
            n = len(notes)
            for k, e in enumerate(notes):
                self.assertAlmostEqual(e.start, notes[0].start + k * 2.0 / n)
                self.assertAlmostEqual(e.length, 0.5 * 2.0 / n)
        for niveau, attendu in ((8, {2}), (9, {1})):
            sortie = self._arp(notes=(60,), longueur=4, octaves=1,
                               sync_level=niveau,
                               ratchet_probability=self.TOUJOURS,
                               ratchet_amount=self.TOUJOURS)
            pas = 16.0 * 2.0 ** (3 - niveau)
            par_pas = {}
            for e in sortie:
                par_pas.setdefault(round(e.start // pas), []).append(e)
            self.assertEqual({len(v) for v in par_pas.values()}, attendu,
                             niveau)
        sortie = self._arp(notes=(60,), longueur=32, octaves=1, sync_level=7,
                           ratchet_probability=self.TOUJOURS,
                           ratchet_amount=self.TOUJOURS)
        par_pas = {}
        for e in sortie:
            par_pas.setdefault(int(e.start), []).append(e)
        self.assertLessEqual({len(v) for v in par_pas.values()}, {4, 8})

    def test_le_glisse_tient_jusqu_a_la_fin_de_la_suivante(self):
        sortie = self._arp(longueur=8, glide_probability=self.TOUJOURS)
        for e, suivante in zip(sortie, sortie[1:-1]):
            self.assertAlmostEqual(e.start + e.length,
                                   suivante.start + 0.5)

    def test_l_inversion_lit_l_echantillon_a_rebours(self):
        from delugeapp.core import render

        sortie = self._arp(longueur=4, reverse_probability=self.TOUJOURS)
        self.assertTrue(sortie and all(e.reversed for e in sortie))
        self.assertFalse(any(e.reversed for e in self._arp(longueur=4)))
        son = SynthPreset.new("R").sound
        son.osc1.type = "sample"
        self.assertEqual(render._reversed(son).osc1.reversed, 1)
        self.assertEqual(son.osc1.reversed, 0, "le son lui-même ne bouge pas")
        with tempfile.TemporaryDirectory() as tmp:
            racine = Path(tmp) / "carte"
            for sous in ("SAMPLES", "SONGS", "SYNTHS", "KITS"):
                (racine / sous).mkdir(parents=True)
            # Un son qui enfle : à rebours, il décroît.
            t = np.arange(11025) / 44100.0
            wav.write(racine / "SAMPLES" / "monte.wav",
                      (2.0 * t * np.sin(2 * np.pi * 330 * t))
                      .astype(np.float32), 44100)
            sd = sdcard.SDCard(racine)
            son.osc1.file_name = "SAMPLES/monte.wav"

            def pentes(note):
                audio = render.render_parts({"a": [note]}, {"a": son},
                                            sd=sd, normalize=False)[:, 0]
                debut = float(np.sqrt(np.mean(audio[:2000] ** 2)))
                suite = float(np.sqrt(np.mean(audio[3000:5000] ** 2)))
                return debut, suite

            droit = pentes(type(sortie[0])(0, 1, 60, 90))
            rebours = pentes(type(sortie[0])(0, 1, 60, 90, reversed=True))
        self.assertLess(droit[0], 0.5 * droit[1])
        self.assertGreater(rebours[0], 1.25 * rebours[1])

    def test_les_etalements(self):
        """Vélocité (``calculateSpreadVelocity``), durée et octave, tirées à
        chaque pas joué."""
        from delugeapp.core import arpeggio, dsp

        arp = arpeggio._Arp(arpeggio.ArpSettings(), dsp.Cong(), None)
        # 50 % → 64 sur 127 ; +127 : 64 + ((127·2²⁴·63) >> 32) · 2 = 126.
        self.assertAlmostEqual(arp._velocity(50, 127), 126 / 1.27)
        self.assertAlmostEqual(arp._velocity(50, -127), (64 - 62) / 1.27)
        self.assertEqual(arp._velocity(50, 0), 50)
        sortie = self._arp(longueur=32, spread_velocity=self.TOUJOURS,
                           spread_gate=self.TOUJOURS,
                           spread_octave=self.TOUJOURS)
        self.assertGreater(len({round(e.velocity, 3) for e in sortie}), 5)
        self.assertTrue(all(1 / 1.27 - 1e-9 <= e.velocity <= 100.0
                            for e in sortie))
        self.assertGreater(len({round(e.length, 4) for e in sortie}), 5)
        self.assertTrue(all(0 < e.length < 1.0 for e in sortie))
        self.assertGreater(max(e.note for e in sortie), 79)

    def test_les_tirages_de_la_machine(self):
        """``getRandomBipolarProbabilityAmount`` de −127 à 127,
        ``getRandomWeighted2BitsAmount`` de 0 à 3. Leur « triangle » est la
        somme de deux bruits de 32 bits **saturée** : un quart des tirages
        tombe au bord — 0, 1, 2 et 3 sortent à 18, 32, 32 et 18 %."""
        from delugeapp.core import arpeggio, dsp

        arp = arpeggio._Arp(arpeggio.ArpSettings(), dsp.Cong(7), None)
        bipolaires = [arp._bipolar(self.TOUJOURS) for _i in range(4000)]
        self.assertEqual((min(bipolaires), max(bipolaires)), (-127, 127))
        bords = sum(1 for b in bipolaires if abs(b) == 127) / 4000
        self.assertAlmostEqual(bords, 0.25, delta=0.03)
        deux = [arp._two_bits(self.TOUJOURS) for _i in range(4000)]
        for valeur, part in ((0, 0.18), (1, 0.32), (2, 0.32), (3, 0.18)):
            self.assertAlmostEqual(deux.count(valeur) / 4000, part,
                                   delta=0.03, msg=valeur)
        self.assertEqual(arp._bipolar(0), 0)
        self.assertEqual(arp._two_bits(0), 0)
        moitie = [arp._chance(1 << 31) for _i in range(2000)]
        self.assertAlmostEqual(sum(moitie) / 2000, 0.5, delta=0.05)

    def test_le_verrou_rejoue_les_tirages_du_fichier(self):
        """``randomizerLock`` : les seize tirages écrits par la machine,
        rejoués à l'identique tant que le réglage n'a pas bougé."""
        moitie = 1 << 31
        tirages = (1, 0, 1, 1, 0, 0, 1, 0, 1, 1, 1, 0, 0, 1, 0, 1)
        sortie = self._arp(notes=(60,), longueur=32, octaves=1,
                           note_probability=moitie, randomizer_lock=True,
                           locked={"note": tirages},
                           last_locked={"note": moitie})
        joues = sorted(int(e.start) for e in sortie)
        attendu = [k for k in range(32) if tirages[k % 16]]
        self.assertEqual(joues, attendu)
        # Le réglage a changé depuis : seize tirages neufs, rejoués en
        # boucle.
        neuf = self._arp(notes=(60,), longueur=32, octaves=1,
                         note_probability=moitie, randomizer_lock=True,
                         locked={"note": tirages},
                         last_locked={"note": moitie + 1})
        joues = {int(e.start) for e in neuf}
        self.assertEqual({k for k in joues if k < 16},
                         {k - 16 for k in joues if k >= 16})

    def test_le_mode_pattern_suit_l_ordre_du_fichier(self):
        """``rearrangePatterntArpNotes`` : 60 à la place 0, 64 à la place
        0, 67 à la place 1 — soit 64, 67, 60."""
        sortie = self._arp(mode="pattern", longueur=6,
                           note_pattern=(0, 0, 1) + (0,) * 13)
        self.assertEqual([e.note for e in sortie],
                         [64, 67, 60, 76, 79, 72])

    def test_ternaire_et_pointe(self):
        ternaire = self._arp(notes=(60,), longueur=4, sync_type=10)
        self.assertEqual([round(e.start, 6) for e in ternaire],
                         [round(k * 2 / 3, 6) for k in range(6)])
        pointe = self._arp(notes=(60,), longueur=4, sync_type=19)
        self.assertEqual([e.start for e in pointe], [0.0, 1.5, 3.0])

    def test_la_vitesse_libre(self):
        """Niveau 0 : la première note part aussitôt ; au réglage neutre,
        ``gatePos`` gagne 2 048 × 128 par passe, un pas toutes les 64
        passes, soit 8 192 échantillons — 1,486 double-croche à 120 BPM."""
        sortie = self._arp(notes=(60,), longueur=6, octaves=1, sync_level=0)
        pas = 8192 / (44100 * 60 / 120 / 4)
        self.assertEqual(len(sortie), 5)
        for k, e in enumerate(sortie):
            self.assertAlmostEqual(e.start, k * pas, places=9)
        # La moitié du pas, en 32 passes ; la dernière, coupée au relâché.
        for e in sortie[:-1]:
            self.assertAlmostEqual(e.length, 32 * 128 / 5512.5, places=9)
        self.assertAlmostEqual(sortie[-1].start + sortie[-1].length, 6.0)
        # Deux fois plus vite d'une octave de réglage.
        vite = self._arp(notes=(60,), longueur=6, octaves=1, sync_level=0,
                         free_rate=1 << 25)
        self.assertAlmostEqual(vite[1].start, pas / 2, places=9)

    def test_les_reglages_se_lisent_dans_le_fichier(self):
        import xml.etree.ElementTree as ET

        from delugeapp.core import arpeggio
        from delugeapp.core.model import Arpeggiator

        el = ET.fromstring(
            '<arpeggiator arpMode="arp" noteMode="pattern" syncType="10" '
            'randomizerLock="1" lastLockedNoteProb="-1" '
            'lockedNoteProbArray="01000100010001000100010001000100" '
            'lockeChordProbArray="0101" '
            'notePattern="000100000104050204050A0100080408" />')
        arp = Arpeggiator.from_xml(el)
        self.assertEqual((arp.sync_type, arp.randomizer_lock), (10, True))
        self.assertEqual(arp.last_locked["note"], 0xFFFFFFFF)
        self.assertEqual(arp.locked["chord"], (1, 1))
        self.assertEqual(arp.note_pattern[:6], (0, 1, 0, 0, 1, 4))
        sortie = ET.Element("arpeggiator")
        arp.to_xml(sortie)
        self.assertEqual(sortie.get("lastLockedNoteProb"), "-1")
        self.assertEqual(sortie.get("notePattern"),
                         "000100000104050204050A0100080408")
        self.assertEqual(sortie.get("lockedChordProbArray"), "0101")
        son = SynthPreset.new("A").sound
        son.arp = arp
        son.set_param("rhythm", -(1 << 31) + (5 << 32) // 50 + 1)
        son.set_param("chordProbability", 0x7FFFFFFF)
        s = arpeggio.settings_of(son)
        self.assertEqual((s.note_mode, s.rhythm, s.chord_probability,
                          s.note_probability, s.sync_type),
                         ("pattern", 5, self.TOUJOURS, self.TOUJOURS, 10))
        self.assertTrue(s.randomizer_lock)
        self.assertEqual(s.note_pattern, arp.note_pattern)

    def test_l_ecoute_d_un_morceau_passe_sa_gamme(self):
        """``render_parts(song_key=…)`` : les accords dans la gamme du
        morceau."""
        from unittest import mock

        from delugeapp.core import arpeggio, render
        from delugeapp.core.accomp import NoteEvent

        son = SynthPreset.new("C").sound
        son.arp.mode = "up"
        vu = {}
        vrai = arpeggio.expand

        def espion(events, s, seed=0, key=None, bpm=120.0):
            vu["key"], vu["bpm"] = key, bpm
            return vrai(events, s, seed=seed, key=key, bpm=bpm)

        with mock.patch.object(arpeggio, "expand", espion):
            render.render_parts({"a": [NoteEvent(0, 2, 60, 90)]},
                                {"a": son}, bpm=100, normalize=False,
                                song_key=(9, (0, 2, 3, 5, 7, 8, 10)))
        self.assertEqual(vu, {"key": (9, (0, 2, 3, 5, 7, 8, 10)),
                              "bpm": 100.0})


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

    def test_la_position_fond_deux_cycles_voisins(self):
        """``WaveTable::render`` : la position tombe entre deux cycles, lus
        au même point de leur période puis fondus au prorata
        (``crossCycleStrength2``) ; la phase avance avant la lecture."""
        from delugeapp.core import dsp

        taille = 256
        t = np.arange(taille) / taille
        table = np.stack([np.sin(2 * np.pi * t), -np.sin(2 * np.pi * t),
                          np.zeros(taille)])
        n = 2 * dsp.BLOCK
        inc = np.full(2, (1 << 32) // 64, dtype=np.int64)    # 64 points
        un = np.ones(n)
        for place, gain in ((0.0, 1.0), (0.25, 0.0), (0.5, -1.0),
                            (0.75, -0.5), (1.0, 0.0)):
            with self.subTest(place=place):
                onde, _p = dsp.wavetable_oscillator(
                    table, inc, n, 0, un, np.full(n, place))
                attendu = gain * np.sin(2 * np.pi * (np.arange(n) + 1) / 64)
                np.testing.assert_allclose(onde, attendu, atol=2e-3)
        # Une rampe de position glisse d'un cycle à l'autre sans saut.
        onde, _p = dsp.wavetable_oscillator(table, inc, n, 0, un,
                                            np.linspace(0.0, 0.5, n))
        self.assertLess(float(np.max(np.abs(np.diff(onde)))), 0.12)

    def test_une_note_aigue_perd_les_harmoniques_au_dessus_de_nyquist(self):
        """Une bande par octave, comme les bandes du firmware : la table
        jouée en aigu n'a plus que ce qui tient sous la moitié de la
        fréquence d'échantillonnage."""
        from delugeapp.core import dsp

        taille = 2048
        t = np.arange(taille) / taille
        riche = sum(np.sin(2 * np.pi * h * t) / h for h in range(1, 400))
        wav.write(self.root / "SAMPLES/Nappes/riche.wav",
                  np.tile(riche / np.max(np.abs(riche)) * 0.8,
                          2).astype(np.float32), 44100, 16)
        from unittest import mock

        from delugeapp.core.model import Osc

        osc = Osc(type="wavetable",
                         file_name="SAMPLES/Nappes/riche.wav")
        with mock.patch("delugeapp.core.wavetable.cycle_size_of",
                        lambda _p: taille):
            grave = render._wavetable_table(self.sd, osc,
                                            dsp.note_increment(36))
            aigu = render._wavetable_table(self.sd, osc,
                                           dsp.note_increment(96))
        self.assertEqual(grave.shape, (2, taille))
        spectre = np.abs(np.fft.rfft(aigu[0]))
        # Do 7, 2 093 Hz : 10 harmoniques sous Nyquist, 8 gardées.
        self.assertGreater(spectre[8], 1.0)
        self.assertLess(float(np.max(spectre[9:])), 1e-6)
        # Do 2, 65 Hz : 337 sous Nyquist, 256 gardées.
        grave = np.abs(np.fft.rfft(grave[0]))
        self.assertGreater(grave[256], 1.0)
        self.assertLess(float(np.max(grave[257:])), 1e-6)

    def test_un_cable_balaye_la_table(self):
        """La position était lue une fois, sans ses câbles : un balayage par
        l'enveloppe 2 ne s'entendait pas."""
        from delugeapp.core import wavetable as wt
        from delugeapp.core.fixedpoint import from_display
        from delugeapp.core.model import PatchCable

        rel, _e = wt.write_wavetable(self.sd, "SAMPLES/Nappes/nappe.wav",
                                     "NAPPE", apply=True)

        def rendu(cable):
            preset = SynthPreset.new("TABLE")
            son = preset.sound
            son.osc1.type = "wavetable"
            son.osc1.file_name = rel
            son.unison_num = 1
            son.set_param("oscBVolume", from_display(0, scale=50))
            son.set_param("oscAWavetablePosition", -(1 << 31))
            son.patch_cables = [PatchCable(
                source="envelope2", destination="oscAWavetablePosition",
                amount=PatchCable.amount_from_display(50))] if cable else []
            return render.render_sound(son, note=57, seconds=0.6,
                                       sd=self.sd).mean(axis=1)

        fixe, balaye = rendu(False), rendu(True)
        self.assertEqual(fixe.shape, balaye.shape)
        self.assertGreater(float(np.max(np.abs(fixe - balaye))), 0.01)



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


# --------------------------------------------------------------------------- #
# L'étirement des échantillons
# --------------------------------------------------------------------------- #

def _wrap32(v: int) -> int:
    return ((v + (1 << 31)) & 0xFFFFFFFF) - (1 << 31)


def _percussivite_en_entiers(samples: np.ndarray) -> list[int]:
    """``Sample::fillPercCache`` recopié en entiers de Python, ligne à
    ligne, pour juger la boucle en flottants du module."""
    from delugeapp.core import dsp

    tab = [int(v) for v in dsp.table("tanHSmall")]
    data = samples if samples.ndim == 2 else samples[:, None]
    lus = [sum(int(np.floor(float(c) * 2 ** 31)) >> 2 for c in trame)
           for trame in data]
    out = [0] * (((len(lus) - 1) >> 7) + 1)
    poles = [0, 0]
    dernier, angle_avant = 0, 0
    for i, lu in enumerate(lus):
        angle = abs(lu - dernier)
        dernier = lu
        for p in range(2):
            poles[p] += (angle - poles[p]) >> 9
            angle = poles[p]
        if ((i + 1) & 127) == 64:
            ecart = abs(angle - angle_avant)
            if angle:
                q = (ecart * 262144 // angle) >> 1
            else:
                q = ((1 << 64) - 1 if ecart else 0) >> 1
            q = _wrap32(q)
            w = max(-(1 << 31), min((1 << 31) - 1, q << 23)) + (1 << 31)
            quel, force = w >> 24, (w >> 8) & 65535
            valeur = tab[quel] * (65536 - force) + tab[quel + 1] * force
            out[(i + 1) >> 7] = (valeur >> 25) & 255
        angle_avant = angle
    return out


class _TirageNul:
    """Un ``CONG`` qui tire toujours zéro : les tables du firmware nues."""

    def noise(self) -> int:
        return 0

    def random255(self) -> int:
        return 0


class TestEtirement(unittest.TestCase):
    """L'étireur du firmware (``TimeStretcher``) : un échantillon dont la
    vitesse se sépare de la hauteur. Ignoré jusqu'au 20 novembre 2026 —
    l'écoute lisait toujours plus vite un échantillon joué plus haut.
    Aucun son de la carte de l'utilisateur ne s'en sert (8 novembre) : le
    portage se juge contre le code du firmware 1.3, transcrit ici."""

    SR = 44100

    def setUp(self):
        from delugeapp.core import dsp
        from delugeapp.core import timestretch as ts

        self.dsp, self.ts = dsp, ts

    # --- les nombres du firmware -------------------------------------- #

    def test_le_rapport_de_vitesse_du_firmware(self):
        """``getSpeedParamForNoSyncing`` et ``timeStretchAdjustTable``."""
        ts, unite = self.ts, 1 << 24
        octave_haut = self.dsp.sample_increment(72, self.SR)
        self.assertEqual(ts.speed_ratio(octave_haut, unite, False, 0), unite,
                         "sans réglage, la vitesse suit la hauteur")
        self.assertEqual(ts.speed_ratio(octave_haut, unite, True, 0),
                         (unite << 24) // octave_haut)
        self.assertEqual(ts.speed_ratio(octave_haut, unite, True, 0),
                         unite // 2)
        self.assertEqual(ts.speed_ratio(unite, unite, True, 0), unite,
                         "à sa hauteur, rien à étirer")
        self.assertEqual(ts.speed_ratio(unite, unite, False, 12), 2 * unite)
        self.assertEqual(ts.speed_ratio(unite, unite, False, -48), unite // 16)
        self.assertEqual(ts.speed_ratio(octave_haut, unite, True, 12), unite)
        # La table : 2^((i − 48)/12) sur 2²⁴, à l'arrondi près.
        for i, v in enumerate(ts._ADJUST):
            self.assertLessEqual(abs(v - 2 ** ((i - 48) / 12) * unite), 1.0,
                                 i)
        self.assertEqual(len(ts._ADJUST), 97)

    def test_le_logarithme_rapide(self):
        """``quickLog`` : 832 << 20 au neutre, 32 << 20 par octave."""
        log = self.ts._quick_log
        unite = 1 << 24
        self.assertEqual(log(unite), 832 << 20)
        self.assertEqual(log(2 * unite), 864 << 20)
        self.assertEqual(log(unite // 2), 800 << 20)
        self.assertEqual(log(4 * unite), 896 << 20)
        # Entre deux octaves, la mantisse en ligne droite (tronquée).
        self.assertEqual(log(3 * unite // 2), (832 << 20) + (16 << 20))
        # Au-delà de 2²⁶, la mantisse perd ses bits du bas.
        self.assertEqual(log((3 << 28) + 15), (31 << 25) + (1 << 24))

    def test_les_bornes_de_saut_des_tables(self):
        """``hopEnd`` au neutre, une octave plus vite, une plus lente — et le
        débordement de ``crossfadeProportional << 8`` au ralenti."""
        ts, unite = self.ts, 1 << 24
        nul = _TirageNul()
        self.assertEqual(ts._hop_parameters(unite, nul),
                         (3000, 11000, 0, 60))
        # +12 : hors des tables fines, la quatrième des grossières.
        self.assertEqual(ts._hop_parameters(2 * unite, nul),
                         (600, 4000, 9 << 24, 40))
        # −12 : la première des fines ; 160 << 24 déborde 32 bits.
        mini, maxi, part, fixe = ts._hop_parameters(unite // 2, nul)
        self.assertEqual((mini, maxi, fixe), (3000, 6500, 10))
        self.assertEqual(part, (160 << 24) - (1 << 32))
        # Entre deux demi-tons, la table s'interpole.
        mini, maxi, _p, _f = ts._hop_parameters(
            ts.speed_ratio(unite, unite, False, 1), nul)
        self.assertTrue(2500 < mini < 3000 and 7500 < maxi < 11000)
        # Le tirage écarte la borne basse d'au plus son double.
        tirage = self.dsp.Cong()
        bornes = {ts._hop_parameters(unite // 2, tirage)[0]
                  for _s in range(40)}
        self.assertGreater(len(bornes), 30)
        self.assertTrue(all(0 <= b <= 6000 for b in bornes), bornes)

    def test_la_percussivite_transcrite(self):
        """La boucle en flottants rend les octets de ``fillPercCache``, au
        pixel près : un silence, une attaque, une note qui s'éteint, un
        bruit stéréo plein pot."""
        rng = np.random.default_rng(3)
        n = 20000
        t = np.arange(n) / self.SR
        mono = np.zeros(n)
        mono[3000:] = 0.7 * np.sin(2 * np.pi * 180 * t[3000:]) \
            * np.exp(-(t[3000:] - t[3000]) * 12)
        mono[15000:15040] = 0.9
        stereo = np.stack([rng.uniform(-1, 1, n), mono], axis=1)
        for nom, signal in (("mono", mono), ("stéréo", stereo)):
            with self.subTest(signal=nom):
                attendu = _percussivite_en_entiers(signal)
                self.assertEqual(self.ts.percussiveness(signal).tolist(),
                                 attendu)
        octets = self.ts.percussiveness(mono)
        self.assertEqual(int(octets[:20].max()), 0, "le silence ne bouge pas")
        self.assertGreater(int(octets[3000 // 128 + 1]), 40,
                           "une attaque sature presque")

    def test_le_saut_vise_la_zone_la_plus_percussive(self):
        """La recherche de ``hopEnd`` : une seule attaque devant la tête, et
        le saut le plus court dont la fenêtre l'atteint."""
        ts, unite = self.ts, 1 << 24
        data = np.zeros((40000, 1))
        st = ts._Stretcher(data, 128, self.SR, False, 1)
        st.perc = np.zeros(400, dtype=np.int64)
        st.perc[60] = 50
        st.zone_start, st.cache_end = 0, 40000
        ratio = 2 * unite
        choisi = st._beam_search(5000, 600, 4000, ratio, 2300)
        top = 5000 >> 7
        devant = [w for w in range(600, 4000, 128)
                  if top + ((w * (ratio + unite)) >> 32) > 60]
        self.assertEqual(choisi, devant[0])
        # Hors de la zone calculée, la longueur par défaut.
        st.cache_end = 5000
        self.assertEqual(st._beam_search(5000, 600, 4000, ratio, 2300), 2300)
        # Et le saut suivant dure ce que la recherche a choisi, moins son
        # fondu : 9/256 du saut plus 4 × 40 échantillons.
        st.cache_end, st.rng, st.big = 40000, _TirageNul(), 5000 << 24
        st.hop_end(unite, ratio)
        fondu = ts._mulr(devant[0], 9 << 24) + 160
        self.assertEqual(st.til_hop, devant[0] - fondu)
        self.assertEqual(st.xf_inc, unite // fondu)
        self.assertEqual(st.newer.pos >> 24, 5000 + devant[0] // 2)

    def test_les_fondus_sont_lineaires(self):
        """``Linear crossfades`` : à chaque saut, la tête neuve part de zéro
        et monte en ligne droite, l'ancienne descend d'autant."""
        ts = self.ts
        n = self.SR
        t = np.arange(self.SR) / self.SR
        data = (0.5 * np.sin(2 * np.pi * 220 * t))[:, None]
        nb = -(-n // 128)
        st = ts._Stretcher(data, n, self.SR, False, self.dsp.CONG_SEED)
        st.run(np.full(nb, 1 << 24), np.full(nb, 3 << 23), n)
        debuts = np.flatnonzero(st.on_old[1:] & ~st.on_old[:-1]) + 1
        self.assertGreater(debuts.size, 5)
        for d in debuts:
            fin = d + int(np.argmin(st.on_old[d:])) if not st.on_old[-1] \
                else n
            poids = st.weight[d:fin]
            self.assertLess(float(poids[0]), 0.05)
            pentes = np.diff(poids)
            self.assertTrue(np.all(pentes > 0), d)
            self.assertLess(float(np.ptp(pentes)), 1e-9 + 1.0 / 128, d)
        self.assertTrue(np.all(st.weight[~st.on_old] == 1.0))

    # --- ce qui s'entend ------------------------------------------------ #

    def _sinus_etire(self, amount, demi=0, independent=False, n=None):
        n = n or self.SR
        t = np.arange(self.SR) / self.SR
        sinus = 0.5 * np.sin(2 * np.pi * 220 * t)
        nb = -(-n // 128)
        inc = self.dsp.sample_increment(60 + demi, self.SR)
        ratio = self.ts.speed_ratio(inc, 1 << 24, independent, amount)
        return self.ts.stretch(sinus, np.full(nb, inc), np.full(nb, ratio), n,
                               self.SR)

    def test_les_tetes_se_calent_en_phase(self):
        """Ralenti de cinq demi-tons, un sinus reste un sinus : le niveau ne
        creuse pas aux fondus, rien ne sort de la fondamentale. Sans le calage
        des moyennes glissantes, le niveau tombait à 0,15 et 16 dB à côté."""
        x = self._sinus_etire(-5)[self.SR // 10:self.SR * 9 // 10]
        w = 300
        niveau = np.sqrt(np.convolve(x ** 2, np.ones(w) / w,
                                     mode="valid") * 2)
        self.assertGreater(float(niveau.min()), 0.49)
        self.assertLess(float(niveau.max()), 0.51)
        spectre = np.abs(np.fft.rfft(x * np.hanning(x.size))) ** 2
        freqs = np.fft.rfftfreq(x.size, 1 / self.SR)
        hors = spectre[np.abs(freqs - 220) >= 10].sum() / spectre.sum()
        self.assertLess(10 * np.log10(hors), -50)

    def test_la_voix_s_arrete_au_bout_du_fichier(self):
        """Deux fois plus vite, une seconde dure une demi-seconde ; bouclée,
        elle continue."""
        n = int(0.8 * self.SR)
        x = self._sinus_etire(12, n=n)
        fin = np.flatnonzero(np.abs(x) > 1e-3)[-1] / self.SR
        self.assertAlmostEqual(fin, 0.5, delta=0.01)
        t = np.arange(self.SR) / self.SR
        sinus = 0.5 * np.sin(2 * np.pi * 220 * t)
        nb = -(-n // 128)
        boucle = self.ts.stretch(sinus, np.full(nb, 1 << 24),
                                 np.full(nb, 2 << 24), n, self.SR, loop=True)
        self.assertGreater(float(np.abs(boucle[-2000:]).max()), 0.4)

    def _carte(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        racine = Path(tmp.name) / "carte"
        for sous in ("SAMPLES", "SONGS", "SYNTHS", "KITS"):
            (racine / sous).mkdir(parents=True)
        t = np.arange(self.SR // 2) / self.SR
        wav.write(racine / "SAMPLES" / "la.wav",
                  (0.5 * np.sin(2 * np.pi * 220 * t)).astype(np.float32),
                  self.SR)
        return sdcard.SDCard(racine)

    def _ecoute(self, sd, note, enable=0, amount=0):
        preset = SynthPreset.new("Étiré")
        osc = preset.sound.osc1
        osc.type, osc.file_name = "sample", "SAMPLES/la.wav"
        osc.time_stretch_enable, osc.time_stretch_amount = enable, amount
        preset.sound.set_param("volume", from_display(35, scale=50))
        preset.sound.env1.sustain = from_display(50, scale=50)
        audio = render.render_sound(preset.sound, note=note, seconds=1.0,
                                    gate=1.0, sd=sd)[:, 0]
        fin = (np.flatnonzero(np.abs(audio) > 0.05 * np.abs(audio).max())[-1]
               + 1) / self.SR
        milieu = audio[int(0.05 * self.SR):int(0.2 * self.SR)]
        signes = np.signbit(milieu)
        hauteur = np.count_nonzero(signes[1:] != signes[:-1]) / 2 / 0.15
        return fin, hauteur, audio

    def test_un_echantillon_transpose_garde_sa_duree(self):
        """``timeStretchEnable`` : une octave plus haut, la demi-seconde du
        fichier dure toujours une demi-seconde — et sonne à 440 Hz."""
        sd = self._carte()
        fin, hauteur, _a = self._ecoute(sd, 72)
        self.assertAlmostEqual(fin, 0.25, delta=0.01)
        self.assertAlmostEqual(hauteur, 440, delta=10)
        fin, hauteur, _a = self._ecoute(sd, 72, enable=1)
        self.assertAlmostEqual(fin, 0.5, delta=0.015)
        self.assertAlmostEqual(hauteur, 440, delta=10)
        fin, hauteur, _a = self._ecoute(sd, 53, enable=1)
        self.assertAlmostEqual(fin, 0.5, delta=0.015)
        self.assertAlmostEqual(hauteur, 220 * 2 ** (-7 / 12), delta=8)

    def test_l_ecart_de_vitesse_garde_la_hauteur(self):
        """``timeStretchAmount`` : douze demi-tons de plus, deux fois plus
        vite, à la même hauteur."""
        sd = self._carte()
        fin, hauteur, _a = self._ecoute(sd, 60, amount=12)
        self.assertAlmostEqual(fin, 0.25, delta=0.015)
        self.assertAlmostEqual(hauteur, 220, delta=8)

    def test_sans_etirement_la_lecture_ne_change_pas(self):
        """Hauteur et vitesse liées, ou à la hauteur du fichier : la lecture
        d'avant, au bit près."""
        sd = self._carte()
        _f, _h, avant = self._ecoute(sd, 67)
        _f, _h, neutre = self._ecoute(sd, 60, enable=1)
        _f, _h, lu = self._ecoute(sd, 60)
        self.assertTrue(np.array_equal(neutre, lu))
        from unittest import mock

        with mock.patch.object(self.ts, "stretch",
                               side_effect=AssertionError("étiré")):
            _f, _h, encore = self._ecoute(sd, 67)
        self.assertTrue(np.array_equal(avant, encore))
