/**
 * MatchTable tests — plan 12-08.
 *
 * Covers UI-SPEC §Surface 2 §Match table columns:
 *   - 8-column header shape
 *   - Source chip colour-class dispatch by match_source
 *   - Watchlist row renders signal-amber dot
 *   - Observer role → Actions Select disabled with tooltip
 *   - font-mono applied to matched_value
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

if (
  typeof Element !== "undefined" &&
  !Element.prototype.hasPointerCapture
) {
  Element.prototype.hasPointerCapture = () => false;
  Element.prototype.setPointerCapture = () => {};
  Element.prototype.releasePointerCapture = () => {};
}

vi.mock("sonner", () => ({
  toast: {
    info: vi.fn(),
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
  },
}));

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>(
    "../lib/api",
  );
  return {
    ...actual,
    patchBrandMatch: vi.fn(),
  };
});

import type { BrandMatchRead } from "../lib/api";
import { MatchTable } from "../MatchTable";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const BASE: BrandMatchRead = {
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

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("MatchTable", () => {
  it("renders the 8-column header", () => {
    render(
      <MatchTable matches={[BASE]} isObserver={false} onMatchUpdate={() => {}} />,
    );
    expect(screen.getByText("Term")).toBeInTheDocument();
    expect(screen.getByText("Matched value")).toBeInTheDocument();
    expect(screen.getByText("Source")).toBeInTheDocument();
    expect(screen.getByText("Severity")).toBeInTheDocument();
    expect(screen.getByText("First seen")).toBeInTheDocument();
    expect(screen.getByText("Last seen")).toBeInTheDocument();
    expect(screen.getByText("Status")).toBeInTheDocument();
    expect(screen.getByText("Actions")).toBeInTheDocument();
  });

  it("source chip colour classes dispatch on match_source (dnstwist → signal-amber)", () => {
    const { container } = render(
      <MatchTable
        matches={[{ ...BASE, match_source: "dnstwist" }]}
        isObserver={false}
        onMatchUpdate={() => {}}
      />,
    );
    const chip = container.querySelector(
      ".bg-\\[var\\(--brand-signal\\)\\]\\/20",
    );
    expect(chip).not.toBeNull();
  });

  it("source chip colour classes dispatch on match_source (ct_log → teal mist)", () => {
    const { container } = render(
      <MatchTable
        matches={[{ ...BASE, match_source: "ct_log" }]}
        isObserver={false}
        onMatchUpdate={() => {}}
      />,
    );
    const chip = container.querySelector(".bg-teal-900\\/40");
    expect(chip).not.toBeNull();
  });

  it("source chip colour classes dispatch on match_source (fts → slate muted)", () => {
    const { container } = render(
      <MatchTable
        matches={[{ ...BASE, match_source: "fts" }]}
        isObserver={false}
        onMatchUpdate={() => {}}
      />,
    );
    const chip = container.querySelector(".bg-muted");
    expect(chip).not.toBeNull();
  });

  it("watchlist row renders signal-amber dot in Status column", () => {
    render(
      <MatchTable
        matches={[{ ...BASE, lifecycle_status: "watchlist" }]}
        isObserver={false}
        onMatchUpdate={() => {}}
      />,
    );
    expect(screen.getByTestId("watchlist-dot")).toBeInTheDocument();
    expect(screen.getByLabelText("On watchlist")).toBeInTheDocument();
  });

  it("matched_value renders with font-mono class", () => {
    const { container } = render(
      <MatchTable matches={[BASE]} isObserver={false} onMatchUpdate={() => {}} />,
    );
    const mono = container.querySelector(".font-mono");
    expect(mono).not.toBeNull();
    expect(mono?.textContent).toContain("intellibird-lookalike.io");
  });

  it("Observer → Actions Select disabled", () => {
    render(
      <MatchTable matches={[BASE]} isObserver={true} onMatchUpdate={() => {}} />,
    );
    const combobox = screen.getByRole("combobox", { name: /lifecycle action/i });
    expect(combobox).toBeDisabled();
  });
});
