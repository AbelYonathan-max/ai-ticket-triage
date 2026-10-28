"""A deterministic stand-in for the language model, for local runs, tests and demos without Azure."""

from __future__ import annotations

import re

from triage.llm.base import LlmAssist, LlmRequest, LlmResponse
from triage.llm.guard import looks_like_injection

# "Hi team,", "Morning," or "Dear Service Desk," at the start of a ticket says nothing about the problem.
GREETING = re.compile(
    r"^\s*(?:hi|hello|hey|hiya|morning|afternoon|good (?:morning|afternoon|evening)|dear|to whom it may concern)"
    r"(?:[ \t]+[\w'/-]+){0,3}[ \t]*(?:[,!.:]+|(?=\n))\s*",
    re.IGNORECASE,
)


def first_sentence(text: str, limit: int = 200) -> str:
    text = GREETING.sub("", text.strip(), count=1)
    return re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0].strip()[:limit]


class StubProvider:
    name = "stub"

    def assist(self, request: LlmRequest) -> LlmResponse:
        first = first_sentence(request.body)
        summary = f"{request.subject.strip().rstrip('.')}: {first}" if first else request.subject.strip()
        if request.articles:
            top = request.articles[0]
            reply = (
                f'Thank you for getting in touch. Our guide "{top.title}" ({top.id}) covers this kind of '
                f"problem. {first_sentence(top.summary)} If the guide does not help, reply to this message "
                "and an analyst will pick it up."
            )
            kb_ids = [top.id]
        else:
            reply = (
                "Thank you for getting in touch. An analyst will look at your ticket. To help us, please "
                "reply with what you were doing when the problem started and any error message you saw."
            )
            kb_ids = []
        assist = LlmAssist(
            summary=summary,
            category=request.model_category,
            category_reason="Stub provider: repeats the classifier's category.",
            reply_draft=reply,
            kb_ids=kb_ids,
            missing_information=[],
            injection_suspected=looks_like_injection(f"{request.subject}\n{request.body}"),
        )
        return LlmResponse(assist=assist, tokens=0)
