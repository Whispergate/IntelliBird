// Server-side fetch helper. Uses the compose-internal API_BASE when running
// inside the web container; falls back to localhost for local dev.
export type SystemStatus = {
  auth_enabled: boolean;
  host: string;
  host_loopback_only: boolean;
  version: string;
  warning: string | null;
};

// Browser: use relative URLs → Next.js Route Handler at /api/[...path] proxies
// to BACKEND_URL at request time (same-origin, no CORS). Server: use
// compose-internal API_BASE to talk directly to backend inside Docker.
const API_BASE =
  typeof window === "undefined"
    ? process.env.API_BASE ??
      process.env.NEXT_PUBLIC_API_BASE ??
      "http://api:8000"
    : "";

export async function fetchSystemStatus(): Promise<SystemStatus | null> {
  try {
    const res = await fetch(`${API_BASE}/api/system/status`, {
      cache: "no-store",
    });
    if (!res.ok) return null;
    return (await res.json()) as SystemStatus;
  } catch {
    return null;
  }
}

export type FeedType = "rss" | "taxii" | "nvd";
export type ArchivePolicy = "keep" | "drop" | "move-to-cold";

export type Source = {
  id: string;
  name: string;
  feed_type: FeedType;
  url: string;
  poll_interval_sec: number;
  hot_retention_days: number;
  archive_policy: ArchivePolicy;
  enabled: boolean;
  last_polled_at: string | null;
  last_status: string | null;
  consecutive_failures: number;
  silent_failure_count: number;
  effective_status: string | null;
  created_at: string;
};

export type CreateSourcePayload = {
  name: string;
  feed_type: FeedType;
  url: string;
  credentials?: Record<string, string> | null;
  poll_interval_sec: number;
  hot_retention_days: number;
  archive_policy: ArchivePolicy;
  enabled: boolean;
};

export type UpdateSourcePayload = {
  name?: string;
  url?: string;
  credentials?: Record<string, string> | null; // absent/null → keep existing
  poll_interval_sec?: number;
  hot_retention_days?: number;
  archive_policy?: ArchivePolicy;
  enabled?: boolean;
};

export type EventCount = { count: number };

async function _handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status} ${res.statusText}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export async function fetchSources(): Promise<Source[]> {
  const res = await fetch(`${API_BASE}/api/admin/sources`, { cache: "no-store" });
  return _handle<Source[]>(res);
}

export async function fetchSource(id: string): Promise<Source> {
  const res = await fetch(`${API_BASE}/api/admin/sources/${id}`, { cache: "no-store" });
  return _handle<Source>(res);
}

export async function createSource(payload: CreateSourcePayload): Promise<Source> {
  const res = await fetch(`${API_BASE}/api/admin/sources`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store",
  });
  return _handle<Source>(res);
}

