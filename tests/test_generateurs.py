# -*- coding: utf-8 -*-
"""Tests des générateurs : genres, sons, kits, théorie, rythmes,
accompagnement, esquisses et écriture des morceaux.

Sans carte réelle ni Qt : chaque test fabrique sa carte jetable. Découpés
de ``test_core.py`` le 20 novembre 2026.

    python -m unittest tests.test_generateurs -v
"""

from __future__ import annotations

import os
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

from delugeapp.core import (accomp, db, dxml, genres, kitgen, midifile, render,
                            rhythm, scan, sdcard, sketch, slicer, synthgen,
                            theory, wav)
from delugeapp.core.fixedpoint import to_display
from delugeapp.core.model import (Kit, Note, Song, SynthPreset,
                                  tempo_from_song_attrs)

import sys as _sys                                           # noqa: E402

# Les aides partagées (``tests/aides_coeur.py``), par leur nom : ``unittest
# discover -s tests`` charge les modules à plat, pytest en paquet.
_DOSSIER = str(Path(__file__).resolve().parent)
if _DOSSIER not in _sys.path:
    _sys.path.insert(0, _DOSSIER)
from aides_coeur import lire_midi  # noqa: E402


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
            lu = lire_midi(chemin)
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

    def test_un_nom_pris_se_voit_casse_confondue(self):
        """Sous Linux, « Essai.XML » ne voyait pas « ESSAI.XML », et le
        morceau prenait un nom que la FAT du Deluge confond avec l'autre
        (tests sur GitHub, 9 novembre 2026). Windows confondant déjà les
        casses, un système qui les distingue est simulé ici."""
        from unittest import mock

        from delugeapp.core import songwriter

        (self.root / "SONGS" / "ESSAI.XML").write_bytes(b"<song />")
        vrai = Path.exists

        def sensible(chemin, *args, **kwargs):
            if not vrai(chemin, *args, **kwargs):
                return False
            parent = chemin.parent
            return parent == chemin or chemin.name in os.listdir(parent)

        with mock.patch.object(Path, "exists", sensible):
            self.assertFalse((self.root / "SONGS" / "Essai.XML").exists())
            self.assertTrue(self.sd.exists("SONGS/Essai.XML"))
            self.assertTrue(self.sd.exists("songs/essai.xml"))
            self.assertFalse(self.sd.exists("SONGS/Essai 2.XML"))
            self.assertEqual(songwriter.free_song_name(self.sd, "Essai"),
                             "SONGS/Essai 2.XML")

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
