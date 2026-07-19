"""app.security - IntelliBird security primitives package.

Modules:
    jwt       - JWT encode/decode helpers (AUTH-03)
    passwords - Argon2 hash/verify/dummy (AUTH-01/04)
    lockout   - Redis failed-login counter (AUTH-04)
    oidc      - Authentik OIDC client + groups->role mapping (AUTH-01)
"""
