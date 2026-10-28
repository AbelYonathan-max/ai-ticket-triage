from __future__ import annotations

from collections import Counter

from triage.data.synthetic import generate
from triage.domain.itil import priority_from
from triage.domain.rules import apply_rules
from triage.domain.taxonomy import CATEGORIES
from triage.privacy.redact import redact


def test_generator_is_deterministic() -> None:
    a, b = generate(50, seed=3), generate(50, seed=3)
    assert [(t.subject, t.body) for t in a] == [(t.subject, t.body) for t in b]
    assert [t.body for t in generate(50, seed=4)] != [t.body for t in a]


def test_generator_covers_every_category_and_label() -> None:
    tickets = generate(2000, seed=5)
    assert set(Counter(t.category for t in tickets)) == set(CATEGORIES)
    assert {t.type for t in tickets} == {"incident", "request"}
    assert {t.impact for t in tickets} == {1, 2, 3} and {t.urgency for t in tickets} == {1, 2, 3}


def test_labels_agree_with_the_safety_rules() -> None:
    """If the rules would raise a generated ticket above its label, the generator or the rules are wrong."""
    tickets = generate(3000, seed=9)
    disagreements = 0
    for t in tickets:
        text = f"{redact(t.subject).text}\n{redact(t.body).text}"
        out = apply_rules(text, t.category, t.type, t.impact, t.urgency)
        if priority_from(out.impact, out.urgency) != priority_from(t.impact, t.urgency):
            disagreements += 1
    assert disagreements / len(tickets) < 0.005


def test_generated_personal_data_is_fake_and_redactable() -> None:
    tickets = generate(500, seed=6)
    phones = [t for t in tickets if "07700 900" in t.body or "07700900" in t.body]
    assert phones, "expected some tickets with Ofcom drama-range phone numbers"
    for t in phones:
        assert "07700 900" not in redact(t.body).text
    emails = [t for t in tickets if "@" in t.body]
    assert all("@example." in t.body for t in emails)
