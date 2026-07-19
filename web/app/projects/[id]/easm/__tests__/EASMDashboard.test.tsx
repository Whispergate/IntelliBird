/**
 * EASMDashboard tests - plan 11-08.
 *
 * Tests Surface 3: EASM Dashboard at /projects/[id]/easm.
 * Activated in plan 11-08 (was a Wave 0 stub referencing plan 11-09).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// jsdom does not implement Pointer Events (hasPointerCapture). Radix UI Select
// requires it. Polyfill here so Radix pointerdown handler doesn't throw.
if (
  typeof Element !== "undefined" &&
  !Element.prototype.hasPointerCapture
) {
  Element.prototype.hasPointerCapture = () => false;
  Element.prototype.setPointerCapture = () => {};
  Element.prototype.releasePointerCapture = () => {};
}

// ---------------------------------------------------------------------------
// Mock next/navigation (useRouter required by EASMDashboardClient)
// ---------------------------------------------------------------------------
const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
  useSearchParams: () => ({ get: vi.fn().mockReturnValue(null) }),
}));

// ---------------------------------------------------------------------------
// Mock sonner
// ---------------------------------------------------------------------------
vi.mock("sonner", () => ({
  toast: {
    info: vi.fn(),
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
  },
}));

// ---------------------------------------------------------------------------
// Mock the EASM api module
// ---------------------------------------------------------------------------
vi.mock("../lib/api", () => ({
  listFindings: vi.fn(),
  getSafelist: vi.fn(),
  listScans: vi.fn(),
  patchFindingLifecycle: vi.fn(),
}));

import {
  listFindings,
  getSafelist,
  listScans,
  patchFindingLifecycle,
} from "../lib/api";
import type { EASMFinding, EASMSafelist, EASMScan } from "../lib/api";
import { EASMDashboardClient } from "../EASMDashboardClient";

// ---------------------------------------------------------------------------
// Test fixtures
// ---------------------------------------------------------------------------

const SAFELIST_STUB: EASMSafelist = {
  modules: ["crt", "dnsdumpster", "hackertarget"],
  bbot_version: "2.8.4",
  requires_credentials: {},
};

const FINDING_NEW: EASMFinding = {
  id: "f1",
  project_id: "proj-1",
  scan_id: "scan-1",
  bbot_event_type: "DNS_NAME",
  canonical_target: "example.com",
  severity: null,
  module: "crt",
  raw_bbot: {},
  first_seen: "2026-04-01T00:00:00Z",
  last_seen: "2026-04-10T00:00:00Z",
  lifecycle_status: "new",
  dismiss_until: null,
};

const FINDING_WATCHLIST: EASMFinding = {
  ...FINDING_NEW,
  id: "f2",
  canonical_target: "sub.example.com",
  lifecycle_status: "watchlist",
};

// 6 days + 2 hours ago (> 6 days - banner should show)
const CONFIRMED_AT_OLD = new Date(
  Date.now() - (6 * 24 * 60 * 60 + 2 * 60 * 60) * 1000,
).toISOString();

// 1 day ago (< 6 days - banner should NOT show)
const CONFIRMED_AT_RECENT = new Date(
  Date.now() - 24 * 60 * 60 * 1000,
).toISOString();

const SCAN_RUNNING: EASMScan = {
  id: "scan-1",
  project_id: "proj-1",
  status: "running",
  scan_mode: "passive",
  modules: ["crt"],
  started_at: "2026-04-10T00:00:00Z",
  finished_at: null,
  stdout_bytes: 100,
  error: null,
  launched_by: "user-sub",
  findings_count: 0,
};

function setupMocks({
  findings = [] as EASMFinding[],
  scans = [] as EASMScan[],
} = {}) {
  vi.mocked(listFindings).mockResolvedValue(findings);
  vi.mocked(getSafelist).mockResolvedValue(SAFELIST_STUB);
  vi.mocked(listScans).mockResolvedValue(scans);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("EASMDashboard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockPush.mockClear();
  });

  it("renders empty state heading when API returns empty array", async () => {
    setupMocks({ findings: [] });

    render(
      <EASMDashboardClient
        projectId="proj-1"
        initialProject={{ active_scans_authorised: false, active_auth_confirmed_at: null }}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("No EASM findings yet")).toBeInTheDocument();
    });

    expect(
      screen.getByText(
        /Launch a passive scan to begin discovering your project's external attack surface\./,
      ),
    ).toBeInTheDocument();
  });

  it("renders findings table when API returns findings", async () => {
    setupMocks({ findings: [FINDING_NEW] });

    render(
      <EASMDashboardClient
        projectId="proj-1"
        initialProject={{ active_scans_authorised: false, active_auth_confirmed_at: null }}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("example.com")).toBeInTheDocument();
    });

    // Should NOT show empty state
    expect(screen.queryByText("No EASM findings yet")).not.toBeInTheDocument();

    // Table header columns visible
    expect(screen.getByText("Type")).toBeInTheDocument();
    expect(screen.getByText("Target")).toBeInTheDocument();
    expect(screen.getByText("Severity")).toBeInTheDocument();
  });

  it("24h banner appears when confirmed_at > 6d ago AND active_scans_authorised=true", async () => {
    setupMocks({ findings: [] });

    render(
      <EASMDashboardClient
        projectId="proj-1"
        initialProject={{
          active_scans_authorised: true,
          active_auth_confirmed_at: CONFIRMED_AT_OLD,
        }}
      />,
    );

    await waitFor(() => {
      expect(
        screen.getByText(
          /Active-scan authorisation expires in less than 24 hours/,
        ),
      ).toBeInTheDocument();
    });
  });

  it("24h banner does NOT appear when gate not set", async () => {
    setupMocks({ findings: [] });

    render(
      <EASMDashboardClient
        projectId="proj-1"
        initialProject={{
          active_scans_authorised: false,
          active_auth_confirmed_at: CONFIRMED_AT_OLD,
        }}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("No EASM findings yet")).toBeInTheDocument();
    });

    expect(
      screen.queryByText(/Active-scan authorisation expires/),
    ).not.toBeInTheDocument();
  });

  it("24h banner does NOT appear when confirmed_at < 6d ago", async () => {
    setupMocks({ findings: [] });

    render(
      <EASMDashboardClient
        projectId="proj-1"
        initialProject={{
          active_scans_authorised: true,
          active_auth_confirmed_at: CONFIRMED_AT_RECENT,
        }}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("No EASM findings yet")).toBeInTheDocument();
    });

    expect(
      screen.queryByText(/Active-scan authorisation expires/),
    ).not.toBeInTheDocument();
  });

  it("filter Severity dropdown change triggers refetch with severity param", async () => {
    setupMocks({ findings: [FINDING_NEW] });
    const user = userEvent.setup();

    render(
      <EASMDashboardClient
        projectId="proj-1"
        initialProject={{ active_scans_authorised: false, active_auth_confirmed_at: null }}
      />,
    );

    // Wait for initial load
    await waitFor(() =>
      expect(vi.mocked(listFindings)).toHaveBeenCalledTimes(1),
    );

    // Open the Severity select (index 2 - Type, Module, Severity, Lifecycle)
    const selects = screen.getAllByRole("combobox");
    // Severity is the 3rd select (0-indexed: 2)
    const severitySelect = selects[2];
    await user.click(severitySelect);

    const highOption = await screen.findByText("High");
    await user.click(highOption);

    // listFindings should be called again with severity=high
    await waitFor(() =>
      expect(vi.mocked(listFindings)).toHaveBeenCalledWith(
        "proj-1",
        expect.objectContaining({ severity: "high", offset: 0 }),
      ),
    );
  });

  it("patchFinding success triggers optimistic UI update (lifecycle_status changes in table)", async () => {
    const updatedFinding: EASMFinding = {
      ...FINDING_NEW,
      lifecycle_status: "confirmed",
    };
    vi.mocked(listFindings).mockResolvedValue([FINDING_NEW]);
    vi.mocked(getSafelist).mockResolvedValue(SAFELIST_STUB);
    vi.mocked(listScans).mockResolvedValue([]);
    vi.mocked(patchFindingLifecycle).mockResolvedValue(updatedFinding);

    const user = userEvent.setup();

    render(
      <EASMDashboardClient
        projectId="proj-1"
        initialProject={{ active_scans_authorised: false, active_auth_confirmed_at: null }}
        isObserver={false}
      />,
    );

    // Wait for findings table to load
    await waitFor(() => {
      expect(screen.getByText("example.com")).toBeInTheDocument();
    });

    // Open Actions select - find the combobox in the Actions column
    // The 5th combobox (0-indexed: 4) is the Actions Select after the 4 filter bar dropdowns
    const allComboboxes = screen.getAllByRole("combobox");
    // 4 filter bar selects + 1 actions select per row
    const actionsSelect = allComboboxes[4];
    await user.click(actionsSelect);

    const confirmOption = await screen.findByText("Confirm finding");
    await user.click(confirmOption);

    await waitFor(() => {
      expect(vi.mocked(patchFindingLifecycle)).toHaveBeenCalledWith(
        "proj-1",
        "f1",
        "confirmed",
      );
    });
  });
});
