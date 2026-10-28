# Optional: analysts sign in with their Microsoft Entra account through Container Apps authentication
# ("Easy Auth"). The platform handles the sign-in and passes the user's object ID to the app, which
# checks it against var.analyst_object_ids. Creating the app registration needs the Microsoft Graph
# permission Application.ReadWrite.OwnedBy, which the bootstrap script grants when it can.
data "azuread_client_config" "current" {}

locals {
  app_fqdn = azurerm_container_app.app.ingress[0].fqdn
}

resource "azuread_application" "easy_auth" {
  count            = var.enable_easy_auth ? 1 : 0
  display_name     = "AI ticket triage (${local.base})"
  sign_in_audience = "AzureADMyOrg"
  owners           = [data.azuread_client_config.current.object_id]

  web {
    homepage_url  = "https://${local.app_fqdn}"
    redirect_uris = ["https://${local.app_fqdn}/.auth/login/aad/callback"]

    # Sign-in only, with an ID token: no client secret to store or rotate.
    implicit_grant {
      id_token_issuance_enabled = true
    }
  }

  required_resource_access {
    resource_app_id = "00000003-0000-0000-c000-000000000000" # Microsoft Graph

    resource_access {
      id   = "e1fe6dd8-ba31-4d61-89e7-88639da4683d" # User.Read, to sign in
      type = "Scope"
    }
  }
}

resource "azuread_service_principal" "easy_auth" {
  count     = var.enable_easy_auth ? 1 : 0
  client_id = azuread_application.easy_auth[0].client_id
  owners    = [data.azuread_client_config.current.object_id]
}

resource "azapi_resource" "easy_auth" {
  count     = var.enable_easy_auth ? 1 : 0
  type      = "Microsoft.App/containerApps/authConfigs@2025-07-01"
  name      = "current"
  parent_id = azurerm_container_app.app.id

  body = {
    properties = {
      platform = { enabled = true }
      # The public pages stay open; the app itself decides who is an analyst.
      globalValidation = { unauthenticatedClientAction = "AllowAnonymous" }
      httpSettings     = { requireHttps = true }
      login            = { tokenStore = { enabled = false } }
      identityProviders = {
        azureActiveDirectory = {
          enabled = true
          registration = {
            clientId     = azuread_application.easy_auth[0].client_id
            openIdIssuer = "https://login.microsoftonline.com/${data.azurerm_client_config.current.tenant_id}/v2.0"
          }
        }
      }
    }
  }

  depends_on = [azuread_service_principal.easy_auth]
}
