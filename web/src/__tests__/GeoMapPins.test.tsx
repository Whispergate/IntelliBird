import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import maplibregl from "maplibre-gl";
import * as apiClient from "@/app/api-client";
import { GeoMapImpl } from "@/app/components/GeoMapImpl";
import { RoleProvider } from "@/app/lib/role-context";

// Mock next/navigation
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/blue",
  useSearchParams: () => new URLSearchParams(),
}));

// Mock the api-client listEvents
// vi.mock is hoisted above imports, so the factory must not reference module-level vars.
vi.mock("@/app/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/app/api-client")>();
  return {
    ...actual,
    listEvents: vi.fn(),
  };
});

function makeMapInstance() {
  return {
    remove: vi.fn(),
    on: vi.fn(),
    off: vi.fn(),
    addControl: vi.fn(),
    addSource: vi.fn(),
    addLayer: vi.fn(),
    setStyle: vi.fn(),
    getSource: vi.fn(),
    easeTo: vi.fn(),
  };
}

const twoGeoEvents = [
  {
    id: "evt-001",
    observed_at: "2026-04-01T00:00:00Z",
    fetched_at: "2026-04-01T00:00:00Z",
    source_id: "src-1",
    source_name: "Feed A",
    source_type: "rss" as const,
    stix_id: null,
    stix_type: "indicator",
    title: "Event One",
    description: null,
    tlp: "amber" as const,
    tags: [],
    attack_techniques: [],
    archived: false,
    visibility: "shared" as const,
    geo_lat: 51.5,
    geo_lon: -0.12,
  },
  {
    id: "evt-002",
    observed_at: "2026-04-02T00:00:00Z",
    fetched_at: "2026-04-02T00:00:00Z",
    source_id: "src-2",
    source_name: "Feed B",
    source_type: "taxii" as const,
    stix_id: null,
    stix_type: "malware",
    title: "Event Two",
    description: null,
    tlp: "red" as const,
    tags: [],
    attack_techniques: [],
    archived: false,
    visibility: "shared" as const,
    geo_lat: 48.85,
    geo_lon: 2.35,
  },
];

