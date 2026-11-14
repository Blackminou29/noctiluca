# -*- coding: utf-8 -*-
"""Tests de l'atelier du compositeur et de ce qui le porte.

* le format des notes du firmware 1.3 (``noteDataWithSplitProb``) et les
  pistes MIDI et CV, lues et écrites ;
* les variantes de son **dans le style** (:func:`synthgen.style_variations`) ;
* les variations de clips (:mod:`delugeapp.core.variation`) ;
* le projet de l'atelier (:mod:`delugeapp.core.atelier`) ;
* l'ajout à un morceau sans rien en réécrire (:mod:`delugeapp.core.songinsert`) ;
* le jeu calé sur l'horloge de la machine (:class:`delugelink.Transport`).

Sans carte réelle ni Qt : chaque test fabrique sa carte jetable.

    python -m unittest tests.test_atelier -v
"""

from __future__ import annotations

import tempfile
import threading
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

from delugeapp.core import (accomp, atelier, conditions, db, dxml,  # noqa: E402
                            genres, midiport, render, rhythm, scan,
                            sdcard, songinsert, songwriter, synthgen,
                            theory, variation, wav)
from delugeapp.core.delugelink import DelugeLink, Transport  # noqa: E402
from delugeapp.core.fixedpoint import to_display  # noqa: E402
from delugeapp.core.model import (NOTE_BLOBS, Note, NoteRow, Song,  # noqa: E402
                                  decode_notes, encode_notes, note_blob_tag)


def _carte(racine: Path, avec_sons: bool = True) -> sdcard.SDCard:
    """Une carte jetable ; avec des échantillons de batterie, de quoi bâtir
    un kit."""
    for sous in ("SONGS", "SYNTHS", "KITS", "SAMPLES"):
        (racine / sous).mkdir(parents=True, exist_ok=True)
    if avec_sons:
        t = np.linspace(0, 0.3, 13230, endpoint=False, dtype=np.float32)
        for i, role in enumerate(("Kick", "Snare", "HatC", "HatO", "Clap",
                                  "Rim", "Crash", "Shaker", "Ride",
                                  "Cowbell", "TomL", "TomM", "TomH")):
            dossier = racine / "SAMPLES" / "DRUMS" / role
            dossier.mkdir(parents=True, exist_ok=True)
            signal = (0.5 * np.sin(2 * np.pi * (60 + 40 * i) * t)
                      * np.exp(-t * 6)).astype(np.float32)
            wav.write(dossier / f"909 {role}.wav", signal, 44100)
    return sdcard.SDCard(racine)


class CarteCase(unittest.TestCase):
    """Une carte jetable indexée, pour les kits."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "carte"
        self.sd = _carte(self.root)
        self.lib = db.Library(Path(self._tmp.name) / "i.db")
        scan.scan_card(self.sd, self.lib, compute_hash=False)

    def tearDown(self):
        self.lib.close()
        self._tmp.cleanup()


# --------------------------------------------------------------------------- #
# Le format 1.3 et les pistes MIDI et CV
# --------------------------------------------------------------------------- #

class TestNotesDuFirmware13(unittest.TestCase):
    """Un morceau enregistré par la 1.3 range ses notes dans
    ``noteDataWithSplitProb`` : sans le lire, chaque morceau que
    l'utilisateur enregistrera désormais paraîtrait vide."""

    def test_la_disposition_est_celle_du_firmware(self):
        """``NoteRow::writeToFile`` : pos(8) longueur(8) vélocité(2) lift(2)
        probabilité(2) itération(4) fill(2) — 20 = toujours, 0000 = aucune
        itération."""
        blob = ("0x" + "00000060" + "00000030" + "64" + "40" + "14"
                + "0000" + "00"
                + "000000C0" + "00000018" + "50" + "28" + "0A" + "0203"
                + "01")
        notes = decode_notes(blob, width=28)
        self.assertEqual([(n.pos, n.length, n.velocity, n.lift, n.condition)
                          for n in notes],
                         [(96, 48, 100, 64, 20), (192, 24, 80, 40, 10)])
        self.assertEqual((notes[1].iterance, notes[1].fill), (0x0203, 1))

    def test_aller_retour_a_28_caracteres(self):
        notes = [Note(pos=0, length=96, velocity=100),
                 Note(pos=384, length=12, velocity=1, condition=5, lift=90)]
        blob = encode_notes(notes, width=28)
        self.assertEqual(len(blob), 2 + 28 * len(notes))
        back = decode_notes(blob, width=28)
        self.assertEqual([(n.pos, n.length, n.velocity, n.condition, n.lift)
                          for n in back],
                         [(0, 96, 100, 20, 64), (384, 12, 1, 5, 90)])

    def test_un_octet_c1_2_garde_son_sens_en_1_3(self):
        """L'octet de condition d'un morceau c1.2, en 28 caractères, comme
        le relit ``NoteRow::readFromFile`` du firmware 1.3 : 0 remplissage,
        128 sauf remplissage, 21 à 55 une itération de l'ancien menu, et le
        bit 7 d'une probabilité (« suit la précédente ») gardé.

        Corrigé le 13 novembre 2026 : ce test prenait un octet ≥ 0x80 pour
        une itération d'avant 1.3, et le faisait jouer toujours."""
        def champs(condition):
            blob = encode_notes([Note(pos=0, length=24,
                                      condition=condition)], width=28)[2:]
            return blob[20:22], blob[22:26], blob[26:28]

        self.assertEqual(champs(0x86), ("86", "0000", "00"))
        self.assertEqual(champs(0), ("14", "0000", "02"))
        self.assertEqual(champs(128), ("14", "0000", "01"))
        self.assertEqual(champs(21), ("14", "0201", "00"))   # 1 sur 2
        self.assertEqual(champs(26), ("14", "0401", "00"))   # 1 sur 4
        self.assertEqual(champs(10), ("0A", "0000", "00"))   # 50 %

    def test_chaque_balise_se_lit(self):
        notes = [Note(pos=24, length=12, velocity=90)]
        for tag, width in NOTE_BLOBS:
            el = dxml.loads(b'<noteRow y="60" />').root
            if width == 26:
                el.set(tag, "0x" + "00000018" + "0000000C" + "5A" + "40"
                       + "14" + "00" + "00")
            else:
                el.set(tag, encode_notes(notes, with_lift=width != 20,
                                         width=width if width != 26
                                         else None))
            row = NoteRow.from_xml(el)
            self.assertEqual([(n.pos, n.length, n.velocity)
                              for n in row.notes], [(24, 12, 90)], tag)

    def test_la_balise_suit_la_version_du_morceau(self):
        """``noteDataWithLift`` n'est lu que sous c1.3.0 ; les versions
        officielles passent avant les communautaires."""
        self.assertEqual(note_blob_tag("c1.3.0")[0], "noteDataWithSplitProb")
        self.assertEqual(note_blob_tag("c1.4.0-beta")[0],
                         "noteDataWithSplitProb")
        for version in ("c1.2.1", "c1.3.0-alpha", "4.1.4", "3.0.4", ""):
            self.assertEqual(note_blob_tag(version)[0], "noteDataWithLift",
                             version)


class TestPistesMidiEtCV(CarteCase):
    """Les pistes MIDI et CV, écrites comme la machine les écrit."""

    def _spec(self, tracks, rows=None):
        rows = rows or {60: [Note(pos=0, length=96, velocity=100)]}
        clips = [songwriter.ClipSpec(track=i, length=songwriter.BAR,
                                     rows=rows, name="Essai")
                 for i in range(len(tracks))]
        return songwriter.SongSpec(name="MIDI CV", tracks=tracks, clips=clips)

    def test_une_piste_midi_et_une_piste_cv(self):
        spec = self._spec([songwriter.midi_track(5), songwriter.cv_track(2)])
        res = songwriter.write_song(self.sd, spec, apply=True)
        self.assertTrue(res.applied, res.error)
        texte = self.sd.abs(res.rel).read_text(encoding="utf-8")
        # Le canal 5 de l'écran s'écrit 4 ; CV 2 s'écrit 1.
        self.assertIn('<midi\n\t\t\tchannel="4"\n\t\t\tsuffix="-1"', texte)
        self.assertIn('<cvChannel\n\t\t\tchannel="1"', texte)
        self.assertNotIn("presetName=\"MIDI", texte)
        song = Song.load(self.sd.abs(res.rel))
        kinds = sorted((c.kind, c.channel) for c in song.clips)
        self.assertEqual(kinds, [("cv", 1), ("midi", 4)])
        self.assertEqual(sorted((i["kind"], i.get("channel"))
                                for i in song.instruments),
                         [("cv", 1), ("midi", 4)])
        for clip in song.clips:
            self.assertEqual(clip.note_count, 1)

    def test_deux_pistes_midi_sur_le_meme_canal(self):
        """La seconde prend un suffixe, que son clip cite."""
        spec = self._spec([songwriter.midi_track(3), songwriter.midi_track(3)])
        res = songwriter.write_song(self.sd, spec, apply=True)
        song = Song.load(self.sd.abs(res.rel))
        self.assertEqual(sorted(i["suffix"] for i in song.instruments),
                         [-1, 0])
        self.assertEqual(sorted(c.suffix for c in song.clips), [-1, 0])

    def test_l_arpegiateur_porte_ses_reglages(self):
        """Sans ``soundParams``, l'arpégiateur d'un clip MIDI garde ses
        réglages propres (relevé sur « O Coast », c1.2.1)."""
        doc = songwriter.build(self._spec([songwriter.midi_track(1)]))
        clip = doc.root.find("sessionClips")[0]
        arp = clip.find("arpeggiator")
        self.assertEqual(arp.get("gate"), "0")
        self.assertEqual(arp.get("arpMode"), "off")
        self.assertIsNone(clip.find("soundParams"))


# --------------------------------------------------------------------------- #
# Les variantes de son dans le style
# --------------------------------------------------------------------------- #

class TestVariantesDansLeStyle(unittest.TestCase):
    """Le même son, un curseur poussé ; ou un seul aspect tiré à nouveau."""

    GENRES = ("acid", "techno", "house", "ambient", "dnb", "synthwave")

    def _sig(self, preset):
        s = preset.sound
        out = {"p." + k: to_display(v) for k, v in s.params.items()}
        for name in ("env1", "env2"):
            env = getattr(s, name)
            for field in ("attack", "decay", "sustain", "release"):
                out["%s.%s" % (name, field)] = to_display(getattr(env, field))
        out.update(osc1=s.osc1.type, osc2=s.osc2.type, mode=s.mode,
                   lpf=s.lpf_mode, poly=s.polyphonic, unison=s.unison_num,
                   cables=tuple(sorted((c.source, c.destination)
                                       for c in s.patch_cables)))
        return out

    def _diff(self, a, b):
        return {k for k in set(a) | set(b) if a.get(k) != b.get(k)}

    def test_plus_sale_reste_le_meme_son(self):
        """Mesuré avant les tirages nommés : 18 réglages changés en médiane
        et la structure du son dans 584 cas sur 660. Désormais, ni forme
        d'onde, ni moteur, ni câble ne bouge."""
        for genre in self.GENRES:
            for role in ("bass", "lead", "pad"):
                for seed in range(4):
                    base = synthgen.GenOptions(genre=genre, role=role,
                                               seed=seed)
                    poussee = synthgen.nudged(base, "Plus sale")
                    changed = self._diff(
                        self._sig(synthgen.generate(base)),
                        self._sig(synthgen.generate(poussee)))
                    self.assertFalse(changed & {"osc1", "osc2", "mode",
                                                "poly", "cables", "unison"},
                                     (genre, role, seed, changed))
                    self.assertLessEqual(len(changed), 5)

    def test_les_poussees_vont_dans_leur_sens(self):
        sens = {"Plus brillant": ("p.lpfFrequency", 1),
                "Plus sombre": ("p.lpfFrequency", -1),
                "Plus sale": ("p.lpfResonance", 1),
                "Plus d'espace": ("p.reverbAmount", 1),
                "Plus sec": ("p.reverbAmount", -1)}
        for genre in self.GENRES:
            for seed in range(3):
                base = synthgen.GenOptions(genre=genre, role="lead",
                                           seed=seed)
                ref = self._sig(synthgen.generate(base))
                for label, (key, direction) in sens.items():
                    var = self._sig(synthgen.generate(
                        synthgen.nudged(base, label)))
                    self.assertGreaterEqual((var[key] - ref[key])
                                            * direction, 0,
                                            (genre, label))

    def test_un_curseur_en_butee_ne_donne_rien(self):
        base = synthgen.GenOptions(genre="techno", brightness=1.0, seed=1)
        self.assertIsNone(synthgen.nudged(base, "Plus brillant"))
        self.assertIsNotNone(synthgen.nudged(base, "Plus sombre"))

    def test_un_autre_filtre_ne_touche_que_le_filtre(self):
        for genre in self.GENRES:
            base = synthgen.GenOptions(genre=genre, role="bass", seed=5)
            changed = self._diff(
                self._sig(synthgen.generate(base)),
                self._sig(synthgen.generate(
                    synthgen.rerolled(base, "filtre", 99))))
            self.assertTrue(changed <= {"p.lpfFrequency", "p.lpfResonance",
                                        "p.hpfFrequency", "lpf",
                                        "p.sampleRateReduction",
                                        "p.bitCrush"}, (genre, changed))

    def test_les_variantes_sont_reproductibles_et_jouables(self):
        base = synthgen.GenOptions(genre="house", role="pad", seed=4,
                                   name="VELOURS PAD")
        a = synthgen.style_variations(base, 8, seed=11)
        b = synthgen.style_variations(base, 8, seed=11)
        self.assertEqual(len(a), 8)
        self.assertEqual([v.label for v in a], [v.label for v in b])
        self.assertEqual([self._sig(v.preset) for v in a],
                         [self._sig(v.preset) for v in b])
        noms = [v.preset.name for v in a]
        self.assertEqual(len(set(noms)), 8, noms)
        for variant in a:
            self.assertGreaterEqual(variant.preset.sound.display("volume"),
                                    synthgen.MIN_VOLUME)
        # Aspects et directions en alternance.
        self.assertIn(a[0].changed, synthgen.VARIABLE_FACETS)
        self.assertIn(a[1].changed, synthgen.NUDGES)

    def test_une_variante_reste_dans_le_profil(self):
        """La coupure d'une variante reste dans l'intervalle du genre pour
        le rôle : c'est ce qui la garde dans le style, quand ``mutate``
        déplace tout sans le connaître."""
        for genre in self.GENRES:
            profil = genres.genre(genre).for_role("bass")
            low, high = profil.cutoff
            base = synthgen.GenOptions(genre=genre, role="bass", seed=2)
            for variant in synthgen.style_variations(base, 8, seed=3):
                coupure = variant.preset.sound.display("lpfFrequency")
                self.assertTrue(low - 1 <= coupure <= max(high, 18) + 1,
                                (genre, variant.label, coupure))


class TestGarderEtRetoucher(unittest.TestCase):
    """Une nouvelle graine qui garde des aspects ; une retouche qui garde
    les retouches faites à la main (générateur, 13 novembre 2026)."""

    GENRES = TestVariantesDansLeStyle.GENRES
    _sig = TestVariantesDansLeStyle._sig
    _diff = TestVariantesDansLeStyle._diff

    GROUPES = {
        "filtre": {"p.lpfFrequency", "p.lpfResonance", "p.hpfFrequency",
                   "lpf", "p.sampleRateReduction", "p.bitCrush"},
        "enveloppes": {"%s.%s" % (e, f) for e in ("env1", "env2")
                       for f in ("attack", "decay", "sustain", "release")},
        "timbre": {"osc1", "osc2"},
    }

    def test_un_aspect_garde_ne_bouge_pas_et_le_reste_change(self):
        """Mesuré sur 22 genres × 10 rôles × 3 graines : l'aspect gardé n'a
        jamais bougé, et le reste du son a changé à chaque fois."""
        for genre in self.GENRES:
            for role in ("bass", "lead", "pad", "pluck"):
                base = synthgen.GenOptions(genre=genre, role=role, seed=3)
                avant = self._sig(synthgen.generate(base))
                for garde, champs in self.GROUPES.items():
                    autre = synthgen.reseeded(base, 1003, keep=(garde,))
                    apres = self._sig(synthgen.generate(autre))
                    change = self._diff(avant, apres)
                    self.assertFalse(change & champs, (genre, role, garde))
                    self.assertTrue(change - champs, (genre, role, garde))

    def test_une_graine_propre_suit_l_aspect_garde(self):
        base = synthgen.rerolled(
            synthgen.GenOptions(genre="acid", seed=5), "filtre", 77)
        self.assertEqual(synthgen.facet_seed(base, "filtre"), 77)
        self.assertEqual(synthgen.facet_seed(base, "timbre"), 5)
        garde = synthgen.reseeded(base, 9, keep=("filtre", "timbre"))
        self.assertEqual(garde.seed, 9)
        self.assertEqual(garde.facets, {"filtre": 77, "timbre": 5})
        # Sans rien garder, chaque aspect suit la nouvelle graine.
        self.assertEqual(synthgen.reseeded(base, 9).facets, {})
        self.assertEqual(base.facets, {"filtre": 77})     # intact
        with self.assertRaises(ValueError):
            synthgen.reseeded(base, 9, keep=("couleur",))

    def test_au_hasard_rend_ses_reglages(self):
        """« Au hasard » garde ses réglages : on peut ensuite retoucher le
        son dans son style."""
        for seed in range(6):
            options = synthgen.random_options(seed=seed)
            self.assertEqual(self._sig(synthgen.generate(options)),
                             self._sig(synthgen.randomize(seed=seed)))

    def test_une_retouche_garde_les_retouches_a_la_main(self):
        from delugeapp.core import soundedit

        base = synthgen.GenOptions(genre="techno", role="bass", seed=4)
        genere = synthgen.generate(base).sound
        retouche = soundedit.copy_sound(genere)
        retouche.name = "MA BASSE"
        soundedit.set_value(retouche, "reverbAmount",
                            soundedit.value(genere, "reverbAmount") + 9)
        sombre = synthgen.nudged(base, "Plus sombre")
        obtenu = synthgen.restyled(base, sombre, retouche).sound
        attendu = synthgen.generate(sombre).sound
        self.assertEqual(obtenu.name, "MA BASSE")
        self.assertEqual(soundedit.value(obtenu, "reverbAmount"),
                         soundedit.value(attendu, "reverbAmount") + 9)
        self.assertEqual(soundedit.value(obtenu, "lpfFrequency"),
                         soundedit.value(attendu, "lpfFrequency"))
        self.assertLess(soundedit.value(obtenu, "lpfFrequency"),
                        soundedit.value(genere, "lpfFrequency") + 1)
        # Sans retouche, c'est le son des nouveaux réglages, tel quel.
        self.assertEqual(self._sig(synthgen.restyled(base, sombre)),
                         self._sig(synthgen.generate(sombre)))


