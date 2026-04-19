"""Runtime configuration — pydantic-settings + placeholder-rejection validator.

Imported at startup by api (app.main), worker (app.workers.broker), and
scheduler (app.scheduler.jobs). If SECRET_KEY is a placeholder or <32
chars, the process exits 1 BEFORE any socket is opened.

PITFALLS C-3 + FN.
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

    # pre-auth infra (Phase 8 / INFRA-02, INFRA-04)
    REKEY_FROM_SECRET: str | None = Field(
        default=None,
        description=(
            "Previous SECRET_KEY used during credentials rekey. "
            "Set in .env before POST /api/admin/rekey-credentials, "
            "unset after. Deliberately NOT subject to placeholder-length "
            "validation — old keys may pre-date the 32-char rule."
        ),
    )
    SETUP_TOKEN: str | None = Field(
        default=None,
        description=(
            "One-time token gating POST /api/admin/rekey-credentials. "
            "Compared against the X-Setup-Token request header. "
            "Unset this after rekey completes."
        ),
    )
    AUTH_ENABLED: bool = Field(
        default=False,
        description=(
            "Feature flag. False = AuthMiddleware is pass-through and "
            "Next.js proxy preserves X-Dashboard-Role. True = Phase 9 JWT auth. "
            "Flip once Phase 9 ships."
        ),
    )

    # jwt signing key — Phase 9 / AUTH-03. Separate from SECRET_KEY so rotating one
    # does not invalidate the other. Validated by reject_placeholders below.
    JWT_SIGNING_KEY: str = Field(
        ...,
        description=(
            "JWT HS256 signing key (openssl rand -hex 32). Separate from SECRET_KEY: "
            "rotating SECRET_KEY for credential rekey must not invalidate live sessions, "
            "and rotating JWT_SIGNING_KEY for session reset must not touch credentials."
        ),
    )

    # Authentik OIDC — Phase 9 / AUTH-01. All fields optional; presence of SSO_ISSUER_URL
    # enables the OIDC login button on /login and registers /api/auth/oidc/* routes.
    SSO_ISSUER_URL: str | None = Field(
        default=None,
        description="Authentik OIDC issuer URL, e.g. https://authentik.example/application/o/intellibird/",
    )
    SSO_CLIENT_ID: str | None = Field(
        default=None,
        description="Authentik OIDC client_id",
    )
    SSO_CLIENT_SECRET: str | None = Field(
        default=None,
        description="Authentik OIDC client_secret",
    )
    SSO_GROUPS_CLAIM: str = Field(
        default="groups",
        description="id_token claim name that holds the user's group list (Authentik default: 'groups')",
    )
    SSO_ADMIN_GROUPS: str | None = Field(
        default=None,
        description="Comma-separated Authentik group names that map to Admin role",
    )
    SSO_ANALYST_GROUPS: str | None = Field(
        default=None,
        description="Comma-separated Authentik group names that map to Analyst role",
    )
    SSO_VIEWER_GROUPS: str | None = Field(
        default=None,
        description="Comma-separated Authentik group names that map to Viewer role (optional — unmatched groups default to Viewer per CONTEXT.md)",
    )

    # ingest knobs
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

    # geo resolution (MAP-05,)
    GEOLITE_PATH: str = Field(
        default="/app/geolite/GeoLite2-City.mmdb",
        description=(
            "Path to MaxMind GeoLite2 City MMDB file (operator-provided, optional). "
            "If absent, IP-based geo resolution is skipped; STIX location SDOs still resolve."
        ),
    )

    # webhook payload deep-links (HOOK-03..06,)
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
        if self.JWT_SIGNING_KEY in PLACEHOLDERS:
            print(
                "FATAL: JWT_SIGNING_KEY is a placeholder value. "
                "Generate a new one with:  openssl rand -hex 32",
                file=sys.stderr, flush=True,
            )
            sys.exit(1)
        if len(self.JWT_SIGNING_KEY) < MIN_SECRET_KEY_LEN:
            print(
                f"FATAL: JWT_SIGNING_KEY must be at least {MIN_SECRET_KEY_LEN} "
                f"characters (got {len(self.JWT_SIGNING_KEY)}). "
                "Generate a new one with:  openssl rand -hex 32",
                file=sys.stderr, flush=True,
            )
            sys.exit(1)
        return self


# Module-level instance. Importing this module triggers validation; any
# of the three backend services will abort startup if.env is invalid.
settings: Settings = Settings()  # type: ignore[call-arg]
