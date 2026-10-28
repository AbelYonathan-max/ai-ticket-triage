"""Remove personal data from ticket text before anything else sees it.

Redaction runs first, before the model, the database and the language model. Only the redacted
text is stored or sent anywhere, which is the main data minimisation control in the DPIA.

Detectors are deliberately simple and testable: regular expressions with checksum validation where
one exists (NHS numbers use modulus 11, card numbers use the Luhn check). Names are the hardest
case; the heuristics below catch the common patterns in service desk tickets (greetings, sign-offs,
"my name is", titles, email headers) and the DPIA records the residual risk.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

# Capitalised words that look like names after a greeting or trigger word but are not people.
_NOT_NAMES = {
    "it",
    "team",
    "all",
    "there",
    "service",
    "servicedesk",
    "helpdesk",
    "support",
    "everyone",
    "guys",
    "folks",
    "sir",
    "madam",
    "both",
    "again",
    "desk",
    "microsoft",
    "teams",
    "office",
    "outlook",
    "windows",
    "excel",
    "word",
    "adobe",
    "google",
    "azure",
    "citrix",
    "oracle",
    "sharepoint",
    "onedrive",
    "power",
    "the",
    "my",
    "our",
    "your",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
    "morning",
    "afternoon",
    "evening",
    "please",
    "thanks",
    "thank",
    "regards",
    "best",
    "hello",
    "hi",
    "dear",
    "urgent",
    "help",
    "kind",
    "many",
    "warm",
    "cheers",
    "ta",
    "it's",
    "its",
    "this",
    "that",
    "we",
    "they",
    "he",
    "she",
    "you",
    "i",
    "a",
    "an",
    "no",
    "yes",
    "ok",
    "okay",
    "vpn",
    "nhs",
}

_NAME = r"[A-Z][a-z'’\-]+(?:[ \t]+[A-Z][a-z'’\-]+){0,2}"


@dataclass
class Redaction:
    text: str
    counts: dict[str, int] = field(default_factory=dict)
    special_category_hint: bool = False

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def nhs_number_is_valid(digits: str) -> bool:
    """Modulus 11 check used by NHS numbers."""
    if len(digits) != 10 or not digits.isdigit():
        return False
    total = sum(int(d) * (10 - i) for i, d in enumerate(digits[:9]))
    check = 11 - (total % 11)
    if check == 11:
        check = 0
    return check != 10 and check == int(digits[9])


def luhn_is_valid(digits: str) -> bool:
    if not 13 <= len(digits) <= 19 or not digits.isdigit():
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
CARD = re.compile(r"(?<!\d)(?:\d[ \-]?){12,18}\d(?!\d)")
NHS = re.compile(r"(?<![\d\-])\d{3}[ \-]?\d{3}[ \-]?\d{4}(?![\d\-])")
NI = re.compile(
    r"\b(?!BG|GB|KN|NK|NT|TN|ZZ)[ABCEGHJ-PRSTW-Z][ABCEGHJ-NPRSTW-Z][ ]?\d{2}[ ]?\d{2}[ ]?\d{2}[ ]?[A-D]\b",
    re.IGNORECASE,
)
PHONE = re.compile(
    r"(?<![\w+])(?:\+44[ \-]?(?:\(0\)[ \-]?)?|\(?0)\d{2,4}\)?[ \-]?\d{3,4}[ \-]?\d{3,4}(?![\w])"
)
IPV4 = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")
POSTCODE = re.compile(
    r"\b(?:GIR ?0AA|[A-PR-UWYZ][A-HK-Y]?\d[A-Z\d]? ?\d[ABD-HJLNP-UW-Z]{2})\b",
    re.IGNORECASE,
)
STAFF_ID = re.compile(
    r"\b(?P<label>(?:staff|employee|payroll|personnel|badge)\s*(?:no\.?|number|num|id|ref)\.?\s*[:#]?\s*)"
    r"(?P<value>[A-Z]{0,3}\d{4,10})\b",
    re.IGNORECASE,
)
SECRET = re.compile(
    r"\b(?P<label>(?:password|passcode|passphrase|pwd|pin(?: number| code)?)\b"
    r"(?:\s*(?P<sep>[:=])\s*|\s+(?P<verb>is|was|will be|=)\s+))"
    r"(?P<value>\"[^\"]{1,64}\"|'[^']{1,64}'|\S{1,64})",
    re.IGNORECASE,
)
_SECRET_STOPWORDS = {
    "reset",
    "expired",
    "changed",
    "change",
    "incorrect",
    "wrong",
    "not",
    "locked",
    "blank",
    "working",
    "required",
    "needed",
    "the",
    "my",
    "a",
    "same",
    "different",
    "correct",
    "right",
    "fine",
    "ok",
}
TITLE_NAME = re.compile(r"\b(?:Mr|Mrs|Ms|Miss|Mx|Dr|Prof)\.?\s+" + _NAME)
MY_NAME = re.compile(r"\b(?P<lead>(?i:my name is|my name's)\s+)(?P<name>" + _NAME + ")")
THIS_IS = re.compile(
    r"\b(?P<lead>(?i:this is|it'?s)\s+)(?P<name>" + _NAME + r")(?=\s+(?i:from|in|at|on)\b|,)"
)
GREETING = re.compile(
    r"(?m)^(?P<lead>[ \t]*(?i:hi|hello|hey|dear|morning|good morning|good afternoon|afternoon)[ \t]+)"
    r"(?P<name>[A-Z][a-z'’\-]+(?:[ \t]+[A-Z][a-z'’\-]+)?)(?P<tail>[ \t]*[,!.\n])"
)
SIGNOFF_NEXT_LINE = re.compile(
    r"(?m)^(?P<lead>[ \t]*(?i:thanks|thank you|many thanks|thanks again|kind regards|best regards|regards|"
    r"best wishes|best|cheers|warm regards|ta|sent from my \w+)[ \t,.!]*\r?\n(?:[ \t]*\r?\n)*[ \t]*)"
    r"(?P<name>" + _NAME + r")[ \t]*$"
)
SIGNOFF_SAME_LINE = re.compile(
    r"(?m)(?P<lead>\b(?i:thanks|thank you|many thanks|kind regards|regards|best wishes|cheers)[ \t]*[,\-][ \t]*)"
    r"(?P<name>" + _NAME + r")(?=[ \t]*(?:$|[(\[,|/\-–]|\d))"
)
HEADER_NAME = re.compile(
    r"(?m)^(?P<lead>[ \t]*(?i:from|to|cc|sent by|reported by):[ \t]*)(?P<name>" + _NAME + ")"
)
TRIGGER_NAME = re.compile(
    r"\b(?P<lead>(?i:new starter|starter|leaver|colleague|my manager|line manager|employee|patient|called|"
    r"named)\s+(?i:is\s+|was\s+)?)(?P<name>[A-Z][a-z'’\-]+\s+[A-Z][a-z'’\-]+)\b"
)
HEALTH_HINT = re.compile(
    r"\b(diagnos\w*|medical condition|disabilit\w*|pregnan\w*|sick note|fit note|mental health|cancer|"
    r"chemotherapy|hiv|surgery|therapy|counselling|occupational health|medication for)\b",
    re.IGNORECASE,
)


def _looks_like_name(name: str) -> bool:
    words = name.split()
    return bool(words) and all(w.lower().strip("'’-") not in _NOT_NAMES for w in words)


def _secret_value_looks_real(match: re.Match[str]) -> bool:
    value = match.group("value")
    bare = value.strip("\"'").rstrip(".,;!?)")
    if bare.lower() in _SECRET_STOPWORDS or not bare:
        return False
    if value[:1] in "\"'" or match.group("sep"):
        return True
    # After "is" or "was", only treat it as a secret if it looks like one (digits or symbols).
    return bool(re.search(r"[\d!@#$%^&*?£_+=]", bare)) and len(bare) >= 4


def redact(text: str) -> Redaction:
    """Return text with personal data replaced by [TOKENS], plus counts by type."""
    counts: Counter[str] = Counter()
    # Browsers and email send CRLF line endings; the line-based name patterns expect "\n".
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    def sub(pattern: re.Pattern[str], repl: Callable[[re.Match[str]], str], value: str) -> str:
        return pattern.sub(repl, value)

    def token(kind: str) -> Callable[[re.Match[str]], str]:
        def _replace(m: re.Match[str]) -> str:
            counts[kind] += 1
            return f"[{kind}]"

        return _replace

    def checked(kind: str, validator: Callable[[str], bool]) -> Callable[[re.Match[str]], str]:
        def _replace(m: re.Match[str]) -> str:
            digits = re.sub(r"\D", "", m.group(0))
            if validator(digits):
                counts[kind] += 1
                return f"[{kind}]"
            return m.group(0)

        return _replace

    def keep_lead(kind: str, check_name: bool = True) -> Callable[[re.Match[str]], str]:
        def _replace(m: re.Match[str]) -> str:
            name = m.group("name")
            if check_name and not _looks_like_name(name):
                return m.group(0)
            counts[kind] += 1
            tail = m.groupdict().get("tail") or ""
            return f"{m.group('lead')}[{kind}]{tail}"

        return _replace

    def secret(m: re.Match[str]) -> str:
        if not _secret_value_looks_real(m):
            return m.group(0)
        counts["SECRET"] += 1
        return f"{m.group('label')}[SECRET]"

    def staff(m: re.Match[str]) -> str:
        counts["STAFF_ID"] += 1
        return f"{m.group('label')}[STAFF_ID]"

    out = text
    out = sub(SECRET, secret, out)
    out = sub(EMAIL, token("EMAIL"), out)
    out = sub(CARD, checked("CARD_NUMBER", luhn_is_valid), out)
    out = sub(NHS, checked("NHS_NUMBER", nhs_number_is_valid), out)
    out = sub(NI, token("NI_NUMBER"), out)
    out = sub(PHONE, token("PHONE"), out)
    out = sub(IPV4, token("IP_ADDRESS"), out)
    out = sub(STAFF_ID, staff, out)
    out = sub(POSTCODE, token("POSTCODE"), out)
    out = sub(TITLE_NAME, token("NAME"), out)
    out = sub(MY_NAME, keep_lead("NAME"), out)
    out = sub(THIS_IS, keep_lead("NAME"), out)
    out = sub(HEADER_NAME, keep_lead("NAME"), out)
    out = sub(GREETING, keep_lead("NAME"), out)
    out = sub(SIGNOFF_NEXT_LINE, keep_lead("NAME"), out)
    out = sub(SIGNOFF_SAME_LINE, keep_lead("NAME"), out)
    out = sub(TRIGGER_NAME, keep_lead("NAME"), out)

    special = counts.get("NHS_NUMBER", 0) > 0 or bool(HEALTH_HINT.search(out))
    return Redaction(text=out, counts=dict(counts), special_category_hint=special)


def redact_ticket(subject: str, body: str) -> tuple[Redaction, Redaction]:
    return redact(subject), redact(body)
