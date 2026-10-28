"""Quality gate for the trained model in models/ (built by `python -m triage.ml.train`).

CI trains the model and then runs these tests. A change to the data, features or rules that makes
the model worse than these floors fails the build instead of reaching production.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import HANDWRITTEN, ROOT
from triage.ml.model import TriageModel
from triage.ml.train import evaluate, load_handwritten

pytestmark = pytest.mark.quality
MODEL_DIR = ROOT / "models"

FLOORS = {
    "category_macro_f1": 0.90,
    "type_macro_f1": 0.92,
    "impact_macro_f1": 0.75,
    "urgency_macro_f1": 0.65,
    "priority_within_one": 0.95,
}


@pytest.fixture(scope="module")
def model() -> TriageModel:
    if not (MODEL_DIR / "triage_model.joblib").exists():
        pytest.skip("no trained model in models/")
    return TriageModel.load(MODEL_DIR)


def test_recorded_test_metrics_meet_the_floors(model: TriageModel) -> None:
    summary = model.metadata["test_summary"]
    for key, floor in FLOORS.items():
        assert summary[key] >= floor, f"{key} {summary[key]} is below {floor}"
    assert summary["auto_route"]["accuracy_routed"] >= 0.95
    assert summary["under_prioritised"] <= 0.08


def test_metrics_reproduce_from_the_saved_model(model: TriageModel) -> None:
    test = [e for e in load_handwritten(HANDWRITTEN) if e.split == "test"]
    result = evaluate(model, test, model.review_threshold)
    assert result["heads"]["category"]["macro_f1"] == pytest.approx(
        model.metadata["test_summary"]["category_macro_f1"]
    )


def test_model_card_is_in_sync(model: TriageModel) -> None:
    metrics = json.loads(Path(ROOT / "docs" / "model-metrics.json").read_text(encoding="utf-8"))
    assert metrics["version"] == model.version
