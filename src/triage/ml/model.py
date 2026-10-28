"""The triage model: one shared text representation and four classifier heads.

Text goes through two TF-IDF vectorisers (words and word pairs, plus character n-grams that cope
with typos and text-speak). Four linear classifiers sit on top: category, ticket type, impact and
urgency. Linear models were chosen on purpose: they train in seconds, run in milliseconds on a
small container, and every prediction can be explained by the words that pushed it.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from scipy import sparse
from sklearn.pipeline import FeatureUnion

HEADS = ("category", "type", "impact", "urgency")
MODEL_FILE = "triage_model.joblib"
METADATA_FILE = "metadata.json"

_QUOTES = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-"})


def normalise(text: str) -> str:
    """Lower-case, unify quotes and dashes, and collapse whitespace."""
    text = text.translate(_QUOTES).lower()
    text = re.sub(r"https?://\S+", " url ", text)
    return re.sub(r"\s+", " ", text).strip()


def ticket_text(subject: str, body: str) -> str:
    """The model reads the subject twice: it is short and usually the clearest signal."""
    return normalise(f"{subject} . {subject} . {body}")


@dataclass(frozen=True)
class HeadPrediction:
    label: str
    confidence: float
    probabilities: dict[str, float]
    top_terms: list[tuple[str, float]]


class ModelIntegrityError(RuntimeError):
    """The model file does not match the checksum recorded when it was trained."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 16), b""):
            digest.update(block)
    return digest.hexdigest()


class TriageModel:
    def __init__(self, vectorizer: FeatureUnion, heads: dict[str, Any], metadata: dict[str, Any]) -> None:
        self.vectorizer = vectorizer
        self.heads = heads
        self.metadata = metadata
        names = vectorizer.get_feature_names_out()
        # Only word features are shown to people; character n-grams explain poorly.
        self._word_mask = np.array([n.startswith("word__") for n in names])
        self._names = np.array([n.split("__", 1)[1] for n in names])

    @property
    def version(self) -> str:
        return str(self.metadata.get("version", "unversioned"))

    @property
    def review_threshold(self) -> float:
        return float(self.metadata.get("review_threshold", 0.6))

    def transform(self, texts: list[str]) -> sparse.csr_matrix:
        return self.vectorizer.transform(texts)

    def predict_proba(self, texts: list[str]) -> dict[str, np.ndarray]:
        x = self.transform(texts)
        return {head: clf.predict_proba(x) for head, clf in self.heads.items()}

    def classes(self, head: str) -> list[str]:
        return [str(c) for c in self.heads[head].classes_]

    def predict(self, subject: str, body: str, explain: int = 5) -> dict[str, HeadPrediction]:
        """Predict every head for one redacted ticket, with the top words behind each prediction."""
        x = self.transform([ticket_text(subject, body)])
        row = x.tocsr()
        out: dict[str, HeadPrediction] = {}
        for head, clf in self.heads.items():
            proba = clf.predict_proba(x)[0]
            classes = [str(c) for c in clf.classes_]
            best = int(np.argmax(proba))
            out[head] = HeadPrediction(
                label=classes[best],
                confidence=float(proba[best]),
                probabilities={c: round(float(p), 4) for c, p in zip(classes, proba, strict=True)},
                top_terms=self._explain(clf, row, best, explain) if explain else [],
            )
        return out

    def _explain(self, clf: Any, row: sparse.csr_matrix, class_index: int, k: int) -> list[tuple[str, float]]:
        coef = getattr(clf, "coef_", None)
        if coef is None:
            return []
        weights = coef[0] if coef.shape[0] == 1 else coef[class_index]
        sign = -1.0 if coef.shape[0] == 1 and class_index == 0 else 1.0
        idx = row.indices
        contrib = row.data * weights[idx] * sign
        keep = self._word_mask[idx] & (contrib > 0)
        idx, contrib = idx[keep], contrib[keep]
        order = np.argsort(-contrib)[:k]
        return [(str(self._names[idx[i]]), round(float(contrib[i]), 3)) for i in order]

    # ------------------------------------------------------------------ persistence
    def save(self, model_dir: Path) -> Path:
        model_dir.mkdir(parents=True, exist_ok=True)
        path = model_dir / MODEL_FILE
        joblib.dump({"vectorizer": self.vectorizer, "heads": self.heads}, path, compress=3)
        meta = dict(self.metadata)
        meta["sha256"] = sha256_file(path)
        (model_dir / METADATA_FILE).write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
        self.metadata = meta
        return path

    @classmethod
    def load(cls, model_dir: Path) -> TriageModel:
        """Load a trained model, refusing a file whose checksum does not match its metadata.

        joblib files can run code when loaded, so the model is only ever loaded from the image's own
        build output, and the checksum check stops a swapped or corrupted file from being used.
        """
        path = model_dir / MODEL_FILE
        meta = json.loads((model_dir / METADATA_FILE).read_text(encoding="utf-8"))
        expected = meta.get("sha256")
        actual = sha256_file(path)
        if not expected or expected != actual:
            raise ModelIntegrityError(f"model checksum mismatch: expected {expected}, got {actual}")
        # The checksum was verified above and the file is built by our own pipeline.
        bundle = joblib.load(path)  # nosec B301
        return cls(bundle["vectorizer"], bundle["heads"], meta)
