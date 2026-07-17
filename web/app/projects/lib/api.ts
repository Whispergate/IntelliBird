/**
 * Typed client helpers for /api/projects/* surface.
 *
 * These wrap fetch + JSON handling in the same pattern as web/app/api-client.ts
 * (browser uses relative URLs → Next.js Route Handler proxy; server uses
 * compose-internal API_BASE).
 *
 * Types are sourced from api-client.generated.ts where the backend schema is
 * already regenerated. When the backend is NOT running at plan-execution time
 * (the case for plan 10-08 executed offline), the generated file ships a
 * placeholder stub re-exporting these hand-written types so consumers still
 * typecheck. Regenerate with `pnpm gen:api` once the stack is online to replace
 * the stub with the real OpenAPI-derived shapes.
 *
 * Iter-1 lock — iterate-08 plan specifically:
 *   `exportProject` returns `{ blob, filename }`. The filename comes from the
 *   server-sent `Content-Disposition` header via `parseContentDispositionFilename`.
 *   The backend is the sole source of truth for the filename convention
 *   (`intellibird-project-<slug>-<YYYY-MM-DD>.<stix.json|csv>`). DO NOT add a
 *   client-side slug() helper — drift will poison exports if backend slug rules
 *   change.
 */
import { LEGACY_PROJECT_ID } from "./constants";

// ---------------------------------------------------------------------------
// Base URL resolution — identical pattern to web/app/api-client.ts
// ---------------------------------------------------------------------------

// Server-side fetch must talk directly to the backend container AND inject
// the Auth.js session bearer token itself, because the request never traverses
// the /api/[...path] proxy that does this for browser requests. Without
// bearer injection, every RSC fetch returns 401 `invalid_token`.
const SERVER_API_BASE =
  process.env.API_BASE ??
  process.env.NEXT_PUBLIC_API_BASE ??
  "http://api:8000";

/**
 * Universal fetch helper. Browser: relative URL → /api/[...path] proxy
 * injects bearer. Server: absolute URL to backend + bearer injected here
 * via `auth()` session lookup.
 */
async function _apiFetch(path: string, init?: RequestInit): Promise<Response> {
  if (typeof window !== "undefined") {
    return fetch(path, init);
  }
  const headers = new Headers(init?.headers);
  if (process.env.AUTH_ENABLED === "true") {
    headers.delete("authorization");
    const { auth } = await import("@/auth");
    const session = await auth();
    const accessToken = (session as { accessToken?: string } | null)?.accessToken;
    if (typeof accessToken === "string" && accessToken.length > 0) {
      headers.set("Authorization", `Bearer ${accessToken}`);
    }
  }
  return fetch(`${SERVER_API_BASE}${path}`, { ...init, headers });
}

// ---------------------------------------------------------------------------
// Types — hand-written mirrors of backend/app/schemas/projects.py.
// These are re-exported from api-client.generated.ts once `pnpm gen:api` runs.
// ---------------------------------------------------------------------------

export type EngagementType =
  | "red_team"
  | "tiber"
  | "bbest"
  | "internal"
  | "intel_only";

export type ScopeType =
  | "keyword"
  | "service"
  | "domain"
  | "certificate"
  | "whois"
  | "as_number"
  | "ip_range";

export type ProjectRole = "Lead" | "Contributor" | "Observer";

export interface ProjectResponse {
  id: string;
  name: string;
  engagement_type: EngagementType;
  description: string | null;
  created_by: string;
  archived: boolean;
  active_scans_authorised: boolean;
  scope_acknowledgement_text: string | null;
  active_auth_confirmed_at: string | null;
  active_auth_confirmed_by: string | null;
  created_at: string;
  updated_at: string;
  member_count: number;
  creator_is_current_user: boolean;
  // CERT-03: CertStream worker toggle
  certstream_enabled?: boolean | null;
}

export interface ProjectCreateBody {
  name: string;
  engagement_type: EngagementType;
  description?: string | null;
}

export interface ProjectUpdateBody {
  name?: string | null;
  engagement_type?: EngagementType | null;
  description?: string | null;
  archived?: boolean | null;
  // CERT-03: CertStream worker toggle
  certstream_enabled?: boolean | null;
}

export interface MembershipResponse {
  id: string;
  project_id: string;
  user_sub: string;
  project_role: ProjectRole;
  added_by: string | null;
  created_at: string;
  project_name?: string | null;
}

