/**
 * Runtime reverse-proxy for /api/* → BACKEND_URL.
 *
 * Next.js next.config.mjs `rewrites` evaluates at BUILD time, so
 * `process.env.BACKEND_URL` baked the fallback value. This Route Handler
 * reads the env at REQUEST time and forwards. Works in Docker (BACKEND_URL
 * = http://api:8000) and local dev (fallback to http://127.0.0.1:8000).
 *
 * Phase 8 / INFRA-04 mitigation for pitfall H-1:
 *   When process.env.AUTH_ENABLED === "true", the proxy strips the spoofable
 *   X-Dashboard-Role request header before forwarding upstream. This prevents
 *   a browser-origin attacker from setting the header directly and reaching
 *   the backend with an elevated dashboard role. Phase 9 auth swaps the
 *   header-based dashboard-role derivation for a JWT-claim-based one; the
 *   strip is a defensive layer regardless.
 */
export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const ALLOWED_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"] as const;

async function proxy(
  req: Request,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params;
  const backend = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";
  const upstreamUrl = new URL(req.url);
  const target = `${backend}/api/${path.join("/")}${upstreamUrl.search}`;

  const headers = new Headers(req.headers);
  // Drop browser-only hop headers and host (server resolves it)
  headers.delete("host");
  headers.delete("connection");

  // Phase 9 / AUTH-02 + AUTH-04: inject Authorization: Bearer from the Auth.js
  // v5 session when AUTH_ENABLED=true. This is the single source of truth for
  // auth on upstream calls — the client CANNOT set Authorization because the
  // incoming header is overwritten server-side here. X-Dashboard-Role is also
  // stripped (Phase 8 INFRA-04 behaviour preserved).
  if (process.env.AUTH_ENABLED === "true") {
    headers.delete("x-dashboard-role");
    // Defensive: strip any client-provided Authorization before re-adding from session.
    headers.delete("authorization");

    const { auth } = await import("@/auth");
    const session = await auth();
    const accessToken = (session as any)?.accessToken;
    if (typeof accessToken === "string" && accessToken.length > 0) {
      headers.set("Authorization", `Bearer ${accessToken}`);
    }
  }

  const method = req.method.toUpperCase();
  const body =
    method === "GET" || method === "HEAD" ? undefined : await req.arrayBuffer();

  try {
    const upstream = await fetch(target, {
      method,
      headers,
      body,
      redirect: "manual",
    });
    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: upstream.headers,
    });
  } catch (err) {
    return new Response(
      JSON.stringify({
        error: "upstream_unreachable",
        detail: err instanceof Error ? err.message : String(err),
        target,
      }),
      { status: 502, headers: { "content-type": "application/json" } },
    );
  }
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
export const HEAD = proxy;
export { ALLOWED_METHODS };
