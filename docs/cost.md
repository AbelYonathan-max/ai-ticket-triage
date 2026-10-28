# Running cost

Estimates for UK South with light demo use, in pounds per month. Prices change, so check the
[Azure pricing calculator](https://azure.microsoft.com/pricing/calculator/) for current figures.

| Resource | Setting | Expected cost |
|---|---|---|
| Container Apps (app and two jobs) | Consumption plan, scales to zero, 0.5 vCPU and 1 GiB | £0: light use stays inside the monthly free grant of 180,000 vCPU-seconds, 360,000 GiB-seconds and 2 million requests per subscription |
| Azure SQL Database | Serverless, free offer | £0: the free offer includes a monthly compute allowance and 32 GB of storage, and pauses rather than bills when the allowance runs out |
| Container Registry | Basic | About £4 |
| Key Vault | Standard, a handful of secret reads | Pennies |
| Log Analytics and Application Insights | Pay as you go, daily cap 0.15 GB | £0 inside the first 5 GB a month |
| Metric alert | One rule | Pennies |
| Terraform state storage | Standard LRS, a few kilobytes | Pennies |
| **Total** | | **About £4 to £5 a month** |

## Optional

| Feature | Cost |
|---|---|
| Azure OpenAI (`ENABLE_OPENAI=true`) | Billed per token. The daily token budget (200,000 by default) caps the spend; triage carries on without the assistant once it is used up |
| Budget alerts (`ENABLE_BUDGET=true`) | Free |
| Keeping one replica always on (`min_replicas = 1`) | Roughly £8 to £25 a month for 0.5 vCPU and 1 GiB, depending on traffic, and no cold starts |

## Turning it off

Delete the two resource groups (see the [runbook](runbook.md#tearing-down)). Nothing else is left
running or billed.
