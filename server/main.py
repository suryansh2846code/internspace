"""Multi-tenant server ("brain") for InternHelper — Path B.

Accounts + per-user résumés/applications + the agent job queue. No browser here;
the Playwright work runs in each user's local agent (see agent/)."""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from server.config import settings
from server.db import init_db, check_db, engine
from server.routers import auth, resumes, applications, jobs, actions, agent

log = logging.getLogger("internspace")

# Configure structured logging to stdout/stderr for Azure Container Apps.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: validate config, connect DB, create tables.
    Shutdown: dispose connection pool cleanly."""
    # Fail fast if JWT secret is weak in production.
    settings.validate_for_production()

    # Create tables if missing (idempotent); Alembic migrations come later.
    init_db()
    log.info("Database tables initialised (create_all)")

    # Verify database connectivity.
    if check_db():
        log.info("Database connectivity verified")
    else:
        log.warning("Database connectivity check failed at startup")

    yield

    # Clean shutdown — release all pooled connections.
    engine.dispose()
    log.info("Database connection pool disposed")


app = FastAPI(title="InternHelper API", lifespan=lifespan)


# ── CORS (only when ALLOWED_ORIGINS is configured) ───────────────────────────
if settings.allowed_origins:
    _origins = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/health/db")
def health_db():
    """Separate, slightly heavier probe that tests DB connectivity."""
    ok = check_db()
    return {"ok": ok, "database": "connected" if ok else "unreachable"}


@app.get("/api/platforms")
def platforms():
    # Static here (the brain doesn't import the browser stack).
    return [
        {"name": "internshala", "label": "Internshala", "supports_auto_apply": True},
        {"name": "unstop", "label": "Unstop", "supports_auto_apply": True},
    ]


app.include_router(auth.router)
app.include_router(resumes.router)
app.include_router(applications.router)
app.include_router(jobs.router)
app.include_router(actions.router)
app.include_router(agent.router)

# ── Serve the dashboard ──────────────────────────────────────────────────────
# Use absolute paths derived from this file's location so the container's cwd
# doesn't matter.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FRONTEND = os.path.join(_ROOT, "frontend")
app.mount("/static", StaticFiles(directory=os.path.join(_FRONTEND, "static")), name="static")
app.mount("/assets", StaticFiles(directory=os.path.join(_ROOT, "assets")), name="assets")


@app.middleware("http")
async def _no_cache(request, call_next):
    resp = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/")
def dashboard():
    return FileResponse(os.path.join(_FRONTEND, "index.html"))
