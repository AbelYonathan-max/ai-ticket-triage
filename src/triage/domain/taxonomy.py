"""Service desk taxonomy: ticket categories, ticket types and resolver groups.

Categories follow how a typical UK public sector service desk splits its queues. Each category maps
to the resolver group that owns it. The labelling guide in docs/labelling-guide.md explains the
boundaries between categories, which is what the model and the reviewers both rely on.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Category:
    code: str
    label: str
    group: str
    description: str


CATEGORIES: dict[str, Category] = {
    c.code: c
    for c in (
        Category(
            "access",
            "Accounts and access",
            "Service Desk (1st line)",
            "Passwords, locked accounts, MFA, smartcards, new starters, leavers and permissions to systems "
            "or network folders.",
        ),
        Category(
            "hardware",
            "Hardware and devices",
            "End User Computing",
            "Laptops, desktops, monitors, docking stations, peripherals, desk and mobile phones, and "
            "equipment requests.",
        ),
        Category(
            "software",
            "Software and applications",
            "Application Support",
            "Installing, licensing, updating or fixing applications, including line-of-business systems, "
            "browsers and virtual apps.",
        ),
        Category(
            "m365",
            "Email, Teams and Microsoft 365",
            "Microsoft 365 Team",
            "Outlook, mailboxes and shared mailboxes, calendars, Teams, SharePoint, OneDrive and "
            "distribution lists.",
        ),
        Category(
            "network",
            "Network, Wi-Fi and VPN",
            "Network Operations",
            "Wi-Fi, VPN and remote access, internet connectivity, network drives and network ports.",
        ),
        Category(
            "printing",
            "Printing and scanning",
            "End User Computing",
            "Printers, print queues, secure print release, toner and paper, scanning and scan-to-email.",
        ),
        Category(
            "security",
            "Security",
            "Security Operations",
            "Phishing, malware, suspicious sign-ins, lost or stolen devices, data sent to the wrong person "
            "and security questions.",
        ),
    )
}

TICKET_TYPES: dict[str, str] = {
    "incident": "Incident",
    "request": "Service request",
}

IMPACT_LABELS: dict[int, str] = {
    1: "High: many users, a whole site or a critical service",
    2: "Medium: a team, a department or several people",
    3: "Low: one person",
}

URGENCY_LABELS: dict[int, str] = {
    1: "High: work has stopped or it is time-critical",
    2: "Medium: work is affected but there is a workaround",
    3: "Low: it can wait",
}

MAJOR_INCIDENT_GROUP = "Major Incident Manager"


def category_label(code: str) -> str:
    return CATEGORIES[code].label if code in CATEGORIES else code


def resolver_group(category: str) -> str:
    return CATEGORIES[category].group if category in CATEGORIES else "Service Desk (1st line)"
