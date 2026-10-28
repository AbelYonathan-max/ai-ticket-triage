from __future__ import annotations

import pytest

from triage.domain.rules import RULES, apply_rules

POSITIVE = [
    ("active-compromise", "I clicked the link in the email and entered my password", "security", "incident"),
    (
        "active-compromise",
        "My account was signed in from a different country overnight",
        "security",
        "incident",
    ),
    ("ransomware", "A ransom note appeared and my files end in .locked", "software", "incident"),
    ("lost-or-stolen-device", "I left my laptop on the train this morning", "hardware", "incident"),
    ("lost-or-stolen-device", "My work phone was stolen at the weekend", "security", "incident"),
    (
        "personal-data-breach",
        "I emailed a spreadsheet of client details to the wrong person",
        "security",
        "incident",
    ),
    ("organisation-wide", "Nobody in the building can get online", "network", "incident"),
    ("organisation-wide", "Email is down across the whole trust", "m365", "incident"),
    ("several-people", "The whole team can't open the shared drive", "network", "incident"),
    ("several-people", "My colleagues have the same problem", "software", "incident"),
    ("patient-safety", "Clinic staff can't see patient records", "software", "incident"),
    ("work-stopped", "I can't do any work at all", "hardware", "incident"),
    ("deadline", "I need this by 3pm for a board paper", "software", "request"),
]

NEGATIVE = [
    ("lost-or-stolen-device", "I lost my laptop charger, can I order a new one?", "hardware", "request"),
    ("ransomware", "Please install the new version of Adobe Reader", "software", "request"),
    ("patient-safety", "Can't print the ward rota", "printing", "request"),  # requests never fire it
    ("work-stopped", "Teams is a bit slow but I can still work", "m365", "incident"),
    ("organisation-wide", "Can someone check my mailbox size?", "m365", "request"),
    ("active-compromise", "I clicked the link in the email and entered my password", "access", "incident"),
]


@pytest.mark.parametrize(("rule_id", "text", "category", "ticket_type"), POSITIVE)
def test_rule_fires(rule_id: str, text: str, category: str, ticket_type: str) -> None:
    outcome = apply_rules(text, category, ticket_type, impact=3, urgency=3)
    assert rule_id in outcome.fired, outcome


@pytest.mark.parametrize(("rule_id", "text", "category", "ticket_type"), NEGATIVE)
def test_rule_does_not_fire(rule_id: str, text: str, category: str, ticket_type: str) -> None:
    outcome = apply_rules(text, category, ticket_type, impact=3, urgency=3)
    assert rule_id not in outcome.fired, outcome


def test_rules_never_lower_priority() -> None:
    for text, category, ticket_type in [(p[1], p[2], p[3]) for p in POSITIVE]:
        outcome = apply_rules(text, category, ticket_type, impact=1, urgency=1)
        assert (outcome.impact, outcome.urgency) == (1, 1)


def test_major_outage_needs_high_impact() -> None:
    low = apply_rules("The finance system is down", "software", "incident", impact=3, urgency=3)
    assert "major-outage" not in low.fired
    high = apply_rules(
        "The finance system is down for every site", "software", "incident", impact=3, urgency=3
    )
    assert {"organisation-wide", "major-outage"} <= set(high.fired)
    assert (high.impact, high.urgency) == (1, 1)
    assert any("major incident" in r for r in high.review_reasons)


def test_rules_stay_within_one_sentence() -> None:
    text = "My colleagues are fine. Also, could I have a new mouse?"
    assert "several-people" not in apply_rules(text, "hardware", "request", 3, 3).fired


def test_rule_ids_are_unique() -> None:
    ids = [r.id for r in RULES]
    assert len(ids) == len(set(ids))
