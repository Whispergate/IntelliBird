import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, waitFor } from "@testing-library/react";
import maplibregl from "maplibre-gl";
import * as apiClient from "@/app/api-client";
import { GeoMapImpl } from "@/app/components/GeoMapImpl";
import { RoleProvider } from "@/app/lib/role-context";

const replaceMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: replaceMock }),
  usePathname: () => "/blue",
  useSearchParams: () => new URLSearchParams(),
}));

// vi.mock hoisted — factory must not reference module-level vars
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

const geoEvents = [
  {
    id: "evt-abc",
    observed_at: "2026-04-01T00:00:00Z",
    fetched_at: "2026-04-01T00:00:00Z",
    source_id: "src-1",
    source_name: "Feed A",
    source_type: "rss" as const,
    stix_id: null,
    stix_type: "indicator",
    title: "Event ABC",
    description: null,
    tlp: "green" as const,
    tags: [],
    attack_techniques: [],
    archived: false,
    visibility: "shared" as const,
    geo_lat: 51.5,
    geo_lon: -0.12,
  },
];

describe("Map pin click (plan 06-04, MAP-02)", () => {
  let localMapInstance: ReturnType<typeof makeMapInstance>;

  beforeEach(() => {
    vi.clearAllMocks();
    localMapInstance = makeMapInstance();
    // Must use a regular function (not arrow) since GeoMapImpl calls `new Map(...)`.
    vi.mocked(maplibregl.Map).mockImplementation(function MapMock() {
      return localMapInstance;
    } as never);
  });

  it("test_pin_click_calls_router_replace — pin click invokes router.replace with ?event=<id>", async () => {
    vi.mocked(apiClient.listEvents).mockResolvedValue({
      items: geoEvents,
      next_cursor: null,
      total: 1,
    });

    render(
      <RoleProvider value="blue">
        <GeoMapImpl />
      </RoleProvider>,
    );

    await waitFor(() => {
      expect(apiClient.listEvents).toHaveBeenCalled();
    });

    // Trigger map load to register click handlers
    const loadCall = localMapInstance.on.mock.calls.find(
      (c: unknown[]) => c[0] === "load",
    );
    expect(loadCall).toBeTruthy();
    (loadCall![1] as () => void)();

    // Find the unclustered-point click handler
    const pinClickCall = localMapInstance.on.mock.calls.find(
      (c: unknown[]) => c[0] === "click" && c[1] === "unclustered-point",
    );
    expect(pinClickCall).toBeTruthy();

    const pinClickHandler = pinClickCall![2] as (e: unknown) => void;
    pinClickHandler({
      features: [{ properties: { event_id: "evt-abc" } }],
    });

    expect(replaceMock).toHaveBeenCalledWith("/blue?event=evt-abc");
  });

  it("test_cluster_click_awaits_expansion_zoom — cluster click calls map.easeTo with expansion zoom", async () => {
    vi.mocked(apiClient.listEvents).mockResolvedValue({
      items: geoEvents,
      next_cursor: null,
      total: 1,
    });

    const getClusterExpansionZoomMock = vi.fn().mockResolvedValue(14);
    localMapInstance.getSource.mockReturnValue({
      getClusterExpansionZoom: getClusterExpansionZoomMock,
    });

    render(
      <RoleProvider value="blue">
        <GeoMapImpl />
      </RoleProvider>,
    );

    await waitFor(() => {
      expect(apiClient.listEvents).toHaveBeenCalled();
    });

    // Trigger map load
    const loadCall = localMapInstance.on.mock.calls.find(
      (c: unknown[]) => c[0] === "load",
    );
    expect(loadCall).toBeTruthy();
    (loadCall![1] as () => void)();

    // Find the clusters click handler
    const clusterClickCall = localMapInstance.on.mock.calls.find(
      (c: unknown[]) => c[0] === "click" && c[1] === "clusters",
    );
    expect(clusterClickCall).toBeTruthy();

    const clusterClickHandler = clusterClickCall![2] as (e: unknown) => Promise<void>;
    await clusterClickHandler({
      features: [
        {
          properties: { cluster_id: 42, point_count: 5 },
          geometry: { type: "Point", coordinates: [10, 20] },
        },
      ],
    });

    await waitFor(() => {
      expect(localMapInstance.easeTo).toHaveBeenCalledWith({
        center: [10, 20],
        zoom: 14,
      });
    });
  });

  it("test_pin_click_uses_encodeURIComponent — special chars in event_id are URL-encoded", async () => {
    vi.mocked(apiClient.listEvents).mockResolvedValue({
      items: geoEvents,
      next_cursor: null,
      total: 1,
    });

    render(
      <RoleProvider value="blue">
        <GeoMapImpl />
      </RoleProvider>,
    );

    await waitFor(() => {
      expect(apiClient.listEvents).toHaveBeenCalled();
    });

    const loadCall = localMapInstance.on.mock.calls.find(
      (c: unknown[]) => c[0] === "load",
    );
    (loadCall![1] as () => void)();

    const pinClickCall = localMapInstance.on.mock.calls.find(
      (c: unknown[]) => c[0] === "click" && c[1] === "unclustered-point",
    );
    const pinClickHandler = pinClickCall![2] as (e: unknown) => void;
    pinClickHandler({
      features: [{ properties: { event_id: "evt/abc" } }],
    });

    expect(replaceMock).toHaveBeenCalledWith("/blue?event=evt%2Fabc");
  });
});
