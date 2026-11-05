# -*- coding: utf-8 -*-
"""Tests de la traduction anglaise.

Le français est la langue source : chaque texte de l'application est écrit
en français dans le code, et c'est lui la clé de sa traduction
(:mod:`delugeapp.i18n`). Ces tests lisent le code **sans l'importer** —
par son arbre syntaxique, avec ``i18n_analyse.py`` — et vérifient que le
catalogue le suit : chaque texte visible traduit, aucune traduction
orpheline, des gabarits aux marques identiques, rien de traduit à l'import.

Ils n'importent pas Qt : l'interface en anglais, écran par écran, se
vérifie dans ``test_ui.py`` (``TestInterfaceEnAnglais``).
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import i18n_analyse as analyse                               # noqa: E402

from delugeapp import i18n                                   # noqa: E402
from delugeapp.i18n import en                                # noqa: E402

#: Des lettres accentuées : une traduction anglaise n'en a pas.
_ACCENTS = set("éèêëàâçùûôîïœÉÈÊÀÂÇÔÎ")


class LangueCase(unittest.TestCase):
    """Rend le français après chaque test : la suite entière le suppose."""

    def tearDown(self):
        i18n.set_language("fr")


class TestLeCatalogueSuitLeCode(unittest.TestCase):
    """Chaque module du code et son fichier de catalogue, l'un face à
    l'autre."""

    @classmethod
    def setUpClass(cls):
        cls.analyses = {chemin: analyse.analyser(chemin)
                        for chemin in analyse.sources()}

    def _rapporter(self, problemes: dict[str, list[str]], quoi: str) -> None:
        self.assertEqual(
            problemes, {},
            "%s :\n%s" % (quoi, "\n".join(
                "  %s : %s" % (m, " | ".join(p[:6]))
                for m, p in sorted(problemes.items()))))

    def test_aucun_texte_visible_n_echappe_a_la_traduction(self):
        oublis = {}
        for chemin, a in self.analyses.items():
            if a.oublis:
                oublis[analyse.nom_catalogue(chemin)] = [
                    "l.%d %r" % (ligne, texte[:60])
                    for ligne, texte in a.oublis]
        self._rapporter(oublis, "textes visibles hors de tr() et N_()")

    def test_rien_ne_se_traduit_a_l_import(self):
        """La fenêtre se reconstruit dans la nouvelle langue sans relancer
        le processus : un texte traduit à l'import resterait dans
        l'ancienne."""
        fautes = {}
        for chemin, a in self.analyses.items():
            if a.a_l_import:
                fautes[analyse.nom_catalogue(chemin)] = [
                    "l.%d %r" % (ligne, texte[:60])
                    for ligne, texte in a.a_l_import]
        self._rapporter(fautes, "tr() appelé à l'import")

    def test_chaque_cle_a_sa_traduction(self):
        manquantes = {}
        for chemin, a in self.analyses.items():
            nom = analyse.nom_catalogue(chemin)
            textes = analyse.lire_catalogue(nom) or {}
            absentes = [repr(c[:60]) for c in a.cles if c not in textes]
            if absentes:
                manquantes[nom] = absentes
        self._rapporter(manquantes, "clés sans traduction")

    def test_aucune_traduction_orpheline(self):
        """Une traduction dont le texte français a changé ne sert plus à
        rien — et la nouvelle phrase, elle, n'est pas traduite."""
        orphelines = {}
        for chemin, a in self.analyses.items():
            nom = analyse.nom_catalogue(chemin)
            textes = analyse.lire_catalogue(nom) or {}
            restes = [repr(c[:60]) for c in textes if c not in a.cles]
            if restes:
                orphelines[nom] = restes
        self._rapporter(orphelines, "traductions sans texte dans le code")

    def test_un_gabarit_garde_ses_marques(self):
        """``tr("%d fichier(s)") % n`` : la traduction doit porter le même
        ``%d``, sinon le remplissage lève ou mélange les valeurs."""
        fautes = {}
        for nom in en.MODULES:
            for cle, valeur in (analyse.lire_catalogue(nom) or {}).items():
                if analyse.marques(cle) != analyse.marques(valeur):
                    fautes.setdefault(nom, []).append(
                        "%r %s != %s" % (cle[:40], analyse.marques(cle),
                                         analyse.marques(valeur)))
        self._rapporter(fautes, "gabarits aux marques différentes")

    def test_aucune_traduction_vide_ou_accentuee(self):
        fautes = {}
        for nom in en.MODULES:
            for cle, valeur in (analyse.lire_catalogue(nom) or {}).items():
                if not valeur.strip() or _ACCENTS & set(valeur):
                    fautes.setdefault(nom, []).append(repr(valeur[:60]))
        self._rapporter(fautes, "traductions vides ou en français")

    def test_une_cle_n_a_qu_une_traduction(self):
        """Les fichiers du catalogue se fondent en un seul dictionnaire : une
        même phrase traduite deux fois différemment, l'une écraserait
        l'autre en silence."""
        vues: dict[str, tuple[str, str]] = {}
        conflits = {}
        for nom in en.MODULES:
            for cle, valeur in (analyse.lire_catalogue(nom) or {}).items():
                if cle in vues and vues[cle][1] != valeur:
                    conflits.setdefault(cle[:60], []).append(
                        "%s=%r, %s=%r" % (vues[cle][0], vues[cle][1], nom,
                                          valeur))
                vues.setdefault(cle, (nom, valeur))
        self._rapporter(conflits, "une clé, plusieurs traductions")

    def test_chaque_fichier_du_catalogue_est_charge(self):
        fichiers = {p.stem for p in analyse.CATALOGUE.glob("*.py")
                    if p.stem != "__init__"}
        self.assertEqual(fichiers, set(en.MODULES))
        avec_cles = {analyse.nom_catalogue(c)
                     for c, a in self.analyses.items() if a.cles}
        self.assertEqual(avec_cles - fichiers, set(),
                         "modules dont les textes n'ont pas de catalogue")

    def test_le_catalogue_reunit_tous_les_fichiers(self):
        cles = set()
        for nom in en.MODULES:
            cles |= set(analyse.lire_catalogue(nom) or {})
        self.assertEqual(set(en.load()), cles)

    def test_l_analyse_voit_les_oublis(self):
        """Sans cela, les tests précédents passeraient sur un analyseur
        aveugle."""
        with tempfile.TemporaryDirectory() as dossier:
            source = Path(dossier) / "essai.py"
            source.write_text(
                "from delugeapp.i18n import tr\n"
                "TITRE = tr('Réglages')\n"
                "def f(label):\n"
                "    label.setText('Écouter')\n"
                "    return tr('Carte : %s') % 'x'\n", encoding="utf-8")
            a = analyse.analyser(source)
        self.assertEqual([t for _l, t in a.oublis], ["Écouter"])
        self.assertEqual([t for _l, t in a.a_l_import], ["Réglages"])
        self.assertIn("Carte : %s", a.cles)


