"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import "maplibre-gl/dist/maplibre-gl.css";
import { useRole } from "@/app/lib/role-context";
import { listEvents, type EventItem } from "@/app/api-client";

export type GeoMapProps = {
  height?: number | string;
  interactive?: boolean;
  overlayText?: string | null;
  tilesUrl?: string;
};

// Module-level guard - ensures addProtocol is called at most once per page load
// even if the component is mounted multiple times (dashboard + drawer).
let pmtilesRegistered = false;

// Build a GeoJSON FeatureCollection from EventItem array.
function buildGeoJSON(events: EventItem[]): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: events
      .filter((e) => e.geo_lat != null && e.geo_lon != null)
      .map((e) => ({
        type: "Feature" as const,
        geometry: {
          type: "Point" as const,
          coordinates: [e.geo_lon as number, e.geo_lat as number],
        },
        properties: {
          event_id: e.id,
          tlp: e.tlp ?? "unresolved",
        },
      })),
  };
}

// TLP color match expression for MapLibre paint
const TLP_COLOR_EXPRESSION = [
  "match",
  ["get", "tlp"],
  "clear",
  "#9FE1CB",
  "green",
  "#1D9E75",
  "amber",
  "#EF9F27",
  "amber+strict",
  "#C87912",
  "red",
  "hsl(0, 70%, 45%)",
  "#888780", // default - unresolved
];

