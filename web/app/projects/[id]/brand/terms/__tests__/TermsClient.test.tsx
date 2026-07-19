/**
 * TermsClient tests - plan 12-09 (UI-SPEC §Surface 5).
 *
 * Coverage:
 *   - Table renders all 7 columns
 *   - In-row mode Switch disabled for Observer with tooltip copy
 *   - Archive Tooltip + aria-label render; window.confirm fires with canonical copy
 *   - Show archived Switch toggles archived-term visibility
 *   - Empty state canonical copy strings render
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// jsdom pointer events polyfill (Radix requirement)
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

vi.mock("../../lib/api", async () => {
  const actual =
    await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return {
    ...actual,
    listBrandTerms: vi.fn(),
    patchBrandTerm: vi.fn(),
    createBrandTerm: vi.fn(),
    previewBrandTerm: vi.fn(),
  };
});

import {
  listBrandTerms,
  patchBrandTerm,
} from "../../lib/api";
import type { BrandTermRead } from "../../lib/api";
import { TermsClient } from "../TermsClient";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const TERM_ACTIVE: BrandTermRead = {
  id: "t1",
  project_id: "proj-1",
  term_type: "keyword",
  value: "IntelliBird",
  mode: "active",
  archived: false,
  high_noise_risk: false,
  created_by: "user-abc-1234567890-xyz-extra",
  created_at: "2026-01-15T10:00:00Z",
  matches_24h: 12,
};

const TERM_ARCHIVED: BrandTermRead = {
  ...TERM_ACTIVE,
  id: "t2",
  value: "oldterm",
  archived: true,
  matches_24h: null,
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("TermsClient", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders empty-state canonical copy when no terms", async () => {
    vi.mocked(listBrandTerms).mockResolvedValue([]);

    render(<TermsClient projectId="proj-1" />);

    await waitFor(() => {
      expect(screen.getByText("No brand terms yet.")).toBeInTheDocument();
    });
    expect(
      screen.getByText(
        "Add a keyword, domain, product name, or person to start monitoring for brand mentions and lookalike domains.",
      ),
    ).toBeInTheDocument();
    // CTA button
    expect(screen.getAllByText("Add brand term").length).toBeGreaterThan(0);
  });

  it("renders the 7-column header and a term row", async () => {
    vi.mocked(listBrandTerms).mockResolvedValue([TERM_ACTIVE]);

    render(<TermsClient projectId="proj-1" />);

    await waitFor(() => {
      expect(screen.getByText("IntelliBird")).toBeInTheDocument();
    });
    // All 7 column headers
    for (const col of [
      "Value",
      "Type",
      "Mode",
      "Matches 24h",
      "Created by",
      "Created at",
      "Actions",
    ]) {
      expect(screen.getByText(col)).toBeInTheDocument();
    }
  });

  it("mode Switch disabled for Observer with canonical tooltip copy", async () => {
    vi.mocked(listBrandTerms).mockResolvedValue([TERM_ACTIVE]);

    render(<TermsClient projectId="proj-1" isObserver />);

    await waitFor(() =>
      expect(screen.getByText("IntelliBird")).toBeInTheDocument(),
    );
    // Switch aria-label "Scan mode" is rendered; disabled state
    const modeSwitch = screen.getByLabelText("Scan mode");
    expect(modeSwitch).toBeDisabled();
    // Hover the disabled-switch wrapper to trigger Radix Tooltip portal render
    const user = userEvent.setup();
    await user.hover(modeSwitch.parentElement!.parentElement!);
    const tooltipCopy = await screen.findAllByText(
      "Observers cannot toggle scan mode.",
    );
    expect(tooltipCopy.length).toBeGreaterThan(0);
  });

  it("archive button renders with Tooltip + fires window.confirm with canonical copy", async () => {
    vi.mocked(listBrandTerms).mockResolvedValue([TERM_ACTIVE]);
    vi.mocked(patchBrandTerm).mockResolvedValue({
      ...TERM_ACTIVE,
      archived: true,
    });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();

    render(<TermsClient projectId="proj-1" />);

    await waitFor(() =>
      expect(screen.getByText("IntelliBird")).toBeInTheDocument(),
    );

    const archiveBtn = screen.getByRole("button", { name: "Archive term" });
    expect(archiveBtn).toBeInTheDocument();

    await user.click(archiveBtn);

    expect(confirmSpy).toHaveBeenCalledWith(
      "Archive term 'IntelliBird'? Existing matches remain; scan cycle skips this term.",
    );
    await waitFor(() => {
      expect(vi.mocked(patchBrandTerm)).toHaveBeenCalledWith(
        "proj-1",
        "t1",
        { archived: true },
      );
    });
  });

  it("Show archived Switch toggles archived-term visibility and refetches", async () => {
    // First call: include_archived=false → only active term
    // Second call: include_archived=true → active + archived
    vi.mocked(listBrandTerms)
      .mockResolvedValueOnce([TERM_ACTIVE])
      .mockResolvedValueOnce([TERM_ACTIVE, TERM_ARCHIVED]);

    const user = userEvent.setup();
    render(<TermsClient projectId="proj-1" />);

    await waitFor(() =>
      expect(screen.getByText("IntelliBird")).toBeInTheDocument(),
    );
    expect(screen.queryByText("oldterm")).not.toBeInTheDocument();

    await user.click(screen.getByLabelText("Show archived"));

    await waitFor(() => {
      expect(screen.getByText("oldterm")).toBeInTheDocument();
    });
    // listBrandTerms called twice - second with include_archived=true
    expect(vi.mocked(listBrandTerms)).toHaveBeenCalledWith("proj-1", true);

    // Archived row renders with opacity-60 on its <tr>
    const archivedRow = screen.getByTestId("term-row-t2");
    expect(archivedRow.className).toMatch(/opacity-60/);
    // And no archive button inside that row
    expect(
      within(archivedRow).queryByRole("button", { name: "Archive term" }),
    ).not.toBeInTheDocument();
  });

  it("hides Add-brand-term button for Observer role", async () => {
    vi.mocked(listBrandTerms).mockResolvedValue([]);

    render(<TermsClient projectId="proj-1" isObserver />);

    await waitFor(() =>
      expect(screen.getByText("No brand terms yet.")).toBeInTheDocument(),
    );
    // No "Add brand term" trigger (empty state CTA is also hidden for Observer)
    expect(screen.queryByText("Add brand term")).not.toBeInTheDocument();
  });
});