class TestLaLangue(LangueCase):

    def test_un_code_de_langue_inconnu_donne_le_francais(self):
        self.assertEqual(i18n.normalize("EN "), "en")
        self.assertEqual(i18n.normalize("English"), "en")
        self.assertEqual(i18n.normalize("de"), "fr")
        self.assertEqual(i18n.normalize(None), "fr")

    def test_tr_suit_la_langue_choisie(self):
        self.assertEqual(i18n.tr("Quitter"), "Quitter")
        self.assertEqual(i18n.set_language("en"), "en")
        self.assertTrue(i18n.is_english())
        self.assertEqual(i18n.tr("Quitter"), "Quit")
        # Une donnée de la carte n'a pas de traduction : elle passe.
        self.assertEqual(i18n.tr("SYNTHS/BASSE.XML"), "SYNTHS/BASSE.XML")
        self.assertEqual(i18n.tr(""), "")

    def test_sources_retrouve_le_francais_d_un_libelle(self):
        self.assertEqual(i18n.sources("Quit"), [])
        i18n.set_language("en")
        self.assertIn("Quitter", i18n.sources("Quit"))

    def test_le_pluriel_suit_la_regle_de_chaque_langue(self):
        un, plusieurs = "%d mesure", "%d mesures"
        self.assertEqual(i18n.plural(0, un, plusieurs) % 0, "0 mesure")
        self.assertEqual(i18n.plural(2, un, plusieurs) % 2, "2 mesures")
        i18n.set_language("en")
        self.assertEqual(i18n.plural(0, un, plusieurs) % 0, "0 bars")
        self.assertEqual(i18n.plural(1, un, plusieurs) % 1, "1 bar")

    def test_nombres_et_dates_dans_l_usage_de_la_langue(self):
        moment = datetime(2026, 10, 15, 14, 53)
        self.assertEqual(i18n.decimal(1.5), "1,5")
        self.assertEqual(i18n.integer(12345), "12 345")
        self.assertEqual(i18n.clock(moment), "14h53")
        self.assertEqual(i18n.day_month(moment), "15/10")
        self.assertEqual(i18n.full_date(moment), "15/10/2026")
        i18n.set_language("en")
        self.assertEqual(i18n.decimal(1.5), "1.5")
        self.assertEqual(i18n.integer(12345), "12,345")
        self.assertEqual(i18n.clock(moment), "14:53")
        self.assertEqual(i18n.day_month(moment), "15 Oct")
        self.assertEqual(i18n.full_date(moment), "15 Oct 2026")

    def test_les_unites_suivent_la_langue(self):
        from delugeapp.core import units

        self.assertEqual(units.human_size(1536 * 1024), "1,5 Mio")
        i18n.set_language("en")
        self.assertEqual(units.human_size(1536 * 1024), "1.5 MiB")

    def test_les_notes_suivent_la_langue(self):
        from delugeapp.core import theory

        self.assertEqual(theory.note_to_name(60), "Do3")
        i18n.set_language("en")
        self.assertEqual(theory.note_to_name(60), "C3")
        # Lire un nom de note marche dans les deux langues, quelle que soit
        # celle de l'interface.
        self.assertEqual(theory.name_to_note("Do3"), 60)


