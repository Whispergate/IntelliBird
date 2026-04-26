// Server-side fetch helper. Uses the compose-internal API_BASE when running
// inside the web container; falls back to localhost for local dev.
import type { components } from "./api-client.generated";

// ============================================================
// Enum types extracted from generated schema
// (These types are inlined in schema objects — no standalone OpenAPI schemas for them)
// ============================================================

// FeedType: "bbot" added locally (Phase 11 plan 11-05); "brand-monitor" added
// locally (Phase 12 plan 12-10) — both pending api-client.generated.ts regen.
export type FeedType =
  | components["schemas"]["SourceResponse"]["feed_type"]
  | "bbot"
  | "brand-monitor"
  // Quick task 260425-ovt: HTML-scrape source type. Backend FeedType already
  // accepts "custom"; widening here keeps types in sync until openapi regen.
  | "custom";

/**
 * Quick task 260425-ovt: canonical scrape_config shape for feed_type='custom'.
 * item/title/link selectors are required; the rest are optional. The backend
 * hard-caps max_items at 200.
 */
export type ScrapeConfig = {
  // Quick task 260426-aas: "auto" mode omits selectors (trafilatura discovery);
  // "manual" mode requires item/title/link selectors. Absent mode = legacy
  // manual rows shipped 2026-04-25.
  mode?: "auto" | "manual";
  item_selector?: string;
  title_selector?: string;
  link_selector?: string;
  date_selector?: string;
  date_format?: string;
  summary_selector?: string;
  user_agent?: string;
  max_items?: number;
};
export type ArchivePolicy = components["schemas"]["SourceResponse"]["archive_policy"];
// TlpName: non-nullable enum (generated EventItem.tlp is optional nullable; we normalise here)
export type TlpName = "clear" | "green" | "amber" | "amber+strict" | "red";
export type Visibility = components["schemas"]["EventItem"]["visibility"];
export type DestinationType = components["schemas"]["WebhookResponse"]["destination_type"];

// WebhookAuth — union of generated discriminated auth schemas
export type WebhookAuth =
  | components["schemas"]["BearerAuth"]
  | components["schemas"]["BasicAuth"]
  | components["schemas"]["HeaderAuth"];

// ============================================================
// Types imported from generated OpenAPI schema
// ============================================================

export type SystemStatus = components["schemas"]["SystemStatusResponse"];
// Quick task 260425-ovt: widen Source/Create/Update/TestConnection types with
// optional scrape_config + the local FeedType union. The generated schema does
// not yet include 260425-ovt fields; once `pnpm gen:api` regenerates these
// overrides become no-ops.
export type Source = Omit<components["schemas"]["SourceResponse"], "feed_type"> & {
  feed_type: FeedType;
  scrape_config?: ScrapeConfig | null;
};
export type CreateSourcePayload = Omit<components["schemas"]["SourceCreate"], "feed_type"> & {
  feed_type: FeedType;
  scrape_config?: ScrapeConfig | null;
};
export type UpdateSourcePayload = components["schemas"]["SourceUpdate"] & {
  scrape_config?: ScrapeConfig | null;
};
export type TestConnectionPayload = Omit<
  components["schemas"]["TestConnectionRequest"],
  "feed_type"
> & {
  feed_type: FeedType;
  scrape_config?: ScrapeConfig | null;
};
export type TestConnectionResult = components["schemas"]["TestConnectionResponse"];
export type CredentialField = components["schemas"]["CredentialField"];
export type SourceTemplate = components["schemas"]["SourceTemplate"];

// EventItem: override optional fields to required (callers depend on required shapes;
// generated schema marks source_name, source_type, tlp, tags, attack_techniques as optional)
// easm_scan_id: added by Phase 11 migration 010 (plan 11-01); not yet in generated schema
// (pending pnpm gen:api regen when backend is reachable). Typed locally as string|null.
// score / scored_at / score_version: added by Phase 15 migration 013 (plan 15-01).
// Typed locally until generated schema is regenerated from the new backend.
export type EventItem = Omit<
  components["schemas"]["EventItem"],
  "tlp" | "attack_techniques" | "tags" | "source_name" | "source_type"
> & {
  tlp: TlpName | null;
  attack_techniques: string[];
  tags: string[];
  source_name: string | null;
  source_type: FeedType | null;
  easm_scan_id?: string | null;
  score?: number | null;
  scored_at?: string | null;
  score_version?: number | null;
};

// EventDetail: same field overrides as EventItem plus raw_stix
// score / scored_at / score_version: Phase 15 migration 013 local extensions.
export type EventDetail = Omit<
  components["schemas"]["EventDetail"],
  "tlp" | "attack_techniques" | "tags" | "source_name" | "source_type"
