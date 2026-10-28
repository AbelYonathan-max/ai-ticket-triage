"""Generate synthetic UK service desk tickets for training.

No real tickets or people are used. Names, phone numbers (Ofcom drama ranges), email addresses
(example.org) and NHS numbers (the 999 test range) are invented, so the training set holds no
personal data at all. That is a deliberate privacy-by-design choice recorded in the DPIA.

Each ticket is built from an issue (which fixes the category and ticket type), optional context,
and optional phrases that signal impact and urgency. The impact and urgency labels come from the
phrases that were added, so the labels are consistent with the text. Noise (typos, lower case,
text-speak, signatures, disclaimers, forwarded headers) makes the text closer to real tickets.

Usage:  python -m triage.data.synthetic --count 8400 --seed 7 --out data/synthetic/train.csv
"""

from __future__ import annotations

import argparse
import csv
import random
import re
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------------------------
# Vocabulary used to fill {slots} in the templates
# --------------------------------------------------------------------------------------------

SLOTS: dict[str, list[str]] = {
    "device": [
        "laptop",
        "PC",
        "desktop",
        "Surface",
        "ThinkPad",
        "Dell laptop",
        "HP laptop",
        "work laptop",
        "computer",
        "machine",
    ],
    "vendor": ["Dell", "HP", "Lenovo", "Microsoft", "Windows"],
    "app": [
        "Excel",
        "Word",
        "PowerPoint",
        "Adobe Acrobat",
        "Acrobat Reader",
        "Visio",
        "Project",
        "SAP",
        "Power BI Desktop",
        "SPSS",
        "OneNote",
        "Snipping Tool",
        "Notepad++",
        "QGIS",
        "AutoCAD",
    ],
    "software": [
        "Visio",
        "Adobe Acrobat Pro",
        "Power BI Desktop",
        "Python",
        "SPSS",
        "Tableau",
        "Notepad++",
        "R and RStudio",
        "Zoom",
        "Snagit",
        "Microsoft Project",
        "AutoCAD",
        "QGIS",
        "Visual Studio Code",
        "7-Zip",
        "NVivo",
        "Stata",
        "Camtasia",
        "Audacity",
    ],
    "lob": [
        "the HR system",
        "the finance system",
        "Oracle Fusion",
        "SAP",
        "EMIS",
        "SystmOne",
        "Cerner",
        "Mosaic",
        "Civica",
        "the case management system",
        "the housing system",
        "the CRM",
        "Dynamics 365",
        "the payroll system",
        "iTrent",
        "Agresso",
        "Unit4",
        "the planning portal",
        "Workday",
        "RiO",
        "Liquidlogic",
        "Uniform",
        "ESR",
        "TrakCare",
        "the booking system",
        "the council tax system",
        "the benefits system",
        "Capita",
        "the records system",
    ],
    "lob_err": [
        "Object reference not set to an instance of an object",
        "Session expired",
        "Unable to connect to the database",
        "HTTP 500 Internal Server Error",
        "Invalid user context",
        "Request timed out",
        "Error 1004",
        "Runtime error 91",
        "Service unavailable",
        "Login failed for user",
    ],
    "error": [
        "error 0x80070005",
        "error 500",
        "'something went wrong'",
        "error code 53003",
        "error 0x800CCC0E",
        "'license not found'",
        "error 0x80004005",
        "error 1603",
        "code 0xc0000225",
        "'The trust relationship between this workstation and the primary domain failed'",
    ],
    "site": [
        "the Kingston office",
        "the Croydon hub",
        "the Civic Centre",
        "Riverside House",
        "Victoria Street",
        "the Leeds office",
        "Ward 7",
        "Ward 12",
        "outpatients",
        "the main hospital",
        "St Mary's site",
        "the central library",
        "the contact centre",
        "the Bristol office",
        "the Newcastle office",
        "the training centre",
        "the Canary Wharf office",
        "the town hall",
        "the depot",
        "the Guildhall",
        "the Manchester office",
        "the Birmingham hub",
        "Alexandra House",
        "the Wembley office",
    ],
    "floor": [
        "ground floor",
        "first floor",
        "2nd floor",
        "third floor",
        "4th floor",
        "fifth floor",
        "basement",
        "mezzanine",
    ],
    "printer": [
        "the printer by the kitchen",
        "PRN-3F-02",
        "the big Canon on floor 2",
        "the Ricoh in reception",
        "the printer in room 204",
        "the colour printer",
        "the MFD near the lifts",
        "PRT-LDS-014",
        "the Xerox on the third floor",
        "the printer in the post room",
        "the HP by my desk",
    ],
    "print_err": [
        "Call for service",
        "SC542",
        "Error 49",
        "Check toner",
        "Paper jam in tray 2",
        "Network error",
        "Service required",
        "Load paper",
        "E-200",
    ],
    "drive": [
        "S: drive",
        "shared drive",
        "H: drive",
        "P: drive",
        "Finance share",
        "team drive",
        "X: drive",
        "G: drive",
        "departmental share",
    ],
    "folder": [
        "Budgets 2026",
        "HR Confidential",
        "Team Admin",
        "Projects",
        "Complaints",
        "Rotas",
        "Board Papers",
        "Procurement",
        "Audit",
        "Casework",
        "Contracts",
        "Training",
    ],
    "browser": ["Edge", "Chrome", "Firefox"],
    "time": [
        "since this morning",
        "since yesterday",
        "for the last hour",
        "since the update last night",
        "since Monday",
        "on and off all week",
        "since I got back from leave",
        "since lunchtime",
        "for a couple of days",
        "since the weekend",
    ],
    "team": [
        "finance",
        "HR",
        "payroll",
        "the contact centre",
        "outpatients",
        "housing",
        "planning",
        "legal",
        "procurement",
        "the comms team",
        "estates",
        "pharmacy",
        "radiology",
        "children's services",
        "revenues and benefits",
        "adult social care",
        "the policy team",
        "customer services",
        "the data team",
        "facilities",
        "the project office",
        "admissions",
    ],
    "mobile": ["iPhone", "work mobile", "Samsung", "work phone", "Android phone"],
    "vpn": ["the VPN", "GlobalProtect", "AnyConnect", "the Always On VPN", "remote access", "FortiClient"],
    "smartcard": ["smartcard", "NHS smartcard", "ID badge smartcard", "access card"],
    "mailbox": [
        "the shared mailbox",
        "the team inbox",
        "the enquiries mailbox",
        "the generic mailbox",
        "the complaints inbox",
        "the bookings mailbox",
    ],
    "ext_org": [
        "a supplier",
        "the council",
        "our auditors",
        "a GP practice",
        "HMRC",
        "a partner organisation",
        "Gmail addresses",
        "the CQC",
        "a contractor",
        "another trust",
        "a school",
    ],
    "brand": [
        "Microsoft",
        "DocuSign",
        "HMRC",
        "Royal Mail",
        "our bank",
        "the chief executive",
        "DHL",
        "Amazon",
        "SharePoint",
        "the payroll team",
        "Evri",
        "the DVLA",
    ],
    "project": [
        "digital transformation",
        "estates move",
        "budget review",
        "winter planning",
        "website redesign",
        "recruitment",
        "audit",
        "new build",
    ],
    "addin": ["Power Pivot", "Analysis ToolPak", "Solver", "Adobe PDF", "Bloomberg", "Power Query"],
    "role": [
        "administrator",
        "analyst",
        "nurse",
        "caseworker",
        "receptionist",
        "project officer",
        "team leader",
        "apprentice",
        "social worker",
        "pharmacist",
    ],
    "desk": ["14", "3B", "F2-22", "by the window", "next to the printer", "27", "G-08", "in the quiet zone"],
    "room": ["204", "3.12", "G05", "the boardroom", "meeting room 4", "the training room", "1.07"],
    "bsod": [
        "CRITICAL_PROCESS_DIED",
        "your device ran into a problem and needs to restart",
        "INACCESSIBLE_BOOT_DEVICE",
        "a BitLocker recovery key",
        "no bootable device",
        "MEMORY_MANAGEMENT",
    ],
    "locked_msg": [
        "Your account has been locked",
        "The referenced account is currently locked out",
        "Account disabled, contact your administrator",
        "Sign-in blocked",
        "Your account has been temporarily locked to prevent unauthorised use",
    ],
    "hour": ["2pm", "3pm", "11am", "midday", "4pm", "10:30"],
    "place": ["home", "another site", "a client's office", "the regional office"],
    "day": ["Monday", "next Monday", "Wednesday", "the 3rd", "Thursday", "the 1st of next month"],
    "agent": ["Sam", "Priya", "Tom", "Ade", "Chris", "Jess", "Raj", "Kate"],
    "n_team": ["Four", "Five", "Six", "Seven", "Eight", "Ten", "A dozen", "12", "15"],
    "n_site": ["60", "80", "120", "200", "300", "400"],
    "n_team_l": ["four", "five", "six", "eight", "ten", "a dozen", "15"],
}

