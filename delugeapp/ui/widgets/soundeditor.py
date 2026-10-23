# -*- coding: utf-8 -*-
"""L'éditeur de son : chaque réglage, au cran de la machine et en clair.

Un onglet par menu du Deluge — Voix, Oscillateurs, Filtres, Enveloppes,
LFO, Effets, Modulations. Chaque encodeur montre le cran que l'on lit sur la
machine (0 à 50) et, dessous, ce qu'il vaut vraiment selon les lois du
firmware (:mod:`delugeapp.core.soundedit`) : « 1,8 s », « 237 Hz ».

:class:`SoundEditor` modifie le son qu'on lui donne ; :class:`SoundEditorDialog`
travaille sur une copie, et ne la rend qu'à « Garder ce son ».
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...core import soundedit
from ...core.fixedpoint import to_display
from ...i18n import tr
from ..theme import GOLD, PAD
from .common import Card
from .envelope import EnvelopeEditor
from .filtercurve import FilterCurve
from .knob import Knob

log = logging.getLogger(__name__)


def _label(control, index: int | None = None) -> str:
    text = tr(control.label)
    if "%d" in text:
        text = text % (index if index is not None else int(control.key[3]))
    return text


class _KnobControl(QWidget):
    """Un encodeur, et dessous ce que vaut son cran."""

    #: Largeur d'un réglage : « Réduction de fréquence » tient sur deux
    #: lignes. Le libellé dessiné par l'encodeur, lui, était coupé net à
    #: 58 px (« éverbération »).
    WIDTH = 104

    def __init__(self, control, color: str, parent=None) -> None:
        super().__init__(parent)
        self.control = control
        self.setFixedWidth(self.WIDTH)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        self.title = QLabel(_label(control))
        self.title.setAlignment(Qt.AlignmentFlag.AlignHCenter
                                | Qt.AlignmentFlag.AlignBottom)
        self.title.setWordWrap(True)
        # Deux lignes réservées pour tous : un titre long ne décale plus son
        # encodeur sous ceux de la rangée.
        self.title.setFixedHeight(36)
        layout.addWidget(self.title)
        self.knob = Knob("", 0, control.minimum, control.maximum,
                         control.bipolar, color=color)
        self.knob.setToolTip("%s\n\n%s" % (_label(control), tr(control.tip)))
        layout.addWidget(self.knob, 0, Qt.AlignmentFlag.AlignHCenter)
        self.caption = QLabel("")
        self.caption.setProperty("role", "subtitle")
        self.caption.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.caption)


class _ChoiceControl(QWidget):
    """Un choix : un libellé et sa liste."""

    def __init__(self, control, parent=None) -> None:
        super().__init__(parent)
        self.control = control
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        title = QLabel(_label(control))
        title.setProperty("role", "subtitle")
        layout.addWidget(title)
        self.combo = QComboBox()
        self.combo.setToolTip(tr(control.tip))
        for value, label in control.choices:
            self.combo.addItem(tr(label), value)
        layout.addWidget(self.combo)

    def show_value(self, value) -> None:
        index = self.combo.findData(value)
        if index < 0:
            # Une valeur que l'éditeur ne propose pas (un échantillon, une
            # table d'ondes) : montrée telle quelle, gardée si on n'y touche
            # pas.
            self.combo.addItem(str(value), value)
            index = self.combo.count() - 1
        self.combo.blockSignals(True)
        self.combo.setCurrentIndex(index)
        self.combo.blockSignals(False)


class SoundEditor(QWidget):
    """Modifie un son, réglage par réglage (le son donné est modifié)."""

    changed = pyqtSignal()

    def __init__(self, sound, color: str = GOLD, parent=None) -> None:
        super().__init__(parent)
        self._sound = sound
        self._color = color
        self._controls: dict[str, QWidget] = {}
        self._cable_rows: list[dict] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        for section in soundedit.SECTIONS:
            self.tabs.addTab(self._build_section(section), tr(section))
        self.tabs.addTab(self._build_cables(), tr("Modulations"))
        self.refresh()

    # -- construction ------------------------------------------------------- #

    def _scroll(self, inner: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(inner)
        return scroll

    def _build_section(self, section: str) -> QWidget:
        inner = QWidget()
        column = QVBoxLayout(inner)
        column.setContentsMargins(PAD, PAD, PAD, PAD)
        column.setSpacing(PAD)
        controls = soundedit.controls_of(section)
        if section == soundedit.SECTIONS[2]:           # Filtres
            self.filter_curve = FilterCurve()
            self.filter_curve.set_accent(self._color)
            self.filter_curve.setMinimumHeight(130)
            column.addWidget(self.filter_curve)
        if section == soundedit.SECTIONS[3]:           # Enveloppes
            self.envelopes = {}
            row = QHBoxLayout()
            for index in (1, 2):
                editor = EnvelopeEditor(color=self._color, title=(
                    tr("Enveloppe 1 — amplitude") if index == 1
                    else tr("Enveloppe 2 — modulation")))
                editor.changed.connect(
                    lambda values, i=index: self._envelope_dragged(i, values))
                self.envelopes[index] = editor
                row.addWidget(editor, 1)
            column.addLayout(row)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        choices = [c for c in controls if c.kind == "choice"]
        knobs = [c for c in controls if c.kind == "knob"]
        if choices:
            line = QGridLayout()
            line.setHorizontalSpacing(12)
            for index, c in enumerate(choices):
                widget = _ChoiceControl(c)
                widget.combo.currentIndexChanged.connect(
                    lambda _i, key=c.key: self._choice_changed(key))
                self._controls[c.key] = widget
                line.addWidget(widget, index // 4, index % 4)
            column.addLayout(line)
        # Les oscillateurs par rangée : A, puis B, puis le bruit et la FM ;
        # les enveloppes aussi, 1 puis 2 (huit d'affilée débordaient à
        # 720 px, l'enveloppe 2 coupée).
        per_row = {soundedit.SECTIONS[1]: 4, soundedit.SECTIONS[3]: 4}.get(
            section, 6)
        for index, c in enumerate(knobs):
            widget = _KnobControl(c, self._color)
            widget.knob.valueChanged.connect(
                lambda v, key=c.key: self._knob_changed(key, v))
            self._controls[c.key] = widget
            grid.addWidget(widget, index // per_row, index % per_row)
        column.addLayout(grid)
        column.addStretch(1)
        return self._scroll(inner)

    def _build_cables(self) -> QWidget:
        inner = QWidget()
        column = QVBoxLayout(inner)
        column.setContentsMargins(PAD, PAD, PAD, PAD)
        hint = QLabel(tr(
            "Chaque modulation relie une source à un réglage, avec une "
            "profondeur de −50 à +50 comme sur la machine. Sans polarité, la "
            "source va de −1 à +1 : une enveloppe tire le réglage vers le bas "
            "au repos ; unipolaire, elle va de 0 à 1."))
        hint.setProperty("role", "subtitle")
        hint.setWordWrap(True)
        column.addWidget(hint)
        self._cables_box = QVBoxLayout()
        self._cables_box.setSpacing(6)
        column.addLayout(self._cables_box)
        self.add_cable_button = QPushButton(tr("Ajouter une modulation"))
        self.add_cable_button.setToolTip(tr(
            "Une modulation de plus : le LFO 1 sur la coupure, à régler."))
        self.add_cable_button.clicked.connect(self._add_cable)
        line = QHBoxLayout()
        line.addWidget(self.add_cable_button)
        line.addStretch(1)
        column.addLayout(line)
        column.addStretch(1)
        return self._scroll(inner)

    def _cable_row(self, index: int, cable) -> dict:
        from ...core.model import param_of_destination

        host = QWidget()
        line = QHBoxLayout(host)
        line.setContentsMargins(0, 0, 0, 0)
        source = QComboBox()
        for value, label in soundedit.CABLE_SOURCES:
            source.addItem(tr(label), value)
        destination = QComboBox()
        for value, label in soundedit.CABLE_DESTINATIONS:
            destination.addItem(tr(label), value)
        depth = QSpinBox()
        depth.setRange(-50, 50)
        depth.setToolTip(tr("La profondeur, de −50 à +50 comme sur la "
                            "machine."))
        polarity = QComboBox()
        polarity.addItem(tr("Bipolaire"), "")
        polarity.addItem(tr("Unipolaire"), "unipolar")
        polarity.setToolTip(tr("Bipolaire : la source va de −1 à +1 (le "
                               "défaut). Unipolaire : de 0 à 1."))
        effect = QLabel("")
        effect.setProperty("role", "subtitle")
        effect.setMinimumWidth(120)
        remove = QPushButton(tr("Retirer"))
        remove.setToolTip(tr("Retire cette modulation."))

        for combo, value in ((source, cable.source),
                             (destination,
                              param_of_destination(cable.destination))):
            found = combo.findData(value)
            if found < 0:
                combo.addItem(str(value), value)
                found = combo.count() - 1
            combo.setCurrentIndex(found)
        depth.setValue(cable.display())
        polarity.setCurrentIndex(1 if cable.polarity == "unipolar" else 0)
        effect.setText(soundedit.describe_cable(cable))

        # Des listes qui se resserrent : à 720 px, la ligne entière, bouton
        # Retirer compris, sortait de la fenêtre.
        for combo, longueur in ((source, 6), (destination, 7),
                                (polarity, 6)):
            combo.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(longueur)
        depth.setFixedWidth(72)
        effect.setMinimumWidth(96)
        effect.setWordWrap(True)
        for widget in (source, destination, depth, polarity):
            line.addWidget(widget)
        line.addWidget(effect, 1)
        line.addWidget(remove)
        row = {"host": host, "source": source, "destination": destination,
               "depth": depth, "polarity": polarity, "effect": effect,
               "remove": remove}
        source.currentIndexChanged.connect(
            lambda _i, r=row: self._cable_changed(r))
        destination.currentIndexChanged.connect(
            lambda _i, r=row: self._cable_changed(r))
        depth.valueChanged.connect(lambda _v, r=row: self._cable_changed(r))
        polarity.currentIndexChanged.connect(
            lambda _i, r=row: self._cable_changed(r))
        remove.clicked.connect(lambda _c=False, r=row: self._remove_cable(r))
        return row

    # -- état ----------------------------------------------------------------- #

    def sound(self):
        return self._sound

    def set_sound(self, sound) -> None:
        self._sound = sound
        self.refresh()

    def refresh(self) -> None:
        """Montre le son tel qu'il est."""
        sound = self._sound
        for key, widget in self._controls.items():
            widget.setVisible(soundedit.visible(sound, key))
            try:
                current = soundedit.value(sound, key)
            except Exception as exc:  # noqa: BLE001
                log.debug("réglage illisible %s : %s", key, exc)
                continue
            if isinstance(widget, _KnobControl):
                widget.knob.set_value(int(current))
                widget.caption.setText(soundedit.describe(sound, key))
            else:
                widget.show_value(current)
        self._refresh_shapes()
        self._fill_cables()

    def _refresh_shapes(self) -> None:
        sound = self._sound
        if getattr(self, "filter_curve", None) is not None:
            self.filter_curve.set_filter(
                sound.display("lpfFrequency"), sound.display("lpfResonance"),
                sound.lpf_mode)
            hpf = sound.display("hpfFrequency")
            self.filter_curve.set_hpf(
                hpf if hpf > 0 and sound.hpf_mode != "Off" else None)
        for index, editor in getattr(self, "envelopes", {}).items():
            env = getattr(sound, "env%d" % index)
            editor.set_adsr(to_display(env.attack), to_display(env.decay),
                            to_display(env.sustain), to_display(env.release))

    def _fill_cables(self) -> None:
        for row in self._cable_rows:
            row["host"].setParent(None)
            row["host"].deleteLater()
        self._cable_rows = []
        for index, cable in enumerate(self._sound.patch_cables):
            row = self._cable_row(index, cable)
            self._cable_rows.append(row)
            self._cables_box.addWidget(row["host"])

    # -- modifications -------------------------------------------------------- #

    def _knob_changed(self, key: str, new: int) -> None:
        soundedit.set_value(self._sound, key, new)
        widget = self._controls[key]
        widget.caption.setText(soundedit.describe(self._sound, key))
        # Un réglage peut changer la description d'un autre : le désaccord
        # dépend du nombre de voix.
        for other in ("unison.detune", "lfo1Rate", "lfo2Rate", "delayRate"):
            if other != key and other in self._controls:
                self._controls[other].caption.setText(
                    soundedit.describe(self._sound, other))
        self._refresh_shapes()
        self.changed.emit()

    def _choice_changed(self, key: str) -> None:
        widget = self._controls[key]
        soundedit.set_value(self._sound, key, widget.combo.currentData())
        # Changer de moteur montre ou cache des réglages, et peut éteindre
        # les filtres (FM) : tout se remontre.
        self.refresh()
        self.changed.emit()

    def _envelope_dragged(self, index: int, values: dict) -> None:
        for segment, new in values.items():
            key = "env%d.%s" % (index, segment)
            soundedit.set_value(self._sound, key, new)
            widget = self._controls.get(key)
            if widget is not None:
                widget.knob.set_value(int(new))
                widget.caption.setText(soundedit.describe(self._sound, key))
        self.changed.emit()

    def _cable_changed(self, row: dict) -> None:
        index = self._cable_rows.index(row)
        soundedit.set_cable(self._sound, index,
                            source=row["source"].currentData(),
                            destination=row["destination"].currentData(),
                            depth=row["depth"].value(),
                            polarity=row["polarity"].currentData())
        row["effect"].setText(soundedit.describe_cable(
            self._sound.patch_cables[index]))
        self.changed.emit()

    def _add_cable(self) -> None:
        soundedit.add_cable(self._sound)
        self._fill_cables()
        self.changed.emit()

    def _remove_cable(self, row: dict) -> None:
        index = self._cable_rows.index(row)
        soundedit.remove_cable(self._sound, index)
        self._fill_cables()
        self.changed.emit()


