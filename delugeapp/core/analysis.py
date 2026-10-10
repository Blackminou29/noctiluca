# -*- coding: utf-8 -*-
"""Analyse acoustique des échantillons — numpy seul.

Ce module répond aux questions qu'un producteur se pose devant un dossier
d'échantillons : à quel tempo tourne cette boucle, dans quelle tonalité est ce
accord, ce kick est-il vraiment un kick, ce fichier est-il écrêté ou muet.

Tout est calculé à la transformée de Fourier (:func:`numpy.fft.rfft`) sur des
fenêtres de Hann de 2048 points avec un pas de 512 (cf. SPEC §4.10). Aucun
signal de plus de :data:`MAX_SECONDS` n'est traité : au-delà, le fichier est
sous-échantillonné, ce qui garde l'analyse d'une carte entière dans des durées
acceptables sans rien changer aux résultats.

Aucune fonction ne lève : un signal vide ou absurde donne une valeur neutre.

**Ce que ces mesures valent, vérifié sur la carte de l'utilisateur :**

* :func:`detect_bpm` — exact à 2,5 BPM près sur 14 tempos de référence entre
  70 et 180 BPM, et sur les fichiers de la carte réellement nommés d'après
  leur tempo (``DRUMS 130`` -> 129,2 BPM, 13 des 16 ``*-NoKS-120`` -> 120,2).
  En revanche, **un son tenu n'a pas de tempo** : sur une nappe ou une note
  isolée de multi-échantillon, la fonction renvoie une valeur plausible mais
  arbitraire. C'est pourquoi ``core.scan`` n'enregistre un tempo qu'au-delà
  de 4 secondes et d'un seuil de confiance.
* :func:`detect_key` — retrouve les 12 tonalités majeures et mineures d'essai,
  y compris la distinction entre une majeure et sa relative mineure, qui est la
  vraie difficulté de l'exercice : elles ont les mêmes notes et seule une
  tonique nettement posée les sépare. Un morceau modal ou atonal donne une
  confiance basse — c'est le signal qu'il ne faut pas s'y fier.
* :func:`estimate_root_note` — classe de hauteur correcte sur **92 %** des
  1 026 échantillons de la carte dont le nom indique la note. L'octave, elle,
  dépend de la convention de la banque : ``Bassoon`` et ``Cello`` nomment
  leurs fichiers une octave au-dessus de la notation scientifique, là où
  ``Church Organ`` la respecte.
* :func:`classify_drum` — **95 %** d'accord avec le classement manuel des
  254 percussions de la carte.
"""

from __future__ import annotations

import logging
import re

import numpy as np

log = logging.getLogger(__name__)

#: Taille de fenêtre et pas de l'analyse spectrale.
FRAME = 2048
HOP = 512

#: Fenêtre dédiée à l'analyse de hauteur, volontairement plus longue.
#:
#: La SPEC prescrit 2048 points, ce qui convient au flux spectral et aux
#: descripteurs, mais **pas** au rattachement des bins à une classe de
#: hauteur : à 44,1 kHz, un bin de 2048 points couvre 21,5 Hz, soit
#: **2,6 demi-tons à Do2 et 4,9 demi-tons à Do1**. Une basse voyait donc son
#: énergie répartie au hasard entre plusieurs notes, et la détection de
#: tonalité répondait « F » pour trois tonalités différentes. À 8192 points,
#: un bin vaut 0,7 demi-ton à Do2 : c'est exploitable.
#: Fenêtre longue préférée, et repli pour les signaux trop courts. À 16384
#: points, un bin vaut 0,70 demi-ton à Do1 et 0,35 à Do2 : la basse devient
#: analysable, ce qui compte beaucoup en musique électronique où c'est
#: justement elle qui porte la tonique.
FRAME_CHROMA = 16384
FRAME_CHROMA_MIN = 8192
HOP_CHROMA = 4096

#: Bornes de l'analyse de hauteur. 65 Hz (Do1) couvre les basses ; au-dessus
#: de 3 kHz l'énergie est surtout faite d'harmoniques qui brouillent les
#: classes de hauteur.
CHROMA_LO_HZ = 65.0
CHROMA_HI_HZ = 3000.0

