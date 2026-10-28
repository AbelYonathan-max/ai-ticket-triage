data "azurerm_client_config" "current" {}

data "azurerm_resource_group" "main" {
  name = var.resource_group_name
}

resource "random_string" "suffix" {
  length  = 5
  upper   = false
  special = false
}

locals {
  location = coalesce(var.location, data.azurerm_resource_group.main.location)
  # The database can sit in another region than the app (see var.sql_location).
  sql_location = coalesce(var.sql_location, local.location)
  base         = "${var.name_prefix}-${random_string.suffix.result}"
  compact      = replace(local.base, "-", "")
  image        = "${azurerm_container_registry.main.login_server}/${var.image_repository}:${var.image_tag}"
  tags         = merge({ app = "ai-ticket-triage", managed_by = "terraform" }, var.tags)
}

# Two identities, so the web app cannot change the database schema or grant itself more rights:
# "migrate" is the SQL server's Entra admin and is used only by the migration job; "app" can read and
# write rows and nothing else.
resource "azurerm_user_assigned_identity" "app" {
  name                = "id-${local.base}-app"
  resource_group_name = data.azurerm_resource_group.main.name
  location            = local.location
  tags                = local.tags
}

resource "azurerm_user_assigned_identity" "migrate" {
  name                = "id-${local.base}-migrate"
  resource_group_name = data.azurerm_resource_group.main.name
  location            = local.location
  tags                = local.tags
}

# Role assignments take a minute or two to reach every Azure service. Anything that relies on one
# waits for this.
resource "time_sleep" "rbac" {
  create_duration = "90s"

  depends_on = [
    azurerm_role_assignment.deployer_secrets,
    azurerm_role_assignment.app_secrets,
    azurerm_role_assignment.app_pull,
    azurerm_role_assignment.migrate_pull,
    azurerm_role_assignment.app_openai,
  ]
}