# --------------------------------------------------------------------------- #
# Les conditions des notes (13 novembre 2026)
# --------------------------------------------------------------------------- #

class TestLesConditionsDesNotes(unittest.TestCase):
    """Probabilité, itération, remplissage : les règles du firmware 1.3
    (``instrument_clip.cpp``, ``iterance.h``, ``iterance_migration.cpp``)."""

    def test_l_octet_c1_2_comme_le_relit_le_firmware(self):
        sur = conditions.iterance
        self.assertEqual(conditions.from_legacy(21), (100, sur(2, 1), 0))
        self.assertEqual(conditions.from_legacy(24), (100, sur(3, 2), 0))
        self.assertEqual(conditions.from_legacy(26), (100, sur(4, 1), 0))
        self.assertEqual(conditions.from_legacy(55), (100, sur(8, 8), 0))
        self.assertEqual(conditions.from_legacy(0), (100, 0, conditions.FILL))
        self.assertEqual(conditions.from_legacy(128),
                         (100, 0, conditions.NOT_FILL))
        self.assertEqual(conditions.from_legacy(10), (50, 0, 0))
        self.assertEqual(conditions.from_legacy(0x86), (30, 0, 0))
        self.assertEqual(conditions.from_legacy(20), (100, 0, 0))
        # Chaque itération de l'ancien menu fait l'aller-retour.
        for byte in range(21, 56):
            self.assertEqual(conditions.legacy_byte(
                *conditions.from_legacy(byte)), byte)
        # Une probabilité ne devient jamais 0, le remplissage d'un c1.2.
        self.assertEqual(conditions.probability_byte(1), 1)
        self.assertEqual(conditions.legacy_byte(2), 1)
        # Une itération que l'ancien menu ignore : la note joue toujours.
        self.assertEqual(conditions.legacy_byte(
            100, (4 << 8) | 0b101), 20)

    def test_l_iteration_compte_les_repetitions(self):
        un, deux = (accomp.NoteEvent(0, 1, 60, 90, iterance=conditions
                                     .iterance(2, s)) for s in (1, 2))
        joue = [[e is un for e in conditions.playing([un, deux], r)]
                for r in range(4)]
        self.assertEqual(joue, [[True], [False], [True], [False]])
        premiere = accomp.NoteEvent(0, 1, 60, 90, iterance=(0 << 8) | 1)
        derniere = accomp.NoteEvent(0, 1, 62, 90, iterance=(0 << 8) | 2)
        self.assertEqual(conditions.playing([premiere, derniere], 0),
                         [premiere])
        self.assertEqual(conditions.playing([premiere, derniere], 3,
                                            ending=True), [derniere])

    def test_le_remplissage_attend_le_bouton(self):
        fill = accomp.NoteEvent(0, 1, 60, 90, fill=conditions.FILL)
        sauf = accomp.NoteEvent(0, 1, 62, 90, fill=conditions.NOT_FILL)
        self.assertEqual(conditions.playing([fill, sauf], 0), [sauf])
        self.assertEqual(conditions.playing([fill, sauf], 0,
                                            fill_held=True), [fill])

    def test_le_hasard_suit_les_regles_du_firmware(self):
        import random

        rng = random.Random(4)
        a = accomp.NoteEvent(0, 1, 60, 90, probability=25)
        b = accomp.NoteEvent(0, 1, 64, 90, probability=25)
        c = accomp.NoteEvent(0, 1, 67, 90, probability=30)
        d = accomp.NoteEvent(0, 1, 72, 90, probability=70)
        e = accomp.NoteEvent(0, 1, 60, 90, probability=50)
        f = accomp.NoteEvent(0, 1, 64, 90, probability=50)
        ensemble, seule, total = 0, 0, 2000
        for _ in range(total):
            # Même probabilité, même instant : un seul tirage.
            joue = conditions.playing([a, b], 0, rng)
            self.assertIn(len(joue), (0, 2))
            ensemble += bool(joue)
            # 30 % + 70 % : exactement une note — et 50 % + 50 % aussi
            # (« somme à 100 % », qui passe avant le tirage partagé).
            joue = conditions.playing([c, d], 0, rng)
            self.assertEqual(len(joue), 1)
            seule += joue[0] is c
            self.assertEqual(len(conditions.playing([e, f], 0, rng)), 1)
        self.assertAlmostEqual(ensemble / total, 0.25, delta=0.04)
        self.assertAlmostEqual(seule / total, 0.3, delta=0.04)
        # Sans hasard (un export MIDI), toute note incertaine joue.
        self.assertEqual(len(conditions.playing([a, b, c], 0)), 3)

    def test_une_relance_de_deux_notes_joue_entiere(self):
        """Deux notes ajoutées au même instant, à 50 % chacune, feraient
        100 % : la machine n'en jouerait qu'une. « vivante » les met à
        45 %, et elles partagent un seul tirage."""
        import random

        accords = [accomp.NoteEvent(bar * 16.0, 15.5, note, 80)
                   for bar in range(4) for note in (57, 64)]
        out = variation.vary_part(accords, "vivante", part="Accords", bars=4,
                                  seed=1)
        ajoutees = [e for e in out if e.probability < 100
                    and (e.start, e.note) not in {(a.start, a.note)
                                                  for a in accords}]
        self.assertTrue(ajoutees)
        self.assertEqual({e.probability for e in ajoutees}, {45})
        rng = random.Random(3)
        moment = ajoutees[0].start
        groupe = [e for e in out if e.start == moment]
        for _ in range(200):
            self.assertIn(len(conditions.playing(groupe, 0, rng)),
                          (0, len(groupe)))

    def test_ce_qu_il_faut_ecouter_d_un_clip(self):
        coups = [rhythm.Step(pos=0), rhythm.Step(
            pos=4, iterance=conditions.iterance(4, 4))]
        self.assertEqual(conditions.cycle(coups), 4)
        self.assertEqual(conditions.cycle([rhythm.Step(pos=0,
                                                       probability=50)]), 2)
        self.assertEqual(conditions.cycle([rhythm.Step(pos=0)]), 1)
        self.assertEqual(conditions.cycle(coups, limit=2), 2)


class TestLesConditionsDansLAtelier(CarteCase):
    """Poser une condition, l'entendre, l'écrire, la relire."""

    def _projet(self):
        projet = atelier.new_project(atelier.Style(genre="techno", seed=3),
                                     sd=self.sd, lib=self.lib)
        batterie = next(t for t in projet.tracks if t.is_drums)
        clip = batterie.clips[0]
        return projet, batterie, clip

    def test_poser_et_relire_une_condition(self):
        projet, batterie, clip = self._projet()
        kick = rhythm.cell(clip.pattern.tracks["Kick"][0])
        moitie = conditions.Condition(probability=50)
        self.assertEqual(atelier.condition_at(projet, batterie.uid, clip.key,
                                              "Kick", kick),
                         conditions.Condition())
        avant = atelier.clip_conditions(clip)
        self.assertTrue(atelier.set_hit_condition(
            projet, batterie.uid, clip.key, "Kick", kick, moitie))
        self.assertEqual(atelier.condition_at(projet, batterie.uid, clip.key,
                                              "Kick", kick), moitie)
        self.assertEqual(atelier.clip_conditions(clip), avant + 1)
        vide = next(p for p in range(16) if all(
            rhythm.cell(s) != p for s in clip.pattern.tracks["Kick"]))
        self.assertFalse(atelier.set_hit_condition(
            projet, batterie.uid, clip.key, "Kick", vide, moitie))
        self.assertIsNone(atelier.condition_at(projet, batterie.uid,
                                               clip.key, "Kick", vide))

    def test_une_condition_s_ecrit_et_se_relit(self):
        """Dans un morceau c1.2.1, l'octet que la machine relit ; puis
        ``from_song`` rend la condition à l'atelier."""
        projet, batterie, clip = self._projet()
        coups = sorted(clip.pattern.tracks["Kick"], key=lambda s: s.pos)
        poses = [conditions.Condition(probability=50),
                 conditions.Condition(iterance=conditions.iterance(2, 1)),
                 conditions.Condition(fill=conditions.FILL),
                 conditions.Condition(fill=conditions.NOT_FILL)]
        for coup, cond in zip(coups, poses):
            atelier.set_hit_condition(projet, batterie.uid, clip.key, "Kick",
                                      rhythm.cell(coup), cond)
        spec = atelier.to_song_spec(projet, "CONDITIONS", sd=self.sd,
                                    lib=self.lib)
        res = songwriter.write_song(self.sd, spec, apply=True)
        self.assertTrue(res.applied, res.error)
        song = Song.load(self.sd.abs(res.rel))
        octets = sorted({n.condition for c in song.clips
                         for r in c.note_rows for n in r.notes})
        for attendu in (10, 21, 0, 128):
            self.assertIn(attendu, octets)
        relu = atelier.from_song(song, self.sd)
        lues = {conditions.of(s) for t in relu.tracks if t.is_drums
                for c in t.clips if c.pattern is not None
                for hits in c.pattern.tracks.values() for s in hits}
        self.assertTrue(set(poses) <= lues, lues)

    def test_les_conditions_d_un_synthe_se_relisent(self):
        projet, _batterie, _clip = self._projet()
        basse = next(t for t in projet.tracks if t.part == "Basse")
        clip = basse.clips[0]
        premiere = sorted(clip.events, key=lambda e: e.start)[0]
        un_sur_quatre = conditions.Condition(
            iterance=conditions.iterance(4, 1))
        self.assertTrue(atelier.set_note_condition(
            projet, basse.uid, clip.key, premiere.note,
            int(premiere.start), un_sur_quatre))
        spec = atelier.to_song_spec(projet, "SYNTHE", sd=self.sd,
                                    lib=self.lib)
        res = songwriter.write_song(self.sd, spec, apply=True)
        relu = atelier.from_song(Song.load(self.sd.abs(res.rel)), self.sd)
        lues = {conditions.of(e) for t in relu.tracks if not t.is_drums
                for c in t.clips for e in c.events}
        self.assertIn(un_sur_quatre, lues)

    def test_une_iteration_empeche_le_repli_du_clip(self):
        """« 1 sur 2 » compte les tours du clip : replié de quatre mesures à
        une, il compterait quatre fois plus vite."""
        rows = {60: [Note(pos=p * songwriter.BAR, length=24)
                     for p in range(4)]}
        _rows, longueur = songwriter.fold(rows, 4 * songwriter.BAR)
        self.assertEqual(longueur, songwriter.BAR)
        rows = {60: [Note(pos=p * songwriter.BAR, length=24,
                          iterance=conditions.iterance(2, 1))
                     for p in range(4)]}
        _rows, longueur = songwriter.fold(rows, 4 * songwriter.BAR)
        self.assertEqual(longueur, 4 * songwriter.BAR)

    def test_l_ecoute_deroule_les_tours(self):
        projet, batterie, clip = self._projet()
        clip.bars = 1
        clip.pattern = rhythm.Pattern(name="", steps=16)
        clip.pattern.add("Kick", rhythm.Step(pos=0))
        clip.pattern.add("Kick", rhythm.Step(
            pos=8, iterance=conditions.iterance(2, 1)))
        clip.pattern.add("HatC", rhythm.Step(pos=4, fill=conditions.FILL))
        _parts, batterie_jouee, mesures = atelier.clip_parts(
            projet, batterie.uid, clip.key)
        self.assertEqual(mesures, 2)
        self.assertEqual(sorted(rhythm.cell(s)
                                for s in batterie_jouee.tracks["Kick"]),
                         [0, 8, 16])
        self.assertFalse(batterie_jouee.tracks.get("HatC"))

    def test_les_variations_qui_vivent(self):
        for genre in ("techno", "house", "dnb", "lofi"):
            beat = rhythm.genre_beat(genre, bars=2, seed=1)
            vive = variation.vary_drums(beat, "vivante", genre=genre, seed=2)
            avant = {(t, rhythm.cell(s)) for t, hits in beat.tracks.items()
                     for s in hits}
            apres = {(t, rhythm.cell(s)) for t, hits in vive.tracks.items()
                     for s in hits}
            self.assertTrue(avant <= apres, genre)
            self.assertTrue(set(vive.tracks) <= set(beat.tracks), genre)
            self.assertTrue(any(conditions.has_condition(s)
                                for hits in vive.tracks.values()
                                for s in hits), genre)
            fill = variation.vary_drums(beat, "roulement FILL", genre=genre)
            roulement = [(t, rhythm.cell(s)) for t, hits in fill.tracks.items()
                         for s in hits if s.fill == conditions.FILL]
            self.assertTrue(roulement, genre)
            self.assertTrue(all(c >= 24 for _t, c in roulement), genre)
            # Jamais deux coups au même instant d'une rangée.
            for hits in fill.tracks.values():
                cases = [rhythm.cell(s) for s in hits]
                self.assertEqual(len(cases), len(set(cases)), genre)
            # Sous le roulement, le motif se tait — la grosse caisse non.
            for track, hits in fill.tracks.items():
                for s in hits:
                    if rhythm.cell(s) >= 24 and track == "Kick":
                        self.assertNotEqual(s.fill, conditions.NOT_FILL)

    def test_le_bouton_fill_de_la_machine(self):
        """SYNC-SCALING ne joue le remplissage qu'avec *Sync Scaling Action*
        sur *Fill mode* (``view.cpp``) ; mesuré sur la carte de
        l'utilisateur : il ne l'est pas."""
        self.assertIsNone(conditions.fill_button_ready(None))
        self.assertIsNone(conditions.fill_button_ready(self.sd))
        reglages = self.root / "SETTINGS"
        reglages.mkdir(exist_ok=True)
        fichier = reglages / "CommunityFeatures.XML"
        for valeur, attendu in (("0", False), ("1", True)):
            fichier.write_text(
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<runtimeFeatureSettings firmwareVersion="c1.3.0">\n'
                '\t<setting name="quantize" value="1"></setting>\n'
                '\t<setting name="syncScalingAction" value="%s"></setting>\n'
                '</runtimeFeatureSettings>\n' % valeur, encoding="utf-8")
            self.assertIs(conditions.fill_button_ready(self.sd), attendu)

    def test_un_clip_du_deluge_ne_prend_pas_de_condition(self):
        projet, batterie, clip = self._projet()
        clip.existing = 0
        with self.assertRaises(ValueError):
            atelier.set_hit_condition(projet, batterie.uid, clip.key, "Kick",
                                      0, conditions.Condition(probability=50))


# --------------------------------------------------------------------------- #
# L'automation d'un clip (14 novembre 2026)
# --------------------------------------------------------------------------- #

