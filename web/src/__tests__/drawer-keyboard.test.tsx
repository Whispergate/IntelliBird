import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const replaceMock = vi.fn();
let currentSearchParams = new URLSearchParams();

vi.mock("@/app/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/app/api-client")>(
    "@/app/api-client",
  );
  return { ...actual, getEvent: vi.fn(), patchEventTags: vi.fn() };
});

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: replaceMock }),
  usePathname: () => "/blue",
  useSearchParams: () => currentSearchParams,
}));

import { EventDetailDrawer } from "@/app/components/EventDetailDrawer";
import { RoleProvider } from "@/app/lib/role-context";
import * as apiClient from "@/app/api-client";

const getEventMock = vi.mocked(apiClient.getEvent);

function baseEvent() {
  return {
    id: "evt-2",
    observed_at: new Date().toISOString(),
    fetched_at: new Date().toISOString(),
    source_id: "s1",
    source_name: "feed",
    source_type: "rss" as const,
    stix_id: null,
    stix_type: "indicator",
    title: "middle event",
    description: "d",
    tlp: "green" as const,
    tags: [],
    attack_techniques: [],
    archived: false,
    visibility: "shared" as const,
    geo_lat: null,
    geo_lon: null,
    raw_stix: null,
  };
}

beforeEach(() => {
  getEventMock.mockReset();
  getEventMock.mockResolvedValue(baseEvent());
  replaceMock.mockReset();
  currentSearchParams = new URLSearchParams("event=evt-2");
});

describe("drawer keyboard", () => {
  it("ArrowRight calls onNavigate with nextEventId", async () => {
    const onNavigate = vi.fn();
    render(
      <RoleProvider value="blue">
        <EventDetailDrawer
          prevEventId="evt-1"
          nextEventId="evt-3"
          currentIndex={1}
          totalCount={3}
          onNavigate={onNavigate}
        />
      </RoleProvider>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("event-detail-drawer")).toBeInTheDocument();
    });
    await userEvent.keyboard("{ArrowRight}");
    await waitFor(() => {
      expect(onNavigate).toHaveBeenCalledWith("evt-3");
    });
  });

  it("ArrowLeft calls onNavigate with prevEventId", async () => {
    const onNavigate = vi.fn();
    render(
      <RoleProvider value="blue">
        <EventDetailDrawer
          prevEventId="evt-1"
          nextEventId="evt-3"
          currentIndex={1}
          totalCount={3}
          onNavigate={onNavigate}
        />
      </RoleProvider>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("event-detail-drawer")).toBeInTheDocument();
    });
    await userEvent.keyboard("{ArrowLeft}");
    await waitFor(() => {
      expect(onNavigate).toHaveBeenCalledWith("evt-1");
    });
  });

  it("keyboard nav is skipped when an input has focus (tag editor open)", async () => {
    const onNavigate = vi.fn();
    render(
      <RoleProvider value="blue">
        <EventDetailDrawer
          prevEventId="evt-1"
          nextEventId="evt-3"
          currentIndex={1}
          totalCount={3}
          onNavigate={onNavigate}
        />
      </RoleProvider>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("event-detail-drawer")).toBeInTheDocument();
    });
    // Focus the tag input (tag editor is now real as of this plan)
    const tagInput = await screen.findByTestId("tag-input");
    tagInput.focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(onNavigate).not.toHaveBeenCalled();
  });

  it("DrawerNav is not rendered when totalCount is 0", async () => {
    render(
      <RoleProvider value="blue">
        <EventDetailDrawer totalCount={0} />
      </RoleProvider>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("event-detail-drawer")).toBeInTheDocument();
    });
    expect(screen.queryByTestId("drawer-nav")).not.toBeInTheDocument();
  });

  it("DrawerNav disables Prev on first event", async () => {
    const onNavigate = vi.fn();
    render(
      <RoleProvider value="blue">
        <EventDetailDrawer
          prevEventId={null}
          nextEventId="evt-2"
          currentIndex={0}
          totalCount={3}
          onNavigate={onNavigate}
        />
      </RoleProvider>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("drawer-nav")).toBeInTheDocument();
    });
    const prevBtn = screen.getByRole("button", { name: /Previous event/i });
    expect(prevBtn).toBeDisabled();
  });
});
