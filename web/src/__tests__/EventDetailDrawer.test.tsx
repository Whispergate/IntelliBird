import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks — factories must not reference outer let variables (hoisting issue).
// Capture the mock fn via vi.mocked after import instead.
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

function baseEvent(overrides: Partial<EventDetail> = {}): EventDetail {
  return {
    id: "evt-1",
    observed_at: new Date().toISOString(),
    fetched_at: new Date().toISOString(),
    source_id: "s1",
    source_name: "vendor-feed",
    source_type: "rss",
    stix_id: null,
    stix_type: "indicator",
    title: "Sample event title",
    description: "This is the description.",
    tlp: "green",
    tags: [],
    attack_techniques: [],
    archived: false,
    visibility: "shared",
    geo_lat: null,
    geo_lon: null,
    raw_stix: { type: "indicator", spec_version: "2.1" },
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

beforeEach(() => {
  getEventMock.mockReset();
  replaceMock.mockReset();
  currentSearchParams = new URLSearchParams();
});

describe("EventDetailDrawer", () => {
  it("renders nothing visible when searchParams has no event", () => {
    // searchParams is empty — no ?event param
    render(
      <RoleProvider value="blue">
        <EventDetailDrawer />
      </RoleProvider>,
    );
    expect(
      screen.queryByTestId("event-detail-drawer"),
    ).not.toBeInTheDocument();
  });

  it("renders drawer with title when searchParams has event=<id>", async () => {
    currentSearchParams = new URLSearchParams("event=evt-1");
    getEventMock.mockResolvedValue(baseEvent());
    render(
      <RoleProvider value="blue">
        <EventDetailDrawer />
      </RoleProvider>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("event-detail-drawer")).toBeInTheDocument();
    });
    expect(screen.getByText("Sample event title")).toBeInTheDocument();
  });

  it("falls back to 'Untitled event' when event.title is null", async () => {
    currentSearchParams = new URLSearchParams("event=evt-1");
    getEventMock.mockResolvedValue(baseEvent({ title: null }));
    render(
      <RoleProvider value="blue">
        <EventDetailDrawer />
      </RoleProvider>,
    );
    await waitFor(() => {
      expect(screen.getByText("Untitled event")).toBeInTheDocument();
    });
  });

  it("description shows verbatim fallback when null", async () => {
    currentSearchParams = new URLSearchParams("event=evt-1");
    getEventMock.mockResolvedValue(baseEvent({ description: null }));
    render(
      <RoleProvider value="blue">
        <EventDetailDrawer />
      </RoleProvider>,
    );
    await waitFor(() => {
      expect(
        screen.getByText("No description available."),
      ).toBeInTheDocument();
    });
  });

  it("techniques section shows verbatim fallback when empty", async () => {
    currentSearchParams = new URLSearchParams("event=evt-1");
    getEventMock.mockResolvedValue(baseEvent({ attack_techniques: [] }));
    render(
      <RoleProvider value="blue">
        <EventDetailDrawer />
      </RoleProvider>,
    );
    await waitFor(() => {
      expect(screen.getByText("No techniques linked.")).toBeInTheDocument();
    });
  });

  it("geo section always shows 'No geo data available.' (M1)", async () => {
    currentSearchParams = new URLSearchParams("event=evt-1");
    getEventMock.mockResolvedValue(baseEvent());
    render(
      <RoleProvider value="blue">
        <EventDetailDrawer />
      </RoleProvider>,
    );
    await waitFor(() => {
      expect(
        screen.getByText("No geo data available."),
      ).toBeInTheDocument();
    });
  });

  it("raw data summary shows 'VIEW RAW DATA'", async () => {
    currentSearchParams = new URLSearchParams("event=evt-1");
    getEventMock.mockResolvedValue(baseEvent());
    render(
      <RoleProvider value="blue">
        <EventDetailDrawer />
      </RoleProvider>,
    );
    await waitFor(() => {
      expect(
        screen.getByTestId("drawer-raw-summary"),
      ).toHaveTextContent("VIEW RAW DATA");
    });
  });

  it("getEvent called with role from context", async () => {
    currentSearchParams = new URLSearchParams("event=evt-1");
    getEventMock.mockResolvedValue(baseEvent());
    render(
      <RoleProvider value="red">
        <EventDetailDrawer />
      </RoleProvider>,
    );
    await waitFor(() => {
      expect(getEventMock).toHaveBeenCalledWith("evt-1", "red");
    });
  });

  it("renders technique chips with links to mitre.org", async () => {
    currentSearchParams = new URLSearchParams("event=evt-1");
    getEventMock.mockResolvedValue(
      baseEvent({ attack_techniques: ["T1190", "T1566"] }),
    );
    render(
      <RoleProvider value="blue">
        <EventDetailDrawer />
      </RoleProvider>,
    );
    await waitFor(() => {
      expect(screen.getByText("T1190")).toBeInTheDocument();
    });
    const link = screen
      .getByLabelText("ATT&CK technique T1190 (opens mitre.org)")
      .closest("a");
    expect(link).toHaveAttribute(
      "href",
      "https://attack.mitre.org/techniques/T1190/",
    );
    expect(link).toHaveAttribute("target", "_blank");
  });
});
