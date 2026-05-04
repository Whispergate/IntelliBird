// Server-side fetch helper. Uses the compose-internal API_BASE when running
// inside the web container; falls back to localhost for local dev.
import type { components } from "./api-client.generated";

// ============================================================
// Enum types extracted from generated schema
// (These types are inlined in schema objects — no standalone OpenAPI schemas for them)
// ============================================================

// FeedType: "bbot" added locally (Phase 11 plan 11-05); "brand-monitor" added
// locally (Phase 12 plan 12-10) — both pending api-client.generated.ts regen.
// Phase 24 / DARK-07: "tor_html", "paste", "telegram" added for dark-web collection.
export type FeedType =
  | components["schemas"]["SourceResponse"]["feed_type"]
  | "bbot"
  | "brand-monitor"
  // Quick task 260425-ovt: HTML-scrape source type. Backend FeedType already
  // accepts "custom"; widening here keeps types in sync until openapi regen.
  | "custom"
  // Phase 24 / DARK-07: dark-web source types.
  | "tor_html"
  | "paste"
  | "telegram";

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
  // Phase 24 / DARK-07: operator OPSEC acknowledgement flag stored on the source row.
  opsec_authorised?: boolean;
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
  include_brand_match?: boolean;
  include_monitoring?: boolean;
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

// Phase 28 — extended GraphResponse with centrality fields
export type TraverseGraphResponse = GraphResponse & {
  per_node_centrality?: Record<string, number> | null;
  centrality_truncated?: boolean;
};

/**
 * GET /api/projects/{id}/graph/traverse — multi-hop AGE Cypher traversal.
 *
 * Client-side only — uses relative URL through the [...path] proxy.
 * Per CLAUDE.md: browser fetches must use relative URLs (no _apiFetch).
 */