export interface MembershipCreateBody {
  user_sub: string;
  project_role: ProjectRole;
}

export interface ScopeRowResponse {
  id: string;
  project_id: string;
  scope_type: ScopeType;
  value: string;
  contact: string | null;
  exclude: boolean;
  active_test_scope: boolean;
  intel_scope: boolean;
  created_at: string;
}

export interface ScopeRowCreateBody {
  scope_type: ScopeType;
  value: string;
  contact?: string | null;
  exclude?: boolean;
  active_test_scope?: boolean;
  intel_scope?: boolean;
}

export interface ScopeRowUpdateBody {
  contact?: string | null;
  exclude?: boolean;
  active_test_scope?: boolean;
  intel_scope?: boolean;
}

export interface ProjectSourceResponse {
  project_id: string;
  source_id: string;
  source_name: string;
  feed_type: string;
  created_at: string;
}

export interface SharedIOC {
  kind: "ip" | "domain" | "hash";
  value: string;
}

export interface CompareResponse {
  project_a_id: string;
  project_b_id: string;
  shared_actors: string[];
  shared_techniques: string[];
  shared_iocs: SharedIOC[];
}

// Re-export the sentinel id for convenience.
export { LEGACY_PROJECT_ID };

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function _handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const data = await res.json();
      if (data && typeof data === "object" && "detail" in data) {
        detail = String((data as { detail?: unknown }).detail ?? detail);
      }
    } catch {
      // ignore JSON-parse errors; keep status text
    }
    throw new Error(detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

/**
 * Parse `filename` out of a Content-Disposition header value.
 *
 * Handles three forms:
 *   - RFC 5987 extended:  filename*=UTF-8''<percent-encoded>
 *   - Quoted:             filename="value"
 *   - Bare:               filename=value
 *
 * Returns `null` when the header is missing or unparseable. The backend is the
 * sole source of truth for the export filename convention — the client MUST
 * NOT synthesise its own filename by slugging the project name (iter-1 lock).
 */
export function parseContentDispositionFilename(
  header: string | null,
): string | null {
  if (!header) return null;
  const ext = /filename\*\s*=\s*UTF-8''([^;\r\n]+)/i.exec(header);
  if (ext?.[1]) {
    try {
      return decodeURIComponent(ext[1]);
    } catch {
      // fall through
    }
  }
  const quoted = /filename\s*=\s*"([^"]+)"/i.exec(header);
  if (quoted?.[1]) return quoted[1];
  const bare = /filename\s*=\s*([^;\r\n]+)/i.exec(header);
  return bare?.[1]?.trim() ?? null;
}

function jsonInit(
  method: string,
  body?: unknown,
  extra?: RequestInit,
): RequestInit {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((extra?.headers as Record<string, string> | undefined) ?? {}),
  };
  return {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
    ...extra,
  };
}

// ---------------------------------------------------------------------------
// Projects CRUD (10-03)
// ---------------------------------------------------------------------------

export async function listProjects(
  opts: { includeArchived?: boolean } = {},
): Promise<ProjectResponse[]> {
  const qs = opts.includeArchived ? "?include_archived=true" : "";
  const r = await _apiFetch(`/api/projects${qs}`, { cache: "no-store" });
  return _handle<ProjectResponse[]>(r);
}

export async function fetchProjectDetail(id: string): Promise<ProjectResponse> {
  const r = await _apiFetch(`/api/projects/${id}`, { cache: "no-store" });
  return _handle<ProjectResponse>(r);
}

export async function createProject(
  body: ProjectCreateBody,
): Promise<ProjectResponse> {
  const r = await _apiFetch(`/api/projects`, jsonInit("POST", body));
  return _handle<ProjectResponse>(r);
}

export async function updateProject(
  id: string,
  patch: ProjectUpdateBody,
): Promise<ProjectResponse> {
  const r = await _apiFetch(`/api/projects/${id}`,
    jsonInit("PATCH", patch),
  );
  return _handle<ProjectResponse>(r);
}

export async function archiveProject(id: string): Promise<ProjectResponse> {
  const r = await _apiFetch(`/api/projects/${id}/archive`,
    jsonInit("POST"),
  );
  return _handle<ProjectResponse>(r);
}

export async function restoreProject(id: string): Promise<ProjectResponse> {
  const r = await _apiFetch(`/api/projects/${id}/restore`,
    jsonInit("POST"),
  );
  return _handle<ProjectResponse>(r);
}