> & {
  tlp: TlpName | null;
  attack_techniques: string[];
  tags: string[];
  source_name: string | null;
  source_type: FeedType | null;
  raw_stix: Record<string, unknown> | null;
  score?: number | null;
  scored_at?: string | null;
  score_version?: number | null;
};

// EventListResponse: override items array to use our normalised EventItem type
export type EventListResponse = Omit<components["schemas"]["EventListResponse"], "items"> & {
  items: EventItem[];
};
export type FilterPreset = components["schemas"]["FilterPresetResponse"];
export type GraphNode = components["schemas"]["GraphNode"];
export type GraphEdge = components["schemas"]["GraphEdge"];
export type GraphResponse = components["schemas"]["GraphResponse"];
export type TagPatchPayload = components["schemas"]["TagPatchRequest"];
export type TagPatchResponse = components["schemas"]["TagPatchResponse"];

// Webhook: override bound_preset_names to required (callers depend on it always being present)
export type Webhook = Omit<components["schemas"]["WebhookResponse"], "bound_preset_names"> & {
  bound_preset_names: string[];
};

export type CreateWebhookPayload = components["schemas"]["WebhookCreate"];

// UpdateWebhookPayload: make clear_auth optional (callers don't always send it; backend defaults to false)
export type UpdateWebhookPayload = Omit<components["schemas"]["WebhookUpdate"], "clear_auth"> & {
  clear_auth?: boolean;
};

export type TestWebhookPayload = components["schemas"]["TestSendRequest"];
export type TestWebhookResult = components["schemas"]["TestSendResponse"];
export type RekeyResponse = components["schemas"]["RekeyResponse"];
export type EventCount = components["schemas"]["EventCountResponse"];

// AI suggestion row (Phase 17 / AI-08). Mirrors backend
// app/schemas/ai.py::AISuggestionRead. Inlined here pending
// api-client.generated.ts regen.
export type AISuggestionRead = {
  id: string;
  ai_summary_id: string;
  project_id: string;
  event_id: string | null;
  suggestion_type: "cve" | "attack" | "actor";
  value: string;
  status: "pending" | "confirmed" | "discarded";
  created_at: string;
  decided_at: string | null;
  decided_by_user_id: string | null;
};

// ============================================================
// UI-only types (not in OpenAPI schema — frontend shapes only)
// ============================================================

export type DashboardRole = "red" | "blue"; // frontend-only, not in OpenAPI schema

export type EventsQuery = {
  source?: string[];
  source_type?: FeedType[];
  observed_from?: string;
  observed_to?: string;
  tlp?: TlpName[];
  attack_technique?: string[];
  tag?: string[];
  free_text?: string;
  include_archived?: boolean;
  include_total?: boolean;
  include_bbot?: boolean;
  cursor?: string;
  limit?: number;
  has_geo?: boolean;
  tag_mode?: "any" | "all";
};

// DeliveryStatus — more specific than generated WebhookResponse.last_delivery_status (string | null)
export type DeliveryStatus = "ok" | "http_error" | "network_error" | "timeout" | null;

// ============================================================
// API base + helpers
// ============================================================

// Browser: use relative URLs → Next.js Route Handler at /api/[...path] proxies
// to BACKEND_URL at request time (same-origin, no CORS). The proxy reads the
// Auth.js session cookie and injects `Authorization: Bearer <token>` before
// forwarding upstream.
//
// Server (RSC, Server Action, Route Handler that calls these helpers): cannot
// use relative URLs — Node.js fetch needs an origin. Talks directly to backend
// over the compose internal network AND must inject the bearer token itself
// because the request never traverses the /api/[...path] proxy on the SSR
// path. See _apiFetch below.
const SERVER_API_BASE =
  process.env.API_BASE ??
  process.env.NEXT_PUBLIC_API_BASE ??
  "http://api:8000";

/**
 * Universal fetch helper used by every call site in this module.
 *
 * - Browser: relative URL, browser sends Auth.js cookie, /api/[...path]
 *   route handler injects bearer before forwarding upstream.
 * - Server: absolute URL to backend container; reads Auth.js session via
 *   `auth()` and injects `Authorization: Bearer <token>` directly so the
 *   backend AuthMiddleware accepts the request.
 *
 * Without the server-side bearer injection, every RSC fetch returns 401
 * `invalid_token` because the backend never sees the cookie that would
 * have authenticated the proxy hop.
 */
