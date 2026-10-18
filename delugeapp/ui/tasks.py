# -*- coding: utf-8 -*-
"""Exécution de travaux longs hors du fil de l'interface.

L'analyse d'une carte (1 700 échantillons et 1 000 XML) prend plusieurs
dizaines de secondes : elle ne doit jamais bloquer la boucle Qt (cf. SPEC §0.6
et §6.2). Ce module fournit :

* :class:`Worker` — enveloppe une fonction quelconque dans un objet à signaux ;
* :func:`run_task` — la lance dans un :class:`QThread` et branche l'affichage
  de la progression, dans la barre d'état ou dans une boîte modale.

La fonction appelée reçoit automatiquement les mots-clés ``progress`` et
``should_stop`` **si sa signature les accepte**, ce qui évite d'imposer une
signature unique à tous les services du noyau.
"""

from __future__ import annotations

import inspect
import logging
import traceback
from typing import Any, Callable

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication, QProgressDialog

log = logging.getLogger(__name__)

#: Fils de travail en cours, pour pouvoir les arrêter à la fermeture.
#:
#: Un ``QThread`` encore en train de tourner quand l'interpréteur se termine
#: fait **planter le processus** : vérifié, le programme meurt pendant la
#: destruction des objets Qt. La fenêtre principale doit donc appeler
#: :func:`stop_all` avant de rendre la main, et c'est ce registre qui le
#: permet.
_ACTIVE: "list[tuple[QThread, Worker]]" = []


def active_count() -> int:
    """Nombre de travaux encore en cours."""
    return len(_ACTIVE)


def stop_all(timeout_ms: int = 3000) -> int:
    """Demande l'arrêt de tous les travaux et attend la fin des fils.

    À appeler impérativement avant de quitter l'application. Retourne le
    nombre de fils qui n'ont pas répondu dans le délai : ils sont alors
    terminés de force, ce qui vaut mieux qu'un plantage à la sortie.
    """
    pending = list(_ACTIVE)
    for _thread, worker in pending:
        try:
            worker.cancel()
        except RuntimeError:
            pass

    stubborn = 0
    for thread, _worker in pending:
        try:
            thread.quit()
            if not thread.wait(int(timeout_ms)):
                log.warning("fil de travail non terminé : arrêt forcé")
                thread.terminate()
                thread.wait(500)
                stubborn += 1
        except RuntimeError:
            # Le fil a déjà été détruit par Qt : rien à faire.
            pass
    _ACTIVE.clear()
    return stubborn


