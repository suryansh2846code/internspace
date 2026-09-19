"""Server settings (env-driven). Azure / Railway inject DATABASE_URL + secrets."""
import logging

from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger("internspace")

_WEAK_SECRETS = frozenset({
    "dev-secret-change-me", "secret", "development", "test",
    "123456", "changeme", "password",
})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # SQLite locally, Postgres in production (Azure / Railway).
    database_url: str = "sqlite:///./data/app.db"
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_ttl_min: int = 60 * 24 * 14      # 14 days (web session)
    pairing_token_ttl_min: int = 15               # device pairing window
    agent_key_ttl_min: int = 60 * 24 * 365        # 1 year (paired device key)
    agent_online_secs: int = 40                   # heartbeat freshness for "online"

    # Where agents upload/read résumé files (local dir now; S3/R2 later)
    resume_dir: str = "./data/resumes"

    # Download URLs for the packaged agent apps (empty → Connect modal shows the
    # terminal fallback only). Set to GitHub Release assets once built.
    agent_download_mac: str = ""
    agent_download_windows: str = ""

    # CORS: comma-separated origins, e.g. "https://my-app.azurecontainerapps.io"
    # Empty → no CORS middleware (frontend is same-origin).
    allowed_origins: str = ""

    # Database connection-pool tuning (ignored for SQLite).
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_recycle: int = 1800  # seconds — recycle before Azure drops idle conns

    @property
    def is_production_db(self) -> bool:
        """True when using a real PostgreSQL database (not SQLite)."""
        return not self.database_url.startswith("sqlite")

    def validate_for_production(self) -> None:
        """Fail loudly if a weak JWT secret is used against a production DB."""
        if self.is_production_db and self.jwt_secret in _WEAK_SECRETS:
            raise RuntimeError(
                "FATAL: JWT_SECRET is set to a weak default. "
                "Set a strong, random JWT_SECRET environment variable before "
                "deploying with PostgreSQL."
            )
        if self.is_production_db:
            log.info("Production mode: PostgreSQL database detected")
        else:
            log.info("Development mode: SQLite database")


settings = Settings()
