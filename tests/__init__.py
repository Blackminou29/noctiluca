# -*- coding: utf-8 -*-
"""Paquet des tests — et, avant tout, le bac à sable qui protège la machine.

**Rien dans la suite ne doit toucher aux réglages réels de l'utilisateur.**
Ce n'est pas une précaution théorique : c'est arrivé trois fois.

* une fois en remplaçant ``sd_path`` par un dossier temporaire, si bien que
  l'application démarrait sur une carte vide ;
* une fois en écrivant dans le registre l'état de la fenêtre, et
  l'utilisateur a démarré sur une navigation repliée en neuf icônes ;
* une fois — la plus grave — en éteignant ``confirm_writes`` et
  ``always_backup_before_write``, les deux filets qui protègent une carte
  contenant des mois de travail.

Les deux premières fois, j'ai corrigé les montages de test un par un. La
troisième a suffi : le garde-fou est maintenant **à l'entrée du paquet**,
avant que ``delugeapp.config`` ne soit importé, donc avant que ses chemins ne
soient calculés. Un test, un montage ou un script oublié ne peut plus écrire
ailleurs qu'ici.

:data:`tests.BAC_A_SABLE` est le dossier ; ``TestDossierDeConfiguration``
vérifie que l'isolement tient réellement, et échoue si quelqu'un retire
ces lignes.
"""

import os
import tempfile
from pathlib import Path

#: Dossier de configuration utilisé par toute la suite.
#:
#: Dans le dossier temporaire du système, pas dans le projet : il contient des
#: index SQLite et des journaux, qui n'ont rien à faire dans le dépôt.
BAC_A_SABLE: Path = Path(tempfile.gettempdir()) / "noctiluca-tests"

try:
    BAC_A_SABLE.mkdir(parents=True, exist_ok=True)
except OSError:                                     # pragma: no cover
    # Si même cela échoue, mieux vaut un échec de test qu'une écriture chez
    # l'utilisateur : on pose quand même la variable.
    pass

# Affectation inconditionnelle, et non ``setdefault`` : une variable héritée
# de l'environnement pourrait désigner le dossier réel, ce qui annulerait la
# protection — c'est précisément ce qu'il faut rendre impossible.
os.environ["NOCTILUCA_CONFIG"] = str(BAC_A_SABLE)
# L'ancienne variable, que l'application lit encore : retirée, pour que les
# tests qui ôtent la nouvelle voient bien un démarrage sans rien d'imposé.
os.environ.pop("DELUGE_COMPANION_CONFIG", None)
