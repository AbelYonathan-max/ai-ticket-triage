#!/usr/bin/env bash
# One-time Azure set-up for the AI ticket triage service, run by the subscription owner.
#
# In Azure Cloud Shell (Bash):
#   git clone https://github.com/OWNER/REPO.git && bash REPO/infra/bootstrap/bootstrap.sh OWNER/REPO
#
# What it does, all inside your own subscription:
#   1. Signs in to GitHub with a one-time code, to read the repository's IDs and set its variables.
#   2. Picks a region: UK South, unless your subscription only allows certain regions.
#   3. Registers the Azure resource providers the app uses.
#   4. Creates two resource groups: one for the app, one for the Terraform state and deploy identity.
#   5. Creates a storage account for Terraform state (no shared keys, no public access, versioning on).
#   6. Creates the deploy identity that GitHub Actions signs in as, trusted only for this repository's
#      "production" environment (OpenID Connect, so no password or key is stored anywhere).
#   7. Gives that identity Contributor on the app resource group only, plus the right to grant a short
#      list of roles there, and access to the state container.
#   8. Gives you read access to the app's Key Vault secrets (to fetch the analyst key).
#   9. If your account can, lets the deploy identity create the Entra ID app registration for sign-in.
#  10. Sets the repository variables (names and IDs, nothing secret) and starts the first deploy.
#
# Safe to run again: every step checks what already exists. To choose the region yourself, put
# LOCATION=<region> in front of the command.
set -euo pipefail

REPO="${1:?Usage: bootstrap.sh OWNER/REPO}"
LOCATION="${LOCATION:-}"
APP_RG="${APP_RG:-rg-triage-prod}"
OPS_RG="${OPS_RG:-rg-triage-ops}"
IDENTITY_NAME="${IDENTITY_NAME:-id-triage-github}"
GRAPH_APP_ID="00000003-0000-0000-c000-000000000000"
PREFERRED_REGIONS="uksouth ukwest northeurope westeurope swedencentral francecentral germanywestcentral norwayeast switzerlandnorth polandcentral italynorth spaincentral eastus2 eastus centralus westus2 westus3"

say() { printf '\n== %s\n' "$*"; }

on_exit() {
  local status=$?
  if [ "$status" -ne 0 ]; then
    echo
    echo "!! The script stopped because the step above failed. Fix what its message says and run the same"
    echo "   command again: every step is safe to repeat. If the message says RequestDisallowedByAzure, your"
    echo "   subscription can only deploy to some regions: put one in front, for example LOCATION=westeurope bash ..."
  fi
}
trap on_exit EXIT

retry() {
  # Run a command until it works, for permissions and identities that take a while to propagate.
  local attempt
  for attempt in 1 2 3 4 5 6 7 8 9 10; do
    if "$@"; then return 0; fi
    echo "   not ready yet (attempt $attempt), waiting 15 seconds"
    sleep 15
  done
  return 1
}

say "Checking your Azure account"
SUBSCRIPTION_ID=$(az account show --query id -o tsv)
TENANT_ID=$(az account show --query tenantId -o tsv)
SUBSCRIPTION_NAME=$(az account show --query name -o tsv)
QUOTA_ID=$(az rest --method get --url "/subscriptions/${SUBSCRIPTION_ID}?api-version=2022-12-01" \
  --query subscriptionPolicies.quotaId -o tsv 2>/dev/null || echo unknown)
ME=$(az ad signed-in-user show --query id -o tsv)
echo "   subscription: $SUBSCRIPTION_NAME ($QUOTA_ID)"

say "Signing in to GitHub"
GH=false
GH_LOGGED_IN_HERE=false
if command -v gh >/dev/null 2>&1; then
  if gh auth status --hostname github.com >/dev/null 2>&1; then
    GH=true
  else
    echo "   Needed once, to read the repository's IDs, set its variables and start the first deploy."
    echo "   Press Enter, copy the one-time code, open https://github.com/login/device and paste the code there."
    if gh auth login --hostname github.com --git-protocol https --web; then
      GH=true
      GH_LOGGED_IN_HERE=true
    fi
  fi
