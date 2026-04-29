/**
 * BrandDashboard tests — plan 12-08.
 *
 * Covers UI-SPEC §Surface 2 + §Surface 3:
 *   - Filter bar renders 4 controls (severity, source, lifecycle, include_dismissed)
 *   - Match table renders rows from API response
 *   - Suppression-review banner conditional visibility
 *   - Noise-downgrade banner conditional visibility
 *   - Empty state renders canonical strings
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// jsdom pointer events polyfill (Radix Select requirement)
if (
  typeof Element !== "undefined" &&
  !Element.prototype.hasPointerCapture
) {
  Element.prototype.hasPointerCapture = () => false;
  Element.prototype.setPointerCapture = () => {};
  Element.prototype.releasePointerCapture = () => {};
}

const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
  usePathname: () => "/projects/proj-1/brand",
  useSearchParams: () => ({ get: vi.fn().mockReturnValue(null) }),
}));

vi.mock("sonner", () => ({
  toast: {
    info: vi.fn(),
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
  },
}));

vi.mock("../lib/api", () => ({
  listBrandMatches: vi.fn(),
  patchBrandMatch: vi.fn(),
  extendDismissal: vi.fn(),
  listSuppressionReview: vi.fn(),
}));

import { listBrandMatches } from "../lib/api";
import type {
  BrandDashboardResponse,
  BrandMatchRead,
} from "../lib/api";
import { BrandDashboardClient } from "../BrandDashboardClient";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const MATCH_NEW: BrandMatchRead = {
  id: "m1",
  project_id: "proj-1",
  term_id: "t1",
  term: {
    id: "t1",
    value: "IntelliBird",
    term_type: "keyword",
    mode: "active",
    high_noise_risk: false,
  },
  matched_value: "intellibird-lookalike.io",
  match_source: "dnstwist",
  severity: "high",
  lifecycle_status: "new",
  dismiss_until: null,
  first_seen: new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString(),
  last_seen: new Date(Date.now() - 60 * 60 * 1000).toISOString(),
};

function buildResp(
  overrides: Partial<BrandDashboardResponse> = {},
): BrandDashboardResponse {
  return {
    matches: [],
    has_expiring_dismissals: false,
    expiring_dismissals_count: 0,
    has_recent_auto_downgrade: false,
    recent_auto_downgrade_terms: [],
    recent_auto_downgrade_counts: {},
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("BrandDashboard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockPush.mockClear();
  });

  it("renders empty-state canonical copy when API returns no matches", async () => {
    vi.mocked(listBrandMatches).mockResolvedValue(buildResp({ matches: [] }));

    render(<BrandDashboardClient projectId="proj-1" />);

    await waitFor(() => {
      expect(screen.getByText("No brand matches yet.")).toBeInTheDocument();
    });
    expect(
      screen.getByText("Add brand terms to start monitoring."),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Add brand term").length).toBeGreaterThan(0);
  });

  it("renders match table when API returns matches", async () => {
    vi.mocked(listBrandMatches).mockResolvedValue(
      buildResp({ matches: [MATCH_NEW] }),
    );

    render(<BrandDashboardClient projectId="proj-1" />);

    await waitFor(() => {
      expect(
        screen.getByText("intellibird-lookalike.io"),
      ).toBeInTheDocument();
    });
    expect(screen.queryByText("No brand matches yet.")).not.toBeInTheDocument();
    expect(screen.getByText("Term")).toBeInTheDocument();
    expect(screen.getByText("Matched value")).toBeInTheDocument();
  });

  it("suppression banner hidden unless has_expiring_dismissals=true", async () => {
    vi.mocked(listBrandMatches).mockResolvedValue(
      buildResp({ matches: [] }),
    );
    render(<BrandDashboardClient projectId="proj-1" />);
    await waitFor(() =>
      expect(screen.getByText("No brand matches yet.")).toBeInTheDocument(),
    );
    expect(
      screen.queryByText(/dismissed matches will re-surface/),
    ).not.toBeInTheDocument();
  });

  it("suppression banner renders when has_expiring_dismissals=true", async () => {
    vi.mocked(listBrandMatches).mockResolvedValue(
      buildResp({
        matches: [],
        has_expiring_dismissals: true,
        expiring_dismissals_count: 4,
      }),
    );
    render(<BrandDashboardClient projectId="proj-1" />);
    await waitFor(() =>
      expect(
        screen.getByText(
          /4 dismissed matches will re-surface in the next 7 days\. Review before they return\./,
        ),
      ).toBeInTheDocument(),
    );
  });

  it("noise-downgrade banner hidden unless has_recent_auto_downgrade=true", async () => {
    vi.mocked(listBrandMatches).mockResolvedValue(
      buildResp({ matches: [] }),
    );
    render(<BrandDashboardClient projectId="proj-1" />);
    await waitFor(() =>
      expect(screen.getByText("No brand matches yet.")).toBeInTheDocument(),
    );
    expect(
      screen.queryByText(/auto-downgraded to watch-only/),
    ).not.toBeInTheDocument();
  });

  it("noise-downgrade banner (single term) renders with literal copy", async () => {
    vi.mocked(listBrandMatches).mockResolvedValue(
      buildResp({
        matches: [],
        has_recent_auto_downgrade: true,
        recent_auto_downgrade_terms: ["foo"],
        recent_auto_downgrade_counts: { foo: 42 },
      }),
    );
    render(<BrandDashboardClient projectId="proj-1" />);
    await waitFor(() =>
      expect(
        screen.getByText(
          /Term 'foo' auto-downgraded to watch-only — 42 matches in last 24h\. Review on the Terms tab\./,
        ),
      ).toBeInTheDocument(),
    );
  });

  it("filter bar renders all 4 controls and switching severity triggers refetch", async () => {
    vi.mocked(listBrandMatches).mockResolvedValue(
      buildResp({ matches: [MATCH_NEW] }),
    );
    const user = userEvent.setup();

    render(<BrandDashboardClient projectId="proj-1" />);

    await waitFor(() =>
      expect(vi.mocked(listBrandMatches)).toHaveBeenCalledTimes(1),
    );

    const comboboxes = screen.getAllByRole("combobox");
    // 3 selects on filter bar (+ 1 actions select per row = 4)
    expect(comboboxes.length).toBeGreaterThanOrEqual(3);

    // Switch is visible by label
    expect(screen.getByLabelText("Include dismissed")).toBeInTheDocument();

    // Open severity select (index 0)
    await user.click(comboboxes[0]);
    const highOption = await screen.findByRole("option", { name: "HIGH" });
    await user.click(highOption);

    await waitFor(() =>
      expect(vi.mocked(listBrandMatches)).toHaveBeenCalledWith(
        "proj-1",
        expect.objectContaining({ severity: "high" }),
      ),
    );
  });
});
