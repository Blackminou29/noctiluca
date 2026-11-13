# -*- coding: utf-8 -*-
"""Tests du hub MIDI (:mod:`delugeapp.core.midihub`).

Sans appareil ni Qt : les ports sont simulés — des claviers qu'on « joue »,
des sorties qui notent ce qu'elles reçoivent —, et le Deluge est celui de
``tests/deluge_simule.py``, branché à un vrai :class:`DelugeLink`.

    python -m unittest tests.test_hub -v
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

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

from delugeapp.core import midifollow, midihub, midiport     # noqa: E402
from delugeapp.core.delugelink import DelugeLink             # noqa: E402
from delugeapp.core.midihub import DELUGE, MidiHub, Route    # noqa: E402

NOTE_ON, NOTE_OFF, CC = 0x90, 0x80, 0xB0


def _voisin(nom: str):
    """Un module de ``tests/`` (``deluge_simule``, ``ports_simules``), quelle
    que soit la façon dont la suite est lancée."""
    import importlib

    dossier = str(Path(__file__).resolve().parent)
    if dossier not in sys.path:
        sys.path.insert(0, dossier)
    return importlib.import_module(nom)


def _deluge_simule():
    return _voisin("deluge_simule")


#: Les ports simulés (``tests/ports_simules.py``), partagés avec les tests
#: d'interface.
FausseSortie = _voisin("ports_simules").FausseSortie
FauxPorts = _voisin("ports_simules").FauxPorts


class HubCase(unittest.TestCase):
    """Un clavier, une surface de contrôle, deux sorties."""

    ENTREES = ("Clavier", "Surface")
    SORTIES = ("Synthé", "Boîte")

    def setUp(self):
        self.ports = FauxPorts(self.ENTREES, self.SORTIES)
        self.hub = MidiHub(self.ports)
        self.addCleanup(self.hub.close)

    def jouer(self, nom, status, data1=0, data2=0):
        self.ports.jouer(nom, status, data1, data2)
        self.assertTrue(self.hub.flush(), "le fil du hub n'a pas suivi")

    def recus(self, nom="Synthé"):
        return self.ports.sorties_ouvertes[nom].recus


# --------------------------------------------------------------------------- #
# Ce qu'un branchement fait d'un message
# --------------------------------------------------------------------------- #

class TestUnBranchement(HubCase):
    """Canal, transposition, étendue, filtres, table des boutons."""

    def test_une_note_traverse_telle_quelle(self):
        self.hub.connect("Clavier", "Synthé")
        self.jouer("Clavier", NOTE_ON | 2, 60, 96)
        self.jouer("Clavier", NOTE_OFF | 2, 60, 40)
        self.assertEqual(self.recus(), [(NOTE_ON | 2, 60, 96),
                                        (NOTE_OFF | 2, 60, 40)])

    def test_le_canal_d_arrivee_remplace_celui_du_clavier(self):
        self.hub.connect("Clavier", "Synthé", channel_out=10)
        self.jouer("Clavier", NOTE_ON, 36, 110)
        self.jouer("Clavier", CC, 1, 64)
        self.assertEqual(self.recus(), [(NOTE_ON | 9, 36, 110),
                                        (CC | 9, 1, 64)])

    def test_une_note_de_force_nulle_est_un_relachement(self):
        """Beaucoup de claviers relâchent par « note jouée, force 0 »."""
        self.hub.connect("Clavier", "Synthé", channel_out=3)
        self.jouer("Clavier", NOTE_ON, 64, 80)
        self.jouer("Clavier", NOTE_ON, 64, 0)
        self.assertEqual(self.recus(), [(NOTE_ON | 2, 64, 80),
                                        (NOTE_ON | 2, 64, 0)])
        self.assertEqual(self.ports.sorties_ouvertes["Synthé"].notes_tenues(),
                         set())

    def test_la_transposition_ecarte_ce_qui_sort_du_clavier(self):
        self.hub.connect("Clavier", "Synthé", transpose=12)
        self.jouer("Clavier", NOTE_ON, 60, 100)
        self.jouer("Clavier", NOTE_ON, 120, 100)      # 132 : hors du MIDI
        self.jouer("Clavier", NOTE_OFF, 120, 0)
        self.jouer("Clavier", NOTE_OFF, 60, 0)
        self.assertEqual(self.recus(), [(NOTE_ON, 72, 100),
                                        (NOTE_OFF, 72, 0)])

    def test_l_etendue_ne_laisse_passer_que_sa_part_du_clavier(self):
        """Un clavier partagé : le bas vers une sortie, le haut vers l'autre."""
        self.hub.connect("Clavier", "Synthé", high=59)
        self.hub.connect("Clavier", "Boîte", low=60)
        for note in (48, 59, 60, 72):
            self.jouer("Clavier", NOTE_ON, note, 100)
        self.assertEqual([m[1] for m in self.recus("Synthé")], [48, 59])
        self.assertEqual([m[1] for m in self.recus("Boîte")], [60, 72])

    def test_chaque_filtre_ferme_sa_famille_de_messages(self):
        essais = (("notes", (NOTE_ON, 60, 100)),
                  ("controllers", (CC, 74, 30)),
                  ("bend", (0xE0, 0, 96)),
                  ("bend", (0xD0, 90, 0)))
        for filtre, message in essais:
            with self.subTest(filtre=filtre, message=message):
                route = self.hub.connect("Clavier", "Synthé")
                self.jouer("Clavier", *message)
                self.assertEqual(self.recus(), [message])
                self.hub.update(route.uid, **{filtre: False})
                self.recus().clear()
                self.jouer("Clavier", *message)
                self.assertEqual(self.recus(), [])
                self.hub.remove(route.uid)

    def test_programmes_et_horloge_ne_passent_que_demandes(self):
        route = self.hub.connect("Clavier", "Synthé")
        for message in ((0xC0, 5, 0), (midiport.START, 0, 0),
                        (midiport.CLOCK, 0, 0), (midiport.STOP, 0, 0)):
            self.jouer("Clavier", *message)
        self.assertEqual(self.recus(), [])
        self.hub.update(route.uid, programs=True, clock=True)
        for message in ((0xC0, 5, 0), (midiport.START, 0, 0),
                        (midiport.CLOCK, 0, 0), (midiport.STOP, 0, 0)):
            self.jouer("Clavier", *message)
        self.assertEqual(self.recus(), [(0xC0, 5, 0), (midiport.START, 0, 0),
                                        (midiport.CLOCK, 0, 0),
                                        (midiport.STOP, 0, 0)])

    def test_le_je_suis_la_d_un_clavier_ne_va_nulle_part(self):
        """« Active sensing » : trois fois par seconde, pour rien."""
        self.hub.connect("Clavier", "Synthé", clock=True)
        self.jouer("Clavier", 0xFE)
        self.assertEqual(self.recus(), [])
        self.assertEqual(self.hub.monitor(), [])

    def test_la_table_des_boutons_traduit_un_controleur(self):
        """Le bouton 21 de la surface pilote le filtre du Deluge (74)."""
        self.hub.connect("Surface", "Synthé", channel_out=1,
                         cc_map={21: 74})
        self.jouer("Surface", CC | 5, 21, 99)
        self.jouer("Surface", CC | 5, 22, 10)
        self.assertEqual(self.recus(), [(CC, 74, 99), (CC, 22, 10)])

    def test_n_ecouter_qu_un_canal_de_la_source(self):
        self.hub.connect("Clavier", "Synthé", channel_in=2)
        self.jouer("Clavier", NOTE_ON, 60, 100)        # canal 1 : écarté
        self.jouer("Clavier", NOTE_ON | 1, 62, 100)    # canal 2
        self.assertEqual(self.recus(), [(NOTE_ON | 1, 62, 100)])

    def test_la_pression_par_touche_suit_la_note_transposee(self):
        self.hub.connect("Clavier", "Synthé", transpose=-12, channel_out=4)
        self.jouer("Clavier", NOTE_ON, 60, 100)
        self.jouer("Clavier", 0xA0, 60, 77)
        self.jouer("Clavier", 0xA0, 61, 77)     # touche jamais enfoncée
        self.assertEqual(self.recus(), [(NOTE_ON | 3, 48, 100),
                                        (0xA0 | 3, 48, 77)])

    def test_une_valeur_de_128_est_ramenee_dans_le_midi(self):
        """Le Deluge envoie 128 pour un bouton au maximum : le pilote le
        garde, la sortie le borne (``midiport.short_message``)."""
        self.assertEqual(midiport.short_message(CC, 74, 128) >> 16, 127)


