"""SQLAlchemy engine + session (sync; runs in FastAPI's threadpool)."""
import logging
import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from server.config import settings

log = logging.getLogger("internspace")

# Railway / Azure sometimes give postgres:// URLs; SQLAlchemy wants postgresql://
_url = settings.database_url.replace("postgres://", "postgresql://", 1)

_is_sqlite = _url.startswith("sqlite")

# For the SQLite fallback, make sure its directory exists (else "unable to open").
if _is_sqlite:
    _path = _url.split("sqlite:///", 1)[-1]
    if _path and os.path.dirname(_path):
        os.makedirs(os.path.dirname(_path), exist_ok=True)

# Build engine kwargs based on database type.
_engine_kwargs: dict = {"pool_pre_ping": True}

if _is_sqlite:
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    # Production PostgreSQL — sensible connection pooling for a small
    # Azure Container App (single-container, ~5 concurrent connections).
    _engine_kwargs["pool_size"] = settings.db_pool_size
    _engine_kwargs["max_overflow"] = settings.db_max_overflow
    _engine_kwargs["pool_recycle"] = settings.db_pool_recycle

    # Azure Database for PostgreSQL Flexible Server requires SSL by default.
    # If the user's DATABASE_URL already includes sslmode=require, psycopg2
    # handles it natively. No additional connect_args are needed here because
    # psycopg2-binary respects URL-embedded SSL parameters.

engine = create_engine(_url, **_engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency — yields a session, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from server import models  # noqa: F401  (register models)
    Base.metadata.create_all(bind=engine)


def check_db() -> bool:
    """Quick connectivity probe (SELECT 1). Returns True on success."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        log.warning("Database health check failed: %s", exc)
        return False
