# Authentik Disaster Recovery Runbook

Operator procedure for backing up, restoring, and verifying the self-hosted Authentik IdP that fronts IntelliBird's OIDC SSO. Covers total loss of the Authentik stack (authentik-db + media volume + secrets) and the minimum steps required to restore login for Admin/Analyst/Viewer roles.

Related: [auth-setup.md](auth-setup.md) (initial Authentik provisioning), [secret-rotation.md](secret-rotation.md) (IntelliBird SECRET_KEY drill).

> **Pinned image:** `ghcr.io/goauthentik/server:2025.12.1` - do not float this tag during recovery. Restore must run against the same image major/minor as the backup source to avoid migration drift. The tag is pinned in `ops/docker-compose.yml` on both `authentik-server` and `authentik-worker`.

> **Scope:** IdP only. IntelliBird application DB (`db` service) recovery is a separate runbook. In a full disaster, recover Authentik first so SSO works, then recover IntelliBird application state.

> **Compose profile:** The Authentik stack is opt-in via the `sso` profile. Every `docker compose` command below must include `--profile sso`.

---

## 1. Backup

Two artefacts MUST be captured together. Backing up only the DB will produce a broken Authentik on restore (missing branding, uploaded flows, certs).

### 1.1 Postgres dump (authentik-db)

```bash
# From the host running ops/docker-compose.yml
mkdir -p backups

docker compose -f ops/docker-compose.yml --profile sso exec -T authentik-db \
  pg_dump -U "${AUTHENTIK_PG_USER:-authentik}" -d "${AUTHENTIK_PG_DB:-authentik}" -Fc \
  > "backups/authentik-db-$(date -u +%Y%m%dT%H%M%SZ).dump"
```

- `-Fc` (custom format) enables selective restore via `pg_restore`.
- Run at least weekly; retain >= 14 days. Store off-host (S3, Restic, encrypted external disk).
- Size sanity: expect a few hundred KB to a few MB for a small team. A zero-byte file means the exec failed silently - check `docker compose --profile sso ps authentik-db`.

### 1.2 Media volume tarball (`/data/media`)

Authentik 2025.10+ relocated user-uploaded assets (logos, flow backgrounds, uploaded certificates) from `/media` to `/data/media`. The backup MUST target the new path.

```bash
docker compose -f ops/docker-compose.yml --profile sso exec -T authentik-server \
  tar -czf - -C /data media \
  > "backups/authentik-media-$(date -u +%Y%m%dT%H%M%SZ).tgz"
```

Verify non-empty:

```bash
tar -tzf backups/authentik-media-*.tgz | head
```

> **Pitfall 4 (RESEARCH.md):** Backing up `/media` instead of `/data/media` on 2025.10+ produces a tarball with no useful content - Authentik boots after restore but uploaded certs/icons 404.

### 1.3 Sealed secrets

The following are NOT in either artefact above and must be captured separately via your secrets vault (1Password, sops, Vault, etc.):

