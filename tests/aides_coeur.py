# -*- coding: utf-8 -*-
"""Aides partagées entre les fichiers de tests du noyau.

Pas un module de tests (son nom ne commence pas par ``test_``) :
chaque fichier l'importe par son nom, le dossier ``tests/`` ajouté au
chemin, quelle que soit la façon dont la suite est lancée.
"""

from __future__ import annotations

import time
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

from delugeapp.core import wav


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


def _son(chemin, frequence=220.0, duree=0.05, profondeur=16, canaux=1,
         taux=44100):
    """Un son court, écrit par l'écrivain de l'application."""
    t = np.linspace(0, duree, int(taux * duree), endpoint=False)
    signal = (0.5 * np.sin(2 * np.pi * frequence * t)).astype(np.float32)
    if canaux > 1:
        signal = np.stack([signal] * canaux, axis=1)
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    wav.write(chemin, signal, taux, profondeur)
    return chemin


def lire_midi(path: Path) -> dict:
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
