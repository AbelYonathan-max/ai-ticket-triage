# Azure SQL with Microsoft Entra authentication only: there is no SQL login or password anywhere.
# The region is part of the name, so a server refused in one region never blocks the name in the next.
resource "azurerm_mssql_server" "main" {
  name                          = "sql-${local.base}-${local.sql_location}"
  resource_group_name           = data.azurerm_resource_group.main.name
  location                      = local.sql_location
  version                       = "12.0"
  minimum_tls_version           = "1.2"
  public_network_access_enabled = true
  tags                          = local.tags

  azuread_administrator {
    login_username              = azurerm_user_assigned_identity.migrate.name
    object_id                   = azurerm_user_assigned_identity.migrate.principal_id
    tenant_id                   = data.azurerm_client_config.current.tenant_id
    azuread_authentication_only = true
  }
}

# Container Apps on the consumption plan has no fixed outbound address, so the server accepts
# connections from Azure services. Every connection still needs an Entra token for one of the two
# identities. A private endpoint is the upgrade path (docs/threat-model.md).
resource "azurerm_mssql_firewall_rule" "azure_services" {
  name             = "AllowAzureServices"
  server_id        = azurerm_mssql_server.main.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

# The Azure SQL free offer: a serverless database with a monthly allowance of compute and 32 GB of
# storage at no cost. When the allowance runs out the database pauses until the next month instead of
# billing. The azurerm provider has no setting for the free offer yet, hence azapi.
resource "azapi_resource" "database" {
  type      = "Microsoft.Sql/servers/databases@2025-01-01"
  name      = "triage"
  parent_id = azurerm_mssql_server.main.id
  location  = azurerm_mssql_server.main.location
  tags      = local.tags

  body = {
    sku = {
      name     = "GP_S_Gen5"
      tier     = "GeneralPurpose"
      family   = "Gen5"
      capacity = 2
    }
    properties = {
      useFreeLimit                     = true
      freeLimitExhaustionBehavior      = "AutoPause"
      autoPauseDelay                   = 60
      minCapacity                      = 0.5
      maxSizeBytes                     = 34359738368
      requestedBackupStorageRedundancy = "Local"
      zoneRedundant                    = false
      collation                        = "SQL_Latin1_General_CP1_CI_AS"
    }
  }
}
