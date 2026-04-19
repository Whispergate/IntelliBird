# Authentication Setup (Phase 9)

Bring a Phase-8 IntelliBird deployment from unauthenticated-loopback-only to full JWT +
optional Authentik SSO auth.

This runbook assumes Phase 8 is complete: `AUTH_ENABLED` flag is wired, `SECRET_KEY` rotation
has been exercised at least once (see [secret-rotation.md](secret-rotation.md)), and the
OpenAPI codegen + NoAuthBanner three-state wiring are live.

## When you need this runbook

- First-time Phase 9 bring-up — you have no users and `AUTH_ENABLED=false`.
- Adding Authentik SSO to an already-authenticated deployment.
- Rotating `JWT_SIGNING_KEY` (see "Rotating JWT_SIGNING_KEY" below).

## Prerequisites

- Phase 8 shipped — confirm `curl -s http://127.0.0.1:8000/api/system/status | jq .auth_enabled` returns `false` or `true`.
- `docker compose` v2 installed (`docker compose version` reports v2+).
- `openssl` on the operator shell (for key generation).
- Edit access to `ops/.env`.

## 1. Generate JWT_SIGNING_KEY

`JWT_SIGNING_KEY` is separate from `SECRET_KEY` — rotating credentials-rekey `SECRET_KEY` does
not invalidate live sessions, and rotating `JWT_SIGNING_KEY` does not touch credentials.

```bash
echo "JWT_SIGNING_KEY=$(openssl rand -hex 32)" >> ops/.env
```

Confirm the line appears in `ops/.env`:

```bash
grep ^JWT_SIGNING_KEY= ops/.env
```

Any attempt to start the api service without a valid `JWT_SIGNING_KEY` (length < 32 or
placeholder string) will `sys.exit(1)` with a `FATAL` log. This is deliberate — there is
no auth without a signing key.

## 2. Set SETUP_TOKEN for the first admin

The `/api/admin/setup` endpoint creates the first Admin user. It is gated by the same
`X-Setup-Token` header pattern as the Phase 8 rekey endpoint.

```bash
echo "SETUP_TOKEN=$(openssl rand -hex 16)" >> ops/.env
```

## 3. Enable auth and restart

```bash
# Flip the flag on both api and web services
sed -i 's/^AUTH_ENABLED=.*/AUTH_ENABLED=true/' ops/.env  # or edit manually

cd ops
docker compose up -d --force-recreate api web
```

Confirm the api logs show the startup banner:

```bash
docker compose logs api | grep -E "startup_auth_status|startup_bind_loopback"
```

Expected:
- `startup_bind_loopback` line (inherited Phase 1 invariant).
- `startup_auth_status` line with `auth_enabled=True`, `jwt_signing_key_len=64`,
  `sso_configured=False` (unless Authentik is configured — Section 7).

## 4. Create the first admin

### Option A — /setup UI page (recommended)

```bash
# Visit http://127.0.0.1:3000/setup in your browser
```

Fill the form:
- Setup token: paste the value of `SETUP_TOKEN` from `ops/.env`
- Username: `admin` (or any string)
- Password: at least 12 characters
- Confirm password: must match

The page submits to `POST /api/admin/setup` with the `X-Setup-Token` header injected from
the setup token field. If the token is wrong or missing, the page renders the error card:
"Setup token is invalid or has expired. Check SETUP_TOKEN in the api environment."

### Option B — curl from the api container (fallback)

```bash
SETUP=$(grep ^SETUP_TOKEN= ops/.env | cut -d= -f2)

docker compose exec api curl -sX POST http://localhost:8000/api/admin/setup \
  -H "X-Setup-Token: ${SETUP}" \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"a-strong-password-12+"}'
```

Expected response (HTTP 201):

```json
{"id":"...","username":"admin","role":"Admin","dashboard_roles":["red","blue"],"must_change_password":false}
```

If you see `{"detail":"setup_already_complete"}`, skip to Section 6 — a user already exists.

## 5. Remove SETUP_TOKEN and restart

**MANDATORY** — leaving `SETUP_TOKEN` set after first-admin creation is a security risk.

```bash
grep -v "^SETUP_TOKEN=" ops/.env > ops/.env.new && mv ops/.env.new ops/.env
cd ops
docker compose restart api
```

