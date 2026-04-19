"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter, usePathname, useSearchParams } from "next/navigation";
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
import { RoleProvider } from "@/app/lib/role-context";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { FilterChips } from "./components/FilterChips";
import { EventsTable } from "./components/EventsTable";

// ---------------------------------------------------------------------------
// URL ↔ filter helpers
// ---------------------------------------------------------------------------

function parseFiltersFromSearchParams(sp: URLSearchParams): EventsQuery {
  const out: EventsQuery = {};

  // preset JSON blob — merged in first so explicit params can override
  const preset = sp.get("preset");
  if (preset) {
    try {
      Object.assign(out, JSON.parse(decodeURIComponent(preset)));
    } catch {
      // malformed preset — ignore
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

function buildSearchParams(filter: EventsQuery): URLSearchParams {
  const params = new URLSearchParams();
  for (const tlp of filter.tlp ?? []) params.append("tlp", tlp);
  for (const src of filter.source ?? []) params.append("source", src);
  for (const tag of filter.tag ?? []) params.append("tag", tag);
  for (const st of filter.source_type ?? []) params.append("source_type", st);
  if (filter.observed_from) params.set("observed_from", filter.observed_from);
  if (filter.observed_to) params.set("observed_to", filter.observed_to);
  return params;
}

// ---------------------------------------------------------------------------
// EventsClient
// ---------------------------------------------------------------------------

export function EventsClient() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const [role, setRole] = useState<"red" | "blue" | undefined>(undefined);
  const [filter, setFilter] = useState<EventsQuery>({});
  const [events, setEvents] = useState<EventItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [presets, setPresets] = useState<FilterPreset[]>([]);
  const [selectedPreset, setSelectedPreset] = useState<string>("");

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
        // presets unavailable — not fatal
      });
  }, []);

  // Fetch events when searchParams change
  useEffect(() => {
    const parsed = parseFiltersFromSearchParams(searchParams);
    setFilter(parsed);

    let cancelled = false;
    setLoading(true);
    setError(null);

    listEvents({ ...parsed, limit: parsed.limit ?? 50 }, role)
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
  }, [searchParams, role]);

  // ---------------------------------------------------------------------------
  // URL manipulation helpers
  // ---------------------------------------------------------------------------

  function resetFilters() {
    setSelectedPreset("");
    router.replace("/events");
  }

  function applyPreset(preset: FilterPreset) {
    const merged: EventsQuery = { ...(preset.query_params as EventsQuery) };
    const params = buildSearchParams(merged);
    const qs = params.toString();
    router.replace(qs ? `/events?${qs}` : "/events");
  }

  function addTagFilter(tag: string) {
    const current = parseFiltersFromSearchParams(searchParams);
    const existing = (current.tag as string[] | undefined) ?? [];
    if (existing.includes(tag)) return;
    current.tag = [...existing, tag];
    const eventId = searchParams.get("event");
    const params = buildSearchParams(current);
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
    const params = buildSearchParams(current);
    if (eventId) params.set("event", eventId);
    const qs = params.toString();
    router.replace(qs ? `/events?${qs}` : "/events");
  }

  function handleRowClick(id: string) {
    const params = buildSearchParams(filter);
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
    const params = buildSearchParams(current);
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
    !!filter.observed_to;

  const showEmpty = !loading && !error && events.length === 0;
  const showError = !loading && !!error;

  return (
    <RoleProvider value={role ?? "blue"}>
      {/* Page header*/}
      <div style={{ marginBottom: "1rem" }}>
        <h1 className="brand-display text-foreground">Events</h1>
        <p className="text-muted-foreground mt-1" style={{ fontSize: 16 }}>
          All ingested intel events — filter, tag, and drill in.
        </p>
      </div>

      {/* Quick tag filters — click to add to filter set*/}
      <div style={{ marginBottom: "1.5rem" }} className="flex flex-col gap-1">
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
              listEvents({ ...filter, limit: filter.limit ?? 50 }, role)
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
            No events match your filters.
          </h2>
          <p className="text-muted-foreground" style={{ fontSize: 16 }}>
            Try removing a filter or registering additional sources.
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
        />
      )}

      {/* Event detail drawer — unconditional mount; opens on ?event=<id>*/}
      <EventDetailDrawer />
    </RoleProvider>
  );
}
