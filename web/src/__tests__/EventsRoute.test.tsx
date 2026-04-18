import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// ------------------------------------------------------------------
// Mocks must be hoisted before component imports
// ------------------------------------------------------------------

const replaceMock = vi.fn();
let searchParamsStore: URLSearchParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: replaceMock }),
  usePathname: () => "/events",
  useSearchParams: () => searchParamsStore,
}));

vi.mock("@/app/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/app/api-client")>(
    "@/app/api-client",
  );
  return {
    ...actual,
    listEvents: vi.fn().mockResolvedValue({ items: [], next_cursor: null, total: null }),
    listPresets: vi.fn().mockResolvedValue([]),
  };
});

import * as apiClient from "@/app/api-client";
import { EventsClient } from "@/app/events/EventsClient";
import { RoleProvider } from "@/app/lib/role-context";

const listEventsMock = apiClient.listEvents as ReturnType<typeof vi.fn>;
const listPresetsMock = apiClient.listPresets as ReturnType<typeof vi.fn>;

function buildEvent(id = "evt-1", overrides: Partial<ReturnType<typeof buildEvents>[number]> = {}) {
  return {
    id,
    observed_at: new Date().toISOString(),
    fetched_at: new Date().toISOString(),
    source_id: "s1",
    source_name: "Test Source",
    source_type: "rss" as const,
    stix_id: null,
    stix_type: "indicator",
    title: `Event ${id}`,
    description: null,
    tlp: "green" as const,
    tags: [],
    attack_techniques: [],
    archived: false,
    visibility: "shared" as const,
    geo_lat: null,
    geo_lon: null,
    ...overrides,
  };
}

function buildEvents(n: number) {
  return Array.from({ length: n }, (_, i) => buildEvent(`evt-${i}`));
}

beforeEach(() => {
  replaceMock.mockClear();
  listEventsMock.mockReset();
  listPresetsMock.mockReset();
  searchParamsStore = new URLSearchParams();
  listEventsMock.mockResolvedValue({ items: [], next_cursor: null, total: null });
  listPresetsMock.mockResolvedValue([]);
  window.localStorage.clear();
});

function renderEventsClient() {
  return render(
    <RoleProvider value="blue">
      <EventsClient />
    </RoleProvider>,
  );
}

describe("Events route (plan 06-07, MAP/D-28)", () => {
  it("test_events_page_renders_title — h1 'Events' heading is present", async () => {
    renderEventsClient();
    expect(screen.getByRole("heading", { level: 1, name: "Events" })).toBeInTheDocument();
  });

  it("test_events_page_renders_subtitle_copy", async () => {
    renderEventsClient();
    expect(
      screen.getByText("All ingested intel events — filter, tag, and drill in."),
    ).toBeInTheDocument();
  });

  it("test_list_events_called_on_mount", async () => {
    renderEventsClient();
    await waitFor(() => {
      expect(listEventsMock.mock.calls.length).toBeGreaterThanOrEqual(1);
    });
  });

  it("test_preset_url_param_parses_and_applies — listEvents called with tag from preset JSON", async () => {
    const presetJson = JSON.stringify({ tag: ["exploit"], limit: 1000 });
    searchParamsStore = new URLSearchParams({ preset: encodeURIComponent(presetJson) });
    renderEventsClient();
    await waitFor(() => {
      expect(listEventsMock).toHaveBeenCalled();
      const lastCall = listEventsMock.mock.calls[listEventsMock.mock.calls.length - 1];
      const query = lastCall[0] as { tag?: string[] };
      expect(query.tag).toEqual(["exploit"]);
    });
  });

  it("test_events_table_has_six_columns — all 6 column headers present", async () => {
    listEventsMock.mockResolvedValue({ items: buildEvents(1), next_cursor: null, total: null });
    renderEventsClient();
    await waitFor(() => {
      expect(screen.getAllByTestId("events-row").length).toBeGreaterThan(0);
    });
    expect(screen.getByRole("columnheader", { name: /title/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /type/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /tlp/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /att.?&.?ck/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /source/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /observed/i })).toBeInTheDocument();
  });

  it("test_row_click_replaces_url_with_event_param", async () => {
    listEventsMock.mockResolvedValue({
      items: [buildEvent("evt-abc")],
      next_cursor: null,
      total: null,
    });
    renderEventsClient();
    const rows = await screen.findAllByTestId("events-row");
    await userEvent.click(rows[0]);
    expect(replaceMock).toHaveBeenCalledWith(
      expect.stringContaining("event=evt-abc"),
    );
  });

  it("test_clear_filters_button_removes_filters — router.replace called without tlp after clear", async () => {
    searchParamsStore = new URLSearchParams({ tlp: "amber" });
    renderEventsClient();
    const clearBtn = await screen.findByRole("button", { name: /clear filters/i });
    await userEvent.click(clearBtn);
    expect(replaceMock).toHaveBeenCalledWith(
      expect.not.stringContaining("tlp="),
    );
  });
});
