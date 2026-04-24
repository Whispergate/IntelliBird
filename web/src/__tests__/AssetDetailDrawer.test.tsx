// Owned by: 12.1-05-PLAN

import React from "react";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  act,
} from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("sonner", () => ({
  toast: vi.fn(),
}));

import {
  AssetDetailDrawer,
  type AssetDetail,
} from "@/app/projects/[id]/assets/components/AssetDetailDrawer";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const DETAIL: AssetDetail = {
  asset_id: "asset-1",
  bbot_event_type: "DNS_NAME",
  canonical_target: "www.example.com",
  scope: "in_scope",
  stale: false,
  first_seen: "2026-01-01T00:00:00Z",
  last_seen: "2026-04-20T00:00:00Z",
  scan_count: 3,
  findings: [
    {
      finding_id: "f1",
      module: "subdomain-brute",
      scan_id: "scanABCDEF1234",
      scan_started_at: "2026-04-20T10:00:00Z",
      lifecycle_status: "current",
      raw_bbot: { data: "www.example.com", type: "DNS_NAME" },
    },
    {
      finding_id: "f2",
      module: "sslcert",
      scan_id: "scan123456789",
      scan_started_at: "2026-04-18T09:00:00Z",
      lifecycle_status: "current",
      raw_bbot: { data: "cert-info" },
    },
  ],
  promoted_events: [],
  note: "",
  note_updated_by: null,
  note_updated_at: null,
};

function mockFetchForDetail(
  overrides: Partial<AssetDetail> = {},
  patchResponse: { ok: boolean } = { ok: true },
) {
  const detail = { ...DETAIL, ...overrides };
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : String(input);
    if (init?.method === "PATCH" && /\/note$/.test(url)) {
      return new Response(JSON.stringify({ ok: patchResponse.ok }), {
        status: patchResponse.ok ? 200 : 500,
        headers: { "Content-Type": "application/json" },
      });
    }
    return new Response(JSON.stringify(detail), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  global.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.useRealTimers();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("AssetDetailDrawer (12.1-05b)", () => {
  it("canonical_target renders in the header when drawer opens", async () => {
    mockFetchForDetail();
    render(
      <AssetDetailDrawer
        projectId="proj-1"
        assetId="asset-1"
        onClose={() => {}}
        canEditNote={true}
      />,
    );
    await waitFor(() => {
      expect(screen.getByText("www.example.com")).toBeInTheDocument();
    });
  });

  it("renders one findings row per finding", async () => {
    mockFetchForDetail();
    render(
      <AssetDetailDrawer
        projectId="proj-1"
        assetId="asset-1"
        onClose={() => {}}
        canEditNote={true}
      />,
    );
    await waitFor(() => {
      expect(screen.getByText("subdomain-brute")).toBeInTheDocument();
      expect(screen.getByText("sslcert")).toBeInTheDocument();
    });
  });

  it("Raw BBOT JSON block is collapsed by default (content not rendered)", async () => {
    mockFetchForDetail();
    render(
      <AssetDetailDrawer
        projectId="proj-1"
        assetId="asset-1"
        onClose={() => {}}
        canEditNote={true}
      />,
    );
    await waitFor(() => {
      expect(screen.getAllByText("Raw BBOT JSON").length).toBeGreaterThan(0);
    });
    // Raw data string from DETAIL.findings[0].raw_bbot.data should not be rendered.
    expect(screen.queryByText(/"data": "www\.example\.com"/)).toBeNull();
  });

  it("Note textarea disabled (via canEditNote=false) for Observer role", async () => {
    mockFetchForDetail();
    render(
      <AssetDetailDrawer
        projectId="proj-1"
        assetId="asset-1"
        onClose={() => {}}
        canEditNote={false}
      />,
    );
    const textarea = await screen.findByTestId("asset-note-textarea");
    expect(textarea).toBeDisabled();
  });

  it("Typing into note textarea triggers PATCH after 1500ms debounce and shows Saved", async () => {
    const fetchMock = mockFetchForDetail();
    // Mount with real timers so the initial detail GET resolves and the
    // textarea mounts synchronously via React state updates.
    render(
      <AssetDetailDrawer
        projectId="proj-1"
        assetId="asset-1"
        onClose={() => {}}
        canEditNote={true}
      />,
    );
    const textarea = await screen.findByTestId("asset-note-textarea");

    // Now switch to fake timers to control the 1500ms debounce window
    // without waiting real wall-clock time.
    vi.useFakeTimers();
    try {
      await act(async () => {
        fireEvent.change(textarea, { target: { value: "hello" } });
      });

      // Before debounce window: no PATCH yet.
      const patchCallsBefore = fetchMock.mock.calls.filter(
        ([, init]) => (init as RequestInit | undefined)?.method === "PATCH",
      );
      expect(patchCallsBefore).toHaveLength(0);

      // Advance past the 1500ms debounce window — fires the PATCH.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1600);
      });

      const patchCalls = fetchMock.mock.calls.filter(
        ([, init]) => (init as RequestInit | undefined)?.method === "PATCH",
      );
      expect(patchCalls.length).toBeGreaterThanOrEqual(1);
      const [urlCalled, initCalled] = patchCalls[0];
      expect(String(urlCalled)).toBe(
        "/api/projects/proj-1/assets/asset-1/note",
      );
      expect((initCalled as RequestInit).body).toContain("hello");

      // Drain microtasks to let the PATCH promise resolve and set status="saved".
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
    } finally {
      vi.useRealTimers();
    }

    // "Saved" status appears.
    await waitFor(() => {
      const status = screen.getByTestId("asset-note-status");
      expect(status.textContent ?? "").toMatch(/Saved/);
    });
  });
});
