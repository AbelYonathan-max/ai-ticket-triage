# Plan-level tests with mocked providers: they need no Azure account and run in CI on every push.
# Run with: terraform init -backend=false && terraform test

mock_provider "azurerm" {
  mock_data "azurerm_client_config" {
    defaults = {
      tenant_id       = "11111111-1111-1111-1111-111111111111"
      object_id       = "22222222-2222-2222-2222-222222222222"
      subscription_id = "33333333-3333-3333-3333-333333333333"
    }
  }

  mock_data "azurerm_resource_group" {
    defaults = {
      id       = "/subscriptions/33333333-3333-3333-3333-333333333333/resourceGroups/rg-triage-prod"
      location = "uksouth"
    }
  }
}

mock_provider "azuread" {
  mock_data "azuread_client_config" {
    defaults = {
      object_id = "22222222-2222-2222-2222-222222222222"
    }
  }

  mock_resource "azuread_application" {
    defaults = {
      client_id = "55555555-5555-5555-5555-555555555555"
    }
  }
}

mock_provider "azapi" {}

mock_provider "time" {
  mock_resource "time_static" {
    defaults = {
      rfc3339 = "2026-11-14T10:00:00Z"
    }
  }
}

# The azurerm provider still validates IDs in mocked runs, so the resources other resources point at
# get realistic values.
override_resource {
  target = azurerm_user_assigned_identity.app
  values = {
    id           = "/subscriptions/33333333-3333-3333-3333-333333333333/resourceGroups/rg-triage-prod/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-app"
    principal_id = "66666666-6666-6666-6666-666666666666"
    client_id    = "77777777-7777-7777-7777-777777777777"
  }
}

override_resource {
  target = azurerm_user_assigned_identity.migrate
  values = {
    id           = "/subscriptions/33333333-3333-3333-3333-333333333333/resourceGroups/rg-triage-prod/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-migrate"
    principal_id = "88888888-8888-8888-8888-888888888888"
    client_id    = "99999999-9999-9999-9999-999999999999"
  }
}

override_resource {
  target = azurerm_container_registry.main
  values = {
    id           = "/subscriptions/33333333-3333-3333-3333-333333333333/resourceGroups/rg-triage-prod/providers/Microsoft.ContainerRegistry/registries/acrtriagetest"
    login_server = "acrtriagetest.azurecr.io"
  }
}

override_resource {
  target = azurerm_key_vault.main
  values = {
    id = "/subscriptions/33333333-3333-3333-3333-333333333333/resourceGroups/rg-triage-prod/providers/Microsoft.KeyVault/vaults/kv-triage-test"
  }
}

override_resource {
  target = azurerm_key_vault_secret.analyst_key
  values = {
    versionless_id = "https://kv-triage-test.vault.azure.net/secrets/analyst-api-key"
  }
}

override_resource {
  target = azurerm_key_vault_secret.session_secret
  values = {
    versionless_id = "https://kv-triage-test.vault.azure.net/secrets/session-secret"
  }
}

override_resource {
  target = azurerm_log_analytics_workspace.main
  values = {
    id = "/subscriptions/33333333-3333-3333-3333-333333333333/resourceGroups/rg-triage-prod/providers/Microsoft.OperationalInsights/workspaces/log-triage-test"
  }
}

override_resource {
  target = azurerm_container_app_environment.main
  values = {
    id = "/subscriptions/33333333-3333-3333-3333-333333333333/resourceGroups/rg-triage-prod/providers/Microsoft.App/managedEnvironments/cae-triage-test"
  }
}

override_resource {
  target = azurerm_container_app.app
  values = {
    id = "/subscriptions/33333333-3333-3333-3333-333333333333/resourceGroups/rg-triage-prod/providers/Microsoft.App/containerApps/ca-triage-test"
  }
}

override_resource {
  target = azurerm_mssql_server.main
  values = {
    id                          = "/subscriptions/33333333-3333-3333-3333-333333333333/resourceGroups/rg-triage-prod/providers/Microsoft.Sql/servers/sql-triage-test"
    fully_qualified_domain_name = "sql-triage-test.database.windows.net"
  }
}

override_resource {
  target = azurerm_cognitive_account.openai
  values = {
    id       = "/subscriptions/33333333-3333-3333-3333-333333333333/resourceGroups/rg-triage-prod/providers/Microsoft.CognitiveServices/accounts/oai-triage-test"
    endpoint = "https://oai-triage-test.openai.azure.com/"
  }
}

override_resource {
  target = azurerm_monitor_action_group.owners
  values = {
    id = "/subscriptions/33333333-3333-3333-3333-333333333333/resourceGroups/rg-triage-prod/providers/Microsoft.Insights/actionGroups/ag-triage-test"
  }
}

variables {
  resource_group_name = "rg-triage-prod"
  image_tag           = "abc123"
}