# --------------------------------------------------------------------------- #
# Aucune note coincée
# --------------------------------------------------------------------------- #

class TestAucuneNoteCoincee(HubCase):
    """Le hub sait ce qu'il a fait passer, et le relâche."""

    def _synthe(self):
        return self.ports.sorties_ouvertes["Synthé"]

    def test_le_relachement_part_ou_l_appui_est_parti(self):
        """On change de canal et d'octave touche enfoncée : la note se
        relâche sur l'ancien canal, à l'ancienne hauteur."""
        route = self.hub.connect("Clavier", "Synthé", channel_out=2)
        self.jouer("Clavier", NOTE_ON, 60, 100)
        self.hub.update(route.uid, channel_out=7, transpose=12)
        self.assertEqual(self._synthe().notes_tenues(), set())
        self.assertIn((NOTE_OFF | 1, 60, 0), self.recus())
        # Le relâchement du clavier, arrivé après, ne part plus nulle part.
        avant = len(self.recus())
        self.jouer("Clavier", NOTE_OFF, 60, 0)
        self.assertEqual(len(self.recus()), avant)

    def test_couper_un_branchement_relache_ses_notes(self):
        route = self.hub.connect("Clavier", "Synthé")
        self.jouer("Clavier", NOTE_ON, 60, 100)
        self.jouer("Clavier", NOTE_ON, 64, 100)
        self.hub.update(route.uid, enabled=False)
        self.assertEqual(self._synthe().notes_tenues(), set())

    def test_retirer_un_branchement_relache_ses_notes(self):
        route = self.hub.connect("Clavier", "Synthé")
        autre = self.hub.connect("Surface", "Synthé")
        self.jouer("Clavier", NOTE_ON, 60, 100)
        self.jouer("Surface", NOTE_ON | 1, 36, 100)
        sortie = self._synthe()
        self.assertTrue(self.hub.remove(route.uid))
        # Celle de l'autre branchement tient toujours.
        self.assertEqual(sortie.notes_tenues(), {(2, 36)})
        self.assertFalse(sortie.fermee)
        self.assertTrue(self.hub.remove(autre.uid))
        self.assertEqual(sortie.notes_tenues(), set())
        self.assertTrue(sortie.fermee)

    def test_une_cible_qui_disparait_relache_ses_notes(self):
        """Le Deluge n'a plus de canal pour la piste : la voie tombe alors
        que ses deux ports restent ouverts — c'est elle, et non la
        fermeture d'un port, qui doit relâcher."""
        self.hub.connect("Clavier", "Synthé", follow="track_2")
        self.hub.connect("Clavier", "Boîte")
        self.hub.connect("Surface", "Synthé")
        self.hub.set_follow(midifollow.FollowSettings(tracks=((2, 5),)), 1)
        self.jouer("Clavier", NOTE_ON, 60, 100)
        self.assertEqual(self._synthe().notes_tenues(), {(5, 60)})
        self.hub.set_follow(midifollow.FollowSettings(), 1)
        self.assertFalse(self.ports.ouvertes["Clavier"].fermee)
        self.assertFalse(self._synthe().fermee)
        self.assertEqual(self._synthe().notes_tenues(), set())

    def test_la_pedale_et_la_molette_reviennent_au_repos(self):
        route = self.hub.connect("Clavier", "Synthé")
        self.jouer("Clavier", CC, 64, 127)
        self.jouer("Clavier", 0xE0, 0, 100)
        self.hub.remove(route.uid)
        self.assertEqual(self.recus()[-2:], [(CC, 64, 0), (0xE0, 0, 64)])

    def test_un_clavier_debranche_relache_ce_qu_il_tenait(self):
        self.hub.connect("Clavier", "Synthé")
        self.jouer("Clavier", NOTE_ON, 60, 100)
        sortie = self._synthe()
        self.ports.entrees.remove("Clavier")
        self.assertTrue(self.hub.rescan())
        self.assertEqual(sortie.notes_tenues(), set())
        self.assertTrue(self.ports.ouvertes["Clavier"].fermee)

    def test_arreter_le_hub_relache_et_rend_les_ports(self):
        self.hub.connect("Clavier", "Synthé")
        self.jouer("Clavier", NOTE_ON, 60, 100)
        sortie, entree = self._synthe(), self.ports.ouvertes["Clavier"]
        self.hub.set_enabled(False)
        self.assertEqual(sortie.notes_tenues(), set())
        self.assertTrue(sortie.fermee and entree.fermee)
        self.assertEqual(self.hub.state(self.hub.routes[0].uid), "hub_off")
        # Remis en marche, il reprend ses ports.
        self.hub.set_enabled(True)
        self.assertEqual(self.hub.state(self.hub.routes[0].uid), "active")
        self.assertFalse(self._synthe().fermee)

    def test_tout_eteindre_relache_et_demande_le_silence(self):
        self.hub.connect("Clavier", "Synthé")
        self.jouer("Clavier", NOTE_ON, 60, 100)
        self.assertEqual(self.hub.panic(), 1)
        recus = self.recus()
        self.assertIn((NOTE_OFF, 60, 0), recus)
        silences = [m for m in recus if m[0] & 0xF0 == CC and m[1] == 123]
        self.assertEqual(len(silences), 16)

    def test_fermer_le_hub_relache_tout(self):
        self.hub.connect("Clavier", "Synthé")
        self.jouer("Clavier", NOTE_ON, 60, 100)
        sortie = self._synthe()
        self.hub.close()
        self.assertEqual(sortie.notes_tenues(), set())
        self.assertTrue(sortie.fermee)
        # Fermé, il ne rouvre plus rien.
        self.assertFalse(self.hub.rescan())
        self.assertTrue(sortie.fermee)


