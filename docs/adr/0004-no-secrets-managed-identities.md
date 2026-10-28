# ADR 4: No secrets, managed identities everywhere

Status: accepted

## Context

Leaked credentials are one of the most common causes of cloud breaches. A public repository with a
deploy pipeline is a tempting target.

## Decision

- GitHub Actions signs in to Azure with OpenID Connect. Azure trusts tokens only for this repository's
  `production` environment. No client secret exists.
- The app and the jobs use user-assigned managed identities for every Azure service: the registry,
  Key Vault, Azure SQL (Entra-only authentication, no SQL logins) and Azure OpenAI (API keys switched
  off).
- Two app-side identities: the web app's can read and write rows only; a separate migration identity
  is the SQL admin and is attached only to the migration job.
- The deploy identity is Contributor on one resource group, and may grant only five named roles there,
  enforced by an Azure role assignment condition.
- The two values that must be secret (the analyst key and the session-signing secret) are generated
  by Terraform as ephemeral values and written to Key Vault with write-only arguments, so they are not
  in the Terraform state either.

## Consequences

- There is nothing to rotate on a schedule except the analyst key, which is a Terraform variable
  bump.
- Setting up needs an Owner once, to create the deploy identity and its role assignments
  ([bootstrap script](../../infra/bootstrap/bootstrap.sh)).
- Role assignments take a minute or two to apply across Azure, so Terraform waits before using them.