- `AUTHENTIK_SECRET_KEY`
- `AUTHENTIK_PG_PASS`
- `SSO_CLIENT_ID` and `SSO_CLIENT_SECRET` (IntelliBird's OIDC client credentials - in `ops/.env`)

A "complete backup" means DB dump + media tarball + verified secrets-vault snapshot from the same window.

---

## 2. Restore

Total-loss recovery assumes a fresh host with Docker + the IntelliBird repo checked out, and access to the three artefact groups above.

### 2.1 Rebuild sequence

```bash
# 1. Restore secrets to ops/.env (AUTHENTIK_*, SSO_*) from your vault snapshot.
#    See docs/ops/auth-setup.md §7.1 for the expected variables.

# 2. Start only the authentik-db container (empty volume).
docker compose -f ops/docker-compose.yml --profile sso up -d authentik-db

# Wait for init (authentik-db creates DB+role on first boot).
until docker compose -f ops/docker-compose.yml --profile sso exec -T authentik-db \
  pg_isready -U "${AUTHENTIK_PG_USER:-authentik}"; do sleep 2; done

# 3. Drop+recreate the authentik DB, then pg_restore into it.
docker compose -f ops/docker-compose.yml --profile sso exec -T authentik-db \
  psql -U "${AUTHENTIK_PG_USER:-authentik}" -d postgres \
  -c "DROP DATABASE IF EXISTS authentik; CREATE DATABASE authentik OWNER \"${AUTHENTIK_PG_USER:-authentik}\";"

docker compose -f ops/docker-compose.yml --profile sso exec -T authentik-db \
  pg_restore -U "${AUTHENTIK_PG_USER:-authentik}" -d authentik --clean --if-exists \
  < backups/authentik-db-<TIMESTAMP>.dump

# 4. Bring up authentik-server (creates the named volume if absent), then
#    extract the media tarball into /data inside the container.
docker compose -f ops/docker-compose.yml --profile sso up -d authentik-server

docker compose -f ops/docker-compose.yml --profile sso exec -T authentik-server \
  tar -xzf - -C /data \
  < backups/authentik-media-<TIMESTAMP>.tgz

# 5. Full SSO stack up, pinned tag verified.
docker compose -f ops/docker-compose.yml --profile sso up -d
docker compose -f ops/docker-compose.yml --profile sso images | grep goauthentik/server
# MUST show: ghcr.io/goauthentik/server   2025.12.1
```

### 2.2 Post-restore health check

```bash
# Authentik UI reachable on loopback (compose publishes 127.0.0.1:9000 only).
curl -sf -o /dev/null -w "%{http_code}\n" http://127.0.0.1:9000/if/admin/
# Expect: 200 or 302 (redirect to login).

# Worker healthy.
docker compose -f ops/docker-compose.yml --profile sso logs --tail=50 authentik-worker \
  | grep -iE "ready|bootstrap|startup"
```

---

## 3. Re-issue OIDC Client (intellibird provider)

If the IntelliBird OIDC client secret was compromised, or if the restore predates the current `SSO_CLIENT_SECRET` in `ops/.env`, rotate via the Authentik Admin UI.

> **CLI path not verified.** The `ak` CLI exposes provider management but the 2025.12 schema for OIDC client-secret rotation has not been confirmed against this project. Use the UI until verified.

### 3.1 Admin UI navigation

1. Log in to `http://127.0.0.1:9000/if/admin/` as the restored superuser (akadmin or your named admin).
2. **Applications -> Providers ->** select the `IntelliBird` OIDC provider (created per `auth-setup.md` §7.4).
3. **Edit -> Protocol Settings:**
   - Client type: `Confidential`
   - Client ID: confirm it matches `SSO_CLIENT_ID` in `ops/.env`
   - Client Secret: **regenerate** -> copy the new value
   - Redirect URIs: `http://localhost:3000/api/auth/oidc/callback` (or your deployment's host equivalent)
   - Signing Key: `authentik Self-signed Certificate` (per `auth-setup.md`)
   - Scopes: `openid`, `profile`, `email`, `groups`
4. **Save.** Navigate to **Applications -> Applications -> IntelliBird** and confirm the provider binding is intact.
5. Update IntelliBird env and restart the api:
   ```bash
   # ops/.env
   # SSO_CLIENT_SECRET=<new value from step 3>
   docker compose -f ops/docker-compose.yml restart api
   ```

### 3.2 Group -> role mapping sanity check

**Admin UI -> Directory -> Groups** - verify `intellibird-admins` and `intellibird-analysts` exist and contain your test users. Unmapped users land as Viewer by default (`auth-setup.md` §8).

---

## 4. Verify SSO

From the IntelliBird host (or any machine that can reach the backend):

```bash
curl -sS -o /dev/null -w "%{http_code} %{redirect_url}\n" \
  http://127.0.0.1:8000/api/auth/oidc/login
```

**Expected:** `302 http://authentik:9000/application/o/authorize/?client_id=...&redirect_uri=...&response_type=code&scope=openid+profile+email+groups&state=...`

(The `Location` host is whatever `SSO_ISSUER_URL` resolves to - `authentik:9000` inside the compose network, or your public Authentik hostname.)

Failure modes:

| Response                              | Likely cause                                                          |
| ------------------------------------- | --------------------------------------------------------------------- |
| `500` + backend log `oidc_*` error    | `SSO_CLIENT_ID`/`SSO_CLIENT_SECRET` not updated post-restore; restart api |
| `302` to `/login?error=oidc_disabled` | `SSO_ISSUER_URL` unset or `AUTH_ENABLED` not true                     |
| `302` but Authentik shows 404         | Provider not bound to application, or Redirect URI mismatch (§3.1 #3) |
| `401 invalid_token` on callback       | Client secret in `ops/.env` does not match Authentik post-rotation   |

Full round-trip check (browser):

1. Open `http://127.0.0.1:3000/login` in an incognito window.
2. Click **Sign in with Authentik** -> redirected to Authentik login.
3. Authenticate as a user in `intellibird-analysts`.
4. Redirected back to `/red` or `/blue`.
5. `curl -s -H "Authorization: Bearer <session-token>" http://127.0.0.1:8000/api/auth/me | jq` returns `{"role":"Analyst",...}`.

---

## 5. Rehearsal

DR is only valid if exercised. Rehearse at least every 90 days in a staging stack that mirrors production image tags.

### 5.1 Rehearsal procedure

1. Take fresh backups per §1 from production (or a production-like staging instance).
2. Stand up an isolated Docker host (not prod).
3. Walk §2 + §3 end-to-end using ONLY the backup artefacts and this runbook - no shortcuts, no copy-paste from a live prod shell.
4. Run §4 verification (curl + browser round-trip) against the rehearsed stack.
5. Time each phase; record deviations from the runbook as issues against this document.

### 5.2 Pass criteria

- Stack healthy within 30 minutes of starting §2.
- §4 curl returns 302 to Authentik on the rehearsed stack.
- Browser round-trip login with a test user in `intellibird-analysts` lands on `/red` or `/blue` with role badge correct.
- `/api/auth/me` returns the correct role for the test user.
- No manual steps were required that are not already documented here. Any gap = doc bug -> file a follow-up issue and PR before signing off.

### 5.3 Last Rehearsal

> Operator: fill all fields after each rehearsal. Keep prior entries above newer ones for an audit trail.

```
Date (UTC):          ____-__-__T__:__:__Z
Operator:            __________________________
Authentik image tag: ghcr.io/goauthentik/server:__________  (expected 2025.12.1)
Backup artefacts:
  - DB dump path:    __________________________  (size: _____ bytes)
  - Media tarball:   __________________________  (size: _____ bytes)
  - Dump timestamp:  ____-__-__T__:__:__Z
Phase timings (min):
  - Restore (§2):    ____
  - OIDC re-issue:   ____
  - Verify (§4):     ____
  - Total:           ____
OIDC client rotated: [ ] yes  [ ] no    (new secret written to ops/.env: [ ] yes)
Verify §4 curl:      HTTP ____   redirect Location: __________________________
Browser round-trip:  [ ] pass  [ ] fail
Role observed:       __________   (expected: Analyst for intellibird-analysts test user)
Deviations / doc gaps found:
  - ________________________________________________
  - ________________________________________________
Follow-up issues filed:
  - ________________________________________________
Result:              [ ] PASS  [ ] FAIL
Sign-off:            __________________________
```

---

## References

- [auth-setup.md](auth-setup.md) - initial Authentik provisioning (env, groups, provider binding)
- [secret-rotation.md](secret-rotation.md) - IntelliBird SECRET_KEY drill (separate from this runbook)
- `ops/docker-compose.yml` - pinned service definitions (`authentik-server`, `authentik-worker`, `authentik-db`)
- [Authentik backup/restore docs](https://docs.goauthentik.io/sys-mgmt/ops/backup-restore/)
- [Authentik 2025.12 release notes](https://docs.goauthentik.io/releases/2025.12/) - `/data/media` path, `/files` URL prefix
