"""ITIL priority matrix and service level (SLA) targets.

Priority comes from impact and urgency, as in ITIL incident management:

                 urgency 1   urgency 2   urgency 3
    impact 1        P1          P2          P3
    impact 2        P2          P3          P4
    impact 3        P3          P4          P4

Response and resolution targets come from config/sla.yaml. P1 runs on a 24x7 clock. The other
priorities only count service desk hours, skipping weekends and bank holidays.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

PRIORITY_MATRIX: dict[tuple[int, int], int] = {
    (1, 1): 1,
    (1, 2): 2,
    (1, 3): 3,
    (2, 1): 2,
    (2, 2): 3,
    (2, 3): 4,
    (3, 1): 3,
    (3, 2): 4,
    (3, 3): 4,
}

_WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def priority_from(impact: int, urgency: int) -> int:
    """Return the ITIL priority (1 = highest) for an impact and urgency, each 1 to 3."""
    if (impact, urgency) not in PRIORITY_MATRIX:
        raise ValueError(f"impact and urgency must be 1, 2 or 3 (got {impact}, {urgency})")
    return PRIORITY_MATRIX[(impact, urgency)]


@dataclass(frozen=True)
class SlaTarget:
    priority: int
    name: str
    respond_minutes: int
    resolve_minutes: int
    clock: str  # "24x7" or "business"


@dataclass(frozen=True)
class BusinessCalendar:
    tz: ZoneInfo
    start: time
    end: time
    days: frozenset[int]
    holidays: frozenset[date]

    def is_business_day(self, d: date) -> bool:
        return d.weekday() in self.days and d not in self.holidays

    def _next_open(self, d: date) -> datetime:
        d = d + timedelta(days=1)
        while not self.is_business_day(d):
            d += timedelta(days=1)
        return datetime.combine(d, self.start, tzinfo=self.tz)

    def add_business_minutes(self, start: datetime, minutes: int) -> datetime:
        """Add working minutes to a time, skipping evenings, weekends and bank holidays."""
        if start.tzinfo is None:
            raise ValueError("start must be timezone-aware")
        t = start.astimezone(self.tz)
        remaining = float(minutes)
        while True:
            if not self.is_business_day(t.date()) or t.timetz().replace(tzinfo=None) >= self.end:
                t = self._next_open(t.date())
                continue
            if t.timetz().replace(tzinfo=None) < self.start:
                t = datetime.combine(t.date(), self.start, tzinfo=self.tz)
            close = datetime.combine(t.date(), self.end, tzinfo=self.tz)
            available = (close - t).total_seconds() / 60
            if remaining <= available:
                return (t + timedelta(minutes=remaining)).astimezone(UTC)
            remaining -= available
            t = self._next_open(t.date())


@dataclass(frozen=True)
class SlaPolicy:
    calendar: BusinessCalendar
    targets: dict[int, SlaTarget]

    def due_times(self, priority: int, opened_at: datetime) -> tuple[datetime, datetime]:
        """Return (respond_by, resolve_by) in UTC for a ticket opened at `opened_at`."""
        target = self.targets[priority]
        if target.clock == "24x7":
            return (
                (opened_at + timedelta(minutes=target.respond_minutes)).astimezone(UTC),
                (opened_at + timedelta(minutes=target.resolve_minutes)).astimezone(UTC),
            )
        return (
            self.calendar.add_business_minutes(opened_at, target.respond_minutes),
            self.calendar.add_business_minutes(opened_at, target.resolve_minutes),
        )


def _parse_time(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def policy_from_dict(raw: dict[str, Any]) -> SlaPolicy:
    hours = raw["business_hours"]
    calendar = BusinessCalendar(
        tz=ZoneInfo(raw.get("timezone", "Europe/London")),
        start=_parse_time(hours["start"]),
        end=_parse_time(hours["end"]),
        days=frozenset(_WEEKDAYS[d] for d in hours["days"]),
        holidays=frozenset(
            d if isinstance(d, date) else date.fromisoformat(str(d)) for d in raw.get("bank_holidays", [])
        ),
    )
    if calendar.start >= calendar.end:
        raise ValueError("business_hours start must be before end")
    targets: dict[int, SlaTarget] = {}
    for key, spec in raw["priorities"].items():
        level = int(str(key).lstrip("Pp"))
        clock = spec.get("clock", "business")
        if clock not in ("24x7", "business"):
            raise ValueError(f"unknown SLA clock {clock!r} for {key}")
        targets[level] = SlaTarget(
            priority=level,
            name=spec["name"],
            respond_minutes=int(spec["respond_minutes"]),
            resolve_minutes=int(spec["resolve_minutes"]),
            clock=clock,
        )
    if set(targets) != {1, 2, 3, 4}:
        raise ValueError("the SLA policy must define P1 to P4")
    return SlaPolicy(calendar=calendar, targets=targets)


@lru_cache(maxsize=4)
def load_policy(path: str | None = None) -> SlaPolicy:
    """Load the SLA policy from a YAML file, or the bundled default."""
    if path:
        text = Path(path).read_text(encoding="utf-8")
    else:
        text = resources.files("triage.config").joinpath("sla.yaml").read_text(encoding="utf-8")
    return policy_from_dict(yaml.safe_load(text))