# --------------------------------------------------------------------------- #
# Les ports
# --------------------------------------------------------------------------- #

class TestLesPortsDuHub(HubCase):
    """Le hub n'ouvre que ce dont il a besoin, et suit les appareils."""

    def test_sans_branchement_rien_n_est_ouvert(self):
        self.hub.rescan()
        self.assertEqual(self.ports.ouvertures, [])
        self.assertEqual([b.name for b in self.hub.sources()],
                         ["Clavier", "Surface"])
        self.assertFalse(any(b.open for b in self.hub.sources()))

    def test_seuls_les_ports_d_un_branchement_sont_ouverts(self):
        self.hub.connect("Clavier", "Synthé")
        self.assertEqual(sorted(self.ports.ouvertures),
                         ["in:Clavier", "out:Synthé"])
        ouverts = {b.name for b in self.hub.sources() if b.open}
        self.assertEqual(ouverts, {"Clavier"})

    def test_un_branchement_coupe_ne_garde_pas_ses_ports(self):
        """Avec un pilote à un seul client, un port tenu par le hub est
        refusé au DAW : coupé, le branchement le rend."""
        route = self.hub.connect("Clavier", "Synthé")
        entree = self.ports.ouvertes["Clavier"]
        self.hub.update(route.uid, enabled=False)
        self.assertTrue(entree.fermee)
        self.assertEqual(self.hub.state(route.uid), "off")

    def test_un_appareil_absent_attend_puis_est_pris_a_son_arrivee(self):
        self.ports.entrees.remove("Surface")
        route = self.hub.connect("Surface", "Synthé")
        self.assertEqual(self.hub.state(route.uid), "no_source")
        surface = next(b for b in self.hub.sources() if b.name == "Surface")
        self.assertFalse(surface.present)
        self.ports.entrees.append("Surface")
        self.assertTrue(self.hub.rescan())
        self.assertEqual(self.hub.state(route.uid), "active")
        self.jouer("Surface", NOTE_ON, 40, 90)
        self.assertEqual(self.recus(), [(NOTE_ON, 40, 90)])

    def test_une_destination_absente_n_empeche_pas_de_voir_la_source(self):
        self.ports.sorties.remove("Boîte")
        route = self.hub.connect("Clavier", "Boîte")
        self.assertEqual(self.hub.state(route.uid), "no_dest")
        self.jouer("Clavier", NOTE_ON, 60, 100)
        evenement = self.hub.monitor()[-1]
        self.assertEqual((evenement.source, evenement.delivered),
                         ("Clavier", 0))

    def test_rien_ne_change_rien_n_est_rouvert(self):
        self.hub.connect("Clavier", "Synthé")
        self.jouer("Clavier", NOTE_ON, 60, 100)
        avant = list(self.ports.ouvertures)
        for _ in range(3):
            self.assertFalse(self.hub.rescan())
        self.assertEqual(self.ports.ouvertures, avant)
        # La note tenue l'est toujours : rien n'a été relâché.
        self.assertEqual(self.ports.sorties_ouvertes["Synthé"].notes_tenues(),
                         {(1, 60)})

    def test_un_port_refuse_dit_pourquoi(self):
        self.ports.refus["Synthé"] = "port déjà utilisé"
        with self.assertLogs("delugeapp.core.midihub", level="WARNING"):
            route = self.hub.connect("Clavier", "Synthé")
        # Dit une fois dans le journal, pas à chaque seconde.
        with self.assertNoLogs("delugeapp.core.midihub", level="WARNING"):
            self.hub.rescan()
        self.assertEqual(self.hub.state(route.uid), "no_dest")
        self.assertEqual(self.hub.port_error("Synthé"), "port déjà utilisé")
        del self.ports.refus["Synthé"]
        self.hub.rescan()
        self.assertEqual(self.hub.state(route.uid), "active")
        self.assertEqual(self.hub.port_error("Synthé"), "")

    def test_un_appareil_ne_se_branche_pas_sur_lui_meme(self):
        self.ports.sorties.append("Clavier")
        with self.assertRaises(ValueError):
            self.hub.connect("Clavier", "Clavier")
        self.assertEqual(self.hub.routes, [])
        self.assertTrue(MidiHub.refusal("Clavier", "Clavier"))
        self.assertEqual(MidiHub.refusal("Clavier", "Synthé"), "")

    def test_brancher_deux_fois_rend_le_meme_branchement(self):
        premier = self.hub.connect("Clavier", "Synthé", transpose=12)
        second = self.hub.connect("Clavier", "Synthé")
        self.assertEqual(premier.uid, second.uid)
        self.assertEqual(second.transpose, 12)
        self.assertEqual(len(self.hub.routes), 1)

    def test_plusieurs_claviers_plusieurs_destinations(self):
        """Deux surfaces à la fois, chacune vers sa destination — et le
        clavier vers les deux."""
        self.hub.connect("Clavier", "Synthé", channel_out=1)
        self.hub.connect("Clavier", "Boîte", channel_out=2)
        self.hub.connect("Surface", "Boîte", channel_out=10)
        self.jouer("Clavier", NOTE_ON, 60, 100)
        self.jouer("Surface", NOTE_ON, 36, 120)
        self.assertEqual(self.recus("Synthé"), [(NOTE_ON, 60, 100)])
        self.assertEqual(self.recus("Boîte"), [(NOTE_ON | 1, 60, 100),
                                               (NOTE_ON | 9, 36, 120)])
        self.assertEqual(self.hub.monitor()[0].delivered, 2)

    def test_les_valeurs_hors_bornes_sont_ramenees(self):
        route = self.hub.connect("Clavier", "Synthé", channel_out=99,
                                 transpose=500, follow="n'importe quoi")
        self.assertEqual((route.channel_out, route.transpose, route.follow),
                         (16, 60, ""))
        change = self.hub.update(route.uid, low=100, high=20, channel_in=-3)
        self.assertEqual((change.low, change.high, change.channel_in),
                         (20, 100, 0))
        # Les deux bouts ne se changent pas par là.
        self.hub.update(route.uid, source="Surface", dest="Boîte")
        garde = self.hub.route(route.uid)
        self.assertEqual((garde.source, garde.dest), ("Clavier", "Synthé"))