export async function _apiFetch(path: string, init?: RequestInit): Promise<Response> {
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

async function _handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status} ${res.statusText}: ${text}`);
  }
  return res.json() as Promise<T>;
}

function _buildQuery(q: EventsQuery): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(q)) {
    if (value === undefined || value === null) continue;
    if (Array.isArray(value)) for (const v of value) params.append(key, String(v));
    else params.append(key, String(value));
  }
  const s = params.toString();
  return s ? `?${s}` : "";
}

function _roleHeaders(role?: DashboardRole): HeadersInit {
  return role ? { "X-Dashboard-Role": role } : {};
}

// ============================================================
// System status
// ============================================================

export async function fetchSystemStatus(): Promise<SystemStatus | null> {
  try {
    const res = await _apiFetch(`/api/system/status`, {
      cache: "no-store",
    });
    if (!res.ok) return null;
    return (await res.json()) as SystemStatus;
  } catch {
    return null;
  }
}

// ============================================================
// Sources — SRC-01..04
// ============================================================

export async function fetchSources(): Promise<Source[]> {
  const res = await _apiFetch(`/api/admin/sources`, { cache: "no-store" });
  return _handle<Source[]>(res);
}

export async function fetchSource(id: string): Promise<Source> {
  const res = await _apiFetch(`/api/admin/sources/${id}`, { cache: "no-store" });
  return _handle<Source>(res);
}

export async function createSource(payload: CreateSourcePayload): Promise<Source> {
  const res = await _apiFetch(`/api/admin/sources`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store",
  });
  return _handle<Source>(res);
}

export async function updateSource(id: string, payload: UpdateSourcePayload): Promise<Source> {
  const res = await _apiFetch(`/api/admin/sources/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store",
  });
  return _handle<Source>(res);
}

export async function deleteSource(id: string): Promise<void> {
  const res = await _apiFetch(`/api/admin/sources/${id}`, {
    method: "DELETE",
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status} ${res.statusText}: ${text}`);
  }
}

export async function getSourceEventCount(id: string): Promise<EventCount> {
  const res = await _apiFetch(`/api/admin/sources/${id}/event-count`, { cache: "no-store" });
  return _handle<EventCount>(res);
}

export async function testConnection(
  payload: TestConnectionPayload,
): Promise<TestConnectionResult> {
  const res = await _apiFetch(`/api/admin/sources/test-connection`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store",
  });
  return _handle<TestConnectionResult>(res);
}

// Preconfigured source templates (operator quick-add)
export async function fetchSourceTemplates(): Promise<SourceTemplate[]> {
  const res = await _apiFetch(`/api/admin/source-templates`, { cache: "no-store" });
  return _handle<SourceTemplate[]>(res);
}

// ============================================================
// Events — FIL-01..05, FIL-03, FIL-04
// ============================================================

export async function listEvents(
  query: EventsQuery = {},
  role?: DashboardRole,
): Promise<EventListResponse> {
  const res = await _apiFetch(`/api/events${_buildQuery(query)}`, {
    cache: "no-store",
    headers: _roleHeaders(role),
  });
  return _handle<EventListResponse>(res);
}

export async function getEvent(id: string, role?: DashboardRole): Promise<EventDetail> {
  const res = await _apiFetch(`/api/events/${id}`, {
    cache: "no-store",
    headers: _roleHeaders(role),
  });
  return _handle<EventDetail>(res);
}

export async function patchEventTags(
  id: string,
  payload: TagPatchPayload,
): Promise<TagPatchResponse> {
  const res = await _apiFetch(`/api/events/${id}/tags`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store",
  });
  return _handle<TagPatchResponse>(res);
}

export async function getEventGraph(
  id: string,
  depth: 1 | 2 | 3 = 2,
  role?: DashboardRole,
): Promise<GraphResponse> {
  const res = await _apiFetch(`/api/events/${id}/graph?depth=${depth}`, {
    cache: "no-store",
    headers: _roleHeaders(role),
  });
  return _handle<GraphResponse>(res);
}

// ============================================================
// Filter presets — FIL-05
// ============================================================

export async function listPresets(): Promise<FilterPreset[]> {
  const res = await _apiFetch(`/api/presets`, { cache: "no-store" });
  return _handle<FilterPreset[]>(res);
}

export async function getPreset(name: string): Promise<FilterPreset> {
  const res = await _apiFetch(`/api/presets/${encodeURIComponent(name)}`, {
    cache: "no-store",
  });
  return _handle<FilterPreset>(res);
}

export async function createPreset(
  name: string,
  query_params: Record<string, unknown>,
): Promise<FilterPreset> {
  const res = await _apiFetch(`/api/presets`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, query_params }),
    cache: "no-store",
  });
  return _handle<FilterPreset>(res);
}

export async function upsertPreset(
  name: string,
  query_params: Record<string, unknown>,
): Promise<FilterPreset> {
  const res = await _apiFetch(`/api/presets/${encodeURIComponent(name)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query_params }),
    cache: "no-store",
  });
  return _handle<FilterPreset>(res);
}

