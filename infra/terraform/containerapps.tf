resource "azurerm_container_app_environment" "main" {
  name                       = "cae-${local.base}"
  resource_group_name        = data.azurerm_resource_group.main.name
  location                   = local.location
  logs_destination           = "log-analytics"
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  tags                       = local.tags
}

locals {
  # Settings shared by the app and both jobs. Secrets are referenced by name, never inlined.
  common_env = {
    TRIAGE_ENV            = "prod"
    TRIAGE_SQL_SERVER     = azurerm_mssql_server.main.fully_qualified_domain_name
    TRIAGE_SQL_DATABASE   = azapi_resource.database.name
    TRIAGE_RETENTION_DAYS = tostring(var.retention_days)
    TRIAGE_REPO_URL       = var.repo_url
  }

  app_env = merge(local.common_env, {
    AZURE_CLIENT_ID                = azurerm_user_assigned_identity.app.client_id
    TRIAGE_AUTH_MODE               = var.enable_easy_auth ? "easyauth" : "apikey"
    TRIAGE_TRUST_EASY_AUTH_HEADERS = tostring(var.enable_easy_auth)
    TRIAGE_ANALYST_IDS             = join(",", var.analyst_object_ids)
    TRIAGE_LLM_PROVIDER            = var.enable_openai ? "azure_openai" : "stub"
    TRIAGE_OPENAI_ENDPOINT         = var.enable_openai ? azurerm_cognitive_account.openai[0].endpoint : ""
    TRIAGE_OPENAI_DEPLOYMENT       = var.enable_openai ? azurerm_cognitive_deployment.assist[0].name : ""
    TRIAGE_OPENAI_REASONING_EFFORT = var.enable_openai ? var.openai_reasoning_effort : ""
    TRIAGE_LLM_DAILY_TOKEN_BUDGET  = tostring(var.llm_daily_token_budget)
    TRIAGE_AUTO_MIGRATE            = "false"
    TRIAGE_SEED_DEMO               = "false"
    OTEL_SERVICE_NAME              = "triage-web"
    OTEL_RESOURCE_ATTRIBUTES       = "service.namespace=ai-ticket-triage"
  })

  app_secret_env = {
    TRIAGE_ANALYST_API_KEY                = "analyst-api-key"
    TRIAGE_SESSION_SECRET                 = "session-secret"
    APPLICATIONINSIGHTS_CONNECTION_STRING = "appinsights"
  }
}

resource "azurerm_container_app" "app" {
  name                         = "ca-${local.base}"
  resource_group_name          = data.azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"
  max_inactive_revisions       = 5
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  registry {
    server   = azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.app.id
  }

  secret {
    name                = "analyst-api-key"
    identity            = azurerm_user_assigned_identity.app.id
    key_vault_secret_id = azurerm_key_vault_secret.analyst_key.versionless_id
  }

  secret {
    name                = "session-secret"
    identity            = azurerm_user_assigned_identity.app.id
    key_vault_secret_id = azurerm_key_vault_secret.session_secret.versionless_id
  }

  secret {
    name  = "appinsights"
    value = azurerm_application_insights.main.connection_string
  }

  ingress {
    external_enabled           = true
    target_port                = 8000
    transport                  = "auto"
    allow_insecure_connections = false

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = var.min_replicas
    max_replicas = var.max_replicas

    http_scale_rule {
      name                = "http"
      concurrent_requests = "20"
    }

    container {
      name   = "app"
      image  = local.image
      cpu    = 0.5
      memory = "1Gi"

      dynamic "env" {
        for_each = local.app_env
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = local.app_secret_env
        content {
          name        = env.key
          secret_name = env.value
        }
      }

      # /healthz does not touch the database, so a paused database never restarts the app.
      startup_probe {
        transport               = "HTTP"
        port                    = 8000
        path                    = "/healthz"
        interval_seconds        = 3
        failure_count_threshold = 10
      }

      liveness_probe {
        transport        = "HTTP"
        port             = 8000
        path             = "/healthz"
        interval_seconds = 30
      }

      readiness_probe {
        transport        = "HTTP"
        port             = 8000
        path             = "/healthz"
        interval_seconds = 10
      }
    }
  }

  depends_on = [time_sleep.rbac]
}

resource "azurerm_container_app_job" "migrate" {
  name                         = "caj-${local.base}-migrate"
  resource_group_name          = data.azurerm_resource_group.main.name
  location                     = local.location
  container_app_environment_id = azurerm_container_app_environment.main.id
  replica_timeout_in_seconds   = 900
  replica_retry_limit          = 1
  tags                         = local.tags

  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.migrate.id]
  }

  registry {
    server   = azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.migrate.id
  }

  secret {
    name  = "appinsights"
    value = azurerm_application_insights.main.connection_string
  }

  template {
    container {
      name    = "migrate"
      image   = local.image
      cpu     = 0.5
      memory  = "1Gi"
      command = ["python", "-m", "triage.jobs.run", "migrate"]

      dynamic "env" {
        for_each = merge(local.common_env, {
          AZURE_CLIENT_ID               = azurerm_user_assigned_identity.migrate.client_id
          TRIAGE_APP_IDENTITY_NAME      = azurerm_user_assigned_identity.app.name
          TRIAGE_APP_IDENTITY_CLIENT_ID = azurerm_user_assigned_identity.app.client_id
          OTEL_SERVICE_NAME             = "triage-migrate"
        })
        content {
          name  = env.key
          value = env.value
        }
      }

      env {
        name        = "APPLICATIONINSIGHTS_CONNECTION_STRING"
        secret_name = "appinsights"
      }
    }
  }

  depends_on = [time_sleep.rbac]
}

# Deletes tickets past the retention period and refreshes the demo queue. It runs as the app identity,
# which can delete rows but cannot change the schema.
resource "azurerm_container_app_job" "retention" {
  name                         = "caj-${local.base}-retention"
  resource_group_name          = data.azurerm_resource_group.main.name
  location                     = local.location
  container_app_environment_id = azurerm_container_app_environment.main.id
  replica_timeout_in_seconds   = 900
  replica_retry_limit          = 1
  tags                         = local.tags

  schedule_trigger_config {
    cron_expression          = "15 3 * * *" # 03:15 UTC every day
    parallelism              = 1
    replica_completion_count = 1
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  registry {
    server   = azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.app.id
  }

  secret {
    name  = "appinsights"
    value = azurerm_application_insights.main.connection_string
  }

  template {
    container {
      name    = "retention"
      image   = local.image
      cpu     = 0.5
      memory  = "1Gi"
      command = ["python", "-m", "triage.jobs.run", "retention"]

      dynamic "env" {
        for_each = merge(local.common_env, {
          AZURE_CLIENT_ID   = azurerm_user_assigned_identity.app.client_id
          OTEL_SERVICE_NAME = "triage-retention"
        })
        content {
          name  = env.key
          value = env.value
        }
      }

      env {
        name        = "APPLICATIONINSIGHTS_CONNECTION_STRING"
        secret_name = "appinsights"
      }
    }
  }

  depends_on = [time_sleep.rbac]
}
