#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# InternSpace — Azure Container Apps Deployment Helper
#
# Prerequisites:
#   - Azure CLI installed:  brew install azure-cli   (or https://aka.ms/install-azure-cli)
#   - Docker installed:     brew install --cask docker
#   - An active Azure subscription (GitHub Student Developer Pack includes $100 credit)
#
# Usage:
#   1. Edit the variables below.
#   2. Run:  bash azure/deploy.sh
#
# This script is idempotent — re-running it updates existing resources.
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Configuration (edit these) ────────────────────────────────────────────────
RESOURCE_GROUP="${RESOURCE_GROUP:-internspace-rg}"
LOCATION="${LOCATION:-eastus}"
ACR_NAME="${ACR_NAME:-internspaceacr}"        # must be globally unique, lowercase
CONTAINER_APP_ENV="${CONTAINER_APP_ENV:-internspace-env}"
CONTAINER_APP_NAME="${CONTAINER_APP_NAME:-internspace}"
PG_SERVER="${PG_SERVER:-internspace-pg}"       # must be globally unique
PG_DB="${PG_DB:-internspace}"
PG_ADMIN="${PG_ADMIN:-internspaceadmin}"
IMAGE_TAG="latest"

# ── Derived ───────────────────────────────────────────────────────────────────
IMAGE="${ACR_NAME}.azurecr.io/internspace:${IMAGE_TAG}"

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  InternSpace → Azure Container Apps Deployment              ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# ── 0. Login ──────────────────────────────────────────────────────────────────
echo "▸ Checking Azure login..."
az account show > /dev/null 2>&1 || az login
echo ""

# ── 1. Resource Group ─────────────────────────────────────────────────────────
echo "▸ Creating resource group: ${RESOURCE_GROUP} in ${LOCATION}..."
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --output none
echo "  ✓ Resource group ready"

# ── 2. Azure Container Registry ──────────────────────────────────────────────
echo "▸ Creating ACR: ${ACR_NAME}..."
az acr create --resource-group "$RESOURCE_GROUP" --name "$ACR_NAME" \
  --sku Basic --admin-enabled true --output none 2>/dev/null || true
echo "  ✓ ACR ready"

echo "▸ Logging into ACR..."
az acr login --name "$ACR_NAME"

# ── 3. Build & Push Docker Image ─────────────────────────────────────────────
echo "▸ Building and pushing image: ${IMAGE}..."
# Build in Azure (no local Docker needed) or locally if Docker is available.
if command -v docker &> /dev/null; then
  docker build -t "$IMAGE" .
  docker push "$IMAGE"
else
  echo "  Docker not found locally — building in Azure..."
  az acr build --registry "$ACR_NAME" --image "internspace:${IMAGE_TAG}" . --no-logs
fi
echo "  ✓ Image pushed"

# ── 4. PostgreSQL Flexible Server ─────────────────────────────────────────────
echo "▸ Creating PostgreSQL Flexible Server: ${PG_SERVER}..."
echo "  ⚠  You will be prompted for a password (or set PG_PASSWORD env var)."
PG_PASSWORD="${PG_PASSWORD:-}"
if [ -z "$PG_PASSWORD" ]; then
  read -rsp "  Enter PostgreSQL admin password: " PG_PASSWORD
  echo ""
fi

az postgres flexible-server create \
  --resource-group "$RESOURCE_GROUP" \
  --name "$PG_SERVER" \
  --location "$LOCATION" \
  --admin-user "$PG_ADMIN" \
  --admin-password "$PG_PASSWORD" \
  --database-name "$PG_DB" \
  --sku-name Standard_B1ms \
  --tier Burstable \
  --storage-size 32 \
  --version 16 \
  --public-access 0.0.0.0 \
  --yes \
  --output none 2>/dev/null || echo "  (server may already exist)"

DATABASE_URL="postgresql://${PG_ADMIN}:${PG_PASSWORD}@${PG_SERVER}.postgres.database.azure.com:5432/${PG_DB}?sslmode=require"
echo "  ✓ PostgreSQL ready"

# ── 5. Container Apps Environment ─────────────────────────────────────────────
echo "▸ Creating Container Apps environment: ${CONTAINER_APP_ENV}..."
az containerapp env create \
  --resource-group "$RESOURCE_GROUP" \
  --name "$CONTAINER_APP_ENV" \
  --location "$LOCATION" \
  --output none 2>/dev/null || true
echo "  ✓ Environment ready"

# ── 6. Deploy Container App ──────────────────────────────────────────────────
ACR_SERVER="${ACR_NAME}.azurecr.io"
ACR_PASS=$(az acr credential show --name "$ACR_NAME" --query "passwords[0].value" -o tsv)

echo "▸ Deploying Container App: ${CONTAINER_APP_NAME}..."
echo "  ⚠  Set JWT_SECRET, LLM keys, etc. via 'az containerapp update' after deploy."

# Generate a JWT secret if not set.
JWT_SECRET="${JWT_SECRET:-$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))' 2>/dev/null || openssl rand -base64 48)}"

az containerapp create \
  --resource-group "$RESOURCE_GROUP" \
  --name "$CONTAINER_APP_NAME" \
  --environment "$CONTAINER_APP_ENV" \
  --image "$IMAGE" \
  --registry-server "$ACR_SERVER" \
  --registry-username "$ACR_NAME" \
  --registry-password "$ACR_PASS" \
  --target-port 8000 \
  --ingress external \
  --min-replicas 0 \
  --max-replicas 1 \
  --cpu 0.5 \
  --memory 1Gi \
  --env-vars \
    "DATABASE_URL=${DATABASE_URL}" \
    "JWT_SECRET=${JWT_SECRET}" \
    "LLM_PROVIDER=${LLM_PROVIDER:-groq}" \
    "GROQ_API_KEY=${GROQ_API_KEY:-}" \
  --output none 2>/dev/null || \
az containerapp update \
  --resource-group "$RESOURCE_GROUP" \
  --name "$CONTAINER_APP_NAME" \
  --image "$IMAGE" \
  --output none

echo "  ✓ Container App deployed"

# ── 7. Get the URL ────────────────────────────────────────────────────────────
FQDN=$(az containerapp show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$CONTAINER_APP_NAME" \
  --query "properties.configuration.ingress.fqdn" -o tsv)

echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  ✅  InternSpace is live at: https://${FQDN}"
echo ""
echo "  Health check:  curl https://${FQDN}/api/health"
echo ""
echo "  To update env vars:"
echo "    az containerapp update \\"
echo "      --resource-group ${RESOURCE_GROUP} \\"
echo "      --name ${CONTAINER_APP_NAME} \\"
echo "      --set-env-vars KEY=value"
echo ""
echo "  To view logs:"
echo "    az containerapp logs show \\"
echo "      --resource-group ${RESOURCE_GROUP} \\"
echo "      --name ${CONTAINER_APP_NAME} \\"
echo "      --follow"
echo ""
echo "  Local agent:"
echo "    SERVER_URL=https://${FQDN} python3 -m agent.agent"
echo "════════════════════════════════════════════════════════════════"