class Worker(QObject):
    """Porte une fonction à exécuter dans un fil secondaire.

    Les trois signaux sont émis depuis le fil de travail ; Qt les acheminera
    vers le fil de l'interface, les connexions étant automatiquement en file
    d'attente entre fils différents.
    """

    #: Objet de progression transmis tel quel par la fonction appelée.
    progress = pyqtSignal(object)
    #: Valeur de retour de la fonction.
    finished = pyqtSignal(object)
    #: Message d'erreur en français, si la fonction a levé.
    failed = pyqtSignal(str)

    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = dict(kwargs)
        self._cancelled = False

    # -- annulation -------------------------------------------------------- #

    def cancel(self) -> None:
        """Demande l'arrêt. La fonction appelée doit consulter ``should_stop``."""
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        """Vrai si l'annulation a été demandée."""
        return self._cancelled

    # -- exécution --------------------------------------------------------- #

    def _supported_extras(self) -> dict[str, Any]:
        """Mots-clés ``progress``/``should_stop`` acceptés par la fonction.

        Une fonction munie de ``**kwargs`` les accepte tous les deux.
        """
        extras: dict[str, Any] = {}
        try:
            sig = inspect.signature(self._fn)
        except (TypeError, ValueError):
            return extras
        params = sig.parameters
        accepts_any = any(p.kind is inspect.Parameter.VAR_KEYWORD
                          for p in params.values())
        if accepts_any or "progress" in params:
            extras["progress"] = self.progress.emit
        if accepts_any or "should_stop" in params:
            extras["should_stop"] = lambda: self._cancelled
        return extras

    def run(self) -> None:
        """Exécute la fonction et émet son résultat ou son erreur.

        Ne laisse **jamais** remonter d'exception : elle atteindrait la boucle
        Qt et ferait tomber l'application (cf. SPEC §6.3).
        """
        try:
            kwargs = dict(self._kwargs)
            for key, value in self._supported_extras().items():
                kwargs.setdefault(key, value)
            result = self._fn(*self._args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - rempart volontaire
            log.exception("échec de la tâche %r", getattr(self._fn, "__name__", self._fn))
            detail = str(exc).strip() or exc.__class__.__name__
            self.failed.emit(detail)
            log.debug("trace complète :\n%s", traceback.format_exc())
        else:
            self.finished.emit(result)


def _status_bar(parent: Any):
    """Barre d'état de la fenêtre contenant ``parent``, ou ``None``."""
    widget = parent
    while widget is not None:
        getter = getattr(widget, "statusBar", None)
        if callable(getter):
            try:
                return getter()
            except (RuntimeError, TypeError):
                return None
        widget = getattr(widget, "parent", lambda: None)()
    return None


def _progress_text(payload: Any, title: str) -> str:
    """Libellé lisible à partir d'un objet de progression quelconque.

    Accepte les ``ScanProgress`` du noyau, les couples ``(fait, total)``, les
    chaînes, ou n'importe quel objet (replié sur ``str``).
    """
    message = getattr(payload, "message", None)
    current = getattr(payload, "current", None)
    total = getattr(payload, "total", None)
    if message is not None:
        if current and total:
            return f"{message} ({current}/{total})"
        return str(message)
    if isinstance(payload, tuple) and len(payload) == 2:
        return f"{title} ({payload[0]}/{payload[1]})"
    if isinstance(payload, str):
        return payload
    return title


def run_task(parent: Any, fn: Callable[..., Any], *args: Any,
             on_result: Callable[[Any], None] | None = None,
             on_progress: Callable[[Any], None] | None = None,
             on_error: Callable[[str], None] | None = None,
             title: str = "Traitement…", modal: bool = False,
             quiet: bool = False, **kwargs: Any) -> Worker:
    """Lance ``fn`` dans un fil secondaire et retourne son :class:`Worker`.

    :param parent: widget d'ancrage — sert à trouver la barre d'état et à
        rattacher la boîte de progression ; le worker lui est rattaché pour
        que Qt ne le détruise pas prématurément.
    :param on_result: appelé dans le fil de l'interface avec la valeur de retour.
    :param on_progress: appelé à chaque progression, en plus de l'affichage.
    :param on_error: appelé avec le message d'erreur ; par défaut, journalisé
        et affiché dans la barre d'état.
    :param modal: ``True`` affiche une :class:`QProgressDialog` annulable
        plutôt qu'un simple message dans la barre d'état.
    :param quiet: un travail de fond que l'utilisateur n'a pas demandé
        (compter ce qui attend le Deluge, comparer la sauvegarde) : rien dans
        la barre d'état — ni pendant, ni l'effacement de la fin, qui
        emportait le message qu'on venait d'y lire.

    Le fil est nettoyé automatiquement à la fin, dans tous les cas.
    """
    worker = Worker(fn, *args, **kwargs)
    thread = QThread(parent)
    worker.moveToThread(thread)

    # Empêche le ramasse-miettes de prendre le worker tant que le fil tourne.
    worker.setParent(None)
    thread._worker = worker  # type: ignore[attr-defined]

    status = None if (modal or quiet) else _status_bar(parent)
    dialog: QProgressDialog | None = None
    if modal:
        dialog = QProgressDialog(title, "Annuler", 0, 0,
                                 parent if hasattr(parent, "window") else None)
        dialog.setWindowTitle(title)
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setMinimumDuration(400)
        dialog.canceled.connect(worker.cancel)

    def _on_progress(payload: Any) -> None:
        """Met à jour l'affichage, puis prévient l'appelant."""
        try:
            text = _progress_text(payload, title)
            current = getattr(payload, "current", None)
            total = getattr(payload, "total", None)
            if dialog is not None:
                dialog.setLabelText(text)
                if isinstance(current, int) and isinstance(total, int) and total > 0:
                    dialog.setMaximum(total)
                    dialog.setValue(current)
            elif status is not None:
                status.showMessage(text)
        except (RuntimeError, TypeError) as exc:
            log.debug("affichage de progression impossible : %s", exc)
        if on_progress is not None:
            try:
                on_progress(payload)
            except Exception:  # noqa: BLE001 - un rappel ne doit rien casser
                log.exception("rappel de progression en échec")

    def _cleanup() -> None:
        """Ferme l'affichage et arrête le fil, quoi qu'il arrive."""
        try:
            if dialog is not None:
                dialog.close()
                dialog.deleteLater()
            elif status is not None:
                status.clearMessage()
        except RuntimeError:
            pass
        thread.quit()

    def _on_finished(result: Any) -> None:
        _cleanup()
        if on_result is not None:
            try:
                on_result(result)
            except Exception:  # noqa: BLE001 - rempart avant la boucle Qt
                log.exception("rappel de résultat en échec")

    def _on_failed(message: str) -> None:
        _cleanup()
        if on_error is not None:
            try:
                on_error(message)
            except Exception:  # noqa: BLE001
                log.exception("rappel d'erreur en échec")
        else:
            log.error("tâche « %s » en échec : %s", title, message)
            if status is not None:
                try:
                    status.showMessage(f"Échec : {message}", 8000)
                except RuntimeError:
                    pass

    def _forget() -> None:
        """Retire le fil du registre : sans cela il fuirait."""
        for entry in list(_ACTIVE):
            if entry[0] is thread:
                _ACTIVE.remove(entry)
                break

    worker.progress.connect(_on_progress)
    worker.finished.connect(_on_finished)
    worker.failed.connect(_on_failed)
    thread.started.connect(worker.run)
    thread.finished.connect(_forget)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)

    _ACTIVE.append((thread, worker))
    thread.start()
    return worker


def process_events() -> None:
    """Laisse l'interface se redessiner pendant une boucle synchrone courte.

    À n'utiliser que pour un traitement bref ; au-delà, passer par
    :func:`run_task`.
    """
    app = QApplication.instance()
    if app is not None:
        app.processEvents()
