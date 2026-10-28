"""The triage pipeline: redact, classify, apply safety rules, prioritise, route and assist.

Order matters. Redaction runs first so that nothing downstream (the model, the database, the
language model, the logs) ever sees the original text. The classifier then predicts category, type,
impact and urgency; the safety rules can only raise impact or urgency; the ITIL matrix turns impact
and urgency into a priority with SLA due times. Anything uncertain or high risk goes to a person.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from triage.domain.itil import SlaPolicy, priority_from
from triage.domain.rules import apply_rules
from triage.domain.taxonomy import MAJOR_INCIDENT_GROUP, resolver_group
from triage.kb.retrieve import KbHit, KnowledgeBase
from triage.llm.assistant import Assistant, AssistOutcome
from triage.llm.base import LlmRequest
from triage.ml.model import TriageModel
from triage.privacy.redact import redact_ticket

TYPE_REVIEW_THRESHOLD = 0.6
UNDER_PRIORITY_THRESHOLD = 0.35  # P(urgency = high) above this when urgency was not predicted high


@dataclass
class TriageResult:
    subject: str  # redacted
    body: str  # redacted
    pii_counts: dict[str, int]
    special_category_hint: bool
    category: str
    category_confidence: float
    category_probabilities: dict[str, float]
    ticket_type: str
    type_confidence: float
    model_impact: int
    model_urgency: int
    impact: int
    urgency: int
    priority: int
    priority_name: str
    rules_fired: list[str]
    resolver_group: str
    major_incident: bool
    needs_review: bool
    review_reasons: list[str]
    flags: list[str]
    opened_at: datetime
    respond_by: datetime
    resolve_by: datetime
    explanation: dict[str, list[tuple[str, float]]]
    kb_hits: list[KbHit]
    assist: AssistOutcome | None
    model_version: str
    latency_ms: int = 0
    extra: dict[str, object] = field(default_factory=dict)

    @property
    def pii_total(self) -> int:
        return sum(self.pii_counts.values())


def _pct(x: float) -> str:
    return f"{100 * x:.0f}%"


class TriageService:
    def __init__(
        self,
        model: TriageModel,
        kb: KnowledgeBase,
        policy: SlaPolicy,
        assistant: Assistant | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.model = model
        self.kb = kb
        self.policy = policy
        self.assistant = assistant
        self.clock = clock

    def triage(
        self, subject: str, body: str, opened_at: datetime | None = None, use_llm: bool = True
    ) -> TriageResult:
        start = time.perf_counter()
        opened = opened_at or self.clock()
        red_subject, red_body = redact_ticket(subject, body)
        counts = dict(red_subject.counts)
        for kind, n in red_body.counts.items():
            counts[kind] = counts.get(kind, 0) + n
        special = red_subject.special_category_hint or red_body.special_category_hint
        text = f"{red_subject.text}\n{red_body.text}"

        pred = self.model.predict(red_subject.text, red_body.text)
        category = pred["category"].label
        ticket_type = pred["type"].label
        model_impact = int(pred["impact"].label)
        model_urgency = int(pred["urgency"].label)
        outcome = apply_rules(text, category, ticket_type, model_impact, model_urgency)
        priority = priority_from(outcome.impact, outcome.urgency)
        respond_by, resolve_by = self.policy.due_times(priority, opened)
        major = priority == 1 and outcome.impact == 1

        reasons: list[str] = []
        flags: list[str] = []
        cat_conf = pred["category"].confidence
        if cat_conf < self.model.review_threshold:
            reasons.append(
                f"Low confidence in the category ({_pct(cat_conf)}, below {_pct(self.model.review_threshold)}): "
                "check the routing."
            )
        if pred["type"].confidence < TYPE_REVIEW_THRESHOLD:
            reasons.append(
                f"Unsure whether this is an incident or a request ({_pct(pred['type'].confidence)})."
            )
        p_high = pred["urgency"].probabilities.get("1", 0.0)
        if outcome.urgency > 1 and p_high >= UNDER_PRIORITY_THRESHOLD:
            reasons.append(
                f"The model gives a {_pct(p_high)} chance that work has stopped or it is time-critical: "
                "check the urgency."
            )
        if priority == 1:
            reasons.append("P1: a person confirms every critical ticket.")
        reasons.extend(r for r in outcome.review_reasons if r not in reasons)
        if special:
            flags.append("May contain health or other special category data: handle with extra care.")
        if counts:
            flags.append(f"Removed {sum(counts.values())} item(s) of personal data before triage.")

        hits = self.kb.search(text, category=category)
        assist: AssistOutcome | None = None
        if use_llm and self.assistant is not None:
            assist = self.assistant.run(
                LlmRequest(red_subject.text, red_body.text, category, [h.article for h in hits])
            )
            flags.extend(assist.flags)
            reasons.extend(assist.review_reasons)
            if assist.assist is not None and assist.assist.category != category:
                reasons.append(
                    f"The AI second opinion suggests a different category ({assist.assist.category}): "
                    "check the routing."
                )

        group = resolver_group(category)
        return TriageResult(
            subject=red_subject.text,
            body=red_body.text,
            pii_counts=counts,
            special_category_hint=special,
            category=category,
            category_confidence=round(cat_conf, 4),
            category_probabilities=pred["category"].probabilities,
            ticket_type=ticket_type,
            type_confidence=round(pred["type"].confidence, 4),
            model_impact=model_impact,
            model_urgency=model_urgency,
            impact=outcome.impact,
            urgency=outcome.urgency,
            priority=priority,
            priority_name=self.policy.targets[priority].name,
            rules_fired=outcome.fired,
            resolver_group=f"{MAJOR_INCIDENT_GROUP} and {group}" if major else group,
            major_incident=major,
            needs_review=bool(reasons),
            review_reasons=reasons,
            flags=flags,
            opened_at=opened.astimezone(UTC),
            respond_by=respond_by,
            resolve_by=resolve_by,
            explanation={head: p.top_terms for head, p in pred.items()},
            kb_hits=hits,
            assist=assist,
            model_version=self.model.version,
            latency_ms=int((time.perf_counter() - start) * 1000),
        )