// ---------------------------------------------------------------------------
// Memberships (10-03)
// ---------------------------------------------------------------------------

export async function listMemberships(
  projectId: string,
): Promise<MembershipResponse[]> {
  const r = await _apiFetch(`/api/projects/${projectId}/memberships`, {
    cache: "no-store",
  });
  return _handle<MembershipResponse[]>(r);
}

export async function addMember(
  projectId: string,
  body: MembershipCreateBody,
): Promise<MembershipResponse> {
  const r = await _apiFetch(`/api/projects/${projectId}/memberships`,
    jsonInit("POST", body),
  );
  return _handle<MembershipResponse>(r);
}

export async function updateMemberRole(
  projectId: string,
  membershipId: string,
  role: ProjectRole,
): Promise<MembershipResponse> {
  const r = await _apiFetch(`/api/projects/${projectId}/memberships/${membershipId}`,
    jsonInit("PATCH", { project_role: role }),
  );
  return _handle<MembershipResponse>(r);
}

export async function removeMember(
  projectId: string,
  membershipId: string,
): Promise<void> {
  const r = await _apiFetch(`/api/projects/${projectId}/memberships/${membershipId}`,
    jsonInit("DELETE"),
  );
  await _handle<void>(r);
}

// ---------------------------------------------------------------------------
// Scope rows (10-04)
// ---------------------------------------------------------------------------

export async function listScopeRows(
  projectId: string,
): Promise<ScopeRowResponse[]> {
  const r = await _apiFetch(`/api/projects/${projectId}/scope`, {
    cache: "no-store",
  });
  return _handle<ScopeRowResponse[]>(r);
}

export async function addScopeRow(
  projectId: string,
  body: ScopeRowCreateBody,
): Promise<ScopeRowResponse> {
  const r = await _apiFetch(`/api/projects/${projectId}/scope`,
    jsonInit("POST", body),
  );
  return _handle<ScopeRowResponse>(r);
}

export async function deleteScopeRow(
  projectId: string,
  rowId: string,
): Promise<void> {
  const r = await _apiFetch(`/api/projects/${projectId}/scope/${rowId}`,
    jsonInit("DELETE"),
  );
  await _handle<void>(r);
}

export async function updateScopeRow(
  projectId: string,
  rowId: string,
  patch: ScopeRowUpdateBody,
): Promise<ScopeRowResponse> {
  const r = await _apiFetch(`/api/projects/${projectId}/scope/${rowId}`,
    jsonInit("PATCH", patch),
  );
  return _handle<ScopeRowResponse>(r);
}

// ---------------------------------------------------------------------------
// Project sources (10-04)
// ---------------------------------------------------------------------------

export async function listProjectSources(
  projectId: string,
): Promise<ProjectSourceResponse[]> {
  const r = await _apiFetch(`/api/projects/${projectId}/sources`, {
    cache: "no-store",
  });
  return _handle<ProjectSourceResponse[]>(r);
}

export async function replaceProjectSources(
  projectId: string,
  sourceIds: string[],
): Promise<ProjectSourceResponse[]> {
  const r = await _apiFetch(`/api/projects/${projectId}/sources`,
    jsonInit("PUT", { source_ids: sourceIds }),
  );
  return _handle<ProjectSourceResponse[]>(r);
}

// ---------------------------------------------------------------------------
// Export + Compare (10-07)
// ---------------------------------------------------------------------------

/**
 * Download a per-project STIX bundle or CSV export.
 *
 * Returns the response blob AND the filename parsed out of
 * `Content-Disposition`. Callers trigger the download using the returned
 * filename; they MUST NOT synthesise their own (iter-1 lock — backend owns the
 * slug rules).
 *
 * 413 errors (50k event cap) surface via thrown Error with backend detail; the
 * UI layer maps this to the spec'd toast copy.
 */