# Slots whose choice also sets the urgency label for that ticket.
URGENCY_SLOTS: dict[str, list[tuple[str, int]]] = {
    "when_u": [
        ("tomorrow", 1),
        ("tomorrow morning", 1),
        ("today", 1),
        ("on Monday", 2),
        ("next week", 2),
        ("this Thursday", 2),
        ("in two weeks", 3),
        ("next month", 3),
        ("on the 1st of next month", 3),
        ("in a few weeks", 3),
    ],
}

FIRST_NAMES = [
    "Sarah",
    "Mohammed",
    "Priya",
    "James",
    "Olivia",
    "Kwame",
    "Siobhan",
    "Tom",
    "Aisha",
    "Liam",
    "Wei",
    "Grace",
    "Daniel",
    "Fatima",
    "Rhys",
    "Emma",
    "Jakub",
    "Hannah",
    "Ben",
    "Zainab",
    "Oluwaseun",
    "Megan",
    "Arjun",
    "Lucy",
    "Marcus",
    "Eilidh",
    "Nadia",
    "Owen",
    "Ruth",
    "Sam",
]
SURNAMES = [
    "Jones",
    "Ali",
    "Patel",
    "Smith",
    "Brown",
    "Mensah",
    "Murphy",
    "Wilson",
    "Rahman",
    "O'Connor",
    "Chen",
    "Okafor",
    "Evans",
    "Hussain",
    "Davies",
    "Taylor",
    "Nowak",
    "Clarke",
    "Carter",
    "Ahmed",
    "Adeyemi",
    "Hughes",
    "Singh",
    "Green",
    "Johnson",
    "Campbell",
    "Kowalski",
    "Price",
    "Adebayo",
    "Lee",
]
JOB_TITLES = [
    "Housing Officer",
    "Senior Finance Analyst",
    "Ward Manager",
    "Staff Nurse",
    "Policy Adviser",
    "HR Business Partner",
    "Planning Officer",
    "Customer Service Adviser",
    "Project Manager",
    "Receptionist",
    "Pharmacy Technician",
    "Social Worker",
    "Data Analyst",
    "Paralegal",
    "Procurement Officer",
    "Team Leader",
    "Executive Assistant",
    "Caseworker",
    "Payroll Officer",
]

# --------------------------------------------------------------------------------------------
# Issues
# --------------------------------------------------------------------------------------------

Body = str | tuple[str, dict[str, int]]


@dataclass(frozen=True)
class Issue:
    id: str
    category: str
    type: str  # "incident" or "request"
    subjects: tuple[str, ...]
    bodies: tuple[Body, ...]
    details: tuple[str, ...] = ()
    base_impact: int = 3
    base_urgency: int | None = None  # None: incidents default to 2, requests to 3
    shared: bool = False  # impact phrases (team, site, organisation) make sense for this issue
    urgency_choices: dict[int, float] | None = None  # override the urgency distribution
    weight: float = 1.0


def _i(id: str, category: str, type: str, subjects: list[str], bodies: list[Body], **kw: object) -> Issue:
    return Issue(id, category, type, tuple(subjects), tuple(bodies), **kw)  # type: ignore[arg-type]