class TestLesTextesGardes(LangueCase):
    """Ce que l'index et l'historique gardent reste en français, et se
    traduit à l'affichage par :func:`~delugeapp.i18n.tr_stored`."""

    def test_un_texte_garde_se_traduit_a_l_affichage(self):
        self.assertEqual(i18n.tr_stored("3 erreur(s)"), "3 erreur(s)")
        i18n.set_language("en")
        self.assertEqual(i18n.tr_stored("%d erreur(s)"), "%d error(s)")
        self.assertEqual(i18n.tr_stored("3 erreur(s)"), "3 error(s)")
        self.assertEqual(i18n.tr_stored("16 rangées"), "16 rows")
        self.assertEqual(
            i18n.tr_stored("BOM UTF-8 retiré ; 2 '&' non échappé(s) "
                           "corrigé(s)"),
            "UTF-8 BOM removed; 2 unescaped '&' fixed")
        self.assertEqual(
            i18n.tr_stored("DelugeXMLError: XML illisible : ligne 3"),
            "DelugeXMLError: unreadable XML: ligne 3")

    def test_un_gabarit_trop_vague_ne_traduit_rien(self):
        """« %s à %s » reconnaîtrait n'importe quelle phrase : « lecture à
        faire » deviendrait « lecture at faire »."""
        i18n.set_language("en")
        self.assertEqual(i18n.tr_stored("lecture à faire"), "lecture à faire")
        self.assertEqual(i18n.tr_stored("inconnu"), "inconnu")

    def test_les_reparations_xml_restent_en_francais_dans_l_index(self):
        """La page Santé écarte les documents multi-racines, normaux en
        firmware 2.x, en cherchant « multi-racines » dans la note gardée :
        la note ne doit pas changer avec la langue."""
        from delugeapp.core import dxml, health

        i18n.set_language("en")
        doc = dxml.loads(b"\xef\xbb\xbf<firmwareVersion>2.1</firmwareVersion>"
                         b"<sound><name>A</name></sound>")
        self.assertIn("BOM UTF-8 retiré", doc.repaired)
        self.assertTrue(any(benin in note for note in doc.repaired
                            for benin in health.BENIGN_REPAIRS))


