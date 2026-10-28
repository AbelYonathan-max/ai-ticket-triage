import pytest

from triage.privacy.redact import luhn_is_valid, nhs_number_is_valid, redact


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("contact me on jane.doe@example.org please", "EMAIL"),
        ("my mobile is 07700 900123", "PHONE"),
        ("ring 020 7946 0018 ext 4", "PHONE"),
        ("call +44 (0)20 7946 0018", "PHONE"),
        ("call +44 7700 900123", "PHONE"),
        ("office 0161 496 0000", "PHONE"),
        ("patient NHS number 943 476 5919 can't be found", "NHS_NUMBER"),
        ("NI number AB 12 34 56 C", "NI_NUMBER"),
        ("card 4111 1111 1111 1111 was charged", "CARD_NUMBER"),
        ("my laptop at SW1A 1AA", "POSTCODE"),
        ("printer at m1 1ae is down", "POSTCODE"),
        ("server 10.20.30.40 unreachable", "IP_ADDRESS"),
        ("staff number: 1234567", "STAFF_ID"),
        ("my password is Summer2026!", "SECRET"),
        ("password: hunter", "SECRET"),
        ("Hi there,\nmy name is Priya Patel and I need help", "NAME"),
        ("Dr Okafor cannot log in", "NAME"),
        ("Hi Sarah,\nthe printer is broken", "NAME"),
        ("Printer broken.\n\nThanks,\nTom Baker", "NAME"),
        ("Printer broken. Cheers, Tom", "NAME"),
        ("From: Grace Hopper\nSent: Monday", "NAME"),
        ("please set up an account for new starter Amir Khan on Monday", "NAME"),
        ("This is Wendy from payroll, the scanner is broken", "NAME"),
    ],
)
def test_detects_personal_data(text: str, kind: str) -> None:
    result = redact(text)
    assert result.counts.get(kind, 0) >= 1, result.text
    assert f"[{kind}]" in result.text


@pytest.mark.parametrize(
    "text",
    [
        "my password is not working since the reset",
        "my password has expired",
        "Hi IT, the VPN keeps dropping",
        "Hello Service Desk, Outlook will not open",
        "Thanks,\nFinance Team",
        "error code 0x80070005 when installing",
        "ticket 4111 1111 1111 1112 is a reference not a card",
        "I need Microsoft Teams installed",
        "we have 120 users on the third floor",
        "Office 365 licence for Windows 11",
    ],
)
def test_leaves_ordinary_text_alone(text: str) -> None:
    result = redact(text)
    assert result.total == 0, (result.text, result.counts)
    assert result.text == text


def test_nhs_number_checksum() -> None:
    assert nhs_number_is_valid("9434765919")
    assert not nhs_number_is_valid("9434765918")
    assert not nhs_number_is_valid("12345")


def test_luhn() -> None:
    assert luhn_is_valid("4111111111111111")
    assert not luhn_is_valid("4111111111111112")


def test_nhs_number_flags_special_category() -> None:
    assert redact("NHS no 943 476 5919").special_category_hint
    assert redact("I have a hospital appointment for my diagnosis").special_category_hint
    assert not redact("printer jammed").special_category_hint


def test_multiple_items_counted() -> None:
    text = (
        "Hi Mark,\nI'm locked out. My email is a.b@example.com and my mobile is 07700 900456.\n"
        "My password is Winter2025! if that helps.\n\nKind regards,\nAisha Rahman"
    )
    result = redact(text)
    assert result.counts == {"EMAIL": 1, "PHONE": 1, "SECRET": 1, "NAME": 2}
    assert "Winter2025" not in result.text
    assert "a.b@example.com" not in result.text
    assert "Aisha" not in result.text


def test_redaction_is_idempotent() -> None:
    once = redact("email me at x@y.com or call 07700 900123").text
    assert redact(once).text == once
