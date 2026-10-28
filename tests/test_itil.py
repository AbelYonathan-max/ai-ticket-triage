from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from triage.domain.itil import PRIORITY_MATRIX, load_policy, policy_from_dict, priority_from

LONDON = ZoneInfo("Europe/London")


def london(*args: int) -> datetime:
    return datetime(*args, tzinfo=LONDON)  # type: ignore[misc]


def test_priority_matrix_is_complete_and_monotonic() -> None:
    assert len(PRIORITY_MATRIX) == 9
    for impact in (1, 2, 3):
        for urgency in (1, 2, 3):
            p = priority_from(impact, urgency)
            if impact > 1:
                assert priority_from(impact - 1, urgency) <= p
            if urgency > 1:
                assert priority_from(impact, urgency - 1) <= p


@pytest.mark.parametrize(
    ("impact", "urgency", "expected"), [(1, 1, 1), (1, 2, 2), (2, 2, 3), (3, 3, 4), (3, 1, 3)]
)
def test_priority_examples(impact: int, urgency: int, expected: int) -> None:
    assert priority_from(impact, urgency) == expected


def test_priority_rejects_out_of_range() -> None:
    with pytest.raises(ValueError, match="impact and urgency"):
        priority_from(0, 2)


def test_p1_runs_around_the_clock() -> None:
    policy = load_policy()
    opened = london(2026, 11, 7, 23, 0)  # Saturday night
    respond, resolve = policy.due_times(1, opened)
    assert respond == opened.astimezone(UTC) + timedelta(minutes=15)
    assert resolve == opened.astimezone(UTC) + timedelta(hours=4)


def test_business_clock_skips_evening_and_weekend() -> None:
    policy = load_policy()
    opened = london(2026, 11, 6, 17, 0)  # Friday 17:00, one hour before close
    respond, _ = policy.due_times(3, opened)  # 4 business hours
    assert respond == london(2026, 11, 9, 11, 0).astimezone(UTC)  # Monday 11:00


def test_business_clock_starts_at_opening_time_when_logged_overnight() -> None:
    policy = load_policy()
    respond, _ = policy.due_times(2, london(2026, 11, 3, 6, 30))  # Tuesday before opening
    assert respond == london(2026, 11, 3, 8, 30).astimezone(UTC)


def test_business_clock_skips_bank_holidays() -> None:
    policy = load_policy()
    # Thursday 24 December 2026 at 17:00; 25 and 28 December are bank holidays, 26-27 a weekend.
    respond, _ = policy.due_times(3, london(2026, 12, 24, 17, 0))
    assert respond == london(2026, 12, 29, 11, 0).astimezone(UTC)


def test_business_clock_across_clock_change() -> None:
    policy = load_policy()
    # Friday 23 October 2026 17:00 BST; clocks go back on Sunday 25 October.
    respond, _ = policy.due_times(3, london(2026, 10, 23, 17, 0))
    assert respond == london(2026, 10, 26, 11, 0).astimezone(UTC)
    assert respond.hour == 11  # 11:00 GMT is 11:00 UTC


def test_naive_times_are_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        load_policy().calendar.add_business_minutes(datetime(2026, 11, 3, 9, 0), 10)


def test_policy_validation() -> None:
    base = {
        "business_hours": {"start": "09:00", "end": "17:00", "days": ["mon"]},
        "priorities": {f"P{i}": {"name": "x", "respond_minutes": 1, "resolve_minutes": 2} for i in (1, 2, 3)},
    }
    with pytest.raises(ValueError, match="P1 to P4"):
        policy_from_dict(base)
    base["business_hours"] = {"start": "17:00", "end": "09:00", "days": ["mon"]}
    with pytest.raises(ValueError, match="before end"):
        policy_from_dict(base)
