"""Deterministic safety rules that sit on top of the model.

The model estimates impact and urgency from wording it has seen before. These rules catch the
situations where under-prioritising would be costly (an active security compromise, a possible
personal data breach, a patient-facing outage) and raise the priority. Rules can only ever make a
ticket more urgent or send it to a human; they never lower anything the model predicted.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

_CANT = r"(?:can'?t|cannot|can not|unable to|not able to|won'?t)"


def _gap(n: int) -> str:
    """Up to n characters without crossing a sentence boundary."""
    return r"[^.?!\n]{0," + str(n) + "}"


@dataclass(frozen=True)
class Rule:
    id: str
    description: str
    pattern: re.Pattern[str]
    min_impact: int | None = None  # raise impact to at least this level (1 = highest)
    min_urgency: int | None = None
    review_reason: str | None = None
    applies: Callable[[str, str], bool] = lambda category, ticket_type: True
    requires_impact: int | None = None  # only fires when impact is already at least this severe


@dataclass
class RuleOutcome:
    impact: int
    urgency: int
    fired: list[str] = field(default_factory=list)
    review_reasons: list[str] = field(default_factory=list)
    impact_changed: bool = False
    urgency_changed: bool = False


def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


_DEVICE = r"(laptop|phone|mobile|tablet|ipad|device|smart ?card|usb|memory stick)"
_NOT_ACCESSORY = r"(?!\s*(charger|bag|case|stand|cable|lead|sleeve|number|screen protector|power))"
_CLINICAL = (
    r"(patients?|clinic|theatres?|a ?& ?e|emergency department|prescri\w*|medication|ambulance|clinical|"
    r"safeguarding|discharge)"
)

RULES: tuple[Rule, ...] = (
    Rule(
        id="active-compromise",
        description="Someone clicked a phishing link, entered credentials, or malware is active.",
        pattern=_rx(
            r"\b(clicked|opened|entered|typed|gave|put)\b"
            + _gap(60)
            + r"\b(link|attachment|password|details|"
            r"credentials|code)\b|\bransom(ware)?\b|\b(files|documents)\b"
            + _gap(40)
            + r"\b(have been|were|got|are now)\s+(encrypted|renamed)\b|\bmalware\b|\bvirus\b|\btrojan\b|"
            r"\bhacked\b|\bcompromised\b|\b(sign|log)(ed)?[- ]?in\b"
            + _gap(40)
            + r"\b(from|in) (another|a different) country\b|\bmfa\b"
            + _gap(40)
            + r"\b(didn'?t|did not) "
            r"(request|ask)"
        ),
        min_urgency=1,
        review_reason="Possible active compromise: a security analyst should confirm containment steps.",
        applies=lambda category, ticket_type: category == "security",
    ),
    Rule(
        id="ransomware",
        description="Files are being encrypted or a ransom note has appeared: it can spread to shared drives.",
        pattern=_rx(
            r"\bransom(ware)?\b|\bpay\b"
            + _gap(30)
            + r"\bbitcoin\b|\b(\.locked|readme_restore|decrypt your files)\b"
        ),
        min_impact=2,
        min_urgency=1,
        review_reason="Possible ransomware: isolate the device from the network and start the security incident process.",
    ),
    Rule(
        id="lost-or-stolen-device",
        description="A device or smartcard that may hold or unlock organisational data is lost or stolen.",
        pattern=_rx(
            r"\b(lost|stolen|left|missing|nicked|can'?t find)\b"
            + _gap(50)
            + r"\b"
            + _DEVICE
            + r"\b"
            + _NOT_ACCESSORY
            + r"|\b"
            + _DEVICE
            + r"\b"
            + _NOT_ACCESSORY
            + _gap(40)
            + r"\b(was |has been |got )?(lost|stolen|missing|nicked)\b"
        ),
        min_impact=2,
        min_urgency=1,
        review_reason="Lost or stolen device: remote wipe and account checks may be needed.",
    ),
    Rule(
        id="personal-data-breach",
        description="Personal data may have been sent to the wrong person or exposed.",
        pattern=_rx(
            r"\b(sent|emailed|forwarded|shared|posted)\b"
            + _gap(60)
            + r"\b(wrong|incorrect)\s+(person|recipient|"
            r"address|email|patient|family|client|resident|customer)\b|\bdata breach\b|"
            r"\b(personal|patient|client|resident|customer|sensitive)\s+(data|information|details|records)\b"
            + _gap(60)
            + r"\b(sent|shared|exposed|leaked|lost)\b|\bby mistake\b"
            + _gap(40)
            + r"\b(sent|emailed|shared)\b|\b(sent|emailed|shared)\b"
            + _gap(80)
            + r"\bby mistake\b"
        ),
        min_impact=2,
        min_urgency=1,
        review_reason="Possible personal data breach: the 72-hour ICO reporting clock may apply.",
    ),
    Rule(
        id="organisation-wide",
        description="The ticket says the problem affects the whole organisation, a whole site or every site.",
        pattern=_rx(
            r"\b(entire|whole)\s+(organisation|organization|trust|council|company|building|site|hospital)\b|"
            r"\ball (sites|users|staff|wards|offices)\b|\bevery (site|office|ward|user)\b|"
            r"\b(organisation|organization|trust|council|site)[- ]wide\b|\bacross the (organisation|"
            r"organization|trust|council|whole)\b|\bnobody\b"
            + _gap(30)
            + r"\b(can|is able)\b|\bno ?one\b"
            + _gap(30)
            + r"\bcan\b|\bthe public (can'?t|cannot)\b"
        ),
        min_impact=1,
    ),
    Rule(
        id="several-people",
        description="The ticket says several people or a whole team are affected.",
        pattern=_rx(
            r"\b(whole|entire)\s+(team|office|floor|ward|unit|department)\b|\beveryone\b|\ball of us\b|"
            r"\b(several|multiple|lots of|a few|three|four|five|six|many)\s+(people|users|colleagues|staff|"
            r"of us|members)\b|\b(my|our|the)\s+(colleagues|team(mates)?)\b"
            + _gap(40)
            + r"\b(same|too|also|as well)\b|\bsame (problem|issue)\b|\b(it'?s|it is) not just me\b"
        ),
        min_impact=2,
    ),
    Rule(
        id="major-outage",
        description="A service is down for many users: treat as a possible major incident.",
        pattern=_rx(
            r"\b(down|outage|offline|lost (the )?(internet|network|connection|phones|power|wi-?fi)|"
            r"no (network|internet|connection|email|phones|wi-?fi)|(isn'?t|not|aren'?t) (working|loading|"
            r"receiving|reachable)|can'?t (use|get into|access|connect|process|take)|unavailable)\b"
        ),
        min_urgency=1,
        review_reason="Possible major incident: many users are affected, confirm and start the major incident process.",
        applies=lambda category, ticket_type: ticket_type == "incident",
        requires_impact=1,
    ),
    Rule(
        id="patient-safety",
        description="A clinical or patient-facing service is not working.",
        pattern=_rx(
            r"\b" + _CLINICAL + r"\b" + _gap(80) + _CANT + r"|" + _CANT + _gap(80) + r"\b" + _CLINICAL + r"\b"
        ),
        min_urgency=1,
        review_reason="Clinical safety: a person should confirm the priority of a patient-facing problem.",
        applies=lambda category, ticket_type: ticket_type == "incident",
    ),
    Rule(
        id="work-stopped",
        description="The person says they cannot work at all.",
        pattern=_rx(
            r"\b" + _CANT + r" (do any|do my|do anything|work|get any)\b|\bcompletely (down|stuck|blocked)\b|"
            r"\bat a standstill\b|\bdead in the water\b|\b(service|system)\b" + _gap(30) + r"\bhas stopped\b"
        ),
        min_urgency=1,
        applies=lambda category, ticket_type: ticket_type == "incident",
    ),
    Rule(
        id="deadline",
        description="The ticket mentions a deadline today.",
        pattern=_rx(
            r"\bdeadline\b"
            + _gap(20)
            + r"\b(today|this (morning|afternoon)|tonight)\b|\bby (\d{1,2}(:\d\d)?\s?"
            r"(am|pm)|end of (the )?day|close of play|cop|lunch(time)?|tonight)\b|\bin (\d+|five|ten|fifteen|"
            r"twenty|thirty) (mins?|minutes)\b|\b(today|this afternoon)\b"
            + _gap(30)
            + r"\b(meeting|deadline|"
            r"interview|submission|presentation)\b|\bdeadline (at|is) \d"
        ),
        min_urgency=2,
    ),
)


def apply_rules(text: str, category: str, ticket_type: str, impact: int, urgency: int) -> RuleOutcome:
    """Apply every matching rule. Impact and urgency only ever move towards 1 (more severe)."""
    outcome = RuleOutcome(impact=impact, urgency=urgency)
    for rule in RULES:
        if not rule.applies(category, ticket_type) or not rule.pattern.search(text):
            continue
        if rule.requires_impact is not None and outcome.impact > rule.requires_impact:
            continue
        changed = False
        if rule.min_impact is not None and outcome.impact > rule.min_impact:
            outcome.impact = rule.min_impact
            outcome.impact_changed = changed = True
        if rule.min_urgency is not None and outcome.urgency > rule.min_urgency:
            outcome.urgency = rule.min_urgency
            outcome.urgency_changed = changed = True
        if rule.review_reason:
            outcome.review_reasons.append(rule.review_reason)
        if changed or rule.review_reason:
            outcome.fired.append(rule.id)
    return outcome