ISSUES: list[Issue] = [
    # ---------------------------------------------------------------- access
    _i(
        "password_reset",
        "access",
        "request",
        [
            "Password reset",
            "Forgotten my password",
            "Password expired",
            "Need my password resetting",
            "Can't remember password for {lob}",
            "Reset password please",
            "password",
        ],
        [
            "I've forgotten my password and can't log in to my {device}.",
            "My password expired over the weekend and the self-service reset isn't letting me change it.",
            "Can you reset my password for {lob}? I've tried a few times and now I'm not sure what it is.",
            "I came back from annual leave and my password has expired. Could you reset it please?",
            "I need my network password resetting, I changed it on Friday and can't remember the new one.",
            "The password reset page keeps saying my security answers are wrong, can someone reset it for me?",
            "Please can you reset my {lob} password, it says it has expired.",
        ],
        details=(
            "I tried the self-service portal but it says I'm not registered.",
            "I can get into my phone but not my laptop.",
            "It says the password is incorrect even though I'm typing it right.",
        ),
        urgency_choices={1: 0.25, 2: 0.35, 3: 0.4},
    ),
    _i(
        "account_locked",
        "access",
        "incident",
        [
            "Account locked",
            "Locked out",
            "Locked out of my account",
            "Account disabled?",
            "Can't log in - locked",
            "locked out again",
        ],
        [
            "My account is locked after too many attempts and I can't log in.",
            "I'm getting '{locked_msg}' when I try to sign in.",
            "Locked out of {lob} again, it says my account is disabled.",
            "I typed my password wrong a few times and now Windows says the account is locked.",
            "Can you unlock my account please, it locked itself while I was on a call.",
            "My login keeps getting locked out every morning.",
        ],
        details=(
            "It's been happening every morning this week.",
            "I think my phone might be trying an old password.",
            "I haven't changed anything recently.",
        ),
    ),
    _i(
        "mfa",
        "access",
        "incident",
        [
            "MFA not working",
            "Authenticator app problem",
            "Not getting the sign-in code",
            "New phone - need MFA reset",
            "2FA issue",
            "Can't approve sign in",
        ],
        [
            "I got a new phone and the Authenticator app no longer works, so I can't approve sign-ins.",
            "I'm not receiving the text message code when I sign in to Microsoft 365.",
            "The Authenticator app shows a number but nothing happens when I approve it.",
            "My MFA keeps asking me to set it up again every time I log in.",
            "My old phone broke and the verification codes went to that phone.",
            "I changed my phone number and now I can't get the verification codes.",
        ],
        details=(
            "I'm working from home today.",
            "I've tried removing and re-adding the account in the app.",
            "The app says the time is out of sync.",
        ),
    ),
    _i(
        "new_starter",
        "access",
        "request",
        [
            "New starter account",
            "New starter - IT setup",
            "Account for new team member",
            "New user request",
            "Starter {when_u}",
            "New staff member access",
        ],
        [
            "We have a new starter joining {team} {when_u}. Could you set up their account and email?",
            "Please create a network account and mailbox for our new {role} who starts {when_u}.",
            "New starter request for {team}, starting {when_u}. They'll need access to {lob} and the {drive}.",
            "Can you set up IT for a temporary member of staff starting {when_u}? They need a login and email.",
            "Our new {role}, {person}, starts {when_u} and will need a user account set up.",
        ],
        details=(
            "I'm their line manager.",
            "HR have already sent the form through.",
            "They'll be based at {site}.",
        ),
    ),
    _i(
        "leaver",
        "access",
        "request",
        ["Leaver", "Staff leaving - disable account", "Leaver request", "Account closure", "Leaver process"],
        [
            "{person} leaves {team} {when_u}. Please disable their account and set an out of office.",
            "Can you remove access for a leaver? Their last day was Friday.",
            "We had a member of staff leave yesterday, please disable their login.",
            "Please close the account of a member of staff who has left {team} and pass their files to me.",
            "Our agency worker finishes {when_u}, can their access be removed afterwards?",
        ],
        details=("Their laptop has been returned to the office.", "Please keep their files for 30 days."),
    ),
    _i(
        "permissions",
        "access",
        "request",
        [
            "Access to shared folder",
            "Permission request",
            "Need access to the {drive}",
            "Access rights for {lob}",
            "Folder permissions",
            "access request",
        ],
        [
            "Could I please have access to the {folder} folder on the {drive}? My manager has approved it.",
            "I need read and write access to {lob} for my new role in {team}.",
            "I've moved to {team} and need the same permissions as the rest of the team.",
            "Please give {person} edit rights to the {folder} folder.",
            "Can I be given the approver role in {lob}? I'm covering for my manager.",
        ],
        details=("My manager is copied in to approve.", "It's for the next three months only."),
    ),
    _i(
        "smartcard",
        "access",
        "incident",
        [
            "Smartcard not working",
            "Smartcard locked",
            "Card reader issue",
            "Smartcard certificate expired",
            "Can't log in with smartcard",
        ],
        [
            "My {smartcard} isn't being recognised by the card reader so I can't get into {lob}.",
            "My smartcard is locked and needs unlocking, I put the wrong passcode in three times.",
            "The certificate on my smartcard has expired and {lob} won't let me in.",
            "The card reader light flashes but nothing happens when I insert my {smartcard}.",
            "{lob} says my smartcard role isn't valid any more.",
        ],
        details=("I'm at {site} today.", "My registration authority manager is off this week."),
    ),
    _i(
        "access_denied",
        "access",
        "incident",
        [
            "Access denied",
            "Can't sign in to {lob}",
            "Login error",
            "{lob} says user not found",
            "Not authorised",
        ],
        [
            "When I try to log in to {lob} it says my user account doesn't exist.",
            "I'm getting 'access denied' when I open the {folder} folder, I had access last week.",
            "I can't sign in to {lob}, it says I don't have a role assigned.",
            "Since moving teams I can't get into {lob}, it just says not authorised.",
            "{lob} rejects my login with '{lob_err}'.",
        ],
        shared=True,
    ),
    # ---------------------------------------------------------------- hardware
    _i(
        "wont_start",
        "hardware",
        "incident",
        [
            "Laptop won't turn on",
            "Laptop dead",
            "PC not starting",
            "{device} won't boot",
            "Black screen on startup",
            "Blue screen",
        ],
        [
            "My {device} won't turn on at all, the power light doesn't come on.",
            "The laptop gets stuck on the {vendor} logo and then turns itself off.",
            "My PC shows a black screen with a blinking cursor when I switch it on.",
            "When I open my laptop nothing happens, I've had it on charge all night.",
            "I get a blue screen saying '{bsod}' and then it restarts.",
            "My {device} is asking for {bsod} when it starts up.",
        ],
        details=(
            "I've held the power button for 30 seconds.",
            "I've tried a different plug socket.",
            "It was fine yesterday.",
        ),
    ),
    _i(
        "screen",
        "hardware",
        "incident",
        [
            "Screen flickering",
            "Monitor not working",
            "Second screen not detected",
            "Cracked screen",
            "Display problem",
            "monitor issue",
        ],
        [
            "My laptop screen keeps flickering and has lines across it.",
            "My second monitor isn't being detected when I plug into the dock.",
            "I dropped my laptop and the screen is cracked.",
            "The monitor on my desk at {site} just shows 'no signal'.",
            "The display is really dim and I can't change the brightness.",
            "My external monitor goes black every few minutes.",
        ],
    ),
    _i(
        "dock",
        "hardware",
        "incident",
        [
            "Docking station not working",
            "Dock problem",
            "USB-C dock",
            "Hot desk dock not charging",
            "Dock issue at desk {desk}",
        ],
        [
            "The docking station on hot desk {desk} isn't charging my laptop or showing the screens.",
            "My keyboard and mouse stop working when I connect to the dock.",
            "The dock at {site} keeps disconnecting every few minutes.",
            "When I plug my laptop into the dock I get no screens and no keyboard.",
        ],
        shared=True,
    ),
    _i(
        "peripheral",
        "hardware",
        "incident",
        [
            "Keyboard not working",
            "Mouse broken",
            "Headset not working",
            "Webcam not detected",
            "Keys sticking",
            "Mouse not responding",
        ],
        [
            "Half the keys on my keyboard have stopped working.",
            "My wireless mouse isn't responding even with new batteries.",
            "My headset microphone has stopped working completely, it isn't detected when I plug it in.",
            "The webcam on my laptop isn't detected by any app.",
            "The USB headset crackles and cuts out.",
            "The trackpad on my laptop has stopped responding.",
        ],
    ),
    _i(
        "equipment_request",
        "hardware",
        "request",
        [
            "Equipment request",
            "Request for a second monitor",
            "New headset please",
            "Laptop replacement",
            "Ergonomic keyboard",
            "Request: new mouse",
            "Hardware request",
        ],
        [
            "Could I please order a second monitor for my desk? My manager has approved it.",
            "I'd like to request a new headset as mine is on its last legs.",
            "Can I get a replacement laptop? Mine is over five years old and very slow.",
            "Our new starter needs a laptop, dock and headset for when they start {when_u}.",
            "Following my DSE assessment I've been advised to get an ergonomic keyboard and mouse.",
            "Please could we have a webcam for the meeting room on the {floor}.",
        ],
    ),
    _i(
        "battery",
        "hardware",
        "incident",
        ["Battery not charging", "Laptop battery", "Charger not working", "Laptop not charging"],
        [
            "My laptop says plugged in, not charging.",
            "The battery only lasts about 20 minutes now.",
            "My laptop charger has stopped working, the light on the power brick doesn't come on.",
            "The laptop dies as soon as I unplug it.",
        ],
    ),
    _i(
        "slow_device",
        "hardware",
        "incident",
        ["Laptop very slow", "PC running slow", "Computer freezing", "Fan really loud", "Slow laptop"],
        [
            "My laptop has become really slow, it takes ages to open anything.",
            "My PC freezes several times a day and I have to hold the power button.",
            "The fan is constantly loud and the laptop gets very hot.",
            "It's taking 15 minutes to log in every morning.",
            "My {device} keeps freezing and the mouse pointer stops moving.",
        ],
    ),
    _i(
        "phone_fault",
        "hardware",
        "incident",
        [
            "Desk phone not working",
            "Work mobile broken",
            "Phone screen cracked",
            "Mobile won't charge",
            "No dial tone",
        ],
        [
            "The desk phone at {site} has no dial tone.",
            "My {mobile} won't charge any more.",
            "I've dropped my work phone and the screen is smashed but it still turns on.",
            "My {mobile} keeps restarting on its own.",
            "The speaker on my work phone has stopped working, I can't hear callers.",
        ],
    ),
    _i(
        "phone_request",
        "hardware",
        "request",
        ["Mobile phone request", "Need a work phone", "Request for work mobile", "Phone upgrade"],
        [
            "Could I please request a work mobile? My role now involves being on call.",
            "Can I get a work phone for my new role? My manager has approved it.",
            "My {mobile} is very old and won't update, can I have a replacement?",
            "We need two mobiles for the new out-of-hours team.",
        ],
    ),
    # ---------------------------------------------------------------- software
    _i(
        "install_request",
        "software",
        "request",
        [
            "Software request",
            "Install {software}",
            "Please install {software}",
            "Need {software}",
            "Software installation",
            "request for {software}",
        ],
        [
            "Could you please install {software} on my laptop? I need it for my new role.",
            "I need {software} for a project starting next month, my manager has approved the cost.",
            "Can I get {software} added to the Company Portal? I can't find it there.",
            "Requesting {software} for myself and a colleague in {team}.",
            "Please can {software} be installed, I'm doing a training course that uses it.",
            "I'd like {software} installed to help with reporting.",
        ],
        details=("It's on the approved software list.", "I've raised a purchase order already."),
    ),
    _i(
        "app_crash",
        "software",
        "incident",
        [
            "{app} keeps crashing",
            "{app} not responding",
            "{app} freezing",
            "Problem with {app}",
            "{app} won't open",
        ],
        [
            "{app} crashes every time I open a particular file.",
            "{app} freezes and says 'not responding' when I try to save.",
            "{time} {app} closes itself after a few minutes.",
            "{app} won't open at all, I just get a spinning wheel.",
            "{app} shows {error} when it starts.",
        ],
        details=("I've tried repairing it from Control Panel.", "Other files open fine."),
    ),
    _i(
        "licence_problem",
        "software",
        "incident",
        [
            "Licence expired",
            "{software} licence",
            "Product activation failed",
            "Unlicensed product",
            "Read only mode",
        ],
        [
            "{software} says my licence has expired and it's now in read-only mode.",
            "Word has a red banner saying 'Unlicensed Product' and won't let me edit.",
            "{software} says activation failed with {error}.",
            "My {software} licence seems to have been removed, it asks me to sign in to a trial.",
        ],
    ),
    _i(
        "licence_request",
        "software",
        "request",
        ["Licence request", "Need a {software} licence", "Licence for {software}", "Trial ended"],
        [
            "I need a licence for {software}, the trial has run out.",
            "Could we get two more {software} licences for {team}?",
            "Please can my {software} licence be upgraded to the pro version?",
        ],
    ),
    _i(
        "update_problem",
        "software",
        "incident",
        [
            "Windows update stuck",
            "Update failed",
            "Problems after update",
            "Restart required constantly",
            "Stuck on updates",
        ],
        [
            "My laptop has been stuck on 'Working on updates 30%' for an hour.",
            "Since last night's update {app} won't open.",
            "It keeps asking me to restart for updates but the update fails every time with {error}.",
            "After the update my {app} toolbar has disappeared.",
        ],
    ),
    _i(
        "lob_error",
        "software",
        "incident",
        [
            "{lob} error",
            "{lob} not loading",
            "Problem with {lob}",
            "{lob} down?",
            "Error in {lob}",
            "{lob} really slow",
        ],
        [
            "{lob} shows '{lob_err}' when I try to save a record.",
            "{lob} won't load past the login screen this morning.",
            "I can't run reports in {lob}, it just times out.",
            "{lob} is extremely slow, each screen takes a minute to load.",
            "Getting an error in {lob}: '{lob_err}'.",
            "{lob} keeps logging me out every few minutes.",
            "I can't print from {lob}, but printing from Word works fine.",
        ],
        shared=True,
    ),
    _i(
        "browser",
        "software",
        "incident",
        [
            "Website not opening",
            "Intranet page blank",
            "Certificate error",
            "{browser} problem",
            "{browser} crashing",
        ],
        [
            "The intranet won't load in {browser}, I just get a blank page.",
            "I'm getting a certificate error when I open {lob} in {browser}.",
            "{browser} keeps crashing when I open more than a few tabs.",
            "{browser} won't let me download PDFs from {lob}.",
        ],
    ),
    _i(
        "macros",
        "software",
        "incident",
        [
            "Macros blocked",
            "Excel add-in missing",
            "Excel macro error",
            "Template not working",
            "Macro security warning",
        ],
        [
            "Excel is blocking the macros in our team's budget spreadsheet.",
            "The {addin} add-in has disappeared from Excel.",
            "Our Word templates aren't showing in the New menu any more.",
            "Our Excel macro now fails with 'Runtime error 1004'.",
        ],
        shared=True,
    ),
    _i(
        "citrix",
        "software",
        "incident",
        ["Citrix not working", "Virtual desktop won't launch", "Remote app issue", "Citrix error"],
        [
            "Citrix Workspace says 'cannot start app' when I open {lob}.",
            "My virtual desktop is stuck on 'preparing your desktop'.",
            "The Citrix session keeps freezing and I lose my work.",
            "The {lob} icon has disappeared from my Citrix apps.",
        ],
        shared=True,
    ),
    # ---------------------------------------------------------------- m365
    _i(
        "outlook_sync",
        "m365",
        "incident",
        [
            "Outlook not syncing",
            "Emails not coming in",
            "Outlook stuck",
            "Outlook disconnected",
            "Not receiving emails",
            "Outbox stuck",
        ],
        [
            "Outlook says 'disconnected' at the bottom and no new emails are coming in.",
            "I haven't received any emails {time} but people say they've sent them.",
            "Outlook is stuck on 'updating this folder'.",
            "My sent emails are stuck in the outbox.",
            "Outlook keeps asking me to sign in over and over.",
            "Outlook search isn't finding any emails older than a week.",
            "Outlook crashes as soon as it opens.",
            "Outlook opens then closes straight away with no error.",
        ],
        shared=True,
    ),
    _i(
        "mailbox_full",
        "m365",
        "incident",
        ["Mailbox full", "Mailbox size limit", "Can't send - mailbox full", "Mailbox almost full"],
        [
            "I'm getting a message that my mailbox is full and I can't send emails.",
            "Can my mailbox size be increased? I keep getting warnings.",
            "My mailbox has hit its limit and emails are bouncing back to people.",
        ],
    ),
    _i(
        "shared_mailbox",
        "m365",
        "request",
        [
            "Shared mailbox access",
            "Access to {mailbox}",
            "Add me to shared mailbox",
            "New shared mailbox",
            "Mailbox permissions",
        ],
        [
            "Could you give me access to {mailbox} for {team}? My manager has approved it.",
            "Please add {person} to the {team} shared mailbox with send-as permission.",
            "Can we have a new shared mailbox for the {project} project?",
            "Please can I have full access to {mailbox} while my colleague is on leave.",
        ],
    ),
    _i(
        "shared_mailbox_problem",
        "m365",
        "incident",
        ["Can't send from shared mailbox", "Shared mailbox missing", "Shared mailbox not showing"],
        [
            "I can see {mailbox} but can't send from it, it says I don't have permission.",
            "{mailbox} has disappeared from my Outlook folder list.",
            "Emails I send from {mailbox} are going into my own sent items instead.",
        ],
        shared=True,
    ),
    _i(
        "teams_av",
        "m365",
        "incident",
        [
            "Teams audio problem",
            "No sound in Teams",
            "Teams camera not working",
            "Teams calls dropping",
            "Can't share screen in Teams",
            "Teams issue",
        ],
        [
            "People can't hear me on Teams calls but my headset works in other apps.",
            "My camera shows a black screen in Teams meetings.",
            "Teams calls keep dropping after a few minutes.",
            "I can't share my screen in Teams, the button is greyed out.",
            "Teams won't let me join meetings from external organisations.",
            "Teams keeps showing me as away when I'm at my desk.",
            "Teams crashes whenever I join a meeting.",
            "Teams freezes during calls and I have to restart it.",
        ],
        shared=True,
    ),
    _i(
        "onedrive_sharepoint",
        "m365",
        "incident",
        [
            "OneDrive not syncing",
            "SharePoint access",
            "Files not syncing",
            "OneDrive red cross",
            "SharePoint site not loading",
        ],
        [
            "OneDrive has red crosses on loads of files and says sync is paused.",
            "I can't open files from our SharePoint site, it says I need permission.",
            "Files I saved yesterday aren't showing in OneDrive on my other laptop.",
            "The SharePoint team site for {team} is showing an error.",
            "OneDrive says I'm out of storage space.",
        ],
        shared=True,
    ),
    _i(
        "calendar_problem",
        "m365",
        "incident",
        ["Calendar problem", "Meeting times wrong", "Room booking declined", "Calendar missing"],
        [
            "My manager's calendar has disappeared from my Outlook, I have delegate access.",
            "Meeting invites are showing at the wrong time since the clocks changed.",
            "I can't book the meeting room on the {floor}, the room calendar declines everything.",
            "Meetings I accept aren't appearing in my calendar.",
        ],
    ),
    _i(
        "calendar_request",
        "m365",
        "request",
        ["Delegate access", "Calendar sharing", "Calendar access request", "New room mailbox"],
        [
            "Can you give me delegate access to {person}'s calendar?",
            "Please could my calendar be shared with my assistant so they can manage meetings.",
            "Can we set up a bookable calendar for the new meeting room {room}?",
        ],
    ),
    _i(
        "dl_teams_request",
        "m365",
        "request",
        [
            "Distribution list",
            "Add me to distribution list",
            "New Teams team",
            "Create a Team",
            "Mailing list request",
            "Teams channel request",
        ],
        [
            "Please add me to the {team} distribution list.",
            "Can you create a new Team in Teams for our {project} project?",
            "Could we have a distribution list set up for all {team} staff?",
            "Please remove {person} from the {team} all-staff list, they left in May.",
            "Can I be made an owner of the {team} Team?",
        ],
    ),
    _i(
        "email_delivery",
        "m365",
        "incident",
        [
            "Emails bouncing",
            "Undeliverable",
            "Email not received by external",
            "Email going to junk",
            "Emails to {ext_org} failing",
        ],
        [
            "Emails I send to {ext_org} keep bouncing back with an undeliverable message.",
            "A supplier says our emails go straight into their spam.",
            "I'm not receiving emails from {ext_org}, they've checked their end.",
            "Important emails are going into my junk folder.",
        ],
        shared=True,
    ),
    # ---------------------------------------------------------------- network
    _i(
        "wifi",
        "network",
        "incident",
        [
            "Wi-Fi not working",
            "Can't connect to Wi-Fi",
            "Wi-Fi keeps dropping",
            "No Wi-Fi on the {floor}",
            "WiFi issues",
            "wifi down",
        ],
        [
            "My laptop won't connect to the staff Wi-Fi at {site}.",
            "The Wi-Fi keeps dropping out every few minutes on the {floor}.",
            "I'm connected to Wi-Fi but it says 'No internet, secured'.",
            "The Wi-Fi is really slow in the meeting rooms on the {floor}.",
            "I can't see the corporate Wi-Fi network at all, only the guest one.",
            "Since I changed my password my laptop won't connect to the Wi-Fi.",
        ],
        shared=True,
    ),
    _i(
        "vpn",
        "network",
        "incident",
        [
            "VPN not connecting",
            "Can't connect to VPN",
            "{vpn} error",
            "VPN keeps disconnecting",
            "Remote access problem",
            "vpn",
        ],
        [
            "{vpn} won't connect from home, it just says 'connecting' then fails.",
            "I'm working from home and the VPN drops every 10 minutes.",
            "{vpn} gives an error saying the gateway is unreachable.",
            "I can connect to {vpn} but can't reach the {drive} or the intranet.",
            "The VPN worked yesterday but today it says my certificate is invalid.",
        ],
        shared=True,
    ),
    _i(
        "internet",
        "network",
        "incident",
        [
            "No internet",
            "Internet very slow",
            "Network down",
            "Internet outage at {site}",
            "Connection problems",
            "Network issues",
        ],
        [
            "The internet is extremely slow at {site}, pages are taking ages.",
            ("We have no network connection at {site}, nothing is loading.", {"impact": 2}),
            "My wired connection says 'unidentified network'.",
            "Every website times out but Teams is fine.",
            "The network keeps dropping for a few seconds at a time.",
        ],
        shared=True,
    ),
    _i(
        "network_drive",
        "network",
        "incident",
        [
            "Can't access the {drive}",
            "Mapped drive missing",
            "Network drive not showing",
            "Shared drive disconnected",
            "Drive mapping",
        ],
        [
            "My {drive} has disappeared from File Explorer.",
            "The {drive} shows a red cross and says it's disconnected.",
            "Opening files from the {drive} is really slow today.",
            "I get 'network path not found' when I click on the {drive}.",
        ],
        shared=True,
    ),
    _i(
        "remote_access_request",
        "network",
        "request",
        ["VPN access request", "Remote access", "Need VPN", "Home working setup", "Remote access request"],
        [
            "Could I please be set up with VPN access? I've been approved to work from home two days a week.",
            "I need remote access to {lob} while I'm working from {place}.",
            "Please can {person} have remote access set up before they start home working.",
            "Can I get remote access to the {drive} from home?",
        ],
    ),
    _i(
        "guest_wifi",
        "network",
        "request",
        ["Guest Wi-Fi", "Wi-Fi for visitors", "Guest access", "Wi-Fi code", "Visitor internet access"],
        [
            "We have visitors from {ext_org} on {day}, could we get guest Wi-Fi codes for 10 people?",
            "How do visitors get on the guest Wi-Fi at {site}?",
            "Can a contractor have Wi-Fi access for the next two weeks?",
            "We're running a training event in {room}, can guests use the Wi-Fi?",
        ],
    ),
    _i(
        "network_port",
        "network",
        "incident",
        [
            "Network port not working",
            "Floor port dead",
            "Ethernet not working",
            "Wired connection not working",
        ],
        [
            "The network port under desk {desk} doesn't work, the light on the cable doesn't come on.",
            "The ethernet cable in meeting room {room} gives no connection.",
            "None of the wall ports in room {room} seem to work.",
        ],
    ),
    _i(
        "network_port_request",
        "network",
        "request",
        ["Patch request", "Network point request", "Floor port patching"],
        [
            "Could you patch the floor port in room {room} so we can use a desk phone there?",
            "We need two more network points in {room} for the new printers.",
            "Can the network port at desk {desk} be activated please?",
        ],
    ),
    _i(
        "site_unreachable",
        "network",
        "incident",
        ["Site can't be reached", "Intranet down", "Website not loading internally", "DNS issue?"],
        [
            "Internal websites say 'this site can't be reached' but external ones work.",
            "The {lob} web page won't load from the office but works on my phone's data.",
            "I can't get to the intranet, it says the server IP address could not be found.",
        ],
        shared=True,
    ),
    # ---------------------------------------------------------------- printing
    _i(
        "printer_offline",
        "printing",
        "incident",
        [
            "Printer offline",
            "Printer not working",
            "Can't print",
            "Printing problem",
            "{printer} offline",
            "printing",
        ],
        [
            "{printer} shows as offline and nothing prints.",
            "I send things to print but they never come out.",
            "My laptop says the printer is offline but others can print to it.",
            "The printer on the {floor} has an error on the screen: '{print_err}'.",
            "{printer} isn't printing anything, the screen says '{print_err}'.",
        ],
        shared=True,
    ),
    _i(
        "jam",
        "printing",
        "incident",
        ["Paper jam", "Printer jammed", "Paper jam - can't clear", "Tray keeps jamming"],
        [
            "{printer} has a paper jam that we can't clear.",
            "Tray 2 keeps jamming every few pages.",
            "The printer says there's a paper jam but there's no paper stuck anywhere.",
        ],
        shared=True,
    ),
    _i(
        "toner_request",
        "printing",
        "request",
        ["Toner low", "Need toner", "Order toner", "Toner request", "Printer supplies"],
        [
            "Could we order a new black toner cartridge for {printer}?",
            "The printer says toner low, please can we have a replacement.",
            "Can we get some more staples and a waste toner box for {printer}?",
        ],
    ),
    _i(
        "add_printer",
        "printing",
        "request",
        ["Add printer", "Install printer", "New printer setup", "Printer for new office", "Map printer"],
        [
            "Could you add {printer} to my laptop please?",
            "I've moved desks to the {floor} and need the printer there adding.",
            "We have a new printer in room {room}, can it be set up for the team?",
            "Please can I have access to print in colour?",
        ],
    ),
    _i(
        "scanning",
        "printing",
        "incident",
        [
            "Scan to email not working",
            "Scanner problem",
            "Can't scan",
            "Scanning error",
            "Scans not arriving",
        ],
        [
            "Scan to email on {printer} isn't sending anything to my inbox.",
            "The scanner says 'SMTP error' when I scan to my email.",
            "Scans come out as blank pages.",
            "My scans aren't appearing in the scan folder on the {drive}.",
        ],
        shared=True,
    ),
    _i(
        "print_quality",
        "printing",
        "incident",
        ["Print quality", "Streaks on prints", "Faded printing", "Smudged printouts"],
        [
            "Everything printed from {printer} has a black line down the page.",
            "Colour prints are coming out with a green tint.",
            "Prints are smudged and the toner rubs off on my hands.",
        ],
    ),
    _i(
        "secure_print",
        "printing",
        "incident",
        [
            "Follow-me printing",
            "Print release not working",
            "Card not working on printer",
            "Secure print issue",
        ],
        [
            "When I tap my ID card on the printer it says 'user not found'.",
            "My print jobs aren't showing on the release screen.",
            "The follow-me print queue is empty even though I've printed three documents.",
        ],
        shared=True,
    ),
    _i(
        "queue_stuck",
        "printing",
        "incident",
        ["Print queue stuck", "Print jobs stuck", "Documents stuck in queue"],
        [
            "There are 20 documents stuck in the print queue and I can't delete them.",
            "My print job says 'error - printing' and blocks everything else.",
            "The print queue for {printer} is frozen.",
        ],
        shared=True,
    ),
    # ---------------------------------------------------------------- security
    _i(
        "phishing_report",
        "security",
        "incident",
        [
            "Suspicious email",
            "Phishing?",
            "Is this email genuine?",
            "Spam email received",
            "Possible scam email",
            "Dodgy email",
        ],
        [
            "I've received an email claiming to be from {brand} asking me to verify my account. I haven't opened it.",
            "Got a strange email with an invoice attachment from someone I don't know. Is it safe?",
            "I think this email is a phishing attempt, it says my mailbox will be deleted unless I log in.",
            (
                "Several of us have received an email from a 'director' asking us to buy gift cards.",
                {"impact": 2},
            ),
            "I've had a text message pretending to be {brand} about my work account. I deleted it.",
        ],
        urgency_choices={2: 0.65, 3: 0.35},
    ),
    _i(
        "phishing_clicked",
        "security",
        "incident",
        [
            "Clicked a link",
            "I think I've been phished",
            "Entered my password on a fake site",
            "Mistake - clicked link",
            "URGENT: suspicious link",
        ],
        [
            "I clicked a link in an email that looked like it was from {brand} and entered my password before I "
            "realised.",
            "I opened an attachment in a suspicious email and now my laptop is acting strangely.",
            "I gave my login details to someone who called saying they were from IT.",
            "I clicked on a link in a text about a parcel and typed in my work email and password.",
        ],
        base_urgency=1,
    ),
    _i(
        "malware",
        "security",
        "incident",
        ["Virus warning", "Antivirus alert", "Pop-ups", "Is this a virus?", "Defender alert", "Virus?"],
        [
            "Defender has popped up saying it found a threat and quarantined a file.",
            "I'm getting lots of pop-ups saying my computer has a virus and to call a number.",
            (
                "All the files on the {drive} have been renamed with a strange extension and there's a ransom note.",
                {"impact": 1},
            ),
            "My browser homepage has changed and I keep getting redirected to odd sites, I think it's malware.",
        ],
        base_urgency=1,
    ),
    _i(
        "lost_device",
        "security",
        "incident",
        ["Lost laptop", "Stolen phone", "Lost my work phone", "Laptop stolen", "Lost smartcard"],
        [
            "I left my work laptop on the train this morning.",
            "My work phone was stolen last night, I've reported it to the police.",
            "I can't find my laptop, I think I left it in a meeting room at {site}.",
            "I've lost my smartcard somewhere between the car park and {site}.",
            "My bag with my work laptop was stolen from my car.",
        ],
        base_urgency=1,
        base_impact=2,
    ),
    _i(
        "suspicious_signin",
        "security",
        "incident",
        [
            "Suspicious sign-in",
            "MFA requests I didn't make",
            "Unusual sign-in activity",
            "Login alert",
            "Account compromised?",
        ],
        [
            "I keep getting MFA approval requests on my phone that I didn't request.",
            "I got an alert about a sign-in to my account from another country.",
            "Someone has sent emails from my account that I didn't write, I think it's been hacked.",
            "My password was changed and I didn't change it, I think my account is compromised.",
        ],
        base_urgency=1,
    ),
    _i(
        "data_breach",
        "security",
        "incident",
        [
            "Email sent to wrong person",
            "Data breach",
            "Sent personal data in error",
            "Wrong recipient",
            "Possible data breach",
        ],
        [
            "I've accidentally sent a spreadsheet with resident details to the wrong email address.",
            "I emailed a patient letter to the wrong patient by mistake.",
            "A document with staff salaries was shared with the whole department by mistake.",
            "I attached the wrong file to an external email and it contained client case notes.",
        ],
        base_urgency=1,
        base_impact=2,
    ),
    _i(
        "usb_request",
        "security",
        "request",
        [
            "USB access request",
            "Encrypted USB",
            "USB blocked",
            "Need to use a memory stick",
            "Secure file transfer",
        ],
        [
            "Could I have an encrypted USB stick? I need to take files to {ext_org}.",
            "My USB stick is blocked, how can I get access to copy training videos?",
            "I need to transfer a large file to a partner organisation, what's the approved secure way?",
        ],
    ),
    _i(
        "security_question",
        "security",
        "request",
        [
            "Security question",
            "Is this allowed?",
            "Personal device question",
            "Secure file sharing",
            "Security advice",
        ],
        [
            "Am I allowed to access my work email on my personal phone?",
            "Can I use a personal Dropbox account to share files with a supplier?",
            "Is it OK to install a browser extension for grammar checking?",
            "A supplier wants us to fill in a security questionnaire, who should I send it to?",
            "Can I forward work emails to my personal account to read at home?",
        ],
    ),
    # ---------------------------------------------------------------- questions (service requests)
    _i(
        "access_howto",
        "access",
        "request",
        [
            "How do I change my password?",
            "Question about MFA",
            "Self-service password reset",
            "Quick question",
            "Access process?",
        ],
        [
            "How do I register for the self-service password reset?",
            "Is there a way to change my password before it expires?",
            "How do I set up the Authenticator app on a new phone?",
            "Is it possible to have a second phone number for sign-in codes?",
            "What's the process for getting access to {lob}?",
        ],
    ),
    _i(
        "hardware_howto",
        "hardware",
        "request",
        [
            "Laptop loan",
            "Borrow a laptop",
            "Returning equipment",
            "Spare charger?",
            "Question about equipment",
        ],
        [
            "Can I borrow a laptop for a training day next week?",
            "Is it possible to get a laptop for working from home?",
            "How do I return old equipment? I have two monitors I don't need.",
            "Is there a spare charger I can borrow at {site}?",
            "Who do I ask about getting a replacement work phone?",
        ],
    ),
    _i(
        "software_howto",
        "software",
        "request",
        ["How do I...", "Default PDF program", "Company Portal question", "Software question"],
        [
            "How do I change the default PDF program back to Acrobat?",
            "Is it possible to get {software} on a Mac?",
            "Where can I find {software} in the Company Portal?",
            "Is there a way to recover a Word document I didn't save?",
            "How do I clear the cache in {browser}?",
        ],
    ),
    _i(
        "m365_howto",
        "m365",
        "request",
        [
            "Email signature",
            "How do I archive emails?",
            "Recall an email",
            "Calendar sharing question",
            "OneDrive question",
        ],
        [
            "How do I add the new email signature with the logo?",
            "How do I archive old emails? My mailbox is nearly full.",
            "Is there a way to recall an email I sent to the wrong team?",
            "How do I share my calendar with my team?",
            "Can an out of office be set up for a colleague who is off unexpectedly?",
            "How do I send a large file securely through OneDrive?",
        ],
    ),
    _i(
        "network_howto",
        "network",
        "request",
        ["Drive from home?", "Guest Wi-Fi question", "Website blocked", "VPN question", "Unblock website"],
        [
            "Is it possible to access the {drive} from home?",
            "How do visitors connect to the guest Wi-Fi at {site}?",
            "Can a website be unblocked? It says it's blocked by your organisation and I need it for work.",
            "How do I set up the VPN on a new laptop?",
            "Is there a way to get the {drive} on my laptop when I'm at {place}?",
        ],
    ),
    _i(
        "printing_howto",
        "printing",
        "request",
        ["Print from phone?", "Secure print PIN", "Scan to folder", "Who orders toner?", "Default printer"],
        [
            "Is there a way to print from my phone?",
            "How do I set a PIN for secure printing?",
            "How do I scan to a folder instead of to email?",
            "Who orders paper and toner for {printer}?",
            "How do I change my default printer to {printer}?",
        ],
    ),
    _i(
        "security_howto",
        "security",
        "request",
        ["Security question", "Public Wi-Fi", "Reporting phishing", "Cyber training"],
        [
            "Is it safe to use hotel Wi-Fi with my work laptop?",
            "How do I report a suspicious email properly?",
            "Where can I find the annual cyber security training?",
            "Is it OK to use a password manager for team logins?",
        ],
    ),
]