fi
github_api() {
  # github_api PATH JQ_FILTER: read from the GitHub API, signed in if possible.
  if [ "$GH" = true ]; then
    gh api "$1" --jq "$2"
  else
    curl -fsS "https://api.github.com/$1" | jq -r "$2"
  fi
}
REPO_INFO=$(github_api "repos/$REPO" '[.owner.login, .owner.id, .name, .id, .created_at] | @tsv' 2>/dev/null || true)
if [ -z "$REPO_INFO" ]; then
  echo "   Could not read https://github.com/$REPO. Check the OWNER/REPO name, and sign in to GitHub if it is private."
  exit 1
fi
read -r OWNER OWNER_ID NAME REPO_ID CREATED <<<"$REPO_INFO"
REPO="$OWNER/$NAME" # GitHub's exact spelling, which the deploy token's subject uses
echo "   repository: https://github.com/$REPO"

say "Choosing the region"
if [ -z "$LOCATION" ]; then
  # Azure for Students and some trial subscriptions may only deploy to a few regions, listed in a policy
  # assignment such as "Allowed resource deployment regions". Use one of those if UK South is not allowed.
  ALLOWED=$(az policy assignment list --disable-scope-strict-match -o json 2>/dev/null | python3 -c '
import json, sys
regions = set()
for assignment in json.load(sys.stdin):
    title = (assignment.get("displayName") or assignment.get("name") or "").lower()
    if "region" in title or "location" in title:
        for parameter in (assignment.get("parameters") or {}).values():
            value = parameter.get("value") if isinstance(parameter, dict) else None
            if isinstance(value, list):
                regions.update(v.lower() for v in value if isinstance(v, str) and v.lower() != "global")
print(" ".join(sorted(regions)))
' 2>/dev/null || true)
  LOCATION=uksouth
  if [ -n "$ALLOWED" ] && [[ " $ALLOWED " != *" uksouth "* ]]; then
    echo "   your subscription only allows: $ALLOWED"
    for region in $PREFERRED_REGIONS $ALLOWED; do
      if [[ " $ALLOWED " == *" $region "* ]]; then
        LOCATION=$region
        break
      fi
    done
  fi
fi
echo "   using $LOCATION"

say "Registering resource providers (can take a few minutes the first time)"
PROVIDERS="Microsoft.App Microsoft.ContainerRegistry Microsoft.KeyVault Microsoft.Sql Microsoft.OperationalInsights Microsoft.Insights Microsoft.ManagedIdentity Microsoft.Storage Microsoft.CognitiveServices Microsoft.Consumption Microsoft.AlertsManagement"
for ns in $PROVIDERS; do
  az provider register --namespace "$ns" --output none
done
for ns in $PROVIDERS; do
  until [ "$(az provider show --namespace "$ns" --query registrationState -o tsv)" = "Registered" ]; do
    echo "   waiting for $ns"
    sleep 10
  done
done

say "Resource groups"
# A resource group's own region does not limit its resources: everything is created in $LOCATION.
for rg in "$APP_RG" "$OPS_RG"; do
  if [ "$(az group exists --name "$rg")" != "true" ]; then
    az group create --name "$rg" --location "$LOCATION" --tags app=ai-ticket-triage --output none
  fi
done
APP_RG_ID=$(az group show --name "$APP_RG" --query id -o tsv)

say "Terraform state storage"
STATE_ACCOUNT=$(az storage account list --resource-group "$OPS_RG" --query "[0].name" -o tsv)
if [ -z "$STATE_ACCOUNT" ]; then
  STATE_ACCOUNT="sttriage$(printf '%04x%04x' "$RANDOM" "$RANDOM")"
  az storage account create --name "$STATE_ACCOUNT" --resource-group "$OPS_RG" --location "$LOCATION" \
    --sku Standard_LRS --kind StorageV2 --min-tls-version TLS1_2 --https-only true \
    --allow-blob-public-access false --allow-shared-key-access false --output none
fi
az storage account blob-service-properties update --account-name "$STATE_ACCOUNT" --resource-group "$OPS_RG" \
  --enable-versioning true --enable-delete-retention true --delete-retention-days 14 --output none
if [ "$(az storage container-rm exists --storage-account "$STATE_ACCOUNT" --name tfstate --query exists -o tsv)" != "true" ]; then
  az storage container-rm create --storage-account "$STATE_ACCOUNT" --name tfstate --output none
fi
STATE_ACCOUNT_ID=$(az storage account show --name "$STATE_ACCOUNT" --resource-group "$OPS_RG" --query id -o tsv)

say "Deploy identity for GitHub Actions"
if ! az identity show --name "$IDENTITY_NAME" --resource-group "$OPS_RG" --output none 2>/dev/null; then
  az identity create --name "$IDENTITY_NAME" --resource-group "$OPS_RG" --location "$LOCATION" --output none
fi
CLIENT_ID=$(az identity show --name "$IDENTITY_NAME" --resource-group "$OPS_RG" --query clientId -o tsv)
PRINCIPAL_ID=$(az identity show --name "$IDENTITY_NAME" --resource-group "$OPS_RG" --query principalId -o tsv)

federate() {
  # federate NAME SUBJECT: trust GitHub Actions tokens with this subject (updated if the repository moved).
  local current
  current=$(az identity federated-credential show --name "$1" --identity-name "$IDENTITY_NAME" \
    --resource-group "$OPS_RG" --query subject -o tsv 2>/dev/null || true)
  if [ -z "$current" ]; then
    az identity federated-credential create --name "$1" --identity-name "$IDENTITY_NAME" \
      --resource-group "$OPS_RG" --issuer https://token.actions.githubusercontent.com \
      --subject "$2" --audiences api://AzureADTokenExchange --output none
  elif [ "$current" != "$2" ]; then
    az identity federated-credential update --name "$1" --identity-name "$IDENTITY_NAME" \
      --resource-group "$OPS_RG" --subject "$2" --output none
  fi
  echo "   trusts GitHub tokens for: $2"
}
# GitHub puts the repository in the token's subject. Repositories created or renamed after 15 July 2026
# use the owner and repository IDs as well as the names (repo:owner@id/name@id:...), so nobody can reuse
# the name to deploy here. Older repositories may still use names only, so they also get that form.
federate github-production "repo:${OWNER}@${OWNER_ID}/${NAME}@${REPO_ID}:environment:production"
if [[ "$CREATED" < "2026-07-15" ]]; then
  federate github-production-names "repo:${REPO}:environment:production"
fi

assign() {
  # assign ROLE SCOPE [extra az arguments]: idempotent role assignment for the deploy identity.
  local role="$1" scope="$2"
  shift 2
  if [ -n "$(az role assignment list --assignee "$PRINCIPAL_ID" --role "$role" --scope "$scope" --query '[0].id' -o tsv)" ]; then
    return 0
  fi
  retry az role assignment create --assignee-object-id "$PRINCIPAL_ID" --assignee-principal-type ServicePrincipal \
    --role "$role" --scope "$scope" "$@" --output none
}

say "Permissions for the deploy identity"
assign "Contributor" "$APP_RG_ID"
assign "Storage Blob Data Contributor" "$STATE_ACCOUNT_ID"

# It may grant only these roles, and only inside the app resource group.
role_id() { az role definition list --name "$1" --query "[0].name" -o tsv; }
GRANTABLE="$(role_id AcrPull), $(role_id AcrPush), $(role_id 'Key Vault Secrets User'), $(role_id 'Key Vault Secrets Officer'), $(role_id 'Cognitive Services OpenAI User')"
CONDITION="((!(ActionMatches{'Microsoft.Authorization/roleAssignments/write'})) OR (@Request[Microsoft.Authorization/roleAssignments:RoleDefinitionId] ForAnyOfAnyValues:GuidEquals {${GRANTABLE}})) AND ((!(ActionMatches{'Microsoft.Authorization/roleAssignments/delete'})) OR (@Resource[Microsoft.Authorization/roleAssignments:RoleDefinitionId] ForAnyOfAnyValues:GuidEquals {${GRANTABLE}}))"
assign "Role Based Access Control Administrator" "$APP_RG_ID" --condition "$CONDITION" --condition-version 2.0

say "Your own access to the app's secrets"
if [ -z "$(az role assignment list --assignee "$ME" --role 'Key Vault Secrets User' --scope "$APP_RG_ID" --query '[0].id' -o tsv)" ]; then
  az role assignment create --assignee-object-id "$ME" --assignee-principal-type User \
    --role "Key Vault Secrets User" --scope "$APP_RG_ID" --output none
fi

say "Microsoft Entra sign-in (optional)"
EASY_AUTH=false
GRAPH_SP=$(az ad sp show --id "$GRAPH_APP_ID" --query id -o tsv 2>/dev/null || true)
OWNED_BY=$(az ad sp show --id "$GRAPH_APP_ID" --query "appRoles[?value=='Application.ReadWrite.OwnedBy'].id | [0]" -o tsv 2>/dev/null || true)
if [ -n "$GRAPH_SP" ] && [ -n "$OWNED_BY" ]; then
  EXISTING=$(az rest --method get --url "https://graph.microsoft.com/v1.0/servicePrincipals/${PRINCIPAL_ID}/appRoleAssignments" \
    --query "value[?appRoleId=='${OWNED_BY}'].id | [0]" -o tsv 2>/dev/null || true)
  if [ -n "$EXISTING" ]; then
    EASY_AUTH=true
  elif az rest --method post --url "https://graph.microsoft.com/v1.0/servicePrincipals/${PRINCIPAL_ID}/appRoleAssignments" \
    --headers "Content-Type=application/json" \
    --body "{\"principalId\":\"${PRINCIPAL_ID}\",\"resourceId\":\"${GRAPH_SP}\",\"appRoleId\":\"${OWNED_BY}\"}" \
    --output none 2>/dev/null; then
    EASY_AUTH=true
  fi
fi
if [ "$EASY_AUTH" = true ]; then
  echo "   on: analysts will sign in with their Microsoft account"
else
  echo "   off: your account cannot grant Microsoft Graph permissions, so analysts sign in with a key from Key Vault"
fi

# Budgets are not available on every subscription type.
case "$QUOTA_ID" in
  AzureForStudents* | Sponsored* | AzurePass* | unknown) BUDGET=false ;;
  *) BUDGET=true ;;
