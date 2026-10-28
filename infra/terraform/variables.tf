variable "resource_group_name" {
  description = "Resource group for the app. The bootstrap script creates it and scopes the deploy identity to it."
  type        = string
}

variable "location" {
  description = "Azure region. Defaults to the resource group's region (UK South from the bootstrap script)."
  type        = string
  default     = null
}

variable "name_prefix" {
  description = "Short prefix for resource names. A random suffix is added for globally unique names."
  type        = string
  default     = "triage"

  validation {
    condition     = can(regex("^[a-z][a-z0-9]{1,9}$", var.name_prefix))
    error_message = "Use 2 to 10 lower-case letters or digits, starting with a letter."
  }
}

variable "image_repository" {
  description = "Repository name of the app image in the container registry."
  type        = string
  default     = "ai-ticket-triage"
}

variable "image_tag" {
  description = "Image tag to run. The deploy workflow passes the commit SHA."
  type        = string
  default     = "latest"
}

variable "deployer_principal_type" {
  description = "Principal type of whoever runs Terraform: ServicePrincipal for the GitHub identity, User when run by hand."
  type        = string
  default     = "ServicePrincipal"

  validation {
    condition     = contains(["ServicePrincipal", "User"], var.deployer_principal_type)
    error_message = "Use ServicePrincipal or User."
  }
}

variable "min_replicas" {
  description = "Minimum app replicas. 0 scales to zero when idle (cheapest, with a cold start of a few seconds)."
  type        = number
  default     = 0
}

variable "max_replicas" {
  description = "Maximum app replicas."
  type        = number
  default     = 2
}

variable "retention_days" {
  description = "Days to keep submitted tickets before the daily job deletes them. Demo tickets are refreshed daily."
  type        = number
  default     = 30

  validation {
    condition     = var.retention_days >= 1 && var.retention_days <= 365
    error_message = "Use between 1 and 365 days."
  }
}

variable "enable_easy_auth" {
  description = "Sign analysts in with Microsoft Entra ID (Container Apps authentication). Needs the Graph permission the bootstrap script grants. Off: analysts sign in with a key from Key Vault."
  type        = bool
  default     = false
}

variable "analyst_object_ids" {
  description = "Entra object IDs of the people who may review tickets when Entra sign-in is on."
  type        = list(string)
  default     = []
}

variable "enable_openai" {
  description = "Create an Azure OpenAI resource and turn on the language model assistant. Off: a deterministic stand-in drafts replies."
  type        = bool
  default     = false
}

variable "openai_model" {
  description = "Azure OpenAI model for the assistant. Check the model retirement schedule before changing it."
  type        = string
  default     = "gpt-5.4-mini"
}

variable "openai_model_version" {
  description = "Model version. gpt-5.4-mini 2026-03-17 retires on 21 September 2027 at the earliest."
  type        = string
  default     = "2026-03-17"
}

variable "openai_reasoning_effort" {
  description = "Reasoning effort for gpt-5 family models. Empty for models that do not reason."
  type        = string
  default     = "low"
}

variable "openai_deployment_sku" {
  description = "Deployment type. GlobalStandard is the most widely available; Standard keeps processing in the resource's region (see docs/dpia.md)."
  type        = string
  default     = "GlobalStandard"
}

variable "openai_capacity" {
  description = "Deployment capacity in thousands of tokens per minute."
  type        = number
  default     = 10
}

variable "llm_daily_token_budget" {
  description = "Daily token cap for the assistant. When it is spent the app carries on without the assistant."
  type        = number
  default     = 200000
}

variable "enable_alerts" {
  description = "Email the subscription owners when the app returns server errors."
  type        = bool
  default     = true
}

variable "enable_budget" {
  description = "Create a monthly cost budget for the resource group. Not available on every subscription type."
  type        = bool
  default     = false
}

variable "monthly_budget" {
  description = "Monthly budget in the billing currency."
  type        = number
  default     = 10
}

variable "log_daily_quota_gb" {
  description = "Daily cap on log ingestion, to keep costs inside the free allowance."
  type        = number
  default     = 0.15
}

variable "repo_url" {
  description = "Link to the source code, shown in the app's footer."
  type        = string
  default     = ""
}

variable "secret_version" {
  description = "Increase by one to generate a new analyst key and session secret."
  type        = number
  default     = 1
}

variable "tags" {
  description = "Extra tags for every resource."
  type        = map(string)
  default     = {}
}
