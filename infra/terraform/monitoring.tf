resource "azurerm_log_analytics_workspace" "main" {
  name                = "log-${local.base}"
  resource_group_name = data.azurerm_resource_group.main.name
  location            = local.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
  daily_quota_gb      = var.log_daily_quota_gb
  tags                = local.tags
}

resource "azurerm_application_insights" "main" {
  name                = "appi-${local.base}"
  resource_group_name = data.azurerm_resource_group.main.name
  location            = local.location
  workspace_id        = azurerm_log_analytics_workspace.main.id
  application_type    = "web"
  tags                = local.tags
}

# Alerts go to whoever holds the Owner role on the subscription, so no email address is stored here.
resource "azurerm_monitor_action_group" "owners" {
  count               = var.enable_alerts || var.enable_budget ? 1 : 0
  name                = "ag-${local.base}-owners"
  resource_group_name = data.azurerm_resource_group.main.name
  short_name          = "triageown"
  tags                = local.tags

  arm_role_receiver {
    name                    = "subscription-owners"
    role_id                 = "8e3af657-a8ff-443c-a75c-2fe8c4bcb635" # Owner
    use_common_alert_schema = true
  }
}

resource "azurerm_monitor_metric_alert" "server_errors" {
  count               = var.enable_alerts ? 1 : 0
  name                = "alert-${local.base}-5xx"
  resource_group_name = data.azurerm_resource_group.main.name
  scopes              = [azurerm_container_app.app.id]
  description         = "The triage app returned more than 5 server errors in 15 minutes. See docs/runbook.md."
  severity            = 2
  frequency           = "PT5M"
  window_size         = "PT15M"
  tags                = local.tags

  criteria {
    metric_namespace = "Microsoft.App/containerApps"
    metric_name      = "Requests"
    aggregation      = "Total"
    operator         = "GreaterThan"
    threshold        = 5

    dimension {
      name     = "statusCodeCategory"
      operator = "Include"
      values   = ["5xx"]
    }
  }

  action {
    action_group_id = azurerm_monitor_action_group.owners[0].id
  }
}
