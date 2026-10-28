# ITIL mapping

How the service supports ITIL 4 practices, and where the rules live in the code.

## Practices

| ITIL 4 practice | What the service does | Where |
|---|---|---|
| Service desk | One entry point (web form and API) that acknowledges every ticket with a reference, a priority and target times | `api/` |
| Incident management | Classifies incidents, sets priority from impact and urgency, routes to the resolver group, tracks response and resolution targets | `domain/itil.py`, `service.py` |
| Service request management | Separates requests (new laptop, access, software) from incidents, so they follow the request route and lower urgency | `ml/`, `domain/taxonomy.py` |
| Major incident management | Flags a possible major incident when many users or a whole site are affected and the priority is P1, routes it to the Major Incident Manager and always asks a person to confirm | `domain/rules.py`, `service.py` |
| Information security management | Security category routed to Security Operations; rules raise phishing clicks, ransomware, lost devices and data breaches to high urgency | `domain/rules.py` |
| Knowledge management | Suggests approved help articles; the language model may only cite articles it was given | `kb/` |
| Service level management | SLA targets per priority in a policy file, on a business-hours clock with bank holidays; overdue tickets shown on the dashboard | `config/sla.yaml`, `domain/itil.py` |
| Monitoring and event management | Health endpoints, alerts on server errors, structured logs in Log Analytics | `api/app.py`, `infra/terraform/monitoring.tf` |
| Continual improvement | Analyst reviews record agreement with each triage; the dashboard shows the agreement rate; reviews are the input for retraining | `db/repository.py`, `web/templates/dashboard.html` |

## Priority matrix

Impact: 1 high (many users, a whole site or a critical service), 2 medium (a team, a department or
several people), 3 low (one person). Urgency: 1 high (work has stopped or it is time-critical),
2 medium (work is affected but there is a workaround), 3 low (it can wait).

| Impact \ Urgency | 1 High | 2 Medium | 3 Low |
|---|---|---|---|
| **1 High** | P1 Critical | P2 High | P3 Medium |
| **2 Medium** | P2 High | P3 Medium | P4 Low |
| **3 Low** | P3 Medium | P4 Low | P4 Low |

## Service level targets

From [`sla.yaml`](../src/triage/config/sla.yaml). Business hours are 08:00 to 18:00 London time,
Monday to Friday, excluding England and Wales bank holidays.

| Priority | Respond within | Resolve within | Clock |
|---|---|---|---|
| P1 Critical | 15 minutes | 4 hours | Around the clock |
| P2 High | 30 minutes | 8 business hours | Business hours |
| P3 Medium | 4 business hours | 3 business days | Business hours |
| P4 Low | 1 business day | 5 business days | Business hours |

These are typical public sector targets, not taken from any one organisation. Change the file to
match a real service level agreement; the clock and the tests read it.

## Safety rules

Deterministic rules run after the model and can only raise impact or urgency:

| Rule | Raises |
|---|---|
| Someone clicked a phishing link, entered credentials, or malware is active | Urgency to high |
| Ransomware: files encrypted or a ransom note | Impact to medium or higher, urgency to high |
| A device or smartcard that may hold or unlock data is lost or stolen | Impact to medium or higher, urgency to high |
| Personal data sent to the wrong person or exposed | Impact to medium or higher, urgency to high |
| The whole organisation, a whole site or every site is affected | Impact to high |
| Several people or a whole team are affected | Impact to medium or higher |
| A service is down for many users | Urgency to high, possible major incident review |
| A clinical or patient-facing service is not working | Urgency to high, clinical safety review |
| The person cannot work at all | Urgency to high |
| A deadline today | Urgency to medium or higher |

On the test set the rules cut under-prioritised tickets from 7.9% to 5.3%, at the cost of slightly
more over-prioritised ones (10.1% to 11.6%), which is the right trade for a service desk.