# --------------------------------------------------------------------------- #
# Le fil, le fusible, les mesures
# --------------------------------------------------------------------------- #

class TestLeFilDuHub(HubCase):

    def test_une_note_qui_revient_en_boucle_coupe_la_source(self):
        route = self.hub.connect("Clavier", "Synthé")
        with self.assertLogs("delugeapp.core.midihub", level="WARNING"):
            for _ in range(midihub.REPEAT_MAX + 5):
                self.ports.jouer("Clavier", NOTE_ON, 60, 100)
            self.hub.flush()
        self.assertEqual(self.hub.state(route.uid), "tripped")
        self.assertEqual(len(self.recus()), midihub.REPEAT_MAX + 1)
        # La note que la boucle tenait est relâchée ; plus rien ne passe.
        self.assertEqual(self.recus()[-1], (NOTE_OFF, 60, 0))
        self.jouer("Clavier", NOTE_ON, 62, 100)
        self.assertEqual(self.recus()[-1], (NOTE_OFF, 60, 0))
        source = next(b for b in self.hub.sources() if b.name == "Clavier")
        self.assertTrue(source.tripped)
        # Rendue, elle rejoue.
        self.hub.rearm("Clavier")
        self.assertEqual(self.hub.state(route.uid), "active")
        self.jouer("Clavier", NOTE_ON, 62, 100)
        self.assertEqual(self.recus()[-1], (NOTE_ON, 62, 100))

    def test_un_debit_impossible_coupe_la_source(self):
        route = self.hub.connect("Surface", "Synthé")
        with self.assertLogs("delugeapp.core.midihub", level="WARNING"):
            for i in range(midihub.RATE_MAX + 10):
                self.ports.jouer("Surface", CC, 1, i % 128)
            self.hub.flush()
        self.assertEqual(self.hub.state(route.uid), "tripped")
        self.assertEqual(len(self.recus()), midihub.RATE_MAX)

    def test_jouer_vite_ne_coupe_rien(self):
        """Un roulement serré, la même note à la même force : seize coups
        par seconde, loin du seuil."""
        route = self.hub.connect("Clavier", "Synthé")
        for _ in range(16):
            self.ports.jouer("Clavier", NOTE_ON, 38, 100)
            self.ports.jouer("Clavier", NOTE_OFF, 38, 0)
        self.hub.flush()
        self.assertEqual(self.hub.state(route.uid), "active")
        self.assertEqual(len(self.recus()), 32)

    def test_une_sortie_qui_leve_ne_tue_pas_le_fil(self):
        self.hub.connect("Clavier", "Synthé")
        self.hub.connect("Clavier", "Boîte")
        self.ports.sorties_ouvertes["Synthé"].leve = True
        with self.assertLogs("delugeapp.core.midihub", level="ERROR"):
            self.jouer("Clavier", NOTE_ON, 60, 100)
        self.ports.sorties_ouvertes["Synthé"].leve = False
        self.jouer("Clavier", NOTE_ON, 62, 100)
        self.assertEqual(self.recus("Synthé"), [(NOTE_ON, 62, 100)])

    def test_le_retard_se_mesure(self):
        self.hub.connect("Clavier", "Synthé")
        self.assertIsNone(self.hub.stats().median_ms)
        self.assertEqual(self.hub.stats().summary(),
                         "Rien n'est encore passé.")
        for note in range(60, 70):
            self.jouer("Clavier", NOTE_ON, note, 100)
        mesure = self.hub.stats()
        self.assertEqual(mesure.relayed, 10)
        self.assertIsNotNone(mesure.median_ms)
        self.assertGreaterEqual(mesure.worst_ms, mesure.median_ms)
        # Un changement de fil, pas une attente : loin sous 50 ms, même
        # sur une machine chargée.
        self.assertLess(mesure.median_ms, 50.0)
        self.assertIn("10 messages relayés", mesure.summary())

    def test_le_moniteur_garde_les_messages_pas_les_tops_d_horloge(self):
        self.hub.connect("Clavier", "Synthé", clock=True)
        self.jouer("Clavier", midiport.START)
        for _ in range(24):
            self.jouer("Clavier", midiport.CLOCK)
        self.jouer("Clavier", NOTE_ON, 60, 100)
        vus = self.hub.monitor()
        self.assertEqual([(e.status, e.delivered) for e in vus],
                         [(midiport.START, 1), (NOTE_ON, 1)])
        self.assertEqual(self.hub.stats().clock, 24)
        self.assertEqual(self.hub.monitor(after=vus[0].seq), vus[1:])
        self.assertEqual(len(self.recus()), 26)

    def test_le_dernier_controleur_sert_a_apprendre_un_bouton(self):
        self.hub.connect("Surface", "Synthé")
        self.assertIsNone(self.hub.last_controller("Surface"))
        self.jouer("Surface", CC | 3, 21, 50)
        numero, valeur, rang = self.hub.last_controller("Surface")
        self.assertEqual((numero, valeur), (21, 50))
        self.jouer("Surface", CC | 3, 22, 51)
        self.assertGreater(self.hub.last_controller("Surface")[2], rang)

    def test_les_compteurs_disent_qui_joue(self):
        route = self.hub.connect("Clavier", "Synthé")
        self.jouer("Clavier", NOTE_ON, 60, 100)
        self.jouer("Clavier", NOTE_OFF, 60, 0)
        source = next(b for b in self.hub.sources() if b.name == "Clavier")
        sortie = next(b for b in self.hub.destinations()
                      if b.name == "Synthé")
        self.assertEqual((source.count, sortie.count), (2, 2))
        self.assertEqual(self.hub.counts(), {route.uid: 2})

    def test_le_hub_presse_python_tant_qu_il_relaie_et_pas_apres(self):
        """Sous Windows, un fil qui attend la main de Python ne l'a qu'au
        battement de l'ordonnanceur : 8 ms de retard médian dès que
        l'interface calcule (mesuré). Le hub raccourcit cette attente tant
        qu'une entrée est ouverte, et rend ce qu'il a trouvé."""
        avant = sys.getswitchinterval()
        self.assertGreater(avant, midihub.SWITCH_INTERVAL)
        route = self.hub.connect("Clavier", "Synthé")
        self.assertAlmostEqual(sys.getswitchinterval(),
                               midihub.SWITCH_INTERVAL)
        # Un second hub n'y change rien, et ne rend rien trop tôt.
        autre = MidiHub(FauxPorts(["Clavier"], ["Synthé"]))
        autre.connect("Clavier", "Synthé")
        self.hub.update(route.uid, enabled=False)
        self.assertAlmostEqual(sys.getswitchinterval(),
                               midihub.SWITCH_INTERVAL)
        autre.close()
        self.assertAlmostEqual(sys.getswitchinterval(), avant)
        # Remis en service puis fermé : rendu encore.
        self.hub.update(route.uid, enabled=True)
        self.assertAlmostEqual(sys.getswitchinterval(),
                               midihub.SWITCH_INTERVAL)
        self.hub.close()
        self.assertAlmostEqual(sys.getswitchinterval(), avant)

    def test_la_phrase_d_etat(self):
        self.assertEqual(self.hub.summary(), "Hub MIDI : aucun branchement.")
        self.hub.connect("Clavier", "Synthé")
        self.ports.sorties.remove("Boîte")
        self.hub.connect("Surface", "Boîte")
        self.assertEqual(self.hub.summary(),
                         "Hub MIDI : 1 branchement en service sur 2.")
        self.hub.set_enabled(False)
        self.assertEqual(self.hub.summary(), "Hub MIDI à l'arrêt.")