class TestCeQueLApplicationEcritSuitLaLangue(LangueCase):
    """Ce que l'application écrit — sur la carte, dans un fichier — se
    nomme dans la langue de l'interface au moment de l'écriture. Les clés
    du code, elles, restent en français."""

    def _deux_langues(self, fabriquer):
        francais = fabriquer()
        i18n.set_language("en")
        try:
            return francais, fabriquer()
        finally:
            i18n.set_language("fr")

    def test_les_clips_d_un_morceau(self):
        from delugeapp.core import songwriter
        from delugeapp.core.model import SynthPreset

        def noms():
            return [songwriter.preset_song(
                SynthPreset.new("S"), name="S", bpm=120, genre="techno",
                role=role).clips[0].name
                for role in ("bass", "lead", "pluck", "pad")]

        fr, en = self._deux_langues(noms)
        self.assertEqual(fr, ["Basse", "Melodie", "Arpege", "Accords"])
        self.assertEqual(en, ["Bass", "Melody", "Arpeggio", "Chords"])

    def test_les_sections_d_une_esquisse(self):
        from delugeapp.core import sketch, songwriter, theory

        progression = theory.progression(57, "mineur", "techno", bars=4,
                                         seed=1)

        def noms():
            resultat = sketch.sketch(progression, genre="techno", seed=1)
            spec = songwriter.sketch_song(resultat, name="E", bpm=124,
                                          genre="techno")
            doc = songwriter.build(spec)
            return [el.get("clipName") for el in doc.root.iter()
                    if el.get("clipName")]

        fr, en = self._deux_langues(noms)
        self.assertIn("Intro Accords", fr)
        self.assertIn("Montee Basse", fr)
        self.assertIn("Intro Chords", en)
        self.assertIn("Build-up Bass", en)
        self.assertEqual(len(fr), len(en))
        self.assertTrue(all(n.isascii() for n in fr + en))
        # Les rôles des sections tiennent toujours à leur nom français.
        self.assertEqual(sketch.section_kind("Montée"), "montée")

    def test_une_boucle_decoupee(self):
        from delugeapp.core import slicer, songwriter

        tranches = slicer.SliceSet(
            rel="SAMPLES/DRUMS/Kick/808.wav", sr=44100, frames=88200,
            slices=[slicer.Slice(i * 22050, (i + 1) * 22050)
                    for i in range(4)], bpm=120.0)
        fr, en = self._deux_langues(
            lambda: songwriter.slices_song(tranches, name="B").clips[0].name)
        self.assertEqual((fr, en), ("Boucle", "Loop"))

    def test_les_dossiers_d_un_rangement_par_duree(self):
        from delugeapp.core import organize

        def dossiers():
            return [organize._bucket_for({"duration": d}, "duration")
                    for d in (0.5, 2.0, 10.0, 60.0)]

        fr, en = self._deux_langues(dossiers)
        self.assertEqual(fr, ["Moins de 1 s", "1 a 5 s", "5 a 30 s",
                              "Plus de 30 s"])
        self.assertEqual(en, ["Under 1 s", "1 to 5 s", "5 to 30 s",
                              "Over 30 s"])

    def test_un_nom_vide(self):
        from delugeapp.core import sdcard

        fr, en = self._deux_langues(lambda: sdcard.safe_deluge_name(""))
        self.assertEqual((fr, en), ("SANS NOM", "UNTITLED"))

    def test_le_dossier_d_une_sauvegarde(self):
        """Le dossier se nomme dans la langue ; le manifeste garde le
        libellé en clé, que la page Santé traduit à l'affichage."""
        from delugeapp.core import backup, sdcard

        with tempfile.TemporaryDirectory() as dossier:
            racine = Path(dossier) / "carte"
            for sous in ("SONGS", "SYNTHS", "KITS", "SAMPLES"):
                (racine / sous).mkdir(parents=True)
            (racine / "SONGS" / "A.XML").write_text("<song/>",
                                                     encoding="utf-8")
            carte = sdcard.SDCard(racine)
            fr, en = self._deux_langues(lambda: backup.create_backup(
                carte, Path(dossier) / "sauvegardes", label="manuelle"))
            self.assertTrue(fr.path.name.endswith("_manuelle"), fr.path)
            self.assertTrue(en.path.name.endswith("_manual"), en.path)
            relus = backup.list_backups(Path(dossier) / "sauvegardes")
            self.assertEqual({b.label for b in relus}, {"manuelle"})

    def test_les_pistes_d_un_export_midi(self):
        from delugeapp.core import midifile
        from delugeapp.core.accomp import NoteEvent

        parties = {"Accords": [NoteEvent(0, 16, 60, 90)],
                   "Basse": [NoteEvent(0, 4, 36, 100)]}
        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier) / "e.mid"

            def ecrire():
                midifile.parts_to_midi(chemin, parties, 120,
                                       markers=[(0.0, "Montée")])
                return chemin.read_bytes()

            fr, en = self._deux_langues(ecrire)
        for texte in (b"Accords", b"Basse", b"Montee"):
            self.assertIn(texte, fr)
        for texte in (b"Chords", b"Bass", b"Build-up"):
            self.assertIn(texte, en)
        self.assertNotIn(b"Accords", en)


class TestLeLanceur(LangueCase):

    def test_la_langue_des_reglages_est_prise_au_demarrage(self):
        import main as lanceur
        from delugeapp import config

        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier) / "settings.json"
            chemin.write_text('{"language": "en"}', encoding="utf-8")
            with mock.patch.object(config, "SETTINGS_PATH", chemin):
                self.assertEqual(lanceur._choose_language(), "en")
            self.assertEqual(i18n.language(), "en")
            chemin.write_text('{"language": "klingon"}', encoding="utf-8")
            with mock.patch.object(config, "SETTINGS_PATH", chemin):
                self.assertEqual(lanceur._choose_language(), "fr")

    def test_l_aide_de_la_ligne_de_commande_parle_la_langue(self):
        import main as lanceur

        i18n.set_language("en")
        with self.assertRaises(SystemExit), \
                mock.patch("sys.stdout") as sortie:
            lanceur._parse_args(["--help"])
        texte = "".join(str(appel.args[0]) for appel in sortie.write.mock_calls
                        if appel.args)
        self.assertNotIn("vide l'index", texte)
        self.assertIn("SD card", texte)
        self.assertFalse(_ACCENTS & set(texte), texte)


if __name__ == "__main__":
    unittest.main()
