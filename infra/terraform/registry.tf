resource "azurerm_container_registry" "main" {
  name                = "acr${local.compact}"
  resource_group_name = data.azurerm_resource_group.main.name
  location            = local.location
  sku                 = "Basic"
  admin_enabled       = false # images are pulled with managed identities, never a registry password
  tags                = local.tags
}

resource "azurerm_role_assignment" "deployer_push" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPush"
  principal_id         = data.azurerm_client_config.current.object_id
  principal_type       = var.deployer_principal_type
}

resource "azurerm_role_assignment" "app_pull" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "migrate_pull" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.migrate.principal_id
  principal_type       = "ServicePrincipal"
}