# --------------------------------------------------------------------------- #
# Le Deluge
# --------------------------------------------------------------------------- #

class DelugeCase(unittest.TestCase):
    """Le Deluge simulé au bout d'un vrai lien, et un clavier simulé."""

    def setUp(self):
        self.machine = _deluge_simule().DelugeSimule()
        self._sauves = (midiport.outputs, midiport.inputs,
                        midiport.available)
        clavier_in = midiport.MidiDevice(7, "KeyStep 37", "in")
        self.appareils_in = [clavier_in]
        midiport.outputs = lambda: self.machine.devices("out")
        midiport.inputs = lambda: (self.machine.devices("in")
                                   + self.appareils_in)
        midiport.available = lambda: True
        self.addCleanup(self._rendre)
        self.lien = DelugeLink()
        self.machine.brancher(self.lien)
        self.addCleanup(self.lien.close)

        # Le clavier est simulé ; le Deluge passe par le vrai ``Backend``.
        self.clavier = FauxPorts(["KeyStep 37"], [])
        vrai = midihub.Backend(lambda: self.lien)
        self.backend = vrai
        ouvrir = vrai.open_input

        def open_input(name, push):
            if name == "KeyStep 37":
                return self.clavier.open_input(name, push)
            return ouvrir(name, push)

        vrai.open_input = open_input
        self.hub = MidiHub(vrai)
        self.addCleanup(self.hub.close)

    def _rendre(self):
        (midiport.outputs, midiport.inputs,
         midiport.available) = self._sauves

    def jouer(self, status, data1=0, data2=0):
        self.clavier.jouer("KeyStep 37", status, data1, data2)
        self.assertTrue(self.hub.flush())

    def courts(self):
        return [e[1:] for e in self.machine.sorties[1].envoyes
                if e[0] == "court"]


