output "app_url" {
  description = "Public address of the app."
  value       = "https://${azurerm_container_app.app.ingress[0].fqdn}"
}

output "resource_group_name" {
  value = data.azurerm_resource_group.main.name
}

output "registry_name" {
  value = azurerm_container_registry.main.name
}

output "registry_login_server" {
  value = azurerm_container_registry.main.login_server
}

output "container_app_name" {
  value = azurerm_container_app.app.name
}

output "migrate_job_name" {
  value = azurerm_container_app_job.migrate.name
}

output "retention_job_name" {
  value = azurerm_container_app_job.retention.name
}

output "key_vault_name" {
  description = "Holds the analyst key: az keyvault secret show --vault-name <this> -n analyst-api-key --query value -o tsv"
  value       = azurerm_key_vault.main.name
}

output "sql_server_fqdn" {
  value = azurerm_mssql_server.main.fully_qualified_domain_name
}

output "sql_location" {
  description = "The database's region. The deploy workflow keeps an existing database there."
  value       = azurerm_mssql_server.main.location
}

output "sign_in" {
  value = var.enable_easy_auth ? "Microsoft Entra ID" : "Analyst key from Key Vault"
}

output "assistant" {
  value = var.enable_openai ? "Azure OpenAI ${var.openai_model} ${var.openai_model_version}" : "Deterministic stand-in (Azure OpenAI off)"
}