export async function deletePreset(name: string): Promise<void> {
  const res = await _apiFetch(`/api/presets/${encodeURIComponent(name)}`, {
    method: "DELETE",
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status} ${res.statusText}: ${text}`);
  }
}

// ============================================================
// Webhook alerts — HOOK-01, HOOK-02, HOOK-06, HOOK-09
// ============================================================

export async function listWebhooks(): Promise<Webhook[]> {
  const res = await _apiFetch(`/api/admin/webhooks`, { cache: "no-store" });
  return _handle<Webhook[]>(res);
}

export async function createWebhook(payload: CreateWebhookPayload): Promise<Webhook> {
  const res = await _apiFetch(`/api/admin/webhooks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store",
  });
  return _handle<Webhook>(res);
}

export async function updateWebhook(
  id: string,
  payload: UpdateWebhookPayload,
): Promise<Webhook> {
  const res = await _apiFetch(`/api/admin/webhooks/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store",
  });
  return _handle<Webhook>(res);
}

export async function deleteWebhook(id: string): Promise<void> {
  const res = await _apiFetch(`/api/admin/webhooks/${id}`, {
    method: "DELETE",
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status} ${res.statusText}: ${text}`);
  }
}

export async function testWebhook(
  payload: TestWebhookPayload,
): Promise<TestWebhookResult> {
  const res = await _apiFetch(`/api/admin/webhooks/test-send`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store",
  });
  return _handle<TestWebhookResult>(res);
}

// ============================================================
// Monitoring sources — MON-04, Phase 16 plan 16-07
// (Types locally defined — api-client.generated.ts pending regen when
//  backend openapi endpoint is accessible without auth.)
// ============================================================

export type MonitoringSourceItem = {
  id: string;
  name: string;
  feed_type: string;
  last_event_at: string | null;
  silence_sla_seconds: number;
  sla_breached: boolean;
  silent_failure_count: number;
  parse_error_rate_1h: number;
  drift_z_score: number | null;
  drift_severity: string | null;
  sparkline: number[];
};

export type MonitoringConfigPatch = {
  last_event_sla_seconds?: number | null;
  drift_z_high?: number | null;
  drift_z_medium?: number | null;
};

export async function listMonitoringSources(): Promise<MonitoringSourceItem[]> {
  const res = await _apiFetch("/api/admin/monitoring/sources", {
    cache: "no-store",
  });
  return _handle<MonitoringSourceItem[]>(res);
}

export async function patchMonitoringConfig(
  sourceId: string,
  payload: MonitoringConfigPatch,
): Promise<Record<string, unknown>> {
  const res = await _apiFetch(`/api/admin/monitoring/sources/${sourceId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store",
  });
  return _handle<Record<string, unknown>>(res);
}

// ============================================================
// Maintenance windows — H-7, Phase 16 plan 16-07
// ============================================================

export type MaintenanceWindowItem = {
  id: string;
  start_at: string;
  end_at: string;
  reason: string | null;
  created_by_user_id: string | null;
  created_at: string;
};

export type CreateMaintenanceWindowPayload = {
  start_at: string;
  end_at: string;
  reason?: string | null;
};

export async function listMaintenanceWindows(): Promise<MaintenanceWindowItem[]> {
  const res = await _apiFetch("/api/admin/maintenance-window", {
    cache: "no-store",
  });
  return _handle<MaintenanceWindowItem[]>(res);
}

export async function getActiveMaintenanceWindow(): Promise<MaintenanceWindowItem | null> {
  const res = await _apiFetch("/api/admin/maintenance-window/active", {
    cache: "no-store",
  });
  if (res.status === 404) return null;
  return _handle<MaintenanceWindowItem>(res);
}

export async function createMaintenanceWindow(
  payload: CreateMaintenanceWindowPayload,
): Promise<{ id: string }> {
  const res = await _apiFetch("/api/admin/maintenance-window", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store",
  });
  return _handle<{ id: string }>(res);
}

export async function deleteMaintenanceWindow(id: string): Promise<void> {
  const res = await _apiFetch(`/api/admin/maintenance-window/${id}`, {
    method: "DELETE",
    cache: "no-store",
  });
  if (!res.ok && res.status !== 204) {
    const text = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status} ${res.statusText}: ${text}`);
  }
}
