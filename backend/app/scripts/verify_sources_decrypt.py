"""PROD-04 read-back verifier for SECRET_KEY rotation drills.

Run AFTER `POST /api/admin/rekey-credentials` to confirm every
`sources.credentials_enc` blob decrypts cleanly under the current
`SECRET_KEY`. Complements the lifespan canary check (which only proves
the canary row survives) by iterating every real source row.

Exit codes:
    0 — every non-NULL credentials_enc decrypted OK.
    1 — one or more rows failed (IDs + error types printed to stderr).

Usage:
    docker compose -f ops/docker-compose.yml exec api \\
        python -m app.scripts.verify_sources_decrypt
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select

from app.config import settings
from app.crypto import decrypt_credentials
from app.database import async_session_factory
from app.models.sources import Source


async def _run() -> int:
    async with async_session_factory() as session:
        rows = (await session.execute(select(Source.id, Source.credentials_enc))).all()

    total = 0
    failed: list[tuple[str, str]] = []
    for sid, enc in rows:
        if enc is None:
            continue
        total += 1
        try:
            decrypt_credentials(settings.SECRET_KEY, enc)
        except Exception as exc:  # noqa: BLE001 — surface any failure
            failed.append((str(sid), f"{type(exc).__name__}: {exc}"))

    if failed:
        print(
            f"FAIL: {len(failed)}/{total} sources could not decrypt under current SECRET_KEY:",
            file=sys.stderr,
        )
        for sid, err in failed:
            print(f"  - {sid}: {err}", file=sys.stderr)
        return 1

    print(f"OK: {total}/{total} sources decrypt under current SECRET_KEY")
    return 0


def main() -> None:
    sys.exit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
