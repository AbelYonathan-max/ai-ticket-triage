"""Guardrails around the language model: input checks, output checks, a circuit breaker and a budget.

Each check maps to a risk in docs/threat-model.md (OWASP Top 10 for LLM applications):
- prompt injection (LLM01): heuristic input check plus the model's own flag; either sends the ticket
  to a person and withholds the reply draft.
- insecure output handling (LLM05): the output must validate against the schema, cite only articles
  that were retrieved, make no false claims and never ask for secrets. Drafts are shown as text,
  never rendered as HTML.
- excessive agency (LLM06): the model has no tools and cannot set priority.
- unbounded consumption (LLM10): timeout, circuit breaker and a daily token budget.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from triage.llm.base import LlmAssist

INJECTION = re.compile(
    r"\b(ignore|disregard|forget|override)\b[^.?!\n]{0,40}\b(instructions?|rules|prompts?|guidelines|"
    r"above|previous)\b|\b(system|developer) (prompt|message|instructions?)\b|\byou are now\b|"
    r"\b(pretend|act) (to be|as) (an?|the) (ai|assistant|admin|administrator|model)\b|\bjailbreak\b|"
    r"\b(reveal|print|show|repeat)\b[^.?!\n]{0,30}\b(your|the) (prompt|instructions|rules)\b|"
    r"\b(set|change|make|mark)\b[^.?!\n]{0,30}\b(priority|p[1-4]|severity)\b[^.?!\n]{0,20}\b(to|as)\b|"
    r"</?(system|assistant|instructions?)>|\[(system|inst)\]",
    re.IGNORECASE,
)

FALSE_CLAIM = re.compile(
    r"\b(i|we)\s*(have|'ve|’ve)?\s+(now\s+)?(reset|unlocked|fixed|resolved|restored|granted|installed|"
    r"changed|enabled|disabled|removed|deleted|re-?imaged|replaced|sent you)\b|"
    r"\b(has|have) (now )?been (reset|unlocked|fixed|resolved|restored|granted|installed|replaced)\b|"
    r"\b(is|are) now (fixed|resolved|working|unlocked)\b",
    re.IGNORECASE,
)

SECRET_REQUEST = re.compile(
    r"\b(send|tell|give|share|provide|confirm|reply with|type|enter|include)\b[^.?!\n]{0,50}"
    r"\b(password|passcode|pin|mfa code|verification code|one[- ]time (pass)?code|otp|security code|"
    r"authenticator code|recovery code|6[- ]digit code)\b",
    re.IGNORECASE,
)

PLACEHOLDER = re.compile(
    r"\[(EMAIL|PHONE|NAME|NHS_NUMBER|NI_NUMBER|CARD_NUMBER|IP_ADDRESS|POSTCODE|STAFF_ID|SECRET)\]"
)


def looks_like_injection(text: str) -> bool:
    return bool(INJECTION.search(text))


@dataclass
class GuardResult:
    assist: LlmAssist
    flags: list[str] = field(default_factory=list)
    review_reasons: list[str] = field(default_factory=list)
    reply_withheld: bool = False


def check_output(assist: LlmAssist, allowed_kb_ids: set[str], input_injection: bool) -> GuardResult:
    """Validate the model's output. Unsafe parts are removed and the reason is recorded."""
    result = GuardResult(assist=assist)
    unknown = [k for k in assist.kb_ids if k not in allowed_kb_ids]
    if unknown:
        result.flags.append(f"Removed citations to articles that were not supplied: {', '.join(unknown)}")
        assist = assist.model_copy(update={"kb_ids": [k for k in assist.kb_ids if k in allowed_kb_ids]})

    withhold: list[str] = []
    if input_injection or assist.injection_suspected:
        withhold.append("the ticket text looks like it tries to instruct the AI")
        result.review_reasons.append(
            "Possible prompt injection: the ticket text tries to instruct the AI, so its reply draft was withheld."
        )
    if FALSE_CLAIM.search(assist.reply_draft):
        withhold.append("the draft claimed an action had already been taken")
    if SECRET_REQUEST.search(assist.reply_draft):
        withhold.append("the draft asked for a password or code")
    if PLACEHOLDER.search(assist.reply_draft):
        withhold.append("the draft contained redaction tokens")
    if withhold:
        result.flags.append("Reply draft withheld: " + "; ".join(withhold) + ".")
        result.reply_withheld = True
        assist = assist.model_copy(update={"reply_draft": ""})
    result.assist = assist
    return result


class CircuitBreaker:
    """Stop calling the provider for a while after repeated failures, so a broken dependency is cheap."""

    def __init__(
        self, failures: int = 3, reset_after: float = 60.0, clock: Callable[[], float] = time.monotonic
    ):
        self.failures = failures
        self.reset_after = reset_after
        self._clock = clock
        self._count = 0
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    def allow(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return True
            if self._clock() - self._opened_at >= self.reset_after:
                self._opened_at = None  # half open: let one call through
                self._count = self.failures - 1
                return True
            return False

    def record(self, ok: bool) -> None:
        with self._lock:
            if ok:
                self._count = 0
                self._opened_at = None
                return
            self._count += 1
            if self._count >= self.failures:
                self._opened_at = self._clock()

    @property
    def is_open(self) -> bool:
        return self._opened_at is not None


class DailyTokenBudget:
    """A per-replica cap on tokens per UTC day. The Azure deployment's rate limit is the hard backstop."""

    def __init__(self, limit: int, today: Callable[[], date] = lambda: datetime.now(UTC).date()) -> None:
        self.limit = limit
        self._today = today
        self._day = today()
        self._used = 0
        self._lock = threading.Lock()

    def _roll(self) -> None:
        if self._today() != self._day:
            self._day = self._today()
            self._used = 0

    def allow(self) -> bool:
        with self._lock:
            self._roll()
            return self._used < self.limit

    def record(self, tokens: int) -> None:
        with self._lock:
            self._roll()
            self._used += max(0, tokens)

    @property
    def used(self) -> int:
        with self._lock:
            self._roll()
            return self._used