# --------------------------------------------------------------------------------------------
# Phrases that set impact and urgency, and generic text around the issue
# --------------------------------------------------------------------------------------------

IMPACT_PHRASES: dict[int, list[str]] = {
    3: [
        "It's just me as far as I know.",
        "Nobody else seems to have the problem.",
        "Only my account seems affected.",
        "My colleagues are fine, it's just my machine.",
        "It's only happening to me.",
    ],
    2: [
        "A few people in {team} have the same problem.",
        "The whole team is affected.",
        "Everyone on the {floor} is having this.",
        "My colleagues in {team} are having the same issue.",
        "It's affecting all of us in the {team} office.",
        "Three of us can't use it.",
        "Several people on my floor have the same issue.",
        "It's not just me, my team has it too.",
        "{n_team} of us in {team} are affected.",
        "About {n_team_l} people on the {floor} have said the same.",
        "Everyone in {team} is getting it.",
        "My colleagues are getting the same error.",
        "The rest of the team can't use it either.",
        "Same for everyone sat near me.",
        "All the PCs on the ward have the same problem.",
        "It's happening on every machine in our office.",
    ],
    1: [
        "It's affecting everyone at {site}.",
        "Nobody across the organisation can use it.",
        "All sites are affected.",
        "The whole building is affected.",
        "Every user we've spoken to has the same problem.",
        "It's affecting the entire contact centre and the public can't get through.",
        "All wards are affected.",
        "This is affecting the whole organisation.",
        "About {n_site} staff here are affected.",
        "Nobody in the building can use it.",
        "Customers can't use our online services.",
        "Residents can't get through to us at all.",
        "It's down for the whole service, around {n_site} staff.",
        "Every site we've checked has the same problem.",
        "The public-facing website is affected.",
        "All {n_site} agents on shift are affected.",
    ],
}

