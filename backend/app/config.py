"""Runtime configuration — pydantic-settings + placeholder-rejection validator.

Imported at startup by api (app.main), worker (app.workers.broker), and
scheduler (app.scheduler.jobs). If SECRET_KEY is a placeholder or <32
chars, the process exits 1 BEFORE any socket is opened.

PITFALLS C-3 + FND-05.
"""
from __future__ import annotations

import sys

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Values that indicate the operator never ran `openssl rand -hex 32`.
PLACEHOLDERS: frozenset[str] = frozenset({
    "",
    "CHANGEME",
    "changeme",
    "your-secret-here",
    "secret",
    "placeholder",
    "replace-me",
})

MIN_SECRET_KEY_LEN: int = 32


class Settings(BaseSettings):
    """IntelliBird runtime settings. All fields loaded from ops/.env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    SECRET_KEY: str = Field(..., description="App secret (openssl rand -hex 32)")
    DATABASE_URL: str = Field(..., description="postgresql+asyncpg://... DSN")
    REDIS_URL: str = Field(default="redis://redis:6379/0")
    HOST: str = Field(default="127.0.0.1",
                      description="API bind address; non-loopback triggers banner")
    PORT: int = Field(default=8000)

    # Phase 2 ingest knobs
    NVD_USER_AGENT: str = Field(
        default="IntelliBird/0.1 (+https://github.com/intellibird)",
        description="User-Agent header sent to nvd.nist.gov per NVD polite-use policy",
    )
    TAXII_USER_AGENT: str = Field(
        default="IntelliBird/0.1",
        description="User-Agent header sent to TAXII servers",
    )
    INGEST_MAX_ITEMS_PER_POLL: int = Field(
        default=5000,
        description="Safety cap — max items processed per single poll attempt across any feed type",
    )
    INGEST_SILENT_FAILURE_THRESHOLD: int = Field(
        default=5,
        description=(
            "Number of consecutive successful polls with zero new rows after which "
            "a source is flagged as silent in the health view (SRC-06). "
            "Plan 02 _effective_status returns 'silent' when silent_failure_count >= this."
        ),
    )

    # Phase 6 geo resolution (MAP-05, D-03/D-04)
    GEOLITE_PATH: str = Field(
        default="/app/geolite/GeoLite2-City.mmdb",
        description=(
            "Path to MaxMind GeoLite2 City MMDB file (operator-provided, optional). "
            "If absent, IP-based geo resolution is skipped; STIX location SDOs still resolve."
        ),
    )

    # Phase 7 webhook payload deep-links (HOOK-03..06, D-34)
    DASHBOARD_URL: str = Field(
        default="http://127.0.0.1:3000",
        description=(
            "Base URL for deep-links embedded in webhook payloads "
            "(e.g. {DASHBOARD_URL}/events?event={id}). Phase 7 D-34."
        ),
    )

    @model_validator(mode="after")
    def reject_placeholders(self) -> "Settings":
        if self.SECRET_KEY in PLACEHOLDERS:
            print(
                "FATAL: SECRET_KEY is a placeholder value. "
                "Generate a new one with:  openssl rand -hex 32",
                file=sys.stderr, flush=True,
            )
            sys.exit(1)
        if len(self.SECRET_KEY) < MIN_SECRET_KEY_LEN:
            print(
                f"FATAL: SECRET_KEY must be at least {MIN_SECRET_KEY_LEN} "
                f"characters (got {len(self.SECRET_KEY)}). "
                "Generate a new one with:  openssl rand -hex 32",
                file=sys.stderr, flush=True,
            )
            sys.exit(1)
        return self


# Module-level instance. Importing this module triggers validation; any
# of the three backend services will abort startup if .env is invalid.
settings: Settings = Settings()  # type: ignore[call-arg]
