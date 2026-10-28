"""Shared fixtures. Tests train a small model from synthetic tickets, so they never need models/."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from triage.api.app import create_app
from triage.data.synthetic import generate
from triage.db.session import make_engine
from triage.domain.itil import load_policy
from triage.kb.retrieve import default_knowledge_base
from triage.llm.assistant import Assistant
from triage.llm.guard import DailyTokenBudget
from triage.llm.stub import StubProvider
from triage.ml.model import HEADS, TriageModel
from triage.ml.train import CANDIDATES, _example, build_vectorizer, fit
from triage.service import TriageService
from triage.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
HANDWRITTEN = ROOT / "data" / "test" / "handwritten.jsonl"

# Tuesday 3 November 2026, 10:00 London time (GMT): a normal working morning.
WORKDAY_MORNING = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)


@pytest.fixture(scope="session")
def tiny_model(tmp_path_factory: pytest.TempPathFactory) -> TriageModel:
    tickets = generate(1500, seed=11)
    examples = [_example(t.subject, t.body, {h: str(getattr(t, h)) for h in HEADS}, "train") for t in tickets]
    model = fit(build_vectorizer(), CANDIDATES["logistic_regression"], examples, None)
    model.metadata = {
        "version": "test+tiny",
        "review_threshold": 0.6,
        "training": {"synthetic": len(examples), "dev": 0},
        "test_summary": {"n": 0},
    }
    folder = tmp_path_factory.mktemp("model")
    model.save(folder)
    return TriageModel.load(folder)


@pytest.fixture
def service(tiny_model: TriageModel) -> TriageService:
    return TriageService(
        tiny_model,
        default_knowledge_base(),
        load_policy(),
        Assistant(StubProvider(), DailyTokenBudget(1_000_000)),
        clock=lambda: WORKDAY_MORNING,
    )


def make_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "env": "test",
        "database_url": "sqlite://",
        "auto_migrate": True,
        "auth_mode": "none",
        "llm_provider": "stub",
        "rate_limit_per_minute": 1000,
        "session_secret": "test-secret-not-for-production",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.fixture
def make_client(service: TriageService) -> Iterator[object]:
    clients: list[TestClient] = []

    def _make(**overrides: object) -> TestClient:
        settings = make_settings(**overrides)
        app = create_app(settings, service=service, engine=make_engine(settings))
        client = TestClient(app, base_url="https://testserver")
        clients.append(client)
        return client

    yield _make
    for c in clients:
        c.close()


@pytest.fixture
def client(make_client: object) -> TestClient:
    return make_client()  # type: ignore[operator, no-any-return]