INCIDENT_URGENCY: dict[int, list[str]] = {
    1: [
        "I can't do any work at all.",
        "This is urgent, I'm completely stuck.",
        "I have a deadline at {hour} today.",
        "I'm presenting to the board in 20 minutes.",
        "We have patients waiting and can't book them in.",
        "Payroll has to run today.",
        "Clinic starts in ten minutes and I can't access records.",
        "Please treat as urgent, I can't work.",
        "Our service to the public has stopped.",
        "Customers are waiting at the counter.",
        "We can't take payments.",
        "I can't get past this screen at all.",
        "It's month end and we have to close today.",
        "This needs fixing before my {hour} meeting.",
        "I've got nothing else I can work on.",
        "This has to be submitted by {hour} today.",
        "People are waiting on me for this right now.",
    ],
    2: [
        "It's slowing me down but I can still work.",
        "I've got a workaround for now.",
        "Could it be looked at today if possible?",
        "It's annoying rather than urgent.",
        "I can use another PC in the meantime.",
        "It's intermittent but getting worse.",
        "I can carry on with other work for now.",
        "I'm getting by for now.",
        "I've found a way round it for now.",
        "I'm managing for now but it's a pain.",
        "It's causing a bit of a backlog.",
        "We're working around it for now.",
        "I'm using a colleague's PC today.",
        "Would be good to get it sorted this week.",
    ],
    3: [
        "No rush.",
        "Not urgent, whenever you get a chance.",
        "Any time this week is fine.",
        "Low priority.",
        "It can wait until next week.",
        "No urgency on this one.",
        "Not a big deal, just thought I'd report it.",
        "I can live with it.",
        "Small thing really.",
        "Not a big problem.",
        "When you get a moment.",
        "It's a minor annoyance.",
        "I'm off for the rest of the week so no hurry.",
    ],
}

