# SECRET_KEY Rotation Runbook

Operator procedure for rotating `SECRET_KEY` without orphaning encrypted source
credentials. See `.planning/phases/08-pre-auth-infra-hardening/` for the design.

## When to rotate

- Any suspected key compromise.
- Scheduled rotation (recommended annually for production deployments).
- After any developer/operator leaves a trusted role.

You can detect that rotation was skipped by checking the UI banner
(**CREDENTIAL DECRYPTION FAILURE** - red `#b00020`) or by curl:

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

Both `REKEY_FROM_SECRET` and `SETUP_TOKEN` are one-shot - remove them so the
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

- `startup_decrypt_check_ok` on second restart - canary round-trips cleanly
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

1. The transaction rolled back - stored blobs are UNCHANGED under the OLD key.
2. Investigate the failing rows - they were encrypted under a key that is
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

## interaction

The rekey endpoint is deliberately exempt from `AuthMiddleware` (see
`backend/app/middleware/auth.py` - `EXEMPT_PATHS`). It remains callable when
`AUTH_ENABLED=true`. The `X-Setup-Token` gate is the only auth it enforces -
keep `SETUP_TOKEN` unset in normal operation so the endpoint returns 403 for
all callers.

## See also

- `ops/.env.example` - env var reference
- `backend/app/routers/admin/rekey.py` - endpoint implementation
- `backend/app/main.py` - lifespan canary check
- `backend/app/scripts/verify_sources_decrypt.py` - full-table read-back verifier (PROD-04)
- `backend/tests/integration/test_rekey_router.py` - regression coverage for the endpoint
- `.planning/research/PITFALLS.md` §C-1 - threat-model rationale

---

# PROD-04 Rehearsed Drill (operator reference)

The numbered procedure above is the canonical operator flow. The sections
below reorganise it into a rehearsed drill that records evidence per run
and adds explicit pre-flight **and** full-table read-back steps. Use this
form when rotating production or when rehearsing. Commands use
`$INTELLIBIRD_URL` (default `http://127.0.0.1:8000` for local compose);
replace with the deployment hostname for staging/prod.

## Pre-Flight

Capture recoverable state BEFORE any mutation. These two artefacts are
the rollback contract.

```bash
# 1. Backup the env file (keep pre-rotation copy on disk, NOT in git).
cp ops/.env ops/.env.bak-$(date +%Y%m%d)

# 2. Dump the DB. credentials_enc is in `sources`; canary is in `crypto_canary`.
mkdir -p backups
docker compose -f ops/docker-compose.yml exec -T db \
  pg_dump -U intellibird intellibird \
  > backups/pre-rotation-$(date +%Y%m%d).sql

# 3. Record current source/credential counts as a sanity baseline.
docker compose -f ops/docker-compose.yml exec -T db \
  psql -U intellibird -d intellibird -tAc \
  "SELECT count(*) FILTER (WHERE credentials_enc IS NOT NULL),
          count(*) FROM sources;"
# expected output: "<N_with_creds>|<N_total>"

# 4. Confirm pre-rotation canary is healthy.
curl -sf $INTELLIBIRD_URL/api/system/status | jq '.decrypt_check'
# expected: "ok"
```

If any of the above fails, STOP - do not rotate. Fix the failure or the
rehearsal evidence will be unusable for rollback.

## Rotate

```bash
# Capture the current (about-to-become-OLD) key and generate the new one.
OLD_KEY=$(grep ^SECRET_KEY= ops/.env | cut -d= -f2-)
NEW_KEY=$(openssl rand -hex 32)
SETUP=$(openssl rand -hex 16)

# Edit ops/.env: SECRET_KEY=<NEW_KEY>, REKEY_FROM_SECRET=<OLD_KEY>, SETUP_TOKEN=<SETUP>
sed -i.tmp -E -e "s|^SECRET_KEY=.*|SECRET_KEY=${NEW_KEY}|" ops/.env
printf "REKEY_FROM_SECRET=%s\nSETUP_TOKEN=%s\n" "$OLD_KEY" "$SETUP" >> ops/.env
rm -f ops/.env.tmp

docker compose -f ops/docker-compose.yml restart api
timeout 60 bash -c 'until curl -sf $INTELLIBIRD_URL/healthz; do sleep 2; done'

# Run the rekey endpoint.
curl -fsS -X POST $INTELLIBIRD_URL/api/admin/rekey-credentials \
  -H "X-Setup-Token: ${SETUP}" | tee /tmp/rekey-response.json
# expected: {"rekeyed": <N>, "skipped": <M>}
```