describe("GeoMap pins (plan 06-04, MAP-01)", () => {
  let localMapInstance: ReturnType<typeof makeMapInstance>;

  beforeEach(() => {
    vi.clearAllMocks();
    localMapInstance = makeMapInstance();
    // Must use a regular function (not arrow) since GeoMapImpl calls `new Map(...)`.
    vi.mocked(maplibregl.Map).mockImplementation(function MapMock() {
      return localMapInstance;
    } as never);
  });

  it("test_list_events_called_with_has_geo_and_role — calls listEvents with has_geo and role", async () => {
    vi.mocked(apiClient.listEvents).mockResolvedValue({
      items: [],
      next_cursor: null,
      total: 0,
    });

    render(
      <RoleProvider value="red">
        <GeoMapImpl />
      </RoleProvider>,
    );

    await waitFor(() => {
      expect(apiClient.listEvents).toHaveBeenCalled();
    });

    const firstArg = vi.mocked(apiClient.listEvents).mock.calls[0][0];
    const secondArg = vi.mocked(apiClient.listEvents).mock.calls[0][1];
    expect(firstArg).toMatchObject({ has_geo: true, limit: 1000 });
    expect(secondArg).toBe("red");
  });

  it("test_empty_state_overlay_renders_exact_copy — shows empty overlay when no events", async () => {
    // GeoMapImpl fires two listEvents calls: has_geo=true for pins, then a
    // probe (limit=1) to distinguish "no events at all" from "no geo-resolved
    // events". The "No geo-resolved events…" copy renders only when the probe
    // proves the DB has events but none have coordinates.
    // Call 1 (has_geo=true) → empty
    vi.mocked(apiClient.listEvents).mockResolvedValueOnce({
      items: [],
      next_cursor: null,
      total: 0,
    });
    // Call 2 (probe, limit=1) → at least one event (non-geo)
    vi.mocked(apiClient.listEvents).mockResolvedValueOnce({
      items: [twoGeoEvents[0]],
      next_cursor: null,
      total: 1,
    });

    render(
      <RoleProvider value="blue">
        <GeoMapImpl />
      </RoleProvider>,
    );

    await waitFor(() => {
      expect(
        screen.getByText(
          "No geo-resolved events. Configure GeoLite2 or wait for STIX-located intel.",
        ),
      ).toBeInTheDocument();
    });
  });

  it("test_map_addSource_called_with_cluster_true — addSource called with cluster options after load", async () => {
    vi.mocked(apiClient.listEvents).mockResolvedValue({
      items: twoGeoEvents,
      next_cursor: null,
      total: 2,
    });

    render(
      <RoleProvider value="blue">
        <GeoMapImpl />
      </RoleProvider>,
    );

    await waitFor(() => {
      expect(apiClient.listEvents).toHaveBeenCalled();
    });

    // Trigger the "load" callback so source/layers get registered
    const loadCall = localMapInstance.on.mock.calls.find(
      (c: unknown[]) => c[0] === "load",
    );
    expect(loadCall).toBeTruthy();
    (loadCall![1] as () => void)();

    await waitFor(() => {
      expect(localMapInstance.addSource).toHaveBeenCalledWith(
        "events",
        expect.objectContaining({
          type: "geojson",
          cluster: true,
          clusterRadius: 40,
          clusterMaxZoom: 14,
        }),
      );
    });
  });

  it("test_addSource_features_match_events — GeoJSON features match event coordinates and ids", async () => {
    vi.mocked(apiClient.listEvents).mockResolvedValue({
      items: twoGeoEvents,
      next_cursor: null,
      total: 2,
    });

    render(
      <RoleProvider value="blue">
        <GeoMapImpl />
      </RoleProvider>,
    );

    await waitFor(() => {
      expect(apiClient.listEvents).toHaveBeenCalled();
    });

    // Wait for the events state to propagate and eventsSnapshot.current to be set.
    // The listEvents promise resolves, setEvents fires, React re-renders, then
    // eventsSnapshot.current is updated by the dependent useEffect.
    await new Promise((r) => setTimeout(r, 20));

    const loadCall = localMapInstance.on.mock.calls.find(
      (c: unknown[]) => c[0] === "load",
    );
    expect(loadCall).toBeTruthy();
    (loadCall![1] as () => void)();

    await waitFor(() => {
      expect(localMapInstance.addSource).toHaveBeenCalled();
    });

    const addSourceArgs = localMapInstance.addSource.mock.calls[0];
    const sourceData = addSourceArgs[1].data as GeoJSON.FeatureCollection;

    expect(sourceData.features).toHaveLength(2);

    const feature0 = sourceData.features[0];
    expect(feature0.geometry).toMatchObject({
      type: "Point",
      coordinates: [twoGeoEvents[0].geo_lon, twoGeoEvents[0].geo_lat],
    });
    expect(feature0.properties?.event_id).toBe(twoGeoEvents[0].id);

    const feature1 = sourceData.features[1];
    expect(feature1.geometry).toMatchObject({
      type: "Point",
      coordinates: [twoGeoEvents[1].geo_lon, twoGeoEvents[1].geo_lat],
    });
    expect(feature1.properties?.event_id).toBe(twoGeoEvents[1].id);
  });

  it("test_phase5_placeholder_overlay_absent — overlay text must not appear in DOM", async => {
    vi.mocked(apiClient.listEvents).mockResolvedValue({
      items: [],
      next_cursor: null,
      total: 0,
    });

    render(
      <RoleProvider value="blue">
        <GeoMapImpl />
      </RoleProvider>,
    );

    await waitFor(() => {
      expect(apiClient.listEvents).toHaveBeenCalled();
    });

    expect(
      screen.queryByText("Geo layer loads in."),
    ).not.toBeInTheDocument();
  });
});