export function GeoMapImpl({
  height = "50vh",
  interactive = true,
  overlayText = null,
  tilesUrl,
}: GeoMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const mapRef = useRef<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [events, setEvents] = useState<EventItem[]>([]);
  const [eventsLoaded, setEventsLoaded] = useState(false);
  const [hasAnyEvents, setHasAnyEvents] = useState(false);

  const router = useRouter();
  const pathname = usePathname();
  const role = useRole();

  // Fetch geo-resolved events + probe whether any events exist at all.
  // Two queries distinguish empty-DB from unresolved-geo for the overlay.
  useEffect(() => {
    let cancelled = false;
    Promise.all([
      listEvents({ has_geo: true, limit: 1000 }, role).catch(() => ({
        items: [],
      })),
      listEvents({ limit: 1 }, role).catch(() => ({ items: [] })),
    ]).then(([geoRes, probeRes]) => {
      if (cancelled) return;
      setEvents(
        ((geoRes.items as EventItem[]) || []).filter(
          (e) => e.geo_lat != null && e.geo_lon != null,
        ),
      );
      setHasAnyEvents(((probeRes.items as EventItem[]) || []).length > 0);
      setEventsLoaded(true);
    });
    return () => {
      cancelled = true;
    };
  }, [role]);

  // Map initialisation - runs once on mount.
  useEffect(() => {
    if (!containerRef.current) return;
    let cancelled = false;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let map: any = null;

    (async () => {
      try {
        const maplibreModule = await import("maplibre-gl");
        // Handle both ESM default and CommonJS shapes
        const maplibregl =
          (maplibreModule as unknown as { default: typeof maplibreModule })
            .default ?? maplibreModule;
        const { Protocol } = await import("pmtiles");

        if (!pmtilesRegistered) {
          const protocol = new Protocol();
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          (maplibregl as any).addProtocol(
            "pmtiles",
            protocol.tile.bind(protocol),
          );
          pmtilesRegistered = true;
        }

        if (cancelled || !containerRef.current) return;

        const resolvedTilesUrl =
          tilesUrl ??
          process.env.NEXT_PUBLIC_MAP_TILES_URL ??
          "/tiles/world.pmtiles";

        // Probe pmtiles asset before handing to map. Invalid file (missing,
        // text placeholder, wrong magic bytes) → skip the protomaps source and
        // render an Ink-only background. Map still mounts; overlay stays.
        let pmtilesUsable = false;
        try {
          const probe = await fetch(resolvedTilesUrl, {
            method: "GET",
            headers: { Range: "bytes=0-6" },
          });
          if (probe.ok) {
            const buf = await probe.arrayBuffer();
            const bytes = new Uint8Array(buf);
            // PMTiles v3 magic: 0x50 0x4D 0x54 0x69 0x6C 0x65 0x73 ("PMTiles")
            pmtilesUsable =
              bytes.length >= 7 &&
              bytes[0] === 0x50 &&
              bytes[1] === 0x4d &&
              bytes[2] === 0x54 &&
              bytes[3] === 0x69 &&
              bytes[4] === 0x6c &&
              bytes[5] === 0x65 &&
              bytes[6] === 0x73;
          }
        } catch {
          pmtilesUsable = false;
        }
        if (cancelled || !containerRef.current) return;

        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const style: any = pmtilesUsable
          ? {
              version: 8,
              sources: {
                protomaps: {
                  type: "vector",
                  url: `pmtiles://${resolvedTilesUrl}`,
                  attribution: "© Protomaps",
                },
              },
              layers: [
                {
                  id: "background",
                  type: "background",
                  paint: { "background-color": "#04342C" },
                },
                {
                  id: "earth",
                  source: "protomaps",
                  "source-layer": "earth",
                  type: "fill",
                  paint: { "fill-color": "#071f1a" },
                },
                {
                  id: "water",
                  source: "protomaps",
                  "source-layer": "water",
                  type: "fill",
                  paint: { "fill-color": "#04342C" },
                },
                {
                  id: "boundaries",
                  source: "protomaps",
                  "source-layer": "boundaries",
                  type: "line",
                  paint: {
                    "line-color": "#0F6E56",
                    "line-opacity": 0.4,
                    "line-width": 0.5,
                  },
                },
              ],
            }
          : {
              // Fallback style when pmtiles not configured: ship a Natural Earth
              // 110m countries GeoJSON (~800KB, baked in) for a usable basemap
              // without any external tile infrastructure. Ink bg + Deep-teal
              // country fill + Primary teal country outline.
              version: 8,
              sources: {
                "ne-countries": {
                  type: "geojson",
                  data: "/tiles/world-110m.geojson",
                },
              },
              layers: [
                {
                  id: "background",
                  type: "background",
                  paint: { "background-color": "#04342C" },
                },
                {
                  id: "countries-fill",
                  source: "ne-countries",
                  type: "fill",
                  paint: { "fill-color": "#0a3d32", "fill-opacity": 0.9 },
                },
                {
                  id: "countries-outline",
                  source: "ne-countries",
                  type: "line",
                  paint: {
                    "line-color": "#1D9E75",
                    "line-opacity": 0.35,
                    "line-width": 0.5,
                  },
                },
              ],
            };

        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        map = new (maplibregl as any).Map({
          container: containerRef.current,
          style,
          center: [0, 20],
          zoom: 1.5,
          interactive,
        });

        // Store map ref for the events-data sync effect
        mapRef.current = map;

        // Swallow runtime tile fetch errors so browser console stays clean.
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        map.on("error", (_ev: any) => {
          /* intentional no-op*/
        });

        // Register GeoJSON source, layers and click handlers on map load.
        map.on("load", () => {
          if (cancelled) return;

          // Snapshot events at load time via closure - the events-sync effect
          // keeps the source updated as state changes after load.
          const currentEvents = eventsSnapshot.current;

          map.addSource("events", {
            type: "geojson",
            data: buildGeoJSON(currentEvents),
            cluster: true,
            clusterRadius: 40,
            clusterMaxZoom: 14,
          });

          // Individual pins (TLP-colored)
          map.addLayer({
            id: "unclustered-point",
            type: "circle",
            source: "events",
            filter: ["!", ["has", "point_count"]],
            paint: {
              "circle-color": TLP_COLOR_EXPRESSION,
              "circle-radius": 8,
              "circle-stroke-width": 0,
            },
          });

          // Cluster circles with step radius + color
          map.addLayer({
            id: "clusters",
            type: "circle",
            source: "events",
            filter: ["has", "point_count"],
            paint: {
              "circle-color": [
                "step",
                ["get", "point_count"],
                "#1D9E75",
                10,
                "#0F6E56",
                100,
                "#04342C",
              ],
              "circle-radius": [
                "step",
                ["get", "point_count"],
                8,
                10,
                12,
                100,
                16,
              ],
              "circle-stroke-color": [
                "step",
                ["get", "point_count"],
                "transparent",
                100,
                "#EF9F27",
              ],
              "circle-stroke-width": [
                "step",
                ["get", "point_count"],
                0,
                100,
                2,
              ],
            },
          });

          // Cluster count label
          map.addLayer({
            id: "cluster-count",
            type: "symbol",
            source: "events",
            filter: ["has", "point_count"],
            layout: {
              "text-field": "{point_count_abbreviated}",
              "text-size": 13,
            },
            paint: { "text-color": "#E1F5EE" },
          });

          // Pin click → open EventDetailDrawer via URL param
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          map.on("click", "unclustered-point", (e: any) => {
            const eid = e.features?.[0]?.properties?.event_id;
            if (eid) {
              router.replace(
                `${pathname}?event=${encodeURIComponent(String(eid))}`,
              );
            }
          });

          // Cluster click → Promise-based expansion zoom (MapLibre v5 API)
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          map.on("click", "clusters", async (e: any) => {
            const feature = e.features?.[0];
            const clusterId = feature?.properties?.cluster_id;
            if (clusterId == null) return;
            const source = map.getSource("events");
            try {
              const zoom = await source.getClusterExpansionZoom(clusterId);
              const coords = feature.geometry.coordinates as [number, number];
              map.easeTo({ center: coords, zoom });
            } catch {
              /* noop*/
            }
          });
        });
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e));
        }
      }
    })();

    return () => {
      cancelled = true;
      mapRef.current = null;
      try {
        map?.remove?.();
      } catch {
        // ignore cleanup errors
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [interactive, tilesUrl]);

  // Keep a ref to current events so the map load callback (closed over at
  // mount time) always gets the latest snapshot when it fires.
  const eventsSnapshot = useRef<EventItem[]>([]);
  useEffect(() => {
    eventsSnapshot.current = events;
  }, [events]);

  // Re-sync the GeoJSON source whenever events state changes after map load.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const source = map.getSource?.("events");
    if (source?.setData) {
      source.setData(buildGeoJSON(events));
    }
  }, [events]);

  if (error) {
    return (
      <div
        data-testid="geomap-error"
        style={{
          height,
          width: "100%",
          background: "hsl(var(--card))",
          color: "var(--brand-slate)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 16,
        }}
      >
        Map unavailable. Check tile configuration.
      </div>
    );
  }

  return (
    <div
      data-testid="geomap-container"
      style={{
        position: "relative",
        height,
        width: "100%",
        background: "#04342C",
      }}
    >
      <div ref={containerRef} style={{ height: "100%", width: "100%" }} />

      {/* overlayText prop - kept for backward compatibility with tests*/}
      {overlayText ? (
        <div
          data-testid="geomap-overlay"
          style={{
            position: "absolute",
            bottom: 8,
            right: 8,
            fontSize: 12,
            color: "hsl(var(--muted-foreground))",
            background: "rgba(0,0,0,0.5)",
            padding: "4px 8px",
            borderRadius: 4,
          }}
        >
          {overlayText}
        </div>
      ) : null}

      {/* empty-state overlay - fires when 0 geo-resolved events after fetch*/}
      {eventsLoaded && events.length === 0 ? (
        <div
          data-testid="geomap-empty"
          className="text-xs text-muted-foreground"
          style={{
            position: "absolute",
            bottom: 16,
            left: "50%",
            transform: "translateX(-50%)",
            background: "rgba(0,0,0,0.6)",
            padding: "4px 12px",
            borderRadius: 9999,
            whiteSpace: "nowrap",
          }}
        >
          {hasAnyEvents
            ? "No geo-resolved events. Configure GeoLite2 or wait for STIX-located intel."
            : "No events yet. Register sources and wait for the first poll."}
        </div>
      ) : null}
    </div>
  );
}
