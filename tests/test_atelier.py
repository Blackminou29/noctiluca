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

BAC_A_SABLE = Path(_tempfile.gettempdir()) / "deluge-companion-tests"
BAC_A_SABLE.mkdir(parents=True, exist_ok=True)
_os.environ["DELUGE_COMPANION_CONFIG"] = str(BAC_A_SABLE)

from delugeapp.core import (accomp, atelier, db, dxml, genres, midiport,  # noqa: E402
                            rhythm, scan, sdcard, songinsert, songwriter,
                            synthgen, theory, variation, wav)
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

    def test_une_ancienne_iteration_joue_toujours(self):
        """L'octet de condition ≥ 0x80 (itération d'avant 1.3) n'a pas de
        place dans le champ de probabilité : la note joue toujours plutôt
        qu'au hasard."""
        blob = encode_notes([Note(pos=0, length=24, condition=0x86)],
                            width=28)
        self.assertEqual(blob[2 + 20:2 + 22], "14")

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
        for attaque, pas in zip(attaques, range(0, 16, 4)):
            attendu = depart["t0"] + (96 + pas * 6) * periode
            # Au début de la mesure suivante, à quelques millisecondes près
            # (mesuré : 1,7 ms d'avance voulue, ±0,8 ms).
            self.assertAlmostEqual(attaque, attendu, delta=0.012)

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


if __name__ == "__main__":
    unittest.main()
