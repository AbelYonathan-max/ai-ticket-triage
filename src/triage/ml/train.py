"""Train, select and evaluate the triage model, then write the model card figures and metrics.

Data:
  * 8,400 synthetic tickets (see triage.data.synthetic) to learn from.
  * 281 tickets written one at a time, separately from the generator, split once with a fixed seed:
    - dev (92): to choose the model and the confidence threshold for human review;
    - test (189): touched once, at the end, for the numbers we report.

The final model is trained on the synthetic tickets plus the dev tickets (weighted x3, because they
read more like real tickets). The test tickets are never used for training or tuning.

Usage:  python -m triage.ml.train [--out models] [--docs docs]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.naive_bayes import ComplementNB
from sklearn.pipeline import FeatureUnion
from sklearn.svm import LinearSVC

from triage import __version__
from triage.data import synthetic
from triage.domain.itil import priority_from
from triage.domain.rules import apply_rules
from triage.ml.model import HEADS, TriageModel, ticket_text
from triage.privacy.redact import redact

SEED = 7
TARGET_AUTO_ACCURACY = 0.97  # tickets routed without review should be right at least 97% of the time
MIN_THRESHOLD = 0.5  # never auto-route unless one category has more than half the probability
DEV_WEIGHT = 3.0
LOGREG_TOLERANCE = 0.02  # prefer the explainable model unless another beats it by more than this


@dataclass
class Example:
    text: str
    labels: dict[str, str]
    raw_text: str  # redacted subject and body joined, as the rules see it
    split: str = "train"


def build_vectorizer() -> FeatureUnion:
    return FeatureUnion(
        [
            (
                "word",
                TfidfVectorizer(
                    ngram_range=(1, 2),
                    min_df=2,
                    sublinear_tf=True,
                    max_features=60000,
                    # A regex, not a password.
                    token_pattern=r"(?u)\b\w[\w']*\b",  # noqa: S106 # nosec B106
                ),
            ),
            (
                "char",
                TfidfVectorizer(
                    analyzer="char_wb",
                    ngram_range=(3, 5),
                    min_df=3,
                    sublinear_tf=True,
                    max_features=80000,
                ),
            ),
        ]
    )


CANDIDATES: dict[str, Callable[[], Any]] = {
    "logistic_regression": lambda: LogisticRegression(C=8.0, max_iter=3000, class_weight="balanced"),
    "linear_svm_calibrated": lambda: CalibratedClassifierCV(
        LinearSVC(C=0.5, class_weight="balanced"), cv=3, method="sigmoid"
    ),
    "complement_naive_bayes": lambda: ComplementNB(alpha=0.3),
}


def _example(subject: str, body: str, labels: dict[str, str], split: str) -> Example:
    rs, rb = redact(subject).text, redact(body).text
    return Example(text=ticket_text(rs, rb), labels=labels, raw_text=f"{rs}\n{rb}", split=split)


def load_synthetic(path: Path) -> list[Example]:
    with path.open(encoding="utf-8") as f:
        return [
            _example(r["subject"], r["body"], {h: str(r[h]) for h in HEADS}, "train")
            for r in csv.DictReader(f)
        ]


def load_handwritten(path: Path) -> list[Example]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [_example(r["subject"], r["body"], {h: str(r[h]) for h in HEADS}, r["split"]) for r in rows]


def fit(
    vectorizer: FeatureUnion, factory: Callable[[], Any], examples: list[Example], weights: np.ndarray | None
) -> TriageModel:
    x = vectorizer.fit_transform([e.text for e in examples])
    heads = {}
    for head in HEADS:
        clf = factory()
        y = [e.labels[head] for e in examples]
        if weights is not None:
            clf.fit(x, y, sample_weight=weights)
        else:
            clf.fit(x, y)
        heads[head] = clf
    return TriageModel(vectorizer, heads, {})


def _priority(impact: str, urgency: str) -> int:
    return priority_from(int(impact), int(urgency))


def evaluate(model: TriageModel, examples: list[Example], threshold: float | None = None) -> dict[str, Any]:
    texts = [e.text for e in examples]
    proba = model.predict_proba(texts)
    result: dict[str, Any] = {"n": len(examples), "heads": {}}
    preds: dict[str, list[str]] = {}
    for head in HEADS:
        classes = model.classes(head)
        y_pred = [classes[i] for i in np.argmax(proba[head], axis=1)]
        y_true = [e.labels[head] for e in examples]
        preds[head] = y_pred
        labels = sorted(set(y_true) | set(classes))
        report = classification_report(y_true, y_pred, labels=labels, output_dict=True, zero_division=0)
        result["heads"][head] = {
            "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
            "macro_f1": round(
                float(f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)), 4
            ),
            "per_class": {
                c: {k: round(float(report[c][k]), 4) for k in ("precision", "recall", "f1-score", "support")}
                for c in labels
            },
            "labels": labels,
            "confusion": confusion_matrix(y_true, y_pred, labels=labels).tolist(),
        }

    # Priority, before and after the safety rules (rules only ever raise priority).
    true_p = [_priority(e.labels["impact"], e.labels["urgency"]) for e in examples]
    model_p = [_priority(i, u) for i, u in zip(preds["impact"], preds["urgency"], strict=True)]
    ruled_p = []
    for e, cat, typ, imp, urg in zip(
        examples, preds["category"], preds["type"], preds["impact"], preds["urgency"], strict=True
    ):
        o = apply_rules(e.raw_text, cat, typ, int(imp), int(urg))
        ruled_p.append(priority_from(o.impact, o.urgency))

    def _pstats(pred: list[int]) -> dict[str, float]:
        t, p = np.array(true_p), np.array(pred)
        return {
            "exact": round(float((t == p).mean()), 4),
            "within_one": round(float((np.abs(t - p) <= 1).mean()), 4),
            "under_prioritised": round(float((p > t).mean()), 4),
            "over_prioritised": round(float((p < t).mean()), 4),
            "p1_recall": round(float(((p == 1) & (t == 1)).sum() / max(1, (t == 1).sum())), 4),
        }

    result["priority"] = {"model_only": _pstats(model_p), "with_rules": _pstats(ruled_p)}

    # Coverage and accuracy of tickets routed without review, at every confidence threshold.
    conf = proba["category"].max(axis=1)
    correct = np.array([p == e.labels["category"] for p, e in zip(preds["category"], examples, strict=True)])
    curve = []
    for t in np.round(np.arange(0.30, 0.96, 0.05), 2):
        mask = conf >= t
        curve.append(
            {
                "threshold": float(t),
                "coverage": round(float(mask.mean()), 4),
                "accuracy": round(float(correct[mask].mean()), 4) if mask.any() else None,
            }
        )
    result["auto_route_curve"] = curve
    if threshold is not None:
        mask = conf >= threshold
        result["auto_route"] = {
            "threshold": threshold,
            "coverage": round(float(mask.mean()), 4),
            "accuracy_routed": round(float(correct[mask].mean()), 4) if mask.any() else None,
            "accuracy_reviewed": round(float(correct[~mask].mean()), 4) if (~mask).any() else None,
        }
    return result


def choose_threshold(curve: list[dict[str, Any]], target: float) -> float:
    """Lowest threshold (at least MIN_THRESHOLD) whose auto-routed tickets meet the accuracy target."""
    for point in curve:
        if point["threshold"] < MIN_THRESHOLD:
            continue
        if point["accuracy"] is not None and point["accuracy"] >= target:
            return float(point["threshold"])
    return 0.8


def data_fingerprint(*paths: Path) -> str:
    digest = hashlib.sha256()
    for p in paths:
        digest.update(p.read_bytes())
    digest.update(json.dumps(sorted(CANDIDATES)).encode())
    return digest.hexdigest()[:10]


def _mean_f1(ev: dict[str, Any]) -> float:
    return float(np.mean([ev["heads"][h]["macro_f1"] for h in HEADS]))


def train(data: Path, handwritten: Path, out: Path, docs: Path | None, quiet: bool = False) -> dict[str, Any]:
    def log(msg: str) -> None:
        if not quiet:
            print(msg)

    if not data.exists():
        synthetic.write_csv(synthetic.generate(8400, SEED), data)
        log(f"generated synthetic training data at {data}")
    train_rows = load_synthetic(data)
    hand = load_handwritten(handwritten)
    dev = [e for e in hand if e.split == "dev"]
    test = [e for e in hand if e.split == "test"]
    log(f"synthetic {len(train_rows)}, dev {len(dev)}, test {len(test)}")

    # 1. Model selection on the dev set, training on synthetic data only.
    selection: dict[str, Any] = {}
    for name, factory in CANDIDATES.items():
        model = fit(build_vectorizer(), factory, train_rows, None)
        ev = evaluate(model, dev)
        selection[name] = {
            "dev_macro_f1": {h: ev["heads"][h]["macro_f1"] for h in HEADS},
            "dev_mean_macro_f1": round(_mean_f1(ev), 4),
            "_model": model,
            "_eval": ev,
        }
        log(f"  {name:24s} dev macro-F1 {selection[name]['dev_macro_f1']}  mean {_mean_f1(ev):.3f}")
    best = max(selection, key=lambda n: selection[n]["dev_mean_macro_f1"])
    chosen = "logistic_regression"
    if selection[best]["dev_mean_macro_f1"] - selection[chosen]["dev_mean_macro_f1"] > LOGREG_TOLERANCE:
        chosen = best
    threshold = choose_threshold(selection[chosen]["_eval"]["auto_route_curve"], TARGET_AUTO_ACCURACY)
    log(f"chosen {chosen}, review threshold {threshold}")

    # 2. Final model: synthetic + dev (weighted), evaluated once on the untouched test set.
    synthetic_only_test = evaluate(selection[chosen]["_model"], test, threshold)
    final_rows = train_rows + dev
    weights = np.array([1.0] * len(train_rows) + [DEV_WEIGHT] * len(dev))
    final = fit(build_vectorizer(), CANDIDATES[chosen], final_rows, weights)
    test_eval = evaluate(final, test, threshold)

    import sklearn

    fingerprint = data_fingerprint(data, handwritten)
    final.metadata = {
        "version": f"{__version__}+{fingerprint}",
        "algorithm": chosen,
        "review_threshold": threshold,
        "heads": {h: final.classes(h) for h in HEADS},
        "training": {"synthetic": len(train_rows), "dev": len(dev), "dev_weight": DEV_WEIGHT},
        "sklearn_version": sklearn.__version__,
        "test_summary": {
            "n": test_eval["n"],
            "category_accuracy": test_eval["heads"]["category"]["accuracy"],
            "type_accuracy": test_eval["heads"]["type"]["accuracy"],
            "category_macro_f1": test_eval["heads"]["category"]["macro_f1"],
            "type_macro_f1": test_eval["heads"]["type"]["macro_f1"],
            "impact_macro_f1": test_eval["heads"]["impact"]["macro_f1"],
            "urgency_macro_f1": test_eval["heads"]["urgency"]["macro_f1"],
            "priority_exact": test_eval["priority"]["with_rules"]["exact"],
            "priority_within_one": test_eval["priority"]["with_rules"]["within_one"],
            "under_prioritised": test_eval["priority"]["with_rules"]["under_prioritised"],
            "p1_recall": test_eval["priority"]["with_rules"]["p1_recall"],
            "auto_route": test_eval["auto_route"],
        },
    }
    final.save(out)
    log(f"saved model {final.version} to {out}")

    metrics = {
        "version": final.version,
        "algorithm": chosen,
        "review_threshold": threshold,
        "target_auto_accuracy": TARGET_AUTO_ACCURACY,
        "selection_on_dev": {
            n: {k: v for k, v in s.items() if not k.startswith("_")} for n, s in selection.items()
        },
        "test": test_eval,
        "test_synthetic_only_model": {
            "heads": {h: {"macro_f1": synthetic_only_test["heads"][h]["macro_f1"]} for h in HEADS},
            "auto_route": synthetic_only_test["auto_route"],
        },
        "majority_baseline_test": {
            h: round(
                max(sum(e.labels[h] == c for e in test) for c in {e.labels[h] for e in test}) / len(test), 4
            )
            for h in HEADS
        },
    }
    if docs is not None:
        from triage.ml.report import write_reports

        write_reports(metrics, docs)
        log(f"wrote model card figures and metrics to {docs}")
    for h in HEADS:
        log(
            f"  test {h:9s} acc {test_eval['heads'][h]['accuracy']:.3f}  macro-F1 {test_eval['heads'][h]['macro_f1']:.3f}"
        )
    log(f"  test priority {test_eval['priority']}")
    log(f"  test auto-route {test_eval['auto_route']}")
    return metrics


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Train and evaluate the triage model")
    parser.add_argument("--data", type=Path, default=Path("data/synthetic/train.csv"))
    parser.add_argument("--handwritten", type=Path, default=Path("data/test/handwritten.jsonl"))
    parser.add_argument("--out", type=Path, default=Path("models"))
    parser.add_argument("--docs", type=Path, default=None, help="write model card figures and metrics here")
    args = parser.parse_args(argv)
    train(args.data, args.handwritten, args.out, args.docs)


if __name__ == "__main__":
    main()
