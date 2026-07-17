/**
 * AISuggestionChip tests
 *
 * Covers:
 *   - Pending chip renders yellow variant + Check + X buttons
 *   - On confirm click: optimistic transition to confirmed (green)
 *   - On discard click: optimistic transition to discarded (muted)
 *   - Revert on fetch reject
 *   - Confirmed/discarded chips render correct classes, no action buttons
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AISuggestionChip } from "./AISuggestionChip";
import type { AISuggestion } from "./AISuggestionChip";

// jsdom pointer events polyfill (Radix Tooltip requirement)
if (typeof Element !== "undefined" && !Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = () => false;
  Element.prototype.setPointerCapture = () => {};
  Element.prototype.releasePointerCapture = () => {};
}

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}));

const PENDING_SUGGESTION: AISuggestion = {
  id: "sug-001",
  entity_value: "CVE-2024-1234",
  entity_type: "cve",
  status: "pending",
};

const CONFIRMED_SUGGESTION: AISuggestion = {
  id: "sug-002",
  entity_value: "T1059",
  entity_type: "attack",
  status: "confirmed",
};

const DISCARDED_SUGGESTION: AISuggestion = {
  id: "sug-003",
  entity_value: "APT28",
  entity_type: "actor",
  status: "discarded",
};

describe("AISuggestionChip — pending state", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders yellow chip with entity value and type", () => {
    render(<AISuggestionChip suggestion={PENDING_SUGGESTION} />);
    const chip = screen.getByTestId("suggestion-chip");
    expect(chip).toHaveAttribute("data-status", "pending");
    expect(chip.className).toContain("bg-yellow-500/10");
    expect(chip.className).toContain("text-yellow-300");
    expect(screen.getByText("CVE-2024-1234")).toBeTruthy();
    expect(screen.getByText("cve")).toBeTruthy();
  });

  it("renders Confirm and Discard aria-label buttons for pending chip", () => {
    render(<AISuggestionChip suggestion={PENDING_SUGGESTION} />);
    expect(screen.getByLabelText("Confirm suggestion")).toBeTruthy();
    expect(screen.getByLabelText("Discard suggestion")).toBeTruthy();
  });

  it("transitions to confirmed on Confirm click (optimistic)", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    );

    render(<AISuggestionChip suggestion={PENDING_SUGGESTION} />);
    const confirmBtn = screen.getByLabelText("Confirm suggestion");
    await user.click(confirmBtn);

    await waitFor(() => {
      const chip = screen.getByTestId("suggestion-chip");
      expect(chip).toHaveAttribute("data-status", "confirmed");
      expect(chip.className).toContain("bg-green-500/10");
    });

    expect(fetchSpy).toHaveBeenCalledWith(
      `/api/ai/suggestions/sug-001/confirm`,
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("transitions to discarded on Discard click (optimistic)", async () => {
    const user = userEvent.setup();
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    );

    render(<AISuggestionChip suggestion={PENDING_SUGGESTION} />);
    const discardBtn = screen.getByLabelText("Discard suggestion");
    await user.click(discardBtn);

    await waitFor(() => {
      const chip = screen.getByTestId("suggestion-chip");
      expect(chip).toHaveAttribute("data-status", "discarded");
      expect(chip.className).toContain("bg-muted");
    });
  });

  it("reverts to pending and shows toast.error on fetch reject (confirm)", async () => {
    const user = userEvent.setup();
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new Error("Network error"));

    const { toast } = await import("sonner");

    render(<AISuggestionChip suggestion={PENDING_SUGGESTION} />);
    const confirmBtn = screen.getByLabelText("Confirm suggestion");
    await user.click(confirmBtn);

    await waitFor(() => {
      const chip = screen.getByTestId("suggestion-chip");
      // Should revert to pending
      expect(chip).toHaveAttribute("data-status", "pending");
    });

    expect(toast.error).toHaveBeenCalledWith("Could not confirm suggestion.");
  });

  it("reverts to pending and shows toast.error on fetch reject (discard)", async () => {
    const user = userEvent.setup();
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new Error("Network error"));

    const { toast } = await import("sonner");

    render(<AISuggestionChip suggestion={PENDING_SUGGESTION} />);
    const discardBtn = screen.getByLabelText("Discard suggestion");
    await user.click(discardBtn);

    await waitFor(() => {
      const chip = screen.getByTestId("suggestion-chip");
      expect(chip).toHaveAttribute("data-status", "pending");
    });

    expect(toast.error).toHaveBeenCalledWith("Could not discard suggestion.");
  });
});

describe("AISuggestionChip — confirmed state", () => {
  it("renders green chip with no action buttons", () => {
    render(<AISuggestionChip suggestion={CONFIRMED_SUGGESTION} />);
    const chip = screen.getByTestId("suggestion-chip");
    expect(chip).toHaveAttribute("data-status", "confirmed");
    expect(chip.className).toContain("bg-green-500/10");
    expect(chip.className).toContain("text-green-300");
    expect(screen.queryByLabelText("Confirm suggestion")).toBeNull();
    expect(screen.queryByLabelText("Discard suggestion")).toBeNull();
  });
});

describe("AISuggestionChip — discarded state", () => {
  it("renders muted chip with no action buttons", () => {
    render(<AISuggestionChip suggestion={DISCARDED_SUGGESTION} />);
    const chip = screen.getByTestId("suggestion-chip");
    expect(chip).toHaveAttribute("data-status", "discarded");
    expect(chip.className).toContain("bg-muted");
    expect(chip.className).toContain("text-muted-foreground");
    expect(screen.queryByLabelText("Confirm suggestion")).toBeNull();
    expect(screen.queryByLabelText("Discard suggestion")).toBeNull();
  });
});
