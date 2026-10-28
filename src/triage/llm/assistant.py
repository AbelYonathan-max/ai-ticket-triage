"""Run the language model step safely: budget, circuit breaker, timing and guardrails in one place."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from triage.llm.base import LlmAssist, LlmError, LlmProvider, LlmRequest
from triage.llm.guard import CircuitBreaker, DailyTokenBudget, check_output, looks_like_injection

log = logging.getLogger(__name__)


@dataclass
class AssistOutcome:
    status: str  # ok, disabled, budget_exhausted, circuit_open, error
    provider: str
    assist: LlmAssist | None = None
    flags: list[str] = field(default_factory=list)
    review_reasons: list[str] = field(default_factory=list)
    tokens: int = 0
    latency_ms: int = 0


class Assistant:
    def __init__(
        self, provider: LlmProvider, budget: DailyTokenBudget, breaker: CircuitBreaker | None = None
    ):
        self.provider = provider
        self.budget = budget
        self.breaker = breaker or CircuitBreaker()

    def run(self, request: LlmRequest) -> AssistOutcome:
        name = self.provider.name
        if not self.budget.allow():
            return AssistOutcome("budget_exhausted", name, flags=["Daily AI token budget reached."])
        if not self.breaker.allow():
            return AssistOutcome("circuit_open", name, flags=["AI assistant paused after repeated errors."])
        injection = looks_like_injection(f"{request.subject}\n{request.body}")
        start = time.perf_counter()
        try:
            response = self.provider.assist(request)
        except LlmError as exc:
            self.breaker.record(ok=False)
            log.warning("llm_error", extra={"provider": name, "error": str(exc)})
            outcome = AssistOutcome(
                "error", name, flags=["The AI assistant was unavailable for this ticket."]
            )
            if injection:
                outcome.review_reasons.append(
                    "Possible prompt injection: the ticket text tries to instruct the AI."
                )
            return outcome
        latency = int((time.perf_counter() - start) * 1000)
        self.breaker.record(ok=True)
        self.budget.record(response.tokens)
        guarded = check_output(response.assist, {a.id for a in request.articles}, injection)
        return AssistOutcome(
            status="ok",
            provider=name,
            assist=guarded.assist,
            flags=guarded.flags,
            review_reasons=guarded.review_reasons,
            tokens=response.tokens,
            latency_ms=latency,
        )