export async function updateSource(id: string, payload: UpdateSourcePayload): Promise<Source> {
  const res = await fetch(`${API_BASE}/api/admin/sources/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store",
  });
  return _handle<Source>(res);
}

export async function deleteSource(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/admin/sources/${id}`, {
    method: "DELETE",
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status} ${res.statusText}: ${text}`);
  }
}

export async function getSourceEventCount(id: string): Promise<EventCount> {
  const res = await fetch(`${API_BASE}/api/admin/sources/${id}/event-count`, { cache: "no-store" });
  return _handle<EventCount>(res);
}

export type TestConnectionPayload = {
  feed_type: FeedType;
  url: string;
  credentials?: Record<string, string> | null;
};

export type TestConnectionResult = {
  ok: boolean;
  latency_ms: number;
  item_count_sampled: number;
  error_detail: string | null;
};

export async function testConnection(
  payload: TestConnectionPayload,
): Promise<TestConnectionResult> {
  const res = await fetch(`${API_BASE}/api/admin/sources/test-connection`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store",
  });
  return _handle<TestConnectionResult>(res);
}

// Preconfigured source templates (operator quick-add)
export type CredentialField = {
  key: string;
  label: string;
  type: "password" | "text";
  required: boolean;
  placeholder?: string | null;
};

export type SourceTemplate = {
  id: string;
  name: string;
  feed_type: FeedType;
  url: string;
  description: string;
  auth_scheme: string | null;
  credential_fields: CredentialField[];
  poll_interval_sec: number;
  docs_url: string | null;
};

export async function fetchSourceTemplates(): Promise<SourceTemplate[]> {
  const res = await fetch(`${API_BASE}/api/admin/source-templates`, { cache: "no-store" });
  return _handle<SourceTemplate[]>(res);
}

// ============================================================
// Phase 4 query API — FIL-01..05, FIL-03, FIL-04
// ============================================================

export type TlpName = "clear" | "green" | "amber" | "amber+strict" | "red";
export type Visibility = "shared" | "red_only" | "blue_only";
export type DashboardRole = "red" | "blue";

export type EventItem = {
  id: string;
  observed_at: string;
  fetched_at: string;
  source_id: string | null;
  source_name: string | null;
  source_type: FeedType | null;
  stix_id: string | null;
  stix_type: string;
  title: string | null;
  description: string | null;
  tlp: TlpName | null;
  tags: string[];
  attack_techniques: string[];
  archived: boolean;
  visibility: Visibility;
  geo_lat: number | null;
  geo_lon: number | null;
};

export type EventDetail = EventItem & { raw_stix: Record<string, unknown> | null };

export type EventListResponse = {
  items: EventItem[];
  next_cursor: string | null;
  total: number | null;
};

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
  cursor?: string;
  limit?: number;
  has_geo?: boolean;
  tag_mode?: "any" | "all";
};

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

export async function listEvents(
  query: EventsQuery = {},
  role?: DashboardRole,
): Promise<EventListResponse> {
  const res = await fetch(`${API_BASE}/api/events${_buildQuery(query)}`, {
    cache: "no-store",
    headers: _roleHeaders(role),
  });
  return _handle<EventListResponse>(res);
}

export async function getEvent(id: string, role?: DashboardRole): Promise<EventDetail> {
  const res = await fetch(`${API_BASE}/api/events/${id}`, {
    cache: "no-store",
    headers: _roleHeaders(role),
  });
  return _handle<EventDetail>(res);
}

export type TagPatchPayload = { add: string[]; remove: string[] };
export type TagPatchResponse = { tags: string[] };

export async function patchEventTags(
  id: string,
  payload: TagPatchPayload,
): Promise<TagPatchResponse> {
  const res = await fetch(`${API_BASE}/api/events/${id}/tags`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store",
  });
  return _handle<TagPatchResponse>(res);
}

export type GraphNode = { data: { id: string; label: string; type: string; tag_source?: string } };
export type GraphEdge = { data: { source: string; target: string; relation: string } };
export type GraphResponse = { nodes: GraphNode[]; edges: GraphEdge[]; truncated: boolean };

export async function getEventGraph(
  id: string,
  depth: 1 | 2 | 3 = 2,
  role?: DashboardRole,
): Promise<GraphResponse> {
  const res = await fetch(`${API_BASE}/api/events/${id}/graph?depth=${depth}`, {
    cache: "no-store",
    headers: _roleHeaders(role),
  });
  return _handle<GraphResponse>(res);
}

export type FilterPreset = {
  id: string;
  name: string;
  query_params: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export async function listPresets(): Promise<FilterPreset[]> {
  const res = await fetch(`${API_BASE}/api/presets`, { cache: "no-store" });
  return _handle<FilterPreset[]>(res);
}

export async function getPreset(name: string): Promise<FilterPreset> {
  const res = await fetch(`${API_BASE}/api/presets/${encodeURIComponent(name)}`, {
    cache: "no-store",
  });
  return _handle<FilterPreset>(res);
}

export async function createPreset(
  name: string,
  query_params: Record<string, unknown>,
): Promise<FilterPreset> {
  const res = await fetch(`${API_BASE}/api/presets`, {
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
  const res = await fetch(`${API_BASE}/api/presets/${encodeURIComponent(name)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query_params }),
    cache: "no-store",
  });
  return _handle<FilterPreset>(res);
}

export async function deletePreset(name: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/presets/${encodeURIComponent(name)}`, {
    method: "DELETE",
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status} ${res.statusText}: ${text}`);
  }
}

// ============================================================
// Phase 7 webhook alerts — HOOK-01, HOOK-02, HOOK-06, HOOK-09
// ============================================================

export type DestinationType = "slack" | "teams" | "discord" | "generic";
export type DeliveryStatus = "ok" | "http_error" | "network_error" | "timeout" | null;

export type WebhookAuth =
  | { type: "bearer"; token: string }
  | { type: "basic"; username: string; password: string }
  | { type: "header"; name: string; value: string };

export type Webhook = {
  id: string;
  name: string;
  destination_type: DestinationType;
  url: string;
  // auth deliberately absent — never returned in plaintext (SRC-04 parallel)
  batching_window_sec: number;
  enabled: boolean;
  last_dispatch_at: string | null;
  last_delivery_at: string | null;
  last_delivery_status: DeliveryStatus;
  consecutive_failures: number;
  bound_preset_names: string[];
  created_at: string;
  updated_at: string;
};

export type CreateWebhookPayload = {
  name: string;
  destination_type: DestinationType;
  url: string;
  auth?: WebhookAuth | null;
  batching_window_sec: number; // one of 0, 60, 300, 900, 1800
  bound_preset_names: string[];
  enabled: boolean;
};

export type UpdateWebhookPayload = {
  name?: string;
  url?: string;
  auth?: WebhookAuth | null;
  clear_auth?: boolean;
  batching_window_sec?: number;
  bound_preset_names?: string[];
  enabled?: boolean;
  // destination_type DELIBERATELY ABSENT — locked on edit (D-35)
};

export type TestWebhookPayload = {
  destination_type: DestinationType;
  url: string;
  auth?: WebhookAuth | null;
};

export type TestWebhookResult = {
  ok: boolean;
  latency_ms: number;
  error_detail: string | null;
};

export async function listWebhooks(): Promise<Webhook[]> {
  const res = await fetch(`${API_BASE}/api/admin/webhooks`, { cache: "no-store" });
  return _handle<Webhook[]>(res);
}

export async function createWebhook(payload: CreateWebhookPayload): Promise<Webhook> {
  const res = await fetch(`${API_BASE}/api/admin/webhooks`, {
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
  const res = await fetch(`${API_BASE}/api/admin/webhooks/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store",
  });
  return _handle<Webhook>(res);
}

export async function deleteWebhook(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/admin/webhooks/${id}`, {
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
  const res = await fetch(`${API_BASE}/api/admin/webhooks/test-send`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store",
  });
  return _handle<TestWebhookResult>(res);
}