class TestLeDelugeDansLeHub(DelugeCase):

    def test_les_ports_du_deluge_sont_remplaces_par_le_lien(self):
        """Le hub ne rouvre pas « Deluge », « MIDIIN2 (Deluge) »… : il voit
        un seul Deluge, celui du lien, et seulement une fois connecté."""
        self.assertEqual(self.backend.inputs(), ["KeyStep 37"])
        self.assertEqual(self.backend.outputs(),
                         ["Microsoft GS Wavetable Synth"])
        self.assertTrue(self.backend.deluge_detected())
        self.assertTrue(self.lien.connect())
        self.assertEqual(self.backend.inputs(), [DELUGE, "KeyStep 37"])
        self.assertEqual(self.backend.outputs(),
                         [DELUGE, "Microsoft GS Wavetable Synth"])

    def test_le_clavier_joue_l_instrument_selectionne(self):
        """Par défaut, un branchement vers le Deluge vise MIDI Follow A."""
        self.assertTrue(self.lien.connect())
        route = self.hub.connect("KeyStep 37", DELUGE)
        self.assertEqual(route.follow, "a")
        self.hub.set_follow(midifollow.FollowSettings(channel_a=5), 1)
        self.assertEqual(self.hub.state(route.uid), "active")
        self.jouer(NOTE_ON, 60, 100)
        self.jouer(NOTE_OFF, 60, 0)
        self.assertEqual(self.courts(), [(NOTE_ON | 4, 60, 100),
                                         (NOTE_OFF | 4, 60, 0)])

    def test_le_canal_suit_celui_que_la_machine_change(self):
        self.assertTrue(self.lien.connect())
        self.hub.connect("KeyStep 37", DELUGE)
        self.hub.set_follow(midifollow.FollowSettings(channel_a=1), 1)
        self.jouer(NOTE_ON, 60, 100)
        self.hub.set_follow(midifollow.FollowSettings(channel_a=9), 1)
        # La note tenue est relâchée sur l'ancien canal, la suivante part
        # sur le nouveau.
        self.jouer(NOTE_ON, 62, 100)
        self.assertEqual(self.courts(), [(NOTE_ON, 60, 100),
                                         (NOTE_OFF, 60, 0),
                                         (NOTE_ON | 8, 62, 100)])

    def test_sans_reglages_lus_le_canal_a_est_celui_de_l_application(self):
        self.assertTrue(self.lien.connect())
        route = self.hub.connect("KeyStep 37", DELUGE)
        self.hub.set_follow(None, 3)
        self.assertEqual(self.hub.channel_for(route), 3)
        self.assertIn("Channel A vaut 3", self.hub.advice(route))
        # La carte dit que MIDI Follow est éteint : le message part quand
        # même sur le canal de l'application, et le conseil le signale.
        self.hub.set_follow(midifollow.FollowSettings(), 3)
        self.assertEqual(self.hub.state(route.uid), "active")
        self.assertIn("n'écoute pas MIDI Follow A", self.hub.advice(route))
        self.hub.set_follow(midifollow.FollowSettings(channel_a=3), 3)
        self.assertEqual(self.hub.advice(route), "")

    def test_une_piste_sans_canal_attend_et_dit_quoi_regler(self):
        """« Channel Track 2 » du firmware 1.3 : ce canal va à la piste 2,
        quelle que soit celle qu'on regarde."""
        self.assertTrue(self.lien.connect())
        route = self.hub.connect("KeyStep 37", DELUGE, follow="track_2")
        self.hub.set_follow(midifollow.FollowSettings(channel_a=1), 1)
        self.assertEqual(self.hub.state(route.uid), "no_channel")
        self.assertIn("Channel Track 2", self.hub.advice(route))
        self.jouer(NOTE_ON, 60, 100)
        self.assertEqual(self.courts(), [])
        self.hub.set_follow(
            midifollow.FollowSettings(channel_a=1, tracks=((2, 6),)), 1)
        self.assertEqual(self.hub.state(route.uid), "active")
        self.jouer(NOTE_ON, 60, 100)
        self.assertEqual(self.courts(), [(NOTE_ON | 5, 60, 100)])

    def test_le_deluge_absent_puis_connecte(self):
        route = self.hub.connect("KeyStep 37", DELUGE)
        self.assertEqual(self.hub.state(route.uid), "no_dest")
        self.assertTrue(self.hub.deluge_detected())
        self.assertTrue(self.lien.connect())
        self.hub.rescan()
        self.assertEqual(self.hub.state(route.uid), "active")
        # Déconnecté : le branchement attend, et le hub n'a rien fermé du
        # lien — ce port n'est pas à lui.
        self.jouer(NOTE_ON, 60, 100)
        self.lien.disconnect()
        self.hub.rescan()
        self.assertEqual(self.hub.state(route.uid), "no_dest")

    def test_le_deluge_comme_source_ne_prive_pas_le_lien(self):
        """Ce que la machine envoie arrive au hub **et** au lien : son
        tempo, ses notes, son retour MIDI Follow."""
        self.assertTrue(self.lien.connect())
        sortie = FausseSortie("Port virtuel")
        ouvrir = self.backend.open_output
        self.backend.open_output = (
            lambda nom: sortie if nom == "Port virtuel" else ouvrir(nom))
        sorties = self.backend.outputs
        self.backend.outputs = lambda: sorties() + ["Port virtuel"]
        route = self.hub.connect(DELUGE, "Port virtuel", clock=True)
        self.assertEqual(self.hub.state(route.uid), "active")

        self.machine.court(NOTE_ON | 2, 67, 90)
        self.machine.court(midiport.START)
        self.machine.court(CC, 74, 128)
        self.assertTrue(self.hub.flush())
        self.assertEqual(sortie.recus, [(NOTE_ON | 2, 67, 90),
                                        (midiport.START, 0, 0),
                                        (CC, 74, 128)])
        evenements = self.lien.service()
        self.assertIn("notes", evenements)
        self.assertIn("transport", evenements)
        self.assertEqual(self.lien.held, {67})
        self.assertTrue(self.lien.running)

    def test_l_auditeur_survit_a_une_reconnexion(self):
        self.assertTrue(self.lien.connect())
        recus = []
        self.lien.set_listener(lambda s, a, b, t: recus.append((s, a, b)))
        self.machine.court(NOTE_ON, 60, 100)
        self.lien.disconnect()
        self.assertIsNone(self.machine.entrees[1].court)
        self.assertTrue(self.lien.connect())
        self.machine.court(NOTE_ON, 62, 100)
        self.assertEqual(recus, [(NOTE_ON, 60, 100), (NOTE_ON, 62, 100)])
        self.lien.set_listener(None)
        self.machine.court(NOTE_ON, 64, 100)
        self.assertEqual(len(recus), 2)

    def test_un_branchement_vers_le_deluge_ne_vise_a_que_depuis_ailleurs(self):
        self.assertEqual(midihub.default_route("Clavier", DELUGE).follow, "a")
        self.assertEqual(midihub.default_route(DELUGE, "Port").follow, "")
        self.assertEqual(midihub.default_route("Clavier", "Port").follow, "")
        self.assertFalse(midihub.default_route("Clavier", DELUGE).clock)