export async function exportProject(
  projectId: string,
  format: "stix" | "csv",
): Promise<{ blob: Blob; filename: string }> {
  const r = await _apiFetch(`/api/projects/${projectId}/export?format=${format}`,
    { method: "POST", cache: "no-store" },
  );
  if (!r.ok) {
    let detail = `${r.status} ${r.statusText}`;
    try {
      const data = await r.json();
      if (data && typeof data === "object" && "detail" in data) {
        detail = String((data as { detail?: unknown }).detail ?? detail);
      }
    } catch {
      // ignore
    }
    const err = new Error(detail) as Error & { status?: number };
    err.status = r.status;
    throw err;
  }
  const blob = await r.blob();
  const filename =
    parseContentDispositionFilename(r.headers.get("Content-Disposition")) ??
    // Last-resort fallback used only when the server forgot the header. Uses
    // the opaque project UUID — NOT a slugged project name — so an undetected
    // regression surfaces as an ugly filename rather than silently drifting
    // from the backend's slug convention.
    `intellibird-project-${projectId}.${format === "stix" ? "stix.json" : "csv"}`;
  return { blob, filename };
}

export async function compareProjects(
  a: string,
  b: string,
): Promise<CompareResponse> {
  const r = await _apiFetch(`/api/projects/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`,
    { cache: "no-store" },
  );
  return _handle<CompareResponse>(r);
}

// ---------------------------------------------------------------------------
// Project graph (-03)
// ---------------------------------------------------------------------------

export interface ProjectGraphNode {
  id: string;
  label: string;
  node_type: string;
  tag_source?: string;
}

export interface ProjectGraphEdge {
  source: string;
  target: string;
  relation: string;
}

export interface ProjectGraphResponse {
  nodes: ProjectGraphNode[];
  edges: ProjectGraphEdge[];
  truncated: boolean;
}

export async function fetchProjectGraph(
  projectId: string,
): Promise<ProjectGraphResponse> {
  const r = await _apiFetch(`/api/projects/${projectId}/graph`, {
    method: "GET",
    cache: "no-store",
  });
  return _handle<ProjectGraphResponse>(r);
}

// ---------------------------------------------------------------------------
// Per-project brand stoplist (BRAND-01)
// Server-side only — uses _apiFetch so Auth.js bearer is injected.
// Client components use the helpers in brand/lib/api.ts (browser relative URL).
// ---------------------------------------------------------------------------

export interface BrandStoplistTerm {
  id: string;
  term: string;
  created_at: string;
  created_by_user_id: string | null;
}

export async function listBrandStoplist(
  projectId: string,
): Promise<BrandStoplistTerm[]> {
  const r = await _apiFetch(`/api/projects/${projectId}/brand/stoplist`, {
    cache: "no-store",
  });
  return _handle<BrandStoplistTerm[]>(r);
}

export async function addBrandStoplistTerm(
  projectId: string,
  term: string,
): Promise<BrandStoplistTerm> {
  const r = await _apiFetch(`/api/projects/${projectId}/brand/stoplist`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ term }),
  });
  return _handle<BrandStoplistTerm>(r);
}

export async function deleteBrandStoplistTerm(
  projectId: string,
  termId: string,
): Promise<void> {
  const r = await _apiFetch(
    `/api/projects/${projectId}/brand/stoplist/${termId}`,
    { method: "DELETE" },
  );
  await _handle<void>(r);
}

// ---------------------------------------------------------------------------
// Attack Path Analysis — ATK-01..ATK-04
// ---------------------------------------------------------------------------

export interface AttackPathNode {
  id: string;
  technique_id: string;
  tactic: string;
  name: string;
  confidence: number;
  rationale: string;
}

export interface AttackPathEdge {
  from: string;
  to: string;
  rationale: string;
}

export interface AttackPathResponse {
  nodes: AttackPathNode[];
  edges: AttackPathEdge[];
  truncated: boolean;
  model_used: string;
  events_analysed: number;
}

/**
 * POST /api/projects/{id}/attack-path
 * Triggers AI reconstruction of MITRE kill-chain from project events.
 * Returns structured attack path graph suitable for Cytoscape overlay.
 *
 * @param projectId - Project UUID
 * @param days - Lookback window in days (default 30, max 90)
 */
export async function analyseAttackPath(
  projectId: string,
  days: number = 30,
): Promise<AttackPathResponse> {
  const res = await _apiFetch(`/api/projects/${projectId}/attack-path`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ days }),
  });
  if (res.status === 400) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? "No events in window");
  }
  if (res.status === 503) {
    throw new Error("AI provider not configured for this project");
  }
  if (res.status === 504) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? "AI provider timed out — try a cloud provider (OpenAI / Anthropic) in Admin → AI Settings");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `Attack path analysis failed: HTTP ${res.status}`);
  }
  return res.json() as Promise<AttackPathResponse>;
}
