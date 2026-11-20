# -*- coding: utf-8 -*-
"""Tests du pont vers les DAW : MIDI, DAWproject, Reaper, Live, pistes
audio et écoute d'un morceau entier.

Sans carte réelle ni Qt : chaque test fabrique sa carte jetable. Découpés
de ``test_core.py`` le 20 novembre 2026.

    python -m unittest tests.test_daw -v
"""

from __future__ import annotations

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

from delugeapp.core import db, kitgen, scan, sdcard, wav
from delugeapp.core.model import Note, Song, SynthPreset


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

    def test_un_clip_s_ecoute_dans_la_gamme_du_morceau(self):
        """Les accords de l'arpégiateur (:mod:`.arpeggio`) prennent la gamme
        du morceau, comme sur la machine (``currentSong->key``)."""
        from unittest import mock

        from delugeapp.core import daw, render

        song = daw.from_deluge(self._morceau())
        song.root, song.mode_notes = 9, (0, 2, 3, 5, 7, 8, 10)
        vu = []
        vrai = render.render_parts

        def espion(*args, **kwargs):
            vu.append(kwargs.get("song_key"))
            return vrai(*args, **kwargs)

        with mock.patch.object(render, "render_parts", espion):
            daw.render_clip(song, *song.clip_order[1], self.sd)
        self.assertEqual(vu, [(9, (0, 2, 3, 5, 7, 8, 10))])

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
        # Le mélange passe une fois par la saturation du compresseur maître,
        # chaque piste y passe seule : 0,003 de pleine échelle d'écart
        # (−50 dB), mesuré le 14 novembre 2026.
        self.assertLess(float(np.max(np.abs(attendu[:n] - mix[:n]))), 5e-3)
        self.assertLessEqual(float(np.max(np.abs(mix))), 0.999 + 1e-6)
        self.assertIsNone(daw.render_mix(song, self.sd,
                                         should_stop=lambda: True))

    def test_le_rendu_progressif_coupe_entre_deux_blocs(self):
        """Un rendu partiel qui s'arrête avant sa fenêtre (un passage
        silencieux) : la tranche livrée finit sur un bloc entier de 128 —
        le compresseur maître calcule un bloc tronqué autrement."""
        from unittest import mock

        from delugeapp.core import daw

        song = daw.from_deluge(self._morceau())

        def court(_song, _sd, should_stop=None, until=None, contained=True):
            n = 9000 if until is None else int(until * 1000) + 77
            return np.zeros((n, 2), dtype=np.float32)

        recus = []
        with mock.patch.object(daw, "render_mix", court):
            daw.render_progressively(song, self.sd, first=4.0,
                                     progress=recus.append)
        self.assertEqual(len(recus), 2)
        bornes = np.cumsum([r.audio.shape[0] for r in recus])
        self.assertEqual([int(b) % 128 for b in bornes], [0, 0])

    def test_le_compresseur_maitre_du_morceau_est_lu_et_entendu(self):
        """L'``audioCompressor`` du morceau — pas ceux de ses sons — et son
        volume règlent la sortie de l'écoute du morceau entier."""
        import xml.etree.ElementTree as ET

        from delugeapp.core import daw

        chemin = self._morceau()
        song = daw.from_deluge(chemin)
        comp = song.compressor
        self.assertEqual((comp.threshold, comp.ratio, comp.blend),
                         (0.0, float(1 << 30), float((1 << 31) - 1)))
        self.assertEqual(comp.final_volume, float(1 << 24))
        repos = daw.render_mix(song, self.sd, contained=False)
        arbre = ET.parse(chemin)
        arbre.getroot().find("audioCompressor").set("thresh", "1610612736")
        arbre.write(chemin, encoding="utf-8", xml_declaration=True)
        regle = daw.from_deluge(chemin)
        self.assertEqual(regle.compressor.threshold, 1610612736.0)
        comprime = daw.render_mix(regle, self.sd, contained=False)
        self.assertEqual(comprime.shape, repos.shape)
        self.assertGreater(float(np.max(np.abs(comprime - repos))), 0.01)

    def test_le_debut_joue_pendant_que_la_suite_se_calcule(self):
        """Le calcul est causal : les premiers temps d'un rendu partiel
        sont ceux du rendu complet, et les morceaux livrés s'enchaînent
        sans couture."""
        from delugeapp.core import daw

        song = daw.from_deluge(self._morceau())
        self.assertTrue(8.0 < daw.song_length(song) <= 16.0)
        recus = []
        reste = daw.render_progressively(song, self.sd, first=4.0,
                                         progress=recus.append)
        # Fenêtres de 4, 8, puis le tout : deux morceaux d'avance.
        self.assertEqual(len(recus), 2)
        self.assertTrue(all(r.message for r in recus))
        self.assertEqual(recus[0].audio.shape[0],
                         round(song.seconds(4.0) * 44100))
        suite = np.concatenate([r.audio for r in recus] + [reste])
        plein = np.clip(daw.render_mix(song, self.sd, contained=False),
                        -1.0, 1.0)
        self.assertEqual(suite.shape, plein.shape)
        self.assertLess(float(np.max(np.abs(suite - plein))), 1e-6)
        self.assertGreater(float(np.max(np.abs(recus[1].audio))), 0.01)
        self.assertIsNone(daw.render_progressively(
            song, self.sd, should_stop=lambda: True))

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