esac

say "GitHub repository variables"
VARS=(
  "AZURE_CLIENT_ID=$CLIENT_ID"
  "AZURE_TENANT_ID=$TENANT_ID"
  "AZURE_SUBSCRIPTION_ID=$SUBSCRIPTION_ID"
  "AZURE_LOCATION=$LOCATION"
  "APP_RESOURCE_GROUP=$APP_RG"
  "TFSTATE_RESOURCE_GROUP=$OPS_RG"
  "TFSTATE_STORAGE_ACCOUNT=$STATE_ACCOUNT"
  "ENABLE_EASY_AUTH=$EASY_AUTH"
  "ENABLE_BUDGET=$BUDGET"
  "ANALYST_OBJECT_IDS=[\"$ME\"]"
)
SET_BY_SCRIPT=false
DEPLOY_STARTED=false
if [ "$GH" = true ]; then
  SET_BY_SCRIPT=true
  for pair in "${VARS[@]}"; do
    gh variable set "${pair%%=*}" --repo "$REPO" --body "${pair#*=}" || SET_BY_SCRIPT=false
  done
fi
if [ "$SET_BY_SCRIPT" = true ]; then
  echo "   set on https://github.com/$REPO/settings/variables/actions"
  echo "   giving Azure a minute to apply the new permissions, then starting the first deploy"
  sleep 60
  if gh workflow run deploy.yml --repo "$REPO"; then
    DEPLOY_STARTED=true
  fi
else
  echo "   Could not set them from here. Add these under Settings > Secrets and variables > Actions > Variables,"
  echo "   then run the Deploy workflow from the Actions tab:"
  for pair in "${VARS[@]}"; do echo "     ${pair%%=*} = ${pair#*=}"; done
fi
if [ "$GH_LOGGED_IN_HERE" = true ]; then
  gh auth logout --hostname github.com </dev/null >/dev/null 2>&1 || true
fi

say "Done"
echo "   region: $LOCATION, subscription type: $QUOTA_ID"
echo "   Entra sign-in: $EASY_AUTH, cost budget: $BUDGET"
if [ "$DEPLOY_STARTED" = true ]; then
  echo "   first deploy started, about 15 minutes: https://github.com/$REPO/actions/workflows/deploy.yml"
fi
echo "   None of these values is a secret: they are names and IDs. Azure accepts sign-ins for the deploy"
echo "   identity only from GitHub Actions runs in ${REPO}, environment 'production'."
