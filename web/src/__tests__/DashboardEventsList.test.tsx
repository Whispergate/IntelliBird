import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const replaceMock = vi.fn();

vi.mock("@/app/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/app/api-client")>(
    "@/app/api-client",
  );
  return {
    ...actual,
    listEvents: vi.fn().mockResolvedValue({ items: [], next_cursor: null, total: null }),
    getPreset: vi.fn().mockResolvedValue({
      id: "p1",
      name: "default-blue",
      query_params: { source_type: ["rss"] },
      created_at: "",
      updated_at: "",
    }),
  };
});

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: replaceMock }),
  usePathname: () => "/blue",
}));

import * as apiClient from "@/app/api-client";
import { DashboardEventsList } from "@/app/components/DashboardEventsList";
import { RoleProvider } from "@/app/lib/role-context";

const listEventsMock = apiClient.listEvents as ReturnType<typeof vi.fn>;
const getPresetMock = apiClient.getPreset as ReturnType<typeof vi.fn>;

function buildEvents(n: number, attack_techniques: string[] = []) {
  return Array.from({ length: n }, (_, i) => ({
    id: `evt-${i}`,
    observed_at: new Date(Date.now() - i * 60_000).toISOString(),
    fetched_at: new Date().toISOString(),
    source_id: "s1",
    source_name: `source-${i}`,
    source_type: "rss" as const,
    stix_id: null,
    stix_type: "indicator",
    title: `event title ${i}`,
    description: null,
    tlp: "green" as const,
    tags: [],
    attack_techniques,
    archived: false,
    visibility: "shared" as const,
    geo_lat: null,
    geo_lon: null,
  }));
}

beforeEach(() => {
  listEventsMock.mockReset();
  getPresetMock.mockReset();
  replaceMock.mockReset();
  getPresetMock.mockResolvedValue({
    id: "p1",
    name: "default-blue",
    query_params: { source_type: ["rss"] },
    created_at: "",
    updated_at: "",
  });
  listEventsMock.mockResolvedValue({
    items: buildEvents(25),
    next_cursor: null,
    total: null,
  });
});

describe("DashboardEventsList", () => {
  it("renders 25 rows from listEvents response", async () => {
    render(
      <RoleProvider value="blue">
        <DashboardEventsList />
      </RoleProvider>,
    );
    await waitFor(() => {
      expect(screen.getAllByTestId("events-row").length).toBe(25);
    });
  });

  it("row click calls router.replace with ?event=<id>", async () => {
    render(
      <RoleProvider value="blue">
        <DashboardEventsList />
      </RoleProvider>,
    );
    const rows = await screen.findAllByTestId("events-row");
    await userEvent.click(rows[0]);
    expect(replaceMock).toHaveBeenCalledWith("/blue?event=evt-0");
  });

  it("renders verbatim empty state when listEvents returns []", async () => {
    listEventsMock.mockResolvedValueOnce({
      items: [],
      next_cursor: null,
      total: null,
    });
    render(
      <RoleProvider value="blue">
        <DashboardEventsList />
      </RoleProvider>,
    );
    await waitFor(() => {
      expect(screen.getByText("No events yet.")).toBeInTheDocument();
    });
    expect(
      screen.getByText(
        "Register sources and wait for the first poll, or check your filter preset.",
      ),
    ).toBeInTheDocument();
  });

  it("fetches preset default-<role> and merges into listEvents query", async () => {
    render(
      <RoleProvider value="red">
        <DashboardEventsList />
      </RoleProvider>,
    );
    await waitFor(() => {
      expect(getPresetMock).toHaveBeenCalledWith("default-red");
    });
    // listEvents called with merged query + role header
    expect(listEventsMock).toHaveBeenCalled();
    const lastCall = listEventsMock.mock.calls[listEventsMock.mock.calls.length - 1];
    expect(lastCall[1]).toBe("red");
  });

  it("ATT&CK column header is rendered", async () => {
    render(
      <RoleProvider value="blue">
        <DashboardEventsList />
      </RoleProvider>,
    );
    await waitFor(() => {
      expect(screen.getAllByTestId("events-row").length).toBeGreaterThan(0);
    });
    expect(screen.getByText("ATT&CK")).toBeInTheDocument();
  });

  it("ATT&CK column renders '{N} TTPs' when attack_techniques has entries", async () => {
    listEventsMock.mockResolvedValueOnce({
      items: buildEvents(1, ["T1001", "T1002", "T1003"]),
      next_cursor: null,
      total: null,
    });
    render(
      <RoleProvider value="blue">
        <DashboardEventsList />
      </RoleProvider>,
    );
    await waitFor(() => {
      expect(screen.getByText("3 TTPs")).toBeInTheDocument();
    });
  });

  it("ATT&CK column renders em dash when attack_techniques is empty", async () => {
    listEventsMock.mockResolvedValueOnce({
      items: buildEvents(1, []),
      next_cursor: null,
      total: null,
    });
    render(
      <RoleProvider value="blue">
        <DashboardEventsList />
      </RoleProvider>,
    );
    await waitFor(() => {
      expect(screen.getAllByTestId("events-row").length).toBe(1);
    });
    // em dash U+2014 — rendered in the ATT&CK cell
    const emDashes = screen.getAllByText("\u2014");
    expect(emDashes.length).toBeGreaterThan(0);
  });
});