If the endpoint returns 500 with `{"error": "decrypt_failed", "source_ids": [...]}`,
the transaction rolled back - stored blobs are UNCHANGED. See the
`Rollback` section below for the decision path.

## Read-Back Verify

Belt-and-braces check: the lifespan canary only proves one row round-trips.
This script iterates every `sources.credentials_enc` under the CURRENT key.

```bash
docker compose -f ops/docker-compose.yml exec -T api \
  python -m app.scripts.verify_sources_decrypt
# expected stdout: "OK: N/N sources decrypt under current SECRET_KEY"
# exit code 0 on success; 1 with stderr list of failing UUIDs on failure

# Cross-check the public status endpoint too:
curl -s $INTELLIBIRD_URL/api/system/status | jq '{decrypt_check, warning}'
# expected: { "decrypt_check": "ok", "warning": null }
```

If the script exits non-zero, STOP and proceed to `Rollback`. Do not
remove `REKEY_FROM_SECRET` - you may need to retry.

## Clean Up

Only after read-back passes. Removes the one-shot env vars so the rekey
endpoint returns 403 to any future caller.

```bash
grep -v -E "^(REKEY_FROM_SECRET|SETUP_TOKEN)=" ops/.env > ops/.env.new
mv ops/.env.new ops/.env
docker compose -f ops/docker-compose.yml restart api

# Re-verify after the transient envs are gone.
curl -s $INTELLIBIRD_URL/api/system/status | jq '.decrypt_check'
# expected: "ok"
```

## Rollback

Two rollback contracts, depending on how far the drill progressed.

**A. Rekey endpoint returned non-2xx (no blobs mutated):**

```bash
# Restore pre-rotation env - SECRET_KEY returns to OLD_KEY.
mv ops/.env.bak-<YYYYMMDD> ops/.env
docker compose -f ops/docker-compose.yml restart api
curl -s $INTELLIBIRD_URL/api/system/status | jq '.decrypt_check'  # "ok"
```

No DB restore needed - the rekey router is transaction-atomic.

**B. Rekey succeeded but read-back or downstream checks fail (blobs now
under new key, but something is wrong):**

```bash
# Stop api so it cannot write during restore.
docker compose -f ops/docker-compose.yml stop api

# Restore DB from pre-flight dump.
docker compose -f ops/docker-compose.yml exec -T db \
  psql -U intellibird -d intellibird < backups/pre-rotation-<YYYYMMDD>.sql

# Restore pre-rotation env.
mv ops/.env.bak-<YYYYMMDD> ops/.env

# Restart.
docker compose -f ops/docker-compose.yml start api
curl -s $INTELLIBIRD_URL/api/system/status | jq '.decrypt_check'  # "ok"
```

Any source rows created BETWEEN the pre-flight dump and the rollback will
be lost. Capture them from application logs / UI before restoring if they
matter.

## Last Rehearsal

_Fill during rehearsal. Append a new block per run; do not overwrite
history. The most recent entry is the authoritative "last rehearsed on"
record for PROD-04 evidence._

```markdown
- Date: YYYY-MM-DD
- Operator: <username>
- Environment: <local | staging | prod>
- Sources rotated: <N>
- Pre-flight baseline: <N_with_creds>/<N_total>
- Rekey endpoint: <2xx | 4xx | 5xx - paste /tmp/rekey-response.json>
- Read-back (verify_sources_decrypt): <OK N/N | FAIL - paste stderr>
- system/status decrypt_check: <ok | failed>
- Rollback exercised: <yes: path A | yes: path B | no>
- Cleanup completed (REKEY_FROM_SECRET + SETUP_TOKEN removed): <yes | no>
- Result: <PASS | FAIL>
- Notes / gotchas:
```

### Evidence (most recent first)

_No rehearsal logged yet. Operator: append the first entry here once Task
6.2 of plan 13-06 is executed._

