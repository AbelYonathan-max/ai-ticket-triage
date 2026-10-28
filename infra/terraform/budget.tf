# A monthly budget for the resource group, with emails to the subscription owners at 50% and 90% of
# actual spend and when the forecast passes 100%. Off by default because some subscription types
# (Azure for Students, for example) do not support budgets; the bootstrap script checks.
resource "time_static" "budget_start" {
  count = var.enable_budget ? 1 : 0
}

resource "azurerm_consumption_budget_resource_group" "main" {
  count             = var.enable_budget ? 1 : 0
  name              = "budget-${local.base}"
  resource_group_id = data.azurerm_resource_group.main.id
  amount            = var.monthly_budget
  time_grain        = "Monthly"

  time_period {
    start_date = "${formatdate("YYYY-MM", time_static.budget_start[0].rfc3339)}-01T00:00:00Z"
  }

  dynamic "notification" {
    for_each = { "50" = "Actual", "90" = "Actual", "100" = "Forecasted" }
    content {
      enabled        = true
      threshold      = tonumber(notification.key)
      threshold_type = notification.value
      operator       = "GreaterThan"
      contact_groups = [azurerm_monitor_action_group.owners[0].id]
      contact_roles  = ["Owner"]
    }
  }

  lifecycle {
    ignore_changes = [time_period]
  }
}
