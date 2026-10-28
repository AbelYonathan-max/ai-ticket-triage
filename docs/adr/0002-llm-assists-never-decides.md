# ADR 2: The language model assists, it never decides

Status: accepted

## Context

A language model writes good summaries and reply drafts, but it can be manipulated by text inside
the ticket (prompt injection), can state things that are not true, and costs money per call.
Priority decides how fast someone gets help, so it must be predictable and auditable.

## Decision

- Priority, impact and urgency come only from the classifier, the safety rules and the ITIL matrix.
  The model's answer has no field that can change them.
- The model gets redacted text only, plus the matched help articles, and must answer in a strict JSON
  schema (Azure OpenAI structured outputs).
- Its answer is checked before use: citations of articles it was not given are dropped, and the
  reply draft is withheld if it claims something was already done, asks for a password or code, or
  contains redaction tags. A ticket that looks like a prompt injection attempt has its draft withheld
  and goes to a person.
- A circuit breaker and a daily token budget mean a failing or expensive model degrades to triage
  without the assistant, never to no triage.
- The reply is a draft for an analyst to check and send. Nothing is sent to the requester
  automatically.
- Azure OpenAI is off by default. A deterministic stand-in shows the feature without cost.

## Consequences

- The service works the same with the model switched off, and tests do not depend on it.
- The model cannot take actions, so the impact of a successful prompt injection is limited to a bad
  draft that a person reads first.
- Model upgrades are a configuration change (Terraform variables), checked against the retirement
  schedule.
