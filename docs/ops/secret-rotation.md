# SECRET_KEY Rotation Runbook

Operator procedure for rotating `SECRET_KEY` without orphaning encrypted source
credentials. See `.planning/phases/08-pre-auth-infra-hardening/` for the design.

## When to rotate

- Any suspected key compromise.
- Scheduled rotation (recommended annually for production deployments).
- After any developer/operator leaves a trusted role.

You can detect that rotation was skipped by checking the UI banner
(**CREDENTIAL DECRYPTION FAILURE** — red `#b00020`) or by curl:

```bash
curl -s http://127.0.0.1:8000/api/system/status | jq .decrypt_check
# "ok"      → canary decrypts cleanly under current SECRET_KEY
# "failed"  → rotation happened without rekey; encrypted creds are unreadable
# "unknown" → canary row missing (migration 007 not applied)
```

## Full procedure (5 steps)

### 1. Generate the new key

```bash
NEW_KEY=$(openssl rand -hex 32)
echo "$NEW_KEY"  # record somewhere safe; you'll paste it into .env
```

### 2. Generate a one-time setup token

```bash
SETUP=$(openssl rand -hex 16)
echo "$SETUP"  # record; you'll paste into .env AND the curl header
```

### 3. Edit `ops/.env`

Set three variables. `REKEY_FROM_SECRET` = the CURRENT `SECRET_KEY` (i.e., the
key that currently encrypts `sources.credentials_enc`). `SECRET_KEY` = the NEW
key you just generated.

```bash
# BEFORE any edit, capture the OLD key that is currently in the file:
OLD_KEY=$(grep ^SECRET_KEY= ops/.env | cut -d= -f2-)

# Overwrite the three relevant lines in-place (keep a backup):
cp ops/.env ops/.env.bak
sed -i.tmp -E \
  -e "s|^SECRET_KEY=.*|SECRET_KEY=${NEW_KEY}|" \
  ops/.env
printf "REKEY_FROM_SECRET=%s\nSETUP_TOKEN=%s\n" "$OLD_KEY" "$SETUP" >> ops/.env
rm -f ops/.env.tmp
```

Confirm:

```bash
grep -E "^(SECRET_KEY|REKEY_FROM_SECRET|SETUP_TOKEN)=" ops/.env
```

### 4. Restart api + run rekey

```bash
docker compose -f ops/docker-compose.yml restart api

# Wait for api health (lifespan will log startup_decrypt_check_failed because
# SECRET_KEY has changed and the canary can no longer decrypt):
timeout 60 bash -c 'until curl -sf http://127.0.0.1:8000/healthz; do sleep 2; done'

curl -sX POST http://127.0.0.1:8000/api/admin/rekey-credentials \
  -H "X-Setup-Token: ${SETUP}" | jq
```

Expected success output:

```json
{ "rekeyed": 3, "skipped": 1 }
```

`skipped` includes the canary row on first startup if its `credentials_enc` was
already seeded under the new key by the lifespan hook, plus any sources that
never had credentials_enc.

### 5. Unset the transient env vars and restart

Both `REKEY_FROM_SECRET` and `SETUP_TOKEN` are one-shot — remove them so the
rekey endpoint returns 403 for anyone who later sets `X-Setup-Token`:

```bash
grep -v -E "^(REKEY_FROM_SECRET|SETUP_TOKEN)=" ops/.env > ops/.env.new
mv ops/.env.new ops/.env
docker compose -f ops/docker-compose.yml restart api
```

## Verify success

```bash
curl -s http://127.0.0.1:8000/api/system/status | jq '{decrypt_check, warning}'
```

Expected:

```json
{ "decrypt_check": "ok", "warning": null }
```

Check the backend logs:

```bash
docker compose -f ops/docker-compose.yml logs api | grep -E "startup_(canary_seeded|decrypt_check_ok|decrypt_check_failed)"
```

Expected lines (one of):

- `startup_decrypt_check_ok` on second restart — canary round-trips cleanly
- `startup_canary_seeded` on very first start after migration 007

If you see `startup_decrypt_check_failed`, rekey did NOT run or did not
complete. Return to step 4.

## What happens if you skip the rekey

1. Backend starts, logs `startup_decrypt_check_failed` at CRITICAL level
   (event includes `error_type=InvalidTag`).
2. `GET /api/system/status` returns `decrypt_check: "failed"` and a warning
   pointing to this runbook.
3. The UI renders a red `#b00020` `CREDENTIAL DECRYPTION FAILURE` banner on
   every page.
4. Any attempt to poll sources that had encrypted credentials will fail with
   `cryptography.exceptions.InvalidTag` in the worker logs.
5. Fix: set `REKEY_FROM_SECRET` to the OLD key, `SETUP_TOKEN` to a fresh
   token, and re-run steps 4-5 above.

## Rollback

The rekey endpoint is transaction-atomic. If it returns 500 with
`{"error": "decrypt_failed", "source_ids": ["<uuid>", ...]}`:

1. The transaction rolled back — stored blobs are UNCHANGED under the OLD key.
2. Investigate the failing rows — they were encrypted under a key that is
   neither your current `SECRET_KEY` nor the `REKEY_FROM_SECRET` you supplied.
   Common causes: the row was manually inserted with a bad blob, or a past
   rekey was interrupted.
3. Either fix the bad rows (edit via `sources` admin UI or direct UPDATE) or
   adjust `REKEY_FROM_SECRET` to the key those specific rows were encrypted
   under, then retry step 4.

To fully revert the rotation and go back to the old key:

```bash
# Restore the pre-rotation .env
mv ops/.env.bak ops/.env
docker compose -f ops/docker-compose.yml restart api
# decrypt_check returns to "ok" because SECRET_KEY is back to the original
```

This only works if you did NOT complete step 4 successfully. Once rekey has
run, stored blobs are re-encrypted under the new key and the old key can no
longer decrypt them.

## Phase 9 interaction

The rekey endpoint is deliberately exempt from `AuthMiddleware` (see
`backend/app/middleware/auth.py` — `EXEMPT_PATHS`). It remains callable when
`AUTH_ENABLED=true`. The `X-Setup-Token` gate is the only auth it enforces —
keep `SETUP_TOKEN` unset in normal operation so the endpoint returns 403 for
all callers.

## See also

- `ops/.env.example` — env var reference
- `backend/app/routers/admin/rekey.py` — endpoint implementation
- `backend/app/main.py` — lifespan canary check
- `.planning/research/PITFALLS.md` §C-1 — threat-model rationale