export async function traverseGraph(
  projectId: string,
  seedIocId: string,
  hops: 1 | 2 | 3,
  edgeFilter: string[] = [],
): Promise<TraverseGraphResponse> {
  const params = new URLSearchParams({
    seed_ioc_id: seedIocId,
    hops: String(hops),
  });
  for (const f of edgeFilter) {
    params.append("edge_filter[]", f);
  }
  const res = await fetch(`/api/projects/${projectId}/graph/traverse?${params.toString()}`);
  return _handle<TraverseGraphResponse>(res);
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

// ============================================================
// IOCs — Phase 22 (IOC-02..08). Shapes mirror backend
// app/schemas/iocs.py::IOCRead + IOCPatch. Inlined pending
// api-client.generated.ts regen.
// ============================================================

export type IOCType =
  | "ip"
  | "ipv6"
  | "domain"
  | "url"
  | "sha256"
  | "sha1"
  | "md5"
  | "email"
  | "btc"
  | "eth"
  | "mutex"
  | "registry_key"
  | "filename";

export type IOCStatus = "active" | "expired" | "whitelisted";
export type IOCSource = "manual" | "csv" | "json" | "stix" | "event" | "backfill";

export type IOCRead = {
  id: string;
  project_id: string | null;
  type: IOCType;
  value: string;
  normalized_value: string;
  status: IOCStatus;
  confidence: string; // Numeric(3,2) serialised as string
  ttl_days: number;
  source: IOCSource;
  first_seen: string;
  last_seen: string;
  created_at: string;
  updated_at: string;
  created_by: string | null;
};

export type IOCPatch = {
  confidence?: string | number;
  ttl_days?: number;
};

export type IOCEventSummary = {
  id: string;
  title: string;
  observed_at: string;
  stix_type: string | null;
  visibility: string | null;
  source_id: string | null;
};

export type IOCBulkImportFormat = "csv" | "json" | "stix";

export type IOCBulkImportError = {
  line: number;
  value: string;
  error: string;
};

export type IOCBulkImportDryRun = {
  would_insert: number;
  would_update: number;
  would_skip: number;
  unmapped_sdo_count: number;
  errors: IOCBulkImportError[];
};

export type IOCBulkImportEnqueued = {
  job_id: string;
  rows_accepted: number;
};

export type IOCJobStatus = {
  status: "queued" | "running" | "complete" | "failed";
  processed?: number;
  total?: number;
  inserted?: number;
  updated?: number;
  skipped?: number;
  events_processed?: number;
  iocs_inserted?: number;
  error?: string;
};

export type IOCBackfillEnqueued = {
  job_id: string;
  project_id: string | null;
};

export type IOCListParams = {
  projectId?: string;
  type?: string[];
  status?: string;
  min_confidence?: number;
  age_days?: number;
  q?: string;
  include_expired?: boolean;
  limit?: number;
  cursor?: string;
};

function _iocListQuery(params: IOCListParams): string {
  const sp = new URLSearchParams();
  if (params.projectId) sp.append("project_id", params.projectId);
  if (params.type) for (const t of params.type) sp.append("type", t);
  if (params.status) sp.append("status", params.status);
  if (params.min_confidence !== undefined) sp.append("min_confidence", String(params.min_confidence));
  if (params.age_days !== undefined) sp.append("age_days", String(params.age_days));
  if (params.q) sp.append("q", params.q);
  if (params.include_expired) sp.append("include_expired", "true");
  if (params.limit !== undefined) sp.append("limit", String(params.limit));
  if (params.cursor) sp.append("cursor", params.cursor);
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export async function listIOCs(params: IOCListParams = {}): Promise<IOCRead[]> {
  const res = await _apiFetch(`/api/iocs${_iocListQuery(params)}`, { cache: "no-store" });
  return _handle<IOCRead[]>(res);
}

export async function getIOC(id: string): Promise<IOCRead> {
  const res = await _apiFetch(`/api/iocs/${id}`, { cache: "no-store" });
  return _handle<IOCRead>(res);
}

export async function getIOCEvents(id: string, limit = 25): Promise<IOCEventSummary[]> {
  const res = await _apiFetch(`/api/iocs/${id}/events?limit=${limit}`, { cache: "no-store" });
  return _handle<IOCEventSummary[]>(res);
}

export async function listEventIOCs(eventId: string, limit = 200): Promise<IOCRead[]> {
  const res = await _apiFetch(`/api/events/${eventId}/iocs?limit=${limit}`, {
    cache: "no-store",
  });
  return _handle<IOCRead[]>(res);
}

export async function whitelistIOC(
  id: string,
  opts: { projectId?: string } = {},
): Promise<IOCRead> {
  const qs = opts.projectId ? `?project_id=${encodeURIComponent(opts.projectId)}` : "";
  const res = await _apiFetch(`/api/iocs/${id}/whitelist${qs}`, {
    method: "POST",
    cache: "no-store",
  });
  return _handle<IOCRead>(res);
}

export async function unwhitelistIOC(id: string): Promise<IOCRead> {
  const res = await _apiFetch(`/api/iocs/${id}/whitelist`, {
    method: "DELETE",
    cache: "no-store",
  });
  return _handle<IOCRead>(res);
}

export async function patchIOC(id: string, body: IOCPatch): Promise<IOCRead> {
  const res = await _apiFetch(`/api/iocs/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  return _handle<IOCRead>(res);
}

export async function deleteIOC(id: string): Promise<void> {
  const res = await _apiFetch(`/api/iocs/${id}`, {
    method: "DELETE",
    cache: "no-store",
  });
  if (!res.ok && res.status !== 204) {
    const text = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status} ${res.statusText}: ${text}`);
  }
}

function _bulkImportContentType(format: IOCBulkImportFormat): string {
  if (format === "csv") return "text/csv";
  if (format === "json") return "application/json";
  return "application/stix+json";
}

export async function dryRunBulkImport(opts: {
  projectId?: string;
  format: IOCBulkImportFormat;
  body: string | Blob;
}): Promise<IOCBulkImportDryRun> {
  const sp = new URLSearchParams();
  sp.append("dry_run", "true");
  sp.append("format", opts.format);
  if (opts.projectId) sp.append("project_id", opts.projectId);
  const res = await _apiFetch(`/api/iocs/bulk-import?${sp.toString()}`, {
    method: "POST",
    headers: { "Content-Type": _bulkImportContentType(opts.format) },
    body: opts.body,
    cache: "no-store",
  });
  return _handle<IOCBulkImportDryRun>(res);
}

export async function submitBulkImport(opts: {
  projectId?: string;
  format: IOCBulkImportFormat;
  body: string | Blob;
}): Promise<IOCBulkImportEnqueued> {
  const sp = new URLSearchParams();
  sp.append("format", opts.format);
  if (opts.projectId) sp.append("project_id", opts.projectId);
  const res = await _apiFetch(`/api/iocs/bulk-import?${sp.toString()}`, {
    method: "POST",
    headers: { "Content-Type": _bulkImportContentType(opts.format) },
    body: opts.body,
    cache: "no-store",
  });
  return _handle<IOCBulkImportEnqueued>(res);
}

export async function pollJobStatus(jobId: string): Promise<IOCJobStatus> {
  const res = await _apiFetch(`/api/jobs/${jobId}`, { cache: "no-store" });
  return _handle<IOCJobStatus>(res);
}

export async function triggerBackfill(projectId?: string): Promise<IOCBackfillEnqueued> {
  const qs = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
  const res = await _apiFetch(`/api/admin/iocs/backfill${qs}`, {
    method: "POST",
    cache: "no-store",
  });
  return _handle<IOCBackfillEnqueued>(res);
}

// ============================================================
// Enrichment types — Phase 23 / ENRICH-01, ENRICH-04
// ============================================================

export type EnrichmentProviderName =
  | "vt"
  | "abuseipdb"
  | "greynoise"
  | "otx"
  | "shodan"
  | "urlhaus";

export type EnrichmentProviderRead = {
  id: string;
  project_id: string | null;
  provider: EnrichmentProviderName;
  enabled: boolean;
  api_key_masked: string | null;
  daily_request_cap: number | null;
  breaker_open_until: string | null; // ISO 8601 datetime or null
  created_at: string;
  updated_at: string;
};

export type EnrichmentProviderWrite = {
  enabled: boolean;
  api_key?: string | null;
  daily_request_cap?: number | null;
};

export type IOCEnrichmentRead = {
  id: string;
  ioc_id: string;
  provider: string;
  verdict: "clean" | "suspicious" | "malicious" | "unknown";
  score: number | null;
  fetched_at: string;
  evidence_text: string | null;
};

// ============================================================
// Enrichment API helpers
// ============================================================

/**
 * GET /api/projects/{project_id}/enrichment-providers
 * List all 6 provider slots for a project (with breaker state).
 * Client-side fetch — uses relative URL through /api/[...path] proxy.
 */
export async function listEnrichmentProviders(
  projectId: string,
): Promise<EnrichmentProviderRead[]> {
  const res = await fetch(`/api/projects/${projectId}/enrichment-providers`);
  if (!res.ok) throw new Error(`listEnrichmentProviders failed: ${res.status}`);
  return res.json() as Promise<EnrichmentProviderRead[]>;
}

/**
 * PUT /api/projects/{project_id}/enrichment-providers/{provider}
 * Create or update a provider row (encrypted key, enable/disable, cap).
 */
export async function upsertEnrichmentProvider(
  projectId: string,
  provider: EnrichmentProviderName,
  payload: EnrichmentProviderWrite,
): Promise<EnrichmentProviderRead> {
  const res = await fetch(
    `/api/projects/${projectId}/enrichment-providers/${provider}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (!res.ok) throw new Error(`upsertEnrichmentProvider failed: ${res.status}`);
  return res.json() as Promise<EnrichmentProviderRead>;
}

/**
 * GET /api/iocs/{id}/enrichments
 * Fetch per-provider enrichment results for an IOC.
 */
export async function getIOCEnrichments(
  iocId: string,
): Promise<IOCEnrichmentRead[]> {
  const res = await fetch(`/api/iocs/${iocId}/enrichments`);
  if (!res.ok) throw new Error(`getIOCEnrichments failed: ${res.status}`);
  return res.json() as Promise<IOCEnrichmentRead[]>;
}

/**
 * POST /api/iocs/{id}/enrich
 * Manually trigger re-enrichment. Pass refresh=true to bypass 24h cache.
 */
export async function triggerIOCEnrichment(
  iocId: string,
  options: { refresh?: boolean } = {},
): Promise<{ queued: boolean; ioc_id: string }> {
  const url = `/api/iocs/${iocId}/enrich${options.refresh ? "?refresh=true" : ""}`;
  const res = await fetch(url, { method: "POST" });
  if (!res.ok) throw new Error(`triggerIOCEnrichment failed: ${res.status}`);
  return res.json() as Promise<{ queued: boolean; ioc_id: string }>;
}

// ── Audit Log ──────────────────────────────────────────────────────────────

export interface AuditLogRead {
  id: string;
  time: string;
  user_sub: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  project_id: string | null;
  before_jsonb: Record<string, unknown> | null;
  after_jsonb: Record<string, unknown> | null;
  request_id: string | null;
}

export interface AuditLogListResponse {
  items: AuditLogRead[];
  next_cursor: string | null;
}

export async function listAuditLog(params?: {
  user_sub?: string;
  resource_type?: string;
  action?: string;
  from_dt?: string;   // ISO string
  to_dt?: string;     // ISO string
  limit?: number;
  cursor?: string;    // ISO timestamp of last row time
}): Promise<AuditLogListResponse> {
  const sp = new URLSearchParams();
  if (params?.user_sub)      sp.set("user_sub",      params.user_sub);
  if (params?.resource_type) sp.set("resource_type", params.resource_type);
  if (params?.action)        sp.set("action",        params.action);
  if (params?.from_dt)       sp.set("from_dt",       params.from_dt);
  if (params?.to_dt)         sp.set("to_dt",         params.to_dt);
  if (params?.limit)         sp.set("limit",         String(params.limit));
  if (params?.cursor)        sp.set("cursor",        params.cursor);
  const res = await fetch(`/api/admin/audit?${sp}`);
  if (res.status === 403) throw Object.assign(new Error("forbidden"), { status: 403 });
  if (!res.ok) throw new Error(`listAuditLog: ${res.status}`);
  return res.json();
}

// ── Actors ─────────────────────────────────────────────────────────────────

export interface ActorRead {
  id: string;
  primary_name: string;
  aliases: string[] | null;
  country: string | null;
  motivation: string | null;
  sophistication: string | null;
  first_seen: string | null;
  profile_md: string | null;
  mitre_group_id: string | null;
  last_bootstrap_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ActorListResponse {
  items: ActorRead[];
  next_cursor: string | null;
  total: number | null;
}

export interface CampaignRead {
  id: string;
  name: string;
  actor_id: string | null;
  start_date: string | null;
  end_date: string | null;
  summary_md: string | null;
  project_id: string | null;
  created_by_user_sub: string | null;
  created_at: string;
  updated_at: string;
}

export interface CampaignListResponse {
  items: CampaignRead[];
  next_cursor: string | null;
}

export interface ActorGraphData {
  nodes: Array<{ data: { id: string; label: string; type: string } }>;
  edges: Array<{ data: { id: string; source: string; target: string; label: string } }>;
}

export async function listActors(params?: {
  q?: string;
  country?: string;
  sophistication?: string;
  limit?: number;
  cursor?: string;
}): Promise<ActorListResponse> {
  const sp = new URLSearchParams();
  if (params?.q) sp.set("q", params.q);
  if (params?.country) sp.set("country", params.country);
  if (params?.sophistication) sp.set("sophistication", params.sophistication);
  if (params?.limit) sp.set("limit", String(params.limit));
  if (params?.cursor) sp.set("cursor", params.cursor);
  const res = await fetch(`/api/actors?${sp}`);
  if (!res.ok) throw new Error(`listActors: ${res.status}`);
  return res.json();
}

export async function getActor(id: string): Promise<ActorRead> {
  const res = await fetch(`/api/actors/${id}`);
  if (!res.ok) throw new Error(`getActor: ${res.status}`);
  return res.json();
}

export async function getActorGraph(id: string): Promise<ActorGraphData> {
  const res = await fetch(`/api/actors/${id}/graph`);
  if (!res.ok) throw new Error(`getActorGraph: ${res.status}`);
  return res.json();
}

export async function createActor(
  payload: Omit<ActorRead, "id" | "created_at" | "updated_at" | "mitre_group_id" | "last_bootstrap_at">,
): Promise<ActorRead> {
  const res = await fetch("/api/actors", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`createActor: ${res.status}`);
  return res.json();
}

export async function patchActor(id: string, payload: Partial<ActorRead>): Promise<ActorRead> {
  const res = await fetch(`/api/actors/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`patchActor: ${res.status}`);
  return res.json();
}

export async function listCampaigns(projectId: string): Promise<CampaignListResponse> {
  const res = await fetch(`/api/campaigns?project_id=${projectId}`);
  if (!res.ok) throw new Error(`listCampaigns: ${res.status}`);
  return res.json();
}

export async function createCampaign(payload: {
  name: string;
  actor_id?: string;
  start_date?: string;
  end_date?: string;
  summary_md?: string;
  project_id?: string;
}): Promise<CampaignRead> {
  const res = await fetch("/api/campaigns", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`createCampaign: ${res.status}`);
  return res.json();
}

export async function patchCampaign(
  id: string,
  payload: Partial<CampaignRead>,
): Promise<CampaignRead> {
  const res = await fetch(`/api/campaigns/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`patchCampaign: ${res.status}`);
  return res.json();
}

export async function deleteCampaign(id: string): Promise<void> {
  const res = await fetch(`/api/campaigns/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`deleteCampaign: ${res.status}`);
}

export async function linkEventToCampaign(campaignId: string, eventId: string): Promise<void> {
  const res = await fetch(`/api/campaigns/${campaignId}/events/${eventId}`, { method: "POST" });
  if (!res.ok) throw new Error(`linkEventToCampaign: ${res.status}`);
}

export async function unlinkEventFromCampaign(campaignId: string, eventId: string): Promise<void> {
  const res = await fetch(`/api/campaigns/${campaignId}/events/${eventId}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`unlinkEventFromCampaign: ${res.status}`);
}

// ---------------------------------------------------------------------------
// TAXII Partner Key Admin — Phase 26 / TAXII-03
// ---------------------------------------------------------------------------

export interface TaxiiClientRead {
  id: string;
  label: string;
  project_id: string;
  tlp_max_level: string;
  rate_limit_rpm: number;
  revoked: boolean;
  revoked_at: string | null;
  created_at: string;
}

export interface TaxiiClientCreated extends TaxiiClientRead {
  raw_api_key: string; // shown once — copy immediately
}

export interface TaxiiClientCreate {
  label: string;
  project_id: string;
  tlp_max_level?: string;
  rate_limit_rpm?: number;
}

export async function listTaxiiClients(): Promise<TaxiiClientRead[]> {
  const res = await fetch('/api/admin/taxii-clients/');
  if (!res.ok) throw new Error(`listTaxiiClients: ${res.status}`);
  return res.json();
}

export async function createTaxiiClient(body: TaxiiClientCreate): Promise<TaxiiClientCreated> {
  const res = await fetch('/api/admin/taxii-clients/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`createTaxiiClient: ${res.status}`);
  return res.json();
}

export async function revokeTaxiiClient(id: string): Promise<void> {
  const res = await fetch(`/api/admin/taxii-clients/${id}`, { method: 'DELETE' });
  if (!res.ok && res.status !== 204) throw new Error(`revokeTaxiiClient: ${res.status}`);
}

// === Phase 27: Sandbox + YARA ===

export interface SandboxReportRead {
  id: string;
  event_id: string;
  project_id: string;
  provider: string;
  status: string;
  sha256: string;
  report_json: Record<string, unknown> | null;
  techniques: string[] | null;
  network_iocs: string[] | null;
  process_tree: Record<string, unknown> | null;
  score: number | null;
  verdict: string | null;
  submitted_at: string;
  completed_at: string | null;
  poll_attempts: number;
}

export interface YaraRuleRead {
  id: string;
  name: string;
  family: string;
  enabled: boolean;
  project_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface YaraRuleCreate {
  name: string;
  family: string;
  content: string;
  enabled: boolean;
  project_id?: string | null;
}

export interface SandboxConfigCreate {
  provider: "cuckoo" | "anyrun" | "joesandbox" | "hybridanalysis" | "triage";
  api_key?: string | null;
  enabled: boolean;
  public_warning_acknowledged: boolean;
  options?: Record<string, unknown>;
}

export async function getSandboxReport(
  projectId: string,
  eventId: string,
): Promise<SandboxReportRead | null> {
  const res = await _apiFetch(`/api/projects/${projectId}/events/${eventId}/sandbox-report`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listYaraRules(params?: {
  project_id?: string;
  enabled?: boolean;
}): Promise<YaraRuleRead[]> {
  const qs = new URLSearchParams();
  if (params?.project_id) qs.set("project_id", params.project_id);
  if (params?.enabled !== undefined) qs.set("enabled", String(params.enabled));
  const res = await _apiFetch(`/api/admin/yara-rules?${qs}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function createYaraRule(body: YaraRuleCreate): Promise<YaraRuleRead> {
  const res = await _apiFetch("/api/admin/yara-rules", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function patchYaraRule(
  ruleId: string,
  patch: { enabled?: boolean; name?: string; family?: string },
): Promise<YaraRuleRead> {
  const res = await _apiFetch(`/api/admin/yara-rules/${ruleId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function deleteYaraRule(ruleId: string): Promise<void> {
  const res = await _apiFetch(`/api/admin/yara-rules/${ruleId}`, { method: "DELETE" });
  if (!res.ok) throw new Error(await res.text());
}

export async function upsertSandboxConfig(
  projectId: string,
  body: SandboxConfigCreate,
): Promise<void> {
  const res = await _apiFetch(`/api/projects/${projectId}/sandbox-config`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await res.text());
}

// === Phase 29: Sigma Rule Engine ===

export interface SigmaRuleRead {
  id: string;
  name: string;
  content: string;
  level: string | null;
  tags: string[];
  enabled: boolean;
  project_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface SigmaRuleCreate {
  name: string;
  content: string;
  level?: string | null;
  tags?: string[];
  enabled: boolean;
  project_id?: string | null;
}

export interface SigmaRuleTestResult {
  match_count: number;
  matched_event_ids: string[];
}

export async function listSigmaRules(params?: {
  project_id?: string;
  enabled?: boolean;
}): Promise<SigmaRuleRead[]> {
  const qs = new URLSearchParams();
  if (params?.project_id) qs.set("project_id", params.project_id);
  if (params?.enabled !== undefined) qs.set("enabled", String(params.enabled));
  const res = await _apiFetch(`/api/admin/sigma-rules?${qs}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function createSigmaRule(body: SigmaRuleCreate): Promise<SigmaRuleRead> {
  const res = await _apiFetch("/api/admin/sigma-rules", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function patchSigmaRule(
  ruleId: string,
  patch: { enabled?: boolean; name?: string },
): Promise<SigmaRuleRead> {
  const res = await _apiFetch(`/api/admin/sigma-rules/${ruleId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function deleteSigmaRule(ruleId: string): Promise<void> {
  const res = await _apiFetch(`/api/admin/sigma-rules/${ruleId}`, { method: "DELETE" });
  if (!res.ok) throw new Error(await res.text());
}

export async function testSigmaRule(body: {
  rule_yaml: string;
  project_id: string | null;
}): Promise<SigmaRuleTestResult> {
  const res = await _apiFetch("/api/admin/sigma-rules/test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ---------------------------------------------------------------------------
// Cases (Phase 31 — CASE-01..05)
// ---------------------------------------------------------------------------

export interface CaseRow {
  id: string;
  project_id: string;
  title: string;
  status: "open" | "in_progress" | "on_hold" | "resolved" | "closed";
  severity: "low" | "medium" | "high" | "critical" | null;
  assignee_user_sub: string | null;
  description: string | null;
  summary_md: string | null;
  opened_at: string;
  closed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface CaseListResponse {
  items: CaseRow[];
  total: number;
}

export interface CaseEvidenceEvent {
  case_id: string;
  event_id: string;
  attached_at: string;
  attached_by: string | null;
}

export interface CaseEvidenceIOC {
  case_id: string;
  ioc_id: string;
  attached_at: string;
  attached_by: string | null;
}

export async function listCases(
  projectId: string,
  params?: { status?: string; severity?: string; assignee_user_sub?: string; limit?: number; offset?: number }
): Promise<CaseListResponse> {
  const sp = new URLSearchParams();
  if (params?.status) sp.set("status", params.status);
  if (params?.severity) sp.set("severity", params.severity);
  if (params?.assignee_user_sub) sp.set("assignee_user_sub", params.assignee_user_sub);
  if (params?.limit) sp.set("limit", String(params.limit));
  if (params?.offset) sp.set("offset", String(params.offset));
  const qs = sp.toString() ? `?${sp.toString()}` : "";
  const res = await fetch(`/api/projects/${projectId}/cases${qs}`);
  if (!res.ok) throw new Error(`listCases failed: ${res.status}`);
  return res.json();
}

export async function createCase(
  projectId: string,
  body: { title: string; severity?: string | null; description?: string | null; assignee_user_sub?: string | null }
): Promise<CaseRow> {
  const res = await fetch(`/api/projects/${projectId}/cases`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`createCase failed: ${res.status}`);
  return res.json();
}

export async function patchCase(
  projectId: string,
  caseId: string,
  body: Partial<{ title: string; status: string; severity: string | null; assignee_user_sub: string | null; description: string | null }>
): Promise<CaseRow> {
  const res = await fetch(`/api/projects/${projectId}/cases/${caseId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`patchCase failed: ${res.status}`);
  return res.json();
}

export async function deleteCase(projectId: string, caseId: string): Promise<void> {
  const res = await fetch(`/api/projects/${projectId}/cases/${caseId}`, { method: "DELETE" });
  if (!res.ok && res.status !== 204) throw new Error(`deleteCase failed: ${res.status}`);
}

export async function attachEvents(
  projectId: string, caseId: string, eventIds: string[]
): Promise<{ attached: number }> {
  const res = await fetch(`/api/projects/${projectId}/cases/${caseId}/events`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event_ids: eventIds }),
  });
  if (!res.ok) throw new Error(`attachEvents failed: ${res.status}`);
  return res.json();
}

export async function detachEvent(
  projectId: string, caseId: string, eventId: string
): Promise<void> {
  const res = await fetch(`/api/projects/${projectId}/cases/${caseId}/events/${eventId}`, { method: "DELETE" });
  if (!res.ok && res.status !== 204) throw new Error(`detachEvent failed: ${res.status}`);
}

export async function getCaseEvents(
  projectId: string, caseId: string, params?: { limit?: number; offset?: number }
): Promise<CaseEvidenceEvent[]> {
  const sp = new URLSearchParams();
  if (params?.limit) sp.set("limit", String(params.limit));
  if (params?.offset) sp.set("offset", String(params.offset));
  const qs = sp.toString() ? `?${sp.toString()}` : "";
  const res = await fetch(`/api/projects/${projectId}/cases/${caseId}/events${qs}`);
  if (!res.ok) throw new Error(`getCaseEvents failed: ${res.status}`);
  return res.json();
}

export async function attachIOCs(
  projectId: string, caseId: string, iocIds: string[]
): Promise<{ attached: number }> {
  const res = await fetch(`/api/projects/${projectId}/cases/${caseId}/iocs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ioc_ids: iocIds }),
  });
  if (!res.ok) throw new Error(`attachIOCs failed: ${res.status}`);
  return res.json();
}

export async function detachIOC(
  projectId: string, caseId: string, iocId: string
): Promise<void> {
  const res = await fetch(`/api/projects/${projectId}/cases/${caseId}/iocs/${iocId}`, { method: "DELETE" });
  if (!res.ok && res.status !== 204) throw new Error(`detachIOC failed: ${res.status}`);
}

export async function getCaseIOCs(
  projectId: string, caseId: string, params?: { limit?: number; offset?: number }
): Promise<CaseEvidenceIOC[]> {
  const sp = new URLSearchParams();
  if (params?.limit) sp.set("limit", String(params.limit));
  if (params?.offset) sp.set("offset", String(params.offset));
  const qs = sp.toString() ? `?${sp.toString()}` : "";
  const res = await fetch(`/api/projects/${projectId}/cases/${caseId}/iocs${qs}`);
  if (!res.ok) throw new Error(`getCaseIOCs failed: ${res.status}`);
  return res.json();
}

export interface CaseActivityEntry {
  id: string;
  action: string;
  user_sub: string | null;
  time: string;
  after_jsonb: Record<string, unknown> | null;
}

export async function getCase(projectId: string, caseId: string): Promise<CaseRow> {
  const res = await fetch(`/api/projects/${projectId}/cases/${caseId}`);
  if (!res.ok) throw new Error(`getCase failed: ${res.status}`);
  return res.json();
}

export async function getCaseActivity(
  projectId: string, caseId: string
): Promise<CaseActivityEntry[]> {
  const res = await fetch(`/api/projects/${projectId}/cases/${caseId}/activity`);
  if (!res.ok) throw new Error(`getCaseActivity failed: ${res.status}`);
  return res.json();
}

export async function summariseCase(
  projectId: string, caseId: string
): Promise<{ status: string }> {
  const res = await fetch(`/api/projects/${projectId}/cases/${caseId}/summarise`, { method: "POST" });
  if (!res.ok) throw new Error(`summariseCase failed: ${res.status}`);
  return res.json();
}

export async function regenerateCaseSummary(
  projectId: string, caseId: string
): Promise<{ status: string }> {
  const res = await fetch(`/api/projects/${projectId}/cases/${caseId}/summarise/regenerate`, { method: "POST" });
  if (!res.ok) throw new Error(`regenerateCaseSummary failed: ${res.status}`);
  return res.json();
}
