"""Détection automatique des personnages: regroupement des voix par réplique."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Sequence

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import pdist, squareform

from . import features
from .asr import Line
from .config import module_available
from .media import read_pcm

ProgressCb = Callable[[float, str], None] | None

MAX_SPEAKERS = 8
_MIN_SPEECH = 0.30          # sous ce seuil, l'extrait est trop court pour être fiable
_ACCEPT_SILHOUETTE = 0.14   # en dessous, on considère qu'il n'y a qu'une seule voix
_RELIABLE_SPEECH = 1.0      # durée minimale pour qu'un extrait puisse fonder un personnage


def _speechbrain_embeddings(audio: Path, lines: Sequence[Line],
                            cb: ProgressCb) -> np.ndarray | None:
    """Empreintes ECAPA-TDNN si speechbrain est installé (meilleure précision)."""
    try:
        import torch
        from speechbrain.inference.speaker import EncoderClassifier

        from .config import CACHE_DIR

        if cb:
            cb(0.05, "Chargement du modèle d'empreintes vocales")
        model = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            savedir=str(CACHE_DIR / "models" / "ecapa"),
            run_opts={"device": "cpu"},
        )
        signal = read_pcm(audio, sr=16000)
        vectors = []
        for idx, line in enumerate(lines):
            chunk = _slice(signal, line, 16000)
            if chunk.size < 16000 * _MIN_SPEECH:
                chunk = np.pad(chunk, (0, int(16000 * _MIN_SPEECH) - chunk.size))
            with torch.no_grad():
                emb = model.encode_batch(torch.from_numpy(chunk[None, :]))
            vectors.append(emb.squeeze().cpu().numpy())
            if cb:
                cb(0.05 + 0.85 * (idx + 1) / max(len(lines), 1), "Analyse des voix")
        return np.vstack(vectors)
    except Exception:
        return None


def _slice(signal: np.ndarray, line: Line, sr: int) -> np.ndarray:
    start = max(int(line.start * sr), 0)
    end = min(int(line.end * sr), signal.size)
    return signal[start:end] if end > start else np.zeros(0, dtype=np.float32)


def _builtin_embeddings(audio: Path, lines: Sequence[Line], cb: ProgressCb) -> np.ndarray:
    signal = read_pcm(audio, sr=features.SR)
    vectors = []
    for idx, line in enumerate(lines):
        vectors.append(features.embed(_slice(signal, line, features.SR)))
        if cb:
            cb(0.1 + 0.8 * (idx + 1) / max(len(lines), 1), "Analyse des voix")
    return np.vstack(vectors) if vectors else np.zeros((0, 1), dtype=np.float32)


def _silhouette(dist: np.ndarray, labels: np.ndarray) -> float:
    """Score de silhouette moyen à partir d'une matrice de distances."""
    uniq = np.unique(labels)
    if uniq.size < 2 or uniq.size >= labels.size:
        return -1.0
    scores = []
    for i in range(labels.size):
        same = labels == labels[i]
        same[i] = False
        if not same.any():
            scores.append(0.0)
            continue
        a = dist[i, same].mean()
        b = min(dist[i, labels == other].mean() for other in uniq if other != labels[i])
        scores.append((b - a) / max(a, b, 1e-9))
    return float(np.mean(scores))


def _prepare(vectors: np.ndarray, metric: str,
             fit: np.ndarray | None = None) -> np.ndarray:
    """Met les empreintes dans l'espace où les distances sont comparables.

    `fit` restreint le calcul des statistiques aux extraits fiables, pour que
    les répliques très courtes ne déforment pas la normalisation.
    """
    reference = vectors[fit] if fit is not None and fit.any() else vectors
    if metric == "ecapa":
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms < 1e-9] = 1.0
        return vectors / norms
    centered = vectors - reference.mean(axis=0, keepdims=True)
    scale = reference.std(axis=0, keepdims=True)
    scale[scale < 1e-6] = 1.0
    return centered / scale