#: Durée maximale analysée, en secondes.
MAX_SECONDS = 30.0

#: Noms de notes, en français et en anglais.
NOTE_FR = ("Do", "Do#", "Ré", "Ré#", "Mi", "Fa", "Fa#",
           "Sol", "Sol#", "La", "La#", "Si")
NOTE_EN = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")

#: Profils de tonalité de Krumhansl-Schmuckler, pour la corrélation du
#: chromagramme. Ce sont les poids perceptifs mesurés de chaque degré.
KS_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09,
                     2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KS_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53,
                     2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

#: Fréquence de référence du la 440 et sa note MIDI.
A4_HZ = 440.0
A4_MIDI = 69

#: Catégories de percussions du Deluge (cf. SPEC §1.1).
DRUM_CATEGORIES = (
    "Kick", "Snare", "HatC", "HatO", "Clap", "Rim", "TomH", "TomM", "TomL",
    "Crash", "Ride", "China", "Cowbell", "Block", "Claves", "ConH", "ConM",
    "ConL", "Guiro", "Shaker", "Tambourine", "Timpany", "Other",
)

#: Indices de reconnaissance par le nom de fichier. L'ordre compte : les
#: libellés les plus spécifiques sont testés d'abord, pour que « open hat »
#: ne soit pas pris pour un « hat » fermé.
#:
#: Ne JAMAIS y mettre un nom de machine (« 808 », « 909 », « linndrum ») : les
#: banques nomment leurs fichiers « 808 Clap », « 808 Cowbell », « 808 Conga
#: low »… Un tel indice rattachait toute la boîte à rythmes à la grosse
#: caisse — c'était 4 des erreurs de classement mesurées sur cette carte.
_NAME_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Kick", ("kick", "bassdrum", "bass drum", "kik", " bd", "bd ")),
    ("Rim", ("rimshot", "rim shot", "rim")),
    ("Snare", ("snare", "snr", " sd", "sd ")),
    ("Clap", ("clap", "handclap")),
    ("Crash", ("crash", "cymbal")),
    ("Ride", ("ride",)),
    ("China", ("china", "splash")),
    ("Cowbell", ("cowbell", "cow bell")),
    ("Claves", ("clave",)),
    ("Block", ("block", "woodblock", "agogo", "agog")),
    ("Shaker", ("shaker", "maraca", "cabasa")),
    ("Tambourine", ("tambourine", "tamb")),
    ("Guiro", ("guiro",)),
    ("Timpany", ("timpani", "timpany", "timp")),
    ("Cowbell", ("bell",)),
)

#: Familles à registre : la catégorie dépend d'un mot de hauteur.
_REGISTER_FAMILIES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("conga", "bongo"), "Con"),
    (("tom",), "Tom"),
)

#: Mots indiquant le registre. Les expressions sont ancrées sur des limites de
#: mot : un chiffre nu ne doit jamais servir d'indice, sinon « DDD1 Tom low »
#: et « R100 Conga low » sont lus comme aigus à cause du nom de la machine.
#: Un chiffre n'est accepté qu'accolé au nom de la famille (« Tom 1 »).
_REGISTER_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("H", (r"extra\s+high", r"very\s+high", r"high", r"\bhi\b", r"\bhaut\b")),
    ("L", (r"extra\s+low", r"very\s+low", r"\blow\b", r"\blo\b", r"\bfloor\b",
           r"\bbas\b")),
    ("M", (r"\bmedium\b", r"\bmid\b", r"\bmoyen\b")),
)

#: Numérotation accolée à la famille : « tom 1 » = aigu, « tom 3 » = grave.
_REGISTER_DIGITS = {"1": "H", "2": "M", "3": "L", "4": "L"}

#: Modificateurs d'ouverture d'un charleston.
_OPEN_HINTS = (r"\bopen\w*\b", r"\bouvert\w*\b", r"\bhho\b")
_CLOSED_HINTS = (r"\bclosed?\w*\b", r"\bferm\w*\b", r"\bhhc\b", r"\btight\b")

#: Familles de charleston, pour la détection ouvert/fermé.
_HAT_FAMILY = (r"hi\s*hat", r"\bhihat\b", r"\bhat\b", r"\bhh\b", r"\bhats\b")