run "defaults_are_cheap_and_locked_down" {
  command = apply

  assert {
    condition     = azurerm_mssql_server.main.azuread_administrator[0].azuread_authentication_only
    error_message = "SQL must accept Microsoft Entra authentication only."
  }

  assert {
    condition     = azurerm_mssql_server.main.location == "uksouth" && azapi_resource.database.location == "uksouth"
    error_message = "By default the database should be in the app's region."
  }

  assert {
    condition     = azurerm_mssql_server.main.azuread_administrator[0].object_id == azurerm_user_assigned_identity.migrate.principal_id
    error_message = "Only the migrate identity should be the SQL admin."
  }

  assert {
    condition     = azapi_resource.database.body.properties.useFreeLimit && azapi_resource.database.body.properties.freeLimitExhaustionBehavior == "AutoPause"
    error_message = "The database should use the free offer and pause rather than bill."
  }

  assert {
    condition     = !azurerm_container_registry.main.admin_enabled
    error_message = "The registry admin user must stay off; pulls use managed identities."
  }

  assert {
    condition     = azurerm_key_vault.main.rbac_authorization_enabled
    error_message = "Key Vault should use Azure RBAC."
  }

  assert {
    condition     = !azurerm_container_app.app.ingress[0].allow_insecure_connections
    error_message = "The app must be HTTPS only."
  }

  assert {
    condition     = azurerm_container_app.app.template[0].min_replicas == 0
    error_message = "The app should scale to zero by default."
  }

  assert {
    condition     = azurerm_container_app.app.template[0].container[0].image == "acrtriagetest.azurecr.io/ai-ticket-triage:abc123"
    error_message = "The app should run the tagged image from the private registry."
  }

  assert {
    condition = alltrue([
      for e in azurerm_container_app.app.template[0].container[0].env :
      e.secret_name != null && e.secret_name != "" if contains(["TRIAGE_ANALYST_API_KEY", "TRIAGE_SESSION_SECRET", "APPLICATIONINSIGHTS_CONNECTION_STRING"], e.name)
    ])
    error_message = "Secrets must be passed as secret references, never as plain values."
  }

  assert {
    condition     = contains([for e in azurerm_container_app.app.template[0].container[0].env : "${e.name}=${e.value}" if e.value != null], "TRIAGE_AUTH_MODE=apikey")
    error_message = "Without Entra sign-in the app should use the Key Vault analyst key."
  }

  assert {
    condition     = contains([for e in azurerm_container_app.app.template[0].container[0].env : "${e.name}=${e.value}" if e.value != null], "TRIAGE_LLM_PROVIDER=stub")
    error_message = "Without Azure OpenAI the app should use the stand-in assistant."
  }

  assert {
    condition     = azurerm_container_app_job.migrate.identity[0].identity_ids == toset([azurerm_user_assigned_identity.migrate.id])
    error_message = "Only the migrate job should run as the migrate identity."
  }

  assert {
    condition     = azurerm_container_app_job.retention.identity[0].identity_ids == toset([azurerm_user_assigned_identity.app.id])
    error_message = "The retention job should run as the least-privileged app identity."
  }

  assert {
    condition     = length(azurerm_cognitive_account.openai) == 0 && length(azuread_application.easy_auth) == 0 && length(azurerm_consumption_budget_resource_group.main) == 0
    error_message = "Azure OpenAI, Entra sign-in and the budget should be off by default."
  }

  assert {
    condition     = length(azurerm_monitor_metric_alert.server_errors) == 1
    error_message = "The server error alert should be on by default."
  }
}

run "every_option_on" {
  command = apply

  variables {
    enable_openai      = true
    enable_easy_auth   = true
    enable_budget      = true
    analyst_object_ids = ["44444444-4444-4444-4444-444444444444"]
    sql_location       = "ukwest"
  }

  assert {
    condition     = azurerm_mssql_server.main.location == "ukwest" && azapi_resource.database.location == "ukwest" && azurerm_container_app_environment.main.location == "uksouth"
    error_message = "The database should follow sql_location while the app stays in its own region."
  }

  assert {
    condition     = !azurerm_cognitive_account.openai[0].local_auth_enabled
    error_message = "Azure OpenAI must not allow API keys."
  }

  assert {
    condition     = azurerm_cognitive_deployment.assist[0].model[0].name == "gpt-5.4-mini"
    error_message = "Unexpected default model."
  }

  assert {
    condition     = azurerm_role_assignment.app_openai[0].role_definition_name == "Cognitive Services OpenAI User"
    error_message = "The app should only be able to call the model, not manage it."
  }

  assert {
    condition = alltrue([for pair in ["TRIAGE_LLM_PROVIDER=azure_openai", "TRIAGE_AUTH_MODE=easyauth", "TRIAGE_TRUST_EASY_AUTH_HEADERS=true", "TRIAGE_ANALYST_IDS=44444444-4444-4444-4444-444444444444", "TRIAGE_OPENAI_ENDPOINT=https://oai-triage-test.openai.azure.com/"] :
    contains([for e in azurerm_container_app.app.template[0].container[0].env : "${e.name}=${e.value}" if e.value != null], pair)])
    error_message = "The app settings do not match the options."
  }

  assert {
    condition     = azapi_resource.easy_auth[0].body.properties.globalValidation.unauthenticatedClientAction == "AllowAnonymous"
    error_message = "Public pages should stay open; the app decides who is an analyst."
  }

  assert {
    condition     = length(azurerm_consumption_budget_resource_group.main[0].notification) == 3
    error_message = "The budget should warn at 50% and 90% of actual spend and at 100% forecast."
  }

  assert {
    condition     = azurerm_consumption_budget_resource_group.main[0].time_period[0].start_date == "2026-11-01T00:00:00Z"
    error_message = "The budget should start on the first day of the month."
  }
}

run "rejects_a_bad_name_prefix" {
  command = plan

  variables {
    name_prefix = "Triage_App"
  }

  expect_failures = [var.name_prefix]
}
