# InternHelper

**Find internships. Apply from your own machine. Keep platform logins off the server.**

InternHelper is a multi-tenant internship application assistant for **Internshala** and **Unstop**. A cloud **brain** queues work and stores your account data. A local **agent** on your computer does the browser work with *your* session and *your* IP.

> Built for personal productivity. Respect each platform’s terms of use. You stay in control of every apply.

---

## How it works

```
Dashboard (browser)  ──HTTPS──►  Server / brain  ◄──HTTPS poll──  Agent / hands
   you click actions         accounts + job queue              Playwright on your PC
```

| Piece | Role |
|--------|------|
| **Brain** (`server/`) | FastAPI app: accounts, résumés, applications, settings, job queue. No browser. |
| **Hands** (`agent/`) | Runs on your Mac/PC. Logs into platforms locally, claims jobs, reports results. |
| **Dashboard** (`frontend/`) | Vanilla HTML/CSS/JS UI served by the server. |

Platform passwords never sit on the server. The agent only **polls out** over HTTPS.

---

## Features

- Upload résumés per role and extract search keywords with an LLM
- Search listings across Internshala and Unstop
- Queue search / apply / sync jobs from the dashboard
- Local agent (menu bar on macOS, or terminal) executes jobs with Playwright
- Device pairing with a short code (“Connect your computer”)
- Pause / stop controls the agent honors cooperatively
- Pluggable LLMs: Groq, OpenAI, Anthropic, or local

---

## Repo map

| Path | What it is |
|------|------------|
| `server/` | Brain — FastAPI, auth, DB, job queue |
| `agent/` | Hands — job loop, pairing, macOS menu bar |
| `adapters/` | Platform-specific logic behind one interface |
| `frontend/` | Dashboard UI |
| `applicant/` | Résumé parse, keywords, answer generation |
| `scraper/` / `apply/` | Listing scrape and form fill |
| `packaging/` | PyInstaller specs for downloadable apps |
| `ARCHITECTURE.md` | Full system map |
| `JOURNEY.md` | How it grew (problem → fix log) |
| `PROJECT.md` | Design journal |
| `DEPLOY.md` | Railway deploy notes |

---

## Quick start (local)

### 1. Server (brain)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-server.txt
cp .env.example .env   # set JWT_SECRET + LLM keys as needed
python -m server.main  # or follow DEPLOY.md for Railway + Postgres
```

### 2. Agent (hands)

```bash
pip install -r requirements-agent.txt
playwright install chromium

# macOS menu bar
python -m agent.app

# or terminal
SERVER_URL=http://localhost:8000 AGENT_PAIR_TOKEN=<code> python -m agent.agent
```

Pair from the dashboard **Connect your computer** panel, then log into Internshala / Unstop once in the headed browser. Session stays in a local profile.

More detail: [agent/README.md](agent/README.md) · [DEPLOY.md](DEPLOY.md)

---

## Stack

- **Python** — FastAPI, SQLAlchemy, Playwright, optional rumps (macOS tray)
- **Postgres** in production (Railway); SQLite-friendly for early local runs
- **LLM** — Groq / OpenAI / Anthropic / local via a small provider factory
- **Frontend** — no framework; plain HTML/CSS/JS

---

## Status

Actively used as a personal/systems project. Packaging and multi-tenant Path-B architecture are documented in `ARCHITECTURE.md` and `JOURNEY.md`.

Suggested GitHub description:

> Multi-tenant internship assistant: cloud job queue + local Playwright agent for Internshala & Unstop (logins stay on your machine).

Suggested topics: `python`, `fastapi`, `playwright`, `internship`, `automation`, `multi-tenant`

---

## License

No license file yet. Ask if you want MIT (or another) added before promoting the repo.
