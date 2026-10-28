# ADR 3: Container Apps and the Azure SQL free offer

Status: accepted

## Context

The service is a portfolio project that should cost close to nothing when idle, but use the same
kind of platform as a production service: containers, a relational database, managed identities,
monitoring and infrastructure as code.

## Decision

- **Azure Container Apps** on the consumption plan for the web app and two jobs (migration and daily
  retention). It scales to zero, so an idle app costs nothing, and the monthly free grant covers light
  use.
- **Azure SQL Database, serverless, on the free offer**: a monthly allowance of compute and 32 GB of
  storage at no cost, pausing instead of billing if the allowance runs out. The azurerm provider has
  no setting for the free offer, so the database is created with the azapi provider.
- **Azure Container Registry, Basic**, pulled with managed identities.
- **Key Vault** for the analyst key and session secret, referenced by the app, never copied into
  its configuration.

## Consequences

- The first request after a quiet period waits for the app to start and possibly the database to
  resume. Health probes do not touch the database, and the app retries the "database is resuming"
  errors.
- The SQL server accepts connections from Azure services rather than from a private network,
  because Container Apps on the consumption plan has no fixed outbound address. Access still needs
  an Entra token. A virtual network with a private endpoint is the upgrade path, at extra cost.
- The registry is the main running cost, about £4 a month.