class SoundEditorDialog(QDialog):
    """Modifier un son : on travaille sur une copie, rendue à « Garder ce
    son » ; « Annuler » ne touche à rien."""

    def __init__(self, ctx, sound, title: str = "", color: str = GOLD,
                 parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._original = soundedit.copy_sound(sound)
        self._sound = soundedit.copy_sound(sound)
        self.setWindowTitle(title or tr("Modifier le son"))
        self.resize(940, 640)
        self.setMinimumSize(720, 520)

        column = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel(tr("Nom")))
        self.name_edit = QLineEdit(self._sound.name or "")
        self.name_edit.setToolTip(tr("Le nom du son, tel qu'il paraîtra sur "
                                     "le Deluge."))
        top.addWidget(self.name_edit, 1)
        column.addLayout(top)

        self.editor = SoundEditor(self._sound, color=color)
        self.editor.changed.connect(self._changed)
        column.addWidget(self.editor, 1)

        self.summary = QLabel("")
        self.summary.setProperty("role", "subtitle")
        self.summary.setWordWrap(True)
        column.addWidget(self.summary)

        buttons = QHBoxLayout()
        self.listen_button = QPushButton(tr("Écouter"))
        self.listen_button.setToolTip(tr(
            "Joue le son tel qu'il est réglé, calculé par l'ordinateur aux "
            "lois du Deluge."))
        self.listen_button.clicked.connect(self.listen)
        buttons.addWidget(self.listen_button)
        self.live_check = QCheckBox(tr("Écouter en réglant"))
        self.live_check.setToolTip(tr(
            "Rejoue le son un instant après chaque réglage."))
        buttons.addWidget(self.live_check)
        self.reset_button = QPushButton(tr("Revenir au son de départ"))
        self.reset_button.setToolTip(tr(
            "Oublie toutes les modifications faites ici."))
        self.reset_button.clicked.connect(self.reset)
        buttons.addWidget(self.reset_button)
        buttons.addStretch(1)
        self.cancel_button = QPushButton(tr("Annuler"))
        self.cancel_button.setToolTip(tr("Ferme sans rien changer."))
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_button)
        self.keep_button = QPushButton(tr("Garder ce son"))
        self.keep_button.setDefault(True)
        self.keep_button.setToolTip(tr(
            "Garde le son modifié. Rien n'est écrit sur la carte : il le sera "
            "avec le morceau, ou par « Enregistrer dans SYNTHS »."))
        self.keep_button.clicked.connect(self.accept)
        buttons.addWidget(self.keep_button)
        column.addLayout(buttons)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(450)
        self._timer.timeout.connect(self.listen)
        self._changed()

    # -- résultat ------------------------------------------------------------ #

    def edited_sound(self):
        """Le son modifié (son nom compris)."""
        name = self.name_edit.text().strip()
        if name:
            self._sound.name = name
        return self._sound

    def changes(self) -> list[str]:
        return soundedit.differences(self._original, self.edited_sound())

    # -- actions -------------------------------------------------------------- #

    def _changed(self) -> None:
        changes = soundedit.differences(self._original, self._sound)
        if changes:
            shown = changes[:4]
            more = len(changes) - len(shown)
            text = " · ".join(shown)
            if more > 0:
                text += " · " + tr("et %d autre(s)") % more
            self.summary.setText(tr("Modifié : %s") % text)
        else:
            self.summary.setText(tr(
                "Chaque encodeur montre le cran de la machine et, dessous, ce "
                "qu'il vaut sur le Deluge."))
        if self.live_check.isChecked():
            self._timer.start()

    def reset(self) -> None:
        self._sound = soundedit.copy_sound(self._original)
        self.name_edit.setText(self._sound.name or "")
        self.editor.set_sound(self._sound)
        self._changed()

    def listen(self) -> None:
        """Rend le son réglé (fil séparé) puis le joue."""
        from ...core.model import SynthPreset
        from ..tasks import run_task

        player = getattr(self.ctx, "player", None)
        if player is None:
            self.summary.setText(tr("Aucune sortie audio disponible."))
            return
        preset = SynthPreset(name=self._sound.name,
                             sound=soundedit.copy_sound(self._sound))
        sd = self.ctx.sd if getattr(self.ctx, "has_card", False) else None

        def rendre(p, card):
            from ...core import render

            return render.render_preview(p, sr=44100, sd=card)

        run_task(self, rendre, preset, sd, on_result=self._play,
                 title=tr("Rendu du son"), quiet=True)

    def _play(self, audio) -> None:
        player = getattr(self.ctx, "player", None)
        if audio is None or player is None:
            return
        try:
            player.set_volume(self.ctx.settings.preview_volume)
            player.play_array(audio, 44100)
        except Exception as exc:  # noqa: BLE001
            log.debug("lecture impossible : %s", exc)