def cluster_speakers(vectors: np.ndarray, forced: int | None = None,
                     max_speakers: int = MAX_SPEAKERS,
                     metric: str = "mfcc") -> tuple[np.ndarray, float]:
    """Regroupe les empreintes. Retourne (indices de groupe base 0, qualité).

    `metric="ecapa"` utilise la distance cosinus sur les vecteurs bruts, comme
    l'exige ce type d'empreinte. `metric="mfcc"` standardise chaque dimension
    puis raisonne en distance euclidienne (linkage de Ward), ce qui évite de
    faire exploser le bruit des extraits proches de la moyenne générale.
    """
    n = vectors.shape[0]
    if n == 0:
        return np.zeros(0, dtype=int), 0.0
    if n == 1 or forced == 1:
        return np.zeros(n, dtype=int), 1.0

    prepared = _prepare(vectors, metric)
    if metric == "ecapa":
        condensed = pdist(prepared, metric="cosine")
        method = "average"
    else:
        condensed = pdist(prepared, metric="euclidean")
        method = "ward"

    dist = squareform(condensed)
    tree = linkage(condensed, method=method)

    if forced and forced > 1:
        labels = fcluster(tree, t=min(forced, n), criterion="maxclust")
        return labels - 1, _silhouette(dist, labels)

    best_labels = np.ones(n, dtype=int)
    best_score = -1.0
    for k in range(2, min(max_speakers, n) + 1):
        labels = fcluster(tree, t=k, criterion="maxclust")
        if np.unique(labels).size < k:
            continue
        score = _silhouette(dist, labels)
        # Petit malus par personnage supplémentaire: on évite la sur-segmentation.
        adjusted = score - 0.03 * (k - 2)
        if adjusted > best_score:
            best_score, best_labels = adjusted, labels
    if best_score < _ACCEPT_SILHOUETTE:
        return np.zeros(n, dtype=int), max(best_score, 0.0)
    return best_labels - 1, best_score


def _assign_short(vectors: np.ndarray, labels: np.ndarray, reliable: np.ndarray,
                  metric: str) -> np.ndarray:
    """Rattache chaque extrait court au centre de groupe le plus proche.

    Une réplique de moins d'une seconde ne porte pas assez de signal pour créer
    un personnage à elle seule: on la classe, sans lui laisser fonder un groupe.
    """
    out = np.full(vectors.shape[0], -1, dtype=int)
    out[reliable] = labels
    prepared = _prepare(vectors, metric, fit=reliable)
    groups = np.unique(labels)
    centroids = np.vstack([prepared[reliable][labels == g].mean(axis=0) for g in groups])
    if metric == "ecapa":
        norms = np.linalg.norm(centroids, axis=1, keepdims=True)
        norms[norms < 1e-9] = 1.0
        centroids = centroids / norms
    for idx in np.flatnonzero(~reliable):
        dists = np.linalg.norm(centroids - prepared[idx], axis=1)
        out[idx] = groups[int(dists.argmin())]
    return out


def _smooth(labels: np.ndarray, lines: Sequence[Line], gap: float = 0.35) -> np.ndarray:
    """Lisse les répliques isolées: un enchaînement serré vient rarement de 2 voix."""
    out = labels.copy()
    for i in range(1, len(out) - 1):
        prev_gap = lines[i].start - lines[i - 1].end
        next_gap = lines[i + 1].start - lines[i].end
        if (out[i - 1] == out[i + 1] != out[i]
                and prev_gap < gap and next_gap < gap
                and (lines[i].end - lines[i].start) < 1.2):
            out[i] = out[i - 1]
    return out


def assign_speakers(audio: Path, lines: list[Line], forced: int | None = None,
                    use_embeddings: bool = True, cb: ProgressCb = None) -> dict:
    """Attribue un identifiant de personnage à chaque réplique, sur place."""
    if not lines:
        return {"speakers": [], "quality": 0.0, "method": "none"}

    vectors = None
    method = "mfcc"
    if use_embeddings and module_available("speechbrain"):
        vectors = _speechbrain_embeddings(audio, lines, cb)
        if vectors is not None:
            method = "ecapa"
    if vectors is None:
        vectors = _builtin_embeddings(audio, lines, cb)

    durations = np.array([max(l.end - l.start, 0.0) for l in lines])
    # Un cri ou un impact ne doit pas servir de reference pour definir une voix:
    # on le classe sans le laisser fonder un personnage.
    verbal = np.array([not getattr(l, "nonverbal", False) for l in lines])
    reliable = (durations >= _RELIABLE_SPEECH) & verbal
    if reliable.sum() < 2:
        reliable = np.ones(len(lines), dtype=bool)

    core_labels, quality = cluster_speakers(vectors[reliable], forced=forced, metric=method)
    labels = (_assign_short(vectors, core_labels, reliable, method)
              if not reliable.all() else core_labels)
    labels = _smooth(labels, lines)

    # Numérotation par ordre d'apparition: Personnage 1 parle en premier.
    order: dict[int, int] = {}
    for label in labels:
        order.setdefault(int(label), len(order))
    for line, label in zip(lines, labels):
        line.speaker = f"Personnage {order[int(label)] + 1}"
    if cb:
        cb(1.0, f"{len(order)} voix détectée(s)")
    return {
        "speakers": [f"Personnage {i + 1}" for i in range(len(order))],
        "quality": round(float(quality), 3),
        "method": method,
    }
