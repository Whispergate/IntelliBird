"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { useSession } from "next-auth/react";
import { toast } from "sonner";

import {
  listEvents,
  listPresets,
  type EventItem,
  type EventsQuery,
  type FilterPreset,
  type TlpName,
  type FeedType,
} from "@/app/api-client";
import { EventDetailDrawer } from "@/app/components/EventDetailDrawer";
import { TierBadge } from "@/app/components/TierBadge";
import { RoleProvider } from "@/app/lib/role-context";
import { type Tier, TIER_COLORS, classifyTier } from "@/lib/scoring";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { FilterChips } from "./components/FilterChips";
import { EventsTable } from "./components/EventsTable";
import { AttachToCaseModal } from "./components/AttachToCaseModal";

// ---------------------------------------------------------------------------
// BrandProvenanceBadge - rendered in EventsTable when event.source_type === 'brand-monitor'.
//
// Per 12-UI-SPEC §Surface 7:
//   - Height 16px (h-4), horizontal padding 8px (px-2)
//   - Signal-amber left-border (border-l-2 border-[var(--brand-signal)])
//   - Background colour dispatches on first matching brand-match:<source> tag:
//       * brand-match:dnstwist → bg-orange-500/20 text-orange-300
//       * brand-match:ct_log   → bg-teal-900/40  text-teal-300
//       * brand-match:fts      → bg-muted        text-muted-foreground
//       * fallback             → bg-accent/20    text-[var(--brand-signal)]
//   - Tooltip: "Brand match - {match_source} - /projects/{project_id}/brand"
//     match_source extracted from first brand-match:* tag
//     project_id extracted from project:<uuid> tag
//
// Co-located here (not in EventsTable.tsx) to keep Surface 7 logic adjacent to
// the include_brand_match toggle state - mirrors the BBOT precedent where all
// provenance logic lives near the feed-level Switch owner.
// ---------------------------------------------------------------------------
export function BrandProvenanceBadge({ event }: { event: EventItem }) {
  // Guard: only render for source_type === 'brand-monitor'.
  if (event.source_type !== "brand-monitor") return null;

  // Extract first brand-match:<source> tag - drives both colour + tooltip text.
  const matchTag = event.tags.find((t) => t.startsWith("brand-match:"));
  const matchSource = matchTag ? matchTag.slice("brand-match:".length) : "unknown";

  // Extract project UUID from project:<uuid> tag (EventItem has no project_id field
  // in the generated schema; project binding is tag-encoded per ingest contract).
  const projectTag = event.tags.find((t) => t.startsWith("project:"));
  const projectId = projectTag ? projectTag.slice("project:".length) : "";

  // Background colour dispatch per 12-UI-SPEC §Surface 7.
  const bgClass =
    matchSource === "dnstwist"
      ? "bg-orange-500/20 text-orange-300"
      : matchSource === "ct_log"
        ? "bg-teal-900/40 text-teal-300"
        : matchSource === "fts"
          ? "bg-muted text-muted-foreground"
          : "bg-accent/20 text-[var(--brand-signal)]";

  const tooltip = `Brand match - ${matchSource} - /projects/${projectId}/brand`;

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            className={`inline-flex items-center h-4 px-2 border-l-2 border-[var(--brand-signal)] text-[12px] font-medium uppercase tracking-[0.15em] rounded-sm ${bgClass}`}
          >
            Brand
          </span>
        </TooltipTrigger>
        <TooltipContent>{tooltip}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

// ---------------------------------------------------------------------------
// Sort value helpers - maps between Select value (hyphens) and URL param (underscores)
// ---------------------------------------------------------------------------

type SortValue = "observed_desc" | "score_desc" | "score_asc";

/** Map from URL param string to Select internal value */
const URL_TO_SORT: Record<string, SortValue> = {
  observed_desc: "observed_desc",
  score_desc: "score_desc",
  score_asc: "score_asc",
};

/** Map from Select internal value to URL param string */
const SORT_TO_URL: Record<SortValue, string> = {
  observed_desc: "observed_desc",
  score_desc: "score_desc",
  score_asc: "score_asc",
};

// ---------------------------------------------------------------------------
// URL ↔ filter helpers
// ---------------------------------------------------------------------------

function parseFiltersFromSearchParams(sp: URLSearchParams): EventsQuery {
  const out: EventsQuery = {};

  // preset JSON blob - merged in first so explicit params can override
  const preset = sp.get("preset");
  if (preset) {
    try {
      Object.assign(out, JSON.parse(decodeURIComponent(preset)));
    } catch {
      // malformed preset - ignore
    }
  }

  const tlps = sp.getAll("tlp");
  if (tlps.length) out.tlp = tlps as TlpName[];

  const sources = sp.getAll("source");
  if (sources.length) out.source = sources;

  const tags = sp.getAll("tag");
  if (tags.length) out.tag = tags;

  const sourceTypes = sp.getAll("source_type");
  if (sourceTypes.length) out.source_type = sourceTypes as FeedType[];

  const from = sp.get("observed_from");
  if (from) out.observed_from = from;

  const to = sp.get("observed_to");
  if (to) out.observed_to = to;

  return out;
}

function buildSearchParams(
  filter: EventsQuery,
  sort?: SortValue,
  tiers?: Set<Tier>,
): URLSearchParams {
  const params = new URLSearchParams();
  for (const tlp of filter.tlp ?? []) params.append("tlp", tlp);
  for (const src of filter.source ?? []) params.append("source", src);
  for (const tag of filter.tag ?? []) params.append("tag", tag);
  for (const st of filter.source_type ?? []) params.append("source_type", st);
  if (filter.observed_from) params.set("observed_from", filter.observed_from);
  if (filter.observed_to) params.set("observed_to", filter.observed_to);
  if (sort && sort !== "observed_desc") params.set("sort", SORT_TO_URL[sort]);
  if (tiers && tiers.size > 0) params.set("tier", Array.from(tiers).join(","));
  return params;
}

// ---------------------------------------------------------------------------
// EventsClient
// ---------------------------------------------------------------------------

export interface EventsClientProps {
  projectId?: string;
  projectName?: string;
  basePath?: string;
}

export function EventsClient({ projectId, projectName, basePath }: EventsClientProps = {}) {
  // projectId / projectName / basePath are accepted for /projects/[id]/intel route.
  // Full project-scoping (URL pinning, fetch threading, source-bound check) wired
  // by plan 10-12; this signature ensures the page.tsx call typechecks.
  void projectId;
  void projectName;
  void basePath;
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const { data: _session } = useSession();
  const isAdmin =
    ((_session?.user as { role?: string } | undefined)?.role ?? "") === "Admin";
  const [role, setRole] = useState<"red" | "blue" | undefined>(undefined);
  const [filter, setFilter] = useState<EventsQuery>({});
  const [sortValue, setSortValue] = useState<SortValue>("observed_desc");
  const [selectedTiers, setSelectedTiers] = useState<Set<Tier>>(new Set());
  const [includeBbot, setIncludeBbot] = useState(false);
  // BRP-05: off-by-default toggle that unhides source_type='brand-monitor'
  // events in the main feed. Mirrors includeBbot placement / query-append pattern.
  const [includeBrandMatch, setIncludeBrandMatch] = useState(false);
  // Source-monitoring synthesised alerts (source_silence, volume_drift,
  // parse_error_rate). Admin/lead-only - toggle hidden from analyst+observer.
  const [includeMonitoring, setIncludeMonitoring] = useState(false);
  const [events, setEvents] = useState<EventItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [presets, setPresets] = useState<FilterPreset[]>([]);
  const [selectedPreset, setSelectedPreset] = useState<string>("");
  const [selectedRows, setSelectedRows] = useState<Set<string>>(new Set());
  const [attachToCaseOpen, setAttachToCaseOpen] = useState(false);

  // Resolve role from localStorage
  useEffect(() => {
    try {
      const stored = window.localStorage.getItem("intellibird:last-role") as
        | "red"
        | "blue"
        | null;
      if (stored === "red" || stored === "blue") {
        setRole(stored);
      }
    } catch {
      // localStorage unavailable
    }
  }, []);

  // Load presets on mount
  useEffect(() => {
    listPresets()
      .then((ps) => setPresets(ps))
      .catch(() => {
        // presets unavailable - not fatal
      });
  }, []);

  // Fetch events when searchParams change
  useEffect(() => {
    const parsed = parseFiltersFromSearchParams(searchParams);
    setFilter(parsed);

    // Parse sort from URL - default to observed_desc
    const urlSort = searchParams.get("sort") ?? "observed_desc";
    const resolvedSort: SortValue =
      (URL_TO_SORT[urlSort] as SortValue | undefined) ?? "observed_desc";
    setSortValue(resolvedSort);

    // Parse tier filter from URL - comma-separated e.g. "S,A"
    const urlTier = searchParams.get("tier");
    if (urlTier) {
      const tierSet = new Set<Tier>(
        urlTier.split(",").filter((t): t is Tier =>
          (["S", "A", "B", "C", "D"] as string[]).includes(t),
        ),
      );
      setSelectedTiers(tierSet);
    } else {
      setSelectedTiers(new Set());
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    // Build API query - include sort + tier params when set
    const tierParam = urlTier ?? "";
    const apiSort = urlSort !== "observed_desc" ? urlSort : undefined;

    listEvents(
      {
        ...parsed,
        limit: parsed.limit ?? 50,
        ...(includeBbot ? { include_bbot: true } : {}),
        ...(includeBrandMatch ? ({ include_brand_match: true } as Partial<EventsQuery>) : {}),
        ...(includeMonitoring ? ({ include_monitoring: true } as Partial<EventsQuery>) : {}),
        ...(apiSort ? ({ sort: apiSort } as Partial<EventsQuery>) : {}),
        ...(tierParam ? ({ tier: tierParam } as Partial<EventsQuery>) : {}),
      },
      role,
    )
      .then((res) => {
        if (!cancelled) {
          setEvents(res.items);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
          setLoading(false);
          toast.error("Failed to load events.");
        }
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams, role, includeBbot, includeBrandMatch, includeMonitoring]);

  // ---------------------------------------------------------------------------
  // URL manipulation helpers
  // ---------------------------------------------------------------------------

  function resetFilters() {
    setSelectedPreset("");
    router.replace("/events");
  }

  function applyPreset(preset: FilterPreset) {
    const merged: EventsQuery = { ...(preset.query_params as EventsQuery) };
    const params = buildSearchParams(merged, sortValue, selectedTiers);
    const qs = params.toString();
    router.replace(qs ? `/events?${qs}` : "/events");
  }

  function addTagFilter(tag: string) {
    const current = parseFiltersFromSearchParams(searchParams);
    const existing = (current.tag as string[] | undefined) ?? [];
    if (existing.includes(tag)) return;
    current.tag = [...existing, tag];
    const eventId = searchParams.get("event");
    const params = buildSearchParams(current, sortValue, selectedTiers);
    if (eventId) params.set("event", eventId);
    const qs = params.toString();
    router.replace(qs ? `/events?${qs}` : "/events");
  }

  function removeFilter(key: keyof EventsQuery, value?: string) {
    const current = parseFiltersFromSearchParams(searchParams);

    if (value !== undefined && Array.isArray(current[key])) {
      const arr = (current[key] as string[]).filter((v) => v !== value);
      if (arr.length === 0) {
        delete current[key];
      } else {
        (current as Record<string, unknown>)[key] = arr;
      }
    } else {
      delete current[key];
    }

    // Preserve ?event= param if present
    const eventId = searchParams.get("event");
    const params = buildSearchParams(current, sortValue, selectedTiers);
    if (eventId) params.set("event", eventId);
    const qs = params.toString();
    router.replace(qs ? `/events?${qs}` : "/events");
  }

  function handleRowClick(id: string) {
    const params = buildSearchParams(filter, sortValue, selectedTiers);
    params.set("event", encodeURIComponent(id));
    router.replace(`/events?${params.toString()}`);
  }

  function handleDateChange(key: "observed_from" | "observed_to", value: string) {
    const current = parseFiltersFromSearchParams(searchParams);
    if (value) {
      current[key] = value;
    } else {
      delete current[key];
    }
    const eventId = searchParams.get("event");
    const params = buildSearchParams(current, sortValue, selectedTiers);
    if (eventId) params.set("event", eventId);
    const qs = params.toString();
    router.replace(qs ? `/events?${qs}` : "/events");
  }

  function toggleRowSelection(id: string) {
    setSelectedRows((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  function handleSortChange(newSort: string) {
    const resolved = (URL_TO_SORT[newSort] ?? "observed_desc") as SortValue;
    setSortValue(resolved);
    const current = parseFiltersFromSearchParams(searchParams);
    const eventId = searchParams.get("event");
    const params = buildSearchParams(current, resolved, selectedTiers);
    if (eventId) params.set("event", eventId);
    const qs = params.toString();
    router.replace(qs ? `/events?${qs}` : "/events");
  }

  function toggleTier(tier: Tier) {
    const next = new Set(selectedTiers);
    if (next.has(tier)) {
      next.delete(tier);
    } else {
      next.add(tier);
    }
    setSelectedTiers(next);
    const current = parseFiltersFromSearchParams(searchParams);
    const eventId = searchParams.get("event");
    const params = buildSearchParams(current, sortValue, next);
    if (eventId) params.set("event", eventId);
    const qs = params.toString();
    router.replace(qs ? `/events?${qs}` : "/events");
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const hasFilters =
    (filter.tlp?.length ?? 0) > 0 ||
    (filter.source?.length ?? 0) > 0 ||
    (filter.tag?.length ?? 0) > 0 ||
    (filter.source_type?.length ?? 0) > 0 ||
    !!filter.observed_from ||
    !!filter.observed_to ||
    selectedTiers.size > 0;

  const hasTierFilter = selectedTiers.size > 0;
  const showEmpty = !loading && !error && events.length === 0;
  const showError = !loading && !!error;

  return (
    <RoleProvider value={role ?? "blue"}>
      {/* Page header*/}
      <div style={{ marginBottom: "1rem" }}>
        <h1 className="brand-display text-foreground">Events</h1>
        <p className="text-muted-foreground mt-1" style={{ fontSize: 16 }}>
          All ingested intel events - filter, tag, and drill in.
        </p>
      </div>

      {/* Quick tag filters - click to add to filter set*/}
      <div style={{ marginBottom: "0.75rem" }} className="flex flex-col gap-1">
        <span className="brand-caption text-[10px] text-muted-foreground" style={{ letterSpacing: "0.12em" }}>
          Quick filters
        </span>
        <div className="flex flex-wrap gap-1" data-testid="quick-tag-filters">
          {[
            "critical", "high-severity", "apt", "ransomware", "exploit",
            "vulnerability", "ioc", "actor", "c2", "phishing", "tooling",
            "vendor-advisory",
          ].map((t) => {
            const active = (filter.tag ?? []).includes(t);
            return (
              <button
                key={t}
                type="button"
                onClick={() => (active ? removeFilter("tag", t) : addTagFilter(t))}
                data-testid={`quick-tag-${t}`}
                className="brand-caption inline-flex items-center rounded-md border px-2 py-0.5 hover:opacity-90 cursor-pointer text-[11px]"
                style={{
                  borderColor: active ? "#EF9F27" : "#0F6E56",
                  backgroundColor: active
                    ? "rgba(239, 159, 39, 0.15)"
                    : "transparent",
                  color: active ? "#EF9F27" : "#888780",
                  borderStyle: active ? "solid" : "dashed",
                }}
              >
                {active ? "✓ " : "+"}{t}
              </button>
            );
          })}
        </div>
      </div>

      {/* Tier filter chip row - multi-select, OR semantics, URL-synced via ?tier=S,A */}
      <div style={{ marginBottom: "1.5rem" }} className="flex flex-col gap-1" data-testid="tier-filter-row">
        <span className="brand-caption text-muted-foreground" style={{ letterSpacing: "0.12em" }}>
          Tier
        </span>
        <div className="flex flex-wrap gap-1" data-testid="tier-chips">
          {(["S", "A", "B", "C", "D"] as const).map((tier) => {
            const active = selectedTiers.has(tier);
            const colors = TIER_COLORS[tier];
            return (
              <button
                key={tier}
                type="button"
                onClick={() => toggleTier(tier)}
                data-testid={`tier-chip-${tier}`}
                aria-pressed={active}
                className="brand-caption inline-flex items-center rounded-md border px-2 py-1 cursor-pointer text-xs"
                style={
                  active
                    ? {
                        borderStyle: "solid",
                        // inline hex equivalents matching TIER_COLORS Tailwind class tokens
                        borderColor:
                          tier === "S" ? "#ef4444"
                          : tier === "A" ? "#f97316"
                          : tier === "B" ? "#eab308"
                          : tier === "C" ? "#60a5fa"
                          : "#888780",
                      }
                    : {
                        borderColor: "#0F6E56",
                        backgroundColor: "transparent",
                        color: "#888780",
                        borderStyle: "dashed",
                      }
                }
              >
                {active ? (
                  <TierBadge tier={tier} />
                ) : (
                  tier
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* Filter row*/}
      <div
        className="flex flex-wrap items-center gap-3"
        style={{ marginBottom: "1.5rem" }}
      >
        {/* Filter chips*/}
        <FilterChips activeFilters={filter} onRemove={removeFilter} />

        {/* Date range inputs*/}
        <div className="flex items-center gap-2">
          <label className="brand-caption text-muted-foreground" htmlFor="events-from">
            From
          </label>
          <input
            id="events-from"
            type="date"
            value={filter.observed_from ?? ""}
            onChange={(e) => handleDateChange("observed_from", e.target.value)}
            className="h-8 rounded border border-input bg-transparent px-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
          />
        </div>
        <div className="flex items-center gap-2">
          <label className="brand-caption text-muted-foreground" htmlFor="events-to">
            To
          </label>
          <input
            id="events-to"
            type="date"
            value={filter.observed_to ?? ""}
            onChange={(e) => handleDateChange("observed_to", e.target.value)}
            className="h-8 rounded border border-input bg-transparent px-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
          />
        </div>

        {/* Sort selector - includes score sort options per UI-SPEC §Surface 2 */}
        <div style={{ width: 180 }}>
          <Select
            value={sortValue}
            onValueChange={handleSortChange}
          >
            <SelectTrigger aria-label="Sort events" className="h-8 text-sm">
              <SelectValue placeholder="Sort by..." />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="observed_desc">Newest first</SelectItem>
              <SelectItem value="score_desc">Score: High → Low</SelectItem>
              <SelectItem value="score_asc">Score: Low → High</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* Preset selector*/}
        <div style={{ width: 200 }}>
          <Select
            value={selectedPreset}
            onValueChange={(val) => {
              setSelectedPreset(val);
              const preset = presets.find((p) => p.id === val);
              if (preset) applyPreset(preset);
            }}
          >
            <SelectTrigger aria-label="Load preset" className="h-8 text-sm">
              <SelectValue placeholder="Load preset..." />
            </SelectTrigger>
            <SelectContent>
              {presets.map((p) => (
                <SelectItem key={p.id} value={p.id}>
                  {p.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* Reset / clear all filters*/}
        {hasFilters && (
          <Button
            variant="ghost"
            size="sm"
            className="ml-auto"
            onClick={resetFilters}
            aria-label="Clear filters"
          >
            Clear filters
          </Button>
        )}
      </div>

      {/* Multi-select toolbar - appears when ≥1 row selected */}
      {selectedRows.size >= 1 && (
        <div className="flex items-center gap-3 px-3 py-2 rounded-md bg-muted/50 border border-border mb-2">
          <span className="text-sm text-muted-foreground">
            {selectedRows.size} event{selectedRows.size === 1 ? "" : "s"} selected
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setAttachToCaseOpen(true)}
          >
            Attach to Case
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setSelectedRows(new Set())}
            className="ml-auto"
          >
            Clear selection
          </Button>
        </div>
      )}

      {/* include_bbot toggle - off by default; keeps main events feed clean (H-4) */}
      <div className="flex items-center justify-end gap-2 mt-2 mb-2">
        <Label htmlFor="include-bbot" className="text-sm text-muted-foreground cursor-pointer">
          Include BBOT findings
        </Label>
        <Switch
          id="include-bbot"
          checked={includeBbot}
          onCheckedChange={setIncludeBbot}
        />
      </div>

      {/* include_brand_match toggle - off by default; hides brand-monitor events
          from the main feed until user opts in (BRP-05, 12-UI-SPEC §Surface 7). */}
      <div className="flex items-center justify-end gap-2 mb-4">
        <Label
          htmlFor="include-brand-match"
          className="text-sm text-muted-foreground cursor-pointer"
        >
          Include brand matches
        </Label>
        <Switch
          id="include-brand-match"
          checked={includeBrandMatch}
          onCheckedChange={setIncludeBrandMatch}
        />
      </div>

      {/* include_monitoring toggle - Admin/lead only.
          Synthesised source-monitoring alerts (source_silence, volume_drift,
          parse_error_rate) are noise for analysts; only ops surfaces them. */}
      {isAdmin && (
        <div className="flex items-center justify-end gap-2 mb-4">
          <Label
            htmlFor="include-monitoring"
            className="text-sm text-muted-foreground cursor-pointer"
          >
            Include monitoring alerts
          </Label>
          <Switch
            id="include-monitoring"
            checked={includeMonitoring}
            onCheckedChange={setIncludeMonitoring}
          />
        </div>
      )}

      {/* Events table*/}
      {showError ? (
        <div
          className="flex flex-col items-center justify-center py-16 gap-2"
          data-testid="events-error"
        >
          <h2
            className="brand-heading text-destructive"
            style={{ fontSize: 22, fontWeight: 500 }}
          >
            Could not load events.
          </h2>
          <p className="text-muted-foreground" style={{ fontSize: 16 }}>
            Check the API connection and try again.
          </p>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setError(null);
              setLoading(true);
              const apiSort = sortValue !== "observed_desc" ? sortValue : undefined;
              const tierParam = selectedTiers.size > 0 ? Array.from(selectedTiers).join(",") : undefined;
              listEvents(
                {
                  ...filter,
                  limit: filter.limit ?? 50,
                  ...(includeBbot ? { include_bbot: true } : {}),
                  ...(includeMonitoring
                    ? ({ include_monitoring: true } as Partial<EventsQuery>)
                    : {}),
                  ...(includeBrandMatch
                    ? ({ include_brand_match: true } as Partial<EventsQuery>)
                    : {}),
                  ...(apiSort ? ({ sort: apiSort } as Partial<EventsQuery>) : {}),
                  ...(tierParam ? ({ tier: tierParam } as Partial<EventsQuery>) : {}),
                },
                role,
              )
                .then((res) => {
                  setEvents(res.items);
                  setLoading(false);
                })
                .catch((err: unknown) => {
                  setError(err instanceof Error ? err.message : String(err));
                  setLoading(false);
                });
            }}
          >
            Retry
          </Button>
        </div>
      ) : showEmpty ? (
        <div
          className="flex flex-col items-center justify-center py-16 gap-2"
          data-testid="events-empty"
        >
          <h2
            className="brand-heading text-foreground"
            style={{ fontSize: 22, fontWeight: 500 }}
          >
            {hasTierFilter ? "No events match this tier" : "No events match your filters."}
          </h2>
          <p className="text-muted-foreground" style={{ fontSize: 16 }}>
            {hasTierFilter
              ? "Try removing the tier filter or adjusting score thresholds in the project scoring config."
              : "Try removing a filter or registering additional sources."}
          </p>
          <Button variant="ghost" size="sm" onClick={resetFilters}>
            Clear filters
          </Button>
        </div>
      ) : (
        <EventsTable
          items={events}
          loading={loading}
          onRowClick={handleRowClick}
          selectedRows={selectedRows}
          onToggleRow={toggleRowSelection}
        />
      )}

      {/* Attach to Case modal - opens when "Attach to Case" button clicked */}
      <AttachToCaseModal
        projectId={projectId ?? ""}
        eventIds={Array.from(selectedRows)}
        open={attachToCaseOpen}
        onOpenChange={setAttachToCaseOpen}
        onSuccess={() => setSelectedRows(new Set())}
      />

      {/* Event detail drawer - unconditional mount; opens on ?event=<id>*/}
      <EventDetailDrawer />
    </RoleProvider>
  );
}