def _matches(text: str, patterns: tuple[str, ...]) -> bool:
    """Vrai si l'une des expressions apparaît dans ``text``."""
    return any(re.search(p, text) for p in patterns)


def _hat_category(text: str) -> str:
    """``HatO``/``HatC`` pour un charleston, ou ``''`` si ce n'en est pas un.

    Le modificateur est cherché séparément de la famille : les fichiers
    réels s'appellent « 808 Open hihat », et non « open hat ». Énumérer les
    combinaisons faisait manquer les 15 charlestons ouverts de cette carte.
    """
    if not _matches(text, _HAT_FAMILY):
        return ""
    if _matches(text, _OPEN_HINTS):
        return "HatO"
    if _matches(text, _CLOSED_HINTS):
        return "HatC"
    return "HatC"       # un charleston non qualifié est fermé


def _register_category(text: str) -> str:
    """Catégorie d'une percussion à registre (conga, tom), ou ``''``.

    Reconnaît « 808 Conga low », « Linndrum Conga extra high », « Tom 2 »…
    en séparant la famille du mot de hauteur, plutôt qu'en énumérant toutes
    les combinaisons.
    """
    for needles, prefix in _REGISTER_FAMILIES:
        family = next((n for n in needles if n in text), None)
        if family is None:
            continue
        for suffix, patterns in _REGISTER_HINTS:
            if _matches(text, patterns):
                return prefix + suffix
        # Chiffre accolé à la famille : « tom 1 », « conga2 ».
        digit = re.search(rf"{family}\s*([1-4])\b", text)
        if digit:
            return prefix + _REGISTER_DIGITS[digit.group(1)]
        return prefix + "M"      # famille reconnue, hauteur muette
    return ""


# --------------------------------------------------------------------------- #
# Préparation du signal
# --------------------------------------------------------------------------- #

def _mono(data: np.ndarray) -> np.ndarray:
    """Ramène un signal à un seul canal, en float32."""
    arr = np.asarray(data)
    if arr.ndim > 1:
        arr = arr.mean(axis=1)
    return np.nan_to_num(arr.astype(np.float32, copy=False))