class TestLesCanauxParPiste(unittest.TestCase):
    """``SETTINGS/MIDIFollow.XML`` du firmware 1.3 : A, B, C et seize
    pistes (mesuré sur la carte de l'utilisateur, 12 novembre 2026)."""

    XML = """<?xml version="1.0" encoding="UTF-8"?>
<defaults>
	<settings>
		<channels>
			<a>
				<channel>1</channel>
			</a>
			<b>
				<channel>256</channel>
			</b>
			<c>
				<channel>16</channel>
			</c>
			<track_1>
				<channel>256</channel>
			</track_1>
			<track_2>
				<channel>4</channel>
			</track_2>
			<track_16>
				<channel>11</channel>
			</track_16>
		</channels>
		<kit_root_note>
			<note>36</note>
		</kit_root_note>
		<feedback>
			<channel>track_a</channel>
			<automation>disabled</automation>
			<filter>disabled</filter>
		</feedback>
	</settings>
</defaults>
"""

    def test_les_pistes_reglees_sont_lues(self):
        with tempfile.TemporaryDirectory() as dossier:
            fichier = Path(dossier) / "MIDIFollow.XML"
            fichier.write_text(self.XML, encoding="utf-8")
            lus = midifollow.read_settings(path=fichier)
        self.assertEqual((lus.channel_a, lus.channel_b, lus.channel_c),
                         (1, None, 16))
        self.assertEqual(lus.tracks, ((2, 4), (16, 11)))
        self.assertEqual(lus.channel_of("track_2"), 4)
        self.assertIsNone(lus.channel_of("track_1"))
        self.assertIsNone(lus.channel_of("track_x"))
        self.assertEqual(lus.channel_of("C"), 16)
        # « La piste, et A » : le retour vers A est allumé.
        self.assertEqual(lus.feedback, "a")


# --------------------------------------------------------------------------- #
# Dire, lire, écrire
# --------------------------------------------------------------------------- #

class TestLesMotsDuHub(unittest.TestCase):

    def test_le_role_d_un_port_se_lit_dans_son_nom(self):
        for nom, role in (
                (DELUGE, "deluge"),
                ("Microsoft GS Wavetable Synth", "synth"),
                ("loopMIDI Port", "virtual"),
                ("Noctiluca vers le DAW", "virtual"),
                ("LoopBe Internal MIDI", "virtual"),
                ("KeyStep 37", "device"),
                ("Launchkey Mini MK3 MIDI", "device")):
            with self.subTest(nom=nom):
                self.assertEqual(midihub.role_of(nom), role)
        self.assertEqual(midihub.endpoint_label(DELUGE), "Deluge")
        self.assertEqual(
            midihub.endpoint_label("Microsoft GS Wavetable Synth"),
            "Synthé de Windows")

    def test_un_branchement_se_dit_en_une_phrase(self):
        route = Route("KeyStep 37", DELUGE, follow="a", transpose=-12,
                      cc_map={21: 74})
        self.assertEqual(
            midihub.describe_route(route, 1),
            "« KeyStep 37 » vers « Deluge » : l'instrument sélectionné — "
            "MIDI Follow A, canal 1, transposé de -12 demi-tons, 1 bouton "
            "traduit — notes, molette et pression, contrôleurs")
        muet = Route("A", "B", notes=False, bend=False, controllers=False)
        self.assertTrue(midihub.describe_route(muet).endswith(
            "canal d'origine — rien ne passe"))
        self.assertIn("la piste 3, canal non réglé sur le Deluge",
                      midihub.describe_route(Route("A", DELUGE,
                                                   follow="track_3")))

    def test_un_message_se_dit_en_clair(self):
        dire = midihub.describe_message
        self.assertEqual(dire(NOTE_ON | 1, 60, 96),
                         "note Do3, force 96 (canal 2)")
        self.assertEqual(dire(NOTE_ON, 60, 0), "note Do3 relâchée (canal 1)")
        self.assertEqual(dire(CC | 15, 74, 127),
                         "contrôleur 74 = 127 (canal 16)")
        self.assertEqual(dire(0xE0, 0, 64), "molette +0 (canal 1)")
        self.assertEqual(dire(0xC0, 4), "programme 5 (canal 1)")
        self.assertEqual(dire(midiport.START), "départ")

    def test_les_mots_passent_en_anglais(self):
        from delugeapp import i18n

        i18n.set_language("en")
        self.addCleanup(i18n.set_language, "fr")
        self.assertEqual(midihub.describe_message(NOTE_ON, 60, 96),
                         "note C3, velocity 96 (channel 1)")
        self.assertEqual(MidiHub.state_text("no_source"),
                         "the source is not plugged in")
        self.assertEqual(MidiHub(FauxPorts()).summary(),
                         "MIDI hub: no patch.")


