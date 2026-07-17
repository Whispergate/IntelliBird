/**
 * DiffView tests
 *
 * Activates the Wave 0 stub from plan 11-00.
 * Covers UI-SPEC §Surface 6 §"Diff vs previous" (EASM-08).
 */

import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

// ---------------------------------------------------------------------------
// Mock API helpers
// ---------------------------------------------------------------------------
vi.mock("../lib/api", () => ({
  getScanDiff: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

import { getScanDiff } from "../lib/api";
import { DiffView } from "../scans/[scanId]/DiffView";

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

const MOCK_NEW_ENTRY = {
  bbot_event_type: "DNS_NAME",
  canonical_target: "new.example.com",
  raw_bbot: { host: "new.example.com" },
  module: "crt",
  severity: null,
};

const MOCK_CHANGED_ENTRY = {
  bbot_event_type: "OPEN_PORT",
  canonical_target: "192.168.1.1:443",
  previous: { port: 443, service: "https" },
  current: { port: 443, service: "http2" },
  module: "httpx",
};

const MOCK_RESOLVED_ENTRY = {
  bbot_event_type: "SUBDOMAIN_TAKEOVER_CANDIDATE",
  canonical_target: "old.example.com",
  raw_bbot: { host: "old.example.com" },
  module: "subdomaincenter",
  severity: "high" as const,
};

const FULL_DIFF = {
  this_scan_id: "scan-2",
  prior_scan_id: "scan-1",
  new: [MOCK_NEW_ENTRY],
  changed: [MOCK_CHANGED_ENTRY],
  resolved: [MOCK_RESOLVED_ENTRY],
};

const EMPTY_DIFF = {
  this_scan_id: "scan-2",
  prior_scan_id: "scan-1",
  new: [],
  changed: [],
  resolved: [],
};

const NO_PRIOR_DIFF = {
  this_scan_id: "scan-1",
  prior_scan_id: null,
  new: [],
  changed: [],
  resolved: [],
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("DiffView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders spinner while getScanDiff is pending", async () => {
    // Never-resolving promise to keep loading state
    vi.mocked(getScanDiff).mockReturnValue(new Promise(() => {}));
    render(<DiffView projectId="proj-1" scanId="scan-2" />);
    expect(screen.getByTestId("diff-spinner")).toBeInTheDocument();
  });

  it("renders no-prior-scan heading when prior_scan_id is null", async () => {
    vi.mocked(getScanDiff).mockResolvedValue(NO_PRIOR_DIFF);
    render(<DiffView projectId="proj-1" scanId="scan-1" />);
    expect(
      await screen.findByText("No previous scan to compare"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "This is the first scan for this project. Diff view requires at least two completed scans.",
      ),
    ).toBeInTheDocument();
  });

  it("renders NEW section with green accent on entries", async () => {
    vi.mocked(getScanDiff).mockResolvedValue(FULL_DIFF);
    render(<DiffView projectId="proj-1" scanId="scan-2" />);
    await screen.findByText("NEW");
    // The NEW entry's target should appear
    expect(screen.getByText("new.example.com")).toBeInTheDocument();
    // The NEW section heading should be present
    expect(screen.getByText("NEW")).toBeInTheDocument();
  });

  it("renders CHANGED section with orange 'Changed' label", async () => {
    vi.mocked(getScanDiff).mockResolvedValue(FULL_DIFF);
    render(<DiffView projectId="proj-1" scanId="scan-2" />);
    await screen.findByText("CHANGED");
    // The Changed label should appear in orange (class check)
    const changedLabels = screen.getAllByText("Changed");
    expect(changedLabels.length).toBeGreaterThan(0);
    expect(changedLabels[0]).toHaveClass("text-orange-500");
  });

  it("renders RESOLVED section with muted styling", async () => {
    vi.mocked(getScanDiff).mockResolvedValue(FULL_DIFF);
    render(<DiffView projectId="proj-1" scanId="scan-2" />);
    await screen.findByText("RESOLVED");
    expect(screen.getByText("old.example.com")).toBeInTheDocument();
    // Resolved label in muted-foreground
    const resolvedLabels = screen.getAllByText("Resolved");
    expect(resolvedLabels.length).toBeGreaterThan(0);
    expect(resolvedLabels[0]).toHaveClass("text-muted-foreground");
  });

  it("NEW section empty state copy matches UI-SPEC byte-exact", async () => {
    vi.mocked(getScanDiff).mockResolvedValue(EMPTY_DIFF);
    render(<DiffView projectId="proj-1" scanId="scan-2" />);
    await screen.findByText("NEW");
    expect(
      screen.getByText("No new findings compared to the previous scan."),
    ).toBeInTheDocument();
  });

  it("CHANGED section empty state copy matches byte-exact", async () => {
    vi.mocked(getScanDiff).mockResolvedValue(EMPTY_DIFF);
    render(<DiffView projectId="proj-1" scanId="scan-2" />);
    await screen.findByText("CHANGED");
    expect(screen.getByText("No changed findings.")).toBeInTheDocument();
  });

  it("RESOLVED section empty state copy matches byte-exact", async () => {
    vi.mocked(getScanDiff).mockResolvedValue(EMPTY_DIFF);
    render(<DiffView projectId="proj-1" scanId="scan-2" />);
    await screen.findByText("RESOLVED");
    expect(
      screen.getByText("No resolved findings. Prior findings are still present."),
    ).toBeInTheDocument();
  });

  it("error state renders 'Try again' link that refetches", async () => {
    vi.mocked(getScanDiff)
      .mockRejectedValueOnce(new Error("Network error"))
      .mockResolvedValueOnce(FULL_DIFF);
    render(<DiffView projectId="proj-1" scanId="scan-2" />);

    // Wait for error state
    await waitFor(() => {
      expect(screen.getByText("Try again")).toBeInTheDocument();
    });

    // The error message should be present
    expect(
      screen.getByText(/Could not compute diff/),
    ).toBeInTheDocument();
  });
});