def _prepare(data: np.ndarray, sr: int) -> tuple[np.ndarray, int]:
    """Signal mono, borné à :data:`MAX_SECONDS`, sous-échantillonné au besoin.

    Le sous-échantillonnage est une simple décimation : pour une détection de
    tempo ou de tonalité, l'aliasing introduit est sans conséquence, et cela
    évite de filtrer 8 000 fichiers inutilement.
    """
    arr = _mono(data)
    if arr.size == 0 or sr <= 0:
        return arr, max(int(sr), 1)
    limit = int(MAX_SECONDS * sr)
    if arr.size > limit:
        arr = arr[:limit]
    # Au-delà de 48 kHz, on décime : l'information utile est en dessous.
    if sr > 48000:
        step = int(sr // 24000) or 1
        arr = arr[::step]
        sr = int(sr // step)
    return arr, sr


def _stft_magnitude(arr: np.ndarray) -> np.ndarray:
    """Module de la transformée à court terme : tableau ``(trames, bins)``."""
    if arr.size < FRAME:
        padded = np.zeros(FRAME, dtype=np.float32)
        padded[:arr.size] = arr
        arr = padded
    n_frames = 1 + (arr.size - FRAME) // HOP
    if n_frames < 1:
        return np.zeros((1, FRAME // 2 + 1), dtype=np.float32)
    window = np.hanning(FRAME).astype(np.float32)
    # Vue glissante : évite de recopier le signal pour chaque trame.
    idx = np.arange(n_frames)[:, None] * HOP + np.arange(FRAME)[None, :]
    frames = arr[idx] * window
    return np.abs(np.fft.rfft(frames, axis=1)).astype(np.float32)


def _onset_envelope(arr: np.ndarray) -> np.ndarray:
    """Enveloppe d'attaque par flux spectral (différences positives)."""
    mag = _stft_magnitude(arr)
    if mag.shape[0] < 2:
        return np.zeros(1, dtype=np.float32)
    # Compression logarithmique : rapproche la perception et stabilise le flux.
    logmag = np.log1p(mag * 10.0)
    flux = np.diff(logmag, axis=0)
    env = np.sum(np.maximum(flux, 0.0), axis=1)
    peak = float(np.max(env)) if env.size else 0.0
    return (env / peak).astype(np.float32) if peak > 0 else env.astype(np.float32)


def _db(value: float) -> float:
    """Décibels pleine échelle, plancher à -120 dB."""
    return 20.0 * float(np.log10(value)) if value > 1e-6 else -120.0


# --------------------------------------------------------------------------- #
# Tempo
# --------------------------------------------------------------------------- #

def detect_bpm(data: np.ndarray, sr: int, lo: float = 60,
               hi: float = 200) -> tuple[float, float]:
    """Tempo estimé et confiance (0 à 1).

    Flux spectral puis autocorrélation de l'enveloppe d'attaque. Les
    sous-multiples et multiples (moitié, double, tiers) sont repliés dans
    l'intervalle ``[lo, hi]``, parce qu'une boucle à 85 BPM et la même à
    170 BPM ont la même autocorrélation : on retient celle qui tombe dans
    l'intervalle demandé.

    Retourne ``(0.0, 0.0)`` si le signal ne permet rien d'affirmer.
    """
    try:
        arr, sr = _prepare(data, sr)
        if arr.size < FRAME * 4:
            return 0.0, 0.0
        env = _onset_envelope(arr)
        if env.size < 8 or float(np.max(env)) <= 0:
            return 0.0, 0.0

        env = env - float(np.mean(env))
        corr = np.correlate(env, env, mode="full")[env.size - 1:]
        if corr.size < 4 or corr[0] <= 0:
            return 0.0, 0.0
        corr = corr / corr[0]

        fps = sr / float(HOP)           # trames par seconde
        lag_min = max(2, int(round(fps * 60.0 / float(hi))))
        lag_max = min(corr.size - 1, int(round(fps * 60.0 / float(lo))))
        if lag_max <= lag_min:
            return 0.0, 0.0

        window = corr[lag_min:lag_max + 1]
        best = int(np.argmax(window)) + lag_min
        strength = float(window[int(np.argmax(window))])
        if strength <= 0:
            return 0.0, 0.0

        raw_bpm = 60.0 * fps / float(best)

        # Lever l'ambiguïté d'octave rythmique. L'autocorrélation d'une mesure
        # à 128 BPM culmine aussi bien à 64 BPM (un pic tous les deux temps) :
        # retenir la première valeur tombant dans l'intervalle donnait 64.
        # On note donc chaque candidat par le soutien réel de
        # l'autocorrélation à son propre décalage, pondéré par la
        # vraisemblance perceptive du tempo (les auditeurs ramènent
        # spontanément un tempo autour de 120 BPM).
        def support(bpm_value: float) -> float:
            lag = 60.0 * fps / bpm_value
            i = int(round(lag))
            if not lag_min <= i <= lag_max:
                return 0.0
            return float(corr[i])

        def plausibility(bpm_value: float) -> float:
            # Cloche large centrée sur 120 BPM (une octave d'écart ~ 0,5).
            return float(np.exp(-0.5 * (np.log2(bpm_value / 120.0) ** 2) / 0.36))

        candidates: dict[float, float] = {}
        for factor in (1.0, 2.0, 0.5, 4.0, 0.25, 3.0, 1.0 / 3.0, 1.5, 2.0 / 3.0):
            value = raw_bpm * factor
            if lo <= value <= hi:
                candidates[round(value, 2)] = support(value) * plausibility(value)
        if not candidates:
            return 0.0, 0.0
        bpm = max(candidates, key=lambda k: candidates[k])

        # Confiance : hauteur du pic rapportée à l'agitation moyenne.
        spread = float(np.mean(np.abs(window)))
        confidence = (0.0 if spread <= 0 else
                      min(1.0, max(0.0, (strength - spread) / (1.0 - spread + 1e-9))))
        return round(float(bpm), 2), round(confidence, 3)
    except (ValueError, FloatingPointError, MemoryError) as exc:
        log.debug("détection de tempo impossible : %s", exc)
        return 0.0, 0.0


def transients(data: np.ndarray, sr: int,
               sensitivity: float = 1.0) -> np.ndarray:
    """Positions des attaques, en numéro d'échantillon.

    ``sensitivity`` au-dessus de 1 détecte davantage d'attaques, en dessous
    moins. Sert à découper une boucle ou à placer des points de bouclage.
    """
    try:
        arr, sr2 = _prepare(data, sr)
        if arr.size < FRAME * 2:
            return np.zeros(0, dtype=np.int64)
        env = _onset_envelope(arr)
        if env.size < 3:
            return np.zeros(0, dtype=np.int64)

        # Seuil adaptatif : moyenne glissante de l'enveloppe.
        width = max(3, int(env.size * 0.02) | 1)
        kernel = np.ones(width, dtype=np.float32) / width
        local = np.convolve(env, kernel, mode="same")
        sens = max(0.05, float(sensitivity))
        threshold = local + (float(np.std(env)) * 0.5 / sens)

        hits: list[int] = []
        min_gap = max(1, int(0.03 * sr2 / HOP))     # 30 ms d'écart minimal
        last = -min_gap - 1
        for i in range(1, env.size - 1):
            if (env[i] > threshold[i] and env[i] >= env[i - 1]
                    and env[i] > env[i + 1] and i - last > min_gap):
                hits.append(i)
                last = i
        # Retour dans l'échelle du signal d'origine.
        ratio = sr / float(sr2) if sr2 else 1.0
        return (np.asarray(hits, dtype=np.int64) * HOP * ratio).astype(np.int64)
    except (ValueError, MemoryError) as exc:
        log.debug("détection des attaques impossible : %s", exc)
        return np.zeros(0, dtype=np.int64)


# --------------------------------------------------------------------------- #
# Hauteur et tonalité
# --------------------------------------------------------------------------- #

def chromagram(data: np.ndarray, sr: int) -> np.ndarray:
    """Énergie par classe de hauteur : tableau de 12 valeurs, somme = 1.

    Utilise la fenêtre longue :data:`FRAME_CHROMA`, indispensable pour que le
    rattachement d'un bin à un demi-ton ait un sens (voir le commentaire de
    cette constante).

    Deux précautions qui changent beaucoup le résultat :

    * seuls les bins proches d'un centre de demi-ton comptent, pondérés par
      leur écart — un bin à mi-chemin entre deux notes n'apporte que du bruit ;
    * seuls les **pics** du spectre sont retenus, pas tout le plancher : le
      bruit de fond d'un enregistrement se répartit sur les douze classes et
      noie la tonalité.
    """
    out = np.zeros(12, dtype=np.float64)
    try:
        arr, sr = _prepare(data, sr)
        if arr.size < FRAME_CHROMA_MIN // 2 or sr <= 0:
            return out

        # Fenêtre la plus longue que le signal permet : la résolution en
        # hauteur en dépend directement.
        frame = FRAME_CHROMA if arr.size >= FRAME_CHROMA else FRAME_CHROMA_MIN
        window = np.hanning(frame).astype(np.float32)
        spectra = []
        for start in range(0, max(1, arr.size - frame + 1), HOP_CHROMA):
            block = arr[start:start + frame]
            if block.size < frame:
                break
            spectra.append(np.abs(np.fft.rfft(block * window)))
        if not spectra:
            padded = np.zeros(frame, dtype=np.float32)
            chunk = arr[:frame]
            padded[:chunk.size] = chunk
            spectra = [np.abs(np.fft.rfft(padded * window))]
        spectrum = np.mean(np.asarray(spectra), axis=0).astype(np.float64)
        freqs = np.fft.rfftfreq(frame, d=1.0 / sr)

        keep = ((freqs >= CHROMA_LO_HZ) & (freqs <= CHROMA_HI_HZ)
                & (spectrum > 0))
        if not np.any(keep):
            return out

        # Ne garder que les pics locaux : un maximum par partiel.
        peaks = np.zeros_like(keep)
        inner = spectrum[1:-1]
        peaks[1:-1] = (inner >= spectrum[:-2]) & (inner > spectrum[2:])
        keep &= peaks
        if not np.any(keep):
            return out

        f = freqs[keep]
        energy = spectrum[keep]
        # Les pics très faibles sont du bruit : seuil relatif au plus fort.
        threshold = float(energy.max()) * 0.02
        strong = energy >= threshold
        f, energy = f[strong], energy[strong]
        if f.size == 0:
            return out

        midi = 12.0 * np.log2(f / A4_HZ) + A4_MIDI
        nearest = np.rint(midi)
        # Écart au centre du demi-ton, dans [0, 0.5] ; au-delà de 0,3 on jette.
        deviation = np.abs(midi - nearest)
        usable = deviation <= 0.3
        if not np.any(usable):
            return out
        weight = np.cos(np.pi * deviation[usable]) ** 2
        classes = nearest[usable].astype(np.int64) % 12
        np.add.at(out, classes, energy[usable] * weight)

        total = float(out.sum())
        return out / total if total > 0 else out
    except (ValueError, FloatingPointError, MemoryError) as exc:
        log.debug("chromagramme impossible : %s", exc)
        return out


def detect_key(data: np.ndarray, sr: int) -> tuple[str, float]:
    """Tonalité estimée et confiance (0 à 1).

    Corrélation du chromagramme aux 24 profils de Krumhansl-Schmuckler
    (12 majeurs, 12 mineurs). Le mineur est suffixé ``m`` : ``'C#m'``.
    La confiance est l'écart relatif entre le meilleur profil et le suivant,
    ce qui est plus parlant que la corrélation brute : un signal atonal donne
    des corrélations proches, donc une confiance faible.
    """
    try:
        chroma = chromagram(data, sr)
        if float(chroma.sum()) <= 0:
            return "", 0.0

        scores: list[tuple[float, str]] = []
        for tonic in range(12):
            for profile, suffix in ((KS_MAJOR, ""), (KS_MINOR, "m")):
                rotated = np.roll(profile, tonic)
                a = chroma - chroma.mean()
                b = rotated - rotated.mean()
                denom = float(np.linalg.norm(a) * np.linalg.norm(b))
                score = float(np.dot(a, b) / denom) if denom > 0 else 0.0
                scores.append((score, f"{NOTE_EN[tonic]}{suffix}"))

        scores.sort(reverse=True)
        best, name = scores[0]
        runner_up = scores[1][0] if len(scores) > 1 else 0.0
        if best <= 0:
            return "", 0.0
        confidence = min(1.0, max(0.0, (best - runner_up) / (abs(best) + 1e-9)))
        # Une corrélation franche compte autant que l'écart au suivant.
        confidence = min(1.0, 0.5 * confidence + 0.5 * max(0.0, best))
        return name, round(confidence, 3)
    except (ValueError, FloatingPointError) as exc:
        log.debug("détection de tonalité impossible : %s", exc)
        return "", 0.0


def estimate_root_note(data: np.ndarray, sr: int) -> int | None:
    """Note MIDI de la fondamentale, ou ``None`` si indéterminable.

    Autocorrélation du signal, qui résiste mieux qu'un simple pic spectral aux
    sons dont l'harmonique est plus forte que la fondamentale — cas courant
    des basses et des pianos échantillonnés.
    """
    try:
        arr, sr = _prepare(data, sr)
        if arr.size < 2048 or sr <= 0:
            return None
        # On travaille sur la portion la plus énergique (après l'attaque).
        start, end = silence_bounds(arr, -50.0)
        segment = arr[start:end] if end > start + 2048 else arr
        segment = segment[:sr * 2]
        if segment.size < 2048:
            return None
        segment = segment - float(np.mean(segment))

        corr = np.correlate(segment, segment, mode="full")[segment.size - 1:]
        if corr.size < 4 or corr[0] <= 0:
            return None
        corr = corr / corr[0]

        # Intervalle de recherche : 27,5 Hz (La0) à 4186 Hz (Do8).
        lag_min = max(2, int(sr / 4186.0))
        lag_max = min(corr.size - 1, int(sr / 27.5))
        if lag_max <= lag_min:
            return None
        window = corr[lag_min:lag_max + 1]
        best = int(np.argmax(window))
        if float(window[best]) < 0.25:       # trop peu périodique : bruit
            return None
        freq = sr / float(best + lag_min)
        if not 20.0 <= freq <= 5000.0:
            return None
        midi = int(round(12.0 * np.log2(freq / A4_HZ) + A4_MIDI))
        return midi if 0 <= midi <= 127 else None
    except (ValueError, FloatingPointError, ZeroDivisionError) as exc:
        log.debug("estimation de la fondamentale impossible : %s", exc)
        return None


def note_name(midi: int, french: bool = True) -> str:
    """Nom d'une note MIDI : ``60`` -> ``'Do3'`` en français, ``'C3'`` sinon."""
    try:
        value = int(midi)
    except (TypeError, ValueError):
        return ""
    names = NOTE_FR if french else NOTE_EN
    return f"{names[value % 12]}{value // 12 - 2}"


# --------------------------------------------------------------------------- #
# Niveaux
# --------------------------------------------------------------------------- #

def loudness(data: np.ndarray) -> dict:
    """Mesures de niveau d'un échantillon.

    * ``peak_db`` — crête numérique ;
    * ``true_peak_db`` — crête après suréchantillonnage ×4, qui révèle les
      dépassements entre deux échantillons (un fichier peut afficher 0 dB et
      saturer à la lecture) ;
    * ``rms_db`` — niveau efficace ;
    * ``crest`` — rapport crête/RMS : élevé pour une percussion, faible pour
      un son compressé ou saturé ;
    * ``dc_offset`` — composante continue, qui gaspille de la dynamique ;
    * ``clipped`` — proportion d'échantillons à pleine échelle.
    """
    out = {"peak_db": -120.0, "true_peak_db": -120.0, "rms_db": -120.0,
           "crest": 0.0, "dc_offset": 0.0, "clipped": 0.0}
    try:
        arr = _mono(data)
        if arr.size == 0:
            return out
        peak = float(np.max(np.abs(arr)))
        rms = float(np.sqrt(np.mean(np.square(arr, dtype=np.float64))))
        out["peak_db"] = _db(peak)
        out["rms_db"] = _db(rms)
        out["crest"] = round(peak / rms, 3) if rms > 1e-9 else 0.0
        out["dc_offset"] = round(float(np.mean(arr, dtype=np.float64)), 6)
        out["clipped"] = round(float(np.mean(np.abs(arr) >= 0.9995)), 6)

        # Crête réelle : interpolation ×4 par zéro-padding spectral.
        chunk = arr[:min(arr.size, 1 << 18)]
        if chunk.size >= 16:
            spec = np.fft.rfft(chunk)
            up = np.fft.irfft(spec, n=chunk.size * 4) * 4.0
            out["true_peak_db"] = _db(float(np.max(np.abs(up))))
        else:
            out["true_peak_db"] = out["peak_db"]
        return out
    except (ValueError, FloatingPointError, MemoryError) as exc:
        log.debug("mesure de niveau impossible : %s", exc)
        return out


def silence_bounds(data: np.ndarray,
                   threshold_db: float = -60.0) -> tuple[int, int]:
    """Premier et dernier échantillon au-dessus du seuil.

    Retourne ``(0, 0)`` pour un signal entièrement sous le seuil — ce qui est
    la façon de reconnaître un fichier muet.
    """
    try:
        arr = _mono(data)
        if arr.size == 0:
            return 0, 0
        threshold = 10.0 ** (float(threshold_db) / 20.0)
        above = np.nonzero(np.abs(arr) > threshold)[0]
        if above.size == 0:
            return 0, 0
        return int(above[0]), int(above[-1]) + 1
    except (ValueError, MemoryError) as exc:
        log.debug("bornes de silence impossibles : %s", exc)
        return 0, 0


# --------------------------------------------------------------------------- #
# Spectre
# --------------------------------------------------------------------------- #

def spectral(data: np.ndarray, sr: int) -> dict:
    """Descripteurs spectraux moyens.

    * ``centroid`` — centre de gravité du spectre en Hz : la « brillance » ;
    * ``rolloff85`` — fréquence sous laquelle se trouvent 85 % de l'énergie ;
    * ``flatness`` — platitude (0 = très tonal, 1 = bruit blanc) ;
    * ``bandwidth`` — étalement autour du centroïde ;
    * ``low_ratio`` / ``high_ratio`` — part d'énergie sous 200 Hz et au-dessus
      de 5 kHz, qui suffisent à distinguer un kick d'un charleston.
    """
    out = {"centroid": 0.0, "rolloff85": 0.0, "flatness": 0.0,
           "bandwidth": 0.0, "low_ratio": 0.0, "high_ratio": 0.0}
    try:
        arr, sr = _prepare(data, sr)
        if arr.size < FRAME // 2:
            return out
        mag = _stft_magnitude(arr)
        spectrum = np.mean(mag, axis=0).astype(np.float64)
        freqs = np.fft.rfftfreq(FRAME, d=1.0 / sr)
        total = float(spectrum.sum())
        if total <= 0:
            return out

        centroid = float(np.dot(freqs, spectrum) / total)
        out["centroid"] = round(centroid, 1)
        variance = float(np.dot(np.square(freqs - centroid), spectrum) / total)
        out["bandwidth"] = round(float(np.sqrt(max(variance, 0.0))), 1)

        cumulative = np.cumsum(spectrum)
        idx = int(np.searchsorted(cumulative, 0.85 * total))
        out["rolloff85"] = round(float(freqs[min(idx, freqs.size - 1)]), 1)

        positive = spectrum[spectrum > 0]
        if positive.size:
            geometric = float(np.exp(np.mean(np.log(positive))))
            arithmetic = float(np.mean(positive))
            out["flatness"] = round(geometric / arithmetic, 4) if arithmetic > 0 else 0.0

        out["low_ratio"] = round(float(spectrum[freqs < 200.0].sum() / total), 4)
        out["high_ratio"] = round(float(spectrum[freqs > 5000.0].sum() / total), 4)
        return out
    except (ValueError, FloatingPointError, MemoryError) as exc:
        log.debug("descripteurs spectraux impossibles : %s", exc)
        return out


# --------------------------------------------------------------------------- #
# Classement des percussions
# --------------------------------------------------------------------------- #

def classify_drum(name: str, info: dict, spec: dict) -> str:
    """Catégorie ``SAMPLES/DRUMS`` d'une percussion.

    Le nom du fichier est de loin l'indice le plus fiable : les banques
    d'échantillons nomment leurs fichiers correctement. Il est donc consulté
    d'abord, et le spectre ne sert qu'à départager les fichiers au nom muet
    (``01.wav``, ``smp0042.wav``…).

    :param name: nom du fichier, avec ou sans extension.
    :param info: ``{'duration', 'channels', …}`` — typiquement un
        :class:`~delugeapp.core.wav.AudioInfo` converti en dictionnaire.
    :param spec: sortie de :func:`spectral`.
    """
    text = " " + str(name or "").lower().replace("_", " ").replace("-", " ") + " "
    # Les familles à registre d'abord : « 808 Conga low » doit donner ConL,
    # et non s'arrêter sur un indice plus général.
    hat = _hat_category(text)
    if hat:
        return hat
    register = _register_category(text)
    if register:
        return register
    for category, needles in _NAME_HINTS:
        if any(needle in text for needle in needles):
            return category

    try:
        duration = float(info.get("duration", 0.0) or 0.0)
        centroid = float(spec.get("centroid", 0.0) or 0.0)
        low = float(spec.get("low_ratio", 0.0) or 0.0)
        high = float(spec.get("high_ratio", 0.0) or 0.0)
        flatness = float(spec.get("flatness", 0.0) or 0.0)
    except (TypeError, ValueError, AttributeError):
        return "Other"

    if centroid <= 0:
        return "Other"

    # Beaucoup de grave et peu d'aigu, court : grosse caisse.
    if low > 0.5 and centroid < 300 and duration < 2.0:
        return "Kick"
    # Très aigu et bref : charleston fermé ; plus long : ouvert.
    if high > 0.35 and centroid > 5000:
        return "HatC" if duration < 0.25 else "HatO"
    # Aigu, long, bruité : cymbale.
    if centroid > 4000 and duration > 1.0 and flatness > 0.1:
        return "Crash"
    # Médium bruité et bref : caisse claire ou clap.
    if 700 < centroid < 4000 and duration < 1.0:
        return "Snare" if flatness < 0.25 else "Clap"
    # Grave tonal un peu long : tom.
    if low > 0.3 and centroid < 700:
        return "TomL" if duration > 0.5 else "TomM"
    return "Other"
