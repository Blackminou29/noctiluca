# -*- coding: utf-8 -*-
"""Des ports MIDI simulés, pour éprouver le hub sans appareil.

Ils tiennent la place de :class:`delugeapp.core.midihub.Backend` : des
claviers qu'on « joue » (:meth:`FauxPorts.jouer`), des sorties qui notent ce
qu'elles reçoivent (:class:`FausseSortie`). Rien ici ne touche à ``winmm``.

Ce module n'importe pas ``delugeapp`` : le module de test qui l'utilise pose
son bac à sable avant.
"""

from __future__ import annotations

import time

NOTE_ON, NOTE_OFF = 0x90, 0x80


class FausseSortie:
    """Une sortie qui note ce qu'on lui envoie."""

    def __init__(self, nom: str) -> None:
        self.nom = nom
        self.recus: list[tuple[int, int, int]] = []
        self.fermee = False
        #: Vrai : chaque envoi lève, comme un pilote qui tombe.
        self.leve = False

    def send(self, status, data1=0, data2=0) -> bool:
        if self.leve:
            raise OSError("pilote tombé")
        if self.fermee:
            return False
        self.recus.append((int(status), int(data1), int(data2)))
        return True

    def close(self) -> None:
        self.fermee = True

    def notes_tenues(self) -> set[tuple[int, int]]:
        """(canal, note) encore enfoncées d'après ce qui est arrivé."""
        tenues: set[tuple[int, int]] = set()
        for statut, note, force in self.recus:
            genre, canal = statut & 0xF0, (statut & 0x0F) + 1
            if genre == NOTE_ON and force > 0:
                tenues.add((canal, note))
            elif genre in (NOTE_ON, NOTE_OFF):
                tenues.discard((canal, note))
        return tenues


class FausseEntree:
    """Une entrée ouverte : ce que le hub a donné pour recevoir ses
    messages."""

    def __init__(self, nom: str, pousser) -> None:
        self.nom = nom
        self.pousser = pousser
        self.fermee = False

    def close(self) -> None:
        self.fermee = True


class FauxPorts:
    """Les ports de la machine, simulés : ce que le hub croit voir."""

    def __init__(self, entrees=(), sorties=()) -> None:
        self.entrees = list(entrees)
        self.sorties = list(sorties)
        self.ouvertes: dict[str, FausseEntree] = {}
        self.sorties_ouvertes: dict[str, FausseSortie] = {}
        #: Nom -> raison d'un refus à l'ouverture.
        self.refus: dict[str, str] = {}
        self.last_error = ""
        self.ouvertures: list[str] = []
        #: Ce que :meth:`deluge_detected` répond : un Deluge au bout du
        #: câble, que le lien n'a pas encore connecté.
        self.deluge_au_bout = False

    def inputs(self):
        return list(self.entrees)

    def outputs(self):
        return list(self.sorties)

    def deluge_detected(self) -> bool:
        return self.deluge_au_bout

    def open_input(self, name, push):
        self.last_error = self.refus.get(name, "")
        if self.last_error or name not in self.entrees:
            return None
        self.ouvertures.append("in:" + name)
        self.ouvertes[name] = FausseEntree(name, push)
        return self.ouvertes[name]

    def open_output(self, name):
        self.last_error = self.refus.get(name, "")
        if self.last_error or name not in self.sorties:
            return None
        self.ouvertures.append("out:" + name)
        self.sorties_ouvertes[name] = FausseSortie(name)
        return self.sorties_ouvertes[name]

    def jouer(self, nom: str, status: int, data1: int = 0,
              data2: int = 0) -> None:
        """Ce que le rappel du pilote ferait à l'arrivée d'un message."""
        self.ouvertes[nom].pousser(status, data1, data2, time.perf_counter())
