# Runbook

Commands assume Azure Cloud Shell (Bash) or a terminal signed in with `az login`, and these
variables (names are in the Terraform outputs and on the Deploy run's summary):

```bash
RG=rg-triage-prod
APP=$(az containerapp list -g $RG --query "[0].name" -o tsv)
MIGRATE_JOB=$(az containerapp job list -g $RG --query "[?ends_with(name,'-migrate')].name | [0]" -o tsv)
RETENTION_JOB=$(az containerapp job list -g $RG --query "[?ends_with(name,'-retention')].name | [0]" -o tsv)
VAULT=$(az keyvault list -g $RG --query "[0].name" -o tsv)
```

## Deploying

Every push to `main` that passes CI is deployed by the **Deploy** workflow. To deploy by hand, run
the workflow from the Actions tab (`workflow_dispatch`). A deploy:

1. makes sure the container registry exists,
2. builds the image (the model is trained inside the build) and pushes it tagged with the commit SHA,
3. applies Terraform, which creates a new app revision and updates both jobs,
4. runs the migration job and waits for it,
5. checks `/readyz` and submits a test ticket.

Schema changes must be backwards compatible for one release (add columns, do not rename or drop),
because the new app revision can start a few seconds before the migration finishes.

## Rolling back

The app keeps its last five inactive revisions.

```bash
az containerapp revision list -n $APP -g $RG -o table
az containerapp ingress traffic set -n $APP -g $RG --revision-weight <previous-revision>=100
```

This is a quick fix only: the next deploy goes back to the latest revision. For a lasting rollback,
revert the commit on `main` and let the pipeline deploy it.

## Health

- `GET /healthz`: the process is up. Used by the platform probes.
- `GET /readyz`: the database is reachable and its schema is at the expected migration. Returns 503
  with `"status": "not ready"` otherwise.

The first request after a quiet period can take 10 to 60 seconds: the app scales from zero, and the
free-offer database resumes from pause. The app retries the "database is resuming" errors.

## Database region

Azure SQL does not accept new servers from every subscription type in every region (free trials in
most of the UK and western Europe, for example). A deploy then creates the database in the first
region that accepts it: the deploy's `sql_location` input, the `SQL_LOCATION` repository variable,
the app's region, UK West, then North Europe, West Europe, France Central, Germany West Central,
Sweden Central, Norway East, Poland Central, Italy North, Spain Central and Switzerland North. All of
these are in the UK, the EEA or Switzerland. The deploy log shows why each refused region said no.
The app is unaffected, apart from a few milliseconds per query. The Terraform output
`sql_location` shows the database's region, and an existing database never moves, because moving it
would mean a new server and a copy of the data.

If no region in the list accepts the server, ask Azure for access to one: in the portal, **Help +
support**, create a support request of type **Service and subscription limits (quotas)** for SQL
Database region access. These requests are free on every subscription type. Then set
`SQL_LOCATION` to that region and run **Deploy** again. Upgrading a free trial to pay-as-you-go
often lifts the limit too.

## Alerts

**More than 5 server errors in 15 minutes** emails the subscription owners. To investigate, in the
Log Analytics workspace:

```kusto
ContainerAppConsoleLogs_CL
| where TimeGenerated > ago(1h)
| where Log_s has "unhandled_error" or Log_s has "readyz_db_error" or Log_s has "sql_connect_retry"
| project TimeGenerated, RevisionName_s, Log_s
| order by TimeGenerated desc
```

and the **Failures** view in Application Insights. Typical causes:

| Symptom | Likely cause | Action |
|---|---|---|
| `readyz_db_error` with `OperationalError` | Free monthly database allowance used up, so the database is paused until the 1st | Wait, or switch the database to paid serverless in Terraform (`useFreeLimit = false`) |
| `readyz` says the schema is behind | The migration job did not run or failed | See below |
| `llm_error` warnings | Azure OpenAI throttling or an outage | Nothing: triage carries on without the assistant; the circuit breaker retries after a minute |
| 401 on `/login` for everyone | The analyst key was rotated | Fetch the new key (below) |

## Migration job failed

The deploy runs a failed migration once more after a minute, and prints the job's output from Log
Analytics each time it fails. To look yourself:

```bash
az containerapp job execution list -n $MIGRATE_JOB -g $RG -o table
```

Then in Log Analytics:

```kusto
ContainerAppConsoleLogs_CL
| where TimeGenerated > ago(2h)
| where * has "<migrate job name>"
| order by TimeGenerated desc
```

Common causes: a new role assignment not yet active (re-run the job after two minutes:
`az containerapp job start -n $MIGRATE_JOB -g $RG`), or an error in a migration script (fix it and
push). "Can't open lib ... msodbcsql ... file not found" means the image's ODBC driver is missing a
library it links against, not that the driver file is gone. The image build now fails on that, and
CI runs the migration job from the image against SQL Server, so it should not reach a deploy again.

## The analyst key

Read it (you need **Key Vault Secrets User** on the resource group, which the bootstrap script gives
you):

```bash
az keyvault secret show --vault-name $VAULT -n analyst-api-key --query value -o tsv
```

Rotate it, together with the session secret (which signs everyone out): increase `secret_version` in
Terraform, for example by adding `TF_VAR_secret_version: "2"` to the Deploy workflow, and deploy.
The app picks up the new values when its next revision starts.

## Retention

The retention job runs daily at 03:15 UTC. It deletes tickets older than `retention_days` (30) and
refreshes the demo queue. To run it now:

```bash
az containerapp job start -n $RETENTION_JOB -g $RG
```

## A personal data incident

If personal data was entered and must be removed at once (a reporter mentions a patient by name, or
redaction missed something):

1. Find the ticket ID from the link or the queue.
2. Delete it in the database, or wait for retention if the risk is low. The app has no delete
   button, on purpose, so that analysts cannot remove evidence. In the portal, make yourself the
   SQL server's Microsoft Entra admin for a moment (SQL server, Microsoft Entra ID), open the
   database's Query editor and run `DELETE FROM tickets WHERE id = '<ticket id>'` (its triage result
   and reviews go with it). The next deploy puts the migration identity back as admin.
3. Record what happened and when for the data protection officer. Check whether the text reached
   Azure OpenAI (the ticket shows the assistant status) and the 72-hour ICO reporting test.
4. Add the missed pattern to `privacy/redact.py` with a test.

## Switching features

As repository variables (Settings, Secrets and variables, Actions, Variables), then re-run Deploy:

| Variable | Effect |
|---|---|
| `ENABLE_OPENAI` | `true` creates Azure OpenAI and turns on the assistant |
| `ENABLE_EASY_AUTH` | `true` turns on Microsoft Entra sign-in (needs the Graph permission from the bootstrap script) |
| `ENABLE_BUDGET` | `true` creates a monthly budget with email alerts |
| `ANALYST_OBJECT_IDS` | JSON list of Entra object IDs allowed to review, for Entra sign-in |

## Tearing down

```bash
az group delete -n rg-triage-prod --yes
az group delete -n rg-triage-ops --yes   # Terraform state and the deploy identity
```

Key Vault keeps a soft-deleted copy for 7 days. To reuse the same name sooner, purge it:
`az keyvault purge -n <vault name>`.