Visit `/setup` again in the browser — page should return `404` (or render the "already
complete" card if the UI still reaches it via the status endpoint).

## 6. Verify login and admin API

```bash
# Log in and capture the access token
ACCESS=$(curl -sX POST http://127.0.0.1:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"a-strong-password-12+"}' | jq -r .access_token)

# Confirm /me returns the admin user
curl -s -H "Authorization: Bearer ${ACCESS}" http://127.0.0.1:8000/api/auth/me | jq .

# Confirm /admin/users is admin-gated
curl -s -H "Authorization: Bearer ${ACCESS}" http://127.0.0.1:8000/api/admin/users | jq 'length'
```

Expected:
- `/me` returns `{ id, username, role:"Admin", dashboard_roles:["red","blue"], must_change_password:false }`.
- `/admin/users` returns an array of length 1 (the admin just created).

## 7. (Optional) Bring up Authentik SSO

Skip this section if you only need local accounts.

### 7.1 Generate Authentik secrets

```bash
cat >> ops/.env <<EOF
AUTHENTIK_PG_DB=authentik
AUTHENTIK_PG_USER=authentik
AUTHENTIK_PG_PASS=$(openssl rand -base64 24)
AUTHENTIK_SECRET_KEY=$(openssl rand -base64 60)
EOF
```

### 7.2 Start the SSO profile

```bash
cd ops
docker compose --profile sso up -d authentik-db authentik-server authentik-worker
docker compose logs -f authentik-server   # wait for "System migrations finished"
```

### 7.3 First-boot admin

Authentik's initial admin is configured via a web flow on first boot:

```bash
open http://127.0.0.1:9000/if/flow/initial-setup/
```

Set the Authentik admin email + password. This is the Authentik-internal admin, separate
from IntelliBird's admin.

If `open` is not available on your host, navigate manually to the URL in a browser.
Alternatively, find the recovery link in Authentik logs:

```bash
docker compose --profile sso logs authentik-server | grep recovery
```

### 7.4 Create the OIDC application + provider

In the Authentik UI (`http://127.0.0.1:9000`):

1. **Applications -> Create**. Name: `IntelliBird`. Slug: `intellibird`. Click next.
2. **Providers -> Create -> OAuth2/OpenID Provider**:
   - Name: `IntelliBird`
   - Authentication flow: `default-authentication-flow`
   - Authorization flow: `default-provider-authorization-explicit-consent`
   - Client type: `Confidential`
   - Client ID + Secret: autogenerated — **copy both values**.
   - Redirect URIs: `http://localhost:3000/api/auth/oidc/callback`
   - Signing key: `authentik Self-signed Certificate`
   - Scopes: `openid`, `profile`, `email`, `groups`
3. Back on the application, set **Provider** to the OIDC provider you just made.
4. **Customisation -> Property Mappings**: confirm `authentik default OAuth Mapping: OpenID 'groups'` is enabled.
5. **Directory -> Groups**: create `intellibird-admins` and `intellibird-analysts`.
6. Assign users to the appropriate group. Unmapped users land as Viewer by default.

### 7.5 Wire the IntelliBird api to Authentik

Edit `ops/.env`:

```bash
cat >> ops/.env <<EOF
SSO_ISSUER_URL=http://authentik:9000/application/o/intellibird/
SSO_CLIENT_ID=<from step 7.4.2>
SSO_CLIENT_SECRET=<from step 7.4.2>
SSO_GROUPS_CLAIM=groups
SSO_ADMIN_GROUPS=intellibird-admins
SSO_ANALYST_GROUPS=intellibird-analysts
SSO_VIEWER_GROUPS=
EOF

cd ops
docker compose restart api
```

Confirm the api sees SSO:

```bash
docker compose logs api | grep startup_auth_status
# Expected: sso_configured=True
```

### 7.6 Verify the SSO flow

Open `http://127.0.0.1:3000/login` in an incognito browser. The "Sign in with Authentik"
button should appear below the "or" separator.

Click it -> redirected to Authentik -> log in as an `intellibird-admins` user -> redirected
back to `/red` or `/blue`. On success the `users` table has a new row with
`oidc_sub=<authentik sub>` and `role=Admin`.

## 8. Role-group mapping reference

| IntelliBird role | JWT claim `role` | Authentik group (env-driven) | Dashboard access |
|---|---|---|---|
| Admin | `"Admin"` | `SSO_ADMIN_GROUPS` | `red` + `blue` (enforced) |
| Analyst | `"Analyst"` | `SSO_ANALYST_GROUPS` | per-user (operator sets) |
| Viewer | `"Viewer"` | (fallback — no match) | per-user (operator sets) |

To promote an SSO user from Viewer to Analyst or Admin:

1. Add the user to the appropriate Authentik group.
2. User signs out and back in — role updates on the next callback.

To force an existing SSO user to re-authenticate (e.g. after role change):

```bash
docker compose exec db psql -U ${POSTGRES_USER} ${POSTGRES_DB} \
  -c "UPDATE users SET token_version = token_version + 1 WHERE oidc_sub = '<sub>';"
```

## 9. Rotating JWT_SIGNING_KEY

Rotating `JWT_SIGNING_KEY` invalidates every outstanding session immediately. Users are
bounced to `/login`.

```bash
NEW=$(openssl rand -hex 32)
sed -i "s/^JWT_SIGNING_KEY=.*/JWT_SIGNING_KEY=${NEW}/" ops/.env

cd ops
docker compose restart api
```

Unlike `SECRET_KEY`, there is no rekey endpoint for `JWT_SIGNING_KEY` — old tokens simply
fail signature verify and users must log in again. The Redis blocklist entries under the old
key expire naturally (15-min access TTL, 7-day refresh TTL).

## 10. Rollback (emergency auth disable)

If Phase 9 breaks and you need to revert to pre-auth behaviour for triage:

```bash
sed -i 's/^AUTH_ENABLED=.*/AUTH_ENABLED=false/' ops/.env
cd ops
docker compose restart api web
```

Effect:
- `AuthMiddleware` becomes a pass-through; every route responds as pre-Phase-9.
- Next.js proxy no longer strips `x-dashboard-role` nor injects `Authorization: Bearer`.
- `NoAuthBanner` renders the amber/red "NO AUTHENTICATION CONFIGURED" banner.

This is a triage step only. Re-enable auth (`AUTH_ENABLED=true` + restart) before the
deployment is used for intel work.

## 11. Uninstalling Authentik SSO

```bash
cd ops
docker compose --profile sso stop authentik-server authentik-worker
docker compose --profile sso rm -f authentik-server authentik-worker

# Unset SSO_* env vars in ops/.env
grep -vE "^SSO_|^AUTHENTIK_" ops/.env > ops/.env.new && mv ops/.env.new ops/.env

docker compose restart api
```

The `/login` page's "Sign in with Authentik" button disappears on the next page load.
Local-account users are unaffected.

## 12. What breaks if you skip this runbook

- Start `api` with `AUTH_ENABLED=true` and unset `JWT_SIGNING_KEY` -> process exits 1 at
  startup. Logs show `FATAL: JWT_SIGNING_KEY is a placeholder value.` Fix: generate the key
  per Section 1.
- Start with `AUTH_ENABLED=true` and no users in the DB -> every `/api/*` route returns 401
  `invalid_token`. Fix: generate `SETUP_TOKEN`, visit `/setup`, create the first admin.
- Leave `SETUP_TOKEN` set after first-admin creation -> `/api/admin/setup` remains callable.
  An attacker in possession of `SETUP_TOKEN` cannot create a new admin (the endpoint returns
  409 once any user exists), but the value is still a leak. Fix: remove per Section 5.
- `AUTH_ENABLED=true` with `SSO_ISSUER_URL` set but no `SSO_ADMIN_GROUPS` or
  `SSO_ANALYST_GROUPS` -> all SSO users land as Viewer regardless of Authentik group membership.
  Fix: set `SSO_ADMIN_GROUPS=intellibird-admins` (and `SSO_ANALYST_GROUPS` if needed) and
  restart api.
- Redis unreachable at runtime -> AuthMiddleware returns 503 `auth_infra_down` (fail-closed).
  This is intentional — a running deployment without functional token revocation is not safe.
  Fix: confirm `docker compose ps redis` shows healthy; check `REDIS_URL` in `ops/.env`.

---

Last updated: 2026-04-18 (Phase 9 shipped).
Related: [secret-rotation.md](secret-rotation.md), [../../ops/.env.example](../../ops/.env.example).
