# Deploying InternSpace to Azure

The **server** ("brain") runs on Azure Container Apps; the **agent** ("hands")
runs on each user's local machine with Playwright/Chromium.

```
User Browser → Azure Container Apps → Azure PostgreSQL
                      ↑
                Local Agent (Playwright, Chromium)
```

---

## Prerequisites

| Requirement | How to get it |
|-------------|---------------|
| GitHub account | [github.com](https://github.com) |
| GitHub Student Developer Pack | [education.github.com](https://education.github.com/pack) — includes $100 Azure credit |
| Azure subscription | Activated via Student Pack or [portal.azure.com](https://portal.azure.com) |
| Azure CLI | `brew install azure-cli` or [install guide](https://aka.ms/install-azure-cli) |
| Docker | `brew install --cask docker` or [docker.com](https://docker.com) |

---

## Step 1 — Create Azure Database for PostgreSQL

### Option A: Azure Portal
1. Go to **portal.azure.com** → **Create a resource** → **Azure Database for PostgreSQL Flexible Server**.
2. Choose:
   - **Resource group**: `internspace-rg` (create new)
   - **Server name**: `internspace-pg` (globally unique)
   - **Region**: `East US` (or closest)
   - **PostgreSQL version**: 16
   - **Compute tier**: Burstable → `Standard_B1ms` (~$13/month, covered by Student credit)
   - **Admin username**: `internspaceadmin`
   - **Password**: a strong password
3. Under **Networking**: Allow public access → **Allow access from Azure services** ✓
4. Create the server, then note your connection string:
   ```
   postgresql://internspaceadmin:<PASSWORD>@internspace-pg.postgres.database.azure.com:5432/internspace?sslmode=require
   ```

### Option B: Azure CLI
```bash
az login
az group create --name internspace-rg --location eastus

az postgres flexible-server create \
  --resource-group internspace-rg \
  --name internspace-pg \
  --location eastus \
  --admin-user internspaceadmin \
  --admin-password "<STRONG_PASSWORD>" \
  --database-name internspace \
  --sku-name Standard_B1ms \
  --tier Burstable \
  --version 16 \
  --public-access 0.0.0.0 \
  --yes
```

---

## Step 2 — Create Azure Container Registry (ACR)

```bash
az acr create --resource-group internspace-rg --name internspaceacr --sku Basic --admin-enabled true
az acr login --name internspaceacr
```

---

## Step 3 — Build & Deploy

### Build and push the Docker image

```bash
# From the repo root:
docker build -t internspaceacr.azurecr.io/internspace:latest .
docker push internspaceacr.azurecr.io/internspace:latest
```

Or build in Azure (no local Docker needed):
```bash
az acr build --registry internspaceacr --image internspace:latest .
```

### Create the Container App

```bash
# Create the environment
az containerapp env create \
  --resource-group internspace-rg \
  --name internspace-env \
  --location eastus

# Get ACR credentials
ACR_PASS=$(az acr credential show --name internspaceacr --query "passwords[0].value" -o tsv)

# Generate a strong JWT secret
JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")

# Deploy
az containerapp create \
  --resource-group internspace-rg \
  --name internspace \
  --environment internspace-env \
  --image internspaceacr.azurecr.io/internspace:latest \
  --registry-server internspaceacr.azurecr.io \
  --registry-username internspaceacr \
  --registry-password "$ACR_PASS" \
  --target-port 8000 \
  --ingress external \
  --min-replicas 0 \
  --max-replicas 1 \
  --cpu 0.5 \
  --memory 1Gi \
  --env-vars \
    "DATABASE_URL=postgresql://internspaceadmin:<PASSWORD>@internspace-pg.postgres.database.azure.com:5432/internspace?sslmode=require" \
    "JWT_SECRET=${JWT_SECRET}" \
    "LLM_PROVIDER=groq" \
    "GROQ_API_KEY=<YOUR_GROQ_KEY>"
```

### Or use the helper script

```bash
PG_PASSWORD="<PASSWORD>" GROQ_API_KEY="<KEY>" bash azure/deploy.sh
```

---

## Step 4 — Configure Environment Variables

Set these in the Azure Container App:

| Variable | Required | Notes |
|----------|----------|-------|
| `DATABASE_URL` | ✅ | PostgreSQL connection string with `?sslmode=require` |
| `JWT_SECRET` | ✅ | Long random string — `python3 -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `LLM_PROVIDER` | ✅ | `groq` \| `openai` \| `anthropic` |
| `GROQ_API_KEY` | When using Groq | From [console.groq.com](https://console.groq.com) |
| `OPENAI_API_KEY` | When using OpenAI | From [platform.openai.com](https://platform.openai.com) |
| `ANTHROPIC_API_KEY` | When using Anthropic | From [console.anthropic.com](https://console.anthropic.com) |
| `AGENT_DOWNLOAD_MAC` | Optional | URL to macOS agent download (GitHub Release asset) |
| `AGENT_DOWNLOAD_WINDOWS` | Optional | URL to Windows agent download |
| `ALLOWED_ORIGINS` | Optional | Comma-separated CORS origins (usually not needed) |

To update variables after deploy:
```bash
az containerapp update \
  --resource-group internspace-rg \
  --name internspace \
  --set-env-vars "GROQ_API_KEY=<NEW_KEY>"
```

---

## Step 5 — Configure Health Checks

The app exposes:
- `GET /api/health` — fast, lightweight (for liveness/readiness probes)
- `GET /api/health/db` — includes database connectivity check

In Azure Portal → Container App → **Health probes**:
- **Liveness probe**: HTTP GET `/api/health`, port `8000`, period `30s`
- **Readiness probe**: HTTP GET `/api/health`, port `8000`, period `10s`

---

## Step 6 — Test Production

Get the app URL:
```bash
az containerapp show \
  --resource-group internspace-rg \
  --name internspace \
  --query "properties.configuration.ingress.fqdn" -o tsv
```

Then verify:
```bash
DOMAIN="<your-app>.azurecontainerapps.io"

curl https://$DOMAIN/api/health          # {"ok": true}
curl https://$DOMAIN/api/health/db       # {"ok": true, "database": "connected"}
curl https://$DOMAIN/                    # HTML dashboard
curl https://$DOMAIN/api/platforms       # Platform list
```

Check logs:
```bash
az containerapp logs show \
  --resource-group internspace-rg \
  --name internspace \
  --follow
```

---

## Step 7 — Configure the Local Agent

The agent runs on the user's Mac/Windows — **never on Azure**.

### macOS / Linux

```bash
git clone https://github.com/suryansh2846code/internspace.git
cd internspace
python3 -m pip install -r requirements-agent.txt
python3 -m playwright install chromium

# Connect to Azure:
SERVER_URL=https://<your-app>.azurecontainerapps.io python3 -m agent.agent
```

### Windows (PowerShell)

```powershell
git clone https://github.com/suryansh2846code/internspace.git
cd internspace
python -m pip install -r requirements-agent.txt
python -m playwright install chromium

# Connect to Azure:
$env:SERVER_URL="https://<your-app>.azurecontainerapps.io"
python -m agent.agent
```

The agent will prompt for a pairing code. Get it from the web dashboard:
**Log in → Connect your computer → copy the code → paste it**.

After pairing, the agent stores a device key at `~/.internhelper/agent.json`
and reconnects automatically on subsequent runs (no re-pairing needed).

---

## Updating

```bash
# Rebuild and push
docker build -t internspaceacr.azurecr.io/internspace:latest .
docker push internspaceacr.azurecr.io/internspace:latest

# Restart to pull new image
az containerapp revision restart \
  --resource-group internspace-rg \
  --name internspace
```

Tables are created on startup (`create_all`). New tables appear automatically;
column changes need a migration (Alembic — not yet configured).

---

## Cost Estimate (Student Pack)

| Resource | Tier | ~Monthly Cost |
|----------|------|---------------|
| PostgreSQL Flexible | Burstable B1ms | $13 |
| Container App | 0.5 vCPU / 1 GiB | ~$0 (free tier: 180k vCPU-sec/month) |
| ACR | Basic | $5 |
| **Total** | | **~$18/month** (well within $100 Student credit) |
