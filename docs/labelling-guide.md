# Labelling guide

The rules used to label the hand-written dev and test tickets. Reviewers in the app should use the
same rules, so that their corrections can be used for retraining.

## Category: who should own it

Label the category by the team that would fix the underlying problem, not by the words used.

| Category | Includes | Boundary cases |
|---|---|---|
| Accounts and access | Passwords, locked accounts, MFA, smartcards, new starters, leavers, permissions to systems or folders | "Can't log in to the VPN" is network if the VPN is down, access if the password expired |
| Hardware and devices | Laptops, desktops, monitors, docks, keyboards, mice, headsets, phones, equipment requests | A laptop that will not start is hardware even if it shows a BitLocker screen |
| Software and applications | Installing, licensing, updating or fixing applications, including line-of-business and clinical systems | A clinical system that rejects one person's login is access; one that is down for everyone is software |
| Email, Teams and Microsoft 365 | Outlook, mailboxes, shared mailboxes, calendars, Teams, SharePoint, OneDrive, distribution lists | Teams calls breaking up for one person on home Wi-Fi is still Microsoft 365 unless the network is clearly at fault |
| Network, Wi-Fi and VPN | Wi-Fi, VPN, internet, network drives, network ports | Mapped drives missing while off the VPN is network |
| Printing and scanning | Printers, queues, secure print, toner, paper, scan to email | A printer driver install on one laptop is printing, not software |
| Security | Phishing, malware, suspicious sign-ins, lost or stolen devices, data sent to the wrong person | A forgotten password is access; "someone else reset my password" is security |

## Type

- **Incident:** something that worked has stopped working or got worse.
- **Service request:** asking for something new or standard (access, equipment, software, information).

"My new starter has no account" is a request if it was never set up, an incident if it was set up
and is now broken.

## Impact: how many people or how much of the service

- **1 High:** many users, a whole site, every site, or a critical service (for example a clinical
  system, payroll on pay day, the contact centre phones).
- **2 Medium:** a team, a department, a ward or several named people.
- **3 Low:** one person.

## Urgency: how fast it hurts

- **1 High:** work has stopped with no workaround, a patient or safety risk, an active security
  incident, or a deadline in the next few hours.
- **2 Medium:** work is affected but there is a workaround, or a deadline today or tomorrow.
- **3 Low:** it can wait, including most requests.

Label what the ticket says, not what you guess. A calm ticket that says "nobody on the ward can see
medication charts" is urgency 1 however politely it is written.

## The data sets

- **Synthetic training data:** 8,400 tickets from a template generator with UK public sector
  vocabulary, typos, sign-offs and personal data, labelled by construction.
- **Dev set:** 92 hand-written tickets used for model selection and the review threshold.
- **Test set:** 189 hand-written tickets, written separately with these rules and used once for the
  final figures.