REQUEST_URGENCY: dict[int, list[str]] = {
    1: [
        "I need this today please.",
        "This is needed urgently for an audit today.",
        "Could this be done this morning? It's holding up our work.",
        "They start tomorrow morning.",
        "It's needed for a meeting at {hour} today.",
        "Needed by the end of today please.",
    ],
    2: [
        "Ideally by the end of the week.",
        "Needed before Monday if possible.",
        "In the next couple of days please.",
        "From next week if possible.",
        "They start next Wednesday.",
        "Could someone chase this please?",
        "It's starting to hold things up.",
    ],
    3: [
        "No rush.",
        "Whenever is convenient.",
        "In the next couple of weeks is fine.",
        "Not urgent.",
        "Any time this month.",
        "Happy to wait.",
        "No hurry at all.",
        "Whenever suits.",
    ],
}

GREETINGS = [
    "Hi",
    "Hello",
    "Hi IT",
    "Hi team",
    "Morning",
    "Good morning",
    "Dear Service Desk",
    "Hi there",
    "Hiya",
    "Afternoon",
    "Hello IT team",
    "Hi {agent}",
    "Dear IT",
]
OPENERS = [
    "Hope you're well.",
    "Sorry to bother you.",
    "Not sure if this is the right place, but",
    "Me again!",
    "Quick one.",
    "Hope someone can help.",
    "Raising this on behalf of my manager.",
    "Following up on my call earlier.",
    "Can someone help please?",
]
TRIED = [
    "I've restarted twice.",
    "I've already tried turning it off and on again.",
    "I've rebooted but no change.",
    "I tried logging out and back in.",
    "A colleague had a look but couldn't fix it.",
    "I've checked the intranet guidance but it didn't help.",
    "I followed the steps in the help article.",
    "Nothing has changed on my side as far as I know.",
    "Screenshot attached.",
]
SIGNOFFS = [
    "Thanks",
    "Many thanks",
    "Kind regards",
    "Regards",
    "Cheers",
    "Thank you",
    "Best wishes",
    "Thanks in advance",
]
DISCLAIMERS = [
    "This email and any attachments are confidential and intended solely for the addressee.",
    "Please consider the environment before printing this email.",
    "Sent from my iPhone",
    "Sent from Outlook for Android",
    "The information in this email may be subject to the Freedom of Information Act 2000.",
]
GENERIC_SUBJECTS = [
    "Help please",
    "IT issue",
    "Problem",
    "Urgent",
    "Quick question",
    "(no subject)",
    "Ticket",
    "Can someone help",
    "Not working",
    "Issue",
    "Help!",
    "IT help needed",
    "Support request",
]
SECONDARY: dict[str, list[str]] = {
    "access": ["my password expires next week, can I change it early?"],
    "hardware": ["my mouse is a bit sticky", "could I get a new keyboard at some point?"],
    "software": ["could I get Visio installed at some point?", "Excel is a bit slow too"],
    "m365": ["Outlook has been a bit slow as well", "can I be added to the team distribution list?"],
    "network": ["the Wi-Fi is patchy by the window", "the VPN was slow yesterday"],
    "printing": ["the printer near me is out of paper", "the printer has been jamming a bit"],
}
TEXTSPEAK = [
    (r"\byou\b", "u"),
    (r"\bplease\b", "pls"),
    (r"\bthanks\b", "thx"),
    (r"\bbecause\b", "cos"),
    (r"\bcan't\b", "cant"),
    (r"\bdon't\b", "dont"),
    (r"\bI'm\b", "im"),
    (r"\bit's\b", "its"),
    (r"\bpeople\b", "ppl"),
    (r"\bas soon as possible\b", "asap"),
]


