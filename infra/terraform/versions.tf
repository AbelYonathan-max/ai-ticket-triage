terraform {
  # 1.11 or later: the Key Vault secrets are write-only, so their values never reach the state file.
  required_version = ">= 1.11.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 5.11"
    }
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 3.10"
    }
    azapi = {
      source  = "azure/azapi"
      version = "~> 2.13"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.9"
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.14"
    }
  }

  # State lives in the storage account made by infra/bootstrap/bootstrap.sh. The deploy workflow
  # passes the account details with -backend-config, and signs in with OIDC: no storage keys.
  backend "azurerm" {}
}
