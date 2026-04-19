import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// ---------------------------------------------------------------------------
// Mocks — use vi.fn directly inside the factory to avoid hoisting issues
// ---------------------------------------------------------------------------

const replaceMock = vi.fn();
let currentSearchParams = new URLSearchParams();

vi.mock("@/app/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/app/api-client")>(
    "@/app/api-client",
  );
  return { ...actual, getEvent: vi.fn() };
});

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: replaceMock }),
  usePathname: () => "/blue",
  useSearchParams: () => currentSearchParams,
}));

// ---------------------------------------------------------------------------
// Imports (after mocks)
// ---------------------------------------------------------------------------

import { EventDetailDrawer } from "@/app/components/EventDetailDrawer";
import { RoleProvider } from "@/app/lib/role-context";
import * as apiClient from "@/app/api-client";
import type { EventDetail } from "@/app/api-client";

const getEventMock = vi.mocked(apiClient.getEvent);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function baseEvent(): EventDetail {
  return {
    id: "evt-1",
    observed_at: new Date().toISOString(),
    fetched_at: new Date().toISOString(),
    source_id: "s1",
    source_name: "feed",
    source_type: "rss",
    stix_id: null,
    stix_type: "indicator",
    title: "Event X",
    description: "d",
    tlp: "green",
    tags: [],
    attack_techniques: [],
    archived: false,
    visibility: "shared",
    geo_lat: null,
    geo_lon: null,
    raw_stix: null,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

beforeEach(() => {
  getEventMock.mockReset();
  getEventMock.mockResolvedValue(baseEvent());
  replaceMock.mockReset();
  currentSearchParams = new URLSearchParams("event=evt-1");
});

describe("drawer URL state", () => {
  it("clicking the sheet-close button calls router.replace(pathname)", async () => {
    render(
      <RoleProvider value="blue">
        <EventDetailDrawer />
      </RoleProvider>,
    );
    // Wait for drawer to be in the DOM (sheet open)
    await waitFor(() => {
      expect(screen.getByTestId("event-detail-drawer")).toBeInTheDocument();
    });
    // Click the close button tagged data-testid="sheet-close"
    const closeBtn = screen.getByTestId("sheet-close");
    await userEvent.click(closeBtn);
    await waitFor(() => {
      expect(replaceMock).toHaveBeenCalledWith("/blue");
    });
  });

  it("onOpenChange(false) path calls router.replace(pathname)", async () => {
    // Directly test the Sheet onOpenChange callback wiring without relying on
    // Radix UI keyboard events in jsdom. Render the drawer, confirm it mounts,
    // then fire an Escape keydown to trigger Radix's close path.
    render(
      <RoleProvider value="blue">
        <EventDetailDrawer />
      </RoleProvider>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("event-detail-drawer")).toBeInTheDocument();
    });
    // Pressing Escape should invoke onOpenChange(false) via Radix Sheet
    await userEvent.keyboard("{Escape}");
    await waitFor(() => {
      expect(replaceMock).toHaveBeenCalledWith("/blue");
    });
  });
});