# --------------------------------------------------------------------------------------------
# Generation
# --------------------------------------------------------------------------------------------


@dataclass
class Ticket:
    subject: str
    body: str
    category: str
    type: str
    impact: int
    urgency: int
    issue: str
    meta: dict[str, str] = field(default_factory=dict)


def _nhs_number(rng: random.Random) -> str:
    while True:
        digits = "999" + "".join(str(rng.randint(0, 9)) for _ in range(6))
        total = sum(int(d) * (10 - i) for i, d in enumerate(digits))
        check = 11 - total % 11
        check = 0 if check == 11 else check
        if check != 10:
            n = digits + str(check)
            return f"{n[:3]} {n[3:6]} {n[6:]}"


def _phone(rng: random.Random) -> str:
    return rng.choice(
        [
            f"07700 900{rng.randint(0, 999):03d}",
            f"020 7946 0{rng.randint(0, 999):03d}",
            f"0113 496 0{rng.randint(0, 999):03d}",
            f"0161 496 0{rng.randint(0, 999):03d}",
            f"+44 7700 900{rng.randint(0, 999):03d}",
        ]
    )


def _person(rng: random.Random) -> str:
    return f"{rng.choice(FIRST_NAMES)} {rng.choice(SURNAMES)}"


class _Filler:
    """Fills {slots} in a template and remembers any urgency a slot implies."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.urgency: int | None = None
        self.chosen: dict[str, str] = {}

    def __call__(self, template: str) -> str:
        def repl(m: re.Match[str]) -> str:
            key = m.group(1)
            if key in self.chosen:
                return self.chosen[key]
            if key == "person":
                value = _person(self.rng)
            elif key in URGENCY_SLOTS:
                value, level = self.rng.choice(URGENCY_SLOTS[key])
                self.urgency = level
            else:
                value = self.rng.choice(SLOTS[key])
            self.chosen[key] = value
            return value

        return re.sub(r"\{(\w+)\}", repl, template)


def _sample_level(rng: random.Random, weights: dict[int, float]) -> int:
    levels = list(weights)
    return rng.choices(levels, weights=[weights[k] for k in levels])[0]


def _typos(rng: random.Random, text: str, n: int) -> str:
    words = text.split(" ")
    for _ in range(n):
        i = rng.randrange(len(words))
        w = words[i]
        if len(w) < 4 or not w.isalpha():
            continue
        j = rng.randrange(1, len(w) - 1)
        op = rng.random()
        if op < 0.4:
            w = w[:j] + w[j + 1] + w[j] + w[j + 2 :]
        elif op < 0.7:
            w = w[:j] + w[j + 1 :]
        else:
            w = w[:j] + w[j] + w[j:]
        words[i] = w
    return " ".join(words)


def make_ticket(rng: random.Random, issue: Issue | None = None) -> Ticket:
    if issue is None:
        category = rng.choice(sorted({i.category for i in ISSUES}))
        pool = [i for i in ISSUES if i.category == category]
        issue = rng.choices(pool, weights=[i.weight for i in pool])[0]
    fill = _Filler(rng)

    body_choice = rng.choice(issue.bodies)
    body_text, overrides = (body_choice, {}) if isinstance(body_choice, str) else body_choice
    core = fill(body_text)
    core = core[:1].upper() + core[1:]

    # Impact: start from the issue (or this body), then maybe widen it with a phrase.
    impact = overrides.get("impact", issue.base_impact)
    impact_phrase = ""
    if issue.shared and impact == 3:
        impact = _sample_level(rng, {3: 0.6, 2: 0.28, 1: 0.12})
    elif issue.shared and impact == 2:
        impact = _sample_level(rng, {2: 0.75, 1: 0.25})
    if impact != overrides.get("impact", issue.base_impact):
        impact_phrase = fill(rng.choice(IMPACT_PHRASES[impact]))
    elif impact == 3 and issue.type == "incident" and rng.random() < 0.15:
        impact_phrase = fill(rng.choice(IMPACT_PHRASES[3]))

    # Urgency: a slot (e.g. "starts tomorrow") or the issue may fix it; otherwise sample and add a phrase.
    # An incident that hits a whole site or organisation is treated as urgent (a possible major incident).
    default_urgency = 2 if issue.type == "incident" else 3
    urgency_phrase = ""
    if impact == 1 and issue.type == "incident":
        urgency = 1
        if rng.random() < 0.4:
            urgency_phrase = fill(rng.choice(INCIDENT_URGENCY[1]))
    elif fill.urgency is not None:
        urgency = fill.urgency
    elif issue.base_urgency is not None:
        urgency = issue.base_urgency
    else:
        weights = issue.urgency_choices or (
            {1: 0.3, 2: 0.45, 3: 0.25} if issue.type == "incident" else {1: 0.12, 2: 0.28, 3: 0.6}
        )
        urgency = _sample_level(rng, weights)
        phrases = INCIDENT_URGENCY if issue.type == "incident" else REQUEST_URGENCY
        if urgency != default_urgency or rng.random() < 0.5:
            urgency_phrase = fill(rng.choice(phrases[urgency]))
    # Ticket-level labels for issues fixed at a high urgency can only go up from there.
    urgency = min(urgency, overrides.get("urgency", urgency))

    parts: list[str] = []
    if rng.random() < 0.5:
        greeting = fill(rng.choice(GREETINGS))
        parts.append(greeting + rng.choice([",", "", " -", ","]) + "\n")
    if rng.random() < 0.2:
        parts.append(rng.choice(OPENERS) + " ")
    parts.append(core)
    if issue.details and rng.random() < 0.4:
        parts.append(" " + fill(rng.choice(issue.details)))
    if rng.random() < 0.3:
        parts.append(" " + rng.choice(TRIED))
    sentences = [p for p in (impact_phrase, urgency_phrase) if p]
    rng.shuffle(sentences)
    for s in sentences:
        parts.append(" " + s)
    if rng.random() < 0.06:
        others = [c for c in SECONDARY if c != issue.category]
        extra = rng.choice(SECONDARY[rng.choice(others)])
        parts.append(" Also, unrelated, " + extra + ("" if extra.endswith("?") else "."))
    if rng.random() < 0.15:
        parts.append(
            " "
            + rng.choice(
                [
                    f"You can call me on {_phone(rng)}.",
                    f"My email is {_person(rng).lower().replace(' ', '.').replace(chr(39), '')}@example.org if easier.",
                    f"My staff number is {rng.randint(1000000, 9999999)}.",
                    f"Desk phone {_phone(rng)}.",
                ]
            )
        )
    if issue.category in ("access", "software") and "lob" in fill.chosen and rng.random() < 0.05:
        parts.append(f" The patient's NHS number is {_nhs_number(rng)} if that helps.")

    body = "".join(parts).strip()

    if rng.random() < 0.5:
        sign = rng.choice(SIGNOFFS)
        name = _person(rng) if rng.random() < 0.7 else rng.choice(FIRST_NAMES)
        block = f"\n\n{sign},\n{name}"
        if rng.random() < 0.3:
            block += f"\n{rng.choice(JOB_TITLES)}\nTel: {_phone(rng)}"
        body += block
    if rng.random() < 0.08:
        body += "\n\n" + rng.choice(DISCLAIMERS)

    # Subject
    subject = rng.choice(GENERIC_SUBJECTS) if rng.random() < 0.15 else fill(rng.choice(issue.subjects))
    if rng.random() < 0.05:
        subject = rng.choice(["RE: ", "Fw: ", "FW: "]) + subject
    if rng.random() < 0.04:
        body = (
            f"-----Original Message-----\nFrom: {_person(rng)}\nSent: {rng.choice(SLOTS['day'])} 09:14\n"
            f"To: Service Desk\nSubject: {subject}\n\n{body}"
        )

    # Noise
    if rng.random() < 0.25:
        body = _typos(rng, body, rng.randint(1, 3))
    if rng.random() < 0.08:
        for pattern, repl in TEXTSPEAK:
            body = re.sub(pattern, repl, body, flags=re.IGNORECASE)
    if rng.random() < 0.12:
        body = body.lower()
        subject = subject.lower()
    if rng.random() < 0.08:
        body = re.sub(r"[.,!]", "", body)
    if rng.random() < 0.04:
        subject = subject.upper()

    return Ticket(
        subject=subject,
        body=body,
        category=issue.category,
        type=issue.type,
        impact=impact,
        urgency=urgency,
        issue=issue.id,
    )


def generate(count: int, seed: int = 7) -> list[Ticket]:
    # Synthetic data, not security, so a seeded generator is right.
    rng = random.Random(seed)  # nosec B311
    return [make_ticket(rng) for _ in range(count)]


FIELDS = ["subject", "body", "category", "type", "impact", "urgency", "issue"]


def write_csv(tickets: list[Ticket], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for t in tickets:
            writer.writerow({k: getattr(t, k) for k in FIELDS})


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--count", type=int, default=8400)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=Path, default=Path("data/synthetic/train.csv"))
    args = parser.parse_args(argv)
    tickets = generate(args.count, args.seed)
    write_csv(tickets, args.out)
    print(f"wrote {len(tickets)} tickets to {args.out}")


if __name__ == "__main__":
    main()