class TestLeFichierDesBranchements(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.fichier = Path(self._tmp.name) / "sous" / "hub.json"

    def test_aller_et_retour(self):
        routes = [Route("KeyStep 37", DELUGE, follow="a", transpose=12,
                        cc_map={21: 74, 22: 71}),
                  Route(DELUGE, "loopMIDI Port", clock=True, notes=False,
                        enabled=False, channel_in=2, channel_out=10)]
        self.assertTrue(midihub.save_config(self.fichier, False, routes))
        marche, lues = midihub.load_config(self.fichier)
        self.assertFalse(marche)
        self.assertEqual([r.to_dict() for r in lues],
                         [r.to_dict() for r in routes])
        # Rien d'autre n'est resté dans le dossier.
        self.assertEqual([p.name for p in self.fichier.parent.iterdir()],
                         ["hub.json"])

    def test_sans_fichier_le_hub_est_en_marche_et_vide(self):
        self.assertEqual(midihub.load_config(self.fichier), (True, []))

    def test_un_fichier_abime_ne_leve_pas(self):
        self.fichier.parent.mkdir(parents=True)
        for contenu in ("{", "[1, 2]", '{"routes": 5}', ""):
            self.fichier.write_text(contenu, encoding="utf-8")
            with self.subTest(contenu=contenu):
                if contenu in ("{", ""):
                    with self.assertLogs("delugeapp.core.midihub",
                                         level="WARNING"):
                        lu = midihub.load_config(self.fichier)
                else:
                    lu = midihub.load_config(self.fichier)
                self.assertEqual(lu, (True, []))

    def test_ce_qui_ne_tient_pas_debout_est_ecarte_le_reste_repare(self):
        self.fichier.parent.mkdir(parents=True)
        self.fichier.write_text(json.dumps({"enabled": True, "routes": [
            {"source": "A", "dest": "B", "uid": "un", "transpose": "9",
             "channel_out": 40, "follow": "track_99",
             "cc_map": {"21": 74, "x": 1, "200": 3}},
            {"source": "A", "dest": "C", "uid": "un"},      # même identité
            {"source": "A", "dest": "A"},                   # sur lui-même
            {"source": "", "dest": "B"},
            "pas un branchement",
        ]}), encoding="utf-8")
        _marche, lues = midihub.load_config(self.fichier)
        self.assertEqual(len(lues), 1)
        seul = lues[0]
        self.assertEqual((seul.transpose, seul.channel_out, seul.follow,
                          seul.cc_map), (9, 16, "", {21: 74}))

    def test_le_hub_reprend_ce_qu_il_a_enregistre(self):
        ports = FauxPorts(["Clavier"], ["Synthé"])
        hub = MidiHub(ports)
        self.addCleanup(hub.close)
        hub.connect("Clavier", "Synthé", channel_out=4)
        midihub.save_config(self.fichier, hub.enabled, hub.routes)

        autre = MidiHub(FauxPorts(["Clavier"], ["Synthé"]))
        self.addCleanup(autre.close)
        marche, routes = midihub.load_config(self.fichier)
        autre.set_routes(routes)
        autre.set_enabled(marche)
        self.assertEqual(autre.state(routes[0].uid), "active")
        self.assertEqual(autre.routes[0].channel_out, 4)


# --------------------------------------------------------------------------- #
# Le vrai rappel du pilote
# --------------------------------------------------------------------------- #

class _FauxWinmmEntree:
    """``winmm`` réduit à l'ouverture d'une entrée sans SysEx : de quoi
    appeler le vrai rappel de :class:`midiport.MidiIn`."""

    def __init__(self):
        self.proc = None
        self.appels: list[str] = []

    def midiInOpen(self, poignee, index, proc, inst, drapeaux):  # noqa: N802
        poignee._obj.value = 4242
        self.proc = proc
        self.appels.append("open")
        return 0

    def midiInStart(self, _h):                                   # noqa: N802
        return 0

    def midiInStop(self, _h):                                    # noqa: N802
        return 0

    def midiInReset(self, _h):                                   # noqa: N802
        return 0

    def midiInClose(self, _h):                                   # noqa: N802
        self.appels.append("close")
        return 0

    def court(self, status: int, d1: int = 0, d2: int = 0) -> None:
        self.proc(4242, 0x3C3, None, status | (d1 << 8) | (d2 << 16), 0)


class TestLeRobinetDesMessagesCourts(unittest.TestCase):
    """``MidiIn.set_message_tap`` : le rappel confie chaque message court
    au hub, qui le garde ou le laisse aussi à la file."""

    def setUp(self):
        if midiport.ctypes is None:
            self.skipTest("ctypes de Windows absent")
        self.faux = _FauxWinmmEntree()
        self._vrai = midiport._winmm
        midiport._winmm = self.faux
        self.addCleanup(self._rendre)
        self.entree = midiport.MidiIn(sysex=False)
        self.assertTrue(self.entree.open(
            midiport.MidiDevice(0, "KeyStep 37", "in")))
        self.addCleanup(self.entree.close)

    def _rendre(self):
        midiport._winmm = self._vrai

    def test_un_robinet_qui_garde_vide_la_file(self):
        vus = []
        self.entree.set_message_tap(
            lambda s, a, b, t: vus.append((s, a, b)) or True)
        self.faux.court(NOTE_ON, 60, 100)
        self.faux.court(CC, 74, 128)
        self.assertEqual(vus, [(NOTE_ON, 60, 100), (CC, 74, 128)])
        self.assertEqual(self.entree.poll(), [])

    def test_un_robinet_qui_ne_garde_pas_laisse_la_file_intacte(self):
        vus = []
        self.entree.set_message_tap(
            lambda s, a, b, t: vus.append(s) and False)
        self.faux.court(NOTE_ON, 60, 100)
        self.assertEqual(vus, [NOTE_ON])
        self.assertEqual([m.status for m in self.entree.poll()], [NOTE_ON])
        self.entree.set_message_tap(None)
        self.faux.court(NOTE_OFF, 60, 0)
        self.assertEqual(vus, [NOTE_ON])
        self.assertEqual(len(self.entree.poll()), 1)

    def test_un_robinet_qui_leve_ne_remonte_pas_dans_le_pilote(self):
        def robinet(*_a):
            raise RuntimeError("boum")

        self.entree.set_message_tap(robinet)
        self.faux.court(NOTE_ON, 60, 100)        # ne lève pas

    def test_le_vrai_backend_garde_les_messages_pour_le_hub(self):
        """Une entrée ouverte par le hub n'empile rien dans le port : sa
        file, que personne ne vide, déborderait."""
        self._sauves = midiport.inputs
        midiport.inputs = lambda: [midiport.MidiDevice(0, "KeyStep 37", "in")]
        self.addCleanup(setattr, midiport, "inputs", self._sauves)
        recus = []
        port = midihub.Backend().open_input(
            "KeyStep 37", lambda s, a, b, t: recus.append((s, a, b)))
        self.assertIsNotNone(port)
        self.addCleanup(port.close)
        self.faux.court(NOTE_ON, 60, 100)
        self.assertEqual(recus, [(NOTE_ON, 60, 100)])
        self.assertEqual(port.poll(), [])


class TestUneSortieDuHubSeFermeSansBruit(unittest.TestCase):
    """Le hub relâche lui-même ce qu'il a fait passer : fermer sa sortie
    n'envoie pas seize « silence » et une remise à zéro au DAW."""

    def test_reset_on_close(self):
        if midiport.ctypes is None:
            self.skipTest("ctypes de Windows absent")

        class Sortie:
            def __init__(self):
                self.appels = []

            def midiOutOpen(self, poignee, *_a):                 # noqa: N802
                poignee._obj.value = 77
                return 0

            def midiOutShortMsg(self, _h, message):              # noqa: N802
                self.appels.append(message & 0xFF)
                return 0

            def midiOutReset(self, _h):                          # noqa: N802
                self.appels.append("reset")
                return 0

            def midiOutClose(self, _h):                          # noqa: N802
                self.appels.append("close")
                return 0

        faux = Sortie()
        vrai, midiport._winmm = midiport._winmm, faux
        self.addCleanup(setattr, midiport, "_winmm", vrai)
        port = midiport.MidiOut(reset_on_close=False)
        self.assertTrue(port.open(midiport.MidiDevice(0, "loopMIDI", "out")))
        port.send(NOTE_ON, 60, 100)
        port.close()
        self.assertEqual(faux.appels, [NOTE_ON, "close"])


if __name__ == "__main__":
    unittest.main()
