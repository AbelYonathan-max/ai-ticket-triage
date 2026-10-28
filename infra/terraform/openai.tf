# Optional: the language model assistant. Off by default because it costs money per call and free
# trial subscriptions have no Azure OpenAI quota. When off, a deterministic stand-in drafts replies.
resource "azurerm_cognitive_account" "openai" {
  count                         = var.enable_openai ? 1 : 0
  name                          = "oai-${local.base}"
  resource_group_name           = data.azurerm_resource_group.main.name
  location                      = local.location
  kind                          = "OpenAI"
  sku_name                      = "S0"
  custom_subdomain_name         = "oai-${local.base}"
  local_auth_enabled            = false # Entra ID only: there is no API key to leak
  public_network_access_enabled = true
  tags                          = local.tags
}

resource "azurerm_cognitive_deployment" "assist" {
  count                  = var.enable_openai ? 1 : 0
  name                   = "triage-assist"
  cognitive_account_id   = azurerm_cognitive_account.openai[0].id
  version_upgrade_option = "OnceCurrentVersionExpired"

  model {
    format  = "OpenAI"
    name    = var.openai_model
    version = var.openai_model_version
  }

  sku {
    name     = var.openai_deployment_sku
    capacity = var.openai_capacity
  }
}

# Can call deployments, cannot change them or read keys.
resource "azurerm_role_assignment" "app_openai" {
  count                = var.enable_openai ? 1 : 0
  scope                = azurerm_cognitive_account.openai[0].id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
  principal_type       = "ServicePrincipal"
}
