"""Write the evaluation figures, the metrics file and the generated part of the model card."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from triage.domain.taxonomy import CATEGORIES

BEGIN = "<!-- BEGIN GENERATED METRICS -->"
END = "<!-- END GENERATED METRICS -->"

INK = "#1f2933"
MUTED = "#616e7c"
GRID = "#d9e2ec"
ACCENT = "#1d4ed8"  # blue 700
SECOND = "#b45309"  # amber 700


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def confusion_figure(metrics: dict[str, Any], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    head = metrics["test"]["heads"]["category"]
    labels = head["labels"]
    names = [CATEGORIES[c].label.replace(" and ", " & ") if c in CATEGORIES else c for c in labels]
    cm = np.array(head["confusion"], dtype=float)
    share = cm / np.maximum(cm.sum(axis=1, keepdims=True), 1)

    fig, ax = plt.subplots(figsize=(8.2, 6.4), dpi=150)
    ax.imshow(share, cmap="Blues", vmin=0, vmax=1)
    for i in range(len(labels)):
        for j in range(len(labels)):
            if cm[i, j]:
                ax.text(
                    j,
                    i,
                    f"{int(cm[i, j])}",
                    ha="center",
                    va="center",
                    fontsize=10,
                    color="white" if share[i, j] > 0.55 else INK,
                )
    ax.set_xticks(range(len(labels)), names, rotation=35, ha="right", fontsize=9, color=INK)
    ax.set_yticks(range(len(labels)), names, fontsize=9, color=INK)
    ax.set_xlabel("Predicted category", color=MUTED)
    ax.set_ylabel("True category", color=MUTED)
    ax.set_title(
        f"Category on {metrics['test']['n']} held-out tickets (macro F1 {head['macro_f1']:.2f})",
        color=INK,
        fontsize=11,
        loc="left",
    )
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.tight_layout()
    fig.savefig(path, facecolor="white")
    plt.close(fig)


def threshold_figure(metrics: dict[str, Any], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    curve = [p for p in metrics["test"]["auto_route_curve"] if p["accuracy"] is not None]
    t = [p["threshold"] for p in curve]
    coverage = [p["coverage"] for p in curve]
    accuracy = [p["accuracy"] for p in curve]
    chosen = metrics["review_threshold"]

    fig, ax = plt.subplots(figsize=(8.2, 4.4), dpi=150)
    ax.plot(
        t,
        accuracy,
        color=ACCENT,
        linewidth=2,
        marker="o",
        markersize=4,
        label="Accuracy of auto-routed tickets",
    )
    ax.plot(
        t, coverage, color=SECOND, linewidth=2, marker="s", markersize=4, label="Share of tickets auto-routed"
    )
    ax.axvline(chosen, color=MUTED, linewidth=1, linestyle="--")
    ax.text(
        chosen + 0.01,
        0.52,
        f"chosen threshold {chosen:.2f}\n(picked on the dev set)",
        color=MUTED,
        fontsize=9,
    )
    ax.set_ylim(max(0.0, min(coverage + accuracy) - 0.05), 1.01)
    ax.set_xlim(min(t) - 0.02, max(t) + 0.02)
    ax.set_xlabel("Minimum model confidence to route a ticket without review", color=MUTED)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(loc="lower left", frameon=False, fontsize=9)
    ax.set_title(
        "Trading review workload for accuracy (held-out test set)", color=INK, fontsize=11, loc="left"
    )
    fig.tight_layout()
    fig.savefig(path, facecolor="white")
    plt.close(fig)


def metrics_markdown(metrics: dict[str, Any]) -> str:
    test = metrics["test"]
    heads = test["heads"]
    base = metrics["majority_baseline_test"]
    rows = [
        ("Category (7 classes)", "category"),
        ("Incident or service request", "type"),
        ("Impact (3 levels)", "impact"),
        ("Urgency (3 levels)", "urgency"),
    ]
    lines = [
        f"Model `{metrics['version']}` ({metrics['algorithm'].replace('_', ' ')}), evaluated once on "
        f"**{test['n']} held-out tickets** that were written separately from the training data and never "
        "used for training or tuning.",
        "",
        "| Output | Accuracy | Macro F1 | Majority-class baseline |",
        "|---|---|---|---|",
    ]
    for name, h in rows:
        lines.append(
            f"| {name} | {_pct(heads[h]['accuracy'])} | {heads[h]['macro_f1']:.3f} | {_pct(base[h])} |"
        )
    pr = test["priority"]
    ar = test["auto_route"]
    so = metrics["test_synthetic_only_model"]
    lines += [
        "",
        "**Priority (P1 to P4)** after the safety rules: "
        f"{_pct(pr['with_rules']['exact'])} exactly right, {_pct(pr['with_rules']['within_one'])} within one level, "
        f"{_pct(pr['with_rules']['under_prioritised'])} under-prioritised "
        f"(model alone: {_pct(pr['model_only']['under_prioritised'])}). "
        f"P1 recall: {_pct(pr['with_rules']['p1_recall'])} with rules, {_pct(pr['model_only']['p1_recall'])} without.",
        "",
        f"**Human review:** tickets whose category confidence is below {metrics['review_threshold']:.2f} go to an "
        f"analyst. At that threshold {_pct(ar['coverage'])} of test tickets were routed automatically and "
        f"{_pct(ar['accuracy_routed'])} of those were routed to the right team"
        + (
            f"; the model was right on {_pct(ar['accuracy_reviewed'])} of the ones sent for review."
            if ar.get("accuracy_reviewed") is not None
            else "."
        ),
        "",
        "**Effect of the 92 realistic dev tickets:** a model trained on synthetic tickets alone scores "
        f"category macro F1 {so['heads']['category']['macro_f1']:.3f} and urgency "
        f"{so['heads']['urgency']['macro_f1']:.3f} on the same test set, against "
        f"{heads['category']['macro_f1']:.3f} and {heads['urgency']['macro_f1']:.3f} for the final model.",
        "",
        "Per category (test set):",
        "",
        "| Category | Precision | Recall | F1 | Tickets |",
        "|---|---|---|---|---|",
    ]
    for c in heads["category"]["labels"]:
        pc = heads["category"]["per_class"][c]
        label = CATEGORIES[c].label if c in CATEGORIES else c
        lines.append(
            f"| {label} | {pc['precision']:.2f} | {pc['recall']:.2f} | {pc['f1-score']:.2f} | "
            f"{int(pc['support'])} |"
        )
    lines += [
        "",
        "Model selection on the dev set (macro F1, trained on synthetic data only):",
        "",
        "| Algorithm | Category | Type | Impact | Urgency |",
        "|---|---|---|---|---|",
    ]
    for name, s in metrics["selection_on_dev"].items():
        f = s["dev_macro_f1"]
        lines.append(
            f"| {name.replace('_', ' ')} | {f['category']:.3f} | {f['type']:.3f} | {f['impact']:.3f} | "
            f"{f['urgency']:.3f} |"
        )
    lines += [
        "",
        "![Confusion matrix](img/category-confusion.png)",
        "",
        "![Review threshold](img/review-threshold.png)",
    ]
    return "\n".join(lines)


def write_reports(metrics: dict[str, Any], docs: Path) -> None:
    img = docs / "img"
    img.mkdir(parents=True, exist_ok=True)
    (docs / "model-metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    confusion_figure(metrics, img / "category-confusion.png")
    threshold_figure(metrics, img / "review-threshold.png")
    card = docs / "model-card.md"
    block = f"{BEGIN}\n{metrics_markdown(metrics)}\n{END}"
    if card.exists():
        text = card.read_text(encoding="utf-8")
        if BEGIN in text and END in text:
            text = text[: text.index(BEGIN)] + block + text[text.index(END) + len(END) :]
        else:
            text = text.rstrip() + "\n\n" + block + "\n"
    else:
        text = f"# Model card\n\n{block}\n"
    card.write_text(text, encoding="utf-8")
