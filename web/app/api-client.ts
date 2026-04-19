// Server-side fetch helper. Uses the compose-internal API_BASE when running
// inside the web container; falls back to localhost for local dev.
import type { components } from "./api-client.generated";

// ============================================================
// Enum types extracted from generated schema
// (These types are inlined in schema objects — no standalone OpenAPI schemas for them)
// ============================================================

export type FeedType = components["schemas"]["SourceResponse"]["feed_type"];
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
export type Source = components["schemas"]["SourceResponse"];
export type CreateSourcePayload = components["schemas"]["SourceCreate"];
export type UpdateSourcePayload = components["schemas"]["SourceUpdate"];
export type TestConnectionPayload = components["schemas"]["TestConnectionRequest"];
export type TestConnectionResult = components["schemas"]["TestConnectionResponse"];
export type CredentialField = components["schemas"]["CredentialField"];
export type SourceTemplate = components["schemas"]["SourceTemplate"];

// EventItem: override optional fields to required (callers depend on required shapes;
// generated schema marks source_name, source_type, tlp, tags, attack_techniques as optional)
export type EventItem = Omit<
  components["schemas"]["EventItem"],
  "tlp" | "attack_techniques" | "tags" | "source_name" | "source_type"
> & {
  tlp: TlpName | null;
  attack_techniques: string[];
  tags: string[];
  source_name: string | null;
  source_type: FeedType | null;
};

// EventDetail: same field overrides as EventItem plus raw_stix
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
// to BACKEND_URL at request time (same-origin, no CORS). Server: use
// compose-internal API_BASE to talk directly to backend inside Docker.
const API_BASE =
  typeof window === "undefined"
    ? process.env.API_BASE ??
      process.env.NEXT_PUBLIC_API_BASE ??
      "http://api:8000"
    : "";

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
    const res = await fetch(`${API_BASE}/api/system/status`, {
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
export async function fetchSourceTemplates(): Promise<SourceTemplate[]> {
  const res = await fetch(`${API_BASE}/api/admin/source-templates`, { cache: "no-store" });
  return _handle<SourceTemplate[]>(res);
}

// ============================================================
// Events — FIL-01..05, FIL-03, FIL-04
// ============================================================

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

// ============================================================
// Filter presets — FIL-05
// ============================================================

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
// Webhook alerts — HOOK-01, HOOK-02, HOOK-06, HOOK-09
// ============================================================

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
