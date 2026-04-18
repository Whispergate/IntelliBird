import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { RoleProvider } from "@/app/lib/role-context";

vi.mock("@/app/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/app/api-client")>(
    "@/app/api-client",
  );
  return {
    ...actual,
    listEvents: vi.fn().mockResolvedValue({ items: [], next_cursor: null, total: null }),
  };
});

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/blue",
}));

import * as apiClient from "@/app/api-client";
import type { EventItem } from "@/app/api-client";
import { BlueWidgets, RedWidgets } from "@/app/components/widgets";
import { ActorInfra } from "@/app/components/widgets/ActorInfra";
import { ToolingChatter } from "@/app/components/widgets/ToolingChatter";
import { CveRelevance } from "@/app/components/widgets/CveRelevance";
import { VendorAdvisories } from "@/app/components/widgets/VendorAdvisories";
import { bucketByDay } from "@/app/components/widgets/bucketByDay";

const listEventsMock = apiClient.listEvents as ReturnType<typeof vi.fn>;

function makeItem(daysAgo: number): EventItem {
  return {
    id: `evt-${daysAgo}`,
    observed_at: new Date(Date.now() - daysAgo * 86_400_000).toISOString(),
    fetched_at: new Date().toISOString(),
    source_id: "s1",
    source_name: "test",
    source_type: "rss",
    stix_id: null,
    stix_type: "indicator",
    title: `event ${daysAgo}d ago`,
    description: null,
    tlp: "clear",
    tags: [],
    attack_techniques: [],
    archived: false,
    visibility: "shared",
    geo_lat: null,
    geo_lon: null,
  };
}

beforeEach(() => {
  listEventsMock.mockReset();
  listEventsMock.mockResolvedValue({ items: [], next_cursor: null, total: null });
});

describe("Widgets data (plan 06-06, BLU-01/RED-01)", () => {
  it("every widget calls listEvents with limit 1000", async () => {
    render(
      <RoleProvider value="blue">
        <BlueWidgets />
      </RoleProvider>,
    );
    await waitFor(() => expect(listEventsMock).toHaveBeenCalled());

    listEventsMock.mockReset();
    listEventsMock.mockResolvedValue({ items: [], next_cursor: null, total: null });

    render(
      <RoleProvider value="red">
        <RedWidgets />
      </RoleProvider>,
    );
    await waitFor(() => expect(listEventsMock).toHaveBeenCalled());

    for (const call of listEventsMock.mock.calls) {
      expect(call[0].limit).toBe(1000);
    }
  });

  it("ActorInfra passes tag_mode=any with tag=['actor','c2']", async () => {
    render(
      <RoleProvider value="red">
        <ActorInfra />
      </RoleProvider>,
    );
    await waitFor(() => expect(listEventsMock).toHaveBeenCalled());
    const call = listEventsMock.mock.calls[0];
    expect(call[0].tag_mode).toBe("any");
    expect(call[0].tag).toEqual(["actor", "c2"]);
  });

  it("ToolingChatter passes tag_mode=any with tag=['tooling','offensive-tooling']", async () => {
    render(
      <RoleProvider value="red">
        <ToolingChatter />
      </RoleProvider>,
    );
    await waitFor(() => expect(listEventsMock).toHaveBeenCalled());
    const call = listEventsMock.mock.calls[0];
    expect(call[0].tag_mode).toBe("any");
    expect(call[0].tag).toEqual(["tooling", "offensive-tooling"]);
  });

  it("CveRelevance uses tag=['high-severity'] and no explicit tag_mode (default all)", async () => {
    render(
      <RoleProvider value="blue">
        <CveRelevance />
      </RoleProvider>,
    );
    await waitFor(() => expect(listEventsMock).toHaveBeenCalled());
    const call = listEventsMock.mock.calls[0];
    expect(call[0].tag).toEqual(["high-severity"]);
    // tag_mode should be absent (undefined) for default "all" semantics
    expect(call[0].tag_mode).toBeUndefined();
  });

  it("VendorAdvisories uses tag=['vendor-advisory']", async () => {
    render(
      <RoleProvider value="blue">
        <VendorAdvisories />
      </RoleProvider>,
    );
    await waitFor(() => expect(listEventsMock).toHaveBeenCalled());
    const call = listEventsMock.mock.calls[0];
    expect(call[0].tag).toEqual(["vendor-advisory"]);
  });

  it("zero state renders 'Go to Sources →' CTA link when count=0", async () => {
    listEventsMock.mockResolvedValue({ items: [], next_cursor: null, total: null });
    render(
      <RoleProvider value="blue">
        <BlueWidgets />
      </RoleProvider>,
    );
    await waitFor(() => {
      const ctas = screen.getAllByText("Go to Sources \u2192");
      expect(ctas.length).toBeGreaterThan(0);
    });
  });

  it("bucketByDay helper correctly assigns items to 7-day buckets (oldest first)", () => {
    const items: EventItem[] = [
      makeItem(0),  // today → bucket index 6
      makeItem(1),  // 1d ago → bucket index 5
      makeItem(3),  // 3d ago → bucket index 3
      makeItem(6),  // 6d ago → bucket index 0
      makeItem(7),  // 7d ago → outside window, not counted
    ];
    const buckets = bucketByDay(items, 7);
    expect(buckets.length).toBe(7);
    expect(buckets[6]).toBe(1); // today
    expect(buckets[5]).toBe(1); // 1d ago
    expect(buckets[3]).toBe(1); // 3d ago
    expect(buckets[0]).toBe(1); // 6d ago
    // day 7 is outside window — sum should be 4 total
    expect(buckets.reduce((a, b) => a + b, 0)).toBe(4);
  });

  it("sparkline is NOT rendered when count is 0", async () => {
    listEventsMock.mockResolvedValue({ items: [], next_cursor: null, total: null });
    render(
      <RoleProvider value="blue">
        <BlueWidgets />
      </RoleProvider>,
    );
    await waitFor(() => {
      expect(screen.queryAllByTestId("widget-sparkline").length).toBe(0);
    });
  });

  it("sparkline IS rendered when count > 0 with at least 2 days of data", async () => {
    const items = [makeItem(0), makeItem(1), makeItem(2)];
    listEventsMock.mockResolvedValue({ items, next_cursor: null, total: null });
    render(
      <RoleProvider value="blue">
        <BlueWidgets />
      </RoleProvider>,
    );
    await waitFor(() => {
      expect(screen.getAllByTestId("widget-sparkline").length).toBeGreaterThan(0);
    });
  });
});