class TestLAutomation(CarteCase):
    """Une courbe posée, entendue, écrite au format du firmware, relue."""

    def _projet(self):
        projet = atelier.new_project(atelier.Style(genre="house", seed=2),
                                     sd=self.sd, lib=self.lib)
        accords = next(t for t in projet.tracks if t.part == "Accords")
        return projet, accords, accords.clips[0]

    def test_les_formes_et_le_format_du_firmware(self):
        from delugeapp.core import automation

        montee = automation.shape_nodes("montée", 64, 10, 40)
        self.assertEqual(montee[0], (0, 10))
        self.assertEqual(montee[-1][1], 40)
        self.assertTrue(all(a[1] < b[1] for a, b in zip(montee, montee[1:])))
        vague = [v for _s, v in automation.shape_nodes("vague", 64, 0, 50)]
        self.assertGreaterEqual(max(vague), 49)      # au milieu du clip
        self.assertEqual((vague[0], vague[-1]), (0, 0))
        with self.assertRaises(ValueError):
            automation.shape_nodes("spirale", 16, 0, 50)
        # Le format : valeur courante, puis valeur + position par nœud.
        texte = automation.encode("lpfFrequency", [(0, 50), (4, 0)], 24, 384)
        self.assertEqual(texte, "0x7FFFFFFF" "7FFFFFFF00000000"
                                "8000000000000060")
        courant, noeuds = automation.decode(texte)
        self.assertEqual(courant, 0x7FFFFFFF)
        self.assertEqual(noeuds, [(0, 0x7FFFFFFF, False),
                                  (96, -0x80000000, False)])
        # Un nœud de la carte, relu tel que la machine l'écrit.
        carte = automation.decode("0x7FFFFFFFE0000000000000F07FFFFFFF00000120")
        self.assertEqual(automation.sampled(carte, 24, 768, "lpfFrequency"),
                         [(0, 50), (10, 19), (12, 50)])
        # Un nœud interpolé fait glisser la valeur.
        glisse = automation.decode("0x80000000" "8000000000000000"
                                   "7FFFFFFF" + "%08X" % (0x80000000 | 384))
        valeurs = [v for _s, v in automation.sampled(glisse, 24, 384,
                                                      "lpfFrequency")]
        self.assertGreater(len(valeurs), 10)
        self.assertEqual(valeurs, sorted(valeurs))
        self.assertEqual(automation.value_at([(0, 5), (8, 9)], 3), 5)
        self.assertEqual(automation.value_at([(4, 5), (8, 9)], 1), 9)
        self.assertEqual(automation.tile([(0, 1), (2, 3)], 4, 10, 100),
                         [(100.0, 1), (102.0, 3), (104.0, 1), (106.0, 3),
                          (108.0, 1)])

    def test_poser_une_courbe_l_ecrire_et_la_relire(self):
        projet, accords, clip = self._projet()
        noeuds = atelier.set_automation(projet, accords.uid, clip.key,
                                        "lpfFrequency", "montée", 8, 36)
        self.assertEqual(clip.automation["lpfFrequency"], noeuds)
        batterie = next(t for t in projet.tracks if t.is_drums)
        with self.assertRaises(ValueError):
            atelier.set_automation(projet, batterie.uid,
                                   batterie.clips[0].key, "volume",
                                   "montée", 0, 50)
        spec = atelier.to_song_spec(projet, "COURBE", sd=self.sd,
                                    lib=self.lib)
        ecrit = [c for c in spec.clips if c.automation]
        self.assertTrue(ecrit)
        # Une courbe empêche le repli : le clip garde ses quatre mesures.
        self.assertTrue(all(c.length == clip.bars * songwriter.BAR
                            for c in ecrit))
        res = songwriter.write_song(self.sd, spec, apply=True)
        self.assertTrue(res.applied, res.error)
        song = Song.load(self.sd.abs(res.rel))
        lues = [c.automation["lpfFrequency"] for c in song.clips
                if "lpfFrequency" in c.automation]
        self.assertTrue(lues)
        relu = atelier.from_song(song, self.sd)
        courbes = [c.automation.get("lpfFrequency") for t in relu.tracks
                   for c in t.clips if c.automation]
        self.assertIn(noeuds, courbes)

    def test_une_courbe_s_entend(self):
        projet, accords, clip = self._projet()
        parts, _d, mesures = atelier.clip_parts(projet, accords.uid, clip.key)
        self.assertEqual(parts.automation, {})
        atelier.set_automation(projet, accords.uid, clip.key, "volume",
                               "montée", 0, 50)
        parts, _d, mesures = atelier.clip_parts(projet, accords.uid, clip.key)
        courbe = parts.automation["Accords#%d" % accords.uid]["volume"]
        self.assertEqual(courbe[0], (0.0, -0x80000000))
        sons = atelier.listen_sounds(projet)
        audio = render.render_parts(dict(parts), sons, bpm=120,
                                    normalize=False,
                                    automation=parts.automation)
        moitie = audio.shape[0] // 2
        debut = float(np.sqrt((audio[:moitie // 2] ** 2).mean()))
        fin = float(np.sqrt((audio[moitie:moitie * 2] ** 2).mean()))
        self.assertGreater(fin, 4 * max(debut, 1e-9))
        # Sans courbe, le rendu est celui d'avant, à l'échantillon près.
        nu = render.render_parts(dict(parts), sons, bpm=120, normalize=False)
        vide = render.render_parts(dict(parts), sons, bpm=120,
                                   normalize=False, automation={})
        self.assertTrue(np.array_equal(nu, vide))

    def test_la_montee_d_une_section(self):
        projet, accords, clip = self._projet()
        index = max(range(len(projet.sections)),
                    key=lambda i: projet.sections[i].bars)
        section = projet.sections[index]
        avant = dict(section.cells)
        autres = {i: dict(s.cells) for i, s in enumerate(projet.sections)
                  if i != index}
        faits = atelier.section_rise(projet, index)
        self.assertTrue(faits)
        for uid, cle in faits:
            piste = projet.track(uid)
            neuf = piste.clip(cle)
            self.assertEqual(section.cells[uid], cle)
            self.assertNotEqual(avant[uid], cle)
            self.assertEqual(neuf.bars, min(16, section.bars))
            courbe = neuf.automation["lpfFrequency"]
            haut = atelier.current_value(piste, "lpfFrequency")
            self.assertEqual(courbe[-1][1], haut)
            self.assertEqual(courbe[0][1], max(0, haut - 20))
        self.assertEqual({i: dict(s.cells) for i, s in
                          enumerate(projet.sections) if i != index}, autres)
        # Dans le morceau entier, la courbe ne déborde pas de sa section.
        parts, _d, _m = atelier.song_parts(projet)
        uid = faits[0][0]
        courbe = parts.automation["%s#%d" % (projet.track(uid).part, uid)][
            "lpfFrequency"]
        debut = sum(s.bars for s in projet.sections[:index]) * 16
        fin = debut + section.bars * 16
        apres = [v for s, v in courbe if s >= fin]
        if apres:
            self.assertEqual(apres[0], atelier._static_raw(projet.track(uid),
                                                           "lpfFrequency"))

    def test_le_cache_ne_refait_que_ce_qui_change(self):
        """Mesuré sur son brouillon : un geste dans une boucle de huit
        mesures s'entendait après 1,90 s ; avec le cache, 0,27 s — et le son
        est celui d'un rendu complet, à l'échantillon près."""
        from unittest import mock

        from delugeapp.ui.pages.atelier import _render_mix

        projet, accords, clip = self._projet()
        index = atelier.fullest_section(projet)
        parts, batterie, mesures = atelier.section_parts(projet, index)
        sons = atelier.listen_sounds(projet)
        kit = next(t.kit for t in projet.tracks if t.is_drums)
        cache = {}
        premier = _render_mix(dict(parts), sons, batterie, 120, kit, self.sd,
                              0, parts.automation, cache)
        self.assertIn("#batterie", cache)
        gardes = {k: v for k, v in cache.items()}
        # Une note de plus dans une seule partie.
        cle = "Accords#%d" % accords.uid
        modifiees = dict(parts)
        e = modifiees[cle][0]
        modifiees[cle] = modifiees[cle] + [accomp.NoteEvent(
            e.start + 1, 1, e.note + 2, 70)]
        with mock.patch.object(render, "render_pattern",
                               side_effect=AssertionError("refaite")):
            rapide = _render_mix(modifiees, sons, batterie, 120, kit,
                                 self.sd, 0, parts.automation, cache)
        plein = _render_mix(modifiees, sons, batterie, 120, kit, self.sd, 0,
                            parts.automation)
        self.assertTrue(np.array_equal(rapide, plein))
        self.assertFalse(np.array_equal(premier, plein))
        for nom, valeur in gardes.items():
            if nom not in (cle, "#batterie"):
                self.assertIs(cache[nom], valeur, nom)       # repris tel quel
        self.assertIsNot(cache[cle], gardes[cle])

    def test_doubler_double_la_courbe(self):
        projet, accords, clip = self._projet()
        copie = atelier.duplicate_clip(projet, accords.uid, clip.key)
        atelier.set_automation(projet, accords.uid, copie.key, "pan",
                               "balancement", -20, 20)
        noeuds = list(copie.automation["pan"])
        atelier.double_clip(projet, accords.uid, copie.key)
        self.assertEqual(copie.automation["pan"],
                         noeuds + [(s + clip.steps, v) for s, v in noeuds])


# --------------------------------------------------------------------------- #
# Un clip depuis un fichier MIDI (13 novembre 2026)
# --------------------------------------------------------------------------- #

def _fichier_midi(chemin: Path, ppq: int = 96) -> Path:
    """Un fichier MIDI de type 1 : une basse de deux mesures et demie, une
    batterie General MIDI sur le canal 10 (dont une note sans rôle, 31)."""
    from delugeapp.core import midifile

    noire = ppq
    basse = midifile.MidiTrack(name="Bass", channel=0)
    for rang, note in enumerate((45, 45, 48, 52, 50, 45, 57, 55, 53, 52)):
        basse.add(rang * noire, note, 100, noire // 2)
    batterie = midifile.MidiTrack(name="Drums", channel=9)
    for temps in range(8):
        batterie.add(temps * noire, 36, 120, noire // 4)       # grosse caisse
        batterie.add(temps * noire + noire // 2, 42, 64, noire // 4)
    batterie.add(noire, 38, 110, noire // 4)
    batterie.add(3 * noire, 31, 90, noire // 4)                 # sans rôle
    midifile.write_midi(chemin, [basse, batterie], bpm=97, ppq=ppq)
    return chemin


class TestUnClipDepuisUnFichierMidi(CarteCase):

    def _projet(self):
        return atelier.new_project(atelier.Style(genre="techno", seed=3),
                                   sd=self.sd, lib=self.lib)

    def test_une_ligne_de_basse_devient_un_clip(self):
        from delugeapp.core import midifile

        data = midifile.read_midi(_fichier_midi(Path(self._tmp.name)
                                                / "idee.mid"))
        projet = self._projet()
        basse = next(t for t in projet.tracks if t.part == "Basse")
        choix = atelier.midi_choices(data, drums=False)
        self.assertEqual([c[1] for c in choix], ["Bass", "Drums"])
        avant = len(basse.clips)
        clip, laissees = atelier.import_midi_clip(projet, basse.uid, data,
                                                  choix[0][0])
        self.assertEqual(len(basse.clips), avant + 1)
        self.assertEqual((clip.bars, clip.note_count, laissees), (3, 10, 0))
        self.assertEqual(clip.origin, "MIDI importé")
        self.assertEqual([(e.start, e.note) for e in clip.events[:3]],
                         [(0.0, 45), (4.0, 45), (8.0, 48)])
        self.assertEqual(clip.events[0].length, 2.0)
        self.assertEqual(clip.events[0].velocity, 100 * 100 // 127)

    def test_une_batterie_general_midi_trouve_ses_rangees(self):
        from delugeapp.core import midifile

        data = midifile.read_midi(_fichier_midi(Path(self._tmp.name)
                                                / "idee.mid", ppq=480))
        projet = self._projet()
        batterie = next(t for t in projet.tracks if t.is_drums)
        choix = atelier.midi_choices(data, drums=True)
        self.assertEqual(choix[0][1], "Drums")
        clip, laissees = atelier.import_midi_clip(projet, batterie.uid, data,
                                                  choix[0][0])
        self.assertEqual(laissees, 1)                     # la note 31
        self.assertEqual(clip.bars, 2)
        self.assertEqual(sorted(clip.pattern.tracks),
                         ["HatC", "Kick", "Snare"])
        self.assertEqual(sorted(rhythm.cell(s)
                                for s in clip.pattern.tracks["Kick"]),
                         list(range(0, 32, 4)))
        self.assertEqual([rhythm.cell(s)
                          for s in clip.pattern.tracks["Snare"]], [4])
        # Le clip s'écrit comme un autre.
        for section in projet.sections:
            section.cells[batterie.uid] = clip.key
        spec = atelier.to_song_spec(projet, "IMPORT", sd=self.sd,
                                    lib=self.lib)
        self.assertTrue(songwriter.write_song(self.sd, spec,
                                              apply=True).applied)

    def test_rien_a_reprendre(self):
        from delugeapp.core import midifile

        vide = midifile.MidiFileData(tracks=[("Rien", [])])
        projet = self._projet()
        self.assertEqual(atelier.midi_choices(vide), [])
        basse = next(t for t in projet.tracks if t.part == "Basse")
        with self.assertRaises(ValueError):
            atelier.import_midi_clip(projet, basse.uid, vide, 0)
        sans_role = midifile.MidiFileData(
            ppq=96, tracks=[("Perc", [(0, 31, 100, 24, 9)])])
        batterie = next(t for t in projet.tracks if t.is_drums)
        with self.assertRaises(ValueError):
            atelier.import_midi_clip(projet, batterie.uid, sans_role, 0)
        self.assertEqual(midifile.drum_role(36), "Kick")
        self.assertEqual(midifile.drum_role(35), "Kick")
        self.assertEqual(midifile.drum_role(41), "TomL")
        self.assertEqual(midifile.drum_role(47), "TomM")
        self.assertEqual(midifile.drum_role(31), "")
        # 58 (« vibraslap ») n'a que le rôle fourre-tout « Other » : aucun.
        self.assertEqual(midifile.drum_role(58), "")


# --------------------------------------------------------------------------- #
# Le morceau entier en audio (13 novembre 2026)
# --------------------------------------------------------------------------- #

class TestLeMorceauEnAudio(CarteCase):

    def _projet(self):
        projet = atelier.new_project(atelier.Style(genre="house", seed=2),
                                     sd=self.sd, lib=self.lib)
        # Deux sections courtes : le rendu reste rapide.
        projet.sections = projet.sections[:2]
        for section in projet.sections:
            section.bars = 2
        return projet

    def test_le_morceau_section_apres_section(self):
        projet = self._projet()
        parts, batterie, mesures = atelier.song_parts(projet)
        self.assertEqual(mesures, 4)
        self.assertEqual(batterie.steps, 64)
        # Chaque section commence à sa place.
        debut = {round(float(s.pos)) for h in batterie.tracks.values()
                 for s in h}
        self.assertTrue(any(p >= 32 for p in debut))
        self.assertTrue(all(0 <= e.start < 64 for v in parts.values()
                            for e in v))
        seule = next(t for t in projet.tracks if t.part == "Basse")
        parts, batterie, _m = atelier.song_parts(projet, only={seule.uid})
        self.assertIsNone(batterie)
        self.assertEqual(list(parts), ["Basse#%d" % seule.uid])

    def test_le_melange_et_ses_pistes(self):
        projet = self._projet()
        sortie = Path(self._tmp.name) / "export" / "MORCEAU.wav"
        etapes = []
        fichiers = atelier.export_audio(projet, sortie, sd=self.sd,
                                        stems=True, progress=etapes.append)
        self.assertEqual(fichiers[0], sortie)
        jouees = [t for t in projet.tracks
                  if any(s.cells.get(t.uid) for s in projet.sections)]
        self.assertEqual(len(fichiers), 1 + len(jouees))
        self.assertTrue(all(f.name.startswith("MORCEAU - ")
                            for f in fichiers[1:]))
        self.assertTrue(etapes and etapes[-1].startswith("Écriture"))
        melange, sr = wav.read(sortie)
        self.assertEqual(sr, 44100)
        self.assertEqual(wav.probe(sortie).bit_depth, 24)
        tempo = projet.style.tempo()
        self.assertGreaterEqual(melange.shape[0] / sr, 4 * 4 * 60.0 / tempo)
        self.assertLessEqual(float(np.abs(melange).max()), 0.981)
        somme = sum(wav.read(f)[0] for f in fichiers[1:])
        self.assertLess(float(np.abs(somme - melange).max()), 1e-4)

    def test_un_meme_gain_pour_toutes_les_pistes(self):
        """Un mélange qui sature est ramené sous la pleine échelle, et
        chaque piste du même gain : leur somme reste le mélange."""
        from unittest import mock

        projet = self._projet()
        pistes = projet.tracks[:2]
        fort = np.full((4410, 2), 0.8, dtype=np.float32)
        plus_fort = np.full((4410, 2), 1.2, dtype=np.float32)
        sortie = Path(self._tmp.name) / "FORT.wav"
        with mock.patch.object(atelier, "render_tracks",
                               return_value=[(pistes[0], fort),
                                             (pistes[1], plus_fort)]):
            fichiers = atelier.export_audio(projet, sortie, stems=True)
        melange = wav.read(fichiers[0])[0]
        a, b = (wav.read(f)[0] for f in fichiers[1:])
        self.assertAlmostEqual(float(np.abs(melange).max()), 0.98, places=3)
        gain = 0.98 / 2.0
        self.assertAlmostEqual(float(a.max()), 0.8 * gain, places=3)
        self.assertAlmostEqual(float(b.max()), 1.2 * gain, places=3)
        self.assertLess(float(np.abs(a + b - melange).max()), 1e-4)

    def test_rien_ne_sonne(self):
        projet = self._projet()
        for section in projet.sections:
            section.cells.clear()
        with self.assertRaises(ValueError):
            atelier.export_audio(projet, Path(self._tmp.name) / "R.wav")
        self.assertIsNone(atelier.export_audio(
            self._projet(), Path(self._tmp.name) / "S.wav",
            should_stop=lambda: True))


# --------------------------------------------------------------------------- #
# Les rangées d'un kit, choisies (13 novembre 2026)
# --------------------------------------------------------------------------- #

class TestLesRangeesChoisies(CarteCase):
    """Choisir les rôles d'un kit, et l'échantillon d'une rangée."""

    def setUp(self):
        super().setUp()
        t = np.linspace(0, 0.2, 8820, endpoint=False, dtype=np.float32)
        for nom in ("909 Snare 2", "808 Snare", "Linn Snare"):
            wav.write(self.root / "SAMPLES" / "DRUMS" / "Snare"
                      / f"{nom}.wav",
                      (0.4 * np.sin(2 * np.pi * 300 * t)).astype(np.float32),
                      44100)
        scan.scan_card(self.sd, self.lib, compute_hash=False)

    def test_les_roles_voulus_et_leur_ordre(self):
        from delugeapp.core import kitgen

        self.assertEqual(len(kitgen.ROLES), len(set(kitgen.ROLES)))
        self.assertEqual(kitgen.ROLES[:len(kitgen.DEFAULT_SLOTS)],
                         kitgen.DEFAULT_SLOTS)
        # Ceux du genre d'abord, dans son ordre ; puis les autres.
        self.assertEqual(kitgen.ordered_slots(
            "techno", {"Cowbell", "HatC", "Kick", "Clap"}),
            ["Kick", "Clap", "HatC", "Cowbell"])
        self.assertTrue({"Kick", "Snare", "Cowbell"}
                        <= kitgen.available_roles(self.lib))
        self.assertNotIn("Timpany", kitgen.available_roles(self.lib))
        kit = kitgen.build_kit(self.sd, self.lib, "CHOISI", genre="techno",
                               seed=1, slots=["Kick", "Snare", "Cowbell"])
        self.assertEqual([kitgen.row_role(r) for r in kit.rows],
                         ["Kick", "Snare", "Cowbell"])

    def test_les_candidats_d_une_rangee(self):
        from delugeapp.core import kitgen

        kit = kitgen.build_kit(self.sd, self.lib, "CHOISI", genre="techno",
                               seed=1, slots=["Kick", "Snare", "HatC"])
        rang = [kitgen.row_role(r) for r in kit.rows].index("Snare")
        actuel = kit.rows[rang].file_name
        candidats = kitgen.row_candidates(kit, rang, self.lib, "techno")
        self.assertTrue(candidats[0]["current"])
        self.assertEqual(candidats[0]["rel"], actuel)
        autres = [c for c in candidats if not c["current"]]
        self.assertEqual(len(autres), 3)
        # La même machine d'abord.
        famille = kitgen.family_of(actuel)
        self.assertEqual(autres[0]["family"], famille)
        noms = {c["name"] for c in autres}
        self.assertTrue({"808 Snare", "Linn Snare"} <= noms)
        # Jamais un son d'une autre rangée du kit, ni d'un autre rôle.
        ailleurs = {sdcard.norm_rel(r.file_name) for i, r in
                    enumerate(kit.rows) if i != rang}
        self.assertFalse(ailleurs & {sdcard.norm_rel(c["rel"])
                                     for c in candidats})
        # Deux rangées du même rôle : chacune écarte le son de l'autre.
        import copy

        kit = kitgen.build_kit(self.sd, self.lib, "DOUBLE", genre="techno",
                               seed=1, slots=["Snare"])
        jumelle = next(c for c in kitgen.row_candidates(kit, 0, self.lib)
                       if not c["current"])
        kit.rows.append(copy.deepcopy(kit.rows[0]))
        kitgen.use_sample(kit, 1, jumelle)
        noms = {c["rel"] for c in kitgen.row_candidates(kit, 0, self.lib)
                if not c["current"]}
        self.assertNotIn(jumelle["rel"], noms)

    def test_poser_un_echantillon_choisi(self):
        from delugeapp.core import kitgen

        kit = kitgen.build_kit(self.sd, self.lib, "CHOISI", genre="techno",
                               seed=1, slots=["Kick", "Snare", "HatC"])
        rang = [kitgen.row_role(r) for r in kit.rows].index("Snare")
        avant = [(r.name, r.file_name) for r in kit.rows]
        candidats = kitgen.row_candidates(kit, rang, self.lib, "techno")
        self.assertIsNone(kitgen.use_sample(kit, rang, candidats[0]))
        linn = next(c for c in candidats if c["name"] == "Linn Snare")
        slot = kitgen.use_sample(kit, rang, linn)
        self.assertEqual(slot.rel, linn["rel"])
        self.assertEqual(kit.rows[rang].file_name, linn["rel"])
        self.assertEqual(kit.rows[rang].name, avant[rang][0])
        self.assertEqual([(r.name, r.file_name) for i, r in
                          enumerate(kit.rows) if i != rang],
                         [x for i, x in enumerate(avant) if i != rang])


# --------------------------------------------------------------------------- #
# Les variations de clips
# --------------------------------------------------------------------------- #

class TestVariationsDeClips(unittest.TestCase):
    """Une variation reste dans la gamme, sur l'harmonie, apparentée."""

    def _parties(self, genre="house", scale="mineur"):
        prog = theory.progression(57, scale, "house", seed=3, bars=4)
        styles = accomp.genre_styles(genre)
        return prog, {
            "Basse": accomp.bass_part(prog, styles[1]),
            "Accords": accomp.chord_part(prog, styles[0]),
            "Arpège": accomp.arp_part(prog, seed=2),
            "Mélodie": accomp.melody_part(prog, root=57, scale=scale,
                                          genre=genre, seed=5),
        }

    def test_dans_la_gamme_et_dans_le_clip(self):
        """Mesuré sur 22 genres × 3 gammes × 4 graines : 0 note hors gamme
        sur 200 000 — après correction de la quinte d'un accord diminué
        (94 basses sur 6 225 sortaient de la gamme)."""
        for scale in ("mineur", "majeur", "dorien"):
            prog, parts = self._parties(scale=scale)
            permises = {(57 + i) % 12 for i in theory.SCALES[scale]}
            for part, events in parts.items():
                permises_partie = permises | {e.note % 12 for e in events}
                for how in variation.MELODIC:
                    for seed in range(3):
                        out = variation.vary_part(
                            events, how, part=part, bars=4, chords=prog,
                            root=57, scale=scale, seed=seed)
                        self.assertTrue(out, (part, how))
                        for e in out:
                            self.assertIn(e.note % 12, permises_partie,
                                          (scale, part, how))
                            self.assertTrue(0 <= e.start < 64)
                            self.assertLessEqual(e.start + e.length, 64.001)

    def test_aucune_variation_ne_rend_l_original(self):
        prog, parts = self._parties()
        for part, events in parts.items():
            for how in variation.MELODIC:
                out = variation.vary_part(events, how, part=part, bars=4,
                                          chords=prog, root=57,
                                          scale="mineur", seed=1)
                self.assertLess(variation.similarity(events, out), 0.999,
                                (part, how))
                # 0,20 : « moins » sur des stabs garde un accord sur cinq —
                # le temps fort de chaque mesure, tenu.
                self.assertGreaterEqual(variation.kinship(events, out),
                                        0.2 - 1e-9, (part, how))

    def test_la_melodie_garde_ses_temps_forts_sur_l_accord(self):
        prog, parts = self._parties()
        for how in variation.MELODIC:
            out = variation.vary_part(parts["Mélodie"], how, part="Mélodie",
                                      bars=4, chords=prog, root=57,
                                      scale="mineur", seed=2)
            for e in out:
                if e.start % 8 == 0:
                    accord = variation.chord_at(prog, int(e.start // 16))
                    classes = {n % 12 for n in accord["notes"]}
                    classes.add(accord["root"] % 12)
                    self.assertIn(e.note % 12, classes, how)

    def test_aucune_note_ne_chevauche_sa_jumelle(self):
        """Le firmware ignorerait la seconde (``NoteRow::readFromFile``)."""
        prog, parts = self._parties()
        for part, events in parts.items():
            for how in variation.MELODIC:
                out = variation.vary_part(events, how, part=part, bars=4,
                                          chords=prog, seed=4)
                par_note = {}
                for e in out:
                    par_note.setdefault(e.note, []).append(e)
                for notes in par_note.values():
                    notes.sort(key=lambda e: e.start)
                    for a, b in zip(notes, notes[1:]):
                        self.assertLessEqual(a.start + a.length,
                                             b.start + 1e-6)

    def test_une_partie_cv_ne_joue_qu_une_note_a_la_fois(self):
        prog, parts = self._parties()
        out = variation.vary_part(parts["Accords"], "rythme", part="Accords",
                                  bars=4, chords=prog, seed=1, mono=True)
        out.sort(key=lambda e: e.start)
        for a, b in zip(out, out[1:]):
            self.assertLessEqual(a.start + a.length, b.start + 1e-6)

    def test_l_octave_est_parente_meme_sans_note_commune(self):
        prog, parts = self._parties()
        out = variation.vary_part(parts["Mélodie"], "octave", part="Mélodie",
                                  bars=4, chords=prog, seed=1)
        self.assertEqual(variation.similarity(parts["Mélodie"], out), 0.0)
        self.assertEqual(variation.kinship(parts["Mélodie"], out), 1.0)

    def test_la_batterie(self):
        for genre in ("techno", "house", "dnb", "dubstep", "lofi"):
            beat = rhythm.genre_beat(genre, bars=2, seed=1)
            for how in ("ornements", "remplissage", "doublée"):
                out = variation.vary_drums(beat, how, genre=genre, seed=2)
                for track in ("Kick", "Snare", "Clap"):
                    avant = {rhythm.cell(s) for s in beat.tracks.get(track, [])}
                    apres = {rhythm.cell(s) for s in out.tracks.get(track, [])}
                    if how == "ornements":
                        self.assertTrue(avant <= apres, (genre, how, track))
            cassure = variation.vary_drums(beat, "cassure", genre=genre)
            self.assertNotIn("Kick", cassure.tracks)
            legere = variation.vary_drums(beat, "légère", genre=genre)
            self.assertFalse({"Snare", "Clap"} & set(legere.tracks))
            demi = variation.vary_drums(beat, "demi-temps", genre=genre)
            caisse = "Snare" if "Snare" in demi.tracks else "Clap"
            self.assertTrue(all(rhythm.cell(s) % 16 == 8
                                for s in demi.tracks.get(caisse, [])))
            for how in variation.DRUMS:
                out = variation.vary_drums(beat, how, genre=genre, seed=3)
                self.assertEqual(out.steps, beat.steps)
                self.assertLess(variation.drum_similarity(beat, out), 0.999,
                                (genre, how))

    def test_doublee_sur_des_charleys_deja_serres(self):
        """Rien à doubler : la variation orne plutôt que de rendre
        l'original (mesuré : parenté 1,00 en psytrance)."""
        beat = rhythm.genre_beat("psytrance", bars=1, seed=1)
        beat.tracks["HatC"] = [rhythm.Step(pos=float(p)) for p in range(16)]
        out = variation.vary_drums(beat, "doublée", genre="psytrance", seed=1)
        self.assertLess(variation.drum_similarity(beat, out), 0.999)


# --------------------------------------------------------------------------- #
# Le projet de l'atelier
# --------------------------------------------------------------------------- #

class TestProjetDeLAtelier(CarteCase):

    def test_un_projet_par_genre(self):
        for genre in genres.genre_keys():
            projet = atelier.new_project(atelier.Style(genre=genre, seed=2))
            self.assertTrue(projet.progression)
            self.assertTrue(projet.sections, genre)
            parts = [t.part for t in projet.tracks]
            self.assertEqual(parts[:3], ["Batterie", "Basse", "Accords"])
            for section in projet.sections:
                for uid, key in section.cells.items():
                    self.assertIsNotNone(projet.track(uid).clip(key))

    def test_la_structure_se_developpe(self):
        """L'intro sans basse, la cassure sans grosse caisse, et le second
        sommet fait répondre la mélodie."""
        projet = atelier.new_project(atelier.Style(genre="house", seed=3))
        par_part = {t.part: t for t in projet.tracks}
        batterie, basse = par_part["Batterie"], par_part["Basse"]
        melodie = par_part["Mélodie"]
        intro = projet.sections[0]
        self.assertNotIn(basse.uid, intro.cells)
        self.assertEqual(batterie.clip(intro.cells[batterie.uid]).origin,
                         "légère")
        cassure = next(s for s in projet.sections if s.kind == "cassure")
        clip = batterie.clip(cassure.cells[batterie.uid])
        self.assertNotIn("Kick", clip.pattern.tracks)
        pics = [s for s in projet.sections if s.kind == "pic"]
        self.assertNotEqual(pics[0].cells[melodie.uid],
                            pics[1].cells[melodie.uid])
        self.assertEqual(melodie.clip(pics[1].cells[melodie.uid]).origin,
                         "réponse")

    def test_pistes_midi_et_cv(self):
        projet = atelier.new_project(atelier.Style(genre="techno", seed=1),
                                     kinds={"Basse": "midi",
                                            "Mélodie": "cv"})
        cv = next(t for t in projet.tracks if t.kind == "cv")
        self.assertTrue(cv.mono)
        for clip in cv.clips:
            notes = sorted(clip.events, key=lambda e: e.start)
            for a, b in zip(notes, notes[1:]):
                self.assertLessEqual(a.start + a.length, b.start + 1e-6)
        with self.assertRaises(ValueError):
            atelier.add_track(projet, "nimporte")
        # Une piste CV ne joue pas d'accords.
        piste = atelier.add_track(projet, "cv", "Accords")
        self.assertNotEqual(piste.part, "Accords")

    def test_un_morceau_neuf_avec_son_arrangement(self):
        projet = atelier.new_project(atelier.Style(genre="techno", seed=3),
                                     sd=self.sd, lib=self.lib,
                                     kinds={"Basse": "midi"})
        spec = atelier.to_song_spec(projet, "ATELIER", sd=self.sd,
                                    lib=self.lib)
        res = songwriter.write_song(self.sd, spec, apply=True)
        self.assertTrue(res.applied, res.error)
        song = Song.load(self.sd.abs(res.rel))
        self.assertEqual(len({c.section for c in song.clips}),
                         len(projet.sections))
        self.assertIn("midi", {c.kind for c in song.clips})
        texte = self.sd.abs(res.rel).read_text(encoding="utf-8")
        self.assertIn("clipInstances", texte)
        self.assertTrue(all(c.note_count for c in song.clips))

    def test_une_batterie_sans_kit_ne_s_ecrit_pas(self):
        projet = atelier.new_project(atelier.Style(genre="techno", seed=3))
        with self.assertRaises(ValueError):
            atelier.to_song_spec(projet, "SANS KIT")

    def test_aller_retour_par_la_carte(self):
        """Écrit, relu : mêmes pistes et parties, même progression."""
        projet = atelier.new_project(atelier.Style(genre="house", seed=7),
                                     sd=self.sd, lib=self.lib)
        spec = atelier.to_song_spec(projet, "RETOUR", sd=self.sd,
                                    lib=self.lib)
        res = songwriter.write_song(self.sd, spec, apply=True)
        song = Song.load(self.sd.abs(res.rel))
        relu = atelier.from_song(song, self.sd)
        self.assertEqual(sorted(t.part for t in relu.tracks),
                         sorted(t.part for t in projet.tracks))
        self.assertEqual([c["name"] for c in relu.progression],
                         [c["name"] for c in projet.progression])
        self.assertEqual(relu.song_rel, res.rel)
        self.assertTrue(all(c.existing is not None
                            for t in relu.tracks for c in t.clips))

    def test_une_melodie_n_est_pas_prise_pour_des_accords(self):
        """Mon premier jet comptait les attaques de tous les clips d'une
        piste ensemble : trois clips de mélodie aux mêmes temps passaient
        pour des accords de trois notes."""
        phrase = [(0, 4), (4, 2), (6, 2), (8, 6), (14, 2)]
        clips = [atelier.AtelierClip(key=k, events=[
            accomp.NoteEvent(bar * 16 + s, d, 72 + (s % 5), 90)
            for bar in range(4) for s, d in phrase]) for k in "ABC"]
        self.assertEqual(atelier._guess_part(clips), "Mélodie")
        accords = [atelier.AtelierClip(key="A", events=[
            accomp.NoteEvent(s, 4.0, n, 80) for s in range(0, 64, 16)
            for n in (57, 60, 64)])]
        self.assertEqual(atelier._guess_part(accords), "Accords")

    def test_la_progression_se_lit_dans_les_notes(self):
        for ambiance in ("pop", "mélancolique", "house"):
            prog = theory.progression(57, "mineur", ambiance, seed=1, bars=4)
            events = accomp.chord_part(prog, "tenu")
            lue = atelier.infer_progression(events, 57, "mineur", 4)
            self.assertEqual([c["name"] for c in lue],
                             [c["name"] for c in prog], ambiance)

    def test_variations_et_cases(self):
        projet = atelier.new_project(atelier.Style(genre="dnb", seed=4),
                                     structure=False)
        basse = next(t for t in projet.tracks if t.part == "Basse")
        clip = atelier.vary_clip(projet, basse.uid, "A", "fin")
        self.assertEqual(clip.parent, "A")
        section = atelier.add_section(projet, "Refrain", bars=8)
        atelier.set_cell(projet, 0, basse.uid, clip.key)
        self.assertEqual(section.cells[basse.uid], clip.key)
        atelier.remove_clip(projet, basse.uid, clip.key)
        self.assertNotIn(basse.uid, section.cells)
        with self.assertRaises(ValueError):
            atelier.set_cell(projet, 0, basse.uid, "Z9")


# --------------------------------------------------------------------------- #
# Compléter un morceau sans le réécrire
# --------------------------------------------------------------------------- #

class TestCompleterUnMorceau(CarteCase):
    """Le nouveau fichier est l'original octet pour octet, plus des ajouts."""

    def _morceau(self, nom="ORIGINE", layout=None, version=None):
        projet = atelier.new_project(atelier.Style(genre="house", seed=2),
                                     sd=self.sd, lib=self.lib,
                                     structure=False)
        projet.sections = [atelier.AtelierSection(
            name="Boucle", bars=4,
            cells={t.uid: "A" for t in projet.tracks})]
        spec = atelier.to_song_spec(projet, nom, sd=self.sd, lib=self.lib)
        res = songwriter.write_song(self.sd, spec, apply=True)
        chemin = self.sd.abs(res.rel)
        data = chemin.read_bytes()
        if layout is not None:
            data = data.replace(b'sessionLayout="0"',
                                b'sessionLayout="%s"' % layout.encode())
        if version is not None:
            data = data.replace(b'firmwareVersion="c1.2.1"',
                                b'firmwareVersion="%s"' % version.encode(), 1)
        chemin.write_bytes(data)
        return res.rel, data

    def _projet_complete(self, rel):
        projet = atelier.from_song(Song.load(self.sd.abs(rel)), self.sd)
        for piste in projet.tracks:
            how = "remplissage" if piste.is_drums else "notes"
            atelier.vary_clip(projet, piste.uid, "A", how, seed=1)
        atelier.add_track(projet, "midi", "Basse", channel=6)
        refrain = atelier.add_section(projet, "Refrain", bars=8)
        for piste in projet.tracks:
            refrain.cells[piste.uid] = piste.clips[-1].key
        pont = atelier.add_section(projet, "Pont", bars=4)
        for piste in projet.tracks:
            pont.cells[piste.uid] = piste.clips[0].key
        return projet

    def test_l_original_s_y_retrouve_octet_pour_octet(self):
        rel, data = self._morceau()
        projet = self._projet_complete(rel)
        plan, _notes = atelier.insertion_plan(projet, self.sd, self.lib)
        self.assertFalse(plan.error, plan.error)
        self.assertEqual(songinsert.verify(data, plan), "")
        # Les ajouts défaits, il reste exactement l'original.
        self.assertEqual(plan.rel, "SONGS/ORIGINE 2.XML")
        self.assertEqual(self.sd.abs(rel).read_bytes(), data)
        res = songinsert.write_insert(self.sd, plan, apply=True)
        self.assertTrue(res.applied, res.error)
        self.assertEqual(self.sd.abs(rel).read_bytes(), data,
                         "l'original a changé")
        avant, apres = Song.load(self.sd.abs(rel)), \
            Song.load(self.sd.abs(plan.rel))
        n = len(avant.clips)
        self.assertEqual([c.note_count for c in avant.clips],
                         [c.note_count for c in apres.clips[:n]])
        nouveaux = apres.clips[n:]
        self.assertTrue(nouveaux)
        self.assertTrue(all(c.note_count for c in nouveaux))
        self.assertTrue(all(c.section >= 1 for c in nouveaux))
        self.assertIn("midi", {c.kind for c in nouveaux})
        self.assertEqual(len(apres.instruments), len(avant.instruments) + 1)

    def test_la_simulation_n_ecrit_rien(self):
        rel, _data = self._morceau()
        projet = self._projet_complete(rel)
        plan, _ = atelier.insertion_plan(projet, self.sd, self.lib)
        avant = sorted(p.name for p in (self.root / "SONGS").iterdir())
        res = songinsert.write_insert(self.sd, plan, apply=False)
        self.assertFalse(res.applied)
        self.assertEqual(sorted(p.name for p in (self.root / "SONGS")
                                .iterdir()), avant)

    def test_un_fichier_apparu_n_est_pas_remplace(self):
        rel, _data = self._morceau()
        plan, _ = atelier.insertion_plan(self._projet_complete(rel),
                                         self.sd, self.lib)
        self.sd.abs(plan.rel).write_bytes(b"deja la")
        res = songinsert.write_insert(self.sd, plan, apply=True)
        self.assertFalse(res.applied)
        self.assertEqual(self.sd.abs(plan.rel).read_bytes(), b"deja la")

    def test_un_morceau_13_recoit_le_format_13(self):
        """Seuls des clips neufs ici : une copie garde le blob de son
        original (mon premier essai, sur un morceau dont seule la version
        disait 1.3, y trouvait donc l'ancien)."""
        rel, _data = self._morceau(nom="UN TREIZE", version="c1.3.0")
        projet = atelier.from_song(Song.load(self.sd.abs(rel)), self.sd)
        variante = atelier.add_section(projet, "Variante", bars=4)
        variante.cells = {}
        for piste in projet.tracks:
            how = "remplissage" if piste.is_drums else "notes"
            clip = atelier.vary_clip(projet, piste.uid, "A", how, seed=1)
            variante.cells[piste.uid] = clip.key
        plan, _ = atelier.insertion_plan(projet, self.sd, self.lib)
        self.assertFalse(plan.error, plan.error)
        ajouts = b"".join(e[2] for e in plan.edits)
        self.assertIn(b"noteDataWithSplitProb", ajouts)
        self.assertNotIn(b"noteDataWithLift", ajouts)

    def test_l_arrangement_seul_ne_bouge_pas(self):
        """Comme « Calm Down », réenregistré par la 1.3 le 22 octobre 2026 :
        des clips d'arrangement seul, que les instances désignent par le bit
        31 (``80000000``…, ``Song::setupClipIndexesForSaving``). Les clips
        neufs vont en fin de ``<sessionClips>`` : aucune référence ne
        bouge, et le bloc d'arrangement reste identique à l'octet."""
        import re

        rel, data = self._morceau(nom="AVEC ARRANGEMENT", version="c1.3.0")
        debut = data.index(b"<sessionClips>")
        clip = re.search(rb"<instrumentClip\b.*?</instrumentClip>",
                         data[debut:], re.S).group(0)
        clip = re.sub(rb'\s+section="\d+"', b"", clip, count=1)
        bloc = (b"\n\t<arrangementOnlyTracks>\n\t\t" + clip
                + b"\n\t</arrangementOnlyTracks>")
        fin = data.index(b"</sessionClips>") + len(b"</sessionClips>")
        data = data[:fin] + bloc + data[fin:]
        instances = re.search(rb'clipInstances="0x([0-9A-Fa-f]*)"', data)
        self.assertIsNotNone(instances, "le morceau écrit a un arrangement")
        data = (data[:instances.end(1)] + b"000100000000060080000000"
                + data[instances.end(1):])
        self.sd.abs(rel).write_bytes(data)
        avant = Song.load(self.sd.abs(rel))
        self.assertEqual(len(avant.arrangement_clips), 1)

        projet = atelier.from_song(avant, self.sd)
        pont = atelier.add_section(projet, "Pont", bars=4)
        pont.cells = {}
        for piste in projet.tracks:
            how = "remplissage" if piste.is_drums else "notes"
            pont.cells[piste.uid] = atelier.vary_clip(
                projet, piste.uid, "A", how, seed=3).key
        plan, _ = atelier.insertion_plan(projet, self.sd, self.lib)
        self.assertFalse(plan.error, plan.error)
        res = songinsert.write_insert(self.sd, plan, apply=True)
        self.assertTrue(res.applied, res.error)
        neuf = self.sd.abs(plan.rel).read_bytes()
        self.assertIn(bloc, neuf)
        self.assertEqual(
            re.findall(rb'clipInstances="0x([0-9A-Fa-f]*)"', data),
            re.findall(rb'clipInstances="0x([0-9A-Fa-f]*)"', neuf))
        self.assertLess(neuf.rindex(b"noteDataWithSplitProb"),
                        neuf.index(b"<arrangementOnlyTracks>"),
                        "les clips neufs restent dans la session")
        apres = Song.load(self.sd.abs(plan.rel))
        self.assertEqual(len(apres.arrangement_clips), 1)
        self.assertGreater(len(apres.clips), len(avant.clips))

    def test_un_morceau_ancien_est_refuse(self):
        rel, _data = self._morceau(nom="ANCIEN", version="3.0.4")
        projet = self._projet_complete(rel)
        with self.assertRaises(ValueError):
            atelier.insertion_plan(projet, self.sd, self.lib)

    def test_en_grille_un_clip_ne_se_cache_pas(self):
        """En disposition grille, une case piste × section ne montre qu'un
        clip : un clip neuf d'une piste qui en a déjà un dans la section est
        refusé (le nouveau y serait invisible)."""
        rel, _data = self._morceau(nom="GRILLE", layout="1")
        cible = songinsert.read_target(self.sd, rel)
        piste = next(i for i, t in enumerate(cible.tracks) if t.clips)
        clip = songinsert.NewClip(track=piste, section=0, rows={
            60: [Note(pos=0, length=96, velocity=100)]}, length=384,
            name="Cache")
        plan = songinsert.plan_insert(self.sd, cible, [], [clip])
        self.assertTrue(plan.error)
        clip.section = 3
        plan = songinsert.plan_insert(self.sd, cible, [], [clip])
        self.assertFalse(plan.error, plan.error)

    def test_les_repetitions_ne_touchent_que_les_sections_neuves(self):
        rel, data = self._morceau(nom="REPETE")
        cible = songinsert.read_target(self.sd, rel)
        plan = songinsert.plan_insert(self.sd, cible, [], [], {0: 4})
        self.assertTrue(plan.error, "la section 0 est au morceau")
        plan = songinsert.plan_insert(self.sd, cible, [], [], {5: 3})
        self.assertFalse(plan.error, plan.error)
        self.assertEqual(len(plan.edits), 1)
        position, old, new = plan.edits[0]
        self.assertIn(b'id="5"', old)
        self.assertIn(b'numRepeats="3"', new)
        self.assertEqual(songinsert.verify(data, plan), "")

    def test_la_version_suivante(self):
        for nom in ("Cool1 4", "Cool1 2"):
            (self.root / "SONGS" / ("%s.XML" % nom)).write_bytes(b"x")
        self.assertEqual(songinsert.next_version(self.sd, "Cool1 4"),
                         "SONGS/Cool1 5.XML")
        self.assertEqual(songinsert.next_version(self.sd, "Calm Down"),
                         "SONGS/Calm Down.XML")
        self.assertEqual(songinsert.next_version(
            self.sd, "Le Mans - D dièse Major 3"),
            "SONGS/Le Mans - D diese Major 4.XML")

    def test_une_preuve_qui_echoue_empeche_l_ecriture(self):
        rel, data = self._morceau(nom="PREUVE")
        plan, _ = atelier.insertion_plan(self._projet_complete(rel),
                                         self.sd, self.lib)
        plan.data = plan.data.replace(b"ORIGINE", b"0RIGINE")
        abime = plan.data.replace(b'section="0"', b'section="9"', 1)
        plan.data = abime
        self.assertTrue(songinsert.verify(data, plan))

    def test_les_rangees_de_kit_suivent_leur_son(self):
        """Une rangée désigne son son par ``drumIndex`` : réordonnées sur
        la machine, les rangées gardent chacune ses notes."""
        rel, data = self._morceau(nom="KIT")
        texte = data.decode("utf-8")
        # Les deux premières rangées du clip de kit échangent leur son.
        texte = texte.replace('drumIndex="0"', 'drumIndex="@"', 1)
        texte = texte.replace('drumIndex="1"', 'drumIndex="0"', 1)
        texte = texte.replace('drumIndex="@"', 'drumIndex="1"', 1)
        self.sd.abs(rel).write_text(texte, encoding="utf-8")
        song = Song.load(self.sd.abs(rel))
        kit_clip = next(c for c in song.clips if c.kind == "kit")
        self.assertEqual(kit_clip.note_rows[0].drum_index, 1)
        projet = atelier.from_song(song, self.sd)
        batterie = next(t for t in projet.tracks if t.is_drums)
        ordre = atelier.drum_rows(batterie)
        noms = songinsert._drum_names(song.doc.root, batterie.name)
        self.assertEqual(ordre[0], noms[1])
        self.assertEqual(ordre[1], noms[0])


# --------------------------------------------------------------------------- #
# Jouer calé sur la machine
# --------------------------------------------------------------------------- #

class _Sortie:
    is_open = True

    def __init__(self):
        self.recus = []

    def note_on(self, note, velocity=100, channel=1):
        self.recus.append(("on", note, time.perf_counter()))
        return True

    def note_off(self, note, channel=1):
        self.recus.append(("off", note, time.perf_counter()))
        return True

    def all_notes_off(self, channel=None):
        pass


class TestJouerCaleSurLaMachine(unittest.TestCase):

    def test_la_position_suit_l_horloge(self):
        transport = Transport()
        t0 = time.perf_counter()
        transport.feed(midiport.START, at=t0)
        for k in range(10):
            transport.feed(midiport.CLOCK, at=t0 + k * 0.02)
        self.assertEqual(transport.ticks, 9)
        self.assertAlmostEqual(transport.period, 0.02, places=4)
        self.assertAlmostEqual(transport.time_of(12), t0 + 12 * 0.02,
                               places=4)
        self.assertAlmostEqual(transport.tempo, 125.0, places=1)

    def test_le_pointeur_de_position(self):
        """F2 en doubles-croches, puis CONTINUE : la première impulsion
        est à cette position."""
        transport = Transport()
        transport.feed(midiport.SONG_POSITION, 32, 0)     # 32 × 6 impulsions
        transport.feed(midiport.CONTINUE)
        transport.feed(midiport.CLOCK)
        self.assertEqual(transport.ticks, 192)
        transport.feed(midiport.STOP)
        self.assertFalse(transport.snapshot()[0])

    def test_la_prochaine_boucle(self):
        transport = Transport()
        maintenant = time.perf_counter()
        t0 = maintenant - 29 * 0.02
        transport.feed(midiport.START, at=t0)
        for k in range(30):
            transport.feed(midiport.CLOCK, at=t0 + k * 0.02)
        self.assertEqual(transport.next_boundary(96), 96)
        self.assertEqual(transport.next_boundary(24), 48)
        # Repartie : la première impulsion est le temps zéro, et la durée
        # d'une impulsion est déjà connue — on joue la boucle tout de suite.
        transport.feed(midiport.STOP)
        transport.feed(midiport.START)
        transport.feed(midiport.CLOCK)
        self.assertEqual(transport.ticks, 0)
        self.assertEqual(transport.next_boundary(96), 0)

    def test_le_clip_part_sur_la_mesure_et_suit_l_horloge(self):
        lien = DelugeLink()
        lien._out = _Sortie()
        periode = 60.0 / 123.0 / 24.0
        arret = threading.Event()
        depart = {}

        def horloge():
            lien.transport.feed(midiport.START)
            t0 = time.perf_counter() + 0.01
            depart["t0"] = t0
            k = 0
            while not arret.is_set():
                cible = t0 + k * periode
                while time.perf_counter() < cible:
                    time.sleep(0.0005)
                lien.transport.feed(midiport.CLOCK, at=cible)
                k += 1

        fil = threading.Thread(target=horloge, daemon=True)
        fil.start()
        try:
            time.sleep(0.6)                 # au milieu de la première mesure
            notes = [(s, 0.5, 36, 100) for s in range(0, 16, 4)]
            self.assertTrue(lien.play_synced(notes, 16, loops=1))
            for _ in range(400):
                if not lien.is_playing:
                    break
                time.sleep(0.01)
        finally:
            arret.set()
            fil.join(1.0)
        attaques = [t for kind, _n, t in lien._out.recus if kind == "on"]
        self.assertEqual(len(attaques), 4)
        # Au début de la mesure suivante, à quelques millisecondes près
        # (mesuré : 1,7 ms d'avance voulue, ±0,8 ms). Les machines de GitHub,
        # partagées, ont pris 51 ms de retard (macOS, 9 novembre 2026) :
        # 80 ms y gardent chaque note sur son pas (une double-croche dure
        # 122 ms à 123 BPM).
        ecart = 0.08 if _os.environ.get("GITHUB_ACTIONS") else 0.012
        for attaque, pas in zip(attaques, range(0, 16, 4)):
            attendu = depart["t0"] + (96 + pas * 6) * periode
            self.assertAlmostEqual(attaque, attendu, delta=ecart)

    def test_la_machine_s_arrete_le_jeu_aussi(self):
        lien = DelugeLink()
        lien._out = _Sortie()
        t0 = time.perf_counter()
        lien.transport.feed(midiport.START, at=t0)
        for k in range(5):
            lien.transport.feed(midiport.CLOCK, at=t0 + k * 0.02)
        lien.transport.last = time.perf_counter()
        self.assertTrue(lien.play_synced([(0, 1, 60, 100)], 16, loops=0))
        lien.transport.feed(midiport.STOP)
        for _ in range(200):
            if not lien.is_playing:
                break
            time.sleep(0.01)
        self.assertFalse(lien.is_playing)

    def test_machine_arretee_le_clip_joue_au_tempo_donne(self):
        lien = DelugeLink()
        lien._out = _Sortie()
        self.assertTrue(lien.play_synced([(0, 1, 60, 100), (4, 1, 62, 100)],
                                         8, bpm=240.0))
        for _ in range(300):
            if not lien.is_playing:
                break
            time.sleep(0.01)
        attaques = [t for kind, _n, t in lien._out.recus if kind == "on"]
        self.assertEqual(len(attaques), 2)
        # 4 doubles-croches à 240 BPM : 250 ms.
        self.assertAlmostEqual(attaques[1] - attaques[0], 0.25, delta=0.03)

    def test_les_notes_d_une_batterie_suivent_ses_rangees(self):
        projet = atelier.new_project(atelier.Style(genre="techno", seed=1),
                                     structure=False)
        batterie = next(t for t in projet.tracks if t.is_drums)
        notes, steps = atelier.live_notes(projet, batterie.uid, "A",
                                          kit_root=36)
        self.assertEqual(steps, 64)
        ordre = atelier.drum_rows(batterie)
        self.assertEqual(ordre[0], "Kick")
        kicks = [n for n in notes if n[2] == 36]
        self.assertEqual(len(kicks), len(batterie.clip("A")
                                         .pattern.tracks["Kick"]))


# --------------------------------------------------------------------------- #
# Modifier un son à la main
# --------------------------------------------------------------------------- #

class TestLesReglagesDuSon(CarteCase):
    """:mod:`soundedit` : chaque réglage se lit, s'écrit, se décrit en clair
    — et une retouche arrive jusque dans le morceau écrit."""

    def setUp(self):
        super().setUp()
        from delugeapp.core import soundedit

        self.se = soundedit
        self.son = synthgen.generate(synthgen.GenOptions(
            genre="house", role="pad", seed=4)).sound

    def test_chaque_reglage_va_et_revient(self):
        for c in self.se.CONTROLS:
            with self.subTest(reglage=c.key):
                son = self.se.copy_sound(self.son)
                if c.kind == "choice":
                    for valeur, _libelle in c.choices:
                        if c.key == "mode":
                            continue
                        self.se.set_value(son, c.key, valeur)
                        self.assertEqual(self.se.value(son, c.key), valeur)
                else:
                    for valeur in (c.minimum, c.maximum,
                                   (c.minimum + c.maximum) // 2):
                        self.se.set_value(son, c.key, valeur)
                        self.assertEqual(int(self.se.value(son, c.key)),
                                         valeur)
                    # Hors bornes : ramené aux bornes du menu de la machine.
                    self.se.set_value(son, c.key, c.maximum + 40)
                    self.assertEqual(int(self.se.value(son, c.key)),
                                     c.maximum)

    def test_ce_que_vaut_un_reglage(self):
        se, son = self.se, self.se.copy_sound(self.son)
        for cle, cran, attendu in (
                ("env1.decay", 13, "1,8 s"), ("env1.attack", 0, "instantané"),
                ("env1.sustain", 25, "50 %"), ("lpfFrequency", 19, "237 Hz"),
                ("lpfFrequency", 40, "6,2 kHz"), ("portamento", 0, "coupé"),
                ("portamento", 7, "58 ms"), ("volume", 25, "-12,0 dB"),
                ("pan", 0, "centre"), ("hpfFrequency", 0, "tout passe")):
            with self.subTest(reglage=cle, cran=cran):
                se.set_value(son, cle, cran)
                self.assertEqual(se.describe(son, cle), attendu)
        son.unison_num = 2
        se.set_value(son, "unison.detune", 8)
        self.assertEqual(se.describe(son, "unison.detune"), "±4,0 cents")

    def test_passer_en_fm_eteint_les_filtres_comme_la_machine(self):
        se, son = self.se, self.se.copy_sound(self.son)
        self.assertFalse(se.visible(son, "modulator1Amount"))
        se.set_value(son, "mode", "fm")
        self.assertEqual((son.lpf_mode, son.hpf_mode), ("Off", "Off"))
        self.assertTrue(se.visible(son, "modulator1Amount"))
        self.assertFalse(se.visible(son, "osc1.type"))
        se.set_value(son, "mode", "subtractive")
        self.assertEqual((son.lpf_mode, son.hpf_mode), ("24dB", "HPLadder"))

    def test_les_modulations(self):
        from delugeapp.core.model import PatchCable

        se, son = self.se, self.se.copy_sound(self.son)
        avant = len(son.patch_cables)
        cable = se.add_cable(son, "lfo1", "pitch", 5)
        self.assertEqual(len(son.patch_cables), avant + 1)
        self.assertEqual(se.describe_cable(cable), "±0,34 demi-ton")
        filtre = PatchCable("envelope2", "lpfFrequency",
                            PatchCable.amount_from_display(25))
        self.assertEqual(se.describe_cable(filtre), "±4,0 octave(s)")
        filtre.polarity = "unipolar"
        self.assertEqual(se.describe_cable(filtre), "+4,0 octave(s)")
        se.set_cable(son, avant, destination="oscAPulseWidth", depth=-10,
                     polarity="unipolar")
        modifie = son.patch_cables[avant]
        self.assertEqual((modifie.destination, modifie.display(),
                          modifie.polarity),
                         ("oscAPhaseWidth", -10, "unipolar"))
        se.remove_cable(son, avant)
        self.assertEqual(len(son.patch_cables), avant)

    def test_les_differences_se_lisent(self):
        se, son = self.se, self.se.copy_sound(self.son)
        self.assertEqual(se.differences(self.son, son), [])
        se.set_value(son, "lpfFrequency", 44)
        # Un mode différent de celui du son (ce pad-là est déjà en 12 dB).
        se.set_value(son, "lpf_mode",
                     "24dB" if son.lpf_mode != "24dB" else "12dB")
        changes = se.differences(self.son, son)
        self.assertTrue(any(c.startswith("Coupure :") and c.endswith("→ 44")
                            for c in changes), changes)
        self.assertTrue(any(c.startswith("Passe-bas :") for c in changes))

    def test_une_retouche_arrive_dans_le_morceau_ecrit(self):
        """Le son retouché d'une piste est celui que le morceau porte — un
        aller-retour par le fichier, pas une supposition."""
        se = self.se
        projet = atelier.new_project(atelier.Style(genre="house", seed=2),
                                     sd=self.sd, lib=self.lib,
                                     structure=False)
        piste = next(t for t in projet.tracks if t.kind == "synth")
        son = se.copy_sound(piste.preset.sound)
        se.set_value(son, "lpfFrequency", 44)
        se.set_value(son, "env1.release", 30)
        cable = se.add_cable(son, "envelope2", "lpfFrequency", 20)
        cable.polarity = "unipolar"
        son.name = "MA NAPPE"
        self.assertTrue(atelier.edit_sound(projet, piste.uid, son))
        self.assertTrue(piste.edited)
        projet.sections = [atelier.AtelierSection(
            name="Boucle", bars=4,
            cells={t.uid: "A" for t in projet.tracks})]
        spec = atelier.to_song_spec(projet, "RETOUCHE", sd=self.sd,
                                    lib=self.lib)
        fait = songwriter.write_song(self.sd, spec, apply=True)
        self.assertTrue(fait.applied, fait.error)
        racine = dxml.load(self.sd.abs(fait.rel)).root
        clip = next(c for c in racine.find("sessionClips")
                    if c.get("instrumentPresetName") == "MA NAPPE")
        params = clip.find("soundParams")
        self.assertEqual(to_display(params.get("lpfFrequency")), 44)
        self.assertEqual(to_display(params.find("envelope1").get("release")),
                         30)
        cables = [(c.get("source"), c.get("destination"), c.get("polarity"))
                  for c in params.iter("patchCable")]
        self.assertIn(("envelope2", "lpfFrequency", "unipolar"), cables)

    def test_une_piste_du_morceau_d_origine_ne_se_retouche_pas(self):
        projet = atelier.new_project(atelier.Style(genre="house", seed=2),
                                     sd=self.sd, lib=self.lib,
                                     structure=False)
        piste = next(t for t in projet.tracks if t.kind == "synth")
        piste.existing = {"kind": "sound", "name": "X"}
        avant = piste.preset
        self.assertFalse(atelier.edit_sound(projet, piste.uid,
                                            self.se.copy_sound(self.son)))
        self.assertIs(piste.preset, avant)

    def test_une_retouche_se_reporte_sur_une_variante(self):
        """``carry_edits`` : un réglage tourné l'est d'autant ; un choix reste,
        sauf si la variante change ce choix-là ; la FM éteint les filtres."""
        se = self.se
        depart = se.copy_sound(self.son)
        depart.mode, depart.lpf_mode = "subtractive", "24dB"
        se.set_value(depart, "lpfFrequency", 25)
        se.set_value(depart, "env2.decay", 10)
        depart.osc1.type, depart.osc2.type = "saw", "square"
        retouche = se.copy_sound(depart)
        se.set_value(retouche, "lpfFrequency", 31)
        se.set_value(retouche, "osc1.type", "triangle")
        se.set_value(retouche, "osc2.type", "sine")
        variante = se.copy_sound(depart)
        se.set_value(variante, "lpfFrequency", 48)
        se.set_value(variante, "osc2.type", "analogSaw")
        se.set_value(variante, "env2.decay", 18)
        variante.name = "VARIANTE 2"
        r = se.carry_edits(depart, retouche, variante)
        self.assertEqual(se.value(r, "lpfFrequency"), 50)   # 48 + 6, borné
        self.assertEqual(r.osc1.type, "triangle")           # la vôtre
        self.assertEqual(r.osc2.type, "analogSaw")          # celle de la variante
        self.assertEqual(se.value(r, "env2.decay"), 18)
        self.assertEqual(r.name, "VARIANTE 2")
        self.assertEqual(se.value(variante, "lpfFrequency"), 48)
        # Passé en FM à la main : filtres éteints, même si la variante en
        # tire un autre.
        fm = se.copy_sound(depart)
        se.set_value(fm, "mode", "fm")
        se.set_value(variante, "lpf_mode", "12dB")
        r = se.carry_edits(depart, fm, variante)
        self.assertEqual((r.mode, r.lpf_mode, r.hpf_mode), ("fm", "Off", "Off"))

    def test_les_modulations_retouchees_se_reportent(self):
        from delugeapp.core.model import param_of_destination

        se = self.se

        def cables(son):
            return {(c.source, param_of_destination(c.destination)):
                    (c.display(), c.polarity or "bipolar")
                    for c in son.patch_cables}

        depart = se.copy_sound(self.son)
        depart.patch_cables = []
        se.add_cable(depart, "lfo1", "lpfFrequency", 10)
        se.add_cable(depart, "envelope2", "lpfFrequency", 20)
        se.add_cable(depart, "velocity", "volume", 30)
        se.add_cable(depart, "note", "hpfFrequency", 8)
        retouche = se.copy_sound(depart)
        se.set_cable(retouche, 0, depth=16)
        se.set_cable(retouche, 1, polarity="unipolar")
        se.remove_cable(retouche, 2)
        se.add_cable(retouche, "lfo2", "pan", 17)
        variante = se.copy_sound(depart)
        se.set_cable(variante, 0, depth=30)
        se.remove_cable(variante, 3)
        se.add_cable(variante, "random", "pitch", 5)
        r = cables(se.carry_edits(depart, retouche, variante))
        self.assertEqual(r, {
            ("lfo1", "lpfFrequency"): (36, "bipolar"),        # 30 + 6
            ("envelope2", "lpfFrequency"): (20, "unipolar"),  # votre polarité
            ("random", "pitch"): (5, "bipolar"),              # ajoutée par elle
            ("lfo2", "pan"): (17, "bipolar"),                 # ajoutée par vous
        })                      # retirées : la vôtre, et celle de la variante

    def test_les_variantes_d_un_son_retouche_gardent_les_retouches(self):
        """La demande : « une fois un son retouché, les 8 variantes proposées
        doivent prendre en compte les modifications apportées au son »."""
        from delugeapp.core.model import param_of_destination

        se = self.se
        projet = atelier.new_project(atelier.Style(genre="house", seed=2),
                                     sd=self.sd, lib=self.lib,
                                     structure=False)
        piste = next(t for t in projet.tracks if t.kind == "synth")
        genere = se.copy_sound(piste.preset.sound)
        self.assertFalse(any(v.retouched for v in atelier.sound_variations(
            projet, piste.uid, 8, seed=5)))
        son = se.copy_sound(genere)
        se.set_value(son, "env1.release", 44)
        se.set_value(son, "osc1.type", "triangle")
        se.add_cable(son, "lfo2", "pan", 17)
        son.name = "MA NAPPE"
        atelier.edit_sound(projet, piste.uid, son)
        variantes = atelier.sound_variations(projet, piste.uid, 8, seed=5)
        self.assertEqual(len(variantes), 8)
        for v in variantes:
            with self.subTest(variante=v.label):
                r = v.preset.sound
                brute = synthgen.generate(v.options).sound
                ecart = se.value(brute, "env1.release") \
                    - se.value(genere, "env1.release")
                self.assertEqual(se.value(r, "env1.release"),
                                 max(0, min(50, 44 + ecart)))
                if brute.osc1.type == genere.osc1.type:
                    self.assertEqual(r.osc1.type, "triangle")
                self.assertIn(("lfo2", "pan", 17), [
                    (c.source, param_of_destination(c.destination),
                     c.display()) for c in r.patch_cables])
                self.assertTrue(v.preset.name.startswith("MA NAPPE "))
                self.assertTrue(v.retouched)
                self.assertEqual(r.arp.mode, "off")
        # Adoptée, la variante reste retouchée, et ses propres variantes
        # gardent la modulation ajoutée à la main.
        atelier.adopt_sound(projet, piste.uid, variantes[0])
        self.assertTrue(piste.edited)
        for v in atelier.sound_variations(projet, piste.uid, 8, seed=6):
            self.assertIn(("lfo2", "pan"), [
                (c.source, param_of_destination(c.destination))
                for c in v.preset.sound.patch_cables])

    def test_une_variante_qui_ne_change_plus_rien_est_ecartee(self):
        from unittest import mock

        se = self.se
        projet = atelier.new_project(atelier.Style(genre="house", seed=2),
                                     sd=self.sd, lib=self.lib,
                                     structure=False)
        piste = next(t for t in projet.tracks if t.kind == "synth")
        son = se.copy_sound(piste.preset.sound)
        se.set_value(son, "env1.release", 44)
        atelier.edit_sound(projet, piste.uid, son)
        # Une variante qui serait le son généré lui-même : retouchée, elle
        # redevient le son de la piste.
        pareille = synthgen.Variant("Pareille", piste.options,
                                    atelier._generate(piste.options))
        autre = synthgen.style_variations(piste.options, 1, seed=1)[0]
        with mock.patch.object(synthgen, "style_variations",
                               return_value=[pareille, autre]):
            out = atelier.sound_variations(projet, piste.uid, 8, seed=1)
        self.assertEqual([v.label for v in out], [autre.label])



# --------------------------------------------------------------------------- #
# Ce que l'atelier garde (7 novembre 2026)
# --------------------------------------------------------------------------- #

class TestLAtelierGardeLeTravail(CarteCase):
    """Les notes dessinées, le brouillon, la version qu'on remplace."""

    def _basse(self, projet):
        piste = next(t for t in projet.tracks if t.part == "Basse")
        return piste, piste.clips[0]

    def test_une_note_s_ajoute_puis_se_retire(self):
        projet = atelier.new_project(atelier.Style(genre="techno", seed=4))
        piste, clip = self._basse(projet)
        clip.events[:] = []
        self.assertTrue(atelier.toggle_note(projet, piste.uid, clip.key,
                                            45, 3))
        self.assertEqual([(e.start, e.length, e.note) for e in clip.events],
                         [(3.0, 2.0, 45)])
        # Un clic sur la note, à son second pas, la retire.
        self.assertFalse(atelier.toggle_note(projet, piste.uid, clip.key,
                                             45, 4))
        self.assertEqual(clip.events, [])

    def test_une_note_neuve_ne_chevauche_pas_la_suivante(self):
        """Le Deluge ignore une note qui chevauche la précédente sur sa
        rangée : la neuve s'arrête où la suivante commence."""
        projet = atelier.new_project(atelier.Style(genre="techno", seed=4))
        piste, clip = self._basse(projet)
        clip.events[:] = [accomp.NoteEvent(5.0, 1.0, 45, 90)]
        atelier.toggle_note(projet, piste.uid, clip.key, 45, 4)
        self.assertEqual(sorted((e.start, e.length) for e in clip.events),
                         [(4.0, 1.0), (5.0, 1.0)])

    def test_une_piste_cv_reste_monophonique(self):
        projet = atelier.new_project(atelier.Style(genre="techno", seed=4))
        piste = atelier.add_track(projet, "cv", "Basse")
        clip = piste.clips[0]
        clip.events[:] = [accomp.NoteEvent(2.0, 4.0, 40, 90),
                          accomp.NoteEvent(8.0, 1.0, 43, 90)]
        atelier.toggle_note(projet, piste.uid, clip.key, 48, 3)
        self.assertEqual(sorted((e.start, e.note) for e in clip.events),
                         [(3.0, 48), (8.0, 43)])

    def test_un_clip_du_deluge_ne_se_dessine_pas(self):
        projet = atelier.new_project(atelier.Style(genre="techno", seed=4))
        piste, clip = self._basse(projet)
        clip.existing = 0
        with self.assertRaises(ValueError):
            atelier.toggle_note(projet, piste.uid, clip.key, 45, 0)

    def test_le_brouillon_rend_le_projet_entier(self):
        projet = atelier.new_project(atelier.Style(genre="house", seed=5),
                                     sd=self.sd, lib=self.lib)
        projet.written["SONGS/X.XML"] = "ab" * 32
        repris, meta = atelier.load_draft(
            atelier.dump_draft(projet, {"step": "Clips"}))
        self.assertEqual(meta, {"step": "Clips"})
        self.assertEqual(repris.written, projet.written)
        self.assertEqual([t.part for t in repris.tracks],
                         [t.part for t in projet.tracks])
        batterie = next(t for t in repris.tracks if t.is_drums)
        self.assertEqual([r.file_name for r in batterie.kit.rows],
                         [r.file_name for r in next(
                             t for t in projet.tracks if t.is_drums).kit.rows])
        self.assertEqual(
            atelier.to_song_spec(repris, "A", sd=self.sd, lib=self.lib).bpm,
            atelier.to_song_spec(projet, "A", sd=self.sd, lib=self.lib).bpm)

    def test_un_brouillon_d_avant_un_champ_neuf_se_relit(self):
        """``pickle`` ne passe pas par le constructeur : un champ ajouté au
        code depuis restait absent, et la première lecture levait."""
        projet = atelier.new_project(atelier.Style(genre="house", seed=5))
        del projet.__dict__["written"]
        del projet.sections[0].__dict__["cells"]
        repris, _meta = atelier.load_draft(atelier.dump_draft(projet))
        self.assertEqual(repris.written, {})
        self.assertEqual(repris.sections[0].cells, {})

    def test_un_brouillon_abime_est_refuse(self):
        for octets in (b"", b"pas un brouillon",
                       __import__("pickle").dumps({"format": 99})):
            with self.subTest(octets=octets[:12]):
                with self.assertRaises(ValueError):
                    atelier.load_draft(octets)

    def test_seul_un_morceau_inchange_se_remplace(self):
        projet = atelier.new_project(atelier.Style(genre="house", seed=5),
                                     sd=self.sd, lib=self.lib)
        spec = atelier.to_song_spec(projet, "REMPLACE", sd=self.sd,
                                    lib=self.lib)
        premier = songwriter.write_song(self.sd, spec, apply=True)
        self.assertTrue(premier.applied)
        cible = self.sd.abs(premier.rel)
        empreinte = songwriter.file_sha256(cible)
        ancien = cible.read_bytes()

        # Une empreinte fausse : rien n'est remplacé, rien n'est écrit.
        refus = songwriter.write_song(self.sd, spec, apply=True,
                                      replace=premier.rel,
                                      expected_sha="0" * 64)
        self.assertFalse(refus.applied)
        self.assertEqual(cible.read_bytes(), ancien)

        projet.style.bpm = 131
        spec = atelier.to_song_spec(projet, "REMPLACE", sd=self.sd,
                                    lib=self.lib)
        plan = songwriter.write_song(self.sd, spec, replace=premier.rel,
                                     expected_sha=empreinte)
        self.assertTrue(plan.ok)
        self.assertIn("_BACKUP", plan.text())
        fait = songwriter.write_song(self.sd, spec, apply=True,
                                     replace=premier.rel,
                                     expected_sha=empreinte)
        self.assertTrue(fait.applied, fait.error)
        self.assertEqual(fait.rel, premier.rel)
        self.assertNotEqual(cible.read_bytes(), ancien)
        self.assertEqual(self.sd.abs(fait.kept).read_bytes(), ancien)
        self.assertEqual(sorted(p.name for p in (self.root / "SONGS")
                                .iterdir()), ["REMPLACE.XML"])


# --------------------------------------------------------------------------- #
# Les clips qu'on reprend à la main, l'écoute en contexte, le volume
# --------------------------------------------------------------------------- #

class TestLesClipsALaMain(unittest.TestCase):
    """Clip vide, copie, longueur doublée, octave, force d'un coup."""

    def setUp(self):
        self.projet = atelier.new_project(atelier.Style(genre="house",
                                                        seed=6))
        par_part = {t.part: t for t in self.projet.tracks}
        self.batterie, self.basse = par_part["Batterie"], par_part["Basse"]

    def test_un_clip_vide_se_dessine(self):
        for piste in (self.batterie, self.basse):
            with self.subTest(piste=piste.part):
                clip = atelier.empty_clip(self.projet, piste.uid, bars=2)
                self.assertEqual((clip.bars, clip.note_count, clip.origin),
                                 (2, 0, "vide"))
                self.assertIs(piste.clips[-1], clip)
        clip = self.batterie.clips[-1]
        self.assertEqual(clip.pattern.steps, 32)
        self.assertTrue(atelier.toggle_hit(self.projet, self.batterie.uid,
                                           clip.key, "Kick", 0))
        clip = self.basse.clips[-1]
        self.assertTrue(atelier.toggle_note(self.projet, self.basse.uid,
                                            clip.key, 45, 0, length=6))
        self.assertEqual([(e.start, e.length) for e in clip.events],
                         [(0.0, 6.0)])

    def test_la_copie_ne_touche_pas_a_l_original(self):
        for piste in (self.batterie, self.basse):
            with self.subTest(piste=piste.part):
                source = piste.clips[0]
                avant = source.note_count
                copie = atelier.duplicate_clip(self.projet, piste.uid,
                                               source.key)
                self.assertEqual((copie.parent, copie.origin, copie.bars),
                                 (source.key, "copie", source.bars))
                self.assertEqual(copie.note_count, avant)
                self.assertNotEqual(copie.key, source.key)
        copie = self.basse.clips[-1]
        copie.events.clear()
        self.assertTrue(self.basse.clips[0].events)
        copie = self.batterie.clips[-1]
        copie.pattern.tracks.clear()
        self.assertTrue(self.batterie.clips[0].pattern.tracks)

    def test_la_copie_d_un_clip_du_deluge_se_dessine(self):
        source = self.basse.clips[0]
        source.existing = 3
        copie = atelier.duplicate_clip(self.projet, self.basse.uid,
                                       source.key)
        self.assertIsNone(copie.existing)
        libre = next(n for n in range(30, 90)
                     if n not in {e.note for e in copie.events})
        self.assertTrue(atelier.toggle_note(self.projet, self.basse.uid,
                                            copie.key, libre, 0))

    def test_doubler_repete_le_contenu(self):
        clip = self.basse.clips[0]
        notes = [(e.start, e.note) for e in clip.events]
        pas = clip.steps
        atelier.double_clip(self.projet, self.basse.uid, clip.key)
        self.assertEqual(clip.bars, 8)
        self.assertEqual(sorted((e.start, e.note) for e in clip.events),
                         sorted(notes + [(s + pas, n) for s, n in notes]))
        clip = self.batterie.clips[0]
        coups = {nom: sorted(float(s.pos) for s in liste)
                 for nom, liste in clip.pattern.tracks.items()}
        pas = clip.steps
        atelier.double_clip(self.projet, self.batterie.uid, clip.key)
        self.assertEqual(clip.pattern.steps, 2 * pas)
        for nom, positions in coups.items():
            self.assertEqual(
                sorted(float(s.pos) for s in clip.pattern.tracks[nom]),
                sorted(positions + [p + pas for p in positions]), nom)
        # Le second passage reste éditable case par case.
        self.assertTrue(clip.pattern.tracks.get("Kick"))
        case = max(rhythm.cell(s)
                   for s in clip.pattern.tracks["Kick"])
        self.assertFalse(atelier.toggle_hit(self.projet, self.batterie.uid,
                                            clip.key, "Kick", case))

    def test_doubler_s_arrete_a_seize_mesures(self):
        clip = self.basse.clips[0]
        atelier.double_clip(self.projet, self.basse.uid, clip.key)
        atelier.double_clip(self.projet, self.basse.uid, clip.key)
        self.assertEqual(clip.bars, atelier.MAX_BARS)
        avant = len(clip.events)
        with self.assertRaises(ValueError):
            atelier.double_clip(self.projet, self.basse.uid, clip.key)
        self.assertEqual((clip.bars, len(clip.events)),
                         (atelier.MAX_BARS, avant))

    def test_une_octave_plus_bas_puis_plus_haut(self):
        clip = self.basse.clips[0]
        notes = [e.note for e in clip.events]
        self.assertEqual(atelier.transpose_clip(self.projet, self.basse.uid,
                                                clip.key, -12), len(notes))
        self.assertEqual([e.note for e in clip.events],
                         [n - 12 for n in notes])
        atelier.transpose_clip(self.projet, self.basse.uid, clip.key, 12)
        self.assertEqual([e.note for e in clip.events], notes)

    def test_une_octave_de_trop_ne_change_rien(self):
        clip = self.basse.clips[0]
        clip.events[0].note = 5
        notes = [e.note for e in clip.events]
        with self.assertRaises(ValueError):
            atelier.transpose_clip(self.projet, self.basse.uid, clip.key, -12)
        self.assertEqual([e.note for e in clip.events], notes)
        with self.assertRaises(ValueError):
            atelier.transpose_clip(self.projet, self.batterie.uid,
                                   self.batterie.clips[0].key, 12)

    def test_un_clip_du_deluge_ne_se_retouche_pas(self):
        clip = self.basse.clips[0]
        clip.existing = 0
        for geste in (lambda: atelier.double_clip(self.projet,
                                                  self.basse.uid, clip.key),
                      lambda: atelier.transpose_clip(self.projet,
                                                     self.basse.uid,
                                                     clip.key, 12),
                      lambda: atelier.accent_note(self.projet, self.basse.uid,
                                                  clip.key, 40, 0)):
            with self.assertRaises(ValueError):
                geste()

    def test_la_force_d_un_coup_tourne(self):
        clip = atelier.empty_clip(self.projet, self.batterie.uid, bars=1)
        uid = self.batterie.uid
        self.assertIsNone(atelier.accent_hit(self.projet, uid, clip.key,
                                             "Kick", 4))
        atelier.toggle_hit(self.projet, uid, clip.key, "Kick", 4)
        vues = [atelier.accent_hit(self.projet, uid, clip.key, "Kick", 4)
                for _ in range(4)]
        self.assertEqual(vues, [70, 40, 100, 70])
        self.assertEqual(clip.pattern.tracks["Kick"][0].velocity, 70)

    def test_la_force_d_une_note_tourne(self):
        clip = atelier.empty_clip(self.projet, self.basse.uid, bars=1)
        uid = self.basse.uid
        atelier.toggle_note(self.projet, uid, clip.key, 45, 2, length=4)
        self.assertIsNone(atelier.accent_note(self.projet, uid, clip.key,
                                              45, 9))
        # Où qu'on touche la note, c'est elle qui change : 90, puis 70.
        self.assertEqual(atelier.accent_note(self.projet, uid, clip.key,
                                             45, 5), 70)
        self.assertEqual(atelier.accent_note(self.projet, uid, clip.key,
                                             45, 2), 40)
        self.assertEqual(atelier.accent_note(self.projet, uid, clip.key,
                                             45, 2), 100)


class TestLaStructureEtLEcoute(unittest.TestCase):
    """Dupliquer une section, écouter un clip avec le morceau, faire taire
    une piste."""

    def setUp(self):
        self.projet = atelier.new_project(atelier.Style(genre="house",
                                                        seed=6))
        self.par_part = {t.part: t for t in self.projet.tracks}

    def test_la_copie_d_une_section_la_suit(self):
        projet = self.projet
        noms = [s.name for s in projet.sections]
        rang = next(i for i, s in enumerate(projet.sections)
                    if s.kind == "pic")
        source = projet.sections[rang]
        place = atelier.duplicate_section(projet, rang)
        self.assertEqual(place, rang + 1)
        copie = projet.sections[place]
        self.assertEqual((copie.bars, copie.cells, copie.kind),
                         (source.bars, source.cells, source.kind))
        self.assertIsNot(copie.cells, source.cells)
        self.assertIsNone(copie.existing)
        self.assertNotIn(copie.name, noms)
        self.assertEqual(len(projet.sections), len(noms) + 1)
        with self.assertRaises(ValueError):
            atelier.duplicate_section(projet, 99)

    def test_le_nom_d_une_copie_prend_le_numero_libre(self):
        projet = self.projet
        projet.sections[0].name = "Refrain"
        projet.sections[1].name = "Refrain 2"
        place = atelier.duplicate_section(projet, 1)
        self.assertEqual(projet.sections[place].name, "Refrain 3")

    def test_une_piste_muette_se_tait(self):
        projet = self.projet
        plein = atelier.fullest_section(projet)
        parties, batterie, mesures = atelier.section_parts(projet, plein)
        self.assertIsNotNone(batterie)
        self.assertGreaterEqual(len(parties), 2)
        basse = self.par_part["Basse"]
        seules = {basse.uid}
        parties, batterie, _m = atelier.section_parts(projet, plein,
                                                      only=seules)
        self.assertIsNone(batterie)
        self.assertEqual(list(parties), [atelier._part_key(basse)])
        parties, batterie, _m = atelier.section_parts(projet, plein,
                                                      only=set())
        self.assertEqual((parties, batterie), ({}, None))

    def test_un_clip_s_ecoute_avec_le_morceau(self):
        projet = self.projet
        basse, batterie = self.par_part["Basse"], self.par_part["Batterie"]
        neuf = atelier.vary_clip(projet, basse.uid, basse.clips[0].key,
                                 "notes")
        # Placé nulle part : il prend la section qu'on regarde.
        cible = atelier.fullest_section(projet)
        parties, motif, mesures, section = atelier.context_parts(
            projet, basse.uid, neuf.key, section=cible)
        self.assertEqual(section, cible)
        self.assertIsNotNone(motif)
        cle = atelier._part_key(basse)
        self.assertEqual(sorted((e.start, e.note) for e in parties[cle]
                                if e.start < neuf.steps),
                         sorted((e.start, e.note) for e in neuf.events))
        self.assertGreater(len(parties), 1)
        self.assertGreaterEqual(mesures, neuf.bars)
        # Placé dans une section, c'est celle-là qu'on entend.
        atelier.set_cell(projet, 0, basse.uid, neuf.key)
        _p, _m, _b, section = atelier.context_parts(projet, basse.uid,
                                                    neuf.key, section=cible)
        self.assertEqual(section, 0)
        # Sa piste muette, il sonne quand même ; les autres se taisent.
        parties, motif, _b, _s = atelier.context_parts(
            projet, basse.uid, neuf.key, only={batterie.uid})
        self.assertEqual(list(parties), [cle])

    def test_le_plus_long_clip_donne_la_duree(self):
        projet = self.projet
        basse, accords = self.par_part["Basse"], self.par_part["Accords"]
        court = atelier.empty_clip(projet, basse.uid, bars=1)
        atelier.toggle_note(projet, basse.uid, court.key, 40, 0)
        section = next(i for i, s in enumerate(projet.sections)
                       if s.cells.get(accords.uid))
        _p, _m, mesures, _s = atelier.context_parts(projet, basse.uid,
                                                    court.key,
                                                    section=section)
        self.assertEqual(mesures, 4)
        _p, _m, mesures, _s = atelier.context_parts(
            projet, basse.uid, court.key, section=section, only=set())
        self.assertEqual(mesures, 1)

    def test_sans_section_le_clip_joue_seul(self):
        projet = atelier.new_project(atelier.Style(genre="house", seed=6),
                                     structure=False)
        basse = next(t for t in projet.tracks if t.part == "Basse")
        parties, motif, mesures, section = atelier.context_parts(
            projet, basse.uid, basse.clips[0].key)
        self.assertEqual((list(parties), motif, section),
                         ([atelier._part_key(basse)], None, -1))
        self.assertEqual(mesures, basse.clips[0].bars)

    def test_un_rendu_replie_tourne_en_mesure(self):
        from delugeapp.core import render

        audio = np.zeros((1000, 2), dtype=np.float32)
        audio[0] = 0.5                 # le premier temps
        audio[450] = 0.25              # la queue, après la dernière mesure
        boucle = render.loop_fold(audio, 400 / 44100.0, 44100)
        self.assertEqual(boucle.shape, (400, 2))
        self.assertAlmostEqual(float(boucle[0, 0]), 0.5)
        self.assertAlmostEqual(float(boucle[50, 0]), 0.25)
        # Plus court que la boucle : complété de silence.
        boucle = render.loop_fold(audio[:100], 400 / 44100.0, 44100)
        self.assertEqual(boucle.shape, (400, 2))
        self.assertEqual(float(np.abs(boucle[100:]).max()), 0.0)


class TestLeVolumeDUnePiste(CarteCase):
    """Le volume réglé s'entend, s'écrit, et suit la piste quand elle change
    de son."""

    def setUp(self):
        super().setUp()
        self.projet = atelier.new_project(atelier.Style(genre="house",
                                                        seed=6),
                                          sd=self.sd, lib=self.lib,
                                          kinds={"Mélodie": "midi"})
        self.par_part = {t.part: t for t in self.projet.tracks}

    def test_le_cran_du_kit_d_un_morceau_neuf(self):
        from delugeapp.core import render

        self.assertEqual(atelier.KIT_VOLUME, render.SONG_VOLUME)
        self.assertEqual(atelier.track_volume(self.par_part["Batterie"]), 35)

    def test_une_piste_midi_n_a_pas_de_volume(self):
        midi = self.par_part["Mélodie"]
        self.assertIsNone(atelier.track_volume(midi))
        self.assertFalse(atelier.set_track_volume(self.projet, midi.uid, 30))
        self.assertEqual(atelier.describe_volume(midi), "")

    def test_le_volume_s_entend(self):
        from delugeapp.core import render

        basse, batterie = self.par_part["Basse"], self.par_part["Batterie"]
        self.assertTrue(atelier.set_track_volume(self.projet, basse.uid, 50))
        fort = render.render_sound(basse.preset.sound, 36, 0.4, 22050)
        atelier.set_track_volume(self.projet, basse.uid, 25)
        doux = render.render_sound(basse.preset.sound, 36, 0.4, 22050)
        rapport = float(np.abs(fort).max()) / float(np.abs(doux).max())
        self.assertAlmostEqual(rapport, 4.0, delta=0.3)   # 12 dB
        self.assertEqual(atelier.describe_volume(basse), "-12,0 dB")
        avant = render.kit_gain(batterie.kit)
        atelier.set_track_volume(self.projet, batterie.uid, 25)
        self.assertAlmostEqual(avant / render.kit_gain(batterie.kit),
                               (1.0 + 0.4) ** 2, delta=0.05)

    def test_le_volume_suit_la_piste_qui_change_de_son(self):
        from delugeapp.core import soundedit

        basse, batterie = self.par_part["Basse"], self.par_part["Batterie"]
        atelier.set_track_volume(self.projet, basse.uid, 22)
        atelier.regenerate_sound(self.projet, basse.uid, seed=99)
        self.assertEqual(atelier.track_volume(basse), 22)
        variantes = atelier.sound_variations(self.projet, basse.uid, 4,
                                             seed=1)
        self.assertEqual({soundedit.value(v.preset.sound, "volume")
                          for v in variantes}, {22})
        atelier.adopt_sound(self.projet, basse.uid, variantes[0])
        self.assertEqual(atelier.track_volume(basse), 22)
        preset = synthgen.generate(synthgen.GenOptions(genre="techno",
                                                       role="bass", seed=3))
        atelier.use_preset(self.projet, preset, "Basse", uid=basse.uid)
        self.assertEqual(atelier.track_volume(basse), 22)
        atelier.set_track_volume(self.projet, batterie.uid, 41)
        atelier.use_kit(self.projet, atelier._build_kit(
            self.sd, self.lib, self.projet.style, 5))
        self.assertEqual(atelier.track_volume(batterie), 41)

    def test_sans_reglage_le_son_garde_le_sien(self):
        basse = self.par_part["Basse"]
        self.assertIsNone(basse.level)
        vus = set()
        for graine in range(6):
            atelier.regenerate_sound(self.projet, basse.uid, seed=graine)
            vus.add(atelier.track_volume(basse))
        self.assertTrue(all(0 < v <= 50 for v in vus), vus)

    def test_le_volume_regle_dans_l_editeur_devient_celui_de_la_piste(self):
        from delugeapp.core import soundedit

        basse = self.par_part["Basse"]
        atelier.set_track_volume(self.projet, basse.uid, 30)
        son = soundedit.copy_sound(basse.preset.sound)
        soundedit.set_value(son, "volume", 44)
        atelier.edit_sound(self.projet, basse.uid, son)
        self.assertEqual((basse.level, atelier.track_volume(basse)),
                         (44, 44))

    def test_une_piste_du_morceau_d_origine_garde_son_volume(self):
        basse = self.par_part["Basse"]
        basse.existing = {"kind": "sound"}
        avant = atelier.track_volume(basse)
        self.assertFalse(atelier.set_track_volume(self.projet, basse.uid, 5))
        self.assertEqual(atelier.track_volume(basse), avant)

    def test_le_volume_s_ecrit_avec_le_morceau(self):
        from delugeapp.core.fixedpoint import parse_fixed, to_display

        basse, batterie = self.par_part["Basse"], self.par_part["Batterie"]
        atelier.set_track_volume(self.projet, basse.uid, 21)
        atelier.set_track_volume(self.projet, batterie.uid, 44)
        spec = atelier.to_song_spec(self.projet, "VOLUME", sd=self.sd,
                                    lib=self.lib)
        res = songwriter.write_song(self.sd, spec, apply=True)
        self.assertTrue(res.applied, res.error)
        racine = dxml.load(self.sd.abs(res.rel)).root

        # Dans un morceau, les réglages d'un instrument vivent dans chacun
        # de ses clips : ``kitParams`` pour un kit, ``soundParams`` pour un
        # synthé.
        def crans(nom, balise):
            return {to_display(parse_fixed(clip.find(balise).get("volume")))
                    for clip in racine.iter("instrumentClip")
                    if clip.get("instrumentPresetName") == nom}

        self.assertEqual(crans(batterie.kit.name, "kitParams"), {44})
        self.assertEqual(crans(basse.preset.name, "soundParams"), {21})
        accords = self.par_part["Accords"]
        self.assertEqual(crans(accords.preset.name, "soundParams"),
                         {atelier.track_volume(accords)})


class TestLeLecteurEchangeEnPlace(unittest.TestCase):
    """``Player.replace_array`` : une boucle qui tourne reçoit un nouveau
    rendu sans perdre sa place. L'état d'une lecture est posé à la main :
    aucun flux audio réel n'est ouvert."""

    def setUp(self):
        from delugeapp.core import audio_out

        self.lecteur = audio_out.Player()
        self._backend = self.lecteur._backend
        self.addCleanup(self._rendre)

    def _rendre(self):
        with self.lecteur._state_lock:
            self.lecteur._playing = False
            self.lecteur._loop = False
            self.lecteur._data = None
        self.lecteur._backend = self._backend

    def _boucle(self, trames, position=0):
        self.lecteur._backend = "sounddevice"
        with self.lecteur._state_lock:
            self.lecteur._data = trames
            self.lecteur._sr = 44100
            self.lecteur._pos = position
            self.lecteur._loop = True
            self.lecteur._playing = True
            self.lecteur._volume = 1.0

    def test_rien_ne_joue_rien_ne_s_echange(self):
        neuf = np.zeros((100, 2), dtype=np.float32)
        self.assertFalse(self.lecteur.replace_array(neuf, 44100))

    def test_la_boucle_reprend_au_meme_echantillon(self):
        ancien = np.full((100, 2), 0.25, dtype=np.float32)
        neuf = np.full((100, 2), 0.5, dtype=np.float32)
        self._boucle(ancien, position=40)
        self.assertTrue(self.lecteur.replace_array(neuf, 44100))
        sortie = np.zeros((30, 2), dtype=np.float32)
        self.lecteur._callback(sortie, 30, None, None)
        self.assertTrue(np.allclose(sortie, 0.5), "l'ancien son joue encore")
        self.assertEqual(self.lecteur._pos, 70)
        self.assertTrue(self.lecteur._playing)
        # Et la boucle tourne : la fin enchaîne sur le début du neuf.
        sortie = np.zeros((60, 2), dtype=np.float32)
        self.lecteur._callback(sortie, 60, None, None)
        self.assertEqual(self.lecteur._pos, 30)
        self.assertTrue(np.allclose(sortie, 0.5))

    def test_un_son_mono_prend_les_canaux_de_la_boucle(self):
        self._boucle(np.zeros((100, 2), dtype=np.float32))
        self.assertTrue(self.lecteur.replace_array(
            np.full(100, 0.1, dtype=np.float32), 44100))
        self.assertEqual(self.lecteur._data.shape, (100, 2))

    def test_une_autre_duree_n_est_pas_echangee(self):
        ancien = np.full((100, 2), 0.25, dtype=np.float32)
        self._boucle(ancien)
        for neuf, frequence in ((np.zeros((90, 2), np.float32), 44100),
                                (np.zeros((100, 2), np.float32), 48000)):
            self.assertFalse(self.lecteur.replace_array(neuf, frequence))
        self.assertIs(self.lecteur._data, ancien)

    def test_une_lecture_unique_n_est_pas_echangee(self):
        ancien = np.full((100, 2), 0.25, dtype=np.float32)
        self._boucle(ancien)
        self.lecteur._loop = False
        self.assertFalse(self.lecteur.replace_array(
            np.zeros((100, 2), np.float32), 44100))
        self.assertIs(self.lecteur._data, ancien)

    def test_sans_sortie_seule_la_duree_compte(self):
        self.lecteur._backend = "none"
        with self.lecteur._state_lock:
            self.lecteur._loop = True
            self.lecteur._playing = True
            self.lecteur._duration = 100 / 44100.0
        self.assertTrue(self.lecteur.replace_array(
            np.zeros((100, 2), np.float32), 44100))
        self.assertFalse(self.lecteur.replace_array(
            np.zeros((300, 2), np.float32), 44100))


class TestLeLecteurEnFlux(unittest.TestCase):
    """``Player.play_stream`` : le début d'un morceau joue pendant que la
    suite se calcule ; arrivée au bout, la lecture attend en silence."""

    setUp = TestLeLecteurEchangeEnPlace.setUp
    _boucle = TestLeLecteurEchangeEnPlace._boucle

    def _flux(self, trames, position=0):
        self._boucle(trames, position)
        with self.lecteur._state_lock:
            self.lecteur._loop = False
            self.lecteur._streaming = True

    def _rendre(self):
        with self.lecteur._state_lock:
            self.lecteur._streaming = False
        TestLeLecteurEchangeEnPlace._rendre(self)

    def test_le_flux_attend_la_suite_en_silence(self):
        from delugeapp.core import audio_out

        self._flux(np.full((50, 2), 0.25, dtype=np.float32), position=40)
        sortie = np.ones((30, 2), dtype=np.float32)
        self.lecteur._callback(sortie, 30, None, None)
        self.assertTrue(np.allclose(sortie[:10], 0.25))
        self.assertTrue(np.allclose(sortie[10:], 0.0))
        self.assertTrue(self.lecteur._playing, "le flux s'est arrêté")
        self.assertTrue(self.lecteur.extend_stream(
            np.full((40, 2), 0.5, dtype=np.float32)))
        self.assertEqual(self.lecteur._data.shape, (90, 2))
        sortie = np.zeros((30, 2), dtype=np.float32)
        self.lecteur._callback(sortie, 30, None, None)
        self.assertTrue(np.allclose(sortie, 0.5), "la suite n'a pas joué")
        self.lecteur.end_stream()
        if audio_out._sd is None:
            return
        with self.assertRaises(audio_out._sd.CallbackStop):
            self.lecteur._callback(np.zeros((30, 2), np.float32), 30,
                                   None, None)
        self.assertFalse(self.lecteur._playing)

    def test_sans_flux_rien_ne_s_allonge(self):
        ancien = np.zeros((100, 2), dtype=np.float32)
        self.assertFalse(self.lecteur.extend_stream(ancien))
        self._boucle(ancien)
        self.assertFalse(self.lecteur.extend_stream(ancien))
        self.assertIs(self.lecteur._data, ancien)

    def test_une_lecture_ordinaire_coupe_le_flux(self):
        self.lecteur._backend = "none"
        self.assertTrue(self.lecteur.play_stream(
            np.zeros((441, 2), np.float32), 44100))
        self.lecteur.play_array(np.zeros((441, 2), np.float32), 44100)
        self.assertFalse(self.lecteur.extend_stream(
            np.zeros((441, 2), np.float32)))

    def test_sans_sortie_le_flux_dure_jusqu_a_sa_fin(self):
        self.lecteur._backend = "none"
        self.assertTrue(self.lecteur.play_stream(
            np.zeros((441, 2), np.float32), 44100))
        with self.lecteur._state_lock:
            self.lecteur._start_time -= 1.0         # une seconde a passé
        self.assertTrue(self.lecteur.is_playing, "fini avant la suite")
        self.assertTrue(self.lecteur.extend_stream(
            np.zeros((22050, 2), np.float32)))
        self.assertAlmostEqual(self.lecteur._duration, 0.51, places=6)
        self.lecteur.end_stream()
        self.assertFalse(self.lecteur.is_playing)

    def test_winsound_ne_sait_pas(self):
        joues = []
        self.lecteur._play_winsound_array = lambda *a: joues.append(a)
        self.lecteur._backend = "winsound"
        self.assertFalse(self.lecteur.play_stream(
            np.zeros((441, 2), np.float32), 44100))
        self.assertEqual(joues, [], "un début joué pour rien")
        self.assertFalse(self.lecteur._playing)

    def test_portaudio_refuse_le_flux_s_arrete(self):
        """PortAudio refuse d'ouvrir : la lecture bascule sur winsound, qui
        ne s'allonge pas — le flux est abandonné, l'appelant attendra."""
        def bascule(arr, sr, loop):
            self.lecteur._backend = "winsound"
            with self.lecteur._state_lock:
                self.lecteur._playing = True

        self.lecteur._backend = "sounddevice"
        self.lecteur._play_sounddevice = bascule
        self.assertFalse(self.lecteur.play_stream(
            np.zeros((441, 2), np.float32), 44100))
        self.assertFalse(self.lecteur._playing)
        self.assertFalse(self.lecteur._streaming)


class TestLesBrouillonsDeLAtelier(unittest.TestCase):
    """Les morceaux rangés sur l'ordinateur : chacun se rouvre tel quel."""

    def setUp(self):
        from delugeapp.core import atelierstore

        self.store = atelierstore
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name) / "atelier" / "brouillons"

    def tearDown(self):
        self._tmp.cleanup()

    def _projet(self, genre="house", graine=5):
        return atelier.new_project(atelier.Style(genre=genre, seed=graine))

    def test_ranger_puis_rouvrir(self):
        projet = self._projet()
        basse = next(t for t in projet.tracks if t.part == "Basse")
        atelier.set_track_volume(projet, basse.uid, 19)
        projet.edits = 3
        fiche = self.store.shelve(self.base, projet,
                                  {"name": "MON MORCEAU", "genre": "house"})
        self.assertEqual((fiche.ident, fiche.name, fiche.worked),
                         (projet.ident, "MON MORCEAU", True))
        liste = self.store.entries(self.base)
        self.assertEqual([(e.ident, e.name) for e in liste],
                         [(projet.ident, "MON MORCEAU")])
        self.assertEqual(liste[0].meta["genre"], "house")
        repris, meta = self.store.load(self.base, projet.ident)
        self.assertEqual(meta["name"], "MON MORCEAU")
        self.assertEqual(repris.ident, projet.ident)
        self.assertEqual(repris.edits, 3)
        reprise = next(t for t in repris.tracks if t.part == "Basse")
        self.assertEqual(atelier.track_volume(reprise), 19)
        self.assertEqual([c.key for c in reprise.clips],
                         [c.key for c in basse.clips])

    def test_le_meme_morceau_ne_fait_qu_un_brouillon(self):
        projet = self._projet()
        self.store.shelve(self.base, projet, {"name": "UN"})
        self.store.shelve(self.base, projet, {"name": "UN, RETOUCHÉ"})
        autre = self._projet(graine=6)
        self.store.shelve(self.base, autre, {"name": "DEUX"})
        self.assertEqual(sorted(e.name for e in self.store.entries(self.base)),
                         ["DEUX", "UN, RETOUCHÉ"])

    def test_le_plus_recent_d_abord(self):
        from unittest import mock

        for rang, nom in enumerate(("A", "B", "C")):
            with mock.patch.object(self.store.time, "time",
                                   return_value=1000.0 + rang):
                self.store.shelve(self.base, self._projet(graine=rang),
                                  {"name": nom})
        self.assertEqual([e.name for e in self.store.entries(self.base)],
                         ["C", "B", "A"])

    def test_supprimer(self):
        projet = self._projet()
        self.store.shelve(self.base, projet, {"name": "UN"})
        self.assertTrue(self.store.remove(self.base, projet.ident))
        self.assertEqual(self.store.entries(self.base), [])
        self.assertEqual(list(self.base.iterdir()), [])
        self.assertFalse(self.store.remove(self.base, projet.ident))
        with self.assertRaises(OSError):
            self.store.load(self.base, projet.ident)

    def test_les_morceaux_travailles_restent_les_derniers(self):
        from unittest import mock

        gardes = []
        for rang in range(6):
            projet = self._projet(graine=rang)
            # Les deux plus anciens ont été retouchés, ou écrits.
            if rang == 0:
                projet.edits = 2
            if rang == 1:
                projet.written["SONGS/X.XML"] = "0" * 64
            with mock.patch.object(self.store.time, "time",
                                   return_value=1000.0 + rang):
                self.store.shelve(self.base, projet, {"name": "M%d" % rang},
                                  keep=4)
            gardes.append(projet.ident)
        noms = sorted(e.name for e in self.store.entries(self.base))
        self.assertEqual(noms, ["M0", "M1", "M4", "M5"])

    def test_une_fiche_abimee_est_passee(self):
        projet = self._projet()
        self.store.shelve(self.base, projet, {"name": "BON"})
        (self.base / ("%s.json" % ("ab" * 16))).write_text("{", "utf-8")
        (self.base / ("%s.pickle" % ("ab" * 16))).write_bytes(b"x")
        (self.base / "orpheline.json").write_text("{}", "utf-8")
        (self.base / ("%s.json" % ("cd" * 16))).write_text("{}", "utf-8")
        self.assertEqual([e.name for e in self.store.entries(self.base)],
                         ["BON"])
        with self.assertRaises(ValueError):
            self.store.load(self.base, "ab" * 16)

    def test_un_identifiant_etranger_est_refuse(self):
        for ident in ("", "../ailleurs", "ZZZZ", "a/b"):
            with self.subTest(ident=ident):
                with self.assertRaises(ValueError):
                    self.store.load(self.base, ident)
                with self.assertRaises(ValueError):
                    self.store.remove(self.base, ident)

    def test_un_brouillon_d_avant_les_brouillons_recoit_son_identifiant(self):
        projet = self._projet()
        del projet.__dict__["ident"]
        del projet.__dict__["edits"]
        del projet.tracks[0].__dict__["level"]
        repris, _meta = atelier.load_draft(atelier.dump_draft(projet))
        self.assertRegex(repris.ident, r"^[0-9a-f]{32}$")
        self.assertEqual((repris.edits, repris.tracks[0].level), (0, None))


if __name__ == "__main__":
    unittest.main()
