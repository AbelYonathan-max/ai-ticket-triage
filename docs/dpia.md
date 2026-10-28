# Data protection impact assessment

This follows the structure of the ICO's sample DPIA template. It is written for the public demo of
this project and as a starting point for an organisation that wants to run the service on its own
tickets. That organisation would be the controller and must review, complete and sign it off with
its Data Protection Officer.

## 1. Why a DPIA is needed

The service processes free text written by staff about IT problems. That text often contains
personal data (names, phone numbers, staff IDs) and can contain special category data, such as a
mention of a hospital stay or a patient's details in an NHS setting. It uses automated
classification to decide priority, and can send text to a cloud language model. Innovative
technology combined with possible special category data meets the ICO's criteria for a DPIA.

## 2. The processing

**Nature.** A person submits a ticket through a web form or an API client. The service removes
personal data with pattern-based redaction, classifies the redacted text, sets an ITIL priority and
SLA targets, suggests help articles and, if switched on, asks Azure OpenAI for a summary and a reply
draft. The redacted ticket and the triage result are stored in Azure SQL. Analysts review triage
results. A daily job deletes tickets older than 30 days.

**Data.**

| Data | Source | Stored | Notes |
|---|---|---|---|
| Ticket subject and body | Requester | Redacted text only | The original text is held in memory for the length of the request and never written anywhere |
| Counts of removed items by type | Redaction | Yes | For example `{"PHONE": 1}`; no values |
| Triage result | Service | Yes | Category, priority, deadlines, reasons |
| Analyst reviews and notes | Analyst | Yes | Notes are redacted before saving |
| Analyst identifier | Sign-in | Yes, in the audit log | Microsoft Entra object ID, or "analyst" for the shared key |
| Requester identity | None | No | The demo does not ask who the requester is |
| IP address | Request | No | Held in memory for rate limiting only; Application Insights masks client IPs by default |
| Application logs | Service | 30 days in Log Analytics | Ticket IDs, category, priority and timings; never ticket text |

**Scope.** Demo: whatever visitors type, retained 30 days. In an organisation: all IT tickets, which
could be thousands a month, from all staff.

**Context.** Staff expect their IT tickets to be read by the service desk. They may not expect an
automated system or a cloud AI service to process them, so this must be explained in the privacy
notice (the app's `/privacy` page is a starting point). Tickets can come from people under stress,
such as clinicians during an outage.

**Purposes.** Faster and more consistent routing and prioritisation of IT tickets, so urgent
problems get help sooner; less manual sorting for the service desk.

## 3. Consultation

For a real deployment: the service desk manager and analysts (who own the triage decisions), the
Data Protection Officer, information security, and a sample of staff who raise tickets. Clinical
safety officers should be consulted in a health setting, because priority can affect patient care.

## 4. Necessity and proportionality

- **Lawful basis (UK GDPR Article 6).** For a public body, public task (6(1)(e)), as running IT
  services supports its functions; for a private organisation, legitimate interests (6(1)(f)), with a
  legitimate interests assessment.
- **Special category data (Article 9).** The service is not designed to process it and removes the
  identifiers it can detect, but free text may still contain it. The service flags tickets with
  health terms ("may contain special category data: handle with extra care"). The controller must
  identify an Article 9 condition and a DPA 2018 Schedule 1 condition where needed, or instruct
  staff not to include such details.
- **Data minimisation.** Redaction runs before anything else; only redacted text is stored or sent
  to the language model; logs hold no ticket text; no requester identity is collected in the demo.
- **Automated decision-making (Article 22).** Triage decides how fast a ticket is handled, not
  anything with legal or similarly significant effects on the person. Even so, every P1, every
  possible major incident, every clinical safety flag and every low-confidence decision goes to a
  person, and analysts can change any triage.
- **Accuracy.** The model card publishes the test results and known weaknesses. Analyst reviews are
  stored so disagreements can be measured and the model retrained.
- **Retention.** 30 days, enforced by a daily job (`TRIAGE_RETENTION_DAYS`).
- **Processors and transfers.** Microsoft Azure is the processor. Resources are in UK South, unless
  the subscription only allows other regions and the set-up script picks one of those: check before
  using real data. The database can be in another region than the app when Azure SQL does not accept
  new servers from the subscription in the app's region (as with free trials in UK South and UK
  West). The deploy then tries UK West first and then EEA regions, which UK GDPR treats as adequate,
  so stored data stays in the UK or the EEA. The Terraform output `sql_location` shows the
  database's region. Azure OpenAI, when switched on, is deployed as Global Standard by default,
  which may process prompts outside the UK while stored data stays in the resource's geography;
  choose the regional Standard deployment type for UK-only processing where the model is available.
  Check Microsoft's current data, privacy and abuse monitoring terms for Azure OpenAI before
  switching it on.
- **Individual rights.** Tickets are found by their ID. Because the stored text is redacted and
  the demo stores no requester identity, most tickets cannot be linked to a person; an organisation
  linking tickets to staff accounts must support access and erasure requests.

## 5. Risks

| # | Risk | Likelihood | Severity | Overall |
|---|---|---|---|---|
| 1 | Redaction misses personal data, which is then stored or sent to the language model | Possible | Significant | High |
| 2 | Special category data (health, patient details) entered in a ticket | Probable in health settings | Significant | High |
| 3 | A wrong low priority delays help in an urgent situation, including a clinical one | Possible | Severe | High |
| 4 | Language model output misleads an analyst or the requester | Possible | Minimal to significant | Medium |
| 5 | Unauthorised access to stored tickets | Remote | Significant | Medium |
| 6 | Data kept longer than needed | Remote | Minimal | Low |
| 7 | Prompt injection makes the language model produce harmful text | Possible | Minimal | Low |

## 6. Measures

| # | Measures | Effect on risk | Residual risk |
|---|---|---|---|
| 1 | Redaction of 10 data types tested against tricky cases; redaction before storage and before the language model; 30-day retention; banner telling demo users not to enter real data; analyst notes redacted | Reduced | Medium |
| 2 | Health-term flag on tickets; guidance in the privacy notice; only redacted text leaves the request; option to keep Azure OpenAI off | Reduced | Medium; the controller must decide its Article 9 position |
| 3 | Safety rules can only raise priority; P1, possible major incidents and clinical safety tickets always reviewed; low-confidence tickets reviewed; published under-prioritisation rate (5.3% on the test set) | Reduced | Medium; monitor with analyst reviews |
| 4 | The model cannot set priority; strict output schema; guardrails withhold risky drafts; drafts go to an analyst, never straight to the requester | Reduced | Low |
| 5 | Entra-only database access through managed identities; no passwords or keys; HTTPS only; analyst sign-in for the queue; tickets otherwise reachable only by their unguessable ID; audit log | Reduced | Low |
| 6 | Daily retention job, demo data refreshed daily, log retention 30 days | Eliminated in practice | Low |
| 7 | Injection detection on input; such tickets have their draft withheld and go to a person; the model has no tools or actions | Reduced | Low |

## 7. Sign-off

| Item | Name and date | Notes |
|---|---|---|
| Measures approved by | | For the adopting organisation |
| Residual risks approved by | | Risks 1 to 3 remain medium |
| DPO advice | | |
| Review date | | After the first month of analyst reviews, and on any change to the model or the language model |
