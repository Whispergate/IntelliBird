"""Pydantic v2 schemas for webhook CRUD + test-send — HOOK-01, HOOK-09."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

DestinationType = Literal["slack", "teams", "discord", "generic"]
DeliveryStatus = Literal["ok", "http_error", "network_error", "timeout"]

_BATCHING_ALLOWED = {0, 60, 300, 900, 1800}  #
_NAME_REGEX = r"^[a-z0-9_-]{1,64}$"


# ---------------------------------------------------------------------------
# Auth discriminated union
# ---------------------------------------------------------------------------


class BearerAuth(BaseModel):
    """Bearer token authentication — adds Authorization: Bearer <token> header."""

    type: Literal["bearer"] = "bearer"
    token: str = Field(min_length=1)


class BasicAuth(BaseModel):
    """HTTP Basic authentication — adds Authorization: Basic <base64> header."""

    type: Literal["basic"] = "basic"
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class HeaderAuth(BaseModel):
    """Arbitrary custom header authentication — adds {name}: {value} header."""

    type: Literal["header"] = "header"
    name: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1)


# Pydantic v2 discriminated union via Annotated + Field(discriminator=...)
AuthSpec = BearerAuth | BasicAuth | HeaderAuth


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class WebhookCreate(BaseModel):
    """Payload to create a new webhook destination. (HOOK-01)"""

    name: str = Field(pattern=_NAME_REGEX, min_length=1, max_length=64)
    project_id: uuid.UUID
    destination_type: DestinationType
    url: str = Field(min_length=1, max_length=2000)
    auth: AuthSpec | None = None
    batching_window_sec: int = Field(default=300)
    enabled: bool = True
    bound_preset_names: list[str] = Field(default_factory=list)

    def validate_batching(self) -> None:
        """Raise ValueError if batching_window_sec is not in the allowed set."""
        if self.batching_window_sec not in _BATCHING_ALLOWED:
            raise ValueError(
                f"batching_window_sec must be one of {sorted(_BATCHING_ALLOWED)}"
            )


class WebhookUpdate(BaseModel):
    """Payload to partially update a webhook.

 destination_type DELIBERATELY ABSENT — locked on edit.
"""

    name: str | None = Field(default=None, pattern=_NAME_REGEX)
    url: str | None = None
    auth: AuthSpec | None = None
    # None/absent → keep existing auth; set clear_auth=True to remove auth entirely.
    clear_auth: bool = False
    batching_window_sec: int | None = None
    enabled: bool | None = None
    bound_preset_names: list[str] | None = None


# ---------------------------------------------------------------------------
# Response schema
# ---------------------------------------------------------------------------


class WebhookResponse(BaseModel):
    """Webhook representation returned by CRUD endpoints.

 auth_enc DELIBERATELY ABSENT — SRC-04 parallel: credentials never returned
 in plaintext responses. bound_preset_names populated via join query in router
 (07-04); defaults to [] for schema-level tests.
"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    destination_type: DestinationType
    url: str
    # auth_enc DELIBERATELY ABSENT — SRC-04 parallel
    batching_window_sec: int
    enabled: bool
    last_dispatch_at: datetime | None
    last_delivery_at: datetime | None
    last_delivery_status: str | None
    consecutive_failures: int
    bound_preset_names: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Test-send schemas (HOOK-09)
# ---------------------------------------------------------------------------


class TestSendRequest(BaseModel):
    """Payload for the test-send endpoint.

 Client sends plaintext auth — backend encrypts for the round-trip.
 Always returns HTTP 200; ok flag signals success/failure.
"""

    destination_type: DestinationType
    url: str = Field(min_length=1)
    auth: AuthSpec | None = None


class TestSendResponse(BaseModel):
    """Result of a test-send. HTTP 200 always; ok=False means delivery failed."""

    ok: bool
    latency_ms: int
    error_detail: str | None = None
