resource "azurerm_key_vault" "main" {
  name                          = "kv-${local.base}"
  resource_group_name           = data.azurerm_resource_group.main.name
  location                      = local.location
  tenant_id                     = data.azurerm_client_config.current.tenant_id
  sku_name                      = "standard"
  rbac_authorization_enabled    = true
  soft_delete_retention_days    = 7
  purge_protection_enabled      = false # a demo that may be torn down and rebuilt; see docs/threat-model.md
  public_network_access_enabled = true
  tags                          = local.tags
}

# The deploy identity writes the secrets; the app identity can only read them.
resource "azurerm_role_assignment" "deployer_secrets" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
  principal_type       = var.deployer_principal_type
}

resource "azurerm_role_assignment" "app_secrets" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
  principal_type       = "ServicePrincipal"
}

# Ephemeral values with write-only secret arguments: Terraform generates the secrets and stores them in
# Key Vault, but never writes them to the state file. Change var.secret_version to rotate them.
ephemeral "random_password" "analyst_key" {
  length  = 40
  special = false
}

ephemeral "random_password" "session_secret" {
  length  = 64
  special = false
}

resource "azurerm_key_vault_secret" "analyst_key" {
  name             = "analyst-api-key"
  key_vault_id     = azurerm_key_vault.main.id
  value_wo         = ephemeral.random_password.analyst_key.result
  value_wo_version = var.secret_version
  content_type     = "text/plain"
  depends_on       = [time_sleep.rbac]
}

resource "azurerm_key_vault_secret" "session_secret" {
  name             = "session-secret"
  key_vault_id     = azurerm_key_vault.main.id
  value_wo         = ephemeral.random_password.session_secret.result
  value_wo_version = var.secret_version
  content_type     = "text/plain"
  depends_on       = [time_sleep.rbac]
}
